"""
Concurrent Workflows Benchmark (Phase 3.2)

Tests workflow execution at scale with concurrent workflow submissions.
Validates end-to-end latency, task queue performance, and peer communication.

Usage:
    python -m ipfs_datasets_py.mcp_server.benchmarks.concurrent_workflows
    python -m ipfs_datasets_py.mcp_server.benchmarks.concurrent_workflows --workflows 50
    python -m ipfs_datasets_py.mcp_server.benchmarks.concurrent_workflows --scenario complex
"""

import asyncio
import argparse
import logging
import statistics
import time
from typing import Dict, List, Any, Optional
from pathlib import Path
import json
import uuid

logger = logging.getLogger(__name__)

# Try to import P2P tools
try:
    from ipfs_datasets_py.mcp_server.tools import (
        mcplusplus_workflow_tools,
        mcplusplus_taskqueue_tools
    )
    P2P_TOOLS_AVAILABLE = True
except ImportError:
    P2P_TOOLS_AVAILABLE = False
    logger.warning("P2P tools not available")


def generate_simple_workflow() -> Dict[str, Any]:
    """Generate a simple workflow (2-3 steps)."""
    workflow_id = f"simple-wf-{uuid.uuid4().hex[:8]}"
    return {
        'workflow_id': workflow_id,
        'name': f'Simple Workflow {workflow_id}',
        'steps': [
            {
                'step_id': 'fetch',
                'action': 'fetch_data',
                'inputs': {'url': 'https://example.com/data'}
            },
            {
                'step_id': 'process',
                'action': 'transform',
                'inputs': {},
                'depends_on': ['fetch']
            },
            {
                'step_id': 'store',
                'action': 'store_result',
                'inputs': {},
                'depends_on': ['process']
            }
        ],
        'priority': 1.0
    }


def generate_complex_workflow() -> Dict[str, Any]:
    """Generate a complex workflow (10+ steps with dependencies)."""
    workflow_id = f"complex-wf-{uuid.uuid4().hex[:8]}"
    return {
        'workflow_id': workflow_id,
        'name': f'Complex Workflow {workflow_id}',
        'steps': [
            # Initial fetch steps (parallel)
            {'step_id': 'fetch1', 'action': 'fetch_data', 'inputs': {'source': 'A'}},
            {'step_id': 'fetch2', 'action': 'fetch_data', 'inputs': {'source': 'B'}},
            {'step_id': 'fetch3', 'action': 'fetch_data', 'inputs': {'source': 'C'}},
            
            # Processing steps (depends on fetch)
            {'step_id': 'process1', 'action': 'transform', 'inputs': {}, 'depends_on': ['fetch1']},
            {'step_id': 'process2', 'action': 'transform', 'inputs': {}, 'depends_on': ['fetch2']},
            {'step_id': 'process3', 'action': 'transform', 'inputs': {}, 'depends_on': ['fetch3']},
            
            # Merge step (depends on all processing)
            {'step_id': 'merge', 'action': 'merge_data', 'inputs': {},
             'depends_on': ['process1', 'process2', 'process3']},
            
            # Analysis steps (depends on merge)
            {'step_id': 'analyze1', 'action': 'analyze', 'inputs': {}, 'depends_on': ['merge']},
            {'step_id': 'analyze2', 'action': 'analyze', 'inputs': {}, 'depends_on': ['merge']},
            
            # Final aggregation (depends on analysis)
            {'step_id': 'aggregate', 'action': 'aggregate', 'inputs': {},
             'depends_on': ['analyze1', 'analyze2']},
            
            # Store result
            {'step_id': 'store', 'action': 'store_result', 'inputs': {},
             'depends_on': ['aggregate']}
        ],
        'priority': 1.5
    }


def generate_dag_workflow() -> Dict[str, Any]:
    """Generate a workflow with complex DAG dependencies."""
    workflow_id = f"dag-wf-{uuid.uuid4().hex[:8]}"
    return {
        'workflow_id': workflow_id,
        'name': f'DAG Workflow {workflow_id}',
        'steps': [
            # Layer 1: Root nodes (no dependencies)
            {'step_id': 'root1', 'action': 'init', 'inputs': {}},
            {'step_id': 'root2', 'action': 'init', 'inputs': {}},
            
            # Layer 2: Depends on layer 1
            {'step_id': 'l2_1', 'action': 'process', 'inputs': {}, 'depends_on': ['root1']},
            {'step_id': 'l2_2', 'action': 'process', 'inputs': {}, 'depends_on': ['root1', 'root2']},
            {'step_id': 'l2_3', 'action': 'process', 'inputs': {}, 'depends_on': ['root2']},
            
            # Layer 3: Depends on layer 2
            {'step_id': 'l3_1', 'action': 'transform', 'inputs': {}, 'depends_on': ['l2_1', 'l2_2']},
            {'step_id': 'l3_2', 'action': 'transform', 'inputs': {}, 'depends_on': ['l2_2', 'l2_3']},
            
            # Layer 4: Final merge
            {'step_id': 'final', 'action': 'merge', 'inputs': {}, 'depends_on': ['l3_1', 'l3_2']}
        ],
        'priority': 2.0
    }


async def submit_workflow(workflow: Dict[str, Any]) -> Dict[str, Any]:
    """Submit a workflow and return submission metrics."""
    start = time.perf_counter()
    
    try:
        if P2P_TOOLS_AVAILABLE:
            result = await mcplusplus_workflow_tools.workflow_submit(**workflow)
        else:
            # Mock result
            await asyncio.sleep(0.01)  # Simulate submission
            result = {
                'success': True,
                'workflow_id': workflow['workflow_id'],
                'status': 'submitted'
            }
    except Exception as e:
        logger.error(f"Failed to submit workflow {workflow['workflow_id']}: {e}")
        result = {
            'success': False,
            'workflow_id': workflow['workflow_id'],
            'error': str(e)
        }
    
    end = time.perf_counter()
    
    return {
        'workflow_id': workflow['workflow_id'],
        'submission_latency_ms': (end - start) * 1000,
        'success': result.get('success', False),
        'result': result
    }


async def monitor_workflow(workflow_id: str, timeout: float = 30.0) -> Dict[str, Any]:
    """Monitor workflow until completion or timeout."""
    start = time.perf_counter()
    status_checks = 0
    final_status = 'timeout'
    
    try:
        while (time.perf_counter() - start) < timeout:
            status_checks += 1
            
            if P2P_TOOLS_AVAILABLE:
                status_result = await mcplusplus_workflow_tools.workflow_status(
                    workflow_id=workflow_id
                )
                final_status = status_result.get('status', 'unknown')
                
                if final_status in ['completed', 'failed', 'cancelled']:
                    break
            else:
                # Mock completion
                await asyncio.sleep(0.1)
                final_status = 'completed'
                break
            
            await asyncio.sleep(0.5)  # Check every 500ms
    except Exception as e:
        logger.error(f"Error monitoring workflow {workflow_id}: {e}")
        final_status = 'error'
    
    end = time.perf_counter()
    
    return {
        'workflow_id': workflow_id,
        'execution_time_sec': end - start,
        'status_checks': status_checks,
        'final_status': final_status
    }


async def run_scenario(
    scenario: str,
    num_workflows: int,
    monitor: bool = False
) -> Dict[str, Any]:
    """
    Run a specific workflow scenario.
    
    Args:
        scenario: Scenario name ('simple', 'complex', 'dag', 'mixed')
        num_workflows: Number of workflows to submit
        monitor: Whether to monitor workflow execution
        
    Returns:
        Dict with scenario results
    """
    logger.info(f"Running scenario: {scenario} ({num_workflows} workflows)...")
    
    # Generate workflows
    workflows = []
    for i in range(num_workflows):
        if scenario == 'simple':
            workflows.append(generate_simple_workflow())
        elif scenario == 'complex':
            workflows.append(generate_complex_workflow())
        elif scenario == 'dag':
            workflows.append(generate_dag_workflow())
        elif scenario == 'mixed':
            # Mix of all types
            if i % 3 == 0:
                workflows.append(generate_simple_workflow())
            elif i % 3 == 1:
                workflows.append(generate_complex_workflow())
            else:
                workflows.append(generate_dag_workflow())
    
    # Submit all workflows concurrently
    start_time = time.perf_counter()
    submission_results = await asyncio.gather(*[
        submit_workflow(wf) for wf in workflows
    ])
    submission_time = time.perf_counter() - start_time
    
    # Monitor workflows if requested
    monitoring_results = []
    if monitor:
        workflow_ids = [r['workflow_id'] for r in submission_results if r['success']]
        monitoring_results = await asyncio.gather(*[
            monitor_workflow(wid) for wid in workflow_ids
        ])
    
    # Calculate metrics
    submission_latencies = [r['submission_latency_ms'] for r in submission_results]
    successful_submissions = sum(1 for r in submission_results if r['success'])
    
    results = {
        'scenario': scenario,
        'num_workflows': num_workflows,
        'successful_submissions': successful_submissions,
        'failed_submissions': num_workflows - successful_submissions,
        'submission_time_sec': submission_time,
        'submission_throughput': num_workflows / submission_time if submission_time > 0 else 0,
        'submission_latency': {
            'avg_ms': statistics.mean(submission_latencies) if submission_latencies else 0,
            'min_ms': min(submission_latencies) if submission_latencies else 0,
            'max_ms': max(submission_latencies) if submission_latencies else 0,
            'p95_ms': sorted(submission_latencies)[int(len(submission_latencies) * 0.95)] if submission_latencies else 0,
            'p99_ms': sorted(submission_latencies)[int(len(submission_latencies) * 0.99)] if submission_latencies else 0
        }
    }
    
    if monitoring_results:
        execution_times = [r['execution_time_sec'] for r in monitoring_results]
        total_status_checks = sum(r['status_checks'] for r in monitoring_results)
        
        results['monitoring'] = {
            'workflows_monitored': len(monitoring_results),
            'execution_time': {
                'avg_sec': statistics.mean(execution_times) if execution_times else 0,
                'min_sec': min(execution_times) if execution_times else 0,
                'max_sec': max(execution_times) if execution_times else 0
            },
            'total_status_checks': total_status_checks,
            'final_statuses': {}
        }
        
        # Count final statuses
        for result in monitoring_results:
            status = result['final_status']
            results['monitoring']['final_statuses'][status] = \
                results['monitoring']['final_statuses'].get(status, 0) + 1
    
    return results


async def run_benchmark(
    scenarios: List[str],
    num_workflows: int = 100,
    monitor: bool = False,
    output_file: Optional[str] = None
):
    """
    Run concurrent workflow benchmarks.
    
    Args:
        scenarios: List of scenarios to test
        num_workflows: Number of workflows per scenario
        monitor: Whether to monitor workflow execution
        output_file: Optional output file for results
    """
    results = {
        'timestamp': time.time(),
        'config': {
            'scenarios': scenarios,
            'num_workflows': num_workflows,
            'monitor': monitor
        },
        'scenarios': []
    }
    
    # Run each scenario
    for scenario in scenarios:
        result = await run_scenario(scenario, num_workflows, monitor)
        results['scenarios'].append(result)
    
    # Print results
    print_results(results)
    
    # Save to file if requested
    if output_file:
        save_results(results, output_file)
    
    return results


def print_results(results: Dict[str, Any]):
    """Print benchmark results in a readable format."""
    print("\n" + "=" * 80)
    print("CONCURRENT WORKFLOWS BENCHMARK RESULTS (Phase 3.2)")
    print("=" * 80)
    
    config = results['config']
    print(f"\nConfiguration:")
    print(f"  Workflows per scenario: {config['num_workflows']}")
    print(f"  Monitor execution: {config['monitor']}")
    
    # Per-scenario results
    for scenario in results['scenarios']:
        print("\n" + "-" * 80)
        print(f"Scenario: {scenario['scenario'].upper()}")
        print("-" * 80)
        
        print(f"\nSubmission:")
        print(f"  Successful: {scenario['successful_submissions']}/{scenario['num_workflows']}")
        print(f"  Throughput: {scenario['submission_throughput']:.2f} workflows/sec")
        print(f"  Total time: {scenario['submission_time_sec']:.2f} sec")
        
        lat = scenario['submission_latency']
        print(f"\nSubmission Latency:")
        print(f"  Average: {lat['avg_ms']:.2f} ms")
        print(f"  Min: {lat['min_ms']:.2f} ms")
        print(f"  Max: {lat['max_ms']:.2f} ms")
        print(f"  P95: {lat['p95_ms']:.2f} ms")
        print(f"  P99: {lat['p99_ms']:.2f} ms")
        
        if 'monitoring' in scenario:
            mon = scenario['monitoring']
            print(f"\nExecution Monitoring:")
            print(f"  Workflows monitored: {mon['workflows_monitored']}")
            print(f"  Average execution time: {mon['execution_time']['avg_sec']:.2f} sec")
            print(f"  Total status checks: {mon['total_status_checks']}")
            print(f"  Final statuses:")
            for status, count in mon['final_statuses'].items():
                print(f"    {status}: {count}")
    
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
        description='Benchmark concurrent workflow execution (Phase 3.2)'
    )
    parser.add_argument(
        '--scenario',
        type=str,
        choices=['simple', 'complex', 'dag', 'mixed', 'all'],
        default='all',
        help='Scenario to test (default: all)'
    )
    parser.add_argument(
        '--workflows',
        type=int,
        default=100,
        help='Number of workflows per scenario (default: 100)'
    )
    parser.add_argument(
        '--monitor',
        action='store_true',
        help='Monitor workflow execution (adds overhead)'
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
    
    # Determine scenarios to run
    if args.scenario == 'all':
        scenarios = ['simple', 'complex', 'dag', 'mixed']
    else:
        scenarios = [args.scenario]
    
    # Run benchmark
    await run_benchmark(
        scenarios=scenarios,
        num_workflows=args.workflows,
        monitor=args.monitor,
        output_file=args.output
    )


if __name__ == '__main__':
    asyncio.run(main())
