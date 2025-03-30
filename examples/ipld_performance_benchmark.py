#!/usr/bin/env python3
"""
IPLD Performance Benchmark

This script demonstrates and benchmarks the performance improvements
from the optimized IPLD codec for high-throughput processing.

It creates test datasets of various sizes and benchmarks encoding,
decoding, and CAR file operations using both standard and optimized
implementations.

Usage:
  python ipld_performance_benchmark.py [--size small|medium|large]

Example:
  python ipld_performance_benchmark.py --size medium
"""

import argparse
import json
import os
import random
import sys
import tempfile
import time
from typing import Dict, List, Tuple, Any

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

# Import required modules
from ipfs_datasets_py.ipld.storage import IPLDStorage
from ipfs_datasets_py.ipld.optimized_codec import (
    OptimizedEncoder, OptimizedDecoder, BatchProcessor,
    create_batch_processor, PBNode
)


def create_test_data(size: str) -> Tuple[List[Dict], List[bytes]]:
    """
    Create test data of specified size.
    
    Args:
        size (str): Size category ('small', 'medium', 'large')
        
    Returns:
        Tuple of (json_objects, binary_data)
    """
    # Define sizes
    sizes = {
        "small": 100,
        "medium": 1000,
        "large": 10000
    }
    
    count = sizes.get(size, 100)
    print(f"Creating test data with {count} items...")
    
    # Create JSON objects
    json_objects = []
    for i in range(count):
        # Create a more complex object with nested data
        obj = {
            "id": i,
            "name": f"Item {i}",
            "created": time.time(),
            "metadata": {
                "type": random.choice(["document", "image", "video", "audio"]),
                "tags": [f"tag{random.randint(1, 10)}" for _ in range(random.randint(1, 5))],
                "size": random.randint(1000, 10000000),
                "attributes": {
                    "width": random.randint(100, 4000),
                    "height": random.randint(100, 4000),
                    "color": f"#{random.randint(0, 0xFFFFFF):06x}"
                }
            },
            "content": "x" * random.randint(100, 1000)  # Random content length
        }
        json_objects.append(obj)
    
    # Create binary data
    binary_data = []
    for i in range(count):
        size = random.randint(100, 10000)
        data = bytes(random.getrandbits(8) for _ in range(size))
        binary_data.append(data)
    
    return json_objects, binary_data


def benchmark_json_encoding(storage: IPLDStorage, json_objects: List[Dict]) -> Tuple[float, float]:
    """
    Benchmark JSON encoding using standard and batch methods.
    
    Args:
        storage (IPLDStorage): Storage instance
        json_objects (List[Dict]): JSON objects to encode
        
    Returns:
        Tuple of (standard_time, batch_time)
    """
    print(f"Benchmarking JSON encoding with {len(json_objects)} objects...")
    
    # Standard method (one by one)
    start_time = time.time()
    standard_cids = []
    for obj in json_objects:
        cid = storage.store_json(obj)
        standard_cids.append(cid)
    standard_time = time.time() - start_time
    
    print(f"Standard JSON encoding: {standard_time:.2f} seconds")
    
    # Batch method
    start_time = time.time()
    batch_cids = storage.store_json_batch(json_objects)
    batch_time = time.time() - start_time
    
    print(f"Batch JSON encoding: {batch_time:.2f} seconds")
    
    # Verify results
    assert len(standard_cids) == len(batch_cids), "CID count mismatch"
    
    return standard_time, batch_time


def benchmark_binary_encoding(storage: IPLDStorage, binary_data: List[bytes]) -> Tuple[float, float]:
    """
    Benchmark binary data encoding using standard and batch methods.
    
    Args:
        storage (IPLDStorage): Storage instance
        binary_data (List[bytes]): Binary data to encode
        
    Returns:
        Tuple of (standard_time, batch_time)
    """
    print(f"Benchmarking binary encoding with {len(binary_data)} blocks...")
    
    # Standard method (one by one)
    start_time = time.time()
    standard_cids = []
    for data in binary_data:
        cid = storage.store(data)
        standard_cids.append(cid)
    standard_time = time.time() - start_time
    
    print(f"Standard binary encoding: {standard_time:.2f} seconds")
    
    # Batch method
    start_time = time.time()
    batch_cids = storage.store_batch(binary_data)
    batch_time = time.time() - start_time
    
    print(f"Batch binary encoding: {batch_time:.2f} seconds")
    
    # Verify results
    assert len(standard_cids) == len(batch_cids), "CID count mismatch"
    
    return standard_time, batch_time


def benchmark_retrieval(storage: IPLDStorage, cids: List[str]) -> Tuple[float, float]:
    """
    Benchmark data retrieval using standard and batch methods.
    
    Args:
        storage (IPLDStorage): Storage instance
        cids (List[str]): CIDs to retrieve
        
    Returns:
        Tuple of (standard_time, batch_time)
    """
    print(f"Benchmarking retrieval with {len(cids)} CIDs...")
    
    # Standard method (one by one)
    start_time = time.time()
    standard_results = []
    for cid in cids:
        data = storage.get(cid)
        standard_results.append(data)
    standard_time = time.time() - start_time
    
    print(f"Standard retrieval: {standard_time:.2f} seconds")
    
    # Batch method
    start_time = time.time()
    batch_results = storage.get_batch(cids)
    batch_time = time.time() - start_time
    
    print(f"Batch retrieval: {batch_time:.2f} seconds")
    
    # Verify results
    assert len(standard_results) == len(batch_results), "Result count mismatch"
    
    return standard_time, batch_time


def benchmark_car_operations(storage: IPLDStorage, cids: List[str]) -> Tuple[float, float, float, float]:
    """
    Benchmark CAR file export/import using standard and streaming methods.
    
    Args:
        storage (IPLDStorage): Storage instance
        cids (List[str]): CIDs to include in CAR
        
    Returns:
        Tuple of (standard_export_time, stream_export_time, standard_import_time, stream_import_time)
    """
    print(f"Benchmarking CAR operations with {len(cids)} CIDs...")
    
    # Create temp directory for CAR files
    temp_dir = tempfile.mkdtemp()
    standard_car_path = os.path.join(temp_dir, "standard.car")
    stream_car_path = os.path.join(temp_dir, "stream.car")
    
    # Standard export
    start_time = time.time()
    storage.export_to_car(cids, standard_car_path)
    standard_export_time = time.time() - start_time
    
    print(f"Standard CAR export: {standard_export_time:.2f} seconds")
    
    # Streaming export
    start_time = time.time()
    with open(stream_car_path, 'wb') as f:
        storage.export_to_car_stream(cids, f)
    stream_export_time = time.time() - start_time
    
    print(f"Streaming CAR export: {stream_export_time:.2f} seconds")
    
    # Create new storage instances for import testing
    standard_import_storage = IPLDStorage(base_dir=os.path.join(temp_dir, "standard_import"))
    stream_import_storage = IPLDStorage(base_dir=os.path.join(temp_dir, "stream_import"))
    
    # Standard import
    start_time = time.time()
    standard_import_storage.import_from_car(standard_car_path)
    standard_import_time = time.time() - start_time
    
    print(f"Standard CAR import: {standard_import_time:.2f} seconds")
    
    # Streaming import
    start_time = time.time()
    with open(stream_car_path, 'rb') as f:
        stream_import_storage.import_from_car_stream(f)
    stream_import_time = time.time() - start_time
    
    print(f"Streaming CAR import: {stream_import_time:.2f} seconds")
    
    # Clean up
    try:
        import shutil
        shutil.rmtree(temp_dir)
    except:
        print(f"Failed to remove temp directory: {temp_dir}")
    
    return standard_export_time, stream_export_time, standard_import_time, stream_import_time


def benchmark_optimized_codec(binary_data: List[bytes]) -> Dict[str, float]:
    """
    Benchmark the optimized codec directly.
    
    Args:
        binary_data (List[bytes]): Binary data to encode/decode
        
    Returns:
        Dict with benchmark results
    """
    print(f"Benchmarking optimized codec with {len(binary_data)} blocks...")
    
    # Create nodes for encoding
    nodes = [PBNode(data=data) for data in binary_data]
    
    # Standard encoder/decoder (without optimizations)
    standard_encoder = OptimizedEncoder(use_cache=False, max_workers=1)
    standard_decoder = OptimizedDecoder(use_cache=False, max_workers=1)
    
    # Optimized encoder/decoder
    optimized_encoder = OptimizedEncoder(use_cache=True, max_workers=None)
    optimized_decoder = OptimizedDecoder(use_cache=True, max_workers=None)
    
    # Benchmark standard encoding
    start_time = time.time()
    standard_encoded = []
    for node in nodes:
        encoded = standard_encoder.encode_node(node)
        standard_encoded.append(encoded)
    standard_encode_time = time.time() - start_time
    
    print(f"Standard encoding: {standard_encode_time:.2f} seconds")
    
    # Benchmark optimized encoding
    start_time = time.time()
    optimized_encoded = optimized_encoder.encode_batch(nodes)
    optimized_encode_time = time.time() - start_time
    
    print(f"Optimized encoding: {optimized_encode_time:.2f} seconds")
    
    # Extract encoded data for decoding tests
    encoded_data = [(data, cid) for data, cid in standard_encoded]
    
    # Benchmark standard decoding
    start_time = time.time()
    for data, cid in encoded_data:
        standard_decoder.decode_block(data, cid)
    standard_decode_time = time.time() - start_time
    
    print(f"Standard decoding: {standard_decode_time:.2f} seconds")
    
    # Benchmark optimized decoding
    start_time = time.time()
    optimized_decoder.decode_batch(encoded_data)
    optimized_decode_time = time.time() - start_time
    
    print(f"Optimized decoding: {optimized_decode_time:.2f} seconds")
    
    # Check cache impact
    cache_encoder = OptimizedEncoder(use_cache=True, max_workers=1)
    
    # First run to warm up cache
    for node in nodes[:10]:
        cache_encoder.encode_node(node)
    
    # Benchmark repeated encoding with cache
    start_time = time.time()
    for _ in range(5):
        for node in nodes[:10]:
            cache_encoder.encode_node(node)
    cache_encode_time = time.time() - start_time
    
    print(f"Cached encoding (50 operations): {cache_encode_time:.2f} seconds")
    
    if cache_encoder.stats:
        cache_hits = cache_encoder.stats.cache_hits
        cache_misses = cache_encoder.stats.cache_misses
        cache_hit_rate = cache_hits / (cache_hits + cache_misses) if (cache_hits + cache_misses) > 0 else 0
        print(f"Cache hit rate: {cache_hit_rate:.2%}")
    
    # Return results
    return {
        "standard_encode_time": standard_encode_time,
        "optimized_encode_time": optimized_encode_time,
        "standard_decode_time": standard_decode_time,
        "optimized_decode_time": optimized_decode_time,
        "cache_encode_time": cache_encode_time
    }


def run_full_benchmark(size: str) -> Dict[str, Any]:
    """
    Run a full set of benchmarks and return the results.
    
    Args:
        size (str): Size category ('small', 'medium', 'large')
        
    Returns:
        Dict with benchmark results
    """
    # Create test data
    json_objects, binary_data = create_test_data(size)
    
    # Create storage
    temp_dir = tempfile.mkdtemp()
    storage = IPLDStorage(base_dir=temp_dir)
    
    # Run benchmarks
    results = {}
    
    # JSON encoding benchmark
    standard_json_time, batch_json_time = benchmark_json_encoding(storage, json_objects)
    results["json_encoding"] = {
        "standard_time": standard_json_time,
        "batch_time": batch_json_time,
        "improvement": standard_json_time / batch_json_time if batch_json_time > 0 else 0
    }
    
    # Binary encoding benchmark
    standard_binary_time, batch_binary_time = benchmark_binary_encoding(storage, binary_data)
    results["binary_encoding"] = {
        "standard_time": standard_binary_time,
        "batch_time": batch_binary_time,
        "improvement": standard_binary_time / batch_binary_time if batch_binary_time > 0 else 0
    }
    
    # Store data for retrieval benchmark
    print("Storing data for retrieval benchmark...")
    cids = storage.store_batch(binary_data)
    
    # Retrieval benchmark
    standard_retrieval_time, batch_retrieval_time = benchmark_retrieval(storage, cids)
    results["retrieval"] = {
        "standard_time": standard_retrieval_time,
        "batch_time": batch_retrieval_time,
        "improvement": standard_retrieval_time / batch_retrieval_time if batch_retrieval_time > 0 else 0
    }
    
    # CAR operations benchmark
    # Use a subset of CIDs for larger datasets to keep benchmark reasonable
    car_cids = cids[:min(len(cids), 100)]
    standard_export_time, stream_export_time, standard_import_time, stream_import_time = (
        benchmark_car_operations(storage, car_cids)
    )
    results["car_operations"] = {
        "standard_export_time": standard_export_time,
        "stream_export_time": stream_export_time,
        "standard_import_time": standard_import_time,
        "stream_import_time": stream_import_time,
        "export_improvement": standard_export_time / stream_export_time if stream_export_time > 0 else 0,
        "import_improvement": standard_import_time / stream_import_time if stream_import_time > 0 else 0
    }
    
    # Optimized codec benchmark
    codec_results = benchmark_optimized_codec(binary_data)
    results["codec"] = codec_results
    results["codec"]["encode_improvement"] = (
        codec_results["standard_encode_time"] / codec_results["optimized_encode_time"]
        if codec_results["optimized_encode_time"] > 0 else 0
    )
    results["codec"]["decode_improvement"] = (
        codec_results["standard_decode_time"] / codec_results["optimized_decode_time"]
        if codec_results["optimized_decode_time"] > 0 else 0
    )
    
    # Clean up
    try:
        import shutil
        shutil.rmtree(temp_dir)
    except:
        print(f"Failed to remove temp directory: {temp_dir}")
    
    return results


def print_results(results: Dict[str, Any]) -> None:
    """
    Print formatted benchmark results.
    
    Args:
        results (Dict): Benchmark results
    """
    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)
    
    print("\nJSON Encoding:")
    print(f"  Standard:   {results['json_encoding']['standard_time']:.2f}s")
    print(f"  Batch:      {results['json_encoding']['batch_time']:.2f}s")
    print(f"  Improvement: {results['json_encoding']['improvement']:.2f}x")
    
    print("\nBinary Encoding:")
    print(f"  Standard:   {results['binary_encoding']['standard_time']:.2f}s")
    print(f"  Batch:      {results['binary_encoding']['batch_time']:.2f}s")
    print(f"  Improvement: {results['binary_encoding']['improvement']:.2f}x")
    
    print("\nData Retrieval:")
    print(f"  Standard:   {results['retrieval']['standard_time']:.2f}s")
    print(f"  Batch:      {results['retrieval']['batch_time']:.2f}s")
    print(f"  Improvement: {results['retrieval']['improvement']:.2f}x")
    
    print("\nCAR Operations:")
    print(f"  Standard Export: {results['car_operations']['standard_export_time']:.2f}s")
    print(f"  Stream Export:   {results['car_operations']['stream_export_time']:.2f}s")
    print(f"  Export Improvement: {results['car_operations']['export_improvement']:.2f}x")
    print(f"  Standard Import: {results['car_operations']['standard_import_time']:.2f}s")
    print(f"  Stream Import:   {results['car_operations']['stream_import_time']:.2f}s")
    print(f"  Import Improvement: {results['car_operations']['import_improvement']:.2f}x")
    
    print("\nOptimized Codec:")
    print(f"  Standard Encoding: {results['codec']['standard_encode_time']:.2f}s")
    print(f"  Optimized Encoding: {results['codec']['optimized_encode_time']:.2f}s")
    print(f"  Encoding Improvement: {results['codec']['encode_improvement']:.2f}x")
    print(f"  Standard Decoding: {results['codec']['standard_decode_time']:.2f}s")
    print(f"  Optimized Decoding: {results['codec']['optimized_decode_time']:.2f}s")
    print(f"  Decoding Improvement: {results['codec']['decode_improvement']:.2f}x")
    
    print("\nOverall Improvement:")
    improvements = [
        results['json_encoding']['improvement'],
        results['binary_encoding']['improvement'],
        results['retrieval']['improvement'],
        results['car_operations']['export_improvement'],
        results['car_operations']['import_improvement'],
        results['codec']['encode_improvement'],
        results['codec']['decode_improvement']
    ]
    avg_improvement = sum(improvements) / len(improvements)
    print(f"  Average: {avg_improvement:.2f}x")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='IPLD Performance Benchmark')
    parser.add_argument('--size', choices=['small', 'medium', 'large'], default='small',
                      help='Size of the test dataset (default: small)')
    
    args = parser.parse_args()
    
    print(f"Starting IPLD performance benchmark with {args.size} dataset...")
    start_time = time.time()
    
    results = run_full_benchmark(args.size)
    
    total_time = time.time() - start_time
    print(f"\nBenchmark completed in {total_time:.2f} seconds")
    
    print_results(results)
    
    # Save results to file
    result_file = f"ipld_benchmark_{args.size}_{int(time.time())}.json"
    with open(result_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nDetailed results saved to {result_file}")