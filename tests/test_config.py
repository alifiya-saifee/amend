import pytest

from amend.config import ConfigError, get_settings


def test_sandbox_loads():
    s = get_settings()
    assert s.paypal_env == "sandbox"
    assert s.paypal_base == "https://api-m.sandbox.paypal.com"


@pytest.mark.parametrize("env", ["live", "production", "", "Sandbox"])
def test_refuses_to_start_unless_sandbox(monkeypatch, env):  # checklist test 9 / S57
    monkeypatch.setenv("PAYPAL_ENV", env)
    with pytest.raises(ConfigError, match="PAYPAL_ENV must be sandbox"):
        get_settings()


def test_repr_and_str_hide_secrets():
    s = get_settings()
    text = repr(s) + str(s) + str(s.model_dump())
    for secret in ("test-secret-ABC123", "test-client-id-XYZ", "test-gemini-key", "test-demo-pw"):
        assert secret not in text


def test_missing_gives_names_only(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    s = get_settings()
    assert s.missing("GROQ_API_KEY", "GEMINI_API_KEY") == ["GROQ_API_KEY"]


def test_bad_rail_rejected(monkeypatch):
    monkeypatch.setenv("MONEY_RAIL", "crypto")
    with pytest.raises(ConfigError):
        get_settings()
