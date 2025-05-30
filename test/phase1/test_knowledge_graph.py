import os
import sys
import unittest
import tempfile
import shutil
from typing import Dict, List, Any, Optional

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

# Import the modules to test
try:
    from ipfs_datasets_py.knowledge_graph_extraction import Entity, Relationship, KnowledgeGraph, KnowledgeGraphExtractor
    MODULE_AVAILABLE = True
except ImportError:
    MODULE_AVAILABLE = False

class TestEntity(unittest.TestCase):
    """Test the Entity class."""

    def setUp(self):
        """Set up test fixtures before each test"""
        if not MODULE_AVAILABLE:
            self.skipTest("Entity module not available")

    def test_entity_creation(self):
        """Test Entity creation and properties"""
        # Create an entity
        entity = Entity(
            entity_id="E001",
            entity_type="person",
            name="John Doe",
            properties={"age": 30, "occupation": "software developer"}
        )

        # Check properties
        self.assertEqual(entity.entity_id, "E001")
        self.assertEqual(entity.entity_type, "person")
        self.assertEqual(entity.name, "John Doe")
        self.assertEqual(entity.properties["age"], 30)
        self.assertEqual(entity.properties["occupation"], "software developer")

    def test_entity_to_dict(self):
        """Test Entity to_dict method"""
        # Create an entity
        entity = Entity(
            entity_id="E001",
            entity_type="person",
            name="John Doe",
            properties={"age": 30, "occupation": "software developer"}
        )

        # Convert to dict
        entity_dict = entity.to_dict()

        # Check dictionary structure
        self.assertEqual(entity_dict["entity_id"], "E001")
        self.assertEqual(entity_dict["entity_type"], "person")
        self.assertEqual(entity_dict["name"], "John Doe")
        self.assertEqual(entity_dict["properties"]["age"], 30)
        self.assertEqual(entity_dict["properties"]["occupation"], "software developer")

class TestRelationship(unittest.TestCase):
    """Test the Relationship class."""

    def setUp(self):
        """Set up test fixtures before each test"""
        if not MODULE_AVAILABLE:
            self.skipTest("Relationship module not available")

    def test_relationship_creation(self):
        """Test Relationship creation and properties"""
        # Create entities
        entity1 = Entity(entity_id="E001", entity_type="person", name="John Doe")
        entity2 = Entity(entity_id="E002", entity_type="organization", name="Acme Corp")

        # Create relationship
        relationship = Relationship(
            relationship_id="R001",
            relationship_type="works_for",
            source=entity1,
            target=entity2,
            properties={"start_date": "2020-01-15", "position": "engineer"}
        )

        # Check properties
        self.assertEqual(relationship.relationship_id, "R001")
        self.assertEqual(relationship.relationship_type, "works_for")
        self.assertEqual(relationship.source, entity1)
        self.assertEqual(relationship.target, entity2)
        self.assertEqual(relationship.properties["start_date"], "2020-01-15")
        self.assertEqual(relationship.properties["position"], "engineer")

    def test_relationship_to_dict(self):
        """Test Relationship to_dict method"""
        # Create entities
        entity1 = Entity(entity_id="E001", entity_type="person", name="John Doe")
        entity2 = Entity(entity_id="E002", entity_type="organization", name="Acme Corp")

        # Create relationship
        relationship = Relationship(
            relationship_id="R001",
            relationship_type="works_for",
            source=entity1,
            target=entity2,
            properties={"start_date": "2020-01-15", "position": "engineer"}
        )

        # Convert to dict
        rel_dict = relationship.to_dict(include_entities=True)

        # Check dictionary structure
        self.assertEqual(rel_dict["relationship_id"], "R001")
        self.assertEqual(rel_dict["relationship_type"], "works_for")
        self.assertEqual(rel_dict["source"]["entity_id"], "E001")
        self.assertEqual(rel_dict["target"]["entity_id"], "E002")
        self.assertEqual(rel_dict["properties"]["start_date"], "2020-01-15")

        # Convert to dict without including entities
        rel_dict_minimal = relationship.to_dict(include_entities=False)

        # Check that only IDs are included
        self.assertEqual(rel_dict_minimal["source"], "E001")
        self.assertEqual(rel_dict_minimal["target"], "E002")

class TestKnowledgeGraph(unittest.TestCase):
    """Test the KnowledgeGraph class."""

    def setUp(self):
        """Set up test fixtures before each test"""
        if not MODULE_AVAILABLE:
            self.skipTest("KnowledgeGraph module not available")
        self.kg = KnowledgeGraph()

    def test_add_entity(self):
        """Test adding entities to the knowledge graph"""
        # Add entities
        entity1 = self.kg.add_entity("person", "John Doe", {"age": 30})
        entity2 = self.kg.add_entity("organization", "Acme Corp", {"industry": "technology"})

        # Check entity count
        self.assertEqual(len(self.kg.entities), 2)

        # Get entity by ID
        retrieved_entity = self.kg.get_entity_by_id(entity1.entity_id)
        self.assertEqual(retrieved_entity.name, "John Doe")

        # Get entities by type
        person_entities = self.kg.get_entities_by_type("person")
        self.assertEqual(len(person_entities), 1)
        self.assertEqual(person_entities[0].name, "John Doe")

    def test_add_relationship(self):
        """Test adding relationships to the knowledge graph"""
        # Add entities
        entity1 = self.kg.add_entity("person", "John Doe")
        entity2 = self.kg.add_entity("organization", "Acme Corp")
        entity3 = self.kg.add_entity("person", "Jane Smith")

        # Add relationships
        rel1 = self.kg.add_relationship("works_for", entity1, entity2, {"position": "engineer"})
        rel2 = self.kg.add_relationship("manages", entity1, entity3, {"department": "engineering"})

        # Check relationship count
        self.assertEqual(len(self.kg.relationships), 2)

        # Get relationship by ID
        retrieved_rel = self.kg.get_relationship_by_id(rel1.relationship_id)
        self.assertEqual(retrieved_rel.relationship_type, "works_for")

        # Get relationships by type
        manages_rels = self.kg.get_relationships_by_type("manages")
        self.assertEqual(len(manages_rels), 1)
        self.assertEqual(manages_rels[0].properties["department"], "engineering")

        # Get relationships by entity
        john_rels = self.kg.get_relationships_by_entity(entity1)
        self.assertEqual(len(john_rels), 2)  # Both relationships involve John

        # Get relationships between entities
        john_jane_rels = self.kg.get_relationships_between(entity1, entity3)
        self.assertEqual(len(john_jane_rels), 1)
        self.assertEqual(john_jane_rels[0].relationship_type, "manages")

    def test_serialization(self):
        """Test serialization and deserialization of knowledge graph"""
        # Create a knowledge graph with entities and relationships
        entity1 = self.kg.add_entity("person", "John Doe", {"age": 30})
        entity2 = self.kg.add_entity("organization", "Acme Corp", {"industry": "technology"})
        self.kg.add_relationship("works_for", entity1, entity2, {"position": "engineer"})

        # Convert to dictionary
        kg_dict = self.kg.to_dict()

        # Check dictionary structure
        self.assertEqual(len(kg_dict["entities"]), 2)
        self.assertEqual(len(kg_dict["relationships"]), 1)

        # Create a new knowledge graph from the dictionary
        new_kg = KnowledgeGraph.from_dict(kg_dict)

        # Check entity and relationship counts
        self.assertEqual(len(new_kg.entities), 2)
        self.assertEqual(len(new_kg.relationships), 1)

        # Check specific entity and relationship data
        john = new_kg.get_entities_by_name("John Doe")[0]
        acme = new_kg.get_entities_by_name("Acme Corp")[0]
        self.assertEqual(john.properties["age"], 30)
        self.assertEqual(acme.properties["industry"], "technology")

        # Check relationships
        works_for_rels = new_kg.get_relationships_by_type("works_for")
        self.assertEqual(len(works_for_rels), 1)
        self.assertEqual(works_for_rels[0].properties["position"], "engineer")

class TestKnowledgeGraphExtractor(unittest.TestCase):
    """Test the KnowledgeGraphExtractor class."""

    def setUp(self):
        """Set up test fixtures before each test"""
        if not MODULE_AVAILABLE:
            self.skipTest("KnowledgeGraphExtractor module not available")
        self.extractor = KnowledgeGraphExtractor()

    def test_entity_extraction(self):
        """Test extraction of entities from text"""
        text = """John Doe is a software engineer at Acme Corporation.
                 He works with Jane Smith, who leads the AI team.
                 The company is based in New York and was founded in 1985."""

        # Extract entities
        entities = self.extractor.extract_entities(text)

        # Check extracted entities
        entity_names = [e.name for e in entities]
        self.assertIn("John Doe", entity_names)
        self.assertIn("Jane Smith", entity_names)
        self.assertIn("Acme Corporation", entity_names)
        self.assertIn("New York", entity_names)

        # Check entity types
        for entity in entities:
            if entity.name == "John Doe":
                self.assertEqual(entity.entity_type, "person")
            elif entity.name == "Acme Corporation":
                self.assertEqual(entity.entity_type, "organization")
            elif entity.name == "New York":
                self.assertEqual(entity.entity_type, "location")

    def test_relationship_extraction(self):
        """Test extraction of relationships from text"""
        text = """John Doe works for Acme Corporation as a software engineer.
                 He reports to Jane Smith, who manages the engineering team.
                 Acme Corporation is headquartered in New York."""

        # Extract knowledge graph
        kg = self.extractor.extract_knowledge_graph(text)

        # Check extracted relationships
        relationship_types = [r.relationship_type for r in kg.relationships]
        self.assertIn("works_for", relationship_types)
        self.assertIn("reports_to", relationship_types)
        self.assertIn("headquartered_in", relationship_types)
        self.assertIn("manages", relationship_types)

        # Check specific relationships
        for rel in kg.relationships:
            if rel.relationship_type == "works_for":
                self.assertEqual(rel.source.name, "John Doe")
                self.assertEqual(rel.target.name, "Acme Corporation")
                self.assertEqual(rel.properties.get("position"), "software engineer")
            elif rel.relationship_type == "headquartered_in":
                self.assertEqual(rel.source.name, "Acme Corporation")
                self.assertEqual(rel.target.name, "New York")

    def test_full_extraction(self):
        """Test full knowledge graph extraction pipeline"""
        text = """
        Artificial Intelligence (AI) was pioneered by researchers like Alan Turing and John McCarthy.
        Turing developed the Turing Test in 1950, which measures a machine's ability to exhibit intelligent behavior.
        McCarthy organized the Dartmouth Conference in 1956, which is considered the founding event of AI as a field.

        Deep Learning, a subfield of AI, has been revolutionized by Geoffrey Hinton, who works at Google Brain.
        His research on neural networks has led to breakthroughs in image recognition and natural language processing.
        Another key figure is Yann LeCun, who leads AI research at Facebook and developed convolutional neural networks.

        OpenAI, founded by Elon Musk and Sam Altman in 2015, created GPT models that have transformed text generation.
        DeepMind, acquired by Google in 2014, developed AlphaGo, which defeated world champion Lee Sedol in 2016.
        """

        # Extract full knowledge graph
        kg = self.extractor.extract_knowledge_graph(text)

        # Check entities
        self.assertGreaterEqual(len(kg.entities), 10)  # Should extract many entities

        # Check relationships
        self.assertGreaterEqual(len(kg.relationships), 5)  # Should extract several relationships

        # Check specific semantic information was captured
        ai_entities = kg.get_entities_by_name("Artificial Intelligence")
        self.assertTrue(any(e.entity_type == "field" for e in ai_entities))

        # Verify some key relationships were captured
        found_pioneer_relationship = False
        for rel in kg.relationships:
            if rel.relationship_type == "pioneered" and "Turing" in rel.source.name:
                found_pioneer_relationship = True
                break
        self.assertTrue(found_pioneer_relationship)

if __name__ == '__main__':
    unittest.main()
