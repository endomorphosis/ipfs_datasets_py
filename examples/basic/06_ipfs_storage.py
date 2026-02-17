"""
IPFS Storage - Store and Retrieve Data on IPFS

This example demonstrates how to store and retrieve data using IPFS
(InterPlanetary File System). IPFS provides content-addressed, decentralized
storage that's perfect for datasets and embeddings.

Requirements:
    - IPFS daemon running (ipfs init && ipfs daemon)
    - OR use ipfs_kit_py for embedded IPFS
    - ipfshttpclient: pip install ipfshttpclient

Usage:
    python examples/06_ipfs_storage.py
"""

import asyncio
import tempfile
import json
from pathlib import Path


def check_ipfs_availability():
    """Check if IPFS daemon is running."""
    try:
        import ipfshttpclient
        client = ipfshttpclient.connect()
        version = client.version()
        print(f"✅ IPFS daemon connected (version: {version['Version']})")
        return True
    except Exception as e:
        print(f"⚠️  IPFS daemon not available: {e}")
        print("   Start with: ipfs init && ipfs daemon")
        return False


async def demo_basic_ipfs_operations():
    """Demonstrate basic IPFS add/get operations."""
    print("\n" + "="*70)
    print("DEMO 1: Basic IPFS Operations")
    print("="*70)
    
    if not check_ipfs_availability():
        print("\n⚠️  Skipping - IPFS daemon not running")
        return
    
    try:
        import ipfshttpclient
        
        client = ipfshttpclient.connect()
        
        # Add text content
        print("\n📤 Adding text to IPFS...")
        content = "Hello, IPFS! This is a test message from ipfs_datasets_py."
        result = client.add_str(content)
        cid = result
        
        print(f"   ✅ Added successfully")
        print(f"   CID: {cid}")
        
        # Retrieve content
        print("\n📥 Retrieving content from IPFS...")
        retrieved = client.cat(cid)
        retrieved_text = retrieved.decode('utf-8')
        
        print(f"   ✅ Retrieved: {retrieved_text}")
        
        # Verify
        if content == retrieved_text:
            print("   ✅ Content verification passed!")
        else:
            print("   ❌ Content verification failed!")
        
        return cid
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def demo_file_storage():
    """Store and retrieve files on IPFS."""
    print("\n" + "="*70)
    print("DEMO 2: File Storage on IPFS")
    print("="*70)
    
    if not check_ipfs_availability():
        print("\n⚠️  Skipping - IPFS daemon not running")
        return
    
    try:
        import ipfshttpclient
        
        client = ipfshttpclient.connect()
        
        # Create a temporary file
        print("\n📝 Creating sample file...")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp:
            tmp.write("This is sample file content.\n")
            tmp.write("It contains multiple lines.\n")
            tmp.write("IPFS will store this file immutably.\n")
            tmp_path = tmp.name
        
        # Add file to IPFS
        print(f"\n📤 Adding file to IPFS: {tmp_path}")
        result = client.add(tmp_path)
        cid = result['Hash']
        
        print(f"   ✅ File added")
        print(f"   CID: {cid}")
        print(f"   Size: {result['Size']} bytes")
        
        # Retrieve file
        print("\n📥 Retrieving file from IPFS...")
        content = client.cat(cid)
        retrieved_text = content.decode('utf-8')
        
        print("   ✅ Retrieved content:")
        print(f"   {retrieved_text}")
        
        # Cleanup
        import os
        os.unlink(tmp_path)
        
        return cid
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def demo_json_storage():
    """Store structured data (JSON) on IPFS."""
    print("\n" + "="*70)
    print("DEMO 3: Structured Data (JSON) Storage")
    print("="*70)
    
    if not check_ipfs_availability():
        print("\n⚠️  Skipping - IPFS daemon not running")
        return
    
    try:
        import ipfshttpclient
        
        client = ipfshttpclient.connect()
        
        # Create structured data
        data = {
            "dataset": "sample_dataset",
            "version": "1.0.0",
            "records": [
                {"id": 1, "name": "Alice", "score": 95},
                {"id": 2, "name": "Bob", "score": 87},
                {"id": 3, "name": "Charlie", "score": 92},
            ],
            "metadata": {
                "created": "2024-01-01",
                "author": "Example Author"
            }
        }
        
        print("\n📊 Storing JSON data on IPFS...")
        print(f"   Records: {len(data['records'])}")
        
        # Convert to JSON and add
        json_str = json.dumps(data, indent=2)
        result = client.add_str(json_str)
        cid = result
        
        print(f"   ✅ Data stored")
        print(f"   CID: {cid}")
        
        # Retrieve and parse
        print("\n📥 Retrieving and parsing JSON...")
        retrieved = client.cat(cid)
        parsed_data = json.loads(retrieved.decode('utf-8'))
        
        print(f"   ✅ Retrieved dataset: {parsed_data['dataset']}")
        print(f"   Records: {len(parsed_data['records'])}")
        
        return cid
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def demo_directory_storage():
    """Store a directory structure on IPFS."""
    print("\n" + "="*70)
    print("DEMO 4: Directory Storage")
    print("="*70)
    
    if not check_ipfs_availability():
        print("\n⚠️  Skipping - IPFS daemon not running")
        return
    
    try:
        import ipfshttpclient
        import os
        
        client = ipfshttpclient.connect()
        
        # Create temporary directory with files
        print("\n📁 Creating sample directory...")
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files
            (Path(tmpdir) / "file1.txt").write_text("Content of file 1")
            (Path(tmpdir) / "file2.txt").write_text("Content of file 2")
            
            # Create subdirectory
            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()
            (subdir / "file3.txt").write_text("Content of file 3")
            
            print(f"   Created directory with 3 files")
            
            # Add directory to IPFS
            print(f"\n📤 Adding directory to IPFS...")
            result = client.add(tmpdir, recursive=True)
            
            # Get root CID (last item)
            root_cid = result[-1]['Hash']
            
            print(f"   ✅ Directory added")
            print(f"   Root CID: {root_cid}")
            print(f"   Total items: {len(result)}")
            
            # List directory contents
            print("\n📋 Directory contents on IPFS:")
            for item in result:
                print(f"      - {item['Name']} ({item['Hash']})")
            
            return root_cid
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def demo_pinning():
    """Demonstrate IPFS pinning for persistence."""
    print("\n" + "="*70)
    print("DEMO 5: IPFS Pinning")
    print("="*70)
    
    if not check_ipfs_availability():
        print("\n⚠️  Skipping - IPFS daemon not running")
        return
    
    try:
        import ipfshttpclient
        
        client = ipfshttpclient.connect()
        
        # Add content
        print("\n📤 Adding content...")
        content = "Important data that should be pinned."
        result = client.add_str(content)
        cid = result
        
        print(f"   CID: {cid}")
        
        # Pin the content
        print("\n📌 Pinning content...")
        client.pin.add(cid)
        print("   ✅ Content pinned")
        
        # List pinned items
        print("\n📋 Checking pin status...")
        pins = client.pin.ls(type='all')
        if cid in pins['Keys']:
            print(f"   ✅ {cid} is pinned")
        
        # Note: Unpinning is optional
        print("\n💡 Pinned content will persist across garbage collection")
        print("   To unpin: client.pin.rm(cid)")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


def show_tips():
    """Show tips for IPFS storage."""
    print("\n" + "="*70)
    print("TIPS FOR IPFS STORAGE")
    print("="*70)
    
    print("\n1. Content Addressing:")
    print("   - CIDs are deterministic: same content = same CID")
    print("   - Content is immutable once stored")
    print("   - Use IPLD for linked data structures")
    
    print("\n2. Pinning:")
    print("   - Pin important content to prevent garbage collection")
    print("   - Use pinning services for redundancy")
    print("   - Consider using Filecoin for long-term storage")
    
    print("\n3. Performance:")
    print("   - Add files in parallel for better throughput")
    print("   - Use chunking for large files")
    print("   - Consider using local IPFS gateway for faster access")
    
    print("\n4. Integration:")
    print("   - Store embeddings on IPFS for decentralized AI")
    print("   - Use IPFS for dataset versioning")
    print("   - Combine with IPLD for graph data structures")
    
    print("\n5. Setup:")
    print("   - Install IPFS: https://docs.ipfs.tech/install/")
    print("   - Initialize: ipfs init")
    print("   - Start daemon: ipfs daemon")
    print("   - Or use ipfs_kit_py for embedded IPFS")
    
    print("\n6. Next Steps:")
    print("   - See IPFS documentation: https://docs.ipfs.tech/")
    print("   - Explore IPLD: https://ipld.io/")


async def main():
    """Run all IPFS storage demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - IPFS STORAGE")
    print("="*70)
    
    # Check availability first
    if not check_ipfs_availability():
        print("\n" + "="*70)
        print("SETUP REQUIRED")
        print("="*70)
        print("\nTo use IPFS features, you need:")
        print("1. Install IPFS: https://docs.ipfs.tech/install/")
        print("2. Initialize: ipfs init")
        print("3. Start daemon: ipfs daemon")
        print("\nThen run this example again.")
        return
    
    await demo_basic_ipfs_operations()
    await demo_file_storage()
    await demo_json_storage()
    await demo_directory_storage()
    await demo_pinning()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ IPFS STORAGE EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
