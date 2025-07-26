#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"

from datetime import datetime
import pytest
import os
import asyncio
import numpy as np
from unittest.mock import Mock, AsyncMock, patch
from pydantic import BaseModel

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

# Wikipedia categories from the docstring
CLASSIFICATIONS = {
    "Science and technology",
    "Engineering", 
    "Industry",
    "Language",
    "Government",
    "Education",
    "Nature",
    "Mass media",
    "People",
    "Military",
    "Energy",
    "Knowledge",
    "Life",
    "Organizations",
    "History",
    "Concepts",
    "Philosophy",
    "Food and drink",
    "Humanities",
    "World",
    "Geography",
    "Law",
    "Business",
    "Events",
    "Entertainment",
    "Culture",
    "Religion",
    "Ethics",
    "Sports",
    "Music",
    "Academic Disciplines",
    "Politics",
    "Economy",
    "Society",
    "Mathematics",
    "Policy",
    "Health"
}

class ClassificationResult(BaseModel):
    """Result of entity classification."""
    entity: str
    category: str
    confidence: float


# Check if each classes methods are accessible:
assert LLMOptimizer._initialize_models
assert LLMOptimizer.optimize_for_llm
assert LLMOptimizer._extract_structured_text
assert LLMOptimizer._generate_document_summary
assert LLMOptimizer._create_optimal_chunks
assert LLMOptimizer._create_chunk
assert LLMOptimizer._establish_chunk_relationships
assert LLMOptimizer._generate_embeddings
assert LLMOptimizer._get_entity_classification  # Updated method name
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


class TestLLMOptimizerGetEntityClassification:
    """Test LLMOptimizer._get_entity_classification method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.optimizer = LLMOptimizer()
        self.mock_openai_client = Mock()
        self.mock_openai_client.chat = Mock()
        self.mock_openai_client.chat.completions = Mock()
        self.mock_openai_client.chat.completions.create = AsyncMock()

    @pytest.mark.asyncio
    async def test_get_entity_classification_valid_sentence_business(self):
        """
        GIVEN a sentence about a business entity
        WHEN _get_entity_classification is called with valid OpenAI client
        THEN expect:
            - ClassificationResult returned
            - Category matches expected business classification
            - Confidence between 0.0 and 1.0
            - Entity field matches input sentence
        """
        # Given
        sentence = "Apple Inc. is a technology company"
        
        # Mock OpenAI response with log probabilities
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].logprobs = Mock()
        mock_response.choices[0].logprobs.content = [Mock()]
        mock_response.choices[0].logprobs.content[0].top_logprobs = [
            Mock(token="Business", logprob=-0.693),  # ln(0.5) ≈ -0.693
            Mock(token="Science and technology", logprob=-1.609),  # ln(0.2) ≈ -1.609
            Mock(token="Industry", logprob=-2.303)  # ln(0.1) ≈ -2.303
        ]
        mock_response.choices[0].message.content = "Business"
        
        self.mock_openai_client.chat.completions.create.return_value = mock_response
        
        # When
        result = await self.optimizer._get_entity_classification(
            sentence,
            openai_client=self.mock_openai_client
        )
        
        # Then
        assert isinstance(result, ClassificationResult)
        assert result.entity == sentence
        assert result.category == "Business"
        assert 0.0 <= result.confidence <= 1.0
        assert result.confidence > 0.4  # Should be reasonably confident

    @pytest.mark.asyncio
    async def test_get_entity_classification_empty_sentence_raises_valueerror(self):
        """
        GIVEN an empty sentence
        WHEN _get_entity_classification is called
        THEN expect ValueError to be raised
        """
        # Given
        sentence = ""
        
        # When & Then
        with pytest.raises(ValueError, match="text is empty"):
            await self.optimizer._get_entity_classification(
                sentence,
                openai_client=self.mock_openai_client
            )

    @pytest.mark.asyncio
    async def test_get_entity_classification_whitespace_only_sentence_raises_valueerror(self):
        """
        GIVEN a sentence with only whitespace
        WHEN _get_entity_classification is called
        THEN expect ValueError to be raised (due to no leading/trailing whitespace requirement)
        """
        # Given
        sentence = "   \t\n   "
        
        # When & Then
        with pytest.raises(ValueError):
            await self.optimizer._get_entity_classification(
                sentence,
                openai_client=self.mock_openai_client
            )

    @pytest.mark.asyncio
    async def test_get_entity_classification_too_long_sentence_raises_valueerror(self):
        """
        GIVEN a sentence longer than 512 characters
        WHEN _get_entity_classification is called
        THEN expect ValueError to be raised
        """
        # Given
        sentence = "A" * 513  # 513 characters, exceeds limit
        
        # When & Then
        with pytest.raises(ValueError, match="512 characters"):
            await self.optimizer._get_entity_classification(
                sentence,
                openai_client=self.mock_openai_client
            )

    @pytest.mark.asyncio
    async def test_get_entity_classification_none_openai_client_raises_valueerror(self):
        """
        GIVEN None as openai_client
        WHEN _get_entity_classification is called
        THEN expect ValueError to be raised
        """
        # Given
        sentence = "Apple Inc."
        
        # When & Then
        with pytest.raises(ValueError, match="openai client is not set"):
            await self.optimizer._get_entity_classification(
                sentence,
                openai_client=None
            )

    @pytest.mark.asyncio
    async def test_get_entity_classification_empty_classifications_raises_valueerror(self):
        """
        GIVEN empty classifications set
        WHEN _get_entity_classification is called
        THEN expect ValueError to be raised
        """
        # Given
        sentence = "Apple Inc."
        empty_classifications = set()
        
        # When & Then
        with pytest.raises(ValueError, match="categories is empty"):
            await self.optimizer._get_entity_classification(
                sentence,
                openai_client=self.mock_openai_client,
                classifications=empty_classifications
            )

    @pytest.mark.asyncio
    async def test_get_entity_classification_custom_classifications(self):
        """
        GIVEN custom classification categories
        WHEN _get_entity_classification is called
        THEN expect:
            - Classification from custom set only
            - Result category in provided classifications
            - Proper confidence scoring
        """
        # Given
        sentence = "Apple Inc."
        custom_classifications = {"Technology", "Food", "Transportation"}
        
        # Mock response favoring Technology
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].logprobs = Mock()
        mock_response.choices[0].logprobs.content = [Mock()]
        mock_response.choices[0].logprobs.content[0].top_logprobs = [
            Mock(token="Technology", logprob=-0.223),  # ln(0.8) ≈ -0.223
            Mock(token="Food", logprob=-2.303),  # ln(0.1) ≈ -2.303
        ]
        mock_response.choices[0].message.content = "Technology"
        
        self.mock_openai_client.chat.completions.create.return_value = mock_response
        
        # When
        result = await self.optimizer._get_entity_classification(
            sentence,
            openai_client=self.mock_openai_client,
            classifications=custom_classifications
        )
        
        # Then
        assert result.category in custom_classifications
        assert result.category == "Technology"
        assert result.entity == sentence
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_get_entity_classification_low_confidence_unclassified(self):
        """
        GIVEN a sentence that gets low confidence scores (below threshold)
        WHEN _get_entity_classification is called
        THEN expect:
            - "unclassified" category returned
            - Confidence of 0.0
            - Entity field preserved
        """
        # Given
        sentence = "Obscure entity that doesn't fit categories"
        
        # Mock response with all low probabilities (below ln(0.05) ≈ -2.996)
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].logprobs = Mock()
        mock_response.choices[0].logprobs.content = [Mock()]
        mock_response.choices[0].logprobs.content[0].top_logprobs = [
            Mock(token="Business", logprob=-4.0),  # Very low confidence
            Mock(token="Science and technology", logprob=-4.5),
            Mock(token="Education", logprob=-5.0)
        ]
        mock_response.choices[0].message.content = "unclassified"
        
        self.mock_openai_client.chat.completions.create.return_value = mock_response
        
        # When
        result = await self.optimizer._get_entity_classification(
            sentence,
            openai_client=self.mock_openai_client
        )
        
        # Then
        assert result.category == "unclassified"
        assert result.confidence == 0.0
        assert result.entity == sentence

    @pytest.mark.asyncio
    async def test_get_entity_classification_temperature_zero_deterministic(self):
        """
        GIVEN multiple calls with the same sentence
        WHEN _get_entity_classification is called with temperature=0.0
        THEN expect:
            - Consistent results across calls
            - OpenAI client called with temperature=0.0
            - Deterministic behavior
        """
        # Given
        sentence = "NASA space exploration program"
        
        # Mock consistent response
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].logprobs = Mock()
        mock_response.choices[0].logprobs.content = [Mock()]
        mock_response.choices[0].logprobs.content[0].top_logprobs = [
            Mock(token="Science and technology", logprob=-0.105),  # ln(0.9)
        ]
        mock_response.choices[0].message.content = "Science and technology"
        
        self.mock_openai_client.chat.completions.create.return_value = mock_response
        
        # When - Call multiple times
        result1 = await self.optimizer._get_entity_classification(
            sentence,
            openai_client=self.mock_openai_client
        )
        result2 = await self.optimizer._get_entity_classification(
            sentence,
            openai_client=self.mock_openai_client
        )
        
        # Then
        assert result1.category == result2.category
        assert result1.confidence == result2.confidence
        assert result1.entity == result2.entity
        
        # Verify temperature=0.0 was used
        call_args = self.mock_openai_client.chat.completions.create.call_args
        assert call_args[1]["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_get_entity_classification_timeout_handling(self):
        """
        GIVEN an OpenAI client that times out
        WHEN _get_entity_classification is called with custom timeout
        THEN expect asyncio.TimeoutError to be raised
        """
        # Given
        sentence = "Apple Inc."
        
        # Mock timeout
        self.mock_openai_client.chat.completions.create.side_effect = asyncio.TimeoutError()
        
        # When & Then
        with pytest.raises(asyncio.TimeoutError):
            await self.optimizer._get_entity_classification(
                sentence,
                openai_client=self.mock_openai_client,
                timeout=1
            )

    @pytest.mark.asyncio
    async def test_get_entity_classification_retry_mechanism(self):
        """
        GIVEN OpenAI API that fails initially but succeeds on retry
        WHEN _get_entity_classification is called with retries
        THEN expect:
            - Method to retry on failure
            - Success after retries
            - Proper result returned
        """
        # Given
        sentence = "Microsoft Corporation"
        
        # Mock response for successful retry
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].logprobs = Mock()
        mock_response.choices[0].logprobs.content = [Mock()]
        mock_response.choices[0].logprobs.content[0].top_logprobs = [
            Mock(token="Business", logprob=-0.223),
        ]
        mock_response.choices[0].message.content = "Business"
        
        # First call fails, second succeeds
        self.mock_openai_client.chat.completions.create.side_effect = [
            Exception("API Error"),
            mock_response
        ]
        
        # When
        result = await self.optimizer._get_entity_classification(
            sentence,
            openai_client=self.mock_openai_client,
            retries=3
        )
        
        # Then
        assert result.category == "Business"
        assert result.entity == sentence
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_get_entity_classification_max_retries_exceeded(self):
        """
        GIVEN OpenAI API that consistently fails
        WHEN _get_entity_classification is called with limited retries
        THEN expect RuntimeError about max retries exceeded
        """
        # Given
        sentence = "Apple Inc."
        
        # Mock consistent failure
        self.mock_openai_client.chat.completions.create.side_effect = Exception("Persistent API Error")
        
        # When & Then
        with pytest.raises(RuntimeError, match="max retries exceeded"):
            await self.optimizer._get_entity_classification(
                sentence,
                openai_client=self.mock_openai_client,
                retries=2
            )

    @pytest.mark.asyncio
    async def test_get_entity_classification_log_probability_conversion(self):
        """
        GIVEN OpenAI response with specific log probabilities
        WHEN _get_entity_classification is called
        THEN expect:
            - Correct conversion from log probability to confidence
            - Mathematical accuracy in probability calculation
            - Confidence reflects the log probability value
        """
        # Given
        sentence = "Harvard University"
        
        # Mock response with known log probability
        log_prob = -0.693  # ln(0.5) = -0.693, so confidence should be ≈0.5
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].logprobs = Mock()
        mock_response.choices[0].logprobs.content = [Mock()]
        mock_response.choices[0].logprobs.content[0].top_logprobs = [
            Mock(token="Education", logprob=log_prob),
        ]
        mock_response.choices[0].message.content = "Education"
        
        self.mock_openai_client.chat.completions.create.return_value = mock_response
        
        # When
        result = await self.optimizer._get_entity_classification(
            sentence,
            openai_client=self.mock_openai_client
        )
        
        # Then
        expected_confidence = np.exp(log_prob)  # e^(-0.693) ≈ 0.5
        assert result.category == "Education"
        assert abs(result.confidence - expected_confidence) < 0.01  # Allow small floating point error

    @pytest.mark.asyncio
    async def test_get_entity_classification_wikipedia_categories_default(self):
        """
        GIVEN no custom classifications provided
        WHEN _get_entity_classification is called
        THEN expect:
            - Default Wikipedia categories used
            - Result category in CLASSIFICATIONS set
            - All default categories available for classification
        """
        # Given
        sentence = "Python programming language"
        
        # Mock response favoring a Wikipedia category
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].logprobs = Mock()
        mock_response.choices[0].logprobs.content = [Mock()]
        mock_response.choices[0].logprobs.content[0].top_logprobs = [
            Mock(token="Science and technology", logprob=-0.105),
        ]
        mock_response.choices[0].message.content = "Science and technology"
        
        self.mock_openai_client.chat.completions.create.return_value = mock_response
        
        # When
        result = await self.optimizer._get_entity_classification(
            sentence,
            openai_client=self.mock_openai_client
            # No classifications parameter - should use defaults
        )
        
        # Then
        assert result.category in CLASSIFICATIONS
        assert result.category == "Science and technology"
        assert result.entity == sentence

    @pytest.mark.asyncio
    async def test_get_entity_classification_response_parsing_failure(self):
        """
        GIVEN malformed OpenAI response
        WHEN _get_entity_classification is called
        THEN expect RuntimeError about response parsing failure
        """
        # Given
        sentence = "Apple Inc."
        
        # Mock malformed response
        mock_response = Mock()
        mock_response.choices = []  # Empty choices - malformed
        
        self.mock_openai_client.chat.completions.create.return_value = mock_response
        
        # When & Then
        with pytest.raises(RuntimeError, match="response parsing fails"):
            await self.optimizer._get_entity_classification(
                sentence,
                openai_client=self.mock_openai_client
            )

    @pytest.mark.asyncio
    async def test_get_entity_classification_type_validation(self):
        """
        GIVEN invalid argument types
        WHEN _get_entity_classification is called
        THEN expect TypeError to be raised
        """
        # Given & When & Then - Test invalid sentence type
        with pytest.raises(TypeError):
            await self.optimizer._get_entity_classification(
                123,  # Invalid type - should be string
                openai_client=self.mock_openai_client
            )
        
        # Test invalid classifications type
        with pytest.raises(TypeError):
            await self.optimizer._get_entity_classification(
                "Apple Inc.",
                openai_client=self.mock_openai_client,
                classifications="invalid"  # Should be set, not string
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])