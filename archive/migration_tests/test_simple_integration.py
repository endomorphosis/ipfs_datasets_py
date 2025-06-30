#!/usr/bin/env python3
"""
Simple integration test for PDF processing pipeline validation.
"""

import asyncio
import tempfile
import json
from pathlib import Path
import sys

# Add project path
sys.path.insert(0, '/home/barberb/ipfs_datasets_py')

async def test_simple_integration():
    """Test simple integration of PDF processing components."""
    print("Testing simple PDF processing integration...")
    
    try:
        from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_ingest_to_graphrag import pdf_ingest_to_graphrag
        
        # Create a temporary text file 
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("This is a test document about IPFS and distributed systems.")
            temp_path = f.name
        
        try:
            # Test 1: PDF Processor
            print("Testing PDFProcessor...")
            processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
            result = await processor.process_pdf(temp_path)
            print(f"PDFProcessor result status: {result.get('status', 'unknown')}")
            
            # Test 2: MCP Tool
            print("Testing PDF MCP tool...")
            request_data = {
                "pdf_path": temp_path,
                "options": {"enable_ocr": False}
            }
            result2 = await pdf_ingest_to_graphrag(json.dumps(request_data))
            print(f"MCP tool result status: {result2.get('status', 'unknown')}")
            
            print("✓ Integration test completed successfully")
            return True
            
        finally:
            # Clean up
            Path(temp_path).unlink(missing_ok=True)
            
    except Exception as e:
        print(f"✗ Integration test failed: {e}")
        return False

async def test_error_handling():
    """Test error handling in integration scenarios."""
    print("\nTesting error handling...")
    
    try:
        from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_ingest_to_graphrag import pdf_ingest_to_graphrag
        
        # Test with non-existent file
        processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        result = await processor.process_pdf("/nonexistent/file.pdf")
        assert result["status"] == "error", "Should return error for non-existent file"
        
        # Test MCP tool with invalid JSON
        result2 = await pdf_ingest_to_graphrag("invalid json")
        assert result2["status"] == "error", "Should return error for invalid JSON"
        
        print("✓ Error handling test completed successfully")
        return True
        
    except Exception as e:
        print(f"✗ Error handling test failed: {e}")
        return False

async def main():
    """Run all integration tests."""
    print("=== PDF Processing Integration Tests ===\n")
    
    tests = [
        test_simple_integration,
        test_error_handling
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"Test {test.__name__} failed with exception: {e}")
            results.append(False)
    
    print(f"\n=== Results ===")
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("🎉 All integration tests passed!")
        return 0
    else:
        print("⚠️  Some tests failed.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
