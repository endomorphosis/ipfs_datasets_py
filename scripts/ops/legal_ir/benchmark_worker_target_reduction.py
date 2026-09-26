#!/usr/bin/env python3
"""Compare complete and reduced runtime targets in four native owner jobs.

One newly prepared, complete six-target bundle and a frozen 3+3 corpus selection
are shared by independent spawned workers, ordered full/reduced/reduced/full, with deferred hydration GC in both arms.
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

HELPER_PATH = Path(__file__).with_name("qualify_target_preparation_telemetry.py")
HELPER_SHA = "281189523dfc4ff704df9918dddc68e47dc9c4f6053cf805e731d85020065f44"
if hashlib.sha256(HELPER_PATH.read_bytes()).hexdigest() != HELPER_SHA:
    raise RuntimeError("frozen preparation helper changed")

from qualify_target_preparation_telemetry import (
    PINNED, PINNED_BYTES, PINNED_SHA, PRIOR, PRIOR_SHA, ROOT,
    prepare as original_prepare, sha, verify_descriptor, write,
)


ORDER = (False, True, True, False)
BRIDGES = ["modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec", "external_prover_router"]
REPORT_EXCLUSIONS = frozenset({"elapsed_seconds", "identity_hashing_seconds", "projection_profile"})
RUN_PROVENANCE = frozenset({"job_id", "run_id", "job_spec_sha256"})


def complete_bridge_reports(prepared):
    reports, statuses = prepared["bridge_report_telemetry"], prepared["statuses"]
    return (len(statuses) == 6 and set(reports) == set(statuses)
        and all(value == "ready" for value in statuses.values())
        and all(report["report_received"] is True
            and report["attempted_bridge_count"] == report["implemented_bridge_count"] == 5
            and len(report["attempted_bridge_names"]) == len(report["implemented_bridge_names"]) == 5
            and set(report["attempted_bridge_names"]) == set(report["implemented_bridge_names"]) == set(BRIDGES)
            and report["failed_bridge_count"] == 0 and report["failed_bridge_names"] == []
            and report["failures"] == {} and report["outer_timeout"] is None
            for report in reports.values()))


def validate_preparation_observation(prepared, observation, config):
    rows = observation["outcomes"]
    if (observation["returned"] is not True or observation["wrapper_restored"] is not True
            or observation["native_targets_retained"] is not False or "error" in observation
            or len(rows) != 6 or len({row["sample_id"] for row in rows}) != 6
            or {row["sample_id"]: row["status"] for row in rows} != prepared["statuses"]
            or {row["sample_id"]: row["bridge_report_telemetry"] for row in rows}
                != prepared["bridge_report_telemetry"]
            or canonical(observation["initial_config"]) != canonical(config)):
        raise ValueError("preparation boundary observations differ from the returned result/configuration")


def prepare(payload, path, observation_path):
    """Retain bounded native outcomes even when the producer's end guard raises.

    Only this dedicated preparation child observes the generator boundary. It
    returns the original pair unchanged, retains no target/sample object, and
    never modifies the producer timeout, configuration, result or exception.
    """
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_target_preparation as module

    initial_config = config_probe(payload["training_config"])
    original = module._bounded_target_results
    observation = {"schema": "target-preparation-boundary-observation-v1", "outcomes": [],
        "instrumented_preparation_boundary": True, "native_worker_callables_wrapped": False,
        "native_targets_retained": False, "automatic_retry": False, "copy_seconds": 0.0,
        "initial_config": initial_config, "returned": False, "wrapper_restored": False}

    def observed(generate, samples, workers):
        generated = original(generate, samples, workers)
        try:
            for sample, result in generated:
                started = time.perf_counter()
                if (type(result) is not tuple or len(result) != 4 or type(result[0]) is not str
                        or type(result[2]) is not str or type(result[3]) is not dict
                        or len(observation["outcomes"]) >= 6):
                    raise ValueError("unexpected native target-generation result")
                raw = canonical(result[3])
                if len(raw) > 65536:
                    raise ValueError("bridge telemetry exceeds diagnostic byte bound")
                observation["outcomes"].append({"sample_id": result[0], "status": result[2],
                    "bridge_report_telemetry": json.loads(raw)})
                observation["copy_seconds"] += time.perf_counter() - started
                yield sample, result
                del sample, result
        finally:
            generated.close()

    module._bounded_target_results = observed
    failure = None
    try:
        result = original_prepare(payload, path)
        observation["returned"] = True
        return result
    except BaseException as exc:
        failure = exc
        observation["error"] = {"type": type(exc).__name__, "message": str(exc)[:2048]}
        raise
    finally:
        module._bounded_target_results = original
        observation["wrapper_restored"] = module._bounded_target_results is original
        try:
            write(Path(observation_path), observation)
        except Exception as exc:
            if failure is None:
                raise
            print(json.dumps({"preparation_observation_write_error": type(exc).__name__,
                              "message": str(exc)[:2048]}), file=sys.stderr, flush=True)


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


TOP_LEVEL_CLOCKS = frozenset({
    "base_checkpoint_load_seconds", "candidate_serialization_seconds", "corpus_verification_seconds",
    "elapsed_seconds", "sample_build_seconds", "sample_build_seconds_per_sample",
    "target_artifact_verification_seconds", "target_hydration_seconds", "target_load_seconds",
    "training_seconds", "weight_load_seconds_after_json_parse",
})
STORAGE_CLOCKS = frozenset({"hydrate_validate_seconds", "manifest_parse_validate_seconds",
                           "open_hash_seconds", "read_decompress_seconds"})
PROFILE_CLOCKS = frozenset({"seconds", "max_seconds", "p50_seconds", "p95_seconds"})


def full_worker_parity(worker, artifacts):
    """Keep every semantic field; enumerate each permitted runtime difference.

    Exemptions are path-scoped. In particular max_seconds budgets, graph wall
    timestamps, document hashes, profile event order/counts/metadata, and every
    evaluation value remain compared. Original values stay in the full receipt.
    """
    exemptions = []

    def exempt(path, value, reason):
        exemptions.append({"path": list(path), "reason": reason, "original": value})
        return {"parity_exemption": reason}

    def visit(value, path=()):
        if (len(path) == 1 and path[0] in TOP_LEVEL_CLOCKS
                or path == ("training_report", "elapsed_seconds")
                or len(path) == 2 and path[0] == "target_storage_statistics" and path[1] in STORAGE_CLOCKS
                or len(path) == 2 and path[0] == "target_hydration_gc"
                    and path[1] in {"hydrate_seconds", "collection_seconds", "total_seconds"}
                or len(path) == 4 and path[:1] == ("sparse_patch_segments",)
                    and path[2:] == ("capture_context", "identity_hashing_seconds")):
            if type(value) not in (int, float) or value < 0:
                raise ValueError("invalid clock measurement at " + repr(path))
            return exempt(path, value, "clock")
        if path[:2] == ("training_report", "projection_profile"):
            if (len(path) == 3 and path[2] in {"total_seconds", "warm_p95_projection_seconds"}
                    or len(path) == 5 and path[2] in {
                        "by_cost_family", "by_feature_head", "by_legal_family", "by_stage"}
                        and path[4] in PROFILE_CLOCKS
                    or len(path) == 5 and path[2] == "events" and type(path[3]) is int and path[4] == "seconds"):
                return exempt(path, value, "projection_profile_clock")
        if (len(path) == 4 and path[0] == "ontology_capture_observation"
                and path[1] in {"captures", "records", "stages", "stage_totals"}
                and path[3] == "elapsed_seconds"):
            return exempt(path, value, "ontology_observation_clock")
        if path in {
                ("memory_before_training",), ("memory_after_training_before_serialization",),
                ("target_hydration_gc", "gc_stats_before"), ("target_hydration_gc", "gc_stats_after"),
                ("target_hydration_gc", "gc_stats_delta")}:
            return exempt(path, value, "memory_or_gc_observation")
        if path == ("target_reduction",):
            return exempt(path, value, "explicit_target_reduction_policy_and_telemetry")
        if path in {("job_id",), ("run_id",), ("job_spec_canonical_sha256",),
                    ("job_spec", "job_id"), ("job_spec", "run_id"), ("job_spec", "output_directory"),
                    ("ontology_capture_observation", "producer_identity", "job_spec_sha256"),
                    ("runtime", "pid")}:
            return exempt(path, value, "verified_run_provenance")
        if path == ("candidate",):
            exempt(path, value, "raw_manifest_descriptor_binds_verified_run_provenance")
            return artifacts["manifest_with_normalized_patch_references"]
        if path == ("sparse_patch_bytes",):
            exempt(path, value, "raw_patch_size_includes_verified_run_provenance")
            return sum(len(canonical(patch)) for patch in artifacts["decoded_patches_without_run_provenance"])
        if path == ("sparse_patch_segments",):
            payloads = artifacts["decoded_patches_without_run_provenance"]
            if len(payloads) != len(value):
                raise ValueError("normalized patch count differs")
            rows = []
            for index, (ref, payload) in enumerate(zip(value, payloads)):
                if set(ref) != {"path", "sha256", "bytes", "capture_context"}:
                    raise ValueError("unexpected sparse segment descriptor fields")
                exempt((*path, index), {key: ref[key] for key in ("path", "sha256", "bytes")},
                       "raw_patch_descriptor_binds_verified_run_provenance")
                rows.append({"payload": payload,
                    "capture_context": visit(ref["capture_context"], (*path, index, "capture_context"))})
            return rows
        if type(value) is dict:
            return {key: visit(item, (*path, key)) for key, item in value.items()}
        if type(value) is list:
            return [visit(item, (*path, index)) for index, item in enumerate(value)]
        return value

    return visit(worker), exemptions


def parity_differences(left, right):
    """Bounded diagnostics, not a normalization or secondary acceptance rule."""
    changes, count = [], 0

    def walk(a, b, path):
        nonlocal count
        if type(a) is type(b) is dict and set(a) == set(b):
            for key in a:
                walk(a[key], b[key], (*path, key))
        elif type(a) is type(b) is list and len(a) == len(b):
            for index, (x, y) in enumerate(zip(a, b)):
                walk(x, y, (*path, index))
        elif canonical(a) != canonical(b):
            count += 1
            if len(changes) < 64:
                row = {"path": list(path), "reference_type": type(a).__name__, "candidate_type": type(b).__name__}
                for label, value in (("reference", a), ("candidate", b)):
                    raw = canonical(value)
                    row[label] = value if len(raw) <= 512 else {"canonical_bytes": len(raw),
                        "canonical_sha256": hashlib.sha256(raw).hexdigest()}
                changes.append(row)

    walk(left, right, ())
    return {"difference_count": count, "differences": changes, "all_differences_retained": count == len(changes)}


def collect_timings(worker, owner_seconds):
    stages = worker["training_report"]["projection_profile"]["by_stage"]
    initial_evaluate = stages["before_holdout_evaluation"]["seconds"]
    result = {
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
    result["evaluation_profile_stage_seconds_per_span"] = {
        name: value / 3 for name, value in result["evaluation_profile_stage_seconds"].items()}
    result["target_reduction_seconds"] = worker["target_reduction"]["total_seconds"]
    result["target_reduction_hash_seconds"] = worker["target_reduction"]["hash_seconds"]
    result["target_reduction_release_seconds"] = worker["target_reduction"]["release_seconds"]
    return result


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
    source_paths.update({Path(__file__).resolve(), Path(original_prepare.__code__.co_filename).resolve(),
        ROOT / "ipfs_datasets_py/logic/autoformal/__init__.py",
        ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_ontology_observation.py",
        ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/_autoencoder_prepared_targets.py",
        ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_coordinator.py"})
    receipt["source_hashes"] = {str(path.relative_to(ROOT)): sha(path) for path in sorted(source_paths)}
    write(args.directory / "selection.json", receipt["selection"])
    initial_config = spawned(config_probe, payload["training_config"])
    config_path = args.directory / "target-config-before.json"
    write(config_path, initial_config)
    receipt["initial_target_config_artifact"] = descriptor(config_path)
    receipt["package_source_count"] = len(initial_config["code_sha256"])
    reducer_name = "optimizers/logic_theorem_optimizer/_autoencoder_prepared_targets.py"
    if reducer_name not in initial_config["code_sha256"]:
        raise ValueError("full producer source binding must include the new runtime target reducer")
    snapshot_root = args.directory / "source-code"
    receipt["source_code_snapshots"] = []
    total_source_bytes = 0
    for path in sorted(source_paths):
        relative = path.relative_to(ROOT)
        raw = path.read_bytes()
        total_source_bytes += len(raw)
        if total_source_bytes > 64 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != receipt["source_hashes"][str(relative)]:
            raise ValueError("source snapshot byte bound or identity mismatch")
        if relative.parts[0] == "ipfs_datasets_py":
            key = str(relative.relative_to("ipfs_datasets_py"))
            if initial_config["code_sha256"].get(key) != hashlib.sha256(raw).hexdigest():
                raise ValueError("source snapshot differs from complete producer manifest")
        destination = snapshot_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(raw)
        receipt["source_code_snapshots"].append({"source": str(relative), **descriptor(destination)})

    started = time.perf_counter()
    preparation_failure = None
    try:
        prepared = spawned(prepare, payload, str(args.directory / "targets.bundle"), str(args.directory / "preparation-outcomes.json"))
    except BaseException as exc:
        preparation_failure = exc
    finally:
        receipt["target_preparation_dispatch_seconds"] = time.perf_counter() - started
        outcome_path = args.directory / "preparation-outcomes.json"
        if outcome_path.exists():
            receipt["preparation_boundary_observation"] = json.loads(outcome_path.read_bytes())
            receipt["preparation_boundary_observation_artifact"] = descriptor(outcome_path)
    if preparation_failure is not None:
        raise preparation_failure
    receipt["target_preparation"] = prepared
    preparation_path = args.directory / "target-preparation.json"
    write(preparation_path, prepared)
    validate_preparation_observation(prepared, receipt["preparation_boundary_observation"], initial_config)
    # SampleRecord has no runtime sample_id. The preparer derives those IDs;
    # each normal worker independently verifies exact requested membership.
    expected_ids = set(prepared["statuses"])
    if (len(expected_ids) != 6 or prepared["sample_count"] != 6 or prepared["legal_ir_target_count"] != 6
            or set(prepared["statuses"]) != expected_ids
            or set(prepared["statuses"].values()) != {"ready"}
            or set(prepared["bridge_report_telemetry"]) != expected_ids or prepared["admitted"] is not False
            or not complete_bridge_reports(prepared)):
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
    variant_id, branch = "worker-target-reduction", "qualification"
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
            code_identity="worker-target-reduction-current-source", expected_source_sha256=expected_sources,
            target_snapshot_id=prepared["target_snapshot_id"], target_snapshot_artifact=bound(targets))
        for ordinal, reduce in enumerate(ORDER):
            policy = "reduced" if reduce else "full"
            run_id = f"target-{ordinal}-{policy}"
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
                "runtime_target_policy": {"reduce_native_targets": reduce, "defer_target_hydration_gc": True,
                    "scope": "native private reduction after verified complete hydration", "ordinal": ordinal}}
            row["run_metadata"] = metadata
            registry.create_run(f"create-{run_id}", run_id, variant_id, version, metadata)
            receipt["owner_dispatch_performed"] = True
            started = time.perf_counter()
            owner = run_training_jobs(registry, [spec], max_workers=1, defer_target_hydration_gc=True, reduce_native_targets=reduce)
            row["owner_wall_seconds"] = time.perf_counter() - started
            row["owner_result"] = owner
            if owner["failed"] or len(owner["completed"]) != 1:
                raise ValueError(f"normal owner dispatch did not complete: {run_id}")
            completed = owner["completed"][0]
            worker_path = Path(spec.output_directory) / "receipt.json"
            worker = json.loads(worker_path.read_bytes())
            row["worker"] = worker
            if (worker["job_spec"] != spec.to_dict() or worker["job_spec_canonical_sha256"] != spec.canonical_sha256
                    or worker["job_id"] != spec.job_id or worker["run_id"] != spec.run_id):
                raise ValueError("worker provenance differs from the exact submitted specification")
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
            if (telemetry["requested"] is not True or telemetry["applied"] is not True
                    or telemetry["explicit_collection_performed"] is not True
                    or telemetry["gc_enabled_before"] is not True or telemetry["gc_enabled_after"] is not True
                    or telemetry["gc_threshold_before"] != telemetry["gc_threshold_after"]):
                raise ValueError("requested GC policy was not applied/restored with unchanged thresholds")
            if (Path(spec.output_directory) / "candidate.state.json").exists():
                raise ValueError("sparse combined job unexpectedly wrote a full candidate")
            row["artifact_parity_evidence"] = artifact_parity(worker)
            row["selected_parity_values"] = worker_parity(worker, row["artifact_parity_evidence"])
            row["parity_values"], row["parity_exemptions"] = full_worker_parity(worker, row["artifact_parity_evidence"])
            row["timings"] = collect_timings(worker, row["owner_wall_seconds"])
            row["memory"] = {name: worker[name] for name in (
                "memory_before_training", "memory_after_training_before_serialization")}
            row["target_reduction"] = worker["target_reduction"]
            reduction = worker["target_reduction"]
            if (reduction["requested"] is not reduce or reduction["applied"] is not reduce
                    or reduction["policy"] != "worker_private_native_targets_v1"
                    or reduction["original_target_count"] != 6
                    or (reduce and (reduction["original_target_count"] != 6
                        or reduction["prepared_target_count"] != 6 or reduction["skip_reason"] is not None))
                    or (not reduce and (reduction["prepared_target_count"] != 0
                        or reduction["skip_reason"] != "not_requested"))):
                raise ValueError("requested target reduction was not applied exactly to all six native targets")
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
        receipt["pair_comparisons"].append({"full_ordinal": normal_index, "reduced_ordinal": deferred_index,
            "exact_semantic_parity": canonical(normal["parity_values"]) == canonical(deferred["parity_values"]),
            "strict_worker_differences": parity_differences(normal["parity_values"], deferred["parity_values"]),
            "seconds_saved": {key: normal["timings"][key] - deferred["timings"][key] for key in timing_keys}})
    medians = {policy: {key: statistics.median(row["timings"][key] for row in receipt["runs"] if row["policy"] == policy)
                       for key in timing_keys} for policy in ("full", "reduced")}
    receipt["timing_medians"] = medians
    receipt["observed_reduction_fraction"] = {key: (medians["full"][key] - medians["reduced"][key]) / medians["full"][key]
        if medians["full"][key] else None for key in timing_keys}
    receipt["jobs_and_parity_passed"] = (receipt["fresh_worker_processes"] and receipt["head_unchanged_after_restart"]
        and receipt["staged_pinned_checkpoint_unchanged"] and all(receipt["parity"].values()))


def final_guards(args, receipt):
    """Preserve end guards even when preparation or an owner job fails closed."""
    guards = {}
    guards["harness_and_dependencies_unchanged"] = (
        sha(Path(__file__)) == receipt["harness_sha256"] and sha(HELPER_PATH) == HELPER_SHA)
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
    guards["retained_source_snapshots_verified"] = all(
        Path(ref["path"]).stat().st_size == ref["bytes"] and sha(ref["path"]) == ref["sha256"]
        for ref in receipt.get("source_code_snapshots", []))
    required = {"pinned_checkpoint_unchanged", "parent_receipt_unchanged", "source_unchanged",
                "complete_target_producer_config_unchanged", "harness_and_dependencies_unchanged",
                "retained_source_snapshots_verified"}
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
    os.environ.update({"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS": "1", "CUDA_VISIBLE_DEVICES": "",
        "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
    receipt = {"schema": "worker-target-reduction-native-comparison-v1", "passed": False,
        "harness_sha256": sha(Path(__file__)),
        "harness_dependencies": [{"path": str(HELPER_PATH), "sha256": HELPER_SHA}],
        "recorded_at": datetime.now(timezone.utc).isoformat(), "parent_receipt": {"path": str(PRIOR), "sha256": PRIOR_SHA},
        "runs": [], "execution_order": ["reduced" if flag else "full" for flag in ORDER],
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
        "parity_scope": "all worker fields except explicit path-scoped clock/memory/GC measurements, run provenance and reduction policy telemetry; decoded patches/manifests and all report/profile non-clock fields compared; no target hash or graph timestamp exemption",
        "legacy_selected_parity_report_excluded_fields": sorted(REPORT_EXCLUSIONS),
        "strict_full_worker_parity_required": True, "defer_target_hydration_gc": True,
        "parity_artifact_excluded_provenance_fields": sorted(RUN_PROVENANCE),
        "ontology_parity_scope": "counts, sample/scope order, outcomes and diagnostics; captured record/triple contents are not present in worker receipts and are not compared here",
        "full_target_graph_parity_recomputed": False,
        "same_immutable_target_bundle_for_all_jobs": True,
        "target_document_hashes_must_match": True,
        "evaluation_timing_scope": "each recorded bridge-on evaluation stage and seconds per three spans; all five target views active, no isolated individual-bridge evaluation timers",
        "preparation_boundary_observer": "one child-only generator boundary observer; original returned pairs unchanged; primitive diagnostics copied outside production generation intervals; no old/new preparation speed comparison",
        "native_worker_callables_wrapped": False, "automatic_retry_or_reselection": False,
        "timing_scope": "four sequential spawned native workers; owner wall includes spawn, worker resource cleanup/pool shutdown and durable verification/replay; preparation/staging/config probes excluded; hydration includes restored-GC cleanup; OS cache uncontrolled",
        "memory_scope": "RSS/PSS before training and after training, plus reduction before/after and Linux ru_maxrss peaks; peaks include hydration; no inferred buffer memory",
        "speedup_required_for_pass": False}
    started = time.perf_counter()
    try:
        run(args, receipt)
    except BaseException as exc:
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        try:
            final_guards(args, receipt)
        except BaseException as exc:
            receipt["final_guard_error"] = {"type": type(exc).__name__, "message": str(exc)}
            receipt["passed"] = False
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
