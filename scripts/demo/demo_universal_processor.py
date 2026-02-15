#!/usr/bin/env python3
"""
Demo: Universal Processor - Single Entrypoint for All Processing

This script demonstrates the new UniversalProcessor that provides a single,
unified API for processing URLs, files, and folders with automatic routing
to specialized processors.

Usage:
    python demo_universal_processor.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ipfs_datasets_py.processors import (
    UniversalProcessor,
    ProcessorConfig,
    ProcessingResult,
    InputType
)


async def demo_basic_usage():
    """Demonstrate basic usage of UniversalProcessor."""
    print("=" * 80)
    print("DEMO: Universal Processor - Single Entrypoint")
    print("=" * 80)
    print()
    
    # Create processor
    print("1. Creating UniversalProcessor...")
    processor = UniversalProcessor()
    print(f"   ✓ Processor created with {len(processor.registry)} registered processors")
    print()
    
    # List available processors
    print("2. Available Processors:")
    processors_info = processor.list_processors()
    for name, details in processors_info.items():
        print(f"   • {name}")
        print(f"     Types: {', '.join(details['types'])}")
        print(f"     Priority: {details['priority']}")
    print()
    
    return processor


async def demo_input_detection(processor):
    """Demonstrate automatic input type detection."""
    print("=" * 80)
    print("DEMO: Automatic Input Type Detection")
    print("=" * 80)
    print()
    
    test_inputs = [
        "https://example.com",
        "document.pdf",
        "video.mp4",
        "/path/to/folder",
        "QmTest123...",  # IPFS CID
    ]
    
    for input_source in test_inputs:
        from ipfs_datasets_py.processors.input_detection import classify_input
        classification = classify_input(input_source)
        
        print(f"Input: {input_source}")
        print(f"  Type: {classification['input_type'].value}")
        print(f"  File Type: {classification.get('file_type', 'N/A')}")
        print(f"  Suggested Processors: {', '.join(classification['suggested_processors'])}")
        print()


async def demo_pdf_processing(processor):
    """Demonstrate PDF processing (simulated)."""
    print("=" * 80)
    print("DEMO: PDF Processing")
    print("=" * 80)
    print()
    
    # Note: This is simulated since we don't have actual files
    print("Example: processor.process('document.pdf')")
    print()
    print("Expected behavior:")
    print("  1. Input detection identifies it as a PDF file")
    print("  2. PDFProcessorAdapter is selected")
    print("  3. PDF content is extracted")
    print("  4. Knowledge graph is built with document entities")
    print("  5. Vector embeddings are generated")
    print("  6. Standardized ProcessingResult is returned")
    print()
    
    # Show what the result would look like
    print("Result structure:")
    print("  ProcessingResult(")
    print("    knowledge_graph=KnowledgeGraph(")
    print("      entities=[Entity(type='PDFDocument', label='document.pdf'), ...]")
    print("      relationships=[...]")
    print("    ),")
    print("    vectors=VectorStore(embeddings={...}),")
    print("    content={'text': '...', 'metadata': {...}},")
    print("    metadata=ProcessingMetadata(...)")
    print("  )")
    print()


async def demo_url_processing(processor):
    """Demonstrate URL processing (simulated)."""
    print("=" * 80)
    print("DEMO: URL/Website Processing (GraphRAG)")
    print("=" * 80)
    print()
    
    print("Example: processor.process('https://example.com/article')")
    print()
    print("Expected behavior:")
    print("  1. Input detection identifies it as a URL")
    print("  2. GraphRAGProcessorAdapter is selected")
    print("  3. Web page is fetched and parsed")
    print("  4. Entities and relationships are extracted")
    print("  5. Knowledge graph is constructed")
    print("  6. Vector embeddings are generated from content")
    print()
    
    print("Knowledge Graph Output:")
    print("  Entities:")
    print("    • WebPage: 'Example Article'")
    print("    • Person: 'John Doe' (author)")
    print("    • Organization: 'ACME Corp' (mentioned)")
    print("    • Concept: 'Machine Learning' (topic)")
    print()
    print("  Relationships:")
    print("    • (John Doe) --[AUTHORED]--> (Example Article)")
    print("    • (Example Article) --[MENTIONS]--> (ACME Corp)")
    print("    • (Example Article) --[ABOUT]--> (Machine Learning)")
    print()


async def demo_batch_processing(processor):
    """Demonstrate batch processing."""
    print("=" * 80)
    print("DEMO: Batch Processing")
    print("=" * 80)
    print()
    
    print("Example: processor.process([")
    print("  'doc1.pdf',")
    print("  'doc2.pdf',")
    print("  'https://example.com',")
    print("  'video.mp4'")
    print("])")
    print()
    print("Expected behavior:")
    print("  1. Each input is processed by appropriate processor")
    print("  2. Processing can be parallelized (future)")
    print("  3. Results are collected")
    print("  4. Errors are isolated (one failure doesn't stop others)")
    print("  5. BatchProcessingResult is returned")
    print()
    
    print("BatchProcessingResult structure:")
    print("  results: [ProcessingResult, ProcessingResult, ...]")
    print("  errors: [('input', 'error_message'), ...]")
    print("  metadata: {")
    print("    'total_inputs': 4,")
    print("    'successful': 3,")
    print("    'failed': 1,")
    print("    'success_rate': 0.75")
    print("  }")
    print()


async def demo_statistics(processor):
    """Demonstrate statistics and monitoring."""
    print("=" * 80)
    print("DEMO: Statistics and Monitoring")
    print("=" * 80)
    print()
    
    stats = processor.get_statistics()
    
    print("Processor Statistics:")
    print(f"  Total calls: {stats['total_calls']}")
    print(f"  Successful: {stats['successful_calls']}")
    print(f"  Failed: {stats['failed_calls']}")
    print(f"  Cache hits: {stats['cache_hits']}")
    print(f"  Total processing time: {stats['total_processing_time']:.2f}s")
    print(f"  Average processing time: {stats['average_processing_time']:.2f}s")
    print(f"  Success rate: {stats['success_rate']:.1%}")
    print()
    
    print("Per-processor statistics:")
    for proc_name, proc_stats in stats.get('processor_stats', {}).items():
        if proc_stats.get('calls', 0) > 0:
            print(f"  {proc_name}:")
            print(f"    Calls: {proc_stats['calls']}")
            print(f"    Successes: {proc_stats['successes']}")
            print(f"    Failures: {proc_stats['failures']}")
    print()


async def demo_configuration():
    """Demonstrate processor configuration."""
    print("=" * 80)
    print("DEMO: Processor Configuration")
    print("=" * 80)
    print()
    
    print("ProcessorConfig options:")
    print()
    
    print("1. Basic configuration:")
    print("   config = ProcessorConfig(")
    print("       enable_caching=True,")
    print("       parallel_workers=4,")
    print("       timeout_seconds=300")
    print("   )")
    print()
    
    print("2. Manual routing:")
    print("   config = ProcessorConfig(")
    print("       preferred_processors={")
    print("           '.pdf': 'PDFProcessor',")
    print("           'youtube.com': 'MultimediaProcessor'")
    print("       }")
    print("   )")
    print()
    
    print("3. Error handling:")
    print("   config = ProcessorConfig(")
    print("       fallback_enabled=True,")
    print("       max_retries=2,")
    print("       raise_on_error=False")
    print("   )")
    print()


async def demo_comparison():
    """Show comparison: Old vs New API."""
    print("=" * 80)
    print("COMPARISON: Old API vs New API")
    print("=" * 80)
    print()
    
    print("OLD API (Before Refactoring):")
    print("-" * 40)
    print("from ipfs_datasets_py.processors.pdf_processor import PDFProcessor")
    print("from ipfs_datasets_py.processors.website_graphrag_processor import WebsiteGraphRAGProcessor")
    print("from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper")
    print()
    print("# Different imports, different APIs")
    print("pdf_proc = PDFProcessor()")
    print("result1 = await pdf_proc.process_pdf('doc.pdf')")
    print()
    print("web_proc = WebsiteGraphRAGProcessor()")
    print("result2 = await web_proc.process_website('https://example.com')")
    print()
    print("ffmpeg = FFmpegWrapper()")
    print("result3 = await ffmpeg.convert('video.mp4')")
    print()
    print("# Different result formats!")
    print()
    print()
    
    print("NEW API (After Refactoring):")
    print("-" * 40)
    print("from ipfs_datasets_py.processors import UniversalProcessor")
    print()
    print("# Single import, single API")
    print("processor = UniversalProcessor()")
    print()
    print("# Automatic routing")
    print("result1 = await processor.process('doc.pdf')")
    print("result2 = await processor.process('https://example.com')")
    print("result3 = await processor.process('video.mp4')")
    print()
    print("# All results have the same format:")
    print("# - result.knowledge_graph")
    print("# - result.vectors")
    print("# - result.content")
    print("# - result.metadata")
    print()
    print("Benefits:")
    print("  ✓ Single import")
    print("  ✓ Consistent API")
    print("  ✓ Automatic routing")
    print("  ✓ Standardized output")
    print("  ✓ Easy to use")
    print()


async def main():
    """Run all demos."""
    print()
    print("╔═══════════════════════════════════════════════════════════════════════════════╗")
    print("║                                                                               ║")
    print("║         UNIVERSAL PROCESSOR - COMPREHENSIVE DEMO                             ║")
    print("║                                                                               ║")
    print("║   Single entrypoint for URLs, files, and folders                             ║")
    print("║   Automatic routing to specialized processors                                ║")
    print("║   Standardized knowledge graphs + vectors output                             ║")
    print("║                                                                               ║")
    print("╚═══════════════════════════════════════════════════════════════════════════════╝")
    print()
    
    try:
        # Run demos
        processor = await demo_basic_usage()
        await demo_input_detection(processor)
        await demo_pdf_processing(processor)
        await demo_url_processing(processor)
        await demo_batch_processing(processor)
        await demo_statistics(processor)
        await demo_configuration()
        await demo_comparison()
        
        print("=" * 80)
        print("DEMO COMPLETE")
        print("=" * 80)
        print()
        print("Next Steps:")
        print("  1. Review the comprehensive refactoring plan:")
        print("     docs/PROCESSORS_REFACTORING_PLAN.md")
        print()
        print("  2. Check the quick reference:")
        print("     docs/PROCESSORS_QUICK_REFERENCE.md")
        print()
        print("  3. Try the processor with real files:")
        print("     from ipfs_datasets_py.processors import UniversalProcessor")
        print("     processor = UniversalProcessor()")
        print("     result = await processor.process('your_file.pdf')")
        print()
        
    except Exception as e:
        print(f"Error running demo: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
