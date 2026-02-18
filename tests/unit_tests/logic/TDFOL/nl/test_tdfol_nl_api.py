"""
Tests for TDFOL Natural Language API.

Tests the unified parse_natural_language() API and end-to-end functionality.
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.nl import tdfol_nl_api

# Mark all tests to skip if spaCy is not installed
pytest.importorskip("spacy", reason="spaCy not installed")

try:
    from ipfs_datasets_py.logic.TDFOL.nl import (
        parse_natural_language,
        parse_natural_language_batch,
        NLParser,
        ParseOptions,
        ParseResult,
    )
    DEPENDENCIES_AVAILABLE = True
except ImportError:
    DEPENDENCIES_AVAILABLE = False


@pytest.mark.skipif(not DEPENDENCIES_AVAILABLE, reason="NL dependencies not available")
class TestParseNaturalLanguage:
    """Test parse_natural_language() function."""
    
    def test_simple_obligation(self):
        """Test parsing simple obligation sentence."""
        result = parse_natural_language("Contractors must pay taxes.")
        
        assert result.success
        assert result.num_formulas > 0
        assert any("O(" in f.formula_string for f in result.formulas)
    
    def test_universal_quantification(self):
        """Test parsing universal quantification."""
        result = parse_natural_language("All contractors must pay taxes.")
        
        assert result.success
        assert result.num_formulas > 0
        # Should have universal quantifier
        assert any("∀" in f.formula_string or "forall" in f.formula_string.lower() 
                   for f in result.formulas)
    
    def test_permission(self):
        """Test parsing permission sentence."""
        result = parse_natural_language("Employees may request vacation.")
        
        assert result.success
        assert result.num_formulas > 0
        assert any("P(" in f.formula_string for f in result.formulas)
    
    def test_prohibition(self):
        """Test parsing prohibition sentence."""
        result = parse_natural_language("Contractors must not disclose information.")
        
        assert result.success
        assert result.num_formulas > 0
        assert any("F(" in f.formula_string for f in result.formulas)
    
    def test_temporal_always(self):
        """Test parsing temporal 'always' sentence."""
        result = parse_natural_language("Payment must always be made.")
        
        assert result.success
        assert result.num_formulas > 0
        # Should have temporal operator (box)
        assert any("□" in f.formula_string or "always" in f.formula_string.lower()
                   for f in result.formulas)
    
    def test_conditional(self):
        """Test parsing conditional sentence."""
        result = parse_natural_language(
            "If payment is received then goods must be delivered."
        )
        
        assert result.success
        assert result.num_formulas > 0
        # Should have implication
        assert any("→" in f.formula_string or "->" in f.formula_string
                   for f in result.formulas)
    
    def test_confidence_threshold(self):
        """Test min_confidence filtering."""
        # High threshold should return fewer results
        result_high = parse_natural_language(
            "All contractors must pay taxes.",
            min_confidence=0.9
        )
        result_low = parse_natural_language(
            "All contractors must pay taxes.",
            min_confidence=0.3
        )
        
        assert result_high.success
        assert result_low.success
        # Lower threshold should match more patterns
        assert result_low.num_formulas >= result_high.num_formulas
    
    def test_metadata_inclusion(self):
        """Test metadata inclusion in results."""
        result = parse_natural_language(
            "All contractors must pay taxes within 30 days.",
            include_metadata=True
        )
        
        assert result.success
        assert result.metadata
        assert 'num_entities' in result.metadata
        assert 'num_patterns' in result.metadata
        assert 'entities' in result.metadata
    
    def test_empty_text(self):
        """Test handling of empty text."""
        result = parse_natural_language("")
        
        # Should handle gracefully
        assert result.num_formulas == 0
    
    def test_nonsense_text(self):
        """Test handling of nonsense text."""
        result = parse_natural_language("xyzzy abracadabra foobar")
        
        # Should not crash, may have no formulas
        assert result.num_formulas == 0 or result.num_formulas > 0


@pytest.mark.skipif(not DEPENDENCIES_AVAILABLE, reason="NL dependencies not available")
class TestNLParser:
    """Test NLParser class with state."""
    
    def test_parser_initialization(self):
        """Test parser initialization."""
        parser = NLParser()
        assert parser is not None
        assert parser.options is not None
    
    def test_parser_with_options(self):
        """Test parser with custom options."""
        options = ParseOptions(
            min_confidence=0.7,
            include_metadata=False,
            resolve_context=True
        )
        parser = NLParser(options)
        
        assert parser.options.min_confidence == 0.7
        assert not parser.options.include_metadata
        assert parser.options.resolve_context
    
    def test_stateful_parsing(self):
        """Test stateful parsing with context."""
        parser = NLParser()
        
        # First sentence establishes context
        result1 = parser.parse("Contractors must submit reports.")
        assert result1.success
        
        # Second sentence uses context
        result2 = parser.parse("They shall do so within 30 days.")
        assert result2.success
    
    def test_caching(self):
        """Test parsing cache."""
        parser = NLParser()
        
        # First parse
        result1 = parser.parse("All contractors must pay taxes.")
        time1 = result1.parse_time_ms
        
        # Second parse (should be cached)
        result2 = parser.parse("All contractors must pay taxes.")
        time2 = result2.parse_time_ms
        
        assert result1.success
        assert result2.success
        # Cached result should be much faster
        assert time2 < time1 or time2 == 0.0
    
    def test_clear_cache(self):
        """Test cache clearing."""
        parser = NLParser()
        
        # Parse and cache
        parser.parse("Contractors must pay taxes.")
        assert len(parser._cache) > 0
        
        # Clear cache
        parser.clear_cache()
        assert len(parser._cache) == 0
    
    def test_reset_context(self):
        """Test context reset."""
        options = ParseOptions(resolve_context=True)
        parser = NLParser(options)
        
        # Parse with context
        parser.parse("Contractors must submit reports.")
        assert parser.context is not None
        
        # Reset context
        parser.reset_context()
        # Should have new empty context
        assert parser.context is not None
        assert len(parser.context.entities) == 0


@pytest.mark.skipif(not DEPENDENCIES_AVAILABLE, reason="NL dependencies not available")
class TestBatchParsing:
    """Test batch parsing functionality."""
    
    def test_batch_parsing(self):
        """Test parsing multiple texts."""
        texts = [
            "All contractors must pay taxes.",
            "Employees may request vacation.",
            "Disclosure is forbidden."
        ]
        
        results = parse_natural_language_batch(texts)
        
        assert len(results) == len(texts)
        for result in results:
            assert result.success
            assert result.num_formulas > 0
    
    def test_batch_with_context(self):
        """Test batch parsing with context resolution."""
        texts = [
            "Contractors must submit reports.",
            "They shall file within 30 days.",
            "Failure to comply may result in penalties."
        ]
        
        results = parse_natural_language_batch(texts, resolve_context=True)
        
        assert len(results) == len(texts)
        for result in results:
            assert result.success
    
    def test_empty_batch(self):
        """Test empty batch."""
        results = parse_natural_language_batch([])
        assert len(results) == 0


@pytest.mark.skipif(not DEPENDENCIES_AVAILABLE, reason="NL dependencies not available")
class TestComplexSentences:
    """Test parsing of complex, real-world sentences."""
    
    def test_complex_legal_sentence(self):
        """Test complex legal sentence."""
        result = parse_natural_language(
            "All licensed contractors must submit quarterly tax reports "
            "within 30 days of the end of each quarter."
        )
        
        assert result.success
        assert result.num_formulas > 0
    
    def test_multiple_clauses(self):
        """Test sentence with multiple clauses."""
        result = parse_natural_language(
            "If a contractor fails to pay taxes within 30 days, "
            "then they must pay a penalty."
        )
        
        assert result.success
        assert result.num_formulas > 0
    
    def test_negation_and_obligation(self):
        """Test sentence with negation and obligation."""
        result = parse_natural_language(
            "Contractors must not disclose confidential client information "
            "to third parties."
        )
        
        assert result.success
        assert result.num_formulas > 0


@pytest.mark.skipif(not DEPENDENCIES_AVAILABLE, reason="NL dependencies not available")
class TestErrorHandling:
    """Test error handling."""
    
    def test_no_patterns_matched(self):
        """Test handling when no patterns match."""
        result = parse_natural_language(
            "The quick brown fox jumps over the lazy dog."
        )
        
        # Should not crash, may have warnings
        assert len(result.warnings) > 0 or result.num_formulas == 0
    
    def test_very_long_text(self):
        """Test handling of very long text."""
        long_text = "Contractors must pay taxes. " * 100
        result = parse_natural_language(long_text)
        
        # Should handle without crashing
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
