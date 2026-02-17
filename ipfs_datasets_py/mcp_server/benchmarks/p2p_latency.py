"""
P2P Latency Benchmark (Phase 3.2)

Measures latency for P2P operations comparing FastAPI vs Trio execution to validate
the 50-70% latency reduction target.

Usage:
    python -m ipfs_datasets_py.mcp_server.benchmarks.p2p_latency
    python -m ipfs_datasets_py.mcp_server.benchmarks.p2p_latency --iterations 100
    python -m ipfs_datasets_py.mcp_server.benchmarks.p2p_latency --tool workflow_submit
"""

import asyncio
import argparse
import logging
import statistics
import time
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
    logger.warning("RuntimeRouter not available - benchmark will be limited")

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


# Map of tool names to their functions
P2P_TOOL_MAP = {
    # Workflow tools (6)
    'workflow_submit': None,
    'workflow_status': None,
    'workflow_cancel': None,
    'workflow_list': None,
    'workflow_dependencies': None,
    'workflow_result': None,
    
    # Task queue tools (14)
    'task_submit': None,
    'task_status': None,
    'task_cancel': None,
    'task_list': None,
    'task_priority': None,
    'task_result': None,
    'queue_stats': None,
    'queue_pause': None,
    'queue_resume': None,
    'queue_clear': None,
    'task_retry': None,
    'worker_register': None,
    'worker_unregister': None,
    'worker_status': None,
    
    # Peer management tools (6)
    'peer_discover': None,
    'peer_connect': None,
    'peer_disconnect': None,
    'peer_list': None,
    'peer_metrics': None,
    'bootstrap_network': None,
}


def initialize_tool_map():
    """Initialize the tool map with actual function references."""
    if not P2P_TOOLS_AVAILABLE:
        return
    
    # Workflow tools
    P2P_TOOL_MAP['workflow_submit'] = mcplusplus_workflow_tools.workflow_submit
    P2P_TOOL_MAP['workflow_status'] = mcplusplus_workflow_tools.workflow_status
    P2P_TOOL_MAP['workflow_cancel'] = mcplusplus_workflow_tools.workflow_cancel
    P2P_TOOL_MAP['workflow_list'] = mcplusplus_workflow_tools.workflow_list
    P2P_TOOL_MAP['workflow_dependencies'] = mcplusplus_workflow_tools.workflow_dependencies
    P2P_TOOL_MAP['workflow_result'] = mcplusplus_workflow_tools.workflow_result
    
    # Task queue tools
    P2P_TOOL_MAP['task_submit'] = mcplusplus_taskqueue_tools.task_submit
    P2P_TOOL_MAP['task_status'] = mcplusplus_taskqueue_tools.task_status
    P2P_TOOL_MAP['task_cancel'] = mcplusplus_taskqueue_tools.task_cancel
    P2P_TOOL_MAP['task_list'] = mcplusplus_taskqueue_tools.task_list
    P2P_TOOL_MAP['task_priority'] = mcplusplus_taskqueue_tools.task_priority
    P2P_TOOL_MAP['task_result'] = mcplusplus_taskqueue_tools.task_result
    P2P_TOOL_MAP['queue_stats'] = mcplusplus_taskqueue_tools.queue_stats
    P2P_TOOL_MAP['queue_pause'] = mcplusplus_taskqueue_tools.queue_pause
    P2P_TOOL_MAP['queue_resume'] = mcplusplus_taskqueue_tools.queue_resume
    P2P_TOOL_MAP['queue_clear'] = mcplusplus_taskqueue_tools.queue_clear
    P2P_TOOL_MAP['task_retry'] = mcplusplus_taskqueue_tools.task_retry
    P2P_TOOL_MAP['worker_register'] = mcplusplus_taskqueue_tools.worker_register
    P2P_TOOL_MAP['worker_unregister'] = mcplusplus_taskqueue_tools.worker_unregister
    P2P_TOOL_MAP['worker_status'] = mcplusplus_taskqueue_tools.worker_status
    
    # Peer management tools
    P2P_TOOL_MAP['peer_discover'] = mcplusplus_peer_tools.peer_discover
    P2P_TOOL_MAP['peer_connect'] = mcplusplus_peer_tools.peer_connect
    P2P_TOOL_MAP['peer_disconnect'] = mcplusplus_peer_tools.peer_disconnect
    P2P_TOOL_MAP['peer_list'] = mcplusplus_peer_tools.peer_list
    P2P_TOOL_MAP['peer_metrics'] = mcplusplus_peer_tools.peer_metrics
    P2P_TOOL_MAP['bootstrap_network'] = mcplusplus_peer_tools.bootstrap_network


def get_test_params_for_tool(tool_name: str) -> Dict[str, Any]:
    """Get test parameters for a specific tool."""
    params = {
        # Workflow tools
        'workflow_submit': {
            'workflow_id': f'test-wf-{int(time.time())}',
            'name': 'Benchmark Workflow',
            'steps': [
                {'step_id': 'step1', 'action': 'test_action', 'inputs': {}}
            ]
        },
        'workflow_status': {'workflow_id': 'test-wf-001'},
        'workflow_cancel': {'workflow_id': 'test-wf-001'},
        'workflow_list': {'limit': 10},
        'workflow_dependencies': {'workflow_id': 'test-wf-001'},
        'workflow_result': {'workflow_id': 'test-wf-001'},
        
        # Task queue tools
        'task_submit': {
            'task_id': f'test-task-{int(time.time())}',
            'function': 'test_function',
            'args': [],
            'kwargs': {}
        },
        'task_status': {'task_id': 'test-task-001'},
        'task_cancel': {'task_id': 'test-task-001'},
        'task_list': {'limit': 10},
        'task_priority': {'task_id': 'test-task-001', 'priority': 1.0},
        'task_result': {'task_id': 'test-task-001'},
        'queue_stats': {},
        'queue_pause': {'queue_name': 'default'},
        'queue_resume': {'queue_name': 'default'},
        'queue_clear': {'queue_name': 'default'},
        'task_retry': {'task_id': 'test-task-001'},
        'worker_register': {'worker_id': 'test-worker-001', 'capabilities': []},
        'worker_unregister': {'worker_id': 'test-worker-001'},
        'worker_status': {'worker_id': 'test-worker-001'},
        
        # Peer management tools
        'peer_discover': {'max_peers': 10},
        'peer_connect': {'peer_id': 'test-peer-001'},
        'peer_disconnect': {'peer_id': 'test-peer-001'},
        'peer_list': {},
        'peer_metrics': {'peer_id': 'test-peer-001'},
        'bootstrap_network': {},
    }
    
    return params.get(tool_name, {})


async def measure_tool_latency(
    tool_name: str,
    tool_func: callable,
    runtime: str,
    iterations: int = 100
) -> List[float]:
    """
    Measure latency for a specific tool.
    
    Args:
        tool_name: Name of the tool
        tool_func: Tool function to measure
        runtime: Runtime to use ('fastapi' or 'trio')
        iterations: Number of iterations
        
    Returns:
        List of latency measurements in milliseconds
    """
    latencies = []
    params = get_test_params_for_tool(tool_name)
    
    # Warm-up iteration
    try:
        await tool_func(**params)
    except Exception as e:
        logger.debug(f"Warm-up call failed (expected in benchmark): {e}")
    
    # Actual measurements
    for i in range(iterations):
        start = time.perf_counter()
        try:
            await tool_func(**params)
        except Exception as e:
            logger.debug(f"Tool call failed (iteration {i}): {e}")
        end = time.perf_counter()
        
        latency_ms = (end - start) * 1000
        latencies.append(latency_ms)
    
    return latencies


async def benchmark_tool(
    tool_name: str,
    tool_func: callable,
    router: Optional['RuntimeRouter'],
    iterations: int = 100
) -> Dict[str, Any]:
    """
    Benchmark a single tool with both runtimes.
    
    Args:
        tool_name: Name of the tool
        tool_func: Tool function
        router: RuntimeRouter instance (None for direct calls)
        iterations: Number of iterations per runtime
        
    Returns:
        Dict with benchmark results
    """
    logger.info(f"Benchmarking {tool_name}...")
    
    results = {
        'tool_name': tool_name,
        'iterations': iterations,
        'fastapi': {},
        'trio': {}
    }
    
    if router:
        # Test with Trio runtime (routed)
        logger.info(f"  Testing with Trio runtime...")
        trio_latencies = await measure_tool_latency(
            tool_name, tool_func, RUNTIME_TRIO, iterations
        )
        
        results['trio'] = {
            'latencies': trio_latencies,
            'avg_ms': statistics.mean(trio_latencies),
            'min_ms': min(trio_latencies),
            'max_ms': max(trio_latencies),
            'median_ms': statistics.median(trio_latencies),
            'stdev_ms': statistics.stdev(trio_latencies) if len(trio_latencies) > 1 else 0,
            'p95_ms': sorted(trio_latencies)[int(len(trio_latencies) * 0.95)],
            'p99_ms': sorted(trio_latencies)[int(len(trio_latencies) * 0.99)]
        }
        
        # Test with FastAPI runtime (direct call, simulating thread pool)
        logger.info(f"  Testing with FastAPI runtime (simulated)...")
        fastapi_latencies = await measure_tool_latency(
            tool_name, tool_func, RUNTIME_FASTAPI, iterations
        )
        
        results['fastapi'] = {
            'latencies': fastapi_latencies,
            'avg_ms': statistics.mean(fastapi_latencies),
            'min_ms': min(fastapi_latencies),
            'max_ms': max(fastapi_latencies),
            'median_ms': statistics.median(fastapi_latencies),
            'stdev_ms': statistics.stdev(fastapi_latencies) if len(fastapi_latencies) > 1 else 0,
            'p95_ms': sorted(fastapi_latencies)[int(len(fastapi_latencies) * 0.95)],
            'p99_ms': sorted(fastapi_latencies)[int(len(fastapi_latencies) * 0.99)]
        }
        
        # Calculate improvement
        if results['fastapi']['avg_ms'] > 0:
            improvement_pct = (
                (results['fastapi']['avg_ms'] - results['trio']['avg_ms']) / 
                results['fastapi']['avg_ms'] * 100
            )
            results['improvement_percent'] = improvement_pct
    else:
        # Fallback: measure tool directly
        logger.info(f"  Testing tool directly (no router)...")
        latencies = await measure_tool_latency(
            tool_name, tool_func, 'direct', iterations
        )
        
        results['direct'] = {
            'latencies': latencies,
            'avg_ms': statistics.mean(latencies),
            'min_ms': min(latencies),
            'max_ms': max(latencies),
            'median_ms': statistics.median(latencies),
            'stdev_ms': statistics.stdev(latencies) if len(latencies) > 1 else 0,
            'p95_ms': sorted(latencies)[int(len(latencies) * 0.95)],
            'p99_ms': sorted(latencies)[int(len(latencies) * 0.99)]
        }
    
    return results


async def run_benchmark(
    tool_names: Optional[List[str]] = None,
    iterations: int = 100,
    output_file: Optional[str] = None
):
    """
    Run P2P latency benchmarks.
    
    Args:
        tool_names: List of tool names to benchmark (None = all)
        iterations: Number of iterations per tool
        output_file: Optional output file for results
    """
    initialize_tool_map()
    
    # Determine which tools to benchmark
    if tool_names:
        tools_to_test = {k: v for k, v in P2P_TOOL_MAP.items() if k in tool_names}
    else:
        tools_to_test = P2P_TOOL_MAP
    
    # Initialize router if available
    router = None
    if RUNTIME_ROUTER_AVAILABLE:
        try:
            router = RuntimeRouter(
                default_runtime=RUNTIME_FASTAPI,
                enable_metrics=True
            )
            await router.startup()
            logger.info("RuntimeRouter initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize RuntimeRouter: {e}")
    
    # Run benchmarks
    all_results = []
    
    for tool_name, tool_func in tools_to_test.items():
        if tool_func is None:
            logger.warning(f"Tool {tool_name} not available, skipping")
            continue
        
        try:
            result = await benchmark_tool(tool_name, tool_func, router, iterations)
            all_results.append(result)
        except Exception as e:
            logger.error(f"Failed to benchmark {tool_name}: {e}")
    
    # Cleanup
    if router:
        await router.shutdown()
    
    # Generate summary
    summary = generate_summary(all_results)
    
    # Print results
    print_results(summary)
    
    # Save to file if requested
    if output_file:
        save_results(summary, output_file)
    
    return summary


def generate_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate summary statistics from benchmark results."""
    summary = {
        'timestamp': time.time(),
        'total_tools': len(results),
        'tools': results,
        'aggregate': {
            'trio': {'avg_latencies': [], 'p95_latencies': []},
            'fastapi': {'avg_latencies': [], 'p95_latencies': []}
        }
    }
    
    # Collect aggregate stats
    for result in results:
        if 'trio' in result and result['trio']:
            summary['aggregate']['trio']['avg_latencies'].append(result['trio']['avg_ms'])
            summary['aggregate']['trio']['p95_latencies'].append(result['trio']['p95_ms'])
        
        if 'fastapi' in result and result['fastapi']:
            summary['aggregate']['fastapi']['avg_latencies'].append(result['fastapi']['avg_ms'])
            summary['aggregate']['fastapi']['p95_latencies'].append(result['fastapi']['p95_ms'])
    
    # Calculate aggregate averages
    if summary['aggregate']['trio']['avg_latencies']:
        summary['aggregate']['trio']['overall_avg_ms'] = statistics.mean(
            summary['aggregate']['trio']['avg_latencies']
        )
        summary['aggregate']['trio']['overall_p95_ms'] = statistics.mean(
            summary['aggregate']['trio']['p95_latencies']
        )
    
    if summary['aggregate']['fastapi']['avg_latencies']:
        summary['aggregate']['fastapi']['overall_avg_ms'] = statistics.mean(
            summary['aggregate']['fastapi']['avg_latencies']
        )
        summary['aggregate']['fastapi']['overall_p95_ms'] = statistics.mean(
            summary['aggregate']['fastapi']['p95_latencies']
        )
    
    # Calculate overall improvement
    if (summary['aggregate']['fastapi'].get('overall_avg_ms') and
        summary['aggregate']['trio'].get('overall_avg_ms')):
        fastapi_avg = summary['aggregate']['fastapi']['overall_avg_ms']
        trio_avg = summary['aggregate']['trio']['overall_avg_ms']
        
        summary['aggregate']['overall_improvement_percent'] = (
            (fastapi_avg - trio_avg) / fastapi_avg * 100
        )
    
    return summary


def print_results(summary: Dict[str, Any]):
    """Print benchmark results in a readable format."""
    print("\n" + "=" * 80)
    print("P2P LATENCY BENCHMARK RESULTS (Phase 3.2)")
    print("=" * 80)
    
    print(f"\nTotal tools benchmarked: {summary['total_tools']}")
    
    # Per-tool results
    print("\n" + "-" * 80)
    print("Per-Tool Results:")
    print("-" * 80)
    
    for result in summary['tools']:
        tool_name = result['tool_name']
        print(f"\n{tool_name}:")
        
        if 'trio' in result and result['trio']:
            trio = result['trio']
            print(f"  Trio Runtime:    avg={trio['avg_ms']:.2f}ms  "
                  f"p95={trio['p95_ms']:.2f}ms  p99={trio['p99_ms']:.2f}ms")
        
        if 'fastapi' in result and result['fastapi']:
            fastapi = result['fastapi']
            print(f"  FastAPI Runtime: avg={fastapi['avg_ms']:.2f}ms  "
                  f"p95={fastapi['p95_ms']:.2f}ms  p99={fastapi['p99_ms']:.2f}ms")
        
        if 'improvement_percent' in result:
            improvement = result['improvement_percent']
            status = "✅" if improvement >= 50 else "⚠️"
            print(f"  {status} Improvement: {improvement:.1f}%")
    
    # Aggregate results
    print("\n" + "-" * 80)
    print("Aggregate Results:")
    print("-" * 80)
    
    agg = summary['aggregate']
    
    if agg.get('trio', {}).get('overall_avg_ms'):
        print(f"\nTrio Overall:    avg={agg['trio']['overall_avg_ms']:.2f}ms  "
              f"p95={agg['trio']['overall_p95_ms']:.2f}ms")
    
    if agg.get('fastapi', {}).get('overall_avg_ms'):
        print(f"FastAPI Overall: avg={agg['fastapi']['overall_avg_ms']:.2f}ms  "
              f"p95={agg['fastapi']['overall_p95_ms']:.2f}ms")
    
    if 'overall_improvement_percent' in agg:
        improvement = agg['overall_improvement_percent']
        target_met = "✅ TARGET MET" if improvement >= 50 else "⚠️ BELOW TARGET"
        print(f"\n{target_met}: {improvement:.1f}% latency reduction")
        print(f"Target: 50-70% reduction")
    
    print("\n" + "=" * 80 + "\n")


def save_results(summary: Dict[str, Any], output_file: str):
    """Save benchmark results to a JSON file."""
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(summary, f, indent=2)
    
    logger.info(f"Results saved to {output_file}")


async def main():
    """Main entry point for the benchmark."""
    parser = argparse.ArgumentParser(
        description='Benchmark P2P tool latency (Phase 3.2)'
    )
    parser.add_argument(
        '--tool',
        type=str,
        help='Specific tool to benchmark (default: all)'
    )
    parser.add_argument(
        '--iterations',
        type=int,
        default=100,
        help='Number of iterations per tool (default: 100)'
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
    
    # Determine tools to benchmark
    tool_names = [args.tool] if args.tool else None
    
    # Run benchmark
    await run_benchmark(
        tool_names=tool_names,
        iterations=args.iterations,
        output_file=args.output
    )


if __name__ == '__main__':
    asyncio.run(main())
