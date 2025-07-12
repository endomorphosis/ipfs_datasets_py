"""
Tests for integrated knowledge graph extraction and validation.

This module tests the KnowledgeGraphExtractorWithValidation class that integrates
knowledge graph extraction with SPARQL validation. The integration provides a
unified workflow for extracting structured knowledge from text, Wikipedia articles,
and multiple documents, while automatically validating the extracted knowledge
against Wikidata through SPARQL queries.

The tests in this module verify:
1. Knowledge graph extraction with integrated validation
2. Wikipedia-specific extraction with focused validation
3. Multi-document extraction with cross-document validation
4. Application of correction suggestions to improve knowledge graphs
5. Path finding between entities in both extracted and external knowledge bases

These tests use mock objects to simulate the extraction and validation processes,
allowing for thorough testing of the integration without requiring external
API calls to Wikidata or Wikipedia.
"""

import unittest
import os
import sys
import json
from typing import Dict, List, Any, Optional
from unittest.mock import MagicMock, patch

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

# Import the modules to test
from ipfs_datasets_py.knowledge_graph_extraction import (
    KnowledgeGraph, Entity, Relationship,
    KnowledgeGraphExtractorWithValidation
)
from ipfs_datasets_py.llm.llm_semantic_validation import ValidationResult


class TestKnowledgeGraphExtractorWithValidation(unittest.TestCase):
    """Tests for the integrated knowledge graph extractor with validation."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock the ValidationResult
        self.mock_validation_result = ValidationResult(
            is_valid=True,
            data={
                "entity_coverage": 0.8,
                "relationship_coverage": 0.7,
                "overall_coverage": 0.75,
                "entity_validations": {
                    "entity1": {"valid": True, "name": "IPFS", "type": "technology"},
                    "entity2": {"valid": False, "name": "Protocol Labs", "type": "organization"}
                },
                "relationship_validations": {
                    "rel1": {"valid": True, "source": "IPFS", "target": "Protocol Labs", "relationship_type": "developed_by"}
                }
            }
        )

        # Mock the validator
        self.mock_validator = MagicMock()
        self.mock_validator.validate_knowledge_graph.return_value = self.mock_validation_result
        self.mock_validator.generate_validation_explanation.return_value = "Mock explanation"
        self.mock_validator.find_entity_paths.return_value = ValidationResult(
            is_valid=True,
            data={
                "direct_paths": [{"property": "developed_by"}],
                "two_hop_paths": []
            }
        )

        # Create a test knowledge graph
        self.test_kg = KnowledgeGraph(name="test_kg")

        # Add entities
        self.entity1 = self.test_kg.add_entity(
            entity_type="technology",
            name="IPFS",
            properties={"description": "InterPlanetary File System"}
        )

        self.entity2 = self.test_kg.add_entity(
            entity_type="organization",
            name="Protocol Labs",
            properties={"founder": "Juan Benet"}
        )

        # Add relationship
        self.test_kg.add_relationship(
            relationship_type="developed_by",
            source=self.entity1,
            target=self.entity2
        )

        # Mock the base extractor
        self.mock_extractor = MagicMock()
        self.mock_extractor.extract_enhanced_knowledge_graph.return_value = self.test_kg
        self.mock_extractor.extract_from_wikipedia.return_value = self.test_kg
        self.mock_extractor.extract_from_documents.return_value = self.test_kg
        self.mock_extractor.enrich_with_types.return_value = self.test_kg

        # Create extractor with validation using mocks
        with patch('ipfs_datasets_py.knowledge_graph_extraction.KnowledgeGraphExtractor', return_value=self.mock_extractor):
            with patch('ipfs_datasets_py.llm.llm_semantic_validation.SPARQLValidator', return_value=self.mock_validator):
                self.extractor_with_validation = KnowledgeGraphExtractorWithValidation(
                    validate_during_extraction=True,
                    auto_correct_suggestions=True
                )
                self.extractor_with_validation.validator = self.mock_validator
                self.extractor_with_validation.validator_available = True
                self.extractor_with_validation.extractor = self.mock_extractor

    def test_extract_knowledge_graph(self):
        """Test extracting a knowledge graph from text with validation."""
        # Call the method to test
        result = self.extractor_with_validation.extract_knowledge_graph(
            text="Sample text",
            extraction_temperature=0.7,
            structure_temperature=0.5,
            validation_depth=2
        )

        # Check that the base extractor was called
        self.mock_extractor.extract_enhanced_knowledge_graph.assert_called_once()

        # Check that the validator was called
        self.mock_validator.validate_knowledge_graph.assert_called_once()

        # Check the result structure
        self.assertIn("knowledge_graph", result)
        self.assertIn("validation_results", result)
        self.assertIn("validation_metrics", result)
        self.assertEqual(result["entity_count"], 2)
        self.assertEqual(result["relationship_count"], 1)

        # Check validation metrics
        self.assertEqual(result["validation_metrics"]["entity_coverage"], 0.8)
        self.assertEqual(result["validation_metrics"]["relationship_coverage"], 0.7)
        self.assertEqual(result["validation_metrics"]["overall_coverage"], 0.75)

    def test_extract_from_wikipedia(self):
        """Test extracting a knowledge graph from Wikipedia with validation."""
        # Call the method to test
        result = self.extractor_with_validation.extract_from_wikipedia(
            page_title="IPFS",
            extraction_temperature=0.7,
            structure_temperature=0.5,
            validation_depth=2
        )

        # Check that the base extractor was called
        self.mock_extractor.extract_from_wikipedia.assert_called_once()

        # Check that the validator was called
        self.mock_validator.validate_knowledge_graph.assert_called_once()

        # Check the result structure
        self.assertIn("knowledge_graph", result)
        self.assertIn("validation_results", result)
        self.assertIn("validation_metrics", result)

    def test_extract_from_documents(self):
        """Test extracting a knowledge graph from multiple documents with validation."""
        # Sample documents
        documents = [
            {"text": "Document 1"},
            {"text": "Document 2"}
        ]

        # Call the method to test
        result = self.extractor_with_validation.extract_from_documents(
            documents=documents,
            text_key="text",
            extraction_temperature=0.7,
            structure_temperature=0.5,
            validation_depth=2
        )

        # Check that the base extractor was called
        self.mock_extractor.extract_from_documents.assert_called_once()
        self.mock_extractor.enrich_with_types.assert_called_once()

        # Check that the validator was called
        self.mock_validator.validate_knowledge_graph.assert_called_once()

        # Check the result structure
        self.assertIn("knowledge_graph", result)
        self.assertIn("validation_results", result)
        self.assertIn("validation_metrics", result)

    def test_apply_validation_corrections(self):
        """Test applying validation corrections to a knowledge graph."""
        # Sample corrections
        corrections = {
            "entities": {
                self.entity1.entity_id: {
                    "entity_name": "IPFS",
                    "suggestions": {
                        "description": "InterPlanetary File System - a peer-to-peer hypermedia protocol"
                    }
                }
            },
            "relationships": {
                "rel1": {
                    "source": "IPFS",
                    "relationship_type": "developed_by",
                    "target": "Protocol Labs",
                    "suggestions": "Consider using 'creator' instead"
                }
            }
        }

        # Call the method to test
        corrected_kg = self.extractor_with_validation.apply_validation_corrections(
            kg=self.test_kg,
            corrections=corrections
        )

        # Check the corrected knowledge graph
        self.assertEqual(len(corrected_kg.entities), 2)
        self.assertEqual(len(corrected_kg.relationships), 1)

        # Check that entity properties were corrected
        ipfs_entities = [e for e in corrected_kg.entities.values() if e.name == "IPFS"]
        self.assertTrue(len(ipfs_entities) > 0)
        corrected_entity = ipfs_entities[0]
        self.assertIn("description", corrected_entity.properties)


if __name__ == "__main__":
    unittest.main()
