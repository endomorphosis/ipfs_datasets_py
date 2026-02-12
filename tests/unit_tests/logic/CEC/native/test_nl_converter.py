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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
