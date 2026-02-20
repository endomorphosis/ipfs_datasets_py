#!/usr/bin/env python3
"""
Comprehensive demonstration of TDFOL Performance Dashboard

This script demonstrates all features of the performance dashboard:
1. Real-time metrics collection
2. Statistics aggregation
3. Interactive HTML dashboard generation
4. JSON export
5. Strategy comparison

Usage:
    python demonstrate_performance_dashboard.py
    python demonstrate_performance_dashboard.py --num-proofs 100
    python demonstrate_performance_dashboard.py --output-dir ./dashboard_output
"""

import argparse
import random
import sys
import time
from pathlib import Path
from typing import List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from ipfs_datasets_py.logic.TDFOL.performance_dashboard import (
    PerformanceDashboard,
    get_global_dashboard,
)


# ============================================================================
# Mock Proof Results for Demonstration
# ============================================================================


class DemoProofResult:
    """Mock proof result for demonstration."""
    
    def __init__(self, formula: str, time_ms: float, success: bool, method: str, num_steps: int):
        self.formula = formula
        self.time_ms = time_ms
        self.status = "ProofStatus.PROVED" if success else "ProofStatus.FAILED"
        self.method = method
        self.proof_steps = list(range(num_steps))
    
    def is_proved(self) -> bool:
        """Return True when the proof status equals PROVED."""
        return self.status == "ProofStatus.PROVED"


def generate_demo_proofs(num_proofs: int = 50) -> List[tuple]:
    """Generate demo proof results with various characteristics."""
    
    strategies = ['forward', 'backward', 'bidirectional', 'tableaux', 'auto']
    methods = ['forward_chaining', 'backward_chaining', 'modal_tableaux', 'resolution']
    
    formulas = [
        # Propositional
        "P(x) -> Q(x)",
        "P(x) & Q(x)",
        "P(x) | Q(x)",
        "~P(x)",
        "(P(x) -> Q(x)) & (Q(x) -> R(x))",
        
        # Temporal
        "□(P(x) -> Q(x))",
        "◊P(x)",
        "□◊P(x)",
        "P(x) Until Q(x)",
        "Always(P(x))",
        
        # Deontic
        "O(P(x)) -> P(x)",
        "O(P(x) & Q(x))",
        "P(P(x))",
        "F(~P(x))",
        "O(P(x)) & P(Q(x))",
        
        # Modal
        "□(P(x) | ~P(x))",
        "◊□P(x)",
        "□P(x) -> P(x)",
    ]
    
    proofs = []
    
    for i in range(num_proofs):
        formula = random.choice(formulas)
        strategy = random.choice(strategies)
        method = random.choice(methods)
        
        # Simulate cache hits (30% of the time)
        cache_hit = random.random() < 0.3
        
        if cache_hit:
            # Cache hits are fast
            time_ms = random.uniform(1, 10)
            success = True
            num_steps = random.randint(1, 3)
            memory_mb = random.uniform(10, 50)
        else:
            # Regular proofs vary more
            time_ms = random.uniform(10, 500)
            success = random.random() < 0.85  # 85% success rate
            num_steps = random.randint(1, 20) if success else 0
            memory_mb = random.uniform(50, 512)
        
        result = DemoProofResult(formula, time_ms, success, method, num_steps)
        
        metadata = {
            'strategy': strategy,
            'cache_hit': cache_hit,
            'memory_mb': memory_mb,
        }
        
        proofs.append((result, metadata))
        
        # Simulate real-time behavior
        time.sleep(0.01)  # Small delay
    
    return proofs


# ============================================================================
# Demonstration Functions
# ============================================================================


def demonstrate_basic_usage():
    """Demonstrate basic dashboard usage."""
    print("\n" + "="*80)
    print("DEMONSTRATION 1: Basic Usage")
    print("="*80)
    
    # Create dashboard
    dashboard = PerformanceDashboard()
    print("✓ Created performance dashboard")
    
    # Generate and record some proofs
    print("\n→ Generating 20 demo proofs...")
    proofs = generate_demo_proofs(20)
    
    for result, metadata in proofs:
        dashboard.record_proof(result, metadata)
    
    print(f"✓ Recorded {len(proofs)} proofs")
    
    # Get statistics
    print("\n→ Calculating statistics...")
    stats = dashboard.get_statistics()
    
    print(f"\nStatistics Summary:")
    print(f"  Total proofs: {stats['total_proofs']}")
    print(f"  Success rate: {stats['success_rate']:.1%}")
    print(f"  Cache hit rate: {stats['cache_hit_rate']:.1%}")
    print(f"  Avg proof time: {stats['timing']['avg_ms']:.2f}ms")
    print(f"  Median proof time: {stats['timing']['median_ms']:.2f}ms")
    print(f"  P95 proof time: {stats['timing']['p95_ms']:.2f}ms")
    print(f"  P99 proof time: {stats['timing']['p99_ms']:.2f}ms")
    print(f"  Cache speedup: {stats['avg_speedup_from_cache']:.1f}x")
    
    return dashboard


def demonstrate_strategy_comparison(dashboard: PerformanceDashboard):
    """Demonstrate strategy comparison."""
    print("\n" + "="*80)
    print("DEMONSTRATION 2: Strategy Comparison")
    print("="*80)
    
    comparison = dashboard.compare_strategies()
    
    print("\nStrategy Performance Comparison:")
    print(f"{'Strategy':<15} {'Count':<8} {'Success':<10} {'Cache Hit':<12} {'Avg Time':<12}")
    print("-" * 80)
    
    for strategy, metrics in comparison['strategies'].items():
        print(f"{strategy:<15} "
              f"{metrics['count']:<8} "
              f"{metrics['success_rate']*100:>6.1f}%    "
              f"{metrics['cache_hit_rate']*100:>6.1f}%      "
              f"{metrics['avg_time_ms']:>8.2f}ms")
    
    # Find best strategy
    best_strategy = min(
        comparison['strategies'].items(),
        key=lambda x: x[1]['avg_time_ms']
    )
    
    print(f"\n✓ Fastest strategy: {best_strategy[0]} "
          f"({best_strategy[1]['avg_time_ms']:.2f}ms avg)")


def demonstrate_custom_metrics(dashboard: PerformanceDashboard):
    """Demonstrate custom metrics recording."""
    print("\n" + "="*80)
    print("DEMONSTRATION 3: Custom Metrics")
    print("="*80)
    
    print("\n→ Recording custom metrics...")
    
    # Record various custom metrics
    dashboard.record_metric('cpu_usage_percent', 45.2, tags={'process': 'prover'})
    dashboard.record_metric('memory_usage_mb', 512.0, tags={'process': 'prover'})
    dashboard.record_metric('disk_io_mb', 128.5, tags={'operation': 'cache_write'})
    dashboard.record_metric('network_latency_ms', 15.3, tags={'endpoint': 'zkp_server'})
    
    print(f"✓ Recorded {len(dashboard.timeseries_metrics)} time-series metrics")
    
    # Show sample metrics
    print("\nSample metrics:")
    for metric in dashboard.timeseries_metrics[-4:]:
        print(f"  {metric.metric_name}: {metric.value} {metric.tags}")


def demonstrate_html_generation(dashboard: PerformanceDashboard, output_dir: Path):
    """Demonstrate HTML dashboard generation."""
    print("\n" + "="*80)
    print("DEMONSTRATION 4: HTML Dashboard Generation")
    print("="*80)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / 'performance_dashboard.html'
    
    print(f"\n→ Generating HTML dashboard at: {html_path}")
    dashboard.generate_html(str(html_path))
    
    print(f"✓ HTML dashboard generated successfully")
    print(f"  File size: {html_path.stat().st_size / 1024:.1f} KB")
    print(f"\n  Open in browser: file://{html_path.absolute()}")


def demonstrate_json_export(dashboard: PerformanceDashboard, output_dir: Path):
    """Demonstrate JSON export."""
    print("\n" + "="*80)
    print("DEMONSTRATION 5: JSON Export")
    print("="*80)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / 'performance_metrics.json'
    
    print(f"\n→ Exporting metrics to JSON: {json_path}")
    dashboard.export_json(str(json_path))
    
    print(f"✓ Metrics exported successfully")
    print(f"  File size: {json_path.stat().st_size / 1024:.1f} KB")
    
    # Show JSON structure
    import json
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    print(f"\nJSON structure:")
    print(f"  metadata: {len(data['metadata'])} fields")
    print(f"  statistics: {len(data['statistics'])} fields")
    print(f"  proof_metrics: {len(data['proof_metrics'])} records")
    print(f"  timeseries_metrics: {len(data['timeseries_metrics'])} records")
    print(f"  strategy_comparison: {len(data['strategy_comparison']['strategies'])} strategies")


def demonstrate_real_time_monitoring(dashboard: PerformanceDashboard):
    """Demonstrate real-time monitoring scenario."""
    print("\n" + "="*80)
    print("DEMONSTRATION 6: Real-time Monitoring")
    print("="*80)
    
    print("\n→ Simulating real-time proof attempts...")
    
    # Clear previous data
    dashboard.clear()
    
    strategies = ['forward', 'backward', 'tableaux']
    
    for i in range(10):
        # Generate proof
        formula = f"P{i}(x) -> Q{i}(x)"
        strategy = strategies[i % len(strategies)]
        time_ms = random.uniform(50, 200)
        success = random.random() < 0.9
        
        result = DemoProofResult(formula, time_ms, success, 'forward', 5)
        
        dashboard.record_proof(result, metadata={'strategy': strategy})
        
        # Get current stats
        stats = dashboard.get_statistics()
        
        print(f"  Proof {i+1:2d}: {formula:<20} "
              f"[{strategy:<10}] {time_ms:>6.1f}ms "
              f"({'✓' if success else '✗'}) "
              f"| Avg: {stats['timing']['avg_ms']:>6.1f}ms")
        
        time.sleep(0.05)
    
    print(f"\n✓ Completed real-time monitoring simulation")


def demonstrate_performance_analysis():
    """Demonstrate comprehensive performance analysis."""
    print("\n" + "="*80)
    print("DEMONSTRATION 7: Performance Analysis")
    print("="*80)
    
    dashboard = PerformanceDashboard()
    
    # Generate proofs with specific patterns
    print("\n→ Generating proofs with different characteristics...")
    
    # Fast proofs (cached)
    for i in range(20):
        result = DemoProofResult(f"P{i}", random.uniform(1, 5), True, 'cache', 1)
        dashboard.record_proof(result, metadata={'strategy': 'auto', 'cache_hit': True})
    
    # Medium proofs (optimized)
    for i in range(30):
        result = DemoProofResult(f"Q{i}", random.uniform(50, 150), True, 'optimized', 8)
        dashboard.record_proof(result, metadata={'strategy': 'forward', 'cache_hit': False})
    
    # Slow proofs (complex)
    for i in range(10):
        result = DemoProofResult(f"R{i}", random.uniform(300, 500), True, 'tableaux', 20)
        dashboard.record_proof(result, metadata={'strategy': 'tableaux', 'cache_hit': False})
    
    # Failed proofs
    for i in range(5):
        result = DemoProofResult(f"S{i}", random.uniform(400, 600), False, 'failed', 0)
        dashboard.record_proof(result, metadata={'strategy': 'forward', 'cache_hit': False})
    
    stats = dashboard.get_statistics()
    
    print(f"\nPerformance Analysis:")
    print(f"  Total proofs: {stats['total_proofs']}")
    print(f"  Success rate: {stats['success_rate']:.1%}")
    print(f"  Cache hit rate: {stats['cache_hit_rate']:.1%}")
    print(f"  Cache speedup: {stats['avg_speedup_from_cache']:.1f}x")
    
    print(f"\nTiming Distribution:")
    print(f"  Min:    {stats['timing']['min_ms']:>8.2f}ms")
    print(f"  P50:    {stats['timing']['median_ms']:>8.2f}ms")
    print(f"  P95:    {stats['timing']['p95_ms']:>8.2f}ms")
    print(f"  P99:    {stats['timing']['p99_ms']:>8.2f}ms")
    print(f"  Max:    {stats['timing']['max_ms']:>8.2f}ms")
    
    print(f"\nFormula Type Distribution:")
    for ftype, count in stats['formula_types']['counts'].items():
        success_rate = stats['formula_types']['success_rates'][ftype]
        print(f"  {ftype:<15}: {count:>3} proofs ({success_rate:.1%} success)")
    
    return dashboard


def demonstrate_global_dashboard():
    """Demonstrate global dashboard usage."""
    print("\n" + "="*80)
    print("DEMONSTRATION 8: Global Dashboard")
    print("="*80)
    
    print("\n→ Using global dashboard instance...")
    
    # Get global dashboard
    dashboard1 = get_global_dashboard()
    dashboard1.record_metric('test_metric_1', 100.0)
    
    # Get it again (same instance)
    dashboard2 = get_global_dashboard()
    dashboard2.record_metric('test_metric_2', 200.0)
    
    print(f"✓ Global dashboard is singleton: {dashboard1 is dashboard2}")
    print(f"  Total metrics: {len(dashboard2.timeseries_metrics)}")


# ============================================================================
# Main
# ============================================================================


def main():
    """Run all demonstrations."""
    parser = argparse.ArgumentParser(
        description='Demonstrate TDFOL Performance Dashboard features'
    )
    parser.add_argument(
        '--num-proofs',
        type=int,
        default=50,
        help='Number of demo proofs to generate (default: 50)'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='./dashboard_output',
        help='Output directory for dashboard files (default: ./dashboard_output)'
    )
    parser.add_argument(
        '--quick',
        action='store_true',
        help='Run quick demonstration (fewer proofs)'
    )
    
    args = parser.parse_args()
    
    if args.quick:
        args.num_proofs = 20
    
    output_dir = Path(args.output_dir)
    
    print("\n" + "="*80)
    print(" TDFOL PERFORMANCE DASHBOARD - COMPREHENSIVE DEMONSTRATION")
    print("="*80)
    print(f"\nConfiguration:")
    print(f"  Number of proofs: {args.num_proofs}")
    print(f"  Output directory: {output_dir}")
    
    try:
        # Run demonstrations
        dashboard = demonstrate_basic_usage()
        
        # Add more proofs for comprehensive demo
        if args.num_proofs > 20:
            print(f"\n→ Adding {args.num_proofs - 20} more proofs...")
            additional_proofs = generate_demo_proofs(args.num_proofs - 20)
            for result, metadata in additional_proofs:
                dashboard.record_proof(result, metadata)
            print(f"✓ Total proofs: {len(dashboard.proof_metrics)}")
        
        demonstrate_strategy_comparison(dashboard)
        demonstrate_custom_metrics(dashboard)
        demonstrate_html_generation(dashboard, output_dir)
        demonstrate_json_export(dashboard, output_dir)
        demonstrate_real_time_monitoring(dashboard)
        
        # Performance analysis with fresh dashboard
        analysis_dashboard = demonstrate_performance_analysis()
        html_path = output_dir / 'performance_analysis.html'
        analysis_dashboard.generate_html(str(html_path))
        print(f"\n✓ Performance analysis dashboard: {html_path}")
        
        demonstrate_global_dashboard()
        
        # Final summary
        print("\n" + "="*80)
        print(" DEMONSTRATION COMPLETE")
        print("="*80)
        print(f"\nGenerated files:")
        print(f"  📊 {output_dir / 'performance_dashboard.html'}")
        print(f"  📊 {output_dir / 'performance_analysis.html'}")
        print(f"  📄 {output_dir / 'performance_metrics.json'}")
        print(f"\nOpen the HTML files in your browser to view interactive dashboards!")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
