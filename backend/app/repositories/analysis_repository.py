"""
Analysis repository.

Encapsulates all database persistence operations for the ``Analysis`` model.
This layer contains no business logic and no web-framework code; it only
translates between Python objects and rows in the ``analyses`` table.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.analysis import Analysis


class AnalysisRepository:
    """Data-access object for ``Analysis`` records."""

    @staticmethod
    def create_analysis(db: Session, data: dict[str, Any]) -> Analysis:
        """
        Create and persist a new ``Analysis`` row.

        Args:
            db: Active SQLAlchemy session.
            data: Mapping of ``Analysis`` column names to values
                (e.g. ``url``, ``title``, ``brand``, ``price``, ``rating``,
                ``image_url``, ``description``, ``overall_score``, ``verdict``).

        Returns:
            The newly created and refreshed ``Analysis`` instance, including
            database-generated fields such as ``id`` and ``created_at``.

        Raises:
            sqlalchemy.exc.SQLAlchemyError: If the insert or commit fails.
                The session is rolled back before the exception is re-raised.
        """
        analysis = Analysis(**data)
        try:
            db.add(analysis)
            db.commit()
            db.refresh(analysis)
        except Exception:
            db.rollback()
            raise
        return analysis

    @staticmethod
    def get_analysis(
        db: Session,
        analysis_id: int,
        user_id: UUID,
    ) -> Analysis | None:
        """
        Retrieve a single ``Analysis`` by its primary key.

        Args:
            db: Active SQLAlchemy session.
            analysis_id: Primary key of the analysis to fetch.
            user_id: Authenticated owner of the analysis.

        Returns:
            The matching ``Analysis`` instance, or ``None`` if no row exists
            with the given id.
        """
        statement = select(Analysis).where(
            Analysis.id == analysis_id,
            Analysis.user_id == user_id,
        )
        return db.execute(statement).scalar_one_or_none()

    @staticmethod
    def list_analyses(
        db: Session,
        user_id: UUID,
        limit: int = 100,
    ) -> Sequence[Analysis]:
        """
        List analyses ordered from newest to oldest.

        Args:
            db: Active SQLAlchemy session.
            user_id: Authenticated owner whose analyses are returned.
            limit: Maximum number of rows to return. Defaults to 100.

        Returns:
            A sequence of ``Analysis`` instances ordered by ``created_at``
            descending, containing at most ``limit`` items.
        """
        statement = (
            select(Analysis)
            .where(Analysis.user_id == user_id)
            .order_by(Analysis.created_at.desc())
            .limit(limit)
        )
        return db.execute(statement).scalars().all()

    @staticmethod
    def delete_analysis(
        db: Session,
        analysis_id: int,
        user_id: UUID,
    ) -> bool:
        """
        Delete an ``Analysis`` row by its primary key.

        Args:
            db: Active SQLAlchemy session.
            analysis_id: Primary key of the analysis to delete.
            user_id: Authenticated owner of the analysis.

        Returns:
            ``True`` if a row was found and deleted, ``False`` if no row
            exists with the given id.

        Raises:
            sqlalchemy.exc.SQLAlchemyError: If the delete or commit fails.
                The session is rolled back before the exception is re-raised.
        """
        analysis = db.execute(
            select(Analysis).where(
                Analysis.id == analysis_id,
                Analysis.user_id == user_id,
            )
        ).scalar_one_or_none()
        if analysis is None:
            return False

        try:
            db.delete(analysis)
            db.commit()
        except Exception:
            db.rollback()
            raise
        return True

    @staticmethod
    def get_analytics(db: Session, days: int | None = None) -> dict[str, Any]:
        """Aggregate analysis, category, source, and score-trend data."""
        records = db.query(Analysis)
        if days is not None:
            records = records.filter(
                Analysis.created_at >= datetime.now(timezone.utc) - timedelta(days=days)
            )

        total_analyses = records.with_entities(func.count(Analysis.id)).scalar() or 0
        sources_analyzed = records.with_entities(
            func.sum(Analysis.sources_analyzed)
        ).scalar() or 0
        avg_score = records.with_entities(
            func.avg(Analysis.overall_score)
        ).scalar() or 0.0
        worth_it_count = records.filter(Analysis.verdict == "WORTH IT").count()
        consider_count = records.filter(Analysis.verdict == "CONSIDER").count()
        skip_count = records.filter(Analysis.verdict == "SKIP").count()
        trend_rows = (
            records.with_entities(
                func.date(Analysis.created_at).label("date"),
                func.avg(Analysis.overall_score).label("score"),
            )
            .group_by(func.date(Analysis.created_at))
            .order_by(func.date(Analysis.created_at).desc())
            .limit(90 if days is None else min(days, 90))
            .all()
        )
        history = [
            {"date": str(row.date), "score": float(row.score or 0)}
            for row in reversed(trend_rows)
        ]
        category_rows = (
            records.with_entities(
                Analysis.category.label("category"),
                func.count(Analysis.id).label("analysis_count"),
                func.avg(Analysis.overall_score).label("avg_score"),
            )
            .group_by(Analysis.category)
            .all()
        )
        categories = [
            {
                "category": row.category or "Other",
                "count": int(row.analysis_count),
                "avg_score": float(row.avg_score or 0),
            }
            for row in category_rows
        ]
        top_category = max(categories, key=lambda item: item["count"], default=None)
        source_counts: dict[str, int] = {}
        for url, in records.with_entities(Analysis.url).all():
            domain = (urlparse(url).hostname or "").lower().removeprefix("www.")
            if domain:
                source_counts[domain] = source_counts.get(domain, 0) + 1
        top_sources = [
            {"domain": domain, "count": count}
            for domain, count in sorted(
                source_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:10]
        ]

        return {
            "total_analyses": total_analyses,
            "sources_analyzed": sources_analyzed,
            "avg_score": avg_score,
            "worth_it_count": worth_it_count,
            "consider_count": consider_count,
            "skip_count": skip_count,
            "history": history,
            "categories": categories,
            "most_analyzed_category": top_category,
            "top_sources": top_sources,
        }

    @staticmethod
    def find_similar(
        db: Session,
        analysis: Analysis,
        user_id: UUID,
        limit: int = 5,
    ) -> Sequence[Analysis]:
        """Find similarly titled products using a title-derived ILIKE pattern."""
        title = (analysis.title or "").strip()
        search_terms = " ".join(title.split()[:2])
        if search_terms == "":
            return []
        return (
            db.query(Analysis)
            .filter(
                Analysis.id != analysis.id,
                Analysis.user_id == user_id,
                Analysis.title.ilike(f"%{search_terms}%"),
            )
            .order_by(Analysis.overall_score.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_leaderboard(db: Session, limit: int = 10) -> dict[str, Sequence[Analysis]]:
        """Return top and bottom scored persisted analyses."""
        return {
            "highest": (
                db.query(Analysis)
                .order_by(Analysis.overall_score.desc(), Analysis.created_at.desc())
                .limit(limit)
                .all()
            ),
            "lowest": (
                db.query(Analysis)
                .order_by(Analysis.overall_score.asc(), Analysis.created_at.desc())
                .limit(limit)
                .all()
            ),
        }