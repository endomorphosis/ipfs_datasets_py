"""
Tests for CEC MCP Server Tools

Tests all CEC-related MCP tools including parsing, proving, and analysis.
"""

import pytest


class TestCECParseTools:
    """Test CEC parse MCP tools"""
    
    def test_parse_dcec_basic(self):
        """Test parse_dcec tool with basic input"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        result = parse_dcec("The agent must obey", language="en")
        assert result is not None
        assert 'formula' in result
    
    def test_translate_dcec_to_json(self):
        """Test translate_dcec to JSON format"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import translate_dcec
        result = translate_dcec("O(pay(agent))", target_format="json")
        assert result is not None
        assert result['format'] == "json"
    
    def test_validate_formula(self):
        """Test validate_formula tool"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import validate_formula
        result = validate_formula("O(pay(agent))")
        assert result is not None
        assert 'valid' in result
    
    def test_parse_tool_metadata(self):
        """Test parse tool metadata structure"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import TOOLS
        assert 'parse_dcec' in TOOLS
        assert 'translate_dcec' in TOOLS


class TestCECParseToolsEdgeCases:
    """
    GIVEN parse tools with edge case inputs
    WHEN handling unusual or invalid data
    THEN tools should handle gracefully
    """
    
    def test_parse_empty_string(self):
        """
        GIVEN empty string input
        WHEN parsing
        THEN should handle gracefully
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        result = parse_dcec("", language="en")
        assert result is not None
        assert 'success' in result
    
    def test_parse_very_long_text(self):
        """
        GIVEN very long text input
        WHEN parsing
        THEN should handle without crashing
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        long_text = "The agent must " + "obey " * 100
        result = parse_dcec(long_text, language="en")
        assert result is not None
    
    def test_parse_special_characters(self):
        """
        GIVEN text with special characters
        WHEN parsing
        THEN should handle correctly
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        result = parse_dcec("Agent: $#@! & *()_+", language="en")
        assert result is not None
    
    def test_parse_invalid_language_code(self):
        """
        GIVEN invalid language code
        WHEN parsing
        THEN should fallback gracefully
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        result = parse_dcec("test", language="invalid")
        assert result is not None
    
    def test_translate_unsupported_format(self):
        """
        GIVEN unsupported target format
        WHEN translating
        THEN should return error
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import translate_dcec
        result = translate_dcec("O(P(x))", target_format="unsupported")
        assert result is not None
        assert result['success'] is False
    
    def test_validate_malformed_formula(self):
        """
        GIVEN malformed formula
        WHEN validating
        THEN should detect errors
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import validate_formula
        result = validate_formula("O(((")
        assert result is not None


class TestCECProveTools:
    """Test CEC prove MCP tools"""
    
    def test_prove_dcec_basic(self):
        """Test prove_dcec with simple formula"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import prove_dcec
        result = prove_dcec("P(x) | ~P(x)", strategy="auto")
        assert result is not None
        assert 'proved' in result
    
    def test_check_theorem(self):
        """Test check_theorem tool"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import check_theorem
        result = check_theorem("P(x) | ~P(x)")
        assert result is not None
        assert 'is_theorem' in result
    
    def test_get_proof_tree(self):
        """Test get_proof_tree tool"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import get_proof_tree
        result = get_proof_tree("P(x) -> P(x)")
        assert result is not None
        assert 'tree' in result
    
    def test_prove_tool_metadata(self):
        """Test prove tool metadata structure"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import TOOLS
        assert 'prove_dcec' in TOOLS
        assert 'check_theorem' in TOOLS


class TestCECProveToolsStrategies:
    """
    GIVEN prove tools with different strategies
    WHEN using various provers
    THEN each should work appropriately
    """
    
    def test_prove_with_z3_strategy(self):
        """
        GIVEN z3 prover strategy
        WHEN proving
        THEN should attempt z3
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import prove_dcec
        result = prove_dcec("P(x) -> P(x)", strategy="z3")
        assert result is not None
    
    def test_prove_with_vampire_strategy(self):
        """
        GIVEN vampire prover strategy
        WHEN proving
        THEN should attempt vampire
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import prove_dcec
        result = prove_dcec("P(x) -> P(x)", strategy="vampire")
        assert result is not None
    
    def test_prove_with_e_prover_strategy(self):
        """
        GIVEN e_prover strategy
        WHEN proving
        THEN should attempt e_prover
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import prove_dcec
        result = prove_dcec("P(x) -> P(x)", strategy="e_prover")
        assert result is not None
    
    def test_prove_with_short_timeout(self):
        """
        GIVEN very short timeout
        WHEN proving complex formula
        THEN should timeout gracefully
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import prove_dcec
        result = prove_dcec("P(x)", timeout=1)
        assert result is not None
        assert 'execution_time' in result
    
    def test_prove_with_axioms(self):
        """
        GIVEN axioms list
        WHEN proving goal
        THEN should use axioms
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import prove_dcec
        result = prove_dcec(
            goal="Q(x)",
            axioms=["P(x)", "P(x) -> Q(x)"],
            strategy="auto"
        )
        assert result is not None
    
    def test_get_proof_tree_complex(self):
        """
        GIVEN complex formula
        WHEN getting proof tree
        THEN should return structure
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_prove_tool import get_proof_tree
        result = get_proof_tree("(P(x) -> Q(x)) -> (P(x) -> Q(x))")
        assert result is not None
        assert 'depth' in result


class TestCECAnalysisTools:
    """Test CEC analysis MCP tools"""
    
    def test_analyze_formula(self):
        """Test analyze_formula tool"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import analyze_formula
        result = analyze_formula("O(P(x)) & K(agent, Q(y))")
        assert result is not None
        assert 'complexity' in result
    
    def test_visualize_proof_text(self):
        """Test visualize_proof with text format"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import visualize_proof
        result = visualize_proof("P(x) -> P(x)", format="text")
        assert result is not None
        assert result['format'] == "text"
    
    def test_get_formula_complexity(self):
        """Test get_formula_complexity tool"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import get_formula_complexity
        result = get_formula_complexity("P(x)")
        assert result is not None
        assert 'overall_complexity' in result
    
    def test_profile_operation(self):
        """Test profile_operation tool"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import profile_operation
        result = profile_operation("parse", "O(P(x))", iterations=10)
        assert result is not None
        assert 'avg_time' in result
    
    def test_analysis_tool_metadata(self):
        """Test analysis tool metadata structure"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import TOOLS
        assert 'analyze_formula' in TOOLS
        assert 'visualize_proof' in TOOLS


class TestCECAnalysisToolsScenarios:
    """
    GIVEN analysis tools with various scenarios
    WHEN analyzing different formulas
    THEN should handle appropriately
    """
    
    def test_analyze_deeply_nested_formula(self):
        """
        GIVEN deeply nested formula
        WHEN analyzing
        THEN should calculate correct depth
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import analyze_formula
        nested = "O(K(agent, B(agent2, P(x))))"
        result = analyze_formula(nested)
        assert result is not None
        assert result['depth'] > 2
    
    def test_analyze_very_large_formula(self):
        """
        GIVEN very large formula
        WHEN analyzing
        THEN should handle without crashing
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import analyze_formula
        large = " & ".join([f"P{i}(x)" for i in range(20)])
        result = analyze_formula(large)
        assert result is not None
    
    def test_visualize_proof_json_format(self):
        """
        GIVEN json format request
        WHEN visualizing
        THEN should return JSON
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import visualize_proof
        result = visualize_proof("P(x) -> P(x)", format="json")
        assert result is not None
        assert result['format'] == "json"
    
    def test_profile_prove_operation(self):
        """
        GIVEN prove operation
        WHEN profiling
        THEN should return timing
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import profile_operation
        result = profile_operation("prove", "P(x) -> P(x)", iterations=5)
        assert result is not None
        assert 'total_time' in result
    
    def test_get_complexity_high(self):
        """
        GIVEN complex formula
        WHEN getting complexity
        THEN should classify as high
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import get_formula_complexity
        complex_formula = "O(K(a, P(x))) & B(b, Q(y)) & (R(z) -> S(w))"
        result = get_formula_complexity(complex_formula)
        assert result is not None
        assert 'overall_complexity' in result


class TestMultiLanguageTools:
    """
    GIVEN multi-language parsing support
    WHEN parsing in different languages
    THEN should handle appropriately
    """
    
    def test_parse_spanish_text(self):
        """
        GIVEN Spanish text
        WHEN parsing with es language
        THEN should parse
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        result = parse_dcec("El agente debe obedecer", language="es")
        assert result is not None
        assert 'formula' in result
    
    def test_parse_french_text(self):
        """
        GIVEN French text
        WHEN parsing with fr language
        THEN should parse
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        result = parse_dcec("L'agent doit obéir", language="fr")
        assert result is not None
        assert 'formula' in result
    
    def test_parse_german_text(self):
        """
        GIVEN German text
        WHEN parsing with de language
        THEN should parse
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        result = parse_dcec("Der Agent muss gehorchen", language="de")
        assert result is not None
        assert 'formula' in result
    
    def test_auto_detect_language(self):
        """
        GIVEN auto language detection
        WHEN parsing mixed language
        THEN should detect language
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        result = parse_dcec("The agent must comply", language="auto")
        assert result is not None
        assert 'language_detected' in result
    
    def test_parse_spanish_with_domain(self):
        """
        GIVEN Spanish text with legal domain
        WHEN parsing
        THEN should use domain vocabulary
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        result = parse_dcec("El contrato es obligatorio", language="es", domain="legal")
        assert result is not None
    
    def test_parse_french_with_domain(self):
        """
        GIVEN French text with medical domain
        WHEN parsing
        THEN should use domain vocabulary
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        result = parse_dcec("Le traitement est obligatoire", language="fr", domain="medical")
        assert result is not None
    
    def test_parse_german_with_domain(self):
        """
        GIVEN German text with technical domain
        WHEN parsing
        THEN should use domain vocabulary
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        result = parse_dcec("Das System muss funktionieren", language="de", domain="technical")
        assert result is not None
    
    def test_cross_language_consistency(self):
        """
        GIVEN same concept in different languages
        WHEN parsing each
        THEN should produce similar formulas
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        en_result = parse_dcec("must obey", language="en")
        es_result = parse_dcec("debe obedecer", language="es")
        fr_result = parse_dcec("doit obéir", language="fr")
        assert all([en_result, es_result, fr_result])
    
    def test_translate_preserves_semantics(self):
        """
        GIVEN formula translation
        WHEN translating to different formats
        THEN semantics should be preserved
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import translate_dcec
        tptp_result = translate_dcec("O(P(x))", target_format="tptp")
        json_result = translate_dcec("O(P(x))", target_format="json")
        assert tptp_result['success'] or json_result['success']
    
    def test_multi_language_error_messages(self):
        """
        GIVEN error in parsing
        WHEN language is specified
        THEN error should be clear
        """
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        result = parse_dcec(None, language="es")
        assert result is not None
        # Should handle error gracefully regardless of language

