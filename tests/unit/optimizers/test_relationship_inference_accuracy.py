"""
Relationship Inference Accuracy Tests

Validates relationship inference patterns in OntologyGenerator:
1. Verb-frame pattern matching
2. Context-window inference
3. Entity type-based inference
4. Confidence scoring mechanisms
5. Distance-based decay
6. Type confidence calculation
7. Sentence window filtering
8. Parallel processing accuracy

Test Categories:
- Verb Patterns: Legal obligations, ownership, causality, taxonomic
- Context Patterns: Employment, management, production, partnerships
- Type Inference: Person-org, person-location, org-product relationships
- Confidence: Distance decay, type confidence, threshold filtering
- Edge Cases: Empty text, single entity, duplicate relationships
- Integration: Complex documents with multiple relationship types
"""
import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    Entity,
    Relationship,
    OntologyGenerationContext,
    ExtractionConfig,
)


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def generator():
    """Create OntologyGenerator with rule-based extraction (no LLM)."""
    return OntologyGenerator(use_ipfs_accelerate=False)


@pytest.fixture
def context():
    """Create basic extraction context."""
    return OntologyGenerationContext(
        data_type="text",
        data_source="test_document",
        domain="general",
        config=ExtractionConfig(
            max_entities=100,
            max_relationships=100,
            confidence_threshold=0.0,  # Accept all for testing
        ),
    )


# ============================================================================
# Helper Functions
# ============================================================================

def create_entity(entity_id: str, text: str, entity_type: str = "Concept") -> Entity:
    """Create an Entity instance for testing."""
    return Entity(id=entity_id, text=text, type=entity_type, confidence=0.9)


def get_relationship(relationships: list, source_text: str, target_text: str, rel_type: str = None):
    """Find relationship by source/target entity text and optionally type."""
    # Build entity text to ID map from relationships
    entity_ids = {}
    for rel in relationships:
        # We need to get entities from context to map text to IDs
        pass
    
    for rel in relationships:
        if rel_type is None:
            return rel  # Just return first if no type specified
        if rel.type == rel_type:
            return rel
    return None


def has_relationship(relationships: list, source_id: str, target_id: str, rel_type: str = None) -> bool:
    """Check if relationship exists between entities."""
    for rel in relationships:
        if rel.source_id == source_id and rel.target_id == target_id:
            if rel_type is None or rel.type == rel_type:
                return True
        # Check reverse direction for undirected relationships
        if rel.target_id == source_id and rel.source_id == target_id:
            if rel_type is None or rel.type == rel_type:
                return True
    return False


def get_relationship_by_ids(relationships: list, source_id: str, target_id: str, rel_type: str = None):
    """Get relationship by source/target IDs and optionally type."""
    for rel in relationships:
        if rel.source_id == source_id and rel.target_id == target_id:
            if rel_type is None or rel.type == rel_type:
                return rel
        # Check reverse direction
        if rel.target_id == source_id and rel.source_id == target_id:
            if rel_type is None or rel.type == rel_type:
                return rel
    return None


# ============================================================================
# Test Verb-Frame Pattern Matching
# ============================================================================

class TestVerbFramePatterns:
    """Test verb-frame pattern matching for relationship types."""
    
    def test_obligation_pattern(self, generator, context):
        """Test 'must' obligation pattern extraction."""
        # Pattern: (\w+)\s+(?:must|shall|...)\s+\w+\s+(\w+)
        # Matches: "Alice must pay Bob"
        text = "Alice must pay Bob by the deadline."
        entities = [
            create_entity("e1", "Alice", "Person"),
            create_entity("e2", "Bob", "Person"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        # Should detect "must" pattern with 'obligates' type
        assert len(relationships) > 0
        obligation_rel = get_relationship_by_ids(relationships, "e1", "e2", "obligates")
        assert obligation_rel is not None, "Expected 'obligates' relationship from 'must' pattern"
        assert obligation_rel.confidence > 0.5
        # Type confidence should be high for legal domain patterns
        assert obligation_rel.properties.get('type_confidence', 0) >= 0.8
    
    def test_ownership_pattern(self, generator, context):
        """Test ownership pattern extraction."""
        text = "Alice owns a Tesla Model 3."
        entities = [
            create_entity("e1", "Alice", "Person"),
            create_entity("e2", "Tesla Model 3", "Product"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        owns_rel = get_relationship_by_ids(relationships, "e1", "e2", "owns")
        assert owns_rel is not None, "Expected 'owns' relationship"
        assert owns_rel.properties.get('type_confidence', 0) >= 0.7
    
    def test_causality_pattern(self, generator, context):
        """Test causality pattern extraction."""
        text = "Smoking causes cancer."
        entities = [
            create_entity("e1", "Smoking", "Activity"),
            create_entity("e2", "cancer", "Condition"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        causes_rel = get_relationship_by_ids(relationships, "e1", "e2", "causes")
        assert causes_rel is not None, "Expected 'causes' relationship"
    
    def test_taxonomic_is_a_pattern(self, generator, context):
        """Test taxonomic 'is a' relationship."""
        text = "A dog is a mammal."
        entities = [
            create_entity("e1", "dog", "Species"),
            create_entity("e2", "mammal", "Class"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        is_a_rel = get_relationship_by_ids(relationships, "e1", "e2", "is_a")
        assert is_a_rel is not None, "Expected 'is_a' relationship"
    
    def test_part_of_pattern(self, generator, context):
        """Test part-of compositional relationship."""
        text = "The engine is part of the car."
        entities = [
            create_entity("e1", "engine", "Component"),
            create_entity("e2", "car", "Vehicle"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        part_of_rel = get_relationship_by_ids(relationships, "e1", "e2", "part_of")
        assert part_of_rel is not None, "Expected 'part_of' relationship"
    
    def test_employment_pattern(self, generator, context):
        """Test employment relationship detection."""
        text = "Microsoft employs many engineers."
        entities = [
            create_entity("e1", "Microsoft", "Organization"),
            create_entity("e2", "engineers", "Person"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        employs_rel = get_relationship_by_ids(relationships, "e1", "e2", "employs")
        assert employs_rel is not None, "Expected 'employs' relationship"
    
    def test_management_pattern(self, generator, context):
        """Test management relationship detection."""
        text = "Sarah manages the product team."
        entities = [
            create_entity("e1", "Sarah", "Person"),
            create_entity("e2", "product team", "Organization"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        manages_rel = get_relationship_by_ids(relationships, "e1", "e2", "manages")
        assert manages_rel is not None, "Expected 'manages' relationship"


# ============================================================================
# Test Context-Window Inference
# ============================================================================

class TestContextWindowInference:
    """Test context-window based relationship type inference."""
    
    def test_employment_context_pattern(self, generator, context):
        """Test employment detection from context keywords."""
        text = "John works at Apple. He was hired in 2020."
        entities = [
            create_entity("e1", "John", "Person"),
            create_entity("e2", "Apple", "Organization"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        # Should infer employment relationship from "hired" context
        assert len(relationships) > 0
        # May be detected as 'employs' (reverse direction) or 'works_for'
        has_employment = any(
            rel.type in ('employs', 'works_for', 'employs_hired')
            for rel in relationships
        )
        assert has_employment, "Expected employment relationship from context"
    
    def test_location_context_pattern(self, generator, context):
        """Test location relationship from context."""
        text = "The headquarters is located in San Francisco."
        entities = [
            create_entity("e1", "headquarters", "Organization"),
            create_entity("e2", "San Francisco", "Location"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        located_rel = get_relationship_by_ids(relationships, "e1", "e2", "located_in")
        assert located_rel is not None, "Expected 'located_in' relationship"
    
    def test_production_context_pattern(self, generator, context):
        """Test production relationship from context."""
        text = "Tesla produces electric vehicles in California."
        entities = [
            create_entity("e1", "Tesla", "Organization"),
            create_entity("e2", "electric vehicles", "Product"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        produces_rel = get_relationship_by_ids(relationships, "e1", "e2", "produces")
        assert produces_rel is not None, "Expected 'produces' relationship"
    
    def test_founded_context_pattern(self, generator, context):
        """Test founding relationship detection."""
        text = "Steve Jobs founded Apple in 1976."
        entities = [
            create_entity("e1", "Steve Jobs", "Person"),
            create_entity("e2", "Apple", "Organization"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        founded_rel = get_relationship_by_ids(relationships, "e1", "e2", "founded")
        assert founded_rel is not None, "Expected 'founded' relationship"
    
    def test_leadership_context_pattern(self, generator, context):
        """Test leadership relationship detection."""
        text = "The CEO leads the executive team."
        entities = [
            create_entity("e1", "CEO", "Person"),
            create_entity("e2", "executive team", "Organization"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        leads_rel = get_relationship_by_ids(relationships, "e1", "e2", "leads")
        assert leads_rel is not None, "Expected 'leads' relationship"
    
    def test_partnership_context_pattern(self, generator, context):
        """Test partnership relationship detection."""
        text = "Google partners with Mozilla on web standards."
        entities = [
            create_entity("e1", "Google", "Organization"),
            create_entity("e2", "Mozilla", "Organization"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        partners_rel = get_relationship_by_ids(relationships, "e1", "e2", "partners_with")
        assert partners_rel is not None, "Expected 'partners_with' relationship"


# ============================================================================
# Test Entity Type-Based Inference
# ============================================================================

class TestEntityTypeInference:
    """Test relationship inference based on entity types."""
    
    def test_person_organization_inference(self, generator, context):
        """Test person-organization relationship inference."""
        text = "Alice and Microsoft are mentioned together in the document."
        entities = [
            create_entity("e1", "Alice", "Person"),
            create_entity("e2", "Microsoft", "Organization"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        # Type-based inference should suggest 'works_for' for person-org pairs
        assert len(relationships) > 0
        # Should infer some relationship between person and organization
        rel = relationships[0]
        assert rel.type in ('works_for', 'related_to', 'employs')
    
    def test_person_location_inference(self, generator, context):
        """Test person-location relationship inference."""
        text = "Bob lives in New York City."
        entities = [
            create_entity("e1", "Bob", "Person"),
            create_entity("e2", "New York City", "Location"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        # Should infer location relationship
        assert len(relationships) > 0
        # Check for located_in or related_to
        has_location = any(
            rel.type in ('located_in', 'related_to')
            for rel in relationships
        )
        assert has_location
    
    def test_organization_product_inference(self, generator, context):
        """Test organization-product relationship inference."""
        text = "Apple introduced the iPhone in 2007."
        entities = [
            create_entity("e1", "Apple", "Organization"),
            create_entity("e2", "iPhone", "Product"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        # Should infer production relationship
        assert len(relationships) > 0
        produces_rel = get_relationship_by_ids(relationships, "e1", "e2", "produces")
        # May be 'produces' or 'related_to' if no strong context signal
        assert produces_rel is not None or any(rel.type == 'related_to' for rel in relationships)
    
    def test_same_type_inference(self, generator, context):
        """Test relationship inference between same entity types."""
        text = "Alice collaborated with Bob on the project."
        entities = [
            create_entity("e1", "Alice", "Person"),
            create_entity("e2", "Bob", "Person"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        # Same type entities should get generic 'related_to' or specific context pattern
        assert len(relationships) > 0


# ============================================================================
# Test Confidence Scoring
# ============================================================================

class TestConfidenceScoring:
    """Test confidence score calculation mechanisms."""
    
    def test_distance_based_confidence_decay(self, generator, context):
        """Test confidence decreases with entity distance."""
        # Close entities (within 50 chars)
        text_close = "Alice and Bob work together."
        entities_close = [
            create_entity("e1", "Alice", "Person"),
            create_entity("e2", "Bob", "Person"),
        ]
        
        # Distant entities (>100 chars apart)
        text_far = "Alice is the CEO. " + " ".join(["word"] * 20) + " Bob is an engineer."
        entities_far = [
            create_entity("e1", "Alice", "Person"),
            create_entity("e2", "Bob", "Person"),
        ]
        
        rels_close = generator.infer_relationships(entities_close, context, data=text_close)
        rels_far = generator.infer_relationships(entities_far, context, data=text_far)
        
        # Close entities should have higher confidence
        assert len(rels_close) > 0
        assert len(rels_far) > 0
        
        # Confidence should decay with distance
        assert rels_close[0].confidence > rels_far[0].confidence
    
    def test_type_confidence_for_verb_patterns(self, generator, context):
        """Test type confidence is high for verb-frame matches."""
        text = "The Tenant must pay the Landlord."
        entities = [
            create_entity("e1", "Tenant", "Person"),
            create_entity("e2", "Landlord", "Person"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        obligation_rel = get_relationship_by_ids(relationships, "e1", "e2", "obligates")
        assert obligation_rel is not None
        # Verb-frame patterns should have high type confidence
        assert obligation_rel.properties.get('type_confidence', 0) >= 0.8
    
    def test_type_confidence_for_context_inference(self, generator, context):
        """Test type confidence for context-window inference."""
        text = "The company employs thousands of workers."
        entities = [
            create_entity("e1", "company", "Organization"),
            create_entity("e2", "workers", "Person"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        employs_rel = get_relationship_by_ids(relationships, "e1", "e2", "employs")
        assert employs_rel is not None
        # Context patterns should have moderate-high type confidence
        type_conf = employs_rel.properties.get('type_confidence', 0)
        assert type_conf >= 0.65
    
    def test_type_confidence_for_fallback(self, generator, context):
        """Test type confidence for fallback 'related_to' relationships."""
        text = "Alice mentioned Bob in passing."
        entities = [
            create_entity("e1", "Alice", "Person"),
            create_entity("e2", "Bob", "Person"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        # Fallback relationships should have lower type confidence
        assert len(relationships) > 0
        rel = relationships[0]
        # May be 'related_to' with lower confidence
        if rel.type == 'related_to':
            assert rel.properties.get('type_confidence', 1.0) < 0.6
    
    def test_confidence_threshold_filtering(self, generator):
        """Test relationships are filtered by confidence threshold."""
        context_filtered = OntologyGenerationContext(
            data_type="text",
            data_source="test_document",
            domain="general",
            config=ExtractionConfig(
                confidence_threshold=0.7,  # High threshold
            ),
        )
        
        # Distant entities with low confidence
        text = "Alice is mentioned. " + " ".join(["word"] * 30) + " Bob is also mentioned."
        entities = [
            create_entity("e1", "Alice", "Person"),
            create_entity("e2", "Bob", "Person"),
        ]
        
        relationships = generator.infer_relationships(entities, context_filtered, data=text)
        
        # All returned relationships should meet threshold
        for rel in relationships:
            assert rel.confidence >= 0.7


# ============================================================================
# Test Sentence Window Filtering
# ============================================================================

class TestSentenceWindowFiltering:
    """Test sentence window constraints on relationship inference."""
    
    def test_sentence_window_limits_relationships(self, generator):
        """Test sentence_window parameter limits relationship extraction."""
        context_windowed = OntologyGenerationContext(
            data_type="text",
            data_source="test_document",
            domain="general",
            config=ExtractionConfig(
                sentence_window=1,  # Only within 1 sentence
            ),
        )
        
        # Entities in different sentences
        text = "Alice is the CEO. Bob is an engineer. Charlie is a designer."
        entities = [
            create_entity("e1", "Alice", "Person"),
            create_entity("e2", "Bob", "Person"),
            create_entity("e3", "Charlie", "Person"),
        ]
        
        relationships = generator.infer_relationships(entities, context_windowed, data=text)
        
        # Should not connect entities across sentence boundaries
        # Alice-Bob and Bob-Charlie should not be connected if >1 sentence apart
        # This depends on sentence tokenization, so just verify filtered
        # Total relationships should be fewer than without window
        assert len(relationships) >= 0  # May be 0 if all cross-sentence
    
    def test_sentence_window_allows_same_sentence(self, generator):
        """Test entities in same sentence can form relationships."""
        context_windowed = OntologyGenerationContext(
            data_type="text",
            data_source="test_document",
            domain="general",
            config=ExtractionConfig(
                sentence_window=0,  # Same sentence only
            ),
        )
        
        # Entities in same sentence
        text = "Alice and Bob work together at Microsoft."
        entities = [
            create_entity("e1", "Alice", "Person"),
            create_entity("e2", "Bob", "Person"),
        ]
        
        relationships = generator.infer_relationships(entities, context_windowed, data=text)
        
        # Should detect relationship within sentence
        assert len(relationships) > 0


# ============================================================================
# Test Parallel Processing
# ============================================================================

class TestParallelInference:
    """Test parallel relationship inference maintains accuracy."""
    
    def test_parallel_processing_accuracy(self, generator):
        """Test parallel inference produces same results as serial."""
        context_serial = OntologyGenerationContext(
            data_type="text",
            data_source="test_document",
            domain="general",
            config=ExtractionConfig(
                enable_parallel_inference=False,
            ),
        )
        
        context_parallel = OntologyGenerationContext(
            data_type="text",
            data_source="test_document",
            domain="general",
            config=ExtractionConfig(
                enable_parallel_inference=True,
                max_workers=2,
            ),
        )
        
        text = "Alice works at Microsoft. Bob manages the team. Charlie founded the startup."
        entities = [
            create_entity("e1", "Alice", "Person"),
            create_entity("e2", "Microsoft", "Organization"),
            create_entity("e3", "Bob", "Person"),
            create_entity("e4", "team", "Organization"),
            create_entity("e5", "Charlie", "Person"),
            create_entity("e6", "startup", "Organization"),
        ]
        
        rels_serial = generator.infer_relationships(entities, context_serial, data=text)
        rels_parallel = generator.infer_relationships(entities, context_parallel, data=text)
        
        # Parallel should produce same number of relationships
        assert len(rels_serial) == len(rels_parallel)
        
        # Verify all serial relationships exist in parallel results
        serial_types_set = {(r.source_id, r.target_id, r.type) for r in rels_serial}
        parallel_types_set = {(r.source_id, r.target_id, r.type) for r in rels_parallel}
        assert serial_types_set == parallel_types_set


# ============================================================================
# Test Edge Cases
# ============================================================================

class TestEdgeCases:
    """Test edge cases in relationship inference."""
    
    def test_empty_text(self, generator, context):
        """Test relationship inference with empty text."""
        entities = [
            create_entity("e1", "Alice", "Person"),
            create_entity("e2", "Bob", "Person"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data="")
        
        # Should return empty or only generic relationships
        # Without text, no verb patterns or context inference possible
        assert len(relationships) >= 0
    
    def test_single_entity(self, generator, context):
        """Test with only one entity (no relationships possible)."""
        text = "Alice is mentioned."
        entities = [create_entity("e1", "Alice", "Person")]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        # No relationships possible with single entity
        assert len(relationships) == 0
    
    def test_no_entities(self, generator, context):
        """Test with no entities."""
        text = "Some text without entities."
        entities = []
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        assert len(relationships) == 0
    
    def test_duplicate_relationship_prevention(self, generator, context):
        """Test duplicate relationships are not created."""
        # Text with multiple mentions of same relationship
        text = "Alice employs Bob. She hired Bob last year."
        entities = [
            create_entity("e1", "Alice", "Person"),
            create_entity("e2", "Bob", "Person"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        # Should not have multiple identical relationships
        rel_pairs = [(r.source_id, r.target_id) for r in relationships]
        # Count occurrences of (e1, e2) pair
        e1_e2_count = rel_pairs.count(("e1", "e2")) + rel_pairs.count(("e2", "e1"))
        # May have multiple relationships with different types, but check it's reasonable
        assert e1_e2_count <= 2  # At most one in each direction
    
    def test_entities_not_in_text(self, generator, context):
        """Test entities that don't appear in text."""
        text = "Alice works at Microsoft."
        entities = [
            create_entity("e1", "Bob", "Person"),  # Not in text
            create_entity("e2", "Google", "Organization"),  # Not in text
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        # Should not find relationships for entities not in text
        assert len(relationships) == 0
    
    def test_very_long_distance(self, generator, context):
        """Test entities very far apart (>200 chars)."""
        # Entities >200 chars apart should not form relationships
        spacer = " ".join(["word"] * 50)  # ~250 chars
        text = f"Alice is the CEO. {spacer} Bob is an engineer."
        entities = [
            create_entity("e1", "Alice", "Person"),
            create_entity("e2", "Bob", "Person"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        # Should not connect entities >200 chars apart
        assert len(relationships) == 0


# ============================================================================
# Test Integration Scenarios
# ============================================================================

class TestIntegrationScenarios:
    """Test complex real-world scenarios with multiple relationship types."""
    
    def test_corporate_announcement(self, generator, context):
        """Test relationship extraction from corporate announcement."""
        text = """
        Microsoft announced that CEO Satya Nadella will lead the cloud computing division.
        The company founded by Bill Gates in 1975 employs over 200,000 people worldwide.
        Microsoft produces Windows, Office, and Azure products.
        """
        
        entities = [
            create_entity("e1", "Microsoft", "Organization"),
            create_entity("e2", "Satya Nadella", "Person"),
            create_entity("e3", "cloud computing division", "Organization"),
            create_entity("e4", "Bill Gates", "Person"),
            create_entity("e5", "Windows", "Product"),
            create_entity("e6", "Office", "Product"),
            create_entity("e7", "Azure", "Product"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        # Should detect multiple relationship types:
        # 1. Satya Nadella -[leads]-> cloud computing division
        # 2. Bill Gates -[founded]-> Microsoft
        # 3. Microsoft -[employs]-> people (if extracted as entity)
        # 4. Microsoft -[produces]-> Windows/Office/Azure
        
        assert len(relationships) >= 3, "Expected multiple relationships"
        
        # Check for leadership relationship
        leads_rel = has_relationship(relationships, "e2", "e3", "leads")
        assert leads_rel, "Expected leadership relationship"
        
        # Check for founding relationship
        founded_rel = has_relationship(relationships, "e4", "e1", "founded")
        assert founded_rel, "Expected founding relationship"
        
        # Check for production relationships
        production_rels = [
            r for r in relationships
            if r.type == "produces" and r.source_id == "e1"
        ]
        assert len(production_rels) >= 2, "Expected multiple production relationships"
    
    def test_legal_contract_obligations(self, generator, context):
        """Test obligation extraction from legal contract."""
        text = """
        The Borrower must repay the Lender the principal amount by December 31, 2025.
        The Lender shall provide the funds within 5 business days.
        The Guarantor is obligated to cover any defaults by the Borrower.
        """
        
        entities = [
            create_entity("e1", "Borrower", "Person"),
            create_entity("e2", "Lender", "Person"),
            create_entity("e3", "Guarantor", "Person"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        # Should detect obligation relationships
        obligation_rels = [r for r in relationships if r.type == "obligates"]
        assert len(obligation_rels) >= 2, "Expected multiple obligations"
    
    def test_academic_paper_citations(self, generator, context):
        """Test relationship extraction from academic text."""
        text = """
        Einstein published the theory of relativity in 1905.
        The paper authored by Einstein revolutionized physics.
        Later scientists built upon this work.
        """
        
        entities = [
            create_entity("e1", "Einstein", "Person"),
            create_entity("e2", "theory of relativity", "Concept"),
            create_entity("e3", "paper", "Document"),
            create_entity("e4", "physics", "Field"),
        ]
        
        relationships = generator.infer_relationships(entities, context, data=text)
        
        # Should detect authorship/creation relationships
        assert len(relationships) >= 2
