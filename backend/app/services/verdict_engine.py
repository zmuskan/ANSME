"""
Verdict engine.

The deterministic decision layer of ANSME.

    Product URL -> Product Extractor -> Feature Engineering -> Verdict Engine
        -> API Response -> Database -> LLM Explanation Layer

The data decides; an LLM may later explain the result but never influences
it. The same inputs always produce the same output, and every number can be
recomputed by hand from the rules below. This module is pure Python with no
I/O, no side effects and no third-party dependencies.

Scoring rules
-------------
All scores are on a 0-10 scale, clamped, and rounded to 1 decimal place.

Value score
    * No (valid) budget ............ 7.0
    * Budget given, price unusable . 5.0  (value cannot be assessed)
    * price <= budget .............. 10.0
    * price > budget ............... 10.0 - (10.0 * over_budget_ratio)
      where over_budget_ratio = (price - budget) / budget.
      Example: 20% over budget -> 8.0; 100% or more over budget -> 0.0.

Rating score
    * rating (0-5 scale) * 2, e.g. 4.5 -> 9.0, 4.0 -> 8.0, 3.5 -> 7.0
    * Missing or invalid rating -> 5.0

Confidence score (confidence in the extracted data, not sentiment)
    * price and rating both usable .. 10.0
    * exactly one usable ............ 7.0
    * neither usable ................ 3.0

Overall score
    0.45 * value + 0.45 * rating + 0.10 * confidence, computed from the
    already-rounded metric values so the output can be verified by hand,
    then clamped to 0-10 and rounded to 1 decimal place.

Verdict (based on the rounded overall score)
    >= 8.0 -> "WORTH IT"  |  >= 6.0 and < 8.0 -> "CONSIDER"  |  < 6.0 -> "SKIP"

Input handling
--------------
``None``, non-numeric, NaN, infinite, zero and negative values for price or
budget are treated as missing. A rating is treated as missing unless it is
in the range (0, 5]; a rating of 0 almost always means "unrated" on scraped
pages, and values above 5 indicate bad data.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

__all__ = ["compute_verdict"]

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

MIN_SCORE: Final[float] = 0.0
MAX_SCORE: Final[float] = 10.0
SCORE_PRECISION: Final[Decimal] = Decimal("0.1")

# Value score
VALUE_SCORE_NO_BUDGET: Final[float] = 7.0
VALUE_SCORE_UNASSESSABLE: Final[float] = 5.0
VALUE_SCORE_WITHIN_BUDGET: Final[float] = MAX_SCORE
OVER_BUDGET_PENALTY_PER_RATIO: Final[float] = 10.0  # points lost per 1.0 (100%) over

# Rating score
MAX_RATING: Final[float] = 5.0
RATING_SCALE_FACTOR: Final[float] = MAX_SCORE / MAX_RATING  # 0-5 -> 0-10
RATING_SCORE_MISSING: Final[float] = 5.0

# Confidence score
CONFIDENCE_SCORE_FULL: Final[float] = 10.0  # price and rating present
CONFIDENCE_SCORE_PARTIAL: Final[float] = 7.0  # exactly one present
CONFIDENCE_SCORE_NONE: Final[float] = 3.0  # neither present

# Overall score weights (sum to 1.0)
WEIGHT_VALUE: Final[float] = 0.45
WEIGHT_RATING: Final[float] = 0.45
WEIGHT_CONFIDENCE: Final[float] = 0.10

# Verdict thresholds and labels
THRESHOLD_WORTH_IT: Final[float] = 8.0
THRESHOLD_CONSIDER: Final[float] = 6.0

VERDICT_WORTH_IT: Final[str] = "WORTH IT"
VERDICT_CONSIDER: Final[str] = "CONSIDER"
VERDICT_SKIP: Final[str] = "SKIP"


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def compute_verdict(
    *,
    price: float | None,
    rating: float | None,
    budget: float | None = None,
) -> dict[str, Any]:
    """
    Convert product features into a deterministic recommendation.

    Args:
        price: Product price. Invalid or non-positive values count as missing.
        rating: Product rating on a 0-5 scale. Values outside (0, 5] count as
            missing.
        budget: Optional maximum the user wants to spend. Invalid or
            non-positive values count as "no budget".

    Returns:
        ``{"overall_score": float, "verdict": str, "metrics": {"value_score":
        float, "rating_score": float, "confidence_score": float}}``

    Example:
        >>> compute_verdict(price=90000, rating=4.8, budget=100000)
        {'overall_score': 9.8, 'verdict': 'WORTH IT', 'metrics': {'value_score': 10.0, 'rating_score': 9.6, 'confidence_score': 10.0}}
    """
    clean_price = _sanitize_positive(price)
    clean_budget = _sanitize_positive(budget)
    clean_rating = _sanitize_rating(rating)

    value_score = _round_score(_compute_value_score(clean_price, clean_budget))
    rating_score = _round_score(_compute_rating_score(clean_rating))
    confidence_score = _round_score(
        _compute_confidence_score(clean_price, clean_rating)
    )

    overall_score = _compute_overall_score(value_score, rating_score, confidence_score)

    return {
        "overall_score": overall_score,
        "verdict": _determine_verdict(overall_score),
        "metrics": {
            "value_score": value_score,
            "rating_score": rating_score,
            "confidence_score": confidence_score,
        },
    }


# --------------------------------------------------------------------------- #
# Score computation
# --------------------------------------------------------------------------- #


def _compute_value_score(price: float | None, budget: float | None) -> float:
    """
    Score how well the price fits the budget (0-10).

    Inputs must already be sanitized (positive and finite, or ``None``).
    Overspending is deducted proportionally to the over-budget ratio, and the
    result never goes below 0.
    """
    if budget is None:
        return VALUE_SCORE_NO_BUDGET
    if price is None:
        return VALUE_SCORE_UNASSESSABLE
    if price <= budget:
        return VALUE_SCORE_WITHIN_BUDGET

    over_budget_ratio = (price - budget) / budget  # budget > 0 is guaranteed
    return _clamp(
        VALUE_SCORE_WITHIN_BUDGET - over_budget_ratio * OVER_BUDGET_PENALTY_PER_RATIO
    )


def _compute_rating_score(rating: float | None) -> float:
    """Convert a sanitized 0-5 rating to a 0-10 score; missing -> 5.0."""
    if rating is None:
        return RATING_SCORE_MISSING
    return _clamp(rating * RATING_SCALE_FACTOR)


def _compute_confidence_score(price: float | None, rating: float | None) -> float:
    """
    Score confidence in the extracted data (0-10), not sentiment.

    Both fields present -> 10.0, exactly one present -> 7.0, neither -> 3.0.
    """
    present_count = sum(value is not None for value in (price, rating))
    if present_count == 2:
        return CONFIDENCE_SCORE_FULL
    if present_count == 1:
        return CONFIDENCE_SCORE_PARTIAL
    return CONFIDENCE_SCORE_NONE


def _compute_overall_score(
    value_score: float,
    rating_score: float,
    confidence_score: float,
) -> float:
    """Weighted blend of the three metrics, clamped to 0-10 and rounded."""
    weighted = (
        WEIGHT_VALUE * value_score
        + WEIGHT_RATING * rating_score
        + WEIGHT_CONFIDENCE * confidence_score
    )
    return _round_score(weighted)


def _determine_verdict(overall_score: float) -> str:
    """Map the (rounded) overall score to a verdict label."""
    if overall_score >= THRESHOLD_WORTH_IT:
        return VERDICT_WORTH_IT
    if overall_score >= THRESHOLD_CONSIDER:
        return VERDICT_CONSIDER
    return VERDICT_SKIP


# --------------------------------------------------------------------------- #
# Input sanitization
# --------------------------------------------------------------------------- #


def _to_float(value: Any) -> float | None:
    """
    Coerce ``value`` to a finite float, or return ``None``.

    Accepts ints, floats and numeric strings. Rejects ``None``, booleans,
    NaN, infinities and anything that cannot be parsed.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _sanitize_positive(value: Any) -> float | None:
    """Return ``value`` as a float if it is finite and > 0, else ``None``."""
    number = _to_float(value)
    if number is None or number <= 0.0:
        return None
    return number


def _sanitize_rating(value: Any) -> float | None:
    """Return a rating in the range (0, 5], else ``None``."""
    number = _sanitize_positive(value)
    if number is None or number > MAX_RATING:
        return None
    return number


# --------------------------------------------------------------------------- #
# Numeric helpers
# --------------------------------------------------------------------------- #


def _clamp(value: float, lower: float = MIN_SCORE, upper: float = MAX_SCORE) -> float:
    """Clamp ``value`` into ``[lower, upper]``; NaN collapses to ``lower``."""
    if math.isnan(value):
        return lower
    return max(lower, min(upper, value))


def _round_score(value: float) -> float:
    """
    Clamp to 0-10 and round half-up to 1 decimal place.

    Uses ``Decimal`` on the float's shortest repr so values such as 8.25
    round to 8.3 instead of following binary floating-point or banker's
    rounding.
    """
    clamped = _clamp(value)
    return float(Decimal(repr(clamped)).quantize(SCORE_PRECISION, rounding=ROUND_HALF_UP))