#!/usr/bin/env python3
"""
Performance Benchmark for TDFOL Natural Language Parser.

Measures parsing speed, memory usage, and throughput.
"""

import time
import statistics
from typing import List, Dict, Any

try:
    from ipfs_datasets_py.logic.TDFOL.nl import parse_natural_language, NLParser
    DEPENDENCIES_AVAILABLE = True
except ImportError:
    DEPENDENCIES_AVAILABLE = False
    print("ERROR: NL parsing dependencies not available.")
    print("Install with: pip install ipfs_datasets_py[knowledge_graphs]")
    print("Then run: python -m spacy download en_core_web_sm")
    exit(1)


def benchmark_parse_time(text: str, iterations: int = 10) -> Dict[str, float]:
    """Benchmark parsing time for a single text."""
    times = []
    
    for _ in range(iterations):
        start = time.time()
        result = parse_natural_language(text)
        end = time.time()
        times.append((end - start) * 1000)  # Convert to ms
    
    return {
        'mean': statistics.mean(times),
        'median': statistics.median(times),
        'stdev': statistics.stdev(times) if len(times) > 1 else 0.0,
        'min': min(times),
        'max': max(times),
        'p95': sorted(times)[int(len(times) * 0.95)] if len(times) > 1 else times[0],
    }


def benchmark_batch_processing(texts: List[str]) -> Dict[str, Any]:
    """Benchmark batch processing performance."""
    start = time.time()
    
    parser = NLParser()
    results = []
    for text in texts:
        result = parser.parse(text)
        results.append(result)
    
    end = time.time()
    total_time = (end - start) * 1000  # ms
    
    return {
        'total_time_ms': total_time,
        'num_texts': len(texts),
        'avg_time_per_text_ms': total_time / len(texts),
        'throughput_per_second': len(texts) / ((end - start) or 0.001),
        'num_formulas': sum(r.num_formulas for r in results),
    }


def benchmark_caching_speedup(text: str, iterations: int = 5) -> Dict[str, float]:
    """Benchmark caching speedup."""
    parser = NLParser()
    
    # First parse (no cache)
    times_no_cache = []
    for _ in range(iterations):
        parser.clear_cache()
        start = time.time()
        parser.parse(text)
        end = time.time()
        times_no_cache.append((end - start) * 1000)
    
    # With cache
    times_cached = []
    for _ in range(iterations):
        start = time.time()
        parser.parse(text)  # Should be cached
        end = time.time()
        times_cached.append((end - start) * 1000)
    
    avg_no_cache = statistics.mean(times_no_cache)
    avg_cached = statistics.mean(times_cached)
    
    return {
        'avg_no_cache_ms': avg_no_cache,
        'avg_cached_ms': avg_cached,
        'speedup': avg_no_cache / avg_cached if avg_cached > 0 else float('inf'),
    }


def run_benchmarks():
    """Run all benchmarks and print results."""
    print("=" * 70)
    print("TDFOL Natural Language Parser Performance Benchmark")
    print("=" * 70)
    print()
    
    # Test sentences
    simple_sentence = "Contractors must pay taxes."
    complex_sentence = (
        "All licensed contractors must submit quarterly tax reports "
        "within 30 days of the end of each quarter."
    )
    
    batch_texts = [
        "All contractors must pay taxes.",
        "Employees may request vacation.",
        "Disclosure is forbidden.",
        "Payment must be made within 30 days.",
        "Contractors shall submit reports.",
        "Workers are required to wear helmets.",
        "Vehicles must not park here.",
        "Entry is prohibited after 10 PM.",
        "All members may vote.",
        "Smoking is not permitted.",
    ]
    
    # Benchmark 1: Simple sentence parsing
    print("Benchmark 1: Simple Sentence Parsing")
    print(f"Text: '{simple_sentence}'")
    results = benchmark_parse_time(simple_sentence, iterations=20)
    print(f"  Mean:     {results['mean']:.2f} ms")
    print(f"  Median:   {results['median']:.2f} ms")
    print(f"  Min:      {results['min']:.2f} ms")
    print(f"  Max:      {results['max']:.2f} ms")
    print(f"  95th %:   {results['p95']:.2f} ms")
    print(f"  Std Dev:  {results['stdev']:.2f} ms")
    print()
    
    # Benchmark 2: Complex sentence parsing
    print("Benchmark 2: Complex Sentence Parsing")
    print(f"Text: '{complex_sentence[:50]}...'")
    results = benchmark_parse_time(complex_sentence, iterations=20)
    print(f"  Mean:     {results['mean']:.2f} ms")
    print(f"  Median:   {results['median']:.2f} ms")
    print(f"  Min:      {results['min']:.2f} ms")
    print(f"  Max:      {results['max']:.2f} ms")
    print(f"  95th %:   {results['p95']:.2f} ms")
    print(f"  Std Dev:  {results['stdev']:.2f} ms")
    print()
    
    # Benchmark 3: Batch processing
    print("Benchmark 3: Batch Processing")
    print(f"Number of texts: {len(batch_texts)}")
    results = benchmark_batch_processing(batch_texts)
    print(f"  Total time:     {results['total_time_ms']:.2f} ms")
    print(f"  Avg per text:   {results['avg_time_per_text_ms']:.2f} ms")
    print(f"  Throughput:     {results['throughput_per_second']:.1f} texts/second")
    print(f"  Total formulas: {results['num_formulas']}")
    print()
    
    # Benchmark 4: Caching speedup
    print("Benchmark 4: Caching Speedup")
    print(f"Text: '{simple_sentence}'")
    results = benchmark_caching_speedup(simple_sentence, iterations=10)
    print(f"  Without cache:  {results['avg_no_cache_ms']:.2f} ms")
    print(f"  With cache:     {results['avg_cached_ms']:.2f} ms")
    print(f"  Speedup:        {results['speedup']:.1f}x")
    print()
    
    print("=" * 70)
    print("Benchmark Complete")
    print("=" * 70)


if __name__ == "__main__":
    if not DEPENDENCIES_AVAILABLE:
        exit(1)
    
    print("Starting benchmarks...")
    print("(This may take a minute...)")
    print()
    
    run_benchmarks()
