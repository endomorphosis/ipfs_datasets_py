"""Helpers for structured JSON logs.

This module provides a small, stable envelope for structured log payloads so that
downstream parsers can reliably identify and version log schemas.

Example:
    >>> from ipfs_datasets_py.optimizers.common.structured_logging import (
    ...     with_schema, log_event, EventType
    ... )
    >>> import logging
    >>> 
    >>> logger = logging.getLogger(__name__)
    >>> log_event(logger, EventType.EXTRACTION_STARTED, {"input_length": 1234})
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Dict, Mapping, Optional

DEFAULT_SCHEMA = "ipfs_datasets_py.optimizer_log"
DEFAULT_SCHEMA_VERSION = 2  # Bumped from 1 to 2 for new event/timestamp fields


class EventType(Enum):
    """Standard event types for optimizer structured logs."""
    
    # Pipeline events
    PIPELINE_RUN_STARTED = "pipeline.run.started"
    PIPELINE_RUN_COMPLETED = "pipeline.run.completed"
    PIPELINE_RUN_FAILED = "pipeline.run.failed"
    PIPELINE_BATCH_STARTED = "pipeline.batch.started"
    PIPELINE_BATCH_COMPLETED = "pipeline.batch.completed"
    
    # Extraction events
    EXTRACTION_STARTED = "extraction.started"
    EXTRACTION_COMPLETED = "extraction.completed"
    EXTRACTION_FAILED = "extraction.failed"
    
    # Critic events
    CRITIC_SCORE_STARTED = "critic.score.started"
    CRITIC_SCORE_COMPLETED = "critic.score.completed"
    CRITIC_SCORE_FAILED = "critic.score.failed"
    
    # Mediator/refinement events
    REFINEMENT_ROUND_STARTED = "refinement.round.started"
    REFINEMENT_ROUND_COMPLETED = "refinement.round.completed"
    REFINEMENT_CONVERGED = "refinement.converged"
    REFINEMENT_FAILED = "refinement.failed"
    
    # Validator events
    VALIDATION_STARTED = "validation.started"
    VALIDATION_COMPLETED = "validation.completed"
    VALIDATION_FAILED = "validation.failed"
    
    # Logic optimizer events
    LOGIC_SESSION_STARTED = "logic.session.started"
    LOGIC_SESSION_COMPLETED = "logic.session.completed"
    LOGIC_SESSION_FAILED = "logic.session.failed"
    PROOF_ATTEMPT_STARTED = "logic.proof.attempt.started"
    PROOF_ATTEMPT_COMPLETED = "logic.proof.attempt.completed"
    
    # Generic events
    OPTIMIZER_STARTED = "optimizer.started"
    OPTIMIZER_COMPLETED = "optimizer.completed"
    OPTIMIZER_FAILED = "optimizer.failed"


def with_schema(
    payload: Mapping[str, Any],
    *,
    schema: str = DEFAULT_SCHEMA,
    schema_version: int = DEFAULT_SCHEMA_VERSION,
) -> Dict[str, Any]:
    """Return a dict payload enriched with schema metadata.

    If the payload already contains a ``schema`` or ``schema_version`` key, its
    value is preserved.

    Args:
        payload: Log payload dictionary
        schema: Schema identifier (default: ipfs_datasets_py.optimizer_log)
        schema_version: Schema version integer (default: 2)

    Returns:
        Dict with schema metadata added
    """

    result: Dict[str, Any] = dict(payload)

    result.setdefault("schema", schema)
    result.setdefault("schema_version", schema_version)

    return result


def enrich_with_timestamp(
    payload: Mapping[str, Any],
    *,
    timestamp_key: str = "timestamp",
) -> Dict[str, Any]:
    """Enrich payload with current Unix timestamp.

    Args:
        payload: Log payload dictionary
        timestamp_key: Key to use for timestamp (default: "timestamp")

    Returns:
        Dict with timestamp added if not already present
    """
    result: Dict[str, Any] = dict(payload)
    result.setdefault(timestamp_key, time.time())
    return result


def log_event(
    logger: logging.Logger,
    event: EventType,
    data: Optional[Dict[str, Any]] = None,
    *,
    level: int = logging.INFO,
    include_schema: bool = True,
    include_timestamp: bool = True,
) -> None:
    """Log a structured event with standard schema envelope.

    Args:
        logger: Python logger instance
        event: Event type from EventType enum
        data: Optional additional event data
        level: Log level (default: INFO)
        include_schema: Whether to add schema metadata (default: True)
        include_timestamp: Whether to add timestamp (default: True)

    Example:
        >>> log_event(logger, EventType.EXTRACTION_STARTED, {"entities": 5})
    """
    import json
    
    payload = {"event": event.value}
    
    if data:
        payload.update(data)
    
    if include_timestamp:
        payload = enrich_with_timestamp(payload)
    
    if include_schema:
        payload = with_schema(payload)
    
    try:
        logger.log(level, json.dumps(payload, default=str))
    except Exception as exc:
        # Fallback to simple logging if JSON serialization fails
        logger.debug(f"Structured logging failed for {event.value}: {exc}")

