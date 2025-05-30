#!/usr/bin/env python3

# Minimal test to check individual module imports
import sys
import os

# Add current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

print("=== MINIMAL IMPORT TEST ===")

# Test 1: Direct module import without going through __init__.py
print("Testing direct web_archive import...")
try:
    import ipfs_datasets_py.web_archive
    print("✓ web_archive module imported")

    from ipfs_datasets_py.web_archive import WebArchiveProcessor
    print("✓ WebArchiveProcessor class imported")

    processor = WebArchiveProcessor()
    print("✓ WebArchiveProcessor instantiated")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()

print("\nTesting direct graphrag_processor import...")
try:
    import ipfs_datasets_py.graphrag_processor
    print("✓ graphrag_processor module imported")

    from ipfs_datasets_py.graphrag_processor import MockGraphRAGProcessor
    print("✓ MockGraphRAGProcessor class imported")

    mock_proc = MockGraphRAGProcessor()
    print("✓ MockGraphRAGProcessor instantiated")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n=== TEST COMPLETE ===")
