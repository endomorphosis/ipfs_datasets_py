"""
Memory Usage Benchmark (Phase 3.2)

Tracks memory efficiency for the dual-runtime architecture.
Monitors baseline memory, memory per request, leak detection, and GC impact.

Usage:
    python -m ipfs_datasets_py.mcp_server.benchmarks.memory_usage
    python -m ipfs_datasets_py.mcp_server.benchmarks.memory_usage --iterations 1000
    python -m ipfs_datasets_py.mcp_server.benchmarks.memory_usage --runtime trio
"""

import anyio
import argparse
import logging
import gc
import time
import psutil
import os
from typing import Dict, List, Any, Optional
from pathlib import Path
import json

logger = logging.getLogger(__name__)

# Try to import RuntimeRouter
try:
    from ipfs_datasets_py.mcp_server.runtime_router import RuntimeRouter, RUNTIME_FASTAPI, RUNTIME_TRIO
    RUNTIME_ROUTER_AVAILABLE = True
except ImportError:
    RUNTIME_ROUTER_AVAILABLE = False
    logger.warning("RuntimeRouter not available")

# Try to import P2P tools
try:
    from ipfs_datasets_py.mcp_server.tools import mcplusplus_workflow_tools
    P2P_TOOLS_AVAILABLE = True
except ImportError:
    P2P_TOOLS_AVAILABLE = False
    logger.warning("P2P tools not available")


class MemoryTracker:
    """Track memory usage over time."""
    
    def __init__(self):
        self.process = psutil.Process(os.getpid())
        self.measurements = []
    
    def get_memory_mb(self) -> float:
        """Get current memory usage in MB."""
        return self.process.memory_info().rss / (1024 * 1024)
    
    def take_snapshot(self, label: str = "") -> Dict[str, Any]:
        """Take a memory snapshot."""
        memory_mb = self.get_memory_mb()
        snapshot = {
            'timestamp': time.time(),
            'label': label,
            'memory_mb': memory_mb
        }
        self.measurements.append(snapshot)
        return snapshot
    
    def get_stats(self) -> Dict[str, Any]:
        """Calculate memory statistics."""
        if not self.measurements:
            return {}
        
        memories = [m['memory_mb'] for m in self.measurements]
        
        return {
            'count': len(memories),
            'min_mb': min(memories),
            'max_mb': max(memories),
            'avg_mb': sum(memories) / len(memories),
            'peak_mb': max(memories),
            'baseline_mb': memories[0] if memories else 0,
            'growth_mb': memories[-1] - memories[0] if len(memories) > 1 else 0,
            'measurements': self.measurements
        }


async def measure_baseline_memory(tracker: MemoryTracker) -> Dict[str, Any]:
    """Measure baseline memory before any operations."""
    logger.info("Measuring baseline memory...")
    
    # Force garbage collection
    gc.collect()
    await anyio.sleep(0.5)
    
    # Take initial snapshot
    initial = tracker.take_snapshot('baseline_start')
    
    # Wait and take another snapshot
    await anyio.sleep(2.0)
    
    final = tracker.take_snapshot('baseline_end')
    
    return {
        'initial_mb': initial['memory_mb'],
        'final_mb': final['memory_mb'],
        'stable': abs(final['memory_mb'] - initial['memory_mb']) < 5.0  # Stable if < 5MB drift
    }


async def measure_memory_per_request(
    tracker: MemoryTracker,
    runtime: str = 'trio',
    iterations: int = 100
) -> Dict[str, Any]:
    """Measure memory usage per request."""
    logger.info(f"Measuring memory per request ({runtime} runtime, {iterations} iterations)...")
    
    # Force GC before test
    gc.collect()
    await anyio.sleep(0.5)
    
    initial = tracker.take_snapshot(f'{runtime}_before')
    
    # Run iterations
    for i in range(iterations):
        if P2P_TOOLS_AVAILABLE:
            try:
                await mcplusplus_workflow_tools.workflow_status(
                    workflow_id=f'test-wf-{i}'
                )
            except Exception as e:
                logger.debug(f"Request failed (expected): {e}")
        else:
            # Mock request
            await anyio.sleep(0.001)
        
        # Take periodic snapshots
        if i % (iterations // 10) == 0:
            tracker.take_snapshot(f'{runtime}_iter_{i}')
    
    # Force GC after test
    gc.collect()
    await anyio.sleep(0.5)
    
    final = tracker.take_snapshot(f'{runtime}_after')
    
    # Calculate memory per request
    memory_increase = final['memory_mb'] - initial['memory_mb']
    memory_per_request = memory_increase / iterations if iterations > 0 else 0
    
    return {
        'runtime': runtime,
        'iterations': iterations,
        'initial_mb': initial['memory_mb'],
        'final_mb': final['memory_mb'],
        'increase_mb': memory_increase,
        'memory_per_request_kb': memory_per_request * 1024
    }


async def detect_memory_leaks(
    tracker: MemoryTracker,
    iterations: int = 1000,
    batch_size: int = 100
) -> Dict[str, Any]:
    """Detect potential memory leaks."""
    logger.info(f"Detecting memory leaks ({iterations} iterations, {batch_size} per batch)...")
    
    batch_measurements = []
    
    for batch in range(iterations // batch_size):
        # Run a batch of requests
        gc.collect()
        initial = tracker.take_snapshot(f'leak_check_batch_{batch}_before')
        
        for i in range(batch_size):
            if P2P_TOOLS_AVAILABLE:
                try:
                    await mcplusplus_workflow_tools.workflow_list(limit=10)
                except Exception as e:
                    logger.debug(f"Request failed (expected): {e}")
            else:
                await anyio.sleep(0.001)
        
        gc.collect()
        final = tracker.take_snapshot(f'leak_check_batch_{batch}_after')
        
        batch_measurements.append({
            'batch': batch,
            'initial_mb': initial['memory_mb'],
            'final_mb': final['memory_mb'],
            'increase_mb': final['memory_mb'] - initial['memory_mb']
        })
    
    # Analyze growth trend
    increases = [b['increase_mb'] for b in batch_measurements]
    avg_increase = sum(increases) / len(increases) if increases else 0
    
    # Check if memory consistently grows (potential leak)
    growing_batches = sum(1 for inc in increases if inc > 0)
    leak_suspected = growing_batches > len(increases) * 0.8  # 80% of batches growing
    
    return {
        'iterations': iterations,
        'batch_size': batch_size,
        'num_batches': len(batch_measurements),
        'avg_increase_per_batch_mb': avg_increase,
        'total_increase_mb': sum(increases),
        'growing_batches': growing_batches,
        'leak_suspected': leak_suspected,
        'batch_measurements': batch_measurements
    }


async def measure_gc_impact(
    tracker: MemoryTracker,
    iterations: int = 1000
) -> Dict[str, Any]:
    """Measure garbage collection impact."""
    logger.info(f"Measuring GC impact ({iterations} iterations)...")
    
    gc_timings = []
    
    # Disable automatic GC
    gc.disable()
    
    try:
        # Run iterations without GC
        tracker.take_snapshot('gc_impact_start')
        
        for i in range(iterations):
            if P2P_TOOLS_AVAILABLE:
                try:
                    await mcplusplus_workflow_tools.workflow_status(
                        workflow_id=f'test-wf-{i}'
                    )
                except Exception as e:
                    logger.debug(f"Request failed (expected): {e}")
            else:
                await anyio.sleep(0.001)
            
            # Force GC every 100 iterations
            if i % 100 == 0:
                before_gc = tracker.take_snapshot(f'before_gc_{i}')
                
                gc_start = time.perf_counter()
                gc.collect()
                gc_end = time.perf_counter()
                
                after_gc = tracker.take_snapshot(f'after_gc_{i}')
                
                gc_timings.append({
                    'iteration': i,
                    'gc_time_ms': (gc_end - gc_start) * 1000,
                    'memory_before_mb': before_gc['memory_mb'],
                    'memory_after_mb': after_gc['memory_mb'],
                    'memory_freed_mb': before_gc['memory_mb'] - after_gc['memory_mb']
                })
        
        tracker.take_snapshot('gc_impact_end')
    
    finally:
        # Re-enable automatic GC
        gc.enable()
    
    # Calculate GC statistics
    avg_gc_time = sum(t['gc_time_ms'] for t in gc_timings) / len(gc_timings) if gc_timings else 0
    total_gc_time = sum(t['gc_time_ms'] for t in gc_timings)
    total_freed = sum(t['memory_freed_mb'] for t in gc_timings)
    
    return {
        'iterations': iterations,
        'num_gc_collections': len(gc_timings),
        'avg_gc_time_ms': avg_gc_time,
        'total_gc_time_ms': total_gc_time,
        'total_memory_freed_mb': total_freed,
        'gc_timings': gc_timings
    }


async def run_benchmark(
    tests: List[str],
    iterations: int = 1000,
    runtime: str = 'trio',
    output_file: Optional[str] = None
):
    """
    Run memory usage benchmarks.
    
    Args:
        tests: List of tests to run ('baseline', 'per_request', 'leak_detection', 'gc_impact', 'all')
        iterations: Number of iterations
        runtime: Runtime to test
        output_file: Optional output file for results
    """
    tracker = MemoryTracker()
    
    results = {
        'timestamp': time.time(),
        'config': {
            'tests': tests,
            'iterations': iterations,
            'runtime': runtime
        },
        'tests': {}
    }
    
    # Run requested tests
    if 'baseline' in tests or 'all' in tests:
        results['tests']['baseline'] = await measure_baseline_memory(tracker)
    
    if 'per_request' in tests or 'all' in tests:
        results['tests']['per_request'] = await measure_memory_per_request(
            tracker, runtime, iterations
        )
    
    if 'leak_detection' in tests or 'all' in tests:
        results['tests']['leak_detection'] = await detect_memory_leaks(
            tracker, iterations
        )
    
    if 'gc_impact' in tests or 'all' in tests:
        results['tests']['gc_impact'] = await measure_gc_impact(tracker, iterations)
    
    # Add overall memory stats
    results['overall_stats'] = tracker.get_stats()
    
    # Print results
    print_results(results)
    
    # Save to file if requested
    if output_file:
        save_results(results, output_file)
    
    return results


def print_results(results: Dict[str, Any]):
    """Print benchmark results in a readable format."""
    print("\n" + "=" * 80)
    print("MEMORY USAGE BENCHMARK RESULTS (Phase 3.2)")
    print("=" * 80)
    
    config = results['config']
    print(f"\nConfiguration:")
    print(f"  Tests: {', '.join(config['tests'])}")
    print(f"  Iterations: {config['iterations']}")
    print(f"  Runtime: {config['runtime']}")
    
    # Per-test results
    for test_name, test_result in results['tests'].items():
        print("\n" + "-" * 80)
        print(f"Test: {test_name.upper().replace('_', ' ')}")
        print("-" * 80)
        
        if test_name == 'baseline':
            print(f"\nInitial memory: {test_result['initial_mb']:.2f} MB")
            print(f"Final memory: {test_result['final_mb']:.2f} MB")
            status = "✅ Stable" if test_result['stable'] else "⚠️ Unstable"
            print(f"Status: {status}")
        
        elif test_name == 'per_request':
            print(f"\nInitial memory: {test_result['initial_mb']:.2f} MB")
            print(f"Final memory: {test_result['final_mb']:.2f} MB")
            print(f"Memory increase: {test_result['increase_mb']:.2f} MB")
            print(f"Memory per request: {test_result['memory_per_request_kb']:.3f} KB")
        
        elif test_name == 'leak_detection':
            print(f"\nBatches tested: {test_result['num_batches']}")
            print(f"Average increase per batch: {test_result['avg_increase_per_batch_mb']:.3f} MB")
            print(f"Total increase: {test_result['total_increase_mb']:.2f} MB")
            print(f"Growing batches: {test_result['growing_batches']}/{test_result['num_batches']}")
            
            status = "⚠️ LEAK SUSPECTED" if test_result['leak_suspected'] else "✅ No leak detected"
            print(f"Status: {status}")
        
        elif test_name == 'gc_impact':
            print(f"\nGC collections: {test_result['num_gc_collections']}")
            print(f"Average GC time: {test_result['avg_gc_time_ms']:.2f} ms")
            print(f"Total GC time: {test_result['total_gc_time_ms']:.2f} ms")
            print(f"Total memory freed: {test_result['total_memory_freed_mb']:.2f} MB")
    
    # Overall stats
    if 'overall_stats' in results:
        stats = results['overall_stats']
        print("\n" + "-" * 80)
        print("Overall Memory Statistics")
        print("-" * 80)
        print(f"\nBaseline: {stats.get('baseline_mb', 0):.2f} MB")
        print(f"Peak: {stats.get('peak_mb', 0):.2f} MB")
        print(f"Average: {stats.get('avg_mb', 0):.2f} MB")
        print(f"Growth: {stats.get('growth_mb', 0):.2f} MB")
        print(f"Measurements taken: {stats.get('count', 0)}")
    
    print("\n" + "=" * 80 + "\n")


def save_results(results: Dict[str, Any], output_file: str):
    """Save benchmark results to a JSON file."""
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Remove detailed measurements to reduce file size
    if 'overall_stats' in results and 'measurements' in results['overall_stats']:
        del results['overall_stats']['measurements']
    
    if 'leak_detection' in results.get('tests', {}):
        if 'batch_measurements' in results['tests']['leak_detection']:
            # Keep only first and last 5 batch measurements
            measurements = results['tests']['leak_detection']['batch_measurements']
            if len(measurements) > 10:
                results['tests']['leak_detection']['batch_measurements'] = \
                    measurements[:5] + measurements[-5:]
    
    if 'gc_impact' in results.get('tests', {}):
        if 'gc_timings' in results['tests']['gc_impact']:
            # Keep only summary, remove detailed timings
            del results['tests']['gc_impact']['gc_timings']
    
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    logger.info(f"Results saved to {output_file}")


async def main():
    """Main entry point for the benchmark."""
    parser = argparse.ArgumentParser(
        description='Benchmark memory usage (Phase 3.2)'
    )
    parser.add_argument(
        '--test',
        type=str,
        choices=['baseline', 'per_request', 'leak_detection', 'gc_impact', 'all'],
        default='all',
        help='Test to run (default: all)'
    )
    parser.add_argument(
        '--iterations',
        type=int,
        default=1000,
        help='Number of iterations (default: 1000)'
    )
    parser.add_argument(
        '--runtime',
        type=str,
        choices=['trio', 'fastapi'],
        default='trio',
        help='Runtime to test (default: trio)'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Output file for results (JSON)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Determine tests to run
    if args.test == 'all':
        tests = ['all']
    else:
        tests = [args.test]
    
    # Run benchmark
    await run_benchmark(
        tests=tests,
        iterations=args.iterations,
        runtime=args.runtime,
        output_file=args.output
    )


if __name__ == '__main__':
    anyio.run(main)
