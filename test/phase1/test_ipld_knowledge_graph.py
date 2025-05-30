"""
Test IPLD Knowledge Graph Module

This module contains tests for the IPLDKnowledgeGraph class which implements
IPLD-based knowledge graph with entity and relationship modeling.
"""

import os
import numpy as np
import tempfile
import shutil
import unittest
from typing import List, Dict, Any

from ipfs_datasets_py.ipld import (
    IPLDStorage, IPLDVectorStore, IPLDKnowledgeGraph,
    Entity, Relationship
)

class TestIPLDKnowledgeGraph(unittest.TestCase):
    """Test cases for the IPLDKnowledgeGraph class."""

    def setUp(self):
        """Set up test environment."""
        # Create temporary directory for test data
        self.temp_dir = tempfile.mkdtemp()

        # Create a simple IPLD storage
        self.storage = IPLDStorage()

        # Create a vector store for testing
        self.vector_store = IPLDVectorStore(
            dimension=10,
            metric="cosine",
            storage=self.storage
        )

        # Create a knowledge graph
        self.kg = IPLDKnowledgeGraph(
            name="test_graph",
            storage=self.storage,
            vector_store=self.vector_store
        )

        # Create test vectors for entities
        self.test_vectors = [
            np.array([1, 0, 0, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32),
            np.array([0, 1, 0, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32),
            np.array([0, 0, 1, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32),
            np.array([0, 0, 0, 1, 0, 0, 0, 0, 0, 0], dtype=np.float32),
            np.array([0, 0, 0, 0, 1, 0, 0, 0, 0, 0], dtype=np.float32),
        ]

    def tearDown(self):
        """Clean up after tests."""
        # Clean up temp directory
        shutil.rmtree(self.temp_dir)

    def test_add_entity(self):
        """Test adding entities to the graph."""
        # Add an entity
        entity = self.kg.add_entity(
            entity_type="person",
            name="Alice",
            properties={"age": 30, "occupation": "Engineer"},
            vector=self.test_vectors[0]
        )

        # Check if the entity was added
        self.assertEqual(self.kg.entity_count, 1)

        # Get the entity
        retrieved_entity = self.kg.get_entity(entity.id)

        # Check entity data
        self.assertEqual(retrieved_entity.type, "person")
        self.assertEqual(retrieved_entity.name, "Alice")
        self.assertEqual(retrieved_entity.properties["age"], 30)
        self.assertEqual(retrieved_entity.properties["occupation"], "Engineer")

        # Check if the entity has a vector ID
        self.assertIn("vector_ids", retrieved_entity.properties)
        self.assertEqual(len(retrieved_entity.properties["vector_ids"]), 1)

    def test_add_relationship(self):
        """Test adding relationships between entities."""
        # Add two entities
        alice = self.kg.add_entity(
            entity_type="person",
            name="Alice",
            properties={"age": 30}
        )

        bob = self.kg.add_entity(
            entity_type="person",
            name="Bob",
            properties={"age": 35}
        )

        # Add a relationship
        relationship = self.kg.add_relationship(
            relationship_type="knows",
            source=alice,
            target=bob,
            properties={"since": 2020}
        )

        # Check if the relationship was added
        self.assertEqual(self.kg.relationship_count, 1)

        # Get the relationship
        retrieved_rel = self.kg.get_relationship(relationship.id)

        # Check relationship data
        self.assertEqual(retrieved_rel.type, "knows")
        self.assertEqual(retrieved_rel.source_id, alice.id)
        self.assertEqual(retrieved_rel.target_id, bob.id)
        self.assertEqual(retrieved_rel.properties["since"], 2020)

        # Get relationships for Alice
        alice_rels = self.kg.get_entity_relationships(alice.id)
        self.assertEqual(len(alice_rels), 1)

        # Get outgoing relationships for Alice
        alice_outgoing = self.kg.get_entity_relationships(alice.id, direction="outgoing")
        self.assertEqual(len(alice_outgoing), 1)

        # Get incoming relationships for Alice
        alice_incoming = self.kg.get_entity_relationships(alice.id, direction="incoming")
        self.assertEqual(len(alice_incoming), 0)

        # Get relationships for Bob
        bob_rels = self.kg.get_entity_relationships(bob.id)
        self.assertEqual(len(bob_rels), 1)

        # Get incoming relationships for Bob
        bob_incoming = self.kg.get_entity_relationships(bob.id, direction="incoming")
        self.assertEqual(len(bob_incoming), 1)

    def test_query(self):
        """Test querying the graph."""
        # Create a small graph
        alice = self.kg.add_entity(entity_type="person", name="Alice")
        bob = self.kg.add_entity(entity_type="person", name="Bob")
        carol = self.kg.add_entity(entity_type="person", name="Carol")
        dave = self.kg.add_entity(entity_type="person", name="Dave")

        company = self.kg.add_entity(entity_type="company", name="Tech Corp")

        # Add relationships
        self.kg.add_relationship("knows", alice, bob)
        self.kg.add_relationship("knows", bob, carol)
        self.kg.add_relationship("knows", carol, dave)

        self.kg.add_relationship("works_at", alice, company)
        self.kg.add_relationship("works_at", bob, company)

        # Query: Find people Alice knows (directly)
        query_results = self.kg.query(alice, ["knows"])
        self.assertEqual(len(query_results), 1)
        self.assertEqual(query_results[0]["entity"].name, "Bob")

        # Query: Find people Alice knows through one intermediate person
        query_results = self.kg.query(alice, ["knows", "knows"])
        self.assertEqual(len(query_results), 1)
        self.assertEqual(query_results[0]["entity"].name, "Carol")

        # Query: Find people Alice knows through two intermediate people
        query_results = self.kg.query(alice, ["knows", "knows", "knows"])
        self.assertEqual(len(query_results), 1)
        self.assertEqual(query_results[0]["entity"].name, "Dave")

        # Query: Find companies where Alice works
        query_results = self.kg.query(alice, ["works_at"])
        self.assertEqual(len(query_results), 1)
        self.assertEqual(query_results[0]["entity"].name, "Tech Corp")

        # Query: Find people who work at the same company as Alice
        # This would require a more complex query in a real graph database
        # But we can simulate it with our simple query mechanism
        company_results = self.kg.query(alice, ["works_at"])
        company = company_results[0]["entity"]

        coworker_results = self.kg.query(company, [])  # Empty path to start from the company

        # Find incoming "works_at" relationships to the company
        coworkers = []
        for rel in self.kg.get_entity_relationships(company.id, direction="incoming"):
            if rel.type == "works_at" and rel.source_id != alice.id:
                worker = self.kg.get_entity(rel.source_id)
                coworkers.append(worker)

        self.assertEqual(len(coworkers), 1)
        self.assertEqual(coworkers[0].name, "Bob")

    def test_vector_augmented_query(self):
        """Test vector-augmented queries."""
        # Skip if vector_store is not available
        if self.vector_store is None:
            self.skipTest("Vector store is not available")

        # Create a small graph with vectors
        alice = self.kg.add_entity(
            entity_type="person",
            name="Alice",
            vector=self.test_vectors[0]
        )

        bob = self.kg.add_entity(
            entity_type="person",
            name="Bob",
            vector=self.test_vectors[1]
        )

        carol = self.kg.add_entity(
            entity_type="person",
            name="Carol",
            vector=self.test_vectors[2]
        )

        # Add relationships
        self.kg.add_relationship("knows", alice, bob)
        self.kg.add_relationship("knows", bob, carol)

        # Create a query vector most similar to Alice
        query_vector = np.array([0.9, 0.1, 0, 0, 0, 0, 0, 0, 0, 0], dtype=np.float32)

        # Perform vector-augmented query
        results = self.kg.vector_augmented_query(
            query_vector,
            top_k=3,
            max_hops=1
        )

        # Check if we got 3 results (Alice, Bob, Carol)
        self.assertEqual(len(results), 3)

        # Alice should be the first result (most similar to query)
        self.assertEqual(results[0]["entity"].name, "Alice")

        # Bob should be connected to Alice
        bob_result = next((r for r in results if r["entity"].name == "Bob"), None)
        self.assertIsNotNone(bob_result)

        # Carol might be included if max_hops > 1
        if any(r["entity"].name == "Carol" for r in results):
            carol_result = next((r for r in results if r["entity"].name == "Carol"), None)
            self.assertGreater(carol_result["hops"], 0)

    def test_export_import_car(self):
        """Test exporting and importing using CAR files."""
        # Skip if ipld_car is not available
        try:
            import ipld_car
        except ImportError:
            self.skipTest("ipld_car is not available")

        # Create a small graph
        alice = self.kg.add_entity(entity_type="person", name="Alice")
        bob = self.kg.add_entity(entity_type="person", name="Bob")

        # Add a relationship
        self.kg.add_relationship("knows", alice, bob)

        # Define CAR file path
        car_path = os.path.join(self.temp_dir, "test_graph.car")

        # Export to CAR file
        root_cid = self.kg.export_to_car(car_path)
        self.assertIsNotNone(root_cid)
        self.assertTrue(os.path.exists(car_path))

        # Import from CAR file
        imported_kg = IPLDKnowledgeGraph.from_car(car_path)

        # Check if the imported graph has the same entities and relationships
        self.assertEqual(imported_kg.entity_count, self.kg.entity_count)
        self.assertEqual(imported_kg.relationship_count, self.kg.relationship_count)

        # Check if the imported graph has the same entity types
        alice_type = next(
            (entity.type for entity in imported_kg.entities.values() if entity.name == "Alice"),
            None
        )
        self.assertEqual(alice_type, "person")

        # Check if the relationship was imported correctly
        alice_entity = next(
            (entity for entity in imported_kg.entities.values() if entity.name == "Alice"),
            None
        )

        if alice_entity:
            alice_rels = imported_kg.get_entity_relationships(alice_entity.id)
            self.assertEqual(len(alice_rels), 1)
            self.assertEqual(alice_rels[0].type, "knows")

if __name__ == "__main__":
    unittest.main()
