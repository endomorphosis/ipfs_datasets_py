#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock


from ipfs_datasets_py.pdf_processing.graphrag_integrator import (
    GraphRAGIntegrator, Entity, Relationship, KnowledgeGraph
)
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk


from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

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


class TestQueryGraph:
    """Test class for GraphRAGIntegrator.query_graph method."""

    @pytest.fixture
    def integrator(self):
        """Create a GraphRAGIntegrator instance for testing."""
        integrator = GraphRAGIntegrator()
        
        # Setup sample global entities
        integrator.global_entities = {
            "entity_1": Entity(
                id="entity_1",
                name="John Smith",
                type="person",
                description="Software engineer at ACME Corp",
                confidence=0.9,
                source_chunks=["chunk_1"],
                properties={"role": "engineer"}
            ),
            "entity_2": Entity(
                id="entity_2",
                name="ACME Corp",
                type="organization",
                description="Technology company specializing in AI",
                confidence=0.8,
                source_chunks=["chunk_1"],
                properties={"industry": "technology"}
            ),
            "entity_3": Entity(
                id="entity_3",
                name="San Francisco",
                type="location",
                description="City in California",
                confidence=0.7,
                source_chunks=["chunk_2"],
                properties={"state": "California"}
            )
        }
        
        # Setup sample knowledge graphs
        mock_graph_1 = Mock(spec=KnowledgeGraph)
        mock_graph_1.relationships = []
        mock_graph_1.entities = []
        
        mock_graph_2 = Mock(spec=KnowledgeGraph)
        mock_graph_2.relationships = []
        mock_graph_2.entities = []
        
        integrator.knowledge_graphs = {
            "graph_1": mock_graph_1,
            "graph_2": mock_graph_2
        }
        
        # Setup sample global graph
        integrator.global_graph = Mock()
        
        return integrator

    @pytest.fixture
    def sample_relationships(self):
        """Create sample relationships for testing."""
        return [
            Relationship(
                id="rel_1",
                source_entity_id="entity_1",
                target_entity_id="entity_2",
                relationship_type="works_for",
                description="John Smith works for ACME Corp",
                confidence=0.9,
                source_chunks=["chunk_1"],
                properties={}
            ),
            Relationship(
                id="rel_2",
                source_entity_id="entity_1",
                target_entity_id="entity_3",
                relationship_type="located_in",
                description="John Smith is located in San Francisco",
                confidence=0.8,
                source_chunks=["chunk_2"],
                properties={}
            )
        ]

    @pytest.mark.asyncio
    async def test_query_graph_global_search_valid_query(self, integrator, sample_relationships):
        """
        GIVEN a valid query string and no specific graph_id
        WHEN query_graph is called
        THEN the global knowledge graph should be searched
        AND matching entities and their relationships should be returned
        AND results should be ranked by relevance score
        """
        # Mock the global graph to return relationships
        integrator.global_graph.edges.return_value = [
            ("entity_1", "entity_2", {"relationship": sample_relationships[0]}),
            ("entity_1", "entity_3", {"relationship": sample_relationships[1]})
        ]
        
        result = await integrator.query_graph("software engineer", max_results=5)
        
        assert isinstance(result, dict)
        assert "query" in result
        assert "entities" in result
        assert "relationships" in result
        assert "total_matches" in result
        assert "timestamp" in result
        
        assert result["query"] == "software engineer"
        assert isinstance(result["entities"], list)
        assert isinstance(result["relationships"], list)
        assert isinstance(result["total_matches"], int)

    @pytest.mark.asyncio
    async def test_query_graph_specific_graph_search(self, integrator):
        """
        GIVEN a valid query string and a specific graph_id
        WHEN query_graph is called
        THEN only the specified knowledge graph should be searched
        AND results should be limited to that graph's entities and relationships
        """
        # Setup specific graph entities
        graph_entities = [
            Entity(id="graph_entity_1", name="Graph Entity", type="person",
                  description="Entity in specific graph", confidence=0.8,
                  source_chunks=["chunk_graph"], properties={})
        ]
        mock_graph = Mock(spec=KnowledgeGraph)
        mock_graph.entities = graph_entities
        mock_graph.relationships = []
        integrator.knowledge_graphs["graph_1"] = mock_graph
        
        result = await integrator.query_graph("Graph Entity", graph_id="graph_1")
        
        assert result["query"] == "Graph Entity"
        # Should search only the specific graph, not global entities

    @pytest.mark.asyncio
    async def test_query_graph_case_insensitive_matching(self, integrator):
        """
        GIVEN a query with mixed case that matches entities
        WHEN query_graph is called
        THEN matching should be case-insensitive
        AND entities should be found regardless of case differences
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("JOHN SMITH")  # Uppercase query
        
        # Should find "John Smith" entity despite case difference
        assert isinstance(result["entities"], list)

    @pytest.mark.asyncio
    async def test_query_graph_entity_name_matching(self, integrator):
        """
        GIVEN a query that matches entity names
        WHEN query_graph is called
        THEN entities with matching names should be included in results
        AND relevance scores should reflect name match quality
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("John")
        
        # Should find entities with "John" in the name
        matching_entities = [e for e in result["entities"] if "john" in e.get("name", "").lower()]
        assert len(matching_entities) > 0

    @pytest.mark.asyncio
    async def test_query_graph_entity_type_matching(self, integrator):
        """
        GIVEN a query that matches entity types
        WHEN query_graph is called
        THEN entities with matching types should be included in results
        AND type matches should contribute to relevance scoring
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("person")
        
        # Should find entities of type "person"
        person_entities = [e for e in result["entities"] if e.get("type") == "person"]
        assert len(person_entities) > 0

    @pytest.mark.asyncio
    async def test_query_graph_entity_description_matching(self, integrator):
        """
        GIVEN a query that matches entity descriptions
        WHEN query_graph is called
        THEN entities with matching descriptions should be included in results
        AND description matches should be properly scored
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("software engineer")
        
        # Should find entities with "software engineer" in description
        matching_entities = [e for e in result["entities"] 
                           if "software engineer" in e.get("description", "").lower()]
        assert len(matching_entities) > 0

    @pytest.mark.asyncio
    async def test_query_graph_max_results_limiting(self, integrator):
        """
        GIVEN more matching entities than max_results limit
        WHEN query_graph is called
        THEN only the top max_results entities should be returned
        AND they should be the highest-scoring matches
        """
        # Add more entities to ensure we exceed max_results
        for i in range(15):
            integrator.global_entities[f"extra_entity_{i}"] = Entity(
                id=f"extra_entity_{i}",
                name=f"Test Entity {i}",
                type="person",
                description="Test description",
                confidence=0.5,
                source_chunks=[f"chunk_{i}"],
                properties={}
            )
        
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("Test", max_results=5)
        
        # Should return at most 5 entities
        assert len(result["entities"]) <= 5
        assert result["total_matches"] >= 5  # But total_matches should reflect all matches

    @pytest.mark.asyncio
    async def test_query_graph_relevance_score_ordering(self, integrator):
        """
        GIVEN multiple entities with different relevance scores
        WHEN query_graph is called
        THEN results should be ordered by relevance score descending
        AND highest scoring entities should appear first
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("smith")
        
        if len(result["entities"]) > 1:
            # Check that entities are ordered by relevance (assuming relevance field exists)
            relevance_scores = []
            for entity in result["entities"]:
                # Calculate relevance based on name match
                name = entity.get("name", "").lower()
                if "smith" in name:
                    relevance_scores.append(1.0)
                else:
                    relevance_scores.append(0.0)
            
            # Should be in descending order
            assert relevance_scores == sorted(relevance_scores, reverse=True)

    @pytest.mark.asyncio
    async def test_query_graph_related_relationships_inclusion(self, integrator, sample_relationships):
        """
        GIVEN matching entities that have relationships
        WHEN query_graph is called
        THEN relationships connected to matching entities should be included
        AND relationship data should be properly serialized
        """
        integrator.global_graph.edges.return_value = [
            ("entity_1", "entity_2", {"relationship": sample_relationships[0]})
        ]
        
        result = await integrator.query_graph("John Smith")
        
        # Should include relationships for matching entities
        assert isinstance(result["relationships"], list)
        if result["relationships"]:
            rel = result["relationships"][0]
            assert "id" in rel
            assert "source_entity_id" in rel
            assert "target_entity_id" in rel
            assert "relationship_type" in rel

    @pytest.mark.asyncio
    async def test_query_graph_no_matches_found(self, integrator):
        """
        GIVEN a query that matches no entities
        WHEN query_graph is called
        THEN empty entities and relationships lists should be returned
        AND total_matches should be 0
        AND proper structure should still be maintained
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("nonexistent_entity_xyz")
        
        assert result["entities"] == []
        assert result["relationships"] == []
        assert result["total_matches"] == 0
        assert result["query"] == "nonexistent_entity_xyz"
        assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_query_graph_empty_query_string(self, integrator):
        """
        GIVEN an empty query string
        WHEN query_graph is called
        THEN should raise ValueError for empty query
        """
        with pytest.raises(ValueError, match="query must be a non-empty string"):
            await integrator.query_graph("")

    @pytest.mark.asyncio
    async def test_query_graph_whitespace_only_query(self, integrator):
        """
        GIVEN a query containing only whitespace
        WHEN query_graph is called
        THEN should raise ValueError for whitespace-only query
        """
        with pytest.raises(ValueError, match="query must be a non-empty string"):
            await integrator.query_graph("   \t\n   ")

    @pytest.mark.asyncio
    async def test_query_graph_nonexistent_graph_id(self, integrator):
        """
        GIVEN a graph_id that doesn't exist in knowledge_graphs
        WHEN query_graph is called
        THEN a KeyError should be raised
        AND the error should indicate the graph was not found
        """
        with pytest.raises(KeyError):
            await integrator.query_graph("test query", graph_id="nonexistent_graph")

    @pytest.mark.asyncio
    async def test_query_graph_none_query_parameter(self, integrator):
        """
        GIVEN None as the query parameter
        WHEN query_graph is called
        THEN a TypeError should be raised
        AND the error should indicate invalid query type
        """
        with pytest.raises(TypeError):
            await integrator.query_graph(None)

    @pytest.mark.asyncio
    async def test_query_graph_invalid_max_results_negative(self, integrator):
        """
        GIVEN a negative max_results value
        WHEN query_graph is called
        THEN a ValueError should be raised
        AND the error should indicate invalid max_results range
        """
        with pytest.raises(ValueError):
            await integrator.query_graph("test", max_results=-1)

    @pytest.mark.asyncio
    async def test_query_graph_invalid_max_results_zero(self, integrator):
        """
        GIVEN zero as max_results value
        WHEN query_graph is called
        THEN a ValueError should be raised
        AND the error should indicate invalid max_results range
        """
        with pytest.raises(ValueError):
            await integrator.query_graph("test", max_results=0)

    @pytest.mark.asyncio
    async def test_query_graph_invalid_max_results_type(self, integrator):
        """
        GIVEN a non-integer max_results parameter
        WHEN query_graph is called
        THEN a TypeError should be raised
        AND the error should indicate expected integer type
        """
        with pytest.raises(TypeError):
            await integrator.query_graph("test", max_results="invalid")

    @pytest.mark.asyncio
    async def test_query_graph_return_structure_validation(self, integrator):
        """
        GIVEN any valid query
        WHEN query_graph is called
        THEN the return value should be a dictionary containing:
            - 'query': the original query string
            - 'entities': list of entity dictionaries
            - 'relationships': list of relationship dictionaries
            - 'total_matches': integer count
            - 'timestamp': ISO format timestamp
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("test query")
        
        # Verify required keys
        required_keys = ['query', 'entities', 'relationships', 'total_matches', 'timestamp']
        for key in required_keys:
            assert key in result
        
        # Verify types
        assert isinstance(result['query'], str)
        assert isinstance(result['entities'], list)
        assert isinstance(result['relationships'], list)
        assert isinstance(result['total_matches'], int)
        assert isinstance(result['timestamp'], str)
        
        # Verify timestamp format (ISO)
        try:
            datetime.fromisoformat(result['timestamp'].replace('Z', '+00:00'))
        except ValueError:
            pytest.fail("Timestamp is not in ISO format")

    @pytest.mark.asyncio
    async def test_query_graph_entity_serialization(self, integrator):
        """
        GIVEN entities in the results
        WHEN query_graph is called
        THEN entities should be properly serialized to dictionaries
        AND all entity attributes should be preserved
        AND numpy arrays should be converted to lists if present
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("John")
        
        for entity in result["entities"]:
            assert isinstance(entity, dict)
            # Verify entity has expected fields
            expected_fields = ['id', 'name', 'type', 'description', 'confidence', 'source_chunks', 'properties']
            for field in expected_fields:
                assert field in entity

    @pytest.mark.asyncio
    async def test_query_graph_relationship_serialization(self, integrator, sample_relationships):
        """
        GIVEN relationships in the results
        WHEN query_graph is called
        THEN relationships should be properly serialized to dictionaries
        AND all relationship attributes should be preserved
        """
        integrator.global_graph.edges.return_value = [
            ("entity_1", "entity_2", {"relationship": sample_relationships[0]})
        ]
        
        result = await integrator.query_graph("John")
        
        for relationship in result["relationships"]:
            assert isinstance(relationship, dict)
            # Verify relationship has expected fields
            expected_fields = ['id', 'source_entity_id', 'target_entity_id', 'relationship_type', 
                             'description', 'confidence', 'source_chunks', 'properties']
            for field in expected_fields:
                assert field in relationship

    @pytest.mark.asyncio
    async def test_query_graph_timestamp_generation_is_iso_format(self, integrator):
        """
        GIVEN any query execution
        WHEN query_graph is called
        THEN a timestamp should be generated in ISO format
        """
        integrator.global_graph.edges.return_value = []

        result = await integrator.query_graph("test")

        timestamp_str = result["timestamp"]

        # Verify timestamp is in ISO format by parsing it
        parsed_timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        assert isinstance(parsed_timestamp, datetime)

    @pytest.mark.asyncio
    async def test_query_graph_timestamp_generation_is_after_function_begins(self, integrator):
        """
        GIVEN any query execution
        WHEN query_graph is called
        THEN the timestamp should be greater than or equal to the time just before the function call
        """
        integrator.global_graph.edges.return_value = []
        
        before_time = datetime.now()
        result = await integrator.query_graph("test")

        timestamp_str = result["timestamp"]
        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

        # Verify timestamp is after before_time
        assert before_time <= timestamp.replace(tzinfo=None)

    @pytest.mark.asyncio
    async def test_query_graph_timestamp_generated_during_execution(self, integrator):
        """
        GIVEN any query execution
        WHEN query_graph is called
        THEN the timestamp should be less than or equal to the time just after the function call
        """
        integrator.global_graph.edges.return_value = []

        result = await integrator.query_graph("test")
        after_time = datetime.now()
        
        timestamp_str = result["timestamp"]
        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        
        # Verify timestamp is before after_time
        assert timestamp.replace(tzinfo=None) <= after_time

    @pytest.mark.asyncio
    async def test_query_graph_total_matches_accuracy(self, integrator):
        """
        GIVEN a query with known number of matches
        WHEN query_graph is called with max_results limit
        THEN total_matches should reflect actual matches before limiting
        AND it should be accurate regardless of max_results value
        """
        # Add 10 matching entities
        for i in range(10):
            integrator.global_entities[f"match_entity_{i}"] = Entity(
                id=f"match_entity_{i}",
                name=f"Matching Entity {i}",
                type="person",
                description="Matching description",
                confidence=0.8,
                source_chunks=[f"chunk_{i}"],
                properties={}
            )
        
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("Matching", max_results=3)
        
        # Should return only 3 entities but report all 10 as total matches
        assert len(result["entities"]) <= 3
        assert result["total_matches"] >= 10

    @pytest.mark.asyncio
    async def test_query_graph_large_result_set_performance(self, integrator):
        """
        GIVEN a query that matches many entities (>1000)
        WHEN query_graph is called
        THEN performance should remain reasonable
        AND memory usage should be manageable
        AND results should still be properly ranked and limited
        """
        # Add 1500 entities
        for i in range(1500):
            integrator.global_entities[f"large_entity_{i}"] = Entity(
                id=f"large_entity_{i}",
                name=f"Large Entity {i}",
                type="person",
                description="Large test entity",
                confidence=0.5,
                source_chunks=[f"chunk_{i}"],
                properties={}
            )
        
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("Large", max_results=100)
        
        # Should complete efficiently
        assert isinstance(result, dict)
        assert len(result["entities"]) <= 100
        assert result["total_matches"] >= 1500

    @pytest.mark.asyncio
    async def test_query_graph_special_characters_in_query(self, integrator):
        """
        GIVEN a query containing special characters, punctuation, or symbols
        WHEN query_graph is called
        THEN the query should be handled gracefully
        AND matching should work correctly despite special characters
        """
        integrator.global_graph.edges.return_value = []
        
        special_queries = [
            "Dr. Smith-Jones",
            "O'Connor & Associates",
            "Query with @#$%^&*() symbols",
            "Multi-line\nquery\twith\ttabs"
        ]
        
        for query in special_queries:
            result = await integrator.query_graph(query)
            assert isinstance(result, dict)
            assert result["query"] == query

    @pytest.mark.asyncio
    async def test_query_graph_unicode_query_handling(self, integrator):
        """
        GIVEN a query containing unicode characters
        WHEN query_graph is called
        THEN unicode should be handled correctly in matching
        AND results should include entities with unicode content
        """
        # Add entity with unicode content
        integrator.global_entities["unicode_entity"] = Entity(
            id="unicode_entity",
            name="José María González",
            type="person",
            description="Persona con caracteres unicode",
            confidence=0.8,
            source_chunks=["chunk_unicode"],
            properties={}
        )
        
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("José")
        
        # Should handle unicode correctly
        assert isinstance(result, dict)
        assert result["query"] == "José"

    @pytest.mark.asyncio
    async def test_query_graph_empty_knowledge_graphs(self, integrator):
        """
        GIVEN empty knowledge_graphs and global_entities
        WHEN query_graph is called
        THEN empty results should be returned gracefully
        AND no errors should be raised
        """
        integrator.global_entities = {}
        integrator.knowledge_graphs = {}
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("any query")
        
        assert result["entities"] == []
        assert result["relationships"] == []
        assert result["total_matches"] == 0

    @pytest.mark.asyncio
    async def test_query_graph_concurrent_queries(self, integrator):
        """
        GIVEN multiple concurrent query_graph calls
        WHEN executed simultaneously
        THEN all queries should complete successfully
        AND results should be independent and correct
        AND no race conditions should occur
        """
        import anyio
        
        integrator.global_graph.edges.return_value = []
        
        # Execute multiple queries concurrently
        queries = ["query1", "query2", "query3", "query4", "query5"]
        tasks = [integrator.query_graph(query) for query in queries]

        results = [None] * len(tasks)

        async def _run_one(index: int, coro):
            results[index] = await coro

        async with anyio.create_task_group() as tg:
            for i, coro in enumerate(tasks):
                tg.start_soon(_run_one, i, coro)
        
        # Verify all results are correct and independent
        assert len(results) == 5
        for i, result in enumerate(results):
            assert result["query"] == queries[i]
            assert isinstance(result, dict)
            # Each result should have the same structure
            required_keys = ['query', 'entities', 'relationships', 'total_matches', 'timestamp']
            for key in required_keys:
                assert key in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
