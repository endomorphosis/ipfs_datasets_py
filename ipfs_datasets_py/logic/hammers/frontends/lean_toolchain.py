"""Tag-pinned Lean/lake toolchain resolver for Lean Refactor Arena.

Resolves ``version_info`` Lean tags to elan toolchain binaries::

    {ELAN_HOME}/toolchains/leanprover--lean4---<tag>/bin/{lean,lake}

Pins are tag-specific. This module never consults ``PATH`` ``lean`` / ``lake``,
never runs ``elan which``, and never picks a toolchain by newest mtime.
:class:`~ipfs_datasets_py.logic.hammers.models.EnvironmentLockRecord` is
populated through ``executable_paths``; the record has no
``primary_executable`` field.

Compile workers should invoke :func:`run_lean_process` with the resolved
paths. :class:`~ipfs_datasets_py.logic.hammers.frontends.lean.LeanFrontend`
keeps PATH ``lean --json`` via :func:`run_bounded_process` and is not
made lake-aware here.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import stat
import sys
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    from ipfs_datasets_py.logic.hammers.corpus import compute_content_digest
    from ipfs_datasets_py.logic.hammers.models import EnvironmentLockRecord, ITPKind
    from ipfs_datasets_py.logic.hammers.process_lifecycle import (
        ProcessExecutionResult,
        ProcessKind,
        ProcessLimits,
        get_process_supervisor,
    )
except ImportError:  # script invocation without an installed package
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
    from ipfs_datasets_py.logic.hammers.corpus import compute_content_digest
    from ipfs_datasets_py.logic.hammers.models import EnvironmentLockRecord, ITPKind
    from ipfs_datasets_py.logic.hammers.process_lifecycle import (
        ProcessExecutionResult,
        ProcessKind,
        ProcessLimits,
        get_process_supervisor,
    )


__all__ = [
    "ELAN_TOOLCHAIN_DIRNAME_PREFIX",
    "EXPECTED_UNIQUE_TAGS",
    "FROZEN_WARMUP_SHA256",
    "KERNEL_COMMAND_TEMPLATE",
    "LeanToolchainError",
    "LeanToolchainMissing",
    "LeanToolchainResolver",
    "TagPinnedToolchain",
    "VersionPin",
    "default_elan_home",
    "elan_toolchain_dirname",
    "iter_version_info",
    "normalize_lean_tag",
    "run_lean_process",
]

ELAN_TOOLCHAIN_DIRNAME_PREFIX = "leanprover--lean4---"
KERNEL_COMMAND_TEMPLATE = "{lake} env {lean} --json {source_file}"
FROZEN_WARMUP_SHA256 = "6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804"
EXPECTED_UNIQUE_TAGS: Tuple[str, ...] = (
    "v4.25.0",
    "v4.26.0",
    "v4.27.0",
    "v4.28.0",
    "v4.29.0",
    "v4.29.1",
    "v4.30.0",
    "v4.31.0",
    "v4.32.0",
    "v4.33.0-rc2",
)
WARMUP_N = 15

_FRONTEND_DIR = Path(__file__).resolve().parent
_REPO_ROOT = Path(__file__).resolve().parents[6]
_DEFAULT_WARMUP_JSONL = (
    _REPO_ROOT / "papers" / "completion" / "lean_refactor_arena" / "data" / "benchmark_data_warmup.jsonl"
)
_LEAN_FRONTEND_PATH = _FRONTEND_DIR / "lean.py"

_FORBIDDEN_RESOLVER_CALLS = frozenset(
    {
        "which",
        "find_executable",
        "glob",
        "iglob",
        "rglob",
        "build_environment_lock",
    }
)
_FORBIDDEN_RESOLVER_ATTRS = frozenset({"st_mtime", "st_mtime_ns"})
class LeanToolchainError(RuntimeError):
    """Fail-closed toolchain resolution or lock-construction error."""


class LeanToolchainMissing(LeanToolchainError):
    """The tag-pinned elan ``lean``/``lake`` binaries are not installed."""


@dataclass(frozen=True)
class VersionPin:
    """One JSONL ``version_info`` entry: Lean tag plus the matching git commit."""

    lean_tag: str
    git_commit: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"lean_tag": self.lean_tag, "git_commit": self.git_commit}


@dataclass(frozen=True)
class TagPinnedToolchain:
    """Resolved elan ``lean`` and ``lake`` paths for one Lean tag."""

    lean_tag: str
    git_commit: str
    toolchain_name: str
    elan_home: str
    toolchain_dir: str
    lean_path: str
    lake_path: str
    lean_installed: bool
    lake_installed: bool

    @property
    def installed(self) -> bool:
        return self.lean_installed and self.lake_installed

    @property
    def executable_paths(self) -> Dict[str, str]:
        return {"lean": self.lean_path, "lake": self.lake_path}

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["installed"] = self.installed
        payload["executable_paths"] = self.executable_paths
        return payload


def default_elan_home() -> Path:
    """Return ``ELAN_HOME`` when set, otherwise ``~/.elan``. Never searches PATH."""

    raw = os.environ.get("ELAN_HOME")
    if raw is not None and str(raw).strip():
        return Path(str(raw)).expanduser()
    return Path.home() / ".elan"


def normalize_lean_tag(value: str) -> str:
    """Strip an elan spec down to the JSONL Lean tag (for example ``v4.26.0``)."""

    if not isinstance(value, str) or not value.strip():
        raise LeanToolchainError("lean tag must be a nonempty string")
    text = value.strip()
    if text.startswith(ELAN_TOOLCHAIN_DIRNAME_PREFIX):
        text = text[len(ELAN_TOOLCHAIN_DIRNAME_PREFIX) :]
    elif ":" in text:
        text = text.rsplit(":", 1)[-1]
    text = text.strip()
    if not text:
        raise LeanToolchainError(f"lean tag {value!r} normalized to empty")
    return text


def elan_toolchain_dirname(lean_tag: str) -> str:
    """Elan directory name for ``leanprover/lean4:<tag>``."""

    return f"{ELAN_TOOLCHAIN_DIRNAME_PREFIX}{normalize_lean_tag(lean_tag)}"


def iter_version_info(version_info: Any) -> List[VersionPin]:
    """Parse JSONL ``version_info`` (list of ``{lean_tag: git_commit}`` maps)."""

    if not isinstance(version_info, list):
        raise LeanToolchainError("version_info must be a list of {lean_tag: git_commit} maps")
    pins: List[VersionPin] = []
    for index, item in enumerate(version_info):
        if isinstance(item, dict) and item:
            for tag, commit in item.items():
                if not isinstance(tag, str) or not tag.strip():
                    raise LeanToolchainError(f"version_info[{index}] has an empty lean tag")
                if commit is None:
                    commit_text = ""
                elif isinstance(commit, str):
                    commit_text = commit
                else:
                    raise LeanToolchainError(
                        f"version_info[{index}] git commit must be a string, not {type(commit).__name__}"
                    )
                pins.append(VersionPin(lean_tag=normalize_lean_tag(tag), git_commit=commit_text))
            continue
        if isinstance(item, str) and item.strip():
            pins.append(VersionPin(lean_tag=normalize_lean_tag(item), git_commit=""))
            continue
        raise LeanToolchainError(f"version_info[{index}] is not a {{lean_tag: git_commit}} map")
    if not pins:
        raise LeanToolchainError("version_info is empty")
    return pins


def _is_executable(path: Path) -> bool:
    """Return whether ``path`` is a regular file with an execute bit.

    Uses mode bits rather than ``os.access(X_OK)`` so a tag-pinned binary on
    a ``noexec`` mount is still recognized as present. Running it remains a
    later compile-worker concern.
    """

    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) and bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def run_lean_process(
    command: Sequence[str],
    *,
    timeout: float,
    cwd: Optional[str | Path] = None,
    input_text: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    cancel_event=None,
    lease=None,
    cpu_seconds: Optional[float] = None,
    memory_mb: Optional[int] = None,
) -> ProcessExecutionResult:
    """Run a literal Lean/Lake argv under the shared Hammer lifecycle supervisor.

    Same contract as ``ipfs_datasets_py.logic.modal.lean_runtime.run_lean_process``.
    Imported here so compile workers do not need ``logic.modal`` (that package
    import is heavy and is not required to pin elan paths).
    """

    executable_name = Path(command[0]).name.lower() if command else ""
    kind = ProcessKind.LAKE if executable_name == "lake" else ProcessKind.LEAN
    return get_process_supervisor().run(
        command,
        kind=kind,
        limits=ProcessLimits(
            wall_time_seconds=max(0.001, float(timeout)),
            cpu_seconds=cpu_seconds,
            memory_mb=memory_mb,
        ),
        cwd=cwd,
        input_text=input_text,
        env=env,
        cancel_event=cancel_event,
        lease=lease,
    )


class LeanToolchainResolver:
    """Resolve tag-pinned elan ``lean`` and ``lake`` paths and environment locks."""

    def __init__(self, elan_home: Optional[os.PathLike[str] | str] = None):
        self.elan_home = Path(elan_home) if elan_home is not None else default_elan_home()

    def toolchain_dir(self, lean_tag: str) -> Path:
        return self.elan_home / "toolchains" / elan_toolchain_dirname(lean_tag)

    def resolve_tag(
        self,
        lean_tag: str,
        *,
        git_commit: str = "",
        require_installed: bool = True,
    ) -> TagPinnedToolchain:
        """Return the elan ``lean``/``lake`` paths for ``lean_tag``.

        ``require_installed=True`` (the compile-worker default) fails closed
        when either binary is missing. Paths are still tag-pinned when
        ``require_installed=False``; missing files are a capability gap, not
        a PATH or newest-mtime fallback.
        """

        tag = normalize_lean_tag(lean_tag)
        toolchain_dir = self.toolchain_dir(tag)
        lean_path = toolchain_dir / "bin" / "lean"
        lake_path = toolchain_dir / "bin" / "lake"
        pin = TagPinnedToolchain(
            lean_tag=tag,
            git_commit=git_commit,
            toolchain_name=elan_toolchain_dirname(tag),
            elan_home=str(self.elan_home),
            toolchain_dir=str(toolchain_dir),
            lean_path=str(lean_path),
            lake_path=str(lake_path),
            lean_installed=_is_executable(lean_path),
            lake_installed=_is_executable(lake_path),
        )
        if require_installed and not pin.installed:
            raise LeanToolchainMissing(
                "tag-pinned elan toolchain not installed at "
                f"{toolchain_dir} (lean_tag={tag!r}; never falling back to "
                "PATH lean or newest-mtime toolchain)"
            )
        return pin

    def resolve_version_info(
        self,
        version_info: Any,
        *,
        require_installed: bool = True,
    ) -> List[TagPinnedToolchain]:
        return [
            self.resolve_tag(pin.lean_tag, git_commit=pin.git_commit, require_installed=require_installed)
            for pin in iter_version_info(version_info)
        ]

    def environment_lock(
        self,
        pin: TagPinnedToolchain,
        *,
        kernel_command_template: str = KERNEL_COMMAND_TEMPLATE,
        solver_versions: Optional[Mapping[str, str]] = None,
        os_info: Optional[str] = None,
        container_digest: Optional[str] = None,
        policy_digest: Optional[str] = None,
    ) -> EnvironmentLockRecord:
        """Build :class:`EnvironmentLockRecord` from ``pin.executable_paths``.

        Does not call :func:`build_environment_lock` and does not pass
        ``primary_executable``. The record has no such field.
        """

        if not isinstance(pin, TagPinnedToolchain):
            raise LeanToolchainError("environment_lock requires a TagPinnedToolchain")
        if not kernel_command_template or not str(kernel_command_template).strip():
            raise LeanToolchainError("kernel_command_template must be nonempty")
        executable_paths = dict(pin.executable_paths)
        if executable_paths.keys() != {"lean", "lake"}:
            raise LeanToolchainError("executable_paths must be exactly lean and lake")
        resolved_os = os_info if os_info is not None else platform.platform()
        solvers = dict(solver_versions or {})
        lock_payload = {
            "itp": ITPKind.LEAN.value,
            "itp_version": pin.lean_tag,
            "kernel_command_template": kernel_command_template,
            "solver_versions": solvers,
            "executable_paths": executable_paths,
            "os_info": resolved_os,
            "container_digest": container_digest,
            "policy_digest": policy_digest,
            "lean_tag": pin.lean_tag,
            "git_commit": pin.git_commit,
            "toolchain_name": pin.toolchain_name,
        }
        lock = EnvironmentLockRecord(
            lock_id=compute_content_digest(lock_payload),
            itp=ITPKind.LEAN,
            itp_version=pin.lean_tag,
            kernel_command_template=kernel_command_template,
            solver_versions=solvers,
            executable_paths=executable_paths,
            os_info=resolved_os,
            container_digest=container_digest,
            policy_digest=policy_digest,
        )
        lock.validate()
        if hasattr(lock, "primary_executable"):
            raise LeanToolchainError("EnvironmentLockRecord must not expose primary_executable")
        if "primary_executable" in lock.to_dict():
            raise LeanToolchainError("EnvironmentLockRecord.to_dict() must not include primary_executable")
        return lock


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _function_named(tree: ast.AST, class_name: str, method_name: str) -> Optional[ast.AST]:
    for node in tree.body:  # type: ignore[attr-defined]
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                    return item
    return None


def _collect_calls(node: ast.AST) -> List[str]:
    names: List[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _call_name(child.func)
            if name:
                names.append(name)
    return names


def _string_constants(node: ast.AST) -> List[str]:
    values: List[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            values.append(child.value)
    return values


def audit_lean_frontend_path_json(source: Optional[str] = None) -> Dict[str, Any]:
    """Confirm :class:`LeanFrontend` still uses PATH ``lean --json``."""

    text = _LEAN_FRONTEND_PATH.read_text(encoding="utf-8") if source is None else source
    tree = ast.parse(text)
    snapshot = _function_named(tree, "LeanFrontend", "snapshot_goal")
    capability = _function_named(tree, "LeanFrontend", "capability")
    if snapshot is None or capability is None:
        raise LeanToolchainError("LeanFrontend.snapshot_goal / capability not found")
    snapshot_calls = _collect_calls(snapshot)
    capability_calls = _collect_calls(capability)
    snapshot_strings = _string_constants(snapshot)
    imports_lean_toolchain = "lean_toolchain" in text
    report = {
        "path": str(_LEAN_FRONTEND_PATH),
        "snapshot_calls_run_bounded_process": "run_bounded_process" in snapshot_calls,
        "snapshot_calls_run_lean_process": "run_lean_process" in snapshot_calls,
        "snapshot_argv_has_json_flag": "--json" in snapshot_strings,
        "snapshot_argv_has_lake": "lake" in snapshot_strings,
        "capability_find_executable": "find_executable" in capability_calls,
        "capability_run_bounded_process": "run_bounded_process" in capability_calls,
        "imports_lean_toolchain": imports_lean_toolchain,
        "unchanged_path_lean_json": (
            "run_bounded_process" in snapshot_calls
            and "run_lean_process" not in snapshot_calls
            and "--json" in snapshot_strings
            and "lake" not in snapshot_strings
            and "find_executable" in capability_calls
            and not imports_lean_toolchain
        ),
    }
    return report


def audit_resolver_source(source: Optional[str] = None) -> Dict[str, Any]:
    """Confirm this module never PATH-resolves or newest-mtime-picks Lean."""

    text = Path(__file__).read_text(encoding="utf-8") if source is None else source
    tree = ast.parse(text)
    calls = set(_collect_calls(tree))
    attrs = {
        child.attr
        for child in ast.walk(tree)
        if isinstance(child, ast.Attribute) and isinstance(child.attr, str)
    }
    lock_kwargs: List[List[Optional[str]]] = []
    for child in ast.walk(tree):
        if isinstance(child, ast.Call) and _call_name(child.func) == "EnvironmentLockRecord":
            lock_kwargs.append([keyword.arg for keyword in child.keywords])
    forbidden_calls = sorted(calls & _FORBIDDEN_RESOLVER_CALLS)
    forbidden_attrs = sorted(attrs & _FORBIDDEN_RESOLVER_ATTRS)
    uses_primary_executable = any("primary_executable" in kwargs for kwargs in lock_kwargs)
    uses_executable_paths = any("executable_paths" in kwargs for kwargs in lock_kwargs) and bool(
        lock_kwargs
    )
    return {
        "forbidden_calls": forbidden_calls,
        "forbidden_attrs": forbidden_attrs,
        "environment_lock_kwargs": lock_kwargs,
        "uses_primary_executable_kwarg": uses_primary_executable,
        "uses_executable_paths_kwarg": uses_executable_paths,
        "ok": (
            not forbidden_calls
            and not forbidden_attrs
            and not uses_primary_executable
            and uses_executable_paths
        ),
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_warmup_records(jsonl: Path) -> Tuple[str, int, List[dict]]:
    raw = jsonl.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != FROZEN_WARMUP_SHA256:
        raise LeanToolchainError(f"warmup JSONL hash mismatch: {digest} != {FROZEN_WARMUP_SHA256}")
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    return digest, len(raw), records


def _write_fake_toolchain(elan_home: Path, lean_tag: str) -> Path:
    toolchain_dir = elan_home / "toolchains" / elan_toolchain_dirname(lean_tag)
    bin_dir = toolchain_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ("lean", "lake"):
        path = bin_dir / name
        path.write_text(f"#!/bin/sh\necho fake-{name}-{lean_tag}\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return toolchain_dir


def _synthetic_elan_checks() -> Dict[str, Any]:
    """Prove tag pinning against a private elan home; no live Lean required."""

    with tempfile.TemporaryDirectory(prefix="lra-012-elan-") as tmp:
        elan_home = Path(tmp)
        _write_fake_toolchain(elan_home, "v4.26.0")
        _write_fake_toolchain(elan_home, "v4.32.0")
        resolver = LeanToolchainResolver(elan_home)
        old_path = os.environ.get("PATH")
        os.environ["PATH"] = "/nonexistent-lra-012-no-lean"
        try:
            pin_426 = resolver.resolve_tag(
                "v4.26.0", git_commit="451e5f047bafa010d178856db76c00029bfa4d7f", require_installed=True
            )
            pin_432 = resolver.resolve_tag("v4.32.0", require_installed=True)
            missing_ok = False
            try:
                resolver.resolve_tag("v4.25.0", require_installed=True)
            except LeanToolchainMissing:
                missing_ok = True
            missing_pin = resolver.resolve_tag("v4.25.0", require_installed=False)
            lock = resolver.environment_lock(pin_426, os_info="lra-012-synthetic")
            lock_dict = lock.to_dict()
            field_names = {item.name for item in fields(EnvironmentLockRecord)}
            version_info = [
                {"v4.26.0": "451e5f047bafa010d178856db76c00029bfa4d7f"},
                {"v4.32.0": "c48433678e8fb6306ebcd48453300c8e16058a62"},
            ]
            resolved = resolver.resolve_version_info(version_info, require_installed=True)
        finally:
            if old_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = old_path
        expected_426 = elan_home / "toolchains" / "leanprover--lean4---v4.26.0" / "bin"
        expected_432 = elan_home / "toolchains" / "leanprover--lean4---v4.32.0" / "bin"
        return {
            "elan_home": str(elan_home),
            "v4.26.0": pin_426.to_dict(),
            "v4.32.0": pin_432.to_dict(),
            "missing_v4.25.0_require_installed_raises": missing_ok,
            "missing_v4.25.0_paths": missing_pin.to_dict(),
            "lock_id": lock.lock_id,
            "lock_itp": lock.itp.value,
            "lock_itp_version": lock.itp_version,
            "lock_kernel_command_template": lock.kernel_command_template,
            "lock_executable_paths": lock.executable_paths,
            "lock_has_primary_executable_attr": hasattr(lock, "primary_executable"),
            "lock_dict_has_primary_executable": "primary_executable" in lock_dict,
            "environment_lock_field_names": sorted(field_names),
            "resolved_version_info_tags": [item.lean_tag for item in resolved],
            "tag_pinned_v4_26": pin_426.lean_path == str(expected_426 / "lean")
            and pin_426.lake_path == str(expected_426 / "lake"),
            "tag_pinned_v4_32": pin_432.lean_path == str(expected_432 / "lean")
            and pin_432.lake_path == str(expected_432 / "lake"),
            "did_not_select_v4_32_for_v4_26": "v4.32.0" not in pin_426.lean_path
            and "v4.32.0" not in pin_426.lake_path,
            "ignored_empty_path": pin_426.installed and pin_432.installed,
            "ok": bool(
                missing_ok
                and not missing_pin.installed
                and pin_426.installed
                and pin_432.installed
                and pin_426.lean_path == str(expected_426 / "lean")
                and pin_426.lake_path == str(expected_426 / "lake")
                and pin_432.lean_path == str(expected_432 / "lean")
                and "v4.32.0" not in pin_426.lean_path
                and lock.executable_paths == pin_426.executable_paths
                and lock.executable_paths.keys() == {"lean", "lake"}
                and "primary_executable" not in field_names
                and not hasattr(lock, "primary_executable")
                and "primary_executable" not in lock_dict
                and lock.itp is ITPKind.LEAN
                and lock.itp_version == "v4.26.0"
                and lock.kernel_command_template == KERNEL_COMMAND_TEMPLATE
                and [item.lean_tag for item in resolved] == ["v4.26.0", "v4.32.0"]
            ),
        }


def self_check(jsonl: Optional[Path] = None) -> Dict[str, Any]:
    """Resolve every warm-up ``version_info`` tag; do not compile; do not score."""

    jsonl_path = Path(jsonl) if jsonl is not None else _DEFAULT_WARMUP_JSONL
    digest, n_bytes, records = _load_warmup_records(jsonl_path)
    resolver = LeanToolchainResolver()
    per_record: List[Dict[str, Any]] = []
    unique_tags: List[str] = []
    seen_tags: set[str] = set()
    all_pins_tag_pinned = True
    for record in records:
        pins = resolver.resolve_version_info(record.get("version_info"), require_installed=False)
        lock_views = []
        for pin in pins:
            if pin.lean_tag not in seen_tags:
                seen_tags.add(pin.lean_tag)
                unique_tags.append(pin.lean_tag)
            expected_lean = str(
                Path(pin.elan_home) / "toolchains" / pin.toolchain_name / "bin" / "lean"
            )
            expected_lake = str(
                Path(pin.elan_home) / "toolchains" / pin.toolchain_name / "bin" / "lake"
            )
            tag_pinned = (
                pin.lean_path == expected_lean
                and pin.lake_path == expected_lake
                and pin.toolchain_name == f"{ELAN_TOOLCHAIN_DIRNAME_PREFIX}{pin.lean_tag}"
                and pin.lean_tag in pin.lean_path
                and pin.lean_tag in pin.lake_path
            )
            all_pins_tag_pinned = all_pins_tag_pinned and tag_pinned
            lock = resolver.environment_lock(pin, os_info="lra-012-self-check")
            lock_views.append(
                {
                    "lean_tag": pin.lean_tag,
                    "git_commit": pin.git_commit,
                    "lean_path": pin.lean_path,
                    "lake_path": pin.lake_path,
                    "installed": pin.installed,
                    "tag_pinned": tag_pinned,
                    "lock_id": lock.lock_id,
                    "lock_executable_paths": lock.executable_paths,
                    "lock_has_primary_executable": hasattr(lock, "primary_executable")
                    or "primary_executable" in lock.to_dict(),
                }
            )
        per_record.append(
            {
                "name": record.get("name"),
                "source": record.get("source"),
                "n_toolchains": len(pins),
                "pins": lock_views,
            }
        )
    unique_sorted = tuple(sorted(seen_tags))
    frontend = audit_lean_frontend_path_json()
    resolver_audit = audit_resolver_source()
    synthetic = _synthetic_elan_checks()
    installed_tags = sorted(
        {
            pin["lean_tag"]
            for row in per_record
            for pin in row["pins"]
            if pin["installed"]
        }
    )
    missing_tags = sorted(tag for tag in unique_sorted if tag not in set(installed_tags))
    lock_fields = {item.name for item in fields(EnvironmentLockRecord)}
    report: Dict[str, Any] = {
        "ok": False,
        "arena_score": None,
        "compiled": False,
        "lake": False,
        "llama_server_started": False,
        "frozen_warmup_sha256": digest,
        "jsonl_bytes": n_bytes,
        "jsonl_unchanged": digest == FROZEN_WARMUP_SHA256,
        "n_records": len(records),
        "n_version_pins": sum(row["n_toolchains"] for row in per_record),
        "unique_tags": list(unique_sorted),
        "expected_unique_tags": list(EXPECTED_UNIQUE_TAGS),
        "unique_tags_match": unique_sorted == EXPECTED_UNIQUE_TAGS,
        "all_pins_tag_pinned": all_pins_tag_pinned,
        "installed_tags_in_default_elan_home": installed_tags,
        "missing_tags_in_default_elan_home": missing_tags,
        "default_elan_home": str(resolver.elan_home),
        "validation_home": str(Path.home()),
        "elan_home_env": os.environ.get("ELAN_HOME"),
        "path": os.environ.get("PATH"),
        "capability_gap": (
            "No tag-pinned elan lean/lake binaries are installed under the "
            "resolver elan home. Paths are still tag-pinned; this is not "
            "PATH lean usability and is not a lake compile."
            if missing_tags and not installed_tags
            else ""
        ),
        "environment_lock_fields": sorted(lock_fields),
        "environment_lock_has_primary_executable": "primary_executable" in lock_fields,
        "environment_lock_has_executable_paths": "executable_paths" in lock_fields,
        "any_lock_used_primary_executable": any(
            pin["lock_has_primary_executable"] for row in per_record for pin in row["pins"]
        ),
        "run_lean_process_exported": run_lean_process is not None and callable(run_lean_process),
        "lean_frontend": frontend,
        "resolver_audit": resolver_audit,
        "synthetic_elan": synthetic,
        "records": per_record,
        "warmup_path": str(jsonl_path),
    }
    report["ok"] = bool(
        report["n_records"] == WARMUP_N
        and report["jsonl_unchanged"]
        and report["unique_tags_match"]
        and report["all_pins_tag_pinned"]
        and not report["environment_lock_has_primary_executable"]
        and report["environment_lock_has_executable_paths"]
        and not report["any_lock_used_primary_executable"]
        and frontend["unchanged_path_lean_json"]
        and resolver_audit["ok"]
        and synthetic["ok"]
        and report["run_lean_process_exported"]
        and report["compiled"] is False
        and report["lake"] is False
        and report["arena_score"] is None
        and not report["llama_server_started"]
    )
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="resolve every warm-up version_info tag; no lake compile",
    )
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=None,
        help="warmup JSONL path (default: frozen data/benchmark_data_warmup.jsonl)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.self_check or argv is None or list(argv or []) == []:
        report = self_check(args.jsonl)
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0 if report["ok"] else 1
    parser.error("choose --self-check")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
