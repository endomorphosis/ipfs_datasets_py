# TDFOL Security Validator

Enterprise-grade security validation for TDFOL (Typed Distributed First-Order Logic) theorem proving. Part of Phase 12 Task 12.2.

## Overview

The Security Validator provides comprehensive security features for theorem proving including:

- **Input Validation**: Formula sanitization, type checking, and malformed input detection
- **ZKP Security Audit**: Cryptographic proof verification and side-channel attack detection
- **Resource Limits**: Memory, time, and complexity limits to prevent resource exhaustion
- **DoS Prevention**: Rate limiting, recursive bomb detection, and complex formula rejection
- **Threat Detection**: Injection attacks, timing attacks, and malicious pattern detection
- **Security Reporting**: Event logging, threat analysis, and security audits

## Features

### 🛡️ Security Levels

Four configurable security levels to balance security and performance:

- **LOW**: Permissive validation with warnings
- **MEDIUM**: Balanced security (default)
- **HIGH**: Strict validation with character whitelisting
- **PARANOID**: Maximum security with aggressive filtering

### 🔍 Input Validation

- Formula size limits (default: 10,000 characters)
- Nesting depth limits (default: 100 levels)
- Variable count limits (default: 1,000 variables)
- Operator count limits (default: 5,000 operators)
- Character whitelist/blacklist enforcement
- Null byte and control character detection

### 🔐 ZKP Security Audit

- Proof structure validation
- Cryptographic parameter checking
- Timing attack detection
- Side-channel analysis
- Proof integrity verification
- Entropy analysis

### ⚡ Resource Limits

- Maximum memory usage (default: 500 MB)
- Maximum proof time (default: 30 seconds)
- Maximum stack depth (default: 1,000 levels)
- Automatic timeout enforcement

### 🚫 DoS Prevention

- Rate limiting (default: 100 requests/minute)
- Concurrent request limits (default: 10 concurrent)
- Excessive repetition detection
- Exponential complexity detection
- Recursive bomb detection
- Resource exhaustion prevention

### 🧹 Formula Sanitization

- Dangerous pattern removal
- Whitespace normalization
- Control character stripping
- Length limiting
- Safe escaping

## Installation

```bash
# Standard installation
pip install -e .

# With development dependencies
pip install -e ".[test]"
```

## Quick Start

### Basic Usage

```python
from ipfs_datasets_py.logic.TDFOL.security_validator import SecurityValidator

# Create validator
validator = SecurityValidator()

# Validate a formula
formula = "∀x. P(x) → Q(x)"
result = validator.validate_formula(formula)

if result.valid:
    print("✓ Formula is secure")
else:
    print(f"✗ Security issues: {result.errors}")
```

### Security Levels

```python
from ipfs_datasets_py.logic.TDFOL.security_validator import (
    SecurityValidator,
    SecurityConfig,
    SecurityLevel
)

# Create high-security validator
config = SecurityConfig(security_level=SecurityLevel.HIGH)
validator = SecurityValidator(config)

result = validator.validate_formula(formula)
```

### ZKP Proof Audit

```python
# Audit a ZKP proof
proof = {
    'commitment': 'a' * 64,
    'challenge': 'b' * 64,
    'response': 'c' * 64,
}

audit = validator.audit_zkp_proof(proof)
print(f"Audit passed: {audit.passed}")
print(f"Risk level: {audit.risk_level}")
print(f"Vulnerabilities: {audit.vulnerabilities}")
```

### Input Sanitization

```python
# Sanitize potentially dangerous input
dangerous_input = "test\x00eval(malicious)"
safe_input = validator.sanitize_input(dangerous_input)
print(f"Sanitized: {safe_input}")
```

## API Reference

### SecurityValidator

Main security validation class.

#### Methods

##### `validate_formula(formula: str, identifier: str = "default") -> ValidationResult`

Validate formula for security threats.

**Parameters:**
- `formula`: Formula string to validate
- `identifier`: Unique identifier for rate limiting

**Returns:** `ValidationResult` with validation status and details

##### `sanitize_input(input_str: str) -> str`

Sanitize input string for safe processing.

**Parameters:**
- `input_str`: Input to sanitize

**Returns:** Sanitized string

##### `check_resource_limits(formula: str, memory_mb: float = None, time_seconds: float = None) -> bool`

Check if formula is within resource limits.

**Parameters:**
- `formula`: Formula to check
- `memory_mb`: Current memory usage
- `time_seconds`: Current execution time

**Returns:** True if within limits

##### `audit_zkp_proof(proof: Dict[str, Any], formula: str = None) -> AuditResult`

Audit ZKP proof for security vulnerabilities.

**Parameters:**
- `proof`: ZKP proof dictionary
- `formula`: Optional associated formula

**Returns:** `AuditResult` with audit findings

##### `detect_dos_pattern(formula: str) -> bool`

Detect DoS attack patterns.

**Parameters:**
- `formula`: Formula to analyze

**Returns:** True if DoS pattern detected

##### `get_security_report() -> Dict[str, Any]`

Generate security report with statistics and events.

**Returns:** Dictionary with security data

### SecurityConfig

Security configuration parameters.

**Attributes:**
- `max_formula_size`: Maximum formula length (default: 10,000)
- `max_formula_depth`: Maximum nesting depth (default: 100)
- `max_variables`: Maximum variable count (default: 1,000)
- `max_operators`: Maximum operator count (default: 5,000)
- `max_memory_mb`: Maximum memory usage (default: 500 MB)
- `max_proof_time_seconds`: Maximum proof time (default: 30s)
- `max_stack_depth`: Maximum stack depth (default: 1,000)
- `max_requests_per_minute`: Rate limit (default: 100)
- `max_concurrent_requests`: Concurrent limit (default: 10)
- `security_level`: Security enforcement level (default: MEDIUM)

### ValidationResult

Validation result dataclass.

**Attributes:**
- `valid`: Whether validation passed
- `errors`: List of error messages
- `warnings`: List of warning messages
- `threats`: List of detected threat types
- `metadata`: Additional metadata

### AuditResult

ZKP audit result dataclass.

**Attributes:**
- `passed`: Whether audit passed
- `vulnerabilities`: List of vulnerabilities found
- `recommendations`: List of recommendations
- `risk_level`: Overall risk level (low/medium/high/critical)
- `audit_time`: Time taken for audit

## Security Best Practices

### 1. Always Validate Input

```python
# ✓ Good: Validate before processing
result = validator.validate_formula(user_input)
if result.valid:
    process_formula(user_input)
else:
    handle_error(result.errors)

# ✗ Bad: Process without validation
process_formula(user_input)  # Dangerous!
```

### 2. Use Appropriate Security Levels

```python
# For untrusted input (public API)
config = SecurityConfig(security_level=SecurityLevel.HIGH)

# For trusted internal use
config = SecurityConfig(security_level=SecurityLevel.MEDIUM)

# For maximum security (sensitive data)
config = SecurityConfig(security_level=SecurityLevel.PARANOID)
```

### 3. Sanitize Before Validation

```python
# ✓ Good: Sanitize then validate
sanitized = validator.sanitize_input(user_input)
result = validator.validate_formula(sanitized)

# ✗ Bad: Trust user input
result = validator.validate_formula(user_input)
```

### 4. Check Resource Limits

```python
import psutil
import time

start_time = time.time()
process = psutil.Process()

# During processing, check limits
if not validator.check_resource_limits(
    formula,
    memory_mb=process.memory_info().rss / 1024 / 1024,
    time_seconds=time.time() - start_time
):
    raise ResourceExhaustedError("Resource limits exceeded")
```

### 5. Audit ZKP Proofs

```python
# Always audit proofs before verification
audit = validator.audit_zkp_proof(proof)
if not audit.passed:
    raise SecurityError(f"Proof audit failed: {audit.vulnerabilities}")

if audit.risk_level in ["high", "critical"]:
    raise SecurityError(f"High risk proof: {audit.risk_level}")

# Proceed with verification
verify_proof(proof)
```

### 6. Monitor Security Events

```python
# Periodically check security report
report = validator.get_security_report()

if report['total_events'] > 100:
    alert_security_team(report)

# Check for specific threats
if 'injection' in report['threat_breakdown']:
    investigate_injection_attempts()
```

### 7. Rate Limit Per User

```python
# Use unique identifiers for rate limiting
user_id = get_user_id()
result = validator.validate_formula(formula, identifier=user_id)

if not result.valid and ThreatType.DOS in result.threats:
    log_rate_limit_violation(user_id)
```

### 8. Handle Concurrent Requests

```python
# Check concurrent limits before processing
if validator.concurrent_requests >= validator.config.max_concurrent_requests:
    return error_response("Server too busy, try again later")

# Process with validation
result = validator.validate_formula(formula)
```

### 9. Log Security Events

```python
import logging

logger = logging.getLogger(__name__)

result = validator.validate_formula(formula, identifier=user_id)
if not result.valid:
    logger.warning(
        f"Security validation failed for user {user_id}: "
        f"errors={result.errors}, threats={result.threats}"
    )
```

### 10. Regular Security Audits

```python
# Schedule periodic security audits
def scheduled_security_audit():
    report = validator.get_security_report()
    
    # Generate audit report
    audit_report = {
        'timestamp': datetime.now(),
        'total_events': report['total_events'],
        'threat_breakdown': report['threat_breakdown'],
        'high_risk_events': [
            e for e in report['recent_events']
            if e['threat_type'] in ['injection', 'dos']
        ]
    }
    
    save_audit_report(audit_report)
    validator.clear_security_events()
```

## Threat Detection

### Injection Attacks

Detects and blocks:
- Code injection (`eval`, `exec`, `compile`)
- Command injection (`$()`, backticks, pipes)
- Python internals access (`__import__`, `getattr`)
- SQL injection patterns

### DoS Attacks

Detects and blocks:
- Excessive character repetition
- Exponential complexity patterns
- Deeply nested quantifiers
- Recursive bombs
- Resource exhaustion attempts

### Timing Attacks

Monitors for:
- Timing variance in verification
- Side-channel information leakage
- Constant-time operation violations

### Malformed Input

Detects:
- Null bytes
- Control characters
- Invalid character encodings
- Unbalanced parentheses
- Syntax errors

## Examples

See `examples/logic/TDFOL/security_validator_examples.py` for comprehensive examples including:

1. Basic formula validation
2. Security level configuration
3. Injection attack detection
4. Resource limit enforcement
5. DoS prevention
6. Rate limiting
7. Input sanitization
8. ZKP proof auditing
9. Security reporting
10. Custom configuration
11. Convenience functions
12. Comprehensive workflows

Run examples:
```bash
python examples/logic/TDFOL/security_validator_examples.py
```

## Testing

Comprehensive test suite with 25+ security tests:

```bash
# Run all security tests
pytest tests/unit/logic/TDFOL/test_security_validator.py -v

# Run specific test categories
pytest tests/unit/logic/TDFOL/test_security_validator.py -k "injection" -v
pytest tests/unit/logic/TDFOL/test_security_validator.py -k "dos" -v
pytest tests/unit/logic/TDFOL/test_security_validator.py -k "zkp" -v

# Run with coverage
pytest tests/unit/logic/TDFOL/test_security_validator.py --cov=ipfs_datasets_py.logic.TDFOL.security_validator --cov-report=html
```

Test categories:
- Input validation (7 tests)
- Character validation (3 tests)
- Injection detection (4 tests)
- DoS prevention (3 tests)
- Recursive bombs (2 tests)
- Rate limiting (3 tests)
- Concurrent requests (1 test)
- Input sanitization (5 tests)
- Resource limits (2 tests)
- ZKP audit (7 tests)
- Security levels (2 tests)
- Security reporting (2 tests)
- Convenience functions (3 tests)
- Edge cases (4 tests)

## Performance

Typical performance metrics:

- Basic validation: ~0.001s
- Full validation: ~0.01s
- ZKP audit: ~0.05s
- Sanitization: ~0.0001s

Resource usage:
- Memory: ~10 MB per validator instance
- CPU: <1% during validation
- Thread-safe for concurrent use

## Troubleshooting

### Common Issues

**Issue**: Rate limit exceeded
```python
# Solution: Increase rate limit or use per-user identifiers
config = SecurityConfig(max_requests_per_minute=200)
validator = SecurityValidator(config)
```

**Issue**: Formula too large
```python
# Solution: Increase size limit or chunk formula
config = SecurityConfig(max_formula_size=50000)
validator = SecurityValidator(config)
```

**Issue**: False positives in injection detection
```python
# Solution: Use lower security level or whitelist patterns
config = SecurityConfig(security_level=SecurityLevel.MEDIUM)
validator = SecurityValidator(config)
```

## Integration

### With TDFOL Prover

```python
from ipfs_datasets_py.logic.TDFOL.prover import TDFOLProver
from ipfs_datasets_py.logic.TDFOL.security_validator import SecurityValidator

# Create integrated prover with security
class SecureTDFOLProver(TDFOLProver):
    def __init__(self):
        super().__init__()
        self.validator = SecurityValidator()
    
    def prove(self, formula: str) -> ProofResult:
        # Validate before proving
        validation = self.validator.validate_formula(formula)
        if not validation.valid:
            raise SecurityError(f"Formula validation failed: {validation.errors}")
        
        # Proceed with proof
        return super().prove(formula)
```

### With Web API

```python
from flask import Flask, request, jsonify
from ipfs_datasets_py.logic.TDFOL.security_validator import SecurityValidator

app = Flask(__name__)
validator = SecurityValidator()

@app.route('/validate', methods=['POST'])
def validate_endpoint():
    formula = request.json.get('formula')
    user_id = request.headers.get('User-ID', 'anonymous')
    
    result = validator.validate_formula(formula, identifier=user_id)
    
    return jsonify({
        'valid': result.valid,
        'errors': result.errors,
        'warnings': result.warnings,
        'threats': [t.value for t in result.threats]
    })
```

## Contributing

When contributing to security validation:

1. Follow secure coding practices
2. Add tests for new security features
3. Document security implications
4. Review code for vulnerabilities
5. Update security best practices

## License

Part of the IPFS Datasets Python project.

## References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [CWE/SANS Top 25](https://cwe.mitre.org/top25/)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)
- [Zero-Knowledge Proof Security](https://eprint.iacr.org/)

## Support

For security issues, please report to the security team following responsible disclosure practices.

---

**Phase 12 Task 12.2** - Enterprise-Grade Security Validation for TDFOL
