"""
Product analysis engine.

Sits between the product extractor and the verdict engine and turns raw
product fields into explainable, structured insights:

    extractor -> analysis_engine -> verdict_engine

This module is **deterministic Python only**: no LLMs, no external ML
libraries, no randomness, and no I/O. The same input always produces the
same output, and every insight can be traced back to a keyword, a threshold,
or a rating tier defined in this file.

Public API:
    analyze_product: Produce sentiment, pros/cons, risk flags, requirement
        match and a human-readable explanation for one product.

Known limitations (by design, to keep behaviour predictable and explainable):
    * Keyword matching is lexical. Negation ("not durable") is not detected.
    * The high-price threshold is a single fixed number and assumes the
      currency used by the extractor (see ``HIGH_PRICE_THRESHOLD``).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, NamedTuple, Sequence

# --------------------------------------------------------------------------- #
# Tunable constants
# --------------------------------------------------------------------------- #

#: Rating tiers (inclusive lower bounds on a 0-5 scale).
RATING_HIGH: float = 4.5
RATING_GOOD: float = 4.0
RATING_AVERAGE: float = 3.0

#: A rating strictly below this value raises the ``low_rating`` risk flag.
LOW_RATING_THRESHOLD: float = 3.5

#: A price at or above this value raises the ``high_price`` risk flag.
#: Expressed in the same currency units the extractor returns (e.g. INR).
HIGH_PRICE_THRESHOLD: float = 50_000.0

#: Neutral score used when there is not enough information to judge.
NEUTRAL_SCORE: float = 5.0

#: Upper bound on the number of pros / cons returned, to keep output readable.
MAX_INSIGHTS: int = 5

#: Maximum number of highlighted labels quoted inside the explanation.
MAX_EXPLAINED_LABELS: int = 3

RISK_HIGH_PRICE: str = "high_price"
RISK_LOW_RATING: str = "low_rating"
RISK_MISSING_DESCRIPTION: str = "missing_description"
RISK_MISSING_RATING: str = "missing_rating"


# --------------------------------------------------------------------------- #
# Keyword signal tables
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _Signal:
    """A keyword rule that maps matched text to a readable insight."""

    label: str
    pattern: re.Pattern[str]
    message: str


def _signal(label: str, regex: str, message: str) -> _Signal:
    """Build a ``_Signal`` with a case-insensitive compiled pattern."""
    return _Signal(label=label, pattern=re.compile(regex, re.IGNORECASE), message=message)


_PRO_SIGNALS: tuple[_Signal, ...] = (
    _signal("battery", r"\bbatter(?:y|ies)\b", "Strong battery-related features mentioned"),
    _signal("camera", r"\bcameras?\b", "Notable camera-related features mentioned"),
    _signal("performance", r"\bperformance\b", "Performance-oriented capabilities highlighted"),
    _signal("display", r"\bdisplays?\b", "Quality display features highlighted"),
    _signal("premium", r"\bpremium\b", "Premium positioning or build quality indicated"),
    _signal("durable", r"\bdurab(?:le|ility)\b", "Durability is emphasised"),
    _signal("fast", r"\bfast(?:er|est)?\b", "Speed-related advantages mentioned"),
    _signal("lightweight", r"\blight[\s-]?weight\b", "Lightweight design mentioned"),
    _signal("comfortable", r"\bcomfort(?:able|ably)?\b", "Comfort-focused design mentioned"),
)

_CON_SIGNALS: tuple[_Signal, ...] = (
    _signal("heavy", r"\bheav(?:y|ier|iest)\b", "May be heavy or bulky"),
    _signal("expensive", r"\b(?:expensive|costly)\b", "Described as expensive or costly"),
    _signal("slow", r"\bslow(?:er|est|ly)?\b", "Slow performance or response mentioned"),
    _signal("limited", r"\blimited\b", "Limited features or availability mentioned"),
    _signal("basic", r"\bbasic\b", "Basic feature set mentioned"),
    _signal("poor", r"\bpoor(?:ly)?\b", "Poor quality or performance mentioned"),
    # "low latency / low power / low weight / low price" are positives, so skip them.
    _signal(
        "low",
        r"\blow(?:er|est)?\b(?!\s*[-\s]?(?:latency|power|weight|price|cost|noise|lag))",
        "Low specification or quality mentioned",
    ),
)

_PRO_LABEL_BY_MESSAGE: dict[str, str] = {s.message: s.label for s in _PRO_SIGNALS}
_CON_LABEL_BY_MESSAGE: dict[str, str] = {s.message: s.label for s in _CON_SIGNALS}


# --------------------------------------------------------------------------- #
# Requirement vocabulary
# --------------------------------------------------------------------------- #

#: Canonical requirement keyword -> words/phrases that satisfy it in product text.
_REQUIREMENT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "gaming": ("gaming", "gamer", "gamers", "game", "games", "gpu", "fps", "refresh rate"),
    "camera": ("camera", "cameras", "photo", "photos", "photography", "megapixel", "lens"),
    "battery": ("battery", "batteries", "mah", "charging", "long lasting"),
    "student": ("student", "students", "study", "college", "school", "learning"),
    "budget": ("budget", "affordable", "value", "cheap", "economical"),
    "office": ("office", "work", "productivity", "business", "professional"),
    "travel": ("travel", "portable", "compact", "lightweight"),
    "music": ("music", "audio", "sound", "speaker", "speakers"),
    "performance": ("performance", "fast", "powerful", "speed"),
    "display": ("display", "screen", "amoled", "oled", "lcd"),
}

#: Any variant word -> canonical requirement keyword (built once at import).
_REQUIREMENT_ALIASES: dict[str, str] = {
    variant: canonical
    for canonical, variants in _REQUIREMENT_SYNONYMS.items()
    for variant in (canonical, *variants)
    if " " not in variant
}

_REQUIREMENT_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "or", "the", "for", "to", "of", "in", "on", "with", "my",
        "i", "me", "need", "needs", "want", "wants", "good", "best", "great", "use",
        "using", "something", "that", "is", "are", "be", "it", "this", "very", "also",
    }
)

_TOKEN_RE: re.Pattern[str] = re.compile(r"[a-z0-9]+")


class RequirementMatch(NamedTuple):
    """Result of comparing requirement keywords against product text."""

    score: float
    matched: list[str]
    unmatched: list[str]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def analyze_product(
    title: str | None,
    description: str | None,
    price: float | None,
    rating: float | None,
    requirements: str | None = None,
) -> dict[str, Any]:
    """
    Analyze a product and return explainable, deterministic insights.

    Args:
        title: Product title, if known.
        description: Product description, if known.
        price: Product price in the extractor's currency units, if known.
        rating: Customer rating on a 0-5 scale, if known.
        requirements: Optional free-text user requirements, for example
            ``"gaming camera battery"``.

    Returns:
        A dictionary with the following keys:

        * ``sentiment_score`` (``float``): 0-10 score derived from the rating.
        * ``requirement_match`` (``float``): 0-10 score for how well the product
          text covers the user's requirements (``5.0`` if none were given).
        * ``pros`` (``list[str]``): Readable strengths found in the text.
        * ``cons`` (``list[str]``): Readable drawbacks found in the text.
        * ``risk_flags`` (``list[str]``): Any of ``high_price``, ``low_rating``,
          ``missing_description``, ``missing_rating``.
        * ``explanation`` (``str``): A human-readable summary paragraph.
    """
    clean_price = _coerce_number(price)
    clean_rating = _coerce_rating(rating)

    sentiment_score = _compute_sentiment_score(clean_rating)
    pros = _extract_pros(title, description)
    cons = _extract_cons(title, description)
    risk_flags = _detect_risks(description, clean_price, clean_rating)
    requirement_result = _compute_requirement_match(title, description, requirements)

    explanation = _build_explanation(
        rating=clean_rating,
        sentiment_score=sentiment_score,
        pros=pros,
        cons=cons,
        risk_flags=risk_flags,
        requirement_result=requirement_result,
    )

    return {
        "sentiment_score": sentiment_score,
        "requirement_match": requirement_result.score,
        "pros": pros,
        "cons": cons,
        "risk_flags": risk_flags,
        "explanation": explanation,
    }


# --------------------------------------------------------------------------- #
# Core helpers
# --------------------------------------------------------------------------- #


def _compute_sentiment_score(rating: float | None) -> float:
    """
    Convert a 0-5 rating into a 0-10 sentiment score.

    The score is piecewise linear and continuous across the rating tiers:

    * ``rating >= 4.5`` (high):    8.5 -> 10.0
    * ``rating >= 4.0`` (good):    7.0 -> 8.5
    * ``rating >= 3.0`` (average): 4.5 -> 7.0
    * ``rating <  3.0`` (poor):    0.0 -> 4.5

    Args:
        rating: Customer rating on a 0-5 scale, or ``None``.

    Returns:
        The sentiment score rounded to one decimal place. ``5.0`` (neutral)
        is returned when no rating is available.
    """
    if rating is None:
        return NEUTRAL_SCORE

    if rating >= RATING_HIGH:
        score = 8.5 + (rating - RATING_HIGH) / (5.0 - RATING_HIGH) * 1.5
    elif rating >= RATING_GOOD:
        score = 7.0 + (rating - RATING_GOOD) / (RATING_HIGH - RATING_GOOD) * 1.5
    elif rating >= RATING_AVERAGE:
        score = 4.5 + (rating - RATING_AVERAGE) * 2.5
    else:
        score = rating / RATING_AVERAGE * 4.5

    return _round_score(score)


def _extract_pros(title: str | None, description: str | None) -> list[str]:
    """
    Extract readable strengths by searching the title and description.

    Keywords searched: battery, camera, performance, display, premium,
    durable, fast, lightweight, comfortable.

    Args:
        title: Product title, if known.
        description: Product description, if known.

    Returns:
        Up to ``MAX_INSIGHTS`` readable pro statements, in a stable order
        that follows the keyword table (not the order of appearance).
    """
    corpus = _build_corpus(title, description)
    return [s.message for s in _find_signals(corpus, _PRO_SIGNALS)][:MAX_INSIGHTS]


def _extract_cons(title: str | None, description: str | None) -> list[str]:
    """
    Extract readable drawbacks by searching the title and description.

    Keywords searched: heavy, expensive, slow, limited, basic, poor, low.

    Args:
        title: Product title, if known.
        description: Product description, if known.

    Returns:
        Up to ``MAX_INSIGHTS`` readable con statements, in a stable order
        that follows the keyword table.
    """
    corpus = _build_corpus(title, description)
    return [s.message for s in _find_signals(corpus, _CON_SIGNALS)][:MAX_INSIGHTS]


def _detect_risks(
    description: str | None,
    price: float | None,
    rating: float | None,
) -> list[str]:
    """
    Detect risk flags from the structured product fields.

    Flags:
        * ``high_price``: price is at or above ``HIGH_PRICE_THRESHOLD``.
        * ``low_rating``: rating is below ``LOW_RATING_THRESHOLD``.
        * ``missing_description``: description is empty or absent.
        * ``missing_rating``: no usable rating is available.

    Args:
        description: Product description, if known.
        price: Cleaned price, or ``None``.
        rating: Cleaned rating, or ``None``.

    Returns:
        Applicable risk flags in a fixed, deterministic order.
    """
    flags: list[str] = []

    if price is not None and price >= HIGH_PRICE_THRESHOLD:
        flags.append(RISK_HIGH_PRICE)
    if rating is not None and rating < LOW_RATING_THRESHOLD:
        flags.append(RISK_LOW_RATING)
    if not _normalise_text(description):
        flags.append(RISK_MISSING_DESCRIPTION)
    if rating is None:
        flags.append(RISK_MISSING_RATING)

    return flags


def _compute_requirement_match(
    title: str | None,
    description: str | None,
    requirements: str | None,
) -> RequirementMatch:
    """
    Score how well the title and description cover the user's requirements.

    Requirement text is tokenised, stop words are removed, and each remaining
    keyword is canonicalised through the synonym table (for example ``game``
    becomes ``gaming``). A keyword counts as matched when the product text
    contains the keyword or any of its synonyms.

    Args:
        title: Product title, if known.
        description: Product description, if known.
        requirements: Free-text user requirements, if any.

    Returns:
        A ``RequirementMatch`` whose ``score`` is ``matched / total * 10``
        rounded to one decimal place. When no usable requirement keywords are
        given, the score is the neutral ``5.0`` and both lists are empty.
    """
    keywords = _parse_requirements(requirements)
    if not keywords:
        return RequirementMatch(score=NEUTRAL_SCORE, matched=[], unmatched=[])

    corpus = _build_corpus(title, description)
    matched: list[str] = []
    unmatched: list[str] = []

    for keyword in keywords:
        if corpus and _keyword_in_text(keyword, corpus):
            matched.append(keyword)
        else:
            unmatched.append(keyword)

    score = _round_score(len(matched) / len(keywords) * 10.0)
    return RequirementMatch(score=score, matched=matched, unmatched=unmatched)


def _build_explanation(
    rating: float | None,
    sentiment_score: float,
    pros: Sequence[str],
    cons: Sequence[str],
    risk_flags: Sequence[str],
    requirement_result: RequirementMatch,
) -> str:
    """
    Compose a human-readable paragraph that explains the analysis.

    The paragraph covers, in order: requirement suitability, sentiment,
    strengths, drawbacks, and risks.

    Args:
        rating: Cleaned rating, or ``None``.
        sentiment_score: Score from ``_compute_sentiment_score``.
        pros: Pro statements from ``_extract_pros``.
        cons: Con statements from ``_extract_cons``.
        risk_flags: Flags from ``_detect_risks``.
        requirement_result: Result from ``_compute_requirement_match``.

    Returns:
        A single paragraph of plain English.
    """
    sentences: list[str] = []

    # 1. Requirement suitability.
    matched = requirement_result.matched
    unmatched = requirement_result.unmatched
    if matched:
        sentences.append(
            f"This product appears suitable for users prioritizing {_join_natural(matched)}."
        )
        if unmatched:
            sentences.append(
                f"It does not clearly mention {_join_natural(unmatched)}."
            )
    elif unmatched:
        sentences.append(
            "This product does not clearly address the stated requirements "
            f"({_join_natural(unmatched)})."
        )
    else:
        sentences.append("This product was assessed from its listing details alone.")

    # 2. Sentiment.
    sentences.append(_describe_sentiment(rating, sentiment_score))

    # 3. Strengths and drawbacks.
    pro_labels = [_PRO_LABEL_BY_MESSAGE[p] for p in pros if p in _PRO_LABEL_BY_MESSAGE]
    if pro_labels:
        sentences.append(
            f"Key strengths mentioned include {_join_natural(pro_labels[:MAX_EXPLAINED_LABELS])}."
        )
    con_labels = [_CON_LABEL_BY_MESSAGE[c] for c in cons if c in _CON_LABEL_BY_MESSAGE]
    if con_labels:
        sentences.append(
            f"Potential drawbacks mentioned include {_join_natural(con_labels[:MAX_EXPLAINED_LABELS])}."
        )

    # 4. Risks.
    if RISK_HIGH_PRICE in risk_flags:
        sentences.append(
            "However, the product may be expensive for budget-focused buyers."
        )
    if RISK_LOW_RATING in risk_flags:
        sentences.append("The low customer rating is a notable risk.")
    if RISK_MISSING_DESCRIPTION in risk_flags:
        sentences.append(
            "The listing has no description, which limits the depth of this analysis."
        )

    return " ".join(sentences)


# --------------------------------------------------------------------------- #
# Internal utilities
# --------------------------------------------------------------------------- #


def _describe_sentiment(rating: float | None, sentiment_score: float) -> str:
    """Return one sentence describing sentiment for the given rating tier."""
    if rating is None:
        return "No customer rating is available, so sentiment is treated as neutral."

    if rating >= RATING_HIGH:
        tone = "very positive due to a strong rating"
    elif rating >= RATING_GOOD:
        tone = "positive due to a good rating"
    elif rating >= RATING_AVERAGE:
        tone = "mixed due to an average rating"
    else:
        tone = "negative due to a poor rating"

    return (
        f"The overall sentiment is {tone} "
        f"({rating:.1f}/5, sentiment score {sentiment_score:.1f}/10)."
    )


def _find_signals(text: str, signals: Sequence[_Signal]) -> list[_Signal]:
    """Return every signal whose pattern occurs in ``text``, in table order."""
    if not text:
        return []
    return [signal for signal in signals if signal.pattern.search(text)]


def _parse_requirements(requirements: str | None) -> list[str]:
    """
    Tokenise requirement text into unique canonical keywords.

    Stop words and single-character tokens are dropped, variants are mapped
    to their canonical keyword, and the original order is preserved.
    """
    text = _normalise_text(requirements)
    if not text:
        return []

    keywords: list[str] = []
    for token in _TOKEN_RE.findall(text):
        if len(token) < 2 or token in _REQUIREMENT_STOPWORDS:
            continue
        canonical = _REQUIREMENT_ALIASES.get(token)
        if canonical is None:
            canonical = token
        if canonical not in keywords:
            keywords.append(canonical)
    return keywords


def _keyword_in_text(keyword: str, text: str) -> bool:
    """
    Check whether ``keyword`` or any of its synonyms appears in ``text``.

    Unknown keywords are matched as whole words, allowing a plural suffix.
    """
    variants = _REQUIREMENT_SYNONYMS.get(keyword)
    if variants is None:
        pattern = rf"\b{re.escape(keyword)}(?:s|es)?\b"
        return re.search(pattern, text) is not None

    for variant in (keyword, *variants):
        parts = [re.escape(part) for part in variant.split()]
        pattern = rf"\b{r'[\s-]+'.join(parts)}\b"
        if re.search(pattern, text):
            return True
    return False


def _build_corpus(title: str | None, description: str | None) -> str:
    """Join the title and description into one normalised, searchable string."""
    return " ".join(
        part for part in (_normalise_text(title), _normalise_text(description)) if part
    )


def _normalise_text(value: str | None) -> str:
    """Return a stripped, lower-cased string; ``None`` or non-strings become ``""``."""
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def _coerce_number(value: Any) -> float | None:
    """Return ``value`` as a finite float, or ``None`` if it is missing or invalid."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _coerce_rating(value: Any) -> float | None:
    """Return ``value`` as a finite rating clamped to the 0-5 range, or ``None``."""
    number = _coerce_number(value)
    if number is None:
        return None
    return min(max(number, 0.0), 5.0)


def _round_score(value: float) -> float:
    """Clamp a score to the 0-10 range and round it to one decimal place."""
    return round(min(max(value, 0.0), 10.0), 1)


def _join_natural(items: Sequence[str]) -> str:
    """Join items as natural English: ``"a"``, ``"a and b"``, ``"a, b and c"``."""
    values = list(items)
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return f"{', '.join(values[:-1])} and {values[-1]}"