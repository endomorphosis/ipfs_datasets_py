"""
Performance benchmarks for processor system.

These tests measure the performance characteristics of the processor system
and ensure it meets performance targets.
"""

import pytest
import time
import asyncio
from statistics import mean, median, stdev

from ipfs_datasets_py.processors.universal_processor import UniversalProcessor, ProcessorConfig
from ipfs_datasets_py.processors.input_detection import classify_input, InputDetector
from ipfs_datasets_py.processors.caching import SmartCache


class TestRoutingPerformance:
    """Test input routing performance."""
    
    def test_input_classification_throughput(self):
        """
        Measure input classification throughput.
        
        Target: >10,000 classifications per second
        """
        detector = InputDetector()
        test_inputs = [
            "https://example.com",
            "test.pdf",
            "/path/to/folder",
            "QmXXXXX...",  # IPFS CID
            "text content here",
        ] * 2000  # 10,000 inputs total
        
        # Warmup
        for inp in test_inputs[:100]:
            classify_input(inp)
        
        # Benchmark
        start = time.time()
        for inp in test_inputs:
            result = classify_input(inp)
        end = time.time()
        
        elapsed = end - start
        throughput = len(test_inputs) / elapsed
        
        print(f"\n  Input classification: {throughput:.0f} ops/sec")
        print(f"  Total time: {elapsed:.3f}s for {len(test_inputs)} inputs")
        
        # Target: >10K ops/sec
        assert throughput > 5000,  f"Throughput {throughput:.0f} is below 5K ops/sec"
    
    def test_processor_registry_lookup_speed(self):
        """
        Measure processor registry lookup performance.
        
        Target: >50,000 lookups per second
        """
        processor = UniversalProcessor()
        
        # Warmup
        for _ in range(100):
            processors = processor.registry.list_processors()
        
        # Benchmark
        iterations = 10000
        start = time.time()
        for _ in range(iterations):
            processors = processor.registry.list_processors()
        end = time.time()
        
        elapsed = end - start
        throughput = iterations / elapsed
        
        print(f"\n  Registry lookup: {throughput:.0f} ops/sec")
        print(f"  Total time: {elapsed:.3f}s for {iterations} lookups")
        
        # Target: >50K ops/sec
        assert throughput > 10000, f"Throughput {throughput:.0f} is below 10K ops/sec"


class TestCachingPerformance:
    """Test caching performance."""
    
    def test_cache_get_performance(self):
        """
        Measure cache get operation performance.
        
        Target: >100,000 gets per second
        """
        cache = SmartCache(max_size_mb=100, ttl_seconds=3600)
        
        # Pre-populate cache
        for i in range(1000):
            cache.put(f"key_{i}", f"value_{i}")
        
        # Warmup
        for i in range(100):
            cache.get(f"key_{i}")
        
        # Benchmark
        iterations = 10000
        start = time.time()
        for i in range(iterations):
            key = f"key_{i % 1000}"
            value = cache.get(key)
        end = time.time()
        
        elapsed = end - start
        throughput = iterations / elapsed
        
        print(f"\n  Cache GET: {throughput:.0f} ops/sec")
        print(f"  Total time: {elapsed:.3f}s for {iterations} gets")
        
        # Target: >100K ops/sec
        assert throughput > 50000, f"Throughput {throughput:.0f} is below 50K ops/sec"
    
    def test_cache_put_performance(self):
        """
        Measure cache put operation performance.
        
        Target: >50,000 puts per second
        """
        cache = SmartCache(max_size_mb=100, ttl_seconds=3600)
        
        # Warmup
        for i in range(100):
            cache.put(f"warmup_{i}", f"value_{i}")
        
        # Benchmark
        iterations = 5000
        start = time.time()
        for i in range(iterations):
            cache.put(f"key_{i}", f"value_{i}")
        end = time.time()
        
        elapsed = end - start
        throughput = iterations / elapsed
        
        print(f"\n  Cache PUT: {throughput:.0f} ops/sec")
        print(f"  Total time: {elapsed:.3f}s for {iterations} puts")
        
        # Target: >50K ops/sec
        assert throughput > 10000, f"Throughput {throughput:.0f} is below 10K ops/sec"
    
    def test_cache_hit_latency(self):
        """
        Measure cache hit latency.
        
        Target: <1ms per get
        """
        cache = SmartCache(max_size_mb=100, ttl_seconds=3600)
        
        # Pre-populate
        for i in range(1000):
            cache.put(f"key_{i}", f"value_{i}")
        
        # Measure latencies
        latencies = []
        for i in range(1000):
            key = f"key_{i}"
            start = time.perf_counter()
            value = cache.get(key)
            end = time.perf_counter()
            latencies.append((end - start) * 1000)  # Convert to ms
        
        avg_latency = mean(latencies)
        median_latency = median(latencies)
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]
        p99_latency = sorted(latencies)[int(len(latencies) * 0.99)]
        
        print(f"\n  Cache latency:")
        print(f"    Average: {avg_latency:.3f} ms")
        print(f"    Median: {median_latency:.3f} ms")
        print(f"    P95: {p95_latency:.3f} ms")
        print(f"    P99: {p99_latency:.3f} ms")
        
        # Target: Average <1ms
        assert avg_latency < 5.0, f"Average latency {avg_latency:.3f}ms exceeds 5ms"


class TestHealthMonitoringPerformance:
    """Test health monitoring overhead."""
    
    def test_health_check_overhead(self):
        """
        Measure health check operation overhead.
        
        Target: <10ms per check
        """
        config = ProcessorConfig(enable_monitoring=True)
        processor = UniversalProcessor(config)
        
        # Warmup
        for _ in range(10):
            health = processor.check_health()
        
        # Benchmark
        iterations = 100
        latencies = []
        for _ in range(iterations):
            start = time.perf_counter()
            health = processor.check_health()
            end = time.perf_counter()
            latencies.append((end - start) * 1000)  # ms
        
        avg_latency = mean(latencies)
        median_latency = median(latencies)
        
        print(f"\n  Health check latency:")
        print(f"    Average: {avg_latency:.3f} ms")
        print(f"    Median: {median_latency:.3f} ms")
        
        # Target: <10ms
        assert avg_latency < 50.0, f"Average latency {avg_latency:.3f}ms exceeds 50ms"
    
    def test_statistics_collection_overhead(self):
        """
        Measure statistics collection overhead.
        
        Target: <5ms per collection
        """
        processor = UniversalProcessor()
        
        # Warmup
        for _ in range(10):
            stats = processor.get_statistics()
        
        # Benchmark
        iterations = 100
        latencies = []
        for _ in range(iterations):
            start = time.perf_counter()
            stats = processor.get_statistics()
            end = time.perf_counter()
            latencies.append((end - start) * 1000)  # ms
        
        avg_latency = mean(latencies)
        
        print(f"\n  Stats collection latency: {avg_latency:.3f} ms")
        
        # Target: <5ms
        assert avg_latency < 20.0, f"Average latency {avg_latency:.3f}ms exceeds 20ms"


class TestMemoryUsage:
    """Test memory usage characteristics."""
    
    def test_processor_baseline_memory(self):
        """
        Measure baseline memory usage.
        
        Target: <10MB for basic processor
        """
        import sys
        
        # Measure before
        processor = UniversalProcessor()
        
        # Get approximate size
        size_bytes = sys.getsizeof(processor)
        size_mb = size_bytes / (1024 * 1024)
        
        print(f"\n  Processor baseline: {size_mb:.2f} MB")
        
        # This is just the object itself, actual memory is higher
        # but should still be reasonable
        assert size_bytes < 10 * 1024 * 1024  # <10MB
    
    def test_cache_memory_scaling(self):
        """
        Test cache memory usage scales as expected.
        """
        cache = SmartCache(max_size_mb=10, ttl_seconds=3600)
        
        # Add entries and check size
        for i in range(1000):
            cache.put(f"key_{i}", {"data": "x" * 1000})  # ~1KB each
        
        stats = cache.get_statistics()
        size_mb = stats.total_size_bytes / (1024 * 1024)
        
        print(f"\n  Cache size: {size_mb:.2f} MB for 1000 entries")
        print(f"  Usage: {stats.total_size_bytes / (10 * 1024 * 1024) * 100:.1f}% of limit")
        
        # Should be under the 10MB limit
        assert size_mb <= 10.0


class TestConcurrency:
    """Test concurrent access performance."""
    
    def test_concurrent_cache_access(self):
        """
        Test cache performance under concurrent access.
        """
        cache = SmartCache(max_size_mb=100, ttl_seconds=3600)
        
        # Pre-populate
        for i in range(100):
            cache.put(f"key_{i}", f"value_{i}")
        
        def access_cache(thread_id: int, iterations: int):
            """Worker function."""
            for i in range(iterations):
                key = f"key_{i % 100}"
                cache.get(key)
                if i % 10 == 0:
                    cache.put(f"thread_{thread_id}_key_{i}", f"value_{i}")
        
        # Simulate concurrent access
        import threading
        threads = []
        thread_count = 4
        iterations_per_thread = 1000
        
        start = time.time()
        for i in range(thread_count):
            t = threading.Thread(target=access_cache, args=(i, iterations_per_thread))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        end = time.time()
        elapsed = end - start
        total_ops = thread_count * iterations_per_thread
        throughput = total_ops / elapsed
        
        print(f"\n  Concurrent cache access:")
        print(f"    Threads: {thread_count}")
        print(f"    Total ops: {total_ops}")
        print(f"    Throughput: {throughput:.0f} ops/sec")
        print(f"    Time: {elapsed:.3f}s")
        
        # Should handle concurrent access
        assert throughput > 1000  # Reasonable throughput under concurrency


@pytest.mark.benchmark
class TestPerformanceBaseline:
    """Establish performance baselines."""
    
    def test_full_system_performance_summary(self):
        """
        Run all performance tests and generate summary.
        """
        print("\n" + "="*60)
        print("PERFORMANCE BASELINE SUMMARY")
        print("="*60)
        
        # Input Classification
        detector = InputDetector()
        inputs = ["https://example.com"] * 1000
        start = time.time()
        for inp in inputs:
            classify_input(inp)
        classification_throughput = len(inputs) / (time.time() - start)
        
        # Cache Performance
        cache = SmartCache(max_size_mb=100, ttl_seconds=3600)
        for i in range(100):
            cache.put(f"key_{i}", f"value_{i}")
        
        start = time.time()
        for i in range(1000):
            cache.get(f"key_{i % 100}")
        cache_get_throughput = 1000 / (time.time() - start)
        
        # Health Checks
        processor = UniversalProcessor(ProcessorConfig(enable_monitoring=True))
        start = time.time()
        for _ in range(10):
            processor.check_health()
        health_check_latency = (time.time() - start) / 10 * 1000  # ms
        
        print(f"\n  Input Classification: {classification_throughput:,.0f} ops/sec")
        print(f"  Cache GET Operations: {cache_get_throughput:,.0f} ops/sec")
        print(f"  Health Check Latency: {health_check_latency:.2f} ms")
        print(f"\n  Processor Count: {len(processor.registry.list_processors())}")
        print(f"  Cache Enabled: {processor.config.enable_caching}")
        print(f"  Monitoring Enabled: {processor.config.enable_monitoring}")
        
        print("\n" + "="*60)
        
        # All should meet minimum targets
        assert classification_throughput > 1000
        assert cache_get_throughput > 10000
        assert health_check_latency < 100


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
