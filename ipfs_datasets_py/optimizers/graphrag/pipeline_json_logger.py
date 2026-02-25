"""Comprehensive JSON logging for GraphRAG pipeline runs.

This module provides structured JSON logging for all stages of ontology generation,
evaluation, refinement, and learning adaptation. Logs are formatted for easy parsing
by log aggregation systems (ELK, Splunk, etc.) and include performance metrics,
error tracking, and workflow state.

Features:
    - Full pipeline lifecycle tracking
    - Per-stage timing and metrics
    - Error and exception logging
    - Cache statistics
    - Dependency tracking
    - Performance profiling

Usage:
    >>> from ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger import (
    ...     PipelineJSONLogger,
    ...     start_pipeline_run,
    ... )
    >>> 
    >>> logger = PipelineJSONLogger(domain="legal")
    >>> with start_pipeline_run(logger, data_source="test"):
    ...     # Run pipeline stages
    ...     logger.log_extraction_started(entity_count=10)
    ...     logger.log_extraction_completed(entity_count=10, relationship_count=5)
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, TypedDict, cast

from ipfs_datasets_py.optimizers.common.structured_logging import (
    EventType,
    redact_payload,
    with_schema,
    enrich_with_timestamp,
)


class PipelineErrorDict(TypedDict, total=False):
    """Structure for pipeline error entries.
    
    Fields:
        stage: Pipeline stage where error occurred
        type: Error type (exception class name)
        message: Human-readable error message
    """
    stage: str
    type: str
    message: str


class PipelineMetricsDict(TypedDict, total=False):
    """Structure for pipeline execution metrics.
    
    Fields:
        entity_count: Number of entities extracted
        relationship_count: Number of relationships extracted
        overall_score: Overall quality/confidence score (0-1)
    """
    entity_count: int
    relationship_count: int
    overall_score: float


class PipelineStage(Enum):
    """Distinct stages of ontology pipeline execution."""
    
    EXTRACTION = "extraction"
    EVALUATION = "evaluation"
    REFINEMENT = "refinement"
    ADAPTATION = "adaptation"
    SERIALIZATION = "serialization"


@dataclass
class LogContext:
    """Context for a pipeline run session."""
    
    run_id: str
    domain: str
    data_source: str
    data_type: str = "text"
    refine: bool = True
    max_workers: int = 1
    timestamp_started: float = field(default_factory=time.time)
    stages: Dict[str, float] = field(default_factory=dict)
    stage_timings: Dict[str, float] = field(default_factory=dict)
    metrics: PipelineMetricsDict = field(default_factory=lambda: cast(PipelineMetricsDict, {}))
    errors: List[PipelineErrorDict] = field(default_factory=list)
    
    def elapsed_ms(self) -> float:
        """Get elapsed time since run start in milliseconds."""
        return (time.time() - self.timestamp_started) * 1000.0
    
    def mark_stage_start(self, stage: str) -> None:
        """Mark the start of a pipeline stage."""
        self.stages[stage] = time.time()
    
    def mark_stage_end(self, stage: str) -> None:
        """Mark the end of a pipeline stage and record timing."""
        if stage in self.stages:
            duration_ms = (time.time() - self.stages[stage]) * 1000.0
            self.stage_timings[stage] = duration_ms
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dict for logging."""
        return {
            "run_id": self.run_id,
            "domain": self.domain,
            "data_source": self.data_source,
            "data_type": self.data_type,
            "refine": self.refine,
            "max_workers": self.max_workers,
            "total_elapsed_ms": self.elapsed_ms(),
            "stage_timings": self.stage_timings,
            "metrics": self.metrics,
            "error_count": len(self.errors),
        }


class PipelineJSONLogger:
    """Structured JSON logger for ontology pipeline runs.
    
    Tracks all stages of a pipeline execution and emits JSON-formatted logs
    suitable for log aggregation systems.
    """
    
    def __init__(
        self,
        domain: str,
        logger: Optional[logging.Logger] = None,
        include_schema: bool = True,
        include_timestamp: bool = True,
    ):
        """Initialize the pipeline JSON logger.
        
        Args:
            domain: Ontology domain (e.g., "legal", "medical")
            logger: Python logger instance (default: module logger)
            include_schema: Whether to add schema metadata to logs
            include_timestamp: Whether to add timestamp to logs
        """
        self.domain = domain
        self.logger = logger or logging.getLogger(__name__)
        self.include_schema = include_schema
        self.include_timestamp = include_timestamp
        self._context: Optional[LogContext] = None
    
    def _emit_log(
        self,
        event_type: str,
        data: Dict[str, Any],
        level: int = logging.INFO,
    ) -> None:
        """Emit a structured JSON log entry.
        
        Args:
            event_type: Event type string
            data: Event data
            level: Logging level
        """
        status = data.get("status")
        if not isinstance(status, str) or not status.strip():
            if event_type.endswith(".started"):
                status = "started"
            elif event_type.endswith(".completed"):
                status = "completed"
            elif event_type.endswith(".failed"):
                status = "failed"
            else:
                status = "info"

        payload = {
            "timestamp": f"{datetime.utcnow().isoformat()}Z",
            "level": str(logging.getLevelName(level)),
            "message": event_type,
            "event": event_type,
            "module": __name__,
            "component": "pipeline_json_logger",
            "optimizer_type": "graphrag",
            "domain": self.domain,
            "optimizer_pipeline": "graphrag",
            "status": status,
            **data,
        }
        
        if self._context:
            payload["run_id"] = self._context.run_id

        payload = redact_payload(payload)
        
        if self.include_timestamp:
            payload = enrich_with_timestamp(payload)
        
        if self.include_schema:
            payload = with_schema(payload)
        
        try:
            self.logger.log(level, json.dumps(payload, default=str))
        except (TypeError, ValueError, RuntimeError, OSError) as exc:
            self.logger.debug(f"JSON logging failed: {exc}")
    
    def start_run(
        self,
        run_id: str,
        data_source: str,
        data_type: str = "text",
        refine: bool = True,
        max_workers: int = 1,
    ) -> LogContext:
        """Start a new pipeline run and return context.
        
        Args:
            run_id: Unique identifier for this run
            data_source: Source of the input data
            data_type: Type of data ("text", "json", etc.)
            refine: Whether refinement will be performed
            max_workers: Number of parallel workers
            
        Returns:
            LogContext for the run
        """
        if not isinstance(run_id, str):
            raise TypeError("run_id must be a string")
        if not run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        if not isinstance(data_source, str):
            raise TypeError("data_source must be a string")
        if not data_source.strip():
            raise ValueError("data_source must be a non-empty string")
        if not isinstance(data_type, str):
            raise TypeError("data_type must be a string")
        if not data_type.strip():
            raise ValueError("data_type must be a non-empty string")
        if not isinstance(refine, bool):
            raise TypeError("refine must be a bool")
        if not isinstance(max_workers, int):
            raise TypeError("max_workers must be an int")
        if max_workers <= 0:
            raise ValueError("max_workers must be greater than 0")

        self._context = LogContext(
            run_id=run_id,
            domain=self.domain,
            data_source=data_source,
            data_type=data_type,
            refine=refine,
            max_workers=max_workers,
        )
        
        self._emit_log(
            "pipeline.run.started",
            {
                "run_id": run_id,
                "data_source": data_source,
                "data_type": data_type,
                "refine": refine,
                "max_workers": max_workers,
            },
        )
        
        return self._context
    
    def end_run(self, success: bool = True, error: Optional[str] = None) -> Dict[str, Any]:
        """End the current pipeline run.
        
        Args:
            success: Whether the run completed successfully
            error: Error message if failed
            
        Returns:
            Summary dict of the run
        """
        if not self._context:
            return {}
        
        context = self._context
        summary = context.to_dict()
        
        event_type = "pipeline.run.completed" if success else "pipeline.run.failed"
        data = {
            "run_id": context.run_id,
            "success": success,
            **summary,
        }
        
        if error:
            data["error"] = error
        
        self._emit_log(event_type, data)
        self._context = None
        
        return summary
    
    def log_extraction_started(
        self,
        data_length: int,
        strategy: str = "rule_based",
    ) -> None:
        """Log the start of entity/relationship extraction.
        
        Args:
            data_length: Length of input data in characters
            strategy: Extraction strategy being used
        """
        if not isinstance(data_length, int):
            raise TypeError("data_length must be an int")
        if data_length < 0:
            raise ValueError("data_length must be greater than or equal to 0")
        if not isinstance(strategy, str):
            raise TypeError("strategy must be a string")
        if not strategy.strip():
            raise ValueError("strategy must be a non-empty string")

        if self._context:
            self._context.mark_stage_start("extraction")
        
        self._emit_log(
            "extraction.started",
            {
                "data_length": data_length,
                "strategy": strategy,
            },
        )
    
    def log_extraction_completed(
        self,
        entity_count: int,
        relationship_count: int,
        entity_types: Optional[Dict[str, int]] = None,
    ) -> None:
        """Log the completion of extraction.
        
        Args:
            entity_count: Number of entities extracted
            relationship_count: Number of relationships extracted
            entity_types: Count of entities by type
        """
        if not isinstance(entity_count, int):
            raise TypeError("entity_count must be an int")
        if not isinstance(relationship_count, int):
            raise TypeError("relationship_count must be an int")
        if entity_count < 0:
            raise ValueError("entity_count must be greater than or equal to 0")
        if relationship_count < 0:
            raise ValueError("relationship_count must be greater than or equal to 0")
        if entity_types is not None:
            if not isinstance(entity_types, dict):
                raise TypeError("entity_types must be a dict")
            if not all(isinstance(k, str) for k in entity_types):
                raise TypeError("entity_types keys must be strings")
            if not all(isinstance(v, int) for v in entity_types.values()):
                raise TypeError("entity_types values must be ints")
            if any(v < 0 for v in entity_types.values()):
                raise ValueError("entity_types values must be greater than or equal to 0")

        if self._context:
            self._context.mark_stage_end("extraction")
            self._context.metrics["entity_count"] = entity_count
            self._context.metrics["relationship_count"] = relationship_count
        
        data: Dict[str, Any] = {
            "entity_count": entity_count,
            "relationship_count": relationship_count,
        }
        
        if entity_types:
            data["entity_types"] = entity_types
        
        self._emit_log("extraction.completed", data)
    
    def log_evaluation_started(
        self,
        parallel: bool = False,
        batch_size: int = 1,
    ) -> None:
        """Log the start of ontology evaluation.
        
        Args:
            parallel: Whether parallel evaluation is being used
            batch_size: Size of batch being evaluated
        """
        if not isinstance(parallel, bool):
            raise TypeError("parallel must be a bool")
        if not isinstance(batch_size, int):
            raise TypeError("batch_size must be an int")
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than 0")

        if self._context:
            self._context.mark_stage_start("evaluation")
        
        self._emit_log(
            "evaluation.started",
            {
                "parallel": parallel,
                "batch_size": batch_size,
            },
        )
    
    def log_evaluation_completed(
        self,
        score: float,
        dimensions: Optional[Dict[str, float]] = None,
        cache_hit: bool = False,
        cache_size: int = 0,
    ) -> None:
        """Log the completion of evaluation.
        
        Args:
            score: Overall ontology score
            dimensions: Individual dimension scores
            cache_hit: Whether result came from cache
            cache_size: Size of evaluation cache
        """
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise TypeError("score must be a number")
        if dimensions is not None:
            if not isinstance(dimensions, dict):
                raise TypeError("dimensions must be a dict")
            if not all(isinstance(k, str) for k in dimensions):
                raise TypeError("dimensions keys must be strings")
            if not all((not isinstance(v, bool)) and isinstance(v, (int, float)) for v in dimensions.values()):
                raise TypeError("dimensions values must be numbers")
        if not isinstance(cache_hit, bool):
            raise TypeError("cache_hit must be a bool")
        if not isinstance(cache_size, int):
            raise TypeError("cache_size must be an int")
        if cache_size < 0:
            raise ValueError("cache_size must be greater than or equal to 0")

        if self._context:
            self._context.mark_stage_end("evaluation")
            self._context.metrics["overall_score"] = score
        
        data: Dict[str, Any] = {
            "score": score,
            "cache_hit": cache_hit,
            "cache_size": cache_size,
        }
        
        if dimensions:
            data["dimensions"] = dimensions
        
        self._emit_log("evaluation.completed", data)
    
    def log_refinement_started(
        self,
        mode: str = "rule_based",
        max_rounds: int = 1,
        current_score: float = 0.0,
    ) -> None:
        """Log the start of refinement cycle.
        
        Args:
            mode: Refinement mode (rule_based, llm, agentic)
            max_rounds: Maximum refinement rounds
            current_score: Current ontology score
        """
        if not isinstance(mode, str):
            raise TypeError("mode must be a string")
        if not mode.strip():
            raise ValueError("mode must be a non-empty string")
        if not isinstance(max_rounds, int):
            raise TypeError("max_rounds must be an int")
        if max_rounds <= 0:
            raise ValueError("max_rounds must be greater than 0")
        if isinstance(current_score, bool) or not isinstance(current_score, (int, float)):
            raise TypeError("current_score must be a number")

        if self._context:
            self._context.mark_stage_start("refinement")
        
        self._emit_log(
            "refinement.started",
            {
                "mode": mode,
                "max_rounds": max_rounds,
                "current_score": current_score,
            },
        )
    
    def log_refinement_round(
        self,
        round_num: int,
        max_rounds: int,
        score_before: float,
        score_after: float,
        actions_applied: List[str],
    ) -> None:
        """Log a single refinement round.
        
        Args:
            round_num: Current round number (1-indexed)
            max_rounds: Total rounds planned
            score_before: Ontology score before refinement
            score_after: Ontology score after refinement
            actions_applied: List of refinement actions applied
        """
        if not isinstance(round_num, int):
            raise TypeError("round_num must be an int")
        if not isinstance(max_rounds, int):
            raise TypeError("max_rounds must be an int")
        if max_rounds <= 0:
            raise ValueError("max_rounds must be greater than 0")
        if round_num < 1:
            raise ValueError("round_num must be at least 1")
        if round_num > max_rounds:
            raise ValueError("round_num must be less than or equal to max_rounds")
        if isinstance(score_before, bool) or not isinstance(score_before, (int, float)):
            raise TypeError("score_before must be a number")
        if isinstance(score_after, bool) or not isinstance(score_after, (int, float)):
            raise TypeError("score_after must be a number")
        if not isinstance(actions_applied, list):
            raise TypeError("actions_applied must be a list")
        if not all(isinstance(action, str) for action in actions_applied):
            raise TypeError("actions_applied must contain only strings")

        improvement = score_after - score_before
        
        self._emit_log(
            "refinement.round.completed",
            {
                "round": round_num,
                "max_rounds": max_rounds,
                "score_before": score_before,
                "score_after": score_after,
                "improvement": improvement,
                "actions": actions_applied,
                "action_count": len(actions_applied),
            },
        )
    
    def log_refinement_completed(
        self,
        final_score: float,
        initial_score: float,
        rounds_completed: int,
        total_actions: int,
    ) -> None:
        """Log the completion of refinement.
        
        Args:
            final_score: Final ontology score
            initial_score: Initial ontology score
            rounds_completed: Number of rounds completed
            total_actions: Total refinement actions applied
        """
        if isinstance(final_score, bool) or not isinstance(final_score, (int, float)):
            raise TypeError("final_score must be a number")
        if isinstance(initial_score, bool) or not isinstance(initial_score, (int, float)):
            raise TypeError("initial_score must be a number")
        if not isinstance(rounds_completed, int):
            raise TypeError("rounds_completed must be an int")
        if not isinstance(total_actions, int):
            raise TypeError("total_actions must be an int")
        if rounds_completed < 0:
            raise ValueError("rounds_completed must be greater than or equal to 0")
        if total_actions < 0:
            raise ValueError("total_actions must be greater than or equal to 0")

        if self._context:
            self._context.mark_stage_end("refinement")
        
        improvement = final_score - initial_score
        
        self._emit_log(
            "refinement.completed",
            {
                "final_score": final_score,
                "initial_score": initial_score,
                "improvement": improvement,
                "rounds": rounds_completed,
                "total_actions": total_actions,
            },
        )
    
    def log_error(
        self,
        stage: str,
        error_type: str,
        error_message: str,
        traceback: Optional[str] = None,
    ) -> None:
        """Log an error during pipeline execution.
        
        Args:
            stage: Stage where error occurred
            error_type: Type of error (e.g., exception class name)
            error_message: Error message
            traceback: Optional stack trace
        """
        if self._context:
            self._context.errors.append({
                "stage": stage,
                "type": error_type,
                "message": error_message,
            })
        
        data = {
            "stage": stage,
            "error_type": error_type,
            "error_message": error_message,
        }
        
        if traceback:
            data["traceback"] = traceback
        
        self._emit_log("pipeline.error", data, level=logging.ERROR)
    
    def log_cache_statistics(
        self,
        cache_type: str,
        size: int,
        hit_count: int,
        miss_count: int,
        eviction_count: int = 0,
    ) -> None:
        """Log cache statistics.
        
        Args:
            cache_type: Type of cache (shared_eval, local_eval, etc.)
            size: Current cache size
            hit_count: Total cache hits
            miss_count: Total cache misses
            eviction_count: Total cache evictions
        """
        if not isinstance(cache_type, str):
            raise TypeError("cache_type must be a string")
        if not cache_type.strip():
            raise ValueError("cache_type must be a non-empty string")
        if not isinstance(size, int):
            raise TypeError("size must be an int")
        if not isinstance(hit_count, int):
            raise TypeError("hit_count must be an int")
        if not isinstance(miss_count, int):
            raise TypeError("miss_count must be an int")
        if not isinstance(eviction_count, int):
            raise TypeError("eviction_count must be an int")
        if size < 0:
            raise ValueError("size must be greater than or equal to 0")
        if hit_count < 0:
            raise ValueError("hit_count must be greater than or equal to 0")
        if miss_count < 0:
            raise ValueError("miss_count must be greater than or equal to 0")
        if eviction_count < 0:
            raise ValueError("eviction_count must be greater than or equal to 0")

        hit_rate = hit_count / (hit_count + miss_count) if (hit_count + miss_count) > 0 else 0.0
        
        self._emit_log(
            "cache.statistics",
            {
                "cache_type": cache_type,
                "size": size,
                "hit_count": hit_count,
                "miss_count": miss_count,
                "hit_rate": hit_rate,
                "eviction_count": eviction_count,
            },
        )
    
    def log_batch_progress(
        self,
        batch_index: int,
        batch_total: int,
        items_completed: int,
        items_failed: int,
        current_score: float,
    ) -> None:
        """Log progress on batch processing.
        
        Args:
            batch_index: Current batch index (0-indexed)
            batch_total: Total number of batches
            items_completed: Number of items completed
            items_failed: Number of items that failed
            current_score: Current batch average score
        """
        if not isinstance(batch_index, int):
            raise TypeError("batch_index must be an int")
        if not isinstance(batch_total, int):
            raise TypeError("batch_total must be an int")
        if not isinstance(items_completed, int):
            raise TypeError("items_completed must be an int")
        if not isinstance(items_failed, int):
            raise TypeError("items_failed must be an int")
        if isinstance(current_score, bool) or not isinstance(current_score, (int, float)):
            raise TypeError("current_score must be a number")
        if batch_index < 0:
            raise ValueError("batch_index must be greater than or equal to 0")
        if batch_total <= 0:
            raise ValueError("batch_total must be greater than 0")
        if batch_index > batch_total:
            raise ValueError("batch_index must be less than or equal to batch_total")
        if items_completed < 0:
            raise ValueError("items_completed must be greater than or equal to 0")
        if items_failed < 0:
            raise ValueError("items_failed must be greater than or equal to 0")

        progress_pct = (batch_index / batch_total * 100) if batch_total > 0 else 0.0
        
        self._emit_log(
            "batch.progress",
            {
                "batch": batch_index,
                "total_batches": batch_total,
                "progress_percent": progress_pct,
                "items_completed": items_completed,
                "items_failed": items_failed,
                "current_score": current_score,
            },
        )


@contextmanager
def start_pipeline_run(
    logger: PipelineJSONLogger,
    run_id: str,
    data_source: str = "pipeline",
    data_type: str = "text",
    refine: bool = True,
) -> Any:
    """Context manager for a complete pipeline run.
    
    Args:
        logger: PipelineJSONLogger instance
        run_id: Unique run identifier
        data_source: Source of input data
        data_type: Type of data
        refine: Whether refinement will run
        
    Yields:
        LogContext for the run
        
    Example:
        >>> logger = PipelineJSONLogger(domain="legal")
        >>> with start_pipeline_run(logger, "run_123") as ctx:
        ...     logger.log_extraction_started(1000)
        ...     # ... do work ...
        ...     logger.log_extraction_completed(10, 5)
    """
    context = logger.start_run(
        run_id=run_id,
        data_source=data_source,
        data_type=data_type,
        refine=refine,
    )
    
    try:
        yield context
        logger.end_run(success=True)
    except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as exc:
        logger.end_run(success=False, error=str(exc))
        raise
