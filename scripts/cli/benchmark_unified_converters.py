"""Performance benchmarks for unified converter architecture."""

import time
import asyncio
from ipfs_datasets_py.logic.fol import FOLConverter
from ipfs_datasets_py.logic.deontic import DeonticConverter


def benchmark_batch_processing():
    """Benchmark batch processing speedup."""
    print("\n" + "="*60)
    print("BENCHMARK: Batch Processing Speedup")
    print("="*60)
    
    converter = FOLConverter(use_ml=False, enable_monitoring=False, use_cache=False)
    texts = ["All humans are mortal", "Socrates is a human"] * 5
    
    # Sequential
    start = time.time()
    seq_results = [converter.convert(t) for t in texts]
    seq_time = time.time() - start
    
    # Batch
    start = time.time()
    batch_results = converter.convert_batch(texts, max_workers=4)
    batch_time = time.time() - start
    
    speedup = seq_time / batch_time if batch_time > 0 else 0
    print(f"Sequential: {seq_time:.3f}s, Batch: {batch_time:.3f}s, Speedup: {speedup:.2f}x")
    return speedup


def benchmark_caching():
    """Benchmark caching performance."""
    print("\n" + "="*60)
    print("BENCHMARK: Caching Performance")
    print("="*60)
    
    converter = FOLConverter(use_cache=True, use_ml=False, enable_monitoring=False)
    text = "All humans are mortal"
    
    start = time.time()
    converter.convert(text)
    first_time = time.time() - start
    
    start = time.time()
    converter.convert(text)
    second_time = time.time() - start
    
    speedup = first_time / second_time if second_time > 0 else 0
    print(f"First: {first_time*1000:.2f}ms, Cached: {second_time*1000:.2f}ms, Speedup: {speedup:.1f}x")
    return speedup


def main():
    """Run all benchmarks."""
    print("="*60)
    print("UNIFIED CONVERTER ARCHITECTURE - BENCHMARKS")
    print("="*60)
    
    batch_speedup = benchmark_batch_processing()
    cache_speedup = benchmark_caching()
    
    print("\n" + "="*60)
    print(f"Batch Speedup: {batch_speedup:.2f}x (Target: 2-5x)")
    print(f"Cache Speedup: {cache_speedup:.1f}x")
    print("="*60)


if __name__ == "__main__":
    main()
