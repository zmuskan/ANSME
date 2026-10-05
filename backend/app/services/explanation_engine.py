"""
Explanation engine.

Turns a score, a metrics breakdown and a verdict into a human-readable
explanation. Deterministic Python only: no AI APIs, no database, no web
framework code.

The output shape (``summary``, ``strengths``, ``weaknesses``,
``verdict_reason``, ``evidence``) is intentionally stable so this module can
later be augmented by a RAG/LLM generator without changing callers.

Public API:
    generate_explanation: Build the structured explanation.
    format_explanation: Render it as plain text.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

#: Metric scores (0-10) at or above this value are reported as strengths.
STRENGTH_THRESHOLD: float = 7.0

#: Metric scores (0-10) below this value are reported as weaknesses.
WEAKNESS_THRESHOLD: float = 5.0

#: metric key -> (display name, strength text, weakness text)
_METRIC_TEXT: dict[str, tuple[str, str, str]] = {
    "price_score": (
        "price",
        "Competitive price / within budget",
        "Price is high or outside the budget",
    ),
    "rating_score": (
        "rating",
        "Strong customer rating",
        "Customer rating is weak",
    ),
    "value_score": (
        "value",
        "Good value for money",
        "Limited value for money",
    ),
    "confidence_score": (
        "confidence",
        "High confidence in the available data",
        "Limited review confidence",
    ),
    "feature_score": (
        "features",
        "Features match the stated needs well",
        "Features only partly match the stated needs",
    ),
    "sentiment_score": (
        "sentiment",
        "Positive review sentiment",
        "Negative review sentiment",
    ),
    "requirement_match_score": (
        "requirements",
        "Strong match for stated requirements",
        "Weak match for stated requirements",
    ),
    "requirement_match": (
        "requirements",
        "Strong match for stated requirements",
        "Weak match for stated requirements",
    ),
}


def generate_explanation(
    overall_score: float | None,
    metrics: Mapping[str, Any] | None,
    verdict: str | None,
) -> dict[str, Any]:
    """
    Generate a human-readable explanation for an ANSME decision.

    Args:
        overall_score: Overall score on a 0-10 scale, or ``None``.
        metrics: Mapping of metric name to 0-10 score (for example
            ``price_score``, ``rating_score``, ``value_score``,
            ``confidence_score``). Unknown metrics are explained generically.
        verdict: ``"BUY"``, ``"CONSIDER"``, ``"SKIP"`` or any other label.

    Returns:
        A dictionary with:

        * ``summary`` (``str``): Score and per-metric breakdown.
        * ``strengths`` (``list[str]``): Metrics scoring well.
        * ``weaknesses`` (``list[str]``): Metrics scoring poorly.
        * ``verdict_reason`` (``str``): Why the verdict was reached.
                * ``evidence`` (``list[dict[str, str]]``): Supporting source evidence,
                    empty until a retrieval layer is connected.
    """
    score = _to_score(overall_score)
    clean_metrics = _clean_metrics(metrics)
    verdict_label = verdict.strip().upper() if isinstance(verdict, str) and verdict.strip() else "UNKNOWN"

    strengths: list[str] = []
    weaknesses: list[str] = []
    for key, value in sorted(clean_metrics.items(), key=lambda kv: kv[1], reverse=True):
        _, strong_text, _ = _metric_text(key)
        if value >= STRENGTH_THRESHOLD:
            strengths.append(strong_text)
    for key, value in sorted(clean_metrics.items(), key=lambda kv: kv[1]):
        _, _, weak_text = _metric_text(key)
        if value < WEAKNESS_THRESHOLD:
            weaknesses.append(weak_text)

    return {
        "summary": _build_summary(score, clean_metrics, verdict_label),
        "strengths": strengths,
        "weaknesses": weaknesses,
        "verdict_reason": _build_verdict_reason(verdict_label, score, clean_metrics),
        "evidence": [],
    }


def format_explanation(
    explanation: Mapping[str, Any],
    overall_score: float | None,
    verdict: str | None,
) -> str:
    """
    Render a structured explanation as plain text.

    Args:
        explanation: Output of ``generate_explanation``.
        overall_score: Overall score shown on the first line.
        verdict: Verdict shown at the end.

    Returns:
        Multi-line text with ``Strengths``, ``Weaknesses`` and ``Verdict``.
    """
    score = _to_score(overall_score)
    score_text = f"{score:.1f}" if score is not None else "N/A"
    verdict_text = verdict.strip().upper() if isinstance(verdict, str) and verdict.strip() else "UNKNOWN"

    lines = [f"This product received a score of {score_text}.", "Strengths:"]
    lines += [f"- {item}" for item in explanation.get("strengths", [])] or ["- None identified"]
    lines.append("Weaknesses:")
    lines += [f"- {item}" for item in explanation.get("weaknesses", [])] or ["- None identified"]
    lines += ["Verdict:", verdict_text]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


def _build_summary(
    score: float | None,
    metrics: Mapping[str, float],
    verdict: str,
) -> str:
    """Compose the score + breakdown sentence(s)."""
    if score is None:
        opening = f"No overall score is available (verdict: {verdict})."
    else:
        opening = f"This product received an overall score of {score:.1f}/10 ({verdict})."

    if not metrics:
        return opening + " No metric breakdown was provided."

    breakdown = ", ".join(
        f"{_metric_text(key)[0]} {value:.1f}" for key, value in metrics.items()
    )
    best_key = max(metrics, key=lambda k: metrics[k])
    worst_key = min(metrics, key=lambda k: metrics[k])

    summary = f"{opening} Breakdown: {breakdown}."
    if len(metrics) > 1:
        summary += (
            f" Strongest area: {_metric_text(best_key)[0]} ({metrics[best_key]:.1f}); "
            f"weakest area: {_metric_text(worst_key)[0]} ({metrics[worst_key]:.1f})."
        )
    return summary


def _build_verdict_reason(
    verdict: str,
    score: float | None,
    metrics: Mapping[str, float],
) -> str:
    """Explain why the verdict was given, citing the metrics that drove it."""
    best = _top_names(metrics, highest=True)
    worst = _top_names(metrics, highest=False)

    if verdict == "BUY":
        reason = "Recommended to buy: the overall score is high"
        if best:
            reason += f", driven mainly by {best}"
        reason += "."
        if worst and metrics and min(metrics.values()) < WEAKNESS_THRESHOLD:
            reason += f" Keep an eye on {worst}."
        return reason

    if verdict == "CONSIDER":
        reason = "Worth considering: the overall score is moderate"
        if best:
            reason += f", helped by {best}"
        if worst:
            reason += f" but held back by {worst}"
        return reason + "."

    if verdict == "SKIP":
        reason = "Not recommended: the overall score is low"
        if worst:
            reason += f", mainly because of {worst}"
        return reason + "."

    score_text = f" (score {score:.1f}/10)" if score is not None else ""
    return f"The verdict '{verdict}'{score_text} has no standard explanation."


def _top_names(metrics: Mapping[str, float], highest: bool) -> str:
    """Return the display name(s) of the best or worst metric(s), or ``""``."""
    if not metrics:
        return ""
    target = max(metrics.values()) if highest else min(metrics.values())
    names = [_metric_text(key)[0] for key, value in metrics.items() if value == target]
    return " and ".join(names)


def _metric_text(key: str) -> tuple[str, str, str]:
    """Return (display name, strength text, weakness text) for a metric key."""
    if key in _METRIC_TEXT:
        return _METRIC_TEXT[key]
    name = key.removesuffix("_score").replace("_", " ").strip() or key
    return (name, f"Strong {name}", f"Weak {name}")


def _clean_metrics(metrics: Mapping[str, Any] | None) -> dict[str, float]:
    """Keep only numeric metrics, clamped to the 0-10 range."""
    if not isinstance(metrics, Mapping):
        return {}
    cleaned: dict[str, float] = {}
    for key, value in metrics.items():
        score = _to_score(value)
        if isinstance(key, str) and score is not None:
            cleaned[key] = score
    return cleaned


def _to_score(value: Any) -> float | None:
    """Return ``value`` as a finite float clamped to 0-10, or ``None``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return min(max(number, 0.0), 10.0)