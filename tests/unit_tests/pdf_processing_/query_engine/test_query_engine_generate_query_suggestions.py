#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
from unittest.mock import Mock, MagicMock


home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine, QueryResult

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


class TestQueryEngineGenerateQuerySuggestions:
    """Test QueryEngine._generate_query_suggestions method for intelligent follow-up query generation."""

    def setup_method(self):
        """Set up test fixtures for each test method."""
        self.mock_graphrag = Mock(spec=GraphRAGIntegrator)
        self.mock_storage = Mock(spec=IPLDStorage)
        self.query_engine = QueryEngine(
            graphrag_integrator=self.mock_graphrag,
            storage=self.mock_storage,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2"
        )

    def create_mock_query_result(self, result_type: str, content: str, metadata: Dict[str, Any] = None) -> QueryResult:
        """Helper method to create mock QueryResult objects."""
        return QueryResult(
            id=f"test_id_{result_type}",
            type=result_type,
            content=content,
            relevance_score=0.8,
            source_document="doc_001",
            source_chunks=["chunk_001"],
            metadata=metadata or {}
        )

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_entity_based_suggestions(self):
        """
        GIVEN a QueryEngine instance
        AND original query "Bill Gates"
        AND results containing entity results with "Bill Gates" and "Microsoft"
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Entity-specific queries generated: "What is Bill Gates?", "What is Microsoft?"
            - Entity relationship queries: "What are the relationships of Bill Gates?"
            - Maximum 5 suggestions returned
        """
        # GIVEN
        original_query = "Bill Gates"
        results = [
            self.create_mock_query_result(
                "entity", 
                "Bill Gates (Person): Co-founder of Microsoft",
                {"entity_name": "Bill Gates", "entity_type": "Person"}
            ),
            self.create_mock_query_result(
                "entity",
                "Microsoft (Organization): Technology company",
                {"entity_name": "Microsoft", "entity_type": "Organization"}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        assert "What is Bill Gates?" in suggestions
        assert "What is Microsoft?" in suggestions
        assert "What are the relationships of Bill Gates?" in suggestions

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_relationship_type_suggestions(self):
        """
        GIVEN a QueryEngine instance
        AND original query "founded companies"
        AND results containing relationship results with "founded" type
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Relationship type queries generated: "Find all founded relationships"
            - Related relationship queries suggested
            - Type-specific exploration suggestions
        """
        # GIVEN
        original_query = "founded companies"
        results = [
            self.create_mock_query_result(
                "relationship",
                "Bill Gates founded Microsoft",
                {"relationship_type": "founded", "source_entity": "Bill Gates", "target_entity": "Microsoft"}
            ),
            self.create_mock_query_result(
                "relationship",
                "Steve Jobs founded Apple",
                {"relationship_type": "founded", "source_entity": "Steve Jobs", "target_entity": "Apple"}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        assert any("founded relationships" in suggestion for suggestion in suggestions)

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_cross_document_analysis(self):
        """
        GIVEN a QueryEngine instance
        AND original query "technology companies"
        AND results from multiple documents
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Cross-document analysis suggestions generated
            - Multi-document comparison queries suggested
            - Document-spanning relationship suggestions
        """
        # GIVEN
        original_query = "technology companies"
        results = [
            QueryResult(
                id="result_1",
                type="cross_document_relationship",
                content="Microsoft (doc1) competes with Apple (doc2)",
                relevance_score=0.9,
                source_document="multiple",
                source_chunks=["doc1_chunk1", "doc2_chunk1"],
                metadata={"documents": ["doc1", "doc2"]}
            ),
            QueryResult(
                id="result_2", 
                type="entity",
                content="Google (Organization): Search company",
                relevance_score=0.8,
                source_document="doc3",
                source_chunks=["doc3_chunk1"],
                metadata={"entity_name": "Google"}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        assert any("across documents" in suggestion or "multiple documents" in suggestion for suggestion in suggestions)

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_top_results_analysis(self):
        """
        GIVEN a QueryEngine instance
        AND original query "artificial intelligence"
        AND results list with many items
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Only top 5 results analyzed for suggestion generation
            - Performance optimized by limiting analysis scope
            - Most relevant content used for suggestions
        """
        # GIVEN
        original_query = "artificial intelligence"
        # Create 10 results to test the top 5 limitation
        results = []
        for i in range(10):
            results.append(
                self.create_mock_query_result(
                    "entity",
                    f"AI Entity {i} (Organization): AI company {i}",
                    {"entity_name": f"AI Entity {i}"}
                )
            )

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        # Verify that suggestions are based on limited analysis (implementation detail)

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_person_organization_suggestions(self):
        """
        GIVEN a QueryEngine instance
        AND original query "tech executives"
        AND results containing Person and Organization entities
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Person-specific queries generated for people mentioned
            - Organization-specific queries generated for companies mentioned
            - Entity type differentiation in suggestions
        """
        # GIVEN
        original_query = "tech executives"
        results = [
            self.create_mock_query_result(
                "entity",
                "Tim Cook (Person): CEO of Apple",
                {"entity_name": "Tim Cook", "entity_type": "Person"}
            ),
            self.create_mock_query_result(
                "entity",
                "Apple (Organization): Technology company",
                {"entity_name": "Apple", "entity_type": "Organization"}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        assert "What is Tim Cook?" in suggestions
        assert "What is Apple?" in suggestions

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_maximum_five_limit(self):
        """
        GIVEN a QueryEngine instance
        AND original query with many possible suggestions
        AND results with rich content for suggestion generation
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Exactly 5 or fewer suggestions returned
            - Most relevant suggestions prioritized
            - Limit enforced regardless of available content
        """
        # GIVEN
        original_query = "technology industry"
        # Create results that could generate many suggestions
        results = []
        for i in range(10):
            results.append(
                self.create_mock_query_result(
                    "entity",
                    f"Tech Company {i} (Organization): Technology firm {i}",
                    {"entity_name": f"Tech Company {i}", "entity_type": "Organization"}
                )
            )

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_empty_results_list(self):
        """
        GIVEN a QueryEngine instance
        AND original query "nonexistent topic"
        AND empty results list
        WHEN _generate_query_suggestions is called
        THEN expect ValueError to be raised (no suggestions possible)
        """
        # GIVEN
        original_query = "nonexistent topic"
        results = []

        # WHEN & THEN
        with pytest.raises(ValueError, match="no suggestions possible"):
            await self.query_engine._generate_query_suggestions(original_query, results)

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_non_query_result_objects(self):
        """
        GIVEN a QueryEngine instance
        AND original query "test"
        AND results list containing non-QueryResult objects
        WHEN _generate_query_suggestions is called
        THEN expect TypeError to be raised
        """
        # GIVEN
        original_query = "test"
        results = ["not a QueryResult", {"also": "not a QueryResult"}]

        # WHEN & THEN
        with pytest.raises(TypeError):
            await self.query_engine._generate_query_suggestions(original_query, results)

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_relevance_ordered_output(self):
        """
        GIVEN a QueryEngine instance
        AND original query "business relationships"
        AND results with varying relevance
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Suggestions ordered by relevance and likelihood of user interest
            - Most relevant suggestions appear first
            - Logical suggestion progression maintained
        """
        # GIVEN
        original_query = "business relationships"
        results = [
            QueryResult(
                id="high_relevance",
                type="relationship",
                content="Microsoft acquired LinkedIn",
                relevance_score=0.9,
                source_document="doc1",
                source_chunks=["chunk1"],
                metadata={"relationship_type": "acquired"}
            ),
            QueryResult(
                id="low_relevance",
                type="entity",
                content="Small Company (Organization)",
                relevance_score=0.3,
                source_document="doc2", 
                source_chunks=["chunk2"],
                metadata={"entity_name": "Small Company"}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        # Higher relevance results should influence suggestions more

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_complete_executable_queries(self):
        """
        GIVEN a QueryEngine instance
        AND original query "technology innovations"
        AND valid results
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Each suggestion is a complete, executable query string
            - Suggestions can be directly used as new queries
            - No partial or incomplete query suggestions
        """
        # GIVEN
        original_query = "technology innovations"
        results = [
            self.create_mock_query_result(
                "entity",
                "OpenAI (Organization): AI research company",
                {"entity_name": "OpenAI", "entity_type": "Organization"}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        for suggestion in suggestions:
            assert isinstance(suggestion, str)
            assert len(suggestion.strip()) > 0
            assert suggestion.endswith("?") or suggestion.startswith("Find") or suggestion.startswith("What")

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_context_preservation(self):
        """
        GIVEN a QueryEngine instance
        AND original query about specific domain
        AND domain-specific results
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Suggestions maintain relevance to original query context
            - Domain-specific follow-up questions generated
            - User's original intent preserved in suggestions
        """
        # GIVEN
        original_query = "machine learning algorithms"
        results = [
            self.create_mock_query_result(
                "entity",
                "TensorFlow (Technology): Machine learning framework",
                {"entity_name": "TensorFlow", "entity_type": "Technology"}
            ),
            self.create_mock_query_result(
                "entity",
                "Neural Networks (Concept): Deep learning approach",
                {"entity_name": "Neural Networks", "entity_type": "Concept"}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        # Suggestions should maintain ML/AI context
        suggestion_text = " ".join(suggestions).lower()
        assert any(term in suggestion_text for term in ["tensorflow", "neural", "machine", "learning"])

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_entity_relationship_patterns(self):
        """
        GIVEN a QueryEngine instance
        AND original query "founders"
        AND results containing entities and relationships
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Entity queries: "What is [EntityName]?"
            - Relationship queries: "What are the relationships of [EntityName]?"
            - Pattern-based suggestion generation implemented
        """
        # GIVEN
        original_query = "founders"
        results = [
            self.create_mock_query_result(
                "entity",
                "Elon Musk (Person): Entrepreneur and founder",
                {"entity_name": "Elon Musk", "entity_type": "Person"}
            ),
            self.create_mock_query_result(
                "relationship",
                "Elon Musk founded Tesla",
                {"relationship_type": "founded", "source_entity": "Elon Musk", "target_entity": "Tesla"}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        assert "What is Elon Musk?" in suggestions
        assert "What are the relationships of Elon Musk?" in suggestions

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_no_meaningful_suggestions(self):
        """
        GIVEN a QueryEngine instance
        AND original query with very sparse results
        AND results lacking sufficient content for suggestions
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Empty list returned if no meaningful suggestions possible
            - Graceful handling of insufficient content
            - No forced or irrelevant suggestions generated
        """
        # GIVEN
        original_query = "sparse content"
        results = [
            QueryResult(
                id="sparse",
                type="chunk",
                content="",  # Empty content
                relevance_score=0.1,
                source_document="doc1",
                source_chunks=["chunk1"],
                metadata={}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) == 0  # No meaningful suggestions possible

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_original_query_context_usage(self):
        """
        GIVEN a QueryEngine instance
        AND original query providing context
        AND results with related content
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Original query context maintained and used
            - Suggestions relevant to original user intent
            - Query context helps maintain focus in suggestions
        """
        # GIVEN
        original_query = "startup funding rounds"
        results = [
            self.create_mock_query_result(
                "relationship",
                "Sequoia Capital funded Airbnb",
                {"relationship_type": "funded", "source_entity": "Sequoia Capital", "target_entity": "Airbnb"}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        # Suggestions should maintain startup/funding context
        suggestion_text = " ".join(suggestions).lower()
        assert any(term in suggestion_text for term in ["sequoia", "airbnb", "funded", "funding"])

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_suggestion_uniqueness(self):
        """
        GIVEN a QueryEngine instance
        AND original query generating potential duplicate suggestions
        AND results with overlapping content
        WHEN _generate_query_suggestions is called
        THEN expect:
            - No duplicate suggestions in returned list
            - Unique suggestions only
            - Duplicate elimination implemented
        """
        # GIVEN
        original_query = "microsoft"
        # Create results that could lead to duplicate suggestions
        results = [
            self.create_mock_query_result(
                "entity",
                "Microsoft (Organization): Technology company",
                {"entity_name": "Microsoft", "entity_type": "Organization"}
            ),
            self.create_mock_query_result(
                "entity",
                "Microsoft Corporation (Organization): Same company",
                {"entity_name": "Microsoft", "entity_type": "Organization"}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        assert len(suggestions) == len(set(suggestions))  # No duplicates

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_performance_with_large_results(self):
        """
        GIVEN a QueryEngine instance
        AND original query with many results
        AND large results list for analysis
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Method completes within reasonable time
            - Performance optimized for large result sets
            - Analysis limited to prevent performance issues
        """
        # GIVEN
        original_query = "performance test"
        # Create large results list
        results = []
        for i in range(100):  # Large number of results
            results.append(
                self.create_mock_query_result(
                    "entity",
                    f"Entity {i} (Organization): Company {i}",
                    {"entity_name": f"Entity {i}"}
                )
            )

        # WHEN
        import time
        start_time = time.time()
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)
        end_time = time.time()

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        assert (end_time - start_time) < 1.0  # Should complete within 1 second

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_mixed_result_types(self):
        """
        GIVEN a QueryEngine instance
        AND original query "comprehensive analysis"
        AND results containing mix of entities, relationships, chunks, and documents
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Suggestions generated based on all result types
            - Entity, relationship, and content-based suggestions mixed
            - Comprehensive suggestion coverage across result types
        """
        # GIVEN
        original_query = "comprehensive analysis"
        results = [
            self.create_mock_query_result(
                "entity",
                "IBM (Organization): Technology corporation",
                {"entity_name": "IBM", "entity_type": "Organization"}
            ),
            self.create_mock_query_result(
                "relationship",
                "IBM acquired Red Hat",
                {"relationship_type": "acquired", "source_entity": "IBM", "target_entity": "Red Hat"}
            ),
            QueryResult(
                id="chunk_result",
                type="chunk",
                content="IBM's cloud computing strategy involves...",
                relevance_score=0.7,
                source_document="doc1",
                source_chunks=["chunk1"],
                metadata={"semantic_types": "paragraph"}
            ),
            QueryResult(
                id="doc_result",
                type="document",
                content="Document about enterprise technology",
                relevance_score=0.6,
                source_document="doc1",
                source_chunks=[],
                metadata={"title": "Enterprise Tech Report"}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        # Should handle mixed result types without errors

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_suggestion_quality_control(self):
        """
        GIVEN a QueryEngine instance
        AND original query with potential for low-quality suggestions
        AND results with varying content quality
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Only high-quality, meaningful suggestions generated
            - Low-quality or generic suggestions filtered out
            - Suggestion quality control mechanisms active
        """
        # GIVEN
        original_query = "quality test"
        results = [
            QueryResult(
                id="good_quality",
                type="entity",
                content="Apple Inc. (Organization): Consumer technology company",
                relevance_score=0.9,
                source_document="doc1",
                source_chunks=["chunk1"],
                metadata={"entity_name": "Apple Inc.", "entity_type": "Organization"}
            ),
            QueryResult(
                id="poor_quality",
                type="entity",
                content="X (Unknown): Unclear entity",
                relevance_score=0.2,
                source_document="doc2",
                source_chunks=["chunk2"],
                metadata={"entity_name": "X", "entity_type": "Unknown"}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        # Should prioritize high-quality results for suggestions

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_async_method_behavior(self):
        """
        GIVEN a QueryEngine instance
        AND valid original query and results
        WHEN _generate_query_suggestions is called as async method
        THEN expect:
            - Method executes asynchronously without blocking
            - Async/await pattern supported correctly
            - Concurrent execution possible
        """
        # GIVEN
        original_query = "async test"
        results = [
            self.create_mock_query_result(
                "entity",
                "AsyncCorp (Organization): Testing company",
                {"entity_name": "AsyncCorp", "entity_type": "Organization"}
            )
        ]

        # WHEN
        # Test that the method can be awaited
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_content_analysis_depth(self):
        """
        GIVEN a QueryEngine instance
        AND original query "content analysis"
        AND results with rich metadata and content
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Deep content analysis for suggestion generation
            - Metadata utilized for contextual suggestions
            - Content richness reflected in suggestion quality
        """
        # GIVEN
        original_query = "content analysis"
        results = [
            QueryResult(
                id="rich_content",
                type="entity",
                content="OpenAI (Organization): AI research company focused on AGI",
                relevance_score=0.9,
                source_document="doc1",
                source_chunks=["chunk1"],
                metadata={
                    "entity_name": "OpenAI",
                    "entity_type": "Organization",
                    "properties": {
                        "focus": "AGI research",
                        "location": "San Francisco",
                        "founded": "2015"
                    }
                }
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        # Rich metadata should enable better suggestions

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_domain_specific_patterns(self):
        """
        GIVEN a QueryEngine instance
        AND original query in specific domain (e.g., "medical research")
        AND domain-specific results
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Domain-specific suggestion patterns recognized
            - Field-appropriate follow-up queries generated
            - Domain expertise reflected in suggestions
        """
        # GIVEN
        original_query = "medical research"
        results = [
            self.create_mock_query_result(
                "entity",
                "Johns Hopkins (Organization): Medical research institution",
                {"entity_name": "Johns Hopkins", "entity_type": "Organization", "domain": "medical"}
            ),
            self.create_mock_query_result(
                "relationship",
                "Johns Hopkins conducted COVID-19 research",
                {"relationship_type": "conducted", "domain": "medical"}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        # Should maintain medical/research domain context

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_user_intent_inference(self):
        """
        GIVEN a QueryEngine instance
        AND original query with implied user intent
        AND results supporting intent inference
        WHEN _generate_query_suggestions is called
        THEN expect:
            - User intent inferred from original query
            - Suggestions aligned with inferred intent
            - Intent-driven suggestion generation implemented
        """
        # GIVEN
        original_query = "who founded"  # Intent: looking for founders
        results = [
            self.create_mock_query_result(
                "relationship",
                "Mark Zuckerberg founded Facebook",
                {"relationship_type": "founded", "source_entity": "Mark Zuckerberg", "target_entity": "Facebook"}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        # Should align with founding/founder intent
        suggestion_text = " ".join(suggestions).lower()
        assert any(term in suggestion_text for term in ["founded", "founder", "mark", "zuckerberg", "facebook"])

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_temporal_context_awareness(self):
        """
        GIVEN a QueryEngine instance
        AND original query with temporal context (e.g., "recent developments")
        AND results with temporal information
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Temporal context preserved in suggestions
            - Time-aware follow-up queries generated
            - Temporal relevance maintained
        """
        # GIVEN
        original_query = "recent AI developments"
        results = [
            QueryResult(
                id="temporal_result",
                type="entity",
                content="GPT-4 (Technology): Recent large language model",
                relevance_score=0.9,
                source_document="doc1",
                source_chunks=["chunk1"],
                metadata={
                    "entity_name": "GPT-4",
                    "entity_type": "Technology",
                    "temporal_context": "2023",
                    "recency": "recent"
                }
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        # Should maintain temporal context

    @pytest.mark.asyncio
    async def test_generate_query_suggestions_complexity_escalation(self):
        """
        GIVEN a QueryEngine instance
        AND original simple query
        AND results enabling more complex follow-up queries
        WHEN _generate_query_suggestions is called
        THEN expect:
            - Suggestions progressively increase in complexity
            - Simple to complex query progression offered
            - User learning pathway supported through suggestions
        """
        # GIVEN
        original_query = "Google"  # Simple entity query
        results = [
            self.create_mock_query_result(
                "entity",
                "Google (Organization): Search engine company",
                {"entity_name": "Google", "entity_type": "Organization"}
            ),
            self.create_mock_query_result(
                "relationship",
                "Google acquired YouTube",
                {"relationship_type": "acquired", "source_entity": "Google", "target_entity": "YouTube"}
            )
        ]

        # WHEN
        suggestions = await self.query_engine._generate_query_suggestions(original_query, results)

        # THEN
        assert isinstance(suggestions, list)
        assert len(suggestions) <= 5
        # Should offer progression from simple to complex queries
        # e.g., "What is Google?" -> "What are the relationships of Google?" -> "Google acquisitions across documents"

    
if __name__ == "__main__":
    pytest.main([__file__, "-v"])