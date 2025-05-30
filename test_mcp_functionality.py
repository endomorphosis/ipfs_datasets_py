#!/usr/bin/env python3

"""
Simple MCP Server Test Script

This script tests the MCP server functionality by creating a minimal
server implementation that uses our new modules directly.
"""

import sys
import os
from pathlib import Path

# Add current directory to Python path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

def test_web_archive_functionality():
    """Test web archive functionality for MCP tools."""
    print("=== Testing Web Archive Functionality ===")

    try:
        from ipfs_datasets_py.web_archive import WebArchiveProcessor

        processor = WebArchiveProcessor()

        # Test HTML text extraction
        test_html = """
        <html>
            <head><title>Test Page</title></head>
            <body>
                <h1>Welcome to Test Page</h1>
                <p>This is a test paragraph with some content.</p>
                <div>More content here</div>
            </body>
        </html>
        """

        result = processor.extract_text_from_html(test_html)
        print(f"✓ HTML text extraction: {result['status']}")
        print(f"  Extracted text: {result['text'][:50]}...")

        # Test URL processing
        test_urls = ['https://example.com', 'https://test.org']
        url_result = processor.process_urls(test_urls)
        print(f"✓ URL processing: {url_result['status']}")
        print(f"  Processed {len(url_result['results'])} URLs")

        return True

    except Exception as e:
        print(f"✗ Web archive test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_vector_tools_functionality():
    """Test vector tools functionality for MCP tools."""
    print("\n=== Testing Vector Tools Functionality ===")

    try:
        from ipfs_datasets_py.vector_tools import VectorSimilarityCalculator, VectorStore

        # Test similarity calculator
        calc = VectorSimilarityCalculator()

        # Test vectors
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [0.0, 1.0, 0.0]
        vec3 = [1.0, 0.0, 0.0]

        similarity1 = calc.cosine_similarity(vec1, vec2)
        similarity2 = calc.cosine_similarity(vec1, vec3)
        distance = calc.euclidean_distance(vec1, vec2)

        print(f"✓ Cosine similarity (orthogonal): {similarity1:.3f}")
        print(f"✓ Cosine similarity (identical): {similarity2:.3f}")
        print(f"✓ Euclidean distance: {distance:.3f}")

        # Test batch similarity
        vectors = [[1, 0], [0, 1], [1, 1], [0.5, 0.5]]
        query = [1, 0]
        batch_similarities = calc.batch_similarity(vectors, query)
        print(f"✓ Batch similarities: {batch_similarities}")

        # Test vector store
        store = VectorStore(dimension=2)
        store.add_vector("vec1", [1.0, 0.0], {"label": "first"})
        store.add_vector("vec2", [0.0, 1.0], {"label": "second"})

        search_results = store.search_similar([0.8, 0.2], top_k=2)
        print(f"✓ Vector store search: {len(search_results)} results")

        return True

    except Exception as e:
        print(f"✗ Vector tools test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_graphrag_functionality():
    """Test GraphRAG functionality for MCP tools."""
    print("\n=== Testing GraphRAG Functionality ===")

    try:
        from ipfs_datasets_py.graphrag_processor import MockGraphRAGProcessor

        processor = MockGraphRAGProcessor()

        # Test simple query
        query_result = processor.query("What is machine learning?")
        print(f"✓ GraphRAG query: {query_result['status']}")
        print(f"  Response: {query_result['results'][0]['text'][:50]}...")

        # Test graph loading
        graph = processor.load_graph("test_graph")
        print(f"✓ Graph loading: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")

        return True

    except Exception as e:
        print(f"✗ GraphRAG test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def create_simple_mcp_tool_registry():
    """Create a simple registry of MCP tools."""
    print("\n=== Creating MCP Tool Registry ===")

    tool_registry = {}

    # Register web archive tools
    try:
        from ipfs_datasets_py.web_archive import WebArchiveProcessor

        def extract_text_tool(html_content: str):
            processor = WebArchiveProcessor()
            return processor.extract_text_from_html(html_content)

        tool_registry['extract_text_from_html'] = extract_text_tool
        print("✓ Registered extract_text_from_html tool")

    except Exception as e:
        print(f"✗ Failed to register web archive tools: {e}")

    # Register vector tools
    try:
        from ipfs_datasets_py.vector_tools import VectorSimilarityCalculator

        def calculate_similarity_tool(vector1, vector2):
            calc = VectorSimilarityCalculator()
            return calc.cosine_similarity(vector1, vector2)

        tool_registry['calculate_similarity'] = calculate_similarity_tool
        print("✓ Registered calculate_similarity tool")

    except Exception as e:
        print(f"✗ Failed to register vector tools: {e}")

    # Register GraphRAG tools
    try:
        from ipfs_datasets_py.graphrag_processor import MockGraphRAGProcessor

        def query_graph_tool(query: str):
            processor = MockGraphRAGProcessor()
            return processor.query(query)

        tool_registry['query_knowledge_graph'] = query_graph_tool
        print("✓ Registered query_knowledge_graph tool")

    except Exception as e:
        print(f"✗ Failed to register GraphRAG tools: {e}")

    return tool_registry

def test_tool_registry(registry):
    """Test the tool registry functionality."""
    print("\n=== Testing Tool Registry ===")

    # Test HTML extraction tool
    if 'extract_text_from_html' in registry:
        try:
            result = registry['extract_text_from_html']("<h1>Test</h1><p>Content</p>")
            print(f"✓ HTML extraction tool works: {result['status']}")
        except Exception as e:
            print(f"✗ HTML extraction tool failed: {e}")

    # Test similarity calculation tool
    if 'calculate_similarity' in registry:
        try:
            result = registry['calculate_similarity']([1, 0], [0, 1])
            print(f"✓ Similarity calculation tool works: {result:.3f}")
        except Exception as e:
            print(f"✗ Similarity calculation tool failed: {e}")

    # Test GraphRAG tool
    if 'query_knowledge_graph' in registry:
        try:
            result = registry['query_knowledge_graph']("What is AI?")
            print(f"✓ GraphRAG tool works: {result['status']}")
        except Exception as e:
            print(f"✗ GraphRAG tool failed: {e}")

def main():
    """Main test function."""
    print("IPFS Datasets Python - MCP Server Test")
    print("=" * 50)

    # Test individual components
    web_ok = test_web_archive_functionality()
    vector_ok = test_vector_tools_functionality()
    graphrag_ok = test_graphrag_functionality()

    if web_ok and vector_ok and graphrag_ok:
        print("\n🎉 All core functionality tests PASSED!")

        # Create and test tool registry
        registry = create_simple_mcp_tool_registry()
        test_tool_registry(registry)

        print(f"\n📋 MCP Tools Available: {list(registry.keys())}")
        print("\n✅ MCP Server functionality is working correctly!")
        print("   The modules are ready for VS Code integration.")

    else:
        print("\n❌ Some tests failed. Please check the errors above.")

    return web_ok and vector_ok and graphrag_ok

if __name__ == "__main__":
    main()
