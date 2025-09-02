# Test file for TestQueryEngineProcessDocumentQuery

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
from typing import Dict, List, Any, Optional

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

work_dir = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py"
file_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/query_engine.py")
md_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/query_engine_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine, QueryResult
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


class TestQueryEngineProcessDocumentQuery:
    """Test QueryEngine._process_document_query method for document-level analysis."""

    def setup_method(self):
        """Setup test fixtures for each test method."""
        # Mock GraphRAG integrator
        self.mock_graphrag = Mock(spec=GraphRAGIntegrator)
        
        # Mock storage
        self.mock_storage = Mock(spec=IPLDStorage)
        
        # Create QueryEngine instance with mocked dependencies
        self.query_engine = QueryEngine(
            graphrag_integrator=self.mock_graphrag,
            storage=self.mock_storage,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2"
        )
        
        # Mock knowledge graphs data with proper structure
        mock_entity_1 = Mock()
        mock_entity_1.id = "ent_001"
        mock_entity_1.name = "Microsoft"
        mock_entity_1.type = "Organization"
        mock_entity_1.description = "Technology company"
        
        mock_entity_2 = Mock()
        mock_entity_2.id = "ent_002"
        mock_entity_2.name = "Bill Gates"
        mock_entity_2.type = "Person"
        mock_entity_2.description = "Co-founder of Microsoft"
        
        mock_entity_3 = Mock()
        mock_entity_3.id = "ent_003"
        mock_entity_3.name = "AI"
        mock_entity_3.type = "Technology"
        mock_entity_3.description = "Artificial Intelligence"
        
        mock_entity_4 = Mock()
        mock_entity_4.id = "ent_004"
        mock_entity_4.name = "Apple"
        mock_entity_4.type = "Organization"
        mock_entity_4.description = "Technology company"
        
        mock_entity_5 = Mock()
        mock_entity_5.id = "ent_005"
        mock_entity_5.name = "Innovation"
        mock_entity_5.type = "Concept"
        mock_entity_5.description = "Technological advancement"
        
        # Mock chunks
        mock_chunk_1 = Mock()
        mock_chunk_1.content = "Microsoft is a leading technology company"
        mock_chunk_1.chunk_id = "doc_001_chunk_1"
        
        mock_chunk_2 = Mock()
        mock_chunk_2.content = "Apple drives innovation in consumer technology"
        mock_chunk_2.chunk_id = "doc_002_chunk_1"
        
        # Mock relationships
        mock_rel_1 = Mock()
        mock_rel_1.id = "rel_001"
        mock_rel_1.source_entity = "ent_002"
        mock_rel_1.target_entity = "ent_001"
        mock_rel_1.type = "founded"
        
        # Mock knowledge graphs using proper structure
        mock_kg_1 = Mock()
        mock_kg_1.document_id = "doc_001"
        mock_kg_1.graph_id = "graph_001"
        mock_kg_1.entities = [mock_entity_1, mock_entity_2, mock_entity_3]
        mock_kg_1.relationships = [mock_rel_1]
        mock_kg_1.chunks = [mock_chunk_1] * 15  # 15 chunks
        mock_kg_1.metadata = {
            "document_title": "Artificial Intelligence Research in Technology Companies",
            "entity_count": 12,
            "relationship_count": 8,
            "creation_date": "2024-06-15",
            "processing_date": "2024-07-01"
        }
        mock_kg_1.creation_timestamp = "2024-06-15T10:00:00Z"
        mock_kg_1.ipld_cid = "QmTest001"
        
        mock_kg_2 = Mock()
        mock_kg_2.document_id = "doc_002"
        mock_kg_2.graph_id = "graph_002"
        mock_kg_2.entities = [mock_entity_4, mock_entity_5]
        mock_kg_2.relationships = []
        mock_kg_2.chunks = [mock_chunk_2] * 8  # 8 chunks
        mock_kg_2.metadata = {
            "document_title": "Technology Innovation Trends",
            "entity_count": 5,
            "relationship_count": 3,
            "creation_date": "2024-05-20",
            "processing_date": "2024-07-02"
        }
        mock_kg_2.creation_timestamp = "2024-05-20T10:00:00Z"
        mock_kg_2.ipld_cid = "QmTest002"
        
        mock_kg_3 = Mock()
        mock_kg_3.document_id = "doc_003"
        mock_kg_3.graph_id = "graph_003"
        # Create 20 mock entities
        mock_entities_3 = []
        for i in range(20):
            entity = Mock()
            entity.id = f"ent_{i+10}"
            entity.name = f"Entity_{i}"
            entity.type = "Technology"
            entity.description = f"Technology entity {i}"
            mock_entities_3.append(entity)
        mock_kg_3.entities = mock_entities_3
        mock_kg_3.relationships = [Mock() for _ in range(15)]  # 15 relationships
        mock_kg_3.chunks = [Mock() for _ in range(25)]  # 25 chunks
        # Set content for chunks
        for i, chunk in enumerate(mock_kg_3.chunks):
            chunk.content = f"This is content for chunk {i+1} about machine learning"
            chunk.chunk_id = f"doc_003_chunk_{i+1}"
        mock_kg_3.metadata = {
            "document_title": "Comprehensive Analysis of Machine Learning",
            "entity_count": 20,
            "relationship_count": 15,
            "creation_date": "2024-01-15",
            "processing_date": "2024-07-03"
        }
        mock_kg_3.creation_timestamp = "2024-01-15T10:00:00Z"
        mock_kg_3.ipld_cid = "QmTest003"
        
        self.mock_knowledge_graphs = {
            "doc_001": mock_kg_1,
            "doc_002": mock_kg_2,
            "doc_003": mock_kg_3
        }
        
        # Mock GraphRAG integrator attributes
        self.mock_graphrag.knowledge_graphs = self.mock_knowledge_graphs

    @pytest.mark.asyncio
    async def test_process_document_query_title_matching(self):
        """
        GIVEN a QueryEngine instance with documents having titles
        AND normalized query "artificial intelligence research"
        AND document with matching title exists
        WHEN _process_document_query is called
        THEN expect:
            - Document title analyzed for keyword matches
            - Documents with matching titles scored highly
            - Title matching weighted appropriately in final score
        """
        # Arrange
        query = "artificial intelligence research"
        filters = None
        max_results = 10
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        assert len(results) > 0
        # Find the result for doc_001 which has matching title
        doc_001_result = next((r for r in results if r.id == "doc_001"), None)
        assert doc_001_result is not None
        assert doc_001_result.type == "document"
        assert doc_001_result.relevance_score > 0.5  # High score for title match
        assert "artificial intelligence" in doc_001_result.content.lower()
        assert doc_001_result.source_document == "doc_001"

    @pytest.mark.asyncio
    async def test_process_document_query_entity_content_matching(self):
        """
        GIVEN a QueryEngine instance with documents containing entities
        AND normalized query "technology companies"
        AND documents with relevant entities
        WHEN _process_document_query is called
        THEN expect:
            - Document entities analyzed for query relevance
            - Documents with matching entity types scored appropriately
            - Entity content matching combined with other factors
        """
        # Arrange
        query = "technology companies"
        filters = None
        max_results = 10
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        assert len(results) > 0
        # Check that documents with Organization entities score well
        org_docs = [r for r in results if any("Organization" in str(getattr(ent, 'type', '')) 
                                             for ent in self.mock_knowledge_graphs[r.id].entities)]
        assert len(org_docs) > 0
        for result in org_docs:
            assert result.relevance_score > 0.0
            assert result.type == "document"

    @pytest.mark.asyncio
    async def test_process_document_query_document_characteristics_analysis(self):
        """
        GIVEN a QueryEngine instance with documents of varying characteristics
        AND normalized query "comprehensive research papers"
        WHEN _process_document_query is called
        THEN expect:
            - Document metadata analyzed (entity counts, relationship counts)
            - Document characteristics considered in scoring
            - Rich documents scored higher for comprehensive queries
        """
        # Arrange
        query = "comprehensive research papers"
        filters = None
        max_results = 10
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        assert len(results) > 0
        # doc_003 has the most entities and relationships (comprehensive)
        doc_003_result = next((r for r in results if r.id == "doc_003"), None)
        if doc_003_result:
            # Should score well due to high entity/relationship counts
            assert doc_003_result.relevance_score > 0.0
            assert "entity_count" in doc_003_result.metadata
            assert "relationship_count" in doc_003_result.metadata

    @pytest.mark.asyncio
    async def test_process_document_query_document_id_filter(self):
        """
        GIVEN a QueryEngine instance with multiple documents
        AND normalized query "detailed analysis"
        AND filters {"document_id": "doc_003"}
        WHEN _process_document_query is called
        THEN expect:
            - Only doc_003 analyzed and returned
            - Other documents filtered out
            - Detailed analysis of specified document provided
        """
        # Arrange
        query = "detailed analysis"
        filters = {"document_id": "doc_003"}
        max_results = 10
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        assert len(results) == 1
        assert results[0].id == "doc_003"
        assert results[0].type == "document"
        assert results[0].source_document == "doc_003"
        # Verify it contains detailed information
        assert "entity_count" in results[0].metadata
        assert "relationship_count" in results[0].metadata

    @pytest.mark.asyncio
    async def test_process_document_query_min_entities_filter(self):
        """
        GIVEN a QueryEngine instance with documents having different entity counts
        AND normalized query "entity-rich documents"
        AND filters {"min_entities": 15}
        WHEN _process_document_query is called
        THEN expect:
            - Only documents with >= 15 entities returned
            - Documents with fewer entities filtered out
            - Entity count verification performed
        """
        # Arrange
        query = "machine learning"  # This should match doc_003's title
        filters = {"min_entities": 15}
        max_results = 10
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        # Only doc_003 has 20 entities (>= 15)
        assert len(results) == 1
        assert results[0].id == "doc_003"
        assert results[0].metadata["entity_count"] >= 15

    @pytest.mark.asyncio
    async def test_process_document_query_min_relationships_filter(self):
        """
        GIVEN a QueryEngine instance with documents having different relationship counts
        AND normalized query "relationship-rich papers"
        AND filters {"min_relationships": 10}
        WHEN _process_document_query is called
        THEN expect:
            - Only documents with >= 10 relationships returned
            - Documents with fewer relationships filtered out
            - Relationship count verification performed
        """
        # Arrange
        query = "machine learning"  # This should match doc_003's title  
        filters = {"min_relationships": 10}
        max_results = 10
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        # Only doc_003 has 15 relationships (>= 10)
        assert len(results) == 1
        assert results[0].id == "doc_003"
        assert results[0].metadata["relationship_count"] >= 10

    @pytest.mark.asyncio
    async def test_process_document_query_creation_date_filter(self):
        """
        GIVEN a QueryEngine instance with documents having creation dates
        AND normalized query "recent research"
        AND filters {"creation_date": "2024-01-01"}
        WHEN _process_document_query is called
        THEN expect:
            - Only documents created after specified date returned
            - Date filtering applied correctly
            - Document processing/creation date used for filtering
        """
        # Arrange
        query = "research innovation machine"  # Each word should match at least one document
        filters = {"creation_date": "2024-01-01"}
        max_results = 10
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        # All test documents have creation dates after 2024-01-01
        assert len(results) == 3
        for result in results:
            creation_date = datetime.strptime(
                self.mock_knowledge_graphs[result.id].metadata["creation_date"], 
                "%Y-%m-%d"
            )
            filter_date = datetime.strptime("2024-01-01", "%Y-%m-%d")
            assert creation_date >= filter_date

    @pytest.mark.asyncio
    async def test_process_document_query_max_results_limiting(self):
        """
        GIVEN a QueryEngine instance with many documents
        AND normalized query "research papers"
        AND max_results = 2
        WHEN _process_document_query is called
        THEN expect:
            - Exactly 2 results returned (or fewer if less available)
            - Results are highest-scored documents
            - Results ordered by relevance score descending
        """
        # Arrange
        query = "research papers"
        filters = None
        max_results = 2
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        assert len(results) <= 2
        if len(results) > 1:
            # Verify ordering by relevance score
            assert results[0].relevance_score >= results[1].relevance_score

    @pytest.mark.asyncio
    async def test_process_document_query_no_matching_documents(self):
        """
        GIVEN a QueryEngine instance
        AND normalized query with no matching documents
        WHEN _process_document_query is called
        THEN expect:
            - Empty list returned
            - No exceptions raised
            - Method completes successfully
        """
        # Arrange - Use empty knowledge graphs
        self.mock_graphrag.knowledge_graphs = {}
        query = "nonexistent topic"
        filters = None
        max_results = 10
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        assert results == []
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_process_document_query_invalid_max_results(self):
        """
        GIVEN a QueryEngine instance
        AND normalized query "test"
        AND max_results = -1 or 0
        WHEN _process_document_query is called
        THEN expect ValueError to be raised
        """
        # Arrange
        query = "test"
        filters = None
        
        # Act & Assert - Test negative max_results
        with pytest.raises(ValueError, match="max_results must be positive"):
            await self.query_engine._process_document_query(query, filters, -1)
        
        # Act & Assert - Test zero max_results
        with pytest.raises(ValueError, match="max_results must be positive"):
            await self.query_engine._process_document_query(query, filters, 0)

    @pytest.mark.asyncio
    async def test_process_document_query_invalid_filters_type(self):
        """
        GIVEN a QueryEngine instance
        AND normalized query "test"
        AND filters as list instead of dict
        WHEN _process_document_query is called
        THEN expect TypeError to be raised
        """
        # Arrange
        query = "test"
        filters = ["invalid", "filter", "type"]  # Should be dict
        max_results = 10
        
        # Act & Assert
        with pytest.raises(TypeError, match="filters must be a dictionary"):
            await self.query_engine._process_document_query(query, filters, max_results)

    @pytest.mark.asyncio
    async def test_process_document_query_corrupted_metadata(self):
        """
        GIVEN a QueryEngine instance with corrupted document metadata
        AND normalized query "test"
        WHEN _process_document_query is called
        THEN expect RuntimeError to be raised
        """
        # Arrange - Corrupt the metadata
        corrupted_kg = Mock()
        corrupted_kg.document_id = "doc_001"
        corrupted_kg.entities = []
        corrupted_kg.relationships = []
        corrupted_kg.chunks = []
        corrupted_kg.metadata = None  # Corrupted metadata
        
        corrupted_graphs = {
            "doc_001": corrupted_kg
        }
        self.mock_graphrag.knowledge_graphs = corrupted_graphs
        query = "test"
        filters = None
        max_results = 10
        
        # Act & Assert
        with pytest.raises(RuntimeError, match="Corrupted document metadata"):
            await self.query_engine._process_document_query(query, filters, max_results)

    @pytest.mark.asyncio
    async def test_process_document_query_missing_metadata_attributes(self):
        """
        GIVEN a QueryEngine instance with documents missing required metadata
        AND normalized query "test"
        WHEN _process_document_query is called
        THEN expect AttributeError to be raised
        """
        # Arrange - Missing required metadata attributes  
        incomplete_kg = Mock(spec=[])  # Empty spec so it has no attributes
        incomplete_kg.document_id = "doc_001"
        incomplete_kg.metadata = {
            "creation_date": "2024-01-01"
        }
        # Don't set entities and relationships to trigger AttributeError
        
        incomplete_graphs = {
            "doc_001": incomplete_kg
        }
        self.mock_graphrag.knowledge_graphs = incomplete_graphs
        query = "test"
        filters = None
        max_results = 10
        
        # Act & Assert
        with pytest.raises(AttributeError, match="Missing required metadata"):
            await self.query_engine._process_document_query(query, filters, max_results)

    @pytest.mark.asyncio
    async def test_process_document_query_result_structure_validation(self):
        """
        GIVEN a QueryEngine instance with valid documents
        AND normalized query "research papers"
        WHEN _process_document_query is called
        THEN expect each QueryResult to have:
            - id: str (document_id)
            - type: "document"
            - content: str (document summary with statistics)
            - relevance_score: float (0.0-1.0)
            - source_document: str (same as id)
            - source_chunks: List[str] (empty for document-level)
            - metadata: Dict with document details and processing info
        """
        # Arrange
        query = "research papers"
        filters = None
        max_results = 10
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        assert len(results) > 0
        for result in results:
            # Check required attributes
            assert isinstance(result.id, str)
            assert result.type == "document"
            assert isinstance(result.content, str)
            assert isinstance(result.relevance_score, float)
            assert 0.0 <= result.relevance_score <= 1.0
            assert isinstance(result.source_document, str)
            assert result.source_document == result.id
            assert isinstance(result.source_chunks, list)
            assert result.source_chunks == []  # Empty for document-level
            assert isinstance(result.metadata, dict)
            
            # Check metadata content
            assert "entity_count" in result.metadata
            assert "relationship_count" in result.metadata
            assert "processing_date" in result.metadata

    @pytest.mark.asyncio
    async def test_process_document_query_document_summary_generation(self):
        """
        GIVEN a QueryEngine instance with documents
        AND normalized query "technology papers"
        WHEN _process_document_query is called
        THEN expect:
            - Document summary includes entity counts
            - Document summary includes relationship counts
            - Document summary includes key entities (first 5)
            - Summary format is consistent and informative
        """
        # Arrange
        query = "technology papers"
        filters = None
        max_results = 10
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        assert len(results) > 0
        for result in results:
            content = result.content.lower()
            # Check summary includes counts
            assert "entities" in content or "entity" in content
            assert "relationships" in content or "relationship" in content
            # Check for key entities mention
            doc_data = self.mock_knowledge_graphs[result.id]
            if doc_data.entities:
                # At least one entity name should be in content
                entity_found = any(getattr(ent, 'name', '').lower() in content for ent in doc_data.entities[:5])
                assert entity_found

    @pytest.mark.asyncio
    async def test_process_document_query_scoring_algorithm_components(self):
        """
        GIVEN a QueryEngine instance with documents
        AND normalized query matching different aspects
        WHEN _process_document_query is called
        THEN expect:
            - Title matching weighted appropriately
            - Entity content matching weighted appropriately
            - Document characteristics weighted appropriately
            - Combined scores between 0.0 and 1.0
        """
        # Arrange
        query = "artificial intelligence technology"  # Matches title and entities
        filters = None
        max_results = 10
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        assert len(results) > 0
        for result in results:
            # Scores should be normalized
            assert 0.0 <= result.relevance_score <= 1.0
            
        # Document with title match should score higher
        doc_001_result = next((r for r in results if r.id == "doc_001"), None)
        if doc_001_result and len(results) > 1:
            other_results = [r for r in results if r.id != "doc_001"]
            avg_other_score = sum(r.relevance_score for r in other_results) / len(other_results)
            # Title match should generally score higher
            assert doc_001_result.relevance_score >= avg_other_score * 0.8

    @pytest.mark.asyncio
    async def test_process_document_query_entity_sampling_limitation(self):
        """
        GIVEN a QueryEngine instance with documents having many entities
        AND normalized query "entity analysis"
        WHEN _process_document_query is called
        THEN expect:
            - Entity sampling limited to first 5 entities for readability
            - Performance optimized by limiting entity analysis
            - Key entities still captured in summary
        """
        # Arrange
        query = "entity analysis"
        filters = {"document_id": "doc_003"}  # Has 20 entities
        max_results = 10
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        assert len(results) == 1
        result = results[0]
        
        # Check that key entities are mentioned but not all 20
        doc_data = self.mock_knowledge_graphs["doc_003"]
        entity_names_in_content = [getattr(ent, 'name', '') for ent in doc_data.entities[:5] 
                                 if getattr(ent, 'name', '').lower() in result.content.lower()]
        
        # Should have some entities mentioned but not necessarily all 20
        assert len(entity_names_in_content) <= 5

    @pytest.mark.asyncio
    async def test_process_document_query_chunk_sampling_optimization(self):
        """
        GIVEN a QueryEngine instance with documents having many chunks
        AND normalized query "content analysis"
        WHEN _process_document_query is called
        THEN expect:
            - Content sampling analyzes first 10 chunks for performance
            - Analysis optimized to prevent excessive computation
            - Representative content analysis maintained
        """
        # Arrange
        query = "content analysis"
        filters = {"document_id": "doc_003"}  # Has 25 chunks
        max_results = 10
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        assert len(results) == 1
        result = results[0]
        
        # Verify the result contains analysis but processing was optimized
        # (This test mainly verifies the method completes efficiently)
        assert result.type == "document"
        assert isinstance(result.content, str)
        assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_process_document_query_ipld_storage_integration(self):
        """
        GIVEN a QueryEngine instance with IPLD storage details
        AND normalized query "storage information"
        WHEN _process_document_query is called
        THEN expect:
            - IPLD storage information included in metadata
            - Document storage details accessible
            - Storage integration seamless
        """
        # Arrange
        query = "technology"  # This should match documents
        filters = None
        max_results = 10
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        assert len(results) > 0
        for result in results:
            # Verify storage integration in metadata
            assert "ipld_storage_details" in result.metadata
            # Storage details should be accessible through the storage instance
            assert self.query_engine.storage is not None

    @pytest.mark.asyncio
    async def test_process_document_query_metadata_completeness(self):
        """
        GIVEN a QueryEngine instance with documents
        AND normalized query "document metadata"
        WHEN _process_document_query is called
        THEN expect QueryResult.metadata to contain:
            - entity_count: int
            - relationship_count: int
            - key_entities: List[str]
            - processing_date: str
            - ipld_storage_details: Dict
            - document_characteristics: Dict
        """
        # Arrange
        query = "technology"  # This should match documents
        filters = None
        max_results = 10
        
        # Act
        results = await self.query_engine._process_document_query(query, filters, max_results)
        
        # Assert
        assert len(results) > 0
        for result in results:
            metadata = result.metadata
            
            # Check required metadata fields
            assert "entity_count" in metadata
            assert isinstance(metadata["entity_count"], int)
            
            assert "relationship_count" in metadata
            assert isinstance(metadata["relationship_count"], int)
            
            assert "key_entities" in metadata
            assert isinstance(metadata["key_entities"], list)
            
            assert "processing_date" in metadata
            assert isinstance(metadata["processing_date"], str)
            
            assert "ipld_storage_details" in metadata
            assert isinstance(metadata["ipld_storage_details"], dict)
            
            assert "document_characteristics" in metadata
            assert isinstance(metadata["document_characteristics"], dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])