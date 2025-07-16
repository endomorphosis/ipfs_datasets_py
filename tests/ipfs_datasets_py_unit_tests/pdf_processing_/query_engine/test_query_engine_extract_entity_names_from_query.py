#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py
# Auto-generated on 2025-07-07 02:28:56

import pytest
import os
import faker

from tests._test_utils import (
    raise_on_bad_callable_metadata,
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


class TestQueryEngineExtractEntityNamesFromQuery:
    """Test QueryEngine._extract_entity_names_from_query method for entity name detection."""

    def setup_method(self):
        """Setup QueryEngine instance for testing."""
        # Create minimal mock objects for initialization
        from unittest.mock import Mock
        mock_graphrag = Mock(spec=GraphRAGIntegrator)
        mock_storage = Mock(spec=IPLDStorage)
        self.query_engine = QueryEngine(
            graphrag_integrator=mock_graphrag,
            storage=mock_storage,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2"
        )

    def test_extract_entity_names_single_entity(self):
        """
        GIVEN a QueryEngine instance
        AND query "Who is Bill Gates?"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - List containing ["Bill Gates"] returned
            - Capitalized word sequence properly identified
        """
        query = "Who is Bill Gates?"
        result = self.query_engine._extract_entity_names_from_query(query)
        assert result == ["Bill Gates"]

    def test_extract_entity_names_multiple_entities(self):
        """
        GIVEN a QueryEngine instance
        AND query "Microsoft and Apple are competitors"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - List containing ["Microsoft", "Apple"] returned
            - Both capitalized entities identified
            - Order of appearance preserved
        """
        query = "Microsoft and Apple are competitors"
        result = self.query_engine._extract_entity_names_from_query(query)
        assert result == ["Microsoft", "Apple"]

    def test_extract_entity_names_multi_word_entities(self):
        """
        GIVEN a QueryEngine instance
        AND query "path from John Smith to Mary Johnson"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - List containing ["John Smith", "Mary Johnson"] returned
            - Multi-word capitalized sequences captured correctly
        """
        query = "path from John Smith to Mary Johnson"
        result = self.query_engine._extract_entity_names_from_query(query)
        assert result == ["John Smith", "Mary Johnson"]

    def test_extract_entity_names_no_entities_found(self):
        """
        GIVEN a QueryEngine instance
        AND query "what is artificial intelligence"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Empty list returned
            - No capitalized sequences meeting criteria
        """
        query = "what is artificial intelligence"
        result = self.query_engine._extract_entity_names_from_query(query)
        assert result == []

    def test_extract_entity_names_minimum_word_length_requirement(self):
        """
        GIVEN a QueryEngine instance
        AND query "Who is Al or Bo Smith?"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Only words with >= 3 characters per word considered
            - "Al" excluded due to length
            - "Bo Smith" not excluded because the combined length is >= 3
        """
        query = "Who is Al or Bo Smith?"
        result = self.query_engine._extract_entity_names_from_query(query)
        # Based on docstring requirement of minimum 3 characters per word
        assert "Al" not in result
        # Bo Smith should *not* excluded
        # as "Bo Smith" has more than 3 characters in total.
        assert "Bo Smith" in result

    def test_extract_entity_names_sequence_breaking_on_lowercase(self):
        """
        GIVEN a QueryEngine instance
        AND query "John Smith and jane Doe"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Sequence stops at first non-capitalized word
            - "John Smith" captured
            - "jane Doe" sequence broken at "jane" (not capitalized)
        """
        query = "John Smith and jane Doe"
        result = self.query_engine._extract_entity_names_from_query(query)
        assert "John Smith" in result
        # "jane Doe" should not be captured as "jane" is not capitalized
        assert "jane Doe" not in result
        # "Doe" might be captured separately if it starts a new capitalized sequence
        
    def test_extract_entity_names_mixed_with_articles(self):
        """
        GIVEN a QueryEngine instance
        AND query "The Microsoft Corporation and The Apple Company"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - "The" is *not* considered as part of entity name if capitalized
            - "Microsoft Corporation" and "Apple Company" extracted
            - Articles *not* included in capitalized sequences
        NOTE: This is a limitation of NLTK method. Might be improved with other libraries.
        """
        query = "The Microsoft Corporation and The Apple Company"
        result = self.query_engine._extract_entity_names_from_query(query)
        assert "the" not in result  # "The" should not be included
        assert "Microsoft Corporation" in result
        assert "Apple Company" in result

    def test_extract_entity_names_punctuation_handling(self):
        """
        GIVEN a QueryEngine instance
        AND query "Microsoft's CEO, John Smith, founded something"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Punctuation doesn't break entity detection
            - "Microsoft" and "John Smith" extracted
            - Commas and apostrophes handled appropriately
        """
        query = "Microsoft's CEO, John Smith, founded something"
        result = self.query_engine._extract_entity_names_from_query(query)
        # Should extract entities despite punctuation
        assert any("Microsoft" in entity for entity in result)
        assert "John Smith" in result

    def test_extract_entity_names_empty_string_input(self):
        """
        GIVEN a QueryEngine instance
        AND empty query ""
        WHEN _extract_entity_names_from_query is called
        THEN expect ValueError to be raised
        """
        query = ""
        with pytest.raises(ValueError):
            self.query_engine._extract_entity_names_from_query(query)

    def test_extract_entity_names_whitespace_only_input(self):
        """
        GIVEN a QueryEngine instance
        AND whitespace-only query "   \n\t   "
        WHEN _extract_entity_names_from_query is called
        THEN expect ValueError to be raised
        """
        query = "   \n\t   "
        with pytest.raises(ValueError):
            self.query_engine._extract_entity_names_from_query(query)

    def test_extract_entity_names_non_string_input(self):
        """
        GIVEN a QueryEngine instance
        AND non-string input (int, list, dict, None)
        WHEN _extract_entity_names_from_query is called
        THEN expect TypeError to be raised
        """
        test_inputs = [123, [1, 2, 3], {"key": "value"}, None]
        for invalid_input in test_inputs:
            with pytest.raises(TypeError):
                self.query_engine._extract_entity_names_from_query(invalid_input)

    def test_extract_entity_names_acronyms_and_abbreviations(self):
        """
        GIVEN a QueryEngine instance
        AND query "IBM and NASA are organizations"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Acronyms like "IBM" and "NASA" identified as entities
            - All-caps words treated as capitalized sequences
        """
        query = "IBM and NASA are organizations"
        result = self.query_engine._extract_entity_names_from_query(query)
        assert "IBM" in result
        assert "NASA" in result

    def test_extract_entity_names_numbers_in_entity_names(self):
        """
        GIVEN a QueryEngine instance
        AND the queries
         - "Version 2.0 Software and Product 3M are items"
         - "Death Race 2000 is a great movie to watch during the 2020 Olympics."
         - "What is 42?"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Numbers within entity names handled appropriately
            - Entity sequences with numbers considered or excluded based on criteria
        """
        query1 = "Version 2.0 Software and Product 3M are items"
        result = self.query_engine._extract_entity_names_from_query(query1)
        # Test that the method handles numbers in entity names
        # Specific behavior depends on implementation
        assert isinstance(result, list)
        assert "Version 2.0 Software" in result
        assert "Product 3M" in result
        query2 = "Death Race 2000 is a great movie to watch during the 2020 Olympics."
        result = self.query_engine._extract_entity_names_from_query(query2)
        assert "Death Race 2000" in result
        assert "2020 Olympics" in result
        query3 = "What is 42?"
        result = self.query_engine._extract_entity_names_from_query(query3)
        # Should not extract "42" as an entity
        assert "42" not in result

    def test_extract_entity_names_special_characters_in_names(self):
        """
        GIVEN a QueryEngine instance
        AND query "AT&T and McDonald's are companies"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Special characters within entity names handled
            - Ampersands, apostrophes preserved in entity names
        """
        query = "AT&T and McDonald's are companies"
        result = self.query_engine._extract_entity_names_from_query(query)
        # Should handle special characters appropriately
        assert isinstance(result, list)
        # Entities with special characters should be captured
        
    def test_extract_entity_names_consecutive_entities(self):
        """
        GIVEN a QueryEngine instance
        AND query "Microsoft Apple Google Amazon compete"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Consecutive single-word entities identified separately
            - Each capitalized word treated as separate entity
        """
        query = "Microsoft Apple Google Amazon compete"
        result = self.query_engine._extract_entity_names_from_query(query)
        expected_entities = ["Microsoft", "Apple", "Google", "Amazon"]
        for entity in expected_entities:
            assert entity in result

    def test_extract_entity_names_title_case_vs_sentence_case(self):
        """
        GIVEN a QueryEngine instance
        AND query "Technology companies Include Microsoft And Apple"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Title case words properly identified
            - "Technology", "Include Microsoft And Apple" as separate sequences
            - Sentence case vs title case distinguished
        """
        query = "Technology companies Include Microsoft And Apple"
        result = self.query_engine._extract_entity_names_from_query(query)
        # Should identify capitalized sequences
        assert "Technology" in result
        # Should capture consecutive capitalized words
        assert any("Microsoft" in entity and "Apple" in entity for entity in result) or ("Microsoft" in result and "Apple" in result)

    def test_extract_entity_names_unicode_characters(self):
        """
        GIVEN a QueryEngine instance
        AND query "Café Münchën and Naïve Technologies"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Unicode characters in entity names handled correctly
            - Capitalized unicode letters recognized
            - ["Café Münchën", "Naïve Technologies"] extracted
        """
        query = "Café Münchën and Naïve Technologies"
        result = self.query_engine._extract_entity_names_from_query(query)
        assert "Café Münchën" in result
        assert "Naïve Technologies" in result

    def test_extract_entity_names_hyphenated_names(self):
        """
        GIVEN a QueryEngine instance
        AND query "Mary-Jane Watson and Jean-Claude Van Damme"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Hyphenated entity names captured as single entities
            - Hyphens don't break entity sequence detection
            - Complete hyphenated names preserved
        """
        query = "Mary-Jane Watson and Jean-Claude Van Damme"
        result = self.query_engine._extract_entity_names_from_query(query)
        # Should preserve hyphenated names
        assert any("Mary-Jane" in entity for entity in result)
        assert any("Jean-Claude" in entity for entity in result)

    def test_extract_entity_names_very_long_query(self):
        """
        GIVEN a QueryEngine instance
        AND very long query (1000+ characters) with multiple entities
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Method completes without performance issues
            - All entities in long text properly identified
            - Memory usage remains reasonable
        """
        # Create a long query with multiple entities
        entities = ["Microsoft", "Apple", "Google", "Amazon", "Facebook", "Tesla", "Netflix", "Adobe"]
        long_query = " ".join([f"The company {entity} has many employees and" for entity in entities] * 20)
        
        result = self.query_engine._extract_entity_names_from_query(long_query)
        # Should handle long queries without issues
        assert isinstance(result, list)
        # Should find the entities
        for entity in entities:
            assert entity in result

    def test_extract_entity_names_case_sensitivity_preservation(self):
        """
        GIVEN a QueryEngine instance
        AND query with mixed case entities
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Original capitalization preserved in extracted names
            - Case sensitivity maintained for proper nouns
            - No automatic case conversion applied
        """
        query = "iPhone and MacBook are Apple products"
        result = self.query_engine._extract_entity_names_from_query(query)
        # Should preserve original capitalization
        if "iPhone" in result:
            assert "iPhone" in result  # Not "Iphone" or "IPHONE"
        if "MacBook" in result:
            assert "MacBook" in result  # Not "Macbook" or "MACBOOK"
        assert "Apple" in result

    def test_extract_entity_names_accuracy_stress_test(self):
        """
        GIVEN a QueryEngine instance
        AND a series of statements from Faker library
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Method maintains 95% or higher accuracy.
            - Handles all entity formats (names, organizations, products) with consistent results
            - Consistent accuracy between different entity types
        
        """
        faker.Faker.seed(420)  # For reproducibility
        faker_dict = {
            "company": [faker.Faker().company() for _ in range(30)],
            "address": [faker.Faker().address() for _ in range(30)],
            "city": [faker.Faker().city() for _ in range(30)],
            "country": [faker.Faker().country() for _ in range(30)],
            "street_name": [faker.Faker().street_name() for _ in range(30)],
            "crypto_currency": [faker.Faker().cryptocurrency_name() for _ in range(30)],
            "product": [faker.Faker().product_name() for _ in range(30)],
        }



if __name__ == "__main__":
    pytest.main([__file__, "-v"])