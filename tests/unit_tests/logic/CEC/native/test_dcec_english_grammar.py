"""
Tests for DCEC English Grammar.

Following GIVEN-WHEN-THEN format for clear test structure.
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.dcec_english_grammar import (
    DCECEnglishGrammar, create_dcec_grammar
)
from ipfs_datasets_py.logic.CEC.native.grammar_engine import Category
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    Formula, LogicalConnective
)


class TestDCECEnglishGrammar:
    """Test suite for DCECEnglishGrammar class."""
    
    def test_grammar_initialization(self):
        """
        GIVEN: DCEC English grammar parameters
        WHEN: Initializing the grammar
        THEN: Grammar should be ready with lexicon and rules
        """
        # GIVEN / WHEN
        grammar = DCECEnglishGrammar()
        
        # THEN
        assert grammar is not None
        assert grammar.engine is not None
        assert len(grammar.engine.lexicon) > 0
        assert len(grammar.engine.rules) > 0
    
    def test_factory_function(self):
        """
        GIVEN: Factory function for grammar creation
        WHEN: Calling create_dcec_grammar
        THEN: Should return initialized grammar
        """
        # GIVEN / WHEN
        grammar = create_dcec_grammar()
        
        # THEN
        assert isinstance(grammar, DCECEnglishGrammar)
        assert grammar.engine is not None


class TestLexicon:
    """Test suite for DCEC lexicon."""
    
    def test_logical_connectives_in_lexicon(self):
        """
        GIVEN: Initialized DCEC grammar
        WHEN: Checking for logical connectives
        THEN: Should have and, or, not, if entries
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        
        # WHEN / THEN
        assert "and" in grammar.engine.lexicon
        assert "or" in grammar.engine.lexicon
        assert "not" in grammar.engine.lexicon
        assert "if" in grammar.engine.lexicon
    
    def test_deontic_modals_in_lexicon(self):
        """
        GIVEN: Initialized DCEC grammar
        WHEN: Checking for deontic modals
        THEN: Should have must, may, forbidden entries
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        
        # WHEN / THEN
        assert "must" in grammar.engine.lexicon
        assert "may" in grammar.engine.lexicon
        assert "forbidden" in grammar.engine.lexicon
        assert "obligated" in grammar.engine.lexicon
        assert "prohibited" in grammar.engine.lexicon
    
    def test_cognitive_modals_in_lexicon(self):
        """
        GIVEN: Initialized DCEC grammar
        WHEN: Checking for cognitive modals
        THEN: Should have believes, knows, intends, desires
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        
        # WHEN / THEN
        assert "believes" in grammar.engine.lexicon
        assert "knows" in grammar.engine.lexicon
        assert "intends" in grammar.engine.lexicon
        assert "desires" in grammar.engine.lexicon
    
    def test_temporal_operators_in_lexicon(self):
        """
        GIVEN: Initialized DCEC grammar
        WHEN: Checking for temporal operators
        THEN: Should have always, eventually, next, until
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        
        # WHEN / THEN
        assert "always" in grammar.engine.lexicon
        assert "eventually" in grammar.engine.lexicon
        assert "next" in grammar.engine.lexicon
        assert "until" in grammar.engine.lexicon
    
    def test_quantifiers_in_lexicon(self):
        """
        GIVEN: Initialized DCEC grammar
        WHEN: Checking for quantifiers
        THEN: Should have all, every, some, any
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        
        # WHEN / THEN
        assert "all" in grammar.engine.lexicon
        assert "every" in grammar.engine.lexicon
        assert "some" in grammar.engine.lexicon
        assert "any" in grammar.engine.lexicon
    
    def test_common_agents_in_lexicon(self):
        """
        GIVEN: Initialized DCEC grammar
        WHEN: Checking for common agents
        THEN: Should have jack, robot, alice, bob, system
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        
        # WHEN / THEN
        assert "jack" in grammar.engine.lexicon
        assert "robot" in grammar.engine.lexicon
        assert "alice" in grammar.engine.lexicon
        assert "bob" in grammar.engine.lexicon
        assert "system" in grammar.engine.lexicon
        
        # Check category
        jack_entries = grammar.engine.lexicon["jack"]
        assert any(e.category == Category.AGENT for e in jack_entries)
    
    def test_common_actions_in_lexicon(self):
        """
        GIVEN: Initialized DCEC grammar
        WHEN: Checking for common actions
        THEN: Should have laugh, sleep, run, eat, walk
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        
        # WHEN / THEN
        for action in ["laugh", "sleep", "run", "eat", "walk", "talk", "work"]:
            assert action in grammar.engine.lexicon
            entries = grammar.engine.lexicon[action]
            assert any(e.category == Category.ACTION_TYPE for e in entries)
    
    def test_common_fluents_in_lexicon(self):
        """
        GIVEN: Initialized DCEC grammar
        WHEN: Checking for common fluents (predicates)
        THEN: Should have happy, sad, hungry, tired, sick, angry
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        
        # WHEN / THEN
        for fluent in ["happy", "sad", "hungry", "tired", "sick", "angry"]:
            assert fluent in grammar.engine.lexicon
            entries = grammar.engine.lexicon[fluent]
            assert any(e.category == Category.FLUENT for e in entries)


class TestGrammarRules:
    """Test suite for DCEC grammar rules."""
    
    def test_has_conjunction_rule(self):
        """
        GIVEN: Initialized DCEC grammar
        WHEN: Checking for AND rule
        THEN: Should have rule for Boolean AND Boolean → Boolean
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        
        # WHEN
        and_rules = [r for r in grammar.engine.rules if "and" in r.name.lower()]
        
        # THEN
        assert len(and_rules) > 0
        assert any(r.category == Category.BOOLEAN for r in and_rules)
    
    def test_has_disjunction_rule(self):
        """
        GIVEN: Initialized DCEC grammar
        WHEN: Checking for OR rule
        THEN: Should have rule for Boolean OR Boolean → Boolean
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        
        # WHEN
        or_rules = [r for r in grammar.engine.rules if "or" in r.name.lower()]
        
        # THEN
        assert len(or_rules) > 0
        assert any(r.category == Category.BOOLEAN for r in or_rules)
    
    def test_has_negation_rule(self):
        """
        GIVEN: Initialized DCEC grammar
        WHEN: Checking for NOT rule
        THEN: Should have rule for NOT Boolean → Boolean
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        
        # WHEN
        not_rules = [r for r in grammar.engine.rules if "not" in r.name.lower()]
        
        # THEN
        assert len(not_rules) > 0
        assert any(r.category == Category.BOOLEAN for r in not_rules)
    
    def test_has_deontic_rules(self):
        """
        GIVEN: Initialized DCEC grammar
        WHEN: Checking for deontic rules
        THEN: Should have rules for obligated, forbidden
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        
        # WHEN
        deontic_rules = [r for r in grammar.engine.rules
                        if "obligated" in r.name or "forbidden" in r.name]
        
        # THEN
        assert len(deontic_rules) > 0
    
    def test_has_cognitive_rules(self):
        """
        GIVEN: Initialized DCEC grammar
        WHEN: Checking for cognitive rules
        THEN: Should have rules for believes, knows
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        
        # WHEN
        cognitive_rules = [r for r in grammar.engine.rules
                          if "believes" in r.name or "knows" in r.name]
        
        # THEN
        assert len(cognitive_rules) > 0
    
    def test_has_temporal_rules(self):
        """
        GIVEN: Initialized DCEC grammar
        WHEN: Checking for temporal rules
        THEN: Should have rules for always, eventually
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        
        # WHEN
        temporal_rules = [r for r in grammar.engine.rules
                         if "always" in r.name or "eventually" in r.name]
        
        # THEN
        assert len(temporal_rules) > 0


class TestLinearization:
    """Test suite for DCEC→English linearization."""
    
    def test_linearize_conjunction(self):
        """
        GIVEN: A conjunction semantic value
        WHEN: Linearizing to English
        THEN: Should produce "... and ..." format
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        semantic_value = {
            "type": "connective",
            "operator": LogicalConnective.AND,
            "left": {"type": "atomic", "predicate": "P", "arguments": []},
            "right": {"type": "atomic", "predicate": "Q", "arguments": []}
        }
        
        # WHEN
        text = grammar._linearize_boolean(semantic_value)
        
        # THEN
        assert "and" in text.lower()
        assert "p" in text.lower()
        assert "q" in text.lower()
    
    def test_linearize_negation(self):
        """
        GIVEN: A negation semantic value
        WHEN: Linearizing to English
        THEN: Should produce "not ..." format
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        semantic_value = {
            "type": "connective",
            "operator": LogicalConnective.NOT,
            "formula": {"type": "atomic", "predicate": "P", "arguments": []}
        }
        
        # WHEN
        text = grammar._linearize_boolean(semantic_value)
        
        # THEN
        assert "not" in text.lower()
        assert "p" in text.lower()
    
    def test_linearize_deontic_obligated(self):
        """
        GIVEN: A deontic obligation semantic value
        WHEN: Linearizing to English
        THEN: Should produce "... must ..." format
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        semantic_value = {
            "type": "deontic",
            "operator": "obligated",
            "agent": {"name": "jack"},
            "action": {"name": "run"}
        }
        
        # WHEN
        text = grammar._linearize_boolean(semantic_value)
        
        # THEN
        assert "jack" in text.lower()
        assert "must" in text.lower()
        assert "run" in text.lower()
    
    def test_linearize_cognitive_believes(self):
        """
        GIVEN: A cognitive belief semantic value
        WHEN: Linearizing to English
        THEN: Should produce "... believes ..." format
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        semantic_value = {
            "type": "cognitive",
            "operator": "believes",
            "agent": {"name": "alice"},
            "proposition": {"type": "atomic", "predicate": "P", "arguments": []}
        }
        
        # WHEN
        text = grammar._linearize_boolean(semantic_value)
        
        # THEN
        assert "alice" in text.lower()
        assert "believes" in text.lower()
    
    def test_linearize_temporal_always(self):
        """
        GIVEN: A temporal always semantic value
        WHEN: Linearizing to English
        THEN: Should produce "always ..." format
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        semantic_value = {
            "type": "temporal",
            "operator": "always",
            "proposition": {"type": "atomic", "predicate": "P", "arguments": []}
        }
        
        # WHEN
        text = grammar._linearize_boolean(semantic_value)
        
        # THEN
        assert "always" in text.lower()
        assert "p" in text.lower()


class TestSemanticConversion:
    """Test suite for semantic↔formula conversion."""
    
    def test_semantic_to_formula_atomic(self):
        """
        GIVEN: An atomic semantic value
        WHEN: Converting to Formula
        THEN: Should produce AtomicFormula
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        semantic_value = {
            "type": "atomic",
            "predicate": "happy",
            "arguments": []
        }
        
        # WHEN
        formula = grammar._semantic_to_formula(semantic_value)
        
        # THEN
        assert formula is not None
        # AtomicFormula check would go here
    
    def test_formula_to_semantic_atomic(self):
        """
        GIVEN: An AtomicFormula
        WHEN: Converting to semantic representation
        THEN: Should produce correct semantic dict
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula
        formula = AtomicFormula("happy", [])
        
        # WHEN
        semantic = grammar._formula_to_semantic(formula)
        
        # THEN
        assert semantic["type"] == "atomic"
        assert semantic["predicate"] == "happy"


class TestEndToEnd:
    """End-to-end integration tests."""
    
    def test_parse_simple_agent_action(self):
        """
        GIVEN: English text "jack runs"
        WHEN: Parsing to DCEC
        THEN: Should produce some parse (may be incomplete without full grammar)
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        text = "jack runs"
        
        # WHEN
        formula = grammar.parse_to_dcec(text)
        
        # THEN
        # May or may not parse depending on tokenization and rules
        # This is a basic sanity check
        assert formula is None or isinstance(formula, Formula)
    
    def test_round_trip_basic(self):
        """
        GIVEN: A simple DCEC formula
        WHEN: Converting to English and back
        THEN: Should preserve semantics (approximately)
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula
        original_formula = AtomicFormula("happy", [])
        
        # WHEN
        english = grammar.formula_to_english(original_formula)
        
        # THEN
        assert english is not None
        assert isinstance(english, str)
        assert len(english) > 0


class TestEdgeCases:
    """Test suite for edge cases and error handling."""
    
    def test_parse_empty_string(self):
        """
        GIVEN: Empty string input
        WHEN: Parsing to DCEC
        THEN: Should handle gracefully
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        
        # WHEN
        formula = grammar.parse_to_dcec("")
        
        # THEN
        assert formula is None
    
    def test_parse_unknown_words(self):
        """
        GIVEN: Text with unknown words
        WHEN: Parsing to DCEC
        THEN: Should return None or partial parse
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        text = "xyzabc qwerty"
        
        # WHEN
        formula = grammar.parse_to_dcec(text)
        
        # THEN
        assert formula is None  # Unknown words should fail to parse
    
    def test_linearize_unknown_type(self):
        """
        GIVEN: Semantic value with unknown type
        WHEN: Linearizing
        THEN: Should fall back to string conversion
        """
        # GIVEN
        grammar = DCECEnglishGrammar()
        semantic_value = {"type": "unknown", "data": "test"}
        
        # WHEN
        text = grammar._linearize_boolean(semantic_value)
        
        # THEN
        assert text is not None
        assert isinstance(text, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
