"""Training replay and honest source-specific evaluation denominators."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import compositional_training as sut
from ipfs_datasets_py.logic.intent_ir.formalize import compositional_curriculum as corpus_module


def _row(name, correct):
    result = {"id": name, "slot_correct": {slot: correct for slot in ("actor", "action", "object", "modality")}}
    for key in ("encode_valid", "encode_exact", "native_ir_valid", "decode_exact", "composed_exact",
                "cycle_consistent", "encoder_oov", "deployable_candidate", "deployable_exact"):
        result[key] = correct
    return result


def _samples():
    return [{"id": name, "provenance": {"kind": kind}} for name, kind in (
        ("public", "skillcenter_rich_weak_span"),
        ("old", "authored_development_control"),
        ("new", "authored_compositional_curriculum"))]


def test_source_replay_failure_stops_before_any_fitting(monkeypatch, tmp_path):
    calls = []
    def reject(corpus):
        raise ValueError("changed target")
    monkeypatch.setattr(corpus_module, "validate_compositional_corpus", reject)
    monkeypatch.setattr(sut, "train_intent_copy", lambda *args, **kwargs: calls.append("fit"))
    with pytest.raises(ValueError, match="changed target"):
        sut.train_compositional_intent({}, tmp_path / "output")
    assert calls == [] and not (tmp_path / "output").exists()


def test_validated_corpus_and_settings_pass_unchanged(monkeypatch, tmp_path):
    corpus = {"samples": _samples()}
    before = deepcopy(corpus)
    calls = []
    monkeypatch.setattr(corpus_module, "validate_compositional_corpus", lambda value: calls.append(("validate", value)))
    def fit(value, output, **settings):
        calls.append(("fit", value, output, settings))
        return {"receipt": "from_shared_training"}
    monkeypatch.setattr(sut, "train_intent_copy", fit)
    result = sut.train_compositional_intent(corpus, tmp_path, epochs=100, copy_dropout=0)
    assert result == {"receipt": "from_shared_training"}
    assert calls == [("validate", corpus), ("fit", corpus, tmp_path, {"epochs": 100, "copy_dropout": 0})]
    assert corpus == before


def test_public_and_both_authored_groups_never_share_denominators(monkeypatch):
    rows = [_row("public", False), _row("old", True), _row("new", False)]
    base = {"rows": rows, "groups": {"authored": {"count": 2}}, "weight_ablation": None}
    monkeypatch.setattr(sut, "evaluate_intent_copy", lambda *args, **kwargs: deepcopy(base))
    result = sut.evaluate_compositional_intent({}, _samples())
    assert result["rows"] == rows
    assert result["source_groups"]["skillcenter_rich_weak_span"]["composed_exact_rate"] == 0
    assert result["source_groups"]["authored_development_control"]["composed_exact_rate"] == 1
    assert result["source_groups"]["authored_compositional_curriculum"]["composed_exact_rate"] == 0
    assert all(metrics["count"] == 1 for metrics in result["source_groups"].values())
    assert result["source_group_ids"]["authored_compositional_curriculum"] == ["new"]
    assert result["authored_curriculum_is_not_public_semantic_gold"] is True


@pytest.mark.parametrize("ids", [["public", "old"], ["public", "old", "unknown"],
                                   ["public", "old", "new", "new"]])
def test_missing_extra_and_duplicate_evaluation_rows_rejected(monkeypatch, ids):
    monkeypatch.setattr(sut, "evaluate_intent_copy", lambda *args, **kwargs: {"rows": [_row(i, True) for i in ids]})
    with pytest.raises(ValueError, match="identities differ"):
        sut.evaluate_compositional_intent({}, _samples())


def test_duplicate_input_identity_rejected(monkeypatch):
    monkeypatch.setattr(sut, "evaluate_intent_copy", lambda *args, **kwargs: {"rows": [_row("public", True)]})
    with pytest.raises(ValueError, match="identities differ"):
        sut.evaluate_compositional_intent({}, [_samples()[0], _samples()[0]])


def test_empty_evaluation_has_no_invented_denominator(monkeypatch):
    monkeypatch.setattr(sut, "evaluate_intent_copy", lambda *args, **kwargs: {"rows": [], "count": 0})
    result = sut.evaluate_compositional_intent({}, [])
    assert result["source_groups"] == result["source_group_ids"] == {}
