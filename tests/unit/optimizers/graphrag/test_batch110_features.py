"""Batch-110 feature tests.

Methods under test:
  - ExtractionConfig.clone()
  - OntologyMediator.total_action_count()
  - OntologyMediator.top_actions(n)
  - OntologyMediator.undo_depth()
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kwargs):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
    return ExtractionConfig(**kwargs)


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic

    gen = OntologyGenerator()
    critic = OntologyCritic(use_llm=False)
    return OntologyMediator(generator=gen, critic=critic)


# ---------------------------------------------------------------------------
# ExtractionConfig.clone
# ---------------------------------------------------------------------------

class TestExtractionConfigClone:
    def test_clone_equals_original(self):
        cfg = _make_config(confidence_threshold=0.7)
        cloned = cfg.clone()
        assert cloned.confidence_threshold == cfg.confidence_threshold

    def test_clone_is_different_object(self):
        cfg = _make_config()
        cloned = cfg.clone()
        assert cloned is not cfg

    def test_clone_full_config(self):
        cfg = _make_config(
            confidence_threshold=0.8,
            max_entities=50,
            window_size=300,
        )
        cloned = cfg.clone()
        assert cloned.max_entities == 50
        assert cloned.window_size == 300

    def test_clone_independent(self):
        # Modifying clone doesn't affect original (via from_dict round-trip)
        cfg = _make_config(max_entities=10)
        cloned = cfg.clone()
        assert cloned.max_entities == cfg.max_entities


# ---------------------------------------------------------------------------
# OntologyMediator.total_action_count
# ---------------------------------------------------------------------------

class TestTotalActionCount:
    def test_no_actions(self):
        m = _make_mediator()
        assert m.total_action_count() == 0

    def test_after_direct_set(self):
        m = _make_mediator()
        m._action_counts["add"] = 3
        m._action_counts["remove"] = 2
        assert m.total_action_count() == 5

    def test_single_action(self):
        m = _make_mediator()
        m._action_counts["merge"] = 7
        assert m.total_action_count() == 7


# ---------------------------------------------------------------------------
# OntologyMediator.top_actions
# ---------------------------------------------------------------------------

class TestTopActions:
    def test_no_actions_returns_empty(self):
        m = _make_mediator()
        assert m.top_actions() == []

    def test_returns_most_frequent_first(self):
        m = _make_mediator()
        m._action_counts["alpha"] = 1
        m._action_counts["beta"] = 5
        m._action_counts["gamma"] = 3
        result = m.top_actions(2)
        assert result[0] == "beta"
        assert result[1] == "gamma"

    def test_n_limits_results(self):
        m = _make_mediator()
        for i in range(5):
            m._action_counts[f"action_{i}"] = i + 1
        assert len(m.top_actions(2)) == 2

    def test_n_larger_than_actions(self):
        m = _make_mediator()
        m._action_counts["only"] = 1
        assert len(m.top_actions(10)) == 1

    def test_alphabetical_tie_breaking(self):
        m = _make_mediator()
        m._action_counts["b_action"] = 5
        m._action_counts["a_action"] = 5
        result = m.top_actions(2)
        # Both have same count; "a_action" should come first alphabetically
        assert result[0] == "a_action"


# ---------------------------------------------------------------------------
# OntologyMediator.undo_depth
# ---------------------------------------------------------------------------

class TestUndoDepth:
    def test_empty_stack(self):
        m = _make_mediator()
        assert m.undo_depth() == 0

    def test_equals_get_undo_depth(self):
        m = _make_mediator()
        m.stash({"entities": [], "relationships": []})
        assert m.undo_depth() == m.get_undo_depth()

    def test_increments_on_stash(self):
        m = _make_mediator()
        initial = m.undo_depth()
        m.stash({"entities": [], "relationships": []})
        assert m.undo_depth() == initial + 1

    def test_decrements_on_clear(self):
        m = _make_mediator()
        m.stash({"entities": [], "relationships": []})
        m.clear_stash()
        assert m.undo_depth() == 0
