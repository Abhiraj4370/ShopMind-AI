"""Configuration management for the ShopMind AI."""

from __future__ import annotations

from common.config import Settings as BaseSettings


class Settings(BaseSettings):
    """ShopMind AI configuration."""

    # ------------------------------------------------------------------
    # Service
    # ------------------------------------------------------------------

    service_name: str = "shopmind-ai"

    service_version: str = "0.1.0"

    host: str = "0.0.0.0"

    port: int = 8020

    # ------------------------------------------------------------------
    # LLM
    # ------------------------------------------------------------------

    default_model: str = "gemini-3.6-flash"

    # AI provider/model settings are inherited from common.config.

    # ------------------------------------------------------------------
    # Merchant discovery
    # ------------------------------------------------------------------

    known_merchant_urls: list[str] = [
        "http://localhost:8020/merchants/techzone",
        "http://localhost:8020/merchants/homegoods",
        "http://localhost:8020/merchants/megamart",
    ]

    max_merchants: int = 10

    # ------------------------------------------------------------------
    # Timeouts
    # ------------------------------------------------------------------

    comparison_timeout: int = 30

    discovery_timeout: int = 10

    checkout_timeout: int = 60

    max_results_per_merchant: int = 20

    # ------------------------------------------------------------------
    # Human confirmation
    # ------------------------------------------------------------------

    human_confirmation_required: bool = True

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    session_ttl_seconds: int = 3600

    # ------------------------------------------------------------------
    # Currency / region
    # ------------------------------------------------------------------

    default_country_code: str = "US"

    default_currency: str = "USD"

    currency_api_timeout: float = 5.0

    # Public merchant discovery is disabled by default to reduce SSRF risk.
    allow_external_merchant_discovery: bool = False

    # Persistence / product intelligence
    database_path: str = "data/shopmind.db"
    cache_ttl_seconds: int = 120
    price_alert_interval_seconds: int = 900
    admin_api_key: str = ""
    max_saved_items_per_user: int = 200


def get_settings() -> Settings:
    """Return settings instance."""

    return Settings()