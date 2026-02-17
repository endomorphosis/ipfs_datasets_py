"""
File Conversion - Convert Various Formats to Text

This example demonstrates how to convert various file formats (PDF, DOCX, PPTX,
TXT, HTML, etc.) to text using the FileConverter class. This is useful for
processing documents before embedding or analysis.

Requirements:
    - Core dependencies (already in ipfs_datasets_py)
    - Optional: pandoc, pypandoc for advanced conversions

Usage:
    python examples/04_file_conversion.py
"""

import asyncio
import tempfile
from pathlib import Path


def create_sample_files():
    """Create sample files for demonstration."""
    samples = {}
    
    # Create a text file
    txt_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    txt_file.write("This is a plain text document.\n")
    txt_file.write("It contains multiple lines of text.\n")
    txt_file.write("Plain text is the simplest format.")
    txt_file.close()
    samples['txt'] = txt_file.name
    
    # Create a markdown file
    md_file = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False)
    md_file.write("# Markdown Document\n\n")
    md_file.write("This is a **markdown** file with:\n\n")
    md_file.write("- Bullet points\n")
    md_file.write("- *Italic text*\n")
    md_file.write("- **Bold text**\n\n")
    md_file.write("## Code Example\n\n")
    md_file.write("```python\nprint('Hello, World!')\n```")
    md_file.close()
    samples['md'] = md_file.name
    
    # Create a JSON file
    json_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json_file.write('{\n')
    json_file.write('  "title": "Sample JSON",\n')
    json_file.write('  "description": "This is a JSON document",\n')
    json_file.write('  "items": ["item1", "item2", "item3"],\n')
    json_file.write('  "nested": {"key": "value"}\n')
    json_file.write('}')
    json_file.close()
    samples['json'] = json_file.name
    
    # Create a CSV file
    csv_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
    csv_file.write("name,age,city\n")
    csv_file.write("Alice,30,New York\n")
    csv_file.write("Bob,25,Los Angeles\n")
    csv_file.write("Charlie,35,Chicago\n")
    csv_file.close()
    samples['csv'] = csv_file.name
    
    # Create an HTML file
    html_file = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
    html_file.write("<html><head><title>Sample HTML</title></head>\n")
    html_file.write("<body>\n")
    html_file.write("  <h1>HTML Document</h1>\n")
    html_file.write("  <p>This is a paragraph with <strong>bold</strong> text.</p>\n")
    html_file.write("  <ul><li>Item 1</li><li>Item 2</li></ul>\n")
    html_file.write("</body></html>")
    html_file.close()
    samples['html'] = html_file.name
    
    return samples


async def demo_basic_conversion():
    """Demonstrate basic file conversion."""
    print("\n" + "="*70)
    print("DEMO 1: Basic File Conversion")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.file_converter import FileConverter
        
        # Create sample files
        print("\n📝 Creating sample files...")
        samples = create_sample_files()
        
        # Initialize converter
        converter = FileConverter()
        
        # Convert each file
        for file_type, file_path in samples.items():
            print(f"\n🔄 Converting {file_type.upper()} file...")
            try:
                result = await converter.convert(file_path, target_format='txt')
                
                if result.success:
                    print(f"   ✅ Conversion successful")
                    print(f"   Source format: {result.source_format}")
                    print(f"   Output length: {len(result.content)} chars")
                    print(f"   Preview: {result.content[:100]}...")
                else:
                    print(f"   ❌ Conversion failed: {result.error}")
                    
            except Exception as e:
                print(f"   ❌ Error: {e}")
        
        # Cleanup
        import os
        for path in samples.values():
            try:
                os.unlink(path)
            except:
                pass
        
    except ImportError as e:
        print(f"\n❌ Missing dependencies: {e}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def demo_metadata_extraction():
    """Demonstrate metadata extraction during conversion."""
    print("\n" + "="*70)
    print("DEMO 2: Metadata Extraction")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.file_converter import (
            FileConverter,
            MetadataExtractor
        )
        
        # Create a sample file
        txt_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        txt_file.write("Sample document with metadata.\n" * 10)
        txt_file.close()
        
        print(f"\n📄 Extracting metadata from: {txt_file.name}")
        
        # Extract metadata
        extractor = MetadataExtractor()
        metadata = await extractor.extract(txt_file.name)
        
        print("\n📊 Extracted Metadata:")
        print(f"   File size: {metadata.get('size_bytes', 0)} bytes")
        print(f"   MIME type: {metadata.get('mime_type', 'unknown')}")
        print(f"   Created: {metadata.get('created', 'unknown')}")
        print(f"   Modified: {metadata.get('modified', 'unknown')}")
        
        if 'content_metadata' in metadata:
            content_meta = metadata['content_metadata']
            print(f"\n   Content Metadata:")
            print(f"   - Character count: {content_meta.get('char_count', 0)}")
            print(f"   - Word count: {content_meta.get('word_count', 0)}")
            print(f"   - Line count: {content_meta.get('line_count', 0)}")
        
        # Cleanup
        import os
        os.unlink(txt_file.name)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def demo_batch_conversion():
    """Demonstrate batch file conversion."""
    print("\n" + "="*70)
    print("DEMO 3: Batch File Conversion")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.file_converter import (
            BatchProcessor,
            ResourceLimits
        )
        
        # Create multiple sample files
        print("\n📝 Creating sample files for batch processing...")
        samples = create_sample_files()
        file_paths = list(samples.values())
        
        print(f"   Created {len(file_paths)} files")
        
        # Setup batch processor with resource limits
        limits = ResourceLimits(
            max_memory_mb=512,
            max_concurrent=3,
            timeout_seconds=30
        )
        
        print("\n🔄 Starting batch conversion...")
        processor = BatchProcessor(resource_limits=limits)
        
        # Process all files
        results = await processor.process_batch(
            file_paths,
            target_format='txt'
        )
        
        # Display results
        print("\n📊 Batch Processing Results:")
        successful = sum(1 for r in results if r.success)
        print(f"   Total files: {len(results)}")
        print(f"   Successful: {successful}")
        print(f"   Failed: {len(results) - successful}")
        
        # Show details
        print("\n   Details:")
        for i, result in enumerate(results, 1):
            status = "✅" if result.success else "❌"
            print(f"   {status} File {i}: {result.source_format} -> {len(result.content) if result.success else 0} chars")
        
        # Cleanup
        import os
        for path in file_paths:
            try:
                os.unlink(path)
            except:
                pass
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def demo_format_detection():
    """Demonstrate automatic format detection."""
    print("\n" + "="*70)
    print("DEMO 4: Automatic Format Detection")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.file_converter import FileConverter
        
        samples = create_sample_files()
        converter = FileConverter()
        
        print("\n🔍 Detecting file formats...")
        for file_type, file_path in samples.items():
            # Detect without extension hint
            detected = await converter.detect_format(file_path)
            print(f"   {file_type.upper():8s} -> Detected as: {detected}")
        
        # Cleanup
        import os
        for path in samples.values():
            try:
                os.unlink(path)
            except:
                pass
        
    except Exception as e:
        print(f"\n❌ Error: {e}")


async def demo_url_download_convert():
    """Demonstrate downloading and converting from URL."""
    print("\n" + "="*70)
    print("DEMO 5: Download and Convert from URL")
    print("="*70)
    
    print("\n📥 URL download and conversion example")
    print("   (Requires network access)")
    
    # Example code (commented out as it requires network access)
    """
    try:
        from ipfs_datasets_py.processors.file_converter import FileConverter
        
        converter = FileConverter()
        
        # Download and convert a web page
        url = "https://example.com"
        result = await converter.convert_url(url, target_format='txt')
        
        if result.success:
            print(f"   ✅ Downloaded and converted {url}")
            print(f"   Content length: {len(result.content)} chars")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
    """
    
    print("\n   💡 Tip: Use converter.convert_url(url, target_format='txt')")
    print("   to download and convert web pages")


def show_supported_formats():
    """Show supported file formats."""
    print("\n" + "="*70)
    print("SUPPORTED FILE FORMATS")
    print("="*70)
    
    formats = {
        "Text-based": ["txt", "md", "rst", "tex"],
        "Documents": ["pdf", "docx", "odt", "rtf", "epub"],
        "Presentations": ["pptx", "odp"],
        "Spreadsheets": ["xlsx", "ods", "csv"],
        "Web": ["html", "xml", "json", "yaml"],
        "Archives": ["zip", "tar", "gz", "7z"],
        "Code": ["py", "js", "java", "cpp", "go"],
    }
    
    for category, exts in formats.items():
        print(f"\n{category}:")
        print(f"   {', '.join(exts)}")


def show_tips():
    """Show tips for file conversion."""
    print("\n" + "="*70)
    print("TIPS FOR FILE CONVERSION")
    print("="*70)
    
    print("\n1. Large Files:")
    print("   - Use BatchProcessor with ResourceLimits")
    print("   - Set appropriate timeout values")
    print("   - Monitor memory usage")
    
    print("\n2. PDFs:")
    print("   - Text PDFs convert quickly")
    print("   - Image PDFs require OCR (see 07_pdf_processing.py)")
    print("   - Consider using PyMuPDF for better quality")
    
    print("\n3. Office Documents:")
    print("   - Install pandoc for best results")
    print("   - DOCX/PPTX conversion preserves structure")
    print("   - Use metadata extraction for document properties")
    
    print("\n4. Error Handling:")
    print("   - Always check result.success before using content")
    print("   - Log conversion errors for debugging")
    print("   - Implement fallback strategies for critical files")
    
    print("\n5. Next Steps:")
    print("   - See 07_pdf_processing.py for advanced PDF handling")
    print("   - See 09_batch_processing.py for large-scale processing")


async def main():
    """Run all file conversion demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - FILE CONVERSION")
    print("="*70)
    
    await demo_basic_conversion()
    await demo_metadata_extraction()
    await demo_batch_conversion()
    await demo_format_detection()
    await demo_url_download_convert()
    
    show_supported_formats()
    show_tips()
    
    print("\n" + "="*70)
    print("✅ FILE CONVERSION EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
