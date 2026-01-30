#!/usr/bin/env python3
"""
IPFS-Accelerated File Conversion Example.

Demonstrates the complete Phase 3 integration:
- File conversion with IPFS storage
- Content-addressable caching
- ML acceleration (when available)
- Batch processing with distributed storage
- Pin management

Usage:
    python examples/ipfs_accelerate_example.py
    
    # With IPFS disabled
    IPFS_STORAGE_ENABLED=0 python examples/ipfs_accelerate_example.py
    
    # With acceleration disabled
    IPFS_ACCELERATE_ENABLED=0 python examples/ipfs_accelerate_example.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ipfs_datasets_py.file_converter import (
    IPFSAcceleratedConverter,
    create_converter,
    IPFS_AVAILABLE
)


def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


async def demo_1_basic_conversion():
    """Demo 1: Basic conversion with IPFS storage."""
    print_section("Demo 1: Basic Conversion with IPFS Storage")
    
    # Create test file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("This is a test document for IPFS storage.\n")
        f.write("It contains multiple lines of text.\n")
        f.write("Perfect for demonstrating file conversion!")
        test_file = Path(f.name)
    
    try:
        # Create converter
        converter = IPFSAcceleratedConverter(
            backend='native',
            enable_ipfs=True,
            enable_acceleration=True
        )
        
        print(f"\n✅ Created IPFS-accelerated converter")
        print(f"   Backend: native")
        print(f"   IPFS enabled: Yes")
        print(f"   Acceleration enabled: Yes")
        
        # Convert file
        print(f"\n📄 Converting: {test_file.name}")
        result = await converter.convert(test_file, store_on_ipfs=True)
        
        print(f"\n✅ Conversion successful!")
        print(f"   Text length: {len(result.text)} characters")
        print(f"   Processing time: {result.processing_time:.3f}s")
        print(f"   Backend used: {result.backend_used}")
        print(f"   Accelerated: {result.accelerated}")
        
        if result.ipfs_cid:
            print(f"\n📦 IPFS Storage:")
            print(f"   CID: {result.ipfs_cid}")
            print(f"   Gateway URL: {result.ipfs_gateway_url}")
            print(f"   Pinned: {result.ipfs_pinned}")
        else:
            print(f"\n⚠️  IPFS storage not available (running in local-only mode)")
        
        print(f"\n📝 Converted text preview:")
        print(f"   {result.text[:100]}...")
        
    finally:
        test_file.unlink(missing_ok=True)


async def demo_2_batch_processing():
    """Demo 2: Batch processing with concurrent IPFS storage."""
    print_section("Demo 2: Batch Processing with IPFS")
    
    # Create multiple test files
    test_files = []
    for i in range(5):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        f.write(f"Document {i+1}\n")
        f.write(f"This is test document number {i+1}.\n")
        f.write(f"It contains important information about topic {i+1}.")
        f.close()
        test_files.append(Path(f.name))
    
    try:
        converter = IPFSAcceleratedConverter(
            backend='native',
            enable_ipfs=True
        )
        
        print(f"\n📚 Converting {len(test_files)} files concurrently...")
        results = await converter.convert_batch(
            test_files,
            max_concurrent=3,
            store_on_ipfs=True
        )
        
        print(f"\n✅ Batch conversion complete!")
        print(f"   Total files: {len(results)}")
        
        successful = [r for r in results if not isinstance(r, Exception) and r.success]
        print(f"   Successful: {len(successful)}")
        
        if successful and successful[0].ipfs_cid:
            print(f"\n📦 IPFS CIDs:")
            for i, result in enumerate(successful[:3], 1):
                print(f"   File {i}: {result.ipfs_cid}")
            if len(successful) > 3:
                print(f"   ... and {len(successful) - 3} more")
        
        # Show stats
        total_text = sum(len(r.text) for r in successful)
        total_time = sum(r.processing_time for r in successful)
        print(f"\n📊 Statistics:")
        print(f"   Total text: {total_text} characters")
        print(f"   Total time: {total_time:.3f}s")
        print(f"   Avg per file: {total_time/len(successful):.3f}s")
        
    finally:
        for f in test_files:
            f.unlink(missing_ok=True)


async def demo_3_pin_management():
    """Demo 3: Pin management."""
    print_section("Demo 3: Pin Management")
    
    # Create test file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Important document that should be pinned for persistence.")
        test_file = Path(f.name)
    
    try:
        converter = IPFSAcceleratedConverter(
            backend='native',
            enable_ipfs=True,
            auto_pin=False  # Manual pinning
        )
        
        # Convert without auto-pinning
        print(f"\n📄 Converting file (no auto-pin)...")
        result = await converter.convert(test_file, store_on_ipfs=True, pin=False)
        
        if result.ipfs_cid:
            print(f"\n✅ File stored on IPFS")
            print(f"   CID: {result.ipfs_cid}")
            print(f"   Initially pinned: {result.ipfs_pinned}")
            
            # Manually pin
            print(f"\n📌 Manually pinning file...")
            pinned = await converter.pin_result(result.ipfs_cid)
            print(f"   Pin successful: {pinned}")
            
            # List pins
            print(f"\n📋 Listing pinned files...")
            pins = await converter.list_pinned_results()
            print(f"   Total pinned: {len(pins)}")
            if pins:
                print(f"   First few: {pins[:3]}")
            
            # Unpin
            print(f"\n🔓 Unpinning file...")
            unpinned = await converter.unpin_result(result.ipfs_cid)
            print(f"   Unpin successful: {unpinned}")
        else:
            print(f"\n⚠️  IPFS not available - pin management skipped")
    
    finally:
        test_file.unlink(missing_ok=True)


async def demo_4_retrieve_from_ipfs():
    """Demo 4: Retrieve converted text from IPFS."""
    print_section("Demo 4: Retrieve from IPFS")
    
    # Create and store file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("This document will be stored on IPFS and retrieved later.")
        test_file = Path(f.name)
    
    try:
        converter = IPFSAcceleratedConverter(backend='native', enable_ipfs=True)
        
        print(f"\n📄 Converting and storing on IPFS...")
        result = await converter.convert(test_file, store_on_ipfs=True)
        
        if result.ipfs_cid:
            print(f"\n✅ Stored on IPFS")
            print(f"   CID: {result.ipfs_cid}")
            
            # Retrieve from IPFS
            print(f"\n📥 Retrieving from IPFS by CID...")
            retrieved_text = await converter.retrieve_from_ipfs(result.ipfs_cid)
            
            if retrieved_text:
                print(f"\n✅ Retrieved successfully!")
                print(f"   Text length: {len(retrieved_text)} characters")
                print(f"   Matches original: {retrieved_text == result.text}")
                print(f"\n📝 Retrieved text:")
                print(f"   {retrieved_text[:80]}...")
            else:
                print(f"\n⚠️  Retrieval failed (IPFS may not be available)")
        else:
            print(f"\n⚠️  IPFS not available - skipping retrieval demo")
    
    finally:
        test_file.unlink(missing_ok=True)


async def demo_5_status_and_capabilities():
    """Demo 5: Check status and capabilities."""
    print_section("Demo 5: Status and Capabilities")
    
    converter = IPFSAcceleratedConverter(
        backend='native',
        enable_ipfs=True,
        enable_acceleration=True
    )
    
    status = converter.get_status()
    
    print(f"\n🔧 Converter Configuration:")
    print(f"   Backend: {status['converter_backend']}")
    print(f"   IPFS enabled: {status['ipfs_enabled']}")
    print(f"   Acceleration enabled: {status['acceleration_enabled']}")
    print(f"   Auto-pin: {status['auto_pin']}")
    print(f"   Cache directory: {status['cache_dir']}")
    
    print(f"\n📦 IPFS Status:")
    ipfs_status = status['ipfs']
    print(f"   Available: {ipfs_status['available']}")
    print(f"   Connected: {ipfs_status['connected']}")
    print(f"   Gateway: {ipfs_status.get('gateway_url', 'N/A')}")
    if ipfs_status.get('import_error'):
        print(f"   Import error: {ipfs_status['import_error']}")
    
    print(f"\n⚡ Acceleration Status:")
    accel_status = status['acceleration']
    print(f"   Available: {accel_status.get('accelerate_available', False)}")
    print(f"   Initialized: {accel_status.get('accelerate_initialized', False)}")
    print(f"   Distributed enabled: {accel_status.get('distributed_enabled', False)}")
    
    print(f"\n💡 Capabilities:")
    if ipfs_status['connected']:
        print(f"   ✅ IPFS storage active")
        print(f"   ✅ Content-addressable caching")
        print(f"   ✅ Distributed retrieval")
    else:
        print(f"   ⚠️  Running in local-only mode")
        print(f"   ✅ Local file conversion still works")


async def demo_6_convenience_functions():
    """Demo 6: Convenience functions."""
    print_section("Demo 6: Convenience Functions")
    
    # Create converter using convenience function
    print(f"\n🛠️  Using create_converter() convenience function...")
    converter = create_converter(
        backend='native',
        enable_ipfs=True
    )
    
    print(f"✅ Converter created")
    print(f"   Type: {type(converter).__name__}")
    
    # Quick conversion
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Quick test using convenience function")
        test_file = Path(f.name)
    
    try:
        result = await converter.convert(test_file)
        print(f"\n✅ Quick conversion successful")
        print(f"   Text: {result.text[:50]}...")
    finally:
        test_file.unlink(missing_ok=True)


async def main():
    """Run all demos."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 12 + "IPFS-Accelerated File Conversion Demo" + " " * 17 + "║")
    print("║" + " " * 20 + "Phase 3 Integration" + " " * 27 + "║")
    print("╚" + "=" * 68 + "╝")
    
    try:
        await demo_1_basic_conversion()
        await demo_2_batch_processing()
        await demo_3_pin_management()
        await demo_4_retrieve_from_ipfs()
        await demo_5_status_and_capabilities()
        await demo_6_convenience_functions()
        
        print("\n" + "=" * 70)
        print("  All demos completed successfully!")
        print("=" * 70)
        
        print(f"\n💡 Key Takeaways:")
        print(f"   • File conversion works with or without IPFS")
        print(f"   • IPFS provides content-addressable storage")
        print(f"   • ML acceleration is optional and automatic")
        print(f"   • Batch processing supports concurrent operations")
        print(f"   • Graceful fallback to local mode when needed")
        
        print(f"\n📚 Next Steps:")
        print(f"   1. Install IPFS: pip install ipfs_kit_py")
        print(f"   2. Install acceleration: pip install ipfs_accelerate_py")
        print(f"   3. Run IPFS daemon: ipfs daemon")
        print(f"   4. Try with real documents!")
        
        if not IPFS_AVAILABLE:
            print(f"\n⚠️  Note: ipfs_kit_py not installed - running in local-only mode")
            print(f"   Install with: pip install ipfs_kit_py")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error running demos: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
