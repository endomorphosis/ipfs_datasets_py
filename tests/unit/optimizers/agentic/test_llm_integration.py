"""Test suite for LLM integration module."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from ipfs_datasets_py.optimizers.agentic.llm_integration import (
    OptimizerLLMRouter,
    LLMProvider,
    ProviderCapability,
    PROVIDER_CAPABILITIES,
)
from ipfs_datasets_py.optimizers.agentic.base import OptimizationMethod


class TestLLMProvider:
    """Test LLMProvider enum."""
    
    def test_provider_values(self):
        """Test that all providers have correct values."""
        assert LLMProvider.GPT4.value == "gpt4"
        assert LLMProvider.CLAUDE.value == "claude"
        assert LLMProvider.LOCAL.value == "local"


class TestOptimizerLLMRouter:
    """Test OptimizerLLMRouter class."""
    
    def test_init_default(self):
        """Test default initialization."""
        router = OptimizerLLMRouter()
        assert router.preferred_provider is not None
        assert len(router.fallback_providers) > 0
        assert router.enable_tracking is True
    
    def test_init_with_provider(self):
        """Test initialization with specific provider."""
        router = OptimizerLLMRouter(
            preferred_provider=LLMProvider.CLAUDE,
            fallback_providers=[LLMProvider.GPT4],
        )
        assert router.preferred_provider == LLMProvider.CLAUDE

    def test_generate_passes_router_kwargs_to_backend(self):
        """generate() should forward typed router_kwargs to router backend."""
        router = OptimizerLLMRouter(enable_caching=False)
        router._retry_handler.retry = lambda func, max_retries=2: func()

        with patch(
            "ipfs_datasets_py.optimizers.agentic.llm_integration.router_generate",
            return_value="ok",
        ) as mocked_generate:
            response = router.generate(
                prompt="test prompt",
                method=OptimizationMethod.TEST_DRIVEN,
                router_kwargs={"top_p": 0.1, "presence_penalty": 0.2},
            )

        assert response == "ok"
        mocked_generate.assert_called_once()
        call_kwargs = mocked_generate.call_args.kwargs
        assert call_kwargs["top_p"] == 0.1
        assert call_kwargs["presence_penalty"] == 0.2

    def test_generate_cache_key_includes_router_kwargs(self):
        """router_kwargs should participate in cache-key arguments."""
        mock_cache = Mock()
        mock_cache.get.return_value = "cached"

        router = OptimizerLLMRouter(enable_caching=True, cache=mock_cache)
        response = router.generate(
            prompt="test prompt",
            method=OptimizationMethod.TEST_DRIVEN,
            router_kwargs={"top_p": 0.5},
        )

        assert response == "cached"
        mock_cache.get.assert_called_once()
        _, kwargs = mock_cache.get.call_args
        assert kwargs["top_p"] == "0.5"

    def test_generate_calls_retry_without_unexpected_kwargs(self):
        """Regression: retry wrapper should not inject unrelated kwargs into callables."""
        router = OptimizerLLMRouter(enable_caching=False)

        mock_retry = Mock(side_effect=lambda func: func())
        router._retry_handler.retry = mock_retry

        with patch(
            "ipfs_datasets_py.optimizers.agentic.llm_integration.router_generate",
            return_value="ok",
        ):
            response = router.generate(
                prompt="test prompt",
                method=OptimizationMethod.TEST_DRIVEN,
            )

        assert response == "ok"
        mock_retry.assert_called_once()
        assert mock_retry.call_args.kwargs == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
