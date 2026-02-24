"""Benchmark utilities for standardized performance reporting.

This module provides utilities for computing, formatting, and reporting performance
metrics from benchmark results, including relative deltas, percentage improvements,
and formatted result tables.

Usage:
    >>> baseline = 1000  # microseconds
    >>> optimized = 750  # microseconds
    >>> delta = compute_relative_delta(baseline, optimized)
    >>> print(f"Improvement: {delta.percent_improvement:.1f}%")
    Improvement: 25.0%
    
    >>> metrics = compute_benchmark_metrics(baseline=1000, optimized=800)
    >>> print(format_delta_report(metrics))
    Baseline: 1000.0 μs
    Optimized: 800.0 μs
    Improvement: 20.0%
    Speedup: 1.25x
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import statistics


@dataclass
class DeltaMetrics:
    """Standardized delta computation results.
    
    Attributes:
        baseline_value: Original unoptimized value
        optimized_value: Optimized value after improvements
        absolute_delta: baseline - optimized (positive = improvement)
        percent_improvement: (baseline - optimized) / baseline * 100
        speedup_factor: baseline / optimized
        is_improvement: True if optimized < baseline
    """
    baseline_value: float
    optimized_value: float
    absolute_delta: float
    percent_improvement: float
    speedup_factor: float
    is_improvement: bool


def compute_relative_delta(baseline: float, optimized: float) -> DeltaMetrics:
    """Compute standardized performance delta metrics.
    
    Args:
        baseline: Baseline (original) metric value.
        optimized: Optimized metric value.
        
    Returns:
        DeltaMetrics with computed deltas and ratios.
        
    Raises:
        ValueError: If baseline or optimized is <= 0.
    """
    if baseline <= 0 or optimized <= 0:
        raise ValueError(f"Values must be positive; got baseline={baseline}, optimized={optimized}")
    
    absolute_delta = baseline - optimized
    percent_improvement = (absolute_delta / baseline) * 100
    speedup_factor = baseline / optimized
    is_improvement = optimized < baseline
    
    return DeltaMetrics(
        baseline_value=baseline,
        optimized_value=optimized,
        absolute_delta=absolute_delta,
        percent_improvement=percent_improvement,
        speedup_factor=speedup_factor,
        is_improvement=is_improvement,
    )


def compute_benchmark_metrics(baseline: float, optimized: float) -> Dict[str, float]:
    """Compute performance metrics returning a dict (legacy compatibility).
    
    Args:
        baseline: Baseline metric value.
        optimized: Optimized metric value.
        
    Returns:
        Dict with keys: 'baseline', 'optimized', 'delta', 'percent_improvement', 'speedup'.
    """
    metrics = compute_relative_delta(baseline, optimized)
    return {
        'baseline': metrics.baseline_value,
        'optimized': metrics.optimized_value,
        'delta': metrics.absolute_delta,
        'percent_improvement': metrics.percent_improvement,
        'speedup': metrics.speedup_factor,
    }


def format_delta_report(metrics: DeltaMetrics, unit: str = "μs", precision: int = 1) -> str:
    """Format a delta metrics object as a human-readable report.
    
    Args:
        metrics: DeltaMetrics object to format.
        unit: Unit label for display (default: "μs" for microseconds).
        precision: Decimal places for percentage/speedup display.
        
    Returns:
        Multi-line formatted report string.
        
    Example:
        >>> metrics = compute_relative_delta(1000, 750)
        >>> print(format_delta_report(metrics))
        Baseline:     1000.0 μs
        Optimized:     750.0 μs
        Improvement:   250.0 μs (25.0%)
        Speedup:       1.3x
    """
    lines = [
        f"Baseline:     {metrics.baseline_value:.1f} {unit}",
        f"Optimized:    {metrics.optimized_value:.1f} {unit}",
        f"Improvement:  {metrics.absolute_delta:.1f} {unit} ({metrics.percent_improvement:.{precision}f}%)",
        f"Speedup:      {metrics.speedup_factor:.2f}x",
    ]
    if not metrics.is_improvement:
        lines.append("⚠️  Optimized is slower than baseline!")
    return "\n".join(lines)


def format_delta_inline(metrics: DeltaMetrics, precision: int = 1) -> str:
    """Format delta as a single-line inline string.
    
    Args:
        metrics: DeltaMetrics object to format.
        precision: Decimal places for percentage display.
        
    Returns:
        Single-line string like "-25.0% (1.3x speedup)".
    """
    if metrics.is_improvement:
        return f"-{metrics.percent_improvement:.{precision}f}% ({metrics.speedup_factor:.2f}x speedup)"
    else:
        return f"+{abs(metrics.percent_improvement):.{precision}f}% (slower by {1/metrics.speedup_factor:.2f}x)"


def aggregate_deltas(benchmark_results: List[Tuple[float, float]]) -> Dict[str, float]:
    """Aggregate multiple baseline/optimized pairs into average metrics.
    
    Args:
        benchmark_results: List of (baseline, optimized) tuples.
        
    Returns:
        Dict with aggregate stats: 'mean_percent_improvement', 'min_improvement',
        'max_improvement', 'mean_speedup', 'count'.
    """
    if not benchmark_results:
        raise ValueError("benchmark_results cannot be empty")
    
    deltas = [compute_relative_delta(b, o) for b, o in benchmark_results]
    percent_improvements = [d.percent_improvement for d in deltas]
    speedups = [d.speedup_factor for d in deltas]
    
    return {
        'mean_percent_improvement': statistics.mean(percent_improvements),
        'median_percent_improvement': statistics.median(percent_improvements),
        'min_improvement': min(percent_improvements),
        'max_improvement': max(percent_improvements),
        'mean_speedup': statistics.mean(speedups),
        'count': len(deltas),
    }


def format_benchmark_table(
    results: List[Dict],
    name_col: str = 'name',
    baseline_col: str = 'baseline',
    optimized_col: str = 'optimized',
    unit: str = 'μs',
    precision: int = 1,
) -> str:
    """Format a list of benchmark results as a markdown table with delta columns.
    
    Args:
        results: List of dicts with benchmark data. Each must have keys specified by
                 name_col, baseline_col, optimized_col.
        name_col: Key name for benchmark name/label.
        baseline_col: Key name for baseline metric.
        optimized_col: Key name for optimized metric.
        unit: Unit label for table display.
        precision: Decimal places for percentage display.
        
    Returns:
        Markdown-formatted table string.
        
    Example:
        >>> results = [
        ...     {'name': 'legal_small', 'baseline': 400, 'optimized': 260},
        ...     {'name': 'tech_medium', 'baseline': 1400, 'optimized': 920},
        ... ]
        >>> print(format_benchmark_table(results))
        | Benchmark | Baseline | Optimized | Improvement | Speedup |
        |-----------|----------|-----------|-------------|---------|
        | legal_small | 400.0 μs | 260.0 μs | -35.0% | 1.54x |
        | tech_medium | 1400.0 μs | 920.0 μs | -34.3% | 1.52x |
    """
    lines = [
        "| Benchmark | Baseline | Optimized | Improvement | Speedup |",
        "|-----------|----------|-----------|-------------|---------|",
    ]
    
    for row in results:
        name = row.get(name_col, "?")
        baseline = float(row.get(baseline_col, 0))
        optimized = float(row.get(optimized_col, 0))
        
        if baseline <= 0 or optimized <= 0:
            continue  # Skip invalid rows
        
        metrics = compute_relative_delta(baseline, optimized)
        improvement_pct = f"-{metrics.percent_improvement:.{precision}f}%" if metrics.is_improvement else f"+{abs(metrics.percent_improvement):.{precision}f}%"
        
        line = (
            f"| {name} | {baseline:.1f} {unit} | {optimized:.1f} {unit} | "
            f"{improvement_pct} | {metrics.speedup_factor:.2f}x |"
        )
        lines.append(line)
    
    return "\n".join(lines)


class BenchmarkReporter:
    """Standardized benchmark reporting helper (stateful).
    
    Accumulates results and produces formatted reports with consistent styling.
    
    Example:
        >>> reporter = BenchmarkReporter(unit="μs")
        >>> reporter.add_result("legal_small", baseline=400, optimized=265)
        >>> reporter.add_result("tech_medium", baseline=1400, optimized=920)
        >>> print(reporter.table())
        | Benchmark | Baseline | Optimized | Improvement | Speedup |
        ...
        >>> print(reporter.summary())
        Mean improvement: 34.6%
    """
    
    def __init__(self, unit: str = "μs", precision: int = 1):
        """Initialize reporter.
        
        Args:
            unit: Unit label for display (default: "μs").
            precision: Decimal places for percentage display.
        """
        self.unit = unit
        self.precision = precision
        self.results: List[Dict] = []
    
    def add_result(self, name: str, baseline: float, optimized: float) -> None:
        """Add a benchmark result.
        
        Args:
            name: Benchmark name/label.
            baseline: Baseline metric value.
            optimized: Optimized metric value.
        """
        self.results.append({
            'name': name,
            'baseline': baseline,
            'optimized': optimized,
        })
    
    def table(self) -> str:
        """Get results as a markdown table.
        
        Returns:
            Markdown-formatted table with delta columns.
        """
        return format_benchmark_table(
            self.results,
            unit=self.unit,
            precision=self.precision,
        )
    
    def summary(self) -> str:
        """Get aggregate statistics summary.
        
        Returns:
            Formatted summary string with mean, min, max improvements.
        """
        if not self.results:
            return "No results recorded."
        
        pairs = [(r['baseline'], r['optimized']) for r in self.results]
        agg = aggregate_deltas(pairs)
        
        lines = [
            f"Benchmark Summary ({len(self.results)} runs):",
            f"  Mean improvement: {agg['mean_percent_improvement']:.{self.precision}f}%",
            f"  Median improvement: {agg['median_percent_improvement']:.{self.precision}f}%",
            f"  Min improvement: {agg['min_improvement']:.{self.precision}f}%",
            f"  Max improvement: {agg['max_improvement']:.{self.precision}f}%",
            f"  Mean speedup: {agg['mean_speedup']:.2f}x",
        ]
        return "\n".join(lines)
    
    def detailed_report(self) -> str:
        """Get complete report with table and summary.
        
        Returns:
            Multi-line report with table and aggregate statistics.
        """
        return "\n".join([
            self.table(),
            "",
            self.summary(),
        ])


if __name__ == "__main__":
    # Example usage
    print("=== Single Result ===")
    metrics = compute_relative_delta(1000, 750)
    print(format_delta_report(metrics))
    print()
    
    print("=== Inline Format ===")
    print(f"Delta: {format_delta_inline(metrics)}")
    print()
    
    print("=== Table Format ===")
    results = [
        {'name': 'legal_small', 'baseline': 400, 'optimized': 260},
        {'name': 'legal_medium', 'baseline': 3200, 'optimized': 3150},
        {'name': 'tech_medium', 'baseline': 1400, 'optimized': 920},
        {'name': 'financial_medium', 'baseline': 10600, 'optimized': 7925},
    ]
    print(format_benchmark_table(results))
    print()
    
    print("=== Reporter ===")
    reporter = BenchmarkReporter()
    for r in results:
        reporter.add_result(r['name'], r['baseline'], r['optimized'])
    print(reporter.detailed_report())
