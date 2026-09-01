"""PitchRoast audit service — JSON sanitisation, LLM integration, retry logic."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Optional

import httpx

logger = logging.getLogger("pitchroast")

from app.schemas import (
    AuditErrorResponse,
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
    """Raised when a model endpoint is unreachable or returns a gateway error."""


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
# OpenRouter API call — prioritized model pool with immediate failover
# ---------------------------------------------------------------------------

# Ordered by priority: fastest / highest-uptime free models first
MODEL_POOL: tuple[str, ...] = (
    "openrouter/free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "google/gemini-2.0-flash-exp:free",
    "google/gemini-flash-1.5:free",
)

BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT = 30.0
MAX_RETRIES = 3

# HTTP status codes that indicate the provider is down — fail over immediately
GATEWAY_ERRORS = {502, 503, 504, 520, 521, 522}


async def _call_openrouter(
    messages: list[dict[str, str]],
    model: str,
    api_key: str = "",
) -> str:
    """
    Call OpenRouter for a single model. Returns the raw assistant content string.

    Raises:
        ModelUnavailableError on gateway errors (502/503/504/520-522) or >= 500.
        RateLimitError on HTTP 429.
        httpx.HTTPStatusError on other non-2xx responses.
    """
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

    logger.info("[OpenRouter] POST model=%s msg_count=%d", model, len(messages))

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.post(
            f"{BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
        )

    logger.info(
        "[OpenRouter] model=%s status=%d content_length=%d",
        model,
        response.status_code,
        len(response.content),
    )

    # Log full response body on errors for debugging
    if response.status_code >= 400:
        try:
            body = response.json()
            logger.error(
                "[OpenRouter] model=%s ERROR body=%s",
                model,
                json.dumps(body, indent=2)[:1000],
            )
        except Exception:
            logger.error(
                "[OpenRouter] model=%s ERROR raw=%s",
                model,
                response.text[:500],
            )

    # Immediate failover on gateway errors
    if response.status_code in GATEWAY_ERRORS:
        raise ModelUnavailableError(
            f"Model {model} returned HTTP {response.status_code} (gateway error)"
        )

    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", "60"))
        raise RateLimitError(retry_after=retry_after)

    if response.status_code >= 500:
        raise ModelUnavailableError(
            f"Model {model} returned HTTP {response.status_code}"
        )

    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Mock LLM safety hatch (MOCK_LLM=true)
# ---------------------------------------------------------------------------

MOCK_RESPONSES: dict[str, dict[str, Any]] = {
    "techcrunch": {
        "persona": "TechCrunch Sarah",
        "persona_avatar": "👩‍💻",
        "roast": (
            "Look, I've seen a thousand pitches this week, and this one blends right into the pile. "
            "You lead with 'revolutionary' instead of traction. Where's the ARR? The user count? "
            "The waitlist signups? Without numbers, this is just noise. "
            "I'd delete this in 3 seconds — which is exactly what I did."
        ),
        "scores": [
            {"name": "Clarity", "score": 3, "feedback": "Hook is buried under buzzwords.", "suggestion": "Lead with your traction metric in sentence one."},
            {"name": "Specificity", "score": 2, "feedback": "Zero concrete data points.", "suggestion": "Add ARR, user count, or growth rate."},
            {"name": "Buzzword Density", "score": 1, "feedback": "Revolutionary, synergy, cutting-edge — the holy trinity of nothing.", "suggestion": "Replace every buzzword with a number."},
            {"name": "Length", "score": 5, "feedback": "Length is fine, but the substance isn't.", "suggestion": "Cut 50% of the words, double the data."},
            {"name": "Relevance", "score": 4, "feedback": "On-beat for TC, but generic.", "suggestion": "Reference a recent article or competitive landscape."},
            {"name": "Readability", "score": 6, "feedback": "Grammatically fine, but soulless.", "suggestion": "Use shorter sentences and active voice."},
        ],
        "overall_score": 3.5,
        "redlines": [
            {"original": "revolutionary AI platform", "replacement": "AI onboarding tool", "reason": "Buzzword — name the product category instead."},
            {"original": "disrupt the industry", "replacement": "cut SaaS onboarding time by 40%", "reason": "Vague claim — replace with a measurable outcome."},
            {"original": "cutting-edge technology", "replacement": "transformer-based NLP pipeline", "reason": "Generic filler — be specific about the tech."},
        ],
        "rewritten_pitch": (
            "Hi — I'm the founder of EngageAI. We reduce SaaS onboarding time by 40% using AI-assisted "
            "workflows. We hit $2M ARR in 8 months with 150% net revenue retention. "
            "Our 12 design partners include two YC W24 companies. Can I send a 2-min demo?"
        ),
        "model_used": "mock",
    },
    "forbes": {
        "persona": "Forbes Marcus",
        "persona_avatar": "📰",
        "roast": (
            "This pitch reads like it was generated by a buzzword committee. 'Synergy'? 'Ecosystem'? "
            "Where's the business case? What's the TAM? Who's writing the check, and what's the ROI? "
            "I ghost pitches like this every morning before coffee."
        ),
        "scores": [
            {"name": "Clarity", "score": 2, "feedback": "No clear value proposition.", "suggestion": "Open with the business outcome, not the technology."},
            {"name": "Specificity", "score": 1, "feedback": "Completely devoid of metrics.", "suggestion": "Include market size, revenue, or customer logos."},
            {"name": "Buzzword Density", "score": 1, "feedback": "Maximum buzzword saturation.", "suggestion": "Rewrite without a single jargon term."},
            {"name": "Length", "score": 6, "feedback": "Appropriate length for an exec summary.", "suggestion": "Keep it, but fill with substance."},
            {"name": "Relevance", "score": 3, "feedback": "Enterprise angle is there, but buried.", "suggestion": "Lead with enterprise buyer pain point."},
            {"name": "Readability", "score": 5, "feedback": "Readable but generic.", "suggestion": "Use executive-level language."},
        ],
        "overall_score": 3.0,
        "redlines": [
            {"original": "synergies across the enterprise landscape", "replacement": "reduced onboarding costs by 40% for enterprise clients", "reason": "Replace jargon with business impact."},
            {"original": "explosive growth", "replacement": "$2M ARR with 150% NRR", "reason": "Vague growth claim — use actual numbers."},
        ],
        "rewritten_pitch": (
            "Dear Marcus — EngageAI helps enterprise SaaS teams cut onboarding time by 40%, saving an "
            "average of $120K per customer. We've reached $2M ARR with 150% net revenue retention. "
            "Two YC W24 companies are design partners. Would a 15-min briefing be useful?"
        ),
        "model_used": "mock",
    },
    "the_verge": {
        "persona": "The Verge Priya",
        "persona_avatar": "📱",
        "roast": (
            "Okay, I've read this three times and I still don't know what your product actually IS. "
            "Is it an app? A platform? A dashboard? You say 'AI-powered' like that explains something. "
            "Show me a screenshot. Tell me what it feels like to USE it. This pitch is all hype, zero product."
        ),
        "scores": [
            {"name": "Clarity", "score": 2, "feedback": "Product description is completely absent.", "suggestion": "Explain what the product does in plain English."},
            {"name": "Specificity", "score": 2, "feedback": "No product details whatsoever.", "suggestion": "Include a product demo link or screenshot."},
            {"name": "Buzzword Density", "score": 1, "feedback": "Every other word is 'AI' or 'revolutionary'.", "suggestion": "Describe the product like you're explaining it to a friend."},
            {"name": "Length", "score": 5, "feedback": "Fine length, wrong content.", "suggestion": "Use the space to show the product."},
            {"name": "Relevance", "score": 3, "feedback": "Could be a Verge story if you showed the product.", "suggestion": "Lead with the user experience."},
            {"name": "Readability", "score": 6, "feedback": "Clear writing, empty substance.", "suggestion": "Shorter sentences, concrete examples."},
        ],
        "overall_score": 3.2,
        "redlines": [
            {"original": "revolutionary AI-powered platform", "replacement": "AI onboarding assistant for SaaS", "reason": "Describe the product category, not the hype."},
            {"original": "leverage cutting-edge technology", "replacement": "uses a chat interface inside your product", "reason": "Tell me what it looks like to use."},
        ],
        "rewritten_pitch": (
            "Hey — EngageAI is an in-app onboarding assistant that uses AI to walk new users through "
            "your product. Think Intercom, but it actually learns from user behavior. "
            "We've cut onboarding time by 40% for 12 design partners. Want a 2-min demo?"
        ),
        "model_used": "mock",
    },
    "gulf_news": {
        "persona": "Gulf News Fatima",
        "persona_avatar": "🌍",
        "roast": (
            "Another Western-centric pitch with zero mention of the MENA region. You claim 'global impact' "
            "but can't name a single market outside the US. If you're pitching to Gulf News, tell me "
            "about Dubai, Riyadh, or Abu Dhabi. What's your regional strategy? Who are your MENA partners?"
        ),
        "scores": [
            {"name": "Clarity", "score": 4, "feedback": "The product is vaguely clear, but regional context is missing.", "suggestion": "Add MENA-specific use cases."},
            {"name": "Specificity", "score": 2, "feedback": "No regional data or partners.", "suggestion": "Name Gulf-region customers or expansion plans."},
            {"name": "Buzzword Density", "score": 2, "feedback": "Heavy jargon, no regional grounding.", "suggestion": "Replace global claims with regional evidence."},
            {"name": "Length", "score": 5, "feedback": "Acceptable, but wasted on generic claims.", "suggestion": "Use the space for MENA-specific content."},
            {"name": "Relevance", "score": 2, "feedback": "Zero relevance to Gulf News readers.", "suggestion": "Mention MENA expansion, Dubai office, or regional partnerships."},
            {"name": "Readability", "score": 6, "feedback": "Clear, but tone-deaf to the audience.", "suggestion": "Address the regional audience directly."},
        ],
        "overall_score": 3.5,
        "redlines": [
            {"original": "disrupt the industry", "replacement": "expand into the UAE and Saudi markets", "reason": "Generic claim — make it regionally relevant."},
            {"original": "explosive growth", "replacement": "partnerships with 3 Dubai-based SaaS companies", "reason": "Replace vague growth with regional evidence."},
        ],
        "rewritten_pitch": (
            "Dear Fatima — EngageAI is expanding into the UAE market with partnerships with 3 Dubai-based "
            "SaaS companies. We reduce onboarding time by 40% and have seen 200% growth in MENA inquiries "
            "this quarter. Our Dubai office opens in Q1. Can I share our regional expansion deck?"
        ),
        "model_used": "mock",
    },
    "roastbot": {
        "persona": "RoastBot",
        "persona_avatar": "🔥",
        "roast": (
            "OH BOY, another pitch that reads like a buzzword cookie-cutter factory exploded. "
            "'Revolutionary'? 'Game-changing'? 'Synergy'? I've got a bingo card and you just filled every square. "
            "This pitch is the literary equivalent of a participation trophy — it tries so hard and accomplishes nothing. "
            "I've seen better copy on a bathroom wall. At least that has useful information."
        ),
        "scores": [
            {"name": "Clarity", "score": 1, "feedback": "Clear as mud. What does this product DO?", "suggestion": "Explain in one sentence what you sell."},
            {"name": "Specificity", "score": 0, "feedback": "Zero numbers. Zero names. Zero substance.", "suggestion": "Literally any data point would help."},
            {"name": "Buzzword Density", "score": 0, "feedback": "This pitch IS a buzzword.", "suggestion": "Delete the whole thing and start over."},
            {"name": "Length", "score": 4, "feedback": "Too long for zero content.", "suggestion": "If you can't fill 200 words with substance, write 50."},
            {"name": "Relevance", "score": 2, "feedback": "Relevant to nobody.", "suggestion": "Pick a specific person and write to them."},
            {"name": "Readability", "score": 5, "feedback": "Technically grammatical. That's the nicest thing I can say.", "suggestion": "Shorter. Sharper. Funnier."},
        ],
        "overall_score": 2.0,
        "redlines": [
            {"original": "revolutionary AI-powered platform", "replacement": "a thing that does a thing", "reason": "Your description is equally vague but shorter."},
            {"original": "disrupt the way businesses handle customer engagement", "replacement": "helps companies talk to their customers", "reason": "I translated it from BS to English."},
            {"original": "leveraging cutting-edge technology to create synergies", "replacement": "using software to make money", "reason": "That's what all of you mean anyway."},
            {"original": "across the enterprise landscape", "replacement": "", "reason": "This phrase has never added value to any sentence in history."},
        ],
        "rewritten_pitch": (
            "Hi — I'm [Name] from [Company]. We help SaaS teams cut onboarding time by 40%. "
            "We have $2M ARR and 12 design partners. Here's a 2-min demo: [link]. "
            "Interested? If not, no hard feelings. If yes, let's talk."
        ),
        "model_used": "mock",
    },
}


def _build_mock_response(persona: str, pitch_text: str) -> PitchAuditResponse:
    """Build a realistic mock PitchAuditResponse for demo/offline mode."""
    mock = MOCK_RESPONSES.get(persona, MOCK_RESPONSES["roastbot"])
    # Use the persona labels for display
    label, avatar = PERSONA_LABELS.get(persona, ("RoastBot", "🔥"))
    mock["persona"] = label
    mock["persona_avatar"] = avatar
    mock["model_used"] = "mock"
    return PitchAuditResponse(**mock)


# ---------------------------------------------------------------------------
# Main audit function — resilient multi-model failover
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
    Audit a pitch: build prompts, call LLM with model pool failover, parse, validate.

    Model pool strategy:
      - Iterates through MODEL_POOL in priority order
      - On gateway errors (502/503/504/520-522): immediate failover, no retry
      - On rate limits (429): retry with exponential backoff per model
      - On parse errors: retry up to MAX_RETRIES per model
      - Falls through to next model on any exhausted retry budget

    MOCK_LLM=true: returns a realistic mock response without API calls.
    """
    # ---- Demo safety hatch ----
    if os.environ.get("MOCK_LLM", "").lower() == "true":
        return _build_mock_response(persona, pitch_text)

    # ---- Validate request ----
    request = PitchRequest(
        pitch_text=pitch_text,
        persona=persona,
        company_name=company_name,
        target_publication=target_publication,
        campaign_angle=campaign_angle,
    )

    # ---- Build prompts ----
    persona_prompt = PERSONA_PROMPTS[request.persona.value]
    system_msg = SYSTEM_PROMPT_TEMPLATE.format(persona_prompt=persona_prompt, response_schema="")
    optional_ctx = _build_optional_context(request)
    user_msg = USER_MESSAGE_TEMPLATE.format(
        pitch_text=request.pitch_text, optional_context=optional_ctx
    )
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]

    logger.info(
        "[audit_pitch] persona=%s pitch_length=%d company=%s",
        persona,
        len(pitch_text),
        company_name,
    )
    logger.info("[audit_pitch] model_pool=%s", list(MODEL_POOL))

    # ---- Iterate through model pool with per-model retries ----
    last_error: Exception | None = None

    for model in MODEL_POOL:
        logger.info("[audit_pitch] trying model=%s", model)
        for attempt in range(MAX_RETRIES + 1):
            try:
                raw_content = await _call_openrouter(
                    messages, model=model, api_key=api_key
                )
                parsed = sanitize_llm_response(raw_content)
                if parsed is None:
                    raise ParseError(
                        f"Could not parse LLM output from {model}: {raw_content[:200]}"
                    )

                # Inject model_used if missing
                if "model_used" not in parsed:
                    parsed["model_used"] = model

                return PitchAuditResponse(**parsed)

            except RateLimitError as e:
                # Rate limited: retry with backoff, then move to next model
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = min(2**attempt, 8)
                    await asyncio.sleep(wait)
                    continue
                break  # retries exhausted → next model

            except ParseError as e:
                # Parse error: retry (LLM output may be non-deterministic)
                last_error = e
                if attempt < MAX_RETRIES:
                    continue
                break  # retries exhausted → next model

            except ModelUnavailableError as e:
                # Gateway error: immediate failover, no retry
                logger.warning("[audit_pitch] model=%s GATEWAY ERROR: %s", model, e)
                last_error = e
                break  # → next model immediately

    # All models exhausted
    logger.error(
        "[audit_pitch] ALL MODELS EXHAUSTED. last_error=%s",
        last_error,
    )
    if isinstance(last_error, RateLimitError):
        raise last_error
    raise last_error or ModelUnavailableError("All models in pool exhausted.")
