"""Tests for LLMInterfaceFactory backend-selection centralization."""

from __future__ import annotations

from ipfs_datasets_py.ml.llm.llm_interface import LLMInterfaceFactory
from ipfs_datasets_py.ml.llm.llm_router_interface import RoutedLLMInterface
from ipfs_datasets_py.ml.llm.llm_interface import MockLLMInterface


def test_factory_prefers_router_when_provider_env_set(monkeypatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_PY_LLM_PROVIDER", "claude")
    iface = LLMInterfaceFactory.create("mock-llm")
    assert isinstance(iface, RoutedLLMInterface)


def test_factory_keeps_mock_when_no_provider_signals(monkeypatch) -> None:
    monkeypatch.delenv("IPFS_DATASETS_PY_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_OPENROUTER_API_KEY", raising=False)

    iface = LLMInterfaceFactory.create("mock-llm")
    assert isinstance(iface, MockLLMInterface)
