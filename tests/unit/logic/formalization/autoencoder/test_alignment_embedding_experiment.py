"""Test-only vectors check orchestration; no encoder performance is measured.

The available-lane tests explicitly replace the production-validation boundary
after validating the same records as diagnostic fixtures. Production still
requires actual native evidence. No model, autoencoder, compiler or prover is
loaded here; the only numerical fit is the small real TRAIN-only ridge head.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_embedding_experiment as subject,
)
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_richer_embeddings as embeddings,
)
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_richer_panel as panel_owner,
)
from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_richer_retrieval as retrieval,
)
from ipfs_datasets_py.logic.formalization.autoencoder.alignment_richer_review import (
    prepare_richer_review,
    validate_richer_review_bundle,
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


def configuration():
    return {"schema": "alignment-embedding-experiment-config/v1",
            "study_id": "autoformalization-richer-embedding-development-v1",
            "structure_report": {"path": "structure/report.json", "sha256": "a" * 64},
            "spacy_backend": "local_en_core_web_sm", "gte384_snapshot": "/test-only/no-model/gte-small",
            "gte768_assets": {"manifest": binding(ROOT / ASSET_MANIFEST, ROOT),
                              "model_directory": "/test-only/no-model/gte768",
                              "code_directory": "/test-only/no-code/gte768"}, "max_seconds": 120}


def seal_predecessor(workspace, config, prior):
    prior["report_sha256"] = digest({key: value for key, value in prior.items() if key != "report_sha256"})
    path = workspace / "structure/report.json"
    write_json(path, prior)
    settings = json.loads(config.read_bytes())
    settings["structure_report"] = binding(path, workspace)
    write_json(config, settings)


def replace_panel(workspace, config, prior, panel):
    panel["integrity"] = panel_owner._integrity(panel)
    panel_owner.validate_alignment_richer_panel(panel)
    path = workspace / "structure/panel.json"
    write_json(path, panel)
    prior["panel_binding"] = binding(path, workspace)
    review = prepare_richer_review(panel, {"panel": prior["panel_binding"], "evaluation_role": "exposed_development",
                                          "source_bindings": []})
    review_path = workspace / "structure/review-private.json"
    write_json(review_path, review)
    prior["review_bindings"] = {"full_bundle_private": binding(review_path, workspace)}
    prior["review_preparation_validation"] = validate_richer_review_bundle(review)
    seal_predecessor(workspace, config, prior)


@pytest.fixture
def predecessor(tmp_path):
    """Use the authored public panel, not any cached original corpus or weights."""
    panel = panel_owner.build_alignment_richer_panel()
    protocol = tmp_path / "protocol.md"
    protocol.write_text("test-only protected exposed-development protocol")
    prior = {"schema": "alignment-structure-experiment-report/v1", "status": "completed",
             "source_bindings": [], "protected_protocol_bindings": [binding(protocol, tmp_path)],
             "evaluation_role": "exposed_development", "target_origin": "synthetic_authored_unreviewed",
             **dict.fromkeys(("qualified", "production_admitted", "source_fidelity_established",
                              "sealed_final_test_accessed", "original_validation_accessed",
                              "query_targets_used_in_construction"), False)}
    config = tmp_path / "embedding.json"
    write_json(config, configuration())
    replace_panel(tmp_path, config, prior, panel)
    assert not (tmp_path / "validation.json").exists()
    return tmp_path, config, prior, panel


def fake_lane(inputs, lane_id, *, status="produced"):
    """An orthogonal basis is a nonsemantic fixture, never a model result."""
    dimension = embeddings.DIMENSIONS[lane_id]
    receipts = [embeddings._receipt(row, [1.] + [0.] * (dimension - 1), token_count=2)
                for row in inputs["rows"]]
    if status == "partial":
        assert lane_id == "native384"
        receipts[0] = embeddings._receipt(inputs["rows"][0], None, token_count=513,
                                         status="token_limit_exceeded")
    lane = embeddings._lane(inputs, lane_id, receipts,
                            embeddings._backend("test-only-nonsemantic-fixture", execution_kind="injected_fixture"),
                            status="diagnostic_fixture", model_inference_executed=False,
                            encoder_execution_executed=False)
    lane["status"] = status
    embeddings._seal(lane)
    return lane


def inject_lanes(monkeypatch, *, statuses=None, on_produce=None):
    """Stub native admission only for tests that exercise post-encoder control."""
    actual_validator = embeddings.validate_embedding_lane
    calls = []

    def validate_test_fixture(lane, inputs):
        if lane["status"] in {"produced", "partial"}:
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
        embeddings.validate_richer_embedding_inputs(inputs)
        calls.append({"id": lane_id, "inputs": deepcopy(inputs)})
        status = (statuses or {}).get(lane_id, "produced")
        lane = (embeddings._unavailable(inputs, lane_id, "test-only-no-model", "not executed in test")
                if status == "unavailable" else fake_lane(inputs, lane_id, status=status))
        if on_produce:
            on_produce(lane_id, inputs, lane)
        return lane

    monkeypatch.setattr(embeddings, "validate_embedding_lane", validate_test_fixture)
    monkeypatch.setattr(subject, "_produce_lane", produce)
    return calls


def read_artifact(item):
    path = Path(item["path"])
    raw = path.read_bytes()
    assert item["sha256"] == hashlib.sha256(raw).hexdigest() and item["bytes"] == len(raw)
    return json.loads(raw)


@pytest.mark.parametrize("field,value", [
    ("schema", "wrong"), ("study_id", "sealed-final-study"),
    ("spacy_backend", "heuristic"), ("gte384_snapshot", "relative-model"),
    ("gte384_snapshot", ""), ("gte384_snapshot", True),
    ("max_seconds", True), ("max_seconds", 0), ("max_seconds", 901),
    ("max_seconds", float("nan")), ("max_seconds", float("inf")), ("max_seconds", 10**400),
    ("structure_report", {"path": "report.json", "sha256": "A" * 64}),
    ("structure_report", {"path": "", "sha256": "a" * 64}),
    ("structure_report", {"path": "report.json", "sha256": "a" * 64, "unbound": True}),
    ("gte768_assets", {"manifest": {"path": "manifest.json", "sha256": "a" * 64},
                       "model_directory": "relative", "code_directory": "/code"}),
    ("gte768_assets", {"manifest": {"path": "manifest.json", "sha256": "a" * 64},
                       "model_directory": "/model", "code_directory": "/code", "download": True}),
])
def test_config_rejects_scope_changes_and_closed_bounds(tmp_path, field, value):
    settings = configuration()
    settings[field] = value
    path = tmp_path / "config.json"
    write_json(path, settings)
    with pytest.raises(ValueError):
        subject.load_embedding_config(path)


def test_config_digest_binds_the_exact_bytes_parsed_once(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    original = (json.dumps(configuration(), indent=3) + "\n").encode()
    path.write_bytes(original)
    read = subject._bounded_bytes

    def capture_then_change(supplied, limit):
        raw = read(supplied, limit)
        write_json(path, {**configuration(), "max_seconds": 60})
        return raw

    monkeypatch.setattr(subject, "_bounded_bytes", capture_then_change)
    settings, observed = subject.load_embedding_config(path)
    assert settings == configuration()
    assert observed["sha256"] == hashlib.sha256(original).hexdigest() and observed["bytes"] == len(original)
    monkeypatch.setattr(subject, "_bounded_bytes", read)
    write_json(path, {**configuration(), "query_target_for_encoding": True})
    with pytest.raises(ValueError, match="closed"):
        subject.load_embedding_config(path)
    path.write_text(json.dumps(configuration())[:-1] + ',"max_seconds":1}')
    with pytest.raises(ValueError):
        subject.load_embedding_config(path)


def test_train_only_real_ridge_source_only_rankings_and_bound_artifacts(predecessor, monkeypatch):
    workspace, config, prior, panel = predecessor
    before = {path: path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
    calls = inject_lanes(monkeypatch)
    train = {"sha256:" + row["input_sha256"]: row for row in panel["rows"] if row["split"] == "train"}
    development = {"sha256:" + row["input_sha256"]: row for row in panel["rows"] if row["split"] == "validation"}
    seen_fit, seen_rank, seen_score = [], [], []
    fit, rank, score = retrieval.fit_structural_ridge, retrieval.rank_richer_candidates, retrieval.score_richer_rankings

    def fit_spy(rows, **kwargs):
        assert kwargs == {"dimension": 2048, "seed": 0, "alpha": 1.0}
        assert {row["id"] for row in rows} == set(train) and len(rows) == 16
        assert all(row["target"] == train[row["id"]]["target"] for row in rows)
        assert all(set(row) == {"id", "group_id", "source_vector", "target"} for row in rows)
        seen_fit.append(deepcopy(rows))
        return fit(rows, **kwargs)

    def rank_spy(query, rows, head, **kwargs):
        assert set(query) == {"id", "group_id", "source_vector"}
        assert query["id"] in development and development[query["id"]]["context"]["role"] == "none_required"
        assert {row["id"] for row in rows} == set(train) and kwargs == {"top_k": 5}
        result = rank(query, rows, head, **kwargs)
        seen_rank.append(result["ranking_sha256"])
        return result

    def score_spy(ranked, reference, rows):
        assert ranked["ranking_sha256"] in seen_rank
        assert development[ranked["id"]]["row_kind"] == "positive"
        assert reference == development[ranked["id"]]["target"]
        seen_score.append(ranked["id"])
        return score(ranked, reference, rows)

    monkeypatch.setattr(retrieval, "fit_structural_ridge", fit_spy)
    monkeypatch.setattr(retrieval, "rank_richer_candidates", rank_spy)
    monkeypatch.setattr(retrieval, "score_richer_rankings", score_spy)
    output = workspace / "embedding-run"
    report = subject.run_embedding_experiment(config, ROOT, workspace, output)
    assert len(calls) == len(seen_fit) == report["trained_ridge_heads"] == 3
    assert len(seen_rank) == 48 and len(seen_score) == 24
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert not (workspace / "validation.json").exists()
    assert report["report_sha256"] == digest({key: value for key, value in report.items() if key != "report_sha256"})
    assert json.loads((output / "report.json").read_bytes()) == report
    inputs = read_artifact(report["embedding_input_binding"])
    assert inputs["row_count"] == 34 and inputs["context_unapplied_rows"] == 2
    assert all(call["inputs"] == inputs for call in calls)
    assert all(set(row) == {"id", "input_sha256", "source_text", "source_sha256", "context_role", "context_applied"}
               for row in inputs["rows"])
    exact = {"sha256:" + row["input_sha256"]: row for row in panel["rows"]}
    assert all(row["source_text"] == exact[row["id"]]["source_text"] for row in inputs["rows"])
    context = [row for row in inputs["rows"] if row["context_role"] == "explicit_assumptions"]
    assert context[0]["source_sha256"] == context[1]["source_sha256"] and context[0]["id"] != context[1]["id"]
    for lane, dimension in embeddings.DIMENSIONS.items():
        evidence = read_artifact(report["lane_bindings"][lane])
        assert evidence["backend_evidence"]["execution_kind"] == "injected_fixture"
        assert evidence["model_inference_executed"] is evidence["encoder_execution_executed"] is False
        assert evidence["dimension"] == dimension and len(evidence["receipts"]) == 34
        head = read_artifact(report["ridge_head_bindings"][lane])
        assert head["source_width"] == dimension and head["formal_dimension"] == 2048
        assert head["training_count"] == 16 and head["intercept"] is False
        assert {row["id"] for row in head["training_manifest"]} == set(train)
        evaluation = read_artifact(report["retrieval_evaluation_bindings"][lane])
        assert len(evaluation["rankings"]) == 16 and len(evaluation["posthoc_scores"]) == 8
        assert all(row["ranking"]["query_reference_consumed"] is False for row in evaluation["rankings"])
        for row in evaluation["rankings"]:
            assert set(row["ranking"]["candidate_ids"]) == set(train)
            for policy in ("source_cosine", "structural_ridge"):
                assert len(row["ranking"][policy]["ranked"]) == 5
                assert len(row["ranking"][policy]["full_pool_ranking"]) == 16
        for policy in ("source_cosine", "structural_ridge"):
            summary = report["summaries"][lane]["policies"][policy]
            assert summary["eligible_positive_queries"] == summary["scored_queries"] == summary["ndcg_queries"] == 8
            assert 0 <= summary["mean_graded_facet_ndcg"] <= 1
            conditions = summary["unscoped_qualifier_coverage"]["conditions"]
            assert conditions["eligible_pool_ceiling_mean_identity_recall"] == .75
            assert conditions["eligible_pool_ceiling_occurrence_weighted_identity_recall"] == .8
    assert report["independent_review_status"] == prior["review_preparation_validation"]
    assert report["independent_review_status"]["item_count"] == 34 and report["independent_review_status"]["completed_reviews"] == 0
    assert report["formal_hash_dimension"] == 2048 and report["source_input_dimensions"] == [8, 384, 768]
    for field in ("qualified", "production_admitted", "proof_authority", "source_fidelity_established",
                  "query_targets_used_in_embedding", "query_targets_used_in_fit_or_ranking", "development_used_in_fit",
                  "model_autoencoder_training_executed", "paired_contrastive_training_executed",
                  "leanstral_hidden_states_extracted", "sealed_final_test_accessed", "original_validation_accessed"):
        assert report[field] is False
    assert report["native_useful_proof_coverage"] == {"status": "unrun", "value": None}


def test_dev_reference_mutation_changes_only_posthoc_scores_not_inputs_heads_or_rankings(predecessor, monkeypatch):
    workspace, config, prior, panel = predecessor
    calls = inject_lanes(monkeypatch)
    left = subject.run_embedding_experiment(config, ROOT, workspace, workspace / "before")
    changed = deepcopy(panel)
    row = next(row for row in changed["rows"] if row["split"] == "validation" and row["row_kind"] == "positive"
               and row["target"]["rules"][0]["modality"] == "O")
    row["target"]["rules"][0]["modality"] = "F"
    row["target_sha256"] = digest(row["target"])
    replace_panel(workspace, config, prior, changed)
    right = subject.run_embedding_experiment(config, ROOT, workspace, workspace / "after")
    assert calls[0]["inputs"] == calls[3]["inputs"]
    assert left["embedding_input_binding"]["sha256"] == right["embedding_input_binding"]["sha256"]
    for lane in embeddings.DIMENSIONS:
        assert read_artifact(left["ridge_head_bindings"][lane]) == read_artifact(right["ridge_head_bindings"][lane])
        before = read_artifact(left["retrieval_evaluation_bindings"][lane])
        after = read_artifact(right["retrieval_evaluation_bindings"][lane])
        assert before["rankings"] == after["rankings"]
        assert before["posthoc_scores"] != after["posthoc_scores"]


def test_unavailable_and_diagnostic_fixture_lanes_do_not_fit_or_fabricate_metrics(predecessor, monkeypatch):
    workspace, config, _, _ = predecessor

    def no_fit(*args, **kwargs):
        raise AssertionError("incomplete or unexecuted native lanes must not fit")

    monkeypatch.setattr(retrieval, "fit_structural_ridge", no_fit)
    inject_lanes(monkeypatch, statuses={"legacy8": "unavailable", "native384": "diagnostic_fixture", "native768": "unavailable"})
    report = subject.run_embedding_experiment(config, ROOT, workspace, workspace / "unavailable")
    assert report["trained_ridge_heads"] == 0 and report["ridge_head_bindings"] == report["retrieval_evaluation_bindings"] == {}
    assert report["embedding_receipts_produced"] == {"legacy8": 0, "native384": 34, "native768": 0}
    assert all(summary["status"] == "unavailable_complete_embeddings" and summary["scored_queries"] == 0
               for summary in report["summaries"].values())
    assert read_artifact(report["lane_bindings"]["native384"])["status"] == "diagnostic_fixture"


def test_partial_lane_preserves_failure_receipt_without_training_or_empty_vector_fallback(predecessor, monkeypatch):
    workspace, config, _, _ = predecessor
    inject_lanes(monkeypatch, statuses={"legacy8": "unavailable", "native384": "partial", "native768": "unavailable"})
    report = subject.run_embedding_experiment(config, ROOT, workspace, workspace / "partial")
    lane = read_artifact(report["lane_bindings"]["native384"])
    assert lane["status"] == "partial" and lane["receipts"][0]["embedding"] is None
    assert lane["receipts"][0]["status"] == "token_limit_exceeded"
    assert report["trained_ridge_heads"] == 0 and report["ridge_head_bindings"] == report["retrieval_evaluation_bindings"] == {}


@pytest.mark.parametrize("field,value", [
    ("evaluation_role", "sealed_final"), ("target_origin", "human_adjudicated"),
    ("qualified", True), ("production_admitted", True), ("source_fidelity_established", True),
    ("sealed_final_test_accessed", True), ("original_validation_accessed", True),
    ("query_targets_used_in_construction", True),
])
def test_rehashed_predecessor_cannot_promote_scope_or_authority(predecessor, field, value):
    workspace, config, prior, _ = predecessor
    prior[field] = value
    seal_predecessor(workspace, config, prior)
    output = workspace / "rejected"
    with pytest.raises(ValueError, match="scope"):
        subject.run_embedding_experiment(config, ROOT, workspace, output)
    assert not output.exists()


@pytest.mark.parametrize("field,value", [("completed_reviews", 1), ("item_count", 40), ("qualified", True), ("proof_authority", True)])
def test_rehashed_predecessor_cannot_forge_independent_review_status(predecessor, field, value):
    workspace, config, prior, _ = predecessor
    prior["review_preparation_validation"][field] = value
    seal_predecessor(workspace, config, prior)
    output = workspace / "forged-review"
    with pytest.raises(ValueError, match="review"):
        subject.run_embedding_experiment(config, ROOT, workspace, output)
    assert not output.exists()


@pytest.mark.parametrize("corruption", ["dimension", "receipt_source", "missing_receipt"])
def test_lane_receipt_bounds_and_source_bindings_fail_before_publication(predecessor, monkeypatch, corruption):
    workspace, config, _, _ = predecessor

    def corrupt(lane_id, inputs, lane):
        if lane_id != "legacy8":
            return
        if corruption == "dimension":
            lane["dimension"] = 768
        elif corruption == "receipt_source":
            lane["receipts"][0]["source_sha256"] = "0" * 64
        else:
            lane["receipts"].pop()
        embeddings._seal(lane)

    inject_lanes(monkeypatch, on_produce=corrupt)
    output = workspace / "bad-lane"
    with pytest.raises(ValueError):
        subject.run_embedding_experiment(config, ROOT, workspace, output)
    assert not output.exists()


@pytest.mark.parametrize("changed", ["configuration", "protocol", "panel", "review"])
def test_input_bytes_changed_during_encoding_prevent_publication(predecessor, monkeypatch, changed):
    workspace, config, _, _ = predecessor

    def change_after_produce(lane_id, inputs, lane):
        if lane_id != "native768":
            return
        if changed == "configuration":
            settings = json.loads(config.read_bytes())
            settings["max_seconds"] = 60
            write_json(config, settings)
        else:
            path = {"protocol": workspace / "protocol.md", "panel": workspace / "structure/panel.json",
                    "review": workspace / "structure/review-private.json"}[changed]
            path.write_bytes(path.read_bytes() + b"\n")

    inject_lanes(monkeypatch, statuses=dict.fromkeys(embeddings.DIMENSIONS, "unavailable"), on_produce=change_after_produce)
    output = workspace / "changed"
    with pytest.raises(ValueError, match="changed|digest mismatch"):
        subject.run_embedding_experiment(config, ROOT, workspace, output)
    assert not output.exists()


def test_source_byte_change_detected_without_editing_repository(predecessor, monkeypatch):
    workspace, config, _, _ = predecessor
    observe, calls = subject._sources, []

    def changed_sources(repository, prior):
        observed = observe(repository, prior)
        calls.append(True)
        if len(calls) == 2:
            observed[0]["sha256"] = "0" * 64
        return observed

    monkeypatch.setattr(subject, "_sources", changed_sources)
    inject_lanes(monkeypatch, statuses=dict.fromkeys(embeddings.DIMENSIONS, "unavailable"))
    output = workspace / "source-changed"
    with pytest.raises(ValueError, match="source bytes changed"):
        subject.run_embedding_experiment(config, ROOT, workspace, output)
    assert not output.exists()


def test_loaded_embedding_helper_from_another_tree_is_rejected(predecessor, monkeypatch):
    workspace, config, _, _ = predecessor
    monkeypatch.setattr(embeddings, "__file__", str(workspace / "other-tree.py"))
    output = workspace / "wrong-origin"
    with pytest.raises(ValueError, match="another tree"):
        subject.run_embedding_experiment(config, ROOT, workspace, output)
    assert not output.exists()


def test_stale_predecessor_file_digest_is_rejected(predecessor):
    workspace, config, _, _ = predecessor
    path = workspace / "structure/report.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        subject.run_embedding_experiment(config, ROOT, workspace, workspace / "stale")
    assert not (workspace / "stale").exists()


def test_fresh_output_required_and_pre_first_lane_deadline_creates_no_outputs(predecessor, monkeypatch):
    workspace, config, _, _ = predecessor
    output = workspace / "existing"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("preserve")
    with pytest.raises(ValueError, match="fresh"):
        subject.run_embedding_experiment(config, ROOT, workspace, output)
    assert sentinel.read_text() == "preserve"
    ticks = iter((0., 1000.))
    monkeypatch.setattr(subject, "time", SimpleNamespace(perf_counter=lambda: next(ticks, 1000.)))

    def no_production(*args, **kwargs):
        raise AssertionError("expired cooperative deadline must precede first encoder")

    monkeypatch.setattr(subject, "_produce_lane", no_production)
    with pytest.raises(ValueError, match="deadline"):
        subject.run_embedding_experiment(config, ROOT, workspace, workspace / "expired")
    assert not (workspace / "expired").exists()
