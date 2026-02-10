#!/usr/bin/env python3
"""
Example: Using the FileConverter for various file types.

This example demonstrates:
1. Basic file conversion
2. Backend selection
3. Batch processing
4. Error handling
5. GraphRAG integration (if available)
"""

import asyncio
from pathlib import Path
import tempfile
import json


async def example_basic_conversion():
    """Example 1: Basic file conversion."""
    print("=" * 60)
    print("Example 1: Basic File Conversion")
    print("=" * 60)
    
    from ipfs_datasets_py.processors.file_converter import FileConverter
    
    # Create a test file
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sample.txt"
        test_file.write_text("Hello from FileConverter!\nThis is a test document.")
        
        # Convert with auto backend selection
        converter = FileConverter()
        result = await converter.convert(test_file)
        
        if result.success:
            print(f"✓ Conversion successful!")
            print(f"  Backend used: {result.backend}")
            print(f"  Text length: {len(result.text)} characters")
            print(f"  Text preview: {result.text[:50]}...")
            print(f"  Metadata: {result.metadata}")
        else:
            print(f"✗ Conversion failed: {result.error}")
    
    print()


async def example_backend_selection():
    """Example 2: Explicit backend selection."""
    print("=" * 60)
    print("Example 2: Backend Selection")
    print("=" * 60)
    
    from ipfs_datasets_py.processors.file_converter import FileConverter
    
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "data.json"
        test_data = {"name": "FileConverter", "version": "0.1.0", "status": "active"}
        test_file.write_text(json.dumps(test_data, indent=2))
        
        # Try each backend
        backends = ['native', 'markitdown', 'omni']
        
        for backend_name in backends:
            try:
                converter = FileConverter(backend=backend_name)
                result = await converter.convert(test_file)
                
                if result.success:
                    print(f"✓ {backend_name:12} - Success ({len(result.text)} chars)")
                else:
                    print(f"✗ {backend_name:12} - Failed: {result.error[:50]}")
            except (ImportError, Exception) as e:
                print(f"⊗ {backend_name:12} - Not available: {str(e)[:50]}")
    
    print()


async def example_multiple_formats():
    """Example 3: Converting multiple file formats."""
    print("=" * 60)
    print("Example 3: Multiple File Formats")
    print("=" * 60)
    
    from ipfs_datasets_py.processors.file_converter import FileConverter
    
    converter = FileConverter()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create various file types
        files = {
            "sample.txt": "Plain text content",
            "document.md": "# Markdown\n\nWith **formatting**",
            "data.json": '{"key": "value"}',
            "table.csv": "name,age\nAlice,30\nBob,25",
            "page.html": "<html><body><h1>Title</h1></body></html>",
        }
        
        for filename, content in files.items():
            file_path = Path(tmpdir) / filename
            file_path.write_text(content)
        
        # Convert each file
        for filename in files.keys():
            file_path = Path(tmpdir) / filename
            result = await converter.convert(file_path)
            
            status = "✓" if result.success else "✗"
            print(f"{status} {filename:15} - {result.backend:10} - {len(result.text):4} chars")
    
    print()


async def example_batch_processing():
    """Example 4: Batch file processing."""
    print("=" * 60)
    print("Example 4: Batch Processing")
    print("=" * 60)
    
    from ipfs_datasets_py.processors.file_converter import FileConverter
    
    converter = FileConverter()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create multiple files
        files = []
        for i in range(10):
            file_path = Path(tmpdir) / f"document_{i:02d}.txt"
            file_path.write_text(f"Document {i}\n" + ("Content " * 10))
            files.append(file_path)
        
        print(f"Converting {len(files)} files in batch...")
        
        # Convert in batch with concurrency limit
        results = await converter.convert_batch(files, max_concurrent=3)
        
        # Summarize results
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        total_chars = sum(len(r.text) for r in results if r.success)
        
        print(f"✓ Successful: {successful}/{len(results)}")
        print(f"✗ Failed: {failed}/{len(results)}")
        print(f"📊 Total characters: {total_chars:,}")
    
    print()


async def example_sync_wrapper():
    """Example 5: Synchronous wrapper."""
    print("=" * 60)
    print("Example 5: Synchronous Wrapper")
    print("=" * 60)
    
    from ipfs_datasets_py.processors.file_converter import FileConverter
    
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sync_test.txt"
        test_file.write_text("Testing synchronous conversion")
        
        converter = FileConverter()
        
        # Use sync wrapper (no await needed)
        result = converter.convert_sync(test_file)
        
        if result.success:
            print(f"✓ Sync conversion successful!")
            print(f"  Text: {result.text}")
        else:
            print(f"✗ Sync conversion failed: {result.error}")
    
    print()


async def example_error_handling():
    """Example 6: Error handling."""
    print("=" * 60)
    print("Example 6: Error Handling")
    print("=" * 60)
    
    from ipfs_datasets_py.processors.file_converter import FileConverter
    
    converter = FileConverter(backend='native')
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Test various error conditions
        
        # 1. Nonexistent file
        result1 = await converter.convert(Path(tmpdir) / "nonexistent.txt")
        print(f"Nonexistent file: {'✓ Handled' if not result1.success else '✗ Unexpected success'}")
        print(f"  Error: {result1.error}")
        
        # 2. Unsupported format (for native backend)
        unsupported_file = Path(tmpdir) / "test.xyz"
        unsupported_file.write_text("content")
        result2 = await converter.convert(unsupported_file)
        print(f"Unsupported format: {'✓ Handled' if not result2.success else '✗ Unexpected success'}")
        print(f"  Error: {result2.error[:60]}...")
    
    print()


async def example_graphrag_integration():
    """Example 7: GraphRAG integration (if available)."""
    print("=" * 60)
    print("Example 7: GraphRAG Integration")
    print("=" * 60)
    
    try:
        from ipfs_datasets_py.processors.file_converter import FileConverter
        from ipfs_datasets_py.rag import GraphRAG
        
        print("GraphRAG available - demonstrating integration...")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create sample documents
            doc1 = Path(tmpdir) / "doc1.txt"
            doc1.write_text("Artificial Intelligence is transforming technology.")
            
            doc2 = Path(tmpdir) / "doc2.txt"
            doc2.write_text("Machine Learning is a subset of AI.")
            
            # Convert and add to knowledge graph
            converter = FileConverter()
            
            result1 = await converter.convert(doc1)
            result2 = await converter.convert(doc2)
            
            if result1.success and result2.success:
                print(f"✓ Converted {len([result1, result2])} documents")
                print(f"  Doc 1: {len(result1.text)} chars")
                print(f"  Doc 2: {len(result2.text)} chars")
                print("  Ready for GraphRAG processing")
                
                # Note: Actual GraphRAG integration would require initialization
                # graph = GraphRAG()
                # await graph.add_document(result1.text, metadata=result1.metadata)
                # await graph.add_document(result2.text, metadata=result2.metadata)
            else:
                print("✗ Conversion failed")
        
    except ImportError as e:
        print(f"⊗ GraphRAG not available: {e}")
    
    print()


async def example_backend_info():
    """Example 8: Getting backend information."""
    print("=" * 60)
    print("Example 8: Backend Information")
    print("=" * 60)
    
    from ipfs_datasets_py.processors.file_converter import FileConverter
    
    converter = FileConverter()
    
    # Get backend info
    info = converter.get_backend_info()
    print(f"Backend: {info['name']}")
    print(f"Type: {info['backend_type']}")
    print(f"Supported formats: {info['supported_formats']}")
    
    # Get format list
    formats = converter.get_supported_formats()
    print(f"\nFormats ({len(formats)}): {', '.join(formats[:15])}")
    if len(formats) > 15:
        print(f"             ... and {len(formats) - 15} more")
    
    print()


async def main():
    """Run all examples."""
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 10 + "FileConverter Usage Examples" + " " * 20 + "║")
    print("╚" + "═" * 58 + "╝")
    print()
    
    examples = [
        example_basic_conversion,
        example_backend_selection,
        example_multiple_formats,
        example_batch_processing,
        example_sync_wrapper,
        example_error_handling,
        example_backend_info,
        example_graphrag_integration,
    ]
    
    for example in examples:
        try:
            await example()
        except Exception as e:
            print(f"✗ Example failed: {e}")
            import traceback
            traceback.print_exc()
            print()
    
    print("=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
