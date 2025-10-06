"""
Streaming Data Loader Module

This module provides high-performance streaming data loading capabilities for
processing large datasets without loading them entirely into memory. It includes:

- Streaming loaders for different data formats (Parquet, CSV, JSON, etc.)
- Memory-mapped access for large vector datasets
- Performance optimization with prefetching and caching
- Monitoring and statistics for streaming operations

The streaming loaders are designed to work with the IPFS datasets ecosystem,
providing efficient access to datasets stored in IPFS or other storage systems.
"""

import os
import io
import json
import tempfile
import mmap
import time
import logging
import threading
import queue
from typing import Dict, List, Optional, Tuple, Union, Any, Iterator, BinaryIO, Callable, Generator

# Check for optional dependencies
try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyarrow.csv as csv
    import pyarrow.json as json_pa
    import pyarrow.fs as fs
    HAVE_ARROW = True
except ImportError:
    HAVE_ARROW = False

try:
    from datasets import Dataset, DatasetDict, load_dataset, Features
    HAVE_DATASETS = True
except ImportError:
    HAVE_DATASETS = False

# Configure logging
logger = logging.getLogger(__name__)


class StreamingStats:
    """
    Statistics Collector for Streaming Data Operations

    The StreamingStats class provides comprehensive performance monitoring and metrics
    collection for streaming data operations. It tracks throughput, batch processing
    times, and resource utilization to help optimize streaming performance and identify
    bottlenecks during large dataset processing operations.

    This class is designed to work seamlessly with all streaming loaders in the module,
    providing consistent performance metrics across different data formats and sources.

    Key Features:
    - Real-time throughput calculation (records/second, bytes/second)
    - Batch processing time analysis with min/max/average statistics
    - Memory and resource utilization tracking
    - Configurable statistics collection with minimal overhead
    - Thread-safe operations for concurrent streaming scenarios

    Attributes:
        start_time (float): Unix timestamp when statistics collection began
        bytes_processed (int): Total number of bytes processed across all batches
        records_processed (int): Total number of records processed across all batches
        batches_processed (int): Total number of batches processed
        processing_times (List[float]): List of processing times for each batch in seconds
        batch_sizes (List[int]): List of record counts for each processed batch
        current_batch_start (Optional[float]): Start time of the currently processing batch

    Usage Example:
        stats = StreamingStats()
        
        # Start timing a batch
        stats.start_batch()
        # ... process batch ...
        stats.end_batch(records=1000, bytes_count=50000)
        
        # Get performance metrics
        metrics = stats.get_throughput()
        print(f"Processing rate: {metrics['records_per_second']:.2f} records/sec")
    """

    def __init__(self):
        """
        Initialize statistics collector for streaming operations.

        Creates a new statistics collector with all counters and timers reset to zero.
        The start time is set to the current system time to enable elapsed time calculations.

        Attributes initialized:
            start_time (float): Current Unix timestamp marking the beginning of collection
            bytes_processed (int): Counter for total bytes processed, initialized to 0
            records_processed (int): Counter for total records processed, initialized to 0
            batches_processed (int): Counter for total batches processed, initialized to 0
            processing_times (List[float]): Empty list to store batch processing durations
            batch_sizes (List[int]): Empty list to store batch record counts
            current_batch_start (Optional[float]): Batch timing marker, initially None
        """
        self.start_time = time.time()
        self.bytes_processed = 0
        self.records_processed = 0
        self.batches_processed = 0
        self.processing_times = []
        self.batch_sizes = []
        self.current_batch_start = None

    def start_batch(self):
        """
        Mark the start of a new batch for timing and performance measurement.

        Records the current timestamp to track batch processing duration.
        Should be called at the beginning of each batch processing operation
        to enable accurate performance monitoring and statistics collection.

        Example:
            >>> stats = StreamingStats()
            >>> stats.start_batch()
            >>> # ... process batch data ...
            >>> stats.end_batch(processed_records, total_bytes)
        """
        self.current_batch_start = time.time()

    def end_batch(self, records, bytes_count=None):
        """
        Mark the end of a batch.

        Args:
            records (int): Number of records in the batch
            bytes_count (int, optional): Size of the batch in bytes
        """
        if self.current_batch_start is None:
            return

        batch_time = time.time() - self.current_batch_start
        self.processing_times.append(batch_time)
        self.batch_sizes.append(records)
        self.records_processed += records

        if bytes_count:
            self.bytes_processed += bytes_count

        self.batches_processed += 1
        self.current_batch_start = None

    def get_throughput(self):
        """
        Calculate comprehensive throughput and performance metrics.

        Computes various performance statistics based on collected data including
        processing rates, timing statistics, and resource utilization metrics.
        All rates are calculated from the start time to the current moment.

        Returns:
            Dict[str, Union[float, int]]: Dictionary containing throughput statistics:
                - elapsed_seconds (float): Total elapsed time since statistics started
                - records_per_second (float): Average record processing rate
                - batches_per_second (float): Average batch processing rate  
                - total_records (int): Total number of records processed
                - total_batches (int): Total number of batches processed
                - bytes_per_second (float): Average data throughput (if bytes tracked)
                - total_bytes (int): Total bytes processed (if bytes tracked)
                - avg_batch_time (float): Average batch processing time (if available)
                - avg_batch_size (float): Average records per batch (if available)
                - min_batch_time (float): Fastest batch processing time (if available)
                - max_batch_time (float): Slowest batch processing time (if available)

        Example:
            >>> stats = streaming_stats.get_throughput()
            >>> print(f"Processing {stats['records_per_second']:.2f} records/sec")
            >>> print(f"Average batch time: {stats['avg_batch_time']:.3f}s")
        """
        elapsed = time.time() - self.start_time

        if elapsed == 0:
            elapsed = 0.001  # Avoid division by zero

        stats = {
            "elapsed_seconds": elapsed,
            "records_per_second": self.records_processed / elapsed,
            "batches_per_second": self.batches_processed / elapsed,
            "total_records": self.records_processed,
            "total_batches": self.batches_processed
        }

        if self.bytes_processed > 0:
            stats["bytes_per_second"] = self.bytes_processed / elapsed
            stats["total_bytes"] = self.bytes_processed

        if self.processing_times:
            stats["avg_batch_time"] = sum(self.processing_times) / len(self.processing_times)
            stats["avg_batch_size"] = sum(self.batch_sizes) / len(self.batch_sizes)
            stats["min_batch_time"] = min(self.processing_times)
            stats["max_batch_time"] = max(self.processing_times)

        return stats

    def reset(self):
        """
        Reset all statistics counters and timers to initial state.

        This method clears all collected statistics and resets the start time
        to the current moment, effectively starting a new statistics collection
        session. Useful for measuring performance of specific operations.
        """
        self.start_time = time.time()
        self.bytes_processed = 0
        self.records_processed = 0
        self.batches_processed = 0
        self.processing_times = []
        self.batch_sizes = []
        self.current_batch_start = None


class StreamingCache:
    """
    High-Performance Cache for Streaming Data Operations

    The StreamingCache class provides an intelligent caching layer for streaming data
    operations with automatic memory management, TTL-based expiration, and LRU eviction.
    It's designed to improve performance by reducing redundant data loading while
    maintaining strict memory bounds and ensuring data freshness.

    This cache is thread-safe and optimized for high-throughput streaming scenarios
    where the same data segments may be accessed multiple times during processing.

    Args:
        max_size_mb (int, optional): Maximum cache size in megabytes. The cache will
            automatically evict entries when this limit is approached. Defaults to 100.
        ttl_seconds (int, optional): Time-to-live for cache entries in seconds. Entries
            older than this duration are automatically expired. Defaults to 300 (5 minutes).

    Key Features:
    - Automatic memory management with configurable size limits
    - TTL-based expiration for data freshness guarantees
    - LRU (Least Recently Used) eviction policy for optimal cache utilization
    - Thread-safe operations with fine-grained locking
    - Comprehensive cache statistics and hit/miss ratio tracking
    - Intelligent size estimation for different data types

    Attributes:
        max_size_bytes (int): Maximum cache size in bytes (converted from max_size_mb)
        ttl_seconds (int): Time-to-live duration for cache entries
        cache (Dict[Any, Any]): Primary storage for cached values
        cache_times (Dict[Any, float]): Timestamps for TTL tracking
        cache_sizes (Dict[Any, int]): Size tracking for memory management
        current_size_bytes (int): Current total cache size in bytes
        hits (int): Number of successful cache retrievals
        misses (int): Number of cache misses (not found or expired)

    Usage Example:
        cache = StreamingCache(max_size_mb=200, ttl_seconds=600)
        
        # Cache a processed batch
        cache.put("batch_key_001", processed_data)
        
        # Retrieve cached data
        data = cache.get("batch_key_001")
        if data is not None:
            print("Cache hit!")
        
        # Get cache performance metrics
        stats = cache.get_stats()
        print(f"Hit ratio: {stats['hit_ratio']:.2%}")
    """

    def __init__(self, max_size_mb=100, ttl_seconds=300):
        """
        Initialize cache with configurable size and TTL limits.

        Args:
            max_size_mb (int, optional): Maximum cache size in megabytes. Values should be
                positive integers. The cache will evict entries when approaching this limit.
                Defaults to 100 MB.
            ttl_seconds (int, optional): Time-to-live for cache entries in seconds. Entries
                older than this duration are considered expired. Defaults to 300 seconds.

        Attributes initialized:
            max_size_bytes (int): Converted maximum size limit in bytes
            ttl_seconds (int): TTL duration for entry expiration
            cache (Dict[Any, Any]): Primary cache storage dictionary
            cache_times (Dict[Any, float]): Entry timestamp tracking for TTL
            cache_sizes (Dict[Any, int]): Entry size tracking for memory management
            current_size_bytes (int): Running total of current cache size
            hits (int): Cache hit counter for performance metrics
            misses (int): Cache miss counter for performance metrics
            _lock (threading.RLock): Reentrant lock for thread-safe operations
        """
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.ttl_seconds = ttl_seconds
        self.cache = {}
        self.cache_times = {}
        self.cache_sizes = {}
        self.current_size_bytes = 0
        self.hits = 0
        self.misses = 0
        self._lock = threading.RLock()

    def get(self, key):
        """
        Retrieve a value from the cache with TTL validation and access tracking.

        Attempts to retrieve the cached value associated with the given key.
        Automatically handles TTL (time-to-live) expiration by checking if
        the cached entry has exceeded its lifetime and removing expired entries.
        Updates access time for cache hit statistics and LRU eviction.

        Args:
            key (Any): The cache key to retrieve. Must match a key previously
                stored with the put() method.

        Returns:
            Any: The cached value if found and not expired, None if the key
                does not exist in the cache or if the entry has expired.

        Side Effects:
            - Increments hit counter if value is found and valid
            - Increments miss counter if value is not found or expired  
            - Updates access time for LRU eviction algorithm
            - Automatically removes expired entries from cache

        Example:
            >>> cache = StreamingCache(ttl_seconds=300)
            >>> cache.put("data_key", some_data)
            >>> 
            >>> # Retrieve data (within TTL)
            >>> data = cache.get("data_key")
            >>> if data is not None:
            ...     print("Cache hit!")
            >>> 
            >>> # After TTL expiration, returns None
            >>> time.sleep(350)
            >>> expired_data = cache.get("data_key")  # Returns None

        Thread Safety:
            This method is thread-safe and can be called concurrently from
            multiple threads without external synchronization.
        """
        with self._lock:
            if key not in self.cache:
                self.misses += 1
                return None

            # Check TTL
            cache_time = self.cache_times.get(key, 0)
            if time.time() - cache_time > self.ttl_seconds:
                # Expired
                self._remove(key)
                self.misses += 1
                return None

            # Update access time
            self.cache_times[key] = time.time()
            self.hits += 1

            return self.cache[key]

    def put(self, key, value, size_bytes=None):
        """
        Add a value to the cache with intelligent size management and eviction.

        Stores the provided value in the cache with automatic size estimation
        and LRU eviction if necessary. The cache will automatically make room
        for new entries by removing the oldest entries when the size limit
        is approached.

        Args:
            key (Any): Unique identifier for the cached value. Should be hashable
                and suitable as a dictionary key.
            value (Any): Value to store in cache. Can be any Python object,
                with automatic size estimation for common types.
            size_bytes (Optional[int], optional): Explicit size of the value in bytes.
                If None, size will be estimated automatically based on the value type.
                For numpy arrays, uses nbytes; for strings/bytes, uses length;
                for other objects, attempts JSON serialization for estimation.
                Defaults to None.

        Returns:
            bool: True if the value was successfully cached, False if the value
                was too large to fit in the cache (exceeds max_size_bytes).

        Raises:
            TypeError: If the key is not hashable
            MemoryError: If cache operations fail due to insufficient memory

        Example:
            >>> cache = StreamingCache(max_size_mb=100)
            >>> success = cache.put("batch_001", processed_data)
            >>> if success:
            ...     print("Data cached successfully")
            >>> 
            >>> # Cache with explicit size
            >>> cache.put("large_array", numpy_array, size_bytes=array.nbytes)

        Note:
            If the value is larger than the maximum cache size, it will not be
            cached and the method will return False with a warning logged.
        """
        with self._lock:
            # Estimate size if not provided
            if size_bytes is None:
                if hasattr(value, 'nbytes'):
                    size_bytes = value.nbytes
                elif isinstance(value, bytes):
                    size_bytes = len(value)
                elif isinstance(value, str):
                    size_bytes = len(value.encode('utf-8'))
                else:
                    try:
                        size_bytes = len(json.dumps(value).encode('utf-8'))
                    except:
                        # If we can't determine size, use a default
                        size_bytes = 1024

            # Check if the value is too large for the cache
            if size_bytes > self.max_size_bytes:
                logger.warning(f"Value of size {size_bytes} bytes is too large for cache (max: {self.max_size_bytes})")
                return False

            # Make room if necessary
            self._ensure_space(size_bytes)

            # If the key already exists, update size tracking
            if key in self.cache:
                old_size = self.cache_sizes.get(key, 0)
                self.current_size_bytes -= old_size

            # Add to cache
            self.cache[key] = value
            self.cache_times[key] = time.time()
            self.cache_sizes[key] = size_bytes
            self.current_size_bytes += size_bytes

            return True

    def _ensure_space(self, size_bytes):
        """
        Ensure there's enough space in the cache for a new entry.

        Implements LRU eviction policy by removing the least recently used entries
        until sufficient space is available for the new entry. This method is
        called automatically before adding new entries to prevent cache overflow.

        Args:
            size_bytes (int): The size in bytes required for the new cache entry.
                Must be a positive integer representing the memory footprint.

        Note:
            This method modifies the cache state by potentially removing multiple
            entries. The eviction continues until either sufficient space is
            available or the cache becomes empty.

        Example:
            >>> cache = StreamingCache(max_size_mb=100)
            >>> cache._ensure_space(50 * 1024 * 1024)  # Ensure 50MB space
            >>> # Cache may evict old entries to make room
        """
        # If we need more space, remove entries until we have enough
        while self.current_size_bytes + size_bytes > self.max_size_bytes and self.cache:
            # Find the oldest entry
            oldest_key = min(self.cache_times.items(), key=lambda x: x[1])[0]
            self._remove(oldest_key)

    def _remove(self, key):
        """
        Remove an entry from the cache and update size tracking.

        Performs a complete removal of the cache entry including cleanup of
        associated metadata (size tracking, access order). This method is
        typically called during LRU eviction or explicit cache invalidation.

        Args:
            key: Cache key to remove. Can be any hashable type that was
                previously used as a cache key.

        Note:
            This method safely handles cases where the key doesn't exist in
            the cache, making it safe to call during eviction loops. Size
            tracking is automatically updated to maintain cache consistency.

        Side Effects:
            - Updates current_size_bytes counter
            - Removes entry from cache dictionary
            - Removes entry from cache_sizes tracking
            - Updates access_order for LRU maintenance
        """
        if key in self.cache:
            size = self.cache_sizes.get(key, 0)
            self.current_size_bytes -= size
            del self.cache[key]
            if key in self.cache_times:
                del self.cache_times[key]
            if key in self.cache_sizes:
                del self.cache_sizes[key]

    def clear(self):
        """
        Clear all cached data and reset cache state.

        This method removes all cached entries, resets size tracking, and
        clears statistics. The cache will be empty after this operation
        but remains ready for new entries.
        """
        with self._lock:
            self.cache = {}
            self.cache_times = {}
            self.cache_sizes = {}
            self.current_size_bytes = 0

    def get_stats(self):
        """
        Get cache statistics.

        Returns:
            dict: Cache statistics
        """
        with self._lock:
            return {
                "size_bytes": self.current_size_bytes,
                "max_size_bytes": self.max_size_bytes,
                "utilization": self.current_size_bytes / self.max_size_bytes if self.max_size_bytes > 0 else 0,
                "item_count": len(self.cache),
                "hits": self.hits,
                "misses": self.misses,
                "hit_ratio": self.hits / (self.hits + self.misses) if (self.hits + self.misses) > 0 else 0
            }


class PrefetchingQueue:
    """
    Thread-Safe Prefetching Queue for Streaming Operations

    The PrefetchingQueue class implements an asynchronous prefetching mechanism that
    improves streaming performance by reading ahead from source iterators in a background
    thread. This reduces wait times during processing by ensuring data is ready when
    needed, particularly beneficial for I/O-bound streaming operations.

    The queue uses a producer-consumer pattern with a background thread continuously
    fetching data from the source iterator while the main thread consumes batches
    for processing.

    Args:
        source_iter (Iterator): Source iterator to prefetch from. Should yield individual
            items or batches that will be buffered for consumption.
        max_prefetch (int, optional): Maximum number of items to prefetch and queue.
            Higher values increase memory usage but improve throughput. Defaults to 3.
        buffer_size (int, optional): Number of items to collect before placing in queue.
            Larger buffers reduce queue operations but increase memory per queue item.
            Defaults to 1.

    Key Features:
    - Asynchronous prefetching with configurable queue depth
    - Automatic error propagation from background thread
    - Memory-efficient buffering with configurable batch sizes
    - Thread-safe queue operations with proper synchronization
    - Graceful handling of iterator exhaustion and exceptions

    Attributes:
        source_iter (Iterator): The source iterator being prefetched
        queue (queue.Queue): Thread-safe queue for buffered items
        buffer_size (int): Number of items collected per buffer
        end_marker (object): Sentinel object marking iterator completion
        exception (Optional[Exception]): Captured exception from background thread
        prefetch_thread (threading.Thread): Background thread for prefetching

    Usage Example:
        def slow_data_source():
            for i in range(1000):
                time.sleep(0.01)  # Simulate I/O delay
                yield f"item_{i}"
        
        # Create prefetching queue
        prefetch_queue = PrefetchingQueue(slow_data_source(), max_prefetch=5)
        
        # Consume data with improved performance
        for batch in prefetch_queue:
            process_items(batch)
    """

    def __init__(self, source_iter, max_prefetch=3, buffer_size=1):
        """
        Initialize prefetching queue with background thread for asynchronous data loading.

        Args:
            source_iter (Iterator): Source iterator to prefetch from. Must be iterable
                and yield items that can be collected into buffers.
            max_prefetch (int, optional): Maximum number of buffered items to queue.
                Controls memory usage vs. performance trade-off. Defaults to 3.
            buffer_size (int, optional): Number of items to collect before queuing.
                Larger values reduce queue overhead but increase memory per operation.
                Defaults to 1.

        Attributes initialized:
            source_iter (Iterator): Reference to the source iterator
            queue (queue.Queue): FIFO queue with max_prefetch capacity
            buffer_size (int): Items per buffer for batching efficiency
            end_marker (object): Unique sentinel object for iteration termination
            exception (Optional[Exception]): Exception storage for error propagation
            prefetch_thread (threading.Thread): Daemon thread for background prefetching
        """
        self.source_iter = source_iter
        self.queue = queue.Queue(maxsize=max_prefetch)
        self.buffer_size = buffer_size
        self.end_marker = object()  # Sentinel to mark the end of iteration
        self.exception = None
        self.prefetch_thread = threading.Thread(target=self._prefetch_worker)
        self.prefetch_thread.daemon = True
        self.prefetch_thread.start()

    def _prefetch_worker(self):
        """
        Worker function to prefetch items from the source iterator.

        Runs in a background daemon thread to continuously fetch items from
        the source iterator and buffer them for consumption. Implements
        buffering to reduce the frequency of queue operations and improve
        overall throughput.

        The worker handles exceptions gracefully by storing them for later
        propagation to the main thread. When the source iterator is exhausted,
        it sends an end marker to signal completion.
        """
        try:
            buffer = []
            for item in self.source_iter:
                buffer.append(item)
                if len(buffer) >= self.buffer_size:
                    self.queue.put(buffer)
                    buffer = []

            # Put any remaining items
            if buffer:
                self.queue.put(buffer)

            # Mark the end
            self.queue.put(self.end_marker)
        except Exception as e:
            self.exception = e
            self.queue.put(self.end_marker)

    def __iter__(self):
        """
        Return iterator interface for prefetching queue.

        Returns:
            PrefetchingQueue: Self as iterator for iteration protocol
        """
        return self

    def __next__(self):
        """
        Get the next buffered item from the prefetching queue.

        Returns:
            List: Buffer of items from the source iterator

        Raises:
            StopIteration: When the source iterator is exhausted
            Exception: Any exception that occurred in the background thread
        """
        if self.exception:
            raise self.exception

        item = self.queue.get()
        if item is self.end_marker:
            raise StopIteration

        # Return a flattened buffer
        for sub_item in item:
            yield sub_item


class StreamingDataLoader:
    """
    Base Class for High-Performance Streaming Data Loaders

    The StreamingDataLoader class serves as the foundation for all streaming data loaders
    in the module, providing common functionality for memory-efficient processing of large
    datasets. It implements core features like batching, caching, prefetching, and
    performance monitoring that are shared across different data format implementations.

    This abstract base class establishes the interface and common patterns used by
    specialized loaders for Parquet, CSV, JSON, and other data formats.

    Args:
        batch_size (int, optional): Number of records to process per batch. Larger
            batches improve throughput but increase memory usage. Defaults to 10000.
        prefetch_batches (int, optional): Number of batches to prefetch asynchronously.
            Higher values improve performance for I/O-bound operations. Defaults to 2.
        cache_enabled (bool, optional): Whether to enable intelligent caching of
            processed data segments. Reduces redundant processing. Defaults to True.
        cache_size_mb (int, optional): Maximum cache size in megabytes when caching
            is enabled. Defaults to 100 MB.
        collect_stats (bool, optional): Whether to collect detailed performance
            statistics during streaming operations. Defaults to True.

    Key Features:
    - Memory-efficient streaming with configurable batch sizes
    - Asynchronous prefetching for improved I/O performance
    - Intelligent caching with automatic memory management
    - Comprehensive performance statistics and monitoring
    - Thread-safe operations for concurrent access patterns
    - Extensible architecture for format-specific implementations

    Attributes:
        batch_size (int): Records per batch for memory management
        prefetch_batches (int): Asynchronous prefetch queue depth
        collect_stats (bool): Performance monitoring enablement flag
        cache (Optional[StreamingCache]): Cache instance when enabled
        stats (Optional[StreamingStats]): Statistics collector when enabled

    Public Methods:
        get_stats() -> Dict[str, Any]:
            Retrieve comprehensive performance statistics including throughput
            metrics, cache hit ratios, and processing times.

    Protected Methods:
        _cache_get(key) -> Any:
            Retrieve cached data by key with automatic TTL handling.
        _cache_put(key, value, size_bytes=None) -> bool:
            Store data in cache with intelligent size management.
        _start_batch_stats() -> None:
            Begin timing for batch processing statistics.
        _end_batch_stats(records, bytes_count=None) -> None:
            Complete batch timing and update statistics.

    Usage Example:
        # Direct usage (typically subclassed)
        loader = StreamingDataLoader(
            batch_size=5000,
            prefetch_batches=3,
            cache_enabled=True,
            cache_size_mb=200
        )
        
        # Access performance metrics
        stats = loader.get_stats()
        print(f"Throughput: {stats['throughput']['records_per_second']:.2f} rec/sec")
    """

    def __init__(
        self,
        batch_size=10000,
        prefetch_batches=2,
        cache_enabled=True,
        cache_size_mb=100,
        collect_stats=True
    ):
        """
        Initialize streaming data loader with performance optimization features.

        Args:
            batch_size (int, optional): Number of records to process per batch.
                Must be positive. Larger values improve throughput but increase
                memory usage. Defaults to 10000.
            prefetch_batches (int, optional): Number of batches to prefetch
                asynchronously. Must be non-negative. Zero disables prefetching.
                Defaults to 2.
            cache_enabled (bool, optional): Whether to enable caching of processed
                data segments. Improves performance for repeated access patterns.
                Defaults to True.
            cache_size_mb (int, optional): Maximum cache size in megabytes when
                caching is enabled. Must be positive. Defaults to 100.
            collect_stats (bool, optional): Whether to collect detailed performance
                statistics. May have minimal overhead when enabled. Defaults to True.

        Attributes initialized:
            batch_size (int): Configured batch size for processing
            prefetch_batches (int): Prefetch queue depth configuration
            collect_stats (bool): Statistics collection enablement flag
            cache (Optional[StreamingCache]): Cache instance when cache_enabled is True
            stats (Optional[StreamingStats]): Statistics collector when collect_stats is True
        """
        self.batch_size = batch_size
        self.prefetch_batches = prefetch_batches
        self.collect_stats = collect_stats

        if cache_enabled:
            self.cache = StreamingCache(max_size_mb=cache_size_mb)
        else:
            self.cache = None

        if collect_stats:
            self.stats = StreamingStats()
        else:
            self.stats = None

    def _cache_get(self, key):
        """
        Get a value from the cache.

        Args:
            key: Cache key

        Returns:
            The cached value, or None if not found
        """
        if self.cache is None:
            return None

        return self.cache.get(key)

    def _cache_put(self, key, value, size_bytes=None):
        """
        Add a value to the cache.

        Args:
            key: Cache key
            value: Value to cache
            size_bytes (int, optional): Size of the value

        Returns:
            bool: True if the value was cached
        """
        if self.cache is None:
            return False

        return self.cache.put(key, value, size_bytes)

    def _start_batch_stats(self):
        """
        Start timing a new batch for performance statistics collection.

        Initiates timing measurements for the current batch if statistics
        tracking is enabled. This method should be called at the beginning
        of each batch processing operation to ensure accurate performance
        monitoring.

        The timing data is used to calculate throughput metrics, processing
        duration, and other performance characteristics accessible via
        get_stats().
        """
        if self.stats is not None:
            self.stats.start_batch()

    def _end_batch_stats(self, records, bytes_count=None):
        """
        End timing for a batch.

        Args:
            records (int): Number of records in the batch
            bytes_count (int, optional): Size of the batch in bytes
        """
        if self.stats is not None:
            self.stats.end_batch(records, bytes_count)

    def get_stats(self):
        """
        Get performance statistics.

        Returns:
            dict: Performance statistics
        """
        result = {}

        if self.stats is not None:
            result["throughput"] = self.stats.get_throughput()

        if self.cache is not None:
            result["cache"] = self.cache.get_stats()

        return result


class ParquetStreamingLoader(StreamingDataLoader):
    """
    High-Performance Streaming Loader for Parquet Files and Datasets

    The ParquetStreamingLoader class provides memory-efficient, high-throughput access
    to Parquet files and partitioned datasets without loading entire datasets into memory.
    It leverages PyArrow's streaming capabilities and memory mapping for optimal performance
    with large-scale data processing workflows.

    This loader supports both single Parquet files and partitioned datasets (directories
    containing multiple Parquet files), with intelligent handling of column projection,
    predicate pushdown, and memory mapping optimizations.

    Args:
        parquet_path (str): Absolute or relative path to Parquet file or directory.
            For partitioned datasets, provide the root directory path.
        columns (Optional[List[str]], optional): Specific columns to load for projection.
            Only these columns will be read from storage, reducing I/O and memory usage.
            Defaults to None (load all columns).
        filters (Optional[List[Tuple]], optional): PyArrow-compatible filters for
            predicate pushdown. Format: [(column, operator, value), ...].
            Defaults to None (no filtering).
        batch_size (int, optional): Number of records per streaming batch. Larger
            batches improve throughput but increase memory usage. Defaults to 10000.
        prefetch_batches (int, optional): Number of batches to prefetch asynchronously.
            Improves performance for I/O-bound scenarios. Defaults to 2.
        cache_enabled (bool, optional): Whether to enable intelligent caching of
            processed batches. Defaults to True.
        cache_size_mb (int, optional): Maximum cache size in megabytes when caching
            is enabled. Defaults to 100.
        collect_stats (bool, optional): Whether to collect detailed performance
            statistics during streaming operations. Defaults to True.
        use_memory_map (bool, optional): Whether to use memory mapping for file access
            when processing single files. Improves performance for large files.
            Defaults to True.

    Key Features:
    - Memory-efficient streaming of arbitrarily large Parquet datasets
    - Support for both single files and partitioned datasets
    - Column projection and predicate pushdown for optimized I/O
    - Memory mapping support for enhanced performance
    - Comprehensive metadata access and schema inspection
    - Seamless integration with Arrow ecosystem and pandas

    Attributes:
        parquet_path (str): Path to the Parquet file or dataset directory
        columns (Optional[List[str]]): Selected columns for projection
        filters (Optional[List[Tuple]]): Applied filters for predicate pushdown
        use_memory_map (bool): Memory mapping enablement flag
        is_directory (bool): Whether the path points to a partitioned dataset
        parquet_dataset (Optional[pyarrow.dataset.Dataset]): Dataset for directories
        parquet_file (Optional[pyarrow.parquet.ParquetFile]): File handle for single files
        num_rows (Optional[int]): Total number of rows (None for unknown)

    Public Methods:
        __iter__() -> Iterator[pyarrow.Table]:
            Create iterator over dataset batches with automatic resource management.
        __len__() -> int:
            Get total number of records in the dataset.
        iter_batches() -> Iterator[pyarrow.Table]:
            Iterate over batches with optional prefetching for enhanced performance.
        to_arrow_table() -> pyarrow.Table:
            Load entire dataset into memory as single Arrow table.
        to_pandas() -> pandas.DataFrame:
            Convert entire dataset to pandas DataFrame.
        get_schema() -> pyarrow.Schema:
            Retrieve dataset schema with column types and metadata.
        get_metadata() -> Dict[str, Any]:
            Access comprehensive dataset metadata and file information.

    Usage Example:
        # Load large partitioned dataset with column projection
        loader = ParquetStreamingLoader(
            parquet_path="/data/large_dataset/",
            columns=["timestamp", "value", "category"],
            filters=[("category", "in", ["A", "B"])],
            batch_size=50000,
            use_memory_map=True
        )
        
        # Process data in streaming fashion
        for batch in loader.iter_batches():
            processed_batch = process_batch(batch)
            save_results(processed_batch)
        
        # Access performance metrics
        stats = loader.get_stats()
        print(f"Processed {stats['throughput']['total_records']} records")

    Raises:
        ImportError: If PyArrow is not available in the environment
        FileNotFoundError: If the specified parquet_path does not exist
        ValueError: If the path exists but contains no valid Parquet files
    """

    def __init__(
        self,
        parquet_path,
        columns=None,
        filters=None,
        batch_size=10000,
        prefetch_batches=2,
        cache_enabled=True,
        cache_size_mb=100,
        collect_stats=True,
        use_memory_map=True
    ):
        """
        Initialize Parquet streaming loader with advanced optimization features.

        Args:
            parquet_path (str): Path to Parquet file or partitioned dataset directory.
                Must be accessible and contain valid Parquet data.
            columns (Optional[List[str]], optional): Column names to load. Enables
                column projection for reduced I/O. Defaults to None (all columns).
            filters (Optional[List[Tuple]], optional): PyArrow filters for predicate
                pushdown. Format: [("column", "operator", value)]. Operators include
                "=", "!=", "<", ">", "<=", ">=", "in", "not in". Defaults to None.
            batch_size (int, optional): Records per batch for memory management.
                Must be positive. Defaults to 10000.
            prefetch_batches (int, optional): Asynchronous prefetch queue depth.
                Must be non-negative. Defaults to 2.
            cache_enabled (bool, optional): Enable intelligent batch caching.
                Defaults to True.
            cache_size_mb (int, optional): Maximum cache size in megabytes.
                Must be positive when caching enabled. Defaults to 100.
            collect_stats (bool, optional): Enable performance statistics collection.
                Defaults to True.
            use_memory_map (bool, optional): Enable memory mapping for single files.
                Improves performance but requires sufficient virtual memory.
                Defaults to True.

        Raises:
            ImportError: If PyArrow is not available for Parquet operations
            FileNotFoundError: If parquet_path does not exist
            PermissionError: If insufficient permissions to read parquet_path

        Attributes initialized:
            parquet_path (str): Stored path to Parquet file or dataset
            columns (Optional[List[str]]): Column projection configuration
            filters (Optional[List[Tuple]]): Predicate pushdown filters
            use_memory_map (bool): Memory mapping configuration for single files
            is_directory (bool): Flag indicating partitioned dataset vs single file
            parquet_dataset (Optional): PyArrow dataset for partitioned data
            parquet_file (Optional): PyArrow file handle for single files
            num_rows (Optional[int]): Total record count when determinable
        """
        super().__init__(
            batch_size=batch_size,
            prefetch_batches=prefetch_batches,
            cache_enabled=cache_enabled,
            cache_size_mb=cache_size_mb,
            collect_stats=collect_stats
        )

        if not HAVE_ARROW:
            raise ImportError("PyArrow is required for Parquet streaming")

        self.parquet_path = parquet_path
        self.columns = columns
        self.filters = filters
        self.use_memory_map = use_memory_map and os.path.isfile(parquet_path)

        # Open the Parquet file or dataset
        if os.path.isdir(parquet_path):
            # Directory of Parquet files (partitioned dataset)
            self.is_directory = True
            self.parquet_dataset = pq.ParquetDataset(
                parquet_path,
                filters=filters,
                use_legacy_dataset=False
            )
            self.num_rows = None  # Unknown until we scan the dataset
        else:
            # Single Parquet file
            self.is_directory = False
            self.parquet_file = pq.ParquetFile(
                parquet_path,
                memory_map=use_memory_map
            )
            self.num_rows = self.parquet_file.metadata.num_rows

    def __iter__(self):
        """
        Create an iterator over Parquet dataset batches with performance monitoring.

        Yields:
            pyarrow.Table: Batches of data from the Parquet dataset with
                          statistics collection and memory-efficient processing

        Raises:
            OSError: If file access fails during iteration
            pyarrow.ArrowException: If Parquet file corruption is detected
        """
        if self.is_directory:
            # Directory of Parquet files
            fragments = list(self.parquet_dataset.fragments)

            for fragment in fragments:
                for batch in fragment.iter_batches(
                    batch_size=self.batch_size,
                    columns=self.columns
                ):
                    self._start_batch_stats()
                    self._end_batch_stats(len(batch))
                    yield batch
        else:
            # Single Parquet file
            for batch in self.parquet_file.iter_batches(
                batch_size=self.batch_size,
                columns=self.columns
            ):
                self._start_batch_stats()
                self._end_batch_stats(len(batch))
                yield batch

    def __len__(self):
        """
        Get the total number of records in the Parquet dataset.

        For single files, returns the cached row count from metadata.
        For partitioned datasets, scans all fragments to compute the total
        and caches the result for future calls.

        Returns:
            int: Total number of records in the dataset, or 0 if the count
                cannot be determined.

        Note:
            For large partitioned datasets, the first call may be slow as it
            requires scanning all fragments. Subsequent calls return the cached value.

        Example:
            >>> loader = ParquetStreamingLoader("large_dataset.parquet")
            >>> total_records = len(loader)
            >>> print(f"Dataset contains {total_records:,} records")
        """
        if self.num_rows is not None:
            return self.num_rows

        # For partitioned datasets, we need to scan to get the total
        if self.is_directory:
            total_rows = 0
            for fragment in self.parquet_dataset.fragments:
                total_rows += fragment.count_rows()
            self.num_rows = total_rows
            return total_rows

        return 0

    def iter_batches(self):
        """
        Iterate over Parquet dataset batches with enhanced performance optimization.

        Provides an iterator over the dataset with optional asynchronous prefetching
        for improved I/O performance. When prefetching is enabled, multiple batches
        are loaded in the background to reduce wait times during processing.

        Yields:
            pyarrow.Table: Batches of Parquet data with the configured batch_size.
                          Each batch contains the projected columns and filtered rows
                          according to the loader configuration.

        Returns:
            Union[PrefetchingQueue, ParquetStreamingLoader]: A prefetching queue if
                prefetch_batches > 1, otherwise returns self for direct iteration.

        Performance Note:
            Prefetching significantly improves performance for I/O-bound workloads
            by overlapping data loading with processing. The optimal prefetch_batches
            value depends on the processing time per batch and I/O characteristics.

        Example:
            >>> loader = ParquetStreamingLoader("data.parquet", prefetch_batches=3)
            >>> for batch in loader.iter_batches():
            ...     # Process batch while next batches load in background
            ...     result = expensive_computation(batch)
            ...     save_result(result)
        """
        if self.prefetch_batches > 1:
            return PrefetchingQueue(self, self.prefetch_batches)
        return self

    def to_arrow_table(self):
        """
        Load the entire Parquet dataset into memory as a single Arrow table.

        Materializes the complete dataset with all configured column projections
        and filters applied. This method is convenient for smaller datasets or
        when you need the complete data in memory for operations that require
        random access or global computations.

        Returns:
            pyarrow.Table: The complete dataset as a single Arrow table with
                          all applied projections and filters.

        Raises:
            MemoryError: If the dataset is too large to fit in available memory.
            OSError: If file access fails during loading.
            pyarrow.ArrowException: If Parquet file corruption is detected.

        Warning:
            This method loads the entire dataset into memory, which can cause
            out-of-memory errors for large datasets. Consider using streaming
            iteration with iter_batches() for memory-efficient processing of
            large datasets.

        Example:
            >>> loader = ParquetStreamingLoader(
            ...     "data.parquet", 
            ...     columns=["id", "value"]
            ... )
            >>> table = loader.to_arrow_table()
            >>> print(f"Loaded {len(table)} records with {table.num_columns} columns")
            >>> df = table.to_pandas()  # Convert to pandas if needed
        """
        if self.is_directory:
            return self.parquet_dataset.read(columns=self.columns, filters=self.filters)
        else:
            return self.parquet_file.read(columns=self.columns)

    def to_pandas(self):
        """
        Convert the entire dataset to a pandas DataFrame.

        This loads the entire dataset into memory, so use with caution
        for large datasets.

        Returns:
            pandas.DataFrame: The loaded DataFrame

        Raises:
            MemoryError: If the dataset is too large to fit in memory
            ImportError: If pandas is not available
        """
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("Pandas is required for this operation")

        table = self.to_arrow_table()
        return table.to_pandas()

    def get_schema(self):
        """
        Get the schema of the dataset.

        Returns:
            pyarrow.Schema: The dataset schema
        """
        if self.is_directory:
            dataset_schema = self.parquet_dataset.schema
            if self.columns:
                # Filter the schema to only include the requested columns
                fields = [field for field in dataset_schema
                         if field.name in self.columns]
                return pa.schema(fields)
            return dataset_schema
        else:
            file_schema = self.parquet_file.schema_arrow
            if self.columns:
                # Filter the schema to only include the requested columns
                fields = [field for field in file_schema
                         if field.name in self.columns]
                return pa.schema(fields)
            return file_schema

    def get_metadata(self):
        """
        Get metadata from the Parquet file.

        Returns:
            dict: Metadata from the Parquet file
        """
        metadata = {
            "path": self.parquet_path,
            "is_directory": self.is_directory,
            "num_rows": self.num_rows,
            "schema": str(self.get_schema()),
            "memory_mapped": self.use_memory_map and not self.is_directory
        }

        if not self.is_directory:
            # Add more metadata from the file
            file_metadata = self.parquet_file.metadata
            metadata.update({
                "num_row_groups": file_metadata.num_row_groups,
                "created_by": file_metadata.created_by,
                "file_size_bytes": os.path.getsize(self.parquet_path)
            })

        return metadata


class CSVStreamingLoader(StreamingDataLoader):
    """
    High-Performance Streaming Loader for CSV Files

    The CSVStreamingLoader class provides memory-efficient, high-throughput access to
    CSV files without loading entire datasets into memory. It leverages PyArrow's
    advanced CSV parsing capabilities with comprehensive configuration options for
    handling diverse CSV formats and encoding scenarios.

    This loader is optimized for processing large CSV files with configurable parsing
    options, automatic type inference, and intelligent error handling for robust
    data processing workflows.

    Args:
        csv_path (str): Path to CSV file to load. Must be accessible and contain
            valid CSV data with consistent structure throughout the file.
        read_options (Optional[pyarrow.csv.ReadOptions], optional): PyArrow read
            options controlling file reading behavior including block size, encoding,
            threading, and header handling. Defaults to None (use PyArrow defaults).
        parse_options (Optional[pyarrow.csv.ParseOptions], optional): PyArrow parse
            options controlling CSV parsing including delimiters, quote characters,
            escape sequences, and whitespace handling. Defaults to None.
        convert_options (Optional[pyarrow.csv.ConvertOptions], optional): PyArrow
            conversion options controlling type inference, null value handling,
            and column-specific conversions. Defaults to None.
        batch_size (int, optional): Number of records per streaming batch. Larger
            values improve throughput but increase memory usage. Defaults to 10000.
        prefetch_batches (int, optional): Number of batches to prefetch asynchronously
            for improved I/O performance. Defaults to 2.
        cache_enabled (bool, optional): Whether to enable intelligent caching of
            processed data segments. Defaults to True.
        cache_size_mb (int, optional): Maximum cache size in megabytes when caching
            is enabled. Defaults to 100.
        collect_stats (bool, optional): Whether to collect detailed performance
            statistics during streaming operations. Defaults to True.

    Key Features:
    - Memory-efficient streaming of arbitrarily large CSV files
    - Comprehensive CSV parsing options for diverse data formats
    - Automatic type inference with configurable conversion rules
    - Advanced encoding support for international character sets
    - Robust error handling for malformed CSV data
    - Seamless integration with Arrow ecosystem and pandas

    Attributes:
        csv_path (str): Path to the CSV file being processed
        read_options (pyarrow.csv.ReadOptions): Configuration for file reading
        parse_options (pyarrow.csv.ParseOptions): Configuration for CSV parsing
        convert_options (pyarrow.csv.ConvertOptions): Configuration for type conversion

    Public Methods:
        __iter__() -> Iterator[pyarrow.Table]:
            Create iterator over CSV data batches with automatic resource management.
        iter_batches() -> Iterator[pyarrow.Table]:
            Iterate over batches with optional prefetching for enhanced performance.
        to_arrow_table() -> pyarrow.Table:
            Load entire CSV file into memory as single Arrow table.
        to_pandas() -> pandas.DataFrame:
            Convert entire CSV file to pandas DataFrame.
        get_schema() -> pyarrow.Schema:
            Retrieve CSV schema with inferred column types.

    Usage Example:
        # Basic CSV loading
        loader = CSVStreamingLoader("data.csv")
        
        # Advanced CSV loading with custom parsing
        read_opts = pa.csv.ReadOptions(
            encoding="utf-8",
            block_size=2*1024*1024,
            skip_rows=1
        )
        parse_opts = pa.csv.ParseOptions(
            delimiter=";",
            quote_char='"',
            escape_char="\\"
        )
        
        loader = CSVStreamingLoader(
            csv_path="complex_data.csv",
            read_options=read_opts,
            parse_options=parse_opts,
            batch_size=25000
        )
        
        # Process streaming data
        for batch in loader.iter_batches():
            cleaned_batch = validate_and_clean(batch)
            store_processed_batch(cleaned_batch)

    Raises:
        ImportError: If PyArrow is not available for CSV operations
        FileNotFoundError: If csv_path does not exist or is inaccessible
        ValueError: If file exists but is not valid CSV format
        PermissionError: If insufficient permissions to read the specified file
    """

    def __init__(
        self,
        csv_path,
        read_options=None,
        parse_options=None,
        convert_options=None,
        batch_size=10000,
        prefetch_batches=2,
        cache_enabled=True,
        cache_size_mb=100,
        collect_stats=True
    ):
        """
        Initialize CSV streaming loader with comprehensive parsing configuration.

        Args:
            csv_path (str): Path to CSV file to load. Must be readable and contain
                valid CSV data with consistent structure.
            read_options (Optional[pyarrow.csv.ReadOptions], optional): PyArrow read
                options for file access control including encoding, block size,
                threading, and header handling. Defaults to None (PyArrow defaults).
            parse_options (Optional[pyarrow.csv.ParseOptions], optional): PyArrow parse
                options for CSV structure handling including delimiters, quotes,
                and escape characters. Defaults to None (PyArrow defaults).
            convert_options (Optional[pyarrow.csv.ConvertOptions], optional): PyArrow
                conversion options for type inference and null handling.
                Defaults to None (PyArrow defaults).
            batch_size (int, optional): Records per batch for memory management.
                Must be positive. Defaults to 10000.
            prefetch_batches (int, optional): Asynchronous prefetch queue depth.
                Must be non-negative. Defaults to 2.
            cache_enabled (bool, optional): Enable intelligent batch caching.
                Defaults to True.
            cache_size_mb (int, optional): Maximum cache size in megabytes.
                Must be positive when caching enabled. Defaults to 100.
            collect_stats (bool, optional): Enable performance statistics collection.
                Defaults to True.

        Raises:
            ImportError: If PyArrow is not available for CSV streaming operations
            FileNotFoundError: If csv_path does not exist or is not accessible
            PermissionError: If insufficient permissions to read csv_path

        Attributes initialized:
            csv_path (str): Stored path to the CSV file
            read_options (pyarrow.csv.ReadOptions): File reading configuration
            parse_options (pyarrow.csv.ParseOptions): CSV parsing configuration
            convert_options (pyarrow.csv.ConvertOptions): Type conversion configuration
        """
        super().__init__(
            batch_size=batch_size,
            prefetch_batches=prefetch_batches,
            cache_enabled=cache_enabled,
            cache_size_mb=cache_size_mb,
            collect_stats=collect_stats
        )

        if not HAVE_ARROW:
            raise ImportError("PyArrow is required for CSV streaming")

        self.csv_path = csv_path

        # Set up options
        self.read_options = read_options or csv.ReadOptions(
            block_size=1024 * 1024  # 1MB blocks
        )

        # Make sure the batch size is set
        self.read_options = csv.ReadOptions(
            block_size=self.read_options.block_size,
            column_names=self.read_options.column_names,
            skip_rows=self.read_options.skip_rows,
            encoding=self.read_options.encoding,
            use_threads=self.read_options.use_threads,
            skip_rows_after_names=self.read_options.skip_rows_after_names
        )

        self.parse_options = parse_options or csv.ParseOptions(
            delimiter=',',
            quote_char='"'
        )
        self.convert_options = convert_options or csv.ConvertOptions()

    def __iter__(self):
        """
        Create an iterator over CSV file batches with automatic parsing and monitoring.

        Yields:
            pyarrow.Table: Batches of parsed CSV data with type inference
                          and statistics collection

        Raises:
            OSError: If file access fails during reading
            pyarrow.ArrowException: If CSV parsing fails due to malformed data
            UnicodeDecodeError: If file encoding doesn't match specified encoding
        """
        # Open the CSV file for streaming
        with csv.open_csv(
            self.csv_path,
            read_options=self.read_options,
            parse_options=self.parse_options,
            convert_options=self.convert_options
        ) as reader:
            # Read and yield batches
            batch_reader = reader.read_batch(self.batch_size)
            while batch_reader:
                self._start_batch_stats()
                batch = batch_reader.to_table()
                self._end_batch_stats(len(batch))
                yield batch

                # Read the next batch
                batch_reader = reader.read_batch(self.batch_size)

    def iter_batches(self):
        """
        Iterate over batches with optional prefetching.

        Yields:
            pyarrow.Table: Batch of records
        """
        if self.prefetch_batches > 1:
            return PrefetchingQueue(self, self.prefetch_batches)
        return self

    def to_arrow_table(self):
        """
        Convert the entire CSV file to an Arrow table.

        This loads the entire file into memory, so use with caution
        for large files.

        Returns:
            pyarrow.Table: The loaded table

        Raises:
            MemoryError: If the file is too large to fit in memory
        """
        return csv.read_csv(
            self.csv_path,
            read_options=self.read_options,
            parse_options=self.parse_options,
            convert_options=self.convert_options
        )

    def to_pandas(self):
        """
        Convert the entire CSV file to a pandas DataFrame.

        This loads the entire file into memory, so use with caution
        for large files.

        Returns:
            pandas.DataFrame: The loaded DataFrame

        Raises:
            MemoryError: If the file is too large to fit in memory
            ImportError: If pandas is not available
        """
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("Pandas is required for this operation")

        table = self.to_arrow_table()
        return table.to_pandas()

    def get_schema(self):
        """
        Get the schema of the CSV file.

        This reads the first batch to determine the schema.

        Returns:
            pyarrow.Schema: The file schema
        """
        # Read the first batch to get the schema
        with csv.open_csv(
            self.csv_path,
            read_options=self.read_options,
            parse_options=self.parse_options,
            convert_options=self.convert_options
        ) as reader:
            batch_reader = reader.read_batch(self.batch_size)
            if batch_reader:
                return batch_reader.schema
            else:
                # Empty file, return a minimal schema
                return pa.schema([])


class JSONStreamingLoader(StreamingDataLoader):
    """
    High-Performance Streaming Loader for Newline-Delimited JSON Files

    The JSONStreamingLoader class provides memory-efficient, high-throughput access to
    newline-delimited JSON (NDJSON) files without loading entire datasets into memory.
    It leverages PyArrow's streaming JSON capabilities with configurable parsing options
    for handling diverse JSON structures and data types.

    This loader is specifically designed for NDJSON format where each line contains
    a separate JSON object, making it ideal for log files, data exports, and
    streaming data processing scenarios.

    Args:
        json_path (str): Path to newline-delimited JSON file. Each line must contain
            a valid JSON object with consistent schema across the file.
        read_options (Optional[pyarrow.json.ReadOptions], optional): PyArrow read
            options controlling file reading behavior including block size and
            threading configuration. Defaults to None (use PyArrow defaults).
        parse_options (Optional[pyarrow.json.ParseOptions], optional): PyArrow parse
            options controlling JSON parsing behavior, type inference, and schema
            handling. Defaults to None (use PyArrow defaults).
        batch_size (int, optional): Number of records per streaming batch. Larger
            values improve throughput but increase memory usage. Defaults to 10000.
        prefetch_batches (int, optional): Number of batches to prefetch asynchronously
            for improved I/O performance. Defaults to 2.
        cache_enabled (bool, optional): Whether to enable intelligent caching of
            processed data segments. Defaults to True.
        cache_size_mb (int, optional): Maximum cache size in megabytes when caching
            is enabled. Defaults to 100.
        collect_stats (bool, optional): Whether to collect detailed performance
            statistics during streaming operations. Defaults to True.

    Key Features:
    - Memory-efficient streaming of arbitrarily large NDJSON files
    - Automatic JSON schema inference and type conversion
    - Support for nested JSON structures and complex data types
    - Configurable parsing options for diverse JSON formats
    - Robust error handling for malformed JSON records
    - Seamless integration with Arrow ecosystem and pandas

    Attributes:
        json_path (str): Path to the JSON file being processed
        read_options (pyarrow.json.ReadOptions): Configuration for file reading
        parse_options (pyarrow.json.ParseOptions): Configuration for JSON parsing

    Public Methods:
        __iter__() -> Iterator[pyarrow.Table]:
            Create iterator over JSON data batches with automatic resource management.
        iter_batches() -> Iterator[pyarrow.Table]:
            Iterate over batches with optional prefetching for enhanced performance.
        to_arrow_table() -> pyarrow.Table:
            Load entire JSON file into memory as single Arrow table.
        to_pandas() -> pandas.DataFrame:
            Convert entire JSON file to pandas DataFrame.
        get_schema() -> pyarrow.Schema:
            Retrieve JSON schema with inferred column types.

    Usage Example:
        # Basic JSON loading
        loader = JSONStreamingLoader("logs.jsonl")
        
        # Advanced JSON loading with custom options
        read_opts = pa.json.ReadOptions(
            block_size=4*1024*1024,  # 4MB blocks
            use_threads=True
        )
        
        loader = JSONStreamingLoader(
            json_path="large_dataset.jsonl",
            read_options=read_opts,
            batch_size=20000,
            prefetch_batches=3
        )
        
        # Process streaming JSON data
        for batch in loader.iter_batches():
            normalized_batch = normalize_json_records(batch)
            index_documents(normalized_batch)

    Raises:
        ImportError: If PyArrow is not available for JSON operations
        FileNotFoundError: If json_path does not exist or is inaccessible
        ValueError: If file exists but is not valid newline-delimited JSON
        PermissionError: If insufficient permissions to read the specified file
    """

    def __init__(
        self,
        json_path,
        read_options=None,
        parse_options=None,
        batch_size=10000,
        prefetch_batches=2,
        cache_enabled=True,
        cache_size_mb=100,
        collect_stats=True
    ):
        """
        Initialize JSON streaming loader with comprehensive parsing configuration.

        Args:
            json_path (str): Path to newline-delimited JSON file. Must contain valid
                NDJSON format with one JSON object per line.
            read_options (Optional[pyarrow.json.ReadOptions], optional): PyArrow read
                options controlling file access including block size, threading,
                and encoding settings. Defaults to None (PyArrow defaults).
            parse_options (Optional[pyarrow.json.ParseOptions], optional): PyArrow parse
                options controlling JSON parsing behavior, type inference, and
                schema handling. Defaults to None (PyArrow defaults).
            batch_size (int, optional): Records per batch for memory management.
                Must be positive. Defaults to 10000.
            prefetch_batches (int, optional): Asynchronous prefetch queue depth.
                Must be non-negative. Defaults to 2.
            cache_enabled (bool, optional): Enable intelligent batch caching.
                Defaults to True.
            cache_size_mb (int, optional): Maximum cache size in megabytes.
                Must be positive when caching enabled. Defaults to 100.
            collect_stats (bool, optional): Enable performance statistics collection.
                Defaults to True.

        Raises:
            ImportError: If PyArrow is not available for JSON streaming operations
            FileNotFoundError: If json_path does not exist or is not accessible
            PermissionError: If insufficient permissions to read json_path

        Attributes initialized:
            json_path (str): Stored path to the JSON file
            read_options (pyarrow.json.ReadOptions): File reading configuration
            parse_options (pyarrow.json.ParseOptions): JSON parsing configuration
        """
        super().__init__(
            batch_size=batch_size,
            prefetch_batches=prefetch_batches,
            cache_enabled=cache_enabled,
            cache_size_mb=cache_size_mb,
            collect_stats=collect_stats
        )

        if not HAVE_ARROW:
            raise ImportError("PyArrow is required for JSON streaming")

        self.json_path = json_path

        # Set up options
        self.read_options = read_options or json_pa.ReadOptions(
            block_size=1024 * 1024  # 1MB blocks
        )

        # Make sure the batch size is set
        self.read_options = json_pa.ReadOptions(
            block_size=self.read_options.block_size,
            use_threads=self.read_options.use_threads
        )

        self.parse_options = parse_options or json_pa.ParseOptions()

    def __iter__(self):
        """
        Create an iterator over the JSON dataset with streaming processing.

        Opens the JSON file using PyArrow's streaming JSON reader and yields
        batches of records as Arrow tables. The iterator handles large files
        efficiently by processing data in chunks without loading the entire
        file into memory.

        Yields:
            pyarrow.Table: Batches of JSON records converted to Arrow format.
                Each batch contains multiple records according to the configured
                batch size, with automatic schema inference and type conversion.

        Raises:
            FileNotFoundError: If the JSON file path does not exist.
            pyarrow.lib.ArrowInvalid: If the JSON file contains invalid syntax
                or cannot be parsed according to the parse options.
            MemoryError: If batch size is too large for available memory.

        Example:
            >>> loader = JSONStreamingLoader("large_file.jsonl", batch_size=1000)
            >>> for batch in loader:
            ...     print(f"Batch shape: {batch.shape}")
            ...     # Process batch data
            ...     processed = batch.select(["id", "text", "score"])

        Note:
            Uses PyArrow's native JSON streaming capabilities for optimal
            performance. The file is processed line-by-line for JSONL format
            or as a single JSON array for standard JSON files.
        """
        # Open the JSON file for streaming
        with json_pa.open_json(
            self.json_path,
            read_options=self.read_options,
            parse_options=self.parse_options
        ) as reader:
            # Read and yield batches
            batch_reader = reader.read_batch(self.batch_size)
            while batch_reader:
                self._start_batch_stats()
                batch = batch_reader.to_table()
                self._end_batch_stats(len(batch))
                yield batch

                # Read the next batch
                batch_reader = reader.read_batch(self.batch_size)

    def iter_batches(self):
        """
        Iterate over batches with optional prefetching.

        Yields:
            pyarrow.Table: Batch of records
        """
        if self.prefetch_batches > 1:
            return PrefetchingQueue(self, self.prefetch_batches)
        return self

    def to_arrow_table(self):
        """
        Convert the entire JSON file to an Arrow table.

        This loads the entire file into memory, so use with caution
        for large files.

        Returns:
            pyarrow.Table: The loaded table

        Raises:
            MemoryError: If the file is too large to fit in memory
        """
        return json_pa.read_json(
            self.json_path,
            read_options=self.read_options,
            parse_options=self.parse_options
        )

    def to_pandas(self):
        """
        Convert the entire JSON file to a pandas DataFrame.

        This loads the entire file into memory, so use with caution
        for large files.

        Returns:
            pandas.DataFrame: The loaded DataFrame

        Raises:
            MemoryError: If the file is too large to fit in memory
            ImportError: If pandas is not available
        """
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("Pandas is required for this operation")

        table = self.to_arrow_table()
        return table.to_pandas()

    def get_schema(self):
        """
        Get the schema of the JSON file.

        This reads the first batch to determine the schema.

        Returns:
            pyarrow.Schema: The file schema
        """
        # Read the first batch to get the schema
        with json_pa.open_json(
            self.json_path,
            read_options=self.read_options,
            parse_options=self.parse_options
        ) as reader:
            batch_reader = reader.read_batch(self.batch_size)
            if batch_reader:
                return batch_reader.schema
            else:
                # Empty file, return a minimal schema
                return pa.schema([])


class HuggingFaceStreamingLoader(StreamingDataLoader):
    """
    High-Performance Streaming Loader for HuggingFace Datasets

    The HuggingFaceStreamingLoader class provides memory-efficient access to HuggingFace
    datasets using streaming mode to avoid loading entire datasets into memory. It supports
    both datasets from the HuggingFace Hub and local dataset objects, with intelligent
    column projection and batch processing for optimal performance.

    This loader is essential for working with large-scale datasets from the HuggingFace
    ecosystem, enabling processing of datasets that exceed available RAM while maintaining
    high throughput and providing seamless integration with the datasets library.

    Args:
        dataset_name (Optional[str], optional): Name of dataset from HuggingFace Hub.
            Format: "username/dataset-name" or "dataset-name" for official datasets.
            Required if dataset_object is not provided.
        dataset_config (Optional[str], optional): Dataset configuration name for
            datasets with multiple configurations. Defaults to None (default config).
        dataset_split (str, optional): Dataset split to load ("train", "validation",
            "test", etc.). Must exist in the specified dataset. Defaults to "train".
        dataset_object (Optional[datasets.Dataset], optional): Pre-loaded HuggingFace
            dataset object to wrap. Alternative to loading from Hub. Must support
            streaming if not already in streaming mode.
        columns (Optional[List[str]], optional): Specific columns to select from
            the dataset. Enables column projection for reduced memory usage.
            Defaults to None (all columns).
        batch_size (int, optional): Number of records per streaming batch. Larger
            values improve throughput but increase memory usage. Defaults to 10000.
        prefetch_batches (int, optional): Number of batches to prefetch asynchronously
            for improved performance. Defaults to 2.
        cache_enabled (bool, optional): Whether to enable intelligent caching of
            processed data segments. Defaults to True.
        cache_size_mb (int, optional): Maximum cache size in megabytes when caching
            is enabled. Defaults to 100.
        collect_stats (bool, optional): Whether to collect detailed performance
            statistics during streaming operations. Defaults to True.

    Key Features:
    - Memory-efficient streaming of arbitrarily large HuggingFace datasets
    - Support for both Hub datasets and local dataset objects
    - Column projection for reduced memory usage and improved performance
    - Automatic conversion to Arrow format for efficient processing
    - Seamless integration with HuggingFace datasets ecosystem
    - Comprehensive metadata access and feature inspection

    Attributes:
        columns (Optional[List[str]]): Selected columns for projection
        dataset (datasets.Dataset): The underlying HuggingFace dataset in streaming mode

    Public Methods:
        __iter__() -> Iterator[pyarrow.Table]:
            Create iterator over dataset batches with automatic Arrow conversion.
        iter_batches() -> Iterator[pyarrow.Table]:
            Iterate over batches with optional prefetching for enhanced performance.
        get_features() -> datasets.Features:
            Retrieve dataset features and column type information.
        get_schema() -> pyarrow.Schema:
            Get Arrow schema derived from dataset features.
        get_metadata() -> Dict[str, Any]:
            Access comprehensive dataset metadata and information.

    Usage Example:
        # Load popular dataset from Hub
        loader = HuggingFaceStreamingLoader(
            dataset_name="squad",
            dataset_split="train",
            columns=["question", "context", "answers"]
        )
        
        # Load with configuration and optimization
        loader = HuggingFaceStreamingLoader(
            dataset_name="c4",
            dataset_config="en",
            dataset_split="train",
            batch_size=5000,
            prefetch_batches=4,
            cache_size_mb=500
        )
        
        # Process streaming data
        for batch in loader.iter_batches():
            processed_batch = preprocess_text_batch(batch)
            train_model_on_batch(processed_batch)
        
        # Use existing dataset object
        existing_dataset = load_dataset("imdb", split="train", streaming=True)
        loader = HuggingFaceStreamingLoader(dataset_object=existing_dataset)

    Raises:
        ImportError: If HuggingFace datasets library is not available
        ValueError: If neither dataset_name nor dataset_object is provided
        ConnectionError: If unable to download dataset from HuggingFace Hub
        DatasetNotFoundError: If specified dataset or split does not exist
    """

    def __init__(
        self,
        dataset_name=None,
        dataset_config=None,
        dataset_split="train",
        dataset_object=None,
        columns=None,
        batch_size=10000,
        prefetch_batches=2,
        cache_enabled=True,
        cache_size_mb=100,
        collect_stats=True
    ):
        """
        Initialize HuggingFace streaming loader with comprehensive configuration options.

        Args:
            dataset_name (Optional[str], optional): Name of dataset from HuggingFace Hub.
                Format: "username/dataset-name" or "dataset-name" for official datasets.
                Required if dataset_object is not provided.
            dataset_config (Optional[str], optional): Dataset configuration name for
                datasets with multiple configurations. Defaults to None (default config).
            dataset_split (str, optional): Dataset split to load ("train", "validation",
                "test", etc.). Must exist in the specified dataset. Defaults to "train".
            dataset_object (Optional[datasets.Dataset], optional): Pre-loaded HuggingFace
                dataset object to wrap. Alternative to loading from Hub.
            columns (Optional[List[str]], optional): Specific columns to select from
                the dataset. Enables column projection for reduced memory usage.
                Defaults to None (all columns).
            batch_size (int, optional): Records per batch for memory management.
                Must be positive. Defaults to 10000.
            prefetch_batches (int, optional): Asynchronous prefetch queue depth.
                Must be non-negative. Defaults to 2.
            cache_enabled (bool, optional): Enable intelligent batch caching.
                Defaults to True.
            cache_size_mb (int, optional): Maximum cache size in megabytes.
                Must be positive when caching enabled. Defaults to 100.
            collect_stats (bool, optional): Enable performance statistics collection.
                Defaults to True.

        Raises:
            ImportError: If HuggingFace datasets library is not available
            ValueError: If neither dataset_name nor dataset_object is provided
            ConnectionError: If unable to access dataset from HuggingFace Hub
            DatasetNotFoundError: If specified dataset, configuration, or split does not exist

        Attributes initialized:
            columns (Optional[List[str]]): Column projection configuration
            dataset (datasets.Dataset): HuggingFace dataset in streaming mode with
                column selection applied if specified
        """
        super().__init__(
            batch_size=batch_size,
            prefetch_batches=prefetch_batches,
            cache_enabled=cache_enabled,
            cache_size_mb=cache_size_mb,
            collect_stats=collect_stats
        )

        if not HAVE_DATASETS:
            raise ImportError("HuggingFace datasets is required for this loader")

        self.columns = columns

        # Load dataset
        if dataset_object is not None:
            self.dataset = dataset_object
        elif dataset_name is not None:
            # Load from HuggingFace Hub
            self.dataset = load_dataset(
                dataset_name,
                dataset_config,
                split=dataset_split,
                streaming=True  # Important for memory efficiency
            )
        else:
            raise ValueError("Either dataset_name or dataset_object must be provided")

        # Select columns if specified
        if columns is not None:
            self.dataset = self.dataset.select_columns(columns)

    def __iter__(self):
        """
        Create an iterator over the HuggingFace dataset with streaming processing.

        Iterates through the HuggingFace dataset in streaming mode, accumulating
        examples into batches and converting them to PyArrow tables for efficient
        processing. This approach enables working with large datasets that don't
        fit in memory while maintaining compatibility with PyArrow ecosystems.

        Yields:
            pyarrow.Table: Batches of dataset examples converted to Arrow format.
                Each batch contains the configured number of examples with
                automatic type inference and schema consistency across batches.

        Example:
            >>> loader = HuggingFaceStreamingLoader(
            ...     "squad", batch_size=100, columns=["question", "context"]
            ... )
            >>> for batch in loader:
            ...     questions = batch["question"].to_pylist()
            ...     contexts = batch["context"].to_pylist()
            ...     # Process question-answer pairs

        Performance Note:
            The streaming mode (streaming=True) is essential for memory efficiency
            with large datasets. Batch conversion to Arrow format enables
            vectorized operations and integration with PyArrow-based pipelines.

        Note:
            The final batch may contain fewer examples than batch_size if the
            dataset size is not evenly divisible by the batch size.
        """
        batch = []
        for i, example in enumerate(self.dataset):
            batch.append(example)

            if len(batch) >= self.batch_size:
                # Convert batch to Arrow table
                self._start_batch_stats()
                table = self._batch_to_arrow(batch)
                self._end_batch_stats(len(batch))
                yield table
                batch = []

        # Yield the final batch if any
        if batch:
            self._start_batch_stats()
            table = self._batch_to_arrow(batch)
            self._end_batch_stats(len(batch))
            yield table

    def _batch_to_arrow(self, batch):
        """
        Convert a batch of examples to an Arrow table.

        Args:
            batch (List[Dict]): Batch of examples

        Returns:
            pyarrow.Table: The batch as an Arrow table
        """
        # Extract features
        features = self.dataset.features

        # Organize data by column
        columns = {}
        for example in batch:
            for key, value in example.items():
                if key not in columns:
                    columns[key] = []
                columns[key].append(value)

        # Convert to Arrow arrays
        arrays = []
        names = []

        for name, values in columns.items():
            if name in features:
                # Use the feature to convert to Arrow
                feature = features[name]
                array = feature.encode_batch(values)
            else:
                # Infer type
                array = pa.array(values)

            arrays.append(array)
            names.append(name)

        # Create table
        return pa.Table.from_arrays(arrays, names)

    def iter_batches(self):
        """
        Iterate over batches with optional prefetching.

        Yields:
            pyarrow.Table: Batch of records
        """
        if self.prefetch_batches > 1:
            return PrefetchingQueue(self, self.prefetch_batches)
        return self

    def get_features(self):
        """
        Get the features of the dataset.

        Returns:
            datasets.Features: The dataset features
        """
        return self.dataset.features

    def get_schema(self):
        """
        Get the schema of the dataset.

        Returns:
            pyarrow.Schema: The dataset schema
        """
        # Infer from the features if possible
        features = self.get_features()
        return features.arrow_schema

    def get_metadata(self):
        """
        Get metadata about the dataset.

        Returns:
            dict: Dataset metadata
        """
        info = {}

        # Add dataset info
        if hasattr(self.dataset, 'info'):
            info_obj = self.dataset.info

            if hasattr(info_obj, 'description'):
                info['description'] = info_obj.description

            if hasattr(info_obj, 'citation'):
                info['citation'] = info_obj.citation

            if hasattr(info_obj, 'homepage'):
                info['homepage'] = info_obj.homepage

            if hasattr(info_obj, 'version'):
                info['version'] = str(info_obj.version)

            if hasattr(info_obj, 'features'):
                info['features'] = str(info_obj.features)

        return info


class MemoryMappedVectorLoader:
    """
    Memory-Mapped Vector Dataset Loader for Large-Scale Vector Operations

    The MemoryMappedVectorLoader class provides efficient random access to large vector
    datasets using memory mapping technology. This approach enables processing of vector
    datasets that exceed available RAM by mapping file contents directly into virtual
    memory space, allowing the operating system to handle paging automatically.

    This loader is optimized for machine learning and similarity search applications
    that require efficient access to large collections of high-dimensional vectors
    without the memory overhead of loading entire datasets.

    Args:
        file_path (Optional[str], optional): Path to binary file containing vector data.
            File should contain vectors stored consecutively in the specified dtype.
            Required if existing_mmap is not provided.
        dimension (Optional[int], optional): Number of dimensions per vector. Required
            for proper reshaping of the memory map when file_path is provided.
        dtype (numpy.dtype, optional): NumPy data type for vector elements. Supports
            all numeric types (float32, float64, int32, etc.). Defaults to numpy.float32.
        mode (str, optional): Memory mapping mode. 'r' for read-only, 'r+' for
            read-write, 'w+' for write with truncation. Defaults to 'r'.
        offset (int, optional): Byte offset from file start where vector data begins.
            Useful for files with headers or metadata. Defaults to 0.
        existing_mmap (Optional[numpy.memmap], optional): Pre-existing memory map
            to wrap. Alternative to creating new map from file_path.

    Key Features:
    - Memory-efficient access to arbitrarily large vector datasets
    - Random access patterns with O(1) complexity for vector retrieval
    - Support for read-only and read-write operations
    - Automatic file growth and vector appending capabilities
    - Operating system-level memory management and caching
    - Support for all NumPy numeric data types

    Attributes:
        memmap (Optional[numpy.memmap]): Memory-mapped array providing vector access
        dimension (Optional[int]): Number of dimensions per vector
        dtype (numpy.dtype): Data type of vector elements
        file_path (Optional[str]): Path to the underlying file
        vector_size_bytes (int): Size of each vector in bytes

    Public Methods:
        __len__() -> int:
            Get the total number of vectors in the dataset.
        __getitem__(idx) -> numpy.ndarray:
            Retrieve vector(s) by index with support for slicing.
        append(vectors) -> None:
            Add new vectors to the dataset (requires write mode).
        close() -> None:
            Flush changes and release memory map resources.

    Context Manager Support:
        Supports 'with' statement for automatic resource management and cleanup.

    Usage Example:
        # Create new memory-mapped vector dataset
        vectors = np.random.random((1000000, 128)).astype(np.float32)
        
        with MemoryMappedVectorLoader(
            file_path="large_vectors.bin",
            dimension=128,
            dtype=np.float32,
            mode="w+"
        ) as loader:
            loader.append(vectors)
            
            # Random access to vectors
            vector_100 = loader[100]
            vector_slice = loader[1000:2000]
        
        # Read-only access to existing dataset
        with MemoryMappedVectorLoader(
            file_path="large_vectors.bin",
            dimension=128,
            mode="r"
        ) as loader:
            print(f"Dataset contains {len(loader)} vectors")
            similarity_search(loader[query_indices])

    Raises:
        ImportError: If NumPy is not available in the environment
        ValueError: If neither file_path nor existing_mmap is provided
        PermissionError: If insufficient permissions for file access
        OSError: If file operations fail or insufficient disk space
    """

    def __init__(
        self,
        file_path=None,
        dimension=None,
        dtype=np.float32,
        mode='r',
        offset=0,
        existing_mmap=None
    ):
        """
        Initialize memory-mapped vector loader with flexible configuration options.

        Args:
            file_path (Optional[str], optional): Path to binary vector file. Must be
                provided if existing_mmap is None. File will be created if it doesn't
                exist and mode allows writing.
            dimension (Optional[int], optional): Vector dimensionality. Required when
                file_path is provided for proper memory map reshaping. Must be positive.
            dtype (numpy.dtype, optional): NumPy data type for vector elements.
                Common choices: np.float32 (space-efficient), np.float64 (high precision).
                Defaults to np.float32.
            mode (str, optional): File access mode. 'r' for read-only (safe for shared
                access), 'r+' for read-write (existing file), 'w+' for write with
                truncation. Defaults to 'r'.
            offset (int, optional): Byte offset from file start. Useful for skipping
                headers or metadata sections. Must be non-negative. Defaults to 0.
            existing_mmap (Optional[numpy.memmap], optional): Pre-existing memory map
                to wrap. When provided, file_path and dimension are ignored.

        Raises:
            ImportError: If NumPy is not available for memory mapping operations
            ValueError: If neither file_path nor existing_mmap is provided, or if
                dimension is not specified with file_path
            FileNotFoundError: If file_path doesn't exist and mode is read-only
            PermissionError: If insufficient permissions for specified mode
            OSError: If file system operations fail

        Attributes initialized:
            memmap (Optional[numpy.memmap]): Memory-mapped array for vector access
            dimension (Optional[int]): Vector dimensionality for reshaping operations
            dtype (numpy.dtype): Data type configuration for vector elements
            file_path (Optional[str]): File system path to the vector data file
            vector_size_bytes (int): Calculated size per vector for memory management
        """
        if not HAVE_NUMPY:
            raise ImportError("NumPy is required for memory-mapped vectors")

        if existing_mmap is not None:
            # Use existing memory map
            self.memmap = existing_mmap
            self.dimension = existing_mmap.shape[1] if len(existing_mmap.shape) > 1 else None
            self.dtype = existing_mmap.dtype
            self.file_path = None
        elif file_path is not None and dimension is not None:
            # Create new memory map
            self.file_path = file_path
            self.dimension = dimension
            self.dtype = dtype

            # Check if the file exists
            file_exists = os.path.exists(file_path)

            # Create an empty file if it doesn't exist and mode allows writing
            if not file_exists and mode in ('r+', 'w+'):
                with open(file_path, 'wb') as f:
                    # Write an empty placeholder
                    pass

            # Create memory map
            self.memmap = np.memmap(
                file_path,
                dtype=dtype,
                mode=mode,
                offset=offset
            )

            # If the file exists, try to reshape the memmap
            if file_exists:
                # Calculate number of vectors
                vector_size = dimension * np.dtype(dtype).itemsize
                file_size = os.path.getsize(file_path) - offset
                num_vectors = file_size // vector_size

                # Reshape memmap
                if num_vectors > 0:
                    self.memmap = self.memmap.reshape((num_vectors, dimension))
        else:
            raise ValueError("Either file_path and dimension, or existing_mmap must be provided")

        # Calculate vector size in bytes
        self.vector_size_bytes = self.dimension * np.dtype(self.dtype).itemsize

    def __len__(self):
        """
        Get the total number of vectors in the memory-mapped dataset.

        Returns:
            int: Number of vectors available in the dataset, or 0 if the
                 memory map is not initialized or contains no vectors
        """
        if self.memmap is None:
            return 0

        if len(self.memmap.shape) == 1:
            # Not properly initialized or no vectors
            return 0

        return self.memmap.shape[0]

    def __getitem__(self, idx):
        """
        Get a vector or slice of vectors.

        Args:
            idx (int or slice): Index or slice to retrieve

        Returns:
            numpy.ndarray: The requested vector(s)

        Raises:
            IndexError: If the index is out of bounds
        """
        if self.memmap is None:
            raise RuntimeError("Memory map is not initialized")

        if isinstance(idx, slice):
            # Slice of vectors
            return np.array(self.memmap[idx])
        else:
            # Single vector
            return np.array(self.memmap[idx])

    def append(self, vectors):
        """
        Append new vectors to the memory-mapped dataset with automatic file growth.

        Adds one or more vectors to the end of the existing dataset, automatically
        resizing the underlying file as needed. The operation preserves all existing
        data and ensures the new vectors are stored consecutively.

        Args:
            vectors (numpy.ndarray): Vectors to append to the dataset. Can be:
                - 1D array: Single vector with shape (dimension,)
                - 2D array: Multiple vectors with shape (n_vectors, dimension)
                The dtype should match the dataset's dtype and dimension must
                match the dataset's configured dimension.

        Raises:
            RuntimeError: If the memory map is not initialized or is in read-only mode.
            ValueError: If vectors have incorrect shape or dimension mismatch.
            OSError: If file resize operation fails due to insufficient disk space.
            TypeError: If vectors is not a numpy array or has wrong dtype.

        Example:
            >>> # Append single vector
            >>> loader = MemoryMappedVectorLoader("vectors.bin", 128, mode="r+")
            >>> new_vector = np.random.random(128).astype(np.float32)
            >>> loader.append(new_vector)
            >>> 
            >>> # Append multiple vectors
            >>> batch_vectors = np.random.random((1000, 128)).astype(np.float32) 
            >>> loader.append(batch_vectors)
            >>> print(f"Dataset now contains {len(loader)} vectors")

        Performance Note:
            Appending large batches of vectors is more efficient than appending
            individual vectors due to reduced file resize operations.
        """
        if self.memmap is None:
            raise RuntimeError("Memory map is not initialized")

        if self.memmap.mode not in ('r+', 'w+'):
            raise RuntimeError("Memory map is read-only")

        # Ensure vectors have the right shape
        if len(vectors.shape) == 1:
            # Single vector
            if vectors.shape[0] != self.dimension:
                raise ValueError(f"Vector dimension {vectors.shape[0]} doesn't match expected dimension {self.dimension}")
            vectors = vectors.reshape(1, -1)
        else:
            # Multiple vectors
            if vectors.shape[1] != self.dimension:
                raise ValueError(f"Vector dimension {vectors.shape[1]} doesn't match expected dimension {self.dimension}")

        # Get current number of vectors
        current_len = len(self)

        # Calculate new size
        new_size = current_len + vectors.shape[0]

        # Resize the file
        fp = np.memmap(self.file_path, dtype=self.dtype, mode='r+')
        fp.resize(new_size * self.vector_size_bytes)
        del fp

        # Re-open the memory map with the new size
        self.memmap = np.memmap(
            self.file_path,
            dtype=self.dtype,
            mode='r+',
            shape=(new_size, self.dimension)
        )

        # Write the new vectors
        self.memmap[current_len:new_size] = vectors

    def close(self):
        """
        Close the memory map and flush any pending changes to disk.

        This method ensures all pending writes are flushed to the underlying
        file and releases the memory map resources. After calling this method,
        the loader cannot be used for further operations.
        """
        if self.memmap is not None:
            # Flush changes to disk
            self.memmap.flush()

            # Delete the memmap object
            del self.memmap
            self.memmap = None

    def __enter__(self):
        """
        Enter context manager for automatic resource management.

        Returns:
            MemoryMappedVectorLoader: Self for use in with statement
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit context manager and automatically close memory map.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred  
            exc_tb: Exception traceback if an exception occurred

        Returns:
            None: Does not suppress exceptions
        """
        self.close()


class StreamingDataset:
    """
    High-Level Unified API for Streaming Dataset Operations

    The StreamingDataset class provides a comprehensive, user-friendly interface for
    working with streaming datasets across different data formats and sources. It abstracts
    the complexity of different streaming loaders while providing powerful data
    transformation, filtering, and processing capabilities.

    This class follows functional programming patterns similar to Apache Spark and
    modern data processing frameworks, enabling chainable operations and lazy evaluation
    for memory-efficient data processing pipelines.

    Args:
        loader (StreamingDataLoader): Any streaming loader instance (Parquet, CSV, JSON,
            HuggingFace, etc.) that provides the underlying data access functionality.

    Key Features:
    - Unified interface across different data formats and sources
    - Functional programming patterns with chainable operations
    - Lazy evaluation for memory-efficient processing
    - Built-in transformation and filtering capabilities
    - Seamless integration with Arrow and pandas ecosystems
    - Performance monitoring and statistics collection
    - Support for both batch and element-wise operations

    Attributes:
        loader (StreamingDataLoader): Underlying streaming loader providing data access

    Public Methods:
        iter_batches(batch_processor=None) -> Iterator:
            Iterate over data batches with optional processing function.
        map(function, batched=True) -> StreamingDataset:
            Apply transformation function to batches or individual elements.
        filter(function, batched=True) -> StreamingDataset:
            Filter data using predicate function on batches or elements.
        to_arrow_table() -> pyarrow.Table:
            Materialize entire dataset as Arrow table (memory permitting).
        to_pandas() -> pandas.DataFrame:
            Convert entire dataset to pandas DataFrame (memory permitting).
        get_stats() -> Dict[str, Any]:
            Retrieve comprehensive performance statistics from underlying loader.

    Transformation Patterns:
        - Method chaining for complex data pipelines
        - Lazy evaluation minimizes memory usage
        - Support for both vectorized (batched) and element-wise operations
        - Automatic type preservation through Arrow ecosystem

    Usage Example:
        # Load and process large dataset with transformations
        dataset = StreamingDataset(
            ParquetStreamingLoader("large_dataset.parquet", batch_size=10000)
        )
        
        # Chain transformations with lazy evaluation
        processed = (dataset
            .filter(lambda batch: len(batch) > 0)  # Remove empty batches
            .map(lambda batch: compute_features(batch))  # Add computed columns
            .filter(lambda batch: batch.filter(pc.greater(pc.field("score"), 0.5)))  # Filter rows
        )
        
        # Process results in streaming fashion
        for batch in processed.iter_batches():
            save_to_database(batch)
        
        # Or materialize if memory allows
        result_df = processed.to_pandas()
        
        # Monitor performance
        stats = processed.get_stats()
        print(f"Processed {stats['throughput']['total_records']} records")

    Performance Considerations:
        - Transformations are applied during iteration, not eagerly
        - Memory usage scales with batch size, not dataset size
        - Complex transformations may benefit from larger batch sizes
        - Statistics collection provides insights for optimization
    """

    def __init__(self, loader):
        """
        Initialize streaming dataset with underlying loader for data access.

        Args:
            loader (StreamingDataLoader): Any streaming loader instance that provides
                data access functionality. Must implement the streaming loader interface
                with iteration capabilities and optional statistics collection.

        Attributes initialized:
            loader (StreamingDataLoader): Reference to the underlying streaming loader
                that provides actual data access and streaming capabilities.
        """
        self.loader = loader

    def iter_batches(self, batch_processor=None):
        """
        Iterate over data batches with optional processing function.

        Provides a flexible interface for processing streaming data with optional
        transformation applied to each batch. This method maintains the streaming
        nature of the data while allowing for custom processing logic.

        Args:
            batch_processor (Optional[Callable[[Any], Any]], optional): Function to
                apply to each batch before yielding. Should take a batch (typically
                pyarrow.Table) and return a processed batch. If None, batches are
                yielded unchanged. Defaults to None.

        Yields:
            Any: Batches from the underlying loader, optionally processed by
                batch_processor. The exact type depends on the loader and processor.

        Example:
            >>> dataset = StreamingDataset(loader)
            >>> 
            >>> # Process without transformation
            >>> for batch in dataset.iter_batches():
            ...     analyze_batch(batch)
            >>> 
            >>> # Process with custom transformation
            >>> def add_metadata(batch):
            ...     # Add processing timestamp
            ...     return batch.append_column("processed_at", 
            ...                               [datetime.now()] * len(batch))
            >>> 
            >>> for processed_batch in dataset.iter_batches(add_metadata):
            ...     save_batch(processed_batch)

        Performance Note:
            The batch_processor function is applied during iteration, so complex
            processing functions may impact throughput. Consider the trade-off
            between convenience and performance for your use case.
        """
        for batch in self.loader.iter_batches():
            if batch_processor:
                yield batch_processor(batch)
            else:
                yield batch

    def map(self, function, batched=True):
        """
        Apply a transformation function to the dataset with lazy evaluation.

        Creates a new streaming dataset with the specified transformation applied
        during iteration. Supports both batch-level and element-level transformations
        with chainable operations for building complex data processing pipelines.

        Args:
            function (Callable): Transformation function to apply. For batch-level
                transformations (batched=True), should take a batch (typically 
                pyarrow.Table) and return a transformed batch. For element-level
                transformations (batched=False), should take a record dictionary
                and return a transformed record dictionary.
            batched (bool, optional): Whether to apply transformation at batch level
                (True) or individual element level (False). Batch-level is generally
                more efficient for vectorized operations. Defaults to True.

        Returns:
            StreamingDataset: A new streaming dataset that applies the transformation
                during iteration. The original dataset is not modified.

        Example:
            >>> # Batch-level transformation (efficient)
            >>> def add_computed_column(batch):
            ...     import pyarrow.compute as pc
            ...     total = pc.add(batch["price"], batch["tax"])
            ...     return batch.append_column("total", total)
            >>> 
            >>> transformed = dataset.map(add_computed_column, batched=True)
            >>> 
            >>> # Element-level transformation (flexible but slower)
            >>> def normalize_text(record):
            ...     record["text"] = record["text"].lower().strip()
            ...     return record
            >>> 
            >>> normalized = dataset.map(normalize_text, batched=False)
            >>> 
            >>> # Chain multiple transformations
            >>> result = (dataset
            ...           .map(add_computed_column, batched=True)
            ...           .map(normalize_text, batched=False))

        Performance Note:
            Batch-level transformations are generally much faster than element-level
            transformations due to vectorization and reduced Python overhead.
            Use element-level transformations only when the logic cannot be
            expressed efficiently at the batch level.
        """
        if batched:
            return StreamingDataset(
                TransformedLoader(self.loader, function)
            )
        else:
            return StreamingDataset(
                ElementwiseTransformedLoader(self.loader, function)
            )

    def filter(self, function, batched=True):
        """
        Filter dataset elements based on a predicate function with lazy evaluation.

        Creates a new streaming dataset that includes only elements or batches
        that satisfy the predicate condition. The filtering is applied during
        iteration, maintaining the streaming nature and memory efficiency.

        Args:
            function (Callable): Filtering predicate function. For batch-level
                filtering (batched=True), should take a batch (typically pyarrow.Table)
                and return a boolean mask array or filtered batch. For element-level
                filtering (batched=False), should take a record dictionary and
                return a boolean indicating whether to include the element.
            batched (bool, optional): Whether to apply filtering at batch level
                (True) or individual element level (False). Batch-level filtering
                is generally more efficient. Defaults to True.

        Returns:
            StreamingDataset: A new streaming dataset containing only elements
                that satisfy the predicate. The original dataset is not modified.

        Example:
            >>> # Batch-level filtering (efficient)
            >>> def filter_high_scores(batch):
            ...     import pyarrow.compute as pc
            ...     return pc.filter(batch, pc.greater(batch["score"], 0.8))
            >>> 
            >>> high_score_data = dataset.filter(filter_high_scores, batched=True)
            >>> 
            >>> # Element-level filtering (flexible but slower)
            >>> def filter_english_only(record):
            ...     return record.get("language", "").lower() == "en"
            >>> 
            >>> english_data = dataset.filter(filter_english_only, batched=False)
            >>> 
            >>> # Chain filtering operations
            >>> result = (dataset
            ...           .filter(filter_high_scores, batched=True)
            ...           .filter(filter_english_only, batched=False))

        Performance Note:
            Batch-level filtering with PyArrow compute functions is significantly
            faster than element-level filtering due to vectorization. Consider
            implementing complex filtering logic using PyArrow compute operations
            when possible.

        Note:
            The resulting dataset size is not predictable until iteration is
            complete, as filtering may remove an arbitrary number of elements.
        """
        if batched:
            return StreamingDataset(
                FilteredLoader(self.loader, function)
            )
        else:
            return StreamingDataset(
                ElementwiseFilteredLoader(self.loader, function)
            )

    def to_arrow_table(self):
        """
        Convert the entire dataset to an Arrow table.

        Returns:
            pyarrow.Table: The dataset as an Arrow table
        """
        if hasattr(self.loader, 'to_arrow_table'):
            return self.loader.to_arrow_table()

        # Concatenate all batches
        batches = []
        for batch in self.iter_batches():
            batches.append(batch)

        if not batches:
            # Return empty table with schema if possible
            if hasattr(self.loader, 'get_schema'):
                return pa.table([], schema=self.loader.get_schema())
            return pa.table([])

        return pa.concat_tables(batches)

    def to_pandas(self):
        """
        Convert the entire dataset to a pandas DataFrame.

        Returns:
            pandas.DataFrame: The dataset as a DataFrame
        """
        if hasattr(self.loader, 'to_pandas'):
            return self.loader.to_pandas()

        table = self.to_arrow_table()
        return table.to_pandas()

    def get_stats(self):
        """
        Get comprehensive performance and usage statistics for the streaming dataset.

        Retrieves detailed metrics about dataset access patterns, performance
        characteristics, and resource utilization from the underlying data loader.
        Useful for monitoring, debugging, and optimizing data pipeline performance.

        Returns:
            dict: Comprehensive statistics dictionary containing performance metrics
                such as:
                - Access patterns (cache hits/misses, batch counts)
                - Performance metrics (throughput, latency, memory usage)
                - Resource utilization (I/O operations, network activity)
                - Error tracking (failed operations, retry counts)

        Example:
            >>> stats = dataset.get_stats()
            >>> print(f"Cache hit rate: {stats.get('cache_hit_rate', 'N/A'):.2%}")
            >>> print(f"Throughput: {stats.get('throughput_mb_per_sec', 0):.1f} MB/s")
            >>> print(f"Total batches: {stats.get('total_batches', 0)}")
            >>> 
            >>> # Monitor performance over time
            >>> initial_stats = dataset.get_stats()
            >>> # ... process some data ...
            >>> final_stats = dataset.get_stats()
            >>> processing_time = final_stats['total_time'] - initial_stats['total_time']

        Note:
            Statistics availability depends on the underlying data loader
            implementation. Some loaders may provide more detailed metrics
            than others.
        """


class TransformedLoader:
    """
    Batch-Level Transformation Loader for Streaming Data Processing

    The TransformedLoader class wraps an existing streaming loader to apply
    user-defined transformation functions to each batch during iteration. This
    enables efficient data processing pipelines with lazy evaluation and
    memory-efficient batch processing.

    This loader is designed for vectorized operations that work on entire
    Arrow tables or pandas DataFrames, providing optimal performance for
    computational transformations.

    Args:
        base_loader (StreamingDataLoader): The underlying streaming loader that
            provides the source data batches.
        transform_fn (Callable[[pyarrow.Table], pyarrow.Table]): Function that
            takes a batch (Arrow table) and returns a transformed batch.

    Key Features:
    - Lazy evaluation with transformations applied during iteration
    - Memory-efficient batch-level processing
    - Support for complex vectorized operations
    - Chainable with other transformation and filtering operations
    - Preserves underlying loader's performance characteristics

    Attributes:
        base_loader (StreamingDataLoader): Reference to the source data loader
        transform_fn (Callable): The transformation function to apply

    Public Methods:
        __iter__() -> Iterator[Any]:
            Create iterator that applies transformation to each batch.
        iter_batches() -> Iterator[Any]:
            Iterate over transformed batches (same as __iter__ for this class).

    Usage Example:
        # Create base loader
        base_loader = ParquetStreamingLoader("data.parquet")
        
        # Define transformation function
        def add_computed_columns(batch):
            # Add computed columns using PyArrow compute functions
            import pyarrow.compute as pc
            new_batch = batch.append_column(
                "total", 
                pc.add(batch["quantity"], batch["price"])
            )
            return new_batch
        
        # Create transformed loader
        transformed_loader = TransformedLoader(base_loader, add_computed_columns)
        
        # Process transformed data
        for batch in transformed_loader:
            print(f"Processed batch with {len(batch)} records")
            store_processed_batch(batch)
    """

    def __init__(self, base_loader, transform_fn):
        """
        Initialize batch-level transformation loader with source loader and transform function.

        Args:
            base_loader (StreamingDataLoader): The underlying streaming loader
                that provides source data batches. Must implement iteration protocol.
            transform_fn (Callable[[Any], Any]): Function that takes a batch
                and returns a transformed batch. Should handle the data format
                returned by the base loader (typically Arrow tables).

        Attributes initialized:
            base_loader (StreamingDataLoader): Reference to the source data loader
            transform_fn (Callable): Stored transformation function for batch processing
        """
        self.base_loader = base_loader
        self.transform_fn = transform_fn

    def __iter__(self):
        """
        Create an iterator that applies batch-level transformations.

        Iterates through the base loader and applies the configured transformation
        function to each batch. This enables complex data processing pipelines
        with efficient vectorized operations on entire batches rather than
        individual records.

        Yields:
            Transformed batches: The result of applying transform_fn to each batch
                from the base loader. The exact type depends on the transformation
                function but is typically a pyarrow.Table or similar batch format.

        Example:
            >>> def add_features(batch):
            ...     # Add computed columns using PyArrow compute functions
            ...     import pyarrow.compute as pc
            ...     batch = batch.append_column("length", 
            ...                                 pc.length(batch["text"]))
            ...     return batch
            >>> 
            >>> loader = TransformedLoader(base_loader, add_features)
            >>> for enhanced_batch in loader:
            ...     # Process enhanced batch with new computed columns
            ...     texts = enhanced_batch["text"]
            ...     lengths = enhanced_batch["length"]

        Performance Note:
            Batch-level transformations are generally much more efficient than
            element-level transformations due to vectorization opportunities
            and reduced per-record overhead.
        """
        for batch in self.base_loader:
            yield self.transform_fn(batch)

    def iter_batches(self):
        """
        Iterate over transformed batches.

        Yields:
            Transformed batches
        """
        return self


class ElementwiseTransformedLoader:
    """
    Element-Level Transformation Loader for Record-by-Record Processing

    The ElementwiseTransformedLoader class wraps an existing streaming loader to apply
    user-defined transformation functions to individual records within each batch.
    This enables fine-grained data processing where transformations need to be
    applied at the record level rather than batch level.

    This loader automatically handles conversion between Arrow tables and Python
    dictionaries, making it convenient for complex per-record transformations
    that are difficult to express as vectorized operations.

    Args:
        base_loader (StreamingDataLoader): The underlying streaming loader that
            provides the source data batches.
        transform_fn (Callable[[Dict], Dict]): Function that takes a record
            (as dictionary) and returns a transformed record.

    Key Features:
    - Record-level transformation with automatic format conversion
    - Support for complex transformations that require per-record logic
    - Automatic Arrow table to dictionary conversion and back
    - Chainable with other transformation and filtering operations
    - Memory-efficient processing with batch reconstruction

    Attributes:
        base_loader (StreamingDataLoader): Reference to the source data loader
        transform_fn (Callable): The transformation function to apply per record

    Public Methods:
        __iter__() -> Iterator[pyarrow.Table]:
            Create iterator that applies transformation to each record in each batch.
        iter_batches() -> Iterator[pyarrow.Table]:
            Iterate over batches with transformed records.

    Usage Example:
        # Create base loader
        base_loader = JSONStreamingLoader("records.jsonl")
        
        # Define per-record transformation
        def normalize_record(record):
            # Complex per-record transformation
            normalized = {
                "id": record["id"],
                "text": record["text"].lower().strip(),
                "category": categorize_text(record["text"]),
                "timestamp": parse_timestamp(record["created_at"])
            }
            return normalized
        
        # Create element-wise transformed loader
        transformed_loader = ElementwiseTransformedLoader(
            base_loader, 
            normalize_record
        )
        
        # Process transformed records
        for batch in transformed_loader:
            print(f"Processed batch with {len(batch)} normalized records")
            index_records(batch)

    Performance Note:
        Element-wise transformations are generally slower than batch-level
        transformations due to the overhead of converting between formats.
        Use batch-level transformations when possible for better performance.

    Raises:
        ImportError: If PyArrow is not available for table conversions
    """

    def __init__(self, base_loader, transform_fn):
        """
        Initialize elementwise transformed loader with record-level transformation.

        Args:
            base_loader (StreamingDataLoader): The underlying streaming loader
                that provides source data batches. Must implement iteration protocol.
            transform_fn (Callable[[Dict], Dict]): Function that takes a record
                as a dictionary and returns a transformed record dictionary.
                Should preserve or modify the record structure as needed.

        Attributes initialized:
            base_loader (StreamingDataLoader): Reference to the source data loader
            transform_fn (Callable): Stored transformation function for record processing
        """
        self.base_loader = base_loader
        self.transform_fn = transform_fn

    def __iter__(self):
        """
        Create an iterator that applies element-level transformations.

        Processes each batch by converting it to individual records, applying
        the transformation function to each record, and reconstructing the
        batch as a PyArrow table. This approach enables complex per-record
        logic that cannot be efficiently vectorized.

        Yields:
            pyarrow.Table: Batches containing transformed records. Each record
                has been processed individually by the transform function and
                then reconstructed into a batch format for consistency with
                the streaming interface.

        Raises:
            ImportError: If PyArrow is not available for table conversion.

        Example:
            >>> def enrich_record(record):
            ...     record["text_length"] = len(record["text"])
            ...     record["is_long"] = record["text_length"] > 100
            ...     record["processed_at"] = datetime.utcnow().isoformat()
            ...     return record
            >>> 
            >>> loader = ElementwiseTransformedLoader(base_loader, enrich_record)
            >>> for batch in loader:
            ...     # Process enriched records
            ...     long_texts = batch.filter(pc.equal(batch["is_long"], True))

        Performance Note:
            Element-level transformations are slower than batch-level operations
            due to Python overhead and lack of vectorization. Use only when
            the transformation logic cannot be expressed efficiently with
            vectorized operations.
        """
        if not HAVE_ARROW:
            raise ImportError("PyArrow is required for this operation")

        for batch in self.base_loader:
            # Convert batch to records
            records = batch.to_pylist()

            # Apply transformation
            transformed_records = [self.transform_fn(record) for record in records]

            # Convert back to Arrow
            yield pa.Table.from_pylist(transformed_records)

    def iter_batches(self):
        """
        Iterate over transformed batches.

        Yields:
            Transformed batches
        """
        return self


class FilteredLoader:
    """
    Batch-Level Filtering Loader for Streaming Data Processing

    The FilteredLoader class wraps an existing streaming loader to apply
    user-defined filter predicates to entire batches during iteration. This
    enables efficient data filtering pipelines where entire batches can be
    accepted or rejected based on batch-level criteria.

    This loader is optimized for scenarios where filtering decisions can be
    made at the batch level, such as filtering batches based on metadata,
    size constraints, or aggregate properties.

    Args:
        base_loader (StreamingDataLoader): The underlying streaming loader that
            provides the source data batches.
        filter_fn (Callable[[pyarrow.Table], bool]): Predicate function that
            takes a batch and returns True to include or False to exclude.

    Key Features:
    - Efficient batch-level filtering with lazy evaluation
    - Memory-efficient processing by skipping filtered batches entirely
    - Support for complex batch-level filtering criteria
    - Chainable with other transformation and filtering operations
    - Preserves underlying loader's performance characteristics

    Attributes:
        base_loader (StreamingDataLoader): Reference to the source data loader
        filter_fn (Callable): The filter predicate function

    Public Methods:
        __iter__() -> Iterator[Any]:
            Create iterator that yields only batches passing the filter.
        iter_batches() -> Iterator[Any]:
            Iterate over filtered batches (same as __iter__ for this class).

    Usage Example:
        # Create base loader
        base_loader = ParquetStreamingLoader("data.parquet")
        
        # Define batch filter function
        def filter_non_empty_batches(batch):
            # Only process batches with data
            return len(batch) > 0
        
        def filter_recent_data(batch):
            # Only process batches with recent timestamps
            import pyarrow.compute as pc
            if "timestamp" in batch.column_names:
                max_timestamp = pc.max(batch["timestamp"])
                return max_timestamp.as_py() > recent_threshold
            return True
        
        # Create filtered loader
        filtered_loader = FilteredLoader(base_loader, filter_recent_data)
        
        # Process only filtered batches
        for batch in filtered_loader:
            print(f"Processing recent batch with {len(batch)} records")
            analyze_recent_data(batch)
    """

    def __init__(self, base_loader, filter_fn):
        """
        Initialize filtered loader with base loader and filter predicate.

        Args:
            base_loader (StreamingDataLoader): The underlying streaming loader
                that provides source data batches. Must implement iteration protocol.
            filter_fn (Callable[[Any], bool]): Predicate function that takes a batch
                and returns True to include the batch or False to exclude it.
                Should handle the data format returned by the base loader.

        Attributes initialized:
            base_loader (StreamingDataLoader): Reference to the source data loader
            filter_fn (Callable): Stored filter predicate for batch evaluation
        """
        self.base_loader = base_loader
        self.filter_fn = filter_fn

    def __iter__(self):
        """
        Create an iterator that filters batches based on predicate function.

        Evaluates each batch from the base loader using the filter function
        and yields only batches that satisfy the predicate condition. This
        enables efficient data filtering at the batch level, allowing entire
        batches to be skipped when they don't meet criteria.

        Yields:
            Batch data: Only batches for which filter_fn returns True are yielded.
                The format matches the output of the base loader (typically
                pyarrow.Table objects).

        Example:
            >>> def filter_large_batches(batch):
            ...     return len(batch) >= 100  # Only process substantial batches
            >>> 
            >>> def filter_valid_data(batch):
            ...     import pyarrow.compute as pc
            ...     # Only process batches with no null values in key column
            ...     return pc.sum(pc.is_null(batch["id"])).as_py() == 0
            >>> 
            >>> filtered_loader = FilteredLoader(base_loader, filter_large_batches)
            >>> for batch in filtered_loader:
            ...     # Process only batches that meet size criteria
            ...     process_substantial_batch(batch)

        Performance Note:
            Batch-level filtering is very efficient as it can skip entire
            batches without processing individual records. This is particularly
            useful for time-based filtering, quality filtering, or sampling.
        """
        for batch in self.base_loader:
            if self.filter_fn(batch):
                yield batch

    def iter_batches(self):
        """
        Iterate over filtered batches.

        Yields:
            Filtered batches
        """
        return self


class ElementwiseFilteredLoader:
    """
    Element-Level Filtering Loader for Record-by-Record Processing

    The ElementwiseFilteredLoader class wraps an existing streaming loader to apply
    user-defined filter predicates to individual records within each batch. This
    enables fine-grained data filtering where decisions need to be made at the
    record level rather than batch level.

    This loader automatically handles conversion between Arrow tables and Python
    dictionaries, making it convenient for complex per-record filtering logic
    that is difficult to express as vectorized operations.

    Args:
        base_loader (StreamingDataLoader): The underlying streaming loader that
            provides the source data batches.
        filter_fn (Callable[[Dict], bool]): Predicate function that takes a record
            (as dictionary) and returns True to include or False to exclude.

    Key Features:
    - Record-level filtering with automatic format conversion
    - Support for complex filtering logic that requires per-record evaluation
    - Automatic Arrow table to dictionary conversion and back
    - Chainable with other transformation and filtering operations
    - Automatic handling of empty batches after filtering

    Attributes:
        base_loader (StreamingDataLoader): Reference to the source data loader
        filter_fn (Callable): The filter predicate function for records

    Public Methods:
        __iter__() -> Iterator[pyarrow.Table]:
            Create iterator that yields batches containing only filtered records.
        iter_batches() -> Iterator[pyarrow.Table]:
            Iterate over batches with filtered records.

    Usage Example:
        # Create base loader
        base_loader = JSONStreamingLoader("user_data.jsonl")
        
        # Define per-record filter
        def filter_active_users(record):
            # Complex per-record filtering logic
            return (
                record.get("active", False) and
                record.get("last_login_days", 999) < 30 and
                record.get("subscription_status") == "premium"
            )
        
        # Create element-wise filtered loader
        filtered_loader = ElementwiseFilteredLoader(
            base_loader,
            filter_active_users
        )
        
        # Process only filtered records
        for batch in filtered_loader:
            print(f"Processing {len(batch)} active premium users")
            send_promotional_emails(batch)

    Performance Note:
        Element-wise filtering is generally slower than batch-level filtering
        due to format conversion overhead. Use batch-level filtering when
        possible for better performance.

    Raises:
        ImportError: If PyArrow is not available for record format conversion
        ValueError: If filtered records have inconsistent schemas
    """

    def __init__(self, base_loader, filter_fn):
        """
        Initialize element-wise filtering loader for record-level filtering.

        Args:
            base_loader (StreamingDataLoader): The underlying streaming loader that
                provides source data batches. Must yield Arrow tables or compatible
                formats that can be converted to records.
            filter_fn (Callable[[Dict], bool]): Predicate function that takes a record
                as a dictionary and returns True to include or False to exclude the
                record.

        Attributes initialized:
            base_loader (StreamingDataLoader): Reference to the source streaming loader
            filter_fn (Callable): Stored filter predicate for record evaluation
        """
        self.base_loader = base_loader
        self.filter_fn = filter_fn

    def __iter__(self):
        """
        Create an iterator that filters individual elements within batches.

        Processes each batch by converting it to individual records, applying
        the filter function to each record, and reconstructing filtered batches.
        This enables complex per-record filtering logic that cannot be efficiently
        expressed as vectorized operations.

        Yields:
            pyarrow.Table: Batches containing only records that satisfy the
                filter predicate. Batches may be smaller than the original
                batch size if records are filtered out. Empty batches are
                automatically skipped.

        Raises:
            ImportError: If PyArrow is not available for table conversion.

        Example:
            >>> def filter_english_content(record):
            ...     return (record.get("language", "").lower() == "en" and
            ...             len(record.get("text", "")) > 50)
            >>> 
            >>> def filter_high_quality(record):
            ...     return (record.get("score", 0) >= 0.8 and
            ...             record.get("verified", False))
            >>> 
            >>> filtered_loader = ElementwiseFilteredLoader(
            ...     base_loader, filter_english_content
            ... )
            >>> for batch in filtered_loader:
            ...     # Process only English content with sufficient length
            ...     high_quality_texts = [r["text"] for r in batch.to_pylist()]

        Performance Note:
            Element-wise filtering is slower than batch-level filtering due to
            format conversion overhead and Python iteration. Consider using
            PyArrow compute functions for better performance when possible.

        Note:
            Records are converted to dictionaries for filtering, then back to
            Arrow format. This provides flexibility but has performance overhead.
        """
        if not HAVE_ARROW:
            raise ImportError("PyArrow is required for this operation")

        for batch in self.base_loader:
            # Convert batch to records
            records = batch.to_pylist()

            # Filter records
            filtered_records = [record for record in records if self.filter_fn(record)]

            # Skip empty batches
            if not filtered_records:
                continue

            # Convert back to Arrow
            yield pa.Table.from_pylist(filtered_records)

    def iter_batches(self):
        """
        Iterate over filtered batches.

        Yields:
            Filtered batches
        """
        return self


# Factory functions for creating streaming datasets

def load_parquet(
    parquet_path,
    columns=None,
    filters=None,
    batch_size=10000,
    prefetch_batches=2,
    cache_enabled=True,
    cache_size_mb=100,
    collect_stats=True,
    use_memory_map=True
):
    """
    Create a streaming dataset from Parquet files with advanced optimization features.

    This factory function provides a convenient way to create streaming datasets from
    Parquet files or partitioned datasets with comprehensive configuration options
    for performance optimization and resource management.

    Args:
        parquet_path (str): Path to Parquet file or partitioned dataset directory.
            Must contain valid Parquet data accessible to the current process.
        columns (Optional[List[str]], optional): Specific columns to load for
            projection. Reduces I/O and memory usage by reading only required
            columns. Defaults to None (load all columns).
        filters (Optional[List[Tuple]], optional): PyArrow-compatible filters for
            predicate pushdown optimization. Format: [("column", "op", value)].
            Supported operators: "=", "!=", "<", ">", "<=", ">=", "in", "not in".
            Defaults to None (no filtering).
        batch_size (int, optional): Number of records per streaming batch. Larger
            values improve throughput but increase memory usage. Must be positive.
            Defaults to 10000.
        prefetch_batches (int, optional): Number of batches to prefetch asynchronously
            for improved I/O performance. Must be non-negative. Defaults to 2.
        cache_enabled (bool, optional): Whether to enable intelligent caching of
            processed data segments. Improves performance for repeated access.
            Defaults to True.
        cache_size_mb (int, optional): Maximum cache size in megabytes when caching
            is enabled. Must be positive. Defaults to 100.
        collect_stats (bool, optional): Whether to collect detailed performance
            statistics during streaming operations. Minimal overhead when enabled.
            Defaults to True.
        use_memory_map (bool, optional): Whether to use memory mapping for single
            files. Improves performance for large files but requires sufficient
            virtual memory. Defaults to True.

    Returns:
        StreamingDataset: Configured streaming dataset with Parquet loader backend
            providing high-performance access to the specified data.

    Raises:
        ImportError: If PyArrow is not available for Parquet operations
        FileNotFoundError: If parquet_path does not exist or is inaccessible
        ValueError: If path exists but contains no valid Parquet files
        PermissionError: If insufficient permissions to read the specified path

    Usage Example:
        # Basic usage with single file
        dataset = load_parquet("data.parquet")
        
        # Advanced usage with partitioned dataset and optimization
        dataset = load_parquet(
            parquet_path="/data/partitioned_dataset/",
            columns=["timestamp", "value", "category"],
            filters=[("category", "in", ["A", "B"]), ("value", ">", 100)],
            batch_size=50000,
            prefetch_batches=3,
            cache_size_mb=500,
            use_memory_map=True
        )
        
        # Process with transformations
        for batch in dataset.iter_batches():
            processed = transform_batch(batch)
            save_results(processed)
    """
    loader = ParquetStreamingLoader(
        parquet_path=parquet_path,
        columns=columns,
        filters=filters,
        batch_size=batch_size,
        prefetch_batches=prefetch_batches,
        cache_enabled=cache_enabled,
        cache_size_mb=cache_size_mb,
        collect_stats=collect_stats,
        use_memory_map=use_memory_map
    )

    return StreamingDataset(loader)

def load_csv(
    csv_path,
    read_options=None,
    parse_options=None,
    convert_options=None,
    batch_size=10000,
    prefetch_batches=2,
    cache_enabled=True,
    cache_size_mb=100,
    collect_stats=True
):
    """
    Create a streaming dataset from CSV files with comprehensive parsing options.

    This factory function provides a convenient interface for creating streaming
    datasets from CSV files with full control over reading, parsing, and conversion
    options through PyArrow's CSV processing capabilities.

    Args:
        csv_path (str): Path to CSV file to load. Must be accessible and contain
            valid CSV data with consistent structure.
        read_options (Optional[pyarrow.csv.ReadOptions], optional): PyArrow read
            options controlling how the CSV file is read, including encoding,
            block size, and threading. Defaults to None (use PyArrow defaults).
        parse_options (Optional[pyarrow.csv.ParseOptions], optional): PyArrow parse
            options controlling CSV parsing behavior including delimiters, quote
            characters, and escape sequences. Defaults to None (use PyArrow defaults).
        convert_options (Optional[pyarrow.csv.ConvertOptions], optional): PyArrow
            conversion options controlling type inference and column handling.
            Defaults to None (use PyArrow defaults).
        batch_size (int, optional): Number of records per streaming batch. Larger
            values improve throughput but increase memory usage. Must be positive.
            Defaults to 10000.
        prefetch_batches (int, optional): Number of batches to prefetch asynchronously
            for improved I/O performance. Must be non-negative. Defaults to 2.
        cache_enabled (bool, optional): Whether to enable intelligent caching of
            processed data segments. Defaults to True.
        cache_size_mb (int, optional): Maximum cache size in megabytes when caching
            is enabled. Must be positive. Defaults to 100.
        collect_stats (bool, optional): Whether to collect detailed performance
            statistics during streaming operations. Defaults to True.

    Returns:
        StreamingDataset: Configured streaming dataset with CSV loader backend
            providing memory-efficient access to the CSV data.

    Raises:
        ImportError: If PyArrow is not available for CSV operations
        FileNotFoundError: If csv_path does not exist or is inaccessible
        ValueError: If file exists but is not valid CSV format
        PermissionError: If insufficient permissions to read the specified file

    Usage Example:
        # Basic CSV loading
        dataset = load_csv("data.csv")
        
        # Advanced CSV loading with custom options
        read_opts = pa.csv.ReadOptions(
            encoding="utf-8",
            block_size=1024*1024,
            use_threads=True
        )
        parse_opts = pa.csv.ParseOptions(
            delimiter="|",
            quote_char='"',
            escape_char="\\"
        )
        
        dataset = load_csv(
            csv_path="complex_data.csv",
            read_options=read_opts,
            parse_options=parse_opts,
            batch_size=25000,
            cache_size_mb=200
        )
        
        # Process streaming data
        for batch in dataset.iter_batches():
            cleaned_batch = clean_data(batch)
            store_batch(cleaned_batch)
    """
    loader = CSVStreamingLoader(
        csv_path=csv_path,
        read_options=read_options,
        parse_options=parse_options,
        convert_options=convert_options,
        batch_size=batch_size,
        prefetch_batches=prefetch_batches,
        cache_enabled=cache_enabled,
        cache_size_mb=cache_size_mb,
        collect_stats=collect_stats
    )

    return StreamingDataset(loader)

def load_json(
    json_path,
    read_options=None,
    parse_options=None,
    batch_size=10000,
    prefetch_batches=2,
    cache_enabled=True,
    cache_size_mb=100,
    collect_stats=True
):
    """
    Create a streaming dataset from newline-delimited JSON files.

    This factory function provides convenient access to JSON datasets using PyArrow's
    streaming JSON capabilities. The input file must be in newline-delimited JSON
    format (NDJSON) where each line contains a separate JSON object.

    Args:
        json_path (str): Path to newline-delimited JSON file. Each line must contain
            a valid JSON object with consistent schema across the file.
        read_options (Optional[pyarrow.json.ReadOptions], optional): PyArrow read
            options controlling file reading behavior including block size and
            threading configuration. Defaults to None (use PyArrow defaults).
        parse_options (Optional[pyarrow.json.ParseOptions], optional): PyArrow parse
            options controlling JSON parsing behavior and type inference.
            Defaults to None (use PyArrow defaults).
        batch_size (int, optional): Number of records per streaming batch. Larger
            values improve throughput but increase memory usage. Must be positive.
            Defaults to 10000.
        prefetch_batches (int, optional): Number of batches to prefetch asynchronously
            for improved I/O performance. Must be non-negative. Defaults to 2.
        cache_enabled (bool, optional): Whether to enable intelligent caching of
            processed data segments. Defaults to True.
        cache_size_mb (int, optional): Maximum cache size in megabytes when caching
            is enabled. Must be positive. Defaults to 100.
        collect_stats (bool, optional): Whether to collect detailed performance
            statistics during streaming operations. Defaults to True.

    Returns:
        StreamingDataset: Configured streaming dataset with JSON loader backend
            providing memory-efficient access to the JSON data.

    Raises:
        ImportError: If PyArrow is not available for JSON operations
        FileNotFoundError: If json_path does not exist or is inaccessible
        ValueError: If file exists but is not valid newline-delimited JSON
        PermissionError: If insufficient permissions to read the specified file

    Usage Example:
        # Basic JSON loading
        dataset = load_json("data.jsonl")
        
        # Advanced JSON loading with custom options
        read_opts = pa.json.ReadOptions(
            block_size=2*1024*1024,  # 2MB blocks
            use_threads=True
        )
        
        dataset = load_json(
            json_path="large_dataset.jsonl",
            read_options=read_opts,
            batch_size=15000,
            prefetch_batches=4
        )
        
        # Process streaming JSON data
        for batch in dataset.iter_batches():
            normalized_batch = normalize_json_batch(batch)
            index_documents(normalized_batch)
    """
    loader = JSONStreamingLoader(
        json_path=json_path,
        read_options=read_options,
        parse_options=parse_options,
        batch_size=batch_size,
        prefetch_batches=prefetch_batches,
        cache_enabled=cache_enabled,
        cache_size_mb=cache_size_mb,
        collect_stats=collect_stats
    )

    return StreamingDataset(loader)

def load_huggingface(
    dataset_name=None,
    dataset_config=None,
    dataset_split="train",
    dataset_object=None,
    columns=None,
    batch_size=10000,
    prefetch_batches=2,
    cache_enabled=True,
    cache_size_mb=100,
    collect_stats=True
):
    """
    Create a streaming dataset from HuggingFace datasets with efficient memory usage.

    This factory function provides convenient access to HuggingFace datasets using
    streaming mode to avoid loading entire datasets into memory. Supports both
    datasets from the HuggingFace Hub and local dataset objects.

    Args:
        dataset_name (Optional[str], optional): Name of dataset from HuggingFace Hub.
            Format: "username/dataset-name" or "dataset-name" for official datasets.
            Required if dataset_object is not provided.
        dataset_config (Optional[str], optional): Dataset configuration name for
            datasets with multiple configurations. Defaults to None (default config).
        dataset_split (str, optional): Dataset split to load ("train", "validation",
            "test", etc.). Must exist in the specified dataset. Defaults to "train".
        dataset_object (Optional[datasets.Dataset], optional): Pre-loaded HuggingFace
            dataset object to wrap. Alternative to loading from Hub. Must support
            streaming if not already in streaming mode.
        columns (Optional[List[str]], optional): Specific columns to select from
            the dataset. Enables column projection for reduced memory usage.
            Defaults to None (all columns).
        batch_size (int, optional): Number of records per streaming batch. Larger
            values improve throughput but increase memory usage. Must be positive.
            Defaults to 10000.
        prefetch_batches (int, optional): Number of batches to prefetch asynchronously
            for improved performance. Must be non-negative. Defaults to 2.
        cache_enabled (bool, optional): Whether to enable intelligent caching of
            processed data segments. Defaults to True.
        cache_size_mb (int, optional): Maximum cache size in megabytes when caching
            is enabled. Must be positive. Defaults to 100.
        collect_stats (bool, optional): Whether to collect detailed performance
            statistics during streaming operations. Defaults to True.

    Returns:
        StreamingDataset: Configured streaming dataset with HuggingFace loader backend
            providing memory-efficient access to the dataset.

    Raises:
        ImportError: If HuggingFace datasets library is not available
        ValueError: If neither dataset_name nor dataset_object is provided
        ConnectionError: If unable to download dataset from HuggingFace Hub
        DatasetNotFoundError: If specified dataset or split does not exist

    Usage Example:
        # Load from HuggingFace Hub
        dataset = load_huggingface(
            dataset_name="squad",
            dataset_split="train",
            columns=["question", "context", "answers"]
        )
        
        # Load with configuration and optimization
        dataset = load_huggingface(
            dataset_name="c4",
            dataset_config="en",
            dataset_split="train",
            batch_size=5000,
            prefetch_batches=3,
            cache_size_mb=1000
        )
        
        # Process streaming data
        for batch in dataset.iter_batches():
            processed_batch = preprocess_text(batch)
            train_model_batch(processed_batch)
        
        # Use existing dataset object
        existing_dataset = load_dataset("imdb", split="train", streaming=True)
        dataset = load_huggingface(dataset_object=existing_dataset)
    """
    loader = HuggingFaceStreamingLoader(
        dataset_name=dataset_name,
        dataset_config=dataset_config,
        dataset_split=dataset_split,
        dataset_object=dataset_object,
        columns=columns,
        batch_size=batch_size,
        prefetch_batches=prefetch_batches,
        cache_enabled=cache_enabled,
        cache_size_mb=cache_size_mb,
        collect_stats=collect_stats
    )

    return StreamingDataset(loader)

def create_memory_mapped_vectors(
    file_path,
    dimension,
    dtype=np.float32,
    mode='r+',
    initial_vectors=None
):
    """
    Create a memory-mapped vector dataset for efficient large-scale vector operations.

    This factory function creates a new memory-mapped vector dataset optimized for
    machine learning and similarity search applications requiring efficient access
    to large collections of high-dimensional vectors.

    Args:
        file_path (str): Path where the vector dataset file will be created or opened.
            Parent directories will be created if they don't exist. File will be
            created if it doesn't exist and mode allows writing.
        dimension (int): Number of dimensions per vector. Must be positive and
            consistent for all vectors in the dataset.
        dtype (numpy.dtype, optional): NumPy data type for vector elements.
            Common choices include np.float32 (memory efficient), np.float64
            (high precision), np.int32, etc. Defaults to np.float32.
        mode (str, optional): File access mode. 'r+' for read-write (default),
            'w+' for write with truncation, 'r' for read-only access.
            Defaults to 'r+'.
        initial_vectors (Optional[numpy.ndarray], optional): Initial vectors to
            populate the dataset. Shape must be (n_vectors, dimension) and dtype
            must match the specified dtype. Defaults to None (empty dataset).

    Returns:
        MemoryMappedVectorLoader: Configured memory-mapped vector loader ready
            for efficient vector operations and random access.

    Raises:
        ImportError: If NumPy is not available for memory mapping operations
        ValueError: If dimension is not positive or initial_vectors have wrong shape
        PermissionError: If insufficient permissions to create or write file
        OSError: If file system operations fail or insufficient disk space

    Usage Example:
        # Create new vector dataset with initial data
        vectors = np.random.random((100000, 512)).astype(np.float32)
        
        loader = create_memory_mapped_vectors(
            file_path="embeddings.bin",
            dimension=512,
            dtype=np.float32,
            initial_vectors=vectors
        )
        
        # Add more vectors
        new_vectors = compute_embeddings(new_documents)
        loader.append(new_vectors)
        
        # Efficient random access
        query_vector = loader[42]  # Get single vector
        batch_vectors = loader[1000:2000]  # Get slice
        
        print(f"Dataset contains {len(loader)} vectors")
        loader.close()
    """
    loader = MemoryMappedVectorLoader(
        file_path=file_path,
        dimension=dimension,
        dtype=dtype,
        mode=mode
    )

    # Add initial vectors if provided
    if initial_vectors is not None:
        loader.append(initial_vectors)

    return loader

def load_memory_mapped_vectors(
    file_path,
    dimension,
    dtype=np.float32,
    mode='r'
):
    """
    Load an existing memory-mapped vector dataset for efficient access.

    This factory function opens an existing memory-mapped vector dataset,
    providing efficient random access to large collections of vectors without
    loading the entire dataset into memory.

    Args:
        file_path (str): Path to existing vector dataset file. Must contain
            vectors stored consecutively in the specified format.
        dimension (int): Number of dimensions per vector. Must match the
            dimension used when the dataset was created.
        dtype (numpy.dtype, optional): NumPy data type of vector elements.
            Must match the dtype used when the dataset was created.
            Defaults to np.float32.
        mode (str, optional): File access mode. 'r' for read-only (safe for
            shared access), 'r+' for read-write operations. Defaults to 'r'.

    Returns:
        MemoryMappedVectorLoader: Configured memory-mapped vector loader providing
            efficient access to the existing vector dataset.

    Raises:
        ImportError: If NumPy is not available for memory mapping operations
        FileNotFoundError: If file_path does not exist or is inaccessible
        ValueError: If file size is inconsistent with specified dimension and dtype
        PermissionError: If insufficient permissions for specified access mode

    Usage Example:
        # Load existing vector dataset
        loader = load_memory_mapped_vectors(
            file_path="embeddings.bin",
            dimension=512,
            dtype=np.float32,
            mode='r'
        )
        
        print(f"Loaded dataset with {len(loader)} vectors")
        
        # Efficient similarity search
        query_vector = get_query_embedding()
        candidate_vectors = loader[search_indices]
        similarities = compute_cosine_similarity(query_vector, candidate_vectors)
        
        # Random access patterns
        random_sample = loader[np.random.choice(len(loader), 1000)]
        
        loader.close()
    """
    return MemoryMappedVectorLoader(
        file_path=file_path,
        dimension=dimension,
        dtype=dtype,
        mode=mode
    )
