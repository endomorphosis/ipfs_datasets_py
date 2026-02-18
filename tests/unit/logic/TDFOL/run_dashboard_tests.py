#!/usr/bin/env python3
"""
Simple test runner for performance dashboard tests (without pytest dependency).

This script runs a subset of critical tests to verify the dashboard works correctly.
"""

import sys
import tempfile
import traceback
from pathlib import Path

# Add to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from ipfs_datasets_py.logic.TDFOL.performance_dashboard import (
    PerformanceDashboard,
    ProofMetrics,
    TimeSeriesMetric,
    get_global_dashboard,
    reset_global_dashboard,
)


class TestResult:
    """Track test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
    
    def record_pass(self, test_name):
        self.passed += 1
        print(f"  ✓ {test_name}")
    
    def record_fail(self, test_name, error):
        self.failed += 1
        self.errors.append((test_name, error))
        print(f"  ✗ {test_name}: {error}")
    
    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*80}")
        print(f"Test Results: {self.passed}/{total} passed")
        if self.failed > 0:
            print(f"\nFailed tests:")
            for name, error in self.errors:
                print(f"  - {name}: {error}")
        return self.failed == 0


class MockProofResult:
    """Mock proof result."""
    def __init__(self, formula, time_ms, success, method, num_steps):
        self.formula = formula
        self.time_ms = time_ms
        self.status = "ProofStatus.PROVED" if success else "ProofStatus.FAILED"
        self.method = method
        self.proof_steps = list(range(num_steps))
    
    def is_proved(self):
        return self.status == "ProofStatus.PROVED"


def test_dashboard_initialization(results):
    """Test dashboard initialization."""
    try:
        dashboard = PerformanceDashboard()
        assert len(dashboard.proof_metrics) == 0
        assert len(dashboard.timeseries_metrics) == 0
        assert dashboard.start_time > 0
        results.record_pass("dashboard_initialization")
    except Exception as e:
        results.record_fail("dashboard_initialization", str(e))


def test_record_proof(results):
    """Test recording a proof."""
    try:
        dashboard = PerformanceDashboard()
        result = MockProofResult("P(x) -> Q(x)", 150.5, True, "forward", 3)
        dashboard.record_proof(result, metadata={'strategy': 'forward'})
        
        assert len(dashboard.proof_metrics) == 1
        metrics = dashboard.proof_metrics[0]
        assert metrics.proof_time_ms == 150.5
        assert metrics.success is True
        assert metrics.strategy == 'forward'
        
        results.record_pass("record_proof")
    except Exception as e:
        results.record_fail("record_proof", str(e))


def test_record_multiple_proofs(results):
    """Test recording multiple proofs."""
    try:
        dashboard = PerformanceDashboard()
        
        for i in range(10):
            result = MockProofResult(f"P{i}", float(i * 10), True, "forward", 5)
            dashboard.record_proof(result, metadata={'strategy': 'forward'})
        
        assert len(dashboard.proof_metrics) == 10
        results.record_pass("record_multiple_proofs")
    except Exception as e:
        results.record_fail("record_multiple_proofs", str(e))


def test_statistics_calculation(results):
    """Test statistics calculation."""
    try:
        dashboard = PerformanceDashboard()
        
        # Add proofs
        for i in range(10):
            result = MockProofResult(f"P{i}", float(i * 10), True, "forward", 5)
            dashboard.record_proof(result, metadata={'strategy': 'forward'})
        
        stats = dashboard.get_statistics()
        
        assert stats['total_proofs'] == 10
        assert stats['successful_proofs'] == 10
        assert stats['success_rate'] == 1.0
        assert 'timing' in stats
        assert 'avg_ms' in stats['timing']
        
        results.record_pass("statistics_calculation")
    except Exception as e:
        results.record_fail("statistics_calculation", str(e))


def test_cache_statistics(results):
    """Test cache statistics calculation."""
    try:
        dashboard = PerformanceDashboard()
        
        # 3 cache hits
        for i in range(3):
            result = MockProofResult(f"P{i}", 10.0, True, "forward", 1)
            dashboard.record_proof(result, metadata={'cache_hit': True})
        
        # 2 cache misses
        for i in range(2):
            result = MockProofResult(f"Q{i}", 100.0, True, "forward", 5)
            dashboard.record_proof(result, metadata={'cache_hit': False})
        
        stats = dashboard.get_statistics()
        
        assert stats['cache_hits'] == 3
        assert stats['cache_misses'] == 2
        assert stats['cache_hit_rate'] == 0.6
        assert stats['avg_speedup_from_cache'] == 10.0
        
        results.record_pass("cache_statistics")
    except Exception as e:
        results.record_fail("cache_statistics", str(e))


def test_strategy_comparison(results):
    """Test strategy comparison."""
    try:
        dashboard = PerformanceDashboard()
        
        # Add proofs with different strategies
        strategies = ['forward', 'backward', 'tableaux']
        for strategy in strategies:
            for i in range(5):
                result = MockProofResult(f"{strategy}{i}", 100.0, True, strategy, 5)
                dashboard.record_proof(result, metadata={'strategy': strategy})
        
        comparison = dashboard.compare_strategies()
        
        assert len(comparison['strategies']) == 3
        assert 'forward' in comparison['strategies']
        assert comparison['strategies']['forward']['count'] == 5
        
        results.record_pass("strategy_comparison")
    except Exception as e:
        results.record_fail("strategy_comparison", str(e))


def test_custom_metrics(results):
    """Test custom metrics recording."""
    try:
        dashboard = PerformanceDashboard()
        
        dashboard.record_metric('cpu_usage', 45.2, tags={'process': 'prover'})
        dashboard.record_metric('memory_usage', 512.0)
        
        assert len(dashboard.timeseries_metrics) == 2
        assert dashboard.timeseries_metrics[0].metric_name == 'cpu_usage'
        assert dashboard.timeseries_metrics[0].value == 45.2
        
        results.record_pass("custom_metrics")
    except Exception as e:
        results.record_fail("custom_metrics", str(e))


def test_html_generation(results):
    """Test HTML dashboard generation."""
    try:
        dashboard = PerformanceDashboard()
        
        # Add some data
        result = MockProofResult("P(x)", 100.0, True, "forward", 5)
        dashboard.record_proof(result, metadata={'strategy': 'forward'})
        
        # Generate HTML
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
            output_path = f.name
        
        try:
            dashboard.generate_html(output_path)
            
            assert Path(output_path).exists()
            
            content = Path(output_path).read_text()
            assert '<!DOCTYPE html>' in content
            assert 'TDFOL Performance Dashboard' in content
            assert 'Chart.js' in content
            
            results.record_pass("html_generation")
        finally:
            Path(output_path).unlink()
            
    except Exception as e:
        results.record_fail("html_generation", str(e))


def test_json_export(results):
    """Test JSON export."""
    try:
        import json
        
        dashboard = PerformanceDashboard()
        
        # Add some data
        result = MockProofResult("P(x)", 100.0, True, "forward", 5)
        dashboard.record_proof(result, metadata={'strategy': 'forward'})
        
        # Export JSON
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            output_path = f.name
        
        try:
            dashboard.export_json(output_path)
            
            assert Path(output_path).exists()
            
            with open(output_path, 'r') as f:
                data = json.load(f)
            
            assert 'metadata' in data
            assert 'statistics' in data
            assert 'proof_metrics' in data
            assert data['metadata']['total_proofs'] == 1
            
            results.record_pass("json_export")
        finally:
            Path(output_path).unlink()
            
    except Exception as e:
        results.record_fail("json_export", str(e))


def test_global_dashboard(results):
    """Test global dashboard."""
    try:
        dashboard1 = get_global_dashboard()
        dashboard2 = get_global_dashboard()
        
        assert dashboard1 is dashboard2
        
        reset_global_dashboard()
        
        results.record_pass("global_dashboard")
    except Exception as e:
        results.record_fail("global_dashboard", str(e))


def test_clear_dashboard(results):
    """Test clearing dashboard."""
    try:
        dashboard = PerformanceDashboard()
        
        result = MockProofResult("P(x)", 100.0, True, "forward", 5)
        dashboard.record_proof(result)
        dashboard.record_metric('cpu', 50.0)
        
        assert len(dashboard.proof_metrics) > 0
        assert len(dashboard.timeseries_metrics) > 0
        
        dashboard.clear()
        
        assert len(dashboard.proof_metrics) == 0
        assert len(dashboard.timeseries_metrics) == 0
        
        results.record_pass("clear_dashboard")
    except Exception as e:
        results.record_fail("clear_dashboard", str(e))


def test_formula_type_detection(results):
    """Test formula type detection."""
    try:
        dashboard = PerformanceDashboard()
        
        # Temporal formula
        temporal = MockProofResult("□(P(x) -> Q(x))", 100.0, True, "tableaux", 5)
        dashboard.record_proof(temporal)
        assert dashboard.proof_metrics[-1].formula_type == 'temporal'
        
        # Deontic formula
        deontic = MockProofResult("O(P(x)) -> P(x)", 100.0, True, "forward", 5)
        dashboard.record_proof(deontic)
        assert dashboard.proof_metrics[-1].formula_type == 'deontic'
        
        # Propositional formula
        prop = MockProofResult("P(x) -> Q(x)", 100.0, True, "forward", 5)
        dashboard.record_proof(prop)
        assert dashboard.proof_metrics[-1].formula_type == 'propositional'
        
        results.record_pass("formula_type_detection")
    except Exception as e:
        results.record_fail("formula_type_detection", str(e))


def main():
    """Run all tests."""
    print("="*80)
    print("TDFOL Performance Dashboard - Test Suite")
    print("="*80)
    print()
    
    results = TestResult()
    
    # Run tests
    print("Running tests...")
    test_dashboard_initialization(results)
    test_record_proof(results)
    test_record_multiple_proofs(results)
    test_statistics_calculation(results)
    test_cache_statistics(results)
    test_strategy_comparison(results)
    test_custom_metrics(results)
    test_html_generation(results)
    test_json_export(results)
    test_global_dashboard(results)
    test_clear_dashboard(results)
    test_formula_type_detection(results)
    
    # Summary
    success = results.summary()
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
