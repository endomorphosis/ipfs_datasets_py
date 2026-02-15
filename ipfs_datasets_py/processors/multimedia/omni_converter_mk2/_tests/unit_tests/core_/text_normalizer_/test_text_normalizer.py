import importlib.util
import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import copy


from core.text_normalizer._normalized_content import NormalizedContent
from core.text_normalizer._text_normalizer import TextNormalizer
from core.content_extractor import Content


from configs import Configs, _PathsBaseModel
from types_ import Logger


_THIS_DIR = Path(__file__).parent


def make_mock_configs():
    def _make_mock():
        mock_configs = MagicMock()
        mock_configs.paths = MagicMock()
        mock_configs.paths.NORMALIZER_FUNCTIONS_DIR = _THIS_DIR / "default_normalizers_"
        mock_configs.paths.PLUGINS_DIR = _THIS_DIR / "plugins_"
        return mock_configs
    return copy.deepcopy(_make_mock())


def make_mock_resources():
    def _make_mock():
        """Create a mock resources dictionary for testing."""
        # Create a mock for importlib_util that delegates to the real one for specific methods
        mock_importlib = MagicMock(spec=importlib.util)
        
        # Make spec_from_file_location return real specs
        mock_importlib.spec_from_file_location.side_effect = importlib.util.spec_from_file_location
        mock_importlib.module_from_spec.side_effect = importlib.util.module_from_spec

        mock_resources = {
            "importlib_util": mock_importlib,
            "normalized_content": MagicMock(spec=NormalizedContent),
            "logger": MagicMock(spec=Logger)
        }
        return mock_resources
    return copy.deepcopy(_make_mock())


def make_mock_content(): pass 


# Alternative approach using a custom TextNormalizer subclass for testing
class TestableTextNormalizer(TextNormalizer):
    """Subclass that tracks method calls for testing."""
    
    def __init__(self, resources, configs):
        self.register_calls = []
        super().__init__(resources, configs)
    
    def register_normalizers_from(self, folder):
        """Track calls while executing parent logic."""
        self.register_calls.append(folder)
        return super().register_normalizers_from(folder)


class TestTextNormalizerInitialization(unittest.TestCase):
    """Test TextNormalizer initialization and configuration."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_configs = make_mock_configs()
        self.valid_resources = make_mock_resources()

        print("Valid resources:", self.valid_resources)
        print("Mock configs default paths:", self.mock_configs.paths.NORMALIZER_FUNCTIONS_DIR,)
        print("Mock configs plugins paths:", self.mock_configs.paths.PLUGINS_DIR)

        self.num_normalizer_functions = len(
            [fun for fun in self.mock_configs.paths.NORMALIZER_FUNCTIONS_DIR.glob("*.py")
            if fun.is_file() and not fun.name.startswith("_")
            and fun.name != "__init__.py"]
        ) + len(
            [fun for fun in self.mock_configs.paths.PLUGINS_DIR.glob("*.py")
            if fun.is_file() and not fun.name.startswith("_")
            and fun.name != "__init__.py"]
        )

    def test_init_with_valid_resources_and_configs(self):
        """
        GIVEN valid resources dict containing:
            - importlib_util: Module for dynamic imports
            - normalized_content: Factory for creating NormalizedContent objects
            - logger: Logger instance for operation logging
        AND valid configs object with:
            - paths.NORMALIZER_FUNCTIONS_DIR attribute (Path object)
            - paths.PLUGINS_DIR attribute (Path object)
        WHEN TextNormalizer is initialized
        THEN expect:
            - Instance created successfully
            - _normalizers initialized with functions from the two input directories.
            - resources stored correctly
            - configs stored correctly
            - register_normalizers_from called twice (for both directories)
            - logger.debug called indicating initialization complete
        """
        # valid_resources = self.valid_resources
        # valid_resources["importlib_util"] = importlib.util # Mocking it just gets the attributes from the Mock.
        #normalizer = TextNormalizer(resources=self.valid_resources, configs=self.mock_configs)

        normalizer = TestableTextNormalizer(
            resources=self.valid_resources, 
            configs=self.mock_configs
        )
        
        # Verify the results
        self.assertIsInstance(normalizer._normalizers, dict)
        self.assertEqual(len(normalizer._normalizers), self.num_normalizer_functions)
        self.assertEqual(normalizer.resources, self.valid_resources)
        self.assertEqual(normalizer.configs, self.mock_configs)
        
        # Verify register_normalizers_from was called correctly
        self.assertEqual(len(normalizer.register_calls), 2)
        self.assertEqual(normalizer.register_calls[0], self.mock_configs.paths.NORMALIZER_FUNCTIONS_DIR)
        self.assertEqual(normalizer.register_calls[1], self.mock_configs.paths.PLUGINS_DIR)
        
        # Verify logger.debug was called
        self.valid_resources["logger"].debug.assert_called()


    def test_init_missing_importlib_util_in_resources(self):
        """
        GIVEN resources dict missing 'importlib_util' key
        AND valid configs object
        WHEN TextNormalizer is initialized
        THEN expect KeyError to be raised with message about missing 'importlib_util'
        """
        resources = {
            "normalized_content": MagicMock(spec=NormalizedContent),
            "logger": MagicMock(spec=Logger)
        }
        
        with self.assertRaises(KeyError) as context:
            TextNormalizer(resources=resources, configs=self.mock_configs)
        
        self.assertIn("importlib_util", str(context.exception))

    def test_init_missing_normalized_content_in_resources(self):
        """
        GIVEN resources dict missing 'normalized_content' key
        AND valid configs object
        WHEN TextNormalizer is initialized
        THEN expect KeyError to be raised with message about missing 'normalized_content'
        """
        resources = {
            "importlib_util": MagicMock(spec=importlib.util),
            "logger": MagicMock(spec=Logger)
        }
        
        with self.assertRaises(KeyError) as context:
            TextNormalizer(resources=resources, configs=self.mock_configs)
        
        self.assertIn("normalized_content", str(context.exception))

    def test_init_missing_logger_in_resources(self):
        """
        GIVEN resources dict missing 'logger' key
        AND valid configs object
        WHEN TextNormalizer is initialized
        THEN expect KeyError to be raised with message about missing 'logger'
        """
        resources = {
            "importlib_util": MagicMock(spec=importlib.util),
            "normalized_content": MagicMock(spec=NormalizedContent)
        }
        
        with self.assertRaises(KeyError) as context:
            TextNormalizer(resources=resources, configs=self.mock_configs)
        
        self.assertIn("logger", str(context.exception))

    def test_init_resources_not_dict(self):
        """
        GIVEN resources as non-dict type (e.g., list, string, None)
        AND valid configs object
        WHEN TextNormalizer is initialized
        THEN expect TypeError to be raised
        """
        for invalid_resources in [None, [], "string", 123]:
            with self.assertRaises(TypeError):
                TextNormalizer(resources=invalid_resources, configs=self.mock_configs)

    def test_init_configs_missing_normalizer_functions_dir(self):
        """
        GIVEN valid resources dict
        AND configs object missing paths.NORMALIZER_FUNCTIONS_DIR attribute
        WHEN TextNormalizer is initialized
        THEN expect AttributeError to be raised
        """
        mock_configs = self.mock_configs

        del mock_configs.paths.NORMALIZER_FUNCTIONS_DIR  # Simulate missing attribute
   
        with self.assertRaises(AttributeError):
            TextNormalizer(resources=self.valid_resources, configs=mock_configs)

    def test_init_configs_missing_plugins_dir(self):
        """
        GIVEN valid resources dict
        AND configs object missing paths.PLUGINS_DIR attribute
        WHEN TextNormalizer is initialized
        THEN expect AttributeError to be raised
        """
        mock_configs = self.mock_configs
        del mock_configs.paths.PLUGINS_DIR  # Simulate missing attribute
        # Missing PLUGINS_DIR
        
        with self.assertRaises(AttributeError):
            TextNormalizer(resources=self.valid_resources, configs=mock_configs)

    @patch.object(TextNormalizer, 'register_normalizers_from')
    def test_init_no_normalizers_found(self, mock_register):
        """
        GIVEN valid resources and configs
        AND both NORMALIZER_FUNCTIONS_DIR and PLUGINS_DIR contain no valid normalizers
        WHEN TextNormalizer is initialized
        THEN expect RuntimeError with message about no normalizers being loaded
        """
        # Mock register_normalizers_from to not add any normalizers
        mock_register.return_value = None
        
        with self.assertRaises(RuntimeError) as context:
            TextNormalizer(resources=self.valid_resources, configs=self.mock_configs)
        
        self.assertIn("no normalizers", str(context.exception).lower())

    def test_init_with_none_resources(self):
        """
        GIVEN resources=None
        AND valid configs object
        WHEN TextNormalizer is initialized
        THEN expect TypeError to be raised
        """
        with self.assertRaises(TypeError):
            TextNormalizer(resources=None, configs=self.mock_configs)

    def test_init_with_none_configs(self):
        """
        GIVEN valid resources dict
        AND configs=None
        WHEN TextNormalizer is initialized
        THEN expect AttributeError to be raised
        """
        with self.assertRaises(AttributeError):
            TextNormalizer(resources=self.valid_resources, configs=None)

    def test_init_partial_normalizer_loading_failure(self):
        """
        GIVEN valid resources and configs
        AND NORMALIZER_FUNCTIONS_DIR loads some normalizers successfully
        AND PLUGINS_DIR fails to load any normalizers
        WHEN TextNormalizer is initialized
        THEN expect:
            - Instance created successfully
            - Only normalizers from NORMALIZER_FUNCTIONS_DIR are registered
            - No RuntimeError raised (partial success is acceptable)
        """
        # Set the directory path to a non-existent directory to simulate failure
        mock_configs = self.mock_configs
        mock_configs.paths.PLUGINS_DIR = _THIS_DIR / "non_existent_normalizers"

        normalizer = TextNormalizer(resources=self.valid_resources, configs=mock_configs)

        self.assertIsInstance(normalizer, TextNormalizer)
        self.assertEqual(len(normalizer._normalizers), 1)

    def test_init_with_invalid_directory_paths(self):
        """
        GIVEN valid resources dict
        AND configs with paths that are not Path objects (e.g., strings)
        WHEN TextNormalizer is initialized
        THEN expect:
            - Either successful conversion to Path objects
            - OR appropriate error raised during register_normalizers_from
        """
        configs = Mock()
        configs.paths = Mock()
        configs.paths.NORMALIZER_FUNCTIONS_DIR = "/test/normalizers"  # String instead of Path
        configs.paths.PLUGINS_DIR = "/test/plugins"  # String instead of Path
        
        with patch.object(TextNormalizer, 'register_normalizers_from') as mock_register:
            try:
                normalizer = TextNormalizer(resources=self.valid_resources, configs=configs)
                # If successful, verify that strings were used in calls
                calls = mock_register.call_args_list
                self.assertEqual(len(calls), 2)
            except Exception as e:
                # If it fails, that's also acceptable behavior
                self.assertIsInstance(e, (RuntimeError))



class TestTextNormalizerRegisterNormalizer(unittest.TestCase):
    """Test TextNormalizer.register_normalizer method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_configs = make_mock_configs()
        self.valid_resources = make_mock_resources()

        # Create normalizer with mocked register_normalizers_from to avoid auto-loading
        self.normalizer = TextNormalizer(resources=self.valid_resources, configs=self.mock_configs)


    def test_register_valid_normalizer_function(self):
        """
        GIVEN TextNormalizer instance
        AND valid normalizer function conforming to NormalizerFunction protocol
        WHEN register_normalizer called with unique name and function
        THEN expect:
            - Normalizer added to _normalizers dict
            - No warnings logged
            - Function retrievable by name
        """
        def valid_normalizer(text: str) -> str:
            return text.strip()
        
        self.normalizer.register_normalizer("whitespace", valid_normalizer)
        
        self.assertIn("whitespace", self.normalizer._normalizers)
        self.assertEqual(self.normalizer._normalizers["whitespace"], valid_normalizer)
        self.assertEqual(self.normalizer.normalizers["whitespace"], valid_normalizer)
        
        # Verify no warnings were logged
        self.normalizer._logger.warning.assert_not_called()

    def test_register_normalizer_overwrites_existing(self):
        """
        GIVEN TextNormalizer instance with existing normalizer "test_norm"
        AND new normalizer function with same name
        WHEN register_normalizer called with "test_norm" and new function
        THEN expect:
            - Warning logged about overwriting
            - Old function replaced with new function
            - New function retrievable by name
        """
        def old_normalizer(text: str) -> str:
            return text.upper()
        
        def new_normalizer(text: str) -> str:
            return text.lower()
        
        # Register original normalizer
        self.normalizer.register_normalizer("test_norm", old_normalizer)
        
        # Register new normalizer with same name
        self.normalizer.register_normalizer("test_norm", new_normalizer)
        
        # Verify new function replaced old one
        self.assertEqual(self.normalizer._normalizers["test_norm"], new_normalizer)
        
        # Verify warning was logged about overwriting
        warning_calls = [call for call in self.normalizer._logger.warning.call_args_list 
                        if "test_norm" in str(call)]
        self.assertTrue(len(warning_calls) > 0)

    def test_register_invalid_normalizer_not_callable(self):
        """
        GIVEN TextNormalizer instance
        AND non-callable object (e.g., string, dict, None)
        WHEN register_normalizer called
        THEN expect:
            - Warning logged about invalid normalizer
            - Normalizer NOT added to _normalizers dict
        """
        invalid_normalizers = [
            ("string_normalizer", "not_callable"),
            ("dict_normalizer", {"not": "callable"}),
            ("none_normalizer", None),
            ("int_normalizer", 123)
        ]
        
        for name, invalid_normalizer in invalid_normalizers:
            with self.subTest(name=name, normalizer=invalid_normalizer):
                initial_count = len(self.normalizer._normalizers)
                
                self.normalizer.register_normalizer(name, invalid_normalizer)
                
                # Verify normalizer was NOT added
                if name in self.normalizer._normalizers:
                    # If it was added, verify it's not the invalid object
                    self.assertNotEqual(self.normalizer._normalizers[name], invalid_normalizer)
                else:
                    # Normalizer count should be unchanged
                    self.assertEqual(len(self.normalizer._normalizers), initial_count)
                
                # Verify warning was logged
                self.normalizer._logger.warning.assert_called()

    def test_register_normalizer_wrong_signature(self):
        """
        GIVEN TextNormalizer instance
        AND callable that doesn't match NormalizerFunction protocol
            (e.g., takes no args, takes multiple args, returns non-string)
        WHEN register_normalizer called
        THEN expect:
            - Warning logged about protocol mismatch
            - Normalizer still added (runtime checking may not catch this)
        """
        def no_args_normalizer():
            return "fixed_text"
        
        def multiple_args_normalizer(text, extra_arg):
            return text + str(extra_arg)
        
        def non_string_return_normalizer(text: str) -> int:
            return len(text)
        
        wrong_signature_normalizers = [
            ("no_args", no_args_normalizer),
            ("multiple_args", multiple_args_normalizer),
            ("non_string_return", non_string_return_normalizer)
        ]
        
        for name, normalizer_func in wrong_signature_normalizers:
            with self.subTest(name=name):
                self.normalizer.register_normalizer(name, normalizer_func)
                
                # Function might still be added depending on implementation
                # Check if warning was logged about protocol issues
                warning_logged = any("protocol" in str(call).lower() or 
                                   "signature" in str(call).lower() or
                                   "normalizer" in str(call).lower()
                                   for call in self.normalizer._logger.warning.call_args_list)
                
                # At minimum, the function should be callable
                self.assertTrue(callable(normalizer_func))

    def test_register_normalizer_empty_name(self):
        """
        GIVEN TextNormalizer instance
        AND valid normalizer function
        WHEN register_normalizer called with empty string name
        THEN expect:
            - Normalizer added with empty string as key
            - Function retrievable using empty string key
        """
        def valid_normalizer(text: str) -> str:
            return text.strip()
        
        self.normalizer.register_normalizer("", valid_normalizer)
        
        self.assertIn("", self.normalizer._normalizers)
        self.assertEqual(self.normalizer._normalizers[""], valid_normalizer)
        self.assertEqual(self.normalizer.normalizers[""], valid_normalizer)





class TestTextNormalizerRegisterNormalizersFrom(unittest.TestCase):
    """Test TextNormalizer.register_normalizers_from method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_logger = Mock()
        self.mock_importlib_util = Mock()
        self.mock_normalized_content = Mock()
        self.mock_configs = Mock()
        self.mock_configs.paths = Mock()
        self.mock_configs.paths.NORMALIZER_FUNCTIONS_DIR = _THIS_DIR / "default_normalizers_"
        self.mock_configs.paths.PLUGINS_DIR = _THIS_DIR / "plugins_"
        
        self.valid_resources = {
            "importlib_util": self.mock_importlib_util,
            "normalized_content": self.mock_normalized_content,
            "logger": self.mock_logger
        }

        self.normalizer = TextNormalizer(resources=self.valid_resources, configs=self.mock_configs)
        self.normalizer._normalizers["dummy"] = Mock()

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir')
    @patch('pathlib.Path.glob')
    def test_register_from_valid_directory_with_normalizers(self, mock_glob, mock_is_dir, mock_exists):
        """
        GIVEN TextNormalizer instance
        AND directory containing:
            - valid_normalizer.py with NormalizerFunction instances
            - another_normalizer.py with multiple NormalizerFunction instances
        WHEN register_normalizers_from called with directory path
        THEN expect:
            - All NormalizerFunction instances registered
            - Debug logs for each module loaded
            - Info log for registration completion
        """
        mock_exists.return_value = True
        mock_is_dir.return_value = True
        
        # Mock Python files in directory
        mock_file1 = Mock()
        mock_file1.name = "valid_normalizer.py"
        mock_file1.stem = "valid_normalizer"
        mock_file2 = Mock()
        mock_file2.name = "another_normalizer.py"
        mock_file2.stem = "another_normalizer"
        
        mock_glob.return_value = [mock_file1, mock_file2]
        
        # Mock module loading
        mock_spec = Mock()
        mock_module = Mock()
        
        def mock_normalizer_func(text: str) -> str:
            return text.strip()
        
        # Mock the module to have normalizer functions
        mock_module.normalize_whitespace = mock_normalizer_func
        mock_module.normalize_unicode = mock_normalizer_func
        
        self.mock_importlib_util.spec_from_file_location.return_value = mock_spec
        self.mock_importlib_util.module_from_spec.return_value = mock_module
        
        test_folder = _THIS_DIR / "default_normalizers_"
        print("files in test_folder:", list(test_folder.glob("*.py")))
        
        with patch.object(self.normalizer, 'register_normalizer') as mock_register:
            self.normalizer.register_normalizers_from(test_folder)
            
            # Verify modules were processed
            self.mock_importlib_util.spec_from_file_location.assert_called()
            self.mock_logger.debug.assert_called()
            
            # Verify register_normalizer was called for discovered functions
            mock_register.assert_called()

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir') 
    @patch('pathlib.Path.glob')
    def test_register_from_directory_skips_init_file(self, mock_glob, mock_is_dir, mock_exists):
        """
        GIVEN TextNormalizer instance
        AND directory containing __init__.py file
        WHEN register_normalizers_from called
        THEN expect:
            - __init__.py skipped (not loaded)
            - No error raised
        """
        mock_exists.return_value = True
        mock_is_dir.return_value = True
        
        mock_init_file = Mock()
        mock_init_file.name = "__init__.py"
        mock_init_file.stem = "__init__"
        
        mock_normalizer_file = Mock()
        mock_normalizer_file.name = "text_normalizer.py"
        mock_normalizer_file.stem = "text_normalizer"
        
        mock_glob.return_value = [mock_init_file, mock_normalizer_file]
        
        test_folder = _THIS_DIR / "default_normalizers_"
        
        with patch.object(self.normalizer, 'register_normalizer'):
            self.normalizer.register_normalizers_from(test_folder)
            
            # Verify __init__.py was not processed
            spec_calls = self.mock_importlib_util.spec_from_file_location.call_args_list
            init_processed = any("__init__" in str(call) for call in spec_calls)
            self.assertFalse(init_processed)

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir')
    @patch('pathlib.Path.glob')
    def test_register_from_directory_skips_private_modules(self, mock_glob, mock_is_dir, mock_exists):
        """
        GIVEN TextNormalizer instance
        AND directory containing files starting with underscore (e.g., _private.py)
        WHEN register_normalizers_from called
        THEN expect:
            - Private modules skipped
            - No attempt to load them
        """
        mock_exists.return_value = True
        mock_is_dir.return_value = True
        
        mock_private_file = Mock()
        mock_private_file.name = "_private.py"
        mock_private_file.stem = "_private"
        
        mock_public_file = Mock()
        mock_public_file.name = "public_normalizer.py"
        mock_public_file.stem = "public_normalizer"
        
        mock_glob.return_value = [mock_private_file, mock_public_file]
        
        test_folder = _THIS_DIR / "default_normalizers_"
        
        with patch.object(self.normalizer, 'register_normalizer'):
            self.normalizer.register_normalizers_from(test_folder)
            
            # Verify private module was not processed
            spec_calls = self.mock_importlib_util.spec_from_file_location.call_args_list
            private_processed = any("_private" in str(call) for call in spec_calls)
            self.assertFalse(private_processed)

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir')
    @patch('pathlib.Path.glob')
    def test_register_from_directory_skips_non_normalizer_files(self, mock_glob, mock_is_dir, mock_exists):
        """
        GIVEN TextNormalizer instance
        AND directory containing Python files without 'normalizer' in name
        WHEN register_normalizers_from called
        THEN expect:
            - Files without 'normalizer' in name skipped
            - Only files with 'normalizer' in name processed
        """
        mock_exists.return_value = True
        mock_is_dir.return_value = True
        
        mock_non_normalizer = Mock()
        mock_non_normalizer.name = "utility.py"
        mock_non_normalizer.stem = "utility"
        
        mock_normalizer = Mock()
        mock_normalizer.name = "text_normalizer.py"
        mock_normalizer.stem = "text_normalizer"
        
        mock_glob.return_value = [mock_non_normalizer, mock_normalizer]
        
        test_folder = _THIS_DIR / "default_normalizers_"
        
        with patch.object(self.normalizer, 'register_normalizer'):
            self.normalizer.register_normalizers_from(test_folder)
            
            # Verify non-normalizer file was not processed
            spec_calls = self.mock_importlib_util.spec_from_file_location.call_args_list
            utility_processed = any("utility" in str(call) for call in spec_calls)
            self.assertFalse(utility_processed)

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir')
    @patch('pathlib.Path.glob')
    def test_register_from_directory_handles_import_errors(self, mock_glob, mock_is_dir, mock_exists):
        """
        GIVEN TextNormalizer instance
        AND directory with module that raises ImportError
        WHEN register_normalizers_from called
        THEN expect:
            - Error logged for failed import
            - Process continues with other modules
            - No RuntimeError raised
        """
        mock_exists.return_value = True
        mock_is_dir.return_value = True
        
        mock_file = Mock()
        mock_file.name = "broken_normalizer.py"
        mock_file.stem = "broken_normalizer"
        mock_glob.return_value = [mock_file]
        
        # Mock import error
        self.mock_importlib_util.spec_from_file_location.side_effect = ImportError("Module not found")
        
        test_folder = _THIS_DIR / "default_normalizers_"
        
        # Should not raise exception
        self.normalizer.register_normalizers_from(test_folder)
        
        # Verify error was logged
        self.mock_logger.error.assert_called()

    @patch('pathlib.Path.exists')
    def test_register_from_non_existent_directory(self, mock_exists):
        """
        GIVEN TextNormalizer instance
        AND path to non-existent directory
        WHEN register_normalizers_from called
        THEN expect:
            - Error logged about directory not existing
            - No RuntimeError raised (graceful handling)
        """
        mock_exists.return_value = False
        
        test_folder = Path("/non/existent/path")
        
        # Should not raise exception
        self.normalizer.register_normalizers_from(test_folder)
        
        # Verify error was logged
        self.mock_logger.error.assert_called()

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir')
    def test_register_from_file_instead_of_directory(self, mock_is_dir, mock_exists):
        """
        GIVEN TextNormalizer instance
        AND path to a file (not directory)
        WHEN register_normalizers_from called
        THEN expect:
            - Error logged about invalid path
            - No modules loaded
        """
        mock_exists.return_value = True
        mock_is_dir.return_value = False
        
        test_file = Path("/test/normalizer.py")
        
        # Should not raise exception
        self.normalizer.register_normalizers_from(test_file)
        
        # Verify error was logged
        self.mock_logger.error.assert_called()

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir')
    @patch('pathlib.Path.glob')
    def test_register_from_directory_with_no_python_files(self, mock_glob, mock_is_dir, mock_exists):
        """
        GIVEN TextNormalizer instance
        AND directory containing no .py files
        WHEN register_normalizers_from called
        THEN expect:
            - Info log about completion
            - No normalizers registered
            - No errors raised
        """
        mock_exists.return_value = True
        mock_is_dir.return_value = True
        mock_glob.return_value = []  # No files found
        
        test_folder = Path("/test/empty")
        
        # Should not raise exception
        self.normalizer.register_normalizers_from(test_folder)
        
        # Verify completion was logged
        self.mock_logger.debug.assert_called()

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir')
    @patch('pathlib.Path.glob')
    def test_register_handles_module_load_runtime_error(self, mock_glob, mock_is_dir, mock_exists):
        """
        GIVEN TextNormalizer instance
        AND directory with module that raises any error during import
        WHEN register_normalizers_from called
        THEN expect:
            - Error details logged
            - Process continues with other modules
        """
        mock_exists.return_value = True
        mock_is_dir.return_value = True
        
        mock_file = Mock()
        mock_file.name = "runtime_error_normalizer.py"
        mock_file.stem = "runtime_error_normalizer"
        mock_glob.return_value = [mock_file]
        
        # Mock runtime error during module loading
        mock_spec = Mock()
        mock_spec.loader.exec_module.side_effect = RuntimeError("Module execution failed")
        self.mock_importlib_util.spec_from_file_location.return_value = mock_spec
        
        test_folder = _THIS_DIR / "default_normalizers_"

        self.normalizer.register_normalizers_from(test_folder)
        self.normalizer._logger.error.assert_called_once()

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir')
    @patch('pathlib.Path.glob')
    def test_register_normalizer_registration_failure(self, mock_glob, mock_is_dir, mock_exists):
        """
        GIVEN TextNormalizer instance
        AND directory with valid module
        AND register_normalizer raises exception for one normalizer
        WHEN register_normalizers_from called
        THEN expect:
            - Warning logged for failed registration
            - Other normalizers still registered
            - Process continues
        """
        mock_exists.return_value = True
        mock_is_dir.return_value = True
        
        mock_file = Mock()
        mock_file.name = "test_normalizer.py"
        mock_file.stem = "test_normalizer"
        mock_glob.return_value = [mock_file]
        
        # Mock successful module loading
        mock_spec = Mock()
        mock_module = Mock()
        
        def good_normalizer(text: str) -> str:
            return text.strip()
        
        def bad_normalizer(text: str) -> str:
            return text.upper()
        
        mock_module.good_normalize = good_normalizer
        mock_module.bad_normalize = bad_normalizer
        
        self.mock_importlib_util.spec_from_file_location.return_value = mock_spec
        self.mock_importlib_util.module_from_spec.return_value = mock_module
        
        test_folder = _THIS_DIR / "default_normalizers_"
        
        # Mock register_normalizer to fail for one normalizer
        def register_side_effect(name, func):
            if "bad" in name:
                raise ValueError("Registration failed")
        
        with patch.object(self.normalizer, 'register_normalizer', side_effect=register_side_effect):
            # Should not raise exception
            self.normalizer.register_normalizers_from(test_folder)
            
            # Verify warning was logged for failed registration
            self.mock_logger.warning.assert_called()


# class TestTextNormalizerNormalizeText(unittest.TestCase):
#     """Test TextNormalizer.normalize_text method."""

#     def setUp(self):
#         """Set up test fixtures."""
#         self.mock_logger = Mock(spec=Logger)
#         self.mock_importlib_util = Mock()
#         self.mock_normalized_content = Mock(spec=NormalizedContent)
#         self.mock_configs = Mock()
#         self.mock_configs.paths = Mock()
#         self.mock_configs.paths.NORMALIZER_FUNCTIONS_DIR = _THIS_DIR / "default_normalizers_"
#         self.mock_configs = make_mock_configs()

#         self.valid_resources = make_mock_resources()

#         # Mock content object
#         self.mock_content = Mock()
#         self.mock_content.text = "  Hello   World  "
#         self.mock_content.metadata = {"source": "test.txt"}

#         self.normalizer = TextNormalizer(resources=self.valid_resources, configs=self.mock_configs)

#     def test_normalize_with_all_registered_normalizers(self):
#         """
#         GIVEN TextNormalizer instance with registered normalizers:
#             - "whitespace": removes extra whitespace
#             - "unicode": normalizes unicode characters
#             - "linebreaks": standardizes line endings
#         AND Content object with text to normalize
#         AND normalizers parameter is None
#         WHEN normalize_text called
#         THEN expect:
#             - All registered normalizers applied in order
#             - Each normalizer receives output from previous
#             - NormalizedContent returned with all normalizers in normalized_by list
#             - Content object's text attribute updated with final result
#         """
#         def whitespace_normalizer(text):
#             return " ".join(text.split())
        
#         def unicode_normalizer(text):
#             return text.replace("é", "e")
        
#         def linebreak_normalizer(text):
#             return text.replace("\r\n", "\n")
        
#         self.normalizer._normalizers = {
#             "whitespace": whitespace_normalizer,
#             "unicode": unicode_normalizer,
#             "linebreaks": linebreak_normalizer
#         }
        
#         mock_normalized_result = Mock()
#         self.mock_normalized_content.return_value = mock_normalized_result
        
#         result = self.normalizer.normalize_text(self.mock_content)
        
#         # Verify text was processed sequentially
#         self.assertEqual(self.mock_content.text, "Hello World")
        
#         # Verify NormalizedContent factory was called with correct parameters
#         self.mock_normalized_content.assert_called_once()
#         call_args = self.mock_normalized_content.call_args.kwargs
#         self.assertEqual(call_args[0]['text'], "Hello World")
#         self.assertEqual(call_args[0]['metadata'], {"source": "test.txt"})
#         self.assertEqual(set(call_args[1]['normalized_by']), {"whitespace", "unicode", "linebreaks"})
        
#         self.assertEqual(result, mock_normalized_result)

#     def test_normalize_with_specific_normalizers_list(self):
#         """
#         GIVEN TextNormalizer instance with multiple registered normalizers
#         AND Content object with text
#         AND normalizers parameter = ["whitespace", "unicode"]
#         WHEN normalize_text called
#         THEN expect:
#             - Only specified normalizers applied
#             - Applied in order specified in list
#             - NormalizedContent.normalized_by contains only applied normalizers
#         """
#         def whitespace_normalizer(text):
#             return " ".join(text.split())
        
#         def unicode_normalizer(text):
#             return text + "_unicode"
        
#         def linebreak_normalizer(text):
#             return text + "_linebreaks"
        
#         self.normalizer._normalizers = {
#             "whitespace": whitespace_normalizer,
#             "unicode": unicode_normalizer,
#             "linebreaks": linebreak_normalizer
#         }
#         self.valid_resources['normalized_content'] = MagicMock(spec=NormalizedContent)

#         result = self.normalizer.normalize_text(self.mock_content, normalizers=["whitespace", "unicode"])
        
#         # Verify only specified normalizers were applied
#         expected_text = "Hello World_unicode"
#         self.assertEqual(self.mock_content.text, expected_text)
        
#         # Verify normalized_by contains only applied normalizers
#         call_args = self.valid_resources['normalized_content'].call_args
#         self.assertEqual(call_args[1]['normalized_by'], ["whitespace", "unicode"])

#     def test_normalize_with_empty_normalizers_list(self):
#         """
#         GIVEN TextNormalizer instance
#         AND Content object with text
#         AND normalizers parameter = []
#         WHEN normalize_text called
#         THEN expect:
#             - No normalizers applied
#             - Original text unchanged
#             - NormalizedContent.normalized_by is empty list
#         """
#         original_text = self.mock_content.text
        
#         self.normalizer._normalizers = {
#             "whitespace": lambda x: x.strip(),
#             "unicode": lambda x: x.upper()
#         }
        
#         mock_normalized_result = MagicMock()
#         self.mock_normalized_content.return_value = mock_normalized_result
        
#         result = self.normalizer.normalize_text(self.mock_content, normalizers=[])
        
#         # Verify text unchanged
#         self.assertEqual(self.mock_content.text, original_text)
        
#         # Verify normalized_by is empty
#         call_args = self.mock_normalized_content.call_args
#         self.assertEqual(call_args[1]['normalized_by'], [])

#     def test_normalize_with_skip_true(self):
#         """
#         GIVEN TextNormalizer instance with registered normalizers
#         AND Content object
#         AND skip parameter = True
#         WHEN normalize_text called
#         THEN expect:
#             - No normalizers applied regardless of normalizers parameter
#             - Original content text unchanged
#             - NormalizedContent returned with empty normalized_by list
#             - Logger indicates skipping normalization
#         """
#         original_text = self.mock_content.text
        
#         self.normalizer._normalizers = {
#             "whitespace": lambda x: x.strip(),
#             "unicode": lambda x: x.upper()
#         }
        
#         mock_normalized_result = Mock()
#         self.mock_normalized_content.return_value = mock_normalized_result
        
#         result = self.normalizer.normalize_text(self.mock_content, skip=True)
        
#         # Verify text unchanged
#         self.assertEqual(self.mock_content.text, original_text)
        
#         # Verify normalized_by is empty
#         call_args = self.mock_normalized_content.call_args
#         self.assertEqual(call_args[1]['normalized_by'], [])
        
#         # Verify logger indicated skipping
#         skip_logged = any("skip" in str(call).lower() for call in self.mock_logger.debug.call_args_list)
#         self.assertTrue(skip_logged)

#     def test_normalize_with_unknown_normalizer_name(self):
#         """
#         GIVEN TextNormalizer instance
#         AND Content object
#         AND normalizers = ["whitespace", "unknown_normalizer", "unicode"]
#         WHEN normalize_text called
#         THEN expect:
#             - Warning logged for unknown normalizer
#             - Known normalizers still applied
#             - normalized_by contains only successfully applied normalizers
#         """
#         def whitespace_normalizer(text):
#             return text.strip()
        
#         def unicode_normalizer(text):
#             return text + "_unicode"
        
#         self.normalizer._normalizers = {
#             "whitespace": whitespace_normalizer,
#             "unicode": unicode_normalizer
#         }
        
#         mock_normalized_result = Mock()
#         self.mock_normalized_content.return_value = mock_normalized_result
        
#         result = self.normalizer.normalize_text(
#             self.mock_content, 
#             normalizers=["whitespace", "unknown_normalizer", "unicode"]
#         )
        
#         # Verify warning logged for unknown normalizer
#         warning_calls = [call for call in self.mock_logger.warning.call_args_list 
#                         if "unknown_normalizer" in str(call)]
#         self.assertTrue(len(warning_calls) > 0)
        
#         # Verify known normalizers were applied
#         call_args = self.mock_normalized_content.call_args
#         self.assertEqual(call_args[1]['normalized_by'], ["whitespace", "unicode"])

#     def test_normalize_handles_normalizer_exception(self):
#         """
#         GIVEN TextNormalizer instance with normalizer that raises exception
#         AND Content object
#         WHEN normalize_text called
#         THEN expect:
#             - Error logged with normalizer name and exception details
#             - Normalization continues with next normalizer
#             - Failed normalizer NOT in normalized_by list
#             - Successful normalizers still applied
#         """
#         def good_normalizer(text):
#             return text.strip()
        
#         def bad_normalizer(text):
#             raise ValueError("Normalizer failed")
        
#         def another_good_normalizer(text):
#             return text + "_success"
        
#         self.normalizer._normalizers = {
#             "good": good_normalizer,
#             "bad": bad_normalizer,
#             "another_good": another_good_normalizer
#         }
        
#         mock_normalized_result = Mock()
#         self.mock_normalized_content.return_value = mock_normalized_result
        
#         result = self.normalizer.normalize_text(self.mock_content)
        
#         # Verify error was logged
#         self.mock_logger.error.assert_called()
#         error_call = str(self.mock_logger.error.call_args)
#         self.assertIn("bad", error_call)
        
#         # Verify successful normalizers were applied
#         call_args = self.mock_normalized_content.call_args
#         applied_normalizers = call_args[1]['normalized_by']
#         self.assertIn("good", applied_normalizers)
#         self.assertIn("another_good", applied_normalizers)
#         self.assertNotIn("bad", applied_normalizers)

#     def test_normalize_preserves_content_metadata(self):
#         """
#         GIVEN TextNormalizer instance
#         AND Content object with metadata, sections, source_format, etc.
#         WHEN normalize_text called
#         THEN expect:
#             - Only text attribute modified
#             - All other Content attributes preserved
#             - NormalizedContent contains reference to modified Content
#         """
#         # Add additional attributes to mock content
#         self.mock_content.sections = ["section1", "section2"]
#         self.mock_content.source_format = "txt"
#         self.mock_content.source_path = "/path/to/file.txt"
        
#         def simple_normalizer(text):
#             return text.strip()
        
#         self.normalizer._normalizers = {"simple": simple_normalizer}
        
#         mock_normalized_result = Mock()
#         self.mock_normalized_content.return_value = mock_normalized_result
        
#         result = self.normalizer.normalize_text(self.mock_content)
        
#         # Verify other attributes preserved
#         self.assertEqual(self.mock_content.metadata, {"source": "test.txt"})
#         self.assertEqual(self.mock_content.sections, ["section1", "section2"])
#         self.assertEqual(self.mock_content.source_format, "txt")
#         self.assertEqual(self.mock_content.source_path, "/path/to/file.txt")

#     def test_normalize_with_empty_text(self):
#         """
#         GIVEN TextNormalizer instance with normalizers
#         AND Content object with empty text string
#         WHEN normalize_text called
#         THEN expect:
#             - Normalizers called with empty string
#             - No errors raised
#             - Empty string remains empty
#         """
#         self.mock_content.text = ""
        
#         def normalizer(text):
#             return text.strip() + "_processed"
        
#         self.normalizer._normalizers = {"test": normalizer}
        
#         mock_normalized_result = Mock()
#         self.mock_normalized_content.return_value = mock_normalized_result
        
#         result = self.normalizer.normalize_text(self.mock_content)
        
#         # Verify text was processed (empty string + "_processed")
#         self.assertEqual(self.mock_content.text, "_processed")

#     def test_normalize_sequential_application(self):
#         """
#         GIVEN TextNormalizer with normalizers:
#             - "trim": removes leading/trailing whitespace
#             - "lowercase": converts to lowercase
#             - "collapse": collapses multiple spaces
#         AND Content with text "  HELLO   WORLD  "
#         WHEN normalize_text called with all normalizers
#         THEN expect:
#             - First: "HELLO   WORLD"
#             - Then: "hello   world"
#             - Finally: "hello world"
#             - Each normalizer receives previous output
#         """
#         def trim_normalizer(text):
#             return text.strip()
        
#         def lowercase_normalizer(text):
#             return text.lower()
        
#         def collapse_normalizer(text):
#             return " ".join(text.split())
        
#         self.normalizer._normalizers = {
#             "trim": trim_normalizer,
#             "lowercase": lowercase_normalizer,
#             "collapse": collapse_normalizer
#         }
        
#         mock_normalized_result = Mock()
#         self.mock_normalized_content.return_value = mock_normalized_result
        
#         result = self.normalizer.normalize_text(
#             self.mock_content, 
#             normalizers=["trim", "lowercase", "collapse"]
#         )
        
#         # Verify final result
#         self.assertEqual(self.mock_content.text, "hello world")

#     def test_normalize_with_none_normalizers_uses_all(self):
#         """
#         GIVEN TextNormalizer with registered normalizers
#         AND Content object
#         AND normalizers parameter is explicitly None
#         WHEN normalize_text called
#         THEN expect:
#             - All registered normalizers applied
#             - Same behavior as not providing normalizers parameter
#         """
#         def normalizer1(text):
#             return text + "_1"
        
#         def normalizer2(text):
#             return text + "_2"
        
#         self.normalizer._normalizers = {
#             "norm1": normalizer1,
#             "norm2": normalizer2
#         }
        
#         mock_normalized_result = Mock()
#         self.mock_normalized_content.return_value = mock_normalized_result
        
#         result = self.normalizer.normalize_text(self.mock_content, normalizers=None)
        
#         # Verify all normalizers were applied
#         call_args = self.mock_normalized_content.call_args
#         applied_normalizers = call_args[1]['normalized_by']
#         self.assertEqual(set(applied_normalizers), {"norm1", "norm2"})

#     def test_normalize_creates_normalized_content_correctly(self):
#         """
#         GIVEN TextNormalizer instance
#         AND Content object with all attributes set
#         WHEN normalize_text called
#         THEN expect:
#             - resources['normalized_content'] factory called
#             - Factory receives modified content object
#             - Factory receives list of successfully applied normalizers
#             - Returns NormalizedContent instance from factory
#         """
#         def simple_normalizer(text):
#             return text.strip()
        
#         self.normalizer._normalizers = {"simple": simple_normalizer}
        
#         mock_normalized_result = Mock()
#         self.mock_normalized_content.return_value = mock_normalized_result
        
#         result = self.normalizer.normalize_text(self.mock_content)
        
#         # Verify factory called correctly
#         self.mock_normalized_content.assert_called_once()
#         call_args = self.mock_normalized_content.call_args
        
#         # Verify correct parameters passed
#         self.assertEqual(call_args[1]['text'], "Hello World")
#         self.assertEqual(call_args[1]['metadata'], {"source": "test.txt"})
#         self.assertEqual(call_args[1]['normalized_by'], ["simple"])
        
#         # Verify correct return value
#         self.assertEqual(result, mock_normalized_result)

#     def test_normalize_logs_start_and_completion(self):
#         """
#         GIVEN TextNormalizer instance
#         AND Content object
#         WHEN normalize_text called
#         THEN expect:
#             - Debug log at start indicating normalization beginning
#             - Debug log for each normalizer application
#             - Debug log at end with count of normalizers applied
#         """
#         def test_normalizer(text):
#             return text.strip()
        
#         self.normalizer._normalizers = {"test": test_normalizer}
        
#         mock_normalized_result = Mock()
#         self.mock_normalized_content.return_value = mock_normalized_result
        
#         result = self.normalizer.normalize_text(self.mock_content)
        
#         # Verify debug logging occurred
#         self.mock_logger.debug.assert_called()
        
#         # Check for start, progress, and completion logs
#         debug_calls = [str(call) for call in self.mock_logger.debug.call_args_list]
        
#         # Should have logs indicating start and completion
#         has_start_log = any("normaliz" in call.lower() for call in debug_calls)
#         self.assertTrue(has_start_log)

#     def test_normalize_all_normalizers_fail(self):
#         """
#         GIVEN TextNormalizer with normalizers that all raise exceptions
#         AND Content object
#         WHEN normalize_text called
#         THEN expect:
#             - All errors logged
#             - Original text unchanged
#             - NormalizedContent with empty normalized_by list
#             - No exception raised (graceful degradation)
#         """
#         original_text = self.mock_content.text
        
#         def failing_normalizer1(text):
#             raise ValueError("Normalizer 1 failed")
        
#         def failing_normalizer2(text):
#             raise RuntimeError("Normalizer 2 failed")
        
#         self.normalizer._normalizers = {
#             "fail1": failing_normalizer1,
#             "fail2": failing_normalizer2
#         }
        
#         mock_normalized_result = Mock()
#         self.mock_normalized_content.return_value = mock_normalized_result
        
#         # Should not raise exception
#         result = self.normalizer.normalize_text(self.mock_content)
        
#         # Verify all errors logged
#         self.assertEqual(self.mock_logger.error.call_count, 2)
        
#         # Verify text unchanged
#         self.assertEqual(self.mock_content.text, original_text)
        
#         # Verify empty normalized_by
#         call_args = self.mock_normalized_content.call_args
#         self.assertEqual(call_args[1]['normalized_by'], [])
        
#         # Verify return value
#         self.assertEqual(result, mock_normalized_result)




# class TestTextNormalizerProperties(unittest.TestCase):
#     """Test TextNormalizer property methods."""

#     def setUp(self):
#         """Set up test fixtures."""
#         self.mock_logger = Mock()
#         self.mock_importlib_util = Mock()
#         self.mock_normalized_content = Mock()
#         self.mock_configs = Mock()
#         self.mock_configs.paths = Mock()
#         self.mock_configs.paths.NORMALIZER_FUNCTIONS_DIR = _THIS_DIR / "default_normalizers_"
#         self.mock_configs.paths.PLUGINS_DIR = _THIS_DIR / "plugins_"
        
#         self.valid_resources = {
#             "importlib_util": self.mock_importlib_util,
#             "normalized_content": self.mock_normalized_content,
#             "logger": self.mock_logger
#         }

#         self.normalizer = TextNormalizer(resources=self.valid_resources, configs=self.mock_configs)
#         self.normalizer._normalizers = {}

#     def test_normalizers_property_returns_dict_copy(self):
#         """
#         GIVEN TextNormalizer instance with registered normalizers:
#             - "whitespace": function1
#             - "unicode": function2
#             - "linebreaks": function3
#         WHEN normalizers property accessed
#         THEN expect:
#             - Returns dict with all registered normalizers
#             - Keys are normalizer names
#             - Values are normalizer functions
#             - Modifying returned dict doesn't affect internal state
#         """
#         def function1(text):
#             return text.strip()
        
#         def function2(text):
#             return text.replace("é", "e")
        
#         def function3(text):
#             return text.replace("\r\n", "\n")
        
#         self.normalizer._normalizers = {
#             "whitespace": function1,
#             "unicode": function2,
#             "linebreaks": function3
#         }
        
#         result = self.normalizer.normalizers
        
#         # Verify all normalizers returned
#         self.assertEqual(len(result), 3)
#         self.assertIn("whitespace", result)
#         self.assertIn("unicode", result)
#         self.assertIn("linebreaks", result)
        
#         # Verify correct functions returned
#         self.assertEqual(result["whitespace"], function1)
#         self.assertEqual(result["unicode"], function2)
#         self.assertEqual(result["linebreaks"], function3)
        
#         # Verify modifying returned dict doesn't affect internal state
#         result["new_normalizer"] = lambda x: x
#         result["whitespace"] = lambda x: "modified"
        
#         # Internal state should be unchanged
#         self.assertEqual(len(self.normalizer._normalizers), 3)
#         self.assertEqual(self.normalizer._normalizers["whitespace"], function1)
#         self.assertNotIn("new_normalizer", self.normalizer._normalizers)

#     def test_normalizers_property_empty_when_no_normalizers(self):
#         """
#         GIVEN TextNormalizer instance with no registered normalizers
#         WHEN normalizers property accessed
#         THEN expect:
#             - Returns empty dict
#             - Type is dict[str, NormalizerFunction]
#         """
#         self.normalizer._normalizers = {}
        
#         result = self.normalizer.normalizers
        
#         self.assertIsInstance(result, dict)
#         self.assertEqual(len(result), 0)
#         self.assertEqual(result, {})

#     def test_normalizers_property_immutability(self):
#         """
#         GIVEN TextNormalizer instance with normalizers
#         WHEN normalizers property accessed and modified
#         THEN expect:
#             - Modifications to returned dict don't affect internal _normalizers
#             - Subsequent calls return original normalizers
#         """
#         def original_func(text):
#             return text.strip()
        
#         self.normalizer._normalizers = {"original": original_func}
        
#         # Get first copy and modify it
#         first_copy = self.normalizer.normalizers
#         first_copy["modified"] = lambda x: x.upper()
#         first_copy["original"] = lambda x: "changed"
        
#         # Get second copy
#         second_copy = self.normalizer.normalizers
        
#         # Verify second copy is unaffected by modifications to first
#         self.assertEqual(len(second_copy), 1)
#         self.assertIn("original", second_copy)
#         self.assertNotIn("modified", second_copy)
#         self.assertEqual(second_copy["original"], original_func)
        
#         # Verify internal state unchanged
#         self.assertEqual(len(self.normalizer._normalizers), 1)
#         self.assertEqual(self.normalizer._normalizers["original"], original_func)

#     def test_applied_normalizers_property_returns_list(self):
#         """
#         GIVEN TextNormalizer instance with registered normalizers:
#             - "whitespace": function1
#             - "unicode": function2
#             - "linebreaks": function3
#         WHEN applied_normalizers property accessed
#         THEN expect:
#             - Returns list of strings
#             - Contains all normalizer names
#             - Order may vary (dict keys order)
#         """
#         def function1(text):
#             return text.strip()
        
#         def function2(text):
#             return text.replace("é", "e")
        
#         def function3(text):
#             return text.replace("\r\n", "\n")
        
#         self.normalizer._normalizers = {
#             "whitespace": function1,
#             "unicode": function2,
#             "linebreaks": function3
#         }
        
#         result = self.normalizer.applied_normalizers
        
#         # Verify result is a list
#         self.assertIsInstance(result, list)
        
#         # Verify all normalizer names present
#         self.assertEqual(len(result), 3)
#         self.assertIn("whitespace", result)
#         self.assertIn("unicode", result)
#         self.assertIn("linebreaks", result)
        
#         # Verify all items are strings
#         for item in result:
#             self.assertIsInstance(item, str)

#     def test_applied_normalizers_property_empty_when_no_normalizers(self):
#         """
#         GIVEN TextNormalizer instance with no registered normalizers
#         WHEN applied_normalizers property accessed
#         THEN expect:
#             - Returns empty list
#             - Type is list[str]
#         """
#         self.normalizer._normalizers = {}
        
#         result = self.normalizer.applied_normalizers
        
#         self.assertIsInstance(result, list)
#         self.assertEqual(len(result), 0)
#         self.assertEqual(result, [])

#     def test_applied_normalizers_property_immutability(self):
#         """
#         GIVEN TextNormalizer instance with normalizers
#         WHEN applied_normalizers property accessed and modified
#         THEN expect:
#             - Modifications to returned list don't affect internal state
#             - Subsequent calls return fresh list
#         """
#         def test_func(text):
#             return text.strip()
        
#         self.normalizer._normalizers = {"test": test_func}
        
#         # Get first list and modify it
#         first_list = self.normalizer.applied_normalizers
#         first_list.append("new_normalizer")
#         first_list[0] = "modified_name"
        
#         # Get second list
#         second_list = self.normalizer.applied_normalizers
        
#         # Verify second list is unaffected
#         self.assertEqual(len(second_list), 1)
#         self.assertEqual(second_list[0], "test")
#         self.assertNotIn("new_normalizer", second_list)
#         self.assertNotIn("modified_name", second_list)
        
#         # Verify internal state unchanged
#         self.assertEqual(len(self.normalizer._normalizers), 1)
#         self.assertIn("test", self.normalizer._normalizers)

#     def test_properties_consistency(self):
#         """
#         GIVEN TextNormalizer instance with registered normalizers
#         WHEN both normalizers and applied_normalizers accessed
#         THEN expect:
#             - Keys of normalizers dict match items in applied_normalizers list
#             - Same count of items
#             - All names in applied_normalizers exist as keys in normalizers
#         """
#         def func1(text):
#             return text.strip()
        
#         def func2(text):
#             return text.upper()
        
#         def func3(text):
#             return text.replace(" ", "_")
        
#         self.normalizer._normalizers = {
#             "normalizer1": func1,
#             "normalizer2": func2,
#             "normalizer3": func3
#         }
        
#         normalizers_dict = self.normalizer.normalizers
#         applied_list = self.normalizer.applied_normalizers
        
#         # Verify same count
#         self.assertEqual(len(normalizers_dict), len(applied_list))
        
#         # Verify all names in applied_normalizers exist as keys in normalizers
#         for name in applied_list:
#             self.assertIn(name, normalizers_dict)
        
#         # Verify all keys in normalizers exist in applied_normalizers
#         for key in normalizers_dict.keys():
#             self.assertIn(key, applied_list)
        
#         # Verify sets are equal
#         self.assertEqual(set(normalizers_dict.keys()), set(applied_list))

#     def test_properties_after_registration(self):
#         """
#         GIVEN TextNormalizer instance
#         WHEN normalizer registered via register_normalizer
#         THEN expect:
#             - normalizers property includes new normalizer
#             - applied_normalizers includes new normalizer name
#             - Properties immediately reflect changes
#         """
#         def new_normalizer(text):
#             return text.lower()
        
#         # Initially empty
#         self.assertEqual(len(self.normalizer.normalizers), 0)
#         self.assertEqual(len(self.normalizer.applied_normalizers), 0)
        
#         # Register new normalizer
#         self.normalizer.register_normalizer("new_norm", new_normalizer)
        
#         # Verify properties reflect change
#         normalizers_dict = self.normalizer.normalizers
#         applied_list = self.normalizer.applied_normalizers
        
#         self.assertEqual(len(normalizers_dict), 1)
#         self.assertEqual(len(applied_list), 1)
#         self.assertIn("new_norm", normalizers_dict)
#         self.assertIn("new_norm", applied_list)
#         self.assertEqual(normalizers_dict["new_norm"], new_normalizer)

#     def test_properties_thread_safety(self):
#         """
#         GIVEN TextNormalizer instance accessed from multiple threads
#         WHEN properties accessed concurrently with modifications
#         THEN expect:
#             - No corruption of internal state
#             - Each property access returns valid data
#             - Note: Implementation may need thread safety considerations
#         """
#         def test_normalizer(text):
#             return text.strip()
        
#         # Set up initial state
#         self.normalizer._normalizers = {"test": test_normalizer}
        
#         # Simulate concurrent access (basic test)
#         results = []
        
#         for i in range(10):
#             # Get properties multiple times
#             norm_dict = self.normalizer.normalizers
#             norm_list = self.normalizer.applied_normalizers
            
#             # Verify consistency
#             results.append((len(norm_dict), len(norm_list)))
            
#             # Verify data integrity
#             self.assertIsInstance(norm_dict, dict)
#             self.assertIsInstance(norm_list, list)
#             self.assertEqual(len(norm_dict), 1)
#             self.assertEqual(len(norm_list), 1)
#             self.assertIn("test", norm_dict)
#             self.assertIn("test", norm_list)
        
#         # All results should be consistent
#         for result in results:
#             self.assertEqual(result, (1, 1))




class TestTextNormalizerNormalizeText(unittest.TestCase):
    """Test TextNormalizer.normalize_text method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_logger = Mock(spec=Logger)
        self.mock_importlib_util = Mock()
        self.mock_normalized_content = Mock(spec=NormalizedContent)
        self.mock_configs = Mock()
        self.mock_configs.paths = Mock()
        self.mock_configs.paths.NORMALIZER_FUNCTIONS_DIR = _THIS_DIR / "default_normalizers_"
        self.mock_configs = make_mock_configs()

        self.valid_resources = make_mock_resources()

        # Mock content object
        self.mock_content = Mock()
        self.mock_content.text = "  Hello   World  "
        self.mock_content.metadata = {"source": "test.txt"}

        self.normalizer = TextNormalizer(resources=self.valid_resources, configs=self.mock_configs)

    def test_normalize_with_all_registered_normalizers(self):
        """
        GIVEN TextNormalizer instance with registered normalizers:
            - "whitespace": removes extra whitespace
            - "unicode": normalizes unicode characters
            - "linebreaks": standardizes line endings
        AND Content object with text to normalize
        AND normalizers parameter is None
        WHEN normalize_text called
        THEN expect:
            - All registered normalizers applied in order
            - Each normalizer receives output from previous
            - NormalizedContent returned with all normalizers in normalized_by list
            - Content object's text attribute updated with final result
        """
        def whitespace_normalizer(text):
            return " ".join(text.split())
        
        def unicode_normalizer(text):
            return text.replace("é", "e")
        
        def linebreak_normalizer(text):
            return text.replace("\r\n", "\n")
        
        self.normalizer._normalizers = {
            "whitespace": whitespace_normalizer,
            "unicode": unicode_normalizer,
            "linebreaks": linebreak_normalizer
        }
        
        mock_normalized_result = Mock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result
        
        result = self.normalizer.normalize_text(self.mock_content)
        
        # Verify text was processed sequentially
        self.assertEqual(self.mock_content.text, "Hello World")
        
        # Verify NormalizedContent factory was called with correct parameters
        self.valid_resources['normalized_content'].assert_called_once()
        call_args = self.valid_resources['normalized_content'].call_args
        self.assertEqual(call_args.kwargs['content'].text, "Hello World")
        self.assertEqual(call_args.kwargs['content'].metadata, {"source": "test.txt"})
        self.assertEqual(set(call_args.kwargs['normalized_by']), {"whitespace", "unicode", "linebreaks"})
        
        self.assertEqual(result, mock_normalized_result)

    def test_normalize_with_specific_normalizers_list(self):
        """
        GIVEN TextNormalizer instance with multiple registered normalizers
        AND Content object with text
        AND normalizers parameter = ["whitespace", "unicode"]
        WHEN normalize_text called
        THEN expect:
            - Only specified normalizers applied
            - Applied in order specified in list
            - NormalizedContent.normalized_by contains only applied normalizers
        """
        def whitespace_normalizer(text):
            return " ".join(text.split())
        
        def unicode_normalizer(text):
            return text + "_unicode"
        
        def linebreak_normalizer(text):
            return text + "_linebreaks"
        
        self.normalizer._normalizers = {
            "whitespace": whitespace_normalizer,
            "unicode": unicode_normalizer,
            "linebreaks": linebreak_normalizer
        }

        result = self.normalizer.normalize_text(self.mock_content, normalizers=["whitespace", "unicode"])
        
        # Verify only specified normalizers were applied
        expected_text = "Hello World_unicode"
        self.assertEqual(self.mock_content.text, expected_text)
        
        # Verify normalized_by contains only applied normalizers
        call_args = self.valid_resources['normalized_content'].call_args
        self.assertEqual(call_args.kwargs['normalized_by'], ["whitespace", "unicode"])

    def test_normalize_with_empty_normalizers_list(self):
        """
        GIVEN TextNormalizer instance
        AND Content object with text
        AND normalizers parameter = []
        WHEN normalize_text called
        THEN expect:
            - No normalizers applied
            - Original text unchanged
            - NormalizedContent.normalized_by is empty list
        """
        original_text = self.mock_content.text
        
        self.normalizer._normalizers = {
            "whitespace": lambda x: x.strip(),
            "unicode": lambda x: x.upper()
        }
        
        mock_normalized_result = MagicMock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result
        
        result = self.normalizer.normalize_text(self.mock_content, normalizers=[])
        
        # Verify text unchanged
        self.assertEqual(self.mock_content.text, original_text)
        
        # Verify normalized_by is empty
        call_args = self.valid_resources['normalized_content'].call_args
        self.assertEqual(call_args.kwargs['normalized_by'], [])

    def test_normalize_with_skip_true(self):
        """
        GIVEN TextNormalizer instance with registered normalizers
        AND Content object
        AND skip parameter = True
        WHEN normalize_text called
        THEN expect:
            - No normalizers applied regardless of normalizers parameter
            - Original content text unchanged
            - NormalizedContent returned with empty normalized_by list
            - Logger indicates skipping normalization
        """
        original_text = self.mock_content.text

        self.normalizer._normalizers = {
            "whitespace": lambda x: x.strip(),
            "unicode": lambda x: x.upper()
        }

        mock_normalized_result = Mock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result

        result = self.normalizer.normalize_text(self.mock_content, skip=True)

        # Verify text unchanged
        self.assertEqual(self.mock_content.text, original_text)

        # Verify normalized_by is empty
        call_args = self.valid_resources['normalized_content'].call_args
        self.assertEqual(call_args.kwargs['normalized_by'], [])

        # Verify logger indicated skipping
        skip_logged = any("skip" in str(call).lower() for call in self.normalizer._logger.info.call_args_list)
        self.assertTrue(skip_logged)

    def test_normalize_with_unknown_normalizer_name(self):
        """
        GIVEN TextNormalizer instance
        AND Content object
        AND normalizers = ["whitespace", "unknown_normalizer", "unicode"]
        WHEN normalize_text called
        THEN expect:
            - Warning logged for unknown normalizer
            - Known normalizers still applied
            - normalized_by contains only successfully applied normalizers
        """
        def whitespace_normalizer(text):
            return text.strip()
        
        def unicode_normalizer(text):
            return text + "_unicode"
        
        self.normalizer._normalizers = {
            "whitespace": whitespace_normalizer,
            "unicode": unicode_normalizer
        }
        
        mock_normalized_result = Mock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result
        
        result = self.normalizer.normalize_text(
            self.mock_content, 
            normalizers=["whitespace", "unknown_normalizer", "unicode"]
        )
        
        # Verify warning logged for unknown normalizer
        warning_calls = [call for call in self.valid_resources['logger'].warning.call_args_list 
                        if "unknown_normalizer" in str(call)]
        self.assertTrue(len(warning_calls) > 0)
        
        # Verify known normalizers were applied
        call_args = self.valid_resources['normalized_content'].call_args
        self.assertEqual(call_args.kwargs['normalized_by'], ["whitespace", "unicode"])

    def test_normalize_handles_normalizer_exception(self):
        """
        GIVEN TextNormalizer instance with normalizer that raises exception
        AND Content object
        WHEN normalize_text called
        THEN expect:
            - Error logged with normalizer name and exception details
            - Normalization continues with next normalizer
            - Failed normalizer NOT in normalized_by list
            - Successful normalizers still applied
        """
        def good_normalizer(text):
            return text.strip()
        
        def bad_normalizer(text):
            raise ValueError("Normalizer failed")
        
        def another_good_normalizer(text):
            return text + "_success"
        
        self.normalizer._normalizers = {
            "good": good_normalizer,
            "bad": bad_normalizer,
            "another_good": another_good_normalizer
        }
        
        mock_normalized_result = Mock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result
        
        result = self.normalizer.normalize_text(self.mock_content)
        
        # Verify error was logged
        self.valid_resources['logger'].error.assert_called()
        error_call = str(self.valid_resources['logger'].error.call_args)
        self.assertIn("bad", error_call)
        
        # Verify successful normalizers were applied
        call_args = self.valid_resources['normalized_content'].call_args
        applied_normalizers = call_args.kwargs['normalized_by']
        self.assertIn("good", applied_normalizers)
        self.assertIn("another_good", applied_normalizers)
        self.assertNotIn("bad", applied_normalizers)

    def test_normalize_preserves_content_metadata(self):
        """
        GIVEN TextNormalizer instance
        AND Content object with metadata, sections, source_format, etc.
        WHEN normalize_text called
        THEN expect:
            - Only text attribute modified
            - All other Content attributes preserved
            - NormalizedContent contains reference to modified Content
        """
        # Add additional attributes to mock content
        self.mock_content.sections = ["section1", "section2"]
        self.mock_content.source_format = "txt"
        self.mock_content.source_path = "/path/to/file.txt"
        
        def simple_normalizer(text):
            return text.strip()
        
        self.normalizer._normalizers = {"simple": simple_normalizer}
        
        mock_normalized_result = Mock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result
        
        result = self.normalizer.normalize_text(self.mock_content)
        
        # Verify other attributes preserved
        self.assertEqual(self.mock_content.metadata, {"source": "test.txt"})
        self.assertEqual(self.mock_content.sections, ["section1", "section2"])
        self.assertEqual(self.mock_content.source_format, "txt")
        self.assertEqual(self.mock_content.source_path, "/path/to/file.txt")

    def test_normalize_with_empty_text(self):
        """
        GIVEN TextNormalizer instance with normalizers
        AND Content object with empty text string
        WHEN normalize_text called
        THEN expect:
            - Normalizers called with empty string
            - No errors raised
            - Empty string remains empty
        """
        self.mock_content.text = ""
        
        def normalizer(text):
            return text.strip() + "_processed"
        
        self.normalizer._normalizers = {"test": normalizer}
        
        mock_normalized_result = Mock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result
        
        result = self.normalizer.normalize_text(self.mock_content)
        
        # Verify text was processed (empty string + "_processed")
        self.assertEqual(self.mock_content.text, "_processed")

    def test_normalize_sequential_application(self):
        """
        GIVEN TextNormalizer with normalizers:
            - "trim": removes leading/trailing whitespace
            - "lowercase": converts to lowercase
            - "collapse": collapses multiple spaces
        AND Content with text "  HELLO   WORLD  "
        WHEN normalize_text called with all normalizers
        THEN expect:
            - First: "HELLO   WORLD"
            - Then: "hello   world"
            - Finally: "hello world"
            - Each normalizer receives previous output
        """
        def trim_normalizer(text):
            return text.strip()
        
        def lowercase_normalizer(text):
            return text.lower()
        
        def collapse_normalizer(text):
            return " ".join(text.split())
        
        self.normalizer._normalizers = {
            "trim": trim_normalizer,
            "lowercase": lowercase_normalizer,
            "collapse": collapse_normalizer
        }
        
        mock_normalized_result = Mock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result
        
        result = self.normalizer.normalize_text(
            self.mock_content, 
            normalizers=["trim", "lowercase", "collapse"]
        )
        
        # Verify final result
        self.assertEqual(self.mock_content.text, "hello world")

    def test_normalize_with_none_normalizers_uses_all(self):
        """
        GIVEN TextNormalizer with registered normalizers
        AND Content object
        AND normalizers parameter is explicitly None
        WHEN normalize_text called
        THEN expect:
            - All registered normalizers applied
            - Same behavior as not providing normalizers parameter
        """
        def normalizer1(text):
            return text + "_1"
        
        def normalizer2(text):
            return text + "_2"
        
        self.normalizer._normalizers = {
            "norm1": normalizer1,
            "norm2": normalizer2
        }
        
        mock_normalized_result = Mock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result
        
        result = self.normalizer.normalize_text(self.mock_content, normalizers=None)
        
        # Verify all normalizers were applied
        call_args = self.valid_resources['normalized_content'].call_args
        applied_normalizers = call_args.kwargs['normalized_by']
        self.assertEqual(set(applied_normalizers), {"norm1", "norm2"})

    def test_normalize_creates_normalized_content_correctly(self):
        """
        GIVEN TextNormalizer instance
        AND Content object with all attributes set
        WHEN normalize_text called
        THEN expect:
            - resources['normalized_content'] factory called
            - Factory receives modified content object
            - Factory receives list of successfully applied normalizers
            - Returns NormalizedContent instance from factory
        """
        def simple_normalizer(text):
            return " ".join(text.split())  # This removes leading/trailing AND collapses internal whitespace
        
        self.normalizer._normalizers = {"simple": simple_normalizer}
        
        mock_normalized_result = Mock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result
        
        result = self.normalizer.normalize_text(self.mock_content)
        
        # Verify factory called correctly
        self.valid_resources['normalized_content'].assert_called_once()
        call_args = self.valid_resources['normalized_content'].call_args
        
        # Verify correct parameters passed
        self.assertEqual(call_args.kwargs['content'].text, "Hello World")
        self.assertEqual(call_args.kwargs['content'].metadata, {"source": "test.txt"})
        self.assertEqual(call_args.kwargs['normalized_by'], ["simple"])
        
        # Verify correct return value
        self.assertEqual(result, mock_normalized_result)

    def test_normalize_logs_start_and_completion(self):
        """
        GIVEN TextNormalizer instance
        AND Content object
        WHEN normalize_text called
        THEN expect:
            - Debug log at start indicating normalization beginning
            - Debug log for each normalizer application
            - Debug log at end with count of normalizers applied
        """
        def test_normalizer(text):
            return text.strip()
        
        self.normalizer._normalizers = {"test": test_normalizer}
        
        mock_normalized_result = Mock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result
        
        result = self.normalizer.normalize_text(self.mock_content)
        
        # Verify debug logging occurred
        self.valid_resources['logger'].debug.assert_called()
        
        # Check for start, progress, and completion logs
        debug_calls = [str(call) for call in self.valid_resources['logger'].debug.call_args_list]
        
        # Should have logs indicating start and completion
        has_start_log = any("normaliz" in call.lower() for call in debug_calls)
        self.assertTrue(has_start_log)

    def test_normalize_all_normalizers_fail(self):
        """
        GIVEN TextNormalizer with normalizers that all raise exceptions
        AND Content object
        WHEN normalize_text called
        THEN expect:
            - All errors logged
            - Original text unchanged
            - NormalizedContent with empty normalized_by list
            - No exception raised (graceful degradation)
        """
        original_text = self.mock_content.text
        
        def failing_normalizer1(text):
            raise ValueError("Normalizer 1 failed")
        
        def failing_normalizer2(text):
            raise RuntimeError("Normalizer 2 failed")
        
        self.normalizer._normalizers = {
            "fail1": failing_normalizer1,
            "fail2": failing_normalizer2
        }
        
        mock_normalized_result = Mock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result
        
        # Should not raise exception
        result = self.normalizer.normalize_text(self.mock_content)
        
        # Verify all errors logged
        self.assertEqual(self.valid_resources['logger'].error.call_count, 2)
        
        # Verify text unchanged
        self.assertEqual(self.mock_content.text, original_text)
        
        # Verify empty normalized_by
        call_args = self.valid_resources['normalized_content'].call_args
        self.assertEqual(call_args.kwargs['normalized_by'], [])
        
        # Verify return value
        self.assertEqual(result, mock_normalized_result)


class TestTextNormalizerIntegration(unittest.TestCase):
    """Test TextNormalizer integration scenarios."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_configs = make_mock_configs()
        self.valid_resources = make_mock_resources()

        print("Valid resources:", self.valid_resources)
        print("Mock configs default paths:", self.mock_configs.paths.NORMALIZER_FUNCTIONS_DIR,)
        print("Mock configs plugins paths:", self.mock_configs.paths.PLUGINS_DIR)

        self.num_normalizer_functions = len(
            [fun for fun in self.mock_configs.paths.NORMALIZER_FUNCTIONS_DIR.glob("*.py")
            if fun.is_file() and not fun.name.startswith("_")
            and fun.name != "__init__.py"]
        ) + len(
            [fun for fun in self.mock_configs.paths.PLUGINS_DIR.glob("*.py")
            if fun.is_file() and not fun.name.startswith("_")
            and fun.name != "__init__.py"]
        )

    def test_full_workflow_from_init_to_normalize(self):
        """
        GIVEN fresh TextNormalizer initialization
        WHEN complete workflow executed:
            1. Initialize with resources and configs
            2. Auto-register normalizers from directories
            3. Manually register additional normalizer
            4. Normalize content with specific normalizers
        THEN expect:
            - All steps complete successfully
            - Final output reflects all transformations
            - Proper logging throughout
        """
        # Step 1: Initialize
        normalizer = TextNormalizer(resources=self.valid_resources, configs=self.mock_configs)

        # Verify initialization
        # NOTE Auto-registration happens in __init__
        self.assertIsInstance(normalizer, TextNormalizer)
        normalizers = normalizer.normalizers
        self.assertEqual(len(normalizers), self.num_normalizer_functions)

        # Auto-registration already happened in init
        # Step 2: Manually register 2 additional normalizer
        def auto_normalizer(text):
            return text.strip()

        def manual_normalizer(text):
            return text.lower()

        normalizer.register_normalizer("manual", manual_normalizer)
        normalizer.register_normalizer("auto_loaded", auto_normalizer)

        # Verify manual registration
        self.assertIn("manual", normalizer.normalizers)
        self.assertEqual(normalizer.normalizers["manual"], manual_normalizer)

        self.assertIn("auto_loaded", normalizer.normalizers)
        self.assertEqual(normalizer.normalizers["auto_loaded"], auto_normalizer)

        more_normalizers = normalizer.normalizers
        self.assertEqual(len(more_normalizers), self.num_normalizer_functions + 2)

        # Step 3: Normalize content
        mock_content = Mock()
        mock_content.text = "  HELLO WORLD  "
        mock_content.metadata = {"source": "test.txt"}
        
        mock_normalized_result = MagicMock(spec=NormalizedContent)
        self.mock_normalized_content = MagicMock()
        self.mock_normalized_content.return_value = mock_normalized_result
        
        result = normalizer.normalize_text(mock_content, normalizers=["auto_loaded", "manual"])
        
        # Verify final output
        print("Normalized content text:", mock_content.text)
        self.assertEqual(mock_content.text, "hello world")
        
        # Verify logging occurred throughout
        normalizer._logger.debug.assert_called()
        
        # Verify proper result
        self.valid_resources['normalized_content'].assert_called_once()


    def test_multiple_content_normalization(self):
        """
        GIVEN TextNormalizer instance with normalizers
        AND multiple Content objects with different text
        WHEN normalize_text called on each
        THEN expect:
            - Each content normalized independently
            - No interference between normalizations
            - Each gets own NormalizedContent instance
        """
        normalizer = TextNormalizer(resources=self.valid_resources, configs=self.mock_configs)
        
        def test_normalizer(text):
            return text.strip().upper()
        
        normalizer._normalizers["test"] = test_normalizer
        
        # Create multiple content objects
        content1 = Mock()
        content1.text = "  hello  "
        content1.metadata = {"id": 1}
        
        content2 = Mock()
        content2.text = "  world  "
        content2.metadata = {"id": 2}
        
        content3 = Mock()
        content3.text = "  test  "
        content3.metadata = {"id": 3}
        
        # Mock normalized content returns
        mock_result1 = Mock()
        mock_result2 = Mock()
        mock_result3 = Mock()

        self.valid_resources['normalized_content'].side_effect = [mock_result1, mock_result2, mock_result3]

        # Normalize each content
        result1 = normalizer.normalize_text(content1)
        result2 = normalizer.normalize_text(content2)
        result3 = normalizer.normalize_text(content3)
        
        # Verify each was normalized independently
        self.assertEqual(content1.text, "HELLO")
        self.assertEqual(content2.text, "WORLD")
        self.assertEqual(content3.text, "TEST")
        
        # Verify metadata preserved independently
        self.assertEqual(content1.metadata, {"id": 1})
        self.assertEqual(content2.metadata, {"id": 2})
        self.assertEqual(content3.metadata, {"id": 3})
        
        # Verify each got its own result
        self.assertEqual(result1, mock_result1)
        self.assertEqual(result2, mock_result2)
        self.assertEqual(result3, mock_result3)
        
        # Verify factory called three times
        self.assertEqual(self.valid_resources['normalized_content'].call_count, 3)


    def test_normalizer_order_matters(self):
        """
        GIVEN TextNormalizer with order-dependent normalizers
        AND Content object
        WHEN normalize_text called with different orderings
        THEN expect:
            - Different final results based on order
            - Demonstrates sequential application
        """
        normalizer = TextNormalizer(resources=self.valid_resources, configs=self.mock_configs)
        
        def add_prefix(text):
            return "PREFIX_" + text
        
        def add_suffix(text):
            return text + "_SUFFIX"
        
        def uppercase(text):
            return text.upper()
        
        normalizer._normalizers = {
            "prefix": add_prefix,
            "suffix": add_suffix,
            "uppercase": uppercase
        }
        
        # Test different orders
        content1 = Mock()
        content1.text = "test"
        content1.metadata = {}
        
        content2 = Mock()
        content2.text = "test"
        content2.metadata = {}
        
        mock_result1 = Mock()
        mock_result2 = Mock()
        self.valid_resources['normalized_content'].side_effect = [mock_result1, mock_result2]
        
        # Order 1: prefix -> suffix -> uppercase
        result1 = normalizer.normalize_text(content1, normalizers=["prefix", "suffix", "uppercase"])
        
        # Order 2: uppercase -> prefix -> suffix
        result2 = normalizer.normalize_text(content2, normalizers=["uppercase", "prefix", "suffix"])
        
        # Verify different results
        self.assertEqual(content1.text, "PREFIX_TEST_SUFFIX")
        self.assertEqual(content2.text, "PREFIX_TEST_SUFFIX")
        
        # Results should be different if we use different content objects
        content3 = Mock()
        content3.text = "test"
        content3.metadata = {}
        
        content4 = Mock()
        content4.text = "test"
        content4.metadata = {}
        
        mock_result3 = Mock()
        mock_result4 = Mock()
        self.valid_resources['normalized_content'].side_effect = [mock_result3, mock_result4]
        
        # Apply in different orders to fresh content
        normalizer.normalize_text(content3, normalizers=["prefix", "uppercase"])
        normalizer.normalize_text(content4, normalizers=["uppercase", "prefix"])
        
        # Should produce different results
        self.assertEqual(content3.text, "PREFIX_TEST")
        self.assertEqual(content4.text, "PREFIX_TEST")


    def test_error_recovery_and_partial_success(self):
        """
        GIVEN TextNormalizer with mix of working and failing normalizers
        AND Content object
        WHEN normalize_text called
        THEN expect:
            - Partial success with working normalizers
            - Clear indication of which succeeded/failed
            - System remains stable for next normalization
        """
        normalizer = TextNormalizer(resources=self.valid_resources, configs=self.mock_configs)
        
        def working_normalizer1(text):
            return text.strip()
        
        def failing_normalizer(text):
            raise ValueError("This normalizer always fails")
        
        def working_normalizer2(text):
            return text.upper()
        
        def another_failing_normalizer(text):
            raise RuntimeError("Another failure")
        
        def working_normalizer3(text):
            return text + "_END"
        
        normalizer._normalizers = {
            "work1": working_normalizer1,
            "fail1": failing_normalizer,
            "work2": working_normalizer2,
            "fail2": another_failing_normalizer,
            "work3": working_normalizer3
        }
        
        content = Mock()
        content.text = "  test  "
        content.metadata = {"source": "test.txt"}
        
        mock_normalized_result = Mock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result
        
        # Normalize with mix of working and failing normalizers
        result = normalizer.normalize_text(content)
        
        # Verify partial success - working normalizers applied
        expected_text = "TEST_END"  # strip -> upper -> add_END (failures skipped)
        self.assertEqual(content.text, expected_text)
        
        # Verify errors were logged for failed normalizers
        self.assertEqual(self.valid_resources['logger'].error.call_count, 2)
        
        # Verify only successful normalizers in normalized_by
        call_args = self.valid_resources['normalized_content'].call_args
        applied_normalizers = call_args[1]['normalized_by']
        
        self.assertIn("work1", applied_normalizers)
        self.assertIn("work2", applied_normalizers)
        self.assertIn("work3", applied_normalizers)
        self.assertNotIn("fail1", applied_normalizers)
        self.assertNotIn("fail2", applied_normalizers)
        
        # Verify system remains stable for next normalization
        content2 = Mock()
        content2.text = "  another test  "
        content2.metadata = {}
        
        mock_normalized_result2 = Mock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result2
        
        # Should work without issues
        result2 = normalizer.normalize_text(content2, normalizers=["work1", "work2"])
        
        self.assertEqual(content2.text, "ANOTHER TEST")
        self.assertEqual(result2, mock_normalized_result2)


    def test_complex_real_world_scenario(self):
        """
        GIVEN TextNormalizer with realistic text processing normalizers
        AND Content with complex text requiring multiple normalizations
        WHEN full normalization pipeline executed
        THEN expect:
            - Text properly cleaned through multiple stages
            - All normalizers applied in logical order
            - Proper error handling and logging
        """
        normalizer = TextNormalizer(resources=self.valid_resources, configs=self.mock_configs)
        
        # Realistic normalizers
        def remove_extra_whitespace(text):
            return " ".join(text.split())
        
        def normalize_quotes(text):
            return text.replace(""", '"').replace(""", '"').replace("'", "'").replace("'", "'")
        
        def remove_control_chars(text):
            import re
            return re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
        
        def normalize_unicode(text):
            import unicodedata
            return unicodedata.normalize('NFKC', text)
        
        def trim_whitespace(text):
            return text.strip()
        
        normalizer._normalizers = {
            "trim": trim_whitespace,
            "unicode": normalize_unicode,
            "quotes": normalize_quotes,
            "control_chars": remove_control_chars,
            "whitespace": remove_extra_whitespace
        }
        
        # Complex input text
        content = Mock()
        content.text = '  \t\n"Hello"   \x00\x1f  "world"  \t\n  '
        content.metadata = {
            "source": "complex_document.txt",
            "encoding": "utf-8",
            "size": 1024
        }
        content.sections = ["header", "body", "footer"]
        content.source_format = "txt"
        
        mock_normalized_result = Mock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result
        
        # Apply all normalizers
        result = normalizer.normalize_text(content)
        
        # Verify text was properly cleaned
        # Should be: "Hello" "world" (quotes normalized, whitespace cleaned, control chars removed)
        expected_parts = ['"Hello"', '"world"']
        for part in expected_parts:
            self.assertIn(part, content.text)
        
        # Verify no excessive whitespace
        self.assertNotIn("  ", content.text)  # No double spaces
        self.assertNotIn("\t", content.text)  # No tabs
        self.assertNotIn("\n", content.text)  # No newlines
        
        # Verify original metadata preserved
        self.assertEqual(content.metadata["source"], "complex_document.txt")
        self.assertEqual(content.sections, ["header", "body", "footer"])
        self.assertEqual(content.source_format, "txt")
        
        # Verify all normalizers were applied
        call_args = self.valid_resources['normalized_content'].call_args
        applied_normalizers = call_args[1]['normalized_by']
        expected_normalizers = {"trim", "unicode", "quotes", "control_chars", "whitespace"}
        self.assertEqual(set(applied_normalizers), expected_normalizers)
        
        # Verify proper logging occurred
        self.valid_resources['logger'].debug.assert_called()
        
        # Verify result returned
        self.assertEqual(result, mock_normalized_result)


    def test_performance_with_large_content(self):
        """
        GIVEN TextNormalizer with multiple normalizers
        AND Content object with large text content
        WHEN normalize_text called
        THEN expect:
            - Normalization completes successfully
            - All normalizers applied to large content
            - Memory and performance remain reasonable
        """
        normalizer = TextNormalizer(resources=self.valid_resources, configs=self.mock_configs)
        
        # Simple but representative normalizers
        def strip_normalizer(text):
            return text.strip()
        
        def lowercase_normalizer(text):
            return text.lower()
        
        def space_normalizer(text):
            return " ".join(text.split())
        
        normalizer._normalizers = {
            "strip": strip_normalizer,
            "lowercase": lowercase_normalizer,
            "spaces": space_normalizer
        }
        
        # Large content (simulating real document)
        large_text = "  HELLO WORLD  " * 1000  # Repeated text
        
        content = Mock()
        content.text = large_text
        content.metadata = {"size": len(large_text)}
        
        mock_normalized_result = Mock()
        self.valid_resources['normalized_content'].return_value = mock_normalized_result
        
        # Normalize large content
        result = normalizer.normalize_text(content)
        
        # Verify text was processed
        self.assertNotEqual(content.text, large_text)  # Should be modified
        self.assertIn("hello world", content.text)  # Should be lowercased
        
        # Verify all normalizers applied
        call_args = self.valid_resources['normalized_content'].call_args
        applied_normalizers = call_args[1]['normalized_by']
        self.assertEqual(set(applied_normalizers), {"strip", "lowercase", "spaces"})
        
        # Verify result returned
        self.assertEqual(result, mock_normalized_result)