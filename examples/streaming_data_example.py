#!/usr/bin/env python3
"""
Example of using the streaming data loader module for performance optimizations.

This example demonstrates:
1. Loading large datasets efficiently with streaming
2. Memory-mapped access for large vector datasets
3. Performance optimization with prefetching and caching
4. Processing streaming data with transforms and filters

Requirements:
- PyArrow
- NumPy
- (Optional) HuggingFace datasets
"""

import os
import sys
import time
import tempfile
import argparse
import numpy as np
import matplotlib.pyplot as plt
from typing import Dict, List, Optional

# Add the parent directory to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Check for PyArrow
try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyarrow.csv as csv
    HAVE_ARROW = True
except ImportError:
    HAVE_ARROW = False
    print("PyArrow is not installed. Some functionality will be limited.")

# Check for HuggingFace datasets
try:
    from datasets import Dataset
    HAVE_DATASETS = True
except ImportError:
    HAVE_DATASETS = False
    print("HuggingFace datasets is not installed. Some functionality will be limited.")

# Import the streaming data loader
from ipfs_datasets_py.streaming_data_loader import (
    load_parquet,
    load_csv,
    load_json,
    load_huggingface,
    create_memory_mapped_vectors,
    load_memory_mapped_vectors,
    ParquetStreamingLoader,
    StreamingDataset
)


def generate_sample_parquet(output_path, num_rows=1000000):
    """
    Generate a sample Parquet file for testing.

    Args:
        output_path (str): Path to output file
        num_rows (int): Number of rows to generate
    """
    if not HAVE_ARROW:
        print("PyArrow is required to generate sample Parquet files.")
        return

    print(f"Generating sample Parquet file with {num_rows} rows...")

    # Generate data in chunks to avoid memory issues
    chunk_size = 100000
    writer = None

    for chunk_start in range(0, num_rows, chunk_size):
        chunk_end = min(chunk_start + chunk_size, num_rows)
        chunk_size = chunk_end - chunk_start

        # Generate chunk data
        data = {
            "id": pa.array(range(chunk_start, chunk_end)),
            "value_float": pa.array(np.random.rand(chunk_size).astype(np.float32)),
            "value_int": pa.array(np.random.randint(0, 100, size=chunk_size)),
            "category": pa.array(
                np.random.choice(["A", "B", "C", "D", "E"], size=chunk_size)
            ),
            "timestamp": pa.array(
                np.datetime64("2023-01-01") +
                np.random.randint(0, 365, size=chunk_size).astype("timedelta64[D]")
            )
        }

        chunk_table = pa.Table.from_pydict(data)

        # Write to Parquet (append mode for subsequent chunks)
        if writer is None:
            writer = pq.ParquetWriter(
                output_path,
                chunk_table.schema,
                compression="snappy"
            )

        writer.write_table(chunk_table)

        print(f"  Wrote chunk {chunk_start}-{chunk_end}")

    if writer:
        writer.close()

    print(f"Sample Parquet file generated at: {output_path}")
    print(f"File size: {os.path.getsize(output_path) / (1024*1024):.2f} MB")


def generate_sample_vectors(output_path, num_vectors=100000, dimension=128):
    """
    Generate a sample vector file for testing memory-mapped access.

    Args:
        output_path (str): Path to output file
        num_vectors (int): Number of vectors to generate
        dimension (int): Vector dimension
    """
    print(f"Generating sample vector file with {num_vectors} vectors of dimension {dimension}...")

    # Initialize memory-mapped vectors
    vectors = create_memory_mapped_vectors(
        file_path=output_path,
        dimension=dimension,
        mode='w+'
    )

    # Generate and add vectors in batches
    batch_size = 10000
    for i in range(0, num_vectors, batch_size):
        batch_end = min(i + batch_size, num_vectors)
        batch_count = batch_end - i

        print(f"  Generating batch {i}-{batch_end}...")
        batch = np.random.rand(batch_count, dimension).astype(np.float32)
        vectors.append(batch)

    # Close the memory map
    vectors.close()

    print(f"Sample vector file generated at: {output_path}")
    print(f"File size: {os.path.getsize(output_path) / (1024*1024):.2f} MB")


def benchmark_streaming_parquet(parquet_path, batch_sizes=[1000, 10000, 50000],
                              prefetch_counts=[1, 2, 4, 8],
                              use_caching=True):
    """
    Benchmark streaming performance with different configurations.

    Args:
        parquet_path (str): Path to Parquet file
        batch_sizes (List[int]): Batch sizes to test
        prefetch_counts (List[int]): Prefetch counts to test
        use_caching (bool): Whether to use caching

    Returns:
        Dict: Benchmark results
    """
    if not HAVE_ARROW:
        print("PyArrow is required for Parquet streaming.")
        return {}

    results = {}

    # Open the Parquet file to get metadata
    parquet_file = pq.ParquetFile(parquet_path)
    total_rows = parquet_file.metadata.num_rows

    for batch_size in batch_sizes:
        batch_results = {}

        for prefetch in prefetch_counts:
            print(f"Testing batch_size={batch_size}, prefetch={prefetch}...")

            # Create loader
            loader = ParquetStreamingLoader(
                parquet_path=parquet_path,
                batch_size=batch_size,
                prefetch_batches=prefetch,
                cache_enabled=use_caching,
                collect_stats=True
            )

            # Process the entire dataset
            start_time = time.time()
            processed_rows = 0

            for batch in loader.iter_batches():
                processed_rows += len(batch)

            elapsed = time.time() - start_time

            # Get performance stats
            stats = loader.get_stats()

            # Store results
            config_key = f"prefetch={prefetch}"
            batch_results[config_key] = {
                "elapsed_seconds": elapsed,
                "rows_per_second": processed_rows / elapsed,
                "batches_per_second": stats["throughput"]["batches_per_second"],
                "total_rows": processed_rows,
                "batch_size": batch_size,
                "prefetch": prefetch
            }

            print(f"  Processed {processed_rows} rows in {elapsed:.2f} seconds")
            print(f"  Throughput: {processed_rows / elapsed:.2f} rows/second")

        results[f"batch_size={batch_size}"] = batch_results

    return results


def benchmark_memory_mapped_vectors(vector_path, batch_sizes=[100, 1000, 10000]):
    """
    Benchmark memory-mapped vector access performance.

    Args:
        vector_path (str): Path to vector file
        batch_sizes (List[int]): Batch sizes to test

    Returns:
        Dict: Benchmark results
    """
    if not os.path.exists(vector_path):
        print(f"Vector file not found: {vector_path}")
        return {}

    # Get vector details from initial read
    vectors = load_memory_mapped_vectors(
        file_path=vector_path,
        dimension=128,  # Assume this is known
        mode='r'
    )

    dimension = vectors.dimension
    num_vectors = len(vectors)
    print(f"Vector file contains {num_vectors} vectors of dimension {dimension}")

    results = {}

    for batch_size in batch_sizes:
        print(f"Testing batch_size={batch_size}...")

        # Create random access pattern
        np.random.seed(42)  # For reproducibility
        access_indices = np.random.randint(0, num_vectors, size=10000)

        # Sequential batch read
        start_time = time.time()

        # Process in batches
        total_batches = num_vectors // batch_size
        for i in range(total_batches):
            start_idx = i * batch_size
            end_idx = min(start_idx + batch_size, num_vectors)
            batch = vectors[start_idx:end_idx]
            # Do something with the batch (e.g. compute mean)
            _ = np.mean(batch, axis=0)

        seq_elapsed = time.time() - start_time

        # Random access
        start_time = time.time()

        # Process in batches
        total_accesses = len(access_indices)
        for i in range(0, total_accesses, batch_size):
            end_idx = min(i + batch_size, total_accesses)
            batch_indices = access_indices[i:end_idx]
            # Access vectors by these indices
            batch = np.array([vectors[idx] for idx in batch_indices])
            # Do something with the batch
            _ = np.mean(batch, axis=0)

        random_elapsed = time.time() - start_time

        # Store results
        results[f"batch_size={batch_size}"] = {
            "sequential_elapsed_seconds": seq_elapsed,
            "sequential_vectors_per_second": num_vectors / seq_elapsed,
            "random_elapsed_seconds": random_elapsed,
            "random_vectors_per_second": total_accesses / random_elapsed,
            "batch_size": batch_size
        }

        print(f"  Sequential: {num_vectors / seq_elapsed:.2f} vectors/second")
        print(f"  Random: {total_accesses / random_elapsed:.2f} vectors/second")

    vectors.close()
    return results


def plot_benchmark_results(results, title, ylabel):
    """
    Plot benchmark results.

    Args:
        results (Dict): Benchmark results
        title (str): Plot title
        ylabel (str): Y-axis label
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("Matplotlib is required for plotting.")
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    batch_sizes = []
    configs = []
    data = []

    # Extract data
    for batch_key, batch_results in results.items():
        batch_size = int(batch_key.split('=')[1])
        batch_sizes.append(batch_size)

        for config_key, config_results in batch_results.items():
            if config_key not in configs:
                configs.append(config_key)

            while len(data) < len(configs):
                data.append([])

            config_idx = configs.index(config_key)
            while len(data[config_idx]) < len(batch_sizes) - 1:
                data[config_idx].append(0)

            if "rows_per_second" in config_results:
                data[config_idx].append(config_results["rows_per_second"])
            elif "sequential_vectors_per_second" in config_results:
                data[config_idx].append(config_results["sequential_vectors_per_second"])

    # Plot data
    for i, config in enumerate(configs):
        ax.plot(batch_sizes, data[i], marker='o', label=config)

    ax.set_title(title)
    ax.set_xlabel("Batch Size")
    ax.set_ylabel(ylabel)
    ax.set_xscale("log")
    ax.grid(True)
    ax.legend()

    plt.tight_layout()
    plt.savefig(f"{title.lower().replace(' ', '_')}.png")
    plt.close()


def demonstrate_data_transforms(parquet_path):
    """
    Demonstrate data transformation capabilities.

    Args:
        parquet_path (str): Path to Parquet file
    """
    if not HAVE_ARROW:
        print("PyArrow is required for this demonstration.")
        return

    print("Demonstrating data transformations...")

    # Load the dataset
    dataset = load_parquet(
        parquet_path=parquet_path,
        batch_size=10000,
        prefetch_batches=2
    )

    # Define a transformation function
    def transform_batch(batch):
        # Add a new column that is value_float * value_int
        value_float = batch.column("value_float").to_pylist()
        value_int = batch.column("value_int").to_pylist()
        product = [f * i for f, i in zip(value_float, value_int)]

        # Add the new column
        columns = list(batch.column_names)
        data = {name: batch.column(name) for name in columns}
        data["product"] = pa.array(product)

        return pa.Table.from_pydict(data)

    # Apply the transformation
    transformed = dataset.map(transform_batch)

    # Process and analyze the transformed data
    category_stats = {}
    product_by_category = {}

    for batch in transformed.iter_batches():
        # Get columns
        categories = batch.column("category").to_pylist()
        products = batch.column("product").to_pylist()

        # Update statistics
        for category, product in zip(categories, products):
            if category not in category_stats:
                category_stats[category] = 0
                product_by_category[category] = []

            category_stats[category] += 1
            product_by_category[category].append(product)

    # Calculate average product by category
    avg_product = {}
    for category, products in product_by_category.items():
        avg_product[category] = sum(products) / len(products)

    # Print results
    print("\nCategory Statistics:")
    for category, count in category_stats.items():
        print(f"  {category}: {count} rows, Avg product: {avg_product[category]:.4f}")


def demonstrate_memory_mapped_vectors(vector_path):
    """
    Demonstrate memory-mapped vector operations.

    Args:
        vector_path (str): Path to vector file
    """
    if not os.path.exists(vector_path):
        print(f"Vector file not found: {vector_path}")
        return

    print("Demonstrating memory-mapped vector operations...")

    # Open vectors
    vectors = load_memory_mapped_vectors(
        file_path=vector_path,
        dimension=128,  # Assume this is known
        mode='r'
    )

    dimension = vectors.dimension
    num_vectors = len(vectors)
    print(f"Vector file contains {num_vectors} vectors of dimension {dimension}")

    # Calculate mean vector
    print("Calculating mean vector...")
    start_time = time.time()

    # Process in batches to avoid loading everything at once
    batch_size = 10000
    sum_vector = np.zeros(dimension, dtype=np.float32)

    for i in range(0, num_vectors, batch_size):
        end_idx = min(i + batch_size, num_vectors)
        batch = vectors[i:end_idx]
        sum_vector += np.sum(batch, axis=0)

    mean_vector = sum_vector / num_vectors
    elapsed = time.time() - start_time

    print(f"Mean vector calculated in {elapsed:.2f} seconds")
    print(f"Mean: {mean_vector[:5]}... (first 5 elements)")

    # Perform nearest neighbor search
    print("\nDemonstrating nearest neighbor search...")

    # Use the mean as the query vector
    query_vector = mean_vector

    # Simple linear search (for demonstration)
    start_time = time.time()

    best_distance = float('inf')
    best_idx = -1

    for i in range(0, num_vectors, batch_size):
        end_idx = min(i + batch_size, num_vectors)
        batch = vectors[i:end_idx]

        # Calculate distances (using Euclidean distance)
        distances = np.sqrt(np.sum((batch - query_vector) ** 2, axis=1))

        # Find the minimum in this batch
        min_dist = np.min(distances)
        min_idx = np.argmin(distances)

        # Update best if better
        if min_dist < best_distance:
            best_distance = min_dist
            best_idx = i + min_idx

    elapsed = time.time() - start_time

    print(f"Nearest neighbor search completed in {elapsed:.2f} seconds")
    print(f"Best match: index={best_idx}, distance={best_distance:.4f}")

    # Get the best matching vector
    best_vector = vectors[best_idx]
    print(f"Best vector: {best_vector[:5]}... (first 5 elements)")

    vectors.close()


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Streaming Data Loader Example"
    )

    parser.add_argument(
        "--generate-parquet",
        action="store_true",
        help="Generate a sample Parquet file"
    )

    parser.add_argument(
        "--generate-vectors",
        action="store_true",
        help="Generate a sample vector file"
    )

    parser.add_argument(
        "--benchmark-parquet",
        action="store_true",
        help="Benchmark Parquet streaming performance"
    )

    parser.add_argument(
        "--benchmark-vectors",
        action="store_true",
        help="Benchmark memory-mapped vector performance"
    )

    parser.add_argument(
        "--transform-demo",
        action="store_true",
        help="Demonstrate data transformations"
    )

    parser.add_argument(
        "--vector-demo",
        action="store_true",
        help="Demonstrate memory-mapped vector operations"
    )

    parser.add_argument(
        "--parquet-file",
        default=None,
        help="Path to Parquet file (default: generates a temporary file)"
    )

    parser.add_argument(
        "--vector-file",
        default=None,
        help="Path to vector file (default: generates a temporary file)"
    )

    parser.add_argument(
        "--num-rows",
        type=int,
        default=1000000,
        help="Number of rows for sample Parquet file"
    )

    parser.add_argument(
        "--num-vectors",
        type=int,
        default=100000,
        help="Number of vectors for sample vector file"
    )

    parser.add_argument(
        "--dimension",
        type=int,
        default=128,
        help="Vector dimension for sample vector file"
    )

    args = parser.parse_args()

    # Determine file paths
    if args.parquet_file:
        parquet_path = args.parquet_file
    else:
        # Create a temporary file
        parquet_fd, parquet_path = tempfile.mkstemp(suffix=".parquet")
        os.close(parquet_fd)

    if args.vector_file:
        vector_path = args.vector_file
    else:
        # Create a temporary file
        vector_fd, vector_path = tempfile.mkstemp(suffix=".vectors")
        os.close(vector_fd)

    try:
        # Generate sample data if needed
        if args.generate_parquet or (not args.parquet_file and (
            args.benchmark_parquet or args.transform_demo
        )):
            generate_sample_parquet(parquet_path, args.num_rows)

        if args.generate_vectors or (not args.vector_file and (
            args.benchmark_vectors or args.vector_demo
        )):
            generate_sample_vectors(
                vector_path,
                args.num_vectors,
                args.dimension
            )

        # Run benchmarks
        if args.benchmark_parquet:
            results = benchmark_streaming_parquet(parquet_path)
            plot_benchmark_results(
                results,
                "Parquet Streaming Performance",
                "Rows per Second"
            )

        if args.benchmark_vectors:
            results = benchmark_memory_mapped_vectors(vector_path)
            plot_benchmark_results(
                results,
                "Memory-Mapped Vector Performance",
                "Vectors per Second"
            )

        # Run demonstrations
        if args.transform_demo:
            demonstrate_data_transforms(parquet_path)

        if args.vector_demo:
            demonstrate_memory_mapped_vectors(vector_path)

        # If no actions specified, show help
        if not (args.generate_parquet or args.generate_vectors or
                args.benchmark_parquet or args.benchmark_vectors or
                args.transform_demo or args.vector_demo):
            parser.print_help()

    finally:
        # Clean up temporary files
        if not args.parquet_file:
            try:
                os.unlink(parquet_path)
            except:
                pass

        if not args.vector_file:
            try:
                os.unlink(vector_path)
            except:
                pass


if __name__ == "__main__":
    main()
