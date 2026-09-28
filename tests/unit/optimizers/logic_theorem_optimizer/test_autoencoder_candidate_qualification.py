"""Candidate checks distinguish optimizer, metric, syntax, and Lake evidence."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_candidate_qualification as q


@pytest.mark.parametrize("cosine,loss,passed", [
    (.72, .20, True), (1., 0., True), (.719, .01, False), (.99, .201, False),
    (None, .1, False), (.8, None, False), (float("nan"), .1, False),
    (.8, float("inf"), False), (True, .1, False), (.8, False, False),
    (1.1, .1, False), (-1.1, .1, False), (.8, -.1, False),
])
def test_absolute_metric_gate(cosine, loss, passed):
    result = q.metric_gate({"sample_count": 1, "embedding_cosine_similarity": cosine,
                            "reconstruction_loss": loss})
    assert result["passed"] is passed
    assert result["admitted"] is False
    assert result["text_roundtrip_equivalence"] is False
    json.dumps(result, allow_nan=False)


def test_missing_or_aggregate_metrics_do_not_qualify():
    assert not q.metric_gate({})["passed"]
    assert not q.metric_gate({"sample_count": 2, "embedding_cosine_similarity": 1,
                              "reconstruction_loss": 0})["passed"]


@pytest.mark.parametrize("ulps", [1, 8])
@pytest.mark.parametrize("sign", [1, -1])
def test_only_machine_roundoff_outside_cosine_range_is_clamped(sign, ulps):
    cosine = sign * (1.0 + ulps * math.ulp(1.0))
    result = q.metric_gate({"sample_count": 1, "embedding_cosine_similarity": cosine,
                            "reconstruction_loss": 0.0})
    assert result["embedding_cosine_similarity_raw"] == cosine
    assert result["embedding_cosine_similarity"] == float(sign)
    assert result["cosine_roundoff_clamped"] is True
    assert result["diagnostics"] == [{"code": "cosine_roundoff_clamped", "raw": cosine,
                                      "used": float(sign), "tolerance": 8 * math.ulp(1.0)}]
    assert result["passed"] is (sign == 1)
    assert "invalid_embedding_cosine_similarity" not in result["reasons"]
    if sign == -1:
        assert "embedding_cosine_below_threshold" in result["reasons"]
    assert result["min_cosine"] == .72
    assert result["max_reconstruction_loss"] == .20


@pytest.mark.parametrize("sign", [1, -1])
def test_out_of_range_cosine_beyond_roundoff_budget_fails(sign):
    cosine = sign * (1.0 + 9 * math.ulp(1.0))
    result = q.metric_gate({"sample_count": 1, "embedding_cosine_similarity": cosine,
                            "reconstruction_loss": 0.0})
    assert not result["passed"]
    assert not result["cosine_roundoff_clamped"]
    assert result["embedding_cosine_similarity_raw"] == cosine
    assert result["embedding_cosine_similarity"] == cosine
    assert "invalid_embedding_cosine_similarity" in result["reasons"]


def _candidate(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
    path = tmp_path / "candidate.json"
    raw = (ModalAutoencoderTrainingState().to_json() + "\n").encode()
    path.write_bytes(raw)
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _sample(text="The agency shall retain records.", section="1"):
    return {"title": "5", "section": section, "text": text}


def _failed_structure(*args, **kwargs):
    failure = {"passed": False, "reason": "test_structural_gap", "admitted": False}
    return {"compiler": {"compiler_status": "abstain"}, "semantic_gate": failure,
            "family_syntax_gate": failure, "lake_gate": failure}


def test_exact_checkpoint_bytes_required(tmp_path):
    descriptor = _candidate(tmp_path)
    Path(descriptor["path"]).write_bytes(b"{}\n")
    with pytest.raises(ValueError, match="declared size|mismatch"):
        q._load_candidate(descriptor, ())


def test_extra_checkpoint_dependencies_refused(tmp_path):
    descriptor = _candidate(tmp_path)
    extra = tmp_path / "extra.json"
    raw = Path(descriptor["path"]).read_bytes() + b" "
    extra.write_bytes(raw)
    with pytest.raises(q.CandidateQualificationError, match="unreferenced"):
        q._load_candidate(descriptor, [{"path": str(extra), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}])


@pytest.mark.parametrize("kwargs", [
    {"min_cosine": .71}, {"max_reconstruction_loss": .21},
    {"min_cosine": float("nan")}, {"lake_timeout_seconds": 0},
])
def test_thresholds_cannot_be_weakened(tmp_path, kwargs):
    with pytest.raises(q.CandidateQualificationError):
        q.qualify_candidate(_candidate(tmp_path), "candidate-version", [_sample()], tmp_path / "qualification", **kwargs)


def test_native_evaluation_binds_checkpoint_and_missing_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "_structural_gates", _failed_structure)
    descriptor = _candidate(tmp_path)
    result = q.qualify_candidate(descriptor, "registered-version-17", [_sample()], tmp_path / "qualification",
                                  model_config={"compute_device": "python"})
    assert result["candidate_version_id"] == "registered-version-17"
    assert result["candidate_artifact"] == {key: descriptor[key] for key in ("sha256", "bytes")}
    assert result["checkpoint_artifacts"] == [result["candidate_artifact"]]
    assert not result["qualified"] and not result["admitted"]
    assert result["needs_training"]
    assert result["heldout_gate"]["reason"] == "heldout_samples_missing"
    assert result["heldout_role"] == "tuning_validation"
    assert not result["heldout_canary"]
    assert result["metric_evaluation"]["use_sample_memory"] is False
    assert result["metric_evaluation"]["legal_ir_target_count"] == 0
    assert result["rows"][0]["decoded_embedding"] is not None
    assert result["rows"][0]["model_generated_text"] is None
    assert result["execution_path"] == "inference" and result["training_executed"] is False
    assert result["execution_gate_applied"] is True


def test_qualifier_uses_inference_gate_and_never_enters_training(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paths as paths
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
    original = paths.gated_evaluate
    calls = []
    def gated(model, samples, **kwargs):
        calls.append(kwargs)
        return original(model, samples, **kwargs)
    def forbidden(*args, **kwargs):
        pytest.fail("qualification entered projection training")
    monkeypatch.setattr(paths, "gated_evaluate", gated)
    monkeypatch.setattr(AdaptiveModalAutoencoder, "train_generalizable_projection", forbidden)
    monkeypatch.setattr(q, "_structural_gates", _failed_structure)
    result = q.qualify_candidate(_candidate(tmp_path), "version", [_sample()], tmp_path / "qualification",
                                model_config={"compute_device": "python"})
    assert len(calls) == 1 and calls[0]["execution_mode"] == paths.INFERENCE_PATH
    assert result["execution_path"] == paths.INFERENCE_PATH
    assert "dependency:optimizers/logic_theorem_optimizer/autoencoder_paths.py" in result["source_sha256"]
    receipt = result.pop("receipt_artifact")
    raw = Path(receipt["path"]).read_bytes()
    assert receipt["sha256"] == hashlib.sha256(raw).hexdigest()
    assert json.loads(raw) == result


def test_same_text_with_different_citation_is_not_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(q, "_structural_gates", _failed_structure)
    result = q.qualify_candidate(_candidate(tmp_path), "version", [_sample()], tmp_path / "qualification",
                                heldout_samples=[_sample(section="999")], model_config={"compute_device": "python"})
    assert result["heldout_gate"]["reason"] == "heldout_overlap"
    assert not result["qualified"]
    assert any(todo.get("reason") == "heldout_overlap" for todo in result["repair_todos"])


@pytest.mark.parametrize("changed_file", ["family_qualification.py", "tdfol_parser.py", "legacy_modal.py",
                                         "prover_syntax.py", "canonical_contracts.py"])
def test_producer_changes_abort_before_receipt(tmp_path, monkeypatch, changed_file):
    monkeypatch.setattr(q, "_structural_gates", _failed_structure)
    original = Path.read_bytes
    reads = 0
    def changed(path):
        nonlocal reads
        raw = original(path)
        if path.name == changed_file:
            reads += 1
            if reads > 1:
                return raw + b"\n# concurrent source change\n"
        return raw
    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(q.CandidateQualificationError, match="source changed"):
        q.qualify_candidate(_candidate(tmp_path), "version", [_sample()], tmp_path / "qualification",
                            model_config={"compute_device": "python"})
    assert not (tmp_path / "qualification/qualification.json").exists()


def test_model_evaluation_exception_fails_metrics_in_receipt(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
    monkeypatch.setattr(q, "_structural_gates", _failed_structure)
    def fail(*args, **kwargs):
        raise ValueError("nonfinite candidate output")
    monkeypatch.setattr(AdaptiveModalAutoencoder, "evaluate", fail)
    result = q.qualify_candidate(_candidate(tmp_path), "version", [_sample()], tmp_path / "qualification",
                                model_config={"compute_device": "python"})
    assert result["needs_training"] and not result["qualified"]
    assert "nonfinite candidate output" in result["rows"][0]["metric_gate"]["evaluation_error"]


def test_evaluator_cannot_modify_candidate_before_scoring(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
    monkeypatch.setattr(q, "_structural_gates", _failed_structure)
    original = AdaptiveModalAutoencoder.evaluate
    def mutate(model, *args, **kwargs):
        model.state.feature_embedding_weights["changed"] = [1., 2.]
        return original(model, *args, **kwargs)
    monkeypatch.setattr(AdaptiveModalAutoencoder, "evaluate", mutate)
    with pytest.raises(q.CandidateQualificationError, match="candidate state changed"):
        q.qualify_candidate(_candidate(tmp_path), "version", [_sample()], tmp_path / "qualification",
                            model_config={"compute_device": "python"})


def test_constitution_never_enters_roundtrip_or_lake(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic import autoformal
    def fail(*args, **kwargs):
        pytest.fail("Constitution was passed to compile_span")
    monkeypatch.setattr(autoformal, "compile_span", fail)
    lock, _, _ = q._statement_lock()
    sample = {"title": "US Constitution", "section": "Article I", "text": "All legislative Powers herein granted..."}
    result = q._structural_gates(sample, "constitution", tmp_path, lock, 30)
    assert not result["compiler"]["roundtrip"]
    assert not result["semantic_gate"]["passed"]
    assert not result["lake_gate"]["admitted"]
    assert result["semantic_gate"]["reason"] == "constitution_not_formalized"


def test_deadline_never_rendered_as_minimum(tmp_path):
    lock, _, _ = q._statement_lock()
    rule = {"modality": "O", "actor": "Company A", "action": "submit", "object": "report",
            "temporal": ["within_10_days"], "conditions": [],
            "temporal_records": [{"temporal_kind": "within_duration", "quantity": 10, "value": "10 days"}]}
    result = q._lake_gate(rule, roundtrip_ok=True, output_directory=tmp_path / "lake",
                          timeout_seconds=30, statement_lock=lock)
    assert not result["passed"]
    assert not result["admitted"]
    assert not (tmp_path / "lake").exists()


def test_mixed_minimum_and_deadline_is_not_admitted_by_minimum_only(tmp_path):
    lock, _, _ = q._statement_lock()
    rule = {"temporal_records": [
        {"temporal_kind": "minimum_duration", "quantity": 20, "value": "20 days"},
        {"temporal_kind": "within_duration", "quantity": 10, "value": "10 days"}]}
    result = q._lake_gate(rule, roundtrip_ok=True, output_directory=tmp_path / "lake",
                          timeout_seconds=30, statement_lock=lock)
    assert result["reason"] == "within_duration_not_renderable"
    assert not result["admitted"]


def test_generic_norm_fingerprint_is_not_legal_gate(tmp_path):
    lock, _, _ = q._statement_lock()
    result = q._lake_gate({"modality": "F", "actor": "agency", "action": "disclose", "object": "records"},
                          roundtrip_ok=True, output_directory=tmp_path / "lake",
                          timeout_seconds=30, statement_lock=lock)
    assert result["reason"] == "source_rule_not_renderable"
    assert not result["admitted"]


def test_real_source_minimum_runs_lake_legal(tmp_path):
    if not (Path.home() / ".elan/toolchains/leanprover--lean4---v4.26.0/bin/lake").is_file():
        pytest.skip("qualified Lean toolchain is not installed")
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
    session = AutoformalSession()
    source = "The officer shall retain the file for at least 20 days."
    outcome = compile_span(session, source, "minimum-real-source")
    assert outcome["compiler_status"] == "compiled"
    assert outcome["roundtrip"]
    assert "at least 20 days" in outcome["decompiled"]
    assert "at least days" not in outcome["decompiled"]
    lock, _, _ = q._statement_lock()
    result = q._lake_gate(outcome["rule"], roundtrip_ok=True, output_directory=tmp_path / "lake",
                          timeout_seconds=60, statement_lock=lock)
    assert result["passed"] and result["admitted"]
    assert result["command"] == ["lake", "build", "Legal"]
    assert result["returncode"] == 0
    assert result["formalized"] is False
    assert (tmp_path / "lake/Legal.lean").exists()
    assert "Built Legal" in (tmp_path / "lake/lake.log").read_text()
