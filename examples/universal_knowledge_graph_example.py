"""
Universal Knowledge Graph Example

Demonstrates how to generate knowledge graphs and text summaries from ANY file format
using the integrated file_converter → knowledge graph → RAG pipeline.

This example shows:
1. Converting arbitrary files to text
2. Extracting knowledge graphs
3. Generating text summaries
4. Storing in IPFS (optional)
5. Batch processing multiple files
"""

import asyncio
from pathlib import Path
import tempfile
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import the integrated pipeline
from ipfs_datasets_py.processors.file_converter import (
    UniversalKnowledgeGraphPipeline,
    TextSummarizationPipeline,
    BatchKnowledgeGraphProcessor,
)


async def demo_1_single_file_knowledge_graph():
    """Demo 1: Extract knowledge graph from a single file."""
    print("\n" + "=" * 80)
    print("Demo 1: Single File Knowledge Graph Extraction")
    print("=" * 80)

    # Create a test file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("""
        Alice is a software engineer at TechCorp. She works with Bob, who is the team lead.
        Together they built a knowledge graph system using Python and IPFS.
        The system can process PDF, DOCX, and other file formats.
        TechCorp is headquartered in San Francisco and has offices in New York and London.
        Alice graduated from MIT in 2015 with a degree in Computer Science.
        """)
        test_file = f.name

    try:
        # Initialize pipeline
        print("\n📊 Initializing Universal Knowledge Graph Pipeline...")
        pipeline = UniversalKnowledgeGraphPipeline(
            backend="native",
            enable_ipfs=False,  # Set to True if you have IPFS running
            enable_acceleration=False,
        )

        # Process the file
        print(f"📄 Processing file: {test_file}")
        result = await pipeline.process(test_file, generate_summary=True)

        if result.success:
            print("\n✅ Processing successful!")
            print(f"\n📝 Text extracted ({len(result.text)} characters):")
            print(f"   {result.text[:200]}...")

            print(f"\n👥 Entities found: {len(result.entities)}")
            for i, entity in enumerate(result.entities[:5], 1):
                print(f"   {i}. {entity}")

            print(f"\n🔗 Relationships found: {len(result.relationships)}")
            for i, rel in enumerate(result.relationships[:5], 1):
                print(f"   {i}. {rel}")

            if result.summary:
                print(f"\n📋 Summary:\n   {result.summary}")

            if result.ipfs_cid:
                print(f"\n🌐 IPFS CID: {result.ipfs_cid}")
        else:
            print(f"\n❌ Processing failed: {result.error}")

    finally:
        # Cleanup
        Path(test_file).unlink(missing_ok=True)


async def demo_2_text_summarization():
    """Demo 2: Generate text summary from a file."""
    print("\n" + "=" * 80)
    print("Demo 2: Text Summarization")
    print("=" * 80)

    # Create a longer test document
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("""
        The rise of artificial intelligence has transformed many industries.
        Machine learning algorithms can now process vast amounts of data,
        identifying patterns and making predictions that were previously impossible.
        
        Natural language processing has enabled computers to understand human language,
        powering applications like chatbots, translation services, and content analysis.
        Computer vision allows machines to interpret images and videos,
        with applications in autonomous vehicles, medical diagnosis, and security systems.
        
        Deep learning, a subset of machine learning, uses neural networks with multiple layers
        to learn complex representations of data. This has led to breakthroughs in
        speech recognition, image classification, and game playing.
        
        However, AI also raises important ethical questions about bias, privacy,
        and the impact on employment. As AI systems become more powerful,
        it's crucial to develop them responsibly and ensure they benefit society as a whole.
        """)
        test_file = f.name

    try:
        # Initialize summarization pipeline
        print("\n📝 Initializing Text Summarization Pipeline...")
        pipeline = TextSummarizationPipeline(
            backend="native", enable_ipfs=False, max_summary_length=200
        )

        # Summarize the file
        print(f"📄 Summarizing file: {test_file}")
        result = await pipeline.summarize(test_file)

        if result.success:
            print("\n✅ Summarization successful!")
            print(f"\n📝 Original text ({len(result.text)} characters)")
            print(f"\n📋 Summary ({len(result.summary)} characters):")
            print(f"   {result.summary}")

            if result.entities:
                print(f"\n🏷️ Key entities: {', '.join(result.entities[:10])}")

            if result.ipfs_cid:
                print(f"\n🌐 IPFS CID: {result.ipfs_cid}")
        else:
            print(f"\n❌ Summarization failed: {result.error}")

    finally:
        # Cleanup
        Path(test_file).unlink(missing_ok=True)


async def demo_3_batch_processing():
    """Demo 3: Batch process multiple files."""
    print("\n" + "=" * 80)
    print("Demo 3: Batch Processing Multiple Files")
    print("=" * 80)

    # Create multiple test files
    test_files = []
    test_data = [
        (
            "Climate change is causing global temperatures to rise. "
            "Scientists predict more extreme weather events in the coming decades."
        ),
        (
            "The stock market experienced significant volatility today. "
            "Tech stocks led the decline while energy sectors gained."
        ),
        (
            "A new medical breakthrough offers hope for cancer patients. "
            "The treatment uses gene editing technology to target tumors."
        ),
    ]

    for i, content in enumerate(test_data, 1):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(content)
            test_files.append(f.name)

    try:
        # Initialize batch processor
        print("\n📦 Initializing Batch Knowledge Graph Processor...")
        processor = BatchKnowledgeGraphProcessor(
            backend="native", enable_ipfs=False, max_concurrent=3
        )

        # Progress callback
        def on_progress(completed, total, success):
            status = "✅" if success else "❌"
            print(f"   Progress: {status} {completed}/{total} files processed")

        # Process all files
        print(f"\n📄 Processing {len(test_files)} files...")
        results = await processor.process_batch(
            test_files, progress_callback=on_progress, generate_summary=True
        )

        # Display results
        print(f"\n✅ Batch processing complete!")
        successful = sum(1 for r in results if r.success)
        print(f"\n📊 Results: {successful}/{len(results)} files processed successfully")

        for i, result in enumerate(results, 1):
            if result.success:
                print(f"\n   File {i}:")
                print(f"   - Entities: {len(result.entities)}")
                print(f"   - Relationships: {len(result.relationships)}")
                if result.summary:
                    print(f"   - Summary: {result.summary[:100]}...")

    finally:
        # Cleanup
        for file_path in test_files:
            Path(file_path).unlink(missing_ok=True)


async def demo_4_with_ipfs_acceleration():
    """Demo 4: Using IPFS storage and ML acceleration."""
    print("\n" + "=" * 80)
    print("Demo 4: IPFS Storage and ML Acceleration")
    print("=" * 80)

    # Create test file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("""
        Quantum computing represents a paradigm shift in computational power.
        Unlike classical computers that use bits, quantum computers use qubits
        that can exist in multiple states simultaneously through superposition.
        This enables quantum computers to solve certain problems exponentially faster
        than classical computers, with applications in cryptography, drug discovery,
        and optimization problems.
        """)
        test_file = f.name

    try:
        # Initialize with IPFS and acceleration
        print("\n🚀 Initializing pipeline with IPFS and acceleration...")
        print("   Note: Requires ipfs_kit_py and ipfs_accelerate_py")

        pipeline = UniversalKnowledgeGraphPipeline(
            backend="native",
            enable_ipfs=True,  # Enable IPFS storage
            enable_acceleration=True,  # Enable ML acceleration
            enable_rag=False,  # Enable RAG integration if desired
        )

        # Process with IPFS storage
        print(f"\n📄 Processing file with IPFS storage...")
        result = await pipeline.process(test_file, store_on_ipfs=True, generate_summary=True)

        if result.success:
            print("\n✅ Processing successful!")
            print(f"\n📝 Text: {result.text[:100]}...")
            print(f"\n👥 Entities: {len(result.entities)}")
            print(f"🔗 Relationships: {len(result.relationships)}")

            if result.ipfs_cid:
                print(f"\n🌐 Text stored on IPFS:")
                print(f"   CID: {result.ipfs_cid}")
                print(f"   Gateway: https://ipfs.io/ipfs/{result.ipfs_cid}")

            if result.ipfs_graph_cid:
                print(f"\n🌐 Knowledge graph stored on IPFS:")
                print(f"   CID: {result.ipfs_graph_cid}")

            if result.metadata:
                print(f"\n📊 Metadata:")
                for key, value in list(result.metadata.items())[:5]:
                    print(f"   - {key}: {value}")
        else:
            print(f"\n⚠️ Processing completed with warnings: {result.error}")
            print("   This is expected if IPFS/acceleration packages are not installed")

    finally:
        # Cleanup
        Path(test_file).unlink(missing_ok=True)


async def demo_5_real_world_workflow():
    """Demo 5: Complete real-world workflow."""
    print("\n" + "=" * 80)
    print("Demo 5: Complete Real-World Workflow")
    print("=" * 80)

    print("\n🔄 Complete Workflow: File → Text → Knowledge Graph → Summary → Query")
    print("\nThis demonstrates the full pipeline:")
    print("1. Convert any file format to text (PDF, DOCX, etc.)")
    print("2. Extract entities and relationships (knowledge graph)")
    print("3. Generate summary")
    print("4. Store in IPFS for distributed access")
    print("5. Enable RAG querying")

    # Create a comprehensive test document
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("""
# Machine Learning Research Report

## Abstract
This report examines recent advances in machine learning, focusing on
transformer architectures and their applications in natural language processing.

## Introduction
Machine learning has revolutionized artificial intelligence. Deep learning models,
particularly transformers introduced by Vaswani et al. in 2017, have achieved
state-of-the-art results across multiple domains.

## Key Contributors
- Vaswani et al. - Introduced the Transformer architecture
- Devlin et al. - Developed BERT
- Brown et al. - Created GPT-3

## Applications
1. Natural Language Processing
2. Computer Vision
3. Speech Recognition
4. Recommendation Systems

## Conclusion
The future of AI lies in developing more efficient and interpretable models
that can benefit society while addressing ethical concerns.
        """)
        test_file = f.name

    try:
        # Initialize comprehensive pipeline
        print("\n🚀 Initializing comprehensive pipeline...")
        kg_pipeline = UniversalKnowledgeGraphPipeline(
            backend="native", enable_ipfs=False, enable_acceleration=False, enable_rag=False
        )

        summary_pipeline = TextSummarizationPipeline(
            backend="native", enable_ipfs=False, max_summary_length=300
        )

        # Step 1: Extract knowledge graph
        print("\n📊 Step 1: Extracting knowledge graph...")
        kg_result = await kg_pipeline.process(test_file, generate_summary=False)

        if kg_result.success:
            print(f"   ✅ Extracted {len(kg_result.entities)} entities")
            print(f"   ✅ Extracted {len(kg_result.relationships)} relationships")

        # Step 2: Generate summary
        print("\n📝 Step 2: Generating summary...")
        summary_result = await summary_pipeline.summarize(test_file)

        if summary_result.success:
            print(f"   ✅ Summary generated ({len(summary_result.summary)} chars)")

        # Display combined results
        print("\n" + "=" * 80)
        print("FINAL RESULTS")
        print("=" * 80)

        print("\n📋 Summary:")
        print(f"   {summary_result.summary}")

        print("\n👥 Key People & Organizations:")
        if kg_result.entities:
            for entity in kg_result.entities[:5]:
                print(f"   - {entity}")

        print("\n🔗 Key Relationships:")
        if kg_result.relationships:
            for rel in kg_result.relationships[:5]:
                print(f"   - {rel}")

        print("\n💡 Next Steps:")
        print("   - Store knowledge graph in graph database")
        print("   - Create vector embeddings for RAG")
        print("   - Enable semantic search and querying")
        print("   - Build knowledge graph visualization")

    finally:
        # Cleanup
        Path(test_file).unlink(missing_ok=True)


async def main():
    """Run all demos."""
    print("\n" + "=" * 80)
    print("UNIVERSAL KNOWLEDGE GRAPH & TEXT SUMMARIZATION DEMO")
    print("=" * 80)
    print("\nDemonstrating file_converter integration with knowledge graphs and RAG")
    print("Supporting ANY file format: PDF, DOCX, TXT, MD, HTML, and more!")

    try:
        await demo_1_single_file_knowledge_graph()
        await demo_2_text_summarization()
        await demo_3_batch_processing()
        await demo_4_with_ipfs_acceleration()
        await demo_5_real_world_workflow()

        print("\n" + "=" * 80)
        print("✅ ALL DEMOS COMPLETE!")
        print("=" * 80)
        print("\n💡 Key Takeaways:")
        print("   • Any file format → Text extraction")
        print("   • Text → Knowledge graph (entities + relationships)")
        print("   • Text → Summaries")
        print("   • Optional IPFS storage for distributed access")
        print("   • Optional ML acceleration for performance")
        print("   • Batch processing for multiple files")
        print("   • Ready for RAG integration")

        print("\n📚 Documentation:")
        print("   • See docs/FILE_CONVERSION_INTEGRATION_PLAN.md")
        print("   • See docs/COMPLETE_FEATURE_PARITY_ANALYSIS.md")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
