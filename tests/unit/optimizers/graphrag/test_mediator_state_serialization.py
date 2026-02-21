"""
Tests for MediatorState serialization round-trip (to_dict/from_dict/to_json/from_json).

Validates that MediatorState can be fully serialized and restored while
preserving all refinement history, critic scores, and session metadata.
"""

import json
import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import MediatorState
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore


@pytest.fixture
def sample_ontology():
    """Sample ontology for testing."""
    return {
        "entities": [
            {"id": "e1", "text": "Alice", "type": "Person"},
            {"id": "e2", "text": "Acme Corp", "type": "Organization"},
        ],
        "relationships": [
            {"source_id": "e1", "target_id": "e2", "type": "works_for"},
        ],
        "metadata": {"domain": "business"},
    }


@pytest.fixture
def sample_critic_score():
    """Sample CriticScore for testing."""
    return CriticScore(
        completeness=0.85,
        consistency=0.90,
        clarity=0.75,
        granularity=0.80,
        relationship_coherence=0.88, domain_alignment=0.88,
        strengths=["good coverage", "clear names"],
        weaknesses=["missing properties"],
        recommendations=["add entity properties", "infer more relationships"],
        metadata={"entity_count": 2, "relationship_count": 1},
    )


def test_mediator_state_to_dict_basic(sample_ontology, sample_critic_score):
    """MediatorState.to_dict() includes all fields."""
    state = MediatorState(
        session_id="test-session-123",
        domain="legal",
        max_rounds=5,
        target_score=0.85,
        convergence_threshold=0.01,
        current_ontology=sample_ontology,
        total_time_ms=1234.5,
    )
    state.add_round(
        ontology=sample_ontology,
        score=sample_critic_score,
        refinement_action="add_properties",
    )

    result = state.to_dict()

    assert "session_id" in result
    assert result["session_id"] == "test-session-123"
    assert result["domain"] == "legal"
    assert result["max_rounds"] == 5
    assert result["target_score"] == 0.85
    assert result["convergence_threshold"] == 0.01
    assert "current_ontology" in result
    assert "refinement_history" in result
    assert "critic_scores" in result
    assert result["total_time_ms"] == 1234.5


def test_mediator_state_from_dict_basic(sample_ontology, sample_critic_score):
    """MediatorState.from_dict() restores basic fields."""
    original = MediatorState(
        session_id="test-session-456",
        domain="medical",
        max_rounds=10,
        target_score=0.90,
        current_ontology=sample_ontology,
        total_time_ms=5678.9,
    )
    original.add_round(
        ontology=sample_ontology,
        score=sample_critic_score,
        refinement_action="normalize_names",
    )

    state_dict = original.to_dict()
    restored = MediatorState.from_dict(state_dict)

    assert restored.session_id == "test-session-456"
    assert restored.domain == "medical"
    assert restored.max_rounds == 10
    assert restored.target_score == 0.90
    assert restored.total_time_ms == 5678.9
    assert restored.current_ontology == sample_ontology


def test_mediator_state_roundtrip_dict(sample_ontology, sample_critic_score):
    """MediatorState round-trips through to_dict/from_dict without loss."""
    original = MediatorState(
        session_id="roundtrip-dict-789",
        domain="financial",
        max_rounds=7,
        target_score=0.88,
        convergence_threshold=0.02,
        current_ontology=sample_ontology,
        total_time_ms=9999.0,
    )
    
    # Add multiple refinement rounds
    original.add_round(
        ontology=sample_ontology,
        score=sample_critic_score,
        refinement_action="prune_orphans",
    )
    
    modified_ontology = {**sample_ontology, "entities": sample_ontology["entities"][:1]}
    score2 = CriticScore(
        completeness=0.70,
        consistency=0.95,
        clarity=0.80,
        granularity=0.85,
        relationship_coherence=0.90, domain_alignment=0.90,
        strengths=["consistent"],
        weaknesses=["incomplete"],
        recommendations=["add more entities"],
    )
    original.add_round(
        ontology=modified_ontology,
        score=score2,
        refinement_action="merge_duplicates",
    )

    state_dict = original.to_dict()
    restored = MediatorState.from_dict(state_dict)

    # Verify all key fields
    assert restored.session_id == original.session_id
    assert restored.domain == original.domain
    assert restored.max_rounds == original.max_rounds
    assert restored.target_score == original.target_score
    assert restored.convergence_threshold == original.convergence_threshold
    assert restored.total_time_ms == original.total_time_ms
    assert restored.current_ontology == original.current_ontology
    
    # Verify refinement history length
    assert len(restored.refinement_history) == len(original.refinement_history)
    assert len(restored.critic_scores) == len(original.critic_scores)
    
    # Verify first round data
    assert restored.refinement_history[0]["round"] == 1
    assert restored.refinement_history[0]["action"] == "prune_orphans"
    
    # Verify second round data
    assert restored.refinement_history[1]["round"] == 2
    assert restored.refinement_history[1]["action"] == "merge_duplicates"


def test_mediator_state_to_json_valid_json(sample_ontology, sample_critic_score):
    """MediatorState.to_json() produces valid JSON."""
    state = MediatorState(
        session_id="json-test-001",
        domain="general",
        current_ontology=sample_ontology,
    )
    state.add_round(
        ontology=sample_ontology,
        score=sample_critic_score,
        refinement_action="test_action",
    )

    json_str = state.to_json()

    # Should parse without error
    parsed = json.loads(json_str)
    assert isinstance(parsed, dict)
    assert "session_id" in parsed
    assert parsed["session_id"] == "json-test-001"


def test_mediator_state_from_json_restores_state(sample_ontology, sample_critic_score):
    """MediatorState.from_json() restores state from JSON string."""
    original = MediatorState(
        session_id="json-restore-002",
        domain="technology",
        max_rounds=3,
        current_ontology=sample_ontology,
        total_time_ms=1111.1,
    )
    original.add_round(
        ontology=sample_ontology,
        score=sample_critic_score,
        refinement_action="add_missing_relationships",
    )

    json_str = original.to_json()
    restored = MediatorState.from_json(json_str)

    assert restored.session_id == "json-restore-002"
    assert restored.domain == "technology"
    assert restored.max_rounds == 3
    assert restored.total_time_ms == 1111.1
    assert len(restored.refinement_history) == 1
    assert restored.refinement_history[0]["action"] == "add_missing_relationships"


def test_mediator_state_roundtrip_json(sample_ontology, sample_critic_score):
    """MediatorState round-trips through to_json/from_json without loss."""
    original = MediatorState(
        session_id="roundtrip-json-003",
        domain="science",
        max_rounds=15,
        target_score=0.92,
        convergence_threshold=0.005,
        current_ontology=sample_ontology,
        total_time_ms=5555.5,
    )
    
    # Add refinement rounds
    for i in range(3):
        score = CriticScore(
            completeness=0.70 + i * 0.05,
            consistency=0.80 + i * 0.05,
            clarity=0.75 + i * 0.05,
            granularity=0.85,
            relationship_coherence=0.90, domain_alignment=0.90,
            strengths=[f"strength_{i}"],
            weaknesses=[f"weakness_{i}"],
            recommendations=[f"rec_{i}"],
        )
        original.add_round(
            ontology=sample_ontology,
            score=score,
            refinement_action=f"action_{i}",
        )

    json_str = original.to_json()
    restored = MediatorState.from_json(json_str)

    # Verify all fields
    assert restored.session_id == original.session_id
    assert restored.domain == original.domain
    assert restored.max_rounds == original.max_rounds
    assert restored.target_score == original.target_score
    assert restored.convergence_threshold == original.convergence_threshold
    assert restored.total_time_ms == original.total_time_ms
    
    # Verify history
    assert len(restored.refinement_history) == 3
    assert len(restored.critic_scores) == 3
    
    # Verify actions in order
    for i in range(3):
        assert restored.refinement_history[i]["action"] == f"action_{i}"


def test_mediator_state_roundtrip_preserves_score_details(sample_ontology):
    """Round-trip preserves CriticScore details including strengths/weaknesses/recommendations."""
    score = CriticScore(
        completeness=0.82,
        consistency=0.91,
        clarity=0.73,
        granularity=0.79,
        relationship_coherence=0.86, domain_alignment=0.86,
        strengths=["high consistency", "good structure"],
        weaknesses=["low clarity", "missing metadata"],
        recommendations=["improve naming", "add descriptions", "validate types"],
        metadata={"evaluated_at": "2026-02-20", "evaluator": "test"},
    )
    
    state = MediatorState(current_ontology=sample_ontology)
    state.add_round(ontology=sample_ontology, score=score, refinement_action="test")
    
    # Round-trip via dict
    dict_restored = MediatorState.from_dict(state.to_dict())
    assert len(dict_restored.critic_scores) == 1
    # Critic scores are stored as dicts in refinement_history
    score_dict = dict_restored.refinement_history[0]["score"]
    assert "strengths" in score_dict
    assert "high consistency" in score_dict["strengths"]
    assert "good structure" in score_dict["strengths"]
    assert "weaknesses" in score_dict
    assert "low clarity" in score_dict["weaknesses"]
    assert "recommendations" in score_dict
    assert len(score_dict["recommendations"]) == 3
    
    # Round-trip via JSON
    json_restored = MediatorState.from_json(state.to_json())
    score_dict_json = json_restored.refinement_history[0]["score"]
    assert score_dict_json["strengths"] == ["high consistency", "good structure"]
    assert score_dict_json["weaknesses"] == ["low clarity", "missing metadata"]
    assert score_dict_json["recommendations"] == [
        "improve naming",
        "add descriptions",
        "validate types",
    ]


def test_mediator_state_roundtrip_empty_state():
    """Round-trip works for empty MediatorState (no rounds added)."""
    original = MediatorState(
        session_id="empty-state-004",
        domain="general",
        max_rounds=5,
    )
    
    # Dict round-trip
    dict_restored = MediatorState.from_dict(original.to_dict())
    assert dict_restored.session_id == "empty-state-004"
    assert dict_restored.domain == "general"
    assert dict_restored.max_rounds == 5
    assert len(dict_restored.refinement_history) == 0
    assert len(dict_restored.critic_scores) == 0
    
    # JSON round-trip
    json_restored = MediatorState.from_json(original.to_json())
    assert json_restored.session_id == "empty-state-004"
    assert len(json_restored.refinement_history) == 0


def test_mediator_state_roundtrip_preserves_current_round(sample_ontology, sample_critic_score):
    """Round-trip preserves current_round from BaseSession."""
    state = MediatorState(current_ontology=sample_ontology)
    
    # Add 3 rounds
    for i in range(3):
        state.add_round(
            ontology=sample_ontology,
            score=sample_critic_score,
            refinement_action=f"action_{i}",
        )
    
    original_round = state.current_round
    assert original_round == 3
    
    # Round-trip and check
    restored = MediatorState.from_dict(state.to_dict())
    assert restored.current_round == original_round


def test_mediator_state_roundtrip_preserves_base_session_metrics(sample_ontology, sample_critic_score):
    """Round-trip preserves BaseSession metrics like rounds, scores, trend."""
    state = MediatorState(
        current_ontology=sample_ontology,
        target_score=0.90,
        convergence_threshold=0.01,
    )
    
    # Add rounds with improving scores
    scores = [0.70, 0.80, 0.85, 0.88]
    for i, score_val in enumerate(scores):
        score = CriticScore(
            completeness=score_val,
            consistency=score_val,
            clarity=score_val,
            granularity=score_val,
            relationship_coherence=score_val, domain_alignment=score_val,
        )
        state.add_round(
            ontology=sample_ontology,
            score=score,
            refinement_action=f"improve_{i}",
        )
    
    # Capture original metrics
    original_rounds = state.rounds
    original_best = state.best_score
    original_trend = state.trend
    
    # Round-trip
    restored = MediatorState.from_dict(state.to_dict())
    
    # Verify BaseSession metrics preserved
    assert len(restored.rounds) == len(original_rounds)
    assert restored.best_score == pytest.approx(original_best, abs=0.01)
    # Trend is a property computed from rounds, should match
    assert restored.trend == original_trend
