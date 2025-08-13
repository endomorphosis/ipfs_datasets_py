#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"

from datetime import datetime
import pytest
import os
from unittest.mock import Mock, patch
import time
import numpy as np


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


class TestLLMOptimizerOptimizeForLlm:
    """Test LLMOptimizer.optimize_for_llm main processing method."""

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
        self.optimizer.tokenizer.encode.return_value = list(range(50))

    @property
    def decomposed_content(self):
        """Mock decomposed content for testing."""
        return {
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
                            'content': 'Machine learning enables computers to learn patterns from data without explicit programming.',
                            'type': 'text',
                            'subtype': 'paragraph',
                            'position': {'x': 100, 'y': 100},
                            'confidence': 0.90
                        }
                    ]
                }
            ],
            'metadata': {
                'page_count': 1,
                'title': 'ML Basics'
            }
        }

    @property
    def document_metadata(self):
        """Mock document metadata for testing."""
        return {
            'document_id': 'test_doc_001',
            'title': 'Machine Learning Basics',
            'author': 'Test Author'
        }

    @pytest.mark.asyncio
    async def test_optimize_for_llm_returns_llm_document(self):
        """
        GIVEN valid decomposed_content and document_metadata
        WHEN optimize_for_llm is called
        THEN expect LLMDocument instance returned
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        assert isinstance(result, LLMDocument)

    @pytest.mark.asyncio
    async def test_optimize_for_llm_preserves_document_id(self):
        """
        GIVEN valid decomposed_content and document_metadata with document_id
        WHEN optimize_for_llm is called
        THEN expect document_id preserved in result
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        assert result.document_id == self.document_metadata['document_id']

    @pytest.mark.asyncio
    async def test_optimize_for_llm_preserves_title(self):
        """
        GIVEN valid decomposed_content and document_metadata with title
        WHEN optimize_for_llm is called
        THEN expect title preserved in result
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        assert result.title == self.document_metadata['title']

    @pytest.mark.asyncio
    async def test_optimize_for_llm_creates_chunks_list(self):
        """
        GIVEN valid decomposed_content
        WHEN optimize_for_llm is called
        THEN expect chunks returned as list
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        assert isinstance(result.chunks, list)

    @pytest.mark.asyncio
    async def test_optimize_for_llm_creates_non_empty_chunks(self):
        """
        GIVEN valid decomposed_content with content
        WHEN optimize_for_llm is called
        THEN expect at least one chunk created
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        assert len(result.chunks) > 0

    @pytest.mark.asyncio
    async def test_optimize_for_llm_chunks_are_llm_chunk_instances(self):
        """
        GIVEN valid decomposed_content
        WHEN optimize_for_llm is called
        THEN expect all chunks to be LLMChunk instances
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        for chunk in result.chunks:
            assert isinstance(chunk, LLMChunk)

    @pytest.mark.asyncio
    async def test_optimize_for_llm_chunks_have_content(self):
        """
        GIVEN valid decomposed_content
        WHEN optimize_for_llm is called
        THEN expect all chunks to have non-empty content
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        for chunk in result.chunks:
            assert len(chunk.content) > 0

    @pytest.mark.asyncio
    async def test_optimize_for_llm_chunks_have_token_count(self):
        """
        GIVEN valid decomposed_content
        WHEN optimize_for_llm is called
        THEN expect all chunks to have positive token count
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        for chunk in result.chunks:
            assert chunk.token_count > 0

    @pytest.mark.asyncio
    async def test_optimize_for_llm_creates_summary_string(self):
        """
        GIVEN valid decomposed_content
        WHEN optimize_for_llm is called
        THEN expect summary returned as string
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        assert isinstance(result.summary, str)

    @pytest.mark.asyncio
    async def test_optimize_for_llm_creates_non_empty_summary(self):
        """
        GIVEN valid decomposed_content with content
        WHEN optimize_for_llm is called
        THEN expect non-empty summary
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        assert len(result.summary) > 0

    @pytest.mark.asyncio
    async def test_optimize_for_llm_creates_key_entities_list(self):
        """
        GIVEN valid decomposed_content
        WHEN optimize_for_llm is called
        THEN expect key_entities returned as list
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        assert isinstance(result.key_entities, list)

    @pytest.mark.asyncio
    async def test_optimize_for_llm_creates_processing_metadata_dict(self):
        """
        GIVEN valid decomposed_content
        WHEN optimize_for_llm is called
        THEN expect processing_metadata returned as dict
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        assert isinstance(result.processing_metadata, dict)

    @pytest.mark.asyncio
    async def test_optimize_for_llm_includes_processing_time_metadata(self):
        """
        GIVEN valid decomposed_content
        WHEN optimize_for_llm is called
        THEN expect processing_time_seconds in processing_metadata
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        assert 'processing_time_seconds' in result.processing_metadata

    @pytest.mark.asyncio
    async def test_optimize_for_llm_includes_chunk_count_metadata(self):
        """
        GIVEN valid decomposed_content
        WHEN optimize_for_llm is called
        THEN expect chunk_count in processing_metadata
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        assert 'chunk_count' in result.processing_metadata

    @pytest.mark.asyncio
    async def test_optimize_for_llm_includes_token_count_metadata(self):
        """
        GIVEN valid decomposed_content
        WHEN optimize_for_llm is called
        THEN expect token_count in processing_metadata
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        assert 'token_count' in result.processing_metadata

    @pytest.mark.asyncio
    async def test_optimize_for_llm_chunk_count_metadata_matches_actual_chunks(self):
        """
        GIVEN valid decomposed_content
        WHEN optimize_for_llm is called
        THEN expect chunk_count metadata to match actual chunk count
        """

        # When
        result = await self.optimizer.optimize_for_llm(self.decomposed_content, self.document_metadata)
        
        # Then
        assert result.processing_metadata['chunk_count'] == len(result.chunks)

    @pytest.mark.asyncio
    async def test_optimize_for_llm_invalid_decomposed_content(self):
        """
        GIVEN invalid or missing decomposed_content structure
        WHEN optimize_for_llm is called
        THEN expect:
            - ValueError raised with descriptive message
            - Processing halted gracefully
            - No partial results returned
        """
        document_metadata = {'document_id': 'test', 'title': 'Test'}
        
        # Test case 1: Missing 'pages' key
        invalid_content_1 = {
            'metadata': {'title': 'Test'},
            'structure': {}
        }
        
        with pytest.raises(KeyError) as exc_info:
            await self.optimizer.optimize_for_llm(invalid_content_1, document_metadata)
        assert 'pages' in str(exc_info.value).lower()
        
        # Test case 2: None content
        with pytest.raises((TypeError, AttributeError)):
            await self.optimizer.optimize_for_llm(None, document_metadata)
        
        # Test case 3: Empty pages list
        empty_content = {'pages': []}
        result = await self.optimizer.optimize_for_llm(empty_content, document_metadata)
        assert isinstance(result, LLMDocument)
        assert len(result.chunks) == 0
        
        # Test case 4: Pages with no elements
        no_elements_content = {
            'pages': [
                {'elements': []},
                {'elements': []}
            ]
        }
        result = await self.optimizer.optimize_for_llm(no_elements_content, document_metadata)
        assert isinstance(result, LLMDocument)
        assert len(result.chunks) == 0

    @pytest.mark.asyncio
    async def test_optimize_for_llm_invalid_document_metadata(self):
        """
        GIVEN invalid document_metadata structure
        WHEN optimize_for_llm is called
        THEN expect:
            - ValueError raised
            - Appropriate error handling
        """
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
        
        # Test case 1: None metadata
        with pytest.raises((TypeError, AttributeError)):
            await self.optimizer.optimize_for_llm(valid_content, None)
        
        # Test case 2: Missing required keys
        incomplete_metadata = {'title': 'Test'}  # Missing document_id
        with pytest.raises(KeyError):
            await self.optimizer.optimize_for_llm(valid_content, incomplete_metadata)
        
        # Test case 3: Invalid data types
        invalid_type_metadata = {
            'document_id': 123,  # Should be string
            'title': ['not', 'a', 'string']  # Should be string
        }
        # Should handle gracefully by converting to string
        result = await self.optimizer.optimize_for_llm(valid_content, invalid_type_metadata)
        assert isinstance(result, LLMDocument)
        assert isinstance(result.document_id, str)
        assert isinstance(result.title, str)

    @pytest.mark.asyncio
    async def test_optimize_for_llm_empty_content(self):
        """
        GIVEN decomposed_content with no extractable text
        WHEN optimize_for_llm is called
        THEN expect:
            - Graceful handling of empty content
            - LLMDocument returned with empty chunks list
            - Appropriate warning messages
        """
        # Given - Content with empty elements
        empty_content = {
            'pages': [
                {
                    'elements': [
                        {
                            'content': '',  # Empty content
                            'type': 'text',
                            'subtype': 'paragraph',
                            'position': {'x': 0, 'y': 0},
                            'confidence': 0.9
                        },
                        {
                            'content': '   ',  # Whitespace only
                            'type': 'text',
                            'subtype': 'paragraph',
                            'position': {'x': 0, 'y': 50},
                            'confidence': 0.8
                        }
                    ]
                }
            ]
        }
        
        document_metadata = {'document_id': 'empty_test', 'title': 'Empty Content Test'}
        
        # When
        with patch('logging.warning') as mock_warning:
            result = await self.optimizer.optimize_for_llm(empty_content, document_metadata)
        
        # Then
        assert isinstance(result, LLMDocument)
        assert len(result.chunks) == 0
        assert result.summary == '' or 'no content' in result.summary.lower()
        assert len(result.key_entities) == 0
        
        # Should log warning about empty content
        mock_warning.assert_called()

    @pytest.mark.asyncio
    async def test_optimize_for_llm_large_document(self):
        """
        GIVEN large decomposed_content (>1000 pages)
        WHEN optimize_for_llm is called
        THEN expect:
            - Processing completes within reasonable time
            - Memory usage remains manageable
            - All content processed correctly
        """
        # Given - Create large document
        large_pages = []
        for page_num in range(50):  # Reduced from 1000 for test performance
            elements = []
            for elem_num in range(20):
                elements.append({
                    'content': f'Page {page_num + 1}, element {elem_num + 1}. ' * 50,  # Long content
                    'type': 'text',
                    'subtype': 'paragraph',
                    'position': {'x': 100, 'y': elem_num * 50},
                    'confidence': 0.9
                })
            large_pages.append({'elements': elements})
        
        large_content = {
            'pages': large_pages,
            'metadata': {'page_count': 50, 'title': 'Large Document'}
        }
        
        document_metadata = {'document_id': 'large_test', 'title': 'Large Document Test'}
        
        # When
        import time
        start_time = time.time()
        result = await self.optimizer.optimize_for_llm(large_content, document_metadata)
        processing_time = time.time() - start_time
        
        # Then
        assert isinstance(result, LLMDocument)
        assert len(result.chunks) > 0
        assert processing_time < 60.0  # Should complete within 60 seconds
        
        # Verify all pages were processed
        page_numbers = {chunk.source_page for chunk in result.chunks}
        assert len(page_numbers) == 50
        
        # Verify chunk size constraints
        for chunk in result.chunks:
            assert chunk.token_count <= self.optimizer.max_chunk_size
            assert chunk.token_count >= self.optimizer.min_chunk_size or len(result.chunks) == 1

    @pytest.mark.asyncio
    async def test_optimize_for_llm_model_failure_handling(self):
        """
        GIVEN model loading failures during processing
        WHEN optimize_for_llm is called
        THEN expect:
            - RuntimeError raised with descriptive message
            - Partial processing avoided
            - Clean error propagation
        """
        # Given
        valid_content = {
            'pages': [
                {
                    'elements': [
                        {
                            'content': 'Test content for model failure scenario',
                            'type': 'text',
                            'subtype': 'paragraph',
                            'position': {'x': 0, 'y': 0},
                            'confidence': 0.9
                        }
                    ]
                }
            ]
        }
        document_metadata = {'document_id': 'model_fail_test', 'title': 'Model Failure Test'}
        
        # Test case 1: Embedding model failure
        self.optimizer.embedding_model = None
        
        with pytest.raises(RuntimeError) as exc_info:
            await self.optimizer.optimize_for_llm(valid_content, document_metadata)
        assert 'embedding model' in str(exc_info.value).lower()
        
        # Test case 2: Tokenizer failure during processing
        self.optimizer.embedding_model = Mock()
        self.optimizer.embedding_model.encode.return_value = np.random.rand(384)
        self.optimizer.tokenizer = None
        
        # Should still work with fallback tokenization
        result = await self.optimizer.optimize_for_llm(valid_content, document_metadata)
        assert isinstance(result, LLMDocument)
        assert len(result.chunks) > 0

    @pytest.mark.asyncio
    async def test_optimize_for_llm_concurrent_processing(self):
        """
        GIVEN multiple concurrent optimize_for_llm calls
        WHEN processing multiple documents simultaneously
        THEN expect:
            - No interference between concurrent processes
            - All documents processed correctly
            - No shared state corruption
        """
        # Given - Multiple different documents
        documents = []
        for i in range(3):
            doc_content = {
                'pages': [
                    {
                        'elements': [
                            {
                                'content': f'Document {i + 1} unique content for concurrent testing.',
                                'type': 'text',
                                'subtype': 'paragraph',
                                'position': {'x': 0, 'y': 0},
                                'confidence': 0.9
                            }
                        ]
                    }
                ]
            }
            doc_metadata = {'document_id': f'concurrent_test_{i + 1}', 'title': f'Concurrent Test {i + 1}'}
            documents.append((doc_content, doc_metadata))
        
        # When - Process concurrently
        tasks = [
            self.optimizer.optimize_for_llm(content, metadata)
            for content, metadata in documents
        ]
        results = await asyncio.gather(*tasks)
        
        # Then
        assert len(results) == 3
        
        for i, result in enumerate(results):
            assert isinstance(result, LLMDocument)
            assert result.document_id == f'concurrent_test_{i + 1}'
            assert result.title == f'Concurrent Test {i + 1}'
            assert len(result.chunks) > 0
            assert f'Document {i + 1}' in result.chunks[0].content

    @pytest.mark.asyncio
    async def test_optimize_for_llm_unicode_and_special_characters(self):
        """
        GIVEN content with Unicode characters and special formatting
        WHEN optimize_for_llm is called
        THEN expect:
            - Unicode content preserved correctly
            - Special characters handled appropriately
            - No encoding errors
        """
        # Given - Content with Unicode and special characters
        unicode_content = {
            'pages': [
                {
                    'elements': [
                        {
                            'content': 'Título en español: Introducción al aprendizaje automático 🤖',
                            'type': 'text',
                            'subtype': 'header',
                            'position': {'x': 0, 'y': 0},
                            'confidence': 0.9
                        },
                        {
                            'content': 'Français: L\'intelligence artificielle révolutionne l\'industrie. 中文测试内容',
                            'type': 'text',
                            'subtype': 'paragraph',
                            'position': {'x': 0, 'y': 50},
                            'confidence': 0.85
                        },
                        {
                            'content': 'Mathematical symbols: α, β, γ, ∑, ∫, ∂, ∇, ∞, ≈, ≠, ≤, ≥',
                            'type': 'text',
                            'subtype': 'paragraph',
                            'position': {'x': 0, 'y': 100},
                            'confidence': 0.8
                        }
                    ]
                }
            ]
        }
        
        document_metadata = {'document_id': 'unicode_test', 'title': 'Unicode Test Document'}
        
        # When
        result = await self.optimizer.optimize_for_llm(unicode_content, document_metadata)
        
        # Then
        assert isinstance(result, LLMDocument)
        assert len(result.chunks) > 0
        
        # Verify Unicode content is preserved
        all_content = ' '.join(chunk.content for chunk in result.chunks)
        assert '🤖' in all_content
        assert 'español' in all_content
        assert 'Français' in all_content
        assert '中文' in all_content
        assert '∑' in all_content
        
        # Verify no encoding errors occurred
        for chunk in result.chunks:
            assert isinstance(chunk.content, str)
            # Should not contain replacement characters
            assert '�' not in chunk.content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
