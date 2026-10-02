"""Price comparison specialist agent.

Builds a comparison matrix that scores products across merchants on:
- price
- shipping cost
- delivery speed
- stock availability
- product relevance
- requested features

Supports both:
- shopping_items: structured ShoppingPlanItem input
- item_names: legacy input used by existing tests
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import structlog

from shopmind_ai.models import (
    ComparisonEntry,
    ComparisonMatrix,
    ProductResult,
    ShoppingPlanItem,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------

_WEIGHT_RELEVANCE = 0.35
_WEIGHT_PRICE = 0.30
_WEIGHT_SHIPPING = 0.15
_WEIGHT_AVAILABILITY = 0.10
_WEIGHT_DELIVERY = 0.10


class ComparisonAgent:
    """Builds and scores a product comparison matrix."""

    async def build_comparison(
        self,
        search_results: dict[str, list[ProductResult]],
        shopping_items: list[ShoppingPlanItem] | None = None,
        item_names: list[str] | None = None,
    ) -> ComparisonMatrix:
        """Create a comparison matrix for requested shopping items.

        Parameters
        ----------
        search_results:
            Mapping of merchant ID to product results.

        shopping_items:
            Preferred structured shopping plan items.

        item_names:
            Legacy list of item names. Kept for backward compatibility.
        """

        # ------------------------------------------------------------------
        # Backward compatibility
        # ------------------------------------------------------------------

        if shopping_items is None:
            shopping_items = [
                ShoppingPlanItem(name=name)
                for name in (item_names or [])
            ]

        # ------------------------------------------------------------------
        # Flatten products from all merchants
        # ------------------------------------------------------------------

        all_products: list[ProductResult] = []

        for products in search_results.values():
            all_products.extend(products)

        entries: list[ComparisonEntry] = []

        # ------------------------------------------------------------------
        # Compare every requested item
        # ------------------------------------------------------------------

        for item in shopping_items:
            item_name = item.name

            matching = self._find_matching_products(
                all_products,
                item,
            )

            if not matching:
                entries.append(
                    ComparisonEntry(
                        product_query=item_name,
                        merchant_results=[],
                    )
                )
                continue

            # Score products
            scored = self._score_products(
                matching,
                item,
            )

            # Highest score first
            scored.sort(
                key=lambda product: product.score,
                reverse=True,
            )

            # Best price
            best_price = min(
                scored,
                key=lambda product: product.price,
            )

            # Best shipping
            best_shipping = min(
                scored,
                key=self._cheapest_shipping,
            )

            # Overall recommendation
            recommended = scored[0]

            entries.append(
                ComparisonEntry(
                    product_query=item_name,
                    merchant_results=scored,
                    best_price=best_price,
                    best_shipping=best_shipping,
                    recommended=recommended,
                )
            )

        # ------------------------------------------------------------------
        # Matrix statistics
        # ------------------------------------------------------------------

        total_products = sum(
            len(entry.merchant_results)
            for entry in entries
        )

        merchant_ids: set[str] = set()

        for entry in entries:
            for result in entry.merchant_results:
                merchant_ids.add(result.merchant_id)

        matrix = ComparisonMatrix(
            entries=entries,
            total_merchants=len(merchant_ids),
            total_products_found=total_products,
            generated_at=datetime.now(tz=timezone.utc),
        )

        logger.info(
            "comparison_built",
            items=len(entries),
            total_products=total_products,
            merchants=len(merchant_ids),
        )

        return matrix

    # ------------------------------------------------------------------
    # Tokenization
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Convert text into normalized tokens."""

        return {
            token
            for token in re.findall(
                r"[a-z0-9]+",
                text.lower(),
            )
            if len(token) > 2
        }

    # ------------------------------------------------------------------
    # Product matching
    # ------------------------------------------------------------------

    @classmethod
    def _find_matching_products(
        cls,
        products: list[ProductResult],
        item: ShoppingPlanItem,
    ) -> list[ProductResult]:
        """Find products relevant to a shopping-plan item.

        Uses category aliases, budget filtering, feature matching,
        and keyword relevance.
        """

        requested_text = " ".join(
            [
                item.name,
                *item.keywords,
            ]
        ).lower()

        requested_tokens = cls._tokenize(
            requested_text
        )

        matching: list[ProductResult] = []

        # --------------------------------------------------------------
        # Category aliases
        # --------------------------------------------------------------

        category_aliases = {
            "earbuds": {
                "earbud",
                "earbuds",
                "buds",
                "tws",
                "earphone",
                "earphones",
            },
            "headphones": {
                "headphone",
                "headphones",
                "headset",
            },
            "laptop": {
                "laptop",
                "notebook",
                "macbook",
                "chromebook",
            },
            "phone": {
                "phone",
                "smartphone",
                "mobile",
                "iphone",
                "android",
            },
            "tablet": {
                "tablet",
                "ipad",
            },
            "keyboard": {
                "keyboard",
                "keyboards",
            },
            "mouse": {
                "mouse",
                "mice",
            },
            "monitor": {
                "monitor",
                "display",
                "screen",
            },
            "camera": {
                "camera",
                "cameras",
                "dslr",
                "mirrorless",
            },
            "speaker": {
                "speaker",
                "speakers",
                "soundbar",
            },
        }

        # --------------------------------------------------------------
        # Detect requested category
        # --------------------------------------------------------------

        requested_category: str | None = None

        for category, aliases in category_aliases.items():
            if any(
                alias in requested_tokens
                for alias in aliases
            ):
                requested_category = category
                break

        # --------------------------------------------------------------
        # Generic words
        # --------------------------------------------------------------

        generic_tokens = {
            "wireless",
            "bluetooth",
            "portable",
            "active",
            "noise",
            "cancellation",
            "cancelling",
            "long",
            "good",
            "battery",
            "life",
            "anc",
            "best",
            "under",
            "with",
        }

        # --------------------------------------------------------------
        # Evaluate products
        # --------------------------------------------------------------

        for product in products:

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
            ).lower()

            product_tokens = cls._tokenize(
                product_text
            )

            # ----------------------------------------------------------
            # 1. Category validation
            # ----------------------------------------------------------

            if requested_category is not None:

                aliases = category_aliases[
                    requested_category
                ]

                category_match = any(
                    alias in product_text
                    for alias in aliases
                )

                if not category_match:
                    continue

            # ----------------------------------------------------------
            # 2. Earbud-specific validation
            # ----------------------------------------------------------

            if requested_category == "earbuds":

                is_earbud = (
                    "earbud" in product_text
                    or "earbuds" in product_text
                    or "tws" in product_text
                    or "buds" in product_text
                    or product.category.lower()
                    in {
                        "earbuds",
                        "earphones",
                    }
                )

                if not is_earbud:
                    continue

            # ----------------------------------------------------------
            # 3. Headphone-specific validation
            # ----------------------------------------------------------

            if requested_category == "headphones":

                if not any(
                    word in product_text
                    for word in (
                        "headphone",
                        "headphones",
                        "headset",
                    )
                ):
                    continue

            # ----------------------------------------------------------
            # 4. Laptop-specific validation
            # ----------------------------------------------------------

            if requested_category == "laptop":

                if not any(
                    word in product_text
                    for word in (
                        "laptop",
                        "notebook",
                        "macbook",
                        "chromebook",
                    )
                ):
                    continue

            # ----------------------------------------------------------
            # 5. Phone-specific validation
            # ----------------------------------------------------------

            if requested_category == "phone":

                if not any(
                    word in product_text
                    for word in (
                        "phone",
                        "smartphone",
                        "mobile",
                        "iphone",
                        "android",
                    )
                ):
                    continue

            # ----------------------------------------------------------
            # 6. Tablet-specific validation
            # ----------------------------------------------------------

            if requested_category == "tablet":

                if not any(
                    word in product_text
                    for word in (
                        "tablet",
                        "ipad",
                    )
                ):
                    continue

            # ----------------------------------------------------------
            # 7. Budget validation
            # ----------------------------------------------------------

            if item.budget is not None:

                budget = float(item.budget)

                if product.price > budget:
                    continue

            # ----------------------------------------------------------
            # 8. Feature validation
            # ----------------------------------------------------------

            if item.features:

                feature_matches = 0

                for feature in item.features:

                    feature_lower = feature.lower().strip()

                    # --------------------------------------------------
                    # ANC
                    # --------------------------------------------------

                    if feature_lower in {
                        "anc",
                        "active noise cancellation",
                    }:

                        if any(
                            term in product_text
                            for term in (
                                "anc",
                                "active noise cancellation",
                                "noise cancelling",
                                "noise cancellation",
                                "noise-cancelling",
                            )
                        ):
                            feature_matches += 1

                        continue

                    # --------------------------------------------------
                    # Battery
                    # --------------------------------------------------

                    if "battery" in feature_lower:

                        if any(
                            term in product_text
                            for term in (
                                "battery",
                                "hour",
                                "hours",
                                "mah",
                            )
                        ):
                            feature_matches += 1

                        continue

                    # --------------------------------------------------
                    # Bluetooth
                    # --------------------------------------------------

                    if "bluetooth" in feature_lower:

                        if "bluetooth" in product_text:
                            feature_matches += 1

                        continue

                    # --------------------------------------------------
                    # Wireless
                    # --------------------------------------------------

                    if "wireless" in feature_lower:

                        if (
                            "wireless" in product_text
                            or "bluetooth" in product_text
                            or requested_category
                            in {
                                "earbuds",
                                "headphones",
                            }
                        ):
                            feature_matches += 1

                        continue

                    # --------------------------------------------------
                    # Generic feature matching
                    # --------------------------------------------------

                    feature_tokens = cls._tokenize(
                        feature_lower
                    )

                    if (
                        feature_tokens
                        and feature_tokens.intersection(
                            product_tokens
                        )
                    ):
                        feature_matches += 1

                # At least one requested feature must match.
                if feature_matches == 0:
                    continue

            # ----------------------------------------------------------
            # 9. Keyword relevance
            # ----------------------------------------------------------

            meaningful_tokens = (
                requested_tokens - generic_tokens
            )

            if meaningful_tokens:

                keyword_overlap = (
                    meaningful_tokens
                    & product_tokens
                )

                # Category aliases are considered strong matches.
                category_words: set[str] = set()

                if requested_category is not None:
                    category_words = category_aliases[
                        requested_category
                    ]

                category_overlap = (
                    keyword_overlap
                    & category_words
                )

                if (
                    not keyword_overlap
                    and not category_overlap
                ):
                    continue

            matching.append(product)

        return matching

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_products(
        self,
        products: list[ProductResult],
        item: ShoppingPlanItem,
    ) -> list[ProductResult]:
        """Assign a relevance-aware composite score."""

        if not products:
            return []

        # --------------------------------------------------------------
        # Price normalization
        # --------------------------------------------------------------

        prices = [
            product.price
            for product in products
        ]

        min_price = min(prices)

        max_price = (
            max(prices)
            if max(prices) != min_price
            else min_price + 1
        )

        # --------------------------------------------------------------
        # Shipping normalization
        # --------------------------------------------------------------

        shipping_costs = [
            self._cheapest_shipping(product)
            for product in products
        ]

        min_ship = min(shipping_costs)

        max_ship = (
            max(shipping_costs)
            if max(shipping_costs) != min_ship
            else min_ship + 1
        )

        # --------------------------------------------------------------
        # Delivery normalization
        # --------------------------------------------------------------

        delivery_days = [
            self._fastest_delivery(product)
            for product in products
        ]

        min_days = min(delivery_days)

        max_days = (
            max(delivery_days)
            if max(delivery_days) != min_days
            else min_days + 1
        )

        scored: list[ProductResult] = []

        for product in products:

            relevance_score = self._relevance_score(
                product,
                item,
            )

            price_score = 1.0 - (
                (product.price - min_price)
                / (max_price - min_price)
            )

            shipping_cost = self._cheapest_shipping(
                product
            )

            shipping_score = 1.0 - (
                (shipping_cost - min_ship)
                / (max_ship - min_ship)
            )

            days = self._fastest_delivery(
                product
            )

            delivery_score = 1.0 - (
                (days - min_days)
                / (max_days - min_days)
            )

            availability_score = (
                1.0
                if product.in_stock
                else 0.0
            )

            composite = (
                _WEIGHT_RELEVANCE * relevance_score
                + _WEIGHT_PRICE * price_score
                + _WEIGHT_SHIPPING * shipping_score
                + _WEIGHT_AVAILABILITY * availability_score
                + _WEIGHT_DELIVERY * delivery_score
            )

            product_copy = product.model_copy(
                update={
                    "score": round(
                        composite,
                        4,
                    )
                }
            )

            scored.append(product_copy)

        return scored

    # ------------------------------------------------------------------
    # Relevance score
    # ------------------------------------------------------------------

    @classmethod
    def _relevance_score(
        cls,
        product: ProductResult,
        item: ShoppingPlanItem,
    ) -> float:
        """Calculate how closely a product matches the request."""

        requested_text = " ".join(
            [
                item.name,
                *item.keywords,
                *item.features,
            ]
        )

        requested = cls._tokenize(
            requested_text
        )

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

        product_tokens = cls._tokenize(
            product_text
        )

        if not requested:
            return 0.0

        matched = requested.intersection(
            product_tokens
        )

        return len(matched) / len(requested)

    # ------------------------------------------------------------------
    # Shipping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cheapest_shipping(
        product: ProductResult,
    ) -> float:
        """Return the cheapest shipping cost."""

        if not product.shipping_options:
            return 5.99

        return min(
            option.price
            for option in product.shipping_options
        )

    @staticmethod
    def _fastest_delivery(
        product: ProductResult,
    ) -> int:
        """Return the fastest delivery days."""

        if not product.shipping_options:
            return 5

        return min(
            option.estimated_days_min
            for option in product.shipping_options
        )