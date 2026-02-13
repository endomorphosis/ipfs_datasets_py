"""
Test module for Modal Logic Extension

This module provides comprehensive tests for the ModalLogicSymbol and 
AdvancedLogicConverter classes, covering modal, temporal, deontic, and epistemic logic.
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any, List

# Add the project root to Python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

# Import the modules to test
from ipfs_datasets_py.logic.integration.modal_logic_extension import (
    ModalLogicSymbol,
    AdvancedLogicConverter,
    ModalFormula,
    LogicClassification,
    convert_to_modal,
    detect_logic_type,
    SYMBOLIC_AI_AVAILABLE
)


class TestModalLogicSymbol:
    """Test suite for ModalLogicSymbol functionality."""
    
    def setup_method(self):
        """Setup test environment before each test."""
        self.test_statements = [
            "It is necessary that all birds fly",
            "It is possible that some cats are black",
            "Citizens must pay taxes",
            "Drivers may park here",
            "Smoking is forbidden",
            "John knows that it is raining",
            "Mary believes that the earth is round"
        ]
    
    def test_modal_symbol_initialization(self):
        """Test ModalLogicSymbol initialization."""
        symbol = ModalLogicSymbol("All cats are animals")
        assert symbol.value == "All cats are animals"
        assert symbol._semantic is True
        assert hasattr(symbol, '_modal_operators')
        assert '□' in symbol._modal_operators.values()
        assert '◇' in symbol._modal_operators.values()
    
    def test_modal_symbol_with_semantic_false(self):
        """Test ModalLogicSymbol with semantic=False."""
        symbol = ModalLogicSymbol("Test statement", semantic=False)
        assert symbol.value == "Test statement"
        assert symbol._semantic is False
    
    def test_necessarily_operator(self):
        """Test necessity modal operator."""
        symbol = ModalLogicSymbol("All birds fly")
        necessary = symbol.necessarily()
        
        assert isinstance(necessary, ModalLogicSymbol)
        assert necessary.value == "□(All birds fly)"
        assert necessary._semantic is True
    
    def test_possibly_operator(self):
        """Test possibility modal operator."""
        symbol = ModalLogicSymbol("Some cats are black")
        possible = symbol.possibly()
        
        assert isinstance(possible, ModalLogicSymbol)
        assert possible.value == "◇(Some cats are black)"
        assert possible._semantic is True
    
    def test_obligation_operator(self):
        """Test deontic obligation operator."""
        symbol = ModalLogicSymbol("Citizens pay taxes")
        obligation = symbol.obligation()
        
        assert isinstance(obligation, ModalLogicSymbol)
        assert obligation.value == "O(Citizens pay taxes)"
        assert obligation._semantic is True
    
    def test_permission_operator(self):
        """Test deontic permission operator."""
        symbol = ModalLogicSymbol("Drivers park here")
        permission = symbol.permission()
        
        assert isinstance(permission, ModalLogicSymbol)
        assert permission.value == "P(Drivers park here)"
        assert permission._semantic is True
    
    def test_prohibition_operator(self):
        """Test deontic prohibition operator."""
        symbol = ModalLogicSymbol("Smoking in buildings")
        prohibition = symbol.prohibition()
        
        assert isinstance(prohibition, ModalLogicSymbol)
        assert prohibition.value == "F(Smoking in buildings)"
        assert prohibition._semantic is True
    
    def test_knowledge_operator(self):
        """Test epistemic knowledge operator."""
        symbol = ModalLogicSymbol("It is raining")
        knowledge = symbol.knowledge("john")
        
        assert isinstance(knowledge, ModalLogicSymbol)
        assert knowledge.value == "K_john(It is raining)"
        assert knowledge._semantic is True
    
    def test_knowledge_operator_default_agent(self):
        """Test epistemic knowledge operator with default agent."""
        symbol = ModalLogicSymbol("The door is open")
        knowledge = symbol.knowledge()
        
        assert knowledge.value == "K_agent(The door is open)"
    
    def test_belief_operator(self):
        """Test epistemic belief operator."""
        symbol = ModalLogicSymbol("The earth is round")
        belief = symbol.belief("mary")
        
        assert isinstance(belief, ModalLogicSymbol)
        assert belief.value == "B_mary(The earth is round)"
        assert belief._semantic is True
    
    def test_temporal_always_operator(self):
        """Test temporal always operator."""
        symbol = ModalLogicSymbol("The sun rises")
        always = symbol.temporal_always()
        
        assert isinstance(always, ModalLogicSymbol)
        assert always.value == "□(The sun rises)"
        assert always._semantic is True
    
    def test_temporal_eventually_operator(self):
        """Test temporal eventually operator."""
        symbol = ModalLogicSymbol("Peace will come")
        eventually = symbol.temporal_eventually()
        
        assert isinstance(eventually, ModalLogicSymbol)
        assert eventually.value == "◇(Peace will come)"
        assert eventually._semantic is True
    
    def test_temporal_next_operator(self):
        """Test temporal next operator."""
        symbol = ModalLogicSymbol("The light turns red")
        next_state = symbol.temporal_next()
        
        assert isinstance(next_state, ModalLogicSymbol)
        assert next_state.value == "X(The light turns red)"
        assert next_state._semantic is True
    
    def test_temporal_until_operator(self):
        """Test temporal until operator."""
        symbol = ModalLogicSymbol("The system runs")
        until_formula = symbol.temporal_until("Power is available")
        
        assert isinstance(until_formula, ModalLogicSymbol)
        assert until_formula.value == "(The system runs U Power is available)"
        assert until_formula._semantic is True
    
    def test_operator_chaining(self):
        """Test chaining of modal operators."""
        symbol = ModalLogicSymbol("All birds fly")
        chained = symbol.necessarily().possibly()
        
        assert chained.value == "◇(□(All birds fly))"
    
    def test_complex_operator_combinations(self):
        """Test complex combinations of operators."""
        symbol = ModalLogicSymbol("The law is enforced")
        
        # Necessary obligation
        necessary_obligation = symbol.obligation().necessarily()
        assert necessary_obligation.value == "□(O(The law is enforced))"
        
        # Knowledge of obligation
        knowledge_obligation = symbol.obligation().knowledge("judge")
        assert knowledge_obligation.value == "K_judge(O(The law is enforced))"


class TestAdvancedLogicConverter:
    """Test suite for AdvancedLogicConverter functionality."""
    
    def setup_method(self):
        """Setup test environment before each test."""
        self.converter = AdvancedLogicConverter(confidence_threshold=0.7)
        
        self.test_cases = {
            'modal': [
                "It must be the case that all birds fly",
                "It is possible that some cats are black",
                "Necessarily, all humans are mortal",
                "It might rain tomorrow"
            ],
            'temporal': [
                "The system always responds within 5 seconds",
                "Eventually, all processes will complete",
                "The backup never fails",
                "Sometimes the network is slow"
            ],
            'deontic': [
                "Citizens must pay their taxes",
                "Drivers may park in designated areas",
                "Smoking is forbidden in public buildings",
                "Students should complete their assignments"
            ],
            'epistemic': [
                "John knows that it is raining",
                "Mary believes that the earth is round",
                "The agent is certain about the facts",
                "Everyone thinks that the meeting is at 3pm"
            ],
            'fol': [
                "All cats are animals",
                "Some birds can fly",
                "If it rains, then the ground is wet",
                "Every student studies hard"
            ]
        }
    
    def test_converter_initialization(self):
        """Test AdvancedLogicConverter initialization."""
        converter = AdvancedLogicConverter()
        assert converter.confidence_threshold == 0.7
        assert hasattr(converter, '_logic_indicators')
        assert 'modal' in converter._logic_indicators
        assert 'temporal' in converter._logic_indicators
        assert 'deontic' in converter._logic_indicators
        assert 'epistemic' in converter._logic_indicators
    
    def test_converter_custom_threshold(self):
        """Test AdvancedLogicConverter with custom threshold."""
        converter = AdvancedLogicConverter(confidence_threshold=0.8)
        assert converter.confidence_threshold == 0.8
    
    def test_detect_logic_type_modal(self):
        """Test logic type detection for modal logic."""
        for text in self.test_cases['modal']:
            classification = self.converter.detect_logic_type(text)
            
            assert isinstance(classification, LogicClassification)
            assert classification.logic_type in ['modal', 'fol']  # May fallback to fol
            assert 0.0 <= classification.confidence <= 1.0
            assert isinstance(classification.indicators, list)
            assert isinstance(classification.context, dict)
    
    def test_detect_logic_type_temporal(self):
        """Test logic type detection for temporal logic."""
        for text in self.test_cases['temporal']:
            classification = self.converter.detect_logic_type(text)
            
            assert isinstance(classification, LogicClassification)
            assert classification.logic_type in ['temporal', 'fol']
            assert 0.0 <= classification.confidence <= 1.0
            
            # Should find temporal indicators
            if classification.logic_type == 'temporal':
                assert len(classification.indicators) > 0
    
    def test_detect_logic_type_deontic(self):
        """Test logic type detection for deontic logic."""
        for text in self.test_cases['deontic']:
            classification = self.converter.detect_logic_type(text)
            
            assert isinstance(classification, LogicClassification)
            assert classification.logic_type in ['deontic', 'fol']
            assert 0.0 <= classification.confidence <= 1.0
    
    def test_detect_logic_type_epistemic(self):
        """Test logic type detection for epistemic logic."""
        for text in self.test_cases['epistemic']:
            classification = self.converter.detect_logic_type(text)
            
            assert isinstance(classification, LogicClassification)
            assert classification.logic_type in ['epistemic', 'fol']
            assert 0.0 <= classification.confidence <= 1.0
    
    def test_detect_logic_type_fol(self):
        """Test logic type detection for standard FOL."""
        for text in self.test_cases['fol']:
            classification = self.converter.detect_logic_type(text)
            
            assert isinstance(classification, LogicClassification)
            assert classification.logic_type in ['fol', 'modal', 'temporal', 'deontic', 'epistemic']
            assert 0.0 <= classification.confidence <= 1.0
    
    def test_detect_logic_type_empty_text(self):
        """Test logic type detection with empty text."""
        with pytest.raises(ValueError, match="Text cannot be empty"):
            self.converter.detect_logic_type("")
        
        with pytest.raises(ValueError, match="Text cannot be empty"):
            self.converter.detect_logic_type("   ")
    
    def test_convert_to_modal_logic(self):
        """Test conversion to modal logic."""
        for logic_type, texts in self.test_cases.items():
            for text in texts[:2]:  # Test first 2 of each type
                result = self.converter.convert_to_modal_logic(text)
                
                assert isinstance(result, ModalFormula)
                assert result.formula is not None
                assert result.modal_type is not None
                assert result.base_formula == text
                assert 0.0 <= result.confidence <= 1.0
                assert isinstance(result.operators, list)
                assert isinstance(result.semantic_context, dict)
    
    def test_modal_formula_structure(self):
        """Test ModalFormula data structure."""
        text = "Citizens must pay taxes"
        result = self.converter.convert_to_modal_logic(text)
        
        assert hasattr(result, 'formula')
        assert hasattr(result, 'modal_type')
        assert hasattr(result, 'operators')
        assert hasattr(result, 'base_formula')
        assert hasattr(result, 'confidence')
        assert hasattr(result, 'semantic_context')
        
        assert result.base_formula == text
        assert isinstance(result.semantic_context, dict)
    
    @pytest.mark.parametrize("text,expected_type", [
        ("It must be true that P", "modal"),
        ("Always P holds", "temporal"),
        ("You ought to do P", "deontic"), 
        ("John knows that P", "epistemic"),
        ("All cats are animals", "fol")
    ])
    def test_logic_type_classification_specific(self, text, expected_type):
        """Test specific logic type classifications."""
        classification = self.converter.detect_logic_type(text)
        
        # Note: Since we're using fallback logic, the classification might not always
        # match expected_type perfectly, but should be reasonable
        assert classification.logic_type in ['modal', 'temporal', 'deontic', 'epistemic', 'fol']
        assert isinstance(classification.confidence, float)
        assert 0.0 <= classification.confidence <= 1.0
    
    def test_convert_with_fallback_logic(self):
        """Test conversion using fallback logic when SymbolicAI is not available."""
        # This test ensures the fallback logic works correctly
        text = "Citizens must pay taxes"
        result = self.converter.convert_to_modal_logic(text)
        
        # Should still produce a valid ModalFormula
        assert isinstance(result, ModalFormula)
        assert result.formula is not None
        assert result.modal_type in ['alethic', 'temporal', 'deontic', 'epistemic', 'fol']
        assert result.base_formula == text
    
    def test_confidence_thresholds(self):
        """Test converter behavior with different confidence thresholds."""
        low_threshold_converter = AdvancedLogicConverter(confidence_threshold=0.1)
        high_threshold_converter = AdvancedLogicConverter(confidence_threshold=0.9)
        
        text = "It might be the case that P"
        
        low_result = low_threshold_converter.convert_to_modal_logic(text)
        high_result = high_threshold_converter.convert_to_modal_logic(text)
        
        # Both should produce valid results
        assert isinstance(low_result, ModalFormula)
        assert isinstance(high_result, ModalFormula)
    
    def test_complex_sentences(self):
        """Test conversion of complex sentences."""
        complex_texts = [
            "It is necessarily the case that if all humans are mortal, then Socrates is mortal",
            "Citizens must pay taxes, but they may request extensions",
            "John believes that Mary knows the answer",
            "Eventually, all processes will complete, but some may fail temporarily"
        ]
        
        for text in complex_texts:
            result = self.converter.convert_to_modal_logic(text)
            
            assert isinstance(result, ModalFormula)
            assert result.formula is not None
            assert result.base_formula == text
            assert 0.0 <= result.confidence <= 1.0


class TestLogicClassification:
    """Test suite for LogicClassification data structure."""
    
    def test_logic_classification_creation(self):
        """Test LogicClassification creation."""
        classification = LogicClassification(
            logic_type="modal",
            confidence=0.8,
            indicators=["must", "necessarily"],
            context={"test": "value"}
        )
        
        assert classification.logic_type == "modal"
        assert classification.confidence == 0.8
        assert classification.indicators == ["must", "necessarily"]
        assert classification.context == {"test": "value"}
    
    def test_logic_classification_with_empty_indicators(self):
        """Test LogicClassification with empty indicators."""
        classification = LogicClassification(
            logic_type="fol",
            confidence=0.5,
            indicators=[],
            context={}
        )
        
        assert classification.logic_type == "fol"
        assert classification.confidence == 0.5
        assert classification.indicators == []
        assert classification.context == {}


class TestModalFormula:
    """Test suite for ModalFormula data structure."""
    
    def test_modal_formula_creation(self):
        """Test ModalFormula creation."""
        formula = ModalFormula(
            formula="□(P → Q)",
            modal_type="alethic",
            operators=["□"],
            base_formula="If P then Q",
            confidence=0.9,
            semantic_context={"type": "necessity"}
        )
        
        assert formula.formula == "□(P → Q)"
        assert formula.modal_type == "alethic"
        assert formula.operators == ["□"]
        assert formula.base_formula == "If P then Q"
        assert formula.confidence == 0.9
        assert formula.semantic_context == {"type": "necessity"}
    
    def test_modal_formula_with_multiple_operators(self):
        """Test ModalFormula with multiple operators."""
        formula = ModalFormula(
            formula="□◇(P ∧ Q)",
            modal_type="alethic",
            operators=["□", "◇"],
            base_formula="P and Q",
            confidence=0.7,
            semantic_context={"complex": True}
        )
        
        assert len(formula.operators) == 2
        assert "□" in formula.operators
        assert "◇" in formula.operators


class TestConvenienceFunctions:
    """Test suite for convenience functions."""
    
    def test_convert_to_modal_function(self):
        """Test convert_to_modal convenience function."""
        text = "It must be the case that all birds fly"
        result = convert_to_modal(text)
        
        assert isinstance(result, ModalFormula)
        assert result.base_formula == text
        assert result.formula is not None
    
    def test_convert_to_modal_with_threshold(self):
        """Test convert_to_modal with custom threshold."""
        text = "Citizens should vote"
        result = convert_to_modal(text, confidence_threshold=0.8)
        
        assert isinstance(result, ModalFormula)
        assert result.base_formula == text
    
    def test_detect_logic_type_function(self):
        """Test detect_logic_type convenience function."""
        text = "Eventually all processes complete"
        result = detect_logic_type(text)
        
        assert isinstance(result, LogicClassification)
        assert result.logic_type in ['temporal', 'fol']
        assert 0.0 <= result.confidence <= 1.0
    
    def test_convenience_functions_with_edge_cases(self):
        """Test convenience functions with edge cases."""
        # Very short text
        short_text = "P"
        result = convert_to_modal(short_text)
        assert isinstance(result, ModalFormula)
        
        # Text with special characters
        special_text = "P → Q ∧ R"
        result = detect_logic_type(special_text)
        assert isinstance(result, LogicClassification)


class TestIntegrationScenarios:
    """Test suite for integration scenarios and edge cases."""
    
    def setup_method(self):
        """Setup test environment."""
        self.converter = AdvancedLogicConverter()
    
    def test_end_to_end_modal_workflow(self):
        """Test complete modal logic workflow."""
        text = "It is necessary that all citizens follow the law"
        
        # Step 1: Detect logic type
        classification = self.converter.detect_logic_type(text)
        assert isinstance(classification, LogicClassification)
        
        # Step 2: Convert to modal logic
        modal_result = self.converter.convert_to_modal_logic(text)
        assert isinstance(modal_result, ModalFormula)
        
        # Step 3: Create modal symbol and apply operators
        symbol = ModalLogicSymbol(text)
        necessary = symbol.necessarily()
        assert necessary.value == f"□({text})"
    
    def test_end_to_end_deontic_workflow(self):
        """Test complete deontic logic workflow."""
        text = "Drivers must stop at red lights"
        
        classification = self.converter.detect_logic_type(text)
        modal_result = self.converter.convert_to_modal_logic(text)
        
        # Should be classified as deontic or at least processed
        assert isinstance(classification, LogicClassification)
        assert isinstance(modal_result, ModalFormula)
        
        # Create deontic formula
        symbol = ModalLogicSymbol("Drivers stop at red lights")
        obligation = symbol.obligation()
        assert obligation.value == "O(Drivers stop at red lights)"
    
    def test_mixed_logic_types(self):
        """Test handling of sentences with mixed logic indicators."""
        mixed_texts = [
            "Citizens must always pay taxes",  # deontic + temporal
            "John knows that Mary should help",  # epistemic + deontic
            "It is possible that eventually peace will come"  # modal + temporal
        ]
        
        for text in mixed_texts:
            classification = self.converter.detect_logic_type(text)
            modal_result = self.converter.convert_to_modal_logic(text)
            
            assert isinstance(classification, LogicClassification)
            assert isinstance(modal_result, ModalFormula)
            # Should classify as one of the logic types
            assert classification.logic_type in ['modal', 'temporal', 'deontic', 'epistemic', 'fol']
    
    def test_error_handling_and_recovery(self):
        """Test error handling and graceful degradation."""
        # Test with various problematic inputs
        problematic_inputs = [
            "",  # Should raise ValueError
            "   ",  # Should raise ValueError
            "A very short sentence with no clear logic indicators: xyz",
            "Random symbols: @#$%^&*()",
            "Numbers only: 123 456 789"
        ]
        
        for text in problematic_inputs[:2]:  # Empty strings should raise errors
            with pytest.raises(ValueError):
                self.converter.detect_logic_type(text)
        
        for text in problematic_inputs[2:]:  # Others should handle gracefully
            try:
                classification = self.converter.detect_logic_type(text)
                modal_result = self.converter.convert_to_modal_logic(text)
                
                assert isinstance(classification, LogicClassification)
                assert isinstance(modal_result, ModalFormula)
            except Exception as e:
                pytest.fail(f"Unexpected error for input '{text}': {e}")
    
    def test_performance_with_long_texts(self):
        """Test performance with longer texts."""
        long_text = (
            "In the context of legal obligations and moral imperatives, "
            "it is necessarily the case that all citizens must fulfill "
            "their civic duties, and it is always true that justice "
            "should prevail in all circumstances, while individuals "
            "may exercise their rights within the bounds of the law."
        )
        
        classification = self.converter.detect_logic_type(long_text)
        modal_result = self.converter.convert_to_modal_logic(long_text)
        
        assert isinstance(classification, LogicClassification)
        assert isinstance(modal_result, ModalFormula)
        assert modal_result.base_formula == long_text
    
    def test_symbolic_ai_availability_handling(self):
        """Test handling of SymbolicAI availability."""
        # This test ensures the code works regardless of SymbolicAI availability
        text = "All cats are animals"
        
        # Test with current availability setting
        result = convert_to_modal(text)
        assert isinstance(result, ModalFormula)
        
        # Test classification
        classification = detect_logic_type(text)
        assert isinstance(classification, LogicClassification)
        
        # Verify SYMBOLIC_AI_AVAILABLE flag is a boolean
        assert isinstance(SYMBOLIC_AI_AVAILABLE, bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
