"""
History API routes.

Provides read access to previously saved analyses.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user_id
from app.db.database import get_db
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.price_history_repository import PriceHistoryRepository

router = APIRouter(prefix="/history", tags=["History"])


@router.get("")
def list_history(
    limit: int = 100,
    db: Session = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
):
    """
    Return recent analyses ordered newest first.
    """

    analyses = AnalysisRepository.list_analyses(
        db=db,
        user_id=user_id,
        limit=limit,
    )

    return [
        {
            "id": analysis.id,
            "url": analysis.url,
            "title": analysis.title,
            "brand": analysis.brand,
            "price": analysis.price,
            "price_raw": analysis.price_raw,
            "price_currency": analysis.price_currency,
            "rating": analysis.rating,
            "overall_score": analysis.overall_score,
            "verdict": analysis.verdict,
            "category": analysis.category,
            "review_count": analysis.review_count,
            "sentiment_score": analysis.sentiment_score,
            "requirement_match": analysis.requirement_match,
            "pros": analysis.pros,
            "cons": analysis.cons,
            "risk_flags": analysis.risk_flags,
            "explanation": analysis.explanation,
            "created_at": analysis.created_at,
        }
        for analysis in analyses
    ]


@router.get("/{analysis_id}")
def get_history_item(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
):
    """
    Return a single analysis by id.
    """

    analysis = AnalysisRepository.get_analysis(
        db=db,
        analysis_id=analysis_id,
        user_id=user_id,
    )

    if analysis is None:
        raise HTTPException(
            status_code=404,
            detail="Analysis not found",
        )

    evidence = EvidenceRepository.get_by_analysis(db, analysis_id)
    similar = AnalysisRepository.find_similar(db, analysis, user_id)
    price_history = PriceHistoryRepository.for_analysis(db, analysis)

    return {
        "id": analysis.id,
        "url": analysis.url,
        "title": analysis.title,
        "brand": analysis.brand,
        "price": analysis.price,
        "price_raw": analysis.price_raw,
        "price_currency": analysis.price_currency,
        "rating": analysis.rating,
        "image_url": analysis.image_url,
        "description": analysis.description,
        "overall_score": analysis.overall_score,
        "verdict": analysis.verdict,
        "sentiment_score": analysis.sentiment_score,
        "requirement_match": analysis.requirement_match,
        "pros": analysis.pros,
        "cons": analysis.cons,
        "risk_flags": analysis.risk_flags,
        "explanation": analysis.explanation,
        "metrics": analysis.metrics or {},
        "score_breakdown": analysis.score_breakdown or {},
        "processing_time_ms": analysis.processing_time_ms,
        "sources_analyzed": analysis.sources_analyzed,
        "evidence": [
            {
                "title": analysis.title or analysis.url,
                "url": analysis.url,
                "source": "Strength" if item.source_type == "pro" else "Concern",
                "score": analysis.overall_score,
                "snippet": item.evidence_text,
                "quality_score": item.quality_score,
            }
            for item in evidence
        ],
        "review_count": analysis.review_count,
        "category": analysis.category,
        "price_history": price_history,
        "similar_products": [
            {
                "id": item.id,
                "title": item.title,
                "url": item.url,
                "price": item.price,
                "overall_score": item.overall_score,
                "verdict": item.verdict,
            }
            for item in similar
        ],
        "created_at": analysis.created_at,
    }


@router.delete("/{analysis_id}")
def delete_history_item(
    analysis_id: int,
    db: Session = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
):
    """Delete a saved analysis by id."""
    deleted = AnalysisRepository.delete_analysis(
        db=db,
        analysis_id=analysis_id,
        user_id=user_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found",
        )
    return {
        "status": "success",
        "message": f"Analysis {analysis_id} deleted successfully",
    }