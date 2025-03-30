"""
IPLD Optimized Encoder/Decoder

This module provides optimized implementations for encoding and decoding IPLD data structures,
focusing on high-throughput processing of large datasets. It includes:

1. Batch processing of IPLD blocks
2. Memory-efficient encoding/decoding
3. Caching strategies for frequently accessed structures
4. Parallel processing capabilities
5. Performance monitoring
"""

import io
import json
import time
import struct
import hashlib
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple, Union, Any, Set, Generator, ByteString, Callable

try:
    from ipld_dag_pb import encode as dag_pb_encode, decode as dag_pb_decode, PBNode, PBLink
    HAVE_IPLD_DAG_PB = True
except ImportError:
    from ipfs_datasets_py.ipld.dag_pb import encode as dag_pb_encode, decode as dag_pb_decode, PBNode, PBLink
    HAVE_IPLD_DAG_PB = False

try:
    import ipld_car
    HAVE_IPLD_CAR = True
except ImportError:
    HAVE_IPLD_CAR = False

try:
    from multiformats import CID
    HAVE_MULTIFORMATS = True
except ImportError:
    HAVE_MULTIFORMATS = False
    # Simple CID class for compatibility
    class CID:
        @staticmethod
        def decode(cid_str):
            return cid_str
        
        @staticmethod
        def encode(cid_obj):
            return str(cid_obj)


class PerformanceStats:
    """Collect and analyze performance statistics for IPLD operations."""
    
    def __init__(self):
        """Initialize performance stats collection."""
        self.encode_times = []
        self.decode_times = []
        self.batch_sizes = []
        self.total_bytes_processed = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.start_time = time.time()
    
    def record_encode(self, duration: float, size: int, batch_size: int = 1):
        """Record statistics for an encode operation."""
        self.encode_times.append(duration)
        self.total_bytes_processed += size
        self.batch_sizes.append(batch_size)
    
    def record_decode(self, duration: float, size: int, batch_size: int = 1):
        """Record statistics for a decode operation."""
        self.decode_times.append(duration)
        self.total_bytes_processed += size
        self.batch_sizes.append(batch_size)
    
    def record_cache_access(self, hit: bool):
        """Record a cache hit or miss."""
        if hit:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
    
    def get_summary(self) -> Dict[str, Any]:
        """Return a summary of performance statistics."""
        elapsed = time.time() - self.start_time
        encode_count = len(self.encode_times)
        decode_count = len(self.decode_times)
        
        avg_encode_time = sum(self.encode_times) / encode_count if encode_count > 0 else 0
        avg_decode_time = sum(self.decode_times) / decode_count if decode_count > 0 else 0
        
        throughput = self.total_bytes_processed / elapsed if elapsed > 0 else 0
        cache_hit_rate = self.cache_hits / (self.cache_hits + self.cache_misses) if (self.cache_hits + self.cache_misses) > 0 else 0
        
        return {
            "total_operations": encode_count + decode_count,
            "encode_operations": encode_count,
            "decode_operations": decode_count,
            "avg_encode_time_ms": avg_encode_time * 1000,
            "avg_decode_time_ms": avg_decode_time * 1000,
            "throughput_mb_per_sec": throughput / (1024 * 1024),
            "total_bytes_processed": self.total_bytes_processed,
            "cache_hit_rate": cache_hit_rate,
            "elapsed_time_sec": elapsed
        }


class LRUCache:
    """LRU (Least Recently Used) cache for IPLD blocks."""
    
    def __init__(self, max_size: int = 1000):
        """
        Initialize an LRU cache with specified maximum size.
        
        Args:
            max_size: Maximum number of items to store in the cache
        """
        self.max_size = max_size
        self._cache: Dict[str, Any] = {}
        self._access_order: List[str] = []
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get a value from the cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value, or None if not found
        """
        if key in self._cache:
            # Update access order
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]
        return None
    
    def put(self, key: str, value: Any) -> None:
        """
        Add or update a value in the cache.
        
        Args:
            key: Cache key
            value: Value to cache
        """
        if key in self._cache:
            # Update existing entry
            self._access_order.remove(key)
        elif len(self._cache) >= self.max_size:
            # Remove least recently used item
            oldest_key = self._access_order.pop(0)
            del self._cache[oldest_key]
        
        # Add new entry
        self._cache[key] = value
        self._access_order.append(key)
    
    def contains(self, key: str) -> bool:
        """
        Check if key is in cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if key is in cache, False otherwise
        """
        return key in self._cache
    
    def clear(self) -> None:
        """Clear all items from the cache."""
        self._cache.clear()
        self._access_order.clear()
    
    def size(self) -> int:
        """
        Get the current size of the cache.
        
        Returns:
            Number of items in the cache
        """
        return len(self._cache)


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
    
    def __init__(self, 
                use_cache: bool = True, 
                cache_size: int = 1000, 
                max_workers: Optional[int] = None,
                collect_stats: bool = True):
        """
        Initialize an optimized IPLD encoder.
        
        Args:
            use_cache: Whether to use caching for frequent encodings
            cache_size: Maximum size of the LRU cache
            max_workers: Maximum number of worker threads (None = CPU count)
            collect_stats: Whether to collect performance statistics
        """
        self.use_cache = use_cache
        self.cache = LRUCache(cache_size) if use_cache else None
        self.max_workers = max_workers or multiprocessing.cpu_count()
        self.collect_stats = collect_stats
        self.stats = PerformanceStats() if collect_stats else None
    
    def encode_node(self, node: Union[PBNode, Dict]) -> Tuple[bytes, str]:
        """
        Encode a single DAG-PB node and compute its CID.
        
        Args:
            node: The node to encode (PBNode or dict with 'data' and 'links' keys)
            
        Returns:
            Tuple of (encoded_data, cid)
        """
        start_time = time.time() if self.collect_stats else 0
        
        # Convert dict to PBNode if needed
        if isinstance(node, dict):
            pb_node = PBNode(
                data=node.get('data'),
                links=[PBLink(
                    name=link.get('name'),
                    cid=link.get('cid') or link.get('Hash'),
                    tsize=link.get('tsize') or link.get('Tsize')
                ) for link in node.get('links', [])]
            )
        else:
            pb_node = node
        
        # Generate cache key if using cache
        cache_key = None
        if self.use_cache:
            # Simple cache key based on the node data and link CIDs
            hasher = hashlib.sha256()
            if pb_node.data:
                hasher.update(pb_node.data)
            for link in pb_node.links:
                if isinstance(link.cid, str):
                    hasher.update(link.cid.encode())
                else:
                    hasher.update(str(link.cid).encode())
                if link.name:
                    hasher.update(link.name.encode())
            cache_key = hasher.hexdigest()
            
            # Check cache
            if self.cache and cache_key:
                cached = self.cache.get(cache_key)
                if cached:
                    if self.stats:
                        self.stats.record_cache_access(True)
                    return cached
                if self.stats:
                    self.stats.record_cache_access(False)
        
        # Encode the node
        encoded_data = dag_pb_encode(pb_node)
        
        # Calculate CID (simplified)
        hasher = hashlib.sha256()
        hasher.update(encoded_data)
        digest = hasher.digest()
        cid = f"bafyrei{digest.hex()[:32]}"
        
        # Cache the result
        if self.use_cache and self.cache and cache_key:
            self.cache.put(cache_key, (encoded_data, cid))
        
        # Record stats
        if self.collect_stats and self.stats:
            duration = time.time() - start_time
            self.stats.record_encode(duration, len(encoded_data))
        
        return encoded_data, cid
    
    def encode_batch(self, nodes: List[Union[PBNode, Dict]]) -> List[Tuple[bytes, str]]:
        """
        Encode multiple DAG-PB nodes in parallel.
        
        Args:
            nodes: List of nodes to encode
            
        Returns:
            List of (encoded_data, cid) tuples
        """
        start_time = time.time() if self.collect_stats else 0
        total_size = 0
        
        if len(nodes) == 1:
            # For single node, just use regular encoding
            result = [self.encode_node(nodes[0])]
            if self.collect_stats and self.stats:
                encoded_data = result[0][0]
                duration = time.time() - start_time
                self.stats.record_encode(duration, len(encoded_data), 1)
            return result
        
        # Process in parallel for multiple nodes
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(nodes))) as executor:
            results = list(executor.map(self.encode_node, nodes))
        
        # Record batch stats
        if self.collect_stats and self.stats:
            duration = time.time() - start_time
            for encoded_data, _ in results:
                total_size += len(encoded_data)
            self.stats.record_encode(duration, total_size, len(nodes))
        
        return results
    
    def encode_json_batch(self, objects: List[Any]) -> List[Tuple[bytes, str]]:
        """
        Encode multiple JSON objects as IPLD blocks.
        
        Args:
            objects: List of JSON-serializable objects
            
        Returns:
            List of (encoded_data, cid) tuples
        """
        # First convert all objects to JSON bytes
        json_bytes = []
        for obj in objects:
            json_str = json.dumps(obj)
            json_bytes.append(json_str.encode('utf-8'))
        
        # Create nodes with the JSON bytes as data
        nodes = [PBNode(data=data) for data in json_bytes]
        
        # Encode the nodes
        return self.encode_batch(nodes)
    
    def encode_json_stream(self, objects_iter: Generator[Any, None, None], 
                           batch_size: int = 100) -> Generator[Tuple[bytes, str], None, None]:
        """
        Stream-encode JSON objects in batches.
        
        Args:
            objects_iter: Iterator or generator yielding JSON-serializable objects
            batch_size: Number of objects to process in each batch
            
        Yields:
            (encoded_data, cid) tuples for each encoded object
        """
        batch = []
        
        for obj in objects_iter:
            batch.append(obj)
            
            if len(batch) >= batch_size:
                # Process the current batch
                results = self.encode_json_batch(batch)
                for result in results:
                    yield result
                batch = []
        
        # Process any remaining items
        if batch:
            results = self.encode_json_batch(batch)
            for result in results:
                yield result


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
    
    def __init__(self,
                use_cache: bool = True,
                cache_size: int = 1000,
                max_workers: Optional[int] = None,
                collect_stats: bool = True):
        """
        Initialize an optimized IPLD decoder.
        
        Args:
            use_cache: Whether to use caching for frequent decodings
            cache_size: Maximum size of the LRU cache
            max_workers: Maximum number of worker threads (None = CPU count)
            collect_stats: Whether to collect performance statistics
        """
        self.use_cache = use_cache
        self.cache = LRUCache(cache_size) if use_cache else None
        self.max_workers = max_workers or multiprocessing.cpu_count()
        self.collect_stats = collect_stats
        self.stats = PerformanceStats() if collect_stats else None
    
    def decode_block(self, block_data: bytes, cid: Optional[str] = None) -> PBNode:
        """
        Decode a single IPLD block to a DAG-PB node.
        
        Args:
            block_data: Encoded block data
            cid: Optional CID of the block (used for caching)
            
        Returns:
            Decoded PBNode
        """
        start_time = time.time() if self.collect_stats else 0
        
        # Use CID as cache key if provided, otherwise hash the data
        cache_key = None
        if self.use_cache:
            if cid:
                cache_key = cid
            else:
                hasher = hashlib.sha256()
                hasher.update(block_data)
                cache_key = hasher.hexdigest()
            
            # Check cache
            if self.cache and cache_key:
                cached = self.cache.get(cache_key)
                if cached:
                    if self.stats:
                        self.stats.record_cache_access(True)
                    return cached
                if self.stats:
                    self.stats.record_cache_access(False)
        
        # Decode the block
        node = dag_pb_decode(block_data)
        
        # Cache the result
        if self.use_cache and self.cache and cache_key:
            self.cache.put(cache_key, node)
        
        # Record stats
        if self.collect_stats and self.stats:
            duration = time.time() - start_time
            self.stats.record_decode(duration, len(block_data))
        
        return node
    
    def decode_batch(self, blocks: List[Tuple[bytes, Optional[str]]]) -> List[PBNode]:
        """
        Decode multiple IPLD blocks in parallel.
        
        Args:
            blocks: List of (block_data, cid) tuples
            
        Returns:
            List of decoded PBNodes
        """
        start_time = time.time() if self.collect_stats else 0
        total_size = 0
        
        if len(blocks) == 1:
            # For single block, just use regular decoding
            block_data, cid = blocks[0]
            result = [self.decode_block(block_data, cid)]
            if self.collect_stats and self.stats:
                duration = time.time() - start_time
                self.stats.record_decode(duration, len(block_data), 1)
            return result
        
        # Process in parallel for multiple blocks
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(blocks))) as executor:
            futures = [executor.submit(self.decode_block, data, cid) for data, cid in blocks]
            results = [future.result() for future in futures]
        
        # Record batch stats
        if self.collect_stats and self.stats:
            duration = time.time() - start_time
            for data, _ in blocks:
                total_size += len(data)
            self.stats.record_decode(duration, total_size, len(blocks))
        
        return results
    
    def decode_json(self, block_data: bytes, cid: Optional[str] = None) -> Any:
        """
        Decode a block containing JSON data.
        
        Args:
            block_data: Encoded block data
            cid: Optional CID of the block
            
        Returns:
            Decoded JSON data
        """
        node = self.decode_block(block_data, cid)
        
        if not node.data:
            raise ValueError("Block does not contain data")
        
        try:
            return json.loads(node.data.decode('utf-8'))
        except json.JSONDecodeError as e:
            raise ValueError(f"Error decoding JSON: {e}")
    
    def decode_json_batch(self, blocks: List[Tuple[bytes, Optional[str]]]) -> List[Any]:
        """
        Decode multiple blocks containing JSON data.
        
        Args:
            blocks: List of (block_data, cid) tuples
            
        Returns:
            List of decoded JSON objects
        """
        # First decode all blocks to nodes
        nodes = self.decode_batch(blocks)
        
        # Then decode each node's data as JSON
        results = []
        for node in nodes:
            if not node.data:
                results.append(None)
                continue
            
            try:
                json_data = json.loads(node.data.decode('utf-8'))
                results.append(json_data)
            except json.JSONDecodeError:
                results.append(None)
        
        return results


class BatchProcessor:
    """
    Process IPLD blocks in batches for high-throughput operations.
    
    This class handles efficient batch operations on IPLD blocks, including:
    - Encoding multiple blocks in parallel
    - Decoding multiple blocks in parallel
    - Stream processing of large datasets
    - Memory-efficient handling of large data structures
    """
    
    def __init__(self, 
                batch_size: int = 100,
                max_workers: Optional[int] = None,
                use_cache: bool = True,
                cache_size: int = 1000,
                collect_stats: bool = True):
        """
        Initialize a batch processor for IPLD operations.
        
        Args:
            batch_size: Number of blocks to process in each batch
            max_workers: Maximum number of worker threads
            use_cache: Whether to use caching
            cache_size: Maximum size of the LRU cache
            collect_stats: Whether to collect performance statistics
        """
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.encoder = OptimizedEncoder(
            use_cache=use_cache,
            cache_size=cache_size,
            max_workers=max_workers,
            collect_stats=collect_stats
        )
        self.decoder = OptimizedDecoder(
            use_cache=use_cache,
            cache_size=cache_size,
            max_workers=max_workers,
            collect_stats=collect_stats
        )
    
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
        all_results = []
        
        # Open the file and process in chunks
        with open(input_path, 'rb') as f:
            while True:
                batch = []
                for _ in range(self.batch_size):
                    # Read a line if the file is text-based, or a chunk for binary
                    try:
                        line = f.readline()
                        if not line:
                            break
                        batch.append(line)
                    except Exception:
                        # For binary files, read fixed chunks
                        chunk = f.read(1024 * 1024)  # 1MB chunks
                        if not chunk:
                            break
                        batch.append(chunk)
                
                if not batch:
                    break
                
                # Process the batch
                results = process_func(batch)
                all_results.extend(results)
                
                # Write results to output file if specified
                if output_path:
                    with open(output_path, 'a') as out:
                        for result in results:
                            out.write(str(result) + '\n')
        
        return all_results
    
    def car_to_blocks(self, car_data: bytes) -> Dict[str, bytes]:
        """
        Extract blocks from CAR data.
        
        Args:
            car_data: CAR file data
            
        Returns:
            Dict mapping CIDs to block data
        """
        if not HAVE_IPLD_CAR:
            raise ImportError("ipld_car module is required for this operation")
        
        try:
            roots, blocks = ipld_car.decode(car_data)
            return blocks
        except Exception as e:
            raise ValueError(f"Error decoding CAR data: {e}")
    
    def blocks_to_car(self, roots: List[str], blocks: Dict[str, bytes]) -> bytes:
        """
        Create CAR data from blocks.
        
        Args:
            roots: List of root CIDs
            blocks: Dict mapping CIDs to block data
            
        Returns:
            CAR file data
        """
        if not HAVE_IPLD_CAR:
            raise ImportError("ipld_car module is required for this operation")
        
        try:
            # Convert blocks dict to list of (cid, data) tuples
            block_list = [(cid, data) for cid, data in blocks.items()]
            return ipld_car.encode(roots, block_list)
        except Exception as e:
            raise ValueError(f"Error encoding CAR data: {e}")
    
    def process_car_file(self, car_path: str, process_func: Callable[[str, bytes], Tuple[str, bytes]]) -> Tuple[List[str], Dict[str, bytes]]:
        """
        Process blocks in a CAR file.
        
        Args:
            car_path: Path to CAR file
            process_func: Function to process each block, taking (cid, data) and returning (new_cid, new_data)
            
        Returns:
            Tuple of (roots, processed_blocks)
        """
        if not HAVE_IPLD_CAR:
            raise ImportError("ipld_car module is required for this operation")
        
        # Read the CAR file
        with open(car_path, 'rb') as f:
            car_data = f.read()
        
        # Decode the CAR file
        roots, blocks = ipld_car.decode(car_data)
        
        # Process the blocks in batches
        processed_blocks = {}
        batch = []
        batch_cids = []
        
        for cid, data in blocks.items():
            batch.append(data)
            batch_cids.append(cid)
            
            if len(batch) >= self.batch_size:
                # Process the batch
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = [executor.submit(process_func, cid, data) for cid, data in zip(batch_cids, batch)]
                    results = [future.result() for future in futures]
                
                # Store the results
                for new_cid, new_data in results:
                    processed_blocks[new_cid] = new_data
                
                batch = []
                batch_cids = []
        
        # Process any remaining blocks
        if batch:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [executor.submit(process_func, cid, data) for cid, data in zip(batch_cids, batch)]
                results = [future.result() for future in futures]
            
            for new_cid, new_data in results:
                processed_blocks[new_cid] = new_data
        
        return roots, processed_blocks
    
    def get_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Get performance statistics.
        
        Returns:
            Dict with encoding and decoding statistics
        """
        return {
            "encoder": self.encoder.stats.get_summary() if self.encoder.stats else {},
            "decoder": self.decoder.stats.get_summary() if self.decoder.stats else {}
        }


# Utility functions

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
    # Sort links by name for faster lookup
    if node.links:
        links = sorted(node.links, key=lambda link: link.name if link.name else "")
    else:
        links = []
    
    # Deduplicate links
    unique_links = []
    seen_cids = set()
    for link in links:
        cid_key = str(link.cid)
        if cid_key not in seen_cids:
            seen_cids.add(cid_key)
            unique_links.append(link)
    
    # Optimize data if it's JSON
    data = node.data
    if data:
        try:
            # Check if it's JSON data and optimize it
            json_data = json.loads(data.decode('utf-8'))
            # Use more compact JSON encoding
            data = json.dumps(json_data, separators=(',', ':')).encode('utf-8')
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Not JSON data, leave as is
            pass
    
    return PBNode(data=data, links=unique_links)


def calculate_cid_v1(data: bytes) -> str:
    """
    Calculate CIDv1 for data (simplified version).
    
    Args:
        data: Data to calculate CID for
        
    Returns:
        CIDv1 string
    """
    # This is a simplified version; real CID calculation is more complex
    hasher = hashlib.sha256()
    hasher.update(data)
    digest = hasher.digest()
    return f"bafyrei{digest.hex()[:32]}"


def estimate_memory_usage(nodes: List[PBNode]) -> int:
    """
    Estimate memory usage for a list of nodes.
    
    Args:
        nodes: List of nodes
        
    Returns:
        Estimated memory usage in bytes
    """
    total_bytes = 0
    
    for node in nodes:
        # Base size for the node object
        node_size = 24  # Approximate Python object overhead
        
        # Size of data
        if node.data:
            node_size += len(node.data) + 32  # data + overhead
        
        # Size of links
        if node.links:
            link_overhead = 24  # Approximate overhead per link
            for link in node.links:
                link_size = link_overhead
                if link.name:
                    link_size += len(link.name) + 32  # name + overhead
                if link.cid:
                    link_size += len(str(link.cid)) + 32  # cid + overhead
                if link.tsize is not None:
                    link_size += 16  # int + overhead
                node_size += link_size
        
        total_bytes += node_size
    
    return total_bytes


# Factory function for creating optimized processor
def create_batch_processor(batch_size=100, optimize_memory=True, collect_stats=True) -> BatchProcessor:
    """
    Create a batch processor with optimized settings.
    
    Args:
        batch_size: Size of batches for processing
        optimize_memory: Whether to optimize for memory usage
        collect_stats: Whether to collect performance statistics
        
    Returns:
        Configured BatchProcessor
    """
    # Determine optimal batch size and workers based on CPU count and available memory
    if optimize_memory:
        # Use smaller batches and fewer workers to conserve memory
        cpu_count = multiprocessing.cpu_count()
        max_workers = max(1, cpu_count // 2)
        cache_size = 100
    else:
        # Use more resources for maximum performance
        cpu_count = multiprocessing.cpu_count()
        max_workers = cpu_count
        cache_size = 1000
    
    return BatchProcessor(
        batch_size=batch_size,
        max_workers=max_workers,
        use_cache=True,
        cache_size=cache_size,
        collect_stats=collect_stats
    )