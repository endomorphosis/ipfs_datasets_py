"""Joint-triple selection controls over frozen, exposed development evidence.

The prior probe, predictions, candidate pool and all projection generations are
reused. Nothing is fitted here. Query references enter only the scorer after
source-only ranking. This experiment supplies no proof or fidelity authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

from .alignment_baseline import _check_disjoint, _digest, _load_file, _validated_rows
from .alignment_experiment import _file_binding, _write_json, score_rankings, training_candidates
from .alignment_retrieval_experiment import (
    _bound_artifact,
    _read_bound_json,
    _verify_origins,
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

CONFIG_SCHEMA = "alignment-joint-experiment-config/v1"
REPORT_SCHEMA = "alignment-joint-experiment-report/v1"
POLICIES = ["mmr", "hard_joint", "soft_joint"]
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_joint_experiment.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_joint_retrieval.py",
    "scripts/ops/legal_ir/run_alignment_joint_experiment.py",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def load_joint_config(path):
    raw = _bounded_bytes(Path(path), 262_144)
    value = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    fields = {"schema", "study_id", "retrieval_report", "policies", "top_k", "shortlist",
              "diversity_lambda", "max_seconds"}
    _require(type(value) is dict and set(value) == fields and value["schema"] == CONFIG_SCHEMA,
             "closed joint experiment config required")
    _require(value["study_id"] == "autoformalization-joint-development-v1", "development study identity required")
    bound = value["retrieval_report"]
    _require(type(bound) is dict and set(bound) == {"path", "sha256"}
             and type(bound["path"]) is str and 0 < len(bound["path"]) <= 4096
             and type(bound["sha256"]) is str and len(bound["sha256"]) == 64
             and all(letter in "0123456789abcdef" for letter in bound["sha256"]),
             "bound retrieval report required")
    _require(type(value["policies"]) is list and value["policies"] == POLICIES,
             "all three fixed joint policies required")
    _require(type(value["top_k"]) is int and 1 <= value["top_k"] <= 10
             and type(value["shortlist"]) is int and value["top_k"] <= value["shortlist"] <= 40,
             "bounded shortlist and demonstration budget required")
    for name, lower, upper in (("diversity_lambda", 0, 1), ("max_seconds", 1, 300)):
        number = value[name]
        _require(type(number) in (int, float) and lower <= number <= upper and math.isfinite(number),
                 f"invalid {name}")
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _payload_digest(report):
    _require(type(report) is dict and report.get("report_sha256") ==
             hashlib.sha256(_canonical_bytes({k: v for k, v in report.items() if k != "report_sha256"})).hexdigest(),
             "report payload digest differs")


def rank_joint_geometry(query_ids, query_vectors, candidates, candidate_vectors, predictions, settings):
    """Accept source geometry and predictions only; return fixed rankings."""
    from .alignment_joint_retrieval import rerank_joint_candidates
    from .alignment_retrieval import prepare_training_candidates, rerank_candidates

    _require(len(query_ids) == len(query_vectors) == len(predictions), "query prediction accounting differs")
    identities = [candidate["candidate_id"] for candidate in candidates]
    _require(len(identities) == len(candidate_vectors), "candidate geometry accounting differs")
    prepared = prepare_training_candidates(candidates, candidate_vectors=dict(zip(identities, candidate_vectors, strict=True)))
    rankings = {policy: [] for policy in settings["policies"]}
    shortlists = []
    for identity, query, prediction in zip(query_ids, query_vectors, predictions, strict=True):
        exact = None
        for policy in settings["policies"]:
            options = {"top_k": settings["top_k"], "shortlist": settings["shortlist"],
                       "diversity_lambda": settings["diversity_lambda"]}
            if policy == "mmr":
                row = rerank_candidates(identity, query, prepared, policy="mmr", **options)
            else:
                row = rerank_joint_candidates(identity, query, prepared, variant=policy,
                                             predicted_facets=prediction, **options)
            shortlist = row["trace"]["shortlist"]
            if exact is None:
                exact = shortlist
            else:
                _require(shortlist == exact, "policies must use exactly the same normalized shortlist")
            rankings[policy].append({"id": row["id"], "retrieved": row["retrieved"],
                "selection_trace": {**{k: v for k, v in row["trace"].items() if k != "shortlist"},
                                    "shortlist_sha256": _digest(shortlist)}})
        shortlists.append({"id": identity, "retrieved": exact})
    return rankings, shortlists


def _compact(scores):
    return {key: value for key, value in scores.items() if key != "rows"}


def _mmr_replay(rankings, predecessor_rows):
    prior = {row["id"]: row for row in predecessor_rows}
    _require(len(prior) == len(predecessor_rows) == len(rankings), "MMR replay query accounting differs")
    maximum = 0.0
    for row in rankings:
        _require(row["id"] in prior, "MMR replay query differs")
        previous = prior[row["id"]]
        _require([item["candidate_id"] for item in row["retrieved"]] ==
                 [item["candidate_id"] for item in previous["retrieved"]], "frozen MMR candidate ordering differs")
        for current, old in zip(row["retrieved"], previous["retrieved"], strict=True):
            maximum = max(maximum, abs(current["cosine_similarity"] - old["cosine_similarity"]))
        _require(row["selection_trace"] == previous["selection_trace"], "frozen MMR selection trace differs")
    _require(maximum <= 1e-6, "frozen MMR numerical replay differs")
    return {"ordering_matches": len(rankings), "selection_trace_matches": len(rankings),
            "maximum_cosine_score_difference": maximum}


def run_joint_experiment(config_path, repository_root, workspace_root, output_directory):
    started = time.perf_counter()
    repository, workspace = Path(repository_root).resolve(), Path(workspace_root).resolve()
    output = Path(output_directory)
    _require(repository == _executing_repository_root(), "repository must match executing study package")
    _require(not output.exists() and not output.is_symlink(), "fresh output directory required")
    settings, config_binding = load_joint_config(config_path)
    _, predecessor = _read_bound_json(workspace, settings["retrieval_report"])
    _payload_digest(predecessor)
    _require(predecessor.get("schema") == "alignment-retrieval-experiment-report/v1"
             and predecessor.get("status") == "completed", "completed frozen retrieval report required")
    _require(predecessor["evaluation_role"] == "exposed_development"
             and predecessor["target_origin"] == "synthetic_authored_unreviewed"
             and all(predecessor[flag] is False for flag in (
                 "qualified", "production_admitted", "sealed_final_test_accessed",
                 "query_targets_used_in_fit_or_ranking", "development_checkpoint_selection", "projection_weights_retrained")),
             "frozen development scope differs")
    for field in ("top_k", "shortlist", "diversity_lambda"):
        _require(settings[field] == predecessor["configuration"][field], "comparison budget must match predecessor")
    _require(predecessor["configuration"]["include_formal_geometries"] is True, "all formal geometries required")
    _, projection = _read_bound_json(workspace, predecessor["projection_report_binding"])
    _payload_digest(projection)
    _require(projection.get("schema") == "alignment-projection-experiment-report/v1"
             and projection.get("status") == "completed", "completed frozen projection report required")
    _require(all(projection[flag] is False for flag in ("qualified", "production_admitted", "sealed_final_test_accessed",
                                                      "development_used_in_fit", "development_checkpoint_selection")),
             "projection development scope differs")
    base_path = _bound_artifact(workspace, projection["base_configuration_binding"])
    base, _ = load_alignment_config(base_path, expected_sha256=projection["base_configuration_binding"]["sha256"])
    corpus = base["corpus"]
    _require(corpus["vector_space_id"] == "thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd:"
             "d384:pool=mean:norm=l2:precision=float32:input_policy=exact_source_no_truncation", "raw probe source space differs")
    for bound in base["protected_protocols"] + corpus["provenance"]:
        _observed_binding(workspace, bound)
    sources = list(predecessor["source_bindings"])
    for relative in _SOURCE_FILES:
        bound = _file_binding(_workspace_path(repository, relative))
        sources.append({**bound, "path": relative})
    for bound in sources:
        _require(_file_binding(_workspace_path(repository, bound["path"]))["sha256"] == bound["sha256"], "source generation differs")
    _verify_origins(repository, sources)
    roots = (repository, workspace)
    _, train_raw = _load_file(corpus["train"], roots, "train.json", corpus["max_file_bytes"])
    _, dev_raw = _load_file(corpus["development"], roots, "validation.json", corpus["max_file_bytes"])
    training = _validated_rows(train_raw, "train", corpus["max_rows"])
    development = _validated_rows(dev_raw, "validation", corpus["max_rows"])
    _check_disjoint(training, development)
    _require(len(training) <= 512 and len(development) <= 512, "bounded numerical batches required")
    _require(len(training) == predecessor["training_rows"] and len(development) == predecessor["development_rows"],
             "frozen corpus row accounting differs")
    candidates = training_candidates(training)
    _require(_digest([candidate["candidate_id"] for candidate in candidates]) ==
             predecessor["candidate_pool"]["sha256"] == projection["candidate_pool"]["sha256"], "candidate pool generation differs")
    query_ids = [row["id"] for row in development]
    raw_queries = [row["unit_vector"] for row in development]
    raw_candidates = [candidate["source_vector"] for candidate in candidates]
    _, probe = _read_bound_json(workspace, predecessor["probe"])
    _, frozen_predictions = _read_bound_json(workspace, predecessor["predictions"])
    _require(type(frozen_predictions) is dict and set(frozen_predictions) == {
        "schema", "query_ids", "predictions", "probabilities_calibrated", "query_targets_used"}
        and frozen_predictions["schema"] == "alignment-source-facet-predictions/v1"
        and frozen_predictions["query_ids"] == query_ids
        and frozen_predictions["probabilities_calibrated"] is False and frozen_predictions["query_targets_used"] is False,
        "frozen source prediction scope differs")
    from .alignment_retrieval import _vector as _probe_vector
    from .alignment_retrieval import predict_source_facets

    predictions = frozen_predictions["predictions"]
    _require(predictions == predict_source_facets(raw_queries, probe), "frozen source prediction replay differs")
    training_manifest = [{"id": row["id"], "source_vector_sha256": _digest(_probe_vector(row["unit_vector"], 384)),
                          "target_sha256": _digest(row["target"])} for row in training]
    _require(probe["training_row_count"] == len(training) and
             probe["training_manifest_sha256"] == _digest(training_manifest), "frozen probe training generation differs")
    expected_ids = ["raw"]
    for trial in projection["trials"]:
        _require(trial["status"] == "completed", "every prior projection generation must be retained")
        expected_ids.extend([trial["id"] + ":source", trial["id"] + ":formal"])
    _require([geometry["id"] for geometry in predecessor["geometries"]] == expected_ids
             and all(geometry["status"] == "completed" for geometry in predecessor["geometries"]),
             "frozen geometry accounting differs")
    previous_geometries = {geometry["id"]: geometry for geometry in predecessor["geometries"]}
    import torch

    from .alignment_projection import encode_legal_target, load_projection_checkpoint

    _verify_origins(repository, sources)
    output.mkdir(parents=True, exist_ok=False)
    deadline = started + settings["max_seconds"]
    geometries = []

    def evaluate(identity, family, query_vectors, candidate_vectors, checkpoint=None):
        if time.perf_counter() >= deadline:
            geometries.append({"id": identity, "family": family, "status": "unrun_deadline"})
            return
        rankings, shortlists = rank_joint_geometry(query_ids, query_vectors, candidates, candidate_vectors, predictions, settings)
        replay = _mmr_replay(rankings["mmr"], previous_geometries[identity]["policies"]["mmr"]["rows"])
        # Authored development references enter only after all selectors finish.
        scores = {policy: score_rankings(rows, development, candidates, settings["top_k"])
                  for policy, rows in rankings.items()}
        support = _compact(score_rankings(shortlists, development, candidates, min(settings["shortlist"], len(candidates))))
        details = _write_json(output / f"geometry-{len(geometries):02d}.json", {
            "schema": "alignment-joint-geometry-details/v1", "id": identity, "family": family,
            "policies": scores, "shortlist_support": support,
            "qualified": False, "production_admitted": False})
        geometries.append({"id": identity, "family": family, "status": "completed", "checkpoint": checkpoint,
                           "policies": {policy: _compact(score) for policy, score in scores.items()},
                           "shortlist_support": support, "details": details, "mmr_replay": replay})

    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        evaluate("raw", "raw_source", raw_queries, raw_candidates)
        queries = torch.tensor(raw_queries, dtype=torch.float32, device="cpu")
        candidate_tensor = torch.tensor(raw_candidates, dtype=torch.float32, device="cpu")
        for trial in projection["trials"]:
            checkpoint_path = _bound_artifact(workspace, trial["checkpoint"])
            if time.perf_counter() >= deadline:
                evaluate(trial["id"] + ":source", "projected_source", [], [], trial["checkpoint"])
                evaluate(trial["id"] + ":formal", "projected_formal", [], [], trial["checkpoint"])
                continue
            loaded = load_projection_checkpoint(checkpoint_path, expected_sha256=trial["checkpoint"]["sha256"],
                                                expected_source_space_id=corpus["vector_space_id"])
            with torch.no_grad():
                model = loaded["model"]
                projected_queries = model.source(queries).tolist()
                projected_source = model.source(candidate_tensor).tolist()
                formal = torch.tensor([encode_legal_target(candidate["target"], loaded["codec"]) for candidate in candidates],
                                      dtype=torch.float32, device="cpu")
                projected_formal = model.formal(formal).tolist()
            evaluate(trial["id"] + ":source", "projected_source", projected_queries, projected_source, trial["checkpoint"])
            evaluate(trial["id"] + ":formal", "projected_formal", projected_queries, projected_formal, trial["checkpoint"])
    finally:
        torch.set_num_threads(previous_threads)
    for split in ("train", "development"):
        _load_file(corpus[split], roots, "train.json" if split == "train" else "validation.json", corpus["max_file_bytes"])
    for bound in sources:
        _require(_file_binding(_workspace_path(repository, bound["path"]))["sha256"] == bound["sha256"], "joint source drift")
    _verify_origins(repository, sources)
    frozen_bindings = [settings["retrieval_report"], predecessor["projection_report_binding"],
                       projection["base_configuration_binding"], predecessor["probe"], predecessor["predictions"],
                       predecessor["review_admission"], projection["review_bundle"],
                       *[trial["checkpoint"] for trial in projection["trials"]]]
    for bound in frozen_bindings:
        _bound_artifact(workspace, bound)
    for bound in base["protected_protocols"] + corpus["provenance"]:
        _observed_binding(workspace, bound)
    _require(_file_binding(config_path)["sha256"] == config_binding["sha256"], "joint config drift")
    for geometry in geometries:
        if geometry["status"] == "completed":
            current = _file_binding(geometry["details"]["path"])
            _require(current["sha256"] == geometry["details"]["sha256"]
                     and current["bytes"] == geometry["details"]["bytes"], "geometry details drift")
    report = {"schema": REPORT_SCHEMA, "study_id": settings["study_id"], "configuration": settings,
        "configuration_binding": config_binding, "retrieval_report_binding": settings["retrieval_report"],
        "projection_report_binding": predecessor["projection_report_binding"], "source_bindings": sources,
        "complete_dependency_manifest": False,
        "status": "completed" if all(g["status"] == "completed" for g in geometries) else "partial_deadline",
        "evaluation_role": "exposed_development", "target_origin": "synthetic_authored_unreviewed",
        "training_rows": len(training), "development_rows": len(development),
        "development_groups": len({row["group_id"] for row in development}),
        "candidate_pool": predecessor["candidate_pool"], "probe": predecessor["probe"],
        "predictions": predecessor["predictions"], "source_predictions_replayed": True,
        "probe_authored_facet_accuracy": predecessor["probe_authored_facet_accuracy"],
        "geometries": geometries, "review_admission": predecessor["review_admission"],
        "primary_fidelity": {"status": "unavailable", "value": None},
        "native_useful_proof_coverage": {"status": "unrun", "value": None},
        "qualified": False, "production_admitted": False, "sealed_final_test_accessed": False,
        "query_targets_used_in_fit_or_ranking": False, "development_checkpoint_selection": False,
        "projection_weights_retrained": False, "probe_refitted": False, "calibration_fitted": False,
        "elapsed_seconds": time.perf_counter() - started,
        "resource_scope": {"device": "cpu", "torch_threads": 1, "encoder_loads": 0, "model_fits": 0,
                           "provider_calls": 0, "prover_calls": 0, "deadline": "cooperative_between_geometries"},
        "numerical_dependencies": {"torch_version": torch.__version__, "head_precision": "float32",
                                   "prediction_and_ranking_precision": "float64"},
        "limitations": ["Synthetic authored references and cached encoder execution remain independently unverified.",
            "Hard joint coverage concerns argmax predictions; incorrect predictions can select incorrect demonstrations.",
            "Soft joint coverage uses factorized marginal products, not calibrated probabilities of complementary support.",
            "Soft actor and action triple credit can occur in different modality/object contexts.",
            "Relevance-weighted greedy selection does not guarantee available complementary support.",
            "The frozen probe has a closed training vocabulary and only four core facets.",
            "All generations are retained; five exposed development groups support descriptive comparisons only.",
            "No new model fitting, human review, formalization generation, provider, or native proof is supplied."]}
    report["report_sha256"] = hashlib.sha256(_canonical_bytes(report)).hexdigest()
    _write_json(output / "report.json", report)
    return report
