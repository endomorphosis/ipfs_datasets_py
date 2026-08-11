#!/usr/bin/env python3
"""Fail-closed preflight for the sealed legal corpora supervisor."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Importing the board entry installs the board-specific bounded-refill mapping
# before preflight renders the exact launch argv.
from scripts.ops.agent_supervisor import (
    configured_board_scheduler as _board_entry,
)

configured_board_launch_plan = _board_entry._scheduler.configured_board_launch_plan
configured_board_launch_environment = (
    _board_entry._scheduler.configured_board_launch_environment
)
load_configured_board = _board_entry._scheduler.load_configured_board
preflight_configured_board = _board_entry._scheduler.preflight_configured_board
from ipfs_accelerate_py.agent_supervisor.runtime.provider_command_binding import (
    preflight_provider_entry_module,
)
from ipfs_accelerate_py.agent_supervisor.validation.validation_runtime import (
    ValidationRuntimeError,
    preflight_validation_python_modules,
)

from scripts.ops.legal_corpora_reindex.status import (
    _daemon_command,
    _master_command,
    _outer_command,
)

DEFAULT_CONFIG = Path("config/agent_supervisor_legal_corpora_reindex_scheduler.json")
TRUSTED_GIT = Path("/usr/bin/git")


def _run(argv: list[str], cwd: Path, timeout: float = 30.0) -> dict[str, Any]:
    try:
        actual_argv = list(argv)
        environment = None
        if actual_argv and actual_argv[0] == "git":
            git = TRUSTED_GIT.resolve(strict=True)
            metadata = git.stat()
            if (
                git != TRUSTED_GIT
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != 0
                or metadata.st_mode & 0o022
            ):
                raise OSError("trusted Git executable is unavailable")
            actual_argv = [
                str(git),
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.untrackedCache=false",
                "-c",
                "core.attributesFile=/dev/null",
                "-c",
                "core.excludesFile=/dev/null",
                *actual_argv[1:],
            ]
            environment = {
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "HOME": "/nonexistent",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PATH": "/usr/bin:/bin",
            }
        result = subprocess.run(
            actual_argv,
            cwd=cwd,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        return {
            "argv": actual_argv,
            "returncode": result.returncode,
            "stdout": result.stdout.strip()[-2000:],
            "stderr": result.stderr.strip()[-2000:],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "argv": argv,
            "returncode": 124,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
        }


def _cmdline(pid_dir: Path) -> list[str]:
    try:
        raw = (pid_dir / "cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def _probe_python_modules(
    modules: tuple[str, ...],
    *,
    environment: dict[str, str],
) -> tuple[dict[str, bool], dict[str, Any]]:
    """Run the daemon's exact sealed dependency probe before launch."""

    try:
        receipt = preflight_validation_python_modules(
            modules,
            environment=environment,
        )
    except (OSError, ValidationRuntimeError) as exc:
        receipt = {
            "schema": "validation-python-module-preflight-unavailable@1",
            "passed": False,
            "reason": "validation_python_module_probe_unavailable",
            "required_modules": ["pytest", *modules],
            "missing_modules": list(modules),
            "failed_modules": {},
            "exception_type": type(exc).__name__,
            "error": str(exc)[-1000:],
        }
    required = {
        str(item) for item in receipt.get("required_modules", []) if str(item)
    }
    missing = {
        str(item) for item in receipt.get("missing_modules", []) if str(item)
    }
    failures = receipt.get("failed_modules")
    failed = set(failures) if isinstance(failures, dict) else set()
    probe_environment = receipt.get("environment")
    launcher = receipt.get("validation_python_launcher")
    receipt_credible = bool(
        receipt.get("reason")
        in {
            "validation_python_modules_available",
            "validation_python_modules_unavailable",
        }
        and isinstance(probe_environment, dict)
        and probe_environment.get("home_is_private") is True
        and probe_environment.get("python_no_user_site") is True
        and probe_environment.get("site_user_enabled") is False
        and isinstance(launcher, dict)
        and launcher.get("sealed") is True
        and set(modules).issubset(required)
    )
    imports = {
        module: bool(
            receipt_credible and module not in missing and module not in failed
        )
        for module in modules
    }
    return imports, receipt


def _matching_processes(
    repo_root: Path, namespace: str, runtime_root: Path
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return matches
    repo_text = str(repo_root)
    runtime_text = str(runtime_root)
    for child in proc.iterdir():
        if not child.name.isdigit() or int(child.name) == os.getpid():
            continue
        argv = _cmdline(child)
        if not argv:
            continue
        joined = "\0".join(argv)
        implementation_match = any(
            predicate(argv, repo_root)
            for predicate in (_master_command, _outer_command, _daemon_command)
        )
        scope_match = namespace in joined or runtime_text in joined
        if implementation_match and scope_match and repo_text in joined:
            try:
                ppid = int((child / "stat").read_text(encoding="utf-8").split()[3])
            except (OSError, ValueError, IndexError):
                ppid = None
            matches.append({"pid": int(child.name), "ppid": ppid, "argv": argv})
    return sorted(matches, key=lambda item: item["pid"])


def run_preflight(repo_root: Path, config_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    board = load_configured_board(config_path, repo_root=repo_root)
    configured = preflight_configured_board(board)
    if not configured.get("valid"):
        errors.extend(str(item) for item in configured.get("errors", []))

    plan = configured_board_launch_plan(
        board,
        implement=True,
        detach=True,
        stamp="PREFLIGHT",
    )
    expected_environment = {
        "IPFS_ACCELERATE_AGENT_IMPLEMENTATION_PROVIDER": "grok_cli",
        "IPFS_ACCELERATE_AGENT_IMPLEMENTATION_FALLBACK_PROVIDER": "codex",
        "IPFS_ACCELERATE_AGENT_IMPLEMENTATION_FALLBACK_TRIGGER": "primary_quota_exhausted",
        "IPFS_ACCELERATE_AGENT_GROK_MODEL": "grok-4.5",
        "IPFS_ACCELERATE_AGENT_CODEX_MODEL": "gpt-5.6-terra",
        "IPFS_ACCELERATE_AGENT_CODEX_REASONING_EFFORT": "medium",
        "IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON": "/usr/bin/python3.12",
        "IPFS_ACCELERATE_AGENT_VALIDATION_PYTHONPATH": (
            "/opt/ipfs-accelerate-validation-python-74c4a6ff/site-packages"
        ),
        "IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON_MODULES": (
            "huggingface_hub,numpy,pyarrow"
        ),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    if plan.get("environment") != expected_environment:
        errors.append(
            "launch plan ordered-provider environment does not match the sealed contract"
        )
    argv = [str(item) for item in plan.get("argv", [])]
    required_tokens = {
        "--implement": {"--implement", "--common-arg=--implement"},
        "--implementation-supervisor-strict-task-sharding": {
            "--implementation-supervisor-strict-task-sharding"
        },
        "--exit-when-all-tracks-terminal": {"--exit-when-all-tracks-terminal"},
    }
    for token, spellings in required_tokens.items():
        if not any(spelling in argv for spelling in spellings):
            errors.append(f"launch plan is missing {token}")
    for token in (
        "--objective-refill-scan",
        "--codebase-refill-scan",
        "--objective-scan-min-open-tasks",
        "--objective-refill-timeout-seconds",
        "--codebase-scan-min-open-tasks",
        "--codebase-refill-timeout-seconds",
    ):
        if not any(token in item for item in argv):
            errors.append(f"launch plan is missing bounded refill option {token}")
    for forbidden in (
        "--no-objective-task-janitor",
        "--no-objective-goal-completion-reconcile",
    ):
        if any(forbidden in item for item in argv):
            errors.append(f"launch plan unexpectedly disables {forbidden[5:]}")
    if plan.get("lanes") != 4 or plan.get("strict_task_sharding") is not True:
        errors.append("launch plan is not a four-lane strict shard")

    paired_config = board.payload.get("source_binding", {}).get(
        "paired_accelerator", {}
    )
    paired_root = (repo_root / str(paired_config.get("sibling_path") or "")).resolve()
    paired_top = _run(["git", "rev-parse", "--show-toplevel"], paired_root)
    paired_head = _run(["git", "rev-parse", "HEAD"], paired_root)
    paired_clean = _run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"], paired_root
    )
    paired_valid = (
        paired_top["returncode"] == 0
        and Path(paired_top["stdout"]).resolve() == paired_root
        and paired_head["returncode"] == 0
        and paired_head["stdout"] == paired_config.get("required_revision")
        and paired_clean["returncode"] == 0
        and not paired_clean["stdout"]
    )
    if not paired_valid:
        errors.append(
            "paired accelerator is missing, dirty, or not at the exact required revision"
        )

    try:
        binding = preflight_provider_entry_module(
            "ipfs_accelerate_py.agent_supervisor.grok_cli_runner"
        )
        provider_binding = {
            "complete": bool(binding.complete),
            "missing": list(binding.missing),
            "unknown_symbols": list(binding.unknown_symbols),
        }
    except Exception as exc:  # noqa: BLE001 - report provider import failures
        provider_binding = {"complete": False, "error": f"{type(exc).__name__}: {exc}"}
        errors.append(f"provider entry preflight failed: {type(exc).__name__}: {exc}")

    grok = _run(["grok", "--version"], repo_root)
    codex = _run(["codex", "--version"], repo_root)
    codex_auth = _run(["codex", "login", "status"], repo_root)
    hf_auth = _run(["hf", "auth", "whoami"], repo_root)
    if grok["returncode"] != 0:
        errors.append("grok CLI is unavailable")
    if codex["returncode"] != 0 or codex_auth["returncode"] != 0:
        errors.append("Codex fallback CLI is unavailable or unauthenticated")
    if hf_auth["returncode"] != 0 or "justicedao" not in hf_auth["stdout"]:
        errors.append(
            "Hugging Face credentials are unavailable or do not show justicedao access"
        )

    required_modules = ("huggingface_hub", "numpy", "pyarrow", "pytest")
    effective_launch_environment = configured_board_launch_environment(
        {
            str(key): str(value)
            for key, value in plan.get("environment", {}).items()
        },
        inherited_environment=os.environ,
    )
    imports, validation_python_preflight = _probe_python_modules(
        (*required_modules, "datasets"),
        environment=effective_launch_environment,
    )
    for module in required_modules:
        if not imports[module]:
            errors.append(f"required Python module is missing: {module}")
    if not imports["datasets"]:
        warnings.append(
            "optional `datasets` package is absent; direct-Hub builders must use pyarrow/huggingface_hub or install a pinned build environment"
        )

    ignore_checks: list[dict[str, Any]] = []
    for field in ("state", "worktrees", "merge_queue", "logs"):
        sentinel = board.path(board.runtime_paths[field]) / ".preflight-sentinel"
        relative = sentinel.relative_to(repo_root).as_posix()
        check = _run(
            ["git", "check-ignore", "--no-index", "-q", "--", relative], repo_root
        )
        ignored = check["returncode"] == 0
        ignore_checks.append({"field": field, "path": relative, "ignored": ignored})
        if not ignored:
            errors.append(f"runtime path is not ignored by Git: {relative}")

    operation_state: list[str] = []
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REBASE_HEAD", "REVERT_HEAD"):
        path_result = _run(["git", "rev-parse", "--git-path", marker], repo_root)
        marker_path = Path(path_result["stdout"])
        if not marker_path.is_absolute():
            marker_path = repo_root / marker_path
        if path_result["returncode"] == 0 and marker_path.exists():
            operation_state.append(marker)
    if operation_state:
        errors.append(f"Git operation is in progress: {operation_state}")

    runtime_root = board.path(board.runtime_paths["root"])
    collisions = _matching_processes(repo_root, board.board_namespace, runtime_root)
    if collisions:
        errors.append(
            "the exact supervisor namespace is already running; refuse duplicate launch"
        )

    runtime_artifacts: list[str] = []
    if runtime_root.exists():
        runtime_artifacts = sorted(
            path.relative_to(runtime_root).as_posix()
            for path in runtime_root.rglob("*")
            if path.is_file()
        )[:200]
        if runtime_artifacts and not collisions:
            errors.append(
                "stale runtime artifacts exist without an owned live supervisor; operator reconciliation is required"
            )

    return {
        "schema": "ipfs_datasets_py/legal-corpora-reindex-preflight@1",
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "configured_board": configured,
        "launch_plan": plan,
        "runtime_namespace": {
            "root": str(runtime_root),
            "colliding_processes": collisions,
            "existing_artifacts": runtime_artifacts,
            "git_ignore_checks": ignore_checks,
            "git_operation_state": operation_state,
        },
        "providers": {
            "binding": provider_binding,
            "grok": grok,
            "codex": codex,
            "codex_auth": codex_auth,
            "huggingface_auth": hf_auth,
            "python_imports": imports,
            "validation_python_preflight": validation_python_preflight,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[3]
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    config_path = args.config
    if not config_path.is_absolute():
        config_path = repo_root / config_path
    try:
        report = run_preflight(repo_root, config_path.resolve())
    except Exception as exc:  # noqa: BLE001 - CLI boundary is fail-closed
        report = {
            "schema": "ipfs_datasets_py/legal-corpora-reindex-preflight@1",
            "valid": False,
            "errors": [f"{type(exc).__name__}: {exc}"],
            "warnings": [],
        }
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print("valid" if report["valid"] else "invalid")
        for error in report.get("errors", []):
            print(f"ERROR: {error}")
        for warning in report.get("warnings", []):
            print(f"WARNING: {warning}")
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
