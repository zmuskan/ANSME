from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.user_preference import UserPreference


class UserPreferenceRepository:
    @staticmethod
    def get_share_to_leaderboard(db: Session, user_id: UUID) -> bool:
        preference = db.get(UserPreference, user_id)
        return preference.share_to_leaderboard if preference else False

    @staticmethod
    def set_share_to_leaderboard(
        db: Session,
        user_id: UUID,
        enabled: bool,
    ) -> None:
        preference = db.get(UserPreference, user_id)
        if preference is None:
            preference = UserPreference(
                user_id=user_id,
                share_to_leaderboard=enabled,
            )
            db.add(preference)
        else:
            preference.share_to_leaderboard = enabled

        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
