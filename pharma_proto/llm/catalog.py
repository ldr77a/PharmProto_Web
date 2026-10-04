"""Allowlisted provider and model mappings exposed by the local UI."""

from __future__ import annotations

from typing import Literal, cast

Provider = Literal["openai", "gemini", "claude"]
Tier = Literal["cheap", "normal", "good"]

MODEL_CATALOG: dict[Provider, dict[Tier, str]] = {
    "openai": {
        "cheap": "gpt-5.6-luna",
        "normal": "gpt-5.6-terra",
        "good": "gpt-5.6-sol",
    },
    "gemini": {
        "cheap": "gemini-3.5-flash-lite",
        "normal": "gemini-3.7-flash",
        "good": "gemini-3.1-pro-preview",
    },
    "claude": {
        "cheap": "claude-haiku-4-5-20251001",
        "normal": "claude-sonnet-5-5",
        "good": "claude-opus-5-5",
    },
}


def model_for(provider: str, tier: str) -> str:
    if provider not in MODEL_CATALOG:
        raise ValueError("unsupported provider")
    selected = MODEL_CATALOG[cast(Provider, provider)]
    if tier not in selected:
        raise ValueError("unsupported tier")
    return selected[cast(Tier, tier)]


__all__ = ["MODEL_CATALOG", "Provider", "Tier", "model_for"]
