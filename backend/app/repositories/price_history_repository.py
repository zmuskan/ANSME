from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.analysis import Analysis
from app.models.price_history import PriceHistory


class PriceHistoryRepository:
    @staticmethod
    def create(
        db: Session,
        analysis_id: int,
        price: float,
        price_raw: str | None = None,
        price_currency: str | None = None,
    ) -> PriceHistory:
        row = PriceHistory(
            analysis_id=analysis_id,
            price=price,
            price_raw=price_raw,
            price_currency=price_currency,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def for_analysis(db: Session, analysis: Analysis) -> dict[str, Any]:
        rows = (
            db.query(PriceHistory)
            .filter(PriceHistory.analysis_id == analysis.id)
            .order_by(PriceHistory.captured_at.asc())
            .all()
        )
        prices = [float(row.price) for row in rows]
        currencies = {row.price_currency for row in rows}
        common_currency = (
            next(iter(currencies))
            if rows and len(currencies) == 1 and None not in currencies
            else None
        )
        return {
            "history": [
                {
                    "price": float(row.price),
                    "price_raw": row.price_raw,
                    "price_currency": row.price_currency,
                    "captured_at": row.captured_at.isoformat(),
                }
                for row in rows
            ],
            "lowest_seen": min(prices) if common_currency else None,
            "highest_seen": max(prices) if common_currency else None,
            "common_currency": common_currency,
        }
