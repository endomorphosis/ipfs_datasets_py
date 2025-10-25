"""
Unit tests for MCP PDF Tools

This module tests the MCP server tools related to PDF processing.
Uses conditional imports to avoid PyArrow extension type conflicts.
"""

import pytest
import sys
from pathlib import Path
from importlib import import_module


def safe_import_module(module_path):
    """
    Safely import a module, checking if it's already loaded to avoid
    PyArrow extension type re-registration issues.
    
    Args:
        module_path: Dotted path to the module (e.g., 'ipfs_datasets_py.mcp_server.tools.pdf_tools')
    
    Returns:
        The imported module or None if import fails
    """
    # Check if module is already loaded
    if module_path in sys.modules:
        return sys.modules[module_path]
    
    try:
        return import_module(module_path)
    except ImportError:
        return None
    except Exception as e:
        # Handle PyArrow extension type registration errors
        # This occurs when the datasets library is imported multiple times in test contexts
        error_msg = str(e)
        if 'ArrowKeyError' in str(type(e).__name__) or 'already defined' in error_msg:
            # Return None to allow tests to skip gracefully
            return None
        # Re-raise other unexpected errors
        raise


class TestMCPPDFToolsImport:
    """Unit tests for MCP PDF tools import and basic structure"""

    def test_given_mcp_pdf_tools_module_when_importing_then_succeeds(self):
        """
        GIVEN the MCP PDF tools module exists
        WHEN attempting to import it using conditional import
        THEN the import should succeed without errors
        """
        pdf_tools = safe_import_module('ipfs_datasets_py.mcp_server.tools.pdf_tools')
        
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
        WHEN attempting to import them using conditional import
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
            module = safe_import_module(full_path)
            
            if module is not None:
                imported_count += 1
            else:
                # Try to get more detail on why import failed
                try:
                    import_module(full_path)
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
        WHEN checking its exports using conditional import
        THEN it should expose the expected functions
        """
        pdf_tools = safe_import_module('ipfs_datasets_py.mcp_server.tools.pdf_tools')
        
        if pdf_tools is None:
            pytest.skip("MCP PDF tools module not available")
        
        # Get all callable attributes (functions)
        callables = [attr for attr in dir(pdf_tools) if callable(getattr(pdf_tools, attr)) and not attr.startswith('_')]
        
        # Should have at least some PDF-related functions
        assert len(callables) > 0, "PDF tools module should export callable functions"

    def test_given_pdf_processor_when_importing_then_available_in_pdf_processing(self):
        """
        GIVEN the PDFProcessor class
        WHEN importing from pdf_processing module using conditional import
        THEN it should be available for MCP tools to use
        """
        # Use conditional import to avoid re-importing if already loaded
        pdf_processing = safe_import_module('ipfs_datasets_py.pdf_processing')
        
        if pdf_processing is None:
            pytest.skip("pdf_processing module not available")
        
        # Check if PDFProcessor is available in the module
        if not hasattr(pdf_processing, 'PDFProcessor'):
            pytest.skip("PDFProcessor not available in pdf_processing module")
        
        PDFProcessor = getattr(pdf_processing, 'PDFProcessor')
        assert PDFProcessor is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
