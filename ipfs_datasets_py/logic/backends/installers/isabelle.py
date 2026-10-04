"""Isabelle reconstruction-kernel installer plugin (FVT-G151 / FVT-049).

``FormalVerificationInstallerPlugin@1`` for the Isabelle lane:

* ``ensure_isabelle`` — pinned Isabelle2025-2 release archive (authority tool)

Fail-closed installation contract
---------------------------------
* never installs on import or capability discovery;
* requires an explicit ``ensure_isabelle`` call with ``yes=True``;
* user-local installs only (no system package manager mutation);
* managed artifacts require checksum verification before extract;
* under ``strict=True``, only the locked pin ``Isabelle2025-2`` is accepted;
* observes an explicit large-download / storage budget before download;
* this plugin never edits the shared multi-prover certificate or lock;
* Hammer remains proposal-only; this installer never grants Hammer proof
  authority.

Pin selection reads ``config/formal_verification_toolchains.lock.json`` when
available and falls back to the reviewed checksum inventory below.
"""

from __future__ import annotations

import hashlib
import gzip
import json
import math
import os
import platform
import posixpath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
from functools import wraps
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass, field
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
PLUGIN_FAMILY: Final = InstallerPluginFamily.ISABELLE.value
PLUGIN_MODULE: Final = "ipfs_datasets_py.logic.backends.installers.isabelle"
GOAL_ID: Final = "FVT-G151"
TASK_ID: Final = "FVT-049"
PROGRAM: Final = "formal-verification-tactician/isabelle-toolchain"

# Locked managed-pin version (must match deployment lock).
ISABELLE_VERSION: Final = "Isabelle2025-2"
ISABELLE_EXECUTABLE: Final = "isabelle"

# Isabelle distribution archives are multi-gigabyte. Explicit budgets keep
# large-kernel installs fail-closed when free space is insufficient.
MAX_DOWNLOAD_BYTES: Final = 6 * 1024 * 1024 * 1024  # 6 GiB hard download cap
MAX_EXTRACTED_BYTES: Final = 24 * 1024**3
MAX_EXTRACTED_FILE_BYTES: Final = 4 * 1024**3
MAX_ARCHIVE_MEMBERS: Final = 200_000  # includes extended tar headers
MAX_ARCHIVE_PATH_BYTES: Final = 4096  # each UTF-8 path / link name
MAX_ARCHIVE_TOTAL_PATH_BYTES: Final = 16 * 1024**2
MIN_EXTRACTION_FREE_BYTES: Final = 1024**3
_COPY_BYTES: Final = 64 * 1024
_MAX_TAR_METADATA_BYTES: Final = 64 * 1024
_MAX_TOTAL_TAR_METADATA_BYTES: Final = 16 * 1024**2
MIN_FREE_STORAGE_BYTES: Final = 12 * 1024 * 1024 * 1024  # 12 GiB free required
EXPECTED_ARCHIVE_SIZE_BYTES: Final = 4 * 1024 * 1024 * 1024  # ~4 GiB typical
DOWNLOAD_TIMEOUT_SECONDS: Final = 3600.0
PROBE_TIMEOUT_SECONDS: Final = 15.0

# Reviewed fallback pins when the lock file is unavailable (tests / offline).
_FALLBACK_PINS: Final[tuple[dict[str, Any], ...]] = (
    {
        "tool_id": "isabelle",
        "version": ISABELLE_VERSION,
        "platform": "linux-x86_64",
        "artifact_url": (
            "https://isabelle.in.tum.de/website-Isabelle2025-2/dist/"
            "Isabelle2025-2_linux.tar.gz"
        ),
        "sha256": (
            "a20a507bc7c1270d8be96a9f3fbec06345387789d2dc2c4d3df6260d47bfb33c"
        ),
        "identity_kind": "release_archive",
    },
    {
        "tool_id": "isabelle",
        "version": ISABELLE_VERSION,
        "platform": "linux-aarch64",
        "artifact_url": (
            "https://isabelle.in.tum.de/website-Isabelle2025-2/dist/"
            "Isabelle2025-2_linux_arm.tar.gz"
        ),
        "sha256": (
            "650a9669b4a087675afb34294d82ded2f0704d47d580dd9ed45cddc9f1764bdd"
        ),
        "identity_kind": "release_archive",
    },
    {
        "tool_id": "isabelle",
        "version": ISABELLE_VERSION,
        "platform": "darwin-x86_64",
        "artifact_url": (
            "https://isabelle.in.tum.de/website-Isabelle2025-2/dist/"
            "Isabelle2025-2_macos.tar.gz"
        ),
        "sha256": (
            "8f187496e295f169952e944745af9e4ae00c9c1cd2ed4cadbcf7d898e444913e"
        ),
        "identity_kind": "release_archive",
    },
    {
        "tool_id": "isabelle",
        "version": ISABELLE_VERSION,
        "platform": "darwin-arm64",
        "artifact_url": (
            "https://isabelle.in.tum.de/website-Isabelle2025-2/dist/"
            "Isabelle2025-2_macos.tar.gz"
        ),
        "sha256": (
            "8f187496e295f169952e944745af9e4ae00c9c1cd2ed4cadbcf7d898e444913e"
        ),
        "identity_kind": "release_archive",
    },
)

LOCKED_VERSIONS: Final[Mapping[str, str]] = {
    "isabelle": ISABELLE_VERSION,
}

ProgressCallback = Callable[[str, str], None]

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_VERSION_TOKEN = re.compile(r"Isabelle\d{4}(?:-\d+)?", re.IGNORECASE)


class IsabelleInstallerError(RuntimeError):
    """Raised when a strict Isabelle install policy is violated."""


class _InstallInterrupted(IsabelleInstallerError):
    pass


def _positive_int(value: int, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _operation_deadline(timeout: float, cancellation: Any, deadline: float | None = None) -> float:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if cancellation is not None and not callable(getattr(cancellation, "is_set", None)):
        raise TypeError("cancellation must supply is_set()")
    own = time.monotonic() + timeout
    return min(own, deadline) if deadline is not None else own


def _check_running(deadline: float, cancellation: Any) -> None:
    if cancellation is not None and cancellation.is_set():
        raise _InstallInterrupted("Isabelle installation cancelled")
    if time.monotonic() >= deadline:
        raise _InstallInterrupted("Isabelle installation deadline exceeded")


def _open_regular(path: Path, max_bytes: int):
    """Open without waiting on a FIFO or following a final symlink."""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            raise IsabelleInstallerError("artifact must be a regular file within its byte cap")
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _bounded_digest(handle, max_bytes: int, deadline: float, cancellation: Any) -> str:
    digest = hashlib.sha256()
    total = 0
    while True:
        _check_running(deadline, cancellation)
        chunk = handle.read(min(_COPY_BYTES, max_bytes - total + 1))
        _check_running(deadline, cancellation)
        total += len(chunk)
        if total > max_bytes:
            raise IsabelleInstallerError("artifact exceeded its cumulative byte cap")
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolPin:
    """One platform-specific managed pin for Isabelle."""

    tool_id: str
    version: str
    platform: str
    artifact_url: str
    sha256: str
    identity_kind: str = "release_archive"

    def __post_init__(self) -> None:
        for name in ("tool_id", "version", "platform", "artifact_url", "sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise IsabelleInstallerError(
                    f"{name} must be a non-empty trimmed string"
                )
        digest = self.sha256.lower()
        if not _HEX64.match(digest):
            raise IsabelleInstallerError(
                f"sha256 for {self.tool_id!r} must be a 64-char lowercase hex digest"
            )
        object.__setattr__(self, "sha256", digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "version": self.version,
            "platform": self.platform,
            "artifact_url": self.artifact_url,
            "sha256": self.sha256,
            "identity_kind": self.identity_kind,
            "is_checksummed": True,
        }


@dataclass(slots=True)
class InstallReceipt:
    """Machine-readable result of one ensure_isabelle invocation."""

    tool_id: str
    requested_version: str
    selected_version: str | None = None
    selected_platform: str | None = None
    executable_path: str | None = None
    install_home: str | None = None
    pin: dict[str, Any] | None = None
    status: str = "blocked"  # available | installed | blocked | failed
    phase: str = "init"
    installed: bool = False
    already_present: bool = False
    checksum_verified: bool = False
    strict: bool = True
    yes: bool = False
    user_local: bool = True
    support_only: bool = False
    authority_tool: bool = True
    install_attempted: bool = False
    download_attempted: bool = False
    storage_budget_ok: bool = False
    reason_codes: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    bindings: dict[str, Any] = field(default_factory=dict)

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
    candidate = Path(name)
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate.resolve())

    search_path = path_env
    if search_path is None:
        managed_bin = expand_user_local_root() / "bin"
        parts = [str(managed_bin)] if managed_bin.is_dir() else []
        parts.append(os.environ.get("PATH", ""))
        search_path = os.pathsep.join(p for p in parts if p)
    found = shutil.which(name, path=search_path)
    return found


def content_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _announce(
    message: str,
    on_progress: ProgressCallback | None,
    *,
    phase: str = "info",
) -> None:
    if on_progress is not None:
        on_progress(phase, message)


def free_storage_bytes(path: Path) -> int:
    """Return free bytes available for installs under ``path``."""

    target = path
    while not target.exists() and target != target.parent:
        target = target.parent
    usage = shutil.disk_usage(str(target if target.exists() else Path.home()))
    return int(usage.free)


def check_storage_budget(
    install_root: Path,
    *,
    min_free_bytes: int = MIN_FREE_STORAGE_BYTES,
    max_download_bytes: int = MAX_DOWNLOAD_BYTES,
    expected_archive_bytes: int = EXPECTED_ARCHIVE_SIZE_BYTES,
) -> dict[str, Any]:
    """Evaluate the large-kernel download/storage budget before installing.

    Returns a report with ``ok`` True only when free space meets the minimum
    and the expected archive size is within the hard download cap.
    """

    free = free_storage_bytes(install_root)
    archive_ok = 0 < expected_archive_bytes <= max_download_bytes
    free_ok = free >= min_free_bytes
    return {
        "ok": bool(archive_ok and free_ok),
        "free_bytes": free,
        "min_free_bytes": min_free_bytes,
        "max_download_bytes": max_download_bytes,
        "expected_archive_bytes": expected_archive_bytes,
        "archive_within_download_cap": archive_ok,
        "free_space_sufficient": free_ok,
        "reason_codes": (
            []
            if archive_ok and free_ok
            else (
                (["archive_exceeds_download_cap"] if not archive_ok else [])
                + (["insufficient_free_storage"] if not free_ok else [])
            )
        ),
    }


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
        raise IsabelleInstallerError("deployment lock must be a JSON object")
    return payload


def pins_for_tool(
    tool_id: str = "isabelle",
    *,
    repo_root: Path | str | None = None,
    lock: Mapping[str, Any] | None = None,
) -> tuple[ToolPin, ...]:
    """Return managed pins for Isabelle from the lock or reviewed fallbacks."""

    if tool_id != "isabelle":
        raise IsabelleInstallerError(
            f"isabelle installer plugin does not own tool_id={tool_id!r}"
        )

    document = lock if lock is not None else load_lock_document(repo_root)
    pins: list[ToolPin] = []
    if document is not None:
        tools = document.get("tools") or []
        if not isinstance(tools, list):
            raise IsabelleInstallerError("deployment lock tools must be a list")
        for entry in tools:
            if not isinstance(entry, Mapping):
                continue
            if str(entry.get("tool_id") or "") != tool_id:
                continue
            for raw in entry.get("pins") or []:
                if not isinstance(raw, Mapping):
                    continue
                pins.append(
                    ToolPin(
                        tool_id=str(raw.get("tool_id") or tool_id),
                        version=str(raw.get("version") or ""),
                        platform=str(raw.get("platform") or ""),
                        artifact_url=str(raw.get("artifact_url") or ""),
                        sha256=str(raw.get("sha256") or "").lower(),
                        identity_kind=str(
                            raw.get("identity_kind")
                            or entry.get("identity_kind")
                            or "release_archive"
                        ),
                    )
                )
            break
    if not pins:
        for raw in _FALLBACK_PINS:
            pins.append(
                ToolPin(
                    tool_id=str(raw["tool_id"]),
                    version=str(raw["version"]),
                    platform=str(raw["platform"]),
                    artifact_url=str(raw["artifact_url"]),
                    sha256=str(raw["sha256"]),
                    identity_kind=str(raw.get("identity_kind") or "release_archive"),
                )
            )
    if not pins:
        raise IsabelleInstallerError(f"no managed pins registered for {tool_id!r}")
    return tuple(pins)


def locked_version_for(
    tool_id: str = "isabelle",
    *,
    lock: Mapping[str, Any] | None = None,
) -> str:
    """Return the exact managed pin version required under strict install."""

    if tool_id != "isabelle":
        raise IsabelleInstallerError(f"no locked version for tool_id={tool_id!r}")
    if lock is not None:
        versions = lock.get("managed_pin_versions") or {}
        if isinstance(versions, Mapping) and tool_id in versions:
            return str(versions[tool_id])
    return LOCKED_VERSIONS[tool_id]


def select_strict_pin(
    tool_id: str = "isabelle",
    *,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    lock: Mapping[str, Any] | None = None,
    allow_source_fallback: bool = False,
) -> ToolPin:
    """Select the exact locked Isabelle pin for the host platform.

    Under the FVT-G151 contract this is the only pin that strict installation
    may materialize. Version mismatches fail closed rather than upgrading.
    """

    if tool_id != "isabelle":
        raise IsabelleInstallerError(
            f"isabelle installer plugin does not own tool_id={tool_id!r}"
        )
    platform_name = platform_key or detect_platform_key()
    expected = locked_version_for(tool_id, lock=lock)
    candidates = pins_for_tool(tool_id, repo_root=repo_root, lock=lock)
    exact = [
        pin
        for pin in candidates
        if pin.version == expected and pin.platform == platform_name
    ]
    if exact:
        return exact[0]
    if allow_source_fallback:
        source = [
            pin
            for pin in candidates
            if pin.version == expected and pin.platform == "source"
        ]
        if source:
            return source[0]
    available = sorted({f"{pin.platform}@{pin.version}" for pin in candidates})
    raise IsabelleInstallerError(
        f"strict install for {tool_id!r} requires version {expected!r} on "
        f"platform {platform_name!r}; available pins: {available}"
    )


# ---------------------------------------------------------------------------
# Version / runtime probes
# ---------------------------------------------------------------------------


def read_version_banner(
    executable: str,
    *,
    timeout: float = PROBE_TIMEOUT_SECONDS,
    extra_args: Sequence[str] = ("version",),
) -> str | None:
    """Read Isabelle identity. Prefer ``isabelle version`` over ``--version``."""

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


def extract_isabelle_version_token(banner: str | None) -> str | None:
    if not banner:
        return None
    match = _VERSION_TOKEN.search(banner)
    if match is None:
        # Some builds print just "Isabelle2025-2" as the sole line.
        stripped = banner.strip().splitlines()[0].strip() if banner.strip() else ""
        if stripped.startswith("Isabelle"):
            return stripped.split()[0]
        return None
    return match.group(0)


def observed_version_matches_lock(banner: str | None, expected: str = ISABELLE_VERSION) -> bool:
    if not banner:
        return False
    if expected in banner:
        return True
    token = extract_isabelle_version_token(banner)
    return bool(token and token == expected)


# ---------------------------------------------------------------------------
# Artifact download / extract (user-local)
# ---------------------------------------------------------------------------


def probe_theory_processor(executable: str) -> bool:
    """Distinguish a modern usable launcher from a version-only stub."""
    try:
        result = subprocess.run([executable, "process_theories", "-?"],
                                capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS,
                                shell=False, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode in (0, 1) and "Usage: isabelle process_theories" in result.stdout + result.stderr


def verify_sha256(path: Path, expected: str) -> bool:
    return content_sha256(path) == expected.lower()


def download_artifact(
    url: str,
    destination: Path,
    *,
    sha256: str,
    timeout: float = DOWNLOAD_TIMEOUT_SECONDS,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    on_progress: ProgressCallback | None = None,
    cancellation: Any | None = None,
    _deadline: float | None = None,
    _temporary_directory: Path | None = None,
) -> bool:
    """Stream a pinned artifact, preserving the destination on any failure.

    Cache hashing and downloads have cumulative byte bounds. The deadline is
    cooperative: DNS, HTTP headers and individual socket operations can delay
    checks; socket inactivity is capped at ten seconds. Atomic replacement is
    visibility, not a directory-fsync crash-durability guarantee. This helper
    does not provide scheduler admission or subprocess resource containment.
    An admitted worker may supply its existing private staging directory for
    partial files, keeping hard-kill leftovers inside controller quarantine.
    That directory must share a filesystem with the destination for replace.
    """
    max_bytes = _positive_int(max_bytes, "max_bytes")
    deadline = _operation_deadline(timeout, cancellation, _deadline)
    if not isinstance(sha256, str) or not _HEX64.fullmatch(sha256.lower()):
        raise ValueError("sha256 must be a 64-character hexadecimal digest")
    destination = Path(destination)
    temporary: Path | None = None
    try:
        _check_running(deadline, cancellation)
        # lstat includes FIFOs and dangling symlinks; neither is a cache miss.
        if destination.exists() or destination.is_symlink():
            with _open_regular(destination, max_bytes) as cached:
                digest = _bounded_digest(cached, max_bytes, deadline, cancellation)
            if digest == sha256.lower():
                _announce(f"Reusing checksummed artifact at {destination}", on_progress, phase="available")
                _check_running(deadline, cancellation)
                return True
        _announce(f"Downloading {url}", on_progress, phase="downloading")
        _check_running(deadline, cancellation)
        destination.parent.mkdir(parents=True, exist_ok=True)
        request = Request(url, headers={"User-Agent": "ipfs-datasets-py-isabelle-installer/1"})
        with urlopen(request, timeout=min(10.0, max(0.001, deadline - time.monotonic()))) as response:
            _check_running(deadline, cancellation)
            content_length = response.headers.get("Content-Length")
            declared = None
            if content_length is not None:
                if not isinstance(content_length, str) or not re.fullmatch(r"[0-9]{1,20}", content_length):
                    raise IsabelleInstallerError("invalid Content-Length")
                declared = int(content_length)
                if declared > max_bytes:
                    raise IsabelleInstallerError("Content-Length exceeds download byte cap")
            descriptor, name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".partial",
                                               dir=destination.parent if _temporary_directory is None else _temporary_directory)
            temporary = Path(name)
            hasher = hashlib.sha256()
            total = 0
            with os.fdopen(descriptor, "wb") as handle:
                while True:
                    _check_running(deadline, cancellation)
                    read = getattr(response, "read1", response.read)
                    chunk = read(min(_COPY_BYTES, max_bytes - total + 1))
                    _check_running(deadline, cancellation)
                    total += len(chunk)
                    if total > max_bytes:
                        raise IsabelleInstallerError("download exceeded its cumulative byte cap")
                    if declared is not None and total > declared:
                        raise IsabelleInstallerError("download exceeds declared Content-Length")
                    if not chunk:
                        break
                    hasher.update(chunk)
                    handle.write(chunk)
                if declared is not None and total != declared:
                    raise IsabelleInstallerError("download does not match declared Content-Length")
                if hasher.hexdigest() != sha256.lower():
                    raise IsabelleInstallerError("checksum mismatch; refusing install")
                _check_running(deadline, cancellation)
                handle.flush()
                os.fsync(handle.fileno())
            _check_running(deadline, cancellation)
            temporary.replace(destination)
            temporary = None
        return True
    except Exception as exc:
        _announce(f"Download failed: {exc}", on_progress, phase="failed")
        return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _safe_extract_tar(
    archive: Path,
    destination: Path,
    *,
    max_archive_bytes: int = MAX_DOWNLOAD_BYTES,
    max_expanded_bytes: int = MAX_EXTRACTED_BYTES,
    max_file_bytes: int = MAX_EXTRACTED_FILE_BYTES,
    max_members: int = MAX_ARCHIVE_MEMBERS,
    max_path_bytes: int = MAX_ARCHIVE_PATH_BYTES,
    max_total_path_bytes: int = MAX_ARCHIVE_TOTAL_PATH_BYTES,
    min_free_bytes: int = MIN_EXTRACTION_FREE_BYTES,
    timeout: float = DOWNLOAD_TIMEOUT_SECONDS,
    cancellation: Any | None = None,
    _deadline: float | None = None,
) -> None:
    """Extract a bounded tar stream into an empty, private staging directory.

    Only directories, regular files and contained relative links are accepted.
    Sparse files, devices, FIFOs, duplicate files and writes through links are
    refused. Header bounds apply *before* tarfile allocates PAX/longname data.
    Checks are cooperative, including filesystem I/O and decompression; this is
    not a native CPU/RSS guard. The caller owns removal of failed staging trees.
    """
    for name, value in (("max_archive_bytes", max_archive_bytes), ("max_expanded_bytes", max_expanded_bytes),
                        ("max_file_bytes", max_file_bytes), ("max_members", max_members),
                        ("max_path_bytes", max_path_bytes), ("max_total_path_bytes", max_total_path_bytes)):
        _positive_int(value, name)
    if type(min_free_bytes) is not int or min_free_bytes < 0:
        raise ValueError("min_free_bytes must be a nonnegative integer")
    deadline = _operation_deadline(timeout, cancellation, _deadline)
    _check_running(deadline, cancellation)
    destination = Path(destination)
    if destination.is_symlink():
        raise IsabelleInstallerError("extraction destination must not be a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    if next(destination.iterdir(), None) is not None:
        raise IsabelleInstallerError("extraction destination must be empty")
    root = destination.resolve()
    header_count = metadata_bytes = header_depth = total_paths = expanded = 0

    class LimitedTarInfo(tarfile.TarInfo):
        def _proc_member(self, handle):
            nonlocal header_count, metadata_bytes, header_depth
            _check_running(deadline, cancellation)
            header_count += 1
            header_depth += 1
            try:
                if header_count > max_members or header_depth > 16:
                    raise IsabelleInstallerError("archive member/header count exceeded")
                if self.size < 0:
                    raise IsabelleInstallerError("negative archive member size")
                extended = self.type in (tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK,
                                         tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE)
                if extended:
                    metadata_bytes += self.size
                    if self.size > _MAX_TAR_METADATA_BYTES or metadata_bytes > _MAX_TOTAL_TAR_METADATA_BYTES:
                        raise IsabelleInstallerError("archive metadata byte cap exceeded")
                elif self.size > max_file_bytes:
                    raise IsabelleInstallerError("archive per-file byte cap exceeded")
                result = super()._proc_member(handle)
                if result.size < 0 or result.size > max_file_bytes:
                    raise IsabelleInstallerError("archive per-file byte cap exceeded")
                if sum(len(str(k)) + len(str(v)) for k, v in handle.pax_headers.items()) > _MAX_TAR_METADATA_BYTES:
                    raise IsabelleInstallerError("archive global metadata byte cap exceeded")
                return result
            finally:
                header_depth -= 1

        def _proc_sparse(self, *_):
            raise IsabelleInstallerError("sparse archive members are unsupported")

        _proc_gnusparse_00 = _proc_sparse
        _proc_gnusparse_01 = _proc_sparse
        _proc_gnusparse_10 = _proc_sparse

    class LimitedReader:
        def __init__(self, handle, cap, label):
            self.handle = handle
            self.total = 0
            self.cap = cap
            self.label = label

        def read(self, size):
            _check_running(deadline, cancellation)
            size = min(size, _COPY_BYTES) if size >= 0 else _COPY_BYTES
            data = self.handle.read(min(size, self.cap - self.total + 1))
            _check_running(deadline, cancellation)
            self.total += len(data)
            if self.total > self.cap:
                raise IsabelleInstallerError(f"archive exceeded {self.label} byte cap")
            return data

    def checked_name(name: str) -> str:
        nonlocal total_paths
        size = len(name.encode("utf-8", errors="strict"))
        total_paths += size
        if not name or size > max_path_bytes or total_paths > max_total_path_bytes or "\x00" in name or "\\" in name:
            raise IsabelleInstallerError("archive path byte cap or encoding violated")
        if name.startswith("/") or any(part == ".." for part in name.split("/")) or len(name.split("/")) > 64:
            raise IsabelleInstallerError("archive path escapes destination or exceeds depth cap")
        return posixpath.normpath(name)

    def checked_parents(path: Path) -> None:
        # Never follow an archive-created or pre-existing link during writes.
        relative = path.relative_to(root)
        current = root
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise IsabelleInstallerError("archive extraction through a symlink is forbidden")
            current.mkdir(exist_ok=True)
            if not current.is_dir():
                raise IsabelleInstallerError("archive parent is not a directory")

    def storage_check(required: int = 0) -> None:
        _check_running(deadline, cancellation)
        if free_storage_bytes(root) < min_free_bytes + required:
            raise IsabelleInstallerError("insufficient extraction disk headroom")

    def _extract_stream(inflated):
        nonlocal expanded, total_paths
        with tarfile.open(fileobj=inflated, mode="r|", tarinfo=LimitedTarInfo) as handle:
            for member in handle:
                _check_running(deadline, cancellation)
                # Streaming extraction must not retain all prior TarInfo objects.
                handle.members.clear()
                relative = checked_name(member.name)
                path = root / relative
                checked_parents(path)
                storage_check()
                if member.isdir():
                    if member.size or path.is_symlink():
                        raise IsabelleInstallerError("invalid archive directory")
                    path.mkdir(exist_ok=True)
                    continue
                if path.exists() or path.is_symlink():
                    raise IsabelleInstallerError("duplicate archive output path")
                if member.isreg() and not member.sparse:
                    expanded += member.size
                    if expanded > max_expanded_bytes:
                        raise IsabelleInstallerError("archive expanded byte cap exceeded")
                    storage_check(member.size)
                    source = handle.extractfile(member)
                    if source is None:
                        raise IsabelleInstallerError("archive regular file has no data")
                    remaining = member.size
                    with source, path.open("xb") as output:
                        while remaining:
                            storage_check(min(remaining, _COPY_BYTES))
                            chunk = source.read(min(remaining, _COPY_BYTES))
                            _check_running(deadline, cancellation)
                            if not chunk:
                                raise IsabelleInstallerError("truncated archive member")
                            output.write(chunk)
                            remaining -= len(chunk)
                    # Preserve executable bits, never setuid/setgid/sticky bits.
                    path.chmod(member.mode & 0o777)
                elif member.issym() or member.islnk():
                    if member.size:
                        raise IsabelleInstallerError("archive link carries payload")
                    link = member.linkname
                    link_bytes = len(link.encode("utf-8", errors="strict"))
                    total_paths += link_bytes
                    if not link or link.startswith("/") or "\x00" in link or "\\" in link or link_bytes > max_path_bytes or total_paths > max_total_path_bytes:
                        raise IsabelleInstallerError("invalid archive link path")
                    target_name = posixpath.normpath(posixpath.join(posixpath.dirname(relative), link) if member.issym() else link)
                    if target_name == ".." or target_name.startswith("../") or len(target_name.split("/")) > 64:
                        raise IsabelleInstallerError("archive link escapes destination")
                    target = root / target_name
                    if not target.resolve().is_relative_to(root):
                        raise IsabelleInstallerError("archive link resolves outside destination")
                    if member.issym():
                        path.symlink_to(link)
                    else:
                        if target.is_symlink() or not target.is_file():
                            raise IsabelleInstallerError("hardlink target must be an earlier regular file")
                        # Parent symlinks are forbidden even for link sources.
                        checked_parents(target)
                        os.link(target, path, follow_symlinks=False)
                else:
                    raise IsabelleInstallerError("unsupported nonregular archive member")
                storage_check()
            _check_running(deadline, cancellation)
            # Consume bounded tar padding through gzip EOF to verify its CRC
            # and length trailer. Hidden payload after the tar terminator is not
            # a second installation stream.
            while True:
                trailing = handle.fileobj.read(_COPY_BYTES)
                _check_running(deadline, cancellation)
                if not trailing:
                    break
                if any(trailing):
                    raise IsabelleInstallerError("nonzero data after tar terminator")

    with _open_regular(Path(archive), max_archive_bytes) as raw:
        _check_running(deadline, cancellation)
        magic = raw.read(6)
        _check_running(deadline, cancellation)
        raw.seek(0)
        if magic.startswith((b"BZh", b"\xfd7zXZ\x00")):
            raise IsabelleInstallerError("only gzip or plain tar archives are supported")
        reader = LimitedReader(raw, max_archive_bytes, "compressed")
        # Avoid tarfile's automatic xz/bz2 decompression, whose dictionaries and
        # returned blocks can allocate before a TarInfo reaches our guards.
        stream = gzip.GzipFile(fileobj=reader, mode="rb") if magic.startswith(b"\x1f\x8b") else None
        raw_tar_cap = max_expanded_bytes + _MAX_TOTAL_TAR_METADATA_BYTES + max_members * 1024 + _COPY_BYTES
        with stream if stream is not None else nullcontext(reader) as uncompressed:
            inflated = LimitedReader(uncompressed, raw_tar_cap, "decompressed stream")
            _extract_stream(inflated)


def write_launcher(
    name: str,
    target: Path,
    *,
    install_root: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Write a user-local launcher script under ``$root/bin/<name>``."""

    root = expand_user_local_root(install_root)
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / name
    env_exports = ""
    if environment:
        lines = [
            f"export {key}={_shell_quote(value)}"
            for key, value in environment.items()
        ]
        env_exports = "\n".join(lines) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{name}.", suffix=".new", dir=bin_dir)
    temporary_launcher = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("#!/usr/bin/env bash\n"
                         "set -euo pipefail\n"
                         f"{env_exports}"
                         f'exec {_shell_quote(str(target.resolve()))} "$@"\n')
            handle.flush()
            os.fchmod(handle.fileno(), 0o755)
            os.fsync(handle.fileno())
        temporary_launcher.replace(launcher)
    finally:
        temporary_launcher.unlink(missing_ok=True)
    return launcher


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def locate_isabelle_binary(install_home: Path) -> Path | None:
    """Find the ``isabelle`` launcher inside an extracted distribution."""

    direct = install_home / "bin" / "isabelle"
    if direct.is_file() and os.access(direct, os.X_OK):
        return direct
    matches = [
        path
        for path in install_home.rglob("isabelle")
        if path.is_file() and os.access(path, os.X_OK) and path.name == "isabelle"
    ]
    # Prefer bin/isabelle over other helpers when multiple matches exist.
    preferred = [path for path in matches if path.parent.name == "bin"]
    if len(preferred) == 1:
        return preferred[0]
    if len(matches) == 1:
        return matches[0]
    return preferred[0] if preferred else (matches[0] if matches else None)


# ---------------------------------------------------------------------------
# Install authorization gate
# ---------------------------------------------------------------------------


def authorize_plugin_install(
    tool_id: str = "isabelle",
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
    """Fail-closed gate shared by ensure_isabelle."""

    if tool_id != "isabelle":
        raise IsabelleInstallerError(
            f"isabelle plugin does not own tool_id={tool_id!r}"
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
        raise IsabelleInstallerError(str(exc)) from exc
    entry = get_installer_entry(tool_id)
    if entry.family is not InstallerPluginFamily.ISABELLE:
        raise IsabelleInstallerError(
            f"tool {tool_id!r} is not bound to the isabelle installer plugin"
        )
    if strict:
        select_strict_pin(tool_id, platform_key=platform_key)


# ---------------------------------------------------------------------------
# ensure_* entry point
# ---------------------------------------------------------------------------


_INSTALL_MUTEX = threading.RLock()


@contextmanager
def installation_lock(root: Path, *, checkpoint):
    """Serialize legacy and bounded installation, including cancellable waits.

    The caller supplies its own deadline/cancellation checkpoint. This lock is
    also held for publication and ordinary-exception rollback.
    """
    acquired = False
    try:
        while not acquired:
            checkpoint()
            acquired = _INSTALL_MUTEX.acquire(timeout=0.05)
        checkpoint()
        root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(root / ".isabelle-install.lock", os.O_RDWR | os.O_CREAT |
                             getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "r+") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise IsabelleInstallerError("install lock must be a regular file")
            try:
                import fcntl
            except ImportError:
                checkpoint()
                yield
                return
            locked = False
            try:
                while not locked:
                    checkpoint()
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                    except BlockingIOError:
                        time.sleep(0.05)
                checkpoint()
                yield
            finally:
                if locked:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        if acquired:
            _INSTALL_MUTEX.release()


def _serialized_install(function):
    @wraps(function)
    def wrapped(**kwargs):
        cancellation = kwargs.get("cancellation")
        deadline = _operation_deadline(kwargs.get("timeout_seconds", DOWNLOAD_TIMEOUT_SECONDS), cancellation)
        kwargs["_deadline"] = deadline
        try:
            _check_running(deadline, cancellation)
            if not kwargs.get("yes", False) or kwargs.get("dry_run", False):
                return function(**kwargs)
            root = expand_user_local_root(kwargs.get("install_root"))
            with installation_lock(root, checkpoint=lambda: _check_running(deadline, cancellation)):
                return function(**kwargs)
        except _InstallInterrupted as exc:
            if kwargs.get("strict", True):
                raise
            return InstallReceipt(tool_id="isabelle", requested_version=ISABELLE_VERSION,
                                  yes=kwargs.get("yes", False), strict=False, status="failed", phase="interrupted",
                                  reason_codes=["cancelled" if cancellation is not None and cancellation.is_set() else "deadline_exceeded"],
                                  messages=[str(exc)])
    return wrapped


@_serialized_install
def ensure_isabelle(
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
    lock: Mapping[str, Any] | None = None,
    skip_storage_budget: bool = False,
    timeout_seconds: float = DOWNLOAD_TIMEOUT_SECONDS,
    cancellation: Any | None = None,
    max_download_bytes: int = MAX_DOWNLOAD_BYTES,
    max_expanded_bytes: int = MAX_EXTRACTED_BYTES,
    max_file_bytes: int = MAX_EXTRACTED_FILE_BYTES,
    max_members: int = MAX_ARCHIVE_MEMBERS,
    max_path_bytes: int = MAX_ARCHIVE_PATH_BYTES,
    max_total_path_bytes: int = MAX_ARCHIVE_TOTAL_PATH_BYTES,
    min_extraction_free_bytes: int = MIN_EXTRACTION_FREE_BYTES,
    _deadline: float | None = None,
) -> InstallReceipt:
    """Ensure the pinned Isabelle2025-2 reconstruction kernel is present.

    Strict mode selects only the locked release archive for the host platform.
    Installation is user-local, checksummed, and gated on an explicit large
    download/storage budget. Never installs on import. Download, extraction and
    lock waits share a cooperative deadline/cancellation signal. Legacy native
    probes retain their separate subprocess timeout and are not resource-owner
    admitted; use the installed-runtime preparation API for qualified probes.
    """

    deadline = _operation_deadline(timeout_seconds, cancellation, _deadline)
    for name, value in (("max_download_bytes", max_download_bytes), ("max_expanded_bytes", max_expanded_bytes),
                        ("max_file_bytes", max_file_bytes), ("max_members", max_members),
                        ("max_path_bytes", max_path_bytes), ("max_total_path_bytes", max_total_path_bytes)):
        _positive_int(value, name)
    if type(min_extraction_free_bytes) is not int or min_extraction_free_bytes < 0:
        raise ValueError("min_extraction_free_bytes must be a nonnegative integer")
    _check_running(deadline, cancellation)

    receipt = InstallReceipt(
        tool_id="isabelle",
        requested_version=ISABELLE_VERSION,
        strict=strict,
        yes=yes,
        support_only=False,
        authority_tool=True,
    )
    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()

    try:
        pin = select_strict_pin(
            "isabelle",
            platform_key=platform_name,
            repo_root=repo_root,
            lock=lock,
        )
    except IsabelleInstallerError as exc:
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
    receipt.bindings = {
        "tool_id": "isabelle",
        "locked_version": ISABELLE_VERSION,
        "selected_version": pin.version,
        "platform": pin.platform,
        "role": "authority",
        "authority_ceiling": "kernel",
        "authority_scope": "kernel_proof_checking_only",
        "hammer_is_proposal_only": True,
        "hammer_cannot_grant_kernel_authority": True,
        "large_download_budget_bytes": max_download_bytes,
        "min_free_storage_bytes": MIN_FREE_STORAGE_BYTES,
        "does_not_edit_shared_lock": True,
        "does_not_edit_central_certificate": True,
        "archive_limits": {"compressed_bytes": max_download_bytes, "expanded_bytes": max_expanded_bytes,
                           "per_file_bytes": max_file_bytes, "member_headers": max_members,
                           "path_bytes": max_path_bytes, "total_path_bytes": max_total_path_bytes,
                           "minimum_free_bytes": min_extraction_free_bytes},
        "archive_limits_scope": "cooperative_io_and_expansion_not_native_process_containment",
    }

    managed = root / "bin" / ISABELLE_EXECUTABLE
    existing = (str(managed) if managed.is_file() and os.access(managed, os.X_OK) else None) if install_root is not None else which_executable(ISABELLE_EXECUTABLE)
    if existing and not force:
        banner = read_version_banner(existing) or ""
        _check_running(deadline, cancellation)
        version_ok = observed_version_matches_lock(banner, ISABELLE_VERSION)
        theory_processor_ok = probe_theory_processor(existing)
        _check_running(deadline, cancellation)
        receipt.bindings["theory_processing_ready"] = theory_processor_ok
        if theory_processor_ok and (version_ok or not strict):
            receipt.executable_path = existing
            receipt.already_present = True
            receipt.installed = True
            receipt.status = "available"
            receipt.phase = "available"
            receipt.storage_budget_ok = True
            receipt.messages.append(
                f"Isabelle {ISABELLE_VERSION} already available at {existing}"
            )
            receipt.bindings["version_banner"] = banner
            return receipt
        receipt.messages.append(f"Isabelle at {existing} needs a pinned, process_theories-capable runtime.")
        receipt.phase = "repairing"
        receipt.reason_codes.append("locked_version_mismatch" if not version_ok else "theory_processor_unavailable")

    budget = check_storage_budget(root, max_download_bytes=max_download_bytes,
                                  expected_archive_bytes=min(EXPECTED_ARCHIVE_SIZE_BYTES, max_download_bytes))
    receipt.storage_budget_ok = bool(budget["ok"])
    receipt.bindings["storage_budget"] = budget

    if dry_run:
        receipt.status = "blocked" if not yes else "available"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        if not budget["ok"] and not skip_storage_budget:
            receipt.reason_codes.extend(list(budget["reason_codes"]))
        receipt.messages.append(
            f"dry-run selected Isabelle {pin.version} for {pin.platform}"
        )
        return receipt

    if not yes:
        receipt.status = "blocked"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "Isabelle is missing or mismatched; re-run with yes=True to install "
            "user-locally under the large-kernel storage budget."
        )
        return receipt

    if not budget["ok"] and not skip_storage_budget:
        receipt.status = "blocked"
        receipt.phase = "storage_budget"
        receipt.reason_codes.extend(list(budget["reason_codes"]) or ["storage_budget_failed"])
        receipt.messages.append(
            "Insufficient free storage or archive exceeds the large-kernel "
            f"download budget (free={budget['free_bytes']}, "
            f"min={budget['min_free_bytes']}, max_download={budget['max_download_bytes']})."
        )
        return receipt

    try:
        authorize_plugin_install(
            "isabelle",
            yes=yes,
            strict=strict,
            checksum_verified=True,
            platform_key=platform_name,
            test_mode=test_mode,
        )
    except IsabelleInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "authorization"
        receipt.reason_codes.append("authorization_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    archive_name = Path(pin.artifact_url).name or f"{pin.version}_{pin.platform}.tar.gz"
    archive = root / "downloads" / archive_name
    destination = root / pin.version
    receipt.install_attempted = True
    receipt.download_attempted = True
    if not download_artifact(
        pin.artifact_url,
        archive,
        sha256=pin.sha256,
        on_progress=on_progress,
        timeout=timeout_seconds,
        max_bytes=max_download_bytes,
        cancellation=cancellation,
        _deadline=deadline,
    ):
        _check_running(deadline, cancellation)
        receipt.status = "failed"
        receipt.phase = "download"
        receipt.reason_codes.append("download_or_checksum_failed")
        if strict:
            raise IsabelleInstallerError("Isabelle download/checksum failed")
        return receipt
    receipt.checksum_verified = True
    _announce(
        f"Extracting Isabelle {pin.version} into {destination}",
        on_progress,
        phase="extracting",
    )
    # Validate an extracted staging tree before touching an existing install.
    # A unique staging directory also avoids colliding with interrupted extracts.
    with tempfile.TemporaryDirectory(prefix=".extract-isabelle-", dir=root) as directory:
        extract_root = Path(directory)
        try:
            _safe_extract_tar(archive, extract_root, max_archive_bytes=max_download_bytes,
                              max_expanded_bytes=max_expanded_bytes, max_file_bytes=max_file_bytes,
                              max_members=max_members, max_path_bytes=max_path_bytes,
                              max_total_path_bytes=max_total_path_bytes, min_free_bytes=min_extraction_free_bytes,
                              timeout=timeout_seconds, cancellation=cancellation, _deadline=deadline)
        except (IsabelleInstallerError, OSError, tarfile.TarError) as exc:
            if strict or isinstance(exc, _InstallInterrupted):
                raise
            receipt.status = "failed"
            receipt.phase = "extract"
            receipt.reason_codes.append("archive_extraction_failed")
            receipt.messages.append(str(exc))
            return receipt
        _check_running(deadline, cancellation)
        nested = extract_root / pin.version
        candidate = nested if nested.is_dir() else extract_root
        staged_binary = locate_isabelle_binary(candidate)
        if staged_binary is None:
            receipt.status = "failed"
            receipt.phase = "extract"
            receipt.reason_codes.append("executable_missing")
            if strict:
                raise IsabelleInstallerError("Isabelle archive missing executable")
            return receipt
        banner = read_version_banner(str(staged_binary)) or ""
        _check_running(deadline, cancellation)
        if strict and not observed_version_matches_lock(banner, ISABELLE_VERSION):
            raise IsabelleInstallerError("staged Isabelle does not match the locked version")
        theory_ready = probe_theory_processor(str(staged_binary))
        _check_running(deadline, cancellation)
        if not theory_ready:
            receipt.status = "failed"
            receipt.phase = "validation"
            receipt.reason_codes.append("theory_processor_unavailable")
            if strict:
                raise IsabelleInstallerError("staged Isabelle lacks process_theories")
            return receipt
        backup = root / f".previous-{pin.version}"
        launcher = root / "bin" / ISABELLE_EXECUTABLE
        launcher_backup = launcher.with_name(".isabelle.previous")
        if backup.exists() or backup.is_symlink() or launcher_backup.exists() or launcher_backup.is_symlink():
            raise IsabelleInstallerError("Unresolved previous install; refusing overwrite")
        if candidate.is_symlink():
            raise IsabelleInstallerError("distribution root must not be a symlink")
        _check_running(deadline, cancellation)
        moved_tree = moved_launcher = published_tree = launcher_touched = False
        try:
            if destination.exists() or destination.is_symlink():
                destination.replace(backup)
                moved_tree = True
            candidate.replace(destination)
            published_tree = True
            binary = locate_isabelle_binary(destination)
            if binary is None:
                raise IsabelleInstallerError("published Isabelle archive missing executable")
            if launcher.exists() or launcher.is_symlink():
                launcher.replace(launcher_backup)
                moved_launcher = True
            launcher_touched = True
            write_launcher(ISABELLE_EXECUTABLE, binary, install_root=root,
                           environment={"ISABELLE_HOME": str(destination.resolve())})
            _check_running(deadline, cancellation)
            banner = read_version_banner(str(launcher)) or ""
            _check_running(deadline, cancellation)
            if strict and not observed_version_matches_lock(banner, ISABELLE_VERSION):
                raise IsabelleInstallerError("installed Isabelle does not match the locked version")
            theory_ready = probe_theory_processor(str(launcher))
            _check_running(deadline, cancellation)
            if not theory_ready:
                raise IsabelleInstallerError("installed Isabelle does not provide process_theories")
        except BaseException as exc:
            # Keep both previous paths until validation finishes. This is an
            # exception rollback, not a crash-atomic multi-path transaction.
            if launcher_touched:
                launcher.unlink(missing_ok=True)
            if moved_launcher:
                launcher_backup.replace(launcher)
            if published_tree:
                shutil.rmtree(destination)
            if moved_tree:
                backup.replace(destination)
            if strict or not isinstance(exc, Exception) or isinstance(exc, _InstallInterrupted):
                raise
            receipt.status = "failed"
            receipt.phase = "validation"
            receipt.reason_codes.append("publication_validation_failed")
            receipt.messages.append(str(exc))
            return receipt
        # After validated publication, finish required cleanup. The previous
        # installation may predate these archive limits; cleanup latency is
        # not a hard wall bound and this is not a filesystem quota.
        if moved_tree:
            if backup.is_symlink() or not backup.is_dir():
                backup.unlink()
            else:
                shutil.rmtree(backup)
        if moved_launcher:
            launcher_backup.unlink()
    receipt.executable_path = str(launcher)
    receipt.install_home = str(destination.resolve())
    receipt.bindings["theory_processing_ready"] = True
    receipt.installed = True
    receipt.status = "installed"
    receipt.phase = "installed"
    receipt.bindings["version_banner"] = banner
    receipt.bindings["install_home"] = receipt.install_home
    receipt.messages.append(f"Installed Isabelle {pin.version} user-locally")
    return receipt


def _try_legacy_ensure(
    *,
    yes: bool,
    strict: bool,
    force: bool,
    on_progress: ProgressCallback | None,
) -> bool:
    """Optionally delegate to the historical prover_installer bridge."""

    try:
        from ipfs_datasets_py.logic.integration.bridges import prover_installer
    except Exception:
        return False
    try:
        ensure = getattr(prover_installer, "ensure_isabelle", None)
        if ensure is None:
            return False
        return bool(
            ensure(yes=yes, strict=strict, force=force, on_progress=on_progress)
        )
    except Exception:
        return False


def plugin_manifest() -> dict[str, Any]:
    """Describe this family plugin for packaging and certification evidence."""

    registry = default_installer_registry()
    plugin = registry.plugin_for(InstallerPluginFamily.ISABELLE)
    entries = [
        entry.to_dict()
        for entry in registry.entries
        if entry.family is InstallerPluginFamily.ISABELLE
    ]
    return {
        "interface": PLUGIN_INTERFACE,
        "family": PLUGIN_FAMILY,
        "module_path": PLUGIN_MODULE,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "program": PROGRAM,
        "locked_versions": dict(LOCKED_VERSIONS),
        "ensure_entrypoints": {
            "isabelle": "ensure_isabelle",
        },
        "roles": {
            "isabelle": "authority",
            "hammer": "advisor",
        },
        "hammer_is_proposal_only": True,
        "hammer_cannot_grant_kernel_authority": True,
        "authority_ceiling": "kernel",
        "authority_scope": "kernel_proof_checking_only",
        "large_download_budget_bytes": MAX_DOWNLOAD_BYTES,
        "min_free_storage_bytes": MIN_FREE_STORAGE_BYTES,
        "plugin": plugin.to_dict(),
        "entries": entries,
        "policy": {
            "never_on_import": True,
            "requires_explicit_yes": True,
            "user_local_only": True,
            "requires_checksum_for_managed_artifacts": True,
            "strict_selects_locked_versions": True,
            "observes_large_download_storage_budget": True,
            "does_not_edit_shared_lock": True,
            "does_not_edit_central_certificate": True,
            "hammer_remains_proposal_only": True,
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
    "ISABELLE_VERSION",
    "ISABELLE_EXECUTABLE",
    "LOCKED_VERSIONS",
    "MAX_DOWNLOAD_BYTES",
    "MIN_FREE_STORAGE_BYTES",
    "EXPECTED_ARCHIVE_SIZE_BYTES",
    "IsabelleInstallerError",
    "ToolPin",
    "InstallReceipt",
    "expand_user_local_root",
    "detect_platform_key",
    "which_executable",
    "free_storage_bytes",
    "check_storage_budget",
    "resolve_lock_path",
    "load_lock_document",
    "pins_for_tool",
    "locked_version_for",
    "select_strict_pin",
    "read_version_banner",
    "extract_isabelle_version_token",
    "observed_version_matches_lock",
    "verify_sha256",
    "download_artifact",
    "write_launcher",
    "locate_isabelle_binary",
    "authorize_plugin_install",
    "ensure_isabelle",
    "plugin_manifest",
    "IMPORT_INSTALLS_FORBIDDEN",
]
