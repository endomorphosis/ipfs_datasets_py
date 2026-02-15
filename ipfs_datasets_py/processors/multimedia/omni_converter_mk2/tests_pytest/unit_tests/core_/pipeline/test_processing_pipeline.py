"""
Test suite for core/_processing_pipeline.py converted from unittest to pytest.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime
from typing import Optional, Any, Callable
import tempfile
import os
from pathlib import Path
import shutil
import hashlib

from core._processing_result import ProcessingResult
from core._processing_pipeline import ProcessingPipeline
from core import make_processing_pipeline
from configs import configs, Configs
from logger import logger
from types_ import Logger
from file_format_detector import make_file_format_detector
from types_ import Callable, Logger, TypedDict, ModuleType
from core._processing_pipeline import ProcessingPipeline
from core._pipeline_status import PipelineStatus
from core._processing_result import ProcessingResult
from core.file_validator import make_file_validator
from core.text_normalizer import make_text_normalizer
from core.output_formatter import make_output_formatter
from core.content_extractor import make_content_extractor
from core.content_sanitizer import make_content_sanitizer
from core.file_validator._file_validator import FileValidator
from file_format_detector._file_format_detector import FileFormatDetector
from core.content_extractor._content_extractor import ContentExtractor
from core.text_normalizer._text_normalizer import TextNormalizer
from core.output_formatter._output_formatter import OutputFormatter
from core.content_sanitizer import ContentSanitizer
from monitors import make_security_monitor, SecurityMonitor


class _ProcessingPipelineResources(TypedDict):
    file_format_detector: Callable
    file_validator: Callable
    content_extractor: Callable
    text_normalizer: Callable
    output_formatter: Callable
    processing_result: ProcessingResult
    pipeline_status: PipelineStatus
    security_monitor: SecurityMonitor
    logger: Logger
    hashlib: ModuleType


def make_mock_resources():
    """Create a mock resources dictionary for testing."""
    return {
        'file_format_detector': MagicMock(spec=FileFormatDetector),
        'file_validator': MagicMock(spec=FileValidator),
        'content_extractor': MagicMock(spec=ContentExtractor),
        'content_sanitizer': MagicMock(spec=ContentSanitizer),
        'text_normalizer': MagicMock(spec=TextNormalizer),
        'output_formatter': MagicMock(spec=OutputFormatter),
        'processing_result': MagicMock(spec=ProcessingResult),
        'pipeline_status': MagicMock(spec=PipelineStatus),
        'security_monitor': MagicMock(spec=SecurityMonitor),
        'logger': MagicMock(spec=Logger),
        'hashlib': MagicMock(spec=hashlib),
    }


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def test_files(temp_dir):
    """Create test files in temporary directory."""
    test_file_path = os.path.join(temp_dir, "test_file.txt")
    with open(test_file_path, 'w') as f:
        f.write("Test content")
    
    large_file_path = os.path.join(temp_dir, "large_file.txt")
    with open(large_file_path, 'w') as f:
        f.write("A" * (15 * 1024 * 1024))  # 15 MB file (exceeds text limit)
    
    executable_file_path = os.path.join(temp_dir, "test_script.sh")
    with open(executable_file_path, 'w') as f:
        f.write("#!/bin/bash\necho 'test'")
    os.chmod(executable_file_path, stat.S_IRWXU)  # Make executable
    
    return {
        'test_file': test_file_path,
        'large_file': large_file_path,
        'executable_file': executable_file_path
    }


@pytest.fixture
def mock_resources():
    """Provide mock resources for testing."""
    return make_mock_resources()


@pytest.fixture
def mock_configs():
    """Provide mock configs for testing."""
    mock_configs = MagicMock(spec=Configs)
    return mock_configs


@pytest.mark.unit
class TestProcessingPipelineInit:
    """Test ProcessingPipeline initialization."""

    def test_init_with_valid_resources_and_configs(self, mock_resources, mock_configs):
        """
        GIVEN valid configs and resources
        WHEN ProcessingPipeline is initialized
        THEN expect:
            - All attributes properly set from configs and resources
        """
        # Act
        pipeline = ProcessingPipeline(resources=mock_resources, configs=mock_configs)
        
        # Assert
        assert isinstance(pipeline, ProcessingPipeline)
        assert pipeline.configs == mock_configs
        assert pipeline.resources == mock_resources