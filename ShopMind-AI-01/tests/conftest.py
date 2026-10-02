"""Shared test fixtures for ShopMind AI."""

import pytest

from shopmind_ai.config import Settings
from shopmind_ai.main import build_app


@pytest.fixture
def settings():
    """Create test settings."""
    return Settings(
        environment="testing",
        google_api_key="test-key",
        groq_api_key="test-key",
        human_confirmation_required=False,
    )


@pytest.fixture
def app(settings):
    """Create FastAPI app for testing (with mock merchants mounted)."""
    return build_app(settings)
