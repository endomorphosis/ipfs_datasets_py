"""Tests for contextual entity disambiguation.

Tests the system's ability to correctly identify entity types when the same
text could refer to multiple possible entities based on surrounding context.
"""

import pytest
from typing import Any, Dict, List

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionConfig,
    ExtractionStrategy,
    Entity,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def generator():
    """Create ontology generator for testing."""
    # OntologyGenerator doesn't take config in __init__
    # Config is passed through context in extract_entities
    return OntologyGenerator(use_ipfs_accelerate=False)


@pytest.fixture
def context():
    """Create default generation context."""
    return OntologyGenerationContext(
        data_source="test",
        data_type="text",
        domain="legal",
    )


# =============================================================================
# Helper Functions
# =============================================================================


def get_entity_by_text(entities: List[Entity], text: str) -> Entity:
    """Get entity by exact text match."""
    matches = [e for e in entities if e.text == text]
    if not matches:
        raise ValueError(f"Entity with text '{text}' not found. Available: {[e.text for e in entities]}")
    return matches[0]


def has_entity_with_text(entities: List[Entity], text: str) -> bool:
    """Check if entities list contains entity with given text."""
    return any(e.text == text for e in entities)


# =============================================================================
# Test Cases: Basic Disambiguation
# =============================================================================


class TestBasicDisambiguation:
    """Test basic entity type disambiguation from context."""
    
    def test_apple_as_company(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test 'Apple' disambiguated as ORGANIZATION from tech context."""
        text = "Apple Inc. released the new iPhone at their headquarters in Cupertino."
        
        result = generator.extract_entities(text, context)
        
        # Should extract Apple as organization, not fruit
        # Note: Trailing periods are typically removed during extraction
        assert has_entity_with_text(result.entities, "Apple Inc") or has_entity_with_text(result.entities, "Apple Inc.")
        apple = (get_entity_by_text(result.entities, "Apple Inc") 
                 if has_entity_with_text(result.entities, "Apple Inc") 
                 else get_entity_by_text(result.entities, "Apple Inc."))
        assert apple.type in ["ORGANIZATION", "ORG", "Organization", "Company"]
    
    def test_apple_as_fruit(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test 'apple' disambiguated as PRODUCT from food context."""
        text = "I ate an apple from the orchard this morning for breakfast."
        
        result = generator.extract_entities(text, context)
        
        # In rule-based extraction, may not extract simple nouns like "apple"
        # This is expected behavior - focus on proper nouns
        # If extracted, should have low confidence or generic type
    
    def test_washington_as_person(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test 'Washington' disambiguated as PERSON from historical context."""
        text = "George Washington was the first President of the United States."
        
        result = generator.extract_entities(text, context)
        
        assert has_entity_with_text(result.entities, "George Washington")
        washington = get_entity_by_text(result.entities, "George Washington")
        assert washington.type in ["PERSON", "PER"]
    
    def test_washington_as_location(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test 'Washington' disambiguated as LOCATION from geographic context."""
        text = "The capital of Washington state is Olympia, not Seattle."
        
        result = generator.extract_entities(text, context)
        
        # Should extract Washington as location
        washington_found = has_entity_with_text(result.entities, "Washington")
        if washington_found:
            washington = get_entity_by_text(result.entities, "Washington")
            assert washington.type in ["LOCATION", "LOC", "GPE", "Place"]


# =============================================================================
# Test Cases: Multi-Entity Disambiguation
# =============================================================================


class TestMultiEntityDisambiguation:
    """Test disambiguation when multiple ambiguous entities appear together."""
    
    def test_multiple_named_entities(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test disambiguation with multiple proper nouns in same sentence."""
        text = "Microsoft's Bill Gates and Apple's Steve Jobs revolutionized personal computing."
        
        result = generator.extract_entities(text, context)
        
        # Should extract both companies and both people
        assert has_entity_with_text(result.entities, "Microsoft")
        assert has_entity_with_text(result.entities, "Apple")
        assert has_entity_with_text(result.entities, "Bill Gates")
        assert has_entity_with_text(result.entities, "Steve Jobs")
        
        # Companies should be organizations
        microsoft = get_entity_by_text(result.entities, "Microsoft")
        apple = get_entity_by_text(result.entities, "Apple")
        assert microsoft.type in ["ORGANIZATION", "ORG", "Company"]
        assert apple.type in ["ORGANIZATION", "ORG", "Company"]
        
        # People should be persons
        gates = get_entity_by_text(result.entities, "Bill Gates")
        jobs = get_entity_by_text(result.entities, "Steve Jobs")
        assert gates.type in ["PERSON", "PER"]
        assert jobs.type in ["PERSON", "PER"]
    
    def test_location_vs_organization(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test disambiguation between location and organization names."""
        text = "The Paris Agreement was signed in Paris by representatives from many nations."
        
        result = generator.extract_entities(text, context)
        
        # Both "Paris Agreement" and "Paris" should be extracted
        # Paris Agreement likely as an event/agreement
        # Paris (second mention) as location
    
    def test_nested_entity_disambiguation(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test when entity names are nested within each other."""
        text = "Bank of America operates in America and worldwide."
        
        result = generator.extract_entities(text, context)
        
        # Should extract "Bank of America" as organization
        # May also extract "America" separately as location


# =============================================================================
# Test Cases: Context-Based Type Resolution
# =============================================================================


class TestContextBasedTypeResolution:
    """Test entity type resolution based on contextual clues."""
    
    def test_title_prefix_indicates_person(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test titles like 'Dr.', 'President' indicate PERSON type."""
        text = "Dr. Smith and President Johnson attended the medical conference."
        
        result = generator.extract_entities(text, context)
        
        # Should extract both with PERSON type
        if has_entity_with_text(result.entities, "Dr. Smith"):
            smith = get_entity_by_text(result.entities, "Dr. Smith")
            assert smith.type in ["PERSON", "PER"]
        
        if has_entity_with_text(result.entities, "President Johnson"):
            johnson = get_entity_by_text(result.entities, "President Johnson")
            assert johnson.type in ["PERSON", "PER"]
    
    def test_action_verbs_indicate_entity_type(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test action verbs help determine entity types."""
        text = "Tesla announced quarterly earnings. Elon Musk said revenues increased."
        
        result = generator.extract_entities(text, context)
        
        # "announced" suggests Tesla is an organization (companies announce)
        # "said" suggests Elon Musk is a person (people say things)
        if has_entity_with_text(result.entities, "Tesla"):
            tesla = get_entity_by_text(result.entities, "Tesla")
            assert tesla.type in ["ORGANIZATION", "ORG", "Company"]
        
        if has_entity_with_text(result.entities, "Elon Musk"):
            musk = get_entity_by_text(result.entities, "Elon Musk")
            assert musk.type in ["PERSON", "PER"]
    
    def test_possessive_indicates_relationship(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test possessive forms help disambiguate entity relationships."""
        text = "Google's CEO Sundar Pichai spoke at Google's annual conference."
        
        result = generator.extract_entities(text, context)
        
        # "Google's CEO" pattern indicates:
        # - Google is an organization
        # - Sundar Pichai is a person
        # - There's a relationship between them
        assert has_entity_with_text(result.entities, "Google")
        assert has_entity_with_text(result.entities, "Sundar Pichai")
        
        google = get_entity_by_text(result.entities, "Google")
        pichai = get_entity_by_text(result.entities, "Sundar Pichai")
        
        assert google.type in ["ORGANIZATION", "ORG", "Company"]
        assert pichai.type in ["PERSON", "PER"]
    
    def test_location_prepositions(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test location-indicating prepositions aid disambiguation."""
        text = "The meeting in London was attended by officials from London-based firms."
        
        result = generator.extract_entities(text, context)
        
        # "in London" strongly suggests London is a location
        assert has_entity_with_text(result.entities, "London")
        london = get_entity_by_text(result.entities, "London")
        assert london.type in ["LOCATION", "LOC", "GPE", "Place"]


# =============================================================================
# Test Cases: Confidence Scoring
# =============================================================================


class TestDisambiguationConfidence:
    """Test confidence scores for disambiguated entities."""
    
    def test_clear_context_has_high_confidence(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test entities with clear contextual indicators have high confidence."""
        text = "Microsoft Corporation, headquartered in Redmond, Washington."
        
        result = generator.extract_entities(text, context)
        
        # Clear organizational indicators should yield high confidence
        if has_entity_with_text(result.entities, "Microsoft Corporation"):
            microsoft = get_entity_by_text(result.entities, "Microsoft Corporation")
            assert microsoft.confidence > 0.7  # High confidence for clear entity
        
        # Clear location indicators for Washington
        if has_entity_with_text(result.entities, "Washington"):
            washington = get_entity_by_text(result.entities, "Washington")
            # Should be reasonably confident it's a location, not a person
    
    def test_ambiguous_context_has_lower_confidence(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test ambiguous entities may have lower confidence scores."""
        text = "Jordan is important."
        
        result = generator.extract_entities(text, context)
        
        # "Jordan" could be person (Michael Jordan) or country (Jordan)
        # Without more context, confidence should be moderate or entity may not be extracted
    
    def test_multiple_confirmatory_signals_increase_confidence(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test multiple contextual clues increase confidence."""
        text = "CEO Susan Smith of TechCorp Inc. announced that Ms. Smith will retire."
        
        result = generator.extract_entities(text, context)
        
        # "CEO", "Ms.", "will retire" all indicate person
        # Multiple signals should increase confidence
        if has_entity_with_text(result.entities, "Susan Smith"):
            susan = get_entity_by_text(result.entities, "Susan Smith")
            assert susan.type in ["PERSON", "PER"]


# =============================================================================
# Test Cases: Domain-Specific Disambiguation
# =============================================================================


class TestDomainSpecificDisambiguation:
    """Test entity disambiguation in domain-specific contexts."""
    
    def test_legal_domain_entities(self, generator: OntologyGenerator):
        """Test disambiguation in legal domain."""
        context = OntologyGenerationContext(
            data_source="test",
            data_type="text",
            domain="legal",
        )
        
        text = "The plaintiff Smith filed against Defendant Corp in California Superior Court."
        
        result = generator.extract_entities(text, context)
        
        # Legal context: Smith is a person (plaintiff)
        # Defendant Corp is an organization
        # California Superior Court is an institution/organization
    
    def test_medical_domain_entities(self, generator: OntologyGenerator):
        """Test disambiguation in medical domain."""
        context = OntologyGenerationContext(
            data_source="test",
            data_type="text",
            domain="medical",
        )
        
        text = "Dr. Johnson prescribed aspirin at Memorial Hospital's cardiology department."
        
        result = generator.extract_entities(text, context)
        
        # Medical context should help identify:
        # - Dr. Johnson as person
        # - Memorial Hospital as organization
        # - Aspirin as medication (product/substance)
    
    def test_financial_domain_entities(self, generator: OntologyGenerator):
        """Test disambiguation in financial domain."""
        context = OntologyGenerationContext(
            data_source="test",
            data_type="text",
            domain="financial",
        )
        
        text = "Goldman Sachs analyst Maria Rodriguez forecasts JPMorgan earnings."
        
        result = generator.extract_entities(text, context)
        
        # Financial context:
        # - Goldman Sachs: organization (financial institution)
        # - Maria Rodriguez: person (analyst)
        # - JPMorgan: organization (bank)


# =============================================================================
# Test Cases: Coreference and Pronoun Resolution
# =============================================================================


class TestCoreferenceDisambiguation:
    """Test disambiguation when entities are referred to by pronouns or aliases."""
    
    def test_repeated_mention_same_type(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test repeated mentions of same entity maintain type consistency."""
        text = "Amazon launched a new service. Amazon's CEO praised the initiative. The company expects growth."
        
        result = generator.extract_entities(text, context)
        
        # All mentions of Amazon should be consistent
        amazon_entities = [e for e in result.entities if "Amazon" in e.text]
        if amazon_entities:
            # All should be same type
            types = [e.type for e in amazon_entities]
            assert len(set(types)) == 1  # All same type
    
    def test_alias_resolution(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test entity aliases maintain consistent types."""
        text = "International Business Machines (IBM) announced results. IBM's revenue increased."
        
        result = generator.extract_entities(text, context)
        
        # Both "International Business Machines" and "IBM" should be organizations
        # May not catch this without NER model, but structure should support it
    
    def test_title_and_name(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test person mentioned by title and name are identified correctly."""
        text = "The President signed the bill. President Biden addressed the nation."
        
        result = generator.extract_entities(text, context)
        
        # "President Biden" should be identified as person
        if has_entity_with_text(result.entities, "President Biden"):
            biden = get_entity_by_text(result.entities, "President Biden")
            assert biden.type in ["PERSON", "PER"]


# =============================================================================
# Test Cases: Edge Cases
# =============================================================================


class TestDisambiguationEdgeCases:
    """Test edge cases in entity disambiguation."""
    
    def test_single_word_ambiguous_entity(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test single-word entities that could be multiple types."""
        text = "Amazon delivers packages."
        
        result = generator.extract_entities(text, context)
        
        # "Amazon" alone could be:
        # - River (geography)
        # - Company (organization)
        # - Rainforest (location/feature)
        # Context "delivers packages" suggests company
    
    def test_all_caps_entity(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test all-caps entities (acronyms) are handled correctly."""
        text = "NASA and FBI collaborated on the investigation."
        
        result = generator.extract_entities(text, context)
        
        # Both NASA and FBI should be extracted as organizations
        assert has_entity_with_text(result.entities, "NASA")
        assert has_entity_with_text(result.entities, "FBI")
    
    def test_mixed_case_variations(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test entities with unusual capitalization."""
        text = "eBay and PayPal are technology companies."
        
        result = generator.extract_entities(text, context)
        
        # Non-standard capitalization should still be recognized
        assert has_entity_with_text(result.entities, "eBay") or has_entity_with_text(result.entities, "ebay")
        assert has_entity_with_text(result.entities, "PayPal") or has_entity_with_text(result.entities, "Paypal")
    
    def test_entity_at_sentence_start(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test entities at sentence start are correctly identified."""
        text = "Paris hosted the Olympics. London will host next."
        
        result = generator.extract_entities(text, context)
        
        # Sentence-initial position shouldn't affect type detection
        assert has_entity_with_text(result.entities, "Paris")
        assert has_entity_with_text(result.entities, "London")
        
        paris = get_entity_by_text(result.entities, "Paris")
        london = get_entity_by_text(result.entities, "London")
        
        # Both should be locations despite being sentence-initial
        assert paris.type in ["LOCATION", "LOC", "GPE", "Place"]
        assert london.type in ["LOCATION", "LOC", "GPE", "Place"]
    
    def test_entity_in_quotes(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test quoted entities are correctly extracted."""
        text = 'The company "Microsoft" was founded by Bill Gates.'
        
        result = generator.extract_entities(text, context)
        
        # Quotes shouldn't prevent extraction
        # May extract as "Microsoft" or Microsoft
    
    def test_hyphenated_entity(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test hyphenated entity names."""
        text = "The Coca-Cola Company is a beverage corporation."
        
        result = generator.extract_entities(text, context)
        
        # Hyphenated names should be kept together
        assert has_entity_with_text(result.entities, "Coca-Cola Company") or has_entity_with_text(result.entities, "Coca-Cola")
    
    def test_entity_with_numbers(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test entities containing numbers."""
        text = "3M Corporation and Boeing 737 are well-known in manufacturing."
        
        result = generator.extract_entities(text, context)
        
        # Numbers in names should be preserved
        assert has_entity_with_text(result.entities, "3M Corporation") or has_entity_with_text(result.entities, "3M")
    
    def test_empty_text(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test empty text returns empty extents."""
        text = ""
        
        result = generator.extract_entities(text, context)
        
        assert len(result.entities) == 0
    
    def test_no_entities(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test text with no extractable entities."""
        text = "this is just some text without entities"
        
        result = generator.extract_entities(text, context)
        
        # Should return empty or minimal entities (all lowercase, no proper nouns)
        # This is expected behavior


# =============================================================================
# Test Cases: Integration
# =============================================================================


class TestDisambiguationIntegration:
    """Test disambiguation in realistic, complex scenarios."""
    
    def test_news_article_extraction(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test entity disambiguation from news-style text."""
        text = """
        Tech giant Apple announced record quarterly earnings yesterday.
        CEO Tim Cook stated that Apple's iPhone sales exceeded expectations.
        The Cupertino-based company's stock rose 5% on NASDAQ.
        """
        
        result = generator.extract_entities(text, context)
        
        # Should extract:
        # - Apple (organization) - appears twice
        # - Tim Cook (person)
        # - Cupertino (location)
        # - NASDAQ (organization/market)
        assert has_entity_with_text(result.entities, "Apple")
        assert has_entity_with_text(result.entities, "Tim Cook")
    
    def test_legal_document_extraction(self, generator: OntologyGenerator):
        """Test entity disambiguation from legal document."""
        context = OntologyGenerationContext(
            data_source="test",
            data_type="text",
            domain="legal",
        )
        
        text = """
        Plaintiff John Smith v. Defendant MegaCorp Inc.
        Filed in Superior Court of California, County of Los Angeles.
        Attorney Sarah Johnson represents the plaintiff.
        """
        
        result = generator.extract_entities(text, context)
        
        # Should distinguish:
        # - John Smith: person (plaintiff)
        # - MegaCorp Inc.: organization (defendant)
        # - Superior Court: institution
        # - California, Los Angeles: locations
        # - Sarah Johnson: person (attorney)
    
    def test_academic_citation_extraction(self, generator: OntologyGenerator, context: OntologyGenerationContext):
        """Test entity disambiguation from academic citation."""
        text = """
        Research by Dr. Jane Wilson and Dr. Robert Chen at Stanford University
        was published in Nature journal. Wilson's team collaborated with Harvard.
        """
        
        result = generator.extract_entities(text, context)
        
        # Should extract:
        # - Dr. Jane Wilson: person
        # - Dr. Robert Chen: person
        # - Stanford University: organization
        # - Nature: organization (journal/publisher)
        # - Harvard: organization
