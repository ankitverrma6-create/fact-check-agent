"""Application configuration and environment loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH, override=True)


def normalize_api_key(value: str) -> str:
    """Strip whitespace and surrounding quotes from an API key."""
    return value.strip().strip('"').strip("'")


def configure_gemini_environment(api_key: str) -> str:
    """Publish a Google AI Studio key for the google-genai SDK.

    The SDK reads GOOGLE_API_KEY first, then GEMINI_API_KEY. We set both from
    the app configuration so a stale shell-level key cannot override .env.
    """
    cleaned = normalize_api_key(api_key)
    if cleaned:
        os.environ["GOOGLE_API_KEY"] = cleaned
        os.environ["GEMINI_API_KEY"] = cleaned
    return cleaned


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment or Streamlit secrets."""

    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"
    max_pdf_pages: int = 50
    max_claims: int = 3


def _get_secret(key: str, default: str = "") -> str:
    """Read from env first, then Streamlit secrets when available."""
    value = os.getenv(key, default)
    if value:
        return value
    try:
        import streamlit as st

        return st.secrets.get(key, default)
    except Exception:
        return default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings(
        gemini_api_key=normalize_api_key(_get_secret("GEMINI_API_KEY")),
        gemini_model=_get_secret("GEMINI_MODEL", "gemini-2.5-flash"),
        max_pdf_pages=int(_get_secret("MAX_PDF_PAGES", "50")),
        max_claims=min(int(_get_secret("MAX_CLAIMS", "3")), 3),
    )


def validate_settings(settings: Settings) -> list[str]:
    """Return list of missing configuration keys."""
    missing: list[str] = []
    if not settings.gemini_api_key:
        missing.append("GEMINI_API_KEY")
    return missing


def reload_settings() -> Settings:
    """Reload .env and return fresh settings (for Streamlit reruns)."""
    load_dotenv(ENV_PATH, override=True)
    get_settings.cache_clear()
    return get_settings()


def create_gemini_client():
    """Create an authenticated Gemini client from current settings."""
    from src.gemini_client import GeminiClient

    settings = reload_settings()
    return GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
