"""
Vector Search with FAISS and Qdrant

This example demonstrates how to use vector stores (FAISS, Qdrant) for semantic
search. Vector stores allow you to store embeddings and efficiently search for
similar items.

Requirements:
    - faiss-cpu: pip install faiss-cpu (or faiss-gpu for GPU support)
    - qdrant-client: pip install qdrant-client (optional)
    - transformers, torch

Usage:
    python examples/03_vector_search.py
"""

import asyncio
import sys
from pathlib import Path


async def demo_faiss_vector_store():
    """Demonstrate FAISS vector store operations."""
    print("\n" + "="*70)
    print("DEMO 1: FAISS Vector Store")
    print("="*70)
    
    try:
        from ipfs_datasets_py.ml.embeddings.ipfs_embeddings import IPFSEmbeddings
        from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
        
        # Initialize embedder
        print("\n📦 Initializing embedder...")
        embedder = IPFSEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        
        # Sample documents
        documents = [
            "Python is a high-level programming language.",
            "Machine learning uses algorithms to learn from data.",
            "JavaScript is primarily used for web development.",
            "Deep learning is a subset of machine learning.",
            "Natural language processing helps computers understand text.",
        ]
        
        # Generate embeddings
        print(f"\n📝 Generating embeddings for {len(documents)} documents...")
        embeddings = await embedder.generate_embeddings(documents)
        
        # Create FAISS store
        print("\n🔍 Creating FAISS vector store...")
        dimension = len(embeddings[0])
        store = FAISSVectorStore(dimension=dimension)
        
        # Add documents
        print("   Adding documents to store...")
        metadata = [{"doc_id": i, "text": doc} for i, doc in enumerate(documents)]
        await store.add(embeddings=embeddings, metadata=metadata)
        print(f"   ✅ Added {len(documents)} documents")
        
        # Perform search
        query = "What is machine learning?"
        print(f"\n🔎 Searching for: '{query}'")
        query_embedding = await embedder.generate_embeddings([query])
        
        results = await store.search(query_embedding[0], top_k=3)
        
        print("\n📊 Top 3 results:")
        for i, result in enumerate(results, 1):
            print(f"   {i}. Score: {result['score']:.4f}")
            print(f"      Text: {result['metadata']['text']}")
        
        return store
        
    except ImportError as e:
        print(f"\n❌ Missing dependencies: {e}")
        print("   Install with: pip install faiss-cpu transformers torch")
        return None
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def demo_qdrant_vector_store():
    """Demonstrate Qdrant vector store operations."""
    print("\n" + "="*70)
    print("DEMO 2: Qdrant Vector Store (Optional)")
    print("="*70)
    
    print("\n⚠️  Qdrant requires a running Qdrant server.")
    print("   To start Qdrant with Docker:")
    print("   docker run -p 6333:6333 qdrant/qdrant")
    print("\n   Skipping Qdrant demo. See documentation for usage.")
    
    # Uncomment below if you have Qdrant running
    """
    try:
        from ipfs_datasets_py.ml.embeddings.ipfs_embeddings import IPFSEmbeddings
        from ipfs_datasets_py.vector_stores.qdrant_store import QdrantStore
        
        embedder = IPFSEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        
        # Create Qdrant store
        store = QdrantStore(
            collection_name="demo_collection",
            host="localhost",
            port=6333
        )
        
        # Add and search documents similar to FAISS example
        
    except ImportError as e:
        print(f"\\n❌ Qdrant client not installed: {e}")
    except Exception as e:
        print(f"\\n❌ Error connecting to Qdrant: {e}")
    """


async def demo_similarity_threshold():
    """Demonstrate filtering by similarity threshold."""
    print("\n" + "="*70)
    print("DEMO 3: Similarity Threshold Filtering")
    print("="*70)
    
    try:
        from ipfs_datasets_py.ml.embeddings.ipfs_embeddings import IPFSEmbeddings
        from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
        
        embedder = IPFSEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        
        # Create diverse documents
        documents = [
            "Artificial intelligence is changing the world.",
            "AI and machine learning are transforming industries.",
            "Cats are popular pets around the world.",
            "Deep neural networks can learn complex patterns.",
            "Cooking pasta requires boiling water first.",
        ]
        
        print(f"\n📝 Creating vector store with {len(documents)} documents...")
        embeddings = await embedder.generate_embeddings(documents)
        
        dimension = len(embeddings[0])
        store = FAISSVectorStore(dimension=dimension)
        metadata = [{"text": doc} for doc in documents]
        await store.add(embeddings=embeddings, metadata=metadata)
        
        # Search with different thresholds
        query = "What is artificial intelligence?"
        print(f"\n🔎 Query: '{query}'")
        query_embedding = await embedder.generate_embeddings([query])
        
        thresholds = [0.5, 0.7, 0.9]
        for threshold in thresholds:
            print(f"\n   Threshold >= {threshold}:")
            results = await store.search(query_embedding[0], top_k=5)
            filtered_results = [r for r in results if r['score'] >= threshold]
            
            if filtered_results:
                for result in filtered_results:
                    print(f"      Score {result['score']:.4f}: {result['metadata']['text']}")
            else:
                print(f"      No results above threshold {threshold}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")


async def demo_metadata_filtering():
    """Demonstrate filtering by metadata."""
    print("\n" + "="*70)
    print("DEMO 4: Metadata Filtering")
    print("="*70)
    
    try:
        from ipfs_datasets_py.ml.embeddings.ipfs_embeddings import IPFSEmbeddings
        from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
        
        embedder = IPFSEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        
        # Documents with metadata
        documents = [
            ("Python is a programming language.", "tech", 2023),
            ("Machine learning is part of AI.", "tech", 2023),
            ("Cooking pasta is an art.", "food", 2023),
            ("JavaScript runs in browsers.", "tech", 2022),
            ("Baking bread requires patience.", "food", 2022),
        ]
        
        texts = [doc[0] for doc in documents]
        print(f"\n📝 Adding {len(documents)} documents with metadata...")
        embeddings = await embedder.generate_embeddings(texts)
        
        dimension = len(embeddings[0])
        store = FAISSVectorStore(dimension=dimension)
        
        metadata = [
            {"text": doc[0], "category": doc[1], "year": doc[2]} 
            for doc in documents
        ]
        await store.add(embeddings=embeddings, metadata=metadata)
        
        # Search within category
        query = "programming languages"
        print(f"\n🔎 Query: '{query}' (category: tech)")
        query_embedding = await embedder.generate_embeddings([query])
        
        all_results = await store.search(query_embedding[0], top_k=5)
        tech_results = [r for r in all_results if r['metadata']['category'] == 'tech']
        
        print("\n📊 Results filtered by category='tech':")
        for i, result in enumerate(tech_results, 1):
            print(f"   {i}. Score: {result['score']:.4f}")
            print(f"      Text: {result['metadata']['text']}")
            print(f"      Year: {result['metadata']['year']}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")


async def demo_persistence():
    """Demonstrate saving and loading vector stores."""
    print("\n" + "="*70)
    print("DEMO 5: Persistence (Save/Load)")
    print("="*70)
    
    try:
        from ipfs_datasets_py.ml.embeddings.ipfs_embeddings import IPFSEmbeddings
        from ipfs_datasets_py.vector_stores.faiss_store import FAISSVectorStore
        import tempfile
        import os
        
        embedder = IPFSEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        
        # Create and populate store
        documents = ["Test document 1", "Test document 2", "Test document 3"]
        embeddings = await embedder.generate_embeddings(documents)
        
        dimension = len(embeddings[0])
        store = FAISSVectorStore(dimension=dimension)
        metadata = [{"text": doc} for doc in documents]
        await store.add(embeddings=embeddings, metadata=metadata)
        
        # Save to file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".faiss") as tmp:
            save_path = tmp.name
        
        print(f"\n💾 Saving vector store to: {save_path}")
        await store.save(save_path)
        print("   ✅ Saved successfully")
        
        # Load from file
        print("\n📂 Loading vector store from file...")
        loaded_store = FAISSVectorStore(dimension=dimension)
        await loaded_store.load(save_path)
        print("   ✅ Loaded successfully")
        
        # Verify by searching
        query_embedding = await embedder.generate_embeddings(["test"])
        results = await loaded_store.search(query_embedding[0], top_k=2)
        print(f"\n✅ Loaded store has {len(results)} searchable documents")
        
        # Cleanup
        os.unlink(save_path)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")


def show_tips():
    """Show tips for vector search."""
    print("\n" + "="*70)
    print("TIPS FOR VECTOR SEARCH")
    print("="*70)
    
    print("\n1. Choosing a Vector Store:")
    print("   - FAISS: Fast, in-memory, good for prototyping")
    print("   - Qdrant: Production-ready, persistent, filtered search")
    print("   - Elasticsearch: Full-text + vector search hybrid")
    
    print("\n2. Optimizing Search:")
    print("   - Use appropriate top_k value (5-10 usually sufficient)")
    print("   - Filter by metadata to narrow search space")
    print("   - Set similarity thresholds to exclude low-quality results")
    
    print("\n3. Scaling:")
    print("   - FAISS IVF indexes for large datasets (>100k vectors)")
    print("   - Qdrant for distributed deployments")
    print("   - Consider approximate nearest neighbor (ANN) algorithms")
    
    print("\n4. Next Steps:")
    print("   - See 12_graphrag_basic.py for RAG applications")
    print("   - See 09_batch_processing.py for large-scale indexing")


async def main():
    """Run all vector search demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - VECTOR SEARCH")
    print("="*70)
    
    await demo_faiss_vector_store()
    await demo_qdrant_vector_store()
    await demo_similarity_threshold()
    await demo_metadata_filtering()
    await demo_persistence()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ VECTOR SEARCH EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
