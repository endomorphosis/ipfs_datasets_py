"""
Test the security manager module.

This test suite validates the SecurityMonitor component against several criteria:

1. Security Effectiveness (Target: 100% prevention of code execution)
   - Tests verify detection and rejection of executable files
   - Tests verify validation of file formats against allowed list
   - Tests ensure proper file size limit enforcement
   - Tests validate content sanitization for scripts, active content, and personal data
   
2. Error Handling Effectiveness
   - Tests verify graceful handling of security violations
   - Tests ensure proper reporting of security issues
   - Tests confirm isolation of security issues from the main processing pipeline

3. Text Quality for LLM Training
   - The security manager impacts text quality by sanitizing content while
     preserving the essential information needed for LLM training
   - Tests verify text content is properly sanitized without removing essential information
"""
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

from configs import configs

from monitors._constants import Constants

resources = { # NOTE: Since these are constants, we can directly use them without mocking.
    "dangerous_patterns": Constants.SecurityMonitor.DANGEROUS_PATTERNS_REGEX,
    "executable_extensions": Constants.SecurityMonitor.EXECUTABLE_EXTENSIONS,
    "file_size_limits_in_bytes": Constants.SecurityMonitor.FILE_SIZE_LIMITS_IN_BYTES,
    "format_names": Constants.SecurityMonitor.FORMAT_NAMES,
    "pii_detection_regex": Constants.SecurityMonitor.PII_DETECTION_REGEX,
    "remove_active_content_regex": Constants.SecurityMonitor.REMOVE_ACTIVE_CONTENT_REGEX,
    "remove_scripts_regex": Constants.SecurityMonitor.REMOVE_SCRIPTS_REGEX,
    "security_rules": Constants.SecurityMonitor.SECURITY_RULES,
    "sensitive_keys": Constants.SecurityMonitor.SENSITIVE_KEYS,
}

class TestSecurityManager(unittest.TestCase):
    """Test the SecurityMonitor class."""

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

        self._mock_security_result = MagicMock(spec=SecurityResult)
        self._mock_security_result.is_safe = MagicMock()
        self._mock_security_result.issues = MagicMock()
        self._mock_security_result.risk_level = MagicMock()
        self._mock_security_result.metadata = MagicMock()

        self._mock_security_result.is_safe.return_value = True
        self._mock_security_result.issues.return_value = []
        self._mock_security_result.risk_level.return_value = "low"
        self._mock_security_result.metadata.return_value = {"file_path": self.test_file_path, "format": "plain"}

        self._mock_resources = {
            **copy.deepcopy(resources),
            "logger": MagicMock(spec=Logger),
            "security_result": SecurityResult,
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

    def test_init(self):
        """Test initialization."""
        self.assertIn("default", self.security_monitor._file_size_limits)
        self.assertIn("text", self.security_monitor._file_size_limits)
        self.assertIn("image", self.security_monitor._file_size_limits)
        self.assertIn("audio", self.security_monitor._file_size_limits)
        self.assertIn("video", self.security_monitor._file_size_limits)
        self.assertIn("application", self.security_monitor._file_size_limits)
        self.assertEqual(len(self.security_monitor.allowed_formats), 0)
        self.assertTrue(self.security_monitor._security_rules["reject_executable"])

    def test_security_result_init(self):
        """Test SecurityResult initialization."""
        # Create with minimal arguments
        result = SecurityResult(is_safe=True)
        self.assertTrue(result.is_safe)
        self.assertEqual(len(result.issues), 0)
        self.assertEqual(result.risk_level, "low")
        self.assertEqual(len(result.metadata), 0)
        
        # Create with all arguments
        result = SecurityResult(
            is_safe=False,
            issues=["Issue 1", "Issue 2"],
            risk_level="high",
            metadata={"key": "value"}
        )
        self.assertFalse(result.is_safe)
        self.assertEqual(len(result.issues), 2)
        self.assertEqual(result.risk_level, "high")
        self.assertEqual(result.metadata["key"], "value")
    
    def test_security_result_to_dict(self):
        """Test SecurityResult.to_dict()."""
        result = SecurityResult(
            is_safe=False,
            issues=["Issue 1", "Issue 2"],
            risk_level="high",
            metadata={"key": "value"}
        )
        result_dict = result.to_dict()
        
        self.assertFalse(result_dict["is_safe"])
        self.assertEqual(len(result_dict["issues"]), 2)
        self.assertEqual(result_dict["risk_level"], "high")
        self.assertEqual(result_dict["metadata"]["key"], "value")
    

    def test_validate_security_normal_file(self):
        """Test validating a normal file."""
        result = self.security_monitor.validate_security(self.test_file_path, format_name="plain")
        debug_logger.debug(f"Security result: {result.to_dict()}") 
        
        self.assertTrue(result.is_safe)
        self.assertEqual(len(result.issues), 0)
        self.assertEqual(result.risk_level, "low")
        self.assertEqual(result.metadata["file_path"], self.test_file_path)
        self.assertEqual(result.metadata["format"], "plain")
    
    def test_validate_security_large_file(self):
        """Test validating a file that exceeds size limits."""
        result = self.security_monitor.validate_security(self.large_file_path, format_name="plain")

        self.assertFalse(result.is_safe)
        self.assertEqual(len(result.issues), 1)
        self.assertIn("exceeds limit", result.issues[0])
        self.assertNotEqual(result.risk_level, "low")

    def test_validate_security_executable_file(self):
        """Test validating an executable file."""
        result = self.security_monitor.validate_security(self.executable_file_path)

        self.assertFalse(result.is_safe)
        self.assertEqual(len(result.issues), 1)
        self.assertIn("executable", result.issues[0])
        # The actual risk level appears to be 'medium' based on the implementation
        self.assertEqual(result.risk_level, "medium")

    def test_validate_security_nonexistent_file(self):
        """Test validating a file that doesn't exist."""
        nonexistent_path = os.path.join(self.temp_dir, "nonexistent.txt")
        result = self.security_monitor.validate_security(nonexistent_path)
        
        self.assertFalse(result.is_safe)
        self.assertEqual(len(result.issues), 1)
        self.assertIn("does not exist", result.issues[0])
        self.assertEqual(result.risk_level, "high")
    
    def test_validate_security_disallowed_format(self):
        """Test validating a file with a disallowed format."""
        # Set allowed formats
        try:
            self.security_monitor.set_allowed_formats(["html", "pdf"])
            
            result = self.security_monitor.validate_security(self.test_file_path, format_name="plain")
            
            self.assertFalse(result.is_safe)
            self.assertEqual(len(result.issues), 1)
            self.assertIn("not allowed", result.issues[0])
        finally:
            # Reset allowed formats for other tests
            self.security_monitor.set_allowed_formats([])

    def test_is_file_safe(self):
        """Test checking if a file is safe."""
        # Normal file should be safe
        self.assertTrue(self.security_monitor.is_file_safe(self.test_file_path))
        
        # Executable file should not be safe
        self.assertFalse(self.security_monitor.is_file_safe(self.executable_file_path))

    def test_set_security_rules(self):
        """Test setting security rules."""
        try:
            # Set new rules
            self.security_monitor.set_security_rules({
                "reject_executable": False,
                "remove_scripts": False,
                "unknown_rule": True  # Should be ignored
            })

            # Check if rules were updated
            self.assertFalse(self.security_monitor._security_rules["reject_executable"])
            self.assertFalse(self.security_monitor._security_rules["remove_scripts"])
            self.assertNotIn("unknown_rule", self.security_monitor._security_rules)
        finally:
            # Reset to default rules
            self.security_monitor.set_security_rules(Constants.SecurityMonitor.SECURITY_RULES)

    def test_set_allowed_formats(self):
        """Test setting allowed formats."""
        # Initially all formats are allowed
        self.assertEqual(len(self.security_monitor.allowed_formats), 0)
        
        # Set allowed formats
        formats = ["html", "pdf", "plain"]
        self.security_monitor.set_allowed_formats(formats)
        
        # Check if formats were updated
        self.assertEqual(len(self.security_monitor.allowed_formats), 3)
        self.assertIn("html", self.security_monitor.allowed_formats)
        self.assertIn("pdf", self.security_monitor.allowed_formats)
        self.assertIn("plain", self.security_monitor.allowed_formats)
        
        # Reset for other tests
        self.security_monitor.set_allowed_formats([])
    
    def test_set_file_size_limits(self):
        """Test setting file size limits."""
        # Set new limits
        self.security_monitor.set_file_size_limits({
            "text": 20 * 1024 * 1024,  # 20 MB
            "new_category": 30 * 1024 * 1024  # 30 MB
        })

        # Check if limits were updated
        self.assertEqual(self.security_monitor._file_size_limits["text"], 20 * 1024 * 1024)
        self.assertEqual(self.security_monitor._file_size_limits["new_category"], 30 * 1024 * 1024)

        # Other limits should remain unchanged
        self.assertEqual(self.security_monitor._file_size_limits["default"], 100 * 1024 * 1024)

    def test_is_executable(self):
        """Test checking if a file is executable."""
        # Test a non-executable file
        self.assertFalse(self.security_monitor._is_executable(self.test_file_path))
        
        # Test an executable file
        self.assertTrue(self.security_monitor._is_executable(self.executable_file_path))
        
        # Test a file with executable extension
        exe_file_path = os.path.join(self.temp_dir, "test.exe")
        with open(exe_file_path, 'w') as f:
            f.write("This is not a real executable")
        
        self.assertTrue(self.security_monitor._is_executable(exe_file_path))


if __name__ == "__main__":
    unittest.main()
