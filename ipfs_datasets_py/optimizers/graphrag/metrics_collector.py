"""
Metrics Collector for Ontology Optimization.

This module provides comprehensive metrics collection and analysis for ontology
optimization sessions. Tracks performance, quality, and efficiency metrics across
sessions and batches.

Key Features:
    - Session-level metrics collection
    - Batch-level aggregation
    - Time-series tracking
    - Export in multiple formats (JSON, CSV)
    - Statistical analysis

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag import MetricsCollector
    >>> 
    >>> collector = MetricsCollector()
    >>> 
    >>> # Record session
    >>> collector.record_session(session_result)
    >>> 
    >>> # Get statistics
    >>> stats = collector.get_statistics()
    >>> print(f"Average quality: {stats['average_quality_score']:.2f}")
    >>> 
    >>> # Export metrics
    >>> json_data = collector.export_metrics(format='json')

References:
    - Standard metrics collection patterns
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SessionMetrics:
    """
    Metrics from a single ontology session.
    
    Attributes:
        session_id: Unique session identifier
        timestamp: Unix timestamp of session start
        quality_score: Overall quality score
        validation_score: Validation consistency score
        num_rounds: Number of refinement rounds
        time_elapsed: Total time in seconds
        num_entities: Number of entities extracted
        num_relationships: Number of relationships extracted
        converged: Whether session converged
        domain: Domain of the ontology
        metadata: Additional metrics
    """
    
    session_id: str
    timestamp: float
    quality_score: float
    validation_score: float
    num_rounds: int
    time_elapsed: float
    num_entities: int
    num_relationships: int
    converged: bool
    domain: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class MetricsCollector:
    """
    Collect and analyze ontology optimization metrics.
    
    Maintains a history of all session metrics and provides statistical
    analysis, trend identification, and export capabilities.
    
    Example:
        >>> collector = MetricsCollector()
        >>> 
        >>> # Record multiple sessions
        >>> for result in session_results:
        ...     collector.record_session(result)
        >>> 
        >>> # Analyze
        >>> stats = collector.get_statistics()
        >>> print(f"Sessions: {stats['total_sessions']}")
        >>> print(f"Avg quality: {stats['average_quality_score']:.2f}")
        >>> print(f"Convergence rate: {stats['convergence_rate']:.1%}")
        >>> 
        >>> # Export for analysis
        >>> json_str = collector.export_metrics(format='json')
        >>> csv_str = collector.export_metrics(format='csv')
    """
    
    def __init__(self):
        """Initialize the metrics collector."""
        self._metrics: List[SessionMetrics] = []
        self._batch_metrics: List[Dict[str, Any]] = []
        self._start_time = time.time()
        
        logger.info("Initialized MetricsCollector")
    
    def record_session(self, session_result: Any) -> None:
        """
        Record metrics from a session result.
        
        Args:
            session_result: SessionResult object
            
        Example:
            >>> collector.record_session(session_result)
        """
        # Extract metrics from session result
        session_id = f"session_{len(self._metrics) + 1}"
        timestamp = time.time()
        
        # Get quality score
        quality_score = 0.0
        if hasattr(session_result, 'critic_score') and session_result.critic_score:
            quality_score = (
                session_result.critic_score.overall
                if hasattr(session_result.critic_score, 'overall')
                else 0.0
            )
        
        # Get validation score
        validation_score = 1.0 if (
            hasattr(session_result, 'validation_result') and
            session_result.validation_result and
            hasattr(session_result.validation_result, 'is_consistent') and
            session_result.validation_result.is_consistent
        ) else 0.0
        
        # Get ontology stats
        num_entities = len(session_result.ontology.get('entities', [])) if hasattr(session_result, 'ontology') else 0
        num_relationships = len(session_result.ontology.get('relationships', [])) if hasattr(session_result, 'ontology') else 0
        
        # Get domain
        domain = session_result.ontology.get('domain', 'unknown') if hasattr(session_result, 'ontology') else 'unknown'
        
        # Create metrics object
        metrics = SessionMetrics(
            session_id=session_id,
            timestamp=timestamp,
            quality_score=quality_score,
            validation_score=validation_score,
            num_rounds=session_result.num_rounds if hasattr(session_result, 'num_rounds') else 0,
            time_elapsed=session_result.time_elapsed if hasattr(session_result, 'time_elapsed') else 0.0,
            num_entities=num_entities,
            num_relationships=num_relationships,
            converged=session_result.converged if hasattr(session_result, 'converged') else False,
            domain=domain,
            metadata={
                'timestamp_iso': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp)),
            }
        )
        
        self._metrics.append(metrics)
        
        logger.debug(
            f"Recorded session metrics: quality={quality_score:.2f}, "
            f"entities={num_entities}, time={metrics.time_elapsed:.2f}s"
        )
    
    def record_batch(self, batch_result: Any) -> None:
        """
        Record metrics from a batch result.
        
        Args:
            batch_result: BatchResult object
        """
        batch_metrics = {
            'timestamp': time.time(),
            'total_sessions': batch_result.total_sessions if hasattr(batch_result, 'total_sessions') else 0,
            'success_rate': batch_result.success_rate if hasattr(batch_result, 'success_rate') else 0.0,
            'average_score': batch_result.average_score if hasattr(batch_result, 'average_score') else 0.0,
            'metadata': batch_result.metadata if hasattr(batch_result, 'metadata') else {},
        }
        
        self._batch_metrics.append(batch_metrics)
        
        logger.debug(
            f"Recorded batch metrics: sessions={batch_metrics['total_sessions']}, "
            f"avg={batch_metrics['average_score']:.2f}"
        )
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get aggregated statistics across all sessions.
        
        Returns:
            Dictionary with comprehensive statistics
            
        Example:
            >>> stats = collector.get_statistics()
            >>> print(f"Total sessions: {stats['total_sessions']}")
            >>> print(f"Average quality: {stats['average_quality_score']:.2f}")
        """
        if not self._metrics:
            return {
                'total_sessions': 0,
                'error': 'No metrics recorded'
            }
        
        # Compute basic statistics
        total_sessions = len(self._metrics)
        
        quality_scores = [m.quality_score for m in self._metrics]
        avg_quality = sum(quality_scores) / len(quality_scores)
        min_quality = min(quality_scores)
        max_quality = max(quality_scores)
        
        validation_scores = [m.validation_score for m in self._metrics]
        avg_validation = sum(validation_scores) / len(validation_scores)
        
        converged_count = sum(1 for m in self._metrics if m.converged)
        convergence_rate = converged_count / total_sessions
        
        avg_rounds = sum(m.num_rounds for m in self._metrics) / total_sessions
        avg_time = sum(m.time_elapsed for m in self._metrics) / total_sessions
        
        avg_entities = sum(m.num_entities for m in self._metrics) / total_sessions
        avg_relationships = sum(m.num_relationships for m in self._metrics) / total_sessions
        
        # Domain breakdown
        domain_counts = defaultdict(int)
        for m in self._metrics:
            domain_counts[m.domain] += 1
        
        # Time-based statistics
        uptime = time.time() - self._start_time
        sessions_per_hour = total_sessions / (uptime / 3600) if uptime > 0 else 0.0
        
        return {
            'total_sessions': total_sessions,
            'average_quality_score': avg_quality,
            'min_quality_score': min_quality,
            'max_quality_score': max_quality,
            'average_validation_score': avg_validation,
            'convergence_rate': convergence_rate,
            'average_rounds': avg_rounds,
            'average_time_seconds': avg_time,
            'average_entities': avg_entities,
            'average_relationships': avg_relationships,
            'domains': dict(domain_counts),
            'uptime_seconds': uptime,
            'sessions_per_hour': sessions_per_hour,
            'total_batches': len(self._batch_metrics),
        }
    
    def get_time_series(self, metric_name: str) -> List[tuple]:
        """
        Get time series data for a specific metric.
        
        Args:
            metric_name: Name of metric to extract
            
        Returns:
            List of (timestamp, value) tuples
            
        Example:
            >>> time_series = collector.get_time_series('quality_score')
            >>> for timestamp, score in time_series:
            ...     print(f"{timestamp}: {score:.2f}")
        """
        time_series = []
        
        for metrics in self._metrics:
            if hasattr(metrics, metric_name):
                value = getattr(metrics, metric_name)
                time_series.append((metrics.timestamp, value))
        
        return time_series
    
    def export_metrics(self, format: str = 'json') -> str:
        """
        Export metrics in specified format.
        
        Args:
            format: Export format ('json' or 'csv')
            
        Returns:
            Formatted metrics string
            
        Raises:
            ValueError: If format is not supported
            
        Example:
            >>> json_data = collector.export_metrics(format='json')
            >>> with open('metrics.json', 'w') as f:
            ...     f.write(json_data)
            >>> 
            >>> csv_data = collector.export_metrics(format='csv')
            >>> with open('metrics.csv', 'w') as f:
            ...     f.write(csv_data)
        """
        if format == 'json':
            return self._export_json()
        elif format == 'csv':
            return self._export_csv()
        else:
            raise ValueError(f"Unsupported format: {format}. Use 'json' or 'csv'.")
    
    def _export_json(self) -> str:
        """Export metrics as JSON."""
        data = {
            'statistics': self.get_statistics(),
            'sessions': [
                {
                    'session_id': m.session_id,
                    'timestamp': m.timestamp,
                    'quality_score': m.quality_score,
                    'validation_score': m.validation_score,
                    'num_rounds': m.num_rounds,
                    'time_elapsed': m.time_elapsed,
                    'num_entities': m.num_entities,
                    'num_relationships': m.num_relationships,
                    'converged': m.converged,
                    'domain': m.domain,
                }
                for m in self._metrics
            ],
            'batches': self._batch_metrics,
        }
        
        return json.dumps(data, indent=2)
    
    def _export_csv(self) -> str:
        """Export metrics as CSV."""
        if not self._metrics:
            return "No metrics to export"
        
        # CSV header
        lines = [
            "session_id,timestamp,quality_score,validation_score,num_rounds,"
            "time_elapsed,num_entities,num_relationships,converged,domain"
        ]
        
        # Data rows
        for m in self._metrics:
            lines.append(
                f"{m.session_id},{m.timestamp},{m.quality_score},{m.validation_score},"
                f"{m.num_rounds},{m.time_elapsed},{m.num_entities},{m.num_relationships},"
                f"{m.converged},{m.domain}"
            )
        
        return "\n".join(lines)
    
    def clear(self) -> None:
        """Clear all collected metrics."""
        self._metrics.clear()
        self._batch_metrics.clear()
        logger.info("Cleared all metrics")
    
    def get_trend_analysis(self, window_size: int = 10) -> Dict[str, Any]:
        """
        Analyze trends over recent sessions.
        
        Args:
            window_size: Number of recent sessions to analyze
            
        Returns:
            Dictionary with trend analysis
        """
        if len(self._metrics) < window_size:
            window_size = len(self._metrics)
        
        if window_size < 2:
            return {'error': 'Not enough data for trend analysis'}
        
        recent_metrics = self._metrics[-window_size:]
        
        # Quality score trend
        quality_scores = [m.quality_score for m in recent_metrics]
        quality_trend = 'improving' if quality_scores[-1] > quality_scores[0] else 'degrading'
        
        # Time trend
        times = [m.time_elapsed for m in recent_metrics]
        time_trend = 'faster' if times[-1] < times[0] else 'slower'
        
        # Convergence trend
        recent_convergence = sum(1 for m in recent_metrics if m.converged) / window_size
        
        return {
            'window_size': window_size,
            'quality_trend': quality_trend,
            'quality_change': quality_scores[-1] - quality_scores[0],
            'time_trend': time_trend,
            'time_change': times[-1] - times[0],
            'convergence_rate': recent_convergence,
        }


# Export public API
__all__ = [
    'MetricsCollector',
    'SessionMetrics',
]
