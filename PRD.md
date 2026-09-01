# PitchRoast — Product Requirements Document

> **Version:** 1.0.0
> **Date:** September 1, 2026
> **Status:** Draft — Awaiting sign-off before code generation begins
> **Author:** Buffy (AI Systems Architect) × Human (Product Lead)

---

## 1. Executive Summary & Value Proposition

### Problem

Cold PR pitches are notoriously ineffective. Journalists and editors report that **70–80% of unsolicited pitches are deleted without being read**. Common failures include buzzword-laden language, vague metrics, irrelevant beats, and excessive length. PR professionals lack a fast, cost-effective way to pressure-test pitches before sending.

### Solution

**PitchRoast** is an AI-powered pitch auditing tool that simulates cynical, well-known tech and business editors to:

1. **Roast** a cold PR pitch with persona-specific feedback
2. **Score** it across six evaluation dimensions (0–10 each, plus weighted overall)
3. **Redline** the text with inline tracked-change-style edits
4. **Rewrite** a stronger version of the pitch

### Value Proposition

| Stakeholder | Benefit |
|---|---|
| **PR professionals** | Improve outreach conversion rates by catching weak pitches before sending |
| **Startups / Founders** | Get a "journalist's eye" without expensive PR consultants |
| **Pathos Communications** | Demonstrates AI-first product thinking for client pitch tooling |

### Target Users

- In-house comms teams at startups and scale-ups
- Freelance PR practitioners
- Founders doing their own outreach

### Success Metrics

- **Pitch Score Delta:** Average improvement of rewritten pitch vs. original (target: +2.5 points)
- **Time-to-Feedback:** < 15 seconds from submit to full audit
- **Zero Cost:** 100% free-tier operation via OpenRouter

---

## 2. System Architecture & Data Flow

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FRONTEND (Next.js)                    │
│                                                         │
│  ┌──────────────┐    ┌──────────────────────────────┐   │
│  │  Pitch Input  │    │       Results Panel           │   │
│  │  - textarea   │───▶│  - Roast feedback             │   │
│  │  - persona    │    │  - Scores (6 dims + overall)  │   │
│  │  - metadata   │    │  - Redlined text              │   │
│  │  - word count │    │  - Rewritten pitch            │   │
│  └──────────────┘    └──────────────────────────────┘   │
│          │                       ▲                       │
│          ▼                       │                       │
│  ┌──────────────────────────────────────┐               │
│  │     POST /api/audit                  │               │
│  │     (Next.js Route Handler)          │               │
│  └──────────────┬───────────────────────┘               │
└─────────────────┼───────────────────────────────────────┘
                  │ HTTP POST (JSON)
                  ▼
┌─────────────────────────────────────────────────────────┐
│                  BACKEND (Python FastAPI)                 │
│                   http://localhost:8000                   │
│                                                         │
│  ┌──────────────┐    ┌──────────────────────────────┐   │
│  │  Pydantic v2  │    │    LLM Service Layer          │   │
│  │  Validation   │───▶│  - Prompt construction         │   │
│  │              │    │  - OpenRouter API call          │   │
│  │              │    │  - Response parsing + fallback  │   │
│  └──────────────┘    └──────────────┬───────────────┘   │
└─────────────────────────────────────┼───────────────────┘
                                      │ HTTPS
                                      ▼
                          ┌──────────────────────┐
                          │   OpenRouter API      │
                          │   (free tier)         │
                          │                       │
                          │   Model:              │
                          │   meta-llama/         │
                          │   llama-3.3-70b-      │
                          │   instruct:free       │
                          │                       │
                          │   Fallback:           │
                          │   openrouter/free     │
                          └──────────────────────┘
```

### Request Flow

1. **User** enters pitch text, selects an editor persona, and optionally fills in company name / target pub / campaign angle.
2. **Next.js frontend** validates word count (≤1,000 hard limit), then sends `POST /api/audit` to the Next.js Route Handler.
3. **Route Handler** proxies the request to FastAPI at `localhost:8000/audit` (avoids CORS issues, keeps OpenRouter key server-side).
4. **FastAPI** validates the request via Pydantic v2, constructs the system + user prompt, and calls OpenRouter.
5. **OpenRouter** returns a JSON response (via constrained JSON mode in the prompt).
6. **FastAPI** parses, sanitizes, and validates the LLM output against `PitchAuditResponse`, applying the defensive fallback chain if parsing fails.
7. **Response** flows back: FastAPI → Next.js Route Handler → Frontend UI.
8. **Frontend** renders the roast, scores, redlines, and rewrite in the results panel with a copy-to-clipboard button for each section.

### Environment Variables

```env
# Backend (.env)
OPENROUTER_API_KEY=sk-or-v1-...        # Required — user's own OpenRouter key
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct:free
OPENROUTER_FALLBACK_MODEL=openrouter/free
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
REQUEST_TIMEOUT=30
MAX_RETRIES=3

# Frontend (.env.local)
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## 3. Data Schemas

### 3.1 Request Schema (Pydantic v2)

```python
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class EditorPersona(str, Enum):
    TECHCRUNCH = "techcrunch"
    FORBES = "forbes"
    THE_VERGE = "the_verge"
    GULF_NEWS = "gulf_news"
    ROASTBOT = "roastbot"


class PitchRequest(BaseModel):
    """Validated incoming pitch from the frontend."""

    pitch_text: str = Field(
        ...,
        min_length=50,
        max_length=4000,
        description="The cold PR pitch to evaluate.",
    )
    persona: EditorPersona = Field(
        ...,
        description="Which editor persona to simulate.",
    )
    company_name: Optional[str] = Field(
        None,
        max_length=100,
        description="Name of the company being pitched.",
    )
    target_publication: Optional[str] = Field(
        None,
        max_length=100,
        description="The intended target publication.",
    )
    campaign_angle: Optional[str] = Field(
        None,
        max_length=200,
        description="Brief description of the campaign or story angle.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "pitch_text": "Hi, I'm reaching out because our revolutionary AI-powered platform is going to disrupt the way businesses handle customer engagement. We've seen explosive growth and are leveraging cutting-edge technology to create synergies across the enterprise landscape.",
                    "persona": "techcrunch",
                    "company_name": "EngageAI",
                    "target_publication": "TechCrunch",
                    "campaign_angle": "Series A funding announcement",
                }
            ]
        }
    }
```

### 3.2 Response Schema (Pydantic v2)

```python
from pydantic import BaseModel, Field
from typing import List


class DimensionScore(BaseModel):
    """A single evaluation dimension."""

    name: str = Field(..., description="Dimension name (e.g., 'Clarity').")
    score: int = Field(..., ge=0, le=10, description="Score from 0 to 10.")
    feedback: str = Field(..., description="1-2 sentence explanation of the score.")
    suggestion: str = Field(
        ..., description="Concrete improvement suggestion for this dimension."
    )


class Redline(BaseModel):
    """A single tracked-change style edit."""

    original: str = Field(..., description="Original text fragment.")
    replacement: str = Field(..., description="Suggested replacement text.")
    reason: str = Field(..., description="Why this change was made.")


class PitchAuditResponse(BaseModel):
    """Full audit result returned to the frontend."""

    persona: str = Field(..., description="Name of the editor persona used.")
    persona_avatar: str = Field(
        ..., description="Emoji or short label for the persona."
    )
    roast: str = Field(
        ..., description="The persona's candid, personality-driven roast of the pitch."
    )
    scores: List[DimensionScore] = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Exactly 6 dimension scores.",
    )
    overall_score: float = Field(
        ...,
        ge=0,
        le=10,
        description="Weighted overall score (0-10).",
    )
    redlines: List[Redline] = Field(
        ...,
        description="List of inline tracked-change suggestions.",
    )
    rewritten_pitch: str = Field(
        ...,
        description="A complete rewrite of the pitch by the persona.",
    )
    model_used: str = Field(
        ..., description="Which model actually handled the request."
    )
```

### 3.3 Error Response Schema

```python
class AuditErrorResponse(BaseModel):
    """Structured error when audit fails after retries."""

    error: str = Field(..., description="Error type: 'rate_limit' | 'parse_error' | 'timeout' | 'model_unavailable'.")
    message: str = Field(..., description="Human-readable error message.")
    raw_text: Optional[str] = Field(
        None, description="Raw LLM output if parse failed (for debugging)."
    )
    retry_after: Optional[int] = Field(
        None, description="Seconds to wait before retrying (for 429)."
    )
```

---

## 4. Editor System Prompts & Few-Shot Templates

### 4.1 System Prompt Construction

All personas share a base system prompt that enforces JSON output. The persona-specific instructions are injected as a `<persona>` block.

```python
SYSTEM_PROMPT_TEMPLATE = """You are simulating a specific editor at a publications. You must return your response as a SINGLE valid JSON object — no markdown, no code fences, no commentary outside the JSON.

The JSON must strictly follow this schema:
{response_schema}

## Scoring Dimensions

Score each dimension from 0 to 10:
1. **Clarity** — Is the hook immediately obvious in the first sentence?
2. **Specificity** — Are there concrete numbers, names, dates, or outcomes?
3. **Buzzword Density** — How many filler words like "synergy", "game-changing", "leverage", "cutting-edge", "revolutionary", "disrupt", "ecosystem"? (10 = zero buzzwords, 0 = entirely buzzwords)
4. **Length** — Is the pitch under 150 words? (10 = optimal, 0 = >300 words)
5. **Relevance** — Does the pitch match the editor's beat and publication?
6. **Readability** — Is the language clear and professional? Short sentences? Active voice?

The **overall_score** is a weighted average:
- Clarity: 25%
- Specificity: 20%
- Buzzword Density: 15%
- Length: 10%
- Relevance: 20%
- Readability: 10%

## Persona Instructions

<persona>
{persona_prompt}
</persona>

## Few-Shot Example

Input pitch: "We are excited to announce our revolutionary AI platform that will disrupt the industry and create unprecedented synergies for forward-thinking enterprises."

Your JSON response must include:
- "roast": Your candid, persona-appropriate roast of this pitch
- "scores": Exactly 6 DimensionScore objects
- "overall_score": The weighted average
- "redlines": At least 2 specific text edits with original/replacement/reason
- "rewritten_pitch": A complete rewritten version

Return ONLY the JSON object. No markdown fences. No extra text.
"""
```

### 4.2 Persona Prompt Definitions

```python
PERSONA_PROMPTS = {
    "techcrunch": """You are Sarah Chen, a senior editor at TechCrunch covering startups and venture capital.
    You've read 10,000 pitches this year. You're tired of:
    - Pitches that don't lead with traction metrics
    - Founders who say "revolutionary" without explaining what the product actually does
    - PR fluff that wastes your time

    Your style: Direct, slightly dry, metrics-obsessed. You appreciate a pitch that leads with
    ARR growth, user numbers, or a clear product demo link. You respect founders who know
    their competitive landscape.

    Tone: Professional but no-nonsense. Not cruel, but you won't sugarcoat it.""",

    "forbes": """You are Marcus Williams, a leadership and enterprise technology editor at Forbes.
    You've ghosted on pitches that:
    - Use jargon without explaining business impact
    - Claim "market disruption" without market sizing
    - Address you as "Dear Editor" with no personalization

    Your style: Formal, business-impact focused. You want to see: What's the TAM? Who's the buyer?
    What's the ROI? You appreciate executive-level clarity.

    Tone: Authoritative and polished. You hold pitches to a high standard but reward quality.""",

    "the_verge": """You are Priya Kapoor, a consumer tech product reviewer at The Verge.
    You're exhausted by:
    - Pitches that don't explain what the product *is* in the first paragraph
    - B2B jargon in consumer product pitches
    - Claims of being "first to market" without evidence

    Your style: Product-obsessed, witty, and visually-minded. You want to know: What does it look
    like? How does it feel to use? What problem does it solve for *me*?

    Tone: Conversational, clever, occasionally snarky. You roast bad pitches with humor.""",

    "gulf_news": """You are Fatima Al-Rashid, a business and technology correspondent covering the
    UAE and MENA region for Gulf News / Khaleej Times.
    You're turned off by:
    - Pitches with zero regional context or relevance
    - Western-centric framing that ignores MENA markets
    - Claims of "global impact" with no regional evidence

    Your style: Globally aware, regionally grounded. You appreciate pitches that mention MENA
    expansion, Dubai/Abu Dhabi/RIYADH as markets, or partnerships with regional entities.

    Tone: Professional, culturally aware, direct. You hold pitches accountable for global claims.""",

    "roastbot": """You are RoastBot, a maximally unfiltered, brutally honest pitch critic.
    You have zero patience for:
    - Any buzzwords whatsoever
    - Pitches longer than 100 words that could be said in 30
    - Anything that doesn't get to the point in the first sentence

    Your style: Maximum roasting. You use humor, sarcasm, and vivid metaphors to destroy bad pitches.
    You're the editor who reply-alls your roast to the entire newsroom.

    Tone: Unhinged, hilarious, devastating. You're the editor from hell — and you love your job.""",
}
```

### 4.3 User Message Template

```python
USER_MESSAGE_TEMPLATE = """Audit this cold PR pitch:

--- PITCH START ---
{pitch_text}
--- PITCH END ---

{optional_context}

Respond with a single JSON object matching the required schema. No markdown fences. No extra text.
"""
```

Where `optional_context` is built from optional fields:

```python
def build_optional_context(request: PitchRequest) -> str:
    parts = []
    if request.company_name:
        parts.append(f"Company: {request.company_name}")
    if request.target_publication:
        parts.append(f"Target publication: {request.target_publication}")
    if request.campaign_angle:
        parts.append(f"Campaign angle: {request.campaign_angle}")
    return "\n".join(parts) if parts else ""
```

---

## 5. Defensive Engineering & AI Skepticism Plan

This section defines every failure mode and the mitigation strategy. **Never trust raw LLM output.**

### 5.1 LLM Response Sanitization Pipeline

```python
import json
import re
from typing import Optional


def sanitize_llm_response(raw: str) -> Optional[dict]:
    """
    Multi-stage fallback parser for LLM JSON output.
    Returns parsed dict or None if all stages fail.
    """
    # Stage 1: Direct parse (model returned clean JSON)
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass

    # Stage 2: Strip markdown code fences (```json ... ``` or ``` ... ```)
    fenced = re.sub(r"```(?:json)?\s*\n?(.*?)\n?\s*```", r"\1", raw, flags=re.DOTALL)
    try:
        return json.loads(fenced.strip())
    except json.JSONDecodeError:
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
                        return json.loads(raw[start : i + 1])
                    except json.JSONDecodeError:
                        break

    return None
```

### 5.2 Retry & Fallback Strategy

| Failure Mode | Detection | Mitigation |
|---|---|---|
| **HTTP 429 (Rate Limit)** | Response status code | Retry with exponential backoff: **1s → 2s → 4s**. Max 3 retries. If all fail, return `AuditErrorResponse(error="rate_limit", retry_after=N)` where N is from the `Retry-After` header. |
| **HTTP 5xx / Timeout** | Response status code or `TimeoutError` | Retry same model up to 3 times. On final failure, try fallback model (`openrouter/free`). If fallback also fails, return `AuditErrorResponse(error="model_unavailable")`. |
| **Malformed JSON** | `sanitize_llm_response()` returns `None` | Retry the same request up to 2 times. If still malformed, return `AuditErrorResponse(error="parse_error", raw_text=raw)` so the frontend can show the raw output. |
| **JSON Valid but Schema Mismatch** | Pydantic validation fails | Log validation errors. Attempt to extract valid fields and fill defaults for missing ones. If critical fields (roast, scores) are missing, treat as parse_error. |
| **Partial Response** | Response cuts off mid-JSON | Detect via incomplete JSON (depth > 0 at end). Retry once. If still partial, return parse_error with raw text. |

### 5.3 Input Validation (Frontend + Backend)

| Rule | Frontend | Backend (Pydantic) |
|---|---|---|
| **Word count soft cap (300 words)** | Visual warning + yellow indicator | No enforcement (let editor roast length) |
| **Word count hard cap (1,000 words)** | Block submission, show error | `max_length=4000` on `pitch_text` (chars ≈ words × 5 + buffer) |
| **Minimum length (50 chars)** | Grey out submit button | `min_length=50` on `pitch_text` |
| **Persona required** | Dropdown defaults to first option | `EditorPersona` enum, required field |
| **Optional fields sanitized** | Trim whitespace | `max_length` enforcement on each optional field |

### 5.4 Rate Limiting (Application-Level)

To prevent abuse of the free OpenRouter tier:

- **Per-session limit:** 10 audits per 5-minute window (tracked via browser localStorage)
- **Per-IP limit (backend):** 30 requests per minute (in-memory sliding window or simple counter)
- Return `429` with `Retry-After` header when exceeded

### 5.5 Model Hallucination Guards

- **Schema validation:** Pydantic enforces exact structure — hallucinated extra fields are stripped, missing fields trigger defaults
- **Score bounds:** `ge=0, le=10` on every score field — hallucinated scores outside range are rejected
- **Redline validation:** Each redline must have non-empty `original`, `replacement`, and `reason` — empty entries are filtered
- **Rewrite length check:** Rewritten pitch must be > 0 and < 3× original length (flag if LLM padded excessively)

---

## 6. TDD Test Suite Specifications

### 6.1 Backend Tests (pytest)

All tests run against **mock payloads** — no real API calls during testing.

#### `tests/test_schemas.py`

```python
"""Pydantic schema validation tests."""

import pytest
from app.schemas import PitchRequest, PitchAuditResponse, DimensionScore, Redline, AuditErrorResponse


class TestPitchRequest:
    def test_valid_request_minimal(self):
        """Valid request with only required fields."""
        req = PitchRequest(
            pitch_text="A" * 50,
            persona="techcrunch",
        )
        assert req.pitch_text == "A" * 50
        assert req.company_name is None

    def test_valid_request_full(self):
        """Valid request with all optional fields."""
        req = PitchRequest(
            pitch_text="A" * 50,
            persona="forbes",
            company_name="Acme Corp",
            target_publication="Forbes",
            campaign_angle="Product launch",
        )
        assert req.company_name == "Acme Corp"

    def test_rejects_empty_pitch(self):
        """Pitch below min_length raises ValidationError."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            PitchRequest(pitch_text="short", persona="techcrunch")

    def test_rejects_invalid_persona(self):
        """Invalid persona enum value raises ValidationError."""
        with pytest.raises(Exception):
            PitchRequest(pitch_text="A" * 50, persona="invalid_persona")

    def test_rejects_oversized_pitch(self):
        """Pitch above max_length raises ValidationError."""
        with pytest.raises(Exception):
            PitchRequest(pitch_text="A" * 5000, persona="techcrunch")


class TestPitchAuditResponse:
    def test_valid_response(self):
        """Valid response with all required fields."""
        resp = PitchAuditResponse(
            persona="TechCrunch Sarah",
            persona_avatar="👩‍💻",
            roast="This pitch is terrible.",
            scores=[
                DimensionScore(name="Clarity", score=3, feedback="Unclear.", suggestion="Lead with metric."),
                DimensionScore(name="Specificity", score=2, feedback="Vague.", suggestion="Add numbers."),
                DimensionScore(name="Buzzword Density", score=1, feedback="Buzzwords.", suggestion="Remove them."),
                DimensionScore(name="Length", score=5, feedback="OK length.", suggestion="Tighten."),
                DimensionScore(name="Relevance", score=4, feedback="Partially relevant.", suggestion="Tailor more."),
                DimensionScore(name="Readability", score=6, feedback="Readable.", suggestion="Use active voice."),
            ],
            overall_score=3.5,
            redlines=[
                Redline(original="revolutionary", replacement="new", reason="Buzzword"),
            ],
            rewritten_pitch="Here's a concise rewritten pitch.",
            model_used="meta-llama/llama-3.3-70b-instruct:free",
        )
        assert len(resp.scores) == 6
        assert 0 <= resp.overall_score <= 10

    def test_rejects_wrong_score_count(self):
        """Response with != 6 scores raises ValidationError."""
        with pytest.raises(Exception):
            PitchAuditResponse(
                persona="Test",
                persona_avatar="🤖",
                roast="Bad pitch.",
                scores=[
                    DimensionScore(name="Clarity", score=5, feedback="OK.", suggestion="Better."),
                ],
                overall_score=5.0,
                redlines=[],
                rewritten_pitch="Rewrite.",
                model_used="test",
            )

    def test_rejects_score_out_of_range(self):
        """Score > 10 raises ValidationError."""
        with pytest.raises(Exception):
            DimensionScore(name="Clarity", score=11, feedback="Good.", suggestion="Great.")


class TestAuditErrorResponse:
    def test_valid_error_response(self):
        resp = AuditErrorResponse(
            error="rate_limit",
            message="Too many requests.",
            retry_after=30,
        )
        assert resp.error == "rate_limit"
        assert resp.raw_text is None
```

#### `tests/test_parser.py`

```python
"""LLM response sanitisation and parsing tests."""

import pytest
from app.parser import sanitize_llm_response


class TestSanitizeLLMResponse:
    VALID_JSON = '{"roast": "Bad pitch", "scores": [], "overall_score": 5.0}'
    FENCED_JSON = '```json\n{"roast": "Bad pitch"}\n```'
    FENCED_NO_LANG = '```\n{"roast": "Bad pitch"}\n```'
    JSON_WITH_PRETEXT = 'Here is my analysis:\n{"roast": "Bad pitch"}\nHope that helps!'
    MALFORMED = 'This is not JSON at all'
    PARTIAL_JSON = '{"roast": "Bad pitch", "scores": ['

    def test_clean_json(self):
        assert sanitize_llm_response(self.VALID_JSON) is not None

    def test_markdown_fenced_json(self):
        assert sanitize_llm_response(self.FENCED_JSON) is not None

    def test_fenced_without_language(self):
        assert sanitize_llm_response(self.FENCED_NO_LANG) is not None

    def test_json_with_surrounding_text(self):
        result = sanitize_llm_response(self.JSON_WITH_PRETEXT)
        assert result is not None
        assert "roast" in result

    def test_malformed_returns_none(self):
        assert sanitize_llm_response(self.MALFORMED) is None

    def test_partial_json_returns_none(self):
        assert sanitize_llm_response(self.PARTIAL_JSON) is None

    def test_empty_string_returns_none(self):
        assert sanitize_llm_response("") is None
```

#### `tests/test_service.py`

```python
"""Audit service logic tests with mocked OpenRouter calls."""

import pytest
from unittest.mock import AsyncMock, patch
from app.service import audit_pitch


class TestAuditPitch:
    @pytest.mark.asyncio
    async def test_successful_audit(self):
        """Happy path: valid LLM response."""
        mock_response = {
            "persona": "TechCrunch Sarah",
            "persona_avatar": "👩‍💻",
            "roast": "This pitch is terrible.",
            "scores": [
                {"name": "Clarity", "score": 3, "feedback": "Unclear", "suggestion": "Lead with metric"},
                {"name": "Specificity", "score": 2, "feedback": "Vague", "suggestion": "Add numbers"},
                {"name": "Buzzword Density", "score": 1, "feedback": "Buzzwords", "suggestion": "Remove"},
                {"name": "Length", "score": 5, "feedback": "OK", "suggestion": "Tighten"},
                {"name": "Relevance", "score": 4, "feedback": "Partial", "suggestion": "Tailor"},
                {"name": "Readability", "score": 6, "feedback": "Good", "suggestion": "Active voice"},
            ],
            "overall_score": 3.5,
            "redlines": [{"original": "rev", "replacement": "new", "reason": "Buzzword"}],
            "rewritten_pitch": "Better pitch here.",
            "model_used": "test-model",
        }
        with patch("app.service._call_openrouter", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_response
            result = await audit_pitch(
                pitch_text="A" * 50,
                persona="techcrunch",
            )
            assert result.overall_score == 3.5

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self):
        """Should retry 3 times on 429 and then fail."""
        from app.service import RateLimitError

        with patch("app.service._call_openrouter", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = RateLimitError(retry_after=10)
            with pytest.raises(RateLimitError):
                await audit_pitch(pitch_text="A" * 50, persona="techcrunch")
            assert mock_call.call_count == 4  # initial + 3 retries

    @pytest.mark.asyncio
    async def test_fallback_on_parse_error(self):
        """Should retry on malformed JSON, then raise."""
        with patch("app.service._call_openrouter", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "not json at all"
            with pytest.raises(Exception):
                await audit_pitch(pitch_text="A" * 50, persona="techcrunch")
```

### 6.2 Frontend Tests

To be implemented with Vitest + React Testing Library after backend is stable. Key cases:

| Test | What it validates |
|---|---|
| `submits pitch and displays results` | Happy path: form → API → render scores + roast |
| `blocks submission over 1000 words` | Hard cap enforcement |
| `shows word count warning at 300 words` | Soft cap UI indicator |
| `displays rate limit error gracefully` | 429 handling in UI |
| `copy button copies to clipboard` | Clipboard API integration |
| `persona dropdown defaults to TechCrunch` | Default selection |
| `dark mode toggle works` | Theme switching |

---

## 7. Step-by-Step Commit Roadmap

Each commit is small, verifiable, and conventional. Order is **test-first** (TDD) where applicable.

### Phase 1: Project Scaffolding

| # | Commit Message | Files Changed |
|---|---|---|
| 1 | `feat: add PRD.md as ground-truth specification` | `PRD.md` |
| 2 | `chore: scaffold FastAPI backend with pyproject.toml` | `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/main.py` |
| 3 | `chore: add backend environment config and .env.example` | `backend/.env.example` |

### Phase 2: Schema & Parser (TDD)

| # | Commit Message | Files Changed |
|---|---|---|
| 4 | `test: add Pydantic schema validation tests` | `backend/tests/test_schemas.py` |
| 5 | `feat: implement PitchRequest and PitchAuditResponse schemas` | `backend/app/schemas.py` |
| 6 | `test: add LLM response parser tests` | `backend/tests/test_parser.py` |
| 7 | `feat: implement multi-stage JSON sanitiser` | `backend/app/parser.py` |

### Phase 3: Audit Service (TDD)

| # | Commit Message | Files Changed |
|---|---|---|
| 8 | `test: add audit service tests with mocked OpenRouter` | `backend/tests/test_service.py` |
| 9 | `feat: implement editor personas and system prompt templates` | `backend/app/personas.py` |
| 10 | `feat: implement audit service with retry and fallback` | `backend/app/service.py` |
| 11 | `feat: add POST /audit route with Pydantic validation` | `backend/app/main.py` |

### Phase 4: Frontend — Core UI

| # | Commit Message | Files Changed |
|---|---|---|
| 12 | `style: configure dark mode as default theme` | `app/globals.css` |
| 13 | `feat: build pitch input form with persona selector and word count` | `app/components/PitchForm.tsx` |
| 14 | `feat: build results panel with scores, roast, and rewrite tabs` | `app/components/ResultsPanel.tsx` |
| 15 | `feat: assemble split-screen layout on home page` | `app/page.tsx` |
| 16 | `feat: add dark/light mode toggle` | `app/components/ThemeToggle.tsx` |

### Phase 5: Frontend — API Integration

| # | Commit Message | Files Changed |
|---|---|---|
| 17 | `feat: add POST /api/audit Next.js route handler` | `app/api/audit/route.ts` |
| 18 | `feat: integrate PitchForm with audit API` | `app/components/PitchForm.tsx` |
| 19 | `feat: add loading state with flame animation` | `app/components/LoadingSpinner.tsx` |
| 20 | `feat: add copy-to-clipboard on roast and rewrite sections` | `app/components/ResultsPanel.tsx` |

### Phase 6: Defensive Hardening

| # | Commit Message | Files Changed |
|---|---|---|
| 21 | `feat: add client-side rate limiting (10 per 5min)` | `app/lib/rateLimit.ts` |
| 22 | `feat: add server-side IP rate limiting to FastAPI` | `backend/app/middleware.py` |
| 23 | `fix: handle malformed LLM output with graceful fallback UI` | `app/components/ResultsPanel.tsx` |

### Phase 7: Polish & Documentation

| # | Commit Message | Files Changed |
|---|---|---|
| 24 | `docs: add README.md with setup instructions and architecture` | `README.md` |
| 25 | `chore: add .gitignore entries for .env and __pycache__` | `.gitignore` |

---

## Appendix A: Weighted Score Calculation

```python
WEIGHTS = {
    "Clarity": 0.25,
    "Specificity": 0.20,
    "Buzzword Density": 0.15,
    "Length": 0.10,
    "Relevance": 0.20,
    "Readability": 0.10,
}


def calculate_overall_score(scores: dict[str, int]) -> float:
    """Calculate weighted overall score from dimension scores."""
    weighted = sum(scores[dim] * weight for dim, weight in WEIGHTS.items())
    return round(weighted, 1)
```

## Appendix B: Buzzword Blacklist (Reference)

Used by the LLM prompt and optionally for client-side highlighting:

```
synergy, game-changing, revolutionary, disruptive, leverage, cutting-edge,
unprecedented, ecosystem, world-class, best-in-class, innovative, scalable,
paradigm shift, robust, turnkey, bleeding edge, next-generation,
holistic, agile, mission-critical, thought leadership, deep dive,
circle back, move the needle, low-hanging fruit, paradigm, bandwidth
```

## Appendix C: LLM Constrained JSON Mode

Since OpenRouter's free models don't support native JSON mode, we enforce it via:

1. **System prompt instruction:** "Return ONLY the JSON object. No markdown fences. No extra text."
2. **Few-shot example:** Include one complete JSON example in the prompt.
3. **Post-processing:** `sanitize_llm_response()` strips fences and extracts JSON.
4. **Schema validation:** Pydantic validates the final structure.

---

*This PRD is the ground-truth specification. All code generation must conform to this document. Changes to requirements must be reflected here first.*
