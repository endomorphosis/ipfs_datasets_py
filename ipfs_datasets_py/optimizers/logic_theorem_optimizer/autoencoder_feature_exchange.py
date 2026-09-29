"""Explicitly unqualified feature artifacts in the authorized campaign dataset.

Transfers are immutable and commit pinned. Sparse postimages retain their exact
parent/job bindings and are replayed before use. This module never advances a
head, registers an inference model, executes a remote command or grants legal
qualification. Callers own resource admission and publication retry policy.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Mapping

from ...huggingface import autoencoder_incremental as transport
from ...huggingface import autoencoder_incremental_download as download
from ...huggingface.publisher import _reject_secrets
from . import modal_autoencoder_sparse_checkpoint as sparse
from . import autoencoder_feature_training as feature
from .autoencoder_training_worker import TrainingJobSpec

SCHEMA = "autoencoder-feature-update/v1"
REPORT_SCHEMA = "autoencoder-feature-attempt/v1"
PREFIX = "autoformal/uscode/feature-pretraining"
REPOSITORY = transport.REPOSITORY
MAX_BYTES = 128 * 1024 * 1024
MAX_CONTROL_BYTES = 16 * 1024 * 1024
MAX_FILES = 128
MAX_DEPTH = 7
_FALSE = {"qualified": False, "admitted": False, "formalized": False, "promotion_performed": False}
_KINDS = {"checkpoint", "patch", "worker", "evidence"}


class FeatureExchangeError(ValueError):
    """Feature transport metadata, parent identity or exact replay is invalid."""


def _require(condition, message):
    if not condition:
        raise FeatureExchangeError(message)


def _json(value):
    raw = transport._json(value)
    _require(len(raw) <= MAX_CONTROL_BYTES, "feature control byte limit exceeded")
    return raw


def _ref(value):
    return sparse.artifact_ref(value)


def _path(ref, kind):
    _require(kind in _KINDS, "unknown feature artifact role")
    return f"{PREFIX}/artifacts/{ref['sha256']}.{kind}.json"


def _false(value):
    _require(all(value.get(key) is expected for key, expected in _FALSE.items()),
             "feature transport cannot claim qualification, admission or promotion")


def validate_feature_reference(reference, expected_artifact=None, *, _depth=0, _seen=()):
    """Validate the entire closed portable reference before any network access."""
    _require(isinstance(reference, Mapping), "portable feature reference required")
    download._binding(reference.get("repository_id"), reference.get("commit_sha"))
    ref = _ref(reference)
    kind = reference.get("kind", "anchor")
    if kind == "anchor":
        _require(set(reference) <= {"kind", "repository_id", "commit_sha", "path_in_repo", "sha256", "bytes", "materialized_checkpoint"},
                 "unknown full parent reference fields")
        download._reference_plan(reference, expected_artifact=expected_artifact)
        return _depth
    _require(kind == "feature_sparse" and set(reference) == {"kind", "repository_id", "commit_sha", "path_in_repo",
        "sha256", "bytes", "materialized_checkpoint", "anchor_reference"}, "closed feature_sparse reference required")
    _require(_depth < MAX_DEPTH and ref["sha256"] not in _seen, "feature reference depth/cycle limit exceeded")
    _require(ref["bytes"] <= MAX_CONTROL_BYTES and reference["path_in_repo"] == f"{PREFIX}/updates/{ref['sha256']}.json",
             "feature update path is not bounded and content addressed")
    materialized = _ref(reference["materialized_checkpoint"])
    _require(materialized["bytes"] <= download.MAX_ANCHOR_BYTES
             and (expected_artifact is None or materialized == _ref(expected_artifact)), "feature materialized parent identity differs")
    return validate_feature_reference(reference["anchor_reference"], _depth=_depth + 1, _seen=(*_seen, ref["sha256"]))


class _EvidenceFiles:
    def __init__(self, paths):
        self.paths = paths

    def artifact_path(self, reference):
        return self.paths[_ref(reference)["sha256"]]

    def verify_artifact(self, reference):
        transport._read(self.artifact_path(reference), MAX_CONTROL_BYTES, reference)
        return _ref(reference)


class _InlineWorker:
    """Read-only receipt adapter; canonical bytes must match the owner CAS hash."""
    def __init__(self, worker):
        self.raw = _json(worker)

    def verify_artifact(self, reference):
        _require(_ref(reference) == transport._ref(self.raw), "inline worker differs from its owner receipt hash")
        return _ref(reference)

    def artifact_path(self, reference):
        self.verify_artifact(reference)
        return self

    def read_bytes(self):
        return self.raw


def _check_evidence(worker, envelope, paths):
    _require(worker.get("execution_mode") == "native_training" and worker.get("execution_gate_applied") is True
             and worker.get("source_manifest_verified") is True, "native source-verified feature worker evidence required")
    spec = TrainingJobSpec.from_dict(worker["job_spec"])
    actual = feature._feature_evidence(_EvidenceFiles(paths), spec, envelope["completion"])
    _require(_json(actual) == _json(envelope["feature_evidence"]), "feature evidence differs from bound worker completion")
    _false(actual)
    return spec, actual


def stage_feature_update(registry, version_id, evidence, destination, *, parent_reference):
    """Read one owner-verified completion and stage only sparse/evidence bytes.

    A compacted registry candidate is supported: its retained original sparse
    worker manifest is exported, with a transport parent bound to the exact
    materialized full generation. No full checkpoint is uploaded by this path.
    """
    root = Path(destination).absolute()
    worker_ref = _ref(evidence["worker_receipt_artifact"])
    worker_raw = transport._read(Path(registry.artifact_path(worker_ref)), MAX_CONTROL_BYTES, worker_ref)
    worker = transport._object(worker_raw)
    spec = TrainingJobSpec.from_dict(worker["job_spec"])
    run = registry.get_run(spec.run_id)
    _require(run["status"] == "completed" and evidence["candidate_version_id"] == version_id,
             "feature exchange requires the exact completed owner candidate")
    completion = {**evidence, "result": run["result"]}
    actual = feature._feature_evidence(registry, spec, completion)
    _require(actual["optimizer_accepted_epochs"] > 0, "feature update requires an accepted optimizer epoch; publish a no-update report otherwise")
    # Caller evidence may have its own CAS reference appended by the runner.
    _require(all(evidence.get(key) == value for key, value in actual.items()), "supplied feature evidence differs from owner replay")
    envelope = {"completion": completion, "feature_evidence": actual}
    _check_evidence(worker, envelope, {worker_ref["sha256"]: Path(registry.artifact_path(worker_ref))})
    resolver = registry.artifact_path
    parent = sparse.resolve_checkpoint(spec.base_checkpoint, resolver=resolver)
    validate_feature_reference(parent_reference, expected_artifact=parent.materialized_checkpoint)
    _require(validate_feature_reference(parent_reference) < MAX_DEPTH, "compact a full feature generation before the reference depth limit")
    candidate_ref = _ref(run["result"]["worker_candidate_artifact"])
    candidate_raw = transport._read(Path(resolver(candidate_ref)), 1024 * 1024, candidate_ref)
    candidate = sparse.decode_manifest(candidate_raw)
    resolved = sparse.resolve_checkpoint(candidate_ref, resolver=resolver, reset_revision=False)
    version = registry.get_version(version_id)
    registered = sparse.resolve_checkpoint(version["artifact"], resolver=resolver)
    _require(candidate["parent"] == _ref(spec.base_checkpoint) and candidate["base_version_id"] == spec.base_version_id
        and candidate["provenance"] == {"job_id": spec.job_id, "run_id": spec.run_id, "job_spec_sha256": spec.canonical_sha256}
        and resolved.materialized_checkpoint == registered.materialized_checkpoint == worker["candidate_materialized_checkpoint"]
        and registered.state_identity == resolved.state_identity,
        "feature candidate/registry/worker parent or replay identity differs")
    rebased = sparse.encode_manifest(parent=parent.materialized_checkpoint, base_version_id=spec.base_version_id,
        patches=candidate["patches"], materialized_checkpoint=resolved.materialized_checkpoint,
        state_identity=resolved.state_identity, result_revision=resolved.replayed_revision, provenance=candidate["provenance"])
    snapshots = [(transport._ref(rebased), rebased, "checkpoint"), (worker_ref, worker_raw, "worker")]
    envelope_raw = _json(envelope)
    snapshots.append((transport._ref(envelope_raw), envelope_raw, "evidence"))
    for ref in candidate["patches"]:
        snapshots.append((ref, transport._read(Path(resolver(ref)), MAX_BYTES, ref), "patch"))
    _require(len(snapshots) <= MAX_FILES and sum(len(raw) for _, raw, _ in snapshots) <= MAX_BYTES, "feature upload bound exceeded")
    files = []
    for ref, raw, kind in snapshots:
        name = f"{ref['sha256']}.{kind}.json"
        transport._write(root / name, raw)
        files.append({**ref, "kind": kind, "filename": name, "path_in_repo": _path(ref, kind)})
    manifest = {"schema": SCHEMA, "training_purpose": "feature_pretraining", "repository_id": REPOSITORY,
        "base_version_id": spec.base_version_id, "candidate_version_id": version_id,
        "parent_checkpoint": dict(parent.materialized_checkpoint), "anchor_reference": dict(parent_reference),
        "checkpoint_artifact": transport._ref(rebased), "materialized_checkpoint": dict(resolved.materialized_checkpoint),
        "state_identity": resolved.state_identity, "files": files, "owner_replay_verified": True, **_FALSE}
    raw = _json(manifest); ref = transport._ref(raw)
    path = root / (ref["sha256"] + ".update.json")
    transport._write(path, raw)
    load_feature_update(path)
    return {"manifest_path": str(path), "manifest_artifact": ref,
        "path_in_repo": f"{PREFIX}/updates/{ref['sha256']}.json", "materialized_checkpoint": manifest["materialized_checkpoint"], **_FALSE}


def _manifest(value):
    _require(set(value) == {"schema", "training_purpose", "repository_id", "base_version_id", "candidate_version_id",
        "parent_checkpoint", "anchor_reference", "checkpoint_artifact", "materialized_checkpoint", "state_identity",
        "files", "owner_replay_verified", *_FALSE}, "feature manifest fields differ")
    _require(value["schema"] == SCHEMA and value["training_purpose"] == "feature_pretraining"
             and value["repository_id"] == REPOSITORY and value["owner_replay_verified"] is True, "wrong feature transport purpose")
    _false(value)
    validate_feature_reference(value["anchor_reference"], expected_artifact=value["parent_checkpoint"])
    _require(validate_feature_reference(value["anchor_reference"]) < MAX_DEPTH, "feature reference depth exceeded")
    files = value["files"]
    _require(type(files) is list and 3 <= len(files) <= MAX_FILES, "feature file count exceeds bound")
    roles, seen = {}, set()
    for item in files:
        ref = _ref(item); kind = item.get("kind")
        _require(set(item) == {"sha256", "bytes", "kind", "filename", "path_in_repo"}
            and item["path_in_repo"] == _path(ref, kind) and item["filename"] == f"{ref['sha256']}.{kind}.json"
            and ref["sha256"] not in seen, "unbound or duplicate feature blob")
        seen.add(ref["sha256"]); roles.setdefault(kind, []).append(ref)
    _require(sum(item["bytes"] for item in files) <= MAX_BYTES and all(len(roles.get(kind, [])) == 1
        for kind in ("checkpoint", "worker", "evidence")), "feature file roles or total bytes differ")
    _require(roles["checkpoint"][0] == _ref(value["checkpoint_artifact"]), "unbound sparse checkpoint")
    _require(_ref(value["materialized_checkpoint"])["bytes"] <= download.MAX_ANCHOR_BYTES, "feature checkpoint exceeds bound")
    return roles


def load_feature_update(manifest_path):
    """Check transport bytes/evidence without resolving or downloading a parent."""
    path = Path(manifest_path).absolute()
    raw = transport._read(path, MAX_CONTROL_BYTES)
    value = transport._object(raw); roles = _manifest(value)
    _require(raw == _json(value), "feature manifest is not canonical")
    snapshots, local = {}, {}
    for item in value["files"]:
        bound = MAX_BYTES if item["kind"] == "patch" else MAX_CONTROL_BYTES
        content = transport._read(path.parent / item["filename"], bound, item)
        snapshots[item["path_in_repo"]] = content
        local[item["sha256"]] = path.parent / item["filename"]
    checkpoint = sparse.decode_manifest(transport._read(local[roles["checkpoint"][0]["sha256"]], 1024 * 1024))
    _require(checkpoint["parent"] == value["parent_checkpoint"] and checkpoint["base_version_id"] == value["base_version_id"]
        and checkpoint["materialized_checkpoint"] == value["materialized_checkpoint"] and checkpoint["state_identity"] == value["state_identity"]
        and sorted(checkpoint["patches"], key=lambda ref: ref["sha256"]) == sorted(roles.get("patch", []), key=lambda ref: ref["sha256"]),
        "feature sparse parent, result or patch closure differs")
    worker = transport._object(transport._read(local[roles["worker"][0]["sha256"]], MAX_CONTROL_BYTES))
    envelope = transport._object(transport._read(local[roles["evidence"][0]["sha256"]], MAX_CONTROL_BYTES))
    spec, evidence = _check_evidence(worker, envelope, local)
    _require(spec.base_version_id == value["base_version_id"] and evidence["candidate_version_id"] == value["candidate_version_id"]
        and worker["base_materialized_checkpoint"] == value["parent_checkpoint"]
        and worker["candidate_materialized_checkpoint"] == value["materialized_checkpoint"]
        and checkpoint["provenance"] == {"job_id": spec.job_id, "run_id": spec.run_id, "job_spec_sha256": spec.canonical_sha256},
        "feature worker/evidence/checkpoint binding differs")
    _reject_secrets(value, label="feature update metadata")
    _reject_secrets(worker, label="feature worker evidence")
    _reject_secrets(envelope, label="feature completion evidence")
    ref = transport._ref(raw); snapshots[f"{PREFIX}/updates/{ref['sha256']}.json"] = raw
    return {"manifest": value, "manifest_artifact": ref, "snapshots": snapshots, "paths": local}


def _publish(snapshots, *, upload, api):
    _require(type(upload) is bool and sum(map(len, snapshots.values())) <= MAX_BYTES + MAX_CONTROL_BYTES,
             "bounded explicit feature publication required")
    if not upload:
        return {"uploaded": False, "dry_run": True, **_FALSE}
    from huggingface_hub import HfApi, CommitOperationAdd
    api = api or HfApi()
    parent = str(api.repo_info(repo_id=REPOSITORY, repo_type="dataset").sha)
    download._binding(REPOSITORY, parent)
    def present(commit):
        found = set()
        for row in api.get_paths_info(REPOSITORY, list(snapshots), repo_type="dataset", revision=commit):
            path = str(getattr(row, "path", "") or getattr(row, "rfilename", ""))
            _require(path in snapshots and path not in found and transport._matches(row, snapshots[path]),
                     "immutable remote feature artifact conflicts")
            found.add(path)
        return found
    existing = present(parent)
    ops = [CommitOperationAdd(path_in_repo=path, path_or_fileobj=raw) for path, raw in snapshots.items() if path not in existing]
    commit = parent
    if ops:
        made = api.create_commit(repo_id=REPOSITORY, repo_type="dataset", operations=ops, parent_commit=parent,
            commit_message="Append unqualified feature-pretraining artifacts; no legal admission")
        commit = str(getattr(made, "oid", "") or (made.get("oid", "") if isinstance(made, Mapping) else ""))
    download._binding(REPOSITORY, commit)
    _require(present(commit) == set(snapshots), "feature publication is incomplete at pinned commit")
    return {"uploaded": True, "dry_run": False, "commit_sha": commit, "parent_commit": parent,
            "remote_already_present": not ops, **_FALSE}


def publish_feature_update(manifest_path, *, upload=False, api=None):
    bundle = load_feature_update(manifest_path); manifest = bundle["manifest"]
    result = _publish(bundle["snapshots"], upload=upload, api=api)
    reference = None
    if result["uploaded"]:
        reference = {"kind": "feature_sparse", "repository_id": REPOSITORY, "commit_sha": result["commit_sha"],
            "path_in_repo": f"{PREFIX}/updates/{bundle['manifest_artifact']['sha256']}.json", **bundle["manifest_artifact"],
            "materialized_checkpoint": manifest["materialized_checkpoint"], "anchor_reference": manifest["anchor_reference"]}
        validate_feature_reference(reference)
    return {**result, "training_purpose": "feature_pretraining", "weight_reference": reference,
            "manifest_artifact": bundle["manifest_artifact"], "full_checkpoint_uploaded": False}


def download_feature_update(reference, destination, *, local_parent_resolver=None, api=None, client=None):
    """Fetch only the selected bounded feature chain and verify exact full bytes."""
    validate_feature_reference(reference)
    _require(reference.get("kind") == "feature_sparse", "feature_sparse update reference required")
    root = Path(destination).absolute(); client = client or download.HubCampaignArtifactClient(api)
    telemetry = {"downloaded_bytes": 0, "downloaded_files": 0, "downloaded_weight_files": 0, "reused_files": 0}
    with download._owner(root):
        local_manifest = root / (reference["sha256"] + ".update.json")
        raw = download._cached_fetch(client, REPOSITORY, reference["commit_sha"], reference["path_in_repo"],
            local_manifest, MAX_CONTROL_BYTES, root, telemetry, ref=reference)
        value = transport._object(raw); _manifest(value)
        _require(value["anchor_reference"] == reference["anchor_reference"]
                 and value["materialized_checkpoint"] == reference["materialized_checkpoint"], "remote feature reference binding differs")
        for item in value["files"]:
            download._cached_fetch(client, REPOSITORY, reference["commit_sha"], item["path_in_repo"], root / item["filename"],
                min(item["bytes"], MAX_BYTES), root, telemetry, ref=item, weight=item["kind"] in {"patch", "checkpoint"})
        bundle = load_feature_update(local_manifest)
        local_parent = local_parent_resolver(value["parent_checkpoint"]) if local_parent_resolver is not None else None
        if local_parent is not None:
            parent_path = Path(local_parent)
            parent_result = {"downloaded_bytes": 0, "downloaded_weight_files": 0}
        elif value["anchor_reference"].get("kind", "anchor") == "anchor":
            parent_result = download.resolve_campaign_anchor(value["anchor_reference"], root / "parent",
                expected_artifact=value["parent_checkpoint"], api=api, client=client)
            parent_path = Path(parent_result["materialized_checkpoint_path"])
        else:
            parent_result = download_feature_update(value["anchor_reference"], root / "parent", api=api, client=client)
            parent_path = Path(parent_result["materialized_checkpoint_path"])
        # Existing checkpoint resolution checks exact parent bytes and every
        # ordered postimage, including result revision/state/materialized hash.
        parent = sparse.resolve_checkpoint(value["parent_checkpoint"], resolver=lambda ref: parent_path)
        _require(parent.manifest is None, "feature transport parent must materialize to a full checkpoint")
        paths = {**bundle["paths"], value["parent_checkpoint"]["sha256"]: parent_path}
        resolved = sparse.resolve_checkpoint(value["checkpoint_artifact"], resolver=lambda ref: paths[ref["sha256"]])
        _require(resolved.materialized_checkpoint == value["materialized_checkpoint"] and resolved.state_identity == value["state_identity"],
                 "feature replay result differs")
        output = root / (resolved.materialized_checkpoint["sha256"] + ".state.json")
        transport._write(output, sparse.canonical_checkpoint_bytes(resolved.state))
        transport._read(output, download.MAX_ANCHOR_BYTES, resolved.materialized_checkpoint)
        return {"training_purpose": "feature_pretraining", "materialized_checkpoint": dict(resolved.materialized_checkpoint),
            "materialized_checkpoint_artifact": dict(resolved.materialized_checkpoint), "materialized_checkpoint_path": str(output),
            "state_identity": resolved.state_identity, "replay_verified": True, "replayed": True,
            "hash_verified": True, "locally_qualified": False, "registration_performed": False,
            "weights_downloaded": telemetry["downloaded_weight_files"] > 0 or bool(parent_result.get("weights_downloaded"))
                or parent_result.get("downloaded_weight_files", 0) > 0,
            "parent_download": parent_result, **telemetry, **_FALSE}


def publish_feature_checkpoint(path, *, expected_artifact, generation, upload=False, api=None):
    """Publish one explicitly selected full common generation, never a best head."""
    _require(type(generation) is int and generation >= 1, "positive feature generation required")
    seed = download.publish_seed_checkpoint(path, expected_artifact=expected_artifact, upload=upload, api=api)
    metadata = {"schema": "autoencoder-feature-generation/v1", "training_purpose": "feature_pretraining",
        "generation": generation, "artifact": _ref(expected_artifact), "transport_baseline_only": True, **_FALSE}
    raw = _json(metadata); ref = transport._ref(raw)
    report = _publish({f"{PREFIX}/generations/{ref['sha256']}.json": raw}, upload=upload, api=api)
    return {**report, "anchor_reference": seed.get("anchor_reference"), "weight_reference": seed.get("anchor_reference"),
            "feature_generation_metadata": metadata, "full_checkpoint_uploaded": seed["uploaded"]}


def _report(report):
    _require(report.get("schema") == REPORT_SCHEMA and report.get("training_purpose") == "feature_pretraining",
             "explicit feature attempt schema/purpose required")
    _false(report)
    assignment = report["assignment_binding"]
    _require(isinstance(assignment, dict) and assignment.get("policy", {}).get("training_purpose") == "feature_pretraining",
             "exact feature campaign assignment binding required")
    _require(report.get("assignment_sha256") == transport._sha(sparse._json(assignment)), "feature assignment hash differs")
    _require(report.get("work_id") == assignment["run_id"] and report.get("span_revision") == assignment["record"]["record_id"],
             "feature assignment source identity differs")
    source = report["source_provenance"]
    _require(source["source_record"] == assignment["record"] and source["source_observation"] == assignment["source_observation"]
        and source["canonical_generation"] == assignment["generation"] and source["canonical_version_id"] == assignment["base_version_id"]
        and source["canonical_artifact"] == report["base_artifact"]
        and source["source_identity"] == assignment["policy"]["source_identity"]
        and source["feature_input_binding"] == assignment["policy"]["feature_input_binding"],
        "feature source/parent/policy provenance differs")
    worker = report["worker_receipt"]
    spec = TrainingJobSpec.from_dict(worker["job_spec"])
    _require(_json(report["training_config"]) == _json(spec.training_config.to_dict()) and report["autoencoder_config"] == dict(spec.autoencoder_config)
        and _json(report["training_samples"]) == _json([asdict(row) for row in spec.samples])
        and _json(report["validation_samples"]) == _json([asdict(row) for row in spec.validation_samples])
        and report["training_samples"] == [assignment["record"]["sample"]]
        and transport._sha(sparse._json(report["validation_samples"])) == assignment["policy"]["feature_input_binding"]["validation_samples_sha256"],
        "feature report job/sample binding differs")
    evidence = report["feature_evidence"]
    _false(evidence)
    accepted = evidence["optimizer_accepted_epochs"]
    _require(type(accepted) is int and accepted >= 0 and evidence["candidate_version_id"] == report["candidate_version_id"]
        and evidence["run_id"] == spec.run_id and evidence["base_version_id"] == spec.base_version_id
        and worker["job_spec_canonical_sha256"] == spec.canonical_sha256
        and worker["candidate_materialized_checkpoint"] == report["candidate_artifact"]
        and worker["base_materialized_checkpoint"] == report["base_artifact"]
        and worker.get("execution_mode") == "native_training" and worker.get("execution_gate_applied") is True
        and worker.get("source_manifest_verified") is True,
        "feature attempt worker/candidate/epoch binding differs")
    feature._validate_template(spec)
    actual = feature._feature_evidence(_InlineWorker(worker), spec, report["completion"])
    _require(all(evidence.get(key) == value for key, value in actual.items()),
             "feature attempt metrics differ from its complete worker evidence")
    reference = report.get("weight_publication")
    if accepted:
        _require(report["disposition"] == "feature_updated" and reference is not None, "accepted feature attempt requires its sparse publication")
        validate_feature_reference(reference, expected_artifact=report["candidate_artifact"])
        _require(reference.get("kind") == "feature_sparse", "feature update cannot masquerade as a qualified release")
        validate_feature_reference(reference["anchor_reference"], expected_artifact=report["base_artifact"])
    else:
        _require(report["disposition"] == "feature_no_update" and reference is None
            and evidence["next_base_version_id"] == spec.base_version_id, "rejected feature attempt must retain its parent")
    _reject_secrets(report, label="feature attempt report")
    return report


def publish_feature_report(report, destination, *, upload=False, api=None):
    report = transport._object(_json(report))
    report.setdefault("assignment_sha256", transport._sha(sparse._json(report["assignment_binding"])))
    _report(report); raw = _json(report); ref = transport._ref(raw)
    path = Path(destination).absolute() / (ref["sha256"] + ".report.json")
    transport._write(path, raw)
    remote = f"{PREFIX}/reports/{ref['sha256']}.json"
    result = _publish({remote: raw}, upload=upload, api=api)
    descriptor = ({"repository_id": REPOSITORY, "commit_sha": result["commit_sha"], "path_in_repo": remote, **ref}
                  if result["uploaded"] else None)
    return {**result, "report_reference": descriptor, "report_path": str(path), "report_artifact": ref}


def download_feature_report(reference, destination, *, api=None, client=None):
    _require(isinstance(reference, Mapping) and set(reference) == {"repository_id", "commit_sha", "path_in_repo", "sha256", "bytes"},
             "closed feature report reference required")
    download._binding(reference["repository_id"], reference["commit_sha"]); ref = _ref(reference)
    _require(ref["bytes"] <= MAX_CONTROL_BYTES and reference["path_in_repo"] == f"{PREFIX}/reports/{ref['sha256']}.json",
             "feature report must be bounded and content addressed")
    root = Path(destination).absolute(); client = client or download.HubCampaignArtifactClient(api)
    telemetry = {"downloaded_bytes": 0, "downloaded_files": 0, "downloaded_weight_files": 0, "reused_files": 0}
    with download._owner(root):
        path = root / (ref["sha256"] + ".report.json")
        raw = download._cached_fetch(client, REPOSITORY, reference["commit_sha"], reference["path_in_repo"], path,
            MAX_CONTROL_BYTES, root, telemetry, ref=ref)
        report = _report(transport._object(raw)); _require(raw == _json(report), "feature report is not canonical")
        return {"report": report, "report_path": str(path), "report_reference": dict(reference),
                "owner_replay_and_evaluation_required": True, "weights_downloaded": False, **telemetry, **_FALSE}
