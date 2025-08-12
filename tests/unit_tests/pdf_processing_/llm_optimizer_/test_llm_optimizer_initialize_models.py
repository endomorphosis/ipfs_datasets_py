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









class TestLLMOptimizerInitializeModelsHappyPath:
    """Test LLMOptimizer._initialize_models basic functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        # Create optimizer without automatic model initialization
        with patch.object(LLMOptimizer, '_initialize_models'):
            self.optimizer = LLMOptimizer()

    def test_initialize_models_loads_sentence_transformer(self):
        """
        GIVEN valid model names in optimizer instance
        WHEN _initialize_models is called
        THEN SentenceTransformer model is loaded successfully
        """
        # Given
        mock_embedding_model = Mock()
        self.optimizer.SentenceTransformer = Mock(return_value=mock_embedding_model)
        self.optimizer.tiktoken = Mock()
        self.optimizer.tiktoken.encoding_for_model = Mock(return_value=Mock())
        
        # When
        self.optimizer._initialize_models()
        
        # Then
        self.optimizer.SentenceTransformer.assert_called_once_with(self.optimizer.model_name)

    def test_initialize_models_sets_embedding_model_attribute(self):
        """
        GIVEN valid model names in optimizer instance
        WHEN _initialize_models is called
        THEN embedding_model attribute is set correctly
        """
        # Given
        mock_embedding_model = Mock()
        self.optimizer.SentenceTransformer = Mock(return_value=mock_embedding_model)
        self.optimizer.tiktoken = Mock()
        self.optimizer.tiktoken.encoding_for_model = Mock(return_value=Mock())
        
        # When
        self.optimizer._initialize_models()
        
        # Then
        assert self.optimizer.embedding_model is mock_embedding_model

    def test_initialize_models_loads_tokenizer(self):
        """
        GIVEN valid model names in optimizer instance
        WHEN _initialize_models is called
        THEN tokenizer is loaded successfully
        """
        # Given
        mock_tokenizer = Mock()
        self.optimizer.SentenceTransformer = Mock(return_value=Mock())
        self.optimizer.tiktoken = Mock()
        self.optimizer.tiktoken.encoding_for_model = Mock(return_value=mock_tokenizer)
        
        # When
        self.optimizer._initialize_models()
        
        # Then
        self.optimizer.tiktoken.encoding_for_model.assert_called_once_with(self.optimizer.tokenizer_name)

    def test_initialize_models_sets_tokenizer_attribute(self):
        """
        GIVEN valid model names in optimizer instance
        WHEN _initialize_models is called
        THEN tokenizer attribute is set correctly
        """
        # Given
        mock_tokenizer = Mock()
        self.optimizer.SentenceTransformer = Mock(return_value=Mock())
        self.optimizer.tiktoken = Mock()
        self.optimizer.tiktoken.encoding_for_model = Mock(return_value=mock_tokenizer)
        
        # When
        self.optimizer._initialize_models()
        
        # Then
        assert self.optimizer.tokenizer is mock_tokenizer

    def test_initialize_models_no_exceptions_raised(self):
        """
        GIVEN valid model names in optimizer instance
        WHEN _initialize_models is called
        THEN no exceptions are raised
        """
        # Given
        self.optimizer.SentenceTransformer = Mock(return_value=Mock())
        self.optimizer.tiktoken = Mock()
        self.optimizer.tiktoken.encoding_for_model = Mock(return_value=Mock())
        
        # When/Then - Should not raise any exceptions
        self.optimizer._initialize_models()







class TestLLMOptimizerInitializeModelsErrorHandling:
    """Test LLMOptimizer._initialize_models error handling."""

    def setup_method(self):
        """Set up test fixtures."""
        # Create optimizer without automatic model initialization
        with patch.object(LLMOptimizer, '_initialize_models'):
            self.optimizer = LLMOptimizer()

    def test_initialize_models_sentence_transformer_failure(self):
        """
        GIVEN invalid sentence transformer model name
        WHEN _initialize_models is called
        THEN RuntimeError is raised with clear error message
        """
        # Given
        self.optimizer.SentenceTransformer = Mock(side_effect=ValueError("Model not found"))
        
        # When/Then
        with pytest.raises(RuntimeError, match="Could not load embedding model for LLMOptimizer"):
            self.optimizer._initialize_models()

    def test_initialize_models_tokenizer_failure(self):
        """
        GIVEN invalid tokenizer name
        WHEN _initialize_models is called
        THEN RuntimeError is raised with clear error message about tokenizer failure
        """
        # Given
        self.optimizer.SentenceTransformer = Mock(return_value=Mock())
        self.optimizer.tiktoken = Mock()
        self.optimizer.tiktoken.encoding_for_model = Mock(side_effect=KeyError("Tokenizer not found"))
        
        # When/Then
        with pytest.raises(RuntimeError, match="Could not load tokenizer for LLMOptimizer"):
            self.optimizer._initialize_models()

    def test_initialize_models_network_timeout(self):
        """
        GIVEN network timeout during model download
        WHEN _initialize_models is called
        THEN RuntimeError is raised with clear error message about network issues
        """
        # Given
        self.optimizer.SentenceTransformer = Mock(side_effect=TimeoutError("Network timeout"))

        # When/Then
        with pytest.raises(RuntimeError, match="Could not load embedding model for LLMOptimizer"):
            self.optimizer._initialize_models()

    def test_initialize_models_memory_error(self):
        """
        GIVEN insufficient memory for model loading
        WHEN _initialize_models is called
        THEN RuntimeError is raised with clear error message about memory issues
        """
        # Given
        self.optimizer.SentenceTransformer = Mock(side_effect=MemoryError("Insufficient memory"))
        
        # When/Then
        with pytest.raises(RuntimeError, match="Could not load embedding model for LLMOptimizer"):
            self.optimizer._initialize_models()

    def test_initialize_models_partial_success_tokenizer_fails(self):
        """
        GIVEN embedding model loads successfully but tokenizer fails
        WHEN _initialize_models is called
        THEN RuntimeError is raised for tokenizer failure
        """
        # Given
        self.optimizer.SentenceTransformer = Mock(return_value=Mock())
        self.optimizer.tiktoken = Mock()
        self.optimizer.tiktoken.encoding_for_model = Mock(side_effect=ValueError("Invalid tokenizer name"))
        
        # When/Then
        with pytest.raises(RuntimeError, match="Could not load tokenizer for LLMOptimizer"):
            self.optimizer._initialize_models()



class TestLLMOptimizerInitializeModelsTokenizerTypes:
    """Test LLMOptimizer._initialize_models tokenizer type selection."""

    def setup_method(self):
        """Set up test fixtures."""
        # Create optimizer without automatic model initialization
        with patch.object(LLMOptimizer, '_initialize_models'):
            self.optimizer = LLMOptimizer()

    def test_initialize_models_uses_tiktoken_for_gpt_models(self):
        """
        GIVEN tokenizer name contains 'gpt'
        WHEN _initialize_models is called
        THEN tiktoken encoding is used
        """
        # Given
        self.optimizer.tokenizer_name = "gpt-3.5-turbo"
        self.optimizer.SentenceTransformer = Mock(return_value=Mock())
        self.optimizer.tiktoken = Mock()
        self.optimizer.tiktoken.encoding_for_model = Mock(return_value=Mock())
        
        # When
        self.optimizer._initialize_models()
        
        # Then
        self.optimizer.tiktoken.encoding_for_model.assert_called_once_with("gpt-3.5-turbo")

    def test_initialize_models_uses_huggingface_for_non_gpt_models(self):
        """
        GIVEN tokenizer name does not contain 'gpt'
        WHEN _initialize_models is called
        THEN AutoTokenizer is used
        """
        # Given
        self.optimizer.tokenizer_name = "bert-base-uncased"
        self.optimizer.SentenceTransformer = Mock(return_value=Mock())
        self.optimizer.AutoTokenizer = Mock()
        self.optimizer.AutoTokenizer.from_pretrained = Mock(return_value=Mock())
        
        # When
        self.optimizer._initialize_models()
        
        # Then
        self.optimizer.AutoTokenizer.from_pretrained.assert_called_once_with("bert-base-uncased")

    def test_initialize_models_gpt4_uses_tiktoken(self):
        """
        GIVEN tokenizer name is 'gpt-4'
        WHEN _initialize_models is called
        THEN tiktoken encoding is used
        """
        # Given
        self.optimizer.tokenizer_name = "gpt-4"
        self.optimizer.SentenceTransformer = Mock(return_value=Mock())
        self.optimizer.tiktoken = Mock()
        self.optimizer.tiktoken.encoding_for_model = Mock(return_value=Mock())
        
        # When
        self.optimizer._initialize_models()
        
        # Then
        self.optimizer.tiktoken.encoding_for_model.assert_called_once_with("gpt-4")

    def test_initialize_models_roberta_uses_huggingface(self):
        """
        GIVEN tokenizer name is 'roberta-base'
        WHEN _initialize_models is called
        THEN AutoTokenizer is used
        """
        # Given
        self.optimizer.tokenizer_name = "roberta-base"
        self.optimizer.SentenceTransformer = Mock(return_value=Mock())
        self.optimizer.AutoTokenizer = Mock()
        self.optimizer.AutoTokenizer.from_pretrained = Mock(return_value=Mock())
        
        # When
        self.optimizer._initialize_models()
        
        # Then
        self.optimizer.AutoTokenizer.from_pretrained.assert_called_once_with("roberta-base")

    def test_initialize_models_sets_correct_tokenizer_for_huggingface(self):
        """
        GIVEN non-gpt tokenizer name
        WHEN _initialize_models is called
        THEN tokenizer attribute is set to AutoTokenizer instance
        """
        # Given
        mock_hf_tokenizer = Mock()
        self.optimizer.tokenizer_name = "bert-base-uncased"
        self.optimizer.SentenceTransformer = Mock(return_value=Mock())
        self.optimizer.AutoTokenizer = Mock()
        self.optimizer.AutoTokenizer.from_pretrained = Mock(return_value=mock_hf_tokenizer)
        
        # When
        self.optimizer._initialize_models()
        
        # Then
        assert self.optimizer.tokenizer is mock_hf_tokenizer





class TestLLMOptimizerInitializeModelsOpenAIClient:
    """Test LLMOptimizer._initialize_models OpenAI client initialization."""

    def setup_method(self):
        """Set up test fixtures."""
        # Create optimizer without automatic model initialization
        with patch.object(LLMOptimizer, '_initialize_models'):
            self.optimizer = LLMOptimizer()

    def test_initialize_models_initializes_openai_client_with_api_key(self):
        """
        GIVEN API key is available
        WHEN _initialize_models is called
        THEN OpenAI client is initialized successfully
        """
        # Given
        self.optimizer.api_key = "test-api-key"
        self.optimizer.SentenceTransformer = Mock(return_value=Mock())
        self.optimizer.tiktoken = Mock()
        self.optimizer.tiktoken.encoding_for_model = Mock(return_value=Mock())
        self.optimizer.openai_async_client = Mock(return_value=Mock())
        
        # When
        self.optimizer._initialize_models()
        
        # Then
        self.optimizer.openai_async_client.assert_called_once_with(api_key="test-api-key")

    def test_initialize_models_handles_missing_api_key(self):
        """
        GIVEN no API key is available
        WHEN _initialize_models is called
        THEN OpenAI client is set to None and warning is logged
        """
        # Given
        mock_logger = Mock()
        self.optimizer.api_key = None
        self.optimizer.logger = mock_logger
        self.optimizer.SentenceTransformer = Mock(return_value=Mock())
        self.optimizer.tiktoken = Mock()
        self.optimizer.tiktoken.encoding_for_model = Mock(return_value=Mock())
        
        # When
        self.optimizer._initialize_models()
        
        # Then
        assert self.optimizer.openai_async_client is None

    def test_initialize_models_logs_warning_for_missing_api_key(self):
        """
        GIVEN no API key is available
        WHEN _initialize_models is called
        THEN warning is logged about missing API key
        """
        # Given
        mock_logger = Mock()
        self.optimizer.api_key = None
        self.optimizer.logger = mock_logger
        self.optimizer.SentenceTransformer = Mock(return_value=Mock())
        self.optimizer.tiktoken = Mock()
        self.optimizer.tiktoken.encoding_for_model = Mock(return_value=Mock())
        
        # When
        self.optimizer._initialize_models()
        
        # Then
        mock_logger.warning.assert_called_once_with("OpenAI API key not available, OpenAI client not initialized")

    def test_initialize_models_handles_openai_client_failure(self):
        """
        GIVEN OpenAI client initialization fails
        WHEN _initialize_models is called
        THEN client is set to None and warning is logged
        """
        # Given
        mock_logger = Mock()
        self.optimizer.api_key = "test-api-key"
        self.optimizer.logger = mock_logger
        self.optimizer.SentenceTransformer = Mock(return_value=Mock())
        self.optimizer.tiktoken = Mock()
        self.optimizer.tiktoken.encoding_for_model = Mock(return_value=Mock())
        self.optimizer.openai_async_client = Mock(side_effect=Exception("Client init failed"))
        
        # When
        self.optimizer._initialize_models()
        
        # Then
        assert self.optimizer.openai_async_client is None

    def test_initialize_models_logs_openai_client_failure(self):
        """
        GIVEN OpenAI client initialization fails
        WHEN _initialize_models is called
        THEN warning is logged about client initialization failure
        """
        # Given
        mock_logger = Mock()
        self.optimizer.api_key = "test-api-key"
        self.optimizer.logger = mock_logger
        self.optimizer.SentenceTransformer = Mock(return_value=Mock())
        self.optimizer.tiktoken = Mock()
        self.optimizer.tiktoken.encoding_for_model = Mock(return_value=Mock())
        self.optimizer.openai_async_client = Mock(side_effect=Exception("Client init failed"))
        
        # When
        self.optimizer._initialize_models()
        
        # Then
        mock_logger.warning.assert_called_with("Could not initialize OpenAI client: Client init failed")









# class TestLLMOptimizerInitializeModels:
#     """Test LLMOptimizer._initialize_models private method."""

#     def setup_method(self):
#         """Set up test fixtures."""
#         # Create optimizer without automatic model initialization
#         with patch.object(LLMOptimizer, '_initialize_models'):
#             self.optimizer = LLMOptimizer()

#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.SentenceTransformer')
#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.tiktoken.encoding_for_model')
#     def test_initialize_models_loads_sentence_transformer(self, mock_tiktoken, mock_sentence_transformer):
#         """
#         GIVEN valid model names in optimizer instance
#         WHEN _initialize_models is called
#         THEN SentenceTransformer model is loaded successfully
#         """
#         # Given
#         mock_embedding_model = Mock()
#         mock_tokenizer = Mock()
#         mock_sentence_transformer.return_value = mock_embedding_model
#         mock_tiktoken.return_value = mock_tokenizer
        
#         # When
#         self.optimizer._initialize_models()
        
#         # Then
#         mock_sentence_transformer.assert_called_once_with(self.optimizer.model_name)

#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.SentenceTransformer')
#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.tiktoken.encoding_for_model')
#     def test_initialize_models_sets_embedding_model_attribute(self, mock_tiktoken, mock_sentence_transformer):
#         """
#         GIVEN valid model names in optimizer instance
#         WHEN _initialize_models is called
#         THEN embedding_model attribute is set correctly
#         """
#         # Given
#         mock_embedding_model = Mock()
#         mock_tokenizer = Mock()
#         mock_sentence_transformer.return_value = mock_embedding_model
#         mock_tiktoken.return_value = mock_tokenizer
        
#         # When
#         self.optimizer._initialize_models()
        
#         # Then
#         assert self.optimizer.embedding_model is mock_embedding_model

#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.SentenceTransformer')
#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.tiktoken.encoding_for_model')
#     def test_initialize_models_loads_tokenizer(self, mock_tiktoken, mock_sentence_transformer):
#         """
#         GIVEN valid model names in optimizer instance
#         WHEN _initialize_models is called
#         THEN tokenizer is loaded successfully
#         """
#         # Given
#         mock_embedding_model = Mock()
#         mock_tokenizer = Mock()
#         mock_sentence_transformer.return_value = mock_embedding_model
#         mock_tiktoken.return_value = mock_tokenizer
        
#         # When
#         self.optimizer._initialize_models()
        
#         # Then
#         mock_tiktoken.assert_called_once_with(self.optimizer.tokenizer_name)

#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.SentenceTransformer')
#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.tiktoken.encoding_for_model')
#     def test_initialize_models_sets_tokenizer_attribute(self, mock_tiktoken, mock_sentence_transformer):
#         """
#         GIVEN valid model names in optimizer instance
#         WHEN _initialize_models is called
#         THEN tokenizer attribute is set correctly
#         """
#         # Given
#         mock_embedding_model = Mock()
#         mock_tokenizer = Mock()
#         mock_sentence_transformer.return_value = mock_embedding_model
#         mock_tiktoken.return_value = mock_tokenizer
        
#         # When
#         self.optimizer._initialize_models()
        
#         # Then
#         assert self.optimizer.tokenizer is mock_tokenizer

#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.SentenceTransformer')
#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.tiktoken.encoding_for_model')
#     def test_initialize_models_no_exceptions_raised(self, mock_tiktoken, mock_sentence_transformer):
#         """
#         GIVEN valid model names in optimizer instance
#         WHEN _initialize_models is called
#         THEN no exceptions are raised
#         """
#         # Given
#         mock_embedding_model = Mock()
#         mock_tokenizer = Mock()
#         mock_sentence_transformer.return_value = mock_embedding_model
#         mock_tiktoken.return_value = mock_tokenizer
        
#         # When/Then - Should not raise any exceptions
#         self.optimizer._initialize_models()

#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.SentenceTransformer')
#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.tiktoken.encoding_for_model')
#     def test_initialize_models_sentence_transformer_failure(self, mock_tiktoken, mock_sentence_transformer):
#         """
#         GIVEN invalid sentence transformer model name
#         WHEN _initialize_models is called
#         THEN expect:
#             - RuntimeError raised immediately
#             - Exception contains clear error message
#         """
#         # Given
#         mock_sentence_transformer.side_effect = ValueError("Model not found")
#         mock_tokenizer = Mock()
#         mock_tiktoken.return_value = mock_tokenizer
        
#         # When/Then - Expect RuntimeError to be raised
#         with pytest.raises(RuntimeError) as exc_info:
#             self.optimizer._initialize_models()
        
#         # Verify exception message contains expected information
#         error_message = str(exc_info.value)
#         assert "Could not load embedding model for LLMOptimizer" in error_message
#         assert "sentence-transformers/all-MiniLM-L6-v2" in error_message
#         assert "Model not found" in error_message

#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.SentenceTransformer')
#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.tiktoken.encoding_for_model')
#     def test_initialize_models_tokenizer_failure(self, mock_tiktoken, mock_sentence_transformer):
#         """
#         GIVEN invalid tokenizer name
#         WHEN _initialize_models is called
#         THEN expect:
#             - RuntimeError raised immediately
#             - Exception contains clear error message about tokenizer failure
#         """
#         # Given
#         mock_embedding_model = Mock()
#         mock_sentence_transformer.return_value = mock_embedding_model
#         mock_tiktoken.side_effect = KeyError("Tokenizer not found")
        
#         # When/Then - Expect RuntimeError to be raised
#         with pytest.raises(RuntimeError) as exc_info:
#             self.optimizer._initialize_models()
        
#         # Verify exception message contains expected information
#         error_message = str(exc_info.value)
#         assert "Could not load tokenizer for LLMOptimizer" in error_message
#         assert "gpt-3.5-turbo" in error_message
#         assert "Tokenizer not found" in error_message

#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.SentenceTransformer')
#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.tiktoken.encoding_for_model')
#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.AutoTokenizer.from_pretrained')
#     def test_initialize_models_tiktoken_vs_huggingface(self, mock_hf_tokenizer, mock_tiktoken, mock_sentence_transformer):
#         """
#         GIVEN different tokenizer types (tiktoken vs HuggingFace)
#         WHEN _initialize_models is called
#         THEN expect:
#             - Correct tokenizer type detection based on 'gpt' in name
#             - tiktoken used for gpt models
#             - AutoTokenizer used for non-gpt models
#         """
#         # Given - Test tiktoken tokenizer (OpenAI models)
#         mock_embedding_model = Mock()
#         mock_sentence_transformer.return_value = mock_embedding_model
#         mock_tiktoken_tokenizer = Mock()
#         mock_tiktoken.return_value = mock_tiktoken_tokenizer
        
#         # Set tokenizer name to OpenAI model
#         self.optimizer.tokenizer_name = "gpt-3.5-turbo"
        
#         # When
#         self.optimizer._initialize_models()
        
#         # Then - Should use tiktoken for gpt models
#         mock_tiktoken.assert_called_once_with("gpt-3.5-turbo")
#         assert self.optimizer.tokenizer is mock_tiktoken_tokenizer
#         mock_hf_tokenizer.assert_not_called()
        
#         # Reset for second test
#         self.optimizer.embedding_model = None
#         self.optimizer.tokenizer = None
#         mock_tiktoken.reset_mock()
#         mock_hf_tokenizer.reset_mock()
#         mock_sentence_transformer.reset_mock()
        
#         # Given - Test HuggingFace tokenizer (non-gpt models)
#         mock_embedding_model_2 = Mock()
#         mock_sentence_transformer.return_value = mock_embedding_model_2
#         mock_hf_tokenizer_instance = Mock()
#         mock_hf_tokenizer.return_value = mock_hf_tokenizer_instance
        
#         self.optimizer.tokenizer_name = "bert-base-uncased"  # No 'gpt' in name
        
#         # When
#         self.optimizer._initialize_models()
        
#         # Then - Should use HuggingFace AutoTokenizer for non-gpt models
#         mock_tiktoken.assert_not_called()  # Should not call tiktoken for non-gpt models
#         mock_hf_tokenizer.assert_called_once_with("bert-base-uncased")
#         assert self.optimizer.tokenizer is mock_hf_tokenizer_instance
#         assert self.optimizer.embedding_model is mock_embedding_model_2

#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.SentenceTransformer')
#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.tiktoken.encoding_for_model')
#     def test_initialize_models_complete_failure(self, mock_tiktoken, mock_sentence_transformer):
#         """
#         GIVEN both embedding model and tokenizer loading fail
#         WHEN _initialize_models is called
#         THEN expect:
#             - RuntimeError raised immediately
#             - Exception contains clear error message about embedding model failure
#         """
#         # Given
#         mock_sentence_transformer.side_effect = ImportError("SentenceTransformers not available")
#         mock_tiktoken.side_effect = ImportError("tiktoken not available")
        
#         # When/Then - Expect RuntimeError to be raised for embedding model failure
#         with pytest.raises(RuntimeError) as exc_info:
#             self.optimizer._initialize_models()
        
#         # Verify exception message contains expected information
#         error_message = str(exc_info.value)
#         assert "Could not load embedding model for LLMOptimizer" in error_message
#         assert "SentenceTransformers not available" in error_message

#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.SentenceTransformer')
#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.tiktoken.encoding_for_model')
#     def test_initialize_models_network_timeout(self, mock_tiktoken, mock_sentence_transformer):
#         """
#         GIVEN network timeout during model download
#         WHEN _initialize_models is called
#         THEN expect:
#             - RuntimeError raised immediately
#             - Exception contains clear error message about network issues
#         """
#         # Given
#         mock_sentence_transformer.side_effect = TimeoutError("Network timeout")

#         # When/Then - Expect TimeoutError to be raised
#         with pytest.raises(RuntimeError) as exc_info:
#             self.optimizer._initialize_models()
        
#         # Verify exception message contains expected information
#         error_message = str(exc_info.value)
#         assert "Could not load embedding model for LLMOptimizer" in error_message
#         assert "Network timeout" in error_message

#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.SentenceTransformer')
#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.tiktoken.encoding_for_model')
#     def test_initialize_models_memory_error(self, mock_tiktoken, mock_sentence_transformer):
#         """
#         GIVEN insufficient memory for model loading
#         WHEN _initialize_models is called
#         THEN expect:
#             - MemoryError raised
#             - Exception contains clear error message about memory issues
#         """
#         # Given
#         mock_sentence_transformer.side_effect = MemoryError("Insufficient memory")
#         mock_tokenizer = Mock()
#         mock_tiktoken.return_value = mock_tokenizer
        
#         # When/Then - Expect MemoryError to be raised
#         with pytest.raises(RuntimeError) as exc_info:
#             self.optimizer._initialize_models()
        
#         # Verify exception message contains expected information
#         error_message = str(exc_info.value)
#         assert "Could not load embedding model for LLMOptimizer" in error_message
#         assert "Insufficient memory" in error_message

#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.SentenceTransformer')
#     @patch('ipfs_datasets_py.pdf_processing.llm_optimizer.tiktoken.encoding_for_model')
#     def test_initialize_models_partial_success(self, mock_tiktoken, mock_sentence_transformer):
#         """
#         GIVEN embedding model loads successfully but tokenizer fails
#         WHEN _initialize_models is called
#         THEN expect:
#             - RuntimeError raised immediately when tokenizer fails (no graceful handling)
#             - Exception contains clear error message about tokenizer failure
#             - No partial success state - fail completely when any component fails
#         """
#         # Given - Embedding model succeeds, tokenizer fails
#         mock_embedding_model = Mock()
#         mock_sentence_transformer.return_value = mock_embedding_model
#         mock_tiktoken.side_effect = ValueError("Invalid tokenizer name")
        
#         # When/Then - Expect RuntimeError to be raised for tokenizer failure
#         with pytest.raises(RuntimeError) as exc_info:
#             self.optimizer._initialize_models()
        
#         # Verify exception message contains expected information
#         error_message = str(exc_info.value)
#         assert "Could not load tokenizer for LLMOptimizer" in error_message
#         assert "Invalid tokenizer name" in error_message
        
#         # Test opposite scenario - when SentenceTransformer fails first
#         mock_sentence_transformer.side_effect = RuntimeError("Model loading failed")
#         mock_tokenizer = Mock()
#         mock_tiktoken.side_effect = None
#         mock_tiktoken.return_value = mock_tokenizer
        
#         # Reset and reinitialize
#         self.optimizer.embedding_model = None
#         self.optimizer.tokenizer = None
        
#         # When/Then - Expect RuntimeError to be raised for embedding model failure
#         with pytest.raises(RuntimeError) as exc_info:
#             self.optimizer._initialize_models()
        
#         # Verify exception message contains expected information
#         error_message = str(exc_info.value)
#         assert "Could not load embedding model for LLMOptimizer" in error_message
#         assert "Model loading failed" in error_message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
