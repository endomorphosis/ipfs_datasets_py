"""Explicit already-trained source successors and fresh private scan roots.

Training is a separate caller action. This coordinator selects only a direct
registered child whose captured head follows its parent's head through a
freshly received complete source delta. It never fits, runs a forward pass,
promotes a registry head, or reuses an earlier scan's numerical rows. Each
receiving call repeats native history, checkpoint, source and registry checks.
The checks are sequential observations, not an atomic checkout/model snapshot
or process-origin attestation. Serialized byte ceilings do not bound RSS.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from . import codebase_inventory_receiving as receiving
from . import codebase_inventory_projection_replay as projection
from . import codebase_inventory_resume as scan
from . import codebase_inventory_successor as delta
from . import codebase_source_training as training
from .cache import ImmutableCAS
from .content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured

SCHEMA = "codebase-inventory-successor-scan@1"
MAX_RECORD_BYTES = 256 * 1024
_FIELDS = {"schema", "source_delta_cid", "previous_head", "current_head",
    "previous_membership_cid", "current_membership_cid", "previous_training_record_cid",
    "training_record_cid", "previous_model", "model", "root_cid", "scan_limits",
    "optimized", "implementation", "authority", "training_performed_here",
    "inference_performed_here", "numerical_reuse", "model_head_promoted"}
_FALSE = ("training_performed_here", "inference_performed_here", "numerical_reuse", "model_head_promoted")


class CodebaseSuccessorScanError(ValueError):
    """A current source transition, direct child or private scan root differs."""


def _require(value, message):
    if not value:
        raise CodebaseSuccessorScanError(message)


def _shape(value):
    scan._closed(value, _FIELDS, "successor scan selection")
    _require(value["schema"] == SCHEMA and type(value["optimized"]) is bool,
             "closed successor scan profile required")
    _require(all(value[name] is False for name in _FALSE), "selection cannot perform numerical work or promotion")
    scan._authority(value["authority"])
    previous, current = scan._head(value["previous_head"]), scan._head(value["current_head"])
    _require(previous.repository_id == current.repository_id and current.generation == previous.generation + 1,
             "immediate source successor required")
    for name in ("source_delta_cid", "previous_membership_cid", "current_membership_cid",
                 "previous_training_record_cid", "training_record_cid", "root_cid"):
        scan._cid(value[name])
    for name in ("previous_model", "model"):
        scan._model_shape(value[name])
    parent, child = value["previous_model"], value["model"]
    _require(parent["version_id"] != child["version_id"] and len(child["ancestry"]) >= 2
             and child["ancestry"][1:] == parent["ancestry"], "exact direct child ancestry required")
    for name in ("variant_id", "contract_sha256", "feature_space_sha256", "latent_width", "feature_columns",
                 "projection_ids", "projection_widths"):
        _require(scan._wire(parent[name]) == scan._wire(child[name]), "frozen numerical basis differs")
    scan.CodebaseScanResumeLimits.from_dict(value["scan_limits"])
    scan._implementation_shape(value["implementation"])


@dataclass(frozen=True, slots=True)
class CodebaseSuccessorScanRecord:
    artifact_cid: str
    _payload: bytes

    def __post_init__(self):
        scan._cid(self.artifact_cid)
        _require(type(self._payload) is bytes and len(self._payload) <= MAX_RECORD_BYTES,
                 "bounded immutable successor scan record required")
        value = json.loads(self._payload)
        _require(canonical_dag_json_bytes(value) == self._payload and cid_for_structured(value) == self.artifact_cid,
                 "canonical successor scan CID/bytes differ")
        _shape(value)

    def to_dict(self):
        return json.loads(self._payload)

    @classmethod
    def from_dict(cls, artifact_cid, value):
        return cls(artifact_cid, canonical_dag_json_bytes(value))


def load_codebase_successor_scan(artifacts, artifact_cid):
    """Load historical inert bytes; this does not assert currentness."""
    _require(type(artifacts) is ImmutableCAS, "exact immutable source artifact owner required")
    scan._cid(artifact_cid)
    scan._artifact_size(artifacts, artifact_cid, MAX_RECORD_BYTES)
    return CodebaseSuccessorScanRecord.from_dict(artifact_cid, artifacts.get(artifact_cid))


def _implementation():
    files = dict(delta._implementation()["files"])
    files[__name__] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {"files": files, "sha256": scan.features.digest(files),
            "scope": "listed_local_files_only_not_execution_attestation"}


def _record_guard(record, maximum):
    scan._cid(record.artifact_cid)
    return receiving._record_guard(record, maximum)


def _published_training_record(index, item, remaining):
    """Match the unchanged producer's published record from native replay.

    The chain has already undergone the complete native lineage algorithm.
    Reconstructing its exact historical record avoids replaying that ancestry
    twice more. No record constructor or caller metadata replaces the replay.
    """
    row, saved, provenance = item[:3]
    raw = training._wire(saved)
    value = {"schema": training.SCHEMA, "version_id": row["version_id"], "variant_id": row["variant_id"],
        "parent_version_id": row["parent_version_id"], "head": provenance["head"],
        "registry_artifact": row["artifact"], "checkpoint_raw_cid": cid_for_bytes(raw),
        "contract_sha256": saved["state"]["contract_sha256"], "state_sha256": scan.features.digest(saved["state"]),
        "feature_space_sha256": scan.features.digest(saved["feature_space"]),
        "report_json": training._wire(saved["report"]).decode("utf-8"), "authority": dict(training._FALSE),
        "source_model_generation": "historical_recorded_source_and_private_model_candidate",
        "training_performed_during_load": False, "model_head_selected": False}
    remaining()
    encoded = canonical_dag_json_bytes(value)
    record = training.CodebaseFeatureTrainingRecord(cid_for_structured(value), encoded, False)
    scan._artifact_size(index.artifacts, record.artifact_cid, 2 * training.CodebaseFeatureTrainingLimits().max_candidate_bytes)
    _require(canonical_dag_json_bytes(index.artifacts.get(record.artifact_cid)) == record._payload,
             "published source training record bytes differ")
    remaining()
    return record.artifact_cid


def _native_models(index, registry, source_delta, previous_version_id, version_id, optimized, remaining):
    value = source_delta.to_dict()
    chain = scan._resume_lineage(index, registry, version_id, training.CodebaseFeatureTrainingLimits(),
                                  remaining, optimized=optimized)
    _require(len(chain) >= 2 and chain[0][0]["parent_version_id"] == previous_version_id
             and chain[1][0]["version_id"] == previous_version_id, "selected version must be an exact registered direct child")
    _require(scan._wire(chain[0][2]["head"]) == scan._wire(value["current_head"])
             and scan._wire(chain[1][2]["head"]) == scan._wire(value["previous_head"]),
             "parent/child model belongs to another complete source head")
    guard = receiving._chain_guard(chain, remaining)
    previous_cid = _published_training_record(index, chain[1], remaining)
    current_cid = _published_training_record(index, chain[0], remaining)
    result = {"previous_training_record_cid": previous_cid, "training_record_cid": current_cid,
              "previous_model": scan._model(chain[1:]), "model": scan._model(chain)}
    _require(receiving._chain_guard(chain, remaining) == guard, "native lineage snapshot changed during record replay")
    return result, chain


def _root_binding(root, source_delta, models, limits, optimized):
    r, d = root.to_dict(), source_delta.to_dict()
    members = [row["current"]["member"] for row in d["ledger"] if row["current"] is not None]
    _require(scan._wire(r["head"]) == scan._wire(d["current_head"])
             and r["membership_cid"] == d["current_membership_cid"]
             and scan._wire(r["members"]) == scan._wire(members)
             and scan._wire(r["model"]) == scan._wire(models["model"])
             and scan._wire(r["limits"]) == scan._wire(limits.to_dict())
             and r["optimized"] is optimized and r["implementation"] == scan._implementation(),
             "fresh scan root source/model/membership/profile differs")


def _value(source_delta, models, root, optimized, implementation):
    d, r = source_delta.to_dict(), root.to_dict()
    return {"schema": SCHEMA, "source_delta_cid": source_delta.artifact_cid,
        "previous_head": d["previous_head"], "current_head": d["current_head"],
        "previous_membership_cid": d["previous_membership_cid"], "current_membership_cid": d["current_membership_cid"],
        **models, "root_cid": root.artifact_cid, "scan_limits": r["limits"], "optimized": optimized,
        "implementation": implementation, "authority": dict(scan._FALSE), **{name: False for name in _FALSE}}


def _source_exit(index, repository, manifest, source_delta, remaining, optimized):
    """Final native SQL and checkout observations, without a CAS callback.

    The freshly loaded manifest and its CAS/source/AST closure were validated
    before the last model fence. SQL rows are replayed again independently;
    snapshot_repository reads live source bytes without the artifact owner.
    This ordering closes mutations during earlier CAS/model callbacks while
    retaining the ordinary sequential, non-atomic observation boundary.
    """
    d = source_delta.to_dict()
    head = scan._head(d["current_head"])
    _require(manifest.cid == head.manifest_cid and manifest.snapshot.snapshot_cid == head.snapshot_cid,
             "closing source manifest changed")
    if optimized:
        projection.replay_current_inventory_projections(index, manifest, expected_head=head, checkpoint=remaining)
    else:
        for entry in manifest.snapshot.entries:
            remaining()
            index.lookup(manifest, entry.path)
    for name, head_value in (("previous_publication_receipt", d["previous_head"]),
                             ("current_publication_receipt", d["current_head"])):
        _require(scan._wire(scan._receipt(index, scan._head(head_value), remaining).to_dict()) == scan._wire(d[name]),
                 "closing native publication receipt changed")
    remaining()
    captured = manifest.snapshot
    observed = scan.snapshot_repository(repository, repository_id=head.repository_id, max_entries=captured.max_entries,
        max_file_bytes=captured.max_file_bytes, exclusions=captured.exclusions)
    _require(observed.snapshot_cid == head.snapshot_cid and index.current(head.repository_id) == head,
             "closing current source or catalog head changed")
    _require(manifest.cid == head.manifest_cid and manifest.snapshot.snapshot_cid == head.snapshot_cid,
             "closing source manifest changed during native replay")
    remaining()


def _close(record, index, repository, registry, source_delta, root, chain, before, owners, remaining, memory_mb):
    value = record.to_dict()
    guard = receiving._chain_guard(chain, remaining)
    records = (_record_guard(record, MAX_RECORD_BYTES), _record_guard(root, 4 * scan._MIB),
               _record_guard(source_delta, 8 * scan._MIB))
    _require(load_codebase_successor_scan(index.artifacts, record.artifact_cid)._payload == record._payload,
             "durable successor selection bytes differ")
    _require(scan.load_codebase_scan_resume_root(index.artifacts, root.artifact_cid)._payload == root._payload,
             "durable successor root bytes differ")
    # Native source/CAS/history/model/registry closure remains unchanged.
    scan._close(index, repository, root, registry, chain, before, remaining, memory_mb)
    models = {"previous_training_record_cid": _published_training_record(index, chain[1], remaining),
        "training_record_cid": _published_training_record(index, chain[0], remaining),
        "previous_model": scan._model(chain[1:]), "model": scan._model(chain)}
    _root_binding(root, source_delta, models, scan.CodebaseScanResumeLimits.from_dict(value["scan_limits"]), value["optimized"])
    _require(canonical_dag_json_bytes(_value(source_delta, models, root, value["optimized"], _implementation())) == record._payload,
             "closing successor selection identity or implementation differs")
    _require(load_codebase_successor_scan(index.artifacts, record.artifact_cid)._payload == record._payload,
             "closing successor selection bytes differ")
    # All source/AST/root/target/CAS callbacks precede the final native model
    # and registry fences. Final native SQL and live checkout observations
    # use the independently verified local manifest without more CAS callbacks.
    _require(delta.load_codebase_source_delta(index.artifacts, source_delta.artifact_cid)._payload == source_delta._payload,
             "closing source delta bytes differ")
    d = source_delta.to_dict()
    closing = delta._observe(index, repository, scan._head(d["previous_head"]), scan._head(d["current_head"]),
        delta.CodebaseSourceDeltaLimits.from_dict(d["limits"]), remaining, memory_mb, d["optimized"], delta._implementation())
    _require(canonical_dag_json_bytes(closing) == source_delta._payload, "closing native source successor differs")
    manifest = index.load(scan._head(d["current_head"]).manifest_cid)
    scan.legacy._model_fence(registry, chain, remaining)
    _require(scan.legacy._registry_inventory(registry, scan.legacy.CodebaseInventoryScanLimits(), remaining) == before,
             "closing successor registry namespace changed")
    _require(value["implementation"] == _implementation(), "closing successor producer changed")
    _require(receiving._chain_guard(chain, remaining) == guard, "closing native lineage snapshot changed")
    _source_exit(index, repository, manifest, source_delta, remaining, value["optimized"])
    _require(receiving._owner_guard(index, registry, repository) == owners, "successor native owners changed")
    scan._owners(index, registry)
    remaining()
    _require(records == (_record_guard(record, MAX_RECORD_BYTES), _record_guard(root, 4 * scan._MIB),
                         _record_guard(source_delta, 8 * scan._MIB)), "closing immutable successor records changed")


def start_current_codebase_successor_scan(index, repository, *, source_delta, registry, previous_version_id,
        version_id, limits=None, optimized=True, scheduler=None, parent_lease=None, cancel_event=None,
        admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    """Select an already-trained direct child and persist a fresh ordinary root.

    Explicit training with train_current_codebase_features happens beforehand.
    Changed evaluation/cohort/basis requires a separately declared fresh model
    lineage; this entrypoint never chooses or fits such a fallback.
    """
    _require(type(source_delta) is delta.CodebaseSourceDeltaRecord and type(optimized) is bool,
             "exact source delta and inference optimization opt-out required")
    training._text(previous_version_id, "previous_version_id")
    training._text(version_id, "version_id")
    limits = scan.CodebaseScanResumeLimits() if limits is None else limits
    _require(type(limits) is scan.CodebaseScanResumeLimits, "exact ordinary resume limits required")
    source_guard = _record_guard(source_delta, 8 * scan._MIB)
    limits_guard = scan._wire(limits.to_dict())
    # Existing native phase ceilings plus a retained <=8MiB delta, <=16MiB
    # root and <=256KiB selection fit within 256MiB serialized admission.
    # This is an accounting ceiling, not an RSS or execution attestation.
    _require(type(memory_mb) is int and 256 * scan._MIB <= memory_mb * scan._MIB // 4,
             "successor serialized retention exceeds memory reservation")
    with scan._scope(index, registry, scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds,
            memory_mb=memory_mb) as (lease, signal, remaining):
        owners = receiving._owner_guard(index, registry, repository)
        before = scan.legacy._registry_inventory(registry, scan.legacy.CodebaseInventoryScanLimits(), remaining)
        implementation = _implementation()
        delta._receive(source_delta, index, repository, remaining, memory_mb)
        models, chain = _native_models(index, registry, source_delta, previous_version_id, version_id, optimized, remaining)
        del chain
        root = scan.start_current_codebase_scan(index, repository, expected_head=scan._head(source_delta.to_dict()["current_head"]),
            registry=registry, version_id=version_id, limits=limits, optimized=optimized, parent_lease=lease,
            cancel_event=signal, admission_timeout_seconds=min(admission_timeout_seconds, remaining()),
            timeout_seconds=remaining(), memory_mb=memory_mb)
        _root_binding(root, source_delta, models, limits, optimized)
        value = _value(source_delta, models, root, optimized, implementation)
        record = CodebaseSuccessorScanRecord.from_dict(cid_for_structured(value), value)
        record_guard = _record_guard(record, MAX_RECORD_BYTES)
        remaining()
        _require(index.artifacts.put(value) == record.artifact_cid, "durable successor selection publication differs")
        _receive(record, index, repository, registry, before, owners, remaining, memory_mb)
    _require(_record_guard(record, MAX_RECORD_BYTES) == record_guard, "immutable successor record changed during resource closure")
    _require(_record_guard(source_delta, 8 * scan._MIB) == source_guard
             and scan._wire(limits.to_dict()) == limits_guard, "immutable source delta or scan limits changed")
    return record


def _receive(record, index, repository, registry, before, owners, remaining, memory_mb):
    record_guard = _record_guard(record, MAX_RECORD_BYTES)
    _require(load_codebase_successor_scan(index.artifacts, record.artifact_cid)._payload == record._payload,
             "durable successor selection bytes differ")
    value = record.to_dict()
    _require(value["implementation"] == _implementation(), "successor coordinator implementation changed")
    source_delta = delta.load_codebase_source_delta(index.artifacts, value["source_delta_cid"])
    delta._receive(source_delta, index, repository, remaining, memory_mb)
    models, chain = _native_models(index, registry, source_delta, value["previous_model"]["version_id"],
        value["model"]["version_id"], value["optimized"], remaining)
    root = scan.load_codebase_scan_resume_root(index.artifacts, value["root_cid"])
    _root_binding(root, source_delta, models, scan.CodebaseScanResumeLimits.from_dict(value["scan_limits"]), value["optimized"])
    _require(canonical_dag_json_bytes(_value(source_delta, models, root, value["optimized"], _implementation())) == record._payload,
             "fresh native successor selection differs")
    _close(record, index, repository, registry, source_delta, root, chain, before, owners, remaining, memory_mb)
    _require(_record_guard(record, MAX_RECORD_BYTES) == record_guard, "immutable successor record changed during receiving")
    return record


def validate_current_codebase_successor_scan(record, index, repository, *, registry, scheduler=None,
        parent_lease=None, cancel_event=None, admission_timeout_seconds=30.0, timeout_seconds=120.0, memory_mb=1024):
    """Receive exact historical bytes with fresh native current observations.

    This creates no root, runs no inference/training and exports no reusable
    currentness capability. Every later use requires another receiving call.
    """
    _require(type(record) is CodebaseSuccessorScanRecord, "exact immutable successor scan record required")
    record_guard = _record_guard(record, MAX_RECORD_BYTES)
    _require(type(memory_mb) is int and 256 * scan._MIB <= memory_mb * scan._MIB // 4,
             "successor serialized retention exceeds memory reservation")
    with scan._scope(index, registry, scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, timeout_seconds=timeout_seconds,
            memory_mb=memory_mb) as (_, _, remaining):
        owners = receiving._owner_guard(index, registry, repository)
        before = scan.legacy._registry_inventory(registry, scan.legacy.CodebaseInventoryScanLimits(), remaining)
        _receive(record, index, repository, registry, before, owners, remaining, memory_mb)
    _require(_record_guard(record, MAX_RECORD_BYTES) == record_guard, "immutable successor record changed during resource closure")
    return record


__all__ = ["CodebaseSuccessorScanError", "CodebaseSuccessorScanRecord", "start_current_codebase_successor_scan",
           "load_codebase_successor_scan", "validate_current_codebase_successor_scan"]
