"""Deterministic shopping intelligence: ranking, trust and review summaries."""
from __future__ import annotations

import re
from typing import Any

from shopmind_ai.models import ProductResult


def feature_match(product: ProductResult, query: str) -> float:
    requested = set(re.findall(r"[a-z0-9]+", query.lower()))
    haystack = " ".join([product.name, product.description, product.brand, *product.specs.keys(), *product.specs.values()]).lower()
    if not requested:
        return 0.5
    hits = sum(1 for word in requested if len(word) > 2 and word in haystack)
    return min(1.0, hits / max(5, len(requested) // 2))


def trust_score(product: ProductResult) -> float:
    source = float(product.trust_score or 0.0)
    rating = min(1.0, max(0.0, float(product.rating or 0.0) / 5.0))
    reviews = min(1.0, (float(product.review_count or 0) / 10000.0) ** 0.5)
    verified = 1.0 if product.url and product.source_type in {"ucp", "regional_search"} else 0.5
    return round(min(1.0, source * 0.45 + rating * 0.25 + reviews * 0.15 + verified * 0.15), 4)


def rank_products(products: list[ProductResult], query: str, budget: float | None = None) -> list[ProductResult]:
    prices = [float(p.display_price if p.display_price is not None else p.price) for p in products if (p.display_price if p.display_price is not None else p.price) > 0]
    max_price = max(prices, default=1.0)
    min_price = min(prices, default=0.0)
    for product in products:
        price = float(product.display_price if product.display_price is not None else product.price)
        price_score = 1.0 - ((price - min_price) / max(0.01, max_price - min_price))
        budget_score = 1.0 if budget is None or price <= budget else max(0.0, budget / max(price, 0.01))
        rating_score = min(1.0, max(0.0, product.rating / 5.0))
        review_score = min(1.0, (max(product.review_count, 0) / 10000) ** 0.5)
        trust = trust_score(product)
        match = feature_match(product, query)
        instant = 1.0 if product.specs.get("delivery_window") else 0.0
        product.trust_score = trust
        product.score = round(0.24 * price_score + 0.18 * budget_score + 0.20 * rating_score + 0.10 * review_score + 0.18 * match + 0.10 * max(trust, instant), 4)
    return sorted(products, key=lambda p: (-p.score, float(p.display_price if p.display_price is not None else p.price)))


def review_summary(product: ProductResult) -> dict[str, Any]:
    rating = float(product.rating or 0)
    reviews = int(product.review_count or 0)
    positive = min(95, max(45, round(50 + (rating - 3.0) * 25 + min(reviews, 10000) / 1000)))
    negative = max(2, round((100 - positive) * 0.55))
    neutral = max(1, 100 - positive - negative)
    return {
        "rating": rating,
        "review_count": reviews,
        "sentiment": {"positive": positive, "neutral": neutral, "negative": negative},
        "summary": "Strong customer reception based on the available rating/review signals." if rating >= 4 else "Mixed customer reception; review the retailer feedback before buying.",
        "note": "This is an aggregate signal, not a verbatim review summary." if reviews else "No review volume was available from the source.",
    }


def price_signal(history: list[dict[str, Any]], current: float | None) -> dict[str, Any]:
    values = [float(item["price"]) for item in history if item.get("price") is not None]
    if current is None or not values:
        return {"current": current, "average": None, "change_pct": None, "signal": "insufficient_history"}
    avg = sum(values) / len(values)
    change = ((current - avg) / avg * 100) if avg else 0
    signal = "good_time_to_buy" if change <= -5 else "above_recent_average" if change >= 5 else "near_recent_average"
    return {"current": current, "average": round(avg, 2), "change_pct": round(change, 2), "signal": signal}
