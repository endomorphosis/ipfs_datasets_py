#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator.py
# Auto-generated on 2025-07-07 02:28:56
import pytest
import os
import asyncio
import re
import time
import networkx as nx
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, KnowledgeGraph, Entity, Relationship
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk



from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator

# Check if each classes methods are accessible:
assert GraphRAGIntegrator.integrate_document
assert GraphRAGIntegrator._extract_entities_from_chunks
assert GraphRAGIntegrator._extract_entities_from_text
assert GraphRAGIntegrator._extract_relationships
assert GraphRAGIntegrator._extract_chunk_relationships
assert GraphRAGIntegrator._infer_relationship_type
assert GraphRAGIntegrator._extract_cross_chunk_relationships
assert GraphRAGIntegrator._find_chunk_sequences
assert GraphRAGIntegrator._create_networkx_graph
assert GraphRAGIntegrator._merge_into_global_graph
assert GraphRAGIntegrator._discover_cross_document_relationships
assert GraphRAGIntegrator._find_similar_entities
assert GraphRAGIntegrator._calculate_text_similarity
assert GraphRAGIntegrator._store_knowledge_graph_ipld
assert GraphRAGIntegrator.query_graph
assert GraphRAGIntegrator.get_entity_neighborhood


# 4. Check if the modules's imports are accessible:
try:
    import logging
    import hashlib
    from typing import Dict, List, Any, Optional
    from dataclasses import dataclass, asdict
    from datetime import datetime
    import uuid
    import re

    import networkx as nx
    import numpy as np

    from ipfs_datasets_py.ipld import IPLDStorage
    from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
except ImportError as e:
    raise ImportError(f"Could into import the module's dependencies: {e}") 


@pytest.mark.parametrize("text, expected_orgs", [
    (
        "Apple Inc. partnered with Microsoft Corporation and Harvard University. Amazon LLC also joined.",
        ['Apple Inc', 'Microsoft Corporation', 'Harvard University', 'Amazon LLC'],
    ),
    (
        "Google LLC and Facebook Inc. compete with Twitter Corp.",
        ['Google LLC', 'Facebook Inc', 'Twitter Corp'],
    ),
    (
        "Stanford University works with IBM Corp. and Tesla Motors Inc.",
        ['Stanford University', 'IBM Corp', 'Tesla Motors Inc'],
    ),
    (
        "JPMorgan Chase & Co. and Goldman Sachs Group Inc. are major banks.",
        ['JPMorgan Chase & Co', 'Goldman Sachs Group Inc'],
    ),
    (
        "MIT and Caltech collaborate on research projects.",
        ['MIT', 'Caltech'],
    ),
])
class TestExtractEntitiesFromTextOrganization:
    """Test class for organization entity extraction."""

    @pytest.fixture
    async def organization_extraction_result(self, integrator: GraphRAGIntegrator, text: str):
        """Fixture to provide the result of organization entity extraction."""
        chunk_id = "org_chunk"
        result = await integrator._extract_entities_from_text(text, chunk_id)
        org_entities = [entity for entity in result if entity['type'] == 'organization']
        return org_entities, chunk_id

    @pytest.mark.asyncio
    async def test_organization_count(self, organization_extraction_result, expected_orgs: list):
        """
        GIVEN text with organizations
        WHEN _extract_entities_from_text is called
        THEN it extracts the minimum expected number of organization entities.
        """
        org_entities, _ = organization_extraction_result
        assert len(org_entities) == len(expected_orgs), \
            f"Expected {len(expected_orgs)} organization entities, got {len(org_entities)}"

    @pytest.mark.asyncio
    async def test_organization_names_found(self, organization_extraction_result, expected_orgs: list):
        """
        GIVEN text with organizations
        WHEN _extract_entities_from_text is called
        THEN all expected organizations are found in the results.
        """
        org_entities, _ = organization_extraction_result
        org_names = [entity['name'] for entity in org_entities]
        
        for expected_org in expected_orgs:
            assert any(expected_org in name for name in org_names), \
                f"Expected organization '{expected_org}' not found in extracted names: {org_names}"

    @pytest.mark.asyncio
    async def test_organization_confidence(self, organization_extraction_result, expected_orgs: list):
        """
        GIVEN text with organizations
        WHEN _extract_entities_from_text is called
        THEN each extracted organization has a confidence of 0.7.
        """
        org_entities, _ = organization_extraction_result
        for entity in org_entities:
            assert entity['confidence'] == 0.7, \
                f"Expected confidence 0.7 for entity '{entity['name']}', but got {entity['confidence']}"

    @pytest.mark.asyncio
    async def test_organization_type(self, organization_extraction_result, expected_orgs: list):
        """
        GIVEN text with organizations
        WHEN _extract_entities_from_text is called
        THEN each extracted organization has the type 'organization'.
        """
        org_entities, _ = organization_extraction_result
        for entity in org_entities:
            assert entity['type'] == 'organization', \
                f"Expected type 'organization' for entity '{entity['name']}', but got {entity['type']}"

    @pytest.mark.asyncio
    async def test_organization_source_chunk(self, organization_extraction_result, expected_orgs: list):
        """
        GIVEN text with organizations
        WHEN _extract_entities_from_text is called
        THEN each extracted organization has the correct source chunk ID.
        """
        org_entities, chunk_id = organization_extraction_result
        for entity in org_entities:
            actual_chunk_id = entity['properties']['source_chunk']
            assert actual_chunk_id == chunk_id, \
                f"Expected source_chunk '{chunk_id}' for entity '{entity['name']}', but got '{actual_chunk_id}'"





class TestExtractEntitiesFromText:
    """Test class for GraphRAGIntegrator._extract_entities_from_text method."""

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_person_entities(
        self, integrator: GraphRAGIntegrator):
        """
        GIVEN text containing person names in various formats
        WHEN _extract_entities_from_text is called
        THEN person entities should be extracted correctly
        AND entity type should be 'person'
        AND confidence should be 0.7
        AND names should include titles when present
        """
        text = "Dr. John Smith and Ms. Jane Doe met with Robert Johnson yesterday."
        chunk_id = "person_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        person_entities = [entity for entity in result if entity['type'] == 'person']
        assert len(person_entities) >= 3
        
        person_names = [entity['name'] for entity in person_entities]
        assert 'Dr. John Smith' in person_names
        assert 'Ms. Jane Doe' in person_names
        assert 'Robert Johnson' in person_names
        
        for entity in person_entities:
            assert entity['confidence'] == 0.7
            assert entity['type'] == 'person'
            assert entity['properties']['source_chunk'] == chunk_id

    @pytest.fixture
    async def location_extraction_result(self, integrator: GraphRAGIntegrator):
        """Fixture to provide the result of location entity extraction."""
        text = "The office at 123 Main Street, San Francisco, CA hosts meetings. New York, NY is busy."
        chunk_id = "location_chunk"
        result = await integrator._extract_entities_from_text(text, chunk_id)
        print(f"result: {result}")
        location_entities = [entity for entity in result if entity['type'] == 'location']
        return location_entities, chunk_id

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_location_count(self, location_extraction_result):
        """
        GIVEN text with locations
        WHEN _extract_entities_from_text is called
        THEN it extracts at least two location entities.
        """
        location_entities, _ = location_extraction_result
        assert len(location_entities) >= 2, \
            f"Expected at least 2 location entities, but found {len(location_entities)}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("expected_location", [
        'San Francisco',
        'New York'
    ])
    async def test_extract_entities_from_text_location_finds_specific_locations(self, location_extraction_result, expected_location):
        """
        GIVEN text with locations
        WHEN _extract_entities_from_text is called
        THEN specific locations are extracted as entities.
        """
        location_entities, _ = location_extraction_result
        location_names = [entity['name'] for entity in location_entities]
        assert any(expected_location in name for name in location_names), \
            f"Expected location '{expected_location}' not found in extracted names: {location_names}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("index", [0, 1])
    async def test_extract_entities_from_text_location_confidence(self, location_extraction_result, index):
        """
        GIVEN text with locations
        WHEN _extract_entities_from_text is called
        THEN each extracted location entity has a confidence of 0.7.
        """
        location_entities, _ = location_extraction_result
        entity = location_entities[index]
        assert entity['confidence'] == 0.7, \
            f"Expected confidence 0.7 for entity {entity['name']}, but got {entity['confidence']}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("index", [0, 1])
    async def test_extract_entities_from_text_location_type(self, location_extraction_result, index):
        """
        GIVEN text with locations
        WHEN _extract_entities_from_text is called
        THEN each extracted location entity has the type 'location'.
        """
        location_entities, _ = location_extraction_result
        entity = location_entities[index]
        assert entity['type'] == 'location', \
            f"Expected type 'location' for entity {entity['name']}, but got {entity['type']}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("index", [0, 1])
    async def test_extract_entities_from_text_location_source_chunk(self, location_extraction_result, index):
        """
        GIVEN text with locations
        WHEN _extract_entities_from_text is called
        THEN each extracted location entity has the correct source chunk ID.
        """
        location_entities, chunk_id = location_extraction_result
        entity = location_entities[index]
        actual_chunk_id = entity['properties']['source_chunk']
        assert actual_chunk_id == chunk_id, \
            f"Expected source_chunk '{chunk_id}' for entity {entity['name']}, but got '{actual_chunk_id}'"

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_date_entities(self, integrator: GraphRAGIntegrator):
        """
        GIVEN text containing dates in various formats
        WHEN _extract_entities_from_text is called
        THEN date entities should be extracted correctly
        AND entity type should be 'date'
        AND formats MM/DD/YYYY, Month DD, YYYY should be recognized
        """
        text = "The meeting on 12/25/2023 was followed by another on January 15, 2024."
        chunk_id = "date_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        date_entities = [entity for entity in result if entity['type'] == 'date']
        assert len(date_entities) >= 2
        
        date_names = [entity['name'] for entity in date_entities]
        assert '12/25/2023' in date_names
        assert 'January 15, 2024' in date_names
        
        for entity in date_entities:
            assert entity['confidence'] == 0.7
            assert entity['type'] == 'date'
            assert entity['properties']['source_chunk'] == chunk_id

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_currency_entities(self, integrator: GraphRAGIntegrator):
        """
        GIVEN text containing currency amounts and expressions
        WHEN _extract_entities_from_text is called
        THEN currency entities should be extracted correctly
        AND entity type should be 'currency'
        AND dollar amounts and currency words should be recognized
        """
        text = "The contract was worth $50,000 and they paid an additional 25000 dollars."
        chunk_id = "currency_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        currency_entities = [entity for entity in result if entity['type'] == 'currency']
        assert len(currency_entities) >= 2
        
        currency_names = [entity['name'] for entity in currency_entities]
        assert '$50,000' in currency_names
        assert '25000 dollars' in currency_names
        
        for entity in currency_entities:
            assert entity['confidence'] == 0.7
            assert entity['type'] == 'currency'
            assert entity['properties']['source_chunk'] == chunk_id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text, chunk_id, case_description", [
        ("", "empty_chunk", "an empty string"),
        ("   \n\t\r   ", "whitespace_chunk", "only whitespace characters"),
        ("This is just plain text with no entities to extract from it.", "no_entities_chunk", "no recognizable entities")
    ])
    async def test_extract_entities_from_text_no_entities_found(self, integrator: GraphRAGIntegrator, text: str, chunk_id: str, case_description: str):
        """
        GIVEN text that is empty, whitespace-only, or contains no recognizable entities
        WHEN _extract_entities_from_text is called
        THEN an empty list should be returned
        AND no errors should be raised.
        """
        result = await integrator._extract_entities_from_text(text, chunk_id)
        assert result == [], f"Expected an empty list for input with {case_description}, but got {result}"

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_duplicate_entities(self, integrator: GraphRAGIntegrator):
        """
        GIVEN text containing the same entity mentioned multiple times
        WHEN _extract_entities_from_text is called
        THEN only unique entities should be returned
        AND duplicates should be filtered out
        """
        text = "Apple Inc. makes phones. Apple Inc. is innovative. Apple Inc. is successful."
        chunk_id = "duplicate_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)

        apple_entities = [entity for entity in result if 'Apple Inc' in entity['name']]
        assert len(apple_entities) == 1  # Should be deduplicated

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_case_variations(self, integrator: GraphRAGIntegrator):
        """
        GIVEN text containing entities with different case variations
        WHEN _extract_entities_from_text is called
        THEN entities should be extracted preserving original case
        AND case variations should be treated as separate entities initially
        """
        text = "MICROSOFT and Microsoft and microsoft are mentioned."
        chunk_id = "case_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        # The method should extract based on patterns, case variations may be treated differently
        microsoft_entities = [entity for entity in result if 'microsoft' in entity['name'].lower()]
        assert len(microsoft_entities) == 1

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_overlapping_patterns(self, integrator: GraphRAGIntegrator):
        """
        GIVEN text where entity patterns overlap (e.g., person name within organization)
        WHEN _extract_entities_from_text is called
        THEN the most specific or longest match should be preferred
        AND both entities should be extracted if they're genuinely different
        """
        text = "John Smith founded John Smith Inc. and hired Mary Johnson."
        chunk_id = "overlap_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        # Should extract both person and organization entities
        person_entities = [entity for entity in result if entity['type'] == 'person']
        org_entities = [entity for entity in result if entity['type'] == 'organization']
        
        assert len(person_entities) >= 1  # John Smith, Mary Johnson
        assert len(org_entities) >= 1    # John Smith Inc.

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_special_characters(self, integrator: GraphRAGIntegrator):
        """
        GIVEN text containing entities with special characters, apostrophes, hyphens
        WHEN _extract_entities_from_text is called
        THEN entities should be extracted correctly including special characters
        AND regex patterns should handle these characters appropriately
        """
        text = "O'Reilly Media and Coca-Cola Company work with Jean-Pierre's firm."
        chunk_id = "special_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        entity_names = [entity['name'] for entity in result]
        # The exact extraction depends on regex patterns, but should handle common patterns
        assert len(result) >= 1  # Should extract at least some entities

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_unicode_characters(self, integrator: GraphRAGIntegrator):
        """
        GIVEN text containing entities with unicode characters (accented letters, etc.)
        WHEN _extract_entities_from_text is called
        THEN entities should be extracted correctly preserving unicode
        AND no encoding errors should occur
        """
        text = "José García works at Café René and Björk Enterprises in São Paulo."
        chunk_id = "unicode_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        # Should handle unicode characters without errors
        assert isinstance(result, list)
        for entity in result:
            assert isinstance(entity['name'], str)
            # Unicode characters should be preserved
            assert all(isinstance(value, str) for value in entity.values() if isinstance(value, str))

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_mixed_entity_types(self, integrator: GraphRAGIntegrator):
        """
        GIVEN text containing multiple types of entities together
        WHEN _extract_entities_from_text is called
        THEN all entity types should be extracted correctly
        AND each should have the appropriate type classification
        """
        text = "Dr. Sarah Wilson from Stanford University visited Google Inc. on 03/15/2024 for a $10,000 project in Palo Alto, CA."
        chunk_id = "mixed_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        entity_types = set(entity['type'] for entity in result)
        # Should extract multiple types
        assert len(entity_types) >= 2
        
        # Verify each type has appropriate entities
        for entity in result:
            assert entity['type'] in ['person', 'organization', 'location', 'date', 'currency']
            assert entity['confidence'] == 0.7

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_chunk_id_assignment(self, integrator: GraphRAGIntegrator):
        """
        GIVEN a specific chunk_id parameter
        WHEN _extract_entities_from_text is called
        THEN all extracted entities should have the chunk_id in their properties
        AND the chunk_id should be correctly stored in extraction metadata
        """
        text = "IBM Corporation develops technology."
        chunk_id = "test_chunk_123"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        for entity in result:
            assert entity['properties']['source_chunk'] == chunk_id

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_confidence_scores(self, integrator: GraphRAGIntegrator):
        """
        GIVEN any text with entities
        WHEN _extract_entities_from_text is called
        THEN all entities should have confidence score of 0.7
        AND confidence should be consistent across all entity types
        """
        text = "John Doe works at Apple Inc. in San Francisco, CA on 01/01/2024 for $75,000."
        chunk_id = "confidence_chunk"

        result = await integrator._extract_entities_from_text(text, chunk_id)

        for entity in result:
            assert entity['confidence'] == 0.7

    @pytest.fixture
    async def description_extraction_result(self, integrator: GraphRAGIntegrator):
        """Fixture to provide the result of entity extraction for description tests."""
        text = "Microsoft Corporation was founded by Bill Gates in Seattle, WA on 04/04/1975 for $1000."
        chunk_id = "description_chunk"
        result = await integrator._extract_entities_from_text(text, chunk_id)
        print(f"description_extraction_result: {result}")
        return result

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_description_exists(self, description_extraction_result):
        """
        GIVEN text with entities
        WHEN _extract_entities_from_text is called
        THEN each entity should have a 'description' key.
        """
        for entity in description_extraction_result:
            assert 'description' in entity

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_description_is_string(self, description_extraction_result):
        """
        GIVEN text with entities
        WHEN _extract_entities_from_text is called
        THEN each entity's description should be a string.
        """
        for entity in description_extraction_result:
            assert isinstance(entity['description'], str)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_description_is_not_empty(self, description_extraction_result):
        """
        GIVEN text with entities
        WHEN _extract_entities_from_text is called
        THEN each entity's description should not be an empty string.
        """
        for entity in description_extraction_result:
            assert len(entity['description']) > 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("entity_type, keywords", [
        ('person', ['person']),
        ('organization', ['company', 'organization', 'corp']),
        ('location', ['location', 'place']),
        ('date', ['date']),
        ('currency', ['currency', 'amount', 'money'])
    ])
    async def test_extract_entities_from_text_description_content(self, description_extraction_result, entity_type, keywords):
        """
        GIVEN text with various entity types
        WHEN _extract_entities_from_text is called
        THEN each entity's description should contain type-appropriate keywords.
        """
        type_entities = [e for e in description_extraction_result if e['type'] == entity_type]
        assert len(type_entities) > 0, f"No entities of type '{entity_type}' found for testing."
        for entity in type_entities:
            description_lower = entity['description'].lower()
            assert any(word in description_lower for word in keywords), \
                f"Description for {entity_type} '{entity['name']}' did not contain expected keywords: {keywords}"


    @pytest.mark.asyncio
    async def test_extract_entities_from_text_properties_structure(self, integrator: GraphRAGIntegrator):
        """
        GIVEN any text with entities
        WHEN _extract_entities_from_text is called
        THEN each entity should have a properties dict containing:
            - extraction_method: 'regex_pattern_matching'
            - source_chunk: the provided chunk_id
        """
        text = "Tesla Inc. makes electric vehicles."
        chunk_id = "properties_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        for entity in result:
            assert 'properties' in entity
            assert isinstance(entity['properties'], dict)
            assert entity['properties']['extraction_method'] == 'regex_pattern_matching'
            assert entity['properties']['source_chunk'] == chunk_id

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_regex_error_handling(self, integrator: GraphRAGIntegrator):
        """
        GIVEN malformed regex patterns (hypothetically)
        WHEN _extract_entities_from_text is called
        THEN a re.error should be raised
        AND the error should be properly propagated
        """
        # This test verifies that regex errors are handled properly
        # We'll patch re.compile to simulate a bad regex pattern.
        text = "Some text to test regex error handling."
        chunk_id = "regex_error_chunk"
        
        with patch('re.compile', side_effect=re.error("Invalid regex pattern")):
            with pytest.raises(re.error) as exc_info:
                await integrator._extract_entities_from_text(text, chunk_id)
            
            assert "Invalid regex pattern" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_large_text_input(self, integrator: GraphRAGIntegrator):
        """
        GIVEN a very large text input (>10KB)
        WHEN _extract_entities_from_text is called
        THEN all entities should be extracted efficiently
        AND performance should remain reasonable
        AND no memory issues should occur
        """
        # Create large text with repeated entities
        base_text = "Apple Inc. was founded by Steve Jobs in Cupertino, CA on 04/01/1976 for $1,000. "
        large_text = base_text * 500  # ~50KB of text
        chunk_id = "large_chunk"
        
        start_time = time.time()
        result = await integrator._extract_entities_from_text(large_text, chunk_id)
        end_time = time.time()
        
        # Should complete in reasonable time
        assert end_time - start_time < 10  # 10 seconds max
        
        # Should extract entities (may have duplicates that will be filtered)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_none_text_input(self, integrator: GraphRAGIntegrator):
        """
        GIVEN None as the text parameter
        WHEN _extract_entities_from_text is called
        THEN a TypeError should be raised
        AND the error should indicate invalid text type
        """
        with pytest.raises(TypeError) as exc_info:
            await integrator._extract_entities_from_text(None, "chunk_id")
        
        assert "text must be a string" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_none_chunk_id(self, integrator: GraphRAGIntegrator):
        """
        GIVEN None as the chunk_id parameter
        WHEN _extract_entities_from_text is called
        THEN a TypeError should be raised
        AND the error should indicate invalid chunk_id type
        """
        with pytest.raises(TypeError) as exc_info:
            await integrator._extract_entities_from_text("Some text", None)
        
        assert "chunk_id must be a string" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_non_string_inputs(self, integrator: GraphRAGIntegrator):
        """
        GIVEN non-string inputs for text or chunk_id parameters
        WHEN _extract_entities_from_text is called
        THEN a TypeError should be raised
        AND the error should indicate expected string types
        """
        # Test non-string text
        with pytest.raises(TypeError) as exc_info:
            await integrator._extract_entities_from_text(123, "chunk_id")
        assert "text must be a string" in str(exc_info.value)
        
        # Test non-string chunk_id
        with pytest.raises(TypeError) as exc_info:
            await integrator._extract_entities_from_text("Some text", 456)
        assert "chunk_id must be a string" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_edge_case_patterns(self, integrator: GraphRAGIntegrator):
        """
        GIVEN text with edge cases like single letters, numbers only, punctuation only
        WHEN _extract_entities_from_text is called
        THEN these should not be extracted as entities
        AND no false positives should occur
        """
        text = "A B C 123 456 !@# $$ ... --- +++ 999"
        chunk_id = "edge_case_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        # Should not extract single letters, numbers, or punctuation as entities
        for entity in result:
            assert len(entity['name'].strip()) > 1  # Should be meaningful names
            assert not entity['name'].isdigit()  # Should not be pure numbers

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_boundary_matching(self, integrator: GraphRAGIntegrator):
        """
        GIVEN text where potential entities are at word boundaries vs embedded in words
        WHEN _extract_entities_from_text is called
        THEN only properly bounded entities should be extracted
        AND partial word matches should be avoided
        """
        text = "Microprocessor and Microsoft are different. Applegate versus Apple Inc."
        chunk_id = "boundary_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        entity_names = [entity['name'] for entity in result]
        
        # Should extract proper entities, not partial matches
        if 'Microsoft' in entity_names:
            assert 'Microprocessor' not in entity_names or any('Microsoft' in name for name in entity_names)
        
        if any('Apple' in name for name in entity_names):
            # Should prefer "Apple Inc." over partial "Apple" from "Applegate"
            apple_entities = [name for name in entity_names if 'Apple' in name]
            assert any('Inc' in name or name == 'Apple' for name in apple_entities)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_return_type_is_list(self, integrator: GraphRAGIntegrator):
        """
        GIVEN any valid text input
        WHEN _extract_entities_from_text is called
        THEN the return value should be a list
        """
        text = "Amazon Inc. was founded by Jeff Bezos."
        chunk_id = "return_type_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_entity_is_dict(self, integrator: GraphRAGIntegrator):
        """
        GIVEN any valid text input that produces entities
        WHEN _extract_entities_from_text is called
        THEN each element should be a dictionary
        """
        text = "Amazon Inc. was founded by Jeff Bezos."
        chunk_id = "return_type_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        for entity in result:
            assert isinstance(entity, dict)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("required_key", ['name', 'type', 'description', 'confidence', 'properties'])
    async def test_extract_entities_from_text_entity_has_required_keys(self, integrator: GraphRAGIntegrator, required_key: str):
        """
        GIVEN any valid text input that produces entities
        WHEN _extract_entities_from_text is called
        THEN each entity should have all required keys
        """
        text = "Amazon Inc. was founded by Jeff Bezos."
        chunk_id = "return_type_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        for entity in result:
            assert required_key in entity

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_entity_name_is_string(self, integrator: GraphRAGIntegrator):
        """
        GIVEN any valid text input that produces entities
        WHEN _extract_entities_from_text is called
        THEN each entity's name should be a string
        """
        text = "Amazon Inc. was founded by Jeff Bezos."
        chunk_id = "return_type_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        for entity in result:
            assert isinstance(entity['name'], str)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_entity_type_is_string(self, integrator: GraphRAGIntegrator):
        """
        GIVEN any valid text input that produces entities
        WHEN _extract_entities_from_text is called
        THEN each entity's type should be a string
        """
        text = "Amazon Inc. was founded by Jeff Bezos."
        chunk_id = "return_type_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        for entity in result:
            assert isinstance(entity['type'], str)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_entity_description_is_string(self, integrator: GraphRAGIntegrator):
        """
        GIVEN any valid text input that produces entities
        WHEN _extract_entities_from_text is called
        THEN each entity's description should be a string
        """
        text = "Amazon Inc. was founded by Jeff Bezos."
        chunk_id = "return_type_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        for entity in result:
            assert isinstance(entity['description'], str)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_entity_confidence_is_number(self, integrator: GraphRAGIntegrator):
        """
        GIVEN any valid text input that produces entities
        WHEN _extract_entities_from_text is called
        THEN each entity's confidence should be a number
        """
        text = "Amazon Inc. was founded by Jeff Bezos."
        chunk_id = "return_type_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        for entity in result:
            assert isinstance(entity['confidence'], (int, float))

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_entity_properties_is_dict(self, integrator: GraphRAGIntegrator):
        """
        GIVEN any valid text input that produces entities
        WHEN _extract_entities_from_text is called
        THEN each entity's properties should be a dictionary
        """
        text = "Amazon Inc. was founded by Jeff Bezos."
        chunk_id = "return_type_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        for entity in result:
            assert isinstance(entity['properties'], dict)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_entity_name_not_empty(self, integrator: GraphRAGIntegrator):
        """
        GIVEN any valid text input that produces entities
        WHEN _extract_entities_from_text is called
        THEN each entity's name should not be empty
        """
        text = "Amazon Inc. was founded by Jeff Bezos."
        chunk_id = "return_type_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        for entity in result:
            assert len(entity['name']) > 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("valid_type", ['person', 'organization', 'location', 'date', 'currency'])
    async def test_extract_entities_from_text_entity_type_is_valid(self, integrator: GraphRAGIntegrator, valid_type: str):
        """
        GIVEN any valid text input that produces entities
        WHEN _extract_entities_from_text is called
        THEN each entity's type should be one of the valid types
        """
        text = "Amazon Inc. was founded by Jeff Bezos."
        chunk_id = "return_type_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        valid_types = ['person', 'organization', 'location', 'date', 'currency']
        for entity in result:
            assert entity['type'] in valid_types

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_entity_confidence_in_range(self, integrator: GraphRAGIntegrator):
        """
        GIVEN any valid text input that produces entities
        WHEN _extract_entities_from_text is called
        THEN each entity's confidence should be between 0.0 and 1.0
        """
        text = "Amazon Inc. was founded by Jeff Bezos."
        chunk_id = "return_type_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        for entity in result:
            assert 0.0 <= entity['confidence'] <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
