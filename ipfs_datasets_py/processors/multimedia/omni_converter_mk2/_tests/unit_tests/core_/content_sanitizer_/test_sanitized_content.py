




import copy
import os
import unittest
from unittest.mock import MagicMock, patch
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


class TestSanitizedContent(unittest.TestCase):
    """Test the SanitizedContent class."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a temp directory for test files
        self.temp_dir = tempfile.mkdtemp()
        
        # Create test files
        self.test_file_path = os.path.join(self.temp_dir, "test_file.txt")
        with open(self.test_file_path, 'w') as f:
            f.write("Test content")
        
        self.large_file_path = os.path.join(self.temp_dir, "large_file.txt")
        with open(self.large_file_path, 'w') as f:
            f.write("A" * (15 * 1024 * 1024))  # 15 MB file (exceeds text limit)
        
        self.executable_file_path = os.path.join(self.temp_dir, "test_script.sh")
        with open(self.executable_file_path, 'w') as f:
            f.write("#!/bin/sh\necho 'Hello, world!'")

        # Make it executable
        os.chmod(self.executable_file_path, 0o755)

        # Check if the file is executable
        if os.name == 'nt':
            pass
        else:
            # On Unix-like systems, we can check if the file is executable
            if not os.access(self.executable_file_path, os.X_OK):
                raise PermissionError(f"File {self.executable_file_path} is not executable")

        self.mock_configs = MagicMock(spec=Configs)

        # Mock Content object for sanitization tests
        self._mock_content = MagicMock(spec=Content)
        self._mock_content.text = "Test text"
        self._mock_content.metadata = {"format": "txt"}
        self._mock_content.sections = [{"title": "Section 1", "content": "Content 1"}]
        self._mock_content.source_format = "txt"
        self._mock_content.source_path = "/path/to/file.txt"

        self._mock_sanitized_content = MagicMock(spec=SanitizedContent)
        self._mock_sanitized_content.content = self._mock_content
        self._mock_sanitized_content.sanitization_applied = ["remove_scripts", "remove_personal_data"]
        self._mock_sanitized_content.removed_content = {"scripts": 2, "personal_data": 3}

        self._mock_resources = {
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

        # Create a security manager
        self.security_monitor = SecurityMonitor(resources=self._mock_resources, configs=self.mock_configs)

    def tearDown(self):
        """Clean up test fixtures."""
        # Remove temp directory
        shutil.rmtree(self.temp_dir)

    def test_sanitized_content_init(self):
        """Test SanitizedContent initialization."""
        sanitized = SanitizedContent(
            content=self._mock_content,
            sanitization_applied=["remove_scripts", "remove_personal_data"],
            removed_content={"scripts": 2, "personal_data": 3}
        )
        
        self.assertEqual(sanitized.content.text, "Test text")
        self.assertEqual(sanitized.content.metadata["format"], "txt")
        self.assertEqual(len(sanitized.content.sections), 1)
        self.assertEqual(sanitized.content.source_format, "txt")
        self.assertEqual(sanitized.content.source_path, "/path/to/file.txt")
        self.assertEqual(len(sanitized.sanitization_applied), 2)
        self.assertEqual(sanitized.removed_content["scripts"], 2)
        self.assertEqual(sanitized.removed_content["personal_data"], 3)

    def test_sanitized_content_to_dict(self):
        """Test SanitizedContent.to_dict()."""
        mock_content = Content( # Use Content class with mock data
            text="Test text",
            metadata={"format": "txt"},
            sections=[{"title": "Section 1", "content": "Content 1"}],
            source_format="txt",
            source_path=self.test_file_path
        )
        sanitized = SanitizedContent(
            content=mock_content,
            sanitization_applied=["remove_scripts", "remove_personal_data"],
            removed_content={"scripts": 2, "personal_data": 3}
        )
        
        result_dict = sanitized.to_dict()
        debug_logger.debug(f"Sanitized content dict: {result_dict}")
        
        self.assertEqual(result_dict["text"], "Test text")
        self.assertEqual(result_dict["metadata"]["format"], "txt")
        self.assertEqual(len(result_dict["sections"]), 1)
        self.assertEqual(result_dict["source_format"], "txt")
        self.assertEqual(str(result_dict["source_path"]), self.test_file_path)
        self.assertEqual(len(result_dict["sanitization_applied"]), 2)
        self.assertEqual(result_dict["removed_content"]["scripts"], 2)
        self.assertEqual(result_dict["removed_content"]["personal_data"], 3)



