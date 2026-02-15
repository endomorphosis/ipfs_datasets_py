import unittest
from unittest.mock import Mock, MagicMock
from pathlib import Path
import os

# Make sure the input file and documentation file exist.
cwd = os.getcwd()
assert os.path.exists(f'{cwd}/utils/filesystem.py'), "utils/filesystem.py does not exist at the specified directory."
assert os.path.exists(f'{cwd}/utils/filesystem_stubs.md'), "Documentation for utils/filesystem.py does not exist at the specified directory."


from utils.filesystem import FileContent


class TestFileContentInit(unittest.TestCase):
    """Test FileContent initialization and configuration."""

    def setUp(self):
        """Set up test fixtures."""
        pass

    def test_init_with_valid_raw_content_and_defaults(self):
        """
        GIVEN valid raw_content as bytes
        AND default encoding 'utf-8'
        AND default mime_type None
        WHERE:
            - valid_raw_content = b"Hello, World!"
            - custom_encoding = "utf-8" (default)
            - explicit_mime_type = None (default)
        WHEN FileContent is initialized
        THEN expect:
            - Instance created without exceptions
            - as_binary property == b"Hello, World!"
            - encoding attribute == "utf-8"
            - mime_type determined using MIME detection
            - size attribute == 13
            - text_content attribute available for conversion
        """
        valid_raw_content = b"Hello, World!"
        
        file_content = FileContent(valid_raw_content)
        
        self.assertEqual(file_content.as_binary, b"Hello, World!")
        self.assertEqual(file_content.encoding, "utf-8")
        self.assertIsNotNone(file_content.mime_type)
        self.assertEqual(file_content.size, 13)
        self.assertIsInstance(file_content.text_content, str)

    def test_init_with_custom_encoding(self):
        """
        GIVEN valid raw_content as bytes
        AND custom encoding parameter
        AND default mime_type None
        WHERE:
            - valid_raw_content = b"Hello, World!"
            - custom_encoding = "latin-1"
            - explicit_mime_type = None (default)
        WHEN FileContent is initialized
        THEN expect:
            - Instance created without exceptions
            - encoding attribute == "latin-1"
            - text_content uses latin-1 for conversion
        """
        valid_raw_content = b"Hello, World!"
        custom_encoding = "latin-1"
        
        file_content = FileContent(valid_raw_content, encoding=custom_encoding)
        
        self.assertEqual(file_content.encoding, "latin-1")
        # Verify text_content uses the correct encoding
        expected_text = valid_raw_content.decode("latin-1")
        self.assertEqual(file_content.text_content, expected_text)

    def test_init_with_explicit_mime_type(self):
        """
        GIVEN valid raw_content as bytes
        AND default encoding
        AND explicit mime_type parameter
        WHERE:
            - valid_raw_content = b"Hello, World!"
            - custom_encoding = "utf-8" (default)
            - explicit_mime_type = "text/plain"
        WHEN FileContent is initialized
        THEN expect:
            - Instance created without exceptions
            - mime_type attribute == "text/plain"
            - MIME detection bypassed
        """
        valid_raw_content = b"Hello, World!"
        explicit_mime_type = "text/plain"
        
        file_content = FileContent(valid_raw_content, mime_type=explicit_mime_type)
        
        self.assertEqual(file_content.mime_type, "text/plain")

    def test_init_with_empty_raw_content(self):
        """
        GIVEN empty raw_content
        AND default parameters
        WHERE:
            - empty_raw_content = b""
            - custom_encoding = "utf-8" (default)
            - explicit_mime_type = None (default)
        WHEN FileContent is initialized
        THEN expect:
            - Instance created without exceptions
            - size attribute == 0
            - text_content == ""
        """
        empty_raw_content = b""
        
        file_content = FileContent(empty_raw_content)
        
        self.assertEqual(file_content.size, 0)
        self.assertEqual(file_content.text_content, "")

    def test_init_with_invalid_raw_content_type(self):
        """
        GIVEN raw_content that is not bytes (test string, int, None, and list types)
        WHERE:
            - invalid_types = ["string", 123, None, [1, 2, 3]]
        WHEN FileContent is initialized with each invalid type
        THEN expect TypeError to be raised for each case
        """
        invalid_types = ["string", 123, None, [1, 2, 3]]
        
        for invalid_content in invalid_types:
            with self.subTest(invalid_content=invalid_content):
                with self.assertRaises(TypeError):
                    FileContent(invalid_content)

    def test_init_with_invalid_encoding(self):
        """
        GIVEN valid raw_content
        AND invalid encoding name
        WHERE:
            - valid_raw_content = b"Hello, World!"
            - invalid_encoding = "nonexistent-encoding"
        WHEN FileContent is initialized
        THEN expect LookupError to be raised
        """
        valid_raw_content = b"Hello, World!"
        invalid_encoding = "nonexistent-encoding"
        
        with self.assertRaises(LookupError):
            FileContent(valid_raw_content, encoding=invalid_encoding)

class TestFileContentAsBinary(unittest.TestCase):
    """Test FileContent.as_binary property."""

    def setUp(self):
        """Set up test fixtures."""
        pass

    def test_as_binary_returns_original_raw_content(self):
        """
        GIVEN FileContent instance initialized with specific raw_content bytes
        WHERE:
            - specific_raw_content = b"test content for binary access"
        WHEN as_binary property is accessed
        THEN expect:
            - Returned value is specific_raw_content using `is` operator
            - Returned value type == bytes
            - No modification or copying of the original content
        """
        specific_raw_content = b"test content for binary access"
        
        file_content = FileContent(specific_raw_content)
        binary_result = file_content.as_binary
        
        self.assertIs(binary_result, specific_raw_content)
        self.assertIsInstance(binary_result, bytes)

    def test_as_binary_with_empty_content(self):
        """
        GIVEN FileContent instance initialized with empty raw_content
        WHERE:
            - empty_content = b""
        WHEN as_binary property is accessed
        THEN expect:
            - Returned value == b""
            - Type == bytes
        """
        empty_content = b""
        
        file_content = FileContent(empty_content)
        binary_result = file_content.as_binary
        
        self.assertEqual(binary_result, b"")
        self.assertIsInstance(binary_result, bytes)

    def test_as_binary_with_large_content(self):
        """
        GIVEN FileContent instance initialized with large raw_content (5MB)
        WHERE:
            - large_content = b"x" * (5 * 1024 * 1024)  # 5MB
        WHEN as_binary property is accessed multiple times
        THEN expect:
            - Each access returns the same content using `==`
            - Each access returns the same object reference using `is`
            - Multiple accesses complete without memory leaks
        """
        large_content = b"x" * (5 * 1024 * 1024)  # 5MB
        
        file_content = FileContent(large_content)
        
        # First access
        binary_result1 = file_content.as_binary
        # Second access
        binary_result2 = file_content.as_binary
        # Third access
        binary_result3 = file_content.as_binary
        
        # Content equality check
        self.assertEqual(binary_result1, large_content)
        self.assertEqual(binary_result2, large_content)
        self.assertEqual(binary_result3, large_content)
        
        # Object reference check
        self.assertIs(binary_result1, binary_result2)
        self.assertIs(binary_result2, binary_result3)
        self.assertIs(binary_result1, large_content)

    def test_as_binary_immutability(self):
        """
        GIVEN FileContent instance with raw_content
        WHERE:
            - specific_raw_content = b"test content for binary access"
        WHEN as_binary property is accessed and attempts are made to modify via slicing
        THEN expect:
            - Original raw_content in FileContent remains unchanged
            - Subsequent calls to as_binary return original content
        """
        specific_raw_content = b"test content for binary access"
        
        file_content = FileContent(specific_raw_content)
        binary_result = file_content.as_binary
        
        # Attempt to create a modified version (this doesn't modify the original bytes object)
        modified_binary = binary_result[5:] + b" modified"
        
        # Verify original content is unchanged
        self.assertEqual(file_content.as_binary, specific_raw_content)
        self.assertNotEqual(file_content.as_binary, modified_binary)
        
        # Verify subsequent calls return original content
        subsequent_result = file_content.as_binary
        self.assertEqual(subsequent_result, specific_raw_content)
        self.assertIs(subsequent_result, specific_raw_content)

class TestFileContentGetAsText(unittest.TestCase):
    """Test FileContent.get_as_text method."""

    def setUp(self):
        """Set up test fixtures."""
        pass

    def test_get_as_text_with_default_encoding(self):
        """
        GIVEN FileContent instance initialized with UTF-8 text bytes
        AND no encoding parameter provided to get_as_text
        WHERE:
            - utf8_text_bytes = "Hello, 世界".encode('utf-8')
            - default_encoding = None
        WHEN get_as_text is called
        THEN expect:
            - Returned string == "Hello, 世界"
            - Uses the instance's default encoding
            - No encoding errors occur
        """
        utf8_text_bytes = "Hello, 世界".encode('utf-8')
        
        file_content = FileContent(utf8_text_bytes)
        result = file_content.get_as_text()
        
        self.assertEqual(result, "Hello, 世界")
        self.assertIsInstance(result, str)

    def test_get_as_text_with_custom_encoding(self):
        """
        GIVEN FileContent instance with text bytes in specific encoding
        AND custom encoding parameter provided to get_as_text
        WHERE:
            - latin1_text_bytes = "café".encode('latin-1')
            - custom_encoding = "latin-1"
        WHEN get_as_text is called with that encoding
        THEN expect:
            - Text decoded using latin-1
            - Returned string == "café"
            - Instance's default encoding unchanged
        """
        latin1_text_bytes = "café".encode('latin-1')
        custom_encoding = "latin-1"
        
        file_content = FileContent(latin1_text_bytes, encoding="utf-8")  # Different default encoding
        result = file_content.get_as_text(encoding=custom_encoding)
        
        self.assertEqual(result, "café")
        self.assertEqual(file_content.encoding, "utf-8")  # Verify default encoding unchanged

    def test_get_as_text_with_invalid_encoding(self):
        """
        GIVEN FileContent instance with valid raw_content
        AND invalid encoding name parameter
        WHERE:
            - utf8_text_bytes = "Hello, 世界".encode('utf-8')
            - invalid_encoding = "nonexistent-encoding-name"
        WHEN get_as_text is called with invalid encoding name
        THEN expect LookupError to be raised
        """
        utf8_text_bytes = "Hello, 世界".encode('utf-8')
        invalid_encoding = "nonexistent-encoding-name"
        
        file_content = FileContent(utf8_text_bytes)
        
        with self.assertRaises(LookupError):
            file_content.get_as_text(encoding=invalid_encoding)

    def test_get_as_text_with_binary_content_utf8_encoding(self):
        """
        GIVEN FileContent instance with non-text binary content
        AND UTF-8 encoding specified
        WHERE:
            - binary_content = b"\x89PNG\r\n\x1a\n"
            - custom_encoding = "utf-32"
        WHEN get_as_text is called
        THEN expect ValueError to be raised
        """
        binary_content = b"\x89PNG\r\n\x1a\n"
        custom_encoding = "utf-32"
        
        file_content = FileContent(binary_content)

        with self.assertRaises(ValueError):
            file_content.get_as_text(encoding=custom_encoding)

    def test_get_as_text_with_empty_content(self):
        """
        GIVEN FileContent instance with empty raw_content
        WHERE:
            - empty_content = b""
        WHEN get_as_text is called
        THEN expect:
            - Empty string "" returned
            - No exceptions raised
        """
        empty_content = b""
        
        file_content = FileContent(empty_content)
        result = file_content.get_as_text()
        
        self.assertEqual(result, "")
        self.assertIsInstance(result, str)

    def test_get_as_text_multiple_calls_consistency(self):
        """
        GIVEN FileContent instance with text content
        WHERE:
            - utf8_text_bytes = "Hello, 世界".encode('utf-8')
            - custom_encoding = "utf-8"
        WHEN get_as_text is called multiple times with same encoding
        THEN expect:
            - All calls return identical strings (using ==)
            - No state changes between calls
            - Each call returns the same object reference (using is)
        """
        utf8_text_bytes = "Hello, 世界".encode('utf-8')
        custom_encoding = "utf-8"
        
        file_content = FileContent(utf8_text_bytes)
        
        result1 = file_content.get_as_text(encoding=custom_encoding)
        result2 = file_content.get_as_text(encoding=custom_encoding)
        result3 = file_content.get_as_text(encoding=custom_encoding)
        
        # Content equality
        self.assertEqual(result1, result2)
        self.assertEqual(result2, result3)
        self.assertEqual(result1, "Hello, 世界")
        
        # Object reference equality (strings with same content may be interned)
        self.assertIs(result1, result2)
        self.assertIs(result2, result3)

    def test_get_as_text_none_encoding_uses_default(self):
        """
        GIVEN FileContent instance with specific default encoding
        AND None passed as encoding parameter
        WHERE:
            - utf8_text_bytes = "Hello, 世界".encode('utf-8')
            - none_encoding = None
        WHEN get_as_text is called
        THEN expect:
            - Instance's default encoding is used
            - Same result as calling without encoding parameter
        """
        utf8_text_bytes = "Hello, 世界".encode('utf-8')
        none_encoding = None
        
        file_content = FileContent(utf8_text_bytes)
        
        result_with_none = file_content.get_as_text(encoding=none_encoding)
        result_without_param = file_content.get_as_text()
        
        self.assertEqual(result_with_none, result_without_param)
        self.assertEqual(result_with_none, "Hello, 世界")

if __name__ == '__main__':
    unittest.main()