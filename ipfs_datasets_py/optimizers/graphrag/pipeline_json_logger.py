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
from typing import Any, Dict, List, Optional, Callable

from ipfs_datasets_py.optimizers.common.structured_logging import (
    EventType,
    with_schema,
    enrich_with_timestamp,
)


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
    metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    
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
        payload = {
            "event": event_type,
            "domain": self.domain,
            **data,
        }
        
        if self._context:
            payload["run_id"] = self._context.run_id
        
        if self.include_timestamp:
            payload = enrich_with_timestamp(payload)
        
        if self.include_schema:
            payload = with_schema(payload)
        
        try:
            self.logger.log(level, json.dumps(payload, default=str))
        except Exception as exc:
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
        if self._context:
            self._context.mark_stage_end("extraction")
            self._context.metrics["entity_count"] = entity_count
            self._context.metrics["relationship_count"] = relationship_count
        
        data = {
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
        if self._context:
            self._context.mark_stage_end("evaluation")
            self._context.metrics["overall_score"] = score
        
        data = {
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
    except Exception as exc:
        logger.end_run(success=False, error=str(exc))
        raise
