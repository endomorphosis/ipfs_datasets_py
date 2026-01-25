#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
import anyio
import json
import networkx as nx
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, Entity, Relationship


work_dir = os.path.abspath(os.path.dirname(__file__))
while not os.path.exists(os.path.join(work_dir, "__pyproject.toml")):
    parent = os.path.dirname(work_dir)
    if parent == work_dir:
        break
    work_dir = parent
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
def expected_node_counts():
    return {
        "isolated": 1,
        "depth_one": 3,
        "depth_two": 5,
        "large_graph_min": 103
    }


@pytest.fixture
def expected_edge_counts():
    return {
        "isolated": 0,
        "large_graph_min": 103
    }

@pytest.fixture
def entity_ids():
    return {
        "entity": "entity_1",
        "isolated": "isolated_1",
        "nonexistent": "nonexistent_entity",
        "any": "any_entity"
    }


@pytest.fixture
def entity_id(entity_ids):
    return entity_ids['entity']

DEPTH_0 = 0
DEPTH_1 = 1
DEPTH_2 = 2
DEPTH_3 = 3
DEPTH_10 = 10

@pytest.fixture
def depths():
    return {
        "zero": DEPTH_0,
        "one": DEPTH_1,
        "two": DEPTH_2,
        "three": DEPTH_3,
        "ten": DEPTH_10
    }

@pytest.fixture
def expected_node_ids_set():
    return {
        "length_3": {"entity_1", "entity_2", "entity_3"},
        "length_5": {"entity_1", "entity_2", "entity_3", "entity_4", "entity_5"}
    }

@pytest.fixture
def test_constants(
    expected_node_counts, 
    expected_edge_counts, 
    entity_ids, 
    depths, 
    expected_node_ids_set) -> dict[str, dict[str, Any]]:

    return {
        "node_counts": expected_node_counts,
        "edge_counts": expected_edge_counts,
        "entity_ids": entity_ids,
        "depths": depths,
        "node_ids_set": expected_node_ids_set
    }


def _get_first_entity_node(result, entity_id):
    """Helper to extract first entity node from result by ID."""
    return next(node for node in result["nodes"] if node["id"] == entity_id)

def _get_node_ids(result):
    """Helper to extract set of node IDs from result."""
    return {node["id"] for node in result["nodes"]}

def _get_edge_from_source_to_target(result, source_id, target_id):
    """Helper to extract edge from result by source and target IDs."""
    return next(
        edge for edge in result["edges"] 
        if edge["source"] == source_id and edge["target"] == target_id
    )

class TestGetEntityNeighborhood:
    """Test class for GraphRAGIntegrator.get_entity_neighborhood method."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("expected_field,expected_value", [
        ("center_entity_id", "entity_1"),
        ("node_count", 3),
        ("depth", 1),
    ])
    async def test_when_getting_neighborhood_with_depth_one_then_result_fields_are_correct(
        self, integrator_with_test_graph, entity_id, expected_field, expected_value
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and entity with direct neighbors
        WHEN get_entity_neighborhood method is called with depth=1
        THEN expect result fields to have correct values
        """
        # Arrange
        depth = 1
        
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depth)
        
        # Assert
        assert result[expected_field] == expected_value, f"Expected {expected_field} to be {expected_value}, got {result[expected_field]}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_depth_one_then_contains_expected_nodes(
        self, integrator_with_test_graph, entity_id
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and entity with known neighbors
        WHEN get_entity_neighborhood method is called with depth=1
        THEN expect nodes list to contain exactly entity_1, entity_2, and entity_3
        """
        # Arrange

        depth = 1
        expected_node_ids = {"entity_1", "entity_2", "entity_3"}
        
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depth)
        node_ids = _get_node_ids(result)
        
        # Assert
        assert node_ids == expected_node_ids, f"Expected node_ids to be {expected_node_ids}, got {node_ids}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_depth_two_then_center_entity_is_correct(
        self, integrator_with_test_graph, entity_id
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and entity with neighbors
        WHEN get_entity_neighborhood method is called with depth=2
        THEN expect center_entity_id to match input entity_id
        """
        # Arrange

        depth = 2
        
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depth)
        
        # Assert
        assert result["center_entity_id"] == entity_id, f"Expected center_entity_id to be {entity_id}, got {result['center_entity_id']}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_depth_two_then_includes_all_reachable_nodes(
        self, integrator_with_test_graph, entity_id
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and depth=2
        WHEN get_entity_neighborhood method is called
        THEN expect all reachable nodes within 2 hops to be included
        """
        # Arrange

        depth = 2
        expected_node_count = 5
        
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depth)
        
        # Assert
        assert result["node_count"] == expected_node_count, f"Expected node_count to be {expected_node_count}, got {result['node_count']}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_depth_two_then_contains_all_entities(
        self, integrator_with_test_graph, entity_id
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and depth=2
        WHEN get_entity_neighborhood method is called from entity_1
        THEN expect nodes list to contain all five entities in the graph
        """
        # Arrange

        depth = 2
        expected_node_ids = {"entity_1", "entity_2", "entity_3", "entity_4", "entity_5"}
        
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depth)
        node_ids = _get_node_ids(result)
        
        # Assert
        assert node_ids == expected_node_ids, f"Expected node_ids to be {expected_node_ids}, got {node_ids}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_without_depth_parameter_then_defaults_to_two(
        self, integrator_with_test_graph, entity_id
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and no depth parameter
        WHEN get_entity_neighborhood method is called
        THEN expect depth field to equal default value of 2
        """
        # Arrange
        expected_depth = 2

        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id)
        
        # Assert
        assert result["depth"] == expected_depth, f"Expected depth to be {expected_depth}, got {result['depth']}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_without_depth_parameter_then_includes_all_reachable_nodes(
        self, integrator_with_test_graph, entity_id
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and no depth parameter
        WHEN get_entity_neighborhood method is called
        THEN expect node_count to include all entities reachable within default depth
        """
        # Arrange
        expected_node_count = 5

        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id)
        
        # Assert
        assert result["node_count"] == expected_node_count, f"Expected node_count to be {expected_node_count}, got {result['node_count']}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("expected_field,expected_value", [
        ("node_count", 1),
        ("edge_count", 0),
        ("center_entity_id", "isolated_1"),
    ])
    async def test_when_getting_neighborhood_of_isolated_entity_then_result_fields_are_correct(
        self, integrator_with_isolated_entity, expected_field, expected_value
    ):
        """
        GIVEN GraphRAGIntegrator instance with isolated entity that has no connections
        WHEN get_entity_neighborhood method is called
        THEN expect result fields to have correct values for isolated entity
        """
        # Arrange
        entity_id = "isolated_1"
        depth = 2
        
        # Act
        result = await integrator_with_isolated_entity.get_entity_neighborhood(entity_id, depth=depth)
        
        # Assert
        assert result[expected_field] == expected_value, f"Expected {expected_field} to be {expected_value}, got {result[expected_field]}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_of_isolated_entity_then_contains_only_isolated_entity(
        self, integrator_with_isolated_entity
    ):
        """
        GIVEN GraphRAGIntegrator instance with isolated entity that has no connections
        WHEN get_entity_neighborhood method is called
        THEN expect nodes list to contain only the isolated entity
        """
        # Arrange
        entity_id = "isolated_1"
        
        # Act
        result = await integrator_with_isolated_entity.get_entity_neighborhood(entity_id, depth=2)
        
        # Assert
        assert result["nodes"][0]["id"] == entity_id, f"Expected first node id to be {entity_id}, got {result['nodes'][0]['id']}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_of_nonexistent_entity_then_returns_error(
        self, integrator_with_test_graph
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and nonexistent entity_id
        WHEN get_entity_neighborhood method is called
        THEN expect result to contain error key
        """
        # Arrange
        nonexistent_entity_id = "nonexistent_entity"
        
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(nonexistent_entity_id)
        
        # Assert
        assert "error" in result, f"Expected result to contain 'error' key, got keys: {list(result.keys())}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_of_nonexistent_entity_then_error_message_mentions_not_found(
        self, integrator_with_test_graph
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and nonexistent entity_id
        WHEN get_entity_neighborhood method is called
        THEN expect error message to contain 'not found' phrase
        """
        # Arrange
        nonexistent_entity_id = "nonexistent_entity"
        
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(nonexistent_entity_id)
        
        # Assert
        assert "not found" in result["error"].lower(), f"Expected error message to contain 'not found', got: {result['error']}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("expected_field,expected_value", [
        ("node_count", 1),
        ("edge_count", 0),
        ("center_entity_id", "entity_1"),
    ])
    async def test_when_getting_neighborhood_with_depth_zero_then_result_fields_are_correct(
        self, integrator_with_test_graph, entity_id, expected_field, expected_value
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and depth=0
        WHEN get_entity_neighborhood method is called
        THEN expect result fields to have correct values for depth zero
        """
        # Arrange
        depth = 0

        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depth)
        
        # Assert
        assert result[expected_field] == expected_value, f"Expected {expected_field} to be {expected_value}, got {result[expected_field]}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("expected_field,expected_value", [
        ("node_count", 5),
        ("depth", 10),
    ])
    async def test_when_getting_neighborhood_with_large_depth_then_result_fields_are_correct(
        self, integrator_with_test_graph, entity_ids, 
        depths, expected_field, expected_value
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and large depth value
        WHEN get_entity_neighborhood method is called with depth=10
        THEN expect result fields to have correct values
        """
        # Arrange
        depth, entity_id = depths["ten"], entity_ids["entity"]
        
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depth)
        
        # Assert
        assert result[expected_field] == expected_value, f"Expected {expected_field} to be {expected_value}, got {result[expected_field]}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_then_result_is_dictionary(
        self, integrator_with_test_graph, entity_ids, depths
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph
        WHEN get_entity_neighborhood method is called
        THEN expect result to be dictionary type
        """
        # Arrange
        depth, entity_id = depths["one"], entity_ids["entity"]
        
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depth)
        
        # Assert
        assert isinstance(result, dict), f"Expected result to be dict, got {type(result).__name__}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field_name", [
        "center_entity_id",
        "depth", 
        "nodes",
        "edges",
        "node_count",
        "edge_count"
    ])
    async def test_when_getting_neighborhood_then_contains_required_field(
        self, integrator_with_test_graph, entity_id, field_name, depths
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph
        WHEN get_entity_neighborhood method is called
        THEN expect result to contain all required fields
        """
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depths["one"])

        # Assert
        assert field_name in result, f"Expected result to contain '{field_name}' field, got keys: {list(result.keys())}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field_name,expected_type", [
        ("center_entity_id", str),
        ("nodes", list),
        ("edges", list),
        ("depth", int),
        ("node_count", int),
        ("edge_count", int),
    ])
    async def test_when_getting_neighborhood_then_result_fields_have_correct_types(
        self, integrator_with_test_graph, entity_id, field_name, expected_type, depths
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph
        WHEN get_entity_neighborhood method is called
        THEN expect all result fields to have correct data types
        """
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depths["one"])

        # Assert
        assert isinstance(result[field_name], expected_type), f"Expected {field_name} to be {expected_type.__name__}, got {type(result[field_name]).__name__}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("attribute_name,expected_value", [
        ("name", "John Smith"),
        ("type", "person"),
        ("confidence", 0.9),
        ("source_chunks", ["chunk_1"]),
    ])
    async def test_when_getting_neighborhood_then_entity_node_contains_correct_attributes(
        self, integrator_with_test_graph, entity_id, attribute_name, expected_value, depths
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and entity with known attributes
        WHEN get_entity_neighborhood method is called
        THEN expect entity_1 node to contain correct attribute values
        """
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depths["one"])
        entity1_node = _get_first_entity_node(result, entity_id)

        # Assert
        assert entity1_node[attribute_name] == expected_value, f"Expected entity {attribute_name} to be {expected_value}, got {entity1_node[attribute_name]}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("attribute_name,expected_value", [
        ("relationship_type", "leads"),
        ("confidence", 0.9),
        ("source_chunks", ["chunk_1"]),
    ])
    async def test_when_getting_neighborhood_then_edge_contains_correct_attributes(
        self, integrator_with_test_graph, entity_id, depths, attribute_name, expected_value
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and relationship with known attributes
        WHEN get_entity_neighborhood method is called
        THEN expect edge from entity_1 to entity_2 to contain correct attribute values
        """
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depths['one'])
        edge = next(edge for edge in result["edges"] if edge["source"] == entity_id and edge["target"] == "entity_2")

        # Assert
        assert edge[attribute_name] == expected_value, f"Expected edge {attribute_name} to be {expected_value}, got {edge[attribute_name]}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_depth_one_then_includes_directly_connected_entity(
        self, integrator_with_test_graph, entity_id, depths
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph where entity_3 is directly connected to entity_1
        WHEN get_entity_neighborhood method is called with depth=1
        THEN expect entity_3 to be included in results due to direct connection
        """
        # Arrange
        expected_entity = "entity_3"

        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depths['one'])
        node_ids = _get_node_ids(result)

        # Assert
        assert expected_entity in node_ids, f"Expected {expected_entity} to be in node_ids {node_ids}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_from_entity_with_incoming_edges_then_includes_predecessors(
        self, integrator_with_test_graph, depths
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and entity_2 having incoming edges
        WHEN get_entity_neighborhood method is called from entity_2 with depth=1
        THEN expect entity_1 predecessor to be included
        """
        # Arrange
        center_entity = "entity_2"
        expected_predecessor = "entity_1"

        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(center_entity, depth=depths['one'])
        node_ids = _get_node_ids(result)
        
        # Assert
        assert expected_predecessor in node_ids, f"Expected predecessor {expected_predecessor} to be in node_ids {node_ids}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_from_entity_with_outgoing_edges_then_includes_successors(
        self, integrator_with_test_graph, depths
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and entity_2 having outgoing edges
        WHEN get_entity_neighborhood method is called from entity_2 with depth=1
        THEN expect entity_4 successor to be included
        """
        # Arrange
        center_entity = "entity_2"
        expected_successor = "entity_4"
        
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(center_entity, depth=depths['one'])
        node_ids = _get_node_ids(result)
        
        # Assert
        assert expected_successor in node_ids, f"Expected successor {expected_successor} to be in node_ids {node_ids}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("depth", [0, 1, 2, 3])
    async def test_when_getting_neighborhood_then_node_count_matches_nodes_list_length(
        self, integrator_with_test_graph, entity_id, depth
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and various depth values
        WHEN get_entity_neighborhood method is called
        THEN expect node_count field to exactly match length of nodes list
        """
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depth)
        
        # Assert
        assert result["node_count"] == len(result["nodes"]), f"Expected node_count {result['node_count']} to match nodes list length {len(result['nodes'])}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("depth", [0, 1, 2, 3])
    async def test_when_getting_neighborhood_then_edge_count_matches_edges_list_length(
        self, integrator_with_test_graph, entity_id, depth
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph and various depth values
        WHEN get_entity_neighborhood method is called
        THEN expect edge_count field to exactly match length of edges list
        """
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depth)
        
        # Assert
        assert result["edge_count"] == len(result["edges"]), f"Expected edge_count {result['edge_count']} to match edges list length {len(result['edges'])}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_from_empty_graph_then_returns_error(
        self, empty_integrator, entity_ids
    ):
        """
        GIVEN GraphRAGIntegrator instance with empty global graph
        WHEN get_entity_neighborhood method is called with any entity_id
        THEN expect result to contain error key
        """
        # Act
        result = await empty_integrator.get_entity_neighborhood(entity_ids['any'])
        
        # Assert
        assert "error" in result, f"Expected result to contain 'error' key, got keys: {list(result.keys())}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_from_empty_graph_then_error_mentions_not_found(
        self, empty_integrator, entity_ids
    ):
        """
        GIVEN GraphRAGIntegrator instance with empty global graph
        WHEN get_entity_neighborhood method is called with any entity_id
        THEN expect error message to contain 'not found' phrase
        """
        # Act
        result = await empty_integrator.get_entity_neighborhood(entity_ids['any'])

        # Assert
        assert "not found" in result["error"].lower(), f"Expected error message to contain 'not found', got: {result['error']}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_none_entity_id_then_raises_type_error(
        self, real_integrator
    ):
        """
        GIVEN GraphRAGIntegrator instance and None as entity_id parameter
        WHEN get_entity_neighborhood method is called
        THEN expect TypeError with message containing 'entity_id must be a string'
        """
        # Act & Assert
        with pytest.raises(TypeError, match="entity_id must be a string"):
            await real_integrator.get_entity_neighborhood(None)

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_empty_entity_id_then_raises_value_error(
        self, real_integrator
    ):
        """
        GIVEN GraphRAGIntegrator instance and empty string as entity_id
        WHEN get_entity_neighborhood method is called
        THEN expect ValueError with message containing 'entity_id must be a non-empty string'
        """
        # Arrange
        empty_entity_id = ""
        
        # Act & Assert
        with pytest.raises(ValueError, match="entity_id must be a non-empty string."):
            await real_integrator.get_entity_neighborhood(empty_entity_id)

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_negative_depth_then_raises_value_error(
        self, real_integrator, entity_id
    ):
        """
        GIVEN GraphRAGIntegrator instance and negative depth value
        WHEN get_entity_neighborhood method is called
        THEN expect ValueError with message containing 'depth must be a non-negative integer'
        """
        # Arrange
        negative_depth = -1
        
        # Act & Assert
        with pytest.raises(ValueError, match="depth must be a non-negative integer"):
            await real_integrator.get_entity_neighborhood(entity_id, depth=negative_depth)

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_non_integer_depth_then_raises_type_error(
        self, real_integrator, entity_id
    ):
        """
        GIVEN GraphRAGIntegrator instance and non-integer depth parameter
        WHEN get_entity_neighborhood method is called
        THEN expect TypeError with message containing 'depth must be an integer'
        """
        # Arrange
        float_depth = 1.5
        
        # Act & Assert
        with pytest.raises(TypeError, match="depth must be an integer"):
            await real_integrator.get_entity_neighborhood(entity_id, depth=float_depth)


    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_result_then_is_json_serializable(
        self, integrator_with_test_graph, entity_id, depths
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph
        WHEN get_entity_neighborhood method is called and result is serialized to JSON
        THEN expect serialization to complete without exceptions
        """
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depths['two'])
        json_str = json.dumps(result)
        
        # Assert
        assert isinstance(json_str, str), f"Expected JSON string, got {type(json_str).__name__}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_result_then_json_is_deserializable(
        self, integrator_with_test_graph, entity_id, depths
    ):
        """
        GIVEN GraphRAGIntegrator instance with populated test graph
        WHEN get_entity_neighborhood method is called and result is serialized then deserialized
        THEN expect deserialized result to equal original result
        """
        # Act
        result = await integrator_with_test_graph.get_entity_neighborhood(entity_id, depth=depths['two'])
        json_str = json.dumps(result)
        deserialized = json.loads(json_str)
        
        # Assert
        assert deserialized == result, f"Expected deserialized result to match original, got differences"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("expected_field,expected_value", [
        ("node_count", 103),
        ("edge_count", 103),
    ])
    async def test_when_getting_neighborhood_with_large_graph_then_result_fields_are_correct(
        self, integrator_with_large_graph, entity_id, expected_field, expected_value, depths, 
    ):
        """
        GIVEN GraphRAGIntegrator instance with large graph (100 additional entities)
        WHEN get_entity_neighborhood method is called with depth=1
        THEN expect result fields to have correct values for large graph
        """
        # Act
        result = await integrator_with_large_graph.get_entity_neighborhood(entity_id, depth=depths['one'])
        
        # Assert
        assert result[expected_field] == expected_value, f"Expected {expected_field} to be {expected_value}, got {result[expected_field]}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_performance_graph_then_completes_efficiently(
        self, integrator_with_performance_graph, entity_id, depths
    ):
        """
        GIVEN GraphRAGIntegrator instance with performance graph (50 additional entities)
        WHEN get_entity_neighborhood method is called
        THEN expect operation to complete without performance issues
        """
        # Act
        result = await integrator_with_performance_graph.get_entity_neighborhood(entity_id, depth=depths['one'])
        
        # Assert
        assert "error" not in result, f"Expected successful result, got error: {result.get('error', 'No error key')}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_large_graph_then_center_entity_is_preserved(
        self, integrator_with_large_graph, entity_id, depths
    ):
        """
        GIVEN GraphRAGIntegrator instance with large graph (100 additional entities)
        WHEN get_entity_neighborhood method is called
        THEN expect center_entity_id to remain correct
        """
        # Act
        result = await integrator_with_large_graph.get_entity_neighborhood(entity_id, depth=depths['one'])

        # Assert
        assert result["center_entity_id"] == entity_id, f"Expected center_entity_id to be {entity_id}, got {result['center_entity_id']}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_from_cyclic_graph_then_terminates_properly(
        self, cyclic_graph_integrator, entity_id, depths
    ):
        """
        GIVEN GraphRAGIntegrator instance with cyclic graph that could cause infinite traversal
        WHEN get_entity_neighborhood method is called with depth=3
        THEN expect algorithm to terminate properly without infinite loops
        """
        # Act
        result = await cyclic_graph_integrator.get_entity_neighborhood(entity_id, depth=depths["three"])

        # Assert
        assert "error" not in result, \
            f"Expected successful result, got error: {result.get('error', 'No error key')}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_from_cyclic_graph_then_no_duplicate_nodes(
        self, cyclic_graph_integrator, entity_id, depths
    ):
        """
        GIVEN GraphRAGIntegrator instance with cyclic graph containing cycles
        WHEN get_entity_neighborhood method is called
        THEN expect each node to be visited only once with no duplicates
        """
        # Act
        result = await cyclic_graph_integrator.get_entity_neighborhood(entity_id, depth=depths["three"])
        node_ids = [node["id"] for node in result["nodes"]]
        unique_node_ids = set(node_ids)

        # Assert
        assert len(node_ids) == len(unique_node_ids), \
            f"Expected no duplicate nodes, got {len(node_ids)} total vs {len(unique_node_ids)} unique"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_from_cyclic_graph_then_node_count_matches_unique_nodes(
        self, cyclic_graph_integrator, entity_id, depths
    ):
        """
        GIVEN GraphRAGIntegrator instance with cyclic graph containing cycles
        WHEN get_entity_neighborhood method is called
        THEN expect node_count field to match actual number of unique nodes
        """
        # Act
        result = await cyclic_graph_integrator.get_entity_neighborhood(entity_id, depth=depths["three"])
        unique_node_ids = set(node["id"] for node in result["nodes"])
        
        # Assert
        assert result["node_count"] == len(unique_node_ids), f"Expected node_count {result['node_count']} to match unique nodes {len(unique_node_ids)}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_self_loops_then_entity_not_duplicated(
        self, self_loop_integrator, entity_id, depths
    ):
        """
        GIVEN GraphRAGIntegrator instance with entity that has self-referencing edges
        WHEN get_entity_neighborhood method is called
        THEN expect entity to not be duplicated in results
        """
        # Act
        result = await self_loop_integrator.get_entity_neighborhood(entity_id, depth=depths["one"])
        node_ids = [node["id"] for node in result["nodes"]]
        entity_1_count = node_ids.count(entity_id)
        
        # Assert
        assert entity_1_count == 1, f"Expected entity {entity_id} to appear exactly once, got {entity_1_count} occurrences"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_self_loops_then_includes_self_loop_edge(
        self, self_loop_integrator, entity_id
    ):
        """
        GIVEN GraphRAGIntegrator instance with entity that has self-referencing edges
        WHEN get_entity_neighborhood method is called
        THEN expect self-loop edge to be included in results
        """
        depth = 1

        # Act
        result = await self_loop_integrator.get_entity_neighborhood(entity_id, depth=depth)
        self_loops = [edge for edge in result["edges"] 
                     if edge["source"] == entity_id and edge["target"] == entity_id]
        
        # Assert
        assert len(self_loops) == 1, f"Expected exactly one self-loop edge, got {len(self_loops)}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_concurrent_calls_then_all_complete_successfully(
        self, get_entity_neighborhood_concurrent_tasks, entity_id
    ):
        """
        GIVEN GraphRAGIntegrator instance with multiple concurrent calls to get_entity_neighborhood
        WHEN executed simultaneously
        THEN expect all calls to complete successfully without errors
        """
        # Arrange
        tasks = await get_entity_neighborhood_concurrent_tasks(entity_id)
        
        # Act
        results = await asyncio.gather(*tasks)
        
        # Assert
        assert all("error" not in result for result in results), f"Expected all results to be successful, got errors in some results"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_concurrent_calls_then_results_have_correct_center_entity(
        self, get_entity_neighborhood_concurrent_tasks, entity_id
    ):
        """
        GIVEN GraphRAGIntegrator instance with multiple concurrent calls to get_entity_neighborhood
        WHEN executed simultaneously
        THEN expect all results to have correct center_entity_id
        """
        # Arrange
        tasks = await get_entity_neighborhood_concurrent_tasks(entity_id)
        
        # Act
        results = await asyncio.gather(*tasks)
        
        # Assert
        assert all(result["center_entity_id"] == entity_id for result in results), f"Expected all results to have center_entity_id {entity_id}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_concurrent_calls_then_results_have_correct_depth(
        self, get_entity_neighborhood_concurrent_tasks, entity_id
    ):
        """
        GIVEN GraphRAGIntegrator instance with multiple concurrent calls to get_entity_neighborhood
        WHEN executed simultaneously
        THEN expect all results to have correct depth value
        """
        # Arrange
        expected_depth = 1
        tasks = await get_entity_neighborhood_concurrent_tasks(entity_id, depth=expected_depth)
        
        # Act
        results = await asyncio.gather(*tasks)
        
        # Assert
        assert all(result["depth"] == expected_depth for result in results), f"Expected all results to have depth {expected_depth}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_concurrent_calls_then_results_have_correct_node_count(
        self, get_entity_neighborhood_concurrent_tasks, entity_id
    ):
        """
        GIVEN GraphRAGIntegrator instance with multiple concurrent calls to get_entity_neighborhood
        WHEN executed simultaneously
        THEN expect all results to have correct node_count
        """
        # Arrange
        expected_node_count = 3
        tasks = await get_entity_neighborhood_concurrent_tasks(entity_id)
        
        # Act
        results = await asyncio.gather(*tasks)
        
        # Assert
        assert all(result["node_count"] == expected_node_count for result in results), f"Expected all results to have node_count {expected_node_count}"

    @pytest.mark.asyncio
    async def test_when_getting_neighborhood_with_concurrent_calls_then_all_results_identical(
        self, get_entity_neighborhood_concurrent_tasks, entity_id
    ):
        """
        GIVEN GraphRAGIntegrator instance with multiple concurrent calls to get_entity_neighborhood
        WHEN executed simultaneously
        THEN expect all results to be identical with no race conditions
        """
        # Arrange
        tasks = await get_entity_neighborhood_concurrent_tasks(entity_id)
        
        # Act
        results = await asyncio.gather(*tasks)
        first_result = results[0]
        
        # Assert
        assert all(result == first_result for result in results[1:]), f"Expected all results to be identical, got differences"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
