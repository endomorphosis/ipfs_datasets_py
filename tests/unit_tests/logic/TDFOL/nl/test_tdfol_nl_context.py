"""
Tests for TDFOL Context Resolver

Tests the ContextResolver class for tracking context across sentences
and resolving references.
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_context import (
    Context,
    ContextResolver,
    Entity,
)


@pytest.fixture
def context():
    """Create empty context."""
    return Context()


@pytest.fixture
def resolver():
    """Create context resolver."""
    return ContextResolver()


class TestContext:
    """Test suite for Context class."""
    
    def test_context_creation(self):
        """Test creating empty context."""
        # GIVEN: Nothing
        # WHEN: Creating context
        context = Context()
        
        # THEN: Context should be empty
        assert len(context.entities) == 0
        assert context.current_sentence == 0
        assert context.last_mentioned is None
    
    def test_add_entity(self, context):
        """Test adding entity to context."""
        # GIVEN: Empty context
        # WHEN: Adding entity
        entity = context.add_entity("contractor", "AGENT", sentence_id=0)
        
        # THEN: Entity should be added
        assert entity.name == "contractor"
        assert entity.type == "AGENT"
        assert "contractor" in entity.mentions
        assert 0 in entity.sentence_ids
        assert context.last_mentioned == "contractor"
    
    def test_add_duplicate_entity(self, context):
        """Test adding same entity multiple times."""
        # GIVEN: Context with one entity
        context.add_entity("contractor", "AGENT", sentence_id=0)
        
        # WHEN: Adding same entity again
        entity = context.add_entity("contractor", "AGENT", sentence_id=1)
        
        # THEN: Should update existing entity
        assert len(context.entities) == 1
        assert len(entity.mentions) == 2
        assert len(entity.sentence_ids) == 2
    
    def test_resolve_pronoun_he(self, context):
        """Test resolving 'he' pronoun."""
        # GIVEN: Context with an entity
        context.add_entity("contractor", "PERSON", sentence_id=0)
        
        # WHEN: Resolving 'he'
        resolved = context.resolve_reference("he")
        
        # THEN: Should resolve to last mentioned entity
        assert resolved == "contractor"
    
    def test_resolve_pronoun_they(self, context):
        """Test resolving 'they' pronoun."""
        # GIVEN: Context with an entity
        context.add_entity("contractors", "AGENT", sentence_id=0)
        
        # WHEN: Resolving 'they'
        resolved = context.resolve_reference("they")
        
        # THEN: Should resolve to last mentioned entity
        assert resolved == "contractors"
    
    def test_resolve_definite_description(self, context):
        """Test resolving 'the <entity>' pattern."""
        # GIVEN: Context with an entity
        context.add_entity("contractor", "AGENT", sentence_id=0)
        
        # WHEN: Resolving 'the contractor'
        resolved = context.resolve_reference("the contractor")
        
        # THEN: Should resolve to entity
        assert resolved == "contractor"
    
    def test_resolve_direct_match(self, context):
        """Test resolving direct entity name."""
        # GIVEN: Context with an entity
        context.add_entity("contractor", "AGENT", sentence_id=0)
        
        # WHEN: Resolving by name
        resolved = context.resolve_reference("contractor")
        
        # THEN: Should resolve to entity
        assert resolved == "contractor"
    
    def test_resolve_unknown_reference(self, context):
        """Test resolving unknown reference."""
        # GIVEN: Empty context
        # WHEN: Resolving unknown reference
        resolved = context.resolve_reference("unknown")
        
        # THEN: Should return None
        assert resolved is None
    
    def test_get_entity(self, context):
        """Test getting entity by name."""
        # GIVEN: Context with entity
        context.add_entity("contractor", "AGENT", sentence_id=0)
        
        # WHEN: Getting entity
        entity = context.get_entity("contractor")
        
        # THEN: Should return entity
        assert entity is not None
        assert entity.name == "contractor"
    
    def test_list_entities(self, context):
        """Test listing all entities."""
        # GIVEN: Context with multiple entities
        context.add_entity("contractor", "AGENT", sentence_id=0)
        context.add_entity("employee", "PERSON", sentence_id=1)
        
        # WHEN: Listing entities
        entities = context.list_entities()
        
        # THEN: Should return all entities
        assert len(entities) == 2
        names = {e.name for e in entities}
        assert "contractor" in names
        assert "employee" in names
    
    def test_clear_context(self, context):
        """Test clearing context."""
        # GIVEN: Context with entities
        context.add_entity("contractor", "AGENT", sentence_id=0)
        context.current_sentence = 5
        
        # WHEN: Clearing context
        context.clear()
        
        # THEN: Context should be empty
        assert len(context.entities) == 0
        assert context.current_sentence == 0
        assert context.last_mentioned is None


class TestContextResolver:
    """Test suite for ContextResolver class."""
    
    def test_initialization(self):
        """Test resolver initialization."""
        # GIVEN: Nothing
        # WHEN: Creating resolver
        resolver = ContextResolver()
        
        # THEN: Resolver should be created
        assert resolver is not None
    
    def test_build_context_from_doc(self, resolver):
        """Test building context from processed document."""
        # GIVEN: Mock processed document
        from dataclasses import dataclass
        from enum import Enum
        
        class EntityType(Enum):
            AGENT = "AGENT"
        
        @dataclass
        class MockEntity:
            text: str
            type: EntityType
        
        @dataclass
        class MockDoc:
            text: str
            entities: list
        
        doc = MockDoc(
            text="Contractors must pay taxes.",
            entities=[MockEntity("contractors", EntityType.AGENT)]
        )
        
        # WHEN: Building context
        context = resolver.build_context(doc, sentence_id=0)
        
        # THEN: Context should have entities
        assert len(context.entities) > 0
        assert context.current_sentence == 0
    
    def test_update_context(self, resolver):
        """Test updating existing context with new document."""
        # GIVEN: Existing context and new document
        from dataclasses import dataclass
        from enum import Enum
        
        class EntityType(Enum):
            AGENT = "AGENT"
            PERSON = "PERSON"
        
        @dataclass
        class MockEntity:
            text: str
            type: EntityType
        
        @dataclass
        class MockDoc:
            text: str
            entities: list
        
        context = Context()
        context.add_entity("contractor", "AGENT", sentence_id=0)
        
        doc = MockDoc(
            text="Employees must comply.",
            entities=[MockEntity("employees", EntityType.PERSON)]
        )
        
        # WHEN: Updating context
        updated = resolver.update_context(context, doc, sentence_id=1)
        
        # THEN: Context should have both entities
        assert len(updated.entities) == 2
        assert updated.current_sentence == 1
    
    def test_resolve_references(self, resolver):
        """Test resolving references in document."""
        # GIVEN: Context with entities and document with pronouns
        from dataclasses import dataclass
        
        @dataclass
        class MockDoc:
            text: str
        
        context = Context()
        context.add_entity("contractor", "AGENT", sentence_id=0)
        
        doc = MockDoc(text="They must comply with regulations.")
        
        # WHEN: Resolving references
        resolutions = resolver.resolve_references(doc, context)
        
        # THEN: Should resolve pronouns
        assert 'they' in resolutions
        assert resolutions['they'] == "contractor"
    
    def test_merge_contexts(self, resolver):
        """Test merging two contexts."""
        # GIVEN: Two contexts with different entities
        context1 = Context()
        context1.add_entity("contractor", "AGENT", sentence_id=0)
        
        context2 = Context()
        context2.add_entity("employee", "PERSON", sentence_id=1)
        
        # WHEN: Merging contexts
        merged = resolver.merge_contexts(context1, context2)
        
        # THEN: Merged context should have both entities
        assert len(merged.entities) == 2
        assert merged.get_entity("contractor") is not None
        assert merged.get_entity("employee") is not None
    
    def test_merge_overlapping_entities(self, resolver):
        """Test merging contexts with same entity."""
        # GIVEN: Two contexts with same entity
        context1 = Context()
        context1.add_entity("contractor", "AGENT", sentence_id=0)
        
        context2 = Context()
        context2.add_entity("contractor", "AGENT", sentence_id=1)
        
        # WHEN: Merging contexts
        merged = resolver.merge_contexts(context1, context2)
        
        # THEN: Should merge mentions
        assert len(merged.entities) == 1
        entity = merged.get_entity("contractor")
        assert len(entity.mentions) == 2
        assert len(entity.sentence_ids) == 2
    
    def test_get_coreference_chains(self, resolver):
        """Test getting coreference chains."""
        # GIVEN: Context with entity mentioned multiple times
        context = Context()
        context.add_entity("contractor", "AGENT", sentence_id=0)
        context.add_entity("contractor", "AGENT", sentence_id=1)
        context.add_entity("contractor", "AGENT", sentence_id=2)
        
        # WHEN: Getting coreference chains
        chains = resolver.get_coreference_chains(context)
        
        # THEN: Should return chains
        assert len(chains) > 0
        assert any(len(chain) > 1 for chain in chains)


class TestEntity:
    """Test Entity dataclass."""
    
    def test_entity_creation(self):
        """Test creating an entity."""
        # GIVEN: Entity data
        # WHEN: Creating entity
        entity = Entity(
            name="contractor",
            type="AGENT",
            aliases={"contractor", "contractors"},
            mentions=["contractor", "Contractor"],
            sentence_ids=[0, 1, 2]
        )
        
        # THEN: Entity should be created
        assert entity.name == "contractor"
        assert entity.type == "AGENT"
        assert len(entity.aliases) == 2
        assert len(entity.mentions) == 2
        assert len(entity.sentence_ids) == 3
