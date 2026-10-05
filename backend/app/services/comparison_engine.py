"""
Comparison engine.

Compares two already-analyzed products and produces a structured,
human-readable comparison plus a winner.

This module is **deterministic Python only**: no database access, no web
framework code, no AI APIs. The same inputs always produce the same output.

Public API:
    compare_products: Compare ``product_a`` against ``product_b``.

Winner rules (applied in order):
    1. Higher ``overall_score`` wins, unless the gap is within
       ``SCORE_TIE_TOLERANCE``.
    2. Otherwise the higher ``rating`` wins.
    3. Otherwise the lower ``price`` wins.
    4. Otherwise the result is a ``"tie"``.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

#: Overall-score gaps at or below this value are treated as equal.
SCORE_TIE_TOLERANCE: float = 0.05

#: Maximum characters of a product title used inside comparison sentences.
MAX_LABEL_LENGTH: int = 60


def compare_products(
    product_a: Mapping[str, Any],
    product_b: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Compare two analyzed products.

    Args:
        product_a: First product. Recognised keys: ``title``, ``price``,
            ``rating``, ``overall_score``, ``verdict``. All are optional.
        product_b: Second product, with the same keys.

    Returns:
        A dictionary with structured winner details, dimension breakdowns,
        strengths/weaknesses, and an evidence block.

    Raises:
        TypeError: If either argument is not a mapping.
    """
    if not isinstance(product_a, Mapping) or not isinstance(product_b, Mapping):
        raise TypeError("product_a and product_b must be mappings.")

    name_a = _label(product_a, "Product A")
    name_b = _label(product_b, "Product B")

    score_a = _score_or_zero(product_a)
    score_b = _score_or_zero(product_b)
    price_a = _to_float(product_a.get("price"))
    price_b = _to_float(product_b.get("price"))
    rating_a = _to_float(product_a.get("rating"))
    rating_b = _to_float(product_b.get("rating"))

    winner_key = _pick_winner_key(score_a, score_b, rating_a, rating_b, price_a, price_b)
    winner_title = name_a if winner_key == "product_a" else (name_b if winner_key == "product_b" else "tie")

    return {
        "winner": winner_title,
        "winning_key": winner_key,
        "score_difference": round(abs(score_a - score_b), 2),
        "dimension_winners": {
            "overall_winner": _dimension_winner(score_a, score_b, name_a, name_b, higher_is_better=True),
            "rating_winner": _dimension_winner(rating_a, rating_b, name_a, name_b, higher_is_better=True),
            "price_winner": _dimension_winner(price_a, price_b, name_a, name_b, higher_is_better=False),
        },
        "comparison": {
            "price": _compare_price(price_a, price_b, name_a, name_b),
            "rating": _compare_rating(rating_a, rating_b, name_a, name_b),
            "overall": _compare_overall(product_a, product_b, name_a, name_b, score_a, score_b),
        },
        "strengths_and_weaknesses": {
            "product_a": _extract_traits(product_a, product_b, score_a, score_b, price_a, price_b, rating_a, rating_b),
            "product_b": _extract_traits(product_b, product_a, score_b, score_a, price_b, price_a, rating_b, rating_a),
        },
        "evidence": {
            "product_a": {"title": name_a, "price": price_a, "rating": rating_a, "overall_score": score_a},
            "product_b": {"title": name_b, "price": price_b, "rating": rating_b, "overall_score": score_b},
        },
    }


# --------------------------------------------------------------------------- #
# Winner selection
# --------------------------------------------------------------------------- #


def _pick_winner_key(
    score_a: float,
    score_b: float,
    rating_a: float | None,
    rating_b: float | None,
    price_a: float | None,
    price_b: float | None,
) -> str:
    """Apply winner rules returning 'product_a', 'product_b', or 'tie'."""
    if abs(score_a - score_b) > SCORE_TIE_TOLERANCE:
        return "product_a" if score_a > score_b else "product_b"

    if rating_a is not None and rating_b is not None and rating_a != rating_b:
        return "product_a" if rating_a > rating_b else "product_b"

    if price_a is not None and price_b is not None and price_a != price_b:
        return "product_a" if price_a < price_b else "product_b"

    return "tie"


def _dimension_winner(
    val_a: float | None,
    val_b: float | None,
    name_a: str,
    name_b: str,
    higher_is_better: bool = True,
) -> str:
    """Return name of dimension winner or 'tie' / 'N/A'."""
    if val_a is None and val_b is None:
        return "N/A"
    if val_a is None:
        return name_b
    if val_b is None:
        return name_a
    if val_a == val_b:
        return "tie"

    if higher_is_better:
        return name_a if val_a > val_b else name_b
    return name_a if val_a < val_b else name_b


# --------------------------------------------------------------------------- #
# Trait Extraction (Strengths / Weaknesses)
# --------------------------------------------------------------------------- #


def _extract_traits(
    target: Mapping[str, Any],
    opponent: Mapping[str, Any],
    target_score: float,
    opp_score: float,
    target_price: float | None,
    opp_price: float | None,
    target_rating: float | None,
    opp_rating: float | None,
) -> dict[str, list[str]]:
    """Extract human-readable strengths and weaknesses relative to the opponent."""
    strengths: list[str] = []
    weaknesses: list[str] = []

    # Score comparison
    if target_score > opp_score + SCORE_TIE_TOLERANCE:
        strengths.append(f"Higher overall score ({target_score:.1f} vs {opp_score:.1f})")
    elif target_score < opp_score - SCORE_TIE_TOLERANCE:
        weaknesses.append(f"Lower overall score ({target_score:.1f} vs {opp_score:.1f})")

    # Price comparison
    if target_price is not None and opp_price is not None:
        if target_price < opp_price:
            strengths.append(f"More affordable ({_fmt_number(target_price)} vs {_fmt_number(opp_price)})")
        elif target_price > opp_price:
            weaknesses.append(f"More expensive ({_fmt_number(target_price)} vs {_fmt_number(opp_price)})")

    # Rating comparison
    if target_rating is not None and opp_rating is not None:
        if target_rating > opp_rating:
            strengths.append(f"Higher user rating ({target_rating:.1f} vs {opp_rating:.1f})")
        elif target_rating < opp_rating:
            weaknesses.append(f"Lower user rating ({target_rating:.1f} vs {opp_rating:.1f})")

    return {
        "strengths": strengths or ["Comparable baseline performance"],
        "weaknesses": weaknesses or ["No significant competitive drawbacks"],
    }


# --------------------------------------------------------------------------- #
# Dimension comparisons
# --------------------------------------------------------------------------- #


def _compare_price(
    price_a: float | None,
    price_b: float | None,
    name_a: str,
    name_b: str,
) -> str:
    """Describe the price relationship (lower price is better)."""
    if price_a is None and price_b is None:
        return "Price is unavailable for both products."
    if price_a is None:
        return f"Price is unavailable for {name_a}; {name_b} costs {_fmt_number(price_b)}."
    if price_b is None:
        return f"Price is unavailable for {name_b}; {name_a} costs {_fmt_number(price_a)}."
    if price_a == price_b:
        return f"Both products cost {_fmt_number(price_a)}."

    if price_a < price_b:
        cheaper, pricier, low, high = name_a, name_b, price_a, price_b
    else:
        cheaper, pricier, low, high = name_b, name_a, price_b, price_a

    difference = high - low
    sentence = f"{cheaper} is cheaper by {_fmt_number(difference)}"
    if high > 0:
        sentence += f" ({difference / high * 100:.1f}% less than {pricier})"
    return sentence + "."


def _compare_rating(
    rating_a: float | None,
    rating_b: float | None,
    name_a: str,
    name_b: str,
) -> str:
    """Describe the rating relationship (higher rating is better)."""
    if rating_a is None and rating_b is None:
        return "Rating is unavailable for both products."
    if rating_a is None:
        return f"Rating is unavailable for {name_a}; {name_b} is rated {rating_b:.1f}."
    if rating_b is None:
        return f"Rating is unavailable for {name_b}; {name_a} is rated {rating_a:.1f}."
    if rating_a == rating_b:
        return f"Both products have the same rating ({rating_a:.1f})."

    higher = name_a if rating_a > rating_b else name_b
    return (
        f"{higher} has the higher rating "
        f"({max(rating_a, rating_b):.1f} vs {min(rating_a, rating_b):.1f})."
    )


def _compare_overall(
    product_a: Mapping[str, Any],
    product_b: Mapping[str, Any],
    name_a: str,
    name_b: str,
    score_a: float,
    score_b: float,
) -> str:
    """Describe the overall-score relationship, including verdicts if known."""
    verdict_a = _verdict(product_a)
    verdict_b = _verdict(product_b)

    if abs(score_a - score_b) <= SCORE_TIE_TOLERANCE:
        sentence = f"Both products have essentially the same overall score ({score_a:.1f})"
    else:
        leader = name_a if score_a > score_b else name_b
        sentence = (
            f"{leader} scores higher overall "
            f"({max(score_a, score_b):.1f} vs {min(score_a, score_b):.1f})"
        )

    if verdict_a and verdict_b:
        sentence += f"; verdicts are {verdict_a} for {name_a} and {verdict_b} for {name_b}"
    return sentence + "."


# --------------------------------------------------------------------------- #
# Utilities
# --------------------------------------------------------------------------- #


def _to_float(value: Any) -> float | None:
    """Return ``value`` as a finite float, or ``None`` if missing or invalid."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _score_or_zero(product: Mapping[str, Any]) -> float:
    """Return the product's ``overall_score`` or ``0.0`` when unavailable."""
    score = _to_float(product.get("overall_score"))
    if score is None:
        score = _to_float(product.get("final_score"))
    return score if score is not None else 0.0


def _verdict(product: Mapping[str, Any]) -> str | None:
    """Return the upper-cased verdict string, or ``None`` if absent."""
    verdict = product.get("verdict")
    if isinstance(verdict, str) and verdict.strip():
        return verdict.strip().upper()
    return None


def _label(product: Mapping[str, Any], fallback: str) -> str:
    """Return a short display name for the product (title or fallback)."""
    title = product.get("title")
    if isinstance(title, str) and title.strip():
        text = title.strip()
        if len(text) > MAX_LABEL_LENGTH:
            text = text[: MAX_LABEL_LENGTH - 1].rstrip() + "…"
        return text
    return fallback


def _fmt_number(value: float | None) -> str:
    """Format a number with thousands separators, dropping a trailing ``.00``."""
    if value is None:
        return "N/A"
    if float(value).is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}"