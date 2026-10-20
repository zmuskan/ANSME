"""
Product extraction service.

Fetches a product page and converts it into a standardized dictionary of raw
product data. This module collects raw data only; it performs no scoring,
verdict generation, LLM calls, database operations, or FastAPI operations.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
from typing import Any, Iterator
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup

__all__ = ["extract_product_data"]

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=8.0)
MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MIN_IMAGE_DIMENSION = 200
DESCRIPTION_SNIPPET_CHARS = 300

# Use a descriptive, non-spoofed user agent. Retailers may still block requests.
REQUEST_HEADERS = {
    "User-Agent": "ANSME product research tool (product data extraction)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

_PRICE_PREFIX_RE = re.compile(
    r"(?:₹|Rs\.?|INR|US\$|USD|\$|€|EUR|£|GBP)\s*([\d][\d.,]*)",
    re.IGNORECASE,
)
_PRICE_SUFFIX_RE = re.compile(r"([\d][\d.,]*)\s*(?:€|EUR)", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d[\d.,]*")
_STALE_PRICE_RE = re.compile(
    r"\b(?:old|was|original|mrp|strike|list|compare|regular|crossed|discount|saving|save)\b",
    re.IGNORECASE,
)
_SKIP_IMAGE_RE = re.compile(
    r"(?:logo|icon|sprite|pixel|avatar|badge|placeholder|spinner|loading|blank|banner|events|g/31)",
    re.IGNORECASE,
)
_PRODUCT_TYPES = {"product", "productgroup", "individualproduct"}


class ProductExtractionError(Exception):
    """Expected extraction failure with a safe, user-facing message."""


def _error_result(url: str, message: str, *, error_code: str) -> dict[str, Any]:
    return {
        "url": url,
        "status": "error",
        "error": message,
        "error_code": error_code,
    }


async def extract_product_data(url: str) -> dict[str, Any]:
    """
    Fetch a product page and return standardized raw product data.

    The returned keys remain compatible with the existing ANSME pipeline.
    Failed or clearly unusable pages return status="error"; they are not
    reported as successful extractions with empty or misleading product data.
    """
    try:
        target = _normalize_url(url)
        html, final_url = await _fetch_html(target)
        parsed = await asyncio.to_thread(_parse_product_page, html, final_url)

        if parsed["is_blocked_page"]:
            return _error_result(
                url,
                "The retailer returned a block, CAPTCHA, or verification page. "
                "ANSME could not access reliable product data.",
                error_code="retailer_blocked",
            )

        title = parsed["title"]
        if not title or _is_unusable_title(title):
            return _error_result(
                url,
                "The page did not expose a reliable product title. No analysis was run.",
                error_code="product_data_unavailable",
            )

        # A title alone is insufficient: require at least one additional
        # product-specific signal before claiming extraction succeeded.
        has_product_signal = (
            parsed["price"] is not None
            or parsed["image_url"] is not None
            or parsed["brand"] is not None
            or parsed["rating"] is not None
            or parsed["schema_product_found"]
        )
        if not has_product_signal:
            return _error_result(
                url,
                "The page did not expose enough product-specific information "
                "to extract reliably.",
                error_code="product_data_unavailable",
            )

        return {
            "url": url,
            "title": title,
            "brand": parsed["brand"],
            "price": parsed["price"],
            "price_raw": parsed["price_raw"],
            "price_currency": parsed["price_currency"],
            "rating": parsed["rating"],
            "review_count": parsed["review_count"],
            "image_url": parsed["image_url"],
            "description": parsed["description"],
            "cleaned_content": parsed["cleaned_content"],
            "status": "success",
        }

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code == 403:
            message = (
                "Access was blocked by the retailer (HTTP 403). "
                "ANSME cannot extract this page automatically."
            )
            code = "retailer_blocked"
        elif status_code == 404:
            message = "The retailer says this product page was not found (HTTP 404)."
            code = "page_not_found"
        elif status_code in (401, 407, 429):
            message = (
                f"The retailer or network denied the request (HTTP {status_code}). "
                "Try again later or use a retailer-supported data source."
            )
            code = "access_restricted"
        else:
            message = f"The retailer returned HTTP {status_code}; product data could not be retrieved."
            code = "http_error"
        logger.warning("Product extraction failed for %s: HTTP %s", url, status_code)
        return _error_result(url, message, error_code=code)

    except httpx.TimeoutException:
        logger.warning("Product extraction timed out for %s", url)
        return _error_result(
            url,
            "The retailer took too long to respond. Try again later.",
            error_code="request_timeout",
        )
    except httpx.TooManyRedirects:
        logger.warning("Too many redirects while fetching %s", url)
        return _error_result(
            url,
            "The retailer redirected the request too many times.",
            error_code="too_many_redirects",
        )
    except (httpx.RequestError, ValueError) as exc:
        logger.warning("Product extraction could not fetch %s: %s", url, exc)
        return _error_result(
            url,
            "The product page could not be retrieved or parsed safely.",
            error_code="fetch_error",
        )
    except Exception:
        logger.exception("Unexpected product extraction failure for %s", url)
        return _error_result(
            url,
            "An unexpected extraction error occurred. No reliable product data was returned.",
            error_code="extraction_error",
        )


def _normalize_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL must be a non-empty string")
    cleaned = url.strip()
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise ValueError("URL has no hostname")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing embedded credentials are not supported")
    return cleaned


async def _assert_public_host(request: httpx.Request) -> None:
    """Reject private or special-use destinations on every request/redirect."""
    host = request.url.host
    if not host:
        raise ValueError("URL has no hostname")
    try:
        literal_ip = ipaddress.ip_address(host)
        addresses = [str(literal_ip)]
    except ValueError:
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host, port, type=socket.SOCK_STREAM
            )
        except socket.gaierror as exc:
            raise ValueError(f"Could not resolve host: {host}") from exc
        
        addresses = [
            str(info[4][0]).split("%")[0]
            for info in infos
        ]

    if not addresses:
        raise ValueError("Hostname did not resolve to an address")

    for address in addresses:
        parsed_ip = ipaddress.ip_address(address)
        if not parsed_ip.is_global:
            raise ValueError("Refusing to fetch a non-public address")


async def _fetch_html(url: str) -> tuple[str, str]:
    async with httpx.AsyncClient(
        headers=REQUEST_HEADERS,
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        event_hooks={"request": [_assert_public_host]},
    ) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if content_type and not any(
                item in content_type for item in ("html", "xml", "text/plain")
            ):
                raise ValueError(f"Unsupported content type: {content_type}")

            body = bytearray()
            async for chunk in response.aiter_bytes():
                remaining = MAX_RESPONSE_BYTES - len(body)
                if remaining <= 0:
                    break
                body.extend(chunk[:remaining])
                if len(body) >= MAX_RESPONSE_BYTES:
                    break

            return _decode_body(bytes(body), response.charset_encoding), str(response.url)


def _decode_body(body: bytes, header_charset: str | None) -> str:
    encoding = header_charset
    if not encoding:
        match = re.search(rb"""charset=["']?([\w-]+)""", body[:4096], re.IGNORECASE)
        encoding = match.group(1).decode("ascii", "ignore") if match else "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _parse_product_page(html: str, base_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    product = _find_schema_product(soup)
    cleaned_content = _extract_cleaned_content(html, base_url)
    if not cleaned_content:
        cleaned_content = _fallback_text(html)

    blocked = _looks_like_block_page(soup, cleaned_content)
    title = _extract_title(soup, product, base_url)
    price = _extract_price_details(soup, product, cleaned_content, base_url)
    return {
        "title": title,
        "brand": _extract_brand(soup, product),
        "price": price["amount"],
        "price_raw": price["raw"],
        "price_currency": price["currency"],
        "rating": _extract_rating(soup, product),
        "review_count": _extract_review_count(soup, product),
        "image_url": _extract_image(soup, product, base_url),
        "description": _extract_description(soup, product, cleaned_content),
        "cleaned_content": cleaned_content,
        "schema_product_found": product is not None,
        "is_blocked_page": blocked,
    }


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _meta_content(soup: BeautifulSoup, *keys: str) -> str | None:
    for key in keys:
        for attr in ("property", "name", "itemprop"):
            tag = soup.find("meta", attrs={attr: key})
            if tag:
                content = _clean_text(tag.get("content"))
                if content:
                    return content
    return None


def _absolute_url(base_url: str, candidate: Any) -> str | None:
    if isinstance(candidate, dict):
        candidate = candidate.get("url") or candidate.get("contentUrl")
    if not isinstance(candidate, str):
        return None
    candidate = candidate.strip()
    if not candidate or candidate.startswith("data:"):
        return None
    absolute = urljoin(base_url, candidate)
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if _SKIP_IMAGE_RE.search(parsed.path):
        return None
    return absolute


def _snippet(text: str, limit: int = DESCRIPTION_SNIPPET_CHARS) -> str | None:
    text = _clean_text(text)
    if not text:
        return None
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:- ")
    return f"{cut}..."


def _iter_nodes(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _iter_nodes(value)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, (dict, list)):
                yield from _iter_nodes(item)


def _is_product_node(node: dict) -> bool:
    node_type = node.get("@type")
    types = node_type if isinstance(node_type, list) else [node_type]
    return any(
        isinstance(item, str) and item.rsplit("/", 1)[-1].lower() in _PRODUCT_TYPES
        for item in types
    )


def _find_schema_product(soup: BeautifulSoup) -> dict | None:
    candidates: list[dict] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        candidates.extend(node for node in _iter_nodes(data) if _is_product_node(node))

    if not candidates:
        return None

    # Prefer the Product node whose name best agrees with the primary title.
    primary = soup.select_one("#productTitle")
    primary_title = _clean_text(primary.get_text(" ")) if primary else ""
    if primary_title:
        for candidate in candidates:
            if _clean_text(str(candidate.get("name", ""))).casefold() == primary_title.casefold():
                return candidate
    return candidates[0]


def _schema_brand(product: dict) -> str | None:
    for key in ("brand", "manufacturer"):
        value = product.get(key)
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, dict):
            value = value.get("name")
        name = _clean_text(value)
        if name:
            return name
    return None


def _schema_image(product: dict) -> Any:
    return product.get("image")


def _schema_price_details(product: dict) -> dict[str, Any]:
    offers = product.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return {"amount": None, "raw": None, "currency": None}

    candidates: list[tuple[Any, str | None]] = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        currency = _normalize_currency(offer.get("priceCurrency"))
        availability = str(offer.get("availability", "")).rsplit("/", 1)[-1].lower()
        # Avoid offers explicitly marked out of stock when an in-stock offer exists.
        if availability in {"outofstock", "discontinued", "soldout"}:
            continue
        candidates.extend(
            [(offer.get("price"), currency), (offer.get("lowPrice"), currency)]
        )
        specs = offer.get("priceSpecification")
        for spec in specs if isinstance(specs, list) else [specs]:
            if isinstance(spec, dict):
                candidates.append(
                    (spec.get("price"), _normalize_currency(spec.get("priceCurrency")) or currency)
                )
        nested = offer.get("offers")
        if nested:
            nested_details = _schema_price_details({"offers": nested})
            if nested_details["amount"] is not None:
                candidates.append(
                    (nested_details["amount"], nested_details["currency"] or currency)
                )

    for value, currency in candidates:
        amount = _to_price(value)
        if amount is not None:
            raw = str(value).strip()
            return {
                "amount": amount,
                "raw": raw,
                "currency": currency or _currency_from_text(raw),
            }
    return {"amount": None, "raw": None, "currency": None}


def _schema_rating(product: dict) -> float | None:
    aggregate = product.get("aggregateRating")
    if isinstance(aggregate, dict):
        return _to_rating(aggregate.get("ratingValue"))
    return None


def _schema_review_count(product: dict | None) -> int | None:
    aggregate = product.get("aggregateRating") if product else None
    if not isinstance(aggregate, dict):
        return None
    return _to_count(aggregate.get("reviewCount") or aggregate.get("ratingCount"))


def _to_count(value: Any) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d[\d,]*", str(value))
    if not match:
        return None
    count = int(match.group(0).replace(",", ""))
    return count if count > 0 else None


def _extract_review_count(soup: BeautifulSoup, product: dict | None) -> int | None:
    count = _schema_review_count(product)
    if count is not None:
        return count
    for selector in (
        '[itemprop="reviewCount"]',
        '[itemprop="ratingCount"]',
        "#acrCustomerReviewText",
        '[class*="review-count" i]',
        '[class*="rating-count" i]',
    ):
        for node in soup.select(selector)[:10]:
            count = _to_count(node.get("content") or node.get_text(" "))
            if count is not None:
                return count
    return None


def _is_unusable_title(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", title).strip().casefold()
    unusable = {
        "add to your order",
        "page not found",
        "access denied",
        "robot check",
        "sorry! something went wrong!",
        "just a moment...",
    }
    return (
        normalized in unusable
        or "add to your order" in normalized
        or "robot check" in normalized
        or len(normalized) < 3
    )


def _extract_title(
    soup: BeautifulSoup, product: dict | None = None, base_url: str = ""
) -> str:
    # Amazon's primary product title is more reliable than arbitrary page headings.
    amazon_title = soup.select_one("#productTitle")
    if amazon_title:
        text = _clean_text(amazon_title.get_text(" "))
        if text and not _is_unusable_title(text):
            return text

    if product:
        schema_title = _clean_text(str(product.get("name", "")))
        if schema_title and not _is_unusable_title(schema_title):
            return schema_title

    for selector in ('meta[property="og:title"]', 'meta[name="twitter:title"]'):
        tag = soup.select_one(selector)
        if tag:
            text = _clean_text(tag.get("content"))
            if text and not _is_unusable_title(text):
                return text

    h1 = soup.find("h1")
    if h1:
        text = _clean_text(h1.get_text(" "))
        if text and not _is_unusable_title(text):
            return text

    title_tag = soup.title
    if title_tag:
        text = _clean_text(title_tag.get_text(" "))
        if text and not _is_unusable_title(text):
            return text
    return ""


def _extract_brand(soup: BeautifulSoup, product: dict | None) -> str | None:
    if product:
        brand = _schema_brand(product)
        if brand:
            return brand

    amazon_brand = soup.select_one("#bylineInfo")
    if amazon_brand:
        text = _clean_text(amazon_brand.get_text(" "))
        if text:
            text = re.sub(r"^(?:visit the|brand:)\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s+store$", "", text, flags=re.IGNORECASE)
            return text or None

    brand = _meta_content(soup, "product:brand", "og:brand", "brand", "twitter:brand")
    if brand:
        return brand

    node = soup.find(itemprop="brand")
    if node:
        inner = node.select_one('[itemprop="name"]')
        source = inner or node
        text = _clean_text(source.get("content") or source.get_text(" "))
        if text:
            return text
    return None


def _parse_price_string(raw: str) -> float | None:
    match = _NUMBER_RE.search(raw or "")
    if not match:
        return None
    token = match.group(0).rstrip(".,")
    has_comma, has_dot = "," in token, "." in token
    if has_comma and has_dot:
        decimal_sep = "," if token.rfind(",") > token.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        token = token.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif has_comma:
        is_thousands = bool(
            re.fullmatch(r"\d{1,3}(,\d{3})+", token)
            or re.fullmatch(r"\d{1,2}(,\d{2})+,\d{3}", token)
        )
        token = token.replace(",", "") if is_thousands else token.replace(",", ".")
    elif has_dot and token.count(".") > 1:
        token = token.replace(".", "")
    try:
        value = float(token)
    except ValueError:
        return None
    return value if value > 0 else None


def _to_price(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    if isinstance(value, str):
        return _parse_price_string(value)
    return None


def _currency_from_text(raw: str) -> str | None:
    if re.search(r"\bINR\b|₹|\bRs\.?\b", raw, re.IGNORECASE):
        return "INR"
    if re.search(r"\bUSD\b|US\$|\$", raw, re.IGNORECASE):
        return "USD"
    if re.search(r"\bEUR\b|€", raw, re.IGNORECASE):
        return "EUR"
    if re.search(r"\bGBP\b|£", raw, re.IGNORECASE):
        return "GBP"
    return None


def _normalize_currency(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    currency = value.strip().upper()
    if re.fullmatch(r"[A-Z]{3}", currency):
        return currency
    return _currency_from_text(currency)


def _is_stale_price_element(element: Any) -> bool:
    if element.name in {"del", "s", "strike"} or element.find_parent(["del", "s", "strike"]):
        return True
    classes = " ".join(element.get("class") or [])
    identifier = element.get("id") or ""
    return bool(_STALE_PRICE_RE.search(f"{classes} {identifier}"))


def _price_details_from_node(node: Any, *, default_currency: str | None = None) -> dict[str, Any]:
    raw_value = node.get("content") or node.get("value") or node.get_text(" ")
    raw = _clean_text(str(raw_value))
    amount = _parse_price_string(raw)
    if amount is None:
        return {"amount": None, "raw": None, "currency": None}
    currency_node = node.find_parent(attrs={"itemtype": re.compile("Offer", re.IGNORECASE)})
    currency = None
    if currency_node:
        currency_tag = currency_node.select_one('[itemprop="priceCurrency"]')
        if currency_tag:
            currency = _normalize_currency(
                currency_tag.get("content") or currency_tag.get_text(" ")
            )
    return {
        "amount": amount,
        "raw": raw,
        "currency": currency or _currency_from_text(raw) or default_currency,
    }


def _extract_price(soup: BeautifulSoup, product: dict | None, cleaned_content: str) -> float | None:
    return _extract_price_details(soup, product, cleaned_content, "").get("amount")


def _extract_price_details(
    soup: BeautifulSoup,
    product: dict | None,
    cleaned_content: str,
    base_url: str = "",
) -> dict[str, Any]:
    # Amazon: only inspect the primary product's price widgets, never page-wide
    # generic price selectors as a fallback for Amazon.
    is_amazon = "amazon." in (urlparse(base_url).hostname or "").lower()
    if is_amazon:
        for selector in (
            "#corePrice_feature_div .a-price:not(.a-text-price) .a-offscreen",
            "#corePrice_feature_div .a-price:not(.a-text-price) .a-price-whole",
            "#apex_desktop .a-price:not(.a-text-price) .a-offscreen",
            "#priceblock_dealprice",
            "#priceblock_ourprice",
        ):
            for node in soup.select(selector)[:5]:
                if _is_stale_price_element(node):
                    continue
                raw = _clean_text(node.get("content") or node.get_text(" "))
                amount = _parse_price_string(raw)
                if amount is not None:
                    return {
                        "amount": amount,
                        "raw": raw,
                        "currency": _currency_from_text(raw) or "INR",
                    }

        # Amazon often publishes price and currency in a scoped JSON blob.
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or script.get_text())
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
            for node in _iter_nodes(data):
                if not _is_product_node(node):
                    continue
                details = _schema_price_details(node)
                if details["amount"] is not None:
                    return details
        # Do not fall back to arbitrary page text on Amazon: it commonly contains
        # accessory/upsell prices unrelated to the requested product.
        return {"amount": None, "raw": None, "currency": None}

    if product:
        details = _schema_price_details(product)
        if details["amount"] is not None:
            return details

    meta_price = _meta_content(
        soup, "product:price:amount", "og:price:amount", "product:sale_price:amount"
    )
    if meta_price:
        amount = _parse_price_string(meta_price)
        if amount is not None:
            return {
                "amount": amount,
                "raw": meta_price,
                "currency": _normalize_currency(
                    _meta_content(soup, "product:price:currency", "og:price:currency")
                ) or _currency_from_text(meta_price),
            }

    for node in soup.select('[itemprop="price"]')[:10]:
        details = _price_details_from_node(node)
        if details["amount"] is not None:
            return details

    for node in soup.select('[class*="price" i], [id*="price" i]')[:40]:
        if _is_stale_price_element(node):
            continue
        # Skip broad containers that aggregate multiple price elements.
        if node.select_one('[class*="price" i], [id*="price" i]'):
            continue
        details = _price_text_details(node.get_text(" "))
        if details["amount"] is not None:
            return details

    # Generic free-text price extraction is a last resort for non-Amazon pages.
    return _price_text_details(cleaned_content[:20000])


def _price_text_details(text: str) -> dict[str, Any]:
    match = _PRICE_PREFIX_RE.search(text or "") or _PRICE_SUFFIX_RE.search(text or "")
    if not match:
        return {"amount": None, "raw": None, "currency": None}
    raw = match.group(0).strip()
    return {
        "amount": _parse_price_string(match.group(1)),
        "raw": raw,
        "currency": _currency_from_text(raw),
    }


def _to_rating(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        value_float = float(str(value).strip())
        if 0 <= value_float <= 5:
            return round(value_float, 2)
        if 5 < value_float <= 10:
            return round(value_float / 2, 2)
        if 10 < value_float <= 100:
            return round(value_float / 100 * 5, 2)
    except (ValueError, TypeError):
        pass
    return None


def _extract_rating(soup: BeautifulSoup, product: dict | None) -> float | None:
    if product:
        rating = _schema_rating(product)
        if rating is not None:
            return rating

    amazon_rating = soup.select_one("#acrPopover")
    if amazon_rating:
        title = str(amazon_rating.get("title") or "")
        match = re.search(r"(\d+(?:\.\d+)?)\s*out of", title, re.I)
        if match:
            rating = _to_rating(match.group(1))
            if rating is not None:
                return rating

    meta_rating = _meta_content(soup, "og:rating", "twitter:rating", "product:rating:value")
    if meta_rating:
        rating = _to_rating(meta_rating)
        if rating is not None:
            return rating

    for node in soup.select('[itemprop="ratingValue"]')[:10]:
        rating = _to_rating(node.get("content") or node.get_text(" "))
        if rating is not None:
            return rating

    for node in soup.select('[class*="rating" i], [id*="rating" i]')[:20]:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:out of|/)\s*5", node.get_text(" "), re.I)
        if match:
            rating = _to_rating(match.group(1))
            if rating is not None:
                return rating
    return None


def _dimension(value: Any) -> int | None:
    match = re.match(r"\s*(\d+)", str(value)) if value is not None else None
    return int(match.group(1)) if match else None


def _is_valid_image_url(candidate: str | None) -> bool:
    if not candidate:
        return False
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    if _SKIP_IMAGE_RE.search(parsed.path):
        return False
    return True


def _first_large_image(soup: BeautifulSoup, base_url: str) -> str | None:
    unsized_fallback = None
    for img in soup.find_all("img"):
        src_value = (
            img.get("data-old-hires")
            or img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-original")
            or img.get("src")
        )
        if not isinstance(src_value, str) or not src_value:
            continue
        absolute = _absolute_url(base_url, src_value)
        if not absolute or not _is_valid_image_url(absolute):
            continue
        if absolute.lower().split("?")[0].endswith((".svg", ".gif")):
            continue
        dims = [
            dimension
            for dimension in (_dimension(img.get("width")), _dimension(img.get("height")))
            if dimension
        ]
        if dims:
            if min(dims) >= MIN_IMAGE_DIMENSION:
                return absolute
            continue
        unsized_fallback = unsized_fallback or absolute
    return unsized_fallback


def _extract_image(soup: BeautifulSoup, product: dict | None, base_url: str) -> str | None:
    is_amazon = "amazon." in (urlparse(base_url).hostname or "").lower()
    if is_amazon:
        image_node = soup.select_one("#landingImage, #imgBlkFront")
        if image_node:
            candidates = [
                image_node.get("data-old-hires"),
                image_node.get("src"),
                image_node.get("data-src"),
            ]
            dynamic_images = image_node.get("data-a-dynamic-image")
            if isinstance(dynamic_images, str) and dynamic_images:
                try:
                    dynamic = json.loads(dynamic_images)
                    candidates.extend(
                        sorted(
                            dynamic.keys(),
                            key=lambda item: dynamic[item][0] * dynamic[item][1]
                            if isinstance(dynamic[item], list) and len(dynamic[item]) >= 2
                            else 0,
                            reverse=True,
                        )
                    )
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
            for candidate in candidates:
                absolute = _absolute_url(base_url, candidate)
                if absolute and _is_valid_image_url(absolute):
                    return absolute

        if product:
            schema_image = _schema_image(product)
            candidates = schema_image if isinstance(schema_image, list) else [schema_image]
            for candidate in candidates:
                absolute = _absolute_url(base_url, candidate)
                if absolute and _is_valid_image_url(absolute):
                    return absolute
        return None

    # General sites: product schema image first, then social metadata, then a
    # large image. Avoid returning obviously promotional banner URLs.
    if product:
        schema_image = _schema_image(product)
        candidates = schema_image if isinstance(schema_image, list) else [schema_image]
        for candidate in candidates:
            absolute = _absolute_url(base_url, candidate)
            if absolute and _is_valid_image_url(absolute):
                return absolute

    for key in ("og:image", "og:image:secure_url", "twitter:image", "twitter:image:src"):
        image = _absolute_url(base_url, _meta_content(soup, key))
        if image and _is_valid_image_url(image):
            return image
    return _first_large_image(soup, base_url)


def _looks_like_block_page(soup: BeautifulSoup, text: str) -> bool:
    title = _clean_text(soup.title.get_text(" ")) if soup.title else ""
    combined = f"{title} {text[:6000]}".casefold()
    indicators = (
        "robot check",
        "enter the characters you see below",
        "captcha",
        "verify you are human",
        "automated access",
        "unusual traffic",
        "access denied",
        "request blocked",
        "temporarily blocked",
        "security check",
        "enable javascript and cookies to continue",
    )
    if any(indicator in combined for indicator in indicators):
        return True
    # Common Amazon interstitial IDs without relying on page text alone.
    return bool(soup.select_one("#captchacharacters, form[action*='validateCaptcha']"))


def _extract_description(
    soup: BeautifulSoup, product: dict | None, cleaned_content: str
) -> str | None:
    if product:
        description = _clean_text(str(product.get("description", "")))
        if description:
            return description
    description = _meta_content(soup, "description", "og:description")
    if description:
        return description
    return _snippet(cleaned_content)


def _extract_cleaned_content(html: str, url: str) -> str:
    try:
        text = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            include_links=False,
            favor_recall=True,
        )
    except Exception as exc:
        logger.debug("trafilatura failed for %s: %s", url, exc)
        return ""
    return (text or "").strip()


def _fallback_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    lines = (_clean_text(line) for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)
