import unittest
from unittest.mock import MagicMock
import copy
from dataclasses import FrozenInstanceError



from core.text_normalizer._normalized_content import NormalizedContent
from core.content_extractor._content import Content


from logger import logger as debug_logger


def make_mock_content():
    """Create a mock Content object for testing."""
    def _make_mock():
        mock_content = MagicMock(spec=Content)
        mock_content.text = MagicMock(return_value="This is some sample text content")
        mock_content.metadata = MagicMock(return_value={
            "source": "test_file.txt",
            "count": 42,
            "format": "txt"
        })
        return mock_content
    return copy.deepcopy(_make_mock())


def make_mock_normalized_content():
    """Create a mock NormalizedContent object for testing."""
    def _make_mock():
        mock_normalized_content = MagicMock(spec=NormalizedContent)
        mock_normalized_content.content = make_mock_content()
        mock_normalized_content.normalized_by = ["whitespace", "unicode", "linebreaks"]
        return mock_normalized_content
    return copy.deepcopy(_make_mock())


class TestNormalizedContentInitialization(unittest.TestCase):
    """Test NormalizedContent initialization and configuration."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_content = make_mock_content()

        self.sample_text = "This is some normalized text content"
        self.sample_metadata = {"source": "test_file.txt", "count": 42, "format": "txt"}

        self.mock_content.text = self.sample_text
        self.mock_content.metadata = self.sample_metadata

        # Applied to normalized content object.
        self.sample_normalized_by = ["whitespace", "unicode", "linebreaks"]

    def test_init_with_all_valid_parameters(self):
        """
        GIVEN valid parameters:
            - text: A string containing normalized text
            - metadata: A dictionary with arbitrary key-value pairs
            - normalized_by: A list of normalizer names applied
        WHEN NormalizedContent is initialized
        THEN expect:
            - Instance created successfully
            - text attribute matches provided text
            - metadata attribute matches provided dictionary
            - normalized_by attribute matches provided list
        """
        content = NormalizedContent(
            content=self.mock_content,
            normalized_by=self.sample_normalized_by
        )

        self.assertEqual(content.content.text, self.sample_text)
        self.assertEqual(content.content.metadata, self.sample_metadata) # NOTE should be unchanged
        self.assertEqual(content.normalized_by, self.sample_normalized_by)

    def test_init_with_empty_text(self):
        """
        GIVEN empty string for text parameter
        AND valid metadata dict and normalized_by list
        WHEN NormalizedContent is initialized
        THEN expect:
            - Instance created successfully
            - text attribute is empty string
            - Other attributes set correctly
        """
        mock_content = make_mock_content()
        mock_content.text = ""  # Set text to empty string
        content = NormalizedContent(
            content=mock_content,
            normalized_by=self.sample_normalized_by
        )
        
        self.assertEqual(content.content.text, "")
        self.assertEqual(content.normalized_by, self.sample_normalized_by)

    def test_init_with_empty_metadata(self):
        """
        GIVEN valid text string
        AND empty dictionary for metadata
        AND valid normalized_by list
        WHEN NormalizedContent is initialized
        THEN expect:
            - Instance created successfully
            - metadata attribute is empty dict
            - Other attributes set correctly
        """
        mock_content = MagicMock(spec=Content)
        mock_content.text = self.sample_text  # Set text to sample text
        mock_content.metadata = {}  # Set text to dict string

        norm_content = NormalizedContent(
            content=mock_content,
            normalized_by=self.sample_normalized_by
        )
        
        self.assertEqual(norm_content.content.text, self.sample_text)
        self.assertEqual(norm_content.content.metadata, {})
        self.assertEqual(norm_content.normalized_by, self.sample_normalized_by)

    def test_init_with_empty_normalized_by_list(self):
        """
        GIVEN valid text string and metadata dict
        AND empty list for normalized_by
        WHEN NormalizedContent is initialized
        THEN expect:
            - Instance created successfully
            - normalized_by attribute is empty list
            - Other attributes set correctly
        """
        mock_content = MagicMock(spec=Content)
        mock_content.text = self.sample_text  # Set text to sample text
        mock_content.metadata = self.sample_metadata  # Set metadata to sample metadata


        norm_content = NormalizedContent(
            content=self.mock_content,
            normalized_by=[]  # Empty list for normalized_by
        )
        
        self.assertEqual(norm_content.content.text, self.sample_text)
        self.assertEqual(norm_content.content.metadata, self.sample_metadata)
        self.assertEqual(norm_content.normalized_by, [])


class TestNormalizedContentToDict(unittest.TestCase):
    """Test NormalizedContent.to_dict method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_content = MagicMock(spec=Content)
        self.mock_content.text = "This is some sample text content"
        self.mock_content.metadata = {"source": "test_file.txt", "count": 42, "format": "txt"}
        self.mock_content.to_dict.return_value = {
            "text": self.mock_content.text,
            "metadata": self.mock_content.metadata,
            "source_path": "test_file.txt",
            "source_format": "txt"
        }

        self.content = NormalizedContent(
            content=self.mock_content,
            normalized_by=["whitespace", "unicode", "linebreaks"]
        )

    def test_to_dict_returns_all_attributes(self):
        """
        GIVEN NormalizedContent instance with:
            - text: "normalized text content"
            - metadata: {"key": "value", "count": 42}
            - normalized_by: ["whitespace", "unicode", "linebreaks"]
        WHEN to_dict() is called
        THEN expect dict containing:
            - "text" key with matching string value
            - "metadata" key with matching dict value
            - "normalized_by" key with matching list value
        """
        result = self.content.to_dict()
        
        expected = {
            "text": self.mock_content.text,
            "metadata": self.mock_content.metadata,
            "source_path": "test_file.txt",
            "source_format": "txt",
            "normalized_by": ["whitespace", "unicode", "linebreaks"]
        }
        self.assertEqual(result, expected)
        self.assertIn("text", result)
        self.assertIn("metadata", result)
        self.assertIn("normalized_by", result)

    def test_to_dict_immutability(self):
        """
        GIVEN NormalizedContent instance
        WHEN to_dict() is called multiple times
        THEN expect:
            - Each call returns a new dict instance
            - Modifying returned dict doesn't affect original object
            - Original object attributes remain unchanged
        """
        mock_content = MagicMock(spec=Content)
        mock_content.text = "This is some sample text content"
        mock_content.metadata = {"source": "test_file.txt", "count": 42, "format": "txt"}
        mock_content.to_dict.return_value = {
            "text": mock_content.text,
            "metadata": mock_content.metadata,
            "source_path": "test_file.txt",
            "source_format": "txt"
        }

        norm_content = NormalizedContent(
            content=mock_content,
            normalized_by=["whitespace", "unicode", "linebreaks"]
        )
        result1 = norm_content.to_dict()
        result2 = norm_content.to_dict()
        
        # # Verify they are different objects
        self.assertIsNot(result1, result2)
        
        # Modify the returned dict
        result1["text"] = "modified text"
        result1["metadata"]["new_key"] = "new_value"
        result1["normalized_by"].append("new_normalizer")
        
        # Verify original object is unchanged
        self.assertEqual(norm_content.content.text, mock_content.text)
        self.assertEqual(norm_content.content.metadata, mock_content.metadata)
        self.assertEqual(norm_content.normalized_by, ["whitespace", "unicode", "linebreaks"])
        
        # Verify second dict call is also unchanged
        self.assertEqual(result2["text"], mock_content.text)
        self.assertEqual(result2["metadata"], mock_content.metadata)
        self.assertEqual(result2["normalized_by"], ["whitespace", "unicode", "linebreaks"])

class TestNormalizedContentDataclassBehavior(unittest.TestCase):
    """Test NormalizedContent dataclass-specific behaviors."""

    def setUp(self):
        """Set up test fixtures."""
        self.text = "sample text"
        self.normalized_by = ["normalizer1", "normalizer2"]

        self.mock_content = MagicMock()
        self.mock_content.text = self.text
        self.mock_content.normalized_by = self.normalized_by

    def test_equality_comparison(self):
        """
        GIVEN two NormalizedContent instances with identical attributes
        WHEN compared with == operator
        THEN expect True
        
        GIVEN two NormalizedContent instances with different attributes
        WHEN compared with == operator
        THEN expect False
        """
        content1 = NormalizedContent(
            content=self.mock_content,
            normalized_by=self.normalized_by
        )
        
        content2 = NormalizedContent(
            content=self.mock_content,
            normalized_by=self.normalized_by
        )
        
        # Test equality with identical attributes
        self.assertEqual(content1, content2)
        self.assertTrue(content1 == content2)
        
        # Test inequality with different text
        different_content = MagicMock()
        different_content.text = "different text"

        content3 = NormalizedContent(
            content=different_content,
            normalized_by=self.normalized_by
        )
        self.assertNotEqual(content1, content3)
        self.assertFalse(content1 == content3)

        # Test inequality with different normalized_by
        content5 = NormalizedContent(
            content=self.mock_content,
            normalized_by=["different_normalizer"]
        )
        self.assertNotEqual(content1, content5)

    def test_string_representation(self):
        """
        GIVEN NormalizedContent instance with known attributes
        WHEN str() or repr() is called
        THEN expect string representation includes all attribute values
        """
        mock_content = MagicMock(spec=Content)
        mock_content.to_dict.return_value = {
            "text": "test text",
            "source_path": "test.txt",
            "source_format": "txt"
        }
        content = NormalizedContent(
            content=mock_content,
            normalized_by=["whitespace", "unicode"]
        )

        print(content)
        str_repr = str(content)
        repr_repr = repr(content)

        # Check that all attribute values appear in string representation
        self.assertIn("test text", str_repr)
        self.assertIn("source", str_repr)
        self.assertIn("test.txt", str_repr)
        self.assertIn("whitespace", str_repr)
        self.assertIn("unicode", str_repr)
        
        # Check that all attribute values appear in repr
        self.assertIn("test text", repr_repr)
        self.assertIn("source", repr_repr)
        self.assertIn("test.txt", repr_repr)
        self.assertIn("whitespace", repr_repr)
        self.assertIn("unicode", repr_repr)
        
        # Check that class name appears in repr
        self.assertIn("NormalizedContent", repr_repr)

    def test_attribute_immutability(self):
        """
        GIVEN NormalizedContent instance
        WHEN attempting to modify attributes after initialization
        THEN expect:
            - If frozen=True, expect FrozenInstanceError
            - Attributes of content attribute can be modified, but content attribute itself cannot be modified.
        """
        norm_content = NormalizedContent(
            content=self.mock_content,
            normalized_by=self.normalized_by
        )
        norm_content.content.text = "modified text"
        norm_content.content.metadata = {"modified": "metadata"}

        # Check that attributes of content attribute can be modified
        self.assertEqual(norm_content.content.text, "modified text")
        self.assertEqual(norm_content.content.metadata, {"modified": "metadata"})

        # Try to modify attributes and check if dataclass is frozen
        try:
            # Note the content object isn't frozen, so we can modify it
            norm_content.normalized_by = ["modified_normalizer"]

            # If we get here, the dataclass is not frozen
            self.assertEqual(norm_content.normalized_by, ["modified_normalizer"])
            
        except Exception as e:
            # If an exception is raised, check if it's FrozenInstanceError
            self.assertIsInstance(e, FrozenInstanceError)

            # Verify original values are preserved when frozen
            self.assertEqual(norm_content.normalized_by, self.normalized_by)

        class SomeClass:
            pass

        try:
            norm_content.content = SomeClass

            # If we get here, the dataclass is not frozen
            self.assertIsInstance(norm_content.content, SomeClass)
            
        except Exception as e:
            # If an exception is raised, check if it's FrozenInstanceError
            self.assertIsInstance(e, FrozenInstanceError)

            # Verify original values are preserved
            self.assertEqual(norm_content.content, self.mock_content)

if __name__ == "__main__":
    unittest.main()
