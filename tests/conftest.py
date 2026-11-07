"""Test set-up: never read the real .env, never call real PayPal or AI."""
import os
from pathlib import Path

import pytest

from urllib.parse import urlsplit

# The Postgres tests read only TEST_DATABASE_URL (and DATABASE_URL, to compare) from the project .env.
_ENV = Path(__file__).resolve().parent.parent / ".env"
if not os.environ.get("TEST_DATABASE_URL"):
    from dotenv import dotenv_values
    _v = dotenv_values(_ENV).get("TEST_DATABASE_URL")
    if _v:
        os.environ["TEST_DATABASE_URL"] = _v


def _project(url: str) -> tuple[str, str, str]:
    """(supabase project ref or user, host, database) - what identifies a database, ignoring passwords and options."""
    u = urlsplit(url)
    user = (u.username or "").lower()
    ref = user.split(".", 1)[1] if user.startswith("postgres.") else user
    host = (u.hostname or "").lower()
    if host.startswith("db.") and host.endswith(".supabase.co"):  # direct connection: db.<ref>.supabase.co
        ref = host.split(".")[1]
    return ref, host, (u.path or "/").lstrip("/").lower()


def unsafe_test_db(test_url: str, live_urls: list[str]) -> str | None:
    """Why TEST_DATABASE_URL must not be used (None = safe). Tests must never touch the live database."""
    if not test_url.startswith(("postgres://", "postgresql://")):
        return "TEST_DATABASE_URL must be a Postgres URL"
    if "test" not in test_url.lower():
        return ('TEST_DATABASE_URL must contain "test" (e.g. add ?application_name=amend-test). '
                "Supabase URLs show the project ID, not the project name, so the label is added to the URL")
    t = _project(test_url)
    for live in live_urls:
        if not live:
            continue
        if live.strip() == test_url.strip():
            return "TEST_DATABASE_URL is the same as DATABASE_URL"
        if live.startswith(("postgres://", "postgresql://")) and _project(live)[0] == t[0] and t[0]:
            return "TEST_DATABASE_URL points to the same Supabase project as DATABASE_URL"
    return None


def pytest_configure(config):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        return
    from dotenv import dotenv_values
    lives = [os.environ.get("DATABASE_URL", ""), dotenv_values(_ENV).get("DATABASE_URL") or "",
             os.environ.get("LIVE_DATABASE_URL", ""), dotenv_values(_ENV).get("LIVE_DATABASE_URL") or ""]
    why = unsafe_test_db(url, lives)
    if why:
        pytest.exit(f"Refusing to run: {why}. Tests must never touch the live database.", returncode=4)

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
