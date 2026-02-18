"""
Example usage of TDFOL Security Validator.

Demonstrates all major features including input validation, ZKP audits,
resource limits, DoS prevention, and security reporting.
"""

from ipfs_datasets_py.logic.TDFOL.security_validator import (
    SecurityValidator,
    SecurityConfig,
    SecurityLevel,
    create_validator,
    validate_formula,
    audit_proof,
)


def example_basic_validation():
    """Example 1: Basic formula validation."""
    print("=" * 70)
    print("Example 1: Basic Formula Validation")
    print("=" * 70)
    
    # Create validator with default settings
    validator = SecurityValidator()
    
    # Validate a simple formula
    formula = "∀x. P(x) → Q(x)"
    result = validator.validate_formula(formula)
    
    print(f"Formula: {formula}")
    print(f"Valid: {result.valid}")
    print(f"Errors: {result.errors}")
    print(f"Warnings: {result.warnings}")
    print(f"Threats: {[t.value for t in result.threats]}")
    print()


def example_security_levels():
    """Example 2: Different security levels."""
    print("=" * 70)
    print("Example 2: Security Levels")
    print("=" * 70)
    
    formula = "∀x. P(x) # comment"
    
    # Test with different security levels
    for level in [SecurityLevel.LOW, SecurityLevel.MEDIUM, SecurityLevel.HIGH, SecurityLevel.PARANOID]:
        validator = create_validator(level)
        result = validator.validate_formula(formula)
        
        print(f"\nSecurity Level: {level.value}")
        print(f"Valid: {result.valid}")
        print(f"Errors: {len(result.errors)}")
        print(f"Warnings: {len(result.warnings)}")
    print()


def example_injection_detection():
    """Example 3: Injection attack detection."""
    print("=" * 70)
    print("Example 3: Injection Attack Detection")
    print("=" * 70)
    
    validator = SecurityValidator()
    
    # Test various injection attempts
    dangerous_formulas = [
        "eval(malicious_code)",
        "exec(harmful)",
        "__import__('os')",
        "$(rm -rf /)",
        "test | cat /etc/passwd",
    ]
    
    for formula in dangerous_formulas:
        result = validator.validate_formula(formula)
        print(f"\nFormula: {formula}")
        print(f"Valid: {result.valid}")
        print(f"Threats: {[t.value for t in result.threats]}")
    print()


def example_resource_limits():
    """Example 4: Resource limit enforcement."""
    print("=" * 70)
    print("Example 4: Resource Limit Enforcement")
    print("=" * 70)
    
    # Create validator with custom limits
    config = SecurityConfig(
        max_formula_size=1000,
        max_formula_depth=10,
        max_variables=20,
    )
    validator = SecurityValidator(config)
    
    # Test formulas against limits
    test_cases = [
        ("x" * 1500, "Oversized formula"),
        ("(" * 15 + "x" + ")" * 15, "Too deep nesting"),
        (" ".join([f"x{i}" for i in range(25)]), "Too many variables"),
    ]
    
    for formula, description in test_cases:
        result = validator.validate_formula(formula)
        print(f"\n{description}")
        print(f"Valid: {result.valid}")
        print(f"Errors: {result.errors[:1]}")  # First error
    print()


def example_dos_prevention():
    """Example 5: DoS attack prevention."""
    print("=" * 70)
    print("Example 5: DoS Attack Prevention")
    print("=" * 70)
    
    validator = SecurityValidator()
    
    # Test DoS patterns
    dos_formulas = [
        ("a" * 150, "Excessive repetition"),
        ("∀x1∀x2∀x3∀x4∀x5∀x6∀x7∀x8∀x9∀x10∀x11∀x12. P(x1,x2,x3,x4,x5,x6,x7,x8,x9,x10,x11,x12)", "Exponential complexity"),
    ]
    
    for formula, description in dos_formulas:
        result = validator.validate_formula(formula)
        has_dos = validator.detect_dos_pattern(formula)
        
        print(f"\n{description}")
        print(f"DoS Pattern Detected: {has_dos}")
        print(f"Valid: {result.valid}")
        print(f"Warnings: {len(result.warnings)}")
    print()


def example_rate_limiting():
    """Example 6: Rate limiting."""
    print("=" * 70)
    print("Example 6: Rate Limiting")
    print("=" * 70)
    
    # Create validator with low rate limit
    config = SecurityConfig(max_requests_per_minute=5)
    validator = SecurityValidator(config)
    
    formula = "∀x. P(x)"
    
    # Make multiple requests
    print("Making 7 requests (limit is 5):")
    for i in range(7):
        result = validator.validate_formula(formula, identifier="user123")
        print(f"Request {i+1}: {'✓ Allowed' if result.valid else '✗ Blocked'}")
    print()


def example_input_sanitization():
    """Example 7: Input sanitization."""
    print("=" * 70)
    print("Example 7: Input Sanitization")
    print("=" * 70)
    
    validator = SecurityValidator()
    
    # Test sanitization
    dangerous_inputs = [
        "test\x00null_bytes",
        "eval(dangerous)  and  spaces",
        "test\x01\x02\x03control_chars",
    ]
    
    for input_str in dangerous_inputs:
        sanitized = validator.sanitize_input(input_str)
        print(f"\nOriginal: {repr(input_str)}")
        print(f"Sanitized: {repr(sanitized)}")
    print()


def example_zkp_audit():
    """Example 8: ZKP proof security audit."""
    print("=" * 70)
    print("Example 8: ZKP Proof Security Audit")
    print("=" * 70)
    
    validator = SecurityValidator()
    
    # Valid proof
    valid_proof = {
        'commitment': 'a' * 64,
        'challenge': 'b' * 64,
        'response': 'c' * 64,
    }
    
    result = validator.audit_zkp_proof(valid_proof)
    print("Valid Proof:")
    print(f"Passed: {result.passed}")
    print(f"Risk Level: {result.risk_level}")
    print(f"Vulnerabilities: {len(result.vulnerabilities)}")
    print(f"Recommendations: {len(result.recommendations)}")
    print(f"Audit Time: {result.audit_time:.4f}s")
    
    # Invalid proof
    print("\nInvalid Proof (missing fields):")
    invalid_proof = {'commitment': 'short'}
    result = validator.audit_zkp_proof(invalid_proof)
    print(f"Passed: {result.passed}")
    print(f"Risk Level: {result.risk_level}")
    print(f"Vulnerabilities: {result.vulnerabilities[:2]}")  # First 2
    print()


def example_security_reporting():
    """Example 9: Security event reporting."""
    print("=" * 70)
    print("Example 9: Security Event Reporting")
    print("=" * 70)
    
    validator = SecurityValidator()
    
    # Trigger various security events
    validator.validate_formula("")  # Empty formula
    validator.validate_formula("eval(x)")  # Injection
    validator.validate_formula("x" * 15000)  # Oversized
    
    # Get security report
    report = validator.get_security_report()
    
    print(f"Total Security Events: {report['total_events']}")
    print(f"Threat Breakdown: {report['threat_breakdown']}")
    print(f"Security Level: {report['security_level']}")
    print(f"\nRecent Events:")
    for event in report['recent_events'][-3:]:
        print(f"  - {event['threat_type']}: {event['details']}")
    print()


def example_custom_configuration():
    """Example 10: Custom security configuration."""
    print("=" * 70)
    print("Example 10: Custom Security Configuration")
    print("=" * 70)
    
    # Create custom configuration
    config = SecurityConfig(
        security_level=SecurityLevel.HIGH,
        max_formula_size=5000,
        max_formula_depth=50,
        max_variables=500,
        max_requests_per_minute=50,
        max_concurrent_requests=5,
        max_memory_mb=1000,
        max_proof_time_seconds=60.0,
    )
    
    validator = SecurityValidator(config)
    
    print("Custom Configuration:")
    print(f"Security Level: {config.security_level.value}")
    print(f"Max Formula Size: {config.max_formula_size}")
    print(f"Max Formula Depth: {config.max_formula_depth}")
    print(f"Max Variables: {config.max_variables}")
    print(f"Max Requests/Min: {config.max_requests_per_minute}")
    print(f"Max Concurrent: {config.max_concurrent_requests}")
    print(f"Max Memory (MB): {config.max_memory_mb}")
    print(f"Max Proof Time (s): {config.max_proof_time_seconds}")
    
    # Test validation
    formula = "∀x∃y. (P(x) ∧ Q(y)) → R(x,y)"
    result = validator.validate_formula(formula)
    print(f"\nValidation Result: {'✓ Valid' if result.valid else '✗ Invalid'}")
    print()


def example_convenience_functions():
    """Example 11: Convenience functions."""
    print("=" * 70)
    print("Example 11: Convenience Functions")
    print("=" * 70)
    
    # Quick validation
    result = validate_formula("∀x. P(x) → Q(x)", SecurityLevel.MEDIUM)
    print(f"Quick Validation: {'✓ Valid' if result.valid else '✗ Invalid'}")
    
    # Quick audit
    proof = {
        'commitment': 'a' * 64,
        'challenge': 'b' * 64,
        'response': 'c' * 64,
    }
    audit_result = audit_proof(proof)
    print(f"Quick Audit: {'✓ Passed' if audit_result.passed else '✗ Failed'}")
    print()


def example_comprehensive_validation():
    """Example 12: Comprehensive validation workflow."""
    print("=" * 70)
    print("Example 12: Comprehensive Validation Workflow")
    print("=" * 70)
    
    # Create enterprise-grade validator
    config = SecurityConfig(security_level=SecurityLevel.HIGH)
    validator = SecurityValidator(config)
    
    # Formula to validate
    formula = "∀x∃y. (Person(x) ∧ Knows(x,y)) → Friend(x,y)"
    
    print("Step 1: Input Sanitization")
    sanitized_formula = validator.sanitize_input(formula)
    print(f"Sanitized: {sanitized_formula}")
    
    print("\nStep 2: Security Validation")
    validation_result = validator.validate_formula(sanitized_formula, "user456")
    print(f"Valid: {validation_result.valid}")
    print(f"Errors: {validation_result.errors}")
    print(f"Warnings: {validation_result.warnings}")
    
    print("\nStep 3: DoS Pattern Check")
    has_dos = validator.detect_dos_pattern(sanitized_formula)
    print(f"DoS Pattern: {'Yes' if has_dos else 'No'}")
    
    print("\nStep 4: Resource Limit Check")
    within_limits = validator.check_resource_limits(
        sanitized_formula,
        memory_mb=100,
        time_seconds=5.0
    )
    print(f"Within Limits: {within_limits}")
    
    print("\nStep 5: Security Report")
    report = validator.get_security_report()
    print(f"Total Events: {report['total_events']}")
    print(f"Threat Types: {list(report['threat_breakdown'].keys())}")
    
    print("\n✓ Comprehensive validation complete!")
    print()


def main():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("TDFOL SECURITY VALIDATOR - EXAMPLE USAGE")
    print("=" * 70 + "\n")
    
    examples = [
        example_basic_validation,
        example_security_levels,
        example_injection_detection,
        example_resource_limits,
        example_dos_prevention,
        example_rate_limiting,
        example_input_sanitization,
        example_zkp_audit,
        example_security_reporting,
        example_custom_configuration,
        example_convenience_functions,
        example_comprehensive_validation,
    ]
    
    for example in examples:
        try:
            example()
        except Exception as e:
            print(f"Error in {example.__name__}: {e}\n")
    
    print("=" * 70)
    print("All examples completed!")
    print("=" * 70)


if __name__ == "__main__":
    main()
