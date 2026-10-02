"""Centralized configuration management using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized settings for ShopMind AI."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Providers
    google_api_key: str = ""
    groq_api_key: str = ""
    mistral_api_key: str = ""
    openrouter_api_key: str = ""

    # AI routing / model defaults
    groq_model: str = "llama-3.3-70b-versatile"
    mistral_model: str = "mistral-large-latest"
    openrouter_model: str = "openrouter/free"
    ai_provider_order: str = "gemini,groq,mistral,openrouter"

    # Optional AI Providers
    cohere_api_key: str = ""
    huggingface_token: str = ""

    # Infrastructure
    database_url: str = "postgresql://aiportfolio:localdev@localhost:5432/aiportfolio"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"

    # Search
    tavily_api_key: str = ""
    serper_api_key: str = ""

    # Image Generation
    replicate_api_token: str = ""
    stability_api_key: str = ""

    # Observability
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "shopmind-ai"

    # Application
    log_level: str = "INFO"
    environment: str = "development"

    # API hardening / browser access
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    rate_limit_per_minute: int = 30
    max_query_length: int = 1000
