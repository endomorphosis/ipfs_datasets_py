#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"

from datetime import datetime
import pytest
import os
from unittest.mock import Mock, patch, AsyncMock, MagicMock

import os
import pytest
import time
import numpy as np

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

work_dir = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py"
file_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/llm_optimizer.py")
md_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/llm_optimizer_stubs.md")

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


from ipfs_datasets_py.pdf_processing.llm_optimizer import ClassificationResult


def _mock_classify_entity(sentence, **kwargs):
    # Return different entities based on sentence content
    if 'ACME Corporation' in sentence:
        return ClassificationResult(entity=sentence, category='Organizations', confidence=0.85)
    elif 'john.smith@university.edu' in sentence:
        return ClassificationResult(entity=sentence, category='People', confidence=0.9)
    elif 'MIT researchers' in sentence:
        return ClassificationResult(entity=sentence, category='People', confidence=0.8)
    elif '12/25/2024' in sentence:
        return ClassificationResult(entity=sentence, category='Events', confidence=0.7)
    else:
        return ClassificationResult(entity=sentence, category='unclassified', confidence=0.0)


class TestLLMOptimizerExtractKeyEntities:
    """Test LLMOptimizer._extract_key_entities method."""

    def setup_method(self):
        """Set up test fixtures."""
        # Mock the SentenceTransformer
        self.embedding_model_mock = MagicMock()
        self.sentence_transformer_mock = MagicMock()
        self.sentence_transformer_mock.return_value = self.embedding_model_mock
        
        # Mock the tiktoken encoding
        self.tokenizer_mock = MagicMock()
        self.tiktoken_mock = MagicMock()
        self.tiktoken_mock.return_value = self.tokenizer_mock
        
        # Mock the OpenAI async client 
        self.async_client_mock = MagicMock()
        self.openai_client_mock = MagicMock()
        self.openai_client_mock.return_value = self.async_client_mock
        
        self.optimizer = LLMOptimizer(
            api_key='test-api-key',
            async_openai=self.async_client_mock,
            sentence_transformer=self.sentence_transformer_mock,
            tiktoken=self.tiktoken_mock,
        )

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
                    'full_text': 'Contact Dr. John Smith at john.smith@university.edu. The meeting is scheduled for 12/25/2024.'
                },
                {
                    'full_text': 'ACME Corporation will host the partnership meeting. MIT researchers conducted the study from January 2023 to March 2024.'
                }
            ]
        }
        
        # Mock the entity classification to return predictable results
        # Patch the entity classification method
        with patch.object(self.optimizer, '_get_entity_classification', side_effect=_mock_classify_entity):
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
        
        # Should detect people and organizations (now in separate sentences)
        assert 'People' in entity_types
        assert 'Organizations' in entity_types
        
        # Verify that entity text contains the full sentence (as per implementation)
        people_entities = [e for e in entities if e['type'] == 'People']
        org_entities = [e for e in entities if e['type'] == 'Organizations']
        
        assert len(people_entities) > 0
        assert len(org_entities) > 0
        
        # Check that entity text contains full sentences, not just entity phrases
        assert any('john.smith@university.edu' in entity['text'] for entity in people_entities)
        assert any('ACME Corporation' in entity['text'] for entity in org_entities)

    @pytest.mark.asyncio
    async def test_extract_key_entities_empty_content(self):
        """
        GIVEN structured_text with no extractable text
        WHEN _extract_key_entities is called
        THEN expect:
            - ValueError raised
        """
        # Given
        structured_text = {
            'pages': [
                {'full_text': ''},
                {'full_text': '   '},  # Only whitespace
            ]
        }
        
        # When & Then
        with pytest.raises(ValueError, match="No valid text content found for entity extraction"):
            await self.optimizer._extract_key_entities(structured_text)

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
                    'full_text': 'Date patterns: 12/25/2024, 2024-01-15, January 15, 2024. Email patterns: john@example.com, mary.jane@university.edu, admin@company.co.uk. Organization patterns: ACME Corporation, University of California, NASA, FBI.'
                }
            ]
        }
        
        # Mock the entity classification

        
        def mock_classify_entity(sentence, **kwargs):
            if 'Date patterns' in sentence:
                return ClassificationResult(entity=sentence, category='Events', confidence=0.7)
            elif 'Email patterns' in sentence:
                return ClassificationResult(entity=sentence, category='People', confidence=0.8)
            elif 'Organization patterns' in sentence:
                return ClassificationResult(entity=sentence, category='Organizations', confidence=0.85)
            else:
                return ClassificationResult(entity=sentence, category='unclassified', confidence=0.0)
        
        # Patch the entity classification method
        with patch.object(self.optimizer, '_get_entity_classification', side_effect=mock_classify_entity):
            # When
            entities = await self.optimizer._extract_key_entities(structured_text)
        
        # Then
        date_entities = [e for e in entities if 'Events' in e['type']]
        email_entities = [e for e in entities if 'People' in e['type']]
        org_entities = [e for e in entities if 'Organizations' in e['type']]
        
        # Verify entity types are detected
        assert len(date_entities) > 0
        assert len(email_entities) > 0
        assert len(org_entities) > 0
        
        # Verify entity texts contain expected patterns
        assert any('Date patterns' in e['text'] for e in date_entities)
        assert any('Email patterns' in e['text'] for e in email_entities)
        assert any('Organization patterns' in e['text'] for e in org_entities)

    @pytest.mark.asyncio
    async def test_extract_key_entities_confidence_scores_in_valid_range(self):
        """
        GIVEN various entity patterns
        WHEN _extract_key_entities is called
        THEN expect all confidence scores between 0.0 and 1.0
        """
        # Given
        structured_text = {
            'pages': [
                {
                    'full_text': 'Strong patterns: john.smith@university.edu, 12/25/2024, NASA. Weak patterns: something@something, 99/99/9999, ABC.'
                }
            ]
        }

        def mock_classify_entity(sentence, **kwargs):
            if 'university.edu' in sentence:
                return ClassificationResult(entity=sentence, category='Education', confidence=0.9)
            elif 'NASA' in sentence:
                return ClassificationResult(entity=sentence, category='Science and technology', confidence=0.85)
            else:
                return ClassificationResult(entity=sentence, category='unclassified', confidence=0.5)
        
        # Patch the entity classification method
        with patch.object(self.optimizer, '_get_entity_classification', side_effect=mock_classify_entity):
            # When
            entities = await self.optimizer._extract_key_entities(structured_text)
        
        # Then
        for entity in entities:
            assert 0.0 <= entity['confidence'] <= 1.0, \
                f"Confidence score out of range: {entity['confidence']} for entity {entity['text']}"

    @pytest.mark.asyncio
    async def test_extract_key_entities_returns_entities(self):
        """
        GIVEN various entity patterns
        WHEN _extract_key_entities is called
        THEN expect at least one entity returned
        """
        # Given
        structured_text = {
            'pages': [
                {
                    'full_text': 'Strong patterns: john.smith@university.edu, 12/25/2024, NASA. Weak patterns: something@something, 99/99/9999, ABC.'
                }
            ]
        }
        
        # Mock the entity classification method

        
        def mock_classify_entity(sentence, **kwargs):
            if 'university.edu' in sentence:
                return ClassificationResult(entity=sentence, category='Education', confidence=0.9)
            elif 'NASA' in sentence:
                return ClassificationResult(entity=sentence, category='Science and technology', confidence=0.85)
            else:
                return ClassificationResult(entity=sentence, category='unclassified', confidence=0.5)
        
        # Patch the entity classification method
        with patch.object(self.optimizer, '_get_entity_classification', side_effect=mock_classify_entity):
            # When
            entities = await self.optimizer._extract_key_entities(structured_text)
        
        # Then
        assert len(entities) > 0, \
            "Expected at least one entity to be extracted, but got none."

    @pytest.mark.asyncio
    async def test_extract_key_entities_strong_patterns_have_high_confidence(self):
        """
        GIVEN strong entity patterns like university emails
        WHEN _extract_key_entities is called
        THEN expect high confidence scores for strong patterns
        """
        # Given
        structured_text = {
            'pages': [
                {
                    'full_text': 'Strong patterns: john.smith@university.edu, 12/25/2024, NASA.'
                }
            ]
        }
        
        # Mock the entity classification method

        
        def mock_classify_entity(sentence, **kwargs):
            if 'university.edu' in sentence:
                return ClassificationResult(entity=sentence, category='Education', confidence=0.9)
            else:
                return ClassificationResult(entity=sentence, category='unclassified', confidence=0.5)
        
        # Patch the entity classification method
        with patch.object(self.optimizer, '_get_entity_classification', side_effect=mock_classify_entity):
            # When
            entities = await self.optimizer._extract_key_entities(structured_text)
        
        # Then
        education_entities = [e for e in entities if e['type'] == 'Education']
        assert len(education_entities) > 0
        for entity in education_entities:
            if 'university.edu' in entity['text']:
                assert entity['confidence'] > 0.5

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
        # Given - Create text with multiple short sentences to avoid 512 char limit
        structured_text = {
            'pages': [
                {'full_text': 'Company A Corporation partners with University B. Research conducted by scientists.'},
                {'full_text': 'Meeting scheduled for 01/15/2024. Contact admin@example.com for details.'},
                {'full_text': 'NASA announces new findings. MIT researchers publish results.'}
            ]
        }
        
        # Mock the entity classification method

        
        def mock_classify_entity(sentence, **kwargs):
            if 'Corporation' in sentence:
                return ClassificationResult(entity=sentence, category='Business', confidence=0.9)
            elif 'scientists' in sentence or 'researchers' in sentence:
                return ClassificationResult(entity=sentence, category='People', confidence=0.8)
            elif 'NASA' in sentence:
                return ClassificationResult(entity=sentence, category='Science and technology', confidence=0.85)
            elif '2024' in sentence:
                return ClassificationResult(entity=sentence, category='Events', confidence=0.7)
            else:
                return ClassificationResult(entity=sentence, category='unclassified', confidence=0.3)
        
        # Patch the entity classification method
        with patch.object(self.optimizer, '_get_entity_classification', side_effect=mock_classify_entity):
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
                    'full_text': 'Unicode emails: josé@universidad.es, müller@universität.de. International orgs: Société Générale, Toyota.'
                }
            ]
        }
        
        # Mock the entity classification method

        
        def mock_classify_entity(sentence, **kwargs):
            if 'josé@universidad' in sentence or 'müller@universität' in sentence:
                return ClassificationResult(entity=sentence, category='People', confidence=0.8)
            elif 'Société Générale' in sentence or 'Toyota' in sentence:
                return ClassificationResult(entity=sentence, category='Organizations', confidence=0.85)
            else:
                return ClassificationResult(entity=sentence, category='unclassified', confidence=0.3)
        
        # Patch the entity classification method
        with patch.object(self.optimizer, '_get_entity_classification', side_effect=mock_classify_entity):
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
        entity_texts = {entity['text'] for entity in entities}
        # At least some Unicode content should be preserved
        assert any(len(text.encode('utf-8')) > len(text) for text in entity_texts)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
