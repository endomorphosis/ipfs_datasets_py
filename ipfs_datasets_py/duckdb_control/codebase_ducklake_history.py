"""Codebase metadata events through the existing native registry/lake delivery.

The source/semantic owners remain authoritative. The existing registry owns
only the delivery event, exact operation receipt and outbox lease/ack. Native
DuckLake stores historical metadata references, never source/model/proof heads.
This adapter adds no database, schema, or competing journal implementation.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .autoencoder_registry import AutoencoderRegistry, SCHEMA as REGISTRY_SCHEMA
from .autoencoder_ducklake import deliver_ducklake_history, _event_row, _require_commit
from .contracts import canonical_json_bytes, content_identity
from .intent_codebase_catalog import IntentCodebaseCatalog, RECORD_SCHEMA
from .codebase_catalog import CodebaseHead
from ..logic.software_contracts.content import validate_cid
from ..ducklake.autoencoder_history import IsolatedNativeDuckLakeHistory, build_history_batch

SCHEMA = "codebase-discovery-history-request@1"
COMMAND = "RegisterCodebaseDiscoveryHistoryV1"
EVENT_KIND = "codebase_discovery_recorded_v1"
MAX_REQUEST_BYTES = 16 * 1024
MAX_INSPECT = 10
_FIELDS = {"schema", "discovery_schema", "record_cid", "semantic_manifest_cid",
           "policy_receipt_cid", "source_head", "source_owner", "model_version_id",
           "corpus_version_id", "association_semantics", "authority"}
_AUTHORITY = dict(source_observed_live=False, proof_authority=False,
                  training_authority=False, inference_executed=False,
                  source_runtime_semantics_verified=False)


class CodebaseHistoryError(ValueError):
    """A native metadata/history binding is unavailable, changed or unbounded."""


def _require(condition, message):
    if not condition:
        raise CodebaseHistoryError(message)


def _copy(value):
    return json.loads(canonical_json_bytes(value))


def _request(value):
    _require(type(value) is dict and set(value) == _FIELDS and value["schema"] == SCHEMA
             and value["discovery_schema"] == RECORD_SCHEMA
             and value["authority"] == _AUTHORITY
             and value["association_semantics"] == "declared_context_not_training_or_inference_provenance",
             "closed historical metadata request required")
    _require(len(canonical_json_bytes(value)) <= MAX_REQUEST_BYTES, "history request exceeds byte bound")
    for field in ("record_cid", "semantic_manifest_cid", "policy_receipt_cid"):
        validate_cid(value[field], codecs={"dag-json"})
    CodebaseHead.from_dict(value["source_head"])
    owner = value["source_owner"]
    _require(type(owner) is dict and set(owner) == {"database_path", "artifact_root"}, "closed source owner roots required")
    for path in owner.values():
        _require(type(path) is str and len(path.encode()) <= 4096 and str(Path(path)) == path
                 and Path(path).is_absolute() and ".." not in Path(path).parts, "canonical source owner root required")
    for field in ("model_version_id", "corpus_version_id"):
        ref = value[field]
        _require(ref is None or (type(ref) is str and 0 < len(ref.encode()) <= 256), "bounded optional native version ID required")
    return _copy(value)


def prepare_codebase_history_request(discovery, record_cid):
    """Reconstruct existing immutable discovery before describing its history."""
    _require(type(discovery) is IntentCodebaseCatalog, "exact native discovery owner required")
    value = discovery.get(record_cid)
    return _request(dict(schema=SCHEMA, discovery_schema=value["schema"], record_cid=record_cid,
        semantic_manifest_cid=value["semantic_manifest_cid"], policy_receipt_cid=value["policy_receipt_cid"],
        source_head=value["source_head"],
        source_owner=dict(database_path=value["roots"]["source_database"], artifact_root=value["roots"]["source_artifacts"]),
        model_version_id=None if value["model"] is None else value["model"]["version_id"],
        corpus_version_id=None if value["corpus"] is None else value["corpus"]["version_id"],
        association_semantics=value["association_semantics"], authority=dict(_AUTHORITY)))


def _event(registry, event_id):
    # Bound bytes before the existing native getter parses its JSON fields.
    with registry._transaction() as cx:
        sizes = cx.execute("SELECT octet_length(encode(e.event_id))+octet_length(encode(e.kind))+octet_length(encode(e.event_data))+coalesce(octet_length(encode(o.lease)),0)+coalesce(octet_length(encode(o.receipt)),0) FROM autoencoder_control.events e JOIN autoencoder_control.outbox o USING(event_id) WHERE e.event_id=? AND o.consumer='ducklake' LIMIT 2", [event_id]).fetchall()
        _require(len(sizes) == 1 and type(sizes[0][0]) is int and sizes[0][0] <= 128 * 1024,
                 "unknown or oversized native history event")
    value = registry.get_outbox_event("ducklake", event_id)
    _require(type(value["created_at"]) is float and math.isfinite(value["created_at"]), "native event timestamp is not finite")
    return value


def resolve_codebase_history_request(registry, operation_id, request):
    """Resolve exactly this command/payload; never assert current CAS availability."""
    _require(type(registry) is AutoencoderRegistry, "exact native delivery owner required")
    value = _request(request)
    # The existing registry binds operation ID + command + canonical payload.
    result = registry.resolve_operation(operation_id, COMMAND, {"request": value})
    if result is None:
        return None
    expected = dict(schema=REGISTRY_SCHEMA, operation_id=operation_id, command=COMMAND, admitted=False,
        record_cid=value["record_cid"], request_id=content_identity(value),
        event_id=content_identity(dict(operation_id=operation_id, kind=EVENT_KIND, consumer="ducklake")),
        source_observed_live=False, current_artifact_availability_verified=False,
        history_only=True, proof_authority=False, training_authority=False)
    _require(result == expected, "native history registration receipt differs")
    event = _event(registry, result["event_id"])
    _require(event["kind"] == EVENT_KIND and event["payload"] == value,
             "native immutable history event differs from exact operation payload")
    return _copy(result)


def register_codebase_history_request(registry, discovery, operation_id, request):
    """Append a validated metadata event and native outbox row atomically.

    The existing registry mutation primitive supplies exact operation replay and
    the existing event primitive supplies the immutable event plus outbox row.
    No model variant/version or source head is created. Historical replay is
    checked before requiring the captured artifacts to remain available.
    """
    _require(type(registry) is AutoencoderRegistry and type(discovery) is IntentCodebaseCatalog,
             "exact native registry and discovery owners required")
    value = _request(request)
    prior = resolve_codebase_history_request(registry, operation_id, value)
    if prior is not None:
        return prior
    _require(prepare_codebase_history_request(discovery, value["record_cid"]) == value,
             "history request does not reconstruct from native discovery")
    def apply(cx):
        event_id = registry._event(cx, operation_id, EVENT_KIND, value)
        return dict(record_cid=value["record_cid"], request_id=content_identity(value), event_id=event_id,
            source_observed_live=False, current_artifact_availability_verified=False,
            history_only=True, proof_authority=False, training_authority=False)
    registry._mutate(operation_id, COMMAND, {"request": value}, apply)
    return resolve_codebase_history_request(registry, operation_id, value)


def deliver_codebase_history(registry, sink, *, source_id, output_directory,
        worker_id="codebase-history", lease_seconds=300, limit=10):
    """Use the existing durable journal/outbox/native DuckLake worker unchanged.

    The batch belongs to the delivery registry and can include its existing model
    events. Codebase origin roots remain explicit inside each metadata payload.
    """
    return deliver_ducklake_history(registry, sink, source_id=source_id,
        output_directory=output_directory, worker_id=worker_id,
        lease_seconds=lease_seconds, limit=limit)


def _acknowledged_batch(registry, sink, event, source_id):
    receipt = event["receipt"]
    _require(type(receipt) is dict and type(receipt.get("event_ids")) is list
             and 1 <= len(receipt["event_ids"]) <= MAX_INSPECT
             and receipt["event_ids"] == sorted(set(receipt["event_ids"]))
             and event["event_id"] in receipt["event_ids"], "invalid acknowledged batch membership")
    deliveries = [_event(registry, event_id) for event_id in receipt["event_ids"]]
    rows = [_event_row(registry, delivery, verify_artifact=False) for delivery in deliveries]
    source = dict(source_id=source_id, database_path=str(registry.database_path), artifact_root=str(registry.artifact_root))
    batch = build_history_batch(source, rows)
    actual = sink.lookup(batch)
    _require_commit(actual, batch, sink)
    _require(actual == receipt, "native owner acknowledgement differs from actual retained DuckLake commit")
    return batch, actual


def inspect_codebase_history(registry, sink, *, source_id, registrations):
    """Bounded acknowledgement lag and exact native retained-snapshot readback.

    Scope is the explicit requested registration set, not all registry history.
    An unacknowledged event may already be in DuckLake after response loss;
    pending_acknowledgements reports that distinction without inventing absence.
    Retained snapshot observation is not a durable reader pin or GC permission.
    """
    _require(type(registry) is AutoencoderRegistry and type(sink) is IsolatedNativeDuckLakeHistory,
             "exact native delivery owner and isolated DuckLake sink required")
    _require(type(registrations) in (tuple, list) and len(registrations) <= MAX_INSPECT,
             "bounded explicit history registration set required")
    results, identities = [], set()
    for item in registrations:
        _require(type(item) is dict and set(item) == {"operation_id", "request"}, "closed registration selector required")
        receipt = resolve_codebase_history_request(registry, item["operation_id"], item["request"])
        _require(receipt is not None and receipt["event_id"] not in identities,
                 "unknown or duplicate history registration")
        identities.add(receipt["event_id"])
        event = _event(registry, receipt["event_id"])
        row = dict(event_id=event["event_id"], record_cid=receipt["record_cid"], outbox_status=event["status"],
                   snapshot_id=None, snapshot_retained=False, immutable_snapshot_payload_verified=False)
        if event["status"] == "acknowledged":
            batch, commit = _acknowledged_batch(registry, sink, event, source_id)
            snapshot = commit["snapshot_id"]
            _require(type(snapshot) is int and snapshot >= 1, "invalid retained native snapshot")
            expected = canonical_json_bytes(next(v for v in batch["events"] if v["event_id"] == event["event_id"])).decode()
            # Closed integer snapshot selector; never interpolate caller text.
            with sink._mutex:
                sink._boundary()
                sizes = sink._connection.execute(f"SELECT octet_length(encode(event_json)) FROM history.events AT (VERSION => {snapshot}) WHERE source_id=? AND event_id=? LIMIT 2", [source_id, event["event_id"]]).fetchall()
                _require(len(sizes) == 1 and sizes[0][0] <= 128 * 1024, "retained snapshot event exceeds byte bound")
                actual = sink._connection.execute(f"SELECT event_json FROM history.events AT (VERSION => {snapshot}) WHERE source_id=? AND event_id=? LIMIT 2", [source_id, event["event_id"]]).fetchall()
                _require(actual == [(expected,)], "retained snapshot event content differs")
                sink._boundary()
            row.update(snapshot_id=snapshot, snapshot_retained=True, immutable_snapshot_payload_verified=True)
        results.append(row)
    return dict(schema="codebase-discovery-history-inspection@1", scope="explicit_registration_set",
        history_id=sink.identity["history_id"], registrations=len(results),
        pending_acknowledgements=sum(v["outbox_status"] != "acknowledged" for v in results),
        retained_snapshot_records=sum(v["snapshot_retained"] for v in results), records=results,
        source_observed_live=False, proof_authority=False, training_authority=False,
        durable_reader_pin=False, garbage_collection_authority=False, production_activated=False)
