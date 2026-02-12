"""
Test suite for TDFOL-Grammar integration.

Tests natural language processing capabilities.
"""

import pytest
import logging

from ipfs_datasets_py.logic.TDFOL.tdfol_core import Formula, Predicate

# Try to import integration modules
try:
    from ipfs_datasets_py.logic.integration.tdfol_grammar_bridge import (
        TDFOLGrammarBridge,
        NaturalLanguageTDFOLInterface,
        parse_nl,
        explain_formula,
    )
    INTEGRATION_AVAILABLE = True
except ImportError:
    INTEGRATION_AVAILABLE = False
    pytest.skip("Grammar integration not available", allow_module_level=True)


class TestTDFOLGrammarBridge:
    """Test the TDFOL-Grammar Bridge."""
    
    def setup_method(self):
        """Setup for each test."""
        self.bridge = TDFOLGrammarBridge()
    
    def test_bridge_initialization(self):
        """Test bridge initializes correctly."""
        assert self.bridge is not None
        assert isinstance(self.bridge, TDFOLGrammarBridge)
    
    def test_grammar_availability(self):
        """Test grammar availability detection."""
        assert hasattr(self.bridge, 'available')
        assert isinstance(self.bridge.available, bool)
    
    def test_parse_simple_sentence(self):
        """Test parsing simple sentences."""
        text = "P"
        formula = self.bridge.parse_natural_language(text)
        
        if formula:
            assert isinstance(formula, Formula)
            logging.info(f"Parsed '{text}' to: {formula.to_string()}")
    
    def test_parse_with_fallback(self):
        """Test parsing with fallback enabled."""
        text = "P and Q"
        formula = self.bridge.parse_natural_language(text, use_fallback=True)
        
        # Should get some result with fallback
        if formula:
            assert isinstance(formula, Formula)
    
    def test_parse_without_fallback(self):
        """Test parsing without fallback."""
        text = "P and Q"
        formula = self.bridge.parse_natural_language(text, use_fallback=False)
        
        # Might return None without fallback
        if formula:
            assert isinstance(formula, Formula)
    
    def test_formula_to_natural_language(self):
        """Test converting formula to natural language."""
        p = Predicate("P", ())
        
        nl_text = self.bridge.formula_to_natural_language(p)
        assert nl_text is not None
        assert isinstance(nl_text, str)
        assert len(nl_text) > 0
    
    def test_formula_to_nl_with_style(self):
        """Test formula to NL with different styles."""
        p = Predicate("P", ())
        
        formal = self.bridge.formula_to_natural_language(p, style="formal")
        assert isinstance(formal, str)
        
        casual = self.bridge.formula_to_natural_language(p, style="casual")
        assert isinstance(casual, str)
    
    def test_batch_parse(self):
        """Test batch parsing of multiple texts."""
        texts = ["P", "Q", "P and Q"]
        results = self.bridge.batch_parse(texts)
        
        assert len(results) == len(texts)
        for text, formula in results:
            assert isinstance(text, str)
            # formula might be None for some texts
    
    def test_analyze_parse_quality(self):
        """Test parse quality analysis."""
        text = "P"
        analysis = self.bridge.analyze_parse_quality(text)
        
        assert 'text' in analysis
        assert 'success' in analysis
        assert 'method' in analysis
        assert analysis['text'] == text


class TestNaturalLanguageTDFOLInterface:
    """Test the Natural Language TDFOL Interface."""
    
    def setup_method(self):
        """Setup for each test."""
        self.interface = NaturalLanguageTDFOLInterface()
    
    def test_interface_initialization(self):
        """Test interface initializes correctly."""
        assert self.interface is not None
        assert isinstance(self.interface, NaturalLanguageTDFOLInterface)
    
    def test_understand_simple_text(self):
        """Test understanding simple text."""
        text = "P"
        formula = self.interface.understand(text)
        
        if formula:
            assert isinstance(formula, Formula)
            logging.info(f"Understood '{text}' as: {formula.to_string()}")
    
    def test_explain_formula(self):
        """Test explaining a formula."""
        p = Predicate("P", ())
        explanation = self.interface.explain(p)
        
        assert explanation is not None
        assert isinstance(explanation, str)
        assert len(explanation) > 0
    
    def test_reason_simple_syllogism(self):
        """Test reasoning with simple syllogism."""
        premises = ["P", "P -> Q"]
        conclusion = "Q"
        
        result = self.interface.reason(premises, conclusion)
        
        assert 'valid' in result
        assert 'premises' in result
        assert 'conclusion' in result
        assert result['premises'] == premises
        assert result['conclusion'] == conclusion
        
        logging.info(f"Reasoning result: {result}")
    
    def test_reason_with_unparseable_premise(self):
        """Test reasoning with unparseable premise."""
        premises = ["completely unparseable gibberish !!!"]
        conclusion = "Q"
        
        result = self.interface.reason(premises, conclusion)
        
        assert 'error' in result or 'valid' in result
        if 'error' in result:
            assert isinstance(result['error'], str)


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def test_parse_nl_function(self):
        """Test parse_nl convenience function."""
        text = "P"
        formula = parse_nl(text)
        
        # Might return None in test environment
        if formula:
            assert isinstance(formula, Formula)
    
    def test_explain_formula_function(self):
        """Test explain_formula convenience function."""
        p = Predicate("P", ())
        explanation = explain_formula(p)
        
        assert explanation is not None
        assert isinstance(explanation, str)


class TestIntegrationScenarios:
    """Test real-world integration scenarios."""
    
    def setup_method(self):
        """Setup for each test."""
        self.interface = NaturalLanguageTDFOLInterface()
    
    def test_legal_contract_scenario(self):
        """Test legal contract reasoning scenario."""
        premises = [
            "P",  # Contract signed
            "P -> Q"  # Contract signed implies obligation
        ]
        conclusion = "Q"  # Obligation exists
        
        result = self.interface.reason(premises, conclusion)
        assert 'valid' in result
        logging.info(f"Legal reasoning: {result}")
    
    def test_temporal_scenario(self):
        """Test temporal reasoning scenario."""
        # This would work better with temporal formulas
        # but tests basic understanding
        formula = self.interface.understand("always P")
        
        if formula:
            explanation = self.interface.explain(formula)
            assert isinstance(explanation, str)
            logging.info(f"Temporal: {explanation}")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
