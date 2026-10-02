"""FastAPI application for the ShopMind AI.

Exposes REST endpoints for:
- Shopping session management (create, status, confirm, cancel)
- SSE streaming of shopping workflow progress
- Price comparison and split-order optimization
- Merchant discovery and catalog browsing
- Order tracking
- MCP tool surface
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from common import ErrorResponse, HealthResponse

from shopmind_ai.agents.comparison_agent import ComparisonAgent
from shopmind_ai.agents.discovery_agent import DiscoveryAgent
from shopmind_ai.agents.optimizer import SplitOrderOptimizer
from shopmind_ai.agents.search_agent import SearchAgent
from shopmind_ai.config import Settings
from shopmind_ai.models import (
    MerchantInfo,
    OrderSummary,
    ProductResult,
    ShoppingPreferences,
    ShoppingRequest,
    ShoppingSession,
    ShoppingSessionState,
)
from shopmind_ai.orchestrator.graph import compile_shopping_graph
from shopmind_ai.orchestrator.state import ShoppingGraphState
from shopmind_ai.protocols.mcp_surface import MCPToolHandler, list_tools
from shopmind_ai.streaming import ShoppingEventStream
from shopmind_ai.services.currency import (
    currency_symbol,
    resolve_region,
)
from shopmind_ai.services.regional_pricing import RegionalPricingService

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ShopRequest(BaseModel):
    query: str
    budget: float | None = None
    country_code: str | None = None
    currency: str | None = None
    preferences: ShoppingPreferences = Field(
        default_factory=ShoppingPreferences
    )

class CompareRequest(BaseModel):
    """Price comparison request."""

    product_query: str
    max_results_per_merchant: int = 10

    # Optional explicit region/currency from the frontend.
    # If omitted, the server uses Accept-Language/IP detection.
    country_code: str | None = None
    currency: str | None = None


class OptimizeRequest(BaseModel):
    """Split-order optimization request."""

    session_id: str


class DiscoverRequest(BaseModel):
    """Merchant discovery request."""

    urls: list[str]


class ToolExecuteRequest(BaseModel):
    """MCP tool execution request."""

    arguments: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------


class SessionManager:
    """In-memory shopping session store."""

    def __init__(self) -> None:
        self._sessions: dict[str, ShoppingSession] = {}
        self._graph_tasks: dict[str, asyncio.Task[Any]] = {}

    async def create_session(
        self,
        request: ShoppingRequest,
    ) -> ShoppingSession:
        """Create a new shopping session."""

        session_id = str(uuid.uuid4())

        session = ShoppingSession(
            id=session_id,
            request=request,
            state=ShoppingSessionState.PLANNING,
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )

        self._sessions[session_id] = session

        return session

    def get_session(
        self,
        session_id: str,
    ) -> ShoppingSession | None:
        """Retrieve a session by ID."""

        return self._sessions.get(session_id)

    def update_session(
        self,
        session_id: str,
        **kwargs: Any,
    ) -> ShoppingSession | None:
        """Update session fields."""

        session = self._sessions.get(session_id)

        if session is None:
            return None

        for key, value in kwargs.items():
            if hasattr(session, key):
                setattr(session, key, value)

        session.updated_at = datetime.now(tz=timezone.utc)

        return session

    def list_sessions(self) -> list[ShoppingSession]:
        """Return all sessions."""

        return list(self._sessions.values())


# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------


class AppState:
    """Shared application state."""

    def __init__(
        self,
        settings: Settings,
    ) -> None:
        self.settings = settings

        self.session_manager = SessionManager()

        self.event_stream = ShoppingEventStream()

        # Converts merchant prices into the user's local currency.
        self.regional_pricing = RegionalPricingService()

        self.merchants: dict[str, MerchantInfo] = {}

        self.orders: dict[str, OrderSummary] = {}

        self.graph_confirmations: dict[
            str,
            asyncio.Event,
        ] = {}


# ---------------------------------------------------------------------------
# Regional pricing helpers
# ---------------------------------------------------------------------------


async def _convert_product_amount(
    pricing: RegionalPricingService,
    *,
    amount: float,
    source_currency: str,
    target_currency: str,
) -> float:
    """Convert one monetary amount using the same pricing engine as products.

    The RegionalPricingService already exposes convert_products(), so we use
    a temporary ProductResult to avoid depending on a private converter API.
    The original amount/currency is preserved on the real object.
    """
    if not amount:
        return 0.0

    if not source_currency:
        source_currency = "USD"

    if source_currency.upper() == target_currency.upper():
        return round(float(amount), 2)

    temp = ProductResult(
        product_id="__amount__",
        name="__amount__",
        price=float(amount),
        currency=source_currency.upper(),
        merchant_id="__internal__",
        merchant_name="__internal__",
    )

    await pricing.convert_products(
        [temp],
        target_currency.upper(),
    )

    if temp.display_price is not None:
        return round(float(temp.display_price), 2)

    # Fail safe: never silently return a wrong converted value.
    return round(float(amount), 2)


async def _convert_optimization_plan(
    pricing: RegionalPricingService,
    plan: Any,
    target_currency: str,
) -> Any:
    """Convert an optimization plan to the user's display currency."""
    if plan is None:
        return None

    target_currency = target_currency.upper()

    total_product_cost = 0.0
    total_shipping_cost = 0.0
    grand_total = 0.0

    for item in plan.items:
        source_currency = (
            getattr(item, "currency", None) or "USD"
        ).upper()

        original_price = float(item.price)
        original_shipping = float(item.shipping_cost)

        converted_price = await _convert_product_amount(
            pricing,
            amount=original_price,
            source_currency=source_currency,
            target_currency=target_currency,
        )

        converted_shipping = await _convert_product_amount(
            pricing,
            amount=original_shipping,
            source_currency=source_currency,
            target_currency=target_currency,
        )

        item.price = converted_price
        item.shipping_cost = converted_shipping
        item.total = round(
            converted_price + converted_shipping,
            2,
        )
        item.currency = target_currency
        item.currency_symbol = currency_symbol(
            target_currency
        )

        total_product_cost += converted_price
        total_shipping_cost += converted_shipping
        grand_total += item.total

    plan.total_product_cost = round(
        total_product_cost,
        2,
    )
    plan.total_shipping_cost = round(
        total_shipping_cost,
        2,
    )
    plan.grand_total = round(
        grand_total,
        2,
    )
    plan.display_currency = target_currency
    plan.currency_symbol = currency_symbol(
        target_currency
    )

    return plan


async def _regionalize_comparison(
    pricing: RegionalPricingService,
    comparison: Any,
    target_currency: str,
) -> Any:
    """Populate local display prices on every comparison product."""
    if comparison is None:
        return None

    target_currency = target_currency.upper()

    for entry in comparison.entries:
        products: list[ProductResult] = []

        products.extend(entry.merchant_results)

        if entry.best_price is not None:
            products.append(entry.best_price)

        if entry.best_shipping is not None:
            products.append(entry.best_shipping)

        if entry.recommended is not None:
            products.append(entry.recommended)

        # Deduplicate by object identity/product/merchant combination.
        unique: list[ProductResult] = []
        seen: set[tuple[str, str]] = set()

        for product in products:
            key = (
                str(product.merchant_id),
                str(product.product_id),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(product)

        if unique:
            await pricing.convert_products(
                unique,
                target_currency,
            )

    comparison.display_currency = target_currency
    comparison.currency_symbol = currency_symbol(
        target_currency
    )

    return comparison


def _get_plan_budget(
    shopping_request: ShoppingRequest,
    graph_result: dict[str, Any],
) -> float | None:
    """Get the user's budget in the display currency."""
    if shopping_request.budget is not None:
        return float(shopping_request.budget)

    shopping_plan = graph_result.get("shopping_plan")

    if shopping_plan is not None:
        overall_budget = getattr(
            shopping_plan,
            "overall_budget",
            None,
        )
        if overall_budget is not None:
            return float(overall_budget)

    return None


def _filter_products_by_local_budget(
    results: dict[str, list[ProductResult]],
    budget: float | None,
) -> dict[str, list[ProductResult]]:
    """Remove products whose converted display price exceeds the budget."""
    if budget is None:
        return results

    filtered: dict[str, list[ProductResult]] = {}

    for merchant_id, products in results.items():
        kept: list[ProductResult] = []

        for product in products:
            local_price = product.display_price

            # If conversion failed, keep the product rather than silently
            # hiding it. The UI can still show the original merchant price.
            if local_price is None:
                kept.append(product)
                continue

            if float(local_price) <= float(budget):
                kept.append(product)

        filtered[merchant_id] = kept

    return filtered


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(
    settings: Settings | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application."""

    settings = settings or Settings()

    app = FastAPI(
        title="ShopMind AI",
        description=(
            "AI-powered shopping assistant that discovers UCP merchants, "
            "compares prices, and orchestrates multi-merchant purchases."
        ),
        version=settings.service_version,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # -----------------------------------------------------------------------
    # CORS
    # -----------------------------------------------------------------------

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -----------------------------------------------------------------------
    # Shared state
    # -----------------------------------------------------------------------

    state = AppState(settings)

    app.state.app_state = state
    app.state.settings = settings

    mcp_handler = MCPToolHandler(state)

    # -----------------------------------------------------------------------
    # Health
    # -----------------------------------------------------------------------

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["health"],
    )
    async def health() -> HealthResponse:
        """Health check."""

        return HealthResponse(
            status="healthy",
            service=settings.service_name,
            version=settings.service_version,
        )

    # -----------------------------------------------------------------------
    # Shopping session endpoints
    # -----------------------------------------------------------------------

    @app.post(
        "/api/v1/shop",
        tags=["shopping"],
    )
    async def create_shopping_session(
        request: Request,
        req: ShopRequest,
    ) -> dict[str, Any]:
        """Submit a new shopping request.

        Creates a session and starts the LangGraph workflow
        asynchronously.
        """

        # ---------------------------------------------------------------
        # Resolve the user's region/currency.
        #
        # Priority:
        # 1. Explicit currency sent by frontend/API
        # 2. Explicit country_code
        # 3. Browser Accept-Language
        # 4. IP geolocation
        # 5. USD fallback
        # ---------------------------------------------------------------
        client_ip = (
            request.client.host
            if request.client
            else None
        )

        country_code, display_currency = await resolve_region(
            country_code=req.country_code,
            accept_language=request.headers.get("accept-language"),
            ip_address=client_ip,
            preferred_currency=req.currency,
        )

        display_symbol = currency_symbol(display_currency)

        budget = (
            Decimal(str(req.budget))
            if req.budget is not None
            else None
        )

        shopping_req = ShoppingRequest(
            query=req.query,
            budget=budget,
            budget_currency=display_currency,
            country_code=country_code,
            display_currency=display_currency,
            currency_symbol=display_symbol,
            preferences=req.preferences,
        )

        session = await state.session_manager.create_session(
            shopping_req
        )

        confirmation_event = asyncio.Event()

        state.graph_confirmations[
            session.id
        ] = confirmation_event

        # -------------------------------------------------------------------
        # Background graph runner
        # -------------------------------------------------------------------

        async def _run_graph() -> None:
            """Execute the shopping graph safely."""

            try:
                logger.info(
                    "shopping_graph_started",
                    session_id=session.id,
                    query=shopping_req.query,
                )

                # -----------------------------------------------------------
                # Compile graph
                # -----------------------------------------------------------

                compiled = compile_shopping_graph(
                    settings,
                    state.event_stream,
                )

                logger.info(
                    "shopping_graph_compiled",
                    session_id=session.id,
                )

                # -----------------------------------------------------------
                # Initial graph state
                # -----------------------------------------------------------

                initial: ShoppingGraphState = {
                    "request": shopping_req,
                    "session_id": session.id,
                    "preferences": req.preferences,
                    "current_state": ShoppingSessionState.PLANNING,
                    "shopping_plan": None,
                    "discovered_merchants": [],
                    "failed_merchants": [],
                    "search_results": {},
                    "merged_results": [],
                    "comparison_matrix": None,
                    "optimization_plan": None,
                    "user_confirmed": False,
                    "active_checkouts": [],
                    "completed_orders": [],
                    "error": None,
                    "messages": [],
                }

                logger.info(
                    "shopping_graph_invoking",
                    session_id=session.id,
                )

                # -----------------------------------------------------------
                # Execute graph
                # -----------------------------------------------------------

                result = await compiled.ainvoke(
                    initial
                )

                logger.info(
                    "shopping_graph_finished",
                    session_id=session.id,
                    current_state=str(
                        result.get(
                            "current_state",
                            ShoppingSessionState.FAILED,
                        )
                    ),
                    error=result.get("error"),
                )

                # -----------------------------------------------------------
                # Regional pricing pipeline
                #
                # 1. Convert every search result to the user's currency.
                # 2. Apply the user's budget AFTER conversion.
                # 3. Rebuild comparison from the filtered results.
                # 4. Convert comparison display prices.
                # 5. Rebuild/refresh optimization from the valid comparison.
                #
                # Merchant/original price and currency are never destroyed.
                # The converted amount is stored in display_price.
                # -----------------------------------------------------------

                regional_results = result.get(
                    "search_results",
                    {},
                )

                for merchant_id, products in regional_results.items():
                    await state.regional_pricing.convert_products(
                        products,
                        shopping_req.display_currency,
                    )

                budget_limit = _get_plan_budget(
                    shopping_req,
                    result,
                )

                regional_results = _filter_products_by_local_budget(
                    regional_results,
                    budget_limit,
                )

                result["search_results"] = regional_results

                # -----------------------------------------------------------
                # Rebuild comparison from the products that actually satisfy
                # the user's local-currency budget.
                # -----------------------------------------------------------

                if any(regional_results.values()):
                    comparison_agent = ComparisonAgent()

                    product_names: list[str] = []

                    shopping_plan = result.get(
                        "shopping_plan"
                    )

                    if shopping_plan is not None:
                        for plan_item in getattr(
                            shopping_plan,
                            "items",
                            [],
                        ):
                            name = getattr(
                                plan_item,
                                "name",
                                "",
                            )
                            if name:
                                product_names.append(name)

                    if not product_names:
                        product_names = [shopping_req.query]

                    comparison_matrix = (
                        await comparison_agent.build_comparison(
                            regional_results,
                            item_names=product_names,
                        )
                    )

                    comparison_matrix = await _regionalize_comparison(
                        state.regional_pricing,
                        comparison_matrix,
                        shopping_req.display_currency,
                    )

                    result["comparison_matrix"] = comparison_matrix

                    # -------------------------------------------------------
                    # Refresh optimization using the filtered comparison.
                    # This prevents an over-budget USD product from being
                    # selected even when the user's budget is INR/NPR/RUB/etc.
                    # -------------------------------------------------------

                    optimizer = SplitOrderOptimizer()

                    optimization_plan = await optimizer.optimize(
                        comparison_matrix,
                        shopping_req.preferences,
                    )

                    optimization_plan = await _convert_optimization_plan(
                        state.regional_pricing,
                        optimization_plan,
                        shopping_req.display_currency,
                    )

                    result["optimization_plan"] = optimization_plan

                else:
                    # No product satisfies the local budget.
                    result["comparison_matrix"] = None
                    result["optimization_plan"] = None

                    if budget_limit is not None:
                        result["current_state"] = (
                            ShoppingSessionState.FAILED
                        )
                        result["error"] = (
                            "No products were found within the "
                            f"local budget of "
                            f"{shopping_req.currency_symbol}"
                            f"{budget_limit:,.2f} "
                            f"{shopping_req.display_currency}."
                        )

                # -----------------------------------------------------------
                # Persist intermediate state
                # -----------------------------------------------------------

                current_state = result.get(
                    "current_state",
                    ShoppingSessionState.FAILED,
                )

                state.session_manager.update_session(
                    session.id,
                    state=current_state,
                    merchants=result.get(
                        "discovered_merchants",
                        [],
                    ),
                    search_results=result.get(
                        "search_results",
                        {},
                    ),
                    comparison=result.get(
                        "comparison_matrix",
                    ),
                    optimization_plan=result.get(
                        "optimization_plan",
                    ),
                    error=result.get("error"),
                )

                # -----------------------------------------------------------
                # Store discovered merchants
                # -----------------------------------------------------------

                for merchant in result.get(
                    "discovered_merchants",
                    [],
                ):
                    state.merchants[
                        merchant.id
                    ] = merchant

                # -----------------------------------------------------------
                # Confirmation gate
                # -----------------------------------------------------------

                if (
                    current_state
                    == ShoppingSessionState.AWAITING_CONFIRMATION
                ):

                    if settings.human_confirmation_required:

                        logger.info(
                            "awaiting_confirmation",
                            session_id=session.id,
                        )

                        await confirmation_event.wait()

                        logger.info(
                            "confirmation_received",
                            session_id=session.id,
                        )

                    # -------------------------------------------------------
                    # Continue graph after confirmation
                    # -------------------------------------------------------

                    result["user_confirmed"] = True

                    logger.info(
                        "shopping_graph_resuming",
                        session_id=session.id,
                    )

                    result = await compiled.ainvoke(
                        result
                    )

                    final_state = result.get(
                        "current_state",
                        ShoppingSessionState.COMPLETED,
                    )

                    orders = result.get(
                        "completed_orders",
                        [],
                    )

                    state.session_manager.update_session(
                        session.id,
                        state=final_state,
                        orders=orders,
                        error=result.get("error"),
                    )

                    for order in orders:
                        state.orders[
                            order.order_id
                        ] = order

                    logger.info(
                        "shopping_graph_completed",
                        session_id=session.id,
                        state=str(final_state),
                        orders=len(orders),
                    )

            # ----------------------------------------------------------------
            # Cancellation
            # ----------------------------------------------------------------

            except asyncio.CancelledError:

                logger.warning(
                    "shopping_graph_cancelled",
                    session_id=session.id,
                )

                state.session_manager.update_session(
                    session.id,
                    state=ShoppingSessionState.FAILED,
                    error="Shopping workflow was cancelled.",
                )

                raise

            # ----------------------------------------------------------------
            # Any other error
            # ----------------------------------------------------------------

            except Exception as exc:

                logger.exception(
                    "shopping_graph_failed",
                    session_id=session.id,
                    error=str(exc),
                )

                state.session_manager.update_session(
                    session.id,
                    state=ShoppingSessionState.FAILED,
                    error=str(exc),
                )

        # -------------------------------------------------------------------
        # Start background task
        # -------------------------------------------------------------------

        task = asyncio.create_task(
            _run_graph()
        )

        state.session_manager._graph_tasks[
            session.id
        ] = task

        # -------------------------------------------------------------------
        # Return immediately
        # -------------------------------------------------------------------

        return {
            "session_id": session.id,
            "status": session.state.value,
            "message": (
                f"Shopping session created for: {req.query}"
            ),
            "stream_url": (
                f"/api/v1/shop/{session.id}/stream"
            ),
        }

    # -----------------------------------------------------------------------
    # Get shopping session
    # -----------------------------------------------------------------------

    @app.get(
        "/api/v1/shop/{session_id}",
        tags=["shopping"],
    )
    async def get_shopping_session(
        session_id: str,
    ) -> dict[str, Any]:
        """Get current shopping session state."""

        session = state.session_manager.get_session(
            session_id
        )

        if session is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Session {session_id} not found"
                ),
            )

        return session.model_dump()

    # -----------------------------------------------------------------------
    # SSE stream
    # -----------------------------------------------------------------------

    @app.get(
        "/api/v1/shop/{session_id}/stream",
        tags=["shopping"],
    )
    async def stream_shopping_session(
        session_id: str,
    ) -> EventSourceResponse:
        """SSE stream of shopping workflow events."""

        session = state.session_manager.get_session(
            session_id
        )

        if session is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Session {session_id} not found"
                ),
            )

        async def event_generator():
            async for event in state.event_stream.subscribe(
                session_id
            ):
                yield {
                    "event": event.event_type,
                    "data": json.dumps(
                        event.model_dump(),
                        default=str,
                    ),
                }

        return EventSourceResponse(
            event_generator()
        )

    # -----------------------------------------------------------------------
    # Confirm shopping session
    # -----------------------------------------------------------------------

    @app.post(
        "/api/v1/shop/{session_id}/confirm",
        tags=["shopping"],
    )
    async def confirm_shopping_session(
        session_id: str,
    ) -> dict[str, Any]:
        """Confirm the shopping plan."""

        session = state.session_manager.get_session(
            session_id
        )

        if session is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Session {session_id} not found"
                ),
            )

        if (
            session.state
            != ShoppingSessionState.AWAITING_CONFIRMATION
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Session is in state "
                    f"'{session.state.value}', "
                    "not awaiting confirmation."
                ),
            )

        confirmation_event = (
            state.graph_confirmations.get(
                session_id
            )
        )

        if confirmation_event:
            confirmation_event.set()

        return {
            "session_id": session_id,
            "status": "confirmed",
            "message": (
                "Order confirmed. "
                "Proceeding to checkout."
            ),
        }

    # -----------------------------------------------------------------------
    # Cancel shopping session
    # -----------------------------------------------------------------------

    @app.post(
        "/api/v1/shop/{session_id}/cancel",
        tags=["shopping"],
    )
    async def cancel_shopping_session(
        session_id: str,
    ) -> dict[str, Any]:
        """Cancel a shopping session."""

        session = state.session_manager.get_session(
            session_id
        )

        if session is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Session {session_id} not found"
                ),
            )

        task = state.session_manager._graph_tasks.get(
            session_id
        )

        if task and not task.done():
            task.cancel()

        state.session_manager.update_session(
            session_id,
            state=ShoppingSessionState.FAILED,
            error="Cancelled by user.",
        )

        state.event_stream.close(
            session_id
        )

        return {
            "session_id": session_id,
            "status": "cancelled",
            "message": "Shopping session cancelled.",
        }

    # -----------------------------------------------------------------------
    # Comparison endpoint
    # -----------------------------------------------------------------------

    @app.post(
        "/api/v1/compare",
        tags=["comparison"],
    )
    async def compare_prices(
        req: CompareRequest,
        request: Request,
    ) -> dict[str, Any]:
        """Compare prices across known merchants."""

        country_code, display_currency = await resolve_region(
            country_code=req.country_code,
            accept_language=request.headers.get("accept-language"),
            ip_address=(
                request.client.host
                if request.client
                else None
            ),
            preferred_currency=req.currency,
        )

        discovery = DiscoveryAgent(
            settings
        )

        merchants = await discovery.discover_merchants()

        search_agent = SearchAgent(
            settings
        )

        results = await search_agent.search_all_merchants(
            merchants,
            [req.product_query],
        )

        # Convert prices for the current user region.
        for merchant_id, products in results.items():
            await state.regional_pricing.convert_products(
                products,
                display_currency,
            )

        comparison = ComparisonAgent()

        matrix = await comparison.build_comparison(
            results,
            item_names=[req.product_query],
        )

        matrix = await _regionalize_comparison(
            state.regional_pricing,
            matrix,
            display_currency,
        )

        return {
            **matrix.model_dump(),
            "region": {
                "country_code": country_code,
                "currency": display_currency,
                "symbol": currency_symbol(display_currency),
            },
        }

    # -----------------------------------------------------------------------
    # Optimization endpoint
    # -----------------------------------------------------------------------

    @app.post(
        "/api/v1/optimize",
        tags=["comparison"],
    )
    async def optimize_order(
        req: OptimizeRequest,
    ) -> dict[str, Any]:
        """Run split-order optimization."""

        session = state.session_manager.get_session(
            req.session_id
        )

        if session is None:
            raise HTTPException(
                status_code=404,
                detail="Session not found",
            )

        if session.comparison is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No comparison matrix "
                    "available for this session."
                ),
            )

        optimizer = SplitOrderOptimizer()

        plan = await optimizer.optimize(
            session.comparison,
            session.request.preferences,
        )

        plan = await _convert_optimization_plan(
            state.regional_pricing,
            plan,
            session.request.display_currency,
        )

        state.session_manager.update_session(
            req.session_id,
            optimization_plan=plan,
        )

        return plan.model_dump()

    # -----------------------------------------------------------------------
    # Merchant endpoints
    # -----------------------------------------------------------------------

    @app.get(
        "/api/v1/merchants",
        tags=["merchants"],
    )
    async def list_merchants() -> dict[str, Any]:
        """List all known merchants."""

        if not state.merchants:

            discovery = DiscoveryAgent(
                settings
            )

            merchants = await discovery.discover_merchants()

            for merchant in merchants:
                state.merchants[
                    merchant.id
                ] = merchant

        return {
            "merchants": [
                merchant.model_dump()
                for merchant in state.merchants.values()
            ],
            "total": len(state.merchants),
        }

    # -----------------------------------------------------------------------

    @app.post(
        "/api/v1/merchants/discover",
        tags=["merchants"],
    )
    async def discover_merchants(
        req: DiscoverRequest,
    ) -> dict[str, Any]:
        """Discover new UCP merchants."""

        discovery = DiscoveryAgent(
            settings
        )

        merchants = await discovery.discover_merchants(
            req.urls
        )

        for merchant in merchants:
            state.merchants[
                merchant.id
            ] = merchant

        return {
            "discovered": len(merchants),
            "merchants": [
                merchant.model_dump()
                for merchant in merchants
            ],
        }

    # -----------------------------------------------------------------------

    @app.get(
        "/api/v1/merchants/{merchant_id}/catalog",
        tags=["merchants"],
    )
    async def browse_merchant_catalog(
        merchant_id: str,
        q: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Browse a merchant catalog."""

        merchant = state.merchants.get(
            merchant_id
        )

        if merchant is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Merchant {merchant_id} "
                    "not found"
                ),
            )

        search_agent = SearchAgent(
            settings
        )

        results = await search_agent.search_all_merchants(
            [merchant],
            [q or ""],
            filters=None,
        )

        products = results.get(
            merchant_id,
            [],
        )

        return {
            "merchant_id": merchant_id,
            "merchant_name": merchant.name,
            "products": [
                product.model_dump()
                for product in products[:limit]
            ],
            "total": len(products),
        }

    # -----------------------------------------------------------------------
    # Order endpoints
    # -----------------------------------------------------------------------

    @app.get(
        "/api/v1/orders",
        tags=["orders"],
    )
    async def list_orders() -> dict[str, Any]:
        """List all completed orders."""

        return {
            "orders": [
                order.model_dump()
                for order in state.orders.values()
            ],
            "total": len(state.orders),
        }

    # -----------------------------------------------------------------------

    @app.get(
        "/api/v1/orders/{order_id}",
        tags=["orders"],
    )
    async def get_order(
        order_id: str,
    ) -> dict[str, Any]:
        """Get a specific order."""

        order = state.orders.get(
            order_id
        )

        if order is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Order {order_id} not found"
                ),
            )

        return order.model_dump()

    # -----------------------------------------------------------------------
    # MCP endpoints
    # -----------------------------------------------------------------------

    @app.post(
        "/api/v1/mcp/tools",
        tags=["mcp"],
    )
    async def mcp_list_tools() -> dict[str, Any]:
        """List MCP tools."""

        tools = list_tools()

        return {
            "tools": tools,
            "total": len(tools),
        }

    # -----------------------------------------------------------------------

    @app.post(
        "/api/v1/mcp/tools/{tool_name}/execute",
        tags=["mcp"],
    )
    async def mcp_execute_tool(
        tool_name: str,
        req: ToolExecuteRequest,
    ) -> dict[str, Any]:
        """Execute an MCP tool."""

        result = await mcp_handler.execute(
            tool_name,
            req.arguments,
        )

        return result.model_dump()

    # -----------------------------------------------------------------------
    # Error handler
    # -----------------------------------------------------------------------

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        """Handle unexpected API errors."""

        logger.error(
            "unhandled_exception",
            error=str(exc),
            path=request.url.path,
        )

        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="Internal server error",
                detail=str(exc),
                status_code=500,
            ).model_dump(),
        )

    return app