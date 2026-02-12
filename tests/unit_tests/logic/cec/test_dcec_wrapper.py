"""
Unit tests for DCEC Library Wrapper.

These tests validate the wrapper functionality for the DCEC_Library submodule.
"""

import pytest
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from ipfs_datasets_py.logic.CEC.dcec_wrapper import (
    DCECLibraryWrapper,
    DCECStatement
)


class TestDCECLibraryWrapper:
    """Test suite for DCECLibraryWrapper."""
    
    def test_wrapper_initialization(self):
        """
        GIVEN a DCECLibraryWrapper instance
        WHEN initialized
        THEN it should have the expected initial state
        """
        wrapper = DCECLibraryWrapper()
        
        assert wrapper.container is None
        assert wrapper.namespace is None
        assert wrapper.statements == []
        assert wrapper._initialized is False
    
    def test_wrapper_repr(self):
        """
        GIVEN a DCECLibraryWrapper instance
        WHEN getting its string representation
        THEN it should return a meaningful description
        """
        wrapper = DCECLibraryWrapper()
        repr_str = repr(wrapper)
        
        assert "DCECLibraryWrapper" in repr_str
        assert "not initialized" in repr_str
        assert "statements=0" in repr_str
    
    def test_initialization_without_library(self):
        """
        GIVEN a DCECLibraryWrapper instance
        WHEN attempting to initialize without DCEC_Library installed
        THEN it should handle gracefully and return False
        """
        wrapper = DCECLibraryWrapper()
        
        # This may succeed or fail depending on whether DCEC_Library is available
        # The test validates that it doesn't crash
        result = wrapper.initialize()
        
        assert isinstance(result, bool)
        assert wrapper._initialized == result
    
    def test_add_statement_without_initialization(self):
        """
        GIVEN a DCECLibraryWrapper instance that is not initialized
        WHEN adding a statement
        THEN it should return an invalid DCECStatement with error
        """
        wrapper = DCECLibraryWrapper()
        
        result = wrapper.add_statement("test statement")
        
        assert isinstance(result, DCECStatement)
        assert result.is_valid is False
        assert result.error_message == "Library not initialized"
        assert result.raw_text == "test statement"
    
    def test_get_statements_count(self):
        """
        GIVEN a DCECLibraryWrapper instance
        WHEN getting the statements count
        THEN it should return the correct number
        """
        wrapper = DCECLibraryWrapper()
        
        count = wrapper.get_statements_count()
        
        assert count == 0
    
    def test_get_namespace_info_without_initialization(self):
        """
        GIVEN a DCECLibraryWrapper instance that is not initialized
        WHEN getting namespace info
        THEN it should return an error dictionary
        """
        wrapper = DCECLibraryWrapper()
        
        info = wrapper.get_namespace_info()
        
        assert isinstance(info, dict)
        assert "error" in info
    
    def test_print_statement_without_initialization(self):
        """
        GIVEN a DCECLibraryWrapper instance that is not initialized
        WHEN printing a statement
        THEN it should return None
        """
        wrapper = DCECLibraryWrapper()
        
        result = wrapper.print_statement("test")
        
        assert result is None
    
    def test_save_container_without_initialization(self):
        """
        GIVEN a DCECLibraryWrapper instance that is not initialized
        WHEN saving the container
        THEN it should return False
        """
        wrapper = DCECLibraryWrapper()
        
        result = wrapper.save_container("test_file")
        
        assert result is False
    
    def test_load_container_without_initialization(self):
        """
        GIVEN a DCECLibraryWrapper instance that is not initialized
        WHEN loading a container
        THEN it should return False
        """
        wrapper = DCECLibraryWrapper()
        
        result = wrapper.load_container("test_file")
        
        assert result is False


class TestDCECStatement:
    """Test suite for DCECStatement dataclass."""
    
    def test_dcec_statement_creation(self):
        """
        GIVEN DCECStatement parameters
        WHEN creating a DCECStatement instance
        THEN it should have the correct attributes
        """
        stmt = DCECStatement(
            raw_text="test statement",
            is_valid=True,
            error_message=None
        )
        
        assert stmt.raw_text == "test statement"
        assert stmt.is_valid is True
        assert stmt.error_message is None
        assert stmt.parsed_formula is None
        assert stmt.namespace_info is None
    
    def test_dcec_statement_with_error(self):
        """
        GIVEN DCECStatement parameters with an error
        WHEN creating a DCECStatement instance
        THEN it should store the error information
        """
        stmt = DCECStatement(
            raw_text="invalid statement",
            is_valid=False,
            error_message="Parsing failed"
        )
        
        assert stmt.raw_text == "invalid statement"
        assert stmt.is_valid is False
        assert stmt.error_message == "Parsing failed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
