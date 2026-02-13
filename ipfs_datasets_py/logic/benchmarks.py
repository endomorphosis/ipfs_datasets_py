"""
Performance benchmarking suite for logic modules.

Benchmarks:
- FOL conversion performance
- Proof execution speed
- Cache effectiveness
- Batch processing throughput
- Memory usage
"""

import time
import asyncio
import statistics
from typing import List, Dict, Any, Callable
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Result from a single benchmark run."""
    name: str
    description: str
    iterations: int
    total_time: float
    mean_time: float
    median_time: float
    std_dev: float
    min_time: float
    max_time: float
    throughput: float  # operations per second
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "iterations": self.iterations,
            "total_time": self.total_time,
            "mean_time": self.mean_time,
            "median_time": self.median_time,
            "std_dev": self.std_dev,
            "min_time": self.min_time,
            "max_time": self.max_time,
            "throughput": self.throughput,
            "metadata": self.metadata,
        }
    
    def summary(self) -> str:
        """Get human-readable summary."""
        return (
            f"{self.name}: {self.mean_time*1000:.2f}ms avg, "
            f"{self.throughput:.1f} ops/sec, "
            f"σ={self.std_dev*1000:.2f}ms"
        )


class PerformanceBenchmark:
    """Performance benchmarking framework."""
    
    def __init__(self, warmup_iterations: int = 3):
        """
        Initialize benchmark framework.
        
        Args:
            warmup_iterations: Number of warmup runs before timing
        """
        self.warmup_iterations = warmup_iterations
        self.results: List[BenchmarkResult] = []
    
    def benchmark(
        self,
        name: str,
        func: Callable,
        iterations: int = 100,
        description: str = "",
        **kwargs
    ) -> BenchmarkResult:
        """
        Benchmark a synchronous function.
        
        Args:
            name: Benchmark name
            func: Function to benchmark
            iterations: Number of iterations
            description: Description of benchmark
            **kwargs: Arguments to pass to function
            
        Returns:
            BenchmarkResult with timing statistics
        """
        # Warmup
        for _ in range(self.warmup_iterations):
            func(**kwargs)
        
        # Actual benchmark
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            func(**kwargs)
            end = time.perf_counter()
            times.append(end - start)
        
        result = self._create_result(name, description, iterations, times)
        self.results.append(result)
        logger.info(f"Benchmark completed: {result.summary()}")
        
        return result
    
    async def benchmark_async(
        self,
        name: str,
        func: Callable,
        iterations: int = 100,
        description: str = "",
        **kwargs
    ) -> BenchmarkResult:
        """
        Benchmark an asynchronous function.
        
        Args:
            name: Benchmark name
            func: Async function to benchmark
            iterations: Number of iterations
            description: Description of benchmark
            **kwargs: Arguments to pass to function
            
        Returns:
            BenchmarkResult with timing statistics
        """
        # Warmup
        for _ in range(self.warmup_iterations):
            await func(**kwargs)
        
        # Actual benchmark
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            await func(**kwargs)
            end = time.perf_counter()
            times.append(end - start)
        
        result = self._create_result(name, description, iterations, times)
        self.results.append(result)
        logger.info(f"Benchmark completed: {result.summary()}")
        
        return result
    
    def _create_result(
        self,
        name: str,
        description: str,
        iterations: int,
        times: List[float]
    ) -> BenchmarkResult:
        """Create BenchmarkResult from timing data."""
        total = sum(times)
        mean = statistics.mean(times)
        median = statistics.median(times)
        std_dev = statistics.stdev(times) if len(times) > 1 else 0.0
        
        return BenchmarkResult(
            name=name,
            description=description,
            iterations=iterations,
            total_time=total,
            mean_time=mean,
            median_time=median,
            std_dev=std_dev,
            min_time=min(times),
            max_time=max(times),
            throughput=iterations / total if total > 0 else 0.0,
        )
    
    def compare(self, result1: BenchmarkResult, result2: BenchmarkResult) -> Dict[str, Any]:
        """
        Compare two benchmark results.
        
        Args:
            result1: First benchmark result
            result2: Second benchmark result
            
        Returns:
            Dictionary with comparison metrics
        """
        speedup = result2.mean_time / result1.mean_time if result1.mean_time > 0 else 0.0
        improvement = ((result2.mean_time - result1.mean_time) / result2.mean_time * 100) if result2.mean_time > 0 else 0.0
        
        return {
            "baseline": result1.name,
            "comparison": result2.name,
            "speedup": speedup,
            "improvement_percent": improvement,
            "baseline_mean": result1.mean_time,
            "comparison_mean": result2.mean_time,
            "faster": result1.name if result1.mean_time < result2.mean_time else result2.name,
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary of all benchmarks.
        
        Returns:
            Dictionary with summary statistics
        """
        if not self.results:
            return {"error": "No benchmark results"}
        
        return {
            "total_benchmarks": len(self.results),
            "results": [r.to_dict() for r in self.results],
            "fastest": min(self.results, key=lambda r: r.mean_time).name,
            "slowest": max(self.results, key=lambda r: r.mean_time).name,
        }
    
    def print_summary(self) -> None:
        """Print human-readable summary of benchmarks."""
        if not self.results:
            print("No benchmark results yet.")
            return
        
        print("\n" + "="*70)
        print("BENCHMARK SUMMARY")
        print("="*70)
        
        for result in self.results:
            print(f"\n{result.name}")
            print(f"  Description: {result.description}")
            print(f"  Iterations: {result.iterations}")
            print(f"  Mean time: {result.mean_time*1000:.2f} ms")
            print(f"  Median time: {result.median_time*1000:.2f} ms")
            print(f"  Std dev: {result.std_dev*1000:.2f} ms")
            print(f"  Min/Max: {result.min_time*1000:.2f} / {result.max_time*1000:.2f} ms")
            print(f"  Throughput: {result.throughput:.1f} ops/sec")
        
        print("\n" + "="*70)
        print(f"Fastest: {min(self.results, key=lambda r: r.mean_time).name}")
        print(f"Slowest: {max(self.results, key=lambda r: r.mean_time).name}")
        print("="*70 + "\n")


# Pre-defined benchmark suites
class FOLBenchmarks:
    """Benchmark suite for FOL conversion."""
    
    @staticmethod
    async def benchmark_simple_conversion(benchmark: PerformanceBenchmark, use_nlp: bool = False):
        """Benchmark simple FOL conversion."""
        from ipfs_datasets_py.logic.fol.text_to_fol import convert_text_to_fol
        
        text = "All humans are mortal"
        
        result = await benchmark.benchmark_async(
            name=f"FOL Simple Conversion ({'NLP' if use_nlp else 'Regex'})",
            func=convert_text_to_fol,
            iterations=100,
            description="Convert simple sentence to FOL",
            text_input=text,
            use_nlp=use_nlp,
        )
        
        return result
    
    @staticmethod
    async def benchmark_complex_conversion(benchmark: PerformanceBenchmark, use_nlp: bool = False):
        """Benchmark complex FOL conversion."""
        from ipfs_datasets_py.logic.fol.text_to_fol import convert_text_to_fol
        
        text = "If all humans are mortal and Socrates is a human, then Socrates is mortal"
        
        result = await benchmark.benchmark_async(
            name=f"FOL Complex Conversion ({'NLP' if use_nlp else 'Regex'})",
            func=convert_text_to_fol,
            iterations=50,
            description="Convert complex sentence with nested logic",
            text_input=text,
            use_nlp=use_nlp,
        )
        
        return result
    
    @staticmethod
    async def benchmark_batch_conversion(benchmark: PerformanceBenchmark, batch_size: int = 10):
        """Benchmark batch FOL conversion."""
        from ipfs_datasets_py.logic.fol.text_to_fol import convert_text_to_fol
        
        texts = [
            "All dogs are animals",
            "Some cats are black",
            "If it rains, the ground gets wet",
            "Birds can fly",
            "Fish live in water",
        ] * (batch_size // 5)
        
        async def batch_convert():
            results = []
            for text in texts:
                result = await convert_text_to_fol(text)
                results.append(result)
            return results
        
        result = await benchmark.benchmark_async(
            name=f"FOL Batch Conversion ({batch_size} items)",
            func=batch_convert,
            iterations=10,
            description=f"Batch convert {batch_size} sentences",
        )
        
        return result


class CacheBenchmarks:
    """Benchmark suite for proof caching."""
    
    @staticmethod
    def benchmark_cache_hit(benchmark: PerformanceBenchmark):
        """Benchmark cache hit performance."""
        from ipfs_datasets_py.logic.integration.proof_cache import ProofCache
        
        cache = ProofCache(max_size=1000)
        cache.put("test_formula", "z3", {"result": "proven"})
        
        result = benchmark.benchmark(
            name="Cache Hit",
            func=lambda: cache.get("test_formula", "z3"),
            iterations=10000,
            description="Retrieve cached proof result",
        )
        
        return result
    
    @staticmethod
    def benchmark_cache_miss(benchmark: PerformanceBenchmark):
        """Benchmark cache miss performance."""
        from ipfs_datasets_py.logic.integration.proof_cache import ProofCache
        
        cache = ProofCache(max_size=1000)
        
        result = benchmark.benchmark(
            name="Cache Miss",
            func=lambda: cache.get("nonexistent", "z3"),
            iterations=10000,
            description="Check for non-existent cache entry",
        )
        
        return result


async def run_comprehensive_benchmarks() -> Dict[str, Any]:
    """
    Run comprehensive benchmark suite.
    
    Returns:
        Summary of all benchmark results
    """
    benchmark = PerformanceBenchmark(warmup_iterations=3)
    
    logger.info("Starting comprehensive benchmarks...")
    
    # FOL benchmarks
    await FOLBenchmarks.benchmark_simple_conversion(benchmark, use_nlp=False)
    await FOLBenchmarks.benchmark_simple_conversion(benchmark, use_nlp=True)
    await FOLBenchmarks.benchmark_complex_conversion(benchmark, use_nlp=False)
    await FOLBenchmarks.benchmark_batch_conversion(benchmark, batch_size=10)
    
    # Cache benchmarks
    CacheBenchmarks.benchmark_cache_hit(benchmark)
    CacheBenchmarks.benchmark_cache_miss(benchmark)
    
    # Print summary
    benchmark.print_summary()
    
    return benchmark.get_summary()


__all__ = [
    "BenchmarkResult",
    "PerformanceBenchmark",
    "FOLBenchmarks",
    "CacheBenchmarks",
    "run_comprehensive_benchmarks",
]
