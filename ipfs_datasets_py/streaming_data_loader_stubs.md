# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/streaming_data_loader.py'

Files last updated: 1748635923.4613795

Stub file last updated: 2025-07-07 02:11:02

## CSVStreamingLoader

```python
class CSVStreamingLoader(StreamingDataLoader):
    """
    Streaming loader for CSV files.

Provides memory-efficient loading of large CSV files.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ElementwiseFilteredLoader

```python
class ElementwiseFilteredLoader:
    """
    Loader that filters elements.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ElementwiseTransformedLoader

```python
class ElementwiseTransformedLoader:
    """
    Loader that applies a transformation to each element.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## FilteredLoader

```python
class FilteredLoader:
    """
    Loader that filters batches.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## HuggingFaceStreamingLoader

```python
class HuggingFaceStreamingLoader(StreamingDataLoader):
    """
    Streaming loader for HuggingFace datasets.

Provides memory-efficient loading of large HuggingFace datasets.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## JSONStreamingLoader

```python
class JSONStreamingLoader(StreamingDataLoader):
    """
    Streaming loader for JSON files.

Provides memory-efficient loading of large JSON files.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## MemoryMappedVectorLoader

```python
class MemoryMappedVectorLoader:
    """
    Memory-mapped access for large vector datasets.

This provides efficient random access to vector datasets that are
larger than available RAM by using memory mapping.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ParquetStreamingLoader

```python
class ParquetStreamingLoader(StreamingDataLoader):
    """
    Streaming loader for Parquet files.

Provides memory-efficient loading of large Parquet files.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PrefetchingQueue

```python
class PrefetchingQueue:
    """
    Thread-safe queue with prefetching for streaming operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## StreamingCache

```python
class StreamingCache:
    """
    Cache for streaming data operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## StreamingDataLoader

```python
class StreamingDataLoader:
    """
    Base class for streaming data loaders.

Provides common functionality for different loader implementations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## StreamingDataset

```python
class StreamingDataset:
    """
    High-level API for working with streaming datasets.

This class provides a unified interface for different streaming loaders.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## StreamingStats

```python
class StreamingStats:
    """
    Statistics collector for streaming operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TransformedLoader

```python
class TransformedLoader:
    """
    Loader that applies a transformation to each batch.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __enter__

```python
def __enter__(self):
    """
    Context manager entry.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MemoryMappedVectorLoader

## __exit__

```python
def __exit__(self, exc_type, exc_val, exc_tb):
    """
    Context manager exit.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MemoryMappedVectorLoader

## __getitem__

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** MemoryMappedVectorLoader

## __init__

```python
def __init__(self):
    """
    Initialize statistics collector.
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingStats

## __init__

```python
def __init__(self, max_size_mb = 100, ttl_seconds = 300):
    """
    Initialize cache with size limit.

Args:
    max_size_mb (int): Maximum cache size in megabytes
    ttl_seconds (int): Time-to-live for cache entries in seconds
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingCache

## __init__

```python
def __init__(self, source_iter, max_prefetch = 3, buffer_size = 1):
    """
    Initialize prefetching queue.

Args:
    source_iter: Source iterator
    max_prefetch (int): Maximum number of items to prefetch
    buffer_size (int): Number of items per prefetch batch
    """
```
* **Async:** False
* **Method:** True
* **Class:** PrefetchingQueue

## __init__

```python
def __init__(self, batch_size = 10000, prefetch_batches = 2, cache_enabled = True, cache_size_mb = 100, collect_stats = True):
    """
    Initialize streaming data loader.

Args:
    batch_size (int): Number of records per batch
    prefetch_batches (int): Number of batches to prefetch
    cache_enabled (bool): Whether to use caching
    cache_size_mb (int): Maximum cache size in megabytes
    collect_stats (bool): Whether to collect performance statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingDataLoader

## __init__

```python
def __init__(self, parquet_path, columns = None, filters = None, batch_size = 10000, prefetch_batches = 2, cache_enabled = True, cache_size_mb = 100, collect_stats = True, use_memory_map = True):
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
```
* **Async:** False
* **Method:** True
* **Class:** ParquetStreamingLoader

## __init__

```python
def __init__(self, csv_path, read_options = None, parse_options = None, convert_options = None, batch_size = 10000, prefetch_batches = 2, cache_enabled = True, cache_size_mb = 100, collect_stats = True):
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
```
* **Async:** False
* **Method:** True
* **Class:** CSVStreamingLoader

## __init__

```python
def __init__(self, json_path, read_options = None, parse_options = None, batch_size = 10000, prefetch_batches = 2, cache_enabled = True, cache_size_mb = 100, collect_stats = True):
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
```
* **Async:** False
* **Method:** True
* **Class:** JSONStreamingLoader

## __init__

```python
def __init__(self, dataset_name = None, dataset_config = None, dataset_split = "train", dataset_object = None, columns = None, batch_size = 10000, prefetch_batches = 2, cache_enabled = True, cache_size_mb = 100, collect_stats = True):
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
```
* **Async:** False
* **Method:** True
* **Class:** HuggingFaceStreamingLoader

## __init__

```python
def __init__(self, file_path = None, dimension = None, dtype = np.float32, mode = "r", offset = 0, existing_mmap = None):
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
```
* **Async:** False
* **Method:** True
* **Class:** MemoryMappedVectorLoader

## __init__

```python
def __init__(self, loader):
    """
    Initialize streaming dataset.

Args:
    loader: Any streaming loader
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingDataset

## __init__

```python
def __init__(self, base_loader, transform_fn):
    """
    Initialize transformed loader.

Args:
    base_loader: The base loader
    transform_fn (callable): Transformation function
    """
```
* **Async:** False
* **Method:** True
* **Class:** TransformedLoader

## __init__

```python
def __init__(self, base_loader, transform_fn):
    """
    Initialize elementwise transformed loader.

Args:
    base_loader: The base loader
    transform_fn (callable): Transformation function
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElementwiseTransformedLoader

## __init__

```python
def __init__(self, base_loader, filter_fn):
    """
    Initialize filtered loader.

Args:
    base_loader: The base loader
    filter_fn (callable): Filter function
    """
```
* **Async:** False
* **Method:** True
* **Class:** FilteredLoader

## __init__

```python
def __init__(self, base_loader, filter_fn):
    """
    Initialize elementwise filtered loader.

Args:
    base_loader: The base loader
    filter_fn (callable): Filter function
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElementwiseFilteredLoader

## __iter__

```python
def __iter__(self):
    """
    Return self as iterator.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PrefetchingQueue

## __iter__

```python
def __iter__(self):
    """
    Create an iterator over the dataset.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParquetStreamingLoader

## __iter__

```python
def __iter__(self):
    """
    Create an iterator over the dataset.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CSVStreamingLoader

## __iter__

```python
def __iter__(self):
    """
    Create an iterator over the dataset.
    """
```
* **Async:** False
* **Method:** True
* **Class:** JSONStreamingLoader

## __iter__

```python
def __iter__(self):
    """
    Create an iterator over the dataset.
    """
```
* **Async:** False
* **Method:** True
* **Class:** HuggingFaceStreamingLoader

## __iter__

```python
def __iter__(self):
    """
    Create an iterator that transforms batches.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TransformedLoader

## __iter__

```python
def __iter__(self):
    """
    Create an iterator that transforms elements.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElementwiseTransformedLoader

## __iter__

```python
def __iter__(self):
    """
    Create an iterator that filters batches.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FilteredLoader

## __iter__

```python
def __iter__(self):
    """
    Create an iterator that filters elements.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElementwiseFilteredLoader

## __len__

```python
def __len__(self):
    """
    Get the length of the dataset (number of records).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParquetStreamingLoader

## __len__

```python
def __len__(self):
    """
    Get the number of vectors.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MemoryMappedVectorLoader

## __next__

```python
def __next__(self):
    """
    Get the next item.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PrefetchingQueue

## _batch_to_arrow

```python
def _batch_to_arrow(self, batch):
    """
    Convert a batch of examples to an Arrow table.

Args:
    batch (List[Dict]): Batch of examples

Returns:
    pyarrow.Table: The batch as an Arrow table
    """
```
* **Async:** False
* **Method:** True
* **Class:** HuggingFaceStreamingLoader

## _cache_get

```python
def _cache_get(self, key):
    """
    Get a value from the cache.

Args:
    key: Cache key

Returns:
    The cached value, or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingDataLoader

## _cache_put

```python
def _cache_put(self, key, value, size_bytes = None):
    """
    Add a value to the cache.

Args:
    key: Cache key
    value: Value to cache
    size_bytes (int, optional): Size of the value

Returns:
    bool: True if the value was cached
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingDataLoader

## _end_batch_stats

```python
def _end_batch_stats(self, records, bytes_count = None):
    """
    End timing for a batch.

Args:
    records (int): Number of records in the batch
    bytes_count (int, optional): Size of the batch in bytes
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingDataLoader

## _ensure_space

```python
def _ensure_space(self, size_bytes):
    """
    Ensure there's enough space in the cache.

Args:
    size_bytes (int): Size needed
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingCache

## _prefetch_worker

```python
def _prefetch_worker(self):
    """
    Worker function to prefetch items from the source iterator.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PrefetchingQueue

## _remove

```python
def _remove(self, key):
    """
    Remove an entry from the cache.

Args:
    key: Cache key to remove
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingCache

## _start_batch_stats

```python
def _start_batch_stats(self):
    """
    Start timing a new batch for statistics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingDataLoader

## append

```python
def append(self, vectors):
    """
    Append vectors to the memory-mapped file.

Args:
    vectors (numpy.ndarray): Vectors to append

Raises:
    RuntimeError: If the memory map is read-only
    ValueError: If the vectors don't match the expected dimension
    """
```
* **Async:** False
* **Method:** True
* **Class:** MemoryMappedVectorLoader

## clear

```python
def clear(self):
    """
    Clear the cache.
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingCache

## close

```python
def close(self):
    """
    Close the memory map.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MemoryMappedVectorLoader

## create_memory_mapped_vectors

```python
def create_memory_mapped_vectors(file_path, dimension, dtype = np.float32, mode = "r+", initial_vectors = None):
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## end_batch

```python
def end_batch(self, records, bytes_count = None):
    """
    Mark the end of a batch.

Args:
    records (int): Number of records in the batch
    bytes_count (int, optional): Size of the batch in bytes
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingStats

## filter

```python
def filter(self, function, batched = True):
    """
    Filter elements or batches.

Args:
    function (callable): Filter function
    batched (bool): Whether to apply to batches or individual elements

Returns:
    StreamingDataset: A new dataset with filtered elements
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingDataset

## get

```python
def get(self, key):
    """
    Get value from cache.

Args:
    key: Cache key

Returns:
    The cached value, or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingCache

## get_features

```python
def get_features(self):
    """
    Get the features of the dataset.

Returns:
    datasets.Features: The dataset features
    """
```
* **Async:** False
* **Method:** True
* **Class:** HuggingFaceStreamingLoader

## get_metadata

```python
def get_metadata(self):
    """
    Get metadata from the Parquet file.

Returns:
    dict: Metadata from the Parquet file
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParquetStreamingLoader

## get_metadata

```python
def get_metadata(self):
    """
    Get metadata about the dataset.

Returns:
    dict: Dataset metadata
    """
```
* **Async:** False
* **Method:** True
* **Class:** HuggingFaceStreamingLoader

## get_schema

```python
def get_schema(self):
    """
    Get the schema of the dataset.

Returns:
    pyarrow.Schema: The dataset schema
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParquetStreamingLoader

## get_schema

```python
def get_schema(self):
    """
    Get the schema of the CSV file.

This reads the first batch to determine the schema.

Returns:
    pyarrow.Schema: The file schema
    """
```
* **Async:** False
* **Method:** True
* **Class:** CSVStreamingLoader

## get_schema

```python
def get_schema(self):
    """
    Get the schema of the JSON file.

This reads the first batch to determine the schema.

Returns:
    pyarrow.Schema: The file schema
    """
```
* **Async:** False
* **Method:** True
* **Class:** JSONStreamingLoader

## get_schema

```python
def get_schema(self):
    """
    Get the schema of the dataset.

Returns:
    pyarrow.Schema: The dataset schema
    """
```
* **Async:** False
* **Method:** True
* **Class:** HuggingFaceStreamingLoader

## get_stats

```python
def get_stats(self):
    """
    Get cache statistics.

Returns:
    dict: Cache statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingCache

## get_stats

```python
def get_stats(self):
    """
    Get performance statistics.

Returns:
    dict: Performance statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingDataLoader

## get_stats

```python
def get_stats(self):
    """
    Get performance statistics.

Returns:
    dict: Performance statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingDataset

## get_throughput

```python
def get_throughput(self):
    """
    Calculate throughput metrics.

Returns:
    dict: Throughput statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingStats

## iter_batches

```python
def iter_batches(self):
    """
    Iterate over batches with optional prefetching.

Yields:
    pyarrow.Table: Batch of records
    """
```
* **Async:** False
* **Method:** True
* **Class:** ParquetStreamingLoader

## iter_batches

```python
def iter_batches(self):
    """
    Iterate over batches with optional prefetching.

Yields:
    pyarrow.Table: Batch of records
    """
```
* **Async:** False
* **Method:** True
* **Class:** CSVStreamingLoader

## iter_batches

```python
def iter_batches(self):
    """
    Iterate over batches with optional prefetching.

Yields:
    pyarrow.Table: Batch of records
    """
```
* **Async:** False
* **Method:** True
* **Class:** JSONStreamingLoader

## iter_batches

```python
def iter_batches(self):
    """
    Iterate over batches with optional prefetching.

Yields:
    pyarrow.Table: Batch of records
    """
```
* **Async:** False
* **Method:** True
* **Class:** HuggingFaceStreamingLoader

## iter_batches

```python
def iter_batches(self, batch_processor = None):
    """
    Iterate over batches of data.

Args:
    batch_processor (callable, optional): Function to process each batch

Yields:
    The batches, possibly processed
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingDataset

## iter_batches

```python
def iter_batches(self):
    """
    Iterate over transformed batches.

Yields:
    Transformed batches
    """
```
* **Async:** False
* **Method:** True
* **Class:** TransformedLoader

## iter_batches

```python
def iter_batches(self):
    """
    Iterate over transformed batches.

Yields:
    Transformed batches
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElementwiseTransformedLoader

## iter_batches

```python
def iter_batches(self):
    """
    Iterate over filtered batches.

Yields:
    Filtered batches
    """
```
* **Async:** False
* **Method:** True
* **Class:** FilteredLoader

## iter_batches

```python
def iter_batches(self):
    """
    Iterate over filtered batches.

Yields:
    Filtered batches
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElementwiseFilteredLoader

## load_csv

```python
def load_csv(csv_path, read_options = None, parse_options = None, convert_options = None, batch_size = 10000, prefetch_batches = 2, cache_enabled = True, cache_size_mb = 100, collect_stats = True):
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## load_huggingface

```python
def load_huggingface(dataset_name = None, dataset_config = None, dataset_split = "train", dataset_object = None, columns = None, batch_size = 10000, prefetch_batches = 2, cache_enabled = True, cache_size_mb = 100, collect_stats = True):
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## load_json

```python
def load_json(json_path, read_options = None, parse_options = None, batch_size = 10000, prefetch_batches = 2, cache_enabled = True, cache_size_mb = 100, collect_stats = True):
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## load_memory_mapped_vectors

```python
def load_memory_mapped_vectors(file_path, dimension, dtype = np.float32, mode = "r"):
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## load_parquet

```python
def load_parquet(parquet_path, columns = None, filters = None, batch_size = 10000, prefetch_batches = 2, cache_enabled = True, cache_size_mb = 100, collect_stats = True, use_memory_map = True):
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## map

```python
def map(self, function, batched = True):
    """
    Apply a function to each element or batch.

Args:
    function (callable): Function to apply
    batched (bool): Whether to apply to batches (True) or individual elements (False)

Returns:
    StreamingDataset: A new dataset with the applied function
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingDataset

## put

```python
def put(self, key, value, size_bytes = None):
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
```
* **Async:** False
* **Method:** True
* **Class:** StreamingCache

## reset

```python
def reset(self):
    """
    Reset statistics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingStats

## start_batch

```python
def start_batch(self):
    """
    Mark the start of a new batch.
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingStats

## to_arrow_table

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** ParquetStreamingLoader

## to_arrow_table

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** CSVStreamingLoader

## to_arrow_table

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** JSONStreamingLoader

## to_arrow_table

```python
def to_arrow_table(self):
    """
    Convert the entire dataset to an Arrow table.

Returns:
    pyarrow.Table: The dataset as an Arrow table
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingDataset

## to_pandas

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** ParquetStreamingLoader

## to_pandas

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** CSVStreamingLoader

## to_pandas

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** JSONStreamingLoader

## to_pandas

```python
def to_pandas(self):
    """
    Convert the entire dataset to a pandas DataFrame.

Returns:
    pandas.DataFrame: The dataset as a DataFrame
    """
```
* **Async:** False
* **Method:** True
* **Class:** StreamingDataset
