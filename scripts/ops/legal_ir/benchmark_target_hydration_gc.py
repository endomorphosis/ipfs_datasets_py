#!/usr/bin/env python3
"""Compare normal and deferred target-hydration GC in four native owner jobs.

One newly prepared, complete six-target bundle and a frozen 3+3 corpus selection
are shared by independent spawned workers, ordered normal/deferred/deferred/normal.
All normal source, target, Arrow, checkpoint and owner checks remain enabled.
This is local qualification evidence, not admission, promotion or a speed promise.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import copy
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import statistics
import sys
import time

from qualify_target_preparation_telemetry import (
    PINNED, PINNED_BYTES, PINNED_SHA, PRIOR, PRIOR_SHA, ROOT,
    prepare, sha, verify_descriptor, write,
)


ORDER = (False, True, True, False)
BRIDGES = ["modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec", "external_prover_router"]
REPORT_EXCLUSIONS = frozenset({"elapsed_seconds", "identity_hashing_seconds", "projection_profile"})
RUN_PROVENANCE = frozenset({"job_id", "run_id", "job_spec_sha256"})


def canonical(value):
    """Compare exact JSON numerics, including negative zero, without rounding."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def without_fields(value, excluded):
    if isinstance(value, dict):
        return {key: without_fields(item, excluded) for key, item in value.items() if key not in excluded}
    if isinstance(value, list):
        return [without_fields(item, excluded) for item in value]
    return value


def descriptor(path):
    return {"path": str(path), "sha256": sha(path), "bytes": Path(path).stat().st_size}


def config_probe(training_config):
    """Fresh-process complete producer/config guard; never hydrate targets here."""
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_target_preparation import target_snapshot_config
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingConfig, _worker_environment

    with _worker_environment():
        return target_snapshot_config(TrainingConfig.from_dict(training_config)).to_dict()


def spawned(function, *args):
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn")) as executor:
        return executor.submit(function, *args).result()


def validate_config(payload):
    required = {"epochs": 1, "projection_max_update_families": 1, "max_line_search_attempts": 1,
        "max_seconds": 180.0, "projection_update_backend": "python_sparse_batch", "use_sample_memory": False,
        "legal_ir_bridge_names": BRIDGES, "legal_ir_evaluate_provers": False,
        "legal_ir_parallel_workers": 1, "metric_disk_cache": 0, "profile_projection": True}
    actual = {key: payload["training_config"].get(key) for key in required}
    if actual != required or payload["autoencoder_config"] != {}:
        raise ValueError("frozen parent differs from the bounded CPU training configuration")
    if payload["candidate_storage"] != "sparse" or payload["capture_sparse_patches"] is not True:
        raise ValueError("frozen parent must capture accepted patches and persist a sparse candidate")


def artifact_parity(worker):
    """Decode normal owner-verified artifacts; remove only known run provenance."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import decode_patch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_sparse_checkpoint import decode_manifest

    expected = {"job_id": worker["job_id"], "run_id": worker["run_id"],
                "job_spec_sha256": worker["job_spec_canonical_sha256"]}
    patches, normalized_refs = [], []
    for ref in worker["sparse_patch_segments"]:
        verify_descriptor(ref)
        raw = Path(ref["path"]).read_bytes()
        segment = decode_patch(raw)
        provenance = {**expected, "commit_label": ref["capture_context"].get("label", "")}
        if dict(segment.provenance) != provenance:
            raise ValueError("accepted patch provenance differs from the current run")
        payload = json.loads(raw)["payload"]
        # The codec has validated the complete typed payload, including float
        # bits. Keep it unchanged except for the decoded provenance labels.
        payload["provenance"] = {key: value for key, value in provenance.items() if key not in RUN_PROVENANCE}
        patches.append(payload)
        normalized = canonical(payload)
        normalized_refs.append({"sha256": hashlib.sha256(normalized).hexdigest(), "bytes": len(normalized)})
    verify_descriptor(worker["candidate"])
    manifest = decode_manifest(Path(worker["candidate"]["path"]).read_bytes())
    if manifest["provenance"] != expected:
        raise ValueError("candidate manifest provenance differs from the current run")
    raw_refs = [{key: ref[key] for key in ("sha256", "bytes")} for ref in worker["sparse_patch_segments"]]
    if manifest["patches"] != raw_refs:
        raise ValueError("candidate manifest differs from the ordered accepted patches")
    normalized_manifest = copy.deepcopy(manifest)
    normalized_manifest["provenance"] = {}
    normalized_manifest["patches"] = normalized_refs
    return {"decoded_patches_without_run_provenance": patches,
            "manifest_with_normalized_patch_references": normalized_manifest,
            "raw_manifest": manifest, "raw_patch_artifacts": raw_refs,
            "raw_manifest_artifact": {key: worker["candidate"][key] for key in ("sha256", "bytes")}}


def worker_parity(worker, artifacts):
    observation = copy.deepcopy(worker["ontology_capture_observation"])
    if (observation["context_closed"] is not True or observation["observations_complete"] is not True
            or observation["reuse_qualified"] is not False or not observation["captures"]):
        raise ValueError("ontology observation must be complete, closed and explicitly unqualified for reuse")
    identity = observation["producer_identity"]
    if (identity["job_spec_sha256"] != worker["job_spec_canonical_sha256"]
            or identity["target_snapshot_id"] != worker["target_snapshot_id"]):
        raise ValueError("ontology diagnostic label differs from the current job/target")
    del identity["job_spec_sha256"]
    return {
        "training_report_without_timing_and_projection_profile": without_fields(worker["training_report"], REPORT_EXCLUSIONS),
        "projection_profile_counters": worker["training_report"]["projection_profile"]["counters"],
        "candidate_state_identity": worker["candidate_state_identity"],
        "candidate_materialized_checkpoint": worker["candidate_materialized_checkpoint"],
        "base_state_identity": worker["base_state_identity"],
        "base_materialized_checkpoint": worker["base_materialized_checkpoint"],
        "optimizer_accepted_epochs": worker["optimizer_accepted_epochs"],
        "patches": artifacts["decoded_patches_without_run_provenance"],
        "manifest": artifacts["manifest_with_normalized_patch_references"],
        "ontology_observation_without_elapsed_seconds_and_run_label": without_fields(observation, {"elapsed_seconds"}),
        "target_storage_without_timings": without_fields(worker["target_storage_statistics"], {
            "hydrate_validate_seconds", "manifest_parse_validate_seconds", "open_hash_seconds", "read_decompress_seconds"}),
    }


def collect_timings(worker, owner_seconds):
    stages = worker["training_report"]["projection_profile"]["by_stage"]
    initial_evaluate = stages["before_holdout_evaluation"]["seconds"]
    return {
        "owner_wall_seconds": owner_seconds, "owner_wall_seconds_per_training_span": owner_seconds / 3,
        "worker_seconds": worker["elapsed_seconds"], "worker_seconds_per_training_span": worker["elapsed_seconds"] / 3,
        "training_seconds": worker["training_seconds"], "training_seconds_per_training_span": worker["training_seconds"] / 3,
        "target_load_seconds": worker["target_load_seconds"],
        "target_artifact_verification_seconds": worker["target_artifact_verification_seconds"],
        "target_hydration_seconds_including_collection": worker["target_hydration_seconds"],
        "gc_explicit_collection_seconds": worker["target_hydration_gc"]["collection_seconds"],
        "initial_holdout_evaluate_seconds": initial_evaluate,
        "initial_holdout_evaluate_seconds_per_validation_sample": initial_evaluate / 3,
        "evaluation_profile_stage_seconds": {name: value["seconds"] for name, value in stages.items()
                                             if "evaluation" in name or name == "training_cache_prime"},
    }


def run(args, receipt):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_coordinator import registered_checkpoint_inputs, run_training_jobs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, verify_corpus_job_inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_bundle import load_target_artifact
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig

    if sha(PRIOR) != PRIOR_SHA:
        raise ValueError("frozen parent receipt changed")
    prior = json.loads(PRIOR.read_bytes())
    if prior["passed"] is not True:
        raise ValueError("parent native qualification did not pass")
    prior_row = prior["combined_arrow_inputs_and_feature_weights"]["jobs"][0]
    prior_worker = prior_row["worker"]
    payload = copy.deepcopy(prior_worker["job_spec"])
    prior_spec = TrainingJobSpec.from_dict(payload)
    if (prior_spec.canonical_sha256 != prior_worker["job_spec_canonical_sha256"]
            or prior_spec.schema_version != "autoencoder-training-job-v7"
            or prior_spec.base_checkpoint.sha256 != PINNED_SHA or prior_spec.base_checkpoint.bytes != PINNED_BYTES
            or prior_spec.base_checkpoint_dependencies or prior_spec.arrow_feature_weights_artifact is None
            or len(prior_spec.samples) != 3 or len(prior_spec.validation_samples) != 3):
        raise ValueError("parent combined job differs from frozen 3+3 input scope")
    validate_config(payload)
    parent_worker_path = Path(prior_spec.output_directory) / "receipt.json"
    parent_worker_ref = {**prior_row["completed"]["worker_receipt_artifact"], "path": str(parent_worker_path)}
    verify_descriptor(parent_worker_ref)
    if json.loads(parent_worker_path.read_bytes()) != prior_worker:
        raise ValueError("parent worker artifact differs from embedded receipt")
    receipt.update(parent_worker_receipt=parent_worker_ref,
        parent_job_spec_canonical_sha256=prior_spec.canonical_sha256,
        parent_input_verification=verify_corpus_job_inputs(prior_spec), selection=copy.deepcopy(prior["selection"]),
        ordered_training_samples=payload["samples"], ordered_validation_samples=payload["validation_samples"],
        effective_training_config=payload["training_config"], bridge_names=BRIDGES)
    pinned = {"path": str(PINNED), "sha256": PINNED_SHA, "bytes": PINNED_BYTES}
    verify_descriptor(pinned)
    receipt["initial_pinned_checkpoint"] = pinned
    tree_paths = require_workspace_logic_tree()
    for name, filename in (("autoencoder", "modal_autoencoder.py"), ("samples", "legal_samples.py"),
                           ("worker", "autoencoder_training_worker.py")):
        tree_paths[name] = str(ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / filename)
    expected_sources = {name: sha(path) for name, path in tree_paths.items()}
    source_paths = {ROOT / name for name in prior["source_hashes"]}
    source_paths.update(Path(path) for path in tree_paths.values())
    source_paths.update({Path(__file__).resolve(), Path(prepare.__code__.co_filename).resolve(),
        ROOT / "ipfs_datasets_py/logic/autoformal/__init__.py",
        ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_ontology_observation.py",
        ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_coordinator.py"})
    receipt["source_hashes"] = {str(path.relative_to(ROOT)): sha(path) for path in sorted(source_paths)}
    write(args.directory / "selection.json", receipt["selection"])
    initial_config = spawned(config_probe, payload["training_config"])
    config_path = args.directory / "target-config-before.json"
    write(config_path, initial_config)
    receipt["initial_target_config_artifact"] = descriptor(config_path)
    receipt["package_source_count"] = len(initial_config["code_sha256"])

    started = time.perf_counter()
    prepared = spawned(prepare, payload, str(args.directory / "targets.bundle"))
    receipt["target_preparation_dispatch_seconds"] = time.perf_counter() - started
    receipt["target_preparation"] = prepared
    preparation_path = args.directory / "target-preparation.json"
    write(preparation_path, prepared)
    # SampleRecord has no runtime sample_id. The preparer derives those IDs;
    # each normal worker independently verifies exact requested membership.
    expected_ids = set(prepared["statuses"])
    if (len(expected_ids) != 6 or prepared["sample_count"] != 6 or prepared["legal_ir_target_count"] != 6
            or set(prepared["statuses"]) != expected_ids
            or set(prepared["statuses"].values()) - {"ready", "timeout"}
            or set(prepared["bridge_report_telemetry"]) != expected_ids or prepared["admitted"] is not False):
        raise ValueError("preparation must retain six complete targets and their actual diagnostics")
    verify_descriptor(prepared["artifact"])
    bundle = load_target_artifact(prepared["artifact"]["path"], expected_sha256=prepared["artifact"]["sha256"],
        config=TargetSnapshotConfig.from_dict(initial_config), max_bytes=prepared["artifact"]["bytes"])
    try:
        if bundle.snapshot_id != prepared["target_snapshot_id"]:
            raise ValueError("fresh bundle identity differs from preparation receipt")
        receipt["preparation_bundle_statistics_without_hydration"] = dict(bundle.statistics)
    finally:
        bundle.close()
    receipt["target_status_counts"] = dict(Counter(prepared["statuses"].values()))
    receipt["target_preparation_timings"] = {
        "target_generation_seconds_for_six": prepared["target_generation_seconds"],
        "target_generation_seconds_per_span": prepared["target_generation_seconds"] / 6,
        "target_preparation_seconds_for_six": prepared["elapsed_seconds"],
        "target_preparation_seconds_per_span": prepared["elapsed_seconds"] / 6,
        "target_generation_and_artifact_seconds": prepared["target_generation_and_artifact_seconds"],
        "target_pipeline_non_generation_seconds": prepared["target_pipeline_non_generation_seconds"],
    }
    print(json.dumps({"phase": "preparation_done", "target_snapshot_id": prepared["target_snapshot_id"],
        "target_count": prepared["legal_ir_target_count"], "statuses": receipt["target_status_counts"],
        "seconds": receipt["target_preparation_dispatch_seconds"]}), flush=True)

    database, artifact_root = args.directory / "control.duckdb", args.directory / "artifacts"
    variant_id, branch = "target-hydration-gc", "qualification"
    started = time.perf_counter()
    with AutoencoderRegistry(database, artifact_root) as registry:
        def stage(ref):
            verify_descriptor(ref)
            saved = registry.stage_artifact(ref["path"], ref["sha256"])
            if saved != {key: ref[key] for key in ("sha256", "bytes")}:
                raise ValueError("staged descriptor differs from verified input")
            return saved

        def bound(ref):
            return {**ref, "path": str(registry.artifact_path(ref))}

        base = stage(pinned)
        for field in ("corpus_manifest_artifact", "corpus_index_artifact", "embedding_production_artifact",
                      "arrow_embedding_inputs_artifact", "arrow_feature_weights_artifact"):
            payload[field] = bound(stage(payload[field]))
        payload["corpus_source_artifacts"] = [bound(stage(ref)) for ref in payload["corpus_source_artifacts"]]
        targets = stage(prepared["artifact"])
        preparation_artifact = stage(descriptor(preparation_path))
        receipt["target_preparation_receipt_artifact"] = bound(preparation_artifact)
        receipt["staged_target_artifact"] = bound(targets)
        variant = {**payload["variant"], "model_variant": variant_id}
        registry.register_variant("variant", variant_id, {**variant,
            "corpus_index_binding": {"selection_sha256": payload["corpus_selection_sha256"],
                "artifact": {key: payload["corpus_index_artifact"][key] for key in ("sha256", "bytes")}},
            "embedding_production_binding": {"artifact": {
                key: payload["embedding_production_artifact"][key] for key in ("sha256", "bytes")}}})
        version = registry.register_version("base", variant_id, base)["version_id"]
        registry.initialize_head("head", variant_id, branch, version)
        receipt["initial_head"] = registry.resolve_head(variant_id, branch)
        receipt["base_version_id"] = version
        receipt["staging_seconds"] = time.perf_counter() - started
        payload.update(variant=variant, base_version_id=version, **registered_checkpoint_inputs(registry, version),
            code_identity="target-hydration-gc-current-source", expected_source_sha256=expected_sources,
            target_snapshot_id=prepared["target_snapshot_id"], target_snapshot_artifact=bound(targets))
        for ordinal, defer in enumerate(ORDER):
            policy = "deferred" if defer else "normal"
            run_id = f"gc-{ordinal}-{policy}"
            row = {"ordinal": ordinal, "policy": policy, "run_id": run_id, "passed": False}
            receipt["runs"].append(row)
            job_payload = {**payload, "job_id": run_id, "run_id": run_id,
                           "output_directory": str(args.directory / run_id)}
            spec = TrainingJobSpec.from_dict(job_payload)
            job_path = args.directory / f"{run_id}.job.json"
            write(job_path, spec.to_dict())
            metadata = {"job_spec_sha256": spec.canonical_sha256, "job_spec_artifact": registry.stage_artifact(job_path),
                "target_preparation_receipt_artifact": preparation_artifact, "target_preparation_target_artifact": targets,
                "target_preparation_snapshot_id": prepared["target_snapshot_id"],
                "target_hydration_gc_policy": {"defer_target_hydration_gc": defer,
                    "scope": "spawned native worker only; normal verified complete bundle hydration", "ordinal": ordinal}}
            row["run_metadata"] = metadata
            registry.create_run(f"create-{run_id}", run_id, variant_id, version, metadata)
            receipt["owner_dispatch_performed"] = True
            started = time.perf_counter()
            owner = run_training_jobs(registry, [spec], max_workers=1, defer_target_hydration_gc=defer)
            row["owner_wall_seconds"] = time.perf_counter() - started
            row["owner_result"] = owner
            if owner["failed"] or len(owner["completed"]) != 1:
                raise ValueError(f"normal owner dispatch did not complete: {run_id}")
            completed = owner["completed"][0]
            worker_path = Path(spec.output_directory) / "receipt.json"
            worker = json.loads(worker_path.read_bytes())
            row["worker"] = worker
            row["worker_receipt_artifact"] = bound(registry.verify_artifact(completed["worker_receipt_artifact"]))
            if registry.artifact_path(completed["worker_receipt_artifact"]).read_bytes() != worker_path.read_bytes():
                raise ValueError("owner retained worker receipt differs from local receipt")
            if (worker["execution_mode"] != "native_training" or worker["source_manifest_verified"] is not True
                    or worker["shared_targets_verified"] is not True or worker["shared_target_count"] != 6
                    or worker["shared_target_status_counts"] != receipt["target_status_counts"]
                    or worker["embedding_input_storage"] != "arrow_mapped_float32"
                    or worker["weight_storage"] != "arrow_cow_feature_embeddings"
                    or worker["target_artifact_format"] != "bundle" or worker["process_cache_initially_empty"] is not True
                    or worker["admitted"] is not False or worker["promotion_performed"] is not False
                    or completed["promoted"] is not False or completed["result"]["sparse_replay_verified"] is not True):
                raise ValueError("combined native worker verification or sparse owner replay mismatch")
            report = worker["training_report"]
            if (worker["compute_backend"]["autoencoder_compute_device"] not in {"python", "cpu"}
                    or len(report["epoch_reports"]) != 1 or report["effective_max_line_search_attempts"] != 1
                    or report["projection_update_families"] != {"candidate_update_family_count": 1, "max_update_families": 1}
                    or report["sample_memory_used"] is not False):
                raise ValueError("native execution did not retain the CPU, one-epoch, one-family, one-attempt scope")
            for phase in ("before", "after"):
                metrics = worker["training_report"][phase]
                if (metrics["legal_ir_target_count"] != 3 or not metrics["legal_ir_losses"]
                        or "deontic" not in metrics["legal_ir_view_family_metrics"]):
                    raise ValueError("bridge-on evaluation requires three targets, losses and deontic metrics")
            telemetry = worker["target_hydration_gc"]
            row["target_hydration_gc"] = telemetry
            if (telemetry["requested"] is not defer or telemetry["applied"] is not defer
                    or telemetry["explicit_collection_performed"] is not defer
                    or telemetry["gc_enabled_before"] is not True or telemetry["gc_enabled_after"] is not True
                    or telemetry["gc_threshold_before"] != telemetry["gc_threshold_after"]):
                raise ValueError("requested GC policy was not applied/restored with unchanged thresholds")
            if (Path(spec.output_directory) / "candidate.state.json").exists():
                raise ValueError("sparse combined job unexpectedly wrote a full candidate")
            row["artifact_parity_evidence"] = artifact_parity(worker)
            row["parity_values"] = worker_parity(worker, row["artifact_parity_evidence"])
            row["timings"] = collect_timings(worker, row["owner_wall_seconds"])
            row["memory"] = {name: worker[name] for name in (
                "memory_before_training", "memory_after_training_before_serialization")}
            row["head_unchanged"] = registry.resolve_head(variant_id, branch) == receipt["initial_head"]
            if not row["head_unchanged"]:
                raise ValueError("benchmark modified the pinned registry head")
            row["passed"] = True
            print(json.dumps({"phase": "job_done", "ordinal": ordinal, "policy": policy,
                "accepted_epochs": worker["optimizer_accepted_epochs"], "owner_wall_seconds": row["owner_wall_seconds"],
                "target_hydration_seconds": worker["target_hydration_seconds"],
                "training_seconds": worker["training_seconds"]}), flush=True)

    # A new connection must recover every exact full receipt and the separate
    # preparation sidecar association, including policy metadata, from disk.
    with AutoencoderRegistry(database, artifact_root) as registry:
        for row in receipt["runs"]:
            persisted = registry.get_run(row["run_id"])
            completed = row["owner_result"]["completed"][0]
            worker = row["worker"]
            row["run_durable_after_restart"] = (
                persisted["status"] == "completed" and persisted["result"] == completed["result"]
                and persisted["spec"] == row["run_metadata"])
            prep_ref = registry.verify_artifact(persisted["spec"]["target_preparation_receipt_artifact"])
            target_ref = registry.verify_artifact(persisted["spec"]["target_preparation_target_artifact"])
            row["preparation_receipt_durable_after_restart"] = (
                prep_ref == preparation_artifact and registry.artifact_path(prep_ref).read_bytes() == preparation_path.read_bytes()
                and target_ref == targets and target_ref == {key: prepared["artifact"][key] for key in ("sha256", "bytes")}
                and target_ref == {key: worker["target_snapshot_artifact"][key] for key in ("sha256", "bytes")}
                and persisted["spec"]["target_preparation_snapshot_id"] == worker["target_snapshot_id"] == prepared["target_snapshot_id"])
            worker_ref = registry.verify_artifact(persisted["result"]["worker_receipt_artifact"])
            row["worker_receipt_durable_after_restart"] = (
                worker_ref == completed["worker_receipt_artifact"] and registry.artifact_path(worker_ref).read_bytes()
                == (Path(worker["job_spec"]["output_directory"]) / "receipt.json").read_bytes())
            row["candidate_artifacts_durable_after_restart"] = all(
                registry.artifact_path(registry.verify_artifact({key: ref[key] for key in ("sha256", "bytes")})).read_bytes()
                == Path(ref["path"]).read_bytes()
                for ref in [worker["candidate"], *worker["sparse_patch_segments"]])
            if not all(row[key] for key in ("run_durable_after_restart", "preparation_receipt_durable_after_restart",
                    "worker_receipt_durable_after_restart", "candidate_artifacts_durable_after_restart")):
                raise ValueError("durable receipt, preparation or candidate artifact association changed")
        receipt["final_head"] = registry.resolve_head(variant_id, branch)
        receipt["head_unchanged_after_restart"] = receipt["initial_head"] == receipt["final_head"]
        receipt["staged_pinned_checkpoint_unchanged"] = registry.verify_artifact(base) == base

    pids = [row["worker"]["runtime"]["pid"] for row in receipt["runs"]]
    receipt["fresh_worker_processes"] = len(set(pids)) == 4
    baseline = receipt["runs"][0]["parity_values"]
    receipt["parity"] = {key: all(canonical(row["parity_values"][key]) == canonical(value)
                                  for row in receipt["runs"]) for key, value in baseline.items()}
    receipt["raw_artifact_comparison"] = {
        key: all(row["artifact_parity_evidence"][key] == receipt["runs"][0]["artifact_parity_evidence"][key]
                 for row in receipt["runs"]) for key in ("raw_patch_artifacts", "raw_manifest_artifact")}
    receipt["pair_comparisons"] = []
    timing_keys = [key for key, value in receipt["runs"][0]["timings"].items() if isinstance(value, (int, float))]
    for normal_index, deferred_index in ((0, 1), (3, 2)):
        normal, deferred = receipt["runs"][normal_index], receipt["runs"][deferred_index]
        receipt["pair_comparisons"].append({"normal_ordinal": normal_index, "deferred_ordinal": deferred_index,
            "exact_semantic_parity": canonical(normal["parity_values"]) == canonical(deferred["parity_values"]),
            "seconds_saved": {key: normal["timings"][key] - deferred["timings"][key] for key in timing_keys}})
    medians = {policy: {key: statistics.median(row["timings"][key] for row in receipt["runs"] if row["policy"] == policy)
                       for key in timing_keys} for policy in ("normal", "deferred")}
    receipt["timing_medians"] = medians
    receipt["observed_reduction_fraction"] = {key: (medians["normal"][key] - medians["deferred"][key]) / medians["normal"][key]
        if medians["normal"][key] else None for key in timing_keys}
    receipt["jobs_and_parity_passed"] = (receipt["fresh_worker_processes"] and receipt["head_unchanged_after_restart"]
        and receipt["staged_pinned_checkpoint_unchanged"] and all(receipt["parity"].values()))


def final_guards(args, receipt):
    """Preserve end guards even when preparation or an owner job fails closed."""
    guards = {}
    try:
        receipt["final_pinned_checkpoint"] = descriptor(PINNED)
        guards["pinned_checkpoint_unchanged"] = (sha(PINNED) == PINNED_SHA and PINNED.stat().st_size == PINNED_BYTES)
        guards["parent_receipt_unchanged"] = sha(PRIOR) == PRIOR_SHA
    except Exception as exc:
        receipt["pinned_guard_error"] = {"type": type(exc).__name__, "message": str(exc)}
        guards["pinned_checkpoint_unchanged"] = False
    if "source_hashes" in receipt:
        changed = {}
        for path, before in receipt["source_hashes"].items():
            try:
                after = sha(ROOT / path)
            except OSError:
                after = None
            if before != after:
                changed[path] = {"before": before, "after": after}
        receipt["source_changes"] = changed
        guards["source_unchanged"] = not changed
    if "effective_training_config" in receipt and "initial_target_config_artifact" in receipt:
        try:
            current = spawned(config_probe, receipt["effective_training_config"])
            path = args.directory / "target-config-after.json"
            write(path, current)
            receipt["final_target_config_artifact"] = descriptor(path)
            before = json.loads(Path(receipt["initial_target_config_artifact"]["path"]).read_bytes())
            guards["complete_target_producer_config_unchanged"] = canonical(current) == canonical(before)
            receipt["package_source_changes"] = {name: {"before": before["code_sha256"].get(name), "after": current["code_sha256"].get(name)}
                for name in sorted(set(before["code_sha256"]) | set(current["code_sha256"]))
                if before["code_sha256"].get(name) != current["code_sha256"].get(name)}
            receipt["target_dependency_provenance_unchanged"] = current["dependency_provenance"] == before["dependency_provenance"]
        except Exception as exc:
            receipt["target_config_guard_error"] = {"type": type(exc).__name__, "message": str(exc)}
            guards["complete_target_producer_config_unchanged"] = False
    receipt["final_guards"] = guards
    required = {"pinned_checkpoint_unchanged", "parent_receipt_unchanged", "source_unchanged", "complete_target_producer_config_unchanged"}
    receipt["passed"] = ("error" not in receipt and receipt.get("jobs_and_parity_passed") is True
                         and set(guards) == required and all(guards.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.directory.exists() or args.output.exists():
        parser.error("use new artifact and receipt paths")
    args.directory, args.output = args.directory.resolve(), args.output.resolve()
    args.directory.mkdir(parents=True)
    sys.path.insert(0, str(ROOT))
    os.environ.update({"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "CUDA_VISIBLE_DEVICES": "",
        "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
    receipt = {"schema": "target-hydration-gc-native-qualification-v1", "passed": False,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "parent_receipt": {"path": str(PRIOR), "sha256": PRIOR_SHA},
        "runs": [], "execution_order": ["deferred" if flag else "normal" for flag in ORDER],
        "owner_dispatch_performed": False, "training_job_count": 4, "sample_count": 3,
        "validation_sample_count": 3, "target_union_count": 6, "legal_ir_evaluate_provers": False,
        "legal_ir_parallel_workers": 1, "training_workers": 1, "metric_disk_cache": 0, "use_sample_memory": False,
        "epochs": 1, "projection_max_update_families": 1, "max_line_search_attempts": 1, "max_seconds": 180.0,
        "temperature": 0, "native_threads": 1, "projection_update_backend": "python_sparse_batch",
        "control_transport": "local DuckDB owner; Quack and DuckLake are not exercised by this run",
        "admitted": False, "formalized": False, "heldout_canary_qualified": False, "global_holdout_verified": False,
        "promotion_performed": False, "publication_performed": False, "weights_downloaded": False,
        "old_target_or_metric_parity_required": False,
        "target_preparation_receipt_scope": "receipt-only immutable run metadata; workers consume the complete target bundle/statuses normally",
        "target_reuse_scope": "one freshly prepared current-source bundle shared by all four jobs; no historical targets reused",
        "parity_scope": "exact current-run reports excluding listed timings/profile, candidate logical and materialized identities, normalized accepted patches/manifests, and ordered ontology observations",
        "parity_report_excluded_fields": sorted(REPORT_EXCLUSIONS),
        "parity_artifact_excluded_provenance_fields": sorted(RUN_PROVENANCE),
        "ontology_parity_scope": "counts, sample/scope order, outcomes and diagnostics; captured record/triple contents are not present in worker receipts and are not compared here",
        "full_target_graph_parity_recomputed": False,
        "timing_scope": "four sequential spawned native workers; owner wall includes durable verification/replay; preparation/staging/config probes excluded; hydration includes restored-GC cleanup; OS cache uncontrolled",
        "memory_scope": "existing worker process current RSS/PSS and Linux ru_maxrss observations before/after training; no inferred buffer memory or additional hot-path sampling",
        "speedup_required_for_pass": False}
    started = time.perf_counter()
    try:
        run(args, receipt)
    except Exception as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        final_guards(args, receipt)
    receipt["elapsed_seconds"] = time.perf_counter() - started
    receipt["retained_files"] = [{"path": str(path.relative_to(args.directory)), "bytes": path.stat().st_size}
        for path in sorted(args.directory.rglob("*")) if path.is_file()]
    receipt["retained_artifact_bytes"] = sum(item["bytes"] for item in receipt["retained_files"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write(args.output, receipt)
    print(json.dumps({"receipt": str(args.output), "passed": receipt["passed"], "error": receipt.get("error")}), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
