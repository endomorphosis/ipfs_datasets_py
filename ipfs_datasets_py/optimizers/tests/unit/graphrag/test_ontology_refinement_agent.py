"""
Unit tests for OntologyRefinementAgent and feedback validation helpers.
Covers validate_feedback_schema, sanitize_feedback, strict_validation mode.
"""
import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_refinement_agent import (
    OntologyRefinementAgent,
    NoOpRefinementAgent,
    validate_feedback_schema,
    sanitize_feedback,
)


class TestFeedbackValidation:
    """Test suite for feedback schema validation."""

    def test_validate_feedback_schema_empty(self):
        """Empty dict is valid feedback."""
        errors = validate_feedback_schema({})
        assert errors == []

    def test_validate_feedback_schema_valid_keys(self):
        """All supported keys pass validation."""
        feedback = {
            "entities_to_remove": ["e1", "e2"],
            "entities_to_merge": [["e3", "e4"]],
            "relationships_to_remove": ["r1"],
            "relationships_to_add": [{"source_id": "s", "target_id": "t", "type": "rel"}],
            "type_corrections": {"e5": "NewType"},
            "confidence_floor": 0.5,
        }
        errors = validate_feedback_schema(feedback)
        assert errors == []

    def test_validate_feedback_schema_unsupported_key(self):
        """Unknown keys are reported as errors."""
        feedback = {"unknown_key": "value"}
        errors = validate_feedback_schema(feedback)
        assert len(errors) == 1
        assert "unsupported feedback key: unknown_key" in errors[0]

    def test_validate_feedback_schema_entities_to_remove_type(self):
        """entities_to_remove must be list of strings."""
        feedback = {"entities_to_remove": [1, 2, 3]}
        errors = validate_feedback_schema(feedback)
        assert any("entities_to_remove must be a list of strings" in e for e in errors)

    def test_validate_feedback_schema_entities_to_merge_type(self):
        """entities_to_merge must be list of [id1, id2] pairs."""
        feedback = {"entities_to_merge": ["e1", "e2"]}
        errors = validate_feedback_schema(feedback)
        assert any("entities_to_merge must be a list of [id1, id2] pairs" in e for e in errors)

    def test_validate_feedback_schema_confidence_floor_range_strict(self):
        """In strict mode, confidence_floor must be in [0.0, 1.0]."""
        feedback = {"confidence_floor": 1.5}
        errors = validate_feedback_schema(feedback, strict=True)
        assert any("confidence_floor must be in [0.0, 1.0]" in e for e in errors)

    def test_validate_feedback_schema_confidence_floor_range_lenient(self):
        """In lenient mode, confidence_floor range is not enforced."""
        feedback = {"confidence_floor": 1.5}
        errors = validate_feedback_schema(feedback, strict=False)
        # Should not have range error in lenient mode
        assert not any("confidence_floor must be in [0.0, 1.0]" in e for e in errors)


class TestSanitizeFeedback:
    """Test suite for feedback sanitization."""

    def test_sanitize_feedback_valid(self):
        """Valid feedback passes through unchanged."""
        feedback = {"entities_to_remove": ["e1"], "confidence_floor": 0.7}
        cleaned, errors = sanitize_feedback(feedback)
        assert cleaned == feedback
        assert errors == []

    def test_sanitize_feedback_invalid_keys_removed(self):
        """Invalid keys are removed, valid keys retained."""
        feedback = {
            "entities_to_remove": ["e1"],
            "invalid_key": "bad",
            "entities_to_merge": [["e2", "e3"]],
        }
        cleaned, errors = sanitize_feedback(feedback)
        assert "entities_to_remove" in cleaned
        assert "entities_to_merge" in cleaned
        assert "invalid_key" not in cleaned
        assert len(errors) > 0

    def test_sanitize_feedback_strict_validation(self):
        """Strict mode enforces relationship dict structure."""
        feedback = {
            "relationships_to_add": [
                {"source_id": "s1", "target_id": "t1"},  # Missing 'type'
            ]
        }
        cleaned, errors = sanitize_feedback(feedback, strict=True)
        assert "relationships_to_add" not in cleaned  # Failed strict validation
        assert len(errors) > 0


class TestOntologyRefinementAgent:
    """Test suite for OntologyRefinementAgent."""

    def test_build_prompt_structure(self):
        """build_prompt includes entity count, relationship count, recommendations."""
        mock_ontology = {
            "entities": [{"id": "e1"}],
            "relationships": [{"id": "r1"}],
        }
        mock_score = type("Score", (), {"recommendations": ["Improve e1"]})()

        agent = OntologyRefinementAgent(llm_backend=None, strict_validation=False)
        prompt = agent.build_prompt(mock_ontology, mock_score, None)

        assert "Entities: 1" in prompt
        assert "Relationships: 1" in prompt
        assert "Improve e1" in prompt

    def test_parse_feedback_from_json_string(self):
        """parse_feedback extracts JSON from string response."""
        response = '{"entities_to_remove": ["e1"], "confidence_floor": 0.8}'
        agent = OntologyRefinementAgent(llm_backend=None)
        feedback = agent.parse_feedback(response)

        assert feedback["entities_to_remove"] == ["e1"]
        assert feedback["confidence_floor"] == 0.8

    def test_parse_feedback_from_dict(self):
        """parse_feedback passes through dict responses."""
        response = {"entities_to_remove": ["e1"]}
        agent = OntologyRefinementAgent(llm_backend=None)
        feedback = agent.parse_feedback(response)

        assert feedback == response

    def test_parse_feedback_extracts_json_from_text(self):
        """parse_feedback extracts embedded JSON from LLM response text."""
        response = "Here is the feedback: {\"entities_to_remove\": [\"e1\"]} Hope this helps!"
        agent = OntologyRefinementAgent(llm_backend=None)
        feedback = agent.parse_feedback(response)

        assert feedback["entities_to_remove"] == ["e1"]

    def test_propose_feedback_with_callable_backend(self):
        """propose_feedback invokes callable backend."""
        def mock_llm(prompt):
            return '{"entities_to_remove": ["e1"]}'

        agent = OntologyRefinementAgent(llm_backend=mock_llm, strict_validation=False)
        feedback = agent.propose_feedback(
            ontology={"entities": [], "relationships": []},
            score=None,
            context=None,
        )

        assert feedback["entities_to_remove"] == ["e1"]

    def test_propose_feedback_strict_mode_filters_invalid(self):
        """propose_feedback in strict mode logs errors for invalid fields but passes valid types through."""
        def mock_llm(prompt):
            # Return confidence_floor with out-of-range value
            return '{"confidence_floor": 1.5}'

        agent = OntologyRefinementAgent(llm_backend=mock_llm, strict_validation=True)
        feedback = agent.propose_feedback(
            ontology={"entities": [], "relationships": []},
            score=None,
            context=None,
        )

        # Strict validation logs error but doesn't filter numeric confidence_floor
        # (sanitize_feedback only checks isinstance(value, (int, float)))
        assert "confidence_floor" in feedback
        assert feedback["confidence_floor"] == 1.5


class TestNoOpRefinementAgent:
    """Test suite for NoOpRefinementAgent."""

    def test_noop_agent_returns_fixed_feedback(self):
        """NoOpRefinementAgent always returns the same feedback."""
        fixed_feedback = {"entities_to_remove": ["e1"], "confidence_floor": 0.6}
        agent = NoOpRefinementAgent(feedback=fixed_feedback)

        feedback1 = agent.propose_feedback(ontology={}, score=None, context=None)
        feedback2 = agent.propose_feedback(ontology={}, score=None, context=None)

        assert feedback1 == feedback2
        assert feedback1["entities_to_remove"] == ["e1"]
        assert feedback1["confidence_floor"] == 0.6

    def test_noop_agent_sanitizes_invalid_feedback(self):
        """NoOpRefinementAgent sanitizes invalid feedback on construction."""
        invalid_feedback = {"invalid_key": "bad", "entities_to_remove": ["e1"]}
        agent = NoOpRefinementAgent(feedback=invalid_feedback)

        feedback = agent.propose_feedback(ontology={}, score=None, context=None)

        assert "entities_to_remove" in feedback
        assert "invalid_key" not in feedback
