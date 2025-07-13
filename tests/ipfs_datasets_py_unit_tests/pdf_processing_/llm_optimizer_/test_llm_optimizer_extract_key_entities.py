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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
