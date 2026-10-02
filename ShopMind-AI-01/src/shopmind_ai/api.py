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
import time
import secrets
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from fastapi import FastAPI, Header, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from shopmind_ai.services.persistence import PersistenceStore
from shopmind_ai.services.cache import TTLCache
from shopmind_ai.services.intelligence import rank_products, review_summary, price_signal
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
    detect_currency_from_text,
    resolve_region,
    reverse_geocode_coordinates,
)
from shopmind_ai.services.regional_pricing import RegionalPricingService

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ShopRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    budget: float | None = Field(default=None, ge=0, le=100_000_000)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    postal_code: str | None = Field(default=None, max_length=12)
    # Kept only for backward-compatible clients. The server always routes automatically.
    ai_provider: str = "auto"
    preferences: ShoppingPreferences = Field(
        default_factory=ShoppingPreferences
    )
    filters: dict[str, Any] = Field(default_factory=dict)

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

    urls: list[str] = Field(min_length=1, max_length=10)


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
        ttl_seconds: int | None = None,
    ) -> ShoppingSession | None:
        """Retrieve a session and lazily remove expired sessions."""

        session = self._sessions.get(session_id)
        if session is None:
            return None

        if ttl_seconds is not None:
            age = (datetime.now(tz=timezone.utc) - session.updated_at).total_seconds()
            if age > ttl_seconds:
                self._sessions.pop(session_id, None)
                task = self._graph_tasks.pop(session_id, None)
                if task and not task.done():
                    task.cancel()
                return None

        return session

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

        self.graph_confirmations: dict[str, asyncio.Event] = {}
        self.rate_buckets: dict[str, list[float]] = {}
        # Short-lived in-memory capability tokens. Never included in session
        # GET responses or logs.
        self.session_tokens: dict[str, str] = {}
        self.persistence = PersistenceStore(settings.database_path)
        self.cache = TTLCache(settings.cache_ttl_seconds)


# ---------------------------------------------------------------------------
# Session authorization helpers
# ---------------------------------------------------------------------------


def _session_from_request(
    state: AppState,
    session_id: str,
    token: str | None,
) -> ShoppingSession:
    """Return an authorized session or raise a safe HTTP error."""

    session = state.session_manager.get_session(
        session_id,
        ttl_seconds=state.settings.session_ttl_seconds,
    )
    if session is None:
        # Do not reveal whether an expired token/session once existed.
        raise HTTPException(status_code=404, detail="Session not found")

    expected = state.session_tokens.get(session_id)
    if not expected or not token or not secrets.compare_digest(expected, token):
        raise HTTPException(status_code=401, detail="Invalid or missing shopping session token.")

    return session


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


async def _get_plan_budget(
    pricing: RegionalPricingService,
    shopping_request: ShoppingRequest,
    graph_result: dict[str, Any],
) -> float | None:
    """Return the budget converted into the user's display currency."""
    raw_budget = shopping_request.budget
    if raw_budget is None:
        shopping_plan = graph_result.get("shopping_plan")
        if shopping_plan is not None:
            raw_budget = getattr(shopping_plan, "overall_budget", None)

    if raw_budget is None:
        return None

    source_currency = (
        shopping_request.budget_currency or shopping_request.display_currency
    ).upper()
    target_currency = shopping_request.display_currency.upper()

    if source_currency == target_currency:
        return float(raw_budget)

    return await _convert_product_amount(
        pricing,
        amount=float(raw_budget),
        source_currency=source_currency,
        target_currency=target_currency,
    )


def _filter_products_by_local_budget(
    results: dict[str, list[ProductResult]],
    budget: float | None,
) -> dict[str, list[ProductResult]]:
    """Return only products that fit the user's local-currency budget."""
    if budget is None:
        return results

    filtered: dict[str, list[ProductResult]] = {}
    for merchant_id, products in results.items():
        kept: list[ProductResult] = []
        for product in products:
            local_price = product.display_price
            if local_price is None:
                continue
            if 0 < float(local_price) <= float(budget):
                kept.append(product)
        filtered[merchant_id] = kept
    return filtered


def _apply_structured_filters(
    results: dict[str, list[ProductResult]],
    filters: dict[str, Any] | None,
) -> dict[str, list[ProductResult]]:
    """Apply safe server-side filters before comparison/ranking."""
    filters = filters or {}
    min_rating = float(filters.get("min_rating", 0) or 0)
    max_price = filters.get("max_price")
    instant_only = bool(filters.get("instant_only", False))
    verified_only = bool(filters.get("verified_only", False))
    feature = str(filters.get("feature", "")).strip().lower()
    output: dict[str, list[ProductResult]] = {}
    for merchant_id, products in results.items():
        kept = []
        for product in products:
            local_price = product.display_price if product.display_price is not None else product.price
            if min_rating and float(product.rating or 0) < min_rating:
                continue
            if max_price is not None and float(local_price or 0) > float(max_price):
                continue
            if instant_only and not product.specs.get("delivery_window"):
                continue
            if verified_only and not product.verified_source and not product.source_name:
                continue
            if feature:
                haystack = json.dumps(product.model_dump(mode="json")).lower()
                if feature not in haystack:
                    continue
            kept.append(product)
        output[merchant_id] = kept
    return output


def _select_closest_products(
    results: dict[str, list[ProductResult]],
    budget: float,
    *,
    max_products: int = 6,
) -> dict[str, list[ProductResult]]:
    """Select closest real products when no exact budget match exists."""
    candidates: list[tuple[float, str, ProductResult]] = []
    for merchant_id, products in results.items():
        for product in products:
            if product.display_price is None:
                continue
            local_price = float(product.display_price)
            distance = abs(local_price - float(budget))
            candidates.append((distance, merchant_id, product))

    candidates.sort(
        key=lambda item: (
            item[0],
            float(item[2].display_price or 0.0),
            -float(item[2].rating or 0.0),
        )
    )

    selected: dict[str, list[ProductResult]] = {}
    for _, merchant_id, product in candidates[:max_products]:
        selected.setdefault(merchant_id, []).append(product)
    return selected


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
        docs_url="/docs" if settings.environment == "development" else None,
        redoc_url="/redoc" if settings.environment == "development" else None,
    )

    # -----------------------------------------------------------------------
    # CORS
    # -----------------------------------------------------------------------

    allowed_origins = [
        origin.strip()
        for origin in settings.allowed_origins.split(",")
        if origin.strip()
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Accept",
            "Authorization",
            "X-ShopMind-Session-Token",
            "X-ShopMind-User-Id",
            "X-Admin-Key",
        ],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(self)",
        )
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' https:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        return response

    # -----------------------------------------------------------------------
    # Shared state
    # -----------------------------------------------------------------------

    state = AppState(settings)

    app.state.app_state = state
    app.state.settings = settings

    mcp_handler = MCPToolHandler(state)

    async def _price_alert_worker() -> None:
        """Periodically re-check tracked products when web search is configured."""
        if not settings.tavily_api_key:
            return
        searcher = __import__("shopmind_ai.services.regional_search", fromlist=["RegionalSearch"]).RegionalSearch(settings.tavily_api_key, max_results_per_source=3)
        while True:
            try:
                alerts = state.persistence.alerts()
                for alert in alerts:
                    product = json.loads(alert.get("product_json") or "{}")
                    query = product.get("name") or product.get("description") or "product"
                    country = product.get("country_code") or "IN"
                    currency = alert.get("currency") or product.get("display_currency") or "USD"
                    results = await searcher.search(query, country_code=country, display_currency=currency, instant_only=False)
                    if not results:
                        continue
                    current = min((p.display_price for p in results if p.display_price is not None), default=None)
                    target = alert.get("target_price")
                    if current is not None and target is not None and current <= float(target):
                        state.persistence.update_alert(int(alert["id"]), current, active=False, triggered=True)
                        state.persistence.event("price_alert_triggered", {"alert_id": alert["id"], "user_id": alert["user_id"], "price": current, "target": target, "product": query})
                    elif current is not None:
                        state.persistence.update_alert(int(alert["id"]), current)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("price_alert_worker_error", error=str(exc))
            await asyncio.sleep(max(300, settings.price_alert_interval_seconds))

    @app.on_event("startup")
    async def start_background_workers() -> None:
        app.state.price_alert_task = asyncio.create_task(_price_alert_worker())

    @app.on_event("shutdown")
    async def stop_background_workers() -> None:
        task = getattr(app.state, "price_alert_task", None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

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

    def _check_rate_limit(client_ip: str | None) -> None:
        """Apply a small in-memory abuse guard to session creation."""
        key = client_ip or "unknown"
        now = time.monotonic()
        bucket = state.rate_buckets.setdefault(key, [])
        cutoff = now - 60.0
        bucket[:] = [stamp for stamp in bucket if stamp > cutoff]
        if len(bucket) >= settings.rate_limit_per_minute:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please try again shortly.",
                headers={"Retry-After": "60"},
            )
        bucket.append(now)

    @app.get(
        "/api/v1/location/resolve",
        tags=["location"],
    )
    async def resolve_live_location(
        request: Request,
        latitude: float = Query(..., ge=-90, le=90),
        longitude: float = Query(..., ge=-180, le=180),
    ) -> dict[str, Any]:
        """Resolve browser coordinates into a coarse shopping region.

        Coordinates are used transiently and are not persisted. The endpoint
        returns only coarse country/city context needed for regional search.
        """
        client_ip = request.client.host if request.client else None
        _check_rate_limit(client_ip)
        location = await reverse_geocode_coordinates(latitude, longitude)
        if not location:
            raise HTTPException(status_code=404, detail="Unable to resolve live location.")
        country, currency = await resolve_region(country_code=location["country_code"])
        return {
            "country_code": country,
            "currency": currency,
            "symbol": currency_symbol(currency),
            "label": location.get("label", ""),
            "city": location.get("city", ""),
            "region": location.get("region", ""),
            "postal_code": location.get("postal_code", ""),
            "instant_sources_available": bool(
                country == "IN"
            ),
        }

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

        client_ip = request.client.host if request.client else None
        _check_rate_limit(client_ip)

        query = " ".join(req.query.split())
        if not query:
            raise HTTPException(status_code=422, detail="Shopping query cannot be empty.")
        if any(ord(ch) < 32 and ch not in "\t" for ch in query):
            raise HTTPException(status_code=422, detail="Shopping query contains invalid characters.")
        if len(query) > settings.max_query_length:
            raise HTTPException(status_code=413, detail="Shopping query is too long.")

        # ---------------------------------------------------------------
        # Resolve region/currency. Browser live coordinates have priority
        # over coarse IP geolocation when the user explicitly grants access.
        # ---------------------------------------------------------------
        live_location = None
        if req.latitude is not None and req.longitude is not None:
            live_location = await reverse_geocode_coordinates(
                req.latitude,
                req.longitude,
            )

        location_country = (
            live_location.get("country_code")
            if live_location
            else None
        ) or req.country_code

        country_code, display_currency = await resolve_region(
            country_code=location_country,
            accept_language=request.headers.get("accept-language"),
            ip_address=client_ip,
            preferred_currency=req.currency,
        )

        display_symbol = currency_symbol(display_currency)
        detected_budget_currency = detect_currency_from_text(query) or display_currency

        budget = (
            Decimal(str(req.budget))
            if req.budget is not None
            else None
        )

        shopping_req = ShoppingRequest(
            query=query,
            budget=budget,
            budget_currency=detected_budget_currency,
            country_code=country_code,
            display_currency=display_currency,
            currency_symbol=display_symbol,
            latitude=req.latitude,
            longitude=req.longitude,
            location_label=(
                " ".join(
                    x for x in (
                        (live_location or {}).get("label", ""),
                        (live_location or {}).get("postal_code", ""),
                    ) if x
                )
                if live_location
                else ""
            ),
            postal_code=(req.postal_code or (live_location or {}).get("postal_code", "")) if live_location or req.postal_code else "",
            location_source=("browser" if live_location else ("manual_pincode" if req.postal_code else "ip_or_locale")),
            instant_delivery_requested=bool(
                __import__("re").search(
                    r"\b(?:instant|quick|same\s*day|10\s*(?:-|to)\s*30\s*min|minutes?|urgent|fast delivery|deliver (?:it )?now)\b",
                    query,
                    __import__("re").IGNORECASE,
                )
            ),
            ai_provider="auto",
            preferences=req.preferences,
            user_id=request.headers.get("X-ShopMind-User-Id", "guest")[:128],
            filters=req.filters,
        )

        session = await state.session_manager.create_session(
            shopping_req
        )
        state.persistence.record_search(
            shopping_req.user_id, session.id, shopping_req.query, country_code, display_currency
        )

        session_token = secrets.token_urlsafe(32)
        state.session_tokens[session.id] = session_token

        confirmation_event = asyncio.Event()

        state.graph_confirmations[
            session.id
        ] = confirmation_event

        # -------------------------------------------------------------------
        # Background graph runner
        # -------------------------------------------------------------------
        async def _run_graph() -> None:
            """Execute the shopping graph with live session persistence."""

            async def persist_snapshot(
                snapshot: dict[str, Any],
                *,
                fallback_state: ShoppingSessionState,
            ) -> None:
                """Persist every intermediate LangGraph snapshot immediately."""

                if not snapshot:
                    return

                current_state = snapshot.get(
                    "current_state",
                    fallback_state,
                )

                if isinstance(current_state, str):
                    try:
                        current_state = ShoppingSessionState(
                            current_state
                        )
                    except ValueError:
                        current_state = fallback_state

                request_from_graph = snapshot.get(
                    "request",
                    shopping_req,
                )

                # Keep the planner-detected budget/currency in the session.
                state.session_manager.update_session(
                    session.id,
                    request=request_from_graph,
                    state=current_state,
                    merchants=snapshot.get(
                        "discovered_merchants",
                        [],
                    ),
                    search_results=snapshot.get(
                        "search_results",
                        {},
                    ),
                    comparison=snapshot.get(
                        "comparison_matrix",
                    ),
                    optimization_plan=snapshot.get(
                        "optimization_plan",
                    ),
                    orders=snapshot.get(
                        "completed_orders",
                        [],
                    ),
                    error=snapshot.get("error"),
                )

                # Also keep the global merchant registry updated.
                for merchant in snapshot.get(
                    "discovered_merchants",
                    [],
                ):
                    state.merchants[merchant.id] = merchant

                logger.info(
                    "shopping_snapshot_persisted",
                    session_id=session.id,
                    state=str(current_state),
                    budget=str(
                        getattr(
                            request_from_graph,
                            "budget",
                            None,
                        )
                    ),
                    merchants=len(
                        snapshot.get(
                            "discovered_merchants",
                            [],
                        )
                    ),
                    products=sum(
                        len(products)
                        for products in snapshot.get(
                            "search_results",
                            {},
                        ).values()
                    ),
                )

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

                # -----------------------------------------------------------
                # IMPORTANT:
                # Use astream(values) instead of ainvoke().
                #
                # This lets us receive every intermediate graph state and
                # immediately update the REST session.
                # -----------------------------------------------------------
                logger.info(
                    "shopping_graph_streaming",
                    session_id=session.id,
                )

                result: dict[str, Any] = initial

                async for snapshot in compiled.astream(
                    initial,
                    stream_mode="values",
                ):
                    if not isinstance(snapshot, dict):
                        continue

                    result = snapshot

                    await persist_snapshot(
                        snapshot,
                        fallback_state=ShoppingSessionState.PLANNING,
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
                # -----------------------------------------------------------

                regional_results = result.get(
                    "search_results",
                    {},
                )
                all_regional_results = {
                    merchant_id: list(products)
                    for merchant_id, products in regional_results.items()
                }

                for merchant_id, products in regional_results.items():
                    await state.regional_pricing.convert_products(
                        products,
                        shopping_req.display_currency,
                    )

                # Planner may have extracted the budget from the query.
                # Read it from the latest graph request/plan.
                graph_request = result.get(
                    "request",
                    shopping_req,
                )

                budget_limit = await _get_plan_budget(
                    state.regional_pricing,
                    graph_request,
                    result,
                )

                regional_results = _filter_products_by_local_budget(
                    regional_results,
                    budget_limit,
                )

                regional_results = _apply_structured_filters(
                    regional_results,
                    graph_request.filters,
                )

                result["search_results"] = regional_results

                closest_match_mode = False
                if not any(regional_results.values()) and budget_limit is not None:
                    closest_results = _select_closest_products(
                        all_regional_results,
                        budget_limit,
                        max_products=6,
                    )
                    if any(closest_results.values()):
                        regional_results = closest_results
                        result["search_results"] = regional_results
                        closest_match_mode = True
                        result["error"] = None

                # -----------------------------------------------------------
                # Rebuild comparison using products inside local budget.
                # -----------------------------------------------------------

                if any(regional_results.values()):
                    comparison_agent = ComparisonAgent()

                    product_names: list[str] = []

                    shopping_plan = result.get(
                        "shopping_plan",
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
                        product_names = [
                            graph_request.query
                        ]

                    comparison_matrix = (
                        await comparison_agent.build_comparison(
                            regional_results,
                            item_names=product_names,
                        )
                    )

                    comparison_matrix = (
                        await _regionalize_comparison(
                            state.regional_pricing,
                            comparison_matrix,
                            graph_request.display_currency,
                        )
                    )

                    result["comparison_matrix"] = (
                        comparison_matrix
                    )

                    # -------------------------------------------------------
                    # Optimize only products inside user's local budget.
                    # -------------------------------------------------------

                    optimizer = SplitOrderOptimizer()

                    optimization_plan = (
                        await optimizer.optimize(
                            comparison_matrix,
                            graph_request.preferences,
                        )
                    )

                    optimization_plan = (
                        await _convert_optimization_plan(
                            state.regional_pricing,
                            optimization_plan,
                            graph_request.display_currency,
                        )
                    )

                    if closest_match_mode:
                        note = (
                            "No exact product was found within "
                            f"{graph_request.currency_symbol}{budget_limit:,.2f} "
                            f"{graph_request.display_currency}. "
                            "Showing the closest available real products; "
                            "prices have not been changed."
                        )
                        optimization_plan.reasoning = (
                            f"{note} {optimization_plan.reasoning}"
                        ).strip()

                    result["optimization_plan"] = optimization_plan

                else:
                    # -------------------------------------------------------
                    # No exact product inside budget.
                    #
                    # For now mark failed. The next layer can add closest
                    # product recommendations without changing this flow.
                    # -------------------------------------------------------
                    result["comparison_matrix"] = None
                    result["optimization_plan"] = None

                    if budget_limit is not None:
                        result["current_state"] = (
                            ShoppingSessionState.FAILED
                        )

                        result["error"] = (
                            "No products were found within the "
                            f"local budget of "
                            f"{graph_request.currency_symbol}"
                            f"{budget_limit:,.2f} "
                            f"{graph_request.display_currency}."
                        )

                # Deterministic ranking, review intelligence and price signals.
                all_products_flat = [p for batch in regional_results.values() for p in batch]
                ranked = rank_products(all_products_flat, graph_request.query, budget_limit)
                for product in ranked:
                    product.verified_source = bool(product.url and product.source_name)
                    product.review_summary = review_summary(product)
                    product.best_for = []
                    if product.rating >= 4.5: product.best_for.append("Top Rated")
                    if product.display_price is not None and budget_limit is not None and product.display_price <= budget_limit: product.best_for.append("Budget Fit")
                    if product.specs.get("delivery_window"): product.best_for.append("Fastest Delivery")
                    history = state.persistence.price_history(state.persistence.fingerprint(product.model_dump(mode="json")))
                    product.price_signal = price_signal(history, product.display_price)
                    if product.specs.get("delivery_window"):
                        match = __import__("re").search(r"(\d+)[-–](\d+)\s*min", product.specs.get("delivery_window", ""))
                        if match: product.eta_minutes = int(match.group(1)); product.delivery_status = "indicative"
                state.persistence.save_products([p.model_dump(mode="json") for p in ranked])

                # -----------------------------------------------------------
                # Persist final pre-confirmation result.
                # -----------------------------------------------------------

                if closest_match_mode:
                    result["current_state"] = ShoppingSessionState.AWAITING_CONFIRMATION

                current_state = result.get(
                    "current_state",
                    ShoppingSessionState.FAILED,
                )

                state.session_manager.update_session(
                    session.id,
                    request=result.get(
                        "request",
                        graph_request,
                    ),
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
                    orders=result.get(
                        "completed_orders",
                        [],
                    ),
                    error=result.get("error"),
                )

                # Store merchants.
                for merchant in result.get(
                    "discovered_merchants",
                    [],
                ):
                    state.merchants[merchant.id] = merchant

                # -----------------------------------------------------------
                # Confirmation gate
                # -----------------------------------------------------------

                if (
                    current_state
                    == ShoppingSessionState.AWAITING_CONFIRMATION
                ):
                    requires_confirmation = (
                        settings.human_confirmation_required
                        or closest_match_mode
                    )

                    if requires_confirmation:
                        logger.info(
                            "awaiting_confirmation",
                            session_id=session.id,
                        )

                        await confirmation_event.wait()

                        logger.info(
                            "confirmation_received",
                            session_id=session.id,
                        )

                    result["user_confirmed"] = True

                    logger.info(
                        "shopping_graph_resuming",
                        session_id=session.id,
                    )

                    # -------------------------------------------------------
                    # Resume graph and persist every checkout snapshot too.
                    # -------------------------------------------------------

                    final_result: dict[str, Any] = result

                    async for snapshot in compiled.astream(
                        result,
                        stream_mode="values",
                    ):
                        if not isinstance(snapshot, dict):
                            continue

                        final_result = snapshot

                        await persist_snapshot(
                            snapshot,
                            fallback_state=(
                                ShoppingSessionState.CHECKING_OUT
                            ),
                        )

                    final_state = final_result.get(
                        "current_state",
                        ShoppingSessionState.COMPLETED,
                    )

                    orders = final_result.get(
                        "completed_orders",
                        [],
                    )

                    state.session_manager.update_session(
                        session.id,
                        request=final_result.get(
                            "request",
                            graph_request,
                        ),
                        state=final_state,
                        orders=orders,
                        merchants=final_result.get(
                            "discovered_merchants",
                            [],
                        ),
                        search_results=final_result.get(
                            "search_results",
                            {},
                        ),
                        comparison=final_result.get(
                            "comparison_matrix",
                        ),
                        optimization_plan=final_result.get(
                            "optimization_plan",
                        ),
                        error=final_result.get("error"),
                    )

                    for order in orders:
                        state.orders[order.order_id] = order

                    logger.info(
                        "shopping_graph_completed",
                        session_id=session.id,
                        state=str(final_state),
                        orders=len(orders),
                    )

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

            except Exception as exc:
                logger.exception(
                    "shopping_graph_failed",
                    session_id=session.id,
                    error=str(exc),
                )

                state.session_manager.update_session(
                    session.id,
                    state=ShoppingSessionState.FAILED,
                    error="The shopping workflow failed unexpectedly. Please retry.",
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

        def _forget_task(_completed: asyncio.Task[Any]) -> None:
            state.session_manager._graph_tasks.pop(
                session.id,
                None,
            )

        task.add_done_callback(_forget_task)

        # -------------------------------------------------------------------
        # Return immediately
        # -------------------------------------------------------------------

        return {
            "session_id": session.id,
            "session_token": session_token,
            "status": session.state.value,
            "message": (
                f"Shopping session created for: {req.query}"
            ),
            "stream_url": (
                f"/api/v1/shop/{session.id}/stream"
            ),
        }

    def _require_session_token(
        session_id: str,
        provided_token: str | None,
    ) -> None:
        """Authorize access to a private shopping session."""

        expected = state.session_tokens.get(session_id)
        if not expected or not provided_token or not secrets.compare_digest(
            expected,
            provided_token,
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing shopping session token.",
            )

    # -----------------------------------------------------------------------
    # Get shopping session
    # -----------------------------------------------------------------------

    @app.get(
        "/api/v1/shop/{session_id}",
        tags=["shopping"],
    )
    async def get_shopping_session(
        session_id: str,
        x_shopmind_session_token: str | None = Header(default=None, alias="X-ShopMind-Session-Token"),
    ) -> dict[str, Any]:
        """Get current shopping session state."""

        session = state.session_manager.get_session(
            session_id,
            ttl_seconds=settings.session_ttl_seconds,
        )

        if session is None:
            raise HTTPException(
                status_code=404,
                detail="Session not found",
            )

        _require_session_token(
            session_id,
            x_shopmind_session_token,
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
        x_shopmind_session_token: str | None = Header(default=None, alias="X-ShopMind-Session-Token"),
    ) -> EventSourceResponse:
        """SSE stream of shopping workflow events."""

        session = state.session_manager.get_session(
            session_id,
            ttl_seconds=settings.session_ttl_seconds,
        )

        if session is None:
            raise HTTPException(
                status_code=404,
                detail="Session not found",
            )

        _require_session_token(
            session_id,
            x_shopmind_session_token,
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
        x_shopmind_session_token: str | None = Header(default=None, alias="X-ShopMind-Session-Token"),
    ) -> dict[str, Any]:
        """Confirm the shopping plan."""

        session = state.session_manager.get_session(
            session_id,
            ttl_seconds=settings.session_ttl_seconds,
        )

        if session is None:
            raise HTTPException(
                status_code=404,
                detail="Session not found",
            )

        _require_session_token(
            session_id,
            x_shopmind_session_token,
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
        x_shopmind_session_token: str | None = Header(default=None, alias="X-ShopMind-Session-Token"),
    ) -> dict[str, Any]:
        """Cancel a shopping session."""

        session = state.session_manager.get_session(
            session_id,
            ttl_seconds=settings.session_ttl_seconds,
        )

        if session is None:
            raise HTTPException(
                status_code=404,
                detail="Session not found",
            )

        _require_session_token(
            session_id,
            x_shopmind_session_token,
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
        state.session_tokens.pop(session_id, None)

        return {
            "session_id": session_id,
            "status": "cancelled",
            "message": "Shopping session cancelled.",
        }

    @app.post("/api/v1/auth/register", tags=["auth"])
    async def register_user(payload: dict[str, Any]):
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        if "@" not in email or len(password) < 8:
            raise HTTPException(status_code=422, detail="Use a valid email and a password of at least 8 characters.")
        try:
            user_id = state.persistence.create_user(email, password)
        except Exception:
            raise HTTPException(status_code=409, detail="An account with this email already exists.")
        token = secrets.token_urlsafe(32)
        state.session_tokens[f"user:{token}"] = user_id
        return {"user_id": user_id, "access_token": token}

    @app.post("/api/v1/auth/login", tags=["auth"])
    async def login_user(payload: dict[str, Any]):
        user_id = state.persistence.authenticate_user(str(payload.get("email", "")), str(payload.get("password", "")))
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        token = secrets.token_urlsafe(32)
        state.session_tokens[f"user:{token}"] = user_id
        return {"user_id": user_id, "access_token": token}

    @app.get("/api/v1/auth/me", tags=["auth"])
    async def auth_me(authorization: str | None = Header(default=None)):
        token = authorization.removeprefix("Bearer ").strip() if authorization else ""
        user_id = state.session_tokens.get(f"user:{token}")
        if not user_id:
            raise HTTPException(status_code=401, detail="Not authenticated.")
        return state.persistence.user_by_id(user_id)

    # -----------------------------------------------------------------------
    # User intelligence endpoints: wishlist, alerts, price history, chat
    # -----------------------------------------------------------------------

    @app.get("/api/v1/wishlist", tags=["user"])
    async def get_wishlist(x_shopmind_user_id: str = Header(default="guest", alias="X-ShopMind-User-Id")):
        return {"items": state.persistence.wishlist(x_shopmind_user_id[:128])}

    @app.post("/api/v1/wishlist", tags=["user"])
    async def add_wishlist(product: dict[str, Any], x_shopmind_user_id: str = Header(default="guest", alias="X-ShopMind-User-Id")):
        state.persistence.wishlist_add(x_shopmind_user_id[:128], product)
        return {"status": "saved", "items": state.persistence.wishlist(x_shopmind_user_id[:128])}

    @app.delete("/api/v1/wishlist/{fingerprint}", tags=["user"])
    async def remove_wishlist(fingerprint: str, x_shopmind_user_id: str = Header(default="guest", alias="X-ShopMind-User-Id")):
        state.persistence.wishlist_remove(x_shopmind_user_id[:128], fingerprint)
        return {"status": "removed"}

    @app.get("/api/v1/products/price-history", tags=["products"])
    async def get_price_history(fingerprint: str, limit: int = Query(30, ge=1, le=365)):
        return {"fingerprint": fingerprint, "history": state.persistence.price_history(fingerprint, limit)}

    @app.post("/api/v1/alerts", tags=["alerts"])
    async def create_price_alert(product: dict[str, Any], target_price: float | None = None, x_shopmind_user_id: str = Header(default="guest", alias="X-ShopMind-User-Id")):
        alert_id = state.persistence.alert_add(x_shopmind_user_id[:128], product, target_price)
        return {"alert_id": alert_id, "status": "active"}

    @app.get("/api/v1/alerts", tags=["alerts"])
    async def list_price_alerts(x_shopmind_user_id: str = Header(default="guest", alias="X-ShopMind-User-Id")):
        return {"alerts": state.persistence.alerts(x_shopmind_user_id[:128])}

    @app.post("/api/v1/shop/chat", tags=["shopping"])
    async def conversational_search(payload: dict[str, Any], request: Request):
        message = " ".join(str(payload.get("message", "")).split())
        if not message or len(message) > settings.max_query_length:
            raise HTTPException(status_code=422, detail="Message is empty or too long.")
        # Deterministic clarification engine; the full LLM planner still handles the actual shopping plan.
        lower = message.lower()
        missing = []
        if not re.search(r"\b(?:under|below|less than|within)\s*(?:₹|rs\.?|inr|\$|usd|£|gbp|€|eur)?\s*\d", lower):
            missing.append("budget")
        if any(term in lower for term in ("earbuds", "headphones", "laptop", "phone")) and not any(term in lower for term in ("cheap", "best", "anc", "battery", "gaming", "camera")):
            missing.append("priority")
        return {"message": message, "needs_clarification": missing, "suggestions": ["Add a budget", "Add a must-have feature", "Ask for fastest delivery"] if missing else [], "normalized_query": message}

    @app.get("/api/v1/admin/stats", tags=["admin"])
    async def admin_stats(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")):
        if not settings.admin_api_key or not x_admin_key or not secrets.compare_digest(settings.admin_api_key, x_admin_key):
            raise HTTPException(status_code=403, detail="Admin access is disabled or unauthorized.")
        return state.persistence.stats()

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
        x_shopmind_session_token: str | None = Header(default=None, alias="X-ShopMind-Session-Token"),
    ) -> dict[str, Any]:
        """Run split-order optimization."""

        session = _session_from_request(
            state,
            req.session_id,
            x_shopmind_session_token,
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

        if not settings.allow_external_merchant_discovery:
            raise HTTPException(
                status_code=403,
                detail="External merchant discovery is disabled by default.",
            )

        discovery = DiscoveryAgent(settings)
        merchants = await discovery.discover_merchants(req.urls)

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
                detail="An unexpected server error occurred.",
                status_code=500,
            ).model_dump(),
        )

    return app