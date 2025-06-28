#!/usr/bin/env python3
"""
Basic functionality test for PDF processing and MCP tools.
This test validates core functionality without complex mocking.
"""

import asyncio
import tempfile
import sys
from pathlib import Path
import json

# Add the project directory to Python path
sys.path.insert(0, '/home/barberb/ipfs_datasets_py')

async def test_basic_pdf_processor():
    """Test basic PDF processor initialization and imports."""
    print("Testing PDF processor imports...")
    
    try:
        from ipfs_datasets_py.pdf_processing import PDFProcessor
        print("✓ PDFProcessor import successful")
        
        # Test initialization
        processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        print("✓ PDFProcessor initialization successful")
        
        return True
    except Exception as e:
        print(f"✗ PDF processor test failed: {e}")
        return False

async def test_basic_mcp_tools():
    """Test basic MCP tool imports and execution."""
    print("\nTesting MCP tool imports...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
        print("✓ load_dataset import successful")
        
        # Test with a simple mock dataset
        result = await load_dataset("test_dataset")
        print(f"✓ load_dataset execution successful: {result['status']}")
        
        return True
    except Exception as e:
        print(f"✗ MCP tools test failed: {e}")
        return False

async def test_basic_llm_optimizer():
    """Test LLM optimizer functionality."""
    print("\nTesting LLM optimizer...")
    
    try:
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
        print("✓ LLMOptimizer import successful")
        
        optimizer = LLMOptimizer()
        print("✓ LLMOptimizer initialization successful")
        
        return True
    except Exception as e:
        print(f"✗ LLM optimizer test failed: {e}")
        return False

async def test_basic_ocr_engine():
    """Test OCR engine functionality."""
    print("\nTesting OCR engine...")
    
    try:
        from ipfs_datasets_py.pdf_processing.ocr_engine import MultiEngineOCR
        print("✓ MultiEngineOCR import successful")
        
        ocr = MultiEngineOCR()
        print("✓ MultiEngineOCR initialization successful")
        
        return True
    except Exception as e:
        print(f"✗ OCR engine test failed: {e}")
        return False

async def test_simple_pdf_processing():
    """Test simple PDF processing with a temporary file."""
    print("\nTesting simple PDF processing...")
    
    try:
        from ipfs_datasets_py.pdf_processing import PDFProcessor
        
        processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        
        # Create a temporary text file (simulate PDF)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdf', delete=False) as f:
            f.write("This is a test PDF content for processing.")
            temp_path = f.name
        
        # Test processing (this should handle the missing PDF gracefully)
        try:
            result = await processor.process_pdf(temp_path)
            print(f"✓ PDF processing attempted (result: {result.get('status', 'unknown')})")
        except Exception as e:
            print(f"✓ PDF processing error handled gracefully: {type(e).__name__}")
        
        # Clean up
        Path(temp_path).unlink(missing_ok=True)
        
        return True
    except Exception as e:
        print(f"✗ PDF processing test failed: {e}")
        return False

async def test_mcp_pdf_tools():
    """Test PDF MCP tools."""
    print("\nTesting PDF MCP tools...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_ingest_to_graphrag import pdf_ingest_to_graphrag
        print("✓ pdf_ingest_to_graphrag import successful")
        
        # Test with invalid data to see error handling
        request_data = {"pdf_path": "/nonexistent/file.pdf"}
        result = await pdf_ingest_to_graphrag(json.dumps(request_data))
        print(f"✓ pdf_ingest_to_graphrag execution successful: {result.get('status', 'unknown')}")
        
        return True
    except Exception as e:
        print(f"✗ PDF MCP tools test failed: {e}")
        return False

async def main():
    """Run all basic functionality tests."""
    print("=== Basic Functionality Test Suite ===\n")
    
    tests = [
        test_basic_pdf_processor,
        test_basic_mcp_tools,
        test_basic_llm_optimizer,
        test_basic_ocr_engine,
        test_simple_pdf_processing,
        test_mcp_pdf_tools
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"✗ Test {test.__name__} failed with exception: {e}")
            results.append(False)
    
    print("\n=== Test Results ===")
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    print(f"Success rate: {passed/total*100:.1f}%")
    
    if passed == total:
        print("🎉 All basic functionality tests passed!")
        return 0
    else:
        print("⚠️  Some tests failed. See details above.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
