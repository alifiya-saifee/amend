"""Settings from environment variables only. Refuses to start unless PAYPAL_ENV is 'sandbox'.

Secrets are SecretStr: they never appear in repr(), str(), logs or error messages.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PAYPAL_BASE = "https://api-m.sandbox.paypal.com"  # hard-coded: sandbox only (hard rule 2)
AED_RATE = "3.6725"  # fixed display rate; PayPal charges in USD

SECRET_NAMES = ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "GEMINI_API_KEY", "GROQ_API_KEY",
                "NVIDIA_API_KEY", "AMEND_DEMO_PASSWORD", "AMEND_SESSION_SECRET", "AMEND_TICK_SECRET", "WHATSAPP_TOKEN")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    paypal_env: str
    paypal_client_id: SecretStr = SecretStr("")
    paypal_client_secret: SecretStr = SecretStr("")
    paypal_webhook_id: str = ""
    database_url: str = "sqlite:///./amend.db"
    base_url: str = "http://localhost:8000"
    money_rail: str = "platform"  # platform (Option 2) | marketplace (Option 3)
    ai_provider: str = "gemini"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = "llama-3.3-70b-versatile"
    nvidia_api_key: SecretStr = SecretStr("")
    nvidia_model: str = ""
    amend_demo_password: SecretStr = SecretStr("")
    amend_session_secret: SecretStr = SecretStr("")
    amend_tick_secret: SecretStr = SecretStr("")
    whatsapp_token: SecretStr = SecretStr("")
    whatsapp_phone_id: str = ""
    sandbox_brand_email: str = ""
    sandbox_creator_email: str = ""
    sandbox_editor_email: str = ""

    @field_validator("paypal_env")
    @classmethod
    def _sandbox_only(cls, v: str) -> str:
        if v != "sandbox":
            raise ValueError("PAYPAL_ENV must be sandbox")
        return v

    @field_validator("money_rail")
    @classmethod
    def _rail(cls, v: str) -> str:
        if v not in ("platform", "marketplace"):
            raise ValueError("MONEY_RAIL must be platform or marketplace")
        return v

    @property
    def paypal_base(self) -> str:
        return PAYPAL_BASE

    def missing(self, *names: str) -> list[str]:
        """Names of empty settings (never their values)."""
        out = []
        for n in names:
            v = getattr(self, n.lower(), None)
            if isinstance(v, SecretStr):
                v = v.get_secret_value()
            if not v:
                out.append(n)
        return out


class ConfigError(RuntimeError):
    pass


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except Exception as e:  # pydantic's message names the field, never the secret values
        if "PAYPAL_ENV" in str(e).upper() or "paypal_env" in str(e):
            raise ConfigError("Refusing to start: PAYPAL_ENV must be sandbox") from None
        raise ConfigError(f"Bad settings: {type(e).__name__}") from None
