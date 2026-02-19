"""
CEC Optimization Module.

This module provides performance optimization tools including:
- Formula caching (interning, LRU, proof results, parse results)
- Profiling utilities (timing, memory tracking, bottleneck analysis)

Key Components:
- FormulaInterningCache: Reduce memory by sharing identical formulas
- LRUCache: Least-recently-used caching with automatic eviction
- ProofResultCache: Cache theorem proving results
- ParseResultCache: Cache NL parsing results
- CacheManager: Unified cache management
- FormulaProfiler: Performance profiling for formulas
- BottleneckAnalyzer: Identify performance bottlenecks

Usage:
    from ipfs_datasets_py.logic.CEC.optimization import (
        CacheManager, FormulaProfiler
    )
    
    # Set up caching
    cache_mgr = CacheManager()
    interned_formula = cache_mgr.formula_interning.intern(my_formula)
    
    # Profile operations
    profiler = FormulaProfiler()
    profiler.start_profiling("parse_operation")
    # ... do work ...
    result = profiler.stop_profiling("parse_operation")
"""

from .formula_cache import (
    CacheEntry,
    FormulaInterningCache,
    LRUCache,
    ProofResultCache,
    ParseResultCache,
    MemoizationCache,
    CacheManager,
)

from .profiling_utils import (
    ProfilingResult,
    Bottleneck,
    FormulaProfiler,
    BottleneckAnalyzer,
)

__all__ = [
    # Cache components
    'CacheEntry',
    'FormulaInterningCache',
    'LRUCache',
    'ProofResultCache',
    'ParseResultCache',
    'MemoizationCache',
    'CacheManager',
    # Profiling components
    'ProfilingResult',
    'Bottleneck',
    'FormulaProfiler',
    'BottleneckAnalyzer',
]
