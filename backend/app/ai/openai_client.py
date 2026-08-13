"""Shared OpenAI client with optional base_url + HTTP(S)/SOCKS proxy."""

from __future__ import annotations

import os

from app.config import Settings

_DEFAULT_BASE = "https://api.openai.com/v1"


def resolve_openai_proxy(settings: Settings) -> str | None:
    """Prefer OPENAI_PROXY, then standard HTTPS_PROXY / HTTP_PROXY / ALL_PROXY."""
    candidates = (
        (settings.openai_proxy or "").strip(),
        (os.environ.get("OPENAI_PROXY") or "").strip(),
        (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "").strip(),
        (os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or "").strip(),
        (os.environ.get("ALL_PROXY") or os.environ.get("all_proxy") or "").strip(),
    )
    for value in candidates:
        if value:
            return value
    return None


def make_openai_client(settings: Settings):
    from openai import OpenAI

    base_url = (settings.openai_base_url or _DEFAULT_BASE).rstrip("/")
    kwargs: dict = {
        "api_key": settings.openai_api_key,
        "base_url": base_url,
    }
    proxy = resolve_openai_proxy(settings)
    if proxy:
        import httpx

        # Explicit proxy for OpenAI egress only (e.g. Singapore VPN from Aliyun HK).
        # socks5:// requires socksio (see requirements.txt).
        kwargs["http_client"] = httpx.Client(
            proxy=proxy,
            timeout=httpx.Timeout(60.0, connect=20.0),
            trust_env=False,
        )
    return OpenAI(**kwargs)
