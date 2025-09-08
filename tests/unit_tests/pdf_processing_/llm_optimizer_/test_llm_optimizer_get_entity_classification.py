#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"

from datetime import datetime
import pytest
import os
import asyncio
import numpy as np
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pydantic import BaseModel
import math


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
    LLMDocument,
    ClassificationResult
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
    import openai

    import tiktoken
    from transformers import AutoTokenizer
    import numpy as np
    from sentence_transformers import SentenceTransformer
except ImportError as e:
    raise ImportError(f"Failed to import necessary modules: {e}")


def _make_mock_openai_client():
    mock_openai_client = MagicMock(spec=openai.AsyncOpenAI)
    mock_openai_client.chat = MagicMock()
    mock_openai_client.chat.completions = MagicMock()
    mock_openai_client.chat.completions.create = AsyncMock()
    return mock_openai_client


def _make_mock_choices():
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].logprobs = Mock()
    mock_response.choices[0].logprobs.content = [Mock()]
    return mock_response

class TestLLMOptimizerGetEntityClassificationHappyPath:
    """Test LLMOptimizer._get_entity_classification method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_openai_client = _make_mock_openai_client()

        self.optimizer = LLMOptimizer(
            api_key='fake-api-key',
            sentence_transformer=MagicMock(),
            async_openai = self.mock_openai_client,
        )
        self.mock_response = _make_mock_choices()

        # Mock OpenAI response
        self.mock_response.choices[0].logprobs.content[0].top_logprobs = [
            Mock(token="Business", logprob=-0.693),
        ]
        self.mock_response.choices[0].message.content = "Business"
        self.mock_openai_client.chat.completions.create.return_value = self.mock_response

    @pytest.mark.asyncio
    async def test_get_entity_classification_returns_classification_result(self):
        """
        GIVEN a valid sentence about a business entity
        WHEN _get_entity_classification is called
        THEN expect ClassificationResult instance returned
        """
        # Given
        sentence = "Apple Inc. is a technology company"

        # When
        result = await self.optimizer._get_entity_classification(
            sentence, openai_client=self.mock_openai_client
        )
        
        # Then
        assert isinstance(result, ClassificationResult), f"Expected ClassificationResult instance, got {type(result)}"

    @pytest.mark.asyncio
    async def test_get_entity_classification_preserves_entity_field(self):
        """
        GIVEN a sentence about a business entity
        WHEN _get_entity_classification is called
        THEN expect entity field matches input sentence
        """
        # Given
        sentence = "Apple Inc. is a technology company"

        # When
        result = await self.optimizer._get_entity_classification(
            sentence, openai_client=self.mock_openai_client
        )

        # Then
        assert result.entity == sentence, f"Expected entity '{sentence}', got '{result.entity}'"

    @pytest.mark.asyncio
    async def test_get_entity_classification_returns_expected_category(self):
        """
        GIVEN a sentence about a business entity
        WHEN _get_entity_classification is called
        THEN expect category matches expected business classification
        """
        # Given
        sentence = "Apple Inc. is a technology company"

        # When
        result = await self.optimizer._get_entity_classification(
            sentence, openai_client=self.mock_openai_client
        )

        # Then
        assert result.category == "Business", f"Expected category 'Business', got '{result.category}'"

    @pytest.mark.asyncio
    async def test_get_entity_classification_confidence_in_valid_range(self):
        """
        GIVEN a sentence about a business entity
        WHEN _get_entity_classification is called
        THEN expect confidence between 0.0 and 1.0
        """
        # Given
        sentence = "Apple Inc. is a technology company"

        # When
        result = await self.optimizer._get_entity_classification(
            sentence, openai_client=self.mock_openai_client
        )
        
        # Then
        assert 0.0 <= result.confidence <= 1.0, f"Expected confidence between 0.0 and 1.0, got {result.confidence}"

    @pytest.mark.asyncio
    async def test_get_entity_classification_confidence_reasonably_high(self):
        """
        GIVEN a sentence about a business entity with good log probability
        WHEN _get_entity_classification is called
        THEN expect confidence to be reasonably high
        """
        # Given
        sentence = "Apple Inc. is a technology company"

        # When
        result = await self.optimizer._get_entity_classification(
            sentence, openai_client=self.mock_openai_client
        )
        
        # Then
        EXPECTED_CONFIDENCE = 0.4
        assert result.confidence > EXPECTED_CONFIDENCE, f"Expected confidence > {EXPECTED_CONFIDENCE}, got {result.confidence}"

class TestLLMOptimizerGetEntityClassificationBadInputs:

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_openai_client = _make_mock_openai_client()

        self.optimizer = LLMOptimizer(
            api_key='fake-api-key',
            sentence_transformer=MagicMock(),
            async_openai = self.mock_openai_client,
        )
        self.mock_response = _make_mock_choices()

        # Mock OpenAI response
        self.mock_response.choices[0].logprobs.content[0].top_logprobs = [
            Mock(token="Business", logprob=-0.693),
        ]
        self.mock_response.choices[0].message.content = "Business"
        self.mock_openai_client.chat.completions.create.return_value = self.mock_response

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
        openai_client = None

        # When & Then
        with pytest.raises(ValueError, match="openai client is not set"):
            await self.optimizer._get_entity_classification(
                sentence, openai_client=openai_client
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
                sentence, openai_client=self.mock_openai_client,
                classifications=empty_classifications
            )


class TestLLMOptimizerGetEntityClassificationCustomClassifications:

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_openai_client = _make_mock_openai_client()

        self.optimizer = LLMOptimizer(
            api_key='fake-api-key',
            sentence_transformer=MagicMock(),
            async_openai = self.mock_openai_client,
        )
        self.mock_response = _make_mock_choices()

        # Mock response favoring Technology
        self.mock_response.choices[0].logprobs.content[0].top_logprobs = [
            Mock(token="Technology", logprob=-0.223),  # ln(0.8) ≈ -0.223
            Mock(token="Food", logprob=-2.303),  # ln(0.1) ≈ -2.303
        ]
        self.mock_response.choices[0].message.content = "Technology"
        self.mock_openai_client.chat.completions.create.return_value = self.mock_response

    @pytest.mark.asyncio
    async def test_get_entity_classification_custom_classifications_result_in_custom_set(self):
        """
        GIVEN custom classification categories
        WHEN _get_entity_classification is called
        THEN expect result category in provided classifications
        """
        # Given
        sentence = "Apple Inc."
        custom_classifications = {"Technology", "Food", "Transportation"}

        # When
        result = await self.optimizer._get_entity_classification(
            sentence, openai_client=self.mock_openai_client,
            classifications=custom_classifications
        )

        # Then
        assert result.category in custom_classifications

    @pytest.mark.asyncio
    async def test_get_entity_classification_custom_classifications_returns_expected_category(self):
        """
        GIVEN custom classification categories
        WHEN _get_entity_classification is called
        THEN expect specific category returned
        """
        # Given
        sentence = "Apple Inc."
        custom_classifications = {"Technology", "Food", "Transportation"}

        # When
        result = await self.optimizer._get_entity_classification(
            sentence, openai_client=self.mock_openai_client,
            classifications=custom_classifications
        )
        
        # Then
        assert result.category == "Technology"

    @pytest.mark.asyncio
    async def test_get_entity_classification_custom_classifications_preserves_entity(self):
        """
        GIVEN custom classification categories
        WHEN _get_entity_classification is called
        THEN expect entity field preserved
        """
        # Given
        sentence = "Apple Inc."
        custom_classifications = {"Technology", "Food", "Transportation"}

        # When
        result = await self.optimizer._get_entity_classification(
            sentence, openai_client=self.mock_openai_client,
            classifications=custom_classifications
        )
        
        # Then
        assert result.entity == sentence

    @pytest.mark.asyncio
    async def test_get_entity_classification_custom_classifications_confidence_in_valid_range(self):
        """
        GIVEN custom classification categories
        WHEN _get_entity_classification is called
        THEN expect confidence in valid range
        """
        # Given
        sentence = "Apple Inc."
        custom_classifications = {"Technology", "Food", "Transportation"}

        # When
        result = await self.optimizer._get_entity_classification(
            sentence, openai_client=self.mock_openai_client,
            classifications=custom_classifications
        )
        
        # Then
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
        sentence = "I've got a bag full of crabs here!"
        
        # Mock response with all low probabilities (below ln(0.05) ≈ -2.996)
        self.mock_response.choices[0].logprobs.content[0].top_logprobs = [
            Mock(token="Business", logprob=-4.0),  # Very low confidence
            Mock(token="Science and technology", logprob=-4.5),
            Mock(token="Education", logprob=-5.0)
        ]
        self.mock_response.choices[0].message.content = "unclassified"
        
        self.mock_openai_client.chat.completions.create.return_value = self.mock_response
        
        # When
        result = await self.optimizer._get_entity_classification(
            sentence,
            openai_client=self.mock_openai_client
        )
        
        # Then
        assert result.category == "unclassified"
        assert result.confidence == 0.0
        assert result.entity == sentence


class TestLLMOptimizerGetEntityClassificationDeterministicBehavior:

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_openai_client = _make_mock_openai_client()

        self.optimizer = LLMOptimizer(
            api_key='fake-api-key',
            sentence_transformer=MagicMock(),
            async_openai = self.mock_openai_client,
        )
        self.mock_response = _make_mock_choices()

        # Mock consistent response
        self.mock_response.choices[0].logprobs.content[0].top_logprobs = [
            Mock(token="Science and technology", logprob=-0.105),  # ln(0.9)
        ]
        self.mock_response.choices[0].message.content = "Science and technology"
        self.mock_openai_client.chat.completions.create.return_value = self.mock_response

    @pytest.mark.asyncio
    async def test_get_entity_classification_consistent_category_across_calls(self):
        """
        GIVEN multiple calls with the same sentence
        WHEN _get_entity_classification is called with temperature=0.0
        THEN expect consistent category across calls
        """
        # Given
        sentence = "NASA space exploration program"

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

    @pytest.mark.asyncio
    async def test_get_entity_classification_consistent_confidence_across_calls(self):
        """
        GIVEN multiple calls with the same sentence
        WHEN _get_entity_classification is called with temperature=0.0
        THEN expect consistent confidence across calls
        """
        # Given
        sentence = "NASA space exploration program"

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
        assert result1.confidence == result2.confidence

    @pytest.mark.asyncio
    async def test_get_entity_classification_consistent_entity_across_calls(self):
        """
        GIVEN multiple calls with the same sentence
        WHEN _get_entity_classification is called with temperature=0.0
        THEN expect consistent entity across calls
        """
        # Given
        sentence = "NASA space exploration program"

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
        assert result1.entity == result2.entity

    @pytest.mark.asyncio
    async def test_get_entity_classification_uses_temperature_zero(self):
        """
        GIVEN a call to _get_entity_classification
        WHEN the method is called
        THEN expect OpenAI client called with temperature=0.0
        """
        # Given
        sentence = "NASA space exploration program"

        # When
        await self.optimizer._get_entity_classification(
            sentence,
            openai_client=self.mock_openai_client
        )
        
        # Then
        call_args = self.mock_openai_client.chat.completions.create.call_args
        assert call_args[1]["temperature"] == 0.0


class TestLLMOptimizerGetEntityClassificationTimeoutsAndRetries:


    def setup_method(self):
        """Set up test fixtures."""
        self.mock_openai_client = _make_mock_openai_client()

        self.optimizer = LLMOptimizer(
            api_key='fake-api-key',
            sentence_transformer=MagicMock(),
            async_openai = self.mock_openai_client,
        )
        self.mock_response = _make_mock_choices()

        self.mock_response.choices[0].logprobs.content[0].top_logprobs = [
            Mock(token="Business", logprob=-0.223),
        ]
        self.mock_response.choices[0].message.content = "Business"


    @pytest.mark.asyncio
    async def test_get_entity_classification_timeout_handling(self):
        """
        GIVEN an OpenAI client that times out
        WHEN _get_entity_classification is called with custom timeout
        THEN expect asyncio.TimeoutError to be raised
        """
        # Given
        sentence = "Apple Inc."
        timeout = 1
        
        # Mock timeout
        self.mock_openai_client.chat.completions.create.side_effect = asyncio.TimeoutError()
        
        # When & Then
        with pytest.raises(asyncio.TimeoutError):
            await self.optimizer._get_entity_classification(
                sentence, openai_client=self.mock_openai_client, timeout=timeout
            )

    @pytest.mark.asyncio
    async def test_get_entity_classification_retry_mechanism_returns_expected_category(self):
        """
        GIVEN OpenAI API that fails initially but succeeds on retry
        WHEN _get_entity_classification is called with retries
        THEN expect correct category returned after retry
        """
        # Given
        sentence = "Microsoft Corporation"
        retries = 3

        # First call fails, second succeeds
        self.mock_openai_client.chat.completions.create.side_effect = [
            Exception("API Error"), self.mock_response
        ]
        
        # When
        result = await self.optimizer._get_entity_classification(
            sentence, openai_client=self.mock_openai_client, retries=retries
        )
        
        # Then
        assert result.category == "Business", \
            f"Expected category 'Business' after retry, got '{result.category}'"

    @pytest.mark.asyncio
    async def test_get_entity_classification_retry_mechanism_preserves_entity(self):
        """
        GIVEN OpenAI API that fails initially but succeeds on retry
        WHEN _get_entity_classification is called with retries
        THEN expect entity field preserved after retry
        """
        # Given
        sentence = "Microsoft Corporation"
        retries = 3

        # First call fails, second succeeds
        self.mock_openai_client.chat.completions.create.side_effect = [
            Exception("API Error"),
            self.mock_response
        ]
        
        # When
        result = await self.optimizer._get_entity_classification(
            sentence, openai_client=self.mock_openai_client, retries=retries
        )
        
        # Then
        assert result.entity == sentence, \
            f"Expected entity '{sentence}' to be preserved after retry, got '{result.entity}'"

    @pytest.mark.asyncio
    async def test_get_entity_classification_retry_mechanism_confidence_in_valid_range(self):
        """
        GIVEN OpenAI API that fails initially but succeeds on retry
        WHEN _get_entity_classification is called with retries
        THEN expect confidence in valid range after retry
        """
        # Given
        sentence = "Microsoft Corporation"
        retries = 3

        # First call fails, second succeeds
        self.mock_openai_client.chat.completions.create.side_effect = [
            Exception("API Error"),
            self.mock_response
        ]
        
        # When
        result = await self.optimizer._get_entity_classification(
            sentence, openai_client=self.mock_openai_client, retries=retries
        )
        
        # Then
        assert 0.0 <= result.confidence <= 1.0, \
            f"Expected confidence between 0.0 and 1.0 after retry, got {result.confidence}"

    @pytest.mark.asyncio
    async def test_get_entity_classification_max_retries_exceeded(self):
        """
        GIVEN OpenAI API that consistently fails
        WHEN _get_entity_classification is called with limited retries
        THEN expect RuntimeError about max retries exceeded
        """
        # Given
        sentence = "Apple Inc."
        retries = 2
        
        # Mock consistent failure
        self.mock_openai_client.chat.completions.create.side_effect = Exception("Persistent API Error")
        
        # When & Then
        with pytest.raises(RuntimeError):
            await self.optimizer._get_entity_classification(
                sentence,
                openai_client=self.mock_openai_client,
                retries=retries
            )

class TestLLMOptimizerGetEntityClassificationLogProbabilityConversion:


    def setup_method(self):
        """Set up test fixtures."""
        self.mock_openai_client = _make_mock_openai_client()

        self.optimizer = LLMOptimizer(
            api_key='fake-api-key',
            sentence_transformer=MagicMock(),
            async_openai = self.mock_openai_client,
        )
        self.mock_response = _make_mock_choices()

        # Mock response with known log probability
        self.log_prob = math.log(0.5)  # ln(0.5) = -0.693, so confidence should be ≈0.5
        self.mock_response.choices[0].logprobs.content[0].top_logprobs = [
            Mock(token="Education", logprob=self.log_prob),
        ]
        self.mock_response.choices[0].message.content = "Education"
        
        self.mock_openai_client.chat.completions.create.return_value = self.mock_response


    @pytest.mark.asyncio
    async def test_get_entity_classification_log_probability_conversion_accuracy(self):
        """
        GIVEN OpenAI response with specific log probabilities
        WHEN _get_entity_classification is called
        THEN expect correct conversion from log probability to confidence
        """
        # Given
        sentence = "Harvard University"

        # When
        result = await self.optimizer._get_entity_classification(
            sentence, openai_client=self.mock_openai_client
        )
        
        # Then
        tolerance = 0.01  # Allow small floating point error
        expected_confidence = math.exp(self.log_prob)  # e^(log_prob)
        assert abs(result.confidence - expected_confidence) < tolerance, \
            f"Expected confidence {expected_confidence} ± {tolerance}, got {result.confidence}"

    @pytest.mark.asyncio
    async def test_get_entity_classification_log_probability_conversion_category(self):
        """
        GIVEN OpenAI response with specific log probabilities
        WHEN _get_entity_classification is called
        THEN expect correct category returned
        """
        # Given
        sentence = "Harvard University"

        # When
        result = await self.optimizer._get_entity_classification(
            sentence,
            openai_client=self.mock_openai_client
        )
        
        # Then
        assert result.category == "Education", f"Expected category 'Education', got '{result.category}'"

    @pytest.mark.asyncio
    async def test_get_entity_classification_log_probability_confidence_reflects_probability(self):
        """
        GIVEN OpenAI response with specific log probabilities
        WHEN _get_entity_classification is called
        THEN expect confidence reflects the log probability value mathematically
        """
        # Given
        sentence = "Harvard University"

        # When
        result = await self.optimizer._get_entity_classification(
            sentence,
            openai_client=self.mock_openai_client
        )
        
        # Then
        # Confidence should be the exponential of the log probability
        expected_confidence = math.exp(self.log_prob)
        assert result.confidence == expected_confidence, \
            f"Expected confidence {expected_confidence} (exp({self.log_prob})), got {result.confidence}"




class TestLLMOptimizerGetEntityClassificationWikipediaCategoriesDefault:


    def setup_method(self):
        """Set up test fixtures."""
        self.mock_openai_client = _make_mock_openai_client()

        self.optimizer = LLMOptimizer(
            api_key='fake-api-key',
            sentence_transformer=MagicMock(),
            async_openai = self.mock_openai_client,
        )
        self.mock_response = _make_mock_choices()

        self.mock_response.choices[0].logprobs.content[0].top_logprobs = [
            Mock(token="Science and technology", logprob=-0.105),
        ]
        self.mock_response.choices[0].message.content = "Science and technology"
        self.mock_openai_client.chat.completions.create.return_value = self.mock_response

    @pytest.mark.asyncio
    async def test_get_entity_classification_wikipedia_categories_default_uses_default_categories(self):
        """
        GIVEN no custom classifications provided
        WHEN _get_entity_classification is called
        THEN expect result category in default CLASSIFICATIONS set
        """
        # Given
        sentence = "Python programming language"

        # When
        result = await self.optimizer._get_entity_classification(
            sentence,
            openai_client=self.mock_openai_client
        )

        # Then
        assert result.category in CLASSIFICATIONS

    @pytest.mark.asyncio
    async def test_get_entity_classification_wikipedia_categories_default_returns_expected_category(self):
        """
        GIVEN no custom classifications provided
        WHEN _get_entity_classification is called
        THEN expect specific expected category returned
        """
        # Given
        sentence = "Python programming language"

        # When
        result = await self.optimizer._get_entity_classification(
            sentence,
            openai_client=self.mock_openai_client
        )
        
        # Then
        assert result.category == "Science and technology"

    @pytest.mark.asyncio
    async def test_get_entity_classification_wikipedia_categories_default_preserves_entity(self):
        """
        GIVEN no custom classifications provided
        WHEN _get_entity_classification is called
        THEN expect entity field preserved in result
        """
        # Given
        sentence = "Python programming language"

        # When
        result = await self.optimizer._get_entity_classification(
            sentence,
            openai_client=self.mock_openai_client
        )
        
        # Then
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
        with pytest.raises(RuntimeError):
            await self.optimizer._get_entity_classification(
                sentence,
                openai_client=self.mock_openai_client
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalid_sentence", [
        123,
        12.34,
        [],
        {},
        None,
        True,
        object(),
        set(),
    ])
    async def test_get_entity_classification_invalid_sentence_type_raises_typeerror(self, invalid_sentence):
        """
        GIVEN invalid sentence type (not string)
        WHEN _get_entity_classification is called
        THEN expect TypeError to be raised
        """
        # Given - invalid_sentence from parametrize
        
        # When & Then
        with pytest.raises(TypeError):
            await self.optimizer._get_entity_classification(
                invalid_sentence,
                openai_client=self.mock_openai_client
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalid_classifications", [
        "invalid",  # string instead of set
        123,
        12.34,
        [],
        {},
        None,
        True,
        object()
    ])
    async def test_get_entity_classification_invalid_classifications_type_raises_typeerror(self, invalid_classifications):
        """
        GIVEN invalid classifications type (not set)
        WHEN _get_entity_classification is called
        THEN expect TypeError to be raised
        """
        # Given
        sentence = "Apple Inc."
        
        # When & Then
        with pytest.raises(TypeError):
            await self.optimizer._get_entity_classification(
                sentence,
                openai_client=self.mock_openai_client,
                classifications=invalid_classifications
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])