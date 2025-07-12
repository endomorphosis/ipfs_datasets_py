
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
import asyncio
import json
from unittest.mock import Mock, MagicMock, AsyncMock, patch
import networkx as nx
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, Entity, Relationship


from tests._test_utils import (
    raise_on_bad_callable_metadata,
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





class TestInferRelationshipType:
    """Test class for GraphRAGIntegrator._infer_relationship_type method."""

    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.integrator = GraphRAGIntegrator()
        
        # Create mock entities for testing
        self.person_entity = Entity(
            id="person_1",
            name="John Smith",
            type="person",
            description="Software engineer",
            confidence=0.9,
            source_chunks=["chunk_1"],
            properties={}
        )
        
        self.org_entity = Entity(
            id="org_1", 
            name="ACME Corp",
            type="organization",
            description="Technology company",
            confidence=0.8,
            source_chunks=["chunk_1"],
            properties={}
        )
        
        self.person_entity2 = Entity(
            id="person_2",
            name="Jane Doe", 
            type="person",
            description="Manager",
            confidence=0.85,
            source_chunks=["chunk_2"],
            properties={}
        )

    def test_infer_relationship_type_person_organization_leads(self):
        """
        GIVEN a person entity and organization entity with context containing 'CEO', 'leads', or 'director'
        WHEN _infer_relationship_type is called
        THEN 'leads' should be returned
        """
        # Test CEO
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, "John Smith is the CEO of ACME Corp"
        )
        assert result == "leads"
        
        # Test director
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, "John Smith serves as director of operations at ACME Corp"
        )
        assert result == "leads"
        
        # Test leads
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, "John Smith leads the engineering team at ACME Corp"
        )
        assert result == "leads"

    def test_infer_relationship_type_person_organization_works_for(self):
        """
        GIVEN a person entity and organization entity with context containing 'works for', 'employee', or 'employed'
        WHEN _infer_relationship_type is called
        THEN 'works_for' should be returned
        """
        # Test works for
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, "John Smith works for ACME Corp as an engineer"
        )
        assert result == "works_for"
        
        # Test employee
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, "John Smith is an employee at ACME Corp"
        )
        assert result == "works_for"
        
        # Test employed
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, "John Smith is employed by ACME Corp"
        )
        assert result == "works_for"

    def test_infer_relationship_type_person_organization_founded(self):
        """
        GIVEN a person entity and organization entity with context containing 'founded', 'established', or 'created'
        WHEN _infer_relationship_type is called
        THEN 'founded' should be returned
        """
        # Test founded
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, "John Smith founded ACME Corp in 2010"
        )
        assert result == "founded"
        
        # Test established
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, "John Smith established ACME Corp as a startup"
        )
        assert result == "founded"
        
        # Test created
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, "John Smith created ACME Corp to solve problems"
        )
        assert result == "founded"

    def test_infer_relationship_type_person_organization_associated_with(self):
        """
        GIVEN a person entity and organization entity with generic context
        WHEN _infer_relationship_type is called
        THEN 'associated_with' should be returned as default
        """
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, "John Smith and ACME Corp have some connection"
        )
        assert result == "associated_with"

    def test_infer_relationship_type_organization_organization_acquired(self):
        """
        GIVEN two organization entities with context containing 'acquired', 'bought', or 'purchased'
        WHEN _infer_relationship_type is called
        THEN 'acquired' should be returned
        """
        org2 = Entity(
            id="org_2", name="StartupCo", type="organization", 
            description="Startup", confidence=0.8, source_chunks=["chunk_2"], properties={}
        )
        
        # Test acquired
        result = self.integrator._infer_relationship_type(
            self.org_entity, org2, "ACME Corp acquired StartupCo last year"
        )
        assert result == "acquired"
        
        # Test bought
        result = self.integrator._infer_relationship_type(
            self.org_entity, org2, "ACME Corp bought StartupCo for $10M"
        )
        assert result == "acquired"
        
        # Test purchased
        result = self.integrator._infer_relationship_type(
            self.org_entity, org2, "ACME Corp purchased StartupCo's assets"
        )
        assert result == "acquired"

    def test_infer_relationship_type_organization_organization_partners_with(self):
        """
        GIVEN two organization entities with context containing 'partners', 'partnership', or 'collaboration'
        WHEN _infer_relationship_type is called
        THEN 'partners_with' should be returned
        """
        org2 = Entity(
            id="org_2", name="PartnerCorp", type="organization",
            description="Partner company", confidence=0.8, source_chunks=["chunk_2"], properties={}
        )
        
        # Test partners
        result = self.integrator._infer_relationship_type(
            self.org_entity, org2, "ACME Corp partners with PartnerCorp on projects"
        )
        assert result == "partners_with"
        
        # Test partnership
        result = self.integrator._infer_relationship_type(
            self.org_entity, org2, "The partnership between ACME Corp and PartnerCorp is strong"
        )
        assert result == "partners_with"
        
        # Test collaboration
        result = self.integrator._infer_relationship_type(
            self.org_entity, org2, "ACME Corp collaboration with PartnerCorp yields results"
        )
        assert result == "partners_with"

    def test_infer_relationship_type_organization_organization_competes_with(self):
        """
        GIVEN two organization entities with context containing 'competes', 'competitor', or 'rival'
        WHEN _infer_relationship_type is called
        THEN 'competes_with' should be returned
        """
        org2 = Entity(
            id="org_2", name="RivalCorp", type="organization",
            description="Competing company", confidence=0.8, source_chunks=["chunk_2"], properties={}
        )
        
        # Test competes
        result = self.integrator._infer_relationship_type(
            self.org_entity, org2, "ACME Corp competes with RivalCorp in the market"
        )
        assert result == "competes_with"
        
        # Test competitor
        result = self.integrator._infer_relationship_type(
            self.org_entity, org2, "RivalCorp is a major competitor to ACME Corp"
        )
        assert result == "competes_with"
        
        # Test rival
        result = self.integrator._infer_relationship_type(
            self.org_entity, org2, "ACME Corp and RivalCorp are business rivals"
        )
        assert result == "competes_with"

    def test_infer_relationship_type_organization_organization_related_to(self):
        """
        GIVEN two organization entities with generic context
        WHEN _infer_relationship_type is called
        THEN 'related_to' should be returned as default
        """
        org2 = Entity(
            id="org_2", name="OtherCorp", type="organization",
            description="Another company", confidence=0.8, source_chunks=["chunk_2"], properties={}
        )
        
        result = self.integrator._infer_relationship_type(
            self.org_entity, org2, "ACME Corp and OtherCorp have some business connection"
        )
        assert result == "related_to"

    def test_infer_relationship_type_person_person_knows(self):
        """
        GIVEN two person entities with generic context
        WHEN _infer_relationship_type is called
        THEN 'knows' should be returned as default for person-person relationships
        """
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.person_entity2, "John Smith and Jane Doe met at a conference"
        )
        assert result == "knows"

    def test_infer_relationship_type_location_based_located_in(self):
        """
        GIVEN entities with context containing 'located in', 'based in', or 'headquarters'
        WHEN _infer_relationship_type is called
        THEN 'located_in' should be returned
        """
        location_entity = Entity(
            id="loc_1", name="San Francisco", type="location",
            description="City", confidence=0.9, source_chunks=["chunk_1"], properties={}
        )
        
        # Test located in
        result = self.integrator._infer_relationship_type(
            self.org_entity, location_entity, "ACME Corp is located in San Francisco"
        )
        assert result == "located_in"
        
        # Test based in
        result = self.integrator._infer_relationship_type(
            self.org_entity, location_entity, "ACME Corp is based in San Francisco"
        )
        assert result == "located_in"
        
        # Test headquarters
        result = self.integrator._infer_relationship_type(
            self.org_entity, location_entity, "ACME Corp headquarters are in San Francisco"
        )
        assert result == "located_in"

    def test_infer_relationship_type_default_related_to(self):
        """
        GIVEN entities that don't match any specific patterns
        WHEN _infer_relationship_type is called
        THEN 'related_to' should be returned as the fallback
        """
        concept_entity = Entity(
            id="concept_1", name="Innovation", type="concept",
            description="Abstract concept", confidence=0.7, source_chunks=["chunk_1"], properties={}
        )
        
        result = self.integrator._infer_relationship_type(
            self.person_entity, concept_entity, "John Smith thinks about innovation"
        )
        assert result == "related_to"

    def test_infer_relationship_type_case_insensitive_matching(self):
        """
        GIVEN context with keywords in different cases (uppercase, lowercase, mixed)
        WHEN _infer_relationship_type is called
        THEN matching should be case-insensitive
        AND the correct relationship type should be returned
        """
        # Test uppercase
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, "John Smith is the CEO of ACME Corp"
        )
        assert result == "leads"
        
        # Test lowercase
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, "john smith is the ceo of acme corp"
        )
        assert result == "leads"
        
        # Test mixed case
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, "John Smith is the Ceo of ACME Corp"
        )
        assert result == "leads"

    def test_infer_relationship_type_multiple_keywords_priority(self):
        """
        GIVEN context containing multiple relationship keywords
        WHEN _infer_relationship_type is called
        THEN the more specific relationship should be prioritized over generic ones
        """
        # CEO should take priority over employee
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, 
            "John Smith is an employee and CEO of ACME Corp"
        )
        assert result == "leads"  # CEO is more specific than employee

    def test_infer_relationship_type_empty_context(self):
        """
        GIVEN an empty string as context
        WHEN _infer_relationship_type is called
        THEN a ValueError should be raised
        AND the error should indicate empty context
        """
        with pytest.raises(ValueError, match="Context cannot be empty"):
            self.integrator._infer_relationship_type(
                self.person_entity, self.org_entity, ""
            )

    def test_infer_relationship_type_whitespace_only_context(self):
        """
        GIVEN context containing only whitespace characters
        WHEN _infer_relationship_type is called
        THEN a ValueError should be raised
        AND the error should indicate invalid context
        """
        with pytest.raises(ValueError, match="Context cannot be empty"):
            self.integrator._infer_relationship_type(
                self.person_entity, self.org_entity, "   \t\n  "
            )

    def test_infer_relationship_type_none_entity1(self):
        """
        GIVEN None as entity1 parameter
        WHEN _infer_relationship_type is called
        THEN a TypeError should be raised
        AND the error should indicate invalid entity type
        """
        with pytest.raises(TypeError, match="Entity cannot be None"):
            self.integrator._infer_relationship_type(
                None, self.org_entity, "some context"
            )

    def test_infer_relationship_type_none_entity2(self):
        """
        GIVEN None as entity2 parameter
        WHEN _infer_relationship_type is called
        THEN a TypeError should be raised
        AND the error should indicate invalid entity type
        """
        with pytest.raises(TypeError, match="Entity cannot be None"):
            self.integrator._infer_relationship_type(
                self.person_entity, None, "some context"
            )

    def test_infer_relationship_type_none_context(self):
        """
        GIVEN None as context parameter
        WHEN _infer_relationship_type is called
        THEN a TypeError should be raised
        AND the error should indicate invalid context type
        """
        with pytest.raises(TypeError, match="Context must be a string"):
            self.integrator._infer_relationship_type(
                self.person_entity, self.org_entity, None
            )

    def test_infer_relationship_type_invalid_entity1_type(self):
        """
        GIVEN entity1 that is not an Entity instance
        WHEN _infer_relationship_type is called
        THEN a TypeError should be raised
        AND the error should indicate expected Entity type
        """
        with pytest.raises(TypeError, match="Expected Entity instance"):
            self.integrator._infer_relationship_type(
                "not an entity", self.org_entity, "some context"
            )

    def test_infer_relationship_type_invalid_entity2_type(self):
        """
        GIVEN entity2 that is not an Entity instance
        WHEN _infer_relationship_type is called
        THEN a TypeError should be raised
        AND the error should indicate expected Entity type
        """
        with pytest.raises(TypeError, match="Expected Entity instance"):
            self.integrator._infer_relationship_type(
                self.person_entity, "not an entity", "some context"
            )

    def test_infer_relationship_type_entity_missing_type_attribute(self):
        """
        GIVEN entities without type attribute
        WHEN _infer_relationship_type is called
        THEN an AttributeError should be raised
        AND the error should indicate missing type attribute
        """
        # Create mock entity without type attribute
        mock_entity = Mock()
        del mock_entity.type  # Remove type attribute
        
        with pytest.raises(AttributeError, match="Entity must have a 'type' attribute"):
            self.integrator._infer_relationship_type(
                mock_entity, self.org_entity, "some context"
            )

    def test_infer_relationship_type_unknown_entity_types(self):
        """
        GIVEN entities with unrecognized type values
        WHEN _infer_relationship_type is called
        THEN 'related_to' should be returned as default
        AND no errors should be raised
        """
        unknown_entity = Entity(
            id="unknown_1", name="Mystery", type="unknown_type",
            description="Unknown entity", confidence=0.5, source_chunks=["chunk_1"], properties={}
        )
        
        result = self.integrator._infer_relationship_type(
            unknown_entity, self.org_entity, "Mystery entity works with ACME Corp"
        )
        assert result == "related_to"

    def test_infer_relationship_type_mixed_entity_types_not_covered(self):
        """
        GIVEN entity type combinations not explicitly handled (e.g., date-location)
        WHEN _infer_relationship_type is called
        THEN 'related_to' should be returned as default
        AND the method should handle unexpected combinations gracefully
        """
        date_entity = Entity(
            id="date_1", name="2023-01-01", type="date",
            description="Date", confidence=0.8, source_chunks=["chunk_1"], properties={}
        )
        location_entity = Entity(
            id="loc_1", name="New York", type="location",
            description="City", confidence=0.9, source_chunks=["chunk_1"], properties={}
        )
        
        result = self.integrator._infer_relationship_type(
            date_entity, location_entity, "The event happened on 2023-01-01 in New York"
        )
        assert result == "related_to"

    def test_infer_relationship_type_context_with_special_characters(self):
        """
        GIVEN context containing special characters, punctuation, or symbols
        WHEN _infer_relationship_type is called
        THEN keyword matching should work correctly despite special characters
        AND the appropriate relationship type should be returned
        """
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, 
            "John Smith is the C.E.O. of ACME Corp! (since 2020)"
        )
        assert result == "leads"

    def test_infer_relationship_type_very_long_context(self):
        """
        GIVEN a very long context string (>1000 characters)
        WHEN _infer_relationship_type is called
        THEN keyword matching should still work efficiently
        AND the correct relationship type should be identified
        """
        long_context = ("John Smith " * 100) + " is the CEO of ACME Corp " + ("and more text " * 50)
        
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, long_context
        )
        assert result == "leads"

    def test_infer_relationship_type_context_with_unicode(self):
        """
        GIVEN context containing unicode characters
        WHEN _infer_relationship_type is called
        THEN unicode should be handled correctly
        AND keyword matching should work with unicode text
        """
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, 
            "John Smith est le CEO de ACME Corp 🏢"
        )
        assert result == "leads"

    def test_infer_relationship_type_return_value_validation(self):
        """
        GIVEN any valid input
        WHEN _infer_relationship_type is called
        THEN the return value should be either a string or None
        AND if string, it should be one of the documented relationship types
        """
        valid_types = {
            "leads", "works_for", "founded", "associated_with",
            "acquired", "partners_with", "competes_with", "related_to",
            "knows", "located_in", "collaborates_with", "manages"
        }
        
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, "John Smith and ACME Corp"
        )
        
        assert result is None or (isinstance(result, str) and result in valid_types)

    def test_infer_relationship_type_keyword_boundaries(self):
        """
        GIVEN context where keywords appear as substrings within other words
        WHEN _infer_relationship_type is called
        THEN only complete word matches should be considered
        AND partial matches should not trigger relationship type identification
        """
        # "ceo" appears in "ceolicious" but shouldn't match
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, 
            "John Smith likes ceolicious food at ACME Corp"
        )
        # Should not return "leads" because "ceo" is part of "ceolicious"
        assert result == "associated_with"  # Default for person-org

    def test_infer_relationship_type_entity_order_independence(self):
        """
        GIVEN the same two entities but in different order (entity1, entity2) vs (entity2, entity1)
        WHEN _infer_relationship_type is called
        THEN the same relationship type should be returned regardless of order
        AND the method should be commutative for symmetric relationships
        """
        context = "John Smith and ACME Corp have a partnership"
        
        result1 = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, context
        )
        result2 = self.integrator._infer_relationship_type(
            self.org_entity, self.person_entity, context
        )
        
        assert result1 == result2

    def test_infer_relationship_type_context_preprocessing(self):
        """
        GIVEN context that may need preprocessing (extra whitespace, newlines, tabs)
        WHEN _infer_relationship_type is called
        THEN the context should be processed correctly
        AND keyword matching should work despite formatting issues
        """
        messy_context = "  \n\t John Smith   is the   CEO\t\nof  ACME Corp  \n  "
        
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.org_entity, messy_context
        )
        assert result == "leads"

    def test_infer_relationship_type_person_person_manages(self):
        """
        GIVEN two person entities with context containing 'manages', 'supervises', or 'reports to'
        WHEN _infer_relationship_type is called
        THEN 'manages' should be returned
        """
        # Test manages
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.person_entity2, 
            "John Smith manages Jane Doe's team"
        )
        assert result == "manages"
        
        # Test supervises
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.person_entity2, 
            "John Smith supervises Jane Doe"
        )
        assert result == "manages"
        
        # Test reports to (reverse relationship)
        result = self.integrator._infer_relationship_type(
            self.person_entity2, self.person_entity, 
            "Jane Doe reports to John Smith"
        )
        assert result == "manages"

    def test_infer_relationship_type_person_person_collaborates_with(self):
        """
        GIVEN two person entities with context containing 'collaborates', 'works together', or 'colleagues'
        WHEN _infer_relationship_type is called
        THEN 'collaborates_with' should be returned
        """
        # Test collaborates
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.person_entity2, 
            "John Smith collaborates with Jane Doe on projects"
        )
        assert result == "collaborates_with"
        
        # Test works together
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.person_entity2, 
            "John Smith works together with Jane Doe"
        )
        assert result == "collaborates_with"
        
        # Test colleagues
        result = self.integrator._infer_relationship_type(
            self.person_entity, self.person_entity2, 
            "John Smith and Jane Doe are colleagues"
        )
        assert result == "collaborates_with"




class TestGetEntityNeighborhood:
    """Test class for GraphRAGIntegrator.get_entity_neighborhood method."""

    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.integrator = GraphRAGIntegrator()
        
        # Create a test graph with known structure
        self.setup_test_graph()

    def setup_test_graph(self):
        """Set up a test graph with entities and relationships."""
        # Create entities
        self.entity1 = Entity(
            id="entity_1", name="John Smith", type="person",
            description="CEO", confidence=0.9, source_chunks=["chunk_1"], properties={}
        )
        self.entity2 = Entity(
            id="entity_2", name="ACME Corp", type="organization", 
            description="Company", confidence=0.8, source_chunks=["chunk_1"], properties={}
        )
        self.entity3 = Entity(
            id="entity_3", name="Jane Doe", type="person",
            description="CTO", confidence=0.85, source_chunks=["chunk_2"], properties={}
        )
        self.entity4 = Entity(
            id="entity_4", name="TechCorp", type="organization",
            description="Partner company", confidence=0.7, source_chunks=["chunk_3"], properties={}
        )
        self.entity5 = Entity(
            id="entity_5", name="San Francisco", type="location",
            description="City", confidence=0.9, source_chunks=["chunk_1"], properties={}
        )
        
        # Add entities to global registry
        self.integrator.global_entities = {
            "entity_1": self.entity1,
            "entity_2": self.entity2, 
            "entity_3": self.entity3,
            "entity_4": self.entity4,
            "entity_5": self.entity5
        }
        
        # Create graph structure:
        # entity_1 -> entity_2 -> entity_4
        # entity_1 -> entity_3 -> entity_2
        # entity_2 -> entity_5
        self.integrator.global_graph = nx.DiGraph()
        
        # Add nodes with attributes
        self.integrator.global_graph.add_node("entity_1", **{
            "name": self.entity1.name, "type": self.entity1.type, 
            "confidence": self.entity1.confidence, "source_chunks": self.entity1.source_chunks
        })
        self.integrator.global_graph.add_node("entity_2", **{
            "name": self.entity2.name, "type": self.entity2.type,
            "confidence": self.entity2.confidence, "source_chunks": self.entity2.source_chunks
        })
        self.integrator.global_graph.add_node("entity_3", **{
            "name": self.entity3.name, "type": self.entity3.type,
            "confidence": self.entity3.confidence, "source_chunks": self.entity3.source_chunks
        })
        self.integrator.global_graph.add_node("entity_4", **{
            "name": self.entity4.name, "type": self.entity4.type,
            "confidence": self.entity4.confidence, "source_chunks": self.entity4.source_chunks
        })
        self.integrator.global_graph.add_node("entity_5", **{
            "name": self.entity5.name, "type": self.entity5.type,
            "confidence": self.entity5.confidence, "source_chunks": self.entity5.source_chunks
        })
        
        # Add edges with attributes
        self.integrator.global_graph.add_edge("entity_1", "entity_2", 
                                            relationship_type="leads", confidence=0.9, source_chunks=["chunk_1"])
        self.integrator.global_graph.add_edge("entity_1", "entity_3",
                                            relationship_type="manages", confidence=0.8, source_chunks=["chunk_1"])
        self.integrator.global_graph.add_edge("entity_3", "entity_2",
                                            relationship_type="works_for", confidence=0.85, source_chunks=["chunk_2"])
        self.integrator.global_graph.add_edge("entity_2", "entity_4",
                                            relationship_type="partners_with", confidence=0.7, source_chunks=["chunk_1"])
        self.integrator.global_graph.add_edge("entity_2", "entity_5",
                                            relationship_type="located_in", confidence=0.9, source_chunks=["chunk_1"])

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_valid_entity_depth_1(self):
        """
        GIVEN a valid entity_id that exists in the global graph and depth=1
        WHEN get_entity_neighborhood is called
        THEN a subgraph containing the entity and its direct neighbors should be returned
        AND the subgraph should include all nodes within depth 1
        AND all connecting edges should be included
        """
        result = await self.integrator.get_entity_neighborhood("entity_1", depth=1)
        
        # Should include entity_1, entity_2, entity_3 (direct neighbors)
        assert result["center_entity_id"] == "entity_1"
        assert result["depth"] == 1
        assert result["node_count"] == 3
        assert result["edge_count"] == 2
        
        node_ids = {node["id"] for node in result["nodes"]}
        assert node_ids == {"entity_1", "entity_2", "entity_3"}
        
        edge_pairs = {(edge["source"], edge["target"]) for edge in result["edges"]}
        assert edge_pairs == {("entity_1", "entity_2"), ("entity_1", "entity_3")}

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_valid_entity_depth_2(self):
        """
        GIVEN a valid entity_id that exists in the global graph and depth=2
        WHEN get_entity_neighborhood is called
        THEN a subgraph containing neighbors up to 2 hops away should be returned
        AND all intermediate nodes and edges should be included
        """
        result = await self.integrator.get_entity_neighborhood("entity_1", depth=2)
        
        # Should include entity_1 + direct neighbors + their neighbors
        assert result["center_entity_id"] == "entity_1"
        assert result["depth"] == 2
        assert result["node_count"] == 5  # All entities
        assert result["edge_count"] == 5  # All edges
        
        node_ids = {node["id"] for node in result["nodes"]}
        assert node_ids == {"entity_1", "entity_2", "entity_3", "entity_4", "entity_5"}

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_valid_entity_default_depth(self):
        """
        GIVEN a valid entity_id and no depth parameter specified
        WHEN get_entity_neighborhood is called
        THEN depth should default to 2
        AND the neighborhood should include nodes up to 2 hops away
        """
        result = await self.integrator.get_entity_neighborhood("entity_1")
        
        assert result["depth"] == 2
        assert result["node_count"] == 5  # All entities within depth 2

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_isolated_entity(self):
        """
        GIVEN an entity_id that exists but has no connections
        WHEN get_entity_neighborhood is called
        THEN the result should contain only the center entity
        AND nodes list should have one element and edges list should be empty
        """
        # Add isolated entity
        isolated_entity = Entity(
            id="isolated_1", name="Isolated Entity", type="concept",
            description="No connections", confidence=0.5, source_chunks=["chunk_5"], properties={}
        )
        self.integrator.global_entities["isolated_1"] = isolated_entity
        self.integrator.global_graph.add_node("isolated_1", **{
            "name": isolated_entity.name, "type": isolated_entity.type,
            "confidence": isolated_entity.confidence, "source_chunks": isolated_entity.source_chunks
        })
        
        result = await self.integrator.get_entity_neighborhood("isolated_1", depth=2)
        
        assert result["center_entity_id"] == "isolated_1"
        assert result["node_count"] == 1
        assert result["edge_count"] == 0
        assert len(result["nodes"]) == 1
        assert len(result["edges"]) == 0
        assert result["nodes"][0]["id"] == "isolated_1"

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_nonexistent_entity(self):
        """
        GIVEN an entity_id that does not exist in the global graph
        WHEN get_entity_neighborhood is called
        THEN an error dictionary should be returned
        AND it should contain an 'error' key with appropriate message
        """
        result = await self.integrator.get_entity_neighborhood("nonexistent_entity")
        
        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_depth_zero(self):
        """
        GIVEN a valid entity_id and depth=0
        WHEN get_entity_neighborhood is called
        THEN only the center entity should be returned
        AND no neighbors should be included regardless of connections
        """
        result = await self.integrator.get_entity_neighborhood("entity_1", depth=0)
        
        assert result["center_entity_id"] == "entity_1"
        assert result["depth"] == 0
        assert result["node_count"] == 1
        assert result["edge_count"] == 0
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["id"] == "entity_1"

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_large_depth(self):
        """
        GIVEN a valid entity_id and a large depth value (e.g., 10)
        WHEN get_entity_neighborhood is called
        THEN all reachable nodes should be included up to the specified depth
        AND performance should remain reasonable even with large depths
        """
        result = await self.integrator.get_entity_neighborhood("entity_1", depth=10)
        
        # Should still return all reachable nodes (which is all 5 in our test graph)
        assert result["center_entity_id"] == "entity_1"
        assert result["depth"] == 10
        assert result["node_count"] == 5
        assert result["edge_count"] == 5

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_return_structure_validation(self):
        """
        GIVEN a valid entity_id
        WHEN get_entity_neighborhood is called
        THEN the return dictionary should contain:
            - center_entity_id: the input entity ID
            - depth: the depth used for traversal
            - nodes: list of node dictionaries with 'id' field
            - edges: list of edge dictionaries with 'source' and 'target' fields
            - node_count: integer count of nodes
            - edge_count: integer count of edges
        """
        result = await self.integrator.get_entity_neighborhood("entity_1", depth=1)
        
        # Validate structure
        assert isinstance(result, dict)
        assert "center_entity_id" in result
        assert "depth" in result
        assert "nodes" in result
        assert "edges" in result
        assert "node_count" in result
        assert "edge_count" in result
        
        # Validate types
        assert isinstance(result["center_entity_id"], str)
        assert isinstance(result["depth"], int)
        assert isinstance(result["nodes"], list)
        assert isinstance(result["edges"], list)
        assert isinstance(result["node_count"], int)
        assert isinstance(result["edge_count"], int)
        
        # Validate node structure
        for node in result["nodes"]:
            assert isinstance(node, dict)
            assert "id" in node
        
        # Validate edge structure
        for edge in result["edges"]:
            assert isinstance(edge, dict)
            assert "source" in edge
            assert "target" in edge

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_node_data_serialization(self):
        """
        GIVEN entities with various attributes in the neighborhood
        WHEN get_entity_neighborhood is called
        THEN node data should be properly serialized to dictionaries
        AND all node attributes should be preserved
        AND each node should include an 'id' field
        """
        result = await self.integrator.get_entity_neighborhood("entity_1", depth=1)
        
        # Find entity_1 node in results
        entity1_node = next(node for node in result["nodes"] if node["id"] == "entity_1")
        
        # Validate serialization
        assert entity1_node["name"] == "John Smith"
        assert entity1_node["type"] == "person"
        assert entity1_node["confidence"] == 0.9
        assert entity1_node["source_chunks"] == ["chunk_1"]

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_edge_data_serialization(self):
        """
        GIVEN relationships connecting entities in the neighborhood
        WHEN get_entity_neighborhood is called
        THEN edge data should be properly serialized to dictionaries
        AND all edge attributes should be preserved
        AND each edge should include 'source' and 'target' fields
        """
        result = await self.integrator.get_entity_neighborhood("entity_1", depth=1)
        
        # Find specific edge
        edge = next(edge for edge in result["edges"] if edge["source"] == "entity_1" and edge["target"] == "entity_2")
        
        # Validate serialization
        assert edge["relationship_type"] == "leads"
        assert edge["confidence"] == 0.9
        assert edge["source_chunks"] == ["chunk_1"]

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_breadth_first_traversal(self):
        """
        GIVEN a graph with multiple paths to the same node
        WHEN get_entity_neighborhood is called
        THEN breadth-first traversal should be used
        AND nodes should be included at their shortest distance from center
        """
        # Create a graph with multiple paths: entity_1 -> entity_2 -> entity_3 and entity_1 -> entity_3
        # entity_3 should be at depth 1 (shortest path) not depth 2
        
        # Add direct edge from entity_1 to entity_3 (already exists in setup)
        # entity_3 is reachable at depth 1 via direct connection and depth 2 via entity_2
        
        result = await self.integrator.get_entity_neighborhood("entity_1", depth=1)
        
        # entity_3 should be included at depth 1 due to direct connection
        node_ids = {node["id"] for node in result["nodes"]}
        assert "entity_3" in node_ids

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_predecessors_and_successors(self):
        """
        GIVEN a directed graph with incoming and outgoing edges
        WHEN get_entity_neighborhood is called
        THEN both predecessors and successors should be included
        AND directionality should be preserved in the subgraph
        """
        # Test from entity_2 which has both incoming and outgoing edges
        result = await self.integrator.get_entity_neighborhood("entity_2", depth=1)
        
        node_ids = {node["id"] for node in result["nodes"]}
        # Should include entity_1 (predecessor), entity_4 and entity_5 (successors)
        assert "entity_1" in node_ids  # incoming edge
        assert "entity_3" in node_ids  # incoming edge 
        assert "entity_4" in node_ids  # outgoing edge
        assert "entity_5" in node_ids  # outgoing edge

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_node_count_accuracy(self):
        """
        GIVEN a neighborhood result
        WHEN checking the node_count field
        THEN it should exactly match the length of the nodes list
        AND the count should be accurate for any depth
        """
        for depth in [0, 1, 2, 3]:
            result = await self.integrator.get_entity_neighborhood("entity_1", depth=depth)
            assert result["node_count"] == len(result["nodes"])

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_edge_count_accuracy(self):
        """
        GIVEN a neighborhood result
        WHEN checking the edge_count field
        THEN it should exactly match the length of the edges list
        AND the count should include all edges within the subgraph
        """
        for depth in [0, 1, 2, 3]:
            result = await self.integrator.get_entity_neighborhood("entity_1", depth=depth)
            assert result["edge_count"] == len(result["edges"])

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_empty_global_graph(self):
        """
        GIVEN an empty global graph
        WHEN get_entity_neighborhood is called with any entity_id
        THEN an error dictionary should be returned
        AND it should indicate the entity was not found
        """
        # Clear the global graph
        self.integrator.global_graph = nx.DiGraph()
        self.integrator.global_entities = {}
        
        result = await self.integrator.get_entity_neighborhood("any_entity")
        
        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_none_entity_id(self):
        """
        GIVEN None as the entity_id parameter
        WHEN get_entity_neighborhood is called
        THEN a TypeError should be raised
        AND the error should indicate invalid entity_id type
        """
        with pytest.raises(TypeError, match="entity_id must be a string."):
            await self.integrator.get_entity_neighborhood(None)

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_empty_entity_id(self):
        """
        GIVEN an empty string as entity_id
        WHEN get_entity_neighborhood is called
        THEN a ValueError should be raised
        AND the error should indicate invalid entity_id value
        """
        with pytest.raises(ValueError, match="entity_id must be a non-empty string."):
            await self.integrator.get_entity_neighborhood("")

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_negative_depth(self):
        """
        GIVEN a negative depth value
        WHEN get_entity_neighborhood is called
        THEN a ValueError should be raised
        AND the error should indicate invalid depth range
        """
        with pytest.raises(ValueError, match="depth must be a non-negative integer"):
            await self.integrator.get_entity_neighborhood("entity_1", depth=-1)

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_non_integer_depth(self):
        """
        GIVEN a non-integer depth parameter
        WHEN get_entity_neighborhood is called
        THEN a TypeError should be raised
        AND the error should indicate expected integer type
        """
        with pytest.raises(TypeError, match="depth must be an integer"):
            await self.integrator.get_entity_neighborhood("entity_1", depth=1.5)

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_serialization_compatibility(self):
        """
        GIVEN any valid neighborhood result
        WHEN the result is serialized to JSON
        THEN it should be fully serializable without errors
        AND all data types should be JSON-compatible
        """
        result = await self.integrator.get_entity_neighborhood("entity_1", depth=2)
        
        # Should not raise any exceptions
        json_str = json.dumps(result)
        assert isinstance(json_str, str)
        
        # Should be able to deserialize back
        deserialized = json.loads(json_str)
        assert deserialized == result

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_large_neighborhood(self):
        """
        GIVEN an entity with a very large neighborhood (>1000 nodes)
        WHEN get_entity_neighborhood is called
        THEN all nodes should be included correctly
        AND performance should remain reasonable
        AND memory usage should be manageable
        """
        # Create a large graph
        large_graph = nx.DiGraph()
        large_entities = {}
        
        # Create 1000 entities connected to entity_1
        for i in range(1000):
            entity_id = f"large_entity_{i}"
            entity = Entity(
                id=entity_id, name=f"Entity {i}", type="concept",
                description=f"Entity number {i}", confidence=0.5, 
                source_chunks=[f"chunk_{i}"], properties={}
            )
            large_entities[entity_id] = entity
            large_graph.add_node(entity_id, **{
                "name": entity.name, "type": entity.type,
                "confidence": entity.confidence, "source_chunks": entity.source_chunks
            })
            large_graph.add_edge("entity_1", entity_id, relationship_type="related_to", confidence=0.5)
        
        # Temporarily replace global graph
        original_graph = self.integrator.global_graph
        original_entities = self.integrator.global_entities
        
        self.integrator.global_graph = nx.compose(original_graph, large_graph)
        self.integrator.global_entities.update(large_entities)
        
        try:
            result = await self.integrator.get_entity_neighborhood("entity_1", depth=1)
            
            # Should include entity_1 + original neighbors + 1000 new entities
            assert result["node_count"] >= 1000
            assert result["edge_count"] >= 1000
        finally:
            # Restore original graph
            self.integrator.global_graph = original_graph
            self.integrator.global_entities = original_entities

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_cyclic_graph(self):
        """
        GIVEN a graph with cycles that could cause infinite traversal
        WHEN get_entity_neighborhood is called
        THEN the traversal should handle cycles correctly
        AND each node should be visited only once
        AND the algorithm should terminate properly
        """
        # Add a cycle: entity_4 -> entity_1 (completing a cycle)
        self.integrator.global_graph.add_edge("entity_4", "entity_1", 
                                            relationship_type="related_to", confidence=0.6)
        
        result = await self.integrator.get_entity_neighborhood("entity_1", depth=3)
        
        # Should terminate and not include duplicates
        node_ids = [node["id"] for node in result["nodes"]]
        unique_node_ids = set(node_ids)
        
        assert len(node_ids) == len(unique_node_ids)  # No duplicates
        assert result["node_count"] == len(unique_node_ids)

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_self_loops(self):
        """
        GIVEN an entity that has self-referencing edges
        WHEN get_entity_neighborhood is called
        THEN self-loops should be handled correctly
        AND the entity should not be duplicated in results
        """
        # Add self-loop
        self.integrator.global_graph.add_edge("entity_1", "entity_1", 
                                            relationship_type="self_reference", confidence=0.5)
        
        result = await self.integrator.get_entity_neighborhood("entity_1", depth=1)
        
        # Should not duplicate entity_1
        node_ids = [node["id"] for node in result["nodes"]]
        entity_1_count = node_ids.count("entity_1")
        assert entity_1_count == 1
        
        # Should include the self-loop edge
        self_loops = [edge for edge in result["edges"] 
                     if edge["source"] == "entity_1" and edge["target"] == "entity_1"]
        assert len(self_loops) == 1

    @pytest.mark.asyncio
    async def test_get_entity_neighborhood_concurrent_access(self):
        """
        GIVEN multiple concurrent calls to get_entity_neighborhood
        WHEN executed simultaneously
        THEN all calls should complete successfully
        AND results should be independent and correct
        AND no race conditions should occur
        """
        # Create multiple concurrent tasks
        tasks = []
        for i in range(10):
            task = asyncio.create_task(
                self.integrator.get_entity_neighborhood("entity_1", depth=1)
            )
            tasks.append(task)
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks)
        
        # All results should be identical and successful
        for result in results:
            assert "error" not in result
            assert result["center_entity_id"] == "entity_1"
            assert result["depth"] == 1
            assert result["node_count"] == 3
        
        # All results should be identical
        first_result = results[0]
        for result in results[1:]:
            assert result == first_result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
