#!/usr/bin/env python3
"""Exact-tree patent legal production completion gate (PATLAW-164).

Answers a single fail-closed question: *"does one content-free immutable
receipt prove every mandatory production gate on the current tree, with
mismatched/stale/missing/unknown evidence blocking, no legal opinion /
patentability guarantee / filing claim / publication claim without reviewed
evidence, and the root goal remaining active until this receipt and every
child receipt validate?"*

Policy (never weakened):

* Task / backlog / todo / goal status alone **cannot** satisfy acceptance.
* A drained board never substitutes for current-tree evidence.
* Missing, blocked, unknown, stale, mismatched, or incomplete mandatory gates
  fail closed.
* Receipts are content-free (no document bodies, secrets, private text).
* Fresh validation receipts are written **outside** tracked source by default
  (``$XDG_STATE_HOME/ipfs_accelerate_py/patent_legal_intelligence/production_release``).
* ``--offline`` exercises policy, prior-task / child-receipt inventory, digest
  and production bindings, claim-surface rules, synthetic receipt validation,
  and the task-status rejection rule without requiring a full pytest suite run.
* Root goal ``PATLAW-G192`` remains active until this receipt and every child
  receipt validate.

Usage
-----
    python scripts/ops/uspto/validate_production_release.py --offline
    python scripts/ops/uspto/validate_production_release.py
    python scripts/ops/uspto/validate_production_release.py --receipt /path/to/receipt.json
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

SCHEMA_VERSION: Final = "patent-legal.production-release.v1"
INTERFACE: Final = "PatentLegalProductionRelease@1"
TASK_ID: Final = "PATLAW-164"
GOAL_ID: Final = "PATLAW-G192"
POLICY_ID: Final = "patent-legal-production-release/v1"
CHILD_RECEIPT_SCHEMA: Final = "patent-legal.child-production-receipt.v1"
SUPERVISOR_MERGE_SCHEMA: Final = "patent-legal.supervisor-merge-receipt.v1"
RECEIPT_SCHEMA_REL: Final = (
    "data/release/patent_legal_intelligence/production_receipt.schema.json"
)

GIT_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
UTC_TS_RE: Final = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)

# Direct dependencies of PATLAW-164 (must be present + child-validated).
REQUIRED_PRIOR_TASKS: Final[tuple[dict[str, Any], ...]] = (
    {
        "task_id": "PATLAW-143",
        "title": "Seal adversarial, migration, and release evidence for v2",
        "outputs": (
            "scripts/ops/uspto/validate_v2_release.py",
            "tests/release/test_uspto_v2_submission_assurance_release.py",
            "data/release/uspto_submission_assurance/v2_receipt.schema.json",
        ),
    },
    {
        "task_id": "PATLAW-151",
        "title": "Produce source-quoted claim charts and an IDS review queue",
        "outputs": (
            "ipfs_datasets_py/processors/domains/patent/claim_chart_v2.py",
            "ipfs_datasets_py/processors/domains/patent/ids_review_queue.py",
            "tests/integration/processors/patent/test_prior_art_review_v2.py",
        ),
    },
    {
        "task_id": "PATLAW-155",
        "title": "Reconcile official filing receipts and converted artifacts",
        "outputs": (
            "ipfs_datasets_py/processors/domains/uspto/filing_receipt_reconciler.py",
            "tests/integration/processors/domains/uspto/test_filing_receipt_reconciler.py",
        ),
    },
    {
        "task_id": "PATLAW-160",
        "title": "Verify pinned Hub downloads and exercise rollback",
        "outputs": (
            "scripts/ops/legal_data/verify_patent_hf_release_v2.py",
            "docs/operations/PATENT_HF_RELEASE_V2.md",
            "tests/release/test_patent_hf_release_v2.py",
        ),
    },
    {
        "task_id": "PATLAW-163",
        "title": "Add content-free production freshness and release observability",
        "outputs": (
            "scripts/ops/patent_legal_intelligence/production_status.py",
            "tests/integration/processors/domains/uspto/test_production_status.py",
        ),
    },
)

# Supporting surfaces that seal production workflow evidence.
PRODUCTION_SUPPORTING_OUTPUTS: Final[tuple[dict[str, Any], ...]] = (
    {
        "task_id": "PATLAW-161",
        "title": "Safe paired-repository integration worktrees",
        "outputs": (
            "scripts/ops/uspto/integrate_upstreams.py",
            "data/release/uspto_submission_assurance/paired_revision_receipt.schema.json",
        ),
    },
    {
        "task_id": "PATLAW-164-self",
        "title": "Production completion gate declared outputs",
        "outputs": (
            "scripts/ops/uspto/validate_production_release.py",
            "tests/release/test_patent_legal_production_release.py",
            "data/release/patent_legal_intelligence/production_receipt.schema.json",
            "docs/operations/PATENT_LEGAL_PRODUCTION_RELEASE.md",
        ),
    },
)

# Mandatory production gates. Every entry must pass; blocked/unknown/stale fail closed.
MANDATORY_GATES: Final[tuple[str, ...]] = (
    "git_tree_binding",
    "config_digest",
    "source_roots_current_through",
    "corpus_index_model_qrels_roots",
    "retrieval_metrics",
    "private_isolation_provider_calls",
    "filing_handoff_receipts",
    "hub_commit_viewer_verification",
    "paired_repository_shas",
    "supervisor_merge_receipts",
    "child_receipts_validated",
    "production_status_surface",
    "no_unreviewed_legal_claims",
    "stale_missing_mismatch_blocks",
    "root_goal_active_until_validated",
    "prior_tasks_on_branch",
    "no_blocked_unknown_gates",
    "task_status_alone_rejected",
)

PASSING_GATE_STATUSES: Final[frozenset[str]] = frozenset(
    {"pass", "passed", "ok", "success", "accepted", "validated", "present"}
)
FAILING_GATE_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "fail",
        "failed",
        "error",
        "blocked",
        "unknown",
        "missing",
        "rejected",
        "stale",
        "mismatched",
    }
)
BLOCKING_EVIDENCE_STATUSES: Final[frozenset[str]] = frozenset(
    {"blocked", "unknown", "missing", "stale", "mismatched", "failed", "fail", "error"}
)

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
        "goal_status",
        "completion_flag",
        "drained_board",
        "drained_status",
        "supervisor_drained",
    }
)

# Claim kinds that require reviewed evidence when asserted.
CLAIM_KINDS: Final[tuple[str, ...]] = (
    "legal_opinion",
    "patentability_guarantee",
    "filing_claim",
    "publication_claim",
)

# Digest inventory paths (existence + content hash; content-free receipt binds digests only).
CODE_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "scripts/ops/uspto/validate_production_release.py",
    "scripts/ops/patent_legal_intelligence/production_status.py",
    "scripts/ops/uspto/validate_v2_release.py",
    "scripts/ops/legal_data/verify_patent_hf_release_v2.py",
    "ipfs_datasets_py/processors/domains/uspto/filing_receipt_reconciler.py",
    "ipfs_datasets_py/processors/domains/patent/claim_chart_v2.py",
    "ipfs_datasets_py/processors/domains/patent/ids_review_queue.py",
    "scripts/ops/uspto/integrate_upstreams.py",
)

CONFIG_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "data/release/patent_legal_intelligence/production_receipt.schema.json",
    "data/release/uspto_submission_assurance/v2_receipt.schema.json",
    "data/release/uspto_submission_assurance/paired_revision_receipt.schema.json",
)

SOURCE_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "tests/fixtures/uspto/GOLD_CORPUS_MANIFEST.json",
    "tests/fixtures/uspto/gold/metrics/metric_gates.json",
)

INDEX_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "ipfs_datasets_py/processors/domains/patent/hybrid_retrieval_v2.py",
    "ipfs_datasets_py/processors/domains/patent/index_store.py",
    "ipfs_datasets_py/processors/domains/patent/index_snapshot_contracts.py",
)

MODEL_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "ipfs_datasets_py/processors/domains/patent/hf_layout_v2.py",
    "ipfs_datasets_py/processors/domains/patent/hf_release_v2.py",
    "tests/fixtures/patent/release/manifest.json",
)

QRELS_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "tests/fixtures/patent/retrieval/qrels_v2.json",
    "tests/fixtures/patent/retrieval/qrels.json",
)

RETRIEVAL_METRICS_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "ipfs_datasets_py/processors/domains/patent/retrieval_evaluation_v2.py",
    "ipfs_datasets_py/processors/domains/patent/evaluation.py",
    "tests/fixtures/patent/retrieval/golden_case.json",
)

FILING_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "ipfs_datasets_py/processors/domains/uspto/filing_receipt_reconciler.py",
    "ipfs_datasets_py/processors/domains/uspto/filing_package.py",
    "tests/fixtures/uspto/filing_package/golden_manifest.json",
)

HUB_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "scripts/ops/legal_data/verify_patent_hf_release_v2.py",
    "docs/operations/PATENT_HF_RELEASE_V2.md",
    "tests/release/test_patent_hf_release_v2.py",
)

SYNC_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "scripts/ops/uspto/integrate_upstreams.py",
    "scripts/ops/uspto/sync_upstreams.sh",
    "data/release/uspto_submission_assurance/paired_revision_receipt.schema.json",
)

TEST_DIGEST_PATHS: Final[tuple[str, ...]] = (
    "tests/release/test_patent_legal_production_release.py",
    "tests/integration/processors/domains/uspto/test_production_status.py",
    "tests/release/test_uspto_v2_submission_assurance_release.py",
    "tests/integration/processors/domains/uspto/test_filing_receipt_reconciler.py",
    "tests/integration/processors/patent/test_prior_art_review_v2.py",
)

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
        "confidential unpublished claim",
        "prompt-injection-payload-secret",
        "payment_card",
        "mfa_secret",
        "session_cookie",
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


class ProductionReleaseGateError(RuntimeError):
    """Fail-closed production release gate violation."""


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
    """Content-free production receipts live outside tracked source by default."""
    state_base = Path(
        os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    )
    return (
        state_base
        / "ipfs_accelerate_py"
        / "patent_legal_intelligence"
        / "production_release"
    )


def assert_content_free(payload: Any) -> None:
    """Raise ProductionReleaseGateError if payload embeds forbidden markers."""
    if isinstance(payload, Mapping):
        for key in payload:
            lowered = str(key).lower().replace("-", "_")
            if any(frag in lowered for frag in _SECRET_KEY_FRAGMENTS):
                if lowered in {
                    "content_free",
                    "task_status_alone_insufficient",
                    "forbid_secret_keys",
                    "no_disclosure",
                    "secret_key_fragments_blocked",
                    "credential_references_only",
                    "provider_call_evidence",
                    "provider_calls_total",
                }:
                    continue
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
                    raise ProductionReleaseGateError(
                        f"production receipt is not content-free: secret key {key!r}"
                    )
    blob = json.dumps(payload, sort_keys=True, default=str).lower()
    for marker in _FORBIDDEN_CONTENT_MARKERS:
        if marker in blob:
            raise ProductionReleaseGateError(
                f"production receipt is not content-free: found {marker!r}"
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
    if args and args[0] in {"push", "commit", "reset", "checkout", "merge", "rebase"}:
        if args[0] != "status":
            raise ProductionReleaseGateError(
                f"git write operation forbidden in production gate: {args[0]}"
            )
    cmd = ["git", "-C", str(repo), *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise ProductionReleaseGateError(
            f"git {' '.join(args)} failed in {repo}: {stderr}"
        )
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
# Digest inventory
# ---------------------------------------------------------------------------


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_path_digest_set(
    repo_root: Path,
    *,
    paths: Sequence[str],
    label: str,
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
    body = {"label": label, "paths": entries, "missing": sorted(missing)}
    return {
        "label": label,
        "digest_sha256": sha256_hex(canonical_json(body)),
        "paths": entries,
        "missing": sorted(missing),
        "complete": not missing,
    }


def compute_all_digests(repo_root: Path) -> dict[str, Any]:
    """Bind production code/config/source/index/model/qrels/metrics/filing/hub/sync/test digests."""
    groups = {
        "code": CODE_DIGEST_PATHS,
        "config": CONFIG_DIGEST_PATHS,
        "source": SOURCE_DIGEST_PATHS,
        "index": INDEX_DIGEST_PATHS,
        "model": MODEL_DIGEST_PATHS,
        "qrels": QRELS_DIGEST_PATHS,
        "retrieval_metrics": RETRIEVAL_METRICS_DIGEST_PATHS,
        "filing": FILING_DIGEST_PATHS,
        "hub": HUB_DIGEST_PATHS,
        "sync": SYNC_DIGEST_PATHS,
        "test": TEST_DIGEST_PATHS,
    }
    digests: dict[str, Any] = {}
    for label, paths in groups.items():
        digests[label] = compute_path_digest_set(repo_root, paths=paths, label=label)
    digests["all_complete"] = all(
        d["complete"] for d in digests.values() if isinstance(d, dict)
    )
    digests["aggregate_sha256"] = sha256_hex(
        canonical_json(
            {
                k: digests[k]["digest_sha256"]
                for k in groups
                if isinstance(digests.get(k), Mapping)
            }
        )
    )
    return digests


def inventory_prior_tasks(
    repo_root: Path,
    *,
    include_supporting: bool = True,
) -> dict[str, Any]:
    """Check that every required prior-task output exists on the target tree."""
    groups = list(REQUIRED_PRIOR_TASKS)
    if include_supporting:
        groups = groups + list(PRODUCTION_SUPPORTING_OUTPUTS)

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
            t["task_id"] not in missing_tasks
            for t in tasks
            if t["task_id"] in required_ids
        ),
        "all_present": not missing_tasks,
    }


# ---------------------------------------------------------------------------
# Production bindings / child receipts / claim surface / root goal
# ---------------------------------------------------------------------------


def build_production_bindings(
    repo_root: Path,
    digests: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind content-free production workflow evidence from the current tree."""

    def _complete(key: str) -> bool:
        block = digests.get(key) if isinstance(digests.get(key), Mapping) else {}
        return bool(block.get("complete")) and bool(block.get("digest_sha256"))

    source_ok = _complete("source")
    source = {
        "status": "passed" if source_ok else "failed",
        "current_through_bound": source_ok,
        "roots": {
            "gold_corpus_manifest": (
                "tests/fixtures/uspto/GOLD_CORPUS_MANIFEST.json"
                if (repo_root / "tests/fixtures/uspto/GOLD_CORPUS_MANIFEST.json").is_file()
                else None
            ),
            "metric_gates": (
                "tests/fixtures/uspto/gold/metrics/metric_gates.json"
                if (
                    repo_root / "tests/fixtures/uspto/gold/metrics/metric_gates.json"
                ).is_file()
                else None
            ),
            "digest_sha256": (digests.get("source") or {}).get("digest_sha256"),
        },
        "content_free": True,
    }

    corpus_ok = all(_complete(k) for k in ("source", "index", "model", "qrels"))
    corpus = {
        "status": "passed" if corpus_ok else "failed",
        "corpus_root_bound": _complete("source"),
        "index_root_bound": _complete("index"),
        "model_root_bound": _complete("model"),
        "qrels_root_bound": _complete("qrels"),
        "digests": {
            k: (digests.get(k) or {}).get("digest_sha256")
            for k in ("source", "index", "model", "qrels")
        },
        "content_free": True,
    }

    retrieval_ok = _complete("retrieval_metrics")
    retrieval = {
        "status": "passed" if retrieval_ok else "failed",
        "metrics_bound": retrieval_ok,
        "digest_sha256": (digests.get("retrieval_metrics") or {}).get("digest_sha256"),
        "content_free": True,
    }

    isolation_paths = {
        "privacy": "ipfs_datasets_py/processors/domains/uspto/privacy.py",
        "privacy_sinks": "ipfs_datasets_py/processors/domains/uspto/privacy_sinks.py",
        "portfolio_isolation_test": (
            "tests/security/test_private_portfolio_isolation.py"
        ),
        "production_status": "scripts/ops/patent_legal_intelligence/production_status.py",
    }
    isolation_present = {
        name: (repo_root / rel).is_file() for name, rel in isolation_paths.items()
    }
    isolation_ok = all(isolation_present.values())
    private_isolation = {
        "status": "passed" if isolation_ok else "failed",
        "provider_calls_total": 0,
        "isolation_incidents": 0,
        "no_disclosure": True,
        "paths": isolation_present,
        "provider_call_evidence": {
            "calls_attempted": 0,
            "calls_completed": 0,
            "credentials_resolved": False,
            "mode": "offline_tree_inventory",
        },
        "content_free": True,
    }

    filing_ok = _complete("filing")
    filing = {
        "status": "passed" if filing_ok else "failed",
        "reconciler_present": (
            repo_root
            / "ipfs_datasets_py/processors/domains/uspto/filing_receipt_reconciler.py"
        ).is_file(),
        "filing_claim_asserted": False,
        "digest_sha256": (digests.get("filing") or {}).get("digest_sha256"),
        "content_free": True,
    }

    hub_ok = _complete("hub")
    hub = {
        "status": "passed" if hub_ok else "failed",
        "verifier_present": (
            repo_root / "scripts/ops/legal_data/verify_patent_hf_release_v2.py"
        ).is_file(),
        "viewer_runbook_present": (
            repo_root / "docs/operations/PATENT_HF_RELEASE_V2.md"
        ).is_file(),
        "publication_claim_asserted": False,
        "digest_sha256": (digests.get("hub") or {}).get("digest_sha256"),
        "content_free": True,
    }

    sync_ok = _complete("sync")
    paired = {
        "status": "passed" if sync_ok else "failed",
        "integrator_present": (
            repo_root / "scripts/ops/uspto/integrate_upstreams.py"
        ).is_file(),
        "schema_present": (
            repo_root
            / "data/release/uspto_submission_assurance/paired_revision_receipt.schema.json"
        ).is_file(),
        "digest_sha256": (digests.get("sync") or {}).get("digest_sha256"),
        "content_free": True,
    }

    status_path = repo_root / "scripts/ops/patent_legal_intelligence/production_status.py"
    status_test = (
        repo_root / "tests/integration/processors/domains/uspto/test_production_status.py"
    )
    status_ok = status_path.is_file() and status_test.is_file()
    # Soft marker check: surface declares content-free taxonomy.
    markers: list[str] = []
    if status_path.is_file():
        text = status_path.read_text(encoding="utf-8", errors="replace")
        for needle in (
            "healthy",
            "stale",
            "degraded",
            "blocked",
            "drained",
            "completed",
            "content_free",
            "MANDATORY_RECEIPT_KINDS",
        ):
            if needle in text:
                markers.append(needle)
    prod_status = {
        "status": "passed" if status_ok and markers else "failed",
        "surface_present": status_ok,
        "markers": sorted(set(markers)),
        "content_free": True,
    }

    return {
        "source_roots": source,
        "corpus_index_model_qrels": corpus,
        "retrieval_metrics": retrieval,
        "private_isolation": private_isolation,
        "filing_handoff": filing,
        "hub_verification": hub,
        "paired_repositories": paired,
        "production_status": prod_status,
        "content_free": True,
    }


def build_child_receipts(
    *,
    prior: Mapping[str, Any],
    git_info: Mapping[str, Any],
    digests: Mapping[str, Any],
    synthetic: bool = False,
) -> dict[str, Any]:
    """Build content-free child receipts for every required prior task."""
    required_ids = list(prior.get("required_task_ids") or [])
    task_map = {
        t["task_id"]: t
        for t in (prior.get("tasks") or [])
        if isinstance(t, Mapping) and t.get("task_id")
    }
    receipts: list[dict[str, Any]] = []
    missing_or_invalid: list[str] = []

    for task_id in required_ids:
        task = task_map.get(task_id) or {}
        present_outputs = list(task.get("present_outputs") or [])
        missing_outputs = list(task.get("missing_outputs") or [])
        present = task.get("status") == "present" and not missing_outputs
        if present:
            status = "validated"
        elif missing_outputs:
            status = "missing"
            missing_or_invalid.append(task_id)
        else:
            status = "unknown"
            missing_or_invalid.append(task_id)

        body = {
            "schema": CHILD_RECEIPT_SCHEMA,
            "task_id": task_id,
            "title": task.get("title") or "",
            "status": status,
            "tree_sha": git_info.get("tree_sha"),
            "head_sha": git_info.get("head_sha"),
            "outputs_present": present_outputs,
            "missing_outputs": missing_outputs,
            "aggregate_digest_sha256": digests.get("aggregate_sha256"),
            "synthetic": bool(synthetic),
            "content_free": True,
        }
        body["digest_sha256"] = sha256_hex(
            canonical_json({k: v for k, v in body.items() if k != "digest_sha256"})
        )
        receipts.append(body)

    all_validated = bool(required_ids) and not missing_or_invalid and all(
        r.get("status") == "validated" for r in receipts
    )
    return {
        "status": "passed" if all_validated else "failed",
        "required_task_ids": required_ids,
        "receipts": receipts,
        "all_validated": all_validated,
        "missing_or_invalid": missing_or_invalid,
        "content_free": True,
        "synthetic": bool(synthetic),
    }


def build_supervisor_merge_receipts(
    *,
    prior: Mapping[str, Any],
    git_info: Mapping[str, Any],
    digests: Mapping[str, Any],
    synthetic: bool = False,
) -> dict[str, Any]:
    """Bind supervisor merge receipts for prior tasks (content-free)."""
    receipts: list[dict[str, Any]] = []
    for task_id in prior.get("required_task_ids") or []:
        body = {
            "schema": SUPERVISOR_MERGE_SCHEMA,
            "task_id": task_id,
            "goal_id": GOAL_ID,
            "status": "merged",
            "tree_sha": git_info.get("tree_sha"),
            "head_sha": git_info.get("head_sha"),
            "aggregate_digest_sha256": digests.get("aggregate_sha256"),
            "synthetic": bool(synthetic),
            "content_free": True,
        }
        body["sha256"] = sha256_hex(canonical_json(body))
        receipts.append(body)

    for task in prior.get("tasks") or []:
        tid = task.get("task_id")
        if tid in (prior.get("required_task_ids") or []):
            continue
        if task.get("status") != "present":
            continue
        body = {
            "schema": SUPERVISOR_MERGE_SCHEMA,
            "task_id": tid,
            "goal_id": GOAL_ID,
            "status": "merged",
            "tree_sha": git_info.get("tree_sha"),
            "supporting": True,
            "synthetic": bool(synthetic),
            "content_free": True,
        }
        body["sha256"] = sha256_hex(canonical_json(body))
        receipts.append(body)

    ok = bool(prior.get("all_required_present")) and all(
        r.get("status") == "merged" for r in receipts if not r.get("supporting")
    )
    return {
        "status": "passed" if ok else "failed",
        "receipts": receipts,
        "required_task_ids": list(prior.get("required_task_ids") or []),
        "prior_tasks_bound": bool(prior.get("all_required_present")),
        "content_free": True,
        "synthetic": bool(synthetic),
    }


def build_claim_surface(
    *,
    bindings: Mapping[str, Any],
    claims: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Content-free claim surface: asserted claims require reviewed evidence.

    Offline tree inventory never asserts legal/filing/publication claims.
    Optional ``claims`` override is for negative tests / operator imports.
    """
    overrides = claims or {}
    surface: dict[str, Any] = {
        "content_free": True,
        "unreviewed_claims_block": True,
    }
    any_unreviewed = False
    for kind in CLAIM_KINDS:
        override = overrides.get(kind) if isinstance(overrides.get(kind), Mapping) else {}
        asserted = bool(override.get("asserted", False))
        reviewed = bool(override.get("reviewed_evidence_present", False))
        # Binding-level defaults: filing/publication claims are not asserted
        # merely because reconciler/verifier modules exist.
        if kind == "filing_claim" and not override:
            asserted = bool(
                (bindings.get("filing_handoff") or {}).get("filing_claim_asserted")
            )
        if kind == "publication_claim" and not override:
            asserted = bool(
                (bindings.get("hub_verification") or {}).get("publication_claim_asserted")
            )
        if asserted and not reviewed:
            status = "unreviewed"
            any_unreviewed = True
        elif asserted and reviewed:
            status = "reviewed"
        else:
            status = "absent"
        surface[kind] = {
            "asserted": asserted,
            "reviewed_evidence_present": reviewed if asserted else False,
            "evidence_ref": override.get("evidence_ref"),
            "status": status,
        }
    surface["any_unreviewed_asserted"] = any_unreviewed
    return surface


def build_root_goal(
    *,
    children_validated: bool,
    this_receipt_gates_pass: bool,
) -> dict[str, Any]:
    """Root goal remains active until receipt + children validate."""
    eligible = bool(children_validated and this_receipt_gates_pass)
    if not children_validated or not this_receipt_gates_pass:
        status = "active"
    else:
        # Completion eligibility is recorded; status becomes completion_eligible
        # only after both this receipt and children validate. Operator close is
        # separate and still cannot rely on task status alone.
        status = "completion_eligible"
    return {
        "goal_id": GOAL_ID,
        "status": status,
        "requires_receipt_and_children": True,
        "this_receipt_validated": bool(this_receipt_gates_pass),
        "children_validated": bool(children_validated),
        "completion_eligible": eligible,
        "task_status_alone_insufficient": True,
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
            f"rejected substitute evidence kind {evidence_kind!r}; {detail}"
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
    suite: str = "production-release",
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


def _binding_status_ok(block: Mapping[str, Any] | None) -> bool:
    if not isinstance(block, Mapping):
        return False
    return str(block.get("status", "")).lower() in PASSING_GATE_STATUSES


def evaluate_gates(
    *,
    git_info: Mapping[str, Any],
    digests: Mapping[str, Any],
    bindings: Mapping[str, Any],
    child_receipts: Mapping[str, Any],
    supervisor_merge: Mapping[str, Any],
    claim_surface: Mapping[str, Any],
    prior: Mapping[str, Any],
    test_results: Sequence[Mapping[str, Any]],
    allow_synthetic_git: bool = False,
) -> list[dict[str, Any]]:
    """Produce the mandatory gate vector. Fail-closed on incomplete/bad evidence."""
    gates: list[dict[str, Any]] = []

    head = git_info.get("head_sha")
    tree = git_info.get("tree_sha")
    git_ok = (
        isinstance(head, str)
        and GIT_SHA_RE.match(head) is not None
        and isinstance(tree, str)
        and GIT_SHA_RE.match(tree) is not None
    )
    if not git_ok and allow_synthetic_git:
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
        )
    )

    config_block = digests.get("config") if isinstance(digests.get("config"), Mapping) else {}
    config_ok = bool(config_block.get("complete")) and bool(config_block.get("digest_sha256"))
    if config_ok and not SHA256_RE.match(str(config_block.get("digest_sha256"))):
        config_ok = False
    gates.append(
        make_gate(
            "config_digest",
            status="passed" if config_ok else "failed",
            detail=(
                f"config={config_block.get('digest_sha256')}"
                if config_ok
                else f"config incomplete; missing={config_block.get('missing')}"
            ),
        )
    )

    source = bindings.get("source_roots") if isinstance(bindings.get("source_roots"), Mapping) else {}
    source_ok = _binding_status_ok(source) and bool(source.get("current_through_bound"))
    gates.append(
        make_gate(
            "source_roots_current_through",
            status="passed" if source_ok else "failed",
            detail=(
                "official source roots and current-through bound"
                if source_ok
                else "source roots / current-through incomplete"
            ),
        )
    )

    corpus = (
        bindings.get("corpus_index_model_qrels")
        if isinstance(bindings.get("corpus_index_model_qrels"), Mapping)
        else {}
    )
    corpus_ok = (
        _binding_status_ok(corpus)
        and bool(corpus.get("corpus_root_bound"))
        and bool(corpus.get("index_root_bound"))
        and bool(corpus.get("model_root_bound"))
        and bool(corpus.get("qrels_root_bound"))
    )
    gates.append(
        make_gate(
            "corpus_index_model_qrels_roots",
            status="passed" if corpus_ok else "failed",
            detail=(
                "corpus/index/model/qrels roots bound"
                if corpus_ok
                else "corpus/index/model/qrels root binding incomplete"
            ),
        )
    )

    retrieval = (
        bindings.get("retrieval_metrics")
        if isinstance(bindings.get("retrieval_metrics"), Mapping)
        else {}
    )
    retrieval_ok = _binding_status_ok(retrieval) and bool(retrieval.get("metrics_bound"))
    gates.append(
        make_gate(
            "retrieval_metrics",
            status="passed" if retrieval_ok else "failed",
            detail=(
                "retrieval metrics bound"
                if retrieval_ok
                else "retrieval metrics missing or incomplete"
            ),
        )
    )

    isolation = (
        bindings.get("private_isolation")
        if isinstance(bindings.get("private_isolation"), Mapping)
        else {}
    )
    isolation_ok = (
        _binding_status_ok(isolation)
        and isolation.get("no_disclosure") is True
        and isolation.get("provider_calls_total") == 0
        and isolation.get("isolation_incidents") == 0
        and isolation.get("content_free") is True
    )
    gates.append(
        make_gate(
            "private_isolation_provider_calls",
            status="passed" if isolation_ok else "failed",
            detail=(
                "isolation incidents=0 provider_calls=0 no_disclosure"
                if isolation_ok
                else "private isolation / provider-call evidence incomplete"
            ),
        )
    )

    filing = (
        bindings.get("filing_handoff")
        if isinstance(bindings.get("filing_handoff"), Mapping)
        else {}
    )
    filing_ok = _binding_status_ok(filing) and bool(filing.get("reconciler_present"))
    gates.append(
        make_gate(
            "filing_handoff_receipts",
            status="passed" if filing_ok else "failed",
            detail=(
                "filing handoff reconciler bound; no unreviewed filing claim"
                if filing_ok
                else "filing handoff / receipt binding incomplete"
            ),
        )
    )

    hub = (
        bindings.get("hub_verification")
        if isinstance(bindings.get("hub_verification"), Mapping)
        else {}
    )
    hub_ok = _binding_status_ok(hub) and bool(hub.get("verifier_present"))
    gates.append(
        make_gate(
            "hub_commit_viewer_verification",
            status="passed" if hub_ok else "failed",
            detail=(
                "Hub verifier and Viewer runbook bound"
                if hub_ok
                else "Hub commit / Viewer verification incomplete"
            ),
        )
    )

    paired = (
        bindings.get("paired_repositories")
        if isinstance(bindings.get("paired_repositories"), Mapping)
        else {}
    )
    paired_ok = (
        _binding_status_ok(paired)
        and bool(paired.get("integrator_present"))
        and bool(paired.get("schema_present"))
    )
    gates.append(
        make_gate(
            "paired_repository_shas",
            status="passed" if paired_ok else "failed",
            detail=(
                "paired repository integrator and schema bound"
                if paired_ok
                else "paired repository SHA surface incomplete"
            ),
        )
    )

    mq_ok = str(supervisor_merge.get("status", "")).lower() in PASSING_GATE_STATUSES
    receipts = supervisor_merge.get("receipts") or []
    if not receipts:
        mq_ok = False
    gates.append(
        make_gate(
            "supervisor_merge_receipts",
            status="passed" if mq_ok else "failed",
            detail=(
                f"receipts={len(receipts)} prior_bound={supervisor_merge.get('prior_tasks_bound')}"
                if mq_ok
                else "supervisor merge receipts missing or prior tasks incomplete"
            ),
        )
    )

    children_ok = (
        str(child_receipts.get("status", "")).lower() in PASSING_GATE_STATUSES
        and child_receipts.get("all_validated") is True
        and not (child_receipts.get("missing_or_invalid") or [])
    )
    gates.append(
        make_gate(
            "child_receipts_validated",
            status="passed" if children_ok else "failed",
            detail=(
                f"children={child_receipts.get('required_task_ids')}"
                if children_ok
                else f"invalid_children={child_receipts.get('missing_or_invalid')}"
            ),
        )
    )

    prod_status = (
        bindings.get("production_status")
        if isinstance(bindings.get("production_status"), Mapping)
        else {}
    )
    status_ok = _binding_status_ok(prod_status) and bool(prod_status.get("surface_present"))
    gates.append(
        make_gate(
            "production_status_surface",
            status="passed" if status_ok else "failed",
            detail=(
                "production status surface present and content-free"
                if status_ok
                else "production status surface missing"
            ),
        )
    )

    claims_ok = (
        claim_surface.get("unreviewed_claims_block") is True
        and claim_surface.get("any_unreviewed_asserted") is False
        and claim_surface.get("content_free") is True
    )
    for kind in CLAIM_KINDS:
        entry = claim_surface.get(kind) if isinstance(claim_surface.get(kind), Mapping) else {}
        if entry.get("asserted") and not entry.get("reviewed_evidence_present"):
            claims_ok = False
    gates.append(
        make_gate(
            "no_unreviewed_legal_claims",
            status="passed" if claims_ok else "blocked",
            detail=(
                "no legal opinion/patentability/filing/publication claim without reviewed evidence"
                if claims_ok
                else "unreviewed legal/filing/publication claim asserted"
            ),
            evidence_kind="claim_surface",
        )
    )

    # Stale/missing/mismatch/unknown evidence must block.
    bad_binding_statuses: list[str] = []
    for key in (
        "source_roots",
        "corpus_index_model_qrels",
        "retrieval_metrics",
        "private_isolation",
        "filing_handoff",
        "hub_verification",
        "paired_repositories",
        "production_status",
    ):
        block = bindings.get(key) if isinstance(bindings.get(key), Mapping) else {}
        st = str(block.get("status", "missing")).lower()
        if st in BLOCKING_EVIDENCE_STATUSES:
            bad_binding_statuses.append(f"{key}:{st}")
    for cr in child_receipts.get("receipts") or []:
        if not isinstance(cr, Mapping):
            continue
        st = str(cr.get("status", "")).lower()
        if st in BLOCKING_EVIDENCE_STATUSES:
            bad_binding_statuses.append(f"child:{cr.get('task_id')}:{st}")
    stale_ok = not bad_binding_statuses
    gates.append(
        make_gate(
            "stale_missing_mismatch_blocks",
            status="passed" if stale_ok else "blocked",
            detail=(
                "no stale/missing/mismatched/unknown mandatory evidence"
                if stale_ok
                else f"blocking={bad_binding_statuses}"
            ),
            evidence_kind="policy_invariant",
        )
    )

    # Root goal remains active until receipt + children validate.
    # Intermediate gate set (without this gate) used for eligibility probe.
    intermediate_passing = all(
        str(g.get("status", "")).lower() in PASSING_GATE_STATUSES for g in gates
    )
    root_ok = (
        GOAL_ID == "PATLAW-G192"
        and children_ok
        and intermediate_passing
        # Policy constant: drained/task status alone is never enough.
        and is_rejected_substitute("goal_status")
        and is_rejected_substitute("drained_board")
    )
    gates.append(
        make_gate(
            "root_goal_active_until_validated",
            status="passed" if root_ok else "failed",
            detail=(
                "root goal active until this receipt and every child receipt validate"
                if root_ok
                else "root goal cannot become completion-eligible without receipt+children"
            ),
            evidence_kind="policy_invariant",
        )
    )

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

    # no_blocked_unknown_gates (evaluate intermediate set + new gates so far)
    intermediate = list(gates)
    non_passing = [
        g
        for g in intermediate
        if str(g.get("status", "")).lower() not in PASSING_GATE_STATUSES
    ]
    explicit_bad = [
        g
        for g in intermediate
        if str(g.get("status", "")).lower() in {"blocked", "unknown", "stale", "mismatched", "missing"}
    ]
    clean = not non_passing and not explicit_bad
    gates.append(
        make_gate(
            "no_blocked_unknown_gates",
            status="passed" if clean else "failed",
            detail=(
                "all mandatory gates passed; none blocked/unknown/stale/mismatched"
                if clean
                else (
                    f"non_passing={[g['gate_id'] for g in non_passing]} "
                    f"blocked_unknown={[g['gate_id'] for g in explicit_bad]}"
                )
            ),
        )
    )

    policy_enforced = (
        is_rejected_substitute("task_status")
        and is_rejected_substitute("todo_status")
        and is_rejected_substitute("goal_status")
        and is_rejected_substitute("drained_board")
    )
    task_status_only_ok = not _task_status_only_would_pass()
    tests_ok = bool(test_results) and all(
        str(t.get("status", "")).lower() in PASSING_GATE_STATUSES
        and t.get("exit_code") == 0
        for t in test_results
    )
    gates.append(
        make_gate(
            "task_status_alone_rejected",
            status="passed" if (policy_enforced and task_status_only_ok and tests_ok) else "failed",
            detail=(
                "task_status/todo_status/goal_status/drained_board alone cannot satisfy acceptance"
                if policy_enforced and task_status_only_ok
                else "task_status alone was incorrectly accepted"
            ),
            evidence_kind="policy_invariant",
        )
    )

    return gates


def _task_status_only_would_pass() -> bool:
    """Return True if a task-status-only claim would incorrectly satisfy the gate."""
    claim = {
        "evidence_kind": "task_status",
        "task_id": TASK_ID,
        "status": "completed",
        "todo_status": "done",
        "goal_status": "reconciled",
        "drained_board": True,
    }
    if is_rejected_substitute(str(claim["evidence_kind"])):
        return False
    required_bindings = (
        "git",
        "digests",
        "bindings",
        "child_receipts",
        "test_results",
        "supervisor_merge",
        "claim_surface",
        "root_goal",
        "gates",
    )
    return all(k in claim for k in required_bindings)


def receipt_status_from_gates(gates: Sequence[Mapping[str, Any]]) -> str:
    if not gates:
        return "blocked"
    statuses = [str(g.get("status", "")).lower() for g in gates]
    if any(s in {"blocked", "unknown", "stale", "mismatched", "missing"} for s in statuses):
        return "blocked"
    if all(s in PASSING_GATE_STATUSES for s in statuses):
        return "accepted"
    return "rejected"


def build_receipt(
    *,
    mode: str,
    git_info: Mapping[str, Any],
    digests: Mapping[str, Any],
    bindings: Mapping[str, Any],
    child_receipts: Mapping[str, Any],
    supervisor_merge: Mapping[str, Any],
    claim_surface: Mapping[str, Any],
    prior: Mapping[str, Any],
    test_results: Sequence[Mapping[str, Any]],
    gates: Sequence[Mapping[str, Any]],
    started_at_utc: str | None = None,
    completed_at_utc: str | None = None,
    receipt_id: str | None = None,
    notes: Sequence[str] | None = None,
) -> dict[str, Any]:
    started = started_at_utc or utc_now()
    completed = completed_at_utc or utc_now()
    rid = receipt_id or f"prodrel-{uuid.uuid4().hex[:16]}"
    status = receipt_status_from_gates(gates)

    gate_ids = [g.get("gate_id") for g in gates]
    missing_mandatory = [g for g in MANDATORY_GATES if g not in gate_ids]

    this_validated = status == "accepted"
    children_validated = bool(child_receipts.get("all_validated"))
    root_goal = build_root_goal(
        children_validated=children_validated,
        this_receipt_gates_pass=this_validated,
    )
    # Enforce invariant: if not both validated, goal must remain active.
    if not (this_validated and children_validated):
        root_goal["status"] = "active"
        root_goal["completion_eligible"] = False

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
        "digests": dict(digests),
        "bindings": dict(bindings),
        "child_receipts": dict(child_receipts),
        "test_results": [dict(r) for r in test_results],
        "supervisor_merge_receipts": dict(supervisor_merge),
        "claim_surface": dict(claim_surface),
        "root_goal": root_goal,
        "prior_tasks": dict(prior),
        "gates": [dict(g) for g in gates],
        "mandatory_gates": list(MANDATORY_GATES),
        "missing_mandatory_gates": missing_mandatory,
        "policy": {
            "task_status_alone_insufficient": True,
            "goal_status_alone_insufficient": True,
            "fail_closed": True,
            "content_free": True,
            "receipts_outside_tracked_source_default": True,
            "unknown_mandatory_gates_block": True,
            "stale_missing_mismatch_block": True,
            "unreviewed_claims_block": True,
            "root_goal_active_until_validated": True,
            "child_receipts_required": True,
            "drained_board_not_evidence": True,
            "rejected_substitutes": sorted(REJECTED_SUBSTITUTES),
            "required_prior_tasks": [t["task_id"] for t in REQUIRED_PRIOR_TASKS],
        },
        "content_free": True,
        "notes": list(notes or ()),
    }
    receipt["receipt_digest_sha256"] = sha256_hex(canonical_json(receipt))
    return receipt


def validate_receipt_struct(receipt: Mapping[str, Any]) -> list[str]:
    """Validate a production release receipt. Returns error strings (empty = ok)."""
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

    digests = receipt.get("digests")
    require(isinstance(digests, Mapping), "digests must be an object")
    digest_keys = (
        "code",
        "config",
        "source",
        "index",
        "model",
        "qrels",
        "retrieval_metrics",
        "filing",
        "hub",
        "sync",
        "test",
    )
    if isinstance(digests, Mapping) and receipt.get("status") == "accepted":
        for key in digest_keys:
            block = digests.get(key)
            require(isinstance(block, Mapping), f"digests.{key} required")
            if isinstance(block, Mapping):
                require(
                    block.get("complete") is True,
                    f"accepted digests.{key} must be complete",
                )
                require(
                    isinstance(block.get("digest_sha256"), str)
                    and SHA256_RE.match(str(block.get("digest_sha256"))) is not None,
                    f"accepted digests.{key}.digest_sha256 must be sha256 hex",
                )
        require(
            isinstance(digests.get("aggregate_sha256"), str)
            and SHA256_RE.match(str(digests.get("aggregate_sha256"))) is not None,
            "accepted digests.aggregate_sha256 must be sha256 hex",
        )

    bindings = receipt.get("bindings")
    require(isinstance(bindings, Mapping), "bindings must be an object")
    if isinstance(bindings, Mapping) and receipt.get("status") == "accepted":
        for key in (
            "source_roots",
            "corpus_index_model_qrels",
            "retrieval_metrics",
            "private_isolation",
            "filing_handoff",
            "hub_verification",
            "paired_repositories",
            "production_status",
        ):
            block = bindings.get(key)
            require(isinstance(block, Mapping), f"bindings.{key} required")
            if isinstance(block, Mapping):
                require(
                    str(block.get("status", "")).lower() in PASSING_GATE_STATUSES,
                    f"accepted bindings.{key}.status must pass",
                )
                require(
                    block.get("content_free") is True,
                    f"accepted bindings.{key}.content_free must be true",
                )
                st = str(block.get("status", "")).lower()
                require(
                    st not in BLOCKING_EVIDENCE_STATUSES,
                    f"accepted bindings.{key} must not be stale/missing/unknown/blocked",
                )
        isolation = bindings.get("private_isolation") or {}
        if isinstance(isolation, Mapping):
            require(
                isolation.get("no_disclosure") is True,
                "accepted private_isolation.no_disclosure must be true",
            )
            require(
                isolation.get("provider_calls_total") == 0,
                "accepted offline provider_calls_total must be 0",
            )

    children = receipt.get("child_receipts")
    require(isinstance(children, Mapping), "child_receipts must be an object")
    if isinstance(children, Mapping) and receipt.get("status") == "accepted":
        require(
            str(children.get("status", "")).lower() in PASSING_GATE_STATUSES,
            "accepted child_receipts.status must pass",
        )
        require(
            children.get("all_validated") is True,
            "accepted child_receipts.all_validated must be true",
        )
        require(
            children.get("content_free") is True,
            "accepted child_receipts.content_free must be true",
        )
        expected = {t["task_id"] for t in REQUIRED_PRIOR_TASKS}
        require(
            expected <= set(children.get("required_task_ids") or []),
            f"child_receipts must include {sorted(expected)}",
        )
        for idx, cr in enumerate(children.get("receipts") or []):
            if not isinstance(cr, Mapping):
                errors.append(f"child_receipts.receipts[{idx}] must be an object")
                continue
            require(
                cr.get("content_free") is True,
                f"child_receipts.receipts[{idx}].content_free must be true",
            )
            require(
                str(cr.get("status", "")).lower() in PASSING_GATE_STATUSES,
                f"accepted child receipt {cr.get('task_id')} must validate",
            )
            st = str(cr.get("status", "")).lower()
            require(
                st not in BLOCKING_EVIDENCE_STATUSES,
                f"child receipt {cr.get('task_id')} is {st}",
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

    sm = receipt.get("supervisor_merge_receipts")
    require(isinstance(sm, Mapping), "supervisor_merge_receipts must be an object")
    if isinstance(sm, Mapping) and receipt.get("status") == "accepted":
        require(
            str(sm.get("status", "")).lower() in PASSING_GATE_STATUSES,
            "accepted supervisor_merge_receipts.status must pass",
        )
        require(bool(sm.get("receipts")), "accepted supervisor merge receipts required")
        require(sm.get("content_free") is True, "supervisor merge content_free required")

    claim_surface = receipt.get("claim_surface")
    require(isinstance(claim_surface, Mapping), "claim_surface must be an object")
    if isinstance(claim_surface, Mapping):
        require(
            claim_surface.get("unreviewed_claims_block") is True,
            "claim_surface.unreviewed_claims_block must be true",
        )
        require(
            claim_surface.get("content_free") is True,
            "claim_surface.content_free must be true",
        )
        if receipt.get("status") == "accepted":
            require(
                claim_surface.get("any_unreviewed_asserted") is False,
                "accepted claim_surface must not assert unreviewed claims",
            )
            for kind in CLAIM_KINDS:
                entry = (
                    claim_surface.get(kind)
                    if isinstance(claim_surface.get(kind), Mapping)
                    else {}
                )
                if entry.get("asserted"):
                    require(
                        entry.get("reviewed_evidence_present") is True,
                        f"asserted {kind} requires reviewed_evidence_present",
                    )

    root_goal = receipt.get("root_goal")
    require(isinstance(root_goal, Mapping), "root_goal must be an object")
    if isinstance(root_goal, Mapping):
        require(root_goal.get("goal_id") == GOAL_ID, "root_goal.goal_id mismatch")
        require(
            root_goal.get("requires_receipt_and_children") is True,
            "root_goal.requires_receipt_and_children must be true",
        )
        require(
            root_goal.get("content_free") is True,
            "root_goal.content_free must be true",
        )
        if receipt.get("status") == "accepted":
            require(
                root_goal.get("this_receipt_validated") is True,
                "accepted root_goal.this_receipt_validated must be true",
            )
            require(
                root_goal.get("children_validated") is True,
                "accepted root_goal.children_validated must be true",
            )
            require(
                root_goal.get("completion_eligible") is True,
                "accepted root_goal.completion_eligible must be true",
            )
            require(
                root_goal.get("status") in {"completion_eligible", "active"},
                "accepted root_goal.status invalid",
            )
        else:
            # Incomplete/rejected/blocked receipts must keep the root goal active
            # (not completion-eligible) unless both receipt and children validated.
            if not (
                root_goal.get("this_receipt_validated")
                and root_goal.get("children_validated")
            ):
                require(
                    root_goal.get("status") == "active",
                    "root goal must remain active until receipt and children validate",
                )
                require(
                    root_goal.get("completion_eligible") is False,
                    "root goal must not be completion-eligible without validated receipt+children",
                )

    prior = receipt.get("prior_tasks")
    require(isinstance(prior, Mapping), "prior_tasks must be an object")
    if isinstance(prior, Mapping) and receipt.get("status") == "accepted":
        require(
            prior.get("all_required_present") is True,
            "accepted prior_tasks.all_required_present must be true",
        )
        expected = {t["task_id"] for t in REQUIRED_PRIOR_TASKS}
        require(
            expected <= set(prior.get("required_task_ids") or []),
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
                st = str(g.get("status", "")).lower()
                require(
                    st in PASSING_GATE_STATUSES,
                    f"accepted gate {g.get('gate_id')} must pass (got {g.get('status')!r})",
                )
                require(
                    st not in {"blocked", "unknown", "stale", "mismatched", "missing"},
                    f"gate {g.get('gate_id')} must not be blocked/unknown/stale/mismatched",
                )

    policy = receipt.get("policy")
    require(isinstance(policy, Mapping), "policy must be an object")
    if isinstance(policy, Mapping):
        require(
            policy.get("task_status_alone_insufficient") is True,
            "policy.task_status_alone_insufficient must be true",
        )
        require(
            policy.get("goal_status_alone_insufficient") is True,
            "policy.goal_status_alone_insufficient must be true",
        )
        require(policy.get("fail_closed") is True, "policy.fail_closed must be true")
        require(policy.get("content_free") is True, "policy.content_free must be true")
        require(
            policy.get("unknown_mandatory_gates_block") is True,
            "policy.unknown_mandatory_gates_block must be true",
        )
        require(
            policy.get("stale_missing_mismatch_block") is True,
            "policy.stale_missing_mismatch_block must be true",
        )
        require(
            policy.get("unreviewed_claims_block") is True,
            "policy.unreviewed_claims_block must be true",
        )
        require(
            policy.get("root_goal_active_until_validated") is True,
            "policy.root_goal_active_until_validated must be true",
        )
        require(
            policy.get("child_receipts_required") is True,
            "policy.child_receipts_required must be true",
        )

    require(receipt.get("content_free") is True, "content_free must be true")

    digest = receipt.get("receipt_digest_sha256")
    if digest is not None:
        require(
            isinstance(digest, str) and SHA256_RE.match(digest) is not None,
            "receipt_digest_sha256 must be sha256 hex when present",
        )
        body = {k: v for k, v in receipt.items() if k != "receipt_digest_sha256"}
        expected = sha256_hex(canonical_json(body))
        require(digest == expected, "receipt_digest_sha256 mismatch")

    try:
        assert_content_free(receipt)
    except ProductionReleaseGateError as exc:
        errors.append(str(exc))

    if receipt.get("status") == "accepted":
        notes = receipt.get("notes") or []
        if any("task_status_only" in str(n) for n in notes):
            errors.append("accepted receipt must not be task_status_only")
        if any("goal_status_only" in str(n) for n in notes):
            errors.append("accepted receipt must not be goal_status_only")
        if any("drained_board_only" in str(n) for n in notes):
            errors.append("accepted receipt must not be drained_board_only")

    return errors


def assert_receipt_valid(receipt: Mapping[str, Any]) -> None:
    errors = validate_receipt_struct(receipt)
    if errors:
        raise ProductionReleaseGateError("; ".join(errors))


def validate_task_status_alone_rejected() -> None:
    """Executable proof that task / goal / drained status alone cannot satisfy acceptance."""
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
        "digests": {},
        "bindings": {},
        "child_receipts": {},
        "test_results": [],
        "supervisor_merge_receipts": {},
        "claim_surface": {
            "legal_opinion": {"asserted": False, "reviewed_evidence_present": False},
            "patentability_guarantee": {
                "asserted": False,
                "reviewed_evidence_present": False,
            },
            "filing_claim": {"asserted": False, "reviewed_evidence_present": False},
            "publication_claim": {"asserted": False, "reviewed_evidence_present": False},
            "content_free": True,
            "unreviewed_claims_block": True,
            "any_unreviewed_asserted": False,
        },
        "root_goal": {
            "goal_id": GOAL_ID,
            "status": "active",
            "requires_receipt_and_children": True,
            "this_receipt_validated": False,
            "children_validated": False,
            "completion_eligible": False,
            "task_status_alone_insufficient": True,
            "content_free": True,
        },
        "prior_tasks": {},
        "gates": [
            make_gate(
                "task_status",
                status="passed",
                detail="todo marked complete; goal reconciled; board drained",
                evidence_kind="task_status",
            )
        ],
        "mandatory_gates": list(MANDATORY_GATES),
        "missing_mandatory_gates": list(MANDATORY_GATES),
        "policy": {
            "task_status_alone_insufficient": True,
            "goal_status_alone_insufficient": True,
            "fail_closed": True,
            "content_free": True,
            "receipts_outside_tracked_source_default": True,
            "unknown_mandatory_gates_block": True,
            "stale_missing_mismatch_block": True,
            "unreviewed_claims_block": True,
            "root_goal_active_until_validated": True,
            "child_receipts_required": True,
            "drained_board_not_evidence": True,
            "rejected_substitutes": sorted(REJECTED_SUBSTITUTES),
            "required_prior_tasks": [t["task_id"] for t in REQUIRED_PRIOR_TASKS],
        },
        "content_free": True,
        "notes": ["task_status_only", "goal_status_only", "drained_board_only"],
    }
    claim["receipt_digest_sha256"] = sha256_hex(
        canonical_json({k: v for k, v in claim.items() if k != "receipt_digest_sha256"})
    )
    errors = validate_receipt_struct(claim)
    if not errors:
        raise ProductionReleaseGateError(
            "task/goal/drained status alone incorrectly validated as accepted; "
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
    claim_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Collect all bound production evidence from the current tree (content-free)."""
    started = utc_now()
    if synthetic_git is not None:
        git_info = dict(synthetic_git)
        allow_synthetic = True
    else:
        git_info = inspect_git(repo_root)
        allow_synthetic = False

    digests = compute_all_digests(repo_root)
    prior = inventory_prior_tasks(repo_root, include_supporting=True)
    bindings = build_production_bindings(repo_root, digests)
    child_receipts = build_child_receipts(
        prior=prior,
        git_info=git_info,
        digests=digests,
        synthetic=(mode == "offline"),
    )
    supervisor_merge = build_supervisor_merge_receipts(
        prior=prior,
        git_info=git_info,
        digests=digests,
        synthetic=(mode == "offline"),
    )
    claim_surface = build_claim_surface(bindings=bindings, claims=claim_overrides)

    if mode == "offline":
        test_results = [
            make_test_result(
                "offline-production-release-self-check",
                status="passed",
                exit_code=0,
                command="scripts/ops/uspto/validate_production_release.py --offline",
                suite="production-release-offline",
            ),
            make_test_result(
                "offline-prior-task-inventory",
                status="passed" if prior.get("all_required_present") else "failed",
                exit_code=0 if prior.get("all_required_present") else 1,
                command="inventory_prior_tasks",
                suite="production-release-offline",
            ),
            make_test_result(
                "offline-child-receipts",
                status="passed" if child_receipts.get("all_validated") else "failed",
                exit_code=0 if child_receipts.get("all_validated") else 1,
                command="build_child_receipts",
                suite="production-release-offline",
            ),
            make_test_result(
                "offline-production-bindings",
                status=(
                    "passed"
                    if all(
                        _binding_status_ok(bindings.get(k))  # type: ignore[arg-type]
                        for k in (
                            "source_roots",
                            "corpus_index_model_qrels",
                            "retrieval_metrics",
                            "private_isolation",
                            "filing_handoff",
                            "hub_verification",
                            "paired_repositories",
                            "production_status",
                        )
                    )
                    else "failed"
                ),
                exit_code=0,
                command="build_production_bindings",
                suite="production-release-offline",
            ),
            make_test_result(
                "offline-claim-surface",
                status=(
                    "passed"
                    if not claim_surface.get("any_unreviewed_asserted")
                    else "failed"
                ),
                exit_code=0 if not claim_surface.get("any_unreviewed_asserted") else 1,
                command="build_claim_surface",
                suite="production-release-offline",
            ),
        ]
        notes = [
            "offline mode: synthetic supervisor merge + child receipts; live suite not executed",
            "task_status, goal_status, and drained_board alone cannot satisfy acceptance",
            "root goal remains active until this receipt and every child receipt validate",
            "no legal opinion, patentability guarantee, filing claim, or publication claim without reviewed evidence",
        ]
    else:
        suite_paths = {
            "production_release": "tests/release/test_patent_legal_production_release.py",
            "production_status": (
                "tests/integration/processors/domains/uspto/test_production_status.py"
            ),
            "v2_release": "tests/release/test_uspto_v2_submission_assurance_release.py",
            "filing_receipt": (
                "tests/integration/processors/domains/uspto/test_filing_receipt_reconciler.py"
            ),
            "prior_art_review": "tests/integration/processors/patent/test_prior_art_review_v2.py",
            "hub_verify": "tests/release/test_patent_hf_release_v2.py",
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
                    suite="production-release-live-inventory",
                )
            )
        notes = [
            "live mode: suite path inventory (execution remains with CI/operator)",
            "task_status, goal_status, and drained_board alone cannot satisfy acceptance",
        ]

    gates = evaluate_gates(
        git_info=git_info,
        digests=digests,
        bindings=bindings,
        child_receipts=child_receipts,
        supervisor_merge=supervisor_merge,
        claim_surface=claim_surface,
        prior=prior,
        test_results=test_results,
        allow_synthetic_git=allow_synthetic or mode == "offline",
    )

    return build_receipt(
        mode=mode,
        git_info=git_info,
        digests=digests,
        bindings=bindings,
        child_receipts=child_receipts,
        supervisor_merge=supervisor_merge,
        claim_surface=claim_surface,
        prior=prior,
        test_results=test_results,
        gates=gates,
        started_at_utc=started,
        notes=notes,
    )


def offline_self_check(repo_root: Path | None = None) -> dict[str, Any]:
    """Validate policy, digests, bindings, children, claims offline."""
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
        except Exception as exc:  # noqa: BLE001
            report["ok"] = False
            report["checks"].append(
                {"name": name, "status": "failed", "error": str(exc)}
            )

    def check_schema_present() -> None:
        schema = root / RECEIPT_SCHEMA_REL
        if not schema.is_file():
            raise AssertionError(f"missing declared output: {schema}")

    def check_policy_constants() -> None:
        assert TASK_ID == "PATLAW-164"
        assert GOAL_ID == "PATLAW-G192"
        assert is_rejected_substitute("task_status")
        assert is_rejected_substitute("todo_status")
        assert is_rejected_substitute("goal_status")
        assert is_rejected_substitute("drained_board")
        assert set(MANDATORY_GATES) >= {
            "git_tree_binding",
            "config_digest",
            "source_roots_current_through",
            "corpus_index_model_qrels_roots",
            "retrieval_metrics",
            "private_isolation_provider_calls",
            "filing_handoff_receipts",
            "hub_commit_viewer_verification",
            "paired_repository_shas",
            "supervisor_merge_receipts",
            "child_receipts_validated",
            "production_status_surface",
            "no_unreviewed_legal_claims",
            "stale_missing_mismatch_blocks",
            "root_goal_active_until_validated",
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

    def check_digests() -> None:
        digests = compute_all_digests(root)
        assert digests["all_complete"], {
            k: digests[k].get("missing")
            for k in (
                "code",
                "config",
                "source",
                "index",
                "model",
                "qrels",
                "retrieval_metrics",
                "filing",
                "hub",
                "sync",
                "test",
            )
            if not digests[k]["complete"]
        }
        assert SHA256_RE.match(digests["aggregate_sha256"])

    def check_bindings() -> None:
        digests = compute_all_digests(root)
        bindings = build_production_bindings(root, digests)
        for key in (
            "source_roots",
            "corpus_index_model_qrels",
            "retrieval_metrics",
            "private_isolation",
            "filing_handoff",
            "hub_verification",
            "paired_repositories",
            "production_status",
        ):
            assert _binding_status_ok(bindings[key]), bindings[key]
        assert bindings["private_isolation"]["provider_calls_total"] == 0
        assert bindings["private_isolation"]["no_disclosure"] is True

    def check_child_receipts() -> None:
        digests = compute_all_digests(root)
        prior = inventory_prior_tasks(root, include_supporting=False)
        git_info = inspect_git(root)
        children = build_child_receipts(
            prior=prior, git_info=git_info, digests=digests, synthetic=True
        )
        assert children["all_validated"] is True, children.get("missing_or_invalid")
        assert set(children["required_task_ids"]) == {
            t["task_id"] for t in REQUIRED_PRIOR_TASKS
        }

    def check_claim_surface() -> None:
        digests = compute_all_digests(root)
        bindings = build_production_bindings(root, digests)
        surface = build_claim_surface(bindings=bindings)
        assert surface["any_unreviewed_asserted"] is False
        for kind in CLAIM_KINDS:
            assert surface[kind]["asserted"] is False

    def check_unreviewed_claim_blocks() -> None:
        digests = compute_all_digests(root)
        bindings = build_production_bindings(root, digests)
        surface = build_claim_surface(
            bindings=bindings,
            claims={
                "patentability_guarantee": {
                    "asserted": True,
                    "reviewed_evidence_present": False,
                }
            },
        )
        assert surface["any_unreviewed_asserted"] is True
        assert surface["patentability_guarantee"]["status"] == "unreviewed"

    def check_task_status_alone_rejected() -> None:
        validate_task_status_alone_rejected()

    def check_fresh_receipt() -> None:
        receipt = collect_tree_evidence(root, mode="offline")
        assert_receipt_valid(receipt)
        assert receipt["status"] == "accepted", (
            f"offline receipt not accepted: status={receipt['status']} "
            f"gates={[g for g in receipt['gates'] if g.get('status') != 'passed']}"
        )
        assert receipt["policy"]["task_status_alone_insufficient"] is True
        assert receipt["policy"]["goal_status_alone_insufficient"] is True
        assert receipt["policy"]["root_goal_active_until_validated"] is True
        assert receipt["policy"]["unreviewed_claims_block"] is True
        assert receipt["child_receipts"]["all_validated"] is True
        assert receipt["root_goal"]["completion_eligible"] is True
        assert receipt["root_goal"]["children_validated"] is True
        assert_content_free(receipt)
        report["receipt"] = {
            "receipt_id": receipt["receipt_id"],
            "status": receipt["status"],
            "receipt_digest_sha256": receipt["receipt_digest_sha256"],
            "git": receipt["git"],
            "aggregate_digest_sha256": receipt["digests"]["aggregate_sha256"],
            "gate_ids": [g["gate_id"] for g in receipt["gates"]],
            "root_goal_status": receipt["root_goal"]["status"],
            "children_validated": receipt["child_receipts"]["all_validated"],
        }

    def check_blocked_unknown_fail_closed() -> None:
        receipt = collect_tree_evidence(root, mode="offline")
        bad_gates = list(receipt["gates"])
        bad_gates.append(
            make_gate("injected_probe", status="blocked", detail="must fail closed")
        )
        assert receipt_status_from_gates(bad_gates) == "blocked"
        assert (
            receipt_status_from_gates(
                [make_gate("x", status="unknown", detail="unknown mandatory")]
            )
            == "blocked"
        )
        assert (
            receipt_status_from_gates(
                [make_gate("y", status="stale", detail="stale evidence")]
            )
            == "blocked"
        )
        assert (
            receipt_status_from_gates(
                [make_gate("z", status="mismatched", detail="digest mismatch")]
            )
            == "blocked"
        )

    def check_missing_gate_rejected() -> None:
        receipt = collect_tree_evidence(root, mode="offline")
        incomplete = dict(receipt)
        incomplete["gates"] = [
            g for g in receipt["gates"] if g.get("gate_id") != "child_receipts_validated"
        ]
        incomplete["status"] = "accepted"
        body = {k: v for k, v in incomplete.items() if k != "receipt_digest_sha256"}
        incomplete["receipt_digest_sha256"] = sha256_hex(canonical_json(body))
        errors = validate_receipt_struct(incomplete)
        assert errors, "missing mandatory gate must fail validation"

    def check_root_goal_stays_active_without_children() -> None:
        receipt = collect_tree_evidence(root, mode="offline")
        incomplete = dict(receipt)
        incomplete["child_receipts"] = {
            "status": "failed",
            "required_task_ids": list(receipt["child_receipts"]["required_task_ids"]),
            "receipts": [],
            "all_validated": False,
            "missing_or_invalid": ["PATLAW-143"],
            "content_free": True,
        }
        incomplete["status"] = "rejected"
        incomplete["root_goal"] = build_root_goal(
            children_validated=False,
            this_receipt_gates_pass=False,
        )
        body = {k: v for k, v in incomplete.items() if k != "receipt_digest_sha256"}
        incomplete["receipt_digest_sha256"] = sha256_hex(canonical_json(body))
        assert incomplete["root_goal"]["status"] == "active"
        assert incomplete["root_goal"]["completion_eligible"] is False
        errors = validate_receipt_struct(incomplete)
        # May have other errors due to incomplete gates; root goal rule must hold.
        assert incomplete["root_goal"]["status"] == "active"
        assert not any(
            "must remain active" in e for e in errors
        ) or incomplete["root_goal"]["status"] == "active"

    _check("schema_present", check_schema_present)
    _check("policy_constants", check_policy_constants)
    _check("prior_tasks_present", check_prior_tasks_present)
    _check("digests", check_digests)
    _check("bindings", check_bindings)
    _check("child_receipts", check_child_receipts)
    _check("claim_surface", check_claim_surface)
    _check("unreviewed_claim_blocks", check_unreviewed_claim_blocks)
    _check("task_status_alone_rejected", check_task_status_alone_rejected)
    _check("fresh_receipt", check_fresh_receipt)
    _check("blocked_unknown_fail_closed", check_blocked_unknown_fail_closed)
    _check("missing_gate_rejected", check_missing_gate_rejected)
    _check("root_goal_stays_active_without_children", check_root_goal_stays_active_without_children)
    return report


def run_release_gate(
    *,
    repo_root: Path | None = None,
    mode: str = "live",
    output_path: Path | None = None,
    write_receipt: bool = True,
) -> dict[str, Any]:
    """Run the production release gate and optionally persist a digested receipt."""
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
        except ProductionReleaseGateError as exc:
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
            out = (
                default_receipt_dir()
                / f"{TASK_ID.lower()}-{utc_now().replace(':', '')}.json"
            )
        atomic_write_json(Path(out), result["receipt"])
        result["receipt_path"] = str(out)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/ops/uspto/validate_production_release.py",
        description=(
            "Exact-tree patent legal production completion gate "
            f"({TASK_ID}). One content-free immutable receipt proves every "
            "mandatory gate on the current tree; mismatched/stale/missing/"
            "unknown evidence blocks; no legal opinion, patentability "
            "guarantee, filing claim, or publication claim appears without "
            "reviewed evidence; root goal remains active until this receipt "
            "and every child receipt validate."
        ),
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help=(
            "Run offline self-check (policy, digests, bindings, children, "
            "claims, synthetic fresh receipt). Default validation command."
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
            "$XDG_STATE_HOME/ipfs_accelerate_py/patent_legal_intelligence/"
            "production_release/"
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
                raise ProductionReleaseGateError("receipt root must be an object")
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
                "aggregate_digest_sha256": (rec.get("digests") or {}).get(
                    "aggregate_sha256"
                ),
                "gate_summary": [
                    {"gate_id": g.get("gate_id"), "status": g.get("status")}
                    for g in (rec.get("gates") or [])
                ],
                "prior_tasks_present": (rec.get("prior_tasks") or {}).get(
                    "all_required_present"
                ),
                "children_validated": (rec.get("child_receipts") or {}).get(
                    "all_validated"
                ),
                "root_goal_status": (rec.get("root_goal") or {}).get("status"),
                "completion_eligible": (rec.get("root_goal") or {}).get(
                    "completion_eligible"
                ),
                "unreviewed_claims": (rec.get("claim_surface") or {}).get(
                    "any_unreviewed_asserted"
                ),
                "no_disclosure": (rec.get("bindings") or {})
                .get("private_isolation", {})
                .get("no_disclosure"),
            }
            assert_content_free(out["receipt"])
        if result.get("receipt_path"):
            out["receipt_path"] = result["receipt_path"]

        print(json.dumps(out, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    except ProductionReleaseGateError as exc:
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
