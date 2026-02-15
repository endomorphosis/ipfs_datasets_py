"""
Test suite for core/output_formatter/_output_formatter.py converted from unittest to pytest.
"""
import pytest
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
    mock_logger = MagicMock(spec=Logger)
    mock_formatted_output = MagicMock(spec=FormattedOutput)
    mock_normalized_content = MagicMock(spec=NormalizedContent)
    return {
        "normalized_content": mock_normalized_content,
        "formatted_output": mock_formatted_output,
        "logger": mock_logger,
    }


def make_mock_configs() -> MagicMock:
    """
    Create mock configuration object for OutputFormatter testing.
    
    Returns:
        Mocked Configs object with necessary attributes.
    """
    mock_configs = MagicMock()
    mock_configs.output = MagicMock()
    mock_configs.output.default_format = 'txt'
    return mock_configs


def make_mock_content() -> MagicMock:
    """
    Create mock Content object for testing.
    
    Returns:
        Mocked Content object with sample data.
    """
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


def make_mock_normalized_content(mock_content: MagicMock = None) -> MagicMock:
    """Create mock normalized content for testing."""
    mock_normalized_content = MagicMock(spec=NormalizedContent)
    mock_normalized_content.content = mock_content or make_mock_content()
    mock_normalized_content.normalized_by = ["newlines", "whitespace"]
    return mock_normalized_content


@pytest.fixture
def mock_resources():
    """Provide mock resources for testing."""
    return make_mock_resources()


@pytest.fixture
def mock_configs():
    """Provide mock configs for testing."""
    return make_mock_configs()


@pytest.fixture
def temp_dir():
    """Create temporary directory for testing."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.unit
class TestOutputFormatterInitialization:
    """Test OutputFormatter initialization and configuration."""

    def test_init_with_valid_resources_and_configs(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict and configs object
        WHEN OutputFormatter is initialized
        THEN expect:
            - Instance created successfully
            - All attributes properly set from configs and resources
        """
        # WHEN
        formatter = OutputFormatter(resources=mock_resources, configs=mock_configs)
        
        # THEN
        assert isinstance(formatter, OutputFormatter)
        assert formatter.configs == mock_configs
        assert formatter.resources == mock_resources

    def test_init_configs_stored_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict and valid configs object
        WHEN OutputFormatter is initialized
        THEN expect:
            - formatter.configs equals the provided configs object
        """
        # WHEN
        formatter = OutputFormatter(resources=mock_resources, configs=mock_configs)
        
        # THEN
        assert formatter.configs == mock_configs

    def test_init_resources_stored_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict and valid configs object
        WHEN OutputFormatter is initialized
        THEN expect:
            - formatter.resources equals the provided resources dict
        """
        # WHEN
        formatter = OutputFormatter(resources=mock_resources, configs=mock_configs)
        
        # THEN
        assert formatter.resources == mock_resources

    def test_init_logger_component_set_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict containing logger component
        WHEN OutputFormatter is initialized
        THEN expect:
            - formatter._logger equals the provided logger
        """
        # WHEN
        formatter = OutputFormatter(resources=mock_resources, configs=mock_configs)
        
        # THEN
        assert formatter._logger == mock_resources["logger"]

    def test_init_normalized_content_factory_set_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict containing normalized_content factory
        WHEN OutputFormatter is initialized
        THEN expect:
            - formatter._normalized_content equals the provided factory
        """
        # WHEN
        formatter = OutputFormatter(resources=mock_resources, configs=mock_configs)
        
        # THEN
        assert formatter._normalized_content == mock_resources["normalized_content"]

    def test_init_formatted_output_factory_set_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict containing formatted_output factory
        WHEN OutputFormatter is initialized
        THEN expect:
            - formatter._formatted_output equals the provided factory
        """
        # WHEN
        formatter = OutputFormatter(resources=mock_resources, configs=mock_configs)
        
        # THEN
        assert formatter._formatted_output == mock_resources["formatted_output"]