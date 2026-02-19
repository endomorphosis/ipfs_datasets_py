"""
Comprehensive tests for LLM-enhanced NL to TDFOL converter.

Tests cover pattern-only, LLM-only, hybrid approaches, caching,
confidence scoring, and error handling.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter import (
    LLMNLConverter,
    LLMResponseCache,
    LLMParseResult
)
from ipfs_datasets_py.logic.TDFOL.nl.llm_nl_prompts import (
    build_conversion_prompt,
    get_operator_hints_for_text
)


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
        from ipfs_datasets_py.logic.TDFOL.nl.cache_utils import validate_cid
        
        # GIVEN a cache
        cache = LLMResponseCache(max_size=10)
        
        # WHEN we create a cache key
        key = cache._make_key("test text", "openai", "hash123")
        
        # THEN it should be a valid IPFS CID
        assert isinstance(key, str)
        assert key.startswith("bafk")  # CIDv1 with base32
        assert validate_cid(key), f"Invalid CID: {key}"
    
    def test_cache_key_determinism(self):
        """Test that cache keys are deterministic."""
        # GIVEN a cache
        cache = LLMResponseCache(max_size=10)
        
        # WHEN we create the same key multiple times
        key1 = cache._make_key("test", "openai", "hash1")
        key2 = cache._make_key("test", "openai", "hash1")
        key3 = cache._make_key("test", "openai", "hash1")
        
        # THEN all keys should be identical
        assert key1 == key2 == key3
    
    def test_cache_key_uniqueness(self):
        """Test that different inputs produce different cache keys."""
        # GIVEN a cache
        cache = LLMResponseCache(max_size=10)
        
        # WHEN we create keys with different inputs
        key1 = cache._make_key("text1", "openai", "hash1")
        key2 = cache._make_key("text2", "openai", "hash1")
        key3 = cache._make_key("text1", "anthropic", "hash1")
        key4 = cache._make_key("text1", "openai", "hash2")
        
        # THEN all keys should be different
        keys = [key1, key2, key3, key4]
        assert len(keys) == len(set(keys)), "Cache keys should be unique"
    
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
        
        # WHEN we add more items than capacity
        cache.put("text1", "openai", "hash1", "formula1", 0.9)
        cache.put("text2", "openai", "hash2", "formula2", 0.9)
        cache.put("text3", "openai", "hash3", "formula3", 0.9)
        cache.put("text4", "openai", "hash4", "formula4", 0.9)  # Should evict text1
        
        # THEN oldest item is evicted
        assert cache.get("text1", "openai", "hash1") is None  # Evicted
        assert cache.get("text2", "openai", "hash2") is not None  # Still there
        assert len(cache.cache) == 3


class TestPatternOnlyConversion:
    """Tests for pattern-based conversion (no LLM)."""
    
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.TDFOL_NL_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.LLM_ROUTER_AVAILABLE', False)
    def test_pattern_only_high_confidence(self):
        """Test pattern conversion with high confidence (no LLM needed)."""
        # GIVEN a converter with LLM disabled
        with patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.NLParser') as mock_parser_class:
            mock_parser = Mock()
            mock_parser_class.return_value = mock_parser
            
            # Mock high-confidence pattern result
            mock_result = Mock()
            mock_result.success = True
            mock_result.confidence = 0.9
            mock_result.formulas = [Mock(formula_string="∀x.(Contractor(x) → O(PayTaxes(x)))")]
            mock_parser.parse.return_value = mock_result
            
            converter = LLMNLConverter(confidence_threshold=0.85, enable_llm=False)
            
            # WHEN we convert text
            result = converter.convert("All contractors must pay taxes.")
            
            # THEN pattern result is used
            assert result.success
            assert result.method == "pattern"
            assert result.confidence >= 0.85
            assert "Contractor" in result.formula
            assert converter.stats["pattern_only"] == 1
    
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.TDFOL_NL_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.LLM_ROUTER_AVAILABLE', False)
    def test_pattern_only_low_confidence_fails(self):
        """Test pattern conversion with low confidence fails without LLM."""
        # GIVEN a converter with LLM disabled
        with patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.NLParser') as mock_parser_class:
            mock_parser = Mock()
            mock_parser_class.return_value = mock_parser
            
            # Mock low-confidence pattern result
            mock_result = Mock()
            mock_result.success = True
            mock_result.confidence = 0.6
            mock_result.formulas = [Mock(formula_string="some_formula")]
            mock_parser.parse.return_value = mock_result
            
            converter = LLMNLConverter(confidence_threshold=0.85, enable_llm=False)
            
            # WHEN we convert text
            result = converter.convert("Complex ambiguous text.")
            
            # THEN conversion fails
            assert not result.success
            assert result.method == "failed"
            assert "not available" in result.errors[0].lower()


class TestLLMOnlyConversion:
    """Tests for LLM-only conversion (skipping pattern)."""
    
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.TDFOL_NL_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.LLM_ROUTER_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.get_default_router')
    def test_force_llm_conversion(self, mock_get_router):
        """Test forcing LLM conversion (skip pattern)."""
        # GIVEN a converter with force_llm
        with patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.NLParser'):
            mock_router = Mock()
            mock_router.generate.return_value = "Output: ∀x.(Manager(x) → O(Review(x)))"
            mock_get_router.return_value = mock_router
            
            converter = LLMNLConverter(enable_llm=True, enable_caching=False)
            
            # WHEN we convert with force_llm=True
            result = converter.convert("All managers must review.", force_llm=True)
            
            # THEN LLM is used directly
            assert result.success
            assert result.method == "llm"
            assert mock_router.generate.called
    
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.TDFOL_NL_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.LLM_ROUTER_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.get_default_router')
    def test_llm_provider_selection(self, mock_get_router):
        """Test selecting specific LLM provider."""
        # GIVEN a converter
        with patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.NLParser'):
            mock_router = Mock()
            mock_router.generate.return_value = "∀x.P(x)"
            mock_get_router.return_value = mock_router
            
            converter = LLMNLConverter(enable_llm=True, enable_caching=False)
            
            # WHEN we convert with specific provider
            result = converter.convert("Test", provider="gemini", force_llm=True)
            
            # THEN provider is passed to router
            assert result.llm_provider == "gemini"
            call_args = mock_router.generate.call_args
            assert call_args[1]["provider"] == "gemini"


class TestHybridConversion:
    """Tests for hybrid pattern+LLM conversion."""
    
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.TDFOL_NL_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.LLM_ROUTER_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.get_default_router')
    def test_hybrid_llm_fallback(self, mock_get_router):
        """Test LLM fallback when pattern confidence is low."""
        # GIVEN a converter with both pattern and LLM
        with patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.NLParser') as mock_parser_class:
            mock_parser = Mock()
            mock_parser_class.return_value = mock_parser
            
            # Mock low-confidence pattern result
            mock_pattern_result = Mock()
            mock_pattern_result.success = True
            mock_pattern_result.confidence = 0.7
            mock_pattern_result.formulas = [Mock(formula_string="pattern_formula")]
            mock_parser.parse.return_value = mock_pattern_result
            
            # Mock LLM response
            mock_router = Mock()
            mock_router.generate.return_value = "Output: llm_formula"
            mock_get_router.return_value = mock_router
            
            converter = LLMNLConverter(confidence_threshold=0.85, enable_llm=True, enable_caching=False)
            
            # WHEN we convert text
            result = converter.convert("Ambiguous text")
            
            # THEN LLM is used as fallback
            assert result.success
            assert result.method == "hybrid"
            assert converter.stats["llm_fallback"] == 1


class TestConfidenceScoring:
    """Tests for confidence score calculations."""
    
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.TDFOL_NL_AVAILABLE', True)
    def test_confidence_threshold_check(self):
        """Test confidence threshold comparison."""
        # GIVEN a converter with specific threshold
        with patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.NLParser') as mock_parser_class:
            mock_parser = Mock()
            mock_parser_class.return_value = mock_parser
            
            converter = LLMNLConverter(confidence_threshold=0.8, enable_llm=False)
            
            # WHEN pattern confidence equals threshold
            mock_result = Mock(success=True, confidence=0.8, formulas=[Mock(formula_string="formula")])
            mock_parser.parse.return_value = mock_result
            result1 = converter.convert("Text 1")
            
            # WHEN pattern confidence is just below threshold
            mock_result.confidence = 0.79
            mock_parser.parse.return_value = mock_result
            result2 = converter.convert("Text 2")
            
            # THEN threshold is properly enforced
            assert result1.success  # >= threshold
            assert not result2.success  # < threshold (no LLM)
    
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.TDFOL_NL_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.LLM_ROUTER_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.get_default_router')
    def test_best_result_selection(self, mock_get_router):
        """Test selection of best result between pattern and LLM."""
        # GIVEN a converter with both methods
        with patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.NLParser') as mock_parser_class:
            mock_parser = Mock()
            mock_parser_class.return_value = mock_parser
            
            # Pattern result with 0.7 confidence
            mock_pattern_result = Mock()
            mock_pattern_result.success = True
            mock_pattern_result.confidence = 0.7
            mock_pattern_result.formulas = [Mock(formula_string="pattern_formula")]
            mock_parser.parse.return_value = mock_pattern_result
            
            # LLM returns higher confidence formula
            mock_router = Mock()
            mock_router.generate.return_value = "∀x.(P(x) → Q(x))"
            mock_get_router.return_value = mock_router
            
            converter = LLMNLConverter(confidence_threshold=0.85, enable_llm=True, enable_caching=False)
            result = converter.convert("Test")
            
            # THEN LLM formula is selected (higher confidence)
            assert result.method == "hybrid"
            assert "∀x" in result.formula


class TestCachingMechanism:
    """Tests for LLM response caching."""
    
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.TDFOL_NL_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.LLM_ROUTER_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.get_default_router')
    def test_cache_hit_on_repeat(self, mock_get_router):
        """Test cache hit on repeated conversion."""
        # GIVEN a converter with caching enabled
        with patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.NLParser'):
            mock_router = Mock()
            mock_router.generate.return_value = "∀x.P(x)"
            mock_get_router.return_value = mock_router
            
            converter = LLMNLConverter(enable_llm=True, enable_caching=True)
            
            # WHEN we convert same text twice
            result1 = converter.convert("Test text", force_llm=True)
            result2 = converter.convert("Test text", force_llm=True)
            
            # THEN second call hits cache
            assert not result1.cache_hit
            assert result2.cache_hit
            assert mock_router.generate.call_count == 1  # Only called once
    
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.TDFOL_NL_AVAILABLE', True)
    def test_cache_stats(self):
        """Test cache statistics tracking."""
        # GIVEN a converter with caching
        with patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.NLParser'):
            converter = LLMNLConverter(enable_caching=True)
            
            # WHEN we check stats
            stats = converter.get_stats()
            
            # THEN cache stats are included
            assert "cache" in stats
            assert "size" in stats["cache"]
            assert "hit_rate" in stats["cache"]


class TestErrorHandling:
    """Tests for error handling and fallback behavior."""
    
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.TDFOL_NL_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.LLM_ROUTER_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.get_default_router')
    def test_llm_failure_fallback_to_pattern(self, mock_get_router):
        """Test fallback to pattern result when LLM fails."""
        # GIVEN a converter with LLM that will fail
        with patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.NLParser') as mock_parser_class:
            mock_parser = Mock()
            mock_parser_class.return_value = mock_parser
            
            # Pattern result available
            mock_pattern_result = Mock()
            mock_pattern_result.success = True
            mock_pattern_result.confidence = 0.7
            mock_pattern_result.formulas = [Mock(formula_string="fallback_formula")]
            mock_parser.parse.return_value = mock_pattern_result
            
            # LLM will raise exception
            mock_router = Mock()
            mock_router.generate.side_effect = Exception("LLM API error")
            mock_get_router.return_value = mock_router
            
            converter = LLMNLConverter(confidence_threshold=0.85, enable_llm=True, enable_caching=False)
            
            # WHEN we convert text
            result = converter.convert("Test text")
            
            # THEN pattern result is used as fallback
            assert result.success
            assert result.method == "pattern_fallback"
            assert result.formula == "fallback_formula"
            assert len(result.errors) > 0
            assert converter.stats["llm_failures"] == 1
    
    @patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.TDFOL_NL_AVAILABLE', True)
    def test_pattern_parse_exception_handling(self):
        """Test handling of pattern parser exceptions."""
        # GIVEN a converter with failing pattern parser
        with patch('ipfs_datasets_py.logic.TDFOL.nl.llm_nl_converter.NLParser') as mock_parser_class:
            mock_parser = Mock()
            mock_parser_class.return_value = mock_parser
            mock_parser.parse.side_effect = Exception("Pattern error")
            
            converter = LLMNLConverter(enable_llm=False)
            
            # WHEN we convert text
            result = converter.convert("Test text")
            
            # THEN error is handled gracefully
            assert not result.success


class TestPromptBuilding:
    """Tests for prompt template building."""
    
    def test_basic_prompt_building(self):
        """Test basic prompt construction."""
        # WHEN we build a prompt
        prompt = build_conversion_prompt("All X must Y", include_examples=False)
        
        # THEN prompt includes system instructions and input
        assert "TDFOL" in prompt
        assert "All X must Y" in prompt
    
    def test_prompt_with_examples(self):
        """Test prompt with few-shot examples."""
        # WHEN we build a prompt with examples
        prompt = build_conversion_prompt("Test", include_examples=True, complexity="basic")
        
        # THEN examples are included
        assert "Examples:" in prompt
        assert "contractors" in prompt.lower()
    
    def test_operator_hints_detection(self):
        """Test automatic operator hint detection."""
        # WHEN we analyze text for operators
        hints1 = get_operator_hints_for_text("All contractors must pay taxes")
        hints2 = get_operator_hints_for_text("Some users may access the system")
        hints3 = get_operator_hints_for_text("Users shall not delete files")
        
        # THEN correct hints are detected
        assert "universal" in hints1
        assert "obligation" in hints1
        assert "existential" in hints2
        assert "permission" in hints2
        assert "forbidden" in hints3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
