"""Regression tests for llm_router provider alias canonicalization."""

from __future__ import annotations

from ipfs_datasets_py import llm_router


class _DummyProvider:
    def generate(self, prompt: str, **kwargs):
        return "ok"


def test_resolve_provider_uncached_preferred_alias_canonicalized(monkeypatch) -> None:
    calls = []

    def fake_builtin(name: str):
        calls.append(name)
        if name == "openai":
            return _DummyProvider()
        return None

    monkeypatch.setattr(llm_router, "_builtin_provider_by_name", fake_builtin)
    monkeypatch.setattr(llm_router, "_get_accelerate_provider", lambda deps: None)

    provider = llm_router._resolve_provider_uncached(
        preferred="gpt4",
        deps=llm_router.get_default_router_deps(),
    )

    assert isinstance(provider, _DummyProvider)
    assert "openai" in calls


def test_resolve_provider_uncached_forced_alias_canonicalized(monkeypatch) -> None:
    calls = []

    def fake_builtin(name: str):
        calls.append(name)
        if name == "anthropic":
            return _DummyProvider()
        return None

    monkeypatch.setattr(llm_router, "_builtin_provider_by_name", fake_builtin)
    monkeypatch.setattr(llm_router, "_get_accelerate_provider", lambda deps: None)
    monkeypatch.setenv("IPFS_DATASETS_PY_LLM_PROVIDER", "claude")

    provider = llm_router._resolve_provider_uncached(
        preferred=None,
        deps=llm_router.get_default_router_deps(),
    )

    assert isinstance(provider, _DummyProvider)
    assert "anthropic" in calls
