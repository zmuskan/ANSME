from __future__ import annotations

from typing import Any, Sequence

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.analysis import Analysis
from app.repositories.analysis_repository import AnalysisRepository

router = APIRouter(prefix="/leaderboard", tags=["Leaderboard"])


def _serialize(rows: Sequence[Analysis]) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "title": row.title or row.url,
            "url": row.url,
            "overall_score": row.overall_score,
            "verdict": row.verdict,
            "category": row.category,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("")
def leaderboard(
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    rows = AnalysisRepository.get_leaderboard(db, limit=limit)
    return {
        "highest": _serialize(list(rows["highest"])),
        "lowest": _serialize(list(rows["lowest"])),
    }
