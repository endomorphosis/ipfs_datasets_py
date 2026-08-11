"""Audit logging for logic module.

Provides structured audit logging for security and compliance.

DQK-079: mutable file sinks (JSON/JSONL/FileHandler) are disabled by default.
Only ephemeral console logs remain unless an explicit export permit is held.
"""

import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
from ipfs_datasets_py.logic.config import get_config
from ipfs_datasets_py.logic.observability.structured_logging import (
    ObservabilityMutableFileSinkError,
    assert_mutable_file_sink_allowed,
    console_grants_completion_authority,
    console_grants_progress_authority,
    get_observability_filesystem_guard,
    sanitize_publication_view,
)


# Create audit logger — console projection only by default (DQK-079).
audit_logger = logging.getLogger('logic.audit')
audit_logger.setLevel(logging.INFO)
if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
           for h in audit_logger.handlers):
    _console = logging.StreamHandler()
    _console.setLevel(logging.INFO)
    _console.setFormatter(logging.Formatter('%(message)s'))
    audit_logger.addHandler(_console)


class AuditLogger:
    """Structured audit logger for security events."""
    
    def __init__(self, log_path: Optional[str] = None, *, allow_file_sink: bool = False):
        """Initialize audit logger.
        
        Args:
            log_path: Path to audit log file. Ignored unless *allow_file_sink*
                is True and an export permit / legacy-allow is active (DQK-079).
            allow_file_sink: Explicit opt-in for a mutable file sink. Defaults
                to False; file sinks are not authority after cutover.
        """
        self._log_path: Optional[str] = None
        self._file_sink_enabled = False

        if log_path is None and allow_file_sink:
            try:
                config = get_config()
                log_path = config.security.audit_log_path
            except Exception:
                log_path = None

        # DQK-079: do not attach FileHandler unless explicitly permitted.
        if log_path and allow_file_sink:
            path = Path(log_path)
            try:
                assert_mutable_file_sink_allowed(
                    path, kind="audit_jsonl", operation="attach"
                )
            except ObservabilityMutableFileSinkError:
                # Fail closed: keep console-only projection.
                logging.getLogger(__name__).debug(
                    "logic.security audit file sink blocked for %s (DQK-079)",
                    path,
                )
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(path)
            handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(message)s')
            handler.setFormatter(formatter)
            audit_logger.addHandler(handler)
            self._log_path = str(path)
            self._file_sink_enabled = True
    
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
        
        # Console / ephemeral log only. DuckDB cutover (DQK-078/079) is the
        # progress/completion authority; JSON file sinks are not.
        audit_logger.info(json.dumps(event))
        AuditLogger._route_to_observability_shadow(event)

    @staticmethod
    def publication_view(event: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Sanitized publication view excluding secrets and private payloads."""

        view = sanitize_publication_view(event or {})
        view["console_grants_progress_authority"] = console_grants_progress_authority()
        view["console_grants_completion_authority"] = console_grants_completion_authority()
        return view

    @staticmethod
    def export_events_json(file_path: str, events: list) -> str:
        """Explicit deterministic export of security audit events (not authority)."""

        path = Path(file_path)
        guard = get_observability_filesystem_guard()
        with guard.permit_export():
            assert_mutable_file_sink_allowed(path, kind="audit_json", operation="export")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "events": list(events),
                        "export_authority": False,
                        "owner_task": "DQK-079",
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        return str(path)
    
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

    @staticmethod
    def _route_to_observability_shadow(event: Dict[str, Any]) -> None:
        """Project a security audit event into DuckDB cutover (DQK-078) or shadow (DQK-077)."""

        try:
            from ipfs_datasets_py.duckdb_control.observability_adapters import (
                ObservabilityProducer,
                derive_stable_event_id,
            )
            from ipfs_datasets_py.duckdb_control.observability_cutover import (
                try_record_observability_event,
            )
        except Exception:
            return

        event_type = str(event.get("event_type") or "security.event")
        user_id = str(event.get("user_id") or "system")
        success = bool(event.get("success", False))
        event_id = derive_stable_event_id(
            producer=ObservabilityProducer.LOGIC_SECURITY_AUDIT.value,
            action=event_type,
            actor=user_id,
            detail=str(event.get("timestamp") or ""),
            seed=str(event.get("event_id") or "") or None,
        )
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        attributes = {
            "event_type": event_type,
            "success": success,
            **{k: v for k, v in event.items() if k not in {"details", "event_type", "user_id", "success"}},
        }
        if details:
            attributes["details"] = details

        try_record_observability_event(
            producer=ObservabilityProducer.LOGIC_SECURITY_AUDIT,
            action=event_type,
            actor=user_id,
            outcome="succeeded" if success else "failed",
            detail=str((details or {}).get("message") or event_type),
            attributes=attributes,
            event_id=event_id,
            operation_id=f"op-logic-sec-{event_id}",
            raw_payload=event,
            recorded_at=str(event.get("timestamp") or "") or None,
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
