"""Tests for profiling hooks in common module."""

from __future__ import annotations

import builtins
import json
import logging
import time
from unittest.mock import Mock, patch

import pytest

from ipfs_datasets_py.optimizers.common.structured_logging import DEFAULT_SCHEMA_VERSION

from ipfs_datasets_py.optimizers.common.profiling import (
    ProfileResult,
    ProfilingConfig,
    enable_profiling,
    disable_profiling,
    get_profiling_config,
    set_profiling_config,
    profile_method,
    profile_section,
    profile_batch,
)


class TestProfilingConfig:
    """Tests for ProfilingConfig."""
    
    def test_default_config_disabled(self):
        """Default config has profiling disabled."""
        config = ProfilingConfig()
        assert config.enabled is False
        assert config.memory_profiling is False
        assert config.min_duration_ms == 0.0
        assert config.emit_logs is True
    
    def test_config_with_memory_profiling_without_psutil(self):
        """Config warns but doesn't fail without psutil."""
        # This test assumes psutil may or may not be installed
        config = ProfilingConfig(memory_profiling=True)
        # Should not raise, just potentially disable memory profiling
        assert isinstance(config.memory_profiling, bool)

    def test_config_does_not_swallow_keyboard_interrupt_on_psutil_import(self):
        """KeyboardInterrupt during psutil import should propagate."""
        original_import = builtins.__import__

        def interrupting_import(name, *args, **kwargs):
            if name == "psutil":
                raise KeyboardInterrupt()
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=interrupting_import):
            with pytest.raises(KeyboardInterrupt):
                ProfilingConfig(memory_profiling=True)
    
    def test_set_and_get_global_config(self):
        """Can set and retrieve global profiling config."""
        config = ProfilingConfig(enabled=True, min_duration_ms=5.0)
        set_profiling_config(config)
        
        retrieved = get_profiling_config()
        assert retrieved.enabled is True
        assert retrieved.min_duration_ms == 5.0
        
        # Reset
        set_profiling_config(ProfilingConfig(enabled=False))


class TestProfileResult:
    """Tests for ProfileResult."""
    
    def test_to_dict_minimal(self):
        """ProfileResult.to_dict() with minimal fields."""
        result = ProfileResult(
            section_name="test_section",
            duration_ms=123.45,
        )
        
        d = result.to_dict()
        assert d["section_name"] == "test_section"
        assert d["duration_ms"] == 123.45
        assert "memory_delta_mb" not in d
        assert "peak_memory_mb" not in d
    
    def test_to_dict_with_memory(self):
        """ProfileResult.to_dict() includes memory metrics when set."""
        result = ProfileResult(
            section_name="test_section",
            duration_ms=123.45,
            memory_delta_mb=10.5,
            peak_memory_mb=256.0,
        )
        
        d = result.to_dict()
        assert d["memory_delta_mb"] == 10.5
        assert d["peak_memory_mb"] == 256.0
    
    def test_to_dict_with_metadata(self):
        """ProfileResult.to_dict() includes metadata."""
        result = ProfileResult(
            section_name="test_section",
            duration_ms=100.0,
            metadata={"key": "value", "count": 42},
        )
        
        d = result.to_dict()
        assert d["metadata"] == {"key": "value", "count": 42}
    
    def test_to_dict_rounds_floats(self):
        """ProfileResult.to_dict() rounds float values to 2 decimals."""
        result = ProfileResult(
            section_name="test",
            duration_ms=123.456789,
            memory_delta_mb=10.123456,
        )
        
        d = result.to_dict()
        assert d["duration_ms"] == 123.46
        assert d["memory_delta_mb"] == 10.12


class TestProfileSection:
    """Tests for profile_section context manager."""
    
    def test_profile_section_disabled_has_no_overhead(self):
        """profile_section with disabled config has minimal overhead."""
        config = ProfilingConfig(enabled=False)
        
        with profile_section("test", config=config) as result:
            time.sleep(0.01)
        
        # Duration should still be 0 when disabled
        assert result.duration_ms == 0.0
    
    def test_profile_section_measures_time(self):
        """profile_section measures execution time when enabled."""
        config = ProfilingConfig(enabled=True)
        
        with profile_section("test", config=config) as result:
            time.sleep(0.01)
        
        # Should have measured ~10ms
        assert result.duration_ms >= 9.0  # Allow some variance
        assert result.section_name == "test"
    
    def test_profile_section_captures_metadata(self):
        """profile_section includes provided metadata."""
        config = ProfilingConfig(enabled=True)
        metadata = {"input_size": 100, "domain": "test"}
        
        with profile_section("test", metadata=metadata, config=config) as result:
            pass
        
        assert result.metadata == metadata
    
    def test_profile_section_emits_log(self, caplog):
        """profile_section emits structured JSON log when enabled."""
        caplog.set_level(logging.INFO)
        config = ProfilingConfig(enabled=True, emit_logs=True)
        
        with profile_section("test_operation", config=config):
            time.sleep(0.01)
        
        # Find PROFILING log
        log_records = [r for r in caplog.records if "PROFILING:" in r.message]
        assert len(log_records) == 1
        
        log_msg = log_records[0].message
        json_str = log_msg.split("PROFILING: ")[1]
        payload = json.loads(json_str)
        
        # Verify schema
        assert payload["schema"] == "ipfs_datasets_py.optimizer_log"
        assert payload["schema_version"] == DEFAULT_SCHEMA_VERSION
        assert payload["event"] == "profiling_result"
        assert payload["section_name"] == "test_operation"
        assert payload["duration_ms"] >= 9.0
    
    def test_profile_section_respects_min_duration(self, caplog):
        """profile_section only logs if duration exceeds threshold."""
        caplog.set_level(logging.INFO)
        config = ProfilingConfig(enabled=True, emit_logs=True, min_duration_ms=100.0)
        
        with profile_section("fast_operation", config=config):
            time.sleep(0.01)  # Only ~10ms
        
        # No log should be emitted
        log_records = [r for r in caplog.records if "PROFILING:" in r.message]
        assert len(log_records) == 0
    
    def test_profile_section_handles_exceptions(self):
        """profile_section still profiles even if block raises."""
        config = ProfilingConfig(enabled=True)
        
        with pytest.raises(ValueError):
            with profile_section("failing_op", config=config) as result:
                time.sleep(0.01)
                raise ValueError("test error")
        
        # Duration should still be captured
        assert result.duration_ms >= 9.0
    
    def test_profile_section_logging_errors_suppressed(self, caplog):
        """Logging errors in profile_section are suppressed."""
        caplog.set_level(logging.DEBUG)
        config = ProfilingConfig(enabled=True, emit_logs=True)
        
        with patch("ipfs_datasets_py.optimizers.common.profiling.with_schema", side_effect=RuntimeError("Schema error")):
            with profile_section("test", config=config):
                pass
        
        # Should not raise, but may log at debug level
        debug_msgs = [r.message for r in caplog.records if r.levelname == "DEBUG"]
        assert any("Failed to emit profiling log" in msg for msg in debug_msgs)

    def test_profile_section_does_not_swallow_keyboard_interrupt_in_log_emission(self):
        """KeyboardInterrupt from log emission should propagate."""
        config = ProfilingConfig(enabled=True, emit_logs=True)

        with patch("ipfs_datasets_py.optimizers.common.profiling.with_schema", side_effect=KeyboardInterrupt()):
            with pytest.raises(KeyboardInterrupt):
                with profile_section("test", config=config):
                    pass


class TestProfileMethod:
    """Tests for profile_method decorator."""
    
    def test_profile_method_disabled_no_overhead(self):
        """profile_method with disabled config doesn't profile."""
        config = ProfilingConfig(enabled=False)
        
        @profile_method("test.func", config=config)
        def sample_func(x):
            time.sleep(0.01)
            return x * 2
        
        result = sample_func(5)
        assert result == 10
        # No way to verify profiling didn't happen, but shouldn't raise
    
    def test_profile_method_measures_execution(self, caplog):
        """profile_method measures function execution time."""
        caplog.set_level(logging.INFO)
        config = ProfilingConfig(enabled=True)
        
        @profile_method("test.sample_func", config=config)
        def sample_func(x):
            time.sleep(0.01)
            return x * 2
        
        result = sample_func(5)
        assert result == 10
        
        # Should have emitted profiling log
        log_records = [r for r in caplog.records if "PROFILING:" in r.message]
        assert len(log_records) == 1
        
        log_msg = log_records[0].message
        json_str = log_msg.split("PROFILING: ")[1]
        payload = json.loads(json_str)
        
        assert payload["section_name"] == "test.sample_func"
        assert payload["duration_ms"] >= 9.0
    
    def test_profile_method_uses_function_name_by_default(self, caplog):
        """profile_method uses qualified function name if not specified."""
        caplog.set_level(logging.INFO)
        config = ProfilingConfig(enabled=True)
        
        @profile_method(config=config)
        def my_function():
            pass
        
        my_function()
        
        log_records = [r for r in caplog.records if "PROFILING:" in r.message]
        assert len(log_records) == 1
        
        log_msg = log_records[0].message
        json_str = log_msg.split("PROFILING: ")[1]
        payload = json.loads(json_str)
        
        # Should include module and function name
        assert "my_function" in payload["section_name"]
    
    def test_profile_method_with_include_args(self, caplog):
        """profile_method can include argument metadata."""
        caplog.set_level(logging.INFO)
        config = ProfilingConfig(enabled=True)
        
        @profile_method("test.func", include_args=True, config=config)
        def sample_func(x, y, z=10):
            return x + y + z
        
        result = sample_func(1, 2, z=3)
        assert result == 6
        
        log_records = [r for r in caplog.records if "PROFILING:" in r.message]
        log_msg = log_records[0].message
        json_str = log_msg.split("PROFILING: ")[1]
        payload = json.loads(json_str)
        
        # Should include args_count and kwargs_keys in metadata
        assert "metadata" in payload
        assert payload["metadata"].get("args_count") == 3  # self not included for functions
        assert "kwargs_keys" in payload["metadata"]
    
    def test_profile_method_preserves_function_attributes(self):
        """profile_method preserves __name__, __doc__, etc."""
        config = ProfilingConfig(enabled=True)
        
        @profile_method("test.func", config=config)
        def documented_function(x):
            """This is a documented function."""
            return x
        
        assert documented_function.__name__ == "documented_function"
        assert documented_function.__doc__ == "This is a documented function."


class TestProfileBatch:
    """Tests for profile_batch context manager."""
    
    def test_profile_batch_calculates_per_item_timing(self, caplog):
        """profile_batch adds per-item timing metadata."""
        caplog.set_level(logging.INFO)
        config = ProfilingConfig(enabled=True)
        
        batch_size = 10
        with profile_batch("batch_operation", batch_size, config=config) as result:
            time.sleep(0.1)  # ~100ms total
        
        # Should have per_item_ms in metadata
        assert "per_item_ms" in result.metadata
        assert result.metadata["batch_size"] == 10
        # Per item should be ~10ms (100ms / 10 items)
        assert 8.0 <= result.metadata["per_item_ms"] <= 12.0
    
    def test_profile_batch_handles_zero_size(self):
        """profile_batch handles zero batch size gracefully."""
        config = ProfilingConfig(enabled=True)
        
        with profile_batch("empty_batch", 0, config=config) as result:
            pass
        
        assert result.metadata["batch_size"] == 0
        assert result.metadata["per_item_ms"] == 0.0
    
    def test_profile_batch_emits_batch_metrics(self, caplog):
        """profile_batch includes batch_size in logged metadata."""
        caplog.set_level(logging.INFO)
        config = ProfilingConfig(enabled=True)
        
        with profile_batch("test_batch", 5, config=config):
            pass
        
        log_records = [r for r in caplog.records if "PROFILING:" in r.message]
        log_msg = log_records[0].message
        json_str = log_msg.split("PROFILING: ")[1]
        payload = json.loads(json_str)
        
        assert payload["metadata"]["batch_size"] == 5
        assert "per_item_ms" in payload["metadata"]


class TestConvenienceFunctions:
    """Tests for enable_profiling and disable_profiling."""
    
    def test_enable_profiling_sets_global_config(self):
        """enable_profiling() updates global config."""
        enable_profiling(memory=True, min_duration_ms=10.0)
        
        config = get_profiling_config()
        assert config.enabled is True
        assert config.min_duration_ms == 10.0
        # memory_profiling depends on psutil availability
        assert isinstance(config.memory_profiling, bool)
        
        # Reset
        disable_profiling()
    
    def test_disable_profiling_sets_global_config(self):
        """disable_profiling() disables profiling globally."""
        enable_profiling()
        disable_profiling()
        
        config = get_profiling_config()
        assert config.enabled is False
    
    def test_enable_then_disable_workflow(self, caplog):
        """Can enable, use, then disable profiling."""
        caplog.set_level(logging.INFO)
        
        # Enable
        enable_profiling(min_duration_ms=0.0)
        
        with profile_section("enabled_test"):
            pass
        
        logs_enabled = [r for r in caplog.records if "PROFILING:" in r.message]
        assert len(logs_enabled) == 1
        
        # Disable
        caplog.clear()
        disable_profiling()
        
        with profile_section("disabled_test"):
            pass
        
        logs_disabled = [r for r in caplog.records if "PROFILING:" in r.message]
        assert len(logs_disabled) == 0


class TestProfilingIntegration:
    """Integration tests for profiling with optimizers."""
    
    def test_profiling_works_with_method_decorator(self, caplog):
        """Profiling decorator works on class methods."""
        caplog.set_level(logging.INFO)
        enable_profiling()
        
        class SampleOptimizer:
            @profile_method("optimizer.process")
            def process(self, data):
                time.sleep(0.01)
                return len(data)
        
        optimizer = SampleOptimizer()
        result = optimizer.process("test data")
        assert result == 9
        
        log_records = [r for r in caplog.records if "PROFILING:" in r.message]
        assert len(log_records) == 1
        
        log_msg = log_records[0].message
        json_str = log_msg.split("PROFILING: ")[1]
        payload = json.loads(json_str)
        assert payload["section_name"] == "optimizer.process"
        
        # Cleanup
        disable_profiling()
    
    def test_nested_profiling_sections(self, caplog):
        """Nested profile_section calls both emit logs."""
        caplog.set_level(logging.INFO)
        config = ProfilingConfig(enabled=True)
        
        with profile_section("outer", config=config):
            time.sleep(0.01)
            with profile_section("inner", config=config):
                time.sleep(0.01)
        
        log_records = [r for r in caplog.records if "PROFILING:" in r.message]
        assert len(log_records) == 2
        
        # Parse both logs
        section_names = []
        for record in log_records:
            log_msg = record.message
            json_str = log_msg.split("PROFILING: ")[1]
            payload = json.loads(json_str)
            section_names.append(payload["section_name"])
        
        assert "outer" in section_names
        assert "inner" in section_names
