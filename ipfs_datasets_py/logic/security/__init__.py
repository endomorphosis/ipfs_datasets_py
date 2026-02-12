"""Security utilities for logic module.

This module provides security features including:
- Input validation
- Rate limiting
- Audit logging
- Resource limits
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
