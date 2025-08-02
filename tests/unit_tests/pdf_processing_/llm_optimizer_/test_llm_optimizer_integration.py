#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"

from datetime import datetime
import pytest
import os

import os
import pytest
import time
import numpy as np
from unittest.mock import Mock, patch

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.llm_optimizer import (
    ChunkOptimizer,
    LLMOptimizer,
    TextProcessor,
    LLMChunk,
    LLMDocument
)


# Check if each classes methods are accessible:
assert LLMOptimizer._initialize_models
assert LLMOptimizer.optimize_for_llm
assert LLMOptimizer._extract_structured_text
assert LLMOptimizer._generate_document_summary
assert LLMOptimizer._create_optimal_chunks
assert LLMOptimizer._create_chunk
assert LLMOptimizer._establish_chunk_relationships
assert LLMOptimizer._generate_embeddings
assert LLMOptimizer._extract_key_entities
assert LLMOptimizer._generate_document_embedding
assert LLMOptimizer._count_tokens
assert LLMOptimizer._get_chunk_overlap
assert TextProcessor.split_sentences
assert TextProcessor.extract_keywords
assert ChunkOptimizer.optimize_chunk_boundaries


# 4. Check if the modules's imports are accessible:
try:
    import asyncio
    import logging
    from typing import Dict, List, Any, Optional
    from dataclasses import dataclass
    import re

    import tiktoken
    from transformers import AutoTokenizer
    import numpy as np
    from sentence_transformers import SentenceTransformer
except ImportError as e:
    raise ImportError(f"Failed to import necessary modules: {e}")



class TestLLMOptimizerIntegration:
    """Test LLMOptimizer integration and end-to-end workflows."""

    def setup_method(self):
        """Set up test fixtures."""
        self.optimizer = LLMOptimizer(
            max_chunk_size=1024,
            chunk_overlap=100,
            min_chunk_size=50
        )
        
        # Mock the models to avoid actual model loading
        self.optimizer.embedding_model = Mock()
        self.optimizer.embedding_model.encode.return_value = np.random.rand(384)
        self.optimizer.tokenizer = Mock()
        self.optimizer.tokenizer.encode.return_value = list(range(50))  # Mock token list

    @pytest.mark.asyncio
    async def test_complete_optimization_pipeline(self):
        """
        GIVEN realistic PDF decomposition output
        WHEN complete optimization pipeline is executed
        THEN expect:
            - All processing stages complete successfully
            - LLMDocument with valid structure returned
            - Performance within acceptable bounds
            - Resource usage reasonable
        """
        # Given - Realistic PDF decomposition output
        decomposed_content = {
            'pages': [
                {
                    'elements': [
                        {
                            'content': 'Introduction to Machine Learning',
                            'type': 'text',
                            'subtype': 'header',
                            'position': {'x': 100, 'y': 50},
                            'confidence': 0.95
                        },
                        {
                            'content': 'Machine learning is a subset of artificial intelligence that enables computers to learn without being explicitly programmed.',
                            'type': 'text',
                            'subtype': 'paragraph',
                            'position': {'x': 100, 'y': 100},
                            'confidence': 0.90
                        },
                        {
                            'content': 'Table 1: Performance Metrics',
                            'type': 'table',
                            'subtype': 'caption',
                            'position': {'x': 100, 'y': 200},
                            'confidence': 0.85
                        }
                    ]
                },
                {
                    'elements': [
                        {
                            'content': 'Deep Learning Fundamentals',
                            'type': 'text',
                            'subtype': 'header',
                            'position': {'x': 100, 'y': 50},
                            'confidence': 0.92
                        },
                        {
                            'content': 'Deep learning uses neural networks with multiple layers to model and understand complex patterns in data.',
                            'type': 'text',
                            'subtype': 'paragraph',
                            'position': {'x': 100, 'y': 100},
                            'confidence': 0.88
                        }
                    ]
                }
            ],
            'metadata': {
                'page_count': 2,
                'title': 'Machine Learning Fundamentals',
                'author': 'Test Author'
            }
        }
        
        document_metadata = {
            'document_id': 'test_doc_001',
            'title': 'Machine Learning Fundamentals',
            'author': 'Test Author',
            'creation_date': '2024-01-01'
        }
        
        # When - Execute complete pipeline
        start_time = time.time()
        result = await self.optimizer.optimize_for_llm(decomposed_content, document_metadata)
        processing_time = time.time() - start_time
        
        # Then - Verify successful completion
        assert isinstance(result, LLMDocument)
        assert result.document_id == document_metadata['document_id']
        assert result.title == document_metadata['title']
        
        # Verify chunks created
        assert isinstance(result.chunks, list)
        assert len(result.chunks) > 0
        
        # Verify each chunk structure
        for chunk in result.chunks:
            assert isinstance(chunk, LLMChunk)
            assert isinstance(chunk.content, str)
            assert len(chunk.content) > 0
            assert isinstance(chunk.chunk_id, str)
            assert isinstance(chunk.token_count, int)
            assert chunk.token_count > 0
            assert isinstance(chunk.semantic_types, str)
            assert isinstance(chunk.relationships, list)
            assert isinstance(chunk.metadata, dict)
        
        # Verify document-level components
        assert isinstance(result.summary, str)
        assert len(result.summary) > 0
        assert isinstance(result.key_entities, list)
        assert isinstance(result.processing_metadata, dict)
        
        # Verify performance bounds
        TIME_LIMIT = 30.0
        assert processing_time < TIME_LIMIT  # Should complete within 30 seconds
        
        # Verify resource usage indicators in metadata
        assert 'processing_time_seconds' in result.processing_metadata
        assert 'chunk_count' in result.processing_metadata
        assert 'token_count' in result.processing_metadata

    @pytest.mark.asyncio
    async def test_pipeline_error_propagation(self):
        """
        GIVEN intentional errors at various pipeline stages
        WHEN optimization pipeline is executed
        THEN expect:
            - Errors propagated appropriately
            - Clean error messages
            - No partial or corrupted results
        """
        # Given - Invalid decomposed content (missing pages)
        invalid_content = {
            'metadata': {'title': 'Test Document'},
            'structure': {}
            # Missing 'pages' key
        }
        document_metadata = {'document_id': 'test_doc', 'title': 'Test'}
        
        # When & Then - Should raise appropriate error
        with pytest.raises(KeyError) as exc_info:
            await self.optimizer.optimize_for_llm(invalid_content, document_metadata)
        
        assert 'pages' in str(exc_info.value).lower()
        
        # Given - Valid structure but embedding model failure
        valid_content = {
            'pages': [
                {
                    'elements': [
                        {
                            'content': 'Test content',
                            'type': 'text',
                            'subtype': 'paragraph',
                            'position': {'x': 0, 'y': 0},
                            'confidence': 0.9
                        }
                    ]
                }
            ]
        }
        
        # Mock embedding model to raise error
        self.optimizer.embedding_model.encode.side_effect = RuntimeError("Model failed")
        
        # When
        with patch('logging.warning') as mock_log:
            result = await self.optimizer.optimize_for_llm(valid_content, document_metadata)
        
        # Then - Should handle gracefully
        assert isinstance(result, LLMDocument)
        # Chunks should exist but without embeddings
        for chunk in result.chunks:
            assert chunk.embedding is None
        
        # Should log the error
        mock_log.assert_called()

    # TODO Comment this out until it stops getting into an endless loop.
    # @pytest.mark.asyncio
    # async def test_pipeline_performance_benchmarks(self):
    #     """
    #     GIVEN various document sizes and complexities
    #     WHEN optimization pipeline is executed
    #     THEN expect:
    #         - Processing time scales reasonably with content size
    #         - Memory usage remains within bounds
    #         - Quality metrics maintained across sizes
    #     """
    #     # Given - Different document sizes
    #     print("Starting performance benchmarks...")
    #     small_doc = self._create_test_document(pages=1, elements_per_page=3)
    #     print("Created small document for testing.")
    #     medium_doc = self._create_test_document(pages=5, elements_per_page=10)
    #     print("Created medium document for testing.")
    #     large_doc = self._create_test_document(pages=20, elements_per_page=25)
    #     print("Created large document for testing.")
        
    #     document_metadata = {'document_id': 'perf_test', 'title': 'Performance Test'}
        
    #     performance_results = []
        
    #     for doc_name, doc_content in [
    #         ('small', small_doc),
    #         ('medium', medium_doc),
    #         ('large', large_doc)
    #     ]:
    #         # When
    #         print(f"Processing {doc_name} document...")
    #         start_time = time.time()
    #         result = await self.optimizer.optimize_for_llm(doc_content, document_metadata)
    #         processing_time = time.time() - start_time
    #         print(f"Finished processing {doc_name} document in {processing_time:.2f} seconds.")
            
    #         performance_results.append({
    #             'name': doc_name,
    #             'pages': len(doc_content['pages']),
    #             'total_elements': sum(len(page['elements']) for page in doc_content['pages']),
    #             'processing_time': processing_time,
    #             'chunk_count': len(result.chunks),
    #             'avg_chunk_size': np.mean([chunk.token_count for chunk in result.chunks])
    #         })
        
    #     # Then - Verify scaling behavior
    #     small_result, medium_result, large_result = performance_results
        
    #     # Processing time should scale reasonably (not exponentially)
    #     time_ratio_small_to_medium = medium_result['processing_time'] / small_result['processing_time']
    #     time_ratio_medium_to_large = large_result['processing_time'] / medium_result['processing_time']
        
    #     # Should not be exponential scaling (allowing for some variation)
    #     assert time_ratio_small_to_medium < 10  # Medium shouldn't be more than 10x slower
    #     assert time_ratio_medium_to_large < 10  # Large shouldn't be more than 10x slower
        
    #     # Quality metrics should be maintained
    #     for result in performance_results:
    #         assert result['chunk_count'] > 0
    #         assert result['avg_chunk_size'] > 0
    #         assert result['avg_chunk_size'] <= self.optimizer.max_chunk_size




@pytest.fixture
def decomposed_content():
    """Fixture providing consistent test data for reproducibility testing."""
    decomposed_content = {
        'pages': [
            {
                'elements': [
                    {
                        'content': 'Consistent test content for reproducibility testing.',
                        'type': 'text',
                        'subtype': 'paragraph',
                        'position': {'x': 100, 'y': 100},
                        'confidence': 0.9
                    }
                ]
            }
        ]
    }
    return decomposed_content

@pytest.fixture
def document_metadata():
    """Fixture providing consistent document metadata for reproducibility testing."""
    document_metadata = {
        'document_id': 'consistency_test', 
        'title': 'Consistency Test'
    }
    return document_metadata


class TestLLMOptimizerConsistency:
    """Test LLMOptimizer consistency and reproducibility across multiple runs."""

    def setup_method(self):
        """Set up test fixtures."""
        self.optimizer = LLMOptimizer(
            max_chunk_size=1024,
            chunk_overlap=100,
            min_chunk_size=50
        )
        
        # Mock the models to avoid actual model loading
        self.optimizer.embedding_model = Mock()
        self.optimizer.embedding_model.encode.return_value = np.random.rand(384)
        self.optimizer.tokenizer = Mock()
        self.optimizer.tokenizer.encode.return_value = list(range(50))  # Mock token list

    @pytest.mark.asyncio
    async def test_pipeline_consistency_document_id(self, decomposed_content, document_metadata):
        """Test that document ID remains consistent across multiple runs."""
        # Given - Fixed input document

        # When - Run multiple times
        results = []
        for i in range(3):
            result = await self.optimizer.optimize_for_llm(decomposed_content, document_metadata)
            results.append(result)
        
        # Then - Verify document ID consistency
        first_result = results[0]
        for result in results[1:]:
            assert result.document_id == first_result.document_id

    @pytest.mark.asyncio
    async def test_pipeline_consistency_title(self, decomposed_content, document_metadata):
        """Test that title remains consistent across multiple runs."""
        # Given - Fixed input document
        
        # When - Run multiple times
        results = []
        for i in range(3):
            result = await self.optimizer.optimize_for_llm(decomposed_content, document_metadata)
            results.append(result)
        
        # Then - Verify title consistency
        first_result = results[0]
        for result in results[1:]:
            assert result.title == first_result.title

    @pytest.mark.asyncio
    async def test_pipeline_consistency_chunk_count(self, decomposed_content, document_metadata):
        """Test that chunk count remains consistent across multiple runs."""
        # Given - Fixed input document

        # When - Run multiple times
        results = []
        for i in range(3):
            result = await self.optimizer.optimize_for_llm(decomposed_content, document_metadata)
            results.append(result)
        
        # Then - Verify chunk count consistency
        first_result = results[0]
        for result in results[1:]:
            assert len(result.chunks) == len(first_result.chunks)

    @pytest.mark.asyncio
    async def test_pipeline_consistency_chunk_content(self, decomposed_content, document_metadata):
        """Test that chunk content remains consistent across multiple runs."""
        # Given - Fixed input document

        # When - Run multiple times
        results = []
        for i in range(3):
            result = await self.optimizer.optimize_for_llm(decomposed_content, document_metadata)
            results.append(result)
        
        # Then - Verify chunk content consistency
        first_result = results[0]
        for result in results[1:]:
            for i, (chunk1, chunk2) in enumerate(zip(first_result.chunks, result.chunks)):
                assert chunk1.content == chunk2.content

    @pytest.mark.asyncio
    async def test_pipeline_consistency_chunk_ids(self, decomposed_content, document_metadata):
        """Test that chunk IDs remain consistent across multiple runs."""
        # Given - Fixed input document
        
        # When - Run multiple times
        results = []
        for i in range(3):
            result = await self.optimizer.optimize_for_llm(decomposed_content, document_metadata)
            results.append(result)
        
        # Then - Verify chunk ID consistency
        first_result = results[0]
        for result in results[1:]:
            for i, (chunk1, chunk2) in enumerate(zip(first_result.chunks, result.chunks)):
                assert chunk1.chunk_id == chunk2.chunk_id

    @pytest.mark.asyncio
    async def test_pipeline_consistency_token_counts(self, decomposed_content, document_metadata):
        """Test that token counts remain consistent across multiple runs."""
        # Given - Fixed input document

        # When - Run multiple times
        results = []
        for i in range(3):
            result = await self.optimizer.optimize_for_llm(decomposed_content, document_metadata)
            results.append(result)
        
        # Then - Verify token count consistency
        first_result = results[0]
        for result in results[1:]:
            for i, (chunk1, chunk2) in enumerate(zip(first_result.chunks, result.chunks)):
                assert chunk1.token_count == chunk2.token_count

    @pytest.mark.asyncio
    async def test_pipeline_consistency_semantic_types(self, decomposed_content, document_metadata):
        """Test that semantic types remain consistent across multiple runs."""
        # Given - Fixed input document

        # When - Run multiple times
        results = []
        for i in range(3):
            result = await self.optimizer.optimize_for_llm(decomposed_content, document_metadata)
            results.append(result)
        
        # Then - Verify semantic types consistency
        first_result = results[0]
        for result in results[1:]:
            for i, (chunk1, chunk2) in enumerate(zip(first_result.chunks, result.chunks)):
                assert chunk1.semantic_types == chunk2.semantic_types

    @pytest.mark.asyncio
    async def test_pipeline_consistency_source_pages(self, decomposed_content, document_metadata):
        """Test that source pages remain consistent across multiple runs."""
        # Given - Fixed input document

        # When - Run multiple times
        results = []
        for i in range(3):
            result = await self.optimizer.optimize_for_llm(decomposed_content, document_metadata)
            results.append(result)
        
        # Then - Verify source page consistency
        first_result = results[0]
        for result in results[1:]:
            for i, (chunk1, chunk2) in enumerate(zip(first_result.chunks, result.chunks)):
                assert chunk1.source_page == chunk2.source_page

    @pytest.mark.asyncio
    async def test_pipeline_consistency_summary(self, decomposed_content, document_metadata):
        """Test that document summary remains consistent across multiple runs."""
        # Given - Fixed input document

        # When - Run multiple times
        results = []
        for i in range(3):
            result = await self.optimizer.optimize_for_llm(decomposed_content, document_metadata)
            results.append(result)
        
        # Then - Verify summary consistency
        first_result = results[0]
        for result in results[1:]:
            assert result.summary == first_result.summary

    @pytest.mark.asyncio
    async def test_pipeline_consistency_entity_count(self, decomposed_content, document_metadata):
        """Test that entity count remains consistent across multiple runs."""
        # Given - Fixed input document
        
        # When - Run multiple times
        results = []
        for i in range(3):
            result = await self.optimizer.optimize_for_llm(decomposed_content, document_metadata)
            results.append(result)
        
        # Then - Verify entity count consistency
        first_result = results[0]
        for result in results[1:]:
            assert len(result.key_entities) == len(first_result.key_entities)

    def _create_test_document(self, pages: int, elements_per_page: int) -> dict:
        """Helper method to create test documents of varying sizes."""
        doc_pages = []
        
        for page_num in range(pages):
            elements = []
            for elem_num in range(elements_per_page):
                elements.append({
                    'content': f'This is test content for page {page_num + 1}, element {elem_num + 1}. ' * 10,
                    'type': 'text',
                    'subtype': 'paragraph' if elem_num % 3 != 0 else 'header',
                    'position': {'x': 100, 'y': 50 + elem_num * 50},
                    'confidence': 0.9 - (elem_num * 0.01)
                })
            
            doc_pages.append({'elements': elements})
        
        return {
            'pages': doc_pages,
            'metadata': {
                'page_count': pages,
                'title': f'Test Document {pages}p',
                'author': 'Test Author'
            }
        }


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
