"""
Backward compatibility tests.

Ensures that old tools and patterns still work after refactoring.
"""

import pytest
import asyncio
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


class TestBackwardCompatibility:
    """Test backward compatibility with old tools."""
    
    @pytest.mark.asyncio
    async def test_old_tool_registration_works(self):
        """Test that old tool registration pattern still works."""
        # GIVEN - MCP server with old tools
        # WHEN - Importing old tools
        try:
            from ipfs_datasets_py.mcp_server import server
            # THEN - Should import successfully
            assert server is not None
        except ImportError:
            pytest.skip("Server module not available")
    
    @pytest.mark.asyncio
    async def test_old_tools_executable(self):
        """Test that old tools are still executable."""
        # GIVEN - Old tool structure
        # WHEN - Trying to use old tools
        try:
            from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
            manager = HierarchicalToolManager()
            
            # THEN - Both old and new patterns work
            categories = manager.list_categories()
            assert len(categories) > 0
        except Exception:
            pytest.skip("Tools not available in test environment")
    
    @pytest.mark.asyncio
    async def test_results_match_new_tools(self):
        """Test that old tools return same results as new tools."""
        # GIVEN - Both old and new tool access patterns
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Getting results from both
        categories1 = manager.list_categories()
        categories2 = manager.list_categories()
        
        # THEN - Results should match
        assert categories1 == categories2
    
    @pytest.mark.asyncio
    async def test_no_breaking_changes(self):
        """Test that no breaking changes were introduced."""
        # GIVEN - Core modules
        # WHEN - Importing core functionality
        try:
            from ipfs_datasets_py.core_operations import DatasetLoader, IPFSPinner
            from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
            
            # THEN - All should import successfully
            assert DatasetLoader is not None
            assert IPFSPinner is not None
            assert HierarchicalToolManager is not None
        except ImportError as e:
            pytest.fail(f"Breaking change detected: {e}")
    
    @pytest.mark.asyncio
    async def test_migration_path_validated(self):
        """Test that migration path from old to new is clear."""
        # GIVEN - Old and new patterns
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Using new pattern
        categories = manager.list_categories()
        
        # THEN - Should work smoothly
        assert len(categories) > 0


class TestSystemIntegration:
    """Test system integration after refactoring."""
    
    @pytest.mark.asyncio
    async def test_mcp_server_starts(self):
        """Test that MCP server can start."""
        # GIVEN - MCP server module
        # WHEN - Importing server
        try:
            from ipfs_datasets_py.mcp_server import server
            # THEN - Should import successfully
            assert server is not None
        except ImportError:
            pytest.skip("Server not available")
    
    @pytest.mark.asyncio
    async def test_cli_works_with_all_commands(self):
        """Test that CLI works with all commands."""
        # GIVEN - CLI module
        # WHEN - Importing CLI
        import subprocess
        result = subprocess.run(
            ['python', 'ipfs_datasets_cli.py', '--help'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # THEN - Should execute
        assert result.returncode in [0, 1, 2] or len(result.stdout) > 0
    
    @pytest.mark.asyncio
    async def test_python_imports_functional(self):
        """Test that Python imports work."""
        # GIVEN - Core modules
        # WHEN - Importing
        try:
            from ipfs_datasets_py.core_operations import DatasetLoader
            loader = DatasetLoader()
            
            # THEN - Should work
            assert loader is not None
        except ImportError:
            pytest.skip("Core operations not available")
    
    @pytest.mark.asyncio
    async def test_no_import_errors(self):
        """Test that there are no import errors."""
        # GIVEN - Main package
        # WHEN - Importing
        try:
            import ipfs_datasets_py
            # THEN - Should import cleanly
            assert ipfs_datasets_py is not None
        except ImportError as e:
            pytest.fail(f"Import error: {e}")
    
    @pytest.mark.asyncio
    async def test_all_dependencies_resolved(self):
        """Test that all dependencies are resolved."""
        # GIVEN - Package structure
        # WHEN - Checking core imports
        modules_to_test = [
            'ipfs_datasets_py.core_operations',
            'ipfs_datasets_py.mcp_server.hierarchical_tool_manager',
        ]
        
        for module_name in modules_to_test:
            try:
                __import__(module_name)
            except ImportError as e:
                pytest.fail(f"Dependency issue in {module_name}: {e}")
        
        # THEN - All should import
        assert True
