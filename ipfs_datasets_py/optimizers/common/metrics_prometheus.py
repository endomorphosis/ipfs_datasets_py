"""Prometheus metrics integration for optimizer module.

Provides Prometheus-compatible metrics for optimizer sessions including:
- Histogram of optimization scores
- Counter of completed rounds
- Gauge of session duration
- Performance metrics (time, memory)

Metrics are optional and controlled by ENABLE_PROMETHEUS environment variable.

Example:
    >>> from ipfs_datasets_py.optimizers.common.metrics_prometheus import PrometheusMetrics
    >>> metrics = PrometheusMetrics()
    >>>
    >>> # Record optimization score
    >>> metrics.record_score(0.85)
    >>>
    >>> # Increment round counter
    >>> metrics.record_round_completion()
    >>>
    >>> # Record session duration
    >>> metrics.record_session_duration(15.3)
    >>>
    >>> # Get metrics in Prometheus format
    >>> print(metrics.collect_metrics())
"""

import os
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

_GLOBAL_PROMETHEUS_METRICS: Optional["PrometheusMetrics"] = None


def get_global_prometheus_metrics(enabled: Optional[bool] = None) -> "PrometheusMetrics":
    """Return a shared PrometheusMetrics instance.

    Args:
        enabled: Optional override for enablement at first initialization.

    Returns:
        Singleton PrometheusMetrics instance.
    """
    global _GLOBAL_PROMETHEUS_METRICS
    if _GLOBAL_PROMETHEUS_METRICS is None:
        _GLOBAL_PROMETHEUS_METRICS = PrometheusMetrics(enabled=enabled)
    return _GLOBAL_PROMETHEUS_METRICS


@dataclass
class MetricValue:
    """Single metric value with timestamp."""
    value: float
    timestamp: float = field(default_factory=time.time)
    labels: Dict[str, str] = field(default_factory=dict)


class PrometheusMetrics:
    """Prometheus metrics collector for optimizer sessions.
    
    Tracks important metrics like optimization scores, round completion,
    session duration, and memory usage. Can emit metrics in Prometheus
    text format for scraping by Prometheus or other monitoring systems.
    
    Metrics are lazy-initialized only if ENABLE_PROMETHEUS environment
    variable is set to "1", "true", or "yes".
    """
    
    # Metric names (Prometheus convention: _total, _buckets, _sum, _count)
    SCORE_HISTOGRAM = "optimizer_score"  # Optimization score (0-1)
    ROUNDS_COUNTER = "optimizer_rounds_completed_total"  # Total rounds
    DURATION_GAUGE = "optimizer_session_duration_seconds"  # Session duration
    ERRORS_COUNTER = "optimizer_errors_total"  # Total errors
    CACHE_HITS_COUNTER = "optimizer_cache_hits_total"  # Cache hit count
    MEMORY_GAUGE = "optimizer_memory_usage_bytes"  # Peak memory
    STAGE_DURATION_HISTOGRAM = "optimizer_stage_duration_seconds"
    SCORE_DELTA_GAUGE = "optimizer_score_delta"
    
    # Score histogram buckets (for quantiles)
    SCORE_BUCKETS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    STAGE_DURATION_BUCKETS = [
        0.001,
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
        30.0,
    ]
    
    def __init__(self, enabled: Optional[bool] = None):
        """Initialize PrometheusMetrics.
        
        Args:
            enabled: If True, enable metrics collection. If None, check ENABLE_PROMETHEUS env var.
                    Default: None (check env)
        """
        if enabled is None:
            env_val = os.environ.get("ENABLE_PROMETHEUS", "").lower()
            self.enabled = env_val in ("1", "true", "yes")
        else:
            self.enabled = enabled
        
        # Initialize metric storage
        self.scores: List[MetricValue] = []
        self.rounds: List[MetricValue] = []  # Cumulative round count
        self.durations: List[MetricValue] = []
        self.errors: List[MetricValue] = []
        self.cache_hits: List[MetricValue] = []
        self.memory_usage: List[MetricValue] = []
        self.stage_durations: List[MetricValue] = []
        self.score_deltas: List[MetricValue] = []
        
        # Session tracking
        self.session_start: Optional[float] = None
        self.current_round = 0
        self.total_errors = 0
        self.total_cache_hits = 0
        
        if self.enabled:
            logger.info("Prometheus metrics collection enabled")
            self.session_start = time.time()
    
    def record_score(self, score: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Record an optimization score (0-1).
        
        Args:
            score: Quality score from 0 (worst) to 1 (best)
            labels: Optional labels (domain, strategy, optimizer_type, etc.)
        """
        if not self.enabled:
            return
        
        # Validate score
        if not (0.0 <= score <= 1.0):
            logger.warning(f"Invalid score {score}; must be in [0, 1]")
            score = max(0.0, min(1.0, score))
        
        value = MetricValue(value=score, labels=labels or {})
        self.scores.append(value)
        
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Recorded optimization score: {score:.4f}")
    
    def record_round_completion(self, domain: Optional[str] = None) -> None:
        """Increment round completion counter.
        
        Args:
            domain: Optimization domain (legal, medical, etc.)
        """
        if not self.enabled:
            return
        
        self.current_round += 1
        labels = {"domain": domain} if domain else {}
        value = MetricValue(value=float(self.current_round), labels=labels)
        self.rounds.append(value)
        
        logger.debug(f"Round {self.current_round} completed")
    
    def record_session_duration(self, duration_seconds: float) -> None:
        """Record session duration in seconds.
        
        Args:
            duration_seconds: Session duration (seconds)
        """
        if not self.enabled:
            return
        
        value = MetricValue(value=duration_seconds)
        self.durations.append(value)
        
        logger.info(f"Session completed in {duration_seconds:.2f}s")
    
    def record_error(self, error_type: str, dimension: str = "") -> None:
        """Record an error occurred.
        
        Args:
            error_type: Type of error (validation, llm, timeout, etc.)
            dimension: Additional dimension (optimizer_type, round_num, etc.)
        """
        if not self.enabled:
            return
        
        self.total_errors += 1
        labels = {
            "error_type": error_type,
            "dimension": dimension,
        }
        value = MetricValue(value=float(self.total_errors), labels=labels)
        self.errors.append(value)
        
        logger.warning(f"Error recorded: {error_type} ({dimension})")
    
    def record_cache_hit(self, cache_type: str = "general") -> None:
        """Record a cache hit.
        
        Args:
            cache_type: Type of cache (general, ontology, validation, etc.)
        """
        if not self.enabled:
            return
        
        self.total_cache_hits += 1
        labels = {"cache_type": cache_type}
        value = MetricValue(value=float(self.total_cache_hits), labels=labels)
        self.cache_hits.append(value)
        
        logger.debug(f"Cache hit recorded: {cache_type}")
    
    def record_memory_usage(self, bytes_used: int) -> None:
        """Record memory usage.
        
        Args:
            bytes_used: Memory used in bytes
        """
        if not self.enabled:
            return
        
        value = MetricValue(value=float(bytes_used))
        self.memory_usage.append(value)

    def record_stage_duration(
        self,
        stage: str,
        duration_seconds: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        """Record pipeline stage duration in seconds.

        Args:
            stage: Stage name (extracting/evaluating/refining/etc.).
            duration_seconds: Stage duration in seconds.
            labels: Optional labels (domain, pipeline_type, etc.).
        """
        if not self.enabled:
            return

        if duration_seconds < 0.0:
            logger.warning("Invalid stage duration %.6f; clamping to 0", duration_seconds)
            duration_seconds = 0.0

        metric_labels = {"stage": stage}
        if labels:
            metric_labels.update(labels)

        value = MetricValue(value=float(duration_seconds), labels=metric_labels)
        self.stage_durations.append(value)

    def record_score_delta(self, delta: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Record score delta (final minus initial) for an optimization run."""
        if not self.enabled:
            return
        value = MetricValue(value=float(delta), labels=labels or {})
        self.score_deltas.append(value)
    
    def collect_metrics(self) -> str:
        """Collect metrics in Prometheus text format.
        
        Returns:
            Prometheus format metrics string
        """
        if not self.enabled:
            return "# Prometheus metrics disabled\n"
        
        lines = [
            f"# HELP {self.SCORE_HISTOGRAM} Optimization score histogram (0-1)",
            f"# TYPE {self.SCORE_HISTOGRAM} histogram",
        ]
        
        # Add score histogram
        for bucket_threshold in self.SCORE_BUCKETS:
            bucket_count = sum(1 for s in self.scores if s.value <= bucket_threshold)
            lines.append(f'{self.SCORE_HISTOGRAM}_bucket{{le="{bucket_threshold}"}} {bucket_count}')
        
        # Total count and sum for histogram
        if self.scores:
            lines.append(f'{self.SCORE_HISTOGRAM}_sum {sum(s.value for s in self.scores)}')
            lines.append(f'{self.SCORE_HISTOGRAM}_count {len(self.scores)}')
        else:
            lines.append(f'{self.SCORE_HISTOGRAM}_sum 0')
            lines.append(f'{self.SCORE_HISTOGRAM}_count 0')
        
        lines.append("")
        
        # Add round counter
        lines.append(f"# HELP {self.ROUNDS_COUNTER} Total rounds completed")
        lines.append(f"# TYPE {self.ROUNDS_COUNTER} counter")
        lines.append(f"{self.ROUNDS_COUNTER} {self.current_round}")
        lines.append("")
        
        # Add duration gauge
        if self.durations:
            latest_duration = self.durations[-1].value
            lines.append(f"# HELP {self.DURATION_GAUGE} Last session duration in seconds")
            lines.append(f"# TYPE {self.DURATION_GAUGE} gauge")
            lines.append(f"{self.DURATION_GAUGE} {latest_duration}")
            lines.append("")

        # Add stage duration histogram
        if self.stage_durations:
            lines.append(f"# HELP {self.STAGE_DURATION_HISTOGRAM} Pipeline stage duration histogram")
            lines.append(f"# TYPE {self.STAGE_DURATION_HISTOGRAM} histogram")

            grouped: Dict[tuple[tuple[str, str], ...], List[MetricValue]] = {}
            for record in self.stage_durations:
                labels_tuple = tuple(sorted(record.labels.items()))
                grouped.setdefault(labels_tuple, []).append(record)

            for labels_tuple, records in grouped.items():
                labels_dict = dict(labels_tuple)
                label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels_dict.items()))
                for bucket_threshold in self.STAGE_DURATION_BUCKETS:
                    bucket_count = sum(1 for r in records if r.value <= bucket_threshold)
                    lines.append(
                        f'{self.STAGE_DURATION_HISTOGRAM}_bucket'
                        f'{{{label_str},le="{bucket_threshold}"}} {bucket_count}'
                    )
                total_sum = sum(r.value for r in records)
                lines.append(
                    f'{self.STAGE_DURATION_HISTOGRAM}_sum'
                    f'{{{label_str}}} {total_sum}'
                )
                lines.append(
                    f'{self.STAGE_DURATION_HISTOGRAM}_count'
                    f'{{{label_str}}} {len(records)}'
                )
            lines.append("")

        # Add score delta gauge
        if self.score_deltas:
            latest_delta = self.score_deltas[-1]
            lines.append(f"# HELP {self.SCORE_DELTA_GAUGE} Score delta (final - initial)")
            lines.append(f"# TYPE {self.SCORE_DELTA_GAUGE} gauge")
            lines.append(f"{self.SCORE_DELTA_GAUGE} {latest_delta.value}")
            lines.append("")
        
        # Add error counter
        lines.append(f"# HELP {self.ERRORS_COUNTER} Total errors encountered")
        lines.append(f"# TYPE {self.ERRORS_COUNTER} counter")
        lines.append(f"{self.ERRORS_COUNTER} {self.total_errors}")
        lines.append("")
        
        # Add cache hits counter
        lines.append(f"# HELP {self.CACHE_HITS_COUNTER} Total cache hits")
        lines.append(f"# TYPE {self.CACHE_HITS_COUNTER} counter")
        lines.append(f"{self.CACHE_HITS_COUNTER} {self.total_cache_hits}")
        lines.append("")
        
        # Add memory gauge
        if self.memory_usage:
            peak_memory = max(m.value for m in self.memory_usage)
            lines.append(f"# HELP {self.MEMORY_GAUGE} Peak memory usage in bytes")
            lines.append(f"# TYPE {self.MEMORY_GAUGE} gauge")
            lines.append(f"{self.MEMORY_GAUGE} {int(peak_memory)}")
        
        return "\n".join(lines)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of collected metrics.
        
        Returns:
            Dictionary with metric summaries
        """
        if not self.scores:
            return {"enabled": self.enabled, "scores_recorded": 0}
        
        scores = [s.value for s in self.scores]
        return {
            "enabled": self.enabled,
            "scores_recorded": len(scores),
            "avg_score": sum(scores) / len(scores),
            "min_score": min(scores),
            "max_score": max(scores),
            "rounds_completed": self.current_round,
            "errors": self.total_errors,
            "cache_hits": self.total_cache_hits,
            "total_sessions": len(self.durations),
        }
