"""
Analysis repository.

Encapsulates all database persistence operations for the ``Analysis`` model.
This layer contains no business logic and no web-framework code; it only
translates between Python objects and rows in the ``analyses`` table.
"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import select
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
    def get_analysis(db: Session, analysis_id: int) -> Analysis | None:
        """
        Retrieve a single ``Analysis`` by its primary key.

        Args:
            db: Active SQLAlchemy session.
            analysis_id: Primary key of the analysis to fetch.

        Returns:
            The matching ``Analysis`` instance, or ``None`` if no row exists
            with the given id.
        """
        return db.get(Analysis, analysis_id)

    @staticmethod
    def list_analyses(db: Session, limit: int = 100) -> Sequence[Analysis]:
        """
        List analyses ordered from newest to oldest.

        Args:
            db: Active SQLAlchemy session.
            limit: Maximum number of rows to return. Defaults to 100.

        Returns:
            A sequence of ``Analysis`` instances ordered by ``created_at``
            descending, containing at most ``limit`` items.
        """
        statement = (
            select(Analysis)
            .order_by(Analysis.created_at.desc())
            .limit(limit)
        )
        return db.execute(statement).scalars().all()

    @staticmethod
    def delete_analysis(db: Session, analysis_id: int) -> bool:
        """
        Delete an ``Analysis`` row by its primary key.

        Args:
            db: Active SQLAlchemy session.
            analysis_id: Primary key of the analysis to delete.

        Returns:
            ``True`` if a row was found and deleted, ``False`` if no row
            exists with the given id.

        Raises:
            sqlalchemy.exc.SQLAlchemyError: If the delete or commit fails.
                The session is rolled back before the exception is re-raised.
        """
        analysis = db.get(Analysis, analysis_id)
        if analysis is None:
            return False

        try:
            db.delete(analysis)
            db.commit()
        except Exception as exc:
            db.rollback()
            raise
        return True