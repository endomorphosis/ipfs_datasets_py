"""Actual loopback Quack tests plus closed worker scope checks."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.autoencoder_quack import (
    RegistryQuackGateway,
    RegistryTransportClient,
    RegistryTransportError,
    WorkerScope,
    _connect_native,
    _envelope,
)


ROOT = Path(__file__).resolve().parents[3]
NATIVE = pytest.mark.skipif(
    os.environ.get("IPFS_DATASETS_RUN_NATIVE_STORAGE_PROBE") != "1",
    reason="native Quack listeners require explicit isolated-test opt-in",
)


def seed(registry: AutoencoderRegistry, root: Path) -> dict:
    source = root / "synthetic-state.json"
    source.write_text('{"fixture":true}')
    artifact = registry.stage_artifact(source)
    registry.register_variant("variant", "en", {"source_languages": ["en"]})
    version = registry.register_version("version", "en", artifact)
    for name in ("run-a", "run-b"):
        registry.create_run("create-" + name, name, "en", version["version_id"], {"fixture": True})
    return {"version_id": version["version_id"], "artifact": artifact}


@pytest.fixture
def owner(tmp_path: Path):
    pytest.importorskip("duckdb")
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        fixture = seed(registry, tmp_path)
        yield registry, fixture


def test_scope_is_owner_issued_and_commands_are_closed(owner) -> None:
    registry, _ = owner
    scope = WorkerScope("worker-a", frozenset({"run-a"}))
    with pytest.raises(RegistryTransportError, match="prototype opt-in"):
        RegistryQuackGateway(registry, scope)
    gateway = RegistryQuackGateway(registry, scope, enable_prototype=True)
    with pytest.raises(RegistryTransportError, match="assigned worker scope"):
        gateway.dispatch(_envelope("ClaimRun", {"run_id": "run-b"}, "claim"))
    with pytest.raises(RegistryTransportError, match="closed command schema"):
        gateway.dispatch(_envelope("ClaimRun", {"run_id": "run-a", "worker_id": "worker-b"}, "claim"))
    with pytest.raises(RegistryTransportError, match="worker vocabulary"):
        _envelope("PromoteHead", {}, "promote")
    with pytest.raises(RegistryTransportError, match="65536"):
        _envelope("ReadRun", {"run_id": "run-a", "oversized": "x" * 65536}, "read")
    assert registry.get_run("run-a")["status"] == "queued"
    assert registry.get_run("run-b")["status"] == "queued"


def test_scope_rejects_forged_lease_and_unassigned_versions(owner, tmp_path: Path) -> None:
    registry, _ = owner
    gateway = RegistryQuackGateway(registry, WorkerScope("worker-a", frozenset({"run-a"})), enable_prototype=True)
    with pytest.raises(RegistryTransportError, match="lease is outside"):
        gateway.dispatch(_envelope("RenewLease", {"lease": {"run_id": "run-a", "worker_id": "worker-b"}}, "renew"))
    source = tmp_path / "other-state.json"
    source.write_text('{"fixture":"other"}')
    other = registry.register_version("other-version", "en", registry.stage_artifact(source))
    with pytest.raises(RegistryTransportError, match="version is outside"):
        gateway.dispatch(_envelope("ReadVersion", {"version_id": other["version_id"]}, "read-other"))


def native_available() -> None:
    try:
        connection, _ = _connect_native()
        connection.close()
    except (ImportError, RegistryTransportError) as exc:
        pytest.skip(str(exc))


@NATIVE
def test_native_claim_complete_retry_denial_and_owner_restart(tmp_path: Path) -> None:
    native_available()
    database, artifacts = tmp_path / "owner.duckdb", tmp_path / "artifacts"
    scope = WorkerScope("worker-a", frozenset({"run-a"}))
    with AutoencoderRegistry(database, artifacts) as registry:
        fixture = seed(registry, tmp_path)
        with RegistryQuackGateway(registry, scope, enable_prototype=True) as gateway:
            with RegistryTransportClient(**gateway.connection_parameters()) as client:
                claim = client.request("ClaimRun", {"run_id": "run-a"}, "claim")
                assert claim == client.request("ClaimRun", {"run_id": "run-a"}, "claim")
                assert claim["lease"]["worker_id"] == "worker-a"
                assert client.request("ReadRun", {"run_id": "run-a"}, "read")["run"]["status"] == "running"
                renewed = client.request("RenewLease", {"lease": claim["lease"]}, "renew")
                assert renewed["lease"]["fence"] == claim["lease"]["fence"]
                with pytest.raises(RegistryTransportError, match="different payload"):
                    client.request("ClaimRun", {"run_id": "run-a", "lease_seconds": 99}, "claim")
                with pytest.raises(RegistryTransportError, match="assigned worker scope"):
                    client.request("ClaimRun", {"run_id": "run-b"}, "steal")
                with pytest.raises(RegistryTransportError, match="assigned worker scope"):
                    client.request("ReadRun", {"run_id": "run-b"}, "peek")
                with pytest.raises(RegistryTransportError, match="bounded identifier"):
                    client.request("ReadVersion", {"version_id": {"malformed": True}}, "bad-version")
                parameters = gateway.connection_parameters()
                with pytest.raises(Exception):
                    client._connection.execute(
                        "SELECT * FROM quack_query(?, 'SELECT * FROM autoencoder_control.runs', token := ?, disable_ssl := true)",
                        [parameters["endpoint"], parameters["token"]],
                    ).fetchall()
                with pytest.raises(Exception):
                    client._connection.execute(
                        "SELECT * FROM quack_query(?, 'SELECT 1', token := ?, disable_ssl := true)",
                        [parameters["endpoint"], parameters["token"]],
                    ).fetchall()
                with pytest.raises(RegistryTransportError):
                    RegistryTransportClient(parameters["endpoint"], "wrong-test-token-000000000000000")
                with pytest.raises(Exception):
                    client._connection.execute(
                        "INSERT INTO training_gateway.main.command_inbox VALUES (?, ?)",
                        [64, "x" * 65537],
                    ).fetchall()
                with pytest.raises(RegistryTransportError, match="requires exactly sha256 and bytes"):
                    client.request("CompleteRun", {
                        "lease": renewed["lease"], "artifact": {"path": "/etc/passwd"},
                        "result": {"admitted": False},
                    }, "cannot-read-owner-files")
                payload = {"lease": renewed["lease"], "artifact": fixture["artifact"],
                           "result": {"admitted": False, "fixture": True}}
                completed = client.request("CompleteRun", payload, "complete")
                assert completed["status"] == "completed"
                assert completed["admitted"] is False
                assert completed["promoted"] is False
                assert client.request("CompleteRun", payload, "complete") == completed
                assert client.request("ReadVersion", {"version_id": completed["version_id"]}, "candidate")["version"]["parent_version_id"] == fixture["version_id"]
            assert gateway.status()["failure"] is None
            assert gateway.status()["private_registry_served"] is False
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", int(parameters["endpoint"].rsplit(":", 1)[1])), timeout=0.2)
    # A new transient endpoint and owner generation still replay the same
    # durable completion receipt, although its old lease cannot authorize new work.
    with AutoencoderRegistry(database, artifacts) as registry:
        with RegistryQuackGateway(registry, scope, enable_prototype=True) as gateway:
            with RegistryTransportClient(**gateway.connection_parameters()) as client:
                assert client.request("CompleteRun", payload, "complete") == completed
                with pytest.raises(RegistryTransportError, match="stale, expired or invalid lease"):
                    client.request("RenewLease", {"lease": claim["lease"]}, "stale-renew")


@NATIVE
def test_separate_worker_process_and_reply_isolation(owner) -> None:
    native_available()
    registry, _ = owner
    with RegistryQuackGateway(registry, WorkerScope("worker-a", frozenset({"run-a"})), enable_prototype=True) as first:
        with RegistryQuackGateway(registry, WorkerScope("worker-b", frozenset({"run-b"})), enable_prototype=True) as second:
            parameters = first.connection_parameters()
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(ROOT)
            script = """
import json, sys
from ipfs_datasets_py.duckdb_control.autoencoder_quack import RegistryTransportClient
configuration = json.loads(sys.stdin.read())
with RegistryTransportClient(**configuration) as client:
    print(json.dumps(client.request('ClaimRun', {'run_id': 'run-a'}, 'separate-worker')))
"""
            child = subprocess.run([sys.executable, "-c", script], input=json.dumps(parameters),
                                   text=True, capture_output=True, env=environment, cwd=ROOT, timeout=20)
            assert child.returncode == 0, child.stderr
            assert json.loads(child.stdout.strip().splitlines()[-1])["lease"]["worker_id"] == "worker-a"
            with RegistryTransportClient(**second.connection_parameters()) as client:
                with pytest.raises(RegistryTransportError, match="assigned worker scope"):
                    client.request("ReadRun", {"run_id": "run-a"}, "other-worker-read")
                own_claim = client.request("ClaimRun", {"run_id": "run-b"}, "separate-worker")
                assert own_claim["lease"]["worker_id"] == "worker-b"
            with pytest.raises(RegistryTransportError):
                RegistryTransportClient(second.connection_parameters()["endpoint"], parameters["token"])
