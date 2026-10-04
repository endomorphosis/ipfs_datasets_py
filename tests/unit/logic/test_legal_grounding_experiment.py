"""Evaluation boundaries and accounting for the matched grounding experiment."""
from copy import deepcopy
import hashlib
import json

import pytest

from scripts.ops.legal_ir import run_legal_grounding_experiment as experiment


def source(identity="a", text="The Office may retain files."):
    return {"id": identity, "source_text": text}


def test_cross_split_overlap_and_within_split_duplicates_rejected():
    a, b, c = source(), source("b", "The Board must review records."), source("c", "The Clerk must not disclose files.")
    experiment.verify_splits([a], [b], [c])
    with pytest.raises(ValueError, match="overlapping"):
        experiment.verify_splits([a], [b], [{**a, "id": "renamed"}])
    with pytest.raises(ValueError, match="duplicate"):
        experiment.verify_splits([a, {**a, "id": "duplicate-text"}], [b], [c])


@pytest.mark.parametrize("field", ["canonical_ir", "trigger_span", "facet_spans"])
def test_challenge_labels_cannot_enter_generation_inventory(field):
    with pytest.raises(ValueError, match="contain targets"):
        experiment.verify_splits([source()], [source("b", "B")], [{**source("c", "C"), field: None}])


def test_source_hash_is_verified_and_metadata_does_not_cross_inference_boundary():
    row = {**source(), "canonical_ir": "private", "source_sha256": "0" * 64}
    with pytest.raises(ValueError, match="hash"):
        experiment.source_rows([row])
    del row["source_sha256"]
    actual = experiment.source_rows([row])
    assert set(actual[0]) == {"id", "source_text", "source_sha256"}


def test_selection_uses_tuning_then_earliest_stage():
    stages = [{"steps": 400, "tuning_exact": 90}, {"steps": 800, "tuning_exact": 90}]
    assert experiment.select_stage(stages) == stages[0]
    stages[1]["tuning_exact"] += 1
    assert experiment.select_stage(stages) == stages[1]
    with pytest.raises(ValueError, match="unique"):
        experiment.select_stage([stages[0], stages[0]])


def test_artifact_bytes_verified_before_parse(tmp_path):
    path = tmp_path / "sealed.json"
    path.write_text("{not parsed")
    reference = experiment.ref(path)
    assert experiment.read_ref(reference, parse=False) is None
    path.write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        experiment.read_ref(reference, parse=False)


def test_targets_require_complete_source_binding():
    sources = experiment.source_rows([source(), source("b", "B")])
    targets = [{**s, "canonical_ir": {"rules": []}} for s in sources]
    assert len(experiment.reference_rows({"targets": targets}, sources)) == 2
    with pytest.raises(ValueError, match="complete"):
        experiment.reference_rows(targets[:1], sources)
    wrong = deepcopy(targets)
    wrong[0]["source_text"] = "changed"
    with pytest.raises(ValueError, match="binding"):
        experiment.reference_rows(wrong, sources)


def test_paired_accounting_keeps_both_wrong_and_rejects_reordered_ids():
    a = {"rows": [{"id": str(i), "exact": value} for i, value in enumerate([True, True, False, False])]}
    b = {"rows": [{"id": str(i), "exact": value} for i, value in enumerate([True, False, True, False])]}
    assert experiment.paired(a, b) == {"count": 4, "left_only_correct": 1, "right_only_correct": 1,
        "both_correct": 1, "both_wrong": 1}
    with pytest.raises(ValueError, match="identities"):
        experiment.paired(a, {"rows": list(reversed(b["rows"]))})


def test_generate_only_passes_source_strings_and_named_ablation():
    class Decoder:
        def decode_formal_logic(self, texts, **kwargs):
            assert texts == ["The Office may retain files."]
            assert kwargs == {"trigger_ablation": "disabled"}
            return {"target_access": False, "teacher_forcing": False,
                "rows": [{"source_sha256": hashlib.sha256(texts[0].encode()).hexdigest()}]}
    result = experiment.generate(Decoder(), experiment.source_rows([source()]), ablation="disabled")
    assert len(result["rows"]) == 1 and result["target_access"] is False
    with pytest.raises(ValueError, match="intervention"):
        experiment.generate(Decoder(), experiment.source_rows([source()]), parent=True, ablation="disabled")


def test_generate_rejects_teacher_forced_output():
    class Decoder:
        def decode_formal_logic(self, texts, **kwargs):
            return {"target_access": True, "teacher_forcing": True}
    with pytest.raises(ValueError, match="source-only"):
        experiment.generate(Decoder(), experiment.source_rows([source()]))


def test_build_accounting_does_not_equate_compilation_with_reference_fidelity():
    from scripts.ops.legal_ir.summarize_legal_open_vocabulary_experiment import build_accounting
    selection = {"rows": [{"candidate": {"candidate_id": "a"}}], "excluded": [{"candidate_id": "b"}],
        "source_count": 2, "decoded_count": 1, "supported_count": 1, "exclusion_counts": {"decoder_abstained": 1}}
    receipts = [{"candidate_ids": ["a"], "build_passed": True, "backend_executed": True}]
    result = build_accounting(selection, receipts, {"a": False, "b": False})
    assert result["count"] == 2 and result["built"] == 1 and result["exact"] == 0
    assert result["built_reference_mismatch"] == 1 and result["abstained"] == 1


def test_fitting_loader_never_opens_or_hashes_sealed_target_files(tmp_path, monkeypatch):
    from scripts.ops.legal_ir import prepare_legal_grounding_curriculum as curriculum
    def put(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return experiment.ref(path)
    train, tune, challenge = [source()], [source("b", "B")], [source("c", "C")]
    artifacts = {"train": put("train.json", train), "tuning": put("tune.json", tune),
        "challenge_sources": put("sources.json", challenge),
        "challenge_targets": {"path": str(tmp_path / "never-open-test.json"), "sha256": "f" * 64, "bytes": 100}}
    manifest = {"artifacts": artifacts}
    config = {"schema": "legal-grounding-run-config/v1", "curriculum_manifest": put("manifest.json", manifest),
        "training": artifacts["train"], "tuning": artifacts["tuning"], "challenge_sources": artifacts["challenge_sources"],
        "challenge_targets": artifacts["challenge_targets"], "producer_files": [],
        "parent_heads": put("parents.json", [{"arm": "source_only", "seed": s} for s in experiment.SEEDS]),
        "regression_sources": put("regression.json", {"challenge": experiment.source_rows([source("d", "D")])}),
        "regression_targets": {"path": str(tmp_path / "never-open-regression.json"), "sha256": "e" * 64, "bytes": 100}}
    config_ref = put("config.json", config)
    monkeypatch.setattr(curriculum, "load_training_inputs", lambda _: (manifest, train, tune, challenge))
    actual = experiment.load_config(config_ref["path"])
    assert actual[1:3] == (train, tune)
    assert not (tmp_path / "never-open-test.json").exists()
