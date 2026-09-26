"""Isolated native storage fixtures, never model/training qualification."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.ducklake import autoencoder_history as history


def source(tmp_path):
    return {"source_id": "fixture-owner", "database_path": str(tmp_path / "owner.duckdb"), "artifact_root": str(tmp_path / "cas")}


def event(number="a", **changes):
    value = {"event_id": number, "kind": "synthetic_fixture", "payload": {"zero": -0.0, "boolean": True, "integer": 1, "unicode": "é"}, "created_at": 1_800_000_000.25, "version": {"version_id": "fixture-version", "artifact": {"sha256": "a" * 64, "bytes": 10}}, "variant": {"variant_id": "fixture-variant"}}
    value.update(changes)
    return value


def batch(tmp_path, *events):
    return history.build_history_batch(source(tmp_path), list(events or [event()]))


@pytest.fixture
def sink(tmp_path):
    with history.IsolatedNativeDuckLakeHistory(tmp_path / "history", create=True) as value:
        yield value


def test_batch_detached_sorted_and_exact_scalar_types(tmp_path):
    original = [event("b"), event("a")]
    result = history.build_history_batch(source(tmp_path), original)
    assert [row["event_id"] for row in result["events"]] == ["a", "b"]
    assert result["batch_id"] == history._identity({key: value for key, value in result.items() if key != "batch_id"})
    original[0]["payload"]["integer"] = 99
    assert result["events"][1]["payload"]["integer"] == 1
    assert b'"zero":-0.0' in history._json(result)
    assert history.validate_history_source(source(tmp_path)) == source(tmp_path)


@pytest.mark.parametrize("change", [
    lambda b: b.update(extra=1),
    lambda b: b.update(schema=True),
    lambda b: b.update(batch_id="wrong"),
    lambda b: b["source"].update(extra=1),
    lambda b: b["source"].update(source_id=True),
    lambda b: b["source"].update(database_path="relative"),
    lambda b: b["source"].update(artifact_root="/tmp/../bad"),
    lambda b: b["events"][0].update(extra=1),
    lambda b: b["events"][0].update(payload=[]),
    lambda b: b["events"][0].update(version=[]),
    lambda b: b["events"][0].update(variant=False),
    lambda b: b["events"][0].update(created_at=None),
    lambda b: b["events"][0]["payload"].update(bad=float("nan")),
    lambda b: b["events"][0]["payload"].update(bad=(1, 2)),
    lambda b: b["events"][0]["payload"].update({1: "bad"}),
    lambda b: b.update(events=[]),
    lambda b: b.update(events=b["events"] * 11),
])
def test_closed_batch_rejections(tmp_path, change):
    value = batch(tmp_path)
    change(value)
    with pytest.raises(history.HistoryError):
        history.validate_history_batch(value)


def test_duplicate_unsorted_and_bounds(tmp_path):
    with pytest.raises(history.HistoryError, match="unique"):
        history.build_history_batch(source(tmp_path), [event(), event()])
    value = batch(tmp_path, event("a"), event("b"))
    value["events"].reverse()
    with pytest.raises(history.HistoryError, match="sorted"):
        history.validate_history_batch(value)
    with pytest.raises(history.HistoryError):
        batch(tmp_path, event(payload={"too_big": "x" * history.MAX_BATCH_BYTES}))
    value = {}
    for _ in range(34):
        value = {"child": value}
    with pytest.raises(history.HistoryError, match="depth"):
        batch(tmp_path, event(payload=value))
    with pytest.raises(history.HistoryError):
        batch(tmp_path, event(payload={"surrogate": "\ud800"}))


def test_native_reopen_exact_receipt_and_real_parquet(tmp_path):
    root = tmp_path / "history"
    value = batch(tmp_path)
    with history.IsolatedNativeDuckLakeHistory(root, create=True) as sink:
        receipt = sink.append(value)
        assert receipt == sink.lookup(value) == sink.append(value)
        assert receipt["snapshot_id"] == sink._connection.execute("SELECT id FROM history.last_committed_snapshot()").fetchone()[0]
        identity = sink.identity
        identity["runtime"]["duckdb"] = "tampered copy"
        assert sink.identity["runtime"]["duckdb"] == "1.5.5"
        assert sink._connection.execute("SELECT count(*) FROM history.events").fetchone() == (1,)
        assert sink._connection.execute("SELECT count(*) FROM history.commits").fetchone() == (1,)
    assert list((root / "data").rglob("*.parquet"))
    with history.IsolatedNativeDuckLakeHistory(root) as sink:
        assert sink.lookup(value) == receipt
        assert sink.append(value) == receipt
    assert receipt["production_activated"] is receipt["admitted"] is False


def test_commit_before_response_loss_recovers_on_reopen(tmp_path, monkeypatch):
    root = tmp_path / "history"
    value = batch(tmp_path)
    with history.IsolatedNativeDuckLakeHistory(root, create=True) as sink:
        original = sink._lookup
        calls = []
        def lost_result(batch):
            calls.append(1)
            if len(calls) == 2:
                raise ConnectionError("fixture lost committed reply")
            return original(batch)
        monkeypatch.setattr(sink, "_lookup", lost_result)
        with pytest.raises(ConnectionError, match="lost committed"):
            sink.append(value)
    with history.IsolatedNativeDuckLakeHistory(root) as sink:
        receipt = sink.lookup(value)
        assert receipt is not None
        assert sink.append(value) == receipt
        assert sink._connection.execute("SELECT count(*) FROM history.events").fetchone() == (1,)


def test_partial_overlap_inserts_only_missing_exact_rows(sink, tmp_path):
    first = sink.append(batch(tmp_path, event("a"), event("b")))
    second_batch = batch(tmp_path, event("b"), event("c"))
    second = sink.append(second_batch)
    assert second["snapshot_id"] > first["snapshot_id"]
    assert sink._connection.execute("SELECT event_id FROM history.events ORDER BY event_id").fetchall() == [("a",), ("b",), ("c",)]
    assert sink.lookup(second_batch) == second


@pytest.mark.parametrize("mutation", [
    lambda e: e["payload"].update(zero=0.0),
    lambda e: e["payload"].update(boolean=1),
    lambda e: e["payload"].update(integer=1.0),
    lambda e: e.update(version={"version_id": "other"}),
])
def test_changed_event_rejected_without_new_snapshot(sink, tmp_path, mutation):
    original = batch(tmp_path)
    receipt = sink.append(original)
    changed = event()
    mutation(changed)
    with pytest.raises(history.HistoryError, match="conflict"):
        sink.append(batch(tmp_path, changed))
    assert sink.lookup(original) == receipt
    assert sink._connection.execute("SELECT count(*) FROM history.commits").fetchone() == (1,)


def test_changed_source_binding_rejected(sink, tmp_path):
    sink.append(batch(tmp_path))
    changed = source(tmp_path)
    changed["database_path"] += ".changed"
    with pytest.raises(history.HistoryError, match="source namespace"):
        sink.append(history.build_history_batch(changed, [event("b")]))


@pytest.mark.parametrize("sql", [
    "UPDATE history.commits SET batch_json='{}'",
    "DELETE FROM history.commits",
    "DELETE FROM history.events",
    "INSERT INTO history.events SELECT * FROM history.events",
    "DELETE FROM history.sources",
    "INSERT INTO history.sources SELECT * FROM history.sources",
])
def test_native_marker_or_event_corruption_never_acknowledged(sink, tmp_path, sql):
    value = batch(tmp_path)
    sink.append(value)
    sink._connection.execute(sql)
    with pytest.raises(history.HistoryError):
        sink.lookup(value)


def test_lock_and_existing_root_fail_without_mutation(sink, tmp_path):
    descriptor = (sink.root / "history.json").read_bytes()
    with pytest.raises((history.HistoryError, BlockingIOError)):
        history.IsolatedNativeDuckLakeHistory(sink.root)
    with pytest.raises(FileExistsError):
        history.IsolatedNativeDuckLakeHistory(sink.root, create=True)
    assert (sink.root / "history.json").read_bytes() == descriptor
    script = "from ipfs_datasets_py.ducklake.autoencoder_history import IsolatedNativeDuckLakeHistory; IsolatedNativeDuckLakeHistory(__import__('sys').argv[1])"
    result = subprocess.run([sys.executable, "-c", script, str(sink.root)], capture_output=True, timeout=20, env={**os.environ, "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1", "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0"})
    assert result.returncode != 0
    assert b"BlockingIOError" in result.stderr


def test_descriptor_and_path_alias_reject(tmp_path):
    root = tmp_path / "history"
    with history.IsolatedNativeDuckLakeHistory(root, create=True):
        pass
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(history.HistoryError, match="aliased"):
        history.IsolatedNativeDuckLakeHistory(alias)
    descriptor = root / "history.json"
    original = descriptor.read_bytes()
    descriptor.write_bytes(original + b" ")
    with pytest.raises(history.HistoryError, match="descriptor"):
        history.IsolatedNativeDuckLakeHistory(root)
    descriptor.write_bytes(original)
    outside = tmp_path / "outside"
    outside.write_bytes(b"untouched")
    (root / "data" / "foreign.parquet").symlink_to(outside)
    with pytest.raises(history.HistoryError, match="aliases"):
        history.IsolatedNativeDuckLakeHistory(root)
    assert outside.read_bytes() == b"untouched"


def test_path_replacement_and_close_fail_closed(sink, tmp_path):
    (sink.root / "owner.lock").rename(sink.root / "old.lock")
    (sink.root / "owner.lock").write_bytes(b"")
    with pytest.raises(history.HistoryError, match="lock changed"):
        sink.lookup(batch(tmp_path))
    sink.close()
    sink.close()
    with pytest.raises(history.HistoryError, match="closed"):
        sink.lookup(batch(tmp_path))


def test_cap_part_of_identity_and_no_write_when_reserve_cannot_fit(tmp_path):
    root = tmp_path / "history"
    with history.IsolatedNativeDuckLakeHistory(root, create=True, max_history_bytes=4 * 1024 * 1024) as sink:
        assert sink.identity["max_history_bytes"] == 4 * 1024 * 1024
        with pytest.raises(history.HistoryError, match="reserve"):
            sink.append(batch(tmp_path))
        assert sink._connection.execute("SELECT count(*) FROM history.events").fetchone() == (0,)
    with pytest.raises(history.HistoryError, match="descriptor"):
        history.IsolatedNativeDuckLakeHistory(root)


@pytest.mark.parametrize("flags", [{"production": True}, {"production": 1}, {"create": 1}, {"max_history_bytes": True}, {"max_history_bytes": 0}])
def test_production_and_invalid_flags_reject_before_create(tmp_path, flags):
    root = tmp_path / "history"
    with pytest.raises(history.HistoryError):
        history.IsolatedNativeDuckLakeHistory(root, **flags)
    assert not root.exists()


def test_runtime_and_extension_drift_reject(tmp_path, monkeypatch):
    import duckdb
    monkeypatch.setattr(duckdb, "__version__", "wrong")
    with pytest.raises(history.HistoryError, match="pinned runtime"):
        history.IsolatedNativeDuckLakeHistory(tmp_path / "bad-runtime", create=True)
    monkeypatch.undo()
    original = history._read
    def changed(path, maximum):
        raw = original(path, maximum)
        return raw + b"wrong" if str(path).endswith("quack.duckdb_extension") else raw
    monkeypatch.setattr(history, "_read", changed)
    with pytest.raises(history.HistoryError, match="digest"):
        history.IsolatedNativeDuckLakeHistory(tmp_path / "bad-extension", create=True)


def test_aggregate_string_limit_rejected_before_whole_serialization(tmp_path, monkeypatch):
    original = history._json
    observed = []
    def observed_json(value):
        observed.append(value)
        return original(value)
    monkeypatch.setattr(history, "_json", observed_json)
    with pytest.raises(history.HistoryError, match="aggregate"):
        batch(tmp_path, event(payload={str(index): "x" * 300_000 for index in range(4)}))
    assert all("events" not in value for value in observed)


def test_final_encoded_limit_includes_escaping(tmp_path):
    with pytest.raises(history.HistoryError, match="exceeds|byte bound"):
        batch(tmp_path, event(payload={"escaped": "\x01" * 200_000}))


@pytest.mark.parametrize("value", [True, 1, "2026-09-25T00:00:00Z", float("inf")])
def test_created_at_exact_finite_registry_double(tmp_path, value):
    with pytest.raises(history.HistoryError, match="DOUBLE"):
        batch(tmp_path, event(created_at=value))


@pytest.mark.parametrize("entry", ["history.ducklake", "data"])
def test_catalog_and_data_path_replacement_reject(sink, tmp_path, entry):
    original = sink.root / entry
    saved = sink.root / (entry + ".previous")
    original.rename(saved)
    try:
        if entry == "data":
            original.mkdir()
        else:
            original.write_bytes(b"replacement")
        with pytest.raises(history.HistoryError, match="path identity"):
            sink.lookup(batch(tmp_path))
    finally:
        if original.is_dir():
            original.rmdir()
        else:
            original.unlink()
        saved.rename(original)


def test_inherited_pid_cannot_query_or_close(sink, tmp_path, monkeypatch):
    original = os.getpid()
    connection = sink._connection
    lock_fd = sink._fd
    with monkeypatch.context() as patch:
        patch.setattr(history.os, "getpid", lambda: original + 1)
        for action in (lambda: sink.lookup(batch(tmp_path)), lambda: sink.append(batch(tmp_path)), sink.close):
            with pytest.raises(history.HistoryError, match="inherited"):
                action()
        assert sink._connection is connection
        assert sink._fd == lock_fd
    assert sink.lookup(batch(tmp_path)) is None


def test_exception_before_commit_rolls_back_all_rows(sink, tmp_path):
    connection = sink._connection
    class FailCommitMessage:
        def execute(self, sql, *args):
            if sql.startswith("CALL history.set_commit_message"):
                raise RuntimeError("fixture before commit")
            return connection.execute(sql, *args)
        def executemany(self, *args):
            return connection.executemany(*args)
        def close(self):
            return connection.close()
    sink._connection = FailCommitMessage()
    with pytest.raises(RuntimeError, match="before commit"):
        sink.append(batch(tmp_path))
    sink._connection = connection
    assert sink.lookup(batch(tmp_path)) is None
    for table in ("sources", "events", "commits"):
        assert connection.execute(f"SELECT count(*) FROM history.{table}").fetchone() == (0,)


def test_post_commit_corruption_does_not_return_receipt(sink, tmp_path, monkeypatch):
    original = sink._lookup
    calls = []
    def corrupt_after_commit(value):
        calls.append(1)
        if len(calls) == 2:
            sink._connection.execute("UPDATE history.events SET event_json='{}'")
        return original(value)
    monkeypatch.setattr(sink, "_lookup", corrupt_after_commit)
    with pytest.raises(history.HistoryError, match="conflict"):
        sink.append(batch(tmp_path))


def test_namespace_hardlinks_and_size_cap_reject(sink, tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(b"external")
    os.link(outside, sink.root / "hardlinked")
    with pytest.raises(history.HistoryError, match="hard-linked"):
        sink.lookup(batch(tmp_path))
    (sink.root / "hardlinked").unlink()
    with (sink.root / "oversized").open("wb") as handle:
        handle.truncate(sink._max_history_bytes)
    with pytest.raises(history.HistoryError, match="byte cap"):
        sink.lookup(batch(tmp_path))


@pytest.mark.parametrize("phase", ["after_commit", "before_commit"])
def test_actual_sigkill_then_fresh_process_reopen(tmp_path, phase):
    root = tmp_path / "history"
    value = batch(tmp_path)
    input_path = tmp_path / "batch.json"
    input_path.write_bytes(history._json(value))
    child = r'''
import json, os, signal, sys
from pathlib import Path
from ipfs_datasets_py.ducklake.autoencoder_history import IsolatedNativeDuckLakeHistory
root, input_path, phase = sys.argv[1:]
sink = IsolatedNativeDuckLakeHistory(root, create=True)
value = json.loads(Path(input_path).read_bytes())
connection = sink._connection
if phase == "before_commit":
    class DieBeforeCommit:
        def execute(self, sql, *args):
            if sql == "COMMIT":
                os.kill(os.getpid(), signal.SIGKILL)
            return connection.execute(sql, *args)
        def executemany(self, *args):
            return connection.executemany(*args)
        def close(self):
            return connection.close()
    sink._connection = DieBeforeCommit()
receipt = sink.append(value)
print(json.dumps(receipt), flush=True)
os.kill(os.getpid(), signal.SIGKILL)
'''
    killed = subprocess.run([sys.executable, "-c", child, str(root), str(input_path), phase], capture_output=True, text=True, timeout=20, env={**os.environ, "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1", "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0"})
    assert killed.returncode == -9, killed.stderr
    with history.IsolatedNativeDuckLakeHistory(root) as reopened:
        if phase == "after_commit":
            receipt = json.loads(killed.stdout)
            assert reopened.lookup(value) == receipt
            assert reopened.append(value) == receipt
            assert reopened._connection.execute("SELECT count(*) FROM history.events").fetchone() == (1,)
            assert reopened._connection.execute("SELECT count(*) FROM history.commits").fetchone() == (1,)
        else:
            assert reopened.lookup(value) is None
            for table in ("sources", "events", "commits"):
                assert reopened._connection.execute(f"SELECT count(*) FROM history.{table}").fetchone() == (0,)
            assert reopened.append(value)["event_count"] == 1
