"""Read-only owner capture for portable selected campaign evidence packages.

The package builder verifies the typed closure through an owner-restricted
resolver. Original job paths and run records remain historical data; neither
packaging nor restoration registers jobs, restores leases or publishes files.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .autoencoder_registry import AutoencoderRegistry, _artifact, _token
from .contracts import canonical_json_bytes
from ..huggingface.autoencoder_campaign_release import (
    CampaignPackageLimits,
    build_campaign_package,
    _hash_file as _hash_owner_artifact,
    _read_control as _read_owner_metadata,
)


class AutoencoderCampaignPublicationError(ValueError):
    """An owner capture or its immutable selected closure changed or is invalid."""


_JOB_SCHEMA = "autoencoder-training-job-v8"
_MAX_ROOT_BYTES = 64 * 1024 * 1024
_MAX_PLAN_BYTES = 4 * 1024 * 1024
_MAX_BATCHES = 128
_MAX_VERSIONS = 256
_SINGLE_JOB_ARTIFACTS = (
    "base_checkpoint", "corpus_manifest_artifact", "source_inventory_artifact",
    "source_partitions_artifact", "embedding_receipt_set_artifact",
    "produced_record_projection_artifact", "target_snapshot_artifact",
    "arrow_feature_weights_artifact",
)
_MULTIPLE_JOB_ARTIFACTS = (
    "base_checkpoint_dependencies", "corpus_source_artifacts", "embedding_receipt_artifacts",
)


def _require(value: bool, message: str) -> None:
    if not value:
        raise AutoencoderCampaignPublicationError(message)


def _copy(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


def _decode(raw: bytes) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate campaign capture JSON field")
            result[key] = value
        return result

    def nonfinite(value):
        raise AutoencoderCampaignPublicationError("nonfinite campaign capture JSON value")

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    _require(type(value) is dict, "campaign capture artifact must contain an object")
    return value


def _owner_job_paths(registry: AutoencoderRegistry, job: Mapping[str, Any]) -> None:
    """Check locators lexically, without opening selected leaves or sources."""
    _require(job.get("schema_version") == _JOB_SCHEMA, "campaign package requires v8 jobs")
    refs = []
    for name in _SINGLE_JOB_ARTIFACTS:
        value = job.get(name)
        if value is not None:
            refs.append(value)
    for name in _MULTIPLE_JOB_ARTIFACTS:
        values = job.get(name)
        _require(type(values) is list, "job artifact list is missing or invalid: " + name)
        refs.extend(values)
    for value in refs:
        _require(type(value) is dict and set(value) == {"path", "sha256", "bytes"},
                 "job artifact must have an exact owner locator and byte descriptor")
        descriptor = _artifact({key: value[key] for key in ("sha256", "bytes")})
        _require(type(value["path"]) is str
                 and value["path"] == str(registry.artifact_path(descriptor)),
                 "job artifact locator is outside the current owner CAS")


def build_registered_campaign_package(
    registry: AutoencoderRegistry, *, generation_artifact: Mapping[str, Any],
    plan_artifact: Mapping[str, Any], destination: str | Path,
    limits: CampaignPackageLimits = CampaignPackageLimits(),
) -> dict[str, Any]:
    """Package a queued page and its original template without owner mutations.

    Generated runs must be fresh and queued. The original template may retain
    another historical status; its full record is captured without following
    candidate/completion history. All registry records, root artifacts and
    descriptors resolved by typed verification are checked again before return.
    Checkpoint framing and lineage verification belong to the package walker;
    this adapter neither constructs weights nor performs semantic replay.
    """
    _require(type(registry) is AutoencoderRegistry, "campaign capture requires the actual registry owner")
    _require(type(limits) is CampaignPackageLimits, "campaign capture requires package limits")
    try:
        limits = CampaignPackageLimits(**asdict(limits))
    except (TypeError, ValueError) as exc:
        raise AutoencoderCampaignPublicationError("invalid campaign capture limits: " + str(exc)) from exc
    generation_ref, plan_ref = _artifact(generation_artifact), _artifact(plan_artifact)
    resolved: dict[str, dict[str, Any]] = {}
    resolved_bytes = 0

    def owner_hash(descriptor):
        registry._ensure_owner()
        _require(descriptor["bytes"] <= registry.max_artifact_bytes,
                 "owner artifact exceeds the configured registry byte bound")
        path = registry.artifact_path(descriptor)
        _hash_owner_artifact(path, descriptor)
        return path

    def resolve(reference):
        nonlocal resolved_bytes
        descriptor = _artifact(reference)
        previous = resolved.get(descriptor["sha256"])
        _require(previous is None or previous == descriptor, "same artifact digest has inconsistent sizes")
        _require(descriptor["bytes"] <= limits.max_blob_bytes, "owner artifact exceeds package blob bound")
        if previous is None:
            _require(len(resolved) < limits.max_blobs, "owner artifact count exceeds package bound")
            _require(resolved_bytes + descriptor["bytes"] <= limits.max_total_bytes,
                     "owner artifact closure exceeds package byte bound")
            resolved[descriptor["sha256"]] = descriptor
            resolved_bytes += descriptor["bytes"]
        return owner_hash(descriptor)

    def document(reference, *, maximum=_MAX_ROOT_BYTES):
        descriptor = _artifact(reference)
        _require(descriptor["bytes"] <= maximum, "campaign metadata exceeds existing root byte bound")
        path = resolve(descriptor)
        raw = _read_owner_metadata(path, min(maximum, limits.max_blob_bytes, descriptor["bytes"]))
        _require(len(raw) == descriptor["bytes"]
                 and hashlib.sha256(raw).hexdigest() == descriptor["sha256"],
                 "registered campaign metadata changed during capture")
        return _decode(raw)

    def capture():
        generation = document(generation_ref)
        plan = document(plan_ref, maximum=_MAX_PLAN_BYTES)
        _require(generation.get("schema_version") == "autoencoder-campaign-generation-v1"
                 and plan.get("schema_version") == "autoencoder-campaign-plan-v1",
                 "unsupported campaign generation or plan schema")
        _require(plan.get("parent_policy") == "common_fixed_parent",
                 "initial campaign packaging requires a common fixed parent")
        recipe = generation["recipe"]
        _require(type(recipe) is dict, "generation recipe is missing")
        _require(recipe["artifact_root"] == plan["artifact_root"] == str(registry.artifact_root),
                 "campaign recipe and plan must bind the current owner CAS root")
        template_id = _token(recipe["template_run_id"], "template_run_id")
        rows = generation["jobs"]
        _require(type(rows) is list and 0 < len(rows) <= _MAX_BATCHES,
                 "campaign page has an invalid bounded job count")
        job_refs = [(template_id, recipe["template_job_spec_artifact"], recipe["template_job_spec_sha256"])]
        generated_bytes = 0
        for row in rows:
            _require(type(row) is dict, "campaign job binding must be an object")
            descriptor = _artifact(row["job_spec_artifact"])
            generated_bytes += descriptor["bytes"]
            _require(generated_bytes <= _MAX_ROOT_BYTES, "generated job bytes exceed existing page aggregate bound")
            job_refs.append((_token(row["run_id"], "run_id"), descriptor, row["job_spec_sha256"]))
        _require(len({item[0] for item in job_refs}) == len(job_refs), "template and generated run IDs must be distinct")
        run_records = []
        variant_id = _token(recipe["variant_id"], "variant_id")
        base_version_id = _token(recipe["base_version_id"], "base_version_id")
        for ordinal, (run_id, reference, digest) in enumerate(job_refs):
            descriptor = _artifact(reference)
            run = _copy(registry.get_run(run_id))
            _require(run["variant_id"] == variant_id and run["base_version_id"] == base_version_id,
                     "campaign run belongs to a different variant or fixed parent")
            _require(run["spec"] == {"job_spec_sha256": digest, "job_spec_artifact": descriptor},
                     "campaign run differs from the exact immutable job binding")
            if ordinal:
                _require(run["status"] == "queued" and type(run["attempt"]) is int and run["attempt"] == 0
                         and type(run["fence"]) is int and run["fence"] == 0
                         and run["lease"] is None and run["result"] is None,
                         "generated campaign runs must be fresh queued records")
            job = document(descriptor)
            _require(job.get("run_id") == run_id and job.get("base_version_id") == base_version_id,
                     "campaign job identity differs from its registered run")
            _owner_job_paths(registry, job)
            run_records.append(run)
        _require([row["run_id"] for row in plan["batches"]] == [row["run_id"] for row in rows],
                 "plan run ordering differs from generation page")
        variant_record = _copy(registry.get_variant(variant_id))
        chain, seen = [], set()
        version_id = base_version_id
        while version_id is not None:
            _token(version_id, "version_id")
            _require(version_id not in seen, "registry version ancestry contains a cycle")
            _require(len(chain) < min(_MAX_VERSIONS, limits.max_blobs),
                     "registry version ancestry exceeds package bound")
            seen.add(version_id)
            version = _copy(registry.get_version(version_id))
            _require(version["variant_id"] == variant_id and version["version_id"] == version_id,
                     "registry version ancestry crosses variant or identity")
            chain.append(version)
            _require(len(canonical_json_bytes(chain)) <= limits.max_control_bytes,
                     "registry version records exceed package control bound")
            version_id = version["parent_version_id"]
        captured = {"variant_record": variant_record, "version_records": list(reversed(chain)),
                    "run_records": run_records}
        _require(len(canonical_json_bytes(captured)) <= limits.max_control_bytes,
                 "owner capture exceeds package control bound")
        return captured

    try:
        captured = capture()
        expected = canonical_json_bytes(captured)
        result = build_campaign_package(generation_ref, plan_ref, destination,
            **captured, artifact_resolver=resolve, limits=limits)
        _require(canonical_json_bytes(capture()) == expected,
                 "registry campaign bindings changed while packaging")
        for descriptor in tuple(resolved.values()):
            owner_hash(descriptor)
        return result
    except AutoencoderCampaignPublicationError:
        raise
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise AutoencoderCampaignPublicationError("cannot capture registered campaign package: " + str(exc)) from exc


__all__ = ["AutoencoderCampaignPublicationError", "build_registered_campaign_package"]
