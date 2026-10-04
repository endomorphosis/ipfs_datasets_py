"""Compare raw, framed, and declared-context encoder inputs without semantic labels.

The raw-source receipts are reused from a bound exposed-development generation.
New inference forwards two role-marked text arms to each frozen source encoder.
Vector sensitivity does not establish interpretation, autoencoder improvement,
independent fidelity, or proof validity.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path

from .alignment_baseline import _digest, _raw
from .alignment_experiment import _write_json
from .alignment_retrieval_experiment import _read_bound_json, _verify_origins
from .alignment_study import (
    _bounded_bytes,
    _executing_repository_root,
    _observed_binding,
    _reject_constant,
    _strict_object,
)

CONFIG_SCHEMA = "alignment-context-experiment-config/v1"
REPORT_SCHEMA = "alignment-context-experiment-report/v1"
LANES = ("legacy8", "native384", "native768")
_FORBIDDEN = re.compile(r"(^|[-_])(sealed|holdout|heldout|final|test)([-_.]|$)", re.IGNORECASE)
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_context_embeddings.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_context_assay.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_context_experiment.py",
    "scripts/ops/legal_ir/run_alignment_context_experiment.py",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _binding(value):
    _require(type(value) is dict and set(value) == {"path", "sha256"}, "closed content binding required")
    name, digest = value["path"], value["sha256"]
    _require(type(name) is str and 0 < len(name) <= 4096 and "\x00" not in name
             and type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest),
             "bounded path and canonical SHA256 required")
    _require(not any(_FORBIDDEN.search(part) for part in Path(name).parts),
             "sealed/final/test context-study input forbidden")


def load_context_config(path):
    config_path = Path(path)
    raw = _bounded_bytes(config_path, 262_144)
    settings = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    fields = {"schema", "study_id", "embedding_report", "review_admission_report", "spacy_backend",
              "gte384_snapshot", "gte768_assets", "max_seconds"}
    _require(type(settings) is dict and set(settings) == fields and settings["schema"] == CONFIG_SCHEMA,
             "closed context experiment configuration required")
    _require(settings["study_id"] == "autoformalization-context-development-v1", "exposed development identity required")
    for name in ("embedding_report", "review_admission_report"):
        _binding(settings[name])
    _require(settings["spacy_backend"] == "local_en_core_web_sm", "installed native spaCy profile required")
    path = settings["gte384_snapshot"]
    _require(type(path) is str and 0 < len(path) <= 4096 and "\x00" not in path
             and Path(path).is_absolute(), "explicit local GTE-small snapshot required")
    assets = settings["gte768_assets"]
    _require(type(assets) is dict and set(assets) == {"manifest", "model_directory", "code_directory"},
             "closed native768 asset configuration required")
    _binding(assets["manifest"])
    for name in ("model_directory", "code_directory"):
        path = assets[name]
        _require(type(path) is str and 0 < len(path) <= 4096 and "\x00" not in path
                 and Path(path).is_absolute(), "explicit native768 asset directories required")
    seconds = settings["max_seconds"]
    _require(type(seconds) in (int, float) and 1 <= seconds <= 900 and math.isfinite(seconds), "invalid max_seconds")
    return settings, {"path": str(config_path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _report_integrity(value, schema):
    _require(type(value) is dict and value.get("schema") == schema
             and value.get("report_sha256") == _digest({k: v for k, v in value.items() if k != "report_sha256"}),
             "content-bound predecessor report required")
    _require(value.get("evaluation_role") == "exposed_development"
             and all(value.get(field) is False for field in (
                 "qualified", "production_admitted", "source_semantics_verified" if "source_semantics_verified" in value
                 else "source_fidelity_established", "proof_authority", "original_validation_accessed", "sealed_final_test_accessed",
             )), "predecessor scope differs")


def _sources(repository, prior, review):
    expected = {}
    for source in [*prior["source_bindings"], *review["source_bindings"]]:
        path = Path(source["path"])
        if path.is_absolute():
            _require(path.is_relative_to(repository), "bound source must remain in canonical repository")
            path = path.relative_to(repository)
        relative = str(path)
        _require(relative not in expected or expected[relative] == source["sha256"], "predecessor source generations disagree")
        expected[relative] = source["sha256"]
    observed = [_observed_binding(repository, {"path": path, "sha256": digest}) for path, digest in sorted(expected.items())]
    for relative in _SOURCE_FILES:
        _require(relative not in expected, "new context owner already appears in predecessor source generation")
        raw = _bounded_bytes(repository / relative, 1_000_000)
        observed.append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "digest_verified": True})
    _verify_origins(repository, observed)
    return observed


def _deadline(deadline):
    _require(time.perf_counter() <= deadline, "cooperative context experiment deadline exceeded")


def _produce_lane(lane_id, inputs, settings, repository):
    from .alignment_context_embeddings import run_context_lane

    if lane_id == "legacy8":
        return run_context_lane(inputs, lane_id, backend=settings["spacy_backend"])
    if lane_id == "native384":
        return run_context_lane(inputs, lane_id, snapshot_path=settings["gte384_snapshot"])
    assets = settings["gte768_assets"]
    path = Path(assets["manifest"]["path"])
    path = path if path.is_absolute() else repository / path
    return run_context_lane(inputs, lane_id, manifest_path=path,
                            expected_manifest_sha256=assets["manifest"]["sha256"],
                            model_directory=assets["model_directory"], code_directory=assets["code_directory"])


def _check_unqualified(value):
    _require(all(value.get(name) is False for name in (
        "qualified", "proof_authority", "source_fidelity_established", "context_semantics_applied",
    )), "context sensitivity cannot acquire semantic authority")


def _comparable_backends(raw_lane, context_lane):
    """Bind comparisons to the same observed encoder, assets and runtime recipe."""
    raw = raw_lane["backend_evidence"]
    context = context_lane["transport_lane"]["backend_evidence"]
    if context_lane["status"] == "unavailable":
        return {"status": "unavailable", "profile_id": raw["profile_id"],
                "compared_identity_sha256": None, "independent_runtime_attestation": False}
    fields = ("profile_id", "execution_kind", "execution_profile", "implementation", "runtime_versions", "asset_evidence")
    _require(all(_raw(raw[name]) == _raw(context[name]) for name in fields),
             "raw and framed encoder backend profiles, assets or runtimes differ")
    identity = {name: raw[name] for name in fields}
    if raw_lane["lane_id"] == "legacy8" and raw["execution_kind"] == "observed_native":
        keys = ("codec_snapshot", "model_identity", "numerical_snapshot")
        _require(all(_raw(raw["production_evidence"][name]) == _raw(context["production_evidence"][name])
                     for name in keys), "raw and framed spaCy model or codec identity differs")
        identity["spacy_production_identity"] = {name: raw["production_evidence"][name] for name in keys}
    if raw["execution_kind"] == "observed_native" and raw_lane["lane_id"] in ("native384", "native768"):
        key = "model" if raw_lane["lane_id"] == "native384" else "complete_checkpoint_loading"
        _require(_raw(raw["production_evidence"][key]) == _raw(context["production_evidence"][key]),
                 "raw and framed native model or complete checkpoint identity differs")
        identity["native_model_identity"] = raw["production_evidence"][key]
    return {"status": "matched_observed_profile", "profile_id": raw["profile_id"],
            "compared_identity_sha256": _digest(identity), "independent_runtime_attestation": False}


def run_context_experiment(config_path, repository_root, workspace_root, output_directory):
    """Produce a new exact-text representation generation and reference-free assays."""
    started = time.perf_counter()
    repository, workspace = Path(repository_root).resolve(), Path(workspace_root).resolve()
    output = Path(output_directory)
    _require(repository == _executing_repository_root(), "repository must match executing context package")
    _require(not output.exists() and not output.is_symlink(), "fresh output directory required")
    for parent in output.parents:
        _require(not parent.is_symlink(), "symlink output parent forbidden")
    settings, config_binding = load_context_config(config_path)
    deadline = started + settings["max_seconds"]
    for name in ("embedding_report", "review_admission_report"):
        _binding(settings[name])
    _, prior = _read_bound_json(workspace, settings["embedding_report"])
    _report_integrity(prior, "alignment-embedding-experiment-report/v1")
    _require(prior["status"] == "completed" and prior["context_applied_to_embeddings"] is False
             and prior["model_autoencoder_training_executed"] is False
             and prior["query_targets_used_in_embedding"] is False, "raw source baseline scope differs")
    _, review = _read_bound_json(workspace, settings["review_admission_report"])
    _report_integrity(review, "alignment-richer-review-admission-artifact/v1")
    _require(review["status"] == "pending" and type(review["submission_count"]) is int
             and review["submission_count"] == 0 and review["submission_bindings"] == []
             and type(review["completed_independent_reviews"]) is int and review["completed_independent_reviews"] == 0
             and review["reviewer_identity_authenticated"] is False
             and review["source_author_independence_authenticated"] is False,
             "bound zero-submission pending review generation required")
    source_bindings = _sources(repository, prior, review)
    protocols = [_observed_binding(workspace, {"path": v["path"], "sha256": v["sha256"]})
                 for v in prior["protected_protocol_bindings"]]
    asset_binding = _observed_binding(repository, settings["gte768_assets"]["manifest"])
    _require(_raw(prior["configuration"]["gte768_assets"]) == _raw(settings["gte768_assets"])
             and prior["configuration"]["gte384_snapshot"] == settings["gte384_snapshot"]
             and prior["configuration"]["spacy_backend"] == settings["spacy_backend"],
             "raw and context arms must use the same pinned source encoder assets")

    from .alignment_context_assay import compare_context_embeddings, validate_context_assay
    from .alignment_context_embeddings import (
        prepare_context_embedding_inputs,
        validate_context_embedding_lane,
    )
    from .alignment_richer_embeddings import (
        prepare_richer_embedding_inputs,
        validate_embedding_lane,
        validate_richer_embedding_inputs,
    )
    from .alignment_richer_panel import validate_alignment_richer_panel
    from .alignment_richer_review import validate_richer_review_bundle
    from .alignment_richer_review_admission import validate_richer_review_admission

    _binding({"path": prior["panel_binding"]["path"], "sha256": prior["panel_binding"]["sha256"]})
    _, panel = _read_bound_json(workspace, prior["panel_binding"])
    validate_alignment_richer_panel(panel)
    review_bundle_binding = prior["independent_review_bundle_binding"]
    _require(_raw(review["bundle_binding"]) == _raw(review_bundle_binding), "review and encoder generations bind different inputs")
    _, bundle = _read_bound_json(workspace, review_bundle_binding)
    preparation = validate_richer_review_bundle(bundle)
    _require(_raw(bundle["organizer_payload"]["source_panel"]) == _raw(panel)
             and _raw(preparation) == _raw(prior["independent_review_status"])
             and _raw(preparation) == _raw(review["preparation_validation"]), "review preparation differs from bound source/context panel")
    review_validation = validate_richer_review_admission(review["receipt"], bundle, [])
    _require(_raw(review_validation) == _raw(review["admission_validation"])
             and review_validation["status_counts"]["pending"] == 34,
             "review status does not replay against the blank packet")
    _, raw_inputs = _read_bound_json(workspace, prior["embedding_input_binding"])
    validate_richer_embedding_inputs(raw_inputs)
    _require(_raw(raw_inputs) == _raw(prepare_richer_embedding_inputs(panel)), "raw baseline inputs differ from original source/context identities")
    inputs = prepare_context_embedding_inputs(panel)
    lanes, assays, comparable_backends = {}, {}, {}
    raw_bindings = {}
    for lane_id in LANES:
        _deadline(deadline)
        binding = prior["lane_bindings"][lane_id]
        _, raw_lane = _read_bound_json(workspace, binding)
        validate_embedding_lane(raw_lane, raw_inputs)
        _require(raw_lane["status"] == "produced", "complete saved native raw baseline required")
        raw_bindings[lane_id] = binding
        context_lane = _produce_lane(lane_id, inputs, settings, repository)
        validate_context_embedding_lane(context_lane, inputs)
        _check_unqualified(context_lane)
        comparable_backends[lane_id] = _comparable_backends(raw_lane, context_lane)
        _deadline(deadline)
        assay = compare_context_embeddings(inputs, raw_inputs, raw_lane, context_lane)
        validate_context_assay(assay, inputs, raw_inputs, raw_lane, context_lane)
        _check_unqualified(assay)
        lanes[lane_id], assays[lane_id] = context_lane, assay
    _deadline(deadline)
    _require(_raw(source_bindings) == _raw(_sources(repository, prior, review)), "executing sources changed during context run")
    _require(config_binding["sha256"] == load_context_config(config_path)[1]["sha256"], "configuration changed during context run")
    for binding in [settings["embedding_report"], settings["review_admission_report"], prior["panel_binding"],
                    review_bundle_binding, prior["embedding_input_binding"], *raw_bindings.values()]:
        _read_bound_json(workspace, binding)
    for binding in protocols:
        _observed_binding(workspace, {"path": binding["path"], "sha256": binding["sha256"]})
    _observed_binding(repository, settings["gte768_assets"]["manifest"])
    output.mkdir(parents=True, exist_ok=False)
    input_binding = _write_json(output / "context_inputs.json", inputs)
    lane_bindings = {lane: _write_json(output / (lane + "_context_embeddings.json"), v) for lane, v in lanes.items()}
    assay_bindings = {lane: _write_json(output / (lane + "_assay.json"), v) for lane, v in assays.items()}
    report = {
        "schema": REPORT_SCHEMA, "study_id": settings["study_id"], "status": "completed",
        "evaluation_role": "exposed_development", "configuration": settings, "configuration_binding": config_binding,
        "predecessor_binding": settings["embedding_report"], "review_admission_binding": settings["review_admission_report"],
        "source_bindings": source_bindings, "protected_protocol_bindings": protocols, "asset_manifest_binding": asset_binding,
        "panel_binding": prior["panel_binding"], "raw_input_binding": prior["embedding_input_binding"],
        "raw_lane_bindings": raw_bindings, "context_input_binding": input_binding,
        "context_lane_bindings": lane_bindings, "assay_bindings": assay_bindings,
        "backend_comparability": comparable_backends,
        "summaries": {lane: assay["summaries"] for lane, assay in assays.items()},
        "context_pairs": {lane: assay["context_pairs"] for lane, assay in assays.items()},
        "embedding_receipts_produced": {lane: len(v["receipts"]) for lane, v in lanes.items()},
        "context_lane_statuses": {lane: v["status"] for lane, v in lanes.items()},
        "embedded_vector_counts": {lane: sum(row["status"] == "embedded" for row in v["receipts"])
                                   for lane, v in lanes.items()},
        "assay_evidence_scopes": {lane: v["evidence_scope"] for lane, v in assays.items()},
        "encoder_execution_executed": {lane: v["encoder_execution_executed"] for lane, v in lanes.items()},
        "source_input_dimensions": [8, 384, 768], "raw_source_receipts_reused": 102,
        "original_input_count": 34, "new_input_count_per_lane": 68,
        "context_input_forwarding_recipe": "two_arms_same_role_marked_json_shell_context_withheld_or_declared",
        "context_semantics_applied": False, "context_resolution_executed": False,
        "source_fidelity_established": False, "independent_fidelity_available": False,
        "query_targets_used_in_embedding": False, "query_reference_scoring_executed": False,
        "model_autoencoder_training_executed": False, "paired_contrastive_training_executed": False,
        "ridge_training_executed": False, "query_generation_executed": False,
        "leanstral_hidden_states_extracted": False, "new_independent_reviews_created": 0,
        "independent_review_status": review_validation, "independent_review_bundle_binding": review_bundle_binding,
        "native_useful_proof_coverage": {"status": "unrun", "value": None},
        "sealed_final_test_accessed": False, "original_validation_accessed": False,
        "complete_dependency_manifest": False, "dependency_binding_scope": "listed_owner_files_not_dependency_closure",
        "qualified": False, "production_admitted": False, "proof_authority": False,
        "resource_scope": {"local_cpu_only": True, "llm_calls": 0, "prover_calls": 0,
            "raw_baseline_model_inference_repeated": False, "model_downloads": 0,
            "deadline_kind": "cooperative_between_native_calls_without_preemption"},
        "limitations": [
            "Different context vectors measure numerical sensitivity to provided tokens, not correct interpretation.",
            "The two contextual assumptions are authored inputs; all 34 human reviews remain pending.",
            "Framing introduces extra tokens; the matched empty-assumption arm isolates that input change.",
            "Declared text and bindings repeat some cues; their independent effects are not isolated here.",
            "The inner exact-text producer receipt describes serialized transport text, not original raw-source encoding.",
            "No decoder, trained autoencoder, retrieval policy, generation or native proof is evaluated.",
        ], "elapsed_seconds": time.perf_counter() - started,
    }
    report["report_sha256"] = _digest(report)
    _write_json(output / "report.json", report)
    return report


__all__ = ["load_context_config", "run_context_experiment"]
