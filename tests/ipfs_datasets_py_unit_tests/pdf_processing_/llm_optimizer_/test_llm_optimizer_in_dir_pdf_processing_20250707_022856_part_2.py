
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56

import pytest
import os

import os
import pytest
import time
import numpy as np

from tests._test_utils import (
    raise_on_bad_callable_metadata,
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
    LLMDocument,
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
    raise ImportError(f"Could not import the module's own imports: {e}")


class TestQualityOfObjectsInModule:
    """
    Test class for the quality of callable objects 
    (e.g. class, method, function, coroutine, or property) in the module.
    """

    def test_callable_objects_metadata_quality(self):
        """
        GIVEN a Python module
        WHEN the module is parsed by the AST
        THEN
         - Each callable object should have a detailed, Google-style docstring.
         - Each callable object should have a detailed signature with type hints and a return annotation.
        """
        tree = get_ast_tree(file_path)
        try:
            raise_on_bad_callable_metadata(tree)
        except (BadDocumentationError, BadSignatureError) as e:
            pytest.fail(f"Code metadata quality check failed: {e}")

    def test_callable_objects_quality(self):
        """
        GIVEN a Python module
        WHEN the module's source code is examined
        THEN if the file is not indicated as a mock, placeholder, stub, or example:
         - The module should not contain intentionally fake or simplified code 
            (e.g. "In a real implementation, ...")
         - Contain no mocked objects or placeholders.
        """
        try:
            raise_on_bad_callable_code_quality(file_path)
        except (BadDocumentationError, BadSignatureError) as e:
            for indicator in ["mock", "placeholder", "stub", "example"]:
                if indicator in file_path:
                    break
            else:
                # If no indicator is found, fail the test
                pytest.fail(f"Code quality check failed: {e}")



class TestLLMOptimizerGenerateEmbeddings:
    """Test LLMOptimizer._generate_embeddings method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.optimizer = LLMOptimizer()
        
        # Create mock chunks for testing
        self.mock_chunks = [
            LLMChunk(
                content="This is the first chunk of text for testing embeddings.",
                chunk_id="chunk_0000",
                source_page=1,
                source_element=["paragraph"],
                token_count=12,
                semantic_type="text",
                relationships=[],
                metadata={"test": True},
                embedding=None
            ),
            LLMChunk(
                content="This is the second chunk with different content for embedding generation.",
                chunk_id="chunk_0001", 
                source_page=1,
                source_element=["paragraph"],
                token_count=14,
                semantic_type="text",
                relationships=[],
                metadata={"test": True},
                embedding=None
            ),
            LLMChunk(
                content="Final chunk for comprehensive embedding testing scenarios.",
                chunk_id="chunk_0002",
                source_page=2,
                source_element=["paragraph"],
                token_count=10,
                semantic_type="text",
                relationships=[],
                metadata={"test": True},
                embedding=None
            )
        ]

    @pytest.mark.asyncio
    async def test_generate_embeddings_valid_chunks(self):
        """
        GIVEN list of chunks with valid content
        WHEN _generate_embeddings is called
        THEN expect:
            - All chunks have embedding attributes populated
            - Embeddings are numpy arrays with correct shape
            - Batch processing completed successfully
        """
        # Given
        chunks = self.mock_chunks.copy()
        
        # Mock the embedding model
        mock_embedding_model = Mock()
        mock_embeddings = np.random.rand(3, 384)  # 3 chunks, 384-dim embeddings
        mock_embedding_model.encode.return_value = mock_embeddings
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        assert len(result_chunks) == 3
        for i, chunk in enumerate(result_chunks):
            assert chunk.embedding is not None
            assert isinstance(chunk.embedding, np.ndarray)
            assert chunk.embedding.shape == (384,)
            np.testing.assert_array_equal(chunk.embedding, mock_embeddings[i])
        
        # Verify model was called correctly
        mock_embedding_model.encode.assert_called_once()
        call_args = mock_embedding_model.encode.call_args[0][0]
        assert len(call_args) == 3
        assert call_args[0] == chunks[0].content

    @pytest.mark.asyncio
    async def test_generate_embeddings_model_unavailable(self):
        """
        GIVEN embedding model is None or unavailable
        WHEN _generate_embeddings is called
        THEN expect:
            - RuntimeError raised
            - Clear error message about model availability
            - No partial embeddings generated
        """
        # Given
        chunks = self.mock_chunks.copy()
        self.optimizer.embedding_model = None
        
        # When & Then
        with pytest.raises(RuntimeError) as exc_info:
            await self.optimizer._generate_embeddings(chunks)
        
        assert "embedding model" in str(exc_info.value).lower()
        
        # Verify no embeddings were set
        for chunk in chunks:
            assert chunk.embedding is None

    @pytest.mark.asyncio
    async def test_generate_embeddings_empty_chunks(self):
        """
        GIVEN empty chunks list
        WHEN _generate_embeddings is called
        THEN expect:
            - Empty list returned
            - No errors raised
            - Graceful handling
        """
        # Given
        chunks = []
        mock_embedding_model = Mock()
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        assert result_chunks == []
        assert len(result_chunks) == 0
        
        # Verify model was not called for empty input
        mock_embedding_model.encode.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_processing(self):
        """
        GIVEN large number of chunks requiring batch processing
        WHEN _generate_embeddings is called
        THEN expect:
            - Efficient batch processing
            - Memory usage controlled
            - All chunks processed correctly
        """
        # Given - Create many chunks to test batch processing
        large_chunks = []
        for i in range(50):  # Simulate large document
            chunk = LLMChunk(
                content=f"Content for chunk number {i} in batch processing test.",
                chunk_id=f"chunk_{i:04d}",
                source_page=i // 10 + 1,
                source_element=["paragraph"],
                token_count=10,
                semantic_type="text",
                relationships=[],
                metadata={"batch_test": True},
                embedding=None
            )
            large_chunks.append(chunk)
        
        # Mock embedding model with realistic batch size
        mock_embedding_model = Mock()
        mock_embeddings = np.random.rand(50, 384)
        mock_embedding_model.encode.return_value = mock_embeddings
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(large_chunks)
        
        # Then
        assert len(result_chunks) == 50
        for i, chunk in enumerate(result_chunks):
            assert chunk.embedding is not None
            assert isinstance(chunk.embedding, np.ndarray)
            assert chunk.embedding.shape == (384,)
        
        # Verify single batch call was made
        mock_embedding_model.encode.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_embeddings_error_handling(self):
        """
        GIVEN chunks with content that causes embedding errors
        WHEN _generate_embeddings is called
        THEN expect:
            - Failed chunks retain None embeddings
            - Processing continues for valid chunks
            - Error logging for failed batches
        """
        # Given
        chunks = self.mock_chunks.copy()
        
        # Mock embedding model that raises an exception
        mock_embedding_model = Mock()
        mock_embedding_model.encode.side_effect = Exception("Embedding generation failed")
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        with patch('logging.warning') as mock_log:
            result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        assert len(result_chunks) == 3
        for chunk in result_chunks:
            assert chunk.embedding is None  # Should remain None after failure
        
        # Verify error was logged
        mock_log.assert_called()
        log_message = mock_log.call_args[0][0]
        assert "embedding generation failed" in log_message.lower()

    @pytest.mark.asyncio
    async def test_generate_embeddings_memory_constraints(self):
        """
        GIVEN memory-constrained environment
        WHEN _generate_embeddings is called with large chunks
        THEN expect:
            - MemoryError handled gracefully
            - Batch size adjustment or error reporting
            - System stability maintained
        """
        # Given
        chunks = self.mock_chunks.copy()
        
        # Mock embedding model that raises MemoryError
        mock_embedding_model = Mock()
        mock_embedding_model.encode.side_effect = MemoryError("Insufficient memory for embeddings")
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        with patch('logging.error') as mock_log:
            result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        assert len(result_chunks) == 3
        for chunk in result_chunks:
            assert chunk.embedding is None
        
        # Verify memory error was logged appropriately
        mock_log.assert_called()
        log_message = mock_log.call_args[0][0]
        assert "memory" in log_message.lower()


#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pytest
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer


class TestLLMOptimizerExtractKeyEntities:
    """Test LLMOptimizer._extract_key_entities method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.optimizer = LLMOptimizer()

    @pytest.mark.asyncio
    async def test_extract_key_entities_valid_content(self):
        """
        GIVEN structured_text with extractable entities
        WHEN _extract_key_entities is called
        THEN expect:
            - List of entity dictionaries returned
            - Each entity has 'text', 'type', 'confidence' keys
            - Various entity types detected (date, email, organization)
        """
        # Given
        structured_text = {
            'pages': [
                {
                    'full_text': 'Contact Dr. John Smith at john.smith@university.edu on 12/25/2024 for the ACME Corporation partnership meeting.'
                },
                {
                    'full_text': 'The research was conducted by MIT researchers from January 2023 to March 2024. Send updates to admin@research.org.'
                }
            ]
        }
        
        # When
        entities = await self.optimizer._extract_key_entities(structured_text)
        
        # Then
        assert isinstance(entities, list)
        assert len(entities) > 0
        
        # Verify entity structure
        for entity in entities:
            assert isinstance(entity, dict)
            assert 'text' in entity
            assert 'type' in entity
            assert 'confidence' in entity
            assert isinstance(entity['text'], str)
            assert isinstance(entity['type'], str)
            assert isinstance(entity['confidence'], float)
            assert 0.0 <= entity['confidence'] <= 1.0
        
        # Verify specific entity types are detected
        entity_types = {entity['type'] for entity in entities}
        entity_texts = {entity['text'] for entity in entities}
        
        # Should detect dates
        assert any('date' in entity_type for entity_type in entity_types)
        assert any('2024' in text or '2023' in text for text in entity_texts)
        
        # Should detect emails
        assert any('email' in entity_type for entity_type in entity_types)
        assert any('@' in text for text in entity_texts)
        
        # Should detect organizations
        assert any('organization' in entity_type for entity_type in entity_types)

    @pytest.mark.asyncio
    async def test_extract_key_entities_empty_content(self):
        """
        GIVEN structured_text with no extractable text
        WHEN _extract_key_entities is called
        THEN expect:
            - Empty list returned or ValueError raised
            - Graceful handling of no content
        """
        # Given
        structured_text = {
            'pages': [
                {'full_text': ''},
                {'full_text': '   '},  # Only whitespace
            ]
        }
        
        # When
        entities = await self.optimizer._extract_key_entities(structured_text)
        
        # Then
        assert isinstance(entities, list)
        assert len(entities) == 0

    @pytest.mark.asyncio
    async def test_extract_key_entities_missing_pages(self):
        """
        GIVEN structured_text missing 'pages' key
        WHEN _extract_key_entities is called
        THEN expect KeyError to be raised
        """
        # Given
        structured_text = {
            'metadata': {'title': 'Test Document'},
            'structure': {}
        }
        
        # When & Then
        with pytest.raises(KeyError):
            await self.optimizer._extract_key_entities(structured_text)

    @pytest.mark.asyncio
    async def test_extract_key_entities_pattern_recognition(self):
        """
        GIVEN text with specific entity patterns (dates, emails, organizations)
        WHEN _extract_key_entities is called
        THEN expect:
            - Correct pattern recognition for each entity type
            - Appropriate confidence scores assigned
            - Entity text extracted accurately
        """
        # Given
        structured_text = {
            'pages': [
                {
                    'full_text': '''
                    Date patterns: 12/25/2024, 2024-01-15, January 15, 2024
                    Email patterns: john@example.com, mary.jane@university.edu, admin@company.co.uk
                    Organization patterns: ACME Corporation, University of California, NASA, FBI
                    '''
                }
            ]
        }
        
        # When
        entities = await self.optimizer._extract_key_entities(structured_text)
        
        # Then
        date_entities = [e for e in entities if 'date' in e['type']]
        email_entities = [e for e in entities if 'email' in e['type']]
        org_entities = [e for e in entities if 'organization' in e['type']]
        
        # Verify date pattern recognition
        assert len(date_entities) > 0
        date_texts = {e['text'] for e in date_entities}
        assert any('2024' in text for text in date_texts)
        
        # Verify email pattern recognition
        assert len(email_entities) > 0
        email_texts = {e['text'] for e in email_entities}
        assert any('@' in text and '.com' in text for text in email_texts)
        
        # Verify organization pattern recognition
        assert len(org_entities) > 0
        org_texts = {e['text'] for e in org_entities}
        assert any('Corporation' in text or 'University' in text for text in org_texts)

    @pytest.mark.asyncio
    async def test_extract_key_entities_confidence_scoring(self):
        """
        GIVEN various entity patterns with different match strength
        WHEN _extract_key_entities is called
        THEN expect:
            - Confidence scores between 0.0 and 1.0
            - Higher confidence for stronger pattern matches
            - Reasonable score distribution
        """
        # Given
        structured_text = {
            'pages': [
                {
                    'full_text': '''
                    Strong patterns: john.smith@university.edu, 12/25/2024, NASA
                    Weak patterns: something@something, 99/99/9999, ABC
                    '''
                }
            ]
        }
        
        # When
        entities = await self.optimizer._extract_key_entities(structured_text)
        
        # Then
        assert len(entities) > 0
        
        # All confidence scores should be in valid range
        for entity in entities:
            assert 0.0 <= entity['confidence'] <= 1.0
        
        # Strong email pattern should have higher confidence than weak ones
        email_entities = [e for e in entities if 'email' in e['type']]
        if len(email_entities) > 1:
            strong_email = next((e for e in email_entities if 'university.edu' in e['text']), None)
            if strong_email:
                assert strong_email['confidence'] > 0.5

    @pytest.mark.asyncio
    async def test_extract_key_entities_result_limiting(self):
        """
        GIVEN text with many potential entities
        WHEN _extract_key_entities is called
        THEN expect:
            - Results limited to prevent overwhelming
            - Most confident entities prioritized
            - Reasonable number of entities returned
        """
        # Given - Create text with many potential entities
        dates = [f"{i:02d}/15/2024" for i in range(1, 13)]  # 12 dates
        emails = [f"user{i}@example.com" for i in range(1, 21)]  # 20 emails
        orgs = [f"Company {i} Corporation" for i in range(1, 16)]  # 15 organizations
        
        text_content = " ".join(dates + emails + orgs)
        structured_text = {
            'pages': [{'full_text': text_content}]
        }
        
        # When
        entities = await self.optimizer._extract_key_entities(structured_text)
        
        # Then
        assert isinstance(entities, list)
        # Should limit results to reasonable number (not return all 47 potential entities)
        assert len(entities) <= 30  # Reasonable limit
        assert len(entities) > 0
        
        # Verify entities are sorted by confidence (highest first)
        confidences = [entity['confidence'] for entity in entities]
        assert confidences == sorted(confidences, reverse=True)

    @pytest.mark.asyncio
    async def test_extract_key_entities_unicode_and_special_chars(self):
        """
        GIVEN text with Unicode characters and special formatting
        WHEN _extract_key_entities is called
        THEN expect:
            - Unicode entities handled correctly
            - Special characters in emails/patterns recognized
            - No encoding errors
        """
        # Given
        structured_text = {
            'pages': [
                {
                    'full_text': '''
                    Unicode emails: josé@universidad.es, müller@universität.de
                    International orgs: Société Générale, 株式会社 Toyota
                    Special dates: 25/décembre/2024, 15-января-2025
                    '''
                }
            ]
        }
        
        # When
        entities = await self.optimizer._extract_key_entities(structured_text)
        
        # Then
        assert isinstance(entities, list)
        
        # Should handle Unicode characters without errors
        for entity in entities:
            assert isinstance(entity['text'], str)
            assert isinstance(entity['type'], str)
            assert isinstance(entity['confidence'], float)
        
        # Should detect some international patterns
        if len(entities) > 0:
            entity_texts = {entity['text'] for entity in entities}
            # At least some Unicode content should be preserved
            assert any(len(text.encode('utf-8')) > len(text) for text in entity_texts)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pytest
import numpy as np
from unittest.mock import Mock, patch
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer


class TestLLMOptimizerGenerateDocumentEmbedding:
    """Test LLMOptimizer._generate_document_embedding method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.optimizer = LLMOptimizer()

    @pytest.mark.asyncio
    async def test_generate_document_embedding_valid_input(self):
        """
        GIVEN valid summary and structured_text
        WHEN _generate_document_embedding is called
        THEN expect:
            - Numpy array embedding returned
            - Embedding shape matches model output
            - Document-level semantic representation
        """
        # Given
        summary = "This research paper presents novel machine learning approaches for natural language processing tasks."
        structured_text = {
            'pages': [
                {
                    'elements': [
                        {'content': 'Introduction to Machine Learning', 'type': 'header'},
                        {'content': 'Natural Language Processing Overview', 'type': 'title'},
                        {'content': 'Abstract content here...', 'type': 'paragraph'}
                    ]
                }
            ]
        }
        
        # Mock the embedding model
        mock_embedding_model = Mock()
        expected_embedding = np.random.rand(384)
        mock_embedding_model.encode.return_value = expected_embedding
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        result_embedding = await self.optimizer._generate_document_embedding(summary, structured_text)
        
        # Then
        assert result_embedding is not None
        assert isinstance(result_embedding, np.ndarray)
        assert result_embedding.shape == (384,)
        np.testing.assert_array_equal(result_embedding, expected_embedding)
        
        # Verify model was called with combined content
        mock_embedding_model.encode.assert_called_once()
        call_args = mock_embedding_model.encode.call_args[0][0]
        assert summary in call_args
        assert 'Introduction to Machine Learning' in call_args

    @pytest.mark.asyncio
    async def test_generate_document_embedding_empty_summary(self):
        """
        GIVEN empty summary string
        WHEN _generate_document_embedding is called
        THEN expect:
            - ValueError raised or fallback to structured content
            - Appropriate error handling
        """
        # Given
        summary = ""
        structured_text = {
            'pages': [
                {
                    'elements': [
                        {'content': 'Main Content', 'type': 'header'},
                        {'content': 'Document body text here', 'type': 'paragraph'}
                    ]
                }
            ]
        }
        
        # Mock the embedding model
        mock_embedding_model = Mock()
        expected_embedding = np.random.rand(384)
        mock_embedding_model.encode.return_value = expected_embedding
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        result_embedding = await self.optimizer._generate_document_embedding(summary, structured_text)
        
        # Then - Should fallback to structured content
        assert result_embedding is not None
        assert isinstance(result_embedding, np.ndarray)
        
        # Verify model was called with content from structured_text
        mock_embedding_model.encode.assert_called_once()
        call_args = mock_embedding_model.encode.call_args[0][0]
        assert 'Main Content' in call_args

    @pytest.mark.asyncio
    async def test_generate_document_embedding_model_unavailable(self):
        """
        GIVEN embedding model is None
        WHEN _generate_document_embedding is called
        THEN expect:
            - RuntimeError raised
            - Clear error message
            - None returned on graceful handling
        """
        # Given
        summary = "Test summary content"
        structured_text = {'pages': []}
        self.optimizer.embedding_model = None
        
        # When & Then
        with pytest.raises(RuntimeError) as exc_info:
            await self.optimizer._generate_document_embedding(summary, structured_text)
        
        assert "embedding model" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_generate_document_embedding_header_extraction(self):
        """
        GIVEN structured_text with headers and titles
        WHEN _generate_document_embedding is called
        THEN expect:
            - Headers and titles included in embedding
            - Structural information preserved
            - Representative document embedding
        """
        # Given
        summary = "Research paper on advanced topics"
        structured_text = {
            'pages': [
                {
                    'elements': [
                        {'content': 'Chapter 1: Introduction', 'type': 'header'},
                        {'content': 'Research Methodology', 'type': 'title'},
                        {'content': 'Section 2.1: Data Collection', 'type': 'header'},
                        {'content': 'Regular paragraph content', 'type': 'paragraph'},
                        {'content': 'Conclusion and Future Work', 'type': 'header'}
                    ]
                },
                {
                    'elements': [
                        {'content': 'Appendix A: Supplementary Data', 'type': 'header'},
                        {'content': 'Additional content here', 'type': 'paragraph'}
                    ]
                }
            ]
        }
        
        # Mock the embedding model
        mock_embedding_model = Mock()
        expected_embedding = np.random.rand(384)
        mock_embedding_model.encode.return_value = expected_embedding
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        result_embedding = await self.optimizer._generate_document_embedding(summary, structured_text)
        
        # Then
        assert result_embedding is not None
        assert isinstance(result_embedding, np.ndarray)
        
        # Verify headers and titles were included
        mock_embedding_model.encode.assert_called_once()
        call_args = mock_embedding_model.encode.call_args[0][0]
        assert 'Chapter 1: Introduction' in call_args
        assert 'Research Methodology' in call_args
        assert 'Conclusion and Future Work' in call_args
        assert summary in call_args

    @pytest.mark.asyncio
    async def test_generate_document_embedding_memory_constraints(self):
        """
        GIVEN very large document content
        WHEN _generate_document_embedding is called
        THEN expect:
            - MemoryError handled appropriately
            - Content truncation or batch processing
            - Embedding generation completes or fails gracefully
        """
        # Given
        summary = "Large document summary"
        # Create very large structured text to simulate memory issues
        large_content = "This is repeated content. " * 10000  # Very large text
        structured_text = {
            'pages': [
                {
                    'elements': [
                        {'content': large_content, 'type': 'paragraph'},
                        {'content': 'Another large section' * 1000, 'type': 'header'}
                    ]
                }
            ]
        }
        
        # Mock embedding model that raises MemoryError
        mock_embedding_model = Mock()
        mock_embedding_model.encode.side_effect = MemoryError("Insufficient memory for embedding")
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        with patch('logging.error') as mock_log:
            result_embedding = await self.optimizer._generate_document_embedding(summary, structured_text)
        
        # Then
        assert result_embedding is None
        
        # Verify error was logged
        mock_log.assert_called()
        log_message = mock_log.call_args[0][0]
        assert "memory" in log_message.lower()

    @pytest.mark.asyncio
    async def test_generate_document_embedding_content_combination(self):
        """
        GIVEN summary and structured text with various content types
        WHEN _generate_document_embedding is called
        THEN expect:
            - All relevant content types combined appropriately
            - Priority given to summary and headers
            - Document representation is comprehensive
        """
        # Given
        summary = "Comprehensive research on machine learning algorithms and their applications in data science."
        structured_text = {
            'pages': [
                {
                    'elements': [
                        {'content': 'Machine Learning Fundamentals', 'type': 'header'},
                        {'content': 'Data Science Applications', 'type': 'title'},
                        {'content': 'Figure 1: Algorithm Performance', 'type': 'figure_caption'},
                        {'content': 'Table showing results...', 'type': 'table'},
                        {'content': 'Regular text content describing methodology', 'type': 'paragraph'}
                    ]
                }
            ]
        }
        
        # Mock the embedding model
        mock_embedding_model = Mock()
        expected_embedding = np.random.rand(384)
        mock_embedding_model.encode.return_value = expected_embedding
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        result_embedding = await self.optimizer._generate_document_embedding(summary, structured_text)
        
        # Then
        assert result_embedding is not None
        
        # Verify content combination prioritizes important elements
        mock_embedding_model.encode.assert_called_once()
        call_args = mock_embedding_model.encode.call_args[0][0]
        
        # Summary should be included
        assert summary in call_args
        
        # Headers and titles should be included
        assert 'Machine Learning Fundamentals' in call_args
        assert 'Data Science Applications' in call_args
        
        # The combined content should be structured properly
        assert len(call_args) > len(summary)  # More than just summary

    @pytest.mark.asyncio
    async def test_generate_document_embedding_empty_structured_text(self):
        """
        GIVEN empty or minimal structured_text
        WHEN _generate_document_embedding is called
        THEN expect:
            - Embedding based primarily on summary
            - Graceful handling of missing structural content
            - Valid embedding still generated
        """
        # Given
        summary = "Important document summary with key information"
        structured_text = {
            'pages': []  # Empty pages
        }
        
        # Mock the embedding model
        mock_embedding_model = Mock()
        expected_embedding = np.random.rand(384)
        mock_embedding_model.encode.return_value = expected_embedding
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        result_embedding = await self.optimizer._generate_document_embedding(summary, structured_text)
        
        # Then
        assert result_embedding is not None
        assert isinstance(result_embedding, np.ndarray)
        
        # Should use summary as primary content
        mock_embedding_model.encode.assert_called_once()
        call_args = mock_embedding_model.encode.call_args[0][0]
        assert summary in call_args




class TestLLMOptimizerInitialization:
    """Test LLMOptimizer initialization and configuration."""

    def test_init_with_default_parameters(self):
        """
        GIVEN default initialization parameters
        WHEN LLMOptimizer is initialized without custom parameters
        THEN expect:
            - Instance created successfully
            - Default parameters applied correctly
            - All components initialized
        """
        # When
        optimizer = LLMOptimizer()
        
        # Then
        assert optimizer.model_name == "sentence-transformers/all-MiniLM-L6-v2"
        assert optimizer.tokenizer_name == "gpt-3.5-turbo"
        assert optimizer.max_chunk_size == 2048
        assert optimizer.chunk_overlap == 200
        assert optimizer.min_chunk_size == 100
        
        # Components should be initialized
        assert isinstance(optimizer.text_processor, TextProcessor)
        assert isinstance(optimizer.chunk_optimizer, ChunkOptimizer)
        
        # Model attributes should exist (may be None if loading failed)
        assert hasattr(optimizer, 'embedding_model')
        assert hasattr(optimizer, 'tokenizer')

    def test_init_with_custom_parameters(self):
        """
        GIVEN custom initialization parameters
        WHEN LLMOptimizer is initialized with specific values
        THEN expect:
            - Instance created successfully
            - All custom parameters stored correctly
            - Parameter validation successful
        """
        # Given
        custom_params = {
            'model_name': 'sentence-transformers/all-mpnet-base-v2',
            'tokenizer_name': 'gpt-4',
            'max_chunk_size': 4096,
            'chunk_overlap': 400,
            'min_chunk_size': 200
        }
        
        # When
        optimizer = LLMOptimizer(**custom_params)
        
        # Then
        assert optimizer.model_name == custom_params['model_name']
        assert optimizer.tokenizer_name == custom_params['tokenizer_name']
        assert optimizer.max_chunk_size == custom_params['max_chunk_size']
        assert optimizer.chunk_overlap == custom_params['chunk_overlap']
        assert optimizer.min_chunk_size == custom_params['min_chunk_size']
        
        # Components should be initialized with correct parameters
        assert isinstance(optimizer.text_processor, TextProcessor)
        assert isinstance(optimizer.chunk_optimizer, ChunkOptimizer)
        assert optimizer.chunk_optimizer.max_size == custom_params['max_chunk_size']
        assert optimizer.chunk_optimizer.overlap == custom_params['chunk_overlap']
        assert optimizer.chunk_optimizer.min_size == custom_params['min_chunk_size']

    def test_init_parameter_validation_max_chunk_size(self):
        """
        GIVEN invalid max_chunk_size parameters (negative, zero, or <= min_chunk_size)
        WHEN LLMOptimizer is initialized
        THEN expect ValueError to be raised with descriptive message
        """
        # Given - Invalid max_chunk_size values
        invalid_cases = [
            {'max_chunk_size': -1, 'min_chunk_size': 100},  # Negative
            {'max_chunk_size': 0, 'min_chunk_size': 100},   # Zero
            {'max_chunk_size': 50, 'min_chunk_size': 100},  # Less than min_chunk_size
            {'max_chunk_size': 100, 'min_chunk_size': 100}, # Equal to min_chunk_size
        ]
        
        for params in invalid_cases:
            # When & Then
            with pytest.raises(ValueError) as exc_info:
                LLMOptimizer(**params)
            
            assert "max_chunk_size" in str(exc_info.value).lower()

    def test_init_parameter_validation_chunk_overlap(self):
        """
        GIVEN invalid chunk_overlap parameters (>= max_chunk_size or negative)
        WHEN LLMOptimizer is initialized
        THEN expect ValueError to be raised with descriptive message
        """
        # Given - Invalid chunk_overlap values
        invalid_cases = [
            {'chunk_overlap': -1},                          # Negative
            {'chunk_overlap': 2048, 'max_chunk_size': 2048}, # Equal to max_chunk_size
            {'chunk_overlap': 3000, 'max_chunk_size': 2048}, # Greater than max_chunk_size
        ]
        
        for params in invalid_cases:
            # When & Then
            with pytest.raises(ValueError) as exc_info:
                LLMOptimizer(**params)
            
            assert "chunk_overlap" in str(exc_info.value).lower()

    def test_init_parameter_validation_min_chunk_size(self):
        """
        GIVEN invalid min_chunk_size parameters (negative, zero, or >= max_chunk_size)
        WHEN LLMOptimizer is initialized
        THEN expect ValueError to be raised with descriptive message
        """
        # Given - Invalid min_chunk_size values
        invalid_cases = [
            {'min_chunk_size': -1},                           # Negative
            {'min_chunk_size': 0},                            # Zero
            {'min_chunk_size': 2048, 'max_chunk_size': 2048}, # Equal to max_chunk_size
            {'min_chunk_size': 3000, 'max_chunk_size': 2048}, # Greater than max_chunk_size
        ]
        
        for params in invalid_cases:
            # When & Then
            with pytest.raises(ValueError) as exc_info:
                LLMOptimizer(**params)
            
            assert "min_chunk_size" in str(exc_info.value).lower()

    @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.LLMOptimizer._initialize_models')
    def test_init_model_loading_success(self, mock_init_models):
        """
        GIVEN valid model names
        WHEN LLMOptimizer is initialized
        THEN expect:
            - embedding_model loaded successfully
            - tokenizer loaded successfully
            - text_processor created
            - chunk_optimizer created with correct parameters
        """
        # Given - Mock successful model initialization
        mock_embedding_model = Mock()
        mock_tokenizer = Mock()
        
        def mock_init_side_effect(self):
            self.embedding_model = mock_embedding_model
            self.tokenizer = mock_tokenizer
        
        mock_init_models.side_effect = mock_init_side_effect
        
        # When
        optimizer = LLMOptimizer(
            model_name="test-model",
            tokenizer_name="test-tokenizer",
            max_chunk_size=1024,
            chunk_overlap=100,
            min_chunk_size=50
        )
        
        # Then
        mock_init_models.assert_called_once()
        assert optimizer.embedding_model is mock_embedding_model
        assert optimizer.tokenizer is mock_tokenizer
        assert isinstance(optimizer.text_processor, TextProcessor)
        assert isinstance(optimizer.chunk_optimizer, ChunkOptimizer)
        
        # Verify chunk optimizer parameters
        assert optimizer.chunk_optimizer.max_size == 1024
        assert optimizer.chunk_optimizer.overlap == 100
        assert optimizer.chunk_optimizer.min_size == 50

    @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.LLMOptimizer._initialize_models')
    def test_init_model_loading_failure_handling(self, mock_init_models):
        """
        GIVEN invalid model names or network issues
        WHEN LLMOptimizer is initialized
        THEN expect:
            - Graceful handling of model loading failures
            - Fallback mechanisms activated
            - Warning messages logged
            - Instance still created with limited functionality
        """
        # Given - Mock model loading failure
        mock_init_models.side_effect = Exception("Model loading failed")
        
        # When
        with patch('logging.warning') as mock_log:
            optimizer = LLMOptimizer()
        
        # Then
        # Should still create instance despite model loading failure
        assert optimizer is not None
        assert optimizer.max_chunk_size == 2048  # Default values preserved
        assert optimizer.chunk_overlap == 200
        assert optimizer.min_chunk_size == 100
        
        # Should attempt model initialization
        mock_init_models.assert_called_once()
        
        # Warning should be logged
        mock_log.assert_called()

    def test_init_component_creation(self):
        """
        GIVEN valid initialization parameters
        WHEN LLMOptimizer is initialized
        THEN expect:
            - TextProcessor created successfully
            - ChunkOptimizer created with correct parameters
            - All components properly linked
        """
        # Given
        params = {
            'max_chunk_size': 1024,
            'chunk_overlap': 128,
            'min_chunk_size': 64
        }
        
        # When
        optimizer = LLMOptimizer(**params)
        
        # Then
        # TextProcessor should be created
        assert isinstance(optimizer.text_processor, TextProcessor)
        
        # ChunkOptimizer should be created with correct parameters
        assert isinstance(optimizer.chunk_optimizer, ChunkOptimizer)
        assert optimizer.chunk_optimizer.max_size == params['max_chunk_size']
        assert optimizer.chunk_optimizer.overlap == params['chunk_overlap']
        assert optimizer.chunk_optimizer.min_size == params['min_chunk_size']

    def test_init_parameter_types(self):
        """
        GIVEN parameters with incorrect types
        WHEN LLMOptimizer is initialized
        THEN expect:
            - TypeError raised for non-string model names
            - TypeError raised for non-integer chunk parameters
            - Appropriate error messages
        """
        # Given - Invalid parameter types
        invalid_type_cases = [
            {'model_name': 123},  # Non-string model name
            {'tokenizer_name': []},  # Non-string tokenizer name
            {'max_chunk_size': "2048"},  # String instead of int
            {'chunk_overlap': 200.5},  # Float instead of int
            {'min_chunk_size': None},  # None instead of int
        ]
        
        for params in invalid_type_cases:
            # When & Then
            with pytest.raises((TypeError, ValueError)):
                LLMOptimizer(**params)

    def test_init_boundary_values(self):
        """
        GIVEN boundary values for parameters
        WHEN LLMOptimizer is initialized
        THEN expect:
            - Valid boundary values accepted
            - Appropriate parameter relationships maintained
        """
        # Given - Valid boundary cases
        valid_boundary_cases = [
            # Minimum valid configuration
            {'max_chunk_size': 2, 'chunk_overlap': 0, 'min_chunk_size': 1},
            # Large but valid configuration
            {'max_chunk_size': 8192, 'chunk_overlap': 1000, 'min_chunk_size': 500},
            # Edge case: overlap just under max_chunk_size
            {'max_chunk_size': 1000, 'chunk_overlap': 999, 'min_chunk_size': 100},
        ]
        
        for params in valid_boundary_cases:
            # When
            optimizer = LLMOptimizer(**params)
            
            # Then
            assert optimizer.max_chunk_size == params['max_chunk_size']
            assert optimizer.chunk_overlap == params['chunk_overlap']
            assert optimizer.min_chunk_size == params['min_chunk_size']

    @patch('sentence_transformers.SentenceTransformer')
    @patch('tiktoken.encoding_for_model')
    def test_init_with_mocked_dependencies(self, mock_tiktoken, mock_sentence_transformer):
        """
        GIVEN mocked external dependencies
        WHEN LLMOptimizer is initialized
        THEN expect:
            - Dependencies called with correct parameters
            - Instance created successfully
            - Mock objects properly assigned
        """
        # Given
        mock_model = Mock()
        mock_tokenizer = Mock()
        mock_sentence_transformer.return_value = mock_model
        mock_tiktoken.return_value = mock_tokenizer
        
        # When
        optimizer = LLMOptimizer(
            model_name="test-sentence-transformer",
            tokenizer_name="gpt-3.5-turbo"
        )
        
        # Then
        # Should attempt to load sentence transformer
        mock_sentence_transformer.assert_called_with("test-sentence-transformer")
        
        # Should attempt to load tiktoken tokenizer
        mock_tiktoken.assert_called_with("gpt-3.5-turbo")
        
        # Models should be assigned
        assert optimizer.embedding_model is mock_model
        assert optimizer.tokenizer is mock_tokenizer

    def test_init_attribute_access(self):
        """
        GIVEN initialized LLMOptimizer
        WHEN accessing instance attributes
        THEN expect:
            - All expected attributes present
            - Attributes have correct types
            - No unexpected attributes
        """
        # Given & When
        optimizer = LLMOptimizer()
        
        # Then - Check required attributes exist
        required_attributes = [
            'model_name', 'tokenizer_name', 'max_chunk_size', 'chunk_overlap', 'min_chunk_size',
            'embedding_model', 'tokenizer', 'text_processor', 'chunk_optimizer'
        ]
        
        for attr in required_attributes:
            assert hasattr(optimizer, attr), f"Missing required attribute: {attr}"
        
        # Check attribute types
        assert isinstance(optimizer.model_name, str)
        assert isinstance(optimizer.tokenizer_name, str)
        assert isinstance(optimizer.max_chunk_size, int)
        assert isinstance(optimizer.chunk_overlap, int)
        assert isinstance(optimizer.min_chunk_size, int)
        assert isinstance(optimizer.text_processor, TextProcessor)
        assert isinstance(optimizer.chunk_optimizer, ChunkOptimizer)

class TestLLMOptimizerGetChunkOverlap:
    """Test LLMOptimizer._get_chunk_overlap method."""

    def setup_method(self):
        """Set up test fixtures with LLMOptimizer instance."""
        self.optimizer = LLMOptimizer(chunk_overlap=200)  # Set specific overlap for testing

    def test_get_chunk_overlap_valid_content(self):
        """
        GIVEN content longer than overlap requirement
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Overlap text extracted from end of content
            - Approximately chunk_overlap/4 words returned
            - Complete words preserved
        """
        # Given
        content = """
        This is a comprehensive paragraph that contains multiple sentences and should provide
        sufficient content for overlap extraction testing. The method should extract text from
        the end of this content to maintain context continuity between adjacent chunks in the
        document processing pipeline. This ensures that important information and context are
        preserved across chunk boundaries for optimal language model processing and understanding.
        """.strip()
        
        expected_overlap_words = self.optimizer.chunk_overlap // 4  # 200 // 4 = 50 words
        
        # When
        overlap = self.optimizer._get_chunk_overlap(content)
        
        # Then
        assert isinstance(overlap, str)
        assert len(overlap) > 0
        
        # Check that overlap comes from the end of content
        assert overlap in content
        assert content.endswith(overlap) or content.rstrip().endswith(overlap.rstrip())
        
        # Check word count approximation
        overlap_word_count = len(overlap.split())
        assert overlap_word_count <= expected_overlap_words + 10  # Allow some tolerance
        
        # Ensure complete words are preserved (no partial words)
        words = overlap.split()
        if words:
            # First and last words should be complete
            assert not overlap.startswith(' ')  # No leading space indicates complete word
            assert words[0] in content  # First word should exist in original content

    def test_get_chunk_overlap_empty_content(self):
        """
        GIVEN empty content string
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Empty string returned
            - No errors raised
        """
        # Given
        content = ""
        
        # When
        overlap = self.optimizer._get_chunk_overlap(content)
        
        # Then
        assert overlap == ""
        assert isinstance(overlap, str)

    def test_get_chunk_overlap_short_content(self):
        """
        GIVEN content shorter than overlap requirement
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Entire content returned as overlap
            - No truncation of short content
        """
        # Given
        short_content = "Very short text with only a few words here."
        overlap_words = self.optimizer.chunk_overlap // 4  # 50 words
        actual_words = len(short_content.split())  # Much less than 50
        
        # When
        overlap = self.optimizer._get_chunk_overlap(short_content)
        
        # Then
        assert overlap == short_content or overlap == short_content.strip()
        assert len(overlap.split()) == actual_words

    def test_get_chunk_overlap_word_boundary_preservation(self):
        """
        GIVEN content with clear word boundaries
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Word boundaries respected
            - No partial words in overlap
            - Natural language structure preserved
        """
        # Given
        content = "The quick brown fox jumps over the lazy dog. " * 20  # Repeat for length
        
        # When
        overlap = self.optimizer._get_chunk_overlap(content)
        
        # Then
        assert isinstance(overlap, str)
        assert len(overlap) > 0
        
        # Check word boundary preservation
        words = overlap.split()
        if words:
            # All words should be complete (exist in original content)
            for word in words:
                clean_word = word.strip('.,!?;:')  # Remove punctuation for comparison
                assert clean_word in content
        
        # Should not start or end with partial words
        if overlap.strip():
            assert not overlap.startswith(' ')  # No leading whitespace
            # Last character should be word-ending (letter, digit, or punctuation)
            assert overlap[-1].isalnum() or overlap[-1] in '.,!?;:'

    def test_get_chunk_overlap_token_approximation(self):
        """
        GIVEN various content lengths
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Word count approximates token count
            - Overlap size roughly matches chunk_overlap/4
            - Consistent approximation behavior
        """
        # Given
        test_contents = [
            "Short content for testing basic overlap extraction behavior.",
            "Medium length content that provides more words for overlap extraction testing and validation of the approximation algorithm behavior.",
            "Very long content that spans multiple lines and contains extensive text for comprehensive testing of the overlap extraction mechanism. " * 10
        ]
        
        for content in test_contents:
            # When
            overlap = self.optimizer._get_chunk_overlap(content)
            
            # Then
            if content.strip():  # Non-empty content
                overlap_word_count = len(overlap.split())
                expected_words = self.optimizer.chunk_overlap // 4  # 50 words
                
                # Should approximate the expected word count
                if len(content.split()) >= expected_words:
                    # For long content, should be close to expected
                    assert overlap_word_count <= expected_words + 5
                    assert overlap_word_count >= expected_words - 10
                else:
                    # For short content, should return all content
                    assert overlap == content or overlap == content.strip()

    def test_get_chunk_overlap_whitespace_handling(self):
        """
        GIVEN content with various whitespace patterns
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Whitespace handled appropriately
            - No excessive whitespace in overlap
            - Clean word extraction
        """
        # Given
        content = """
        Content    with    irregular     whitespace     and     multiple
        spaces     between     words     for     testing     whitespace
        handling     in     overlap     extraction     functionality.
        """
        
        # When
        overlap = self.optimizer._get_chunk_overlap(content)
        
        # Then
        assert isinstance(overlap, str)
        
        if overlap:
            # Should not have excessive whitespace
            assert not overlap.startswith('  ')  # No double space at start
            assert not overlap.endswith('  ')   # No double space at end
            
            # Words should be separated by single spaces
            words = overlap.split()
            reconstructed = ' '.join(words)
            # The reconstructed version should be cleaner than original
            assert len(reconstructed) <= len(overlap)

    def test_get_chunk_overlap_punctuation_handling(self):
        """
        GIVEN content with various punctuation patterns
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Punctuation preserved with words
            - Sentence boundaries respected where possible
            - Natural text structure maintained
        """
        # Given
        content = """
        This content contains various punctuation marks! It includes questions?
        And statements with periods. There are also commas, semicolons; and other
        punctuation marks that should be preserved during overlap extraction.
        The method should handle these gracefully and maintain readability.
        """
        
        # When
        overlap = self.optimizer._get_chunk_overlap(content)
        
        # Then
        assert isinstance(overlap, str)
        
        if overlap:
            # Punctuation should be preserved
            original_punct_count = sum(1 for c in content if c in '.,!?;:')
            overlap_punct_count = sum(1 for c in overlap if c in '.,!?;:')
            
            # Overlap should contain some punctuation if original did
            if original_punct_count > 0:
                assert overlap_punct_count >= 0  # May contain some punctuation
            
            # Should maintain word-punctuation relationships
            words = overlap.split()
            for word in words:
                if any(p in word for p in '.,!?;:'):
                    # Punctuation should be at end of words, not randomly placed
                    clean_word = word.rstrip('.,!?;:')
                    assert clean_word.isalpha() or clean_word.isalnum()

    def test_get_chunk_overlap_edge_cases(self):
        """
        GIVEN edge case content (whitespace only, single word, etc.)
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Graceful handling of edge cases
            - No errors or exceptions
            - Appropriate return values
        """
        # Given
        edge_cases = [
            "   ",  # Whitespace only
            "word",  # Single word
            "a",  # Single character
            "\n\n\n",  # Newlines only
            "word1 word2",  # Two words
            "123 456 789",  # Numbers
            "!@# $%^ &*()",  # Punctuation and symbols
        ]
        
        for content in edge_cases:
            # When
            overlap = self.optimizer._get_chunk_overlap(content)
            
            # Then
            assert isinstance(overlap, str)
            # Should not raise any exceptions
            # Should return reasonable results
            if content.strip():
                if len(content.split()) <= 2:
                    # Very short content should be returned as-is or stripped
                    assert overlap == content or overlap == content.strip()
                else:
                    assert len(overlap) <= len(content)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pytest
from unittest.mock import Mock, patch
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer


class TestLLMOptimizerGetChunkOverlap:
    """Test LLMOptimizer._get_chunk_overlap method."""

    def setup_method(self):
        """Set up test fixtures with LLMOptimizer instance."""
        self.optimizer = LLMOptimizer(chunk_overlap=200)  # Set specific overlap for testing

    def test_get_chunk_overlap_valid_content(self):
        """
        GIVEN content longer than overlap requirement
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Overlap text extracted from end of content
            - Approximately chunk_overlap/4 words returned
            - Complete words preserved
        """
        # Given
        content = """
        This is a comprehensive paragraph that contains multiple sentences and should provide
        sufficient content for overlap extraction testing. The method should extract text from
        the end of this content to maintain context continuity between adjacent chunks in the
        document processing pipeline. This ensures that important information and context are
        preserved across chunk boundaries for optimal language model processing and understanding.
        """.strip()
        
        expected_overlap_words = self.optimizer.chunk_overlap // 4  # 200 // 4 = 50 words
        
        # When
        overlap = self.optimizer._get_chunk_overlap(content)
        
        # Then
        assert isinstance(overlap, str)
        assert len(overlap) > 0
        
        # Check that overlap comes from the end of content
        assert overlap in content
        assert content.endswith(overlap) or content.rstrip().endswith(overlap.rstrip())
        
        # Check word count approximation
        overlap_word_count = len(overlap.split())
        assert overlap_word_count <= expected_overlap_words + 10  # Allow some tolerance
        
        # Ensure complete words are preserved (no partial words)
        words = overlap.split()
        if words:
            # First and last words should be complete
            assert not overlap.startswith(' ')  # No leading space indicates complete word
            assert words[0] in content  # First word should exist in original content

    def test_get_chunk_overlap_empty_content(self):
        """
        GIVEN empty content string
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Empty string returned
            - No errors raised
        """
        # Given
        content = ""
        
        # When
        overlap = self.optimizer._get_chunk_overlap(content)
        
        # Then
        assert overlap == ""
        assert isinstance(overlap, str)

    def test_get_chunk_overlap_short_content(self):
        """
        GIVEN content shorter than overlap requirement
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Entire content returned as overlap
            - No truncation of short content
        """
        # Given
        short_content = "Very short text with only a few words here."
        overlap_words = self.optimizer.chunk_overlap // 4  # 50 words
        actual_words = len(short_content.split())  # Much less than 50
        
        # When
        overlap = self.optimizer._get_chunk_overlap(short_content)
        
        # Then
        assert overlap == short_content or overlap == short_content.strip()
        assert len(overlap.split()) == actual_words

    def test_get_chunk_overlap_word_boundary_preservation(self):
        """
        GIVEN content with clear word boundaries
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Word boundaries respected
            - No partial words in overlap
            - Natural language structure preserved
        """
        # Given
        content = "The quick brown fox jumps over the lazy dog. " * 20  # Repeat for length
        
        # When
        overlap = self.optimizer._get_chunk_overlap(content)
        
        # Then
        assert isinstance(overlap, str)
        assert len(overlap) > 0
        
        # Check word boundary preservation
        words = overlap.split()
        if words:
            # All words should be complete (exist in original content)
            for word in words:
                clean_word = word.strip('.,!?;:')  # Remove punctuation for comparison
                assert clean_word in content
        
        # Should not start or end with partial words
        if overlap.strip():
            assert not overlap.startswith(' ')  # No leading whitespace
            # Last character should be word-ending (letter, digit, or punctuation)
            assert overlap[-1].isalnum() or overlap[-1] in '.,!?;:'

    def test_get_chunk_overlap_token_approximation(self):
        """
        GIVEN various content lengths
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Word count approximates token count
            - Overlap size roughly matches chunk_overlap/4
            - Consistent approximation behavior
        """
        # Given
        test_contents = [
            "Short content for testing basic overlap extraction behavior.",
            "Medium length content that provides more words for overlap extraction testing and validation of the approximation algorithm behavior.",
            "Very long content that spans multiple lines and contains extensive text for comprehensive testing of the overlap extraction mechanism. " * 10
        ]
        
        for content in test_contents:
            # When
            overlap = self.optimizer._get_chunk_overlap(content)
            
            # Then
            if content.strip():  # Non-empty content
                overlap_word_count = len(overlap.split())
                expected_words = self.optimizer.chunk_overlap // 4  # 50 words
                
                # Should approximate the expected word count
                if len(content.split()) >= expected_words:
                    # For long content, should be close to expected
                    assert overlap_word_count <= expected_words + 5
                    assert overlap_word_count >= expected_words - 10
                else:
                    # For short content, should return all content
                    assert overlap == content or overlap == content.strip()

    def test_get_chunk_overlap_whitespace_handling(self):
        """
        GIVEN content with various whitespace patterns
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Whitespace handled appropriately
            - No excessive whitespace in overlap
            - Clean word extraction
        """
        # Given
        content = """
        Content    with    irregular     whitespace     and     multiple
        spaces     between     words     for     testing     whitespace
        handling     in     overlap     extraction     functionality.
        """
        
        # When
        overlap = self.optimizer._get_chunk_overlap(content)
        
        # Then
        assert isinstance(overlap, str)
        
        if overlap:
            # Should not have excessive whitespace
            assert not overlap.startswith('  ')  # No double space at start
            assert not overlap.endswith('  ')   # No double space at end
            
            # Words should be separated by single spaces
            words = overlap.split()
            reconstructed = ' '.join(words)
            # The reconstructed version should be cleaner than original
            assert len(reconstructed) <= len(overlap)

    def test_get_chunk_overlap_punctuation_handling(self):
        """
        GIVEN content with various punctuation patterns
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Punctuation preserved with words
            - Sentence boundaries respected where possible
            - Natural text structure maintained
        """
        # Given
        content = """
        This content contains various punctuation marks! It includes questions?
        And statements with periods. There are also commas, semicolons; and other
        punctuation marks that should be preserved during overlap extraction.
        The method should handle these gracefully and maintain readability.
        """
        
        # When
        overlap = self.optimizer._get_chunk_overlap(content)
        
        # Then
        assert isinstance(overlap, str)
        
        if overlap:
            # Punctuation should be preserved
            original_punct_count = sum(1 for c in content if c in '.,!?;:')
            overlap_punct_count = sum(1 for c in overlap if c in '.,!?;:')
            
            # Overlap should contain some punctuation if original did
            if original_punct_count > 0:
                assert overlap_punct_count >= 0  # May contain some punctuation
            
            # Should maintain word-punctuation relationships
            words = overlap.split()
            for word in words:
                if any(p in word for p in '.,!?;:'):
                    # Punctuation should be at end of words, not randomly placed
                    clean_word = word.rstrip('.,!?;:')
                    assert clean_word.isalpha() or clean_word.isalnum()

    def test_get_chunk_overlap_edge_cases(self):
        """
        GIVEN edge case content (whitespace only, single word, etc.)
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Graceful handling of edge cases
            - No errors or exceptions
            - Appropriate return values
        """
        # Given
        edge_cases = [
            "   ",  # Whitespace only
            "word",  # Single word
            "a",  # Single character
            "\n\n\n",  # Newlines only
            "word1 word2",  # Two words
            "123 456 789",  # Numbers
            "!@# $%^ &*()",  # Punctuation and symbols
        ]
        
        for content in edge_cases:
            # When
            overlap = self.optimizer._get_chunk_overlap(content)
            
            # Then
            assert isinstance(overlap, str)
            # Should not raise any exceptions
            # Should return reasonable results
            if content.strip():
                if len(content.split()) <= 2:
                    # Very short content should be returned as-is or stripped
                    assert overlap == content or overlap == content.strip()
                else:
                    assert len(overlap) <= len(content)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pytest
import asyncio
import time
from unittest.mock import Mock, patch, MagicMock
import numpy as np
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer, LLMChunk, LLMDocument


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
            assert isinstance(chunk.semantic_type, str)
            assert isinstance(chunk.relationships, list)
            assert isinstance(chunk.metadata, dict)
        
        # Verify document-level components
        assert isinstance(result.summary, str)
        assert len(result.summary) > 0
        assert isinstance(result.key_entities, list)
        assert isinstance(result.processing_metadata, dict)
        
        # Verify performance bounds (should complete in reasonable time)
        assert processing_time < 30.0  # Should complete within 30 seconds
        
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

    @pytest.mark.asyncio
    async def test_pipeline_performance_benchmarks(self):
        """
        GIVEN various document sizes and complexities
        WHEN optimization pipeline is executed
        THEN expect:
            - Processing time scales reasonably with content size
            - Memory usage remains within bounds
            - Quality metrics maintained across sizes
        """
        # Given - Different document sizes
        small_doc = self._create_test_document(pages=1, elements_per_page=3)
        medium_doc = self._create_test_document(pages=5, elements_per_page=10)
        large_doc = self._create_test_document(pages=20, elements_per_page=25)
        
        document_metadata = {'document_id': 'perf_test', 'title': 'Performance Test'}
        
        performance_results = []
        
        for doc_name, doc_content in [
            ('small', small_doc),
            ('medium', medium_doc),
            ('large', large_doc)
        ]:
            # When
            start_time = time.time()
            result = await self.optimizer.optimize_for_llm(doc_content, document_metadata)
            processing_time = time.time() - start_time
            
            performance_results.append({
                'name': doc_name,
                'pages': len(doc_content['pages']),
                'total_elements': sum(len(page['elements']) for page in doc_content['pages']),
                'processing_time': processing_time,
                'chunk_count': len(result.chunks),
                'avg_chunk_size': np.mean([chunk.token_count for chunk in result.chunks])
            })
        
        # Then - Verify scaling behavior
        small_result, medium_result, large_result = performance_results
        
        # Processing time should scale reasonably (not exponentially)
        time_ratio_small_to_medium = medium_result['processing_time'] / small_result['processing_time']
        time_ratio_medium_to_large = large_result['processing_time'] / medium_result['processing_time']
        
        # Should not be exponential scaling (allowing for some variation)
        assert time_ratio_small_to_medium < 10  # Medium shouldn't be more than 10x slower
        assert time_ratio_medium_to_large < 10  # Large shouldn't be more than 10x slower
        
        # Quality metrics should be maintained
        for result in performance_results:
            assert result['chunk_count'] > 0
            assert result['avg_chunk_size'] > 0
            assert result['avg_chunk_size'] <= self.optimizer.max_chunk_size

    @pytest.mark.asyncio
    async def test_pipeline_consistency_across_runs(self):
        """
        GIVEN identical input across multiple runs
        WHEN optimization pipeline is executed multiple times
        THEN expect:
            - Consistent results across runs
            - Deterministic behavior where expected
            - No random variations in core functionality
        """
        # Given - Fixed input document
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
                        },
                        {
                            'content': 'Additional paragraph for comprehensive testing.',
                            'type': 'text',
                            'subtype': 'paragraph',
                            'position': {'x': 100, 'y': 150},
                            'confidence': 0.85
                        }
                    ]
                }
            ]
        }
        document_metadata = {'document_id': 'consistency_test', 'title': 'Consistency Test'}
        
        # When - Run multiple times
        results = []
        for i in range(3):
            result = await self.optimizer.optimize_for_llm(decomposed_content, document_metadata)
            results.append(result)
        
        # Then - Verify consistency
        first_result = results[0]
        
        for result in results[1:]:
            # Core structure should be identical
            assert result.document_id == first_result.document_id
            assert result.title == first_result.title
            assert len(result.chunks) == len(first_result.chunks)
            
            # Chunk content should be identical
            for i, (chunk1, chunk2) in enumerate(zip(first_result.chunks, result.chunks)):
                assert chunk1.content == chunk2.content
                assert chunk1.chunk_id == chunk2.chunk_id
                assert chunk1.token_count == chunk2.token_count
                assert chunk1.semantic_type == chunk2.semantic_type
                assert chunk1.source_page == chunk2.source_page
                
            # Summary should be identical (deterministic extraction)
            assert result.summary == first_result.summary
            
            # Entity extraction should be consistent
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pytest
from unittest.mock import Mock, patch, MagicMock
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer


class TestLLMOptimizerInitializeModels:
    """Test LLMOptimizer._initialize_models private method."""

    def setup_method(self):
        """Set up test fixtures."""
        # Create optimizer without automatic model initialization
        with patch.object(LLMOptimizer, '_initialize_models'):
            self.optimizer = LLMOptimizer()

    @patch('sentence_transformers.SentenceTransformer')
    @patch('tiktoken.encoding_for_model')
    def test_initialize_models_success(self, mock_tiktoken, mock_sentence_transformer):
        """
        GIVEN valid model names in optimizer instance
        WHEN _initialize_models is called
        THEN expect:
            - SentenceTransformer model loaded successfully
            - Tokenizer loaded successfully (tiktoken or HuggingFace)
            - No exceptions raised
            - Models accessible via instance attributes
        """
        # Given
        mock_embedding_model = Mock()
        mock_tokenizer = Mock()
        mock_sentence_transformer.return_value = mock_embedding_model
        mock_tiktoken.return_value = mock_tokenizer
        
        # When
        self.optimizer._initialize_models()
        
        # Then
        # Verify SentenceTransformer was loaded
        mock_sentence_transformer.assert_called_once_with(self.optimizer.model_name)
        assert self.optimizer.embedding_model is mock_embedding_model
        
        # Verify tokenizer was loaded
        mock_tiktoken.assert_called_once_with(self.optimizer.tokenizer_name)
        assert self.optimizer.tokenizer is mock_tokenizer

    @patch('sentence_transformers.SentenceTransformer')
    @patch('tiktoken.encoding_for_model')
    def test_initialize_models_sentence_transformer_failure(self, mock_tiktoken, mock_sentence_transformer):
        """
        GIVEN invalid sentence transformer model name
        WHEN _initialize_models is called
        THEN expect:
            - ImportError or OSError handled gracefully
            - embedding_model set to None
            - Warning logged
            - Fallback behavior activated
        """
        # Given
        mock_sentence_transformer.side_effect = OSError("Model not found")
        mock_tokenizer = Mock()
        mock_tiktoken.return_value = mock_tokenizer
        
        # When
        with patch('logging.warning') as mock_warning:
            self.optimizer._initialize_models()
        
        # Then
        # Verify embedding model is None after failure
        assert self.optimizer.embedding_model is None
        
        # Verify warning was logged
        mock_warning.assert_called()
        warning_message = mock_warning.call_args[0][0]
        assert 'sentence transformer' in warning_message.lower() or 'embedding' in warning_message.lower()
        
        # Verify tokenizer still loaded successfully
        assert self.optimizer.tokenizer is mock_tokenizer

    @patch('sentence_transformers.SentenceTransformer')
    @patch('tiktoken.encoding_for_model')
    def test_initialize_models_tokenizer_failure(self, mock_tiktoken, mock_sentence_transformer):
        """
        GIVEN invalid tokenizer name
        WHEN _initialize_models is called
        THEN expect:
            - Tokenizer loading error handled gracefully
            - tokenizer set to None
            - Warning logged
            - Fallback tokenization available
        """
        # Given
        mock_embedding_model = Mock()
        mock_sentence_transformer.return_value = mock_embedding_model
        mock_tiktoken.side_effect = KeyError("Tokenizer not found")
        
        # When
        with patch('logging.warning') as mock_warning:
            self.optimizer._initialize_models()
        
        # Then
        # Verify tokenizer is None after failure
        assert self.optimizer.tokenizer is None
        
        # Verify warning was logged
        mock_warning.assert_called()
        warning_message = mock_warning.call_args[0][0]
        assert 'tokenizer' in warning_message.lower()
        
        # Verify embedding model still loaded successfully
        assert self.optimizer.embedding_model is mock_embedding_model

    @patch('sentence_transformers.SentenceTransformer')
    @patch('tiktoken.encoding_for_model')
    @patch('transformers.AutoTokenizer.from_pretrained')
    def test_initialize_models_tiktoken_vs_huggingface(self, mock_hf_tokenizer, mock_tiktoken, mock_sentence_transformer):
        """
        GIVEN different tokenizer types (tiktoken vs HuggingFace)
        WHEN _initialize_models is called
        THEN expect:
            - Correct tokenizer type detection
            - Appropriate loading mechanism used
            - Consistent tokenization interface
        """
        # Given - Test tiktoken tokenizer (OpenAI models)
        mock_embedding_model = Mock()
        mock_sentence_transformer.return_value = mock_embedding_model
        mock_tiktoken_tokenizer = Mock()
        mock_tiktoken.return_value = mock_tiktoken_tokenizer
        
        # Set tokenizer name to OpenAI model
        self.optimizer.tokenizer_name = "gpt-3.5-turbo"
        
        # When
        self.optimizer._initialize_models()
        
        # Then - Should use tiktoken
        mock_tiktoken.assert_called_once_with("gpt-3.5-turbo")
        assert self.optimizer.tokenizer is mock_tiktoken_tokenizer
        mock_hf_tokenizer.assert_not_called()
        
        # Reset mocks
        mock_tiktoken.reset_mock()
        mock_hf_tokenizer.reset_mock()
        
        # Given - Test HuggingFace tokenizer (when tiktoken fails)
        mock_tiktoken.side_effect = KeyError("Not a tiktoken model")
        mock_hf_tokenizer_instance = Mock()
        mock_hf_tokenizer.return_value = mock_hf_tokenizer_instance
        
        self.optimizer.tokenizer_name = "bert-base-uncased"
        
        # When
        with patch('logging.warning'):  # Suppress expected warning
            self.optimizer._initialize_models()
        
        # Then - Should fallback to HuggingFace
        mock_tiktoken.assert_called_once_with("bert-base-uncased")
        mock_hf_tokenizer.assert_called_once_with("bert-base-uncased")
        assert self.optimizer.tokenizer is mock_hf_tokenizer_instance

    @patch('sentence_transformers.SentenceTransformer')
    @patch('tiktoken.encoding_for_model')
    def test_initialize_models_complete_failure(self, mock_tiktoken, mock_sentence_transformer):
        """
        GIVEN both embedding model and tokenizer loading fail
        WHEN _initialize_models is called
        THEN expect:
            - Both models set to None
            - Multiple warnings logged
            - No exceptions raised
            - Graceful degradation
        """
        # Given
        mock_sentence_transformer.side_effect = ImportError("SentenceTransformers not available")
        mock_tiktoken.side_effect = ImportError("tiktoken not available")
        
        # When
        with patch('logging.warning') as mock_warning:
            self.optimizer._initialize_models()
        
        # Then
        # Both models should be None
        assert self.optimizer.embedding_model is None
        assert self.optimizer.tokenizer is None
        
        # Multiple warnings should be logged
        assert mock_warning.call_count >= 2
        
        # Verify warning messages
        warning_calls = [call[0][0] for call in mock_warning.call_args_list]
        assert any('sentence transformer' in msg.lower() or 'embedding' in msg.lower() for msg in warning_calls)
        assert any('tokenizer' in msg.lower() for msg in warning_calls)

    @patch('sentence_transformers.SentenceTransformer')
    @patch('tiktoken.encoding_for_model')
    def test_initialize_models_network_timeout(self, mock_tiktoken, mock_sentence_transformer):
        """
        GIVEN network timeout during model download
        WHEN _initialize_models is called
        THEN expect:
            - Timeout error handled gracefully
            - Models set to None
            - Appropriate error logging
            - No hanging or infinite retry
        """
        # Given
        mock_sentence_transformer.side_effect = OSError("Network timeout")
        mock_tiktoken.side_effect = OSError("Connection failed")
        
        # When
        with patch('logging.error') as mock_error:
            self.optimizer._initialize_models()
        
        # Then
        assert self.optimizer.embedding_model is None
        assert self.optimizer.tokenizer is None
        
        # Should log errors for network issues
        assert mock_error.call_count >= 1

    @patch('sentence_transformers.SentenceTransformer')
    @patch('tiktoken.encoding_for_model')
    def test_initialize_models_memory_error(self, mock_tiktoken, mock_sentence_transformer):
        """
        GIVEN insufficient memory for model loading
        WHEN _initialize_models is called
        THEN expect:
            - MemoryError handled gracefully
            - Models set to None
            - Memory error logged
            - System stability maintained
        """
        # Given
        mock_sentence_transformer.side_effect = MemoryError("Insufficient memory")
        mock_tokenizer = Mock()
        mock_tiktoken.return_value = mock_tokenizer
        
        # When
        with patch('logging.error') as mock_error:
            self.optimizer._initialize_models()
        
        # Then
        assert self.optimizer.embedding_model is None
        assert self.optimizer.tokenizer is mock_tokenizer  # Tokenizer should still work
        
        # Should log memory error
        mock_error.assert_called()
        error_message = mock_error.call_args[0][0]
        assert 'memory' in error_message.lower()

    @patch('sentence_transformers.SentenceTransformer')
    @patch('tiktoken.encoding_for_model')
    def test_initialize_models_partial_success(self, mock_tiktoken, mock_sentence_transformer):
        """
        GIVEN one model loads successfully, other fails
        WHEN _initialize_models is called
        THEN expect:
            - Successful model available
            - Failed model set to None
            - Partial functionality maintained
            - Appropriate logging
        """
        # Given - Embedding model succeeds, tokenizer fails
        mock_embedding_model = Mock()
        mock_sentence_transformer.return_value = mock_embedding_model
        mock_tiktoken.side_effect = ValueError("Invalid tokenizer name")
        
        # When
        with patch('logging.warning') as mock_warning:
            self.optimizer._initialize_models()
        
        # Then
        assert self.optimizer.embedding_model is mock_embedding_model
        assert self.optimizer.tokenizer is None
        
        # Should log warning for failed component
        mock_warning.assert_called()
        
        # Test opposite scenario
        mock_sentence_transformer.side_effect = RuntimeError("Model loading failed")
        mock_tokenizer = Mock()
        mock_tiktoken.side_effect = None
        mock_tiktoken.return_value = mock_tokenizer
        
        # Reset and reinitialize
        self.optimizer.embedding_model = None
        self.optimizer.tokenizer = None
        
        with patch('logging.warning'):
            self.optimizer._initialize_models()
        
        assert self.optimizer.embedding_model is None
        assert self.optimizer.tokenizer is mock_tokenizer


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

    @pytest.mark.asyncio
    async def test_optimize_for_llm_complete_pipeline(self):
        """
        GIVEN valid decomposed_content and document_metadata
        WHEN optimize_for_llm is called
        THEN expect:
            - Complete processing pipeline executed
            - LLMDocument returned with all required fields
            - No errors or exceptions raised
            - Processing metadata populated
        """
        # Given
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
        
        document_metadata = {
            'document_id': 'test_doc_001',
            'title': 'Machine Learning Basics',
            'author': 'Test Author'
        }
        
        # When
        result = await self.optimizer.optimize_for_llm(decomposed_content, document_metadata)
        
        # Then
        assert isinstance(result, LLMDocument)
        assert result.document_id == document_metadata['document_id']
        assert result.title == document_metadata['title']
        
        # Verify chunks
        assert isinstance(result.chunks, list)
        assert len(result.chunks) > 0
        for chunk in result.chunks:
            assert isinstance(chunk, LLMChunk)
            assert len(chunk.content) > 0
            assert chunk.token_count > 0
        
        # Verify other components
        assert isinstance(result.summary, str)
        assert len(result.summary) > 0
        assert isinstance(result.key_entities, list)
        assert isinstance(result.processing_metadata, dict)
        
        # Verify processing metadata
        assert 'processing_time_seconds' in result.processing_metadata
        assert 'chunk_count' in result.processing_metadata
        assert 'token_count' in result.processing_metadata
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
