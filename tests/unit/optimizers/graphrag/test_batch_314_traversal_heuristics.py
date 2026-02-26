"""Batch 314: tests for extracted TraversalHeuristics module."""

from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import UnifiedGraphRAGQueryOptimizer
from ipfs_datasets_py.optimizers.graphrag import TraversalHeuristics


def test_detect_query_relations_extracts_expected_relations() -> None:
    relations = TraversalHeuristics.detect_query_relations(
        "What type of component was created and where is it located?"
    )
    assert "instance_of" in relations
    assert "part_of" in relations
    assert "created_by" in relations
    assert "located_in" in relations


def test_detect_fact_verification_query_positive_cases() -> None:
    assert TraversalHeuristics.detect_fact_verification_query(
        {"source_entity": "A", "target_entity": "B"}
    )
    assert TraversalHeuristics.detect_fact_verification_query(
        {"query_text": "Is it true that Paris is the capital of France?"}
    )


def test_detect_exploratory_query_positive_cases() -> None:
    assert TraversalHeuristics.detect_exploratory_query(
        {"query_text": "Tell me about quantum computing"}
    )
    assert TraversalHeuristics.detect_exploratory_query(
        {"traversal": {"max_depth": 4}, "query_text": "overview"}
    )


def test_detect_entity_types_with_default_and_override() -> None:
    assert TraversalHeuristics.detect_entity_types("", predefined_types=["person"]) == ["person"]
    detected = TraversalHeuristics.detect_entity_types("Who founded the company?")
    assert "person" in detected
    assert "organization" in detected


def test_estimate_query_complexity_levels() -> None:
    low = TraversalHeuristics.estimate_query_complexity({"query_text": "what is ai"})
    medium = TraversalHeuristics.estimate_query_complexity(
        {
            "query_text": "explain the relationship between concepts",
            "traversal": {"max_depth": 2, "edge_types": ["related_to", "part_of"]},
        }
    )
    high = TraversalHeuristics.estimate_query_complexity(
        {
            "query_text": "describe in detail all relationships among these entities",
            "entity_ids": ["a", "b", "c", "d", "e"],
            "vector_params": {"top_k": 20},
            "traversal": {"max_depth": 4, "edge_types": ["a", "b", "c", "d", "e", "f"]},
        }
    )
    assert low == "low"
    assert medium in {"low", "medium"}
    assert high == "high"


def test_unified_optimizer_wrappers_delegate_to_traversal_heuristics() -> None:
    optimizer = UnifiedGraphRAGQueryOptimizer()

    query = {"query_text": "Is this related to that?", "traversal": {"max_depth": 2}}
    assert optimizer._detect_fact_verification_query(query) == TraversalHeuristics.detect_fact_verification_query(query)
    assert optimizer._detect_exploratory_query(query) == TraversalHeuristics.detect_exploratory_query(query)
    assert optimizer._estimate_query_complexity(query) == TraversalHeuristics.estimate_query_complexity(query)
    assert optimizer._detect_entity_types("Who founded the company?") == TraversalHeuristics.detect_entity_types(
        "Who founded the company?"
    )