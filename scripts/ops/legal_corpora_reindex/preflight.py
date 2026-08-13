#!/usr/bin/env python3
"""Fail-closed preflight for the sealed legal corpora supervisor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
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

VALIDATION_REQUIRED_MODULES = (
    "aiohttp",
    "anyio",
    "bs4",
    "cachetools",
    "cryptography",
    "datasets",
    "duckdb",
    "faiss",
    "fsspec",
    "httpx",
    "huggingface_hub",
    "hypothesis",
    "jsonschema",
    "multiformats",
    "networkx",
    "numpy",
    "pandas",
    "playwright",
    "pyarrow",
    "pydantic",
    "pydantic_settings",
    "pypdf",
    "PyPDF2",
    "pytest",
    "pytest_asyncio",
    "pytest_benchmark",
    "pytest_cov",
    "pytest_mock",
    "pytest_parallel",
    "pytest_timeout",
    "xdist",
    "yaml",
    "rdflib",
    "requests",
    "sklearn",
    "scipy",
    "sentence_transformers",
    "torch",
    "tqdm",
    "transformers",
    "trio",
    "urllib3",
)
VALIDATION_PYTHON_ROOT = Path(
    "/opt/ipfs-accelerate-legal-validation-7ffe92439767"
)
VALIDATION_PLAYWRIGHT_ROOT = Path(
    "/opt/ipfs-accelerate-legal-playwright-3c176393527b"
)
SEALED_VALIDATION_DEPLOYMENTS = (
    {
        "name": "validation_python",
        "root": VALIDATION_PYTHON_ROOT,
        "schema": "ipfs-accelerate-legal-validation-deployment@1",
        "receipt_sha256": (
            "654d64e130c9b8e748ea76c3947eb47cc52bea64adb40f2592f7204dfe503ad0"
        ),
        "manifest_sha256": (
            "7ffe92439767e99c849a4f7aad0ee5d64e19ab9f754b5f0915f00571ac51f85a"
        ),
    },
    {
        "name": "validation_playwright",
        "root": VALIDATION_PLAYWRIGHT_ROOT,
        "schema": "ipfs-accelerate-legal-playwright-deployment@1",
        "receipt_sha256": (
            "8b497a041d80cf64b4b792c0b9dee34970cdf0202b7801db7577540de4daea3f"
        ),
        "manifest_sha256": (
            "3c176393527b23c59dbf859e86626b32abcca006535679cbc27e69c3b09e7a78"
        ),
    },
)
_MAX_DEPLOYMENT_RECEIPT_BYTES = 64 * 1024
_MAX_DEPLOYMENT_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_DEPLOYMENT_MANIFEST_ENTRIES = 100_000
_MAX_DEPLOYMENT_ERRORS = 20


def _sealed_file_bytes(
    path: Path,
    *,
    maximum_bytes: int,
) -> tuple[bytes, list[str]]:
    """Read one root-owned, immutable regular file without following links."""

    errors: list[str] = []
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        return b"", [f"cannot securely open {path}: {type(exc).__name__}: {exc}"]
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            errors.append(f"sealed file is not regular: {path}")
        if metadata.st_uid != 0 or metadata.st_gid != 0:
            errors.append(f"sealed file is not owned by root:root: {path}")
        if stat.S_IMODE(metadata.st_mode) & 0o222:
            errors.append(f"sealed file has a writable mode: {path}")
        if metadata.st_nlink != 1:
            errors.append(f"sealed file has an unexpected hard link: {path}")
        if metadata.st_size > maximum_bytes:
            errors.append(
                f"sealed file exceeds the bounded size limit: {path}"
            )
            return b"", errors
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > maximum_bytes:
            errors.append(
                f"sealed file changed beyond the bounded size limit: {path}"
            )
            return b"", errors
        if len(payload) != metadata.st_size:
            errors.append(f"sealed file changed while it was read: {path}")
        return payload, errors
    except OSError as exc:
        return b"", [*errors, f"cannot read {path}: {type(exc).__name__}: {exc}"]
    finally:
        os.close(descriptor)


def _manifest_inventory(
    encoded: bytes,
) -> tuple[dict[str, tuple[str, int, int]], list[str]]:
    """Parse the bounded canonical manifest into path/type/mode/size facts."""

    inventory: dict[str, tuple[str, int, int]] = {}
    errors: list[str] = []
    try:
        text = encoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {}, [f"payload manifest is not UTF-8: {exc}"]
    if not text.endswith("\n"):
        errors.append("payload manifest is not newline terminated")
    lines = text.splitlines()
    if not lines or len(lines) > _MAX_DEPLOYMENT_MANIFEST_ENTRIES:
        errors.append("payload manifest has an invalid bounded entry count")
        return {}, errors
    previous_path = ""
    for index, line in enumerate(lines, start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"payload manifest line {index} is invalid JSON: {exc}")
            break
        if not isinstance(record, dict):
            errors.append(f"payload manifest line {index} is not an object")
            break
        path_value = record.get("path")
        kind = record.get("type")
        mode_value = record.get("mode")
        byte_count = record.get("bytes")
        path = PurePosixPath(path_value) if isinstance(path_value, str) else None
        if (
            path is None
            or path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or path.as_posix() != path_value
        ):
            errors.append(f"payload manifest line {index} has an unsafe path")
            break
        if path_value <= previous_path or path_value in inventory:
            errors.append(
                f"payload manifest line {index} is duplicated or out of order"
            )
            break
        previous_path = path_value
        if kind not in {"file", "directory"}:
            errors.append(f"payload manifest line {index} has an invalid type")
            break
        if (
            not isinstance(mode_value, str)
            or len(mode_value) != 4
            or any(character not in "01234567" for character in mode_value)
        ):
            errors.append(f"payload manifest line {index} has an invalid mode")
            break
        mode = int(mode_value, 8)
        if mode & 0o222:
            errors.append(f"payload manifest line {index} declares a writable mode")
            break
        if isinstance(byte_count, bool) or not isinstance(byte_count, int):
            errors.append(f"payload manifest line {index} has invalid bytes")
            break
        if byte_count < 0 or (kind == "directory" and byte_count != 0):
            errors.append(f"payload manifest line {index} has invalid bytes")
            break
        sha256 = record.get("sha256")
        if kind == "file" and (
            not isinstance(sha256, str)
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
        ):
            errors.append(f"payload manifest line {index} has an invalid SHA-256")
            break
        if kind == "directory" and "sha256" in record:
            errors.append(
                f"payload manifest line {index} hashes a directory unexpectedly"
            )
            break
        inventory[path_value] = (kind, mode, byte_count)
    return inventory, errors


def _sealed_tree_inventory(
    root: Path,
) -> tuple[dict[str, tuple[str, int, int]], list[str]]:
    """Audit immutable tree metadata without trusting manifest path names."""

    inventory: dict[str, tuple[str, int, int]] = {}
    errors: list[str] = []
    try:
        if root.resolve(strict=True) != root:
            errors.append(f"deployment root is not its canonical path: {root}")
        root_metadata = root.lstat()
    except OSError as exc:
        return {}, [f"deployment root is unavailable: {root}: {exc}"]
    if not stat.S_ISDIR(root_metadata.st_mode):
        return {}, [f"deployment root is not a directory: {root}"]
    if root_metadata.st_uid != 0 or root_metadata.st_gid != 0:
        errors.append(f"deployment root is not owned by root:root: {root}")
    if stat.S_IMODE(root_metadata.st_mode) & 0o222:
        errors.append(f"deployment root has a writable mode: {root}")

    pending = [(root, "")]
    while pending:
        directory, relative_directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            errors.append(f"cannot audit deployment directory {directory}: {exc}")
            if len(errors) >= _MAX_DEPLOYMENT_ERRORS:
                break
            continue
        for entry in entries:
            relative = (
                f"{relative_directory}/{entry.name}"
                if relative_directory
                else entry.name
            )
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                errors.append(f"cannot stat deployment path {relative}: {exc}")
                if len(errors) >= _MAX_DEPLOYMENT_ERRORS:
                    break
                continue
            kind = (
                "directory"
                if stat.S_ISDIR(metadata.st_mode)
                else "file"
                if stat.S_ISREG(metadata.st_mode)
                else ""
            )
            if not kind:
                errors.append(
                    f"deployment path is a symlink or nonregular object: {relative}"
                )
            if metadata.st_uid != 0 or metadata.st_gid != 0:
                errors.append(f"deployment path is not root-owned: {relative}")
            mode = stat.S_IMODE(metadata.st_mode)
            if mode & 0o222:
                errors.append(f"deployment path has a writable mode: {relative}")
            if kind == "file" and metadata.st_nlink != 1:
                errors.append(f"deployment file is hard-linked: {relative}")
            if relative not in {"DEPLOYMENT.json", "PAYLOAD_MANIFEST.jsonl"}:
                inventory[relative] = (
                    kind,
                    mode,
                    metadata.st_size if kind == "file" else 0,
                )
            if kind == "directory":
                pending.append((Path(entry.path), relative))
            if len(errors) >= _MAX_DEPLOYMENT_ERRORS:
                break
        if len(errors) >= _MAX_DEPLOYMENT_ERRORS:
            break
    return inventory, errors


def _verify_sealed_validation_deployment(
    deployment: dict[str, object],
) -> dict[str, Any]:
    """Verify one exact immutable deployment and its manifest inventory."""

    name = str(deployment["name"])
    root = deployment["root"]
    if not isinstance(root, Path):
        raise TypeError("sealed deployment root must be a Path")
    expected_receipt_sha256 = str(deployment["receipt_sha256"])
    expected_manifest_sha256 = str(deployment["manifest_sha256"])
    receipt_path = root / "DEPLOYMENT.json"
    manifest_path = root / "PAYLOAD_MANIFEST.jsonl"
    receipt_bytes, receipt_errors = _sealed_file_bytes(
        receipt_path,
        maximum_bytes=_MAX_DEPLOYMENT_RECEIPT_BYTES,
    )
    manifest_bytes, manifest_errors = _sealed_file_bytes(
        manifest_path,
        maximum_bytes=_MAX_DEPLOYMENT_MANIFEST_BYTES,
    )
    errors = [*receipt_errors, *manifest_errors]
    receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if receipt_sha256 != expected_receipt_sha256:
        errors.append(f"{name} deployment receipt SHA-256 does not match")
    if manifest_sha256 != expected_manifest_sha256:
        errors.append(f"{name} payload manifest SHA-256 does not match")

    receipt: dict[str, Any] = {}
    if receipt_bytes:
        try:
            parsed_receipt = json.loads(receipt_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            errors.append(f"{name} deployment receipt is malformed: {exc}")
        else:
            if isinstance(parsed_receipt, dict):
                receipt = parsed_receipt
            else:
                errors.append(f"{name} deployment receipt is not an object")
    if receipt:
        if receipt.get("schema") != deployment["schema"]:
            errors.append(f"{name} deployment receipt schema does not match")
        payload = receipt.get("payload")
        if not isinstance(payload, dict):
            errors.append(f"{name} deployment receipt payload is malformed")
            payload = {}
        if payload.get("manifest_sha256") != expected_manifest_sha256:
            errors.append(f"{name} receipt does not bind the exact manifest")
        if payload.get("manifest_schema") != (
            "canonical-json-lines path/type/mode/bytes/sha256@1"
        ):
            errors.append(f"{name} receipt manifest schema is malformed")
        for field in (
            "symlink_count",
            "nonregular_count",
            "hardlinked_file_count",
        ):
            if payload.get(field) != 0:
                errors.append(f"{name} receipt does not attest zero {field}")
        verification = receipt.get("verification")
        if not isinstance(verification, dict) or verification.get("passed") is not True:
            errors.append(f"{name} deployment receipt is not verified")
    else:
        payload = {}

    manifest_inventory, manifest_parse_errors = _manifest_inventory(manifest_bytes)
    tree_inventory, tree_errors = _sealed_tree_inventory(root)
    errors.extend(manifest_parse_errors)
    errors.extend(tree_errors)
    if manifest_inventory != tree_inventory:
        errors.append(f"{name} deployed tree does not match its exact manifest")
    if payload:
        expected_entries = payload.get("entry_count")
        expected_files = payload.get("file_count")
        expected_directories = payload.get("directory_count")
        expected_bytes = payload.get("bytes")
        actual_files = sum(
            kind == "file" for kind, _mode, _bytes in tree_inventory.values()
        )
        actual_directories = sum(
            kind == "directory" for kind, _mode, _bytes in tree_inventory.values()
        )
        actual_bytes = sum(
            byte_count
            for kind, _mode, byte_count in tree_inventory.values()
            if kind == "file"
        )
        if expected_entries != len(tree_inventory):
            errors.append(f"{name} receipt entry count does not match the tree")
        if expected_files != actual_files:
            errors.append(f"{name} receipt file count does not match the tree")
        if expected_directories != actual_directories:
            errors.append(f"{name} receipt directory count does not match the tree")
        if expected_bytes != actual_bytes:
            errors.append(f"{name} receipt byte count does not match the tree")

    errors = errors[:_MAX_DEPLOYMENT_ERRORS]
    return {
        "name": name,
        "root": str(root),
        "valid": not errors,
        "errors": errors,
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha256,
        "expected_receipt_sha256": expected_receipt_sha256,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "expected_manifest_sha256": expected_manifest_sha256,
        "manifest_entry_count": len(manifest_inventory),
        "tree_entry_count": len(tree_inventory),
    }


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
        "IPFS_ACCELERATE_AGENT_GROK_MODEL": "grok-4.6",
        "IPFS_ACCELERATE_AGENT_CODEX_MODEL": "gpt-5.6-terra",
        "IPFS_ACCELERATE_AGENT_CODEX_REASONING_EFFORT": "medium",
        "IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON": "/usr/bin/python3.12",
        "IPFS_ACCELERATE_AGENT_VALIDATION_PYTHONPATH": str(
            VALIDATION_PYTHON_ROOT / "site-packages"
        ),
        "IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON_MODULES": (
            ",".join(VALIDATION_REQUIRED_MODULES)
        ),
        "IPFS_ACCELERATE_AGENT_VALIDATION_PLAYWRIGHT_BROWSERS_PATH": (
            str(VALIDATION_PLAYWRIGHT_ROOT)
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

    validation_deployments = [
        _verify_sealed_validation_deployment(deployment)
        for deployment in SEALED_VALIDATION_DEPLOYMENTS
    ]
    for deployment in validation_deployments:
        if not deployment["valid"]:
            errors.append(
                "sealed validation deployment is invalid: "
                f"{deployment['name']}: {deployment['errors']}"
            )

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

    required_modules = VALIDATION_REQUIRED_MODULES
    effective_launch_environment = configured_board_launch_environment(
        {
            str(key): str(value)
            for key, value in plan.get("environment", {}).items()
        },
        inherited_environment=os.environ,
    )
    effective_controlled_environment = {
        key: effective_launch_environment.get(key) for key in expected_environment
    }
    if effective_controlled_environment != expected_environment:
        errors.append(
            "effective launch environment does not preserve the sealed "
            "validation contract"
        )
    imports, validation_python_preflight = _probe_python_modules(
        required_modules,
        environment=effective_launch_environment,
    )
    for module in required_modules:
        if not imports[module]:
            errors.append(f"required Python module is missing: {module}")

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
        "sealed_validation_deployments": validation_deployments,
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
