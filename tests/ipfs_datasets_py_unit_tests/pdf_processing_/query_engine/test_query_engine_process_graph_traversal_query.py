#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py
# Auto-generated on 2025-07-07 02:28:56

import pytest
import os
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, List, Any, Optional
import networkx as nx

from tests._test_utils import (
    raise_on_bad_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine, QueryResult
from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, Entity, Relationship

# Check if each classes methods are accessible:
assert QueryEngine.query
assert QueryEngine._normalize_query
assert QueryEngine._detect_query_type
assert QueryEngine._process_entity_query
assert QueryEngine._process_relationship_query
assert QueryEngine._process_semantic_query
assert QueryEngine._process_document_query
assert QueryEngine._process_cross_document_query
assert QueryEngine._process_graph_traversal_query
assert QueryEngine._extract_entity_names_from_query
assert QueryEngine._get_entity_documents
assert QueryEngine._get_relationship_documents
assert QueryEngine._generate_query_suggestions
assert QueryEngine.get_query_analytics

# Check if the modules's imports are accessible:
import logging
import json
from dataclasses import dataclass
from datetime import datetime
import re

from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer


class TestQueryEngineProcessGraphTraversalQuery:
    """Test QueryEngine._process_graph_traversal_query method for graph path-finding and connection analysis."""

    def setup_method(self):
        """Set up test fixtures before each test method."""
        # Mock dependencies
        self.mock_graphrag = Mock(spec=GraphRAGIntegrator)
        self.mock_storage = Mock(spec=IPLDStorage)
        
        # Create a mock NetworkX graph
        self.mock_graph = nx.Graph()
        
        # Add test entities as nodes
        self.mock_graph.add_node("Bill Gates", type="Person")
        self.mock_graph.add_node("Microsoft", type="Organization")
        self.mock_graph.add_node("Paul Allen", type="Person")
        self.mock_graph.add_node("GitHub", type="Organization")
        self.mock_graph.add_node("John Smith", type="Person")
        self.mock_graph.add_node("Mary Johnson", type="Person")
        
        # Add relationships as edges
        self.mock_graph.add_edge("Bill Gates", "Microsoft", relationship="founded", confidence=0.95)
        self.mock_graph.add_edge("Paul Allen", "Microsoft", relationship="co_founded", confidence=0.92)
        self.mock_graph.add_edge("Microsoft", "GitHub", relationship="acquired", confidence=0.88)
        
        # Create isolated nodes for testing no-path scenarios
        self.mock_graph.add_node("Isolated Entity", type="Organization")
        
        # Mock GraphRAG integrator methods
        self.mock_graphrag.get_global_graph.return_value = self.mock_graph
        self.mock_graphrag.get_entity_by_name.side_effect = self._mock_get_entity_by_name
        
        # Mock entities for testing
        self.mock_entities = {
            "Bill Gates": Entity(
                id="ent_001",
                name="Bill Gates",
                type="Person",
                description="Co-founder of Microsoft",
                properties={"role": "CEO", "company": "Microsoft"},
                source_chunks=["doc1_chunk1"]
            ),
            "Microsoft": Entity(
                id="ent_002",
                name="Microsoft",
                type="Organization",
                description="Technology company",
                properties={"industry": "Technology"},
                source_chunks=["doc1_chunk2"]
            ),
            "Paul Allen": Entity(
                id="ent_003",
                name="Paul Allen",
                type="Person",
                description="Co-founder of Microsoft",
                properties={"role": "Co-founder"},
                source_chunks=["doc1_chunk3"]
            )
        }
        
        # Create QueryEngine instance
        with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer'):
            self.query_engine = QueryEngine(
                graphrag_integrator=self.mock_graphrag,
                storage=self.mock_storage
            )

    def _mock_get_entity_by_name(self, name: str) -> Optional[Entity]:
        """Helper method to mock entity retrieval by name."""
        return self.mock_entities.get(name)

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_successful_path_finding(self):
        """
        GIVEN a QueryEngine instance with NetworkX graph and entities
        AND normalized query "path bill gates microsoft"
        AND path exists between entities in global graph
        WHEN _process_graph_traversal_query is called
        THEN expect:
            - Entity names extracted using capitalization patterns
            - NetworkX shortest_path algorithm used
            - Path found and formatted as QueryResult
            - Path length used as relevance score
        """
        query = "path Bill Gates Microsoft"
        filters = None
        max_results = 10
        
        results = await self.query_engine._process_graph_traversal_query(query, filters, max_results)
        
        assert len(results) == 1
        result = results[0]
        
        assert result.type == "graph_path"
        assert "Bill Gates" in result.content
        assert "Microsoft" in result.content
        assert "→" in result.content  # Path arrow notation
        assert result.relevance_score > 0.0
        assert result.source_document == "multiple"
        assert isinstance(result.metadata, dict)
        assert "path_entities" in result.metadata
        assert "path_length" in result.metadata

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_entity_name_extraction(self):
        """
        GIVEN a QueryEngine instance
        AND normalized query "connection john smith mary johnson"
        WHEN _process_graph_traversal_query is called
        THEN expect:
            - _extract_entity_names_from_query called
            - Capitalized word sequences identified as entity names
            - At least 2 entities required for path finding
        """
        query = "connection John Smith Mary Johnson"
        filters = None
        max_results = 10
        
        with patch.object(self.query_engine, '_extract_entity_names_from_query', 
                         return_value=["John Smith", "Mary Johnson"]) as mock_extract:
            try:
                await self.query_engine._process_graph_traversal_query(query, filters, max_results)
            except Exception:
                pass  # We expect this to fail since entities don't exist in graph
            
            mock_extract.assert_called_once_with(query)

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_insufficient_entities(self):
        """
        GIVEN a QueryEngine instance
        AND normalized query "path microsoft" (only one entity)
        WHEN _process_graph_traversal_query is called
        THEN expect ValueError to be raised (fewer than 2 entities)
        """
        query = "path Microsoft"
        filters = None
        max_results = 10
        
        with pytest.raises(ValueError, match="At least 2 entities required"):
            await self.query_engine._process_graph_traversal_query(query, filters, max_results)

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_no_path_exists(self):
        """
        GIVEN a QueryEngine instance with disconnected graph components
        AND normalized query "path isolated entity another entity"
        AND no path exists between entities
        WHEN _process_graph_traversal_query is called
        THEN expect NetworkXNoPath exception to be raised
        """
        query = "path Bill Gates Isolated Entity"
        filters = None
        max_results = 10
        
        with pytest.raises(nx.NetworkXNoPath):
            await self.query_engine._process_graph_traversal_query(query, filters, max_results)

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_max_path_length_filter(self):
        """
        GIVEN a QueryEngine instance with long paths
        AND normalized query "connection entity1 entity2"
        AND filters {"max_path_length": 3}
        WHEN _process_graph_traversal_query is called
        THEN expect:
            - Only paths with length <= 3 considered
            - Longer paths filtered out or limited
            - Path length restriction applied appropriately
        """
        # Create a longer path for testing
        self.mock_graph.add_node("Intermediate", type="Organization")
        self.mock_graph.add_edge("Microsoft", "Intermediate", relationship="partners_with")
        self.mock_graph.add_edge("Intermediate", "GitHub", relationship="collaborates_with")
        
        query = "path Bill Gates GitHub"
        filters = {"max_path_length": 2}
        max_results = 10
        
        results = await self.query_engine._process_graph_traversal_query(query, filters, max_results)
        
        # Should find direct path through Microsoft (length 2) but not longer paths
        assert all(result.metadata["path_length"] <= 2 for result in results)

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_entity_types_filter(self):
        """
        GIVEN a QueryEngine instance with entities of different types
        AND normalized query "path through organizations"
        AND filters {"entity_types": ["Organization"]}
        WHEN _process_graph_traversal_query is called
        THEN expect:
            - Only paths through Organization entities considered
            - Path entities filtered by specified types
            - Person entities excluded from path
        """
        query = "path Microsoft GitHub"
        filters = {"entity_types": ["Organization"]}
        max_results = 10
        
        results = await self.query_engine._process_graph_traversal_query(query, filters, max_results)
        
        if results:
            path_entities = results[0].metadata["path_entities"]
            # All entities in path should be Organizations (except endpoints might be allowed)
            for entity in path_entities[1:-1]:  # Exclude start and end entities
                assert entity.get("type") == "Organization"

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_relationship_types_filter(self):
        """
        GIVEN a QueryEngine instance with different relationship types
        AND normalized query "path via founding relationships"
        AND filters {"relationship_types": ["founded", "founded_by"]}
        WHEN _process_graph_traversal_query is called
        THEN expect:
            - Only paths using specified relationship types
            - Other relationship types excluded from path
            - Path restricted to founding-related connections
        """
        query = "path via founding Bill Gates Microsoft"
        filters = {"relationship_types": ["founded", "co_founded"]}
        max_results = 10
        
        results = await self.query_engine._process_graph_traversal_query(query, filters, max_results)
        
        if results:
            path_relationships = results[0].metadata["path_relationships"]
            for rel in path_relationships:
                assert rel["type"] in ["founded", "co_founded"]

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_min_confidence_filter(self):
        """
        GIVEN a QueryEngine instance with relationships having confidence scores
        AND normalized query "high confidence path entities"
        AND filters {"min_confidence": 0.8}
        WHEN _process_graph_traversal_query is called
        THEN expect:
            - Only relationships with confidence >= 0.8 used in path
            - Low confidence relationships excluded
            - Path quality improved by confidence filtering
        """
        query = "high confidence path Bill Gates Microsoft"
        filters = {"min_confidence": 0.9}
        max_results = 10
        
        results = await self.query_engine._process_graph_traversal_query(query, filters, max_results)
        
        if results:
            path_relationships = results[0].metadata["path_relationships"]
            for rel in path_relationships:
                assert rel.get("confidence", 0.0) >= 0.9

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_max_results_limiting(self):
        """
        GIVEN a QueryEngine instance with multiple possible paths
        AND normalized query "paths john microsoft"
        AND max_results = 5
        WHEN _process_graph_traversal_query is called
        THEN expect:
            - Exactly 5 results returned (or fewer if less available)
            - Results are shortest paths (best scores)
            - Results ordered by path length (shorter = higher score)
        """
        # Add multiple paths between entities
        self.mock_graph.add_node("Alternative Path", type="Organization")
        self.mock_graph.add_edge("Bill Gates", "Alternative Path", relationship="advises")
        self.mock_graph.add_edge("Alternative Path", "Microsoft", relationship="partners_with")
        
        query = "paths Bill Gates Microsoft"
        filters = None
        max_results = 2
        
        results = await self.query_engine._process_graph_traversal_query(query, filters, max_results)
        
        assert len(results) <= 2
        if len(results) > 1:
            # Results should be ordered by relevance (shorter paths = higher scores)
            assert results[0].relevance_score >= results[1].relevance_score

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_invalid_max_results(self):
        """
        GIVEN a QueryEngine instance
        AND normalized query "test"
        AND max_results = -2 or 0
        WHEN _process_graph_traversal_query is called
        THEN expect ValueError to be raised
        """
        query = "path Bill Gates Microsoft"
        filters = None
        
        with pytest.raises(ValueError, match="max_results must be positive"):
            await self.query_engine._process_graph_traversal_query(query, filters, -2)
        
        with pytest.raises(ValueError, match="max_results must be positive"):
            await self.query_engine._process_graph_traversal_query(query, filters, 0)

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_invalid_filters_type(self):
        """
        GIVEN a QueryEngine instance
        AND normalized query "test"
        AND filters as tuple instead of dict
        WHEN _process_graph_traversal_query is called
        THEN expect TypeError to be raised
        """
        query = "path Bill Gates Microsoft"
        filters = ("invalid", "filter", "type")
        max_results = 10
        
        with pytest.raises(TypeError, match="filters must be a dictionary"):
            await self.query_engine._process_graph_traversal_query(query, filters, max_results)

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_corrupted_graph(self):
        """
        GIVEN a QueryEngine instance with corrupted NetworkX graph
        AND normalized query "path test entities"
        WHEN _process_graph_traversal_query is called
        THEN expect RuntimeError to be raised
        """
        # Mock corrupted graph
        self.mock_graphrag.get_global_graph.return_value = None
        
        query = "path Bill Gates Microsoft"
        filters = None
        max_results = 10
        
        with pytest.raises(RuntimeError, match="Global graph not available"):
            await self.query_engine._process_graph_traversal_query(query, filters, max_results)

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_missing_networkx(self):
        """
        GIVEN a QueryEngine instance without NetworkX library available
        AND normalized query "path entities"
        WHEN _process_graph_traversal_query is called
        THEN expect ImportError to be raised
        """
        with patch('ipfs_datasets_py.pdf_processing.query_engine.nx', None):
            query = "path Bill Gates Microsoft"
            filters = None
            max_results = 10
            
            with pytest.raises(ImportError, match="NetworkX library is required"):
                await self.query_engine._process_graph_traversal_query(query, filters, max_results)

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_result_structure_validation(self):
        """
        GIVEN a QueryEngine instance with valid graph and entities
        AND normalized query "path bill gates microsoft"
        WHEN _process_graph_traversal_query is called
        THEN expect each QueryResult to have:
            - id: str (path identifier)
            - type: "graph_path"
            - content: str (formatted path description)
            - relevance_score: float (inverse of path length, 0.0-1.0)
            - source_document: "multiple" (paths span documents)
            - source_chunks: List[str] (empty for synthetic results)
            - metadata: Dict with complete path information
        """
        query = "path Bill Gates Microsoft"
        filters = None
        max_results = 10
        
        results = await self.query_engine._process_graph_traversal_query(query, filters, max_results)
        
        assert len(results) > 0
        result = results[0]
        
        # Validate structure
        assert isinstance(result.id, str)
        assert result.type == "graph_path"
        assert isinstance(result.content, str)
        assert isinstance(result.relevance_score, float)
        assert 0.0 <= result.relevance_score <= 1.0
        assert result.source_document == "multiple"
        assert isinstance(result.source_chunks, list)
        assert isinstance(result.metadata, dict)
        
        # Validate metadata content
        required_metadata_keys = [
            "path_entities", "path_relationships", "path_length",
            "entity_types_in_path", "relationship_types_in_path"
        ]
        for key in required_metadata_keys:
            assert key in result.metadata

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_path_formatting(self):
        """
        GIVEN a QueryEngine instance with path results
        AND normalized query "connection bill gates microsoft"
        WHEN _process_graph_traversal_query is called
        THEN expect:
            - Path formatted as "Entity1 → relationship → Entity2 → relationship → Entity3"
            - Arrow notation used for path visualization
            - Complete path with entities and relationships shown
        """
        query = "connection Bill Gates Microsoft"
        filters = None
        max_results = 10
        
        results = await self.query_engine._process_graph_traversal_query(query, filters, max_results)
        
        assert len(results) > 0
        result = results[0]
        
        # Check path formatting
        assert "→" in result.content
        assert "Bill Gates" in result.content
        assert "Microsoft" in result.content
        assert "founded" in result.content or "co_founded" in result.content

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_relevance_scoring_by_path_length(self):
        """
        GIVEN a QueryEngine instance with paths of different lengths
        AND normalized query "paths between entities"
        WHEN _process_graph_traversal_query is called
        THEN expect:
            - Shorter paths receive higher relevance scores
            - Scoring inversely related to path length
            - Scores normalized to 0.0-1.0 range
        """
        # Add longer path for comparison
        self.mock_graph.add_node("Intermediate Node", type="Organization")
        self.mock_graph.add_edge("Bill Gates", "Intermediate Node", relationship="advises")
        self.mock_graph.add_edge("Intermediate Node", "Microsoft", relationship="partners_with")
        
        query = "paths Bill Gates Microsoft"
        filters = None
        max_results = 10
        
        results = await self.query_engine._process_graph_traversal_query(query, filters, max_results)
        
        if len(results) > 1:
            # Shorter paths should have higher scores
            for i in range(len(results) - 1):
                if results[i].metadata["path_length"] < results[i+1].metadata["path_length"]:
                    assert results[i].relevance_score >= results[i+1].relevance_score

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_metadata_completeness(self):
        """
        GIVEN a QueryEngine instance with path results
        AND normalized query "path metadata analysis"
        WHEN _process_graph_traversal_query is called
        THEN expect QueryResult.metadata to contain:
            - path_entities: List[Dict] with entity details for each path node
            - path_relationships: List[Dict] with relationship details
            - path_length: int
            - path_confidence: float (if available)
            - entity_types_in_path: List[str]
            - relationship_types_in_path: List[str]
        """
        query = "path metadata Bill Gates Microsoft"
        filters = None
        max_results = 10
        
        results = await self.query_engine._process_graph_traversal_query(query, filters, max_results)
        
        assert len(results) > 0
        metadata = results[0].metadata
        
        # Check required metadata fields
        assert "path_entities" in metadata
        assert "path_relationships" in metadata
        assert "path_length" in metadata
        assert "entity_types_in_path" in metadata
        assert "relationship_types_in_path" in metadata
        
        # Validate data types
        assert isinstance(metadata["path_entities"], list)
        assert isinstance(metadata["path_relationships"], list)
        assert isinstance(metadata["path_length"], int)
        assert isinstance(metadata["entity_types_in_path"], list)
        assert isinstance(metadata["relationship_types_in_path"], list)

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_path_computation_prevention(self):
        """
        GIVEN a QueryEngine instance with very large graph
        AND normalized query "path distant entities"
        WHEN _process_graph_traversal_query is called
        THEN expect:
            - Path finding limited to prevent excessive computation
            - Reasonable limits on path length or search depth
            - Performance protection mechanisms active
        """
        # Create a large graph to test performance limits
        for i in range(100):
            self.mock_graph.add_node(f"Node_{i}", type="Test")
            if i > 0:
                self.mock_graph.add_edge(f"Node_{i-1}", f"Node_{i}", relationship="connects")
        
        query = "path Node_0 Node_99"
        filters = {"max_path_length": 10}  # Should limit computation
        max_results = 5
        
        # Should complete without timeout or excessive computation
        import time
        start_time = time.time()
        
        try:
            results = await self.query_engine._process_graph_traversal_query(query, filters, max_results)
            computation_time = time.time() - start_time
            assert computation_time < 5.0  # Should complete within reasonable time
        except nx.NetworkXNoPath:
            # Acceptable if path exceeds limits
            pass

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_multiple_path_alternatives(self):
        """
        GIVEN a QueryEngine instance with multiple paths between entities
        AND normalized query "alternative paths entities"
        WHEN _process_graph_traversal_query is called
        THEN expect:
            - Multiple alternative paths discovered if available
            - Different path options returned as separate results
            - Path diversity in results when possible
        """
        # Create alternative paths
        self.mock_graph.add_node("Alt Path 1", type="Organization")
        self.mock_graph.add_node("Alt Path 2", type="Organization")
        
        self.mock_graph.add_edge("Bill Gates", "Alt Path 1", relationship="invests_in")
        self.mock_graph.add_edge("Alt Path 1", "Microsoft", relationship="partners_with")
        
        self.mock_graph.add_edge("Bill Gates", "Alt Path 2", relationship="advises")
        self.mock_graph.add_edge("Alt Path 2", "Microsoft", relationship="collaborates_with")
        
        query = "alternative paths Bill Gates Microsoft"
        filters = None
        max_results = 10
        
        results = await self.query_engine._process_graph_traversal_query(query, filters, max_results)
        
        # Should find multiple different paths
        if len(results) > 1:
            path_contents = [result.content for result in results]
            # Paths should be different
            assert len(set(path_contents)) > 1

    @pytest.mark.asyncio
    async def test_process_graph_traversal_query_bidirectional_paths(self):
        """
        GIVEN a QueryEngine instance with directed relationships
        AND normalized query "bidirectional connection entities"
        WHEN _process_graph_traversal_query is called
        THEN expect:
            - Paths considered in both directions if graph is directed
            - Relationship directionality respected
            - Bidirectional analysis when appropriate
        """
        # Convert to directed graph for testing
        directed_graph = nx.DiGraph()
        directed_graph.add_node("Bill Gates", type="Person")
        directed_graph.add_node("Microsoft", type="Organization")
        
        # Add directed edge
        directed_graph.add_edge("Bill Gates", "Microsoft", relationship="founded")
        
        self.mock_graphrag.get_global_graph.return_value = directed_graph
        
        query = "bidirectional connection Bill Gates Microsoft"
        filters = None
        max_results = 10
        
        results = await self.query_engine._process_graph_traversal_query(query, filters, max_results)
        
        # Should find path in the direction that exists
        assert len(results) > 0
        
        # Test reverse direction (should fail for directed graph)
        query_reverse = "bidirectional connection Microsoft Bill Gates"
        try:
            results_reverse = await self.query_engine._process_graph_traversal_query(query_reverse, filters, max_results)
            # If it finds a path, it should be different or empty
            if results_reverse:
                assert results_reverse[0].content != results[0].content
        except nx.NetworkXNoPath:
            # Expected for directed graph with no reverse path
            pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])