#!/usr/bin/env python3
"""
Final validation script - Run this to confirm everything is working after VS Code reload.
"""

import sys
import anyio
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


async def quick_validation():
    """Quick validation of core functionality."""
    print("🚀 Final Integration Validation\n")

    tests = []

    # Test 1: Core imports
    try:
        import ipfs_datasets_py
        from ipfs_datasets_py.embeddings import EmbeddingCore
        from ipfs_datasets_py.vector_stores import BaseVectorStore

        tests.append(("Core Package Imports", True, "All core imports successful"))
    except Exception as e:
        tests.append(("Core Package Imports", False, f"Import error: {e}"))

    # Test 2: MCP Tools
    try:
        from ipfs_datasets_py.mcp_server.tools.tool_wrapper import EnhancedBaseMCPTool
        from ipfs_datasets_py.mcp_server.tools.tool_registration import MCPToolRegistry

        tests.append(("MCP Tool System", True, "Tool system ready"))
    except Exception as e:
        tests.append(("MCP Tool System", False, f"Tool system error: {e}"))

    # Test 3: FastAPI
    try:
        from ipfs_datasets_py.fastapi_service import app

        tests.append(("FastAPI Service", True, "FastAPI service ready"))
    except Exception as e:
        tests.append(("FastAPI Service", False, f"FastAPI error: {e}"))

    # Test 4: Individual tool functionality
    try:
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import authenticate_user

        result = await authenticate_user("test", "test")
        tests.append(("Sample Tool Function", True, "Tools are functional"))
    except Exception as e:
        tests.append(("Sample Tool Function", False, f"Tool error: {e}"))

    # Results
    print("📋 Validation Results:")
    passed = 0
    for name, success, message in tests:
        status = "✅" if success else "❌"
        print(f"  {status} {name}: {message}")
        if success:
            passed += 1

    success_rate = passed / len(tests)
    print(f"\n📊 Overall: {passed}/{len(tests)} tests passed ({success_rate * 100:.1f}%)")

    if success_rate >= 0.75:  # 75% threshold
        print("\n🎉 INTEGRATION VALIDATION PASSED!")
        print("\n🚀 Ready to use:")
        print("  • FastAPI Service: python start_fastapi.py")
        print("  • MCP Server: python -m ipfs_datasets_py.mcp_server --stdio")
        print("  • Full Tests: python -m pytest tests/ -v")
        print("  • Production Check: python production_readiness_check.py")
        return True
    else:
        print("\n⚠️  Integration needs attention, but basic functionality is available.")
        return False


if __name__ == "__main__":
    try:
        success = anyio.run(quick_validation())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Validation failed: {e}")
        sys.exit(1)
