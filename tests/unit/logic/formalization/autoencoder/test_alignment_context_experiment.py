"""Exercise context orchestration with truthful nonsemantic diagnostic vectors.

Only the test's saved-native admission boundary is replaced. Frozen production
validators still reject fixture vectors as native evidence; the new context and
assay validators run normally, retaining diagnostic labels and false authority.
No model, parser, training routine, retrieval scorer or prover executes here.
"""
from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import alignment_context_embeddings as context
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_context_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_richer_embeddings as embeddings,
)
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_richer_panel as panel_owner
from ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_review import (
    prepare_richer_review,
    validate_richer_review_bundle,
)
from ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_review_admission import (
    admit_richer_reviews,
    validate_richer_review_admission,
)

ROOT = Path(__file__).resolve().parents[5]
ASSET_MANIFEST = "configs/autoencoders/gte_multilingual_local_assets_v1.json"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def binding(path, root):
    return {"path": str(path.relative_to(root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))


def seal_report(value):
    value["report_sha256"] = digest({k: v for k, v in value.items() if k != "report_sha256"})
    return value


def configuration():
    return {"schema": subject.CONFIG_SCHEMA, "study_id": "autoformalization-context-development-v1",
            "embedding_report": {"path": "baseline/report.json", "sha256": "a" * 64},
            "review_admission_report": {"path": "review/report_private.json", "sha256": "b" * 64},
            "spacy_backend": "local_en_core_web_sm", "gte384_snapshot": "/fixture/no-model/gte-small",
            "gte768_assets": {"manifest": binding(ROOT / ASSET_MANIFEST, ROOT),
                              "model_directory": "/fixture/no-model/gte768",
                              "code_directory": "/fixture/no-code/gte768"}, "max_seconds": 120}


def basis(text, width):
    """A text hash chooses a basis vector; this has no semantic interpretation."""
    slot = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16) % 8
    return [float(i == slot) for i in range(width)]


def diagnostic_lane(inputs, lane_id, *, unavailable=False, partial=False):
    if unavailable:
        return embeddings._unavailable(inputs, lane_id, "test-only-no-model", "not executed in test")
    receipts = [embeddings._receipt(row, basis(row["source_text"], embeddings.DIMENSIONS[lane_id]), token_count=2)
                for row in inputs["rows"]]
    if partial:
        assert lane_id == "native384"
        receipts[0] = embeddings._receipt(inputs["rows"][0], None, token_count=513,
                                         status="token_limit_exceeded")
    return embeddings._lane(inputs, lane_id, receipts,
                            embeddings._backend("test-only-nonsemantic", execution_kind="injected_fixture"),
                            status="diagnostic_fixture", model_inference_executed=False,
                            encoder_execution_executed=False)


def make_predecessor(workspace, panel=None):
    """Bind an actual blank review packet and synthetic source-only receipts."""
    workspace.mkdir(parents=True, exist_ok=True)
    panel = deepcopy(panel or panel_owner.build_alignment_richer_panel())
    panel_owner.validate_alignment_richer_panel(panel)
    settings = configuration()
    protocol = workspace / "protocol.md"
    protocol.write_text("test-only exposed development protocol")
    panel_path = workspace / "baseline/panel.json"
    write_json(panel_path, panel)
    bundle = prepare_richer_review(panel, {"panel": binding(panel_path, workspace),
                                          "evaluation_role": "exposed_development", "source_bindings": []})
    bundle_path = workspace / "review/bundle_private.json"
    write_json(bundle_path, bundle)
    preparation = validate_richer_review_bundle(bundle)
    receipt = admit_richer_reviews(bundle, [])
    review = {"schema": "alignment-richer-review-admission-artifact/v1", "status": "pending",
              "evaluation_role": "exposed_development", "submission_count": 0, "submission_bindings": [],
              "completed_independent_reviews": 0, "reviewer_identity_authenticated": False,
              "source_author_independence_authenticated": False, "source_bindings": [],
              "bundle_binding": binding(bundle_path, workspace), "preparation_validation": preparation,
              "admission_validation": validate_richer_review_admission(receipt, bundle, []), "receipt": receipt,
              **dict.fromkeys(("qualified", "production_admitted", "source_semantics_verified", "proof_authority",
                               "original_validation_accessed", "sealed_final_test_accessed"), False)}
    review_path = workspace / "review/report_private.json"
    write_json(review_path, seal_report(review))
    raw_inputs = embeddings.prepare_richer_embedding_inputs(panel)
    raw_path = workspace / "baseline/embedding_inputs.json"
    write_json(raw_path, raw_inputs)
    lanes = {}
    for lane_id in subject.LANES:
        lane = diagnostic_lane(raw_inputs, lane_id)
        # Deliberately needs a TEST-ONLY native admission stub below. Public
        # production validation correctly rejects this invented status claim.
        lane["status"] = "produced"
        embeddings._seal(lane)
        path = workspace / "baseline" / (lane_id + ".json")
        write_json(path, lane)
        lanes[lane_id] = binding(path, workspace)
    prior = {"schema": "alignment-embedding-experiment-report/v1", "status": "completed",
             "evaluation_role": "exposed_development", "source_bindings": [],
             "protected_protocol_bindings": [binding(protocol, workspace)], "configuration": settings,
             "panel_binding": binding(panel_path, workspace), "independent_review_bundle_binding": review["bundle_binding"],
             "independent_review_status": preparation, "embedding_input_binding": binding(raw_path, workspace),
             "lane_bindings": lanes,
             **dict.fromkeys(("qualified", "production_admitted", "source_fidelity_established", "proof_authority",
                              "original_validation_accessed", "sealed_final_test_accessed", "context_applied_to_embeddings",
                              "model_autoencoder_training_executed", "query_targets_used_in_embedding"), False)}
    prior_path = workspace / "baseline/report.json"
    write_json(prior_path, seal_report(prior))
    settings["embedding_report"] = binding(prior_path, workspace)
    settings["review_admission_report"] = binding(review_path, workspace)
    config = workspace / "context.json"
    write_json(config, settings)
    return workspace, config, prior, review, panel


@pytest.fixture
def predecessor(tmp_path):
    # A pytest test-function parent includes a forbidden input-scope token.
    workspace = Path(tempfile.mkdtemp(prefix="context-fixture-", dir=tmp_path.parent))
    try:
        yield make_predecessor(workspace)
    finally:
        shutil.rmtree(workspace)


def inject_lanes(monkeypatch, *, unavailable=None, partial=None, on_produce=None):
    actual_validator = embeddings.validate_embedding_lane
    calls = []

    def validate_saved_test_fixture(lane, inputs):
        if lane["status"] == "produced":
            assert lane["backend_evidence"]["execution_kind"] == "injected_fixture"
            assert lane["backend_evidence"]["production_evidence"] is None
            assert lane["model_inference_executed"] is lane["encoder_execution_executed"] is False
            diagnostic = deepcopy(lane)
            diagnostic["status"] = "diagnostic_fixture"
            embeddings._seal(diagnostic)
            return actual_validator(diagnostic, inputs)
        return actual_validator(lane, inputs)

    def produce(lane_id, inputs, settings, repository):
        assert repository == ROOT
        context.validate_context_embedding_inputs(inputs)
        calls.append({"lane_id": lane_id, "inputs": deepcopy(inputs)})
        transport = context.prepare_context_transport(inputs)
        inner = diagnostic_lane(transport, lane_id, unavailable=lane_id == unavailable, partial=lane_id == partial)
        result = context._wrap_context_lane(inputs, inner)
        if on_produce:
            on_produce(lane_id, inputs, result)
        return result

    monkeypatch.setattr(embeddings, "validate_embedding_lane", validate_saved_test_fixture)
    monkeypatch.setattr(subject, "_produce_lane", produce)
    return calls


def run(fixture, output_name="out"):
    workspace, config, *_ = fixture
    return subject.run_context_experiment(config, ROOT, workspace, workspace / output_name)


def read_artifact(item):
    path = Path(item["path"])
    raw = path.read_bytes()
    assert item["sha256"] == hashlib.sha256(raw).hexdigest() and item["bytes"] == len(raw)
    return json.loads(raw)


def rebind_report(fixture, key, report):
    workspace, config, *_ = fixture
    settings = json.loads(config.read_bytes())
    path = workspace / settings[key]["path"]
    write_json(path, seal_report(report))
    settings[key] = binding(path, workspace)
    write_json(config, settings)


@pytest.mark.parametrize("field,value", [
    ("schema", "wrong"), ("study_id", "sealed-final-study"), ("spacy_backend", "heuristic"),
    ("gte384_snapshot", "relative"), ("gte384_snapshot", ""), ("gte384_snapshot", True),
    ("max_seconds", True), ("max_seconds", 0), ("max_seconds", 901),
    ("max_seconds", float("nan")), ("max_seconds", float("inf")), ("max_seconds", 10**400),
    ("embedding_report", {"path": "report.json", "sha256": "A" * 64}),
    ("embedding_report", {"path": "sealed/report.json", "sha256": "a" * 64}),
    ("review_admission_report", {"path": "report.json", "sha256": "a" * 64, "extra": True}),
    ("gte768_assets", {"manifest": {"path": "manifest.json", "sha256": "a" * 64},
                       "model_directory": "/model", "code_directory": "relative"}),
])
def test_closed_config_rejects_scope_and_bounds(tmp_path, field, value):
    settings = configuration()
    settings[field] = value
    path = tmp_path / "config.json"
    write_json(path, settings)
    with pytest.raises(ValueError):
        subject.load_context_config(path)


def test_config_binding_is_exact_parsed_bytes_and_config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    original = (json.dumps(configuration(), indent=2) + "\n").encode()
    path.write_bytes(original)
    read = subject._bounded_bytes

    def capture_then_change(supplied, limit):
        raw = read(supplied, limit)
        write_json(path, {**configuration(), "max_seconds": 60})
        return raw

    monkeypatch.setattr(subject, "_bounded_bytes", capture_then_change)
    settings, observed = subject.load_context_config(path)
    assert settings == configuration()
    assert observed == {"path": str(path), "sha256": hashlib.sha256(original).hexdigest(), "bytes": len(original)}
    monkeypatch.setattr(subject, "_bounded_bytes", read)
    write_json(path, {**configuration(), "authored_reference_for_encoding": True})
    with pytest.raises(ValueError, match="closed"):
        subject.load_context_config(path)
    path.write_text(json.dumps(configuration())[:-1] + ',"max_seconds":1}')
    with pytest.raises(ValueError):
        subject.load_context_config(path)


def test_real_context_and_assay_validation_preserves_blinding_and_scope(predecessor, monkeypatch):
    workspace, _, _, _, panel = predecessor
    before = {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    calls = inject_lanes(monkeypatch)
    report = run(predecessor)
    assert [call["lane_id"] for call in calls] == list(subject.LANES)
    inputs = read_artifact(report["context_input_binding"])
    assert len(inputs["rows"]) == 68 and inputs["original_row_count"] == 34
    assert sum(row["context_forwarded"] for row in inputs["rows"]) == 2
    originals = {row["input_sha256"]: row for row in panel["rows"]}
    for row in inputs["rows"]:
        original = originals[row["original_input_sha256"]]
        encoded = json.loads(row["encoder_text"])
        assert set(encoded) == {"schema", "source", "assumptions"}
        assert encoded["source"] == {"role": "source", "text": original["source_text"]}
        assert set(encoded["assumptions"]) == {"role", "text", "bindings"}
        assert encoded["assumptions"]["role"] == "declared_assumptions"
        assert original["id"] not in row["encoder_text"]
        assert row["source_sha256"] == original["source_sha256"]
        assert row["context_semantics_applied"] is False
        expected = original["context"] if row["context_forwarded"] else {"text": "", "bindings": {}}
        assert encoded["assumptions"]["text"] == expected["text"]
        assert encoded["assumptions"]["bindings"] == expected["bindings"]
    assert all(call["inputs"] == inputs for call in calls)
    assert report["raw_source_receipts_reused"] == 102 and report["new_input_count_per_lane"] == 68
    assert report["embedding_receipts_produced"] == dict.fromkeys(subject.LANES, 68)
    assert report["report_sha256"] == digest({k: v for k, v in report.items() if k != "report_sha256"})
    for lane_id in subject.LANES:
        lane = read_artifact(report["context_lane_bindings"][lane_id])
        assert lane["status"] == "diagnostic_fixture"
        assert lane["model_inference_executed"] is lane["encoder_execution_executed"] is False
        assert lane["dimension"] == embeddings.DIMENSIONS[lane_id]
        assert lane["transport_lane"]["backend_evidence"]["execution_kind"] == "injected_fixture"
        assay = read_artifact(report["assay_bindings"][lane_id])
        assert assay["status"] == "complete" and assay["evidence_scope"] == "diagnostic_fixture"
        assert assay["native_receipt_evidence_available"] is False
        assert assay["summaries"]["none_required"]["comparisons"]["declared_context"]["exact_vector_values_equal_count"] == 32
        assert len(assay["context_pairs"]) == 1
        assert assay["qualified"] is assay["proof_authority"] is False
    assert report["context_semantics_applied"] is report["source_fidelity_established"] is report["qualified"] is False
    assert report["ridge_training_executed"] is report["query_generation_executed"] is False
    assert report["independent_review_status"]["status_counts"]["pending"] == 34
    assert report["native_useful_proof_coverage"] == {"status": "unrun", "value": None}
    assert all(p.read_bytes() == raw for p, raw in before.items())


def test_authored_target_mutation_cannot_change_inputs_vectors_or_assays(predecessor, monkeypatch):
    workspace, _, _, _, panel = predecessor
    inject_lanes(monkeypatch)
    first = run(predecessor)
    changed = deepcopy(panel)
    row = next(row for row in changed["rows"] if row["split"] == "validation" and row["row_kind"] == "positive")
    row["target"]["rules"][0]["actor"] = "custodian" if row["target"]["rules"][0]["actor"] != "custodian" else "clerk"
    row["target_sha256"] = panel_owner._digest(row["target"])
    changed["integrity"] = panel_owner._integrity(changed)
    second_fixture = make_predecessor(workspace / "changed", changed)
    second = run(second_fixture)
    assert read_artifact(first["context_input_binding"]) == read_artifact(second["context_input_binding"])
    for lane_id in subject.LANES:
        assert read_artifact(first["context_lane_bindings"][lane_id]) == read_artifact(second["context_lane_bindings"][lane_id])
        assert read_artifact(first["assay_bindings"][lane_id]) == read_artifact(second["assay_bindings"][lane_id])


@pytest.mark.parametrize("field,value", [
    ("status", "agreed_multiple_reviews"), ("submission_count", 1), ("completed_independent_reviews", 1),
    ("reviewer_identity_authenticated", True), ("source_author_independence_authenticated", True),
])
def test_review_generation_cannot_acquire_authority_by_resealing(predecessor, monkeypatch, field, value):
    workspace, _, _, review, _ = predecessor
    calls = inject_lanes(monkeypatch)
    review[field] = value
    rebind_report(predecessor, "review_admission_report", review)
    with pytest.raises(ValueError, match="pending review"):
        run(predecessor)
    assert calls == [] and not (workspace / "out").exists()


def test_resealed_review_receipt_must_replay_real_blank_bundle(predecessor, monkeypatch):
    workspace, _, _, review, _ = predecessor
    calls = inject_lanes(monkeypatch)
    review["admission_validation"]["status_counts"]["pending"] = 0
    rebind_report(predecessor, "review_admission_report", review)
    with pytest.raises(ValueError, match="review status"):
        run(predecessor)
    assert calls == [] and not (workspace / "out").exists()


@pytest.mark.parametrize("field", ["context_applied_to_embeddings", "model_autoencoder_training_executed", "query_targets_used_in_embedding"])
def test_raw_baseline_scope_is_not_inferred_from_report_hash(predecessor, monkeypatch, field):
    workspace, _, prior, _, _ = predecessor
    calls = inject_lanes(monkeypatch)
    prior[field] = True
    rebind_report(predecessor, "embedding_report", prior)
    with pytest.raises(ValueError, match="baseline scope"):
        run(predecessor)
    assert calls == [] and not (workspace / "out").exists()


@pytest.mark.parametrize("changed", ["config", "protocol", "panel", "bundle", "raw_lane", "review_report"])
def test_input_changes_during_inference_prevent_publication(predecessor, monkeypatch, changed):
    workspace, config, prior, review, _ = predecessor

    def mutate(lane_id, inputs, result):
        if lane_id != "native768":
            return
        paths = {"config": config, "protocol": workspace / "protocol.md",
                 "panel": workspace / prior["panel_binding"]["path"],
                 "bundle": workspace / review["bundle_binding"]["path"],
                 "raw_lane": workspace / prior["lane_bindings"]["legacy8"]["path"],
                 "review_report": workspace / "review/report_private.json"}
        with paths[changed].open("ab") as stream:
            stream.write(b"\n")

    inject_lanes(monkeypatch, on_produce=mutate)
    with pytest.raises(ValueError, match="changed|digest|SHA256"):
        run(predecessor)
    assert not (workspace / "out").exists()


def test_source_generation_drift_prevents_publication(predecessor, monkeypatch):
    workspace, *_ = predecessor
    inject_lanes(monkeypatch)
    actual, count = subject._sources, 0

    def altered(*args):
        nonlocal count
        count += 1
        result = actual(*args)
        if count == 2:
            result[0]["sha256"] = "0" * 64
        return result

    monkeypatch.setattr(subject, "_sources", altered)
    with pytest.raises(ValueError, match="executing sources changed"):
        run(predecessor)
    assert count == 2 and not (workspace / "out").exists()


def test_unavailable_lane_preserves_null_measurements(predecessor, monkeypatch):
    inject_lanes(monkeypatch, unavailable="native768")
    report = run(predecessor)
    assay = read_artifact(report["assay_bindings"]["native768"])
    assert report["embedding_receipts_produced"]["native768"] == 0
    assert assay["status"] == "unavailable" and assay["native_receipt_evidence_available"] is False
    assert all(row["comparisons"]["declared_context"]["status"] == "unavailable" for row in assay["records"])
    assert all(value is None for value in assay["summaries"]["all_inputs"]["comparisons"]["declared_context"]["means"].values())
    assert report["backend_comparability"]["native768"]["status"] == "unavailable"
    assert report["backend_comparability"]["native768"]["compared_identity_sha256"] is None


@pytest.mark.parametrize("field,value", [
    ("profile_id", "different-pooling-profile"),
    ("runtime_versions", {"fixture_runtime": "changed"}),
    ("asset_evidence", {"fixture_asset_sha256": "0" * 64}),
])
def test_backend_profile_drift_is_rejected_before_comparing_vectors(predecessor, monkeypatch, field, value):
    workspace, *_ = predecessor

    def drift(lane_id, inputs, result):
        if lane_id == "native384":
            inner = result["transport_lane"]
            inner["backend_evidence"][field] = value
            embeddings._seal(inner)
            rebuilt = context._wrap_context_lane(inputs, inner)
            result.clear()
            result.update(rebuilt)

    calls = inject_lanes(monkeypatch, on_produce=drift)
    with pytest.raises(ValueError, match="backend profiles, assets or runtimes differ"):
        run(predecessor)
    assert [call["lane_id"] for call in calls] == ["legacy8", "native384"]
    assert not (workspace / "out").exists()


def test_partial_lane_records_rejection_without_synthetic_replacement(predecessor, monkeypatch):
    inject_lanes(monkeypatch, partial="native384")
    report = run(predecessor)
    lane = read_artifact(report["context_lane_bindings"]["native384"])
    assay = read_artifact(report["assay_bindings"]["native384"])
    assert sum(row["embedding"] is None for row in lane["receipts"]) == 1
    assert assay["status"] == "partial"
    summary = assay["summaries"]["all_inputs"]["comparisons"]["declared_context"]
    assert summary["eligible_count"] == 33 and summary["unavailable_count"] == 1


def test_no_model_stack_training_or_source_reencoding_is_needed(predecessor, monkeypatch):
    inject_lanes(monkeypatch)
    actual_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "transformers", "numpy", "spacy", "safetensors", "sentence_transformers"}:
            raise AssertionError("optional model stack imported")
        return actual_import(name, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("native inference executed")

    monkeypatch.setattr(builtins, "__import__", guarded)
    for name in ("run_spacy8", "run_gte384", "run_gte768"):
        monkeypatch.setattr(embeddings, name, forbidden)
    report = run(predecessor)
    assert report["resource_scope"]["raw_baseline_model_inference_repeated"] is False
    assert report["model_autoencoder_training_executed"] is report["ridge_training_executed"] is False


def test_saved_fixture_native_status_requires_test_only_validation_stub(predecessor):
    workspace, _, prior, _, _ = predecessor
    inputs = json.loads((workspace / prior["embedding_input_binding"]["path"]).read_bytes())
    for lane_id in subject.LANES:
        lane = json.loads((workspace / prior["lane_bindings"][lane_id]["path"]).read_bytes())
        assert lane["backend_evidence"]["execution_kind"] == "injected_fixture"
        with pytest.raises(ValueError):
            embeddings.validate_embedding_lane(lane, inputs)


def test_deadline_before_first_lane_has_no_artifact_output(predecessor, monkeypatch):
    workspace, *_ = predecessor
    calls = inject_lanes(monkeypatch)
    ticks = iter([0.0, 1000.0])
    monkeypatch.setattr(subject, "time", SimpleNamespace(perf_counter=lambda: next(ticks, 1000.0)))
    with pytest.raises(ValueError, match="deadline exceeded"):
        run(predecessor)
    assert calls == [] and not (workspace / "out").exists()


def test_fresh_output_repository_and_loaded_owner_boundaries(predecessor, monkeypatch):
    workspace, config, *_ = predecessor
    calls = inject_lanes(monkeypatch)
    with pytest.raises(ValueError, match="executing context package"):
        subject.run_context_experiment(config, workspace, workspace, workspace / "out")
    (workspace / "out").mkdir()
    with pytest.raises(ValueError, match="fresh output"):
        run(predecessor)
    (workspace / "out").rmdir()
    monkeypatch.setattr(context, "__file__", str(workspace / "foreign_context.py"))
    with pytest.raises(ValueError, match="another tree"):
        run(predecessor)
    assert calls == [] and not (workspace / "out").exists()


def test_cli_reports_bound_artifact_and_failure(predecessor, monkeypatch, capsys):
    workspace, config, *_ = predecessor
    inject_lanes(monkeypatch)
    path = ROOT / "scripts/ops/legal_ir/run_alignment_context_experiment.py"
    spec = importlib.util.spec_from_file_location("context_experiment_cli_fixture", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    argv = ["--config", str(config), "--workspace-root", str(workspace), "--output-directory", str(workspace / "out")]
    assert cli.main(argv) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["qualified"] is False and printed["embedding_receipts_produced"] == dict.fromkeys(subject.LANES, 68)
    assert cli.main(argv) == 2
    failed = json.loads(capsys.readouterr().err)
    assert failed["qualified"] is False and failed["status"] == "failed"
