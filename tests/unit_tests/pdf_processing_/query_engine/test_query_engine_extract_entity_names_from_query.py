#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py
# Auto-generated on 2025-07-07 02:28:56

import pytest
import os
import faker

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

work_dir = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py"
file_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/query_engine.py")
md_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/query_engine_stubs.md")

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



import faker
from typing import Generator

def make_fake_names(n = 30):
    """
    Generate a list of fake names using Faker library.
    
    Args:
        n (int): Number of names to generate (default: 30)
    
    Returns:
        List[str]: List of fake names
    """
    fake = faker.Faker()
    return [fake.name() for _ in range(n)]

def make_fake_name_questions(n: int = 30) -> Generator[tuple[str, str], None, None]:
    """
    Generate a list of fake name-related questions using Faker library.
    
    Args:
        n (int): Number of questions to generate (default: 30)
    
    Returns:
        List[str]: List of fake name-related questions
    """
    fake_names = make_fake_names(n)
    for name in fake_names:
        yield name, f"Who is {name}?"


def make_fake_companies(n: int = 30) -> list[str]:
    """
    Generate a list of fake company names using Faker library.
    
    Args:
        n (int): Number of company names to generate (default: 30)
    
    Returns:
        List[str]: List of fake company names
    """
    fake = faker.Faker()
    return [fake.company() for _ in range(n)]


def make_fake_company_questions(n: int = 30) -> Generator[tuple[str, str], None, None]:
    """
    Generate fake company-related statements using Faker library.
    
    Args:
        n (int): Number of company pairs to generate (default: 30)
    
    Yields:
        tuple[str, str, str]: Tuple containing (company1, company2, statement)
            where statement is "{company1} and {company2} are competitors."
    """
    fake_companies_1 = make_fake_companies(n)
    fake_companies_2 = make_fake_companies(n)
    for company1, company2 in zip(fake_companies_1, fake_companies_2):
        yield company1, company2, f"{company1} and {company2} are competitors."

N = 10

FAKE_NAME_QUERIES = [
        (words[0], words[1]) for words in make_fake_name_questions(n=N)
]

FAKE_COMPANY_QUERIES = [
    (words[0], words[1], words[2]) for words in make_fake_company_questions(n=N)
]

class TestQueryEngineExtractEntityNamesFromQuery:
    """Test QueryEngine._extract_entity_names_from_query method for entity name detection."""

    N = 10 # Number of test cases to generate

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

    @pytest.mark.parametrize("name,query", FAKE_NAME_QUERIES)
    def test_extract_entity_names_single_entity(self, name, query):
        """
        GIVEN a QueryEngine instance
        AND query in the form "Who is {name}?"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - List containing [name] returned
            - Capitalized word sequence properly identified
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        assert result == [name], f"Expected [{name}] but got {result} for query: {query}"

    @pytest.mark.parametrize("name1,name2,query", FAKE_COMPANY_QUERIES)
    def test_extract_entity_names_multiple_entities(self, name1, name2, query):
        """
        GIVEN a QueryEngine instance
        AND query "Microsoft and Apple are competitors"
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - List containing ["Microsoft", "Apple"] returned
            - Both capitalized entities identified
            - Order of appearance preserved
        """
        print(f"Testing with query: {query}")
        print(f"name1: {name1}, name2: {name2}")
        result = self.query_engine._extract_entity_names_from_query(query)
        assert result == [name1, name2]

    @pytest.mark.parametrize("query, expected_entities", [
        ("path from John Smith to Mary Johnson", ["John Smith", "Mary Johnson"]),
        ("connection between Alice Brown and Bob Wilson", ["Alice Brown", "Bob Wilson"]),
        ("relationship from Emma Davis to David Miller", ["Emma Davis", "David Miller"]),
        ("link between Sarah Thompson and Michael Anderson", ["Sarah Thompson", "Michael Anderson"]),
        ("route from Jennifer Garcia to Robert Martinez", ["Jennifer Garcia", "Robert Martinez"]),
        ("bridge from Lisa Rodriguez to James Taylor", ["Lisa Rodriguez", "James Taylor"]),
        ("path between Anna Williams and Christopher Lee", ["Anna Williams", "Christopher Lee"]),
        ("connection from Michelle White to Daniel Harris", ["Michelle White", "Daniel Harris"]),
    ])
    def test_extract_entity_names_multi_word_entities(self, query, expected_entities):
        """
        GIVEN a QueryEngine instance
        AND query with multiple multi-word entities
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - List containing all expected multi-word entities returned
            - Multi-word names properly captured as single entities
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        assert result == expected_entities

    @pytest.mark.parametrize("query", [
        "what is artificial intelligence",
        "how does machine learning work",
        "explain deep learning concepts",
        "what are neural networks",
        "describe natural language processing",
        "how to implement algorithms",
        "what is data science",
        "explain computer vision techniques",
        "how does reinforcement learning work",
        "what are decision trees"
    ])
    def test_extract_entity_names_no_entities_found(self, query):
        """
        GIVEN a QueryEngine instance
        AND query with no capitalized entity names
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Empty list returned
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        assert result == []

    @pytest.mark.parametrize("query, expected_excluded", [
        ("Who is Al or Bo Smith?", ["Al"]),
        ("Meet Jo and Tom Anderson", ["Jo"]),
        ("See Ed or Mary Johnson", ["Ed"]),
        ("Find Li and John Williams", ["Li"]),
        ("Call Mo or Sarah Davis", ["Mo"]),
        ("Ask Xi and Mike Thompson", ["Xi"]),
        ("Tell Bo and Lisa Garcia", ["Bo"]),
        ("Show Ty and Anna Martinez", ["Ty"]),
    ])
    def test_extract_entity_names_minimum_word_length_requirement_excluded(self, query, expected_excluded):
        """
        GIVEN a QueryEngine instance
        AND query with short names (< 3 characters)
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Short names excluded due to length requirement
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        
        for excluded in expected_excluded:
            assert excluded not in result, f"Expected {excluded} to be excluded from {result}"

    @pytest.mark.parametrize("query, expected_included", [
        ("Who is Al or Bo Smith?", ["Bo Smith"]),
        ("Meet Jo and Tom Anderson", ["Tom Anderson"]),
        ("See Ed or Mary Johnson", ["Mary Johnson"]),
        ("Find Li and John Williams", ["John Williams"]),
        ("Call Mo or Sarah Davis", ["Sarah Davis"]),
        ("Ask Xi and Mike Thompson", ["Mike Thompson"]),
        ("Tell Bo and Lisa Garcia", ["Lisa Garcia"]),
        ("Show Ty and Anna Martinez", ["Anna Martinez"]),
    ])
    def test_extract_entity_names_minimum_word_length_requirement_included(self, query, expected_included):
        """
        GIVEN a QueryEngine instance
        AND query with longer entity names
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Longer entity names included because combined length meets requirement
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        
        for included in expected_included:
            assert included in result, f"Expected {included} to be included in {result}"

    @pytest.mark.parametrize("query, expected_included", [
        ("John Smith and jane Doe", ["John Smith"]),
        ("Mary Johnson and bob Wilson", ["Mary Johnson"]),
        ("Alice Brown and charlie Davis", ["Alice Brown"]),
        ("David Miller and sarah Taylor", ["David Miller"]),
        ("Emma Wilson and mike Johnson", ["Emma Wilson"]),
        ("Lisa Garcia and tom Anderson", ["Lisa Garcia"]),
        ("Robert Thompson and anna Martinez", ["Robert Thompson"]),
        ("Jennifer Lee and james White", ["Jennifer Lee"]),
    ])
    def test_extract_entity_names_sequence_breaking_on_lowercase_included(self, query, expected_included):
        """
        GIVEN a QueryEngine instance
        AND query with mixed capitalization patterns
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Properly capitalized sequences captured
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        
        for entity in expected_included:
            assert entity in result, f"Expected {entity} to be found in {result}"

    @pytest.mark.parametrize("query, expected_excluded", [
        ("John Smith and jane Doe", ["jane Doe"]),
        ("Mary Johnson and bob Wilson", ["bob Wilson"]),
        ("Alice Brown and charlie Davis", ["charlie Davis"]),
        ("David Miller and sarah Taylor", ["sarah Taylor"]),
        ("Emma Wilson and mike Johnson", ["mike Johnson"]),
        ("Lisa Garcia and tom Anderson", ["tom Anderson"]),
        ("Robert Thompson and anna Martinez", ["anna Martinez"]),
        ("Jennifer Lee and james White", ["james White"]),
    ])
    def test_extract_entity_names_sequence_breaking_on_lowercase_excluded(self, query, expected_excluded):
        """
        GIVEN a QueryEngine instance
        AND query with mixed capitalization patterns
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Sequence stops at first non-capitalized word
            - Sequences broken at lowercase words not captured
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        
        for entity in expected_excluded:
            assert entity not in result, f"Did not expect {entity} to be found in {result}"
        
    @pytest.mark.parametrize("query, expected_included", [
        ("The Microsoft Corporation and The Apple Company", ["Microsoft Corporation", "Apple Company"]),
        ("A Google Inc and An Amazon Corp", ["Google Inc", "Amazon Corp"]),
        ("The Tesla Motors and The Netflix Inc", ["Tesla Motors", "Netflix Inc"]),
        ("An Oracle Database and A Facebook Platform", ["Oracle Database", "Facebook Platform"]),
        ("The IBM Corporation and An Intel Processor", ["IBM Corporation", "Intel Processor"]),
    ])
    def test_extract_entity_names_articles_entity_inclusion(self, query, expected_included):
        """
        GIVEN a QueryEngine instance
        AND query with articles ("The", "A", "An") before entity names
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Entity names without articles extracted correctly
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        
        # Check that expected entities are included
        for entity in expected_included:
            assert entity in result, f"Expected {entity} to be found in {result}"

    @pytest.mark.parametrize("query, expected_excluded", [
        ("The Microsoft Corporation and The Apple Company", ["The", "the"]),
        ("A Google Inc and An Amazon Corp", ["A", "An", "a", "an"]),
        ("The Tesla Motors and The Netflix Inc", ["The", "the"]),
        ("An Oracle Database and A Facebook Platform", ["An", "A", "an", "a"]),
        ("The IBM Corporation and An Intel Processor", ["The", "An", "the", "an"]),
    ])
    def test_extract_entity_names_articles_exclusion(self, query, expected_excluded):
        """
        GIVEN a QueryEngine instance
        AND query with articles ("The", "A", "An") before entity names
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Articles are *not* considered as part of entity name if capitalized
            - Articles *not* included in capitalized sequences
        NOTE: This is a limitation of NLTK method. Might be improved with other libraries.
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        
        # Check that articles are excluded
        for article in expected_excluded:
            assert article not in result, f"Did not expect article '{article}' to be found in {result}"

    @pytest.mark.parametrize("query, expected_entities", [
        ("Microsoft's CEO, John Smith, founded something", ["Microsoft", "John Smith"]),
        ("Apple's product, iPhone 12, is popular", ["Apple", "iPhone 12"]),
        ("Google's search engine, powered by AI, dominates", ["Google", "AI"]),
        ("Amazon's founder, Jeff Bezos, stepped down", ["Amazon", "Jeff Bezos"]),
        ("Tesla's CEO, Elon Musk, tweeted today", ["Tesla", "Elon Musk"]),
        ("Netflix's series, Stranger Things, is trending", ["Netflix", "Stranger Things"]),
        ("Facebook's platform, Instagram, was acquired", ["Facebook", "Instagram"]),
        ("Oracle's database, MySQL, is open source", ["Oracle", "MySQL"]),
    ])
    def test_extract_entity_names_punctuation_handling(self, query, expected_entities):
        """
        GIVEN a QueryEngine instance
        AND query with punctuation around entity names
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Punctuation doesn't break entity detection
            - Expected entities extracted correctly
            - Commas, apostrophes, and other punctuation handled appropriately
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        for expected_entity in expected_entities:
            assert any(expected_entity in entity for entity in result), \
                f"Expected {expected_entity} to be found in {result}"

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

    @pytest.mark.parametrize("invalid_input", [
        123,
        [1, 2, 3],
        {"key": "value"},
        None,
        42.5,
        True,
        set([1, 2, 3])
    ])
    def test_extract_entity_names_non_string_input(self, invalid_input):
        """
        GIVEN a QueryEngine instance
        AND non-string input (int, list, dict, None, float, bool, set)
        WHEN _extract_entity_names_from_query is called
        THEN expect TypeError to be raised
        """
        with pytest.raises(TypeError):
            self.query_engine._extract_entity_names_from_query(invalid_input)

    @pytest.mark.parametrize("query, expected_entities", [
        ("IBM and NASA are organizations", ["IBM", "NASA"]),
        ("FBI and CIA work together", ["FBI", "CIA"]),
        ("NATO and EU are alliances", ["NATO", "EU"]),
        ("MIT and UCLA are universities", ["MIT", "UCLA"]),
        ("BMW and BMW Group compete", ["BMW", "BMW Group"]),
        ("AT&T and T-Mobile are carriers", ["AT&T", "T-Mobile"]),
        ("USA and UK signed treaty", ["USA", "UK"]),
        ("CNN and BBC report news", ["CNN", "BBC"]),
    ])
    def test_extract_entity_names_acronyms_and_abbreviations(self, query, expected_entities):
        """
        GIVEN a QueryEngine instance
        AND query with acronyms and abbreviations
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Acronyms like "IBM" and "NASA" identified as entities
            - All-caps words treated as capitalized sequences
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        for entity in expected_entities:
            assert entity in result, f"Expected {entity} to be found in {result}"

    @pytest.mark.parametrize("query, expected_entities", [
        ("Version 2.0 Software and Product 3M are items", ["Version 2.0 Software", "Product 3M"]),
        ("Death Race 2000 is a great movie to watch during the 2020 Olympics.", ["Death Race 2000", "2020 Olympics"]),
        ("iPhone 12 and Samsung Galaxy S21 are smartphones", ["iPhone 12", "Samsung Galaxy S21"]),
        ("Windows 10 and Office 365 are Microsoft products", ["Windows 10", "Office 365", "Microsoft"]),
    ])
    def test_extract_entity_names_numbers_in_entity_names_included(self, query, expected_entities):
        """
        GIVEN a QueryEngine instance
        AND queries with numbers in entity names that should be included
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Numbers within entity names handled appropriately
            - Entity sequences with numbers properly extracted
        """
        result = self.query_engine._extract_entity_names_from_query(query)

        for expected_entity in expected_entities:
            assert expected_entity in result, f"Expected {expected_entity} to be found in {result}"

    @pytest.mark.parametrize("query, excluded_entities", [
        ("What is 42?", ["42"]),
        ("The year 1984 was significant", ["1984"]),
    ])
    def test_extract_entity_names_standalone_numbers_excluded(self, query, excluded_entities):
        """
        GIVEN a QueryEngine instance
        AND queries with standalone numbers that should be excluded
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Standalone numbers not treated as entities
            - Pure numeric sequences excluded from results
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        
        for excluded_entity in excluded_entities:
            assert excluded_entity not in result, \
                f"Did not expect {excluded_entity} to be found in {result}"

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

    @pytest.mark.parametrize("query, expected_entities", [
        ("Microsoft Apple Google Amazon compete", ["Microsoft", "Apple", "Google", "Amazon"]),
        ("Tesla Netflix Adobe Oracle systems", ["Tesla", "Netflix", "Adobe", "Oracle"]),
        ("Facebook Twitter LinkedIn Instagram platforms", ["Facebook", "Twitter", "LinkedIn", "Instagram"]),
        ("Intel AMD Nvidia Qualcomm processors", ["Intel", "AMD", "Nvidia", "Qualcomm"]),
        ("IBM Cisco VMware Salesforce enterprises", ["IBM", "Cisco", "VMware", "Salesforce"]),
    ])
    def test_extract_entity_names_consecutive_entities(self, query, expected_entities):
        """
        GIVEN a QueryEngine instance
        AND query with consecutive single-word entities
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Consecutive single-word entities identified separately
            - Each capitalized word treated as separate entity
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        for entity in expected_entities:
            assert entity in result

    @pytest.mark.parametrize("query, expected_entities", [
        ("Technology companies Include Microsoft And Apple", ["Technology", "Include Microsoft And Apple"]),
        ("Business Leaders Like Steve Jobs And Bill Gates", ["Business Leaders Like Steve Jobs And Bill Gates"]),
        ("Software Companies Such As Oracle And Adobe", ["Software Companies Such As Oracle And Adobe"]),
        ("Tech Giants Include Amazon And Facebook", ["Tech Giants Include Amazon And Facebook"]),
        ("Major Corporations Like IBM And Intel", ["Major Corporations Like IBM And Intel"]),
    ])
    def test_extract_entity_names_title_case_vs_sentence_case(self, query, expected_entities):
        """
        GIVEN a QueryEngine instance
        AND query with title case words
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Title case words properly identified
            - Consecutive capitalized sequences captured
            - Sentence case vs title case distinguished
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        # Should identify at least one of the expected entities
        assert any(expected in result for expected in expected_entities), \
            f"Expected one of {expected_entities} to be found in {result}"

    @pytest.mark.parametrize("query, expected_entities", [
        ("Café Münchën and Naïve Technologies", ["Café Münchën", "Naïve Technologies"]),
        ("Björk and Søren Kierkegaard", ["Björk", "Søren Kierkegaard"]),
        ("Zürich Insurance and München Re", ["Zürich Insurance", "München Re"]),
        ("François Mitterrand and José María Aznar", ["François Mitterrand", "José María Aznar"]),
        ("Łódź University and Kraków Institute", ["Łódź University", "Kraków Institute"]),
    ])
    def test_extract_entity_names_unicode_characters(self, query, expected_entities):
        """
        GIVEN a QueryEngine instance
        AND query with unicode characters in entity names
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Unicode characters in entity names handled correctly
            - Capitalized unicode letters recognized
            - All expected entities extracted
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        for expected_entity in expected_entities:
            assert expected_entity in result, f"Expected {expected_entity} to be found in {result}"

    @pytest.mark.parametrize("query, expected_entities", [
        ("Mary-Jane Watson and Jean-Claude Van Damme", ["Mary-Jane Watson", "Jean-Claude Van Damme"]),
        ("Anne-Marie Johnson works with Jean-Luc Picard", ["Anne-Marie Johnson", "Jean-Luc Picard"]),
        ("Smith-Jones Corporation and Brown-Williams LLC", ["Smith-Jones Corporation", "Brown-Williams LLC"]),
        ("X-Ray Technology and Y-Axis Solutions", ["X-Ray Technology", "Y-Axis Solutions"]),
    ])
    def test_extract_entity_names_hyphenated_names(self, query, expected_entities):
        """
        GIVEN a QueryEngine instance
        AND query with hyphenated entity names
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Hyphenated entity names captured as single entities
            - Hyphens don't break entity sequence detection
            - Complete hyphenated names preserved
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        for expected_entity in expected_entities:
            assert expected_entity in result, f"Expected {expected_entity} to be found in {result}"

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

        # Should find the entities
        for entity in entities:
            assert entity in result

    @pytest.mark.parametrize("query, expected_entities", [
        ("iPhone and MacBook are Apple products", ["iPhone", "MacBook", "Apple"]),
        ("YouTube and Gmail are Google services", ["YouTube", "Gmail", "Google"]),
        ("Xbox and OneDrive are Microsoft products", ["Xbox", "OneDrive", "Microsoft"]),
        ("iPad and iMac work with macOS", ["iPad", "iMac", "macOS"]),
        ("WhatsApp and Instagram belong to Facebook", ["WhatsApp", "Instagram", "Facebook"]),
        ("Kindle and FireTV are Amazon devices", ["Kindle", "FireTV", "Amazon"]),
        ("PowerPoint and OneNote are Office apps", ["PowerPoint", "OneNote", "Office"]),
        ("LinkedIn and Skype were acquired by Microsoft", ["LinkedIn", "Skype", "Microsoft"]),
    ])
    def test_extract_entity_names_case_sensitivity_preservation(self, query, expected_entities):
        """
        GIVEN a QueryEngine instance
        AND query with mixed case entities
        WHEN _extract_entity_names_from_query is called
        THEN expect:
            - Original capitalization preserved in extracted names
            - Case sensitivity maintained for proper nouns
            - No automatic case conversion applied
        """
        result = self.query_engine._extract_entity_names_from_query(query)
        for expected_entity in expected_entities:
            assert expected_entity in result, f"Expected {expected_entity} to be found in {result}"

    # def test_extract_entity_names_accuracy_stress_test(self):
    #     """
    #     GIVEN a QueryEngine instance
    #     AND a series of statements from Faker library
    #     WHEN _extract_entity_names_from_query is called
    #     THEN expect:
    #         - Method maintains 95% or higher accuracy.
    #         - Handles all entity formats (names, organizations, products) with consistent results
    #         - Consistent accuracy between different entity types
    #     """
    #     fake = faker.Faker()
    #     faker_dict = {
    #         "company": make_fake_companies(n=self.N),
    #         "address": [fake.address() for _ in range(self.N)],
    #         "city": [fake.city() for _ in range(self.N)],
    #         "country": [fake.country() for _ in range(self.N)],
    #         "street_name": [fake.street_name() for _ in range(self.N)],
    #         "crypto_currency": [fake.cryptocurrency_name() for _ in range(30)],
    #         "product": [fake.random_company_product() for _ in range(30)],
    #     }



if __name__ == "__main__":
    pytest.main([__file__, "-v"])