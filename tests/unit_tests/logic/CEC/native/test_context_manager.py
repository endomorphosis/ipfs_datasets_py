"""
Tests for Context Manager Module.

Tests cover:
- Context state management
- Entity tracking
- Anaphora resolution
- Discourse analysis
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.context_manager import (
    EntityType,
    Entity,
    ContextState,
    ContextManager,
    AnaphoraResolver,
    DiscourseAnalyzer,
)


class TestEntity:
    """Test entity representation."""
    
    def test_entity_creation(self):
        """Test creating entities."""
        # GIVEN entity details
        name = "alice"
        entity_type = EntityType.AGENT
        
        # WHEN creating an entity
        entity = Entity(name, entity_type)
        
        # THEN it should have correct attributes
        assert entity.name == name
        assert entity.entity_type == entity_type
        assert len(entity.mentions) == 0
    
    def test_add_mention(self):
        """Test adding entity mentions."""
        # GIVEN an entity
        entity = Entity("bob", EntityType.AGENT)
        
        # WHEN adding mentions
        entity.add_mention(0)
        entity.add_mention(2)
        
        # THEN mentions should be tracked
        assert len(entity.mentions) == 2
        assert entity.most_recent_mention() == 2


class TestContextState:
    """Test context state."""
    
    def test_context_state_creation(self):
        """Test creating context state."""
        # WHEN creating a context state
        state = ContextState()
        
        # THEN it should initialize correctly
        assert len(state.entities) == 0
        assert state.focus is None
        assert state.position == 0
    
    def test_add_entity_to_context(self):
        """Test adding entities to context."""
        # GIVEN a context and entity
        state = ContextState()
        entity = Entity("alice", EntityType.AGENT)
        
        # WHEN adding the entity
        state.add_entity(entity)
        
        # THEN it should be in context
        assert "alice" in state.entities
        assert state.get_entity("alice") == entity
    
    def test_set_focus(self):
        """Test setting discourse focus."""
        # GIVEN a context and entity
        state = ContextState()
        entity = Entity("bob", EntityType.AGENT)
        state.add_entity(entity)
        
        # WHEN setting focus
        state.set_focus(entity)
        
        # THEN focus should be set
        assert state.focus == entity


class TestContextManager:
    """Test context manager."""
    
    @pytest.fixture
    def manager(self):
        """Create manager instance."""
        return ContextManager()
    
    def test_manager_initialization(self, manager):
        """Test manager initializes correctly."""
        # GIVEN a manager
        # THEN it should have initial state
        assert isinstance(manager.state, ContextState)
        assert len(manager.pronoun_mappings) > 0
    
    def test_process_single_utterance(self, manager):
        """Test processing single utterance."""
        # GIVEN an utterance
        utterance = "alice opens the door"
        
        # WHEN processing
        state = manager.process_utterance(utterance)
        
        # THEN context should be updated
        assert len(state.discourse_history) == 1
        assert state.position == 1
    
    def test_extract_entities(self, manager):
        """Test entity extraction."""
        # GIVEN an utterance with entities
        utterance = "alice and bob open the door"
        
        # WHEN processing
        manager.process_utterance(utterance)
        
        # THEN entities should be extracted
        entities = manager.get_active_entities()
        assert len(entities) > 0
    
    def test_resolve_reference(self, manager):
        """Test reference resolution."""
        # GIVEN context with entities
        manager.process_utterance("alice walks")
        
        # WHEN resolving a reference
        resolved = manager.resolve_reference("alice")
        
        # THEN should resolve correctly
        assert resolved is not None
        assert resolved.name == "alice"
    
    def test_get_discourse_history(self, manager):
        """Test getting discourse history."""
        # GIVEN multiple utterances
        manager.process_utterance("first utterance")
        manager.process_utterance("second utterance")
        
        # WHEN getting history
        history = manager.get_discourse_history()
        
        # THEN should return all utterances
        assert len(history) == 2
        assert history[0] == "first utterance"
    
    def test_reset_context(self, manager):
        """Test resetting context."""
        # GIVEN context with data
        manager.process_utterance("test utterance")
        
        # WHEN resetting
        manager.reset_context()
        
        # THEN context should be cleared
        assert len(manager.state.entities) == 0
        assert manager.state.position == 0


class TestAnaphoraResolver:
    """Test anaphora resolution."""
    
    @pytest.fixture
    def resolver(self):
        """Create resolver instance."""
        manager = ContextManager()
        return AnaphoraResolver(manager)
    
    def test_resolver_creation(self, resolver):
        """Test creating anaphora resolver."""
        # GIVEN a resolver
        # THEN it should initialize correctly
        assert resolver.context_manager is not None
        assert len(resolver.resolution_history) == 0
    
    def test_resolve_anaphora(self, resolver):
        """Test resolving anaphoric references."""
        # GIVEN context with an entity
        resolver.context_manager.process_utterance("alice walks")
        
        # WHEN resolving anaphora
        resolutions = resolver.resolve_anaphora("she runs")
        
        # THEN should resolve pronouns
        assert isinstance(resolutions, dict)


class TestDiscourseAnalyzer:
    """Test discourse analysis."""
    
    @pytest.fixture
    def analyzer(self):
        """Create analyzer instance."""
        return DiscourseAnalyzer()
    
    def test_analyzer_creation(self, analyzer):
        """Test creating discourse analyzer."""
        # GIVEN an analyzer
        # THEN it should initialize correctly
        assert len(analyzer.segments) == 0
    
    def test_segment_discourse(self, analyzer):
        """Test discourse segmentation."""
        # GIVEN multiple utterances
        utterances = [
            "alice walks to the door",
            "she opens it",
            "however bob arrives",
            "he closes the window"
        ]
        
        # WHEN segmenting
        segments = analyzer.segment_discourse(utterances)
        
        # THEN should create segments
        assert len(segments) > 0
        assert all(isinstance(seg, list) for seg in segments)
    
    def test_analyze_coherence(self, analyzer):
        """Test coherence analysis."""
        # GIVEN utterances
        utterances = [
            "alice walks",
            "alice runs",
            "bob sleeps"
        ]
        
        # WHEN analyzing coherence
        score = analyzer.analyze_coherence(utterances)
        
        # THEN should return a score
        assert 0.0 <= score <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
