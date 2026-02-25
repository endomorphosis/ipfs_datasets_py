"""Log redaction utilities for sensitive data protection.

This module provides defensive redaction patterns for log messages to ensure
credentials and secrets never leak into logs, even if developers accidentally
log sensitive objects.

Usage:
    >>> from ipfs_datasets_py.optimizers.common.log_redaction import redact_sensitive
    >>> logger.info(redact_sensitive(potentially_sensitive_message))

or with structured logging filter:
    >>> from ipfs_datasets_py.optimizers.common.log_redaction import SensitiveDataFilter
    >>> logger.addFilter(SensitiveDataFilter())
"""

from __future__ import annotations

import logging
import re
from typing import Pattern


# Redaction patterns (pattern, replacement)
_REDACTION_PATTERNS: list[tuple[Pattern[str], str]] = [
    # API keys (various formats) - match common patterns like sk-xxx, ghp_xxx, etc.
    # Handles: api_key=xxx, api_key: xxx, "api_key": "xxx", 'api_key': 'xxx', {'api_key': 'xxx'}
    (re.compile(r'["\']?(api[_-]?key|apikey)["\']?\s*[:\=]\s*["\']?([a-zA-Z0-9_-]{6,})["\']?', re.IGNORECASE), r'\1=***REDACTED***'),
    
    # Bearer tokens
    (re.compile(r'\b(bearer\s+)([a-zA-Z0-9_.-]{10,})', re.IGNORECASE), r'\1***REDACTED***'),
    
    # Generic tokens (avoid matching "tokens_used" or other metrics)
    (re.compile(r'["\']?(auth[_-]?token|access[_-]?token)["\']?\s*[:\=]\s*["\']?([a-zA-Z0-9_.-]{10,})["\']?', re.IGNORECASE), r'\1=***REDACTED***'),
    
    # Passwords
    (re.compile(r'["\']?(password|passwd|pwd)["\']?\s*[:\=]\s*["\']?([^\s"\',}]+)["\']?', re.IGNORECASE), r'\1=***REDACTED***'),
    
    # Secrets
    (re.compile(r'["\']?(secret|secret[_-]?key)["\']?\s*[:\=]\s*["\']?([a-zA-Z0-9_.-]{6,})["\']?', re.IGNORECASE), r'\1=***REDACTED***'),
    
    # AWS credentials
    (re.compile(r'(AKIA[0-9A-Z]{16})', re.IGNORECASE), r'***REDACTED***'),
    
    # Private keys (PEM headers)
    (re.compile(r'(-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----[^-]+-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----)', re.IGNORECASE | re.DOTALL), r'***REDACTED PRIVATE KEY***'),
]


def redact_sensitive(text: str) -> str:
    """Redact sensitive data from text.
    
    Applies pattern-based redaction to remove:
    - API keys
    - Bearer tokens
    - Auth tokens
    - Passwords
    - Secrets
    - AWS credentials
    - Private keys
    
    Args:
        text: Input text that may contain sensitive data
        
    Returns:
        Text with sensitive data replaced by '***REDACTED***'
        
    Example:
        >>> redact_sensitive("api_key=sk-1234567890abcdef")
        'api_key=***REDACTED***'
        
        >>> redact_sensitive("password='hunter2'")
        'password=***REDACTED***'
        
        >>> redact_sensitive("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")
        'Bearer ***REDACTED***'
    """
    result = text
    for pattern, replacement in _REDACTION_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


class SensitiveDataFilter(logging.Filter):
    """Logging filter to redact sensitive data from log records.
    
    Install this filter on loggers that might receive sensitive data:
        
        >>> logger = logging.getLogger(__name__)
        >>> logger.addFilter(SensitiveDataFilter())
    
    The filter modifies log records in-place before emission.
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Apply redaction to log record message.
        
        Args:
            record: Log record to filter
            
        Returns:
            True (record is always emitted after redaction)
        """
        # Redact message
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            record.msg = redact_sensitive(record.msg)
        
        # For args, we need to be careful - they're used in formatting
        # So we can't just redact them, we need to format the message first then redact
        if hasattr(record, 'args') and record.args:
            try:
                # Format the message now with current args, then redact
                if record.args:
                    formatted_msg = record.msg % record.args
                    record.msg = redact_sensitive(formatted_msg)
                    record.args = ()  # Clear args since we already formatted
            except (TypeError, KeyError, ValueError):
                # If formatting fails, just redact the msg as-is
                pass
        
        return True


def add_redaction_to_logger(logger: logging.Logger) -> None:
    """Add sensitive data redaction filter to logger.
    
    Args:
        logger: Logger instance to protect
        
    Example:
        >>> import logging
        >>> logger = logging.getLogger(__name__)
        >>> add_redaction_to_logger(logger)
    """
    logger.addFilter(SensitiveDataFilter())


def redact_dict(data: dict) -> dict:
    """Redact sensitive values from dictionary (useful for logging config objects).
    
    Redacts values for keys containing sensitive names like 'password', 'key', 'token', 'secret'.
    Preserves metrics like 'tokens_used', 'max_tokens' (text token metrics, not auth tokens).
    
    Args:
        data: Dictionary to redact
        
    Returns:
        New dictionary with sensitive values replaced
        
    Example:
        >>> redact_dict({"api_key": "sk-12345", "max_retries": 3})
        {'api_key': '***REDACTED***', 'max_retries': 3}
    """
    # Exact matches for sensitive keys (case-insensitive)
    sensitive_keys = {
        'password', 'passwd', 'pwd',
        'api_key', 'apikey', 'api-key',
        'auth_token', 'auth-token', 'authtoken',
        'access_token', 'access-token', 'accesstoken',
        'bearer_token', 'bearer-token',
        'secret', 'secret_key', 'secret-key',
        'private_key', 'private-key', 'privatekey',
        'access_key', 'access-key', 'accesskey',
        'credential', 'credentials',
    }
    
    result = {}
    for key, value in data.items():
        key_lower = str(key).lower()
        # Check for exact match (not substring)
        if key_lower in sensitive_keys:
            result[key] = '***REDACTED***'
        elif isinstance(value, dict):
            result[key] = redact_dict(value)
        else:
            result[key] = value
    
    return result
