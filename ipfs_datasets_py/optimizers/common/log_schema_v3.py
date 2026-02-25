"""JSON Log Schema v3 - Complete standardization for optimizer logging.

This module defines the canonical schema for all optimizer structured JSON logs.
Version 3 adds:
- Session-level event tracking
- Iteration/round-level events
- Resource usage tracking  
- Error classification
- Universal field naming conventions

Schema Compliance:
    All optimizer logs MUST include:
    - schema: "ipfs_datasets_py.optimizer_log"
    - schema_version: 3
    - event: Event type from EventType enum
    - timestamp: Unix timestamp (float)
    
    All optimizer logs SHOULD include:
    - session_id: Unique session identifier
    - domain: Optimizer domain (code, logic, graph, etc.)
    - component: Which component emitted the log

Usage:
    >>> from ipfs_datasets_py.optimizers.common.log_schema_v3 import (
    ...     log_session_start,
    ...     log_iteration_complete,
    ...     log_error,
    ... )
    >>> 
    >>> import logging
    >>> logger = logging.getLogger(__name__)
    >>> 
    >>> log_session_start(logger, session_id="sess-001", domain="graph", input_size=1000)
    >>> log_iteration_complete(logger, session_id="sess-001", iteration=1, score=0.75)
    >>> log_error(logger, "extraction_failed", error_msg="Timeout", session_id="sess-001")
"""

from __future__ import annotations

import json
import logging
import time
from enum import Enum
from typing import Any, Dict, Literal, Optional

from ipfs_datasets_py.optimizers.common.structured_logging import redact_payload

SCHEMA_NAME = "ipfs_datasets_py.optimizer_log"
SCHEMA_VERSION = 3


class EventType(Enum):
    """Standard event types for optimizer logs (schema v3)."""
    
    # Session lifecycle
    SESSION_STARTED = "session.started"
    SESSION_COMPLETED = "session.completed"
    SESSION_FAILED = "session.failed"
    
    # Iteration/round lifecycle
    ITERATION_STARTED = "iteration.started"
    ITERATION_COMPLETED = "iteration.completed"
    
    # Generation events
    GENERATE_STARTED = "generate.started"
    GENERATE_COMPLETED = "generate.completed"
    GENERATE_FAILED = "generate.failed"
    
    # Critique events
    CRITIQUE_STARTED = "critique.started"
    CRITIQUE_COMPLETED = "critique.completed"
    CRITIQUE_FAILED = "critique.failed"
    
    # Optimization events
    OPTIMIZE_STARTED = "optimize.started"
    OPTIMIZE_COMPLETED = "optimize.completed"
    OPTIMIZE_FAILED = "optimize.failed"
    
    # Validation events
    VALIDATE_STARTED = "validate.started"
    VALIDATE_COMPLETED = "validate.completed"
    VALIDATE_FAILED = "validate.failed"
    
    # Convergence/early stopping
    CONVERGENCE_DETECTED = "convergence.detected"
    TARGET_REACHED = "target.reached"
    EARLY_STOP = "early_stop"
    
    # Resource/performance
    CACHE_HIT = "cache.hit"
    CACHE_MISS = "cache.miss"
    MEMORY_WARNING = "memory.warning"
    
    # Error classification
    ERROR_RETRYABLE = "error.retryable"
    ERROR_FATAL = "error.fatal"
    ERROR_TIMEOUT = "error.timeout"


ErrorLevel = Literal["debug", "info", "warning", "error", "critical"]


def _build_base_payload(
    event: EventType,
    session_id: Optional[str] = None,
    domain: Optional[str] = None,
    component: Optional[str] = None,
) -> Dict[str, Any]:
    """Build base payload with required fields."""
    payload = {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "event": event.value,
        "timestamp": time.time(),
    }
    
    if session_id:
        payload["session_id"] = session_id
    if domain:
        payload["domain"] = domain
    if component:
        payload["component"] = component
    
    return payload


def _safe_log(logger: logging.Logger, level: int, payload: Dict[str, Any]) -> None:
    """Safely emit JSON log with fallback for serialization errors."""
    try:
        logger.log(level, json.dumps(redact_payload(payload), default=str))
    except (TypeError, ValueError, RuntimeError) as exc:
        # Fallback: emit minimal error log
        logger.debug(
            "JSON serialization failed for event %s: %s",
            payload.get("event", "unknown"),
            exc,
        )


# ============================================================================
# Session-Level Events
# ============================================================================

def log_session_start(
    logger: logging.Logger,
    session_id: str,
    domain: str,
    input_size: Optional[int] = None,
    config: Optional[Dict[str, Any]] = None,
    component: Optional[str] = None,
) -> None:
    """Log session start event.
    
    Args:
        logger: Python logger
        session_id: Unique session identifier
        domain: Optimizer domain (code, logic, graph, text)
        input_size: Size of input data (tokens, lines, entities, etc.)
        config: Optimizer configuration dict
        component: Component name (e.g., "OntologyGenerator")
    """
    payload = _build_base_payload(
        EventType.SESSION_STARTED,
        session_id=session_id,
        domain=domain,
        component=component,
    )
    
    if input_size is not None:
        payload["input_size"] = input_size
    if config:
        payload["config"] = config
    
    _safe_log(logger, logging.INFO, payload)


def log_session_complete(
    logger: logging.Logger,
    session_id: str,
    domain: str,
    iterations: int,
    final_score: float,
    valid: bool,
    execution_time_ms: float,
    component: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> None:
    """Log session completion event.
    
    Args:
        logger: Python logger
        session_id: Unique session identifier
        domain: Optimizer domain
        iterations: Number of iterations completed
        final_score: Final quality score (0-1)
        valid: Whether final artifact is valid
        execution_time_ms: Total execution time in milliseconds
        component: Component name
        metrics: Additional metrics dict
    """
    payload = _build_base_payload(
        EventType.SESSION_COMPLETED,
        session_id=session_id,
        domain=domain,
        component=component,
    )
    
    payload.update({
        "iterations": iterations,
        "final_score": final_score,
        "valid": valid,
        "execution_time_ms": execution_time_ms,
    })
    
    if metrics:
        payload["metrics"] = metrics
    
    _safe_log(logger, logging.INFO, payload)


def log_session_failed(
    logger: logging.Logger,
    session_id: str,
    domain: str,
    error_type: str,
    error_msg: str,
    iteration: Optional[int] = None,
    component: Optional[str] = None,
) -> None:
    """Log session failure event.
    
    Args:
        logger: Python logger
        session_id: Unique session identifier
        domain: Optimizer domain
        error_type: Error classification (timeout, validation_failed, etc.)
        error_msg: Error message
        iteration: Iteration where failure occurred
        component: Component name
    """
    payload = _build_base_payload(
        EventType.SESSION_FAILED,
        session_id=session_id,
        domain=domain,
        component=component,
    )
    
    payload.update({
        "error_type": error_type,
        "error_msg": error_msg,
    })
    
    if iteration is not None:
        payload["iteration"] = iteration
    
    _safe_log(logger, logging.ERROR, payload)


# ============================================================================
# Iteration-Level Events
# ============================================================================

def log_iteration_started(
    logger: logging.Logger,
    session_id: str,
    iteration: int,
    current_score: float,
    feedback_count: int,
    component: Optional[str] = None,
) -> None:
    """Log iteration start event.
    
    Args:
        logger: Python logger
        session_id: Session ID
        iteration: 1-indexed iteration number
        current_score: Score from previous critique
        feedback_count: Number of feedback items
        component: Component name
    """
    payload = _build_base_payload(
        EventType.ITERATION_STARTED,
        session_id=session_id,
        component=component,
    )
    
    payload.update({
        "iteration": iteration,
        "current_score": current_score,
        "feedback_count": feedback_count,
    })
    
    _safe_log(logger, logging.DEBUG, payload)


def log_iteration_complete(
    logger: logging.Logger,
    session_id: str,
    iteration: int,
    score: float,
    score_delta: float,
    execution_time_ms: float,
    component: Optional[str] = None,
) -> None:
    """Log iteration completion event.
    
    Args:
        logger: Python logger
        session_id: Session ID
        iteration: 1-indexed iteration number
        score: New score after this iteration
        score_delta: Score improvement (score - previous_score)
        execution_time_ms: Iteration execution time in ms
        component: Component name
    """
    payload = _build_base_payload(
        EventType.ITERATION_COMPLETED,
        session_id=session_id,
        component=component,
    )
    
    payload.update({
        "iteration": iteration,
        "score": score,
        "score_delta": score_delta,
        "execution_time_ms": execution_time_ms,
    })
    
    _safe_log(logger, logging.INFO, payload)


# ============================================================================
# Pipeline Stage Events
# ============================================================================

def log_generate_complete(
    logger: logging.Logger,
    session_id: str,
    artifact_size: Optional[int] = None,
    execution_time_ms: Optional[float] = None,
    component: Optional[str] = None,
) -> None:
    """Log generation completion event.
    
    Args:
        logger: Python logger
        session_id: Session ID
        artifact_size: Size of generated artifact (entities, lines, tokens, etc.)
        execution_time_ms: Generation time in ms
        component: Component name
    """
    payload = _build_base_payload(
        EventType.GENERATE_COMPLETED,
        session_id=session_id,
        component=component,
    )
    
    if artifact_size is not None:
        payload["artifact_size"] = artifact_size
    if execution_time_ms is not None:
        payload["execution_time_ms"] = execution_time_ms
    
    _safe_log(logger, logging.INFO, payload)


def log_critique_complete(
    logger: logging.Logger,
    session_id: str,
    score: float,
    feedback_count: int,
    execution_time_ms: Optional[float] = None,
    component: Optional[str] = None,
) -> None:
    """Log critique completion event.
    
    Args:
        logger: Python logger
        session_id: Session ID
        score: Quality score (0-1)
        feedback_count: Number of feedback items
        execution_time_ms: Critique time in ms
        component: Component name
    """
    payload = _build_base_payload(
        EventType.CRITIQUE_COMPLETED,
        session_id=session_id,
        component=component,
    )
    
    payload.update({
        "score": score,
        "feedback_count": feedback_count,
    })
    
    if execution_time_ms is not None:
        payload["execution_time_ms"] = execution_time_ms
    
    _safe_log(logger, logging.INFO, payload)


def log_validate_complete(
    logger: logging.Logger,
    session_id: str,
    valid: bool,
    validation_details: Optional[str] = None,
    component: Optional[str] = None,
) -> None:
    """Log validation completion event.
    
    Args:
        logger: Python logger
        session_id: Session ID
        valid: Validation result
        validation_details: Optional details about why validation passed/failed
        component: Component name
    """
    payload = _build_base_payload(
        EventType.VALIDATE_COMPLETED,
        session_id=session_id,
        component=component,
    )
    
    payload["valid"] = valid
    
    if validation_details:
        payload["validation_details"] = validation_details
    
    level = logging.INFO if valid else logging.WARNING
    _safe_log(logger, level, payload)


# ============================================================================
# Convergence/Stopping Events
# ============================================================================

def log_convergence_detected(
    logger: logging.Logger,
    session_id: str,
    iteration: int,
    score: float,
    score_delta: float,
    threshold: float,
    component: Optional[str] = None,
) -> None:
    """Log convergence detection event.
    
    Args:
        logger: Python logger
        session_id: Session ID
        iteration: Iteration where convergence was detected
        score: Current score
        score_delta: Score improvement (fell below threshold)
        threshold: Convergence threshold that triggered stop
        component: Component name
    """
    payload = _build_base_payload(
        EventType.CONVERGENCE_DETECTED,
        session_id=session_id,
        component=component,
    )
    
    payload.update({
        "iteration": iteration,
        "score": score,
        "score_delta": score_delta,
        "threshold": threshold,
    })
    
    _safe_log(logger, logging.INFO, payload)


def log_target_reached(
    logger: logging.Logger,
    session_id: str,
    iteration: int,
    score: float,
    target: float,
    component: Optional[str] = None,
) -> None:
    """Log target score reached event.
    
    Args:
        logger: Python logger
        session_id: Session ID
        iteration: Iteration where target was reached
        score: Score that met/exceeded target
        target: Target score threshold
        component: Component name
    """
    payload = _build_base_payload(
        EventType.TARGET_REACHED,
        session_id=session_id,
        component=component,
    )
    
    payload.update({
        "iteration": iteration,
        "score": score,
        "target": target,
    })
    
    _safe_log(logger, logging.INFO, payload)


# ============================================================================
# Cache/Performance Events
# ============================================================================

def log_cache_hit(
    logger: logging.Logger,
    cache_key: str,
    hit_rate: Optional[float] = None,
    component: Optional[str] = None,
) -> None:
    """Log cache hit event.
    
    Args:
        logger: Python logger
        cache_key: Abbreviated cache key (first 12 chars)
        hit_rate: Current cache hit rate (0-1)
        component: Component name
    """
    payload = _build_base_payload(
        EventType.CACHE_HIT,
        component=component,
    )
    
    payload["cache_key"] = cache_key[:12]
    
    if hit_rate is not None:
        payload["hit_rate"] = hit_rate
    
    _safe_log(logger, logging.DEBUG, payload)


# ============================================================================
# Error Events
# ============================================================================

def log_error(
    logger: logging.Logger,
    error_type: str,
    error_msg: str,
    session_id: Optional[str] = None,
    iteration: Optional[int] = None,
    retryable: bool = False,
    component: Optional[str] = None,
    stack_trace: Optional[str] = None,
) -> None:
    """Log error event.
    
    Args:
        logger: Python logger
        error_type: Error classification (timeout, validation_failed, import_error, etc.)
        error_msg: Error message
        session_id: Optional session ID
        iteration: Optional iteration number
        retryable: Whether error is retryable
        component: Component name
        stack_trace: Optional stack trace
    """
    event = EventType.ERROR_RETRYABLE if retryable else EventType.ERROR_FATAL
    
    payload = _build_base_payload(
        event,
        session_id=session_id,
        component=component,
    )
    
    payload.update({
        "error_type": error_type,
        "error_msg": error_msg,
    })
    
    if iteration is not None:
        payload["iteration"] = iteration
    if stack_trace:
        payload["stack_trace"] = stack_trace
    
    level = logging.WARNING if retryable else logging.ERROR
    _safe_log(logger, level, payload)
