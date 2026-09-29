"""Owner-side coordination of independent autoencoder training processes.

Only this process holds the registry. Workers receive validated immutable job
specifications and return local artifacts. Durable completion registers a
candidate; optimizer acceptance and Lean admission are separate facts.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
from concurrent.futures import wait as _wait_for_preparation
from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence
import uuid

from .autoencoder_training_worker import (
    INDEXED_SCHEMA_VERSION,
    ARROW_INPUT_SCHEMA_VERSION,
    PRODUCED_SCHEMA_VERSION,
    CAMPAIGN_SCHEMA_VERSION,
    MAX_EMBEDDING_PRODUCTION_BYTES,
    MAX_CORPUS_INDEX_BYTES,
    TrainingJobSpec,
    TrainingJobValidationError,
    execute_training_job,
    _execute_native_training_job_with_deferred_gc,
    _execute_native_training_job_with_reduced_targets,
    _execute_native_training_job_with_deferred_gc_and_reduced_targets,
    verify_corpus_job_inputs,
)


class TrainingCoordinationError(ValueError):
    """A run, worker result, or immutable artifact does not match its binding."""


@dataclass(frozen=True)
class SparseCheckpointPolicy:
    """Owner limits for accepted sparse chains; workers cannot relax them."""

    max_depth: int = 8
    max_patch_fraction: float = 0.5

    def __post_init__(self) -> None:
        if type(self.max_depth) is not int or not 1 <= self.max_depth <= 8:
            raise TrainingCoordinationError("sparse max_depth must be within [1, 8]")
        if (isinstance(self.max_patch_fraction, bool)
                or not isinstance(self.max_patch_fraction, (int, float))
                or not math.isfinite(self.max_patch_fraction)
                or not 0 < self.max_patch_fraction <= 1):
            raise TrainingCoordinationError("sparse max_patch_fraction must be within (0, 1]")


def registered_checkpoint_inputs(registry: Any, version_id: str) -> dict[str, Any]:
    """Return verified, owner-staged inputs for a full or sparse model version.

    Inventory verifies file hashes, artifact schemas and the bounded immutable
    reference closure without constructing model weights. Materialized state
    identities remain declarations here: workers and owner acceptance perform
    full semantic replay. This does not write a checkpoint or promote a head.
    """
    from .modal_autoencoder_sparse_checkpoint import inventory_checkpoint

    version = registry.get_version(version_id)
    root = registry.verify_artifact(version["artifact"])

    def resolver(reference: Mapping[str, Any]) -> Path:
        return registry.artifact_path(registry.verify_artifact(reference))

    inventory = inventory_checkpoint(root, resolver=resolver)
    dependencies = sorted((dict(ref) for ref in inventory.artifacts if dict(ref) != root),
                          key=lambda ref: ref["sha256"])
    return {
        "base_checkpoint": {**root, "path": str(registry.artifact_path(root))},
        "base_checkpoint_dependencies": [
            {**ref, "path": str(registry.artifact_path(ref))} for ref in dependencies],
    }


def _bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_bounded(path: Path, limit: int) -> bytes:
    if type(limit) is not int or limit < 1:
        raise TrainingCoordinationError("invalid artifact byte bound")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise TrainingCoordinationError("artifact is not a bounded regular file")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise TrainingCoordinationError("artifact exceeds byte bound")
    return raw


def _read_json(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise TrainingCoordinationError(f"duplicate artifact field: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise TrainingCoordinationError(f"nonfinite artifact value: {value}")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def _verify_variant_index_binding(variant: Mapping[str, Any], spec: TrainingJobSpec) -> None:
    """Keep all coordinator-dispatched batches on one immutable variant index.

    Caller-owned job fields alone cannot freeze a split across later runs. The
    registered variant supplies that authority; an indexed variant cannot fall
    back to a legacy job that omits index verification.
    """
    if "corpus_index_binding" not in variant:
        if spec.schema_version in {INDEXED_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
            raise TrainingCoordinationError("v5 jobs require a registered corpus_index_binding")
        return
    binding = variant["corpus_index_binding"]
    if not isinstance(binding, Mapping) or set(binding) != {"selection_sha256", "artifact"}:
        raise TrainingCoordinationError("corpus_index_binding requires exactly selection_sha256 and artifact")
    selection = binding["selection_sha256"]
    artifact = binding["artifact"]
    if (not isinstance(selection, str) or re.fullmatch(r"[0-9a-f]{64}", selection) is None
            or not isinstance(artifact, Mapping) or set(artifact) != {"sha256", "bytes"}
            or not isinstance(artifact["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]) is None
            or type(artifact["bytes"]) is not int
            or not 1 <= artifact["bytes"] <= MAX_CORPUS_INDEX_BYTES):
        raise TrainingCoordinationError("invalid registered corpus_index_binding")
    if spec.schema_version not in {INDEXED_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
        raise TrainingCoordinationError("indexed variants require v5, v6 or v7 jobs; legacy downgrade is forbidden")
    if (spec.corpus_index_artifact is None
            or dict(artifact) != {"sha256": spec.corpus_index_artifact.sha256,
                                  "bytes": spec.corpus_index_artifact.bytes}
            or selection != spec.corpus_selection_sha256):
        raise TrainingCoordinationError("job index or selection differs from registered corpus_index_binding")


def _verify_variant_embedding_production_binding(variant: Mapping[str, Any], spec: TrainingJobSpec) -> None:
    """Pin production evidence on the immutable variant and forbid downgrade."""
    if "embedding_production_binding" not in variant:
        if spec.schema_version in {PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
            raise TrainingCoordinationError("v6 jobs require a registered embedding_production_binding")
        return
    binding = variant["embedding_production_binding"]
    if not isinstance(binding, Mapping) or set(binding) != {"artifact"}:
        raise TrainingCoordinationError("embedding_production_binding requires exactly artifact")
    artifact = binding["artifact"]
    if (not isinstance(artifact, Mapping) or set(artifact) != {"sha256", "bytes"}
            or not isinstance(artifact["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]) is None
            or type(artifact["bytes"]) is not int
            or not 1 <= artifact["bytes"] <= MAX_EMBEDDING_PRODUCTION_BYTES):
        raise TrainingCoordinationError("invalid registered embedding_production_binding")
    if spec.schema_version not in {PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
        raise TrainingCoordinationError("embedding production bound variants require v6 or v7 jobs; legacy downgrade is forbidden")
    if (spec.embedding_production_artifact is None
            or dict(artifact) != {"sha256": spec.embedding_production_artifact.sha256,
                                  "bytes": spec.embedding_production_artifact.bytes}):
        raise TrainingCoordinationError("job receipt differs from registered embedding_production_binding")


def _verify_variant_source_campaign_binding(variant: Mapping[str, Any], spec: TrainingJobSpec) -> None:
    """Keep successive batches on one immutable source and producer campaign.

    A batch projection belongs to a job. The three campaign roots belong to
    the model variant and cannot be replaced when another batch is submitted.
    Legacy indexes and single-producer bindings have different contracts.
    """
    if "source_campaign_binding" not in variant:
        if spec.schema_version == CAMPAIGN_SCHEMA_VERSION:
            raise TrainingCoordinationError("v8 jobs require a registered source_campaign_binding")
        return
    if spec.schema_version != CAMPAIGN_SCHEMA_VERSION:
        raise TrainingCoordinationError("source campaign bound variants require v8 jobs; legacy downgrade is forbidden")
    if "corpus_index_binding" in variant or "embedding_production_binding" in variant:
        raise TrainingCoordinationError("source_campaign_binding cannot mix legacy corpus or producer bindings")
    binding = variant["source_campaign_binding"]
    fields = {
        "source_inventory": spec.source_inventory_artifact,
        "source_partitions": spec.source_partitions_artifact,
        "embedding_receipt_set": spec.embedding_receipt_set_artifact,
    }
    if not isinstance(binding, Mapping) or set(binding) != set(fields):
        raise TrainingCoordinationError("source_campaign_binding requires exactly the three campaign roots")
    for name, expected in fields.items():
        artifact = binding[name]
        if (not isinstance(artifact, Mapping) or set(artifact) != {"sha256", "bytes"}
                or not isinstance(artifact["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]) is None
                or type(artifact["bytes"]) is not int
                or not 1 <= artifact["bytes"] <= 64 * 1024 * 1024):
            raise TrainingCoordinationError(f"invalid registered source_campaign_binding: {name}")
        if expected is None or dict(artifact) != {"sha256": expected.sha256, "bytes": expected.bytes}:
            raise TrainingCoordinationError(f"job {name} differs from registered source_campaign_binding")


def _verify_registered_job_binding(registry: Any, run: Mapping[str, Any],
                                   spec: TrainingJobSpec) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify immutable owner records independently of an execution lease."""
    variant = registry.get_variant(run["variant_id"])["manifest"]
    _verify_variant_source_campaign_binding(variant, spec)
    _verify_variant_index_binding(variant, spec)
    _verify_variant_embedding_production_binding(variant, spec)
    for name, value in spec.to_dict()["variant"].items():
        if variant.get(name) != value:
            raise TrainingCoordinationError(f"registered variant differs from worker variant: {name}")
    if run["spec"].get("job_spec_sha256") != spec.canonical_sha256:
        raise TrainingCoordinationError("stored job spec digest differs from submitted spec")
    descriptor = registry.verify_artifact(run["spec"].get("job_spec_artifact", {}))
    raw = _read_bounded(registry.artifact_path(descriptor), min(descriptor["bytes"], 64 * 1024 * 1024))
    if len(raw) != descriptor["bytes"] or _sha(raw) != descriptor["sha256"]:
        raise TrainingCoordinationError("job artifact changed during validation")
    stored = TrainingJobSpec.from_dict(_read_json(raw))
    if stored.canonical_sha256 != spec.canonical_sha256:
        raise TrainingCoordinationError("stored job artifact describes another job")
    return variant, descriptor


def _verify_staged_corpus_artifacts(registry: Any, spec: TrainingJobSpec, *, root_scope=None) -> Any:
    """Verify owner paths and return a single-use v8 metadata context, if any.

    The context belongs only to this operation and exact spec. Selected file
    verification consumes it after the CAS checks without reparsing campaign
    roots; current metadata and selected bytes still receive fresh hash checks.
    """
    operation = nullcontext()
    if root_scope is not None:
        from .autoencoder_campaign_job_inputs import _root_scope_operation
        operation = _root_scope_operation(root_scope)
    with operation:
        def verify(artifact):
            if artifact is None:
                return
            descriptor = registry.verify_artifact({"sha256": artifact.sha256, "bytes": artifact.bytes})
            if Path(artifact.path).resolve() != registry.artifact_path(descriptor).resolve():
                raise TrainingCoordinationError("corpus inputs must name staged immutable artifacts")
        if spec.schema_version == CAMPAIGN_SCHEMA_VERSION:
            for artifact in (spec.corpus_manifest_artifact, spec.source_inventory_artifact,
                             spec.source_partitions_artifact, spec.embedding_receipt_set_artifact,
                             spec.produced_record_projection_artifact):
                verify(artifact)
            # Authorize source-frozen roles and exact selected descriptors before
            # reading any selected leaf or source, including the CAS hash checks.
            from .autoencoder_campaign_job_inputs import preflight_campaign_job_inputs
            if root_scope is None:
                prepared = preflight_campaign_job_inputs(spec)
            else:
                from .autoencoder_campaign_job_inputs import _preflight_campaign_job_inputs
                prepared = _preflight_campaign_job_inputs(spec, root_scope=root_scope)
            for artifact in (*spec.embedding_receipt_artifacts, *spec.corpus_source_artifacts):
                verify(artifact)
            return prepared
        for artifact in (spec.corpus_manifest_artifact, spec.corpus_index_artifact, spec.embedding_production_artifact,
                         spec.arrow_embedding_inputs_artifact, *spec.corpus_source_artifacts):
            verify(artifact)


def registered_corpus_job_inputs(registry: Any, run_id: str) -> dict[str, Any]:
    """Resolve and verify a registered job's immutable corpus inputs.

    Completed runs remain usable input anchors. This read-only operation does
    not claim a lease, authorize a checkpoint, or import worker training policy
    into another consumer. Its caller must separately authorize that consumer.
    """
    return _registered_corpus_job_inputs(registry, run_id)


def _registered_corpus_job_inputs(registry: Any, run_id: str, *, root_scope=None) -> dict[str, Any]:
    operation = nullcontext()
    if root_scope is not None:
        from .autoencoder_campaign_job_inputs import _root_scope_operation
        operation = _root_scope_operation(root_scope)
    with operation:
        if root_scope is not None:
            root_scope.check()
            if root_scope._owner is not registry:
                root_scope.close()
                raise TrainingCoordinationError("campaign scope belongs to another registry owner")
        run = registry.get_run(run_id)
        descriptor = registry.verify_artifact(run["spec"].get("job_spec_artifact", {}))
        raw = _read_bounded(registry.artifact_path(descriptor), min(descriptor["bytes"], 64 * 1024 * 1024))
        if len(raw) != descriptor["bytes"] or _sha(raw) != descriptor["sha256"]:
            raise TrainingCoordinationError("job artifact changed during validation")
        spec = TrainingJobSpec.from_dict(_read_json(raw))
        if spec.run_id != run_id or spec.base_version_id != run["base_version_id"]:
            raise TrainingCoordinationError("registered run identity differs from stored job")
        variant, descriptor = _verify_registered_job_binding(registry, run, spec)
        prepared = (_verify_staged_corpus_artifacts(registry, spec) if root_scope is None else
                    _verify_staged_corpus_artifacts(registry, spec, root_scope=root_scope))
        if spec.schema_version == CAMPAIGN_SCHEMA_VERSION:
            from .autoencoder_campaign_job_inputs import _verify_prepared_campaign_job_inputs
            corpus_verification = _verify_prepared_campaign_job_inputs(spec, prepared)
        else:
            corpus_verification = verify_corpus_job_inputs(spec)
        del prepared
        return {"spec": spec, "run": run, "variant": variant, "job_spec_artifact": descriptor,
                "corpus_verification": corpus_verification}


def _validate_runs(registry: Any, specs: Sequence[TrainingJobSpec]) -> dict[str, dict[str, Any]]:
    run_ids: set[str] = set()
    job_ids: set[str] = set()
    output_paths: set[Path] = set()
    corpus_checks: dict[str, dict[str, Any]] = {}
    for spec in specs:
        if not isinstance(spec, TrainingJobSpec):
            raise TrainingCoordinationError("every spec must be a TrainingJobSpec")
        output = Path(spec.output_directory).resolve()
        if spec.run_id in run_ids or spec.job_id in job_ids or output in output_paths:
            raise TrainingCoordinationError("run IDs, job IDs and attempt output directories must be unique")
        if output.exists() or not output.parent.is_dir():
            raise TrainingCoordinationError("attempt directory must be new and its parent must exist")
        run_ids.add(spec.run_id)
        job_ids.add(spec.job_id)
        output_paths.add(output)
        run = registry.get_run(spec.run_id)
        if run["status"] != "queued":
            raise TrainingCoordinationError("coordinator requires a precreated queued run")
        if run["base_version_id"] != spec.base_version_id:
            raise TrainingCoordinationError("run base version differs from job spec")
        _verify_registered_job_binding(registry, run, spec)
        version = registry.get_version(spec.base_version_id)
        base = registry.verify_artifact(version["artifact"])
        if base != {"sha256": spec.base_checkpoint.sha256, "bytes": spec.base_checkpoint.bytes}:
            raise TrainingCoordinationError("job checkpoint differs from registered base artifact")
        # Workers read the owner's staged copy, never a caller's mutable path.
        if Path(spec.base_checkpoint.path).resolve() != registry.artifact_path(base).resolve():
            raise TrainingCoordinationError("worker checkpoint must name the staged immutable base artifact")
        for dependency in spec.base_checkpoint_dependencies:
            descriptor = registry.verify_artifact({"sha256": dependency.sha256, "bytes": dependency.bytes})
            if Path(dependency.path).resolve() != registry.artifact_path(descriptor).resolve():
                raise TrainingCoordinationError("checkpoint dependencies must name staged immutable artifacts")
        for target in (spec.target_snapshot_artifact, spec.arrow_feature_weights_artifact):
            if target is None:
                continue
            descriptor = registry.verify_artifact({"sha256": target.sha256, "bytes": target.bytes})
            if Path(target.path).resolve() != registry.artifact_path(descriptor).resolve():
                raise TrainingCoordinationError("shared targets/weights must name the staged immutable artifact")
        prepared = _verify_staged_corpus_artifacts(registry, spec)
        if spec.schema_version == CAMPAIGN_SCHEMA_VERSION:
            from .autoencoder_campaign_job_inputs import _verify_prepared_campaign_job_inputs
            corpus_checks[spec.run_id] = _verify_prepared_campaign_job_inputs(spec, prepared)
        else:
            corpus_checks[spec.run_id] = verify_corpus_job_inputs(spec)
        del prepared
    return corpus_checks


def _verify_receipt(spec: TrainingJobSpec, returned: Mapping[str, Any], *, native: bool,
                    corpus_verification: Mapping[str, Any]) -> tuple[dict[str, Any], bytes]:
    output = Path(spec.output_directory)
    receipt_path = output / "receipt.json"
    if output.is_symlink() or receipt_path.is_symlink():
        raise TrainingCoordinationError("worker output cannot use symlink aliases")
    raw = _read_bounded(receipt_path, 64 * 1024 * 1024)
    receipt = _read_json(raw)
    if not isinstance(receipt, dict) or _bytes(receipt) != _bytes(returned):
        raise TrainingCoordinationError("returned receipt differs from persisted worker receipt")
    _verify_receipt_payload(spec, receipt, native=native, corpus_verification=corpus_verification)
    return receipt, raw


def _verify_receipt_payload(spec: TrainingJobSpec, receipt: Mapping[str, Any], *, native: bool,
                            corpus_verification: Mapping[str, Any]) -> None:
    """Check the same job bindings for persisted or owner-CAS receipt payloads.

    The caller verifies receipt bytes and their source. This does not stage
    artifacts, replay candidate updates or establish native execution itself.
    """
    output = Path(spec.output_directory)
    # Archived receipts predate the optional expanded-shard bound and used 64MiB.
    # Nondefault jobs require the explicit effective worker bound to match.
    effective_shard_bound = receipt.get("target_shard_max_bytes", 64 * 1024 * 1024)
    if type(effective_shard_bound) is not int or effective_shard_bound != spec.target_shard_max_bytes:
        raise TrainingCoordinationError("worker target_shard_max_bytes differs from job")
    expected = {"schema_version": "autoencoder-training-worker-receipt-v1",
                "job_id": spec.job_id, "run_id": spec.run_id,
                "base_version_id": spec.base_version_id,
                "job_spec_canonical_sha256": spec.canonical_sha256,
                "base_checkpoint": spec.to_dict()["base_checkpoint"],
                "job_spec": spec.to_dict(), "admitted": False, "promotion_performed": False,
                "bridge_names": list(spec.training_config.legal_ir_bridge_names),
                "legal_ir_evaluate_provers": False,
                "legal_ir_parallel_workers": spec.training_config.legal_ir_parallel_workers,
                "metric_disk_cache": 0, "use_sample_memory": False,
                "sample_count": len(spec.samples), "validation_sample_count": len(spec.validation_samples),
                "target_snapshot_id": spec.target_snapshot_id,
                "target_snapshot_artifact": spec.to_dict().get("target_snapshot_artifact"),
                "shared_targets_verified": spec.target_snapshot_artifact is not None,
                "capture_sparse_patches": spec.capture_sparse_patches,
                "corpus_manifest_artifact": spec.to_dict().get("corpus_manifest_artifact"),
                "corpus_source_artifacts": spec.to_dict().get("corpus_source_artifacts", []),
                "corpus_verification": dict(corpus_verification),
                "dataset_and_split_identity_verified": spec.corpus_manifest_artifact is not None,
                "arrow_feature_weights_artifact": spec.to_dict().get("arrow_feature_weights_artifact"),
                "weight_storage": "arrow_cow_feature_embeddings" if spec.arrow_feature_weights_artifact is not None else "private_json"}
    if spec.schema_version in {INDEXED_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
        expected.update(corpus_index_artifact=spec.to_dict()["corpus_index_artifact"],
                        corpus_selection_sha256=spec.corpus_selection_sha256,
                        corpus_index_membership_verified=True)
    if spec.schema_version in {PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
        expected.update(embedding_production_artifact=spec.to_dict()["embedding_production_artifact"],
                        embedding_production_verified=True,
                        embedding_production_verification=corpus_verification["embedding_production_verification"])
    if spec.schema_version == ARROW_INPUT_SCHEMA_VERSION:
        expected.update(
            arrow_embedding_inputs_artifact=spec.to_dict()["arrow_embedding_inputs_artifact"],
            arrow_embedding_inputs_verified=True,
            embedding_input_storage="arrow_mapped_float32",
            arrow_embedding_inputs_verification=corpus_verification["arrow_embedding_inputs_verification"],
            arrow_embedding_inputs_statistics_before_samples=corpus_verification["arrow_embedding_inputs_initial_statistics"],
        )
    if spec.schema_version == CAMPAIGN_SCHEMA_VERSION:
        forbidden = {"corpus_index_artifact", "corpus_selection_sha256", "corpus_index_membership_verified",
                     "embedding_production_artifact", "embedding_production_verified",
                     "embedding_production_verification", "arrow_embedding_inputs_artifact",
                     "arrow_embedding_inputs_verified", "arrow_embedding_inputs_verification"}
        if forbidden.intersection(receipt):
            raise TrainingCoordinationError("v8 worker receipt cannot contain legacy input verification fields")
        expected.update({name: spec.to_dict()[name] for name in (
            "source_inventory_artifact", "source_partitions_artifact", "embedding_receipt_set_artifact",
            "produced_record_projection_artifact", "embedding_receipt_artifacts")})
        expected.update(source_campaign_verified=True, produced_record_projection_verified=True)
    for key, value in expected.items():
        if _bytes(receipt.get(key)) != _bytes(value):
            raise TrainingCoordinationError(f"worker receipt binding mismatch: {key}")
    if "candidate_storage" in spec.to_dict():
        for key in ("candidate_storage", "base_checkpoint_dependencies"):
            if _bytes(receipt.get(key)) != _bytes(spec.to_dict()[key]):
                raise TrainingCoordinationError(f"worker receipt binding mismatch: {key}")
    if spec.expected_source_sha256:
        if receipt.get("source_manifest_verified") is not True or receipt.get("tree_file_sha256") != dict(spec.expected_source_sha256):
            raise TrainingCoordinationError("worker source manifest verification differs from job")
    if native and receipt.get("execution_mode") != "native_training":
        raise TrainingCoordinationError("native dispatch returned an injected test receipt")
    if spec.schema_version == ARROW_INPUT_SCHEMA_VERSION:
        _verify_arrow_input_runtime_statistics(spec, receipt, corpus_verification)
    candidate = receipt.get("candidate", {})
    if set(candidate) != {"path", "sha256", "bytes"}:
        raise TrainingCoordinationError("candidate requires path, sha256 and bytes")
    candidate_path = Path(candidate["path"])
    filename = "candidate.manifest.json" if spec.candidate_storage == "sparse" else "candidate.state.json"
    if candidate_path.is_symlink() or candidate_path.resolve() != (output / filename).resolve():
        raise TrainingCoordinationError("candidate is outside its attempt directory")
    if "candidate_storage" in spec.to_dict() and spec.candidate_storage == "full":
        if receipt.get("candidate_materialized_checkpoint") != {key: candidate[key] for key in ("sha256", "bytes")}:
            raise TrainingCoordinationError("full candidate artifact differs from materialized checkpoint byte identity")
    accepted = receipt.get("optimizer_accepted_epochs")
    if type(accepted) is not int or not 0 <= accepted <= spec.training_config.epochs:
        raise TrainingCoordinationError("invalid optimizer acceptance count")
    report = receipt.get("training_report", {})
    if report.get("accepted_epochs") != accepted:
        raise TrainingCoordinationError("optimizer acceptance disagrees with training report")


def _verify_arrow_input_runtime_statistics(spec: TrainingJobSpec, receipt: Mapping[str, Any],
                                          corpus_verification: Mapping[str, Any]) -> None:
    """Reconcile independently verified layout with bounded worker usage counters.

    Usage and timings are observations, not owner attestation of computation.
    All invariant layout and provenance fields must equal owner preflight.
    """
    initial = corpus_verification["arrow_embedding_inputs_initial_statistics"]
    counters = {"row_accesses", "scalar_accesses", "array_exports"}
    previous = initial
    for name in ("arrow_embedding_inputs_statistics_after_samples", "arrow_embedding_inputs_statistics_after_training"):
        observed = receipt.get(name)
        if not isinstance(observed, Mapping) or set(observed) != set(initial):
            raise TrainingCoordinationError(f"worker receipt binding mismatch: {name}")
        for key, value in observed.items():
            if key in counters:
                valid = type(value) is int and previous[key] <= value <= 2**63 - 1
            else:
                valid = _bytes(value) == _bytes(initial[key])
            if not valid:
                raise TrainingCoordinationError(f"worker receipt binding mismatch: {name}.{key}")
        if observed["row_accesses"] != initial["row_accesses"] + len(spec.samples) + len(spec.validation_samples):
            raise TrainingCoordinationError(f"worker receipt binding mismatch: {name}.row_accesses")
        previous = observed
    for name in ("sample_build_seconds", "sample_build_seconds_per_sample"):
        value = receipt.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise TrainingCoordinationError(f"invalid worker timing: {name}")
    if not math.isclose(receipt["sample_build_seconds_per_sample"] * (len(spec.samples) + len(spec.validation_samples)),
                        receipt["sample_build_seconds"], rel_tol=1e-12, abs_tol=1e-12):
        raise TrainingCoordinationError("inconsistent worker sample build timing")


def _verify_and_stage_patches(registry: Any, spec: TrainingJobSpec, receipt: Mapping[str, Any],
                              policy: SparseCheckpointPolicy) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Replay accepted updates before staging a manifest or compacted checkpoint.

    Full candidates keep the previous byte and state checks. Sparse candidates
    seal the exact materialized bytes without writing those bytes on each job.
    The owner chooses compaction independently of worker artifact descriptors.
    """
    segments = receipt.get("sparse_patch_segments")
    if not isinstance(segments, list):
        raise TrainingCoordinationError("sparse_patch_segments must be an array")
    if not spec.capture_sparse_patches:
        if segments:
            raise TrainingCoordinationError("unexpected sparse segments without capture enabled")
        return {"sparse_replay_verified": False, "sparse_patch_artifacts": [],
                "checkpoint_storage": "full_json", "checkpoint_dependencies": []}, None
    if len(segments) != receipt["optimizer_accepted_epochs"]:
        raise TrainingCoordinationError("sparse segment count differs from accepted epochs")
    from .modal_autoencoder_patch_codec import MAX_PATCH_BYTES, decode_patch, replay_patch
    from .modal_autoencoder_sparse_checkpoint import (
        checkpoint_identity, encode_manifest, resolve_checkpoint, write_checkpoint,
    )

    started = time.perf_counter()
    references = [spec.base_checkpoint, *spec.base_checkpoint_dependencies]
    paths = {ref.sha256: ref for ref in references}

    def resolver(reference: Mapping[str, Any]) -> Path:
        bound = paths.get(reference["sha256"])
        if bound is None or bound.bytes != reference["bytes"]:
            raise TrainingCoordinationError("checkpoint dependency is missing from the job binding")
        descriptor = registry.verify_artifact(reference)
        if Path(bound.path).resolve() != registry.artifact_path(descriptor).resolve():
            raise TrainingCoordinationError("checkpoint dependency is not owner staged")
        return registry.artifact_path(descriptor)

    resolved = None
    if "candidate_storage" in spec.to_dict():
        resolved = resolve_checkpoint({"sha256": spec.base_checkpoint.sha256, "bytes": spec.base_checkpoint.bytes},
                                      resolver=resolver)
        if {(ref["sha256"], ref["bytes"]) for ref in resolved.artifacts} != {(ref.sha256, ref.bytes) for ref in references}:
            raise TrainingCoordinationError("checkpoint dependency closure contains unused artifacts")
        state = resolved.state
    else:
        from .modal_autoencoder import ModalAutoencoderTrainingState
        base = _read_bounded(Path(spec.base_checkpoint.path), min(spec.base_checkpoint.bytes, registry.max_artifact_bytes))
        if len(base) != spec.base_checkpoint.bytes or _sha(base) != spec.base_checkpoint.sha256:
            raise TrainingCoordinationError("base changed before sparse replay")
        state = ModalAutoencoderTrainingState.from_dict(_read_json(base))
        del base
    if state.state_identity_record().to_dict() != receipt["base_state_identity"]:
        raise TrainingCoordinationError("sparse base state identity differs from receipt")
    staged = []
    for index, descriptor in enumerate(segments):
        if not isinstance(descriptor, dict) or type(descriptor.get("bytes")) is not int or not 0 < descriptor["bytes"] <= MAX_PATCH_BYTES:
            raise TrainingCoordinationError("invalid sparse segment descriptor or byte bound")
        path = Path(descriptor.get("path", ""))
        expected_path = Path(spec.output_directory) / f"accepted-{index:06d}.patch.json"
        if path.is_symlink() or path.resolve() != expected_path.resolve():
            raise TrainingCoordinationError("sparse segment is outside its ordered attempt path")
        raw = _read_bounded(path, descriptor["bytes"])
        if len(raw) != descriptor.get("bytes") or _sha(raw) != descriptor.get("sha256"):
            raise TrainingCoordinationError("sparse segment size or SHA-256 mismatch")
        segment = decode_patch(raw)
        expected_provenance = {"job_id": spec.job_id, "run_id": spec.run_id,
                               "job_spec_sha256": spec.canonical_sha256,
                               "commit_label": descriptor.get("capture_context", {}).get("label", "")}
        if dict(segment.provenance) != expected_provenance:
            raise TrainingCoordinationError("sparse segment job/attempt provenance mismatch")
        context = descriptor.get("capture_context", {})
        for name, expected in {"base_state_identity": segment.base_state_identity,
                               "result_state_identity": segment.result_state_identity,
                               "base_revision": segment.patch.base_revision,
                               "result_revision": segment.patch.result_revision}.items():
            if context.get(name) != expected:
                raise TrainingCoordinationError("sparse capture context differs from sealed segment")
        replay_patch(state, segment, expected_base_version_id=spec.base_version_id, expected_sequence=index)
        staged.append(registry.stage_artifact(path, descriptor["sha256"]))
    candidate_limit = min(registry.max_artifact_bytes, 1024 * 1024) if spec.candidate_storage == "sparse" else registry.max_artifact_bytes
    candidate_raw = _read_bounded(Path(receipt["candidate"]["path"]), candidate_limit)
    if len(candidate_raw) != receipt["candidate"]["bytes"] or _sha(candidate_raw) != receipt["candidate"]["sha256"]:
        raise TrainingCoordinationError("candidate changed before sparse replay comparison")
    if spec.candidate_storage != "sparse" and _bytes(state.to_dict()) != _bytes(_read_json(candidate_raw)):
        raise TrainingCoordinationError("sparse replay does not reconstruct the complete candidate")
    if state.state_identity_record().to_dict() != receipt["candidate_state_identity"]:
        raise TrainingCoordinationError("sparse replay candidate identity mismatch")
    summary = {"sparse_replay_verified": True, "sparse_patch_artifacts": staged,
               "sparse_patch_bytes": sum(item["bytes"] for item in staged)}
    reasons = []
    if spec.candidate_storage == "sparse":
        assert resolved is not None
        depth = resolved.depth + 1
        cumulative_bytes = resolved.total_patch_bytes + summary["sparse_patch_bytes"]
        if depth >= policy.max_depth:
            reasons.append("max_depth")
        if cumulative_bytes >= resolved.anchor_checkpoint["bytes"] * policy.max_patch_fraction:
            reasons.append("patch_fraction")
    # Compaction thresholds depend only on the verified chain and owner policy.
    # All sparse validation and staging below stay within scratch cleanup.
    workspace = (tempfile.TemporaryDirectory(prefix=".compact-", dir=registry.artifact_root)
                 if reasons else nullcontext(None))
    with workspace as directory:
        if directory is not None:
            # The owner reconstructed this private state independently. Serialize it
            # once into scratch; none of these bytes are staged until the existing
            # receipt, base and exact manifest comparisons below have passed.
            written = write_checkpoint(state, Path(directory) / "candidate.state.json")
            materialized = {key: written[key] for key in ("sha256", "bytes")}
        else:
            materialized = (checkpoint_identity(state) if resolved is not None
                            else {key: receipt["candidate"][key] for key in ("sha256", "bytes")})
        if "candidate_storage" in spec.to_dict():
            if receipt.get("candidate_materialized_checkpoint") != materialized:
                raise TrainingCoordinationError("sparse replay does not reconstruct the complete candidate bytes")
            if receipt.get("base_materialized_checkpoint") != resolved.materialized_checkpoint:
                raise TrainingCoordinationError("base materialized checkpoint differs from verified parent")
        summary["candidate_materialized_checkpoint"] = materialized
        if spec.candidate_storage != "sparse":
            summary.update(checkpoint_storage="full_json", checkpoint_dependencies=[])
            summary["sparse_replay_seconds"] = time.perf_counter() - started
            return summary, None

        assert resolved is not None
        expected_manifest = encode_manifest(
            parent={"sha256": spec.base_checkpoint.sha256, "bytes": spec.base_checkpoint.bytes},
            base_version_id=spec.base_version_id, patches=staged,
            materialized_checkpoint=materialized, state_identity=state.state_identity(),
            result_revision=state.state_identity_record().to_dict()["revision"],
            provenance={"job_id": spec.job_id, "run_id": spec.run_id, "job_spec_sha256": spec.canonical_sha256})
        if candidate_raw != expected_manifest:
            raise TrainingCoordinationError("sparse candidate manifest differs from verified parent and accepted patches")
        summary.update(
            worker_candidate_artifact={key: receipt["candidate"][key] for key in ("sha256", "bytes")},
            sparse_compaction_policy={"max_depth": policy.max_depth, "max_patch_fraction": policy.max_patch_fraction},
            sparse_compaction_performed=bool(reasons), sparse_compaction_reasons=reasons,
            candidate_chain_depth_before_compaction=depth,
            candidate_cumulative_patch_bytes_before_compaction=cumulative_bytes)
        if reasons:
            candidate = registry.stage_artifact(written["path"], written["sha256"])
            if candidate != materialized:
                raise TrainingCoordinationError("compacted checkpoint bytes differ from replay identity")
            # Retain the small worker manifest as auditable evidence of compaction.
            registry.stage_artifact(receipt["candidate"]["path"], receipt["candidate"]["sha256"])
            summary.update(checkpoint_storage="full_json", checkpoint_dependencies=[],
                           checkpoint_chain_depth=0, checkpoint_cumulative_patch_bytes=0,
                           checkpoint_anchor=candidate)
        else:
            candidate = registry.stage_artifact(receipt["candidate"]["path"], receipt["candidate"]["sha256"])
            closure = {ref["sha256"]: dict(ref) for ref in (*resolved.artifacts, *staged)}
            summary.update(checkpoint_storage="sparse_manifest",
                           checkpoint_dependencies=sorted(closure.values(), key=lambda ref: ref["sha256"]),
                           checkpoint_chain_depth=depth, checkpoint_cumulative_patch_bytes=cumulative_bytes,
                           checkpoint_anchor=dict(resolved.anchor_checkpoint))
    # Include scratch cleanup in the existing complete owner-phase timing.
    summary["sparse_replay_seconds"] = time.perf_counter() - started
    return summary, candidate


def _result_summary(receipt: Mapping[str, Any], receipt_artifact: Mapping[str, Any], *, native: bool) -> dict[str, Any]:
    after = receipt["training_report"].get("after", {})
    targets = after.get("legal_ir_target_count", 0)
    if type(targets) is not int or targets < 0:
        raise TrainingCoordinationError("invalid legal-IR target count")
    summary = {
        "admitted": False, "promotion_performed": False,
        "job_spec_sha256": receipt["job_spec_canonical_sha256"],
        "worker_receipt_artifact": dict(receipt_artifact),
        "execution_mode": "native_training" if native else "injected_test",
        "optimizer_accepted_epochs": receipt["optimizer_accepted_epochs"],
        "legal_ir_target_count": targets,
        "bridge_status": "active" if targets else "no_targets",
        "bridge_names": receipt["bridge_names"],
        "legal_ir_evaluate_provers": receipt["legal_ir_evaluate_provers"],
        "legal_ir_parallel_workers": receipt["legal_ir_parallel_workers"],
        "metric_disk_cache": receipt["metric_disk_cache"],
        "use_sample_memory": receipt["use_sample_memory"],
        "sample_count": receipt["sample_count"],
        "validation_sample_count": receipt["validation_sample_count"],
        "validation_mode": receipt["validation_mode"],
        "heldout_canary_qualified": False,
        "worker_elapsed_seconds": receipt["elapsed_seconds"],
        "training_seconds": receipt["training_seconds"],
        "process_target_cache_initial_entries": receipt["process_target_cache_initial_entries"],
        "process_cache_initially_empty": receipt["process_cache_initially_empty"],
        "profile_projection": receipt["profile_projection"],
        "source_manifest_verified": receipt["source_manifest_verified"],
        "caller_identity_labels_verified": False,
        "corpus_manifest_artifact": receipt["corpus_manifest_artifact"],
        "corpus_source_artifacts": receipt["corpus_source_artifacts"],
        "corpus_verification": receipt["corpus_verification"],
        "corpus_verification_seconds": receipt["corpus_verification_seconds"],
        "dataset_and_split_identity_verified": receipt["dataset_and_split_identity_verified"],
        "target_snapshot_id": receipt["target_snapshot_id"],
        "shared_targets_verified": receipt["shared_targets_verified"],
        "target_shard_max_bytes": receipt.get("target_shard_max_bytes", 64 * 1024 * 1024),
        "shared_target_count": receipt["shared_target_count"],
        "shared_target_status_counts": receipt["shared_target_status_counts"],
        "target_load_seconds": receipt["target_load_seconds"],
        "weight_storage": receipt["weight_storage"],
        "arrow_feature_weights_artifact": receipt["arrow_feature_weights_artifact"],
        "stopped_reason": str(receipt["training_report"].get("stopped_reason", ""))[:1024],
    }
    if "candidate_storage" in receipt:
        summary.update({name: receipt[name] for name in (
            "candidate_storage", "base_materialized_checkpoint", "candidate_materialized_checkpoint",
            "base_checkpoint_load_seconds", "base_checkpoint_chain_depth",
            "base_checkpoint_replayed_patch_bytes", "candidate_serialization_seconds")})
    if receipt["job_spec"]["schema_version"] in {INDEXED_SCHEMA_VERSION, PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
        summary.update({name: receipt[name] for name in (
            "corpus_index_artifact", "corpus_selection_sha256", "corpus_index_membership_verified")})
    if receipt["job_spec"]["schema_version"] in {PRODUCED_SCHEMA_VERSION, ARROW_INPUT_SCHEMA_VERSION}:
        summary.update({name: receipt[name] for name in (
            "embedding_production_artifact", "embedding_production_verified", "embedding_production_verification")})
    if receipt["job_spec"]["schema_version"] == ARROW_INPUT_SCHEMA_VERSION:
        summary.update({name: receipt[name] for name in (
            "arrow_embedding_inputs_artifact", "arrow_embedding_inputs_verified", "arrow_embedding_inputs_verification",
            "embedding_input_storage", "arrow_embedding_inputs_statistics_before_samples",
            "arrow_embedding_inputs_statistics_after_samples", "arrow_embedding_inputs_statistics_after_training",
            "sample_build_seconds", "sample_build_seconds_per_sample")})
    if receipt["job_spec"]["schema_version"] == CAMPAIGN_SCHEMA_VERSION:
        summary.update({name: receipt[name] for name in (
            "source_inventory_artifact", "source_partitions_artifact", "embedding_receipt_set_artifact",
            "produced_record_projection_artifact", "embedding_receipt_artifacts",
            "source_campaign_verified", "produced_record_projection_verified")})
    if "target_reduction" in receipt:
        summary["target_reduction"] = receipt["target_reduction"]
    return summary


def _prepare_completion(registry: Any, spec: TrainingJobSpec, returned: Mapping[str, Any], *,
                        native: bool, corpus_verification: Mapping[str, Any],
                        sparse_checkpoint_policy: SparseCheckpointPolicy
                        ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Verify and stage one result on an owner-side filesystem thread.

    The only registry methods allowed here (including in replay) are
    artifact_path, verify_artifact and stage_artifact: they use no SQL or
    connection. This follows the daemon staging boundary. Run commands and
    durable completion stay on the calling owner thread. Staged bytes confer
    no authority if the owner loses the lease while this work is in progress.
    """
    receipt, receipt_raw = _verify_receipt(
        spec, returned, native=native, corpus_verification=corpus_verification)
    patch_summary, candidate = _verify_and_stage_patches(
        registry, spec, receipt, sparse_checkpoint_policy)
    if candidate is None:
        candidate = registry.stage_artifact(receipt["candidate"]["path"], receipt["candidate"]["sha256"])
    if spec.candidate_storage != "sparse" and candidate["bytes"] != receipt["candidate"]["bytes"]:
        raise TrainingCoordinationError("candidate size disagrees with receipt")
    receipt_artifact = registry.stage_artifact(Path(spec.output_directory) / "receipt.json", _sha(receipt_raw))
    summary = _result_summary(receipt, receipt_artifact, native=native)
    summary.update(patch_summary)
    return candidate, receipt_artifact, summary


def _owned_operation_slot(run_id: str, kind: str, renewal_number: int | None = None) -> str:
    """Stable semantic slots inside an already owner-bound request journal."""
    if kind not in {"claim", "renew", "complete", "fail"}:
        raise TrainingCoordinationError("unsupported owned coordinator operation")
    suffix = kind
    if kind == "renew":
        if type(renewal_number) is not int or renewal_number < 1:
            raise TrainingCoordinationError("owned renewal number must be positive")
        suffix += f"-{renewal_number:06d}"
    elif renewal_number is not None:
        raise TrainingCoordinationError("only renewals have an ordinal")
    return "training-" + _sha(run_id.encode("utf-8")) + "-" + suffix


def _owned_journal_capacity(journal: Any, *, run_count: int, max_workers: int,
                            lease_seconds: float, poll_seconds: float,
                            timeout_seconds: float) -> dict[str, int]:
    """Conservative operation/byte allowance before any claim or launch.

    This does not reserve capacity in the journal or admit host resources. Its
    existing bounds still apply to every subsequent durable write.
    """
    from .autoencoder_daemon_operation_journal import (
        DurableDaemonOperationJournal, MAX_JOURNAL_BYTES, MAX_OPERATIONS, MAX_VALUE_BYTES,
    )
    if type(journal) is not DurableDaemonOperationJournal:
        raise TrainingCoordinationError("owned dispatch requires the exact durable journal")
    operations = journal.operations()
    if journal.pending():
        raise TrainingCoordinationError("unresolved journal operations require recovery")
    margin = max(poll_seconds * 2, lease_seconds / 3)
    renewal_interval = lease_seconds - margin
    # Claim, two forced renewals, completion and a possible failure per run;
    # other renewals are bounded across concurrently active jobs by the deadline.
    concurrent = min(run_count, max_workers)
    additional = (5 + max(0, concurrent - 1)) * run_count + concurrent * (
        math.ceil(timeout_seconds / renewal_interval) + 1)
    current_bytes = len(_read_bounded(journal.path, MAX_JOURNAL_BYTES))
    projected_bytes = current_bytes + MAX_VALUE_BYTES + additional * (2 * MAX_VALUE_BYTES + 1024)
    if len(operations) + additional > MAX_OPERATIONS or projected_bytes > MAX_JOURNAL_BYTES:
        raise TrainingCoordinationError("dispatch exceeds conservative durable journal capacity")
    return {"additional_operation_bound": additional, "projected_journal_bytes": projected_bytes}


def run_training_jobs(registry: Any, specs: Sequence[TrainingJobSpec], *, max_workers: int = 2,
                      lease_seconds: float = 300.0, poll_seconds: float = 0.25,
                      worker_id_prefix: str = "autoencoder",
                      executor_factory: Callable[..., Any] | None = None,
                      worker_function: Callable[..., Mapping[str, Any]] = execute_training_job,
                      clock: Callable[[], float] = time.time,
                      defer_target_hydration_gc: bool = False,
                      reduce_native_targets: bool = False,
                      sparse_checkpoint_policy: SparseCheckpointPolicy = SparseCheckpointPolicy(),
                      _native_pool: Any = None) -> dict[str, Any]:
    """Dispatch registered jobs with the existing spawned-worker defaults.

    Injected executor/worker hooks remain test evidence. Persistent prepared
    campaign execution uses the separate private owner entry point.
    """
    return _run_training_jobs(
        registry, specs, max_workers=max_workers, lease_seconds=lease_seconds,
        poll_seconds=poll_seconds, worker_id_prefix=worker_id_prefix,
        executor_factory=executor_factory, worker_function=worker_function, clock=clock,
        defer_target_hydration_gc=defer_target_hydration_gc,
        reduce_native_targets=reduce_native_targets, sparse_checkpoint_policy=sparse_checkpoint_policy,
        native_pool=_native_pool)


def _run_owned_training_jobs(registry: Any, specs: Sequence[TrainingJobSpec], *,
                             operation_journal: Any, before_claim: Callable[[TrainingJobSpec], None],
                             before_prepare: Callable[[TrainingJobSpec, Mapping[str, Any]], None],
                             worker_id: str, timeout_seconds: float, supervisor: Any = None,
                             before_submit: Callable[..., None] | None = None,
                             after_terminal: Callable[..., None] | None = None,
                             max_workers: int = 2, lease_seconds: float = 300.0,
                             poll_seconds: float = 0.25,
                             executor_factory: Callable[..., Any] | None = None,
                             worker_function: Callable[..., Mapping[str, Any]] = execute_training_job,
                             clock: Callable[[], float] = time.time,
                             defer_target_hydration_gc: bool = False,
                             reduce_native_targets: bool = False,
                             sparse_checkpoint_policy: SparseCheckpointPolicy = SparseCheckpointPolicy()) -> dict[str, Any]:
    """Execute a freshly validated owner selection with durable mutations.

    The adapter owns request, resource and restart reconciliation. It supplies
    only pristine queued jobs; this function never resumes a prior attempt.
    Test injection has no native process identity and stays ``injected_test``.
    """
    from .autoencoder_daemon_operation_journal import DurableDaemonOperationJournal
    if type(operation_journal) is not DurableDaemonOperationJournal:
        raise TrainingCoordinationError("owned dispatch requires the exact durable journal")
    owner = {"database_path": str(registry.database_path), "artifact_root": str(registry.artifact_root)}
    if operation_journal.binding.get("owner") != owner:
        raise TrainingCoordinationError("owned journal belongs to another registry")
    if not callable(before_claim) or not callable(before_prepare):
        raise TrainingCoordinationError("owned dispatch requires admission and completion resource checks")
    if after_terminal is not None and not callable(after_terminal):
        raise TrainingCoordinationError("owned terminal callback must be callable")
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 86400):
        raise TrainingCoordinationError("owned timeout_seconds must be within (0, 86400]")
    if supervisor is not None:
        from .autoencoder_campaign_process import _CampaignProcessExecutor
        if type(supervisor) is not _CampaignProcessExecutor:
            raise TrainingCoordinationError("owned native execution requires the exact supervisor")
        if executor_factory is not None or worker_function is not execute_training_job:
            raise TrainingCoordinationError("native supervisor cannot carry injected worker hooks")
        if (supervisor.defer_target_hydration_gc != defer_target_hydration_gc
                or supervisor.reduce_native_targets != reduce_native_targets):
            raise TrainingCoordinationError("native supervisor runtime policy differs")
    elif executor_factory is None:
        raise TrainingCoordinationError("owned execution requires a supervisor or injected test executor")
    elif not callable(before_submit):
        raise TrainingCoordinationError("injected owned execution requires a start callback")
    return _run_training_jobs(
        registry, specs, max_workers=max_workers, lease_seconds=lease_seconds,
        poll_seconds=poll_seconds, worker_id_prefix=worker_id,
        executor_factory=executor_factory, worker_function=worker_function, clock=clock,
        defer_target_hydration_gc=defer_target_hydration_gc,
        reduce_native_targets=reduce_native_targets, sparse_checkpoint_policy=sparse_checkpoint_policy,
        operation_journal=operation_journal, owned_supervisor=supervisor,
        before_claim=before_claim, before_prepare=before_prepare, before_submit=before_submit,
        after_terminal=after_terminal, timeout_seconds=timeout_seconds)


def _run_training_jobs(registry: Any, specs: Sequence[TrainingJobSpec], *, max_workers: int = 2,
                      lease_seconds: float = 300.0, poll_seconds: float = 0.25,
                      worker_id_prefix: str = "autoencoder",
                      executor_factory: Callable[..., Any] | None = None,
                      worker_function: Callable[..., Mapping[str, Any]] = execute_training_job,
                      clock: Callable[[], float] = time.time,
                      defer_target_hydration_gc: bool = False,
                      reduce_native_targets: bool = False,
                      sparse_checkpoint_policy: SparseCheckpointPolicy = SparseCheckpointPolicy(),
                      operation_journal: Any = None, owned_supervisor: Any = None,
                      before_claim: Callable[[TrainingJobSpec], None] | None = None,
                      before_prepare: Callable[[TrainingJobSpec, Mapping[str, Any]], None] | None = None,
                      before_submit: Callable[..., None] | None = None,
                      after_terminal: Callable[..., None] | None = None,
                      timeout_seconds: float | None = None, native_pool: Any = None) -> dict[str, Any]:
    """Dispatch precreated runs, stage results, and durably record completion.

    Native execution uses ``spawn``. Test injection is always marked as such in
    the durable result. Each run must reference a staged job JSON artifact via
    ``spec.job_spec_artifact`` and its canonical digest via ``job_spec_sha256``.
    This function never promotes a branch head or publishes a model.

    ``defer_target_hydration_gc`` opts native spawned workers into bounded cyclic
    GC deferral during verified bundle hydration, including explicit cleanup.
    Worker receipts record whether the runtime was eligible and applied it.
    It is an execution policy; target and training semantics are unchanged.

    ``reduce_native_targets`` retains immutable evaluator values after complete
    native bundle validation. Ineligible targets retain their full objects.
    The private runtime values confer no artifact-verification authority.

    ``max_seconds`` is the existing optimizer's cooperative budget, not a hard
    process deadline. An unresponsive native dependency can delay pool shutdown;
    host-level timeout/termination supervision remains a later qualification.
    Receipt verification, replay and staging use one owner-side filesystem
    thread while this thread renews every active lease. Completed workers occupy
    their dispatch slot until finalization; replay does not add parallel state
    graphs. Registry commands remain on this thread. Final CompleteRun artifact
    rehash is still synchronous: allow for that latency when choosing leases.
    Python code holding the GIL or unresponsive I/O can still delay heartbeats;
    this is cooperative liveness, not a hard real-time guarantee.
    """
    if type(max_workers) is not int or not 1 <= max_workers <= 32:
        raise TrainingCoordinationError("max_workers must be an integer within [1, 32]")
    if type(defer_target_hydration_gc) is not bool:
        raise TrainingCoordinationError("defer_target_hydration_gc must be boolean")
    if type(reduce_native_targets) is not bool:
        raise TrainingCoordinationError("reduce_native_targets must be boolean")
    owned = operation_journal is not None
    native = (owned_supervisor is not None if owned else
              executor_factory is None and worker_function is execute_training_job)
    if native_pool is not None:
        from .autoencoder_native_pool import _NativeTrainingPool
        if (type(native_pool) is not _NativeTrainingPool or not native or owned
                or defer_target_hydration_gc or reduce_native_targets):
            raise TrainingCoordinationError("native retained pool cannot carry injected or owned runtime hooks")
    owned_deadline = time.monotonic() + timeout_seconds if owned else None
    if defer_target_hydration_gc and not native:
        raise TrainingCoordinationError("GC deferral requires the native spawned worker executor")
    if reduce_native_targets and not native:
        raise TrainingCoordinationError("target reduction requires the native spawned worker executor")
    if not isinstance(sparse_checkpoint_policy, SparseCheckpointPolicy):
        raise TrainingCoordinationError("sparse_checkpoint_policy must be a SparseCheckpointPolicy")
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float)) or not math.isfinite(lease_seconds) or not 0 < lease_seconds <= 86400:
        raise TrainingCoordinationError("lease_seconds must be within (0, 86400]")
    if isinstance(poll_seconds, bool) or not isinstance(poll_seconds, (int, float)) or not math.isfinite(poll_seconds) or not 0 < poll_seconds <= min(30, lease_seconds / 4):
        raise TrainingCoordinationError("poll_seconds must be positive and <= min(30, lease_seconds/4)")
    if not isinstance(worker_id_prefix, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}", worker_id_prefix):
        raise TrainingCoordinationError("worker_id_prefix must be a bounded identifier")
    spec_list = list(specs)
    if native_pool is not None:
        native_pool.validate_dispatch(max_workers, len(spec_list))
    if owned and not 1 <= len(spec_list) <= 64:
        raise TrainingCoordinationError("owned dispatch requires between 1 and 64 fresh jobs")
    for spec in spec_list:
        if not isinstance(spec, TrainingJobSpec) or spec.training_config.max_seconds > lease_seconds:
            raise TrainingCoordinationError("each job's max_seconds must fit within the bounded lease")
    corpus_checks = _validate_runs(registry, spec_list)
    journal_capacity = None
    if owned:
        journal_capacity = _owned_journal_capacity(
            operation_journal, run_count=len(spec_list), max_workers=max_workers,
            lease_seconds=lease_seconds, poll_seconds=poll_seconds, timeout_seconds=timeout_seconds)
        prior_operations = operation_journal.operations()
        for spec in spec_list:
            prefix = _owned_operation_slot(spec.run_id, "claim").removesuffix("claim")
            if any(slot.startswith(prefix) for slot in prior_operations):
                raise TrainingCoordinationError("previous job operations require owner reconciliation")
    invocation = uuid.uuid4().hex
    started = time.perf_counter()
    completed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    active: dict[Any, dict[str, Any]] = {}
    next_index = 0
    operation_counter = 0
    mutation_retries = 0
    resolved_operations = 0
    abort_dispatch = False
    needs_recovery = False

    def poll_owned() -> None:
        if owned:
            if time.monotonic() >= owned_deadline:
                raise TrainingCoordinationError("owned dispatch exceeded its wall-time bound")
            if owned_supervisor is not None:
                owned_supervisor.poll()

    def operation(kind: str) -> str:
        nonlocal operation_counter
        operation_counter += 1
        return f"training:{invocation}:{kind}:{operation_counter}"

    def mutate(command: str, method: Callable[..., dict[str, Any]], args: tuple[Any, ...],
               payload: Mapping[str, Any], *, renewal_number: int | None = None) -> dict[str, Any]:
        """Resolve response loss using the same operation ID and exact payload.

        A registry method may commit successfully and then lose its response.
        Changing the operation ID would turn a retry into another transition.
        The public ledger lookup verifies the original command/payload binding.
        """
        nonlocal mutation_retries, resolved_operations
        if owned:
            if operation_journal.pending():
                raise TrainingCoordinationError("unresolved journal operation requires recovery")
            run_id = payload["run_id"] if command == "ClaimRun" else payload["lease"]["run_id"]
            kind = {"ClaimRun": "claim", "RenewLease": "renew",
                    "CompleteRun": "complete", "FailRun": "fail"}[command]
            slot = _owned_operation_slot(run_id, kind, renewal_number)
            return operation_journal.invoke(registry, slot, command, _read_json(_bytes(payload)))
        operation_id = operation(command)
        retained_payload = _read_json(_bytes(payload))
        last_error: Exception | None = None
        for attempt in range(2):
            if attempt:
                mutation_retries += 1
            try:
                return method(operation_id, *args)
            except Exception as exc:
                last_error = exc
                try:
                    receipt = registry.resolve_operation(operation_id, command, retained_payload)
                except Exception:
                    # A transient read failure does not authorize a new command.
                    continue
                if receipt is not None:
                    resolved_operations += 1
                    return receipt
        assert last_error is not None
        raise last_error

    def renew(item: dict[str, Any], *, force: bool = False) -> None:
        margin = max(poll_seconds * 2, lease_seconds / 3)
        if force or clock() >= item["lease"]["expires_at"] - margin:
            lease = item["lease"]
            item["lease"] = mutate("RenewLease", registry.renew_lease, (lease, lease_seconds),
                                   {"lease": lease, "lease_seconds": lease_seconds},
                                   renewal_number=item["renewal_count"] + 1)["lease"]
            item["renewal_count"] += 1

    def record_failure(item: dict[str, Any], exc: BaseException) -> None:
        nonlocal abort_dispatch, needs_recovery
        error = {"run_id": item["spec"].run_id, "job_id": item["spec"].job_id,
                 "admitted": False, "promotion_performed": False,
                 "error_type": type(exc).__name__, "error": str(exc)[:2048],
                 "execution_mode": "native_training" if native else "injected_test"}
        if owned:
            # A registry transition cannot turn an uncertain live child into
            # a failed job. The supervisor raises if death cannot be confirmed.
            if owned_supervisor is not None:
                owned_supervisor.stop(item["spec"])
            if operation_journal.pending():
                abort_dispatch = True
                needs_recovery = True
                failed.append({**error, "failure_recorded": False, "recovery_required": True})
                return
        try:
            current = registry.get_run(item["spec"].run_id)
            if owned and current["status"] == "failed":
                slot = _owned_operation_slot(item["spec"].run_id, "fail")
                old = operation_journal.operations().get(slot)
                durable = (operation_journal.resolve(registry, slot)
                           if old is not None and old["command"] == "FailRun" else None)
                error["failure_recorded"] = durable is not None
                if durable is None:
                    abort_dispatch = True
                    needs_recovery = True
                    error["recovery_required"] = True
                failed.append(error)
                return
            if current["status"] == "completed":
                if owned:
                    abort_dispatch = True
                    needs_recovery = True
                    failed.append({**error, "failure_recorded": False, "recovery_required": True})
                    return
                # If operation receipt reads remain unavailable, do not relabel
                # authoritative completed work as failed or issue FailRun.
                completed.append({"run_id": current["run_id"], "job_id": item["spec"].job_id,
                                  "status": "completed", "admitted": False, "promoted": False,
                                  "completion_receipt_resolved": False, "result": current["result"],
                                  "coordination_error": str(exc)[:2048]})
                return
            lease = item["lease"]
            durable = mutate("FailRun", registry.fail_run, (lease, error),
                             {"lease": lease, "result": error})
            error["failure_recorded"] = durable["status"] == "failed"
            if (owned and after_terminal is not None and not item.get("quarantined")
                    and not operation_journal.pending()):
                after_terminal(item["spec"], _read_json(_bytes(
                    {**durable, "job_id": item["spec"].job_id, "result": error})))
        except Exception as failure:
            error.setdefault("failure_recorded", False)
            error["failure_record_error"] = str(failure)[:2048]
            if owned:
                abort_dispatch = True
                needs_recovery = True
                error["recovery_required"] = True
        failed.append(error)

    def renew_active(*, force: bool = False, exclude_run_id: str | None = None) -> None:
        for future, item in list(active.items()):
            if item.get("quarantined") or item["spec"].run_id == exclude_run_id:
                continue
            try:
                renew(item, force=force)
            except Exception as exc:
                future.cancel()
                if owned:
                    # A preparation thread may still be writing CAS evidence.
                    # Root cleanup follows the drained pool; do not release its
                    # resource monitoring from this failure callback.
                    item["quarantined"] = True
                record_failure(item, exc)
                item["quarantined"] = True

    factory = executor_factory or ProcessPoolExecutor
    executor = (native_pool if native_pool is not None else
                owned_supervisor if owned_supervisor is not None else
                factory(max_workers=max_workers, mp_context=multiprocessing.get_context("spawn")))
    preparation_pool = None
    try:
        preparation_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="autoencoder-completion")
        while (next_index < len(spec_list) and not abort_dispatch) or active:
            poll_owned()
            while next_index < len(spec_list) and len(active) < max_workers and not abort_dispatch:
                spec = spec_list[next_index]
                next_index += 1
                try:
                    if owned:
                        before_claim(spec)
                        poll_owned()
                    worker_id = (worker_id_prefix if owned else
                                 f"{worker_id_prefix}:{invocation[:12]}:{next_index}")
                    lease = mutate("ClaimRun", registry.claim_run, (spec.run_id, worker_id, lease_seconds),
                                   {"run_id": spec.run_id, "worker_id": worker_id,
                                    "lease_seconds": lease_seconds})["lease"]
                except Exception as exc:
                    if owned:
                        abort_dispatch = True
                        needs_recovery = bool(operation_journal.pending())
                    failed.append({"run_id": spec.run_id, "job_id": spec.job_id,
                                   "admitted": False, "promotion_performed": False,
                                   "failure_recorded": False, "error_type": type(exc).__name__,
                                   "error": str(exc)[:2048],
                                   **({"recovery_required": needs_recovery} if owned else {})})
                    continue
                item = {"spec": spec, "lease": lease, "renewal_count": 0}
                try:
                    # Registry and its DuckDB connection never cross this boundary.
                    if reduce_native_targets:
                        entry = (_execute_native_training_job_with_deferred_gc_and_reduced_targets
                                 if defer_target_hydration_gc else _execute_native_training_job_with_reduced_targets)
                    else:
                        entry = _execute_native_training_job_with_deferred_gc if defer_target_hydration_gc else worker_function
                    if owned:
                        job_ref = registry.verify_artifact(
                            registry.get_run(spec.run_id)["spec"]["job_spec_artifact"])
                        job_artifact = {**job_ref, "path": str(registry.artifact_path(job_ref))}
                    if native_pool is not None:
                        future = executor.submit(spec)
                    elif owned_supervisor is not None:
                        future = executor.submit(spec, lease=lease, job_artifact=job_artifact)
                    else:
                        if owned:
                            before_submit(spec, lease, job_artifact)
                        future = executor.submit(entry, spec)
                    active[future] = item
                except Exception as exc:
                    record_failure(item, exc)
            renew_active()
            if not active:
                continue
            done, _ = wait(tuple(active), timeout=poll_seconds, return_when=FIRST_COMPLETED)
            poll_owned()
            for future in done:
                item = active[future]
                spec = item["spec"]
                if item.get("quarantined"):
                    active.pop(future)
                    continue
                preparation = None
                try:
                    returned = future.result()
                    renew(item, force=True)
                    if owned:
                        before_prepare(spec, returned)
                        poll_owned()
                    preparation = preparation_pool.submit(
                        _prepare_completion, registry, spec, returned, native=native,
                        corpus_verification=corpus_checks[spec.run_id],
                        sparse_checkpoint_policy=sparse_checkpoint_policy)
                    # Keep this item and all other done/running workers in active
                    # until finalization. Quarantine never stops other heartbeats.
                    while not preparation.done():
                        poll_owned()
                        renew_active()
                        if item.get("quarantined"):
                            preparation.cancel()
                        _wait_for_preparation((preparation,), timeout=poll_seconds)
                    if item.get("quarantined"):
                        # A running filesystem task cannot be cancelled safely.
                        # It has drained; its CAS bytes are not a registered version.
                        continue
                    candidate, receipt_artifact, summary = preparation.result()
                    renew(item, force=True)
                    lease = item["lease"]
                    if spec.capture_sparse_patches:
                        summary["sparse_acceptance_assignment"] = {
                            name: lease[name] for name in ("run_id", "attempt", "owner_generation", "fence", "worker_id")}
                    durable = mutate("CompleteRun", registry.complete_run, (lease, candidate, summary),
                                     {"lease": lease, "artifact": candidate, "result": summary})
                    terminal = {**durable, "job_id": spec.job_id, "candidate": candidate,
                                "worker_receipt_artifact": receipt_artifact, "result": summary,
                                "lease_renewal_count": item["renewal_count"]}
                    if owned and after_terminal is not None and not operation_journal.pending():
                        if owned_supervisor is not None:
                            owned_supervisor.stop(spec)
                        # The callback may replay registry-bound completion on
                        # this owner thread. Give every other active lease a
                        # fresh interval; Python/I/O liveness stays cooperative.
                        renew_active(force=True, exclude_run_id=spec.run_id)
                        if operation_journal.pending():
                            raise TrainingCoordinationError("pending mutation blocks terminal qualification")
                        poll_owned()
                        after_terminal(spec, _read_json(_bytes(terminal)))
                        poll_owned()
                    completed.append(terminal)
                except Exception as exc:
                    record_failure(item, exc)
                finally:
                    # A failed Future holds its traceback and replay state graph.
                    # Drop it before waiting for the next training result.
                    preparation = None
                    active.pop(future)
    finally:
        # Drain filesystem work before the caller can close the registry.
        try:
            if preparation_pool is not None:
                preparation_pool.shutdown(wait=True, cancel_futures=True)
        finally:
            if native_pool is not None:
                # The enclosing qualified cycle owns shutdown, including failures.
                pass
            elif owned_supervisor is not None:
                executor.close()
            else:
                executor.shutdown(wait=True, cancel_futures=True)
    report = {"schema_version": "autoencoder-training-coordinator-receipt-v1",
            "admitted": False, "promotion_performed": False,
            "execution_mode": "native_training" if native else "injected_test",
            "defer_target_hydration_gc": defer_target_hydration_gc,
            "reduce_native_targets": reduce_native_targets,
            "native_pool": native_pool.observation() if native_pool is not None else {"enabled": False},
            "max_workers": max_workers, "run_count": len(spec_list),
            "lease_seconds": lease_seconds, "elapsed_seconds": time.perf_counter() - started,
            "mutation_retry_count": mutation_retries, "resolved_operation_count": resolved_operations,
            "completed": completed, "failed": failed}
    if owned:
        report.update(operation_journal_used=True, journal_capacity=journal_capacity,
                      mutation_retry_count=None, resolved_operation_count=None,
                      recovery_required=needs_recovery,
                      undispatched_run_ids=[spec.run_id for spec in spec_list[next_index:]])
    return report


__all__ = ["SparseCheckpointPolicy", "TrainingCoordinationError", "registered_checkpoint_inputs", "run_training_jobs"]
