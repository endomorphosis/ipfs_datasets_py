"""Transport/replay boundaries; real numerical and Lake replay is separate."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_action_runtime_384 as runtime
from ipfs_datasets_py.logic.intent_ir.formalize import action_contracts as codec

SOURCE = "the agent must compute result; requires left > 0; ensures result = old(left) + old(right) and returned."


@pytest.fixture
def setup(tmp_path, monkeypatch):
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_bytes(b"test numerical transport")
    candidate = codec.source_to_target(SOURCE)
    observed = []
    def infer(rows):
        observed.append(deepcopy(rows))
        assert set(rows[0]) == {"id", "source_text", "embedding"}
        return {"rows": [{"candidate_ir": deepcopy(candidate)}]}
    monkeypatch.setattr(runtime, "_pins", lambda: {"test_transport": "unchanged"})
    monkeypatch.setattr(runtime.structured, "load_checkpoint", lambda *args, **kw: SimpleNamespace(infer=infer))
    monkeypatch.setattr(runtime.producer, "_snapshot_assets", lambda path: (tmp_path, [{"asset": "pinned"}]))
    monkeypatch.setattr(runtime.embeddings, "embed_texts", lambda texts, **kw: [[0.0] * 384 for text in texts])
    return {"checkpoint_path": str(checkpoint), "expected_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            "snapshot_path": str(tmp_path)}, candidate, observed


def test_predicted_native_effects_remain_distinct_from_exact_source_provenance(setup):
    options, candidate, observed = setup
    before = deepcopy(candidate)
    report = runtime.prepare_intent_action_inference(SOURCE, **options)
    assert report["status"] == "source_supported_action_contract"
    assert report["raw_candidate_ir"] == candidate == before
    assert report["native_intent_ir"]["actions"][0]["effect_ids"] == ["effect:equation", "effect:returned"]
    assert report["binding"]["changed_paths"] == ["/document/sources/0"]
    assert all(report[key] is False for key in runtime.FALSE)
    assert runtime.verify_intent_action_inference(report, SOURCE, **options) == report
    assert len(observed) == 2  # validation actually recomputes numerical readout


@pytest.mark.parametrize("path", [("native_intent_ir", "title"), ("checkpoint_sha256",),
    ("raw_candidate_ir", "document", "title"), ("proof_authority",), ("source_sha256",),
    ("embedding_sha256",), ("report_sha256",)])
def test_saved_report_mutation_requires_replay(setup, path):
    options, _, _ = setup
    report = runtime.prepare_intent_action_inference(SOURCE, **options)
    current = report
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = True if path[-1] == "proof_authority" else "modified"
    with pytest.raises(ValueError, match="replay differs"):
        runtime.verify_intent_action_inference(report, SOURCE, **options)


def test_source_parser_cannot_correct_wrong_learned_operator(setup):
    options, candidate, _ = setup
    wrong = codec.source_to_target(SOURCE.replace(" + ", " - "))
    candidate.clear()
    candidate.update(wrong)
    report = runtime.prepare_intent_action_inference(SOURCE, **options)
    assert report["status"] == "fail_open_source_disagreement"
    assert report["raw_candidate_ir"] == wrong
    assert report["native_intent_ir"] is None
    assert not report["provenance_binding_performed"]


def test_permission_only_instruction_does_not_run_contract_model(setup):
    options, _, observed = setup
    report = runtime.prepare_intent_action_inference("the agent may delete the report.", **options)
    assert report["status"] == "fail_open_input_out_of_scope"
    assert observed == [] and report["native_intent_ir"] is None


def test_producer_drift_discards_bound_advice(setup, monkeypatch):
    options, _, _ = setup
    counts = iter([{"generation": 1}, {"generation": 2}])
    monkeypatch.setattr(runtime, "_pins", lambda: next(counts))
    report = runtime.prepare_intent_action_inference(SOURCE, **options)
    assert report["status"] == "fail_open_unavailable"
    assert report["native_intent_ir"] is None and report["model_inference_executed"]


def test_missing_checkpoint_fails_open_without_download(setup, monkeypatch):
    options, _, _ = setup
    def missing(*args, **kw):
        raise OSError("local checkpoint unavailable")
    monkeypatch.setattr(runtime.structured, "load_checkpoint", missing)
    report = runtime.prepare_intent_action_inference(SOURCE, **options)
    assert report["status"] == "fail_open_unavailable"
    assert report["continue_planning"] and not report["model_inference_executed"]
    assert not report["download_performed"]


@pytest.mark.parametrize("value", [None, "", "x" * 8193])
def test_invalid_source_is_rejected(setup, value):
    options, _, _ = setup
    with pytest.raises(ValueError, match="instruction"):
        runtime.prepare_intent_action_inference(value, **options)
