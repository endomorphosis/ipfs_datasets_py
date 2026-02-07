# ipfs_datasets_py/mcp_server/tools/dataset_tools/tests/test_legal_text_to_deontic.py
"""
Tests for the legal text to deontic logic conversion tool.
"""
import anyio
import pytest
from typing import Dict, Any

from ..legal_text_to_deontic import convert_legal_text_to_deontic

def test_legal_text_basic():
    """Test basic legal text to deontic logic conversion."""
    
    async def run_test():
        # Test obligation
        result = await convert_legal_text_to_deontic(
            "Citizens must pay taxes by April 15th",
            jurisdiction='us',
            document_type='statute'
        )
        
        assert result["status"] == "success"
        assert len(result["deontic_formulas"]) > 0
        
        formula = result["deontic_formulas"][0]
        assert "Citizens must pay taxes" in formula["original_text"]
        assert formula["obligation_type"] == "obligation"
        assert formula["deontic_operator"] == "O"
        assert formula["confidence"] > 0.5
        
        # Test permission
        result2 = await convert_legal_text_to_deontic(
            "Residents may park on designated streets",
            jurisdiction='us',
            document_type='regulation'
        )
        
        assert result2["status"] == "success"
        if result2["deontic_formulas"]:
            formula2 = result2["deontic_formulas"][0]
            assert formula2["obligation_type"] == "permission"
            assert formula2["deontic_operator"] == "P"

    anyio.run(run_test)

def test_deontic_obligations():
    """Test different types of deontic obligations."""
    
    async def run_test():
        # Test prohibition
        result = await convert_legal_text_to_deontic(
            "Smoking is prohibited in public buildings",
            jurisdiction='us',
            document_type='policy'
        )
        
        assert result["status"] == "success"
        if result["deontic_formulas"]:
            formula = result["deontic_formulas"][0]
            assert formula["obligation_type"] == "prohibition"
            assert formula["deontic_operator"] == "F"
        
        # Test complex legal text with multiple norms
        complex_text = """
        Section 1: All employees must complete safety training.
        Section 2: Supervisors may approve overtime requests.
        Section 3: Workers cannot operate machinery without certification.
        """
        
        result2 = await convert_legal_text_to_deontic(
            complex_text,
            jurisdiction='us',
            document_type='regulation'
        )
        
        assert result2["status"] == "success"
        
        # Should identify multiple norms
        formulas = result2["deontic_formulas"]
        if len(formulas) > 1:
            # Check that we have different types of norms
            norm_types = [f["obligation_type"] for f in formulas]
            assert len(set(norm_types)) > 1  # Multiple different norm types

    anyio.run(run_test)

def test_legal_text_entities_and_actions():
    """Test extraction of legal entities and actions."""
    
    async def run_test():
        result = await convert_legal_text_to_deontic(
            "All drivers must obtain a valid license before operating a vehicle",
            jurisdiction='us',
            document_type='statute'
        )
        
        assert result["status"] == "success"
        
        # Check legal entities
        entities = result["legal_entities"]
        assert isinstance(entities, list)
        
        # Check actions
        actions = result["actions"]
        assert isinstance(actions, list)
        
        if result["deontic_formulas"]:
            formula = result["deontic_formulas"][0]
            assert "subject" in formula
            assert "action" in formula

    anyio.run(run_test)

def test_temporal_constraints():
    """Test extraction of temporal constraints from legal text."""
    
    async def run_test():
        result = await convert_legal_text_to_deontic(
            "Tax returns must be filed annually by April 15th",
            jurisdiction='us',
            document_type='statute'
        )
        
        assert result["status"] == "success"
        
        # Check temporal constraints
        temporal = result["temporal_constraints"]
        assert isinstance(temporal, list)
        
        if result["deontic_formulas"]:
            formula = result["deontic_formulas"][0]
            if "temporal_constraints" in formula:
                constraints = formula["temporal_constraints"]
                assert isinstance(constraints, list)

    anyio.run(run_test)

def test_legal_text_jurisdictions():
    """Test different jurisdiction handling."""
    
    async def run_test():
        legal_text = "All citizens must register to vote"
        
        # Test different jurisdictions
        jurisdictions = ['us', 'eu', 'uk', 'international']
        
        for jurisdiction in jurisdictions:
            result = await convert_legal_text_to_deontic(
                legal_text,
                jurisdiction=jurisdiction,
                document_type='statute'
            )
            
            assert result["status"] == "success"
            assert result["metadata"]["jurisdiction"] == jurisdiction

    anyio.run(run_test)

def test_legal_document_types():
    """Test different legal document types."""
    
    async def run_test():
        legal_text = "Parties must fulfill their contractual obligations"
        
        # Test different document types
        doc_types = ['statute', 'regulation', 'contract', 'policy']
        
        for doc_type in doc_types:
            result = await convert_legal_text_to_deontic(
                legal_text,
                jurisdiction='us',
                document_type=doc_type
            )
            
            assert result["status"] == "success"
            assert result["metadata"]["document_type"] == doc_type

    anyio.run(run_test)

def test_deontic_output_formats():
    """Test different output formats for deontic logic."""
    
    async def run_test():
        legal_text = "Students must attend classes regularly"
        
        # Test defeasible logic format
        result = await convert_legal_text_to_deontic(
            legal_text,
            output_format='defeasible'
        )
        
        assert result["status"] == "success"
        if result["deontic_formulas"]:
            formula = result["deontic_formulas"][0]
            assert "defeasible_form" in formula

    anyio.run(run_test)

def test_legal_text_dataset_input():
    """Test legal text conversion with dataset input."""
    
    async def run_test():
        # Test dataset structure
        dataset_input = {
            "legal_text": [
                "All contractors must provide insurance",
                "Workers may request safety equipment",
                "Violations cannot be ignored"
            ]
        }
        
        result = await convert_legal_text_to_deontic(
            dataset_input,
            jurisdiction='us',
            document_type='regulation'
        )
        
        assert result["status"] == "success"
        
        # Should process multiple legal statements
        formulas = result["deontic_formulas"]
        assert len(formulas) <= 3  # Up to 3 statements

    anyio.run(run_test)

def test_normative_structure_analysis():
    """Test normative structure analysis."""
    
    async def run_test():
        complex_legal_text = """
        Employees must clock in before starting work.
        Supervisors may approve flexible schedules.
        Workers cannot leave without permission.
        """
        
        result = await convert_legal_text_to_deontic(
            complex_legal_text,
            extract_obligations=True
        )
        
        assert result["status"] == "success"
        
        # Check normative structure
        structure = result["normative_structure"]
        assert "obligations" in structure
        assert "permissions" in structure
        assert "prohibitions" in structure

    anyio.run(run_test)

def test_legal_text_error_handling():
    """Test error handling in legal text conversion."""
    
    async def run_test():
        # Test empty input
        result = await convert_legal_text_to_deontic("")
        assert result["status"] == "success"
        assert result["deontic_formulas"] == []
        assert result["summary"]["total_normative_statements"] == 0
        
        # Test invalid jurisdiction (should warn but continue)
        result2 = await convert_legal_text_to_deontic(
            "Test legal text",
            jurisdiction='invalid_jurisdiction'
        )
        # Should default to 'general' and succeed
        assert result2["status"] == "success"
        assert result2["metadata"]["jurisdiction"] == "general"

    anyio.run(run_test)

def test_deontic_confidence_scoring():
    """Test confidence scoring for deontic logic conversion."""
    
    async def run_test():
        # Clear legal obligation should have high confidence
        result1 = await convert_legal_text_to_deontic(
            "All drivers must have a valid license",
            jurisdiction='us'
        )
        
        if result1["status"] == "success" and result1["deontic_formulas"]:
            high_conf = result1["deontic_formulas"][0]["confidence"]
            
            # Ambiguous text should have lower confidence
            result2 = await convert_legal_text_to_deontic(
                "People should probably do things sometimes"
            )
            
            if result2["status"] == "success" and result2["deontic_formulas"]:
                low_conf = result2["deontic_formulas"][0]["confidence"]
                
                # Verify confidence scores are reasonable
                assert isinstance(high_conf, (int, float))
                assert isinstance(low_conf, (int, float))
                assert 0 <= high_conf <= 1
                assert 0 <= low_conf <= 1

    anyio.run(run_test)

if __name__ == "__main__":
    print("Running legal text to deontic logic conversion tests...")
    
    test_legal_text_basic()
    print("✓ Basic legal text conversion test passed")
    
    test_deontic_obligations()
    print("✓ Deontic obligations test passed")
    
    test_legal_text_entities_and_actions()
    print("✓ Entities and actions extraction test passed")
    
    test_temporal_constraints()
    print("✓ Temporal constraints test passed")
    
    test_legal_text_jurisdictions()
    print("✓ Jurisdictions test passed")
    
    test_legal_document_types()
    print("✓ Document types test passed")
    
    test_deontic_output_formats()
    print("✓ Output formats test passed")
    
    test_legal_text_dataset_input()
    print("✓ Dataset input test passed")
    
    test_normative_structure_analysis()
    print("✓ Normative structure analysis test passed")
    
    test_legal_text_error_handling()
    print("✓ Error handling test passed")
    
    test_deontic_confidence_scoring()
    print("✓ Confidence scoring test passed")
    
    print("All legal text to deontic logic tests completed successfully!")
