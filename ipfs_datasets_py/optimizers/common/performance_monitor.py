"""Performance monitoring dashboard for all optimizers.

This module provides comprehensive performance tracking and visualization
for optimization workflows, including LLM cache performance, validation
times, and overall optimization cycle metrics.

Features:
- Real-time performance metrics collection
- Dashboard visualization (text/markdown/HTML)
- Cache hit rate tracking
- Validation time analysis
- Optimization cycle profiling
- Export to JSON/CSV
"""

import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import statistics

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


@dataclass
class OptimizationCycleMetrics:
    """Metrics for a single optimization cycle.
    
    Attributes:
        cycle_id: Unique cycle identifier
        start_time: Cycle start timestamp
        end_time: Cycle end timestamp  
        duration: Total cycle duration in seconds
        llm_calls: Number of LLM API calls made
        llm_cache_hits: Number of cache hits
        llm_cache_misses: Number of cache misses
        validation_time: Time spent in validation
        validation_count: Number of validators run
        file_operations: Number of file I/O operations
        success: Whether cycle completed successfully
        error: Error message if failed
        metadata: Additional cycle metadata
    """
    cycle_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration: float = 0.0
    llm_calls: int = 0
    llm_cache_hits: int = 0
    llm_cache_misses: int = 0
    validation_time: float = 0.0
    validation_count: int = 0
    file_operations: int = 0
    success: bool = False
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def finalize(self) -> None:
        """Finalize cycle metrics."""
        if self.end_time is None:
            self.end_time = datetime.now()
        self.duration = (self.end_time - self.start_time).total_seconds()
    
    def __repr__(self) -> str:
        """Concise REPL-friendly representation."""
        status = "success" if self.success else "failed"
        cache_rate = 100 * self.llm_cache_hits / (self.llm_calls or 1)
        return (
            f"OptimizationCycleMetrics(id={self.cycle_id!r}, duration={self.duration:.2f}s, "
            f"llm_calls={self.llm_calls}, cache_rate={cache_rate:.1f}%, "
            f"validations={self.validation_count}, status={status})"
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self)
        result['start_time'] = self.start_time.isoformat()
        if self.end_time:
            result['end_time'] = self.end_time.isoformat()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OptimizationCycleMetrics":
        """Create from dictionary."""
        data = data.copy()
        data['start_time'] = datetime.fromisoformat(data['start_time'])
        if data.get('end_time'):
            data['end_time'] = datetime.fromisoformat(data['end_time'])
        return cls(**data)


class PerformanceMetricsCollector:
    """Collects and aggregates performance metrics across optimization cycles.
    
    This collector tracks:
    - LLM cache performance (hit rates, API reduction)
    - Validation performance (times, parallelization speedup)
    - Overall cycle performance (durations, success rates)
    - Resource utilization trends
    
    Example:
        >>> collector = PerformanceMetricsCollector()
        >>> cycle = collector.start_cycle("opt-001")
        >>> # ... perform optimization ...
        >>> collector.record_llm_call(cycle.cycle_id, cache_hit=True)
        >>> collector.end_cycle(cycle.cycle_id, success=True)
        >>> stats = collector.get_statistics()
    """
    
    def __init__(
        self,
        max_history: int = 1000,
        persistence_path: Optional[Path] = None,
    ):
        """Initialize metrics collector.
        
        Args:
            max_history: Maximum number of cycles to keep in memory
            persistence_path: Path to persist metrics (JSON)
        """
        self.max_history = max_history
        self.persistence_path = persistence_path
        
        # Active and completed cycles
        self._active_cycles: Dict[str, OptimizationCycleMetrics] = {}
        self._completed_cycles: deque = deque(maxlen=max_history)
        
        # Aggregate statistics
        self._total_llm_calls = 0
        self._total_cache_hits = 0
        self._total_validations = 0
        self._total_file_operations = 0
        
        # Load persisted metrics if available
        if persistence_path and persistence_path.exists():
            self._load_from_disk()
    
    def start_cycle(
        self,
        cycle_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> OptimizationCycleMetrics:
        """Start tracking a new optimization cycle.
        
        Args:
            cycle_id: Unique identifier for cycle
            metadata: Optional metadata to attach
            
        Returns:
            OptimizationCycleMetrics object for this cycle
        """
        cycle = OptimizationCycleMetrics(
            cycle_id=cycle_id,
            start_time=datetime.now(),
            metadata=metadata or {}
        )
        self._active_cycles[cycle_id] = cycle
        return cycle
    
    def end_cycle(
        self,
        cycle_id: str,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """End tracking for an optimization cycle.
        
        Args:
            cycle_id: Cycle identifier
            success: Whether cycle completed successfully
            error: Error message if failed
        """
        if cycle_id not in self._active_cycles:
            return
        
        cycle = self._active_cycles.pop(cycle_id)
        cycle.success = success
        cycle.error = error
        cycle.finalize()
        
        # Add to completed cycles
        self._completed_cycles.append(cycle)
        
        # Persist if configured
        if self.persistence_path:
            self._save_to_disk()
    
    def record_llm_call(
        self,
        cycle_id: str,
        cache_hit: bool,
    ) -> None:
        """Record an LLM API call.
        
        Args:
            cycle_id: Cycle identifier
            cache_hit: Whether this was a cache hit
        """
        if cycle_id in self._active_cycles:
            cycle = self._active_cycles[cycle_id]
            cycle.llm_calls += 1
            if cache_hit:
                cycle.llm_cache_hits += 1
                self._total_cache_hits += 1
            else:
                cycle.llm_cache_misses += 1
            self._total_llm_calls += 1
    
    def record_validation(
        self,
        cycle_id: str,
        duration: float,
        validator_count: int = 1,
    ) -> None:
        """Record validation metrics.
        
        Args:
            cycle_id: Cycle identifier
            duration: Validation duration in seconds
            validator_count: Number of validators run
        """
        if cycle_id in self._active_cycles:
            cycle = self._active_cycles[cycle_id]
            cycle.validation_time += duration
            cycle.validation_count += validator_count
            self._total_validations += validator_count
    
    def record_file_operation(self, cycle_id: str) -> None:
        """Record a file I/O operation.
        
        Args:
            cycle_id: Cycle identifier
        """
        if cycle_id in self._active_cycles:
            cycle = self._active_cycles[cycle_id]
            cycle.file_operations += 1
            self._total_file_operations += 1
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get aggregate performance statistics.
        
        Returns:
            Dictionary containing:
            - cycle_stats: Cycle duration statistics
            - cache_stats: LLM cache performance
            - validation_stats: Validation performance
            - overall_stats: Overall performance metrics
        """
        if not self._completed_cycles:
            return {
                "cycle_stats": {},
                "cache_stats": {},
                "validation_stats": {},
                "overall_stats": {
                    "total_cycles": 0,
                    "active_cycles": len(self._active_cycles),
                }
            }
        
        # Calculate cycle statistics
        durations = [c.duration for c in self._completed_cycles if c.success]
        cycle_stats = {}
        if durations:
            cycle_stats = {
                "mean_duration": statistics.mean(durations),
                "median_duration": statistics.median(durations),
                "min_duration": min(durations),
                "max_duration": max(durations),
                "stdev_duration": statistics.stdev(durations) if len(durations) > 1 else 0.0,
            }
        
        # Calculate cache statistics
        total_llm = sum(c.llm_calls for c in self._completed_cycles)
        total_hits = sum(c.llm_cache_hits for c in self._completed_cycles)
        total_misses = sum(c.llm_cache_misses for c in self._completed_cycles)
        
        cache_stats = {
            "total_llm_calls": total_llm,
            "cache_hits": total_hits,
            "cache_misses": total_misses,
            "hit_rate": total_hits / total_llm if total_llm > 0 else 0.0,
            "api_reduction": total_hits / total_llm if total_llm > 0 else 0.0,
            "estimated_cost_savings": f"{(total_hits / total_llm * 100):.1f}%" if total_llm > 0 else "0%",
        }
        
        # Calculate validation statistics
        validation_times = [c.validation_time for c in self._completed_cycles if c.validation_time > 0]
        validation_stats = {}
        if validation_times:
            validation_stats = {
                "mean_validation_time": statistics.mean(validation_times),
                "median_validation_time": statistics.median(validation_times),
                "total_validations": sum(c.validation_count for c in self._completed_cycles),
            }
        
        # Overall statistics
        success_count = sum(1 for c in self._completed_cycles if c.success)
        total_count = len(self._completed_cycles)
        
        overall_stats = {
            "total_cycles": total_count,
            "successful_cycles": success_count,
            "failed_cycles": total_count - success_count,
            "success_rate": success_count / total_count if total_count > 0 else 0.0,
            "active_cycles": len(self._active_cycles),
            "total_file_operations": sum(c.file_operations for c in self._completed_cycles),
        }
        
        return {
            "cycle_stats": cycle_stats,
            "cache_stats": cache_stats,
            "validation_stats": validation_stats,
            "overall_stats": overall_stats,
        }
    
    def get_recent_cycles(self, n: int = 10) -> List[OptimizationCycleMetrics]:
        """Get the N most recent completed cycles.
        
        Args:
            n: Number of cycles to return
            
        Returns:
            List of recent cycles
        """
        return list(self._completed_cycles)[-n:]
    
    def clear_history(self) -> None:
        """Clear all historical metrics."""
        self._completed_cycles.clear()
        self._total_llm_calls = 0
        self._total_cache_hits = 0
        self._total_validations = 0
        self._total_file_operations = 0
        
        if self.persistence_path and self.persistence_path.exists():
            self.persistence_path.unlink()
    
    def _save_to_disk(self) -> None:
        """Persist metrics to disk."""
        if not self.persistence_path:
            return
        
        data = {
            "cycles": [c.to_dict() for c in self._completed_cycles],
            "totals": {
                "llm_calls": self._total_llm_calls,
                "cache_hits": self._total_cache_hits,
                "validations": self._total_validations,
                "file_operations": self._total_file_operations,
            }
        }
        
        self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.persistence_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _load_from_disk(self) -> None:
        """Load metrics from disk."""
        if not self.persistence_path or not self.persistence_path.exists():
            return
        
        try:
            with open(self.persistence_path, 'r') as f:
                data = json.load(f)
            
            # Load cycles
            for cycle_data in data.get("cycles", []):
                cycle = OptimizationCycleMetrics.from_dict(cycle_data)
                self._completed_cycles.append(cycle)
            
            # Load totals
            totals = data.get("totals", {})
            self._total_llm_calls = totals.get("llm_calls", 0)
            self._total_cache_hits = totals.get("cache_hits", 0)
            self._total_validations = totals.get("validations", 0)
            self._total_file_operations = totals.get("file_operations", 0)
        except Exception as e:
            print(f"Warning: Failed to load metrics from disk: {e}")


class PerformanceDashboard:
    """Generate performance dashboards from metrics.
    
    This dashboard can generate:
    - Text summary for CLI output
    - Markdown report for documentation
    - HTML dashboard with charts (if matplotlib available)
    - JSON/CSV export for analysis
    
    Example:
        >>> collector = PerformanceMetricsCollector()
        >>> dashboard = PerformanceDashboard(collector)
        >>> print(dashboard.generate_text_summary())
        >>> dashboard.generate_html_dashboard("dashboard.html")
    """
    
    def __init__(self, collector: PerformanceMetricsCollector):
        """Initialize dashboard.
        
        Args:
            collector: PerformanceMetricsCollector instance
        """
        self.collector = collector
    
    def generate_text_summary(self) -> str:
        """Generate text summary of performance metrics.
        
        Returns:
            Formatted text summary
        """
        stats = self.collector.get_statistics()
        
        lines = []
        lines.append("=" * 60)
        lines.append("Performance Dashboard Summary")
        lines.append("=" * 60)
        lines.append("")
        
        # Overall stats
        overall = stats["overall_stats"]
        lines.append("Overall Performance:")
        lines.append(f"  Total Cycles: {overall['total_cycles']}")
        lines.append(f"  Successful: {overall['successful_cycles']}")
        lines.append(f"  Failed: {overall['failed_cycles']}")
        lines.append(f"  Success Rate: {overall['success_rate']:.1%}")
        lines.append(f"  Active Cycles: {overall['active_cycles']}")
        lines.append("")
        
        # Cycle stats
        cycle = stats.get("cycle_stats", {})
        if cycle:
            lines.append("Cycle Performance:")
            lines.append(f"  Mean Duration: {cycle['mean_duration']:.2f}s")
            lines.append(f"  Median Duration: {cycle['median_duration']:.2f}s")
            lines.append(f"  Min Duration: {cycle['min_duration']:.2f}s")
            lines.append(f"  Max Duration: {cycle['max_duration']:.2f}s")
            lines.append("")
        
        # Cache stats
        cache = stats.get("cache_stats", {})
        if cache:
            lines.append("LLM Cache Performance:")
            lines.append(f"  Total API Calls: {cache['total_llm_calls']}")
            lines.append(f"  Cache Hits: {cache['cache_hits']}")
            lines.append(f"  Cache Misses: {cache['cache_misses']}")
            lines.append(f"  Hit Rate: {cache['hit_rate']:.1%}")
            lines.append(f"  API Reduction: {cache['api_reduction']:.1%}")
            lines.append(f"  Cost Savings: {cache['estimated_cost_savings']}")
            lines.append("")
        
        # Validation stats
        validation = stats.get("validation_stats", {})
        if validation:
            lines.append("Validation Performance:")
            lines.append(f"  Mean Time: {validation['mean_validation_time']:.2f}s")
            lines.append(f"  Median Time: {validation['median_validation_time']:.2f}s")
            lines.append(f"  Total Validations: {validation['total_validations']}")
            lines.append("")
        
        lines.append("=" * 60)
        
        return "\n".join(lines)
    
    def generate_markdown_report(self) -> str:
        """Generate markdown report.
        
        Returns:
            Markdown formatted report
        """
        stats = self.collector.get_statistics()
        
        lines = []
        lines.append("# Performance Dashboard Report")
        lines.append("")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        
        # Overall stats table
        overall = stats["overall_stats"]
        lines.append("## Overall Performance")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total Cycles | {overall['total_cycles']} |")
        lines.append(f"| Successful | {overall['successful_cycles']} |")
        lines.append(f"| Failed | {overall['failed_cycles']} |")
        lines.append(f"| Success Rate | {overall['success_rate']:.1%} |")
        lines.append(f"| Active Cycles | {overall['active_cycles']} |")
        lines.append("")
        
        # Cycle stats
        cycle = stats.get("cycle_stats", {})
        if cycle:
            lines.append("## Cycle Performance")
            lines.append("")
            lines.append("| Metric | Duration (seconds) |")
            lines.append("|--------|-------------------|")
            lines.append(f"| Mean | {cycle['mean_duration']:.2f} |")
            lines.append(f"| Median | {cycle['median_duration']:.2f} |")
            lines.append(f"| Min | {cycle['min_duration']:.2f} |")
            lines.append(f"| Max | {cycle['max_duration']:.2f} |")
            lines.append(f"| Std Dev | {cycle['stdev_duration']:.2f} |")
            lines.append("")
        
        # Cache stats
        cache = stats.get("cache_stats", {})
        if cache:
            lines.append("## LLM Cache Performance")
            lines.append("")
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            lines.append(f"| Total API Calls | {cache['total_llm_calls']} |")
            lines.append(f"| Cache Hits | {cache['cache_hits']} |")
            lines.append(f"| Cache Misses | {cache['cache_misses']} |")
            lines.append(f"| Hit Rate | {cache['hit_rate']:.1%} |")
            lines.append(f"| API Reduction | {cache['api_reduction']:.1%} |")
            lines.append(f"| Cost Savings | {cache['estimated_cost_savings']} |")
            lines.append("")
        
        # Validation stats
        validation = stats.get("validation_stats", {})
        if validation:
            lines.append("## Validation Performance")
            lines.append("")
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            lines.append(f"| Mean Time | {validation['mean_validation_time']:.2f}s |")
            lines.append(f"| Median Time | {validation['median_validation_time']:.2f}s |")
            lines.append(f"| Total Validations | {validation['total_validations']} |")
            lines.append("")
        
        # Recent cycles
        recent = self.collector.get_recent_cycles(5)
        if recent:
            lines.append("## Recent Cycles")
            lines.append("")
            lines.append("| Cycle ID | Duration | LLM Calls | Cache Hits | Success |")
            lines.append("|----------|----------|-----------|------------|---------|")
            for cycle in recent:
                lines.append(
                    f"| {cycle.cycle_id} | {cycle.duration:.2f}s | "
                    f"{cycle.llm_calls} | {cycle.llm_cache_hits} | "
                    f"{'✓' if cycle.success else '✗'} |"
                )
            lines.append("")
        
        return "\n".join(lines)
    
    def export_json(self, output_path: Path) -> None:
        """Export metrics to JSON.
        
        Args:
            output_path: Output file path
        """
        stats = self.collector.get_statistics()
        recent = [c.to_dict() for c in self.collector.get_recent_cycles(100)]
        
        data = {
            "generated_at": datetime.now().isoformat(),
            "statistics": stats,
            "recent_cycles": recent,
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def export_csv(self, output_path: Path) -> None:
        """Export cycle metrics to CSV.
        
        Args:
            output_path: Output file path
        """
        if not PANDAS_AVAILABLE:
            raise ImportError("pandas is required for CSV export")
        
        cycles = self.collector.get_recent_cycles(1000)
        if not cycles:
            return
        
        # Convert to DataFrame
        data = []
        for cycle in cycles:
            row = {
                "cycle_id": cycle.cycle_id,
                "start_time": cycle.start_time.isoformat(),
                "duration": cycle.duration,
                "llm_calls": cycle.llm_calls,
                "cache_hits": cycle.llm_cache_hits,
                "cache_misses": cycle.llm_cache_misses,
                "validation_time": cycle.validation_time,
                "validation_count": cycle.validation_count,
                "file_operations": cycle.file_operations,
                "success": cycle.success,
            }
            data.append(row)
        
        df = pd.DataFrame(data)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)


# Global collector instance
_global_collector: Optional[PerformanceMetricsCollector] = None


def get_global_collector() -> PerformanceMetricsCollector:
    """Get or create global performance metrics collector.
    
    Returns:
        Global PerformanceMetricsCollector instance
    """
    global _global_collector
    if _global_collector is None:
        _global_collector = PerformanceMetricsCollector()
    return _global_collector


def set_global_collector(collector: PerformanceMetricsCollector) -> None:
    """Set global performance metrics collector.
    
    Args:
        collector: PerformanceMetricsCollector instance
    """
    global _global_collector
    _global_collector = collector
