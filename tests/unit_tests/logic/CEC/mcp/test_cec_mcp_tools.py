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
