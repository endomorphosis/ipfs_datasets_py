"""Real native source embeddings and TRAIN-only richer structural retrieval.

This is an exposed-development source-to-fixed-formal-anchor ridge prototype,
not autoencoder training, statement generation, human review or a proof run.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

from .alignment_baseline import _digest, _raw
from .alignment_experiment import _write_json
from .alignment_retrieval_experiment import _read_bound_json, _verify_origins
from .alignment_richer_panel import validate_alignment_richer_panel
from .alignment_study import (
    _bounded_bytes,
    _executing_repository_root,
    _observed_binding,
    _reject_constant,
    _strict_object,
)

CONFIG_SCHEMA = "alignment-embedding-experiment-config/v1"
REPORT_SCHEMA = "alignment-embedding-experiment-report/v1"
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_embeddings.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_retrieval.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_embedding_experiment.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/source_embeddings_768_complete.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/source_embeddings_768.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/gte_multilingual_profile.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_embedding_runtime.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_embedding_production.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_lineages/legacy_v1/_linguistic_snapshot/spacy_modal_codec.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_lineages/legacy_v1/linguistic.py",
    "scripts/ops/legal_ir/run_alignment_embedding_experiment.py",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _binding(value):
    _require(type(value) is dict and set(value) == {"path", "sha256"}, "closed content binding required")
    _require(type(value["path"]) is str and 0 < len(value["path"]) <= 4096
             and type(value["sha256"]) is str and len(value["sha256"]) == 64
             and all(char in "0123456789abcdef" for char in value["sha256"]), "bounded path and SHA256 required")


def load_embedding_config(path):
    raw = _bounded_bytes(Path(path), 262_144)
    settings = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    _require(type(settings) is dict and set(settings) == {"schema", "study_id", "structure_report", "spacy_backend",
        "gte384_snapshot", "gte768_assets", "max_seconds"} and settings["schema"] == CONFIG_SCHEMA,
        "closed embedding experiment config required")
    _require(settings["study_id"] == "autoformalization-richer-embedding-development-v1", "exposed development identity required")
    _binding(settings["structure_report"])
    _require(settings["spacy_backend"] == "local_en_core_web_sm", "native installed spaCy backend required")
    _require(type(settings["gte384_snapshot"]) is str and 0 < len(settings["gte384_snapshot"]) <= 4096
             and Path(settings["gte384_snapshot"]).is_absolute(), "explicit local GTE-small snapshot required")
    assets = settings["gte768_assets"]
    _require(type(assets) is dict and set(assets) == {"manifest", "model_directory", "code_directory"}, "closed native768 assets required")
    _binding(assets["manifest"])
    _require(all(type(assets[key]) is str and 0 < len(assets[key]) <= 4096 and Path(assets[key]).is_absolute()
                 for key in ("model_directory", "code_directory")), "explicit native768 directories required")
    seconds = settings["max_seconds"]
    _require(type(seconds) in (int, float) and 1 <= seconds <= 900 and math.isfinite(seconds), "invalid max_seconds")
    return settings, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _sources(repository, prior):
    observed = [_observed_binding(repository, {"path": item["path"], "sha256": item["sha256"]})
                for item in prior["source_bindings"]]
    for relative in _SOURCE_FILES:
        raw = _bounded_bytes(repository / relative, 1_000_000)
        observed.append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    _verify_origins(repository, observed)
    return observed


def _deadline(deadline):
    _require(time.perf_counter() <= deadline, "cooperative embedding experiment deadline exceeded")


def _produce_lane(lane_id, inputs, settings, repository):
    """Forward closed source-only inputs to actual local encoder owners."""
    from .alignment_richer_embeddings import run_gte384, run_gte768, run_spacy8

    if lane_id == "legacy8":
        return run_spacy8(inputs, backend=settings["spacy_backend"])
    if lane_id == "native384":
        return run_gte384(inputs, snapshot_path=settings["gte384_snapshot"])
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_runtime import (
        _offline_guard,
    )

    assets = settings["gte768_assets"]
    manifest = Path(assets["manifest"]["path"])
    manifest = manifest if manifest.is_absolute() else repository / manifest
    # This dedicated CLI process retains the complete producer's CPU recipe.
    # Restore inherited thread/environment settings after real inference.
    with _offline_guard():
        import torch
        threads = torch.get_num_threads()
        try:
            torch.set_num_threads(1)
            return run_gte768(inputs, manifest_path=manifest, expected_manifest_sha256=assets["manifest"]["sha256"],
                             model_directory=assets["model_directory"], code_directory=assets["code_directory"])
        finally:
            torch.set_num_threads(threads)


def _summarize_scores(scored):
    results = {}
    for policy in ("source_cosine", "structural_ridge"):
        admitted = [row["score"]["policies"][policy] for row in scored
                    if row["score"]["policies"][policy]["status"] == "available"]
        values = [row["authored_metrics"]["graded_facet_ndcg"] for row in admitted
                  if row["authored_metrics"]["graded_facet_ndcg"] is not None]
        results[policy] = {"eligible_positive_queries": len(scored), "scored_queries": len(admitted),
                          "ndcg_queries": len(values), "mean_graded_facet_ndcg": math.fsum(values) / len(values) if values else None,
                          "unscoped_qualifier_coverage": {}}
        for facet in ("conditions", "exceptions", "temporal"):
            coverages = [row["authored_metrics"]["selected_coverage"]["unscoped_qualifier_identity"][facet]
                         for row in admitted]
            recalls = [coverage["reference_identity_recall"] for coverage in coverages]
            recalls = [value for value in recalls if value is not None]
            ceilings = [row["score"]["pool_coverage_ceiling"]["unscoped_qualifier_identity"][facet] for row in scored]
            ceiling_recalls = [coverage["reference_identity_recall"] for coverage in ceilings
                               if coverage["reference_identity_recall"] is not None]
            selected_required = sum(coverage["reference_atoms"] for coverage in coverages)
            pool_required = sum(coverage["reference_atoms"] for coverage in ceilings)
            results[policy]["unscoped_qualifier_coverage"][facet] = {
                "queries": len(recalls), "mean_identity_recall": math.fsum(recalls) / len(recalls) if recalls else None,
                "occurrence_weighted_identity_recall": sum(len(coverage["matched_atoms"]) for coverage in coverages) / selected_required
                    if selected_required else None,
                "eligible_pool_ceiling_mean_identity_recall": math.fsum(ceiling_recalls) / len(ceiling_recalls) if ceiling_recalls else None,
                "eligible_pool_ceiling_occurrence_weighted_identity_recall": sum(len(coverage["matched_atoms"]) for coverage in ceilings) / pool_required
                    if pool_required else None}
    return results


def run_embedding_experiment(config_path, repository_root, workspace_root, output_directory):
    started = time.perf_counter()
    repository, workspace, output = Path(repository_root).resolve(), Path(workspace_root).resolve(), Path(output_directory)
    _require(repository == _executing_repository_root(), "repository must match executing study package")
    _require(not output.exists() and not output.is_symlink(), "fresh output directory required")
    settings, config_binding = load_embedding_config(config_path)
    deadline = started + settings["max_seconds"]
    _, prior = _read_bound_json(workspace, settings["structure_report"])
    _require(type(prior) is dict and prior.get("schema") == "alignment-structure-experiment-report/v1"
             and prior.get("status") == "completed"
             and prior["report_sha256"] == _digest({key: value for key, value in prior.items() if key != "report_sha256"}),
             "completed content-bound structural report required")
    _require(prior["evaluation_role"] == "exposed_development" and prior["target_origin"] == "synthetic_authored_unreviewed"
             and all(prior[key] is False for key in ("qualified", "production_admitted", "source_fidelity_established",
                 "sealed_final_test_accessed", "original_validation_accessed", "query_targets_used_in_construction")), "predecessor scope differs")
    bindings = _sources(repository, prior)
    protocols = [_observed_binding(workspace, {"path": item["path"], "sha256": item["sha256"]})
                 for item in prior["protected_protocol_bindings"]]
    assets_binding = _observed_binding(repository, settings["gte768_assets"]["manifest"])
    _, panel = _read_bound_json(workspace, prior["panel_binding"])
    validate_alignment_richer_panel(panel)
    from .alignment_richer_embeddings import (
        prepare_richer_embedding_inputs,
        validate_embedding_lane,
    )
    from .alignment_richer_retrieval import (
        fit_structural_ridge,
        rank_richer_candidates,
        score_richer_rankings,
    )
    from .alignment_richer_review import validate_richer_review_bundle

    review_binding = prior["review_bindings"]["full_bundle_private"]
    _, review_bundle = _read_bound_json(workspace, review_binding)
    review_validation = validate_richer_review_bundle(review_bundle)
    _require(_raw(review_validation) == _raw(prior["review_preparation_validation"])
             and _raw(review_bundle["organizer_payload"]["source_panel"]) == _raw(panel),
             "independent review preparation differs from bound blank richer inputs")

    inputs = prepare_richer_embedding_inputs(panel)
    metadata = {"sha256:" + row["input_sha256"]: row for row in panel["rows"]}
    _require(len(metadata) == len(inputs["rows"]), "embedding input identity count differs")
    train_ids = {identity for identity, row in metadata.items() if row["split"] == "train" and row["row_kind"] == "positive"}
    query_ids = {identity for identity, row in metadata.items() if row["split"] == "validation" and row["context"]["role"] == "none_required"}
    contextual_ids = {identity for identity, row in metadata.items() if row["context"]["role"] != "none_required"}
    _require(len(train_ids) == 16 and len(query_ids) == 16 and len(contextual_ids) == 2,
             "fixed authored train/development/context accounting differs")
    productions, fitted, evaluated, summaries = {}, {}, {}, {}
    for lane_id in ("legacy8", "native384", "native768"):
        _deadline(deadline)
        lane = _produce_lane(lane_id, inputs, settings, repository)
        validate_embedding_lane(lane, inputs)
        productions[lane_id] = lane
        _deadline(deadline)
        if lane["status"] != "produced":
            summaries[lane_id] = {"status": "unavailable_complete_embeddings", "dimension": lane["dimension"], "scored_queries": 0}
            continue
        vectors = {row["id"]: row["embedding"] for row in lane["receipts"]}
        _require(set(vectors) == set(metadata), "complete lane receipt identities differ")
        training = [{"id": identity, "group_id": metadata[identity]["group_id"], "source_vector": vectors[identity],
                     "target": metadata[identity]["target"]} for identity in sorted(train_ids)]
        head = fit_structural_ridge(training, dimension=2048, seed=0, alpha=1.0)
        rankings, scored = [], []
        for identity in sorted(query_ids):
            _deadline(deadline)
            row = metadata[identity]
            query = {"id": identity, "group_id": row["group_id"], "source_vector": vectors[identity]}
            ranked = rank_richer_candidates(query, training, head, top_k=5)
            rankings.append({"id": identity, "input_sha256": row["input_sha256"], "ranking": ranked,
                             "diagnostic_role": "positive_posthoc_scoring" if row["row_kind"] == "positive" else "unsupported_or_ambiguous_input_no_admission_claim"})
            # Query references are first supplied after the source-only ranking.
            if row["row_kind"] == "positive":
                scored.append({"id": identity, "score": score_richer_rankings(ranked, row["target"], training)})
        _require(len(scored) == 8 and len(rankings) == 16, "fixed scored/diagnostic query accounting differs")
        fitted[lane_id] = head
        evaluated[lane_id] = {"schema": "alignment-richer-retrieval-evaluation/v1", "rankings": rankings,
                              "posthoc_scores": scored, "query_reference_entered_ranking": False, "qualified": False}
        summaries[lane_id] = {"status": "evaluated", "dimension": lane["dimension"], "training_rows": 16,
                              "ranked_positive_queries": 8, "ranked_unscored_negative_queries": 8,
                              "excluded_context_queries": 2, "policies": _summarize_scores(scored)}
    _deadline(deadline)
    _require(_raw(bindings) == _raw(_sources(repository, prior)), "executing source bytes changed during run")
    _require(config_binding["sha256"] == load_embedding_config(config_path)[1]["sha256"], "configuration changed during run")
    _read_bound_json(workspace, settings["structure_report"])
    _read_bound_json(workspace, prior["panel_binding"])
    _read_bound_json(workspace, review_binding)
    _observed_binding(repository, settings["gte768_assets"]["manifest"])
    for item in prior["protected_protocol_bindings"]:
        _observed_binding(workspace, {"path": item["path"], "sha256": item["sha256"]})
    output.mkdir(parents=True, exist_ok=False)
    input_binding = _write_json(output / "embedding_inputs.json", inputs)
    lane_bindings = {lane: _write_json(output / (lane + "_embeddings.json"), data) for lane, data in productions.items()}
    head_bindings = {lane: _write_json(output / (lane + "_ridge.json"), data) for lane, data in fitted.items()}
    evaluation_bindings = {lane: _write_json(output / (lane + "_retrieval.json"), data) for lane, data in evaluated.items()}
    report = {"schema": REPORT_SCHEMA, "study_id": settings["study_id"], "status": "completed",
              "configuration": settings, "configuration_binding": config_binding, "predecessor_binding": settings["structure_report"],
              "source_bindings": bindings, "protected_protocol_bindings": protocols, "asset_manifest_binding": assets_binding,
              "panel_binding": prior["panel_binding"], "embedding_input_binding": input_binding, "lane_bindings": lane_bindings,
              "ridge_head_bindings": head_bindings, "retrieval_evaluation_bindings": evaluation_bindings, "summaries": summaries,
              "source_input_dimensions": [8, 384, 768], "formal_hash_dimension": 2048, "formal_hash_seed": 0,
              "ridge_alpha": 1.0, "ridge_intercept": False, "trained_ridge_heads": len(fitted), "training_rows_per_head": 16,
              "model_autoencoder_training_executed": False, "paired_contrastive_training_executed": False,
              "embedding_receipts_produced": {lane: len(data["receipts"]) for lane, data in productions.items()},
              "query_targets_used_in_embedding": False, "query_targets_used_in_fit_or_ranking": False,
              "development_used_in_fit": False, "development_exposed_in_prior_grammar_design": True,
              "context_applied_to_embeddings": False, "context_resolution_executed": False,
              "query_generation_executed": False, "source_fidelity_established": False, "proof_authority": False,
              "leanstral_hidden_states_extracted": False, "independent_review_status": review_validation,
              "independent_review_bundle_binding": review_binding,
              "new_independent_reviews_created": 0, "native_useful_proof_coverage": {"status": "unrun", "value": None},
              "evaluation_role": "exposed_development", "target_origin": "synthetic_authored_unreviewed",
              "sealed_final_test_accessed": False, "original_validation_accessed": False,
              "complete_dependency_manifest": False, "dependency_binding_scope": "listed_study_and_core_source_files_only",
              "qualified": False, "production_admitted": False,
              "resource_scope": {"encoder_lanes_attempted": 3, "local_cpu_only": True, "llm_calls": 0, "prover_calls": 0,
                  "deadline_kind": "cooperative_between_lanes_and_queries_no_native_call_preemption"},
              "limitations": ["The 16 TRAIN targets include no exact counterpart to any of the eight positive development references.",
                  "Rankings are scored against unreviewed authored facets and their attainable TRAIN-pool ceilings, not independent source meaning.",
                  "This fits tiny ridge probes against fixed hashed anchors; it does not evaluate trained autoencoder checkpoints or a contrastive objective.",
                  "Eight unsupported/ambiguous queries have unscored diagnostic rankings, not a certified abstention or ambiguity decision.",
                  "Two explicit-context queries are embedded source-only and excluded from semantic ranking scores; context is not resolved.",
                  "Finite formal hashing is lossy; distinct target separation is not a fidelity guarantee.",
                  "Leanstral embeddings, useful native proof coverage and authenticated richer reviews remain unrun or unavailable."],
              "elapsed_seconds": time.perf_counter() - started}
    report["report_sha256"] = _digest(report)
    _write_json(output / "report.json", report)
    return report
