"""LLM-powered shopping planner.

Provider fallback order:

1. Google Gemini
2. Groq
3. Mistral
4. OpenRouter
5. Keyword fallback
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

import structlog

from shopmind_ai.config import Settings
from shopmind_ai.models import ShoppingPlan, ShoppingPlanItem, ShoppingPreferences

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """\
You are a shopping assistant planner.

Given the user's natural-language shopping query, extract a structured
shopping plan.

Return ONLY valid JSON with this schema:

{
  "items": [
    {
      "name": "<product name>",
      "keywords": ["keyword1", "keyword2"],
      "budget": <number or null>,
      "brand_preference": "<brand or null>",
      "features": ["feature1", "feature2"]
    }
  ],
  "overall_budget": <number or null>,
  "preferences": {
    "prefer_single_merchant": false,
    "max_shipping_days": <number or null>,
    "prefer_free_shipping": false
  },
  "reasoning": "<brief explanation>"
}

Rules:
- Extract every distinct product the user wants.
- Separate budget from product features.
- Capture brand preferences.
- Create useful search-engine-friendly keywords.
- If no budget is stated, use null.
- Return ONLY JSON.
"""


class ShoppingPlanner:
    """Parses natural-language shopping queries into structured plans."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

        self._gemini_client: object | None = None
        self._groq_client: object | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def plan(self, query: str, provider: str = "auto") -> ShoppingPlan:
        """Create a shopping plan using the configured fallback chain.

        Gemini -> Groq -> Keyword fallback.

        The budget is also extracted locally as a deterministic safety
        net. This prevents an LLM response containing
        ``"overall_budget": null`` from losing a budget explicitly
        stated by the user, such as "under 1500".
        """

        # --------------------------------------------------------------
        # Always detect the budget locally first.
        # --------------------------------------------------------------
        detected_budget = self._extract_budget_from_query(query)

        plan: ShoppingPlan | None = None

        # --------------------------------------------------------------
        # Provider selection
        # --------------------------------------------------------------
        selected = (provider or "auto").strip().lower()

        providers = (
            [selected]
            if selected != "auto"
            else [
                item.strip().lower()
                for item in self._settings.ai_provider_order.split(",")
                if item.strip()
            ]
        )

        for provider_name in providers:
            if plan is not None:
                break

            try:
                if provider_name == "gemini" and self._settings.google_api_key:
                    logger.info("using_gemini_planner")
                    plan = await self._plan_with_gemini(query)

                elif provider_name == "groq" and self._settings.groq_api_key:
                    logger.info("using_groq_planner")
                    plan = await self._plan_with_groq(query)

                elif provider_name == "mistral" and self._settings.mistral_api_key:
                    logger.info("using_mistral_planner")
                    plan = await self._plan_with_mistral(query)

                elif provider_name == "openrouter" and self._settings.openrouter_api_key:
                    logger.info("using_openrouter_planner")
                    plan = await self._plan_with_openrouter(query)

            except Exception:
                logger.warning(
                    "llm_planning_failed",
                    provider=provider_name,
                    exc_info=True,
                )

        # If a manually selected provider is unavailable, fail over to the
        # normal configured chain instead of breaking the shopping workflow.
        if plan is None and selected != "auto":
            for provider_name in [
                item.strip().lower()
                for item in self._settings.ai_provider_order.split(",")
                if item.strip() and item.strip().lower() != selected
            ]:
                try:
                    if provider_name == "gemini" and self._settings.google_api_key:
                        plan = await self._plan_with_gemini(query)
                    elif provider_name == "groq" and self._settings.groq_api_key:
                        plan = await self._plan_with_groq(query)
                    elif provider_name == "mistral" and self._settings.mistral_api_key:
                        plan = await self._plan_with_mistral(query)
                    elif provider_name == "openrouter" and self._settings.openrouter_api_key:
                        plan = await self._plan_with_openrouter(query)
                    if plan is not None:
                        logger.info(
                            "planner_provider_fallback",
                            requested=selected,
                            selected=provider_name,
                        )
                        break
                except Exception:
                    logger.warning(
                        "planner_fallback_failed",
                        provider=provider_name,
                        exc_info=True,
                    )

        # --------------------------------------------------------------
        # Keyword fallback
        # --------------------------------------------------------------

        if plan is None:
            logger.info("using_fallback_planner")
            plan = self._plan_with_keywords(query)

        # --------------------------------------------------------------
        # IMPORTANT:
        #
        # If the LLM missed the budget but the deterministic parser
        # found one, always use the locally detected budget.
        # --------------------------------------------------------------

        if (
            plan.overall_budget is None
            and detected_budget is not None
        ):
            plan.overall_budget = detected_budget

            # If there is exactly one item, also attach the same
            # budget to that item when the LLM did not provide one.
            if (
                len(plan.items) == 1
                and plan.items[0].budget is None
            ):
                plan.items[0].budget = detected_budget

            plan.reasoning = (
                f"{plan.reasoning} "
                f"Budget detected locally from the user query: "
                f"{detected_budget}."
            ).strip()

            logger.info(
                "budget_recovered_from_query",
                budget=str(detected_budget),
            )

        return plan

    # ------------------------------------------------------------------
    # Deterministic budget extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_budget_from_query(
        query: str,
    ) -> Decimal | None:
        """Extract a numeric budget from a natural-language query.

        Supported examples:
        - under 1500
        - below 2000
        - budget 5000
        - max 3000
        - up to 1500
        - under ₹1500
        - under Rs. 1500
        - under INR 1500
        - 1500 INR
        - 1500 rupees
        - $100
        """

        if not query:
            return None

        text = query.strip()

        # Normalize common currency symbols and encoding variants.
        normalized = (
            text
            .replace("₹", " INR ")
            .replace("â‚¹", " INR ")
            .replace("₨", " PKR ")
            .replace("€", " EUR ")
            .replace("£", " GBP ")
            .replace("₽", " RUB ")
            .replace("$", " USD ")
        )

        # --------------------------------------------------------------
        # Pattern 1:
        # under 1500
        # below 2000
        # budget 5000
        # max 3000
        # up to 1500
        # --------------------------------------------------------------

        match = re.search(
            r"\b(?:under|below|budget|max|upto|up\s+to)"
            r"\s*(?:inr|rs\.?|rupees?|usd|dollars?|"
            r"eur|euros?|gbp|pounds?|rub|rubles?|npr)?"
            r"\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)",
            normalized,
            re.IGNORECASE,
        )

        if match:
            value = match.group(1).replace(",", "")

            try:
                return Decimal(value)
            except Exception:
                pass

        # --------------------------------------------------------------
        # Pattern 2:
        # INR 1500
        # Rs 1500
        # 1500 INR
        # 1500 rupees
        # --------------------------------------------------------------

        match = re.search(
            r"(?:"
            r"(?:inr|rs\.?|rupees?)\s*"
            r"(\d+(?:,\d{3})*(?:\.\d{1,2})?)"
            r"|"
            r"(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*"
            r"(?:inr|rs\.?|rupees?)"
            r")",
            normalized,
            re.IGNORECASE,
        )

        if match:
            value = match.group(1) or match.group(2)

            try:
                return Decimal(value.replace(",", ""))
            except Exception:
                pass

        return None

    # ------------------------------------------------------------------
    # Gemini
    # ------------------------------------------------------------------

    async def _plan_with_gemini(
        self,
        query: str,
    ) -> ShoppingPlan:
        """Use Google Gemini to parse the shopping query."""

        from langchain_google_genai import ChatGoogleGenerativeAI

        if self._gemini_client is None:
            self._gemini_client = ChatGoogleGenerativeAI(
                model=self._settings.default_model,
                google_api_key=self._settings.google_api_key,
                max_output_tokens=1024,
            )

        client: ChatGoogleGenerativeAI = self._gemini_client  # type: ignore[assignment]

        response = await client.ainvoke(
            [
                (
                    "system",
                    _SYSTEM_PROMPT,
                ),
                (
                    "human",
                    query,
                ),
            ]
        )

        raw = response.content

        if isinstance(raw, list):
            parts: list[str] = []

            for item in raw:
                if isinstance(item, dict):
                    text = item.get("text", "")

                    if text:
                        parts.append(str(text))
                else:
                    parts.append(str(item))

            raw = "".join(parts)

        return self._parse_plan_json(
            str(raw),
            query,
        )

    # ------------------------------------------------------------------
    # Groq
    # ------------------------------------------------------------------

    async def _plan_with_groq(
        self,
        query: str,
    ) -> ShoppingPlan:
        """Use Groq as the secondary LLM provider."""

        from langchain_groq import ChatGroq

        if self._groq_client is None:
            self._groq_client = ChatGroq(
                model=self._settings.groq_model,
                api_key=self._settings.groq_api_key,
                temperature=0.2,
                max_tokens=1024,
            )

        client: ChatGroq = self._groq_client  # type: ignore[assignment]

        response = await client.ainvoke(
            [
                (
                    "system",
                    _SYSTEM_PROMPT,
                ),
                (
                    "human",
                    query,
                ),
            ]
        )

        raw = response.content

        if isinstance(raw, list):
            parts: list[str] = []

            for item in raw:
                if isinstance(item, dict):
                    text = item.get("text", "")

                    if text:
                        parts.append(str(text))
                else:
                    parts.append(str(item))

            raw = "".join(parts)

        return self._parse_plan_json(
            str(raw),
            query,
        )

    # ------------------------------------------------------------------
    # Mistral
    # ------------------------------------------------------------------

    async def _plan_with_mistral(self, query: str) -> ShoppingPlan:
        """Use Mistral's JSON mode without adding another SDK dependency."""

        import httpx

        payload = {
            "model": self._settings.mistral_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 1024,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._settings.mistral_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        return self._parse_plan_json(str(content), query)

    # ------------------------------------------------------------------
    # OpenRouter
    # ------------------------------------------------------------------

    async def _plan_with_openrouter(self, query: str) -> ShoppingPlan:
        """Use OpenRouter's OpenAI-compatible chat endpoint."""

        import httpx

        payload: dict[str, Any] = {
            "model": self._settings.openrouter_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 1024,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:5173",
                    "X-Title": "ShopMind AI",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        return self._parse_plan_json(str(content), query)

    # ------------------------------------------------------------------
    # JSON parser
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_plan_json(
        raw: str,
        original_query: str,
    ) -> ShoppingPlan:
        """Convert LLM JSON into ShoppingPlan."""

        cleaned = raw.strip()

        # Remove markdown JSON fences.
        cleaned = re.sub(
            r"^```(?:json)?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

        cleaned = re.sub(
            r"\s*```$",
            "",
            cleaned,
        ).strip()

        try:
            data = json.loads(cleaned)

        except json.JSONDecodeError:
            logger.warning(
                "plan_json_parse_failed",
                raw_snippet=raw[:200],
            )

            return ShoppingPlanner._plan_with_keywords(
                original_query
            )

        # --------------------------------------------------------------
        # Items
        # --------------------------------------------------------------

        items: list[ShoppingPlanItem] = []

        for item_data in data.get("items", []):
            if not isinstance(item_data, dict):
                continue

            budget_val = item_data.get("budget")

            items.append(
                ShoppingPlanItem(
                    name=item_data.get(
                        "name",
                        "",
                    ),
                    keywords=item_data.get(
                        "keywords",
                        [],
                    ),
                    budget=(
                        Decimal(str(budget_val))
                        if budget_val is not None
                        else None
                    ),
                    brand_preference=item_data.get(
                        "brand_preference"
                    ),
                    features=item_data.get(
                        "features",
                        [],
                    ),
                )
            )

        # --------------------------------------------------------------
        # Overall budget
        # --------------------------------------------------------------

        overall_budget_val = data.get(
            "overall_budget"
        )

        overall_budget = (
            Decimal(str(overall_budget_val))
            if overall_budget_val is not None
            else None
        )

        # --------------------------------------------------------------
        # Preferences
        # --------------------------------------------------------------

        prefs_data = data.get(
            "preferences",
            {},
        )

        if not isinstance(
            prefs_data,
            dict,
        ):
            prefs_data = {}

        preferences = ShoppingPreferences(
            prefer_single_merchant=prefs_data.get(
                "prefer_single_merchant",
                False,
            ),
            max_shipping_days=prefs_data.get(
                "max_shipping_days"
            ),
            prefer_free_shipping=prefs_data.get(
                "prefer_free_shipping",
                False,
            ),
        )

        # --------------------------------------------------------------
        # Final plan
        # --------------------------------------------------------------

        return ShoppingPlan(
            items=items,
            overall_budget=overall_budget,
            preferences=preferences,
            reasoning=data.get(
                "reasoning",
                "",
            ),
        )

    # ------------------------------------------------------------------
    # Keyword fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _plan_with_keywords(
        query: str,
    ) -> ShoppingPlan:
        """Create a basic shopping plan without an LLM."""

        # --------------------------------------------------------------
        # Detect budget
        # --------------------------------------------------------------

        overall_budget = (
            ShoppingPlanner._extract_budget_from_query(query)
        )

        budget_match = re.search(
            r"(?:under|below|budget|max|upto|up\s+to)"
            r"\s*(?:â‚¹|₹|rs\.?|inr|\$)?\s*"
            r"(\d+(?:,\d{3})*(?:\.\d{1,2})?)",
            query,
            re.IGNORECASE,
        )

        # --------------------------------------------------------------
        # Remove budget phrase
        # --------------------------------------------------------------

        cleaned = query

        if budget_match:
            cleaned = (
                cleaned[: budget_match.start()]
                + cleaned[budget_match.end() :]
            )

        # --------------------------------------------------------------
        # Split products
        # --------------------------------------------------------------

        fragments = re.split(
            r"\band\b|,|;",
            cleaned,
            flags=re.IGNORECASE,
        )

        items: list[ShoppingPlanItem] = []

        for fragment in fragments:
            fragment = fragment.strip()

            if not fragment or len(fragment) < 3:
                continue

            keywords = [
                word.lower()
                for word in fragment.split()
                if len(word) > 2
            ]

            items.append(
                ShoppingPlanItem(
                    name=fragment,
                    keywords=keywords,
                )
            )

        # --------------------------------------------------------------
        # Whole query fallback
        # --------------------------------------------------------------

        if not items:
            items.append(
                ShoppingPlanItem(
                    name=query.strip(),
                    keywords=[
                        word.lower()
                        for word in query.split()
                        if len(word) > 2
                    ],
                )
            )

        return ShoppingPlan(
            items=items,
            overall_budget=overall_budget,
            reasoning=(
                "Fallback keyword extraction "
                "(no LLM available)."
            ),
        )