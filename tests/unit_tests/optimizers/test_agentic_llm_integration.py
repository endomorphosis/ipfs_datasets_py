import os

from ipfs_datasets_py.optimizers.agentic.llm_integration import (
    LLMProvider,
    OptimizerLLMRouter,
)
from ipfs_datasets_py.optimizers.agentic.base import OptimizationMethod


def test_detect_provider_from_env(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PY_LLM_PROVIDER", "claude")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    router = OptimizerLLMRouter(preferred_provider=None, enable_caching=False)

    assert router.preferred_provider == LLMProvider.CLAUDE


def test_extract_code_and_description():
    router = OptimizerLLMRouter(preferred_provider=LLMProvider.COPILOT, enable_caching=False)

    response = (
        "Here is the fix:\n\n"
        "```python\n"
        "def add(a, b):\n"
        "    return a + b\n"
        "```\n"
        "Extra notes.\n"
    )

    code = router.extract_code(response)
    description = router.extract_description(response)

    assert code == "def add(a, b):\n    return a + b"
    assert description == "Here is the fix:"


def test_select_provider_prefers_test_driven_codex():
    router = OptimizerLLMRouter(
        preferred_provider=LLMProvider.CODEX,
        fallback_providers=[LLMProvider.CLAUDE],
        enable_caching=False,
    )

    provider = router.select_provider(OptimizationMethod.TEST_DRIVEN)

    assert provider == LLMProvider.CODEX
