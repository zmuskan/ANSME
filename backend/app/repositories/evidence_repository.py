from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.evidence import Evidence


class EvidenceRepository:
    """
    Repository for Evidence persistence.
    """

    @staticmethod
    def create(
        db: Session,
        analysis_id: int,
        source_type: str,
        evidence_text: str,
    ) -> Evidence:
        evidence = Evidence(
            analysis_id=analysis_id,
            source_type=source_type,
            evidence_text=evidence_text,
        )

        db.add(evidence)
        db.commit()
        db.refresh(evidence)

        return evidence

    @staticmethod
    def get_by_analysis(
        db: Session,
        analysis_id: int,
    ) -> list[Evidence]:
        return (
            db.query(Evidence)
            .filter(Evidence.analysis_id == analysis_id)
            .order_by(Evidence.created_at.desc())
            .all()
        )

    @staticmethod
    def delete(
        db: Session,
        evidence_id: int,
    ) -> bool:
        evidence = (
            db.query(Evidence)
            .filter(Evidence.id == evidence_id)
            .first()
        )

        if not evidence:
            return False

        db.delete(evidence)
        db.commit()

        return True