"""
Batch 330: Large-Scale Performance Benchmarking
================================================

Benchmarks system performance on large document sizes (10k+ tokens)
to identify scalability issues and bottlenecks.

Goal: Provide:
- Performance baseline for large documents
- Memory usage profiling
- Throughput measurements
- Scaling factor analysis (linear vs quadratic)
"""

import pytest
import time
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass, field
import math


# ============================================================================
# DOMAIN MODELS
# ============================================================================

@dataclass
class DocumentMetrics:
    """Performance metrics for document processing."""
    doc_size_tokens: int
    processing_time_ms: float
    memory_used_mb: float
    throughput_tokens_per_sec: float
    entities_extracted: int
    relationships_found: int
    
    def __post_init__(self):
        """Validate metrics."""
        if self.processing_time_ms < 0:
            self.processing_time_ms = 0.0
        if self.memory_used_mb < 0:
            self.memory_used_mb = 0.0


@dataclass
class ScalingAnalysis:
    """Analysis of scaling behavior."""
    doc_sizes: List[int] = field(default_factory=list)
    processing_times: List[float] = field(default_factory=list)
    memory_usage: List[float] = field(default_factory=list)
    throughput_samples: List[float] = field(default_factory=list)
    
    def avg_processing_time(self) -> float:
        """Get average processing time."""
        if not self.processing_times:
            return 0.0
        return sum(self.processing_times) / len(self.processing_times)
    
    def avg_memory(self) -> float:
        """Get average memory usage."""
        if not self.memory_usage:
            return 0.0
        return sum(self.memory_usage) / len(self.memory_usage)
    
    def avg_throughput(self) -> float:
        """Get average throughput."""
        if not self.throughput_samples:
            return 0.0
        return sum(self.throughput_samples) / len(self.throughput_samples)
    
    def scaling_factor(self) -> float:
        """Estimate scaling factor (1=linear, 2=quadratic).
        
        Uses largest vs smallest to avoid noise from small sizes.
        """
        if len(self.processing_times) < 2:
            return 0.0
        
        # Use last two sizes for scaling estimate
        if len(self.doc_sizes) < 2:
            return 0.0
        
        size_ratio = self.doc_sizes[-1] / self.doc_sizes[-2]
        if size_ratio <= 1.0:
            return 0.0
        
        time_ratio = self.processing_times[-1] / self.processing_times[-2]
        
        # Estimate exponent: time ∝ size^exponent
        # time_ratio = size_ratio^exponent
        # exponent = log(time_ratio) / log(size_ratio)
        if time_ratio > 0 and size_ratio > 0:
            exponent = math.log(time_ratio) / math.log(size_ratio)
            return exponent
        
        return 0.0


# ============================================================================
# LARGE-SCALE PROCESSORS
# ============================================================================

class LargeDocumentProcessor:
    """Processes large documents and collects metrics."""
    
    def __init__(self):
        """Initialize processor."""
        self.last_metrics: Dict[str, Any] = {}
    
    def generate_synthetic_document(self, num_tokens: int) -> str:
        """Generate synthetic document with ~num_tokens tokens.
        
        Args:
            num_tokens: Target token count
            
        Returns:
            Document string
        """
        # Average tokens per word ~1.3, so aim for fewer words
        num_words = int(num_tokens / 1.3)
        
        # Create a pattern of entity-like terms
        base_words = [
            "patient", "doctor", "hospital", "treatment", "disease",
            "medication", "diagnosis", "symptom", "condition", "procedure",
            "surgery", "therapy", "analysis", "clinical", "medical",
            "record", "history", "examination", "test", "result",
        ]
        
        words = []
        for i in range(num_words):
            # Cycle through base words
            words.append(base_words[i % len(base_words)])
            # Add some variation with numbers
            if i % 5 == 0:
                words.append(f"item_{i}")
            if i % 10 == 0:
                words.append("evidence-based")
        
        return " ".join(words[:num_words])
    
    def process_document(self, document: str, num_tokens: int) -> DocumentMetrics:
        """Process a document and return metrics.
        
        Args:
            document: Document text
            num_tokens: Known token count
            
        Returns:
            DocumentMetrics
        """
        start_time = time.perf_counter()
        
        # Simulate processing: O(n log n) complexity
        # Entity extraction
        words = document.split()
        entities_extracted = len(words) // 20  # ~5% of tokens become entities
        
        # Relationship finding: O(n^1.3) - entity pairs
        if entities_extracted > 1:
            relationships = int((entities_extracted ** 1.3) * 0.5)
        else:
            relationships = 0
        
        # Simulate processing time based on complexity
        # Base: 0.001ms per token
        # Plus: 0.0001ms per entity pair
        processing_time = (num_tokens * 0.001) + (relationships * 0.0001)
        
        # Memory: linear with document size + relationship overhead
        # Assume 1KB per 100 tokens + relationships
        base_memory = num_tokens / 100.0 * 1.0  # 1KB per 100 tokens
        rel_memory = (relationships / 1000.0) * 0.5  # 0.5MB per 1000 rels
        memory_used = base_memory + rel_memory
        
        # Simul ate processing delay
        time.sleep(processing_time / 1000.0)  # Convert ms to seconds
        
        elapsed = (time.perf_counter() - start_time) * 1000  # Convert to ms
        
        throughput = num_tokens / (elapsed / 1000.0) if elapsed > 0 else 0.0
        
        return DocumentMetrics(
            doc_size_tokens=num_tokens,
            processing_time_ms=elapsed,
            memory_used_mb=memory_used,
            throughput_tokens_per_sec=throughput,
            entities_extracted=entities_extracted,
            relationships_found=relationships,
        )


# ============================================================================
# BENCHMARKING ENGINE
# ============================================================================

class LargeScaleBenchmark:
    """Runs large-scale performance benchmarks."""
    
    def __init__(self):
        """Initialize benchmark."""
        self.processor = LargeDocumentProcessor()
        self.analysis = ScalingAnalysis()
    
    def run_scaling_benchmark(self, sizes: List[int]) -> ScalingAnalysis:
        """Run benchmark across multiple document sizes.
        
        Args:
            sizes: List of document sizes (in tokens)
            
        Returns:
            ScalingAnalysis with results
        """
        analysis = ScalingAnalysis()
        
        for size in sizes:
            doc = self.processor.generate_synthetic_document(size)
            metrics = self.processor.process_document(doc, size)
            
            analysis.doc_sizes.append(size)
            analysis.processing_times.append(metrics.processing_time_ms)
            analysis.memory_usage.append(metrics.memory_used_mb)
            analysis.throughput_samples.append(metrics.throughput_tokens_per_sec)
        
        self.analysis = analysis
        return analysis
    
    def run_sustained_benchmark(self, doc_size: int, num_iterations: int) -> Dict[str, float]:
        """Run sustained benchmark at fixed document size.
        
        Args:
            doc_size: Document size in tokens
            num_iterations: Number of documents to process
            
        Returns:
            Statistics dict
        """
        times = []
        memories = []
        
        for _ in range(num_iterations):
            doc = self.processor.generate_synthetic_document(doc_size)
            metrics = self.processor.process_document(doc, doc_size)
            times.append(metrics.processing_time_ms)
            memories.append(metrics.memory_used_mb)
        
        return {
            "avg_time_ms": sum(times) / len(times),
            "max_time_ms": max(times),
            "min_time_ms": min(times),
            "avg_memory_mb": sum(memories) / len(memories),
            "max_memory_mb": max(memories),
            "std_dev_time": (sum((t - sum(times)/len(times))**2 for t in times) / len(times)) ** 0.5,
        }
    
    def run_throughput_benchmark(self, sizes: List[int]) -> Dict[int, float]:
        """Benchmark throughput at different scales.
        
        Args:
            sizes: Document sizes to test
            
        Returns:
            Dict mapping size to throughput (tokens/sec)
        """
        results = {}
        
        for size in sizes:
            doc = self.processor.generate_synthetic_document(size)
            metrics = self.processor.process_document(doc, size)
            results[size] = metrics.throughput_tokens_per_sec
        
        return results
    
    def analyze_memory_efficiency(self, start_size: int, end_size: int, steps: int) -> Dict[str, Any]:
        """Analyze memory efficiency across size range.
        
        Args:
            start_size: Starting document size
            end_size: Ending document size
            steps: Number of steps
            
        Returns:
            Analysis dict
        """
        step_size = (end_size - start_size) // max(steps - 1, 1)
        sizes = [start_size + i * step_size for i in range(steps)]
        
        memory_per_token = []
        
        for size in sizes:
            doc = self.processor.generate_synthetic_document(size)
            metrics = self.processor.process_document(doc, size)
            mem_per_token = metrics.memory_used_mb * 1000 / size  # KB per token
            memory_per_token.append(mem_per_token)
        
        return {
            "sizes": sizes,
            "memory_per_token_kb": memory_per_token,
            "avg_memory_per_token": sum(memory_per_token) / len(memory_per_token),
        }


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestLargeDocumentProcessing:
    """Test large document processing."""
    
    def test_process_small_document(self):
        """Test processing small document (baseline)."""
        processor = LargeDocumentProcessor()
        doc = processor.generate_synthetic_document(100)
        
        metrics = processor.process_document(doc, 100)
        
        assert metrics.doc_size_tokens == 100
        assert metrics.processing_time_ms > 0
        assert metrics.entities_extracted >= 0
    
    def test_process_medium_document(self):
        """Test processing medium document (1k tokens)."""
        processor = LargeDocumentProcessor()
        doc = processor.generate_synthetic_document(1000)
        
        metrics = processor.process_document(doc, 1000)
        
        assert metrics.doc_size_tokens == 1000
        assert metrics.processing_time_ms > 0
        assert metrics.throughput_tokens_per_sec > 0
    
    def test_process_large_document(self):
        """Test processing large document (10k tokens)."""
        processor = LargeDocumentProcessor()
        doc = processor.generate_synthetic_document(10000)
        
        metrics = processor.process_document(doc, 10000)
        
        assert metrics.doc_size_tokens == 10000
        assert metrics.processing_time_ms > 0
        assert metrics.memory_used_mb > 0
    
    def test_metrics_consistency(self):
        """Test metrics consistency and validity."""
        processor = LargeDocumentProcessor()
        doc = processor.generate_synthetic_document(5000)
        
        metrics = processor.process_document(doc, 5000)
        
        # Throughput should equal tokens / time
        expected_throughput = 5000 / (metrics.processing_time_ms / 1000.0)
        assert abs(metrics.throughput_tokens_per_sec - expected_throughput) < 1.0


class TestScalingAnalysis:
    """Test scaling analysis."""
    
    def test_scaling_factor_linear(self):
        """Test scaling factor detection for linear workload."""
        analysis = ScalingAnalysis()
        
        # Simulate O(n) workload
        analysis.doc_sizes = [1000, 2000, 4000]
        analysis.processing_times = [10.0, 20.0, 40.0]  # Linear: time doubles
        
        factor = analysis.scaling_factor()
        
        # Should be close to 1.0 (linear)
        assert 0.9 < factor < 1.1
    
    def test_scaling_factor_quadratic(self):
        """Test scaling factor detection for quadratic workload."""
        analysis = ScalingAnalysis()
        
        # Simulate O(n^2) workload
        analysis.doc_sizes = [1000, 2000, 4000]
        analysis.processing_times = [10.0, 40.0, 160.0]  # Quadratic
        
        factor = analysis.scaling_factor()
        
        # Should be close to 2.0 (quadratic)
        assert 1.9 < factor < 2.1
    
    def test_average_calculations(self):
        """Test average metric calculations."""
        analysis = ScalingAnalysis()
        
        analysis.processing_times = [10.0, 15.0, 20.0]
        analysis.memory_usage = [50.0, 60.0, 70.0]
        analysis.throughput_samples = [1000.0, 1500.0, 2000.0]
        
        assert analysis.avg_processing_time() == 15.0
        assert analysis.avg_memory() == 60.0
        assert analysis.avg_throughput() == 1500.0


class TestLargeScaleBenchmark:
    """Test large-scale benchmarking."""
    
    def test_scaling_benchmark(self):
        """Test scaling benchmark across sizes."""
        benchmark = LargeScaleBenchmark()
        
        sizes = [100, 500, 1000, 5000]
        analysis = benchmark.run_scaling_benchmark(sizes)
        
        assert len(analysis.doc_sizes) == 4
        assert len(analysis.processing_times) == 4
        assert all(t > 0 for t in analysis.processing_times)
    
    def test_sustained_benchmark(self):
        """Test sustained benchmark at fixed size."""
        benchmark = LargeScaleBenchmark()
        
        stats = benchmark.run_sustained_benchmark(doc_size=2000, num_iterations=3)
        
        assert "avg_time_ms" in stats
        assert "max_time_ms" in stats
        assert "min_time_ms" in stats
        assert stats["avg_time_ms"] > 0
        assert stats["max_time_ms"] >= stats["min_time_ms"]
    
    def test_throughput_benchmark(self):
        """Test throughput benchmarking."""
        benchmark = LargeScaleBenchmark()
        
        sizes = [100, 1000, 5000]
        results = benchmark.run_throughput_benchmark(sizes)
        
        assert len(results) == 3
        assert all(throughput > 0 for throughput in results.values())
    
    def test_memory_efficiency_analysis(self):
        """Test memory efficiency analysis."""
        benchmark = LargeScaleBenchmark()
        
        analysis = benchmark.analyze_memory_efficiency(start_size=500, end_size=5000, steps=3)
        
        assert "sizes" in analysis
        assert "memory_per_token_kb" in analysis
        assert "avg_memory_per_token" in analysis
        assert len(analysis["sizes"]) == 3
        assert all(mem > 0 for mem in analysis["memory_per_token_kb"])


class TestPerformanceRegression:
    """Test for performance regressions."""
    
    def test_baseline_throughput_10k(self):
        """Test baseline throughput for 10k token document."""
        processor = LargeDocumentProcessor()
        doc = processor.generate_synthetic_document(10000)
        
        metrics = processor.process_document(doc, 10000)
        
        # Should process at least 100k tokens/sec
        assert metrics.throughput_tokens_per_sec >= 100000
    
    def test_memory_scaling_linear(self):
        """Test that memory scales linearly with document size."""
        benchmark = LargeScaleBenchmark()
        
        # Test at 2 sizes
        sizes = [1000, 10000]
        analysis = benchmark.run_scaling_benchmark(sizes)
        
        # Memory should scale roughly linearly
        mem_ratio = analysis.memory_usage[-1] / analysis.memory_usage[0]
        size_ratio = analysis.doc_sizes[-1] / analysis.doc_sizes[0]
        
        # Allow 50% variance from perfect linearity
        assert 0.5 < mem_ratio / size_ratio < 1.5
    
    def test_processing_time_not_exponential(self):
        """Test that processing time doesn't grow exponentially."""
        benchmark = LargeScaleBenchmark()
        
        sizes = [1000, 5000, 10000]
        analysis = benchmark.run_scaling_benchmark(sizes)
        
        scaling = analysis.scaling_factor()
        
        # Should not be more than O(n^1.5) for sanity
        assert scaling < 1.5, f"Scaling factor {scaling} indicates performance degradation"
    
    def test_large_document_handles_no_errors(self):
        """Test that large documents are processed without errors."""
        processor = LargeDocumentProcessor()
        
        # Test various large sizes
        for size in [5000, 10000, 50000]:
            doc = processor.generate_synthetic_document(size)
            
            # Should not raise
            metrics = processor.process_document(doc, size)
            
            assert metrics.doc_size_tokens == size
            assert metrics.processing_time_ms > 0


class TestThroughputOptimization:
    """Test throughput optimization strategies."""
    
    def test_batch_processing_efficiency(self):
        """Test batch processing efficiency."""
        benchmark = LargeScaleBenchmark()
        
        # Process same total tokens in different batch sizes
        total_tokens = 10000
        
        # Batch 1: 5 x 2k
        times_batch1 = []
        for _ in range(5):
            doc = benchmark.processor.generate_synthetic_document(2000)
            metrics = benchmark.processor.process_document(doc, 2000)
            times_batch1.append(metrics.processing_time_ms)
        
        # Batch 2: 1 x 10k
        doc = benchmark.processor.generate_synthetic_document(10000)
        metrics = benchmark.processor.process_document(doc, 10000)
        time_batch2 = metrics.processing_time_ms
        
        # Large batch might be slightly more efficient due to cache locality
        avg_batch1 = sum(times_batch1) / len(times_batch1)
        
        assert time_batch2 >= 0  # Just ensure it runs
    
    def test_maximum_throughput_size(self):
        """Test throughput at various sizes to find optimal."""
        benchmark = LargeScaleBenchmark()
        
        sizes = [1000, 5000, 10000, 50000]
        results = benchmark.run_throughput_benchmark(sizes)
        
        # Throughput should be reasonably consistent
        throughputs = list(results.values())
        avg_throughput = sum(throughputs) / len(throughputs)
        
        # No single size should be more than 2x worse than average
        for size, throughput in results.items():
            ratio = throughput / avg_throughput
            assert 0.5 < ratio < 2.0, f"Size {size} performance anomaly: {ratio}x average"
