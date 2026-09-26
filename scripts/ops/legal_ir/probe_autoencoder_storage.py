#!/usr/bin/env python3
"""Probe installed storage capabilities in disposable databases only.

No extension installation, weight access, production activation or legal admit
occurs here. Native probes are opt-in and load only artifacts matching the
workspace's existing DuckDB/Quack/DuckLake lock. A passing receipt establishes
isolated capabilities, not qualification of the training-control adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = REPO_ROOT / "requirements/duckdb-quack.lock"
SCHEMA = "ipfs_datasets_py/autoencoder-storage-probe@1"
CONNECT_CONFIG = {
    "autoinstall_known_extensions": "false",
    "autoload_known_extensions": "false",
    "allow_unsigned_extensions": "false",
    "threads": "2",
}
EXTENSIONS = ("quack", "ducklake", "httpfs")
# DQK-084's catalog contract; a different native catalog is not a passing probe.
REQUIRED_CATALOG_VERSION = "1.0"
READ_QUERY = "SELECT probe_value FROM probe_rows ORDER BY probe_value"


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _lock_profile(path: Path = LOCK_PATH) -> dict[str, str]:
    profile: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if line.startswith("profile.") and "=" in line:
            key, value = line.split("=", 1)
            if key in profile:
                raise ValueError(f"duplicate profile key: {key}")
            profile[key] = value
    return profile


def inventory() -> dict[str, Any]:
    """Read installed metadata and artifact bytes; never LOAD extensions."""
    import duckdb

    profile = _lock_profile()
    machine = {"aarch64": "linux_arm64", "x86_64": "linux_amd64"}.get(
        platform.machine().lower(), "unsupported"
    )
    connection = duckdb.connect(":memory:", config=CONNECT_CONFIG)
    try:
        rows = connection.execute(
            "SELECT extension_name, loaded, installed, install_path, extension_version "
            "FROM duckdb_extensions() "
            "WHERE extension_name IN ('quack', 'ducklake', 'httpfs')"
        ).fetchall()
    finally:
        connection.close()
    extensions = {}
    for name, loaded, installed, path, version in rows:
        artifact = Path(path)
        expected = profile.get(f"profile.extension.{name}.{machine}.bin_sha256", "")
        digest = _sha256(artifact) if installed and artifact.is_file() else ""
        extensions[name] = {
            "installed": bool(installed),
            "loaded_during_inventory": bool(loaded),
            "path": str(artifact),
            "extension_version": version,
            "sha256": digest,
            "expected_sha256": expected,
            "matches_lock": bool(expected) and digest == expected,
        }
    return {
        "python_version": platform.python_version(),
        "duckdb_version": duckdb.__version__,
        "expected_duckdb_version": profile["profile.duckdb_version"],
        "duckdb_matches_lock": duckdb.__version__ == profile["profile.duckdb_version"],
        "platform": machine,
        "extensions": extensions,
        "source_root": str(REPO_ROOT),
        "source_metadata": {
            str(path.relative_to(REPO_ROOT)): _sha256(path)
            for path in (
                LOCK_PATH,
                Path(__file__).resolve(),
                REPO_ROOT / "ipfs_datasets_py/duckdb_control/capabilities.py",
                REPO_ROOT / "ipfs_datasets_py/ducklake/capabilities.py",
                REPO_ROOT / "ipfs_datasets_py/ducklake/quack_catalog.py",
            )
        },
    }


def native_unavailable_reason(observed: dict[str, Any]) -> str | None:
    if not observed.get("duckdb_matches_lock"):
        return "DuckDB version does not match workspace lock"
    for name in EXTENSIONS:
        if not observed.get("extensions", {}).get(name, {}).get("matches_lock"):
            return f"{name} installed artifact does not match workspace lock"
    return None


def _load_pinned_extensions(connection: Any) -> None:
    observed = inventory()
    reason = native_unavailable_reason(observed)
    if reason:
        raise RuntimeError(reason)
    # The existing DQK-084 policy's explicit order, with automatic loading off.
    for name in EXTENSIONS:
        entry = observed["extensions"][name]
        path = Path(entry["path"])
        if _sha256(path) != entry["expected_sha256"]:
            raise RuntimeError(f"{name} changed after inventory")
        connection.execute(f"LOAD {_literal(path)}")


def _connect(path: Path | str = ":memory:") -> Any:
    import duckdb

    return duckdb.connect(str(path), config=CONNECT_CONFIG)


def _owned_scratch(path: Path, token: str) -> Path:
    root = path.resolve(strict=True)
    if not root.name.startswith("autoencoder-storage-probe-"):
        raise ValueError("probe requires its own disposable scratch directory")
    if not secrets.compare_digest((root / ".probe-owner").read_text(), token):
        raise ValueError("scratch ownership token mismatch")
    return root


def _close_reopen(root: Path) -> dict[str, Any]:
    path = root / "close-reopen.duckdb"
    if path.exists():
        raise ValueError("scratch database already exists")
    connection = _connect(path)
    try:
        connection.execute("CREATE TABLE versions (version_id VARCHAR PRIMARY KEY)")
        connection.execute("INSERT INTO versions VALUES ('isolated-version-1')")
    finally:
        connection.close()
    connection = _connect(path)
    try:
        rows = connection.execute("SELECT version_id FROM versions").fetchall()
    finally:
        connection.close()
    if rows != [("isolated-version-1",)]:
        raise RuntimeError("close/reopen lost committed row")
    return {"status": "passed", "committed_rows_after_reopen": len(rows)}


def _kill_writer(root: Path) -> None:
    path = root / "process-kill.duckdb"
    if path.exists():
        raise ValueError("scratch database already exists")
    connection = _connect(path)
    connection.execute("CREATE TABLE recovery_rows (value INTEGER PRIMARY KEY)")
    connection.execute("INSERT INTO recovery_rows VALUES (1)")
    connection.execute("BEGIN TRANSACTION")
    connection.execute("INSERT INTO recovery_rows VALUES (2)")
    print(json.dumps({"ready_for_kill": True}), flush=True)
    # Parent kills this process after observing the committed and open writes.
    sys.stdin.read()
    connection.close()


def _worker_command(mode: str, root: Path, token: str) -> list[str]:
    return [
        sys.executable, str(Path(__file__).resolve()), "--_worker", mode,
        "--_scratch", str(root), "--_token", token,
    ]


def _process_kill(root: Path, token: str, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    process = subprocess.Popen(
        _worker_command("kill-writer", root, token),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            if not selector.select(timeout):
                raise TimeoutError("writer did not reach committed/open transaction boundary")
            line = process.stdout.readline()
        if json.loads(line) != {"ready_for_kill": True}:
            raise RuntimeError("writer did not report the expected boundary")
        wal = root / "process-kill.duckdb.wal"
        wal_bytes = wal.stat().st_size if wal.exists() else 0
        process.kill()
        process.communicate(timeout=timeout)
        if process.returncode != -signal.SIGKILL:
            raise RuntimeError("writer did not exit through SIGKILL")
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=timeout)
    connection = _connect(root / "process-kill.duckdb")
    try:
        rows = connection.execute("SELECT value FROM recovery_rows ORDER BY value").fetchall()
    finally:
        connection.close()
    if rows != [(1,)]:
        raise RuntimeError("recovery did not retain committed and discard uncommitted writes")
    return {
        "status": "passed", "writer_exit_signal": "SIGKILL",
        "wal_bytes_before_kill": wal_bytes, "committed_rows_recovered": 1,
        "uncommitted_rows_recovered": 0,
        "elapsed_seconds": time.perf_counter() - started,
    }


def _ducklake(root: Path) -> dict[str, Any]:
    catalog = root / "history.ducklake"
    data = root / "history-files"
    if catalog.exists() or data.exists():
        raise ValueError("scratch catalog already exists")
    for create in (True, False):
        connection = _connect()
        try:
            _load_pinned_extensions(connection)
            # This pinned native build has ATTACH AUTOMATIC_MIGRATION, but may
            # not implement the global setting named in the policy contract.
            global_migration_setting = bool(connection.execute(
                "SELECT count(*) FROM duckdb_settings() WHERE name = 'ducklake_auto_migration'"
            ).fetchone()[0])
            if global_migration_setting:
                connection.execute("SET ducklake_auto_migration = false")
            connection.execute(
                f"ATTACH {_literal('ducklake:' + str(catalog))} AS history "
                f"(DATA_PATH {_literal(data)}, CREATE_IF_NOT_EXISTS {str(create).lower()}, "
                "OVERRIDE_DATA_PATH false, AUTOMATIC_MIGRATION false, "
                "DATA_INLINING_ROW_LIMIT 0)"
            )
            catalog_version = connection.execute(
                "SELECT value FROM __ducklake_metadata_history.main.ducklake_metadata "
                "WHERE key = 'version'"
            ).fetchone()[0]
            if catalog_version != REQUIRED_CATALOG_VERSION:
                raise RuntimeError(f"DuckLake catalog version mismatch: {catalog_version}")
            if create:
                connection.execute("CREATE TABLE history.updates (version_id VARCHAR, value DOUBLE)")
                connection.execute("INSERT INTO history.updates VALUES ('probe-version', 1.25)")
            else:
                rows = connection.execute("SELECT version_id, value FROM history.updates").fetchall()
            connection.execute("DETACH history")
        finally:
            connection.close()
    if rows != [("probe-version", 1.25)]:
        raise RuntimeError("DuckLake reopen lost the inserted row")
    parquet_files = list(data.rglob("*.parquet"))
    if not parquet_files:
        raise RuntimeError("DuckLake probe did not create a Parquet data file")
    return {
        "status": "passed", "catalog_file_bytes": catalog.stat().st_size,
        "parquet_file_count": len(parquet_files), "rows_after_reopen": len(rows),
        "metadata_backend": "local_duckdb", "remote_catalog_tested": False,
        "bootstrap_confined_to_disposable_directory": True,
        "global_ducklake_auto_migration_setting_available": global_migration_setting,
        "automatic_migration": False,
        "migration_control": "ATTACH AUTOMATIC_MIGRATION false",
        "catalog_version": catalog_version,
    }


def _reachable(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
            return True
    except OSError:
        return False


def _quack(root: Path) -> dict[str, Any]:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    endpoint = f"quack:127.0.0.1:{port}"
    token = secrets.token_urlsafe(32)
    server = _connect(root / "quack.duckdb")
    client = None
    started = False
    try:
        _load_pinned_extensions(server)
        server.execute("CREATE TABLE probe_rows (probe_value INTEGER)")
        server.execute("INSERT INTO probe_rows VALUES (42)")
        server.execute(
            "CREATE MACRO storage_probe_authz(sid, query) AS "
            f"(sid IS NOT NULL AND query = {_literal(READ_QUERY)})"
        )
        server.execute("SET GLOBAL quack_authentication_function = 'quack_check_token'")
        server.execute("SET GLOBAL quack_authorization_function = 'storage_probe_authz'")
        server.execute(
            "CALL quack_serve(?, token := ?, disable_ssl := true)", [endpoint, token]
        ).fetchall()
        started = True
        client = _connect()
        _load_pinned_extensions(client)
        sql = "SELECT * FROM quack_query(?, ?, token := ?, disable_ssl := true)"
        rows = client.execute(sql, [endpoint, READ_QUERY, token]).fetchall()
        if rows != [(42,)]:
            raise RuntimeError("native Quack returned unexpected rows")
        denied = {}
        for label, query, supplied_token in (
            ("unlisted_query", "SELECT 999", token),
            ("wrong_token", READ_QUERY, "invalid-storage-probe-token"),
        ):
            try:
                client.execute(sql, [endpoint, query, supplied_token]).fetchall()
            except Exception:
                denied[label] = True
            else:
                raise RuntimeError(f"native Quack accepted {label}")
    except Exception as exc:
        # A generated ephemeral token should never end up in the receipt.
        raise RuntimeError(str(exc).replace(token, "<redacted>")) from None
    finally:
        try:
            if client is not None:
                client.close()
            if started:
                server.execute("CALL quack_stop(?)", [endpoint]).fetchall()
        finally:
            server.close()
    deadline = time.monotonic() + 2
    while _reachable(port) and time.monotonic() < deadline:
        time.sleep(0.02)
    if _reachable(port):
        raise RuntimeError("probe listener remained reachable after clean stop")
    return {
        "status": "passed", "transport": "native_quack_query",
        "remote_rows": len(rows), "loopback_only": True,
        "authorization": "one_exact_read_query", "denials": denied,
        "listener_stopped": True, "training_commands_tested": False,
    }


def _run_worker(mode: str, root: Path, token: str, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = subprocess.run(
            _worker_command(mode, root, token), capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        # Extension diagnostics may precede the single final JSON receipt.
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        if result.returncode:
            payload = {**payload, "status": "failed", "worker_exit_code": result.returncode}
    except (subprocess.TimeoutExpired, ValueError, IndexError) as exc:
        payload = {"status": "failed", "reason": type(exc).__name__}
    payload["elapsed_seconds"] = time.perf_counter() - started
    return payload


def run_probe(*, native: bool = False, timeout: float = 30) -> dict[str, Any]:
    """Return an isolated receipt; never accept a user database or endpoint."""
    if not 1 <= timeout <= 60:
        raise ValueError("timeout must be between 1 and 60 seconds")
    started = time.perf_counter()
    observed = inventory()
    receipt: dict[str, Any] = {
        "schema": SCHEMA, "scope": "isolated_disposable_capabilities",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "admitted": False, "runtime_qualified": False,
        "production_activation": False, "training_integration_qualified": False,
        "network_install": False, "autoload": False, "weights_accessed": False,
        "logic_modules_imported": False, "inventory": observed, "probes": {},
    }
    token = secrets.token_hex(32)
    with tempfile.TemporaryDirectory(prefix="autoencoder-storage-probe-") as directory:
        root = Path(directory)
        (root / ".probe-owner").write_text(token)
        probes = receipt["probes"]
        if observed["duckdb_matches_lock"]:
            probes["duckdb_close_reopen"] = _run_worker("close-reopen", root, token, timeout)
            try:
                probes["duckdb_process_kill"] = _process_kill(root, token, timeout)
            except Exception as exc:
                probes["duckdb_process_kill"] = {"status": "failed", "reason": str(exc)}
        else:
            for name in ("duckdb_close_reopen", "duckdb_process_kill"):
                probes[name] = {"status": "unavailable", "reason": "DuckDB lock mismatch"}
        reason = native_unavailable_reason(observed)
        for mode in ("quack", "ducklake"):
            probes[mode] = (
                {"status": "not_run", "reason": "native probes were not requested"}
                if not native else {"status": "unavailable", "reason": reason}
                if reason else _run_worker(mode, root, token, timeout)
            )
    receipt["scratch_removed"] = not root.exists()
    receipt["elapsed_seconds"] = time.perf_counter() - started
    receipt["status"] = (
        "passed" if all(p["status"] in {"passed", "not_run"} for p in probes.values())
        else "incomplete"
    )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true", help="probe installed pinned extensions")
    parser.add_argument("--output", type=Path, help="create a new receipt file; never overwrite")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--_worker", choices=("kill-writer", "close-reopen", "quack", "ducklake"), help=argparse.SUPPRESS)
    parser.add_argument("--_scratch", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--_token", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._worker:
        try:
            root = _owned_scratch(args._scratch, args._token)
            if args._worker == "kill-writer":
                _kill_writer(root)
                return 1  # Normal exit does not establish a crash-recovery probe.
            action = {"close-reopen": _close_reopen, "quack": _quack, "ducklake": _ducklake}[args._worker]
            print(json.dumps(action(root)), flush=True)
            return 0
        except Exception as exc:
            print(json.dumps({"status": "failed", "reason": str(exc), "error_type": type(exc).__name__}), flush=True)
            return 1
    receipt = run_probe(native=args.native, timeout=args.timeout)
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output:
        with args.output.open("x") as handle:
            handle.write(rendered)
    print(rendered, end="")
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
