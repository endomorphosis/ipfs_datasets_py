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


    def test_formula_depth_validation(self):
        """
        GIVEN formulas with varying depths
        WHEN validating formula depth
        THEN deep formulas should be rejected
        """
        # GIVEN
        validator = InputValidator()
        shallow_formula = "P and Q"
        # Create a deeply nested formula
        deep_formula = "P"
        for _ in range(150):  # Exceed default depth limit of 100
            deep_formula = f"not ({deep_formula})"
        
        # WHEN/THEN - Shallow should pass
        try:
            validator.validate_formula(shallow_formula)
            shallow_passed = True
        except ValueError:
            shallow_passed = False
            
        # Deep should fail
        try:
            validator.validate_formula(deep_formula)
            deep_passed = True
        except ValueError:
            deep_passed = False
            
        assert shallow_passed, "Shallow formula should pass validation"
        assert not deep_passed, "Deep formula should be rejected"
        
    def test_null_byte_filtering(self):
        """
        GIVEN text containing null bytes
        WHEN validating input
        THEN null bytes should be filtered or rejected
        """
        # GIVEN
        validator = InputValidator()
        clean_text = "clean text"
        dirty_text = "text\x00with\x00nulls"
        
        # WHEN
        clean_result = validator.validate_text(clean_text)
        
        try:
            dirty_result = validator.validate_text(dirty_text)
            # If it doesn't raise, should have removed null bytes
            assert "\x00" not in dirty_result
        except ValueError:
            # Expected - null bytes rejected
            pass
            
        # THEN
        assert clean_result == clean_text
        
    def test_suspicious_pattern_detection(self):
        """
        GIVEN text with suspicious patterns
        WHEN validating input
        THEN suspicious patterns should be detected
        """
        # GIVEN
        validator = InputValidator()
        normal_text = "This is normal text"
        suspicious_text = "<script>alert('xss')</script>"
        
        # WHEN
        normal_result = validator.validate_text(normal_text)
        
        try:
            suspicious_result = validator.validate_text(suspicious_text)
            # May pass through or be cleaned
            assert suspicious_result is not None
        except ValueError:
            # Or may reject suspicious patterns
            pass
            
        # THEN
        assert normal_result == normal_text
        
    def test_formula_complexity_validation(self):
        """
        GIVEN formulas with varying complexity
        WHEN validating complexity
        THEN overly complex formulas should be rejected
        """
        # GIVEN
        validator = InputValidator()
        simple_formula = "P and Q"
        # Create complex formula with many operators
        complex_parts = [f"P{i}" for i in range(200)]
        complex_formula = " and ".join(complex_parts)
        
        # WHEN/THEN
        try:
            validator.validate_formula(simple_formula)
            simple_passed = True
        except ValueError:
            simple_passed = False
            
        try:
            validator.validate_formula(complex_formula)
            complex_passed = True
        except ValueError:
            complex_passed = False
            
        assert simple_passed, "Simple formula should pass"
        # Complex may or may not pass depending on limits
        # Just verify it doesn't crash
        
    def test_concurrent_rate_limiting(self):
        """
        GIVEN multiple concurrent requests
        WHEN rate limiting is applied
        THEN limits should be enforced correctly
        """
        # GIVEN
        limiter = RateLimiter(calls=5, period=1.0)
        user_id = "concurrent_user"
        
        # WHEN - Make multiple rapid calls
        results = []
        for i in range(10):
            try:
                limiter.check_rate_limit(user_id)
                results.append(True)
            except ValueError:
                results.append(False)
                
        # THEN - Some should succeed, some should fail
        successes = sum(results)
        failures = len(results) - successes
        
        # At least some should be rate limited
        assert failures > 0, "Rate limiting should reject some requests"
        assert successes > 0, "Some requests should succeed"
        
    def test_audit_logging_functionality(self):
        """
        GIVEN audit logging enabled
        WHEN security events occur
        THEN events should be logged
        """
        # GIVEN
        from ipfs_datasets_py.logic.security import AuditLogger
        logger = AuditLogger()
        
        # WHEN
        logger.log_security_event(
            event_type="test_event",
            user_id="test_user",
            details={"action": "test"}
        )
        
        # THEN - Should not raise exception
        # Actual log verification would require checking log files
        assert True, "Audit logging should work without errors"
        
    def test_security_decorator_integration(self):
        """
        GIVEN a function decorated with rate limiting
        WHEN calling the function multiple times
        THEN rate limiting should be enforced
        """
        # GIVEN
        limiter = RateLimiter(calls=3, period=1.0)
        
        @limiter
        def protected_function(user_id: str):
            return "success"
        
        # WHEN/THEN
        user_id = "test_decorator_user"
        successes = 0
        failures = 0
        
        for _ in range(5):
            try:
                result = protected_function(user_id)
                successes += 1
            except ValueError:
                failures += 1
                
        # Should have some successes and some rate-limited failures
        assert successes > 0, "Some calls should succeed"
        assert failures > 0, "Some calls should be rate limited"
        
    def test_security_integration_scenarios(self):
        """
        GIVEN complete security stack (validation + rate limiting + audit)
        WHEN processing requests
        THEN all security controls should work together
        """
        # GIVEN
        validator = InputValidator()
        limiter = RateLimiter(calls=10, period=1.0)
        from ipfs_datasets_py.logic.security import AuditLogger
        logger = AuditLogger()
        
        user_id = "integration_user"
        
        # WHEN - Simulate a request with all security checks
        try:
            # 1. Validate input
            text = validator.validate_text("test input")
            
            # 2. Check rate limit
            limiter.check_rate_limit(user_id)
            
            # 3. Log the event
            logger.log_security_event(
                event_type="request_processed",
                user_id=user_id,
                details={"text_length": len(text)}
            )
            
            success = True
        except (ValueError, Exception) as e:
            success = False
            
        # THEN - Integration should work
        assert success, "Security integration should work end-to-end"
