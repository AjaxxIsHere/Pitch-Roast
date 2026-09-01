"""Pydantic v2 schemas for PitchRoast API."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EditorPersona(str, Enum):
    """Supported editor personas."""

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


class DimensionScore(BaseModel):
    """A single evaluation dimension (0-10)."""

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
    scores: list[DimensionScore] = Field(
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
    redlines: list[Redline] = Field(
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


class AuditErrorResponse(BaseModel):
    """Structured error when audit fails after retries."""

    error: str = Field(
        ...,
        description="Error type: 'rate_limit' | 'parse_error' | 'timeout' | 'model_unavailable'.",
    )
    message: str = Field(..., description="Human-readable error message.")
    raw_text: Optional[str] = Field(
        None, description="Raw LLM output if parse failed (for debugging)."
    )
    retry_after: Optional[int] = Field(
        None, description="Seconds to wait before retrying (for 429)."
    )
