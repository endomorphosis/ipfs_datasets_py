"""
IPFS Content Processing Example
================================

This example demonstrates how to process IPFS content using UniversalProcessor
with the new IPFS adapter.

The IPFS adapter automatically detects IPFS content (CIDs, ipfs:// URLs, /ipfs/ paths)
and processes them through the unified interface.

Updated to use the synchronous ProcessorProtocol (2026-02-15).
"""

from ipfs_datasets_py.processors import UniversalProcessor


def main():
    """Demonstrate IPFS content processing."""
    
    # Create processor instance
    processor = UniversalProcessor()
    
    print("=" * 70)
    print("IPFS Content Processing with UniversalProcessor")
    print("=" * 70)
    print()
    
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
    
    # Process the CID (synchronous)
    # Note: Uncomment the following to actually process
    # result = processor.process(cid)
    # if result.success:
    #     print(f"✓ Success! Extracted {len(result.knowledge_graph.get('entities', []))} entities")
    # else:
    #     print(f"✗ Failed: {result.errors}")


if __name__ == "__main__":
    print()
    print("Note: This example requires either:")
    print("  1. A running IPFS daemon")
    print("  2. Internet access for IPFS gateway fallback")
    print()
    print("Starting example...")
    print()
    
    main()

