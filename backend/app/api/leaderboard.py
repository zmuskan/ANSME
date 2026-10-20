from __future__ import annotations

from typing import Any, Sequence
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user_id
from app.db.database import get_db
from app.models.analysis import Analysis
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.user_preference_repository import UserPreferenceRepository

router = APIRouter(prefix="/leaderboard", tags=["Leaderboard"])


def _sanitize_public_url(url: str) -> str | None:
    """Return a public HTTP(S) URL without credentials, query, or fragment."""
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None

    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        return None

    host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path, "", ""))


def _serialize(rows: Sequence[Analysis]) -> list[dict[str, Any]]:
    serialized = []
    for row in rows:
        public_url = _sanitize_public_url(row.url)
        serialized.append(
            {
                "title": row.title or public_url or "Product",
                "url": public_url,
                "overall_score": row.overall_score,
                "verdict": row.verdict,
                "category": row.category,
            }
        )
    return serialized


class LeaderboardParticipationRequest(BaseModel):
    enabled: bool


@router.get("/participation")
def get_leaderboard_participation(
    db: Session = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> dict[str, bool]:
    return {
        "enabled": UserPreferenceRepository.get_share_to_leaderboard(db, user_id)
    }


@router.put("/participation")
def set_leaderboard_participation(
    request: LeaderboardParticipationRequest,
    db: Session = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> dict[str, bool]:
    UserPreferenceRepository.set_share_to_leaderboard(
        db,
        user_id,
        request.enabled,
    )
    return {"enabled": request.enabled}


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
