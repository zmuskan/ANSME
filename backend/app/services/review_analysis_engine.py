from __future__ import annotations

import re
from collections import Counter
from typing import Any


POSITIVE_WORDS = {
    "good",
    "great",
    "excellent",
    "amazing",
    "love",
    "perfect",
    "fast",
    "comfortable",
    "premium",
    "worth",
    "awesome",
}

NEGATIVE_WORDS = {
    "bad",
    "poor",
    "terrible",
    "worst",
    "slow",
    "broken",
    "expensive",
    "waste",
    "issue",
    "problem",
    "defective",
}


def analyze_reviews(reviews: list[str]) -> dict[str, Any]:
    """
    Deterministic review analysis.

    Returns:
        sentiment_score
        positive_reviews
        negative_reviews
        top_keywords
        summary
    """

    if not reviews:
        return {
            "sentiment_score": 5.0,
            "positive_reviews": 0,
            "negative_reviews": 0,
            "top_keywords": [],
            "summary": "No reviews available.",
        }

    positive = 0
    negative = 0
    keywords = Counter()

    for review in reviews:
        text = review.lower()

        pos_hits = sum(word in text for word in POSITIVE_WORDS)
        neg_hits = sum(word in text for word in NEGATIVE_WORDS)

        if pos_hits > neg_hits:
            positive += 1
        elif neg_hits > pos_hits:
            negative += 1

        tokens = re.findall(r"\b[a-z]{4,}\b", text)
        keywords.update(tokens)

    sentiment_score = round(
        ((positive - negative) / max(len(reviews), 1)) * 5 + 5,
        1,
    )

    sentiment_score = max(0.0, min(10.0, sentiment_score))

    return {
        "sentiment_score": sentiment_score,
        "positive_reviews": positive,
        "negative_reviews": negative,
        "top_keywords": [
            word
            for word, _ in keywords.most_common(10)
        ],
        "summary": (
            f"{positive} positive reviews, "
            f"{negative} negative reviews."
        ),
    }