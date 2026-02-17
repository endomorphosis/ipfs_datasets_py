"""Security utilities for logic module.

This module provides comprehensive security features including:
- **Input validation** - Prevents injection attacks and resource exhaustion
- **Rate limiting** - Prevents DoS attacks with sliding window algorithm
- **Audit logging** - Tracks security events and proof attempts
- **Resource limits** - Protects against excessively complex formulas

## Production Status

**Status:** ✅ Production-Ready (Basic Implementation)

All components are functional and actively used in:
- `proof_execution_engine.py` - Rate limiting and input validation
- `deontic_query_engine.py` - Query validation and rate limiting
- `logic_translation_core.py` - Translation validation

## Usage Examples

### Input Validation

```python
from ipfs_datasets_py.logic.security import InputValidator, ValidationError

validator = InputValidator()

# Validate text length and content
try:
    text = validator.validate_text("user input text")
except ValidationError as e:
    print(f"Invalid input: {e}")

# Validate formula complexity
try:
    validator.validate_formula(formula_object)
except ValidationError as e:
    print(f"Formula too complex: {e}")
```

### Rate Limiting

```python
from ipfs_datasets_py.logic.security import RateLimiter, RateLimitExceeded

limiter = RateLimiter(calls=100, period=60)  # 100 calls per minute

# Check rate limit
try:
    limiter.check_rate_limit(user_id="user123")
except RateLimitExceeded as e:
    print(f"Rate limit exceeded: {e}")

# Or use as decorator
@limiter
def expensive_operation(user_id: str):
    # Your code here
    pass
```

### Audit Logging

```python
from ipfs_datasets_py.logic.security import AuditLogger

logger = AuditLogger()

# Log proof attempt
logger.log_proof_attempt(
    formula="∀x P(x)",
    user_id="user123",
    success=True,
    duration=1.5
)

# Log security event
logger.log_security_event(
    event_type="rate_limit_exceeded",
    user_id="user123",
    details={"attempts": 105}
)
```

## Configuration

Security limits are configurable via `logic/config.py`:

```python
security:
    max_text_length: 10000         # Max input text length
    max_formula_depth: 100         # Max formula nesting
    max_formula_complexity: 1000   # Max formula nodes
    rate_limit_calls: 100          # Calls per period
    rate_limit_period: 60          # Period in seconds
```

## Future Enhancements

**v1.1 (Planned):**
- IP-based rate limiting
- Distributed rate limiting (Redis)
- Enhanced audit log storage
- Real-time security monitoring

**v1.5 (Planned):**
- Advanced formula analysis
- Pattern-based attack detection
- Integration with security frameworks

See [KNOWN_LIMITATIONS.md](../KNOWN_LIMITATIONS.md) for current limitations.
"""

from .input_validation import (
    InputValidator,
    ValidationError,
    validate_text,
    validate_formula,
    validate_formula_list
)

from .rate_limiting import (
    RateLimiter,
    RateLimitExceeded,
    rate_limit
)

from .audit_log import (
    AuditLogger,
    log_proof_attempt,
    log_security_event
)

__all__ = [
    # Input validation
    'InputValidator',
    'ValidationError',
    'validate_text',
    'validate_formula',
    'validate_formula_list',
    
    # Rate limiting
    'RateLimiter',
    'RateLimitExceeded',
    'rate_limit',
    
    # Audit logging
    'AuditLogger',
    'log_proof_attempt',
    'log_security_event'
]
