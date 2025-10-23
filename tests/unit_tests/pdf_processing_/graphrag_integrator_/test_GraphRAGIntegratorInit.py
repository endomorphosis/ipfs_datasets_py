#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator.py
# Auto-generated on 2025-07-07 02:28:56
import pytest
import os
import asyncio
import re
import time
import networkx as nx
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, KnowledgeGraph, Entity, Relationship
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk



from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

work_dir = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py"
file_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/graphrag_integrator.py")
md_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/graphrag_integrator_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator

# Check if each classes methods are accessible:
assert GraphRAGIntegrator.integrate_document
assert GraphRAGIntegrator._extract_entities_from_chunks
assert GraphRAGIntegrator._extract_entities_from_text
assert GraphRAGIntegrator._extract_relationships
assert GraphRAGIntegrator._extract_chunk_relationships
assert GraphRAGIntegrator._infer_relationship_type
assert GraphRAGIntegrator._extract_cross_chunk_relationships
assert GraphRAGIntegrator._find_chunk_sequences
assert GraphRAGIntegrator._create_networkx_graph
assert GraphRAGIntegrator._merge_into_global_graph
assert GraphRAGIntegrator._discover_cross_document_relationships
assert GraphRAGIntegrator._find_similar_entities
assert GraphRAGIntegrator._calculate_text_similarity
assert GraphRAGIntegrator._store_knowledge_graph_ipld
assert GraphRAGIntegrator.query_graph
assert GraphRAGIntegrator.get_entity_neighborhood


# 4. Check if the modules's imports are accessible:
try:
    import logging
    import hashlib
    from typing import Dict, List, Any, Optional
    from dataclasses import dataclass, asdict
    from datetime import datetime
    import uuid
    import re

    import networkx as nx
    import numpy as np

    from ipfs_datasets_py.ipld import IPLDStorage
    from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
except ImportError as e:
    raise ImportError(f"Could into import the module's dependencies: {e}") 


@pytest.fixture
def test_constants():
    """Provide common test constants to eliminate magic numbers and strings."""
    return {
        'DEFAULT_SIMILARITY_THRESHOLD': 0.8,
        'DEFAULT_ENTITY_EXTRACTION_CONFIDENCE': 0.6,
        'CUSTOM_SIMILARITY_THRESHOLD': 0.9,
        'CUSTOM_ENTITY_EXTRACTION_CONFIDENCE': 0.7,
        'HIGH_SIMILARITY_THRESHOLD': 0.95,
        'HIGH_ENTITY_EXTRACTION_CONFIDENCE': 0.75,
        'BOUNDARY_MIN_VALUE': 0.0,
        'BOUNDARY_MAX_VALUE': 1.0,
        'INVALID_LOW_VALUE': -0.1,
        'INVALID_HIGH_SIMILARITY': 1.5,
        'INVALID_HIGH_CONFIDENCE': 1.2,
        'EMPTY_DICT': {},
        'EMPTY_LIST': [],
        'ZERO_LENGTH': 0,
    }


@pytest.fixture
def default_parameters(test_constants):
    """Fixture to provide default parameters."""
    return {
        "storage": None,
        "similarity_threshold": test_constants['DEFAULT_SIMILARITY_THRESHOLD'],
        "entity_extraction_confidence": test_constants['DEFAULT_ENTITY_EXTRACTION_CONFIDENCE']
    }


@pytest.fixture
def custom_storage():
    return AsyncMock(spec=IPLDStorage)

@pytest.fixture
def non_default_parameters(custom_storage, test_constants):
    """Fixture to provide non-default parameters."""
    return {
        "storage": custom_storage,
        "similarity_threshold": test_constants['CUSTOM_SIMILARITY_THRESHOLD'],
        "entity_extraction_confidence": test_constants['CUSTOM_ENTITY_EXTRACTION_CONFIDENCE']
    }

@pytest.fixture
def integrator_custom_storage(custom_storage):
    """Fixture to provide a custom IPLDStorage instance."""
    return GraphRAGIntegrator(storage=custom_storage)

@pytest.fixture
def integrator_custom_similarity(non_default_parameters):
    """Fixture to provide a custom similarity_threshold value."""
    return GraphRAGIntegrator(
        similarity_threshold=non_default_parameters["similarity_threshold"]
    )

@pytest.fixture
def integrator_custom_confidence(non_default_parameters):
    """Fixture to provide a custom entity_extraction_confidence value."""
    return GraphRAGIntegrator(
        entity_extraction_confidence=non_default_parameters["entity_extraction_confidence"]
    )

@pytest.fixture
def integrator_all_custom(custom_storage, non_default_parameters):
    """Create a GraphRAGIntegrator instance with all custom parameters for testing."""
    return GraphRAGIntegrator(
        storage=custom_storage,
        similarity_threshold=non_default_parameters["similarity_threshold"],
        entity_extraction_confidence=non_default_parameters["entity_extraction_confidence"]
    )


@pytest.fixture
def real_integrator():
    """Create a GraphRAGIntegrator instance with default parameters for testing."""
    return GraphRAGIntegrator()


@pytest.fixture
def integrator_with_custom_confidence(test_constants):
    """Create a GraphRAGIntegrator instance with custom entity_extraction_confidence for testing."""
    return GraphRAGIntegrator(
        entity_extraction_confidence=test_constants['CUSTOM_ENTITY_EXTRACTION_CONFIDENCE']
    )


@pytest.fixture
def integrator_with_all_high_custom_params(test_constants):
    """Create a GraphRAGIntegrator instance with all high custom parameters for testing."""
    custom_storage = Mock(spec=IPLDStorage)
    return GraphRAGIntegrator(
        storage=custom_storage,
        similarity_threshold=test_constants['HIGH_SIMILARITY_THRESHOLD'],
        entity_extraction_confidence=test_constants['HIGH_ENTITY_EXTRACTION_CONFIDENCE']
    ), custom_storage


@pytest.fixture
def two_independent_integrators():
    """Create two independent GraphRAGIntegrator instances for testing isolation."""
    return GraphRAGIntegrator(), GraphRAGIntegrator()


class TestGraphRAGIntegratorInit:
    """Test class for GraphRAGIntegrator.__init__ method."""

    def test_init_default_storage_is_ipld_storage_instance(self, real_integrator):
        """
        GIVEN no storage parameter is provided to GraphRAGIntegrator constructor
        WHEN a new GraphRAGIntegrator instance is created
        THEN the storage should be an IPLDStorage instance
        """
        assert isinstance(real_integrator.storage, IPLDStorage)

    @pytest.mark.parametrize("attribute", [
        "similarity_threshold",
        "entity_extraction_confidence"
    ])
    def test_init_default_parameters(self, real_integrator, default_parameters, attribute):
        """
        GIVEN no parameters are provided to GraphRAGIntegrator constructor
        WHEN a new GraphRAGIntegrator instance is created
        THEN the attribute should have the default value
        """
        expected_value = default_parameters[attribute]
        actual_value = getattr(real_integrator, attribute)
        assert actual_value == expected_value, \
            f"Expected default {attribute} to be {expected_value}, but got {actual_value}"

    @pytest.mark.parametrize("attribute,expected_value", [
        ("knowledge_graphs", {}),
        ("global_entities", {}),
        ("cross_document_relationships", []),
        ("document_graphs", {})
    ])
    def test_init_default_collections_empty(self, real_integrator, attribute, expected_value):
        """
        GIVEN no parameters are provided to GraphRAGIntegrator constructor
        WHEN a new GraphRAGIntegrator instance is created
        THEN the collection attributes should be empty
        """
        actual_value = getattr(real_integrator, attribute)
        assert actual_value == expected_value, \
            f"Expected default {attribute} to be {expected_value}, but got {actual_value}"

    def test_init_default_global_graph_is_networkx_digraph(self, real_integrator):
        """
        GIVEN no parameters are provided to GraphRAGIntegrator constructor
        WHEN a new GraphRAGIntegrator instance is created
        THEN the global_graph should be a NetworkX DiGraph instance
        """
        assert isinstance(real_integrator.global_graph, nx.DiGraph)

    @pytest.mark.parametrize("graph_property,expected_length", [
        ("nodes", 0),
        ("edges", 0)
    ])
    def test_init_default_global_graph_empty(self, real_integrator, graph_property, expected_length):
        """
        GIVEN no parameters are provided to GraphRAGIntegrator constructor
        WHEN a new GraphRAGIntegrator instance is created
        THEN the global_graph should have no nodes or edges
        """
        actual_length = len(getattr(real_integrator.global_graph, graph_property))
        assert actual_length == expected_length, \
            f"Expected global_graph.{graph_property} length to be {expected_length}, but got {actual_length}"

    def test_init_with_custom_storage_uses_provided_storage(self, 
        integrator_custom_storage, custom_storage
    ):
        """
        GIVEN a custom IPLDStorage instance is provided
        WHEN GraphRAGIntegrator is initialized with that storage
        THEN the instance should use the provided storage object
        """
        assert integrator_custom_storage.storage is custom_storage, \
            f"Expected storage to be custom instance, but got {type(integrator_custom_storage.storage)}"

    def test_init_with_custom_storage_uses_default_similarity_threshold(self, 
        integrator_custom_storage, default_parameters
    ):
        """
        GIVEN a custom IPLDStorage instance is provided
        WHEN GraphRAGIntegrator is initialized with that storage
        THEN the similarity_threshold should use the default value
        """
        expected_threshold = default_parameters["similarity_threshold"]
        assert integrator_custom_storage.similarity_threshold == expected_threshold, \
            f"Expected similarity_threshold to be {expected_threshold}, but got {integrator_custom_storage.similarity_threshold}"

    def test_init_with_custom_storage_uses_default_entity_extraction_confidence(self, 
        integrator_custom_storage, default_parameters
    ):
        """
        GIVEN a custom IPLDStorage instance is provided
        WHEN GraphRAGIntegrator is initialized with that storage
        THEN the entity_extraction_confidence should use the default value
        """
        expected_confidence = default_parameters["entity_extraction_confidence"]
        assert integrator_custom_storage.entity_extraction_confidence == expected_confidence, \
            f"Expected entity_extraction_confidence to be {expected_confidence}, but got {integrator_custom_storage.entity_extraction_confidence}"

    def test_init_with_custom_similarity_threshold_stores_custom_value(self, 
        integrator_custom_similarity, non_default_parameters
    ):
        """
        GIVEN a custom similarity_threshold value
        WHEN GraphRAGIntegrator is initialized with that threshold
        THEN the instance should store the custom threshold value
        """
        expected_threshold = non_default_parameters['similarity_threshold']
        assert integrator_custom_similarity.similarity_threshold == expected_threshold, \
            f"Expected similarity_threshold to be {expected_threshold}, but got {integrator_custom_similarity.similarity_threshold}"


    def test_init_with_custom_similarity_threshold_uses_default_confidence(self, 
        integrator_custom_similarity, default_parameters
    ):
        """
        GIVEN a custom similarity_threshold value
        WHEN GraphRAGIntegrator is initialized with that threshold
        THEN the entity_extraction_confidence should use the default value
        """
        expected_confidence = default_parameters['entity_extraction_confidence']
        assert integrator_custom_similarity.entity_extraction_confidence == expected_confidence, \
            f"Expected entity_extraction_confidence to be {expected_confidence}, but got {integrator_custom_similarity.entity_extraction_confidence}"


    def test_init_with_custom_similarity_threshold_creates_default_storage(self, 
        integrator_custom_similarity
    ):
        """
        GIVEN a custom similarity_threshold value
        WHEN GraphRAGIntegrator is initialized with that threshold
        THEN the storage should be a default IPLDStorage instance
        """
        assert isinstance(integrator_custom_similarity.storage, IPLDStorage), \
            f"Expected storage to be IPLDStorage instance, but got {type(integrator_custom_similarity.storage)}"

    def test_init_with_custom_entity_extraction_confidence_stores_custom_value(
        self, integrator_with_custom_confidence, test_constants
    ):
        """
        GIVEN a custom entity_extraction_confidence value
        WHEN GraphRAGIntegrator is initialized with that confidence
        THEN the instance should store the custom confidence value
        """
        expected_confidence = test_constants['CUSTOM_ENTITY_EXTRACTION_CONFIDENCE']
        assert integrator_with_custom_confidence.entity_extraction_confidence == expected_confidence, \
            f"Expected entity_extraction_confidence to be {expected_confidence}, but got {integrator_with_custom_confidence.entity_extraction_confidence}"

    def test_init_with_custom_entity_extraction_confidence_uses_default_similarity(
        self, integrator_with_custom_confidence, test_constants
    ):
        """
        GIVEN a custom entity_extraction_confidence value
        WHEN GraphRAGIntegrator is initialized with that confidence
        THEN the similarity_threshold should use the default value
        """
        expected_similarity = test_constants['DEFAULT_SIMILARITY_THRESHOLD']
        assert integrator_with_custom_confidence.similarity_threshold == expected_similarity, \
            f"Expected similarity_threshold to be {expected_similarity}, but got {integrator_with_custom_confidence.similarity_threshold}"

    def test_init_with_custom_entity_extraction_confidence_creates_default_storage(
        self, integrator_with_custom_confidence
    ):
        """
        GIVEN a custom entity_extraction_confidence value
        WHEN GraphRAGIntegrator is initialized with that confidence
        THEN the storage should be a default IPLDStorage instance
        """
        assert isinstance(integrator_with_custom_confidence.storage, IPLDStorage), \
            f"Expected storage to be IPLDStorage instance, but got {type(integrator_with_custom_confidence.storage)}"

    def test_init_with_all_custom_parameters_uses_custom_storage(self, integrator_with_all_high_custom_params):
        """
        GIVEN custom values for all parameters (storage, similarity_threshold, entity_extraction_confidence)
        WHEN GraphRAGIntegrator is initialized with these values
        THEN the instance should use the provided custom storage object
        """
        integrator, custom_storage = integrator_with_all_high_custom_params
        assert integrator.storage is custom_storage, \
            f"Expected storage to be custom instance, but got {type(integrator.storage)}"

    def test_init_with_all_custom_parameters_uses_custom_similarity_threshold(
        self, integrator_with_all_high_custom_params, test_constants
    ):
        """
        GIVEN custom values for all parameters (storage, similarity_threshold, entity_extraction_confidence)
        WHEN GraphRAGIntegrator is initialized with these values
        THEN the instance should use the provided custom similarity_threshold value
        """
        integrator, _ = integrator_with_all_high_custom_params
        expected_similarity = test_constants['HIGH_SIMILARITY_THRESHOLD']
        assert integrator.similarity_threshold == expected_similarity, \
            f"Expected similarity_threshold to be {expected_similarity}, but got {integrator.similarity_threshold}"

    def test_init_with_all_custom_parameters_uses_custom_entity_extraction_confidence(
        self, integrator_with_all_high_custom_params, test_constants
    ):
        """
        GIVEN custom values for all parameters (storage, similarity_threshold, entity_extraction_confidence)
        WHEN GraphRAGIntegrator is initialized with these values
        THEN the instance should use the provided custom entity_extraction_confidence value
        """
        integrator, _ = integrator_with_all_high_custom_params
        expected_confidence = test_constants['HIGH_ENTITY_EXTRACTION_CONFIDENCE']
        assert integrator.entity_extraction_confidence == expected_confidence, \
            f"Expected entity_extraction_confidence to be {expected_confidence}, but got {integrator.entity_extraction_confidence}"

    @pytest.mark.parametrize("param_name,boundary_key", [
        ("similarity_threshold", "BOUNDARY_MIN_VALUE"),
        ("similarity_threshold", "BOUNDARY_MAX_VALUE"),
        ("entity_extraction_confidence", "BOUNDARY_MIN_VALUE"),
        ("entity_extraction_confidence", "BOUNDARY_MAX_VALUE"),
    ])
    def test_init_boundary_values(self, param_name, boundary_key, test_constants):
        """
        GIVEN boundary values for similarity_threshold or entity_extraction_confidence (0.0, 1.0)
        WHEN GraphRAGIntegrator is initialized with these values
        THEN the instance should accept and store these boundary values
        """
        # Arrange
        boundary_value = test_constants[boundary_key]
        kwargs = {param_name: boundary_value}
        
        # Act
        integrator = GraphRAGIntegrator(**kwargs)
        actual_value = getattr(integrator, param_name)
        
        # Assert
        assert actual_value == boundary_value, \
            f"Expected {param_name} to be set to {boundary_value}, but got {actual_value} instead."

    @pytest.mark.parametrize("param_name,invalid_key,expected_error_message", [
        ("similarity_threshold", "INVALID_LOW_VALUE", "similarity_threshold must be between 0.0 and 1.0"),
        ("similarity_threshold", "INVALID_HIGH_SIMILARITY", "similarity_threshold must be between 0.0 and 1.0"),
        ("entity_extraction_confidence", "INVALID_LOW_VALUE", "entity_extraction_confidence must be between 0.0 and 1.0"),
        ("entity_extraction_confidence", "INVALID_HIGH_CONFIDENCE", "entity_extraction_confidence must be between 0.0 and 1.0"),
    ])
    def test_init_invalid_range_values(self, param_name, invalid_key, expected_error_message, test_constants):
        """
        GIVEN an invalid parameter value outside the valid range [0.0, 1.0]
        WHEN GraphRAGIntegrator is initialized with this parameter
        THEN a ValueError should be raised
        AND the error message should indicate the invalid range
        """
        # Arrange
        invalid_value = test_constants[invalid_key]
        kwargs = {param_name: invalid_value}
        
        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            GraphRAGIntegrator(**kwargs)
        
        assert expected_error_message in str(exc_info.value), \
            f"Expected error message to contain '{expected_error_message}', but got '{str(exc_info.value)}' instead."

    @pytest.mark.parametrize("param_name,invalid_value,expected_error_message", [
        ("storage", "not_an_ipld_storage", "storage"),
        ("similarity_threshold", "0.8", "similarity_threshold must be an int or float"),
        ("entity_extraction_confidence", "0.6", "entity_extraction_confidence must be an int or float"),
    ])
    def test_init_type_validation(self, param_name, invalid_value, expected_error_message):
        """
        GIVEN an invalid parameter type
        WHEN GraphRAGIntegrator is initialized with this parameter
        THEN a TypeError should be raised
        AND the error message should indicate the expected type
        """
        kwargs = {param_name: invalid_value}
        with pytest.raises(TypeError) as exc_info:
            GraphRAGIntegrator(**kwargs)
        
        assert expected_error_message in str(exc_info.value), \
            f"Expected error message to contain '{expected_error_message}', but got '{str(exc_info.value)}' instead."

    def test_init_knowledge_graphs_attribute_immutability(self, two_independent_integrators, test_constants):
        """
        GIVEN multiple GraphRAGIntegrator instances are created
        WHEN modifying knowledge_graphs in the first instance
        THEN the second instance's knowledge_graphs should remain unaffected
        """
        integrator1, integrator2 = two_independent_integrators
        expected_dict = test_constants['EMPTY_DICT']
        
        integrator1.knowledge_graphs["test"] = "value"
        
        assert integrator2.knowledge_graphs == expected_dict, \
            f"Expected integrator2.knowledge_graphs to remain {expected_dict}, but got {integrator2.knowledge_graphs}"

    def test_init_global_entities_attribute_immutability(self, two_independent_integrators, test_constants):
        """
        GIVEN multiple GraphRAGIntegrator instances are created
        WHEN modifying global_entities in the first instance
        THEN the second instance's global_entities should remain unaffected
        """
        integrator1, integrator2 = two_independent_integrators
        expected_dict = test_constants['EMPTY_DICT']
        
        integrator1.global_entities["entity"] = "data"
        
        assert integrator2.global_entities == expected_dict, \
            f"Expected integrator2.global_entities to remain {expected_dict}, but got {integrator2.global_entities}"

    def test_init_cross_document_relationships_attribute_immutability(self, two_independent_integrators, test_constants):
        """
        GIVEN multiple GraphRAGIntegrator instances are created
        WHEN modifying cross_document_relationships in the first instance
        THEN the second instance's cross_document_relationships should remain unaffected
        """
        integrator1, integrator2 = two_independent_integrators
        expected_list = test_constants['EMPTY_LIST']
        
        integrator1.cross_document_relationships.append("relationship")
        
        assert integrator2.cross_document_relationships == expected_list, \
            f"Expected integrator2.cross_document_relationships to remain {expected_list}, but got {integrator2.cross_document_relationships}"

    def test_init_document_graphs_attribute_immutability(self, two_independent_integrators, test_constants):
        """
        GIVEN multiple GraphRAGIntegrator instances are created
        WHEN modifying document_graphs in the first instance
        THEN the second instance's document_graphs should remain unaffected
        """
        integrator1, integrator2 = two_independent_integrators
        expected_dict = test_constants['EMPTY_DICT']
        
        integrator1.document_graphs["doc"] = "graph"
        
        assert integrator2.document_graphs == expected_dict, \
            f"Expected integrator2.document_graphs to remain {expected_dict}, but got {integrator2.document_graphs}"

    def test_init_default_storage_creation(self, real_integrator):
        """
        GIVEN no storage parameter is provided
        WHEN GraphRAGIntegrator is initialized
        THEN a new IPLDStorage instance should be created
        """
        assert isinstance(real_integrator.storage, IPLDStorage), \
            f"Expected storage to be IPLDStorage instance, but got {type(real_integrator.storage)}"

    def test_init_global_graph_is_networkx_digraph(self, real_integrator):
        """
        GIVEN GraphRAGIntegrator is initialized
        WHEN checking the global_graph attribute
        THEN it should be a NetworkX DiGraph instance
        """
        assert isinstance(real_integrator.global_graph, nx.DiGraph), \
            f"Expected global_graph to be nx.DiGraph, but got {type(real_integrator.global_graph)}"

    def test_init_global_graph_is_directed(self, real_integrator: GraphRAGIntegrator):
        """
        GIVEN GraphRAGIntegrator is initialized
        WHEN checking the global_graph directedness
        THEN it should be a directed graph
        """
        assert real_integrator.global_graph.is_directed(), \
            "Expected global_graph to be directed, but it was not"

    def test_init_global_graph_has_no_nodes(self, real_integrator, test_constants):
        """
        GIVEN GraphRAGIntegrator is initialized
        WHEN checking the global_graph nodes
        THEN it should have no nodes initially
        """
        expected_count = test_constants['ZERO_LENGTH']
        actual_count = len(real_integrator.global_graph.nodes)
        assert actual_count == expected_count, \
            f"Expected global_graph to have {expected_count} nodes, but got {actual_count}"

    def test_init_global_graph_has_no_edges(self, real_integrator, test_constants):
        """
        GIVEN GraphRAGIntegrator is initialized
        WHEN checking the global_graph edges
        THEN it should have no edges initially
        """
        expected_count = test_constants['ZERO_LENGTH']
        actual_count = len(real_integrator.global_graph.edges)
        assert actual_count == expected_count, \
            f"Expected global_graph to have {expected_count} edges, but got {actual_count}"

    def test_init_knowledge_graphs_collections_are_independent(self, two_independent_integrators):
        """
        GIVEN multiple GraphRAGIntegrator instances are created
        WHEN modifying knowledge_graphs in one instance
        THEN other instances should not be affected
        """
        integrator1, integrator2 = two_independent_integrators
        
        integrator1.knowledge_graphs["doc1"] = "kg1"
        integrator2.knowledge_graphs["doc2"] = "kg2"
        
        assert "doc1" not in integrator2.knowledge_graphs, \
            "Expected integrator2.knowledge_graphs to not contain 'doc1', but it did"

    def test_init_global_entities_collections_are_independent(self, two_independent_integrators):
        """
        GIVEN multiple GraphRAGIntegrator instances are created
        WHEN modifying global_entities in one instance
        THEN other instances should not be affected
        """
        integrator1, integrator2 = two_independent_integrators
        
        integrator1.global_entities["ent1"] = "entity1"
        integrator2.global_entities["ent2"] = "entity2"
        
        assert "ent1" not in integrator2.global_entities, \
            "Expected integrator2.global_entities to not contain 'ent1', but it did"

    def test_init_cross_document_relationships_collections_are_independent(self, two_independent_integrators, test_constants):
        """
        GIVEN multiple GraphRAGIntegrator instances are created
        WHEN modifying cross_document_relationships in one instance
        THEN other instances should not be affected
        """
        integrator1, integrator2 = two_independent_integrators
        expected_length = test_constants['ZERO_LENGTH']
        
        integrator1.cross_document_relationships.append("rel1")
        
        assert len(integrator2.cross_document_relationships) == expected_length, \
            f"Expected integrator2.cross_document_relationships length to be {expected_length}, but got {len(integrator2.cross_document_relationships)}"

    def test_init_collections_start_with_expected_empty_values(self, real_integrator, test_constants):
        """
        GIVEN a new GraphRAGIntegrator instance is created
        WHEN checking initial collection states
        THEN all collections should start with expected empty values
        """
        expected_dict = test_constants['EMPTY_DICT']
        
        assert real_integrator.knowledge_graphs == expected_dict, \
            f"Expected knowledge_graphs to be {expected_dict}, but got {real_integrator.knowledge_graphs}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
