"""Audit logging for logic module.

Provides structured audit logging for security and compliance.
"""

import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
from ipfs_datasets_py.logic.config import get_config


# Create audit logger
audit_logger = logging.getLogger('logic.audit')
audit_logger.setLevel(logging.INFO)


class AuditLogger:
    """Structured audit logger for security events."""
    
    def __init__(self, log_path: Optional[str] = None):
        """Initialize audit logger.
        
        Args:
            log_path: Path to audit log file. If None, uses config or stderr.
        """
        if log_path is None:
            config = get_config()
            log_path = config.security.audit_log_path
        
        # Set up file handler if path provided
        if log_path:
            path = Path(log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            
            handler = logging.FileHandler(path)
            handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(message)s')
            handler.setFormatter(formatter)
            audit_logger.addHandler(handler)
    
    @staticmethod
    def log_event(
        event_type: str,
        user_id: str,
        success: bool,
        details: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        """Log an audit event.
        
        Args:
            event_type: Type of event (e.g., 'proof_attempt', 'security_violation')
            user_id: User identifier
            success: Whether operation succeeded
            details: Additional details about the event
            **kwargs: Additional fields to include
        """
        event = {
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': event_type,
            'user_id': user_id,
            'success': success
        }
        
        if details:
            event['details'] = details
        
        # Add any additional fields
        event.update(kwargs)
        
        # Log as JSON
        audit_logger.info(json.dumps(event))
    
    @staticmethod
    def log_proof_attempt(
        user_id: str,
        formula: str,
        prover: str,
        success: bool,
        duration_ms: float,
        cached: bool = False,
        error: Optional[str] = None
    ) -> None:
        """Log a proof attempt.
        
        Args:
            user_id: User identifier
            formula: Formula being proved (truncated)
            prover: Prover used
            success: Whether proof succeeded
            duration_ms: Time taken in milliseconds
            cached: Whether result was from cache
            error: Error message if failed
        """
        details = {
            'formula': formula[:100],  # Truncate long formulas
            'prover': prover,
            'duration_ms': duration_ms,
            'cached': cached
        }
        
        if error:
            details['error'] = error
        
        AuditLogger.log_event(
            event_type='proof_attempt',
            user_id=user_id,
            success=success,
            details=details
        )
    
    @staticmethod
    def log_security_event(
        user_id: str,
        event_type: str,
        severity: str,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log a security event.
        
        Args:
            user_id: User identifier
            event_type: Type of security event
            severity: Severity level (low, medium, high, critical)
            message: Human-readable message
            details: Additional details
        """
        event_details = {
            'severity': severity,
            'message': message
        }
        
        if details:
            event_details.update(details)
        
        AuditLogger.log_event(
            event_type=f'security.{event_type}',
            user_id=user_id,
            success=False,  # Security events are typically violations
            details=event_details
        )
    
    @staticmethod
    def log_rate_limit_exceeded(
        user_id: str,
        calls: int,
        period: int
    ) -> None:
        """Log rate limit exceeded event.
        
        Args:
            user_id: User identifier
            calls: Number of calls allowed
            period: Time period in seconds
        """
        AuditLogger.log_security_event(
            user_id=user_id,
            event_type='rate_limit_exceeded',
            severity='medium',
            message=f'User exceeded rate limit of {calls} calls per {period}s',
            details={'limit_calls': calls, 'limit_period': period}
        )
    
    @staticmethod
    def log_validation_error(
        user_id: str,
        validation_type: str,
        error_message: str
    ) -> None:
        """Log input validation error.
        
        Args:
            user_id: User identifier
            validation_type: Type of validation that failed
            error_message: Error message
        """
        AuditLogger.log_security_event(
            user_id=user_id,
            event_type='validation_error',
            severity='low',
            message=f'Input validation failed: {validation_type}',
            details={'validation_type': validation_type, 'error': error_message}
        )


# Global audit logger instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def log_proof_attempt(
    user_id: str,
    formula: str,
    prover: str,
    success: bool,
    duration_ms: float,
    cached: bool = False,
    error: Optional[str] = None
) -> None:
    """Log a proof attempt.
    
    Convenience function using global logger.
    """
    get_audit_logger().log_proof_attempt(
        user_id=user_id,
        formula=formula,
        prover=prover,
        success=success,
        duration_ms=duration_ms,
        cached=cached,
        error=error
    )


def log_security_event(
    user_id: str,
    event_type: str,
    severity: str,
    message: str,
    details: Optional[Dict[str, Any]] = None
) -> None:
    """Log a security event.
    
    Convenience function using global logger.
    """
    get_audit_logger().log_security_event(
        user_id=user_id,
        event_type=event_type,
        severity=severity,
        message=message,
        details=details
    )
