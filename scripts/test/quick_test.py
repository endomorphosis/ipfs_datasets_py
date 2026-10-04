#!/usr/bin/env python3
"""
Quick test script to check core functionality without auto-installation
"""

import sys
import os

# Add the package to path
sys.path.insert(0, "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py")

# Disable auto-installation
os.environ["IPFS_DATASETS_AUTO_INSTALL"] = "false"


def test_imports():
    """Test core imports"""
    print("🚀 Testing Core Functionality")
    print("=" * 50)

    results = []

    # Test 1: Basic package import
    try:
        import ipfs_datasets_py

        results.append("✅ 1. Basic package import works")
    except Exception as e:
        results.append(f"❌ 1. Basic package import failed: {e}")

    # Test 2: FastAPI service
    try:
        from ipfs_datasets_py.fastapi_service import app

        results.append("✅ 2. FastAPI service available")
    except Exception as e:
        results.append(f"❌ 2. FastAPI service failed: {e}")

    # Test 3: IpfsDatasets class
    try:
        from ipfs_datasets_py.ipfs_datasets import ipfs_datasets_py

        results.append("✅ 3. ipfs_datasets_py class available")
    except Exception as e:
        results.append(f"❌ 3. ipfs_datasets_py class failed: {e}")

    # Test 4: MCP server class
    try:
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer

        results.append("✅ 4. MCP server class available")
    except Exception as e:
        results.append(f"❌ 4. MCP server class failed: {e}")

    # Test 5: Core dataset manager
    try:
        from ipfs_datasets_py.dataset_manager import DatasetManager

        results.append("✅ 5. DatasetManager available")
    except Exception as e:
        results.append(f"❌ 5. DatasetManager failed: {e}")

    # Test 6: Vector stores
    try:
        from ipfs_datasets_py.vector_stores.base import BaseVectorStore

        results.append("✅ 6. Vector stores available")
    except Exception as e:
        results.append(f"❌ 6. Vector stores failed: {e}")

    # Test 7: Embeddings
    try:
        from ipfs_datasets_py.embeddings.core import IPFSEmbeddings

        results.append("✅ 7. Embeddings core available")
    except Exception as e:
        results.append(f"❌ 7. Embeddings core failed: {e}")

    # Test 8: MCP tools sample
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset

        results.append("✅ 8. MCP tools available")
    except Exception as e:
        results.append(f"❌ 8. MCP tools failed: {e}")

    # Print results
    print("\n📊 Test Results:")
    for result in results:
        print(f"  {result}")

    # Summary
    passed = len([r for r in results if r.startswith("✅")])
    failed = len([r for r in results if r.startswith("❌")])
    total = len(results)

    print(f"\n📈 Summary: {passed}/{total} tests passed ({passed / total * 100:.1f}%)")

    if passed >= 6:  # At least 75% passing
        print("🎉 System is mostly functional!")
        return True
    else:
        print("⚠️ System needs attention")
        return False


if __name__ == "__main__":
    success = test_imports()
    sys.exit(0 if success else 1)
