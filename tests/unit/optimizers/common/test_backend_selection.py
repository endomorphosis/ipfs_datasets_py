"""Tests for shared backend selection/config normalization."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.common.backend_selection import (
    canonicalize_provider,
    detect_provider_from_environment,
    resolve_backend_settings,
)
from ipfs_datasets_py.optimizers.agentic.llm_integration import (
    OptimizerLLMRouter,
    LLMProvider,
)


def test_canonicalize_provider_aliases() -> None:
    assert canonicalize_provider("openai") == "openai"
    assert canonicalize_provider("gpt4") == "openai"
    assert canonicalize_provider("anthropic") == "anthropic"
    assert canonicalize_provider("claude") == "anthropic"
    assert canonicalize_provider("ipfs_accelerate") == "accelerate"


def test_detect_provider_from_environment_var(monkeypatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_LLM_PROVIDER", "claude")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert detect_provider_from_environment(prefer_accelerate=False) == "anthropic"


def test_detect_provider_from_api_key(monkeypatch) -> None:
    monkeypatch.delenv("IPFS_DATASETS_PY_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert detect_provider_from_environment(prefer_accelerate=False) == "openai"


def test_resolve_backend_settings_prefers_accelerate(monkeypatch) -> None:
    monkeypatch.delenv("IPFS_DATASETS_PY_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    resolved = resolve_backend_settings(
        config={},
        default_provider="auto",
        use_ipfs_accelerate=True,
        prefer_accelerate=True,
    )
    assert resolved.provider == "accelerate"
    assert resolved.use_ipfs_accelerate is True


def test_resolve_backend_settings_non_accelerate_disables_flag() -> None:
    resolved = resolve_backend_settings(
        config={"provider": "openai", "model": "gpt-4.1"},
        default_provider="auto",
        use_ipfs_accelerate=True,
        prefer_accelerate=True,
    )
    assert resolved.provider == "openai"
    assert resolved.model == "gpt-4.1"
    assert resolved.use_ipfs_accelerate is False


def test_agentic_provider_mapping_accelerate_to_local() -> None:
    assert OptimizerLLMRouter._provider_from_name("accelerate") == LLMProvider.LOCAL
    assert OptimizerLLMRouter._provider_from_name("openai") == LLMProvider.GPT4
