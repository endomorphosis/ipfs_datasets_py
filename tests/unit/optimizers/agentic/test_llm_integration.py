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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
