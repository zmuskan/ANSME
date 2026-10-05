from __future__ import annotations

import re
from typing import Any


def retrieve_relevant_evidence(
    evidence: list[dict[str, Any]],
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Simple deterministic retrieval engine.

    Returns evidence ranked by keyword overlap.

    Expected evidence format:

    [
        {
            "source": "review",
            "text": "Battery lasts two days"
        }
    ]
    """

    if not query.strip():
        return []

    query_terms = set(_tokenize(query))

    scored: list[tuple[int, dict[str, Any]]] = []

    for item in evidence:
        text = str(item.get("text", ""))

        evidence_terms = set(_tokenize(text))

        overlap = len(
            query_terms.intersection(
                evidence_terms
            )
        )

        if overlap > 0:
            scored.append(
                (
                    overlap,
                    item,
                )
            )

    scored.sort(
        key=lambda x: x[0],
        reverse=True,
    )

    return [
        item
        for _, item in scored[:limit]
    ]


def _tokenize(text: str) -> list[str]:
    return re.findall(
        r"\b[a-z0-9]+\b",
        text.lower(),
    )