# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/ipld/optimized_codec.py'

Files last updated: 1748635923.4313796

Stub file last updated: 2025-07-07 02:17:30

## BatchProcessor

```python
class BatchProcessor:
    """
    Process IPLD blocks in batches for high-throughput operations.

This class handles efficient batch operations on IPLD blocks, including:
- Encoding multiple blocks in parallel
- Decoding multiple blocks in parallel
- Stream processing of large datasets
- Memory-efficient handling of large data structures
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## CID

```python
class CID:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LRUCache

```python
class LRUCache:
    """
    LRU (Least Recently Used) cache for IPLD blocks.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## OptimizedDecoder

```python
class OptimizedDecoder:
    """
    High-performance IPLD decoder with batch processing capability.

Features:
- Batch decoding of multiple blocks
- Memory-efficient processing
- Parallel decoding using thread pool
- LRU caching of frequent decodings
- Performance monitoring
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## OptimizedEncoder

```python
class OptimizedEncoder:
    """
    High-performance IPLD encoder with batch processing capability.

Features:
- Batch encoding of multiple blocks
- Memory-efficient processing
- Parallel encoding using thread pool
- LRU caching of frequent encodings
- Performance monitoring
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PerformanceStats

```python
class PerformanceStats:
    """
    Collect and analyze performance statistics for IPLD operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self):
    """
    Initialize performance stats collection.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceStats

## __init__

```python
def __init__(self, max_size: int = 1000):
    """
    Initialize an LRU cache with specified maximum size.

Args:
    max_size: Maximum number of items to store in the cache
    """
```
* **Async:** False
* **Method:** True
* **Class:** LRUCache

## __init__

```python
def __init__(self, use_cache: bool = True, cache_size: int = 1000, max_workers: Optional[int] = None, collect_stats: bool = True):
    """
    Initialize an optimized IPLD encoder.

Args:
    use_cache: Whether to use caching for frequent encodings
    cache_size: Maximum size of the LRU cache
    max_workers: Maximum number of worker threads (None = CPU count)
    collect_stats: Whether to collect performance statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizedEncoder

## __init__

```python
def __init__(self, use_cache: bool = True, cache_size: int = 1000, max_workers: Optional[int] = None, collect_stats: bool = True):
    """
    Initialize an optimized IPLD decoder.

Args:
    use_cache: Whether to use caching for frequent decodings
    cache_size: Maximum size of the LRU cache
    max_workers: Maximum number of worker threads (None = CPU count)
    collect_stats: Whether to collect performance statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizedDecoder

## __init__

```python
def __init__(self, batch_size: int = 100, max_workers: Optional[int] = None, use_cache: bool = True, cache_size: int = 1000, collect_stats: bool = True):
    """
    Initialize a batch processor for IPLD operations.

Args:
    batch_size: Number of blocks to process in each batch
    max_workers: Maximum number of worker threads
    use_cache: Whether to use caching
    cache_size: Maximum size of the LRU cache
    collect_stats: Whether to collect performance statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## blocks_to_car

```python
def blocks_to_car(self, roots: List[str], blocks: Dict[str, bytes]) -> bytes:
    """
    Create CAR data from blocks.

Args:
    roots: List of root CIDs
    blocks: Dict mapping CIDs to block data

Returns:
    CAR file data
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## calculate_cid_v1

```python
def calculate_cid_v1(data: bytes) -> str:
    """
    Calculate CIDv1 for data (simplified version).

Args:
    data: Data to calculate CID for

Returns:
    CIDv1 string
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## car_to_blocks

```python
def car_to_blocks(self, car_data: bytes) -> Dict[str, bytes]:
    """
    Extract blocks from CAR data.

Args:
    car_data: CAR file data

Returns:
    Dict mapping CIDs to block data
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## clear

```python
def clear(self) -> None:
    """
    Clear all items from the cache.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LRUCache

## contains

```python
def contains(self, key: str) -> bool:
    """
    Check if key is in cache.

Args:
    key: Cache key

Returns:
    True if key is in cache, False otherwise
    """
```
* **Async:** False
* **Method:** True
* **Class:** LRUCache

## create_batch_processor

```python
def create_batch_processor(batch_size = 100, optimize_memory = True, collect_stats = True) -> BatchProcessor:
    """
    Create a batch processor with optimized settings.

Args:
    batch_size: Size of batches for processing
    optimize_memory: Whether to optimize for memory usage
    collect_stats: Whether to collect performance statistics

Returns:
    Configured BatchProcessor
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## decode

```python
@staticmethod
def decode(cid_str):
```
* **Async:** False
* **Method:** True
* **Class:** CID

## decode_batch

```python
def decode_batch(self, blocks: List[Tuple[bytes, Optional[str]]]) -> List[PBNode]:
    """
    Decode multiple IPLD blocks in parallel.

Args:
    blocks: List of (block_data, cid) tuples

Returns:
    List of decoded PBNodes
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizedDecoder

## decode_block

```python
def decode_block(self, block_data: bytes, cid: Optional[str] = None) -> PBNode:
    """
    Decode a single IPLD block to a DAG-PB node.

Args:
    block_data: Encoded block data
    cid: Optional CID of the block (used for caching)

Returns:
    Decoded PBNode
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizedDecoder

## decode_json

```python
def decode_json(self, block_data: bytes, cid: Optional[str] = None) -> Any:
    """
    Decode a block containing JSON data.

Args:
    block_data: Encoded block data
    cid: Optional CID of the block

Returns:
    Decoded JSON data
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizedDecoder

## decode_json_batch

```python
def decode_json_batch(self, blocks: List[Tuple[bytes, Optional[str]]]) -> List[Any]:
    """
    Decode multiple blocks containing JSON data.

Args:
    blocks: List of (block_data, cid) tuples

Returns:
    List of decoded JSON objects
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizedDecoder

## encode

```python
@staticmethod
def encode(cid_obj):
```
* **Async:** False
* **Method:** True
* **Class:** CID

## encode_batch

```python
def encode_batch(self, nodes: List[Union[PBNode, Dict]]) -> List[Tuple[bytes, str]]:
    """
    Encode multiple DAG-PB nodes in parallel.

Args:
    nodes: List of nodes to encode

Returns:
    List of (encoded_data, cid) tuples
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizedEncoder

## encode_json_batch

```python
def encode_json_batch(self, objects: List[Any]) -> List[Tuple[bytes, str]]:
    """
    Encode multiple JSON objects as IPLD blocks.

Args:
    objects: List of JSON-serializable objects

Returns:
    List of (encoded_data, cid) tuples
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizedEncoder

## encode_json_stream

```python
def encode_json_stream(self, objects_iter: Generator[Any, None, None], batch_size: int = 100) -> Generator[Tuple[bytes, str], None, None]:
    """
    Stream-encode JSON objects in batches.

Args:
    objects_iter: Iterator or generator yielding JSON-serializable objects
    batch_size: Number of objects to process in each batch

Yields:
    (encoded_data, cid) tuples for each encoded object
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizedEncoder

## encode_node

```python
def encode_node(self, node: Union[PBNode, Dict]) -> Tuple[bytes, str]:
    """
    Encode a single DAG-PB node and compute its CID.

Args:
    node: The node to encode (PBNode or dict with 'data' and 'links' keys)

Returns:
    Tuple of (encoded_data, cid)
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizedEncoder

## estimate_memory_usage

```python
def estimate_memory_usage(nodes: List[PBNode]) -> int:
    """
    Estimate memory usage for a list of nodes.

Args:
    nodes: List of nodes

Returns:
    Estimated memory usage in bytes
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get

```python
def get(self, key: str) -> Optional[Any]:
    """
    Get a value from the cache.

Args:
    key: Cache key

Returns:
    Cached value, or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** LRUCache

## get_stats

```python
def get_stats(self) -> Dict[str, Dict[str, Any]]:
    """
    Get performance statistics.

Returns:
    Dict with encoding and decoding statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## get_summary

```python
def get_summary(self) -> Dict[str, Any]:
    """
    Return a summary of performance statistics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceStats

## optimize_node_structure

```python
def optimize_node_structure(node: PBNode) -> PBNode:
    """
    Optimize the structure of a DAG-PB node for efficiency.

Optimizations include:
- Ordering links for binary search
- Deduplicating links
- Compacting data representation

Args:
    node: The node to optimize

Returns:
    Optimized node
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## process_car_file

```python
def process_car_file(self, car_path: str, process_func: Callable[[str, bytes], Tuple[str, bytes]]) -> Tuple[List[str], Dict[str, bytes]]:
    """
    Process blocks in a CAR file.

Args:
    car_path: Path to CAR file
    process_func: Function to process each block, taking (cid, data) and returning (new_cid, new_data)

Returns:
    Tuple of (roots, processed_blocks)
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## process_file

```python
def process_file(self, input_path: str, process_func: Callable, output_path: Optional[str] = None) -> List[Any]:
    """
    Process a file in batches.

Args:
    input_path: Path to input file
    process_func: Function to process each batch of data
    output_path: Optional path to write output

Returns:
    List of results from batch processing
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## put

```python
def put(self, key: str, value: Any) -> None:
    """
    Add or update a value in the cache.

Args:
    key: Cache key
    value: Value to cache
    """
```
* **Async:** False
* **Method:** True
* **Class:** LRUCache

## record_cache_access

```python
def record_cache_access(self, hit: bool):
    """
    Record a cache hit or miss.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceStats

## record_decode

```python
def record_decode(self, duration: float, size: int, batch_size: int = 1):
    """
    Record statistics for a decode operation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceStats

## record_encode

```python
def record_encode(self, duration: float, size: int, batch_size: int = 1):
    """
    Record statistics for an encode operation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceStats

## size

```python
def size(self) -> int:
    """
    Get the current size of the cache.

Returns:
    Number of items in the cache
    """
```
* **Async:** False
* **Method:** True
* **Class:** LRUCache
