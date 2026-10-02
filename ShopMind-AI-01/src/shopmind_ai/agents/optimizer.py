"""Split-order optimizer.

Determines the cheapest way to purchase all items in the comparison matrix.
The optimizer works on already-normalised product prices, so it does not
perform currency conversion itself.
"""

from __future__ import annotations

from collections import defaultdict

import structlog

from shopmind_ai.models import (
    ComparisonMatrix,
    ProductResult,
    ShoppingPreferences,
    SplitOrderItem,
    SplitOrderPlan,
)

logger = structlog.get_logger(__name__)


class SplitOrderOptimizer:
    """Computes optimal purchase plans across merchants."""

    async def optimize(
        self,
        matrix: ComparisonMatrix,
        preferences: ShoppingPreferences | None = None,
    ) -> SplitOrderPlan:
        """Build an optimized split-order plan."""

        prefs = preferences or ShoppingPreferences()

        if prefs.prefer_single_merchant:
            return self._optimize_single_merchant(
                matrix,
                prefs,
            )

        return self._optimize_split(
            matrix,
            prefs,
        )

    def _optimize_split(
        self,
        matrix: ComparisonMatrix,
        prefs: ShoppingPreferences,
    ) -> SplitOrderPlan:
        """Pick the cheapest option per item regardless of merchant."""

        items: list[SplitOrderItem] = []

        for entry in matrix.entries:
            if not entry.merchant_results:
                continue

            candidates = self._apply_preference_filters(
                entry.merchant_results,
                prefs,
            )

            if not candidates:
                candidates = entry.merchant_results

            best = min(
                candidates,
                key=lambda p: (
                    p.price
                    + self._cheapest_shipping_cost(p)
                ),
            )

            shipping = self._cheapest_shipping_cost(best)

            items.append(
                SplitOrderItem(
                    product_name=best.name,
                    product_id=best.product_id,
                    merchant_name=best.merchant_name,
                    merchant_id=best.merchant_id,
                    merchant_url=self._get_merchant_url(best),
                    price=best.price,
                    shipping_cost=shipping,
                )
            )

        items = self._apply_free_shipping_thresholds(
            items,
            matrix,
        )

        total_product = round(
            sum(item.price for item in items),
            2,
        )
        total_shipping = round(
            sum(item.shipping_cost for item in items),
            2,
        )
        grand_total = round(
            total_product + total_shipping,
            2,
        )

        single_plan = self._optimize_single_merchant(
            matrix,
            prefs,
        )

        savings = round(
            max(
                0.0,
                single_plan.grand_total - grand_total,
            ),
            2,
        )

        merchant_ids = {
            item.merchant_id
            for item in items
        }

        plan = SplitOrderPlan(
            items=items,
            total_product_cost=total_product,
            total_shipping_cost=total_shipping,
            grand_total=grand_total,
            savings_vs_single=savings,
            merchants_used=len(merchant_ids),
            reasoning=self._build_reasoning(
                items,
                savings,
                matrix,
            ),
        )

        logger.info(
            "split_order_optimized",
            items=len(items),
            merchants=len(merchant_ids),
            grand_total=grand_total,
            savings=savings,
            currency=getattr(
                matrix,
                "display_currency",
                None,
            ),
        )

        return plan

    def _optimize_single_merchant(
        self,
        matrix: ComparisonMatrix,
        prefs: ShoppingPreferences,
    ) -> SplitOrderPlan:
        """Find the best single merchant to fulfil all items."""

        merchant_items: dict[
            str,
            list[tuple[str, ProductResult]],
        ] = defaultdict(list)

        for entry in matrix.entries:
            for result in entry.merchant_results:
                merchant_items[result.merchant_id].append(
                    (
                        entry.product_query,
                        result,
                    )
                )

        num_items = len(matrix.entries)
        best_plan: SplitOrderPlan | None = None

        for merchant_id, available in merchant_items.items():
            item_map: dict[
                str,
                ProductResult,
            ] = {}

            for item_query, product in available:
                if (
                    item_query not in item_map
                    or product.price
                    < item_map[item_query].price
                ):
                    item_map[item_query] = product

            if len(item_map) < num_items:
                continue

            items: list[SplitOrderItem] = []

            for item_query, product in item_map.items():
                shipping = self._cheapest_shipping_cost(product)

                items.append(
                    SplitOrderItem(
                        product_name=product.name,
                        product_id=product.product_id,
                        merchant_name=product.merchant_name,
                        merchant_id=product.merchant_id,
                        merchant_url=self._get_merchant_url(product),
                        price=product.price,
                        shipping_cost=shipping,
                    )
                )

            total_product = round(
                sum(item.price for item in items),
                2,
            )
            total_shipping = round(
                sum(item.shipping_cost for item in items),
                2,
            )
            grand_total = round(
                total_product + total_shipping,
                2,
            )

            plan = SplitOrderPlan(
                items=items,
                total_product_cost=total_product,
                total_shipping_cost=total_shipping,
                grand_total=grand_total,
                savings_vs_single=0.0,
                merchants_used=1,
                reasoning=(
                    f"All items from "
                    f"{items[0].merchant_name if items else 'unknown'}."
                ),
            )

            if (
                best_plan is None
                or grand_total < best_plan.grand_total
            ):
                best_plan = plan

        if best_plan is not None:
            return best_plan

        return SplitOrderPlan(
            items=[],
            reasoning="No single merchant can fulfil all items.",
        )

    def _apply_free_shipping_thresholds(
        self,
        items: list[SplitOrderItem],
        matrix: ComparisonMatrix,
    ) -> list[SplitOrderItem]:
        """Apply the existing simplified free-shipping heuristic."""

        merchant_subtotals: dict[str, float] = defaultdict(float)

        for item in items:
            merchant_subtotals[item.merchant_id] += item.price

        # Preserve the project's existing simplified threshold.
        free_shipping_threshold = 100.0

        updated: list[SplitOrderItem] = []

        for item in items:
            if (
                merchant_subtotals[item.merchant_id]
                >= free_shipping_threshold
            ):
                updated.append(
                    item.model_copy(
                        update={
                            "shipping_cost": 0.0,
                            "total": round(
                                item.price,
                                2,
                            ),
                        }
                    )
                )
            else:
                updated.append(item)

        return updated

    @staticmethod
    def _apply_preference_filters(
        products: list[ProductResult],
        prefs: ShoppingPreferences,
    ) -> list[ProductResult]:
        """Filter products based on user preferences."""

        filtered = list(products)

        if prefs.max_shipping_days is not None:
            filtered = [
                product
                for product in filtered
                if any(
                    option.estimated_days_max
                    <= prefs.max_shipping_days
                    for option in product.shipping_options
                )
                or not product.shipping_options
            ]

        if prefs.prefer_free_shipping:
            free_options = [
                product
                for product in filtered
                if any(
                    option.is_free
                    or option.price == 0
                    for option in product.shipping_options
                )
            ]

            if free_options:
                filtered = free_options

        if prefs.preferred_brands:
            brand_lower = {
                brand.lower()
                for brand in prefs.preferred_brands
            }

            brand_matches = [
                product
                for product in filtered
                if product.brand.lower()
                in brand_lower
            ]

            if brand_matches:
                filtered = brand_matches

        if prefs.min_rating is not None:
            rated = [
                product
                for product in filtered
                if product.rating >= prefs.min_rating
            ]

            if rated:
                filtered = rated

        return filtered

    @staticmethod
    def _cheapest_shipping_cost(
        product: ProductResult,
    ) -> float:
        """Return cheapest shipping cost."""

        if not product.shipping_options:
            return 5.99

        return min(
            option.price
            for option in product.shipping_options
        )

    @staticmethod
    def _get_merchant_url(
        product: ProductResult,
    ) -> str:
        """Derive merchant URL from product metadata."""

        return (
            product.url.rsplit("/api", 1)[0]
            if "/api" in product.url
            else ""
        )

    @staticmethod
    def _build_reasoning(
        items: list[SplitOrderItem],
        savings: float,
        matrix: ComparisonMatrix,
    ) -> str:
        """Build a human-readable explanation of the plan."""

        if not items:
            return "No items to purchase."

        merchant_names = sorted(
            {
                item.merchant_name
                for item in items
            }
        )

        if len(merchant_names) == 1:
            reasoning = (
                f"All {len(items)} item(s) purchased "
                f"from {merchant_names[0]}."
            )
        else:
            reasoning = (
                f"Order split across "
                f"{len(merchant_names)} merchants "
                f"({', '.join(merchant_names)}) "
                f"for optimal pricing."
            )

        currency = getattr(
            matrix,
            "display_currency",
            None,
        )

        if savings > 0:
            if currency:
                reasoning += (
                    f" Saves {currency} {savings:.2f} "
                    f"compared to single-merchant purchase."
                )
            else:
                reasoning += (
                    f" Saves {savings:.2f} "
                    f"compared to single-merchant purchase."
                )

        return reasoning