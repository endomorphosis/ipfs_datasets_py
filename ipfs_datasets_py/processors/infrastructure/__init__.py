"""
Infrastructure - Cross-cutting concerns for processors.

This package provides infrastructure utilities used across all processors:
- Caching: Result caching and cache management
- Monitoring: Metrics, logging, and observability
- Error Handling: Exception management and error recovery
- Profiling: Performance profiling and optimization
- Debug Tools: Debugging utilities and diagnostics
- CLI: Command-line interface utilities

Main Modules:
- caching: Cache management
- monitoring: Monitoring and metrics
- error_handling: Error handling utilities
- profiling: Performance profiling
- debug_tools: Debugging tools
- cli: CLI utilities

Example:
    from ipfs_datasets_py.processors.infrastructure import caching, monitoring
    
    cache = caching.CacheManager()
    monitor = monitoring.MetricsCollector()
"""

__all__ = [
    'caching',
    'monitoring',
    'error_handling',
    'profiling',
    'debug_tools',
    'cli',
]
