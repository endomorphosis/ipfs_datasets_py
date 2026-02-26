"""Batch 330: Credential Redaction Implementation

Provides credential and PII redaction utilities for secure logging.
Prevents sensitive data from appearing in logs, error messages, and outputs.

Usage:
    from .credential_redaction import CredentialRedactor
    
    redactor = CredentialRedactor()
    result = redactor.redact(log_message)
    
    # For dictionaries:
    safe_dict = redactor.redact_dict(data)

"""

from typing import Any, Dict, List, Optional, Pattern
from dataclasses import dataclass, field
from enum import Enum
import re


class CredentialType(Enum):
    """Types of credentials."""
    PASSWORD = "password"
    API_KEY = "api_key"
    TOKEN = "token"
    DATABASE_URL = "database_url"


class CredentialRedactor:
    """Redacts credentials and PII from text and dictionaries."""
    
    DEFAULT_SENSITIVE_KEYS = {
        'password', 'passwd', 'pwd',
        'token', 'api_key', 'apikey',
        'secret', 'private_key',
        'credential', 'credentials',
    }
    
    def __init__(self, custom_patterns: Optional[Dict[str, str]] = None):
        """Initialize redactor with optional custom patterns."""
        self.patterns = custom_patterns or {}
    
    def redact(self, text: str) -> str:
        """Redact credentials and PII from text.
        
        Args:
            text: Text to redact
            
        Returns:
            Redacted text with sensitive data replaced
        """
        if not text:
            return text
        
        redacted = text
        
        # Password patterns
        redacted = re.sub(r'password["\'\s=:]*([^"\s,;\n]+)', '[PASSWORD]', redacted, flags=re.IGNORECASE)
        
        # API key patterns
        redacted = re.sub(r'api[_-]?key["\'\s=:]*([^"\s,;\n]+)', '[API_KEY]', redacted, flags=re.IGNORECASE)
        
        # Token patterns
        redacted = re.sub(r'token["\'\s=:]*([^"\s,;\n]+)', '[TOKEN]', redacted, flags=re.IGNORECASE)
        
        # Email patterns
        redacted = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL]', redacted)
        
        # Phone patterns
        redacted = re.sub(r'\+?1?\s*\(?(\d{3})\)?[-.\s]?(\d{3})[-.\s]?(\d{4})', '[PHONE]', redacted)
        
        # SSN patterns
        redacted = re.sub(r'\d{3}-\d{2}-\d{4}', '[SSN]', redacted)
        
        # Database URLs
        redacted = re.sub(r'(postgresql|mysql|mongo|redis)://[^@]+@[^\s]+', '[REDACTED_DB_URL]', redacted)
        
        return redacted
    
    def redact_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Redact sensitive data from dictionary.
        
        Args:
            data: Dictionary to redact
            
        Returns:
            Dictionary with sensitive values replaced
        """
        redacted = {}
        for key, value in data.items():
            if self._is_sensitive_key(key):
                redacted[key] = '[REDACTED]'
            elif isinstance(value, str):
                redacted[key] = self.redact(value)
            elif isinstance(value, dict):
                redacted[key] = self.redact_dict(value)
            elif isinstance(value, list):
                redacted[key] = [
                    self.redact(v) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                redacted[key] = value
        return redacted
    
    @classmethod
    def _is_sensitive_key(cls, key: str) -> bool:
        """Check if key name indicates sensitive data."""
        return key.lower() in cls.DEFAULT_SENSITIVE_KEYS
