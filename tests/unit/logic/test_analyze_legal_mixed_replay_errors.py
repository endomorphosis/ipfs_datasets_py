"""Posthoc categories preserve failures and separate source-exposure claims."""
import pytest

from scripts.ops.legal_ir import analyze_legal_mixed_replay_errors as analysis


@pytest.mark.parametrize("actual,wanted,state", [(["within 5 days"], ["within 5 days"], "correct"),
    ([], ["within 5 days"], "missing"), (["within 5 days"], [], "spurious"),
    (["within 8 days"], ["within 5 days"], "wrong_value")])
def test_temporal_facet_presence_and_value_failures(actual, wanted, state):
    prediction = {"status": "decoded", "canonical_ir": {"rules": [{"temporal": actual}]}}
    assert analysis.facet_state(prediction, wanted, "temporal") == state


def test_abstention_is_distinct_from_missing_qualifier():
    assert analysis.facet_state({"status": "abstained", "canonical_ir": None}, [], "temporal") == "abstained"


def test_temporal_layout_uses_supplied_coordinates_only():
    target = {"canonical_ir": {"rules": [{"temporal": ["within 5 days"]}]},
              "facet_spans": {"actor": [20, 30], "temporal": [0, 13]}}
    assert analysis.temporal_layout(target) == "before_actor"
    target["facet_spans"]["temporal"] = [40, 53]
    assert analysis.temporal_layout(target) == "after_actor"
    target.pop("facet_spans")
    assert analysis.temporal_layout(target) == "present_coordinates_unavailable"


def test_surface_exposure_prioritizes_training_and_avoids_novelty_claim():
    assert analysis.layout_exposure(["new_train", "earlier_tuning"]) == "matched_admitted_training_surface"
    assert analysis.layout_exposure(["earlier_tuning"]) == "matched_tuning_surface_only"
    assert analysis.layout_exposure(["exposed_grounding_challenge"]) == "matched_exposed_challenge_surface_only"
    assert analysis.layout_exposure([]) == "unmatched_exact_surface_not_proven_inherited_novel"


def test_paired_counts_keep_both_wrong_and_reject_reordering():
    left = [{"id": "a", "exact": False}, {"id": "b", "exact": True}]
    right = [{"id": "a", "exact": False}, {"id": "b", "exact": False}]
    assert analysis.compare_rows(left, right) == {"count": 2, "left_only_correct": 1,
        "right_only_correct": 0, "both_correct": 0, "both_wrong": 1}
    with pytest.raises(ValueError, match="ordering"):
        analysis.compare_rows(left, right[::-1])


def test_incomplete_qualification_cannot_open_any_reference(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("reference opened before qualification freeze")
    monkeypatch.setattr(analysis, "read_ref", forbidden)
    with pytest.raises(ValueError, match="completed qualification"):
        analysis.analyze(tmp_path / "run", tmp_path / "qualification", tmp_path / "report.json")
