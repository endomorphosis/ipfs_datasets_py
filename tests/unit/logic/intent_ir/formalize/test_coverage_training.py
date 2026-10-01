"""Continuation wiring preserves parent bytes and explicit initializer lineage."""
from copy import deepcopy
import json

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import coverage_curriculum as curriculum
from ipfs_datasets_py.logic.intent_ir.formalize import coverage_training as training
from ipfs_datasets_py.logic.intent_ir.formalize import rich_grammar as grammar
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paired_copy_continuation as backend


def sample(identity, source, split):
    return {"id": identity, "instruction": source, "split": split,
            "ast": grammar.parse_instruction(source), "provenance": {"kind": "fixture"}}


def lineage():
    return {"present": True, "frozen": True, "parent_modified": False,
            "initializer_sha256": "a" * 64, "inherited_width": 8}


def test_family_selection_keeps_all_constructors_with_bounded_original_rehearsal():
    originals = [sample(kind, source, "train") for kind, source in [
        ("and", "agent must inspect cache and operator may save report."),
        ("or", "agent must inspect cache or operator may save report."),
        ("then", "agent must inspect cache then operator may save report."),
        ("if", "if cache is ready, agent must inspect report.")]]
    corpus = curriculum.build_coverage_curriculum({"samples": originals})
    data = curriculum.prepare_coverage_training_data(corpus)
    selected = training.select_family_training_rows(corpus, data)
    assert {row["ast"]["kind"] for row in selected["train"]} == {"atom", "and", "or", "then", "if"}
    assert len(selected["train"]) == 48
    assert len(selected["validation"]) == 16
    assert all(row["split"] == split for split, rows in selected.items() for row in rows)
    assert selected == training.select_family_training_rows(corpus, data)


@pytest.mark.parametrize("field,value", [("present", False), ("frozen", False),
    ("parent_modified", True), ("initializer_sha256", "b" * 64)])
def test_missing_or_changed_legal_lineage_cannot_silently_initialize(field, value):
    bad = lineage()
    bad[field] = value
    with pytest.raises(ValueError, match="lineage"):
        training._legal_lineage({"lexical_lineage": bad}, "a" * 64)


@pytest.mark.parametrize("family_mode", [False, True])
def test_continuation_receipt_uses_actual_trainer_result_and_never_overwrites_parent(tmp_path, monkeypatch, family_mode):
    corpus = {"samples": [sample("train", "Run local diagnostics.", "train"),
                          sample("validation", "View heldout parcel.", "validation"),
                          sample("test", "Fetch reserved capsule.", "test")]}
    parent_path = tmp_path / "parent.json"
    parent_path.write_text("immutable original checkpoint")
    parent = {"path": str(parent_path), "schema": "fixture", "sha256": "c" * 64}
    child = {"path": str(tmp_path / "child.json"), "schema": "fixture", "sha256": "d" * 64}
    calls = []
    family_calls = []
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training as family_backend
    def train_families(train_reports, validation_reports, **kwargs):
        family_calls.append((train_reports, validation_reports, kwargs))
        assert all(len(report["family_inventory"]) == 40 for report in train_reports + validation_reports)
        return {"descriptor": {"schema": "test-family-result"}, "report": {"training_executed": False}}
    monkeypatch.setattr(family_backend, "train_family_projection_autoencoder", train_families)
    monkeypatch.setattr(backend, "load_paired_copy_continuation", lambda descriptor: {"training": {"lexical_lineage": lineage()}})
    def train(train_pairs, validation_pairs, **kwargs):
        calls.append((deepcopy(train_pairs), deepcopy(validation_pairs), kwargs))
        assert kwargs["parent_descriptor"] == parent
        assert all("reserved" not in str(row) for row in train_pairs + validation_pairs)
        return child
    monkeypatch.setattr(backend, "train_paired_copy_continuation", train)
    monkeypatch.setattr(training, "register_rich_intent_checkpoint", lambda *a, **k: {"schema": "fixture", "path": "child-manifest"})
    receipt = training.train_coverage_intent(corpus, parent_backend_descriptor=parent,
        expected_legal_initializer_sha256="a" * 64, output=tmp_path / "fork",
        source_training_options={"epochs": 1, "max_seconds": 1},
        **({} if family_mode else {"train_family_projection": False}))
    assert len(calls) == 1 and receipt["backend"] == child
    assert receipt["source_pair_counts"] == {"train": 2, "validation": 2}
    assert receipt["legal_initializer_lineage"] == lineage()
    assert receipt["family_training"]["status"] == ("completed" if family_mode else "not_requested")
    assert len(family_calls) == int(family_mode)
    assert parent_path.read_text() == "immutable original checkpoint"
    assert json.loads((tmp_path / "fork" / "training-receipt.json").read_bytes()) == receipt
    with pytest.raises(FileExistsError):
        training.train_coverage_intent(corpus, parent_backend_descriptor=parent,
            expected_legal_initializer_sha256="a" * 64, output=tmp_path / "fork")
    assert len(calls) == 1


def test_wrong_initializer_is_rejected_before_any_output_or_optimizer(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "load_paired_copy_continuation", lambda descriptor: {"training": {"lexical_lineage": lineage()}})
    monkeypatch.setattr(backend, "train_paired_copy_continuation", lambda *a, **k: pytest.fail("optimizer must not run"))
    with pytest.raises(ValueError, match="lineage"):
        training.train_coverage_intent({"samples": []}, parent_backend_descriptor={"path": "unused"},
            expected_legal_initializer_sha256="b" * 64, output=tmp_path / "fork")
    assert not (tmp_path / "fork").exists()


def test_frozen_pair_limit_is_preflighted_before_output_or_optimizer(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "load_paired_copy_continuation", lambda descriptor: {"training": {"lexical_lineage": lineage()}})
    monkeypatch.setattr(training, "prepare_coverage_training_data", lambda corpus: {"pairs": {"train": [None] * 8193, "validation": [None]}})
    monkeypatch.setattr(backend, "train_paired_copy_continuation", lambda *a, **k: pytest.fail("optimizer must not run"))
    with pytest.raises(ValueError, match="8192"):
        training.train_coverage_intent({"samples": []}, parent_backend_descriptor={"path": "unused"},
            expected_legal_initializer_sha256="a" * 64, output=tmp_path / "fork")
    assert not (tmp_path / "fork").exists()


def test_actual_family_hook_keeps_conditional_structure_and_full_inventory():
    from ipfs_datasets_py.logic.formalization.autoencoder.family_training import prepare_family_training_targets, validate_family_training_report
    corpus = {"samples": [sample("atom", "Run the local archive.", "train"),
        sample("guard", "if parcel is ready, operator must fetch validated catalog.", "validation")]}
    prepared = curriculum.prepare_coverage_training_data(corpus, family_target_builder=prepare_family_training_targets)
    assert len(prepared["family_targets"]) == 2
    for item, original in zip(prepared["family_targets"], corpus["samples"]):
        bundle = item["bundle"]
        validate_family_training_report(bundle, document=original["ast"], source_text=original["instruction"])
        assert len(bundle["family_inventory"]) == 40
        assert bundle["projections"]
        assert not bundle["source_semantics_verified"] and not bundle["proof_authority"]
        if item["sample_id"] == "guard":
            assert {row["logic_family"] for row in bundle["projections"]} == {"dcec", "higher_order", "tdfol"}
            assert any(not row["ready_for_training"] for row in bundle["family_inventory"])
