import unittest
import json
import threading
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import copy
from pprint import pprint
import tempfile
import os


from configs import Configs, _Output
from types_ import Logger


from core.output_formatter._output_formatter import OutputFormatter
from core.output_formatter._formatted_output import FormattedOutput
from core.text_normalizer._normalized_content import NormalizedContent
from core.content_extractor._content import Content


def make_mock_resources() -> dict[str, MagicMock]:
    """
    Create mock resources for OutputFormatter testing.
    
    Returns:
        Dictionary containing mocked dependencies.
    """
    def _make_mock():
        mock_logger = MagicMock(spec=Logger)
        mock_formatted_output = MagicMock(spec=FormattedOutput)
        mock_normalized_content = MagicMock(spec=NormalizedContent)
        return {
            "normalized_content": mock_normalized_content,
            "formatted_output": mock_formatted_output,
            "logger": mock_logger,
        }
    output = _make_mock()
    return copy.copy(output)

def make_mock_configs() -> MagicMock:
    """
    Create mock configuration object for OutputFormatter testing.
    
    Returns:
        Mocked Configs object with necessary attributes.
    """
    def _make_mock():
        mock_configs = MagicMock()
        mock_configs.output = MagicMock()
        mock_configs.output.default_format = 'txt'
        return mock_configs
    output = _make_mock()
    return copy.copy(output)


def make_mock_content() -> MagicMock:
    """
    Create mock Content object for testing.
    
    Returns:
        Mocked Content object with sample data.
    """
    def _make_mock():
        mock_content = MagicMock(spec=Content)
        mock_content.text = "Sample content text for testing"
        mock_content.metadata = {
            "title": "Test Document",
            "author": "Test Author", 
            "created_at": "2023-01-01T12:00:00",
            "tags": ["test", "sample"],
            "word_count": 6
        }
        mock_content.sections = [
            {"title": "Introduction", "content": "Intro content"},
            {"title": "Body", "content": "Main body content"}
        ]
        mock_content.source_path = "test_document.txt"
        mock_content.source_format = "text/plain"
        mock_content.extraction_time = datetime.now().isoformat()
        # Mock the to_dict method to return a dictionary representation
        mock_content.to_dict.return_value = {
            "text": mock_content.text,
            "metadata": mock_content.metadata,
            "source_path": mock_content.source_path,
            "source_format": mock_content.source_format,
            "sections": mock_content.sections,
            "extraction_time": mock_content.extraction_time
        }
        return mock_content
    output = _make_mock()
    return copy.copy(output)

def make_mock_normalized_content(mock_content: MagicMock = None) -> MagicMock:
    def _make_mock(mock_content=None):
        mock_normalized_content = MagicMock(spec=NormalizedContent)
        mock_normalized_content.content = mock_content or make_mock_content()
        mock_normalized_content.normalized_by = ["newlines", "whitespace"]
        return mock_normalized_content
    output = _make_mock(mock_content)
    return copy.copy(output)

def make_sample_content_variations() -> list[MagicMock]:
    """
    Create various Content objects for comprehensive testing.
    
    Returns:
        List of different Content mock objects for edge case testing.
    """
    def _make_mocks():
        variations = []
 
        # Empty content
        empty_content = MagicMock(spec=Content)
        empty_content.text = ""
        empty_content.metadata = {}
        empty_content.source_path = ""
        empty_content.source_format = ""
        empty_content.sections = []
        empty_content.extraction_time = datetime.now().isoformat()
        empty_content.to_dict.return_value = {
            "text": empty_content.text,
            "metadata": empty_content.metadata,
            "source_path": empty_content.source_path,
            "source_format": empty_content.source_format,
            "sections": empty_content.sections,
            "extraction_time": empty_content.extraction_time
        }
        variations.append(empty_content)

        # Rich content with complex metadata
        rich_content = MagicMock(spec=Content)
        rich_content.text = "Rich content with extensive metadata"
        rich_content.metadata = {
            "title": "Complex Document",
            "author": {"name": "John Doe", "email": "john@example.com"},
            "tags": ["complex", "metadata", "nested"],
            "statistics": {"words": 100, "characters": 500},
            "nested": {"level1": {"level2": "deep value"}}
        }
        rich_content.source_path = "complex_doc.docx"
        rich_content.source_format = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        rich_content.sections = []
        rich_content.extraction_time = datetime.now().isoformat()
        rich_content.to_dict.return_value = {
            "text": rich_content.text,
            "metadata": rich_content.metadata,
            "source_path": rich_content.source_path,
            "source_format": rich_content.source_format,
            "sections": rich_content.sections,
            "extraction_time": rich_content.extraction_time
        }
        variations.append(rich_content)
        
        # Content with special characters
        special_content = MagicMock(spec=Content)
        special_content.text = "Special chars: 🌍 测试 \t\n\"quotes\" and 'apostrophes'"
        special_content.metadata = {"title": "Special Characters Test"}
        special_content.source_path = "special_chars.pdf"
        special_content.source_format = "application/pdf"
        special_content.sections = [{"title": "Special Section", "content": "Content with special characters"}]
        special_content.extraction_time = datetime.now().isoformat()
        special_content.to_dict.return_value = {
            "text": special_content.text,
            "metadata": special_content.metadata,
            "source_path": special_content.source_path,
            "source_format": special_content.source_format,
            "sections": special_content.sections,
            "extraction_time": special_content.extraction_time
        }
        variations.append(special_content)
        
        # Large content
        large_content = MagicMock(spec=Content)
        large_content.text = "Large content " * 1000  # Repeated text
        large_content.metadata = {"title": "Large Document", "size": "large"}
        large_content.source_path = "large_document.pdf"
        large_content.source_format = "application/pdf"
        large_content.sections = [{"title": "Large Section", "content": "This section contains a lot of text." * 1000}]
        large_content.extraction_time = datetime.now().isoformat()
        large_content.to_dict.return_value = {
            "text": large_content.text,
            "metadata": large_content.metadata,
            "source_path": large_content.source_path,
            "source_format": large_content.source_format,
            "sections": large_content.sections,
            "extraction_time": large_content.extraction_time
        }
        variations.append(large_content)
        
        # Content with None values
        none_content = MagicMock(spec=Content)
        none_content.text = "Content with None metadata"
        none_content.metadata = {"title": None, "author": None}
        none_content.source_path = None
        none_content.source_format = None
        none_content.sections = None
        none_content.extraction_time = datetime.now().isoformat()
        none_content.to_dict.return_value = {
            "text": none_content.text,
            "metadata": none_content.metadata,
            "source_path": none_content.source_path,
            "source_format": none_content.source_format,
            "sections": none_content.sections,
            "extraction_time": none_content.extraction_time
        }
        variations.append(none_content)
        return variations
    output = _make_mocks()
    return copy.copy(output)


def make_sample_normalized_content_variations():
    def _make_mocks():
        various_content = make_sample_content_variations()
        various_normalized_contents = [make_mock_normalized_content(cont) for cont in various_content]
        return various_normalized_contents
    output = _make_mocks()
    return copy.copy(output)


def create_test_formatter_function(format_name: str):
    """Create a test formatter function for registration testing.
    
    Args:
        format_name: Name to include in the formatter output
        
    Returns:
        Formatter function that can be registered
    """
    def test_formatter(content: Content) -> str:
        return f"{format_name.upper()}: {content.text[:50]}..."
    
    test_formatter.__name__ = f"_format_as_{format_name}"
    return test_formatter


def assert_valid_json(test_case: unittest.TestCase, json_string: str):
    """
    Helper to assert that a string is valid JSON.
    
    Args:
        test_case: The test case instance for assertions
        json_string: String to validate as JSON
    """
    import json
    
    try:
        parsed = json.loads(json_string)
        test_case.assertIsInstance(parsed, (dict, list))
        return parsed
    except json.JSONDecodeError as e:
        test_case.fail(f"Invalid JSON: {e}")


def assert_valid_markdown(test_case: unittest.TestCase, markdown_string: str):
    """
    Helper to assert basic markdown validity.
    
    Args:
        test_case: The test case instance for assertions  
        markdown_string: String to validate as markdown
    """
    test_case.assertIsInstance(markdown_string, str)
    test_case.assertGreater(len(markdown_string), 0)
    
    # Basic markdown checks
    lines = markdown_string.split('\n')
    test_case.assertGreater(len(lines), 0)
    
    # Should have some structure (headers, content, etc.)
    has_structure = any(
        line.startswith('#') or 
        line.startswith('*') or 
        line.startswith('-') or
        '**' in line or
        '__' in line
        for line in lines
    )
    
    # Note: Not all markdown needs special formatting, so we don't require it
    # but if present, it should be reasonable
    return True


def setup_formatter_with_mocks() -> tuple[OutputFormatter, dict]:
    """
    Create an OutputFormatter with all mocked dependencies.
    
    Returns:
        Tuple of (formatter_instance, mocks_dict) for testing
    """
    mocks = {
        'logger': Mock(),
        'configs': make_mock_configs(),
        'resources': make_mock_resources(),
        'content': make_mock_content()
    }
    
    formatter = OutputFormatter(
        resources=mocks['resources'],
        configs=mocks['configs']
    )
    
    return formatter, mocks


class TestOutputFormatterInitialization(unittest.TestCase):
    """Test OutputFormatter initialization and configuration."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_configs = make_mock_configs()
        self.mock_resources = make_mock_resources()

        self.formatter = OutputFormatter(
            resources=self.mock_resources,
            configs=self.mock_configs
        )

    def test_init_with_valid_resources_and_configs(self):
        """
        GIVEN valid resources dict containing:
            - normalized_content: NormalizedContent class
            - formatted_output: FormattedOutput class
            - logger: A logger instance
        AND valid configs object with necessary configuration settings
        WHEN OutputFormatter is initialized
        THEN expect:
            - Instance created successfully
            - resources attribute is set correctly
            - configs attribute is set correctly
            - output_formats dict is initialized with default formatters
            - default_format is set to 'txt'
            - Default formatters are registered (_format_as_txt, _format_as_json, _format_as_markdown)
        """
        # When
        formatter = OutputFormatter(resources=self.mock_resources, configs=self.mock_configs)
        
        # Then
        self.assertIsInstance(formatter, OutputFormatter)
        self.assertEqual(formatter.resources, self.mock_resources)
        self.assertEqual(formatter.configs, self.mock_configs)
        self.assertIsInstance(formatter.output_formats, dict)

        format = formatter.default_format
        self.assertEqual(format, 'txt')
        
        # Check default formatters are registered
        expected_formats = {'txt', 'json', 'md'}
        self.assertEqual(set(formatter.output_formats.keys()), expected_formats)
        
        # Check formatters are callable
        for format_name in expected_formats:
            self.assertTrue(callable(formatter.output_formats[format_name]))

    def test_init_with_none_resources(self):
        """
        GIVEN resources=None
        WHEN OutputFormatter is initialized
        THEN expect:
            - TypeError to be raised
        """
        with self.assertRaises(TypeError):
            formatter = OutputFormatter(resources=None, configs=self.mock_configs)

    def test_init_with_none_configs(self):
        """
        GIVEN configs=None
        WHEN OutputFormatter is initialized
        THEN expect:
            - AttributeError to be raised
        """
        # When
        with self.assertRaises(AttributeError):
            formatter = OutputFormatter(resources=self.mock_resources, configs=None)

    def test_init_state_after_successful_initialization(self):
        """
        GIVEN valid resources and configs
        WHEN OutputFormatter is initialized
        THEN expect:
            - self.resources is the same dict passed in
            - self.configs is the same object passed in
            - self.output_formats contains 'txt', 'json', and 'md' keys
            - self.default_format == 'txt'
            - available_formats property returns ['txt', 'json', 'md']
        """
        # When
        formatter = OutputFormatter(resources=self.mock_resources, configs=self.mock_configs)
        
        # Then
        self.assertIs(formatter.resources, self.mock_resources)
        self.assertIs(formatter.configs, self.mock_configs)
        
        expected_formats = {'txt', 'json', 'md'}
        self.assertEqual(set(formatter.output_formats.keys()), expected_formats)
        self.assertEqual(formatter.default_format, 'txt')
        
        available = formatter.available_formats
        self.assertEqual(set(available), expected_formats)
        self.assertIsInstance(available, list)


class TestDefaultFormattersRegistration(unittest.TestCase):
    """Test default formatter registration functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_configs = make_mock_configs()
        self.mock_resources = make_mock_resources()

        self.formatter = OutputFormatter(
            resources=self.mock_resources,
            configs=self.mock_configs
        )

    def test_register_default_formatters_creates_txt_formatter(self):
        """
        GIVEN an OutputFormatter instance
        WHEN _register_default_formatters is called
        THEN expect:
            - 'txt' key exists in output_formats
            - output_formats['txt'] is callable
            - output_formats['txt'] is bound to self._format_as_txt
        """
        # Given
        formatter = OutputFormatter(resources=self.mock_resources, configs=self.mock_configs)
        
        # When - already called during init, but verify state
        # Then
        self.assertIn('txt', formatter.output_formats)
        self.assertTrue(callable(formatter.output_formats['txt']))
        
        # Verify it's bound to the correct method
        self.assertEqual(formatter.output_formats['txt'].__name__, '_format_as_txt')

    def test_register_default_formatters_creates_json_formatter(self):
        """
        GIVEN an OutputFormatter instance
        WHEN _register_default_formatters is called
        THEN expect:
            - 'json' key exists in output_formats
            - output_formats['json'] is callable
            - output_formats['json'] is bound to self._format_as_json
        """
        # Given
        formatter = OutputFormatter(resources=self.mock_resources, configs=self.mock_configs)
        
        # When - already called during init, but verify state
        # Then
        self.assertIn('json', formatter.output_formats)
        self.assertTrue(callable(formatter.output_formats['json']))
        
        # Verify it's bound to the correct method
        self.assertEqual(formatter.output_formats['json'].__name__, '_format_as_json')

    def test_register_default_formatters_creates_markdown_formatter(self):
        """
        GIVEN an OutputFormatter instance
        WHEN _register_default_formatters is called
        THEN expect:
            - 'md' key exists in output_formats
            - output_formats['md'] is callable
            - output_formats['md'] is bound to self._format_as_markdown
        """
        # Given
        formatter = OutputFormatter(resources=self.mock_resources, configs=self.mock_configs)
        
        # When - already called during init, but verify state
        # Then
        self.assertIn('md', formatter.output_formats)
        self.assertTrue(callable(formatter.output_formats['md']))
        
        # Verify it's bound to the correct method
        self.assertEqual(formatter.output_formats['md'].__name__, '_format_as_markdown')

    def test_register_default_formatters_called_during_init(self):
        """
        GIVEN OutputFormatter class
        WHEN instance is created
        THEN expect:
            - _register_default_formatters is called automatically
            - All default formatters are available immediately after init
        """
        # When
        with patch.object(OutputFormatter, '_register_default_formatters') as mock_register:
            formatter = OutputFormatter(resources=self.mock_resources, configs=self.mock_configs)
            
            # Then
            mock_register.assert_called_once()
            
        # Verify the method actually sets up the formatters when not mocked
        formatter_real = OutputFormatter(resources=self.mock_resources, configs=self.mock_configs)
        print(formatter_real.output_formats.keys())
        expected_formats = {'txt', 'json', 'md'}
        self.assertEqual(set(formatter_real.output_formats.keys()), expected_formats)


class TestTxtFormatter(unittest.TestCase):
    """Test plain text formatting functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_configs = make_mock_configs()
        self.mock_resources = make_mock_resources()

        self.formatter = OutputFormatter(
            resources=self.mock_resources,
            configs=self.mock_configs
        )
        self.mock_normalized_content = make_mock_normalized_content()
        self.output_dict = self.mock_normalized_content.content.to_dict()
        self.output_dict['normalized_by'] = self.mock_normalized_content.normalized_by


    def test_format_as_txt_with_simple_content(self):
        """
        GIVEN a dictionary with text="Hello World"
        WHEN _format_as_txt is called
        THEN expect:
            - Has "Hello World" as plain text string
            - Has source path in the output
            - No additional information or formatting
        """
        # Given
        self.output_dict['text'] = "Hello World"
        # Set all other keys to None.
        self.output_dict['metadata'] = None
        self.output_dict['source_format'] = None
        self.output_dict['sections'] = None
        self.output_dict['normalized_by'] = None

        # When
        result = self.formatter._format_as_txt(self.output_dict)
    
        # Then
        self.assertIsInstance(result, str)
        self.assertIn("Hello World", result)
        self.assertIn("Source path: test_document.txt", result)

    def test_format_as_txt_with_multiline_content(self):
        """
        GIVEN a dictionary with text containing multiple lines
        WHEN _format_as_txt is called
        THEN expect:
            - Returns text preserving line breaks
            - No modification to whitespace
        """
        # Given
        multiline_text = "Line 1\nLine 2\n\nLine 4"
        self.output_dict['text'] = multiline_text
        # Set all other keys to None.
        self.output_dict['metadata'] = None
        self.output_dict['source_format'] = None
        self.output_dict['sections'] = None
        self.output_dict['normalized_by'] = None

        # When
        result = self.formatter._format_as_txt(self.output_dict)
        
        # Then
        self.assertIn(multiline_text, result)
        self.assertIn('\n', result)

    def test_format_as_txt_with_empty_content(self):
        """
        GIVEN a dictionary with empty text=""
        WHEN _format_as_txt is called
        THEN expect:
            - Returns empty string ""
            - No errors raised
        """
        # Given
        self.output_dict['text'] = ""
        
        # When
        result = self.formatter._format_as_txt(self.output_dict)
        
        # Then
        self.assertEqual(result, "")
        self.assertIsInstance(result, str)

    def test_format_as_txt_with_none_text_attribute(self):
        """
        GIVEN a dictionary with text=None
        WHEN _format_as_txt is called
        THEN expect:
            - Handles gracefully (returns empty string or raises appropriate error)
        """
        # Given
        self.output_dict['text'] = None
        
        # When/Then
        try:
            result = self.formatter._format_as_txt(self.output_dict)
            # If it doesn't raise an error, it should return something sensible
            self.assertIn(result, ["", "None", str(None)])
        except (TypeError, AttributeError) as e:
            # This is also acceptable behavior
            self.assertIsInstance(e, (TypeError, AttributeError))

    def test_format_as_txt_with_special_characters(self):
        """
        GIVEN a dictionary with text containing special characters (tabs, unicode, etc.)
        WHEN _format_as_txt is called
        THEN expect:
            - Returns text with special characters preserved
            - No encoding errors
        """
        # Given
        special_text = "Hello\tWorld\n🌍 Unicode 测试 \u2603"
        
        self.output_dict['text'] = special_text
        
        # When
        result = self.formatter._format_as_txt(self.output_dict)
        
        # Then
        self.assertIn(special_text, result)
        self.assertIn('\t', result)
        self.assertIn('🌍', result)
        self.assertIn('测试', result)
        self.assertIn('\u2603', result)




class TestJsonFormatter(unittest.TestCase):
    """Test JSON formatting functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_configs = make_mock_configs()
        self.mock_resources = make_mock_resources()

        self.formatter = OutputFormatter(
            resources=self.mock_resources,
            configs=self.mock_configs
        )
        self.mock_normalized_content = make_mock_normalized_content()
        self.output_dict = self.mock_normalized_content.content.to_dict()
        self.output_dict['normalized_by'] = self.mock_normalized_content.normalized_by

    def test_format_as_json_with_simple_content(self):
        """
        GIVEN a dictionary with basic attributes
        WHEN _format_as_json is called
        THEN expect:
            - Returns valid JSON string
            - JSON contains content attributes
            - JSON is properly formatted with indentation
        """
        # When
        result = self.formatter._format_as_json(self.output_dict )
        
        # Then
        self.assertIsInstance(result, str)
        
        # Verify it's valid JSON
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)
        
        # Check that it contains expected content
        self.assertIn("text", parsed)
        self.assertEqual(parsed["text"], "Sample content text for testing")

    def test_format_as_json_with_complex_content(self):
        """
        GIVEN a dictionary with nested data structures
        WHEN _format_as_json is called
        THEN expect:
            - Returns valid JSON string
            - All nested structures are properly serialized
            - No circular reference errors
        """
        # Given
        self.output_dict['text'] = "Complex content"
        self.output_dict['metadata'] = {
            "title": "Test",
            "nested": {
                "level1": {
                    "level2": ["item1", "item2"]
                }
            },
            "list": [1, 2, {"key": "value"}]
        }
        # When
        result = self.formatter._format_as_json(self.output_dict)
        
        # Then
        self.assertIsInstance(result, str)

        # Verify it's valid JSON
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)
        
        # Verify nested structures are preserved
        if "metadata" in parsed:
            self.assertIn("nested", parsed["metadata"])
            self.assertIn("list", parsed["metadata"])

    def test_format_as_json_with_datetime_attributes(self):
        """
        GIVEN a dictionary containing datetime objects
        WHEN _format_as_json is called
        THEN expect:
            - Datetime objects are serialized to ISO format strings
            - JSON remains valid
        """
        # Given
        test_datetime = datetime(2023, 1, 1, 12, 0, 0)
        self.output_dict['text'] = "DateTime test"
        self.output_dict['extraction_time'] = test_datetime.isoformat() # NOTE This is already done in the Content class
        self.output_dict['metadata'] = {"timestamp": test_datetime}

        # When
        result = self.formatter._format_as_json(self.output_dict)
        
        # Then
        self.assertIsInstance(result, str)
        
        # Verify it's valid JSON (datetime should be serialized)
        try:
            parsed = json.loads(result)
            self.assertIsInstance(parsed, dict)
        except json.JSONDecodeError:
            self.fail("JSON should be valid even with datetime objects")


    def test_format_as_json_encoding_special_characters(self):
        """
        GIVEN a dictionary with special characters (quotes, backslashes, unicode)
        WHEN _format_as_json is called
        THEN expect:
            - Special characters are properly escaped
            - JSON remains valid and parseable
        """
        # Given
        special_text = 'Text with "quotes" and \\backslashes\\ and unicode: 🌍'
        self.output_dict['text'] = special_text
        self.output_dict['metadata'] = {"title": 'Title with "quotes"'}

        # When
        result = self.formatter._format_as_json(self.output_dict)
        
        # Then
        self.assertIsInstance(result, str)
        
        # Verify it's valid JSON
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)
        
        # Verify special characters are preserved after parsing
        if "text" in parsed:
            print(parsed["text"])
            self.assertIn('"', parsed["text"])
            self.assertIn('\\', parsed["text"])
            self.assertIn('🌍', parsed["text"])


class TestMarkdownFormatter(unittest.TestCase):
    """Test Markdown formatting functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_configs = make_mock_configs()
        self.mock_resources = make_mock_resources()

        self.formatter = OutputFormatter(
            resources=self.mock_resources,
            configs=self.mock_configs
        )
        self.mock_normalized_content = make_mock_normalized_content()
        self.output_dict = self.mock_normalized_content.content.to_dict()
        self.output_dict['normalized_by'] = self.mock_normalized_content.normalized_by

    def test_format_as_markdown_with_simple_content(self):
        """
        GIVEN a dictionary with plain text
        WHEN _format_as_markdown is called
        THEN expect:
            - Returns Markdown-formatted string
            - Includes appropriate headers
            - Content is properly formatted
        """
        # When
        result = self.formatter._format_as_markdown(self.output_dict)
        
        # Then
        self.assertIsInstance(result, str)
        self.assertIn("Sample content text for testing", result)
        
        # Should contain some markdown formatting
        # (exact format depends on implementation, but should have structure)
        # TODO - this is a bit vague, need to define what we expect
        self.assertTrue(len(result) >= len(self.output_dict['text']))

        # Check for '# Content from' in in result, since that's always added
        self.assertIn('# Content from', result)

    def test_format_as_markdown_with_metadata(self):
        """
        GIVEN a dictionary with metadata (title, author, date, etc.)
        WHEN _format_as_markdown is called
        THEN expect:
            - Metadata is formatted as Markdown headers/sections
            - Proper Markdown syntax used
        """
        # Given
        self.output_dict['text'] = "Content with metadata"
        self.output_dict['metadata'] = {
            "title": "Test Document",
            "author": "Test Author",
            "date": "2023-01-01",
            "description": "A test document"
        }

        # When
        result = self.formatter._format_as_markdown(self.output_dict)

        # Then
        self.assertIsInstance(result, str)
        
        # Should include metadata in some form
        self.assertIn("Test Document", result)
        self.assertIn("Content with metadata", result)
        
        # Should have markdown structure (headers, etc.)
        self.assertTrue(any(line.startswith('#') for line in result.split('\n')) or 
                       'title' in result.lower() or 
                       'author' in result.lower())

    def test_format_as_markdown_with_sections(self):
        """
        GIVEN a dictionary with multiple sections/chapters
        WHEN _format_as_markdown is called
        THEN expect:
            - Each section has appropriate heading level
            - Sections are properly separated
            - Table of contents generated if applicable
        """
        # Given
        self.output_dict['text']= "Chapter 1: Introduction\n\nChapter 2: Main Content"
        self.output_dict['sections'] = [
            {"title": "Introduction", "content": "Intro content"},
            {"title": "Main Content", "content": "Main content here"}
        ]
        self.output_dict['metadata'] = {"title": "Multi-Section Document"}
        
        # When
        result = self.formatter._format_as_markdown(self.output_dict)
        
        # Then
        self.assertIsInstance(result, str)
        self.assertIn("Introduction", result)
        self.assertIn("Main Content", result)
        
        # Should have some structure for sections
        lines = result.split('\n')
        self.assertTrue(len(lines) > 1)

    def test_format_as_markdown_with_lists_and_formatting(self):
        """
        TODO Figure out how to really test this. Transforming something into text already strips out formatting.
        GIVEN a dictionary containing lists, bold, italic text
        WHEN _format_as_markdown is called
        THEN expect:
            - Lists are formatted with proper Markdown syntax
            - Text formatting is preserved or converted
        """
        # Given
        
        self.output_dict['text'] = "Bold text and italic text with a list:\n- Item 1\n- Item 2"
        self.output_dict['metadata'] = {"title": "Formatted Content"}
        
        # When
        result = self.formatter._format_as_markdown(self.output_dict)
        
        # Then
        self.assertIsInstance(result, str)
        self.assertIn("Item 1", result)
        self.assertIn("Item 2", result)
        
        # Should preserve or enhance markdown formatting
        self.assertTrue(len(result) >= len(self.output_dict['text']))

    def test_format_as_markdown_escaping_special_characters(self):
        """
        GIVEN a dictionary with Markdown special characters (*, _, #, etc.)
        WHEN _format_as_markdown is called
        THEN expect:
            - Special characters are properly escaped
            - Markdown remains valid
        """
        # Given
        special_text = "Text with *asterisks* and _underscores_ and #hashtags"
        
        self.output_dict['text'] = special_text
        self.output_dict['metadata'] = {"title": "Special #Characters"}
        
        # When
        result = self.formatter._format_as_markdown(self.output_dict)
        
        # Then
        self.assertIsInstance(result, str)
        
        # Should contain the special characters in some form
        # (either escaped or as part of formatting)
        self.assertIn("asterisks", result)
        self.assertIn("underscores", result)
        self.assertIn("hashtags", result)
        
        # Should be valid markdown (no unmatched formatting)
        # This is a basic check - in practice, you'd want more sophisticated validation
        self.assertTrue(len(result) > 0)


class TestFormatOutput(unittest.TestCase):
    """Test main format_output method functionality."""

    def setUp(self):
        """Set up test fixtures."""

        self.mock_configs = make_mock_configs()
        self.mock_resources = make_mock_resources()
        self.formatter = OutputFormatter(resources=self.mock_resources, configs=self.mock_configs)

        self.mock_content = make_mock_content()
        self.mock_normalized_content = make_mock_normalized_content(self.mock_content)

    def test_format_output_with_default_format(self):
        """
        GIVEN an OutputFormatter with default_format='txt'
        WHEN format_output is called with format=None
        THEN expect:
            - Uses default format (txt)
            - Returns FormattedOutput instance
            - FormattedOutput.format == 'txt'
            - FormattedOutput.content contains formatted text
        """
        # When
        result = self.formatter.format_output(self.mock_normalized_content, format=None)

        # Then TODO Figure out how to do proper instance checking with mocks.
        #self.assertEqual(result, self.formatter._formatted_output)
        self.formatter._formatted_output.assert_called_once()

        # Verify the call was made with correct parameters
        call_args = self.formatter._formatted_output.call_args
        self.assertIsNotNone(call_args)

    def test_format_output_with_specified_format(self):
        """
        GIVEN an OutputFormatter
        WHEN format_output is called with format='json'
        THEN expect:
            - Uses specified format
            - Returns FormattedOutput instance
            - FormattedOutput.format == 'json'
            - FormattedOutput.content contains JSON
        """
        # When
        result = self.formatter.format_output(self.mock_normalized_content, format='json')

        # Then
        #self.assertEqual(result, self.formatter._formatted_output)
        self.formatter._formatted_output.assert_called_once()

        # Verify the call was made with correct parameters
        call_args = self.formatter._formatted_output.call_args
        self.assertIsNotNone(call_args)

        self.assertEqual(call_args[1]['format'], 'json')


    def test_format_output_with_invalid_format(self):
        """
        GIVEN an OutputFormatter
        WHEN format_output is called with format='invalid_format'
        THEN expect:
            - ValueError raised
            - Error message indicates unsupported format
            - Lists available formats
        """
        # When/Then
        with self.assertRaises(ValueError) as context:
            self.formatter.format_output(self.mock_normalized_content, format='invalid_format')
        
        error_message = str(context.exception)
        self.assertIn('invalid_format', error_message.lower())

    def test_format_output_with_options(self):
        """
        GIVEN an OutputFormatter
        WHEN format_output is called with options={'indent': 4, 'sort_keys': True}
        THEN expect:
            - Options are passed to formatter function
            - Formatter uses options appropriately
            - Output reflects the options
        """
        # Given
        options = {'indent': 4, 'sort_keys': True}

        # When
        result = self.formatter.format_output(self.mock_normalized_content, format='json', options=options)

        # Then
        #self.assertEqual(result, self.formatter._formatted_output)
        self.formatter._formatted_output.assert_called_once()

        # Verify the call was made with correct parameters
        call_args = self.formatter._formatted_output.call_args
        self.assertIsNotNone(call_args)
        pprint(call_args)
        print(len(call_args))

        self.assertEqual(call_args[1]['format'], 'json')

        # The options are merged into metadata, not passed as separate 'options'
        metadata = call_args[1]['metadata']
        self.assertEqual(metadata['indent'], 4)
        self.assertEqual(metadata['sort_keys'], True)
        
        # Or if you want to check that the options are present in metadata:
        for key, value in options.items():
            self.assertEqual(metadata[key], value)

    def test_format_output_with_output_path(self):
        """
        GIVEN an OutputFormatter
        WHEN format_output is called with output_path='/path/to/output.txt'
        THEN expect:
            - FormattedOutput.output_path == '/path/to/output.txt'
            - Path is stored but file not written yet
        """
        # Given


        with tempfile.TemporaryDirectory() as temp_dir:

            output_path = f'{temp_dir}/output.txt'

            mock_configs = make_mock_configs()
            mock_resources = make_mock_resources()

            formatted_output = Mock(spec=FormattedOutput)
            formatted_output.output_path = output_path
            mock_resources['formatted_output'] = formatted_output

            formatter = OutputFormatter(resources=mock_resources, configs=mock_configs)

            # Configure _formatted_output to return the object from resources
            formatter._formatted_output.return_value = mock_resources['formatted_output']

            # When
            result = formatter.format_output(self.mock_normalized_content, output_path=output_path)

            # Then
            #self.assertEqual(result, self.formatter._formatted_output)
            formatter._formatted_output.assert_called_once()

            # Verify the output path is set correctly
            call_args = formatter._formatted_output.call_args
            self.assertIsNotNone(call_args)
            self.assertEqual(call_args[1]['output_path'], output_path)

            # Check that the output_path is stored in the FormattedOutput
            return_value = result.output_path
            self.assertEqual(return_value, output_path)

            # Check that the file is not written yet
            self.assertFalse(os.path.exists(output_path))


    def test_format_output_with_all_parameters(self):
        """
        GIVEN an OutputFormatter
        WHEN format_output is called with all parameters:
            - content: Content object
            - format: 'md'
            - options: {'include_toc': True}
            - output_path: '/path/to/output.md'
        THEN expect:
            - All parameters are processed correctly
            - Returns properly configured FormattedOutput
        """
        # Given
        options = {'include_toc': True}
        output_path = '/path/to/output.md'

        mock_configs = make_mock_configs()
        mock_resources = make_mock_resources()

        formatted_output = Mock(spec=FormattedOutput)
        formatted_output.output_path = output_path
        mock_resources['formatted_output'] = formatted_output

        formatter = OutputFormatter(resources=mock_resources, configs=mock_configs)

        # Configure _formatted_output to return the object from resources
        formatter._formatted_output.return_value = mock_resources['formatted_output']

        # When
        result = self.formatter.format_output(
            self.mock_normalized_content, 
            format='md', 
            options=options, 
            output_path=output_path
        )
        
        # Then
        #self.assertEqual(result, self.formatter._formatted_output)
        self.formatter._formatted_output.assert_called_once()

        # Verify the call was made with correct parameters
        call_args = self.formatter._formatted_output.call_args
        self.assertIsNotNone(call_args)
        self.assertEqual(call_args[1]['format'], 'md')
        self.assertEqual(call_args[1]['output_path'], output_path)

        # The options are merged into metadata, not passed as separate 'options'
        metadata = call_args[1]['metadata']
        self.assertEqual(metadata['include_toc'], True)


    def test_format_output_with_none_content(self):
        """
        GIVEN an OutputFormatter
        WHEN format_output is called with content=None
        THEN expect:
            - Appropriate error raised (TypeError or ValueError)
            - Clear error message
        """
        # When/Then
        with self.assertRaises((TypeError, ValueError, AttributeError)) as context:
            self.formatter.format_output(None)
        
        # Should raise some kind of error for None content
        self.assertIsNotNone(context.exception)


class TestRegisterFormat(unittest.TestCase):
    """Test custom format registration functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_configs = make_mock_configs()
        self.mock_resources = make_mock_resources()

        self.formatter = OutputFormatter(resources=self.mock_resources, configs=self.mock_configs)

    def test_register_format_with_valid_formatter(self):
        """
        GIVEN an OutputFormatter and a valid formatter function
        WHEN register_format is called with name='custom' and formatter=custom_func
        THEN expect:
            - Format is registered successfully
            - 'custom' appears in available_formats
            - format_output can use 'custom' format
        """
        # Given
        def custom_formatter(content):
            return f"CUSTOM: {content.text}"
        
        # When
        self.formatter.register_format('custom', custom_formatter)
        
        # Then
        self.assertIn('custom', self.formatter.output_formats)
        self.assertIn('custom', self.formatter.available_formats)
        self.assertEqual(self.formatter.output_formats['custom'], custom_formatter)

    def test_register_format_with_duplicate_name(self):
        """
        GIVEN an OutputFormatter with existing 'txt' format
        WHEN register_format is called with name='txt'
        THEN expect:
            - ValueError raised
            - Error message indicates format already exists
            - Existing formatter remains unchanged
        """
        # Given
        def duplicate_formatter(content):
            return "duplicate"
        
        original_formatter = self.formatter.output_formats['txt']
        
        # When/Then
        with self.assertRaises(ValueError) as context:
            self.formatter.register_format('txt', duplicate_formatter)
        
        error_message = str(context.exception)
        self.assertIn('txt', error_message.lower())
        self.assertIn('exists', error_message.lower())
        
        # Verify original formatter unchanged
        self.assertEqual(self.formatter.output_formats['txt'], original_formatter)

    def test_register_format_with_invalid_formatter(self):
        """
        GIVEN an OutputFormatter
        WHEN register_format is called with non-callable formatter
        THEN expect:
            - TypeError or ValueError raised
            - Clear error message about formatter needing to be callable
        """
        # Given
        non_callable_formatter = "not a function"
        
        # When/Then
        with self.assertRaises((TypeError, ValueError)) as context:
            self.formatter.register_format('invalid', non_callable_formatter)
        
        error_message = str(context.exception)
        self.assertIn('callable', error_message.lower())

    def test_register_format_updates_available_formats(self):
        """
        GIVEN an OutputFormatter with default formats
        WHEN register_format is called with new format
        THEN expect:
            - available_formats property includes new format
            - Order is maintained or alphabetical
        """
        # Given
        def new_formatter(content):
            return "new format"
        
        original_formats = set(self.formatter.available_formats)
        
        # When
        self.formatter.register_format('new_format', new_formatter)
        
        # Then
        updated_formats = set(self.formatter.available_formats)
        self.assertEqual(updated_formats, original_formats | {'new_format'})
        self.assertIn('new_format', self.formatter.available_formats)

    def test_register_format_case_sensitivity(self):
        """
        GIVEN an OutputFormatter
        WHEN register_format is called with 'TXT' (uppercase)
        THEN expect:
            - Either accepts as different format than 'txt'
            - Or normalizes to lowercase
            - Behavior is consistent
        """
        # Given
        def uppercase_formatter(content):
            return "UPPERCASE"
        
        # When
        try:
            self.formatter.register_format('TXT', uppercase_formatter)
            # If it doesn't raise an error, it should be treated as different from 'txt'
            self.assertIn('TXT', self.formatter.output_formats)
        except ValueError:
            # If it raises an error, it's treating 'TXT' as same as 'txt'
            # This is also acceptable behavior
            pass

    def test_register_format_with_lambda_function(self):
        """
        GIVEN an OutputFormatter
        WHEN register_format is called with a lambda function
        THEN expect:
            - Lambda is accepted as valid formatter
            - Format works correctly when used
        """
        # Given
        lambda_formatter = lambda content: f"LAMBDA: {content.text}"
        
        # When
        self.formatter.register_format('lambda_format', lambda_formatter)
        
        # Then
        self.assertIn('lambda_format', self.formatter.output_formats)
        self.assertEqual(self.formatter.output_formats['lambda_format'], lambda_formatter)

    def test_register_format_with_method_reference(self):
        """
        GIVEN an OutputFormatter
        WHEN register_format is called with a method reference
        THEN expect:
            - Method reference is accepted as valid formatter
            - Format is registered correctly
        """
        # Given
        class CustomFormatter:
            def format_content(self, content):
                return f"METHOD: {content.text}"
        
        custom_instance = CustomFormatter()
        
        # When
        self.formatter.register_format('method_format', custom_instance.format_content)
        
        # Then
        self.assertIn('method_format', self.formatter.output_formats)
        self.assertEqual(self.formatter.output_formats['method_format'], custom_instance.format_content)


class TestAvailableFormatsProperty(unittest.TestCase):
    """Test available_formats property functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_configs = make_mock_configs()
        self.mock_resources = make_mock_resources()


        self.formatter = OutputFormatter(resources=self.mock_resources, configs=self.mock_configs)

    def test_available_formats_returns_list(self):
        """
        GIVEN an OutputFormatter
        WHEN available_formats property is accessed
        THEN expect:
            - Returns list type
            - Not a dict_keys or other iterator
        """
        # When
        result = self.formatter.available_formats
        
        # Then
        self.assertIsInstance(result, list)
        self.assertNotIsInstance(result, dict)

    def test_available_formats_includes_defaults(self):
        """
        GIVEN a newly initialized OutputFormatter
        WHEN available_formats property is accessed
        THEN expect:
            - Contains 'txt', 'json', 'md'
            - Length is at least 3
        """
        # When
        result = self.formatter.available_formats

        # Then
        expected_defaults = {'txt', 'json', 'md'}
        result_set = set(result)

        self.assertTrue(expected_defaults.issubset(result_set))
        self.assertGreaterEqual(len(result), 3)

    def test_available_formats_updated_after_registration(self):
        """
        GIVEN an OutputFormatter
        WHEN new format is registered and available_formats accessed
        THEN expect:
            - New format appears in list
            - All previous formats still present
        """
        # Given
        def new_formatter(content):
            return "new format"
        
        original_formats = set(self.formatter.available_formats)
        
        # When
        self.formatter.register_format('new_test_format', new_formatter)
        updated_formats = set(self.formatter.available_formats)
        
        # Then
        self.assertIn('new_test_format', updated_formats)
        self.assertTrue(original_formats.issubset(updated_formats))
        self.assertEqual(len(updated_formats), len(original_formats) + 1)

    def test_available_formats_is_immutable(self):
        """
        GIVEN an OutputFormatter
        WHEN available_formats is accessed and modified externally
        THEN expect:
            - Modifications don't affect internal output_formats
            - Next call returns fresh list
        """
        # Given
        original_count = len(self.formatter.output_formats)
        
        # When
        formats_list = self.formatter.available_formats
        formats_list.append('external_modification')
        formats_list.clear()
        
        # Then
        # Verify internal state unchanged
        self.assertEqual(len(self.formatter.output_formats), original_count)
        
        # Verify next call returns fresh list
        new_list = self.formatter.available_formats
        self.assertGreaterEqual(len(new_list), 3)
        self.assertNotEqual(len(new_list), 0)

    def test_available_formats_consistency_with_output_formats(self):
        """
        GIVEN an OutputFormatter
        WHEN available_formats is accessed multiple times
        THEN expect:
            - Always returns same formats as keys in output_formats
            - Order might vary but content is consistent
        """
        # When
        formats_list = self.formatter.available_formats
        output_formats_keys = list(self.formatter.output_formats.keys())
        
        # Then
        self.assertEqual(set(formats_list), set(output_formats_keys))

    def test_available_formats_after_multiple_registrations(self):
        """
        GIVEN an OutputFormatter
        WHEN multiple formats are registered sequentially
        THEN expect:
            - available_formats reflects all changes
            - No duplicates in the list
        """
        # Given
        formatters = {
            'format1': lambda c: "format1",
            'format2': lambda c: "format2", 
            'format3': lambda c: "format3"
        }
        
        original_count = len(self.formatter.available_formats)
        
        # When
        for name, formatter in formatters.items():
            self.formatter.register_format(name, formatter)
        
        final_formats = self.formatter.available_formats
        
        # Then
        self.assertEqual(len(final_formats), original_count + 3)
        self.assertEqual(len(final_formats), len(set(final_formats)))  # No duplicates
        
        for name in formatters.keys():
            self.assertIn(name, final_formats)


class TestOutputFormatterIntegration(unittest.TestCase):
    """Test OutputFormatter integration with FormattedOutput."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_configs = make_mock_configs()
        self.mock_resources = make_mock_resources()

        self.formatter = OutputFormatter(
            resources=self.mock_resources,
            configs=self.mock_configs
        )
        # Create mock content with metadata
        self.mock_normalized_content = make_mock_normalized_content()

    def test_formatted_output_creation(self):
        """
        GIVEN an OutputFormatter with valid resources including FormattedOutput class
        WHEN format_output is called
        THEN expect:
            - FormattedOutput instance is created
            - Instance has correct attributes set
            - Instance is properly initialized
        """
        # When
        result = self.formatter.format_output(self.mock_normalized_content, format='txt')
        
        # Then
        #self.assertEqual(result, self.mock_resources['formatted_output'])
        self.formatter._formatted_output.assert_called_once()
        
        # Verify the FormattedOutput was created with appropriate parameters
        call_args, call_kwargs = self.formatter._formatted_output.call_args
        self.assertIsNotNone(call_args or call_kwargs)

    def test_formatted_output_metadata_handling(self):
        """
        GIVEN an OutputFormatter and Content with metadata
        WHEN format_output is called
        THEN expect:
            - FormattedOutput.metadata contains relevant metadata
            - Metadata is properly transferred from Content
        """
        # When
        result = self.formatter.format_output(self.mock_normalized_content, format='json')
        
        # Then
        #self.assertEqual(result, self.mock_resources['formatted_output'])
        self.formatter._formatted_output.assert_called_once()
        
        # The exact way metadata is passed depends on implementation,
        # but the FormattedOutput should be created with content that includes metadata
        call_args, call_kwargs = self.formatter._formatted_output.call_args
        self.assertTrue(call_args is not None or call_kwargs is not None)

    def test_end_to_end_formatting_workflow(self):
        """
        GIVEN complete setup with OutputFormatter, Content, and output path
        WHEN format_output is called followed by write_to_file
        THEN expect:
            - Content is formatted correctly
            - FormattedOutput is created
            - File can be written successfully
        """
        # Given
        output_path = "/tmp/test_output.md"
        
        # Mock the write_to_file method on the FormattedOutput instance
        self.formatter._formatted_output.write_to_file = Mock(return_value=True)
        
        # When
        result = self.formatter.format_output(
            self.mock_normalized_content, 
            format='md', 
            output_path=output_path
        )
        
        # Simulate writing to file
        # NOTE This is not done in the formatter, but in the pipeline itself.
        write_success = result.write_to_file()
        
        # Then
        #self.assertEqual(result, self.formatter._formatted_output)
        self.assertTrue(write_success)
        result.write_to_file.assert_called_once()

    def test_formatting_with_different_content_types(self):
        """
        GIVEN an OutputFormatter
        WHEN format_output is called with different content configurations
        THEN expect:
            - All content types are handled appropriately
            - FormattedOutput is created for each
        """
        import random
        random.seed(420)  # For reproducibility

        # Given - Content with different characteristics
        content_variations = make_sample_normalized_content_variations()
        
        for content in content_variations:
            with self.subTest(content=content):

                # Choose a given format randomly
                formats = ['txt', 'json', 'md']
                chosen_format = random.choice(formats)

                # Reset mock
                self.formatter._formatted_output.reset_mock()

                # When
                result = self.formatter.format_output(content, format=chosen_format)
                
                # Then
                #self.assertEqual(result, self.formatter._formatted_output)
                self.formatter._formatted_output.assert_called_once()

    def test_integration_with_custom_formatter(self):
        """
        GIVEN an OutputFormatter with a custom registered format
        WHEN format_output is called using the custom format
        THEN expect:
            - Custom formatter is used correctly
            - FormattedOutput is created with custom formatted content
            - Integration works seamlessly
        """
        # Given
        def custom_formatter(output_dict):
            return f"CUSTOM PREFIX: {output_dict['text']} | METADATA: {output_dict['metadata']}"
        
        self.formatter.register_format('custom_test', custom_formatter)
        
        # When
        result = self.formatter.format_output(self.mock_normalized_content, format='custom_test')
        
        # Then
        #self.assertEqual(result, self.formatter._formatted_output)
        self.formatter._formatted_output.assert_called_once()

        # Verify the call was made with correct parameters
        call_args, call_kwargs = self.formatter._formatted_output.call_args
        self.assertIsNotNone(call_args or call_kwargs)
        self.assertEqual(call_kwargs['format'], 'custom_test')

        # Check if the custom formatter was used
        formatters = self.formatter.output_formats
        self.assertIn('custom_test', formatters)


class TestOutputFormatterErrorHandling(unittest.TestCase):
    """Test error handling in OutputFormatter."""

    def setUp(self):
        """Set up test fixtures."""

        self.mock_configs = make_mock_configs()
        self.mock_resources = make_mock_resources()
        self.formatter = OutputFormatter(resources=self.mock_resources, configs=self.mock_configs)

        # Create mock content
        self.mock_norm_content = make_mock_normalized_content()

    def test_formatter_function_raises_exception(self):
        """
        GIVEN a formatter function that raises an exception
        WHEN format_output is called using that formatter
        THEN expect:
            - Exception is caught and handled appropriately
            - Error is logged
            - User-friendly error returned or re-raised
        """
        # Given
        def failing_formatter(content):
            raise RuntimeError("Formatter failed!")
        
        self.formatter.register_format('failing_format', failing_formatter)
        
        # When/Then
        with self.assertRaises((RuntimeError, Exception)):
            self.formatter.format_output(self.mock_norm_content, format='failing_format')

    def test_invalid_content_type_handling(self):
        """
        GIVEN various invalid content types (string, dict, list, etc.)
        WHEN format_output is called
        THEN expect:
            - Appropriate type checking
            - Clear error messages
            - No silent failures
        """
        invalid_content_types = [
            "string content",
            {"dict": "content"},
            ["list", "content"],
            123,
            None
        ]
        
        for invalid_content in invalid_content_types:
            with self.subTest(content_type=type(invalid_content).__name__):
                # When/Then
                with self.assertRaises((TypeError, ValueError, AttributeError)):
                    self.formatter.format_output(invalid_content)

    def test_concurrent_format_registration(self):
        """
        GIVEN an OutputFormatter used by multiple threads
        WHEN register_format is called concurrently
        THEN expect:
            - Thread-safe operation
            - No race conditions
            - All formats registered properly
        """
        # Given
        results = {}
        errors = {}
        
        def register_format_thread(thread_id):
            try:
                formatter_func = lambda content: f"Thread {thread_id} format"
                self.formatter.register_format(f'thread_{thread_id}', formatter_func)
                results[thread_id] = True
            except Exception as e:
                errors[thread_id] = e
        
        # When
        threads = []
        for i in range(5):
            thread = threading.Thread(target=register_format_thread, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Then
        # Check that most or all registrations succeeded
        self.assertGreater(len(results), 0)
        
        # Verify formats were actually registered
        for thread_id in results.keys():
            self.assertIn(f'thread_{thread_id}', self.formatter.available_formats)

    def test_malformed_formatter_function(self):
        """
        GIVEN a formatter function with incorrect signature
        WHEN input into register_format
        THEN expect:
            - TypeError raised
            - Clear error message about function signature
        """
        # Given - formatter with wrong signature (no parameters)
        def bad_signature_formatter():
            return "bad formatter"

        # When/Then
        with self.assertRaises(TypeError):
            self.formatter.register_format('bad_signature', bad_signature_formatter)

    def test_formatter_returns_non_string(self):
        """
        GIVEN a formatter that returns non-string content
        WHEN format_output is called
        THEN expect:
            - Either handled gracefully (converted to string)
            - Or raises appropriate error with clear message
        """
        # Given
        def non_string_formatter(output_dict):
            return {"formatted": 420}  # Returns int instead of string
        
        self.formatter.register_format('non_string', non_string_formatter)
        
        # When/Then
        # This should either work (with conversion) or fail clearly
        try:
            result = self.formatter.format_output(self.mock_norm_content, format='non_string')
            # If it succeeds, verify result is reasonable
            self.assertIsNotNone(result)
        except (TypeError, ValueError) as e:
            # If it fails, it should be a clear error
            self.assertIsInstance(e, (TypeError, ValueError))

    def test_missing_content_attributes(self):
        """
        GIVEN content object missing expected attributes
        WHEN formatter tries to access missing attributes
        THEN expect:
            - AttributeError handling
            - Graceful degradation or clear error message
        """
        # Given
        incomplete_content = Mock()
        # Don't set .text or .metadata attributes
 
        # When/Then
        with self.assertRaises((AttributeError, TypeError, ValueError)):
            self.formatter.format_output(incomplete_content, format='txt')

    def test_large_content_handling(self):
        """
        GIVEN extremely large content object
        WHEN format_output is called
        THEN expect:
            - Either handles large content successfully
            - Or fails gracefully with memory/size error
        """
        # Given
        self.mock_norm_content.content.text = "x" * 1000000  # 1MB of text
        self.mock_norm_content.content.metadata = {"size": "large"}
        
        # When/Then
        try:
            result = self.formatter.format_output(self.mock_norm_content, format='txt')
            self.assertIsNotNone(result)
        except (MemoryError, OverflowError) as e:
            # These are acceptable for very large content
            self.assertIsInstance(e, (MemoryError, OverflowError))
