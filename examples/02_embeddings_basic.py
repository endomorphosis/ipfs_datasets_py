"""
Basic Text Embeddings with IPFS Datasets Python

This example demonstrates how to generate text embeddings using the IPFSEmbeddings
class and various embedding models. Embeddings are vector representations of text
that capture semantic meaning.

Requirements:
    - transformers library: pip install transformers
    - torch: pip install torch
    - sentence-transformers models (auto-downloaded)

Usage:
    python examples/02_embeddings_basic.py
"""

import asyncio
import sys
from pathlib import Path


async def demo_basic_embedding_generation():
    """Generate embeddings for simple text."""
    print("\n" + "="*70)
    print("DEMO 1: Basic Embedding Generation")
    print("="*70)
    
    try:
        from ipfs_datasets_py.ml.embeddings.ipfs_embeddings import IPFSEmbeddings
        
        # Initialize with a lightweight model
        print("\n📦 Initializing IPFSEmbeddings with 'all-MiniLM-L6-v2' model...")
        embedder = IPFSEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        
        # Generate embeddings for sample texts
        texts = [
            "The quick brown fox jumps over the lazy dog.",
            "Machine learning is a subset of artificial intelligence.",
            "Python is a popular programming language.",
        ]
        
        print("\n📝 Generating embeddings for sample texts...")
        embeddings = await embedder.generate_embeddings(texts)
        
        print(f"\n✅ Generated {len(embeddings)} embeddings")
        print(f"   Embedding dimension: {len(embeddings[0])}")
        print(f"   First embedding (first 5 values): {embeddings[0][:5]}")
        
        return embeddings
        
    except ImportError as e:
        print(f"\n❌ Missing dependencies: {e}")
        print("   Install with: pip install transformers torch")
        return None
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return None


async def demo_different_models():
    """Compare different embedding models."""
    print("\n" + "="*70)
    print("DEMO 2: Comparing Different Models")
    print("="*70)
    
    try:
        from ipfs_datasets_py.ml.embeddings.ipfs_embeddings import IPFSEmbeddings
        
        # Try different models (from smallest to larger)
        models = [
            "sentence-transformers/all-MiniLM-L6-v2",  # Fast, 384 dims
            # "sentence-transformers/all-mpnet-base-v2",  # Better quality, 768 dims
        ]
        
        sample_text = "Artificial intelligence is transforming the world."
        
        for model_name in models:
            print(f"\n🔄 Testing model: {model_name}")
            try:
                embedder = IPFSEmbeddings(model_name=model_name)
                embeddings = await embedder.generate_embeddings([sample_text])
                print(f"   ✅ Embedding dimension: {len(embeddings[0])}")
            except Exception as e:
                print(f"   ❌ Error with {model_name}: {e}")
        
    except ImportError as e:
        print(f"\n❌ Missing dependencies: {e}")


async def demo_semantic_similarity():
    """Demonstrate semantic similarity between texts."""
    print("\n" + "="*70)
    print("DEMO 3: Semantic Similarity")
    print("="*70)
    
    try:
        from ipfs_datasets_py.ml.embeddings.ipfs_embeddings import IPFSEmbeddings
        import numpy as np
        
        embedder = IPFSEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        
        # Create semantically related and unrelated texts
        texts = [
            "Dogs are loyal pets.",                    # Reference
            "Canines make faithful companions.",       # Similar to #1
            "Python is a programming language.",       # Different topic
            "Puppies are adorable animals.",           # Related to #1
        ]
        
        print("\n📝 Comparing texts for semantic similarity...")
        embeddings = await embedder.generate_embeddings(texts)
        
        # Calculate cosine similarity
        def cosine_similarity(a, b):
            return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
        
        reference = embeddings[0]
        print(f"\nReference text: '{texts[0]}'")
        print("Similarity scores:")
        
        for i, (text, emb) in enumerate(zip(texts[1:], embeddings[1:]), 1):
            similarity = cosine_similarity(reference, emb)
            print(f"  {i}. '{text}'")
            print(f"     Similarity: {similarity:.4f}")
        
        print("\n💡 Note: Higher scores (closer to 1.0) indicate more semantic similarity")
        
    except ImportError as e:
        print(f"\n❌ Missing numpy: {e}")
        print("   Install with: pip install numpy")
    except Exception as e:
        print(f"\n❌ Error: {e}")


async def demo_batch_processing():
    """Demonstrate batch processing of embeddings."""
    print("\n" + "="*70)
    print("DEMO 4: Batch Processing")
    print("="*70)
    
    try:
        from ipfs_datasets_py.ml.embeddings.ipfs_embeddings import IPFSEmbeddings
        
        embedder = IPFSEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        
        # Generate a larger batch of texts
        texts = [f"This is sample text number {i}" for i in range(20)]
        
        print(f"\n📦 Processing {len(texts)} texts in batch...")
        embeddings = await embedder.generate_embeddings(texts)
        
        print(f"✅ Generated {len(embeddings)} embeddings")
        print(f"   Total embedding vectors: {len(embeddings)}")
        print(f"   Dimension per vector: {len(embeddings[0])}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")


async def demo_chunking_strategies():
    """Demonstrate different text chunking strategies."""
    print("\n" + "="*70)
    print("DEMO 5: Text Chunking Strategies")
    print("="*70)
    
    try:
        from ipfs_datasets_py.ml.embeddings.chunking import (
            FixedSizeChunker,
            SemanticChunker,
        )
        
        # Long text that needs chunking
        long_text = """
        The field of artificial intelligence has grown tremendously over the past decade.
        Machine learning algorithms now power many applications we use daily, from
        recommendation systems to autonomous vehicles. Deep learning, a subset of machine
        learning, has been particularly successful in areas like computer vision and
        natural language processing. Neural networks with many layers can learn complex
        patterns from large amounts of data. This has led to breakthroughs in tasks
        that were once thought to be uniquely human, such as image recognition and
        language translation.
        """
        
        # Fixed-size chunking
        print("\n1️⃣ Fixed-Size Chunking (chunk_size=100, overlap=20):")
        fixed_chunker = FixedSizeChunker(chunk_size=100, overlap=20)
        fixed_chunks = fixed_chunker.chunk_text(long_text)
        print(f"   Created {len(fixed_chunks)} chunks")
        for i, chunk in enumerate(fixed_chunks[:2], 1):  # Show first 2
            print(f"   Chunk {i}: '{chunk.text[:50]}...' ({len(chunk.text)} chars)")
        
        # Semantic chunking
        print("\n2️⃣ Semantic Chunking:")
        try:
            semantic_chunker = SemanticChunker(max_chunk_size=200)
            semantic_chunks = semantic_chunker.chunk_text(long_text)
            print(f"   Created {len(semantic_chunks)} semantic chunks")
            for i, chunk in enumerate(semantic_chunks[:2], 1):
                print(f"   Chunk {i}: '{chunk.text[:50]}...' ({len(chunk.text)} chars)")
        except Exception as e:
            print(f"   ⚠️  Semantic chunking requires NLTK: {e}")
        
    except ImportError as e:
        print(f"\n❌ Missing dependencies: {e}")
    except Exception as e:
        print(f"\n❌ Error: {e}")


def show_tips():
    """Show tips for working with embeddings."""
    print("\n" + "="*70)
    print("TIPS FOR WORKING WITH EMBEDDINGS")
    print("="*70)
    
    print("\n1. Model Selection:")
    print("   - all-MiniLM-L6-v2: Fast, good for most tasks (384 dims)")
    print("   - all-mpnet-base-v2: Better quality, slower (768 dims)")
    print("   - Use sentence-transformers models from HuggingFace")
    
    print("\n2. Chunking Long Documents:")
    print("   - Use FixedSizeChunker for consistent chunk sizes")
    print("   - Use SemanticChunker to preserve meaning")
    print("   - Overlap chunks to preserve context at boundaries")
    
    print("\n3. Performance:")
    print("   - Process texts in batches for better throughput")
    print("   - Consider GPU acceleration for large datasets")
    print("   - Cache embeddings to avoid recomputation")
    
    print("\n4. Next Steps:")
    print("   - See 03_vector_search.py for similarity search")
    print("   - See 12_graphrag_basic.py for RAG applications")


async def main():
    """Run all embedding demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - BASIC EMBEDDINGS")
    print("="*70)
    
    await demo_basic_embedding_generation()
    await demo_different_models()
    await demo_semantic_similarity()
    await demo_batch_processing()
    await demo_chunking_strategies()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ EMBEDDING EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
