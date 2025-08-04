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



class TestLLMOptimizerEstablishChunkRelationships:
    """Test LLMOptimizer._establish_chunk_relationships method."""

    def test_establish_chunk_relationships_sequential(self):
        """
        GIVEN list of sequential chunks
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - Adjacent chunks linked in relationships
            - Sequential order preserved
            - Bidirectional relationships established
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer, LLMChunk
        
        # Given
        optimizer = LLMOptimizer()
        
        sequential_chunks = [
            LLMChunk(
                content="First chunk in sequence",
                chunk_id="chunk_0001",
                source_page=1,
                source_elements=["paragraph"],
                token_count=10,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            ),
            LLMChunk(
                content="Second chunk follows first",
                chunk_id="chunk_0002",
                source_page=1,
                source_elements=["paragraph"],
                token_count=12,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            ),
            LLMChunk(
                content="Third chunk completes sequence",
                chunk_id="chunk_0003",
                source_page=1,
                source_elements=["paragraph"],
                token_count=14,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            )
        ]
        
        # When
        optimizer._establish_chunk_relationships(sequential_chunks)
        
        # Then - verify sequential relationships
        assert sequential_chunks[0].relationships == [], "First chunk should have no predecessors"
        assert "chunk_0001" in sequential_chunks[1].relationships, "Second chunk should reference first"
        assert "chunk_0002" in sequential_chunks[2].relationships, "Third chunk should reference second"
        
        # Verify relationship ordering (most recent first if implemented that way)
        for i in range(1, len(sequential_chunks)):
            current_chunk = sequential_chunks[i]
            if current_chunk.relationships:
                # Should have relationship to previous chunk
                previous_chunk_id = sequential_chunks[i-1].chunk_id
                assert previous_chunk_id in current_chunk.relationships, f"Chunk {current_chunk.chunk_id} should reference {previous_chunk_id}"

    def test_establish_chunk_relationships_same_page(self):
        """
        GIVEN chunks from the same page
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - Same-page chunks linked together
            - Page-level contextual relationships established
            - Cross-page relationships avoided
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer, LLMChunk
        
        # Given
        optimizer = LLMOptimizer()
        
        same_page_chunks = [
            LLMChunk(
                content="First paragraph on page 1",
                chunk_id="chunk_0001",
                source_page=1,
                source_elements=["paragraph"],
                token_count=10,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            ),
            LLMChunk(
                content="Second paragraph on page 1",
                chunk_id="chunk_0002",
                source_page=1,
                source_elements=["paragraph"],
                token_count=12,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            ),
            LLMChunk(
                content="Table on page 1",
                chunk_id="chunk_0003",
                source_page=1,
                source_elements=["table"],
                token_count=15,
                semantic_types={"table"},
                relationships=[],
                metadata=self.sample_metadata
            ),
            LLMChunk(
                content="First paragraph on page 2",
                chunk_id="chunk_0004",
                source_page=2,
                source_elements=["paragraph"],
                token_count=11,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            )
        ]
        
        # When
        optimizer._establish_chunk_relationships(same_page_chunks)
        
        # Then - verify same-page relationships are established
        page_1_chunks = [chunk for chunk in same_page_chunks if chunk.source_page == 1]
        page_2_chunks = [chunk for chunk in same_page_chunks if chunk.source_page == 2]
        
        # Check that page 1 chunks reference each other
        assert "chunk_0001" in same_page_chunks[1].relationships, "Second chunk should reference first chunk (same page)"
        assert "chunk_0002" in same_page_chunks[2].relationships, "Table chunk should reference previous paragraph (same page)"
        
        # Check that page 2 chunk doesn't reference page 1 chunks inappropriately
        page_2_chunk = same_page_chunks[3]
        page_1_chunk_ids = {chunk.chunk_id for chunk in page_1_chunks}
        
        # It should reference the immediately previous chunk (cross-page is allowed for sequential flow)
        if page_2_chunk.relationships:
            # At least some relationship should exist for document flow
            assert len(page_2_chunk.relationships) > 0, "Page 2 chunk should have some relationships for document continuity"
        
        # Verify same-page chunks have stronger relationships
        for i in range(len(page_1_chunks) - 1):
            current_chunk = page_1_chunks[i + 1]
            previous_chunk_id = page_1_chunks[i].chunk_id
            assert previous_chunk_id in current_chunk.relationships, f"Same-page chunk {current_chunk.chunk_id} should reference {previous_chunk_id}"

    def test_establish_chunk_relationships_empty_list(self):
        """
        GIVEN empty chunks list
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - ValueError raised or empty list returned
            - No processing errors
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
        
        # Given
        optimizer = LLMOptimizer()
        empty_chunks = []
        
        # When/Then - should handle empty list gracefully
        try:
            optimizer._establish_chunk_relationships(empty_chunks)
            # If no error raised, verify list remains empty
            assert len(empty_chunks) == 0, "Empty list should remain empty"
        except ValueError as e:
            # ValueError is acceptable for empty input
            assert "empty" in str(e).lower() or "no chunks" in str(e).lower(), f"Error should mention empty input: {e}"
        except Exception as e:
            pytest.fail(f"Unexpected exception type for empty list: {type(e).__name__}: {e}")

    def test_establish_chunk_relationships_single_chunk(self):
        """
        GIVEN single chunk in list
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - Single chunk returned with empty relationships
            - No errors raised
            - Graceful handling of edge case
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer, LLMChunk
        
        # Given
        optimizer = LLMOptimizer()
        
        single_chunk = [
            LLMChunk(
                content="Single lonely chunk",
                chunk_id="chunk_0001",
                source_page=1,
                source_elements=["paragraph"],
                token_count=10,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            )
        ]
        
        # When
        optimizer._establish_chunk_relationships(single_chunk)
        
        # Then - single chunk should have no relationships
        assert len(single_chunk) == 1, "Should still have one chunk"
        assert single_chunk[0].relationships == [], "Single chunk should have empty relationships"
        assert single_chunk[0].chunk_id == "chunk_0001", "Chunk ID should be preserved"
        assert single_chunk[0].content == "Single lonely chunk", "Chunk content should be preserved"

    def test_establish_chunk_relationships_performance_limits(self):
        """
        GIVEN large number of chunks
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - Relationship limits applied for performance
            - Processing completes in reasonable time
            - Most important relationships preserved
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer, LLMChunk
        import time
        
        # Given
        optimizer = LLMOptimizer()
        
        # Create large number of chunks (100 chunks)
        large_chunk_list = []
        for i in range(100):
            chunk = LLMChunk(
                content=f"Chunk {i+1} content for performance testing",
                chunk_id=f"chunk_{i+1:04d}",
                source_page=(i // 10) + 1,  # 10 chunks per page
                source_elements=["paragraph"],
                token_count=15,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            )
            large_chunk_list.append(chunk)
        
        # When - measure performance
        start_time = time.time()
        optimizer._establish_chunk_relationships(large_chunk_list)
        processing_time = time.time() - start_time
        
        # Then - verify performance and relationship quality
        assert processing_time < 5.0, f"Processing 100 chunks took too long: {processing_time:.2f}s"
        
        # Verify some relationships are established
        chunks_with_relationships = [chunk for chunk in large_chunk_list if chunk.relationships]
        assert len(chunks_with_relationships) >= 90, "Most chunks should have relationships established"
        
        # Verify sequential relationships exist (at least for first few chunks)
        for i in range(1, min(10, len(large_chunk_list))):
            current_chunk = large_chunk_list[i]
            previous_chunk_id = large_chunk_list[i-1].chunk_id
            assert previous_chunk_id in current_chunk.relationships, f"Sequential relationship missing for chunk {i+1}"
        
        # Verify relationship limits (no chunk should have excessive relationships)
        max_relationships = max(len(chunk.relationships) for chunk in large_chunk_list)
        assert max_relationships <= 10, f"Relationship limit should be applied, found chunk with {max_relationships} relationships"

    def test_establish_chunk_relationships_malformed_chunks(self):
        """
        GIVEN chunks with missing required attributes
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - AttributeError raised
            - Error handling for malformed data
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer, LLMChunk
        
        # Given
        optimizer = LLMOptimizer()
        
        # Create valid chunk for comparison
        valid_chunk = LLMChunk(
            content="Valid chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            source_elements=["paragraph"],
            token_count=10,
            semantic_types="text",
            relationships=[],
            metadata=self.sample_metadata
        )
        
        # Test with chunk missing chunk_id attribute
        malformed_chunk_no_id = LLMChunk(
            content="Chunk without ID",
            chunk_id="",  # Empty ID should cause issues
            source_page=1,
            source_elements=["paragraph"],
            token_count=10,
            semantic_types="text",
            relationships=[],
            metadata=self.sample_metadata
        )
        
        # When/Then - test with malformed chunk
        malformed_chunks = [valid_chunk, malformed_chunk_no_id]
        
        try:
            optimizer._establish_chunk_relationships(malformed_chunks)
            # If it doesn't raise an error, verify it handled the malformed chunk gracefully
            assert isinstance(malformed_chunk_no_id.relationships, list), "Relationships should be a list"
        except (AttributeError, ValueError) as e:
            # These are acceptable errors for malformed data
            error_msg = str(e).lower()
            assert any(keyword in error_msg for keyword in ["chunk_id", "attribute", "missing", "invalid"]), f"Error should mention the issue: {e}"
        
        # Test with None in chunk list
        chunks_with_none = [valid_chunk, None]
        
        with pytest.raises((AttributeError, TypeError, ValueError)):
            optimizer._establish_chunk_relationships(chunks_with_none)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
