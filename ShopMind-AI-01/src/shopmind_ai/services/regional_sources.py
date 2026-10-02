"""Trusted regional shopping-source registry.

The registry is intentionally data-only: search adapters can use it without
hard-coding retailer logic throughout the application.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegionalSource:
    key: str
    name: str
    domain: str
    countries: frozenset[str]
    categories: frozenset[str] = frozenset()
    trust_score: float = 0.90
    currency: str = "USD"
    instant_delivery: bool = False
    delivery_minutes_min: int | None = None
    delivery_minutes_max: int | None = None




COUNTRY_CURRENCIES = {
    "IN": "INR", "NP": "NPR", "RU": "RUB", "US": "USD", "CA": "CAD",
    "GB": "GBP", "DE": "EUR", "AT": "EUR", "FR": "EUR", "IT": "EUR",
    "ES": "EUR", "NL": "EUR", "JP": "JPY", "AE": "AED", "SA": "SAR",
    "AU": "AUD", "BR": "BRL", "CH": "CHF", "SG": "SGD", "MY": "MYR",
    "TH": "THB", "ID": "IDR", "PH": "PHP", "VN": "VND", "KR": "KRW", "CN": "CNY", "PL": "PLN",
}

GLOBAL_SOURCES = (
    RegionalSource(
        "amazon",
        "Amazon",
        "amazon.com",
        frozenset({"US", "CA", "MX"}),
        trust_score=0.94,
    ),
    RegionalSource(
        "amazon_uk",
        "Amazon UK",
        "amazon.co.uk",
        frozenset({"GB"}),
        trust_score=0.94,
    ),
    RegionalSource(
        "amazon_in",
        "Amazon India",
        "amazon.in",
        frozenset({"IN"}),
        trust_score=0.94,
    ),
    RegionalSource(
        "flipkart",
        "Flipkart",
        "flipkart.com",
        frozenset({"IN"}),
        trust_score=0.93,
    ),
    RegionalSource(
        "myntra",
        "Myntra",
        "myntra.com",
        frozenset({"IN"}),
        frozenset({"fashion", "beauty", "lifestyle"}),
        0.91,
    ),
    RegionalSource(
        "croma",
        "Croma",
        "croma.com",
        frozenset({"IN"}),
        trust_score=0.91,
    ),
    RegionalSource(
        "reliance_digital",
        "Reliance Digital",
        "reliancedigital.in",
        frozenset({"IN"}),
        trust_score=0.91,
    ),
    # India quick-commerce sources. These are intentionally separate from
    # normal e-commerce sources so the Instant Delivery section/search can
    # never accidentally show a standard 1-7 day retailer. Delivery windows
    # are indicative; actual ETA is location, stock and traffic dependent.
    RegionalSource(
        "blinkit",
        "Blinkit",
        "blinkit.com",
        frozenset({"IN"}),
        trust_score=0.93,
        instant_delivery=True,
        delivery_minutes_min=10,
        delivery_minutes_max=30,
    ),
    RegionalSource(
        "zepto",
        "Zepto",
        "zeptonow.com",
        frozenset({"IN"}),
        trust_score=0.93,
        instant_delivery=True,
        delivery_minutes_min=10,
        delivery_minutes_max=30,
    ),
    RegionalSource(
        "swiggy_instamart",
        "Swiggy Instamart",
        "swiggy.com",
        frozenset({"IN"}),
        trust_score=0.93,
        instant_delivery=True,
        delivery_minutes_min=10,
        delivery_minutes_max=30,
    ),
    RegionalSource(
        "bbnow",
        "bbnow",
        "bigbasket.com",
        frozenset({"IN"}),
        trust_score=0.92,
        instant_delivery=True,
        delivery_minutes_min=10,
        delivery_minutes_max=30,
    ),
    RegionalSource(
        "flipkart_minutes",
        "Flipkart Minutes",
        "flipkart.com",
        frozenset({"IN"}),
        trust_score=0.93,
        instant_delivery=True,
        delivery_minutes_min=10,
        delivery_minutes_max=30,
    ),
    RegionalSource(
        "amazon_jp",
        "Amazon Japan",
        "amazon.co.jp",
        frozenset({"JP"}),
        trust_score=0.94,
    ),
    RegionalSource(
        "amazon_de",
        "Amazon Germany",
        "amazon.de",
        frozenset({"DE", "AT"}),
        trust_score=0.94,
    ),
    RegionalSource(
        "amazon_fr",
        "Amazon France",
        "amazon.fr",
        frozenset({"FR"}),
        trust_score=0.94,
    ),
    RegionalSource(
        "amazon_it",
        "Amazon Italy",
        "amazon.it",
        frozenset({"IT"}),
        trust_score=0.94,
    ),
    RegionalSource(
        "amazon_es",
        "Amazon Spain",
        "amazon.es",
        frozenset({"ES"}),
        trust_score=0.94,
    ),
    RegionalSource(
        "amazon_nl",
        "Amazon Netherlands",
        "amazon.nl",
        frozenset({"NL"}),
        trust_score=0.94,
    ),
    RegionalSource(
        "amazon_ae",
        "Amazon UAE",
        "amazon.ae",
        frozenset({"AE"}),
        trust_score=0.94,
    ),
    RegionalSource(
        "noon",
        "noon",
        "noon.com",
        frozenset({"AE", "SA"}),
        trust_score=0.89,
    ),
    RegionalSource(
        "walmart",
        "Walmart",
        "walmart.com",
        frozenset({"US"}),
        trust_score=0.93,
    ),
    RegionalSource(
        "bestbuy",
        "Best Buy",
        "bestbuy.com",
        frozenset({"US", "CA"}),
        trust_score=0.92,
    ),
    RegionalSource(
        "currys",
        "Currys",
        "currys.co.uk",
        frozenset({"GB"}),
        trust_score=0.90,
    ),
    RegionalSource("shopee_sg", "Shopee", "shopee.sg", frozenset({"SG"}), trust_score=0.88),
    RegionalSource("shopee_my", "Shopee", "shopee.com.my", frozenset({"MY"}), trust_score=0.88),
    RegionalSource("lazada_sg", "Lazada", "lazada.sg", frozenset({"SG"}), trust_score=0.88),
    RegionalSource("lazada_my", "Lazada", "lazada.com.my", frozenset({"MY"}), trust_score=0.88),
    RegionalSource("mercadolibre_mx", "Mercado Libre", "mercadolibre.com.mx", frozenset({"MX"}), trust_score=0.88),
    RegionalSource("mercadolibre_br", "Mercado Livre", "mercadolivre.com.br", frozenset({"BR"}), trust_score=0.88, currency="BRL"),
    RegionalSource("allegro_pl", "Allegro", "allegro.pl", frozenset({"PL"}), trust_score=0.88, currency="PLN"),
    RegionalSource("rakuten_jp", "Rakuten", "rakuten.co.jp", frozenset({"JP"}), trust_score=0.88, currency="JPY"),
    RegionalSource("coupang_kr", "Coupang", "coupang.com", frozenset({"KR"}), trust_score=0.90, currency="KRW"),
    RegionalSource("jd_cn", "JD.com", "jd.com", frozenset({"CN"}), trust_score=0.89, currency="CNY"),
)



def instant_sources_for_country(
    country_code: str | None,
) -> list[RegionalSource]:
    """Return only sources explicitly classified as quick/instant delivery."""
    country = (country_code or "").upper()
    return [
        source
        for source in GLOBAL_SOURCES
        if source.instant_delivery and country in source.countries
    ]


def sources_for_country(
    country_code: str | None,
    *,
    category: str | None = None,
) -> list[RegionalSource]:
    """Return region-appropriate sources, with global fallbacks."""

    country = (country_code or "").upper()
    category_norm = (category or "").lower()

    matched = [
        source
        for source in GLOBAL_SOURCES
        if country in source.countries
        and (
            not source.categories
            or not category_norm
            or category_norm in source.categories
        )
    ]

    if matched:
        return matched

    # Generic global fallback. Keep this small so search stays fast.
    return [
        source
        for source in GLOBAL_SOURCES
        if source.key in {"amazon", "walmart"}
    ]
