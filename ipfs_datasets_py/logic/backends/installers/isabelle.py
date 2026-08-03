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
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
from collections.abc import Callable, Mapping, Sequence
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
) -> bool:
    """Download ``url`` to ``destination`` and verify the checksum.

    Enforces the large-kernel download budget: refuses responses that exceed
    ``max_bytes``. Never mutates system package managers. Callers must already
    hold ``yes=True`` authorization.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and verify_sha256(destination, sha256):
        if destination.stat().st_size > max_bytes:
            destination.unlink(missing_ok=True)
            _announce(
                f"Cached artifact exceeds download budget of {max_bytes} bytes",
                on_progress,
                phase="failed",
            )
            return False
        _announce(
            f"Reusing checksummed artifact at {destination}",
            on_progress,
            phase="available",
        )
        return True
    _announce(f"Downloading {url}", on_progress, phase="downloading")
    request = Request(
        url,
        headers={"User-Agent": "ipfs-datasets-py-isabelle-installer/1"},
    )
    tmp = destination.with_suffix(destination.suffix + ".partial")
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - reviewed pin URL
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared = int(content_length)
                except ValueError:
                    declared = -1
                if declared > max_bytes:
                    _announce(
                        f"Remote Content-Length {declared} exceeds download budget "
                        f"{max_bytes}; refusing download",
                        on_progress,
                        phase="failed",
                    )
                    return False
            hasher = hashlib.sha256()
            total = 0
            with tmp.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        handle.close()
                        tmp.unlink(missing_ok=True)
                        _announce(
                            f"Download exceeded budget of {max_bytes} bytes",
                            on_progress,
                            phase="failed",
                        )
                        return False
                    hasher.update(chunk)
                    handle.write(chunk)
    except Exception as exc:  # pragma: no cover - network failures host-specific
        tmp.unlink(missing_ok=True)
        _announce(f"Download failed: {exc}", on_progress, phase="failed")
        return False
    digest = hasher.hexdigest()
    if digest != sha256.lower():
        tmp.unlink(missing_ok=True)
        _announce(
            f"Checksum mismatch for {url}; refusing install",
            on_progress,
            phase="failed",
        )
        return False
    tmp.replace(destination)
    return True


def _safe_extract_tar(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as handle:
        try:
            handle.extractall(destination, filter="data")  # type: ignore[call-arg]
        except TypeError:  # pragma: no cover
            handle.extractall(destination)


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
    launcher.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"{env_exports}"
        f'exec {_shell_quote(str(target.resolve()))} "$@"\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
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
) -> InstallReceipt:
    """Ensure the pinned Isabelle2025-2 reconstruction kernel is present.

    Strict mode selects only the locked release archive for the host platform.
    Installation is user-local, checksummed, and gated on an explicit large
    download/storage budget. Never installs on import.
    """

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
        "large_download_budget_bytes": MAX_DOWNLOAD_BYTES,
        "min_free_storage_bytes": MIN_FREE_STORAGE_BYTES,
        "does_not_edit_shared_lock": True,
        "does_not_edit_central_certificate": True,
    }

    existing = which_executable(ISABELLE_EXECUTABLE)
    if existing and not force:
        banner = read_version_banner(existing) or ""
        version_ok = observed_version_matches_lock(banner, ISABELLE_VERSION)
        if version_ok or not strict:
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
        receipt.messages.append(
            f"Isabelle at {existing} is not the locked pin {ISABELLE_VERSION}; "
            "repairing managed runtime."
        )
        receipt.phase = "repairing"
        receipt.reason_codes.append("locked_version_mismatch")

    budget = check_storage_budget(root)
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

    if _try_legacy_ensure(
        yes=yes, strict=strict, force=force, on_progress=on_progress
    ):
        path = which_executable(ISABELLE_EXECUTABLE)
        if path and (
            not strict
            or observed_version_matches_lock(
                read_version_banner(path), ISABELLE_VERSION
            )
        ):
            receipt.executable_path = path
            receipt.installed = True
            receipt.install_attempted = True
            receipt.status = "installed"
            receipt.phase = "installed"
            receipt.checksum_verified = True
            receipt.messages.append(
                f"Installed Isabelle {ISABELLE_VERSION} via managed installer"
            )
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
    ):
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
    if destination.exists():
        shutil.rmtree(destination)
    extract_root = root / f".extract-{pin.version}"
    if extract_root.exists():
        shutil.rmtree(extract_root)
    _safe_extract_tar(archive, extract_root)
    # Archives typically nest Isabelle2025-2/ at the top level.
    nested = extract_root / pin.version
    if nested.is_dir():
        nested.replace(destination)
        shutil.rmtree(extract_root, ignore_errors=True)
    else:
        # Flat extract or alternate nesting: move extract_root into place.
        if destination.exists():
            shutil.rmtree(destination)
        extract_root.replace(destination)

    binary = locate_isabelle_binary(destination)
    if binary is None:
        receipt.status = "failed"
        receipt.phase = "extract"
        receipt.reason_codes.append("executable_missing")
        if strict:
            raise IsabelleInstallerError("Isabelle archive missing executable")
        return receipt

    launcher = write_launcher(
        ISABELLE_EXECUTABLE,
        binary,
        install_root=root,
        environment={
            "ISABELLE_HOME": str(destination.resolve()),
        },
    )
    banner = read_version_banner(str(launcher)) or ""
    if strict and not observed_version_matches_lock(banner, ISABELLE_VERSION):
        receipt.status = "failed"
        receipt.phase = "validation"
        receipt.reason_codes.append("locked_version_mismatch")
        receipt.executable_path = str(launcher)
        receipt.install_home = str(destination)
        receipt.messages.append(
            f"Installed Isabelle did not report locked version {ISABELLE_VERSION}"
        )
        if strict:
            raise IsabelleInstallerError(
                f"installed Isabelle is not the locked pin {ISABELLE_VERSION}"
            )
        return receipt

    receipt.executable_path = str(launcher)
    receipt.install_home = str(destination.resolve())
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
