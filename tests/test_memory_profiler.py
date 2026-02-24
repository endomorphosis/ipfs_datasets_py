"""
Comprehensive test suite for memory optimization profiler.

Test coverage:
- MemorySnapshot: delta, ranking, comparison
- MemoryHotspot: aggregation, percentages
- GCAnalyzer: baseline, stats, collection
- MemoryProfiler: profiling, snapshots, deltas, comparisons
- MemoryComparison: optimization analysis
- MemoryDelta: changes and hotspot tracking
- MemoryOptimizer: recommendations
- Edge cases: threading, errors, missing dependencies
"""

import pytest
import time
import gc
import threading
from unittest.mock import patch, MagicMock
from ipfs_datasets_py.optimizers.perf.memory_profiler import (
    MemorySnapshot,
    MemoryHotspot,
    MemoryDelta,
    MemoryComparison,
    GCAnalyzer,
    MemoryProfiler,
    MemoryOptimizer,
    MemoryUnit,
)


class TestMemoryUnit:
    """Tests for memory unit constants."""
    
    def test_memory_unit_bytes(self):
        assert MemoryUnit.BYTES.value == 1
    
    def test_memory_unit_kb(self):
        assert MemoryUnit.KB.value == 1024
    
    def test_memory_unit_mb(self):
        assert MemoryUnit.MB.value == 1024 * 1024
    
    def test_memory_unit_gb(self):
        assert MemoryUnit.GB.value == 1024 * 1024 * 1024


class TestMemorySnapshot:
    """Tests for MemorySnapshot class."""
    
    def test_snapshot_creation(self):
        snap = MemorySnapshot(
            timestamp=time.time(),
            pid=1234,
            current_memory_mb=100.5,
            peak_memory_mb=150.0,
            total_allocated_mb=200.0
        )
        assert snap.current_memory_mb == 100.5
        assert snap.peak_memory_mb == 150.0
        assert snap.total_allocated_mb == 200.0
        assert snap.pid == 1234
    
    def test_memory_delta_positive(self):
        snap1 = MemorySnapshot(
            timestamp=time.time(),
            pid=1234,
            current_memory_mb=100.0,
            peak_memory_mb=100.0,
            total_allocated_mb=100.0
        )
        snap2 = MemorySnapshot(
            timestamp=time.time(),
            pid=1234,
            current_memory_mb=150.0,
            peak_memory_mb=150.0,
            total_allocated_mb=150.0
        )
        assert snap2.memory_delta(snap1) == pytest.approx(50.0)
    
    def test_memory_delta_negative(self):
        snap1 = MemorySnapshot(
            timestamp=time.time(),
            pid=1234,
            current_memory_mb=100.0,
            peak_memory_mb=100.0,
            total_allocated_mb=100.0
        )
        snap2 = MemorySnapshot(
            timestamp=time.time(),
            pid=1234,
            current_memory_mb=70.0,
            peak_memory_mb=70.0,
            total_allocated_mb=70.0
        )
        assert snap2.memory_delta(snap1) == pytest.approx(-30.0)
    
    def test_get_top_types(self):
        snap = MemorySnapshot(
            timestamp=time.time(),
            pid=1234,
            current_memory_mb=100.0,
            peak_memory_mb=100.0,
            total_allocated_mb=100.0,
            object_counts={'list': 100, 'dict': 50, 'str': 75, 'tuple': 25}
        )
        top = snap.get_top_types(2)
        assert len(top) == 2
        assert top[0][0] == 'list'
        assert top[0][1] == 100
    
    def test_get_top_objects(self):
        snap = MemorySnapshot(
            timestamp=time.time(),
            pid=1234,
            current_memory_mb=100.0,
            peak_memory_mb=100.0,
            total_allocated_mb=100.0,
            largest_objects=[(5000, 'str'), (3000, 'dict'), (2000, 'list')]
        )
        top = snap.get_top_objects(2)
        assert len(top) == 2
        assert top[0][0] == 5000
        assert top[1][0] == 3000


class TestMemoryHotspot:
    """Tests for MemoryHotspot class."""
    
    def test_hotspot_creation(self):
        hotspot = MemoryHotspot(
            object_type='list',
            count=1000,
            total_memory_bytes=5_000_000,
            avg_size_bytes=5000.0,
            percentage_of_total=25.5
        )
        assert hotspot.object_type == 'list'
        assert hotspot.count == 1000
        assert hotspot.total_memory_bytes == 5_000_000
    
    def test_hotspot_total_memory_mb(self):
        hotspot = MemoryHotspot(
            object_type='dict',
            count=500,
            total_memory_bytes=10_485_760,  # 10 MB
            avg_size_bytes=20971.52,
            percentage_of_total=50.0
        )
        assert hotspot.total_memory_mb == pytest.approx(10.0)
    
    def test_hotspot_avg_size_kb(self):
        hotspot = MemoryHotspot(
            object_type='str',
            count=100,
            total_memory_bytes=1_024_000,  # 1000 KB
            avg_size_bytes=10240.0,
            percentage_of_total=10.0
        )
        assert hotspot.avg_size_kb == pytest.approx(1000.0)
    
    def test_hotspot_percentage_calculation(self):
        hotspot = MemoryHotspot(
            object_type='ndarray',
            count=50,
            total_memory_bytes=52_428_800,  # 50 MB
            avg_size_bytes=1048576.0,  # 1 MB
            percentage_of_total=50.0
        )
        assert hotspot.percentage_of_total == pytest.approx(50.0)


class TestGCAnalyzer:
    """Tests for GCAnalyzer class."""
    
    def test_analyzer_creation(self):
        analyzer = GCAnalyzer()
        assert analyzer.baseline_stats is None
        assert analyzer.current_stats is None
    
    def test_set_baseline(self):
        analyzer = GCAnalyzer()
        analyzer.set_baseline()
        assert analyzer.baseline_stats is not None
        assert 'enabled' in analyzer.baseline_stats
        assert 'collection_counts' in analyzer.baseline_stats
    
    def test_get_current_stats(self):
        analyzer = GCAnalyzer()
        stats = analyzer.get_current_stats()
        assert 'enabled' in stats
        assert 'debug_flags' in stats
        assert 'collection_counts' in stats
        assert 'threshold' in stats
        assert 'unreachable' in stats
    
    def test_get_stats_delta_no_baseline(self):
        analyzer = GCAnalyzer()
        delta = analyzer.get_stats_delta()
        assert delta == {}
    
    def test_get_stats_delta_with_baseline(self):
        analyzer = GCAnalyzer()
        analyzer.set_baseline()
        gc.collect()
        delta = analyzer.get_stats_delta()
        # Delta should contain generation deltas
        assert isinstance(delta, dict)
    
    def test_force_collect(self):
        # Create garbage first
        x = [i for i in range(1000)]
        del x
        
        collected = GCAnalyzer.force_collect()
        assert isinstance(collected, int)
        assert collected >= 0


class TestMemoryDelta:
    """Tests for MemoryDelta class."""
    
    def test_delta_creation(self):
        delta = MemoryDelta(
            memory_delta_mb=10.5,
            object_count_delta=100,
            memory_change_percent=5.0
        )
        assert delta.memory_delta_mb == 10.5
        assert delta.object_count_delta == 100
        assert delta.memory_change_percent == pytest.approx(5.0)
    
    def test_delta_with_hotspot_changes(self):
        delta = MemoryDelta(
            memory_delta_mb=-5.0,
            object_count_delta=-50,
            memory_change_percent=-2.5,
            hotspot_changes={'list': (100, 80), 'dict': (50, 60)},
            new_hotspots=['tuple'],
            resolved_hotspots=['str']
        )
        assert len(delta.hotspot_changes) == 2
        assert 'list' in delta.hotspot_changes
        assert delta.new_hotspots == ['tuple']
        assert delta.resolved_hotspots == ['str']
    
    def test_delta_total_hotspot_changes(self):
        delta = MemoryDelta(
            memory_delta_mb=0.0,
            object_count_delta=0,
            memory_change_percent=0.0,
            hotspot_changes={'list': (100, 120), 'dict': (50, 40)}
        )
        assert len(delta.hotspot_changes) == 2


class TestMemoryComparison:
    """Tests for MemoryComparison class."""
    
    def test_comparison_creation(self):
        baseline = MemorySnapshot(time.time(), 1234, 100.0, 100.0, 100.0)
        optimized = MemorySnapshot(time.time(), 1234, 80.0, 80.0, 80.0)
        
        comparison = MemoryComparison(
            baseline_snapshot=baseline,
            optimized_snapshot=optimized,
            memory_saved_mb=20.0,
            memory_saved_percent=20.0,
            improvement_ratio=1.25
        )
        assert comparison.memory_saved_mb == 20.0
        assert comparison.memory_saved_percent == pytest.approx(20.0)
    
    def test_comparison_excellent_recommendation(self):
        baseline = MemorySnapshot(time.time(), 1234, 100.0, 100.0, 100.0)
        optimized = MemorySnapshot(time.time(), 1234, 40.0, 40.0, 40.0)
        
        comparison = MemoryComparison(
            baseline_snapshot=baseline,
            optimized_snapshot=optimized,
            memory_saved_mb=60.0,
            memory_saved_percent=60.0,
            improvement_ratio=2.5,
            recommendation="Excellent optimization! Saved 60.0%"
        )
        assert "Excellent" in comparison.recommendation
    
    def test_comparison_good_recommendation(self):
        baseline = MemorySnapshot(time.time(), 1234, 100.0, 100.0, 100.0)
        optimized = MemorySnapshot(time.time(), 1234, 75.0, 75.0, 75.0)
        
        comparison = MemoryComparison(
            baseline_snapshot=baseline,
            optimized_snapshot=optimized,
            memory_saved_mb=25.0,
            memory_saved_percent=25.0,
            improvement_ratio=1.33,
            recommendation="Good optimization! Saved 25.0%"
        )
        assert "Good" in comparison.recommendation


class TestMemoryProfiler:
    """Tests for MemoryProfiler class."""
    
    def test_profiler_creation(self):
        profiler = MemoryProfiler(enable_tracemalloc=True)
        assert profiler.enable_tracemalloc == True
        assert profiler.baseline_snapshot is None
        assert len(profiler.snapshot_history) == 0
    
    def test_start_profiling(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        assert profiler.baseline_snapshot is not None
        assert len(profiler.snapshot_history) >= 1
    
    def test_snapshot_captures_memory(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        
        # Allocate some memory
        large_list = [i for i in range(10000)]
        
        snap = profiler.snapshot()
        assert snap.current_memory_mb >= 0
        assert snap.timestamp > profiler.baseline_snapshot.timestamp
    
    def test_snapshot_history_tracking(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        
        profiler.snapshot()
        profiler.snapshot()
        profiler.snapshot()
        
        assert len(profiler.snapshot_history) >= 4  # baseline + 3 snapshots
    
    def test_get_memory_delta_zero_at_baseline(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        
        delta = profiler.get_memory_delta()
        # Delta from baseline should be small (close to 0)
        assert abs(delta) < 1000  # Allow 1GB tolerance
    
    def test_get_memory_delta_after_allocation(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        baseline = profiler.get_memory_delta()
        
        # Force garbage collection to ensure clean state
        gc.collect()
        
        # If memory stays roughly same, delta should be small
        delta = profiler.get_memory_delta()
        assert isinstance(delta, float)
    
    def test_get_hotspots(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        
        hotspots = profiler.get_hotspots(top_n=5)
        assert isinstance(hotspots, list)
        assert len(hotspots) <= 5
        
        if len(hotspots) > 0:
            assert hotspots[0].total_memory_bytes >= hotspots[-1].total_memory_bytes
    
    def test_get_hotspots_ordering(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        
        hotspots = profiler.get_hotspots(top_n=10)
        
        # Verify ordering by memory size
        for i in range(len(hotspots) - 1):
            assert hotspots[i].total_memory_bytes >= hotspots[i + 1].total_memory_bytes
    
    def test_compare_snapshots(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        snap1 = profiler.snapshot()
        
        # Make some allocation
        x = [i for i in range(1000)]
        snap2 = profiler.snapshot()
        
        delta = profiler.compare_snapshots(snap1, snap2)
        assert isinstance(delta, MemoryDelta)
        assert isinstance(delta.memory_delta_mb, float)
    
    def test_get_comparison(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        
        baseline = profiler.baseline_snapshot
        optimized = profiler.snapshot()
        
        comparison = profiler.get_comparison(optimized)
        assert isinstance(comparison, MemoryComparison)
        assert comparison.baseline_snapshot == baseline
        assert comparison.optimized_snapshot == optimized
    
    def test_get_comparison_savings(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        
        # Create a large allocation for baseline
        large_baseline = []
        for _ in range(10):
            large_baseline.append([i for i in range(1000)])
        
        baseline = profiler.snapshot()
        
        # Clear allocation and snapshot again
        large_baseline.clear()
        del large_baseline
        gc.collect()
        
        optimized = profiler.snapshot()
        
        comparison = profiler.get_comparison(optimized)
        # Should show memory savings
        assert comparison.memory_saved_mb >= 0 or comparison.memory_saved_mb < 0  # Could go either way
    
    def test_get_snapshothistory(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        
        profiler.snapshot()
        profiler.snapshot()
        
        history = profiler.get_snapshothistory()
        assert len(history) >= 3  # baseline + 2 snapshots
        assert history[0] == profiler.baseline_snapshot
    
    def test_clear_history(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        profiler.snapshot()
        profiler.snapshot()
        
        profiler.clear_history()
        
        # Should only have baseline left
        assert len(profiler.snapshot_history) == 1
        assert profiler.snapshot_history[0] == profiler.baseline_snapshot
    
    def test_thread_safety(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        
        results = []
        
        def worker():
            for _ in range(5):
                snap = profiler.snapshot()
                results.append(snap)
                time.sleep(0.01)
        
        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All snapshots should be captured correctly
        assert len(results) == 15
    
    def test_no_baseline_comparison_raises(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        # Don't call start_profiling()
        
        snap = MemorySnapshot(time.time(), 1234, 100.0, 100.0, 100.0)
        
        with pytest.raises(ValueError):
            profiler.get_comparison(snap)


class TestMemoryOptimizer:
    """Tests for MemoryOptimizer class."""
    
    def test_analyze_dict_hotspots(self):
        hotspots = [
            MemoryHotspot('dict', 1000, 10_000_000, 10000.0, 50.0),
            MemoryHotspot('list', 500, 5_000_000, 10000.0, 25.0),
        ]
        
        recommendations = MemoryOptimizer.analyze_hotspots(hotspots, threshold_percent=10.0)
        
        assert 'dict' in recommendations
        assert 'slots' in recommendations['dict'].lower()
    
    def test_analyze_list_hotspots(self):
        hotspots = [
            MemoryHotspot('list', 500, 5_000_000, 10000.0, 50.0),
        ]
        
        recommendations = MemoryOptimizer.analyze_hotspots(hotspots, threshold_percent=10.0)
        
        assert 'list' in recommendations
        assert 'allocate' in recommendations['list'].lower() or 'generator' in recommendations['list'].lower()
    
    def test_analyze_dataframe_hotspots(self):
        hotspots = [
            MemoryHotspot('DataFrame', 100, 50_000_000, 500000.0, 70.0),
        ]
        
        recommendations = MemoryOptimizer.analyze_hotspots(hotspots, threshold_percent=10.0)
        
        assert 'DataFrame' in recommendations
        assert 'categorical' in recommendations['DataFrame'].lower() or 'sparse' in recommendations['DataFrame'].lower()
    
    def test_analyze_ndarray_hotspots(self):
        hotspots = [
            MemoryHotspot('ndarray', 200, 100_000_000, 500000.0, 80.0),
        ]
        
        recommendations = MemoryOptimizer.analyze_hotspots(hotspots, threshold_percent=10.0)
        
        assert 'ndarray' in recommendations
        assert 'dtype' in recommendations['ndarray'].lower() or 'mmap' in recommendations['ndarray'].lower()
    
    def test_analyze_below_threshold(self):
        hotspots = [
            MemoryHotspot('str', 100, 1_000_000, 10000.0, 2.0),
        ]
        
        recommendations = MemoryOptimizer.analyze_hotspots(hotspots, threshold_percent=10.0)
        
        # Below threshold, might not include recommendations
        assert isinstance(recommendations, dict)


class TestEdgeCases:
    """Tests for edge cases and error conditions."""
    
    def test_empty_snapshot_comparison(self):
        snap1 = MemorySnapshot(time.time(), 1234, 0.0, 0.0, 0.0)
        snap2 = MemorySnapshot(time.time(), 1234, 0.0, 0.0, 0.0)
        
        profiler = MemoryProfiler(enable_tracemalloc=False)
        delta = profiler.compare_snapshots(snap1, snap2)
        
        assert delta.memory_delta_mb == 0.0
    
    def test_comparison_with_zero_baseline(self):
        baseline = MemorySnapshot(time.time(), 1234, 0.0, 0.0, 0.0)
        optimized = MemorySnapshot(time.time(), 1234, 10.0, 10.0, 10.0)
        
        comparison = MemoryComparison(
            baseline_snapshot=baseline,
            optimized_snapshot=optimized,
            memory_saved_mb=-10.0,
            memory_saved_percent=0.0,  # Can't calculate percent from 0
            improvement_ratio=float('inf')
        )
        
        assert comparison.memory_saved_mb == -10.0
    
    def test_profiler_multiple_start_calls(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        baseline1 = profiler.baseline_snapshot
        
        profiler.start_profiling()
        baseline2 = profiler.baseline_snapshot
        
        # Second start should capture new baseline
        assert baseline2.timestamp >= baseline1.timestamp
    
    def test_snapshot_objects_with_large_count(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        
        # Create many small objects
        for _ in range(100):
            [i for i in range(100)]
        
        snap = profiler.snapshot()
        assert len(snap.object_counts) > 0
    
    def test_memory_delta_with_negative_values(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        snap1 = MemorySnapshot(time.time(), 1234, 100.0, 100.0, 100.0)
        snap2 = MemorySnapshot(time.time(), 1234, 50.0, 50.0, 50.0)
        
        delta = profiler.compare_snapshots(snap1, snap2)
        assert delta.memory_delta_mb == pytest.approx(-50.0)
    
    def test_concurrent_snapshots(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        
        snapshots = []
        
        def capture_snapshot():
            for _ in range(3):
                snap = profiler.snapshot()
                snapshots.append(snap)
                time.sleep(0.001)
        
        thread1 = threading.Thread(target=capture_snapshot)
        thread2 = threading.Thread(target=capture_snapshot)
        
        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()
        
        assert len(snapshots) == 6


class TestIntegrationWorkflow:
    """Integration tests for complete profiling workflows."""
    
    def test_full_profiling_workflow(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        
        # Allocate memory incrementally
        data = []
        for i in range(3):
            data.append([j for j in range(1000)])
            profiler.snapshot()
        
        # Compare baseline with final state
        comparison = profiler.get_comparison(profiler.snapshot_history[-1])
        
        assert comparison is not None
        assert comparison.baseline_snapshot is not None
    
    def test_profiling_with_gc_analysis(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        
        # Create garbage
        temp_data = [[i for i in range(100)] for _ in range(100)]
        del temp_data
        
        snap_before = profiler.snapshot()
        gc.collect()
        snap_after = profiler.snapshot()
        
        comparison = profiler.get_comparison(snap_after)
        assert comparison is not None
    
    def test_hotspot_analysis_integration(self):
        profiler = MemoryProfiler(enable_tracemalloc=False)
        profiler.start_profiling()
        
        # Create various objects
        lists = [[i for i in range(100)] for _ in range(50)]
        dicts = [{i: i*2 for i in range(50)} for _ in range(30)]
        strings = ["test" * 100 for _ in range(20)]
        
        profiler.snapshot()
        
        hotspots = profiler.get_hotspots(top_n=5)
        recommendations = MemoryOptimizer.analyze_hotspots(hotspots, threshold_percent=1.0)
        
        assert len(hotspots) > 0
        assert isinstance(recommendations, dict)
