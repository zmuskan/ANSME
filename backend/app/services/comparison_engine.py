
"""
Deterministic, evidence-aware product comparison engine.

No database access, web requests, LLM calls, or external dependencies.

Public API:
    compare_products(product_a, product_b) -> dict

Decision priority:
    1. Lower price, when both prices and currencies are verified and comparable.
    2. Better requirements match, when both matches can be assessed.
    3. Availability of actual customer reviews.
    4. More positive review sentiment, when comparable sentiment evidence exists.
    5. Higher published rating.
    6. Higher overall score.
    7. Tie when the available evidence cannot distinguish the products.

Important:
    Missing data is not treated as zero.
    Unknown review availability is not the same as no reviews.
    A star rating is not review sentiment.
    Lexical requirement matching is not specification verification.
    This module ranks only the products and evidence it receives.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

SCORE_TIE_TOLERANCE = 0.05
MAX_LABEL_LENGTH = 60
MAX_TRAITS = 5

_MISSING = object()

_CURRENCY_ALIASES = {
    "₹": "INR",
    "RS": "INR",
    "RS.": "INR",
    "RUPEE": "INR",
    "RUPEES": "INR",
    "$": "USD",
    "US$": "USD",
    "USD": "USD",
    "€": "EUR",
    "£": "GBP",
}

# Common alternative field names. These are read-only compatibility aliases.
_PRICE_KEYS = ("price", "current_price", "selling_price", "sale_price")
_CURRENCY_KEYS = ("price_currency", "currency", "currency_code")
_RATING_KEYS = ("rating", "average_rating", "star_rating")
_REVIEW_COUNT_KEYS = ("review_count", "reviews_count", "num_reviews", "ratings_count")
_REVIEW_LIST_KEYS = ("reviews", "customer_reviews", "review_texts")
_SENTIMENT_KEYS = (
    "positive_review_ratio",
    "positive_review_fraction",
    "positive_sentiment_ratio",
    "review_sentiment_score",
    "sentiment_score",
)
_REQUIREMENT_SCORE_KEYS = (
    "requirements_match_score",
    "requirement_match_score",
    "requirements_match",
    "requirement_match",
    "requirements_coverage",
)
_SCORE_KEYS = ("overall_score", "final_score")


def compare_products(
    product_a: Mapping[str, Any],
    product_b: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Compare two already-analyzed products.

    Existing top-level response fields are preserved. Additional fields:
        decision_policy: priority order and interpretation.
        decision: selected rule, confidence limitations, and data warnings.

    Inputs may include:
        title, price, price_currency, rating, overall_score, verdict,
        requirements, description, features, attributes,
        requirements_match_score, review_count, reviews,
        positive_review_ratio.

    Raises:
        TypeError: if either product is not a mapping.
    """
    if not isinstance(product_a, Mapping) or not isinstance(product_b, Mapping):
        raise TypeError("product_a and product_b must be mappings.")

    name_a = _label(product_a, "Product A")
    name_b = _label(product_b, "Product B")

    price_a = _get_price(product_a)
    price_b = _get_price(product_b)
    currency_a = _get_currency(product_a)
    currency_b = _get_currency(product_b)

    currencies_match = (
        currency_a is not None
        and currency_b is not None
        and currency_a == currency_b
    )

    prices_comparable = (
        currencies_match
        and price_a is not None
        and price_b is not None
    )

    rating_a = _get_first_number(product_a, _RATING_KEYS)
    rating_b = _get_first_number(product_b, _RATING_KEYS)

    score_a = _get_first_number(product_a, _SCORE_KEYS)
    score_b = _get_first_number(product_b, _SCORE_KEYS)

    requirement_a = _requirement_match(product_a)
    requirement_b = _requirement_match(product_b)

    reviews_a = _review_status(product_a)
    reviews_b = _review_status(product_b)

    sentiment_a = _review_sentiment(product_a)
    sentiment_b = _review_sentiment(product_b)

    winner_key, decision_rule, decision_reason = _choose_winner(
        price_a=price_a,
        price_b=price_b,
        prices_comparable=prices_comparable,
        requirement_a=requirement_a,
        requirement_b=requirement_b,
        reviews_a=reviews_a,
        reviews_b=reviews_b,
        sentiment_a=sentiment_a,
        sentiment_b=sentiment_b,
        rating_a=rating_a,
        rating_b=rating_b,
        score_a=score_a,
        score_b=score_b,
    )

    winner_title = (
        name_a if winner_key == "product_a"
        else name_b if winner_key == "product_b"
        else "tie"
    )

    warnings = _data_warnings(
        product_a=product_a,
        product_b=product_b,
        prices_comparable=prices_comparable,
        currency_a=currency_a,
        currency_b=currency_b,
        reviews_a=reviews_a,
        reviews_b=reviews_b,
        sentiment_a=sentiment_a,
        sentiment_b=sentiment_b,
        requirement_a=requirement_a,
        requirement_b=requirement_b,
    )

    price_difference = None
    price_difference_percent = None

    if prices_comparable and price_a is not None and price_b is not None:
        price_difference = round(abs(price_a - price_b), 2)
        higher_price = max(price_a, price_b)
        if higher_price > 0:
            price_difference_percent = round(
                price_difference / higher_price * 100, 2
            )

    dimension_winners = {
        "overall_winner": _dimension_winner(
            score_a, score_b, name_a, name_b
        ),
        "rating_winner": _dimension_winner(
            rating_a, rating_b, name_a, name_b
        ),
        "price_winner": _dimension_winner(
            price_a if prices_comparable else None,
            price_b if prices_comparable else None,
            name_a,
            name_b,
            higher_is_better=False,
        ),
        "requirements_winner": _dimension_winner(
            requirement_a["score"],
            requirement_b["score"],
            name_a,
            name_b,
        ),
        "review_availability_winner": _dimension_winner(
            _review_availability_value(reviews_a),
            _review_availability_value(reviews_b),
            name_a,
            name_b,
        ),
        "review_sentiment_winner": _dimension_winner(
            sentiment_a,
            sentiment_b,
            name_a,
            name_b,
        ),
    }

    evidence_a = _evidence_summary(
        product_a, name_a, price_a, currency_a, rating_a,
        score_a, requirement_a, reviews_a, sentiment_a
    )
    evidence_b = _evidence_summary(
        product_b, name_b, price_b, currency_b, rating_b,
        score_b, requirement_b, reviews_b, sentiment_b
    )

    traits_a = _extract_traits(
        product_a, product_b, name_a, name_b,
        price_a, price_b, prices_comparable,
        requirement_a, requirement_b,
        reviews_a, reviews_b, sentiment_a, sentiment_b,
        rating_a, rating_b, score_a, score_b,
    )
    traits_b = _extract_traits(
        product_b, product_a, name_b, name_a,
        price_b, price_a, prices_comparable,
        requirement_b, requirement_a,
        reviews_b, reviews_a, sentiment_b, sentiment_a,
        rating_b, rating_a, score_b, score_a,
    )

    return {
        # Existing fields retained for API compatibility.
        "winner": winner_title,
        "winning_key": winner_key,
        "score_difference": (
            round(abs(score_a - score_b), 2)
            if score_a is not None and score_b is not None
            else None
        ),
        "dimension_winners": dimension_winners,
        "comparison": {
            "price": _compare_price(
                price_a, price_b, currency_a, currency_b,
                name_a, name_b, prices_comparable
            ),
            "rating": _compare_rating(
                rating_a, rating_b, name_a, name_b
            ),
            "overall": _compare_overall(
                score_a, score_b, name_a, name_b,
                _verdict(product_a), _verdict(product_b)
            ),
            "requirements": _compare_requirements(
                requirement_a, requirement_b, name_a, name_b
            ),
            "reviews": _compare_reviews(
                reviews_a, reviews_b, name_a, name_b
            ),
            "review_sentiment": _compare_sentiment(
                sentiment_a, sentiment_b, name_a, name_b
            ),
        },
        "strengths_and_weaknesses": {
            "product_a": traits_a,
            "product_b": traits_b,
        },
        "evidence": {
            "product_a": evidence_a,
            "product_b": evidence_b,
        },

        # New fields.
        "decision_policy": [
            "price",
            "requirements_match",
            "review_availability",
            "positive_review_sentiment",
            "published_rating",
            "overall_score",
        ],
        "decision": {
            "rule": decision_rule,
            "reason": decision_reason,
            "warnings": warnings,
            "price_comparable": prices_comparable,
            "currency_a": currency_a,
            "currency_b": currency_b,
            "price_difference": price_difference,
            "price_difference_percent_of_higher": price_difference_percent,
            "requirements_match": {
                "product_a": requirement_a,
                "product_b": requirement_b,
            },
            "review_status": {
                "product_a": reviews_a,
                "product_b": reviews_b,
            },
            "review_sentiment": {
                "product_a": sentiment_a,
                "product_b": sentiment_b,
            },
        },
    }


# ---------------------------------------------------------------------------
# Winner selection
# ---------------------------------------------------------------------------

def _choose_winner(
    *,
    price_a: float | None,
    price_b: float | None,
    prices_comparable: bool,
    requirement_a: dict[str, Any],
    requirement_b: dict[str, Any],
    reviews_a: dict[str, Any],
    reviews_b: dict[str, Any],
    sentiment_a: float | None,
    sentiment_b: float | None,
    rating_a: float | None,
    rating_b: float | None,
    score_a: float | None,
    score_b: float | None,
) -> tuple[str, str, str]:
    """Apply the documented priority order without inventing missing data."""

    # 1. Price. Only compare when both amounts and currencies are known.
    if (
        prices_comparable
        and price_a is not None
        and price_b is not None
        and price_a != price_b
    ):
        if price_a < price_b:
            return (
                "product_a", "price",
                "Product A has the lower verified price in the shared currency."
            )
        return (
            "product_b", "price",
            "Product B has the lower verified price in the shared currency."
        )

    # 2. Requirements. Only compare if both scores are assessable.
    req_a = requirement_a["score"]
    req_b = requirement_b["score"]
    if req_a is not None and req_b is not None and req_a != req_b:
        if req_a > req_b:
            return (
                "product_a", "requirements_match",
                "Product A matches more of the assessed user requirements."
            )
        return (
            "product_b", "requirements_match",
            "Product B matches more of the assessed user requirements."
        )

    # 3. Actual review availability.
    has_a = reviews_a["has_reviews"]
    has_b = reviews_b["has_reviews"]
    if has_a is not None and has_b is not None and has_a != has_b:
        if has_a:
            return (
                "product_a", "review_availability",
                "Product A has customer reviews while Product B has none."
            )
        return (
            "product_b", "review_availability",
            "Product B has customer reviews while Product A has none."
        )

    # 4. Review sentiment. Only compare when both scores exist.
    if (
        sentiment_a is not None
        and sentiment_b is not None
        and sentiment_a != sentiment_b
    ):
        if sentiment_a > sentiment_b:
            return (
                "product_a", "positive_review_sentiment",
                "Product A has the more positive assessed review sentiment."
            )
        return (
            "product_b", "positive_review_sentiment",
            "Product B has the more positive assessed review sentiment."
        )

    # 5. Published rating. Missing ratings never become zero.
    if (
        rating_a is not None
        and rating_b is not None
        and rating_a != rating_b
    ):
        if rating_a > rating_b:
            return (
                "product_a", "published_rating",
                "Product A has the higher published rating."
            )
        return (
            "product_b", "published_rating",
            "Product B has the higher published rating."
        )

    # 6. Existing overall score as a fallback, only when both are present.
    if (
        score_a is not None
        and score_b is not None
        and abs(score_a - score_b) > SCORE_TIE_TOLERANCE
    ):
        if score_a > score_b:
            return (
                "product_a", "overall_score",
                "Product A has the higher existing overall score."
            )
        return (
            "product_b", "overall_score",
            "Product B has the higher existing overall score."
        )

    # Missing or incomparable data cannot justify a fabricated winner.
    return (
        "tie", "insufficient_distinguishing_evidence",
        "The available comparable evidence does not establish a reliable winner."
    )


# ---------------------------------------------------------------------------
# Price and currency
# ---------------------------------------------------------------------------

def _get_price(product: Mapping[str, Any]) -> float | None:
    for key in _PRICE_KEYS:
        if key in product:
            value = _parse_price(product.get(key))
            if value is not None:
                return value

    # Some extractors preserve the displayed price separately.
    for key in ("price_text", "displayed_price", "formatted_price"):
        value = product.get(key)
        parsed = _parse_price(value)
        if parsed is not None:
            return parsed

    return None


def _parse_price(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None

    if isinstance(value, (int, float)):
        number = _to_float(value)
        return number if number is not None and number >= 0 else None

    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    # Remove common currency markers and thousands separators.
    cleaned = re.sub(
        r"(?i)\b(?:INR|USD|EUR|GBP|RS\.?|RUPEES?)\b",
        "",
        text,
    )
    cleaned = cleaned.replace("₹", "").replace("$", "")
    cleaned = cleaned.replace("€", "").replace("£", "")
    cleaned = cleaned.replace(",", "").strip()

    match = re.fullmatch(r"[-+]?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None

    number = _to_float(cleaned)
    return number if number is not None and number >= 0 else None


def _get_currency(product: Mapping[str, Any]) -> str | None:
    for key in _CURRENCY_KEYS:
        currency = _normalize_currency(product.get(key))
        if currency is not None:
            return currency

    # Infer currency only from an explicit symbol/code in a price string.
    for key in ("price_text", "displayed_price", "formatted_price", "price"):
        value = product.get(key)
        if isinstance(value, str):
            currency = _currency_from_explicit_text(value)
            if currency is not None:
                return currency

    return None


def _normalize_currency(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    text = value.strip().upper()
    if not text:
        return None

    alias = _CURRENCY_ALIASES.get(text)
    if alias:
        return alias

    if len(text) == 3 and text.isascii() and text.isalpha():
        return text

    return None


def _currency_from_explicit_text(text: str) -> str | None:
    stripped = text.strip()

    # Prefer explicit ISO codes.
    codes = re.findall(r"(?i)(?<![A-Z])([A-Z]{3})(?![A-Z])", stripped)
    for code in codes:
        normalized = _normalize_currency(code)
        if normalized:
            return normalized

    if "₹" in stripped or re.search(r"(?i)\b(?:RS\.?|RUPEES?)\b", stripped):
        return "INR"
    if "US$" in stripped or "$" in stripped:
        return "USD"
    if "€" in stripped:
        return "EUR"
    if "£" in stripped:
        return "GBP"

    return None


# ---------------------------------------------------------------------------
# Requirements matching
# ---------------------------------------------------------------------------

def _requirement_match(product: Mapping[str, Any]) -> dict[str, Any]:
    """
    Prefer explicit structured match scores. Otherwise compute lexical coverage
    only when requirements and usable product text are both available.
    """
    for key in _REQUIREMENT_SCORE_KEYS:
        if key in product:
            score = _normalise_ratio(product.get(key))
            if score is not None:
                return {
                    "score": score,
                    "method": "provided_structured_score",
                    "matched": None,
                    "total": None,
                }

    requirements = _as_text_list(
        product.get("requirements")
        or product.get("user_requirements")
    )
    product_text = _product_search_text(product)

    if not requirements or not product_text:
        return {
            "score": None,
            "method": "unavailable",
            "matched": None,
            "total": len(requirements) if requirements else None,
        }

    matched = [
        requirement for requirement in requirements
        if _requirement_lexically_matches(requirement, product_text)
    ]
    return {
        "score": len(matched) / len(requirements),
        "method": "lexical_listing_text",
        "matched": len(matched),
        "total": len(requirements),
    }


def _requirement_lexically_matches(requirement: str, text: str) -> bool:
    normalized_requirement = _normalize_text(requirement)
    normalized_text = _normalize_text(text)

    if not normalized_requirement:
        return False

    # Exact phrase match first.
    if normalized_requirement in normalized_text:
        return True

    # For short requirements, require all meaningful tokens.
    tokens = [
        token for token in normalized_requirement.split()
        if len(token) > 1
    ]
    return bool(tokens) and all(token in normalized_text for token in tokens)


def _product_search_text(product: Mapping[str, Any]) -> str:
    parts: list[str] = []

    for key in (
        "title", "description", "cleaned_content", "features",
        "attributes", "specifications", "category", "brand",
    ):
        value = product.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, Mapping):
            parts.extend(
                f"{k} {v}" for k, v in value.items()
                if isinstance(k, str) and isinstance(v, (str, int, float))
            )
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            parts.extend(str(item) for item in value if isinstance(item, (str, int, float)))

    return _normalize_text(" ".join(parts))


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [
            item.strip() for item in value
            if isinstance(item, str) and item.strip()
        ]

    return []


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _normalise_ratio(value: Any) -> float | None:
    number = _to_float(value)
    if number is None:
        return None

    # Support scores expressed on either 0–1 or 0–100 scales.
    if 0 <= number <= 1:
        return number
    if 1 < number <= 100:
        return number / 100

    return None


# ---------------------------------------------------------------------------
# Review availability and sentiment
# ---------------------------------------------------------------------------

def _review_status(product: Mapping[str, Any]) -> dict[str, Any]:
    count = _get_first_number(product, _REVIEW_COUNT_KEYS)
    if count is not None and count < 0:
        count = None

    review_items = None
    for key in _REVIEW_LIST_KEYS:
        value = product.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            review_items = value
            break

    if count is not None:
        has_reviews: bool | None = count > 0
    elif review_items is not None:
        has_reviews = len(review_items) > 0
        count = len(review_items)
    else:
        has_reviews = None

    return {
        "has_reviews": has_reviews,
        "review_count": int(count) if count is not None else None,
        "source": (
            "review_count"
            if _get_first_number(product, _REVIEW_COUNT_KEYS) is not None
            else "review_list"
            if review_items is not None
            else "unknown"
        ),
    }


def _review_sentiment(product: Mapping[str, Any]) -> float | None:
    """
    Return an explicit sentiment/positive-review ratio on a 0–1 scale.
    Star ratings are deliberately not treated as sentiment.
    """
    for key in _SENTIMENT_KEYS:
        if key in product:
            value = _normalise_ratio(product.get(key))
            if value is not None:
                return value

    # Do not infer sentiment from rating, verdict, or product description.
    return None


# ---------------------------------------------------------------------------
# Evidence, traits, and comparisons
# ---------------------------------------------------------------------------

def _evidence_summary(
    product: Mapping[str, Any],
    name: str,
    price: float | None,
    currency: str | None,
    rating: float | None,
    score: float | None,
    requirements: dict[str, Any],
    reviews: dict[str, Any],
    sentiment: float | None,
) -> dict[str, Any]:
    return {
        "title": name,
        "price": price,
        "price_currency": currency,
        "rating": rating,
        "overall_score": score,
        "requirements_match": requirements,
        "review_count": reviews["review_count"],
        "has_reviews": reviews["has_reviews"],
        "positive_review_ratio": sentiment,
        "verdict": _verdict(product),
    }


def _extract_traits(
    target: Mapping[str, Any],
    opponent: Mapping[str, Any],
    target_name: str,
    opponent_name: str,
    target_price: float | None,
    opponent_price: float | None,
    prices_comparable: bool,
    target_req: dict[str, Any],
    opponent_req: dict[str, Any],
    target_reviews: dict[str, Any],
    opponent_reviews: dict[str, Any],
    target_sentiment: float | None,
    opponent_sentiment: float | None,
    target_rating: float | None,
    opponent_rating: float | None,
    target_score: float | None,
    opponent_score: float | None,
) -> dict[str, list[str]]:
    strengths: list[str] = []
    weaknesses: list[str] = []

    if prices_comparable and target_price is not None and opponent_price is not None:
        if target_price < opponent_price:
            strengths.append(
                f"Lower price ({_fmt_number(target_price)} vs "
                f"{_fmt_number(opponent_price)})"
            )
        elif target_price > opponent_price:
            weaknesses.append(
                f"Higher price ({_fmt_number(target_price)} vs "
                f"{_fmt_number(opponent_price)})"
            )

    req_a = target_req["score"]
    req_b = opponent_req["score"]
    if req_a is not None and req_b is not None and req_a != req_b:
        if req_a > req_b:
            strengths.append(f"Better requirements match ({req_a:.0%})")
        else:
            weaknesses.append(f"Weaker requirements match ({req_a:.0%})")

    has_a = target_reviews["has_reviews"]
    has_b = opponent_reviews["has_reviews"]
    if has_a is True and has_b is False:
        strengths.append("Customer reviews are available")
    elif has_a is False and has_b is True:
        weaknesses.append("No customer reviews are available")

    if target_sentiment is not None and opponent_sentiment is not None:
        if target_sentiment > opponent_sentiment:
            strengths.append(
                f"More positive review sentiment ({target_sentiment:.0%})"
            )
        elif target_sentiment < opponent_sentiment:
            weaknesses.append(
                f"Less positive review sentiment ({target_sentiment:.0%})"
            )

    if target_rating is not None and opponent_rating is not None:
        if target_rating > opponent_rating:
            strengths.append(
                f"Higher published rating ({target_rating:.1f} vs "
                f"{opponent_rating:.1f})"
            )
        elif target_rating < opponent_rating:
            weaknesses.append(
                f"Lower published rating ({target_rating:.1f} vs "
                f"{opponent_rating:.1f})"
            )

    if target_score is not None and opponent_score is not None:
        if target_score > opponent_score + SCORE_TIE_TOLERANCE:
            strengths.append(
                f"Higher existing overall score ({target_score:.1f} vs "
                f"{opponent_score:.1f})"
            )
        elif target_score < opponent_score - SCORE_TIE_TOLERANCE:
            weaknesses.append(
                f"Lower existing overall score ({target_score:.1f} vs "
                f"{opponent_score:.1f})"
            )

    # Never fabricate generic positive or negative evidence.
    if not strengths:
        strengths.append("No verified comparative advantage identified")
    if not weaknesses:
        weaknesses.append("No verified comparative disadvantage identified")

    return {
        "strengths": strengths[:MAX_TRAITS],
        "weaknesses": weaknesses[:MAX_TRAITS],
    }


def _compare_price(
    price_a: float | None,
    price_b: float | None,
    currency_a: str | None,
    currency_b: str | None,
    name_a: str,
    name_b: str,
    prices_comparable: bool,
) -> str:
    if not prices_comparable or price_a is None or price_b is None:
        return (
            "A reliable price comparison is unavailable because both prices "
            "and matching, known currencies are required. "
            f"Available currencies: {currency_a or 'unknown'} and "
            f"{currency_b or 'unknown'}."
        )

    symbol = _currency_symbol(currency_a)
    if price_a == price_b:
        return f"Both products cost {symbol}{_fmt_number(price_a)}."

    if price_a < price_b:
        cheaper, pricier = name_a, name_b
        low, high = price_a, price_b
    else:
        cheaper, pricier = name_b, name_a
        low, high = price_b, price_a

    difference = high - low
    percentage = difference / high * 100 if high > 0 else 0.0

    return (
        f"{cheaper} is cheaper by {symbol}{_fmt_number(difference)} "
        f"({percentage:.1f}% less than {pricier})."
    )


def _compare_rating(
    rating_a: float | None,
    rating_b: float | None,
    name_a: str,
    name_b: str,
) -> str:
    if rating_a is None and rating_b is None:
        return "Published ratings are unavailable for both products."
    if rating_a is None:
        return f"Rating is unavailable for {name_a}."
    if rating_b is None:
        return f"Rating is unavailable for {name_b}."
    if rating_a == rating_b:
        return f"Both products have the same published rating ({rating_a:.1f})."

    higher = name_a if rating_a > rating_b else name_b
    return f"{higher} has the higher published rating."


def _compare_overall(
    score_a: float | None,
    score_b: float | None,
    name_a: str,
    name_b: str,
    verdict_a: str | None,
    verdict_b: str | None,
) -> str:
    if score_a is None and score_b is None:
        sentence = "An overall-score comparison is unavailable."
    elif score_a is None:
        sentence = f"An overall score is unavailable for {name_a}."
    elif score_b is None:
        sentence = f"An overall score is unavailable for {name_b}."
    elif abs(score_a - score_b) <= SCORE_TIE_TOLERANCE:
        sentence = (
            f"Both products have essentially the same existing overall "
            f"score ({score_a:.1f})."
        )
    else:
        leader = name_a if score_a > score_b else name_b
        sentence = (
            f"{leader} has the higher existing overall score "
            f"({max(score_a, score_b):.1f} vs {min(score_a, score_b):.1f})."
        )

    if verdict_a and verdict_b:
        sentence += (
            f" Existing verdicts: {name_a} — {verdict_a}; "
            f"{name_b} — {verdict_b}."
        )
    return sentence


def _compare_requirements(
    requirement_a: dict[str, Any],
    requirement_b: dict[str, Any],
    name_a: str,
    name_b: str,
) -> str:
    a = requirement_a["score"]
    b = requirement_b["score"]

    if a is None and b is None:
        return "Requirement matching could not be assessed for either product."
    if a is None:
        return f"Requirement matching is unavailable for {name_a}."
    if b is None:
        return f"Requirement matching is unavailable for {name_b}."
    if a == b:
        return f"Both products have the same assessed requirement match ({a:.0%})."

    better = name_a if a > b else name_b
    return f"{better} has the higher assessed requirement match."


def _compare_reviews(
    reviews_a: dict[str, Any],
    reviews_b: dict[str, Any],
    name_a: str,
    name_b: str,
) -> str:
    a = reviews_a["has_reviews"]
    b = reviews_b["has_reviews"]

    if a is None or b is None:
        return (
            "Review availability is unknown for at least one product; "
            "unknown does not mean zero reviews."
        )
    if a and not b:
        return f"{name_a} has customer reviews; {name_b} has none reported."
    if b and not a:
        return f"{name_b} has customer reviews; {name_a} has none reported."
    if not a and not b:
        return "Neither product has reported customer reviews."
    return (
        f"Both products have reviews. Reported counts: "
        f"{reviews_a['review_count'] if reviews_a['review_count'] is not None else 'unknown'} "
        f"and {reviews_b['review_count'] if reviews_b['review_count'] is not None else 'unknown'}."
    )


def _compare_sentiment(
    sentiment_a: float | None,
    sentiment_b: float | None,
    name_a: str,
    name_b: str,
) -> str:
    if sentiment_a is None or sentiment_b is None:
        return (
            "Comparable review sentiment is unavailable. "
            "Published star ratings are not treated as sentiment."
        )
    if sentiment_a == sentiment_b:
        return "Both products have the same assessed positive-review ratio."

    better = name_a if sentiment_a > sentiment_b else name_b
    return f"{better} has the higher assessed positive-review ratio."


def _data_warnings(
    *,
    product_a: Mapping[str, Any],
    product_b: Mapping[str, Any],
    prices_comparable: bool,
    currency_a: str | None,
    currency_b: str | None,
    reviews_a: dict[str, Any],
    reviews_b: dict[str, Any],
    sentiment_a: float | None,
    sentiment_b: float | None,
    requirement_a: dict[str, Any],
    requirement_b: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []

    if not prices_comparable:
        warnings.append(
            "Price priority could not be applied because both prices and "
            "matching known currencies are required."
        )

    if reviews_a["has_reviews"] is None or reviews_b["has_reviews"] is None:
        warnings.append(
            "Review availability is unknown for at least one product."
        )

    if sentiment_a is None or sentiment_b is None:
        warnings.append(
            "Comparable customer-review sentiment is unavailable."
        )

    if (
        requirement_a["method"] == "lexical_listing_text"
        or requirement_b["method"] == "lexical_listing_text"
    ):
        warnings.append(
            "Lexical requirement matches indicate text coverage, not verified "
            "specification compliance."
        )

    for label, product, currency in (
        ("Product A", product_a, currency_a),
        ("Product B", product_b, currency_b),
    ):
        if _get_price(product) is not None and currency is None:
            warnings.append(
                f"{label} has a numeric price but no verified currency."
            )

    return list(dict.fromkeys(warnings))


# ---------------------------------------------------------------------------
# General utilities
# ---------------------------------------------------------------------------

def _dimension_winner(
    val_a: float | None,
    val_b: float | None,
    name_a: str,
    name_b: str,
    higher_is_better: bool = True,
) -> str:
    if val_a is None and val_b is None:
        return "N/A"
    if val_a is None:
        return "N/A"
    if val_b is None:
        return "N/A"
    if val_a == val_b:
        return "tie"

    if higher_is_better:
        return name_a if val_a > val_b else name_b
    return name_a if val_a < val_b else name_b


def _review_availability_value(reviews: dict[str, Any]) -> float | None:
    value = reviews["has_reviews"]
    return None if value is None else (1.0 if value else 0.0)


def _get_first_number(
    product: Mapping[str, Any],
    keys: Sequence[str],
) -> float | None:
    for key in keys:
        if key in product:
            number = _to_float(product.get(key))
            if number is not None:
                return number
    return None


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _verdict(product: Mapping[str, Any]) -> str | None:
    value = product.get("verdict")
    if isinstance(value, str) and value.strip():
        return value.strip().upper()
    return None


def _label(product: Mapping[str, Any], fallback: str) -> str:
    title = product.get("title")
    if not isinstance(title, str) or not title.strip():
        title = product.get("name")

    if isinstance(title, str) and title.strip():
        text = title.strip()
        if len(text) > MAX_LABEL_LENGTH:
            return text[: MAX_LABEL_LENGTH - 1].rstrip() + "…"
        return text

    return fallback


def _fmt_number(value: float | None) -> str:
    if value is None:
        return "N/A"
    if float(value).is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def _currency_symbol(currency: str | None) -> str:
    return {
        "INR": "₹",
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
    }.get(currency or "", f"{currency or ''} ")


__all__ = [
    "SCORE_TIE_TOLERANCE",
    "MAX_LABEL_LENGTH",
    "compare_products",
]
