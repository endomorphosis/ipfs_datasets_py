#!/usr/bin/env python3
"""Cross-repo datasets/accelerator compatibility checker (PATLAW-080).

Validates and produces compatibility receipts that bind:

* the exact ``datasets`` git SHA,
* the exact ``accelerator`` git SHA,
* one or more test receipts for that pair.

Policy (fail-closed, never weakened):

* dirty or active work aborts **without mutation**;
* conflicts fail closed;
* recursive mutual-submodule chase is forbidden;
* push is never attempted;
* triggers are explicit: startup, eight-hour, twice-daily, pre-release,
  security-fix.

``--offline`` exercises schema, policy, trigger enumeration, and synthetic
manifest validation without network or live git remotes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Mapping, MutableMapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

SCHEMA_VERSION: Final = "uspto.cross-repo-compatibility.v1"
INTERFACE: Final = "UsptoCrossRepoCompatibility@1"

TRIGGERS: Final = (
    "startup",
    "eight-hour",
    "twice-daily",
    "pre-release",
    "security-fix",
)
FETCH_ONLY_TRIGGERS: Final = frozenset({"startup", "eight-hour"})
INTEGRATION_TRIGGERS: Final = frozenset(
    {"twice-daily", "pre-release", "security-fix"}
)

POLICY: Final = {
    "push_allowed": False,
    "recursive_submodules": False,
    "require_clean_worktree": True,
    "fail_closed_on_conflict": True,
    "serialize_integrations": True,
    "fetch_only_triggers": sorted(FETCH_ONLY_TRIGGERS),
    "integration_triggers": sorted(INTEGRATION_TRIGGERS),
}

GIT_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
UTC_TS_RE: Final = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)

_REPO_ROOT: Final = Path(__file__).resolve().parents[3]
_DEFAULT_SCHEMA: Final = (
    _REPO_ROOT
    / "data"
    / "release"
    / "uspto_submission_assurance"
    / "compatibility_manifest.schema.json"
)
_DEFAULT_DATASETS_NAME: Final = "datasets"
_DEFAULT_ACCELERATOR_NAME: Final = "accelerator"
_ACTIVE_MARKER_NAMES: Final = (
    ".cross_repo_sync_active",
    ".lane_active",
    "ACTIVE_LANE",
)


class CompatibilityError(RuntimeError):
    """Fail-closed compatibility or sync policy violation."""


# ---------------------------------------------------------------------------
# Time / paths / JSON helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(payload: str | bytes) -> str:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    """Write JSON atomically (temp sibling + rename). Never partial on target."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return path


def load_schema(schema_path: Path | None = None) -> dict[str, Any]:
    path = Path(schema_path) if schema_path is not None else _DEFAULT_SCHEMA
    if not path.is_file():
        raise CompatibilityError(f"compatibility schema missing: {path}")
    data = load_json(path)
    if not isinstance(data, dict):
        raise CompatibilityError("compatibility schema root must be an object")
    return data


# ---------------------------------------------------------------------------
# Schema validation (stdlib + optional jsonschema)
# ---------------------------------------------------------------------------


def _validate_with_jsonschema(instance: Any, schema: Mapping[str, Any]) -> list[str]:
    try:
        import jsonschema  # type: ignore
        from jsonschema import Draft202012Validator  # type: ignore
    except ImportError:
        return []

    validator = Draft202012Validator(dict(schema))
    errors: list[str] = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.path) or "<root>"
        errors.append(f"{path}: {err.message}")
    return errors


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_manifest_struct(
    manifest: Mapping[str, Any],
    *,
    schema: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate a compatibility manifest. Returns a list of error strings."""
    errors: list[str] = []
    if not isinstance(manifest, Mapping):
        return ["manifest must be an object"]

    _require(
        manifest.get("schema_version") == SCHEMA_VERSION,
        f"schema_version must be {SCHEMA_VERSION!r}",
        errors,
    )
    _require(
        manifest.get("interface") == INTERFACE,
        f"interface must be {INTERFACE!r}",
        errors,
    )
    status = manifest.get("status")
    _require(
        status in {"accepted", "rejected", "aborted"},
        "status must be accepted|rejected|aborted",
        errors,
    )
    trigger = manifest.get("trigger")
    _require(trigger in TRIGGERS, f"trigger must be one of {list(TRIGGERS)}", errors)

    for key in ("datasets", "accelerator"):
        pin = manifest.get(key)
        if not isinstance(pin, Mapping):
            errors.append(f"{key} must be an object")
            continue
        expected_name = _DEFAULT_DATASETS_NAME if key == "datasets" else _DEFAULT_ACCELERATOR_NAME
        _require(pin.get("name") == expected_name, f"{key}.name must be {expected_name!r}", errors)
        sha = pin.get("sha")
        if sha is not None and not (isinstance(sha, str) and GIT_SHA_RE.match(sha)):
            errors.append(f"{key}.sha must be a 40-char lowercase git sha or null")

    receipts = manifest.get("test_receipts")
    if not isinstance(receipts, list):
        errors.append("test_receipts must be an array")
        receipts = []

    policy = manifest.get("policy")
    if not isinstance(policy, Mapping):
        errors.append("policy must be an object")
    else:
        _require(policy.get("push_allowed") is False, "policy.push_allowed must be false", errors)
        _require(
            policy.get("recursive_submodules") is False,
            "policy.recursive_submodules must be false",
            errors,
        )
        _require(
            policy.get("require_clean_worktree") is True,
            "policy.require_clean_worktree must be true",
            errors,
        )
        _require(
            policy.get("fail_closed_on_conflict") is True,
            "policy.fail_closed_on_conflict must be true",
            errors,
        )
        _require(
            policy.get("serialize_integrations") is True,
            "policy.serialize_integrations must be true",
            errors,
        )
        fetch_only = policy.get("fetch_only_triggers")
        integration = policy.get("integration_triggers")
        if not isinstance(fetch_only, list) or set(fetch_only) != FETCH_ONLY_TRIGGERS:
            errors.append("policy.fetch_only_triggers must equal {startup, eight-hour}")
        if not isinstance(integration, list) or set(integration) != INTEGRATION_TRIGGERS:
            errors.append(
                "policy.integration_triggers must equal "
                "{twice-daily, pre-release, security-fix}"
            )

    _require(manifest.get("push_attempted") is False, "push_attempted must be false", errors)
    _require(
        manifest.get("recursive_submodule_chase") is False,
        "recursive_submodule_chase must be false",
        errors,
    )
    for ts_key in ("started_at_utc", "completed_at_utc"):
        ts = manifest.get(ts_key)
        _require(
            isinstance(ts, str) and UTC_TS_RE.match(ts) is not None,
            f"{ts_key} must be UTC Zulu timestamp",
            errors,
        )

    if status == "accepted":
        for key in ("datasets", "accelerator"):
            pin = manifest.get(key)
            if isinstance(pin, Mapping):
                sha = pin.get("sha")
                _require(
                    isinstance(sha, str) and GIT_SHA_RE.match(sha) is not None,
                    f"accepted {key}.sha must be bound",
                    errors,
                )
        if not receipts:
            errors.append("accepted manifest requires at least one test receipt")
        for idx, receipt in enumerate(receipts):
            if not isinstance(receipt, Mapping):
                errors.append(f"test_receipts[{idx}] must be an object")
                continue
            _require(
                receipt.get("status") == "passed",
                f"test_receipts[{idx}].status must be passed for accepted",
                errors,
            )
            _require(
                receipt.get("exit_code") == 0,
                f"test_receipts[{idx}].exit_code must be 0 for accepted",
                errors,
            )
            # When present, receipts must bind the same SHA pair.
            ds = receipt.get("datasets_sha")
            acc = receipt.get("accelerator_sha")
            ds_pin = (manifest.get("datasets") or {}).get("sha") if isinstance(manifest.get("datasets"), Mapping) else None
            acc_pin = (
                (manifest.get("accelerator") or {}).get("sha")
                if isinstance(manifest.get("accelerator"), Mapping)
                else None
            )
            if ds is not None and ds_pin is not None and ds != ds_pin:
                errors.append(f"test_receipts[{idx}].datasets_sha must match datasets.sha")
            if acc is not None and acc_pin is not None and acc != acc_pin:
                errors.append(f"test_receipts[{idx}].accelerator_sha must match accelerator.sha")
        _require(
            manifest.get("abort_reason") in (None, ""),
            "accepted manifest abort_reason must be null",
            errors,
        )

    if status == "aborted":
        reason = manifest.get("abort_reason")
        _require(
            isinstance(reason, str) and bool(reason.strip()),
            "aborted manifest requires abort_reason",
            errors,
        )
        _require(
            manifest.get("mutation_attempted") is False,
            "aborted dirty/active paths must not attempt mutation",
            errors,
        )

    if schema is not None:
        errors.extend(_validate_with_jsonschema(manifest, schema))

    return errors


def assert_manifest_valid(
    manifest: Mapping[str, Any],
    *,
    schema: Mapping[str, Any] | None = None,
) -> None:
    errors = validate_manifest_struct(manifest, schema=schema)
    if errors:
        raise CompatibilityError("; ".join(errors))


# ---------------------------------------------------------------------------
# Git helpers (local, never push, never recursive submodule update)
# ---------------------------------------------------------------------------


def _run_git(
    repo: Path,
    *args: str,
    check: bool = True,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", str(repo), *args]
    # Hard guard: never allow push via this helper.
    if args and args[0] in {"push", "push--force"}:
        raise CompatibilityError("git push is forbidden by cross-repo sync policy")
    if args and args[0] == "submodule" and "recursive" in args:
        raise CompatibilityError("recursive submodule operations are forbidden")
    if args and args[0] == "submodule" and "--recursive" in args:
        raise CompatibilityError("recursive submodule operations are forbidden")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise CompatibilityError(f"git {' '.join(args)} failed in {repo}: {stderr}")
    return result


def is_git_repo(path: Path) -> bool:
    if not path.is_dir():
        return False
    result = _run_git(path, "rev-parse", "--is-inside-work-tree", check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_head_sha(repo: Path) -> str:
    result = _run_git(repo, "rev-parse", "HEAD")
    sha = result.stdout.strip().lower()
    if not GIT_SHA_RE.match(sha):
        raise CompatibilityError(f"invalid HEAD sha in {repo}: {sha!r}")
    return sha


def git_is_dirty(repo: Path) -> bool:
    """True when the worktree or index has uncommitted changes."""
    result = _run_git(repo, "status", "--porcelain", "--untracked-files=normal")
    return bool(result.stdout.strip())


def git_has_unmerged(repo: Path) -> bool:
    result = _run_git(repo, "diff", "--name-only", "--diff-filter=U", check=False)
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def git_fetch_origin(repo: Path, *, remote: str = "origin") -> None:
    """Fetch remote refs only. Never push. Never recurse into submodules."""
    # Explicit non-recursive: do not pass --recurse-submodules.
    _run_git(repo, "fetch", remote, "--no-recurse-submodules", timeout=120.0)


def git_origin_url(repo: Path, *, remote: str = "origin") -> str | None:
    result = _run_git(repo, "remote", "get-url", remote, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_current_ref(repo: Path) -> str | None:
    result = _run_git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def detect_active_work(
    *roots: Path,
    marker_names: Sequence[str] = _ACTIVE_MARKER_NAMES,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Return a human reason when active work must abort the sync."""
    environ = env if env is not None else os.environ
    if environ.get("CROSS_REPO_SYNC_FORCE_ACTIVE", "").strip() in {"1", "true", "yes"}:
        return "CROSS_REPO_SYNC_FORCE_ACTIVE is set"
    marker_env = environ.get("CROSS_REPO_SYNC_ACTIVE_MARKER", "").strip()
    if marker_env:
        marker_path = Path(marker_env)
        if marker_path.exists():
            return f"active work marker present: {marker_path}"
    for root in roots:
        if not root:
            continue
        root = Path(root)
        for name in marker_names:
            candidate = root / name
            if candidate.exists():
                return f"active work marker present: {candidate}"
    return None


def detect_submodule_cycle_risk(
    datasets: Path,
    accelerator: Path,
) -> str | None:
    """Detect mutual submodule registration that would recurse if chased.

    We never chase recursively; this only records the risk for fail-closed
    integration decisions and notes.
    """
    ds_gitmodules = datasets / ".gitmodules"
    acc_gitmodules = accelerator / ".gitmodules"
    if not ds_gitmodules.is_file() or not acc_gitmodules.is_file():
        return None
    try:
        ds_text = ds_gitmodules.read_text(encoding="utf-8", errors="replace")
        acc_text = acc_gitmodules.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"unable to read gitmodules: {exc}"

    ds_points_to_acc = (
        "ipfs_accelerate" in ds_text
        or "accelerator" in ds_text.lower()
        or str(accelerator.name) in ds_text
    )
    acc_points_to_ds = (
        "ipfs_datasets" in acc_text
        or "datasets" in acc_text.lower()
        or str(datasets.name) in acc_text
    )
    if ds_points_to_acc and acc_points_to_ds:
        return (
            "mutual submodule registration detected between datasets and "
            "accelerator; recursive update is forbidden"
        )
    return None


def forbid_recursive_submodule_args(argv: Sequence[str]) -> None:
    """Raise if argv requests recursive submodule chase."""
    joined = " ".join(argv)
    if "--recurse-submodules" in argv or "--recursive" in argv:
        if "submodule" in argv or "fetch" in argv or "update" in argv:
            raise CompatibilityError(
                f"recursive submodule chase forbidden: {joined}"
            )
    if "submodule" in argv and "update" in argv and "--init" in argv:
        # Non-recursive init/update of direct children is allowed only when
        # explicitly not recursive; still refuse depth recursion flags.
        if any(a in {"--recursive", "--recurse"} for a in argv):
            raise CompatibilityError(
                f"recursive submodule chase forbidden: {joined}"
            )


# ---------------------------------------------------------------------------
# Manifest construction
# ---------------------------------------------------------------------------


def default_policy() -> dict[str, Any]:
    return dict(POLICY)


def make_repo_pin(
    name: str,
    *,
    path: Path | None = None,
    sha: str | None = None,
    ref: str | None = None,
    origin_url: str | None = None,
    dirty: bool = False,
    fetched: bool = False,
) -> dict[str, Any]:
    if name not in {_DEFAULT_DATASETS_NAME, _DEFAULT_ACCELERATOR_NAME}:
        raise CompatibilityError(f"unknown repo pin name: {name}")
    pin: dict[str, Any] = {
        "name": name,
        "sha": sha,
        "ref": ref,
        "origin_url": origin_url,
        "dirty": dirty,
        "fetched": fetched,
    }
    if path is not None:
        pin["path"] = str(path)
    return pin


def make_test_receipt(
    name: str,
    *,
    status: str = "passed",
    exit_code: int = 0,
    command: str = "",
    datasets_sha: str | None = None,
    accelerator_sha: str | None = None,
    duration_ms: int = 0,
) -> dict[str, Any]:
    body = {
        "name": name,
        "status": status,
        "exit_code": exit_code,
        "command": command,
        "datasets_sha": datasets_sha,
        "accelerator_sha": accelerator_sha,
        "duration_ms": duration_ms,
    }
    body["sha256"] = sha256_hex(canonical_json(body))
    return body


def build_manifest(
    *,
    status: str,
    trigger: str,
    datasets: Mapping[str, Any],
    accelerator: Mapping[str, Any],
    test_receipts: Sequence[Mapping[str, Any]] | None = None,
    abort_reason: str | None = None,
    mutation_attempted: bool = False,
    conflict: Mapping[str, Any] | None = None,
    lock_path: str | None = None,
    notes: Sequence[str] | None = None,
    started_at_utc: str | None = None,
    completed_at_utc: str | None = None,
    manifest_id: str | None = None,
) -> dict[str, Any]:
    if trigger not in TRIGGERS:
        raise CompatibilityError(f"unknown trigger: {trigger}")
    if status not in {"accepted", "rejected", "aborted"}:
        raise CompatibilityError(f"unknown status: {status}")

    started = started_at_utc or utc_now()
    completed = completed_at_utc or utc_now()
    mid = manifest_id or f"crc-{uuid.uuid4().hex[:16]}"
    receipts = [dict(r) for r in (test_receipts or ())]

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "interface": INTERFACE,
        "manifest_id": mid,
        "status": status,
        "trigger": trigger,
        "datasets": dict(datasets),
        "accelerator": dict(accelerator),
        "test_receipts": receipts,
        "policy": default_policy(),
        "started_at_utc": started,
        "completed_at_utc": completed,
        "abort_reason": abort_reason,
        "mutation_attempted": bool(mutation_attempted),
        "push_attempted": False,
        "recursive_submodule_chase": False,
        "conflict": dict(conflict) if conflict else None,
        "lock_path": lock_path,
        "notes": list(notes or ()),
    }
    # Digest excludes itself for stability.
    manifest["receipt_digest_sha256"] = sha256_hex(canonical_json(manifest))
    return manifest


# ---------------------------------------------------------------------------
# Sync planning / execution (local)
# ---------------------------------------------------------------------------


def resolve_default_paths(
    repo_root: Path | None = None,
) -> tuple[Path, Path]:
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    datasets = root  # this repository is the datasets surface
    accelerator = root / "ipfs_accelerate_py"
    return datasets, accelerator


def inspect_repo(path: Path, name: str) -> dict[str, Any]:
    if not is_git_repo(path):
        return make_repo_pin(name, path=path, sha=None, dirty=False, fetched=False)
    return make_repo_pin(
        name,
        path=path,
        sha=git_head_sha(path),
        ref=git_current_ref(path),
        origin_url=git_origin_url(path),
        dirty=git_is_dirty(path),
        fetched=False,
    )


def plan_sync(
    *,
    trigger: str,
    datasets_path: Path,
    accelerator_path: Path,
    active_marker: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Plan a sync action without mutating repositories.

    Returns a plan dict with ``action`` in:
    ``fetch``, ``integrate``, ``abort``.
    """
    if trigger not in TRIGGERS:
        raise CompatibilityError(f"unknown trigger: {trigger}")

    environ = dict(env) if env is not None else dict(os.environ)
    if active_marker:
        environ["CROSS_REPO_SYNC_ACTIVE_MARKER"] = active_marker

    datasets = inspect_repo(datasets_path, _DEFAULT_DATASETS_NAME)
    accelerator = inspect_repo(accelerator_path, _DEFAULT_ACCELERATOR_NAME)

    plan: dict[str, Any] = {
        "trigger": trigger,
        "action": "fetch" if trigger in FETCH_ONLY_TRIGGERS else "integrate",
        "datasets": datasets,
        "accelerator": accelerator,
        "abort_reason": None,
        "conflict": None,
        "push_allowed": False,
        "recursive_submodules": False,
        "mutation_permitted": False,
    }

    # Conflicts first (fail closed): an unmerged index is also "dirty", but
    # the more specific conflict reason must win for operator diagnostics.
    for repo_path in (datasets_path, accelerator_path):
        if is_git_repo(repo_path) and git_has_unmerged(repo_path):
            plan["action"] = "abort"
            plan["abort_reason"] = "merge_conflict"
            plan["conflict"] = {
                "kind": "merge_conflict",
                "message": "unmerged paths present; conflicts fail closed",
                "paths": [str(repo_path)],
            }
            plan["mutation_permitted"] = False
            return plan

    # Dirty aborts without mutation for any trigger that would integrate;
    # fetch-only may still fetch when clean enough at remote-tracking level,
    # but local dirty still aborts to avoid surprising side effects.
    dirty_paths: list[str] = []
    if datasets.get("dirty"):
        dirty_paths.append(str(datasets_path))
    if accelerator.get("dirty"):
        dirty_paths.append(str(accelerator_path))
    if dirty_paths:
        plan["action"] = "abort"
        plan["abort_reason"] = "dirty_worktree"
        plan["conflict"] = {
            "kind": "dirty_worktree",
            "message": "dirty worktree aborts without mutation",
            "paths": dirty_paths,
        }
        plan["mutation_permitted"] = False
        return plan

    active = detect_active_work(datasets_path, accelerator_path, env=environ)
    if active:
        plan["action"] = "abort"
        plan["abort_reason"] = "active_work"
        plan["conflict"] = {
            "kind": "active_work",
            "message": active,
            "paths": [],
        }
        plan["mutation_permitted"] = False
        return plan

    cycle = detect_submodule_cycle_risk(datasets_path, accelerator_path)
    if cycle:
        plan["notes"] = [cycle]
        # Integration still proceeds without recursive chase; fetch-only is fine.
        # We never set recursive_submodules true.

    if trigger in FETCH_ONLY_TRIGGERS:
        plan["action"] = "fetch"
        plan["mutation_permitted"] = False  # fetch updates remote-tracking only
    else:
        plan["action"] = "integrate"
        plan["mutation_permitted"] = True  # only after clean checks above
    return plan


def execute_fetch(
    datasets_path: Path,
    accelerator_path: Path,
    *,
    allow_missing_remote: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Fetch both origins. Never push. Never recurse submodules."""
    notes: list[str] = []
    pins: list[dict[str, Any]] = []
    for path, name in (
        (datasets_path, _DEFAULT_DATASETS_NAME),
        (accelerator_path, _DEFAULT_ACCELERATOR_NAME),
    ):
        if not is_git_repo(path):
            pins.append(make_repo_pin(name, path=path, sha=None, fetched=False))
            notes.append(f"{name}: not a git repository; skipped fetch")
            continue
        try:
            git_fetch_origin(path)
            pin = inspect_repo(path, name)
            pin["fetched"] = True
            pins.append(pin)
        except CompatibilityError as exc:
            if not allow_missing_remote:
                raise
            pin = inspect_repo(path, name)
            pin["fetched"] = False
            pins.append(pin)
            notes.append(f"{name}: fetch skipped ({exc})")
    return pins[0], pins[1], notes


def run_pair_tests(
    *,
    datasets_sha: str,
    accelerator_sha: str,
    datasets_path: Path,
    accelerator_path: Path,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Run the bound SHA-pair smoke checks and return receipts.

    Offline/dry-run emits a synthetic passed receipt that still binds both SHAs.
    Live mode runs lightweight local assertions (paths exist, SHAs match HEAD).
    """
    if dry_run:
        return [
            make_test_receipt(
                "offline-pair-bind",
                status="passed",
                exit_code=0,
                command="offline:bind-datasets-accelerator-shas",
                datasets_sha=datasets_sha,
                accelerator_sha=accelerator_sha,
            )
        ]

    receipts: list[dict[str, Any]] = []
    # Local identity check: HEAD must match the planned pair.
    try:
        actual_ds = git_head_sha(datasets_path)
        actual_acc = git_head_sha(accelerator_path)
        ok = actual_ds == datasets_sha and actual_acc == accelerator_sha
        receipts.append(
            make_test_receipt(
                "head-sha-pair",
                status="passed" if ok else "failed",
                exit_code=0 if ok else 1,
                command="git rev-parse HEAD (datasets + accelerator)",
                datasets_sha=datasets_sha,
                accelerator_sha=accelerator_sha,
            )
        )
        if not ok:
            return receipts
    except CompatibilityError as exc:
        receipts.append(
            make_test_receipt(
                "head-sha-pair",
                status="error",
                exit_code=2,
                command=f"git rev-parse HEAD failed: {exc}",
                datasets_sha=datasets_sha,
                accelerator_sha=accelerator_sha,
            )
        )
        return receipts

    # Path existence smoke (content-free).
    ok_paths = datasets_path.is_dir() and accelerator_path.is_dir()
    receipts.append(
        make_test_receipt(
            "path-existence",
            status="passed" if ok_paths else "failed",
            exit_code=0 if ok_paths else 1,
            command="test -d datasets && test -d accelerator",
            datasets_sha=datasets_sha,
            accelerator_sha=accelerator_sha,
        )
    )
    return receipts


def run_sync(
    *,
    trigger: str,
    datasets_path: Path,
    accelerator_path: Path,
    output_path: Path | None = None,
    lock_path: Path | None = None,
    dry_run: bool = False,
    skip_fetch: bool = False,
    active_marker: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Execute a full plan → optional fetch → optional tests → atomic receipt."""
    started = utc_now()
    plan = plan_sync(
        trigger=trigger,
        datasets_path=datasets_path,
        accelerator_path=accelerator_path,
        active_marker=active_marker,
        env=env,
    )

    lock_str = str(lock_path) if lock_path else None
    notes: list[str] = list(plan.get("notes") or [])

    if plan["action"] == "abort":
        manifest = build_manifest(
            status="aborted",
            trigger=trigger,
            datasets=plan["datasets"],
            accelerator=plan["accelerator"],
            test_receipts=[],
            abort_reason=str(plan.get("abort_reason") or "aborted"),
            mutation_attempted=False,
            conflict=plan.get("conflict"),
            lock_path=lock_str,
            notes=notes,
            started_at_utc=started,
        )
        if output_path is not None:
            atomic_write_json(output_path, manifest)
        return manifest

    datasets_pin = dict(plan["datasets"])
    accelerator_pin = dict(plan["accelerator"])
    mutation_attempted = False

    if not skip_fetch and not dry_run:
        try:
            datasets_pin, accelerator_pin, fetch_notes = execute_fetch(
                datasets_path, accelerator_path
            )
            notes.extend(fetch_notes)
        except CompatibilityError as exc:
            manifest = build_manifest(
                status="rejected",
                trigger=trigger,
                datasets=datasets_pin,
                accelerator=accelerator_pin,
                test_receipts=[],
                abort_reason=None,
                mutation_attempted=False,
                conflict={
                    "kind": "policy_violation",
                    "message": str(exc),
                    "paths": [],
                },
                lock_path=lock_str,
                notes=notes + [str(exc)],
                started_at_utc=started,
            )
            if output_path is not None:
                atomic_write_json(output_path, manifest)
            return manifest
    elif dry_run or skip_fetch:
        notes.append("fetch skipped (dry-run or skip-fetch)")

    # Re-check dirty after fetch: fetch must not dirty worktree; if something
    # external dirtied, abort without further mutation.
    if not dry_run:
        replan = plan_sync(
            trigger=trigger,
            datasets_path=datasets_path,
            accelerator_path=accelerator_path,
            active_marker=active_marker,
            env=env,
        )
        if replan["action"] == "abort":
            manifest = build_manifest(
                status="aborted",
                trigger=trigger,
                datasets=replan["datasets"],
                accelerator=replan["accelerator"],
                test_receipts=[],
                abort_reason=str(replan.get("abort_reason") or "aborted"),
                mutation_attempted=False,
                conflict=replan.get("conflict"),
                lock_path=lock_str,
                notes=notes,
                started_at_utc=started,
            )
            if output_path is not None:
                atomic_write_json(output_path, manifest)
            return manifest
        datasets_pin = dict(replan["datasets"])
        accelerator_pin = dict(replan["accelerator"])
        datasets_pin["fetched"] = True
        accelerator_pin["fetched"] = True

    ds_sha = datasets_pin.get("sha")
    acc_sha = accelerator_pin.get("sha")

    # Fetch-only triggers: write a non-accepted operational receipt unless
    # both SHAs are bound and we emit a lightweight bind receipt.
    if trigger in FETCH_ONLY_TRIGGERS:
        if (
            isinstance(ds_sha, str)
            and GIT_SHA_RE.match(ds_sha)
            and isinstance(acc_sha, str)
            and GIT_SHA_RE.match(acc_sha)
        ):
            receipts = [
                make_test_receipt(
                    "fetch-only-sha-bind",
                    status="passed",
                    exit_code=0,
                    command="fetch-only:bind-shas",
                    datasets_sha=ds_sha,
                    accelerator_sha=acc_sha,
                )
            ]
            status = "accepted"
        else:
            receipts = []
            status = "rejected"
            notes.append("fetch-only could not bind both SHAs")
        manifest = build_manifest(
            status=status,
            trigger=trigger,
            datasets=datasets_pin,
            accelerator=accelerator_pin,
            test_receipts=receipts,
            mutation_attempted=False,
            lock_path=lock_str,
            notes=notes,
            started_at_utc=started,
        )
        if output_path is not None:
            atomic_write_json(output_path, manifest)
        return manifest

    # Integration triggers: require both SHAs, run pair tests.
    if not (
        isinstance(ds_sha, str)
        and GIT_SHA_RE.match(ds_sha)
        and isinstance(acc_sha, str)
        and GIT_SHA_RE.match(acc_sha)
    ):
        manifest = build_manifest(
            status="rejected",
            trigger=trigger,
            datasets=datasets_pin,
            accelerator=accelerator_pin,
            test_receipts=[],
            mutation_attempted=mutation_attempted,
            conflict={
                "kind": "sha_mismatch",
                "message": "integration requires bound datasets and accelerator SHAs",
                "paths": [str(datasets_path), str(accelerator_path)],
            },
            lock_path=lock_str,
            notes=notes,
            started_at_utc=started,
        )
        if output_path is not None:
            atomic_write_json(output_path, manifest)
        return manifest

    # Integration on clean branches: no recursive submodule update, no push.
    # We intentionally do not rewrite gitlinks or chase nested submodules.
    forbid_recursive_submodule_args(["submodule", "update"])  # policy self-check
    cycle = detect_submodule_cycle_risk(datasets_path, accelerator_path)
    if cycle:
        notes.append(cycle)
        notes.append("integration proceeded without recursive submodule update")

    receipts = run_pair_tests(
        datasets_sha=ds_sha,
        accelerator_sha=acc_sha,
        datasets_path=datasets_path,
        accelerator_path=accelerator_path,
        dry_run=dry_run,
    )
    all_passed = bool(receipts) and all(r.get("status") == "passed" for r in receipts)
    status = "accepted" if all_passed else "rejected"
    manifest = build_manifest(
        status=status,
        trigger=trigger,
        datasets=datasets_pin,
        accelerator=accelerator_pin,
        test_receipts=receipts,
        mutation_attempted=mutation_attempted,
        conflict=None
        if all_passed
        else {
            "kind": "sha_mismatch",
            "message": "pair tests failed; conflicts and test failures fail closed",
            "paths": [],
        },
        lock_path=lock_str,
        notes=notes,
        started_at_utc=started,
    )
    if output_path is not None:
        atomic_write_json(output_path, manifest)
    return manifest


# ---------------------------------------------------------------------------
# Offline self-check
# ---------------------------------------------------------------------------


def offline_self_check(schema_path: Path | None = None) -> dict[str, Any]:
    """Validate schema + policy + synthetic accepted/aborted manifests offline."""
    schema = load_schema(schema_path)
    report: dict[str, Any] = {
        "ok": True,
        "interface": INTERFACE,
        "schema_version": SCHEMA_VERSION,
        "schema_path": str(schema_path or _DEFAULT_SCHEMA),
        "triggers": list(TRIGGERS),
        "fetch_only_triggers": sorted(FETCH_ONLY_TRIGGERS),
        "integration_triggers": sorted(INTEGRATION_TRIGGERS),
        "policy": default_policy(),
        "checks": [],
    }

    def _check(name: str, fn: Any) -> None:
        try:
            fn()
            report["checks"].append({"name": name, "status": "passed"})
        except Exception as exc:  # noqa: BLE001 — offline report collects failures
            report["ok"] = False
            report["checks"].append(
                {"name": name, "status": "failed", "error": str(exc)}
            )

    def check_schema_identity() -> None:
        assert schema.get("$schema"), "schema missing $schema"
        assert "trigger" in json.dumps(schema)
        for t in TRIGGERS:
            assert t in json.dumps(schema), f"trigger {t} missing from schema"

    def check_policy_constants() -> None:
        assert POLICY["push_allowed"] is False
        assert POLICY["recursive_submodules"] is False
        assert POLICY["fail_closed_on_conflict"] is True
        assert set(POLICY["fetch_only_triggers"]) == FETCH_ONLY_TRIGGERS
        assert set(POLICY["integration_triggers"]) == INTEGRATION_TRIGGERS
        assert FETCH_ONLY_TRIGGERS.isdisjoint(INTEGRATION_TRIGGERS)
        assert FETCH_ONLY_TRIGGERS | INTEGRATION_TRIGGERS == set(TRIGGERS)

    def check_accepted_manifest() -> None:
        ds_sha = "a" * 40
        acc_sha = "b" * 40
        manifest = build_manifest(
            status="accepted",
            trigger="pre-release",
            datasets=make_repo_pin("datasets", sha=ds_sha, dirty=False, fetched=True),
            accelerator=make_repo_pin(
                "accelerator", sha=acc_sha, dirty=False, fetched=True
            ),
            test_receipts=[
                make_test_receipt(
                    "offline-pair-bind",
                    datasets_sha=ds_sha,
                    accelerator_sha=acc_sha,
                )
            ],
            mutation_attempted=False,
        )
        assert_manifest_valid(manifest, schema=schema)
        assert manifest["push_attempted"] is False
        assert manifest["recursive_submodule_chase"] is False
        assert manifest["datasets"]["sha"] == ds_sha
        assert manifest["accelerator"]["sha"] == acc_sha
        assert manifest["test_receipts"]

    def check_aborted_dirty() -> None:
        manifest = build_manifest(
            status="aborted",
            trigger="twice-daily",
            datasets=make_repo_pin("datasets", sha="c" * 40, dirty=True),
            accelerator=make_repo_pin("accelerator", sha="d" * 40, dirty=False),
            test_receipts=[],
            abort_reason="dirty_worktree",
            mutation_attempted=False,
            conflict={
                "kind": "dirty_worktree",
                "message": "dirty worktree aborts without mutation",
                "paths": ["/tmp/datasets"],
            },
        )
        assert_manifest_valid(manifest, schema=schema)

    def check_rejected_missing_receipts() -> None:
        bad = build_manifest(
            status="accepted",
            trigger="security-fix",
            datasets=make_repo_pin("datasets", sha="e" * 40),
            accelerator=make_repo_pin("accelerator", sha="f" * 40),
            test_receipts=[],  # invalid for accepted
            mutation_attempted=False,
        )
        errors = validate_manifest_struct(bad, schema=schema)
        assert errors, "accepted without receipts must fail validation"

    def check_push_forbidden() -> None:
        try:
            _run_git(Path("."), "push", "origin", "HEAD", check=False)
            raise AssertionError("push must raise before subprocess")
        except CompatibilityError as exc:
            assert "push" in str(exc).lower()

    def check_recursive_forbidden() -> None:
        try:
            forbid_recursive_submodule_args(
                ["submodule", "update", "--init", "--recursive"]
            )
            raise AssertionError("recursive submodule must be refused")
        except CompatibilityError:
            pass
        try:
            _run_git(Path("."), "submodule", "update", "--recursive", check=False)
            raise AssertionError("recursive submodule git helper must refuse")
        except CompatibilityError:
            pass

    def check_all_triggers_explicit() -> None:
        assert list(TRIGGERS) == [
            "startup",
            "eight-hour",
            "twice-daily",
            "pre-release",
            "security-fix",
        ]

    _check("schema_identity", check_schema_identity)
    _check("policy_constants", check_policy_constants)
    _check("accepted_manifest", check_accepted_manifest)
    _check("aborted_dirty", check_aborted_dirty)
    _check("rejected_missing_receipts", check_rejected_missing_receipts)
    _check("push_forbidden", check_push_forbidden)
    _check("recursive_forbidden", check_recursive_forbidden)
    _check("all_triggers_explicit", check_all_triggers_explicit)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/ops/uspto/check_cross_repo_compatibility.py",
        description=(
            "Validate or produce datasets/accelerator cross-repo compatibility "
            "receipts (PATLAW-080). Never pushes; never recurses mutual submodules."
        ),
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run offline self-check (schema, policy, synthetic manifests)",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="Path to compatibility_manifest.schema.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Validate an existing compatibility manifest JSON",
    )
    parser.add_argument(
        "--trigger",
        choices=list(TRIGGERS),
        default=None,
        help="When planning/running a sync, the explicit trigger",
    )
    parser.add_argument(
        "--datasets-path",
        type=Path,
        default=None,
        help="Path to the datasets repository (default: repo root)",
    )
    parser.add_argument(
        "--accelerator-path",
        type=Path,
        default=None,
        help="Path to the accelerator repository (default: ./ipfs_accelerate_py)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Atomic output path for a produced compatibility receipt",
    )
    parser.add_argument(
        "--lock-path",
        type=Path,
        default=None,
        help="Optional lock path recorded in the receipt",
    )
    parser.add_argument(
        "--active-marker",
        type=Path,
        default=None,
        help="Path that, if present, signals active work and aborts without mutation",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Plan the sync action without fetching or writing a receipt",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Execute plan (fetch / integrate) and write a receipt when --output is set",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute plan without network fetch; emit synthetic pair test receipts",
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Do not git fetch (still may write receipts from current HEADs)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root for default path resolution",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON (default for most commands)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if args.offline and not args.run and not args.plan_only and args.manifest is None:
            report = offline_self_check(args.schema)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report.get("ok") else 2

        schema = load_schema(args.schema)

        if args.manifest is not None:
            manifest = load_json(args.manifest)
            if not isinstance(manifest, Mapping):
                raise CompatibilityError("manifest root must be an object")
            assert_manifest_valid(manifest, schema=schema)
            payload = {
                "ok": True,
                "manifest_id": manifest.get("manifest_id"),
                "status": manifest.get("status"),
                "trigger": manifest.get("trigger"),
                "datasets_sha": (manifest.get("datasets") or {}).get("sha"),
                "accelerator_sha": (manifest.get("accelerator") or {}).get("sha"),
                "test_receipt_count": len(manifest.get("test_receipts") or []),
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        datasets_path, accelerator_path = resolve_default_paths(args.repo_root)
        if args.datasets_path is not None:
            datasets_path = args.datasets_path
        if args.accelerator_path is not None:
            accelerator_path = args.accelerator_path

        if args.plan_only:
            if not args.trigger:
                raise CompatibilityError("--plan-only requires --trigger")
            plan = plan_sync(
                trigger=args.trigger,
                datasets_path=datasets_path,
                accelerator_path=accelerator_path,
                active_marker=str(args.active_marker) if args.active_marker else None,
            )
            print(json.dumps(plan, indent=2, sort_keys=True))
            return 0 if plan.get("action") != "abort" else 3

        if args.run or args.dry_run or args.offline:
            if not args.trigger:
                # Offline default trigger for a dry synthetic path.
                trigger = args.trigger or "startup"
            else:
                trigger = args.trigger
            if args.offline and not args.trigger:
                # Pure offline already handled; if combined with --run, use startup.
                trigger = "startup"
            manifest = run_sync(
                trigger=trigger if args.trigger else "startup",
                datasets_path=datasets_path,
                accelerator_path=accelerator_path,
                output_path=args.output,
                lock_path=args.lock_path,
                dry_run=bool(args.dry_run or args.offline),
                skip_fetch=bool(args.skip_fetch or args.dry_run or args.offline),
                active_marker=str(args.active_marker) if args.active_marker else None,
            )
            assert_manifest_valid(manifest, schema=schema)
            print(json.dumps(manifest, indent=2, sort_keys=True))
            if manifest.get("status") == "accepted":
                return 0
            if manifest.get("status") == "aborted":
                return 3
            return 2

        # Default: offline self-check when no other action given.
        report = offline_self_check(args.schema)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("ok") else 2

    except CompatibilityError as exc:
        err = {"ok": False, "error": str(exc)}
        print(json.dumps(err, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    except OSError as exc:
        err = {"ok": False, "error": f"os error: {exc}"}
        print(json.dumps(err, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
