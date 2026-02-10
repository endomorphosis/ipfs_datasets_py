"""
Test suite for interfaces/options.py converted from unittest to pytest.
"""
import pytest
from unittest.mock import patch, MagicMock
import argparse
import tempfile
import os
from pathlib import Path
from enum import StrEnum

# Import the actual modules - adjust imports based on your project structure
from logger import test_logger as logger
from interfaces.options import (
    _validate_max_workers,
    _validate_max_memory,
    _validate_max_vram,
    Options,
    OutputFormat
)

try:
    from pydantic import ValidationError
    import psutil
except ImportError:
    pytest.skip("Required modules pydantic and psutil are not installed", allow_module_level=True)


# Test Constants
VALID_WORKER_COUNT = 4
INVALID_WORKER_COUNT = 1000
TOTAL_CPU_CORES = 8
VALID_MEMORY_LIMIT = 1
INVALID_MEMORY_LIMIT = 100
TOTAL_SYSTEM_MEMORY = 6
VALID_VRAM_LIMIT = 6144
TXT_FORMAT_VALUE = "txt"
MD_FORMAT_VALUE = "md"
JSON_FORMAT_VALUE = "json"


@pytest.mark.unit
class TestValidateMaxWorkers:
    """
    Tests for _validate_max_workers function behavior.
    Function under test: _validate_max_workers
    Valid input: Worker count less than or equal to CPU cores
    """

    @patch('os.cpu_count')
    def test_when_valid_worker_count_provided_then_returns_same_value(self, mock_cpu_count):
        """
        GIVEN a max_threads value less than CPU cores
        WHEN _validate_max_workers is called with valid worker count
        THEN expect function returns the same value
        """
        mock_cpu_count.return_value = TOTAL_CPU_CORES
        
        result = _validate_max_workers(VALID_WORKER_COUNT)
        
        assert result == VALID_WORKER_COUNT, f"Expected {VALID_WORKER_COUNT}, got {result}"

    @patch('os.cpu_count')
    def test_when_excessive_worker_count_provided_then_raises_value_error(self, mock_cpu_count):
        """
        GIVEN a max_threads value greater than available CPU cores
        WHEN _validate_max_workers is called with excessive worker count
        THEN expect ValueError is raised
        """
        mock_cpu_count.return_value = TOTAL_CPU_CORES
        
        with pytest.raises(ValueError) as exc_info:
            _validate_max_workers(INVALID_WORKER_COUNT)
        
        assert "cpu" in str(exc_info.value).lower(), f"Expected 'cpu' in error message, got: {exc_info.value}"


@pytest.mark.unit
class TestValidateMaxMemory:
    """
    Tests for _validate_max_memory function behavior.
    Function under test: _validate_max_memory
    Valid input: Memory value less than total system memory
    """

    @patch('interfaces.options.Hardware.get_total_memory_in_gb')
    def test_when_valid_memory_limit_provided_then_returns_same_value(self, mock_get_memory):
        """
        GIVEN a max_memory value less than current total memory
        WHEN _validate_max_memory is called with valid memory limit
        THEN expect function returns the same value
        """
        mock_get_memory.return_value = TOTAL_SYSTEM_MEMORY
        
        result = _validate_max_memory(VALID_MEMORY_LIMIT)
        
        assert result == VALID_MEMORY_LIMIT, f"Expected {VALID_MEMORY_LIMIT}, got {result}"

    @patch('interfaces.options.Hardware.get_total_memory_in_gb')
    def test_when_excessive_memory_limit_provided_then_raises_value_error(self, mock_get_memory):
        """
        GIVEN a max_memory value greater than current total memory
        WHEN _validate_max_memory is called with excessive memory limit
        THEN expect ValueError is raised
        """
        mock_get_memory.return_value = TOTAL_SYSTEM_MEMORY

        with pytest.raises(ValueError):
            _validate_max_memory(INVALID_MEMORY_LIMIT)


@pytest.mark.unit
class TestValidateMaxVram:
    """
    Tests for _validate_max_vram function behavior.
    Function under test: _validate_max_vram
    Valid input: Any positive VRAM value
    """

    def test_when_positive_vram_value_provided_then_returns_same_value(self):
        """
        GIVEN any positive max_vram value
        WHEN _validate_max_vram is called with positive VRAM limit
        THEN expect function returns the same value
        """
        result = _validate_max_vram(VALID_VRAM_LIMIT)
        
        assert result == VALID_VRAM_LIMIT, f"Expected {VALID_VRAM_LIMIT}, got {result}"


@pytest.mark.unit
class TestOutputFormatTxt:
    """
    Tests for OutputFormat.TXT enum value behavior.
    Enum under test: OutputFormat.TXT
    """

    def test_when_accessing_txt_format_then_returns_txt_string(self):
        """
        GIVEN the OutputFormat enum
        WHEN accessing OutputFormat.TXT
        THEN expect value equals txt string constant
        """
        assert OutputFormat.TXT == TXT_FORMAT_VALUE, f"Expected {TXT_FORMAT_VALUE}, got {OutputFormat.TXT}"

    def test_when_accessing_txt_format_then_is_str_enum_instance(self):
        """
        GIVEN the OutputFormat enum
        WHEN accessing OutputFormat.TXT
        THEN expect instance is StrEnum type
        """
        assert isinstance(OutputFormat.TXT, StrEnum), f"Expected StrEnum instance, got {type(OutputFormat.TXT)}"


@pytest.mark.unit
class TestOutputFormatMd:
    """
    Tests for OutputFormat.MD enum value behavior.
    Enum under test: OutputFormat.MD
    """

    def test_when_accessing_md_format_then_returns_md_string(self):
        """
        GIVEN the OutputFormat enum
        WHEN accessing OutputFormat.MD
        THEN expect value equals md string constant
        """
        assert OutputFormat.MD == MD_FORMAT_VALUE, f"Expected {MD_FORMAT_VALUE}, got {OutputFormat.MD}"

    def test_when_accessing_md_format_then_is_str_enum_instance(self):
        """
        GIVEN the OutputFormat enum
        WHEN accessing OutputFormat.MD
        THEN expect instance is StrEnum type
        """
        assert isinstance(OutputFormat.MD, StrEnum), f"Expected StrEnum instance, got {type(OutputFormat.MD)}"


@pytest.mark.unit
class TestOutputFormatJson:
    """
    Tests for OutputFormat.JSON enum value behavior.
    Enum under test: OutputFormat.JSON
    """

    def test_when_accessing_json_format_then_returns_json_string(self):
        """
        GIVEN the OutputFormat enum
        WHEN accessing OutputFormat.JSON
        THEN expect value equals json string constant
        """
        assert OutputFormat.JSON == JSON_FORMAT_VALUE, f"Expected {JSON_FORMAT_VALUE}, got {OutputFormat.JSON}"

    def test_when_accessing_json_format_then_is_str_enum_instance(self):
        """
        GIVEN the OutputFormat enum
        WHEN accessing OutputFormat.JSON
        THEN expect instance is StrEnum type
        """
        assert isinstance(OutputFormat.JSON, StrEnum), f"Expected StrEnum instance, got {type(OutputFormat.JSON)}"


# Additional Test Constants
DEFAULT_OUTPUT_PATH = Path.home()
DEFAULT_WALK_VALUE = False
DEFAULT_NORMALIZE_VALUE = True
TEST_BATCH_SIZE = 50
TEST_RETRIES = 3
TEST_THREADS = 2
TEST_MEMORY = 4
TEST_VRAM = 4
TEST_BUDGET = 10.0
TEST_NORMALIZERS = "test"
TEST_CPU = 50
TEST_QUALITY_THRESHOLD = 0.5


@pytest.fixture
def temp_files():
    """Create temporary files and directories for testing."""
    temp_dir = tempfile.mkdtemp()
    temp_file = os.path.join(temp_dir, "test_file.txt")
    with open(temp_file, 'w') as f:
        f.write("test content")
    
    yield {'temp_dir': temp_dir, 'temp_file': temp_file}
    
    # Cleanup
    if os.path.exists(temp_file):
        os.remove(temp_file)
    if os.path.exists(temp_dir):
        os.rmdir(temp_dir)


@pytest.mark.unit
class TestOptionsCreationMinimal:
    """
    Tests for Options model creation with minimal parameters.
    Class under test: Options.__init__
    Valid input: Required input parameter only
    """

    def test_when_minimal_input_provided_then_creates_instance(self, temp_files):
        """
        GIVEN only required input parameter
        WHEN Options is created with input file path
        THEN expect Options instance is created
        """
        options = Options(input=temp_files['temp_file'])
        
        assert isinstance(options, Options), f"Expected Options instance, got {type(options)}"

    def test_when_minimal_input_provided_then_sets_input_path(self, temp_files):
        """
        GIVEN only required input parameter
        WHEN Options is created with input file path
        THEN expect input attribute matches provided path
        """
        options = Options(input=temp_files['temp_file'])
        
        assert str(options.input) == temp_files['temp_file'], f"Expected {temp_files['temp_file']}, got {options.input}"

    def test_when_minimal_input_provided_then_sets_default_output(self, temp_files):
        """
        GIVEN only required input parameter
        WHEN Options is created with input file path
        THEN expect output attribute equals default home path
        """
        options = Options(input=temp_files['temp_file'])
        
        assert options.output == DEFAULT_OUTPUT_PATH, f"Expected {DEFAULT_OUTPUT_PATH}, got {options.output}"

    def test_when_minimal_input_provided_then_sets_default_walk(self, temp_files):
        """
        GIVEN only required input parameter
        WHEN Options is created with input file path
        THEN expect walk attribute equals default walk value
        """
        options = Options(input=temp_files['temp_file'])
        
        assert options.walk is DEFAULT_WALK_VALUE, f"Expected {DEFAULT_WALK_VALUE}, got {options.walk}"

    def test_when_minimal_input_provided_then_sets_default_normalize(self, temp_files):
        """
        GIVEN only required input parameter
        WHEN Options is created with input file path
        THEN expect normalize attribute equals default normalize value
        """
        options = Options(input=temp_files['temp_file'])
        
        assert options.normalize is DEFAULT_NORMALIZE_VALUE, f"Expected {DEFAULT_NORMALIZE_VALUE}, got {options.normalize}"


@pytest.mark.unit
class TestOptionsCreationWithFormat:
    """
    Tests for Options model creation with format specification.
    Class under test: Options.__init__
    Valid input: Input and format parameters
    """

    def test_when_json_format_specified_then_sets_json_format(self, temp_files):
        """
        GIVEN input parameter and JSON format
        WHEN Options is created with format=OutputFormat.JSON
        THEN expect format attribute equals JSON output format
        """
        options = Options(input=temp_files['temp_file'], format=OutputFormat.JSON)
        
        assert options.format == OutputFormat.JSON, f"Expected {OutputFormat.JSON}, got {options.format}"

    def test_when_custom_batch_size_specified_then_sets_batch_size(self, temp_files):
        """
        GIVEN input parameter and custom batch size
        WHEN Options is created with batch_size parameter
        THEN expect batch_size attribute equals provided value
        """
        options = Options(input=temp_files['temp_file'], batch_size=TEST_BATCH_SIZE)
        
        assert options.batch_size == TEST_BATCH_SIZE, f"Expected {TEST_BATCH_SIZE}, got {options.batch_size}"

    def test_when_custom_retries_specified_then_sets_retries(self, temp_files):
        """
        GIVEN input parameter and custom retries value
        WHEN Options is created with retries parameter
        THEN expect retries attribute equals provided value
        """
        options = Options(input=temp_files['temp_file'], retries=TEST_RETRIES)
        
        assert options.retries == TEST_RETRIES, f"Expected {TEST_RETRIES}, got {options.retries}"


@pytest.mark.unit
class TestOptionsInputValidation:
    """
    Tests for Options model input validation behavior.
    Class under test: Options.__init__
    Valid input: Existing file or directory paths
    """

    def test_when_existing_file_provided_then_input_path_exists(self, temp_files):
        """
        GIVEN a valid existing file path
        WHEN Options is created with input file path
        THEN expect input path exists as file
        """
        options = Options(input=temp_files['temp_file'])
        
        assert Path(options.input).exists(), f"Expected path {options.input} to exist"

    def test_when_existing_file_provided_then_input_is_file(self, temp_files):
        """
        GIVEN a valid existing file path
        WHEN Options is created with input file path
        THEN expect input path is a file
        """
        options = Options(input=temp_files['temp_file'])
        
        assert Path(options.input).is_file(), f"Expected {options.input} to be a file"

    def test_when_existing_directory_provided_then_input_path_exists(self, temp_files):
        """
        GIVEN a valid directory path
        WHEN Options is created with input directory path
        THEN expect input path exists
        """
        options = Options(input=temp_files['temp_dir'])
        
        assert Path(options.input).exists(), f"Expected path {options.input} to exist"

    def test_when_existing_directory_provided_then_input_is_directory(self, temp_files):
        """
        GIVEN a valid directory path
        WHEN Options is created with input directory path
        THEN expect input path is a directory
        """
        options = Options(input=temp_files['temp_dir'])
        
        assert Path(options.input).is_dir(), f"Expected {options.input} to be a directory"

    def test_options_input_list_of_files(self, temp_files):
        """
        GIVEN a list of valid file paths
        WHEN Options(input=["/file1.txt", "/file2.txt"]) is created
        THEN expect:
            - input field accepts list[FilePath]
            - All files exist validation passes
        """
        temp_file2 = os.path.join(temp_files['temp_dir'], "test_file2.txt")
        with open(temp_file2, 'w') as f:
            f.write("test content 2")
        
        try:
            options = Options(input=[temp_files['temp_file'], temp_file2])
            assert isinstance(options.input, list)
            assert len(options.input) == 2
        finally:
            if os.path.exists(temp_file2):
                os.remove(temp_file2)

    def test_options_output_default(self, temp_files):
        """
        GIVEN no output parameter specified
        WHEN Options instance is created
        THEN expect:
            - output defaults to Path.home()
            - Is DirectoryPath type
        """
        options = Options(input=temp_files['temp_file'])
        assert options.output == Path.home()

    def test_options_format_validation(self, temp_files):
        """
        GIVEN an invalid format value
        WHEN Options(input="/file", format="invalid") is created
        THEN expect:
            - ValidationError is raised
            - Error mentions valid formats
        """
        with pytest.raises(ValidationError) as exc_info:
            Options(input=temp_files['temp_file'], format="invalid")
        assert "format" in str(exc_info.value).lower()

    def test_options_max_cpu_range(self, temp_files):
        """
        GIVEN max_cpu value over 100
        WHEN Options(input="/file", max_cpu=150) is created
        THEN expect:
            - ValidationError is raised
            - Error mentions maximum of 100
        """
        with pytest.raises(ValidationError) as exc_info:
            Options(input=temp_files['temp_file'], max_cpu=150)
        assert "100" in str(exc_info.value)

    def test_options_quality_threshold_range(self, temp_files):
        """
        GIVEN quality_threshold value over 1.0
        WHEN Options(input="/file", quality_threshold=1.5) is created
        THEN expect:
            - ValidationError is raised
            - Error mentions maximum of 1.0
        """
        with pytest.raises(ValidationError) as exc_info:
            Options(input=temp_files['temp_file'], quality_threshold=1.5)
        assert "1" in str(exc_info.value)


@pytest.mark.unit
class TestOptionsToDict:
    """Test the to_dict method of Options."""

    def test_to_dict_all_fields(self, temp_files):
        """
        GIVEN an Options instance with all fields set
        WHEN to_dict() is called
        THEN expect:
            - Returns dictionary with all fields
            - Values match instance attributes
            - No missing fields
        """
        options = Options(
            input=temp_files['temp_file'],
            output=temp_files['temp_dir'],
            walk=True,
            normalize=False,
            format=OutputFormat.JSON
        )
        result_dict = options.to_dict()
        logger.debug(f"Options to_dict result: {result_dict}")
        
        assert isinstance(result_dict, dict)
        assert 'input' in result_dict
        assert 'output' in result_dict
        assert 'walk' in result_dict
        assert 'normalize' in result_dict
        assert 'format' in result_dict

        # Check values match instance attributes
        assert result_dict['walk'] is True
        assert result_dict['normalize'] is False

    def test_to_dict_defaults_only(self, temp_files):
        """
        GIVEN an Options instance with only defaults
        WHEN to_dict() is called
        THEN expect:
            - Returns dictionary with all fields
            - All values are defaults
        """
        options = Options(input=temp_files['temp_file'])
        result_dict = options.to_dict()
        
        assert isinstance(result_dict, dict)
        assert result_dict['walk'] is False
        assert result_dict['normalize'] is True
        assert result_dict['format'] == OutputFormat.TXT


@pytest.mark.unit
class TestOptionsPrintOptions:
    """Test the print_options method of Options."""

    @patch('builtins.print')
    def test_print_options_defaults(self, mock_print, temp_files):
        """
        GIVEN an Options instance
        WHEN print_options(type_="defaults") is called
        THEN expect:
            - Prints default values for all fields
            - Includes field descriptions
            - Output formatted correctly
        """
        options = Options(input=temp_files['temp_file'])
        options.print_options(type_="defaults")
        
        mock_print.assert_called()
        # Check that print was called with some expected content
        printed_content = ''.join([str(call.args[0]) for call in mock_print.call_args_list])
        assert "default" in printed_content.lower()

    @patch('builtins.print')
    def test_print_options_current(self, mock_print, temp_files):
        """
        GIVEN an Options instance with custom values
        WHEN print_options(type_="current") is called
        THEN expect:
            - Prints current values for all fields
            - Shows both current and default values
            - Output formatted correctly
        """
        options = Options(input=temp_files['temp_file'], walk=True, normalize=False)
        options.print_options(type_="current")
        
        mock_print.assert_called()
        printed_content = ''.join([str(call.args[0]) for call in mock_print.call_args_list])
        assert "current" in printed_content.lower()

    def test_print_options_invalid_type(self, temp_files):
        """
        GIVEN an Options instance
        WHEN print_options(type_="invalid") is called
        THEN expect:
            - Raises ValueError
            - Error message mentions valid types
        """
        options = Options(input=temp_files['temp_file'])
        with pytest.raises(ValueError) as exc_info:
            options.print_options(type_="invalid")
        assert "valid" in str(exc_info.value).lower()


@pytest.mark.unit
class TestOptionsMakeArgparse:
    """Test the add_arguments_to_parser method of Options."""

    @pytest.fixture
    def parser(self):
        """Create a fresh ArgumentParser for each test."""
        return argparse.ArgumentParser()

    def test_make_argparse_all_arguments(self, temp_files, parser):
        """
        GIVEN an Options instance and ArgumentParser
        WHEN add_arguments_to_parser(parser) is called
        THEN expect:
            - All fields added as arguments
            - Correct types assigned
            - Help text included
        """
        options = Options(input=temp_files['temp_file'])
        result_parser = options.add_arguments_to_parser(parser)
        
        assert isinstance(result_parser, argparse.ArgumentParser)
        
        # Check that some key arguments were added
        help_text = result_parser.format_help()
        assert "input" in help_text.lower()
        assert "output" in help_text.lower()
        assert "walk" in help_text.lower()

    def test_make_argparse_defaults(self, temp_files, parser):
        """
        GIVEN an Options instance and ArgumentParser
        WHEN add_arguments_to_parser(parser) is called
        THEN expect:
            - All arguments have correct defaults
            - Defaults match field definitions
        """
        options = Options(input=temp_files['temp_file'])
        result_parser = options.add_arguments_to_parser(parser)
        
        # Parse with minimal required args to get defaults
        args = result_parser.parse_args(['--input', temp_files['temp_file']])
        print(f"args: {args}")
        
        # Check all default values
        assert args.input == temp_files['temp_file']  # Required field, provided
        assert str(args.output) == str(Path.home())
        assert args.walk is False
        assert args.normalize is True
        assert args.security_checks is True
        assert args.metadata is True
        assert args.structure is True
        assert args.format == OutputFormat.TXT.value  # Note: will be string value
        assert args.max_threads == 4
        assert args.max_memory == 6
        assert args.max_vram == 6
        assert args.budget_in_usd == 0.0
        assert args.normalizers is None
        assert args.max_cpu == 80
        assert args.quality_threshold == 0.9
        assert args.continue_on_error is True
        assert args.parallel is False
        assert args.follow_symlinks is False
        assert args.include_metadata is True
        assert args.lossy is False
        assert args.normalize_text is True
        assert args.sanitize is True
        assert args.show_options is False
        assert args.show_progress is False
        assert args.verbose is False
        assert args.list_formats is False
        assert args.version is False
        assert args.max_batch_size == 100
        assert args.retries == 0