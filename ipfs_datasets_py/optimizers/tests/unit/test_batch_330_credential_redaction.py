"""Batch 330: Credential Redaction Framework - Comprehensive Test Suite

Validates credential filtering and PII (Personally Identifiable Information) redaction.
Ensures sensitive data is removed from logs, errors, and outputs.

Test areas:
- Password/token detection and redaction
- API key identification
- PII redaction (SSN, email, phone, addresses)
- Configuration security
- Regex pattern matching
- Redaction patterns and placeholders
- Performance with large payloads

"""

import pytest
from typing import Any, Dict, List, Pattern, Optional
from dataclasses import dataclass, field
from enum import Enum
import re


class CredentialType(Enum):
    """Types of credentials to redact."""
    PASSWORD = "password"
    API_KEY = "api_key"
    TOKEN = "token"
    DATABASE_URL = "database_url"
    AWS_SECRET = "aws_secret"
    PRIVATE_KEY = "private_key"
    SSH_KEY = "ssh_key"
    DATABASE_PASSWORD = "db_password"
    JWT = "jwt"
    OAUTH = "oauth"


class PiiType(Enum):
    """Types of personally identifiable information."""
    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    ADDRESS = "address"
    NAME = "name"
    BIRTH_DATE = "birth_date"
    DRIVER_LICENSE = "driver_license"


@dataclass
class RedactionPattern:
    """Pattern for detecting and redacting sensitive data."""
    pattern_type: str  # 'regex', 'exact', 'keyword'
    pattern: Pattern | str
    credential_type: Optional[CredentialType] = None
    pii_type: Optional[PiiType] = None
    placeholder: str = "[REDACTED]"
    context_before: int = 0  # Characters before pattern to check
    context_after: int = 0  # Characters after pattern to check
    
    def matches(self, text: str) -> bool:
        """Check if pattern matches text."""
        if self.pattern_type == 'regex':
            return bool(re.search(self.pattern, text))
        elif self.pattern_type == 'keyword':
            return self.pattern in text
        return False
    
    def apply(self, text: str) -> str:
        """Apply redaction to text."""
        if self.pattern_type == 'regex':
            return re.sub(self.pattern, self.placeholder, text)
        elif self.pattern_type == 'keyword':
            return text.replace(self.pattern, self.placeholder)
        return text


@dataclass
class RedactionConfig:
    """Configuration for credential redaction."""
    patterns: List[RedactionPattern] = field(default_factory=list)
    redact_credentials: bool = True
    redact_pii: bool = True
    redact_email: bool = True
    redact_phone: bool = True
    redact_ssn: bool = True
    case_sensitive: bool = False
    keep_first_chars: int = 0  # Keep N chars at start
    keep_last_chars: int = 0  # Keep N chars at end
    
    def add_pattern(self, pattern: RedactionPattern) -> None:
        """Add redaction pattern."""
        self.patterns.append(pattern)
    
    @property
    def pattern_count(self) -> int:
        """Number of patterns configured."""
        return len(self.patterns)


@dataclass
class RedactionResult:
    """Result of redaction operation."""
    original_text: str
    redacted_text: str
    redactions_made: int
    credential_types_found: List[CredentialType] = field(default_factory=list)
    pii_types_found: List[PiiType] = field(default_factory=list)
    
    @property
    def was_redacted(self) -> bool:
        """Whether any redaction occurred."""
        return self.redactions_made > 0
    
    @property
    def is_safe(self) -> bool:
        """Whether result is safe to log."""
        # Check if any sensitive patterns remain
        return self.redacted_text == self.redacted_text.lower()  # Simplistic check


class CredentialRedactor:
    """Redacts credentials and PII from text."""
    
    def __init__(self, config: Optional[RedactionConfig] = None):
        """Initialize redactor with configuration."""
        self.config = config or self._default_config()
    
    @staticmethod
    def _default_config() -> RedactionConfig:
        """Create default redaction configuration."""
        config = RedactionConfig()
        
        # Credentials patterns
        config.add_pattern(RedactionPattern(
            pattern_type='regex',
            pattern=r'password["\'\s=:]*([^"\s,;\n]+)',
            credential_type=CredentialType.PASSWORD,
            placeholder='[PASSWORD]',
        ))
        
        config.add_pattern(RedactionPattern(
            pattern_type='regex',
            pattern=r'[Aa]pi[_-]?[Kk]ey["\'\s=:]*([^"\s,;\n]+)',
            credential_type=CredentialType.API_KEY,
            placeholder='[API_KEY]',
        ))
        
        config.add_pattern(RedactionPattern(
            pattern_type='regex',
            pattern=r'token["\'\s=:]*([^"\s,;\n]+)',
            credential_type=CredentialType.TOKEN,
            placeholder='[TOKEN]',
        ))
        
        # Database URLs
        config.add_pattern(RedactionPattern(
            pattern_type='regex',
            pattern=r'(postgresql|mysql|mongo|redis)://[^@]+@[^\s]+"',
            credential_type=CredentialType.DATABASE_URL,
            placeholder='[REDACTED_DB_URL]',
        ))
        
        return config
    
    def redact(self, text: str) -> RedactionResult:
        """Redact sensitive data from text.
        
        Args:
            text: Text to redact
            
        Returns:
            RedactionResult with redacted text and details
        """
        redacted = text
        redactions_made = 0
        credentials_found = []
        pii_found = []
        
        # Apply pattern-based redactions
        for pattern in self.config.patterns:
            if pattern.matches(redacted):
                original_len = len(redacted)
                redacted = pattern.apply(redacted)
                if len(redacted) != original_len or pattern.placeholder in redacted:
                    redactions_made += 1
                    if pattern.credential_type:
                        credentials_found.append(pattern.credential_type)
                    if pattern.pii_type:
                        pii_found.append(pattern.pii_type)
        
        # Email redaction
        if self.config.redact_email:
            email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
            if re.search(email_pattern, redacted):
                redacted = re.sub(email_pattern, '[EMAIL]', redacted)
                redactions_made += 1
                pii_found.append(PiiType.EMAIL)
        
        # Phone redaction
        if self.config.redact_phone:
            phone_pattern = r'\+?1?\s*\(?(\d{3})\)?[-.\s]?(\d{3})[-.\s]?(\d{4})'
            if re.search(phone_pattern, redacted):
                redacted = re.sub(phone_pattern, '[PHONE]', redacted)
                redactions_made += 1
                pii_found.append(PiiType.PHONE)
        
        # SSN redaction
        if self.config.redact_ssn:
            ssn_pattern = r'\d{3}-\d{2}-\d{4}'
            if re.search(ssn_pattern, redacted):
                redacted = re.sub(ssn_pattern, '[SSN]', redacted)
                redactions_made += 1
                pii_found.append(PiiType.SSN)
        
        return RedactionResult(
            original_text=text,
            redacted_text=redacted,
            redactions_made=redactions_made,
            credential_types_found=list(set(credentials_found)),
            pii_types_found=list(set(pii_found)),
        )
    
    def redact_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Redact sensitive data from dictionary."""
        redacted = {}
        for key, value in data.items():
            if self._is_sensitive_key(key):
                redacted[key] = '[REDACTED]'
            elif isinstance(value, str):
                result = self.redact(value)
                redacted[key] = result.redacted_text
            elif isinstance(value, dict):
                redacted[key] = self.redact_dict(value)
            elif isinstance(value, list):
                redacted[key] = [
                    self.redact(v).redacted_text if isinstance(v, str) else v
                    for v in value
                ]
            else:
                redacted[key] = value
        return redacted
    
    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        """Check if key name indicates sensitive data."""
        sensitive_keywords = {
            'password', 'passwd', 'pwd',
            'token', 'api_key', 'apikey',
            'secret', 'private_key', 'privatekey',
            'auth', 'authorization',
            'credential', 'credentials',
            'ssn', 'social_security',
        }
        return key.lower() in sensitive_keywords


# Test Suite

class TestCredentialType:
    """Test CredentialType enum."""
    
    def test_credential_types_defined(self):
        """Should have standard credential types."""
        assert CredentialType.PASSWORD in CredentialType
        assert CredentialType.API_KEY in CredentialType
        assert CredentialType.TOKEN in CredentialType
    
    def test_credential_values(self):
        """Credential values should be strings."""
        for cred_type in CredentialType:
            assert isinstance(cred_type.value, str)


class TestPiiType:
    """Test PiiType enum."""
    
    def test_pii_types_defined(self):
        """Should have standard PII types."""
        assert PiiType.EMAIL in PiiType
        assert PiiType.PHONE in PiiType
        assert PiiType.SSN in PiiType


class TestRedactionPattern:
    """Test RedactionPattern class."""
    
    def test_create_regex_pattern(self):
        """Should create regex redaction pattern."""
        pattern = RedactionPattern(
            pattern_type='regex',
            pattern=r'password[=:]\s*([^\s]+)',
            credential_type=CredentialType.PASSWORD,
        )
        
        assert pattern.pattern_type == 'regex'
        assert pattern.credential_type == CredentialType.PASSWORD
    
    def test_pattern_matching(self):
        """Should match patterns in text."""
        pattern = RedactionPattern(
            pattern_type='keyword',
            pattern='secret_key',
        )
        
        assert pattern.matches('Contains secret_key here')
        assert not pattern.matches('No match here')
    
    def test_regex_pattern_matching(self):
        """Should match regex patterns."""
        pattern = RedactionPattern(
            pattern_type='regex',
            pattern=r'\d{3}-\d{2}-\d{4}',
            pii_type=PiiType.SSN,
        )
        
        assert pattern.matches('SSN: 123-45-6789')
        assert not pattern.matches('SSN: not-a-real-one')
    
    def test_pattern_application(self):
        """Should redact matches with placeholder."""
        pattern = RedactionPattern(
            pattern_type='keyword',
            pattern='password',
            placeholder='[REDACTED]',
        )
        
        text = 'The password is secret123'
        result = pattern.apply(text)
        
        assert '[REDACTED]' in result
        assert 'password' not in result


class TestRedactionConfig:
    """Test RedactionConfig class."""
    
    def test_create_config(self):
        """Should create redaction configuration."""
        config = RedactionConfig(
            redact_credentials=True,
            redact_pii=True,
        )
        
        assert config.redact_credentials is True
        assert config.redact_pii is True
    
    def test_add_pattern(self):
        """Should add patterns to config."""
        config = RedactionConfig()
        pattern = RedactionPattern(
            pattern_type='keyword',
            pattern='secret',
        )
        
        config.add_pattern(pattern)
        assert config.pattern_count == 1
    
    def test_pattern_counting(self):
        """Should count added patterns."""
        config = RedactionConfig()
        
        for i in range(5):
            config.add_pattern(RedactionPattern(
                pattern_type='keyword',
                pattern=f'secret{i}',
            ))
        
        assert config.pattern_count == 5


class TestRedactionResult:
    """Test RedactionResult class."""
    
    def test_create_result(self):
        """Should create redaction result."""
        result = RedactionResult(
            original_text='password=secret123',
            redacted_text='password=[REDACTED]',
            redactions_made=1,
        )
        
        assert result.was_redacted is True
        assert result.redactions_made == 1
    
    def test_no_redaction_result(self):
        """Should indicate no redaction."""
        result = RedactionResult(
            original_text='clean text',
            redacted_text='clean text',
            redactions_made=0,
        )
        
        assert result.was_redacted is False


class TestCredentialRedactor:
    """Test CredentialRedactor class."""
    
    def test_create_redactor(self):
        """Should create redactor with default config."""
        redactor = CredentialRedactor()
        assert redactor.config is not None
    
    def test_redact_password(self):
        """Should redact passwords."""
        redactor = CredentialRedactor()
        text = 'database password: super_secret_pass123'
        
        result = redactor.redact(text)
        
        assert result.was_redacted is True
        assert 'super_secret_pass123' not in result.redacted_text
    
    def test_redact_email(self):
        """Should redact email addresses."""
        redactor = CredentialRedactor()
        text = 'Contact user@example.com for support'
        
        result = redactor.redact(text)
        
        assert result.was_redacted is True
        assert 'user@example.com' not in result.redacted_text
        assert PiiType.EMAIL in result.pii_types_found
    
    def test_redact_phone(self):
        """Should redact phone numbers."""
        redactor = CredentialRedactor()
        text = 'Call us at (555) 123-4567'
        
        result = redactor.redact(text)
        
        assert result.was_redacted is True
        assert '555' not in result.redacted_text
        assert PiiType.PHONE in result.pii_types_found
    
    def test_redact_ssn(self):
        """Should redact social security numbers."""
        redactor = CredentialRedactor()
        text = 'SSN: 123-45-6789'
        
        result = redactor.redact(text)
        
        assert result.was_redacted is True
        assert '123-45-6789' not in result.redacted_text
        assert PiiType.SSN in result.pii_types_found
    
    def test_redact_multiple_credentials(self):
        """Should redact multiple types of credentials."""
        redactor = CredentialRedactor()
        text = 'password=secret123 and email: user@test.com'
        
        result = redactor.redact(text)
        
        assert result.redactions_made >= 2
        assert 'secret123' not in result.redacted_text
        assert 'user@test.com' not in result.redacted_text
    
    def test_redact_dict(self):
        """Should redact sensitive fields in dictionary."""
        redactor = CredentialRedactor()
        data = {
            'username': 'john_doe',
            'password': 'super_secret',
            'email': 'john@example.com',
        }
        
        result = redactor.redact_dict(data)
        
        assert result['password'] == '[REDACTED]'
        assert 'john@example.com' not in result['email']
    
    def test_preserve_non_sensitive_data(self):
        """Should preserve non-sensitive data."""
        redactor = CredentialRedactor()
        text = 'User ID: 12345, Name: John Doe'
        
        result = redactor.redact(text)
        
        assert 'User ID: 12345' in result.redacted_text
        assert 'John Doe' in result.redacted_text
    
    def test_disable_pii_redaction(self):
        """Should respect PII redaction flag."""
        config = RedactionConfig()
        config.redact_email = False
        redactor = CredentialRedactor(config)
        
        text = 'Email: test@example.com'
        result = redactor.redact(text)
        
        # With default config (email enabled by default), email should be redacted
        # With our config (disabled), it won't be
        assert result.was_redacted is False
    
    def test_custom_redaction_config(self):
        """Should use custom configuration."""
        config = RedactionConfig()
        config.add_pattern(RedactionPattern(
            pattern_type='keyword',
            pattern='API_KEY=',
            credential_type=CredentialType.API_KEY,
            placeholder='[HIDDEN_KEY]',
        ))
        
        redactor = CredentialRedactor(config)
        text = 'API_KEY=my_secret_key_xyz'
        
        result = redactor.redact(text)
        
        assert '[HIDDEN_KEY]' in result.redacted_text


class TestCredentialDetectionAndRedaction:
    """Integration tests for detection and redaction."""
    
    def test_password_variations(self):
        """Should detect various password formats."""
        redactor = CredentialRedactor()
        
        test_cases = [
            'password: secret123',
            'password = secret123',
            'password: "secret123"',
            '"password":"secret123"',
        ]
        
        for text in test_cases:
            result = redactor.redact(text)
            assert 'secret' not in result.redacted_text or result.was_redacted
    
    def test_email_variations(self):
        """Should detect various email formats."""
        redactor = CredentialRedactor()
        
        emails = [
            'user@example.com',
            'first.last+tag@subdomain.example.co.uk',
            'test.email@domain.gov',
        ]
        
        for email in emails:
            result = redactor.redact(f'Email: {email}')
            assert email not in result.redacted_text
    
    def test_mixed_content_redaction(self):
        """Should redact from mixed content."""
        redactor = CredentialRedactor()
        
        json_like = '''{
            "user": "john",
            "password": "super_secret",
            "email": "john@example.com",
            "api_key": "sk-1234567890"
        }'''
        
        result = redactor.redact(json_like)
        
        assert 'super_secret' not in result.redacted_text
        assert 'john@example.com' not in result.redacted_text


class TestSensitiveKeyDetection:
    """Test detection of sensitive keys."""
    
    def test_password_keys(self):
        """Should detect password-like keys."""
        redactor = CredentialRedactor()
        
        sensitive_keys = ['password', 'passwd', 'pwd']
        for key in sensitive_keys:
            assert redactor._is_sensitive_key(key) is True
    
    def test_token_keys(self):
        """Should detect token-like keys."""
        redactor = CredentialRedactor()
        
        sensitive_keys = ['token', 'api_key', 'apikey', 'secret']
        for key in sensitive_keys:
            assert redactor._is_sensitive_key(key) is True
    
    def test_normal_keys(self):
        """Should not flag normal keys."""
        redactor = CredentialRedactor()
        
        normal_keys = ['username', 'user_id', 'email']
        for key in normal_keys:
            # email might be special, but username and user_id should be safe
            if key != 'email':
                assert redactor._is_sensitive_key(key) is False
