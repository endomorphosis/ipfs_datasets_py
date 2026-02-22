"""
Tests for TDFOL NL LLM module (consolidated from llm_nl_converter and llm_nl_prompts tests).

This module tests:
- LLM response caching with IPFS CIDs
- LLM-enhanced NL to TDFOL conversion
- Prompt building and template functions
- Hybrid pattern + LLM approach
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

# Import from new consolidated module
from ipfs_datasets_py.logic.TDFOL.nl.llm import (
    LLMNLConverter,
    LLMResponseCache,
    LLMParseResult,
    build_conversion_prompt,
    build_validation_prompt,
    build_error_correction_prompt,
    get_operator_hints_for_text,
    SYSTEM_PROMPT,
    OPERATOR_PROMPTS,
    FEW_SHOT_EXAMPLES,
)


class TestLLMPromptBuilding:
    """Tests for prompt building functions."""
    
    def test_build_conversion_prompt_basic(self):
        """Test building a basic conversion prompt."""
        # GIVEN a text to convert
        text = "All contractors must pay taxes"
        
        # WHEN building a prompt
        prompt = build_conversion_prompt(text, include_examples=False)
        
        # THEN it should contain system prompt and input text
        assert SYSTEM_PROMPT in prompt
        assert text in prompt
        assert "Output:" in prompt
    
    def test_build_conversion_prompt_with_examples(self):
        """Test building prompt with few-shot examples."""
        # GIVEN a text to convert
        text = "All contractors must pay taxes"
        
        # WHEN building a prompt with examples
        prompt = build_conversion_prompt(text, include_examples=True, complexity="basic")
        
        # THEN it should contain examples
        assert "Examples:" in prompt
        assert "All contractors must pay taxes" in prompt  # Example text
        assert "∀x.(Contractor(x) → O(PayTaxes(x)))" in prompt  # Example output
    
    def test_build_conversion_prompt_with_operator_hints(self):
        """Test building prompt with operator-specific hints."""
        # GIVEN a text and operator hints
        text = "All contractors must pay taxes"
        hints = ["universal", "obligation"]
        
        # WHEN building a prompt with hints
        prompt = build_conversion_prompt(text, operator_hints=hints)
        
        # THEN it should contain operator hints
        assert "Relevant operators:" in prompt
        assert OPERATOR_PROMPTS["universal"] in prompt
        assert OPERATOR_PROMPTS["obligation"] in prompt
    
    def test_build_validation_prompt(self):
        """Test building validation prompt."""
        # GIVEN a formula
        formula = "∀x.(Contractor(x) → O(PayTaxes(x)))"
        
        # WHEN building a validation prompt
        prompt = build_validation_prompt(formula)
        
        # THEN it should contain formula and validation instructions
        assert formula in prompt
        assert "syntax correctness" in prompt.lower()
        assert "quantifiers" in prompt.lower()
    
    def test_build_error_correction_prompt(self):
        """Test building error correction prompt."""
        # GIVEN a formula with errors
        formula = "∀x.Contractor(x) → O(PayTaxes(x))"  # Missing parentheses
        errors = ["Missing parentheses around implication"]
        
        # WHEN building an error correction prompt
        prompt = build_error_correction_prompt(formula, errors)
        
        # THEN it should contain formula and errors
        assert formula in prompt
        assert errors[0] in prompt
        assert "corrected version" in prompt.lower()


class TestGetOperatorHints:
    """Tests for operator hint detection."""
    
    def test_detect_universal_quantifier(self):
        """Test detecting universal quantifier keywords."""
        # GIVEN text with universal quantifiers
        texts = [
            "All contractors must pay taxes",
            "Every employee must complete training",
            "Each manager must review reports"
        ]
        
        # WHEN getting operator hints
        results = [get_operator_hints_for_text(text) for text in texts]
        
        # THEN all should detect universal quantifier
        assert all("universal" in hints for hints in results)
    
    def test_detect_obligation(self):
        """Test detecting obligation keywords."""
        # GIVEN text with obligations
        texts = [
            "Contractors must pay taxes",
            "Employees are required to attend",
            "Managers shall review reports"
        ]
        
        # WHEN getting operator hints
        results = [get_operator_hints_for_text(text) for text in texts]
        
        # THEN all should detect obligation
        assert all("obligation" in hints for hints in results)
    
    def test_detect_permission(self):
        """Test detecting permission keywords."""
        # GIVEN text with permissions
        texts = [
            "Employees may take vacation",
            "Users are allowed to edit",
            "Members can access resources"
        ]
        
        # WHEN getting operator hints
        results = [get_operator_hints_for_text(text) for text in texts]
        
        # THEN all should detect permission
        assert all("permission" in hints for hints in results)
    
    def test_detect_temporal_operators(self):
        """Test detecting temporal keywords."""
        # GIVEN text with temporal operators
        text_always = "Users must always use encryption"
        text_eventually = "Reports will eventually be reviewed"
        
        # WHEN getting operator hints
        hints_always = get_operator_hints_for_text(text_always)
        hints_eventually = get_operator_hints_for_text(text_eventually)
        
        # THEN it should detect temporal operators
        assert "temporal_always" in hints_always
        assert "temporal_eventually" in hints_eventually


class TestLLMResponseCache:
    """Tests for LLM response caching with IPFS CIDs."""
    
    def test_cache_basic_operations(self):
        """Test basic cache put/get operations."""
        # GIVEN a cache
        cache = LLMResponseCache(max_size=10)
        
        # WHEN we store and retrieve a response
        cache.put("test text", "openai", "hash1", "∀x.P(x)", 0.9)
        result = cache.get("test text", "openai", "hash1")
        
        # THEN we get the cached result
        assert result is not None
        formula, confidence = result
        assert formula == "∀x.P(x)"
        assert confidence == 0.9
        assert cache.hits == 1
        assert cache.misses == 0
    
    def test_cache_keys_are_ipfs_cids(self):
        """Test that cache keys are valid IPFS CIDs."""
        pytest.importorskip("multiformats", reason="multiformats library not available")
        from ipfs_datasets_py.logic.TDFOL.nl.utils import validate_cid
        
        # GIVEN a cache
        cache = LLMResponseCache(max_size=10)
        
        # WHEN we create a cache key
        key = cache._make_key("test text", "openai", "hash123")
        
        # THEN it should be a valid IPFS CID
        assert isinstance(key, str)
        assert key.startswith("bafk")  # CIDv1 with base32
        assert validate_cid(key), f"Invalid CID: {key}"
    
    def test_cache_miss(self):
        """Test cache miss behavior."""
        # GIVEN a cache
        cache = LLMResponseCache(max_size=10)
        
        # WHEN we try to get a non-existent item
        result = cache.get("unknown text", "openai", "hash1")
        
        # THEN we get None and miss count increases
        assert result is None
        assert cache.misses == 1
    
    def test_cache_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        # GIVEN a small cache
        cache = LLMResponseCache(max_size=3)
        
        # WHEN we add 4 items
        cache.put("text1", "openai", "hash1", "formula1", 0.9)
        cache.put("text2", "openai", "hash1", "formula2", 0.9)
        cache.put("text3", "openai", "hash1", "formula3", 0.9)
        cache.put("text4", "openai", "hash1", "formula4", 0.9)
        
        # THEN the first item should be evicted
        assert cache.get("text1", "openai", "hash1") is None
        assert cache.get("text4", "openai", "hash1") is not None
    
    def test_cache_stats(self):
        """Test cache statistics."""
        # GIVEN a cache with some operations
        cache = LLMResponseCache(max_size=10)
        cache.put("text1", "openai", "hash1", "formula1", 0.9)
        cache.get("text1", "openai", "hash1")  # Hit
        cache.get("text2", "openai", "hash1")  # Miss
        
        # WHEN getting stats
        stats = cache.stats()
        
        # THEN stats should be correct
        assert stats["size"] == 1
        assert stats["max_size"] == 10
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5


class TestLLMNLConverterIntegration:
    """Integration tests for LLM NL Converter."""
    
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm.TDFOL_NL_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm.LLM_ROUTER_AVAILABLE', False)
    def test_converter_without_llm_router(self):
        """Test converter behavior when LLM router is not available."""
        # Skip if NL dependencies not available
        pytest.importorskip("ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api")
        
        # GIVEN converter without LLM router
        try:
            converter = LLMNLConverter(enable_llm=True)
            # THEN LLM should be disabled
            assert converter.enable_llm is False
        except ImportError:
            pytest.skip("TDFOL NL dependencies not available")
    
    def test_converter_initialization(self):
        """Test converter initialization with various options."""
        # Skip if NL dependencies not available
        pytest.importorskip("ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api")
        
        # WHEN creating converters with different options
        try:
            converter1 = LLMNLConverter(confidence_threshold=0.7)
            converter2 = LLMNLConverter(enable_llm=False)
            converter3 = LLMNLConverter(enable_caching=False)
            
            # THEN options should be set correctly
            assert converter1.confidence_threshold == 0.7
            assert converter2.enable_llm is False
            assert converter3.llm_cache is None
        except ImportError:
            pytest.skip("TDFOL NL dependencies not available")
    
    def test_converter_stats(self):
        """Test converter statistics tracking."""
        # Skip if NL dependencies not available
        pytest.importorskip("ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api")
        
        # GIVEN a converter
        try:
            converter = LLMNLConverter()
            
            # WHEN getting stats
            stats = converter.get_stats()
            
            # THEN stats should have expected keys
            assert "pattern_only" in stats
            assert "llm_fallback" in stats
            assert "llm_failures" in stats
            assert "total_conversions" in stats
        except ImportError:
            pytest.skip("TDFOL NL dependencies not available")


class TestBackwardCompatibility:
    """Tests for backward compatibility with old module structure."""
    
    def test_import_from_old_path_llm_nl_converter(self):
        """Test that old imports still work (via __init__.py exports)."""
        # WHEN importing from old path via package
        from ipfs_datasets_py.logic.TDFOL.nl import (
            LLMNLConverter,
            LLMResponseCache,
            LLMParseResult
        )
        
        # THEN imports should succeed
        assert LLMNLConverter is not None
        assert LLMResponseCache is not None
        assert LLMParseResult is not None
    
    def test_import_prompt_functions(self):
        """Test importing prompt building functions."""
        # WHEN importing from package
        from ipfs_datasets_py.logic.TDFOL.nl import (
            build_conversion_prompt,
            build_validation_prompt,
            build_error_correction_prompt,
            get_operator_hints_for_text
        )
        
        # THEN imports should succeed
        assert callable(build_conversion_prompt)
        assert callable(build_validation_prompt)
        assert callable(build_error_correction_prompt)
        assert callable(get_operator_hints_for_text)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
