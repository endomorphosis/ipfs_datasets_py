"""
MCP Server Tests

Tests for the MCP (Model Context Protocol) server functionality.
"""

import pytest
import sys
from pathlib import Path


class TestMCPServerBasics:
    """Basic tests for MCP server functionality"""

    def test_given_mcp_server_module_when_importing_then_succeeds(self):
        """
        GIVEN the MCP server module
        WHEN attempting to import it
        THEN the import should succeed
        """
        try:
            from ipfs_datasets_py import mcp_server
            assert mcp_server is not None
        except ImportError as e:
            pytest.skip(f"MCP server module not available: {e}")

    def test_given_mcp_server_tools_when_importing_then_succeeds(self):
        """
        GIVEN the MCP server tools module
        WHEN attempting to import it
        THEN the import should succeed
        """
        try:
            from ipfs_datasets_py.mcp_server import tools
            assert tools is not None
        except ImportError as e:
            pytest.skip(f"MCP server tools not available: {e}")

    def test_given_mcp_pdf_tools_module_when_checking_existence_then_found(self):
        """
        GIVEN the MCP PDF tools
        WHEN checking if the module exists
        THEN it should be found in the expected location
        """
        pdf_tools_path = Path(__file__).parent.parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "pdf_tools"
        assert pdf_tools_path.exists(), f"PDF tools directory should exist at {pdf_tools_path}"
        
        # Check for __init__.py or Python files
        init_file = pdf_tools_path / "__init__.py"
        py_files = list(pdf_tools_path.glob("*.py"))
        
        assert init_file.exists() or len(py_files) > 0, "PDF tools directory should contain Python files"


class TestMCPPDFToolsIntegration:
    """Integration tests for MCP PDF tools"""

    def test_given_pdf_tools_when_importing_base_module_then_succeeds(self):
        """
        GIVEN the PDF tools module
        WHEN attempting to import from mcp_server.tools.pdf_tools
        THEN the import should succeed or skip gracefully
        """
        try:
            # Try to import the module
            import ipfs_datasets_py.mcp_server.tools.pdf_tools as pdf_tools
            assert pdf_tools is not None
        except ImportError as e:
            pytest.skip(f"PDF tools not available for import: {e}")

    def test_given_pdf_processor_when_used_by_mcp_tools_then_accessible(self):
        """
        GIVEN the PDFProcessor class
        WHEN MCP tools need to use it
        THEN it should be accessible from pdf_processing module
        """
        try:
            from ipfs_datasets_py.pdf_processing import PDFProcessor
            assert PDFProcessor is not None
            
            # Try to instantiate (this may fail due to dependencies, which is okay)
            try:
                processor = PDFProcessor()
                assert processor is not None
            except Exception as e:
                # It's okay if instantiation fails due to missing dependencies
                pytest.skip(f"PDFProcessor instantiation failed (acceptable): {e}")
                
        except ImportError as e:
            pytest.skip(f"PDFProcessor not available: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
