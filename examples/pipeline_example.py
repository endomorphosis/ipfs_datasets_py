"""
Example: Using the async pipeline with monadic error handling.

Demonstrates Phase 2 Feature 3: Async Pipeline
Shows how to build composable pipelines with Result/Error monads.
"""

import asyncio
from pathlib import Path
from ipfs_datasets_py.file_converter import (
    Pipeline, FileUnit, Result, Error,
    ok, error, ErrorType,
    validate_file_exists, detect_format, extract_text,
    StreamProcessor
)


async def example_basic_pipeline():
    """Example 1: Basic file processing pipeline."""
    print("\n" + "="*70)
    print("Example 1: Basic File Processing Pipeline")
    print("="*70)
    
    # Create a simple test file
    test_file = Path("/tmp/test_document.txt")
    test_file.write_text("This is a test document for the pipeline example.")
    
    # Build pipeline with three stages
    pipeline = Pipeline()
    pipeline.add_stage(validate_file_exists, name="validate")
    pipeline.add_stage(detect_format, name="detect_format")
    pipeline.add_stage(extract_text, name="extract_text")
    
    # Process file through pipeline
    file_unit = FileUnit.from_path(test_file)
    result = await pipeline.process(file_unit)
    
    # Handle result
    if result.is_ok():
        final_unit = result.unwrap()
        print(f"✅ Success!")
        print(f"   MIME Type: {final_unit.mime_type}")
        print(f"   Text Length: {len(final_unit.text)} chars")
        print(f"   Text Preview: {final_unit.text[:50]}...")
        print(f"   Metadata: {final_unit.metadata}")
    else:
        print(f"❌ Error: {result.message}")


async def example_error_handling():
    """Example 2: Error handling with missing file."""
    print("\n" + "="*70)
    print("Example 2: Error Handling (Missing File)")
    print("="*70)
    
    # Try to process non-existent file
    pipeline = Pipeline()
    pipeline.add_stage(validate_file_exists, name="validate")
    pipeline.add_stage(detect_format, name="detect_format")
    pipeline.add_stage(extract_text, name="extract_text")
    
    file_unit = FileUnit.from_path("/nonexistent/file.txt")
    result = await pipeline.process(file_unit)
    
    # Error is propagated through pipeline
    if result.is_error():
        print(f"❌ Error caught: {result.error_type.value}")
        print(f"   Message: {result.message}")
        print(f"   Context: {result.context}")
        print("✅ Pipeline handled error gracefully (didn't crash)")


async def example_custom_stages():
    """Example 3: Custom pipeline stages."""
    print("\n" + "="*70)
    print("Example 3: Custom Pipeline Stages")
    print("="*70)
    
    # Create test file
    test_file = Path("/tmp/numbers.txt")
    test_file.write_text("42\n17\n99\n3")
    
    # Custom stage: Parse numbers from text
    async def parse_numbers(file_unit: FileUnit):
        """Extract numbers from text."""
        try:
            numbers = [int(line.strip()) for line in file_unit.text.split('\n') if line.strip()]
            return ok(file_unit.with_metadata(numbers=numbers, count=len(numbers)))
        except Exception as e:
            return error(ErrorType.VALIDATION_FAILED, f"Failed to parse numbers: {e}")
    
    # Custom stage: Calculate statistics
    async def calculate_stats(file_unit: FileUnit):
        """Calculate statistics."""
        numbers = file_unit.metadata.get('numbers', [])
        if not numbers:
            return error(ErrorType.VALIDATION_FAILED, "No numbers found")
        
        stats = {
            'min': min(numbers),
            'max': max(numbers),
            'sum': sum(numbers),
            'avg': sum(numbers) / len(numbers)
        }
        return ok(file_unit.with_metadata(stats=stats))
    
    # Build custom pipeline
    pipeline = Pipeline()
    pipeline.add_stage(validate_file_exists, name="validate")
    pipeline.add_stage(extract_text, name="extract_text")
    pipeline.add_stage(parse_numbers, name="parse_numbers")
    pipeline.add_stage(calculate_stats, name="calculate_stats")
    
    # Process
    file_unit = FileUnit.from_path(test_file)
    result = await pipeline.process(file_unit)
    
    if result.is_ok():
        final_unit = result.unwrap()
        print(f"✅ Numbers found: {final_unit.metadata['numbers']}")
        print(f"✅ Statistics: {final_unit.metadata['stats']}")


async def example_result_monad():
    """Example 4: Result/Error monad operations."""
    print("\n" + "="*70)
    print("Example 4: Result/Error Monad Operations")
    print("="*70)
    
    # Map operation
    result = Result(10)
    doubled = result.map(lambda x: x * 2)
    print(f"Map: Result(10).map(x*2) = {doubled.unwrap()}")
    
    # Flat map (monadic bind)
    def safe_divide(x):
        if x == 0:
            return error(ErrorType.VALIDATION_FAILED, "Division by zero")
        return ok(100 / x)
    
    result = Result(5)
    divided = result.flat_map(safe_divide)
    print(f"Flat map: Result(5).flat_map(100/x) = {divided.unwrap()}")
    
    # Error propagation
    result = Result(0)
    divided = result.flat_map(safe_divide)
    print(f"Error prop: Result(0).flat_map(100/x) = {divided}")
    
    # Async map
    async def async_square(x):
        await asyncio.sleep(0.001)
        return x ** 2
    
    result = Result(7)
    squared = await result.map_async(async_square)
    print(f"Async map: Result(7).map_async(x²) = {squared.unwrap()}")


async def example_stream_processing():
    """Example 5: Stream processing for large files."""
    print("\n" + "="*70)
    print("Example 5: Stream Processing")
    print("="*70)
    
    # Create a larger test file
    test_file = Path("/tmp/large_file.txt")
    content = "Hello, World!\n" * 1000  # ~14KB
    test_file.write_text(content)
    
    # Process in chunks
    processor = StreamProcessor(chunk_size=100)
    
    # Count lines in each chunk
    result = await processor.process_stream(
        test_file,
        lambda chunk: chunk.count(b'\n')
    )
    
    if result.is_ok():
        line_counts = result.unwrap()
        total_lines = sum(line_counts)
        print(f"✅ Processed {len(line_counts)} chunks")
        print(f"✅ Total lines: {total_lines}")
        print(f"✅ File size: {test_file.stat().st_size} bytes")


async def example_pipeline_composition():
    """Example 6: Composing multiple pipelines."""
    print("\n" + "="*70)
    print("Example 6: Pipeline Composition")
    print("="*70)
    
    # Create test file
    test_file = Path("/tmp/composition_test.txt")
    test_file.write_text("Alpha Beta Gamma Delta")
    
    # First pipeline: Extract text
    extract_pipeline = Pipeline()
    extract_pipeline.add_stage(validate_file_exists, name="validate")
    extract_pipeline.add_stage(extract_text, name="extract")
    
    # Process through first pipeline
    file_unit = FileUnit.from_path(test_file)
    result = await extract_pipeline.process(file_unit)
    
    if result.is_ok():
        # Second pipeline: Analyze text
        analyze_pipeline = Pipeline()
        analyze_pipeline.add_stage(
            lambda u: ok(u.with_metadata(
                words=u.text.split(),
                word_count=len(u.text.split())
            )),
            name="count_words"
        )
        analyze_pipeline.add_stage(
            lambda u: ok(u.with_metadata(
                uppercase_words=[w for w in u.metadata['words'] if w[0].isupper()]
            )),
            name="find_uppercase"
        )
        
        # Process through second pipeline
        result2 = await analyze_pipeline.process(result.unwrap())
        
        if result2.is_ok():
            final = result2.unwrap()
            print(f"✅ Word count: {final.metadata['word_count']}")
            print(f"✅ Uppercase words: {final.metadata['uppercase_words']}")


async def main():
    """Run all examples."""
    print("\n" + "="*70)
    print("ASYNC PIPELINE EXAMPLES - Phase 2 Feature 3")
    print("="*70)
    
    await example_basic_pipeline()
    await example_error_handling()
    await example_custom_stages()
    await example_result_monad()
    await example_stream_processing()
    await example_pipeline_composition()
    
    print("\n" + "="*70)
    print("All examples completed!")
    print("="*70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
