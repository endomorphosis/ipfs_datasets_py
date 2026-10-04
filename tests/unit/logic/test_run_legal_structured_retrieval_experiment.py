"""Checkpoint selection must use the development panel, never the holdout."""
import pytest

from scripts.ops.legal_ir.run_legal_structured_retrieval_experiment import select_stage, cyclic_context_rows, digest


def test_selects_tuning_exact_instead_of_test_or_latest_step():
    early = {"new_optimizer_steps": 800, "tuning_exact": 90, "challenge_exact": 0}
    late = {"new_optimizer_steps": 1600, "tuning_exact": 89, "challenge_exact": 192}
    assert select_stage([early, late]) is early


def test_tuning_improvement_selects_later_stage():
    early = {"new_optimizer_steps": 800, "tuning_exact": 90}
    late = {"new_optimizer_steps": 1600, "tuning_exact": 91}
    assert select_stage([late, early]) is late


def test_ties_prefer_earlier_stage_independent_of_list_order():
    early = {"new_optimizer_steps": 800, "tuning_exact": 90}
    late = {"new_optimizer_steps": 1600, "tuning_exact": 90}
    assert select_stage([late, early]) is early


def test_empty_or_duplicate_stages_rejected():
    with pytest.raises(ValueError, match="at least one"):
        select_stage([])
    with pytest.raises(ValueError, match="duplicate"):
        select_stage([{"new_optimizer_steps": 800, "tuning_exact": 90}] * 2)


def test_cyclic_intervention_receipt_matches_actual_vector():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured
    probabilities = [1.] + [0.] * 23
    vector = structured.profile_context(probabilities)
    row = {"id": "query", "source_sha256": "a" * 64, "context": vector,
           "context_sha256": digest(vector), "profile_distribution": probabilities}
    changed = cyclic_context_rows([row], structured)[0]
    assert changed["id"] == row["id"] and changed["source_sha256"] == row["source_sha256"]
    assert changed["context_sha256"] == digest(changed["context"])
    assert changed["context_sha256"] != row["context_sha256"]
    assert changed["profile_distribution"][8] == 1
    assert changed["profile_distribution"][0] == 0
    assert changed["original_context_receipt"] == row
    assert row["profile_distribution"] == probabilities
