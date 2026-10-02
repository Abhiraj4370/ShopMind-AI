"""AI-powered product recommendation agent."""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from shopmind_ai.config import Settings
from shopmind_ai.models import (
    ComparisonMatrix,
    ProductResult,
    ShoppingPlan,
)

logger = structlog.get_logger(__name__)


_SYSTEM_PROMPT = """
You are an expert shopping recommendation assistant.

Analyze the user's shopping request and the available product comparison.

Choose:
1. Best overall product
2. Best value product
3. Best alternative product

Consider:
- User's budget
- Required features
- Brand preferences
- Product price
- Shipping cost
- Delivery speed
- Stock availability
- Rating
- Product specifications

Do NOT recommend products that clearly exceed the user's budget.

Return ONLY valid JSON:

{
  "best_overall_product_id": "...",
  "best_value_product_id": "...",
  "best_alternative_product_id": "...",
  "reasoning": "...",
  "highlights": [
    "...",
    "...",
    "..."
  ]
}
"""


class RecommendationAgent:
    """Uses Gemini to recommend the best products for the user."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None

    async def recommend(
        self,
        shopping_plan: ShoppingPlan,
        comparison: ComparisonMatrix,
    ) -> dict[str, Any]:
        """Generate AI-powered recommendations."""

        products = self._collect_products(comparison)

        if not products:
            return {
                "best_overall_product_id": None,
                "best_value_product_id": None,
                "best_alternative_product_id": None,
                "reasoning": "No products were available for recommendation.",
                "highlights": [],
            }

        prompt = self._build_prompt(shopping_plan, products)

        try:
            result = await self._recommend_with_gemini(prompt)
            return self._validate_result(result, products)
        except Exception:
            logger.warning(
                "ai_recommendation_failed",
                exc_info=True,
            )

            return self._fallback_recommendation(
                shopping_plan,
                products,
            )

    # ------------------------------------------------------------------
    # Gemini
    # ------------------------------------------------------------------

    async def _recommend_with_gemini(
        self,
        prompt: str,
    ) -> dict[str, Any]:
        """Ask Gemini for product recommendations."""

        from langchain_google_genai import ChatGoogleGenerativeAI

        if self._client is None:
            self._client = ChatGoogleGenerativeAI(
                model="gemini-3.6-flash",
                google_api_key=self._settings.google_api_key,
                temperature=0,
            )

        response = await self._client.ainvoke(
            [
                ("system", _SYSTEM_PROMPT),
                ("human", prompt),
            ]
        )

        raw = response.content

        if isinstance(raw, list):
            raw = "".join(
                block.get("text", "")
                if isinstance(block, dict)
                else str(block)
                for block in raw
            )

        return self._parse_json(str(raw))

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(
        shopping_plan: ShoppingPlan,
        products: list[ProductResult],
    ) -> str:
        """Build the recommendation prompt."""

        plan_data = shopping_plan.model_dump(mode="json")

        product_data = []

        for product in products:
            shipping = (
                min(
                    (
                        option.price
                        for option in product.shipping_options
                    ),
                    default=5.99,
                )
            )

            delivery = (
                min(
                    (
                        option.estimated_days_min
                        for option in product.shipping_options
                    ),
                    default=5,
                )
            )

            product_data.append(
                {
                    "product_id": product.product_id,
                    "name": product.name,
                    "brand": product.brand,
                    "price": product.price,
                    "currency": product.currency,
                    "merchant": product.merchant_name,
                    "category": product.category,
                    "description": product.description,
                    "specs": product.specs,
                    "rating": product.rating,
                    "in_stock": product.in_stock,
                    "shipping_cost": shipping,
                    "delivery_days": delivery,
                    "score": product.score,
                    "url": product.url,
                }
            )

        return (
            "USER SHOPPING PLAN:\n"
            + json.dumps(plan_data, indent=2)
            + "\n\nAVAILABLE PRODUCTS:\n"
            + json.dumps(product_data, indent=2)
        )

    # ------------------------------------------------------------------
    # JSON parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """Parse Gemini JSON output."""

        cleaned = re.sub(
            r"```json?\s*",
            "",
            raw,
            flags=re.IGNORECASE,
        )

        cleaned = re.sub(
            r"```\s*$",
            "",
            cleaned,
        ).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning(
                "recommendation_json_parse_failed",
                raw_snippet=raw[:300],
            )
            raise

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_result(
        result: dict[str, Any],
        products: list[ProductResult],
    ) -> dict[str, Any]:
        """Ensure Gemini only recommends products that exist."""

        valid_ids = {
            product.product_id
            for product in products
        }

        def valid_id(value: Any) -> str | None:
            if value in valid_ids:
                return value
            return None

        return {
            "best_overall_product_id": valid_id(
                result.get("best_overall_product_id")
            ),
            "best_value_product_id": valid_id(
                result.get("best_value_product_id")
            ),
            "best_alternative_product_id": valid_id(
                result.get("best_alternative_product_id")
            ),
            "reasoning": str(
                result.get("reasoning", "")
            ),
            "highlights": [
                str(item)
                for item in result.get("highlights", [])
            ],
        }

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_recommendation(
        shopping_plan: ShoppingPlan,
        products: list[ProductResult],
    ) -> dict[str, Any]:
        """Deterministic recommendation when Gemini is unavailable."""

        budget = shopping_plan.overall_budget

        candidates = [
            product
            for product in products
            if (
                budget is None
                or product.price <= float(budget)
            )
        ]

        if not candidates:
            candidates = products

        # Best overall = highest comparison score
        best_overall = max(
            candidates,
            key=lambda product: product.score,
        )

        # Best value = lowest price among reasonable products
        best_value = min(
            candidates,
            key=lambda product: product.price,
        )

        # Best alternative = highest rating excluding overall
        alternatives = [
            product
            for product in candidates
            if product.product_id
            != best_overall.product_id
        ]

        best_alternative = (
            max(
                alternatives,
                key=lambda product: product.rating,
            )
            if alternatives
            else best_overall
        )

        return {
            "best_overall_product_id": best_overall.product_id,
            "best_value_product_id": best_value.product_id,
            "best_alternative_product_id": best_alternative.product_id,
            "reasoning": (
                "AI recommendation unavailable. "
                "Used price, comparison score, and rating "
                "based fallback."
            ),
            "highlights": [
                f"Best overall: {best_overall.name}",
                f"Best value: {best_value.name}",
                f"Best alternative: {best_alternative.name}",
            ],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_products(
        comparison: ComparisonMatrix,
    ) -> list[ProductResult]:
        """Flatten products from comparison entries."""

        products: list[ProductResult] = []

        seen: set[str] = set()

        for entry in comparison.entries:
            for product in entry.merchant_results:
                if product.product_id not in seen:
                    seen.add(product.product_id)
                    products.append(product)

        return products
