from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user_id
from app.db.database import get_db
from app.repositories.analysis_repository import AnalysisRepository
from app.services.comparison_engine import compare_products
from app.services.explanation_engine import generate_explanation
from app.services.review_analysis_engine import analyze_reviews
from app.services.retrieval_engine import retrieve_relevant_evidence

router = APIRouter(prefix="/analytics", tags=["Analytics"])


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------


class ReviewAnalysisRequest(BaseModel):
    reviews: list[str] = Field(default_factory=list)


class CompareRequest(BaseModel):
    product_a: dict[str, Any]
    product_b: dict[str, Any]


class ExplanationRequest(BaseModel):
    overall_score: float | None = None
    metrics: dict[str, Any] | None = None
    verdict: str | None = None


class RetrievalRequest(BaseModel):
    query: str
    evidence: list[dict[str, Any]]
    limit: int = 5


# ------------------------------------------------------------------
# Review Analysis
# ------------------------------------------------------------------


@router.post("/review-analysis")
async def review_analysis(
    request: ReviewAnalysisRequest,
) -> dict[str, Any]:
    """
    Analyze review text.

    Example:
    {
        "reviews": [
            "Amazing battery life",
            "Very expensive phone"
        ]
    }
    """

    return analyze_reviews(request.reviews)


# ------------------------------------------------------------------
# Product Comparison
# ------------------------------------------------------------------


@router.get("")
async def analytics_summary(
    days: int | None = Query(default=None, ge=1, le=3650),
    db: Session = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> dict[str, Any]:
    """Return aggregated analytics, optionally limited to recent days."""
    return AnalysisRepository.get_analytics(db, user_id=user_id, days=days)


@router.post("/compare")
async def compare(
    request: CompareRequest,
) -> dict[str, Any]:
    """
    Compare two analyzed products.
    """

    return compare_products(
        request.product_a,
        request.product_b,
    )


# ------------------------------------------------------------------
# Explanation
# ------------------------------------------------------------------


@router.post("/explain")
async def explain(
    request: ExplanationRequest,
) -> dict[str, Any]:
    """
    Generate structured explanation.
    """

    return generate_explanation(
        overall_score=request.overall_score,
        metrics=request.metrics,
        verdict=request.verdict,
    )


# ------------------------------------------------------------------
# Retrieval
# ------------------------------------------------------------------


@router.post("/retrieve")
async def retrieve(
    request: RetrievalRequest,
) -> dict[str, Any]:
    """
    Retrieve evidence snippets relevant
    to a user query.
    """

    matches = retrieve_relevant_evidence(
        evidence=request.evidence,
        query=request.query,
        limit=request.limit,
    )

    return {
        "query": request.query,
        "match_count": len(matches),
        "results": matches,
    }