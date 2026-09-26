"""Real owner plus isolated native DuckLake delivery and crash recovery.

Only small synthetic checkpoint bytes and metadata are used. Fault wrappers
interrupt real calls; no fake storage sink, training, HF operation, or production
DuckLake activation is exercised or claimed. Installed pinned extensions only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_ducklake import HistoryDeliveryError, deliver_ducklake_history
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.duckdb_control.contracts import canonical_json_bytes
from ipfs_datasets_py.ducklake.autoencoder_history import HistoryError, IsolatedNativeDuckLakeHistory
from tests.unit.duckdb_control.test_autoencoder_registry import Clock, seed, staged, variant, run_spec


class SimulatedCrash(BaseException):
    """Bypass response reconciliation to model process loss at one boundary."""


@pytest.fixture
def history(tmp_path):
    clock = Clock()
    registry = AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts", clock=clock)
    sink = None
    try:
        sink = IsolatedNativeDuckLakeHistory(tmp_path / "history", create=True)
        yield SimpleNamespace(root=tmp_path, registry=registry, sink=sink, clock=clock)
    finally:
        if sink is not None:
            sink.close()
        registry.close()


def deliver(value, name="batch", **options):
    return deliver_ducklake_history(value.registry, value.sink, source_id="fixture-owner",
                                    output_directory=value.root / name, **options)


def journal(value, name="batch"):
    return json.loads((value.root / name / "delivery.json").read_bytes())


def lake_rows(sink, table, column):
    # Read real materialized metadata, independently of the append receipt.
    return [json.loads(row[0]) for row in sink._connection.execute(
        f"SELECT {column} FROM history.{table}").fetchall()]


def status(value, event_id):
    return value.registry.get_outbox_event("ducklake", event_id)["status"]


def test_real_version_and_variant_mirror_leaves_head_hf_and_cas_untouched(history):
    value = history
    base = seed(value.registry, value.root)
    value.registry.initialize_head("initial-head", "english", "main", base["version_id"])
    plan = staged(value.registry, value.root, "offline-plan-fixture")
    value.registry.enqueue_publication("publication-intent", base["version_id"], plan)
    head_before = value.registry.resolve_head("english", "main")
    hf_before = value.registry.pending_outbox("huggingface")
    version = value.registry.get_version(base["version_id"])
    original = value.registry.artifact_path(version["artifact"])
    inode, raw = original.stat().st_ino, original.read_bytes()
    result = deliver(value)
    # Head initialization is itself an immutable DuckLake outbox event.
    assert result["status"] == "acknowledged" and result["event_count"] == 2
    assert result["admitted"] is result["production_activated"] is False
    receipt = result["commit"]
    assert receipt["scope"] == "isolated_history" and receipt["snapshot_id"] > 0
    row, = [row for row in lake_rows(value.sink, "events", "event_json") if row["event_id"] == base["event_id"]]
    owner_event = value.registry.get_outbox_event("ducklake", base["event_id"])
    assert row == {key: owner_event[key] for key in ("event_id", "kind", "payload", "created_at")} | {
        "version": version, "variant": value.registry.get_variant("english")}
    assert type(row["created_at"]) is float and row["created_at"] == value.clock.now
    assert owner_event["receipt"] == receipt
    assert value.registry.pending_outbox("ducklake") == []
    assert value.registry.pending_outbox("huggingface") == hf_before
    assert value.registry.resolve_head("english", "main") == head_before
    assert original.read_bytes() == raw and original.stat().st_ino == inode
    parquet = list((value.root / "history/data").rglob("*.parquet"))
    assert parquet and all(path.stat().st_ino != inode for path in parquet)
    assert not any(path.read_bytes() == raw for path in parquet)
    assert deliver(value) == result
    assert len(lake_rows(value.sink, "commits", "batch_json")) == 1


def test_source_namespaces_disambiguate_identical_event_ids_and_refuse_rebinding(history):
    first = seed(history.registry, history.root)
    first_result = deliver(history)
    other_root = history.root / "second-owner"
    other_root.mkdir()
    with AutoencoderRegistry(other_root / "owner.duckdb", other_root / "artifacts", clock=history.clock) as other:
        second = seed(other, other_root)
        assert second["event_id"] == first["event_id"]
        with pytest.raises(HistoryError, match="source namespace binding conflict"):
            deliver_ducklake_history(other, history.sink, source_id="fixture-owner",
                                    output_directory=history.root / "wrong-source")
        assert other.get_outbox_event("ducklake", second["event_id"])["status"] != "acknowledged"
        # The failed delivery's existing claim is recovered from its immutable
        # journal only. A different source uses a new journal after lease expiry.
        history.clock.now += 301
        result = deliver_ducklake_history(other, history.sink, source_id="second-fixture-owner",
                                         output_directory=history.root / "second-source")
        assert result["status"] == "acknowledged"
        assert result["commit"]["batch_id"] != first_result["commit"]["batch_id"]
        events = history.sink._connection.execute("SELECT source_id,event_id FROM history.events ORDER BY source_id").fetchall()
        assert events == [("fixture-owner", first["event_id"]), ("second-fixture-owner", first["event_id"])]
        assert len(lake_rows(history.sink, "sources", "source_json")) == 2


def test_batch_limit_and_empty_queue_have_no_implicit_next_batch(history):
    for limit in (0, 11, True, 1.0):
        with pytest.raises(HistoryDeliveryError, match="at most ten"):
            deliver(history, name="invalid", limit=limit)
    assert not (history.root / "invalid").exists()
    empty = deliver(history, name="empty")
    assert empty["status"] == "empty" and empty["event_count"] == 0
    for index in range(11):
        seed(history.registry, history.root, name=f"variant-{index}")
    assert deliver(history, name="empty") == empty
    first = deliver(history, name="first-ten")
    assert first["event_count"] == 10 and len(history.registry.pending_outbox("ducklake")) == 1
    assert deliver(history, name="first-ten") == first
    last = deliver(history, name="last-one")
    assert last["event_count"] == 1
    assert len(lake_rows(history.sink, "events", "event_json")) == 11
    assert len(lake_rows(history.sink, "commits", "batch_json")) == 2


@pytest.mark.parametrize("boundary", ["claim", "append", "ack"])
def test_lost_reply_resolves_real_committed_operation_once(history, monkeypatch, boundary):
    registered = seed(history.registry, history.root)
    owner, method = ((history.sink, "append") if boundary == "append" else
                     (history.registry, "claim_outbox" if boundary == "claim" else "ack_outbox"))
    original = getattr(owner, method)
    calls = []

    def lost_reply(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(result)
        if len(calls) == 1:
            raise OSError(f"fixture response lost after native {boundary} commit")
        return result

    monkeypatch.setattr(owner, method, lost_reply)
    result = deliver(history)
    assert result["status"] == "acknowledged" and len(calls) == 1
    assert status(history, registered["event_id"]) == "acknowledged"
    assert len(lake_rows(history.sink, "events", "event_json")) == 1
    assert len(lake_rows(history.sink, "commits", "batch_json")) == 1
    assert all(op["result"] is not None and not op["rejected"] for op in journal(history)["operations"])
    assert deliver(history) == result and len(calls) == 1


def test_partial_ack_then_owner_and_sink_reopen_resumes_exact_frozen_batch(history, monkeypatch):
    for index in range(3):
        seed(history.registry, history.root, name=f"original-{index}")
    original = history.registry.ack_outbox
    acknowledged = []

    def crash_before_second_ack(*args, **kwargs):
        if acknowledged:
            raise SimulatedCrash("fixture process lost before second acknowledgement")
        result = original(*args, **kwargs)
        acknowledged.append(result)
        return result

    monkeypatch.setattr(history.registry, "ack_outbox", crash_before_second_ack)
    with pytest.raises(SimulatedCrash):
        deliver(history)
    frozen = journal(history)
    assert frozen["commit"] is not None and frozen["result"] is None
    assert len(frozen["batch"]["events"]) == 3
    assert sum(status(history, row["event_id"]) == "acknowledged" for row in frozen["batch"]["events"]) == 1
    history.registry.close()
    history.sink.close()
    history.registry = AutoencoderRegistry(history.root / "owner.duckdb", history.root / "artifacts", clock=history.clock)
    history.sink = IsolatedNativeDuckLakeHistory(history.root / "history")
    try:
        later = seed(history.registry, history.root, name="new-after-restart")
        result = deliver(history)
        assert result["status"] == "acknowledged" and result["event_count"] == 3
        assert result["commit"] == frozen["commit"]
        assert journal(history)["batch"] == frozen["batch"]
        assert status(history, later["event_id"]) == "pending"
        assert len(lake_rows(history.sink, "events", "event_json")) == 3
        assert len(lake_rows(history.sink, "commits", "batch_json")) == 1
        assert any(op["rejected"] for op in journal(history)["operations"])
    finally:
        history.registry.close()
        history.sink.close()


def test_competing_lease_blocks_ack_and_expired_token_never_regains_authority(history, monkeypatch):
    registered = seed(history.registry, history.root)
    original = history.sink.append

    def crash_after_native_append(batch):
        original(batch)
        raise SimulatedCrash("fixture loss after native commit")

    monkeypatch.setattr(history.sink, "append", crash_after_native_append)
    with pytest.raises(SimulatedCrash):
        deliver(history, lease_seconds=10)
    old = history.registry.get_outbox_event("ducklake", registered["event_id"])["lease"]
    history.clock.now += 11
    competing = history.registry.claim_outbox_event("competing-claim", registered["event_id"], "ducklake",
                                                   "competing-consumer", lease_seconds=10)["delivery"]["lease"]
    with pytest.raises(RegistryError, match="already leased"):
        deliver(history, lease_seconds=10)
    assert status(history, registered["event_id"]) == "leased"
    with pytest.raises(RegistryError, match="stale|expired"):
        history.registry.ack_outbox("stale-ack", registered["event_id"], "ducklake", {}, old)
    assert history.registry.get_outbox_event("ducklake", registered["event_id"])["lease"] == competing
    history.clock.now += 11
    result = deliver(history, lease_seconds=10)
    assert result["status"] == "acknowledged"
    assert len(lake_rows(history.sink, "commits", "batch_json")) == 1


def test_failed_attempt_event_never_inherits_a_later_run_result(history):
    base = seed(history.registry, history.root)
    history.registry.create_run("create", "fixture-run", "english", base["version_id"], run_spec())
    lease = history.registry.claim_run("first-attempt", "fixture-run", "worker", lease_seconds=30)["lease"]
    failure = history.registry.fail_run("failed", lease, {"admitted": False, "error": "original failure"})
    second = history.registry.claim_run("second-attempt", "fixture-run", "worker", lease_seconds=30)["lease"]
    assert second["attempt"] == 2
    history.registry.complete_run("completed-second", second, staged(history.registry, history.root, "new-candidate"),
                                  {"admitted": False, "synthetic_fixture": True, "changed": True})
    result = deliver(history)
    assert result["event_count"] == 3
    rows = {row["event_id"]: row for row in lake_rows(history.sink, "events", "event_json")}
    failed = rows[failure["event_id"]]
    assert failed["payload"] == {"run_id": "fixture-run", "attempt": 1}
    assert failed["version"] is None and failed["variant"] is None
    assert "result" not in failed and "changed" not in failed["payload"]
    completed, = [row for row in rows.values() if row["kind"] == "candidate_durable"]
    assert completed["version"]["metadata"]["attempt"] == 2
    assert completed["version"]["metadata"]["result"]["changed"] is True


@pytest.mark.parametrize("completed", [False, True])
def test_native_sink_corruption_prevents_ack_or_successful_current_replay(history, monkeypatch, completed):
    registered = seed(history.registry, history.root)
    if completed:
        deliver(history)
    else:
        original = history.sink.append

        def crash_after_append(batch):
            original(batch)
            raise SimulatedCrash("fixture interruption before acknowledgement")

        monkeypatch.setattr(history.sink, "append", crash_after_append)
        with pytest.raises(SimulatedCrash):
            deliver(history)
    # A real unauthorized destination metadata edit in isolated scratch: a
    # surviving batch marker cannot by itself justify acknowledgement.
    history.sink._connection.execute("UPDATE history.events SET event_json='{}' WHERE event_id=?",
                                     [registered["event_id"]])
    with pytest.raises(HistoryError, match="event identity/content conflict"):
        deliver(history)
    assert status(history, registered["event_id"]) == ("acknowledged" if completed else "leased")


def test_no_fake_sink_or_changed_journal_binding_is_accepted(history):
    seed(history.registry, history.root)
    with pytest.raises(HistoryDeliveryError, match="exact owner"):
        deliver_ducklake_history(history.registry, object(), source_id="fixture-owner",
                                output_directory=history.root / "fake")
    assert not (history.root / "fake").exists()
    result = deliver(history)
    with pytest.raises(HistoryDeliveryError, match="binding"):
        deliver_ducklake_history(history.registry, history.sink, source_id="changed-source",
                                output_directory=history.root / "batch")
    assert journal(history)["result"] == result


@pytest.mark.parametrize("empty,field,value", [(False, "admitted", True), (False, "event_count", 99),
                                              (True, "admitted", True), (True, "event_count", 99)])
def test_terminal_result_is_verified_instead_of_trusted_from_journal(history, empty, field, value):
    if not empty:
        seed(history.registry, history.root)
    result = deliver(history)
    path = history.root / "batch/delivery.json"
    before = path.read_bytes()
    tampered = journal(history)
    tampered["result"][field] = value
    path.write_bytes(canonical_json_bytes(tampered) + b"\n")
    with pytest.raises(HistoryDeliveryError, match="result|completion"):
        deliver(history)
    assert journal(history)["result"][field] == value  # no silent repair/retry
    path.write_bytes(before)
    assert deliver(history) == result


def test_lost_claim_reply_cannot_be_changed_into_an_empty_frozen_batch(history, monkeypatch):
    registered = seed(history.registry, history.root)
    original = history.registry.claim_outbox

    def interrupted_claim(*args, **kwargs):
        original(*args, **kwargs)
        raise SimulatedCrash("fixture process lost after durable claim")

    monkeypatch.setattr(history.registry, "claim_outbox", interrupted_claim)
    with pytest.raises(SimulatedCrash):
        deliver(history)
    monkeypatch.setattr(history.registry, "claim_outbox", original)
    tampered = journal(history)
    assert tampered["claim"] is None and tampered["operations"][0]["result"] is None
    tampered["claim"] = {"deliveries": []}
    (history.root / "batch/delivery.json").write_bytes(canonical_json_bytes(tampered) + b"\n")
    with pytest.raises(HistoryDeliveryError, match="claim"):
        deliver(history)
    assert status(history, registered["event_id"]) == "leased"
    assert lake_rows(history.sink, "events", "event_json") == []
    assert lake_rows(history.sink, "commits", "batch_json") == []


def test_actual_sigkill_after_partial_ack_recovers_owner_and_native_sink_from_disk(tmp_path):
    clock = Clock()
    database, artifacts, lake = tmp_path / "owner.duckdb", tmp_path / "artifacts", tmp_path / "history"
    originals = []
    with AutoencoderRegistry(database, artifacts, clock=clock) as registry:
        expected_ids = []
        for index in range(3):
            version = seed(registry, tmp_path, name=f"crash-original-{index}")
            expected_ids.append(version["event_id"])
            artifact = registry.get_version(version["version_id"])["artifact"]
            path = registry.artifact_path(artifact)
            originals.append((path, path.stat().st_ino, path.read_bytes()))
    with IsolatedNativeDuckLakeHistory(lake, create=True):
        pass
    script = r'''
import os, signal, sys
from pathlib import Path
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.autoencoder_ducklake import deliver_ducklake_history
from ipfs_datasets_py.ducklake.autoencoder_history import IsolatedNativeDuckLakeHistory
from tests.unit.duckdb_control.test_autoencoder_registry import Clock
root = Path(sys.argv[1])
registry = AutoencoderRegistry(root / "owner.duckdb", root / "artifacts", clock=Clock())
sink = IsolatedNativeDuckLakeHistory(root / "history")
original = registry.ack_outbox
committed = []
def ack_then_kill(*args, **kwargs):
    if committed:
        print("SIGKILL_AFTER_ONE_DURABLE_ACK", flush=True)
        os.kill(os.getpid(), signal.SIGKILL)
        raise AssertionError("SIGKILL did not terminate the child")
    result = original(*args, **kwargs)
    committed.append(result)
    return result
registry.ack_outbox = ack_then_kill
deliver_ducklake_history(registry, sink, source_id="fixture-owner",
                        output_directory=root / "batch")
raise AssertionError("fault boundary did not run")
'''
    repository = Path(__file__).resolve().parents[3]
    env = {**os.environ, "PYTHONPATH": str(repository), "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
           "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0"}
    child = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=repository,
                           env=env, text=True, capture_output=True, timeout=30, check=False)
    assert child.returncode == -signal.SIGKILL, child.stdout + child.stderr
    assert "SIGKILL_AFTER_ONE_DURABLE_ACK" in child.stdout
    frozen = json.loads((tmp_path / "batch/delivery.json").read_bytes())
    assert frozen["result"] is None and frozen["commit"] is not None
    assert frozen["commit"]["event_ids"] == sorted(expected_ids)
    # Neither child connection was closed or given an exception unwind. These
    # new native connections must recover the durable transaction/journal state.
    with AutoencoderRegistry(database, artifacts, clock=clock) as registry:
        with IsolatedNativeDuckLakeHistory(lake) as sink:
            before = [registry.get_outbox_event("ducklake", event_id) for event_id in expected_ids]
            assert sum(event["status"] == "acknowledged" for event in before) == 1
            later = seed(registry, tmp_path, name="unrelated-after-kill")
            result = deliver_ducklake_history(registry, sink, source_id="fixture-owner",
                                              output_directory=tmp_path / "batch")
            assert result["status"] == "acknowledged" and result["event_count"] == 3
            assert result["commit"] == frozen["commit"]
            after = json.loads((tmp_path / "batch/delivery.json").read_bytes())
            assert after["batch"] == frozen["batch"]
            assert all(registry.get_outbox_event("ducklake", event_id)["receipt"] == frozen["commit"]
                       for event_id in expected_ids)
            assert registry.get_outbox_event("ducklake", later["event_id"])["status"] == "pending"
            assert len(lake_rows(sink, "events", "event_json")) == 3
            assert len(lake_rows(sink, "commits", "batch_json")) == 1
            assert sink.lookup(after["batch"]) == frozen["commit"]
    for path, inode, raw in originals:
        assert path.stat().st_ino == inode and path.read_bytes() == raw
