"""
Test for Knowledge Graph Large Block Handling

This test validates that the knowledge graph correctly handles large
entity and relationship collections by chunking them into separate
IPLD blocks when they exceed the 1MiB IPFS limit.

GIVEN a knowledge graph with a large number of entities and relationships
WHEN the root CID is updated
THEN the data should be split into separate blocks to avoid the 1MiB limit
AND the graph should be loadable from the root CID with all data intact
"""

import os
import sys
import json
import tempfile
import shutil
import unittest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

try:
    from ipfs_datasets_py.ipld import IPLDStorage, IPLDKnowledgeGraph, Entity, Relationship
    from ipfs_datasets_py.ipld.knowledge_graph import MAX_BLOCK_SIZE
    IPLD_AVAILABLE = True
except ImportError as e:
    print(f"Warning: IPLD modules not available: {e}")
    IPLD_AVAILABLE = False


class TestKnowledgeGraphLargeBlocks(unittest.TestCase):
    """Test cases for handling large knowledge graphs that exceed 1MiB block size."""

    def setUp(self):
        """Set up test environment."""
        if not IPLD_AVAILABLE:
            self.skipTest("IPLD modules not available")
        
        # Create temporary directory for test data
        self.temp_dir = tempfile.mkdtemp()

        # Create a simple IPLD storage
        self.storage = IPLDStorage()

        # Create a knowledge graph
        self.kg = IPLDKnowledgeGraph(
            name="large_test_graph",
            storage=self.storage,
            vector_store=None
        )

    def tearDown(self):
        """Clean up after tests."""
        # Clean up temp directory
        if hasattr(self, 'temp_dir'):
            shutil.rmtree(self.temp_dir)

    def test_small_graph_inline_storage(self):
        """
        GIVEN a knowledge graph with a small number of entities
        WHEN the root CID is updated
        THEN the data should be stored inline without chunking
        """
        # Add a few entities (small enough to fit inline)
        for i in range(10):
            self.kg.add_entity(
                entity_type="test_entity",
                name=f"Entity {i}",
                properties={"index": i}
            )
        
        # Get the root CID
        root_cid = self.kg.root_cid
        self.assertIsNotNone(root_cid)
        
        # Load the root node and verify it's inline
        root_bytes = self.storage.get(root_cid)
        root_node = json.loads(root_bytes.decode())
        
        # Verify entity_ids is inline (not chunked)
        self.assertIsInstance(root_node.get("entity_ids"), list)
        self.assertEqual(len(root_node["entity_ids"]), 10)
        
        # Verify entity_cids is inline (not chunked)
        self.assertIsInstance(root_node.get("entity_cids"), dict)
        self.assertEqual(len(root_node["entity_cids"]), 10)

    def test_large_graph_chunked_storage(self):
        """
        GIVEN a knowledge graph with a large number of entities
        WHEN the root CID is updated
        THEN the data should be chunked into separate blocks
        """
        # Create enough entities to exceed the block size threshold
        # Each entity ID is ~36 chars (UUID), so we need ~25,000 entities to exceed 800KB
        num_entities = 30000
        
        print(f"\nCreating {num_entities} entities to test chunking...")
        
        # Add entities in batches to avoid slowdown
        for i in range(num_entities):
            entity = Entity(
                entity_type="test_entity",
                name=f"Entity {i}",
                properties={"index": i}
            )
            self.kg.entities[entity.id] = entity
            self.kg._entity_index[entity.type].add(entity.id)
            self.kg._entity_cids[entity.id] = f"bafytest{i:010d}"
            
            # Print progress every 5000 entities
            if (i + 1) % 5000 == 0:
                print(f"  Added {i + 1} entities...")
        
        # Manually trigger root CID update
        self.kg._update_root_cid()
        
        # Get the root CID
        root_cid = self.kg.root_cid
        self.assertIsNotNone(root_cid)
        
        # Load the root node
        root_bytes = self.storage.get(root_cid)
        root_node = json.loads(root_bytes.decode())
        
        # Verify root block is under 1MB
        self.assertLess(len(root_bytes), 1024 * 1024, 
                       f"Root block size {len(root_bytes)} exceeds 1MB limit")
        
        # Verify entity_ids is chunked (should be a dict with _cid and _chunked)
        entity_ids_field = root_node.get("entity_ids")
        self.assertIsInstance(entity_ids_field, dict)
        self.assertTrue(entity_ids_field.get("_chunked"), 
                       "entity_ids should be marked as chunked")
        self.assertIn("_cid", entity_ids_field, 
                     "entity_ids should have a CID reference")
        
        # Verify entity_cids is chunked
        entity_cids_field = root_node.get("entity_cids")
        self.assertIsInstance(entity_cids_field, dict)
        self.assertTrue(entity_cids_field.get("_chunked"), 
                       "entity_cids should be marked as chunked")
        self.assertIn("_cid", entity_cids_field, 
                     "entity_cids should have a CID reference")
        
        print(f"  Root block size: {len(root_bytes)} bytes (under 1MB limit)")
        print(f"  entity_ids chunked: {entity_ids_field.get('_chunked')}")
        print(f"  entity_cids chunked: {entity_cids_field.get('_chunked')}")

    def test_large_graph_load_from_cid(self):
        """
        GIVEN a knowledge graph with chunked data
        WHEN loading from the root CID
        THEN all entities and relationships should be loaded correctly
        """
        # Create a large graph with chunked data
        num_entities = 30000
        
        print(f"\nCreating {num_entities} entities for load test...")
        
        for i in range(num_entities):
            entity = Entity(
                entity_type="test_entity",
                name=f"Entity {i}",
                properties={"index": i}
            )
            self.kg.entities[entity.id] = entity
            self.kg._entity_index[entity.type].add(entity.id)
            
            # Store entity in IPLD
            entity_bytes = json.dumps(entity.to_dict()).encode()
            entity_cid = self.storage.store(entity_bytes)
            self.kg._entity_cids[entity.id] = entity_cid
            
            if (i + 1) % 5000 == 0:
                print(f"  Added {i + 1} entities...")
        
        # Update root CID
        self.kg._update_root_cid()
        root_cid = self.kg.root_cid
        
        print(f"  Loading graph from CID: {root_cid}")
        
        # Load the graph from CID
        loaded_kg = IPLDKnowledgeGraph.from_cid(
            root_cid,
            storage=self.storage
        )
        
        # Verify all entities were loaded
        self.assertEqual(loaded_kg.entity_count, num_entities,
                        "All entities should be loaded from chunked data")
        
        # Verify entity CIDs were loaded correctly
        self.assertEqual(len(loaded_kg._entity_cids), num_entities,
                        "All entity CIDs should be loaded")
        
        # Verify a few random entities
        for i in [0, 100, 1000, 10000, 29999]:
            entity = next((e for e in loaded_kg.entities.values() 
                          if e.name == f"Entity {i}"), None)
            self.assertIsNotNone(entity, f"Entity {i} should be loaded")
            self.assertEqual(entity.properties.get("index"), i)
        
        print(f"  Successfully loaded {loaded_kg.entity_count} entities")

    def test_large_relationships_chunked_storage(self):
        """
        GIVEN a knowledge graph with a large number of relationships
        WHEN the root CID is updated
        THEN the relationship data should be chunked
        """
        # Create entities
        num_entities = 100
        for i in range(num_entities):
            entity = Entity(
                entity_type="test_entity",
                name=f"Entity {i}"
            )
            self.kg.entities[entity.id] = entity
            self.kg._entity_index[entity.type].add(entity.id)
            entity_cid = self.storage.store(json.dumps(entity.to_dict()).encode())
            self.kg._entity_cids[entity.id] = entity_cid
        
        # Create many relationships (more than can fit in 800KB)
        # Each relationship ID is ~36 chars, so we need ~25,000 to exceed threshold
        entity_ids = list(self.kg.entities.keys())
        num_relationships = 30000
        
        print(f"\nCreating {num_relationships} relationships...")
        
        for i in range(num_relationships):
            rel = Relationship(
                relationship_type="test_relation",
                source=entity_ids[i % num_entities],
                target=entity_ids[(i + 1) % num_entities]
            )
            self.kg.relationships[rel.id] = rel
            self.kg._relationship_index[rel.type].add(rel.id)
            self.kg._relationship_cids[rel.id] = f"bafyreltest{i:010d}"
            
            if (i + 1) % 5000 == 0:
                print(f"  Added {i + 1} relationships...")
        
        # Update root CID
        self.kg._update_root_cid()
        root_cid = self.kg.root_cid
        
        # Load and verify
        root_bytes = self.storage.get(root_cid)
        root_node = json.loads(root_bytes.decode())
        
        # Verify root block is under 1MB
        self.assertLess(len(root_bytes), 1024 * 1024,
                       f"Root block size {len(root_bytes)} exceeds 1MB")
        
        # Verify relationship data is chunked
        rel_ids_field = root_node.get("relationship_ids")
        self.assertIsInstance(rel_ids_field, dict)
        self.assertTrue(rel_ids_field.get("_chunked"))
        
        rel_cids_field = root_node.get("relationship_cids")
        self.assertIsInstance(rel_cids_field, dict)
        self.assertTrue(rel_cids_field.get("_chunked"))
        
        print(f"  Root block size: {len(root_bytes)} bytes")
        print(f"  relationship_ids chunked: {rel_ids_field.get('_chunked')}")
        print(f"  relationship_cids chunked: {rel_cids_field.get('_chunked')}")

    def test_backward_compatibility_inline_data(self):
        """
        GIVEN a knowledge graph with inline (non-chunked) data
        WHEN loading from the root CID
        THEN the graph should load correctly for backward compatibility
        """
        # Create a small graph
        for i in range(5):
            self.kg.add_entity(
                entity_type="test_entity",
                name=f"Entity {i}"
            )
        
        root_cid = self.kg.root_cid
        
        # Load the graph
        loaded_kg = IPLDKnowledgeGraph.from_cid(root_cid, storage=self.storage)
        
        # Verify entities were loaded
        self.assertEqual(loaded_kg.entity_count, 5)
        
        # Verify entity names
        for i in range(5):
            entity = next((e for e in loaded_kg.entities.values() 
                          if e.name == f"Entity {i}"), None)
            self.assertIsNotNone(entity)


if __name__ == "__main__":
    unittest.main(verbosity=2)
