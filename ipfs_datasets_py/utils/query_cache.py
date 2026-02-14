"""Query cache module - DEPRECATED.

This module is maintained for backward compatibility only.
Use ipfs_datasets_py.utils.cache.LocalCache instead.

The QueryCache class has been replaced by LocalCache from utils.cache,
which provides the same functionality with additional features:
- Better thread safety
- Statistics tracking
- TTL-based expiration
- Integration with GitHub cache
- P2P cache support (via P2PCache)

Migration Guide:
    Old code:
    >>> from ipfs_datasets_py.utils.query_cache import QueryCache
    >>> cache = QueryCache()
    
    New code:
    >>> from ipfs_datasets_py.utils.cache import LocalCache
    >>> cache = LocalCache()
"""

import warnings

# Issue deprecation warning
warnings.warn(
    "ipfs_datasets_py.utils.query_cache is deprecated. "
    "Use ipfs_datasets_py.utils.cache.LocalCache instead. "
    "This module will be removed in a future version.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export from new unified cache module
from .cache import LocalCache as QueryCache
from .cache import CacheBackend, CacheEntry, CacheStats

__all__ = [
    'QueryCache',
    'CacheBackend',
    'CacheEntry',
    'CacheStats',
]
