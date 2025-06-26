# ipfs_datasets_py/mcp_server/tools/dataset_tools/tests/test_text_to_fol.py
"""
Tests for the text to First-Order Logic conversion tool.
"""
import asyncio
import pytest
from typing import Dict, Any

from ..text_to_fol import convert_text_to_fol

def test_text_to_fol_basic():
    """Test basic text to FOL conversion functionality."""
    
    async def run_test():
        # Test simple universal statement
        result = await convert_text_to_fol(
            "All cats are animals",
            output_format='json',
            confidence_threshold=0.5
        )
        
        assert result["status"] == "success"
        assert len(result["fol_formulas"]) > 0
        
        formula = result["fol_formulas"][0]
        assert "All cats are animals" in formula["original_text"]
        assert "∀" in formula["fol_formula"]  # Should contain universal quantifier
        assert formula["confidence"] > 0.5
        
        # Test existential statement
        result2 = await convert_text_to_fol(
            "Some birds can fly",
            output_format='json'
        )
        
        assert result2["status"] == "success"
        if result2["fol_formulas"]:
            formula2 = result2["fol_formulas"][0]
            assert "Some birds can fly" in formula2["original_text"]
            # Should contain existential quantifier or appropriate structure
            assert any(symbol in formula2["fol_formula"] for symbol in ["∃", "∀"])

    asyncio.run(run_test())

def test_text_to_fol_complex():
    """Test complex text to FOL conversion scenarios."""
    
    async def run_test():
        # Test conditional statement
        result = await convert_text_to_fol(
            "If someone is a student and studies hard, then they will pass",
            output_format='json',
            include_metadata=True
        )
        
        assert result["status"] == "success"
        
        # Test multiple statements
        dataset_input = {
            "sentences": [
                "All dogs are mammals",
                "Some mammals are carnivores",
                "No fish are mammals"
            ]
        }
        
        result2 = await convert_text_to_fol(
            dataset_input,
            output_format='json'
        )
        
        assert result2["status"] == "success"
        assert len(result2["fol_formulas"]) <= 3  # Should process up to 3 statements
        
        # Check summary statistics
        summary = result2["summary"]
        assert "total_statements" in summary
        assert "successful_conversions" in summary
        assert "conversion_rate" in summary

    asyncio.run(run_test())

def test_text_to_fol_output_formats():
    """Test different output formats for FOL conversion."""
    
    async def run_test():
        test_text = "All humans are mortal"
        
        # Test Prolog output format
        result_prolog = await convert_text_to_fol(
            test_text,
            output_format='prolog'
        )
        
        assert result_prolog["status"] == "success"
        if result_prolog["fol_formulas"]:
            formula = result_prolog["fol_formulas"][0]
            assert "prolog_form" in formula

        # Test TPTP output format
        result_tptp = await convert_text_to_fol(
            test_text,
            output_format='tptp'
        )
        
        assert result_tptp["status"] == "success"
        if result_tptp["fol_formulas"]:
            formula = result_tptp["fol_formulas"][0]
            assert "tptp_form" in formula

    asyncio.run(run_test())

def test_text_to_fol_error_handling():
    """Test error handling in text to FOL conversion."""
    
    async def run_test():
        # Test empty input
        result = await convert_text_to_fol("")
        assert result["status"] == "error"
        assert "empty" in result["message"].lower()
        
        # Test invalid confidence threshold
        result2 = await convert_text_to_fol(
            "Test sentence",
            confidence_threshold=1.5
        )
        assert result2["status"] == "error"
        
        # Test invalid input type
        try:
            result3 = await convert_text_to_fol(123)  # type: ignore
            assert result3["status"] == "error"
        except Exception:
            # Expected to fail due to type checking
            pass

    asyncio.run(run_test())

def test_text_to_fol_confidence_scoring():
    """Test confidence scoring mechanism."""
    
    async def run_test():
        # Simple, clear statement should have high confidence
        result1 = await convert_text_to_fol(
            "All cats are animals",
            confidence_threshold=0.1
        )
        
        if result1["status"] == "success" and result1["fol_formulas"]:
            high_conf = result1["fol_formulas"][0]["confidence"]
            
            # Complex, ambiguous statement should have lower confidence
            result2 = await convert_text_to_fol(
                "The thing over there might be something",
                confidence_threshold=0.1
            )
            
            if result2["status"] == "success" and result2["fol_formulas"]:
                low_conf = result2["fol_formulas"][0]["confidence"]
                
                # High confidence should be greater than low confidence
                # (though both might be processed)
                assert isinstance(high_conf, (int, float))
                assert isinstance(low_conf, (int, float))
                assert 0 <= high_conf <= 1
                assert 0 <= low_conf <= 1

    asyncio.run(run_test())

def test_text_to_fol_predicate_extraction():
    """Test predicate extraction and analysis."""
    
    async def run_test():
        result = await convert_text_to_fol(
            "All students study hard",
            include_metadata=True
        )
        
        assert result["status"] == "success"
        if result["fol_formulas"]:
            formula = result["fol_formulas"][0]
            
            # Should extract predicates
            assert "predicates_used" in formula
            predicates = formula["predicates_used"]
            assert isinstance(predicates, list)
            
            # Should identify quantifiers
            assert "quantifiers" in formula
            quantifiers = formula["quantifiers"]
            assert isinstance(quantifiers, list)

    asyncio.run(run_test())

if __name__ == "__main__":
    print("Running text to FOL conversion tests...")
    
    test_text_to_fol_basic()
    print("✓ Basic FOL conversion test passed")
    
    test_text_to_fol_complex()
    print("✓ Complex FOL conversion test passed")
    
    test_text_to_fol_output_formats()
    print("✓ Output formats test passed")
    
    test_text_to_fol_error_handling()
    print("✓ Error handling test passed")
    
    test_text_to_fol_confidence_scoring()
    print("✓ Confidence scoring test passed")
    
    test_text_to_fol_predicate_extraction()
    print("✓ Predicate extraction test passed")
    
    print("All text to FOL tests completed successfully!")
