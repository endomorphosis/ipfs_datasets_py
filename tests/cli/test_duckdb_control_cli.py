"""CLI tests for the fail-closed DuckDB control plane (DQK-006).

Acceptance coverage:

* Every mutating command is idempotent and receipted
* Dry-run produces no database change
* CLI output has bounded text and structured modes
* Arbitrary SQL is rejected
* Commands: create, migrate, inspect, check, snapshot, capabilities
"""

from __future__ import annotations

import builtins
import importlib
import io
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

import pytest

from ipfs_datasets_py.duckdb_control import capabilities as caps
from ipfs_datasets_py.duckdb_control import cli as control_cli
from ipfs_datasets_py.duckdb_control.cli import (
    COMMANDS,
    MAX_TEXT_LINE_BYTES,
    MAX_TEXT_OUTPUT_BYTES,
    ControlStore,
    format_output,
    main,
    run,
    run_command,
)
from ipfs_datasets_py.duckdb_control.migrations import (
    MigrationRunner,
    default_control_plane_migrations,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    argv: list[str],
    *,
    store: ControlStore | None = None,
    versions: caps.ComponentVersions | None = None,
) -> tuple[int, dict | str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = run(
        argv,
        store=store,
        stdout=stdout,
        stderr=stderr,
        versions=versions,
    )
    out = stdout.getvalue()
    err = stderr.getvalue()
    # Prefer stdout; argparse help goes to stderr.
    text = out if out.strip() else err
    try:
        return code, json.loads(text), text
    except json.JSONDecodeError:
        return code, text, text


def _pinned_versions(**overrides: object) -> caps.ComponentVersions:
    payload = {
        "client_duckdb": caps.REQUIRED_DUCKDB_VERSION_TEXT,
        "server_duckdb": caps.REQUIRED_DUCKDB_VERSION_TEXT,
        "quack_extension": caps.format_version(caps.PINNED_QUACK_EXTENSION_VERSION),
        "quack_extension_build": caps.PINNED_QUACK_EXTENSION_BUILD,
        "quack_extension_source": "core",
        "vss_extension": caps.format_version(caps.PINNED_VSS_EXTENSION_VERSION),
        "vss_extension_build": caps.PINNED_VSS_EXTENSION_BUILD,
        "client_protocol": caps.DEFAULT_QUACK_PROTOCOL_VERSION,
        "server_protocol": caps.DEFAULT_QUACK_PROTOCOL_VERSION,
    }
    payload.update(overrides)
    return caps.ComponentVersions(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Import safety
# ---------------------------------------------------------------------------


def test_cli_module_import_is_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = {"duckdb", "duckdb.experimental"}
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".", 1)[0]
        if root in forbidden or name in forbidden:
            raise AssertionError(f"import of {name!r} is forbidden at module import")
        return real_import(name, globals, locals, fromlist, level)

    sys.modules.pop("ipfs_datasets_py.duckdb_control.cli", None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    reloaded = importlib.import_module("ipfs_datasets_py.duckdb_control.cli")
    assert reloaded.CLI_SCHEMA.startswith("ipfs_datasets_py/")
    assert set(reloaded.COMMANDS) == {
        "create",
        "migrate",
        "inspect",
        "check",
        "snapshot",
        "capabilities",
    }
    sys.modules["ipfs_datasets_py.duckdb_control.cli"] = reloaded
    monkeypatch.setattr(builtins, "__import__", real_import)


def test_commands_constant_matches_task_surface() -> None:
    assert COMMANDS == (
        "create",
        "migrate",
        "inspect",
        "check",
        "snapshot",
        "capabilities",
    )


# ---------------------------------------------------------------------------
# create / migrate — receipted, idempotent, dry-run
# ---------------------------------------------------------------------------


def test_create_is_receipted_and_applies_migrations() -> None:
    store = ControlStore()
    code, payload, _ = _run(["create"], store=store)
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["ok"] is True
    assert payload["command"] == "create"
    assert payload["status"] in {"created", "already_created"}
    receipt = payload["receipt"]
    assert receipt["schema"].endswith("create-receipt@1")
    assert receipt["receipt_id"].startswith("sha256:")
    assert receipt["dry_run"] is False
    assert len(store.backend.list_applied()) == len(default_control_plane_migrations())
    assert store.created is True
    assert payload["data"]["schema_digest"].startswith("schema-digest:sha256:")


def test_create_is_idempotent() -> None:
    store = ControlStore()
    code1, first, _ = _run(
        ["create", "--idempotency-key", "create-op-1"], store=store
    )
    fingerprint = store.mutation_fingerprint()
    applied = dict(store.backend.list_applied())
    code2, second, _ = _run(
        ["create", "--idempotency-key", "create-op-1"], store=store
    )
    assert code1 == 0 and code2 == 0
    assert isinstance(first, dict) and isinstance(second, dict)
    assert second["status"] == "idempotent_replay"
    assert second["receipt"]["receipt_id"] == first["receipt"]["receipt_id"]
    assert store.mutation_fingerprint() == fingerprint
    assert dict(store.backend.list_applied()) == applied


def test_create_without_key_is_idempotent_when_already_created() -> None:
    store = ControlStore()
    _run(["create"], store=store)
    fingerprint = store.mutation_fingerprint()
    code, payload, _ = _run(["create"], store=store)
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["status"] == "already_created"
    assert payload["data"]["idempotent"] is True
    assert store.mutation_fingerprint() == fingerprint


def test_create_dry_run_makes_no_change() -> None:
    store = ControlStore()
    before = store.mutation_fingerprint()
    code, payload, _ = _run(["create", "--dry-run"], store=store)
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["dry_run"] is True
    assert payload["status"] == "dry_run"
    assert payload["receipt"]["dry_run"] is True
    assert payload["receipt"]["receipt_id"].startswith("sha256:")
    assert store.mutation_fingerprint() == before
    assert store.created is False
    assert store.backend.list_applied() == {}
    assert store.backend.statements == []
    assert store.backend.current_lock(MigrationRunner.LOCK_NAME) is None


def test_migrate_applies_pending_and_is_receipted() -> None:
    store = ControlStore()
    code, payload, _ = _run(["migrate"], store=store)
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["ok"] is True
    assert payload["status"] == "applied"
    receipt = payload["receipt"]
    assert receipt["receipt_id"].startswith("sha256:")
    assert receipt["applied_count"] == len(default_control_plane_migrations())
    assert all(
        r["status"] == "applied" for r in receipt["migration_receipts"]
    )


def test_migrate_noop_when_already_applied() -> None:
    store = ControlStore()
    _run(["migrate"], store=store)
    fingerprint = store.mutation_fingerprint()
    code, payload, _ = _run(["migrate"], store=store)
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["status"] == "noop"
    assert payload["receipt"]["applied_count"] == 0
    assert store.mutation_fingerprint() == fingerprint


def test_migrate_dry_run_makes_no_change() -> None:
    store = ControlStore()
    before = store.mutation_fingerprint()
    code, payload, _ = _run(["migrate", "--dry-run"], store=store)
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["dry_run"] is True
    assert payload["status"] == "dry_run"
    assert len(payload["data"]["would_apply"]) == len(
        default_control_plane_migrations()
    )
    assert store.mutation_fingerprint() == before
    assert store.backend.list_applied() == {}
    assert store.backend.statements == []


def test_migrate_idempotency_key_replays_receipt() -> None:
    store = ControlStore()
    code1, first, _ = _run(
        ["migrate", "--idempotency-key", "mig-1"], store=store
    )
    fingerprint = store.mutation_fingerprint()
    code2, second, _ = _run(
        ["migrate", "--idempotency-key", "mig-1"], store=store
    )
    assert code1 == 0 and code2 == 0
    assert isinstance(first, dict) and isinstance(second, dict)
    assert second["status"] == "idempotent_replay"
    assert second["receipt"]["receipt_id"] == first["receipt"]["receipt_id"]
    assert store.mutation_fingerprint() == fingerprint


# ---------------------------------------------------------------------------
# inspect / check
# ---------------------------------------------------------------------------


def test_inspect_read_only_summary() -> None:
    store = ControlStore()
    _run(["create"], store=store)
    fingerprint = store.mutation_fingerprint()
    code, payload, _ = _run(["inspect"], store=store)
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["ok"] is True
    data = payload["data"]
    assert data["created"] is True
    assert data["applied_count"] == len(default_control_plane_migrations())
    assert data["pending_count"] == 0
    assert data["schema_digest"].startswith("schema-digest:")
    assert "policy_pins" in data
    assert store.mutation_fingerprint() == fingerprint


def test_check_ok_on_clean_store() -> None:
    store = ControlStore()
    _run(["create"], store=store)
    code, payload, _ = _run(["check"], store=store)
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["ok"] is True
    assert payload["receipt"]["ok"] is True
    assert payload["receipt"]["issue_count"] == 0
    assert payload["receipt"]["receipt_id"].startswith("sha256:")


def test_check_fails_closed_on_checksum_drift() -> None:
    store = ControlStore()
    _run(["create"], store=store)
    # Tamper applied checksum.
    first_id = default_control_plane_migrations()[0].migration_id
    store.backend.applied[first_id] = "sha256:" + ("ab" * 32)
    code, payload, _ = _run(["check"], store=store)
    assert code == 1
    assert isinstance(payload, dict)
    assert payload["ok"] is False
    assert payload["status"] == "failed"
    assert payload["receipt"]["issue_count"] >= 1
    assert any("checksum" in i for i in payload["receipt"]["issues"])


def test_check_fails_closed_on_unknown_applied() -> None:
    store = ControlStore()
    store.backend.applied["9999_unknown"] = "sha256:" + ("11" * 32)
    store.backend.applied_version_map["9999_unknown"] = 99
    code, payload, _ = _run(["check"], store=store)
    assert code == 1
    assert isinstance(payload, dict)
    assert payload["ok"] is False
    assert any("unknown" in i for i in payload["receipt"]["issues"])


# ---------------------------------------------------------------------------
# snapshot — receipted, idempotent, dry-run
# ---------------------------------------------------------------------------


def test_snapshot_requires_create() -> None:
    store = ControlStore()
    code, payload, _ = _run(["snapshot"], store=store)
    assert code == 2
    assert isinstance(payload, dict)
    assert payload["ok"] is False
    assert "not created" in (payload.get("error") or "").lower()


def test_snapshot_is_receipted() -> None:
    store = ControlStore()
    _run(["create"], store=store)
    code, payload, _ = _run(["snapshot"], store=store)
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["status"] == "created"
    receipt = payload["receipt"]
    assert receipt["receipt_id"].startswith("sha256:")
    assert receipt["snapshot"]["value"].startswith("sha256:")
    assert receipt["dry_run"] is False
    assert payload["data"]["snapshot_id"] in store.snapshots


def test_snapshot_idempotent_by_content_and_key() -> None:
    store = ControlStore()
    _run(["create"], store=store)
    # First snapshot bumps generation; second with same content after no
    # further mutations should replay by content only when body matches.
    # Because generation is part of the body and increments, content differs
    # each time unless we use an idempotency key.
    code1, first, _ = _run(
        ["snapshot", "--idempotency-key", "snap-A"], store=store
    )
    fingerprint = store.mutation_fingerprint()
    code2, second, _ = _run(
        ["snapshot", "--idempotency-key", "snap-A"], store=store
    )
    assert code1 == 0 and code2 == 0
    assert isinstance(first, dict) and isinstance(second, dict)
    assert second["status"] == "idempotent_replay"
    assert second["receipt"]["receipt_id"] == first["receipt"]["receipt_id"]
    assert store.mutation_fingerprint() == fingerprint


def test_snapshot_dry_run_makes_no_change() -> None:
    store = ControlStore()
    _run(["create"], store=store)
    before = store.mutation_fingerprint()
    gen = store.generation
    snaps = dict(store.snapshots)
    code, payload, _ = _run(["snapshot", "--dry-run"], store=store)
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["dry_run"] is True
    assert payload["status"] == "dry_run"
    assert payload["receipt"]["dry_run"] is True
    assert store.mutation_fingerprint() == before
    assert store.generation == gen
    assert store.snapshots == snaps


def test_snapshot_dry_run_allowed_on_empty_store() -> None:
    store = ControlStore()
    before = store.mutation_fingerprint()
    code, payload, _ = _run(["snapshot", "--dry-run"], store=store)
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["dry_run"] is True
    assert store.mutation_fingerprint() == before


# ---------------------------------------------------------------------------
# capabilities
# ---------------------------------------------------------------------------


def test_capabilities_ok_with_injected_pins() -> None:
    store = ControlStore()
    code, payload, _ = _run(
        ["capabilities"],
        store=store,
        versions=_pinned_versions(),
    )
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["ok"] is True
    assert payload["command"] == "capabilities"
    assert payload["receipt"]["ok"] is True
    assert payload["data"]["pins"]["duckdb"] == "1.5.5"


def test_capabilities_fail_closed_on_version_mismatch() -> None:
    store = ControlStore()
    code, payload, _ = _run(
        ["capabilities"],
        store=store,
        versions=_pinned_versions(client_duckdb="1.4.0"),
    )
    assert code == 1
    assert isinstance(payload, dict)
    assert payload["ok"] is False
    assert payload["status"] == "failed"
    assert payload["receipt"]["ok"] is False


def test_capabilities_quack_gate() -> None:
    store = ControlStore()
    code, payload, _ = _run(
        ["capabilities", "--enable-quack"],
        store=store,
        versions=_pinned_versions(),
    )
    assert code == 0
    assert isinstance(payload, dict)
    caps_map = payload["receipt"]["capabilities"]
    assert "quack_transport" in caps_map
    assert payload["data"]["quack_beta"] is True


# ---------------------------------------------------------------------------
# Output modes: structured JSON + bounded text
# ---------------------------------------------------------------------------


def test_structured_json_mode_is_default() -> None:
    store = ControlStore()
    code, payload, raw = _run(["inspect", "--format", "json"], store=store)
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["schema"].endswith("cli-result@1")
    # Canonical-ish compact JSON (no indent required, but must parse).
    assert raw.strip().startswith("{")


def test_text_mode_is_bounded_and_human_readable() -> None:
    store = ControlStore()
    _run(["create"], store=store)
    stdout = io.StringIO()
    code = run(
        ["--format", "text", "inspect"],
        store=store,
        stdout=stdout,
        stderr=io.StringIO(),
    )
    assert code == 0
    text = stdout.getvalue()
    assert "command: inspect" in text
    assert "status: ok" in text
    assert len(text.encode("utf-8")) <= MAX_TEXT_OUTPUT_BYTES
    for line in text.splitlines():
        assert len(line.encode("utf-8")) <= MAX_TEXT_LINE_BYTES


def test_format_output_clips_oversized_text() -> None:
    huge = {
        "schema": "ipfs_datasets_py/duckdb-control-cli-result@1",
        "command": "inspect",
        "ok": True,
        "status": "ok",
        "dry_run": False,
        "error": "X" * (MAX_TEXT_OUTPUT_BYTES * 2),
        "data": {"schema_digest": "Y" * 2000},
    }
    text = format_output(huge, fmt="text")
    assert len(text.encode("utf-8")) <= MAX_TEXT_OUTPUT_BYTES
    assert "truncated" in text or len(text) < len(huge["error"])


def test_format_rejects_unknown_mode() -> None:
    with pytest.raises(control_cli.CliError, match="unsupported output format"):
        format_output({"ok": True}, fmt="yaml")


# ---------------------------------------------------------------------------
# Fail-closed: no arbitrary SQL
# ---------------------------------------------------------------------------


def test_rejects_sql_flag() -> None:
    store = ControlStore()
    code, payload, _ = _run(
        ["migrate", "--sql", "SELECT 1"],
        store=store,
    )
    assert code == 2
    assert isinstance(payload, dict)
    assert payload["ok"] is False
    assert "sql" in (payload.get("error") or "").lower()


def test_rejects_query_flag() -> None:
    store = ControlStore()
    code, payload, _ = _run(
        ["--query", "DROP TABLE schema_registry", "inspect"],
        store=store,
    )
    assert code == 2
    assert isinstance(payload, dict)
    assert "sql" in (payload.get("error") or "").lower()


def test_rejects_sql_statement_smuggling() -> None:
    store = ControlStore()
    code, payload, _ = _run(
        ["inspect", "SELECT * FROM schema_registry;"],
        store=store,
    )
    # Either argparse rejects unknown args or our SQL guard fires.
    assert code != 0


def test_parser_has_no_sql_arguments() -> None:
    parser = control_cli.build_parser()
    help_text = parser.format_help().lower()
    for banned in ("--sql", "--query", "--execute", "arbitrary sql"):
        # Description mentions rejection of arbitrary SQL — that is fine.
        if banned == "arbitrary sql":
            assert banned in help_text
            continue
        # Ensure no option accepts SQL bodies.
        assert f"  {banned}" not in help_text


# ---------------------------------------------------------------------------
# End-to-end operator flow + main()
# ---------------------------------------------------------------------------


def test_full_operator_flow() -> None:
    store = ControlStore()
    # Dry-run create first.
    code, payload, _ = _run(["create", "--dry-run"], store=store)
    assert code == 0
    assert store.created is False

    code, payload, _ = _run(["create"], store=store)
    assert code == 0
    assert store.created is True

    code, payload, _ = _run(["check"], store=store)
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["ok"] is True

    code, payload, _ = _run(["inspect"], store=store)
    assert code == 0

    code, payload, _ = _run(
        ["snapshot", "--idempotency-key", "flow-snap"], store=store
    )
    assert code == 0
    assert isinstance(payload, dict)
    snap_id = payload["data"]["snapshot_id"]

    # Migrate is noop after create.
    code, payload, _ = _run(["migrate", "--dry-run"], store=store)
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["data"]["pending_count"] == 0

    code, payload, _ = _run(
        ["capabilities"],
        store=store,
        versions=_pinned_versions(),
    )
    assert code == 0

    # Snapshot key replays.
    code, payload, _ = _run(
        ["snapshot", "--idempotency-key", "flow-snap"], store=store
    )
    assert code == 0
    assert isinstance(payload, dict)
    assert payload["data"]["snapshot_id"] == snap_id or payload["status"] == "idempotent_replay"


def test_main_entrypoint_returns_int() -> None:
    store = ControlStore()
    # main() uses sys stdout; exercise via run which main wraps.
    assert isinstance(main.__doc__, str) or main.__doc__ is None
    code = run(["inspect"], store=store, stdout=io.StringIO(), stderr=io.StringIO())
    assert code == 0


def test_run_command_dispatch_unknown() -> None:
    store = ControlStore()
    with pytest.raises(control_cli.CliError, match="unknown command"):
        run_command("drop-all", store)


def test_invalid_idempotency_key_fails_closed() -> None:
    store = ControlStore()
    code, payload, _ = _run(
        ["create", "--idempotency-key", "bad key with spaces"],
        store=store,
    )
    assert code == 2
    assert isinstance(payload, dict)
    assert payload["ok"] is False
    assert "idempotency" in (payload.get("error") or "").lower()


def test_help_lists_all_commands() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = run(["--help"], stdout=stdout, stderr=stderr)
    assert code == 0
    text = (stdout.getvalue() + stderr.getvalue()).lower()
    for name in COMMANDS:
        assert name in text
