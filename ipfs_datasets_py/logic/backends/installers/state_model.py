"""TLC + Apalache state-model installer plugin (FVT-G120 / FVT-042).

``FormalVerificationInstallerPlugin@1`` for the TLA state-model lane:

* ``ensure_tlc`` — pinned TLC / TLA+ tools 1.8.0 (``tla2tools.jar``)
* ``ensure_apalache`` — pinned Apalache 0.58.3 symbolic model checker
* Java remains a **host support runtime only** (never installed by this plugin
  and never granted state-model authority by itself)
* TLC requires Java 11+ and Apalache requires Java 17+; callers may select a
  runtime explicitly instead of relying on the process-wide ``PATH``

Fail-closed installation contract
---------------------------------
* never installs on import or capability discovery;
* requires an explicit ``ensure_*`` call with ``yes=True``;
* user-local installs only (no system package manager mutation);
* managed artifacts require reviewed checksum verification before use,
  including TLC's immutable 1.8.0 jar digest;
* under ``strict=True``, only the locked pin versions are accepted:
  TLC ``1.8.0`` and Apalache ``0.58.3``;
* Java presence alone never promotes the TLA lane;
* bounded model-checking never promotes to theorem authority;
* this plugin never edits the shared multi-prover certificate or lock.

Pin selection reads ``config/formal_verification_toolchains.lock.json`` when
available and falls back to the reviewed inventory below.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import zipfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any, Final
from urllib.request import Request, urlopen

from .registry import (
    DEFAULT_LOCK_RELATIVE,
    DEFAULT_USER_LOCAL_INSTALL_ROOT,
    InstallerPluginFamily,
    InstallerRegistryError,
    authorize_installer_entry_install,
    default_installer_registry,
    get_installer_entry,
)

PLUGIN_INTERFACE: Final = "FormalVerificationInstallerPlugin@1"
PLUGIN_FAMILY: Final = InstallerPluginFamily.STATE_MODEL.value
PLUGIN_MODULE: Final = "ipfs_datasets_py.logic.backends.installers.state_model"
GOAL_ID: Final = "FVT-G120"
TASK_ID: Final = "FVT-042"
PROGRAM: Final = "formal-verification-tactician/state-model-toolchains"

# Locked managed-pin versions (must match deployment lock).
TLC_VERSION: Final = "1.8.0"
APALACHE_VERSION: Final = "0.58.3"
TLC_SHA256: Final = (
    "e22f8ffb4bacdea0a871f444dd94fe5fb0d8013b3388ae39e82e26f852c735d5"
)
APALACHE_SHA256: Final = (
    "ba622db9538aebf942cc7a7815f942a6b2b419012707e16dfdc25a73ff95d0a5"
)

TLC_EXECUTABLE: Final = "tlc"
TLC_JAR_NAME: Final = "tla2tools.jar"
APALACHE_EXECUTABLE: Final = "apalache-mc"
JAVA_EXECUTABLE: Final = "java"
JAVA_EXECUTABLE_ENV: Final = "IPFS_DATASETS_PY_JAVA_EXECUTABLE"
TLC_MIN_JAVA_MAJOR: Final = 11
APALACHE_MIN_JAVA_MAJOR: Final = 17
JAVA_OPTION_ENV_VARS: Final = (
    "JAVA_TOOL_OPTIONS",
    "_JAVA_OPTIONS",
    "JDK_JAVA_OPTIONS",
)

# Reviewed fallback pins when the lock file is unavailable (tests / offline).
_FALLBACK_PINS: Final[dict[str, tuple[dict[str, Any], ...]]] = {
    "tlc": (
        {
            "tool_id": "tlc",
            "version": TLC_VERSION,
            "platform": "any",
            "artifact_url": (
                "https://github.com/tlaplus/tlaplus/releases/download/"
                f"v{TLC_VERSION}/tla2tools.jar"
            ),
            "sha256": TLC_SHA256,
            "identity_kind": "immutable_release_tag",
            "is_checksummed": True,
            "requires_checksum_at_install": True,
        },
    ),
    "apalache": (
        {
            "tool_id": "apalache",
            "version": APALACHE_VERSION,
            "platform": "any",
            "artifact_url": (
                "https://github.com/apalache-mc/apalache/releases/download/"
                f"v{APALACHE_VERSION}/apalache-{APALACHE_VERSION}.tgz"
            ),
            "sha256": APALACHE_SHA256,
            "identity_kind": "release_archive",
            "is_checksummed": True,
            "requires_checksum_at_install": True,
        },
    ),
}

LOCKED_VERSIONS: Final[Mapping[str, str]] = {
    "tlc": TLC_VERSION,
    "apalache": APALACHE_VERSION,
}

ProgressCallback = Callable[[str, str], None]

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)+)")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_JAVA_VERSION_RE = re.compile(
    r'(?im)^\s*(?:openjdk|java)\s+version\s+"'
    r'(?P<version>\d+(?:[._+\-][^"]*)?)"'
)
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_TLC_HELP_MARKERS: Final = (
    "TLC - provides model checking and simulation of TLA+ specifications",
    "SYNOPSIS",
    "DESCRIPTION",
)
_MANIFEST_SCHEMA: Final = "state-model-managed-runtime/v1"
_ROOT_LOCKS: dict[str, threading.RLock] = {}
_ROOT_LOCKS_GUARD = threading.Lock()


class StateModelInstallerError(RuntimeError):
    """Raised when a strict TLC/Apalache install policy is violated."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolPin:
    """One managed pin for a state-model-lane tool."""

    tool_id: str
    version: str
    platform: str
    artifact_url: str
    sha256: str = ""
    identity_kind: str = "release_archive"
    is_checksummed: bool = False
    requires_checksum_at_install: bool = True

    def __post_init__(self) -> None:
        for name in ("tool_id", "version", "platform", "artifact_url"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise StateModelInstallerError(
                    f"{name} must be a non-empty trimmed string"
                )
        digest = (self.sha256 or "").lower()
        if digest and not _HEX64.match(digest):
            raise StateModelInstallerError(
                f"sha256 for {self.tool_id!r} must be empty or a 64-char hex digest"
            )
        object.__setattr__(self, "sha256", digest)
        if self.is_checksummed and not digest:
            raise StateModelInstallerError(
                f"checksummed pin for {self.tool_id!r} requires a sha256 digest"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "version": self.version,
            "platform": self.platform,
            "artifact_url": self.artifact_url,
            "sha256": self.sha256,
            "identity_kind": self.identity_kind,
            "is_checksummed": self.is_checksummed,
            "requires_checksum_at_install": self.requires_checksum_at_install,
        }


@dataclass(slots=True)
class InstallReceipt:
    """Machine-readable result of one ensure_* invocation."""

    tool_id: str
    requested_version: str
    selected_version: str | None = None
    selected_platform: str | None = None
    executable_path: str | None = None
    jar_path: str | None = None
    pin: dict[str, Any] | None = None
    status: str = "blocked"  # available | installed | blocked | failed
    phase: str = "init"
    installed: bool = False
    already_present: bool = False
    install_attempted: bool = False
    checksum_verified: bool = False
    observed_sha256: str | None = None
    strict: bool = True
    yes: bool = False
    user_local: bool = True
    support_only: bool = False
    authority_tool: bool = True
    grants_theorem_authority: bool = False
    java_is_support_only: bool = True
    reason_codes: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    bindings: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.grants_theorem_authority:
            raise StateModelInstallerError(
                "state-model install receipts never grant theorem authority"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class JavaRuntimeProbe:
    """Identity and usability evidence for one selected support JVM."""

    executable: str | None
    source: str
    minimum_major: int
    banner: str | None = None
    major: int | None = None
    usable: bool = False
    reason_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RuntimeCommandProbe:
    """Bounded subprocess evidence used before a tool becomes discoverable."""

    command: tuple[str, ...]
    returncode: int | None
    output: str
    usable: bool
    reason_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Path / platform helpers
# ---------------------------------------------------------------------------


def expand_user_local_root(root: str | Path | None = None) -> Path:
    """Return the user-local theorem-prover install root."""

    if root is not None:
        return Path(os.path.expanduser(str(root))).resolve()
    env = os.environ.get("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    return Path(os.path.expanduser(DEFAULT_USER_LOCAL_INSTALL_ROOT)).resolve()


def detect_platform_key() -> str:
    """Return a lock-compatible platform key (e.g. ``linux-x86_64``)."""

    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        arch = "x86_64"
    elif machine in {"aarch64", "arm64"}:
        arch = "aarch64" if system == "linux" else "arm64"
    else:
        arch = machine
    if system == "linux":
        return f"linux-{arch}"
    if system == "darwin":
        return f"darwin-{arch if arch != 'aarch64' else 'arm64'}"
    return f"{system}-{arch}"


def which_executable(name: str, *, path_env: str | None = None) -> str | None:
    """Locate an executable, preferring the managed user-local bin directory."""

    if not name or not str(name).strip():
        return None
    raw_name = str(name)
    # A bare command name is resolved only through PATH.  Treating ``java`` as
    # ``./java`` lets an untrusted working directory shadow the host runtime.
    if os.path.dirname(raw_name):
        candidate = Path(raw_name)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
        return None

    search_path = path_env
    if search_path is None:
        managed_bin = expand_user_local_root() / "bin"
        parts = [str(managed_bin)] if managed_bin.is_dir() else []
        parts.append(os.environ.get("PATH", ""))
        search_path = os.pathsep.join(p for p in parts if p)
    found = shutil.which(raw_name, path=search_path)
    return found


def _java_candidate(
    java_executable: str | Path | None = None,
) -> tuple[str, str]:
    """Return the requested Java candidate and its selection source.

    An explicit function argument or environment override is authoritative:
    an invalid override must not silently fall back to a different JVM.
    """

    if java_executable is not None:
        return str(java_executable), "argument"
    env_override = os.environ.get(JAVA_EXECUTABLE_ENV)
    if env_override:
        return env_override, "environment"
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        return str(Path(java_home) / "bin" / JAVA_EXECUTABLE), "java_home"
    return JAVA_EXECUTABLE, "path"


def resolve_java_executable(
    java_executable: str | Path | None = None,
) -> tuple[str | None, str]:
    """Resolve the selected JVM without mutating ``PATH`` or ``JAVA_HOME``."""

    candidate, source = _java_candidate(java_executable)
    return which_executable(candidate), source


def read_java_version_banner(
    java_executable: str,
    *,
    timeout: float = 10.0,
) -> tuple[int | None, str | None]:
    """Return ``(exit_code, banner)`` from a bounded ``java -version`` probe."""

    try:
        completed = subprocess.run(
            [java_executable, "-version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            env=_runtime_environment(),
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    text = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    ).strip()
    return completed.returncode, text or None


def java_major_version(banner: str | None) -> int | None:
    """Parse only Java's quoted identity token, never arbitrary dotted text."""

    match = _JAVA_VERSION_RE.search(banner or "")
    if match is None:
        return None
    token = match.group("version")
    components = re.findall(r"\d+", token)
    if not components:
        return None
    if components[0] == "1" and len(components) > 1:
        return int(components[1])
    return int(components[0])


def probe_java_runtime(
    *,
    java_executable: str | Path | None = None,
    minimum_major: int,
    timeout: float = 10.0,
) -> JavaRuntimeProbe:
    """Resolve and validate one JVM against a tool-specific minimum version."""

    resolved, source = resolve_java_executable(java_executable)
    if resolved is None:
        reason = (
            "java_override_invalid"
            if source in {"argument", "environment", "java_home"}
            else "java_support_missing"
        )
        return JavaRuntimeProbe(
            executable=None,
            source=source,
            minimum_major=minimum_major,
            reason_code=reason,
        )
    returncode, banner = read_java_version_banner(resolved, timeout=timeout)
    major = java_major_version(banner)
    if returncode is None or returncode != 0:
        return JavaRuntimeProbe(
            executable=resolved,
            source=source,
            minimum_major=minimum_major,
            banner=banner,
            major=major,
            reason_code="java_probe_failed",
        )
    if major is None:
        return JavaRuntimeProbe(
            executable=resolved,
            source=source,
            minimum_major=minimum_major,
            banner=banner,
            reason_code="java_version_unreadable",
        )
    if major < minimum_major:
        return JavaRuntimeProbe(
            executable=resolved,
            source=source,
            minimum_major=minimum_major,
            banner=banner,
            major=major,
            reason_code="java_version_unsupported",
        )
    return JavaRuntimeProbe(
        executable=resolved,
        source=source,
        minimum_major=minimum_major,
        banner=banner,
        major=major,
        usable=True,
    )


def java_is_available(
    *,
    java_executable: str | Path | None = None,
    minimum_major: int | None = None,
) -> bool:
    """Return whether a support JVM exists and, when requested, is compatible."""

    resolved, _ = resolve_java_executable(java_executable)
    if resolved is None:
        return False
    if minimum_major is None:
        return True
    return probe_java_runtime(
        java_executable=resolved,
        minimum_major=minimum_major,
    ).usable


def numeric_version(text: str) -> tuple[int, ...]:
    match = _VERSION_RE.search(text or "")
    if match is None:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def content_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _root_thread_lock(root: Path) -> threading.RLock:
    key = str(root.resolve())
    with _ROOT_LOCKS_GUARD:
        lock = _ROOT_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _ROOT_LOCKS[key] = lock
        return lock


@contextmanager
def installation_lock(root: str | Path):
    """Serialize all state-model publication for one install root.

    The in-process lock closes the gap in ``flock`` semantics between threads;
    the advisory file lock serializes independent Python processes.  The lock
    file is intentionally outside every staged bundle so publication and
    rollback never replace the inode carrying the lock.
    """

    resolved = expand_user_local_root(root)
    lock = _root_thread_lock(resolved)
    with lock:
        lock_dir = resolved / ".locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / "state-model.lock"
        with lock_path.open("a+b") as handle:
            if os.name == "posix":
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            else:  # pragma: no cover - exercised on Windows CI only
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _serialize_live_install(function):
    """Apply the per-root process lock without mutating selection-only dry runs."""

    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any):
        if bool(kwargs.get("dry_run", False)):
            return function(*args, **kwargs)
        root = expand_user_local_root(kwargs.get("install_root"))
        with installation_lock(root):
            return function(*args, **kwargs)

    return wrapped


def _announce(
    message: str,
    on_progress: ProgressCallback | None,
    *,
    phase: str = "info",
) -> None:
    if on_progress is not None:
        on_progress(phase, message)


# ---------------------------------------------------------------------------
# Lock / pin selection
# ---------------------------------------------------------------------------


def resolve_lock_path(repo_root: Path | str | None = None) -> Path | None:
    """Locate the deployment lock without requiring installation."""

    candidates: list[Path] = []
    if repo_root is not None:
        root = Path(repo_root)
        candidates.append(root / DEFAULT_LOCK_RELATIVE)
        candidates.append(root / "config" / "formal_verification_toolchains.lock.json")
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / DEFAULT_LOCK_RELATIVE)
        candidates.append(
            parent / "config" / "formal_verification_toolchains.lock.json"
        )
    cwd = Path.cwd()
    candidates.append(cwd / DEFAULT_LOCK_RELATIVE)
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_lock_document(repo_root: Path | str | None = None) -> dict[str, Any] | None:
    path = resolve_lock_path(repo_root)
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise StateModelInstallerError("deployment lock must be a JSON object")
    return payload


def pins_for_tool(
    tool_id: str,
    *,
    repo_root: Path | str | None = None,
    lock: Mapping[str, Any] | None = None,
) -> tuple[ToolPin, ...]:
    """Return managed pins for ``tool_id`` from the lock or reviewed fallbacks."""

    document = lock if lock is not None else load_lock_document(repo_root)
    pins: list[ToolPin] = []
    if document is not None:
        tools = document.get("tools") or []
        if not isinstance(tools, list):
            raise StateModelInstallerError("deployment lock tools must be a list")
        for entry in tools:
            if not isinstance(entry, Mapping):
                continue
            if str(entry.get("tool_id") or "") != tool_id:
                continue
            for raw in entry.get("pins") or []:
                if not isinstance(raw, Mapping):
                    continue
                sha = str(raw.get("sha256") or "").lower()
                is_checksummed = bool(raw.get("is_checksummed", bool(sha)))
                requires_checksum = bool(
                    raw.get("requires_checksum_at_install")
                    or (entry.get("deployment_contract") or {}).get(
                        "requires_checksum_at_install"
                    )
                    or True
                )
                pins.append(
                    ToolPin(
                        tool_id=str(raw.get("tool_id") or tool_id),
                        version=str(raw.get("version") or ""),
                        platform=str(raw.get("platform") or "any"),
                        artifact_url=str(raw.get("artifact_url") or ""),
                        sha256=sha,
                        identity_kind=str(
                            raw.get("identity_kind")
                            or entry.get("identity_kind")
                            or "release_archive"
                        ),
                        is_checksummed=is_checksummed,
                        requires_checksum_at_install=requires_checksum,
                    )
                )
            break
    if not pins:
        for raw in _FALLBACK_PINS.get(tool_id, ()):
            pins.append(
                ToolPin(
                    tool_id=str(raw["tool_id"]),
                    version=str(raw["version"]),
                    platform=str(raw["platform"]),
                    artifact_url=str(raw["artifact_url"]),
                    sha256=str(raw.get("sha256") or ""),
                    identity_kind=str(raw.get("identity_kind") or "release_archive"),
                    is_checksummed=bool(raw.get("is_checksummed")),
                    requires_checksum_at_install=bool(
                        raw.get("requires_checksum_at_install", True)
                    ),
                )
            )
    if not pins:
        raise StateModelInstallerError(f"no managed pins registered for {tool_id!r}")
    return tuple(pins)


def locked_version_for(tool_id: str, *, lock: Mapping[str, Any] | None = None) -> str:
    """Return the exact managed pin version required under strict install."""

    if lock is not None:
        versions = lock.get("managed_pin_versions") or {}
        if isinstance(versions, Mapping) and tool_id in versions:
            return str(versions[tool_id])
    if tool_id in LOCKED_VERSIONS:
        return LOCKED_VERSIONS[tool_id]
    raise StateModelInstallerError(f"no locked version for tool_id={tool_id!r}")


def select_strict_pin(
    tool_id: str,
    *,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    lock: Mapping[str, Any] | None = None,
    allow_any_platform: bool = True,
) -> ToolPin:
    """Select the exact locked pin for ``tool_id`` on the host platform.

    TLC and Apalache ship platform-portable JVM artifacts under ``any``.
    """

    if tool_id not in {"tlc", "apalache"}:
        raise StateModelInstallerError(
            f"state_model plugin does not own tool_id={tool_id!r}"
        )
    platform_name = platform_key or detect_platform_key()
    expected = locked_version_for(tool_id, lock=lock)
    candidates = pins_for_tool(tool_id, repo_root=repo_root, lock=lock)
    exact = [
        pin
        for pin in candidates
        if pin.version == expected and pin.platform == platform_name
    ]
    selected: ToolPin | None = exact[0] if exact else None
    if allow_any_platform:
        any_pin = [
            pin
            for pin in candidates
            if pin.version == expected and pin.platform in {"any", "source", "portable"}
        ]
        if selected is None and any_pin:
            selected = any_pin[0]
    if selected is not None:
        locked_digest = {
            "tlc": TLC_SHA256,
            "apalache": APALACHE_SHA256,
        }[tool_id]
        if not selected.is_checksummed or selected.sha256 != locked_digest:
            raise StateModelInstallerError(
                f"{tool_id} {expected} requires the reviewed immutable artifact "
                f"digest {locked_digest}; blank or alternate lock identities "
                "fail closed"
            )
        return selected
    available = sorted({f"{pin.platform}@{pin.version}" for pin in candidates})
    raise StateModelInstallerError(
        f"strict install for {tool_id!r} requires version {expected!r} on "
        f"platform {platform_name!r}; available pins: {available}"
    )


# ---------------------------------------------------------------------------
# Version / runtime probes
# ---------------------------------------------------------------------------


def _runtime_environment(
    java_executable: str | Path | None = None,
) -> dict[str, str]:
    env = dict(os.environ)
    for variable in JAVA_OPTION_ENV_VARS:
        env.pop(variable, None)
    if java_executable is not None:
        java_dir = str(Path(java_executable).resolve().parent)
        current = env.get("PATH", "")
        env["PATH"] = os.pathsep.join(
            part for part in (java_dir, current) if part
        )
    return env


def _run_runtime_command(
    command: Sequence[str],
    *,
    timeout: float,
    java_executable: str | Path | None = None,
) -> RuntimeCommandProbe:
    normalized = tuple(str(part) for part in command)
    try:
        completed = subprocess.run(
            list(normalized),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            env=_runtime_environment(java_executable),
        )
    except (OSError, subprocess.SubprocessError):
        return RuntimeCommandProbe(
            command=normalized,
            returncode=None,
            output="",
            usable=False,
            reason_code="runtime_probe_failed",
        )
    text = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    ).strip()
    if completed.returncode != 0:
        return RuntimeCommandProbe(
            command=normalized,
            returncode=completed.returncode,
            output=text,
            usable=False,
            reason_code="runtime_probe_nonzero_exit",
        )
    if not text:
        return RuntimeCommandProbe(
            command=normalized,
            returncode=completed.returncode,
            output="",
            usable=False,
            reason_code="runtime_probe_empty_output",
        )
    return RuntimeCommandProbe(
        command=normalized,
        returncode=completed.returncode,
        output=text,
        usable=True,
    )


def read_version_banner(
    executable: str,
    *,
    timeout: float = 10.0,
    extra_args: Sequence[str] = ("--version",),
) -> str | None:
    try:
        completed = subprocess.run(
            [executable, *list(extra_args)],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    ).strip()
    return text or None


def read_tlc_version_banner(
    executable: str | None = None,
    *,
    jar_path: str | Path | None = None,
    java_executable: str | Path | None = None,
    timeout: float = 10.0,
) -> str | None:
    """Probe TLC identity via launcher or ``java -cp jar tlc2.TLC``."""

    binary = executable or which_executable(TLC_EXECUTABLE)
    if binary:
        probe = probe_tlc_runtime(
            executable=binary,
            java_executable=java_executable,
            timeout=timeout,
        )
        if probe.usable:
            return probe.output
    jar = Path(jar_path) if jar_path else None
    if jar is None and binary:
        # Launcher may live next to the managed jar.
        managed = expand_user_local_root() / "tlc" / TLC_VERSION / TLC_JAR_NAME
        if managed.is_file():
            jar = managed
    if jar is not None and jar.is_file():
        java, _ = resolve_java_executable(java_executable)
        if java:
            probe = probe_tlc_runtime(
                jar_path=jar,
                java_executable=java,
                timeout=timeout,
            )
            if probe.usable:
                return probe.output
    return None


def read_apalache_version_banner(
    executable: str | None = None,
    *,
    java_executable: str | Path | None = None,
    timeout: float = 15.0,
) -> str | None:
    binary = executable or which_executable(APALACHE_EXECUTABLE)
    if not binary:
        binary = which_executable("apalache")
    if not binary:
        return None
    for args in (("version",), ("--version",), ("-V",)):
        probe = _run_runtime_command(
            [binary, *args],
            timeout=timeout,
            java_executable=java_executable,
        )
        if probe.usable:
            return probe.output
    return None


def observed_version_matches_lock(banner: str | None, expected: str) -> bool:
    if not banner:
        return False
    if expected in banner:
        return True
    observed = numeric_version(banner)
    locked = numeric_version(expected)
    return bool(observed and locked and observed == locked)


def _tlc_help_probe(probe: RuntimeCommandProbe) -> RuntimeCommandProbe:
    """Accept TLC's help contract, which intentionally exits with status 1."""

    output = _ANSI_ESCAPE_RE.sub("", probe.output)
    semantic_help = all(marker in output for marker in _TLC_HELP_MARKERS)
    if probe.returncode in {0, 1} and semantic_help:
        return RuntimeCommandProbe(
            command=probe.command,
            returncode=probe.returncode,
            output=output,
            usable=True,
        )
    reason = probe.reason_code
    if probe.returncode in {0, 1} and not semantic_help:
        reason = "tlc_help_semantics_missing"
    return RuntimeCommandProbe(
        command=probe.command,
        returncode=probe.returncode,
        output=output,
        usable=False,
        reason_code=reason or "runtime_probe_failed",
    )


def probe_tlc_runtime(
    *,
    executable: str | None = None,
    jar_path: str | Path | None = None,
    java_executable: str | Path | None = None,
    timeout: float = 15.0,
) -> RuntimeCommandProbe:
    """Prove TLC starts under the selected JVM before reporting it usable."""

    jar = Path(jar_path) if jar_path is not None else None
    if jar is not None and jar.is_file():
        if java_executable is None:
            return RuntimeCommandProbe(
                command=(),
                returncode=None,
                output="",
                usable=False,
                reason_code="java_support_missing",
            )
        return _tlc_help_probe(_run_runtime_command(
            [
                str(java_executable),
                "-cp",
                str(jar),
                "tlc2.TLC",
                "-help",
            ],
            timeout=timeout,
            java_executable=java_executable,
        ))
    if executable:
        return _tlc_help_probe(_run_runtime_command(
            [executable, "-help"],
            timeout=timeout,
            java_executable=java_executable,
        ))
    return RuntimeCommandProbe(
        command=(),
        returncode=None,
        output="",
        usable=False,
        reason_code="runtime_executable_missing",
    )


def probe_apalache_runtime(
    executable: str,
    *,
    java_executable: str | Path | None = None,
    expected_version: str | None = APALACHE_VERSION,
    timeout: float = 20.0,
) -> RuntimeCommandProbe:
    """Prove Apalache starts, exits cleanly, and reports the locked version."""

    last_probe: RuntimeCommandProbe | None = None
    for args in (("version",), ("--version",), ("-V",)):
        probe = _run_runtime_command(
            [executable, *args],
            timeout=timeout,
            java_executable=java_executable,
        )
        last_probe = probe
        if not probe.usable:
            continue
        if expected_version is None or observed_version_matches_lock(
            probe.output,
            expected_version,
        ):
            return probe
        last_probe = RuntimeCommandProbe(
            command=probe.command,
            returncode=probe.returncode,
            output=probe.output,
            usable=False,
            reason_code="runtime_version_mismatch",
        )
    if last_probe is not None:
        return last_probe
    return RuntimeCommandProbe(
        command=(),
        returncode=None,
        output="",
        usable=False,
        reason_code="runtime_executable_missing",
    )


# ---------------------------------------------------------------------------
# Artifact download / extract (user-local)
# ---------------------------------------------------------------------------


def verify_sha256(path: Path, expected: str) -> bool:
    if not expected:
        return False
    return content_sha256(path) == expected.lower()


def download_artifact(
    url: str,
    destination: Path,
    *,
    sha256: str = "",
    require_checksum: bool = True,
    timeout: float = 180.0,
    on_progress: ProgressCallback | None = None,
) -> tuple[bool, str | None]:
    """Download ``url`` to ``destination`` and optionally verify checksum.

    Returns ``(ok, observed_sha256)``.  When ``sha256`` is empty and
    ``require_checksum`` is True, the download succeeds only if the file is
    obtained and a digest is computed for the install receipt (lock pins that
    leave sha256 empty still bind identity at install time).
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        observed = content_sha256(destination)
        if sha256:
            if observed == sha256.lower():
                _announce(
                    f"Reusing checksummed artifact at {destination}",
                    on_progress,
                    phase="available",
                )
                return True, observed
        elif not require_checksum or observed:
            _announce(
                f"Reusing local artifact at {destination}",
                on_progress,
                phase="available",
            )
            return True, observed

    _announce(f"Downloading {url}", on_progress, phase="downloading")
    request = Request(
        url, headers={"User-Agent": "ipfs-datasets-py-state-model-installer/1"}
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - reviewed pin URL
            data = response.read()
    except Exception as exc:  # pragma: no cover - network failures host-specific
        _announce(f"Download failed: {exc}", on_progress, phase="failed")
        return False, None
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".partial",
            delete=False,
        ) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        observed = content_sha256(temporary)
        if sha256 and observed != sha256.lower():
            _announce(
                f"Checksum mismatch for {url}; refusing install",
                on_progress,
                phase="failed",
            )
            return False, None
        if require_checksum and not observed:
            return False, None
        temporary.replace(destination)
        temporary = None
        return True, observed
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _safe_extract_tar(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as handle:
        try:
            handle.extractall(destination, filter="data")  # type: ignore[call-arg]
        except TypeError:  # pragma: no cover
            handle.extractall(destination)


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(destination)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _launcher_body(
    target: Path,
    *,
    environment: Mapping[str, str] | None = None,
    java_jar: Path | None = None,
    java_main: str | None = None,
    java_executable: str | Path | None = None,
) -> str:
    """Render the complete deterministic launcher contract."""

    env_exports = ""
    if environment:
        lines = [
            f"export {key}={_shell_quote(str(environment[key]))}"
            for key in sorted(environment)
        ]
        env_exports = "\n".join(lines) + "\n"
    selected_java = (
        str(Path(java_executable).resolve())
        if java_executable is not None
        else None
    )
    java_environment_guard = (
        "unset " + " ".join(JAVA_OPTION_ENV_VARS) + "\n"
        if java_jar is not None or selected_java
        else ""
    )
    if java_jar is not None and java_main:
        java_command = _shell_quote(selected_java) if selected_java else "java"
        java_guard = ""
        if selected_java is None:
            java_guard = (
                "if ! command -v java >/dev/null 2>&1; then\n"
                '  echo "java (JVM support runtime) is required for TLC" >&2\n'
                "  exit 127\n"
                "fi\n"
            )
        return (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"{env_exports}"
            f"{java_environment_guard}"
            f"{java_guard}"
            f"exec {java_command} -cp {_shell_quote(str(java_jar.resolve()))} "
            f"{_shell_quote(java_main)} \"$@\"\n"
        )
    java_path = ""
    if selected_java:
        java_path = (
            f"export PATH={_shell_quote(str(Path(selected_java).parent))}:"
            '"${PATH:-}"\n'
        )
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"{env_exports}"
        f"{java_environment_guard}"
        f"{java_path}"
        f'exec {_shell_quote(str(target.resolve()))} "$@"\n'
    )


def write_launcher(
    name: str,
    target: Path,
    *,
    install_root: Path | None = None,
    environment: Mapping[str, str] | None = None,
    java_jar: Path | None = None,
    java_main: str | None = None,
    java_executable: str | Path | None = None,
) -> Path:
    """Write a user-local launcher script under ``$root/bin/<name>``."""

    root = expand_user_local_root(install_root)
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / name
    body = _launcher_body(
        target,
        environment=environment,
        java_jar=java_jar,
        java_main=java_main,
        java_executable=java_executable,
    )
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=bin_dir,
            prefix=f".{name}.",
            suffix=".partial",
            delete=False,
        ) as handle:
            handle.write(body)
            temporary = Path(handle.name)
        temporary.chmod(0o755)
        temporary.replace(launcher)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return launcher


def _launcher_identity(
    launcher: Path,
    *,
    expected_body: str,
) -> dict[str, Any]:
    """Validate a launcher by its complete bytes, never by substrings."""

    result: dict[str, Any] = {
        "path": str(launcher.resolve()),
        "present": launcher.is_file() and not launcher.is_symlink(),
        "executable": (
            launcher.is_file()
            and not launcher.is_symlink()
            and os.access(launcher, os.X_OK)
        ),
        "expected_sha256": content_sha256_bytes(expected_body.encode("utf-8")),
        "observed_sha256": None,
        "structural_match": False,
    }
    try:
        observed = launcher.read_bytes()
    except OSError:
        return result
    result["observed_sha256"] = content_sha256_bytes(observed)
    result["structural_match"] = bool(
        result["executable"] and observed == expected_body.encode("utf-8")
    )
    return result


def content_sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_json_file(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _tree_digest(root: Path) -> str:
    """Hash every file/symlink path and payload in an extracted distribution."""

    records: list[dict[str, str]] = []
    if not root.is_dir():
        return ""
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            records.append(
                {
                    "kind": "symlink",
                    "path": relative,
                    "target": os.readlink(path),
                }
            )
        elif path.is_file():
            records.append(
                {
                    "kind": "file",
                    "path": relative,
                    "sha256": content_sha256(path),
                }
            )
    return content_sha256_bytes(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _find_apalache_binary(root: Path) -> Path | None:
    preferred = sorted(
        (
            path
            for path in root.rglob(APALACHE_EXECUTABLE)
            if path.is_file() and not path.is_symlink()
        ),
        key=lambda path: path.as_posix(),
    )
    if len(preferred) == 1:
        return preferred[0]
    if preferred:
        return None
    fallback = sorted(
        (
            path
            for path in root.rglob("apalache")
            if path.is_file() and not path.is_symlink()
        ),
        key=lambda path: path.as_posix(),
    )
    return fallback[0] if len(fallback) == 1 else None


# ---------------------------------------------------------------------------
# Install authorization gate
# ---------------------------------------------------------------------------


def authorize_plugin_install(
    tool_id: str,
    *,
    yes: bool,
    strict: bool = True,
    explicit_call: bool = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    checksum_verified: bool | None = None,
    platform_key: str | None = None,
    test_mode: bool = False,
    system_package_mutation: bool = False,
) -> None:
    """Fail-closed gate shared by ensure_tlc / ensure_apalache."""

    if tool_id not in {"tlc", "apalache"}:
        raise StateModelInstallerError(
            f"state_model plugin does not own tool_id={tool_id!r}"
        )
    try:
        authorize_installer_entry_install(
            tool_id,
            yes=yes,
            explicit_call=explicit_call,
            import_context=import_context,
            capability_discovery=capability_discovery,
            checksum_verified=checksum_verified,
            platform=platform_key,
            system_package_mutation=system_package_mutation,
            test_mode=test_mode,
        )
    except InstallerRegistryError as exc:
        raise StateModelInstallerError(str(exc)) from exc
    entry = get_installer_entry(tool_id)
    if entry.family is not InstallerPluginFamily.STATE_MODEL:
        raise StateModelInstallerError(
            f"tool {tool_id!r} is not bound to the state_model installer plugin"
        )
    if strict:
        select_strict_pin(tool_id, platform_key=platform_key)


def _base_receipt(
    tool_id: str,
    *,
    requested_version: str,
    yes: bool,
    strict: bool,
) -> InstallReceipt:
    return InstallReceipt(
        tool_id=tool_id,
        requested_version=requested_version,
        strict=strict,
        yes=yes,
        support_only=False,
        authority_tool=True,
        grants_theorem_authority=False,
        java_is_support_only=True,
        bindings={
            "tool_id": tool_id,
            "locked_version": requested_version,
            "role": "authority",
            "authority_ceiling": "bounded",
            "grants_theorem_authority": False,
            "bounded_model_checking_only": True,
            "java_is_support_only": True,
            "java_cannot_promote_tla_lane": True,
            "does_not_edit_shared_lock": True,
            "does_not_edit_central_certificate": True,
        },
    )


def _record_java_runtime(
    receipt: InstallReceipt,
    runtime: JavaRuntimeProbe,
) -> None:
    receipt.bindings["java_available"] = runtime.executable is not None
    receipt.bindings["java_usable"] = runtime.usable
    receipt.bindings["java_runtime"] = runtime.to_dict()
    receipt.bindings["java_executable"] = runtime.executable
    receipt.bindings["java_major"] = runtime.major
    receipt.bindings["minimum_java_major"] = runtime.minimum_major


def _block_for_java_runtime(
    receipt: InstallReceipt,
    runtime: JavaRuntimeProbe,
    *,
    tool_name: str,
) -> InstallReceipt:
    receipt.status = "blocked"
    receipt.phase = "java_support"
    reason = runtime.reason_code or "java_support_unusable"
    receipt.reason_codes.append(reason)
    if reason == "java_version_unsupported":
        detail = (
            f"selected Java {runtime.major} is below the certified minimum "
            f"Java {runtime.minimum_major}"
        )
    elif reason == "java_override_invalid":
        detail = "the explicit Java override does not resolve to an executable"
    elif reason == "java_version_unreadable":
        detail = "the selected Java version could not be determined"
    elif reason == "java_probe_failed":
        detail = "the selected Java runtime failed its bounded version probe"
    else:
        detail = "no Java runtime was found"
    receipt.messages.append(
        f"{tool_name} is not runnable because {detail}. Java remains a "
        "support-only host dependency and is never installed or promoted by "
        "this plugin."
    )
    return receipt


def _record_tool_runtime(
    receipt: InstallReceipt,
    probe: RuntimeCommandProbe,
    *,
    binding: str,
) -> None:
    receipt.bindings[binding] = probe.to_dict()


def _fail_runtime_validation(
    receipt: InstallReceipt,
    probe: RuntimeCommandProbe,
    *,
    tool_name: str,
    strict: bool,
) -> InstallReceipt:
    receipt.status = "failed"
    receipt.phase = "runtime_validation"
    receipt.installed = False
    receipt.reason_codes.append("post_install_usability_failed")
    if probe.reason_code:
        receipt.reason_codes.append(probe.reason_code)
    receipt.messages.append(
        f"{tool_name} artifacts were prepared but the bounded runtime probe "
        "did not succeed; no managed launcher was published."
    )
    if strict:
        raise StateModelInstallerError(
            f"{tool_name} installation failed post-install runtime validation"
        )
    return receipt


def _dry_run_receipt(
    receipt: InstallReceipt,
    pin: ToolPin,
    *,
    tool_name: str,
) -> InstallReceipt:
    """Return selection evidence without resolving or executing host tools."""

    receipt.status = "blocked" if not receipt.yes else "available"
    receipt.phase = "dry_run"
    receipt.reason_codes.append("dry_run")
    receipt.bindings["runtime_probe_skipped"] = True
    receipt.bindings["runtime_validation_required"] = False
    receipt.messages.append(
        f"dry-run selected {tool_name} {pin.version} for {pin.platform}; "
        "no executable or JVM probe was run"
    )
    return receipt


def _reject_java_validation_opt_out(
    receipt: InstallReceipt,
    *,
    require_java: bool,
    tool_name: str,
) -> InstallReceipt | None:
    if require_java:
        return None
    receipt.status = "failed"
    receipt.phase = "java_support"
    receipt.reason_codes.append("java_validation_opt_out_forbidden")
    receipt.messages.append(
        f"{tool_name} no longer permits require_java=False for a live ensure "
        "operation because an unvalidated artifact cannot be reported usable; "
        "use dry_run=True for selection-only evidence"
    )
    return receipt


def _manifest_payload(
    *,
    tool_id: str,
    version: str,
    artifact_path: Path,
    artifact_sha256: str,
    payload_path: Path,
    payload_sha256: str,
    java_executable: str | Path,
    launcher_identities: Mapping[str, Mapping[str, Any]],
    distribution_tree_sha256: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": _MANIFEST_SCHEMA,
        "tool_id": tool_id,
        "version": version,
        "artifact_path": str(artifact_path.resolve()),
        "artifact_sha256": artifact_sha256,
        "payload_path": str(payload_path.resolve()),
        "payload_sha256": payload_sha256,
        "java_executable": str(Path(java_executable).resolve()),
        "launchers": {
            name: {
                "path": str(identity["path"]),
                "sha256": str(identity["expected_sha256"]),
            }
            for name, identity in sorted(launcher_identities.items())
        },
    }
    if distribution_tree_sha256 is not None:
        payload["distribution_tree_sha256"] = distribution_tree_sha256
    return payload


def _read_exact_manifest(path: Path, expected: Mapping[str, Any]) -> bool:
    if path.is_symlink():
        return False
    try:
        observed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return observed == dict(expected)


def managed_tlc_identity(
    install_root: str | Path,
    *,
    java_executable: str | Path,
) -> dict[str, Any]:
    """Return structural TLC identity bound to the exact jar and JVM."""

    root = expand_user_local_root(install_root)
    jar = root / "tlc" / TLC_VERSION / TLC_JAR_NAME
    java_path = Path(java_executable).resolve()
    java_present = java_path.is_file() and os.access(java_path, os.X_OK)
    artifact_ok = (
        jar.is_file()
        and not jar.is_symlink()
        and verify_sha256(jar, TLC_SHA256)
    )
    identities: dict[str, dict[str, Any]] = {}
    for name in (TLC_EXECUTABLE, "tlc2", "tla2tools"):
        body = _launcher_body(
            jar,
            environment={"TLA2TOOLS_JAR": str(jar)},
            java_jar=jar,
            java_main="tlc2.TLC",
            java_executable=java_executable,
        )
        identities[name] = _launcher_identity(
            root / "bin" / name,
            expected_body=body,
        )
    launchers_ok = all(
        bool(identity["structural_match"]) for identity in identities.values()
    )
    expected_manifest = _manifest_payload(
        tool_id="tlc",
        version=TLC_VERSION,
        artifact_path=jar,
        artifact_sha256=TLC_SHA256,
        payload_path=jar,
        payload_sha256=TLC_SHA256,
        java_executable=java_executable,
        launcher_identities=identities,
    )
    manifest_path = root / "manifests" / "tlc.json"
    manifest_ok = _read_exact_manifest(manifest_path, expected_manifest)
    return {
        "tool_id": "tlc",
        "version": TLC_VERSION,
        "artifact_path": str(jar),
        "artifact_sha256": TLC_SHA256,
        "artifact_digest_verified": artifact_ok,
        "payload_path": str(jar),
        "payload_sha256": TLC_SHA256 if artifact_ok else None,
        "payload_digest_verified": artifact_ok,
        "java_executable": str(java_path),
        "java_executable_present": java_present,
        "launchers": identities,
        "launchers_structurally_valid": launchers_ok,
        "manifest_path": str(manifest_path),
        "manifest_valid": manifest_ok,
        "usable": bool(
            artifact_ok
            and java_present
            and launchers_ok
            and manifest_ok
        ),
    }


def managed_apalache_identity(
    install_root: str | Path,
    *,
    java_executable: str | Path,
) -> dict[str, Any]:
    """Return structural Apalache archive, tree, payload, and launcher identity."""

    root = expand_user_local_root(install_root)
    archive = root / "downloads" / f"apalache-{APALACHE_VERSION}.tgz"
    destination = root / f"apalache-{APALACHE_VERSION}"
    java_path = Path(java_executable).resolve()
    java_present = java_path.is_file() and os.access(java_path, os.X_OK)
    artifact_ok = (
        archive.is_file()
        and not archive.is_symlink()
        and verify_sha256(archive, APALACHE_SHA256)
    )
    expected_tree = ""
    expected_relative: Path | None = None
    if artifact_ok:
        try:
            with tempfile.TemporaryDirectory(
                prefix="apalache-identity-",
            ) as temporary:
                extracted = Path(temporary) / "distribution"
                _safe_extract_tar(archive, extracted)
                binary = _find_apalache_binary(extracted)
                if binary is not None:
                    expected_relative = binary.relative_to(extracted)
                    expected_tree = _tree_digest(extracted)
        except (OSError, tarfile.TarError):
            expected_tree = ""
            expected_relative = None
    observed_tree = (
        _tree_digest(destination)
        if destination.is_dir() and not destination.is_symlink()
        else ""
    )
    tree_ok = bool(expected_tree and observed_tree == expected_tree)
    payload = (
        destination / expected_relative
        if expected_relative is not None
        else destination / "__missing_apalache_payload__"
    )
    payload_sha = content_sha256(payload) if payload.is_file() else ""
    payload_executable = bool(
        payload.is_file()
        and not payload.is_symlink()
        and os.access(payload, os.X_OK)
    )
    identities: dict[str, dict[str, Any]] = {}
    for name in (APALACHE_EXECUTABLE, "apalache"):
        body = _launcher_body(
            payload,
            java_executable=java_executable,
        )
        identities[name] = _launcher_identity(
            root / "bin" / name,
            expected_body=body,
        )
    launchers_ok = all(
        bool(identity["structural_match"]) for identity in identities.values()
    )
    expected_manifest = _manifest_payload(
        tool_id="apalache",
        version=APALACHE_VERSION,
        artifact_path=archive,
        artifact_sha256=APALACHE_SHA256,
        payload_path=payload,
        payload_sha256=payload_sha,
        java_executable=java_executable,
        launcher_identities=identities,
        distribution_tree_sha256=expected_tree,
    )
    manifest_path = root / "manifests" / "apalache.json"
    manifest_ok = bool(
        payload.is_file()
        and tree_ok
        and _read_exact_manifest(manifest_path, expected_manifest)
    )
    return {
        "tool_id": "apalache",
        "version": APALACHE_VERSION,
        "artifact_path": str(archive),
        "artifact_sha256": APALACHE_SHA256,
        "artifact_digest_verified": artifact_ok,
        "distribution_path": str(destination),
        "expected_distribution_tree_sha256": expected_tree or None,
        "observed_distribution_tree_sha256": observed_tree or None,
        "distribution_tree_verified": tree_ok,
        "payload_path": str(payload),
        "payload_sha256": payload_sha or None,
        "payload_digest_verified": bool(payload_sha and tree_ok),
        "payload_executable": payload_executable,
        "java_executable": str(java_path),
        "java_executable_present": java_present,
        "launchers": identities,
        "launchers_structurally_valid": launchers_ok,
        "manifest_path": str(manifest_path),
        "manifest_valid": manifest_ok,
        "usable": bool(
            artifact_ok
            and tree_ok
            and payload_sha
            and payload_executable
            and java_present
            and launchers_ok
            and manifest_ok
        ),
    }


def _commit_staged_files(
    replacements: Sequence[tuple[Path, Path]],
    *,
    backup_dir: Path,
) -> None:
    """Publish a locked file bundle and restore every prior file on failure.

    Callers hold :func:`installation_lock`, so no independent installer can
    observe or overwrite an in-flight transaction.  Each individual rename is
    atomic; the rollback journal preserves the previous complete generation if
    any later rename fails.
    """

    backup_dir.mkdir(parents=True, exist_ok=True)
    destinations = [destination.resolve() for _, destination in replacements]
    if len(destinations) != len(set(destinations)):
        raise StateModelInstallerError("publication destinations must be unique")
    for staged, destination in replacements:
        if not staged.is_file():
            raise StateModelInstallerError(
                f"staged publication file is missing: {staged}"
            )
        if staged.resolve() == destination.resolve():
            raise StateModelInstallerError(
                f"staged and destination paths must differ: {destination}"
            )
    backups: dict[Path, Path | None] = {}
    published: list[Path] = []
    for index, (_, destination) in enumerate(replacements):
        if destination.is_file():
            backup = backup_dir / f"{index}-{destination.name}"
            shutil.copy2(destination, backup)
            backups[destination] = backup
        else:
            backups[destination] = None
    try:
        for staged, destination in replacements:
            destination.parent.mkdir(parents=True, exist_ok=True)
            staged.replace(destination)
            published.append(destination)
    except Exception:
        for destination in reversed(published):
            backup = backups[destination]
            if backup is None:
                destination.unlink(missing_ok=True)
            else:
                backup.replace(destination)
        raise


def _planned_launcher_identity(path: Path, body: str) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "expected_sha256": content_sha256_bytes(body.encode("utf-8")),
    }


def _stage_tlc_manifest(
    *,
    staging_root: Path,
    install_root: Path,
    jar_path: Path,
    java_executable: str | Path,
) -> tuple[Path, Path]:
    identities: dict[str, dict[str, Any]] = {}
    for name in (TLC_EXECUTABLE, "tlc2", "tla2tools"):
        body = _launcher_body(
            jar_path,
            environment={"TLA2TOOLS_JAR": str(jar_path)},
            java_jar=jar_path,
            java_main="tlc2.TLC",
            java_executable=java_executable,
        )
        identities[name] = _planned_launcher_identity(
            install_root / "bin" / name,
            body,
        )
    payload = _manifest_payload(
        tool_id="tlc",
        version=TLC_VERSION,
        artifact_path=jar_path,
        artifact_sha256=TLC_SHA256,
        payload_path=jar_path,
        payload_sha256=TLC_SHA256,
        java_executable=java_executable,
        launcher_identities=identities,
    )
    staged = staging_root / "tlc.json"
    _write_json_file(staged, payload)
    return staged, install_root / "manifests" / "tlc.json"


def _stage_apalache_manifest(
    *,
    staging_root: Path,
    install_root: Path,
    archive_path: Path,
    binary_path: Path,
    payload_sha256: str,
    distribution_tree_sha256: str,
    java_executable: str | Path,
) -> tuple[Path, Path]:
    identities: dict[str, dict[str, Any]] = {}
    for name in (APALACHE_EXECUTABLE, "apalache"):
        body = _launcher_body(
            binary_path,
            java_executable=java_executable,
        )
        identities[name] = _planned_launcher_identity(
            install_root / "bin" / name,
            body,
        )
    payload = _manifest_payload(
        tool_id="apalache",
        version=APALACHE_VERSION,
        artifact_path=archive_path,
        artifact_sha256=APALACHE_SHA256,
        payload_path=binary_path,
        payload_sha256=payload_sha256,
        java_executable=java_executable,
        launcher_identities=identities,
        distribution_tree_sha256=distribution_tree_sha256,
    )
    staged = staging_root / "apalache.json"
    _write_json_file(staged, payload)
    return staged, install_root / "manifests" / "apalache.json"


def _stage_tlc_launchers(
    *,
    staging_root: Path,
    install_root: Path,
    jar_path: Path,
    java_executable: str | Path,
) -> tuple[Path, tuple[tuple[Path, Path], ...]]:
    staged: list[tuple[Path, Path]] = []
    launcher: Path | None = None
    for name in (TLC_EXECUTABLE, "tlc2", "tla2tools"):
        candidate = write_launcher(
            name,
            jar_path,
            install_root=staging_root,
            java_jar=jar_path,
            java_main="tlc2.TLC",
            java_executable=java_executable,
            environment={"TLA2TOOLS_JAR": str(jar_path)},
        )
        destination = install_root / "bin" / name
        staged.append((candidate, destination))
        if name == TLC_EXECUTABLE:
            launcher = destination
    assert launcher is not None
    return launcher, tuple(staged)


def _stage_apalache_launchers(
    *,
    staging_root: Path,
    install_root: Path,
    binary: Path,
    java_executable: str | Path,
) -> tuple[Path, tuple[tuple[Path, Path], ...]]:
    staged: list[tuple[Path, Path]] = []
    launcher: Path | None = None
    for name in (APALACHE_EXECUTABLE, "apalache"):
        candidate = write_launcher(
            name,
            binary,
            install_root=staging_root,
            java_executable=java_executable,
        )
        destination = install_root / "bin" / name
        staged.append((candidate, destination))
        if name == APALACHE_EXECUTABLE:
            launcher = destination
    assert launcher is not None
    return launcher, tuple(staged)


# ---------------------------------------------------------------------------
# ensure_* entry points
# ---------------------------------------------------------------------------


@_serialize_live_install
def ensure_tlc(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
    install_root: str | Path | None = None,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    dry_run: bool = False,
    test_mode: bool = False,
    require_java: bool = True,
    java_executable: str | Path | None = None,
) -> InstallReceipt:
    """Ensure a runnable pinned TLC / TLA+ tools 1.8.0 jar is user-local."""

    receipt = _base_receipt(
        "tlc",
        requested_version=TLC_VERSION,
        yes=yes,
        strict=strict,
    )
    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()

    try:
        pin = select_strict_pin(
            "tlc",
            platform_key=platform_name,
            repo_root=repo_root,
        )
    except StateModelInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "pin_selection"
        receipt.reason_codes.append("pin_selection_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    receipt.selected_version = pin.version
    receipt.selected_platform = pin.platform
    receipt.pin = pin.to_dict()
    receipt.bindings["selected_version"] = pin.version
    receipt.bindings["platform"] = pin.platform
    receipt.bindings["identity_kind"] = pin.identity_kind

    if dry_run:
        return _dry_run_receipt(receipt, pin, tool_name="TLC")

    rejected = _reject_java_validation_opt_out(
        receipt,
        require_java=require_java,
        tool_name="TLC",
    )
    if rejected is not None:
        return rejected

    java_runtime = probe_java_runtime(
        java_executable=java_executable,
        minimum_major=TLC_MIN_JAVA_MAJOR,
    )
    _record_java_runtime(receipt, java_runtime)
    receipt.bindings["runtime_validation_required"] = True
    if not java_runtime.usable:
        return _block_for_java_runtime(receipt, java_runtime, tool_name="TLC")
    assert java_runtime.executable is not None

    managed_bin = root / "bin"
    path_env = os.pathsep.join(
        part
        for part in (str(managed_bin), os.environ.get("PATH", ""))
        if part
    )
    existing = which_executable(TLC_EXECUTABLE, path_env=path_env)
    managed_jar = root / "tlc" / TLC_VERSION / TLC_JAR_NAME
    jar_ok = (
        managed_jar.is_file()
        and pin.sha256 == TLC_SHA256
        and verify_sha256(managed_jar, TLC_SHA256)
    )
    receipt.bindings["existing_managed_jar_identity_ok"] = jar_ok
    if jar_ok and not force:
        jar_probe = probe_tlc_runtime(
            jar_path=managed_jar,
            java_executable=java_runtime.executable,
        )
        _record_tool_runtime(
            receipt,
            jar_probe,
            binding="existing_artifact_runtime_probe",
        )
        managed_identity = managed_tlc_identity(
            root,
            java_executable=java_runtime.executable,
        )
        receipt.bindings["existing_managed_identity"] = managed_identity
        managed_launcher_path = managed_bin / TLC_EXECUTABLE
        if jar_probe.usable and managed_identity["usable"]:
            public_probe = probe_tlc_runtime(
                executable=str(managed_launcher_path),
                java_executable=java_runtime.executable,
            )
            _record_tool_runtime(
                receipt,
                public_probe,
                binding="existing_public_launcher_probe",
            )
            if public_probe.usable:
                receipt.executable_path = str(managed_launcher_path)
                receipt.jar_path = str(managed_jar)
                receipt.already_present = True
                receipt.installed = True
                receipt.status = "available"
                receipt.phase = "available"
                receipt.observed_sha256 = TLC_SHA256
                receipt.checksum_verified = True
                receipt.messages.append(
                    f"TLC already available and runnable at {managed_launcher_path}"
                )
                return receipt
        if jar_probe.usable and not yes:
            receipt.status = "blocked"
            receipt.phase = "managed_identity"
            receipt.reason_codes.append("managed_identity_repair_required")
            receipt.messages.append(
                "The managed TLC jar is valid, but its complete launcher/manifest "
                "identity is missing or mismatched; re-run with yes=True to "
                "republish the locked bundle."
            )
            return receipt
        if jar_probe.usable and yes:
            try:
                authorize_plugin_install(
                    "tlc",
                    yes=True,
                    strict=strict,
                    checksum_verified=True,
                    platform_key=platform_name,
                    test_mode=test_mode,
                )
            except StateModelInstallerError as exc:
                receipt.status = "failed"
                receipt.phase = "authorization"
                receipt.reason_codes.append("authorization_failed")
                receipt.messages.append(str(exc))
                if strict:
                    raise
                return receipt
            staging_parent = root / ".staging"
            staging_parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="tlc-launchers-",
                dir=staging_parent,
            ) as temporary:
                temporary_root = Path(temporary)
                launcher, replacements = _stage_tlc_launchers(
                    staging_root=temporary_root / "launchers",
                    install_root=root,
                    jar_path=managed_jar,
                    java_executable=java_runtime.executable,
                )
                manifest_replacement = _stage_tlc_manifest(
                    staging_root=temporary_root / "manifests",
                    install_root=root,
                    jar_path=managed_jar,
                    java_executable=java_runtime.executable,
                )
                staged_probe = probe_tlc_runtime(
                    executable=str(
                        temporary_root / "launchers" / "bin" / TLC_EXECUTABLE
                    ),
                    java_executable=java_runtime.executable,
                )
                _record_tool_runtime(
                    receipt,
                    staged_probe,
                    binding="rebound_launcher_runtime_probe",
                )
                if not staged_probe.usable:
                    return _fail_runtime_validation(
                        receipt,
                        staged_probe,
                        tool_name="TLC",
                        strict=strict,
                    )
                _commit_staged_files(
                    (*replacements, manifest_replacement),
                    backup_dir=temporary_root / "backups",
                )
            receipt.executable_path = str(launcher)
            receipt.jar_path = str(managed_jar)
            receipt.already_present = True
            receipt.install_attempted = True
            receipt.installed = True
            receipt.status = "installed"
            receipt.phase = "managed_identity_repaired"
            receipt.observed_sha256 = TLC_SHA256
            receipt.checksum_verified = True
            receipt.messages.append(
                "Republished the complete TLC launcher/manifest bundle with "
                "the selected JVM"
            )
            return receipt

    if existing and not force:
        public_probe = probe_tlc_runtime(
            executable=existing,
            java_executable=java_runtime.executable,
        )
        _record_tool_runtime(
            receipt,
            public_probe,
            binding="existing_public_launcher_probe",
        )
        if public_probe.usable and not strict:
            receipt.executable_path = existing
            receipt.jar_path = None
            receipt.already_present = True
            receipt.installed = True
            receipt.status = "available"
            receipt.phase = "available"
            receipt.messages.append(
                f"Runnable non-managed TLC accepted at {existing} "
                f"under strict={strict}"
            )
            return receipt
        receipt.messages.append(
            "TLC is present but failed strict identity or bounded runtime "
            "validation."
        )

    if not yes:
        receipt.status = "blocked"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "TLC is missing or mismatched; re-run with yes=True to install "
            "user-locally."
        )
        return receipt

    try:
        authorize_plugin_install(
            "tlc",
            yes=yes,
            strict=strict,
            checksum_verified=None,
            platform_key=platform_name,
            test_mode=test_mode,
        )
    except StateModelInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "authorization"
        receipt.reason_codes.append("authorization_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    receipt.install_attempted = True
    jar_dir = root / "tlc" / pin.version
    jar_path = jar_dir / TLC_JAR_NAME
    staging_parent = root / ".staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="tlc-install-",
        dir=staging_parent,
    ) as temporary:
        temporary_root = Path(temporary)
        staged_jar = temporary_root / "artifact" / TLC_JAR_NAME
        ok, observed = download_artifact(
            pin.artifact_url,
            staged_jar,
            sha256=TLC_SHA256,
            require_checksum=True,
            on_progress=on_progress,
        )
        if (
            not ok
            or observed != TLC_SHA256
            or not staged_jar.is_file()
            or not verify_sha256(staged_jar, TLC_SHA256)
        ):
            receipt.status = "failed"
            receipt.phase = "download"
            receipt.reason_codes.append("download_or_checksum_failed")
            if strict:
                raise StateModelInstallerError("TLC download/checksum failed")
            return receipt
        receipt.checksum_verified = True
        receipt.observed_sha256 = observed
        receipt.bindings["observed_sha256"] = observed
        receipt.bindings["release_tag"] = f"v{pin.version}"

        runtime_probe = probe_tlc_runtime(
            jar_path=staged_jar,
            java_executable=java_runtime.executable,
        )
        _record_tool_runtime(
            receipt,
            runtime_probe,
            binding="post_install_runtime_probe",
        )
        if not runtime_probe.usable:
            return _fail_runtime_validation(
                receipt,
                runtime_probe,
                tool_name="TLC",
                strict=strict,
            )

        validation_launcher = write_launcher(
            TLC_EXECUTABLE,
            staged_jar,
            install_root=temporary_root / "validation",
            java_jar=staged_jar,
            java_main="tlc2.TLC",
            java_executable=java_runtime.executable,
        )
        launcher_probe = probe_tlc_runtime(
            executable=str(validation_launcher),
            java_executable=java_runtime.executable,
        )
        _record_tool_runtime(
            receipt,
            launcher_probe,
            binding="post_install_launcher_probe",
        )
        if not launcher_probe.usable:
            return _fail_runtime_validation(
                receipt,
                launcher_probe,
                tool_name="TLC",
                strict=strict,
            )

        launcher, launcher_replacements = _stage_tlc_launchers(
            staging_root=temporary_root / "publication",
            install_root=root,
            jar_path=jar_path,
            java_executable=java_runtime.executable,
        )
        manifest_replacement = _stage_tlc_manifest(
            staging_root=temporary_root / "manifests",
            install_root=root,
            jar_path=jar_path,
            java_executable=java_runtime.executable,
        )
        _commit_staged_files(
            (
                (staged_jar, jar_path),
                *launcher_replacements,
                manifest_replacement,
            ),
            backup_dir=temporary_root / "backups",
        )

    receipt.executable_path = str(launcher)
    receipt.jar_path = str(jar_path)
    receipt.installed = True
    receipt.status = "installed"
    receipt.phase = "installed"
    receipt.messages.append(
        f"Installed TLC {pin.version} user-locally from reviewed digest "
        f"{TLC_SHA256[:12]}…"
    )
    return receipt


@_serialize_live_install
def ensure_apalache(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
    install_root: str | Path | None = None,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    dry_run: bool = False,
    test_mode: bool = False,
    require_java: bool = True,
    java_executable: str | Path | None = None,
) -> InstallReceipt:
    """Ensure a runnable pinned Apalache 0.58.3 release is user-local."""

    receipt = _base_receipt(
        "apalache",
        requested_version=APALACHE_VERSION,
        yes=yes,
        strict=strict,
    )
    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()

    try:
        pin = select_strict_pin(
            "apalache",
            platform_key=platform_name,
            repo_root=repo_root,
        )
    except StateModelInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "pin_selection"
        receipt.reason_codes.append("pin_selection_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    receipt.selected_version = pin.version
    receipt.selected_platform = pin.platform
    receipt.pin = pin.to_dict()
    receipt.bindings["selected_version"] = pin.version
    receipt.bindings["platform"] = pin.platform

    if dry_run:
        return _dry_run_receipt(receipt, pin, tool_name="Apalache")

    rejected = _reject_java_validation_opt_out(
        receipt,
        require_java=require_java,
        tool_name="Apalache",
    )
    if rejected is not None:
        return rejected

    java_runtime = probe_java_runtime(
        java_executable=java_executable,
        minimum_major=APALACHE_MIN_JAVA_MAJOR,
    )
    _record_java_runtime(receipt, java_runtime)
    receipt.bindings["runtime_validation_required"] = True
    if not java_runtime.usable:
        return _block_for_java_runtime(
            receipt,
            java_runtime,
            tool_name="Apalache",
        )
    assert java_runtime.executable is not None

    managed_bin = root / "bin"
    path_env = os.pathsep.join(
        part
        for part in (str(managed_bin), os.environ.get("PATH", ""))
        if part
    )
    existing = which_executable(
        APALACHE_EXECUTABLE,
        path_env=path_env,
    ) or which_executable("apalache", path_env=path_env)
    managed_identity = (
        managed_apalache_identity(
            root,
            java_executable=java_runtime.executable,
        )
        if not force
        else {}
    )
    receipt.bindings["existing_managed_identity"] = managed_identity
    if managed_identity.get("usable"):
        managed_launcher = managed_bin / APALACHE_EXECUTABLE
        runtime_probe = probe_apalache_runtime(
            str(managed_launcher),
            java_executable=java_runtime.executable,
            expected_version=APALACHE_VERSION,
        )
        _record_tool_runtime(
            receipt,
            runtime_probe,
            binding="existing_runtime_probe",
        )
        if runtime_probe.usable:
            receipt.executable_path = str(managed_launcher)
            receipt.already_present = True
            receipt.installed = True
            receipt.status = "available"
            receipt.phase = "available"
            receipt.checksum_verified = True
            receipt.observed_sha256 = APALACHE_SHA256
            receipt.messages.append(
                f"Apalache already available and runnable at {managed_launcher}"
            )
            return receipt
    repairable_managed = bool(
        managed_identity.get("artifact_digest_verified")
        and managed_identity.get("distribution_tree_verified")
        and managed_identity.get("payload_digest_verified")
    )
    if repairable_managed and not force:
        payload = Path(str(managed_identity["payload_path"]))
        runtime_probe = probe_apalache_runtime(
            str(payload),
            java_executable=java_runtime.executable,
            expected_version=APALACHE_VERSION,
        )
        _record_tool_runtime(
            receipt,
            runtime_probe,
            binding="existing_payload_runtime_probe",
        )
        if runtime_probe.usable and not yes:
            receipt.status = "blocked"
            receipt.phase = "managed_identity"
            receipt.reason_codes.append("managed_identity_repair_required")
            receipt.messages.append(
                "The managed Apalache archive and payload are valid, but the "
                "complete launcher/manifest identity is mismatched; re-run with "
                "yes=True to repair it."
            )
            return receipt
        if runtime_probe.usable and yes:
            try:
                authorize_plugin_install(
                    "apalache",
                    yes=True,
                    strict=strict,
                    checksum_verified=True,
                    platform_key=platform_name,
                    test_mode=test_mode,
                )
            except StateModelInstallerError as exc:
                receipt.status = "failed"
                receipt.phase = "authorization"
                receipt.reason_codes.append("authorization_failed")
                receipt.messages.append(str(exc))
                if strict:
                    raise
                return receipt
            staging_parent = root / ".staging"
            staging_parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="apalache-launchers-",
                dir=staging_parent,
            ) as temporary:
                temporary_root = Path(temporary)
                launcher, launcher_replacements = _stage_apalache_launchers(
                    staging_root=temporary_root / "launchers",
                    install_root=root,
                    binary=payload,
                    java_executable=java_runtime.executable,
                )
                manifest_replacement = _stage_apalache_manifest(
                    staging_root=temporary_root / "manifests",
                    install_root=root,
                    archive_path=Path(str(managed_identity["artifact_path"])),
                    binary_path=payload,
                    payload_sha256=str(managed_identity["payload_sha256"]),
                    distribution_tree_sha256=str(
                        managed_identity["expected_distribution_tree_sha256"]
                    ),
                    java_executable=java_runtime.executable,
                )
                _commit_staged_files(
                    (*launcher_replacements, manifest_replacement),
                    backup_dir=temporary_root / "backups",
                )
            receipt.executable_path = str(launcher)
            receipt.already_present = True
            receipt.install_attempted = True
            receipt.installed = True
            receipt.status = "installed"
            receipt.phase = "managed_identity_repaired"
            receipt.checksum_verified = True
            receipt.observed_sha256 = APALACHE_SHA256
            return receipt

    if existing and not force:
        runtime_probe = probe_apalache_runtime(
            existing,
            java_executable=java_runtime.executable,
            expected_version=None if not strict else APALACHE_VERSION,
        )
        _record_tool_runtime(
            receipt,
            runtime_probe,
            binding="existing_runtime_probe",
        )
        if runtime_probe.usable and not strict:
            receipt.executable_path = existing
            receipt.already_present = True
            receipt.installed = True
            receipt.status = "available"
            receipt.phase = "available"
            receipt.messages.append(
                f"Runnable non-managed Apalache accepted at {existing} "
                "under strict=False"
            )
            return receipt
        receipt.messages.append(
            f"Apalache at {existing} failed exact managed identity or bounded "
            f"runtime validation for {APALACHE_VERSION}; repairing."
        )
        receipt.phase = "repairing"

    if not yes:
        receipt.status = "blocked"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "Apalache is missing or mismatched; re-run with yes=True to install "
            "user-locally."
        )
        return receipt

    try:
        authorize_plugin_install(
            "apalache",
            yes=yes,
            strict=strict,
            checksum_verified=None,
            platform_key=platform_name,
            test_mode=test_mode,
        )
    except StateModelInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "authorization"
        receipt.reason_codes.append("authorization_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    receipt.install_attempted = True
    archive = root / "downloads" / Path(pin.artifact_url).name
    destination = root / f"apalache-{pin.version}"
    staging_parent = root / ".staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="apalache-install-",
        dir=staging_parent,
    ) as temporary:
        temporary_root = Path(temporary)
        staged_archive = temporary_root / "artifact" / Path(pin.artifact_url).name
        ok, observed = download_artifact(
            pin.artifact_url,
            staged_archive,
            sha256=APALACHE_SHA256,
            require_checksum=True,
            on_progress=on_progress,
        )
        if (
            not ok
            or observed != APALACHE_SHA256
            or not staged_archive.is_file()
            or not verify_sha256(staged_archive, APALACHE_SHA256)
        ):
            receipt.status = "failed"
            receipt.phase = "download"
            receipt.reason_codes.append("download_or_checksum_failed")
            if strict:
                raise StateModelInstallerError("Apalache download/checksum failed")
            return receipt
        receipt.checksum_verified = True
        receipt.observed_sha256 = observed
        receipt.bindings["observed_sha256"] = observed
        staged_destination = temporary_root / "installation"
        _safe_extract_tar(staged_archive, staged_destination)
        binary = _find_apalache_binary(staged_destination)
        if binary is None:
            receipt.status = "failed"
            receipt.phase = "extract"
            receipt.reason_codes.append("executable_missing_or_ambiguous")
            if strict:
                raise StateModelInstallerError(
                    "Apalache archive did not contain exactly one apalache-mc"
                )
            return receipt
        binary.chmod(binary.stat().st_mode | 0o111)
        distribution_tree_sha256 = _tree_digest(staged_destination)
        payload_sha256 = content_sha256(binary)
        runtime_probe = probe_apalache_runtime(
            str(binary),
            java_executable=java_runtime.executable,
        )
        _record_tool_runtime(
            receipt,
            runtime_probe,
            binding="post_install_runtime_probe",
        )
        if not runtime_probe.usable:
            return _fail_runtime_validation(
                receipt,
                runtime_probe,
                tool_name="Apalache",
                strict=strict,
            )

        validation_launcher = write_launcher(
            APALACHE_EXECUTABLE,
            binary,
            install_root=temporary_root / "validation",
            java_executable=java_runtime.executable,
        )
        launcher_probe = probe_apalache_runtime(
            str(validation_launcher),
            java_executable=java_runtime.executable,
            expected_version=APALACHE_VERSION,
        )
        _record_tool_runtime(
            receipt,
            launcher_probe,
            binding="post_install_launcher_probe",
        )
        if not launcher_probe.usable:
            return _fail_runtime_validation(
                receipt,
                launcher_probe,
                tool_name="Apalache",
                strict=strict,
            )

        relative_binary = binary.relative_to(staged_destination)
        final_binary = destination / relative_binary
        launcher, launcher_replacements = _stage_apalache_launchers(
            staging_root=temporary_root / "publication",
            install_root=root,
            binary=final_binary,
            java_executable=java_runtime.executable,
        )
        manifest_replacement = _stage_apalache_manifest(
            staging_root=temporary_root / "manifests",
            install_root=root,
            archive_path=archive,
            binary_path=final_binary,
            payload_sha256=payload_sha256,
            distribution_tree_sha256=distribution_tree_sha256,
            java_executable=java_runtime.executable,
        )
        previous = temporary_root / "previous-installation"
        moved_previous = False
        moved_staged = False
        try:
            if destination.exists():
                destination.replace(previous)
                moved_previous = True
            staged_destination.replace(destination)
            moved_staged = True
            _commit_staged_files(
                (
                    (staged_archive, archive),
                    *launcher_replacements,
                    manifest_replacement,
                ),
                backup_dir=temporary_root / "launcher-backups",
            )
        except Exception:
            if moved_staged and destination.exists():
                destination.replace(temporary_root / "failed-installation")
            if moved_previous and previous.exists():
                previous.replace(destination)
            raise

    receipt.executable_path = str(launcher)
    receipt.installed = True
    receipt.status = "installed"
    receipt.phase = "installed"
    receipt.messages.append(f"Installed Apalache {pin.version} user-locally")
    return receipt


def ensure_state_model_portfolio(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
    install_root: str | Path | None = None,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    dry_run: bool = False,
    test_mode: bool = False,
    java_executable: str | Path | None = None,
) -> dict[str, Any]:
    """Ensure both authority tools (TLC + Apalache); Java remains host support."""

    tlc = ensure_tlc(
        yes=yes,
        strict=strict,
        force=force,
        on_progress=on_progress,
        install_root=install_root,
        platform_key=platform_key,
        repo_root=repo_root,
        dry_run=dry_run,
        test_mode=test_mode,
        require_java=False if dry_run else True,
        java_executable=java_executable,
    )
    apalache = ensure_apalache(
        yes=yes,
        strict=strict,
        force=force,
        on_progress=on_progress,
        install_root=install_root,
        platform_key=platform_key,
        repo_root=repo_root,
        dry_run=dry_run,
        test_mode=test_mode,
        require_java=False if dry_run else True,
        java_executable=java_executable,
    )
    if dry_run:
        _, source = _java_candidate(java_executable)
        portfolio_java = JavaRuntimeProbe(
            executable=None,
            source=source,
            minimum_major=APALACHE_MIN_JAVA_MAJOR,
            reason_code="dry_run_not_probed",
        )
    else:
        portfolio_java = probe_java_runtime(
            java_executable=java_executable,
            minimum_major=APALACHE_MIN_JAVA_MAJOR,
        )
    return {
        "family": PLUGIN_FAMILY,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "java_available": portfolio_java.executable is not None,
        "java_usable": portfolio_java.usable,
        "java_runtime": portfolio_java.to_dict(),
        "java_requirements": {
            "tlc_minimum_major": TLC_MIN_JAVA_MAJOR,
            "apalache_minimum_major": APALACHE_MIN_JAVA_MAJOR,
            "override_environment": JAVA_EXECUTABLE_ENV,
        },
        "java_is_support_only": True,
        "java_cannot_promote_tla_lane": True,
        "grants_theorem_authority": False,
        "tlc": tlc.to_dict(),
        "apalache": apalache.to_dict(),
        "both_selected": bool(
            tlc.selected_version == TLC_VERSION
            and apalache.selected_version == APALACHE_VERSION
        ),
        "both_usable": tlc.status in {"available", "installed"}
        and apalache.status in {"available", "installed"}
        and portfolio_java.usable,
    }


def plugin_manifest() -> dict[str, Any]:
    """Describe this family plugin for packaging and certification evidence."""

    registry = default_installer_registry()
    plugin = registry.plugin_for(InstallerPluginFamily.STATE_MODEL)
    entries = [
        entry.to_dict()
        for entry in registry.entries
        if entry.family is InstallerPluginFamily.STATE_MODEL
    ]
    return {
        "interface": PLUGIN_INTERFACE,
        "family": PLUGIN_FAMILY,
        "module_path": PLUGIN_MODULE,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "program": PROGRAM,
        "locked_versions": dict(LOCKED_VERSIONS),
        "locked_artifact_digests": {
            "tlc": TLC_SHA256,
            "apalache": APALACHE_SHA256,
        },
        "java_requirements": {
            "tlc_minimum_major": TLC_MIN_JAVA_MAJOR,
            "apalache_minimum_major": APALACHE_MIN_JAVA_MAJOR,
            "override_environment": JAVA_EXECUTABLE_ENV,
        },
        "ensure_entrypoints": {
            "tlc": "ensure_tlc",
            "apalache": "ensure_apalache",
            "portfolio": "ensure_state_model_portfolio",
        },
        "roles": {
            "tlc": "authority",
            "apalache": "authority",
            "java": "support",
        },
        "authority_ceiling": "bounded",
        "java_is_support_only": True,
        "java_cannot_promote_tla_lane": True,
        "grants_theorem_authority": False,
        "bounded_model_checking_never_theorem": True,
        "plugin": plugin.to_dict(),
        "entries": entries,
        "policy": {
            "never_on_import": True,
            "requires_explicit_yes": True,
            "user_local_only": True,
            "requires_checksum_for_managed_artifacts": True,
            "strict_selects_locked_versions": True,
            "does_not_edit_shared_lock": True,
            "does_not_edit_central_certificate": True,
            "java_never_installed_by_plugin": True,
            "java_version_validated_before_install": True,
            "post_install_runtime_probe_required": True,
            "launcher_binds_selected_java": True,
            "java_option_environment_sanitized": list(JAVA_OPTION_ENV_VARS),
            "dry_run_executes_no_host_tools": True,
            "staged_validation_before_atomic_publication": True,
            "per_root_interprocess_publication_lock": True,
            "complete_launcher_bytes_validated": True,
            "payload_and_distribution_digests_validated": True,
            "require_java_false_live_mode_forbidden": True,
        },
    }


# Import must remain free of install side effects (packaging gate).
IMPORT_INSTALLS_FORBIDDEN: Final = True


__all__ = [
    "PLUGIN_INTERFACE",
    "PLUGIN_FAMILY",
    "PLUGIN_MODULE",
    "GOAL_ID",
    "TASK_ID",
    "PROGRAM",
    "TLC_VERSION",
    "APALACHE_VERSION",
    "TLC_SHA256",
    "APALACHE_SHA256",
    "JAVA_EXECUTABLE_ENV",
    "JAVA_OPTION_ENV_VARS",
    "TLC_MIN_JAVA_MAJOR",
    "APALACHE_MIN_JAVA_MAJOR",
    "LOCKED_VERSIONS",
    "StateModelInstallerError",
    "ToolPin",
    "InstallReceipt",
    "JavaRuntimeProbe",
    "RuntimeCommandProbe",
    "expand_user_local_root",
    "detect_platform_key",
    "which_executable",
    "resolve_java_executable",
    "read_java_version_banner",
    "java_major_version",
    "probe_java_runtime",
    "java_is_available",
    "numeric_version",
    "resolve_lock_path",
    "load_lock_document",
    "pins_for_tool",
    "locked_version_for",
    "select_strict_pin",
    "read_version_banner",
    "read_tlc_version_banner",
    "read_apalache_version_banner",
    "observed_version_matches_lock",
    "probe_tlc_runtime",
    "probe_apalache_runtime",
    "verify_sha256",
    "download_artifact",
    "write_launcher",
    "authorize_plugin_install",
    "ensure_tlc",
    "ensure_apalache",
    "ensure_state_model_portfolio",
    "installation_lock",
    "managed_tlc_identity",
    "managed_apalache_identity",
    "plugin_manifest",
    "IMPORT_INSTALLS_FORBIDDEN",
]
