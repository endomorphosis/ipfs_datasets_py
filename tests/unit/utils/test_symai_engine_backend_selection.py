"""Test that symai_ipfs_engine uses centralized backend selection."""
import os
import pytest
from unittest.mock import patch, MagicMock


def test_symai_generate_text_uses_centralized_detection():
    """Verify symai_ipfs_engine._generate_text uses detect_provider_from_environment."""
    from ipfs_datasets_py.utils import symai_ipfs_engine

    # Mock the shared detection and canonicalize functions to verify they're called
    with patch("ipfs_datasets_py.utils.symai_ipfs_engine.detect_provider_from_environment") as mock_detect, \
         patch("ipfs_datasets_py.utils.symai_ipfs_engine.canonicalize_provider") as mock_canon, \
         patch("ipfs_datasets_py.utils.symai_ipfs_engine.llm_router.generate_text") as mock_gen:

        mock_detect.return_value = "openai"
        mock_canon.return_value = "openai"
        mock_gen.return_value = "test response"

        # Call _generate_text with a simple prompt
        result, metadata = symai_ipfs_engine._generate_text("test prompt", "test-model")

        # Verify that both centralized functions were called
        mock_detect.assert_called_once()
        mock_canon.assert_called_once()
        # Verify the llm_router was called with the canonicalized provider
        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["provider"] == "openai"


def test_symai_generate_text_fallback_when_shared_detection_unavailable():
    """Verify fallback to os.environ when shared detection functions unavailable."""
    from ipfs_datasets_py.utils import symai_ipfs_engine

    # Temporarily set detection functions to None to trigger fallback
    with patch.object(symai_ipfs_engine, "detect_provider_from_environment", None), \
         patch.object(symai_ipfs_engine, "canonicalize_provider", None), \
         patch("ipfs_datasets_py.utils.symai_ipfs_engine.llm_router.generate_text") as mock_gen, \
         patch.dict(os.environ, {"IPFS_DATASETS_PY_LLM_PROVIDER": "anthropic"}):

        mock_gen.return_value = "test response"

        result, metadata = symai_ipfs_engine._generate_text("test prompt", "test-model")

        # Verify fallback to os.environ was used
        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["provider"] == "anthropic"
