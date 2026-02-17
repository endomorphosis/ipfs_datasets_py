"""
Runtime Comparison Benchmark (Phase 3.2)

Compares runtimes across different workloads: sequential, concurrent, and mixed.
Measures throughput, latency, CPU usage, and memory usage.

Usage:
    python -m ipfs_datasets_py.mcp_server.benchmarks.runtime_comparison
    python -m ipfs_datasets_py.mcp_server.benchmarks.runtime_comparison --concurrency 50
    python -m ipfs_datasets_py.mcp_server.benchmarks.runtime_comparison --workload mixed
"""

import asyncio
import argparse
import logging
import statistics
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
    from ipfs_datasets_py.mcp_server.tools import (
        mcplusplus_workflow_tools,
        mcplusplus_taskqueue_tools,
        mcplusplus_peer_tools
    )
    P2P_TOOLS_AVAILABLE = True
except ImportError:
    P2P_TOOLS_AVAILABLE = False
    logger.warning("P2P tools not available")


class ResourceMonitor:
    """Monitor system resource usage during benchmarks."""
    
    def __init__(self):
        self.process = psutil.Process(os.getpid())
        self.cpu_samples = []
        self.memory_samples = []
        self.monitoring = False
        self.monitor_task = None
    
    async def start_monitoring(self, interval: float = 0.1):
        """Start monitoring resources."""
        self.monitoring = True
        self.cpu_samples = []
        self.memory_samples = []
        self.monitor_task = asyncio.create_task(self._monitor_loop(interval))
    
    async def stop_monitoring(self):
        """Stop monitoring and return stats."""
        self.monitoring = False
        if self.monitor_task:
            await self.monitor_task
        
        return {
            'cpu': {
                'avg_percent': statistics.mean(self.cpu_samples) if self.cpu_samples else 0,
                'max_percent': max(self.cpu_samples) if self.cpu_samples else 0,
                'samples': len(self.cpu_samples)
            },
            'memory': {
                'avg_mb': statistics.mean(self.memory_samples) if self.memory_samples else 0,
                'max_mb': max(self.memory_samples) if self.memory_samples else 0,
                'samples': len(self.memory_samples)
            }
        }
    
    async def _monitor_loop(self, interval: float):
        """Background loop to monitor resources."""
        while self.monitoring:
            try:
                # Get CPU percentage
                cpu_percent = self.process.cpu_percent(interval=None)
                self.cpu_samples.append(cpu_percent)
                
                # Get memory usage in MB
                memory_mb = self.process.memory_info().rss / (1024 * 1024)
                self.memory_samples.append(memory_mb)
                
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"Error monitoring resources: {e}")
                break


async def sequential_workload(
    tools: List[callable],
    iterations: int = 100
) -> Dict[str, Any]:
    """
    Run tools sequentially.
    
    Args:
        tools: List of tool functions to test
        iterations: Number of iterations
        
    Returns:
        Dict with performance metrics
    """
    logger.info(f"Running sequential workload ({iterations} iterations)...")
    
    monitor = ResourceMonitor()
    await monitor.start_monitoring()
    
    latencies = []
    start_time = time.perf_counter()
    
    for i in range(iterations):
        for tool in tools:
            iteration_start = time.perf_counter()
            try:
                # Each tool has its own test params
                await tool()
            except Exception as e:
                logger.debug(f"Tool call failed: {e}")
            iteration_end = time.perf_counter()
            
            latencies.append((iteration_end - iteration_start) * 1000)
    
    end_time = time.perf_counter()
    resources = await monitor.stop_monitoring()
    
    total_time = end_time - start_time
    total_requests = iterations * len(tools)
    
    return {
        'workload': 'sequential',
        'total_requests': total_requests,
        'total_time_sec': total_time,
        'throughput_req_per_sec': total_requests / total_time if total_time > 0 else 0,
        'latency': {
            'avg_ms': statistics.mean(latencies) if latencies else 0,
            'min_ms': min(latencies) if latencies else 0,
            'max_ms': max(latencies) if latencies else 0,
            'p95_ms': sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
            'p99_ms': sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0
        },
        'resources': resources
    }


async def concurrent_workload(
    tools: List[callable],
    concurrency: int = 10,
    iterations: int = 100
) -> Dict[str, Any]:
    """
    Run tools concurrently.
    
    Args:
        tools: List of tool functions to test
        concurrency: Number of concurrent requests
        iterations: Total number of iterations
        
    Returns:
        Dict with performance metrics
    """
    logger.info(f"Running concurrent workload ({iterations} iterations, "
                f"{concurrency} concurrent)...")
    
    monitor = ResourceMonitor()
    await monitor.start_monitoring()
    
    latencies = []
    start_time = time.perf_counter()
    
    # Run batches of concurrent requests
    for batch in range(iterations // concurrency):
        tasks = []
        for _ in range(concurrency):
            # Pick a random tool
            tool = tools[batch % len(tools)]
            
            async def measure_call(tool_func):
                iteration_start = time.perf_counter()
                try:
                    await tool_func()
                except Exception as e:
                    logger.debug(f"Tool call failed: {e}")
                iteration_end = time.perf_counter()
                return (iteration_end - iteration_start) * 1000
            
            tasks.append(measure_call(tool))
        
        # Wait for batch to complete
        batch_latencies = await asyncio.gather(*tasks)
        latencies.extend(batch_latencies)
    
    end_time = time.perf_counter()
    resources = await monitor.stop_monitoring()
    
    total_time = end_time - start_time
    total_requests = len(latencies)
    
    return {
        'workload': 'concurrent',
        'concurrency': concurrency,
        'total_requests': total_requests,
        'total_time_sec': total_time,
        'throughput_req_per_sec': total_requests / total_time if total_time > 0 else 0,
        'latency': {
            'avg_ms': statistics.mean(latencies) if latencies else 0,
            'min_ms': min(latencies) if latencies else 0,
            'max_ms': max(latencies) if latencies else 0,
            'p95_ms': sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
            'p99_ms': sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0
        },
        'resources': resources
    }


async def mixed_workload(
    p2p_tools: List[callable],
    general_tools: List[callable],
    concurrency: int = 10,
    iterations: int = 100
) -> Dict[str, Any]:
    """
    Run mixed P2P and general tools concurrently.
    
    Args:
        p2p_tools: List of P2P tool functions
        general_tools: List of general tool functions
        concurrency: Number of concurrent requests
        iterations: Total number of iterations
        
    Returns:
        Dict with performance metrics
    """
    logger.info(f"Running mixed workload ({iterations} iterations, "
                f"{concurrency} concurrent, P2P:General = 30:70)...")
    
    monitor = ResourceMonitor()
    await monitor.start_monitoring()
    
    p2p_latencies = []
    general_latencies = []
    start_time = time.perf_counter()
    
    # Run batches of concurrent requests
    for batch in range(iterations // concurrency):
        tasks = []
        
        for i in range(concurrency):
            # 30% P2P tools, 70% general tools
            if i < concurrency * 0.3:
                tool = p2p_tools[batch % len(p2p_tools)]
                is_p2p = True
            else:
                tool = general_tools[batch % len(general_tools)]
                is_p2p = False
            
            async def measure_call(tool_func, is_p2p_tool):
                iteration_start = time.perf_counter()
                try:
                    await tool_func()
                except Exception as e:
                    logger.debug(f"Tool call failed: {e}")
                iteration_end = time.perf_counter()
                return ((iteration_end - iteration_start) * 1000, is_p2p_tool)
            
            tasks.append(measure_call(tool, is_p2p))
        
        # Wait for batch to complete
        batch_results = await asyncio.gather(*tasks)
        
        for latency, is_p2p in batch_results:
            if is_p2p:
                p2p_latencies.append(latency)
            else:
                general_latencies.append(latency)
    
    end_time = time.perf_counter()
    resources = await monitor.stop_monitoring()
    
    total_time = end_time - start_time
    total_requests = len(p2p_latencies) + len(general_latencies)
    
    return {
        'workload': 'mixed',
        'concurrency': concurrency,
        'total_requests': total_requests,
        'p2p_requests': len(p2p_latencies),
        'general_requests': len(general_latencies),
        'total_time_sec': total_time,
        'throughput_req_per_sec': total_requests / total_time if total_time > 0 else 0,
        'p2p_latency': {
            'avg_ms': statistics.mean(p2p_latencies) if p2p_latencies else 0,
            'p95_ms': sorted(p2p_latencies)[int(len(p2p_latencies) * 0.95)] if p2p_latencies else 0,
        },
        'general_latency': {
            'avg_ms': statistics.mean(general_latencies) if general_latencies else 0,
            'p95_ms': sorted(general_latencies)[int(len(general_latencies) * 0.95)] if general_latencies else 0,
        },
        'resources': resources
    }


def create_test_tool(tool_name: str, delay_ms: float = 1.0) -> callable:
    """Create a mock test tool with specified delay."""
    async def test_tool():
        await asyncio.sleep(delay_ms / 1000)
        return {'success': True, 'tool': tool_name}
    return test_tool


async def run_benchmark(
    workload: str = 'all',
    concurrency: int = 10,
    iterations: int = 100,
    output_file: Optional[str] = None
):
    """
    Run runtime comparison benchmarks.
    
    Args:
        workload: Workload type ('sequential', 'concurrent', 'mixed', 'all')
        concurrency: Number of concurrent requests
        iterations: Number of iterations
        output_file: Optional output file for results
    """
    results = {
        'timestamp': time.time(),
        'config': {
            'workload': workload,
            'concurrency': concurrency,
            'iterations': iterations
        },
        'workloads': []
    }
    
    # Create mock P2P and general tools
    p2p_tools = [
        create_test_tool('workflow_submit', delay_ms=2.0),
        create_test_tool('task_submit', delay_ms=2.0),
        create_test_tool('peer_discover', delay_ms=2.0),
    ]
    
    general_tools = [
        create_test_tool('general_tool_1', delay_ms=5.0),
        create_test_tool('general_tool_2', delay_ms=5.0),
        create_test_tool('general_tool_3', delay_ms=5.0),
    ]
    
    # Run requested workloads
    if workload in ['sequential', 'all']:
        result = await sequential_workload(p2p_tools, iterations)
        results['workloads'].append(result)
    
    if workload in ['concurrent', 'all']:
        result = await concurrent_workload(p2p_tools, concurrency, iterations)
        results['workloads'].append(result)
    
    if workload in ['mixed', 'all']:
        result = await mixed_workload(
            p2p_tools, general_tools, concurrency, iterations
        )
        results['workloads'].append(result)
    
    # Print results
    print_results(results)
    
    # Save to file if requested
    if output_file:
        save_results(results, output_file)
    
    return results


def print_results(results: Dict[str, Any]):
    """Print benchmark results in a readable format."""
    print("\n" + "=" * 80)
    print("RUNTIME COMPARISON BENCHMARK RESULTS (Phase 3.2)")
    print("=" * 80)
    
    config = results['config']
    print(f"\nConfiguration:")
    print(f"  Workload: {config['workload']}")
    print(f"  Concurrency: {config['concurrency']}")
    print(f"  Iterations: {config['iterations']}")
    
    # Per-workload results
    for workload in results['workloads']:
        print("\n" + "-" * 80)
        print(f"Workload: {workload['workload'].upper()}")
        print("-" * 80)
        
        print(f"\nThroughput: {workload['throughput_req_per_sec']:.2f} req/sec")
        print(f"Total requests: {workload['total_requests']}")
        print(f"Total time: {workload['total_time_sec']:.2f} sec")
        
        if 'latency' in workload:
            lat = workload['latency']
            print(f"\nLatency:")
            print(f"  Average: {lat['avg_ms']:.2f} ms")
            print(f"  Min: {lat['min_ms']:.2f} ms")
            print(f"  Max: {lat['max_ms']:.2f} ms")
            print(f"  P95: {lat['p95_ms']:.2f} ms")
            print(f"  P99: {lat['p99_ms']:.2f} ms")
        
        if 'p2p_latency' in workload:
            print(f"\nP2P Latency:")
            print(f"  Average: {workload['p2p_latency']['avg_ms']:.2f} ms")
            print(f"  P95: {workload['p2p_latency']['p95_ms']:.2f} ms")
            
            print(f"\nGeneral Latency:")
            print(f"  Average: {workload['general_latency']['avg_ms']:.2f} ms")
            print(f"  P95: {workload['general_latency']['p95_ms']:.2f} ms")
        
        if 'resources' in workload:
            res = workload['resources']
            print(f"\nResource Usage:")
            print(f"  CPU: {res['cpu']['avg_percent']:.1f}% (max: {res['cpu']['max_percent']:.1f}%)")
            print(f"  Memory: {res['memory']['avg_mb']:.1f} MB (max: {res['memory']['max_mb']:.1f} MB)")
    
    print("\n" + "=" * 80 + "\n")


def save_results(results: Dict[str, Any], output_file: str):
    """Save benchmark results to a JSON file."""
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    logger.info(f"Results saved to {output_file}")


async def main():
    """Main entry point for the benchmark."""
    parser = argparse.ArgumentParser(
        description='Compare runtime performance across workloads (Phase 3.2)'
    )
    parser.add_argument(
        '--workload',
        type=str,
        choices=['sequential', 'concurrent', 'mixed', 'all'],
        default='all',
        help='Workload type to test (default: all)'
    )
    parser.add_argument(
        '--concurrency',
        type=int,
        default=10,
        help='Number of concurrent requests (default: 10)'
    )
    parser.add_argument(
        '--iterations',
        type=int,
        default=100,
        help='Number of iterations (default: 100)'
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
    
    # Run benchmark
    await run_benchmark(
        workload=args.workload,
        concurrency=args.concurrency,
        iterations=args.iterations,
        output_file=args.output
    )


if __name__ == '__main__':
    asyncio.run(main())
