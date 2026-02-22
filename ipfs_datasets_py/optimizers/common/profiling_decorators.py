"""Performance and memory profiling decorators for optimizer hot paths.

Provides lightweight decorators for tracking memory usage and execution time
of critical optimizer functions. Designed for development/debugging use with
minimal production overhead when disabled.

Example::

    from ipfs_datasets_py.optimizers.common.profiling_decorators import (
        profile_memory,
        profile_time,
        profile_both,
    )

    @profile_memory(threshold_mb=10.0)
    def extract_entities(text: str) -> List[Entity]:
        # Function implementation
        ...

    @profile_time(slow_threshold_s=1.0)
    def evaluate_ontology(ontology: Dict) -> CriticScore:
        # Function implementation
        ...

    @profile_both()
    def optimize_batch(ontologies: List[Dict]) -> List[Dict]:
        # Function implementation
        ...

The decorators can be globally enabled/disabled via the ``OPTIMIZER_PROFILING``
environment variable::

    export OPTIMIZER_PROFILING=1  # Enable all profiling
    export OPTIMIZER_PROFILING=0  # Disable all profiling (default)

"""

from __future__ import annotations

import functools
import logging
import os
import time
from typing import Any, Callable, Optional, TypeVar

# Check if psutil is available for memory profiling
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

logger = logging.getLogger(__name__)

# Global profiling enable/disable flag
PROFILING_ENABLED = os.environ.get("OPTIMIZER_PROFILING", "0") == "1"

# Type variable for decorated functions
F = TypeVar("F", bound=Callable[..., Any])


def _get_memory_usage_mb() -> float:
    """Get current process memory usage in megabytes.
    
    Returns:
        Memory usage in MB, or 0.0 if psutil not available.
    """
    if not PSUTIL_AVAILABLE:
        return 0.0
    
    try:
        process = psutil.Process()
        mem_info = process.memory_info()
        return mem_info.rss / (1024 * 1024)  # Convert bytes to MB
    except Exception as e:
        logger.debug(f"Failed to get memory usage: {e}")
        return 0.0


def profile_memory(
    threshold_mb: float = 50.0,
    log_level: int = logging.INFO,
    enabled: Optional[bool] = None,
) -> Callable[[F], F]:
    """Decorator to profile memory usage of a function.
    
    Logs a warning if the function's memory delta exceeds the threshold.
    Memory is measured before and after the function call.
    
    Args:
        threshold_mb: Memory increase threshold in MB to trigger logging.
        log_level: Logging level to use (default: INFO).
        enabled: Override global profiling flag (None = use global).
    
    Returns:
        Decorated function that tracks memory usage.
        
    Example::
    
        @profile_memory(threshold_mb=100.0)
        def load_large_ontology(path: str) -> Dict:
            # This will log if memory increases by >100MB
            ...
    
    Note:
        Requires ``psutil`` package. If not installed, decorator is a no-op.
    """
    is_enabled = enabled if enabled is not None else PROFILING_ENABLED
    
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not is_enabled or not PSUTIL_AVAILABLE:
                # Profiling disabled or psutil unavailable - skip tracking
                return func(*args, **kwargs)
            
            mem_before = _get_memory_usage_mb()
            result = func(*args, **kwargs)
            mem_after = _get_memory_usage_mb()
            
            mem_delta = mem_after - mem_before
            
            if mem_delta >= threshold_mb:
                logger.log(
                    log_level,
                    f"{func.__name__} memory usage: +{mem_delta:.2f} MB "
                    f"(before: {mem_before:.2f} MB, after: {mem_after:.2f} MB, "
                    f"threshold: {threshold_mb:.2f} MB)"
                )
            
            return result
        
        return wrapper  # type: ignore
    
    return decorator


def profile_time(
    slow_threshold_s: float = 1.0,
    log_level: int = logging.WARNING,
    enabled: Optional[bool] = None,
) -> Callable[[F], F]:
    """Decorator to profile execution time of a function.
    
    Logs a message if the function's execution time exceeds the threshold.
    Uses monotonic clock for accurate wall-clock measurement.
    
    Args:
        slow_threshold_s: Execution time threshold in seconds to trigger logging.
        log_level: Logging level to use (default: WARNING).
        enabled: Override global profiling flag (None = use global).
    
    Returns:
        Decorated function that tracks execution time.
        
    Example::
    
        @profile_time(slow_threshold_s=5.0)
        def expensive_operation(data: List) -> Result:
            # This will log if execution takes >5 seconds
            ...
    """
    is_enabled = enabled if enabled is not None else PROFILING_ENABLED
    
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not is_enabled:
                # Profiling disabled - skip tracking
                return func(*args, **kwargs)
            
            start_time = time.monotonic()
            result = func(*args, **kwargs)
            end_time = time.monotonic()
            
            duration_s = end_time - start_time
            
            if duration_s >= slow_threshold_s:
                logger.log(
                    log_level,
                    f"{func.__name__} slow execution: {duration_s:.3f}s "
                    f"(threshold: {slow_threshold_s:.3f}s)"
                )
            
            return result
        
        return wrapper  # type: ignore
    
    return decorator


def profile_both(
    memory_threshold_mb: float = 50.0,
    time_threshold_s: float = 1.0,
    log_level: int = logging.INFO,
    enabled: Optional[bool] = None,
) -> Callable[[F], F]:
    """Decorator to profile both memory usage and execution time.
    
    Combines ``profile_memory`` and ``profile_time`` into a single decorator.
    Logs if either threshold is exceeded, showing both metrics.
    
    Args:
        memory_threshold_mb: Memory increase threshold in MB.
        time_threshold_s: Execution time threshold in seconds.
        log_level: Logging level to use (default: INFO).
        enabled: Override global profiling flag (None = use global).
    
    Returns:
        Decorated function that tracks both memory and time.
        
    Example::
    
        @profile_both(memory_threshold_mb=100.0, time_threshold_s=2.0)
        def process_batch(items: List) -> List[Result]:
            # This will log if either threshold is exceeded
            ...
    """
    is_enabled = enabled if enabled is not None else PROFILING_ENABLED
    
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not is_enabled:
                # Profiling disabled - skip tracking
                return func(*args, **kwargs)
            
            mem_before = _get_memory_usage_mb() if PSUTIL_AVAILABLE else 0.0
            start_time = time.monotonic()
            
            result = func(*args, **kwargs)
            
            end_time = time.monotonic()
            mem_after = _get_memory_usage_mb() if PSUTIL_AVAILABLE else 0.0
            
            duration_s = end_time - start_time
            mem_delta = mem_after - mem_before
            
            time_exceeded = duration_s >= time_threshold_s
            mem_exceeded = PSUTIL_AVAILABLE and mem_delta >= memory_threshold_mb
            
            if time_exceeded or mem_exceeded:
                msg_parts = [f"{func.__name__} performance:"]
                
                if time_exceeded:
                    msg_parts.append(f"time={duration_s:.3f}s (threshold: {time_threshold_s:.3f}s)")
                else:
                    msg_parts.append(f"time={duration_s:.3f}s")
                
                if PSUTIL_AVAILABLE:
                    if mem_exceeded:
                        msg_parts.append(f"mem_delta=+{mem_delta:.2f} MB (threshold: {memory_threshold_mb:.2f} MB)")
                    else:
                        msg_parts.append(f"mem_delta=+{mem_delta:.2f} MB")
                
                logger.log(log_level, " | ".join(msg_parts))
            
            return result
        
        return wrapper  # type: ignore
    
    return decorator


def enable_profiling() -> None:
    """Enable profiling decorators globally for the current process.
    
    This is useful for enabling profiling dynamically at runtime without
    restarting the process or changing environment variables.
    
    Example::
    
        from ipfs_datasets_py.optimizers.common.profiling_decorators import enable_profiling
        
        # Enable profiling for debugging
        enable_profiling()
        
        # Now all @profile_* decorated functions will log
        result = my_profiled_function()
    """
    global PROFILING_ENABLED
    PROFILING_ENABLED = True
    logger.info("Optimizer profiling enabled globally")


def disable_profiling() -> None:
    """Disable profiling decorators globally for the current process.
    
    This overrides the ``OPTIMIZER_PROFILING`` environment variable for
    the current process.
    
    Example::
    
        from ipfs_datasets_py.optimizers.common.profiling_decorators import disable_profiling
        
        # Disable profiling to reduce overhead in production
        disable_profiling()
    """
    global PROFILING_ENABLED
    PROFILING_ENABLED = False
    logger.info("Optimizer profiling disabled globally")


def is_profiling_enabled() -> bool:
    """Check if profiling is currently enabled globally.
    
    Returns:
        True if profiling decorators are active, False otherwise.
    """
    return PROFILING_ENABLED
