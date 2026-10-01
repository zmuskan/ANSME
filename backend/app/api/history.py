"""
History API routes.

Provides read access to previously saved analyses.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.repositories.analysis_repository import AnalysisRepository

router = APIRouter(prefix="/history", tags=["History"])


@router.get("")
def list_history(
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    Return recent analyses ordered newest first.
    """

    analyses = AnalysisRepository.list_analyses(
        db=db,
        limit=limit,
    )

    return [
        {
            "id": analysis.id,
            "url": analysis.url,
            "title": analysis.title,
            "brand": analysis.brand,
            "price": analysis.price,
            "rating": analysis.rating,
            "overall_score": analysis.overall_score,
            "verdict": analysis.verdict,
            "created_at": analysis.created_at,
        }
        for analysis in analyses
    ]


@router.get("/{analysis_id}")
def get_history_item(
    analysis_id: int,
    db: Session = Depends(get_db),
):
    """
    Return a single analysis by id.
    """

    analysis = AnalysisRepository.get_analysis(
        db=db,
        analysis_id=analysis_id,
    )

    if analysis is None:
        raise HTTPException(
            status_code=404,
            detail="Analysis not found",
        )

    return {
        "id": analysis.id,
        "url": analysis.url,
        "title": analysis.title,
        "brand": analysis.brand,
        "price": analysis.price,
        "rating": analysis.rating,
        "image_url": analysis.image_url,
        "description": analysis.description,
        "overall_score": analysis.overall_score,
        "verdict": analysis.verdict,
        "created_at": analysis.created_at,
    }