"""
Batch Processing - Process Files at Scale

This example demonstrates how to process large numbers of files efficiently
using batch processing with resource limits, progress tracking, and error handling.

Requirements:
    - Core ipfs_datasets_py dependencies

Usage:
    python examples/09_batch_processing.py
"""

import asyncio
import tempfile
from pathlib import Path
import time


def create_test_dataset(num_files=20):
    """Create a test dataset with multiple files."""
    tmpdir = Path(tempfile.mkdtemp())
    
    print(f"\n📝 Creating {num_files} test files in {tmpdir}...")
    
    files = []
    for i in range(num_files):
        # Create files of varying sizes and types
        if i % 3 == 0:
            # Text files
            file_path = tmpdir / f"document_{i}.txt"
            file_path.write_text(f"This is document {i}.\n" * (50 + i * 10))
        elif i % 3 == 1:
            # JSON files
            file_path = tmpdir / f"data_{i}.json"
            file_path.write_text(f'{{"id": {i}, "value": "test_{i}", "data": [1, 2, 3]}}')
        else:
            # Markdown files
            file_path = tmpdir / f"note_{i}.md"
            file_path.write_text(f"# Note {i}\n\nThis is a markdown note.\n\n" * 5)
        
        files.append(file_path)
    
    print(f"   ✅ Created {len(files)} files")
    return tmpdir, files


async def demo_basic_batch_processing():
    """Process multiple files in batch."""
    print("\n" + "="*70)
    print("DEMO 1: Basic Batch Processing")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.file_converter import BatchProcessor
        
        # Create test files
        tmpdir, files = create_test_dataset(10)
        
        # Initialize batch processor
        print("\n🔄 Initializing batch processor...")
        processor = BatchProcessor(max_concurrent=3)
        
        # Process all files
        print(f"\n📊 Processing {len(files)} files...")
        start_time = time.time()
        
        results = await processor.process_batch(
            files=files,
            target_format='txt'
        )
        
        elapsed = time.time() - start_time
        
        # Summary
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        
        print(f"\n✅ Batch processing complete")
        print(f"   Total files: {len(results)}")
        print(f"   Successful: {successful}")
        print(f"   Failed: {failed}")
        print(f"   Time: {elapsed:.2f} seconds")
        print(f"   Throughput: {len(results)/elapsed:.2f} files/second")
        
        # Show sample results
        print("\n   Sample results:")
        for i, result in enumerate(results[:3], 1):
            status = "✅" if result.success else "❌"
            length = len(result.content) if result.success else 0
            print(f"   {status} File {i}: {length} characters")
        
        # Cleanup
        import shutil
        shutil.rmtree(tmpdir)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def demo_resource_limits():
    """Batch processing with resource limits."""
    print("\n" + "="*70)
    print("DEMO 2: Resource-Limited Batch Processing")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.file_converter import (
            BatchProcessor,
            ResourceLimits
        )
        
        tmpdir, files = create_test_dataset(15)
        
        # Define resource limits
        print("\n⚙️  Configuring resource limits...")
        limits = ResourceLimits(
            max_memory_mb=512,      # Max 512MB memory
            max_concurrent=5,        # Max 5 concurrent tasks
            timeout_seconds=30       # 30 second timeout per file
        )
        
        print(f"   Max memory: {limits.max_memory_mb} MB")
        print(f"   Max concurrent: {limits.max_concurrent}")
        print(f"   Timeout: {limits.timeout_seconds}s")
        
        # Process with limits
        processor = BatchProcessor(resource_limits=limits)
        
        print(f"\n📊 Processing {len(files)} files with limits...")
        results = await processor.process_batch(files, target_format='txt')
        
        successful = sum(1 for r in results if r.success)
        print(f"\n✅ Completed: {successful}/{len(results)} files")
        
        import shutil
        shutil.rmtree(tmpdir)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")


async def demo_progress_tracking():
    """Batch processing with progress tracking."""
    print("\n" + "="*70)
    print("DEMO 3: Progress Tracking")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.file_converter import (
            BatchProcessor,
            BatchProgress
        )
        
        tmpdir, files = create_test_dataset(20)
        
        print("\n📊 Processing with progress tracking...")
        
        # Progress callback
        def on_progress(progress: BatchProgress):
            percent = (progress.completed / progress.total) * 100
            print(f"   Progress: {progress.completed}/{progress.total} "
                  f"({percent:.1f}%) - "
                  f"Success: {progress.successful}, Failed: {progress.failed}")
        
        processor = BatchProcessor(
            max_concurrent=4,
            progress_callback=on_progress
        )
        
        results = await processor.process_batch(files, target_format='txt')
        
        print(f"\n✅ Processing complete")
        
        import shutil
        shutil.rmtree(tmpdir)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")


async def demo_error_handling():
    """Batch processing with error handling."""
    print("\n" + "="*70)
    print("DEMO 4: Error Handling")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.file_converter import BatchProcessor
        
        tmpdir, files = create_test_dataset(10)
        
        # Add some invalid files
        invalid_file = tmpdir / "corrupted.txt"
        invalid_file.write_bytes(b'\x00\x00\xff\xff')  # Binary garbage
        files.append(invalid_file)
        
        print(f"\n🔧 Processing {len(files)} files (including 1 invalid)...")
        
        processor = BatchProcessor(
            max_concurrent=3,
            continue_on_error=True  # Don't stop on errors
        )
        
        results = await processor.process_batch(files, target_format='txt')
        
        # Analyze results
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        
        print(f"\n📊 Results:")
        print(f"   Total: {len(results)}")
        print(f"   Successful: {len(successful)}")
        print(f"   Failed: {len(failed)}")
        
        if failed:
            print("\n   Failed files:")
            for result in failed:
                print(f"      - {result.source_file}: {result.error}")
        
        import shutil
        shutil.rmtree(tmpdir)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")


async def demo_parallel_processing():
    """Compare sequential vs parallel processing."""
    print("\n" + "="*70)
    print("DEMO 5: Sequential vs Parallel Performance")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.file_converter import BatchProcessor
        
        tmpdir, files = create_test_dataset(15)
        
        # Sequential processing (1 at a time)
        print("\n🐌 Sequential processing...")
        processor_seq = BatchProcessor(max_concurrent=1)
        start_seq = time.time()
        results_seq = await processor_seq.process_batch(files, target_format='txt')
        time_seq = time.time() - start_seq
        
        print(f"   Time: {time_seq:.2f}s")
        print(f"   Throughput: {len(files)/time_seq:.2f} files/second")
        
        # Parallel processing (5 concurrent)
        print("\n🚀 Parallel processing (5 concurrent)...")
        processor_par = BatchProcessor(max_concurrent=5)
        start_par = time.time()
        results_par = await processor_par.process_batch(files, target_format='txt')
        time_par = time.time() - start_par
        
        print(f"   Time: {time_par:.2f}s")
        print(f"   Throughput: {len(files)/time_par:.2f} files/second")
        
        # Compare
        speedup = time_seq / time_par
        print(f"\n⚡ Speedup: {speedup:.2f}x faster with parallel processing")
        
        import shutil
        shutil.rmtree(tmpdir)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")


async def demo_caching():
    """Batch processing with caching."""
    print("\n" + "="*70)
    print("DEMO 6: Caching for Repeated Processing")
    print("="*70)
    
    print("\n💾 Caching Example")
    
    example_code = '''
from ipfs_datasets_py.processors.file_converter import (
    BatchProcessor,
    CacheManager
)

# Initialize cache
cache = CacheManager(cache_dir="/tmp/batch_cache")

# Create processor with cache
processor = BatchProcessor(
    max_concurrent=5,
    cache_manager=cache,
    use_cache=True
)

# First run: processes all files
print("First run...")
results1 = await processor.process_batch(files, target_format='txt')
# Time: 10 seconds

# Second run: uses cached results
print("Second run (cached)...")
results2 = await processor.process_batch(files, target_format='txt')
# Time: 0.5 seconds (20x faster!)
    '''
    
    print(example_code)
    
    print("\n💡 Caching benefits:")
    print("   - Skip reprocessing unchanged files")
    print("   - Much faster on repeated runs")
    print("   - Save compute resources")


def show_tips():
    """Show tips for batch processing."""
    print("\n" + "="*70)
    print("TIPS FOR BATCH PROCESSING")
    print("="*70)
    
    print("\n1. Concurrency:")
    print("   - Start with max_concurrent = CPU cores")
    print("   - Adjust based on I/O vs CPU workload")
    print("   - Monitor memory usage and adjust")
    
    print("\n2. Resource Management:")
    print("   - Set memory limits to prevent OOM")
    print("   - Use timeouts for long-running tasks")
    print("   - Implement backpressure if needed")
    
    print("\n3. Error Handling:")
    print("   - Use continue_on_error=True for resilience")
    print("   - Log errors for later analysis")
    print("   - Retry failed files separately")
    
    print("\n4. Performance:")
    print("   - Profile to find bottlenecks")
    print("   - Use caching for repeated processing")
    print("   - Consider distributing across machines")
    
    print("\n5. Progress Tracking:")
    print("   - Implement progress callbacks")
    print("   - Persist state for long-running jobs")
    print("   - Allow resumption after interruption")
    
    print("\n6. Best Practices:")
    print("   - Test on small batches first")
    print("   - Monitor system resources")
    print("   - Have fallback strategies")
    print("   - Keep audit logs")
    
    print("\n7. Scaling:")
    print("   - For >10k files: Consider chunking")
    print("   - For >100k files: Use distributed processing")
    print("   - Consider cloud services for massive scale")


async def main():
    """Run all batch processing demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - BATCH PROCESSING")
    print("="*70)
    
    await demo_basic_batch_processing()
    await demo_resource_limits()
    await demo_progress_tracking()
    await demo_error_handling()
    await demo_parallel_processing()
    await demo_caching()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ BATCH PROCESSING EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
