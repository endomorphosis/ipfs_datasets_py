#!/usr/bin/env python3
"""
Simple verification script for the embedding migration.
Tests core components without complex dependencies.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def test_imports():
    """Test basic imports of migrated components."""
    results = {}

    # Test embeddings core
    try:
        from ipfs_datasets_py.embeddings.schema import EmbeddingRequest, EmbeddingResponse

        results["embeddings_schema"] = True
        print("✅ Embeddings schema imported successfully")
    except Exception as e:
        results["embeddings_schema"] = False
        print(f"❌ Embeddings schema import failed: {e}")

    # Test chunker
    try:
        from ipfs_datasets_py.embeddings.chunker import Chunker, ChunkingConfig

        results["chunker"] = True
        print("✅ Text chunker imported successfully")
    except Exception as e:
        results["chunker"] = False
        print(f"❌ Text chunker import failed: {e}")

    # Test vector stores
    try:
        from ipfs_datasets_py.vector_stores.base import BaseVectorStore

        results["vector_store_base"] = True
        print("✅ Vector store base imported successfully")
    except Exception as e:
        results["vector_store_base"] = False
        print(f"❌ Vector store base import failed: {e}")

    # Test MCP tools
    try:
        from ipfs_datasets_py.mcp_server.tools.embedding_tools.advanced_embedding_generation import (
            generate_embedding,
        )

        results["mcp_embedding_tools"] = True
        print("✅ MCP embedding tools imported successfully")
    except Exception as e:
        results["mcp_embedding_tools"] = False
        print(f"❌ MCP embedding tools import failed: {e}")

    return results


def test_basic_functionality():
    """Test basic functionality of core components."""
    results = {}

    # Test chunker functionality
    try:
        from ipfs_datasets_py.embeddings.chunker import Chunker

        chunker = Chunker()
        text = "This is a test text. It has multiple sentences. We will chunk it."
        chunks = chunker.chunk_text(text, max_chunk_size=50)
        if len(chunks) > 0:
            results["chunker_function"] = True
            print(f"✅ Text chunker created {len(chunks)} chunks")
        else:
            results["chunker_function"] = False
            print("❌ Text chunker returned no chunks")
    except Exception as e:
        results["chunker_function"] = False
        print(f"❌ Text chunker functionality failed: {e}")

    # Test schema creation
    try:
        from ipfs_datasets_py.embeddings.schema import EmbeddingRequest

        request = EmbeddingRequest(text="test text", model="test-model", parameters={})
        results["schema_creation"] = True
        print("✅ Schema creation successful")
    except Exception as e:
        results["schema_creation"] = False
        print(f"❌ Schema creation failed: {e}")

    return results


def main():
    """Main verification function."""
    print("🔍 IPFS Embeddings Migration Verification")
    print("=" * 50)

    print("\n📦 Testing Imports...")
    import_results = test_imports()

    print("\n⚙️  Testing Basic Functionality...")
    function_results = test_basic_functionality()

    print("\n📊 Summary:")
    all_results = {**import_results, **function_results}
    passed = sum(1 for result in all_results.values() if result)
    total = len(all_results)

    print(f"Passed: {passed}/{total} ({passed / total * 100:.1f}%)")

    if passed == total:
        print("🎉 All tests passed! Migration components are working correctly.")
        return 0
    else:
        print("⚠️  Some tests failed. Check the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
