import unittest
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
    raise ImportError("Required modules pydantic and psutil are not installed. Please install them using 'pip install pydantic psutil'.")

# class TestValidateFormat(unittest.TestCase):
#     """Test the _validate_format function."""

#     def test_validate_format_txt(self):
#         """
#         GIVEN a format string "txt"
#         WHEN _validate_format("txt") is called
#         THEN expect:
#             - Returns "txt"
#             - No ValidationError raised
#         """
#         result = _validate_format("txt")
#         self.assertEqual(result, "txt")

#     def test_validate_format_md(self):
#         """
#         GIVEN a format string "md"
#         WHEN _validate_format("md") is called
#         THEN expect:
#             - Returns "md"
#             - No ValidationError raised
#         """
#         result = _validate_format("md")
#         self.assertEqual(result, "md")

#     def test_validate_format_unsupported(self):
#         """
#         GIVEN an unsupported format string "pdf"
#         WHEN _validate_format("pdf") is called
#         THEN expect:
#             - Raises ValidationError
#             - Error message contains supported formats
#         """
#         with self.assertRaises(ValueError) as context:
#             _validate_format("pdf")
#         self.assertIn("supported", str(context.exception).lower())


class TestValidateMaxWorkers(unittest.TestCase):
    """Test the _validate_max_workers function."""

    @patch('os.cpu_count')
    def test_validate_max_workers_valid(self, mock_cpu_count):
        """
        GIVEN a max_threads value less than CPU cores
        WHEN _validate_max_workers(4) is called
        THEN expect:
            - Returns the same value
            - No ValidationError raised
        """
        mock_cpu_count.return_value = 8
        result = _validate_max_workers(4)
        self.assertEqual(result, 4)

    @patch('os.cpu_count')
    def test_validate_max_workers_exceeds_cpu_cores(self, mock_cpu_count):
        """
        GIVEN a max_threads value greater than available CPU cores
        WHEN _validate_max_workers(1000) is called
        THEN expect:
            - Raises ValidationError
            - Error message mentions CPU cores limit
        """
        mock_cpu_count.return_value = 8
        with self.assertRaises(ValueError) as context:
            _validate_max_workers(1000)
        self.assertIn("cpu", str(context.exception).lower())


class TestValidateMaxMemory(unittest.TestCase):
    """Test the _validate_max_memory function."""

    @patch('interfaces.options.Hardware.get_total_memory_in_gb')
    def test_validate_max_memory_valid(self, mock_get_memory):
        """
        GIVEN a max_memory value less than current total memory
        WHEN _validate_max_memory(1) is called
        THEN expect:
            - Returns the same value
            - No ValidationError raised
        """
        mock_get_memory.return_value = 6  # 6 GiB
        
        result = _validate_max_memory(1)
        self.assertEqual(result, 1)

    @patch('interfaces.options.Hardware.get_total_memory_in_gb')
    def test_validate_max_memory_below_current_usage(self, mock_get_memory):
        """
        GIVEN a max_memory value greater than current total memory
        WHEN _validate_max_memory(100) is called
        THEN expect:
            - Raises ValueError
            - Error message contains current RSS usage
        """
        mock_get_memory.return_value = 6  # 6 GiB

        try:
            result = _validate_max_memory(100)
            logger.debug(f"Unexpected success: returned {result}")
        except Exception as e:
            logger.debug(f"Exception raised: {type(e).__name__}: {e}")
        
        with self.assertRaises(ValueError) as context:
            _validate_max_memory(100)


class TestValidateMaxVram(unittest.TestCase):
    """Test the _validate_max_vram function."""

    def test_validate_max_vram_any_positive_value(self):
        """
        GIVEN any positive max_vram value
        WHEN _validate_max_vram(6144) is called
        THEN expect:
            - Returns the same value
            - No ValidationError raised (TODO: validation not implemented)
        """
        result = _validate_max_vram(6144)
        self.assertEqual(result, 6144)


class TestOutputFormat(unittest.TestCase):
    """Test the OutputFormat enum."""

    def test_output_format_txt_value(self):
        """
        GIVEN the OutputFormat enum
        WHEN accessing OutputFormat.TXT
        THEN expect:
            - Value equals "txt"
            - Is instance of StrEnum
        """
        self.assertEqual(OutputFormat.TXT, "txt")
        self.assertIsInstance(OutputFormat.TXT, StrEnum)

    def test_output_format_md_value(self):
        """
        GIVEN the OutputFormat enum
        WHEN accessing OutputFormat.MD
        THEN expect:
            - Value equals "md"
            - Is instance of StrEnum
        """
        self.assertEqual(OutputFormat.MD, "md")
        self.assertIsInstance(OutputFormat.MD, StrEnum)

    def test_output_format_json_value(self):
        """
        GIVEN the OutputFormat enum
        WHEN accessing OutputFormat.JSON
        THEN expect:
            - Value equals "json"
            - Is instance of StrEnum
        """
        self.assertEqual(OutputFormat.JSON, "json")
        self.assertIsInstance(OutputFormat.JSON, StrEnum)


class TestOptionsModel(unittest.TestCase):
    """Test the Options Pydantic model."""

    def setUp(self):
        """Create temporary files and directories for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_file = os.path.join(self.temp_dir, "test_file.txt")
        with open(self.temp_file, 'w') as f:
            f.write("test content")

    def tearDown(self):
        """Clean up temporary files."""
        if os.path.exists(self.temp_file):
            os.remove(self.temp_file)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_options_creation_minimal(self):
        """
        GIVEN only required input parameter
        WHEN Options(input="/path/to/file") is created
        THEN expect:
            - Instance created successfully
            - All default values are set correctly
            - input field contains the provided path
        """
        options = Options(input=self.temp_file)
        self.assertIsInstance(options, Options)
        self.assertEqual(str(options.input), self.temp_file)
        self.assertEqual(options.output, Path.home())
        self.assertFalse(options.walk)
        self.assertTrue(options.normalize)

    def test_options_creation_with_all_fields(self):
        """
        GIVEN all possible parameters
        WHEN Options instance is created with all fields specified
        THEN expect:
            - Instance created successfully
            - All fields contain provided values
            - No validation errors
        """
        options = Options(
            input=self.temp_file,
            output=self.temp_dir,
            walk=True,
            normalize=False,
            security_checks=False,
            metadata=False,
            structure=False,
            format=OutputFormat.JSON,
            max_threads=2,
            max_memory=4,
            max_vram=4,
            budget_in_usd=10.0,
            normalizers="test",
            max_cpu=50,
            quality_threshold=0.5,
            continue_on_error=False,
            parallel=True,
            follow_symlinks=True,
            include_metadata=False,
            lossy=True,
            normalize_text=False,
            sanitize=False,
            show_options=True,
            show_progress=True,
            verbose=True,
            list_formats=True,
            version=True,
            batch_size=50,
            retries=3
        )
        self.assertIsInstance(options, Options)
        self.assertEqual(str(options.input), self.temp_file)
        self.assertEqual(str(options.output), self.temp_dir)
        self.assertTrue(options.walk)
        self.assertFalse(options.normalize)
        self.assertEqual(options.format, OutputFormat.JSON)
        self.assertEqual(options.max_threads, 2)

    def test_options_input_file_path(self):
        """
        GIVEN a valid file path
        WHEN Options(input="/existing/file.txt") is created
        THEN expect:
            - input field is FilePath type
            - Path exists validation passes
        """
        options = Options(input=self.temp_file)
        self.assertTrue(Path(options.input).exists())
        self.assertTrue(Path(options.input).is_file())

    def test_options_input_directory_path(self):
        """
        GIVEN a valid directory path
        WHEN Options(input="/existing/directory") is created
        THEN expect:
            - input field is DirectoryPath type
            - Directory exists validation passes
        """
        options = Options(input=self.temp_dir)
        self.assertTrue(Path(options.input).exists())
        self.assertTrue(Path(options.input).is_dir())

    def test_options_input_list_of_files(self):
        """
        GIVEN a list of valid file paths
        WHEN Options(input=["/file1.txt", "/file2.txt"]) is created
        THEN expect:
            - input field accepts list[FilePath]
            - All files exist validation passes
        """
        temp_file2 = os.path.join(self.temp_dir, "test_file2.txt")
        with open(temp_file2, 'w') as f:
            f.write("test content 2")
        
        try:
            options = Options(input=[self.temp_file, temp_file2])
            self.assertIsInstance(options.input, list)
            self.assertEqual(len(options.input), 2)
        finally:
            if os.path.exists(temp_file2):
                os.remove(temp_file2)

    def test_options_output_default(self):
        """
        GIVEN no output parameter specified
        WHEN Options instance is created
        THEN expect:
            - output defaults to Path.home()
            - Is DirectoryPath type
        """
        options = Options(input=self.temp_file)
        self.assertEqual(options.output, Path.home())

    def test_options_format_validation(self):
        """
        GIVEN an invalid format value
        WHEN Options(input="/file", format="invalid") is created
        THEN expect:
            - ValidationError is raised
            - Error mentions valid formats
        """
        with self.assertRaises(ValidationError) as context:
            Options(input=self.temp_file, format="invalid")
        self.assertIn("format", str(context.exception).lower())

    def test_options_max_cpu_range(self):
        """
        GIVEN max_cpu value over 100
        WHEN Options(input="/file", max_cpu=150) is created
        THEN expect:
            - ValidationError is raised
            - Error mentions maximum of 100
        """
        with self.assertRaises(ValidationError) as context:
            Options(input=self.temp_file, max_cpu=150)
        self.assertIn("100", str(context.exception))

    def test_options_quality_threshold_range(self):
        """
        GIVEN quality_threshold value over 1.0
        WHEN Options(input="/file", quality_threshold=1.5) is created
        THEN expect:
            - ValidationError is raised
            - Error mentions maximum of 1.0
        """
        with self.assertRaises(ValidationError) as context:
            Options(input=self.temp_file, quality_threshold=1.5)
        self.assertIn("1", str(context.exception))

    # def test_options_aliases(self): # NOTE Removed aliases for now.
    #     """
    #     GIVEN field aliases (o, w, f, p)
    #     WHEN Options instance is created using aliases
    #     THEN expect:
    #         - Aliases map to correct fields
    #         - Values are set properly
    #     """
    #     options = Options(
    #         input=self.temp_file,
    #         o=self.temp_dir,
    #         w=True,
    #         f=OutputFormat.MD,
    #         p=True
    #     )
    #     self.assertEqual(str(options.output), self.temp_dir)
    #     self.assertTrue(options.walk)
    #     self.assertEqual(options.format, OutputFormat.MD)
    #     self.assertTrue(options.parallel)


class TestOptionsToDict(unittest.TestCase):
    """Test the to_dict method of Options."""

    def setUp(self):
        """Create temporary file for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_file = os.path.join(self.temp_dir, "test_file.txt")
        with open(self.temp_file, 'w') as f:
            f.write("test content")

    def tearDown(self):
        """Clean up temporary files."""
        if os.path.exists(self.temp_file):
            os.remove(self.temp_file)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_to_dict_all_fields(self):
        """
        GIVEN an Options instance with all fields set
        WHEN to_dict() is called
        THEN expect:
            - Returns dictionary with all fields
            - Values match instance attributes
            - No missing fields
        """
        options = Options(
            input=self.temp_file,
            output=self.temp_dir,
            walk=True,
            normalize=False,
            format=OutputFormat.JSON
        )
        result_dict = options.to_dict()
        logger.debug(f"Options to_dict result: {result_dict}")
        
        self.assertIsInstance(result_dict, dict)
        self.assertIn('input', result_dict)
        self.assertIn('output', result_dict)
        self.assertIn('walk', result_dict)
        self.assertIn('normalize', result_dict)
        self.assertIn('format', result_dict)

        # Check values match instance attributes
        self.assertEqual(result_dict['walk'], True)
        self.assertEqual(result_dict['normalize'], False)

    def test_to_dict_defaults_only(self):
        """
        GIVEN an Options instance with only defaults
        WHEN to_dict() is called
        THEN expect:
            - Returns dictionary with all fields
            - All values are defaults
        """
        options = Options(input=self.temp_file)
        result_dict = options.to_dict()
        
        self.assertIsInstance(result_dict, dict)
        self.assertEqual(result_dict['walk'], False)
        self.assertEqual(result_dict['normalize'], True)
        self.assertEqual(result_dict['format'], OutputFormat.TXT)


class TestOptionsPrintOptions(unittest.TestCase):
    """Test the print_options method of Options."""

    def setUp(self):
        """Create temporary file for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_file = os.path.join(self.temp_dir, "test_file.txt")
        with open(self.temp_file, 'w') as f:
            f.write("test content")

    def tearDown(self):
        """Clean up temporary files."""
        if os.path.exists(self.temp_file):
            os.remove(self.temp_file)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    @patch('builtins.print')
    def test_print_options_defaults(self, mock_print):
        """
        GIVEN an Options instance
        WHEN print_options(type_="defaults") is called
        THEN expect:
            - Prints default values for all fields
            - Includes field descriptions
            - Output formatted correctly
        """
        options = Options(input=self.temp_file)
        options.print_options(type_="defaults")
        
        mock_print.assert_called()
        # Check that print was called with some expected content
        printed_content = ''.join([str(call.args[0]) for call in mock_print.call_args_list])
        self.assertIn("default", printed_content.lower())

    @patch('builtins.print')
    def test_print_options_current(self, mock_print):
        """
        GIVEN an Options instance with custom values
        WHEN print_options(type_="current") is called
        THEN expect:
            - Prints current values for all fields
            - Shows both current and default values
            - Output formatted correctly
        """
        options = Options(input=self.temp_file, walk=True, normalize=False)
        options.print_options(type_="current")
        
        mock_print.assert_called()
        printed_content = ''.join([str(call.args[0]) for call in mock_print.call_args_list])
        self.assertIn("current", printed_content.lower())

    def test_print_options_invalid_type(self):
        """
        GIVEN an Options instance
        WHEN print_options(type_="invalid") is called
        THEN expect:
            - Raises ValueError
            - Error message mentions valid types
        """
        options = Options(input=self.temp_file)
        with self.assertRaises(ValueError) as context:
            options.print_options(type_="invalid")
        self.assertIn("valid", str(context.exception).lower())


class TestOptionsMakeArgparse(unittest.TestCase):
    """Test the add_arguments_to_parser method of Options."""

    def setUp(self):
        """Create temporary file and parser for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_file = os.path.join(self.temp_dir, "test_file.txt")
        with open(self.temp_file, 'w') as f:
            f.write("test content")
        self.parser = argparse.ArgumentParser()

    def tearDown(self):
        """Clean up temporary files."""
        if os.path.exists(self.temp_file):
            os.remove(self.temp_file)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_make_argparse_all_arguments(self):
        """
        GIVEN an Options instance and ArgumentParser
        WHEN add_arguments_to_parser(parser) is called
        THEN expect:
            - All fields added as arguments
            - Correct types assigned
            - Help text included
        """
        options = Options(input=self.temp_file)
        result_parser = options.add_arguments_to_parser(self.parser)
        
        self.assertIsInstance(result_parser, argparse.ArgumentParser)
        
        # Check that some key arguments were added
        help_text = result_parser.format_help()
        self.assertIn("input", help_text.lower())
        self.assertIn("output", help_text.lower())
        self.assertIn("walk", help_text.lower())

    # def test_make_argparse_aliases(self): # NOTE Removed aliases for now.
    #     """
    #     GIVEN an Options instance and ArgumentParser
    #     WHEN add_arguments_to_parser(parser) is called
    #     THEN expect:
    #         - Fields with aliases have short options
    #         - Short options use first letter of alias
    #         - Long options use full alias
    #     """
    #     options = Options(input=self.temp_file)
    #     result_parser = options.add_arguments_to_parser(self.parser)
        
    #     help_text = result_parser.format_help()
    #     # Check for aliases
    #     self.assertIn("-o", help_text)  # output alias
    #     self.assertIn("-w", help_text)  # walk alias
    #     self.assertIn("-f", help_text)  # format alias
    #     self.assertIn("-p", help_text)  # parallel alias

    def test_make_argparse_defaults(self):
        """
        GIVEN an Options instance and ArgumentParser
        WHEN add_arguments_to_parser(parser) is called
        THEN expect:
            - All arguments have correct defaults
            - Defaults match field definitions
        """
        options = Options(input=self.temp_file)
        result_parser = options.add_arguments_to_parser(self.parser)
        
        # Parse with minimal required args to get defaults
        args = result_parser.parse_args(['--input', self.temp_file])
        print(f"args: {args}")
        
        # Check all default values
        self.assertEqual(args.input, self.temp_file)  # Required field, provided
        self.assertEqual(str(args.output), str(Path.home()))
        self.assertFalse(args.walk)
        self.assertTrue(args.normalize)
        self.assertTrue(args.security_checks)
        self.assertTrue(args.metadata)
        self.assertTrue(args.structure)
        self.assertEqual(args.format, OutputFormat.TXT.value)  # Note: will be string value
        self.assertEqual(args.max_threads, 4)
        self.assertEqual(args.max_memory, 6)
        self.assertEqual(args.max_vram, 6)
        self.assertEqual(args.budget_in_usd, 0.0)
        self.assertEqual(args.normalizers, None)
        self.assertEqual(args.max_cpu, 80)
        self.assertEqual(args.quality_threshold, 0.9)
        self.assertTrue(args.continue_on_error)
        self.assertFalse(args.parallel)
        self.assertFalse(args.follow_symlinks)
        self.assertTrue(args.include_metadata)
        self.assertFalse(args.lossy)
        self.assertTrue(args.normalize_text)
        self.assertTrue(args.sanitize)
        self.assertFalse(args.show_options)
        self.assertFalse(args.show_progress)
        self.assertFalse(args.verbose)
        self.assertFalse(args.list_formats)
        self.assertFalse(args.version)
        self.assertEqual(args.max_batch_size, 100)
        self.assertEqual(args.retries, 0)


if __name__ == '__main__':
    unittest.main()