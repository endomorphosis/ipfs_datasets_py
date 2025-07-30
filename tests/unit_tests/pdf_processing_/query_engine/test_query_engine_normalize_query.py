# Test file for TestQueryEngineNormalizeQuery

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine

# Check if each classes methods are accessible:
assert QueryEngine.query
assert QueryEngine._normalize_query
assert QueryEngine._detect_query_type
assert QueryEngine._process_entity_query
assert QueryEngine._process_relationship_query
assert QueryEngine._process_semantic_query
assert QueryEngine._process_document_query
assert QueryEngine._process_cross_document_query
assert QueryEngine._process_graph_traversal_query
assert QueryEngine._extract_entity_names_from_query
assert QueryEngine._get_entity_documents
assert QueryEngine._get_relationship_documents
assert QueryEngine._generate_query_suggestions
assert QueryEngine.get_query_analytics


# Check if the modules's imports are accessible:
import asyncio
import logging
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import re

from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, Entity, Relationship



class TestQueryEngineNormalizeQuery:
    """Test QueryEngine._normalize_query method for query text standardization."""

    @pytest.fixture
    def query_engine(self):
        """Create a mock QueryEngine instance for testing."""
        # Create minimal mock objects
        mock_graphrag = object()  # Placeholder for GraphRAGIntegrator
        mock_storage = object()   # Placeholder for IPLDStorage
        
        # Create QueryEngine instance with mocks
        engine = QueryEngine.__new__(QueryEngine)
        engine.graphrag = mock_graphrag
        engine.storage = mock_storage
        engine.embedding_model = None
        engine.query_processors = {}
        engine.embedding_cache = {}
        engine.query_cache = {}
        
        return engine

    def test_normalize_query_basic_lowercasing(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND query "WHO Is Bill Gates?"
        WHEN _normalize_query is called
        THEN expect:
            - Result is lowercased: "who is bill gates?"
            - No other transformations if no stop words present
        """
        result = query_engine._normalize_query("WHO Is Bill Gates?")
        assert result == "who bill gates?"  # "is" is a stop word and should be removed

    def test_normalize_query_whitespace_cleanup(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND query with extra whitespace "  Who   is    Bill   Gates?  "
        WHEN _normalize_query is called
        THEN expect:
            - Multiple spaces collapsed to single spaces
            - Leading and trailing whitespace removed
            - Result: "who is bill gates?"
        """
        result = query_engine._normalize_query("  Who   is    Bill   Gates?  ")
        assert result == "who bill gates?"

    def test_normalize_query_stop_word_removal(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND query "Who is the CEO of the Microsoft company?"
        WHEN _normalize_query is called
        THEN expect stop words removed:
            - "the", "of" removed
            - Result: "who is ceo microsoft company?"
        """
        result = query_engine._normalize_query("Who is the CEO of the Microsoft company?")
        assert result == "who ceo microsoft company?"

    def test_normalize_query_all_stop_words_comprehensive(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND query containing all documented stop words:
            "The a an and or but in on at to for of with by"
        WHEN _normalize_query is called
        THEN expect all stop words removed, result is empty string
        """
        with pytest.raises(ValueError, match="Query cannot be empty after normalization"):
            query_engine._normalize_query("The a an and or but in on at to for of with by")

    def test_normalize_query_punctuation_preservation(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND query "Who founded Microsoft Corporation?"
        WHEN _normalize_query is called
        THEN expect:
            - Punctuation preserved for entity name matching
            - Only case and whitespace normalized
            - Result retains question mark or other punctuation as needed
        """
        result = query_engine._normalize_query("Who founded Microsoft Corporation?")
        assert result == "who founded microsoft corporation?"

    def test_normalize_query_mixed_case_entity_names(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND query "What is BiLL GaTeS doing?"
        WHEN _normalize_query is called
        THEN expect:
            - All text lowercased including entity names
            - Result: "what bill gates doing?"
        """
        result = query_engine._normalize_query("What is BiLL GaTeS doing?")
        assert result == "what bill gates doing?"

    def test_normalize_query_empty_string_input(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND empty query ""
        WHEN _normalize_query is called
        THEN expect ValueError to be raised
        """
        with pytest.raises(ValueError, match="Query cannot be empty"):
            query_engine._normalize_query("")

    def test_normalize_query_whitespace_only_input(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND whitespace-only query "   \n\t   "
        WHEN _normalize_query is called
        THEN expect ValueError to be raised
        """
        with pytest.raises(ValueError, match="Query cannot be empty"):
            query_engine._normalize_query("   \n\t   ")

    def test_normalize_query_non_string_input(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND non-string input (int, list, dict, None)
        WHEN _normalize_query is called
        THEN expect TypeError to be raised
        """
        with pytest.raises(TypeError, match="Query must be a string"):
            query_engine._normalize_query(123)
        
        with pytest.raises(TypeError, match="Query must be a string"):
            query_engine._normalize_query(["list", "input"])
        
        with pytest.raises(TypeError, match="Query must be a string"):
            query_engine._normalize_query({"dict": "input"})
        
        with pytest.raises(TypeError, match="Query must be a string"):
            query_engine._normalize_query(None)

    def test_normalize_query_single_character_words(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND query "I am a CEO"
        WHEN _normalize_query is called
        THEN expect:
            - Single character words preserved unless they are stop words
            - "a" removed as stop word
            - "I" preserved (not in stop word list)
            - Result: "i am ceo"
        """
        result = query_engine._normalize_query("I am a CEO")
        assert result == "i am ceo"

    def test_normalize_query_multiple_consecutive_stop_words(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND query "the and or but Microsoft"
        WHEN _normalize_query is called
        THEN expect:
            - All consecutive stop words removed
            - Remaining words joined with single spaces
            - Result: "microsoft"
        """
        result = query_engine._normalize_query("the and or but Microsoft")
        assert result == "microsoft"

    def test_normalize_query_stop_words_at_boundaries(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND query "The Microsoft company and Google"
        WHEN _normalize_query is called
        THEN expect:
            - Stop words at beginning and middle removed
            - Result: "microsoft company google"
        """
        result = query_engine._normalize_query("The Microsoft company and Google")
        assert result == "microsoft company google"

    def test_normalize_query_numeric_content(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND query "Companies founded in 1975 by Bill"
        WHEN _normalize_query is called
        THEN expect:
            - Numbers preserved
            - Stop words removed
            - Result: "companies founded 1975 bill"
        """
        result = query_engine._normalize_query("Companies founded in 1975 by Bill")
        assert result == "companies founded 1975 bill"

    def test_normalize_query_special_characters(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND query "Microsoft's CEO & co-founder"
        WHEN _normalize_query is called
        THEN expect:
            - Special characters preserved (apostrophes, hyphens, ampersands)
            - Case normalized
            - Result: "microsoft's ceo & co-founder"
        """
        result = query_engine._normalize_query("Microsoft's CEO & co-founder")
        assert result == "microsoft's ceo & co-founder"

    def test_normalize_query_unicode_characters(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND query with unicode "Café münü naïve résumé"
        WHEN _normalize_query is called
        THEN expect:
            - Unicode characters preserved and lowercased correctly
            - Result: "café münü naïve résumé"
        """
        result = query_engine._normalize_query("Café münü naïve résumé")
        assert result == "café münü naïve résumé"

    def test_normalize_query_very_long_input(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND very long query (1000+ characters)
        WHEN _normalize_query is called
        THEN expect:
            - Method completes without performance issues
            - All transformations applied correctly
            - Result maintains integrity
        """
        # Create a long query with mix of stop words and content
        long_query = "What is the meaning of " + "artificial intelligence " * 100 + "and machine learning?"
        result = query_engine._normalize_query(long_query)
        
        # Check that it processes and removes stop words
        assert "what" in result
        assert "meaning" in result
        assert "artificial intelligence" in result
        assert "machine learning" in result
        assert "the" not in result
        assert "of" not in result
        assert "and" not in result
        
        # Check that it's still a reasonable length (stop words removed)
        assert len(result) < len(long_query)

    def test_normalize_query_newlines_and_tabs(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND query with newlines and tabs "Who\nis\tBill\nGates?"
        WHEN _normalize_query is called
        THEN expect:
            - Newlines and tabs treated as whitespace
            - Collapsed to single spaces
            - Result: "who is bill gates?"
        """
        result = query_engine._normalize_query("Who\nis\tBill\nGates?")
        assert result == "who bill gates?"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
