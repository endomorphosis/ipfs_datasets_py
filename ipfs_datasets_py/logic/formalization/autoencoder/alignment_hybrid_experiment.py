"""Fixed source/formal candidate discovery over frozen development evidence.

Both retrieval heads consult the same training pool. New policies change the
final shortlist while retaining formal-cosine hard-joint selection. No query
reference enters ranking; authored scoring occurs only after selection.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

from .alignment_baseline import _check_disjoint, _digest, _load_file, _validated_rows
from .alignment_experiment import _file_binding, _write_json, score_rankings, training_candidates
from .alignment_joint_experiment import _compact, _payload_digest, rank_joint_geometry
from .alignment_retrieval_experiment import _bound_artifact, _read_bound_json, _verify_origins
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

CONFIG_SCHEMA = "alignment-hybrid-experiment-config/v1"
REPORT_SCHEMA = "alignment-hybrid-experiment-report/v1"
POLICIES = ["source_only", "formal_only", "source_discovery_formal_select", "rrf_formal", "quota_formal"]
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_hybrid_experiment.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_hybrid_retrieval.py",
    "scripts/ops/legal_ir/run_alignment_hybrid_experiment.py",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def load_hybrid_config(path):
    raw = _bounded_bytes(Path(path), 262_144)
    value = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    fields = {"schema", "study_id", "joint_report", "policies", "top_k", "shortlist", "head_budget",
              "rrf_k", "diversity_lambda", "max_seconds"}
    _require(type(value) is dict and set(value) == fields and value["schema"] == CONFIG_SCHEMA,
             "closed hybrid experiment config required")
    _require(value["study_id"] == "autoformalization-hybrid-development-v1", "development study identity required")
    bound = value["joint_report"]
    _require(type(bound) is dict and set(bound) == {"path", "sha256"}
             and type(bound["path"]) is str and 0 < len(bound["path"]) <= 4096
             and type(bound["sha256"]) is str and len(bound["sha256"]) == 64
             and all(letter in "0123456789abcdef" for letter in bound["sha256"]), "bound joint report required")
    _require(type(value["policies"]) is list and value["policies"] == POLICIES, "all five fixed discovery policies required")
    _require(type(value["top_k"]) is int and 1 <= value["top_k"] <= 10
             and type(value["shortlist"]) is int and value["top_k"] <= value["shortlist"] <= 40,
             "bounded shortlist and demonstration budget required")
    _require(value["shortlist"] % 2 == 0, "balanced quota discovery requires an even final budget")
    _require(type(value["head_budget"]) is int and value["head_budget"] == value["shortlist"], "each head budget must match final budget")
    _require(type(value["rrf_k"]) is int and value["rrf_k"] == 60, "fixed reciprocal-rank constant required")
    for name, lower, upper in (("diversity_lambda", 0, 1), ("max_seconds", 1, 300)):
        number = value[name]
        _require(type(number) in (int, float) and lower <= number <= upper and math.isfinite(number), f"invalid {name}")
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def rank_hybrid_pair(query_ids, source_queries, formal_queries, candidates,
                     source_candidate_vectors, formal_candidate_vectors, predictions, settings):
    """Source-only boundary, with no query references or group-routing input."""
    from .alignment_hybrid_retrieval import prepare_hybrid_candidate_pair, rerank_hybrid_policies

    _require(len(query_ids) == len(source_queries) == len(formal_queries) == len(predictions), "query prediction accounting differs")
    identities = [candidate["candidate_id"] for candidate in candidates]
    _require(len(identities) == len(source_candidate_vectors) == len(formal_candidate_vectors), "paired candidate accounting differs")
    pair = prepare_hybrid_candidate_pair(candidates,
        source_candidate_vectors=dict(zip(identities, source_candidate_vectors, strict=True)),
        formal_candidate_vectors=dict(zip(identities, formal_candidate_vectors, strict=True)))
    rankings = {policy: [] for policy in settings["policies"]}
    shortlists = {policy: [] for policy in settings["policies"]}
    unions = []
    for identity, source, formal, prediction in zip(query_ids, source_queries, formal_queries, predictions, strict=True):
        rows = rerank_hybrid_policies(identity, source, formal, pair, policies=settings["policies"],
            predicted_facets=prediction, top_k=settings["top_k"], shortlist=settings["shortlist"],
            head_budget=settings["head_budget"], rrf_k=settings["rrf_k"], diversity_lambda=settings["diversity_lambda"])
        _require([row["policy"] for row in rows] == settings["policies"], "policy accounting differs")
        union = None
        for row in rows:
            trace = row["trace"]
            if union is None:
                union = trace["unpruned_union"]
            else:
                _require(union == trace["unpruned_union"], "policies must share the same unpruned two-head union")
            policy = row["policy"]
            rankings[policy].append({"id": row["id"], "retrieved": row["retrieved"], "selection_trace": trace})
            shortlists[policy].append({"id": row["id"], "retrieved": trace["shortlist"]})
        unions.append({"id": identity, "retrieved": union})
    return rankings, shortlists, unions


def _replay_control(rows, previous, *, embedded=True):
    old = {row["id"]: row for row in previous}
    _require(len(old) == len(previous) == len(rows), "control replay query accounting differs")
    maximum = 0.0
    for row in rows:
        _require(row["id"] in old, "control replay query identity differs")
        prior = old[row["id"]]
        _require(row["retrieved"] == prior["retrieved"], "frozen hard-joint selected items differ")
        trace = row["selection_trace"]
        if embedded:
            joint = trace["embedded_joint_trace"]
            trace = {**{key: value for key, value in joint.items() if key != "shortlist"}, "shortlist_sha256": _digest(joint["shortlist"])}
        _require(trace == prior["selection_trace"], "frozen hard-joint selection trace differs")
        for current, before in zip(row["retrieved"], prior["retrieved"], strict=True):
            maximum = max(maximum, abs(current["cosine_similarity"] - before["cosine_similarity"]))
    return {"ordering_matches": len(rows), "selection_trace_matches": len(rows), "maximum_cosine_score_difference": maximum}


def _union_support(unions, development, candidates):
    # Union sizes vary with overlap; avoid comparing relevance at unequal k.
    values = []
    for union, reference in zip(unions, development, strict=True):
        scores = score_rankings([union], [reference], candidates, len(union["retrieved"]))
        values.append(scores["rows"][0])
    def summarize(rows):
        return {"rows": len(rows), "actor_support": sum(row["actor_support"] for row in rows) / len(rows),
                "action_support": sum(row["action_support"] for row in rows) / len(rows),
                "complementary_actor_action_support": sum(row["complementary_actor_action_support"] for row in rows) / len(rows)}
    return {"summary": summarize(values),
            "by_group": {group: summarize([row for row in values if row["group_id"] == group]) for group in sorted({row["group_id"] for row in values})},
            "by_wording_style": {str(style): summarize([row for row in values if row["wording_style"] == style]) for style in sorted({row["wording_style"] for row in values})}}


def run_hybrid_experiment(config_path, repository_root, workspace_root, output_directory):
    started = time.perf_counter()
    repository, workspace = Path(repository_root).resolve(), Path(workspace_root).resolve()
    output = Path(output_directory)
    _require(repository == _executing_repository_root(), "repository must match executing study package")
    _require(not output.exists() and not output.is_symlink(), "fresh output directory required")
    settings, config_binding = load_hybrid_config(config_path)
    _, predecessor = _read_bound_json(workspace, settings["joint_report"])
    _payload_digest(predecessor)
    _require(predecessor.get("schema") == "alignment-joint-experiment-report/v1"
             and predecessor.get("status") == "completed", "completed frozen joint report required")
    _require(predecessor["evaluation_role"] == "exposed_development" and predecessor["target_origin"] == "synthetic_authored_unreviewed"
             and all(predecessor[name] is False for name in ("qualified", "production_admitted", "sealed_final_test_accessed",
                 "query_targets_used_in_fit_or_ranking", "development_checkpoint_selection", "projection_weights_retrained", "probe_refitted", "calibration_fitted")),
             "frozen development scope differs")
    for name in ("top_k", "shortlist", "diversity_lambda"):
        _require(settings[name] == predecessor["configuration"][name], "comparison budget must match predecessor")
    _, projection = _read_bound_json(workspace, predecessor["projection_report_binding"])
    _payload_digest(projection)
    _require(projection.get("schema") == "alignment-projection-experiment-report/v1" and projection.get("status") == "completed"
             and all(projection[name] is False for name in ("qualified", "production_admitted", "sealed_final_test_accessed",
                                                         "development_used_in_fit", "development_checkpoint_selection")), "frozen projection scope differs")
    base_path = _bound_artifact(workspace, projection["base_configuration_binding"])
    base, _ = load_alignment_config(base_path, expected_sha256=projection["base_configuration_binding"]["sha256"])
    corpus = base["corpus"]
    sources = list(predecessor["source_bindings"])
    for relative in _SOURCE_FILES:
        bound = _file_binding(_workspace_path(repository, relative))
        sources.append({**bound, "path": relative})
    for bound in sources:
        _require(_file_binding(_workspace_path(repository, bound["path"]))["sha256"] == bound["sha256"], "source generation differs")
    _verify_origins(repository, sources)
    for bound in base["protected_protocols"] + corpus["provenance"]:
        _observed_binding(workspace, bound)
    roots = (repository, workspace)
    _, train_raw = _load_file(corpus["train"], roots, "train.json", corpus["max_file_bytes"])
    _, dev_raw = _load_file(corpus["development"], roots, "validation.json", corpus["max_file_bytes"])
    training = _validated_rows(train_raw, "train", corpus["max_rows"])
    development = _validated_rows(dev_raw, "validation", corpus["max_rows"])
    _check_disjoint(training, development)
    _require(len(training) <= 512 and len(development) <= 512, "bounded numerical batches required")
    _require(len(training) == predecessor["training_rows"] and len(development) == predecessor["development_rows"], "frozen row accounting differs")
    candidates = training_candidates(training)
    _require(_digest([candidate["candidate_id"] for candidate in candidates]) == predecessor["candidate_pool"]["sha256"] == projection["candidate_pool"]["sha256"],
             "candidate pool generation differs")
    query_ids = [row["id"] for row in development]
    raw_queries = [row["unit_vector"] for row in development]
    raw_candidates = [candidate["source_vector"] for candidate in candidates]
    _, probe = _read_bound_json(workspace, predecessor["probe"])
    _, cached = _read_bound_json(workspace, predecessor["predictions"])
    _require(type(cached) is dict and set(cached) == {"schema", "query_ids", "predictions", "probabilities_calibrated", "query_targets_used"}
             and cached["schema"] == "alignment-source-facet-predictions/v1" and cached["query_ids"] == query_ids
             and cached["probabilities_calibrated"] is False and cached["query_targets_used"] is False, "frozen source prediction scope differs")
    from .alignment_retrieval import SOURCE_SPACE_ID, _vector, predict_source_facets

    _require(corpus["vector_space_id"] == SOURCE_SPACE_ID, "probe source space differs")
    predictions = cached["predictions"]
    _require(predictions == predict_source_facets(raw_queries, probe), "frozen source prediction replay differs")
    manifest = [{"id": row["id"], "source_vector_sha256": _digest(_vector(row["unit_vector"], 384)), "target_sha256": _digest(row["target"])} for row in training]
    _require(probe["training_row_count"] == len(training) and probe["training_manifest_sha256"] == _digest(manifest), "frozen probe training generation differs")
    expected_ids = ["raw"]
    for trial in projection["trials"]:
        _require(trial["status"] == "completed", "all prior projection generations required")
        expected_ids.extend([trial["id"] + ":source", trial["id"] + ":formal"])
    _require([geometry["id"] for geometry in predecessor["geometries"]] == expected_ids and all(geometry["status"] == "completed" for geometry in predecessor["geometries"]),
             "frozen paired generation accounting differs")
    prior_geometries = {geometry["id"]: geometry for geometry in predecessor["geometries"]}
    for trial in projection["trials"]:
        for family in ("source", "formal"):
            _require(prior_geometries[trial["id"] + ":" + family]["checkpoint"] == trial["checkpoint"], "paired checkpoint binding differs")
    import torch

    from .alignment_projection import encode_legal_target, load_projection_checkpoint

    _verify_origins(repository, sources)
    output.mkdir(parents=True, exist_ok=False)
    deadline = started + settings["max_seconds"]
    raw_control = {"status": "unrun_deadline"}
    pairs = []
    previous_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        if time.perf_counter() < deadline:
            raw_settings = {**settings, "policies": ["hard_joint"]}
            ranked, shortlisted = rank_joint_geometry(query_ids, raw_queries, candidates, raw_candidates, predictions, raw_settings)
            _, old = _read_bound_json(workspace, prior_geometries["raw"]["details"])
            replay = _replay_control(ranked["hard_joint"], old["policies"]["hard_joint"]["rows"], embedded=False)
            raw_score = score_rankings(ranked["hard_joint"], development, candidates, settings["top_k"])
            details = _write_json(output / "raw-control.json", {"schema": "alignment-hybrid-raw-details/v1", "score": raw_score,
                "qualified": False, "production_admitted": False})
            raw_control = {"status": "completed", "score": _compact(raw_score), "details": details, "replay": replay,
                           "shortlist_support": _compact(score_rankings(shortlisted, development, candidates, min(settings["shortlist"], len(candidates))))}
        queries = torch.tensor(raw_queries, dtype=torch.float32, device="cpu")
        candidate_tensor = torch.tensor(raw_candidates, dtype=torch.float32, device="cpu")
        for trial in projection["trials"]:
            checkpoint_path = _bound_artifact(workspace, trial["checkpoint"])
            if time.perf_counter() >= deadline:
                pairs.append({"id": trial["id"], "status": "unrun_deadline"})
                continue
            loaded = load_projection_checkpoint(checkpoint_path, expected_sha256=trial["checkpoint"]["sha256"], expected_source_space_id=corpus["vector_space_id"])
            with torch.no_grad():
                model = loaded["model"]
                projected_queries = model.source(queries).tolist()
                source_vectors = model.source(candidate_tensor).tolist()
                formal = torch.tensor([encode_legal_target(candidate["target"], loaded["codec"]) for candidate in candidates], dtype=torch.float32, device="cpu")
                formal_vectors = model.formal(formal).tolist()
            rankings, shortlists, unions = rank_hybrid_pair(query_ids, projected_queries, projected_queries, candidates,
                                                           source_vectors, formal_vectors, predictions, settings)
            replay = {}
            for policy, family in (("source_only", "source"), ("formal_only", "formal")):
                _, old = _read_bound_json(workspace, prior_geometries[trial["id"] + ":" + family]["details"])
                replay[policy] = _replay_control(rankings[policy], old["policies"]["hard_joint"]["rows"])
            # Development authored references enter only after discovery/selection.
            scores = {policy: score_rankings(rows, development, candidates, settings["top_k"]) for policy, rows in rankings.items()}
            support = {policy: _compact(score_rankings(rows, development, candidates, min(settings["shortlist"], len(candidates)))) for policy, rows in shortlists.items()}
            union_support = _union_support(unions, development, candidates)
            details = _write_json(output / f"pair-{len(pairs):02d}.json", {"schema": "alignment-hybrid-pair-details/v1", "id": trial["id"],
                "policies": scores, "shortlist_support": support, "union_support": union_support,
                "qualified": False, "production_admitted": False})
            pairs.append({"id": trial["id"], "status": "completed", "checkpoint": trial["checkpoint"],
                          "policies": {policy: _compact(score) for policy, score in scores.items()}, "shortlist_support": support,
                          "union_support": union_support, "details": details, "control_replay": replay})
    finally:
        torch.set_num_threads(previous_threads)
    for split in ("train", "development"):
        _load_file(corpus[split], roots, "train.json" if split == "train" else "validation.json", corpus["max_file_bytes"])
    for bound in sources:
        _require(_file_binding(_workspace_path(repository, bound["path"]))["sha256"] == bound["sha256"], "hybrid source drift")
    _verify_origins(repository, sources)
    frozen = [settings["joint_report"], predecessor["projection_report_binding"], predecessor["retrieval_report_binding"],
              projection["base_configuration_binding"], predecessor["probe"], predecessor["predictions"], predecessor["review_admission"], projection["review_bundle"],
              *[trial["checkpoint"] for trial in projection["trials"]], *[geometry["details"] for geometry in predecessor["geometries"]]]
    for bound in frozen:
        _bound_artifact(workspace, bound)
    for bound in base["protected_protocols"] + corpus["provenance"]:
        _observed_binding(workspace, bound)
    _require(_file_binding(config_path)["sha256"] == config_binding["sha256"], "hybrid config drift")
    for completed in [raw_control, *pairs]:
        if completed["status"] == "completed":
            current = _file_binding(completed["details"]["path"])
            _require(current["sha256"] == completed["details"]["sha256"] and current["bytes"] == completed["details"]["bytes"], "hybrid detail artifact drift")
    report = {"schema": REPORT_SCHEMA, "study_id": settings["study_id"], "configuration": settings, "configuration_binding": config_binding,
        "joint_report_binding": settings["joint_report"], "projection_report_binding": predecessor["projection_report_binding"],
        "source_bindings": sources, "complete_dependency_manifest": False,
        "status": "completed" if raw_control["status"] == "completed" and all(pair["status"] == "completed" for pair in pairs) else "partial_deadline",
        "evaluation_role": "exposed_development", "target_origin": "synthetic_authored_unreviewed",
        "training_rows": len(training), "development_rows": len(development), "development_groups": len({row["group_id"] for row in development}),
        "candidate_pool": predecessor["candidate_pool"], "probe": predecessor["probe"], "predictions": predecessor["predictions"],
        "source_predictions_replayed": True, "probe_authored_facet_accuracy": predecessor["probe_authored_facet_accuracy"],
        "raw_control": raw_control, "pairs": pairs, "review_admission": predecessor["review_admission"],
        "primary_fidelity": {"status": "unavailable", "value": None}, "native_useful_proof_coverage": {"status": "unrun", "value": None},
        "qualified": False, "production_admitted": False, "sealed_final_test_accessed": False,
        "query_targets_used_in_fit_or_ranking": False, "development_checkpoint_selection": False,
        "projection_weights_retrained": False, "probe_refitted": False, "calibration_fitted": False,
        "elapsed_seconds": time.perf_counter() - started,
        "resource_scope": {"device": "cpu", "torch_threads": 1, "encoder_loads": 0, "model_fits": 0, "provider_calls": 0, "prover_calls": 0,
                           "deadline": "cooperative_between_pairs", "hybrid_head_prefixes": 2,
                           "per_head_discovery_budget": settings["head_budget"], "final_shortlist_budget": settings["shortlist"], "demonstration_budget": settings["top_k"]},
        "numerical_dependencies": {"torch_version": torch.__version__, "head_precision": "float32", "prediction_and_ranking_precision": "float64"},
        "limitations": ["Two-head fusion offers up to twice the discovery opportunities of single-head controls; only final and demonstration budgets are matched.",
            "New discovery arms share formal-cosine selection; source-only uses source geometry as its separately replayed control.",
            "A fixed-size merge may discard source support already available before pruning.",
            "Prediction errors and relevance-weighted greedy selection can still discard useful examples.",
            "Synthetic references and cached encoder execution remain independently unverified.",
            "The four-facet probe and empty qualifier blocks do not qualify scope, binding, or richer semantics.",
            "No new fit, human review, generation, sealed evaluation, or native proof is supplied."]}
    report["report_sha256"] = hashlib.sha256(_canonical_bytes(report)).hexdigest()
    _write_json(output / "report.json", report)
    return report
