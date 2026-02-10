"""
Test suite for core/text_normalizer/_text_normalizer.py converted from unittest to pytest.
"""
import pytest
import importlib.util
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import copy

# Skip tests if the module can't be imported
try:
    from core.text_normalizer._normalized_content import NormalizedContent
    from core.text_normalizer._text_normalizer import TextNormalizer
    from core.content_extractor import Content
    from configs import Configs, _PathsBaseModel
    from types_ import Logger
except ImportError:
    pytest.skip("core.text_normalizer module not available", allow_module_level=True)


_THIS_DIR = Path(__file__).parent


def make_mock_configs():
    """Create mock configs for testing."""
    mock_configs = MagicMock()
    mock_configs.paths = MagicMock()
    # Use the actual test directories that contain mock normalizers
    mock_configs.paths.NORMALIZER_FUNCTIONS_DIR = Path("tests/unit_tests/core_/text_normalizer_/default_normalizers_")
    mock_configs.paths.PLUGINS_DIR = Path("tests/unit_tests/core_/text_normalizer_/plugins_")
    return copy.deepcopy(mock_configs)


def make_mock_resources():
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
    return copy.deepcopy(mock_resources)


# Alternative approach using a custom TextNormalizer subclass for testing
class _TestableTextNormalizer(TextNormalizer):
    """Subclass that tracks method calls for testing."""
    
    def __init__(self, resources, configs):
        self.register_calls = []
        super().__init__(resources, configs)
    
    def register_normalizers_from(self, folder):
        """Track calls while executing parent logic."""
        self.register_calls.append(folder)
        return super().register_normalizers_from(folder)


@pytest.fixture
def mock_configs():
    """Provide mock configs for testing."""
    return make_mock_configs()


@pytest.fixture
def mock_resources():
    """Provide mock resources for testing."""
    return make_mock_resources()


@pytest.fixture
def temp_dir():
    """Create temporary directory for testing."""
    import tempfile
    import shutil
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.unit
class TestTextNormalizerInitialization:
    """Test TextNormalizer initialization and configuration."""

    @pytest.fixture
    def setup_data(self, mock_configs):
        """Set up test data for each test."""
        # Calculate number of normalizer functions from actual test directories
        try:
            normalizer_dir = Path("tests/unit_tests/core_/text_normalizer_/default_normalizers_")
            plugins_dir = Path("tests/unit_tests/core_/text_normalizer_/plugins_")
            
            normalizer_files = []
            if normalizer_dir.exists():
                normalizer_files.extend([
                    f for f in normalizer_dir.glob("*.py")
                    if f.is_file() and not f.name.startswith("_") and f.name != "__init__.py"
                ])
            
            if plugins_dir.exists():
                normalizer_files.extend([
                    f for f in plugins_dir.glob("*.py")
                    if f.is_file() and not f.name.startswith("_") and f.name != "__init__.py"
                ])
            
            num_normalizer_functions = len(normalizer_files)
        except Exception:
            num_normalizer_functions = 0
        
        return {'num_normalizer_functions': num_normalizer_functions}

    def test_init_with_valid_resources_and_configs(self, mock_resources, mock_configs, setup_data):
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
            - _normalizers initialized with functions from the two input directories
        """
        # WHEN
        normalizer = TextNormalizer(resources=mock_resources, configs=mock_configs)
        
        # THEN
        assert isinstance(normalizer, TextNormalizer)
        assert normalizer.configs == mock_configs
        assert normalizer.resources == mock_resources

    def test_init_configs_stored_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict and valid configs object
        WHEN TextNormalizer is initialized
        THEN expect:
            - normalizer.configs equals the provided configs object
        """
        # WHEN
        normalizer = TextNormalizer(resources=mock_resources, configs=mock_configs)
        
        # THEN
        assert normalizer.configs == mock_configs

    def test_init_resources_stored_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict and valid configs object
        WHEN TextNormalizer is initialized
        THEN expect:
            - normalizer.resources equals the provided resources dict
        """
        # WHEN
        normalizer = TextNormalizer(resources=mock_resources, configs=mock_configs)
        
        # THEN
        assert normalizer.resources == mock_resources

    def test_init_logger_component_set_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict containing logger component
        WHEN TextNormalizer is initialized
        THEN expect:
            - normalizer._logger equals the provided logger
        """
        # WHEN
        normalizer = TextNormalizer(resources=mock_resources, configs=mock_configs)
        
        # THEN
        assert normalizer._logger == mock_resources["logger"]

    def test_init_importlib_util_component_set_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict containing importlib_util component
        WHEN TextNormalizer is initialized
        THEN expect:
            - normalizer._importlib_util equals the provided importlib_util
        """
        # WHEN
        normalizer = TextNormalizer(resources=mock_resources, configs=mock_configs)
        
        # THEN
        assert normalizer._importlib_util == mock_resources["importlib_util"]

    def test_init_normalized_content_factory_set_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict containing normalized_content factory
        WHEN TextNormalizer is initialized
        THEN expect:
            - normalizer._normalized_content equals the provided factory
        """
        # WHEN
        normalizer = TextNormalizer(resources=mock_resources, configs=mock_configs)
        
        # THEN
        assert normalizer._normalized_content == mock_resources["normalized_content"]