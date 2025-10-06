#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"

from datetime import datetime
import pytest
import os
import numpy as np
from pydantic import ValidationError

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

from ipfs_datasets_py.pdf_processing.llm_optimizer import (
    ChunkOptimizer,
    LLMOptimizer,
    TextProcessor,
    LLMChunk,
    LLMDocument
)

from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk.llm_chunk_factory import LLMChunkTestDataFactory

work_dir = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py"
file_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/llm_optimizer.py")
md_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/llm_optimizer_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

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




class TestLLMChunkSemanticTypeClassification:
    """Test LLMChunk semantic type classification and validation."""

    def test_valid_semantic_types(self):
        """
        GIVEN valid semantic type values ('text', 'table', 'figure_caption', 'header', 'mixed')
        WHEN LLMChunk is instantiated with these types
        THEN expect all valid types accepted without error
        """
        # Given - valid semantic types from the documentation
        valid_types = ['text', 'table', 'figure_caption', 'header', 'mixed']
        
        # When/Then - all should be accepted
        for semantic_type in valid_types:
            chunk = LLMChunkTestDataFactory.create_chunk_instance(semantic_types=semantic_type)
            assert chunk.semantic_types == semantic_type

    def test_multiple_semantic_types_in_one_string(self):
        """
        GIVEN multiple semantic types in a string
        WHEN LLMChunk is instantiated
        THEN raise ValidationError
        """
        # Given - multiple semantic types
        multi_types = "text,header"
        # When/Then - should raise ValidationError
        with pytest.raises(ValueError):
            _ = LLMChunkTestDataFactory.create_chunk_instance(semantic_types=multi_types)

    def test_invalid_semantic_types(self):
        """
        GIVEN invalid type for semantic type
        WHEN LLMChunk is instantiated
        THEN expect:
            - Invalid types raise pydantic ValidationError
        """
        # Given - invalid semantic types
        potentially_invalid_types = [
            123, 
            None, 
            ['text'], 
            {'text': 'value'}, 
            {"text"},
        ]
        
        # When/Then - each should raise ValidationError
        for semantic_type in potentially_invalid_types:
            with pytest.raises(ValueError):
                LLMChunkTestDataFactory.create_chunk_instance(semantic_types=semantic_type)

    def test_semantic_types_case_sensitivity_of_valid_types(self):
        """
        GIVEN valid semantic_types values with different casing
        WHEN LLMChunk is instantiated
        THEN expect:
            - Case variations of valid semantic_types should be normalized and accepted.
        """
        # Given - different case variations
        valid_case_variations = {
            'text': ['text', 'TEXT', 'Text', 'tEXt'],
            'table': ['table', 'TABLE', 'Table', 'tABle'],
            'figure_caption': ['figure_caption', 'FIGURE_CAPTION', 'Figure_Caption', 'fIGURE_cAPTION'],
            'header': ['header', 'HEADER', 'Header', 'hEAder'],
            'mixed': ['mixed', 'MIXED', 'Mixed', 'mIXed']
        }
        
        # When/Then - case-sensitive version of valid types should be normalized and accepted
        for type_mappings in valid_case_variations.items():
            for valid_type, type_mappings in type_mappings.items():
                for valid_variant in type_mappings:
                    chunk = LLMChunkTestDataFactory.create_chunk_instance(semantic_types=valid_variant)
                    assert chunk.semantic_types == valid_type

    def test_semantic_types_case_sensitivity_of_valid_types(self):
        """
        GIVEN invalid semantic_type values
        WHEN LLMChunk is instantiated
        THEN expect:
            - Each should raise ValidationError
        """
        import faker
        fake = faker.Faker()
        valid_types = ['text', 'table', 'figure_caption', 'header', 'mixed']

        invalid_types = {
            fake.word(),
            fake.color_name(),
            fake.first_name(),
            fake.company(),
            fake.city(),
            fake.job(),
            fake.catch_phrase(),
            fake.file_extension(),
            fake.domain_word(),
            fake.currency_code()
        }
        for valid_type in valid_types:
            invalid_types.discard(valid_type.upper())

        # Invalid case variants should raise errors
        for invalid_variant in invalid_types:
            with pytest.raises((ValidationError)):
                _ = LLMChunkTestDataFactory.create_chunk_instance(semantic_types=invalid_variant)

    def test_empty_semantic_types(self):
        """
        GIVEN empty semantic_types string
        WHEN LLMChunk is instantiated
        THEN expect raise ValidationError
        """
        with pytest.raises(ValueError):
            _ = LLMChunkTestDataFactory.create_chunk_instance(semantic_types="")



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
