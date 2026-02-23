"""Lightweight profiling hooks for optimizer hot-path methods.

This module provides opt-in performance profiling with minimal overhead when disabled.
Profiling results are emitted as structured JSON logs compatible with the optimizer logging schema.

Usage:
    # Enable profiling globally
    from ipfs_datasets_py.optimizers.common.profiling import enable_profiling
    enable_profiling(memory=True, min_duration_ms=10.0)
    
    # Decorate methods to profile
    from ipfs_datasets_py.optimizers.common.profiling import profile_method
    
    @profile_method("ontology_generator.generate_ontology")
    def generate_ontology(self, data, context):
        # Method is automatically profiled when ProfilingConfig.enabled=True
        return ontology
    
    # Or use context manager for code blocks
    from ipfs_datasets_py.optimizers.common.profiling import profile_section
    
    with profile_section("expensive_operation") as prof:
        # ... do work ...
        pass
    print(f"Took {prof.duration_ms:.2f}ms")
    
    # For batch operations
    from ipfs_datasets_py.optimizers.common.profiling import profile_batch
    
    with profile_batch("process_batch", batch_size=100):
        # ... process batch ...
        pass

Configuration:
    ProfilingConfig controls profiling behavior:
    - enabled: Whether to profile at all (default: False)
    - memory_profiling: Track memory usage (requires psutil, default: False)
    - min_duration_ms: Only log operations exceeding this duration (default: 0.0)
    - emit_logs: Emit structured JSON logs (default: True)
"""

from __future__ import annotations

import contextlib
import functools
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from .structured_logging import with_schema

logger = logging.getLogger(__name__)


@dataclass
class ProfilingConfig:
    """Configuration for profiling behavior.
    
    Attributes:
        enabled: If False, profiling has near-zero overhead (default: False)
        memory_profiling: Track memory usage (requires psutil, default: False)
        min_duration_ms: Only log operations >= this duration (default: 0.0)
        emit_logs: Emit structured JSON logs via logger (default: True)
    """
    
    enabled: bool = False
    memory_profiling: bool = False
    min_duration_ms: float = 0.0
    emit_logs: bool = True
    
    def __post_init__(self):
        """Validate config and warn if memory profiling unavailable."""
        if self.memory_profiling and not PSUTIL_AVAILABLE:
            logger.warning(
                "Memory profiling requested but psutil not available. "
                "Install psutil to enable memory profiling."
            )
            self.memory_profiling = False


# Global profiling configuration
_GLOBAL_CONFIG = ProfilingConfig(enabled=False)


def get_profiling_config() -> ProfilingConfig:
    """Get the current global profiling configuration.
    
    Returns:
        Current ProfilingConfig instance
    """
    return _GLOBAL_CONFIG


def set_profiling_config(config: ProfilingConfig) -> None:
    """Set the global profiling configuration.
    
    Args:
        config: New ProfilingConfig to use globally
    """
    global _GLOBAL_CONFIG
    _GLOBAL_CONFIG = config


def enable_profiling(
    memory: bool = False,
    min_duration_ms: float = 0.0,
    emit_logs: bool = True,
) -> None:
    """Enable profiling globally with specified settings.
    
    Args:
        memory: Enable memory profiling (requires psutil)
        min_duration_ms: Only log operations exceeding this duration
        emit_logs: Emit structured JSON logs
    """
    global _GLOBAL_CONFIG
    _GLOBAL_CONFIG = ProfilingConfig(
        enabled=True,
        memory_profiling=memory,
        min_duration_ms=min_duration_ms,
        emit_logs=emit_logs,
    )


def disable_profiling() -> None:
    """Disable profiling globally (restores minimal overhead mode)."""
    global _GLOBAL_CONFIG
    _GLOBAL_CONFIG = ProfilingConfig(enabled=False)


@dataclass
class ProfileResult:
    """Result of a profiling operation.
    
    Attributes:
        section_name: Name of profiled section/method
        duration_ms: Elapsed time in milliseconds
        memory_delta_mb: Change in memory usage (MB, if tracked)
        peak_memory_mb: Peak memory usage during operation (MB, if tracked)
        metadata: Additional context (batch size, args, etc.)
    """
    
    section_name: str
    duration_ms: float = 0.0
    memory_delta_mb: Optional[float] = None
    peak_memory_mb: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary for logging.
        
        Returns:
            Dictionary with all non-None fields, floats rounded to 2 decimals
        """
        result = {
            "section_name": self.section_name,
            "duration_ms": round(self.duration_ms, 2),
        }
        
        if self.memory_delta_mb is not None:
            result["memory_delta_mb"] = round(self.memory_delta_mb, 2)
        
        if self.peak_memory_mb is not None:
            result["peak_memory_mb"] = round(self.peak_memory_mb, 2)
        
        if self.metadata:
            result["metadata"] = self.metadata
        
        return result


@contextlib.contextmanager
def profile_section(
    section_name: str,
    metadata: Optional[dict[str, Any]] = None,
    config: Optional[ProfilingConfig] = None,
):
    """Profile a code section with timing and optional memory tracking.
    
    Args:
        section_name: Name for this profiled section
        metadata: Additional context to include in result
        config: ProfilingConfig to use (default: global config)
    
    Yields:
        ProfileResult that accumulates metrics during execution
    
    Example:
        with profile_section("data_processing", metadata={"rows": 1000}) as prof:
            # ... do work ...
            pass
        print(f"Took {prof.duration_ms:.2f}ms")
    """
    if config is None:
        config = get_profiling_config()
    
    result = ProfileResult(section_name=section_name, metadata=metadata or {})
    
    if not config.enabled:
        # Return immediately with zero overhead
        yield result
        return
    
    # Memory profiling setup
    start_memory_mb = None
    process = None
    if config.memory_profiling and PSUTIL_AVAILABLE:
        try:
            process = psutil.Process()
            start_memory_mb = process.memory_info().rss / (1024 * 1024)
        except Exception as e:
            logger.debug(f"Failed to get start memory: {e}")
    
    # Start timing
    start_time = time.perf_counter()
    
    try:
        yield result
    finally:
        # Measure duration
        end_time = time.perf_counter()
        result.duration_ms = (end_time - start_time) * 1000.0
        
        # Memory profiling
        if config.memory_profiling and process is not None and start_memory_mb is not None:
            try:
                end_memory_mb = process.memory_info().rss / (1024 * 1024)
                result.memory_delta_mb = end_memory_mb - start_memory_mb
                
                # Peak memory (approximate)
                result.peak_memory_mb = end_memory_mb
            except Exception as e:
                logger.debug(f"Failed to get end memory: {e}")
        
        # Emit log if enabled and duration threshold met
        if config.emit_logs and result.duration_ms >= config.min_duration_ms:
            try:
                _emit_profiling_log(result)
            except Exception as e:
                logger.debug(f"Failed to emit profiling log: {e}")


def _emit_profiling_log(result: ProfileResult) -> None:
    """Emit profiling result as structured JSON log.
    
    Args:
        result: ProfileResult to log
    """
    import json
    
    payload = result.to_dict()
    payload["event"] = "profiling_result"
    
    log_entry = with_schema(payload)
    logger.info(f"PROFILING: {json.dumps(log_entry)}")


def profile_method(
    section_name: Optional[str] = None,
    include_args: bool = False,
    config: Optional[ProfilingConfig] = None,
) -> Callable:
    """Decorator to profile a method or function.
    
    Args:
        section_name: Name for profiling section (default: module.function_name)
        include_args: Include argument count in metadata (default: False)
        config: ProfilingConfig to use (default: global config)
    
    Returns:
        Decorator function
    
    Example:
        @profile_method("ontology_generator.generate")
        def generate_ontology(self, data, context):
            return ontology
    """
    def decorator(func: Callable) -> Callable:
        # Determine section name
        nonlocal section_name
        if section_name is None:
            section_name = f"{func.__module__}.{func.__qualname__}"
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # If profiling disabled, call directly with zero overhead
            profiling_config = config if config is not None else get_profiling_config()
            if not profiling_config.enabled:
                return func(*args, **kwargs)
            
            # Build metadata
            metadata = {}
            if include_args:
                metadata["args_count"] = len(args) + len(kwargs)
                if kwargs:
                    metadata["kwargs_keys"] = list(kwargs.keys())
            
            # Profile execution
            with profile_section(section_name, metadata=metadata, config=profiling_config):
                return func(*args, **kwargs)
        
        return wrapper
    
    return decorator


@contextlib.contextmanager
def profile_batch(
    section_name: str,
    batch_size: int,
    metadata: Optional[dict[str, Any]] = None,
    config: Optional[ProfilingConfig] = None,
):
    """Profile a batch operation with per-item timing.
    
    Args:
        section_name: Name for this profiled section
        batch_size: Number of items in batch
        metadata: Additional context to include
        config: ProfilingConfig to use (default: global config)
    
    Yields:
        ProfileResult with batch_size and per_item_ms in metadata
    
    Example:
        with profile_batch("process_documents", len(documents)):
            for doc in documents:
                # ... process doc ...
                    if config is None:
                        config = get_profiling_config()
    
                pass
    """
    batch_metadata = metadata.copy() if metadata else {}
    batch_metadata["batch_size"] = batch_size
    
    # Create result but don't emit log yet (emit_logs=False in temporary config)
    temp_config = ProfilingConfig(
        enabled=config.enabled,
        memory_profiling=config.memory_profiling,
        min_duration_ms=config.min_duration_ms,
        emit_logs=False,  # Suppress automatic logging
    )
    
    with profile_section(section_name, metadata=batch_metadata, config=temp_config) as result:
        yield result
    
    # Add per-item timing to metadata
    if batch_size > 0:
        result.metadata["per_item_ms"] = result.duration_ms / batch_size
    else:
        result.metadata["per_item_ms"] = 0.0
    
    # Now emit log with complete metadata
    if config.emit_logs and result.duration_ms >= config.min_duration_ms:
        try:
            _emit_profiling_log(result)
        except Exception as e:
            logger.debug(f"Failed to emit profiling log: {e}")
