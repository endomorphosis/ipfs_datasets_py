"""EAAEF-094: DuckLake history projection never grants current authority."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import platform
import secrets
import socket
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from ipfs_datasets_py.ducklake import capabilities as lake_capabilities
from ipfs_datasets_py.ducklake.external_agent_history import (
    CONTROL_HISTORY_CURSOR_READ_OPERATION,
    CONTROL_HISTORY_CURSOR_RECORD_OPERATION,
    CONTROL_HISTORY_OUTBOX_READ_OPERATION,
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
    HistoryError,
    HistoryLakeOwnerIdentity,
    HistoryLakeQuackClient,
    HistoryOutboxBatch,
    HistoryPrivacyError,
    HistoryProjectionLimits,
    HistoryProjectionReceipt,
    HistoryProjectionService,
    HistoryProjector,
    HistoryReceiptError,
    HistorySnapshot,
    HistoryTransportError,
    evaluate_history_activation,
    history_projection_operation_id,
    project_outbox,
    require_acknowledged_history_head_matches,
    require_history_replay_head_matches,
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


def test_epoch_and_batch_take_deep_immutable_json_snapshots() -> None:
    raw_event = {
        "kind": "event",
        "event_id": "nested-event",
        "payload": {"nested": {"values": [1, 2]}},
    }
    epoch = project_outbox(CURSOR, (raw_event,), epoch_id="nested-epoch")
    batch = HistoryOutboxBatch.build(
        batch_id="nested-epoch",
        previous_outbox_ordinal=0,
        cursor=CURSOR,
        events=(raw_event,),
        control_receipt_cid="sha256:" + ("9" * 64),
    )
    raw_event["payload"]["nested"]["values"].append(3)

    assert epoch.events[0].payload["nested"]["values"] == (1, 2)
    assert batch.as_mapping()["events"][0]["payload"]["nested"]["values"] == [1, 2]
    batch.require_digest_valid()

    detached = epoch.as_mapping()
    detached["events"][0]["payload"]["nested"]["values"].append(99)
    assert epoch.events[0].payload["nested"]["values"] == (1, 2)
    with pytest.raises(TypeError):
        epoch.events[0].payload["nested"]["new"] = True

    object.__setattr__(batch, "batch_digest", "sha256:" + ("0" * 64))
    with pytest.raises(HistoryReceiptError, match="changed after"):
        batch.require_digest_valid()

    with pytest.raises(HistoryError, match="strict JSON"):
        project_outbox(
            CURSOR,
            ({"kind": "event", "event_id": "object", "payload": {"value": object()}},),
        )


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
        "owner_id": "control-owner",
        "endpoint_id": "control-quack",
        "owner_process_birth_id": "control-process-birth",
        "owner_generation": 3,
        "fencing_epoch": 5,
        "generation_namespace": "eaaef-control-owner-generation",
        "fence_namespace": "eaaef-control-owner-fence",
        "database_binding_cid": "sha256:" + ("1" * 64),
        "independent_capability_receipt_cid": "sha256:" + ("2" * 64),
        "operations": [
            CONTROL_HISTORY_CURSOR_READ_OPERATION,
            CONTROL_HISTORY_OUTBOX_READ_OPERATION,
            CONTROL_HISTORY_CURSOR_RECORD_OPERATION,
        ],
    }
    payload["capability_cid"] = _digest(payload)
    return payload


def _plain_artifact_pins(platform_name: str) -> dict[str, dict[str, str]]:
    return {
        name: dict(platforms[platform_name])
        for name, platforms in lake_capabilities.PINNED_PLATFORM_DIGESTS.items()
    }


def _lake_capability(
    *,
    platform_name: str = "linux_arm64",
    owner_generation: int = 7,
    fencing_epoch: int = 11,
) -> dict[str, Any]:
    payload = {
        "schema": HISTORY_LAKE_CAPABILITY_SCHEMA,
        "available": True,
        "transport": "quack",
        "database_kind": "ducklake",
        "database_role": "history_projection_only",
        "duckdb_version": "1.5.5",
        "ducklake_specification_version": "1.0",
        "ducklake_catalog_version": "1.0",
        "platform": platform_name,
        "extension_builds": {
            "quack": "quack@1.5.5+core",
            "ducklake": "ducklake@1.5.5+core",
            "httpfs": "httpfs@1.5.5+core",
        },
        "extension_artifact_digests": _plain_artifact_pins(platform_name),
        "explicit_load_order": ["quack", "ducklake", "httpfs"],
        "load_before_configuration_lock": True,
        "configuration_lock_settings": dict(lake_capabilities.CONFIGURATION_LOCK_SETTINGS),
        "allow_unsigned_extensions": False,
        "environment_receipt_schema": lake_capabilities.ENVIRONMENT_RECEIPT_SCHEMA,
        "environment_receipt_cid": "sha256:" + ("3" * 64),
        "native_runtime_receipt_cid": "sha256:" + ("4" * 64),
        "database_binding_cid": "sha256:" + ("5" * 64),
        "owner_lock_binding_cid": "sha256:" + ("6" * 64),
        "independent_capability_receipt_cid": "sha256:" + ("7" * 64),
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
        "owner_verifies_signed_envelopes": True,
        "arbitrary_sql_allowed": False,
        "control_database_opened": False,
        "authoritative": False,
        "owner_id": "history-owner",
        "owner_process_birth_id": "history-process-birth",
        "owner_generation": owner_generation,
        "fencing_epoch": fencing_epoch,
        "generation_namespace": "eaaef-history-owner-generation",
        "fence_namespace": "eaaef-history-owner-fence",
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


def test_exact_self_reports_remain_held_without_independent_binding_and_deadline() -> None:
    held = evaluate_history_activation(
        _control_capability(),
        _lake_capability(),
    )
    assert held.activated is False
    assert set(held.blockers) == {
        "independent_signed_capability_binding_unavailable",
        "bounded_projection_deadline_enforcement_unavailable",
    }
    assert held.as_mapping()["control_plane"] == ("one_fenced_duckdb_quack_owner")
    assert held.as_mapping()["history_plane"] == ("one_separate_ducklake_quack_owner")
    assert not hasattr(HistoryProjectionLimits(), "timeout_seconds")

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

    same_owner = _lake_capability()
    same_owner["owner_id"] = _control_capability()["owner_id"]
    same_owner["capability_cid"] = _digest(
        {key: value for key, value in same_owner.items() if key != "capability_cid"}
    )
    denied_same_owner = evaluate_history_activation(_control_capability(), same_owner)
    assert "control_and_lake_owner_not_distinct" in denied_same_owner.blockers


def _owner_identity_payload(
    root: Path,
    *,
    owner_id: str,
    generation: int,
    fence: int,
) -> dict[str, Any]:
    catalog = root / "history-catalog.duckdb"
    return {
        "owner_id": owner_id,
        "catalog_id": "history-catalog",
        "endpoint_id": "history-quack",
        "catalog_metadata_path": str(catalog),
        "companion_registry_path": str(root / "history-registry.duckdb"),
        "owner_lock_path": str(Path(str(catalog) + ".history-owner.lock")),
        "owner_generation": generation,
        "fencing_epoch": fence,
        "control_database_paths": (str(root / "control.duckdb"),),
    }


def test_history_owner_uses_a_separate_cross_process_nonblocking_lock(
    tmp_path: Path,
) -> None:
    identity = HistoryLakeOwnerIdentity(
        **_owner_identity_payload(
            tmp_path,
            owner_id="lake-owner-1",
            generation=7,
            fence=11,
        )
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

        successor_payload = _owner_identity_payload(
            tmp_path,
            owner_id="lake-owner-2",
            generation=8,
            fence=12,
        )
        contender = subprocess.run(
            [
                sys.executable,
                "-c",
                "\n".join(
                    (
                        "import json, sys",
                        "from ipfs_datasets_py.ducklake.external_agent_history import (",
                        "    ExclusiveHistoryOwnerLease, HistoryContentionError,",
                        "    HistoryLakeOwnerIdentity,",
                        ")",
                        "payload = json.loads(sys.argv[1])",
                        "payload['control_database_paths'] = tuple(payload['control_database_paths'])",
                        "try:",
                        "    ExclusiveHistoryOwnerLease(HistoryLakeOwnerIdentity(**payload)).acquire()",
                        "except HistoryContentionError:",
                        "    raise SystemExit(23)",
                        "raise SystemExit(0)",
                    )
                ),
                json.dumps(successor_payload, sort_keys=True),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert contender.returncode == 23, contender.stderr
    finally:
        first.release()
    successor_identity = HistoryLakeOwnerIdentity(**successor_payload)
    with ExclusiveHistoryOwnerLease(successor_identity) as successor:
        assert successor.held is True

    with pytest.raises(HistoryContentionError, match="generation must advance"):
        ExclusiveHistoryOwnerLease(successor_identity).acquire()

    with pytest.raises(HistoryActivationError, match="must not reuse"):
        catalog = tmp_path / "control.duckdb"
        HistoryLakeOwnerIdentity(
            owner_id="lake-owner-3",
            catalog_id="history-catalog-2",
            endpoint_id="history-quack-2",
            catalog_metadata_path=str(catalog),
            companion_registry_path=str(tmp_path / "registry-2.duckdb"),
            owner_lock_path=str(Path(str(catalog) + ".history-owner.lock")),
            owner_generation=9,
            fencing_epoch=13,
            control_database_paths=(str(catalog),),
        )


class _FakeLakeQuackOwner:
    """Hermetic CAS model; one logical epoch per stable operation id."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.append_attempts = 0

    def invoke(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert request["catalog_id"] == "history-catalog"
        assert request["endpoint_id"] == "history-quack"
        assert "sql" not in request
        operation = request["operation"]
        if operation == LAKE_HISTORY_CAPABILITY_OPERATION:
            return _lake_capability(
                owner_generation=request["owner_generation"],
                fencing_epoch=request["fencing_epoch"],
            )
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
            for key in ("batch_id", "batch_digest", "control_receipt_cid"):
                if prior[key] != payload[key]:
                    raise AssertionError("divergent stable operation replay")
            epoch = payload["epoch"]
            if prior["epoch_id"] != epoch["epoch_id"]:
                raise AssertionError("divergent stable epoch replay")
            return prior
        head_ordinal = max(
            (item["cursor"]["outbox_ordinal"] for item in self.rows.values()),
            default=0,
        )
        if payload["expected_previous_outbox_ordinal"] != head_ordinal:
            raise AssertionError("append compare-and-swap predecessor mismatch")
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


def test_projection_id_is_restart_stable_and_replay_does_not_append() -> None:
    batch = HistoryOutboxBatch.build(
        batch_id="history-epoch-1",
        previous_outbox_ordinal=0,
        cursor=CURSOR,
        events=EVENTS,
        control_receipt_cid="sha256:" + ("b" * 64),
    )
    lake_owner = _FakeLakeQuackOwner()
    first_client = HistoryLakeQuackClient(
        endpoint_id="history-quack",
        catalog_id="history-catalog",
        owner_generation=7,
        fencing_epoch=11,
        invoke=lake_owner.invoke,
    )
    epoch = project_outbox(CURSOR, EVENTS, epoch_id=batch.batch_id)
    operation_id = history_projection_operation_id(
        batch=batch,
        epoch=epoch,
        catalog_id="history-catalog",
    )
    first = first_client.append_epoch(
        operation_id=operation_id,
        batch=batch,
        epoch=epoch,
        expected_previous_outbox_ordinal=0,
    )
    assert first.replayed is False
    assert len(lake_owner.rows) == 1

    restarted_client = HistoryLakeQuackClient(
        endpoint_id="history-quack",
        catalog_id="history-catalog",
        owner_generation=8,
        fencing_epoch=12,
        invoke=lake_owner.invoke,
    )
    same_operation_id = history_projection_operation_id(
        batch=batch,
        epoch=epoch,
        catalog_id="history-catalog",
    )
    assert same_operation_id == operation_id
    prior_head = restarted_client.projection_head()
    assert prior_head is not None
    require_history_replay_head_matches(
        prior_head,
        batch=batch,
        epoch=epoch,
        operation_id=operation_id,
    )
    replay = restarted_client.append_epoch(
        operation_id=operation_id,
        batch=batch,
        epoch=epoch,
        expected_previous_outbox_ordinal=0,
        prior_receipt=prior_head,
    )
    assert replay.receipt_digest == first.receipt_digest
    assert replay.owner_generation == 7
    assert replay.fencing_epoch == 11
    assert replay.lake_snapshot == first.lake_snapshot
    assert len(lake_owner.rows) == 1
    assert lake_owner.rows[operation_id] == dict(first.as_mapping())
    assert lake_owner.append_attempts == 2


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
    lake_owner = _FakeLakeQuackOwner()
    lake_client = HistoryLakeQuackClient(
        endpoint_id="history-quack",
        catalog_id="history-catalog",
        owner_generation=7,
        fencing_epoch=11,
        invoke=lake_owner.invoke,
    )
    epoch = project_outbox(CURSOR, EVENTS, epoch_id=batch.batch_id)
    operation_id = history_projection_operation_id(
        batch=batch,
        epoch=epoch,
        catalog_id="history-catalog",
    )
    checkpoint = lake_client.append_epoch(
        operation_id=operation_id,
        batch=batch,
        epoch=epoch,
        expected_previous_outbox_ordinal=0,
    )

    divergent_mapping = dict(checkpoint.as_mapping())
    divergent_mapping["batch_id"] = "different-batch-same-cursor"
    divergent_mapping["operation_id"] = "different-operation-same-cursor"
    divergent_mapping.pop("receipt_digest")
    divergent_mapping["receipt_digest"] = _digest(divergent_mapping)
    divergent_head = HistoryProjectionReceipt.from_mapping(divergent_mapping)
    assert divergent_head.cursor == checkpoint.cursor
    with pytest.raises(HistoryContinuityError, match="different projection receipts"):
        require_acknowledged_history_head_matches(checkpoint, divergent_head)

    with pytest.raises(HistoryContinuityError, match="exact control batch"):
        require_history_replay_head_matches(
            divergent_head,
            batch=batch,
            epoch=epoch,
            operation_id=operation_id,
        )


def _host_extension_platform() -> str | None:
    if platform.system().lower() != "linux":
        return None
    machine = platform.machine().lower()
    if machine in {"aarch64", "arm64"}:
        return "linux_arm64"
    if machine in {"x86_64", "amd64"}:
        return "linux_amd64"
    return None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_local_exact_duckdb_quack_ducklake_stack_is_hermetic_and_still_held(
    tmp_path: Path,
) -> None:
    """Exercise installed exact artifacts when present, with no skip or activation claim."""

    platform_name = _host_extension_platform()
    try:
        import duckdb
    except ImportError:
        assert evaluate_history_activation(None, None).activated is False
        return
    if duckdb.__version__ != lake_capabilities.REQUIRED_DUCKDB_VERSION_TEXT:
        assert evaluate_history_activation(None, None).activated is False
        return
    if platform_name is None:
        assert evaluate_history_activation(None, None).activated is False
        return

    extension_dir = (
        Path.home()
        / ".duckdb"
        / "extensions"
        / f"v{lake_capabilities.REQUIRED_DUCKDB_VERSION_TEXT}"
        / platform_name
    )
    extensions = {
        name: extension_dir / f"{name}.duckdb_extension"
        for name in lake_capabilities.EXPLICIT_LOAD_ORDER
    }
    if not all(path.is_file() for path in extensions.values()):
        assert evaluate_history_activation(None, None).activated is False
        return

    expected_pins = _plain_artifact_pins(platform_name)
    for name, path in extensions.items():
        assert _file_sha256(path) == expected_pins[name]["bin_sha256"]

    catalog = tmp_path / "history-catalog.duckdb"
    identity = HistoryLakeOwnerIdentity(
        owner_id="local-hermetic-history-owner",
        catalog_id="local-hermetic-history-catalog",
        endpoint_id="local-hermetic-history-quack",
        catalog_metadata_path=str(catalog),
        companion_registry_path=str(tmp_path / "history-owner.duckdb"),
        owner_lock_path=str(Path(str(catalog) + ".history-owner.lock")),
        owner_generation=1,
        fencing_epoch=1,
        control_database_paths=(str(tmp_path / "unopened-control.duckdb"),),
    )
    with ExclusiveHistoryOwnerLease(identity):
        owner = duckdb.connect(str(tmp_path / "history-owner.duckdb"))
        started = False
        endpoint = ""
        try:
            for name in lake_capabilities.EXPLICIT_LOAD_ORDER:
                owner.execute(f"LOAD '{str(extensions[name]).replace(chr(39), chr(39) * 2)}'")
            catalog_sql = str(catalog).replace("'", "''")
            data_sql = str(tmp_path / "history-data").replace("'", "''")
            owner.execute(f"ATTACH 'ducklake:{catalog_sql}' AS history (DATA_PATH '{data_sql}')")
            owner.execute("CREATE TABLE history.epochs (epoch_id VARCHAR, body VARCHAR)")
            owner.execute("INSERT INTO history.epochs VALUES ('epoch-1', 'observed')")
            exact_query = "SELECT epoch_id, body FROM history.epochs ORDER BY epoch_id"
            exact_query_sql = exact_query.replace("'", "''")
            owner.execute(
                "CREATE OR REPLACE MACRO eaaef094_history_authorize(sid, query) "
                f"AS (sid IS NOT NULL AND query = '{exact_query_sql}')"
            )
            owner.execute("SET GLOBAL quack_authentication_function = 'quack_check_token'")
            owner.execute("SET GLOBAL quack_authorization_function = 'eaaef094_history_authorize'")
            reservation = socket.socket()
            try:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            finally:
                reservation.close()
            endpoint = f"quack:127.0.0.1:{port}"
            token = secrets.token_hex(32)
            owner.execute(
                "CALL quack_serve(?, token := ?, disable_ssl := true)",
                [endpoint, token],
            ).fetchall()
            started = True

            client = duckdb.connect(":memory:")
            try:
                client.execute(f"LOAD '{str(extensions['quack']).replace(chr(39), chr(39) * 2)}'")
                rows = client.execute(
                    "SELECT * FROM quack_query(?, ?, token := ?, disable_ssl := true)",
                    [endpoint, exact_query, token],
                ).fetchall()
                assert rows == [("epoch-1", "observed")]
                with pytest.raises(duckdb.Error):
                    client.execute(
                        "SELECT * FROM quack_query(?, ?, token := ?, disable_ssl := true)",
                        [endpoint, "SELECT * FROM history.epochs", token],
                    ).fetchall()
            finally:
                client.close()
        finally:
            if started:
                owner.execute("CALL quack_stop(?)", [endpoint]).fetchall()
            owner.close()

    held = evaluate_history_activation(
        _control_capability(),
        _lake_capability(platform_name=platform_name),
    )
    assert held.activated is False
    assert "independent_signed_capability_binding_unavailable" in held.blockers
