"""EAAEF-094: DuckLake history projection never grants current authority."""

from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ipfs_datasets_py.ducklake.external_agent_history import (
    DuplicateEpochError,
    HistoryAuthorityError,
    HistoryCursor,
    HistoryCursorError,
    HistoryEpoch,
    HistoryPrivacyError,
    HistoryProjector,
    HistorySnapshot,
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
