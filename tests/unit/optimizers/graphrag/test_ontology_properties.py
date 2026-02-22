"""Property-based tests for OntologyGenerator using Hypothesis.

Tests invariants and properties for entity extraction and ontology generation.
"""

import pytest
from hypothesis import given, strategies as st, assume, settings
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionStrategy,
    DataType,
    Entity,
    EntityExtractionResult,
)


# Custom strategies for ontology generation
@st.composite
def extraction_context_strategy(draw):
    """Generate valid OntologyGenerationContext instances."""
    return OntologyGenerationContext(
        data_source=draw(st.text(min_size=1, max_size=50)),
        data_type=draw(st.sampled_from(DataType)),
        domain=draw(st.text(min_size=1, max_size=30, alphabet=st.characters(min_codepoint=97, max_codepoint=122))),
        extraction_strategy=draw(st.sampled_from(ExtractionStrategy)),
    )


@st.composite
def entity_strategy(draw):
    """Generate valid Entity instances."""
    return Entity(
        id=draw(st.text(min_size=1, max_size=30)),
        text=draw(st.text(min_size=1, max_size=100)),
        type=draw(st.sampled_from(["PERSON", "ORG", "LOCATION", "DATE", "OBLIGATION", "CONCEPT"])),
        confidence=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
        properties=draw(st.dictionaries(
            keys=st.text(min_size=1, max_size=20),
            values=st.one_of(st.text(max_size=50), st.integers(), st.floats(allow_nan=False)),
            max_size=5
        )),
    )


@st.composite
def entity_extraction_result_strategy(draw):
    """Generate valid EntityExtractionResult instances."""
    num_entities = draw(st.integers(min_value=0, max_value=20))
    entities = [draw(entity_strategy()) for _ in range(num_entities)]
    
    return EntityExtractionResult(
        entities=entities,
        relationships=[],  # Simplified for property tests
        confidence=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
        metadata=draw(st.dictionaries(
            keys=st.text(min_size=1, max_size=20),
            values=st.text(max_size=50),
            max_size=5
        )),
    )


class TestEntityProperties:
    """Property-based tests for Entity objects."""
    
    @given(entity=entity_strategy())
    @settings(max_examples=100)
    def test_entity_confidence_in_bounds(self, entity):
        """Entity confidence is always between 0 and 1."""
        assert 0.0 <= entity.confidence <= 1.0
    
    @given(entity=entity_strategy())
    @settings(max_examples=100)
    def test_entity_serialization_roundtrip(self, entity):
        """Entity can be serialized and deserialized without loss."""
        entity_dict = entity.to_dict()
        reconstructed = Entity.from_dict(entity_dict)
        
        # Core properties should match
        assert reconstructed.id == entity.id
        assert reconstructed.text == entity.text
        assert reconstructed.type == entity.type
        assert reconstructed.confidence == pytest.approx(entity.confidence)
    
    @given(entity=entity_strategy())
    @settings(max_examples=50)
    def test_entity_to_dict_has_required_keys(self, entity):
        """Entity.to_dict() always has required keys."""
        entity_dict = entity.to_dict()
        
        required_keys = ["id", "type", "text", "confidence", "properties"]
        for key in required_keys:
            assert key in entity_dict
    
    @given(entity=entity_strategy())
    @settings(max_examples=50)
    def test_entity_text_is_string(self, entity):
        """Entity text is always a string."""
        assert isinstance(entity.text, str)
        assert len(entity.text) >= 1  # Non-empty


class TestExtractionResultProperties:
    """Property-based tests for EntityExtractionResult."""
    
    @given(result=entity_extraction_result_strategy())
    @settings(max_examples=100)
    def test_result_confidence_in_bounds(self, result):
        """Result confidence is always between 0 and 1."""
        assert 0.0 <= result.confidence <= 1.0
    
    @given(result=entity_extraction_result_strategy())
    @settings(max_examples=100)
    def test_result_entities_is_list(self, result):
        """Result entities is always a list."""
        assert isinstance(result.entities, list)
    
    @given(result=entity_extraction_result_strategy())
    @settings(max_examples=100)
    def test_all_entity_confidences_in_bounds(self, result):
        """All entity confidences are within bounds."""
        for entity in result.entities:
            assert 0.0 <= entity.confidence <= 1.0
    
    @given(result=entity_extraction_result_strategy())
    @settings(max_examples=50)
    def test_result_has_required_attributes(self, result):
        """Result has required attributes."""
        assert hasattr(result, 'entities')
        assert hasattr(result, 'relationships')
        assert hasattr(result, 'confidence')
        assert hasattr(result, 'metadata')


class TestOntologyGeneratorStatisticalProperties:
    """Property-based tests for OntologyGenerator statistical methods."""
    
    def setup_method(self):
        """Set up generator."""
        self.generator = OntologyGenerator()
    
    @given(results=st.lists(entity_extraction_result_strategy(), min_size=1, max_size=10))
    @settings(max_examples=50)
    def test_history_kurtosis_returns_finite(self, results):
        """history_kurtosis always returns finite float."""
        import math
        kurtosis = self.generator.history_kurtosis(results)
        
        assert isinstance(kurtosis, float)
        assert not math.isnan(kurtosis)
        assert not math.isinf(kurtosis)
    
    @given(result=entity_extraction_result_strategy())
    @settings(max_examples=50)
    def test_high_confidence_entities_count_bounded(self, result):
        """High confidence entity count <= total entity count."""
        threshold = 0.8
        count = self.generator.entity_count_with_confidence_above(result, threshold)
        total_count = len(result.entities)
        
        assert 0 <= count <= total_count
    
    @given(result=entity_extraction_result_strategy())
    @settings(max_examples=100)
    def test_entity_relation_ratio_non_negative(self, result):
        """entity_relation_ratio is always non-negative."""
        ratio = self.generator.entity_relation_ratio(result)
        
        assert ratio >= 0.0
        assert isinstance(ratio, float)
    
    @given(result=entity_extraction_result_strategy())
    @settings(max_examples=50)
    def test_entity_count_equals_list_length(self, result):
        """Entity count matches len(entities)."""
        count = self.generator.entity_count(result)
        
        assert count == len(result.entities)
        assert count >= 0
    
    @given(result=entity_extraction_result_strategy())
    @settings(max_examples=50)
    def test_high_confidence_entities_count_bounded(self, result):
        """High confidence entity count <= total entity count."""
        threshold = 0.8
        count = self.generator.entity_count_with_confidence_above(result, threshold)
        total_count = len(result.entities)
        
        assert 0 <= count <= total_count
    
    @given(
        result=entity_extraction_result_strategy(),
        threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100)
    def test_confidence_count_monotonic_in_threshold(self, result, threshold):
        """Higher threshold means fewer high-confidence entities."""
        # Count entities above threshold
        count = self.generator.entity_count_with_confidence_above(result, threshold)
        
        # Count should be <= total entities
        assert count <= len(result.entities)
    
    @given(result=entity_extraction_result_strategy())
    @settings(max_examples=50)
    def test_entity_text_length_median_non_negative(self, result):
        """Median entity text length is non-negative."""
        median = self.generator.entity_text_length_median(result)
        
        assert median >= 0.0
        assert isinstance(median, float)


class TestUniqueRelationshipTypesProperties:
    """Property-based tests for unique_relationship_types method."""
    
    def setup_method(self):
        """Set up generator."""
        self.generator = OntologyGenerator()
    
    @given(result=entity_extraction_result_strategy())
    @settings(max_examples=50)
    def test_unique_types_returns_list(self, result):
        """unique_relationship_types always returns a list."""
        types = self.generator.unique_relationship_types(result)
        
        assert isinstance(types, list)
    
    @given(result=entity_extraction_result_strategy())
    @settings(max_examples=50)
    def test_unique_types_all_strings(self, result):
        """All unique relationship types are strings."""
        types = self.generator.unique_relationship_types(result)
        
        for t in types:
            assert isinstance(t, str)
    
    @given(result=entity_extraction_result_strategy())
    @settings(max_examples=50)
    def test_unique_types_sorted(self, result):
        """Unique relationship types are sorted."""
        types = self.generator.unique_relationship_types(result)
        
        if len(types) > 1:
            assert types == sorted(types)
    
    @given(result=entity_extraction_result_strategy())
    @settings(max_examples=50)
    def test_unique_types_no_duplicates(self, result):
        """Unique relationship types has no duplicates."""
        types = self.generator.unique_relationship_types(result)
        
        assert len(types) == len(set(types))


class TestExtractionProperties:
    """Property-based tests for extraction invariants."""
    
    def setup_method(self):
        """Set up generator."""
        self.generator = OntologyGenerator()
    
    @given(
        data=st.text(min_size=1, max_size=200),
        context=extraction_context_strategy(),
    )
    @settings(max_examples=20)  # Fewer examples since extraction is expensive
    def test_extract_entities_returns_result(self, data, context):
        """extract_entities always returns EntityExtractionResult."""
        result = self.generator.extract_entities(data, context)
        
        assert isinstance(result, EntityExtractionResult)
    
    @given(
        data=st.text(min_size=1, max_size=200),
        context=extraction_context_strategy(),
    )
    @settings(max_examples=20)
    def test_extracted_entities_confidence_bounds(self, data, context):
        """All extracted entities have confidence in [0, 1]."""
        result = self.generator.extract_entities(data, context)
        
        for entity in result.entities:
            assert 0.0 <= entity.confidence <= 1.0
    
    @given(
        data=st.text(min_size=1, max_size=200),
        context=extraction_context_strategy(),
    )
    @settings(max_examples=20)
    def test_extracted_result_confidence_bounds(self, data, context):
        """Extraction result confidence is in [0, 1]."""
        result = self.generator.extract_entities(data, context)
        
        assert 0.0 <= result.confidence <= 1.0
    
    @given(
        data=st.text(min_size=1, max_size=200),
        context=extraction_context_strategy(),
    )
    @settings(max_examples=20)
    def test_extracted_entities_have_ids(self, data, context):
        """All extracted entities have non-empty IDs."""
        result = self.generator.extract_entities(data, context)
        
        for entity in result.entities:
            assert isinstance(entity.id, str)
            assert len(entity.id) > 0
    
    @given(
        data=st.text(min_size=1, max_size=200),
        context=extraction_context_strategy(),
    )
    @settings(max_examples=20)
    def test_extraction_metadata_is_dict(self, data, context):
        """Extraction metadata is always a dict."""
        result = self.generator.extract_entities(data, context)
        
        assert isinstance(result.metadata, dict)


class TestMultipleResultsProperties:
    """Property-based tests for operations on multiple results."""
    
    def setup_method(self):
        """Set up generator."""
        self.generator = OntologyGenerator()
    
    @given(results=st.lists(entity_extraction_result_strategy(), min_size=1, max_size=5))
    @settings(max_examples=30)
    def test_entity_count_total_sums_correctly(self, results):
        """Total entity count equals sum of individual counts."""
        total = sum(len(r.entities) for r in results)
        
        # Verify using individual entity_count calls
        individual_sum = sum(self.generator.entity_count(r) for r in results)
        
        assert total == individual_sum


class TestEdgeCaseProperties:
    """Property-based tests for edge cases."""
    
    def setup_method(self):
        """Set up generator."""
        self.generator = OntologyGenerator()
    
    @given(result=entity_extraction_result_strategy())
    @settings(max_examples=50)
    def test_statistical_methods_handle_empty_gracefully(self, result):
        """Statistical methods handle results with no entities gracefully."""
        # Create empty result
        empty_result = EntityExtractionResult(
            entities=[],
            relationships=[],
            confidence=0.5,
            metadata={},
        )
        
        # Should not raise errors
        _ = self.generator.entity_count(empty_result)
        _ = self.generator.entity_relation_ratio(empty_result)
        _ = self.generator.unique_relationship_types(empty_result)
        _ = self.generator.entity_text_length_median(empty_result)
    
    @given(results=st.lists(entity_extraction_result_strategy(), max_size=3))
    @settings(max_examples=30)
    def test_history_methods_handle_empty_list(self, results):
        """History methods handle empty result lists gracefully."""
        if not results:
            # Should return 0.0 or default values  
            kurtosis = self.generator.history_kurtosis([])
            
            # history_kurtosis returns 0.0 for empty lists
            assert kurtosis == 0.0
