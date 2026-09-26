"""Exact journal recovery with isolated registries; no daemon/model execution."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_operation_journal as module


Journal = module.DurableDaemonOperationJournal
Error = module.DaemonOperationJournalError
BINDING = {"schema": "synthetic-daemon-request", "request_sha256": "a" * 64, "run_id": "run-1"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def create_payload(version="sha256:" + "b" * 64, run_id="run-1"):
    return {"run_id": run_id, "variant_id": "fixture", "base_version_id": version,
            "spec": {"fixture": True, "unicode": "法", "negative_zero": -0.0}}


class MemoryLedger:
    """Only journal I/O tests use this explicit unit-only registry stand-in."""

    def __init__(self):
        self.calls = []
        self.records = {}

    def resolve_operation(self, operation_id, command, payload):
        self.calls.append(("resolve", operation_id, command, copy.deepcopy(payload)))
        record = self.records.get(operation_id)
        if record is None:
            return None
        assert record[:2] == (command, payload)
        return copy.deepcopy(record[2])

    def create_run(self, operation_id, **payload):
        self.calls.append(("send", operation_id, "CreateRun", copy.deepcopy(payload)))
        receipt = {"schema": "ipfs_datasets_py/autoencoder-control@1", "operation_id": operation_id,
                   "command": "CreateRun", "admitted": False, "run_id": payload["run_id"], "status": "queued"}
        self.records[operation_id] = ("CreateRun", copy.deepcopy(payload), receipt)
        return copy.deepcopy(receipt)


def seed(registry, tmp_path):
    registry.register_variant("seed-variant", "fixture", {"synthetic": True})
    path = tmp_path / "base.json"
    path.write_bytes(b'{"synthetic_state":"base"}')
    artifact = registry.stage_artifact(path)
    version = registry.register_version("seed-version", "fixture", artifact, metadata={"fixture": True})
    return version["version_id"], artifact


def test_real_registry_all_commands_and_detached_inspection(tmp_path):
    path = tmp_path / "journal.json"
    with AutoencoderRegistry(tmp_path / "registry.db", tmp_path / "cas") as registry:
        version, artifact = seed(registry, tmp_path)
        with Journal(path, BINDING) as journal:
            created = journal.invoke(registry, "create_run", "CreateRun", create_payload(version))
            assert created["status"] == "queued"
            lease = journal.invoke(registry, "claim", "ClaimRun", {
                "run_id": "run-1", "worker_id": "fixture-worker", "lease_seconds": 300,
            })["lease"]
            renewed = journal.invoke(registry, "renew-0001", "RenewLease", {
                "lease": lease, "lease_seconds": 300,
            })["lease"]
            assert renewed["fence"] == lease["fence"]
            complete = journal.invoke(registry, "complete", "CompleteRun", {
                "lease": renewed, "artifact": artifact, "result": {"admitted": False, "fixture": True},
            })
            assert complete["promoted"] is False
            assert registry.get_version(complete["version_id"])["parent_version_id"] == version
            journal.invoke(registry, "create-second", "CreateRun", create_payload(version, "run-2"))
            second_lease = journal.invoke(registry, "claim-second", "ClaimRun", {
                "run_id": "run-2", "worker_id": "fixture-worker", "lease_seconds": 300,
            })["lease"]
            failed = journal.invoke(registry, "fail", "FailRun", {
                "lease": second_lease, "result": {"admitted": False, "error": "synthetic"},
            })
            assert failed["status"] == "failed"
            assert registry.resolve_head("fixture", "main") is None
            assert journal.pending() == {}
            assert len(journal.operations()) == 7
            records = journal.operations()
            records["complete"]["receipt"]["status"] = "forged"
            assert journal.receipt("complete") == complete
            binding = journal.binding
            binding["run_id"] = "changed"
            assert journal.binding == BINDING
            assert journal.receipt("unknown") is None
        assert json.loads(path.read_bytes())["schema_version"] == module.SCHEMA_VERSION


def test_commit_then_response_loss_resolves_same_operation_without_resend(tmp_path):
    with AutoencoderRegistry(tmp_path / "registry.db", tmp_path / "cas") as registry:
        version, _ = seed(registry, tmp_path)

        class LostResponse:
            sends = 0

            def resolve_operation(self, *args):
                return registry.resolve_operation(*args)

            def create_run(self, *args, **kwargs):
                self.sends += 1
                registry.create_run(*args, **kwargs)
                raise OSError("synthetic response lost after commit")

        transport = LostResponse()
        with Journal(tmp_path / "journal.json", BINDING) as journal:
            receipt = journal.invoke(transport, "create_run", "CreateRun", create_payload(version))
            assert receipt["status"] == "queued"
            assert journal.invoke(transport, "create_run", "CreateRun", create_payload(version)) == receipt
            assert transport.sends == 1
            assert len(registry.pending_outbox("ducklake")) == 1  # seed version only


def test_pending_completion_recovers_after_owner_restart_and_missing_artifact(tmp_path):
    path, db, cas = tmp_path / "journal.json", tmp_path / "registry.db", tmp_path / "cas"
    loss = RuntimeError("response and follow-up lookup lost")
    with AutoencoderRegistry(db, cas) as registry:
        version, artifact = seed(registry, tmp_path)
        with Journal(path, BINDING) as journal:
            journal.invoke(registry, "create_run", "CreateRun", create_payload(version))
            lease = journal.invoke(registry, "claim", "ClaimRun", {
                "run_id": "run-1", "worker_id": "fixture", "lease_seconds": 300,
            })["lease"]
            payload = {"lease": lease, "artifact": artifact, "result": {"admitted": False}}

            class AmbiguousCompletion:
                committed = False

                def resolve_operation(self, *args):
                    if self.committed:
                        raise OSError("synthetic lookup unavailable")
                    return registry.resolve_operation(*args)

                def complete_run(self, *args, **kwargs):
                    registry.complete_run(*args, **kwargs)
                    self.committed = True
                    raise loss

            with pytest.raises(RuntimeError) as failure:
                journal.invoke(AmbiguousCompletion(), "complete", "CompleteRun", payload)
            assert failure.value is loss
            operation = journal.pending()["complete"]
            expected = registry.resolve_operation(operation["operation_id"], "CompleteRun", payload)
            registry.artifact_path(artifact).unlink()
    with AutoencoderRegistry(db, cas) as registry:
        assert registry.owner_generation > lease["owner_generation"]
        with Journal(path, BINDING) as journal:
            assert journal.invoke(registry, "complete", "CompleteRun", payload) == expected
            assert journal.pending() == {}
            assert journal.receipt("complete") == expected
            # Historical receipt replay remains read-only even without bytes.
            assert journal.invoke(registry, "complete", "CompleteRun", payload) == expected
            assert len(registry.pending_outbox("ducklake")) == 2
            assert registry.resolve_head("fixture", "main") is None


def test_uncommitted_old_lease_is_not_reauthorized_on_restart(tmp_path):
    db, cas, path = tmp_path / "registry.db", tmp_path / "cas", tmp_path / "journal.json"
    with AutoencoderRegistry(db, cas) as registry:
        version, artifact = seed(registry, tmp_path)
        with Journal(path, BINDING) as journal:
            journal.invoke(registry, "create_run", "CreateRun", create_payload(version))
            lease = journal.invoke(registry, "claim", "ClaimRun", {
                "run_id": "run-1", "worker_id": "fixture", "lease_seconds": 300,
            })["lease"]
            payload = {"lease": lease, "artifact": artifact, "result": {"admitted": False}}

            class Unavailable:
                def resolve_operation(self, *args):
                    raise OSError("offline before send")

            with pytest.raises(OSError, match="offline"):
                journal.invoke(Unavailable(), "complete", "CompleteRun", payload)
            operation_id = journal.pending()["complete"]["operation_id"]
    with AutoencoderRegistry(db, cas) as registry, Journal(path, BINDING) as journal:
        with pytest.raises(RegistryError, match="stale"):
            journal.invoke(registry, "complete", "CompleteRun", payload)
        assert journal.pending()["complete"]["operation_id"] == operation_id
        assert registry.get_run("run-1")["attempt"] == 1


def test_intent_is_fsynced_before_dispatch_and_receipt_after(tmp_path, monkeypatch):
    path = tmp_path / "journal.json"
    calls = []
    original = module.os.fsync

    def sync(fd):
        calls.append("fsync")
        return original(fd)

    monkeypatch.setattr(module.os, "fsync", sync)

    class InspectingLedger(MemoryLedger):
        def create_run(self, operation_id, **payload):
            saved = json.loads(path.read_bytes())["operations"]["create_run"]
            assert saved == {"operation_id": operation_id, "command": "CreateRun", "payload": payload, "receipt": None}
            assert calls.count("fsync") >= 4  # initial+intent file and directory
            calls.append("send")
            return super().create_run(operation_id, **payload)

    with Journal(path, BINDING) as journal:
        result = journal.invoke(InspectingLedger(), "create_run", "CreateRun", create_payload())
        assert json.loads(path.read_bytes())["operations"]["create_run"]["receipt"] == result
        assert calls[-2:] == ["fsync", "fsync"]
        assert calls.count("send") == 1


@pytest.mark.parametrize("change", ["payload", "command", "negative-zero-type"])
def test_changed_slot_conflicts_before_registry_lookup(tmp_path, change):
    ledger = MemoryLedger()
    with Journal(tmp_path / "journal.json", BINDING) as journal:
        payload = create_payload()
        journal.invoke(ledger, "create_run", "CreateRun", payload)
        before = len(ledger.calls)
        command = "CreateRun"
        if change == "payload":
            payload["spec"]["unicode"] = "different"
        elif change == "negative-zero-type":
            payload["spec"]["negative_zero"] = 0
        else:
            command, payload = "ClaimRun", {"run_id": "run-1", "worker_id": "fixture", "lease_seconds": 30}
        with pytest.raises(Error, match="conflict"):
            journal.invoke(ledger, "create_run", command, payload)
        assert len(ledger.calls) == before


def test_local_receipt_never_substitutes_for_registry_history(tmp_path):
    ledger = MemoryLedger()
    with Journal(tmp_path / "journal.json", BINDING) as journal:
        journal.invoke(ledger, "create_run", "CreateRun", create_payload())
        ledger.records.clear()
        before = len([row for row in ledger.calls if row[0] == "send"])
        with pytest.raises(Error, match="absent"):
            journal.invoke(ledger, "create_run", "CreateRun", create_payload())
        assert len([row for row in ledger.calls if row[0] == "send"]) == before


def test_metadata_and_binding_survive_restart_detached(tmp_path):
    path = tmp_path / "journal.json"
    metadata = {"lease": None, "argv": ["--synthetic", "法"], "zero": -0.0}
    with Journal(path, BINDING) as journal:
        journal.set_metadata("attempt", metadata)
        metadata["argv"].append("changed")
        assert journal.get_metadata("missing") is None
    with Journal(path, BINDING) as journal:
        assert journal.get_metadata("attempt")["argv"] == ["--synthetic", "法"]
        returned = journal.get_metadata("attempt")
        returned["argv"].clear()
        assert journal.get_metadata("attempt")["argv"]
    with pytest.raises(Error, match="binding"):
        Journal(path, {**BINDING, "run_id": "different"})


@pytest.mark.parametrize("raw", [b"", b"{", b"[]", b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'\xff', b'{}\n'])
def test_invalid_journal_never_resets_or_rewrites(tmp_path, raw):
    path = tmp_path / "journal.json"
    path.write_bytes(raw)
    with pytest.raises(Error):
        Journal(path, BINDING)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("change", ["extra", "unknown-schema", "bad-operation-id", "command-extra", "bad-receipt"])
def test_closed_journal_schema_and_operation_bindings(tmp_path, change):
    path = tmp_path / "journal.json"
    with Journal(path, BINDING) as journal:
        journal.invoke(MemoryLedger(), "create_run", "CreateRun", create_payload())
    data = json.loads(path.read_bytes())
    if change == "extra":
        data["extra"] = 1
    elif change == "unknown-schema":
        data["schema_version"] = "future"
    elif change == "bad-operation-id":
        data["operations"]["create_run"]["operation_id"] = "another"
    elif change == "command-extra":
        data["operations"]["create_run"]["payload"]["extra"] = False
    else:
        data["operations"]["create_run"]["receipt"]["admitted"] = True
    path.write_bytes(canonical(data))
    with pytest.raises(Error):
        Journal(path, BINDING)


@pytest.mark.parametrize("mode", ["journal", "parent", "lock", "hardlink", "directory", "fifo"])
def test_no_symlink_alias_or_nonregular_files(tmp_path, mode):
    parent = tmp_path / "real"
    parent.mkdir()
    path = parent / "journal.json"
    other = tmp_path / "other"
    other.write_bytes(b"untouched")
    if mode == "journal":
        path.symlink_to(other)
    elif mode == "parent":
        alias = tmp_path / "alias"
        alias.symlink_to(parent, target_is_directory=True)
        path = alias / "journal.json"
    elif mode == "lock":
        (parent / ".journal.json.lock").symlink_to(other)
    elif mode == "hardlink":
        os.link(other, path)
    elif mode == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    with pytest.raises(Error):
        Journal(path, BINDING)
    assert other.read_bytes() == b"untouched"


@pytest.mark.parametrize("replacement", ["same-bytes", "changed-bytes", "lock", "parent"])
def test_persistent_file_or_lock_replacement_detected_before_dispatch(tmp_path, replacement):
    parent = tmp_path / "owner"
    parent.mkdir()
    path = parent / "journal.json"
    ledger = MemoryLedger()
    with Journal(path, BINDING) as journal:
        if replacement == "parent":
            parent.rename(tmp_path / "old")
            parent.mkdir()
        elif replacement == "lock":
            lock = parent / ".journal.json.lock"
            lock.unlink()
            lock.touch()
        else:
            new = parent / "replacement"
            new.write_bytes(path.read_bytes() if replacement == "same-bytes" else b"changed")
            new.replace(path)
        with pytest.raises(Error):
            journal.invoke(ledger, "create_run", "CreateRun", create_payload())
        assert ledger.calls == []


def test_lock_is_exclusive_in_same_and_separate_process_and_released(tmp_path):
    path = tmp_path / "journal.json"
    code = '''
import sys
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_operation_journal import DurableDaemonOperationJournal, DaemonOperationJournalError
try:
    with DurableDaemonOperationJournal(sys.argv[1], {}):
        pass
except DaemonOperationJournalError:
    sys.exit(17)
'''
    env = {**os.environ, "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1", "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0"}
    with Journal(path, {}) as journal:
        with pytest.raises(Error, match="locked"):
            Journal(path, {})
        child = subprocess.run([sys.executable, "-c", code, str(path)], env=env, capture_output=True, timeout=30)
        assert child.returncode == 17, child.stderr.decode()
        assert journal.binding == {}
    child = subprocess.run([sys.executable, "-c", code, str(path)], env=env, capture_output=True, timeout=30)
    assert child.returncode == 0, child.stderr.decode()


@pytest.mark.parametrize("command,payload", [
    ("PromoteHead", {}), ("CreateRun", {**create_payload(), "extra": True}),
    ("ClaimRun", {"run_id": "run-1", "worker_id": "w"}),
    ("ClaimRun", {"run_id": "run-1", "worker_id": "w", "lease_seconds": True}),
    ("ClaimRun", {"run_id": "run-1", "worker_id": "w", "lease_seconds": float("nan")}),
    ("CreateRun", {**create_payload(), "spec": {"tuple": (1, 2)}}),
    ("CreateRun", {**create_payload(), "spec": {1: "bad key"}}),
])
def test_bad_commands_reject_before_intent_or_registry(tmp_path, command, payload):
    ledger = MemoryLedger()
    with Journal(tmp_path / "journal.json", BINDING) as journal:
        before = journal.path.read_bytes()
        with pytest.raises(Error):
            journal.invoke(ledger, "invalid", command, payload)
        assert journal.path.read_bytes() == before
        assert ledger.calls == []


def test_bounds_fail_before_mutation_and_preserve_existing_journal(tmp_path, monkeypatch):
    ledger = MemoryLedger()
    with Journal(tmp_path / "journal.json", BINDING) as journal:
        before = journal.path.read_bytes()
        payload = create_payload()
        payload["spec"]["oversized"] = "x" * module.MAX_VALUE_BYTES
        with pytest.raises(Error, match="bound"):
            journal.invoke(ledger, "large", "CreateRun", payload)
        with pytest.raises(Error, match="bound"):
            journal.set_metadata("large", "x" * module.MAX_VALUE_BYTES)
        nested = None
        for _ in range(module.MAX_JSON_DEPTH + 1):
            nested = [nested]
        with pytest.raises(Error, match="structural"):
            journal.set_metadata("deep", nested)
        monkeypatch.setattr(module, "MAX_JOURNAL_BYTES", len(before) + 1024)
        with pytest.raises(Error, match="receipt capacity"):
            journal.invoke(ledger, "small", "CreateRun", create_payload())
        assert journal.path.read_bytes() == before
        assert ledger.calls == []


def test_operation_count_bound(tmp_path, monkeypatch):
    with Journal(tmp_path / "journal.json", BINDING) as journal:
        ledger = MemoryLedger()
        journal.invoke(ledger, "first", "CreateRun", create_payload())
        monkeypatch.setattr(module, "MAX_OPERATIONS", 1)
        before = len(ledger.calls)
        with pytest.raises(Error, match="count"):
            journal.invoke(ledger, "second", "CreateRun", create_payload(run_id="run-2"))
        assert len(ledger.calls) == before


def test_fsync_failure_before_send_keeps_original_and_closes_fail_closed(tmp_path, monkeypatch):
    path = tmp_path / "journal.json"
    ledger = MemoryLedger()
    with Journal(path, BINDING) as journal:
        original = path.read_bytes()
        failure = OSError("synthetic fsync failure")

        def fail(fd):
            raise failure

        monkeypatch.setattr(module.os, "fsync", fail)
        with pytest.raises(OSError) as caught:
            journal.invoke(ledger, "create_run", "CreateRun", create_payload())
        assert caught.value is failure
        assert path.read_bytes() == original
        assert ledger.calls == []
        assert list(tmp_path.glob("*.tmp")) == []
        with pytest.raises(Error, match="unavailable"):
            journal.operations()


def test_closed_session_rejects_use_and_close_is_idempotent(tmp_path):
    journal = Journal(tmp_path / "journal.json", BINDING)
    journal.close()
    journal.close()
    with pytest.raises(Error, match="closed"):
        journal.invoke(MemoryLedger(), "create_run", "CreateRun", create_payload())
