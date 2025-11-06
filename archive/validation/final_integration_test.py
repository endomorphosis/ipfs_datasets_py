#!/usr/bin/env python3
"""
Final integration test to validate the complete ipfs_embeddings_py integration.
"""

import sys
import os
import traceback
from datetime import datetime

def test_integration():
    """Run comprehensive integration tests."""
    results = []
    results.append(f"=== FINAL INTEGRATION TEST ===")
    results.append(f"Timestamp: {datetime.now().isoformat()}")
    results.append(f"Python: {sys.version}")
    results.append(f"Working directory: {os.getcwd()}")
    results.append("")
    
    # Add current directory to path
    sys.path.insert(0, '.')
    
    # Test 1: Basic package import
    try:
        import ipfs_datasets_py
        results.append("✅ 1. Package imports successfully")
        results.append(f"   Location: {ipfs_datasets_py.__file__}")
        results.append(f"   Version: {getattr(ipfs_datasets_py, '__version__', 'unknown')}")
    except Exception as e:
        results.append(f"❌ 1. Package import failed: {e}")
        results.append(f"   Traceback: {traceback.format_exc()}")
    
    # Test 2: Core classes
    try:
        from ipfs_datasets_py.core import IpfsDatasets
        results.append("✅ 2. IpfsDatasets class available")
    except Exception as e:
        results.append(f"❌ 2. IpfsDatasets import failed: {e}")
    
    # Test 3: Embeddings module
    try:
        from ipfs_datasets_py.embeddings.core import EmbeddingCore
        results.append("✅ 3. EmbeddingCore available")
    except Exception as e:
        results.append(f"❌ 3. EmbeddingCore import failed: {e}")
    
    # Test 4: Vector stores
    try:
        from ipfs_datasets_py.vector_stores.base import BaseVectorStore
        results.append("✅ 4. BaseVectorStore available")
    except Exception as e:
        results.append(f"❌ 4. BaseVectorStore import failed: {e}")
    
    # Test 5: Feature flags
    try:
        from ipfs_datasets_py import enable_embeddings, enable_vector_stores
        results.append("✅ 5. Feature flags available")
    except Exception as e:
        results.append(f"❌ 5. Feature flags import failed: {e}")
    
    # Test 6: MCP server
    try:
        from ipfs_datasets_py.mcp_server.server import create_server
        results.append("✅ 6. MCP server available")
    except Exception as e:
        results.append(f"❌ 6. MCP server import failed: {e}")
    
    # Test 7: FastAPI service
    try:
        from ipfs_datasets_py.fastapi_service import app
        results.append("✅ 7. FastAPI service available")
    except Exception as e:
        results.append(f"❌ 7. FastAPI service import failed: {e}")
    
    # Test 8: MCP tools
    try:
        from ipfs_datasets_py.mcp_server.tools.embedding_tools.embedding_generation import embedding_generation
        results.append("✅ 8. MCP embedding tools available")
    except Exception as e:
        results.append(f"❌ 8. MCP embedding tools import failed: {e}")
    
    # Test 9: Vector store tools
    try:
        from ipfs_datasets_py.mcp_server.tools.bespoke_tools.create_vector_store import create_vector_store
        results.append("✅ 9. Vector store tools available")
    except Exception as e:
        results.append(f"❌ 9. Vector store tools import failed: {e}")
    
    # Test 10: Admin tools
    try:
        from ipfs_datasets_py.mcp_server.tools.bespoke_tools.system_status import system_status
        results.append("✅ 10. Admin tools available")
    except Exception as e:
        results.append(f"❌ 10. Admin tools import failed: {e}")
    
    results.append("")
    results.append("=== TEST SUMMARY ===")
    
    passed = len([r for r in results if r.startswith("✅")])
    failed = len([r for r in results if r.startswith("❌")])
    
    results.append(f"Passed: {passed}")
    results.append(f"Failed: {failed}")
    results.append(f"Total: {passed + failed}")
    
    if failed == 0:
        results.append("🎉 ALL TESTS PASSED - INTEGRATION COMPLETE!")
    else:
        results.append(f"⚠️  {failed} tests failed - needs attention")
    
    # Print to console
    for line in results:
        print(line)
    
    # Save to file
    with open('final_integration_results.txt', 'w') as f:
        f.write('\n'.join(results))
    
    return failed == 0

if __name__ == "__main__":
    success = test_integration()
    sys.exit(0 if success else 1)
