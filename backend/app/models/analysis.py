"""
Analysis ORM model.

Stores the result of analyzing a single product URL.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from app.db.database import Base


class Analysis(Base):
    """A persisted product analysis: extracted product data plus its verdict."""

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        index=True,
    )

    url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    title: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    brand: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    price: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    price_raw: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    price_currency: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )

    rating: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    image_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    overall_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    verdict: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    sentiment_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    requirement_match: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    pros: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    cons: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    risk_flags: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    explanation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    metrics: Mapped[dict[str, float] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    score_breakdown: Mapped[dict[str, float] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    processing_time_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    sources_analyzed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    review_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="Other",
        server_default="Other",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    evidence = relationship(
        "Evidence",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )