# Logic Module Security Guide

**Version:** 2.0  
**Last Updated:** 2026-02-17  
**Status:** Production Security Guide

---

## Table of Contents

- [Security Overview](#security-overview)
- [Threat Model](#threat-model)
- [Input Validation](#input-validation)
- [Rate Limiting](#rate-limiting)
- [Resource Management](#resource-management)
- [Secure Configuration](#secure-configuration)
- [Dependency Security](#dependency-security)
- [Deployment Hardening](#deployment-hardening)
- [Security Checklist](#security-checklist)

---

## Security Overview

The logic module processes untrusted input and must defend against:

- **Denial of Service (DoS)** - Resource exhaustion attacks
- **Code Injection** - Malicious formula execution
- **Data Leakage** - Information disclosure
- **Availability** - Service disruption

### Security Architecture

```
User Input → Validation → Sanitization → Rate Limiting → Processing
                ↓              ↓              ↓             ↓
            Reject         Escape        Throttle      Timeout
```

### Security Layers

1. **Input Validation** - Reject malformed/oversized input
2. **Sanitization** - Escape/normalize input
3. **Rate Limiting** - Prevent abuse
4. **Resource Limits** - Bounded memory/CPU
5. **Timeouts** - Prevent hanging
6. **Sandboxing** - Isolate execution (future)

---

## Threat Model

### In Scope

**Threats We Defend Against:**

1. **DoS via Large Input**
   - Attack: Send 100MB formula to exhaust memory
   - Defense: Input size limits (10KB default)

2. **DoS via Complex Formula**
   - Attack: Send deeply nested formula to exhaust CPU
   - Defense: Depth limits (100 levels default)

3. **DoS via Repeated Requests**
   - Attack: Send 10,000 requests/second
   - Defense: Rate limiting (configurable)

4. **Formula Injection**
   - Attack: Craft formula to exploit parser bugs
   - Defense: Strict parsing, suspicious pattern detection

5. **Resource Exhaustion**
   - Attack: Trigger memory leak or infinite loop
   - Defense: Memory limits, timeouts

### Out of Scope

**Threats We Don't Currently Defend Against:**

1. **Cryptographic Attacks** - ZKP module is simulation-only
2. **Side-Channel Attacks** - Timing attacks on proof search
3. **Supply Chain Attacks** - Compromised dependencies (use Dependabot)
4. **Physical Access** - Assumes secure deployment environment

---

## Input Validation

### Built-in Validation

```python
from ipfs_datasets_py.logic.security import InputValidator

validator = InputValidator(
    max_length=10000,        # Max 10KB input
    max_depth=100,           # Max 100 levels nesting
    max_quantifiers=20,      # Max 20 quantifiers
    forbid_patterns=[        # Blocked patterns
        r"<script",
        r"javascript:",
        r"eval\(",
    ],
)

try:
    validator.validate_text(user_input)
    result = converter.convert(user_input)
except ValidationError as e:
    logger.warning(f"Input validation failed: {e}")
    return {"error": "Invalid input"}
```

### Validation Rules

**Text Length:**
```python
# Reject inputs over 10KB (configurable)
if len(text) > 10000:
    raise InputTooLargeError(
        f"Input {len(text)} bytes exceeds maximum 10000 bytes"
    )
```

**Formula Depth:**
```python
# Reject deeply nested formulas
def check_depth(formula, max_depth=100):
    def depth(node, current=0):
        if current > max_depth:
            raise ValidationError(f"Formula depth {current} exceeds maximum {max_depth}")
        for child in node.children:
            depth(child, current + 1)
    depth(formula.root)
```

**Quantifier Count:**
```python
# Reject formulas with too many quantifiers
quantifiers = count_quantifiers(formula)
if quantifiers > 20:
    raise ValidationError(
        f"Formula has {quantifiers} quantifiers, maximum is 20"
    )
```

**Suspicious Patterns:**
```python
# Detect injection attempts
SUSPICIOUS_PATTERNS = [
    r"<script",           # XSS attempt
    r"javascript:",       # JavaScript injection
    r"eval\(",           # Code execution
    r"\$\{",             # Template injection
    r"__import__",       # Python injection
]

for pattern in SUSPICIOUS_PATTERNS:
    if re.search(pattern, user_input, re.IGNORECASE):
        raise SuspiciousPatternError(
            f"Input contains suspicious pattern: {pattern}"
        )
```

### Custom Validation

```python
class CustomValidator(InputValidator):
    """Extend validation for your use case."""
    
    def validate_text(self, text: str):
        # Call parent validation
        super().validate_text(text)
        
        # Add custom checks
        if "DROP TABLE" in text.upper():
            raise ValidationError("SQL injection attempt detected")
        
        # Check character set
        if not text.isascii():
            raise ValidationError("Only ASCII characters allowed")
        
        # Check word count
        words = text.split()
        if len(words) > 1000:
            raise ValidationError("Input has too many words")
```

---

## Rate Limiting

### Token Bucket Rate Limiter

```python
from ipfs_datasets_py.logic.security import RateLimiter

# Configure rate limiter
limiter = RateLimiter(
    calls=100,            # Allow 100 calls
    period=60,            # Per 60 seconds
    storage="memory",     # or "redis" for distributed
)

# Apply to API endpoint
def convert_endpoint(request):
    user_id = request.user.id
    
    try:
        limiter.check_rate_limit(user_id)
    except RateLimitExceeded as e:
        return {
            "error": "Rate limit exceeded",
            "retry_after": e.retry_after_seconds,
        }, 429
    
    result = converter.convert(request.body)
    return {"result": result}
```

### Distributed Rate Limiting

```python
from ipfs_datasets_py.logic.security import RedisRateLimiter

# Use Redis for multi-server rate limiting
limiter = RedisRateLimiter(
    redis_url="redis://localhost:6379/0",
    calls=100,
    period=60,
    key_prefix="logic:ratelimit:",
)

# Automatically synced across all servers
limiter.check_rate_limit(user_id)
```

### Adaptive Rate Limiting

```python
class AdaptiveRateLimiter:
    """Adjust rate limits based on system load."""
    
    def __init__(self, base_calls=100, base_period=60):
        self.base_calls = base_calls
        self.base_period = base_period
    
    def check_rate_limit(self, user_id):
        # Get system load
        load = psutil.cpu_percent()
        
        # Reduce limits under high load
        if load > 80:
            effective_calls = self.base_calls // 2
        elif load > 60:
            effective_calls = int(self.base_calls * 0.75)
        else:
            effective_calls = self.base_calls
        
        # Check limit
        limiter = RateLimiter(effective_calls, self.base_period)
        limiter.check_rate_limit(user_id)
```

### Per-Endpoint Limits

```python
# Different limits for different endpoints
limiters = {
    "convert": RateLimiter(calls=100, period=60),     # 100/min for conversions
    "prove": RateLimiter(calls=20, period=60),        # 20/min for proofs (expensive)
    "batch": RateLimiter(calls=5, period=60),         # 5/min for batch operations
}

def handle_request(endpoint, user_id, request):
    limiter = limiters[endpoint]
    limiter.check_rate_limit(user_id)
    return process_request(request)
```

---

## Resource Management

### Memory Limits

```python
import resource

# Set maximum memory per process (500MB)
soft, hard = resource.getrlimit(resource.RLIMIT_AS)
resource.setrlimit(resource.RLIMIT_AS, (500 * 1024 * 1024, hard))

# Or use cgroups in production
```

### Timeout Protection

```python
from ipfs_datasets_py.logic.integration import prove_formula
import signal

def timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")

# Set timeout
signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(30)  # 30 second timeout

try:
    result = prove_formula(formula)
finally:
    signal.alarm(0)  # Cancel timeout
```

### Process Isolation

```python
from concurrent.futures import ProcessPoolExecutor
import multiprocessing

def isolated_prove(formula):
    """Prove in isolated process with resource limits."""
    def worker(formula):
        # Set resource limits in worker process
        import resource
        resource.setrlimit(
            resource.RLIMIT_AS,
            (500 * 1024 * 1024, 500 * 1024 * 1024)  # 500MB limit
        )
        
        return prove_formula(formula, timeout=30)
    
    with ProcessPoolExecutor(max_workers=1) as executor:
        future = executor.submit(worker, formula)
        try:
            return future.result(timeout=35)  # 5s buffer
        except Exception as e:
            logger.error(f"Isolated proof failed: {e}")
            return None
```

### Bounded Proof Search

```python
def safe_prove(formula, max_states=1000):
    """Prove with bounded state space."""
    prover = Prover()
    prover.max_states = max_states  # Limit explored states
    prover.max_depth = 10           # Limit search depth
    prover.max_time = 30            # Limit time
    
    try:
        return prover.prove(formula)
    except ResourceExhaustedError:
        logger.warning(f"Proof search exhausted {max_states} states")
        return ProofResult(status=ProofStatus.TIMEOUT)
```

---

## Secure Configuration

### Configuration Validation

```python
from ipfs_datasets_py.logic.config import LogicConfig

# Secure defaults
config = LogicConfig(
    max_input_size=10000,           # 10KB max input
    max_formula_depth=100,          # 100 levels max
    max_proof_time=30,              # 30s timeout
    enable_cache=True,              # Enable caching
    cache_max_size=1000,            # Limit cache size
    rate_limit_enabled=True,        # Enable rate limiting
    rate_limit_calls=100,           # 100 calls/min
    suspicious_pattern_check=True,  # Check for suspicious patterns
)

# Validate configuration
config.validate()

# Use configuration
converter = FOLConverter(config=config)
```

### Environment-Specific Configs

```python
import os

# Development: Relaxed limits
if os.getenv("ENV") == "development":
    config = LogicConfig(
        max_input_size=100000,       # 100KB
        max_proof_time=300,          # 5 min
        rate_limit_enabled=False,    # No rate limiting
    )

# Production: Strict limits
elif os.getenv("ENV") == "production":
    config = LogicConfig(
        max_input_size=10000,        # 10KB
        max_proof_time=30,           # 30s
        rate_limit_enabled=True,     # Rate limiting on
        rate_limit_calls=50,         # Stricter limits
    )
```

### Secrets Management

```python
# DON'T: Hardcode credentials
config = LogicConfig(
    redis_url="redis://password@localhost:6379/0"
)

# DO: Use environment variables
config = LogicConfig(
    redis_url=os.getenv("REDIS_URL")
)

# DO: Use secrets manager
from secrets_manager import get_secret
config = LogicConfig(
    redis_url=get_secret("logic/redis_url")
)
```

---

## Dependency Security

### Vulnerability Scanning

```bash
# Scan dependencies for known vulnerabilities
pip install safety
safety check --full-report

# Or use in CI/CD
safety check --json > security-report.json
```

### Pinned Dependencies

```txt
# requirements.txt - Pin exact versions
ipfs-datasets-py==2.0.0
spacy==3.5.0
z3-solver==4.12.2.0
```

### Regular Updates

```bash
# Check for outdated packages
pip list --outdated

# Update dependencies
pip install --upgrade ipfs-datasets-py

# Test after updates
pytest tests/
```

### Dependency Isolation

```bash
# Use virtual environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Or use Docker
docker build -t logic-module .
docker run --rm logic-module pytest
```

---

## Deployment Hardening

### Docker Security

```dockerfile
# Use minimal base image
FROM python:3.12-slim

# Run as non-root user
RUN useradd -m -u 1000 logic
USER logic

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY --chown=logic:logic . /app
WORKDIR /app

# Set resource limits
ENV MEMORY_LIMIT=512M
ENV CPU_LIMIT=1

# Run application
CMD ["python", "-m", "ipfs_datasets_py.logic"]
```

### Kubernetes Security

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: logic-module
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000
  
  containers:
  - name: logic
    image: logic-module:2.0.0
    
    # Resource limits
    resources:
      limits:
        memory: "512Mi"
        cpu: "1000m"
      requests:
        memory: "256Mi"
        cpu: "500m"
    
    # Security context
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop:
        - ALL
    
    # Health checks
    livenessProbe:
      httpGet:
        path: /health
        port: 8080
      initialDelaySeconds: 30
      periodSeconds: 10
    
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      initialDelaySeconds: 10
      periodSeconds: 5
```

### Network Security

```python
# API endpoint with security headers
from flask import Flask, request, jsonify
from flask_limiter import Limiter

app = Flask(__name__)

# Rate limiting
limiter = Limiter(
    app,
    key_func=lambda: request.remote_addr,
    default_limits=["100 per minute"]
)

# Security headers
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Content-Security-Policy'] = "default-src 'self'"
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# Endpoint with validation
@app.route('/convert', methods=['POST'])
@limiter.limit("50 per minute")
def convert():
    # Validate input
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({"error": "Missing text"}), 400
    
    text = data['text']
    if len(text) > 10000:
        return jsonify({"error": "Input too large"}), 400
    
    # Process
    try:
        validator = InputValidator()
        validator.validate_text(text)
        result = converter.convert(text)
        return jsonify({"result": result.fol})
    except ValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Conversion failed")
        return jsonify({"error": "Internal error"}), 500
```

---

## Security Checklist

### Development

- [ ] Input validation on all user input
- [ ] Sanitization of formula text
- [ ] Resource limits configured
- [ ] Timeouts on all operations
- [ ] Error messages don't leak information
- [ ] Logging doesn't include sensitive data
- [ ] Dependencies scanned for vulnerabilities
- [ ] Security tests included in test suite

### Deployment

- [ ] Run as non-root user
- [ ] Resource limits enforced (memory, CPU)
- [ ] Rate limiting enabled
- [ ] Secrets in environment or secrets manager
- [ ] TLS/HTTPS for network traffic
- [ ] Network policies restrict access
- [ ] Container security scanning
- [ ] Regular security updates applied

### Monitoring

- [ ] Log suspicious activity
- [ ] Alert on rate limit violations
- [ ] Monitor resource usage
- [ ] Track error rates
- [ ] Audit logs for sensitive operations
- [ ] Automated vulnerability scanning
- [ ] Incident response plan documented

---

## Security Testing

### Fuzzing

```python
import hypothesis
from hypothesis import strategies as st

@hypothesis.given(st.text(min_size=0, max_size=100000))
def test_fuzz_converter(text):
    """Fuzz test converter with random input."""
    try:
        validator = InputValidator()
        validator.validate_text(text)
        result = converter.convert(text)
    except (ValidationError, ConversionError):
        # Expected errors are OK
        pass
    except Exception as e:
        # Unexpected errors should fail test
        pytest.fail(f"Unexpected error: {e}")
```

### Penetration Testing

```python
def test_dos_large_input():
    """Test DoS via large input."""
    large_input = "a" * 1_000_000  # 1MB
    
    with pytest.raises(InputTooLargeError):
        validator.validate_text(large_input)

def test_dos_deep_nesting():
    """Test DoS via deep nesting."""
    formula = "P"
    for _ in range(200):  # 200 levels deep
        formula = f"¬({formula})"
    
    with pytest.raises(ValidationError, match="depth"):
        validator.validate_formula(formula)

def test_injection_attempt():
    """Test code injection attempt."""
    malicious = "__import__('os').system('rm -rf /')"
    
    with pytest.raises(SuspiciousPatternError):
        validator.validate_text(malicious)
```

### Security Regression Tests

```python
def test_cve_2024_12345():
    """Regression test for CVE-2024-12345."""
    # Specific exploit that was patched
    exploit = "specific malicious input"
    
    # Should be rejected by current version
    with pytest.raises(ValidationError):
        validator.validate_text(exploit)
```

---

## Incident Response

### Security Incident Procedure

1. **Detect** - Monitor alerts for suspicious activity
2. **Contain** - Rate limit or block attacker
3. **Investigate** - Review logs and determine impact
4. **Remediate** - Patch vulnerability
5. **Document** - Create incident report
6. **Review** - Update security measures

### Contact Information

**Security Issues:**
- Email: security@example.com
- PGP Key: https://example.com/pgp-key.asc
- Response Time: 24-48 hours

**Vulnerability Disclosure:**
- Follow responsible disclosure guidelines
- Allow 90 days for patch before public disclosure
- Credit will be given in security advisories

---

## Additional Resources

**Security Documentation:**
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [CWE Top 25](https://cwe.mitre.org/top25/)
- [Python Security Best Practices](https://python.readthedocs.io/en/latest/library/security_warnings.html)

**Tools:**
- [Safety](https://github.com/pyupio/safety) - Vulnerability scanner
- [Bandit](https://github.com/PyCQA/bandit) - Security linter
- [OWASP Dependency-Check](https://owasp.org/www-project-dependency-check/)

**Related Documentation:**
- [ERROR_REFERENCE.md](./ERROR_REFERENCE.md) - Security exceptions
- [API_VERSIONING.md](./API_VERSIONING.md) - Security patches policy
- [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) - Production deployment

---

## Summary

**Core Security Measures:**
- ✅ Input validation (size, depth, patterns)
- ✅ Rate limiting (per-user, per-endpoint)
- ✅ Resource limits (memory, CPU, time)
- ✅ Suspicious pattern detection
- ✅ Secure configuration management

**Deployment Security:**
- ✅ Non-root execution
- ✅ Container hardening
- ✅ Network security
- ✅ Secret management
- ✅ Regular updates

**Ongoing Security:**
- ✅ Vulnerability scanning
- ✅ Security testing
- ✅ Monitoring and alerting
- ✅ Incident response
- ✅ Regular reviews

**For questions:** Open a security issue on GitHub with label `security`

---

**Document Status:** Active Security Guide  
**Maintained By:** Logic Module Security Team  
**Review Frequency:** Quarterly + After Security Incidents
