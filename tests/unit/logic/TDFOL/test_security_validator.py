"""
Comprehensive tests for TDFOL Security Validator.

Tests cover all security features including input validation, ZKP audits,
resource limits, DoS prevention, and formula sanitization.
"""

import pytest
import time
import threading
from typing import Dict, Any

from ipfs_datasets_py.logic.TDFOL.security_validator import (
    SecurityValidator,
    SecurityConfig,
    SecurityLevel,
    ThreatType,
    ValidationResult,
    AuditResult,
    RateLimiter,
    create_validator,
    validate_formula,
    audit_proof,
)


class TestSecurityValidator:
    """Test SecurityValidator class."""
    
    def test_init_default_config(self):
        """Test initialization with default configuration."""
        # GIVEN: No configuration provided
        # WHEN: Creating a validator
        validator = SecurityValidator()
        
        # THEN: Default configuration should be used
        assert validator.config.security_level == SecurityLevel.MEDIUM
        assert validator.config.max_formula_size == 10000
        assert validator.config.max_formula_depth == 100
    
    def test_init_custom_config(self):
        """Test initialization with custom configuration."""
        # GIVEN: Custom configuration
        config = SecurityConfig(
            security_level=SecurityLevel.HIGH,
            max_formula_size=5000
        )
        
        # WHEN: Creating a validator with custom config
        validator = SecurityValidator(config)
        
        # THEN: Custom configuration should be used
        assert validator.config.security_level == SecurityLevel.HIGH
        assert validator.config.max_formula_size == 5000


class TestInputValidation:
    """Test input validation functionality."""
    
    def test_valid_simple_formula(self):
        """Test validation of simple valid formula."""
        # GIVEN: A simple valid formula
        validator = SecurityValidator()
        formula = "∀x. P(x) → Q(x)"
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: Validation should pass
        assert result.valid
        assert len(result.errors) == 0
    
    def test_empty_formula(self):
        """Test validation of empty formula."""
        # GIVEN: An empty formula
        validator = SecurityValidator()
        formula = ""
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: Validation should fail
        assert not result.valid
        assert "Empty formula" in result.errors
        assert ThreatType.MALFORMED_INPUT in result.threats
    
    def test_null_bytes(self):
        """Test detection of null bytes."""
        # GIVEN: Formula with null bytes
        validator = SecurityValidator()
        formula = "∀x. P(x)\x00→ Q(x)"
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: Validation should fail
        assert not result.valid
        assert any("Null bytes" in error for error in result.errors)
        assert ThreatType.INJECTION in result.threats
    
    def test_formula_too_large(self):
        """Test detection of oversized formula."""
        # GIVEN: Formula exceeding size limit
        validator = SecurityValidator()
        formula = "x" * (validator.config.max_formula_size + 1)
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: Validation should fail
        assert not result.valid
        assert any("too large" in error for error in result.errors)
        assert ThreatType.RESOURCE_EXHAUSTION in result.threats
    
    def test_formula_too_deep(self):
        """Test detection of excessive nesting depth."""
        # GIVEN: Deeply nested formula
        validator = SecurityValidator()
        depth = validator.config.max_formula_depth + 1
        formula = "(" * depth + "x" + ")" * depth
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: Validation should fail
        assert not result.valid
        assert any("too deep" in error for error in result.errors)
        assert ThreatType.RESOURCE_EXHAUSTION in result.threats
    
    def test_too_many_variables(self):
        """Test detection of excessive variables."""
        # GIVEN: Formula with too many variables
        config = SecurityConfig(max_variables=10)
        validator = SecurityValidator(config)
        formula = " ".join([f"x{i}" for i in range(11)])
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: Validation should fail
        assert not result.valid
        assert any("Too many variables" in error for error in result.errors)
        assert ThreatType.RESOURCE_EXHAUSTION in result.threats
    
    def test_too_many_operators(self):
        """Test detection of excessive operators."""
        # GIVEN: Formula with too many operators
        config = SecurityConfig(max_operators=10)
        validator = SecurityValidator(config)
        formula = "x ∧ " * 11 + "y"
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: Validation should fail
        assert not result.valid
        assert any("Too many operators" in error for error in result.errors)


class TestCharacterValidation:
    """Test character validation functionality."""
    
    def test_valid_characters(self):
        """Test formula with only valid characters."""
        # GIVEN: Formula with valid characters
        validator = SecurityValidator()
        formula = "∀x∃y. (P(x) ∧ Q(y)) → R(x,y)"
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: No character validation errors
        assert not any("Invalid characters" in error for error in result.errors)
    
    def test_invalid_characters_paranoid(self):
        """Test invalid character detection in paranoid mode."""
        # GIVEN: Formula with unusual characters and paranoid mode
        config = SecurityConfig(security_level=SecurityLevel.PARANOID)
        validator = SecurityValidator(config)
        formula = "∀x. P(x) → Q(x) # comment"
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: Should detect invalid characters
        assert not result.valid or len(result.warnings) > 0
    
    def test_invalid_characters_high(self):
        """Test invalid character detection in high security mode."""
        # GIVEN: Formula with unusual characters and high security
        config = SecurityConfig(security_level=SecurityLevel.HIGH)
        validator = SecurityValidator(config)
        formula = "∀x. P(x) → Q(x) @"
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: Should produce warnings
        assert len(result.warnings) > 0 or not result.valid


class TestInjectionDetection:
    """Test injection attack detection."""
    
    def test_eval_injection(self):
        """Test detection of eval injection."""
        # GIVEN: Formula with eval keyword
        validator = SecurityValidator()
        formula = "eval(malicious_code)"
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: Should detect injection
        assert not result.valid
        assert ThreatType.INJECTION in result.threats
    
    def test_exec_injection(self):
        """Test detection of exec injection."""
        # GIVEN: Formula with exec keyword
        validator = SecurityValidator()
        formula = "exec(harmful_code)"
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: Should detect injection
        assert not result.valid
        assert ThreatType.INJECTION in result.threats
    
    def test_command_injection(self):
        """Test detection of command injection."""
        # GIVEN: Formula with command injection patterns
        validator = SecurityValidator()
        formulas = [
            "$(rm -rf /)",
            "`malicious`",
            "${dangerous}",
            "test | cat /etc/passwd",
            "a; rm -rf /",
            "a && dangerous",
        ]
        
        # WHEN: Validating each formula
        # THEN: Should detect injection or produce warnings
        for formula in formulas:
            result = validator.validate_formula(formula)
            assert not result.valid or len(result.warnings) > 0
    
    def test_python_internals(self):
        """Test detection of Python internals access."""
        # GIVEN: Formula accessing Python internals
        validator = SecurityValidator()
        formulas = [
            "__import__('os')",
            "__builtins__",
            "getattr(obj, 'dangerous')",
        ]
        
        # WHEN: Validating each formula
        # THEN: Should detect injection
        for formula in formulas:
            result = validator.validate_formula(formula)
            assert not result.valid
            assert ThreatType.INJECTION in result.threats


class TestDoSPrevention:
    """Test DoS prevention functionality."""
    
    def test_excessive_repetition(self):
        """Test detection of excessive character repetition."""
        # GIVEN: Formula with excessive repetition
        validator = SecurityValidator()
        formula = "x" * 150
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: Should detect DoS pattern
        assert not result.valid
        assert ThreatType.DOS in result.threats
    
    def test_exponential_pattern(self):
        """Test detection of exponential complexity patterns."""
        # GIVEN: Formula with deeply nested quantifiers
        validator = SecurityValidator()
        formula = "∀x1∀x2∀x3∀x4∀x5∀x6∀x7∀x8∀x9∀x10∀x11∀x12. P(x1,x2,x3,x4,x5,x6,x7,x8,x9,x10,x11,x12)"
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: Should warn about exponential pattern
        assert len(result.warnings) > 0 or ThreatType.DOS in result.threats
    
    def test_detect_dos_pattern_method(self):
        """Test detect_dos_pattern method."""
        # GIVEN: Formula with DoS pattern
        validator = SecurityValidator()
        formula = "a" * 150
        
        # WHEN: Checking for DoS pattern
        has_dos = validator.detect_dos_pattern(formula)
        
        # THEN: Should detect DoS
        assert has_dos


class TestRecursiveBombs:
    """Test recursive bomb detection."""
    
    def test_self_referential_pattern(self):
        """Test detection of self-referential patterns."""
        # GIVEN: Formula with self-reference
        validator = SecurityValidator()
        formula = "x = f(x)"
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: Should warn about self-reference
        assert len(result.warnings) > 0
    
    def test_high_variable_reuse(self):
        """Test detection of high variable reuse."""
        # GIVEN: Formula with many duplicate variables
        validator = SecurityValidator()
        formula = " ".join(["x"] * 20)
        
        # WHEN: Validating the formula
        result = validator.validate_formula(formula)
        
        # THEN: Should warn about reuse
        assert len(result.warnings) > 0


class TestRateLimiting:
    """Test rate limiting functionality."""
    
    def test_rate_limiter_basic(self):
        """Test basic rate limiter functionality."""
        # GIVEN: Rate limiter with low limits
        limiter = RateLimiter(max_requests=5, time_window=60.0)
        
        # WHEN: Making requests within limit
        for i in range(5):
            allowed, error = limiter.check_rate_limit("user1")
            
            # THEN: All should be allowed
            assert allowed
            assert error is None
        
        # WHEN: Exceeding limit
        allowed, error = limiter.check_rate_limit("user1")
        
        # THEN: Should be rejected
        assert not allowed
        assert error is not None
    
    def test_rate_limiter_multiple_users(self):
        """Test rate limiter with multiple users."""
        # GIVEN: Rate limiter
        limiter = RateLimiter(max_requests=5, time_window=60.0)
        
        # WHEN: Different users make requests
        for i in range(5):
            limiter.check_rate_limit("user1")
            limiter.check_rate_limit("user2")
        
        # THEN: Both users should hit limit independently
        allowed1, _ = limiter.check_rate_limit("user1")
        allowed2, _ = limiter.check_rate_limit("user2")
        assert not allowed1
        assert not allowed2
    
    def test_validator_rate_limiting(self):
        """Test validator rate limiting integration."""
        # GIVEN: Validator with low rate limit
        config = SecurityConfig(max_requests_per_minute=5)
        validator = SecurityValidator(config)
        formula = "∀x. P(x)"
        
        # WHEN: Making requests within limit
        for i in range(5):
            result = validator.validate_formula(formula, f"test_user")
            assert result.valid
        
        # WHEN: Exceeding limit
        result = validator.validate_formula(formula, "test_user")
        
        # THEN: Should be rejected
        assert not result.valid
        assert ThreatType.DOS in result.threats


class TestConcurrentRequests:
    """Test concurrent request limiting."""
    
    def test_concurrent_limit(self):
        """Test concurrent request limits."""
        # GIVEN: Validator with low concurrent limit
        config = SecurityConfig(max_concurrent_requests=2)
        validator = SecurityValidator(config)
        
        results = []
        
        def make_request():
            time.sleep(0.1)  # Simulate work
            result = validator.validate_formula("∀x. P(x)")
            results.append(result)
        
        # WHEN: Starting multiple concurrent requests
        threads = [threading.Thread(target=make_request) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # THEN: Some requests should be rejected
        assert any(not r.valid for r in results)


class TestInputSanitization:
    """Test input sanitization functionality."""
    
    def test_sanitize_null_bytes(self):
        """Test removal of null bytes."""
        # GIVEN: Input with null bytes
        validator = SecurityValidator()
        input_str = "test\x00string"
        
        # WHEN: Sanitizing input
        sanitized = validator.sanitize_input(input_str)
        
        # THEN: Null bytes should be removed
        assert '\x00' not in sanitized
        assert sanitized == "teststring"
    
    def test_sanitize_dangerous_patterns(self):
        """Test removal of dangerous patterns."""
        # GIVEN: Input with dangerous patterns
        validator = SecurityValidator()
        input_str = "eval(malicious)"
        
        # WHEN: Sanitizing input
        sanitized = validator.sanitize_input(input_str)
        
        # THEN: Dangerous patterns should be removed
        assert "eval" not in sanitized
    
    def test_sanitize_whitespace(self):
        """Test whitespace normalization."""
        # GIVEN: Input with excessive whitespace
        validator = SecurityValidator()
        input_str = "test    multiple     spaces"
        
        # WHEN: Sanitizing input
        sanitized = validator.sanitize_input(input_str)
        
        # THEN: Whitespace should be normalized
        assert "    " not in sanitized
        assert sanitized == "test multiple spaces"
    
    def test_sanitize_control_characters(self):
        """Test removal of control characters."""
        # GIVEN: Input with control characters
        validator = SecurityValidator()
        input_str = "test\x01\x02\x03string"
        
        # WHEN: Sanitizing input
        sanitized = validator.sanitize_input(input_str)
        
        # THEN: Control characters should be removed
        assert '\x01' not in sanitized
        assert '\x02' not in sanitized
        assert '\x03' not in sanitized
    
    def test_sanitize_length_limit(self):
        """Test length limiting."""
        # GIVEN: Input exceeding length limit
        validator = SecurityValidator()
        input_str = "x" * (validator.config.max_formula_size + 100)
        
        # WHEN: Sanitizing input
        sanitized = validator.sanitize_input(input_str)
        
        # THEN: Should be truncated to limit
        assert len(sanitized) <= validator.config.max_formula_size


class TestResourceLimits:
    """Test resource limit checking."""
    
    def test_check_resource_limits_memory(self):
        """Test memory limit checking."""
        # GIVEN: Validator with memory limits
        validator = SecurityValidator()
        formula = "∀x. P(x)"
        
        # WHEN: Checking with memory within limits
        within_limit = validator.check_resource_limits(formula, memory_mb=100)
        
        # THEN: Should pass
        assert within_limit
        
        # WHEN: Checking with memory exceeding limits
        exceeds_limit = validator.check_resource_limits(
            formula,
            memory_mb=validator.config.max_memory_mb + 100
        )
        
        # THEN: Should fail
        assert not exceeds_limit
    
    def test_check_resource_limits_time(self):
        """Test time limit checking."""
        # GIVEN: Validator with time limits
        validator = SecurityValidator()
        formula = "∀x. P(x)"
        
        # WHEN: Checking with time within limits
        within_limit = validator.check_resource_limits(formula, time_seconds=5.0)
        
        # THEN: Should pass
        assert within_limit
        
        # WHEN: Checking with time exceeding limits
        exceeds_limit = validator.check_resource_limits(
            formula,
            time_seconds=validator.config.max_proof_time_seconds + 10
        )
        
        # THEN: Should fail
        assert not exceeds_limit


class TestZKPAudit:
    """Test ZKP security audit functionality."""
    
    def test_audit_valid_proof(self):
        """Test audit of valid ZKP proof."""
        # GIVEN: Valid ZKP proof
        validator = SecurityValidator()
        proof = {
            'commitment': 'a' * 64,
            'challenge': 'b' * 64,
            'response': 'c' * 64,
        }
        
        # WHEN: Auditing the proof
        result = validator.audit_zkp_proof(proof)
        
        # THEN: Audit should pass
        assert result.passed
        assert len(result.vulnerabilities) == 0
    
    def test_audit_missing_fields(self):
        """Test audit of proof with missing fields."""
        # GIVEN: Proof with missing required fields
        validator = SecurityValidator()
        proof = {
            'commitment': 'a' * 64,
            # Missing challenge and response
        }
        
        # WHEN: Auditing the proof
        result = validator.audit_zkp_proof(proof)
        
        # THEN: Audit should fail
        assert not result.passed
        assert len(result.vulnerabilities) > 0
        assert any("Missing required field" in v for v in result.vulnerabilities)
    
    def test_audit_short_commitment(self):
        """Test audit of proof with short commitment."""
        # GIVEN: Proof with too short commitment
        validator = SecurityValidator()
        proof = {
            'commitment': 'short',
            'challenge': 'b' * 64,
            'response': 'c' * 64,
        }
        
        # WHEN: Auditing the proof
        result = validator.audit_zkp_proof(proof)
        
        # THEN: Should detect vulnerability
        assert not result.passed
        assert any("Commitment too short" in v for v in result.vulnerabilities)
    
    def test_audit_low_entropy_challenge(self):
        """Test audit of proof with low entropy challenge."""
        # GIVEN: Proof with low entropy challenge
        validator = SecurityValidator()
        proof = {
            'commitment': 'a' * 64,
            'challenge': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
            'response': 'c' * 64,
        }
        
        # WHEN: Auditing the proof
        result = validator.audit_zkp_proof(proof)
        
        # THEN: Should provide recommendation
        assert len(result.recommendations) > 0
    
    def test_audit_timing_attacks(self):
        """Test timing attack detection."""
        # GIVEN: Valid proof
        validator = SecurityValidator()
        proof = {
            'commitment': 'a' * 64,
            'challenge': 'b' * 64,
            'response': 'c' * 64,
        }
        
        # WHEN: Auditing the proof
        result = validator.audit_zkp_proof(proof)
        
        # THEN: Audit should complete
        assert result.audit_time > 0
    
    def test_audit_proof_integrity(self):
        """Test proof integrity checking."""
        # GIVEN: Proof with integrity hash
        validator = SecurityValidator()
        import hashlib
        
        proof_data = {
            'commitment': 'a' * 64,
            'challenge': 'b' * 64,
            'response': 'c' * 64,
        }
        proof_hash = hashlib.sha256(str(sorted(proof_data.items())).encode()).hexdigest()
        
        proof = {
            **proof_data,
            'metadata': {'hash': proof_hash}
        }
        
        # WHEN: Auditing the proof
        result = validator.audit_zkp_proof(proof)
        
        # THEN: Integrity check should pass
        assert result.passed
    
    def test_audit_sensitive_metadata(self):
        """Test detection of sensitive metadata."""
        # GIVEN: Proof with sensitive metadata
        validator = SecurityValidator()
        proof = {
            'commitment': 'a' * 64,
            'challenge': 'b' * 64,
            'response': 'c' * 64,
            'metadata': {
                'secret_key': 'should_not_be_here',
            }
        }
        
        # WHEN: Auditing the proof
        result = validator.audit_zkp_proof(proof)
        
        # THEN: Should detect vulnerability
        assert not result.passed
        assert any("sensitive" in v.lower() for v in result.vulnerabilities)


class TestSecurityLevels:
    """Test different security levels."""
    
    def test_low_security_permissive(self):
        """Test low security level is permissive."""
        # GIVEN: Validator with low security
        config = SecurityConfig(security_level=SecurityLevel.LOW)
        validator = SecurityValidator(config)
        formula = "test | command"
        
        # WHEN: Validating potentially dangerous formula
        result = validator.validate_formula(formula)
        
        # THEN: May be more permissive
        # (Warnings instead of errors)
        assert result.valid or len(result.warnings) > 0
    
    def test_paranoid_security_strict(self):
        """Test paranoid security level is strict."""
        # GIVEN: Validator with paranoid security
        config = SecurityConfig(security_level=SecurityLevel.PARANOID)
        validator = SecurityValidator(config)
        formula = "∀x. P(x) #"
        
        # WHEN: Validating formula with unusual character
        result = validator.validate_formula(formula)
        
        # THEN: Should be strict
        assert not result.valid or len(result.errors) > 0


class TestSecurityReporting:
    """Test security reporting functionality."""
    
    def test_get_security_report(self):
        """Test security report generation."""
        # GIVEN: Validator with some security events
        validator = SecurityValidator()
        
        # Trigger some events
        validator.validate_formula("")  # Empty formula
        validator.validate_formula("eval(x)")  # Injection
        
        # WHEN: Getting security report
        report = validator.get_security_report()
        
        # THEN: Report should contain events
        assert "total_events" in report
        assert report["total_events"] > 0
        assert "threat_breakdown" in report
        assert "security_level" in report
    
    def test_clear_security_events(self):
        """Test clearing security events."""
        # GIVEN: Validator with security events
        validator = SecurityValidator()
        validator.validate_formula("")  # Trigger event
        
        # WHEN: Clearing events
        validator.clear_security_events()
        
        # THEN: Events should be cleared
        report = validator.get_security_report()
        assert report["total_events"] == 0


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def test_create_validator(self):
        """Test create_validator function."""
        # GIVEN: Security level
        level = SecurityLevel.HIGH
        
        # WHEN: Creating validator
        validator = create_validator(level)
        
        # THEN: Should have correct security level
        assert validator.config.security_level == level
    
    def test_validate_formula_function(self):
        """Test validate_formula convenience function."""
        # GIVEN: Valid formula
        formula = "∀x. P(x)"
        
        # WHEN: Validating formula
        result = validate_formula(formula, SecurityLevel.MEDIUM)
        
        # THEN: Should return validation result
        assert isinstance(result, ValidationResult)
        assert result.valid
    
    def test_audit_proof_function(self):
        """Test audit_proof convenience function."""
        # GIVEN: Valid proof
        proof = {
            'commitment': 'a' * 64,
            'challenge': 'b' * 64,
            'response': 'c' * 64,
        }
        
        # WHEN: Auditing proof
        result = audit_proof(proof)
        
        # THEN: Should return audit result
        assert isinstance(result, AuditResult)
        assert result.passed


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_very_long_formula(self):
        """Test handling of very long formula."""
        # GIVEN: Extremely long formula
        validator = SecurityValidator()
        formula = "x" * 50000
        
        # WHEN: Validating formula
        result = validator.validate_formula(formula)
        
        # THEN: Should handle gracefully
        assert not result.valid
        assert ThreatType.RESOURCE_EXHAUSTION in result.threats
    
    def test_unicode_formula(self):
        """Test handling of Unicode formula."""
        # GIVEN: Formula with various Unicode characters
        validator = SecurityValidator()
        formula = "∀x∃y. (P(x) ∧ Q(y)) → R(x,y) ∨ ¬S(x)"
        
        # WHEN: Validating formula
        result = validator.validate_formula(formula)
        
        # THEN: Should handle Unicode correctly
        assert result.valid
    
    def test_malformed_proof(self):
        """Test handling of malformed proof."""
        # GIVEN: Malformed proof
        validator = SecurityValidator()
        proof = "not a dict"
        
        # WHEN: Auditing proof
        result = validator.audit_zkp_proof(proof)
        
        # THEN: Should handle gracefully
        assert not result.passed
    
    def test_concurrent_validation_safety(self):
        """Test thread safety of concurrent validations."""
        # GIVEN: Validator and multiple threads
        validator = SecurityValidator()
        results = []
        errors = []
        
        def validate():
            try:
                result = validator.validate_formula("∀x. P(x)", f"thread_{threading.current_thread().ident}")
                results.append(result)
            except Exception as e:
                errors.append(e)
        
        # WHEN: Running concurrent validations
        threads = [threading.Thread(target=validate) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # THEN: Should handle concurrency safely
        assert len(errors) == 0
        assert len(results) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
