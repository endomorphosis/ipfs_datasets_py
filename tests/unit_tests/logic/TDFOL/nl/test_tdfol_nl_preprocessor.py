"""
Tests for TDFOL Natural Language Preprocessor

Tests the NLPreprocessor class for sentence splitting, entity recognition,
dependency parsing, and temporal expression extraction.
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_preprocessor import (
    NLPreprocessor,
    ProcessedDocument,
    Entity,
    EntityType,
    TemporalExpression,
    DependencyRelation,
    HAVE_SPACY,
)

# Skip all tests if spaCy is not installed
pytestmark = pytest.mark.skipif(
    not HAVE_SPACY,
    reason="spaCy is not installed. Install with: pip install ipfs_datasets_py[knowledge_graphs]"
)


@pytest.fixture
def preprocessor():
    """Create NL preprocessor instance."""
    try:
        return NLPreprocessor()
    except (ImportError, OSError) as e:
        pytest.skip(f"Could not initialize preprocessor: {e}")


class TestNLPreprocessor:
    """Test suite for NL Preprocessor."""
    
    def test_initialization(self):
        """Test preprocessor initialization."""
        # GIVEN: spaCy is available
        # WHEN: Creating preprocessor
        preprocessor = NLPreprocessor()
        
        # THEN: Preprocessor should be initialized
        assert preprocessor is not None
        assert preprocessor.nlp is not None
    
    def test_simple_sentence(self, preprocessor):
        """Test processing a simple sentence."""
        # GIVEN: A simple sentence
        text = "Contractors must pay taxes."
        
        # WHEN: Processing the text
        doc = preprocessor.process(text)
        
        # THEN: Document should be processed
        assert isinstance(doc, ProcessedDocument)
        assert doc.text == text
        assert len(doc.sentences) == 1
        assert doc.sentences[0] == text
    
    def test_multiple_sentences(self, preprocessor):
        """Test sentence splitting."""
        # GIVEN: Multiple sentences
        text = "Contractors must pay taxes. Taxes are due annually. Payment is required."
        
        # WHEN: Processing the text
        doc = preprocessor.process(text)
        
        # THEN: Should split into 3 sentences
        assert len(doc.sentences) == 3
        assert "Contractors must pay taxes" in doc.sentences[0]
        assert "Taxes are due annually" in doc.sentences[1]
        assert "Payment is required" in doc.sentences[2]
    
    def test_entity_extraction_agents(self, preprocessor):
        """Test agent entity extraction."""
        # GIVEN: Text with agents
        text = "Alice must deliver the document to Bob."
        
        # WHEN: Processing the text
        doc = preprocessor.process(text)
        agents, actions, objects = preprocessor.extract_agents_actions_objects(doc)
        
        # THEN: Should extract agents
        assert len(agents) >= 1
        agent_texts = [e.text for e in agents]
        assert any('Alice' in t or 'Bob' in t for t in agent_texts)
    
    def test_entity_extraction_actions(self, preprocessor):
        """Test action entity extraction."""
        # GIVEN: Text with action verbs
        text = "Contractors must pay taxes."
        
        # WHEN: Processing the text
        doc = preprocessor.process(text)
        agents, actions, objects = preprocessor.extract_agents_actions_objects(doc)
        
        # THEN: Should extract actions
        assert len(actions) >= 1
        action_lemmas = [e.lemma for e in actions if e.lemma]
        assert any('pay' in lemma.lower() for lemma in action_lemmas)
    
    def test_entity_extraction_objects(self, preprocessor):
        """Test object entity extraction."""
        # GIVEN: Text with objects
        text = "Contractors must pay taxes."
        
        # WHEN: Processing the text
        doc = preprocessor.process(text)
        agents, actions, objects = preprocessor.extract_agents_actions_objects(doc)
        
        # THEN: Should extract objects
        assert len(objects) >= 1
        object_texts = [e.text.lower() for e in objects]
        assert any('tax' in t for t in object_texts)
    
    def test_temporal_expression_deadline(self, preprocessor):
        """Test temporal deadline extraction."""
        # GIVEN: Text with deadline
        text = "Payment must be made within 30 days."
        
        # WHEN: Processing the text
        doc = preprocessor.process(text)
        
        # THEN: Should extract temporal expression
        assert len(doc.temporal) >= 1
        deadline_exprs = [t for t in doc.temporal if t.type == 'deadline']
        assert len(deadline_exprs) >= 1
        assert '30' in deadline_exprs[0].text
        assert 'days' in deadline_exprs[0].text.lower()
    
    def test_temporal_expression_always(self, preprocessor):
        """Test temporal adverb extraction."""
        # GIVEN: Text with temporal adverb
        text = "Contractors must always pay taxes."
        
        # WHEN: Processing the text
        doc = preprocessor.process(text)
        
        # THEN: Should extract 'always'
        assert len(doc.temporal) >= 1
        temporal_texts = [t.text.lower() for t in doc.temporal]
        assert 'always' in temporal_texts
    
    def test_modal_extraction_must(self, preprocessor):
        """Test modal 'must' extraction."""
        # GIVEN: Text with 'must'
        text = "Contractors must pay taxes."
        
        # WHEN: Processing the text
        doc = preprocessor.process(text)
        
        # THEN: Should extract 'must'
        assert 'must' in doc.modalities
    
    def test_modal_extraction_may(self, preprocessor):
        """Test modal 'may' extraction."""
        # GIVEN: Text with 'may'
        text = "Contractors may request extensions."
        
        # WHEN: Processing the text
        doc = preprocessor.process(text)
        
        # THEN: Should extract 'may'
        assert 'may' in doc.modalities
    
    def test_modal_extraction_shall(self, preprocessor):
        """Test modal 'shall' extraction."""
        # GIVEN: Text with 'shall'
        text = "Contractors shall comply with regulations."
        
        # WHEN: Processing the text
        doc = preprocessor.process(text)
        
        # THEN: Should extract 'shall'
        assert 'shall' in doc.modalities
    
    def test_dependency_extraction(self, preprocessor):
        """Test dependency relation extraction."""
        # GIVEN: A simple sentence
        text = "Contractors must pay taxes."
        
        # WHEN: Processing the text
        doc = preprocessor.process(text)
        
        # THEN: Should extract dependencies
        assert len(doc.dependencies) > 0
        assert isinstance(doc.dependencies[0], DependencyRelation)
    
    def test_complex_sentence(self, preprocessor):
        """Test complex sentence with multiple features."""
        # GIVEN: A complex legal sentence
        text = "All contractors must pay taxes within 30 days of project completion."
        
        # WHEN: Processing the text
        doc = preprocessor.process(text)
        
        # THEN: Should extract all components
        assert len(doc.sentences) == 1
        assert len(doc.entities) > 0  # Should extract some entities
        assert len(doc.temporal) > 0  # Should find 'within 30 days'
        assert 'must' in doc.modalities  # Should find 'must'
        assert doc.metadata['num_sentences'] == 1


class TestEntityType:
    """Test EntityType enum."""
    
    def test_entity_types_defined(self):
        """Test that all entity types are defined."""
        # GIVEN: EntityType enum
        # WHEN: Checking types
        # THEN: Should have all required types
        assert EntityType.AGENT
        assert EntityType.ACTION
        assert EntityType.OBJECT
        assert EntityType.TIME
        assert EntityType.CONDITION
        assert EntityType.MODALITY
        assert EntityType.UNKNOWN


class TestEntity:
    """Test Entity dataclass."""
    
    def test_entity_creation(self):
        """Test creating an entity."""
        # GIVEN: Entity parameters
        text = "contractor"
        entity_type = EntityType.AGENT
        
        # WHEN: Creating entity
        entity = Entity(
            text=text,
            type=entity_type,
            start=0,
            end=10,
            lemma="contractor"
        )
        
        # THEN: Entity should be created correctly
        assert entity.text == text
        assert entity.type == entity_type
        assert entity.start == 0
        assert entity.end == 10
        assert entity.lemma == "contractor"
    
    def test_entity_hashable(self):
        """Test that entities are hashable."""
        # GIVEN: Two entities
        entity1 = Entity(text="contractor", type=EntityType.AGENT, start=0, end=10)
        entity2 = Entity(text="contractor", type=EntityType.AGENT, start=0, end=10)
        
        # WHEN: Adding to set
        entity_set = {entity1, entity2}
        
        # THEN: Should be hashable and equal
        assert len(entity_set) == 1


class TestProcessedDocument:
    """Test ProcessedDocument dataclass."""
    
    def test_document_creation(self):
        """Test creating a processed document."""
        # GIVEN: Document parameters
        text = "Test sentence."
        sentences = ["Test sentence."]
        entities = [Entity(text="Test", type=EntityType.UNKNOWN, start=0, end=4)]
        
        # WHEN: Creating document
        doc = ProcessedDocument(
            text=text,
            sentences=sentences,
            entities=entities,
            temporal=[],
            modalities=[],
            dependencies=[]
        )
        
        # THEN: Document should be created correctly
        assert doc.text == text
        assert len(doc.sentences) == 1
        assert len(doc.entities) == 1
        assert len(doc.temporal) == 0
        assert len(doc.modalities) == 0
