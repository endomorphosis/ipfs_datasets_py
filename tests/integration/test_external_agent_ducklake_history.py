"""EAAEF-094: DuckLake history projection never grants current authority."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from ipfs_datasets_py.ducklake.external_agent_history import (
    CONTROL_HISTORY_CURSOR_READ_OPERATION,
    CONTROL_HISTORY_CURSOR_RECORD_OPERATION,
    CONTROL_HISTORY_OUTBOX_READ_OPERATION,
    HISTORY_CONTROL_ACK_SCHEMA,
    HISTORY_CONTROL_SEAM_CAPABILITY_SCHEMA,
    HISTORY_LAKE_CAPABILITY_SCHEMA,
    HISTORY_PROJECTION_RECEIPT_SCHEMA,
    LAKE_HISTORY_APPEND_OPERATION,
    LAKE_HISTORY_CAPABILITY_OPERATION,
    LAKE_HISTORY_CURSOR_OPERATION,
    DuplicateEpochError,
    ExclusiveHistoryOwnerLease,
    HistoryActivationError,
    HistoryAuthorityError,
    HistoryContentionError,
    HistoryContinuityError,
    HistoryCursor,
    HistoryCursorError,
    HistoryEpoch,
    HistoryLakeOwnerIdentity,
    HistoryLakeQuackClient,
    HistoryOutboxBatch,
    HistoryPrivacyError,
    HistoryProjectionService,
    HistoryProjector,
    HistoryReceiptError,
    HistorySnapshot,
    HistoryTransportError,
    evaluate_history_activation,
    project_outbox,
)

CURSOR = HistoryCursor(
    outbox_ordinal=3,
    owner_epoch=1,
    fence=1,
    source_digest="sha256:" + ("a" * 64),
    owner_id="owner-a",
    shard_id="disposable-test-shard",
)

EVENTS = (
    {
        "kind": "task",
        "event_id": "evt-task-1",
        "run_id": "run-1",
        "task_id": "EAAEF-094",
        "payload": {"status": "completed"},
    },
    {
        "kind": "audit",
        "event_id": "evt-audit-1",
        "run_id": "run-1",
        "payload": {"action": "apply"},
    },
    {
        "kind": "snapshot",
        "event_id": "evt-snap-1",
        "payload": {"snapshot_kind": "epoch"},
    },
    {
        "kind": "lineage",
        "event_id": "evt-line-1",
        "payload": {"parent_epoch_id": "epoch-prior"},
    },
    {
        "kind": "benchmark",
        "event_id": "evt-bench-1",
        "payload": {"name": "control-plane", "count": 4},
    },
    {
        "kind": "recovery",
        "event_id": "evt-rec-1",
        "payload": {"checkpoint": "ordinal-3", "accepted_stale_write": False},
    },
)


def test_project_outbox_emits_immutable_epoch_bundle() -> None:
    epoch = project_outbox(CURSOR, EVENTS, epoch_id="epoch-1")
    assert isinstance(epoch, HistoryEpoch)
    assert isinstance(epoch.cursor, HistoryCursor)
    assert isinstance(epoch.snapshot, HistorySnapshot)
    assert epoch.epoch_id == "epoch-1"
    assert epoch.cursor.outbox_ordinal == 3
    assert epoch.grants_current_authority is False
    assert epoch.as_mapping()["authoritative"] is False
    kinds = {event.kind for event in epoch.events}
    assert kinds >= {"task", "audit", "snapshot", "lineage", "benchmark", "recovery"}
    assert "epoch-prior" in epoch.lineage
    assert epoch.benchmarks
    assert epoch.recovery_manifest["accepted_stale_write"] is False
    assert epoch.content_digest.startswith("sha256:")
    assert epoch.snapshot.content_digest == epoch.content_digest
    with pytest.raises(FrozenInstanceError):
        epoch.epoch_id = "mutated"  # type: ignore[misc]


def test_missing_cursor_fails_closed() -> None:
    with pytest.raises(HistoryCursorError, match="missing"):
        project_outbox(None, EVENTS)
    with pytest.raises(HistoryCursorError, match="missing"):
        project_outbox({}, EVENTS)


def test_duplicate_epoch_ids_fail_closed() -> None:
    projector = HistoryProjector()
    first = projector.project_outbox(CURSOR, EVENTS, epoch_id="epoch-dup")
    assert first.epoch_id == "epoch-dup"
    with pytest.raises(DuplicateEpochError, match="duplicate epoch"):
        projector.project_outbox(CURSOR, EVENTS, epoch_id="epoch-dup")
    with pytest.raises(DuplicateEpochError, match="conflicting epoch"):
        project_outbox(
            CURSOR,
            (
                {**EVENTS[0], "epoch_id": "epoch-a"},
                {**EVENTS[1], "epoch_id": "epoch-b"},
            ),
        )


def test_projection_cannot_grant_or_revoke_authority() -> None:
    epoch = project_outbox(CURSOR, EVENTS, epoch_id="epoch-auth")
    for method in (
        epoch.grant_claim,
        epoch.revoke_claim,
        epoch.grant_lease,
        epoch.revoke_lease,
        epoch.grant_fence,
        epoch.revoke_fence,
        epoch.grant_merge_authority,
        epoch.revoke_merge_authority,
    ):
        with pytest.raises(HistoryAuthorityError, match="cannot"):
            method("task-1")
    assert epoch.grants_current_authority is False


def test_secrets_and_transcripts_are_rejected() -> None:
    with pytest.raises(HistoryPrivacyError, match="secret"):
        project_outbox(
            CURSOR,
            ({"kind": "event", "event_id": "bad", "payload": {"api_key": "k"}},),
        )
    with pytest.raises(HistoryPrivacyError, match="transcript"):
        project_outbox(
            CURSOR,
            ({"kind": "event", "event_id": "bad2", "transcript_body": "hello"},),
        )
    with pytest.raises(HistoryPrivacyError, match="chain-of-thought"):
        project_outbox(
            CURSOR,
            ({"kind": "audit", "event_id": "bad3", "thinking": "hidden"},),
        )


def test_import_is_side_effect_free() -> None:
    source_path = Path(inspect.getsourcefile(project_outbox) or "")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert "duckdb" not in imported
    assert "socket" not in imported
    assert "requests" not in imported
    calls = [
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]
    assert "connect" not in calls


def _digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _control_capability() -> dict[str, Any]:
    payload = {
        "schema": HISTORY_CONTROL_SEAM_CAPABILITY_SCHEMA,
        "available": True,
        "transport": "quack",
        "authority": "one_fenced_duckdb_quack_owner",
        "committed_only": True,
        "owner_verifies_signed_envelopes": True,
        "direct_database_access": False,
        "operations": [
            CONTROL_HISTORY_CURSOR_READ_OPERATION,
            CONTROL_HISTORY_OUTBOX_READ_OPERATION,
            CONTROL_HISTORY_CURSOR_RECORD_OPERATION,
        ],
    }
    payload["capability_cid"] = _digest(payload)
    return payload


def _lake_capability() -> dict[str, Any]:
    payload = {
        "schema": HISTORY_LAKE_CAPABILITY_SCHEMA,
        "available": True,
        "transport": "quack",
        "database_kind": "ducklake",
        "database_role": "history_projection_only",
        "duckdb_version": "1.5.5",
        "extension_builds": {
            "quack": "quack@1.5.5+core",
            "ducklake": "ducklake@1.5.5+core",
            "httpfs": "httpfs@1.5.5+core",
        },
        "automatic_extension_install": False,
        "automatic_extension_load": False,
        "automatic_catalog_migration": False,
        "safe_attach_options": {
            "CREATE_IF_NOT_EXISTS": False,
            "OVERRIDE_DATA_PATH": False,
            "AUTOMATIC_MIGRATION": False,
        },
        "exclusive_owner": True,
        "native_duckdb_file_lock": True,
        "separate_from_control_database": True,
        "separate_owner_lock": True,
        "separate_generation_fence": True,
        "remote_clients_quack_only": True,
        "arbitrary_sql_allowed": False,
        "control_database_opened": False,
        "authoritative": False,
        "owner_generation": 7,
        "fencing_epoch": 11,
        "catalog_id": "history-catalog",
        "endpoint_id": "history-quack",
        "operations": [
            LAKE_HISTORY_CAPABILITY_OPERATION,
            LAKE_HISTORY_CURSOR_OPERATION,
            LAKE_HISTORY_APPEND_OPERATION,
        ],
    }
    payload["capability_cid"] = _digest(payload)
    return payload


def test_activation_is_held_without_the_missing_typed_control_seam() -> None:
    decision = evaluate_history_activation(None, _lake_capability())
    assert decision.activated is False
    assert "typed_control_outbox_cursor_seam_unavailable" in decision.blockers
    assert decision.as_mapping()["projection_is_authority"] is False
    with pytest.raises(HistoryActivationError, match="disabled fail-closed"):
        decision.require_activated()

    service = HistoryProjectionService()
    assert service.preflight().activated is False
    with pytest.raises(HistoryActivationError, match="disabled fail-closed"):
        service.project_next()


def test_activation_requires_two_separate_quack_only_owners() -> None:
    accepted = evaluate_history_activation(
        _control_capability(),
        _lake_capability(),
    )
    assert accepted.activated is True
    assert accepted.as_mapping()["control_plane"] == ("one_fenced_duckdb_quack_owner")
    assert accepted.as_mapping()["history_plane"] == ("one_separate_ducklake_quack_owner")

    unsafe = _lake_capability()
    unsafe["remote_clients_quack_only"] = False
    unsafe["control_database_opened"] = True
    unsafe["arbitrary_sql_allowed"] = True
    denied = evaluate_history_activation(_control_capability(), unsafe)
    assert denied.activated is False
    assert set(denied.blockers) >= {
        "lake_clients_not_quack_only",
        "lake_owner_opens_control_database",
        "lake_arbitrary_sql_not_denied",
    }


def test_history_owner_uses_a_separate_nonblocking_lock(tmp_path: Path) -> None:
    identity = HistoryLakeOwnerIdentity(
        owner_id="lake-owner-1",
        catalog_id="history-catalog",
        endpoint_id="history-quack",
        catalog_metadata_path=str(tmp_path / "history-catalog.duckdb"),
        companion_registry_path=str(tmp_path / "history-registry.duckdb"),
        owner_lock_path=str(tmp_path / "history-owner.lock"),
        owner_generation=7,
        fencing_epoch=11,
        control_database_paths=(str(tmp_path / "control.duckdb"),),
    )
    public = identity.as_public_mapping()
    assert public["database_is_separate_from_control"] is True
    assert public["lock_is_separate_from_control"] is True
    assert not any("path" in key for key in public)

    first = ExclusiveHistoryOwnerLease(identity).acquire()
    try:
        assert first.held is True
        with pytest.raises(HistoryContentionError, match="already held"):
            ExclusiveHistoryOwnerLease(identity).acquire()
    finally:
        first.release()
    with ExclusiveHistoryOwnerLease(identity) as successor:
        assert successor.held is True

    with pytest.raises(HistoryActivationError, match="must not reuse"):
        HistoryLakeOwnerIdentity(
            owner_id="lake-owner-2",
            catalog_id="history-catalog",
            endpoint_id="history-quack-2",
            catalog_metadata_path=str(tmp_path / "control.duckdb"),
            companion_registry_path=str(tmp_path / "registry-2.duckdb"),
            owner_lock_path=str(tmp_path / "owner-2.lock"),
            owner_generation=8,
            fencing_epoch=12,
            control_database_paths=(str(tmp_path / "control.duckdb"),),
        )


class _FakeControlGateway:
    def __init__(self, batch: HistoryOutboxBatch) -> None:
        self.batch = batch
        self.cursor: HistoryCursor | None = None
        self.ack_attempts = 0
        self.fail_first_ack = True

    def capability(self) -> Mapping[str, Any]:
        return _control_capability()

    def projection_cursor(self) -> HistoryCursor | None:
        return self.cursor

    def read_committed_history(
        self,
        *,
        after_outbox_ordinal: int,
        limits: Any,
    ) -> HistoryOutboxBatch | None:
        assert limits.max_events <= 5_000
        if self.cursor is not None:
            return None
        assert after_outbox_ordinal == 0
        return self.batch

    def record_projection_cursor(self, receipt: Mapping[str, Any]) -> Mapping[str, Any]:
        self.ack_attempts += 1
        if self.fail_first_ack and self.ack_attempts == 1:
            raise RuntimeError("injected lost control acknowledgement")
        self.cursor = HistoryCursor.from_mapping(receipt["cursor"])
        return {
            "schema": HISTORY_CONTROL_ACK_SCHEMA,
            "recorded": True,
            "transport": "quack",
            "authority": "one_fenced_duckdb_quack_owner",
            "projection_is_authority": False,
            "operation_id": receipt["operation_id"],
            "projection_receipt_digest": receipt["receipt_digest"],
            "outbox_ordinal": self.cursor.outbox_ordinal,
            "ack_receipt_cid": _digest(
                {
                    "operation_id": receipt["operation_id"],
                    "receipt_digest": receipt["receipt_digest"],
                }
            ),
        }


class _FakeLakeQuackOwner:
    """Hermetic typed transport; one logical row per deterministic operation."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.append_attempts = 0

    def invoke(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert request["catalog_id"] == "history-catalog"
        assert request["endpoint_id"] == "history-quack"
        assert request["owner_generation"] == 7
        assert request["fencing_epoch"] == 11
        assert "sql" not in request
        operation = request["operation"]
        if operation == LAKE_HISTORY_CAPABILITY_OPERATION:
            return _lake_capability()
        if operation == LAKE_HISTORY_CURSOR_OPERATION:
            head = max(
                self.rows.values(),
                key=lambda item: item["cursor"]["outbox_ordinal"],
                default=None,
            )
            return {"operation": operation, "receipt": head}
        if operation != LAKE_HISTORY_APPEND_OPERATION:
            raise AssertionError(f"unexpected operation {operation}")
        self.append_attempts += 1
        payload = request["payload"]
        operation_id = payload["operation_id"]
        prior = self.rows.get(operation_id)
        if prior is not None:
            return prior
        epoch = payload["epoch"]
        body = {
            "schema": HISTORY_PROJECTION_RECEIPT_SCHEMA,
            "operation_id": operation_id,
            "batch_id": payload["batch_id"],
            "batch_digest": payload["batch_digest"],
            "control_receipt_cid": payload["control_receipt_cid"],
            "epoch_id": epoch["epoch_id"],
            "cursor": epoch["cursor"],
            "content_digest": epoch["content_digest"],
            "lake_snapshot": len(self.rows) + 1,
            "owner_generation": request["owner_generation"],
            "fencing_epoch": request["fencing_epoch"],
            "catalog_id": request["catalog_id"],
            "endpoint_id": request["endpoint_id"],
            "row_count": len(epoch["events"]) + 1,
            "replayed": False,
            "committed": True,
            "authoritative": False,
            "grants_current_authority": False,
            "control_cursor_recorded": False,
        }
        body["receipt_digest"] = _digest(body)
        self.rows[operation_id] = body
        return body


def test_one_owner_projection_replays_after_lost_ack_without_duplicate() -> None:
    batch = HistoryOutboxBatch.build(
        batch_id="history-epoch-1",
        previous_outbox_ordinal=0,
        cursor=CURSOR,
        events=EVENTS,
        control_receipt_cid="sha256:" + ("b" * 64),
    )
    control = _FakeControlGateway(batch)
    lake_owner = _FakeLakeQuackOwner()
    lake_client = HistoryLakeQuackClient(
        endpoint_id="history-quack",
        catalog_id="history-catalog",
        owner_generation=7,
        fencing_epoch=11,
        invoke=lake_owner.invoke,
    )
    service = HistoryProjectionService(
        control_gateway=control,
        lake_client=lake_client,
    )
    assert service.preflight().activated is True
    with pytest.raises(RuntimeError, match="lost control acknowledgement"):
        service.project_next()
    assert len(lake_owner.rows) == 1
    result = service.project_next()
    assert result is not None
    assert result.projection.cursor == CURSOR
    assert result.as_mapping()["ducklake_grants_current_authority"] is False
    assert len(lake_owner.rows) == 1
    assert lake_owner.append_attempts == 2
    assert control.ack_attempts == 2
    assert service.project_next() is None


def test_quack_client_rejects_paths_sql_and_stale_receipts() -> None:
    def unsafe_transport(request: Mapping[str, Any]) -> Mapping[str, Any]:
        del request
        return {"sql": "SELECT * FROM control.tasks"}

    client = HistoryLakeQuackClient(
        endpoint_id="history-quack",
        catalog_id="history-catalog",
        owner_generation=7,
        fencing_epoch=11,
        invoke=unsafe_transport,
    )
    with pytest.raises(HistoryTransportError, match="direct-access"):
        client.capability()

    batch = HistoryOutboxBatch.build(
        batch_id="history-epoch-stale",
        previous_outbox_ordinal=0,
        cursor=CURSOR,
        events=EVENTS,
        control_receipt_cid="sha256:" + ("c" * 64),
    )
    lake_owner = _FakeLakeQuackOwner()
    valid = HistoryLakeQuackClient(
        endpoint_id="history-quack",
        catalog_id="history-catalog",
        owner_generation=7,
        fencing_epoch=11,
        invoke=lake_owner.invoke,
    )
    epoch = project_outbox(CURSOR, EVENTS, epoch_id=batch.batch_id)
    receipt = valid.append_epoch(
        operation_id="operation-stale-test",
        batch=batch,
        epoch=epoch,
        expected_previous_outbox_ordinal=0,
    )
    tampered = dict(receipt.as_mapping())
    tampered["fencing_epoch"] = 10
    with pytest.raises(HistoryReceiptError, match="digest"):
        type(receipt).from_mapping(tampered)


def test_control_and_lake_cursor_divergence_fails_closed() -> None:
    batch = HistoryOutboxBatch.build(
        batch_id="history-epoch-divergent",
        previous_outbox_ordinal=0,
        cursor=CURSOR,
        events=EVENTS,
        control_receipt_cid="sha256:" + ("d" * 64),
    )
    control = _FakeControlGateway(batch)
    control.cursor = HistoryCursor(
        outbox_ordinal=8,
        owner_epoch=1,
        fence=1,
        source_digest="sha256:" + ("e" * 64),
        owner_id="owner-a",
        shard_id="disposable-test-shard",
    )
    lake_owner = _FakeLakeQuackOwner()
    lake_client = HistoryLakeQuackClient(
        endpoint_id="history-quack",
        catalog_id="history-catalog",
        owner_generation=7,
        fencing_epoch=11,
        invoke=lake_owner.invoke,
    )
    service = HistoryProjectionService(
        control_gateway=control,
        lake_client=lake_client,
    )
    with pytest.raises(HistoryContinuityError, match="ahead"):
        service.project_next()
