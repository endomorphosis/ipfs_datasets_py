"""Frozen paired-head discovery, fair budgets, and no-gold evidence controls."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_hybrid_experiment as subject

ROOT = Path(__file__).resolve().parents[5]
POLICIES = ["source_only", "formal_only", "source_discovery_formal_select", "rrf_formal", "quota_formal"]


def configuration():
    return {"schema": "alignment-hybrid-experiment-config/v1",
            "study_id": "autoformalization-hybrid-development-v1",
            "joint_report": {"path": "artifacts/joint/report.json", "sha256": "a" * 64},
            "policies": list(POLICIES), "top_k": 5, "shortlist": 20, "head_budget": 20,
            "rrf_k": 60, "diversity_lambda": .7, "max_seconds": 180}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def binding(path, workspace):
    return {"path": str(path.relative_to(workspace)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def target(actor="clerk", action="retain", modality="O"):
    return {"rules": [{"actor": actor, "action": action, "modality": modality,
                       "object": "certificate", "conditions": [], "exceptions": [], "temporal": []}]}


@pytest.mark.parametrize("field,value", [
    ("schema", "alignment-hybrid-experiment-config/v99"),
    ("study_id", "sealed-final-study"),
    ("policies", ["source_only", "rrf_formal"]),
    ("policies", list(reversed(POLICIES))),
    ("top_k", True), ("top_k", 0), ("top_k", 11),
    ("shortlist", True), ("shortlist", 4), ("shortlist", 7), ("shortlist", 41),
    ("head_budget", True), ("head_budget", 40),
    ("rrf_k", True), ("rrf_k", 59),
    ("diversity_lambda", True), ("diversity_lambda", float("nan")),
    ("diversity_lambda", -1), ("diversity_lambda", 1.1), ("diversity_lambda", 10**400),
    ("max_seconds", True), ("max_seconds", 0), ("max_seconds", 301), ("max_seconds", 10**400),
])
def test_fixed_controls_reject_wrong_scope_unfair_budgets_and_adaptive_parameters(tmp_path, field, value):
    config = configuration()
    config[field] = value
    if field == "shortlist" and value == 7:
        # Keep head and final budgets equal so only the odd half-quota fails.
        config["head_budget"] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        subject.load_hybrid_config(path)


def test_closed_configuration_binds_exact_parsed_bytes(tmp_path):
    config = configuration()
    raw = (json.dumps(config, indent=3) + "\n").encode()
    path = tmp_path / "config.json"
    path.write_bytes(raw)
    settings, observed = subject.load_hybrid_config(path)
    assert settings == config
    assert observed["sha256"] == hashlib.sha256(raw).hexdigest()
    assert observed["bytes"] == len(raw)
    config["query_gold_routing"] = True
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="closed"):
        subject.load_hybrid_config(path)


def test_configuration_binding_uses_parsed_bytes_when_file_changes_after_read(tmp_path, monkeypatch):
    config = configuration()
    path = tmp_path / "config.json"
    original = json.dumps(config, indent=2).encode()
    path.write_bytes(original)
    changed = {**config, "diversity_lambda": .6}
    changed_bytes = json.dumps(changed, indent=2).encode()
    read = subject._bounded_bytes

    def read_then_change(supplied, limit):
        captured = read(supplied, limit)
        path.write_bytes(changed_bytes)
        return captured

    monkeypatch.setattr(subject, "_bounded_bytes", read_then_change)
    settings, observed = subject.load_hybrid_config(path)
    assert settings == config and json.loads(path.read_bytes()) == changed
    assert observed["sha256"] == hashlib.sha256(original).hexdigest()
    assert observed["sha256"] != hashlib.sha256(changed_bytes).hexdigest()


def test_existing_output_or_foreign_repository_fail_before_artifact_access(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(ValueError, match="executing"):
        subject.run_hybrid_experiment(missing, tmp_path, tmp_path, tmp_path / "new")
    with pytest.raises(ValueError, match="fresh output"):
        subject.run_hybrid_experiment(missing, ROOT, tmp_path, tmp_path)


def test_preloaded_hybrid_helper_origin_must_match_recorded_source(tmp_path, monkeypatch):
    relative = "ipfs_datasets_py/logic/formalization/autoencoder/alignment_hybrid_retrieval.py"
    monkeypatch.setitem(sys.modules, relative[:-3].replace("/", "."),
                        SimpleNamespace(__file__=str(tmp_path / "foreign.py")))
    with pytest.raises(ValueError, match="another tree"):
        subject._verify_origins(ROOT, [{"path": relative}])


def test_pair_ranking_boundary_has_no_query_targets_and_keeps_equal_unique_budgets():
    vectors = [[1., 0.] + [0.] * 382, [.9, .43] + [0.] * 382,
               [0., 1.] + [0.] * 382, [-1., 0.] + [0.] * 382]
    formal_vectors = [vectors[3], vectors[2], vectors[0], vectors[1]]
    candidates = [{"candidate_id": "a", "target": target(), "source_vector": vectors[0], "train_ids": ["train-a"]},
                  {"candidate_id": "b", "target": target("officer", "issue"),
                   "source_vector": vectors[1], "train_ids": ["train-b"]},
                  {"candidate_id": "c", "target": target("custodian", "certify"),
                   "source_vector": vectors[2], "train_ids": ["train-c"]},
                  {"candidate_id": "d", "target": target("commissioner", "inspect"),
                   "source_vector": vectors[3], "train_ids": ["train-d"]}]
    prediction = {facet: {"label": label, "scores": {label: 1.}}
                  for facet, label in (("modality", "O"), ("actor", "clerk"),
                                       ("action", "retain"), ("object", "certificate"))}
    settings = configuration()
    settings.update(top_k=2, shortlist=2, head_budget=2)
    args = (["dev"], [[1., 0.] + [0.] * 382], [[1., 0.] + [0.] * 382], candidates,
            vectors, formal_vectors, [prediction], settings)
    rankings, shortlists, union_rows = subject.rank_hybrid_pair(*args)
    assert list(rankings) == POLICIES and list(shortlists) == POLICIES
    for policy in POLICIES:
        ids = [item["candidate_id"] for item in rankings[policy][0]["retrieved"]]
        assert len(ids) == len(set(ids)) == 2
        pool = [item["candidate_id"] for item in shortlists[policy][0]["retrieved"]]
        assert len(pool) == len(set(pool)) == 2
        assert set(ids) <= set(pool) <= {"a", "b", "c", "d"}
    assert {item["candidate_id"] for item in shortlists["source_only"][0]["retrieved"]} == {"a", "b"}
    assert {item["candidate_id"] for item in shortlists["formal_only"][0]["retrieved"]} == {"c", "d"}
    assert len(union_rows) == 1 and len(union_rows[0]["retrieved"]) == 4
    with pytest.raises(TypeError):
        subject.rank_hybrid_pair(*args, query_targets=[target("executor", "register")])
    with pytest.raises(ValueError):
        subject.rank_hybrid_pair(args[0], args[1], [], *args[3:])


@pytest.fixture
def predecessor_builder(tmp_path):
    pytest.importorskip("torch")
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_experiment import (
        run_projection_experiment,
    )
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_joint_experiment import (
        run_joint_experiment,
    )
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_retrieval_experiment import (
        run_retrieval_experiment,
    )

    config_root = ROOT / "configs/autoencoders"
    base = json.loads((config_root / "alignment_study_development_v1.json").read_text())
    projection = json.loads((config_root / "alignment_projection_development_v1.json").read_text())
    projection.update(shared_dimensions=[384], seeds=[0], negative_weights=[1], steps=2)
    retrieval = json.loads((config_root / "alignment_retrieval_development_v1.json").read_text())
    retrieval.update(top_k=2, shortlist=2)
    joint = json.loads((config_root / "alignment_joint_development_v1.json").read_text())
    joint.update(top_k=2, shortlist=2)
    (tmp_path / "protocol.md").write_text("protected protocol")
    (tmp_path / "provenance.json").write_text("{}")
    base["protected_protocols"] = [binding(tmp_path / "protocol.md", tmp_path)]
    base["corpus"]["provenance"] = [binding(tmp_path / "provenance.json", tmp_path)]

    def row(identity, actor, action, vector, split):
        text = f"The {actor} must {action} the certificate."
        return {"id": identity, "group_id": "group-" + identity, "split": split,
                "source_text": text, "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "embedding": vector, "embedding_sha256": digest(vector), "target": target(actor, action)}

    train = [row("a", "clerk", "retain", [1., 0.] + [0.] * 382, "train"),
             row("b", "officer", "issue", [0., 1.] + [0.] * 382, "train")]
    dev = [row("dev", "executor", "register", [.8, .6] + [0.] * 382, "validation")]
    (tmp_path / "train.json").write_text(json.dumps({"rows": train}))
    base["corpus"]["train"] = binding(tmp_path / "train.json", tmp_path)

    def build(identity, modality="O"):
        dev[0]["target"] = target("executor", "register", modality)
        (tmp_path / "validation.json").write_text(json.dumps({"rows": dev}))
        base["corpus"]["development"] = binding(tmp_path / "validation.json", tmp_path)
        base_path = tmp_path / "base.json"
        base_path.write_text(json.dumps(base))
        projection["study_config"] = binding(base_path, tmp_path)
        projection_path = tmp_path / "projection.json"
        projection_path.write_text(json.dumps(projection))
        run_projection_experiment(projection_path, ROOT, tmp_path, tmp_path / (identity + "-projection"))
        retrieval["projection_report"] = binding(tmp_path / (identity + "-projection") / "report.json", tmp_path)
        retrieval_path = tmp_path / "retrieval.json"
        retrieval_path.write_text(json.dumps(retrieval))
        run_retrieval_experiment(retrieval_path, ROOT, tmp_path, tmp_path / (identity + "-retrieval"))
        joint["retrieval_report"] = binding(tmp_path / (identity + "-retrieval") / "report.json", tmp_path)
        joint_path = tmp_path / "joint.json"
        joint_path.write_text(json.dumps(joint))
        prior = run_joint_experiment(joint_path, ROOT, tmp_path, tmp_path / (identity + "-joint"))
        config = configuration()
        config.update(top_k=2, shortlist=2, head_budget=2,
                      joint_report=binding(tmp_path / (identity + "-joint") / "report.json", tmp_path))
        config_path = tmp_path / (identity + "-hybrid.json")
        config_path.write_text(json.dumps(config))
        return config_path, prior

    return build


def pair_details(pair):
    observed = pair["details"]
    raw = Path(observed["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == observed["sha256"]
    assert len(raw) == observed["bytes"]
    details = json.loads(raw)
    assert details["schema"] == "alignment-hybrid-pair-details/v1" and details["id"] == pair["id"]
    return details


def test_frozen_end_to_end_dev_reference_mutation_preserves_all_discovery_and_selection(
        tmp_path, predecessor_builder, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_experiment,
        alignment_retrieval,
    )

    config_a, prior_a = predecessor_builder("first")

    def forbidden_fit(*args, **kwargs):
        raise AssertionError("hybrid comparison must reuse frozen heads and source predictions")

    monkeypatch.setattr(alignment_retrieval, "fit_facet_probe", forbidden_fit)
    monkeypatch.setattr(alignment_experiment, "_fit_projection", forbidden_fit)
    first = subject.run_hybrid_experiment(config_a, ROOT, tmp_path, tmp_path / "first-hybrid")
    monkeypatch.undo()
    config_b, prior_b = predecessor_builder("second", "F")
    monkeypatch.setattr(alignment_retrieval, "fit_facet_probe", forbidden_fit)
    monkeypatch.setattr(alignment_experiment, "_fit_projection", forbidden_fit)
    second = subject.run_hybrid_experiment(config_b, ROOT, tmp_path, tmp_path / "second-hybrid")
    assert prior_a["probe"]["sha256"] == prior_b["probe"]["sha256"]
    assert prior_a["predictions"]["sha256"] == prior_b["predictions"]["sha256"]
    assert first["status"] == second["status"] == "completed"
    assert first["probe"]["sha256"] == second["probe"]["sha256"]
    assert first["predictions"]["sha256"] == second["predictions"]["sha256"]
    assert len(first["pairs"]) == len(second["pairs"]) == 1
    assert first["raw_control"]["status"] == second["raw_control"]["status"] == "completed"
    a, b = first["pairs"][0], second["pairs"][0]
    da, db = pair_details(a), pair_details(b)
    assert a["id"] == b["id"] == "d384-seed0-neg1"
    for control in ("source_only", "formal_only"):
        assert a["control_replay"][control]["ordering_matches"] == 1
        assert a["control_replay"][control]["selection_trace_matches"] == 1
    for policy in POLICIES:
        ra, rb = da["policies"][policy]["rows"], db["policies"][policy]["rows"]
        assert [row["retrieved"] for row in ra] == [row["retrieved"] for row in rb]
        assert [row["selection_trace"] for row in ra] == [row["selection_trace"] for row in rb]
        assert a["policies"][policy]["summary"] != b["policies"][policy]["summary"]
    assert first["primary_fidelity"] == {"status": "unavailable", "value": None}
    assert first["native_useful_proof_coverage"] == {"status": "unrun", "value": None}
    assert first["qualified"] is first["production_admitted"] is first["sealed_final_test_accessed"] is False
    assert first["resource_scope"]["model_fits"] == 0


def test_corrupted_frozen_prediction_digest_fails_before_new_output(tmp_path, predecessor_builder):
    config_path, prior = predecessor_builder("corruption")
    path = Path(prior["predictions"]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="digest"):
        subject.run_hybrid_experiment(config_path, ROOT, tmp_path, output)
    assert not output.exists()


def test_resealed_cross_generation_pair_accounting_is_rejected(tmp_path, predecessor_builder):
    config_path, prior = predecessor_builder("pairing")
    prior["geometries"][2]["id"] = "d384-seed999-neg1:formal"
    prior["report_sha256"] = digest({k: v for k, v in prior.items() if k != "report_sha256"})
    prior_path = tmp_path / "pairing-joint" / "report.json"
    prior_path.write_text(json.dumps(prior, sort_keys=True, indent=2) + "\n")
    config = json.loads(config_path.read_text())
    config["joint_report"] = binding(prior_path, tmp_path)
    config_path.write_text(json.dumps(config))
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError):
        subject.run_hybrid_experiment(config_path, ROOT, tmp_path, output)
    assert not output.exists()


def test_protected_protocol_drift_fails_before_new_output(tmp_path, predecessor_builder):
    config_path, _ = predecessor_builder("protocol")
    (tmp_path / "protocol.md").write_text("modified protocol")
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="digest"):
        subject.run_hybrid_experiment(config_path, ROOT, tmp_path, output)
    assert not output.exists()


def test_expiry_before_raw_control_and_all_pairs_records_partial_evidence_without_fits(
        tmp_path, predecessor_builder, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_retrieval

    config_path, _ = predecessor_builder("deadline")

    def forbidden_fit(*args, **kwargs):
        raise AssertionError("expired hybrid comparison must not fit a model")

    monkeypatch.setattr(alignment_retrieval, "fit_facet_probe", forbidden_fit)
    readings = iter([0., 1000.])
    monkeypatch.setattr(subject, "time", SimpleNamespace(perf_counter=lambda: next(readings, 1000.)))
    output = tmp_path / "deadline-hybrid"
    report = subject.run_hybrid_experiment(config_path, ROOT, tmp_path, output)
    assert report["status"] == "partial_deadline"
    assert report["raw_control"]["status"] == "unrun_deadline"
    assert [pair["id"] for pair in report["pairs"]] == ["d384-seed0-neg1"]
    assert all(pair["status"] == "unrun_deadline" and "details" not in pair for pair in report["pairs"])
    assert not list(output.glob("pair-*.json"))
    sealed = json.loads((output / "report.json").read_bytes())
    assert sealed["qualified"] is sealed["production_admitted"] is False
    assert sealed["resource_scope"]["model_fits"] == 0
