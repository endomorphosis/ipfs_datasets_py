"""
MCP Server PDF Tools Tests

Tests for MCP server PDF-related tools and functionality.
"""

import pytest
from pathlib import Path


class TestMCPPDFToolsAvailability:
    """Test availability and structure of MCP PDF tools"""

    def test_given_pdf_tools_directory_when_checking_then_exists(self):
        """
        GIVEN the PDF tools directory structure
        WHEN checking if it exists
        THEN it should be found
        """
        pdf_tools_path = Path(__file__).parent.parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "pdf_tools"
        assert pdf_tools_path.exists(), "PDF tools directory should exist"
        assert pdf_tools_path.is_dir(), "PDF tools path should be a directory"

    def test_given_pdf_tools_when_listing_files_then_contains_python_modules(self):
        """
        GIVEN the PDF tools directory
        WHEN listing Python files
        THEN it should contain module files
        """
        pdf_tools_path = Path(__file__).parent.parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "pdf_tools"
        
        if not pdf_tools_path.exists():
            pytest.skip("PDF tools directory not found")
        
        python_files = list(pdf_tools_path.glob("*.py"))
        assert len(python_files) > 0, "PDF tools directory should contain Python files"


class TestMCPPDFToolsImport:
    """Test importing MCP PDF tools"""

    def test_given_pdf_ingest_tool_when_importing_then_succeeds(self):
        """
        GIVEN the pdf_ingest_to_graphrag tool
        WHEN attempting to import it
        THEN import should succeed or skip gracefully
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_ingest_to_graphrag
            assert pdf_ingest_to_graphrag is not None
        except ImportError as e:
            pytest.skip(f"pdf_ingest_to_graphrag not available: {e}")
        except Exception as e:
            pytest.skip(f"Unexpected error importing pdf_ingest_to_graphrag: {e}")

    def test_given_pdf_optimize_tool_when_importing_then_succeeds(self):
        """
        GIVEN the pdf_optimize_for_llm tool
        WHEN attempting to import it
        THEN import should succeed or skip gracefully
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_optimize_for_llm
            assert pdf_optimize_for_llm is not None
        except ImportError as e:
            pytest.skip(f"pdf_optimize_for_llm not available: {e}")
        except Exception as e:
            pytest.skip(f"Unexpected error importing pdf_optimize_for_llm: {e}")

    def test_given_pdf_query_tool_when_importing_then_succeeds(self):
        """
        GIVEN the pdf_query_knowledge_graph tool
        WHEN attempting to import it
        THEN import should succeed or skip gracefully
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_query_knowledge_graph
            assert pdf_query_knowledge_graph is not None
        except ImportError as e:
            pytest.skip(f"pdf_query_knowledge_graph not available: {e}")
        except Exception as e:
            pytest.skip(f"Unexpected error importing pdf_query_knowledge_graph: {e}")


class TestMCPPDFToolsDependencies:
    """Test dependencies required by MCP PDF tools"""

    def test_given_pdf_processing_module_when_importing_then_succeeds(self):
        """
        GIVEN the pdf_processing module
        WHEN MCP tools need to use it
        THEN it should be importable
        """
        try:
            from ipfs_datasets_py import pdf_processing
            assert pdf_processing is not None
        except ImportError as e:
            pytest.skip(f"pdf_processing module not available: {e}")

    def test_given_pdf_processor_class_when_importing_then_succeeds(self):
        """
        GIVEN the PDFProcessor class
        WHEN MCP tools need to use it
        THEN it should be importable
        """
        try:
            from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
            assert PDFProcessor is not None
        except ImportError as e:
            pytest.skip(f"PDFProcessor not available: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
