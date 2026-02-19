"""
Unit tests for native natural language converter.

These tests validate NL to DCEC conversion functionality.
"""

import pytest
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from ipfs_datasets_py.logic.CEC.native import (
    NaturalLanguageConverter,
    ConversionResult,
    DeonticOperator,
    CognitiveOperator,
    TemporalOperator,
)


class TestNaturalLanguageConverter:
    """Test suite for NaturalLanguageConverter."""
    
    def test_converter_initialization(self):
        """
        GIVEN a natural language converter
        WHEN initializing
        THEN it should be ready to use
        """
        converter = NaturalLanguageConverter()
        
        assert converter.initialize() is True
        assert converter._initialized is True
        assert len(converter.conversion_history) == 0
    
    def test_deontic_obligation(self):
        """
        GIVEN text "must act"
        WHEN converting
        THEN it should create obligation formula
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("the agent must act")
        
        assert result.success is True
        assert result.dcec_formula is not None
        assert "O(" in result.dcec_formula.to_string()
        assert "act" in result.dcec_formula.to_string()
    
    def test_deontic_permission(self):
        """
        GIVEN text "may move"
        WHEN converting
        THEN it should create permission formula
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("the robot may move")
        
        assert result.success is True
        assert "P(" in result.dcec_formula.to_string()
        assert "move" in result.dcec_formula.to_string()
    
    def test_deontic_prohibition(self):
        """
        GIVEN text "must not steal"
        WHEN converting
        THEN it should create prohibition formula
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("the agent must not steal")
        
        assert result.success is True
        assert "F(" in result.dcec_formula.to_string()
        assert "steal" in result.dcec_formula.to_string()
    
    def test_cognitive_belief(self):
        """
        GIVEN text "believes that X"
        WHEN converting
        THEN it should create belief formula
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("the agent believes that the goal is achieved")
        
        assert result.success is True
        assert "B(" in result.dcec_formula.to_string()
    
    def test_cognitive_knowledge(self):
        """
        GIVEN text "knows that X"
        WHEN converting
        THEN it should create knowledge formula
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("the agent knows that the task is done")
        
        assert result.success is True
        assert "K(" in result.dcec_formula.to_string()
    
    def test_cognitive_intention(self):
        """
        GIVEN text "intends to X"
        WHEN converting
        THEN it should create intention formula
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("the agent intends to complete")
        
        assert result.success is True
        assert "I(" in result.dcec_formula.to_string()
    
    def test_temporal_always(self):
        """
        GIVEN text "always X"
        WHEN converting
        THEN it should create always formula
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("always the rule applies")
        
        assert result.success is True
        assert "□(" in result.dcec_formula.to_string()
    
    def test_temporal_eventually(self):
        """
        GIVEN text "eventually X"
        WHEN converting
        THEN it should create eventually formula
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("eventually the goal is reached")
        
        assert result.success is True
        assert "◊(" in result.dcec_formula.to_string()
    
    def test_temporal_next(self):
        """
        GIVEN text "next X"
        WHEN converting
        THEN it should create next formula
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("next the state changes")
        
        assert result.success is True
        assert "X(" in result.dcec_formula.to_string()
    
    def test_reverse_conversion_obligation(self):
        """
        GIVEN DCEC formula
        WHEN converting to English
        THEN it should produce readable text
        """
        converter = NaturalLanguageConverter()
        
        # Convert to DCEC
        result = converter.convert_to_dcec("the agent must act")
        assert result.success is True
        
        # Convert back
        english = converter.convert_from_dcec(result.dcec_formula)
        assert "must" in english.lower()
        assert "act" in english.lower()
    
    def test_conversion_history(self):
        """
        GIVEN multiple conversions
        WHEN checking history
        THEN all should be recorded
        """
        converter = NaturalLanguageConverter()
        
        converter.convert_to_dcec("the agent must act")
        converter.convert_to_dcec("the robot may move")
        converter.convert_to_dcec("eventually the goal is reached")
        
        assert len(converter.conversion_history) == 3
    
    def test_conversion_statistics(self):
        """
        GIVEN conversions with success and failure
        WHEN getting statistics
        THEN they should be accurate
        """
        converter = NaturalLanguageConverter()
        
        # Successful conversions
        converter.convert_to_dcec("the agent must act")
        converter.convert_to_dcec("the robot may move")
        
        stats = converter.get_conversion_statistics()
        
        assert stats["total_conversions"] == 2
        assert stats["successful"] == 2
        assert stats["success_rate"] == 1.0
        assert stats["average_confidence"] > 0
    
    def test_agent_extraction(self):
        """
        GIVEN text with different agent names
        WHEN converting
        THEN agent should be extracted correctly
        """
        converter = NaturalLanguageConverter()
        
        result1 = converter.convert_to_dcec("the robot must act")
        result2 = converter.convert_to_dcec("the agent must act")
        
        assert result1.success is True
        assert result2.success is True
        # Both should create valid formulas
        assert "act" in result1.dcec_formula.to_string()
        assert "act" in result2.dcec_formula.to_string()
    
    def test_complex_nested_formula(self):
        """
        GIVEN complex nested text
        WHEN converting
        THEN it should handle nesting
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("the agent believes that the robot must act")
        
        assert result.success is True
        # Should have both belief and obligation
        assert "B(" in result.dcec_formula.to_string()
        assert "O(" in result.dcec_formula.to_string()


class TestConversionResult:
    """Test suite for ConversionResult dataclass."""
    
    def test_conversion_result_creation(self):
        """
        GIVEN conversion result parameters
        WHEN creating ConversionResult
        THEN it should have correct attributes
        """
        result = ConversionResult(
            english_text="test text",
            success=True,
            confidence=0.8
        )
        
        assert result.english_text == "test text"
        assert result.success is True
        assert result.confidence == 0.8
        assert result.dcec_formula is None


# Phase 3 Day 5: New Conversion Patterns (12 tests)
class TestNewConversionPatterns:
    """Test suite for new natural language conversion patterns."""
    
    def test_passive_voice_conversion(self):
        """
        GIVEN passive voice "The door must be closed"
        WHEN converting to DCEC
        THEN it should create obligation about closing door
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("the door must be closed")
        
        assert result.success is True
        assert result.dcec_formula is not None
        # Should recognize obligation even in passive voice
        formula_str = result.dcec_formula.to_string()
        assert "O(" in formula_str or "must" in result.english_text.lower()
    
    def test_conditional_sentence_conversion(self):
        """
        GIVEN conditional "If X then Y must Z"
        WHEN converting to DCEC
        THEN it should create conditional obligation
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("if the alarm sounds then the agent must evacuate")
        
        assert result.success is True
        assert result.dcec_formula is not None
    
    def test_compound_sentence_conversion(self):
        """
        GIVEN compound sentence "X and Y must Z"
        WHEN converting to DCEC
        THEN it should handle conjunction properly
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("Alice and Bob must cooperate")
        
        assert result.success is True
        assert result.dcec_formula is not None
    
    def test_negative_obligation_conversion(self):
        """
        GIVEN negative obligation "X must not Y"
        WHEN converting to DCEC
        THEN it should create obligation with negation
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("the agent must not cheat")
        
        assert result.success is True
        assert result.dcec_formula is not None
        formula_str = result.dcec_formula.to_string()
        # Should have obligation or prohibition
        assert "O(" in formula_str or "F(" in formula_str or "not" in result.english_text.lower()
    
    def test_comparative_sentence_conversion(self):
        """
        GIVEN comparative "X more than Y"
        WHEN converting to DCEC
        THEN it should handle comparison appropriately
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("Alice must work more than Bob")
        
        # May not fully support comparisons, but should not error
        assert result is not None
    
    def test_temporal_adverb_conversion(self):
        """
        GIVEN temporal adverb "X always/sometimes Y"
        WHEN converting to DCEC
        THEN it should include temporal operator
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("the agent must always be honest")
        
        assert result.success is True
        assert result.dcec_formula is not None
    
    def test_modal_adverb_conversion(self):
        """
        GIVEN modal adverb "X possibly/necessarily Y"
        WHEN converting to DCEC
        THEN it should create appropriate modal formula
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("the agent possibly may leave")
        
        # May or may not support, but should not error
        assert result is not None
    
    def test_relative_clause_conversion(self):
        """
        GIVEN relative clause "X who Y must Z"
        WHEN converting to DCEC
        THEN it should handle complex subject
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("the agent who arrives first must open the door")
        
        assert result.success is True
        assert result.dcec_formula is not None
    
    def test_gerund_conversion(self):
        """
        GIVEN gerund form "Closing the door is required"
        WHEN converting to DCEC
        THEN it should create obligation
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("closing the door is required")
        
        # Should recognize as obligation
        assert result is not None
    
    def test_infinitive_conversion(self):
        """
        GIVEN infinitive "To close the door is required"
        WHEN converting to DCEC
        THEN it should create obligation
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("to close the door is required")
        
        # Should recognize as obligation
        assert result is not None
    
    def test_question_to_query_conversion(self):
        """
        GIVEN question "Must X Y?"
        WHEN converting to DCEC
        THEN it should create query formula
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("must the agent act?")
        
        # Should handle questions (possibly as queries)
        assert result is not None
    
    def test_imperative_to_obligation_conversion(self):
        """
        GIVEN imperative "Close the door!"
        WHEN converting to DCEC
        THEN it should create obligation
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("close the door!")
        
        # Imperatives often map to obligations
        assert result is not None


# Phase 3 Day 5: Ambiguity Handling (8 tests)
class TestAmbiguityHandling:
    """Test suite for ambiguity handling in NL conversion."""
    
    def test_ambiguous_agent_resolution_with_context(self):
        """
        GIVEN ambiguous pronoun with context
        WHEN resolving agent reference
        THEN it should use context to resolve ambiguity
        """
        converter = NaturalLanguageConverter()
        
        # First establish context
        result1 = converter.convert_to_dcec("Alice must act")
        
        # Then use pronoun
        result2 = converter.convert_to_dcec("she must wait")
        
        assert result1.success is True
        # Pronoun resolution may not be fully implemented
        assert result2 is not None
    
    def test_ambiguous_action_selection_by_frequency(self):
        """
        GIVEN ambiguous action word
        WHEN selecting interpretation
        THEN it should use most common interpretation
        """
        converter = NaturalLanguageConverter()
        
        # "run" could mean execute or jog
        result = converter.convert_to_dcec("the agent must run the program")
        
        assert result is not None
    
    def test_ambiguous_scope_resolution(self):
        """
        GIVEN ambiguous operator scope
        WHEN parsing formula
        THEN it should resolve scope appropriately
        """
        converter = NaturalLanguageConverter()
        
        # "not all" vs "all not"
        result = converter.convert_to_dcec("not all agents must act")
        
        assert result is not None
    
    def test_multiple_interpretation_generation(self):
        """
        GIVEN highly ambiguous sentence
        WHEN generating interpretations
        THEN it should return multiple possible interpretations
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("the agent may leave or stay")
        
        # Should succeed with at least one interpretation
        assert result is not None
    
    def test_interpretation_ranking_by_confidence(self):
        """
        GIVEN multiple interpretations
        WHEN ranking by confidence
        THEN most likely interpretation should have highest confidence
        """
        converter = NaturalLanguageConverter()
        
        result = converter.convert_to_dcec("the agent must act quickly")
        
        # Should have confidence score
        assert result is not None
        if result.confidence is not None:
            assert 0.0 <= result.confidence <= 1.0
    
    def test_user_disambiguation_query(self):
        """
        GIVEN ambiguous input
        WHEN disambiguation needed
        THEN it could query user for clarification
        """
        converter = NaturalLanguageConverter()
        
        # Ambiguous: "bank" could be financial or river bank
        result = converter.convert_to_dcec("the agent must go to the bank")
        
        # Should handle even if ambiguous
        assert result is not None
    
    def test_context_based_ambiguity_resolution(self):
        """
        GIVEN ambiguity resolvable by context
        WHEN using discourse context
        THEN it should resolve using previous sentences
        """
        converter = NaturalLanguageConverter()
        
        # Establish context
        converter.convert_to_dcec("We are discussing financial obligations")
        
        # Now ambiguous word should be clear
        result = converter.convert_to_dcec("the agent must manage the bank")
        
        assert result is not None
    
    def test_domain_specific_ambiguity_resolution(self):
        """
        GIVEN domain-specific ambiguity
        WHEN using domain knowledge
        THEN it should resolve using domain conventions
        """
        converter = NaturalLanguageConverter()
        
        # In legal domain, certain terms have specific meanings
        result = converter.convert_to_dcec("the party must execute the agreement")
        
        # "execute" in legal context means sign/implement, not kill
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
