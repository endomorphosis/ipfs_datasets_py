"""
Tests for LLM semantic validation and augmentation.

This module tests the semantic validation and augmentation features
for LLM outputs in GraphRAG.
"""

import unittest
import os
import sys
import json
from typing import Dict, List, Any, Optional
from datetime import datetime

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

# Import the modules to test
from ipfs_datasets_py.llm_interface import MockLLMInterface
from ipfs_datasets_py.llm_semantic_validation import (
    SchemaRegistry, SchemaValidator, SemanticAugmenter,
    SemanticValidator, ValidationResult
)


class TestSchemaRegistry(unittest.TestCase):
    """Tests for schema registry functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.registry = SchemaRegistry()
        
        # Register test schemas
        self.test_schema = {
            "type": "object",
            "properties": {
                "test": {"type": "string"}
            },
            "required": ["test"]
        }
        
        self.registry.register_schema("test_domain", "test_task", self.test_schema)
        
        # Register a default schema
        self.default_schema = {
            "type": "object",
            "properties": {
                "default": {"type": "string"}
            },
            "required": ["default"]
        }
        
        self.registry.register_default_schema("test_task", self.default_schema)
    
    def test_register_and_get_schema(self):
        """Test registering and retrieving schemas."""
        # Get the schema we registered
        schema = self.registry.get_schema("test_domain", "test_task")
        
        # Should match the test schema
        self.assertEqual(schema, self.test_schema)
        
        # Try with a non-existent domain
        schema = self.registry.get_schema("non_existent", "test_task")
        
        # Should get the default schema
        self.assertEqual(schema, self.default_schema)
        
        # Try with a non-existent task
        schema = self.registry.get_schema("test_domain", "non_existent")
        
        # Should be None (no default for this task)
        self.assertIsNone(schema)
    
    def test_schema_versioning(self):
        """Test schema versioning."""
        # Register a newer version of the schema
        new_schema = {
            "type": "object",
            "properties": {
                "test": {"type": "string"},
                "additional": {"type": "number"}
            },
            "required": ["test", "additional"]
        }
        
        self.registry.register_schema("test_domain", "test_task", new_schema, version="2.0.0")
        
        # Get without specifying version (should get latest)
        schema = self.registry.get_schema("test_domain", "test_task")
        self.assertEqual(schema, new_schema)
        
        # Get specific version
        schema = self.registry.get_schema("test_domain", "test_task", version="1.0.0")
        self.assertEqual(schema, self.test_schema)
        
        # Get specific version
        schema = self.registry.get_schema("test_domain", "test_task", version="2.0.0")
        self.assertEqual(schema, new_schema)


class TestSchemaValidator(unittest.TestCase):
    """Tests for schema validator functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.registry = SchemaRegistry()
        
        # Register test schemas
        self.test_schema = {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "confidence": {"type": "number"}
            },
            "required": ["answer", "confidence"]
        }
        
        self.registry.register_schema("test_domain", "test_task", self.test_schema)
        
        # Create validator
        self.validator = SchemaValidator(self.registry)
    
    def test_validation_success(self):
        """Test successful validation."""
        # Valid data
        data = {
            "answer": "Test answer",
            "confidence": 0.9
        }
        
        # Validate
        result = self.validator.validate(data, "test_domain", "test_task")
        
        # Should be valid
        self.assertTrue(result.is_valid)
        self.assertEqual(result.data, data)
        self.assertEqual(result.errors, [])
    
    def test_validation_failure(self):
        """Test validation failure."""
        # Invalid data (missing required field)
        data = {
            "answer": "Test answer"
        }
        
        # Validate
        result = self.validator.validate(data, "test_domain", "test_task")
        
        # Should not be valid
        self.assertFalse(result.is_valid)
        self.assertEqual(result.data, data)
        self.assertGreater(len(result.errors), 0)
        
        # Invalid data (wrong type)
        data = {
            "answer": "Test answer",
            "confidence": "high"  # Should be a number
        }
        
        # Validate
        result = self.validator.validate(data, "test_domain", "test_task")
        
        # Should not be valid
        self.assertFalse(result.is_valid)
        self.assertEqual(result.data, data)
        self.assertGreater(len(result.errors), 0)
    
    def test_non_existent_schema(self):
        """Test validation with non-existent schema."""
        # Validate with non-existent schema
        result = self.validator.validate({}, "non_existent", "non_existent")
        
        # Should not be valid
        self.assertFalse(result.is_valid)
        self.assertGreater(len(result.errors), 0)


class TestSemanticAugmenter(unittest.TestCase):
    """Tests for semantic augmenter functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.augmenter = SemanticAugmenter()
    
    def test_basic_augmentation(self):
        """Test basic augmentation."""
        # Data to augment
        data = {
            "answer": "Test answer",
            "confidence": 0.9
        }
        
        # Augment
        augmented = self.augmenter.augment(data, "test_domain", "test_task")
        
        # Check basic augmentation
        self.assertEqual(augmented["answer"], "Test answer")
        self.assertEqual(augmented["confidence"], 0.9)
        self.assertEqual(augmented["domain"], "test_domain")
        self.assertEqual(augmented["task"], "test_task")
        self.assertIn("augmented_at", augmented)
    
    def test_cross_document_reasoning_augmentation(self):
        """Test cross-document reasoning augmentation."""
        # Data to augment
        data = {
            "answer": "The relationship between neural networks and traditional ML methods is complex.",
            "reasoning": "Neural Networks are a subset of Machine Learning techniques that use Deep Learning architectures. Traditional methods like Decision Trees and Support Vector Machines rely on different principles.",
            "confidence": 0.85
        }
        
        # Augment
        augmented = self.augmenter.augment(data, "academic", "cross_document_reasoning")
        
        # Check domain-specific augmentation
        self.assertIn("key_concepts", augmented)
        self.assertIn("uncertainty_assessment", augmented)
        self.assertIn("scholarly_context", augmented)
        
        # Check key concepts extraction
        self.assertTrue(any("Neural Networks" in concept for concept in augmented["key_concepts"]))
        
        # Check uncertainty assessment
        self.assertIn("score", augmented["uncertainty_assessment"])
        self.assertIn("interpretation", augmented["uncertainty_assessment"])
    
    def test_evidence_chain_augmentation(self):
        """Test evidence chain augmentation."""
        # Data to augment
        data = {
            "relationship_type": "complementary",
            "explanation": "The documents provide complementary information about the topic.",
            "inference": "By combining information from both documents, we get a more complete picture.",
            "confidence": 0.9
        }
        
        # Augment
        augmented = self.augmenter.augment(data, "test_domain", "evidence_chain_analysis")
        
        # Check specific augmentation
        self.assertIn("confidence_interpretation", augmented)
        self.assertEqual(augmented["confidence_interpretation"], "high")
        
        self.assertIn("relationship_strength", augmented)
        self.assertEqual(augmented["relationship_strength"], "strong")


class TestSemanticValidator(unittest.TestCase):
    """Tests for semantic validator functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create registry
        self.registry = SchemaRegistry()
        
        # Register test schema
        self.test_schema = {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "confidence": {"type": "number"}
            },
            "required": ["answer", "confidence"]
        }
        
        self.registry.register_schema("test_domain", "test_task", self.test_schema)
        
        # Create validator and augmenter
        self.schema_validator = SchemaValidator(self.registry)
        self.augmenter = SemanticAugmenter()
        
        # Create semantic validator
        self.validator = SemanticValidator(self.schema_validator, self.augmenter)
    
    def test_valid_processing(self):
        """Test processing valid data."""
        # Valid data
        data = {
            "answer": "Test answer",
            "confidence": 0.9
        }
        
        # Process
        success, processed, errors = self.validator.process(data, "test_domain", "test_task")
        
        # Should succeed
        self.assertTrue(success)
        self.assertEqual(len(errors), 0)
        
        # Should have basic augmentation
        self.assertEqual(processed["domain"], "test_domain")
        self.assertEqual(processed["task"], "test_task")
        self.assertIn("augmented_at", processed)
    
    def test_invalid_processing(self):
        """Test processing invalid data."""
        # Invalid data
        data = {
            "answer": "Test answer"
            # Missing confidence
        }
        
        # Process without auto-repair
        success, processed, errors = self.validator.process(
            data, "test_domain", "test_task", auto_repair=False
        )
        
        # Should fail
        self.assertFalse(success)
        self.assertGreater(len(errors), 0)
        
        # Processed data should be the original
        self.assertEqual(processed, data)


class TestSPARQLValidator(unittest.TestCase):
    """Tests for SPARQL validator functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a validator with mocked responses
        self.validator = SPARQLValidator(cache_results=True)
        
        # Mock the _get_wikidata_entity method
        self.original_get_wikidata_entity = self.validator._get_wikidata_entity
        self.validator._get_wikidata_entity = self._mock_get_wikidata_entity
        
        # Mock the _get_entity_properties method
        self.original_get_entity_properties = self.validator._get_entity_properties
        self.validator._get_entity_properties = self._mock_get_entity_properties
        
        # Mock the _check_relationship method
        self.original_check_relationship = self.validator._check_relationship
        self.validator._check_relationship = self._mock_check_relationship
    
    def tearDown(self):
        """Tear down test fixtures."""
        # Restore original methods
        self.validator._get_wikidata_entity = self.original_get_wikidata_entity
        self.validator._get_entity_properties = self.original_get_entity_properties
        self.validator._check_relationship = self.original_check_relationship
    
    def _mock_get_wikidata_entity(self, entity_name, entity_type=None):
        """Mock method for retrieving Wikidata entities."""
        entity_map = {
            "IPFS": {
                "id": "Q22661306",
                "label": "InterPlanetary File System",
                "description": "protocol and peer-to-peer network for storing and sharing data",
                "url": "https://www.wikidata.org/wiki/Q22661306"
            },
            "Juan Benet": {
                "id": "Q57213644",
                "label": "Juan Benet",
                "description": "American computer scientist",
                "url": "https://www.wikidata.org/wiki/Q57213644"
            },
            "Protocol Labs": {
                "id": "Q54872189",
                "label": "Protocol Labs",
                "description": "American technology company",
                "url": "https://www.wikidata.org/wiki/Q54872189"
            }
        }
        
        return entity_map.get(entity_name)
    
    def _mock_get_entity_properties(self, entity_id):
        """Mock method for retrieving Wikidata entity properties."""
        property_map = {
            "Q22661306": [  # IPFS
                {
                    "property": "instance of",
                    "property_id": "P31",
                    "value": "file sharing protocol",
                    "value_uri": "http://www.wikidata.org/entity/Q1172601"
                },
                {
                    "property": "developer",
                    "property_id": "P178",
                    "value": "Protocol Labs",
                    "value_uri": "http://www.wikidata.org/entity/Q54872189"
                },
                {
                    "property": "inception",
                    "property_id": "P571",
                    "value": "2015",
                    "value_uri": "http://www.wikidata.org/entity/Q2015"
                }
            ],
            "Q57213644": [  # Juan Benet
                {
                    "property": "instance of",
                    "property_id": "P31",
                    "value": "human",
                    "value_uri": "http://www.wikidata.org/entity/Q5"
                },
                {
                    "property": "occupation",
                    "property_id": "P106",
                    "value": "computer scientist",
                    "value_uri": "http://www.wikidata.org/entity/Q82594"
                },
                {
                    "property": "employer",
                    "property_id": "P108",
                    "value": "Protocol Labs",
                    "value_uri": "http://www.wikidata.org/entity/Q54872189"
                }
            ],
            "Q54872189": [  # Protocol Labs
                {
                    "property": "instance of",
                    "property_id": "P31",
                    "value": "company",
                    "value_uri": "http://www.wikidata.org/entity/Q783794"
                },
                {
                    "property": "founded by",
                    "property_id": "P112",
                    "value": "Juan Benet",
                    "value_uri": "http://www.wikidata.org/entity/Q57213644"
                },
                {
                    "property": "industry",
                    "property_id": "P452",
                    "value": "software industry",
                    "value_uri": "http://www.wikidata.org/entity/Q40083"
                }
            ]
        }
        
        return property_map.get(entity_id, [])
    
    def _mock_check_relationship(self, source_id, target_id, relationship_type, bidirectional=False):
        """Mock method for checking relationships between Wikidata entities."""
        # Define a map of known relationships
        relationship_map = {
            # IPFS developed by Protocol Labs
            ("Q22661306", "Q54872189", "developed_by"): {
                "exists": True,
                "relationship": {
                    "property": "developer",
                    "property_id": "P178",
                    "direction": "forward"
                },
                "confidence": 0.85
            },
            # Juan Benet works for Protocol Labs
            ("Q57213644", "Q54872189", "works_for"): {
                "exists": True,
                "relationship": {
                    "property": "employer",
                    "property_id": "P108",
                    "direction": "forward"
                },
                "confidence": 0.9
            },
            # Protocol Labs founded by Juan Benet
            ("Q54872189", "Q57213644", "founded_by"): {
                "exists": True,
                "relationship": {
                    "property": "founded by",
                    "property_id": "P112",
                    "direction": "forward"
                },
                "confidence": 0.95
            }
        }
        
        # Check direct relationship
        key = (source_id, target_id, relationship_type)
        if key in relationship_map:
            return relationship_map[key]
            
        # Check reverse relationship if bidirectional
        if bidirectional:
            key = (target_id, source_id, relationship_type)
            if key in relationship_map:
                result = relationship_map[key].copy()
                # Mark it as reverse direction
                if "relationship" in result:
                    result["relationship"] = result["relationship"].copy()
                    result["relationship"]["direction"] = "reverse"
                return result
        
        # No relationship found
        return {
            "exists": False,
            "closest_match": {
                "property": "related to",
                "property_id": "P1365",
                "direction": "forward"
            },
            "confidence": 0.3
        }
    
    def test_validate_entity_success(self):
        """Test successful validation of an entity."""
        # Validate IPFS entity
        result = self.validator.validate_entity(
            entity_name="IPFS",
            entity_type="technology",
            entity_properties={
                "developer": "Protocol Labs",
                "inception": "2015"
            }
        )
        
        # Should be valid
        self.assertTrue(result.is_valid)
        self.assertEqual(result.data["entity"], "IPFS")
        self.assertEqual(result.data["wikidata_entity"]["id"], "Q22661306")
        self.assertIn("developer", result.data["validated_properties"])
        self.assertIn("inception", result.data["validated_properties"])
    
    def test_validate_entity_failure(self):
        """Test failed validation of an entity."""
        # Validate IPFS with incorrect properties
        result = self.validator.validate_entity(
            entity_name="IPFS",
            entity_type="technology",
            entity_properties={
                "developer": "Wrong Developer",
                "inception": "2020"
            }
        )
        
        # Should not be valid
        self.assertFalse(result.is_valid)
        self.assertEqual(result.data["entity"], "IPFS")
        self.assertEqual(result.data["wikidata_entity"]["id"], "Q22661306")
        self.assertGreater(len(result.data["property_mismatches"]), 0)
        self.assertGreater(len(result.errors), 0)
    
    def test_validate_relationship_success(self):
        """Test successful validation of a relationship."""
        # Validate Protocol Labs founded by Juan Benet
        result = self.validator.validate_relationship(
            source_entity="Protocol Labs",
            relationship_type="founded_by",
            target_entity="Juan Benet"
        )
        
        # Should be valid
        self.assertTrue(result.is_valid)
        self.assertEqual(result.data["source"], "Protocol Labs")
        self.assertEqual(result.data["target"], "Juan Benet")
        self.assertEqual(result.data["relationship"], "founded_by")
        self.assertEqual(result.data["wikidata_relationship"]["property"], "founded by")
    
    def test_validate_relationship_failure(self):
        """Test failed validation of a relationship."""
        # Validate non-existent relationship
        result = self.validator.validate_relationship(
            source_entity="IPFS",
            relationship_type="invented_by",
            target_entity="Juan Benet"
        )
        
        # Should not be valid
        self.assertFalse(result.is_valid)
        self.assertEqual(result.data["source"], "IPFS")
        self.assertEqual(result.data["target"], "Juan Benet")
        self.assertEqual(result.data["relationship"], "invented_by")
        self.assertGreater(len(result.errors), 0)
    
    def test_validate_bidirectional_relationship(self):
        """Test validation of a bidirectional relationship."""
        # Validate works_for relationship in both directions
        result1 = self.validator.validate_relationship(
            source_entity="Juan Benet",
            relationship_type="works_for",
            target_entity="Protocol Labs",
            bidirectional=False
        )
        
        result2 = self.validator.validate_relationship(
            source_entity="Protocol Labs",
            relationship_type="works_for",
            target_entity="Juan Benet",
            bidirectional=True  # Allow checking reverse direction
        )
        
        # First direction should be valid
        self.assertTrue(result1.is_valid)
        
        # Second direction should be valid with bidirectional=True
        self.assertTrue(result2.is_valid)
        self.assertEqual(result2.data["wikidata_relationship"]["direction"], "reverse")
    
    def test_string_similarity(self):
        """Test the string similarity calculation."""
        similarity = self.validator._string_similarity(
            "developer of protocol",
            "protocol developer"
        )
        
        # Jaccard similarity with some overlap
        self.assertGreater(similarity, 0.3)
        self.assertLess(similarity, 1.0)
        
        # Identical strings
        similarity = self.validator._string_similarity(
            "identical string",
            "identical string"
        )
        self.assertEqual(similarity, 1.0)
        
        # No overlap
        similarity = self.validator._string_similarity(
            "completely different",
            "entirely unique"
        )
        self.assertEqual(similarity, 0.0)
    
    def test_explanation_generation(self):
        """Test generation of human-readable explanations."""
        # First validate an entity
        validation_result = self.validator.validate_entity(
            entity_name="IPFS",
            entity_type="technology",
            entity_properties={
                "developer": "Protocol Labs",
                "inception": "2015"
            }
        )
        
        # Generate different types of explanations
        summary = self.validator.generate_validation_explanation(
            validation_result,
            explanation_type="summary"
        )
        
        detailed = self.validator.generate_validation_explanation(
            validation_result,
            explanation_type="detailed"
        )
        
        # Check that explanations are generated
        self.assertIsInstance(summary, str)
        self.assertIsInstance(detailed, str)
        
        # Summary should be shorter than detailed
        self.assertLess(len(summary), len(detailed))
        
        # Detailed should contain more information
        self.assertIn("Property Validations", detailed)
        self.assertIn("IPFS", detailed)
        self.assertIn("developer", detailed)


if __name__ == "__main__":
    unittest.main()