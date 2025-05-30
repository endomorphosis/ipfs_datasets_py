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
    """Statistics collector for streaming operations."""

    def __init__(self):
        """Initialize statistics collector."""
        self.start_time = time.time()
        self.bytes_processed = 0
        self.records_processed = 0
        self.batches_processed = 0
        self.processing_times = []
        self.batch_sizes = []
        self.current_batch_start = None

    def start_batch(self):
        """Mark the start of a new batch."""
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
        Calculate throughput metrics.

        Returns:
            dict: Throughput statistics
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
        """Reset statistics."""
        self.start_time = time.time()
        self.bytes_processed = 0
        self.records_processed = 0
        self.batches_processed = 0
        self.processing_times = []
        self.batch_sizes = []
        self.current_batch_start = None


class StreamingCache:
    """Cache for streaming data operations."""

    def __init__(self, max_size_mb=100, ttl_seconds=300):
        """
        Initialize cache with size limit.

        Args:
            max_size_mb (int): Maximum cache size in megabytes
            ttl_seconds (int): Time-to-live for cache entries in seconds
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
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            The cached value, or None if not found
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
        Add value to cache.

        Args:
            key: Cache key
            value: Value to cache
            size_bytes (int, optional): Size of the value. If None, will use
                a default estimation based on the type.

        Returns:
            bool: True if the value was cached, False if it was too large
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
        Ensure there's enough space in the cache.

        Args:
            size_bytes (int): Size needed
        """
        # If we need more space, remove entries until we have enough
        while self.current_size_bytes + size_bytes > self.max_size_bytes and self.cache:
            # Find the oldest entry
            oldest_key = min(self.cache_times.items(), key=lambda x: x[1])[0]
            self._remove(oldest_key)

    def _remove(self, key):
        """
        Remove an entry from the cache.

        Args:
            key: Cache key to remove
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
        """Clear the cache."""
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
    """Thread-safe queue with prefetching for streaming operations."""

    def __init__(self, source_iter, max_prefetch=3, buffer_size=1):
        """
        Initialize prefetching queue.

        Args:
            source_iter: Source iterator
            max_prefetch (int): Maximum number of items to prefetch
            buffer_size (int): Number of items per prefetch batch
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
        """Worker function to prefetch items from the source iterator."""
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
        """Return self as iterator."""
        return self

    def __next__(self):
        """Get the next item."""
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
    Base class for streaming data loaders.

    Provides common functionality for different loader implementations.
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
        Initialize streaming data loader.

        Args:
            batch_size (int): Number of records per batch
            prefetch_batches (int): Number of batches to prefetch
            cache_enabled (bool): Whether to use caching
            cache_size_mb (int): Maximum cache size in megabytes
            collect_stats (bool): Whether to collect performance statistics
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
        """Start timing a new batch for statistics."""
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
    Streaming loader for Parquet files.

    Provides memory-efficient loading of large Parquet files.
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
        Initialize Parquet streaming loader.

        Args:
            parquet_path (str): Path to Parquet file or directory
            columns (List[str], optional): Columns to load
            filters (List[Tuple], optional): PyArrow filters to apply
            batch_size (int): Number of records per batch
            prefetch_batches (int): Number of batches to prefetch
            cache_enabled (bool): Whether to use caching
            cache_size_mb (int): Maximum cache size in megabytes
            collect_stats (bool): Whether to collect performance statistics
            use_memory_map (bool): Whether to use memory mapping for file access

        Raises:
            ImportError: If PyArrow is not available
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
        """Create an iterator over the dataset."""
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
        """Get the length of the dataset (number of records)."""
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
        Iterate over batches with optional prefetching.

        Yields:
            pyarrow.Table: Batch of records
        """
        if self.prefetch_batches > 1:
            return PrefetchingQueue(self, self.prefetch_batches)
        return self

    def to_arrow_table(self):
        """
        Convert the entire dataset to an Arrow table.

        This loads the entire dataset into memory, so use with caution
        for large datasets.

        Returns:
            pyarrow.Table: The loaded table

        Raises:
            MemoryError: If the dataset is too large to fit in memory
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
    Streaming loader for CSV files.

    Provides memory-efficient loading of large CSV files.
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
        Initialize CSV streaming loader.

        Args:
            csv_path (str): Path to CSV file
            read_options (pyarrow.csv.ReadOptions, optional): Options for reading CSV
            parse_options (pyarrow.csv.ParseOptions, optional): Options for parsing CSV
            convert_options (pyarrow.csv.ConvertOptions, optional): Options for converting CSV
            batch_size (int): Number of records per batch
            prefetch_batches (int): Number of batches to prefetch
            cache_enabled (bool): Whether to use caching
            cache_size_mb (int): Maximum cache size in megabytes
            collect_stats (bool): Whether to collect performance statistics

        Raises:
            ImportError: If PyArrow is not available
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
        """Create an iterator over the dataset."""
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
    Streaming loader for JSON files.

    Provides memory-efficient loading of large JSON files.
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
        Initialize JSON streaming loader.

        Args:
            json_path (str): Path to JSON file (must be newline-delimited JSON)
            read_options (pyarrow.json.ReadOptions, optional): Options for reading JSON
            parse_options (pyarrow.json.ParseOptions, optional): Options for parsing JSON
            batch_size (int): Number of records per batch
            prefetch_batches (int): Number of batches to prefetch
            cache_enabled (bool): Whether to use caching
            cache_size_mb (int): Maximum cache size in megabytes
            collect_stats (bool): Whether to collect performance statistics

        Raises:
            ImportError: If PyArrow is not available
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
        """Create an iterator over the dataset."""
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
    Streaming loader for HuggingFace datasets.

    Provides memory-efficient loading of large HuggingFace datasets.
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
        Initialize HuggingFace streaming loader.

        Args:
            dataset_name (str, optional): Name of the dataset to load
            dataset_config (str, optional): Dataset configuration
            dataset_split (str): Dataset split to load
            dataset_object (datasets.Dataset, optional): Existing dataset object
            columns (List[str], optional): Columns to load
            batch_size (int): Number of records per batch
            prefetch_batches (int): Number of batches to prefetch
            cache_enabled (bool): Whether to use caching
            cache_size_mb (int): Maximum cache size in megabytes
            collect_stats (bool): Whether to collect performance statistics

        Raises:
            ImportError: If HuggingFace datasets is not available
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
        """Create an iterator over the dataset."""
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
    Memory-mapped access for large vector datasets.

    This provides efficient random access to vector datasets that are
    larger than available RAM by using memory mapping.
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
        Initialize memory-mapped vector loader.

        Either file_path or existing_mmap must be provided.

        Args:
            file_path (str, optional): Path to binary file containing vectors
            dimension (int, optional): Vector dimension (required if file_path is given)
            dtype (numpy.dtype): Data type of vectors
            mode (str): Mode for memory mapping ('r' for read-only, 'r+' for read-write)
            offset (int): Offset in bytes from the start of the file
            existing_mmap (numpy.memmap, optional): Existing memory map to use

        Raises:
            ImportError: If NumPy is not available
            ValueError: If neither file_path nor existing_mmap is provided
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
        """Get the number of vectors."""
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
        Append vectors to the memory-mapped file.

        Args:
            vectors (numpy.ndarray): Vectors to append

        Raises:
            RuntimeError: If the memory map is read-only
            ValueError: If the vectors don't match the expected dimension
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
        """Close the memory map."""
        if self.memmap is not None:
            # Flush changes to disk
            self.memmap.flush()

            # Delete the memmap object
            del self.memmap
            self.memmap = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


class StreamingDataset:
    """
    High-level API for working with streaming datasets.

    This class provides a unified interface for different streaming loaders.
    """

    def __init__(self, loader):
        """
        Initialize streaming dataset.

        Args:
            loader: Any streaming loader
        """
        self.loader = loader

    def iter_batches(self, batch_processor=None):
        """
        Iterate over batches of data.

        Args:
            batch_processor (callable, optional): Function to process each batch

        Yields:
            The batches, possibly processed
        """
        for batch in self.loader.iter_batches():
            if batch_processor:
                yield batch_processor(batch)
            else:
                yield batch

    def map(self, function, batched=True):
        """
        Apply a function to each element or batch.

        Args:
            function (callable): Function to apply
            batched (bool): Whether to apply to batches (True) or individual elements (False)

        Returns:
            StreamingDataset: A new dataset with the applied function
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
        Filter elements or batches.

        Args:
            function (callable): Filter function
            batched (bool): Whether to apply to batches or individual elements

        Returns:
            StreamingDataset: A new dataset with filtered elements
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
        Get performance statistics.

        Returns:
            dict: Performance statistics
        """
        if hasattr(self.loader, 'get_stats'):
            return self.loader.get_stats()
        return {}


class TransformedLoader:
    """Loader that applies a transformation to each batch."""

    def __init__(self, base_loader, transform_fn):
        """
        Initialize transformed loader.

        Args:
            base_loader: The base loader
            transform_fn (callable): Transformation function
        """
        self.base_loader = base_loader
        self.transform_fn = transform_fn

    def __iter__(self):
        """Create an iterator that transforms batches."""
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
    """Loader that applies a transformation to each element."""

    def __init__(self, base_loader, transform_fn):
        """
        Initialize elementwise transformed loader.

        Args:
            base_loader: The base loader
            transform_fn (callable): Transformation function
        """
        self.base_loader = base_loader
        self.transform_fn = transform_fn

    def __iter__(self):
        """Create an iterator that transforms elements."""
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
    """Loader that filters batches."""

    def __init__(self, base_loader, filter_fn):
        """
        Initialize filtered loader.

        Args:
            base_loader: The base loader
            filter_fn (callable): Filter function
        """
        self.base_loader = base_loader
        self.filter_fn = filter_fn

    def __iter__(self):
        """Create an iterator that filters batches."""
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
    """Loader that filters elements."""

    def __init__(self, base_loader, filter_fn):
        """
        Initialize elementwise filtered loader.

        Args:
            base_loader: The base loader
            filter_fn (callable): Filter function
        """
        self.base_loader = base_loader
        self.filter_fn = filter_fn

    def __iter__(self):
        """Create an iterator that filters elements."""
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
    Load a Parquet file as a streaming dataset.

    Args:
        parquet_path (str): Path to Parquet file or directory
        columns (List[str], optional): Columns to load
        filters (List[Tuple], optional): PyArrow filters to apply
        batch_size (int): Number of records per batch
        prefetch_batches (int): Number of batches to prefetch
        cache_enabled (bool): Whether to use caching
        cache_size_mb (int): Maximum cache size in megabytes
        collect_stats (bool): Whether to collect performance statistics
        use_memory_map (bool): Whether to use memory mapping for file access

    Returns:
        StreamingDataset: The loaded dataset
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
    Load a CSV file as a streaming dataset.

    Args:
        csv_path (str): Path to CSV file
        read_options (pyarrow.csv.ReadOptions, optional): Options for reading CSV
        parse_options (pyarrow.csv.ParseOptions, optional): Options for parsing CSV
        convert_options (pyarrow.csv.ConvertOptions, optional): Options for converting CSV
        batch_size (int): Number of records per batch
        prefetch_batches (int): Number of batches to prefetch
        cache_enabled (bool): Whether to use caching
        cache_size_mb (int): Maximum cache size in megabytes
        collect_stats (bool): Whether to collect performance statistics

    Returns:
        StreamingDataset: The loaded dataset
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
    Load a JSON file as a streaming dataset.

    Args:
        json_path (str): Path to JSON file (must be newline-delimited JSON)
        read_options (pyarrow.json.ReadOptions, optional): Options for reading JSON
        parse_options (pyarrow.json.ParseOptions, optional): Options for parsing JSON
        batch_size (int): Number of records per batch
        prefetch_batches (int): Number of batches to prefetch
        cache_enabled (bool): Whether to use caching
        cache_size_mb (int): Maximum cache size in megabytes
        collect_stats (bool): Whether to collect performance statistics

    Returns:
        StreamingDataset: The loaded dataset
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
    Load a HuggingFace dataset as a streaming dataset.

    Args:
        dataset_name (str, optional): Name of the dataset to load
        dataset_config (str, optional): Dataset configuration
        dataset_split (str): Dataset split to load
        dataset_object (datasets.Dataset, optional): Existing dataset object
        columns (List[str], optional): Columns to load
        batch_size (int): Number of records per batch
        prefetch_batches (int): Number of batches to prefetch
        cache_enabled (bool): Whether to use caching
        cache_size_mb (int): Maximum cache size in megabytes
        collect_stats (bool): Whether to collect performance statistics

    Returns:
        StreamingDataset: The loaded dataset
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
    Create a memory-mapped vector dataset.

    Args:
        file_path (str): Path to the file to create or open
        dimension (int): Vector dimension
        dtype (numpy.dtype): Data type of vectors
        mode (str): Mode for memory mapping ('r+' for read-write, 'r' for read-only)
        initial_vectors (numpy.ndarray, optional): Initial vectors to write

    Returns:
        MemoryMappedVectorLoader: The memory-mapped vector dataset
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
    Load a memory-mapped vector dataset.

    Args:
        file_path (str): Path to the file to open
        dimension (int): Vector dimension
        dtype (numpy.dtype): Data type of vectors
        mode (str): Mode for memory mapping ('r' for read-only, 'r+' for read-write)

    Returns:
        MemoryMappedVectorLoader: The memory-mapped vector dataset
    """
    return MemoryMappedVectorLoader(
        file_path=file_path,
        dimension=dimension,
        dtype=dtype,
        mode=mode
    )
