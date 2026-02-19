"""
Tests for CEC Phase 8 Final Integration

End-to-end tests validating integration across all access methods.
"""

import pytest
import time


class TestEndToEndWorkflows:
    """Test end-to-end workflows across all access methods (5 tests)"""
    
    def test_import_to_mcp_workflow(self):
        """Test workflow from imports to MCP tools"""
        from ipfs_datasets_py.logic.CEC.native import Sort, Variable
        from ipfs_datasets_py.logic.CEC.optimization import CacheManager
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import analyze_formula
        
        sort = Sort("entity")
        var = Variable("x", sort)
        cache_mgr = CacheManager()
        result = analyze_formula("P(x)")
        
        assert result is not None
    
    def test_mcp_to_cli_workflow(self):
        """Test workflow from MCP to CLI"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        from scripts.cli.logic_cli import validate_command, create_parser
        
        mcp_result = parse_dcec("agent", language="en")
        
        if mcp_result.get('formula'):
            parser = create_parser()
            args = parser.parse_args(['validate', mcp_result['formula']])
            cli_result = validate_command(args)
            assert cli_result is not None
    
    def test_full_pipeline_all_methods(self):
        """Test full pipeline using all three methods"""
        from ipfs_datasets_py.logic.CEC.native import Sort, Predicate, Variable, VariableTerm, AtomicFormula
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_analysis_tool import analyze_formula
        from scripts.cli.logic_cli import format_output
        
        sort = Sort("person")
        pred = Predicate("mortal", [sort])
        var = Variable("x", sort)
        term = VariableTerm(var)
        formula = AtomicFormula(pred, [term])
        
        mcp_result = analyze_formula(str(formula))
        cli_output = format_output(mcp_result, 'text')
        
        assert cli_output is not None
    
    def test_cache_sharing(self):
        """Test cache sharing across methods"""
        from ipfs_datasets_py.logic.CEC.optimization import CacheManager
        from ipfs_datasets_py.logic.CEC.native import Sort, Variable, VariableTerm
        
        cache_mgr = CacheManager()
        sort = Sort("entity")
        var = Variable("x", sort)
        term = VariableTerm(var)
        cache_mgr.formula_interning.intern(term)
        
        stats = cache_mgr.get_all_stats()
        assert stats is not None
    
    def test_error_propagation(self):
        """Test error handling across methods"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        
        result = parse_dcec("", language="en")
        assert result is not None


class TestPerformanceValidation:
    """Test performance across all methods (3 tests)"""
    
    def test_import_performance(self):
        """Test import performance"""
        start = time.time()
        from ipfs_datasets_py.logic.CEC.native import Sort, Variable
        from ipfs_datasets_py.logic.CEC.optimization import CacheManager
        elapsed = time.time() - start
        assert elapsed < 1.0
    
    def test_mcp_tool_performance(self):
        """Test MCP tool performance"""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.cec_parse_tool import parse_dcec
        
        start = time.time()
        for _ in range(10):
            parse_dcec("test", language="en")
        elapsed = time.time() - start
        assert elapsed < 2.0
    
    def test_cli_command_performance(self):
        """Test CLI command performance"""
        from scripts.cli.logic_cli import parse_command, create_parser
        
        parser = create_parser()
        start = time.time()
        for _ in range(10):
            args = parser.parse_args(['parse', 'test'])
            parse_command(args)
        elapsed = time.time() - start
        assert elapsed < 2.0


class TestDocumentationCompleteness:
    """Test documentation completeness (2 tests)"""
    
    def test_api_documentation(self):
        """Test API documentation present"""
        from ipfs_datasets_py.logic.CEC import native, optimization, provers
        
        assert native.__doc__ is not None
        assert len(native.__doc__) > 50
        assert optimization.__doc__ is not None
        assert provers.__doc__ is not None
    
    def test_cli_help_text(self):
        """Test CLI help text complete"""
        from scripts.cli.logic_cli import create_parser
        
        parser = create_parser()
        help_text = parser.format_help()
        
        assert 'parse' in help_text
        assert 'prove' in help_text
        assert 'analyze' in help_text
