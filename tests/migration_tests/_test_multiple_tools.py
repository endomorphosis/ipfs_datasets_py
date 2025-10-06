#!/usr/bin/env python3
"""
Test multiple MCP tools to verify functionality.
"""

import os
import sys
import tempfile
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

async def test_web_archive_tools():
    """Test all web archive tools."""
    tools_tested = 0
    tools_passed = 0

    print("Testing Web Archive Tools")
    print("-" * 30)

    # Test extract_text_from_warc
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_text_from_warc import extract_text_from_warc

        with tempfile.NamedTemporaryFile(mode='w', suffix='.warc', delete=False) as f:
            f.write("WARC/1.0\nWARC-Type: response\n\nTest content")
            warc_path = f.name

        result = await extract_text_from_warc(warc_path)
        tools_tested += 1

        if result.get("status") == "success":
            print("✓ extract_text_from_warc")
            tools_passed += 1
        else:
            print(f"✗ extract_text_from_warc: {result.get('error', 'Unknown error')}")

        os.unlink(warc_path)
    except Exception as e:
        tools_tested += 1
        print(f"✗ extract_text_from_warc: {e}")

    # Test extract_metadata_from_warc
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_metadata_from_warc import extract_metadata_from_warc

        with tempfile.NamedTemporaryFile(mode='w', suffix='.warc', delete=False) as f:
            f.write("WARC/1.0\nWARC-Type: response\n\nTest content")
            warc_path = f.name

        result = await extract_metadata_from_warc(warc_path)
        tools_tested += 1

        if result.get("status") == "success":
            print("✓ extract_metadata_from_warc")
            tools_passed += 1
        else:
            print(f"✗ extract_metadata_from_warc: {result.get('error', 'Unknown error')}")

        os.unlink(warc_path)
    except Exception as e:
        tools_tested += 1
        print(f"✗ extract_metadata_from_warc: {e}")

    # Test extract_links_from_warc
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_links_from_warc import extract_links_from_warc

        with tempfile.NamedTemporaryFile(mode='w', suffix='.warc', delete=False) as f:
            f.write("WARC/1.0\nWARC-Type: response\n\nTest content")
            warc_path = f.name

        result = await extract_links_from_warc(warc_path)
        tools_tested += 1

        if result.get("status") == "success":
            print("✓ extract_links_from_warc")
            tools_passed += 1
        else:
            print(f"✗ extract_links_from_warc: {result.get('error', 'Unknown error')}")

        os.unlink(warc_path)
    except Exception as e:
        tools_tested += 1
        print(f"✗ extract_links_from_warc: {e}")

    # Test index_warc
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.index_warc import index_warc

        with tempfile.NamedTemporaryFile(mode='w', suffix='.warc', delete=False) as f:
            f.write("WARC/1.0\nWARC-Type: response\n\nTest content")
            warc_path = f.name

        result = await index_warc(warc_path)
        tools_tested += 1

        if result.get("status") == "success":
            print("✓ index_warc")
            tools_passed += 1
        else:
            print(f"✗ index_warc: {result.get('error', 'Unknown error')}")

        os.unlink(warc_path)
    except Exception as e:
        tools_tested += 1
        print(f"✗ index_warc: {e}")

    return tools_tested, tools_passed

def test_vector_tools():
    """Test vector tools."""
    tools_tested = 0
    tools_passed = 0

    print("\nTesting Vector Tools")
    print("-" * 30)

    # Test create_vector_index
    try:
        from ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index import create_vector_index
        import asyncio

        vectors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        metadata = [{"id": "vec1"}, {"id": "vec2"}, {"id": "vec3"}]

        result = asyncio.run(create_vector_index(vectors, metadata=metadata))
        tools_tested += 1

        if result.get("status") == "success":
            print("✓ create_vector_index")
            tools_passed += 1
        else:
            print(f"✗ create_vector_index: {result.get('error', 'Unknown error')}")
    except Exception as e:
        tools_tested += 1
        print(f"✗ create_vector_index: {e}")

    # Test search_vector_index
    try:
        from ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index import search_vector_index
        import asyncio

        query_vector = [1.0, 0.0, 0.0]
        result = asyncio.run(search_vector_index("test_index", query_vector, top_k=5))
        tools_tested += 1

        if result.get("status") == "success":
            print("✓ search_vector_index")
            tools_passed += 1
        else:
            print(f"✗ search_vector_index: {result.get('error', 'Unknown error')}")
    except Exception as e:
        tools_tested += 1
        print(f"✗ search_vector_index: {e}")

    return tools_tested, tools_passed

def test_graph_tools():
    """Test graph tools."""
    tools_tested = 0
    tools_passed = 0

    print("\nTesting Graph Tools")
    print("-" * 30)

    # Test query_knowledge_graph
    try:
        from ipfs_datasets_py.mcp_server.tools.graph_tools.query_knowledge_graph import query_knowledge_graph
        import asyncio

        result = asyncio.run(query_knowledge_graph(
            graph_id="test_graph",
            query="SELECT * WHERE { ?s ?p ?o } LIMIT 10",
            query_type="sparql"
        ))
        tools_tested += 1

        if result.get("status") == "success":
            print("✓ query_knowledge_graph")
            tools_passed += 1
        else:
            print(f"✗ query_knowledge_graph: {result.get('error', 'Unknown error')}")
    except Exception as e:
        tools_tested += 1
        print(f"✗ query_knowledge_graph: {e}")

    return tools_tested, tools_passed

def main():
    """Run tests for multiple tool categories."""
    print("IPFS Datasets MCP Tools Functionality Test")
    print("=" * 50)

    total_tested = 0
    total_passed = 0

    # Test web archive tools
    tested, passed = test_web_archive_tools()
    total_tested += tested
    total_passed += passed

    # Test vector tools
    tested, passed = test_vector_tools()
    total_tested += tested
    total_passed += passed

    # Test graph tools
    tested, passed = test_graph_tools()
    total_tested += tested
    total_passed += passed

    print(f"\n" + "=" * 50)
    print(f"Overall Results: {total_passed}/{total_tested} tools passed")

    if total_passed == total_tested:
        print("🎉 All tested tools are working correctly!")
        return True
    else:
        print(f"⚠️  {total_tested - total_passed} tools need attention")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
