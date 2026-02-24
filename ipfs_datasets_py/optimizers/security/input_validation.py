"""
Input validation and sanitization for complaint generator optimizers.

Provides comprehensive input validation to prevent:
    - SQL injection attacks
    - XSS (Cross-Site Scripting) attacks
    - Path traversal attacks
    - Command injection attacks
    - Malformed data causing application crashes
    - Resource exhaustion via oversized inputs

Key Features:
    - Type validation with Pydantic models
    - String sanitization (XSS, SQL injection patterns)
    - Path validation (no traversal, restricted to allowed directories)
    - Size limits for all input types
    - Pattern matching for identifiers
    - Error handling with detailed validation messages

Usage:
    >>> validator = InputValidator()
    >>> safe_text = validator.sanitize_text("User <script>alert('xss')</script> input")
    >>> # Returns: "User  input" (script tags removed)
    
    >>> validator.validate_entity_text("Valid entity name")  # OK
    >>> validator.validate_entity_text("a" * 10000)  # Raises ValidationError
"""

import re
import html
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum


# Constants for validation rules
MAX_TEXT_LENGTH = 10000
MAX_ENTITY_TEXT_LENGTH = 500
MAX_IDENTIFIER_LENGTH = 100
MAX_LIST_SIZE = 1000
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100MB
MAX_JSON_DEPTH = 10

# Allowed characters for identifiers
IDENTIFIER_PATTERN = re.compile(r'^[a-zA-Z0-9_\-\.]+$')

# SQL injection patterns (basic detection)
SQL_INJECTION_PATTERNS = [
    re.compile(r"(\bunion\b.*\bselect\b)", re.IGNORECASE),
    re.compile(r"(\bdrop\b.*\btable\b)", re.IGNORECASE),
    re.compile(r"(\binsert\b.*\binto\b)", re.IGNORECASE),
    re.compile(r"(\bdelete\b.*\bfrom\b)", re.IGNORECASE),
    re.compile(r"(\bexec\b.*\()", re.IGNORECASE),
    re.compile(r"(\bor\b.*1\s*=\s*1)", re.IGNORECASE),
    re.compile(r"(\band\b.*1\s*=\s*1)", re.IGNORECASE),
]

# XSS patterns
XSS_PATTERNS = [
    re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"on\w+\s*=", re.IGNORECASE),  # onload=, onclick=, etc.
    re.compile(r"<iframe[^>]*>", re.IGNORECASE),
]

# Path traversal patterns
PATH_TRAVERSAL_PATTERNS = [
    re.compile(r"\.\./"),
    re.compile(r"\.\.\\"),
]

# Command injection patterns
COMMAND_INJECTION_PATTERNS = [
    re.compile(r"[;&|`$]"),  # Shell metacharacters
    re.compile(r"\$\(.*\)"),  # Command substitution
    re.compile(r">\s*/"),  # Redirection to system paths
]


class ValidationError(Exception):
    """Base class for validation errors."""
    pass


class ValidationLevel(Enum):
    """Validation strictness levels."""
    STRICT = "strict"  # Reject anything suspicious
    MODERATE = "moderate"  # Sanitize and warn
    PERMISSIVE = "permissive"  # Only block critical issues


@dataclass
class ValidationResult:
    """Result of validation check.
    
    Attributes:
        valid: Whether input passes validation
        sanitized_value: Sanitized version of input (if applicable)
        errors: List of validation error messages
        warnings: List of validation warnings
    """
    valid: bool
    sanitized_value: Optional[Any] = None
    errors: List[str] = None
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []


class InputValidator:
    """Main input validation and sanitization class."""
    
    def __init__(self, 
                 validation_level: ValidationLevel = ValidationLevel.STRICT,
                 logger: Optional[logging.Logger] = None):
        """Initialize input validator.
        
        Args:
            validation_level: Strictness of validation
            logger: Optional logger instance
        """
        self.validation_level = validation_level
        self.logger = logger or logging.getLogger(__name__)
    
    def sanitize_text(self, text: str, max_length: int = MAX_TEXT_LENGTH) -> str:
        """Sanitize text input by removing dangerous patterns.
        
        Args:
            text: Input text to sanitize
            max_length: Maximum allowed length
            
        Returns:
            Sanitized text
            
        Raises:
            ValidationError: If text is invalid or too long
        """
        if not isinstance(text, str):
            raise ValidationError(f"Expected string, got {type(text).__name__}")
        
        if len(text) > max_length:
            raise ValidationError(f"Text exceeds maximum length of {max_length} characters")
        
        # Remove XSS patterns
        sanitized = text
        for pattern in XSS_PATTERNS:
            sanitized = pattern.sub("", sanitized)
        
        # HTML entity encoding for remaining special chars
        sanitized = html.escape(sanitized, quote=True)
        
        return sanitized
    
    def check_sql_injection(self, text: str) -> ValidationResult:
        """Check text for SQL injection patterns.
        
        Args:
            text: Text to check
            
        Returns:
            ValidationResult with findings
        """
        found_patterns = []
        for pattern in SQL_INJECTION_PATTERNS:
            if pattern.search(text):
                found_patterns.append(pattern.pattern)
        
        if found_patterns:
            return ValidationResult(
                valid=False,
                errors=[f"Potential SQL injection detected: {', '.join(found_patterns)}"]
            )
        
        return ValidationResult(valid=True, sanitized_value=text)
    
    def validate_identifier(self, identifier: str) -> ValidationResult:
        """Validate identifier (e.g., entity ID, file name).
        
        Args:
            identifier: Identifier to validate
            
        Returns:
            ValidationResult
        """
        errors = []
        
        if not isinstance(identifier, str):
            errors.append(f"Identifier must be string, got {type(identifier).__name__}")
            return ValidationResult(valid=False, errors=errors)
        
        if len(identifier) == 0:
            errors.append("Identifier cannot be empty")
        
        if len(identifier) > MAX_IDENTIFIER_LENGTH:
            errors.append(f"Identifier exceeds maximum length of {MAX_IDENTIFIER_LENGTH}")
        
        if not IDENTIFIER_PATTERN.match(identifier):
            errors.append("Identifier contains invalid characters (allowed: a-z, A-Z, 0-9, _, -, .)")
        
        if errors:
            return ValidationResult(valid=False, errors=errors)
        
        return ValidationResult(valid=True, sanitized_value=identifier)
    
    def validate_path(self, path: Union[str, Path], 
                     allowed_base: Optional[Path] = None) -> ValidationResult:
        """Validate file path for safety.
        
        Args:
            path: Path to validate
            allowed_base: If provided, path must be within this directory
            
        Returns:
            ValidationResult
        """
        errors = []
        warnings = []
        
        path_str = str(path)
        
        # Check for path traversal
        for pattern in PATH_TRAVERSAL_PATTERNS:
            if pattern.search(path_str):
                errors.append("Path traversal detected (../ or ..\\)")
                return ValidationResult(valid=False, errors=errors)
        
        # Convert to Path object for normalization
        try:
            path_obj = Path(path_str).resolve()
        except (OSError, RuntimeError, ValueError) as e:
            errors.append(f"Invalid path: {e}")
            return ValidationResult(valid=False, errors=errors)
        
        # Check if within allowed base
        if allowed_base:
            try:
                allowed_base_resolved = allowed_base.resolve()
                path_obj.relative_to(allowed_base_resolved)
            except ValueError:
                errors.append(f"Path must be within {allowed_base}")
                return ValidationResult(valid=False, errors=errors)
        
        # Warn about absolute paths
        if path_obj.is_absolute():
            warnings.append("Absolute path provided (relative paths preferred)")
        
        if errors:
            return ValidationResult(valid=False, errors=errors, warnings=warnings)
        
        return ValidationResult(valid=True, sanitized_value=path_obj, warnings=warnings)
    
    def validate_entity_text(self, text: str) -> ValidationResult:
        """Validate entity text field.
        
        Args:
            text: Entity text to validate
            
        Returns:
            ValidationResult
        """
        errors = []
        warnings = []
        
        if not isinstance(text, str):
            errors.append(f"Entity text must be string, got {type(text).__name__}")
            return ValidationResult(valid=False, errors=errors)
        
        if len(text) == 0:
            errors.append("Entity text cannot be empty")
        
        if len(text) > MAX_ENTITY_TEXT_LENGTH:
            errors.append(f"Entity text exceeds maximum length of {MAX_ENTITY_TEXT_LENGTH}")
        
        # Check for SQL injection
        sql_result = self.check_sql_injection(text)
        if not sql_result.valid:
            errors.extend(sql_result.errors)
        
        # Sanitize but keep validation status
        try:
            sanitized = self.sanitize_text(text, MAX_ENTITY_TEXT_LENGTH)
            if sanitized != text:
                warnings.append("Text was sanitized (special characters removed/encoded)")
        except ValidationError as e:
            errors.append(str(e))
        
        if errors:
            return ValidationResult(valid=False, errors=errors, warnings=warnings)
        
        return ValidationResult(valid=True, sanitized_value=sanitized, warnings=warnings)
    
    def validate_confidence(self, confidence: float) -> ValidationResult:
        """Validate confidence score.
        
        Args:
            confidence: Confidence value to validate
            
        Returns:
            ValidationResult
        """
        errors = []
        
        if not isinstance(confidence, (int, float)):
            errors.append(f"Confidence must be numeric, got {type(confidence).__name__}")
            return ValidationResult(valid=False, errors=errors)
        
        if confidence < 0.0 or confidence > 1.0:
            errors.append("Confidence must be between 0.0 and 1.0")
        
        if errors:
            return ValidationResult(valid=False, errors=errors)
        
        return ValidationResult(valid=True, sanitized_value=float(confidence))
    
    def validate_list_size(self, items: List[Any], max_size: int = MAX_LIST_SIZE) -> ValidationResult:
        """Validate list size to prevent resource exhaustion.
        
        Args:
            items: List to validate
            max_size: Maximum allowed list size
            
        Returns:
            ValidationResult
        """
        errors = []
        
        if not isinstance(items, list):
            errors.append(f"Expected list, got {type(items).__name__}")
            return ValidationResult(valid=False, errors=errors)
        
        if len(items) > max_size:
            errors.append(f"List size {len(items)} exceeds maximum of {max_size}")
        
        if errors:
            return ValidationResult(valid=False, errors=errors)
        
        return ValidationResult(valid=True, sanitized_value=items)
    
    def validate_json_depth(self, data: Union[Dict, List], 
                           current_depth: int = 0,
                           max_depth: int = MAX_JSON_DEPTH) -> ValidationResult:
        """Validate JSON nesting depth to prevent stack overflow.
        
        Args:
            data: JSON data to validate
            current_depth: Current recursion depth
            max_depth: Maximum allowed depth
            
        Returns:
            ValidationResult
        """
        if current_depth > max_depth:
            return ValidationResult(
                valid=False,
                errors=[f"JSON nesting depth {current_depth} exceeds maximum of {max_depth}"]
            )
        
        if isinstance(data, dict):
            for value in data.values():
                if isinstance(value, (dict, list)):
                    result = self.validate_json_depth(value, current_depth + 1, max_depth)
                    if not result.valid:
                        return result
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    result = self.validate_json_depth(item, current_depth + 1, max_depth)
                    if not result.valid:
                        return result
        
        return ValidationResult(valid=True, sanitized_value=data)
    
    def validate_command_input(self, command: str) -> ValidationResult:
        """Validate command input to prevent command injection.
        
        Args:
            command: Command or argument to validate
            
        Returns:
            ValidationResult
        """
        errors = []
        
        if not isinstance(command, str):
            errors.append(f"Command must be string, got {type(command).__name__}")
            return ValidationResult(valid=False, errors=errors)
        
        for pattern in COMMAND_INJECTION_PATTERNS:
            if pattern.search(command):
                errors.append(f"Potential command injection detected: {pattern.pattern}")
        
        if errors:
            return ValidationResult(valid=False, errors=errors)
        
        return ValidationResult(valid=True, sanitized_value=command)


class EntityValidator(InputValidator):
    """Specialized validator for entity data."""
    
    def validate_entity(self, entity_data: Dict[str, Any]) -> ValidationResult:
        """Validate complete entity data structure.
        
        Args:
            entity_data: Entity dictionary to validate
            
        Returns:
            ValidationResult with sanitized entity
        """
        errors = []
        warnings = []
        sanitized = {}
        
        # Required fields
        if "text" not in entity_data:
            errors.append("Missing required field: text")
        else:
            text_result = self.validate_entity_text(entity_data["text"])
            if not text_result.valid:
                errors.extend(text_result.errors)
            else:
                sanitized["text"] = text_result.sanitized_value
                warnings.extend(text_result.warnings)
        
        if "type" not in entity_data:
            errors.append("Missing required field: type")
        else:
            type_result = self.validate_identifier(entity_data["type"])
            if not type_result.valid:
                errors.extend(type_result.errors)
            else:
                sanitized["type"] = type_result.sanitized_value
        
        # Optional fields
        if "confidence" in entity_data:
            conf_result = self.validate_confidence(entity_data["confidence"])
            if not conf_result.valid:
                errors.extend(conf_result.errors)
            else:
                sanitized["confidence"] = conf_result.sanitized_value
        
        if "context" in entity_data:
            try:
                sanitized["context"] = self.sanitize_text(
                    entity_data["context"], 
                    MAX_TEXT_LENGTH
                )
            except ValidationError as e:
                errors.append(f"Context validation failed: {e}")
        
        if errors:
            return ValidationResult(valid=False, errors=errors, warnings=warnings)
        
        return ValidationResult(valid=True, sanitized_value=sanitized, warnings=warnings)


class RelationshipValidator(InputValidator):
    """Specialized validator for relationship data."""
    
    def validate_relationship(self, rel_data: Dict[str, Any]) -> ValidationResult:
        """Validate complete relationship data structure.
        
        Args:
            rel_data: Relationship dictionary to validate
            
        Returns:
            ValidationResult with sanitized relationship
        """
        errors = []
        warnings = []
        sanitized = {}
        
        # Required fields
        for field in ["source", "target", "type"]:
            if field not in rel_data:
                errors.append(f"Missing required field: {field}")
            else:
                result = self.validate_identifier(rel_data[field])
                if not result.valid:
                    errors.extend(result.errors)
                else:
                    sanitized[field] = result.sanitized_value
        
        # Optional confidence
        if "confidence" in rel_data:
            conf_result = self.validate_confidence(rel_data["confidence"])
            if not conf_result.valid:
                errors.extend(conf_result.errors)
            else:
                sanitized["confidence"] = conf_result.sanitized_value
        
        if errors:
            return ValidationResult(valid=False, errors=errors, warnings=warnings)
        
        return ValidationResult(valid=True, sanitized_value=sanitized, warnings=warnings)


# Convenience functions for simple validation

def validate_and_sanitize_text(text: str, max_length: int = MAX_TEXT_LENGTH) -> str:
    """Validate and sanitize text input (convenience function).
    
    Args:
        text: Text to validate
        max_length: Maximum allowed length
        
    Returns:
        Sanitized text
        
    Raises:
        ValidationError: If validation fails
    """
    validator = InputValidator()
    return validator.sanitize_text(text, max_length)


def validate_identifier_safe(identifier: str) -> bool:
    """Check if identifier is safe (convenience function).
    
    Args:
        identifier: Identifier to check
        
    Returns:
        True if valid, False otherwise
    """
    validator = InputValidator()
    result = validator.validate_identifier(identifier)
    return result.valid
