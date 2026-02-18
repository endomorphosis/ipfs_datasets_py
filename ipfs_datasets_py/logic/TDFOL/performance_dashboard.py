"""
TDFOL Performance Dashboard - Comprehensive monitoring and visualization

This module provides real-time performance monitoring and visualization for TDFOL
theorem proving, with support for:

1. Real-time metrics collection during proof execution
2. Statistics aggregation across multiple proofs
3. Interactive HTML dashboard generation with Chart.js
4. JSON export for external monitoring tools
5. Strategy comparison and performance analysis

Features:
- Proof time tracking (P50, P95, P99 percentiles)
- Cache hit/miss rates and speedup calculations
- Strategy selection frequency and performance
- Memory usage monitoring
- Formula complexity metrics
- Success/failure rates by formula type
- Real-time updates capability
- Export as standalone HTML files

Usage:
    >>> dashboard = PerformanceDashboard()
    >>> 
    >>> # Record proof results
    >>> dashboard.record_proof(proof_result, metadata={'strategy': 'forward'})
    >>> 
    >>> # Get statistics
    >>> stats = dashboard.get_statistics()
    >>> print(f"Cache hit rate: {stats['cache_hit_rate']:.1%}")
    >>> 
    >>> # Generate HTML dashboard
    >>> dashboard.generate_html('dashboard.html')
    >>> 
    >>> # Export JSON
    >>> dashboard.export_json('metrics.json')
    >>> 
    >>> # Compare strategies
    >>> comparison = dashboard.compare_strategies()
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum
import statistics

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================


class MetricType(Enum):
    """Types of metrics that can be recorded."""
    PROOF_TIME = "proof_time"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    MEMORY_USAGE = "memory_usage"
    FORMULA_COMPLEXITY = "formula_complexity"
    STRATEGY_SELECTION = "strategy_selection"
    SUCCESS = "success"
    FAILURE = "failure"
    ZKP_VERIFICATION = "zkp_verification"


@dataclass
class ProofMetrics:
    """Metrics for a single proof attempt."""
    
    timestamp: float
    formula_str: str
    formula_complexity: int
    proof_time_ms: float
    success: bool
    method: str
    strategy: str
    cache_hit: bool
    memory_usage_mb: float
    num_steps: int
    formula_type: str  # "temporal", "deontic", "modal", "propositional"
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'timestamp': self.timestamp,
            'datetime': datetime.fromtimestamp(self.timestamp).isoformat(),
            'formula': self.formula_str,
            'complexity': self.formula_complexity,
            'proof_time_ms': self.proof_time_ms,
            'success': self.success,
            'method': self.method,
            'strategy': self.strategy,
            'cache_hit': self.cache_hit,
            'memory_mb': self.memory_usage_mb,
            'num_steps': self.num_steps,
            'formula_type': self.formula_type,
            'metadata': self.metadata
        }


@dataclass
class TimeSeriesMetric:
    """Time-series metric data point."""
    
    timestamp: float
    metric_name: str
    value: float
    tags: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'timestamp': self.timestamp,
            'datetime': datetime.fromtimestamp(self.timestamp).isoformat(),
            'metric': self.metric_name,
            'value': self.value,
            'tags': self.tags
        }


@dataclass
class AggregatedStats:
    """Aggregated statistics across multiple proofs."""
    
    total_proofs: int = 0
    successful_proofs: int = 0
    failed_proofs: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    
    # Timing statistics (ms)
    total_proof_time_ms: float = 0.0
    min_proof_time_ms: float = float('inf')
    max_proof_time_ms: float = 0.0
    avg_proof_time_ms: float = 0.0
    median_proof_time_ms: float = 0.0
    p95_proof_time_ms: float = 0.0
    p99_proof_time_ms: float = 0.0
    
    # Cache statistics
    cache_hit_rate: float = 0.0
    avg_speedup_from_cache: float = 0.0
    
    # Formula statistics
    avg_formula_complexity: float = 0.0
    avg_proof_steps: float = 0.0
    
    # Memory statistics
    avg_memory_usage_mb: float = 0.0
    max_memory_usage_mb: float = 0.0
    
    # Strategy statistics
    strategy_counts: Dict[str, int] = field(default_factory=dict)
    strategy_success_rates: Dict[str, float] = field(default_factory=dict)
    strategy_avg_times: Dict[str, float] = field(default_factory=dict)
    
    # Formula type statistics
    formula_type_counts: Dict[str, int] = field(default_factory=dict)
    formula_type_success_rates: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'total_proofs': self.total_proofs,
            'successful_proofs': self.successful_proofs,
            'failed_proofs': self.failed_proofs,
            'success_rate': self.successful_proofs / self.total_proofs if self.total_proofs > 0 else 0.0,
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'cache_hit_rate': self.cache_hit_rate,
            'avg_speedup_from_cache': self.avg_speedup_from_cache,
            'timing': {
                'total_ms': self.total_proof_time_ms,
                'min_ms': self.min_proof_time_ms if self.min_proof_time_ms != float('inf') else 0.0,
                'max_ms': self.max_proof_time_ms,
                'avg_ms': self.avg_proof_time_ms,
                'median_ms': self.median_proof_time_ms,
                'p95_ms': self.p95_proof_time_ms,
                'p99_ms': self.p99_proof_time_ms,
            },
            'formulas': {
                'avg_complexity': self.avg_formula_complexity,
                'avg_steps': self.avg_proof_steps,
            },
            'memory': {
                'avg_mb': self.avg_memory_usage_mb,
                'max_mb': self.max_memory_usage_mb,
            },
            'strategies': {
                'counts': self.strategy_counts,
                'success_rates': self.strategy_success_rates,
                'avg_times_ms': self.strategy_avg_times,
            },
            'formula_types': {
                'counts': self.formula_type_counts,
                'success_rates': self.formula_type_success_rates,
            }
        }


# ============================================================================
# Performance Dashboard
# ============================================================================


class PerformanceDashboard:
    """
    Comprehensive performance dashboard for TDFOL theorem proving.
    
    Collects and aggregates metrics from proof attempts, providing:
    - Real-time monitoring
    - Historical analysis
    - Interactive visualizations
    - Performance comparisons
    
    Attributes:
        proof_metrics: List of all recorded proof metrics
        timeseries_metrics: List of all time-series metrics
        start_time: Dashboard start timestamp
    
    Example:
        >>> dashboard = PerformanceDashboard()
        >>> 
        >>> # Record proof
        >>> result = prover.prove(formula)
        >>> dashboard.record_proof(result, metadata={'strategy': 'forward'})
        >>> 
        >>> # Generate dashboard
        >>> dashboard.generate_html('dashboard.html')
    """
    
    def __init__(self):
        """Initialize the performance dashboard."""
        self.proof_metrics: List[ProofMetrics] = []
        self.timeseries_metrics: List[TimeSeriesMetric] = []
        self.start_time = time.time()
        
        # Cache for statistics (invalidated on new data)
        self._stats_cache: Optional[AggregatedStats] = None
        self._stats_cache_valid = False
        
        logger.info("Performance dashboard initialized")
    
    def record_proof(
        self,
        proof_result: Any,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record metrics from a proof attempt.
        
        Args:
            proof_result: ProofResult from prover (must have attributes:
                         formula, time_ms, status/is_proved(), method, proof_steps)
            metadata: Optional additional metadata (strategy, cache_hit, etc.)
        
        Example:
            >>> result = prover.prove(formula)
            >>> dashboard.record_proof(result, metadata={
            ...     'strategy': 'forward',
            ...     'cache_hit': False,
            ...     'memory_mb': 128.5
            ... })
        """
        if metadata is None:
            metadata = {}
        
        # Extract proof information
        formula_str = str(proof_result.formula)
        
        # Determine success
        if hasattr(proof_result, 'is_proved'):
            success = proof_result.is_proved()
        elif hasattr(proof_result, 'status'):
            success = str(proof_result.status) == 'ProofStatus.PROVED'
        else:
            success = metadata.get('success', False)
        
        # Get proof time
        proof_time_ms = getattr(proof_result, 'time_ms', metadata.get('proof_time_ms', 0.0))
        
        # Get method
        method = getattr(proof_result, 'method', metadata.get('method', 'unknown'))
        
        # Get proof steps
        proof_steps = getattr(proof_result, 'proof_steps', [])
        num_steps = len(proof_steps)
        
        # Extract metadata
        strategy = metadata.get('strategy', 'unknown')
        cache_hit = metadata.get('cache_hit', False)
        memory_mb = metadata.get('memory_mb', 0.0)
        
        # Determine formula complexity and type
        complexity = self._calculate_complexity(formula_str)
        formula_type = self._determine_formula_type(formula_str)
        
        # Create metrics record
        metrics = ProofMetrics(
            timestamp=time.time(),
            formula_str=formula_str,
            formula_complexity=complexity,
            proof_time_ms=proof_time_ms,
            success=success,
            method=method,
            strategy=strategy,
            cache_hit=cache_hit,
            memory_usage_mb=memory_mb,
            num_steps=num_steps,
            formula_type=formula_type,
            metadata=metadata
        )
        
        self.proof_metrics.append(metrics)
        self._stats_cache_valid = False
        
        # Record time-series metrics
        self.record_metric(
            'proof_time_ms',
            proof_time_ms,
            tags={'strategy': strategy, 'success': str(success)}
        )
        
        if cache_hit:
            self.record_metric('cache_hit', 1.0, tags={'strategy': strategy})
        else:
            self.record_metric('cache_miss', 1.0, tags={'strategy': strategy})
        
        logger.debug(f"Recorded proof metrics: {formula_str[:50]}... "
                    f"({proof_time_ms:.2f}ms, success={success})")
    
    def record_metric(
        self,
        metric_name: str,
        value: float,
        tags: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Record a custom metric value.
        
        Args:
            metric_name: Name of the metric
            value: Metric value
            tags: Optional tags for the metric
        
        Example:
            >>> dashboard.record_metric('memory_usage_mb', 256.5,
            ...                         tags={'process': 'prover'})
        """
        if tags is None:
            tags = {}
        
        metric = TimeSeriesMetric(
            timestamp=time.time(),
            metric_name=metric_name,
            value=value,
            tags=tags
        )
        
        self.timeseries_metrics.append(metric)
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get aggregated statistics across all recorded proofs.
        
        Returns:
            Dictionary containing comprehensive statistics
        
        Example:
            >>> stats = dashboard.get_statistics()
            >>> print(f"Success rate: {stats['success_rate']:.1%}")
            >>> print(f"Cache hit rate: {stats['cache_hit_rate']:.1%}")
            >>> print(f"Median proof time: {stats['timing']['median_ms']:.2f}ms")
        """
        if self._stats_cache_valid and self._stats_cache:
            return self._stats_cache.to_dict()
        
        stats = self._calculate_statistics()
        self._stats_cache = stats
        self._stats_cache_valid = True
        
        return stats.to_dict()
    
    def _calculate_statistics(self) -> AggregatedStats:
        """Calculate aggregated statistics from proof metrics."""
        if not self.proof_metrics:
            return AggregatedStats()
        
        stats = AggregatedStats()
        
        # Count totals
        stats.total_proofs = len(self.proof_metrics)
        stats.successful_proofs = sum(1 for m in self.proof_metrics if m.success)
        stats.failed_proofs = stats.total_proofs - stats.successful_proofs
        stats.cache_hits = sum(1 for m in self.proof_metrics if m.cache_hit)
        stats.cache_misses = stats.total_proofs - stats.cache_hits
        
        # Calculate cache statistics
        if stats.total_proofs > 0:
            stats.cache_hit_rate = stats.cache_hits / stats.total_proofs
        
        # Calculate cache speedup
        cache_hit_times = [m.proof_time_ms for m in self.proof_metrics if m.cache_hit]
        cache_miss_times = [m.proof_time_ms for m in self.proof_metrics if not m.cache_hit]
        
        if cache_hit_times and cache_miss_times:
            avg_hit_time = statistics.mean(cache_hit_times)
            avg_miss_time = statistics.mean(cache_miss_times)
            if avg_hit_time > 0:
                stats.avg_speedup_from_cache = avg_miss_time / avg_hit_time
        
        # Timing statistics
        proof_times = [m.proof_time_ms for m in self.proof_metrics]
        
        if proof_times:
            stats.total_proof_time_ms = sum(proof_times)
            stats.min_proof_time_ms = min(proof_times)
            stats.max_proof_time_ms = max(proof_times)
            stats.avg_proof_time_ms = statistics.mean(proof_times)
            stats.median_proof_time_ms = statistics.median(proof_times)
            
            # Calculate percentiles
            sorted_times = sorted(proof_times)
            n = len(sorted_times)
            stats.p95_proof_time_ms = sorted_times[int(0.95 * n)] if n > 0 else 0.0
            stats.p99_proof_time_ms = sorted_times[int(0.99 * n)] if n > 0 else 0.0
        
        # Formula statistics
        complexities = [m.formula_complexity for m in self.proof_metrics]
        steps = [m.num_steps for m in self.proof_metrics]
        
        if complexities:
            stats.avg_formula_complexity = statistics.mean(complexities)
        if steps:
            stats.avg_proof_steps = statistics.mean(steps)
        
        # Memory statistics
        memory_usages = [m.memory_usage_mb for m in self.proof_metrics]
        if memory_usages:
            stats.avg_memory_usage_mb = statistics.mean(memory_usages)
            stats.max_memory_usage_mb = max(memory_usages)
        
        # Strategy statistics
        strategy_data = defaultdict(lambda: {'count': 0, 'success': 0, 'times': []})
        
        for m in self.proof_metrics:
            strategy_data[m.strategy]['count'] += 1
            if m.success:
                strategy_data[m.strategy]['success'] += 1
            strategy_data[m.strategy]['times'].append(m.proof_time_ms)
        
        for strategy, data in strategy_data.items():
            stats.strategy_counts[strategy] = data['count']
            stats.strategy_success_rates[strategy] = (
                data['success'] / data['count'] if data['count'] > 0 else 0.0
            )
            stats.strategy_avg_times[strategy] = (
                statistics.mean(data['times']) if data['times'] else 0.0
            )
        
        # Formula type statistics
        type_data = defaultdict(lambda: {'count': 0, 'success': 0})
        
        for m in self.proof_metrics:
            type_data[m.formula_type]['count'] += 1
            if m.success:
                type_data[m.formula_type]['success'] += 1
        
        for ftype, data in type_data.items():
            stats.formula_type_counts[ftype] = data['count']
            stats.formula_type_success_rates[ftype] = (
                data['success'] / data['count'] if data['count'] > 0 else 0.0
            )
        
        return stats
    
    def compare_strategies(self) -> Dict[str, Any]:
        """
        Compare performance across different proving strategies.
        
        Returns:
            Dictionary with strategy comparison data
        
        Example:
            >>> comparison = dashboard.compare_strategies()
            >>> for strategy, metrics in comparison['strategies'].items():
            ...     print(f"{strategy}: {metrics['avg_time_ms']:.2f}ms")
        """
        strategy_comparison = defaultdict(lambda: {
            'count': 0,
            'successful': 0,
            'failed': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'times': [],
            'complexities': []
        })
        
        for m in self.proof_metrics:
            data = strategy_comparison[m.strategy]
            data['count'] += 1
            
            if m.success:
                data['successful'] += 1
            else:
                data['failed'] += 1
            
            if m.cache_hit:
                data['cache_hits'] += 1
            else:
                data['cache_misses'] += 1
            
            data['times'].append(m.proof_time_ms)
            data['complexities'].append(m.formula_complexity)
        
        # Calculate aggregate metrics
        result = {'strategies': {}}
        
        for strategy, data in strategy_comparison.items():
            times = data['times']
            result['strategies'][strategy] = {
                'count': data['count'],
                'success_rate': data['successful'] / data['count'] if data['count'] > 0 else 0.0,
                'cache_hit_rate': data['cache_hits'] / data['count'] if data['count'] > 0 else 0.0,
                'avg_time_ms': statistics.mean(times) if times else 0.0,
                'median_time_ms': statistics.median(times) if times else 0.0,
                'min_time_ms': min(times) if times else 0.0,
                'max_time_ms': max(times) if times else 0.0,
                'avg_complexity': statistics.mean(data['complexities']) if data['complexities'] else 0.0,
            }
        
        return result
    
    def generate_html(self, output_path: str) -> None:
        """
        Generate interactive HTML dashboard with charts.
        
        Creates a standalone HTML file with:
        - Line charts for proof times over time
        - Bar charts for strategy comparison
        - Pie charts for cache hit/miss distribution
        - Histograms for proof time distribution
        - Tables with detailed statistics
        
        Args:
            output_path: Path to output HTML file
        
        Example:
            >>> dashboard.generate_html('performance_dashboard.html')
            >>> print("Dashboard saved to performance_dashboard.html")
        """
        stats = self.get_statistics()
        comparison = self.compare_strategies()
        
        # Generate HTML
        html = self._generate_html_content(stats, comparison)
        
        # Write to file
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(html, encoding='utf-8')
        
        logger.info(f"Generated HTML dashboard: {output_path}")
    
    def export_json(self, output_path: str) -> None:
        """
        Export all metrics and statistics to JSON file.
        
        The exported JSON includes:
        - All individual proof metrics
        - All time-series metrics
        - Aggregated statistics
        - Strategy comparison
        - Metadata (dashboard start time, export time, etc.)
        
        Args:
            output_path: Path to output JSON file
        
        Example:
            >>> dashboard.export_json('metrics.json')
            >>> # Can be imported into monitoring tools
        """
        stats = self.get_statistics()
        comparison = self.compare_strategies()
        
        export_data = {
            'metadata': {
                'dashboard_start_time': self.start_time,
                'dashboard_start_datetime': datetime.fromtimestamp(self.start_time).isoformat(),
                'export_time': time.time(),
                'export_datetime': datetime.now().isoformat(),
                'total_proofs': len(self.proof_metrics),
                'total_metrics': len(self.timeseries_metrics),
            },
            'statistics': stats,
            'strategy_comparison': comparison,
            'proof_metrics': [m.to_dict() for m in self.proof_metrics],
            'timeseries_metrics': [m.to_dict() for m in self.timeseries_metrics],
        }
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"Exported metrics to JSON: {output_path}")
    
    def clear(self) -> None:
        """Clear all recorded metrics and reset the dashboard."""
        self.proof_metrics.clear()
        self.timeseries_metrics.clear()
        self._stats_cache = None
        self._stats_cache_valid = False
        self.start_time = time.time()
        
        logger.info("Dashboard cleared")
    
    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    def _calculate_complexity(self, formula_str: str) -> int:
        """Calculate formula complexity (nesting depth)."""
        depth = 0
        max_depth = 0
        
        for char in formula_str:
            if char == '(':
                depth += 1
                max_depth = max(max_depth, depth)
            elif char == ')':
                depth -= 1
        
        return max_depth
    
    def _determine_formula_type(self, formula_str: str) -> str:
        """Determine formula type from string representation."""
        import re
        
        # Check for temporal operators first (most specific)
        temporal_ops = ['Always', 'Eventually', 'Until', 'Next']
        temporal_symbols = ['□', '◊']
        
        if any(op in formula_str for op in temporal_ops):
            return 'temporal'
        
        # Check for temporal/modal symbols early
        if any(symbol in formula_str for symbol in temporal_symbols):
            return 'temporal'
        
        # Check for deontic operators (very specific patterns)
        # Look for Obligatory, Permitted, Forbidden keywords
        deontic_keywords = ['Obligatory', 'Permitted', 'Forbidden']
        if any(keyword in formula_str for keyword in deontic_keywords):
            return 'deontic'
        
        # Check for single-letter deontic operators at start or after non-letter
        # O(...), P(...), F(...) but NOT P(x) where P is a predicate
        # Look for patterns like "O(" at start, after space, or after punctuation
        if re.search(r'(?:^|[^a-zA-Z])O\s*\(', formula_str):
            return 'deontic'
        # Be careful with P and F - only match if they look like modal operators
        # For now, just check O which is unambiguous
        
        # Check for modal operators (not temporal/deontic)
        modal_ops = ['Necessary', 'Possible']
        if any(op in formula_str for op in modal_ops):
            return 'modal'
        
        # Default to propositional
        return 'propositional'
    
    def _generate_html_content(
        self,
        stats: Dict[str, Any],
        comparison: Dict[str, Any]
    ) -> str:
        """Generate HTML dashboard content."""
        
        # Prepare data for charts
        proof_times_data = [
            {
                'x': datetime.fromtimestamp(m.timestamp).isoformat(),
                'y': m.proof_time_ms
            }
            for m in self.proof_metrics
        ]
        
        strategy_labels = list(comparison['strategies'].keys())
        strategy_times = [
            comparison['strategies'][s]['avg_time_ms']
            for s in strategy_labels
        ]
        strategy_success_rates = [
            comparison['strategies'][s]['success_rate'] * 100
            for s in strategy_labels
        ]
        
        # Proof time histogram
        histogram_bins = self._create_histogram_bins([m.proof_time_ms for m in self.proof_metrics])
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TDFOL Performance Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            padding: 20px;
            min-height: 100vh;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        header {{
            background: white;
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }}
        
        h1 {{
            color: #667eea;
            font-size: 2.5rem;
            margin-bottom: 10px;
        }}
        
        .subtitle {{
            color: #666;
            font-size: 1.1rem;
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        
        .stat-card {{
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            transition: transform 0.3s ease;
        }}
        
        .stat-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 10px 25px rgba(0,0,0,0.2);
        }}
        
        .stat-label {{
            color: #888;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }}
        
        .stat-value {{
            color: #667eea;
            font-size: 2.5rem;
            font-weight: bold;
        }}
        
        .stat-unit {{
            color: #888;
            font-size: 1rem;
            margin-left: 5px;
        }}
        
        .charts-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 30px;
            margin-bottom: 30px;
        }}
        
        .chart-container {{
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }}
        
        .chart-title {{
            color: #667eea;
            font-size: 1.3rem;
            margin-bottom: 20px;
            font-weight: 600;
        }}
        
        .chart-canvas {{
            position: relative;
            height: 300px;
        }}
        
        .table-container {{
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            margin-bottom: 30px;
            overflow-x: auto;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        
        th {{
            background: #667eea;
            color: white;
            padding: 15px;
            text-align: left;
            font-weight: 600;
        }}
        
        td {{
            padding: 12px 15px;
            border-bottom: 1px solid #eee;
        }}
        
        tr:hover {{
            background: #f8f9ff;
        }}
        
        .success {{
            color: #10b981;
            font-weight: 600;
        }}
        
        .failure {{
            color: #ef4444;
            font-weight: 600;
        }}
        
        footer {{
            text-align: center;
            color: white;
            margin-top: 50px;
            padding: 20px;
            opacity: 0.8;
        }}
        
        @media (max-width: 768px) {{
            .charts-grid {{
                grid-template-columns: 1fr;
            }}
            
            h1 {{
                font-size: 2rem;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🚀 TDFOL Performance Dashboard</h1>
            <p class="subtitle">Real-time theorem proving performance monitoring and analysis</p>
        </header>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Total Proofs</div>
                <div class="stat-value">{stats['total_proofs']}</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">Success Rate</div>
                <div class="stat-value">{stats['success_rate'] * 100:.1f}<span class="stat-unit">%</span></div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">Cache Hit Rate</div>
                <div class="stat-value">{stats['cache_hit_rate'] * 100:.1f}<span class="stat-unit">%</span></div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">Avg Proof Time</div>
                <div class="stat-value">{stats['timing']['avg_ms']:.1f}<span class="stat-unit">ms</span></div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">Median Time</div>
                <div class="stat-value">{stats['timing']['median_ms']:.1f}<span class="stat-unit">ms</span></div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">P95 Time</div>
                <div class="stat-value">{stats['timing']['p95_ms']:.1f}<span class="stat-unit">ms</span></div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">P99 Time</div>
                <div class="stat-value">{stats['timing']['p99_ms']:.1f}<span class="stat-unit">ms</span></div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">Cache Speedup</div>
                <div class="stat-value">{stats['avg_speedup_from_cache']:.1f}<span class="stat-unit">x</span></div>
            </div>
        </div>
        
        <div class="charts-grid">
            <div class="chart-container">
                <div class="chart-title">Proof Times Over Time</div>
                <div class="chart-canvas">
                    <canvas id="proofTimesChart"></canvas>
                </div>
            </div>
            
            <div class="chart-container">
                <div class="chart-title">Strategy Performance</div>
                <div class="chart-canvas">
                    <canvas id="strategyTimesChart"></canvas>
                </div>
            </div>
            
            <div class="chart-container">
                <div class="chart-title">Strategy Success Rates</div>
                <div class="chart-canvas">
                    <canvas id="strategySuccessChart"></canvas>
                </div>
            </div>
            
            <div class="chart-container">
                <div class="chart-title">Proof Time Distribution</div>
                <div class="chart-canvas">
                    <canvas id="histogramChart"></canvas>
                </div>
            </div>
            
            <div class="chart-container">
                <div class="chart-title">Cache Hit/Miss Distribution</div>
                <div class="chart-canvas">
                    <canvas id="cacheChart"></canvas>
                </div>
            </div>
            
            <div class="chart-container">
                <div class="chart-title">Formula Type Distribution</div>
                <div class="chart-canvas">
                    <canvas id="formulaTypeChart"></canvas>
                </div>
            </div>
        </div>
        
        <div class="table-container">
            <div class="chart-title">Strategy Comparison</div>
            <table>
                <thead>
                    <tr>
                        <th>Strategy</th>
                        <th>Count</th>
                        <th>Success Rate</th>
                        <th>Cache Hit Rate</th>
                        <th>Avg Time (ms)</th>
                        <th>Median Time (ms)</th>
                        <th>Min Time (ms)</th>
                        <th>Max Time (ms)</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(f'''
                    <tr>
                        <td><strong>{strategy}</strong></td>
                        <td>{data['count']}</td>
                        <td class="{'success' if data['success_rate'] > 0.8 else 'failure'}">{data['success_rate'] * 100:.1f}%</td>
                        <td>{data['cache_hit_rate'] * 100:.1f}%</td>
                        <td>{data['avg_time_ms']:.2f}</td>
                        <td>{data['median_time_ms']:.2f}</td>
                        <td>{data['min_time_ms']:.2f}</td>
                        <td>{data['max_time_ms']:.2f}</td>
                    </tr>
                    ''' for strategy, data in comparison['strategies'].items())}
                </tbody>
            </table>
        </div>
        
        <footer>
            <p>Generated by TDFOL Performance Dashboard</p>
            <p>Dashboard started: {datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </footer>
    </div>
    
    <script>
        // Configure Chart.js defaults
        Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
        Chart.defaults.color = '#666';
        
        // Proof times over time
        new Chart(document.getElementById('proofTimesChart'), {{
            type: 'line',
            data: {{
                datasets: [{{
                    label: 'Proof Time (ms)',
                    data: {json.dumps(proof_times_data)},
                    borderColor: '#667eea',
                    backgroundColor: 'rgba(102, 126, 234, 0.1)',
                    tension: 0.4,
                    fill: true
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    x: {{
                        type: 'time',
                        time: {{
                            unit: 'minute'
                        }},
                        title: {{
                            display: true,
                            text: 'Time'
                        }}
                    }},
                    y: {{
                        title: {{
                            display: true,
                            text: 'Time (ms)'
                        }},
                        beginAtZero: true
                    }}
                }},
                plugins: {{
                    legend: {{
                        display: false
                    }}
                }}
            }}
        }});
        
        // Strategy times comparison
        new Chart(document.getElementById('strategyTimesChart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(strategy_labels)},
                datasets: [{{
                    label: 'Avg Time (ms)',
                    data: {json.dumps(strategy_times)},
                    backgroundColor: [
                        'rgba(102, 126, 234, 0.8)',
                        'rgba(118, 75, 162, 0.8)',
                        'rgba(237, 100, 166, 0.8)',
                        'rgba(255, 154, 158, 0.8)',
                        'rgba(250, 208, 196, 0.8)'
                    ]
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    y: {{
                        beginAtZero: true,
                        title: {{
                            display: true,
                            text: 'Time (ms)'
                        }}
                    }}
                }},
                plugins: {{
                    legend: {{
                        display: false
                    }}
                }}
            }}
        }});
        
        // Strategy success rates
        new Chart(document.getElementById('strategySuccessChart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(strategy_labels)},
                datasets: [{{
                    label: 'Success Rate (%)',
                    data: {json.dumps(strategy_success_rates)},
                    backgroundColor: [
                        'rgba(16, 185, 129, 0.8)',
                        'rgba(59, 130, 246, 0.8)',
                        'rgba(249, 115, 22, 0.8)',
                        'rgba(239, 68, 68, 0.8)',
                        'rgba(168, 85, 247, 0.8)'
                    ]
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    y: {{
                        beginAtZero: true,
                        max: 100,
                        title: {{
                            display: true,
                            text: 'Success Rate (%)'
                        }}
                    }}
                }},
                plugins: {{
                    legend: {{
                        display: false
                    }}
                }}
            }}
        }});
        
        // Proof time histogram
        new Chart(document.getElementById('histogramChart'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps([f"{b['start']:.0f}-{b['end']:.0f}" for b in histogram_bins])},
                datasets: [{{
                    label: 'Frequency',
                    data: {json.dumps([b['count'] for b in histogram_bins])},
                    backgroundColor: 'rgba(102, 126, 234, 0.8)'
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    x: {{
                        title: {{
                            display: true,
                            text: 'Proof Time Range (ms)'
                        }}
                    }},
                    y: {{
                        beginAtZero: true,
                        title: {{
                            display: true,
                            text: 'Count'
                        }}
                    }}
                }},
                plugins: {{
                    legend: {{
                        display: false
                    }}
                }}
            }}
        }});
        
        // Cache distribution
        new Chart(document.getElementById('cacheChart'), {{
            type: 'doughnut',
            data: {{
                labels: ['Cache Hits', 'Cache Misses'],
                datasets: [{{
                    data: [{stats['cache_hits']}, {stats['cache_misses']}],
                    backgroundColor: [
                        'rgba(16, 185, 129, 0.8)',
                        'rgba(239, 68, 68, 0.8)'
                    ]
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        position: 'bottom'
                    }}
                }}
            }}
        }});
        
        // Formula type distribution
        new Chart(document.getElementById('formulaTypeChart'), {{
            type: 'pie',
            data: {{
                labels: {json.dumps(list(stats['formula_types']['counts'].keys()))},
                datasets: [{{
                    data: {json.dumps(list(stats['formula_types']['counts'].values()))},
                    backgroundColor: [
                        'rgba(102, 126, 234, 0.8)',
                        'rgba(118, 75, 162, 0.8)',
                        'rgba(237, 100, 166, 0.8)',
                        'rgba(255, 154, 158, 0.8)'
                    ]
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{
                        position: 'bottom'
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>"""
        
        return html
    
    def _create_histogram_bins(
        self,
        values: List[float],
        num_bins: int = 10
    ) -> List[Dict[str, Any]]:
        """Create histogram bins from values."""
        if not values:
            return []
        
        min_val = min(values)
        max_val = max(values)
        
        if min_val == max_val:
            return [{'start': min_val, 'end': max_val, 'count': len(values)}]
        
        bin_width = (max_val - min_val) / num_bins
        bins = []
        
        for i in range(num_bins):
            bin_start = min_val + i * bin_width
            bin_end = bin_start + bin_width
            
            count = sum(1 for v in values if bin_start <= v < bin_end)
            
            # Include max value in last bin
            if i == num_bins - 1:
                count += sum(1 for v in values if v == max_val)
            
            bins.append({
                'start': bin_start,
                'end': bin_end,
                'count': count
            })
        
        return bins


# ============================================================================
# Global Dashboard Instance
# ============================================================================


_global_dashboard: Optional[PerformanceDashboard] = None


def get_global_dashboard() -> PerformanceDashboard:
    """
    Get or create the global performance dashboard instance.
    
    Returns:
        Global PerformanceDashboard instance
    
    Example:
        >>> dashboard = get_global_dashboard()
        >>> dashboard.record_proof(result)
    """
    global _global_dashboard
    if _global_dashboard is None:
        _global_dashboard = PerformanceDashboard()
    return _global_dashboard


def reset_global_dashboard() -> None:
    """Reset the global performance dashboard."""
    global _global_dashboard
    if _global_dashboard is not None:
        _global_dashboard.clear()
    else:
        _global_dashboard = PerformanceDashboard()


__all__ = [
    'PerformanceDashboard',
    'ProofMetrics',
    'TimeSeriesMetric',
    'AggregatedStats',
    'MetricType',
    'get_global_dashboard',
    'reset_global_dashboard',
]
