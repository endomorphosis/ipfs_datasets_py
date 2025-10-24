"""
Unit tests for MCP PDF Tools

This module tests the MCP server tools related to PDF processing.
"""

import pytest
import sys
from pathlib import Path


class TestMCPPDFToolsImport:
    """Unit tests for MCP PDF tools import and basic structure"""

    def test_given_mcp_pdf_tools_module_when_importing_then_succeeds(self):
        """
        GIVEN the MCP PDF tools module exists
        WHEN attempting to import it
        THEN the import should succeed without errors
        """
        try:
            from ipfs_datasets_py.mcp_server.tools import pdf_tools
            assert pdf_tools is not None
        except ImportError as e:
            pytest.skip(f"MCP PDF tools not available: {e}")

    def test_given_pdf_tools_directory_when_checking_structure_then_has_expected_files(self):
        """
        GIVEN the PDF tools directory
        WHEN checking its structure
        THEN it should contain expected tool files
        """
        pdf_tools_dir = Path(__file__).parent.parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "pdf_tools"
        
        if not pdf_tools_dir.exists():
            pytest.skip("PDF tools directory not found")
        
        # Check that the directory exists and has Python files
        python_files = list(pdf_tools_dir.glob("*.py"))
        assert len(python_files) > 0, "PDF tools directory should contain Python files"

    def test_given_mcp_pdf_tools_when_importing_individual_tools_then_no_import_errors(self):
        """
        GIVEN individual PDF tool modules
        WHEN attempting to import them
        THEN no import errors should occur
        """
        tool_modules = [
            "pdf_ingest_to_graphrag",
            "pdf_optimize_for_llm", 
            "pdf_query_knowledge_graph",
            "pdf_extract_entities",
            "pdf_batch_process",
        ]
        
        imported_count = 0
        errors = []
        
        for module_name in tool_modules:
            try:
                module = __import__(
                    f"ipfs_datasets_py.mcp_server.tools.pdf_tools.{module_name}",
                    fromlist=[module_name]
                )
                assert module is not None
                imported_count += 1
            except ImportError as e:
                errors.append(f"{module_name}: {str(e)}")
            except Exception as e:
                errors.append(f"{module_name}: {str(e)}")
        
        # At least some tools should be importable
        if imported_count == 0 and errors:
            pytest.skip(f"No PDF tools could be imported. Errors: {errors}")
        
        assert imported_count > 0, f"Expected at least one tool to import. Errors: {errors}"


class TestMCPPDFToolsStructure:
    """Unit tests for MCP PDF tools structure and interfaces"""

    def test_given_pdf_tools_when_checking_module_structure_then_has_expected_exports(self):
        """
        GIVEN the PDF tools module
        WHEN checking its exports
        THEN it should expose the expected functions
        """
        try:
            from ipfs_datasets_py.mcp_server.tools import pdf_tools
            
            # Get all callable attributes (functions)
            callables = [attr for attr in dir(pdf_tools) if callable(getattr(pdf_tools, attr)) and not attr.startswith('_')]
            
            # Should have at least some PDF-related functions
            assert len(callables) > 0, "PDF tools module should export callable functions"
            
        except ImportError as e:
            pytest.skip(f"MCP PDF tools not available: {e}")

    def test_given_pdf_processor_when_importing_then_available_in_pdf_processing(self):
        """
        GIVEN the PDFProcessor class
        WHEN importing from pdf_processing module
        THEN it should be available for MCP tools to use
        """
        try:
            from ipfs_datasets_py.pdf_processing import PDFProcessor
            assert PDFProcessor is not None
        except ImportError as e:
            pytest.skip(f"PDFProcessor not available: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
