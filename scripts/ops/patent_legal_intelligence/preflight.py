#!/usr/bin/env python3
"""Fail-closed repository, provider, and supervisor launch preflight."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


TARGET_BRANCH = "feature/patent-legal-intelligence"
REQUIRED_FLAGS = {
    "--strict-task-sharding",
    "--execution-slice-task-id",
    "--implementation-protected-path",
    "--merge-queue-dir",
    "--no-objective-task-janitor",
    "--no-objective-goal-refinement",
    "--no-objective-goal-completion-reconcile",
    "--no-objective-goal-migration",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _run(args: Sequence[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(args),
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        return subprocess.CompletedProcess(list(args), 127, "", str(exc))


def _resolve_accelerator(repo_root: Path, requested: str) -> Path | None:
    candidates = []
    if requested:
        candidates.append(Path(requested))
    configured = os.environ.get("PATLAW_ACCELERATE_ROOT", "").strip()
    if configured:
        candidates.append(Path(configured))
    candidates.append(repo_root.parent / "ipfs_accelerate_py")
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if (resolved / "ipfs_accelerate_py" / "agent_supervisor").is_dir():
            return resolved
    return None


def check(repo_root: Path, accelerator_root: Path | None, *, allow_dirty: bool) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    config_path = repo_root / "config/agent_supervisor_patent_legal_intelligence.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        config = {}
        errors.append(f"cannot load supervisor config: {exc}")
    validator = repo_root / "scripts/validate_patent_legal_intelligence_board.py"
    validation = _run([sys.executable, str(validator), "--repo-root", str(repo_root), "--json"], cwd=repo_root)
    try:
        board_report = json.loads(validation.stdout)
    except json.JSONDecodeError:
        board_report = {"ok": False, "errors": [validation.stderr.strip() or "validator returned invalid JSON"]}
    if validation.returncode != 0 or not board_report.get("ok"):
        errors.extend(f"board: {item}" for item in board_report.get("errors", ["validation failed"]))

    branch = _run(["git", "branch", "--show-current"], cwd=repo_root).stdout.strip()
    if branch != TARGET_BRANCH:
        errors.append(f"datasets branch is {branch!r}, expected {TARGET_BRANCH!r}")
    target_probe = _run(["git", "rev-parse", "--verify", "--quiet", TARGET_BRANCH], cwd=repo_root)
    if target_probe.returncode:
        errors.append(f"merge target does not exist: {TARGET_BRANCH}")
    merge_path = _run(["git", "rev-parse", "--git-path", "MERGE_HEAD"], cwd=repo_root).stdout.strip()
    if merge_path and (repo_root / merge_path).exists():
        errors.append("datasets worktree has a merge in progress")
    datasets_dirty = _run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=repo_root).stdout.strip()
    if datasets_dirty and not allow_dirty:
        errors.append("datasets integration worktree is dirty")
    if _run(["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"], cwd=repo_root).returncode:
        errors.append("datasets HEAD does not contain the fetched origin/main")

    if accelerator_root is None:
        errors.append("compatible ipfs_accelerate_py worktree was not found")
        accelerator_branch = ""
        accelerator_dirty = ""
    else:
        accelerator_branch = _run(["git", "branch", "--show-current"], cwd=accelerator_root).stdout.strip()
        accelerator_dirty = _run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=accelerator_root
        ).stdout.strip()
        if accelerator_dirty and not allow_dirty:
            errors.append("accelerator integration worktree is dirty")
        expected_accelerator_branch = str((config.get("accelerator") or {}).get("branch") or "")
        if expected_accelerator_branch and accelerator_branch != expected_accelerator_branch:
            errors.append(
                f"accelerator branch is {accelerator_branch!r}, expected {expected_accelerator_branch!r}"
            )
        if _run(
            ["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"], cwd=accelerator_root
        ).returncode:
            errors.append("accelerator HEAD does not contain the fetched origin/main")
        required_capability = str(
            (config.get("accelerator") or {}).get("required_capability") or ""
        ).strip()
        if not required_capability:
            errors.append("supervisor config does not describe the required accelerator capability")
        required_commit = str(
            (config.get("accelerator") or {}).get("required_feature_commit") or ""
        ).strip()
        if not required_commit:
            errors.append("supervisor config does not pin the reviewed failover commit")
        elif _run(
            ["git", "merge-base", "--is-ancestor", required_commit, "HEAD"], cwd=accelerator_root
        ).returncode:
            errors.append(
                "accelerator lacks reviewed clean Grok-to-Codex failover commit " + required_commit
            )
        check_env = dict(os.environ)
        prior_pythonpath = check_env.get("PYTHONPATH", "")
        check_env["PYTHONPATH"] = f"{accelerator_root}:{repo_root}" + (
            f":{prior_pythonpath}" if prior_pythonpath else ""
        )
        help_result = _run(
            [
                "python3",
                "-P",
                "-m",
                "ipfs_accelerate_py.agent_supervisor.todo_daemon.implementation_supervisor",
                "--help",
            ],
            cwd=repo_root,
            env=check_env,
        )
        if help_result.returncode:
            errors.append(
                "compatible supervisor import/help failed: "
                + (help_result.stderr.strip().splitlines()[-1] if help_result.stderr.strip() else "unknown error")
            )
        else:
            missing_flags = sorted(flag for flag in REQUIRED_FLAGS if flag not in help_result.stdout)
            if missing_flags:
                errors.append(f"accelerator supervisor lacks required flags: {missing_flags}")

    grok_binary = os.environ.get("IPFS_ACCELERATE_AGENT_GROK_BIN", "grok")
    grok_version = _run([grok_binary, "--version"], cwd=repo_root)
    grok_auth = Path(os.environ.get("GROK_AUTH_FILE", "~/.grok/auth.json")).expanduser()
    codex_version = _run(["codex", "--version"], cwd=repo_root)
    codex_login = _run(["codex", "login", "status"], cwd=repo_root)
    if grok_version.returncode:
        errors.append("Grok primary implementation provider executable is unavailable")
    if not grok_auth.is_file():
        errors.append(f"Grok primary authentication file is unavailable: {grok_auth}")
    if codex_version.returncode:
        errors.append("Codex backup implementation provider executable is unavailable")
    if codex_login.returncode:
        errors.append("Codex backup implementation provider is not authenticated")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "board": board_report,
        "repo_root": str(repo_root),
        "datasets_branch": branch,
        "datasets_dirty": bool(datasets_dirty),
        "accelerator_root": str(accelerator_root) if accelerator_root else "",
        "accelerator_branch": accelerator_branch,
        "accelerator_dirty": bool(accelerator_dirty),
        "provider": {
            "name": "auto",
            "primary": "grok",
            "primary_model": "grok-4.5",
            "primary_version": grok_version.stdout.strip(),
            "primary_authenticated": grok_auth.is_file(),
            "backup": "codex",
            "backup_model": "gpt-5.6-terra",
            "backup_version": codex_version.stdout.strip(),
            "backup_authenticated": codex_login.returncode == 0,
            "fresh_attempt_fallback": True,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=_repo_root())
    parser.add_argument("--accelerate-root", default="")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = args.repo_root.expanduser().resolve()
    accelerator_root = _resolve_accelerator(repo_root, args.accelerate_root)
    report = check(repo_root, accelerator_root, allow_dirty=args.allow_dirty)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"PATLAW launch preflight: {'PASS' if report['ok'] else 'FAIL'}")
        for warning in report["warnings"]:
            print(f"WARNING: {warning}")
        for error in report["errors"]:
            print(f"ERROR: {error}")
        if report["ok"]:
            print(
                f"branch={report['datasets_branch']} accelerator={report['accelerator_branch']} "
                f"provider={report['provider']['name']} primary={report['provider']['primary']} "
                f"backup={report['provider']['backup']} fresh_attempt=true"
            )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
