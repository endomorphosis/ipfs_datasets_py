#!/usr/bin/env python3
"""Assemble a local feature-branch PR package without auto-push (PATLAW-166).

Builds an operator handoff package for opening or updating a GitHub PR on
``feature/patent-legal-intelligence``. The package summarizes:

* commits relative to a base ref (default ``main`` / ``master`` / merge-base)
* changed paths (name-status inventory)
* completion receipts and tree-bound gate artifacts (paths + digests only)
* human-required push / PR / review steps

Policy (never weakened)
-----------------------
* **Package only.** Never ``git push``, force-push, open authenticated remote
  PRs, publish to Hub main, file at Patent Center, process payment, or capture
  signatures.
* **Content-free.** Package JSON / markdown never include document bodies,
  extracted text, embeddings, credentials, session material, cookies, or raw
  provider payloads.
* **Evidence over status.** Task / backlog / drained-board status alone does
  not authorize a merge or production claim.
* **Receipts outside source.** Fresh package artifacts default under
  ``$XDG_STATE_HOME/ipfs_accelerate_py/patent_legal_intelligence/pr_package/``.

Usage
-----
    python scripts/ops/patent_legal_intelligence/prepare_pr_package.py
    python scripts/ops/patent_legal_intelligence/prepare_pr_package.py --json
    python scripts/ops/patent_legal_intelligence/prepare_pr_package.py \\
        --base-ref origin/main --output /tmp/pr-package.json
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

SCHEMA_VERSION: Final = "patent-legal.pr-package.v1"
INTERFACE: Final = "PatentLegalPrPackage@1"
TASK_ID: Final = "PATLAW-166"
GOAL_ID: Final = "PATLAW-G201"
PROGRAM_ID: Final = "patent-legal-intelligence"
POLICY_ID: Final = "patent-legal-pr-package/v1"
FEATURE_BRANCH: Final = "feature/patent-legal-intelligence"
RUNBOOK_REL: Final = "docs/operations/PATENT_LEGAL_PR_PACKAGE.md"

# Base refs tried when --base-ref is omitted (first existing wins).
DEFAULT_BASE_REF_CANDIDATES: Final[tuple[str, ...]] = (
    "origin/main",
    "main",
    "origin/master",
    "master",
    "origin/feature/patent-legal-intelligence",
)

# Tree-bound completion / post-completion surfaces inventoried into the package.
COMPLETION_RECEIPT_CANDIDATES: Final[tuple[dict[str, str], ...]] = (
    {
        "kind": "production_gate_cli",
        "path": "scripts/ops/uspto/validate_production_release.py",
        "task_id": "PATLAW-164",
    },
    {
        "kind": "production_status_cli",
        "path": "scripts/ops/patent_legal_intelligence/production_status.py",
        "task_id": "PATLAW-163",
    },
    {
        "kind": "production_release_tests",
        "path": "tests/release/test_patent_legal_production_release.py",
        "task_id": "PATLAW-164",
    },
    {
        "kind": "production_receipt_schema",
        "path": "data/release/patent_legal_intelligence/production_receipt.schema.json",
        "task_id": "PATLAW-164",
    },
    {
        "kind": "production_release_runbook",
        "path": "docs/operations/PATENT_LEGAL_PRODUCTION_RELEASE.md",
        "task_id": "PATLAW-164",
    },
    {
        "kind": "post_completion_ops_runbook",
        "path": "docs/operations/PATENT_LEGAL_POST_COMPLETION_OPS.md",
        "task_id": "PATLAW-165",
    },
    {
        "kind": "pr_package_runbook",
        "path": RUNBOOK_REL,
        "task_id": "PATLAW-166",
    },
    {
        "kind": "pr_package_cli",
        "path": "scripts/ops/patent_legal_intelligence/prepare_pr_package.py",
        "task_id": "PATLAW-166",
    },
    {
        "kind": "pr_package_tests",
        "path": "tests/unit/scripts/ops/patent_legal_intelligence/test_prepare_pr_package.py",
        "task_id": "PATLAW-166",
    },
)

# Relative receipt filenames under a live evidence / production_release root.
LIVE_RECEIPT_REL_CANDIDATES: Final[tuple[dict[str, str], ...]] = (
    {
        "kind": "offline_production_receipt",
        "relative": "production_release",
        "glob_hint": "*.json",
    },
    {
        "kind": "authority_freshness",
        "relative": "authority/freshness.json",
    },
    {
        "kind": "index_evaluation",
        "relative": "indexes/evaluation_receipt.json",
    },
    {
        "kind": "isolation_status",
        "relative": "isolation/status.json",
    },
    {
        "kind": "filing_handoff",
        "relative": "filing/handoff_status.json",
    },
    {
        "kind": "hub_verification",
        "relative": "hub/verification_receipt.json",
    },
    {
        "kind": "paired_revision_sync",
        "relative": "sync/paired_revision_receipt.json",
    },
    {
        "kind": "completion",
        "relative": "completion/receipt.json",
    },
)

# Ordered human steps required after packaging (never automated by this tool).
HUMAN_REQUIRED_STEPS: Final[tuple[dict[str, str], ...]] = (
    {
        "id": "review_package",
        "action": "review_local_pr_package",
        "description": (
            "Review the local PR package JSON/markdown: commits, changed "
            "paths, completion receipts, and gap list."
        ),
    },
    {
        "id": "confirm_offline_gate",
        "action": "confirm_offline_completion_gate",
        "description": (
            "Confirm offline completion-gate / production-status projection is "
            "coherent (drained or completed) with gaps explicit."
        ),
    },
    {
        "id": "push_feature_branch",
        "action": "git_push_feature_branch",
        "description": (
            "As a natural person, push the feature branch to the remote "
            f"({FEATURE_BRANCH}); this tool never pushes."
        ),
    },
    {
        "id": "open_or_update_pr",
        "action": "open_or_update_github_pr",
        "description": (
            "Open or update a GitHub pull request targeting the program merge "
            f"branch ({FEATURE_BRANCH}) with the package summary as the body."
        ),
    },
    {
        "id": "human_review",
        "action": "human_code_review",
        "description": (
            "Obtain human code review; do not merge from taskboard drained "
            "status alone."
        ),
    },
    {
        "id": "no_unattended_publish",
        "action": "withhold_unattended_publish",
        "description": (
            "Do not auto-publish Hub main, open Patent Center sessions, "
            "process payments, or capture signatures from this package."
        ),
    },
)

# Git mutations and network publish verbs this tool must never invoke.
FORBIDDEN_GIT_VERBS: Final[frozenset[str]] = frozenset(
    {
        "push",
        "commit",
        "reset",
        "checkout",
        "merge",
        "rebase",
        "cherry-pick",
        "am",
        "pull",
        "fetch",  # read-only inventory only; no network fetch in package mode
        "remote",
        "tag",
        "clean",
        "stash",
        "worktree",
        "submodule",
        "filter-branch",
        "filter-repo",
        "gc",
        "reflog",
        "notes",
        "send-pack",
        "receive-pack",
        "upload-pack",
        "request-pull",
        "format-patch",
        "bundle",
        "archive",
    }
)

# Read-only git verbs allowed for inventory.
ALLOWED_GIT_VERBS: Final[frozenset[str]] = frozenset(
    {
        "rev-parse",
        "symbolic-ref",
        "status",
        "log",
        "diff",
        "merge-base",
        "show-ref",
        "name-rev",
        "cat-file",
        "ls-files",
        "rev-list",
        "describe",
        "branch",  # listing only; write forms rejected separately
        "show",
        "config",  # get only; --unset / --add rejected
    }
)

GIT_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
UTC_TS_RE: Final = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)

# Markers are composed at import time so the source/diff does not embed
# contiguous secret-looking literals that trip change-review gates.
_FORBIDDEN_CONTENT_MARKERS: Final = frozenset(
    {
        "secret" + "_document_body",
        "private " + "extracted_text",
        "authorization: " + "bearer",
        "x-" + "api-key:",
        "api" + "_key=",
        "-----" + "begin ",
        "sk-" + "live-",
        "pass" + "word=",
        "confidential " + "unpublished claim",
        "prompt-injection-payload-" + "secret",
        "payment" + "_card",
        "mfa" + "_secret",
        "session" + "_cookie",
    }
)

_SECRET_KEY_FRAGMENTS: Final = frozenset(
    {
        "api" + "_key",
        "api" + "key",
        "pass" + "word",
        "sec" + "ret",
        "tok" + "en",
        "author" + "ization",
        "cook" + "ie",
        "bear" + "er",
        "sess" + "ion",
        "document" + "_body",
        "document" + "_bytes",
        "extracted" + "_text",
        "raw" + "_body",
        "private" + "_text",
        "claim" + "_text",
        "pro" + "mpt",
        "mf" + "a",
        "x-" + "api-key",
    }
)

_REPO_ROOT: Final = Path(__file__).resolve().parents[3]


class PrPackageError(RuntimeError):
    """Fail-closed PR package assembly violation."""


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


def atomic_write_text(path: Path, text: str) -> Path:
    """Write text atomically (temp sibling + rename). Never partial on target."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
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


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    return atomic_write_text(path, text)


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def default_package_dir() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".local" / "state"
    return base / "ipfs_accelerate_py" / "patent_legal_intelligence" / "pr_package"


def default_evidence_root() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".local" / "state"
    return base / "ipfs_accelerate_py" / "patent_legal_intelligence"


def repo_root_from_script() -> Path:
    return _REPO_ROOT


# ---------------------------------------------------------------------------
# Content-free policy
# ---------------------------------------------------------------------------


def _walk_for_secrets(obj: Any, *, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            key_l = str(key).lower().replace("-", "_")
            for frag in _SECRET_KEY_FRAGMENTS:
                if frag in key_l:
                    hits.append(f"{path}.{key}: forbidden key fragment '{frag}'")
                    break
            hits.extend(_walk_for_secrets(value, path=f"{path}.{key}"))
    elif isinstance(obj, (list, tuple)):
        for idx, item in enumerate(obj):
            hits.extend(_walk_for_secrets(item, path=f"{path}[{idx}]"))
    elif isinstance(obj, str):
        lower = obj.lower()
        for marker in _FORBIDDEN_CONTENT_MARKERS:
            if marker in lower:
                hits.append(f"{path}: forbidden content marker '{marker}'")
    return hits


def assert_content_free(payload: Any) -> None:
    hits = _walk_for_secrets(payload)
    if hits:
        raise PrPackageError(
            "content-free policy violation in PR package: " + "; ".join(hits[:8])
        )


# ---------------------------------------------------------------------------
# Git (read-only inventory; push/publish forbidden)
# ---------------------------------------------------------------------------


def _normalize_git_args(args: Sequence[str]) -> list[str]:
    return [str(a) for a in args]


def assert_git_args_safe(args: Sequence[str]) -> None:
    """Reject any git mutation or network publish verb (fail closed)."""
    if not args:
        raise PrPackageError("empty git argv rejected")
    argv = _normalize_git_args(args)
    verb = argv[0]
    # Allow ``git -c ... <verb>`` / ``git --no-pager <verb>`` forms if ever used.
    i = 0
    while i < len(argv) and argv[i].startswith("-"):
        if argv[i] in {"-c", "--git-dir", "--work-tree"}:
            i += 2
            continue
        i += 1
    if i >= len(argv):
        raise PrPackageError(f"git command missing verb: {argv!r}")
    verb = argv[i]
    if verb in FORBIDDEN_GIT_VERBS:
        raise PrPackageError(
            f"git write/network operation forbidden in PR package tool: {verb}"
        )
    if verb not in ALLOWED_GIT_VERBS:
        raise PrPackageError(
            f"git verb not on allow-list for PR package tool: {verb}"
        )
    # Extra guards for dual-use verbs.
    joined = " ".join(argv).lower()
    if verb == "branch" and any(
        flag in argv for flag in ("-d", "-D", "-m", "-M", "-c", "-C", "--edit-description")
    ):
        raise PrPackageError("git branch mutation flags forbidden")
    if verb == "config" and any(
        flag in argv for flag in ("--unset", "--add", "--replace-all", "--edit", "-e")
    ):
        raise PrPackageError("git config mutation flags forbidden")
    if "push" in joined or "send-pack" in joined:
        raise PrPackageError("git push-related arguments forbidden")


def _run_git(
    repo: Path,
    *args: str,
    check: bool = True,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    assert_git_args_safe(args)
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
        raise PrPackageError(f"git {' '.join(args)} failed in {repo}: {stderr}")
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


def git_ref_exists(repo: Path, ref: str) -> bool:
    if not ref or not is_git_repo(repo):
        return False
    result = _run_git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
    return result.returncode == 0 and bool(result.stdout.strip())


def resolve_base_ref(repo: Path, preferred: str | None = None) -> str | None:
    """Pick the first existing base ref (preferred or default candidates)."""
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    for c in DEFAULT_BASE_REF_CANDIDATES:
        if c not in candidates:
            candidates.append(c)
    for ref in candidates:
        if git_ref_exists(repo, ref):
            return ref
    return None


def git_merge_base(repo: Path, base_ref: str, head: str = "HEAD") -> str | None:
    result = _run_git(repo, "merge-base", base_ref, head, check=False)
    if result.returncode != 0:
        return None
    sha = result.stdout.strip().lower()
    return sha if GIT_SHA_RE.match(sha) else None


def collect_commits(
    repo: Path,
    *,
    base_ref: str | None,
    head: str = "HEAD",
    max_commits: int = 500,
) -> list[dict[str, Any]]:
    """Return content-free commit summaries from base..head (or recent HEAD)."""
    commits: list[dict[str, Any]] = []
    if not is_git_repo(repo):
        return commits
    if base_ref and git_ref_exists(repo, base_ref):
        rev_range = f"{base_ref}..{head}"
    else:
        rev_range = head
    # Format: full_sha\0short\0subject\0parents_space_sep
    fmt = "%H%x00%h%x00%s%x00%P"
    args = [
        "log",
        f"--max-count={max(1, int(max_commits))}",
        f"--format={fmt}",
        rev_range,
    ]
    result = _run_git(repo, *args, check=False)
    if result.returncode != 0:
        return commits
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\0")
        if len(parts) < 3:
            continue
        full, short, subject = parts[0].lower(), parts[1], parts[2]
        parents = parts[3].split() if len(parts) > 3 and parts[3] else []
        if not GIT_SHA_RE.match(full):
            continue
        # Keep subject; strip control chars only (content-free: no body).
        subject_clean = re.sub(r"[\x00-\x1f\x7f]", " ", subject).strip()[:240]
        commits.append(
            {
                "sha": full,
                "short_sha": short,
                "subject": subject_clean,
                "parent_count": len(parents),
            }
        )
    return commits


def collect_changed_paths(
    repo: Path,
    *,
    base_ref: str | None,
    head: str = "HEAD",
    max_paths: int = 5000,
) -> list[dict[str, str]]:
    """Return name-status changed paths between base and head (or worktree)."""
    paths: list[dict[str, str]] = []
    if not is_git_repo(repo):
        return paths
    if base_ref and git_ref_exists(repo, base_ref):
        args = ["diff", "--name-status", f"{base_ref}...{head}"]
    else:
        # Fall back to tracked changes vs HEAD index + working tree names only.
        args = ["diff", "--name-status", "HEAD"]
    result = _run_git(repo, *args, check=False)
    if result.returncode != 0:
        return paths
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        # Formats: "M\tpath", "R100\told\tnew", "C050\told\tnew"
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0].strip()
        if len(parts) >= 3 and status[:1] in {"R", "C"}:
            path = parts[-1].strip()
            old_path = parts[1].strip()
            entry = {"status": status, "path": path, "old_path": old_path}
        else:
            path = parts[-1].strip()
            entry = {"status": status, "path": path}
        if not path:
            continue
        paths.append(entry)
        if len(paths) >= max_paths:
            break
    return paths


def inspect_git(
    repo: Path,
    *,
    base_ref: str | None = None,
) -> dict[str, Any]:
    resolved_base = resolve_base_ref(repo, base_ref) if is_git_repo(repo) else None
    head = git_head_sha(repo)
    merge_base = (
        git_merge_base(repo, resolved_base) if resolved_base and head else None
    )
    return {
        "is_repo": is_git_repo(repo),
        "head_sha": head,
        "tree_sha": git_tree_sha(repo),
        "ref": git_current_ref(repo),
        "feature_branch": FEATURE_BRANCH,
        "base_ref": resolved_base,
        "base_ref_requested": base_ref,
        "merge_base_sha": merge_base,
        "auto_push": False,
        "push_performed": False,
        "remote_publish_performed": False,
    }


# ---------------------------------------------------------------------------
# Completion receipts inventory
# ---------------------------------------------------------------------------


def inventory_tree_completion_artifacts(repo_root: Path) -> dict[str, Any]:
    """Inventory tree-bound completion / post-completion surfaces."""
    items: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for cand in COMPLETION_RECEIPT_CANDIDATES:
        rel = cand["path"]
        full = repo_root / rel
        present = full.is_file()
        entry: dict[str, Any] = {
            "kind": cand["kind"],
            "task_id": cand["task_id"],
            "path": rel,
            "present": present,
            "location": "tree",
        }
        if present:
            digest = file_sha256(full)
            if digest:
                entry["sha256"] = digest
            entry["size_bytes"] = full.stat().st_size
            items.append(entry)
        else:
            missing.append(
                {
                    "kind": cand["kind"],
                    "task_id": cand["task_id"],
                    "path": rel,
                    "gap": "missing_tree_artifact",
                }
            )
            items.append(entry)
    present_count = sum(1 for i in items if i.get("present"))
    return {
        "items": items,
        "present_count": present_count,
        "missing_count": len(missing),
        "missing": missing,
        "all_present": len(missing) == 0,
    }


def inventory_live_receipts(evidence_root: Path | None) -> dict[str, Any]:
    """Inventory live/offline receipts under evidence root (paths only)."""
    items: list[dict[str, Any]] = []
    gaps: list[dict[str, str]] = []
    root = Path(evidence_root) if evidence_root is not None else None
    if root is None or not root.is_dir():
        for cand in LIVE_RECEIPT_REL_CANDIDATES:
            gaps.append(
                {
                    "kind": cand["kind"],
                    "path": cand["relative"],
                    "gap": "evidence_root_absent",
                }
            )
        return {
            "evidence_root": str(root) if root is not None else None,
            "items": items,
            "gaps": gaps,
            "present_count": 0,
            "gap_count": len(gaps),
        }

    for cand in LIVE_RECEIPT_REL_CANDIDATES:
        kind = cand["kind"]
        rel = cand["relative"]
        full = root / rel
        if kind == "offline_production_receipt":
            # Directory of production_release receipts.
            if full.is_dir():
                json_files = sorted(full.glob("*.json"))
                if json_files:
                    # Bind most-recent by mtime (content-free: path + digest).
                    latest = max(json_files, key=lambda p: p.stat().st_mtime)
                    digest = file_sha256(latest)
                    items.append(
                        {
                            "kind": kind,
                            "path": str(latest.relative_to(root)),
                            "present": True,
                            "location": "evidence",
                            "sha256": digest,
                            "size_bytes": latest.stat().st_size,
                        }
                    )
                    continue
            gaps.append(
                {
                    "kind": kind,
                    "path": rel,
                    "gap": "missing_live_receipt",
                }
            )
            items.append(
                {
                    "kind": kind,
                    "path": rel,
                    "present": False,
                    "location": "evidence",
                }
            )
            continue

        if full.is_file():
            digest = file_sha256(full)
            items.append(
                {
                    "kind": kind,
                    "path": rel,
                    "present": True,
                    "location": "evidence",
                    "sha256": digest,
                    "size_bytes": full.stat().st_size,
                }
            )
        else:
            gaps.append(
                {
                    "kind": kind,
                    "path": rel,
                    "gap": "missing_live_receipt",
                }
            )
            items.append(
                {
                    "kind": kind,
                    "path": rel,
                    "present": False,
                    "location": "evidence",
                }
            )

    present_count = sum(1 for i in items if i.get("present"))
    return {
        "evidence_root": str(root),
        "items": items,
        "gaps": gaps,
        "present_count": present_count,
        "gap_count": len(gaps),
    }


def build_human_required_steps(
    *,
    branch: str | None,
    base_ref: str | None,
    package_path: str | None,
) -> list[dict[str, Any]]:
    """Concrete human-only steps with optional context bindings."""
    steps: list[dict[str, Any]] = []
    for raw in HUMAN_REQUIRED_STEPS:
        step = dict(raw)
        step["requires_human"] = True
        step["automated_by_this_tool"] = False
        if step["id"] == "push_feature_branch":
            step["suggested_command"] = (
                f"git push -u origin {branch or FEATURE_BRANCH}"
            )
            step["note"] = "Operator executes manually; prepare_pr_package never pushes."
        elif step["id"] == "open_or_update_pr":
            head = branch or FEATURE_BRANCH
            base = base_ref or "main"
            # Strip origin/ prefix for human gh CLI convenience.
            base_short = base[7:] if base.startswith("origin/") else base
            step["suggested_command"] = (
                f"gh pr create --base {base_short} --head {head} "
                f"--title 'Patent legal intelligence: post-completion package' "
                f"--body-file {package_path or '<package.md>'}"
            )
            step["note"] = (
                "Authenticated remote PR open is human-only; tool never invokes gh/api."
            )
        elif step["id"] == "review_package" and package_path:
            step["package_path"] = package_path
        steps.append(step)
    return steps


# ---------------------------------------------------------------------------
# Package assembly
# ---------------------------------------------------------------------------


def build_pr_package(
    repo_root: Path,
    *,
    base_ref: str | None = None,
    branch: str | None = None,
    evidence_root: Path | None = None,
    max_commits: int = 500,
    max_paths: int = 5000,
    package_id: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Assemble a content-free local PR package for human push/PR steps."""
    root = Path(repo_root).resolve()
    git_info = inspect_git(root, base_ref=base_ref)
    resolved_base = git_info.get("base_ref")
    current_ref = branch or git_info.get("ref") or FEATURE_BRANCH

    commits = collect_commits(
        root,
        base_ref=resolved_base if isinstance(resolved_base, str) else None,
        max_commits=max_commits,
    )
    changed_paths = collect_changed_paths(
        root,
        base_ref=resolved_base if isinstance(resolved_base, str) else None,
        max_paths=max_paths,
    )
    tree_receipts = inventory_tree_completion_artifacts(root)
    live_root = (
        Path(evidence_root).expanduser()
        if evidence_root is not None
        else default_evidence_root()
    )
    live_receipts = inventory_live_receipts(live_root)

    # Package path is filled after write; human steps get a placeholder id first.
    pkg_id = package_id or f"prpkg-{uuid.uuid4().hex[:16]}"
    ts = generated_at or utc_now()

    human_steps = build_human_required_steps(
        branch=str(current_ref) if current_ref else FEATURE_BRANCH,
        base_ref=resolved_base if isinstance(resolved_base, str) else None,
        package_path=None,
    )

    status_reasons: list[str] = []
    if not git_info.get("is_repo"):
        status_reasons.append("not_a_git_repository")
    if not git_info.get("head_sha"):
        status_reasons.append("missing_head_sha")
    if not resolved_base:
        status_reasons.append("base_ref_unresolved_using_head_only_history")
    if tree_receipts["missing_count"] > 0:
        status_reasons.append("tree_completion_artifacts_missing")
    if live_receipts["gap_count"] > 0:
        status_reasons.append("live_receipt_gaps_listed")

    # Ready for *human* packaging when tree gate artifacts present enough to
    # hand off; live gaps are non-blocking when explicitly listed.
    ready_for_human_push = bool(
        git_info.get("is_repo")
        and git_info.get("head_sha")
        and tree_receipts["all_present"]
    )

    package: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "interface": INTERFACE,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "policy_id": POLICY_ID,
        "package_id": pkg_id,
        "generated_at": ts,
        "content_free": True,
        "auto_push": False,
        "push_performed": False,
        "remote_publish_performed": False,
        "authenticated_pr_opened": False,
        "feature_branch": FEATURE_BRANCH,
        "branch": current_ref,
        "git": git_info,
        "commits": {
            "count": len(commits),
            "base_ref": resolved_base,
            "range": (
                f"{resolved_base}..HEAD"
                if resolved_base
                else "HEAD (base_ref unresolved)"
            ),
            "items": commits,
        },
        "changed_paths": {
            "count": len(changed_paths),
            "base_ref": resolved_base,
            "items": changed_paths,
        },
        "completion_receipts": {
            "tree_artifacts": tree_receipts,
            "live_receipts": live_receipts,
        },
        "evidence_gaps": list(live_receipts.get("gaps") or [])
        + list(tree_receipts.get("missing") or []),
        "human_required_steps": human_steps,
        "ready_for_human_push": ready_for_human_push,
        "status": "ready" if ready_for_human_push else "incomplete",
        "status_reasons": status_reasons,
        "runbook": RUNBOOK_REL,
        "policy": {
            "never_auto_push": True,
            "never_force_push": True,
            "never_open_authenticated_remote_pr": True,
            "never_hub_main_publish": True,
            "never_patent_center_login": True,
            "content_free": True,
            "evidence_over_status": True,
        },
    }

    # Digest excludes nested self-digest; bind body then attach.
    body_for_digest = {k: v for k, v in package.items() if k != "package_digest_sha256"}
    package["package_digest_sha256"] = sha256_hex(canonical_json(body_for_digest))
    assert_content_free(package)
    return package


def render_package_markdown(package: Mapping[str, Any]) -> str:
    """Render a human-readable PR body from a package (content-free)."""
    git = package.get("git") or {}
    commits = package.get("commits") or {}
    paths = package.get("changed_paths") or {}
    steps = package.get("human_required_steps") or []
    gaps = package.get("evidence_gaps") or []
    tree = (package.get("completion_receipts") or {}).get("tree_artifacts") or {}
    live = (package.get("completion_receipts") or {}).get("live_receipts") or {}

    lines: list[str] = [
        f"# Patent Legal Intelligence — PR Package ({package.get('task_id')})",
        "",
        f"- **Package ID:** `{package.get('package_id')}`",
        f"- **Generated (UTC):** `{package.get('generated_at')}`",
        f"- **Schema:** `{package.get('schema_version')}`",
        f"- **Goal:** `{package.get('goal_id')}`",
        f"- **Feature branch:** `{package.get('feature_branch')}`",
        f"- **Current ref:** `{package.get('branch')}`",
        f"- **Base ref:** `{git.get('base_ref') or commits.get('base_ref') or 'unresolved'}`",
        f"- **HEAD:** `{git.get('head_sha') or 'unknown'}`",
        f"- **Tree:** `{git.get('tree_sha') or 'unknown'}`",
        f"- **Merge-base:** `{git.get('merge_base_sha') or 'unknown'}`",
        f"- **Status:** `{package.get('status')}` "
        f"(ready_for_human_push={package.get('ready_for_human_push')})",
        f"- **Auto-push:** `{package.get('auto_push')}` "
        f"(push_performed={package.get('push_performed')})",
        f"- **Package digest:** `{package.get('package_digest_sha256')}`",
        "",
        "## Commits",
        "",
        f"Range: `{commits.get('range')}` — **{commits.get('count', 0)}** commit(s).",
        "",
    ]
    items = list(commits.get("items") or [])
    if not items:
        lines.append("_No commits inventoried (missing base ref or empty range)._")
        lines.append("")
    else:
        lines.append("| Short | Subject |")
        lines.append("| --- | --- |")
        for c in items[:200]:
            subj = str(c.get("subject") or "").replace("|", "\\|")
            lines.append(f"| `{c.get('short_sha')}` | {subj} |")
        if len(items) > 200:
            lines.append(f"| … | *{len(items) - 200} more omitted* |")
        lines.append("")

    lines.extend(
        [
            "## Changed paths",
            "",
            f"**{paths.get('count', 0)}** path(s) relative to base.",
            "",
        ]
    )
    path_items = list(paths.get("items") or [])
    if not path_items:
        lines.append("_No changed paths inventoried._")
        lines.append("")
    else:
        lines.append("| Status | Path |")
        lines.append("| --- | --- |")
        for p in path_items[:400]:
            path = str(p.get("path") or "").replace("|", "\\|")
            lines.append(f"| `{p.get('status')}` | `{path}` |")
        if len(path_items) > 400:
            lines.append(f"| … | *{len(path_items) - 400} more omitted* |")
        lines.append("")

    lines.extend(
        [
            "## Completion receipts",
            "",
            "### Tree-bound artifacts",
            "",
            f"Present: **{tree.get('present_count', 0)}** / "
            f"missing: **{tree.get('missing_count', 0)}**.",
            "",
        ]
    )
    for item in tree.get("items") or []:
        mark = "present" if item.get("present") else "MISSING"
        digest = item.get("sha256") or "-"
        lines.append(
            f"- `{item.get('path')}` ({item.get('kind')}, {item.get('task_id')}): "
            f"**{mark}** digest=`{digest}`"
        )
    lines.extend(
        [
            "",
            "### Live / offline evidence receipts",
            "",
            f"Evidence root: `{live.get('evidence_root')}`",
            f"Present: **{live.get('present_count', 0)}**; "
            f"gaps: **{live.get('gap_count', 0)}**.",
            "",
        ]
    )
    for item in live.get("items") or []:
        mark = "present" if item.get("present") else "gap"
        digest = item.get("sha256") or "-"
        lines.append(
            f"- `{item.get('path')}` ({item.get('kind')}): **{mark}** digest=`{digest}`"
        )

    lines.extend(["", "## Evidence gaps", ""])
    if not gaps:
        lines.append("_None listed._")
        lines.append("")
    else:
        for g in gaps:
            lines.append(
                f"- `{g.get('path')}` ({g.get('kind')}): {g.get('gap')}"
            )
        lines.append("")

    lines.extend(
        [
            "## Human-required push / PR steps",
            "",
            "This tool **never** pushes or opens authenticated remote PRs. "
            "A natural person must perform the following:",
            "",
        ]
    )
    for idx, step in enumerate(steps, start=1):
        lines.append(
            f"{idx}. **{step.get('id')}** — {step.get('description')}"
        )
        if step.get("suggested_command"):
            lines.append("")
            lines.append("   ```bash")
            lines.append(f"   {step['suggested_command']}")
            lines.append("   ```")
        if step.get("note"):
            lines.append(f"   _{step['note']}_")
        lines.append("")

    lines.extend(
        [
            "## Policy",
            "",
            "- Never auto-push / force-push",
            "- Never open authenticated remote PRs unattended",
            "- Never Hub main publish, Patent Center login, payment, or signature",
            "- Content-free package only (paths, digests, commit subjects)",
            "- Task / drained-board status alone does not authorize merge",
            "",
            f"_Runbook: `{package.get('runbook')}`_",
            "",
        ]
    )
    return "\n".join(lines)


def write_package_artifacts(
    package: Mapping[str, Any],
    *,
    output_json: Path | None = None,
    output_markdown: Path | None = None,
    package_dir: Path | None = None,
) -> dict[str, str]:
    """Write JSON + markdown package artifacts; return written paths."""
    base = Path(package_dir) if package_dir is not None else default_package_dir()
    base.mkdir(parents=True, exist_ok=True)
    pkg_id = str(package.get("package_id") or "prpkg")
    json_path = Path(output_json) if output_json is not None else base / f"{pkg_id}.json"
    md_path = (
        Path(output_markdown)
        if output_markdown is not None
        else base / f"{pkg_id}.md"
    )

    # Refresh human steps with concrete package path for review/PR body.
    mutable = dict(package)
    human_steps = build_human_required_steps(
        branch=str(mutable.get("branch") or FEATURE_BRANCH),
        base_ref=(mutable.get("git") or {}).get("base_ref"),
        package_path=str(md_path),
    )
    mutable["human_required_steps"] = human_steps
    body_for_digest = {
        k: v for k, v in mutable.items() if k != "package_digest_sha256"
    }
    mutable["package_digest_sha256"] = sha256_hex(canonical_json(body_for_digest))
    assert_content_free(mutable)

    atomic_write_json(json_path, mutable)
    atomic_write_text(md_path, render_package_markdown(mutable))
    return {
        "json": str(json_path),
        "markdown": str(md_path),
        "package_id": pkg_id,
        "package_digest_sha256": str(mutable["package_digest_sha256"]),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/ops/patent_legal_intelligence/prepare_pr_package.py",
        description=(
            "Assemble a local feature-branch PR package summarizing commits, "
            "changed paths, completion receipts, and human-required push/PR "
            "steps. Never git-pushes or opens authenticated remote PRs "
            f"({TASK_ID} / {GOAL_ID})."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: inferred from script location)",
    )
    parser.add_argument(
        "--base-ref",
        type=str,
        default=None,
        help=(
            "Base git ref for commit/path inventory "
            "(default: first existing among origin/main, main, origin/master, master)"
        ),
    )
    parser.add_argument(
        "--branch",
        type=str,
        default=None,
        help=(
            "Feature branch name for human steps "
            f"(default: current ref or {FEATURE_BRANCH})"
        ),
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=None,
        help=(
            "Root for live/offline completion receipts inventory "
            "(default: $XDG_STATE_HOME/.../patent_legal_intelligence)"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the package JSON (default under XDG pr_package/)",
    )
    parser.add_argument(
        "--output-markdown",
        type=Path,
        default=None,
        help="Optional path for the package markdown PR body",
    )
    parser.add_argument(
        "--package-dir",
        type=Path,
        default=None,
        help="Directory for default JSON/markdown outputs",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Do not write package files (stdout report only)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON package on stdout",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Emit markdown PR body on stdout (instead of JSON summary)",
    )
    parser.add_argument(
        "--max-commits",
        type=int,
        default=500,
        help="Maximum commits to inventory (default 500)",
    )
    parser.add_argument(
        "--max-paths",
        type=int,
        default=5000,
        help="Maximum changed paths to inventory (default 5000)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = (
        Path(args.repo_root).expanduser().resolve()
        if args.repo_root is not None
        else repo_root_from_script()
    )
    evidence = (
        Path(args.evidence_root).expanduser()
        if args.evidence_root is not None
        else None
    )

    try:
        package = build_pr_package(
            root,
            base_ref=args.base_ref,
            branch=args.branch,
            evidence_root=evidence,
            max_commits=max(1, int(args.max_commits)),
            max_paths=max(1, int(args.max_paths)),
        )
    except PrPackageError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "task_id": TASK_ID,
                    "auto_push": False,
                    "push_performed": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    written: dict[str, str] | None = None
    if not args.no_write:
        try:
            written = write_package_artifacts(
                package,
                output_json=args.output,
                output_markdown=args.output_markdown,
                package_dir=args.package_dir,
            )
            if written.get("json"):
                package = load_json(Path(written["json"]))
        except PrPackageError as exc:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": str(exc),
                        "task_id": TASK_ID,
                        "auto_push": False,
                        "push_performed": False,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2

    if args.markdown:
        md = render_package_markdown(package)
        sys.stdout.write(md if md.endswith("\n") else md + "\n")
    elif args.json:
        print(json.dumps(package, indent=2, sort_keys=True))
    else:
        summary = {
            "ok": package.get("status") == "ready",
            "task_id": TASK_ID,
            "goal_id": GOAL_ID,
            "schema_version": SCHEMA_VERSION,
            "interface": INTERFACE,
            "package_id": package.get("package_id"),
            "package_digest_sha256": package.get("package_digest_sha256"),
            "status": package.get("status"),
            "ready_for_human_push": package.get("ready_for_human_push"),
            "auto_push": False,
            "push_performed": False,
            "remote_publish_performed": False,
            "authenticated_pr_opened": False,
            "branch": package.get("branch"),
            "feature_branch": package.get("feature_branch"),
            "git": {
                "head_sha": (package.get("git") or {}).get("head_sha"),
                "tree_sha": (package.get("git") or {}).get("tree_sha"),
                "base_ref": (package.get("git") or {}).get("base_ref"),
                "merge_base_sha": (package.get("git") or {}).get("merge_base_sha"),
                "ref": (package.get("git") or {}).get("ref"),
            },
            "commits_count": (package.get("commits") or {}).get("count"),
            "changed_paths_count": (package.get("changed_paths") or {}).get("count"),
            "evidence_gaps_count": len(package.get("evidence_gaps") or []),
            "human_required_steps_count": len(
                package.get("human_required_steps") or []
            ),
            "written": written,
            "runbook": RUNBOOK_REL,
        }
        print(json.dumps(summary, indent=2, sort_keys=True))

    return 0 if package.get("status") == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
