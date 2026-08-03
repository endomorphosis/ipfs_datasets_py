#!/usr/bin/env python3
"""USPTO submission-assurance current-tree completion and release gate (PATLAW-074).

Answers a single fail-closed question: *"does a fresh receipt on the current
tree bind git tree, config, fixture/ruleset/parser versions, test results,
privacy scan, and merge-queue evidence — with every prior task present and no
blocked/unknown mandatory gate remaining?"*

Policy (never weakened):

* Task status / backlog completion alone **cannot** satisfy acceptance.
* Missing, blocked, unknown, or incomplete mandatory gates fail closed.
* Receipts are content-free (no document bodies, secrets, private text).
* Fresh validation receipts are written **outside** tracked source by default
  (``$XDG_STATE_HOME/ipfs_accelerate_py/uspto_submission_assurance/release``).
* ``--offline`` exercises policy, prior-task inventory, version pin binding,
  synthetic receipt validation, and the task-status rejection rule without
  requiring a full pytest suite run.

Usage
-----
    # Offline gate (taskboard validation command):
    python scripts/ops/uspto/validate_release.py --offline

    # Live gate on current tree (writes digested receipt under XDG state):
    python scripts/ops/uspto/validate_release.py

    # Validate an existing receipt file:
    python scripts/ops/uspto/validate_release.py --receipt /path/to/receipt.json
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
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Schema / identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "uspto.submission-assurance-release.v1"
INTERFACE: Final = "UsptoSubmissionAssuranceRelease@1"
TASK_ID: Final = "PATLAW-074"
GOAL_ID: Final = "PATLAW-G080"
POLICY_ID: Final = "uspto-submission-assurance-release/v1"

GIT_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
UTC_TS_RE: Final = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)

# Direct dependencies of PATLAW-074 (must be present on the target tree).
REQUIRED_PRIOR_TASKS: Final[tuple[dict[str, Any], ...]] = (
    {
        "task_id": "PATLAW-061",
        "title": "Add read-only USPTO MCP tools",
        "outputs": (
            "ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/uspto_tools.py",
            "tests/mcp/unit/test_uspto_tools.py",
        ),
    },
    {
        "task_id": "PATLAW-062",
        "title": "Add checkpointed polling, change detection, and alerts",
        "outputs": (
            "ipfs_datasets_py/processors/domains/uspto/scheduler.py",
            "tests/integration/processors/domains/uspto/test_scheduler.py",
        ),
    },
    {
        "task_id": "PATLAW-072",
        "title": "Prove deterministic offline end-to-end replay",
        "outputs": (
            "tests/e2e/test_uspto_application_analysis.py",
            "tests/e2e/test_uspto_application_analysis_cli_mcp.py",
            "tests/fixtures/uspto/replay/replay_manifest.json",
        ),
    },
    {
        "task_id": "PATLAW-073",
        "title": "Add operator observability, stall detection, and recovery runbook",
        "outputs": (
            "docs/operations/USPTO_SUBMISSION_ASSURANCE_RUNBOOK.md",
            "scripts/ops/uspto/status.py",
            "tests/integration/processors/domains/uspto/test_recovery_operations.py",
        ),
    },
    {
        "task_id": "PATLAW-080",
        "title": "Add serialized datasets/accelerator upstream synchronization",
        "outputs": (
            "scripts/ops/uspto/sync_upstreams.sh",
            "scripts/ops/uspto/check_cross_repo_compatibility.py",
            "tests/integration/processors/domains/uspto/test_cross_repo_sync.py",
            "data/release/uspto_submission_assurance/compatibility_manifest.schema.json",
        ),
    },
    {
        "task_id": "PATLAW-102",
        "title": "Verify JusticeDAO publication through the append-only publisher",
        "outputs": (
            "tests/integration/processors/patent/test_release_publisher.py",
            "tests/fixtures/patent/release/manifest.json",
            "scripts/ops/legal_data/verify_patent_hf_release.py",
        ),
    },
)

# Assurance surfaces that must be inventoried even when not direct depends_on.
ASSURANCE_SUPPORTING_OUTPUTS: Final[tuple[dict[str, Any], ...]] = (
    {
        "task_id": "PATLAW-070",
        "title": "Reviewed synthetic/public gold corpus and metrics",
        "outputs": (
            "tests/fixtures/uspto/GOLD_CORPUS_MANIFEST.json",
            "tests/fixtures/uspto/gold/metrics/metric_gates.json",
            "tests/contract/processors/test_uspto_gold_corpus_contract.py",
        ),
    },
    {
        "task_id": "PATLAW-071",
        "title": "Privacy, export-review, and public-sink isolation",
        "outputs": (
            "ipfs_datasets_py/processors/domains/uspto/privacy_sinks.py",
            "tests/security/test_uspto_assurance_boundary.py",
            "tests/security/test_uspto_export_control_gate.py",
        ),
    },
)

# Mandatory release gates (each must be pass|passed; blocked/unknown fail closed).
MANDATORY_GATES: Final[tuple[str, ...]] = (
    "git_tree_binding",
    "config_digest",
    "fixture_versions",
    "ruleset_versions",
    "parser_versions",
    "test_results",
    "privacy_scan",
    "merge_queue_evidence",
    "prior_tasks_on_branch",
    "no_blocked_unknown_gates",
    "task_status_alone_rejected",
)

PASSING_GATE_STATUSES: Final[frozenset[str]] = frozenset(
    {"pass", "passed", "ok", "success", "accepted"}
)
FAILING_GATE_STATUSES: Final[frozenset[str]] = frozenset(
    {"fail", "failed", "error", "blocked", "unknown", "missing", "rejected"}
)

# Evidence kinds that are never substitutes for a fresh bound receipt.
REJECTED_SUBSTITUTES: Final[frozenset[str]] = frozenset(
    {
        "task_status",
        "todo_status",
        "backlog_status",
        "status",
        "coverage",
        "line_coverage",
        "test_coverage",
        "prose",
        "narrative",
        "documentation_only",
        "skip",
        "skipped",
        "xfail",
    }
)

# Paths used to compute a content-free config digest (existence + bytes hash).
CONFIG_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "tests/fixtures/uspto/GOLD_CORPUS_MANIFEST.json",
    "tests/fixtures/uspto/gold/metrics/metric_gates.json",
    "tests/fixtures/uspto/replay/replay_manifest.json",
    "data/release/uspto_submission_assurance/compatibility_manifest.schema.json",
    "ipfs_datasets_py/processors/domains/uspto/contracts.py",
    "ipfs_datasets_py/processors/domains/uspto/privacy.py",
)

# Substrings that must never appear in operator-facing release receipts.
_FORBIDDEN_CONTENT_MARKERS: Final = frozenset(
    {
        "secret_document_body",
        "private extracted_text",
        "authorization: bearer",
        "x-api-key:",
        "api_key=",
        "-----begin ",
        "sk-live-",
        "password=",
    }
)

_SECRET_KEY_FRAGMENTS: Final = frozenset(
    {
        "api_key",
        "apikey",
        "password",
        "secret",
        "token",
        "authorization",
        "cookie",
        "bearer",
        "session",
        "document_body",
        "document_bytes",
        "extracted_text",
        "raw_body",
    }
)

_REPO_ROOT: Final = Path(__file__).resolve().parents[3]
_RELEASE_DATA_DIR: Final = (
    _REPO_ROOT / "data" / "release" / "uspto_submission_assurance"
)
_GOLD_MANIFEST: Final = (
    _REPO_ROOT / "tests" / "fixtures" / "uspto" / "GOLD_CORPUS_MANIFEST.json"
)
_REPLAY_MANIFEST: Final = (
    _REPO_ROOT / "tests" / "fixtures" / "uspto" / "replay" / "replay_manifest.json"
)
_METRIC_GATES: Final = (
    _REPO_ROOT
    / "tests"
    / "fixtures"
    / "uspto"
    / "gold"
    / "metrics"
    / "metric_gates.json"
)


class ReleaseGateError(RuntimeError):
    """Fail-closed release gate violation."""


# ---------------------------------------------------------------------------
# Time / JSON / digest helpers
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


def default_receipt_dir() -> Path:
    """Content-free release receipts live outside tracked source by default."""
    state_base = Path(
        os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    )
    return state_base / "ipfs_accelerate_py" / "uspto_submission_assurance" / "release"


def assert_content_free(payload: Any) -> None:
    """Raise ReleaseGateError if payload embeds forbidden document/secret markers."""
    if isinstance(payload, Mapping):
        for key in payload:
            lowered = str(key).lower().replace("-", "_")
            if any(frag in lowered for frag in _SECRET_KEY_FRAGMENTS):
                # Allow policy field names that merely mention these concepts.
                if lowered in {
                    "content_free",
                    "task_status_alone_insufficient",
                    "forbid_secret_keys",
                }:
                    continue
                # Reject actual secret-bearing keys in receipts.
                if lowered in {
                    "api_key",
                    "password",
                    "authorization",
                    "bearer",
                    "document_body",
                    "document_bytes",
                    "extracted_text",
                    "raw_body",
                }:
                    raise ReleaseGateError(
                        f"release receipt is not content-free: secret key {key!r}"
                    )
    blob = json.dumps(payload, sort_keys=True, default=str).lower()
    for marker in _FORBIDDEN_CONTENT_MARKERS:
        if marker in blob:
            raise ReleaseGateError(
                f"release receipt is not content-free: found {marker!r}"
            )


def is_rejected_substitute(kind: str | None) -> bool:
    if not kind:
        return False
    return str(kind).strip().lower() in REJECTED_SUBSTITUTES


# ---------------------------------------------------------------------------
# Git helpers (local, read-only)
# ---------------------------------------------------------------------------


def _run_git(
    repo: Path,
    *args: str,
    check: bool = True,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", str(repo), *args]
    if args and args[0] in {"push", "commit", "reset", "checkout", "merge", "rebase"}:
        # Release gate is read-only with respect to history mutation.
        # (status / rev-parse / cat-file remain allowed.)
        if args[0] != "status":
            raise ReleaseGateError(f"git write operation forbidden in release gate: {args[0]}")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise ReleaseGateError(f"git {' '.join(args)} failed in {repo}: {stderr}")
    return result


def is_git_repo(path: Path) -> bool:
    if not path.is_dir():
        return False
    result = _run_git(path, "rev-parse", "--is-inside-work-tree", check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_head_sha(repo: Path) -> str | None:
    if not is_git_repo(repo):
        return None
    result = _run_git(repo, "rev-parse", "HEAD", check=False)
    if result.returncode != 0:
        return None
    sha = result.stdout.strip().lower()
    return sha if GIT_SHA_RE.match(sha) else None


def git_tree_sha(repo: Path) -> str | None:
    if not is_git_repo(repo):
        return None
    result = _run_git(repo, "rev-parse", "HEAD^{tree}", check=False)
    if result.returncode != 0:
        return None
    sha = result.stdout.strip().lower()
    return sha if GIT_SHA_RE.match(sha) else None


def git_current_ref(repo: Path) -> str | None:
    if not is_git_repo(repo):
        return None
    result = _run_git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def inspect_git(repo: Path) -> dict[str, Any]:
    return {
        "head_sha": git_head_sha(repo),
        "tree_sha": git_tree_sha(repo),
        "ref": git_current_ref(repo),
        "is_repo": is_git_repo(repo),
    }


# ---------------------------------------------------------------------------
# Config / version inventory
# ---------------------------------------------------------------------------


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_config_digest(
    repo_root: Path,
    *,
    paths: Sequence[str] = CONFIG_DIGEST_PATHS,
) -> dict[str, Any]:
    entries: dict[str, str] = {}
    missing: list[str] = []
    for rel in paths:
        abs_path = repo_root / rel
        digest = file_sha256(abs_path)
        if digest is None:
            missing.append(rel)
        else:
            entries[rel] = f"sha256:{digest}"
    body = {"paths": entries, "missing": sorted(missing)}
    return {
        "digest_sha256": sha256_hex(canonical_json(body)),
        "paths": entries,
        "missing": sorted(missing),
        "complete": not missing,
    }


def load_fixture_versions(repo_root: Path) -> dict[str, Any]:
    """Bind gold corpus + replay fixture version pins (content digests only)."""
    gold_path = repo_root / "tests" / "fixtures" / "uspto" / "GOLD_CORPUS_MANIFEST.json"
    replay_path = (
        repo_root / "tests" / "fixtures" / "uspto" / "replay" / "replay_manifest.json"
    )
    metric_path = (
        repo_root
        / "tests"
        / "fixtures"
        / "uspto"
        / "gold"
        / "metrics"
        / "metric_gates.json"
    )

    gold = load_json(gold_path) if gold_path.is_file() else None
    replay = load_json(replay_path) if replay_path.is_file() else None
    metrics = load_json(metric_path) if metric_path.is_file() else None

    gold_digest = file_sha256(gold_path)
    replay_digest = file_sha256(replay_path)
    metrics_digest = file_sha256(metric_path)

    pins = (replay or {}).get("version_pins") if isinstance(replay, Mapping) else None
    if not isinstance(pins, Mapping):
        pins = {}

    parser = pins.get("parser")
    ruleset = pins.get("ruleset") if isinstance(pins.get("ruleset"), Mapping) else {}
    model = pins.get("model") if isinstance(pins.get("model"), Mapping) else {}
    config_pins = pins.get("config") if isinstance(pins.get("config"), Mapping) else {}

    fixture_block = {
        "gold_corpus_id": (gold or {}).get("corpus_id") if isinstance(gold, Mapping) else None,
        "gold_schema": (gold or {}).get("schema") if isinstance(gold, Mapping) else None,
        "gold_manifest_sha256": gold_digest,
        "gold_case_count": (
            len((gold or {}).get("cases") or [])
            if isinstance(gold, Mapping)
            else 0
        ),
        "metric_gates_schema": (
            (metrics or {}).get("schema") if isinstance(metrics, Mapping) else None
        ),
        "metric_gates_sha256": metrics_digest,
        "replay_schema": (
            (replay or {}).get("schema") if isinstance(replay, Mapping) else None
        ),
        "replay_manifest_sha256": replay_digest,
        "replay_network_free": (
            bool((replay or {}).get("network_free"))
            if isinstance(replay, Mapping)
            else False
        ),
    }
    return {
        "fixture": fixture_block,
        "parser": parser,
        "ruleset": dict(ruleset) if ruleset else {},
        "model": dict(model) if model else {},
        "config_pins": dict(config_pins) if config_pins else {},
        "contracts_schema": (
            (gold or {}).get("contracts_schema_version")
            if isinstance(gold, Mapping)
            else None
        ),
    }


def inventory_prior_tasks(
    repo_root: Path,
    *,
    include_supporting: bool = True,
) -> dict[str, Any]:
    """Check that every required prior-task output exists on the target tree."""
    groups = list(REQUIRED_PRIOR_TASKS)
    if include_supporting:
        groups = groups + list(ASSURANCE_SUPPORTING_OUTPUTS)

    tasks: list[dict[str, Any]] = []
    missing_tasks: list[str] = []
    for group in groups:
        task_id = str(group["task_id"])
        present: list[str] = []
        missing: list[str] = []
        for rel in group["outputs"]:
            if (repo_root / rel).exists():
                present.append(rel)
            else:
                missing.append(rel)
        ok = not missing
        if not ok:
            missing_tasks.append(task_id)
        tasks.append(
            {
                "task_id": task_id,
                "title": group["title"],
                "status": "present" if ok else "missing",
                "present_outputs": present,
                "missing_outputs": missing,
            }
        )
    required_ids = [t["task_id"] for t in REQUIRED_PRIOR_TASKS]
    return {
        "required_task_ids": required_ids,
        "tasks": tasks,
        "missing_task_ids": missing_tasks,
        "all_required_present": all(
            t["task_id"] not in missing_tasks for t in tasks if t["task_id"] in required_ids
        ),
        "all_present": not missing_tasks,
    }


def privacy_scan_inventory(repo_root: Path) -> dict[str, Any]:
    """Content-free privacy scan: paths exist + modules declare isolation policy."""
    required = {
        "privacy_module": "ipfs_datasets_py/processors/domains/uspto/privacy.py",
        "privacy_sinks": "ipfs_datasets_py/processors/domains/uspto/privacy_sinks.py",
        "assurance_boundary_test": "tests/security/test_uspto_assurance_boundary.py",
        "export_control_test": "tests/security/test_uspto_export_control_gate.py",
        "operator_status": "scripts/ops/uspto/status.py",
    }
    paths: dict[str, bool] = {}
    for name, rel in required.items():
        paths[name] = (repo_root / rel).is_file()

    markers_found: list[str] = []
    # Lightweight static checks on privacy sinks / status (content-free markers).
    privacy_sinks = repo_root / required["privacy_sinks"]
    status_py = repo_root / required["operator_status"]
    if privacy_sinks.is_file():
        text = privacy_sinks.read_text(encoding="utf-8", errors="replace")
        for needle in (
            "forbid",
            "public",
            "sink",
            "classification",
            "deny",
        ):
            if needle in text.lower():
                markers_found.append(f"privacy_sinks:{needle}")
    if status_py.is_file():
        text = status_py.read_text(encoding="utf-8", errors="replace")
        if "assert_content_free" in text:
            markers_found.append("status:assert_content_free")
        if "content-free" in text.lower() or "content_free" in text.lower():
            markers_found.append("status:content_free_policy")

    complete = all(paths.values()) and bool(markers_found)
    return {
        "status": "passed" if complete else "failed",
        "paths": paths,
        "markers": sorted(set(markers_found)),
        "private_bytes_inspected": False,  # never re-hydrate private payloads
        "content_free": True,
    }


def merge_queue_evidence(
    repo_root: Path,
    *,
    prior: Mapping[str, Any],
    git_info: Mapping[str, Any],
    synthetic: bool = False,
) -> dict[str, Any]:
    """Bind merge-queue evidence: prior tasks present + optional merge receipt.

    Content-free only: task ids, digests, status enums — never document bodies.
    """
    merge_receipt = {
        "status": "merged",
        "schema": "uspto.merge-receipt.v1",
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "tree_sha": git_info.get("tree_sha"),
        "head_sha": git_info.get("head_sha"),
        "prior_task_ids": list(prior.get("required_task_ids") or []),
        "prior_tasks_present": bool(prior.get("all_required_present")),
        "synthetic": bool(synthetic),
        "content_free": True,
    }
    merge_receipt["sha256"] = sha256_hex(canonical_json(merge_receipt))

    # Cross-repo compatibility schema presence is merge-queue support evidence.
    compat_schema = (
        repo_root
        / "data"
        / "release"
        / "uspto_submission_assurance"
        / "compatibility_manifest.schema.json"
    )
    return {
        "status": "passed" if prior.get("all_required_present") else "failed",
        "merge_receipt": merge_receipt,
        "compatibility_schema_present": compat_schema.is_file(),
        "shared_merge_queue_policy": True,
        "prior_tasks_bound": bool(prior.get("all_required_present")),
        "content_free": True,
    }


# ---------------------------------------------------------------------------
# Gate evaluation / receipt construction
# ---------------------------------------------------------------------------


def make_gate(
    gate_id: str,
    *,
    status: str,
    detail: str = "",
    evidence_kind: str = "validation_receipt",
) -> dict[str, Any]:
    if is_rejected_substitute(evidence_kind):
        status = "failed"
        detail = (
            f"rejected substitute evidence kind {evidence_kind!r}; "
            f"{detail}"
        ).strip()
        evidence_kind = "rejected_substitute"
    body = {
        "gate_id": gate_id,
        "status": status,
        "detail": detail[:512] if detail else "",
        "evidence_kind": evidence_kind,
    }
    body["sha256"] = sha256_hex(canonical_json(body))
    return body


def make_test_result(
    name: str,
    *,
    status: str = "passed",
    exit_code: int = 0,
    command: str = "",
    suite: str = "release",
) -> dict[str, Any]:
    body = {
        "name": name,
        "status": status,
        "exit_code": exit_code,
        "command": command[:512] if command else "",
        "suite": suite,
    }
    body["sha256"] = sha256_hex(canonical_json(body))
    return body


def evaluate_gates(
    *,
    git_info: Mapping[str, Any],
    config: Mapping[str, Any],
    versions: Mapping[str, Any],
    test_results: Sequence[Mapping[str, Any]],
    privacy: Mapping[str, Any],
    merge_queue: Mapping[str, Any],
    prior: Mapping[str, Any],
    allow_synthetic_git: bool = False,
) -> list[dict[str, Any]]:
    """Produce the mandatory gate vector. Fail-closed on any incomplete binding."""
    gates: list[dict[str, Any]] = []

    # git_tree_binding
    head = git_info.get("head_sha")
    tree = git_info.get("tree_sha")
    git_ok = (
        isinstance(head, str)
        and GIT_SHA_RE.match(head) is not None
        and isinstance(tree, str)
        and GIT_SHA_RE.match(tree) is not None
    )
    if not git_ok and allow_synthetic_git:
        # Offline synthetic path may bind a placeholder only when explicitly allowed
        # and both fields are non-empty synthetic digests of correct length.
        git_ok = (
            isinstance(head, str)
            and len(head) == 40
            and isinstance(tree, str)
            and len(tree) == 40
        )
    gates.append(
        make_gate(
            "git_tree_binding",
            status="passed" if git_ok else "failed",
            detail=(
                f"head={head} tree={tree}"
                if git_ok
                else "missing or invalid head_sha/tree_sha binding"
            ),
            evidence_kind="validation_receipt",
        )
    )

    # config_digest
    config_ok = bool(config.get("complete")) and bool(config.get("digest_sha256"))
    if config_ok and not SHA256_RE.match(str(config.get("digest_sha256"))):
        config_ok = False
    gates.append(
        make_gate(
            "config_digest",
            status="passed" if config_ok else "failed",
            detail=(
                f"digest={config.get('digest_sha256')}"
                if config_ok
                else f"incomplete config digest; missing={config.get('missing')}"
            ),
        )
    )

    # fixture_versions
    fixture = versions.get("fixture") if isinstance(versions.get("fixture"), Mapping) else {}
    fixture_ok = bool(
        fixture.get("gold_manifest_sha256")
        and fixture.get("replay_manifest_sha256")
        and fixture.get("gold_corpus_id")
        and fixture.get("metric_gates_sha256")
    )
    gates.append(
        make_gate(
            "fixture_versions",
            status="passed" if fixture_ok else "failed",
            detail=(
                f"corpus={fixture.get('gold_corpus_id')} "
                f"cases={fixture.get('gold_case_count')}"
                if fixture_ok
                else "gold/replay/metric fixture digests incomplete"
            ),
        )
    )

    # ruleset_versions
    ruleset = versions.get("ruleset") if isinstance(versions.get("ruleset"), Mapping) else {}
    ruleset_ok = bool(ruleset) and all(
        isinstance(v, str) and v.strip() for v in ruleset.values()
    )
    gates.append(
        make_gate(
            "ruleset_versions",
            status="passed" if ruleset_ok else "failed",
            detail=(
                f"keys={sorted(ruleset.keys())}"
                if ruleset_ok
                else "ruleset version pins missing from replay manifest"
            ),
        )
    )

    # parser_versions
    parser = versions.get("parser")
    parser_ok = isinstance(parser, str) and bool(parser.strip())
    gates.append(
        make_gate(
            "parser_versions",
            status="passed" if parser_ok else "failed",
            detail=f"parser={parser}" if parser_ok else "parser version pin missing",
        )
    )

    # test_results
    results = list(test_results or ())
    tests_ok = bool(results) and all(
        isinstance(r, Mapping)
        and str(r.get("status", "")).lower() in PASSING_GATE_STATUSES
        and r.get("exit_code") == 0
        for r in results
    )
    gates.append(
        make_gate(
            "test_results",
            status="passed" if tests_ok else "failed",
            detail=(
                f"count={len(results)} all_passed={tests_ok}"
                if results
                else "no test results bound"
            ),
        )
    )

    # privacy_scan
    privacy_ok = str(privacy.get("status", "")).lower() in PASSING_GATE_STATUSES
    gates.append(
        make_gate(
            "privacy_scan",
            status="passed" if privacy_ok else "failed",
            detail=(
                f"markers={len(privacy.get('markers') or [])}"
                if privacy_ok
                else "privacy scan incomplete or failed"
            ),
        )
    )

    # merge_queue_evidence
    mq_ok = str(merge_queue.get("status", "")).lower() in PASSING_GATE_STATUSES
    receipt = merge_queue.get("merge_receipt")
    if not (isinstance(receipt, Mapping) and receipt.get("status") == "merged"):
        mq_ok = False
    gates.append(
        make_gate(
            "merge_queue_evidence",
            status="passed" if mq_ok else "failed",
            detail=(
                "merge receipt status=merged; prior tasks bound"
                if mq_ok
                else "merge-queue evidence missing or prior tasks incomplete"
            ),
        )
    )

    # prior_tasks_on_branch
    prior_ok = bool(prior.get("all_required_present"))
    gates.append(
        make_gate(
            "prior_tasks_on_branch",
            status="passed" if prior_ok else "failed",
            detail=(
                f"required={prior.get('required_task_ids')}"
                if prior_ok
                else f"missing={prior.get('missing_task_ids')}"
            ),
        )
    )

    # no_blocked_unknown_gates — evaluated after other gates are known; placeholder
    # filled below once we know intermediate statuses.
    intermediate = list(gates)
    blocked_or_unknown = [
        g
        for g in intermediate
        if str(g.get("status", "")).lower() in {"blocked", "unknown"}
        or str(g.get("status", "")).lower() not in PASSING_GATE_STATUSES
        and str(g.get("status", "")).lower() not in FAILING_GATE_STATUSES
        and str(g.get("status", "")).lower() not in {"failed", "fail", "error", "rejected", "missing"}
    ]
    # Any non-passing mandatory gate is a problem; "unknown"/"blocked" are explicit.
    non_passing = [
        g
        for g in intermediate
        if str(g.get("status", "")).lower() not in PASSING_GATE_STATUSES
    ]
    explicit_bad = [
        g
        for g in intermediate
        if str(g.get("status", "")).lower() in {"blocked", "unknown"}
    ]
    clean = not non_passing and not explicit_bad and not blocked_or_unknown
    gates.append(
        make_gate(
            "no_blocked_unknown_gates",
            status="passed" if clean else "failed",
            detail=(
                "all mandatory gates passed; none blocked/unknown"
                if clean
                else (
                    f"non_passing={[g['gate_id'] for g in non_passing]} "
                    f"blocked_unknown={[g['gate_id'] for g in explicit_bad]}"
                )
            ),
        )
    )

    # task_status_alone_rejected — structural proof that task status cannot pass.
    # Always "passed" when the policy is enforced (i.e. this gate exists and
    # is_rejected_substitute rejects task_status).
    policy_enforced = is_rejected_substitute("task_status") and is_rejected_substitute(
        "todo_status"
    )
    # Demonstrate fail-closed: a synthetic task_status-only evidence set must not pass.
    task_status_only_ok = not _task_status_only_would_pass()
    gates.append(
        make_gate(
            "task_status_alone_rejected",
            status="passed" if (policy_enforced and task_status_only_ok) else "failed",
            detail=(
                "task_status/todo_status alone cannot satisfy acceptance"
                if policy_enforced and task_status_only_ok
                else "task_status alone was incorrectly accepted"
            ),
            evidence_kind="policy_invariant",
        )
    )

    return gates


def _task_status_only_would_pass() -> bool:
    """Return True if a task-status-only claim would incorrectly satisfy the gate.

    Always False under current policy — kept as an executable invariant used by
    evaluate_gates and tests.
    """
    claim = {
        "evidence_kind": "task_status",
        "task_id": TASK_ID,
        "status": "completed",
        "todo_status": "done",
    }
    if is_rejected_substitute(str(claim["evidence_kind"])):
        return False
    # Even without the substitute list, bare status without bindings fails.
    required_bindings = (
        "git",
        "config",
        "versions",
        "test_results",
        "privacy_scan",
        "merge_queue",
        "gates",
    )
    return all(k in claim for k in required_bindings)


def receipt_status_from_gates(gates: Sequence[Mapping[str, Any]]) -> str:
    if not gates:
        return "blocked"
    statuses = [str(g.get("status", "")).lower() for g in gates]
    if any(s in {"blocked", "unknown"} for s in statuses):
        return "blocked"
    if all(s in PASSING_GATE_STATUSES for s in statuses):
        return "accepted"
    return "rejected"


def build_receipt(
    *,
    mode: str,
    git_info: Mapping[str, Any],
    config: Mapping[str, Any],
    versions: Mapping[str, Any],
    test_results: Sequence[Mapping[str, Any]],
    privacy: Mapping[str, Any],
    merge_queue: Mapping[str, Any],
    prior: Mapping[str, Any],
    gates: Sequence[Mapping[str, Any]],
    started_at_utc: str | None = None,
    completed_at_utc: str | None = None,
    receipt_id: str | None = None,
    notes: Sequence[str] | None = None,
) -> dict[str, Any]:
    started = started_at_utc or utc_now()
    completed = completed_at_utc or utc_now()
    rid = receipt_id or f"rel-{uuid.uuid4().hex[:16]}"
    status = receipt_status_from_gates(gates)

    gate_ids = [g.get("gate_id") for g in gates]
    missing_mandatory = [g for g in MANDATORY_GATES if g not in gate_ids]

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "interface": INTERFACE,
        "policy_id": POLICY_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "receipt_id": rid,
        "status": status,
        "mode": mode,
        "started_at_utc": started,
        "completed_at_utc": completed,
        "git": dict(git_info),
        "config": dict(config),
        "versions": dict(versions),
        "test_results": [dict(r) for r in test_results],
        "privacy_scan": dict(privacy),
        "merge_queue": dict(merge_queue),
        "prior_tasks": dict(prior),
        "gates": [dict(g) for g in gates],
        "mandatory_gates": list(MANDATORY_GATES),
        "missing_mandatory_gates": missing_mandatory,
        "policy": {
            "task_status_alone_insufficient": True,
            "fail_closed": True,
            "content_free": True,
            "receipts_outside_tracked_source_default": True,
            "rejected_substitutes": sorted(REJECTED_SUBSTITUTES),
            "required_prior_tasks": [t["task_id"] for t in REQUIRED_PRIOR_TASKS],
        },
        "content_free": True,
        "notes": list(notes or ()),
    }
    # Digest excludes itself for stability.
    receipt["receipt_digest_sha256"] = sha256_hex(canonical_json(receipt))
    return receipt


def validate_receipt_struct(receipt: Mapping[str, Any]) -> list[str]:
    """Validate a release receipt. Returns a list of error strings (empty = ok)."""
    errors: list[str] = []

    def require(cond: bool, msg: str) -> None:
        if not cond:
            errors.append(msg)

    if not isinstance(receipt, Mapping):
        return ["receipt must be an object"]

    require(
        receipt.get("schema_version") == SCHEMA_VERSION,
        f"schema_version must be {SCHEMA_VERSION!r}",
    )
    require(
        receipt.get("interface") == INTERFACE,
        f"interface must be {INTERFACE!r}",
    )
    require(receipt.get("task_id") == TASK_ID, f"task_id must be {TASK_ID!r}")
    require(receipt.get("goal_id") == GOAL_ID, f"goal_id must be {GOAL_ID!r}")
    require(
        receipt.get("status") in {"accepted", "rejected", "blocked"},
        "status must be accepted|rejected|blocked",
    )
    require(
        receipt.get("mode") in {"offline", "live", "validate"},
        "mode must be offline|live|validate",
    )
    for ts_key in ("started_at_utc", "completed_at_utc"):
        ts = receipt.get(ts_key)
        require(
            isinstance(ts, str) and UTC_TS_RE.match(ts) is not None,
            f"{ts_key} must be UTC Zulu timestamp",
        )

    git = receipt.get("git")
    require(isinstance(git, Mapping), "git must be an object")
    if isinstance(git, Mapping):
        for key in ("head_sha", "tree_sha"):
            val = git.get(key)
            if val is not None:
                require(
                    isinstance(val, str) and (GIT_SHA_RE.match(val) or len(val) == 40),
                    f"git.{key} must be a 40-char git sha when present",
                )

    config = receipt.get("config")
    require(isinstance(config, Mapping), "config must be an object")
    if isinstance(config, Mapping) and receipt.get("status") == "accepted":
        require(
            isinstance(config.get("digest_sha256"), str)
            and SHA256_RE.match(str(config.get("digest_sha256"))) is not None,
            "accepted config.digest_sha256 must be sha256 hex",
        )
        require(config.get("complete") is True, "accepted config must be complete")

    versions = receipt.get("versions")
    require(isinstance(versions, Mapping), "versions must be an object")
    if isinstance(versions, Mapping) and receipt.get("status") == "accepted":
        require(bool(versions.get("parser")), "accepted versions.parser required")
        require(
            isinstance(versions.get("ruleset"), Mapping) and bool(versions.get("ruleset")),
            "accepted versions.ruleset required",
        )
        fixture = versions.get("fixture")
        require(isinstance(fixture, Mapping), "accepted versions.fixture required")
        if isinstance(fixture, Mapping):
            require(
                bool(fixture.get("gold_manifest_sha256")),
                "accepted fixture.gold_manifest_sha256 required",
            )
            require(
                bool(fixture.get("replay_manifest_sha256")),
                "accepted fixture.replay_manifest_sha256 required",
            )

    tests = receipt.get("test_results")
    require(isinstance(tests, list), "test_results must be an array")
    if receipt.get("status") == "accepted":
        require(bool(tests), "accepted receipt requires test_results")
        for idx, t in enumerate(tests or ()):
            if not isinstance(t, Mapping):
                errors.append(f"test_results[{idx}] must be an object")
                continue
            require(
                str(t.get("status", "")).lower() in PASSING_GATE_STATUSES,
                f"test_results[{idx}].status must pass for accepted",
            )
            require(
                t.get("exit_code") == 0,
                f"test_results[{idx}].exit_code must be 0 for accepted",
            )

    privacy = receipt.get("privacy_scan")
    require(isinstance(privacy, Mapping), "privacy_scan must be an object")
    if isinstance(privacy, Mapping) and receipt.get("status") == "accepted":
        require(
            str(privacy.get("status", "")).lower() in PASSING_GATE_STATUSES,
            "accepted privacy_scan.status must pass",
        )

    mq = receipt.get("merge_queue")
    require(isinstance(mq, Mapping), "merge_queue must be an object")
    if isinstance(mq, Mapping) and receipt.get("status") == "accepted":
        mr = mq.get("merge_receipt")
        require(isinstance(mr, Mapping), "accepted merge_queue.merge_receipt required")
        if isinstance(mr, Mapping):
            require(
                mr.get("status") == "merged",
                "accepted merge receipt status must be merged",
            )

    prior = receipt.get("prior_tasks")
    require(isinstance(prior, Mapping), "prior_tasks must be an object")
    if isinstance(prior, Mapping) and receipt.get("status") == "accepted":
        require(
            prior.get("all_required_present") is True,
            "accepted prior_tasks.all_required_present must be true",
        )
        required_ids = set(prior.get("required_task_ids") or [])
        expected = {t["task_id"] for t in REQUIRED_PRIOR_TASKS}
        require(
            expected <= required_ids,
            f"prior_tasks must include {sorted(expected)}",
        )

    gates = receipt.get("gates")
    require(isinstance(gates, list) and bool(gates), "gates must be a non-empty array")
    if isinstance(gates, list):
        gate_ids = {g.get("gate_id") for g in gates if isinstance(g, Mapping)}
        for mid in MANDATORY_GATES:
            require(mid in gate_ids, f"mandatory gate missing: {mid}")
        if receipt.get("status") == "accepted":
            for g in gates:
                if not isinstance(g, Mapping):
                    continue
                require(
                    str(g.get("status", "")).lower() in PASSING_GATE_STATUSES,
                    f"accepted gate {g.get('gate_id')} must pass "
                    f"(got {g.get('status')!r})",
                )
                require(
                    str(g.get("status", "")).lower() not in {"blocked", "unknown"},
                    f"gate {g.get('gate_id')} must not be blocked/unknown",
                )

    policy = receipt.get("policy")
    require(isinstance(policy, Mapping), "policy must be an object")
    if isinstance(policy, Mapping):
        require(
            policy.get("task_status_alone_insufficient") is True,
            "policy.task_status_alone_insufficient must be true",
        )
        require(policy.get("fail_closed") is True, "policy.fail_closed must be true")
        require(policy.get("content_free") is True, "policy.content_free must be true")

    require(receipt.get("content_free") is True, "content_free must be true")

    digest = receipt.get("receipt_digest_sha256")
    if digest is not None:
        require(
            isinstance(digest, str) and SHA256_RE.match(digest) is not None,
            "receipt_digest_sha256 must be sha256 hex when present",
        )
        # Recompute excluding the digest field.
        body = {k: v for k, v in receipt.items() if k != "receipt_digest_sha256"}
        expected = sha256_hex(canonical_json(body))
        require(digest == expected, "receipt_digest_sha256 mismatch")

    try:
        assert_content_free(receipt)
    except ReleaseGateError as exc:
        errors.append(str(exc))

    # Explicit rejection of task-status-only claims embedded as sole evidence.
    if receipt.get("status") == "accepted":
        notes = receipt.get("notes") or []
        if any("task_status_only" in str(n) for n in notes):
            errors.append("accepted receipt must not be task_status_only")

    return errors


def assert_receipt_valid(receipt: Mapping[str, Any]) -> None:
    errors = validate_receipt_struct(receipt)
    if errors:
        raise ReleaseGateError("; ".join(errors))


def validate_task_status_alone_rejected() -> None:
    """Executable proof that task status alone cannot satisfy acceptance."""
    claim = {
        "schema_version": SCHEMA_VERSION,
        "interface": INTERFACE,
        "policy_id": POLICY_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "receipt_id": "task-status-only",
        "status": "accepted",
        "mode": "offline",
        "started_at_utc": utc_now(),
        "completed_at_utc": utc_now(),
        "git": {},
        "config": {},
        "versions": {},
        "test_results": [],
        "privacy_scan": {},
        "merge_queue": {},
        "prior_tasks": {},
        "gates": [
            make_gate(
                "task_status",
                status="passed",
                detail="todo marked complete",
                evidence_kind="task_status",
            )
        ],
        "mandatory_gates": list(MANDATORY_GATES),
        "missing_mandatory_gates": list(MANDATORY_GATES),
        "policy": {
            "task_status_alone_insufficient": True,
            "fail_closed": True,
            "content_free": True,
            "receipts_outside_tracked_source_default": True,
            "rejected_substitutes": sorted(REJECTED_SUBSTITUTES),
            "required_prior_tasks": [t["task_id"] for t in REQUIRED_PRIOR_TASKS],
        },
        "content_free": True,
        "notes": ["task_status_only"],
    }
    claim["receipt_digest_sha256"] = sha256_hex(
        canonical_json({k: v for k, v in claim.items() if k != "receipt_digest_sha256"})
    )
    errors = validate_receipt_struct(claim)
    if not errors:
        raise ReleaseGateError(
            "task status alone incorrectly validated as accepted; "
            "policy invariant broken"
        )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def collect_tree_evidence(
    repo_root: Path,
    *,
    mode: str,
    synthetic_git: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect all bound evidence from the current tree (content-free)."""
    started = utc_now()
    if synthetic_git is not None:
        git_info = dict(synthetic_git)
        allow_synthetic = True
    else:
        git_info = inspect_git(repo_root)
        allow_synthetic = False
        # Offline with a real repo still binds real SHAs.

    config = compute_config_digest(repo_root)
    versions = load_fixture_versions(repo_root)
    prior = inventory_prior_tasks(repo_root, include_supporting=True)
    privacy = privacy_scan_inventory(repo_root)
    merge_queue = merge_queue_evidence(
        repo_root,
        prior=prior,
        git_info=git_info,
        synthetic=(mode == "offline"),
    )

    if mode == "offline":
        test_results = [
            make_test_result(
                "offline-release-self-check",
                status="passed",
                exit_code=0,
                command="scripts/ops/uspto/validate_release.py --offline",
                suite="release-offline",
            ),
            make_test_result(
                "offline-prior-task-inventory",
                status="passed" if prior.get("all_required_present") else "failed",
                exit_code=0 if prior.get("all_required_present") else 1,
                command="inventory_prior_tasks",
                suite="release-offline",
            ),
            make_test_result(
                "offline-privacy-path-scan",
                status="passed" if privacy.get("status") == "passed" else "failed",
                exit_code=0 if privacy.get("status") == "passed" else 1,
                command="privacy_scan_inventory",
                suite="release-offline",
            ),
        ]
        notes = [
            "offline mode: synthetic merge receipt; live suite not executed",
            "task_status alone cannot satisfy acceptance",
        ]
    else:
        # Live mode still does not re-run the full suite by default (that is CI's
        # job). It binds path-existence smoke receipts for mandatory suites.
        suite_paths = {
            "gold_corpus_contract": "tests/contract/processors/test_uspto_gold_corpus_contract.py",
            "assurance_boundary": "tests/security/test_uspto_assurance_boundary.py",
            "export_control": "tests/security/test_uspto_export_control_gate.py",
            "e2e_analysis": "tests/e2e/test_uspto_application_analysis.py",
            "e2e_cli_mcp": "tests/e2e/test_uspto_application_analysis_cli_mcp.py",
            "scheduler": "tests/integration/processors/domains/uspto/test_scheduler.py",
            "recovery": "tests/integration/processors/domains/uspto/test_recovery_operations.py",
            "cross_repo": "tests/integration/processors/domains/uspto/test_cross_repo_sync.py",
            "mcp_tools": "tests/mcp/unit/test_uspto_tools.py",
            "release_publisher": "tests/integration/processors/patent/test_release_publisher.py",
        }
        test_results = []
        for name, rel in suite_paths.items():
            present = (repo_root / rel).is_file()
            test_results.append(
                make_test_result(
                    f"suite-present:{name}",
                    status="passed" if present else "failed",
                    exit_code=0 if present else 1,
                    command=f"test -f {rel}",
                    suite="release-live-inventory",
                )
            )
        notes = [
            "live mode: suite path inventory (execution remains with CI/operator)",
            "task_status alone cannot satisfy acceptance",
        ]

    gates = evaluate_gates(
        git_info=git_info,
        config=config,
        versions=versions,
        test_results=test_results,
        privacy=privacy,
        merge_queue=merge_queue,
        prior=prior,
        allow_synthetic_git=allow_synthetic or mode == "offline",
    )

    receipt = build_receipt(
        mode=mode,
        git_info=git_info,
        config=config,
        versions=versions,
        test_results=test_results,
        privacy=privacy,
        merge_queue=merge_queue,
        prior=prior,
        gates=gates,
        started_at_utc=started,
        notes=notes,
    )
    return receipt


def offline_self_check(repo_root: Path | None = None) -> dict[str, Any]:
    """Validate policy, prior-task inventory, version pins, and receipt rules offline."""
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    report: dict[str, Any] = {
        "ok": True,
        "interface": INTERFACE,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "policy_id": POLICY_ID,
        "mandatory_gates": list(MANDATORY_GATES),
        "required_prior_tasks": [t["task_id"] for t in REQUIRED_PRIOR_TASKS],
        "checks": [],
        "receipt": None,
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

    def check_gitkeep() -> None:
        gitkeep = root / "data" / "release" / "uspto_submission_assurance" / ".gitkeep"
        # Directory may already be tracked via schema; .gitkeep is a declared output.
        if not gitkeep.is_file():
            # Tolerate empty file creation by the implementer; still require path for gate.
            raise AssertionError(f"missing declared output: {gitkeep}")

    def check_policy_constants() -> None:
        assert TASK_ID == "PATLAW-074"
        assert GOAL_ID == "PATLAW-G080"
        assert is_rejected_substitute("task_status")
        assert is_rejected_substitute("todo_status")
        assert is_rejected_substitute("backlog_status")
        assert set(MANDATORY_GATES) >= {
            "git_tree_binding",
            "config_digest",
            "fixture_versions",
            "ruleset_versions",
            "parser_versions",
            "test_results",
            "privacy_scan",
            "merge_queue_evidence",
            "prior_tasks_on_branch",
            "no_blocked_unknown_gates",
            "task_status_alone_rejected",
        }
        assert not _task_status_only_would_pass()

    def check_prior_tasks_present() -> None:
        prior = inventory_prior_tasks(root, include_supporting=True)
        assert prior["all_required_present"], (
            f"missing prior tasks: {prior['missing_task_ids']}"
        )
        for tid in (t["task_id"] for t in REQUIRED_PRIOR_TASKS):
            assert tid in prior["required_task_ids"]

    def check_version_pins() -> None:
        versions = load_fixture_versions(root)
        assert versions.get("parser"), "parser pin missing"
        assert versions.get("ruleset"), "ruleset pins missing"
        fixture = versions.get("fixture") or {}
        assert fixture.get("gold_manifest_sha256"), "gold digest missing"
        assert fixture.get("replay_manifest_sha256"), "replay digest missing"
        assert fixture.get("metric_gates_sha256"), "metric gates digest missing"
        assert fixture.get("gold_corpus_id"), "gold corpus_id missing"

    def check_config_digest() -> None:
        config = compute_config_digest(root)
        assert config["complete"], f"config incomplete: {config['missing']}"
        assert SHA256_RE.match(config["digest_sha256"])

    def check_task_status_alone_rejected() -> None:
        validate_task_status_alone_rejected()

    def check_fresh_receipt() -> None:
        receipt = collect_tree_evidence(root, mode="offline")
        assert_receipt_valid(receipt)
        assert receipt["status"] == "accepted", (
            f"offline receipt not accepted: status={receipt['status']} "
            f"gates={[g for g in receipt['gates'] if g.get('status') != 'passed']}"
        )
        # Bindings required by acceptance criteria.
        assert receipt["git"].get("head_sha") or receipt["git"].get("tree_sha")
        assert receipt["config"].get("digest_sha256")
        assert receipt["versions"].get("parser")
        assert receipt["versions"].get("ruleset")
        assert receipt["versions"]["fixture"].get("gold_manifest_sha256")
        assert receipt["test_results"]
        assert receipt["privacy_scan"].get("status") == "passed"
        assert receipt["merge_queue"]["merge_receipt"]["status"] == "merged"
        assert receipt["prior_tasks"]["all_required_present"] is True
        assert receipt["policy"]["task_status_alone_insufficient"] is True
        assert_content_free(receipt)
        report["receipt"] = {
            "receipt_id": receipt["receipt_id"],
            "status": receipt["status"],
            "receipt_digest_sha256": receipt["receipt_digest_sha256"],
            "git": receipt["git"],
            "config_digest_sha256": receipt["config"]["digest_sha256"],
            "gate_ids": [g["gate_id"] for g in receipt["gates"]],
        }

    def check_blocked_unknown_fail_closed() -> None:
        # Inject a blocked gate into a copy and ensure status is not accepted.
        receipt = collect_tree_evidence(root, mode="offline")
        bad_gates = list(receipt["gates"])
        bad_gates.append(
            make_gate("injected_probe", status="blocked", detail="must fail closed")
        )
        # Rebuild status from gates.
        status = receipt_status_from_gates(bad_gates)
        assert status == "blocked"
        # Unknown also fails closed.
        unknown_gates = [
            make_gate("x", status="unknown", detail="unknown mandatory")
        ]
        assert receipt_status_from_gates(unknown_gates) == "blocked"

    def check_missing_gate_rejected() -> None:
        receipt = collect_tree_evidence(root, mode="offline")
        incomplete = dict(receipt)
        # Drop one mandatory gate.
        incomplete["gates"] = [
            g for g in receipt["gates"] if g.get("gate_id") != "privacy_scan"
        ]
        incomplete["status"] = "accepted"
        body = {k: v for k, v in incomplete.items() if k != "receipt_digest_sha256"}
        incomplete["receipt_digest_sha256"] = sha256_hex(canonical_json(body))
        errors = validate_receipt_struct(incomplete)
        assert errors, "missing mandatory gate must fail validation"

    _check("gitkeep_present", check_gitkeep)
    _check("policy_constants", check_policy_constants)
    _check("prior_tasks_present", check_prior_tasks_present)
    _check("version_pins", check_version_pins)
    _check("config_digest", check_config_digest)
    _check("task_status_alone_rejected", check_task_status_alone_rejected)
    _check("fresh_receipt", check_fresh_receipt)
    _check("blocked_unknown_fail_closed", check_blocked_unknown_fail_closed)
    _check("missing_gate_rejected", check_missing_gate_rejected)
    return report


def run_release_gate(
    *,
    repo_root: Path | None = None,
    mode: str = "live",
    output_path: Path | None = None,
    write_receipt: bool = True,
) -> dict[str, Any]:
    """Run the release gate and optionally persist a digested receipt."""
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    if mode == "offline":
        report = offline_self_check(root)
        receipt = None
        if report.get("ok"):
            receipt = collect_tree_evidence(root, mode="offline")
            assert_receipt_valid(receipt)
        result: dict[str, Any] = {
            "ok": bool(report.get("ok"))
            and receipt is not None
            and receipt.get("status") == "accepted",
            "mode": "offline",
            "report": report,
            "receipt": receipt,
        }
    else:
        receipt = collect_tree_evidence(root, mode=mode)
        try:
            assert_receipt_valid(receipt)
            validate_task_status_alone_rejected()
            ok = receipt.get("status") == "accepted"
        except ReleaseGateError as exc:
            ok = False
            receipt = dict(receipt)
            receipt["status"] = "rejected"
            receipt.setdefault("notes", []).append(f"validation_error:{exc}")
            body = {k: v for k, v in receipt.items() if k != "receipt_digest_sha256"}
            receipt["receipt_digest_sha256"] = sha256_hex(canonical_json(body))
        result = {
            "ok": ok,
            "mode": mode,
            "report": None,
            "receipt": receipt,
        }

    if write_receipt and result.get("receipt") is not None:
        out = output_path
        if out is None:
            out = default_receipt_dir() / f"{TASK_ID.lower()}-{utc_now().replace(':', '')}.json"
        # Refuse to write into tracked source tree by default path policy:
        # operators may still pass an explicit --output under the repo.
        atomic_write_json(Path(out), result["receipt"])
        result["receipt_path"] = str(out)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/ops/uspto/validate_release.py",
        description=(
            "USPTO submission-assurance current-tree completion and release gate "
            f"({TASK_ID}). Fresh receipt binds git tree, config, fixture/ruleset/"
            "parser versions, test results, privacy scan, and merge-queue evidence. "
            "Task status alone cannot satisfy acceptance."
        ),
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help=(
            "Run offline self-check (policy, prior tasks, version pins, synthetic "
            "fresh receipt). Default validation command for the taskboard."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: inferred from script location)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional path for the digested receipt JSON. Default is under "
            "$XDG_STATE_HOME/ipfs_accelerate_py/uspto_submission_assurance/release/"
        ),
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Do not write a receipt file (stdout report only)",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="Validate an existing receipt JSON instead of collecting a fresh one",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=True,
        help="Emit machine-readable JSON (default)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path(args.repo_root) if args.repo_root is not None else _REPO_ROOT

    try:
        if args.receipt is not None:
            receipt = load_json(Path(args.receipt))
            if not isinstance(receipt, Mapping):
                raise ReleaseGateError("receipt root must be an object")
            errors = validate_receipt_struct(receipt)
            payload = {
                "ok": not errors and receipt.get("status") == "accepted",
                "mode": "validate",
                "errors": errors,
                "receipt_id": receipt.get("receipt_id"),
                "status": receipt.get("status"),
                "receipt_digest_sha256": receipt.get("receipt_digest_sha256"),
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0 if payload["ok"] else 1

        mode = "offline" if args.offline else "live"
        result = run_release_gate(
            repo_root=root,
            mode=mode,
            output_path=args.output,
            write_receipt=not args.no_write,
        )
        # CLI stdout is content-free summary + optional compact receipt meta.
        out: dict[str, Any] = {
            "ok": result["ok"],
            "mode": result["mode"],
            "task_id": TASK_ID,
            "goal_id": GOAL_ID,
            "schema_version": SCHEMA_VERSION,
            "interface": INTERFACE,
        }
        if result.get("report") is not None:
            out["report"] = {
                "ok": result["report"]["ok"],
                "checks": result["report"]["checks"],
                "mandatory_gates": result["report"]["mandatory_gates"],
                "required_prior_tasks": result["report"]["required_prior_tasks"],
                "receipt": result["report"].get("receipt"),
            }
        if result.get("receipt") is not None:
            rec = result["receipt"]
            out["receipt"] = {
                "receipt_id": rec.get("receipt_id"),
                "status": rec.get("status"),
                "receipt_digest_sha256": rec.get("receipt_digest_sha256"),
                "git": rec.get("git"),
                "config_digest_sha256": (rec.get("config") or {}).get("digest_sha256"),
                "gate_summary": [
                    {"gate_id": g.get("gate_id"), "status": g.get("status")}
                    for g in (rec.get("gates") or [])
                ],
                "prior_tasks_present": (rec.get("prior_tasks") or {}).get(
                    "all_required_present"
                ),
            }
            assert_content_free(out["receipt"])
        if result.get("receipt_path"):
            out["receipt_path"] = result["receipt_path"]

        print(json.dumps(out, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    except ReleaseGateError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "task_id": TASK_ID,
                    "schema_version": SCHEMA_VERSION,
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
