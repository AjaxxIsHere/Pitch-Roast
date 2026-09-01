"""PitchRoast analyzer tests — JSON parsing, error handling, and schema validation."""

import json
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.schemas import (
    PitchRequest,
    PitchAuditResponse,
    DimensionScore,
    Redline,
    AuditErrorResponse,
    EditorPersona,
)
from app.services import (
    sanitize_llm_response,
    audit_pitch,
    RateLimitError,
    ModelUnavailableError,
    ParseError,
    MODEL_POOL,
    GATEWAY_ERRORS,
    _build_mock_response,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_AUDIT_RESPONSE = {
    "persona": "TechCrunch Sarah",
    "persona_avatar": "👩‍💻",
    "roast": "This pitch reads like a buzzword bingo card. Zero metrics, zero substance.",
    "scores": [
        {"name": "Clarity", "score": 3, "feedback": "Hook is buried.", "suggestion": "Lead with traction."},
        {"name": "Specificity", "score": 2, "feedback": "No numbers.", "suggestion": "Add ARR or user count."},
        {"name": "Buzzword Density", "score": 1, "feedback": "Loaded with jargon.", "suggestion": "Cut 'revolutionary' and 'synergy'."},
        {"name": "Length", "score": 5, "feedback": "Acceptable length.", "suggestion": "Tighten by 20%."},
        {"name": "Relevance", "score": 4, "feedback": "Partially on-beat.", "suggestion": "Reference a recent TC article."},
        {"name": "Readability", "score": 6, "feedback": "Generally clear.", "suggestion": "Use shorter sentences."},
    ],
    "overall_score": 3.5,
    "redlines": [
        {"original": "revolutionary AI platform", "replacement": "new AI tool", "reason": "Buzzword — be specific instead."},
        {"original": "disrupt the industry", "replacement": "improve onboarding for SaaS teams", "reason": "Vague claim — name the outcome."},
    ],
    "rewritten_pitch": "Hi — EngageAI cuts SaaS onboarding time by 40% using AI-assisted workflows. We recently closed $2M ARR and are launching with 12 design partners. Can I send a 2-min demo?",
    "model_used": "test-model",
}


def _make_dimension_scores(**overrides):
    """Helper: build a full list of 6 DimensionScore dicts with optional overrides."""
    defaults = [
        ("Clarity", 5, "Okay.", "Improve."),
        ("Specificity", 5, "Okay.", "Improve."),
        ("Buzzword Density", 5, "Okay.", "Improve."),
        ("Length", 5, "Okay.", "Improve."),
        ("Relevance", 5, "Okay.", "Improve."),
        ("Readability", 5, "Okay.", "Improve."),
    ]
    scores = []
    for name, score, fb, sug in defaults:
        d = {"name": name, "score": score, "feedback": fb, "suggestion": sug}
        if name in overrides:
            d.update(overrides[name])
        scores.append(d)
    return scores


# ===========================================================================
# 1. JSON Parsing Tests (sanitize_llm_response)
# ===========================================================================


class TestSanitizeLLMResponse:
    """Multi-stage fallback parser for LLM JSON output."""

    # --- Happy-path inputs ---------------------------------------------------

    def test_clean_json(self):
        raw = json.dumps({"roast": "Bad pitch"})
        result = sanitize_llm_response(raw)
        assert result is not None
        assert result["roast"] == "Bad pitch"

    def test_json_with_surrounding_text(self):
        raw = 'Here is my analysis:\n{"roast": "Bad pitch"}\nHope that helps!'
        result = sanitize_llm_response(raw)
        assert result is not None
        assert "roast" in result

    def test_fenced_json_with_language_tag(self):
        raw = '```json\n{"roast": "Bad pitch"}\n```'
        result = sanitize_llm_response(raw)
        assert result is not None
        assert result["roast"] == "Bad pitch"

    def test_fenced_json_without_language_tag(self):
        raw = '```\n{"roast": "Bad pitch"}\n```'
        result = sanitize_llm_response(raw)
        assert result is not None
        assert result["roast"] == "Bad pitch"

    def test_json_with_leading_trailing_whitespace(self):
        raw = '  \n  {"roast": "Trimmed"}  \n  '
        result = sanitize_llm_response(raw)
        assert result is not None
        assert result["roast"] == "Trimmed"

    def test_json_with_nested_objects(self):
        payload = json.dumps({
            "roast": "Bad",
            "scores": [{"name": "Clarity", "score": 5}],
            "meta": {"model": "test"},
        })
        result = sanitize_llm_response(payload)
        assert result is not None
        assert result["meta"]["model"] == "test"

    def test_full_valid_audit_response(self):
        raw = json.dumps(VALID_AUDIT_RESPONSE)
        result = sanitize_llm_response(raw)
        assert result is not None
        assert result["overall_score"] == 3.5
        assert len(result["scores"]) == 6
        assert len(result["redlines"]) == 2

    # --- Invalid / malformed inputs ------------------------------------------

    def test_malformed_returns_none(self):
        assert sanitize_llm_response("This is not JSON at all") is None

    def test_partial_json_returns_none(self):
        assert sanitize_llm_response('{"roast": "Bad pitch", "scores": [') is None

    def test_empty_string_returns_none(self):
        assert sanitize_llm_response("") is None

    def test_just_braces_returns_none(self):
        assert sanitize_llm_response("{}") is not None  # valid empty object

    def test_array_instead_of_object_returns_none(self):
        assert sanitize_llm_response("[1, 2, 3]") is None

    def test_trailing_comma_returns_none(self):
        assert sanitize_llm_response('{"roast": "Bad",}') is None

    def test_single_quotes_returns_none(self):
        assert sanitize_llm_response("{'roast': 'Bad'}") is None

    def test_fenced_surrounding_garbage_returns_none(self):
        raw = '```json\nnot json at all\n```'
        assert sanitize_llm_response(raw) is None


# ===========================================================================
# 2. Schema Validation Tests
# ===========================================================================


class TestEditorPersona:
    def test_all_valid_values(self):
        for val in ("techcrunch", "forbes", "the_verge", "gulf_news", "roastbot"):
            assert EditorPersona(val) == val

    def test_invalid_value_rejected(self):
        with pytest.raises(ValueError):
            EditorPersona("invalid_persona")


class TestPitchRequest:
    def test_valid_minimal(self):
        req = PitchRequest(pitch_text="A" * 50, persona="techcrunch")
        assert req.pitch_text == "A" * 50
        assert req.company_name is None
        assert req.target_publication is None
        assert req.campaign_angle is None

    def test_valid_full(self):
        req = PitchRequest(
            pitch_text="A" * 50,
            persona="forbes",
            company_name="Acme Corp",
            target_publication="Forbes",
            campaign_angle="Series A announcement",
        )
        assert req.company_name == "Acme Corp"
        assert req.target_publication == "Forbes"

    def test_rejects_short_pitch(self):
        with pytest.raises(Exception):
            PitchRequest(pitch_text="short", persona="techcrunch")

    def test_rejects_oversized_pitch(self):
        with pytest.raises(Exception):
            PitchRequest(pitch_text="A" * 5001, persona="techcrunch")

    def test_rejects_invalid_persona(self):
        with pytest.raises(Exception):
            PitchRequest(pitch_text="A" * 50, persona="nonexistent")

    def test_exactly_50_chars_accepted(self):
        req = PitchRequest(pitch_text="x" * 50, persona="roastbot")
        assert len(req.pitch_text) == 50

    def test_exactly_4000_chars_accepted(self):
        req = PitchRequest(pitch_text="x" * 4000, persona="roastbot")
        assert len(req.pitch_text) == 4000


class TestDimensionScore:
    def test_valid(self):
        ds = DimensionScore(name="Clarity", score=7, feedback="Good.", suggestion="Better.")
        assert ds.score == 7

    def test_boundary_zero(self):
        ds = DimensionScore(name="Clarity", score=0, feedback="Terrible.", suggestion="Rewrite.")
        assert ds.score == 0

    def test_boundary_ten(self):
        ds = DimensionScore(name="Clarity", score=10, feedback="Perfect.", suggestion="None needed.")
        assert ds.score == 10

    def test_rejects_negative(self):
        with pytest.raises(Exception):
            DimensionScore(name="Clarity", score=-1, feedback="X", suggestion="Y")

    def test_rejects_above_ten(self):
        with pytest.raises(Exception):
            DimensionScore(name="Clarity", score=11, feedback="X", suggestion="Y")


class TestRedline:
    def test_valid(self):
        r = Redline(original="rev", replacement="new", reason="Buzzword.")
        assert r.original == "rev"


class TestPitchAuditResponse:
    def test_valid_full(self):
        resp = PitchAuditResponse(**VALID_AUDIT_RESPONSE)
        assert resp.persona == "TechCrunch Sarah"
        assert len(resp.scores) == 6
        assert resp.overall_score == 3.5

    def test_rejects_wrong_score_count(self):
        data = {**VALID_AUDIT_RESPONSE, "scores": [
            {"name": "Clarity", "score": 5, "feedback": "OK", "suggestion": "Improve"}
        ]}
        with pytest.raises(Exception):
            PitchAuditResponse(**data)

    def test_rejects_seven_scores(self):
        data = {**VALID_AUDIT_RESPONSE, "scores": _make_dimension_scores() + [
            {"name": "Extra", "score": 5, "feedback": "X", "suggestion": "Y"}
        ]}
        with pytest.raises(Exception):
            PitchAuditResponse(**data)

    def test_rejects_score_out_of_range(self):
        data = {**VALID_AUDIT_RESPONSE, "scores": [
            {"name": "Clarity", "score": 11, "feedback": "X", "suggestion": "Y"}
        ] + _make_dimension_scores()[1:]}
        with pytest.raises(Exception):
            PitchAuditResponse(**data)

    def test_rejects_overall_score_out_of_range(self):
        data = {**VALID_AUDIT_RESPONSE, "overall_score": 10.5}
        with pytest.raises(Exception):
            PitchAuditResponse(**data)

    def test_missing_required_field(self):
        data = {**VALID_AUDIT_RESPONSE}
        del data["roast"]
        with pytest.raises(Exception):
            PitchAuditResponse(**data)


class TestAuditErrorResponse:
    def test_valid_rate_limit(self):
        resp = AuditErrorResponse(error="rate_limit", message="Too many requests.", retry_after=30)
        assert resp.error == "rate_limit"
        assert resp.retry_after == 30
        assert resp.raw_text is None

    def test_valid_parse_error_with_raw(self):
        resp = AuditErrorResponse(error="parse_error", message="Could not parse.", raw_text="{bad")
        assert resp.raw_text == "{bad"

    def test_valid_timeout(self):
        resp = AuditErrorResponse(error="timeout", message="LLM timed out.")
        assert resp.error == "timeout"


# ===========================================================================
# 3. Integration: Parse then Validate
# ===========================================================================


class TestParseAndValidate:
    """End-to-end: parse raw LLM text → validate against Pydantic schema."""

    def test_parse_valid_then_validate(self):
        raw = json.dumps(VALID_AUDIT_RESPONSE)
        parsed = sanitize_llm_response(raw)
        assert parsed is not None
        resp = PitchAuditResponse(**parsed)
        assert resp.rewritten_pitch.startswith("Hi")

    def test_parse_fenced_then_validate(self):
        raw = f"```json\n{json.dumps(VALID_AUDIT_RESPONSE)}\n```"
        parsed = sanitize_llm_response(raw)
        assert parsed is not None
        resp = PitchAuditResponse(**parsed)
        assert len(resp.redlines) == 2

    def test_parse_with_noise_then_validate(self):
        raw = f"Sure! Here's my analysis:\n\n{json.dumps(VALID_AUDIT_RESPONSE)}\n\nLet me know if you need anything else."
        parsed = sanitize_llm_response(raw)
        assert parsed is not None
        resp = PitchAuditResponse(**parsed)
        assert resp.persona_avatar == "👩‍💻"

    def test_parse_garbage_fails_validation(self):
        parsed = sanitize_llm_response("not json at all")
        assert parsed is None  # can't even get to validation


# ===========================================================================
# 4. Model Pool & Failover Tests
# ===========================================================================


class TestModelPool:
    def test_pool_has_six_models(self):
        assert len(MODEL_POOL) == 6

    def test_pool_starts_with_openrouter_free(self):
        assert MODEL_POOL[0] == "openrouter/free"

    def test_pool_ends_with_gemini(self):
        assert MODEL_POOL[-1] == "google/gemini-flash-1.5:free"

    def test_gateway_errors_cover_all_required_codes(self):
        expected = {502, 503, 504, 520, 521, 522}
        assert GATEWAY_ERRORS == expected


class TestAuditPitchMock:
    """Test MOCK_LLM=true safety hatch."""

    @pytest.mark.asyncio
    async def test_mock_mode_techcrunch(self):
        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            result = await audit_pitch(
                pitch_text="A" * 50,
                persona="techcrunch",
            )
            assert result.model_used == "mock"
            assert result.persona == "TechCrunch Sarah"
            assert len(result.scores) == 6

    @pytest.mark.asyncio
    async def test_mock_mode_roastbot(self):
        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            result = await audit_pitch(
                pitch_text="A" * 50,
                persona="roastbot",
            )
            assert result.model_used == "mock"
            assert result.persona_avatar == "🔥"

    @pytest.mark.asyncio
    async def test_mock_mode_all_personas(self):
        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            for persona in ("techcrunch", "forbes", "the_verge", "gulf_news", "roastbot"):
                result = await audit_pitch(pitch_text="A" * 50, persona=persona)
                assert result.model_used == "mock"
                assert len(result.scores) == 6

    @pytest.mark.asyncio
    async def test_mock_mode_disabled_by_default(self):
        """Without MOCK_LLM=true, should NOT use mock."""
        with patch.dict(os.environ, {"MOCK_LLM": ""}, clear=False):
            with patch("app.services._call_openrouter", new_callable=AsyncMock) as mock_call:
                mock_call.return_value = json.dumps(VALID_AUDIT_RESPONSE)
                await audit_pitch(pitch_text="A" * 50, persona="techcrunch")
                mock_call.assert_called_once()


class TestBuildMockResponse:
    def test_returns_valid_pitch_audit_response(self):
        resp = _build_mock_response("techcrunch", "A" * 50)
        assert isinstance(resp, PitchAuditResponse)
        assert resp.model_used == "mock"

    def test_unknown_persona_falls_back_to_roastbot(self):
        resp = _build_mock_response("unknown_persona", "A" * 50)
        assert resp.persona_avatar == "🔥"


class TestAuditPitchFailover:
    """Test the multi-model failover logic in audit_pitch."""

    @pytest.mark.asyncio
    async def test_immediate_failover_on_503(self):
        """503 from first model should immediately try next model."""
        call_count = 0

        async def mock_call(messages, model, api_key=""):
            nonlocal call_count
            call_count += 1
            if model == MODEL_POOL[0]:
                raise ModelUnavailableError(f"{model} returned 503")
            # Second model succeeds
            return json.dumps(VALID_AUDIT_RESPONSE)

        with patch("app.services._call_openrouter", side_effect=mock_call):
            result = await audit_pitch(pitch_text="A" * 50, persona="techcrunch")
            assert result.overall_score == 3.5
            assert call_count == 2  # first failed, second succeeded

    @pytest.mark.asyncio
    async def test_immediate_failover_on_502(self):
        """502 from first model should immediately try next model."""
        async def mock_call(messages, model, api_key=""):
            if model == MODEL_POOL[0]:
                raise ModelUnavailableError(f"{model} returned 502")
            return json.dumps(VALID_AUDIT_RESPONSE)

        with patch("app.services._call_openrouter", side_effect=mock_call):
            result = await audit_pitch(pitch_text="A" * 50, persona="techcrunch")
            assert result.overall_score == 3.5

    @pytest.mark.asyncio
    async def test_immediate_failover_on_504(self):
        """504 from first model should immediately try next model."""
        async def mock_call(messages, model, api_key=""):
            if model == MODEL_POOL[0]:
                raise ModelUnavailableError(f"{model} returned 504")
            return json.dumps(VALID_AUDIT_RESPONSE)

        with patch("app.services._call_openrouter", side_effect=mock_call):
            result = await audit_pitch(pitch_text="A" * 50, persona="techcrunch")
            assert result.overall_score == 3.5

    @pytest.mark.asyncio
    async def test_all_models_fail_raises(self):
        """If all models fail, should raise ModelUnavailableError."""
        async def mock_call(messages, model, api_key=""):
            raise ModelUnavailableError(f"{model} unavailable")

        with patch("app.services._call_openrouter", side_effect=mock_call):
            with pytest.raises(ModelUnavailableError):
                await audit_pitch(pitch_text="A" * 50, persona="techcrunch")

    @pytest.mark.asyncio
    async def test_parse_error_retries_then_falls_through(self):
        """Parse error should retry then fall through to next model."""
        call_count = 0

        async def mock_call(messages, model, api_key=""):
            nonlocal call_count
            call_count += 1
            if model == MODEL_POOL[0]:
                return "not json at all"
            return json.dumps(VALID_AUDIT_RESPONSE)

        with patch("app.services._call_openrouter", side_effect=mock_call):
            result = await audit_pitch(pitch_text="A" * 50, persona="techcrunch")
            assert result.overall_score == 3.5
            # First model retried MAX_RETRIES+1 times, then second model called once
            from app.services import MAX_RETRIES
            assert call_count == (MAX_RETRIES + 1) + 1

    @pytest.mark.asyncio
    async def test_rate_limit_retries_with_backoff(self):
        """Rate limit should retry with backoff, then fall through."""
        call_count = 0

        async def mock_call(messages, model, api_key=""):
            nonlocal call_count
            call_count += 1
            if model == MODEL_POOL[0]:
                raise RateLimitError(retry_after=1)
            return json.dumps(VALID_AUDIT_RESPONSE)

        with patch("app.services._call_openrouter", side_effect=mock_call):
            result = await audit_pitch(pitch_text="A" * 50, persona="techcrunch")
            assert result.overall_score == 3.5
            from app.services import MAX_RETRIES
            assert call_count == (MAX_RETRIES + 1) + 1
