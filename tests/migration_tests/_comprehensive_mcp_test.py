#!/usr/bin/env python3
"""
Comprehensive MCP Tools Test Runner

Tests all available MCP tools across all categories to verify functionality.
"""

import os
import sys
import tempfile
import traceback
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

def test_web_archive_tools():
    """Test all web archive tools."""
    print("Testing Web Archive Tools")
    print("-" * 40)

    results = []

    # Test extract_text_from_warc
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_text_from_warc import extract_text_from_warc

        with tempfile.NamedTemporaryFile(mode='w', suffix='.warc', delete=False) as f:
            f.write("WARC/1.0\nWARC-Type: response\n\nTest content")
            warc_path = f.name

        result = extract_text_from_warc(warc_path)

        if result.get("status") == "success":
            print("✓ extract_text_from_warc")
            results.append(("extract_text_from_warc", True, None))
        else:
            print(f"✗ extract_text_from_warc: {result.get('error', 'Unknown error')}")
            results.append(("extract_text_from_warc", False, result.get('error', 'Unknown error')))

        os.unlink(warc_path)
    except Exception as e:
        print(f"✗ extract_text_from_warc: {e}")
        results.append(("extract_text_from_warc", False, str(e)))

    # Test extract_metadata_from_warc
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_metadata_from_warc import extract_metadata_from_warc

        with tempfile.NamedTemporaryFile(mode='w', suffix='.warc', delete=False) as f:
            f.write("WARC/1.0\nWARC-Type: response\n\nTest content")
            warc_path = f.name

        result = await extract_metadata_from_warc(warc_path)

        if result.get("status") == "success":
            print("✓ extract_metadata_from_warc")
            results.append(("extract_metadata_from_warc", True, None))
        else:
            print(f"✗ extract_metadata_from_warc: {result.get('error', 'Unknown error')}")
            results.append(("extract_metadata_from_warc", False, result.get('error', 'Unknown error')))

        os.unlink(warc_path)
    except Exception as e:
        print(f"✗ extract_metadata_from_warc: {e}")
        results.append(("extract_metadata_from_warc", False, str(e)))

    # Test extract_links_from_warc
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.extract_links_from_warc import extract_links_from_warc

        with tempfile.NamedTemporaryFile(mode='w', suffix='.warc', delete=False) as f:
            f.write("WARC/1.0\nWARC-Type: response\n\nTest content")
            warc_path = f.name

        result = await extract_links_from_warc(warc_path)

        if result.get("status") == "success":
            print("✓ extract_links_from_warc")
            results.append(("extract_links_from_warc", True, None))
        else:
            print(f"✗ extract_links_from_warc: {result.get('error', 'Unknown error')}")
            results.append(("extract_links_from_warc", False, result.get('error', 'Unknown error')))

        os.unlink(warc_path)
    except Exception as e:
        print(f"✗ extract_links_from_warc: {e}")
        results.append(("extract_links_from_warc", False, str(e)))

    # Test index_warc
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.index_warc import index_warc

        with tempfile.NamedTemporaryFile(mode='w', suffix='.warc', delete=False) as f:
            f.write("WARC/1.0\nWARC-Type: response\n\nTest content")
            warc_path = f.name

        result = await index_warc(warc_path)

        if result.get("status") == "success":
            print("✓ index_warc")
            results.append(("index_warc", True, None))
        else:
            print(f"✗ index_warc: {result.get('error', 'Unknown error')}")
            results.append(("index_warc", False, result.get('error', 'Unknown error')))

        os.unlink(warc_path)
    except Exception as e:
        print(f"✗ index_warc: {e}")
        results.append(("index_warc", False, str(e)))

    return results

def test_vector_tools():
    """Test all vector tools."""
    print("\nTesting Vector Tools")
    print("-" * 40)

    results = []

    # Test create_vector_index
    try:
        import anyio
        from ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index import create_vector_index

        # Create test vectors
        vectors = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
        metadata = [{"text": "test1"}, {"text": "test2"}, {"text": "test3"}]

        result = anyio.run(create_vector_index(vectors, dimension=3, metadata=metadata, index_id="test_index"))

        if result.get("status") == "success":
            print("✓ create_vector_index")
            results.append(("create_vector_index", True, None))
        else:
            print(f"✗ create_vector_index: {result.get('message', 'Unknown error')}")
            results.append(("create_vector_index", False, result.get('message', 'Unknown error')))
    except Exception as e:
        print(f"✗ create_vector_index: {e}")
        results.append(("create_vector_index", False, str(e)))

    # Test search_vector_index
    try:
        import anyio
        from ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index import search_vector_index

        query_vector = [1.0, 2.0, 3.0]
        result = anyio.run(search_vector_index("test_index", query_vector, top_k=5))

        if result.get("status") == "success":
            print("✓ search_vector_index")
            results.append(("search_vector_index", True, None))
        else:
            print(f"✗ search_vector_index: {result.get('message', 'Unknown error')}")
            results.append(("search_vector_index", False, result.get('message', 'Unknown error')))
    except Exception as e:
        print(f"✗ search_vector_index: {e}")
        results.append(("search_vector_index", False, str(e)))

    return results

def test_graph_tools():
    """Test all graph tools."""
    print("\nTesting Graph Tools")
    print("-" * 40)

    results = []

    # Test query_knowledge_graph
    try:
        import anyio
        from ipfs_datasets_py.mcp_server.tools.graph_tools.query_knowledge_graph import query_knowledge_graph

        query = "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"
        result = anyio.run(query_knowledge_graph("test_graph", query))

        if result.get("status") == "success":
            print("✓ query_knowledge_graph")
            results.append(("query_knowledge_graph", True, None))
        else:
            print(f"✗ query_knowledge_graph: {result.get('message', 'Unknown error')}")
            results.append(("query_knowledge_graph", False, result.get('message', 'Unknown error')))
    except Exception as e:
        print(f"✗ query_knowledge_graph: {e}")
        results.append(("query_knowledge_graph", False, str(e)))

    return results

def test_dataset_tools():
    """Test all dataset tools."""
    print("\nTesting Dataset Tools")
    print("-" * 40)

    results = []

    tools_to_test = [
        ("load_dataset", ["test_dataset"]),
        ("save_dataset", [{"data": [1, 2, 3]}, "test_output"]),
        ("process_dataset", [{"data": [1, 2, 3]}, [{"operation": "filter", "type": "filter"}]]),
        ("convert_dataset_format", [{"data": [1, 2, 3]}, "csv", "json"])
    ]

    for tool_name, args in tools_to_test:
        try:
            import anyio
            # Try to import and test each tool
            module_path = f"ipfs_datasets_py.mcp_server.tools.dataset_tools.{tool_name}"
            module = __import__(module_path, fromlist=[tool_name])
            tool_func = getattr(module, tool_name)

            # Check if it's an async function
            if asyncio.iscoroutinefunction(tool_func):
                result = anyio.run(tool_func(*args))
            else:
                result = tool_func(*args)

            if result.get("status") == "success":
                print(f"✓ {tool_name}")
                results.append((tool_name, True, None))
            else:
                print(f"✗ {tool_name}: {result.get('error', 'Unknown error')}")
                results.append((tool_name, False, result.get('error', 'Unknown error')))
        except Exception as e:
            print(f"✗ {tool_name}: {e}")
            results.append((tool_name, False, str(e)))

    return results

def test_ipfs_tools():
    """Test all IPFS tools."""
    print("\nTesting IPFS Tools")
    print("-" * 40)

    results = []

    tools_to_test = [
        ("get_from_ipfs", ["QmTest123"]),
        ("pin_to_ipfs", [{"test": "data"}])
    ]

    for tool_name, args in tools_to_test:
        try:
            import anyio
            module_path = f"ipfs_datasets_py.mcp_server.tools.ipfs_tools.{tool_name}"
            module = __import__(module_path, fromlist=[tool_name])
            tool_func = getattr(module, tool_name)

            # Check if it's an async function
            if asyncio.iscoroutinefunction(tool_func):
                result = anyio.run(tool_func(*args))
            else:
                result = tool_func(*args)

            if result.get("status") == "success":
                print(f"✓ {tool_name}")
                results.append((tool_name, True, None))
            else:
                print(f"✗ {tool_name}: {result.get('error', 'Unknown error')}")
                results.append((tool_name, False, result.get('error', 'Unknown error')))
        except Exception as e:
            print(f"✗ {tool_name}: {e}")
            results.append((tool_name, False, str(e)))

    return results

def test_other_tools():
    """Test tools in other categories."""
    print("\nTesting Other Tool Categories")
    print("-" * 40)

    results = []

    # Define tools with their required parameters
    tool_configs = {
        "audit_tools": {
            "record_audit_event": ["test_action", "test_resource", "test_user"],
            "generate_audit_report": {"report_type": "comprehensive", "start_time": "2023-01-01", "end_time": "2023-12-31"}
        },
        "provenance_tools": {
            "record_provenance": ["test_dataset", "test_operation", {"user": "test"}]
        },
        "security_tools": {
            "check_access_permission": ["test_resource", "test_user"]
        },
        "cli": {
            "execute_command": ["echo 'test'"]
        },
        "functions": {
            "execute_python_snippet": ["print('test')"]
        }
    }

    for category, tools in tool_configs.items():
        print(f"\n  {category.replace('_', ' ').title()}:")
        category_path = Path(project_root) / "ipfs_datasets_py" / "mcp_server" / "tools" / category

        if not category_path.exists():
            print(f"    Directory not found: {category_path}")
            continue

        for tool_name, args in tools.items():
            try:
                import anyio
                module_path = f"ipfs_datasets_py.mcp_server.tools.{category}.{tool_name}"
                module = __import__(module_path, fromlist=[tool_name])
                tool_func = getattr(module, tool_name)

                # Check if it's an async function
                if asyncio.iscoroutinefunction(tool_func):
                    # Handle dict args differently from list args
                    if isinstance(args, dict):
                        result = anyio.run(tool_func(**args))
                    else:
                        result = anyio.run(tool_func(*args))
                else:
                    # Handle dict args differently from list args
                    if isinstance(args, dict):
                        result = tool_func(**args)
                    else:
                        result = tool_func(*args)

                if result.get("status") == "success":
                    print(f"    ✓ {tool_name}")
                    results.append((f"{category}.{tool_name}", True, None))
                else:
                    print(f"    ✗ {tool_name}: {result.get('error', 'Unknown error')}")
                    results.append((f"{category}.{tool_name}", False, result.get('error', 'Unknown error')))
            except Exception as e:
                print(f"    ✗ {tool_name}: {e}")
                results.append((f"{category}.{tool_name}", False, str(e)))

    return results

def main():
    """Run all MCP tool tests."""
    print("IPFS Datasets MCP Tools Comprehensive Test")
    print("=" * 50)

    all_results = []

    # Test each category
    try:
        all_results.extend(test_web_archive_tools())
    except Exception as e:
        print(f"Error testing web archive tools: {e}")

    try:
        all_results.extend(test_vector_tools())
    except Exception as e:
        print(f"Error testing vector tools: {e}")

    try:
        all_results.extend(test_graph_tools())
    except Exception as e:
        print(f"Error testing graph tools: {e}")

    try:
        all_results.extend(test_dataset_tools())
    except Exception as e:
        print(f"Error testing dataset tools: {e}")

    try:
        all_results.extend(test_ipfs_tools())
    except Exception as e:
        print(f"Error testing IPFS tools: {e}")

    try:
        all_results.extend(test_other_tools())
    except Exception as e:
        print(f"Error testing other tools: {e}")

    # Summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)

    passed = sum(1 for _, success, _ in all_results if success)
    total = len(all_results)

    print(f"Overall Results: {passed}/{total} tools passed")

    if passed < total:
        print(f"\n⚠️  {total - passed} tools need attention:")
        for tool_name, success, error in all_results:
            if not success:
                print(f"  ✗ {tool_name}: {error}")

    return 0 if passed == total else 1

if __name__ == "__main__":
    exit(main())
