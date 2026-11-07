"""Test set-up: never read the real .env, never call real PayPal or AI."""
import os
from pathlib import Path

import pytest

# The Postgres tests read only TEST_DATABASE_URL from the project .env (nothing else is loaded into tests).
if not os.environ.get("TEST_DATABASE_URL"):
    from dotenv import dotenv_values
    _v = dotenv_values(Path(__file__).resolve().parent.parent / ".env").get("TEST_DATABASE_URL")
    if _v:
        os.environ["TEST_DATABASE_URL"] = _v

FAKE = {
    "PAYPAL_ENV": "sandbox",
    "PAYPAL_CLIENT_ID": "test-client-id-XYZ",
    "PAYPAL_CLIENT_SECRET": "test-secret-ABC123",
    "GEMINI_API_KEY": "test-gemini-key",
    "GROQ_API_KEY": "test-groq-key",
    "NVIDIA_API_KEY": "test-nvidia-key",
    "AMEND_DEMO_PASSWORD": "test-demo-pw",
    "AMEND_SESSION_SECRET": "test-session-secret",
    "AMEND_TICK_SECRET": "test-tick-secret",
    "DATABASE_URL": "sqlite:///:memory:",
    "BASE_URL": "http://testserver",
}


@pytest.fixture(autouse=True)
def fake_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no .env here, so pydantic-settings can't read the real one
    for k in list(os.environ):
        if k.startswith(("PAYPAL_", "GEMINI_", "GROQ_", "NVIDIA_", "AMEND_", "SANDBOX_")):
            monkeypatch.delenv(k, raising=False)
    for k, v in FAKE.items():
        monkeypatch.setenv(k, v)
    from amend.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
