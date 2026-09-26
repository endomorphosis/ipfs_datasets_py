"""Storage probes distinguish real disposable capabilities from qualification."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "autoencoder_storage_probe", ROOT / "scripts/ops/legal_ir/probe_autoencoder_storage.py"
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def test_file_reopen_and_sigkill_recover_only_committed_rows() -> None:
    duckdb = pytest.importorskip("duckdb")
    if duckdb.__version__ != probe._lock_profile()["profile.duckdb_version"]:
        pytest.skip("requires the workspace's pinned DuckDB")
    receipt = probe.run_probe()
    assert receipt["status"] == "passed"
    assert receipt["probes"]["duckdb_close_reopen"]["committed_rows_after_reopen"] == 1
    recovery = receipt["probes"]["duckdb_process_kill"]
    assert recovery["writer_exit_signal"] == "SIGKILL"
    assert recovery["wal_bytes_before_kill"] > 0
    assert recovery["committed_rows_recovered"] == 1
    assert recovery["uncommitted_rows_recovered"] == 0
    assert receipt["probes"]["quack"]["status"] == "not_run"
    assert receipt["probes"]["ducklake"]["status"] == "not_run"
    assert receipt["scratch_removed"] is True
    for field in (
        "admitted", "runtime_qualified", "production_activation",
        "training_integration_qualified", "network_install", "autoload",
        "weights_accessed", "logic_modules_imported",
    ):
        assert receipt[field] is False


def test_version_mismatch_never_runs_a_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "inventory", lambda: {"duckdb_matches_lock": False})
    monkeypatch.setattr(probe, "_run_worker", lambda *a, **k: pytest.fail("ran mismatched runtime"))
    monkeypatch.setattr(probe, "_process_kill", lambda *a, **k: pytest.fail("ran mismatched runtime"))
    receipt = probe.run_probe(native=True)
    assert receipt["status"] == "incomplete"
    assert all(row["status"] == "unavailable" for row in receipt["probes"].values())
    assert receipt["scratch_removed"] is True


def test_extension_mismatch_blocks_native_load(monkeypatch: pytest.MonkeyPatch) -> None:
    observed = {
        "duckdb_matches_lock": True,
        "extensions": {name: {"matches_lock": name != "quack"} for name in probe.EXTENSIONS},
    }
    monkeypatch.setattr(probe, "inventory", lambda: observed)
    connection = SimpleNamespace(execute=lambda *_: pytest.fail("loaded mismatched extension"))
    with pytest.raises(RuntimeError, match="quack installed artifact does not match"):
        probe._load_pinned_extensions(connection)


def test_worker_cannot_claim_existing_unowned_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="disposable scratch"):
        probe._owned_scratch(tmp_path, "irrelevant")
    owned = tmp_path / "autoencoder-storage-probe-guard"
    owned.mkdir()
    (owned / ".probe-owner").write_text("actual-owner-token")
    with pytest.raises(ValueError, match="token mismatch"):
        probe._owned_scratch(owned, "wrong-owner-token")


def test_worker_nonzero_exit_cannot_report_passed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        probe.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=7, stdout=json.dumps({"status": "passed"})),
    )
    result = probe._run_worker("quack", tmp_path, "unused", 1)
    assert result["status"] == "failed"
    assert result["worker_exit_code"] == 7


def test_receipt_write_never_overwrites(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text("original evidence")
    monkeypatch.setattr(probe, "run_probe", lambda **_: {"status": "passed"})
    with pytest.raises(FileExistsError):
        probe.main(["--output", str(receipt)])
    assert receipt.read_text() == "original evidence"


@pytest.mark.skipif(
    os.environ.get("IPFS_DATASETS_RUN_NATIVE_STORAGE_PROBE") != "1",
    reason="native extension/loopback probes are explicitly enabled",
)
def test_installed_native_wire_and_ducklake_roundtrip() -> None:
    pytest.importorskip("duckdb")
    reason = probe.native_unavailable_reason(probe.inventory())
    if reason:
        pytest.skip(reason)
    receipt = probe.run_probe(native=True)
    assert receipt["status"] == "passed", receipt["probes"]
    quack = receipt["probes"]["quack"]
    assert quack["transport"] == "native_quack_query"
    assert quack["denials"] == {"unlisted_query": True, "wrong_token": True}
    assert quack["listener_stopped"] is True
    lake = receipt["probes"]["ducklake"]
    assert lake["rows_after_reopen"] == 1
    assert lake["parquet_file_count"] >= 1
    assert lake["automatic_migration"] is False
    assert lake["catalog_version"] == "1.0"
    assert receipt["runtime_qualified"] is False
    assert receipt["admitted"] is False
    assert receipt["scratch_removed"] is True
