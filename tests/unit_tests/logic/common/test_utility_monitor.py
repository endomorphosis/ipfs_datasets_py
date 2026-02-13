"""
Tests for utility monitoring system.
"""

import time
from ipfs_datasets_py.logic.common.utility_monitor import (
    UtilityMonitor,
    track_performance,
    with_caching,
    get_global_stats,
    clear_global_cache,
    reset_global_stats,
)


class TestUtilityMonitor:
    """Test UtilityMonitor functionality."""
    
    def test_initialization(self):
        """
        GIVEN: UtilityMonitor class
        WHEN: Creating monitor instance
        THEN: Monitor is initialized correctly
        """
        monitor = UtilityMonitor()
        stats = monitor.get_stats()
        assert stats == {}
    
    def test_performance_tracking(self):
        """
        GIVEN: Utility monitor
        WHEN: Tracking function performance
        THEN: Statistics are recorded
        """
        monitor = UtilityMonitor()
        
        @monitor.track_performance
        def test_func(x):
            return x * 2
        
        # Call function multiple times
        result1 = test_func(5)
        result2 = test_func(10)
        
        assert result1 == 10
        assert result2 == 20
        
        # Check stats
        stats = monitor.get_stats('test_func')
        assert stats['calls'] == 2
        assert stats['errors'] == 0
        assert stats['total_time'] > 0
        assert 'avg_time' in stats


def test_manual_integration():
    """Manual integration test."""
    print("\n=== Utility Monitor Test ===")
    
    monitor = UtilityMonitor()
    
    @monitor.track_performance
    @monitor.with_caching()
    def process_text(text: str) -> str:
        time.sleep(0.001)  # Simulate work
        return text.upper()
    
    # Test multiple calls
    print("Call 1 (no cache):")
    start = time.time()
    result1 = process_text("hello")
    time1 = time.time() - start
    print(f"  Result: {result1}, Time: {time1*1000:.2f}ms")
    
    print("Call 2 (cached):")
    start = time.time()
    result2 = process_text("hello")
    time2 = time.time() - start
    print(f"  Result: {result2}, Time: {time2*1000:.2f}ms")
    
    # Stats
    stats = monitor.get_stats()
    print(f"\nStatistics:")
    for func_name, func_stats in stats.items():
        print(f"  {func_name}:")
        print(f"    Calls: {func_stats['calls']}")
        print(f"    Avg time: {func_stats.get('avg_time', 0)*1000:.3f}ms")
    
    print("\n✅ Utility monitor working!")


if __name__ == "__main__":
    test_manual_integration()
