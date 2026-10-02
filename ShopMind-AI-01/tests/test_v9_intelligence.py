from __future__ import annotations

import tempfile
from pathlib import Path

from shopmind_ai.models import ProductResult
from shopmind_ai.services.intelligence import price_signal, rank_products, review_summary
from shopmind_ai.services.persistence import PersistenceStore


def test_product_intelligence_and_price_signal() -> None:
    product = ProductResult(
        product_id="p1",
        name="Wireless ANC Earbuds",
        price=1299,
        currency="INR",
        display_price=1299,
        display_currency="INR",
        merchant_id="m1",
        merchant_name="Trusted Store",
        rating=4.6,
        review_count=1500,
        source_name="Trusted Store",
        source_type="regional_search",
        url="https://example.com/p1",
    )
    ranked = rank_products([product], "wireless earbuds with ANC under 1500", 1500)
    assert ranked[0].score > 0
    assert product.trust_score > 0
    assert review_summary(product)["review_count"] == 1500
    assert price_signal([{"price": 1499}, {"price": 1399}], 1299)["signal"] == "good_time_to_buy"


def test_persistent_wishlist_and_user() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = PersistenceStore(str(Path(tmp) / "shopmind.db"))
        product = {"product_id": "p1", "merchant_id": "m1", "name": "Test", "price": 100, "currency": "INR"}
        store.wishlist_add("u1", product)
        assert len(store.wishlist("u1")) == 1
        user_id = store.create_user("user@example.com", "password123")
        assert store.authenticate_user("user@example.com", "password123") == user_id
        assert store.authenticate_user("user@example.com", "wrong-password") is None
