"""
Product extraction service.

Fetches a product page and converts it into a standardized dictionary of raw
product data. This is the first stage of the ANSME pipeline:

    Raw Data -> Feature Engineering -> Scoring -> Verdict -> LLM Explainability

This module only collects raw data. It performs no scoring, no verdicts and
no LLM calls, and has no database or FastAPI dependencies.

Dependencies:
    pip install httpx beautifulsoup4 trafilatura lxml
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

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=8.0)
MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2 MB hard cap on downloaded HTML
MIN_IMAGE_DIMENSION = 200  # px, used for the "first large image" fallback
DESCRIPTION_SNIPPET_CHARS = 300

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

# Currency symbol before the number: "₹1,29,999", "$ 19.99", "Rs. 499", "INR 1200"
_PRICE_PREFIX_RE = re.compile(
    r"(?:₹|Rs\.?|INR|US\$|\$|USD|€|EUR|£|GBP)\s*(\d[\d.,]*)", re.IGNORECASE
)
# Currency symbol after the number: "19,99 €"
_PRICE_SUFFIX_RE = re.compile(r"(\d[\d.,]*)\s*(?:€|EUR)", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d[\d.,]*")

# Price containers that usually hold struck-through / non-selling prices.
_STALE_PRICE_RE = re.compile(
    r"(old|was|original|mrp|strike|list|compare|regular|crossed|discount|saving|save)",
    re.IGNORECASE,
)
_SKIP_IMAGE_RE = re.compile(
    r"(logo|icon|sprite|pixel|avatar|badge|placeholder|spinner|loading|blank)",
    re.IGNORECASE,
)
_PRODUCT_TYPES = {"product", "productgroup", "individualproduct"}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


async def extract_product_data(url: str) -> dict[str, Any]:
    """
    Fetch ``url`` and extract standardized product data.

    Returns on success::

        {
            "url": str,
            "title": str,
            "brand": str | None,
            "price": float | None,
            "rating": float | None,
            "image_url": str | None,
            "description": str | None,
            "cleaned_content": str,
            "status": "success",
        }

    Returns on failure (never raises)::

        {"url": url, "status": "error", "error": str}
    """
    try:
        target = _normalize_url(url)
        html, final_url = await _fetch_html(target)

        # BeautifulSoup + trafilatura are CPU-bound; keep them off the event loop.
        parsed = await asyncio.to_thread(_parse_product_page, html, final_url)

        return {
            "url": url,
            "title": parsed["title"],
            "brand": parsed["brand"],
            "price": parsed["price"],
            "rating": parsed["rating"],
            "image_url": parsed["image_url"],
            "description": parsed["description"],
            "cleaned_content": parsed["cleaned_content"],
            "status": "success",
        }
    except Exception as exc:  # noqa: BLE001 - contract: never crash the caller
        logger.warning("Product extraction failed for %s: %s", url, exc, exc_info=True)
        return {
            "url": url,
            "status": "error",
            "error": str(exc) or exc.__class__.__name__,
        }


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #


def _normalize_url(url: str) -> str:
    """Trim the URL and default to https:// when no scheme is given."""
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
    return cleaned


async def _assert_public_host(request: httpx.Request) -> None:
    """
    SSRF guard, run for the initial request and for every redirect hop.

    Rejects URLs that resolve to loopback, private, link-local or otherwise
    non-public addresses.
    """
    host = request.url.host
    port = request.url.port or (443 if request.url.scheme == "https" else 80)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host: {host}") from exc

    for info in infos:
        address = info[4][0].split("%")[0]  # strip IPv6 zone id
        if not ipaddress.ip_address(address).is_global:
            raise ValueError("Refusing to fetch a non-public address")


async def _fetch_html(url: str) -> tuple[str, str]:
    """Download the page and return ``(html, final_url)`` after redirects."""
    async with httpx.AsyncClient(
        headers=BROWSER_HEADERS,
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        event_hooks={"request": [_assert_public_host]},
    ) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()

            content_type = response.headers.get("content-type", "").lower()
            if content_type and not any(
                t in content_type for t in ("html", "xml", "text/plain")
            ):
                raise ValueError(f"Unsupported content type: {content_type}")

            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) >= MAX_RESPONSE_BYTES:
                    body = body[:MAX_RESPONSE_BYTES]
                    break

            html = _decode_body(bytes(body), response.charset_encoding)
            return html, str(response.url)


def _decode_body(body: bytes, header_charset: str | None) -> str:
    """Decode bytes using the header charset, a <meta charset>, or UTF-8."""
    encoding = header_charset
    if not encoding:
        match = re.search(rb"charset=[\"']?([\w-]+)", body[:4096], re.IGNORECASE)
        encoding = match.group(1).decode("ascii", "ignore") if match else "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Parsing orchestration
# --------------------------------------------------------------------------- #


def _parse_product_page(html: str, base_url: str) -> dict[str, Any]:
    """Synchronous parse step; executed in a worker thread."""
    soup = BeautifulSoup(html, "lxml")
    product = _find_schema_product(soup)

    cleaned_content = _extract_cleaned_content(html, base_url)
    if not cleaned_content:
        cleaned_content = _fallback_text(html)

    return {
        "title": _extract_title(soup),
        "brand": _extract_brand(soup, product),
        "price": _extract_price(soup, product, cleaned_content),
        "rating": _extract_rating(soup, product),
        "image_url": _extract_image(soup, product, base_url),
        "description": _extract_description(soup, product, cleaned_content),
        "cleaned_content": cleaned_content,
    }


# --------------------------------------------------------------------------- #
# Generic helpers
# --------------------------------------------------------------------------- #


def _clean_text(value: Any) -> str:
    """Collapse whitespace; return '' for non-strings."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _meta_content(soup: BeautifulSoup, *keys: str) -> str | None:
    """Return the first non-empty meta content matching property/name/itemprop."""
    for key in keys:
        for attr in ("property", "name", "itemprop"):
            tag = soup.find("meta", attrs={attr: key})
            if tag:
                content = _clean_text(tag.get("content"))
                if content:
                    return content
    return None


def _absolute_url(base_url: str, candidate: str | None) -> str | None:
    """Resolve ``candidate`` against ``base_url``; only http(s) URLs are kept."""
    if not candidate or not isinstance(candidate, str):
        return None
    candidate = candidate.strip()
    if not candidate or candidate.startswith("data:"):
        return None
    absolute = urljoin(base_url, candidate)
    return absolute if urlparse(absolute).scheme in ("http", "https") else None


def _snippet(text: str, limit: int = DESCRIPTION_SNIPPET_CHARS) -> str | None:
    """Return the start of ``text`` trimmed to ``limit`` chars on a word boundary."""
    text = _clean_text(text)
    if not text:
        return None
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:- ")
    return f"{cut}..."


# --------------------------------------------------------------------------- #
# JSON-LD / schema.org Product
# --------------------------------------------------------------------------- #


def _iter_nodes(node: Any) -> Iterator[dict]:
    """Yield every dict nested anywhere inside a JSON-LD document."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _iter_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_nodes(item)


def _is_product_node(node: dict) -> bool:
    node_type = node.get("@type")
    types = node_type if isinstance(node_type, list) else [node_type]
    return any(isinstance(t, str) and t.lower() in _PRODUCT_TYPES for t in types)


def _find_schema_product(soup: BeautifulSoup) -> dict | None:
    """Return the first schema.org Product found in JSON-LD blocks, if any."""
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        for node in _iter_nodes(data):
            if _is_product_node(node):
                return node
    return None


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


def _schema_image(product: dict) -> str | None:
    value = product.get("image")
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("url") or value.get("contentUrl")
    return value if isinstance(value, str) and value.strip() else None


def _schema_price(product: dict) -> float | None:
    offers = product.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return None

    for offer in offers:
        if not isinstance(offer, dict):
            continue
        candidates: list[Any] = [offer.get("price"), offer.get("lowPrice")]

        spec = offer.get("priceSpecification")
        for item in spec if isinstance(spec, list) else [spec]:
            if isinstance(item, dict):
                candidates.append(item.get("price"))

        nested = offer.get("offers")  # AggregateOffer
        if nested:
            price = _schema_price({"offers": nested})
            if price is not None:
                return price

        for candidate in candidates:
            price = _to_price(candidate)
            if price is not None:
                return price
    return None


def _schema_rating(product: dict) -> float | None:
    """Extract ratingValue from aggregateRating in schema.org Product JSON-LD."""
    agg = product.get("aggregateRating")
    if isinstance(agg, dict):
        rating_val = agg.get("ratingValue")
        return _to_rating(rating_val)
    return None


# --------------------------------------------------------------------------- #
# Title
# --------------------------------------------------------------------------- #


def _extract_title(soup: BeautifulSoup) -> str:
    """Priority: <h1> -> og:title -> <title>."""
    h1 = soup.find("h1")
    if h1:
        text = _clean_text(h1.get_text(" "))
        if text:
            return text

    og_title = _meta_content(soup, "og:title")
    if og_title:
        return og_title

    if soup.title and soup.title.string:
        text = _clean_text(soup.title.string)
        if text:
            return text
    return ""


# --------------------------------------------------------------------------- #
# Brand
# --------------------------------------------------------------------------- #


def _extract_brand(soup: BeautifulSoup, product: dict | None) -> str | None:
    """Priority: schema.org Product -> meta tags -> microdata -> None."""
    if product:
        brand = _schema_brand(product)
        if brand:
            return brand

    brand = _meta_content(
        soup, "product:brand", "og:brand", "brand", "twitter:brand"
    )
    if brand:
        return brand

    # Microdata: <span itemprop="brand">Acme</span> (or nested itemprop="name")
    node = soup.find(attrs={"itemprop": "brand"})
    if node:
        inner = node.find(attrs={"itemprop": "name"})
        text = _clean_text((inner or node).get("content") or (inner or node).get_text(" "))
        if text:
            return text
    return None


# --------------------------------------------------------------------------- #
# Price
# --------------------------------------------------------------------------- #


def _parse_price_string(raw: str) -> float | None:
    """
    Convert a numeric string to a float, handling regional separators:

        "1,29,999.00" (Indian) -> 129999.0
        "1,299.99"    (US)     -> 1299.99
        "1.299,99"    (EU)     -> 1299.99
        "12,50"                -> 12.5
    """
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
            re.fullmatch(r"\d{1,3}(,\d{3})+", token)  # 1,299 / 12,500
            or re.fullmatch(r"\d{1,2}(,\d{2})+,\d{3}", token)  # 1,29,999
        )
        token = token.replace(",", "") if is_thousands else token.replace(",", ".")
    elif has_dot and token.count(".") > 1:
        token = token.replace(".", "")  # 1.299.000

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


def _price_from_text(text: str) -> float | None:
    """Find the first currency-tagged amount (₹ $ € £) in free text."""
    match = _PRICE_PREFIX_RE.search(text or "") or _PRICE_SUFFIX_RE.search(text or "")
    return _parse_price_string(match.group(1)) if match else None


def _is_stale_price_element(element: Any) -> bool:
    if element.name in ("del", "s", "strike") or element.find_parent(
        ["del", "s", "strike"]
    ):
        return True
    classes = " ".join(element.get("class") or [])
    return bool(_STALE_PRICE_RE.search(f"{classes} {element.get('id') or ''}"))


def _extract_price(
    soup: BeautifulSoup, product: dict | None, cleaned_content: str
) -> float | None:
    """
    Priority: schema.org offers -> price meta tags -> itemprop="price"
    -> price-like elements -> first currency amount in page text.
    """
    if product:
        price = _schema_price(product)
        if price is not None:
            return price

    meta_price = _meta_content(
        soup, "product:price:amount", "og:price:amount", "product:sale_price:amount"
    )
    if meta_price:
        price = _parse_price_string(meta_price)
        if price is not None:
            return price

    for node in soup.select('[itemprop="price"]'):
        raw = node.get("content") or node.get("value") or node.get_text(" ")
        price = _parse_price_string(raw)
        if price is not None:
            return price

    for node in soup.select('[class*="price" i], [id*="price" i]')[:40]:
        if _is_stale_price_element(node):
            continue
        price = _price_from_text(node.get_text(" "))
        if price is not None:
            return price

    return _price_from_text(cleaned_content[:20000])


# --------------------------------------------------------------------------- #
# Rating
# --------------------------------------------------------------------------- #


def _to_rating(value: Any) -> float | None:
    """Convert raw value to float bounded within a 0.0 to 5.0 scale."""
    if value is None or isinstance(value, bool):
        return None
    try:
        val = float(str(value).strip())
        if 0.0 <= val <= 5.0:
            return round(val, 2)
        if 5.0 < val <= 10.0:  # Normalize 10-point scales to 5-point
            return round(val / 2.0, 2)
        if 10.0 < val <= 100.0:  # Normalize percentage scales
            return round((val / 100.0) * 5.0, 2)
    except (ValueError, TypeError):
        pass
    return None


def _extract_rating(soup: BeautifulSoup, product: dict | None) -> float | None:
    """
    Priority: schema.org aggregateRating -> meta tags -> itemprop="ratingValue"
    -> rating text elements.
    """
    if product:
        rating = _schema_rating(product)
        if rating is not None:
            return rating

    meta_rating = _meta_content(
        soup, "og:rating", "twitter:rating", "product:rating:value"
    )
    if meta_rating:
        rating = _to_rating(meta_rating)
        if rating is not None:
            return rating

    for node in soup.select('[itemprop="ratingValue"]'):
        raw = node.get("content") or node.get_text(" ")
        rating = _to_rating(raw)
        if rating is not None:
            return rating

    # Pattern search in elements containing rating indicators
    for node in soup.select('[class*="rating" i], [id*="rating" i]')[:20]:
        text = node.get_text(" ")
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:out of|\/)\s*5", text, re.IGNORECASE)
        if match:
            rating = _to_rating(match.group(1))
            if rating is not None:
                return rating

    return None


# --------------------------------------------------------------------------- #
# Image
# --------------------------------------------------------------------------- #


def _dimension(value: Any) -> int | None:
    match = re.match(r"\s*(\d+)", str(value)) if value is not None else None
    return int(match.group(1)) if match else None


def _first_large_image(soup: BeautifulSoup, base_url: str) -> str | None:
    """
    Return the first <img> that looks like a real product image.

    Images with declared dimensions must be at least MIN_IMAGE_DIMENSION px.
    Images with no declared size are only used if nothing better is found.
    """
    unsized_fallback: str | None = None

    for img in soup.find_all("img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-original")
        )
        if not src or _SKIP_IMAGE_RE.search(src):
            continue
        if src.lower().split("?")[0].endswith((".svg", ".gif")):
            continue

        absolute = _absolute_url(base_url, src)
        if not absolute:
            continue

        dims = [d for d in (_dimension(img.get("width")), _dimension(img.get("height"))) if d]
        if dims:
            if min(dims) >= MIN_IMAGE_DIMENSION:
                return absolute
            continue
        unsized_fallback = unsized_fallback or absolute

    return unsized_fallback


def _extract_image(
    soup: BeautifulSoup, product: dict | None, base_url: str
) -> str | None:
    """Priority: og:image -> twitter:image -> first large image -> schema image."""
    for key in ("og:image", "og:image:secure_url", "twitter:image", "twitter:image:src"):
        image = _absolute_url(base_url, _meta_content(soup, key))
        if image:
            return image

    image = _first_large_image(soup, base_url)
    if image:
        return image

    if product:
        return _absolute_url(base_url, _schema_image(product))
    return None


# --------------------------------------------------------------------------- #
# Description & content
# --------------------------------------------------------------------------- #


def _extract_description(
    soup: BeautifulSoup, product: dict | None, cleaned_content: str
) -> str | None:
    """Priority: meta description -> og:description -> cleaned content snippet."""
    description = _meta_content(soup, "description") or _meta_content(
        soup, "og:description"
    )
    if description:
        return description

    if product:
        schema_description = _clean_text(product.get("description"))
        if schema_description:
            return schema_description

    return _snippet(cleaned_content)


def _extract_cleaned_content(html: str, url: str) -> str:
    """Readable main-content text via trafilatura ('' if nothing is found)."""
    try:
        text = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            include_links=False,
            favor_recall=True,
        )
    except Exception as exc:  # noqa: BLE001 - trafilatura failure must not abort
        logger.debug("trafilatura failed for %s: %s", url, exc)
        return ""
    return (text or "").strip()


def _fallback_text(html: str) -> str:
    """Plain visible text, used only when trafilatura returns nothing."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    lines = (_clean_text(line) for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)