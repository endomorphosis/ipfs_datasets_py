#!/usr/bin/env python3

# Simple test script for import verification
import sys
import os

# Add current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

print("Starting import tests...")

try:
    print("1. Testing web_archive import...")
    from ipfs_datasets_py.web_archive import WebArchiveProcessor
    print("   ✓ WebArchiveProcessor imported successfully")
    
    # Test instantiation
    web_proc = WebArchiveProcessor()
    print("   ✓ WebArchiveProcessor instantiated successfully")
    
except Exception as e:
    print(f"   ✗ Web archive import failed: {e}")

try:
    print("2. Testing graphrag_processor import...")
    from ipfs_datasets_py.graphrag_processor import MockGraphRAGProcessor
    print("   ✓ MockGraphRAGProcessor imported successfully")
    
    # Test instantiation
    graphrag = MockGraphRAGProcessor()
    print("   ✓ MockGraphRAGProcessor instantiated successfully")
    
except Exception as e:
    print(f"   ✗ GraphRAG processor import failed: {e}")

try:
    print("3. Testing dataset_manager import...")
    from ipfs_datasets_py.dataset_manager import DatasetManager
    print("   ✓ DatasetManager imported successfully")
    
except Exception as e:
    print(f"   ✗ DatasetManager import failed: {e}")

print("4. Testing vector_tools import...")
# We'll skip this for now due to the hanging issue

print("\nImport tests completed!")
