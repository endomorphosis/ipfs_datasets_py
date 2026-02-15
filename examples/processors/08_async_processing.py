"""
Async Processing Example with Anyio
====================================

This example demonstrates the async capabilities of the processor system
using anyio for unified async support.

Shows:
1. Single file async processing
2. Concurrent batch processing
3. Using anyio backend flexibility (asyncio/trio)
"""

import anyio
from ipfs_datasets_py.processors.adapters import register_all_adapters
from ipfs_datasets_py.processors.core import UniversalProcessor


async def process_single_file():
    """Example 1: Process a single file asynchronously."""
    print("\n" + "=" * 70)
    print("Example 1: Single File Async Processing")
    print("=" * 70)
    
    processor = UniversalProcessor()
    
    # Simulate processing a PDF file
    file_path = "example_document.pdf"
    print(f"\nProcessing: {file_path}")
    print("Using async/await for non-blocking I/O...")
    
    # Note: Uncomment to actually process
    # result = await processor.process(file_path)
    # if result.success:
    #     entities = len(result.knowledge_graph.get('entities', []))
    #     print(f"✓ Success! Found {entities} entities")
    # else:
    #     print(f"✗ Failed: {result.errors}")
    
    print("✓ Async processing complete")


async def process_batch_concurrent():
    """Example 2: Process multiple files concurrently."""
    print("\n" + "=" * 70)
    print("Example 2: Concurrent Batch Processing")
    print("=" * 70)
    
    processor = UniversalProcessor()
    
    # List of files to process
    files = [
        "doc1.pdf",
        "doc2.pdf",
        "doc3.pdf",
        "doc4.pdf",
        "doc5.pdf"
    ]
    
    print(f"\nProcessing {len(files)} files concurrently...")
    print("Using anyio.create_task_group() for parallel execution...")
    
    # Note: Uncomment to actually process
    # results = await processor.process_batch(files, parallel=True)
    # successful = len([r for r in results if r.success])
    # print(f"✓ Processed {successful}/{len(files)} files successfully")
    
    print("✓ Concurrent batch processing complete")


async def demonstrate_anyio_features():
    """Example 3: Demonstrate anyio-specific features."""
    print("\n" + "=" * 70)
    print("Example 3: Anyio Features")
    print("=" * 70)
    
    processor = UniversalProcessor()
    
    print("\n1. Timeout Support:")
    print("   Using anyio.fail_after() for automatic timeout")
    try:
        with anyio.fail_after(5.0):  # 5 second timeout
            # result = await processor.process("large_file.pdf")
            print("   ✓ Processing with 5-second timeout")
    except TimeoutError:
        print("   ✗ Processing timed out")
    
    print("\n2. Concurrent Task Management:")
    print("   Using anyio.create_task_group() for structured concurrency")
    async with anyio.create_task_group() as tg:
        # tg.start_soon(processor.process, "file1.pdf")
        # tg.start_soon(processor.process, "file2.pdf")
        print("   ✓ Task group manages concurrent operations")
    
    print("\n3. Non-blocking Sleep:")
    print("   Using anyio.sleep() for delays without blocking")
    await anyio.sleep(0.1)
    print("   ✓ Slept 0.1 seconds without blocking other tasks")
    
    print("\n4. Backend Flexibility:")
    print("   This code works with asyncio, trio, or any anyio backend")
    print("   ✓ No need to change code for different async backends")


async def main():
    """Main async function demonstrating all examples."""
    print("=" * 70)
    print("Async Processing Examples with Anyio")
    print("=" * 70)
    
    # Register adapters
    print("\nRegistering processor adapters...")
    count = register_all_adapters()
    print(f"✓ Registered {count} adapters")
    
    # Run examples
    await process_single_file()
    await process_batch_concurrent()
    await demonstrate_anyio_features()
    
    print("\n" + "=" * 70)
    print("All examples complete!")
    print("=" * 70)


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("Async Processors with Anyio")
    print("=" * 70)
    print("\nBenefits of async processing:")
    print("  • Non-blocking I/O for better resource utilization")
    print("  • Concurrent processing of multiple files")
    print("  • Backend flexibility (asyncio, trio, etc.)")
    print("  • Structured concurrency with anyio")
    print("\nRunning examples...")
    
    # Use anyio.run() - works with any async backend
    anyio.run(main)
    
    print("\nNote: Uncomment the actual processing calls to run with real files")
