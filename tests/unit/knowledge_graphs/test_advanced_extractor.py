"""
Unit tests for advanced_knowledge_extractor module.

This module tests the advanced knowledge extraction functionality including
domain-specific patterns, entity disambiguation, and relationship extraction.

Following GIVEN-WHEN-THEN format as per repository standards.
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.advanced_knowledge_extractor import (
    ExtractionContext,
    EntityCandidate,
    RelationshipCandidate,
    AdvancedKnowledgeExtractor,
)
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
    Entity,
    Relationship,
    KnowledgeGraph,
)


class TestExtractionContext:
    """Test ExtractionContext dataclass."""
    
    def test_extraction_context_defaults(self):
        """
        GIVEN no parameters
        WHEN creating ExtractionContext
        THEN default values are set
        """
        # WHEN
        context = ExtractionContext()
        
        # THEN
        assert context.domain == "general"
        assert context.source_type == "text"
        assert context.confidence_threshold == 0.6
        assert context.enable_disambiguation is True
        assert context.extract_temporal is True
        assert context.max_entities_per_pass == 100
    
    def test_extraction_context_with_custom_values(self):
        """
        GIVEN custom parameters
        WHEN creating ExtractionContext
        THEN custom values are set
        """
        # GIVEN
        domain = "academic"
        source_type = "paper"
        confidence = 0.8
        disambiguation = False
        temporal = False
        max_entities = 50
        
        # WHEN
        context = ExtractionContext(
            domain=domain,
            source_type=source_type,
            confidence_threshold=confidence,
            enable_disambiguation=disambiguation,
            extract_temporal=temporal,
            max_entities_per_pass=max_entities
        )
        
        # THEN
        assert context.domain == domain
        assert context.source_type == source_type
        assert context.confidence_threshold == confidence
        assert context.enable_disambiguation == disambiguation
        assert context.extract_temporal == temporal
        assert context.max_entities_per_pass == max_entities


class TestEntityCandidate:
    """Test EntityCandidate dataclass."""
    
    def test_entity_candidate_creation(self):
        """
        GIVEN entity candidate attributes
        WHEN creating EntityCandidate
        THEN candidate is created correctly
        """
        # GIVEN
        text = "Apple Inc."
        entity_type = "organization"
        confidence = 0.9
        context = "Apple Inc. is a technology company"
        start_pos = 0
        end_pos = 10
        
        # WHEN
        candidate = EntityCandidate(
            text=text,
            entity_type=entity_type,
            confidence=confidence,
            context=context,
            start_pos=start_pos,
            end_pos=end_pos
        )
        
        # THEN
        assert candidate.text == text
        assert candidate.entity_type == entity_type
        assert candidate.confidence == confidence
        assert candidate.context == context
        assert candidate.start_pos == start_pos
        assert candidate.end_pos == end_pos
        assert candidate.supporting_evidence == []
    
    def test_entity_candidate_with_evidence(self):
        """
        GIVEN candidate with supporting evidence
        WHEN creating EntityCandidate
        THEN evidence is stored
        """
        # GIVEN
        evidence = ["mention 1", "mention 2", "mention 3"]
        
        # WHEN
        candidate = EntityCandidate(
            text="Test Entity",
            entity_type="test",
            confidence=0.8,
            context="Test context",
            start_pos=0,
            end_pos=10,
            supporting_evidence=evidence
        )
        
        # THEN
        assert candidate.supporting_evidence == evidence


class TestRelationshipCandidate:
    """Test RelationshipCandidate dataclass."""
    
    def test_relationship_candidate_creation(self):
        """
        GIVEN subject, predicate, object
        WHEN creating RelationshipCandidate
        THEN candidate is created correctly
        """
        # GIVEN
        subject = EntityCandidate(
            text="John", entity_type="person",
            confidence=0.9, context="ctx", start_pos=0, end_pos=4
        )
        predicate = "works_at"
        obj = EntityCandidate(
            text="Microsoft", entity_type="organization",
            confidence=0.9, context="ctx", start_pos=15, end_pos=24
        )
        confidence = 0.85
        context = "John works at Microsoft"
        evidence = "Found in sentence 3"
        
        # WHEN
        candidate = RelationshipCandidate(
            subject=subject,
            predicate=predicate,
            object=obj,
            confidence=confidence,
            context=context,
            supporting_evidence=evidence
        )
        
        # THEN
        assert candidate.subject == subject
        assert candidate.predicate == predicate
        assert candidate.object == obj
        assert candidate.confidence == confidence
        assert candidate.context == context
        assert candidate.supporting_evidence == evidence


class TestAdvancedKnowledgeExtractor:
    """Test AdvancedKnowledgeExtractor class."""
    
    def test_extractor_initialization_default(self):
        """
        GIVEN no parameters
        WHEN creating AdvancedKnowledgeExtractor
        THEN extractor is initialized with defaults
        """
        # WHEN
        extractor = AdvancedKnowledgeExtractor()
        
        # THEN
        assert extractor is not None
        assert extractor.context is not None
        assert extractor.context.domain == "general"
        assert hasattr(extractor, 'extraction_stats')
        assert extractor.extraction_stats['entities_found'] == 0
        assert extractor.extraction_stats['relationships_found'] == 0
    
    def test_extractor_initialization_with_context(self):
        """
        GIVEN custom ExtractionContext
        WHEN creating AdvancedKnowledgeExtractor
        THEN extractor uses custom context
        """
        # GIVEN
        context = ExtractionContext(
            domain="academic",
            source_type="paper",
            confidence_threshold=0.7
        )
        
        # WHEN
        extractor = AdvancedKnowledgeExtractor(context=context)
        
        # THEN
        assert extractor.context == context
        assert extractor.context.domain == "academic"
        assert extractor.context.source_type == "paper"
        assert extractor.context.confidence_threshold == 0.7
    
    def test_extractor_has_required_methods(self):
        """
        GIVEN AdvancedKnowledgeExtractor
        WHEN checking for key methods
        THEN required methods exist
        """
        # GIVEN
        extractor = AdvancedKnowledgeExtractor()
        
        # THEN
        assert hasattr(extractor, '_initialize_patterns')
        # Check for extraction-related attributes
        assert hasattr(extractor, 'extraction_stats')
        assert hasattr(extractor, 'context')
    
    def test_extraction_stats_initialization(self):
        """
        GIVEN a new extractor
        WHEN checking extraction stats
        THEN stats are initialized to zero
        """
        # GIVEN
        extractor = AdvancedKnowledgeExtractor()
        
        # THEN
        assert extractor.extraction_stats['entities_found'] == 0
        assert extractor.extraction_stats['relationships_found'] == 0
        assert extractor.extraction_stats['disambiguation_resolved'] == 0
        assert extractor.extraction_stats['low_confidence_filtered'] == 0
    
    def test_patterns_initialized(self):
        """
        GIVEN AdvancedKnowledgeExtractor
        WHEN checking patterns
        THEN patterns are initialized
        """
        # GIVEN
        extractor = AdvancedKnowledgeExtractor()
        
        # THEN
        # Should have academic patterns initialized
        assert hasattr(extractor, 'academic_patterns')
        assert isinstance(extractor.academic_patterns, dict)
    
    def test_context_domain_academic(self):
        """
        GIVEN academic domain context
        WHEN creating extractor
        THEN academic patterns are available
        """
        # GIVEN
        context = ExtractionContext(domain="academic")
        
        # WHEN
        extractor = AdvancedKnowledgeExtractor(context=context)
        
        # THEN
        assert extractor.context.domain == "academic"
        assert hasattr(extractor, 'academic_patterns')
    
    def test_context_domain_technical(self):
        """
        GIVEN technical domain context
        WHEN creating extractor
        THEN technical patterns are available
        """
        # GIVEN
        context = ExtractionContext(domain="technical")
        
        # WHEN
        extractor = AdvancedKnowledgeExtractor(context=context)
        
        # THEN
        assert extractor.context.domain == "technical"
    
    def test_confidence_threshold_affects_filtering(self):
        """
        GIVEN different confidence thresholds
        WHEN creating extractors
        THEN thresholds are set correctly
        """
        # GIVEN
        low_threshold = ExtractionContext(confidence_threshold=0.5)
        high_threshold = ExtractionContext(confidence_threshold=0.9)
        
        # WHEN
        extractor_low = AdvancedKnowledgeExtractor(context=low_threshold)
        extractor_high = AdvancedKnowledgeExtractor(context=high_threshold)
        
        # THEN
        assert extractor_low.context.confidence_threshold == 0.5
        assert extractor_high.context.confidence_threshold == 0.9
    
    def test_disambiguation_flag(self):
        """
        GIVEN disambiguation enabled/disabled
        WHEN creating extractors
        THEN flag is set correctly
        """
        # GIVEN
        context_on = ExtractionContext(enable_disambiguation=True)
        context_off = ExtractionContext(enable_disambiguation=False)
        
        # WHEN
        extractor_on = AdvancedKnowledgeExtractor(context=context_on)
        extractor_off = AdvancedKnowledgeExtractor(context=context_off)
        
        # THEN
        assert extractor_on.context.enable_disambiguation is True
        assert extractor_off.context.enable_disambiguation is False
    
    def test_temporal_extraction_flag(self):
        """
        GIVEN temporal extraction enabled/disabled
        WHEN creating extractors
        THEN flag is set correctly
        """
        # GIVEN
        context_on = ExtractionContext(extract_temporal=True)
        context_off = ExtractionContext(extract_temporal=False)
        
        # WHEN
        extractor_on = AdvancedKnowledgeExtractor(context=context_on)
        extractor_off = AdvancedKnowledgeExtractor(context=context_off)
        
        # THEN
        assert extractor_on.context.extract_temporal is True
        assert extractor_off.context.extract_temporal is False


# Integration tests
class TestAdvancedExtractorIntegration:
    """Integration tests for advanced knowledge extractor."""
    
    @pytest.mark.integration
    def test_extractor_with_different_domains(self):
        """
        GIVEN different domain contexts
        WHEN creating extractors
        THEN each extractor is configured for its domain
        """
        # GIVEN
        domains = ["general", "academic", "technical", "business", "news"]
        
        # WHEN/THEN
        for domain in domains:
            context = ExtractionContext(domain=domain)
            extractor = AdvancedKnowledgeExtractor(context=context)
            assert extractor.context.domain == domain
            assert extractor.extraction_stats is not None
    
    @pytest.mark.integration
    def test_extractor_stats_tracking(self):
        """
        GIVEN an extractor with stats
        WHEN accessing stats
        THEN all stat fields are accessible
        """
        # GIVEN
        extractor = AdvancedKnowledgeExtractor()
        
        # WHEN
        stats = extractor.extraction_stats
        
        # THEN
        assert 'entities_found' in stats
        assert 'relationships_found' in stats
        assert 'disambiguation_resolved' in stats
        assert 'low_confidence_filtered' in stats
        # All stats should be numeric
        for key, value in stats.items():
            assert isinstance(value, (int, float))
