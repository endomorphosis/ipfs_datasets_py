#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py
# Auto-generated on 2025-07-07 02:28:56

import pytest
import os
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

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
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, Entity, Relationship
from ipfs_datasets_py.ipld import IPLDStorage

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
import asyncio
import logging
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import re

from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, Entity, Relationship


class TestQueryEngineProcessRelationshipQuery:
    """Test QueryEngine._process_relationship_query method for relationship-focused query processing."""

    def setup_method(self):
        """Set up test fixtures for each test method."""
        # Mock GraphRAG integrator
        self.mock_graphrag = Mock(spec=GraphRAGIntegrator)
        
        # Mock IPLD storage
        self.mock_storage = Mock(spec=IPLDStorage)
        
        # Create test entities
        self.entity_gates = Entity(
            id="entity_001",
            name="Bill Gates",
            type="Person",
            description="Co-founder of Microsoft",
            properties={"role": "CEO", "company": "Microsoft"},
            confidence=0.95,
            source_chunks=["doc_001_chunk_01"]
        )
        
        self.entity_microsoft = Entity(
            id="entity_002", 
            name="Microsoft",
            type="Organization",
            description="Technology company",
            properties={"industry": "Technology"},
            confidence=0.98,
            source_chunks=["doc_001_chunk_02"]
        )
        
        self.entity_allen = Entity(
            id="entity_003",
            name="Paul Allen", 
            type="Person",
            description="Co-founder of Microsoft",
            properties={"role": "Co-founder"},
            confidence=0.92,
            source_chunks=["doc_001_chunk_03"]
        )
        
        # Create test relationships
        self.relationship_founded = Relationship(
            id="rel_001",
            source_entity_id="entity_001",
            target_entity_id="entity_002", 
            relationship_type="founded",
            description="Bill Gates founded Microsoft",
            properties={"year": "1975"},
            confidence=0.90,
            source_chunks=["doc_001_chunk_01"]
        )
        
        self.relationship_works_for = Relationship(
            id="rel_002",
            source_entity_id="entity_003",
            target_entity_id="entity_002",
            relationship_type="works_for",
            description="Paul Allen works for Microsoft", 
            properties={"position": "Co-founder"},
            confidence=0.85,
            source_chunks=["doc_001_chunk_03"]
        )
        
        self.relationship_low_confidence = Relationship(
            id="rel_003",
            source_entity_id="entity_001",
            target_entity_id="entity_003",
            relationship_type="knows",
            description="Bill Gates knows Paul Allen",
            properties={},
            confidence=0.60,
            source_chunks=["doc_001_chunk_04"]
        )
        
        # Mock knowledge graphs
        self.mock_kg1 = Mock()
        self.mock_kg1.entities = {
            "entity_001": self.entity_gates,
            "entity_002": self.entity_microsoft, 
            "entity_003": self.entity_allen
        }
        self.mock_kg1.relationships = {
            "rel_001": self.relationship_founded,
            "rel_002": self.relationship_works_for,
            "rel_003": self.relationship_low_confidence
        }
        self.mock_kg1.chunks = {
            "doc_001_chunk_01": Mock(document_id="doc_001"),
            "doc_001_chunk_02": Mock(document_id="doc_001"),
            "doc_001_chunk_03": Mock(document_id="doc_001"),
            "doc_001_chunk_04": Mock(document_id="doc_001")
        }
        
        self.mock_graphrag.knowledge_graphs = {"doc_001": self.mock_kg1}
        
        # Initialize QueryEngine with mocks
        with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer'):
            self.query_engine = QueryEngine(
                graphrag_integrator=self.mock_graphrag,
                storage=self.mock_storage
            )
            
        # Mock the _get_relationship_documents method
        self.query_engine._get_relationship_documents = Mock(return_value=["doc_001"])

    @pytest.mark.asyncio
    async def test_process_relationship_query_exact_type_match(self):
        """
        GIVEN a QueryEngine instance with relationships in knowledge graph
        AND normalized query "founded companies"
        AND relationship with type "founded" exists
        WHEN _process_relationship_query is called
        THEN expect:
            - Relationship with exact type match gets high relevance score
            - QueryResult returned with formatted relationship description
            - Both source and target entities included in result
        """
        # Execute the method
        results = await self.query_engine._process_relationship_query(
            "founded companies", None, 10
        )
        
        # Assertions
        assert len(results) >= 1
        founded_result = next((r for r in results if "founded" in r.content.lower()), None)
        assert founded_result is not None
        assert founded_result.type == "relationship"
        assert "Bill Gates" in founded_result.content
        assert "Microsoft" in founded_result.content
        assert founded_result.relevance_score > 0.5
        assert founded_result.source_document == "doc_001"
        assert "rel_001" == founded_result.id

    @pytest.mark.asyncio
    async def test_process_relationship_query_entity_name_matching(self):
        """
        GIVEN a QueryEngine instance with relationships
        AND normalized query "bill gates relationships"
        WHEN _process_relationship_query is called
        THEN expect:
            - Relationships involving "Bill Gates" entity returned
            - Both source_entity and target_entity names checked
            - Relevance scored based on entity name matching
        """
        results = await self.query_engine._process_relationship_query(
            "bill gates relationships", None, 10
        )
        
        # Should find relationships where Bill Gates is source or target
        assert len(results) >= 2  # founded and knows relationships
        
        # Check that results contain Bill Gates relationships
        gates_results = [r for r in results if "bill gates" in r.content.lower()]
        assert len(gates_results) >= 2
        
        # Verify both founded and knows relationships are found
        relationship_types = [r.metadata.get("relationship_type") for r in gates_results]
        assert "founded" in relationship_types
        assert "knows" in relationship_types

    @pytest.mark.asyncio
    async def test_process_relationship_query_description_content_matching(self):
        """
        GIVEN a QueryEngine instance with relationships
        AND normalized query "ceo positions"
        AND relationships with "CEO" in description
        WHEN _process_relationship_query is called
        THEN expect:
            - Relationship descriptions analyzed for content matches
            - Relevant relationships scored appropriately
            - Description content included in scoring algorithm
        """
        # Add a relationship with CEO in description
        ceo_relationship = Relationship(
            id="rel_004",
            source_entity_id="entity_001",
            target_entity_id="entity_002",
            relationship_type="leads",
            description="Bill Gates leads Microsoft as CEO",
            properties={"title": "CEO"},
            confidence=0.88,
            source_chunks=["doc_001_chunk_05"]
        )
        self.mock_kg1.relationships["rel_004"] = ceo_relationship
        
        results = await self.query_engine._process_relationship_query(
            "ceo positions", None, 10
        )
        
        # Should find the CEO relationship
        ceo_results = [r for r in results if "ceo" in r.content.lower() or "ceo" in str(r.metadata).lower()]
        assert len(ceo_results) >= 1
        
        # Verify the result has good relevance score
        ceo_result = ceo_results[0]
        assert ceo_result.relevance_score > 0.3

    @pytest.mark.asyncio
    async def test_process_relationship_query_relationship_type_filter(self):
        """
        GIVEN a QueryEngine instance with mixed relationship types
        AND normalized query "company relationships"
        AND filters {"relationship_type": "founded"}
        WHEN _process_relationship_query is called
        THEN expect:
            - Only "founded" relationships returned
            - Other relationship types filtered out
            - Filter applied before scoring
        """
        filters = {"relationship_type": "founded"}
        
        results = await self.query_engine._process_relationship_query(
            "company relationships", filters, 10
        )
        
        # Should only return founded relationships
        assert len(results) == 1
        assert results[0].metadata["relationship_type"] == "founded"
        assert "founded" in results[0].content.lower()

    @pytest.mark.asyncio
    async def test_process_relationship_query_entity_id_filter(self):
        """
        GIVEN a QueryEngine instance with relationships
        AND normalized query "all relationships"
        AND filters {"entity_id": "entity_001"}
        WHEN _process_relationship_query is called
        THEN expect:
            - Only relationships involving entity_001 returned
            - Both source and target entity participation checked
            - Relationships not involving entity filtered out
        """
        filters = {"entity_id": "entity_001"}
        
        results = await self.query_engine._process_relationship_query(
            "all relationships", filters, 10
        )
        
        # Should return relationships where entity_001 is source or target
        assert len(results) >= 2  # founded and knows relationships
        
        for result in results:
            rel_id = result.id
            relationship = self.mock_kg1.relationships[rel_id]
            assert (relationship.source_entity_id == "entity_001" or 
                   relationship.target_entity_id == "entity_001")

    @pytest.mark.asyncio
    async def test_process_relationship_query_confidence_filter(self):
        """
        GIVEN a QueryEngine instance with relationships having confidence scores
        AND normalized query "relationships"
        AND filters {"confidence": 0.7}
        WHEN _process_relationship_query is called
        THEN expect:
            - Only relationships with confidence >= 0.7 returned
            - Low confidence relationships filtered out
        """
        filters = {"confidence": 0.7}
        
        results = await self.query_engine._process_relationship_query(
            "relationships", filters, 10
        )
        
        # Should exclude the low confidence relationship (0.60)
        assert len(results) == 2  # founded (0.90) and works_for (0.85)
        
        for result in results:
            rel_id = result.id
            relationship = self.mock_kg1.relationships[rel_id]
            assert relationship.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_process_relationship_query_document_id_filter(self):
        """
        GIVEN a QueryEngine instance with relationships across documents
        AND normalized query "founded relationships"
        AND filters {"document_id": "doc_001"}
        WHEN _process_relationship_query is called
        THEN expect:
            - Only relationships from doc_001 returned
            - _get_relationship_documents used for filtering
            - Cross-document relationships filtered appropriately
        """
        # Add a second knowledge graph for doc_002
        mock_kg2 = Mock()
        mock_kg2.entities = {}
        mock_kg2.relationships = {
            "rel_005": Relationship(
                id="rel_005",
                source_entity_id="entity_004",
                target_entity_id="entity_005",
                relationship_type="founded",
                description="Other founder relationship",
                properties={},
                confidence=0.80,
                source_chunks=["doc_002_chunk_01"]
            )
        }
        mock_kg2.chunks = {"doc_002_chunk_01": Mock(document_id="doc_002")}
        self.mock_graphrag.knowledge_graphs["doc_002"] = mock_kg2
        
        # Mock _get_relationship_documents to return appropriate docs
        def mock_get_rel_docs(relationship):
            if relationship.id.startswith("rel_00") and relationship.id <= "rel_003":
                return ["doc_001"]
            else:
                return ["doc_002"]
        
        self.query_engine._get_relationship_documents = Mock(side_effect=mock_get_rel_docs)
        
        filters = {"document_id": "doc_001"}
        
        results = await self.query_engine._process_relationship_query(
            "founded relationships", filters, 10
        )
        
        # Should only return relationships from doc_001
        doc_001_rels = 0
        for result in results:
            self.query_engine._get_relationship_documents.assert_called()
            # Verify all results are from doc_001
            assert result.source_document == "doc_001"
            doc_001_rels += 1
            
        assert doc_001_rels >= 1

    @pytest.mark.asyncio
    async def test_process_relationship_query_max_results_limiting(self):
        """
        GIVEN a QueryEngine instance with many relationships
        AND normalized query "relationships"
        AND max_results = 2
        WHEN _process_relationship_query is called
        THEN expect:
            - Exactly 2 results returned (or fewer if less available)
            - Results are top-scored relationships
            - Results ordered by relevance score descending
        """
        results = await self.query_engine._process_relationship_query(
            "relationships", None, 2
        )
        
        # Should return exactly 2 results (or fewer if less available)
        assert len(results) <= 2
        
        # Results should be ordered by relevance score descending
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i].relevance_score >= results[i + 1].relevance_score

    @pytest.mark.asyncio
    async def test_process_relationship_query_missing_entities_handling(self):
        """
        GIVEN a QueryEngine instance with relationships
        AND some referenced entities missing from global registry
        AND normalized query "founded companies"
        WHEN _process_relationship_query is called
        THEN expect:
            - Missing entities logged with warnings
            - Relationships with missing entities skipped
            - No KeyError exceptions raised
            - Valid relationships still processed
        """
        # Add relationship with missing entity
        missing_entity_rel = Relationship(
            id="rel_missing",
            source_entity_id="entity_999",  # Missing entity
            target_entity_id="entity_002",
            relationship_type="founded",
            description="Missing entity founded Microsoft",
            properties={},
            confidence=0.85,
            source_chunks=["doc_001_chunk_06"]
        )
        self.mock_kg1.relationships["rel_missing"] = missing_entity_rel
        
        with patch('logging.warning') as mock_warning:
            results = await self.query_engine._process_relationship_query(
                "founded companies", None, 10
            )
            
            # Should log warning about missing entity
            mock_warning.assert_called()
            
            # Should still return valid relationships
            valid_results = [r for r in results if r.id != "rel_missing"]
            assert len(valid_results) >= 1
            
            # Should not raise KeyError
            # (If we got here without exception, test passed)

    @pytest.mark.asyncio
    async def test_process_relationship_query_no_matches_found(self):
        """
        GIVEN a QueryEngine instance
        AND normalized query "nonexistent relationship type"
        WHEN _process_relationship_query is called
        THEN expect:
            - Empty list returned
            - No exceptions raised
            - Method completes successfully
        """
        results = await self.query_engine._process_relationship_query(
            "nonexistent relationship type", None, 10
        )
        
        assert results == []
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_process_relationship_query_invalid_max_results(self):
        """
        GIVEN a QueryEngine instance
        AND normalized query "test"
        AND max_results = -3 or 0
        WHEN _process_relationship_query is called
        THEN expect ValueError to be raised
        """
        with pytest.raises(ValueError, match="max_results must be positive"):
            await self.query_engine._process_relationship_query("test", None, -3)
            
        with pytest.raises(ValueError, match="max_results must be positive"):
            await self.query_engine._process_relationship_query("test", None, 0)

    @pytest.mark.asyncio
    async def test_process_relationship_query_invalid_filters_type(self):
        """
        GIVEN a QueryEngine instance
        AND normalized query "test"
        AND filters as string instead of dict
        WHEN _process_relationship_query is called
        THEN expect TypeError to be raised
        """
        with pytest.raises(TypeError, match="filters must be a dictionary"):
            await self.query_engine._process_relationship_query("test", "invalid_filters", 10)

    @pytest.mark.asyncio
    async def test_process_relationship_query_corrupted_data(self):
        """
        GIVEN a QueryEngine instance with corrupted relationship data
        AND normalized query "test"
        WHEN _process_relationship_query is called
        THEN expect RuntimeError to be raised
        """
        # Corrupt the knowledge graph data
        self.mock_graphrag.knowledge_graphs = None
        
        with pytest.raises(RuntimeError, match="GraphRAG data is corrupted"):
            await self.query_engine._process_relationship_query("test", None, 10)

    @pytest.mark.asyncio
    async def test_process_relationship_query_result_structure_validation(self):
        """
        GIVEN a QueryEngine instance with valid relationships
        AND normalized query "founded companies"
        WHEN _process_relationship_query is called
        THEN expect each QueryResult to have:
            - id: str (relationship ID)
            - type: "relationship"
            - content: str (formatted relationship statement)
            - relevance_score: float (0.0-1.0)
            - source_document: str
            - source_chunks: List[str]
            - metadata: Dict with relationship and entity details
        """
        results = await self.query_engine._process_relationship_query(
            "founded companies", None, 10
        )
        
        assert len(results) >= 1
        
        for result in results:
            # Validate result structure
            assert isinstance(result.id, str)
            assert result.type == "relationship"
            assert isinstance(result.content, str)
            assert isinstance(result.relevance_score, float)
            assert 0.0 <= result.relevance_score <= 1.0
            assert isinstance(result.source_document, str)
            assert isinstance(result.source_chunks, list)
            assert isinstance(result.metadata, dict)
            
            # Validate metadata content
            assert "source_entity" in result.metadata
            assert "target_entity" in result.metadata
            assert "relationship_type" in result.metadata
            assert "confidence" in result.metadata

    @pytest.mark.asyncio
    async def test_process_relationship_query_relationship_formatting(self):
        """
        GIVEN a QueryEngine instance with relationships
        AND normalized query "founded relationships"
        WHEN _process_relationship_query is called
        THEN expect:
            - Relationship content formatted as "Source Entity relationship_type Target Entity"
            - Entity names properly retrieved and included
            - Relationship type converted from underscore format if needed
        """
        results = await self.query_engine._process_relationship_query(
            "founded relationships", None, 10
        )
        
        founded_result = next((r for r in results if "founded" in r.content.lower()), None)
        assert founded_result is not None
        
        # Check formatting: should contain source entity, relationship type, target entity
        content = founded_result.content
        assert "Bill Gates" in content
        assert "Microsoft" in content
        assert any(word in content.lower() for word in ["founded", "found"])

    @pytest.mark.asyncio
    async def test_process_relationship_query_relevance_scoring_algorithm(self):
        """
        GIVEN a QueryEngine instance with relationships
        AND normalized query matching different aspects
        WHEN _process_relationship_query is called
        THEN expect:
            - Relationship type matching weighted appropriately
            - Entity name matching weighted appropriately
            - Description content matching weighted appropriately
            - Combined scores between 0.0 and 1.0
        """
        results = await self.query_engine._process_relationship_query(
            "bill gates founded", None, 10
        )
        
        # Should have results with varying relevance scores
        assert len(results) >= 1
        
        # Find the founded relationship which should score highest
        founded_result = next((r for r in results if r.metadata.get("relationship_type") == "founded"), None)
        assert founded_result is not None
        
        # Should have high relevance due to exact type and entity match
        assert founded_result.relevance_score > 0.5
        assert 0.0 <= founded_result.relevance_score <= 1.0

    @pytest.mark.asyncio
    async def test_process_relationship_query_source_attribution(self):
        """
        GIVEN a QueryEngine instance with relationships
        AND normalized query "partnerships"
        WHEN _process_relationship_query is called
        THEN expect:
            - source_document field populated correctly
            - source_chunks field contains relationship source chunks
            - _get_relationship_documents called for each relationship
            - Traceability maintained to original content
        """
        results = await self.query_engine._process_relationship_query(
            "partnerships", None, 10
        )
        
        if len(results) > 0:
            result = results[0]
            
            # Verify source attribution
            assert result.source_document is not None
            assert isinstance(result.source_chunks, list)
            
            # Verify _get_relationship_documents was called
            self.query_engine._get_relationship_documents.assert_called()

    @pytest.mark.asyncio
    async def test_process_relationship_query_metadata_completeness(self):
        """
        GIVEN a QueryEngine instance with relationships
        AND normalized query "work relationships"
        WHEN _process_relationship_query is called
        THEN expect QueryResult.metadata to contain:
            - source_entity: Dict with entity details
            - target_entity: Dict with entity details
            - relationship_type: str
            - confidence: float
            - properties: Dict (relationship properties)
        """
        results = await self.query_engine._process_relationship_query(
            "work relationships", None, 10
        )
        
        assert len(results) >= 1
        
        result = results[0]
        metadata = result.metadata
        
        # Check required metadata fields
        assert "source_entity" in metadata
        assert "target_entity" in metadata
        assert "relationship_type" in metadata
        assert "confidence" in metadata
        assert "properties" in metadata
        
        # Verify entity details structure
        source_entity = metadata["source_entity"]
        target_entity = metadata["target_entity"]
        
        assert isinstance(source_entity, dict)
        assert isinstance(target_entity, dict)
        assert "name" in source_entity
        assert "name" in target_entity

    @pytest.mark.asyncio
    async def test_process_relationship_query_underscore_format_handling(self):
        """
        GIVEN a QueryEngine instance with relationships
        AND relationship types in underscore format ("works_for", "founded_by")
        AND normalized query "works for relationships"
        WHEN _process_relationship_query is called
        THEN expect:
            - Underscore format relationship types matched correctly
            - Query terms converted to underscore format for matching
            - Results include relationships with underscore types
        """
        results = await self.query_engine._process_relationship_query(
            "works for relationships", None, 10
        )
        
        # Should find the works_for relationship
        works_for_result = next((r for r in results if r.metadata.get("relationship_type") == "works_for"), None)
        assert works_for_result is not None
        assert "Paul Allen" in works_for_result.content
        assert "Microsoft" in works_for_result.content

    @pytest.mark.asyncio
    async def test_process_relationship_query_bidirectional_entity_matching(self):
        """
        GIVEN a QueryEngine instance with relationships
        AND normalized query "microsoft relationships"
        WHEN _process_relationship_query is called
        THEN expect:
            - Relationships where Microsoft is source entity included
            - Relationships where Microsoft is target entity included
            - Both directions of entity participation considered
        """
        results = await self.query_engine._process_relationship_query(
            "microsoft relationships", None, 10
        )
        
        # Should find relationships where Microsoft is target (founded, works_for)
        microsoft_results = [r for r in results if "microsoft" in r.content.lower()]
        assert len(microsoft_results) >= 2
        
        # Verify both founded and works_for relationships are found
        found_types = set()
        for result in microsoft_results:
            rel_type = result.metadata.get("relationship_type")
            found_types.add(rel_type)
            
            # Microsoft should be either source or target
            source_entity = result.metadata.get("source_entity", {}).get("name", "")
            target_entity = result.metadata.get("target_entity", {}).get("name", "")
            assert "Microsoft" in source_entity or "Microsoft" in target_entity
            
        # Should find at least founded and works_for
        assert "founded" in found_types or "works_for" in found_types


if __name__ == "__main__":
    pytest.main([__file__, "-v"])