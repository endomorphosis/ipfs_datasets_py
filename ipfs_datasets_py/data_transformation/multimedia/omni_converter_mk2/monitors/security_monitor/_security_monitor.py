"""
Security manager module for the Omni-Converter.

This module provides the SecurityMonitor class for security validation and content sanitization.
"""
from __future__ import annotations
from contextlib import closing
from enum import Enum, StrEnum
import os
import re
import zipfile
import tarfile
import tempfile


from types_ import Any, Callable, Optional, Configs, Logger, SecurityResult, ModuleType
from supported_formats import SupportedFormats

class RiskLevel(Enum):
    """Enum for security risk levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class SecurityMonitor:
    """
    Security manager for the Omni-Converter.
    
    This class handles security validation.
    
    Attributes:
        file_size_limits (dict[str, int]): Maximum file size limits by format (in bytes).
        allowed_formats (list[str]): list of allowed formats.
        security_rules (dict[str, Any]): Security rules for validation and sanitization.
    """

    def __init__(self, 
                 *,
                resources: dict[str, Callable], 
                configs: Configs
                ) -> None:
        """Initialize a security manager."""
        self.configs = configs
        self.resources = resources

        self._dangerous_patterns:    list[re.Pattern] = self.resources['dangerous_patterns']
        self._executable_extensions: list[str] = self.resources['executable_extensions']
        self._file_size_limits:      dict[str, int] = self.resources['file_size_limits_in_bytes']

        self._security_rules:           dict[str, Any]   = self.resources['security_rules']
        self._supported_formats_object: SupportedFormats = SupportedFormats # TODO Move this into the constructor after testing.
        self._security_result:          SecurityResult   = self.resources['security_result']
        self._logger:                   Logger           = self.resources['logger']

        self._check_archive_security:  Callable = self.resources['check_archive_security']
        self._check_document_security: Callable = self.resources['check_document_security']
        self._check_image_security:    Callable = self.resources['check_image_security']
        self._check_video_security:    Callable = self.resources['check_video_security']
        self._check_audio_security:    Callable = self.resources['check_audio_security']

        # All formats are allowed by default
        self.allowed_formats: list[str] = [] # Empty means all formats are allowed

    def validate_security(self, file_path: str, format_name: Optional[str] = None) -> 'SecurityResult':
        """
        Validate the security of a file.
        
        Args:
            file_path: The path to the file.
            format_name: The format of the file, if known.
            
        Returns:
            A SecurityResult object with the validation results.
        """
        issues = []
        is_safe = True
        risk_level = "low"
        metadata = {"file_path": file_path, "format": format_name}

        try:
            # Check if file exists
            if not os.path.exists(file_path):
                issues.append("File does not exist")
                return self._security_result(is_safe=False, issues=issues, risk_level="high", metadata=metadata)

            # Get file size
            metadata["file_size"] = file_size = os.path.getsize(file_path)

            # Check file size limits
            category_limit = None
            if format_name:
                # Try to get category from format name
                category = None
                if format_name in self._supported_formats_object.SUPPORTED_TEXT_FORMATS:
                    category = "text"
                elif format_name in self._supported_formats_object.SUPPORTED_IMAGE_FORMATS:
                    category = "image"
                elif format_name in self._supported_formats_object.SUPPORTED_AUDIO_FORMATS:
                    category = "audio"
                elif format_name in self._supported_formats_object.SUPPORTED_VIDEO_FORMATS:
                    category = "video"
                elif format_name in self._supported_formats_object.SUPPORTED_APPLICATION_FORMATS:
                    category = "application"
                else:
                    # If format is not recognized, 
                    issues.append(f"Unrecognized format name '{format_name}'")
                    return self._security_result(
                        is_safe=False, issues=issues, risk_level="high", metadata=metadata
                    )

                if category:
                    category_limit = self._file_size_limits[category]

            size_limit = category_limit or self._file_size_limits["default"]

            if file_size > size_limit:
                msg = f"File size {file_size} bytes exceeds limit of {size_limit} bytes for format '{format_name}'"
                self._logger.warning(msg)
                issues.append(msg)
                is_safe = False

            # Check if format is allowed
            if self.allowed_formats and format_name and format_name not in self.allowed_formats:
                issues.append(f"Format {format_name} is not allowed")
                is_safe = False

            # Check for executable files
            if self._security_rules["reject_executable"] and self._is_executable(file_path):
                issues.append("File appears to be executable")
                is_safe = False

            # Check for high-risk formats that may contain malicious content
            high_risk_formats = {
                "archive": ( # Check for archive/container formats that may contain malicious content
                    self._check_archive_security,
                    ["zip", "tar", "rar", "7z", "gz", "bz2", "xz"],
                    "high"
                ),
                "document": (  # Check for document formats that may contain macros or embedded content
                    self._check_document_security,
                    ["docx", "xlsx", "pptx", "doc", "xls", "ppt", "pdf", "odt", "ods", "odp"],
                    "medium"
                ),
                "image": ( # Check for image formats that may contain embedded payloads
                    self._check_image_security,
                    ["svg", "eps", "ps"],
                    "medium"
                ),
                "video": (
                    self._check_video_security,
                    [],
                    "medium"
                ),
                "audio": (
                    self._check_audio_security,
                    [],
                    "medium"
                )
            }
            for format_type, (check_func, formats, risk) in high_risk_formats.items():
                if format_name in formats:
                    self._logger.info(f"Running {format_type} security checks for {file_path}")
                    _issues = check_func(file_path, format_name)
                    if _issues:
                        self._logger.warning(f"{format_type.capitalize()} security issues found in {file_path}: {_issues}")
                        issues.extend(_issues)
                        is_safe = False
                        risk_level = risk
                        break

            # TODO Add additional checks for specific formats
                # We want to check for storage formats like zip, tar, etc.
                # As they may contain other files that might be malicious.
                # Or be malicious themselves (e.g. zip bombs).

            # Assess overall risk level
            if len(issues) > 5:
                risk_level = "critical"
            elif len(issues) > 2:
                risk_level = "high"
            elif len(issues) > 0:
                risk_level = "medium"
            else:
                risk_level = "low"

            return self._security_result(
                is_safe=is_safe, 
                issues=issues, 
                risk_level=risk_level, 
                metadata=metadata
            )

        except Exception as e:
            issues.append(f"Error during security validation: {e}")
            self._logger.error(f"Security validation error for {file_path}: {e}")
            return self._security_result(
                is_safe=False, 
                issues=issues, 
                risk_level="high", 
                metadata=metadata
            )

    def is_file_safe(self, file_path: str, format_name: Optional[str] = None) -> bool:
        """
        Check if a file is safe.
        
        Args:
            file_path: The path to the file.
            format_name: The format of the file, if known.
            
        Returns:
            True if the file is safe, False otherwise.
        """
        result = self.validate_security(file_path, format_name)
        return result.is_safe

    def _is_executable(self, file_path: str) -> bool:
        """
        Check if a file is executable.
        
        Args:
            file_path: The path to the file.
            
        Returns:
            True if the file is executable, False otherwise.
        """
        # Check file extension
        _, ext = os.path.splitext(file_path)

        if ext.lower() in self._executable_extensions:
            return True

        # Check if file has executable permissions (Unix only)
        try:
            if os.name == "nt":
                return False  # Windows does not support this check. # TODO Find a way to inform the user about this.
            return os.access(file_path, os.X_OK)
        except Exception:
            return False


    def set_security_rules(self, rules: dict[str, Any]) -> None:
        """Set the dictionary of security rules."""
        for key, value in rules.items():
            if key in self._security_rules:
                self._security_rules[key] = value
            else:
                self._logger.warning(f"Unknown security rule: {key}")
        
        self._logger.info("Security rules updated", {"rules": self._security_rules})


    def set_allowed_formats(self, formats: list[str]) -> None:
        """Set the list of allowed formats."""
        self.allowed_formats = formats
        self._logger.info(f"Allowed formats updated '{self.allowed_formats}'")
    

    def set_file_size_limits(self, limits: dict[str, int]) -> None:
        """Set file size limits.
        
        Args:
            limits: Dictionary of file size limits by format (in bytes).
        """
        for key, value in limits.items(): # TODO Add pydantic validation here.
            self._file_size_limits[key] = value
        
        self._logger.info(f"File size limits updated to '{self._file_size_limits}'")
    

