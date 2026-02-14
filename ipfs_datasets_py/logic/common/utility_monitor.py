"""
Utility wrapper for adding monitoring to logic utility functions.

Provides decorators and helpers to add monitoring, caching, and
performance tracking to utility functions throughout the logic module.
"""

from typing import Any, Callable, Dict, Optional, TypeVar, cast
from functools import wraps
import time
import hashlib
import json

# Type variables for generic functions
T = TypeVar('T')
F = TypeVar('F', bound=Callable[..., Any])


class UtilityMonitor:
    """
    Monitor and track utility function calls.
    
    Provides statistics tracking, caching, and performance monitoring
    for utility functions without requiring modification of the functions
    themselves.
    
    Example:
        >>> monitor = UtilityMonitor()
        >>> 
        >>> @monitor.track_performance
        >>> def my_utility(text: str) -> dict:
        ...     return {"result": text.upper()}
        >>> 
        >>> result = my_utility("hello")
        >>> stats = monitor.get_stats()
        >>> print(f"Calls: {stats['my_utility']['calls']}")
    """
    
    def __init__(self) -> None:
        """Initialize utility monitor."""
        self._stats: Dict[str, Dict[str, Any]] = {}
        self._cache: Dict[str, Any] = {}
    
    def track_performance(self, func: F) -> F:
        """
        Decorator to track performance of a utility function.
        
        Args:
            func: Function to monitor
        
        Returns:
            Wrapped function with performance tracking
        
        Example:
            >>> monitor = UtilityMonitor()
            >>> 
            >>> @monitor.track_performance
            >>> def process_text(text):
            ...     return text.upper()
        """
        func_name = func.__name__
        
        if func_name not in self._stats:
            self._stats[func_name] = {
                'calls': 0,
                'total_time': 0.0,
                'errors': 0,
            }
        
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                
                self._stats[func_name]['calls'] += 1
                self._stats[func_name]['total_time'] += elapsed
                
                return result
                
            except Exception as e:
                self._stats[func_name]['errors'] += 1
                raise
        
        return cast(F, wrapper)
    
    def with_caching(
        self,
        cache_key_fn: Optional[Callable[..., str]] = None
    ) -> Callable[[F], F]:
        """
        Decorator to add caching to a utility function.
        
        Args:
            cache_key_fn: Optional function to compute cache key from args
        
        Returns:
            Decorator function
        
        Example:
            >>> monitor = UtilityMonitor()
            >>> 
            >>> @monitor.with_caching()
            >>> def expensive_operation(text):
            ...     time.sleep(1)
            ...     return text.upper()
        """
        def decorator(func: F) -> F:
            func_name = func.__name__
            
            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                # Compute cache key
                if cache_key_fn:
                    cache_key = cache_key_fn(*args, **kwargs)
                else:
                    cache_key = self._default_cache_key(func_name, args, kwargs)
                
                # Check cache
                if cache_key in self._cache:
                    return self._cache[cache_key]
                
                # Compute and cache
                result = func(*args, **kwargs)
                self._cache[cache_key] = result
                
                return result
            
            return cast(F, wrapper)
        
        return decorator
    
    def _default_cache_key(
        self,
        func_name: str,
        args: tuple,
        kwargs: dict
    ) -> str:
        """Generate default cache key from function arguments."""
        key_data = {
            'func': func_name,
            'args': str(args),
            'kwargs': str(sorted(kwargs.items())),
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()
    
    def get_stats(self, func_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get statistics for monitored functions.
        
        Args:
            func_name: Optional specific function name
        
        Returns:
            Statistics dictionary
        """
        if func_name:
            stats = self._stats.get(func_name, {})
            if stats and stats['calls'] > 0:
                stats['avg_time'] = stats['total_time'] / stats['calls']
            return stats
        
        # Return all stats with computed averages
        all_stats = {}
        for name, stats in self._stats.items():
            stats_copy = stats.copy()
            if stats_copy['calls'] > 0:
                stats_copy['avg_time'] = stats_copy['total_time'] / stats_copy['calls']
            all_stats[name] = stats_copy
        
        return all_stats
    
    def clear_cache(self) -> None:
        """Clear the utility cache."""
        self._cache.clear()
    
    def reset_stats(self) -> None:
        """Reset all statistics."""
        self._stats.clear()


# Global monitor instance for convenience
_global_monitor = UtilityMonitor()


def track_performance(func: F) -> F:
    """
    Convenience decorator using global monitor.
    
    Example:
        >>> from ipfs_datasets_py.logic.common.utility_monitor import track_performance
        >>> 
        >>> @track_performance
        >>> def my_function(x):
        ...     return x * 2
    """
    return _global_monitor.track_performance(func)


def with_caching(
    cache_key_fn: Optional[Callable[..., str]] = None
) -> Callable[[F], F]:
    """
    Convenience decorator for caching using global monitor.
    
    Example:
        >>> from ipfs_datasets_py.logic.common.utility_monitor import with_caching
        >>> 
        >>> @with_caching()
        >>> def expensive_function(text):
        ...     return text.upper()
    """
    return _global_monitor.with_caching(cache_key_fn)


def get_global_stats() -> Dict[str, Any]:
    """Get statistics from global monitor."""
    return _global_monitor.get_stats()


def clear_global_cache() -> None:
    """Clear global monitor cache."""
    _global_monitor.clear_cache()


def reset_global_stats() -> None:
    """Reset global monitor statistics."""
    _global_monitor.reset_stats()
