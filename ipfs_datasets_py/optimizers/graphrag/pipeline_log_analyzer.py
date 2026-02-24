"""Log aggregation and analysis utilities for GraphRAG pipeline runs.

This module provides utilities to parse, aggregate, and analyze structured
JSON logs produced by PipelineJSONLogger. Supports log file parsing,
real-time aggregation, and generating performance reports.

Features:
    - Parse JSON log files
    - Aggregate logs by pipeline stage
    - Calculate performance statistics
    - Generate reports and visualizations
    - Filter logs by criteria
    - Export analysis results

Usage:
    >>> from ipfs_datasets_py.optimizers.graphrag.pipeline_log_analyzer import (
    ...     LogAnalyzer,
    ...     load_log_file,
    ... )
    >>> 
    >>> logs = load_log_file("pipeline.log")
    >>> analyzer = LogAnalyzer(logs)
    >>> stats = analyzer.stage_statistics()
    >>> print(stats)
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class StageStatistics:
    """Statistics for a single pipeline stage."""
    
    stage_name: str
    event_count: int = 0
    total_duration_ms: float = 0.0
    min_duration_ms: float = float('inf')
    max_duration_ms: float = 0.0
    error_count: int = 0
    
    @property
    def avg_duration_ms(self) -> float:
        """Calculate average duration."""
        return self.total_duration_ms / self.event_count if self.event_count > 0 else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "stage": self.stage_name,
            "event_count": self.event_count,
            "total_duration_ms": self.total_duration_ms,
            "avg_duration_ms": self.avg_duration_ms,
            "min_duration_ms": self.min_duration_ms,
            "max_duration_ms": self.max_duration_ms,
            "error_count": self.error_count,
        }


@dataclass
class RunStatistics:
    """Statistics for a complete pipeline run."""
    
    run_id: str
    domain: str
    data_source: str
    timestamp: Optional[datetime] = None
    total_duration_ms: float = 0.0
    entity_count: int = 0
    relationship_count: int = 0
    overall_score: float = 0.0
    error_count: int = 0
    refinement_rounds: int = 0
    stage_stats: Dict[str, StageStatistics] = None
    
    def __post_init__(self):
        if self.stage_stats is None:
            self.stage_stats = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "run_id": self.run_id,
            "domain": self.domain,
            "data_source": self.data_source,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "total_duration_ms": self.total_duration_ms,
            "entity_count": self.entity_count,
            "relationship_count": self.relationship_count,
            "overall_score": self.overall_score,
            "error_count": self.error_count,
            "refinement_rounds": self.refinement_rounds,
            "stages": {name: stats.to_dict() for name, stats in self.stage_stats.items()},
        }


class LogAnalyzer:
    """Analyze structured JSON logs from pipeline runs."""
    
    def __init__(self, logs: List[Dict[str, Any]]):
        """Initialize analyzer with logs.
        
        Args:
            logs: List of parsed JSON log dictionaries
        """
        self.logs = logs
        self._runs: Dict[str, RunStatistics] = {}
        self._parse_logs()
    
    def _parse_logs(self) -> None:
        """Parse logs and extract run statistics."""
        current_run: Optional[RunStatistics] = None
        extraction_duration: float = 0.0
        evaluation_duration: float = 0.0
        refinement_start_score: float = 0.0
        refinement_end_score: float = 0.0
        refinement_round_count: int = 0
        
        for log in self.logs:
            event = log.get("event")
            run_id = log.get("run_id")
            
            if not run_id:
                continue
            
            # Create or retrieve run statistics
            if run_id not in self._runs:
                current_run = RunStatistics(
                    run_id=run_id,
                    domain=log.get("domain", "unknown"),
                    data_source=log.get("data_source", "unknown"),
                )
                self._runs[run_id] = current_run
            else:
                current_run = self._runs[run_id]
            
            # Parse timestamps for duration calculation
            if "timestamp" in log:
                try:
                    timestamp = datetime.fromisoformat(log["timestamp"])
                    if current_run.timestamp is None:
                        current_run.timestamp = timestamp
                except (ValueError, TypeError):
                    pass
            
            # Process event-specific fields
            if event == "pipeline.run.started":
                current_run.total_duration_ms = 0.0
            
            elif event == "pipeline.run.completed":
                current_run.total_duration_ms = log.get("total_elapsed_ms", 0.0)
                current_run.entity_count = log.get("metrics", {}).get("entity_count", 0)
                current_run.error_count = log.get("error_count", 0)
            
            elif event == "extraction.completed":
                current_run.entity_count = log.get("entity_count", 0)
                current_run.relationship_count = log.get("relationship_count", 0)
            
            elif event == "evaluation.completed":
                current_run.overall_score = log.get("score", 0.0)
            
            elif event == "refinement.started":
                refinement_start_score = log.get("current_score", 0.0)
                refinement_round_count = 0
            
            elif event == "refinement.round.completed":
                refinement_round_count += 1
                refinement_end_score = log.get("score_after", 0.0)
            
            elif event == "refinement.completed":
                current_run.refinement_rounds = log.get("rounds", 0)
            
            elif event == "pipeline.error":
                current_run.error_count += 1
    
    def stage_statistics(self) -> Dict[str, StageStatistics]:
        """Get statistics aggregated by pipeline stage.
        
        Returns:
            Dictionary mapping stage names to StageStatistics
        """
        stage_stats: Dict[str, StageStatistics] = defaultdict(
            lambda: StageStatistics("")
        )
        
        stage_events: Dict[str, float] = defaultdict(float)
        stage_counts: Dict[str, int] = defaultdict(int)
        stage_errors: Dict[str, int] = defaultdict(int)
        stage_durations: Dict[str, Tuple[float, float, float]] = defaultdict(
            lambda: (float('inf'), 0.0, 0.0)
        )
        
        for log in self.logs:
            event = log.get("event", "")
            
            # Extract stage from event (e.g., "extraction.completed" -> "extraction")
            if "." not in event:
                continue
            
            stage = event.split(".")[0]
            
            # Track events and errors
            stage_counts[stage] += 1
            
            if "error" in event:
                stage_errors[stage] += 1
            
            # Track durations for completed events
            if "completed" in event or "round.completed" in event:
                # Try to extract timing information from log
                if "total_elapsed_ms" in log:
                    duration = log["total_elapsed_ms"]
                    min_d, max_d, total = stage_durations[stage]
                    stage_durations[stage] = (
                        min(min_d, duration),
                        max(max_d, duration),
                        total + duration,
                    )
        
        # Build statistics
        for stage, count in stage_counts.items():
            min_d, max_d, total = stage_durations.get(stage, (0.0, 0.0, 0.0))
            
            stats = StageStatistics(
                stage_name=stage,
                event_count=count,
                total_duration_ms=total if total > 0 else 0.0,
                min_duration_ms=min_d if min_d < float('inf') else 0.0,
                max_duration_ms=max_d,
                error_count=stage_errors.get(stage, 0),
            )
            stage_stats[stage] = stats
        
        return dict(stage_stats)
    
    def run_statistics(self) -> Dict[str, RunStatistics]:
        """Get statistics for each run.
        
        Returns:
            Dictionary mapping run IDs to RunStatistics
        """
        return self._runs.copy()
    
    def filter_logs(
        self,
        run_id: Optional[str] = None,
        event_type: Optional[str] = None,
        minimum_timestamp: Optional[datetime] = None,
        maximum_timestamp: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Filter logs by criteria.
        
        Args:
            run_id: Filter by run ID
            event_type: Filter by event type
            minimum_timestamp: Filter by minimum timestamp
            maximum_timestamp: Filter by maximum timestamp
            
        Returns:
            Filtered list of logs
        """
        filtered = self.logs
        
        if run_id:
            filtered = [l for l in filtered if l.get("run_id") == run_id]
        
        if event_type:
            filtered = [l for l in filtered if l.get("event") == event_type]
        
        if minimum_timestamp or maximum_timestamp:
            def in_range(log: Dict[str, Any]) -> bool:
                ts_str = log.get("timestamp")
                if not ts_str:
                    return True
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if minimum_timestamp and ts < minimum_timestamp:
                        return False
                    if maximum_timestamp and ts > maximum_timestamp:
                        return False
                    return True
                except (ValueError, TypeError):
                    return True
            
            filtered = [l for l in filtered if in_range(l)]
        
        return filtered
    
    def error_summary(self) -> Dict[str, Any]:
        """Get summary of all errors in logs.
        
        Returns:
            Dictionary with error summary
        """
        errors_by_stage: Dict[str, List[str]] = defaultdict(list)
        total_errors = 0
        
        for log in self.logs:
            if log.get("event") == "pipeline.error":
                stage = log.get("stage", "unknown")
                error_msg = log.get("error_message", "No message")
                errors_by_stage[stage].append(error_msg)
                total_errors += 1
        
        return {
            "total_errors": total_errors,
            "errors_by_stage": dict(errors_by_stage),
        }
    
    def performance_summary(self) -> Dict[str, Any]:
        """Get performance summary across all runs.
        
        Returns:
            Dictionary with performance metrics
        """
        runs = self.run_statistics()
        
        if not runs:
            return {}
        
        durations = [r.total_duration_ms for r in runs.values()]
        scores = [r.overall_score for r in runs.values() if r.overall_score > 0]
        
        return {
            "total_runs": len(runs),
            "avg_duration_ms": sum(durations) / len(durations) if durations else 0.0,
            "min_duration_ms": min(durations) if durations else 0.0,
            "max_duration_ms": max(durations) if durations else 0.0,
            "avg_score": sum(scores) / len(scores) if scores else 0.0,
            "min_score": min(scores) if scores else 0.0,
            "max_score": max(scores) if scores else 0.0,
            "total_errors": sum(r.error_count for r in runs.values()),
        }
    
    def export_report(self, format: str = "json") -> str:
        """Export analysis report.
        
        Args:
            format: Export format ("json" or "csv")
            
        Returns:
            Formatted report string
            
        Raises:
            ValueError: If unsupported format requested
        """
        if format == "json":
            report = {
                "runs": {
                    run_id: stats.to_dict()
                    for run_id, stats in self.run_statistics().items()
                },
                "stages": {
                    stage: stats.to_dict()
                    for stage, stats in self.stage_statistics().items()
                },
                "performance_summary": self.performance_summary(),
                "error_summary": self.error_summary(),
            }
            return json.dumps(report, indent=2, default=str)
        else:
            raise ValueError(f"Unsupported format: {format}")


def load_log_file(filepath: str) -> List[Dict[str, Any]]:
    """Load JSON logs from a JSONL file.
    
    Args:
        filepath: Path to log file (JSONL format, one JSON per line)
        
    Returns:
        List of parsed log dictionaries
        
    Raises:
        IOError: If file cannot be read
        ValueError: If logs are malformed
    """
    logs: List[Dict[str, Any]] = []
    
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                log = json.loads(line)
                logs.append(log)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed JSON in log file: {exc}")
    
    return logs


def save_log_file(filepath: str, logs: List[Dict[str, Any]]) -> None:
    """Save logs to JSONL file.
    
    Args:
        filepath: Path to log file
        logs: List of log dictionaries
    """
    with open(filepath, 'w') as f:
        for log in logs:
            f.write(json.dumps(log, default=str) + '\n')
