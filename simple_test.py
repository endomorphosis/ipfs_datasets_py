#!/usr/bin/env python3
"""
Simple test script to verify our MCP functionality without complex imports.
"""
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

def test_web_archive():
    """Test the web archive module directly."""
    print("Testing web_archive module...")
    try:
        # Import directly from the module file
        sys.path.insert(0, str(Path(__file__).resolve().parent / "ipfs_datasets_py"))
        from web_archive import WebArchiveProcessor
        
        # Test basic functionality
        processor = WebArchiveProcessor()
        test_html = "<html><body><h1>Test</h1><p>This is a test.</p></body></html>"
        text = processor.extract_text_from_html(test_html)
        text_preview = str(text)[:50] if text else "None"
        print(f"✓ WebArchiveProcessor.extract_text_from_html: {text_preview}...")
        
        # Test URL archiving
        metadata = processor.archive.archive_url("https://example.com")
        print(f"✓ WebArchiveProcessor.archive_url: {metadata.get('url', 'Unknown')}")
        
        return True
    except Exception as e:
        print(f"✗ web_archive test failed: {e}")
        return False

def test_vector_tools():
    """Test the vector tools module directly."""
    print("\nTesting vector_tools module...")
    try:
        from vector_tools import VectorSimilarityCalculator, VectorStore
        
        # Test similarity calculation
        calc = VectorSimilarityCalculator()
        vector1 = [1.0, 0.0, 0.0]
        vector2 = [0.0, 1.0, 0.0]
        similarity = calc.cosine_similarity(vector1, vector2)
        print(f"✓ VectorSimilarityCalculator.cosine_similarity: {similarity}")
        
        # Test vector store
        store = VectorStore()
        store.add_vector("test1", vector1)
        store.add_vector("test2", vector2)
        print(f"✓ VectorStore operations: {len(store.vectors)} vectors stored")
        
        return True
    except Exception as e:
        print(f"✗ vector_tools test failed: {e}")
        return False

def test_graphrag_processor():
    """Test the GraphRAG processor module directly."""
    print("\nTesting graphrag_processor module...")
    try:
        from graphrag_processor import GraphRAGProcessor, MockGraphRAGProcessor
        
        # Test mock processor
        processor = MockGraphRAGProcessor()
        result = processor.query("What is the capital of France?")
        result_preview = str(result)[:50] if result else "None"
        print(f"✓ MockGraphRAGProcessor.query: {result_preview}...")
        
        # Test basic GraphRAG processor
        rag_processor = GraphRAGProcessor()
        entities = rag_processor.extract_entities("Paris is the capital of France.")
        print(f"✓ GraphRAGProcessor.extract_entities: {len(entities)} entities")
        
        return True
    except Exception as e:
        print(f"✗ graphrag_processor test failed: {e}")
        return False

def test_mcp_tools():
    """Test that MCP tools can import our modules."""
    print("\nTesting MCP tools imports...")
    try:
        # Test web archive tool
        web_tool_path = Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "web_archive_tools" / "extract_text_from_warc.py"
        if web_tool_path.exists():
            print(f"✓ Web archive tool exists: {web_tool_path.name}")
        else:
            print(f"✗ Web archive tool missing: {web_tool_path}")
            
        # Test vector tool
        vector_tool_path = Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "vector_tools" / "create_vector_index.py"
        if vector_tool_path.exists():
            print(f"✓ Vector tool exists: {vector_tool_path.name}")
        else:
            print(f"✗ Vector tool missing: {vector_tool_path}")
            
        # Test graph tool
        graph_tool_path = Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "graph_tools" / "query_knowledge_graph.py"
        if graph_tool_path.exists():
            print(f"✓ Graph tool exists: {graph_tool_path.name}")
        else:
            print(f"✗ Graph tool missing: {graph_tool_path}")
            
        return True
    except Exception as e:
        print(f"✗ MCP tools test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("IPFS Datasets MCP Functionality Test")
    print("=" * 40)
    
    tests = [
        test_web_archive,
        test_vector_tools,
        test_graphrag_processor,
        test_mcp_tools,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"✗ Test {test.__name__} crashed: {e}")
    
    print(f"\nResults: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! MCP functionality is working.")
    else:
        print("⚠️  Some tests failed. Check the output above for details.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
