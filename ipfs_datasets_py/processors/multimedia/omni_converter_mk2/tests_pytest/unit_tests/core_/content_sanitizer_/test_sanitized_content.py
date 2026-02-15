"""
Test suite for core/content_sanitizer/_sanitized_content.py converted from unittest to pytest.
"""
import pytest
from unittest.mock import MagicMock, patch
import copy
import os
import tempfile
import shutil

from logger import logger as debug_logger
from core.content_extractor._content import Content
from types_ import Logger, Configs
from monitors.security_monitor import SecurityMonitor, SecurityResult

from core.content_sanitizer._constants import Constants
from configs import configs
from core.content_sanitizer import ContentSanitizer, SanitizedContent


def make_constants_resources():
    constants_resources = { # NOTE: Since these are constants, we can directly use them without mocking.
        "dangerous_patterns": Constants.ContentSanitizer.DANGEROUS_PATTERNS_REGEX,
        "executable_extensions": Constants.ContentSanitizer.EXECUTABLE_EXTENSIONS,
        "file_size_limits_in_bytes": Constants.ContentSanitizer.FILE_SIZE_LIMITS_IN_BYTES,
        "format_names": Constants.ContentSanitizer.FORMAT_NAMES,
        "pii_detection_regex": Constants.ContentSanitizer.PII_DETECTION_REGEX,
        "remove_active_content_regex": Constants.ContentSanitizer.REMOVE_ACTIVE_CONTENT_REGEX,
        "remove_scripts_regex": Constants.ContentSanitizer.REMOVE_SCRIPTS_REGEX,
        "security_rules": Constants.ContentSanitizer.SECURITY_RULES,
        "sensitive_keys": Constants.ContentSanitizer.SENSITIVE_KEYS,
    }
    return constants_resources


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


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
        f.write("#!/bin/sh\necho 'Hello, world!'")

    # Make it executable
    os.chmod(executable_file_path, 0o755)

    # Check if the file is executable
    if os.name == 'nt':
        pass
    else:
        # On Unix-like systems, we can check if the file is executable
        if not os.access(executable_file_path, os.X_OK):
            raise PermissionError(f"File {executable_file_path} is not executable")

    return {
        'test_file_path': test_file_path,
        'large_file_path': large_file_path,
        'executable_file_path': executable_file_path
    }


@pytest.fixture
def mock_configs():
    """Create mock configs for testing."""
    return MagicMock(spec=Configs)


@pytest.fixture
def mock_content():
    """Create mock Content object for sanitization tests."""
    mock_content = MagicMock(spec=Content)
    mock_content.text = "Test text"
    mock_content.metadata = {"format": "txt"}
    mock_content.sections = [{"title": "Section 1", "content": "Content 1"}]
    mock_content.source_format = "txt"
    mock_content.source_path = "/path/to/file.txt"
    return mock_content


@pytest.fixture
def mock_sanitized_content(mock_content):
    """Create mock SanitizedContent object for testing."""
    mock_sanitized_content = MagicMock(spec=SanitizedContent)
    mock_sanitized_content.content = mock_content
    mock_sanitized_content.sanitization_applied = ["remove_scripts", "remove_personal_data"]
    mock_sanitized_content.removed_content = {"scripts": 2, "personal_data": 3}
    return mock_sanitized_content


@pytest.fixture
def mock_resources():
    """Create mock resources for testing."""
    mock_resources = {
        **make_constants_resources(),
        "logger": MagicMock(spec=Logger),
        "security_result": SecurityResult,
        "sanitized_content": SanitizedContent,
        "check_archive_security": MagicMock(return_value=[]),
        "check_document_security": MagicMock(return_value=[]),
        "check_image_security": MagicMock(return_value=[]),
        "check_video_security": MagicMock(return_value=[]),
        "check_audio_security": MagicMock(return_value=[]),
    }
    return mock_resources


@pytest.fixture
def security_monitor(mock_resources, mock_configs):
    """Create SecurityMonitor instance for testing."""
    return SecurityMonitor(resources=mock_resources, configs=mock_configs)


@pytest.mark.unit
class TestSanitizedContent:
    """Test the SanitizedContent class."""

    def test_sanitized_content_init(self, mock_content):
        """Test SanitizedContent initialization."""
        sanitized = SanitizedContent(
            content=mock_content,
            sanitization_applied=["remove_scripts", "remove_personal_data"],
            removed_content={"scripts": 2, "personal_data": 3}
        )
        
        assert sanitized.content.text == "Test text"
        assert sanitized.content.metadata["format"] == "txt"
        assert len(sanitized.content.sections) == 1
        assert sanitized.content.source_format == "txt"
        assert sanitized.content.source_path == "/path/to/file.txt"
        assert len(sanitized.sanitization_applied) == 2
        assert sanitized.removed_content["scripts"] == 2
        assert sanitized.removed_content["personal_data"] == 3

    def test_sanitized_content_to_dict(self, test_files):
        """Test SanitizedContent.to_dict()."""
        mock_content = Content( # Use Content class with mock data
            text="Test text",
            metadata={"format": "txt"},
            sections=[{"title": "Section 1", "content": "Content 1"}],
            source_format="txt",
            source_path=test_files['test_file_path']
        )
        sanitized = SanitizedContent(
            content=mock_content,
            sanitization_applied=["remove_scripts", "remove_personal_data"],
            removed_content={"scripts": 2, "personal_data": 3}
        )
        
        result_dict = sanitized.to_dict()
        debug_logger.debug(f"Sanitized content dict: {result_dict}")
        
        assert result_dict["text"] == "Test text"
        assert result_dict["metadata"]["format"] == "txt"
        assert len(result_dict["sections"]) == 1
        assert result_dict["source_format"] == "txt"
        assert str(result_dict["source_path"]) == test_files['test_file_path']
        assert len(result_dict["sanitization_applied"]) == 2
        assert result_dict["removed_content"]["scripts"] == 2
        assert result_dict["removed_content"]["personal_data"] == 3