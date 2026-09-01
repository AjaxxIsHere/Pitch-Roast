"""PitchRoast FastAPI backend — POST /audit endpoint."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from app.schemas import AuditErrorResponse, PitchRequest, PitchAuditResponse
from app.services import (
    ModelUnavailableError,
    ParseError,
    RateLimitError,
    audit_pitch,
)


# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown hooks."""
    yield


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PitchRoast API",
    version="0.1.0",
    description="AI-powered cold PR pitch auditor — roast, score, redline, rewrite.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/audit",
    response_model=PitchAuditResponse,
    responses={
        422: {"model": AuditErrorResponse},
        429: {"model": AuditErrorResponse},
        503: {"model": AuditErrorResponse},
    },
)
async def audit(request: PitchRequest) -> PitchAuditResponse:
    """
    Audit a cold PR pitch against a simulated editor persona.

    Returns a full audit with roast, 6-dimension scores, redlines, and rewrite.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "")

    try:
        result = await audit_pitch(
            pitch_text=request.pitch_text,
            persona=request.persona.value,
            company_name=request.company_name,
            target_publication=request.target_publication,
            campaign_angle=request.campaign_angle,
            api_key=api_key,
        )
        return result

    except ValidationError as e:
        err = AuditErrorResponse(
            error="parse_error",
            message=f"LLM response failed validation: {e.error_count()} error(s).",
            raw_text=str(e),
        )
        raise HTTPException(status_code=422, detail=err.model_dump())

    except RateLimitError as e:
        err = AuditErrorResponse(
            error="rate_limit",
            message="Rate limited by LLM provider. Please try again later.",
            retry_after=e.retry_after,
        )
        raise HTTPException(status_code=429, detail=err.model_dump())

    except ParseError as e:
        err = AuditErrorResponse(
            error="parse_error",
            message="Could not parse LLM response.",
            raw_text=str(e),
        )
        raise HTTPException(status_code=422, detail=err.model_dump())

    except ModelUnavailableError as e:
        err = AuditErrorResponse(
            error="model_unavailable",
            message=str(e),
        )
        raise HTTPException(status_code=503, detail=err.model_dump())

    except Exception as e:
        err = AuditErrorResponse(
            error="model_unavailable",
            message=f"Unexpected error: {e}",
        )
        raise HTTPException(status_code=503, detail=err.model_dump())


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
