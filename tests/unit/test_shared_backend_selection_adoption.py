"""Regression tests for shared backend selection adoption outside optimizers."""

from __future__ import annotations

from ipfs_datasets_py.ml.llm.llm_router_interface import RoutedLLMInterface
from ipfs_datasets_py.processors.legal_scrapers.query_expander import QueryExpander


def test_routed_llm_interface_reports_canonical_provider_from_env(monkeypatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_LLM_PROVIDER", "claude")
    iface = RoutedLLMInterface()
    assert iface._resolved_provider_name() == "anthropic"


def test_routed_llm_interface_reports_canonical_provider_from_explicit_provider() -> None:
    iface = RoutedLLMInterface(provider="gpt4")
    assert iface._resolved_provider_name() == "openai"


def test_query_expander_uses_shared_provider_detection(monkeypatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_LLM_PROVIDER", "claude")
    expander = QueryExpander(use_llm=False)
    assert expander.llm_provider == "anthropic"
