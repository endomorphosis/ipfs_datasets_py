"""
Tests for NormalizedContent dataclass (pytest version).

This module contains tests for the NormalizedContent class, covering
initialization, dictionary conversion, and data integrity.

Converted from unittest to pytest format.
"""
import pytest
from unittest.mock import MagicMock
import copy
from dataclasses import FrozenInstanceError

# Skip tests if the module can't be imported
try:
    from core.text_normalizer._normalized_content import NormalizedContent
    from core.content_extractor._content import Content
    from logger import logger as debug_logger
except ImportError:
    pytest.skip("core.text_normalizer._normalized_content module not available", allow_module_level=True)


@pytest.fixture
def mock_content():
    """Create a mock Content object for testing."""
    mock_content = MagicMock(spec=Content)
    mock_content.text = "This is some sample text content"
    mock_content.metadata = {
        "source": "test_file.txt",
        "count": 42,
        "format": "txt"
    }
    mock_content.to_dict.return_value = {
        "text": mock_content.text,
        "metadata": mock_content.metadata,
        "source_path": "test_file.txt",
        "source_format": "txt"
    }
    return mock_content


@pytest.fixture
def sample_normalized_by():
    """Sample normalizer list for testing."""
    return ["whitespace", "unicode", "linebreaks"]


@pytest.fixture
def sample_text():
    """Sample text for testing."""
    return "This is some normalized text content"


@pytest.fixture
def sample_metadata():
    """Sample metadata for testing."""
    return {"source": "test_file.txt", "count": 42, "format": "txt"}


@pytest.mark.unit
class TestNormalizedContentInitialization:
    """Test NormalizedContent initialization and configuration."""

    def test_init_with_all_valid_parameters(self, mock_content, sample_normalized_by, sample_text, sample_metadata):
        """
        Test NormalizedContent initialization with all valid parameters.
        
        Expected behavior:
        - Instance created successfully
        - text attribute matches provided text
        - metadata attribute matches provided dictionary
        - normalized_by attribute matches provided list
        """
        # Arrange
        mock_content.text = sample_text
        mock_content.metadata = sample_metadata
        
        # Act
        content = NormalizedContent(
            content=mock_content,
            normalized_by=sample_normalized_by
        )

        # Assert
        assert content.content.text == sample_text
        assert content.content.metadata == sample_metadata
        assert content.normalized_by == sample_normalized_by

    def test_init_with_empty_text(self, sample_normalized_by):
        """
        Test NormalizedContent initialization with empty text.
        
        Expected behavior:
        - Instance created successfully
        - text attribute is empty string
        - Other attributes set correctly
        """
        # Arrange
        mock_content = MagicMock(spec=Content)
        mock_content.text = ""
        mock_content.metadata = {"source": "test_file.txt"}
        
        # Act
        content = NormalizedContent(
            content=mock_content,
            normalized_by=sample_normalized_by
        )
        
        # Assert
        assert content.content.text == ""
        assert content.normalized_by == sample_normalized_by

    def test_init_with_empty_metadata(self, sample_text, sample_normalized_by):
        """
        Test NormalizedContent initialization with empty metadata.
        
        Expected behavior:
        - Instance created successfully
        - metadata attribute is empty dict
        - Other attributes set correctly
        """
        # Arrange
        mock_content = MagicMock(spec=Content)
        mock_content.text = sample_text
        mock_content.metadata = {}
        
        # Act
        norm_content = NormalizedContent(
            content=mock_content,
            normalized_by=sample_normalized_by
        )
        
        # Assert
        assert norm_content.content.text == sample_text
        assert norm_content.content.metadata == {}
        assert norm_content.normalized_by == sample_normalized_by

    def test_init_with_empty_normalized_by_list(self, mock_content, sample_text, sample_metadata):
        """
        Test NormalizedContent initialization with empty normalized_by list.
        
        Expected behavior:
        - Instance created successfully
        - normalized_by attribute is empty list
        - Other attributes set correctly
        """
        # Arrange
        mock_content.text = sample_text
        mock_content.metadata = sample_metadata

        # Act
        norm_content = NormalizedContent(
            content=mock_content,
            normalized_by=[]
        )
        
        # Assert
        assert norm_content.content.text == sample_text
        assert norm_content.content.metadata == sample_metadata
        assert norm_content.normalized_by == []


@pytest.mark.unit
class TestNormalizedContentToDict:
    """Test NormalizedContent.to_dict method."""

    @pytest.fixture
    def normalized_content(self, mock_content):
        """Create a NormalizedContent instance for testing."""
        mock_content.text = "This is some sample text content"
        mock_content.metadata = {"source": "test_file.txt", "count": 42, "format": "txt"}
        
        return NormalizedContent(
            content=mock_content,
            normalized_by=["whitespace", "unicode", "linebreaks"]
        )

    def test_to_dict_returns_all_attributes(self, normalized_content):
        """
        Test that to_dict() returns all attributes correctly.
        
        Expected behavior:
        - Returns dict containing all expected keys
        - Values match original object attributes
        - Includes normalized_by information
        """
        # Act
        result = normalized_content.to_dict()
        
        # Assert
        expected = {
            "text": "This is some sample text content",
            "metadata": {"source": "test_file.txt", "count": 42, "format": "txt"},
            "source_path": "test_file.txt",
            "source_format": "txt",
            "normalized_by": ["whitespace", "unicode", "linebreaks"]
        }
        
        assert result == expected
        assert "text" in result
        assert "metadata" in result
        assert "normalized_by" in result

    def test_to_dict_immutability(self, normalized_content):
        """
        Test that to_dict() returns immutable copies.
        
        Expected behavior:
        - Each call returns a new dict instance
        - Modifying returned dict doesn't affect original object
        - Original object attributes remain unchanged
        """
        # Act
        result1 = normalized_content.to_dict()
        result2 = normalized_content.to_dict()
        
        # Modify the returned dict
        result1["text"] = "Modified text"
        result1["metadata"]["new_key"] = "new_value"
        
        # Assert
        assert result1 is not result2  # Different instances
        assert result2["text"] == "This is some sample text content"  # Original unchanged
        assert "new_key" not in result2["metadata"]  # Original metadata unchanged
        assert normalized_content.content.text == "This is some sample text content"  # Object unchanged

    def test_to_dict_with_empty_values(self):
        """
        Test to_dict() with empty or minimal values.
        
        Expected behavior:
        - Handles empty text gracefully
        - Handles empty metadata gracefully
        - Handles empty normalized_by list gracefully
        """
        # Arrange
        mock_content = MagicMock(spec=Content)
        mock_content.text = ""
        mock_content.metadata = {}
        mock_content.to_dict.return_value = {
            "text": "",
            "metadata": {},
            "source_path": "",
            "source_format": ""
        }
        
        content = NormalizedContent(
            content=mock_content,
            normalized_by=[]
        )
        
        # Act
        result = content.to_dict()
        
        # Assert
        expected = {
            "text": "",
            "metadata": {},
            "source_path": "",
            "source_format": "",
            "normalized_by": []
        }
        
        assert result == expected
        assert result["normalized_by"] == []


@pytest.mark.unit
class TestNormalizedContentEquality:
    """Test NormalizedContent equality and comparison operations."""
    
    def test_equality_with_identical_content(self, mock_content):
        """
        Test equality comparison with identical content.
        
        Expected behavior:
        - Two instances with same values are equal
        - Equality works correctly with Content objects
        """
        # Arrange
        content1 = NormalizedContent(
            content=mock_content,
            normalized_by=["whitespace", "unicode"]
        )
        
        content2 = NormalizedContent(
            content=mock_content,
            normalized_by=["whitespace", "unicode"]
        )
        
        # Act & Assert
        assert content1 == content2

    def test_inequality_with_different_normalized_by(self, mock_content):
        """
        Test inequality comparison with different normalized_by lists.
        
        Expected behavior:
        - Two instances with different normalized_by are not equal
        - Comparison considers all fields
        """
        # Arrange
        content1 = NormalizedContent(
            content=mock_content,
            normalized_by=["whitespace", "unicode"]
        )
        
        content2 = NormalizedContent(
            content=mock_content,
            normalized_by=["whitespace", "unicode", "linebreaks"]
        )
        
        # Act & Assert
        assert content1 != content2

    def test_inequality_with_different_content(self):
        """
        Test inequality comparison with different content objects.
        
        Expected behavior:
        - Two instances with different content are not equal
        - Content differences are detected properly
        """
        # Arrange
        mock_content1 = MagicMock(spec=Content)
        mock_content1.text = "Content 1"
        mock_content1.metadata = {"source": "file1.txt"}
        
        mock_content2 = MagicMock(spec=Content)
        mock_content2.text = "Content 2"
        mock_content2.metadata = {"source": "file2.txt"}
        
        content1 = NormalizedContent(
            content=mock_content1,
            normalized_by=["whitespace"]
        )
        
        content2 = NormalizedContent(
            content=mock_content2,
            normalized_by=["whitespace"]
        )
        
        # Act & Assert
        assert content1 != content2


@pytest.mark.unit  
class TestNormalizedContentRepresentation:
    """Test NormalizedContent string representation methods."""
    
    def test_str_representation(self, mock_content):
        """
        Test string representation of NormalizedContent.
        
        Expected behavior:
        - __str__ returns readable representation
        - Contains key information about content
        - Format is user-friendly
        """
        # Arrange
        mock_content.text = "Sample text"
        mock_content.metadata = {"source": "test.txt"}
        
        content = NormalizedContent(
            content=mock_content,
            normalized_by=["whitespace", "unicode"]
        )
        
        # Act
        str_repr = str(content)
        
        # Assert
        assert "NormalizedContent" in str_repr
        assert "whitespace" in str_repr
        assert "unicode" in str_repr

    def test_repr_representation(self, mock_content):
        """
        Test repr representation of NormalizedContent.
        
        Expected behavior:
        - __repr__ returns valid Python expression (when possible)
        - Contains all necessary information for reconstruction
        - Format is developer-friendly
        """
        # Arrange
        content = NormalizedContent(
            content=mock_content,
            normalized_by=["whitespace"]
        )
        
        # Act
        repr_str = repr(content)
        
        # Assert
        assert "NormalizedContent" in repr_str
        assert "whitespace" in repr_str