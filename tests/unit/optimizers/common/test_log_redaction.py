"""Tests for log redaction utilities."""

from __future__ import annotations

import logging

import pytest

from ipfs_datasets_py.optimizers.common.log_redaction import (
    add_redaction_to_logger,
    redact_dict,
    redact_sensitive,
    SensitiveDataFilter,
)


class TestRedactSensitive:
    """Tests for redact_sensitive function."""
    
    def test_redacts_api_key_with_equals(self):
        text = "config: api_key=sk-1234567890abcdefghijklmnop"
        result = redact_sensitive(text)
        assert "sk-1234567890abcdefghijklmnop" not in result
        assert "api_key=***REDACTED***" in result
    
    def test_redacts_api_key_with_colon(self):
        text = '{"api_key": "sk-abcd1234efgh5678ijkl90mnop"}'
        result = redact_sensitive(text)
        assert "sk-abcd1234efgh5678ijkl90mnop" not in result
        assert "***REDACTED***" in result
    
    def test_redacts_apikey_no_separator(self):
        text = "apikey=1234567890abcdefghijklmnopqrst"
        result = redact_sensitive(text)
        assert "1234567890abcdefghijklmnopqrst" not in result
        assert "***REDACTED***" in result
    
    def test_redacts_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        result = redact_sensitive(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert "Bearer ***REDACTED***" in result
    
    def test_redacts_auth_token(self):
        text = "auth_token=ghp_1234567890abcdefghijklmnopqrstuv"
        result = redact_sensitive(text)
        assert "ghp_1234567890abcdefghijklmnopqrstuv" not in result
        assert "auth_token=***REDACTED***" in result
    
    def test_redacts_access_token(self):
        text = "access_token: gho_abcdefghijklmnopqrstuvwxyz0123456789"
        result = redact_sensitive(text)
        assert "gho_abcdefghijklmnopqrstuvwxyz0123456789" not in result
        assert "***REDACTED***" in result
    
    def test_redacts_password_with_quotes(self):
        text = "password='hunter2'"
        result = redact_sensitive(text)
        assert "hunter2" not in result
        assert "password=***REDACTED***" in result
    
    def test_redacts_password_without_quotes(self):
        text = "password=super_secret_123"
        result = redact_sensitive(text)
        assert "super_secret_123" not in result
        assert "***REDACTED***" in result
    
    def test_redacts_passwd(self):
        text = "passwd: admin123"
        result = redact_sensitive(text)
        assert "admin123" not in result
        assert "***REDACTED***" in result
    
    def test_redacts_pwd(self):
        text = "pwd=test123"
        result = redact_sensitive(text)
        assert "test123" not in result
        assert "***REDACTED***" in result
    
    def test_redacts_secret(self):
        text = "secret=abc123def456ghi789"
        result = redact_sensitive(text)
        assert "abc123def456ghi789" not in result
        assert "secret=***REDACTED***" in result
    
    def test_redacts_secret_key(self):
        text = "secret_key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        result = redact_sensitive(text)
        assert "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" not in result
        assert "***REDACTED***" in result
    
    def test_redacts_aws_access_key(self):
        text = "AWS key is AKIAIOSFODNN7EXAMPLE"
        result = redact_sensitive(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "***REDACTED***" in result
    
    def test_redacts_rsa_private_key(self):
        text = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF...
-----END RSA PRIVATE KEY-----"""
        result = redact_sensitive(text)
        assert "MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn" not in result
        assert "***REDACTED PRIVATE KEY***" in result
    
    def test_preserves_tokens_used_metric(self):
        """Should NOT redact 'tokens_used' (text token metric)."""
        text = "stats: tokens_used=1234"
        result = redact_sensitive(text)
        assert "tokens_used=1234" in result  # NOT redacted
    
    def test_preserves_max_tokens_param(self):
        """Should NOT redact 'max_tokens' (LLM parameter)."""
        text = "config: max_tokens=2048"
        result = redact_sensitive(text)
        assert "max_tokens=2048" in result  # NOT redacted
    
    def test_preserves_total_input_tokens(self):
        """Should NOT redact 'total_input_tokens' (metric)."""
        text = "total_input_tokens: 456"
        result = redact_sensitive(text)
        assert "total_input_tokens: 456" in result  # NOT redacted
    
    def test_empty_string(self):
        assert redact_sensitive("") == ""
    
    def test_no_sensitive_data(self):
        text = "This is a normal log message with no secrets"
        result = redact_sensitive(text)
        assert result == text
    
    def test_multiple_sensitive_values(self):
        text = "api_key=sk-12345 password=hunter2 secret=abc123def456"
        result = redact_sensitive(text)
        assert "sk-12345" not in result
        assert "hunter2" not in result
        assert "abc123def456" not in result
        assert result.count("***REDACTED***") == 3
    
    def test_case_insensitive(self):
        text = "API_KEY=sk-12345 Password=hunter2 SECRET=xyz789"
        result = redact_sensitive(text)
        assert "sk-12345" not in result
        assert "hunter2" not in result
        assert "xyz789" not in result


class TestSensitiveDataFilter:
    """Tests for SensitiveDataFilter logging filter."""
    
    def test_filter_redacts_message(self, caplog):
        logger = logging.getLogger("test_redaction")
        logger.addFilter(SensitiveDataFilter())
        logger.setLevel(logging.INFO)
        
        with caplog.at_level(logging.INFO, logger="test_redaction"):
            logger.info("api_key=sk-1234567890abcdefghijklmnop")
        
        assert "sk-1234567890abcdefghijklmnop" not in caplog.text
        assert "***REDACTED***" in caplog.text
    
    def test_filter_always_returns_true(self):
        filt = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="api_key=test", args=(), exc_info=None
        )
        assert filt.filter(record) is True
    
    def test_filter_redacts_args_dict(self):
        filt = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="config: %s", args=({"api_key": "sk-12345"},), exc_info=None
        )
        filt.filter(record)
        # After filtering, the message should be formatted and redacted, args cleared
        assert "***REDACTED***" in record.msg or "sk-12345" not in record.msg
        assert record.args == ()  # Args consumed during formatting
    
    def test_filter_redacts_args_tuple(self):
        filt = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="key=%s", args=("api_key=sk-12345",), exc_info=None
        )
        filt.filter(record)
        # Message should be formatted and redacted
        assert "***REDACTED***" in record.msg
        assert "sk-12345" not in record.msg
        assert record.args == ()  # Args consumed


class TestAddRedactionToLogger:
    """Tests for add_redaction_to_logger helper."""
    
    def test_adds_filter_to_logger(self):
        logger = logging.getLogger("test_add_redaction")
        initial_filter_count = len(logger.filters)
        
        add_redaction_to_logger(logger)
        
        assert len(logger.filters) == initial_filter_count + 1
        assert any(isinstance(f, SensitiveDataFilter) for f in logger.filters)
    
    def test_filter_works_after_adding(self, caplog):
        logger = logging.getLogger("test_add_redaction_works")
        logger.setLevel(logging.INFO)
        add_redaction_to_logger(logger)
        
        with caplog.at_level(logging.INFO, logger="test_add_redaction_works"):
            logger.info("password=hunter2")
        
        assert "hunter2" not in caplog.text
        assert "***REDACTED***" in caplog.text


class TestRedactDict:
    """Tests for redact_dict function."""
    
    def test_redacts_api_key_value(self):
        data = {"api_key": "sk-12345", "max_retries": 3}
        result = redact_dict(data)
        assert result["api_key"] == "***REDACTED***"
        assert result["max_retries"] == 3
    
    def test_redacts_password_value(self):
        data = {"username": "alice", "password": "hunter2"}
        result = redact_dict(data)
        assert result["username"] == "alice"
        assert result["password"] == "***REDACTED***"
    
    def test_redacts_token_value(self):
        data = {"auth_token": "ghp_abcdefg1234567890", "timeout": 30}
        result = redact_dict(data)
        assert result["auth_token"] == "***REDACTED***"
        assert result["timeout"] == 30
    
    def test_redacts_secret_value(self):
        data = {"secret": "xyz123abc456", "enabled": True}
        result = redact_dict(data)
        assert result["secret"] == "***REDACTED***"
        assert result["enabled"] is True
    
    def test_redacts_nested_dict(self):
        data = {
            "service": "openai",
            "config": {
                "api_key": "sk-nested",
                "max_tokens": 2048
            }
        }
        result = redact_dict(data)
        assert result["service"] == "openai"
        assert result["config"]["api_key"] == "***REDACTED***"
        assert result["config"]["max_tokens"] == 2048  # NOT redacted (not a sensitive key)
    
    def test_string_values_not_pattern_redacted(self):
        """redact_dict only redacts by key name, not by string content patterns."""
        data = {
            "description": "api_key=sk-12345 embedded in text",
            "count": 42
        }
        result = redact_dict(data)
        # Description is preserved as-is (not a sensitive key)
        assert result["description"] == "api_key=sk-12345 embedded in text"
        assert result["count"] == 42
    
    def test_preserves_non_sensitive_keys(self):
        data = {
            "username": "alice",
            "max_tokens": 2048,
            "tokens_used": 1234,
            "backend": "openai"
        }
        result = redact_dict(data)
        assert result == data  # No redaction for these keys
    
    def test_empty_dict(self):
        assert redact_dict({}) == {}
    
    def test_case_insensitive_key_matching(self):
        data = {
            "API_KEY": "sk-upper",
            "Password": "hunter2",
            "Secret_Key": "xyz789"
        }
        result = redact_dict(data)
        assert result["API_KEY"] == "***REDACTED***"
        assert result["Password"] == "***REDACTED***"
        assert result["Secret_Key"] == "***REDACTED***"
    
    def test_multiple_sensitive_keys(self):
        data = {
            "api_key": "sk-12345",
            "password": "hunter2",
            "secret": "abc123",
            "max_retries": 3
        }
        result = redact_dict(data)
        assert result["api_key"] == "***REDACTED***"
        assert result["password"] == "***REDACTED***"
        assert result["secret"] == "***REDACTED***"
        assert result["max_retries"] == 3


class TestIntegration:
    """Integration tests combining multiple redaction approaches."""
    
    def test_end_to_end_logger_redaction(self, caplog):
        """Complete workflow: logger with filter redacts sensitive data."""
        logger = logging.getLogger("test_integration")
        logger.setLevel(logging.INFO)
        add_redaction_to_logger(logger)
        
        # Log various sensitive data types
        with caplog.at_level(logging.INFO, logger="test_integration"):
            logger.info("Starting service with api_key=sk-12345")
            logger.info("User credentials: password=hunter2")
            logger.info("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")
        
        # Verify all redacted
        assert "sk-12345" not in caplog.text
        assert "hunter2" not in caplog.text
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in caplog.text
        assert caplog.text.count("***REDACTED***") >= 3
    
    def test_dict_redaction_by_key(self):
        """Redact dict by key name (not string patterns)."""
        data = {
            "api_key": "sk-explicit",
            "message": "Using api_key=sk-embedded for authentication"
        }
        result = redact_dict(data)
        
        # Explicit key redacted, message value preserved (not a sensitive key)
        assert result["api_key"] == "***REDACTED***"
        assert result["message"] == "Using api_key=sk-embedded for authentication"
