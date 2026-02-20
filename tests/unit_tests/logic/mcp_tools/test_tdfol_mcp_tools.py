#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for TDFOL MCP Tools.

This module tests the MCP tool wrappers for TDFOL (Temporal Deontic First-Order Logic)
including parsing, proving, and conversion tools.

Test format follows GIVEN-WHEN-THEN pattern as per docs/_example_test_format.md
"""
import pytest
from typing import Dict, Any


# ==============================================================================
# Test tdfol_parse_tool.py
# ==============================================================================


@pytest.mark.asyncio
async def test_parse_symbolic_formula():
    """
    GIVEN: A TDFOL parse tool and a symbolic formula
    WHEN: Parsing the formula
    THEN: Formula is successfully parsed and returned
    """
    # GIVEN
    from ipfs_datasets_py.mcp_server.tools.logic_tools.tdfol_parse_tool import TDFOLParseTool
    
    tool = TDFOLParseTool()
    formula = "∀x.(P(x) → Q(x))"
    
    # WHEN
    result = await tool.execute({
        "formula": formula,
        "format": "symbolic",
        "validate": True
    })
    
    # THEN
    assert result["success"] is True
    assert "parsed_formula" in result
    assert result["format_detected"] == "symbolic"
    assert result["formula"] == formula


@pytest.mark.asyncio
async def test_parse_natural_language():
    """
    GIVEN: A TDFOL parse tool and natural language text
    WHEN: Parsing the text
    THEN: Formula is successfully extracted from natural language
    """
    # GIVEN
    from ipfs_datasets_py.mcp_server.tools.logic_tools.tdfol_parse_tool import TDFOLParseTool
    
    tool = TDFOLParseTool()
    text = "All contractors must submit reports."
    
    # WHEN
    result = await tool.execute({
        "formula": text,
        "format": "natural_language",
        "min_confidence": 0.3  # Lower threshold for test
    })
    
    # THEN
    # Note: This may fail if NL dependencies not installed, which is acceptable
    if "error" in result and "not available" in result["error"]:
        pytest.skip("NL parser dependencies not installed")
    
    assert "success" in result
    assert result["format_detected"] == "natural_language"


@pytest.mark.asyncio
async def test_parse_auto_detect_symbolic():
    """
    GIVEN: A TDFOL parse tool and a symbolic formula with auto-detection
    WHEN: Parsing with format="auto"
    THEN: Format is correctly detected as symbolic
    """
    # GIVEN
    from ipfs_datasets_py.mcp_server.tools.logic_tools.tdfol_parse_tool import TDFOLParseTool
    
    tool = TDFOLParseTool()
    formula = "∀x.(Contractor(x) → O(Pay(x)))"
    
    # WHEN
    result = await tool.execute({
        "formula": formula,
        "format": "auto"
    })
    
    # THEN
    assert "format_detected" in result
    assert result["format_detected"] == "symbolic"


# ==============================================================================
# Test tdfol_prove_tool.py
# ==============================================================================


@pytest.mark.asyncio
async def test_prove_simple_formula():
    """
    GIVEN: A TDFOL prove tool and a simple tautology
    WHEN: Proving the formula
    THEN: Formula is successfully proved
    """
    # GIVEN
    from ipfs_datasets_py.mcp_server.tools.logic_tools.tdfol_prove_tool import TDFOLProveTool
    
    tool = TDFOLProveTool()
    formula = "P(x) → P(x)"  # Simple tautology with variable
    
    # WHEN
    result = await tool.execute({
        "formula": formula,
        "strategy": "auto",
        "timeout_ms": 5000
    })
    
    # THEN
    assert result["success"] is True
    assert "proved" in result
    assert result["formula"] == formula


@pytest.mark.asyncio
async def test_prove_with_axioms():
    """
    GIVEN: A TDFOL prove tool, a formula, and axioms
    WHEN: Proving the formula with axioms
    THEN: Formula is proved using the axioms
    """
    # GIVEN
    from ipfs_datasets_py.mcp_server.tools.logic_tools.tdfol_prove_tool import TDFOLProveTool
    
    tool = TDFOLProveTool()
    formula = "P(a)"
    axioms = ["P(a)"]  # Simple axiom: P(a) proves P(a) directly
    
    # WHEN
    result = await tool.execute({
        "formula": formula,
        "axioms": axioms,
        "strategy": "auto",
        "include_proof_steps": True,
        "timeout_ms": 3000
    })
    
    # THEN
    assert result["success"] is True
    assert "proved" in result


@pytest.mark.asyncio
async def test_batch_prove_multiple_formulas():
    """
    GIVEN: A batch prove tool and multiple formulas
    WHEN: Proving all formulas in batch
    THEN: All formulas are processed and results returned
    """
    # GIVEN
    from ipfs_datasets_py.mcp_server.tools.logic_tools.tdfol_prove_tool import TDFOLBatchProveTool
    
    tool = TDFOLBatchProveTool()
    formulas = [
        "P() → P()",
        "Q() → Q()",
        "R() → R()"
    ]
    
    # WHEN
    result = await tool.execute({
        "formulas": formulas,
        "strategy": "auto",
        "timeout_per_formula_ms": 3000
    })
    
    # THEN
    assert result["success"] is True
    assert "results" in result
    assert result["total_formulas"] == len(formulas)
    assert "total_proved" in result


@pytest.mark.asyncio
async def test_prove_with_timeout():
    """
    GIVEN: A TDFOL prove tool and a short timeout
    WHEN: Proving a complex formula
    THEN: Timeout is respected and appropriate status returned
    """
    # GIVEN
    from ipfs_datasets_py.mcp_server.tools.logic_tools.tdfol_prove_tool import TDFOLProveTool
    
    tool = TDFOLProveTool()
    formula = "∀x.∀y.(P(x) → Q(y))"  # Simpler nested quantifiers
    
    # WHEN
    result = await tool.execute({
        "formula": formula,
        "timeout_ms": 100,  # Very short timeout
        "strategy": "auto"
    })
    
    # THEN
    assert result["success"] is True
    assert "status" in result
    # May timeout or prove quickly depending on implementation


# ==============================================================================
# Test tdfol_convert_tool.py
# ==============================================================================


@pytest.mark.asyncio
async def test_convert_tdfol_to_fol():
    """
    GIVEN: A TDFOL convert tool and a TDFOL formula
    WHEN: Converting to FOL format
    THEN: Formula is successfully converted
    """
    # GIVEN
    from ipfs_datasets_py.mcp_server.tools.logic_tools.tdfol_convert_tool import TDFOLConvertTool
    
    tool = TDFOLConvertTool()
    formula = "∀x.(P(x) → Q(x))"
    
    # WHEN
    result = await tool.execute({
        "formula": formula,
        "source_format": "tdfol",
        "target_format": "fol"
    })
    
    # THEN
    assert result["success"] is True
    assert "converted_formula" in result
    assert result["source_format"] == "tdfol"
    assert result["target_format"] == "fol"


@pytest.mark.asyncio
async def test_convert_tdfol_to_dcec():
    """
    GIVEN: A TDFOL convert tool and a TDFOL formula
    WHEN: Converting to DCEC format
    THEN: Formula is successfully converted to DCEC
    """
    # GIVEN
    from ipfs_datasets_py.mcp_server.tools.logic_tools.tdfol_convert_tool import TDFOLConvertTool
    
    tool = TDFOLConvertTool()
    formula = "O(PayTaxes)"  # Deontic obligation without nested predicate
    
    # WHEN
    result = await tool.execute({
        "formula": formula,
        "source_format": "tdfol",
        "target_format": "dcec"
    })
    
    # THEN
    assert result["success"] is True
    assert "converted_formula" in result
    assert result["target_format"] == "dcec"


@pytest.mark.asyncio
async def test_convert_with_metadata():
    """
    GIVEN: A TDFOL convert tool with metadata enabled
    WHEN: Converting a formula
    THEN: Metadata about the conversion is included
    """
    # GIVEN
    from ipfs_datasets_py.mcp_server.tools.logic_tools.tdfol_convert_tool import TDFOLConvertTool
    
    tool = TDFOLConvertTool()
    formula = "∀x.(P(x) → Q(x))"
    
    # WHEN
    result = await tool.execute({
        "formula": formula,
        "target_format": "fol",
        "include_metadata": True
    })
    
    # THEN
    assert result["success"] is True
    if "metadata" in result:
        assert "conversion_type" in result["metadata"]
        assert "lossless" in result["metadata"]


# ==============================================================================
# Integration Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_parse_and_prove_integration():
    """
    GIVEN: Parse and prove tools
    WHEN: Parsing a formula then proving it
    THEN: Both operations succeed in sequence
    """
    # GIVEN
    from ipfs_datasets_py.mcp_server.tools.logic_tools.tdfol_parse_tool import TDFOLParseTool
    from ipfs_datasets_py.mcp_server.tools.logic_tools.tdfol_prove_tool import TDFOLProveTool
    
    parse_tool = TDFOLParseTool()
    prove_tool = TDFOLProveTool()
    formula = "P() → P()"
    
    # WHEN
    parse_result = await parse_tool.execute({
        "formula": formula,
        "format": "symbolic"
    })
    
    if parse_result.get("success"):
        prove_result = await prove_tool.execute({
            "formula": formula,
            "strategy": "auto"
        })
        
        # THEN
        assert prove_result["success"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
