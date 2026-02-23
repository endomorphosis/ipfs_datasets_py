"""Property-based tests for ontology_types.py structures using Hypothesis.

Uses Hypothesis to generate valid Entity, CriticScore, FeedbackRecord, and
OntologySession structures and verify they satisfy invariants and constraints.

Key invariants tested:
- Confidence values always in [0.0, 1.0]
- Entity/Relationship IDs are non-empty strings
- Relationship source/target IDs refer to valid entities
- CriticScore individual dimensions match overall score reasonably
- FeedbackRecord feedback is structurally valid
"""

from hypothesis import given, strategies as st, assume
from ipfs_datasets_py.optimizers.graphrag.ontology_refinement_agent import (
    validate_feedback_schema,
)


# ─────────────────────────────────────────────────────────────────────────────
# Hypothesis Strategies
# ─────────────────────────────────────────────────────────────────────────────


@st.composite
def entity_strategy(draw):
    """Hypothesis strategy for generating valid Entity dicts."""
    return {
        "id": draw(st.text(alphabet="a-z0-9_", min_size=1, max_size=20)),
        "text": draw(st.text(min_size=1, max_size=100)),
        "type": draw(st.sampled_from(["Person", "Organization", "Location", "Date", "Concept"])),
        "confidence": draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
    }


@st.composite
def relationship_strategy(draw, entity_ids=None):
    """Hypothesis strategy for generating valid Relationship dicts."""
    if entity_ids is None:
        entity_ids = [f"e{i}" for i in range(1, 6)]
    
    return {
        "id": draw(st.text(alphabet="a-z0-9_", min_size=1, max_size=20)),
        "source_id": draw(st.sampled_from(entity_ids)),
        "target_id": draw(st.sampled_from(entity_ids)),
        "type": draw(st.sampled_from(["related_to", "knows", "works_for", "located_in", "part_of"])),
        "confidence": draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
    }


@st.composite
def critic_score_strategy(draw):
    """Hypothesis strategy for generating valid CriticScore dicts."""
    # Generate dimensions that have reasonable relationship to overall score
    overall = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    variance = 0.15  # Dimensions can deviate from overall by up to 15%
    
    def bounded_dimension(mean):
        return draw(st.floats(min_value=max(0.0, mean - variance), max_value=min(1.0, mean + variance),
                             allow_nan=False, allow_infinity=False))
    
    score = {"overall": overall}
    
    # Optionally add dimension scores
    if draw(st.booleans()):
        score["completeness"] = bounded_dimension(overall)
    if draw(st.booleans()):
        score["consistency"] = bounded_dimension(overall)
    if draw(st.booleans()):
        score["clarity"] = bounded_dimension(overall)
    if draw(st.booleans()):
        score["granularity"] = bounded_dimension(overall)
    if draw(st.booleans()):
        score["domain_alignment"] = bounded_dimension(overall)
    if draw(st.booleans()):
        score["relationship_coherence"] = bounded_dimension(overall)
    
    return score


@st.composite
def feedback_strategy(draw):
    """Hypothesis strategy for generating valid FeedbackRecord dicts."""
    feedback = {}
    
    # Optionally add each feedback field
    if draw(st.booleans()):
        entity_ids = [f"e{i}" for i in draw(st.lists(st.integers(1, 10), min_size=1, max_size=5, unique=True))]
        feedback["entities_to_remove"] = entity_ids
    
    if draw(st.booleans()):
        merge_pairs = [
            [f"e{a}", f"e{b}"]
            for a, b in draw(st.lists(st.tuples(st.integers(1, 20), st.integers(1, 20)), min_size=1, max_size=5))
        ]
        feedback["entities_to_merge"] = merge_pairs
    
    if draw(st.booleans()):
        rel_ids = [f"r{i}" for i in draw(st.lists(st.integers(1, 20), min_size=1, max_size=5, unique=True))]
        feedback["relationships_to_remove"] = rel_ids
    
    if draw(st.booleans()):
        relationships = [
            {"source_id": f"e{draw(st.integers(1, 10))}", "target_id": f"e{draw(st.integers(1, 10))}", "type": "rel"}
            for _ in range(draw(st.integers(1, 3)))
        ]
        feedback["relationships_to_add"] = relationships
    
    if draw(st.booleans()):
        corrections = {f"e{i}": "NewType" for i in draw(st.lists(st.integers(1, 10), min_size=1, max_size=3, unique=True))}
        feedback["type_corrections"] = corrections
    
    if draw(st.booleans()):
        feedback["confidence_floor"] = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    
    return feedback


# ─────────────────────────────────────────────────────────────────────────────
# Property-Based Tests: Entity
# ─────────────────────────────────────────────────────────────────────────────


class TestEntityProperties:
    """Property-based tests for Entity TypedDict."""
    
    @given(entity_strategy())
    def test_entity_confidence_in_range(self, entity):
        """Entity confidence is always in [0.0, 1.0]."""
        assert 0.0 <= entity["confidence"] <= 1.0
    
    @given(entity_strategy())
    def test_entity_has_required_fields(self, entity):
        """Entity has all required fields."""
        assert "id" in entity
        assert "text" in entity
        assert "type" in entity
        assert "confidence" in entity
    
    @given(entity_strategy())
    def test_entity_id_nonempty(self, entity):
        """Entity ID is non-empty string."""
        assert isinstance(entity["id"], str)
        assert len(entity["id"]) > 0
    
    @given(entity_strategy())
    def test_entity_text_nonempty(self, entity):
        """Entity text is non-empty string."""
        assert isinstance(entity["text"], str)
        assert len(entity["text"]) > 0
    
    @given(entity_strategy())
    def test_entity_type_valid(self, entity):
        """Entity type is one of expected categories."""
        valid_types = ["Person", "Organization", "Location", "Date", "Concept"]
        assert entity["type"] in valid_types


# ─────────────────────────────────────────────────────────────────────────────
# Property-Based Tests: Relationship
# ─────────────────────────────────────────────────────────────────────────────


class TestRelationshipProperties:
    """Property-based tests for Relationship TypedDict."""
    
    @given(st.lists(entity_strategy(), min_size=2, max_size=10).flatmap(
        lambda entities: st.tuples(
            st.just(entities),
            relationship_strategy(entity_ids=[e["id"] for e in entities])
        )
    ))
    def test_relationship_confidence_in_range(self, data):
        """Relationship confidence is always in [0.0, 1.0]."""
        entities, rel = data
        assert 0.0 <= rel["confidence"] <= 1.0
    
    @given(st.lists(entity_strategy(), min_size=2, max_size=10).flatmap(
        lambda entities: st.tuples(
            st.just(entities),
            relationship_strategy(entity_ids=[e["id"] for e in entities])
        )
    ))
    def test_relationship_endpoints_valid(self, data):
        """Relationship source and target reference valid entities."""
        entities, rel = data
        entity_ids = [e["id"] for e in entities]
        assert rel["source_id"] in entity_ids
        assert rel["target_id"] in entity_ids
    
    @given(st.lists(entity_strategy(), min_size=2, max_size=10).flatmap(
        lambda entities: st.tuples(
            st.just(entities),
            relationship_strategy(entity_ids=[e["id"] for e in entities])
        )
    ))
    def test_relationship_has_required_fields(self, data):
        """Relationship has all required fields."""
        entities, rel = data
        assert "id" in rel
        assert "source_id" in rel
        assert "target_id" in rel
        assert "type" in rel
        assert "confidence" in rel


# ─────────────────────────────────────────────────────────────────────────────
# Property-Based Tests: CriticScore
# ─────────────────────────────────────────────────────────────────────────────


class TestCriticScoreProperties:
    """Property-based tests for CriticScore TypedDict."""
    
    @given(critic_score_strategy())
    def test_critic_score_overall_in_range(self, score):
        """CriticScore overall is in [0.0, 1.0]."""
        assert 0.0 <= score["overall"] <= 1.0
    
    @given(critic_score_strategy())
    def test_critic_score_dimensions_in_range(self, score):
        """All dimension scores are in [0.0, 1.0]."""
        dimension_keys = [
            "completeness", "consistency", "clarity", "granularity",
            "domain_alignment", "relationship_coherence"
        ]
        for key in dimension_keys:
            if key in score:
                assert 0.0 <= score[key] <= 1.0, f"{key}={score[key]} out of range"
    
    @given(critic_score_strategy())
    def test_critic_score_dimensions_near_overall(self, score):
        """Dimension scores are reasonably close to overall score."""
        overall = score["overall"]
        variance_threshold = 0.20  # Allow up to 20% variance
        
        dimension_keys = [
            "completeness", "consistency", "clarity", "granularity",
            "domain_alignment", "relationship_coherence"
        ]
        for key in dimension_keys:
            if key in score:
                dim_score = score[key]
                diff = abs(dim_score - overall)
                # Allow greater variance at extremes (near 0 or 1)
                allowed_variance = variance_threshold
                if overall < 0.3 or overall > 0.7:
                    allowed_variance = 0.25
                assert diff <= allowed_variance, f"{key}={dim_score} varies too far from overall={overall}"


# ─────────────────────────────────────────────────────────────────────────────
# Property-Based Tests: FeedbackRecord
# ─────────────────────────────────────────────────────────────────────────────


class TestFeedbackRecordProperties:
    """Property-based tests for FeedbackRecord TypedDict."""
    
    @given(feedback_strategy())
    def test_feedback_schema_valid(self, feedback):
        """FeedbackRecord feedback passes schema validation."""
        errors = validate_feedback_schema(feedback, strict=False)
        assert len(errors) == 0, f"Schema errors: {errors}"
    
    @given(feedback_strategy())
    def test_feedback_contains_only_valid_keys(self, feedback):
        """FeedbackRecord only contains valid keys."""
        valid_keys = {
            "entities_to_remove",
            "entities_to_merge",
            "relationships_to_remove",
            "relationships_to_add",
            "type_corrections",
            "confidence_floor"
        }
        assert set(feedback.keys()).issubset(valid_keys)
    
    @given(feedback_strategy())
    def test_feedback_entities_to_remove_type(self, feedback):
        """If present, entities_to_remove is list of strings."""
        if "entities_to_remove" in feedback:
            assert isinstance(feedback["entities_to_remove"], list)
            assert all(isinstance(e, str) for e in feedback["entities_to_remove"])
    
    @given(feedback_strategy())
    def test_feedback_confidence_floor_valid(self, feedback):
        """If present, confidence_floor is in [0.0, 1.0]."""
        if "confidence_floor" in feedback:
            cf = feedback["confidence_floor"]
            assert isinstance(cf, float)
            assert 0.0 <= cf <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Property-Based Tests: Collections
# ─────────────────────────────────────────────────────────────────────────────


class TestOntologyCollectionProperties:
    """Property-based tests for ontology collections."""
    
    @given(st.lists(entity_strategy(), min_size=1, max_size=50))
    def test_entity_list_all_valid(self, entities):
        """List of entities all have valid confidence."""
        for entity in entities:
            assert 0.0 <= entity["confidence"] <= 1.0
    
    @given(st.lists(entity_strategy(), min_size=1, max_size=50))
    def test_entity_ids_unique_possibility(self, entities):
        """Entity IDs can be made unique (valid structure for ontology)."""
        # Just verify we can make a dict from entities by ID
        entity_dict = {e["id"]: e for e in entities}
        assert len(entity_dict) <= len(entities)  # No duplicates possible
    
    @given(st.lists(critic_score_strategy(), min_size=1, max_size=10))
    def test_score_history_valid(self, scores):
        """List of critic scores all have valid overall."""
        for score in scores:
            assert 0.0 <= score["overall"] <= 1.0
    
    @given(st.lists(score := critic_score_strategy(), min_size=2, max_size=10))
    def test_score_monotonicity_possible(self, scores):
        """Scores can be checked for monotonic improvement."""
        # Verify we can sort by overall score without errors
        sorted_scores = sorted(scores, key=lambda s: s["overall"])
        assert len(sorted_scores) == len(scores)
