from __future__ import annotations

from uuid import UUID

from sqlalchemy import Boolean, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    share_to_leaderboard: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
