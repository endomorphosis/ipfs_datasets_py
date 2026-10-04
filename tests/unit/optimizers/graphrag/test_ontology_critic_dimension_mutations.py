"""Mutation-style regression tests for ontology critic dimension evaluators.

These tests harden evaluator behavior against common mutation patterns by
asserting score movement under targeted input changes.
"""

from types import SimpleNamespace

from ipfs_datasets_py.optimizers.graphrag.ontology_critic_clarity import evaluate_clarity
from ipfs_datasets_py.optimizers.graphrag.ontology_critic_completeness import evaluate_completeness
from ipfs_datasets_py.optimizers.graphrag.ontology_critic_consistency import evaluate_consistency
from ipfs_datasets_py.optimizers.graphrag.ontology_critic_connectivity import (
    evaluate_relationship_coherence,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic_domain_alignment import (
    evaluate_domain_alignment,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic_granularity import evaluate_granularity


def _base_entities():
    return [
        {"id": "e1", "text": "alpha", "type": "concept", "properties": {"p": 1}, "confidence": 0.9},
        {"id": "e2", "text": "beta", "type": "concept", "properties": {"p": 2}, "confidence": 0.8},
        {"id": "e3", "text": "gamma", "type": "concept", "properties": {"p": 3}, "confidence": 0.7},
    ]


def test_completeness_rewards_relationships_diversity_and_source_coverage():
    context = SimpleNamespace(domain="general")

    sparse = {
        "entities": _base_entities(),
        "relationships": [],
        "domain": "general",
    }
    rich = {
        "entities": [
            {"id": "e1", "text": "contract", "type": "legal_term", "properties": {"p": 1}},
            {"id": "e2", "text": "clause", "type": "legal_term", "properties": {"p": 2}},
            {"id": "e3", "text": "party", "type": "actor", "properties": {"p": 3}},
        ],
        "relationships": [
            {"source_id": "e1", "target_id": "e2", "type": "has_clause"},
            {"source_id": "e2", "target_id": "e3", "type": "involves"},
        ],
        "domain": "legal",
    }

    sparse_score = evaluate_completeness(sparse, context, None)
    rich_score = evaluate_completeness(rich, context, "contract clause party")

    assert rich_score > sparse_score


def test_clarity_penalizes_short_names_and_missing_fields():
    context = SimpleNamespace()

    good = {
        "entities": _base_entities(),
        "relationships": [],
    }
    noisy = {
        "entities": [
            {"id": "e1", "text": "a", "type": "concept", "properties": {}, "confidence": 0.0},
            {"id": "e2", "text": "b", "type": "concept", "properties": {}, "confidence": 0.0},
            {"id": "e3", "text": "c", "type": "concept", "properties": {}, "confidence": 0.0},
        ],
        "relationships": [],
    }

    good_score = evaluate_clarity(good, context)
    noisy_score = evaluate_clarity(noisy, context)

    assert good_score > noisy_score


def test_consistency_penalizes_invalid_refs_duplicates_and_cycles():
    context = SimpleNamespace()

    base = {
        "entities": [
            {"id": "e1"},
            {"id": "e2"},
            {"id": "e3"},
        ],
        "relationships": [
            {"source_id": "e1", "target_id": "e2", "type": "is_a"},
            {"source_id": "e2", "target_id": "e3", "type": "part_of"},
        ],
    }
    mutated = {
        "entities": [
            {"id": "e1"},
            {"id": "e1"},
            {"id": "e3"},
        ],
        "relationships": [
            {"source_id": "e1", "target_id": "e2", "type": "is_a"},
            {"source_id": "e2", "target_id": "e1", "type": "is_a"},
            {"source_id": "e4", "target_id": "e3", "type": "part_of"},
        ],
    }

    base_score = evaluate_consistency(base, context)
    mutated_score = evaluate_consistency(mutated, context)

    assert base_score > mutated_score


def test_granularity_rewards_properties_and_relationship_ratio():
    context = SimpleNamespace()

    coarse = {
        "entities": [
            {"id": "e1", "properties": {}},
            {"id": "e2", "properties": {}},
        ],
        "relationships": [],
    }
    detailed = {
        "entities": [
            {"id": "e1", "properties": {"p1": 1, "p2": 2}},
            {"id": "e2", "properties": {"p3": 3}},
        ],
        "relationships": [
            {"source_id": "e1", "target_id": "e2", "type": "depends_on"},
            {"source_id": "e2", "target_id": "e1", "type": "relates_to"},
        ],
    }

    coarse_score = evaluate_granularity(coarse, context)
    detailed_score = evaluate_granularity(detailed, context)

    assert detailed_score > coarse_score


def test_domain_alignment_rewards_vocab_hits():
    legal_context = SimpleNamespace(domain="legal")

    aligned = {
        "entities": [
            {"id": "e1", "type": "contract"},
            {"id": "e2", "type": "party"},
        ],
        "relationships": [
            {"source_id": "e1", "target_id": "e2", "type": "obligation"},
        ],
    }
    unaligned = {
        "entities": [
            {"id": "e1", "type": "vehicle"},
            {"id": "e2", "type": "tree"},
        ],
        "relationships": [
            {"source_id": "e1", "target_id": "e2", "type": "related_to"},
        ],
    }

    aligned_score = evaluate_domain_alignment(aligned, legal_context)
    unaligned_score = evaluate_domain_alignment(unaligned, legal_context)

    assert aligned_score > unaligned_score


def test_relationship_coherence_rewards_meaningful_types():
    context = SimpleNamespace()

    generic = {
        "entities": [
            {"id": "e1", "type": "component"},
            {"id": "e2", "type": "module"},
        ],
        "relationships": [
            {"source_id": "e1", "target_id": "e2", "type": "related_to"},
            {"source_id": "e2", "target_id": "e1", "type": "connected"},
        ],
    }
    meaningful = {
        "entities": [
            {"id": "e1", "type": "component"},
            {"id": "e2", "type": "module"},
        ],
        "relationships": [
            {"source_id": "e1", "target_id": "e2", "type": "depends_on"},
            {"source_id": "e2", "target_id": "e1", "type": "implements"},
        ],
    }

    generic_score = evaluate_relationship_coherence(generic, context)
    meaningful_score = evaluate_relationship_coherence(meaningful, context)

    assert meaningful_score > generic_score
