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
_MODULE_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_MAX_CONTROLLER_DEPLOYMENT_ENTRIES = 10_000


class PairedAcceleratorBootstrapError(RuntimeError):
    """The paired accelerator source cannot be proven before import."""


@dataclass(frozen=True)
class PairedAcceleratorBinding:
    root: Path
    revision: str
    controller_pythonpath: tuple[Path, ...] = ()


@dataclass(frozen=True)
class ControllerRuntimeDeployment:
    pythonpath: Path
    receipt_path: Path
    receipt_sha256: str


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


def _attest_controller_deployment(
    deployment: ControllerRuntimeDeployment,
) -> None:
    pythonpath = deployment.pythonpath
    receipt_path = deployment.receipt_path
    if not pythonpath.is_absolute() or not receipt_path.is_absolute():
        raise PairedAcceleratorBootstrapError(
            "controller runtime paths must be absolute"
        )
    try:
        resolved_pythonpath = pythonpath.resolve(strict=True)
        resolved_receipt = receipt_path.resolve(strict=True)
    except OSError as exc:
        raise PairedAcceleratorBootstrapError(
            "controller runtime deployment is unavailable"
        ) from exc
    if resolved_pythonpath != pythonpath or resolved_receipt != receipt_path:
        raise PairedAcceleratorBootstrapError(
            "controller runtime paths must be canonical and symlink-free"
        )
    if (
        not pythonpath.is_dir()
        or not receipt_path.is_file()
        or receipt_path.name != "DEPLOYMENT.json"
        or receipt_path.parent != pythonpath.parent
    ):
        raise PairedAcceleratorBootstrapError(
            "controller runtime deployment layout is not canonical"
        )
    if re.fullmatch(r"[0-9a-f]{64}", deployment.receipt_sha256) is None:
        raise PairedAcceleratorBootstrapError(
            "controller runtime receipt digest is malformed"
        )
    try:
        receipt_bytes = receipt_path.read_bytes()
    except OSError as exc:
        raise PairedAcceleratorBootstrapError(
            "controller runtime receipt is unreadable"
        ) from exc
    if hashlib.sha256(receipt_bytes).hexdigest() != deployment.receipt_sha256:
        raise PairedAcceleratorBootstrapError(
            "controller runtime receipt digest does not match"
        )
    try:
        receipt = json.loads(
            receipt_bytes.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except PairedAcceleratorBootstrapError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PairedAcceleratorBootstrapError(
            "controller runtime receipt is not canonical JSON"
        ) from exc
    if (
        not isinstance(receipt, Mapping)
        or receipt.get("schema")
        != "ipfs-accelerate/controller-python-deployment@1"
        or receipt.get("manifest_order") != "UTF-8 relative path ascending"
        or receipt.get("excluded") != ["**/__pycache__/**", "**/*.pyc"]
        or not isinstance(receipt.get("file_count"), int)
        or isinstance(receipt.get("file_count"), bool)
        or not isinstance(receipt.get("byte_count"), int)
        or isinstance(receipt.get("byte_count"), bool)
        or re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("manifest_sha256", "")))
        is None
    ):
        raise PairedAcceleratorBootstrapError(
            "controller runtime receipt fields are not canonical"
        )
    try:
        top_level_names = {item.name for item in receipt_path.parent.iterdir()}
    except OSError as exc:
        raise PairedAcceleratorBootstrapError(
            "controller runtime deployment cannot be enumerated"
        ) from exc
    if top_level_names != {"DEPLOYMENT.json", pythonpath.name}:
        raise PairedAcceleratorBootstrapError(
            "controller runtime deployment contains unexpected top-level content"
        )

    inspected = 0
    manifest_records: list[tuple[str, int, str]] = []
    stack = [receipt_path.parent]
    while stack:
        current = stack.pop()
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise PairedAcceleratorBootstrapError(
                "controller runtime deployment cannot be inspected"
            ) from exc
        inspected += 1
        if inspected > _MAX_CONTROLLER_DEPLOYMENT_ENTRIES:
            raise PairedAcceleratorBootstrapError(
                "controller runtime deployment exceeds its entry bound"
            )
        if (
            stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or os.access(current, os.W_OK)
        ):
            raise PairedAcceleratorBootstrapError(
                "controller runtime deployment is not root-owned and read-only"
            )
        if stat.S_ISDIR(metadata.st_mode):
            try:
                with os.scandir(current) as entries:
                    stack.extend(Path(entry.path) for entry in entries)
            except OSError as exc:
                raise PairedAcceleratorBootstrapError(
                    "controller runtime deployment cannot be enumerated"
                ) from exc
        elif not stat.S_ISREG(metadata.st_mode):
            raise PairedAcceleratorBootstrapError(
                "controller runtime deployment contains an unsupported node"
            )
        elif current != receipt_path and pythonpath in current.parents:
            try:
                content = current.read_bytes()
            except OSError as exc:
                raise PairedAcceleratorBootstrapError(
                    "controller runtime payload is unreadable"
                ) from exc
            manifest_records.append(
                (
                    current.relative_to(pythonpath).as_posix(),
                    len(content),
                    hashlib.sha256(content).hexdigest(),
                )
            )

    manifest_records.sort()
    manifest_bytes = "".join(
        f"{digest}  {relative}\n"
        for relative, _size, digest in manifest_records
    ).encode("utf-8")
    if (
        len(manifest_records) != receipt.get("file_count")
        or sum(size for _relative, size, _digest in manifest_records)
        != receipt.get("byte_count")
        or hashlib.sha256(manifest_bytes).hexdigest()
        != receipt.get("manifest_sha256")
    ):
        raise PairedAcceleratorBootstrapError(
            "controller runtime payload does not match its receipt manifest"
        )


def _controller_runtime_from_payload(
    payload: Mapping[str, Any],
) -> tuple[tuple[ControllerRuntimeDeployment, ...], tuple[str, ...]]:
    raw = payload.get("controller_runtime")
    if raw is None:
        return (), ()
    if not isinstance(raw, Mapping) or set(raw) != {
        "deployments",
        "required_modules",
    }:
        raise PairedAcceleratorBootstrapError(
            "controller_runtime must contain exactly deployments and required_modules"
        )
    raw_deployments = raw.get("deployments")
    raw_modules = raw.get("required_modules")
    if not isinstance(raw_deployments, list) or not raw_deployments:
        raise PairedAcceleratorBootstrapError(
            "controller_runtime.deployments must be a nonempty list"
        )
    if not isinstance(raw_modules, list) or not raw_modules:
        raise PairedAcceleratorBootstrapError(
            "controller_runtime.required_modules must be a nonempty list"
        )

    deployments: list[ControllerRuntimeDeployment] = []
    for raw_deployment in raw_deployments:
        if not isinstance(raw_deployment, Mapping) or set(raw_deployment) != {
            "pythonpath",
            "receipt_path",
            "receipt_sha256",
        }:
            raise PairedAcceleratorBootstrapError(
                "controller runtime deployment fields are not canonical"
            )
        values = tuple(
            raw_deployment.get(field)
            for field in ("pythonpath", "receipt_path", "receipt_sha256")
        )
        if not all(
            isinstance(value, str)
            and value
            and not any(character in value for character in "\x00\r\n")
            for value in values
        ):
            raise PairedAcceleratorBootstrapError(
                "controller runtime deployment values are malformed"
            )
        deployment = ControllerRuntimeDeployment(
            pythonpath=Path(values[0]),
            receipt_path=Path(values[1]),
            receipt_sha256=values[2],
        )
        if deployment.pythonpath in {
            existing.pythonpath for existing in deployments
        }:
            raise PairedAcceleratorBootstrapError(
                "controller runtime deployment is duplicated"
            )
        _attest_controller_deployment(deployment)
        deployments.append(deployment)

    modules: list[str] = []
    for value in raw_modules:
        if (
            not isinstance(value, str)
            or _MODULE_PATTERN.fullmatch(value) is None
            or value in modules
        ):
            raise PairedAcceleratorBootstrapError(
                "controller runtime required modules are malformed"
            )
        top_level = value.split(".", 1)[0]
        if not any(
            (deployment.pythonpath / top_level).is_dir()
            or (deployment.pythonpath / f"{top_level}.py").is_file()
            or any(deployment.pythonpath.glob(f"{top_level}.*.so"))
            for deployment in deployments
        ):
            raise PairedAcceleratorBootstrapError(
                f"controller runtime module is absent: {value}"
            )
        modules.append(value)
    return tuple(deployments), tuple(modules)


def _append_controller_import_roots(roots: Sequence[Path]) -> None:
    rendered = [str(root) for root in roots]
    sys.path[:] = [item for item in sys.path if item not in rendered]
    sys.path.extend(rendered)


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


def _load_control_payload(root: Path) -> Mapping[str, Any]:
    relative_config = PAIRED_CONFIG_RELATIVE.as_posix()
    config_path = (root / PAIRED_CONFIG_RELATIVE).resolve()
    _git(root, "ls-files", "--error-unmatch", "--", relative_config)
    try:
        config_bytes = config_path.read_bytes()
    except OSError as exc:
        raise PairedAcceleratorBootstrapError(
            "scheduler config is unreadable"
        ) from exc
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
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
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
    return payload


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
    payload = _load_control_payload(root)
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
    controller_deployments, _ = _controller_runtime_from_payload(payload)
    binding = PairedAcceleratorBinding(
        paired_root,
        revision,
        tuple(deployment.pythonpath for deployment in controller_deployments),
    )
    _prepend_import_root(binding.root)
    _append_controller_import_roots(binding.controller_pythonpath)
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
    payload = _load_control_payload(control_root)
    source_binding = payload.get("source_binding")
    paired = (
        source_binding.get("paired_accelerator")
        if isinstance(source_binding, Mapping)
        else None
    )
    if not isinstance(paired, Mapping):
        raise PairedAcceleratorBootstrapError(
            "child control config has no paired accelerator binding"
        )
    expected_revision = paired.get("required_revision")
    expected = (control_root.parent / "ipfs_accelerate_py").resolve()
    if (
        paired.get("repository_name") != "ipfs_accelerate_py"
        or paired.get("sibling_path") != "../ipfs_accelerate_py"
        or paired.get("require_clean_worktree") is not True
        or paired.get("require_exact_revision") is not True
        or not isinstance(expected_revision, str)
        or root != expected
    ):
        raise PairedAcceleratorBootstrapError(
            "child paired accelerator binding does not match the control config"
        )
    if revision != expected_revision:
        raise PairedAcceleratorBootstrapError(
            "child paired accelerator revision does not match the control config"
        )
    _attest_checkout(root, revision)
    controller_deployments, _ = _controller_runtime_from_payload(payload)
    binding = PairedAcceleratorBinding(
        root,
        revision,
        tuple(deployment.pythonpath for deployment in controller_deployments),
    )
    _prepend_import_root(binding.root)
    _append_controller_import_roots(binding.controller_pythonpath)
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
