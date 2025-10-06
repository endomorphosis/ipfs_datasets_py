#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"

from datetime import datetime
import pytest
import os
from unittest.mock import MagicMock, AsyncMock, Mock, patch


import os
import pytest
import time
import numpy as np
import openai
import tiktoken

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
    LLMDocument,
    WIKIPEDIA_CLASSIFICATIONS,
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

@pytest.fixture
def valid_init_params_for_chunk_optimizer():
    """Initialize parameters for ChunkOptimizer tests."""
    return {
        'max_size': 2048,
        'overlap': 200,
        'min_size': 100
    }

@pytest.fixture
def other_valid_init_params_for_chunk_optimizer():
    """Another set of valid initialization parameters."""
    return {
        'max_size': 1024,
        'overlap': 100,
        'min_size': 50
    }

@pytest.fixture
def wikipedia_classifications():
    return WIKIPEDIA_CLASSIFICATIONS

@pytest.fixture
def api_key():
    key = os.getenv("OPENAI_API_KEY", "test_api_key")
    return key

@pytest.fixture
def model_name():
    return "sentence-transformers/all-MiniLM-L6-v2"

@pytest.fixture
def llm_name():
    return "gpt-4o-2024-08-06"

@pytest.fixture
def tokenizer_name():
    return "gpt-3.5-turbo"


@pytest.fixture
def chunk_optimizer(valid_init_params_for_chunk_optimizer):
    """Fixture to create a ChunkOptimizer instance."""
    return ChunkOptimizer(**valid_init_params_for_chunk_optimizer)


@pytest.fixture
def chunk_optimizer_class():
    return ChunkOptimizer


@pytest.fixture
def mock_sentence_transformer_class() -> MagicMock:
    return MagicMock(spec=SentenceTransformer)


@pytest.fixture
def real_sentence_transformer_class() -> SentenceTransformer:
    return SentenceTransformer


@pytest.fixture
def mock_async_openai_class():
    return openai.AsyncOpenAI


@pytest.fixture
def real_async_openai_class():
    return openai.AsyncOpenAI


@pytest.fixture
def real_tiktoken_module():
    return tiktoken


@pytest.fixture
def mock_tiktoken_module():
    """Mock the tiktoken module."""
    return MagicMock(spec=tiktoken)


@pytest.fixture
def mock_auto_tokenizer_class():
    return MagicMock(spec=AutoTokenizer)


@pytest.fixture
def real_auto_tokenizer_class():
    return AutoTokenizer


@pytest.fixture
def mock_logger():
    mock_logger = MagicMock(spec=logging.Logger)
    mock_logger.level = logging.DEBUG
    return mock_logger

@pytest.fixture
def real_logger():
    return logging.getLogger("test_logger")


@pytest.fixture
def text_processor_class():
    return TextProcessor


@pytest.fixture
def text_processor():
    return TextProcessor()


@pytest.fixture
def valid_init_params_for_llm_optimizer(
    model_name,
    llm_name,
    tokenizer_name,
    valid_init_params_for_chunk_optimizer,
    api_key,
    wikipedia_classifications,
    real_auto_tokenizer_class,
    text_processor_class,
    real_tiktoken_module,
    real_sentence_transformer_class,
    chunk_optimizer_class,
    real_async_openai_class,
    real_logger
    ):
    """Initialize parameters for LLMOptimizer tests."""
    return {
        'model_name': model_name,
        'llm_name': llm_name,
        'tokenizer_name': tokenizer_name,
        'max_chunk_size': valid_init_params_for_chunk_optimizer['max_size'],
        'chunk_overlap': valid_init_params_for_chunk_optimizer['overlap'],
        'min_chunk_size': valid_init_params_for_chunk_optimizer['min_size'],
        'entity_classifications': wikipedia_classifications,
        'api_key': api_key,
        'async_openai': real_async_openai_class,
        'sentence_transformer': real_sentence_transformer_class,
        'text_processor': text_processor_class,
        'auto_tokenizer': real_auto_tokenizer_class,
        'chunk_optimizer': chunk_optimizer_class,
        'tiktoken': real_tiktoken_module,
        'logger': real_logger
    }


@pytest.fixture
def llm_optimizer(valid_init_params_for_llm_optimizer) -> LLMOptimizer:
    """Fixture to create a LLMOptimizer instance."""
    return LLMOptimizer(**valid_init_params_for_llm_optimizer)

@pytest.fixture
def mock_encode_return():
    return np.random.rand(384)

@pytest.fixture
def mock_token_list():
    return list(range(50))


@pytest.fixture
def llm_optimizer_with_mocks(
    valid_init_params_for_llm_optimizer,
    mock_sentence_transformer_class,
    mock_async_openai_class,
    mock_tiktoken_module,
    mock_auto_tokenizer_class,
    mock_logger,
    mock_encode_return,
    mock_token_list,
    ) -> LLMOptimizer:
    """Fixture to create an llm optimizer with mocked dependencies."""
    params = valid_init_params_for_llm_optimizer.copy()

    mocks = {
        'sentence_transformer': mock_sentence_transformer_class,
        'async_openai': mock_async_openai_class,
        'tiktoken': mock_tiktoken_module,
        'auto_tokenizer': mock_auto_tokenizer_class,
        'logger': mock_logger,
    }
    params.update(mocks)

    optimizer = LLMOptimizer(**params)

    optimizer.embedding_model.encode.return_value = mock_encode_return
    optimizer.tokenizer.encode.return_value = mock_token_list

    return optimizer


def make_llm_optimizer(resources: dict) -> LLMOptimizer:
    """
    Helper function to create an LLMOptimizer instance with given resources.
    Dictionaries can be mixed-and-matched to get custom mocks.
    """
    return LLMOptimizer(**resources)


# ================================
# SHARED TEST DATA FIXTURES
# ================================

@pytest.fixture
def test_element_content():
    """Standard test content for elements."""
    return {
        'header': 'Introduction to Machine Learning',
        'header_with_numbers': '1. Introduction to Machine Learning',
        'paragraph': 'Machine learning is a subset of artificial intelligence that enables computers to learn without being explicitly programmed.',
        'long_paragraph': 'This is test content for testing purposes. ' * 20,
        'realistic_paragraph': 'Deep learning uses neural networks with multiple layers to model and understand complex patterns in data.',
        'consistent_content': 'Consistent test content for reproducibility testing.',
        'table_content': 'Table 1: Performance Metrics'
    }

@pytest.fixture
def table_element():
    table = {
        'content': 'Table 1: Performance Metrics',
        'type': 'table',
        'subtype': 'caption',
        'position': {'x': 100, 'y': 200},
        'confidence': 0.85
    }
    return table


@pytest.fixture
def element_factory(test_element_content):
    """Factory function to create test elements with consistent structure."""
    def _make_element(content_key='paragraph', subtype=None, position=None):
        content = test_element_content.get(content_key, content_key)
        default_position = {'x': 100, 'y': 50}
        return {
            'content': content,
            'type': 'text',
            'subtype': subtype or 'paragraph',
            'position': position or default_position,
            'confidence': 0.95
        }
    return _make_element


@pytest.fixture
def metadata_factory():
    def _make_metadata(pages,title='Test Document', author='Test Author'):
        return {
            'page_count': pages,
            'title': title,
            'author': author
        }
    return _make_metadata


@pytest.fixture
def structure_factory(metadata_factory):
    def _make_structure(pages,title='Test Document'):
        return {
            'page_count': metadata_factory(pages)['page_count'],
            'title': metadata_factory(pages,title=title)['title']
        }
    return _make_structure


@pytest.fixture
def simple_decomposed_content(element_factory, metadata_factory, structure_factory):
    """Simple test content with one page and one element."""
    pages = [{"elements": [element_factory('paragraph')]}]
    metadata = metadata_factory(len(pages))
    structure = structure_factory(len(pages))
    return {'pages': pages, 'metadata': metadata, 'structure': structure}


@pytest.fixture
def realistic_decomposed_content(element_factory, metadata_factory, structure_factory, table_element):
    """Realistic test content with multiple elements and pages."""
    xy = {'x': 100, 'y': 100}
    title = 'Machine Learning Fundamentals'
    pages = [
        {
            'elements': [
                element_factory('header', 'header'),
                element_factory('paragraph', 'paragraph', xy),
                table_element,
            ]
        },
        {
            'elements': [
                element_factory('header_with_numbers', 'header'),
                element_factory('realistic_paragraph', 'paragraph', xy),
            ]
        }
    ],
    return {
        'pages': pages,
        'metadata': metadata_factory(len(pages), title=title),
        'structure': metadata_factory(len(pages), title=title),
    }


@pytest.fixture
def consistency_decomposed_content(element_factory, metadata_factory):
    """Consistent test content for reproducibility testing."""
    xy = {'x': 100, 'y': 100}
    title = 'Consistency Test'
    pages = [{'elements': [element_factory('consistent_content', 'paragraph', xy)]}]
    return {
        'pages': pages,
        'metadata': metadata_factory(len(pages), title=title),
        'structure': metadata_factory(len(pages), title=title),
    }


@pytest.fixture
def invalid_decomposed_content(element_factory):
    """Invalid decomposed content missing required 'pages' key."""
    return {
        'invalid_key': [{'elements': [element_factory('paragraph')]}]
    }


@pytest.fixture
def document_creator(element_factory):
    """Factory function to create test documents of varying sizes."""
    def _create_test_document(pages: int, elements_per_page: int) -> dict:
        """Helper method to create test documents of varying sizes."""
        doc_pages = []
        
        for page_num in range(pages):
            elements = []
            for elem_num in range(elements_per_page):
                content = f'This is test content for page {page_num + 1}, element {elem_num + 1}. ' * 10
                element = element_factory(content, 
                                        'paragraph' if elem_num % 3 != 0 else 'header',
                                        {'x': 100, 'y': 50 + elem_num * 50})
                element['confidence'] = 0.9 - (elem_num * 0.01)
                elements.append(element)
            
            doc_pages.append({'elements': elements})
        
        return {
            'pages': doc_pages,
            'metadata': {
                'page_count': pages,
                'title': f'Test Document {pages}p',
                'author': 'Test Author'
            },
            'structure': {
                'page_count': pages,
                'title': f'Test Document {pages}p'
            }
        }
    
    return _create_test_document


# ================================
# SHARED METADATA FIXTURES
# ================================

@pytest.fixture
def simple_document_metadata():
    """Simple document metadata for basic testing."""
    return {
        'document_id': 'test_doc', 
        'title': 'Test',
        'author': 'Test Author'
    }


@pytest.fixture
def realistic_document_metadata():
    """Realistic document metadata for comprehensive testing."""
    return {
        'document_id': 'test_doc_001',
        'title': 'Machine Learning Fundamentals',
        'author': 'Test Author',
        'creation_date': '2024-01-01'
    }


@pytest.fixture
def consistency_document_metadata():
    """Consistent document metadata for reproducibility testing."""
    return {
        'document_id': 'consistency_test', 
        'title': 'Consistency Test',
        'author': 'Test Author'
    }


# ================================
# SHARED TEST CONFIGURATION FIXTURES
# ================================

@pytest.fixture
def time_limit():
    """Standard time limit for performance testing."""
    return 30.0


@pytest.fixture
def number_of_runs():
    """Number of runs for consistency testing."""
    return 3


@pytest.fixture
def expected_time_limit():
    """Expected time limit for file processing."""
    return 60.0

