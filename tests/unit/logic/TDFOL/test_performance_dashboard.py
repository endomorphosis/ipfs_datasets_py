"""
Comprehensive tests for TDFOL Performance Dashboard

Tests cover:
1. Metrics collection (proof recording, custom metrics)
2. Statistics calculation (aggregation, percentiles)
3. Strategy comparison
4. HTML generation
5. JSON export
6. Edge cases and error handling
"""

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from ipfs_datasets_py.logic.TDFOL.performance_dashboard import (
    AggregatedStats,
    MetricType,
    PerformanceDashboard,
    ProofMetrics,
    TimeSeriesMetric,
    get_global_dashboard,
    reset_global_dashboard,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@dataclass
class MockProofResult:
    """Mock proof result for testing."""
    formula: Any
    time_ms: float
    status: str
    method: str
    proof_steps: List[Any]
    
    def is_proved(self) -> bool:
        return self.status == "ProofStatus.PROVED"


@pytest.fixture
def dashboard():
    """Create a fresh dashboard for testing."""
    dash = PerformanceDashboard()
    yield dash
    dash.clear()


@pytest.fixture
def sample_proof_result():
    """Create a sample proof result."""
    return MockProofResult(
        formula="P(x) -> Q(x)",
        time_ms=150.5,
        status="ProofStatus.PROVED",
        method="forward_chaining",
        proof_steps=[1, 2, 3]
    )


@pytest.fixture
def temporal_proof_result():
    """Create a temporal logic proof result."""
    return MockProofResult(
        formula="□(P(x) -> Q(x))",
        time_ms=250.0,
        status="ProofStatus.PROVED",
        method="modal_tableaux",
        proof_steps=[1, 2, 3, 4, 5]
    )


@pytest.fixture
def deontic_proof_result():
    """Create a deontic logic proof result."""
    return MockProofResult(
        formula="O(P(x)) -> P(x)",
        time_ms=180.0,
        status="ProofStatus.PROVED",
        method="backward_chaining",
        proof_steps=[1, 2, 3, 4]
    )


@pytest.fixture
def failed_proof_result():
    """Create a failed proof result."""
    return MockProofResult(
        formula="P(x) & ~P(x)",
        time_ms=500.0,
        status="ProofStatus.FAILED",
        method="forward_chaining",
        proof_steps=[]
    )


# ============================================================================
# Test: Initialization
# ============================================================================


def test_dashboard_initialization(dashboard):
    """
    GIVEN: A new PerformanceDashboard
    WHEN: Initializing the dashboard
    THEN: Dashboard is properly initialized with empty state
    """
    assert len(dashboard.proof_metrics) == 0
    assert len(dashboard.timeseries_metrics) == 0
    assert dashboard.start_time > 0
    assert not dashboard._stats_cache_valid


def test_global_dashboard_singleton():
    """
    GIVEN: Multiple calls to get_global_dashboard
    WHEN: Getting the global dashboard instance
    THEN: Returns the same instance each time
    """
    dashboard1 = get_global_dashboard()
    dashboard2 = get_global_dashboard()
    
    assert dashboard1 is dashboard2


def test_reset_global_dashboard():
    """
    GIVEN: A global dashboard with recorded metrics
    WHEN: Resetting the global dashboard
    THEN: Dashboard is cleared
    """
    dashboard = get_global_dashboard()
    dashboard.record_metric("test", 1.0)
    
    reset_global_dashboard()
    
    dashboard = get_global_dashboard()
    assert len(dashboard.proof_metrics) == 0
    assert len(dashboard.timeseries_metrics) == 0


# ============================================================================
# Test: Proof Recording
# ============================================================================


def test_record_single_proof(dashboard, sample_proof_result):
    """
    GIVEN: A dashboard and a proof result
    WHEN: Recording the proof
    THEN: Metrics are properly captured
    """
    dashboard.record_proof(sample_proof_result, metadata={'strategy': 'forward'})
    
    assert len(dashboard.proof_metrics) == 1
    
    metrics = dashboard.proof_metrics[0]
    assert metrics.formula_str == "P(x) -> Q(x)"
    assert metrics.proof_time_ms == 150.5
    assert metrics.success is True
    assert metrics.method == "forward_chaining"
    assert metrics.strategy == "forward"
    assert metrics.num_steps == 3


def test_record_multiple_proofs(dashboard, sample_proof_result, temporal_proof_result):
    """
    GIVEN: A dashboard and multiple proof results
    WHEN: Recording multiple proofs
    THEN: All metrics are captured
    """
    dashboard.record_proof(sample_proof_result, metadata={'strategy': 'forward'})
    dashboard.record_proof(temporal_proof_result, metadata={'strategy': 'tableaux'})
    
    assert len(dashboard.proof_metrics) == 2
    assert dashboard.proof_metrics[0].strategy == 'forward'
    assert dashboard.proof_metrics[1].strategy == 'tableaux'


def test_record_proof_with_cache_hit(dashboard, sample_proof_result):
    """
    GIVEN: A proof result from cache
    WHEN: Recording with cache_hit=True
    THEN: Cache hit is recorded
    """
    dashboard.record_proof(
        sample_proof_result,
        metadata={'strategy': 'forward', 'cache_hit': True}
    )
    
    metrics = dashboard.proof_metrics[0]
    assert metrics.cache_hit is True


def test_record_proof_with_memory_usage(dashboard, sample_proof_result):
    """
    GIVEN: A proof result with memory usage
    WHEN: Recording with memory_mb metadata
    THEN: Memory usage is captured
    """
    dashboard.record_proof(
        sample_proof_result,
        metadata={'strategy': 'forward', 'memory_mb': 256.5}
    )
    
    metrics = dashboard.proof_metrics[0]
    assert metrics.memory_usage_mb == 256.5


def test_record_failed_proof(dashboard, failed_proof_result):
    """
    GIVEN: A failed proof result
    WHEN: Recording the failure
    THEN: Failure is properly recorded
    """
    dashboard.record_proof(failed_proof_result, metadata={'strategy': 'forward'})
    
    metrics = dashboard.proof_metrics[0]
    assert metrics.success is False
    assert metrics.num_steps == 0


def test_formula_type_detection_temporal(dashboard, temporal_proof_result):
    """
    GIVEN: A temporal logic formula
    WHEN: Recording the proof
    THEN: Formula type is detected as 'temporal'
    """
    dashboard.record_proof(temporal_proof_result)
    
    metrics = dashboard.proof_metrics[0]
    assert metrics.formula_type == 'temporal'


def test_formula_type_detection_deontic(dashboard, deontic_proof_result):
    """
    GIVEN: A deontic logic formula
    WHEN: Recording the proof
    THEN: Formula type is detected as 'deontic'
    """
    dashboard.record_proof(deontic_proof_result)
    
    metrics = dashboard.proof_metrics[0]
    assert metrics.formula_type == 'deontic'


def test_formula_type_detection_propositional(dashboard, sample_proof_result):
    """
    GIVEN: A propositional formula
    WHEN: Recording the proof
    THEN: Formula type is detected as 'propositional'
    """
    dashboard.record_proof(sample_proof_result)
    
    metrics = dashboard.proof_metrics[0]
    assert metrics.formula_type == 'propositional'


def test_formula_complexity_calculation(dashboard):
    """
    GIVEN: Formulas with different nesting levels
    WHEN: Recording proofs
    THEN: Complexity is calculated correctly
    """
    simple = MockProofResult("P", 10.0, "ProofStatus.PROVED", "forward", [])
    nested = MockProofResult("((P -> Q) & (Q -> R))", 20.0, "ProofStatus.PROVED", "forward", [])
    
    dashboard.record_proof(simple)
    dashboard.record_proof(nested)
    
    assert dashboard.proof_metrics[0].formula_complexity == 0
    assert dashboard.proof_metrics[1].formula_complexity == 2


# ============================================================================
# Test: Custom Metrics Recording
# ============================================================================


def test_record_custom_metric(dashboard):
    """
    GIVEN: A dashboard
    WHEN: Recording a custom metric
    THEN: Metric is properly stored
    """
    dashboard.record_metric("memory_usage_mb", 256.5, tags={'process': 'prover'})
    
    assert len(dashboard.timeseries_metrics) == 1
    
    metric = dashboard.timeseries_metrics[0]
    assert metric.metric_name == "memory_usage_mb"
    assert metric.value == 256.5
    assert metric.tags == {'process': 'prover'}


def test_record_multiple_custom_metrics(dashboard):
    """
    GIVEN: A dashboard
    WHEN: Recording multiple custom metrics
    THEN: All metrics are stored
    """
    dashboard.record_metric("cpu_usage", 45.2)
    dashboard.record_metric("memory_usage", 512.0)
    dashboard.record_metric("disk_io", 1024.0)
    
    assert len(dashboard.timeseries_metrics) == 3


# ============================================================================
# Test: Statistics Calculation
# ============================================================================


def test_statistics_empty_dashboard(dashboard):
    """
    GIVEN: An empty dashboard
    WHEN: Getting statistics
    THEN: Returns empty statistics
    """
    stats = dashboard.get_statistics()
    
    assert stats['total_proofs'] == 0
    assert stats['successful_proofs'] == 0
    assert stats['failed_proofs'] == 0


def test_statistics_single_proof(dashboard, sample_proof_result):
    """
    GIVEN: A dashboard with one proof
    WHEN: Getting statistics
    THEN: Statistics are calculated correctly
    """
    dashboard.record_proof(sample_proof_result, metadata={'strategy': 'forward'})
    
    stats = dashboard.get_statistics()
    
    assert stats['total_proofs'] == 1
    assert stats['successful_proofs'] == 1
    assert stats['success_rate'] == 1.0
    assert stats['timing']['avg_ms'] == 150.5


def test_statistics_multiple_proofs(dashboard, sample_proof_result, temporal_proof_result, failed_proof_result):
    """
    GIVEN: A dashboard with multiple proofs
    WHEN: Getting statistics
    THEN: Aggregate statistics are correct
    """
    dashboard.record_proof(sample_proof_result, metadata={'strategy': 'forward'})
    dashboard.record_proof(temporal_proof_result, metadata={'strategy': 'tableaux'})
    dashboard.record_proof(failed_proof_result, metadata={'strategy': 'forward'})
    
    stats = dashboard.get_statistics()
    
    assert stats['total_proofs'] == 3
    assert stats['successful_proofs'] == 2
    assert stats['failed_proofs'] == 1
    assert stats['success_rate'] == 2/3


def test_statistics_timing_percentiles(dashboard):
    """
    GIVEN: Multiple proofs with varying times
    WHEN: Getting statistics
    THEN: Percentiles are calculated correctly
    """
    # Create proofs with times: 10, 20, 30, ..., 100 ms
    for i in range(1, 11):
        result = MockProofResult(
            f"P{i}",
            float(i * 10),
            "ProofStatus.PROVED",
            "forward",
            []
        )
        dashboard.record_proof(result)
    
    stats = dashboard.get_statistics()
    
    assert stats['timing']['min_ms'] == 10.0
    assert stats['timing']['max_ms'] == 100.0
    assert stats['timing']['median_ms'] == 55.0  # Median of 10,20,...,100
    assert stats['timing']['p95_ms'] >= 90.0
    assert stats['timing']['p99_ms'] >= 90.0


def test_statistics_cache_metrics(dashboard, sample_proof_result):
    """
    GIVEN: Proofs with cache hits and misses
    WHEN: Getting statistics
    THEN: Cache statistics are correct
    """
    # 3 cache hits (fast)
    for i in range(3):
        dashboard.record_proof(
            MockProofResult(f"P{i}", 10.0, "ProofStatus.PROVED", "forward", []),
            metadata={'cache_hit': True}
        )
    
    # 2 cache misses (slow)
    for i in range(2):
        dashboard.record_proof(
            MockProofResult(f"Q{i}", 100.0, "ProofStatus.PROVED", "forward", []),
            metadata={'cache_hit': False}
        )
    
    stats = dashboard.get_statistics()
    
    assert stats['cache_hits'] == 3
    assert stats['cache_misses'] == 2
    assert stats['cache_hit_rate'] == 0.6
    assert stats['avg_speedup_from_cache'] == 10.0  # 100 / 10


def test_statistics_strategy_breakdown(dashboard):
    """
    GIVEN: Proofs using different strategies
    WHEN: Getting statistics
    THEN: Strategy breakdown is correct
    """
    dashboard.record_proof(
        MockProofResult("P1", 100.0, "ProofStatus.PROVED", "forward", []),
        metadata={'strategy': 'forward'}
    )
    dashboard.record_proof(
        MockProofResult("P2", 200.0, "ProofStatus.PROVED", "backward", []),
        metadata={'strategy': 'backward'}
    )
    dashboard.record_proof(
        MockProofResult("P3", 150.0, "ProofStatus.FAILED", "forward", []),
        metadata={'strategy': 'forward'}
    )
    
    stats = dashboard.get_statistics()
    
    assert stats['strategies']['counts']['forward'] == 2
    assert stats['strategies']['counts']['backward'] == 1
    assert stats['strategies']['success_rates']['forward'] == 0.5  # 1/2
    assert stats['strategies']['success_rates']['backward'] == 1.0  # 1/1


def test_statistics_formula_type_breakdown(dashboard, sample_proof_result, temporal_proof_result, deontic_proof_result):
    """
    GIVEN: Proofs of different formula types
    WHEN: Getting statistics
    THEN: Formula type breakdown is correct
    """
    dashboard.record_proof(sample_proof_result)
    dashboard.record_proof(temporal_proof_result)
    dashboard.record_proof(deontic_proof_result)
    
    stats = dashboard.get_statistics()
    
    assert stats['formula_types']['counts']['propositional'] == 1
    assert stats['formula_types']['counts']['temporal'] == 1
    assert stats['formula_types']['counts']['deontic'] == 1


def test_statistics_caching(dashboard, sample_proof_result):
    """
    GIVEN: Statistics calculated once
    WHEN: Requesting statistics again without new data
    THEN: Cached statistics are returned
    """
    dashboard.record_proof(sample_proof_result)
    
    stats1 = dashboard.get_statistics()
    stats2 = dashboard.get_statistics()
    
    # Should return same object from cache
    assert stats1 == stats2
    assert dashboard._stats_cache_valid


def test_statistics_cache_invalidation(dashboard, sample_proof_result):
    """
    GIVEN: Cached statistics
    WHEN: Recording new proof
    THEN: Cache is invalidated
    """
    dashboard.record_proof(sample_proof_result)
    stats1 = dashboard.get_statistics()
    
    assert dashboard._stats_cache_valid
    
    dashboard.record_proof(sample_proof_result)
    
    assert not dashboard._stats_cache_valid
    
    stats2 = dashboard.get_statistics()
    assert stats2['total_proofs'] == 2


# ============================================================================
# Test: Strategy Comparison
# ============================================================================


def test_compare_strategies_empty(dashboard):
    """
    GIVEN: An empty dashboard
    WHEN: Comparing strategies
    THEN: Returns empty comparison
    """
    comparison = dashboard.compare_strategies()
    
    assert comparison['strategies'] == {}


def test_compare_strategies_single_strategy(dashboard):
    """
    GIVEN: Proofs using a single strategy
    WHEN: Comparing strategies
    THEN: Returns comparison for that strategy
    """
    for i in range(5):
        result = MockProofResult(f"P{i}", float(i * 10), "ProofStatus.PROVED", "forward", [])
        dashboard.record_proof(result, metadata={'strategy': 'forward'})
    
    comparison = dashboard.compare_strategies()
    
    assert 'forward' in comparison['strategies']
    forward = comparison['strategies']['forward']
    
    assert forward['count'] == 5
    assert forward['success_rate'] == 1.0
    assert forward['avg_time_ms'] == 20.0  # (0+10+20+30+40)/5


def test_compare_strategies_multiple_strategies(dashboard):
    """
    GIVEN: Proofs using multiple strategies
    WHEN: Comparing strategies
    THEN: Returns comparison for all strategies
    """
    dashboard.record_proof(
        MockProofResult("P1", 100.0, "ProofStatus.PROVED", "forward", []),
        metadata={'strategy': 'forward', 'cache_hit': True}
    )
    dashboard.record_proof(
        MockProofResult("P2", 200.0, "ProofStatus.PROVED", "backward", []),
        metadata={'strategy': 'backward', 'cache_hit': False}
    )
    dashboard.record_proof(
        MockProofResult("P3", 150.0, "ProofStatus.FAILED", "tableaux", []),
        metadata={'strategy': 'tableaux', 'cache_hit': False}
    )
    
    comparison = dashboard.compare_strategies()
    
    assert len(comparison['strategies']) == 3
    assert 'forward' in comparison['strategies']
    assert 'backward' in comparison['strategies']
    assert 'tableaux' in comparison['strategies']


def test_compare_strategies_success_rates(dashboard):
    """
    GIVEN: Strategies with different success rates
    WHEN: Comparing strategies
    THEN: Success rates are calculated correctly
    """
    # Forward: 2 success, 1 failure
    dashboard.record_proof(
        MockProofResult("P1", 100.0, "ProofStatus.PROVED", "forward", []),
        metadata={'strategy': 'forward'}
    )
    dashboard.record_proof(
        MockProofResult("P2", 100.0, "ProofStatus.PROVED", "forward", []),
        metadata={'strategy': 'forward'}
    )
    dashboard.record_proof(
        MockProofResult("P3", 100.0, "ProofStatus.FAILED", "forward", []),
        metadata={'strategy': 'forward'}
    )
    
    comparison = dashboard.compare_strategies()
    
    assert comparison['strategies']['forward']['success_rate'] == 2/3


def test_compare_strategies_cache_hit_rates(dashboard):
    """
    GIVEN: Strategies with different cache hit rates
    WHEN: Comparing strategies
    THEN: Cache hit rates are calculated correctly
    """
    # Forward: 2 hits, 1 miss
    dashboard.record_proof(
        MockProofResult("P1", 10.0, "ProofStatus.PROVED", "forward", []),
        metadata={'strategy': 'forward', 'cache_hit': True}
    )
    dashboard.record_proof(
        MockProofResult("P2", 10.0, "ProofStatus.PROVED", "forward", []),
        metadata={'strategy': 'forward', 'cache_hit': True}
    )
    dashboard.record_proof(
        MockProofResult("P3", 100.0, "ProofStatus.PROVED", "forward", []),
        metadata={'strategy': 'forward', 'cache_hit': False}
    )
    
    comparison = dashboard.compare_strategies()
    
    assert comparison['strategies']['forward']['cache_hit_rate'] == 2/3


def test_compare_strategies_timing_statistics(dashboard):
    """
    GIVEN: Strategies with varying proof times
    WHEN: Comparing strategies
    THEN: Timing statistics are correct
    """
    times = [10.0, 20.0, 30.0, 40.0, 50.0]
    
    for time in times:
        dashboard.record_proof(
            MockProofResult(f"P{time}", time, "ProofStatus.PROVED", "forward", []),
            metadata={'strategy': 'forward'}
        )
    
    comparison = dashboard.compare_strategies()
    forward = comparison['strategies']['forward']
    
    assert forward['min_time_ms'] == 10.0
    assert forward['max_time_ms'] == 50.0
    assert forward['avg_time_ms'] == 30.0
    assert forward['median_time_ms'] == 30.0


# ============================================================================
# Test: HTML Generation
# ============================================================================


def test_generate_html_empty_dashboard(dashboard):
    """
    GIVEN: An empty dashboard
    WHEN: Generating HTML
    THEN: HTML is created without errors
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        output_path = f.name
    
    try:
        dashboard.generate_html(output_path)
        
        assert Path(output_path).exists()
        
        content = Path(output_path).read_text()
        assert '<!DOCTYPE html>' in content
        assert 'TDFOL Performance Dashboard' in content
    finally:
        Path(output_path).unlink()


def test_generate_html_with_data(dashboard, sample_proof_result, temporal_proof_result):
    """
    GIVEN: A dashboard with recorded proofs
    WHEN: Generating HTML
    THEN: HTML includes data and charts
    """
    dashboard.record_proof(sample_proof_result, metadata={'strategy': 'forward'})
    dashboard.record_proof(temporal_proof_result, metadata={'strategy': 'tableaux'})
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        output_path = f.name
    
    try:
        dashboard.generate_html(output_path)
        
        content = Path(output_path).read_text()
        
        # Check for key elements
        assert 'Chart.js' in content
        assert 'proofTimesChart' in content
        assert 'strategyTimesChart' in content
        assert 'cacheChart' in content
        
        # Check for data
        assert 'forward' in content
        assert 'tableaux' in content
    finally:
        Path(output_path).unlink()


def test_generate_html_creates_directory(dashboard, sample_proof_result):
    """
    GIVEN: An output path with non-existent directory
    WHEN: Generating HTML
    THEN: Directory is created
    """
    dashboard.record_proof(sample_proof_result)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / 'subdir' / 'dashboard.html'
        
        dashboard.generate_html(str(output_path))
        
        assert output_path.exists()


def test_generate_html_responsive_design(dashboard, sample_proof_result):
    """
    GIVEN: A dashboard with data
    WHEN: Generating HTML
    THEN: HTML includes responsive CSS
    """
    dashboard.record_proof(sample_proof_result)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        output_path = f.name
    
    try:
        dashboard.generate_html(output_path)
        
        content = Path(output_path).read_text()
        
        assert 'viewport' in content
        assert '@media' in content
    finally:
        Path(output_path).unlink()


# ============================================================================
# Test: JSON Export
# ============================================================================


def test_export_json_empty_dashboard(dashboard):
    """
    GIVEN: An empty dashboard
    WHEN: Exporting to JSON
    THEN: JSON is created with empty data
    """
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
        assert data['metadata']['total_proofs'] == 0
    finally:
        Path(output_path).unlink()


def test_export_json_with_data(dashboard, sample_proof_result, temporal_proof_result):
    """
    GIVEN: A dashboard with recorded proofs
    WHEN: Exporting to JSON
    THEN: JSON includes all data
    """
    dashboard.record_proof(sample_proof_result, metadata={'strategy': 'forward'})
    dashboard.record_proof(temporal_proof_result, metadata={'strategy': 'tableaux'})
    dashboard.record_metric('cpu_usage', 45.2)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        output_path = f.name
    
    try:
        dashboard.export_json(output_path)
        
        with open(output_path, 'r') as f:
            data = json.load(f)
        
        assert data['metadata']['total_proofs'] == 2
        assert data['metadata']['total_metrics'] == 3  # 2 from record_proof + 1 custom
        assert len(data['proof_metrics']) == 2
        assert len(data['timeseries_metrics']) == 3
        assert 'statistics' in data
        assert 'strategy_comparison' in data
    finally:
        Path(output_path).unlink()


def test_export_json_valid_structure(dashboard, sample_proof_result):
    """
    GIVEN: A dashboard with data
    WHEN: Exporting to JSON
    THEN: JSON has valid structure
    """
    dashboard.record_proof(sample_proof_result, metadata={'strategy': 'forward'})
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        output_path = f.name
    
    try:
        dashboard.export_json(output_path)
        
        with open(output_path, 'r') as f:
            data = json.load(f)
        
        # Check metadata structure
        assert 'dashboard_start_time' in data['metadata']
        assert 'export_time' in data['metadata']
        assert 'export_datetime' in data['metadata']
        
        # Check proof metrics structure
        proof = data['proof_metrics'][0]
        assert 'formula' in proof
        assert 'proof_time_ms' in proof
        assert 'success' in proof
        assert 'strategy' in proof
        
        # Check statistics structure
        stats = data['statistics']
        assert 'total_proofs' in stats
        assert 'timing' in stats
        assert 'strategies' in stats
    finally:
        Path(output_path).unlink()


def test_export_json_creates_directory(dashboard, sample_proof_result):
    """
    GIVEN: An output path with non-existent directory
    WHEN: Exporting to JSON
    THEN: Directory is created
    """
    dashboard.record_proof(sample_proof_result)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / 'subdir' / 'metrics.json'
        
        dashboard.export_json(str(output_path))
        
        assert output_path.exists()


# ============================================================================
# Test: Dashboard Operations
# ============================================================================


def test_clear_dashboard(dashboard, sample_proof_result):
    """
    GIVEN: A dashboard with recorded metrics
    WHEN: Clearing the dashboard
    THEN: All metrics are removed
    """
    dashboard.record_proof(sample_proof_result)
    dashboard.record_metric('cpu', 50.0)
    
    assert len(dashboard.proof_metrics) > 0
    assert len(dashboard.timeseries_metrics) > 0
    
    dashboard.clear()
    
    assert len(dashboard.proof_metrics) == 0
    assert len(dashboard.timeseries_metrics) == 0
    assert not dashboard._stats_cache_valid


# ============================================================================
# Test: Edge Cases
# ============================================================================


def test_statistics_with_single_value():
    """
    GIVEN: Dashboard with single proof
    WHEN: Calculating percentiles
    THEN: Handles single value gracefully
    """
    dashboard = PerformanceDashboard()
    result = MockProofResult("P", 100.0, "ProofStatus.PROVED", "forward", [])
    dashboard.record_proof(result)
    
    stats = dashboard.get_statistics()
    
    assert stats['timing']['min_ms'] == 100.0
    assert stats['timing']['max_ms'] == 100.0
    assert stats['timing']['median_ms'] == 100.0
    assert stats['timing']['p95_ms'] == 100.0


def test_proof_metrics_to_dict():
    """
    GIVEN: A ProofMetrics instance
    WHEN: Converting to dictionary
    THEN: All fields are included
    """
    metrics = ProofMetrics(
        timestamp=1234567890.0,
        formula_str="P(x)",
        formula_complexity=1,
        proof_time_ms=100.0,
        success=True,
        method="forward",
        strategy="auto",
        cache_hit=False,
        memory_usage_mb=128.0,
        num_steps=5,
        formula_type="propositional",
        metadata={'custom': 'value'}
    )
    
    d = metrics.to_dict()
    
    assert d['formula'] == "P(x)"
    assert d['proof_time_ms'] == 100.0
    assert d['success'] is True
    assert d['metadata']['custom'] == 'value'


def test_timeseries_metric_to_dict():
    """
    GIVEN: A TimeSeriesMetric instance
    WHEN: Converting to dictionary
    THEN: All fields are included
    """
    metric = TimeSeriesMetric(
        timestamp=1234567890.0,
        metric_name="cpu_usage",
        value=45.2,
        tags={'process': 'prover'}
    )
    
    d = metric.to_dict()
    
    assert d['metric'] == "cpu_usage"
    assert d['value'] == 45.2
    assert d['tags']['process'] == 'prover'
    assert 'datetime' in d


def test_histogram_bins_creation(dashboard):
    """
    GIVEN: A list of values
    WHEN: Creating histogram bins
    THEN: Bins are created correctly
    """
    values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    
    bins = dashboard._create_histogram_bins(values, num_bins=5)
    
    assert len(bins) == 5
    assert bins[0]['start'] == 10
    assert bins[-1]['end'] == 100
    
    # Check that all values are counted
    total_count = sum(b['count'] for b in bins)
    assert total_count == len(values)


def test_histogram_bins_single_value(dashboard):
    """
    GIVEN: A list with a single unique value
    WHEN: Creating histogram bins
    THEN: Single bin is created
    """
    values = [50, 50, 50, 50]
    
    bins = dashboard._create_histogram_bins(values, num_bins=5)
    
    assert len(bins) == 1
    assert bins[0]['count'] == 4


def test_histogram_bins_empty_list(dashboard):
    """
    GIVEN: An empty list of values
    WHEN: Creating histogram bins
    THEN: Returns empty list
    """
    bins = dashboard._create_histogram_bins([], num_bins=5)
    
    assert bins == []


# ============================================================================
# Test: Integration with Real Components
# ============================================================================


def test_integration_with_optimized_prover_style_result(dashboard):
    """
    GIVEN: A proof result mimicking OptimizedProver output
    WHEN: Recording the proof
    THEN: All metrics are extracted correctly
    """
    # Simulate OptimizedProver result structure
    result = MagicMock()
    result.formula = "□(P -> Q)"
    result.time_ms = 234.5
    result.status = "ProofStatus.PROVED"
    result.method = "modal_tableaux"
    result.proof_steps = [1, 2, 3, 4]
    result.is_proved.return_value = True
    
    dashboard.record_proof(
        result,
        metadata={
            'strategy': 'tableaux',
            'cache_hit': False,
            'memory_mb': 512.0
        }
    )
    
    metrics = dashboard.proof_metrics[0]
    assert metrics.proof_time_ms == 234.5
    assert metrics.success is True
    assert metrics.num_steps == 4
    assert metrics.memory_usage_mb == 512.0


def test_record_proof_missing_attributes(dashboard):
    """
    GIVEN: A proof result with missing optional attributes
    WHEN: Recording the proof
    THEN: Uses metadata or defaults
    """
    result = MagicMock()
    result.formula = "P"
    del result.time_ms  # Missing attribute
    del result.status  # Missing attribute
    
    dashboard.record_proof(
        result,
        metadata={
            'proof_time_ms': 100.0,
            'success': True,
            'method': 'custom',
            'strategy': 'auto'
        }
    )
    
    metrics = dashboard.proof_metrics[0]
    assert metrics.proof_time_ms == 100.0
    assert metrics.success is True
    assert metrics.method == 'custom'
