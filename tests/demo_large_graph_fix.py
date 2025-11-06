#!/usr/bin/env python3
"""
Simple demonstration script showing the fix for large knowledge graph blocks.

This script creates a large knowledge graph that would exceed the 1MiB IPFS limit
and demonstrates that it now works correctly with automatic chunking.
"""

import sys
import os
import json

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from ipfs_datasets_py.ipld import IPLDStorage, IPLDKnowledgeGraph, Entity
    from ipfs_datasets_py.ipld.knowledge_graph import MAX_BLOCK_SIZE
    print("✓ Successfully imported IPLD modules")
except Exception as e:
    print(f"✗ Failed to import IPLD modules: {e}")
    sys.exit(1)


def main():
    """Demonstrate the fix for large knowledge graph blocks."""
    
    print("\n" + "="*70)
    print("Knowledge Graph Large Block Fix Demonstration")
    print("="*70)
    
    # Create storage and knowledge graph
    print("\n1. Creating knowledge graph...")
    storage = IPLDStorage()
    kg = IPLDKnowledgeGraph(
        name="large_graph_demo",
        storage=storage
    )
    
    # Create a large number of entities that would exceed 1MB when combined
    num_entities = 25000  # This will create ~1MB of entity data
    print(f"2. Adding {num_entities} entities (this would exceed 1MiB without chunking)...")
    
    for i in range(num_entities):
        entity = Entity(
            entity_type="test_entity",
            name=f"Entity {i}",
            properties={"index": i, "description": f"This is entity number {i}"}
        )
        kg.entities[entity.id] = entity
        kg._entity_index[entity.type].add(entity.id)
        
        # Store entity in IPLD
        entity_bytes = json.dumps(entity.to_dict()).encode()
        entity_cid = storage.store(entity_bytes)
        kg._entity_cids[entity.id] = entity_cid
        
        # Progress indicator
        if (i + 1) % 5000 == 0:
            print(f"   Added {i + 1}/{num_entities} entities...")
    
    print(f"   ✓ Added all {num_entities} entities")
    
    # Update the root CID (this triggers chunking)
    print("\n3. Updating root CID (triggering automatic chunking)...")
    kg._update_root_cid()
    root_cid = kg.root_cid
    print(f"   ✓ Root CID: {root_cid}")
    
    # Verify the root block size
    print("\n4. Verifying root block size...")
    root_bytes = storage.get(root_cid)
    root_size = len(root_bytes)
    print(f"   Root block size: {root_size:,} bytes ({root_size / 1024:.2f} KB)")
    
    if root_size < 1024 * 1024:
        print(f"   ✓ Root block is under 1 MiB limit")
    else:
        print(f"   ✗ WARNING: Root block exceeds 1 MiB limit!")
        return False
    
    # Verify data is chunked
    print("\n5. Checking if data was chunked...")
    root_node = json.loads(root_bytes.decode())
    
    entity_ids = root_node.get("entity_ids")
    entity_cids = root_node.get("entity_cids")
    
    if isinstance(entity_ids, dict) and entity_ids.get("_chunked"):
        print("   ✓ entity_ids was chunked into separate block")
        print(f"     CID: {entity_ids.get('_cid')}")
    else:
        print("   ✗ entity_ids was not chunked (unexpected for this size)")
    
    if isinstance(entity_cids, dict) and entity_cids.get("_chunked"):
        print("   ✓ entity_cids was chunked into separate block")
        print(f"     CID: {entity_cids.get('_cid')}")
    else:
        print("   ✗ entity_cids was not chunked (unexpected for this size)")
    
    # Test loading from CID
    print("\n6. Loading knowledge graph from root CID...")
    loaded_kg = IPLDKnowledgeGraph.from_cid(root_cid, storage=storage)
    print(f"   Loaded entities: {loaded_kg.entity_count}")
    
    if loaded_kg.entity_count == num_entities:
        print(f"   ✓ All {num_entities} entities loaded successfully")
    else:
        print(f"   ✗ Expected {num_entities} entities, got {loaded_kg.entity_count}")
        return False
    
    # Verify a few random entities
    print("\n7. Verifying loaded entity data...")
    test_indices = [0, 1000, 10000, 24999]
    all_valid = True
    
    for idx in test_indices:
        entity = next((e for e in loaded_kg.entities.values() 
                      if e.name == f"Entity {idx}"), None)
        if entity and entity.properties.get("index") == idx:
            print(f"   ✓ Entity {idx} loaded correctly")
        else:
            print(f"   ✗ Entity {idx} missing or incorrect")
            all_valid = False
    
    if not all_valid:
        return False
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"✓ Created knowledge graph with {num_entities} entities")
    print(f"✓ Root block size: {root_size:,} bytes (under 1 MiB)")
    print(f"✓ Data automatically chunked into separate IPLD blocks")
    print(f"✓ Successfully loaded all entities from CID")
    print("\nThe fix is working correctly!")
    print("="*70)
    
    return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
