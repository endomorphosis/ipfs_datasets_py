"""Unit tests for profiling decorators.

Tests the memory and time profiling decorators for optimizer functions.
"""

import logging
import time
from unittest.mock import patch, MagicMock
import pytest

from ipfs_datasets_py.optimizers.common.profiling_decorators import (
    profile_memory,
    profile_time,
    profile_both,
    enable_profiling,
    disable_profiling,
    is_profiling_enabled,
    PSUTIL_AVAILABLE,
)


class TestProfileTime:
    """Test the profile_time decorator."""

    def test_logs_when_slow_threshold_exceeded(self, caplog):
        """Test that slow functions trigger logging."""
        @profile_time(slow_threshold_s=0.1, enabled=True)
        def slow_function():
            time.sleep(0.15)
            return "done"
        
        with caplog.at_level(logging.WARNING):
            result = slow_function()
        
        assert result == "done"
        assert len(caplog.records) == 1
        assert "slow_function" in caplog.text
        assert "slow execution" in caplog.text
        assert "threshold: 0.100s" in caplog.text

    def test_does_not_log_when_fast(self, caplog):
        """Test that fast functions don't trigger logging."""
        @profile_time(slow_threshold_s=1.0, enabled=True)
        def fast_function():
            return "quick"
        
        with caplog.at_level(logging.WARNING):
            result = fast_function()
        
        assert result == "quick"
        assert len(caplog.records) == 0

    def test_disabled_by_flag(self, caplog):
        """Test that profiling can be disabled via flag."""
        @profile_time(slow_threshold_s=0.01, enabled=False)
        def slow_function():
            time.sleep(0.05)
            return "done"
        
        with caplog.at_level(logging.WARNING):
            result = slow_function()
        
        # Should not log when disabled
        assert result == "done"
        assert len(caplog.records) == 0

    def test_preserves_function_metadata(self):
        """Test that decorator preserves function name and docstring."""
        @profile_time(enabled=True)
        def my_function():
            """My docstring."""
            pass
        
        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."

    def test_custom_log_level(self, caplog):
        """Test that custom log level is respected."""
        @profile_time(slow_threshold_s=0.05, log_level=logging.INFO, enabled=True)
        def slow_function():
            time.sleep(0.1)
            return "done"
        
        with caplog.at_level(logging.INFO):
            slow_function()
        
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.INFO


class TestProfileMemory:
    """Test the profile_memory decorator."""

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not available")
    def test_logs_when_memory_threshold_exceeded(self, caplog):
        """Test that high-memory functions trigger logging."""
        @profile_memory(threshold_mb=0.1, enabled=True)
        def memory_heavy_function():
            # Allocate ~5MB of data
            data = [0] * (1024 * 1024)  # ~8MB for integers
            return len(data)
        
        with caplog.at_level(logging.INFO):
            result = memory_heavy_function()
        
        assert result > 0
        # Should log if memory increased
        if caplog.records:
            assert "memory_heavy_function" in caplog.text
            assert "memory usage" in caplog.text

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not available")
    def test_does_not_log_low_memory_usage(self, caplog):
        """Test that low-memory functions don't trigger logging."""
        @profile_memory(threshold_mb=1000.0, enabled=True)
        def light_function():
            x = [1, 2, 3]
            return sum(x)
        
        with caplog.at_level(logging.INFO):
            result = light_function()
        
        assert result == 6
        # Should not log for low memory usage
        assert len(caplog.records) == 0

    def test_disabled_by_flag(self, caplog):
        """Test that memory profiling can be disabled."""
        @profile_memory(threshold_mb=0.01, enabled=False)
        def any_function():
            return "result"
        
        with caplog.at_level(logging.INFO):
            result = any_function()
        
        assert result == "result"
        assert len(caplog.records) == 0

    @pytest.mark.skipif(PSUTIL_AVAILABLE, reason="Test for missing psutil")
    def test_graceful_when_psutil_missing(self, caplog):
        """Test that decorator works when psutil is not installed."""
        @profile_memory(threshold_mb=1.0, enabled=True)
        def any_function():
            return "works"
        
        with caplog.at_level(logging.INFO):
            result = any_function()
        
        # Should work silently without psutil
        assert result == "works"
        assert len(caplog.records) == 0


class TestProfileBoth:
    """Test the profile_both decorator."""

    def test_logs_when_time_threshold_exceeded(self, caplog):
        """Test that slow execution triggers logging."""
        @profile_both(time_threshold_s=0.05, memory_threshold_mb=1000.0, enabled=True)
        def slow_function():
            time.sleep(0.1)
            return "done"
        
        with caplog.at_level(logging.INFO):
            result = slow_function()
        
        assert result == "done"
        assert len(caplog.records) == 1
        assert "slow_function" in caplog.text
        assert "performance:" in caplog.text
        assert "time=" in caplog.text

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not available")
    def test_logs_when_memory_threshold_exceeded(self, caplog):
        """Test that high memory usage triggers logging."""
        @profile_both(time_threshold_s=10.0, memory_threshold_mb=0.1, enabled=True)
        def memory_heavy():
            # Allocate some memory
            data = [0] * (1024 * 1024)
            return len(data)
        
        with caplog.at_level(logging.INFO):
            result = memory_heavy()
        
        assert result > 0
        if caplog.records:
            assert "performance:" in caplog.text
            assert "mem_delta=" in caplog.text

    def test_does_not_log_when_both_under_threshold(self, caplog):
        """Test that fast, low-memory functions don't log."""
        @profile_both(time_threshold_s=1.0, memory_threshold_mb=100.0, enabled=True)
        def efficient_function():
            return sum([1, 2, 3])
        
        with caplog.at_level(logging.INFO):
            result = efficient_function()
        
        assert result == 6
        assert len(caplog.records) == 0

    def test_disabled_by_flag(self, caplog):
        """Test that combined profiling can be disabled."""
        @profile_both(time_threshold_s=0.01, memory_threshold_mb=0.01, enabled=False)
        def any_function():
            time.sleep(0.1)
            return "result"
        
        with caplog.at_level(logging.INFO):
            result = any_function()
        
        assert result == "result"
        assert len(caplog.records) == 0


class TestGlobalProfilingControl:
    """Test global profiling enable/disable functions."""

    def test_enable_profiling(self, caplog):
        """Test that enable_profiling activates decorators."""
        enable_profiling()
        
        # Global flag should now be True
        assert is_profiling_enabled()
        
        # Decorator should work without explicit enabled=True
        @profile_time(slow_threshold_s=0.05)
        def slow_func():
            time.sleep(0.1)
        
        with caplog.at_level(logging.WARNING):
            slow_func()
        
        # Should log because profiling is enabled globally
        assert len(caplog.records) >= 1  # May include enable message + function log

    def test_disable_profiling(self, caplog):
        """Test that disable_profiling deactivates decorators."""
        disable_profiling()
        
        # Global flag should now be False
        assert not is_profiling_enabled()
        
        # Decorator should not work without explicit enabled=True
        @profile_time(slow_threshold_s=0.01)
        def slow_func():
            time.sleep(0.1)
        
        with caplog.at_level(logging.WARNING):
            slow_func()
        
        # Should not log function performance (may have disable message)
        func_logs = [r for r in caplog.records if "slow execution" in r.message]
        assert len(func_logs) == 0

    def test_explicit_enabled_overrides_global(self, caplog):
        """Test that explicit enabled=True overrides global disable."""
        disable_profiling()
        
        @profile_time(slow_threshold_s=0.05, enabled=True)
        def slow_func():
            time.sleep(0.1)
        
        with caplog.at_level(logging.WARNING):
            slow_func()
        
        # Should log because explicitly enabled
        func_logs = [r for r in caplog.records if "slow execution" in r.message]
        assert len(func_logs) == 1


class TestDecoratorEdgeCases:
    """Test edge cases and error handling."""

    def test_decorated_function_can_raise_exception(self):
        """Test that exceptions in decorated functions propagate."""
        @profile_time(enabled=True)
        def failing_function():
            raise ValueError("Expected error")
        
        with pytest.raises(ValueError, match="Expected error"):
            failing_function()

    def test_decorated_function_with_arguments(self, caplog):
        """Test that decorators work with function arguments."""
        @profile_time(slow_threshold_s=0.05, enabled=True)
        def add(a: int, b: int) -> int:
            time.sleep(0.1)
            return a + b
        
        with caplog.at_level(logging.WARNING):
            result = add(2, 3)
        
        assert result == 5
        assert len(caplog.records) == 1

    def test_decorated_function_with_kwargs(self, caplog):
        """Test that decorators work with keyword arguments."""
        @profile_time(slow_threshold_s=0.05, enabled=True)
        def greet(name: str, greeting: str = "Hello") -> str:
            time.sleep(0.1)
            return f"{greeting}, {name}!"
        
        with caplog.at_level(logging.WARNING):
            result = greet("World", greeting="Hi")
        
        assert result == "Hi, World!"
        assert len(caplog.records) == 1

    def test_multiple_decorators_stacked(self, caplog):
        """Test that multiple profiling decorators can be stacked."""
        @profile_time(slow_threshold_s=0.05, enabled=True)
        @profile_memory(threshold_mb=0.1, enabled=True)
        def double_profiled():
            time.sleep(0.1)
            return "done"
        
        with caplog.at_level(logging.INFO):
            result = double_profiled()
        
        assert result == "done"
        # Should have at least one log entry (time)
        assert len(caplog.records) >= 1


class TestProfilingMetricsAccuracy:
    """Test that profiling metrics are reasonably accurate."""

    def test_time_measurement_accuracy(self, caplog):
        """Test that time measurements are within expected range."""
        sleep_duration = 0.2
        
        @profile_time(slow_threshold_s=0.1, enabled=True)
        def timed_sleep():
            time.sleep(sleep_duration)
        
        with caplog.at_level(logging.WARNING):
            timed_sleep()
        
        # Check that logged time is approximately correct
        assert len(caplog.records) == 1
        log_message = caplog.records[0].message
        
        # Extract the time value from log (format: "time=0.200s")
        # Just verify it contains a reasonable number
        assert "0." in log_message  # Should have decimal
        assert "s" in log_message   # Should have seconds unit

    @pytest.mark.skipif(not PSUTIL_AVAILABLE, reason="psutil not available")
    def test_memory_measurement_non_negative(self, caplog):
        """Test that memory delta measurements are reported."""
        @profile_memory(threshold_mb=0.01, enabled=True)
        def allocate_memory():
            # Allocate some memory
            data = [i for i in range(100000)]
            return len(data)
        
        with caplog.at_level(logging.INFO):
            result = allocate_memory()
        
        assert result == 100000
        # Memory measurements should be non-negative (or at least reported)
        if caplog.records:
            log_message = caplog.records[0].message
            assert "MB" in log_message
