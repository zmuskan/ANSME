"""
Analyze API route.

Wires the first end-to-end ANSME pipeline:

    URL -> product_extractor -> verdict_engine -> repository -> structured response

All recommendations come from deterministic Python code. This module only
receives the request, orchestrates the services, delegates persistence to the
repository layer, and shapes the response. A failure on one URL never fails
the whole request, and a failure to persist one result is reported without
discarding the analysis result.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user_id
from app.db.database import get_db
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.price_history_repository import PriceHistoryRepository
from app.schemas.analyze import AnalyzeRequest, EvidenceResponse
from app.services.analysis_engine import analyze_product
from app.services.product_extractor import extract_product_data
from app.services.verdict_engine import compute_verdict

logger = logging.getLogger(__name__)

router = APIRouter()

# Maximum number of product pages fetched at the same time for one request.
MAX_CONCURRENT_EXTRACTIONS = 10

# Extractor fields that are not returned to API clients (large, internal).
_EXCLUDED_PRODUCT_FIELDS = frozenset({"cleaned_content"})


@router.post("/analyze")
async def analyze(
    request: AnalyzeRequest,
    db: Session = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> dict[str, Any]:
    """
    Analyze one or more product URLs and return a deterministic verdict for each.

    For every URL the product is extracted, scored against the optional
    budget, and merged with its verdict. Results keep the same order as the
    submitted URLs. URLs that cannot be processed appear in ``products`` with
    ``"status": "error"`` and an ``"error"`` message; the rest are unaffected.

    Each successful result is persisted through ``AnalysisRepository``. A
    persistence failure for one result is logged and does not affect the
    other results or the response.

    Raises:
        HTTPException: 400 if no non-empty URL is provided.
    """
    urls = _clean_urls(request.urls)
    if not urls:
        raise HTTPException(status_code=400, detail="At least one URL is required.")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)
    products = await asyncio.gather(
        *(
            _process_url(
                url,
                request.budget,
                semaphore,
                request.requirements,
                request.budget_currency,
                "budget_currency" in request.model_fields_set,
            )
            for url in urls
        )
    )

    if request.save_history:
        _persist_successful_products(db, products, user_id)

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


def _persist_successful_products(
    db: Session,
    products: list[dict[str, Any]],
    user_id: UUID,
) -> None:
    """
    Persist every successful product result via ``AnalysisRepository``.

    Each result is saved independently. A failed save is reported on that
    product, and any partially persisted analysis is removed when possible.
    """
    for product in products:
        if product.get("status") != "success":
            continue

        analysis_id: int | None = None
        try:
            analysis = AnalysisRepository.create_analysis(
                db,
                _build_analysis_data(product, user_id),
            )
            analysis_id = analysis.id
            if product.get("price") is not None:
                PriceHistoryRepository.create(
                    db,
                    analysis_id=analysis.id,
                    price=float(product["price"]),
                    price_raw=product.get("price_raw"),
                    price_currency=product.get("price_currency"),
                )
            analysis_details = product.get("analysis") or {}
            for pro in analysis_details.get("pros", []):
                EvidenceRepository.create(
                    db=db,
                    analysis_id=analysis.id,
                    source_type="pro",
                    evidence_text=pro,
                    quality_score=_evidence_quality(product, pro),
                )
            for con in analysis_details.get("cons", []):
                EvidenceRepository.create(
                    db=db,
                    analysis_id=analysis.id,
                    source_type="con",
                    evidence_text=con,
                    quality_score=_evidence_quality(product, con),
                )
            product["price_history"] = PriceHistoryRepository.for_analysis(db, analysis)
            product["similar_products"] = [
                {
                    "id": item.id,
                    "title": item.title,
                    "url": item.url,
                    "price": item.price,
                    "overall_score": item.overall_score,
                    "verdict": item.verdict,
                }
                for item in AnalysisRepository.find_similar(db, analysis, user_id)
            ]
            product["history_saved"] = True
        except Exception:
            try:
                db.rollback()
            except Exception:
                logger.exception("Failed to roll back analysis persistence")
            if analysis_id is not None:
                try:
                    AnalysisRepository.delete_analysis(db, analysis_id, user_id)
                except Exception:
                    logger.exception(
                        "Failed to remove incomplete analysis after a save failure"
                    )
            logger.exception("Failed to save analysis result")
            product["history_saved"] = False
            product["history_save_error"] = (
                "Analysis completed, but it could not be saved to your history."
            )


def _build_analysis_data(
    product: dict[str, Any],
    user_id: UUID,
) -> dict[str, Any]:
    """Map a successful product result to the column values for ``Analysis``."""
    analysis_details = product.get("analysis") or {}
    return {
        "user_id": user_id,
        "url": product["url"],
        "title": product.get("title"),
        "brand": product.get("brand"),
        "price": product.get("price"),
        "price_raw": product.get("price_raw"),
        "price_currency": product.get("price_currency"),
        "rating": product.get("rating"),
        "image_url": product.get("image_url"),
        "description": product.get("description"),
        "overall_score": product["overall_score"],
        "verdict": product["verdict"],
        "sentiment_score": analysis_details.get("sentiment_score"),
        "requirement_match": analysis_details.get("requirement_match"),
        "pros": analysis_details.get("pros"),
        "cons": analysis_details.get("cons"),
        "risk_flags": analysis_details.get("risk_flags"),
        "explanation": analysis_details.get("explanation"),
        "metrics": product.get("metrics"),
        "score_breakdown": product.get("score_breakdown"),
        "processing_time_ms": product.get("processing_time_ms", 0),
        "sources_analyzed": product.get("sources_analyzed", 0),
        "review_count": product.get("review_count"),
        "category": product.get("category", "Other"),
    }


async def _process_url(
    url: str,
    budget: float | None,
    semaphore: asyncio.Semaphore,
    requirements: str | None = None,
    budget_currency: str | None = None,
    budget_currency_is_explicit: bool = False,
) -> dict[str, Any]:
    """
    Run the full pipeline for one URL without ever raising.

    Returns the merged product + verdict dictionary on success, or an error
    dictionary (``url``, ``status``, ``error``) on failure.
    """
    start_time = time.perf_counter()
    try:
        async with semaphore:
            product = await extract_product_data(url)

        if not isinstance(product, dict) or product.get("status") != "success":
            return _build_error(url, product)

        analysis = analyze_product(
            title=product.get("title"),
            description=product.get("description"),
            price=product.get("price"),
            rating=product.get("rating"),
            requirements=requirements,
        )
        effective_budget = budget
        budget_status = (
            "not_provided"
            if budget is None
            else "applied"
            if budget_currency_is_explicit
            else "legacy_numeric"
        )
        if budget is not None and budget_currency_is_explicit:
            if (
                not _currencies_match(budget_currency, product.get("price_currency"))
                or not _has_usable_price(product.get("price"))
            ):
                effective_budget = None
                budget_status = "unverified"
        verdict = compute_verdict(
            price=product.get("price"),
            rating=product.get("rating"),
            budget=effective_budget,
        )

        result = _merge_product_and_verdict(product, verdict)
        result["budget_status"] = budget_status
        result["analysis"] = analysis
        result["sources_analyzed"] = 1
        result["category"] = _classify_category(
            f"{product.get('title') or ''} {product.get('description') or ''}"
        )
        result["score_breakdown"] = _build_score_breakdown(verdict.get("metrics", {}))
        result["evidence"] = _build_evidence_response(result)
        result["processing_time_ms"] = int((time.perf_counter() - start_time) * 1000)
        result["price_history"] = {
            "history": (
                [{
                    "price": product["price"],
                    "price_raw": product.get("price_raw"),
                    "price_currency": product.get("price_currency"),
                    "captured_at": None,
                }]
                if product.get("price") is not None
                else []
            ),
            "lowest_seen": product.get("price"),
            "highest_seen": product.get("price"),
            "common_currency": product.get("price_currency"),
        }
        return result
    except Exception as exc:  # noqa: BLE001 - one bad URL must not fail the request
        logger.exception("Unexpected failure while analyzing %s", url)
        return {
            "url": url,
            "status": "error",
            "error": str(exc) or exc.__class__.__name__,
        }


def _currencies_match(currency_a: Any, currency_b: Any) -> bool:
    """Return whether two valid ISO-style currency codes match."""
    if not all(isinstance(currency, str) for currency in (currency_a, currency_b)):
        return False
    normalized_a = currency_a.strip()
    normalized_b = currency_b.strip()
    return (
        all(
            len(currency) == 3 and currency.isascii() and currency.isalpha()
            for currency in (normalized_a, normalized_b)
        )
        and normalized_a.upper() == normalized_b.upper()
    )


def _has_usable_price(value: Any) -> bool:
    """Return whether a product price is finite and positive."""
    if value is None or isinstance(value, bool):
        return False
    try:
        price = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(price) and price > 0


def _build_error(url: str, product: Any) -> dict[str, Any]:
    """Build the error entry for a failed extraction."""
    message = "Product extraction failed."
    if isinstance(product, dict):
        message = str(product.get("error") or message)
    return {"url": url, "status": "error", "error": message}


def _build_score_breakdown(metrics: dict[str, Any]) -> dict[str, float]:
    """Return weighted score contributions from the verdict engine metrics."""
    return {
        "Value contribution": round(float(metrics.get("value_score", 0)) * 0.45, 2),
        "Rating contribution": round(float(metrics.get("rating_score", 0)) * 0.45, 2),
        "Confidence contribution": round(
            float(metrics.get("confidence_score", 0)) * 0.10,
            2,
        ),
    }


def _build_evidence_response(product: dict[str, Any]) -> list[dict[str, Any]]:
    """Link generated pros and cons to the product page they were derived from."""
    analysis = product.get("analysis") or {}
    evidence = [
        EvidenceResponse(
            title=product.get("title") or product["url"],
            url=product["url"],
            source=source,
            score=float(product.get("overall_score", 0)),
            snippet=snippet,
            quality_score=_evidence_quality(product, snippet),
        ).model_dump()
        for source, key in (("Strength", "pros"), ("Concern", "cons"))
        for snippet in analysis.get(key, [])
    ]
    return evidence


def _evidence_quality(product: dict[str, Any], snippet: str) -> float:
    """Score evidence completeness using extracted rating, reviews, and text."""
    quality = 0
    if product.get("rating") is not None:
        quality += 40
    if product.get("review_count"):
        quality += 30
    if len(snippet) > 80:
        quality += 30
    return float(quality)


def _classify_category(text: str) -> str:
    """Assign a coarse product category from title/description keywords."""
    normalized = text.casefold()
    category_terms = {
        "Electronics": ("phone", "laptop", "headphone", "tablet", "camera", "electronics", "smartwatch", "speaker", "television", "tv"),
        "Fashion": ("clothing", "shirt", "dress", "shoe", "sneaker", "jacket", "fashion", "handbag", "jeans"),
        "Beauty": ("skincare", "cosmetic", "makeup", "shampoo", "perfume", "beauty", "moisturizer", "serum"),
        "Books": ("book", "novel", "paperback", "hardcover", "isbn", "textbook"),
        "Home": ("furniture", "kitchen", "bedding", "appliance", "home", "mattress", "lamp", "vacuum"),
    }
    for category, terms in category_terms.items():
        if any(term in normalized for term in terms):
            return category
    return "Other"


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