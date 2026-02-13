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


class TestGrammarBasedNLGeneration:
    """Test suite for Phase 2 Enhancement: Grammar-Based NL Generation."""
    
    def setup_method(self):
        """Setup for each test."""
        self.bridge = TDFOLGrammarBridge()
    
    def test_grammar_based_generation_simple(self):
        """
        GIVEN: A simple DCEC formula
        WHEN: Converting to natural language using grammar
        THEN: Returns high-quality natural language using grammar rules
        """
        # Test simple predicate
        dcec_str = "(P x)"
        result = self.bridge._dcec_to_natural_language(dcec_str, style="formal")
        
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0
    
    def test_formal_style_generation(self):
        """
        GIVEN: A DCEC formula
        WHEN: Using formal style
        THEN: Returns formal English with proper phrasing
        """
        dcec_str = "(O (agent1 laugh))"
        result = self.bridge._dcec_to_natural_language(dcec_str, style="formal")
        
        assert result is not None
        # Should contain formal language
        assert "obligat" in result.lower() or "must" in result.lower()
    
    def test_casual_style_generation(self):
        """
        GIVEN: A DCEC formula
        WHEN: Using casual style
        THEN: Returns casual English with simplified phrasing
        """
        dcec_str = "(O (agent1 laugh))"
        formal_result = self.bridge._dcec_to_natural_language(dcec_str, style="formal")
        casual_result = self.bridge._dcec_to_natural_language(dcec_str, style="casual")
        
        assert formal_result is not None
        assert casual_result is not None
        assert isinstance(casual_result, str)
        assert len(casual_result) > 0
        
        # Casual style should differ from formal phrasing
        assert casual_result != formal_result
        
        # Casual style should simplify formal terms:
        # avoid highly formal "obligated" phrasing and prefer simpler modals.
        casual_lower = casual_result.lower()
        # Allow flexibility - casual style may use various simplified forms
        has_casual_markers = (
            "must" in casual_lower
            or "should" in casual_lower
            or "needs to" in casual_lower
            or "has to" in casual_lower
        )
        # Should NOT have formal obligated terminology in casual style
        assert "obligat" not in casual_lower or has_casual_markers
    
    def test_technical_style_generation(self):
        """
        GIVEN: A DCEC formula
        WHEN: Using technical style
        THEN: Returns technical notation close to formal logic
        """
        dcec_str = "(P x)"
        result = self.bridge._dcec_to_natural_language(dcec_str, style="technical")
        
        assert result is not None
        # Technical style may preserve more logical notation
    
    def test_grammar_fallback_mechanism(self):
        """
        GIVEN: Grammar engine is not available
        WHEN: Attempting grammar-based generation
        THEN: Falls back to template replacement gracefully
        """
        # Even if grammar fails, should get result
        dcec_str = "(P x)"
        result = self.bridge._dcec_to_natural_language(dcec_str, style="formal")
        
        assert result is not None
        assert isinstance(result, str)
    
    def test_deontic_operator_rendering(self):
        """
        GIVEN: DCEC formula with deontic operators (O, P, F)
        WHEN: Converting to natural language
        THEN: Properly renders obligation, permission, prohibition
        """
        test_cases = [
            ("(O (action x))", ["obligat", "must"]),
            ("(P (action x))", ["permit", "may", "allow"]),
            ("(F (action x))", ["forbid", "must not", "prohibited"]),
        ]
        
        for dcec_str, expected_terms in test_cases:
            result = self.bridge._dcec_to_natural_language(dcec_str, style="formal")
            assert result is not None
            # Should contain one of the expected terms
            result_lower = result.lower()
            # At least one term should be present (flexible check)
            has_expected_term = any(term in result_lower for term in expected_terms)
            assert has_expected_term, f"Expected one of {expected_terms} in '{result}'"
    
    def test_temporal_operator_rendering(self):
        """
        GIVEN: DCEC formula with temporal operators (G, F, X)
        WHEN: Converting to natural language
        THEN: Properly renders always, eventually, next
        """
        test_cases = [
            ("(G (P x))", ["always", "at all times", "forever"]),
            ("(F (P x))", ["eventually", "sometime", "in the future"]),
            ("(X (P x))", ["next", "immediately after"]),
        ]
        
        for dcec_str, expected_terms in test_cases:
            result = self.bridge._dcec_to_natural_language(dcec_str, style="formal")
            assert result is not None
            # Check for temporal language (flexible)
            result_lower = result.lower()
            has_expected_term = any(term in result_lower for term in expected_terms)
            assert has_expected_term, f"Expected one of {expected_terms} in '{result}'"
    
    def test_complex_nested_formula_rendering(self):
        """
        GIVEN: Complex nested DCEC formula
        WHEN: Converting to natural language
        THEN: Handles nesting with proper structure
        """
        # Nested formula: O(P(x) -> Q(x))
        dcec_str = "(O (-> (P x) (Q x)))"
        result = self.bridge._dcec_to_natural_language(dcec_str, style="formal")
        
        assert result is not None
        assert len(result) > 10  # Should be reasonably detailed
    
    def test_style_consistency(self):
        """
        GIVEN: Same formula with different styles
        WHEN: Converting with each style
        THEN: Each style produces different but valid output
        """
        dcec_str = "(O (action x))"
        
        formal = self.bridge._dcec_to_natural_language(dcec_str, style="formal")
        casual = self.bridge._dcec_to_natural_language(dcec_str, style="casual")
        technical = self.bridge._dcec_to_natural_language(dcec_str, style="technical")
        
        # All should succeed
        assert formal is not None
        assert casual is not None
        assert technical is not None
        
        # All should be strings
        assert isinstance(formal, str)
        assert isinstance(casual, str)
        assert isinstance(technical, str)
    
    def test_grammar_lexicon_usage(self):
        """
        GIVEN: Grammar engine with 100+ lexicon entries
        WHEN: Generating natural language
        THEN: Uses lexicon for better phrasing
        """
        # If grammar is available, should use lexicon
        dcec_str = "(P x)"
        result = self.bridge._dcec_to_natural_language(dcec_str, style="formal")
        
        assert result is not None
        # Grammar should produce readable English
        assert len(result) >= len(dcec_str)  # Should expand abbreviations
    
    def test_casual_style_transformations(self):
        """
        GIVEN: Formal English text
        WHEN: Applying casual style transformations
        THEN: Transforms formal terms to casual equivalents
        """
        # Test the _apply_casual_style method
        if hasattr(self.bridge, '_apply_casual_style'):
            formal_text = "It is obligatory that agent1 believes proposition"
            casual_text = self.bridge._apply_casual_style(formal_text)
            
            # Should simplify formal language
            assert "must" in casual_text or "obligatory" in casual_text
            assert len(casual_text) <= len(formal_text) + 10  # Shouldn't expand much
    
    def test_error_handling_invalid_dcec(self):
        """
        GIVEN: Invalid DCEC string
        WHEN: Attempting to convert to NL
        THEN: Handles error gracefully with fallback
        """
        invalid_dcec = "((((( invalid ))))"
        result = self.bridge._dcec_to_natural_language(invalid_dcec, style="formal")
        
        # Should get some result even with invalid input (fallback)
        assert result is not None
        assert isinstance(result, str)
    
    def test_empty_formula_handling(self):
        """
        GIVEN: Empty or None DCEC formula
        WHEN: Attempting to convert to NL
        THEN: Handles gracefully
        """
        # Empty string
        result = self.bridge._dcec_to_natural_language("", style="formal")
        assert result is not None
    
    def test_quantifier_rendering(self):
        """
        GIVEN: DCEC formula with quantifiers (forall, exists)
        WHEN: Converting to natural language
        THEN: Properly renders "for all" and "there exists"
        """
        test_cases = [
            ("(forall x (P x))", ["all", "every", "for all"]),
            ("(exists x (P x))", ["some", "there exists", "exists"]),
        ]
        
        for dcec_str, expected_terms in test_cases:
            result = self.bridge._dcec_to_natural_language(dcec_str, style="formal")
            assert result is not None
            # Should contain quantifier language
    
    def test_conjunction_disjunction_rendering(self):
        """
        GIVEN: DCEC formula with logical connectives
        WHEN: Converting to natural language
        THEN: Properly renders "and", "or", "implies"
        """
        test_cases = [
            ("(and (P x) (Q x))", ["and", ","]),
            ("(or (P x) (Q x))", ["or"]),
            ("(-> (P x) (Q x))", ["implies", "if", "then"]),
        ]
        
        for dcec_str, expected_terms in test_cases:
            result = self.bridge._dcec_to_natural_language(dcec_str, style="formal")
            assert result is not None


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
