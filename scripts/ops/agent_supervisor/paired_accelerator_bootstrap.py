"""Stdlib-only bootstrap for an exact paired ``ipfs_accelerate_py`` checkout.

This module must run before importing ``ipfs_accelerate_py``.  It binds the
configured-board launcher and its detached implementation children to the
same clean sibling worktree and full commit recorded by the board config.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ATTESTATION_REQUIRED_ENV = "IPFS_ACCELERATE_PAIRED_ATTESTATION_REQUIRED"
PAIRED_ROOT_ENV = "IPFS_ACCELERATE_PAIRED_ROOT"
PAIRED_REVISION_ENV = "IPFS_ACCELERATE_PAIRED_REVISION"
PAIRED_CONTROL_ROOT_ENV = "IPFS_ACCELERATE_PAIRED_CONTROL_ROOT"
GIT_BINARY = Path("/usr/bin/git")
PAIRED_CONFIG_RELATIVE = Path(
    "config/agent_supervisor_legal_corpora_reindex_scheduler.json"
)


class PairedAcceleratorBootstrapError(RuntimeError):
    """The paired accelerator source cannot be proven before import."""


@dataclass(frozen=True)
class PairedAcceleratorBinding:
    root: Path
    revision: str


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PairedAcceleratorBootstrapError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _argument(argv: Sequence[str], name: str) -> str | None:
    prefix = f"{name}="
    found: list[str] = []
    for index, value in enumerate(argv):
        option = value.split("=", 1)[0]
        if option.startswith("--") and option != name and name.startswith(option):
            raise PairedAcceleratorBootstrapError(
                f"{name} must not use an abbreviated option"
            )
        if value.startswith(prefix):
            found.append(value[len(prefix) :])
        if value == name:
            if index + 1 >= len(argv):
                raise PairedAcceleratorBootstrapError(f"{name} has no value")
            found.append(argv[index + 1])
    if len(found) > 1:
        raise PairedAcceleratorBootstrapError(f"{name} is duplicated")
    return found[0] if found else None


def _trusted_git_binary() -> Path:
    try:
        resolved = GIT_BINARY.resolve(strict=True)
        stat_result = resolved.stat()
    except OSError as exc:
        raise PairedAcceleratorBootstrapError("trusted Git binary is absent") from exc
    if not resolved.is_file() or stat_result.st_uid != 0 or stat_result.st_mode & 0o022:
        raise PairedAcceleratorBootstrapError("trusted Git binary is mutable")
    return resolved


def _git_environment() -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": "/nonexistent",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
    }


def _git_bytes(root: Path, *arguments: str) -> bytes:
    git_binary = _trusted_git_binary()
    command = [
        str(git_binary),
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
        *arguments,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            env=_git_environment(),
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PairedAcceleratorBootstrapError(
            f"paired Git inspection failed: {type(exc).__name__}"
        ) from exc
    if result.returncode != 0:
        raise PairedAcceleratorBootstrapError(
            f"paired Git inspection failed: {arguments[0] if arguments else 'git'}"
        )
    return result.stdout


def _git(root: Path, *arguments: str) -> str:
    try:
        return _git_bytes(root, *arguments).decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise PairedAcceleratorBootstrapError(
            f"paired Git inspection failed: {type(exc).__name__}"
        ) from exc


def _gitlink_is_populated(path: Path) -> bool:
    try:
        if path.is_symlink() or path.is_file():
            return True
        with os.scandir(path) as entries:
            return next(entries, None) is not None
    except FileNotFoundError:
        return False
    except (NotADirectoryError, OSError):
        return True


def _attest_checkout(root: Path, revision: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise PairedAcceleratorBootstrapError(
            "paired revision must be a full lowercase commit"
        )
    if not root.is_dir():
        raise PairedAcceleratorBootstrapError("paired accelerator root is absent")
    top = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    if top != root:
        raise PairedAcceleratorBootstrapError(
            "paired accelerator root is not the exact Git worktree"
        )
    if _git(root, "rev-parse", "HEAD") != revision:
        raise PairedAcceleratorBootstrapError(
            "paired accelerator HEAD does not match the sealed revision"
        )
    gitlink = _git_bytes(root, "ls-tree", "-z", "HEAD", "--", "ipfs_datasets_py")
    for record in gitlink.rstrip(b"\0").split(b"\0") if gitlink else ():
        metadata, separator, path_bytes = record.partition(b"\t")
        fields = metadata.split()
        if (
            separator
            and path_bytes == b"ipfs_datasets_py"
            and fields[:2] == [b"160000", b"commit"]
            and _gitlink_is_populated(root / "ipfs_datasets_py")
        ):
            raise PairedAcceleratorBootstrapError(
                "paired accelerator dataset gitlink must remain unpopulated"
            )
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise PairedAcceleratorBootstrapError(
            "paired accelerator worktree is not clean"
        )
    index_records = _git_bytes(
        root,
        "ls-files",
        "-v",
        "-z",
        "--",
        "ipfs_accelerate_py",
    ).rstrip(b"\0")
    if not index_records or any(
        not record.startswith(b"H ") for record in index_records.split(b"\0")
    ):
        raise PairedAcceleratorBootstrapError(
            "paired accelerator package has non-default index flags"
        )
    tree = _git_bytes(
        root,
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        "HEAD",
        "--",
        "ipfs_accelerate_py",
    )
    tree_records = tree.rstrip(b"\0").split(b"\0") if tree else ()
    if not tree_records:
        raise PairedAcceleratorBootstrapError(
            "paired accelerator package has no tracked payload"
        )
    for record in tree_records:
        metadata, separator, path_bytes = record.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise PairedAcceleratorBootstrapError(
                "paired accelerator package tree is not canonical"
            )
        mode, object_type, expected_digest = fields
        relative = Path(os.fsdecode(path_bytes))
        try:
            relative.relative_to("ipfs_accelerate_py")
        except ValueError as exc:
            raise PairedAcceleratorBootstrapError(
                "paired accelerator package tree is not canonical"
            ) from exc
        if mode == b"160000" and object_type == b"commit":
            if _gitlink_is_populated(root / relative):
                raise PairedAcceleratorBootstrapError(
                    "paired accelerator package gitlink must remain unpopulated"
                )
            continue
        if object_type != b"blob":
            raise PairedAcceleratorBootstrapError(
                "paired accelerator package tree is not canonical"
            )
        try:
            payload_path = root / relative
            payload_stat = payload_path.lstat()
            if mode == b"120000":
                if not stat.S_ISLNK(payload_stat.st_mode):
                    raise OSError("tracked symlink is absent")
                payload = os.fsencode(os.readlink(payload_path))
            elif mode in {b"100644", b"100755"}:
                if not stat.S_ISREG(payload_stat.st_mode):
                    raise OSError("tracked file is absent")
                payload = payload_path.read_bytes()
                executable = bool(payload_stat.st_mode & stat.S_IXUSR)
                if executable != (mode == b"100755"):
                    raise OSError("tracked executable mode differs")
            else:
                raise OSError("tracked mode is unsupported")
        except (OSError, ValueError) as exc:
            raise PairedAcceleratorBootstrapError(
                "paired accelerator package payload is not canonical"
            ) from exc
        digest = hashlib.sha1(
            f"blob {len(payload)}\0".encode("ascii") + payload,
            usedforsecurity=False,
        ).hexdigest()
        if digest.encode("ascii") != expected_digest:
            raise PairedAcceleratorBootstrapError(
                "paired accelerator package payload does not match HEAD"
            )
    if _git(
        root,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
        "--",
        "ipfs_accelerate_py",
    ):
        raise PairedAcceleratorBootstrapError(
            "paired accelerator package contains ignored executable content"
        )


def _prepend_import_root(root: Path) -> None:
    text = str(root)
    sys.path[:] = [item for item in sys.path if item != text]
    sys.path.insert(0, text)


def _install_child_binding(
    binding: PairedAcceleratorBinding,
    control_root: Path,
) -> None:
    for name in tuple(os.environ):
        if name.startswith(("PYTHON", "GIT_")):
            os.environ.pop(name, None)
    os.environ[ATTESTATION_REQUIRED_ENV] = "1"
    os.environ[PAIRED_ROOT_ENV] = str(binding.root)
    os.environ[PAIRED_REVISION_ENV] = binding.revision
    os.environ[PAIRED_CONTROL_ROOT_ENV] = str(control_root.resolve())
    os.environ["IPFS_ACCELERATE_ROOT"] = str(binding.root)
    os.environ["PYTHONPATH"] = str(binding.root)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True


def bootstrap_from_config_argv(
    repository_root: Path,
    argv: Sequence[str],
) -> PairedAcceleratorBinding | None:
    """Load and enforce an optional paired binding before package import."""

    root = repository_root.resolve()
    configured_root = _argument(argv, "--repo-root")
    if configured_root is not None and Path(configured_root).resolve() != root:
        raise PairedAcceleratorBootstrapError(
            "configured repository root does not match the launcher checkout"
        )
    config_value = _argument(argv, "--config")
    if config_value is None:
        return None
    config_path = Path(config_value)
    if not config_path.is_absolute():
        config_path = root / config_path
    config_path = config_path.resolve()
    try:
        config_path.relative_to(root)
    except ValueError as exc:
        raise PairedAcceleratorBootstrapError(
            "scheduler config is outside the launcher checkout"
        ) from exc
    if config_path != (root / PAIRED_CONFIG_RELATIVE).resolve():
        raise PairedAcceleratorBootstrapError(
            "paired scheduler requires the canonical legal-corpora config"
        )
    relative_config = PAIRED_CONFIG_RELATIVE.as_posix()
    _git(root, "ls-files", "--error-unmatch", "--", relative_config)
    try:
        config_bytes = config_path.read_bytes()
    except OSError as exc:
        raise PairedAcceleratorBootstrapError("scheduler config is unreadable") from exc
    if config_bytes != _git_bytes(root, "show", f"HEAD:{relative_config}"):
        raise PairedAcceleratorBootstrapError(
            "scheduler config does not match the exact HEAD blob"
        )
    try:
        payload = json.loads(
            config_bytes.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except PairedAcceleratorBootstrapError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PairedAcceleratorBootstrapError(
            f"scheduler config is unreadable: {type(exc).__name__}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise PairedAcceleratorBootstrapError("scheduler config must be an object")
    if payload.get("schema") != (
        "ipfs_accelerate_py.agent_supervisor.legal_corpora_reindex.scheduler_config@1"
    ):
        raise PairedAcceleratorBootstrapError(
            "scheduler config schema is not canonical"
        )
    source_binding = payload.get("source_binding")
    if not isinstance(source_binding, Mapping):
        return None
    paired = source_binding.get("paired_accelerator")
    if paired is None:
        return None
    if not isinstance(paired, Mapping):
        raise PairedAcceleratorBootstrapError("paired_accelerator must be an object")
    repository_name = paired.get("repository_name")
    sibling_path = paired.get("sibling_path")
    revision = paired.get("required_revision")
    if (
        repository_name != "ipfs_accelerate_py"
        or sibling_path != f"../{repository_name}"
        or paired.get("require_clean_worktree") is not True
        or paired.get("require_exact_revision") is not True
        or not isinstance(revision, str)
    ):
        raise PairedAcceleratorBootstrapError(
            "paired accelerator contract is incomplete or unsafe"
        )
    paired_root = (root / sibling_path).resolve()
    if paired_root != (root.parent / repository_name).resolve():
        raise PairedAcceleratorBootstrapError(
            "paired accelerator does not occupy the exact sibling slot"
        )
    _attest_checkout(paired_root, revision)
    binding = PairedAcceleratorBinding(paired_root, revision)
    _prepend_import_root(binding.root)
    _install_child_binding(binding, root)
    return binding


def bootstrap_from_environment(
    repository_root: Path,
) -> PairedAcceleratorBinding | None:
    """Re-attest a parent-provided binding in a detached child process."""

    if os.environ.get(ATTESTATION_REQUIRED_ENV) != "1":
        return None
    root_value = os.environ.get(PAIRED_ROOT_ENV, "")
    revision = os.environ.get(PAIRED_REVISION_ENV, "")
    root = Path(root_value).resolve()
    control_root = repository_root.resolve()
    control_value = os.environ.get(PAIRED_CONTROL_ROOT_ENV, "")
    if not control_value or Path(control_value).resolve() != control_root:
        raise PairedAcceleratorBootstrapError(
            "child control root does not match the initial launcher checkout"
        )
    expected = (control_root.parent / "ipfs_accelerate_py").resolve()
    if root != expected:
        raise PairedAcceleratorBootstrapError(
            "child paired accelerator root is not the exact sibling"
        )
    _attest_checkout(root, revision)
    binding = PairedAcceleratorBinding(root, revision)
    _prepend_import_root(binding.root)
    _install_child_binding(binding, control_root)
    return binding


def attest_imported_module(
    binding: PairedAcceleratorBinding | None,
    module_file: str,
    *,
    expected_relative: str,
) -> None:
    """Recheck checkout state and the exact module origin after import."""

    if binding is None:
        return
    _attest_checkout(binding.root, binding.revision)
    expected = (binding.root / expected_relative).resolve()
    actual = Path(module_file).resolve()
    if actual != expected:
        raise PairedAcceleratorBootstrapError(
            "imported accelerator module does not match the paired checkout"
        )


__all__ = (
    "ATTESTATION_REQUIRED_ENV",
    "PAIRED_CONTROL_ROOT_ENV",
    "PAIRED_REVISION_ENV",
    "PAIRED_ROOT_ENV",
    "PairedAcceleratorBinding",
    "PairedAcceleratorBootstrapError",
    "attest_imported_module",
    "bootstrap_from_config_argv",
    "bootstrap_from_environment",
)
