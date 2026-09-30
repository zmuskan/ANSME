"""
Analyze API route.

Wires the first end-to-end ANSME pipeline:

    URL -> product_extractor -> verdict_engine -> structured response

All recommendations come from deterministic Python code. This module only
receives the request, orchestrates the two services, and shapes the response.
A failure on one URL never fails the whole request.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.schemas.analyze import AnalyzeRequest
from app.services.product_extractor import extract_product_data
from app.services.verdict_engine import compute_verdict

logger = logging.getLogger(__name__)

router = APIRouter()

# Maximum number of product pages fetched at the same time for one request.
MAX_CONCURRENT_EXTRACTIONS = 10

# Extractor fields that are not returned to API clients (large, internal).
_EXCLUDED_PRODUCT_FIELDS = frozenset({"cleaned_content"})


@router.post("/analyze")
async def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    """
    Analyze one or more product URLs and return a deterministic verdict for each.

    For every URL the product is extracted, scored against the optional
    budget, and merged with its verdict. Results keep the same order as the
    submitted URLs. URLs that cannot be processed appear in ``products`` with
    ``"status": "error"`` and an ``"error"`` message; the rest are unaffected.

    Raises:
        HTTPException: 400 if no non-empty URL is provided.
    """
    urls = _clean_urls(request.urls)
    if not urls:
        raise HTTPException(status_code=400, detail="At least one URL is required.")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)
    products = await asyncio.gather(
        *(_process_url(url, request.budget, semaphore) for url in urls)
    )

    successful = sum(1 for p in products if p.get("status") == "success")
    failed = len(products) - successful

    return {
        "status": "success",
        "processed_count": len(products),
        "successful_count": successful,
        "failed_count": failed,
        "budget": request.budget,
        "products": list(products),
    }


def _clean_urls(urls: list[str] | None) -> list[str]:
    """Trim URLs and drop empty or non-string entries."""
    if not urls:
        return []
    return [url.strip() for url in urls if isinstance(url, str) and url.strip()]


async def _process_url(
    url: str,
    budget: float | None,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """
    Run the full pipeline for one URL without ever raising.

    Returns the merged product + verdict dictionary on success, or an error
    dictionary (``url``, ``status``, ``error``) on failure.
    """
    try:
        async with semaphore:
            product = await extract_product_data(url)

        if not isinstance(product, dict) or product.get("status") != "success":
            return _build_error(url, product)

        verdict = compute_verdict(
            price=product.get("price"),
            rating=product.get("rating"),
            budget=budget,
        )
        return _merge_product_and_verdict(product, verdict)
    except Exception as exc:  # noqa: BLE001 - one bad URL must not fail the request
        logger.exception("Unexpected failure while analyzing %s", url)
        return {
            "url": url,
            "status": "error",
            "error": str(exc) or exc.__class__.__name__,
        }


def _build_error(url: str, product: Any) -> dict[str, Any]:
    """Build the error entry for a failed extraction."""
    message = "Product extraction failed."
    if isinstance(product, dict):
        message = str(product.get("error") or message)
    return {"url": url, "status": "error", "error": message}


def _merge_product_and_verdict(
    product: dict[str, Any],
    verdict: dict[str, Any],
) -> dict[str, Any]:
    """Combine extracted product fields with the verdict engine output."""
    merged = {
        key: value
        for key, value in product.items()
        if key not in _EXCLUDED_PRODUCT_FIELDS
    }
    # Compatible with overall_score or final_score key
    merged["overall_score"] = verdict.get("overall_score", verdict.get("final_score", 0.0))
    merged["verdict"] = verdict.get("verdict", "UNKNOWN")
    merged["metrics"] = verdict.get("metrics", {})
    return merged