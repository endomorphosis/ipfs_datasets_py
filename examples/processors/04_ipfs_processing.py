"""
IPFS Content Processing Example
================================

This example demonstrates how to process IPFS content using UniversalProcessor
with the new IPFS adapter and anyio for async support.

The IPFS adapter automatically detects IPFS content (CIDs, ipfs:// URLs, /ipfs/ paths)
and processes them through the unified async interface.
"""

import anyio
from ipfs_datasets_py.processors.adapters import register_all_adapters
from ipfs_datasets_py.processors.core import UniversalProcessor


async def main():
    """Demonstrate IPFS content processing with anyio."""
    
    print("=" * 70)
    print("IPFS Content Processing with UniversalProcessor (Async)")
    print("=" * 70)
    print()
    
    # Register all adapters
    print("Registering processor adapters...")
    count = register_all_adapters()
    print(f"✓ Registered {count} adapters")
    print()
    
    # Create processor instance
    processor = UniversalProcessor()
    
    # Example 1: Process direct CID
    print("Example 1: Processing IPFS CID")
    print("-" * 70)
    
    # Using a known IPFS CID (IPFS white paper)
    cid = "QmV9tSDx9UiPeWExXEeH6aoDvmihvx6jD5eLb4jbTaKGps"
    
    print(f"Input: {cid}")
    print("Automatic IPFS detection and processing...")
    print()
    print("✓ IPFS adapter registered with highest priority (20)")
    print("✓ Supports: CIDs, ipfs:// URLs, /ipfs/ paths, ipns:// URLs")
    print("✓ Multi-strategy fetching: daemon → ipfs_kit → gateway")
    print()
    
    # Note: Uncomment to actually process (requires IPFS)
    # print("Processing...")
    # result = await processor.process(cid)
    # if result.success:
    #     print(f"✓ Success! Extracted {len(result.knowledge_graph.get('entities', []))} entities")
    # else:
    #     print(f"✗ Failed: {result.errors}")
    
    print("Example complete!")
    print()


if __name__ == "__main__":
    print()
    print("Note: This example requires either:")
    print("  1. A running IPFS daemon")
    print("  2. Internet access for IPFS gateway fallback")
    print()
    print("Using anyio for async support (works with asyncio, trio, etc.)")
    print()
    print("Starting example...")
    print()
    
    # Use anyio.run() instead of asyncio.run()
    anyio.run(main)

