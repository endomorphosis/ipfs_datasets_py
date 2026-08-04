#!/usr/bin/env python3
"""Operator production handoff receipt for post-completion ops (PATLAW-169).

Assembles a single content-free handoff artifact that binds:

* exact git HEAD / tree SHA
* offline completion-gate / production-status disposition
* PR package path (or explicit gap)
* live canary disposition (or offline/gap)
* Hub dry-run receipt presence (or gap)
* remaining human actions (never auto-push / auto-file / legal sign-off)

Never git-pushes, never opens remote PRs, never claims legal completion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "patent-legal-operator-handoff-receipt.v1"
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# Composed so source does not embed contiguous secret-looking literals.
_FORBIDDEN_MARKERS = frozenset(
    {
        "authorization: " + "bearer",
        "x-" + "api-key:",
        "api" + "_key=",
        "sk-" + "live-",
        "pass" + "word=",
        "-----" + "begin ",
        "secret" + "_document_body",
        "private " + "extracted_text",
    }
)


class HandoffError(RuntimeError):
    """Fail-closed handoff assembly error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(payload: str | bytes) -> str:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def assert_content_free(payload: Any) -> None:
    blob = canonical_json(payload).lower()
    for marker in _FORBIDDEN_MARKERS:
        if marker in blob:
            raise HandoffError(f"handoff receipt is not content-free: found {marker!r}")


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def git_head_and_tree(repo: Path) -> tuple[str | None, str | None]:
    head = _run_git(repo, "rev-parse", "HEAD")
    tree = _run_git(repo, "rev-parse", "HEAD^{tree}")
    head_sha = head.stdout.strip().lower() if head.returncode == 0 else ""
    tree_sha = tree.stdout.strip().lower() if tree.returncode == 0 else ""
    return (
        head_sha if GIT_SHA_RE.match(head_sha) else None,
        tree_sha if GIT_SHA_RE.match(tree_sha) else None,
    )


def git_branch(repo: Path) -> str | None:
    result = _run_git(repo, "symbolic-ref", "-q", "--short", "HEAD")
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def default_state_root() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "ipfs_accelerate_py" / "patent_legal_intelligence"


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[3]


def _path_if_file(path: Path | None) -> Path | None:
    if path is None:
        return None
    return path if path.is_file() else None


def discover_artifact(
    *,
    explicit: Path | None,
    candidates: Sequence[Path],
) -> dict[str, Any]:
    if explicit is not None:
        if explicit.is_file():
            return {
                "present": True,
                "path": str(explicit),
                "digest_sha256": sha256_hex(explicit.read_bytes()),
                "gap": None,
            }
        return {
            "present": False,
            "path": str(explicit),
            "digest_sha256": None,
            "gap": "explicit_path_missing",
        }
    for candidate in candidates:
        if candidate.is_file():
            return {
                "present": True,
                "path": str(candidate),
                "digest_sha256": sha256_hex(candidate.read_bytes()),
                "gap": None,
            }
    return {
        "present": False,
        "path": None,
        "digest_sha256": None,
        "gap": "no_artifact_found",
        "searched": [str(path) for path in candidates[:12]],
    }


def run_production_status_offline(repo: Path) -> dict[str, Any]:
    """Best-effort offline production_status projection (content-free summary)."""

    script = repo / "scripts/ops/patent_legal_intelligence/production_status.py"
    if not script.is_file():
        return {"present": False, "gap": "production_status_script_missing", "status": None}
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--offline", "--json"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "present": False,
            "gap": f"production_status_failed:{type(exc).__name__}",
            "status": None,
        }
    if result.returncode != 0:
        return {
            "present": False,
            "gap": "production_status_nonzero_exit",
            "status": None,
            "returncode": result.returncode,
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "present": False,
            "gap": "production_status_invalid_json",
            "status": None,
        }
    # Keep only content-free top-level fields.
    summary = {
        "present": True,
        "gap": None,
        "status": payload.get("status") or payload.get("overall_status") or payload.get("state"),
        "drained": payload.get("drained"),
        "completed": payload.get("completed")
        if "completed" in payload
        else (payload.get("status") == "completed"),
    }
    return summary


def remaining_human_actions(
    *,
    pr_package: Mapping[str, Any],
    canary: Mapping[str, Any],
    hub_dry_run: Mapping[str, Any],
    production_status: Mapping[str, Any],
) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if not pr_package.get("present"):
        actions.append(
            {
                "id": "assemble_pr_package",
                "action": "Run prepare_pr_package.py and review the local PR package.",
            }
        )
    else:
        actions.append(
            {
                "id": "review_pr_package",
                "action": "Review the local PR package commits, paths, and receipts.",
            }
        )
        actions.append(
            {
                "id": "human_git_push",
                "action": "If ready, a natural person runs git push (never unattended).",
            }
        )
        actions.append(
            {
                "id": "open_or_update_pr",
                "action": "A natural person opens or updates the GitHub PR and requests review.",
            }
        )
    if not canary.get("present"):
        actions.append(
            {
                "id": "canary_gap",
                "action": "Record or re-run offline/live canary and attach the content-free receipt.",
            }
        )
    if not hub_dry_run.get("present"):
        actions.append(
            {
                "id": "hub_dry_run_gap",
                "action": "Record or re-run Hub dry-run staging verification (no main upload).",
            }
        )
    if production_status.get("status") not in {"completed", "drained"}:
        actions.append(
            {
                "id": "review_production_status",
                "action": "Review offline production_status projection and close mandatory gaps.",
            }
        )
    actions.append(
        {
            "id": "no_auto_legal_signoff",
            "action": "Do not claim legal sign-off, filing, payment, or Patent Center submission without a natural person.",
        }
    )
    actions.append(
        {
            "id": "no_unattended_publish",
            "action": "Do not promote Hub main or auto-publish without explicit human approval of exact digests.",
        }
    )
    return actions


def build_handoff_receipt(
    *,
    repo_root: Path,
    pr_package_path: Path | None = None,
    canary_receipt_path: Path | None = None,
    hub_dry_run_receipt_path: Path | None = None,
    state_root: Path | None = None,
) -> dict[str, Any]:
    repo = repo_root.resolve()
    state = state_root or default_state_root()
    head, tree = git_head_and_tree(repo)
    branch = git_branch(repo)

    pr_package = discover_artifact(
        explicit=pr_package_path,
        candidates=[
            state / "pr_package" / "pr_package.json",
            state / "pr_package" / "latest.json",
            Path("/tmp/patlaw-pr-package.json"),
        ],
    )
    canary = discover_artifact(
        explicit=canary_receipt_path,
        candidates=[
            state / "canary" / "receipt.json",
            state / "canary" / "latest.json",
            Path("/tmp/patlaw-canary/receipt.json"),
        ],
    )
    hub_dry_run = discover_artifact(
        explicit=hub_dry_run_receipt_path,
        candidates=[
            state / "hub_dry_run" / "receipt.json",
            state / "hub_dry_run" / "latest.json",
            Path("/tmp/patlaw-hub-dry-run/receipt.json"),
            repo / "data/release/patent_legal_intelligence/hub_dry_run_receipt.json",
        ],
    )
    production_status = run_production_status_offline(repo)

    actions = remaining_human_actions(
        pr_package=pr_package,
        canary=canary,
        hub_dry_run=hub_dry_run,
        production_status=production_status,
    )
    gaps = [
        item["gap"]
        for item in (pr_package, canary, hub_dry_run, production_status)
        if item.get("gap")
    ]
    ready_for_human_review = (
        head is not None
        and tree is not None
        and pr_package.get("present") is True
        and not any(
            gap
            for gap in gaps
            if gap
            not in {
                "no_artifact_found",  # optional live/hub gaps may remain listed
            }
        )
    )
    # Handoff is never automatic legal completion.
    receipt = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now(),
        "program": "patent-legal-intelligence-v1",
        "branch": branch,
        "git_head_sha": head,
        "git_tree_sha": tree,
        "components": {
            "offline_gate_and_production_status": production_status,
            "pr_package": pr_package,
            "canary": canary,
            "hub_dry_run": hub_dry_run,
        },
        "gaps": gaps,
        "remaining_human_actions": actions,
        "auto_push": False,
        "auto_file": False,
        "legal_signoff_complete": False,
        "ready_for_human_review": bool(pr_package.get("present") and head and tree),
        "notes": [
            "This receipt does not authorize filing, payment, signature, or Hub main publish.",
            "Natural-person actions remain mandatory for push, PR, and publication promote.",
        ],
    }
    # Stabilize digest without self-reference.
    digest_body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    receipt["receipt_sha256"] = sha256_hex(canonical_json(digest_body))
    assert_content_free(receipt)
    return receipt


def write_receipt(receipt: Mapping[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(canonical_json(receipt) + "\n", encoding="utf-8")
    tmp.replace(output)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--pr-package", type=Path, default=None)
    parser.add_argument("--canary-receipt", type=Path, default=None)
    parser.add_argument("--hub-dry-run-receipt", type=Path, default=None)
    parser.add_argument("--state-root", type=Path, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path for the handoff JSON (default under XDG state handoff/).",
    )
    parser.add_argument("--json", action="store_true", help="Print receipt JSON to stdout.")
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Do not write a receipt file; stdout only when --json.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = (args.repo_root or repo_root_from_script()).resolve()
    try:
        receipt = build_handoff_receipt(
            repo_root=repo,
            pr_package_path=args.pr_package,
            canary_receipt_path=args.canary_receipt,
            hub_dry_run_receipt_path=args.hub_dry_run_receipt,
            state_root=args.state_root,
        )
    except HandoffError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    written: Path | None = None
    if not args.no_write:
        output = args.output
        if output is None:
            output = default_state_root() / "handoff" / "operator_handoff_receipt.json"
        written = write_receipt(receipt, output.resolve())
        receipt = {**receipt, "receipt_path": str(written)}
        # Refresh digest after adding path.
        body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
        receipt["receipt_sha256"] = sha256_hex(canonical_json(body))
        write_receipt(receipt, written)

    if args.json or args.no_write:
        print(canonical_json(receipt))
    else:
        print(
            f"handoff status={'ready_for_human_review' if receipt.get('ready_for_human_review') else 'gaps_remain'} "
            f"head={receipt.get('git_head_sha') or 'unknown'} "
            f"path={written or '-'}"
        )
        for action in receipt.get("remaining_human_actions") or []:
            print(f"  - {action.get('id')}: {action.get('action')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
