"""PitchRoast audit service — JSON sanitisation, LLM integration, retry logic."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import httpx

from app.schemas import (
    AuditErrorResponse,
    EditorPersona,
    PitchAuditResponse,
    PitchRequest,
)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class RateLimitError(Exception):
    """Raised when OpenRouter returns HTTP 429."""

    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s.")


class ModelUnavailableError(Exception):
    """Raised when all models fail after retries."""


class ParseError(Exception):
    """Raised when LLM output cannot be parsed into valid JSON."""


# ---------------------------------------------------------------------------
# LLM response sanitiser (multi-stage fallback)
# ---------------------------------------------------------------------------


def sanitize_llm_response(raw: str) -> Optional[dict[str, Any]]:
    """
    Multi-stage fallback parser for LLM JSON output.
    Returns parsed dict or None if all stages fail.
    """
    if not raw or not raw.strip():
        return None

    # Stage 1: Direct parse (model returned clean JSON)
    try:
        result = json.loads(raw.strip())
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    # Stage 2: Strip markdown code fences (```json ... ``` or ``` ... ```)
    fenced = re.sub(r"```(?:json)?\s*\n?(.*?)\n?\s*```", r"\1", raw, flags=re.DOTALL)
    try:
        result = json.loads(fenced.strip())
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    # Stage 3: Find the first { ... } block via bracket matching
    start = raw.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        result = json.loads(raw[start : i + 1])
                        if isinstance(result, dict):
                            return result
                    except (json.JSONDecodeError, TypeError):
                        break

    return None


# ---------------------------------------------------------------------------
# Persona prompt definitions
# ---------------------------------------------------------------------------

PERSONA_PROMPTS: dict[str, str] = {
    "techcrunch": (
        "You are Sarah Chen, a senior editor at TechCrunch covering startups and venture capital. "
        "You've read 10,000 pitches this year. You're tired of pitches that don't lead with traction "
        "metrics, founders who say 'revolutionary' without explaining what the product actually does, "
        "and PR fluff that wastes your time. Your style: Direct, slightly dry, metrics-obsessed. "
        "Tone: Professional but no-nonsense."
    ),
    "forbes": (
        "You are Marcus Williams, a leadership and enterprise technology editor at Forbes. "
        "You've ghosted on pitches that use jargon without explaining business impact, claim "
        "'market disruption' without market sizing, and address you as 'Dear Editor' with no "
        "personalization. Your style: Formal, business-impact focused. Tone: Authoritative and polished."
    ),
    "the_verge": (
        "You are Priya Kapoor, a consumer tech product reviewer at The Verge. "
        "You're exhausted by pitches that don't explain what the product is in the first paragraph, "
        "B2B jargon in consumer product pitches, and claims of being 'first to market' without evidence. "
        "Your style: Product-obsessed, witty, and visually-minded. Tone: Conversational and occasionally snarky."
    ),
    "gulf_news": (
        "You are Fatima Al-Rashid, a business and technology correspondent covering the UAE and MENA "
        "region for Gulf News / Khaleej Times. You're turned off by pitches with zero regional context, "
        "Western-centric framing that ignores MENA markets, and claims of 'global impact' with no "
        "regional evidence. Your style: Globally aware, regionally grounded. Tone: Professional and direct."
    ),
    "roastbot": (
        "You are RoastBot, a maximally unfiltered, brutally honest pitch critic. You have zero patience "
        "for any buzzwords, pitches longer than 100 words that could be said in 30, and anything that "
        "doesn't get to the point in the first sentence. Your style: Maximum roasting with humor, sarcasm, "
        "and vivid metaphors. Tone: Unhinged, hilarious, devastating."
    ),
}

PERSONA_LABELS: dict[str, tuple[str, str]] = {
    "techcrunch": ("TechCrunch Sarah", "👩‍💻"),
    "forbes": ("Forbes Marcus", "📰"),
    "the_verge": ("The Verge Priya", "📱"),
    "gulf_news": ("Gulf News Fatima", "🌍"),
    "roastbot": ("RoastBot", "🔥"),
}

SYSTEM_PROMPT_TEMPLATE = """You are simulating a specific editor at a publication. You MUST return your response as a SINGLE valid JSON object — no markdown, no code fences, no commentary outside the JSON.

The JSON must strictly follow this schema:
{{
  "persona": "string — display name of the persona",
  "persona_avatar": "string — emoji for the persona",
  "roast": "string — your candid roast of the pitch",
  "scores": [
    {{"name": "Clarity", "score": 0-10, "feedback": "string", "suggestion": "string"}},
    {{"name": "Specificity", "score": 0-10, "feedback": "string", "suggestion": "string"}},
    {{"name": "Buzzword Density", "score": 0-10, "feedback": "string", "suggestion": "string"}},
    {{"name": "Length", "score": 0-10, "feedback": "string", "suggestion": "string"}},
    {{"name": "Relevance", "score": 0-10, "feedback": "string", "suggestion": "string"}},
    {{"name": "Readability", "score": 0-10, "feedback": "string", "suggestion": "string"}}
  ],
  "overall_score": 0.0-10.0,
  "redlines": [{{"original": "string", "replacement": "string", "reason": "string"}}],
  "rewritten_pitch": "string — complete rewritten version"
}}

Scoring rules:
- Clarity (25%): Is the hook immediately obvious in the first sentence?
- Specificity (20%): Concrete numbers, names, dates, or outcomes?
- Buzzword Density (15%): 10 = zero buzzwords, 0 = entirely buzzwords
- Length (10%): 10 = under 150 words, 0 = over 300 words
- Relevance (20%): Does it match the editor's beat?
- Readability (10%): Clear, professional, active voice?

## Persona Instructions

{persona_prompt}

Return ONLY the JSON object. No markdown fences. No extra text.
"""

USER_MESSAGE_TEMPLATE = """Audit this cold PR pitch:

--- PITCH START ---
{pitch_text}
--- PITCH END ---

{optional_context}

Respond with a single JSON object matching the required schema. No markdown fences. No extra text."""


# ---------------------------------------------------------------------------
# Helper: build optional context block
# ---------------------------------------------------------------------------


def _build_optional_context(request: PitchRequest) -> str:
    parts = []
    if request.company_name:
        parts.append(f"Company: {request.company_name}")
    if request.target_publication:
        parts.append(f"Target publication: {request.target_publication}")
    if request.campaign_angle:
        parts.append(f"Campaign angle: {request.campaign_angle}")
    return "\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# OpenRouter API call
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
FALLBACK_MODEL = "openrouter/free"
BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT = 30.0
MAX_RETRIES = 3


async def _call_openrouter(
    messages: list[dict[str, str]],
    model: str = DEFAULT_MODEL,
    api_key: str = "",
) -> dict[str, Any]:
    """Call OpenRouter and return the parsed assistant message content."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://pitchroast.app",
        "X-Title": "PitchRoast",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2048,
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(f"{BASE_URL}/chat/completions", json=payload, headers=headers)

    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", "60"))
        raise RateLimitError(retry_after=retry_after)

    if response.status_code >= 500:
        raise ModelUnavailableError(f"OpenRouter returned {response.status_code}")

    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Main audit function
# ---------------------------------------------------------------------------


async def audit_pitch(
    pitch_text: str,
    persona: str,
    company_name: str | None = None,
    target_publication: str | None = None,
    campaign_angle: str | None = None,
    api_key: str = "",
) -> PitchAuditResponse:
    """
    Audit a pitch: build prompts, call LLM, parse response, validate with Pydantic.
    Retries on rate-limit and parse errors per the defensive engineering plan.
    """
    request = PitchRequest(
        pitch_text=pitch_text,
        persona=persona,
        company_name=company_name,
        target_publication=target_publication,
        campaign_angle=campaign_angle,
    )

    persona_prompt = PERSONA_PROMPTS[request.persona.value]
    system_msg = SYSTEM_PROMPT_TEMPLATE.format(persona_prompt=persona_prompt, response_schema="")
    optional_ctx = _build_optional_context(request)
    user_msg = USER_MESSAGE_TEMPLATE.format(pitch_text=request.pitch_text, optional_context=optional_ctx)

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]

    last_error: Exception | None = None

    # Attempt with primary model, then fallback
    for model in (DEFAULT_MODEL, FALLBACK_MODEL):
        for attempt in range(MAX_RETRIES + 1):
            try:
                raw_content = await _call_openrouter(messages, model=model, api_key=api_key)
                parsed = sanitize_llm_response(raw_content)
                if parsed is None:
                    raise ParseError(f"Could not parse LLM output: {raw_content[:200]}")

                # Inject model_used if missing
                if "model_used" not in parsed:
                    parsed["model_used"] = model

                return PitchAuditResponse(**parsed)

            except RateLimitError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    import asyncio
                    wait = min(2**attempt, 8)
                    await asyncio.sleep(wait)
                    continue
                # All retries exhausted for this model, try next model
                break

            except ParseError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    continue
                break

            except ModelUnavailableError as e:
                last_error = e
                break

    # All models and retries exhausted
    if isinstance(last_error, RateLimitError):
        raise last_error
    raise last_error or ModelUnavailableError("All models failed.")
