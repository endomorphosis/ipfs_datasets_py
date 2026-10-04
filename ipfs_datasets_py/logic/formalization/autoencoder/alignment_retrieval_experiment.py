"""Inference-available retrieval controls over frozen development checkpoints.

The only new fit is a train-only facet ridge probe. All prior projection
generations are retained; none is selected or retrained on development. This
adapter stages review admission without inventing annotations or authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

from .alignment_baseline import CORE_FACETS, _check_disjoint, _digest, _load_file, _validated_rows
from .alignment_experiment import (
    _file_binding,
    _write_json,
    score_rankings,
    training_candidates,
)
from .alignment_study import (
    _bounded_bytes,
    _canonical_bytes,
    _executing_repository_root,
    _observed_binding,
    _reject_constant,
    _strict_object,
    _workspace_path,
    load_alignment_config,
)

CONFIG_SCHEMA = "alignment-retrieval-experiment-config/v1"
REPORT_SCHEMA = "alignment-retrieval-experiment-report/v1"
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_retrieval_experiment.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_retrieval.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_review_admission.py",
    "scripts/ops/legal_ir/run_alignment_retrieval_experiment.py",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _load_json(path, limit):
    return json.loads(_bounded_bytes(Path(path), limit), object_pairs_hook=_strict_object,
                      parse_constant=_reject_constant)


def load_retrieval_config(path):
    raw = _bounded_bytes(Path(path), 262_144)
    value = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    fields = {"schema", "study_id", "projection_report", "policies", "top_k", "shortlist",
              "diversity_lambda", "ridge_regularization", "include_formal_geometries", "max_seconds"}
    _require(type(value) is dict and set(value) == fields and value["schema"] == CONFIG_SCHEMA,
             "closed retrieval experiment config required")
    _require(value["study_id"] == "autoformalization-retrieval-development-v1", "development study identity required")
    _require(type(value["projection_report"]) is dict and set(value["projection_report"]) == {"path", "sha256"},
             "bound projection report required")
    _require(type(value["policies"]) is list and value["policies"] == ["cosine", "mmr", "facet_cover"],
             "all three fixed retrieval policies required")
    _require(type(value["top_k"]) is int and 1 <= value["top_k"] <= 10
             and type(value["shortlist"]) is int and value["top_k"] <= value["shortlist"] <= 40,
             "bounded shortlist and demonstration budget required")
    for name, lo, hi in (("diversity_lambda", 0, 1), ("ridge_regularization", .00001, 100), ("max_seconds", 1, 300)):
        number = value[name]
        _require(type(number) in (int, float) and math.isfinite(number) and lo <= number <= hi,
                 f"invalid {name}")
    _require(type(value["include_formal_geometries"]) is bool, "explicit formal-geometry switch required")
    return value, {"path":str(path), "sha256":hashlib.sha256(raw).hexdigest(), "bytes":len(raw)}


def _verify_origins(repository, bindings):
    for binding in bindings:
        relative = binding["path"]
        if relative.startswith("ipfs_datasets_py/") and relative.endswith(".py"):
            module = sys.modules.get(relative[:-3].replace("/", "."))
            if module is not None:
                origin = getattr(module, "__file__", None)
                _require(origin is not None and Path(origin).resolve() == repository/relative,
                         f"loaded retrieval dependency comes from another tree: {relative}")


def _artifact_path(workspace, binding):
    supplied = Path(binding["path"])
    if supplied.is_absolute():
        _require(supplied.is_relative_to(workspace), "artifact must remain inside workspace")
        relative = str(supplied.relative_to(workspace))
    else:
        relative = str(supplied)
    return _workspace_path(workspace, relative)


def _bound_artifact(workspace, binding):
    path = _artifact_path(workspace, binding)
    raw = _bounded_bytes(path, 32_000_000)
    _require(hashlib.sha256(raw).hexdigest() == binding["sha256"], "artifact digest mismatch")
    return path


def _read_bound_json(workspace, binding):
    path = _artifact_path(workspace, binding)
    raw = _bounded_bytes(path, 32_000_000)
    _require(hashlib.sha256(raw).hexdigest() == binding["sha256"], "artifact digest mismatch")
    value = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    return path, value


def rank_retrieval_geometry(query_ids, query_vectors, candidates, candidate_vectors, predictions, settings):
    """Ranking boundary accepts source vectors and inferred facets, never query gold."""
    from .alignment_retrieval import prepare_training_candidates, rerank_candidates

    _require(len(query_ids) == len(query_vectors) == len(predictions), "query prediction accounting differs")
    ids = [c["candidate_id"] for c in candidates]
    _require(len(ids) == len(candidate_vectors), "candidate geometry accounting differs")
    vectors = dict(zip(ids, candidate_vectors, strict=True))
    prepared = prepare_training_candidates(candidates, candidate_vectors=vectors)
    rankings = {policy: [] for policy in settings["policies"]}
    shortlists = []
    for identity, query, predicted in zip(query_ids, query_vectors, predictions, strict=True):
        actual_shortlist = None
        for policy in settings["policies"]:
            row = rerank_candidates(identity, query, prepared, policy=policy, top_k=settings["top_k"],
                shortlist=settings["shortlist"], diversity_lambda=settings["diversity_lambda"],
                predicted_facets=predicted if policy == "facet_cover" else None)
            exact = row["trace"]["shortlist"]
            if actual_shortlist is None:
                actual_shortlist = exact
            else:
                _require(exact == actual_shortlist, "policies must use exactly the same normalized shortlist")
            # Keep the frozen selection trace once; no authored reference is joined here.
            rankings[policy].append({"id": row["id"], "retrieved": row["retrieved"],
                "selection_trace": {**{k:v for k,v in row["trace"].items() if k != "shortlist"},
                                    "shortlist_sha256": _digest(exact)}})
        shortlists.append({"id":identity,"retrieved":actual_shortlist})
    return rankings, shortlists


def run_retrieval_experiment(config_path, repository_root, workspace_root, output_directory):
    started = time.perf_counter()
    repository, workspace = Path(repository_root).resolve(), Path(workspace_root).resolve()
    output = Path(output_directory)
    _require(repository == _executing_repository_root(), "repository must match executing study package")
    _require(not output.exists() and not output.is_symlink(), "fresh output directory required")
    settings, config_binding = load_retrieval_config(config_path)
    _, prior = _read_bound_json(workspace, settings["projection_report"])
    _require(prior.get("schema") == "alignment-projection-experiment-report/v1" and prior.get("status") == "completed",
             "completed prior projection experiment required")
    body = {k:v for k,v in prior.items() if k != "report_sha256"}
    _require(hashlib.sha256(_canonical_bytes(body)).hexdigest() == prior["report_sha256"], "prior payload digest differs")
    _require(prior["evaluation_role"] == "exposed_development" and prior["target_origin"] == "synthetic_authored_unreviewed"
             and not any(prior[k] for k in ("qualified", "production_admitted", "sealed_final_test_accessed",
                                           "development_used_in_fit", "development_checkpoint_selection")),
             "prior development scope differs")
    base_binding = prior["base_configuration_binding"]
    base_path = _workspace_path(workspace, base_binding["path"])
    base, _ = load_alignment_config(base_path, expected_sha256=base_binding["sha256"])
    corpus = base["corpus"]
    for binding in base["protected_protocols"]+corpus["provenance"]:
        _observed_binding(workspace, binding)
    sources = list(prior["source_bindings"])
    for relative in _SOURCE_FILES:
        binding = _file_binding(_workspace_path(repository, relative))
        sources.append({**binding, "path": relative})
    for binding in sources:
        _require(_file_binding(_workspace_path(repository, binding["path"]))["sha256"] == binding["sha256"], "source generation differs")
    _verify_origins(repository, sources)
    roots = (repository, workspace)
    _, train_raw = _load_file(corpus["train"], roots, "train.json", corpus["max_file_bytes"])
    _, dev_raw = _load_file(corpus["development"], roots, "validation.json", corpus["max_file_bytes"])
    training = _validated_rows(train_raw, "train", corpus["max_rows"])
    development = _validated_rows(dev_raw, "validation", corpus["max_rows"])
    _check_disjoint(training, development)
    _require(len(training) <= 512 and len(development) <= 512, "bounded numerical batches required")
    candidates = training_candidates(training)
    ids = [c["candidate_id"] for c in candidates]
    _require(_digest(ids) == prior["candidate_pool"]["sha256"], "candidate pool generation differs")
    query_ids = [r["id"] for r in development]
    raw_queries = [r["unit_vector"] for r in development]
    raw_candidates = [c["source_vector"] for c in candidates]
    _, review = _read_bound_json(workspace, prior["review_bundle"])
    from .alignment_review_admission import admit_alignment_reviews

    # Stage the real blank handoff; no reviewer annotations or identities are synthesized.
    admission = admit_alignment_reviews(review, [review["reviewer_payload"]])
    import torch

    from .alignment_projection import encode_legal_target, load_projection_checkpoint
    from .alignment_retrieval import fit_facet_probe, predict_source_facets

    _verify_origins(repository, sources)
    output.mkdir(parents=True, exist_ok=False)
    probe = fit_facet_probe(training, regularization=settings["ridge_regularization"])
    predictions = predict_source_facets(raw_queries, probe)
    probe_binding = _write_json(output/"facet_probe.json", probe)
    prediction_binding = _write_json(output/"source_predictions.json", {"schema": "alignment-source-facet-predictions/v1",
        "query_ids": query_ids, "predictions": predictions, "probabilities_calibrated": False, "query_targets_used": False})
    admission_binding = _write_json(output/"review_admission.json", admission)
    previous_threads = torch.get_num_threads()
    deadline = started+settings["max_seconds"]
    geometries = []

    def evaluate(identity, family, qvectors, cvectors, checkpoint=None):
        if time.perf_counter() >= deadline:
            geometries.append({"id": identity, "family": family, "status": "unrun_deadline"})
            return
        frozen, shortlist = rank_retrieval_geometry(query_ids, qvectors, candidates, cvectors, predictions, settings)
        short_score = score_rankings(shortlist, development, candidates, min(settings["shortlist"], len(ids)))
        scores = {policy: score_rankings(rows, development, candidates, settings["top_k"])
                  for policy,rows in frozen.items()}
        geometries.append({"id": identity, "family": family, "status": "completed", "checkpoint": checkpoint,
                           "policies": scores, "shortlist_support": {"summary": short_score["summary"],
                               "by_group": short_score["by_group"], "by_wording_style": short_score["by_wording_style"]}})

    try:
        torch.set_num_threads(1)
        evaluate("raw", "raw_source", raw_queries, raw_candidates)
        q = torch.tensor(raw_queries, dtype=torch.float32, device="cpu")
        c = torch.tensor(raw_candidates, dtype=torch.float32, device="cpu")
        for trial in prior["trials"]:
            _require(trial["status"] == "completed", "every prior projection trial must be retained")
            checkpoint_path = _bound_artifact(workspace, trial["checkpoint"])
            if time.perf_counter() >= deadline:
                evaluate(trial["id"]+":source", "projected_source", [], [], trial["checkpoint"])
                if settings["include_formal_geometries"]:
                    evaluate(trial["id"]+":formal", "projected_formal", [], [], trial["checkpoint"])
                continue
            loaded = load_projection_checkpoint(checkpoint_path, expected_sha256=trial["checkpoint"]["sha256"],
                                                 expected_source_space_id=corpus["vector_space_id"])
            with torch.no_grad():
                model = loaded["model"]
                projected_queries = model.source(q).tolist()
                projected_sources = model.source(c).tolist()
                projected_formal = None
                if settings["include_formal_geometries"]:
                    formal = torch.tensor([encode_legal_target(candidate["target"], loaded["codec"]) for candidate in candidates],
                                          dtype=torch.float32, device="cpu")
                    projected_formal = model.formal(formal).tolist()
            evaluate(trial["id"]+":source", "projected_source", projected_queries, projected_sources, trial["checkpoint"])
            if projected_formal is not None:
                evaluate(trial["id"]+":formal", "projected_formal", projected_queries, projected_formal, trial["checkpoint"])
    finally:
        torch.set_num_threads(previous_threads)
    # Compare frozen predictions to authored references only after fitting/ranking.
    prediction_accuracy = {facet: sum(p[facet]["label"] == r["target"]["rules"][0][facet]
                                      for p,r in zip(predictions, development, strict=True))/len(development)
                           for facet in CORE_FACETS}
    for split in ("train", "development"):
        _load_file(corpus[split], roots, "train.json" if split == "train" else "validation.json", corpus["max_file_bytes"])
    for binding in sources:
        _require(_file_binding(_workspace_path(repository, binding["path"]))["sha256"] == binding["sha256"], "retrieval source drift")
    _verify_origins(repository, sources)
    _bound_artifact(workspace, settings["projection_report"])
    _bound_artifact(workspace, prior["review_bundle"])
    _bound_artifact(workspace, base_binding)
    for trial in prior["trials"]:
        _bound_artifact(workspace, trial["checkpoint"])
    _require(_file_binding(config_path)["sha256"] == config_binding["sha256"], "retrieval config drift")
    for binding in base["protected_protocols"]+corpus["provenance"]:
        _observed_binding(workspace, binding)
    report = {"schema": REPORT_SCHEMA, "study_id": settings["study_id"], "configuration": settings,
        "configuration_binding": config_binding, "projection_report_binding": settings["projection_report"],
        "source_bindings": sources, "complete_dependency_manifest": False,
        "status": "completed" if all(g["status"] == "completed" for g in geometries) else "partial_deadline",
        "evaluation_role": "exposed_development", "target_origin": "synthetic_authored_unreviewed",
        "training_rows": len(training), "development_rows": len(development),
        "development_groups": len({r["group_id"] for r in development}),
        "candidate_pool": prior["candidate_pool"], "probe": probe_binding, "predictions": prediction_binding,
        "probe_authored_facet_accuracy": prediction_accuracy, "geometries": geometries,
        "review_admission": admission_binding, "primary_fidelity": {"status": "unavailable", "value": None},
        "native_useful_proof_coverage": {"status": "unrun", "value": None},
        "qualified": False, "production_admitted": False, "sealed_final_test_accessed": False,
        "query_targets_used_in_fit_or_ranking": False, "development_checkpoint_selection": False,
        "projection_weights_retrained": False,
        "elapsed_seconds": time.perf_counter()-started,
        "resource_scope": {"device": "cpu", "torch_threads": 1, "encoder_loads": 0,
                           "provider_calls": 0, "prover_calls": 0, "deadline": "cooperative_between_geometries"},
        "numerical_dependencies": {"torch_version": torch.__version__, "head_precision": "float32",
                                   "ridge_and_ranking_precision": "float64"},
        "limitations": ["All source/target labels are synthetic and unreviewed; cached encoder execution is unauthenticated.",
            "Facet softmax masses are inference predictions, not calibrated semantic confidence.",
            "Unique individual facet coverage does not guarantee joint actor/action-modality-object support.",
            "Shortlist support is an authored post-ranking ceiling diagnostic, never a selector input.",
            "The probe has a closed training vocabulary; unseen atoms and richer qualifier semantics are unqualified.",
            "All prior projection generations are retained; exposed development supports descriptive comparisons only.",
            "No inference-time gold facets, formalization, generation, proof, or automatic human review is supplied."]}
    report["report_sha256"] = hashlib.sha256(_canonical_bytes(report)).hexdigest()
    _write_json(output/"report.json", report)
    return report
