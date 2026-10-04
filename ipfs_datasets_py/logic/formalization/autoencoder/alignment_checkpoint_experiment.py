"""Expose frozen learned source384 representations under a bounded new profile."""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

from .alignment_baseline import _digest, _raw
from .alignment_context_experiment import _report_integrity
from .alignment_experiment import _write_json
from .alignment_retrieval_experiment import _read_bound_json, _verify_origins
from .alignment_study import (
    _bounded_bytes,
    _executing_repository_root,
    _observed_binding,
    _reject_constant,
    _strict_object,
)

CONFIG_SCHEMA = "alignment-checkpoint-experiment-config/v1"
REPORT_SCHEMA = "alignment-checkpoint-experiment-report/v1"
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_checkpoint_representations.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_representation_retrieval.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_checkpoint_experiment.py",
    "scripts/ops/legal_ir/run_alignment_checkpoint_experiment.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/gte_bridge_teacher.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/gte_worker_contract.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/gte_migration_inventory.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_transfer_replay.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_latent_formula.py",
)
_FLAGS = ("qualified", "production_admitted", "proof_authority", "source_fidelity_established",
    "independent_fidelity_available", "context_resolution_executed", "context_semantics_applied",
    "original_validation_accessed", "sealed_final_test_accessed", "model_training_executed",
    "source_encoder_inference_executed", "formula_generation_executed", "leanstral_hidden_states_extracted")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _config(path):
    raw = _bounded_bytes(Path(path), 262144)
    value = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    fields = {"schema", "study_id", "context_report", "source384_checkpoint", "preserved_repository_root",
              "spacy_manifest", "spacy_core", "parallel_lineages", "max_seconds"}
    _require(type(value) is dict and set(value) == fields and value["schema"] == CONFIG_SCHEMA
             and value["study_id"] == "autoformalization-checkpoint-development-v1", "closed checkpoint-study configuration required")
    for name in ("context_report", "source384_checkpoint", "spacy_manifest", "spacy_core", "parallel_lineages"):
        b = value[name]
        _require(type(b) is dict and set(b) == {"path", "sha256"}
                 and type(b["path"]) is str and 0 < len(b["path"]) <= 4096 and "\x00" not in b["path"]
                 and type(b["sha256"]) is str and len(b["sha256"]) == 64
                 and all(c in "0123456789abcdef" for c in b["sha256"]), "exact file bindings required")
    _require(type(value["preserved_repository_root"]) is str and Path(value["preserved_repository_root"]).is_absolute()
             and "\x00" not in value["preserved_repository_root"], "explicit preserved donor source tree required")
    seconds = value["max_seconds"]
    _require(type(seconds) in (int, float) and 1 <= seconds <= 600 and math.isfinite(seconds), "bounded max_seconds required")
    return value, {"path": str(Path(path).absolute()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _scope(value):
    _require(all(value.get(key) is False for key in ("qualified", "proof_authority", "source_fidelity_established")),
             "checkpoint diagnostics cannot grant authority")


def _sources(repository, predecessor):
    pins = {v["path"]: v["sha256"] for v in predecessor["source_bindings"]}
    observed = [_observed_binding(repository, {"path": name, "sha256": pin}) for name, pin in sorted(pins.items())]
    for name in _SOURCE_FILES:
        if name not in pins:
            data = _bounded_bytes(repository / name, 8 * 1024 * 1024)
            observed.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "digest_verified": True})
    _verify_origins(repository, observed)
    return observed


def _readiness(settings, workspace, plan, raw_lanes):
    manifest_path, manifest = _read_bound_json(workspace, settings["spacy_manifest"])
    core_path, core = _read_bound_json(workspace, settings["spacy_core"])
    lineages_path, lineages = _read_bound_json(workspace, settings["parallel_lineages"])
    _require(manifest_path.parent == core_path.parent and manifest["core_file"] == core_path.name
             and manifest["core_sha256"] == settings["spacy_core"]["sha256"]
             and manifest["core_bytes"] == len(core_path.read_bytes()), "spaCy bundle linkage differs")
    _require(manifest["schema"] == "legacy-linguistic-training-checkpoint/v1" and manifest["dimension"] == 8
             and manifest["profile_id"] == "legacy-linguistic-features-8d/v1"
             and manifest["configuration"]["backend"] == "local_en_core_web_sm"
             and manifest["formula_head_present"] is False
             and all(manifest[name] is False for name in ("admitted", "formalized", "independent_formula_generation", "semantic_qualification")),
             "retained spaCy profile or authority differs")
    identity_raw = json.dumps(manifest["linguistic_identity"], sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    _require(hashlib.sha256(identity_raw).hexdigest() == manifest["linguistic_identity_sha256"], "spaCy identity digest differs")
    tables = {name: len(value) for name, value in core.items() if name.endswith("_embedding_weights") and type(value) is dict}
    _require(len(tables) == 13 and not any(tables.values()), "selected spaCy checkpoint vector tables differ")
    heads = {name: len(value) for name, value in core.items() if "logit" in name and type(value) is dict}
    selected = [v for v in lineages["lanes"] if v["lane_id"] == "multilingual_768d"]
    _require(lineages["schema"] == "gte-parallel-lineage-plan/v1" and len(selected) == 1
             and selected[0]["checkpoint"] is None, "selected 768D checkpoint declaration differs")
    for lane in raw_lanes.values():
        _require(lane["status"] == "produced", "saved native backbone execution required")
    return {"schema": "alignment-selected-checkpoint-readiness/v1", "legacy8": {
        "status": "selected_spacy_vector_weight_tables_empty", "manifest_binding": settings["spacy_manifest"],
        "core_binding": settings["spacy_core"], "vector_weight_table_rows": tables,
        "categorical_logit_table_rows": heads, "decoded_sample_memory_rows": len(core["decoded_embeddings"]),
        "bundle_source_identity": manifest["linguistic_identity"], "runtime_reload_executed": False,
        "vector_endpoint_executed": False, "complete_historical_teacher_equivalence": False},
        "source384": {"status": "projection_only_profile_prepared", "native_input_dimension": 384,
            "endpoint_dimensions": plan["endpoint_dimensions"], "checkpoint_binding": settings["source384_checkpoint"],
            "current_full_decoder_admitted": False, "current_full_decoder_source_drift": plan["current_full_decoder_source_drift"]},
        "multilingual768": {"status": "no_selected_trained_checkpoint", "catalog_binding": settings["parallel_lineages"],
            "native_source_vectors_available": True, "autoencoder_checkpoint": None,
            "absence_scope": "selected_catalog_generation_not_exhaustive_filesystem_search", "learned_state_executed": False},
        "selection_policy": "predeclared_retained_assets_no_development_score_selection",
        "model_inference_executed": False, "original_corpus_rows_read": False, "qualified": False,
        "source_fidelity_established": False, "proof_authority": False,
        "inspection_paths": [str(manifest_path), str(core_path), str(lineages_path)]}


def run_checkpoint_experiment(config_path, repository_root, workspace_root, output_directory):
    started = time.perf_counter()
    repository, workspace, output = Path(repository_root).resolve(), Path(workspace_root).resolve(), Path(output_directory)
    _require(repository == _executing_repository_root(), "canonical executing repository required")
    _require(not output.exists() and not output.is_symlink()
             and not any(p.is_symlink() for p in output.parents), "fresh ordinary output directory required")
    settings, config_binding = _config(config_path)
    _, prior = _read_bound_json(workspace, settings["context_report"])
    _report_integrity(prior, "alignment-context-experiment-report/v1")
    _require(prior["status"] == "completed" and prior["embedded_vector_counts"] == dict.fromkeys(
        ("legacy8", "native384", "native768"), 68), "successful context generation required")
    source_bindings = _sources(repository, prior)
    from .alignment_checkpoint_representations import (
        extract_source384_representations,
        prepare_source384_representation_plan,
        validate_source384_representations,
    )
    from .alignment_representation_retrieval import (
        assay_residual_projection,
        rank_checkpoint_representations,
        score_checkpoint_representations,
        validate_checkpoint_rankings,
    )
    from .alignment_richer_embeddings import (
        prepare_richer_embedding_inputs,
        validate_embedding_lane,
    )
    from .alignment_richer_review import validate_richer_review_bundle
    from .alignment_richer_review_admission import validate_richer_review_admission

    _, panel = _read_bound_json(workspace, prior["panel_binding"])
    _, inputs = _read_bound_json(workspace, prior["raw_input_binding"])
    _require(_raw(inputs) == _raw(prepare_richer_embedding_inputs(panel)), "source input generation differs")
    raw_lanes = {name: _read_bound_json(workspace, binding)[1] for name, binding in prior["raw_lane_bindings"].items()}
    for lane in raw_lanes.values():
        validate_embedding_lane(lane, inputs)
    _, review = _read_bound_json(workspace, prior["review_admission_binding"])
    _, bundle = _read_bound_json(workspace, prior["independent_review_bundle_binding"])
    validate_richer_review_bundle(bundle)
    _require(_raw(bundle["organizer_payload"]["source_panel"]) == _raw(panel), "blank review binds different source panel")
    review_validation = validate_richer_review_admission(review["receipt"], bundle, [])
    _require(_raw(review_validation) == _raw(prior["independent_review_status"])
             and review_validation["status_counts"]["pending"] == 34, "pending review admission differs")
    checkpoint_path, _ = _read_bound_json(workspace, settings["source384_checkpoint"])
    plan = prepare_source384_representation_plan(inputs, raw_lanes["native384"], checkpoint_path=checkpoint_path,
        expected_checkpoint_sha256=settings["source384_checkpoint"]["sha256"],
        preserved_repository_root=settings["preserved_repository_root"])
    readiness = _readiness(settings, workspace, plan, raw_lanes)
    _require(time.perf_counter() - started <= settings["max_seconds"], "checkpoint preparation deadline exceeded")
    representations = extract_source384_representations(plan, inputs, raw_lanes["native384"])
    validation = validate_source384_representations(representations, inputs, raw_lanes["native384"], plan=plan)
    _scope(representations)
    rankings = rank_checkpoint_representations(panel, inputs, representations)
    validate_checkpoint_rankings(rankings, panel, inputs, representations)
    scores = score_checkpoint_representations(panel, rankings, inputs, representations)
    assay = assay_residual_projection(inputs, representations)
    for value in (readiness, rankings, scores, assay):
        _scope(value)
    _require(_raw(source_bindings) == _raw(_sources(repository, prior)), "executing source generation changed")
    _require(_raw(config_binding) == _raw(_config(config_path)[1]), "configuration changed")
    pinned_inputs = [settings[name] for name in ("context_report", "source384_checkpoint", "spacy_manifest", "spacy_core", "parallel_lineages")]
    pinned_inputs += [prior["panel_binding"], prior["raw_input_binding"], prior["review_admission_binding"],
                      prior["independent_review_bundle_binding"], *prior["raw_lane_bindings"].values()]
    for binding in pinned_inputs:
        _read_bound_json(workspace, binding)
    for binding in prior["protected_protocol_bindings"]:
        _observed_binding(workspace, {"path": binding["path"], "sha256": binding["sha256"]})
    _require(time.perf_counter() - started <= settings["max_seconds"], "cooperative checkpoint experiment deadline exceeded")
    output.mkdir(parents=True, exist_ok=False)
    artifacts = {name: _write_json(output / (name + ".json"), value) for name, value in (
        ("representation_plan", plan), ("readiness", readiness), ("representations", representations),
        ("rankings", rankings), ("scores", scores), ("numeric_assay", assay))}
    report = {"schema": REPORT_SCHEMA, "status": "completed", "study_id": settings["study_id"],
        "evaluation_role": "exposed_development", "configuration": settings, "configuration_binding": config_binding,
        "predecessor_binding": settings["context_report"], "source_bindings": source_bindings,
        "protected_protocol_bindings": prior["protected_protocol_bindings"], "pinned_input_bindings": pinned_inputs,
        "panel_binding": prior["panel_binding"], "raw_input_binding": prior["raw_input_binding"],
        "raw_lane_bindings": prior["raw_lane_bindings"], "artifact_bindings": artifacts,
        "native_source_dimension": 384, "checkpoint_endpoint_dimensions": plan["endpoint_dimensions"],
        "checkpoint_inference_rows": representations["row_count"], "model_inference_executed": representations["model_inference_executed"],
        "representation_status": representations["status"], "representation_validation": validation,
        "retrieval_summaries": {arm: value["summary"] for arm, value in scores["arms"].items()},
        "numeric_summary": assay["summary"], "independent_review_status": review_validation,
        "source_checkpoint_overlap": plan["split_overlap"], "native_useful_proof_coverage": {"status": "unrun", "value": None},
        "current_full_decoder_admitted": False, "current_full_decoder_loader_attempted": False,
        "complete_dependency_manifest": False, "dependency_scope": "listed_sources_and_preserved_donor_files_only",
        "resource_scope": {"device": "cpu", "dtype": "float32", "source_encoder_calls": 0, "prover_calls": 0,
            "llm_calls": 0, "model_downloads": 0, "optimizer_steps": 0, "deadline_kind": "cooperative_without_preemption"},
        "limitations": ["Residual branch activation requires the input skip connection; it is not a complete compressed autoencoder state.",
            "The source384 formula-conditioning state is trained for decoder initialization, not for contrastive retrieval.",
            "The public full-decoder runtime is not admitted; this independently bound projection-only route preserves original tensors.",
            "Checkpoint-source manifest hash overlap checks do not authenticate semantic split independence.",
            "Authored development retrieval relevance is separate from source fidelity and useful proof coverage.",
            "All 34 independent review items remain pending; context is withheld from this source-only checkpoint comparison."],
        "elapsed_seconds": time.perf_counter() - started, **dict.fromkeys(_FLAGS, False)}
    report["report_sha256"] = _digest(report)
    _write_json(output / "report.json", report)
    return report
