"""Product search specialist agent.

Executes parallel searches across all discovered merchants, normalises
results, and keeps both budget-eligible and closest-match products so the
caller can explain when no exact budget match exists.
"""

from __future__ import annotations

import asyncio
import re
from decimal import Decimal
from typing import Any

import structlog

from shopmind_ai.config import Settings
from shopmind_ai.models import MerchantInfo, ProductResult, ShoppingRequest
from shopmind_ai.services.regional_search import RegionalSearch
from shopmind_ai.protocols.ucp_client import UCPClient, UCPClientError

logger = structlog.get_logger(__name__)


class SearchAgent:
    """Search products across multiple UCP merchants."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ucp_client = UCPClient(timeout=settings.comparison_timeout)
        self._regional_search = RegionalSearch(
            settings.tavily_api_key,
            max_results_per_source=5,
        )

    async def search_all_merchants(
        self,
        merchants: list[MerchantInfo],
        queries: list[str],
        filters: dict[str, Any] | None = None,
        request: ShoppingRequest | None = None,
    ) -> dict[str, list[ProductResult]]:
        """Search all merchants in parallel.

        Price/budget filtering is deliberately NOT performed here. Merchant
        prices can be in different currencies, while the user's budget is in
        the display currency. Currency conversion is performed by the
        regional-pricing layer after search.
        """

        tasks: list[asyncio.Task[tuple[str, list[ProductResult]]]] = []

        for merchant in merchants:
            for query in queries:
                task = asyncio.create_task(
                    self._search_one_merchant(
                        merchant,
                        query,
                        filters=filters,
                    )
                )
                tasks.append(task)

        if not tasks:
            return {}

        results = await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        merchant_results: dict[str, list[ProductResult]] = {}

        for result in results:
            if isinstance(result, Exception):
                logger.warning(
                    "search_task_failed",
                    error=str(result),
                )
                continue

            merchant_id, products = result
            merchant_results.setdefault(
                merchant_id,
                [],
            ).extend(products)

        # Deduplicate + relevance filtering.
        for merchant_id in merchant_results:
            products = self._deduplicate(
                merchant_results[merchant_id]
            )

            filtered_products = [
                product
                for product in products
                if any(
                    self._is_relevant_product(product, query)
                    for query in queries
                )
            ]

            merchant_results[merchant_id] = filtered_products

        # Regional web search is additive for normal searches. For an explicit
        # instant-delivery request, regional quick-commerce sources become the
        # authoritative result pool so ordinary UCP offers are never mislabeled
        # as 10-30 minute delivery.
        if request is not None and request.instant_delivery_requested:
            merchant_results = {}

        if request is not None and self._regional_search.enabled:
            regional_tasks = [
                self._regional_search.search(
                    query,
                    country_code=request.country_code,
                    display_currency=request.display_currency,
                    location_label=request.location_label,
                    instant_only=(
                        request.country_code == "IN"
                        and request.instant_delivery_requested
                    ),
                )
                for query in queries
            ]

            regional_batches = await asyncio.gather(
                *regional_tasks,
                return_exceptions=True,
            )

            regional_products: list[ProductResult] = []
            for batch in regional_batches:
                if isinstance(batch, Exception):
                    logger.warning(
                        "regional_search_task_failed",
                        error=str(batch),
                    )
                    continue
                regional_products.extend(batch)

            if regional_products:
                regional_products = self._deduplicate(regional_products)

                # When the user explicitly asks for instant delivery, do not
                # present ordinary 1-7 day UCP offers as if they were instant.
                # Keep them only as a fallback when no instant source returned
                # a product.
                if request.instant_delivery_requested:
                    merchant_results = {
                        "__regional_instant__": regional_products,
                    }
                else:
                    merchant_results.setdefault(
                        "__regional__",
                        [],
                    ).extend(regional_products)

                logger.info(
                    "regional_search_complete",
                    country=request.country_code,
                    currency=request.display_currency,
                    location=request.location_label,
                    instant=request.instant_delivery_requested,
                    products=len(regional_products),
                )

        logger.info(
            "search_complete",
            merchants=len(merchant_results),
            total_products=sum(
                len(products)
                for products in merchant_results.values()
            ),
        )

        return merchant_results

    async def _search_one_merchant(
        self,
        merchant: MerchantInfo,
        query: str,
        filters: dict[str, Any] | None = None,
    ) -> tuple[str, list[ProductResult]]:
        """Search one merchant for one query."""

        try:
            products = await self._ucp_client.search_products(
                merchant.url,
                query,
                filters=filters,
                limit=self._settings.max_results_per_merchant,
            )

            for product in products:
                if not product.merchant_id:
                    product.merchant_id = merchant.id

                if not product.merchant_name:
                    product.merchant_name = merchant.name

            logger.debug(
                "merchant_search_complete",
                merchant=merchant.name,
                query=query,
                results=len(products),
            )

            return merchant.id, products

        except UCPClientError as exc:
            logger.warning(
                "merchant_search_failed",
                merchant=merchant.name,
                query=query,
                error=str(exc),
            )
            return merchant.id, []

    # ---------------------------------------------------------
    # Budget helpers
    # ---------------------------------------------------------

    @staticmethod
    def extract_budget(query: str) -> Decimal | None:
        """Extract a numeric budget from common shopping language."""

        if not query:
            return None

        text = (
            query
            .replace("₹", " INR ")
            .replace("â‚¹", " INR ")
            .replace("$", " USD ")
            .replace("€", " EUR ")
            .replace("£", " GBP ")
            .replace("₽", " RUB ")
        )

        match = re.search(
            r"\b(?:under|below|budget|max|upto|up\s+to)"
            r"\s*(?:inr|rs\.?|rupees?|usd|dollars?|"
            r"eur|euros?|gbp|pounds?|rub|rubles?|npr)?"
            r"\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)",
            text,
            re.IGNORECASE,
        )

        if match:
            try:
                return Decimal(
                    match.group(1).replace(",", "")
                )
            except Exception:
                return None

        return None

    @staticmethod
    def filter_by_local_budget(
        products: list[ProductResult],
        budget: Decimal | float | int | None,
    ) -> tuple[list[ProductResult], list[ProductResult]]:
        """Split products into eligible and over-budget lists.

        This helper expects ``product.price`` to already be in the user's
        local/display currency. It never invents or changes a product price.
        """

        if budget is None:
            return list(products), []

        budget_decimal = Decimal(str(budget))

        eligible: list[ProductResult] = []
        over_budget: list[ProductResult] = []

        for product in products:
            try:
                price = Decimal(str(product.price))
            except Exception:
                over_budget.append(product)
                continue

            # A zero price from a web snippet means "price not detected",
            # not a free product. Never let it pass a budget filter.
            if price > 0 and price <= budget_decimal:
                eligible.append(product)
            else:
                over_budget.append(product)

        return eligible, over_budget

    # ---------------------------------------------------------
    # Relevance filtering
    # ---------------------------------------------------------

    @staticmethod
    def _normalise(text: str) -> set[str]:
        """Convert text into useful lowercase tokens."""

        text = (text or "").lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)

        stop_words = {
            "the",
            "and",
            "for",
            "with",
            "under",
            "below",
            "budget",
            "max",
            "upto",
            "up",
            "to",
            "best",
            "good",
            "need",
            "want",
            "buy",
            "please",
            "rs",
            "inr",
            "usd",
            "eur",
            "gbp",
            "rub",
            "npr",
        }

        return {
            word
            for word in text.split()
            if len(word) >= 3
            and word not in stop_words
            and not word.isdigit()
        }

    @classmethod
    def _is_relevant_product(
        cls,
        product: ProductResult,
        query: str,
    ) -> bool:
        """Check whether a product is genuinely relevant."""

        query_tokens = cls._normalise(query)

        product_text = " ".join(
            [
                product.name,
                product.description,
                product.category,
                product.brand,
                " ".join(
                    f"{key} {value}"
                    for key, value in product.specs.items()
                ),
            ]
        )

        product_tokens = cls._normalise(product_text)

        if not query_tokens or not product_tokens:
            return False

        category_groups = [
            {
                "earbud",
                "earbuds",
                "tws",
                "headphone",
                "headphones",
                "earphone",
                "earphones",
            },
            {
                "laptop",
                "notebook",
                "macbook",
                "chromebook",
            },
            {
                "phone",
                "smartphone",
                "mobile",
                "iphone",
                "android",
            },
            {
                "tablet",
                "ipad",
            },
            {
                "keyboard",
                "mouse",
                "monitor",
                "speaker",
                "camera",
                "watch",
            },
        ]

        for group in category_groups:
            query_has_group = bool(query_tokens & group)
            product_has_group = bool(product_tokens & group)

            if query_has_group and not product_has_group:
                return False

        overlap = query_tokens & product_tokens

        meaningful_query_tokens = {
            token
            for token in query_tokens
            if token not in {
                "wireless",
                "good",
                "battery",
                "life",
                "best",
            }
        }

        if meaningful_query_tokens:
            meaningful_overlap = (
                meaningful_query_tokens & product_tokens
            )

            if not meaningful_overlap:
                return False

        return len(overlap) >= 1

    # ---------------------------------------------------------
    # Deduplication
    # ---------------------------------------------------------

    @staticmethod
    def _deduplicate(
        products: list[ProductResult],
    ) -> list[ProductResult]:
        seen: set[str] = set()
        unique: list[ProductResult] = []

        for product in products:
            key = (
                f"{product.merchant_id}:"
                f"{product.product_id}"
            )

            if key not in seen:
                seen.add(key)
                unique.append(product)

        return unique

    async def close(self) -> None:
        """Close HTTP client."""

        await self._ucp_client.close()