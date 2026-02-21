"""Shared backend selection and normalization helpers.

This module centralizes backend/provider resolution rules used across optimizer
families (GraphRAG and agentic) so backend behavior does not drift.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional


_PROVIDER_ALIASES: Dict[str, str] = {
    "gpt4": "openai",
    "openai": "openai",
    "gpt-4": "openai",
    "claude": "anthropic",
    "anthropic": "anthropic",
    "codex": "codex",
    "copilot": "copilot",
    "gemini": "gemini",
    "local": "local",
    "accelerate": "accelerate",
    "ipfs_accelerate": "accelerate",
    "auto": "auto",
}

_DEFAULT_MODEL_BY_PROVIDER: Dict[str, str] = {
    "accelerate": "gpt-4",
    "openai": "gpt-4",
    "anthropic": "claude-3-opus",
    "gemini": "gemini-1.5-pro",
    "local": "local-default",
    "codex": "codex",
    "copilot": "copilot",
}


def canonicalize_provider(provider: Optional[str], default: str = "auto") -> str:
    """Return canonical provider name from aliases.

    Unknown values fall back to ``default``.
    """
    raw = (provider or "").strip().lower()
    if not raw:
        return default
    return _PROVIDER_ALIASES.get(raw, default)


def detect_provider_from_environment(*, prefer_accelerate: bool = False) -> str:
    """Detect best provider from env vars and available API keys.

    Order:
    1. ``IPFS_DATASETS_PY_LLM_PROVIDER`` if set.
    2. API key presence (OpenAI/Anthropic/Gemini).
    3. ``accelerate`` if preferred.
    4. ``local`` fallback.
    """
    env_provider = canonicalize_provider(
        os.environ.get("IPFS_DATASETS_PY_LLM_PROVIDER", ""),
        default="auto",
    )
    if env_provider != "auto":
        return env_provider

    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"

    if prefer_accelerate:
        return "accelerate"
    return "local"


def default_model_for_provider(provider: str, fallback: str = "gpt-4") -> str:
    """Return a default model for a canonical provider."""
    return _DEFAULT_MODEL_BY_PROVIDER.get(provider, fallback)


@dataclass(frozen=True)
class BackendResolution:
    """Normalized backend selection and config values."""

    provider: str
    model: str
    temperature: float
    max_tokens: int
    use_ipfs_accelerate: bool
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize normalized backend settings."""
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "use_ipfs_accelerate": self.use_ipfs_accelerate,
            **self.extra,
        }


def resolve_backend_settings(
    config: Optional[Mapping[str, Any]] = None,
    *,
    default_provider: str = "auto",
    default_model: str = "gpt-4",
    use_ipfs_accelerate: bool = False,
    prefer_accelerate: bool = False,
) -> BackendResolution:
    """Normalize backend config using shared provider selection rules."""
    source: Dict[str, Any] = dict(config or {})

    canonical = canonicalize_provider(source.get("provider"), default=default_provider)
    if canonical == "auto":
        canonical = detect_provider_from_environment(prefer_accelerate=prefer_accelerate)

    model = str(source.get("model") or default_model_for_provider(canonical, default_model))
    temperature = float(source.get("temperature", 0.3))
    max_tokens = int(source.get("max_tokens", 2048))

    # accelerate backend is only meaningful when explicitly enabled.
    effective_use_accelerate = bool(use_ipfs_accelerate and canonical == "accelerate")

    known = {"provider", "model", "temperature", "max_tokens", "use_ipfs_accelerate"}
    extra = {k: v for k, v in source.items() if k not in known}

    return BackendResolution(
        provider=canonical,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        use_ipfs_accelerate=effective_use_accelerate,
        extra=extra,
    )
