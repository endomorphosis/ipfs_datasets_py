# Performance Optimization Features

This document describes the performance optimization features implemented in the `ipfs_datasets_py` library for handling large datasets efficiently.

## Overview

The performance optimization features include:

1. **Streaming Data Loading**: Memory-efficient processing of large datasets
2. **Memory-Mapped Vector Storage**: Efficient access to vector datasets larger than RAM
3. **IPLD Optimization**: High-throughput processing of IPLD structures
4. **Query Performance Improvements**: Statistics and indexing for faster queries

## Streaming Data Loading

### Core Components

The streaming data loading system consists of several key components:

#### Base Classes

- **StreamingDataLoader**: Base class for all streaming loaders
- **StreamingDataset**: High-level API for working with streaming datasets
- **StreamingStats**: Statistics collector for streaming operations
- **StreamingCache**: Cache for streaming data operations
- **PrefetchingQueue**: Thread-safe queue with prefetching

#### Format-Specific Loaders

- **ParquetStreamingLoader**: For Parquet files and directories
- **CSVStreamingLoader**: For CSV files
- **JSONStreamingLoader**: For JSON files (newline-delimited)
- **HuggingFaceStreamingLoader**: For HuggingFace datasets

### Memory-Mapped Vector Storage

The `MemoryMappedVectorLoader` provides efficient access to large vector datasets:

- Uses memory mapping to avoid loading the entire dataset into RAM
- Supports random access to vectors
- Allows appending new vectors to existing files
- Works with very large vector datasets (terabytes)

### Usage Examples

#### Loading and Processing a Large Parquet File

```python
from ipfs_datasets_py.streaming_data_loader import load_parquet

# Load a large Parquet file with streaming
dataset = load_parquet(
    parquet_path="large_dataset.parquet",
    batch_size=10000,  # Process 10,000 records at a time
    prefetch_batches=2  # Prefetch the next 2 batches
)

# Process data in batches
for batch in dataset.iter_batches():
    # Process each batch without loading the entire dataset
    process_batch(batch)

# Transform data on-the-fly
transformed = dataset.map(lambda batch: transform_batch(batch))

# Filter data on-the-fly
filtered = dataset.filter(lambda batch: some_condition(batch))

# Get performance statistics
stats = dataset.get_stats()
print(f"Throughput: {stats['throughput']['records_per_second']} records/second")
```

#### Working with Memory-Mapped Vectors

```python
from ipfs_datasets_py.streaming_data_loader import (
    create_memory_mapped_vectors,
    load_memory_mapped_vectors
)
import numpy as np

# Create and populate memory-mapped vectors
with create_memory_mapped_vectors(
    file_path="embeddings.bin",
    dimension=768,
    mode='w+'
) as vectors:
    # Add vectors in batches
    batch = np.random.rand(1000, 768).astype(np.float32)
    vectors.append(batch)
    
    # Add more batches
    for i in range(10):
        batch = np.random.rand(1000, 768).astype(np.float32)
        vectors.append(batch)

# Memory-mapped access to vectors
vectors = load_memory_mapped_vectors(
    file_path="embeddings.bin",
    dimension=768,
    mode='r'
)

# Random access
vector = vectors[1000]  # Get a specific vector
batch = vectors[5000:5100]  # Get a batch of vectors

# Process vectors in batches
batch_size = 10000
for i in range(0, len(vectors), batch_size):
    end_idx = min(i + batch_size, len(vectors))
    batch = vectors[i:end_idx]
    # Process batch
    process_vectors(batch)
```

## Performance Considerations

### Batch Size Tuning

The batch size significantly impacts performance:

- **Too small**: Overhead from processing many small batches
- **Too large**: High memory usage and potential spikes
- **Optimal range**: Typically 5,000 to 50,000 records, depending on:
  - Record size
  - Available memory
  - Processing complexity

### Prefetching

Prefetching loads the next batch(s) while processing the current batch:

- Reduces wait time between batches
- Improves CPU utilization
- Can be adjusted based on:
  - I/O speed
  - Processing complexity
  - Available memory

### Caching

The built-in caching system:

- Avoids redundant reads for frequently accessed data
- Uses a least-recently-used (LRU) eviction policy
- Can be tuned with:
  - Maximum cache size
  - Time-to-live (TTL) for entries

### Memory-Mapped Access Strategies

For optimal memory-mapped vector operations:

- **Sequential access**: Most efficient access pattern
- **Block access**: Group random access into blocks when possible
- **Balanced batch size**: Match to CPU cache lines for optimal performance
- **Careful with writes**: Write operations might cause copy-on-write overhead

## Integration with Other Components

### IPFS Integration

The streaming system works seamlessly with IPFS:

```python
from ipfs_datasets_py.streaming_data_loader import load_parquet
from ipfs_datasets_py.car_conversion import DataInterchangeUtils

# Stream a Parquet file and convert to CAR in batches
parquet_dataset = load_parquet("large_dataset.parquet", batch_size=10000)
converter = DataInterchangeUtils()

# Stream from Parquet to CAR
converter.stream_parquet_to_car(
    parquet_path="large_dataset.parquet",
    car_path="large_dataset.car",
    batch_size=10000
)

# Stream from CAR to Parquet
converter.stream_car_to_parquet(
    car_path="large_dataset.car",
    parquet_path="reconstructed.parquet",
    batch_size=10000
)
```

### Vector Storage Integration

The memory-mapped vectors integrate with vector indexes:

```python
from ipfs_datasets_py.streaming_data_loader import load_memory_mapped_vectors
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex

# Load vectors from memory-mapped file
vectors = load_memory_mapped_vectors("embeddings.bin", dimension=768)

# Create an index
index = IPFSKnnIndex(dimension=768)

# Add vectors in batches
batch_size = 10000
for i in range(0, len(vectors), batch_size):
    end_idx = min(i + batch_size, len(vectors))
    batch = vectors[i:end_idx]
    # Create metadata for this batch
    metadata = [{"id": f"vec-{j}", "index": j} for j in range(i, end_idx)]
    # Add to index
    index.add_vectors(batch, metadata)
```

## Benchmarking and Optimization

### Performance Monitoring

The streaming system includes built-in performance monitoring:

```python
dataset = load_parquet("large_dataset.parquet", collect_stats=True)

# Process data
for batch in dataset.iter_batches():
    process_batch(batch)

# Get statistics
stats = dataset.get_stats()
print(f"Processed {stats['throughput']['total_records']} records")
print(f"Average throughput: {stats['throughput']['records_per_second']} records/second")
print(f"Average batch time: {stats['throughput']['avg_batch_time']} seconds")
```

### Benchmarking Different Configurations

The `examples/streaming_data_example.py` file includes tools for benchmarking:

- Different batch sizes
- Different prefetch counts
- Caching vs. no caching
- Memory-mapped vs. regular access
- Sequential vs. random access patterns

## Future Extensions

Planned future extensions include:

1. **Parallel Batch Processing**: Utilizing multiple cores for batch processing
2. **Adaptive Batch Sizing**: Automatically adjusting batch size based on performance
3. **Advanced Prefetching Strategies**: Predictive loading based on access patterns
4. **Distributed Streaming**: Integration with distributed data processing frameworks
5. **Optimized Vector Operations**: Fast similarity search within memory-mapped vectors