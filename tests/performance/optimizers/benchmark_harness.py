"""Benchmark harness for measuring GraphRAG optimization improvements.

This module provides infrastructure for:
- Running extraction and critic benchmarks across standard datasets
- Collecting performance metrics (latency, memory, throughput, accuracy)
- Comparing results across optimization implementations
- Generating benchmark reports

Usage::

    from benchmark_harness import BenchmarkHarness, BenchmarkConfig
    from benchmark_datasets import BenchmarkDataset
    
    # Configure benchmark
    config = BenchmarkConfig(
        domains=["legal", "medical"],
        complexities=["simple", "medium", "complex"],
        runs_per_variant=3,
        measure_memory=True,
        measure_accuracy=True,
    )
    
    # Run benchmark
    harness = BenchmarkHarness(config)
    results = harness.run_all()
    
    # Generate report
    harness.write_report("benchmark_results.json")
    harness.print_summary()
"""
from __future__ import annotations

import json
import time
import psutil
import os
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any, Callable
from pathlib import Path
import gc


@dataclass
class BenchmarkConfig:
    """Configuration for benchmark runs."""
    
    domains: List[str] = field(default_factory=lambda: ["legal", "medical"])
    complexities: List[str] = field(default_factory=lambda: ["simple", "medium", "complex"])
    runs_per_variant: int = 3
    measure_memory: bool = True
    measure_accuracy: bool = True
    warmup_runs: int = 1
    timeout_seconds: float = 300.0


@dataclass
class MetricPoint:
    """Single measurement of a metric."""
    
    value: float
    unit: str
    timestamp: float  # Unix timestamp


@dataclass
class BenchmarkMetrics:
    """Collected metrics for a single benchmark run."""
    
    # Timing metrics
    latency_ms: float  # Total execution time in milliseconds
    latency_min_ms: float = 0.0
    latency_max_ms: float = 0.0
    
    # Memory metrics  
    memory_peak_mb: float = 0.0
    memory_avg_mb: float = 0.0
    memory_delta_mb: float = 0.0  # Peak - baseline
    
    # Extraction metrics
    entity_count: int = 0
    relationship_count: int = 0
    entities_per_ms: float = 0.0  # Throughput
    
    # Quality metrics
    accuracy_score: float = 0.0  # 0-1 if measured
    confidence_avg: float = 0.0
    
    # Resource tracking
    cpu_percent: float = 0.0
    gc_collections: int = 0
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BenchmarkMetrics":
        """Deserialize from dictionary."""
        # Filter to only known fields
        field_names = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in field_names}
        return cls(**filtered)


@dataclass
class BenchmarkRun:
    """A single benchmark execution result."""
    
    config: Dict[str, Any]  # Benchmark configuration
    domain: str             # Legal, medical, technical, financial
    complexity: str         # simple, medium, complex
    dataset_tokens: int     # Size of test input
    metrics: BenchmarkMetrics
    run_number: int         # 1, 2, 3... for multi-run averaging
    variant_name: str       # e.g., "optimized_v1", "baseline"
    timestamp: float        # When run occurred
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "config": self.config,
            "domain": self.domain,
            "complexity": self.complexity,
            "dataset_tokens": self.dataset_tokens,
            "metrics": asdict(self.metrics),
            "run_number": self.run_number,
            "variant_name": self.variant_name,
            "timestamp": self.timestamp,
        }


@dataclass  
class BenchmarkResult:
    """Aggregated results across multiple runs."""
    
    domain: str
    complexity: str
    variant: str
    dataset_tokens: int
    
    # Aggregated metrics
    latency_avg_ms: float
    latency_std_ms: float
    latency_min_ms: float
    latency_max_ms: float
    
    memory_peak_avg_mb: float
    memory_peak_std_mb: float
    
    entity_count_avg: float
    throughput_entities_per_sec: float
    
    accuracy_avg: float = 0.0
    confidence_avg: float = 0.0
    
    # Metadata
    run_count: int = 1
    total_runs_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)


class BenchmarkHarness:
    """Main benchmark harness for running and collecting metrics."""
    
    def __init__(
        self,
        config: Optional[BenchmarkConfig] = None,
        variant_name: str = "baseline",
    ):
        """Initialize benchmark harness.
        
        Args:
            config: Benchmark configuration
            variant_name: Name for this variant (e.g., "optimized_v1")
        """
        self.config = config or BenchmarkConfig()
        self.variant_name = variant_name
        self.runs: List[BenchmarkRun] = []
        self.results: Dict[str, BenchmarkResult] = {}
        
    def measure_extraction(
        self,
        dataset,
        extraction_fn: Callable,
    ) -> BenchmarkMetrics:
        """Measure performance of extraction function.
        
        Args:
            dataset: BenchmarkDataset instance
            extraction_fn: Function(text, context) -> result with .entity_count, .relationship_count
            
        Returns:
            BenchmarkMetrics with measurements
        """
        gc.collect()
        process = psutil.Process(os.getpid())
        
        # Baseline memory
        mem_before = process.memory_info().rss / 1024 / 1024  # MB
        
        # Warmup run (not measured)
        try:
            for _ in range(self.config.warmup_runs):
                extraction_fn(dataset.text)
        except Exception:
            pass  # Tolerate warmup failures
        
        gc.collect()
        mem_baseline = process.memory_info().rss / 1024 / 1024  # MB
        
        # Measured runs
        latencies = []
        memory_samples = []
        result = None
        
        try:
            for _ in range(self.config.runs_per_variant):
                gc.collect()
                
                start_time = time.perf_counter()
                start_mem = process.memory_info().rss / 1024 / 1024
                
                result = extraction_fn(dataset.text)
                
                elapsed = (time.perf_counter() - start_time) * 1000  # ms
                end_mem = process.memory_info().rss / 1024 / 1024
                
                latencies.append(elapsed)
                memory_samples.append(end_mem)
                
                if elapsed > self.config.timeout_seconds * 1000:
                    break  # Timeout
        except Exception as e:
            # Benchmark failed - still return metrics with what we have
            pass
        
        # Compute statistics
        latency_avg = sum(latencies) / len(latencies) if latencies else 0.0
        latency_min = min(latencies) if latencies else 0.0
        latency_max = max(latencies) if latencies else 0.0
        
        memory_peak = max(memory_samples) if memory_samples else mem_baseline
        memory_avg = sum(memory_samples) / len(memory_samples) if memory_samples else mem_baseline
        memory_delta = max(0, memory_peak - mem_baseline)
        
        # Extract result metrics
        entity_count = 0
        relationship_count = 0
        if result and hasattr(result, 'entity_count'):
            entity_count = result.entity_count
        if result and hasattr(result, 'relationship_count'):
            relationship_count = result.relationship_count
        
        # Calculate throughput (entities per millisecond)
        entities_per_ms = entity_count / latency_avg if latency_avg > 0 else 0.0
        
        metrics = BenchmarkMetrics(
            latency_ms=latency_avg,
            latency_min_ms=latency_min,
            latency_max_ms=latency_max,
            memory_peak_mb=memory_peak,
            memory_avg_mb=memory_avg,
            memory_delta_mb=memory_delta,
            entity_count=entity_count,
            relationship_count=relationship_count,
            entities_per_ms=entities_per_ms,
            cpu_percent=process.cpu_percent(interval=0.1),
            gc_collections=gc.get_count()[0],
        )
        
        return metrics
    
    def run_single_benchmark(
        self,
        domain: str,
        complexity: str,
        extraction_fn: Callable,
        run_number: int = 1,
    ) -> BenchmarkRun:
        """Run a single benchmark.
        
        Args:
            domain: Dataset domain
            complexity: Dataset complexity
            extraction_fn: Function to benchmark
            run_number: Run iteration number
            
        Returns:
            BenchmarkRun with results
        """
        # Load dataset
        from benchmark_datasets import BenchmarkDataset
        try:
            dataset = BenchmarkDataset.load(domain, complexity)
        except Exception as e:
            # Dataset load failed, return empty result
            return BenchmarkRun(
                config={"domain": domain, "complexity": complexity},
                domain=domain,
                complexity=complexity,
                dataset_tokens=0,
                metrics=BenchmarkMetrics(latency_ms=0),
                run_number=run_number,
                variant_name=self.variant_name,
                timestamp=time.time(),
            )
        
        # Measure extraction
        metrics = self.measure_extraction(dataset, extraction_fn)
        
        # Create result
        run = BenchmarkRun(
            config={
                "domain": domain,
                "complexity": complexity,
                "variant": self.variant_name,
            },
            domain=domain,
            complexity=complexity,
            dataset_tokens=dataset.token_count,
            metrics=metrics,
            run_number=run_number,
            variant_name=self.variant_name,
            timestamp=time.time(),
        )
        
        self.runs.append(run)
        return run
    
    def run_all(
        self,
        extraction_fn: Callable,
    ) -> List[BenchmarkRun]:
        """Run all configured benchmarks.
        
        Args:
            extraction_fn: Function(text) -> result with entity_count, relationship_count
            
        Returns:
            List of BenchmarkRun results
        """
        for domain in self.config.domains:
            for complexity in self.config.complexities:
                for run_num in range(1, self.config.runs_per_variant + 1):
                    try:
                        self.run_single_benchmark(
                            domain, complexity, extraction_fn, run_num
                        )
                    except Exception:
                        pass  # Continue with other benchmarks
        
        self._aggregate_results()
        return self.runs
    
    def _aggregate_results(self) -> None:
        """Aggregate runs into summary results."""
        from statistics import mean, stdev
        
        # Group by (domain, complexity, variant)
        groups: Dict[tuple, List[BenchmarkRun]] = {}
        for run in self.runs:
            key = (run.domain, run.complexity, run.variant_name)
            if key not in groups:
                groups[key] = []
            groups[key].append(run)
        
        # Aggregate each group
        for (domain, complexity, variant), runs in groups.items():
            if not runs:
                continue
            
            latencies = [r.metrics.latency_ms for r in runs]
            memories = [r.metrics.memory_peak_mb for r in runs]
            entity_counts = [r.metrics.entity_count for r in runs]
            throughputs = [r.metrics.entities_per_ms for r in runs]
            
            latency_std = stdev(latencies) if len(latencies) > 1 else 0.0
            memory_std = stdev(memories) if len(memories) > 1 else 0.0
            
            result = BenchmarkResult(
                domain=domain,
                complexity=complexity,
                variant=variant,
                dataset_tokens=runs[0].dataset_tokens,  # Same for all runs
                latency_avg_ms=mean(latencies),
                latency_std_ms=latency_std,
                latency_min_ms=min(latencies),
                latency_max_ms=max(latencies),
                memory_peak_avg_mb=mean(memories),
                memory_peak_std_mb=memory_std,
                entity_count_avg=mean(entity_counts) if entity_counts else 0.0,
                throughput_entities_per_sec=mean(throughputs) * 1000 if throughputs else 0.0,
                run_count=len(runs),
                total_runs_seconds=sum(r.metrics.latency_ms for r in runs) / 1000,
            )
            
            key_str = f"{domain}_{complexity}"
            self.results[key_str] = result
    
    def write_report(self, filepath: str) -> None:
        """Write benchmark results to JSON file.
        
        Args:
            filepath: Output JSON file path
        """
        report = {
            "variant": self.variant_name,
            "timestamp": time.time(),
            "config": asdict(self.config),
            "runs": [r.to_dict() for r in self.runs],
            "aggregated_results": {k: v.to_dict() for k, v in self.results.items()},
        }
        
        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2)
    
    def print_summary(self) -> None:
        """Print summary of benchmark results."""
        print(f"\n{'='*80}")
        print(f"Benchmark Results - Variant: {self.variant_name}")
        print(f"{'='*80}\n")
        
        if not self.results:
            print("No results to display.")
            return
        
        # Header
        print(f"{'Domain':<12} {'Complexity':<12} {'Tokens':<10} {'Latency (ms)':<15} "
              f"{'Entities':<10} {'Throughput':<15}")
        print("-" * 80)
        
        for key in sorted(self.results.keys()):
            result = self.results[key]
            print(f"{result.domain:<12} {result.complexity:<12} {result.dataset_tokens:<10} "
                  f"{result.latency_avg_ms:>8.2f}±{result.latency_std_ms:<5.2f} "
                  f"{result.entity_count_avg:>8.0f}  "
                  f"{result.throughput_entities_per_sec:>12.0f}/s")
        
        print(f"\n{'='*80}\n")


class BenchmarkComparator:
    """Compare results between two benchmark variants."""
    
    @staticmethod
    def compare_variants(
        baseline_file: str,
        optimized_file: str,
    ) -> Dict[str, Any]:
        """Compare two benchmark result files.
        
        Args:
            baseline_file: Path to baseline results JSON
            optimized_file: Path to optimized results JSON
            
        Returns:
            Dict with delta comparisons
        """
        with open(baseline_file) as f:
            baseline = json.load(f)
        with open(optimized_file) as f:
            optimized = json.load(f)
        
        comparisons = {}
        
        baseline_results = baseline.get("aggregated_results", {})
        optimized_results = optimized.get("aggregated_results", {})
        
        for key in baseline_results.keys():
            if key not in optimized_results:
                continue
            
            base = baseline_results[key]
            opt = optimized_results[key]
            
            # Calculate improvements
            latency_improvement = (
                (base["latency_avg_ms"] - opt["latency_avg_ms"]) / base["latency_avg_ms"] * 100
            ) if base["latency_avg_ms"] > 0 else 0.0
            
            memory_improvement = (
                (base["memory_peak_avg_mb"] - opt["memory_peak_avg_mb"]) / base["memory_peak_avg_mb"] * 100
            ) if base["memory_peak_avg_mb"] > 0 else 0.0
            
            throughput_improvement = (
                (opt["throughput_entities_per_sec"] - base["throughput_entities_per_sec"]) / 
                base["throughput_entities_per_sec"] * 100
            ) if base["throughput_entities_per_sec"] > 0 else 0.0
            
            comparisons[key] = {
                "latency_ms_baseline": base["latency_avg_ms"],
                "latency_ms_optimized": opt["latency_avg_ms"],
                "latency_improvement_percent": latency_improvement,
                "memory_mb_baseline": base["memory_peak_avg_mb"],
                "memory_mb_optimized": opt["memory_peak_avg_mb"],
                "memory_improvement_percent": memory_improvement,
                "throughput_improvement_percent": throughput_improvement,
            }
        
        return {
            "baseline_variant": baseline.get("variant", "unknown"),
            "optimized_variant": optimized.get("variant", "unknown"),
            "comparisons": comparisons,
        }
    
    @staticmethod
    def print_comparison(comparison: Dict[str, Any]) -> None:
        """Print comparison results.
        
        Args:
            comparison: Comparison dict from compare_variants()
        """
        print(f"\n{'='*100}")
        print(f"Benchmark Comparison")
        print(f"Baseline: {comparison['baseline_variant']} → Optimized: {comparison['optimized_variant']}")
        print(f"{'='*100}\n")
        
        print(f"{'Variant':<20} {'Latency Improvement':<20} {'Memory Improvement':<20} "
              f"{'Throughput Improvement':<20}")
        print("-" * 100)
        
        for key, deltas in comparison["comparisons"].items():
            print(f"{key:<20} {deltas['latency_improvement_percent']:>+7.1f}%          "
                  f"{deltas['memory_improvement_percent']:>+7.1f}%           "
                  f"{deltas['throughput_improvement_percent']:>+7.1f}%")
        
        print(f"\n{'='*100}\n")
