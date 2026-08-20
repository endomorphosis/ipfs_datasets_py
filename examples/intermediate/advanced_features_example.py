"""
Advanced Features Example: Metadata Extraction and Batch Processing

Demonstrates enhanced features from Phase 3 continued:
- Rich metadata extraction
- Enhanced batch processing with progress tracking
- Resource management
- Caching
"""

import asyncio
import tempfile
from pathlib import Path

# Import all the new features
from ipfs_datasets_py.processors.file_converter import (
    IPFSAcceleratedConverter,
    MetadataExtractor,
    BatchProcessor,
    BatchProgress,
    ResourceLimits,
    CacheManager,
    create_batch_processor,
    extract_metadata,
)


def create_test_files():
    """Create temporary test files."""
    files = []

    # Create various file types
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("This is a plain text document with some content.\n" * 10)
        files.append(f.name)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("# Markdown Document\n\nThis is a **markdown** file.\n" * 5)
        files.append(f.name)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write('{"name": "test", "value": 123, "items": [1, 2, 3]}')
        files.append(f.name)

    return files


def demo_1_metadata_extraction():
    """Demo 1: Extract rich metadata from files."""
    print("\n" + "=" * 70)
    print("DEMO 1: Rich Metadata Extraction")
    print("=" * 70)

    files = create_test_files()

    try:
        # Create metadata extractor
        extractor = MetadataExtractor(enable_ipfs=True)
        print("\n✅ Created metadata extractor")

        # Extract metadata from first file
        print(f"\n📄 Extracting metadata from: {Path(files[0]).name}")
        metadata = extractor.extract(files[0])

        print("\n📊 Metadata extracted:")
        print(f"  • File name: {metadata['file']['name']}")
        print(f"  • File size: {metadata['file']['size_human']}")
        print(f"  • Modified: {metadata['file']['modified']}")
        print(f"  • Extension: {metadata['file']['extension']}")
        print(f"  • MD5 hash: {metadata['hashes']['md5']}")
        print(f"  • SHA256 hash: {metadata['hashes']['sha256'][:16]}...")
        print(f"  • MIME type: {metadata['format']['mime_type']}")

        # Extract from all files in batch
        print(f"\n📦 Extracting metadata from {len(files)} files...")
        batch_metadata = extractor.extract_batch(files)

        print(f"\n✅ Extracted metadata from {len(batch_metadata)} files")
        for file_path, meta in batch_metadata.items():
            if "file" in meta:
                print(f"  • {Path(file_path).name}: {meta['file']['size_human']}")

        print("\n✅ Metadata extraction complete!")

    finally:
        # Cleanup
        for file_path in files:
            Path(file_path).unlink(missing_ok=True)


def demo_2_batch_processing_with_progress():
    """Demo 2: Batch processing with progress tracking."""
    print("\n" + "=" * 70)
    print("DEMO 2: Batch Processing with Progress Tracking")
    print("=" * 70)

    files = create_test_files()

    try:
        # Create converter
        converter = IPFSAcceleratedConverter(backend="native", enable_ipfs=False)
        print("\n✅ Created IPFS-accelerated converter (local mode)")

        # Define progress callback
        def progress_callback(progress: BatchProgress):
            """Called on each progress update."""
            data = progress.to_dict()
            print(
                f"\r  Progress: {data['completed']}/{data['total']} completed, "
                f"{data['failed']} failed, "
                f"{data['success_rate']:.1f}% success rate",
                end="",
            )

        # Create batch processor with progress tracking
        processor = create_batch_processor(
            converter, max_concurrent=3, progress_callback=progress_callback
        )

        print(f"\n📦 Processing {len(files)} files with progress tracking...")

        # Process batch
        results = processor.process_batch_sync(files)

        print()  # New line after progress
        print(f"\n✅ Processed {len(results)} files successfully!")

        for result in results:
            if result:
                print(
                    f"  • {result.metadata.get('format', 'unknown')}: {len(result.text)} characters"
                )

    finally:
        for file_path in files:
            Path(file_path).unlink(missing_ok=True)


async def demo_3_async_batch_with_limits():
    """Demo 3: Async batch processing with resource limits."""
    print("\n" + "=" * 70)
    print("DEMO 3: Async Batch Processing with Resource Limits")
    print("=" * 70)

    files = create_test_files()

    try:
        # Create converter
        converter = IPFSAcceleratedConverter(backend="native")
        print("\n✅ Created converter")

        # Create resource limits
        limits = ResourceLimits(
            max_concurrent=2,  # Max 2 files at once
            max_file_size_mb=10,  # Max 10 MB per file
            timeout_seconds=5.0,  # 5 second timeout per file
        )

        print(f"\n⚙️  Resource limits:")
        print(f"  • Max concurrent: {limits.max_concurrent}")
        print(f"  • Max file size: {limits.max_file_size_mb} MB")
        print(f"  • Timeout: {limits.timeout_seconds} seconds")

        # Create processor with limits
        processor = BatchProcessor(converter, limits=limits)

        print(f"\n📦 Processing {len(files)} files asynchronously...")

        # Process files
        results = await processor.process_batch(files)

        print(f"\n✅ Processed {len(results)} files with resource limits!")

        # All files should pass limits
        for result in results:
            if result:
                print(f"  • Success: {len(result.text)} characters extracted")

    finally:
        for file_path in files:
            Path(file_path).unlink(missing_ok=True)


def demo_4_caching():
    """Demo 4: Caching for performance."""
    print("\n" + "=" * 70)
    print("DEMO 4: Caching for Performance")
    print("=" * 70)

    files = create_test_files()

    try:
        # Create cache manager
        cache = CacheManager()
        print("\n✅ Created cache manager")
        print(f"  • Cache directory: {cache.cache_dir}")

        # Generate cache key for file
        cache_key = cache.get_cache_key(files[0], backend="native")
        print(f"\n🔑 Cache key for first file: {cache_key[:16]}...")

        # Simulate caching converted content
        cache.set(cache_key, "Cached conversion result")

        # Retrieve from cache
        cached_result = cache.get(cache_key)
        print(f"\n✅ Retrieved from cache: '{cached_result}'")

        # Check cache miss
        miss_result = cache.get("nonexistent_key")
        print(f"✅ Cache miss handled: {miss_result}")

        # Clear cache
        cache.clear()
        print(f"\n✅ Cache cleared")

        after_clear = cache.get(cache_key)
        print(f"✅ After clear: {after_clear}")

    finally:
        for file_path in files:
            Path(file_path).unlink(missing_ok=True)


def demo_5_combined_workflow():
    """Demo 5: Complete workflow combining all features."""
    print("\n" + "=" * 70)
    print("DEMO 5: Complete Workflow - All Features Combined")
    print("=" * 70)

    files = create_test_files()

    try:
        # 1. Extract metadata first
        print("\n📊 Step 1: Extract metadata...")
        metadata_results = extract_metadata(files[0])
        print(f"  • File: {metadata_results['file']['name']}")
        print(f"  • Size: {metadata_results['file']['size_human']}")
        print(f"  • Hash: {metadata_results['hashes']['sha256'][:16]}...")

        # 2. Create converter with all features
        print("\n🔧 Step 2: Create converter with all features...")
        converter = IPFSAcceleratedConverter(
            backend="native",
            enable_ipfs=False,  # Local mode
            enable_acceleration=False,  # Local mode
        )
        print("  • Converter created")

        # 3. Setup batch processor with progress
        print("\n⚙️  Step 3: Setup batch processor...")
        progress_updates = []

        def track_progress(progress):
            progress_updates.append(progress.to_dict())

        processor = create_batch_processor(
            converter, max_concurrent=2, max_file_size_mb=10, progress_callback=track_progress
        )
        print(f"  • Processor configured with limits")

        # 4. Process batch
        print(f"\n📦 Step 4: Process {len(files)} files...")
        results = processor.process_batch_sync(files)

        print(f"\n✅ Processing complete!")
        print(f"  • Files processed: {len(results)}")
        print(f"  • Progress updates: {len(progress_updates)}")

        if progress_updates:
            final = progress_updates[-1]
            print(f"  • Success rate: {final['success_rate']:.1f}%")
            print(f"  • Items/sec: {final['items_per_second']:.2f}")

        # 5. Show results
        print("\n📄 Step 5: Results summary...")
        for i, result in enumerate(results[:3], 1):  # Show first 3
            if result:
                print(
                    f"  • File {i}: {len(result.text)} chars, "
                    f"backend: {result.metadata.get('backend', 'unknown')}"
                )

        print("\n✅ Complete workflow finished successfully!")

    finally:
        for file_path in files:
            Path(file_path).unlink(missing_ok=True)


def main():
    """Run all demos."""
    print("\n" + "=" * 70)
    print("ADVANCED FEATURES DEMONSTRATION")
    print("Phase 3 Continued: Metadata & Batch Processing")
    print("=" * 70)

    try:
        # Run all demos
        demo_1_metadata_extraction()
        demo_2_batch_processing_with_progress()

        # Async demo
        print("\nRunning async demo...")
        asyncio.run(demo_3_async_batch_with_limits())

        demo_4_caching()
        demo_5_combined_workflow()

        # Summary
        print("\n" + "=" * 70)
        print("💡 KEY TAKEAWAYS")
        print("=" * 70)
        print("""
✅ Rich Metadata Extraction
   • File properties, hashes, MIME types
   • Batch extraction support
   • IPFS-ready with CID calculation

✅ Enhanced Batch Processing
   • Progress tracking with callbacks
   • Resource limits (concurrency, size, timeout)
   • Async and sync APIs

✅ Caching Layer
   • Content-based cache keys
   • Performance optimization
   • Simple get/set/clear API

✅ Complete Integration
   • All features work together
   • Graceful degradation
   • Production-ready

These features combine the best of:
   • omni_converter_mk2 (metadata, resource management)
   • convert_to_txt_based_on_mime_type (async, batch)
   • ipfs_kit_py (content addressing)
   • Native implementation (zero deps)
        """)

        print("\n✅ All demos completed successfully!")

    except Exception as e:
        print(f"\n❌ Error in demo: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
