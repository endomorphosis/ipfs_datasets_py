"""
Core Integration Test Suite

Tests the integration between the MCP architecture and core package functionality.
"""

import asyncio
import pytest
import logging
from ipfs_datasets_py.deontic_logic import DeonticLogicConverter, DeonticLogicDatabase
from ipfs_datasets_py.mcp_tools.tools.deontic_logic_tools import deontic_logic_tools
from mcp_legal_tools_registry import get_legal_tools, get_tool_names

class TestCoreIntegration:
    """Test core package integration with MCP architecture"""
    
    def setup_method(self):
        """Setup test environment"""
        self.converter = DeonticLogicConverter()
        self.database = DeonticLogicDatabase()
        
    def test_core_package_imports(self):
        """Test that core package modules can be imported"""
        from ipfs_datasets_py.deontic_logic import DeonticLogicConverter
        from ipfs_datasets_py.deontic_logic import DeonticLogicDatabase
        from ipfs_datasets_py.deontic_logic import DeonticLogicAnalyzer
        
        assert DeonticLogicConverter is not None
        assert DeonticLogicDatabase is not None
        assert DeonticLogicAnalyzer is not None
    
    def test_mcp_tools_registration(self):
        """Test that MCP tools are properly registered"""
        tools = get_legal_tools()
        tool_names = get_tool_names()
        
        # Check required tools are registered
        required_tools = [
            'convert_text_to_logic',
            'search_deontic_statements', 
            'get_deontic_statistics',
            'detect_logical_conflicts',
            'analyze_legal_topic'
        ]
        
        for tool_name in required_tools:
            assert tool_name in tool_names, f"Tool {tool_name} not registered"
            assert tool_name in tools, f"Tool {tool_name} not in tools dictionary"
    
    @pytest.mark.asyncio
    async def test_mcp_tool_conversion(self):
        """Test MCP tool for text conversion"""
        test_text = "States must provide equal educational opportunities."
        
        result = await deontic_logic_tools.convert_text_to_logic(test_text)
        
        assert result['success'] == True
        assert result['count'] > 0
        assert len(result['statements']) > 0
        
        # Check statement structure
        statement = result['statements'][0]
        assert 'logic_expression' in statement
        assert 'natural_language' in statement
        assert 'confidence' in statement
        assert 'modality' in statement
    
    @pytest.mark.asyncio
    async def test_mcp_tool_search(self):
        """Test MCP tool for searching statements"""
        # First add some test data
        test_text = "Courts must ensure due process."
        await deontic_logic_tools.convert_text_to_logic(test_text)
        
        # Search for it
        result = await deontic_logic_tools.search_statements("due process")
        
        assert result['success'] == True
        assert isinstance(result['statements'], list)
    
    @pytest.mark.asyncio
    async def test_mcp_tool_statistics(self):
        """Test MCP tool for database statistics"""
        result = await deontic_logic_tools.get_database_statistics()
        
        assert result['success'] == True
        assert 'statistics' in result
        
        stats = result['statistics']
        assert 'total_statements' in stats
        assert 'modality_distribution' in stats
        assert 'topic_count' in stats
    
    def test_direct_core_functionality(self):
        """Test direct use of core functionality"""
        # Test converter directly
        statements = self.converter.convert_text("Courts shall ensure justice.")
        assert len(statements) > 0
        
        # Test database directly
        statement = statements[0]
        stmt_id = self.database.store_statement(statement)
        assert stmt_id > 0
        
        # Test statistics
        stats = self.database.get_statistics()
        assert stats['total_statements'] >= 1

if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])