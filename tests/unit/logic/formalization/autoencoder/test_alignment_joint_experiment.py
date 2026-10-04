"""Frozen-selector integration, source-only boundaries, and evidence integrity."""
from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_joint_experiment as subject

ROOT = Path(__file__).resolve().parents[5]


def configuration():
    return {
        "schema": "alignment-joint-experiment-config/v1",
        "study_id": "autoformalization-joint-development-v1",
        "retrieval_report": {"path": "artifacts/retrieval/report.json", "sha256": "a" * 64},
        "policies": ["mmr", "hard_joint", "soft_joint"],
        "top_k": 5,
        "shortlist": 20,
        "diversity_lambda": .7,
        "max_seconds": 180,
    }


def target(actor="clerk", action="retain", modality="O"):
    return {"rules": [{"actor": actor, "action": action, "modality": modality,
                       "object": "certificate", "conditions": [], "exceptions": [], "temporal": []}]}


def binding(path, workspace):
    return {"path": str(path.relative_to(workspace)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def canonical_digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def rewrite_report(path, report):
    report["report_sha256"] = canonical_digest({k: v for k, v in report.items() if k != "report_sha256"})
    path.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")


@pytest.mark.parametrize("field,value", [
    ("schema", "alignment-joint-experiment-config/v99"),
    ("study_id", "sealed-final-study"),
    ("policies", ["hard_joint", "soft_joint"]),
    ("policies", ["mmr", "soft_joint", "hard_joint"]),
    ("top_k", True), ("top_k", 0), ("top_k", 11),
    ("shortlist", 4), ("shortlist", True), ("shortlist", 41),
    ("diversity_lambda", True), ("diversity_lambda", -1),
    ("diversity_lambda", float("nan")), ("diversity_lambda", 1.1),
    ("max_seconds", True), ("max_seconds", 0), ("max_seconds", 301),
    ("max_seconds", 10 ** 400), ("diversity_lambda", 10 ** 400),
])
def test_closed_fixed_controls_reject_relabeling_and_invalid_budgets(tmp_path, field, value):
    config = configuration()
    config[field] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        subject.load_joint_config(path)


def test_configuration_identity_binds_exact_parsed_bytes_and_rejects_unknown_fields(tmp_path):
    config = configuration()
    raw = (json.dumps(config, indent=3) + "\n").encode()
    path = tmp_path / "config.json"
    path.write_bytes(raw)
    value, observed = subject.load_joint_config(path)
    assert value == config
    assert observed["sha256"] == hashlib.sha256(raw).hexdigest()
    assert observed["bytes"] == len(raw)
    config["query_gold"] = target()
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="closed"):
        subject.load_joint_config(path)


def test_existing_output_and_foreign_repository_fail_before_artifact_or_numerical_access(tmp_path):
    missing_config = tmp_path / "missing.json"
    with pytest.raises(ValueError, match="executing"):
        subject.run_joint_experiment(missing_config, tmp_path, tmp_path, tmp_path / "new")
    with pytest.raises(ValueError, match="fresh output"):
        subject.run_joint_experiment(missing_config, ROOT, tmp_path, tmp_path)


def test_preloaded_joint_module_origin_must_match_recorded_source(tmp_path, monkeypatch):
    relative = "ipfs_datasets_py/logic/formalization/autoencoder/alignment_joint_retrieval.py"
    monkeypatch.setitem(sys.modules, relative[:-3].replace("/", "."),
                        SimpleNamespace(__file__=str(tmp_path / "foreign.py")))
    with pytest.raises(ValueError, match="another tree"):
        subject._verify_origins(ROOT, [{"path": relative}])


def test_ranking_boundary_forwards_only_geometry_training_candidates_and_predictions(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_joint_retrieval,
        alignment_retrieval,
    )

    predicted = {facet: {"label": label, "scores": {label: 1.}}
                 for facet, label in (("modality", "O"), ("actor", "clerk"),
                                      ("action", "retain"), ("object", "certificate"))}
    calls = []
    frozen_shortlist = [{"candidate_id": "candidate", "cosine_similarity": 1.}]

    def result(identity, kind):
        return {"id": identity, "policy": kind,
                "retrieved": [{"candidate_id": "candidate", "cosine_similarity": 1.,
                               "selection_score": 1., "marginal_predicted_coverage": 0.}],
                "trace": {"shortlist": deepcopy(frozen_shortlist), "shortlist_count": 1,
                          "candidate_count": 1, "query_target_consumed": False, "qualified": False}}

    def mmr(identity, query, candidates, **kwargs):
        assert kwargs["policy"] == "mmr" and "query_target" not in kwargs
        assert kwargs.get("predicted_facets") is None
        calls.append("mmr")
        return result(identity, "mmr")

    def joint(identity, query, candidates, **kwargs):
        assert kwargs["variant"] in ("hard_joint", "soft_joint")
        assert kwargs["predicted_facets"] == predicted
        assert "query_target" not in kwargs and "query_group" not in kwargs
        calls.append(kwargs["variant"])
        return result(identity, kwargs["variant"])

    monkeypatch.setattr(alignment_retrieval, "rerank_candidates", mmr)
    monkeypatch.setattr(alignment_joint_retrieval, "rerank_joint_candidates", joint)
    candidate = {"candidate_id": "candidate", "target": target(), "train_ids": ["training"],
                 "source_vector": [1.] + [0.] * 383}
    settings = {"policies": ["mmr", "hard_joint", "soft_joint"], "top_k": 1,
                "shortlist": 1, "diversity_lambda": .7}
    rankings, shortlists = subject.rank_joint_geometry(["dev"], [[1.] + [0.] * 383],
        [candidate], [[1.] + [0.] * 383], [predicted], settings)
    assert calls == settings["policies"]
    assert set(rankings) == set(settings["policies"])
    assert shortlists == [{"id": "dev", "retrieved": frozen_shortlist}]


@pytest.fixture
def predecessor_builder(tmp_path):
    pytest.importorskip("torch")
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_experiment import (
        run_projection_experiment,
    )
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_retrieval_experiment import (
        run_retrieval_experiment,
    )

    base = json.loads((ROOT / "configs/autoencoders/alignment_study_development_v1.json").read_text())
    projection = json.loads((ROOT / "configs/autoencoders/alignment_projection_development_v1.json").read_text())
    projection.update(shared_dimensions=[384], seeds=[0], negative_weights=[1], steps=2)
    retrieval = json.loads((ROOT / "configs/autoencoders/alignment_retrieval_development_v1.json").read_text())
    retrieval.update(top_k=2, shortlist=2)
    (tmp_path / "protocol.md").write_text("protected protocol")
    (tmp_path / "provenance.json").write_text("{}")
    base["protected_protocols"] = [binding(tmp_path / "protocol.md", tmp_path)]
    base["corpus"]["provenance"] = [binding(tmp_path / "provenance.json", tmp_path)]

    def source_row(identity, actor, action, vector, split):
        text = f"The {actor} must {action} the certificate."
        return {"id": identity, "group_id": "group-" + identity, "split": split,
                "source_text": text, "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "embedding": vector, "embedding_sha256": canonical_digest(vector),
                "target": target(actor, action)}

    training = [source_row("a", "clerk", "retain", [1., 0.] + [0.] * 382, "train"),
                source_row("b", "officer", "issue", [0., 1.] + [0.] * 382, "train")]
    development = [source_row("dev", "executor", "register", [.8, .6] + [0.] * 382, "validation")]
    (tmp_path / "train.json").write_text(json.dumps({"rows": training}))
    base["corpus"]["train"] = binding(tmp_path / "train.json", tmp_path)

    def build(identity, modality="O"):
        development[0]["target"] = target("executor", "register", modality)
        (tmp_path / "validation.json").write_text(json.dumps({"rows": development}))
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
        report = run_retrieval_experiment(retrieval_path, ROOT, tmp_path, tmp_path / (identity + "-retrieval"))
        config = configuration()
        config.update(top_k=2, shortlist=2,
                      retrieval_report=binding(tmp_path / (identity + "-retrieval") / "report.json", tmp_path))
        config_path = tmp_path / (identity + "-joint.json")
        config_path.write_text(json.dumps(config))
        return config_path, report

    return build


def details(geometry):
    bound = geometry["details"]
    raw = Path(bound["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == bound["sha256"]
    value = json.loads(raw)
    assert value["schema"] == "alignment-joint-geometry-details/v1"
    assert value["id"] == geometry["id"] and value["family"] == geometry["family"]
    return value


def test_frozen_end_to_end_reference_mutation_preserves_predictions_selectors_and_mmr_replay(
        tmp_path, predecessor_builder, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_retrieval

    first_config, first_prior = predecessor_builder("first")
    def forbidden_fit(*args, **kwargs):
        raise AssertionError("joint selector comparison must reuse frozen probe without fitting")
    monkeypatch.setattr(alignment_retrieval, "fit_facet_probe", forbidden_fit)
    first = subject.run_joint_experiment(first_config, ROOT, tmp_path, tmp_path / "first-joint")
    # Restore fitting only while constructing the independent predecessor fixture.
    monkeypatch.undo()
    second_config, second_prior = predecessor_builder("second", "F")
    monkeypatch.setattr(alignment_retrieval, "fit_facet_probe", forbidden_fit)
    second = subject.run_joint_experiment(second_config, ROOT, tmp_path, tmp_path / "second-joint")
    assert first_prior["probe"]["sha256"] == second_prior["probe"]["sha256"]
    assert first_prior["predictions"]["sha256"] == second_prior["predictions"]["sha256"]
    assert [g["id"] for g in first["geometries"]] == [g["id"] for g in first_prior["geometries"]]
    assert first["status"] == second["status"] == "completed"
    for a, b in zip(first["geometries"], second["geometries"], strict=True):
        da, db = details(a), details(b)
        assert a["id"] == b["id"]
        assert a["mmr_replay"]["ordering_matches"] == 1
        assert b["mmr_replay"]["ordering_matches"] == 1
        assert a["mmr_replay"]["maximum_cosine_score_difference"] < 1e-6
        for policy in ("mmr", "hard_joint", "soft_joint"):
            ra, rb = da["policies"][policy]["rows"], db["policies"][policy]["rows"]
            assert [x["retrieved"] for x in ra] == [x["retrieved"] for x in rb]
            assert [x["selection_trace"] for x in ra] == [x["selection_trace"] for x in rb]
        assert a["policies"]["hard_joint"]["summary"] != b["policies"]["hard_joint"]["summary"]
    assert first["primary_fidelity"] == {"status": "unavailable", "value": None}
    assert first["native_useful_proof_coverage"] == {"status": "unrun", "value": None}
    assert first["qualified"] is first["production_admitted"] is first["sealed_final_test_accessed"] is False


def test_reused_prediction_byte_corruption_fails_before_new_output(tmp_path, predecessor_builder):
    config_path, prior = predecessor_builder("corruption")
    predictions = Path(prior["predictions"]["path"])
    predictions.write_bytes(predictions.read_bytes() + b" ")
    destination = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="digest"):
        subject.run_joint_experiment(config_path, ROOT, tmp_path, destination)
    assert not destination.exists()


def test_deadline_before_first_geometry_retains_all_unrun_ids_without_fits_or_details(
        tmp_path, predecessor_builder, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import alignment_retrieval

    config_path, predecessor = predecessor_builder("deadline")

    def forbidden_fit(*args, **kwargs):
        raise AssertionError("expired selector comparison must not fit a model")

    monkeypatch.setattr(alignment_retrieval, "fit_facet_probe", forbidden_fit)
    readings = iter([0., 1000.])
    # Replace only this runner's time binding; predecessor helpers retain real time.
    monkeypatch.setattr(subject, "time", SimpleNamespace(perf_counter=lambda: next(readings, 1000.)))
    output = tmp_path / "deadline-joint"
    report = subject.run_joint_experiment(config_path, ROOT, tmp_path, output)

    assert report["status"] == "partial_deadline"
    assert [geometry["id"] for geometry in report["geometries"]] == [
        geometry["id"] for geometry in predecessor["geometries"]]
    assert len(report["geometries"]) == 3
    assert all(geometry["status"] == "unrun_deadline" for geometry in report["geometries"])
    assert all("details" not in geometry for geometry in report["geometries"])
    assert not list(output.glob("geometry-*.json"))
    sealed = json.loads((output / "report.json").read_bytes())
    assert sealed["status"] == "partial_deadline"
    assert sealed["qualified"] is sealed["production_admitted"] is False
    assert sealed["resource_scope"]["model_fits"] == 0
    assert sealed["probe_refitted"] is sealed["projection_weights_retrained"] is False


@pytest.mark.parametrize("fault", ["query_ids", "targets_used", "calibrated"])
def test_resealed_prediction_scope_or_query_accounting_cannot_be_admitted(
        tmp_path, predecessor_builder, fault):
    config_path, prior = predecessor_builder("scope")
    prediction_path = Path(prior["predictions"]["path"])
    predictions = json.loads(prediction_path.read_bytes())
    if fault == "query_ids":
        predictions["query_ids"] = ["foreign-query"]
    elif fault == "targets_used":
        predictions["query_targets_used"] = True
    else:
        predictions["probabilities_calibrated"] = True
    prediction_path.write_text(json.dumps(predictions))
    prior["predictions"] = {**prior["predictions"],
                            "sha256": hashlib.sha256(prediction_path.read_bytes()).hexdigest(),
                            "bytes": prediction_path.stat().st_size}
    prior_path = tmp_path / "scope-retrieval" / "report.json"
    rewrite_report(prior_path, prior)
    config = json.loads(config_path.read_text())
    config["retrieval_report"] = binding(prior_path, tmp_path)
    config_path.write_text(json.dumps(config))
    destination = tmp_path / "must-not-exist"
    with pytest.raises(ValueError):
        subject.run_joint_experiment(config_path, ROOT, tmp_path, destination)
    assert not destination.exists()
