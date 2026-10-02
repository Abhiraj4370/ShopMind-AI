"""Tests for regional source selection and safe web-result parsing."""

from decimal import Decimal

from shopmind_ai.services.regional_search import (
    _extract_price,
    _extract_rating_reviews,
    _extract_features,
)
from shopmind_ai.services.regional_sources import sources_for_country


def test_india_sources_include_major_retailers():
    names = {source.name for source in sources_for_country("IN")}

    assert "Amazon India" in names
    assert "Flipkart" in names


def test_unknown_region_has_global_fallback():
    sources = sources_for_country("ZZ")

    assert sources
    assert any(source.name == "Amazon" for source in sources)


def test_price_parser():
    price, currency = _extract_price("Special offer ₹1,299 today")
    assert price == Decimal("1299")
    assert currency == "INR"


def test_rating_and_reviews_parser():
    rating, reviews = _extract_rating_reviews(
        "Rated 4.5 out of 5 stars from 12,421 reviews"
    )

    assert rating == 4.5
    assert reviews == 12421


def test_india_instant_sources_are_separate():
    from shopmind_ai.services.regional_sources import instant_sources_for_country

    names = {source.name for source in instant_sources_for_country("IN")}
    assert "Blinkit" in names
    assert "Zepto" in names
    assert "Swiggy Instamart" in names


def test_feature_parser_extracts_buyer_features():
    features = _extract_features("Wireless earbuds with ANC, 40 hours battery, IPX5, fast charging")
    assert features["ANC"]
    assert features["Battery"] == "40h"
    assert features["Water resistance"] == "IPX5"
    assert features["Fast charging"]
