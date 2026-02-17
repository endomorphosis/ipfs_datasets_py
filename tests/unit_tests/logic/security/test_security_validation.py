"""
Security validation tests for logic module.

Tests input validation, rate limiting, and security controls.
Following GIVEN-WHEN-THEN pattern from docs/_example_test_format.md
"""

import pytest
import time
from unittest import mock

# Try importing security modules
try:
    from ipfs_datasets_py.logic.security import InputValidator, RateLimiter, AuditLogger
    SECURITY_AVAILABLE = True
except ImportError as e:
    SECURITY_AVAILABLE = False
    IMPORT_ERROR = str(e)


@pytest.mark.skipif(not SECURITY_AVAILABLE, reason=f"Security modules not available")
class TestInputValidation:
    """Tests for InputValidator security controls."""
    
    def test_input_length_validation(self):
        """
        GIVEN: InputValidator with default settings
        WHEN: Validating very long input (>100KB)
        THEN: Input is rejected with ValueError
        """
        # GIVEN
        validator = InputValidator()
        
        # WHEN - create 100KB input
        long_input = "a" * 100_000
        
        # THEN
        with pytest.raises(ValueError):
            validator.validate_text(long_input)
    
    def test_normal_length_accepted(self):
        """
        GIVEN: InputValidator
        WHEN: Validating normal length input
        THEN: Input is accepted
        """
        # GIVEN
        validator = InputValidator()
        
        # WHEN
        normal_input = "All cats are animals"
        
        # THEN
        result = validator.validate_text(normal_input)
        assert result == normal_input or result is not None
    
    def test_rate_limiting_enforcement(self):
        """
        GIVEN: RateLimiter configured for 10 calls/minute
        WHEN: Making 15 requests rapidly
        THEN: Requests 11-15 are blocked
        """
        # GIVEN
        limiter = RateLimiter(calls=10, period=60)
        user_id = "test_user"
        
        # WHEN - first 10 should succeed
        for i in range(10):
            limiter.check_rate_limit(user_id)
        
        # THEN - 11th should fail
        with pytest.raises(Exception):  # RateLimitExceeded or similar
            limiter.check_rate_limit(user_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
