"""Main LangGraph StateGraph for the ShopMind shopping workflow.

Nodes
-----
plan       -- LLM parses the query into a structured shopping plan
discover   -- Fetch ``/.well-known/ucp`` from candidate merchants
search     -- Parallel product search across discovered merchants
compare    -- Build a price/shipping comparison matrix
recommend  -- AI-powered product recommendations
optimize   -- Split-order optimization across merchants
present    -- Prepare the human-readable summary
wait       -- Human-in-the-loop confirmation gate
checkout   -- Execute checkouts at selected merchants
complete   -- Finalize orders and emit completion event

Edges
-----
plan -> discover
discover -> search | fail
search -> compare
compare -> recommend
recommend -> optimize
optimize -> present
present -> wait
wait -> checkout | fail
checkout -> complete
"""

from __future__ import annotations

import structlog
from langgraph.graph import END, StateGraph

from shopmind_ai.agents.checkout_agent import CheckoutAgent
from shopmind_ai.agents.comparison_agent import ComparisonAgent
from shopmind_ai.agents.discovery_agent import DiscoveryAgent
from shopmind_ai.agents.optimizer import SplitOrderOptimizer
from shopmind_ai.agents.recommendation_agent import RecommendationAgent
from shopmind_ai.agents.search_agent import SearchAgent
from shopmind_ai.config import Settings
from shopmind_ai.models import ShoppingSessionState
from shopmind_ai.orchestrator.planner import ShoppingPlanner
from shopmind_ai.orchestrator.state import ShoppingGraphState
from shopmind_ai.streaming import (
    EVENT_AWAITING_CONFIRMATION,
    EVENT_CHECKING_OUT,
    EVENT_COMPARING,
    EVENT_COMPARISON_READY,
    EVENT_COMPLETED,
    EVENT_ERROR,
    EVENT_MERCHANTS_DISCOVERED,
    EVENT_OPTIMIZING,
    EVENT_OPTIMIZATION_READY,
    EVENT_PLANNING,
    EVENT_PRODUCTS_FOUND,
    EVENT_SEARCHING,
    ShoppingEventStream,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Node factories
# ---------------------------------------------------------------------------


def _make_plan_node(
    planner: ShoppingPlanner,
    stream: ShoppingEventStream,
):
    """Create the plan node."""

    async def plan_node(
        state: ShoppingGraphState,
    ) -> ShoppingGraphState:
        """Parse the shopping query into a structured plan."""

        session_id = state.get("session_id", "")
        request = state["request"]

        await stream.emit(
            session_id,
            EVENT_PLANNING,
            message="Analyzing your shopping request...",
        )

        try:
            plan = await planner.plan(request.query, request.ai_provider)

            # Propagate the planner-extracted budget back to the top-level
            # request so the API/session, regional pricing, and filtering
            # layers all see the same budget.
            if (
                request.budget is None
                and plan.overall_budget is not None
            ):
                request.budget = plan.overall_budget
                logger.info(
                    "budget_propagated_to_request",
                    session_id=session_id,
                    budget=str(request.budget),
                    budget_currency=getattr(
                        request,
                        "budget_currency",
                        None,
                    ),
                    display_currency=getattr(
                        request,
                        "display_currency",
                        None,
                    ),
                )

            item_names = [
                item.name
                for item in plan.items
            ]

            await stream.emit(
                session_id,
                EVENT_PLANNING,
                data={
                    "items": item_names,
                    "reasoning": plan.reasoning,
                },
                message=(
                    f"Found {len(plan.items)} item(s) "
                    f"to search for: {', '.join(item_names)}"
                ),
            )

            return {
                **state,
                "shopping_plan": plan,
                "current_state": ShoppingSessionState.DISCOVERING,
                "error": None,
                "messages": state.get("messages", [])
                + [
                    {
                        "role": "system",
                        "content": f"Plan: {plan.reasoning}",
                    }
                ],
            }

        except Exception as exc:
            logger.exception("plan_node_error")

            await stream.emit(
                session_id,
                EVENT_ERROR,
                message="Planning failed. Please retry the search.",
            )

            return {
                **state,
                "error": f"Planning failed: {exc}",
            }

    return plan_node


def _make_discover_node(
    discovery: DiscoveryAgent,
    stream: ShoppingEventStream,
):
    """Create the discover node."""

    async def discover_node(
        state: ShoppingGraphState,
    ) -> ShoppingGraphState:
        session_id = state.get("session_id", "")

        await stream.emit(
            session_id,
            EVENT_MERCHANTS_DISCOVERED,
            message="Discovering UCP merchants...",
        )

        try:
            merchants, failed = (
                await discovery.discover_merchants_with_failures()
            )

            logger.info(
                "ucp_discovery_complete",
                session_id=session_id,
                discovered=len(merchants),
                failed=len(failed),
                merchant_ids=[m.id for m in merchants],
            )

            await stream.emit(
                session_id,
                EVENT_MERCHANTS_DISCOVERED,
                data={
                    "merchants": [
                        merchant.name
                        for merchant in merchants
                    ],
                    "failed": failed,
                },
                message=(
                    f"Discovered {len(merchants)} merchant(s)."
                ),
            )

            return {
                **state,
                "discovered_merchants": merchants,
                "failed_merchants": failed,
                "current_state": (
                    ShoppingSessionState.SEARCHING
                    if merchants
                    else ShoppingSessionState.FAILED
                ),
                "error": (
                    None
                    if merchants
                    else "No merchants discovered."
                ),
            }

        except Exception as exc:
            logger.exception(
                "discover_node_error"
            )

            await stream.emit(
                session_id,
                EVENT_ERROR,
                message="Merchant discovery failed. Please retry the search.",
            )

            return {
                **state,
                "discovered_merchants": [],
                "failed_merchants": [],
                "error": f"Discovery failed: {exc}",
            }

    return discover_node


def _make_search_node(
    search_agent: SearchAgent,
    stream: ShoppingEventStream,
):
    """Create the search node."""

    async def search_node(
        state: ShoppingGraphState,
    ) -> ShoppingGraphState:
        session_id = state.get("session_id", "")
        merchants = state.get(
            "discovered_merchants",
            [],
        )
        plan = state.get("shopping_plan")

        if not plan or not plan.items:
            return {
                **state,
                "current_state": ShoppingSessionState.FAILED,
                "error": "No shopping plan available.",
            }

        queries: list[str] = []

        for item in plan.items:
            if item.keywords:
                queries.append(
                    " ".join(item.keywords)
                )
            else:
                queries.append(item.name)

        await stream.emit(
            session_id,
            EVENT_SEARCHING,
            data={
                "queries": queries,
                "merchant_count": len(merchants),
            },
            message=(
                f"Searching {len(merchants)} merchant(s) "
                f"for {len(queries)} item(s)..."
            ),
        )

        try:
            results = await search_agent.search_all_merchants(
                merchants,
                queries,
                request=state.get("request"),
            )

            total_products = sum(
                len(product_list)
                for product_list in results.values()
            )

            merged = []

            for product_list in results.values():
                merged.extend(product_list)

            await stream.emit(
                session_id,
                EVENT_PRODUCTS_FOUND,
                data={
                    "total_products": total_products,
                    "per_merchant": {
                        key: len(value)
                        for key, value in results.items()
                    },
                },
                message=(
                    f"Found {total_products} product(s) "
                    f"across {len(results)} merchant(s)."
                ),
            )

            return {
                **state,
                "search_results": results,
                "merged_results": merged,
                "current_state": ShoppingSessionState.COMPARING,
                "error": None,
            }

        except Exception as exc:
            logger.exception(
                "search_node_error"
            )

            await stream.emit(
                session_id,
                EVENT_ERROR,
                message="Product search failed. Please retry the search.",
            )

            return {
                **state,
                "current_state": ShoppingSessionState.FAILED,
                "error": "Search failed. Please retry the search.",
            }

    return search_node


def _make_compare_node(
    comparison: ComparisonAgent,
    stream: ShoppingEventStream,
):
    """Create the compare node."""

    async def compare_node(
        state: ShoppingGraphState,
    ) -> ShoppingGraphState:
        session_id = state.get("session_id", "")
        search_results = state.get(
            "search_results",
            {},
        )
        plan = state.get("shopping_plan")

        shopping_items = plan.items if plan else []

        await stream.emit(
            session_id,
            EVENT_COMPARING,
            message="Building price comparison matrix...",
        )

        try:
            matrix = await comparison.build_comparison(
                search_results,
                shopping_items,
            )

            await stream.emit(
                session_id,
                EVENT_COMPARISON_READY,
                data={
                    "entries": len(matrix.entries),
                    "total_products": (
                        matrix.total_products_found
                    ),
                },
                message=(
                    f"Comparison ready: "
                    f"{len(matrix.entries)} item(s) compared."
                ),
            )

            return {
                **state,
                "comparison_matrix": matrix,
                "current_state": ShoppingSessionState.OPTIMIZING,
                "error": None,
            }

        except Exception as exc:
            logger.exception(
                "compare_node_error"
            )

            await stream.emit(
                session_id,
                EVENT_ERROR,
                message="Comparison failed. Please retry the search.",
            )

            return {
                **state,
                "current_state": ShoppingSessionState.FAILED,
                "error": "Comparison failed. Please retry the search.",
            }

    return compare_node


# ---------------------------------------------------------------------------
# AI Recommendation
# ---------------------------------------------------------------------------


def _make_recommendation_node(
    recommendation_agent: RecommendationAgent,
    stream: ShoppingEventStream,
):
    """Create the AI recommendation node."""

    async def recommendation_node(
        state: ShoppingGraphState,
    ) -> ShoppingGraphState:
        session_id = state.get("session_id", "")
        plan = state.get("shopping_plan")
        comparison = state.get("comparison_matrix")

        if not plan:
            return {
                **state,
                "current_state": ShoppingSessionState.FAILED,
                "error": "No shopping plan available for recommendation.",
            }

        if not comparison:
            return {
                **state,
                "current_state": ShoppingSessionState.FAILED,
                "error": "No comparison matrix available for recommendation.",
            }

        await stream.emit(
            session_id,
            EVENT_COMPARING,
            message="AI is analyzing the best products for you...",
        )

        try:
            recommendations = (
                await recommendation_agent.recommend(
                    plan,
                    comparison,
                )
            )

            await stream.emit(
                session_id,
                EVENT_COMPARISON_READY,
                data={
                    "recommendations": recommendations,
                },
                message=(
                    "AI recommendations are ready."
                ),
            )

            return {
                **state,
                "recommendations": recommendations,
                "error": None,
            }

        except Exception as exc:
            logger.exception(
                "recommendation_node_error"
            )

            await stream.emit(
                session_id,
                EVENT_ERROR,
                message="AI recommendation failed. Please retry the search.",
            )

            return {
                **state,
                "recommendations": None,
                "current_state": ShoppingSessionState.FAILED,
                "error": "AI recommendation failed. Please retry the search.",
            }

    return recommendation_node


def _make_optimize_node(
    optimizer: SplitOrderOptimizer,
    stream: ShoppingEventStream,
):
    """Create the optimize node."""

    async def optimize_node(
        state: ShoppingGraphState,
    ) -> ShoppingGraphState:
        session_id = state.get("session_id", "")
        matrix = state.get(
            "comparison_matrix"
        )
        preferences = state.get(
            "preferences"
        )

        if not matrix:
            return {
                **state,
                "current_state": ShoppingSessionState.FAILED,
                "error": (
                    "No comparison matrix available."
                ),
            }

        await stream.emit(
            session_id,
            EVENT_OPTIMIZING,
            message=(
                "Optimizing purchase "
                "across merchants..."
            ),
        )

        try:
            plan = await optimizer.optimize(
                matrix,
                preferences,
            )

            await stream.emit(
                session_id,
                EVENT_OPTIMIZATION_READY,
                data={
                    "grand_total": plan.grand_total,
                    "merchants_used": plan.merchants_used,
                    "savings": plan.savings_vs_single,
                },
                message=(
                    f"Optimization complete: "
                    f"{plan.currency_symbol}{plan.grand_total:.2f} total "
                    f"across {plan.merchants_used} merchant(s). "
                    f"Savings: "
                    f"{plan.currency_symbol}{plan.savings_vs_single:.2f}"
                ),
            )

            return {
                **state,
                "optimization_plan": plan,
                "current_state": (
                    ShoppingSessionState.AWAITING_CONFIRMATION
                ),
                "error": None,
            }

        except Exception as exc:
            logger.exception(
                "optimize_node_error"
            )

            await stream.emit(
                session_id,
                EVENT_ERROR,
                message="Optimization failed. Please retry the search.",
            )

            return {
                **state,
                "current_state": ShoppingSessionState.FAILED,
                "error": "Optimization failed. Please retry the search.",
            }

    return optimize_node


def _make_present_node(
    stream: ShoppingEventStream,
):
    """Create the present node."""

    async def present_node(
        state: ShoppingGraphState,
    ) -> ShoppingGraphState:
        session_id = state.get("session_id", "")
        plan = state.get(
            "optimization_plan"
        )
        recommendations = state.get(
            "recommendations"
        )

        summary_lines: list[str] = []

        # --------------------------------------------------------------
        # AI recommendations
        # --------------------------------------------------------------

        if recommendations:
            reasoning = recommendations.get(
                "reasoning"
            )

            if reasoning:
                summary_lines.append("AI Recommendation:")
                summary_lines.append(
                    f"  {reasoning}"
                )

            highlights = recommendations.get(
                "highlights",
                [],
            )

            for highlight in highlights:
                summary_lines.append(f"  - {highlight}")

        # --------------------------------------------------------------
        # Optimized order
        # --------------------------------------------------------------

        if plan:
            summary_lines.append(
                f"Total: {plan.currency_symbol}{plan.grand_total:.2f}"
            )

            for item in plan.items:
                summary_lines.append(
                    f"  - {item.product_name} "
                    f"from {item.merchant_name}: "
                    f"{item.currency_symbol}{item.price:.2f} + "
                    f"{item.currency_symbol}{item.shipping_cost:.2f} shipping"
                )

            if plan.savings_vs_single > 0:
                summary_lines.append(
                    "  Savings vs single merchant: "
                    f"{plan.currency_symbol}{plan.savings_vs_single:.2f}"
                )

        await stream.emit(
            session_id,
            EVENT_AWAITING_CONFIRMATION,
            data={
                "summary": summary_lines,
                "plan": (
                    plan.model_dump()
                    if plan
                    else {}
                ),
                "recommendations": (
                    recommendations
                    if recommendations
                    else {}
                ),
            },
            message=(
                "Please review and "
                "confirm your order."
            ),
        )

        return {
            **state,
            "current_state": (
                ShoppingSessionState.AWAITING_CONFIRMATION
            ),
        }

    return present_node


def _make_wait_node(
    stream: ShoppingEventStream,
):
    """Create the wait-for-confirmation node."""

    async def wait_node(
        state: ShoppingGraphState,
    ) -> ShoppingGraphState:
        confirmed = state.get(
            "user_confirmed",
            False,
        )

        session_id = state.get(
            "session_id",
            "",
        )

        if not confirmed:
            await stream.emit(
                session_id,
                EVENT_AWAITING_CONFIRMATION,
                message=(
                    "Waiting for your confirmation..."
                ),
            )

        return {
            **state,
            "user_confirmed": confirmed,
        }

    return wait_node


def _make_checkout_node(
    checkout_agent: CheckoutAgent,
    stream: ShoppingEventStream,
):
    """Create the checkout node."""

    async def checkout_node(
        state: ShoppingGraphState,
    ) -> ShoppingGraphState:
        session_id = state.get(
            "session_id",
            "",
        )

        plan = state.get(
            "optimization_plan"
        )

        merchants = state.get(
            "discovered_merchants",
            [],
        )

        if not plan:
            return {
                **state,
                "current_state": ShoppingSessionState.FAILED,
                "error": "No optimization plan for checkout.",
            }

        await stream.emit(
            session_id,
            EVENT_CHECKING_OUT,
            message=(
                f"Checking out with "
                f"{plan.merchants_used} merchant(s)..."
            ),
        )

        try:
            merchants_map = {
                merchant.id: merchant
                for merchant in merchants
            }

            orders = await checkout_agent.execute_checkouts(
                plan,
                merchants_map,
                stream,
                session_id,
            )

            return {
                **state,
                "completed_orders": orders,
                "current_state": (
                    ShoppingSessionState.COMPLETED
                ),
                "error": None,
            }

        except Exception as exc:
            logger.exception(
                "checkout_node_error"
            )

            await stream.emit(
                session_id,
                EVENT_ERROR,
                message="Checkout failed. No new order was confirmed.",
            )

            return {
                **state,
                "current_state": ShoppingSessionState.FAILED,
                "error": "Checkout failed. Please review the merchant status and retry.",
            }

    return checkout_node


def _make_complete_node(
    stream: ShoppingEventStream,
):
    """Create the complete node."""

    async def complete_node(
        state: ShoppingGraphState,
    ) -> ShoppingGraphState:
        session_id = state.get(
            "session_id",
            "",
        )

        orders = state.get(
            "completed_orders",
            [],
        )

        await stream.emit(
            session_id,
            EVENT_COMPLETED,
            data={
                "order_count": len(orders),
                "orders": (
                    [order.model_dump() for order in orders]
                    if orders
                    else []
                ),
            },
            message=(
                f"Shopping complete! "
                f"{len(orders)} order(s) placed."
            ),
        )

        return {
            **state,
            "current_state": (
                ShoppingSessionState.COMPLETED
            ),
        }

    return complete_node


async def _fail_node(
    state: ShoppingGraphState,
) -> ShoppingGraphState:
    """Terminal failure node."""

    return {
        **state,
        "current_state": ShoppingSessionState.FAILED,
    }


# ---------------------------------------------------------------------------
# Conditional routing
# ---------------------------------------------------------------------------


def _after_discover(
    state: ShoppingGraphState,
) -> str:
    """Route after discovery."""

    merchants = state.get(
        "discovered_merchants",
        [],
    )

    if merchants:
        return "search"

    return "fail"


def _after_compare(
    state: ShoppingGraphState,
) -> str:
    """Always send comparison results to AI recommendation."""

    matrix = state.get(
        "comparison_matrix"
    )

    if not matrix:
        return "fail"

    return "recommend"


def _after_wait(
    state: ShoppingGraphState,
) -> str:
    """Route after human confirmation."""

    if state.get(
        "user_confirmed",
        False,
    ):
        return "checkout"

    return "fail"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_shopping_graph(
    settings: Settings,
    stream: ShoppingEventStream,
) -> StateGraph:
    """Construct the LangGraph shopping workflow."""

    # --------------------------------------------------------------
    # Instantiate agents
    # --------------------------------------------------------------

    planner = ShoppingPlanner(
        settings
    )

    discovery = DiscoveryAgent(
        settings
    )

    search_agent = SearchAgent(
        settings
    )

    comparison = ComparisonAgent()

    recommendation_agent = RecommendationAgent(
        settings
    )

    optimizer = SplitOrderOptimizer()

    checkout_agent = CheckoutAgent(
        settings
    )

    # --------------------------------------------------------------
    # Build graph
    # --------------------------------------------------------------

    graph = StateGraph(
        ShoppingGraphState
    )

    # --------------------------------------------------------------
    # Nodes
    # --------------------------------------------------------------

    graph.add_node(
        "plan",
        _make_plan_node(
            planner,
            stream,
        ),
    )

    graph.add_node(
        "discover",
        _make_discover_node(
            discovery,
            stream,
        ),
    )

    graph.add_node(
        "search",
        _make_search_node(
            search_agent,
            stream,
        ),
    )

    graph.add_node(
        "compare",
        _make_compare_node(
            comparison,
            stream,
        ),
    )

    graph.add_node(
        "recommend",
        _make_recommendation_node(
            recommendation_agent,
            stream,
        ),
    )

    graph.add_node(
        "optimize",
        _make_optimize_node(
            optimizer,
            stream,
        ),
    )

    graph.add_node(
        "present",
        _make_present_node(
            stream
        ),
    )

    graph.add_node(
        "wait_for_confirmation",
        _make_wait_node(
            stream
        ),
    )

    graph.add_node(
        "checkout",
        _make_checkout_node(
            checkout_agent,
            stream,
        ),
    )

    graph.add_node(
        "complete",
        _make_complete_node(
            stream
        ),
    )

    graph.add_node(
        "fail",
        _fail_node
    )

    # --------------------------------------------------------------
    # Entry point
    # --------------------------------------------------------------

    graph.set_entry_point(
        "plan"
    )

    # --------------------------------------------------------------
    # Edges
    # --------------------------------------------------------------

    graph.add_edge(
        "plan",
        "discover",
    )

    graph.add_conditional_edges(
        "discover",
        _after_discover,
        {
            "search": "search",
            "fail": "fail",
        },
    )

    graph.add_edge(
        "search",
        "compare",
    )

    graph.add_conditional_edges(
        "compare",
        _after_compare,
        {
            "recommend": "recommend",
            "fail": "fail",
        },
    )

    graph.add_edge(
        "recommend",
        "optimize",
    )

    graph.add_edge(
        "optimize",
        "present",
    )

    graph.add_edge(
        "present",
        "wait_for_confirmation",
    )

    graph.add_conditional_edges(
        "wait_for_confirmation",
        _after_wait,
        {
            "checkout": "checkout",
            "fail": "fail",
        },
    )

    graph.add_edge(
        "checkout",
        "complete",
    )

    # --------------------------------------------------------------
    # Terminal nodes
    # --------------------------------------------------------------

    graph.add_edge(
        "complete",
        END,
    )

    graph.add_edge(
        "fail",
        END,
    )

    return graph


def compile_shopping_graph(
    settings: Settings,
    stream: ShoppingEventStream,
):
    """Build and compile the shopping graph into a runnable."""

    graph = build_shopping_graph(
        settings,
        stream,
    )

    return graph.compile()