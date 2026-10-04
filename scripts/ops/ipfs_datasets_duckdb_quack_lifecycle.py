#!/usr/bin/env python3
"""Lifecycle owner CLI for governed plan/runtime-generation rollover (DQK-083).

This script is the only supported operator surface for accepting a revised
goal/task graph or an attested runtime environment via the DQK-083 lifecycle
owner.  Completing DQK-083 *installs* this owner; it does not:

* activate a runtime generation (DQK-103)
* approve a plan revision (DQK-081)

Authority is signed/CID-bound DuckDB plan-revision and environment-generation
rows.  JSON/Markdown/formal-source/environment files may transport a projection
but never authorize rollover.

Commands
--------
install-check
    Prove the lifecycle owner is installed without activating anything.
rollover
    Drain, verify authority rows, materialize a new immutable generation,
    fence writers, launch/verify the new master, and retire the old generation.
activate-runtime
    DQK-103 surface.  With ``--check`` reports install-only status.  Without a
    future DQK-103 permit this command refuses activation.

Standard-library plus the repository package.  Importing side effects are
limited to path setup for hermetic and installed layouts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]


def _ensure_repo_on_path() -> None:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


_ensure_repo_on_path()

from ipfs_datasets_py.duckdb_control import generation_rollover as rollover  # noqa: E402
from ipfs_datasets_py.duckdb_control.generation_rollover import (  # noqa: E402
    ACTIVATION_SCHEMA,
    APPROVAL_GATE_TASK_ID,
    LIFECYCLE_OWNER_TASK_ID,
    PROGRAM_ID,
    RUNTIME_ACTIVATION_GATE_TASK_ID,
    GenerationRolloverError,
    MemoryAuthorityStore,
    PlanRevisionRow,
    EnvironmentGenerationRow,
    GenerationIdentity,
    ProcessBirthIdentity,
    WriterFenceState,
    authorize_rollover_from_files,
    build_environment_row,
    build_plan_revision_row,
    build_process_birth,
    execute_rollover,
    install_check,
    load_transport_projection,
    refuse_runtime_activation_without_permit,
    self_check,
    verify_completion_from_merge_receipts,
    verify_runtime_activation_permit,
)


def _emit(payload: Mapping[str, Any], *, as_json: bool, stream: Any = None) -> None:
    handle = stream if stream is not None else sys.stdout
    if as_json:
        handle.write(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n"
        )
    else:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _load_json_object(path: str | Path, *, noun: str) -> dict[str, Any]:
    target = Path(path)
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise GenerationRolloverError(f"{noun} unreadable: {exc}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GenerationRolloverError(f"{noun} is not JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise GenerationRolloverError(f"{noun} must be a JSON object")
    return value


def _build_store_from_authority_dir(authority_dir: Path) -> MemoryAuthorityStore:
    """Load hermetic authority rows from a directory of JSON projections.

    Files under the directory are *transport only*.  Each plan-revision and
    environment JSON is re-parsed into a sealed authority row and inserted into
    the in-memory store; unsigned or mismatched rows fail closed.
    """

    store = MemoryAuthorityStore()
    if not authority_dir.is_dir():
        raise GenerationRolloverError(f"authority directory missing: {authority_dir}")

    active_path = authority_dir / "active_generation.json"
    if active_path.is_file():
        active = GenerationIdentity.from_mapping(_load_json_object(active_path, noun="active generation"))
        store.set_active_generation(active)

    for path in sorted(authority_dir.glob("plan_revision_*.json")):
        body = _load_json_object(path, noun=f"plan revision transport {path.name}")
        # Transport projection may wrap the row or be the row itself.
        row_body = body.get("body") if body.get("transport_only") else body
        if not isinstance(row_body, dict):
            raise GenerationRolloverError(f"{path} transport body is not an object")
        store.put_plan_revision(row_body)

    for path in sorted(authority_dir.glob("environment_*.json")):
        body = _load_json_object(path, noun=f"environment transport {path.name}")
        row_body = body.get("body") if body.get("transport_only") else body
        if not isinstance(row_body, dict):
            raise GenerationRolloverError(f"{path} transport body is not an object")
        store.put_environment_generation(row_body)

    for path in sorted(authority_dir.glob("merge_receipt_*.json")):
        store.put_merge_receipt(_load_json_object(path, noun="merge receipt"))

    for path in sorted(authority_dir.glob("terminal_receipt_*.json")):
        store.put_terminal_receipt(_load_json_object(path, noun="terminal receipt"))

    seed_path = authority_dir / "seed_TASKS.json"
    if seed_path.is_file():
        seed = _load_json_object(seed_path, noun="seed TASKS")
        tasks = seed.get("tasks") or seed.get("TASKS") or ()
        if isinstance(tasks, (list, tuple)):
            store.set_seed_tasks_tuple(*[str(item) for item in tasks])

    return store


def cmd_install_check(args: argparse.Namespace) -> int:
    report = install_check()
    if args.check:
        hermetic = self_check()
        report = {**report, "self_check": hermetic, "self_check_ok": hermetic.get("ok")}
    _emit(report, as_json=bool(args.json) or True)
    return 0 if report.get("ok") else 1


def cmd_rollover(args: argparse.Namespace) -> int:
    if args.check:
        report = self_check()
        _emit(report, as_json=bool(args.json) or True)
        return 0 if report.get("ok") else 1

    # Files alone never authorize — even if the operator passes them.
    transport_paths = list(args.transport_file or [])
    if transport_paths and not args.authority_dir and not args.plan_revision_row_cid:
        authorize_rollover_from_files(*transport_paths)

    if not args.authority_dir:
        raise GenerationRolloverError(
            "rollover requires --authority-dir with accepted DuckDB authority "
            "row projections (files alone cannot authorize)"
        )

    store = _build_store_from_authority_dir(Path(args.authority_dir))

    # Optional: verify transport projections match authority CIDs when provided.
    for path in transport_paths:
        projection = load_transport_projection(path)
        if projection.get("authority"):
            raise GenerationRolloverError("transport projection claimed authority")
        body = projection.get("body")
        if isinstance(body, dict) and body.get("row_cid"):
            row_cid = str(body["row_cid"])
            if store.get_plan_revision(row_cid) is None and store.get_environment_generation(row_cid) is None:
                raise GenerationRolloverError(
                    f"transport projection {path} is not bound to an authority row"
                )

    result = execute_rollover(
        store,
        plan_revision_row_cid=args.plan_revision_row_cid or None,
        environment_row_cid=args.environment_row_cid or None,
        operation_id=args.operation_id or None,
        journal_path=args.journal or None,
        crash_at=args.crash_at or None,
        materialize=not args.no_materialize,
        launch_master=not args.no_launch,
        owner_birth=build_process_birth(),
    )
    _emit(result, as_json=bool(args.json) or True)
    return 0 if result.get("ok") else 1


def cmd_activate_runtime(args: argparse.Namespace) -> int:
    """DQK-103 surface: verify a signed activation permit or report install-only."""

    receipt_path = str(getattr(args, "receipt", "") or "").strip()
    plan_root = str(getattr(args, "plan_root", "") or "").strip()
    repository_tree = str(getattr(args, "repository_tree", "") or "").strip()
    if receipt_path:
        raw = Path(receipt_path).read_bytes()
        env_receipt_path = Path(
            os.environ.get(
                "IPFS_DATASETS_DQK_ENV_ROOT",
                str(Path.home() / ".venvs" / "ipfs-datasets-duckdb-quack"),
            )
        ) / "environment-receipt.json"
        # Prefer the sealed env receipt next to EXPECTED_ENV_ROOT when present.
        candidates = [
            Path("/home/barberb/lift_coding/.venvs/ipfs-datasets-duckdb-quack/environment-receipt.json"),
            env_receipt_path,
            REPO_ROOT.parent.parent / ".venvs" / "ipfs-datasets-duckdb-quack" / "environment-receipt.json",
        ]
        env_receipt = None
        for candidate in candidates:
            if candidate.is_file() and not candidate.is_symlink():
                env_receipt = _load_json_object(candidate, noun="environment receipt")
                break
        if env_receipt is None:
            raise GenerationRolloverError("sealed environment receipt is unavailable")
        if not plan_root or not repository_tree:
            raise GenerationRolloverError(
                "activate-runtime --receipt requires --plan-root and --repository-tree"
            )
        report = verify_runtime_activation_permit(
            raw,
            plan_root_cid=plan_root,
            repository_tree_id=repository_tree,
            environment_receipt=env_receipt,
        )
        _emit(report, as_json=bool(args.json) or True)
        return 0 if report.get("accepted") is True else 1

    if args.check or not args.activation_permit_cid:
        report = refuse_runtime_activation_without_permit(
            activation_permit_cid=args.activation_permit_cid or None,
            check_only=True,
        )
        # Enrich with install evidence for the manual-gate verifier profile.
        report["owner_task_id"] = LIFECYCLE_OWNER_TASK_ID
        report["runtime_activation_gate_task_id"] = RUNTIME_ACTIVATION_GATE_TASK_ID
        report["approval_gate_task_id"] = APPROVAL_GATE_TASK_ID
        report["program_id"] = PROGRAM_ID
        report["schema"] = ACTIVATION_SCHEMA
        report["activated"] = False
        report["lifecycle_owner_installed"] = True
        report["dqk_083_activates_generation"] = False
        _emit(report, as_json=bool(args.json) or True)
        return 0

    # Explicit permit CID alone still fails closed (body required via --receipt).
    try:
        refuse_runtime_activation_without_permit(
            activation_permit_cid=args.activation_permit_cid,
            check_only=False,
        )
    except GenerationRolloverError as exc:
        error = {
            "ok": False,
            "activated": False,
            "schema": ACTIVATION_SCHEMA,
            "error": str(exc),
            "owner_task_id": LIFECYCLE_OWNER_TASK_ID,
            "runtime_activation_gate_task_id": RUNTIME_ACTIVATION_GATE_TASK_ID,
            "lifecycle_owner_installed": True,
            "dqk_083_activates_generation": False,
        }
        _emit(error, as_json=True)
        return 1
    return 1


def cmd_verify_merges(args: argparse.Namespace) -> int:
    if not args.authority_dir:
        raise GenerationRolloverError("--authority-dir is required")
    store = _build_store_from_authority_dir(Path(args.authority_dir))
    expected = tuple(args.task_id or ())
    report = verify_completion_from_merge_receipts(
        store,
        expected_task_ids=expected or None,
        seed_head=args.seed_head or None,
    )
    _emit(report, as_json=bool(args.json) or True)
    return 0 if report.get("ok") else 1


def cmd_refuse_files(args: argparse.Namespace) -> int:
    paths = list(args.file or [])
    try:
        authorize_rollover_from_files(*paths)
    except GenerationRolloverError as exc:
        payload = {
            "ok": True,
            "authorized": False,
            "error": str(exc),
            "owner_task_id": LIFECYCLE_OWNER_TASK_ID,
            "transport_projections_cannot_authorize": True,
        }
        _emit(payload, as_json=bool(args.json) or True)
        return 0
    _emit({"ok": False, "authorized": True}, as_json=True)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipfs_datasets_duckdb_quack_lifecycle",
        description=(
            "DQK-083 lifecycle owner: governed plan/runtime-generation rollover "
            "and writer fencing. Completing this task only installs the owner; "
            "it cannot activate a runtime generation (DQK-103) or approve a plan "
            f"(DQK-081)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    install = sub.add_parser(
        "install-check",
        help="prove the lifecycle owner is installed (no activation)",
    )
    install.add_argument("--check", action="store_true", help="run hermetic self-check")
    install.add_argument("--json", action="store_true", help="emit JSON")
    install.set_defaults(func=cmd_install_check)

    rollover_cmd = sub.add_parser(
        "rollover",
        help="execute governed generation rollover from DuckDB authority rows",
    )
    rollover_cmd.add_argument(
        "--authority-dir",
        type=str,
        default="",
        help="directory of accepted plan-revision/environment authority row JSON",
    )
    rollover_cmd.add_argument(
        "--plan-revision-row-cid",
        type=str,
        default="",
        help="CID of the accepted plan-revision authority row",
    )
    rollover_cmd.add_argument(
        "--environment-row-cid",
        type=str,
        default="",
        help="CID of the accepted environment-generation authority row",
    )
    rollover_cmd.add_argument(
        "--transport-file",
        action="append",
        default=[],
        help="optional transport projection (cannot authorize alone)",
    )
    rollover_cmd.add_argument("--operation-id", type=str, default="")
    rollover_cmd.add_argument(
        "--journal",
        type=str,
        default="",
        help="path to durable rollover journal for crash recovery",
    )
    rollover_cmd.add_argument(
        "--crash-at",
        type=str,
        default="",
        help="test-only crash boundary (drain|materialize|launch|retire)",
    )
    rollover_cmd.add_argument(
        "--no-materialize",
        action="store_true",
        help="refuse plan-root materialization (environment-only path)",
    )
    rollover_cmd.add_argument(
        "--no-launch",
        action="store_true",
        help="skip synthetic master launch (still binds identity fields)",
    )
    rollover_cmd.add_argument("--check", action="store_true", help="hermetic self-check")
    rollover_cmd.add_argument("--json", action="store_true")
    rollover_cmd.set_defaults(func=cmd_rollover)

    activate = sub.add_parser(
        "activate-runtime",
        help=(
            "DQK-103 runtime activation surface; --check reports install-only "
            "status and refuses activation under DQK-083"
        ),
    )
    activate.add_argument(
        "--check",
        action="store_true",
        help="install-only check; does not activate a generation",
    )
    activate.add_argument(
        "--activation-permit-cid",
        type=str,
        default="",
        help="DQK-103 activation permit CID (body still required via --receipt)",
    )
    activate.add_argument(
        "--receipt",
        type=str,
        default="",
        help="path to signed runtime-activation permit JSON (DQK-103)",
    )
    activate.add_argument(
        "--plan-root",
        type=str,
        default="",
        help="expected plan root CID (required with --receipt)",
    )
    activate.add_argument(
        "--repository-tree",
        type=str,
        default="",
        help="expected repository tree identity (required with --receipt)",
    )
    activate.add_argument("--json", action="store_true")
    activate.set_defaults(func=cmd_activate_runtime)

    merges = sub.add_parser(
        "verify-merges",
        help="restart path: verify completion via merge receipts (not seed HEAD)",
    )
    merges.add_argument("--authority-dir", type=str, required=True)
    merges.add_argument("--task-id", action="append", default=[])
    merges.add_argument(
        "--seed-head",
        type=str,
        default="",
        help="ignored; seed HEAD is never required",
    )
    merges.add_argument("--json", action="store_true")
    merges.set_defaults(func=cmd_verify_merges)

    refuse = sub.add_parser(
        "refuse-files",
        help="prove transport files cannot authorize rollover",
    )
    refuse.add_argument("--file", action="append", default=[])
    refuse.add_argument("--json", action="store_true")
    refuse.set_defaults(func=cmd_refuse_files)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except GenerationRolloverError as exc:
        error = {
            "ok": False,
            "error": str(exc),
            "owner_task_id": LIFECYCLE_OWNER_TASK_ID,
            "program_id": PROGRAM_ID,
        }
        _emit(error, as_json=True, stream=sys.stderr)
        return 1
    except OSError as exc:
        error = {
            "ok": False,
            "error": str(exc),
            "owner_task_id": LIFECYCLE_OWNER_TASK_ID,
        }
        _emit(error, as_json=True, stream=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
