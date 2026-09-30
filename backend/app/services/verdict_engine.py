"""
Verdict engine.

Deterministic scoring and verdict generation for ANSME.

    Raw Product Data -> Feature Engineering -> Deterministic Scoring
        -> Verdict Generation -> LLM Explainability

This module is the "Scoring" and "Verdict" stages. The data decides; an LLM
may later explain the result but never influences it. The same inputs always
produce the same output, and every number can be recomputed by hand from the
rules documented below.

Pure Python, standard library only. No I/O, no network, no database.

Scoring rules
-------------
All scores are on a 0-10 scale, clamped, and rounded to 1 decimal place.

Value score
    * No (valid) budget ............................ 8.0  (neutral-good default)
    * Budget given, price missing/invalid .......... 5.0  (cannot be assessed)
    * price <= budget .............................. 10.0
    * price > budget ............................... 10.0 - (0.2 * percent_over_budget)
      e.g. 20% over budget -> 6.0, 50% or more over budget -> 0.0

Rating score
    * rating (0-5 scale) * 2, e.g. 4.5 -> 9.0, 4.0 -> 8.0, 3.5 -> 7.0
    * Missing or invalid rating -> 5.0

Confidence score (data quality)
    Additive and fully deterministic:

        baseline (engine always has something to work with) ...... 2.0
        valid price present ..................................... +3.5
        valid rating present .................................... +3.5
        valid budget AND valid price present (value is comparable) +1.0
                                                          maximum = 10.0

    Examples: price + rating, no budget -> 9.0; price + rating + budget ->
    10.0; price only -> 5.5; nothing usable -> 2.0.

Overall score
    0.40 * value + 0.40 * rating + 0.20 * confidence, computed from the
    already-rounded metric values so the output can be verified by hand.

Verdict (based on the rounded overall score)
    >= 8.0 -> "WORTH IT"   |   >= 6.0 -> "CONSIDER"   |   < 6.0 -> "SKIP"
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

# Value score
DEFAULT_VALUE_SCORE: Final[float] = 8.0  # no budget supplied
UNASSESSABLE_VALUE_SCORE: Final[float] = 5.0  # budget supplied, price unusable
OVER_BUDGET_PENALTY_PER_PERCENT: Final[float] = 0.1  # points lost per 1% over

# Rating score
MAX_RATING: Final[float] = 5.0
RATING_TO_SCORE_FACTOR: Final[float] = MAX_SCORE / MAX_RATING  # 5-star -> 10-point
DEFAULT_RATING_SCORE: Final[float] = 5.0  # rating missing/invalid

# Confidence score components (sum to MAX_SCORE)
CONFIDENCE_BASELINE: Final[float] = 2.0
CONFIDENCE_PRICE_WEIGHT: Final[float] = 3.5
CONFIDENCE_RATING_WEIGHT: Final[float] = 3.5
CONFIDENCE_BUDGET_WEIGHT: Final[float] = 1.0

# Overall score weights (sum to 1.0)
VALUE_WEIGHT: Final[float] = 0.40
RATING_WEIGHT: Final[float] = 0.40
CONFIDENCE_WEIGHT: Final[float] = 0.20

# Verdict thresholds
WORTH_IT_THRESHOLD: Final[float] = 8.0
CONSIDER_THRESHOLD: Final[float] = 6.0

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
        price: Product price. ``None``, non-numeric, non-finite, zero or
            negative values are treated as missing.
        rating: Product rating on a 0-5 scale. ``None``, non-numeric,
            non-finite, zero, negative or greater-than-5 values are treated
            as missing (a rating of 0 almost always means "unrated").
        budget: Optional maximum the user wants to spend. ``None``,
            non-numeric, non-finite, zero or negative values are treated as
            "no budget".

    Returns:
        A dictionary of the form::

            {
                "overall_score": 8.6,
                "verdict": "WORTH IT",
                "metrics": {
                    "value_score": 10.0,
                    "rating_score": 9.2,
                    "confidence_score": 8.5,
                },
            }
    """
    clean_price = _clean_positive(price)
    clean_budget = _clean_positive(budget)
    clean_rating = _clean_rating(rating)

    value_score = _round_score(_compute_value_score(clean_price, clean_budget))
    rating_score = _round_score(_compute_rating_score(clean_rating))
    confidence_score = _round_score(
        _compute_confidence_score(clean_price, clean_rating, clean_budget)
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

    ``price`` and ``budget`` must already be sanitized (positive, finite, or
    ``None``). Overspending is penalized proportionally: every 1% over budget
    costs ``OVER_BUDGET_PENALTY_PER_PERCENT`` points, so 20% over scores 6.0
    and 50% or more over scores 0.0.
    """
    if budget is None:
        return DEFAULT_VALUE_SCORE
    if price is None:
        return UNASSESSABLE_VALUE_SCORE
    if price <= budget:
        return MAX_SCORE

    percent_over = ((price - budget) / budget) * 100.0  # budget > 0 is guaranteed
    return _clamp(MAX_SCORE - percent_over * OVER_BUDGET_PENALTY_PER_PERCENT)


def _compute_rating_score(rating: float | None) -> float:
    """Convert a sanitized 0-5 rating to a 0-10 score; missing -> 5.0."""
    if rating is None:
        return DEFAULT_RATING_SCORE
    return _clamp(rating * RATING_TO_SCORE_FACTOR)


def _compute_confidence_score(
    price: float | None,
    rating: float | None,
    budget: float | None,
) -> float:
    """
    Score data quality (0-10) from which usable inputs are present.

    Additive formula: baseline 2.0, +3.5 for a valid price, +3.5 for a valid
    rating, +1.0 when both a budget and a price exist (so the value score is
    an actual comparison rather than a default).
    """
    score = CONFIDENCE_BASELINE
    if price is not None:
        score += CONFIDENCE_PRICE_WEIGHT
    if rating is not None:
        score += CONFIDENCE_RATING_WEIGHT
    if price is not None and budget is not None:
        score += CONFIDENCE_BUDGET_WEIGHT
    return _clamp(score)


def _compute_overall_score(
    value_score: float, rating_score: float, confidence_score: float
) -> float:
    """Weighted average (40% value, 40% rating, 20% confidence), 1 decimal."""
    weighted = (
        value_score * VALUE_WEIGHT
        + rating_score * RATING_WEIGHT
        + confidence_score * CONFIDENCE_WEIGHT
    )
    return _round_score(weighted)


def _determine_verdict(overall_score: float) -> str:
    """Map the (rounded) overall score to a verdict label."""
    if overall_score >= WORTH_IT_THRESHOLD:
        return VERDICT_WORTH_IT
    if overall_score >= CONSIDER_THRESHOLD:
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


def _clean_positive(value: Any) -> float | None:
    """Return ``value`` as a float if it is finite and > 0, else ``None``."""
    number = _to_float(value)
    if number is None or number <= 0.0:
        return None
    return number


def _clean_rating(value: Any) -> float | None:
    """Return a rating in the half-open range (0, 5], else ``None``."""
    number = _clean_positive(value)
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

    Uses ``Decimal`` on the float's shortest repr so values like 8.25 round
    to 8.3 rather than following binary floating-point or banker's rounding.
    """
    clamped = _clamp(value)
    rounded = Decimal(repr(clamped)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(rounded)