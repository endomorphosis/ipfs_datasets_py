"""Train-only, CPU projection experiment on exposed synthetic Legal IR.

The frozen encoder is never loaded. This is a diagnostic alignment trainer,
not a source-fidelity or proof qualification route. Torch remains optional
until numerical execution. Final fixed-step checkpoints are evaluated once;
development references never enter fitting or ranking.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from .alignment_baseline import (
    CORE_FACETS,
    _check_disjoint,
    _digest,
    _load_file,
    _validated_rows,
)
from .alignment_study import (
    AlignmentStudyError,
    _bounded_bytes,
    _canonical_bytes,
    _executing_repository_root,
    _observed_binding,
    _reject_constant,
    _strict_object,
    _workspace_path,
    load_alignment_config,
    prepare_alignment_study,
)

CONFIG_SCHEMA = "alignment-projection-experiment-config/v1"
REPORT_SCHEMA = "alignment-projection-experiment-report/v1"
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_experiment.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_projection.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_review.py",
    "scripts/ops/legal_ir/run_alignment_projection_experiment.py",
)


def _require(condition, message):
    if not condition:
        raise AlignmentStudyError(message)


def load_projection_experiment_config(path):
    raw = _bounded_bytes(Path(path), 262_144)
    value = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    fields = {"schema", "study_id", "study_config", "shared_dimensions", "seeds", "negative_weights",
              "steps", "learning_rate", "temperature", "weight_decay", "top_k", "max_seconds"}
    _require(type(value) is dict and set(value) == fields, "closed projection experiment config required")
    _require(value["schema"] == CONFIG_SCHEMA, "unsupported projection experiment schema")
    _require(value["study_id"] == "autoformalization-projection-development-v1", "development study identity required")
    _require(type(value["study_config"]) is dict and set(value["study_config"]) == {"path", "sha256"},
             "bound base study configuration required")
    dimensions, seeds, weights = value["shared_dimensions"], value["seeds"], value["negative_weights"]
    _require(type(dimensions) is list and 1 <= len(dimensions) <= 2
             and all(type(d) is int and d in (384, 512) for d in dimensions)
             and len(set(dimensions)) == len(dimensions), "unique shared widths 384 or 512 required")
    _require(type(seeds) is list and 1 <= len(seeds) <= 3
             and all(type(seed) is int and 0 <= seed <= 999 for seed in seeds)
             and len(set(seeds)) == len(seeds), "bounded unique integer seeds required")
    _require(type(weights) is list and 1 <= len(weights) <= 2
             and all(type(w) in (int, float) and math.isfinite(w) and 1 <= w <= 4 for w in weights)
             and len(set(weights)) == len(weights), "bounded negative weights required")
    for field, lower, upper in (("steps", 1, 200), ("top_k", 1, 20)):
        _require(type(value[field]) is int and lower <= value[field] <= upper, f"invalid {field}")
    for field, lower, upper in (("learning_rate", .0001, 1), ("temperature", .01, 1),
                               ("weight_decay", 0, .1), ("max_seconds", 1, 300)):
        number = value[field]
        _require(type(number) in (int, float) and math.isfinite(number) and lower <= number <= upper,
                 f"invalid {field}")
    return value, {"path": str(Path(path).resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
                   "bytes": len(raw)}


def _unit(vector):
    norm = math.sqrt(math.fsum(x*x for x in vector))
    _require(norm > 0 and math.isfinite(norm), "nonzero finite representative required")
    return [x/norm for x in vector]


def training_candidates(training):
    """One candidate per training target: normalize(mean(unit source vectors))."""
    groups = defaultdict(list)
    for row in training:
        groups[row["target_sha256"]].append(row)
    candidates = []
    for identity, rows in sorted(groups.items()):
        representative = _unit([math.fsum(row["unit_vector"][i] for row in rows)/len(rows)
                                for i in range(384)])
        candidates.append({"candidate_id": identity, "target": rows[0]["target"],
                           "train_ids": sorted(row["id"] for row in rows),
                           "source_vector": representative})
    return candidates


def rank_vectors(query_ids, query_vectors, candidate_ids, candidate_vectors, top_k):
    """Source-only ranking boundary. No query targets or groups are admitted."""
    _require(len(query_ids) == len(query_vectors), "query vector accounting mismatch")
    _require(len(candidate_ids) == len(candidate_vectors) and len(set(candidate_ids)) == len(candidate_ids),
             "unique candidate vector accounting required")
    result = []
    for identity, query in zip(query_ids, query_vectors, strict=True):
        scores = []
        for candidate_id, candidate in zip(candidate_ids, candidate_vectors, strict=True):
            _require(len(query) == len(candidate), "retrieval dimensions differ")
            score = math.fsum(a*b for a, b in zip(query, candidate, strict=True))
            _require(math.isfinite(score), "nonfinite retrieval similarity")
            scores.append((candidate_id, score))
        ranked = sorted(scores, key=lambda pair: (-pair[1], pair[0]))[:top_k]
        result.append({"id": identity, "retrieved": [{"candidate_id": cid, "cosine_similarity": score}
                                                     for cid, score in ranked]})
    return result


def _summarize(rows):
    names = ("nearest_core_fraction", "mean_top_k_core_fraction", "best_top_k_core_fraction",
             "core_ndcg", "actor_support", "action_support", "complementary_actor_action_support",
             "nearest_actor_match", "nearest_action_match")
    return {"rows": len(rows), **{name: math.fsum(float(row[name]) for row in rows)/len(rows)
                                  if rows else None for name in names}}


def score_rankings(rankings, development, candidates, top_k):
    """Read authored references only after rankings are frozen."""
    _require([row["id"] for row in rankings] == [row["id"] for row in development],
             "development ranking accounting differs")
    lookup = {c["candidate_id"]: c for c in candidates}
    scored = []
    for ranking, row in zip(rankings, development, strict=True):
        reference = row["target"]["rules"][0]
        def matches(candidate, reference=reference):
            rule = candidate["target"]["rules"][0]
            return {facet: rule[facet] == reference[facet] for facet in CORE_FACETS}
        retrieved = ranking["retrieved"]
        ids = [item["candidate_id"] for item in retrieved]
        _require(len(ids) == min(top_k, len(candidates)) and len(set(ids)) == len(ids)
                 and all(cid in lookup for cid in ids), "rankings must use the declared unique candidate pool")
        facets = [matches(lookup[cid]) for cid in ids]
        gains = [sum(match.values()) for match in facets]
        ideal = sorted((sum(matches(c).values()) for c in candidates), reverse=True)[:len(ids)]
        def dcg(values):
            return math.fsum((2**value-1)/math.log2(i+2) for i, value in enumerate(values))
        ideal_dcg = dcg(ideal)
        actor_support = any(match["actor"] and match["modality"] and match["object"] for match in facets)
        action_support = any(match["action"] and match["modality"] and match["object"] for match in facets)
        scored.append({**ranking, "group_id": row["group_id"], "wording_style": row.get("wording_style"),
                       "nearest_core_fraction": gains[0]/4,
                       "mean_top_k_core_fraction": math.fsum(gains)/(4*len(gains)),
                       "best_top_k_core_fraction": max(gains)/4,
                       "core_ndcg": dcg(gains)/ideal_dcg if ideal_dcg else 0,
                       "actor_support": actor_support, "action_support": action_support,
                       "complementary_actor_action_support": actor_support and action_support,
                       "nearest_actor_match": facets[0]["actor"], "nearest_action_match": facets[0]["action"]})
    by_group, by_style = defaultdict(list), defaultdict(list)
    for row in scored:
        by_group[row["group_id"]].append(row)
        by_style[str(row["wording_style"])].append(row)
    return {"summary": _summarize(scored), "by_group": {k: _summarize(v) for k,v in sorted(by_group.items())},
            "by_wording_style": {k: _summarize(v) for k,v in sorted(by_style.items())}, "rows": scored}


def _fit_projection(training, settings, shared_dimension, seed, negative_weight, deadline):
    """Training-only interface; development vectors/references are absent."""
    import torch

    from .alignment_projection import (
        create_projection_heads,
        encode_legal_target,
        fit_legal_feature_codec,
        multi_positive_contrastive_loss,
    )
    targets = [row["target"] for row in training]
    codec = fit_legal_feature_codec(targets)
    model = create_projection_heads(384, codec["feature_dimension"], shared_dimension, seed)
    source = torch.tensor([row["unit_vector"] for row in training], dtype=torch.float32, device="cpu")
    formal = torch.tensor([encode_legal_target(target, codec) for target in targets], dtype=torch.float32, device="cpu")
    target_ids = [row["target_sha256"] for row in training]
    rules = [target["rules"][0] for target in targets]
    weights = torch.tensor([[negative_weight if all(a[facet] == b[facet] for facet in ("modality", "actor", "object"))
                             and a["action"] != b["action"] else 1.0 for b in rules] for a in rules],
                           dtype=torch.float32, device="cpu")
    optimizer = torch.optim.SGD(model.parameters(), lr=settings["learning_rate"],
                                weight_decay=settings["weight_decay"], momentum=0)
    def objective():
        return multi_positive_contrastive_loss(model.source(source), model.formal(formal), target_ids,
                                               temperature=settings["temperature"], hard_negative_weights=weights)
    started = time.perf_counter()
    with torch.no_grad():
        initial_loss = float(objective().item())
    losses = []
    for _step in range(settings["steps"]):
        if time.perf_counter() >= deadline:
            break
        optimizer.zero_grad(set_to_none=True)
        loss = objective()
        _require(bool(torch.isfinite(loss)), "nonfinite training objective")
        loss.backward()
        _require(all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in model.parameters()),
                 "nonfinite or missing projection gradients")
        optimizer.step()
        losses.append(float(loss.item()))
    with torch.no_grad():
        final_loss = float(objective().item())
    _require(math.isfinite(final_loss), "nonfinite final projection objective")
    return model, codec, {"completed_steps": len(losses), "requested_steps": settings["steps"],
                          "initial_loss": initial_loss, "final_loss": final_loss, "pre_step_losses": losses,
                          "elapsed_seconds": time.perf_counter()-started,
                          "optimizer": "SGD", "momentum": 0, "optimizer_state": {},
                          "resumption_supported": False, "training_rows": len(training),
                          "unique_training_targets": len(set(target_ids)),
                          "duplicate_targets_are_positives": True, "negative_weight": negative_weight,
                          "development_used_in_fit": False, "selection": "final_fixed_step_only"}


def _file_binding(path):
    raw = Path(path).read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _verify_loaded_origins(repository):
    for relative in _SOURCE_FILES:
        if not relative.startswith("ipfs_datasets_py/"):
            continue
        name = relative[:-3].replace("/", ".")
        module = sys.modules.get(name)
        if module is not None:
            origin = getattr(module, "__file__", None)
            _require(origin is not None and Path(origin).resolve() == repository/relative,
                     f"loaded experiment dependency comes from another tree: {name}")


def _write_json(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False).encode()+b"\n"
    _require(len(raw) <= 32_000_000, "artifact exceeds byte bound")
    with Path(path).open("xb") as stream:
        stream.write(raw)
    return _file_binding(path)


def run_projection_experiment(config_path, repository_root, workspace_root, output_directory):
    """Create a fresh, unqualified development experiment and review bundle."""
    started = time.perf_counter()
    repository, workspace, output = Path(repository_root).resolve(), Path(workspace_root).resolve(), Path(output_directory)
    _require(repository == _executing_repository_root(), "repository must match executing study package")
    _require(not output.exists() and not output.is_symlink(), "fresh output directory required")
    _verify_loaded_origins(repository)
    settings, config_binding = load_projection_experiment_config(config_path)
    base_binding = _observed_binding(workspace, settings["study_config"])
    base_path = _workspace_path(workspace, base_binding["path"])
    base, _ = load_alignment_config(base_path, expected_sha256=base_binding["sha256"])
    inventory = prepare_alignment_study(base_path, repository, workspace, expected_config_sha256=base_binding["sha256"])
    sources = list(inventory["source_bindings"])
    for relative in _SOURCE_FILES:
        path = _workspace_path(repository, relative)
        binding = _file_binding(path)
        sources.append({**binding, "path": relative})
    roots = (repository, workspace)
    corpus = base["corpus"]
    _, train_raw = _load_file(corpus["train"], roots, "train.json", corpus["max_file_bytes"])
    _, dev_raw = _load_file(corpus["development"], roots, "validation.json", corpus["max_file_bytes"])
    training = _validated_rows(train_raw, "train", corpus["max_rows"])
    development = _validated_rows(dev_raw, "validation", corpus["max_rows"])
    _check_disjoint(training, development)
    _require(len(training) <= 512 and len(development) <= 512,
             "full-batch projection prototype admits at most 512 rows per split")
    candidates = training_candidates(training)
    ids = [c["candidate_id"] for c in candidates]
    query_ids = [row["id"] for row in development]
    query_vectors = [row["unit_vector"] for row in development]
    top_k = settings["top_k"]
    raw_ranking = rank_vectors(query_ids, query_vectors, ids, [c["source_vector"] for c in candidates], top_k)
    raw_score = score_rankings(raw_ranking, development, candidates, top_k)
    from .alignment_review import prepare_alignment_review

    review = prepare_alignment_review(training, development,
                                      {"train": corpus["train"], "development": corpus["development"],
                                       "provenance": corpus["provenance"]})
    output.mkdir(parents=True, exist_ok=False)
    inventory_binding = _write_json(output/"inventory.json", inventory)
    review_binding = _write_json(output/"review_bundle.json", review)
    # Reviewer handoff is a separate file with no organizer target key.
    reviewer_binding = _write_json(output/"reviewer_items.json", review["reviewer_payload"])
    import torch

    from .alignment_projection import (
        create_projection_checkpoint,
        encode_legal_target,
        load_projection_checkpoint,
        save_projection_checkpoint,
    )
    _verify_loaded_origins(repository)
    previous_threads = torch.get_num_threads()
    trials = []
    deadline = started+settings["max_seconds"]
    try:
        torch.set_num_threads(1)
        for dimension in settings["shared_dimensions"]:
            for seed in settings["seeds"]:
                for weight in settings["negative_weights"]:
                    identity = f"d{dimension}-seed{seed}-neg{weight:g}"
                    trial = {"id": identity, "shared_dimension": dimension, "seed": seed, "negative_weight": weight}
                    if time.perf_counter() >= deadline:
                        trials.append({**trial, "status": "unrun_deadline"})
                        continue
                    model, codec, trace = _fit_projection(training, settings, dimension, seed, weight, deadline)
                    checkpoint = create_projection_checkpoint(model, codec, source_space_id=corpus["vector_space_id"],
                        train_bindings=[{**corpus["train"], "split": "train"}], generation_id=identity,
                        training_recipe={"optimizer": "SGD", "momentum": 0, "learning_rate": settings["learning_rate"],
                            "weight_decay": settings["weight_decay"], "temperature": settings["temperature"],
                            "requested_steps": settings["steps"], "completed_steps": trace["completed_steps"],
                            "seed": seed, "negative_weight": weight, "batching": "full_training_rows",
                            "selection": "final_fixed_step_only", "development_fit": False})
                    checkpoint_path = output/(identity+".checkpoint.json")
                    save_projection_checkpoint(checkpoint, checkpoint_path)
                    checkpoint_binding = _file_binding(checkpoint_path)
                    restored = load_projection_checkpoint(checkpoint_path,
                        expected_sha256=checkpoint_binding["sha256"], expected_source_space_id=corpus["vector_space_id"])
                    if trace["completed_steps"] != settings["steps"]:
                        trials.append({**trial, "status": "partial_deadline", "training": trace, "checkpoint": checkpoint_binding})
                        continue
                    with torch.no_grad():
                        q = torch.tensor(query_vectors, dtype=torch.float32, device="cpu")
                        source_candidates = torch.tensor([c["source_vector"] for c in candidates], dtype=torch.float32, device="cpu")
                        formal_candidates = torch.tensor([encode_legal_target(c["target"], codec) for c in candidates],
                                                         dtype=torch.float32, device="cpu")
                        query_projection = model.source(q)
                        replay_error = float((query_projection-restored["model"].source(q)).abs().max().item())
                        _require(replay_error == 0, "checkpoint numerical replay differs")
                        query_lists = query_projection.tolist()
                        ss = rank_vectors(query_ids, query_lists, ids, model.source(source_candidates).tolist(), top_k)
                        sf = rank_vectors(query_ids, query_lists, ids, model.formal(formal_candidates).tolist(), top_k)
                    trials.append({**trial, "status": "completed", "training": trace, "formal_feature_dimension": codec["feature_dimension"],
                                   "formal_codec_space_id": codec["feature_space_id"], "checkpoint": checkpoint_binding,
                                   "checkpoint_replay_max_abs_error": replay_error,
                                   "source_to_source": score_rankings(ss, development, candidates, top_k),
                                   "source_to_formal": score_rankings(sf, development, candidates, top_k)})
    finally:
        torch.set_num_threads(previous_threads)
    # Recheck exact inputs and code; concurrent drift cannot become a completed receipt.
    for relative in ("train", "development"):
        _load_file(corpus[relative], roots, "train.json" if relative == "train" else "validation.json", corpus["max_file_bytes"])
    for binding in sources:
        _require(_file_binding(repository/binding["path"])["sha256"] == binding["sha256"], "experiment source drift")
    _verify_loaded_origins(repository)
    _observed_binding(workspace, settings["study_config"])
    for binding in base["protected_protocols"]+corpus["provenance"]:
        _observed_binding(workspace, binding)
    _require(_file_binding(config_path)["sha256"] == config_binding["sha256"], "experiment configuration drift")
    train_pairs = {(r["target"]["rules"][0]["actor"], r["target"]["rules"][0]["action"]) for r in training}
    dev_pairs = {(r["target"]["rules"][0]["actor"], r["target"]["rules"][0]["action"]) for r in development}
    ceilings = [r["best_top_k_core_fraction"] for r in score_rankings(
        rank_vectors(query_ids, query_vectors, ids, [c["source_vector"] for c in candidates], len(candidates)),
        development, candidates, len(candidates))["rows"]]
    report = {"schema": REPORT_SCHEMA, "study_id": settings["study_id"], "evaluation_role": "exposed_development",
              "target_origin": "synthetic_authored_unreviewed", "configuration": settings,
              "configuration_binding": config_binding, "base_configuration_binding": base_binding,
              "source_bindings": sources, "complete_dependency_manifest": False,
              "inventory": inventory_binding, "review_bundle": review_binding, "reviewer_items": reviewer_binding,
              "training_rows": len(training), "development_rows": len(development),
              "training_groups": len({r["group_id"] for r in training}), "development_groups": len({r["group_id"] for r in development}),
              "panel_structure": {"actor_action_pairs_disjoint": not bool(train_pairs & dev_pairs),
                                  "training_actor_action_pairs": len(train_pairs), "development_actor_action_pairs": len(dev_pairs),
                                  "wording_multiplicity_counts": dict(sorted(Counter(len(c["train_ids"]) for c in candidates).items())),
                                  "individual_core_ceiling_min": min(ceilings), "individual_core_ceiling_max": max(ceilings)},
              "candidate_pool": {"unique_targets": len(candidates), "sha256": _digest(ids),
                                  "target_ids": ids, "pooling": "normalize(mean(unit_source_vectors)); then project once",
                                  "training_only": True, "same_ids_all_arms": True},
              "raw_source_control": raw_score, "trials": trials,
              "status": "completed" if all(t["status"] == "completed" for t in trials) else "partial_deadline",
              "elapsed_seconds": time.perf_counter()-started,
              "resource_scope": {"device": "cpu", "torch_threads": 1, "encoder_loads": 0,
                                 "provider_calls": 0, "prover_calls": 0, "projection_training": True,
                                 "deadline": "cooperative_between_optimizer_steps_and_trials"},
              "numerical_dependencies": {"torch_version": torch.__version__,
                                         "torch_git_version": torch.version.git_version, "head_precision": "float32",
                                         "raw_normalization_and_ranking_accumulation": "Python_float64",
                                         "complete_dependency_manifest": False},
              "primary_fidelity": {"status": "unavailable", "value": None},
              "native_useful_proof_coverage": {"status": "unrun", "value": None},
              "qualified": False, "production_admitted": False, "sealed_final_test_accessed": False,
              "development_used_in_fit": False, "development_checkpoint_selection": False,
              "limitations": ["Synthetic, unreviewed targets and unauthenticated cached encoder execution.",
                  "Complete targets are held out; panel_structure records composition overlap and attainable individual core relevance.",
                  "Complementary support measures demonstrations, not reconstruction, source fidelity, or proofs.",
                  "Candidate pool collapses training wording duplicates; this is a new control, distinct from prior row-pool B1.",
                  "Metrics use authored references after ranking; grouped synthetic development comparisons are descriptive here.",
                  "Hard-negative weighting distinguishes authored action facets, not independently checked semantic equivalence.",
                  "The formal encoder is a small categorical/bag rule codec; empty qualifier blocks do not exercise binder, scope, or proof structure.",
                  "Listed file bindings are not a complete dependency closure; no resumed optimizer execution is supported."]}
    report["report_sha256"] = hashlib.sha256(_canonical_bytes(report)).hexdigest()
    _write_json(output/"report.json", report)
    return report
