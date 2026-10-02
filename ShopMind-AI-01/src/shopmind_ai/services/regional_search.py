"""Regional web product search.

Uses Tavily as a search adapter rather than scraping retailer HTML directly.
This keeps the integration resilient and lets the source registry control
which shopping domains are considered trusted for a region.
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from typing import Any

import httpx
import structlog

from shopmind_ai.models import ProductResult
from shopmind_ai.services.cache import TTLCache
from shopmind_ai.services.regional_sources import (
    COUNTRY_CURRENCIES,
    RegionalSource,
    sources_for_country,
    instant_sources_for_country,
)

logger = structlog.get_logger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"


class RegionalSearch:
    """Search trusted regional shopping sources through a web-search API."""

    def __init__(
        self,
        api_key: str,
        *,
        max_results_per_source: int = 5,
    ) -> None:
        self.api_key = api_key
        self.max_results_per_source = max_results_per_source
        self.cache = TTLCache(ttl=120, max_items=250)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def search(
        self,
        query: str,
        *,
        country_code: str | None,
        display_currency: str,
        category: str | None = None,
        location_label: str = "",
        instant_only: bool = False,
    ) -> list[ProductResult]:
        if not self.enabled:
            return []

        cache_key = "|".join((query.strip().lower(), country_code or "", display_currency.upper(), category or "", location_label.lower(), str(instant_only)))
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        sources = (
            instant_sources_for_country(country_code)
            if instant_only
            else sources_for_country(country_code, category=category)
        )

        products: list[ProductResult] = []

        # Search a small number of trusted domains in parallel.
        async with httpx.AsyncClient(timeout=20.0) as client:
            tasks = [
                self._search_source(
                    client,
                    source,
                    query,
                    display_currency,
                    location_label,
                )
                for source in sources
            ]

            results = await _gather_safely(tasks)

        for result in results:
            products.extend(result)

        products = self._deduplicate(products)
        self.cache.set(cache_key, products)
        return products

    async def _search_source(
        self,
        client: httpx.AsyncClient,
        source: RegionalSource,
        query: str,
        currency: str,
        location_label: str = "",
    ) -> list[ProductResult]:
        # Do not ask the search engine to invent structured product data.
        # We only normalize what appears in the title/snippet.
        location_hint = f" near {location_label}" if location_label else ""
        delivery_hint = " fast delivery 10-30 minutes" if source.instant_delivery else ""
        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "query": f"{query}{location_hint}{delivery_hint} price rating reviews",
            "search_depth": "advanced",
            "topic": "general",
            "max_results": self.max_results_per_source,
            "include_answer": False,
            "include_raw_content": False,
            "include_domains": [source.domain],
        }

        try:
            response = await client.post(
                _TAVILY_URL,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            products: list[ProductResult] = []

            for item in data.get("results", []):
                title = str(item.get("title") or "").strip()
                url = str(item.get("url") or "").strip()
                content = str(item.get("content") or "").strip()

                if not title or not url:
                    continue

                text = f"{title} {content}"
                price, source_currency = _extract_price(text)
                rating, review_count = _extract_rating_reviews(text)

                if price is None:
                    # Never fabricate a zero price. A result without an
                    # observable price cannot safely participate in shopping
                    # recommendations.
                    continue

                source_currency = (
                    source_currency
                    or COUNTRY_CURRENCIES.get(
                        next(iter(source.countries), "US"),
                        currency,
                    )
                ).upper()

                product_id = hashlib.sha1(
                    url.encode("utf-8")
                ).hexdigest()[:16]

                products.append(
                    ProductResult(
                        product_id=f"web-{product_id}",
                        name=title,
                        description=content[:600],
                        price=float(price),
                        currency=source_currency,
                        display_price=(
                            float(price)
                            if source_currency == currency.upper()
                            else None
                        ),
                        display_currency=(
                            currency.upper()
                            if source_currency == currency.upper()
                            else None
                        ),
                        merchant_id=f"regional:{source.key}",
                        merchant_name=source.name,
                        url=url,
                        rating=rating,
                        review_count=review_count,
                        source_name=source.name,
                        source_domain=source.domain,
                        source_type="regional_search",
                        trust_score=source.trust_score,
                        score=source.trust_score,
                        verified_source=True,
                        price_confidence="observed_in_search_snippet",
                        specs={
                            **_extract_features(text),
                            "delivery_window": (
                                f"{source.delivery_minutes_min}-{source.delivery_minutes_max} min"
                                if source.instant_delivery
                                and source.delivery_minutes_min is not None
                                and source.delivery_minutes_max is not None
                                else ""
                            ),
                            "location": location_label,
                            "availability": "Source-dependent; check live stock at checkout",
                        },
                    )
                )

            logger.info(
                "regional_source_search_complete",
                source=source.name,
                domain=source.domain,
                results=len(products),
            )

            return products

        except Exception as exc:
            logger.warning(
                "regional_source_search_failed",
                source=source.name,
                domain=source.domain,
                error=str(exc),
            )
            return []

    @staticmethod
    def _deduplicate(
        products: list[ProductResult],
    ) -> list[ProductResult]:
        seen: set[str] = set()
        unique: list[ProductResult] = []

        for product in products:
            key = product.url or (
                f"{product.merchant_id}:{product.name}"
            )

            if key in seen:
                continue

            seen.add(key)
            unique.append(product)

        return unique


async def _gather_safely(tasks: list[Any]) -> list[list[ProductResult]]:
    import asyncio

    results = await asyncio.gather(
        *tasks,
        return_exceptions=True,
    )

    output: list[list[ProductResult]] = []

    for result in results:
        if isinstance(result, Exception):
            continue
        output.append(result)

    return output


def _extract_price(text: str) -> tuple[Decimal | None, str | None]:
    """Extract an explicit price and, when visible, its currency."""

    patterns = [
        (r"(?:₹|INR|Rs\.?)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", "INR"),
        (r"(?:₨|NPR)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", "NPR"),
        (r"(?:₽|RUB)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", "RUB"),
        (r"(?:\$|USD)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", "USD"),
        (r"(?:£|GBP)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", "GBP"),
        (r"(?:€|EUR)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", "EUR"),
        (r"(?:¥|JPY)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", "JPY"),
        (r"(?:C\$|CAD)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", "CAD"),
        (r"(?:A\$|AUD)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", "AUD"),
        (r"(?:AED)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", "AED"),
        (r"(?:BRL|R\$)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", "BRL"),
        (r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(INR|NPR|RUB|USD|GBP|EUR|JPY|CAD|AUD|AED|BRL)", None),
    ]

    for pattern, detected_currency in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        try:
            value = Decimal(match.group(1).replace(",", ""))
        except Exception:
            continue
        if value <= 0:
            continue
        return value, detected_currency or match.group(2).upper()

    return None, None


def _extract_features(text: str) -> dict[str, str]:
    """Extract common buyer-facing features from search text without inventing them."""
    lower = text.lower()
    features: dict[str, str] = {}
    checks = [
        ("ANC", r"\b(?:anc|active noise cancellation)\b"),
        ("Battery", r"\b([0-9]{1,3})\s*(?:hours?|hrs?)\b"),
        ("Bluetooth", r"\bbluetooth(?:\s*[0-9.]+)?\b"),
        ("Water resistance", r"\b(?:ipx[0-9]+|ip[0-9]{2})\b"),
        ("Fast charging", r"\bfast charging\b"),
        ("Wireless", r"\bwireless\b"),
        ("Warranty", r"\b([0-9]{1,2})\s*(?:year|yr)\s*warranty\b"),
    ]
    for label, pattern in checks:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        if label == "Battery":
            features[label] = f"{match.group(1)}h"
        elif label == "Warranty":
            features[label] = f"{match.group(1)} year"
        elif label == "Water resistance":
            features[label] = match.group(0).upper()
        else:
            features[label] = match.group(0)
    return {k: v for k, v in features.items() if v}


def _extract_rating_reviews(text: str) -> tuple[float, int]:
    rating = 0.0
    review_count = 0

    rating_match = re.search(
        r"\b([0-5](?:\.[0-9])?)\s*(?:/5|out of 5|stars?)\b",
        text,
        re.IGNORECASE,
    )

    if rating_match:
        rating = float(rating_match.group(1))

    review_match = re.search(
        r"([0-9][0-9,]*(?:\.[0-9]+)?\s*[kKmM]?)\s*(?:reviews?|ratings?)\b",
        text,
        re.IGNORECASE,
    )

    if review_match:
        raw = review_match.group(1).replace(",", "").replace(" ", "")
        multiplier = 1

        if raw.lower().endswith("k"):
            multiplier = 1_000
            raw = raw[:-1]
        elif raw.lower().endswith("m"):
            multiplier = 1_000_000
            raw = raw[:-1]

        try:
            review_count = int(float(raw) * multiplier)
        except ValueError:
            review_count = 0

    return rating, review_count
