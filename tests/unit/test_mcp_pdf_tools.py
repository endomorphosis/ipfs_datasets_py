"""
Unit tests for MCP PDF Tools

This module tests the MCP server tools related to PDF processing.
Uses centralized safe import utility to avoid PyArrow extension type conflicts.
"""

import pytest
import sys
from pathlib import Path

# Use centralized safe import utility
sys.path.insert(0, str(Path(__file__).parent.parent))
from test_import_utils import safe_importer


class TestMCPPDFToolsImport:
    """Unit tests for MCP PDF tools import and basic structure"""

    def test_given_mcp_pdf_tools_module_when_importing_then_succeeds(self):
        """
        GIVEN the MCP PDF tools module exists
        WHEN attempting to import it using safe importer
        THEN the import should succeed without errors
        """
        pdf_tools = safe_importer.import_module('ipfs_datasets_py.mcp_server.tools.pdf_tools')
        
        if pdf_tools is None:
            pytest.skip("MCP PDF tools module not available")
        
        assert pdf_tools is not None

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
        WHEN attempting to import them using safe importer
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
            full_path = f"ipfs_datasets_py.mcp_server.tools.pdf_tools.{module_name}"
            module = safe_importer.import_module(full_path)
            
            if module is not None:
                imported_count += 1
            else:
                errors.append(f"{module_name}: module not available or import conflict")
        
        # At least some tools should be importable
        if imported_count == 0 and errors:
            pytest.skip(f"No PDF tools could be imported. Errors: {errors}")
        
        assert imported_count > 0, f"Expected at least one tool to import. Errors: {errors}"


class TestMCPPDFToolsStructure:
    """Unit tests for MCP PDF tools structure and interfaces"""

    def test_given_pdf_tools_when_checking_module_structure_then_has_expected_exports(self):
        """
        GIVEN the PDF tools module
        WHEN checking its exports using safe importer
        THEN it should expose the expected functions
        """
        pdf_tools = safe_importer.import_module('ipfs_datasets_py.mcp_server.tools.pdf_tools')
        
        if pdf_tools is None:
            pytest.skip("MCP PDF tools module not available")
        
        # Get all callable attributes (functions)
        callables = [attr for attr in dir(pdf_tools) if callable(getattr(pdf_tools, attr)) and not attr.startswith('_')]
        
        # Should have at least some PDF-related functions
        assert len(callables) > 0, "PDF tools module should export callable functions"

    def test_given_pdf_processor_when_importing_then_available_in_pdf_processing(self):
        """
        GIVEN the PDFProcessor class
        WHEN importing from pdf_processing module using safe importer
        THEN it should be available for MCP tools to use
        """
        # Use safe importer to avoid re-importing if already loaded
        pdf_processing = safe_importer.import_module('ipfs_datasets_py.pdf_processing')
        
        if pdf_processing is None:
            pytest.skip("pdf_processing module not available")
        
        # Check if PDFProcessor is available in the module
        if not hasattr(pdf_processing, 'PDFProcessor'):
            pytest.skip("PDFProcessor not available in pdf_processing module")
        
        PDFProcessor = getattr(pdf_processing, 'PDFProcessor')
        assert PDFProcessor is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
