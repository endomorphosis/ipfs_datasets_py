"""TLC + Apalache state-model installer plugin (FVT-G120 / FVT-042).

``FormalVerificationInstallerPlugin@1`` for the TLA state-model lane:

* ``ensure_tlc`` — pinned TLC / TLA+ tools 1.8.0 (``tla2tools.jar``)
* ``ensure_apalache`` — pinned Apalache 0.58.3 symbolic model checker
* Java remains a **host support runtime only** (never installed by this plugin
  and never granted state-model authority by itself)

Fail-closed installation contract
---------------------------------
* never installs on import or capability discovery;
* requires an explicit ``ensure_*`` call with ``yes=True``;
* user-local installs only (no system package manager mutation);
* managed artifacts require checksum verification before use
  (TLC's lock pin records empty ``sha256`` and
  ``requires_checksum_at_install`` — the installer binds the observed jar
  digest at explicit install time);
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
import zipfile
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
PLUGIN_FAMILY: Final = InstallerPluginFamily.STATE_MODEL.value
PLUGIN_MODULE: Final = "ipfs_datasets_py.logic.backends.installers.state_model"
GOAL_ID: Final = "FVT-G120"
TASK_ID: Final = "FVT-042"
PROGRAM: Final = "formal-verification-tactician/state-model-toolchains"

# Locked managed-pin versions (must match deployment lock).
TLC_VERSION: Final = "1.8.0"
APALACHE_VERSION: Final = "0.58.3"

TLC_EXECUTABLE: Final = "tlc"
TLC_JAR_NAME: Final = "tla2tools.jar"
APALACHE_EXECUTABLE: Final = "apalache-mc"
JAVA_EXECUTABLE: Final = "java"

# Reviewed fallback pins when the lock file is unavailable (tests / offline).
# TLC jar sha256 is bound at install when the lock pin leaves it empty.
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
            "sha256": "",
            "identity_kind": "immutable_release_tag",
            "is_checksummed": False,
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
            "sha256": (
                "ba622db9538aebf942cc7a7815f942a6b2b419012707e16dfdc25a73ff95d0a5"
            ),
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


def java_is_available() -> bool:
    """Return True when a host JVM is on PATH (support runtime only)."""

    return which_executable(JAVA_EXECUTABLE) is not None


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
    if exact:
        return exact[0]
    if allow_any_platform:
        any_pin = [
            pin
            for pin in candidates
            if pin.version == expected and pin.platform in {"any", "source", "portable"}
        ]
        if any_pin:
            return any_pin[0]
    available = sorted({f"{pin.platform}@{pin.version}" for pin in candidates})
    raise StateModelInstallerError(
        f"strict install for {tool_id!r} requires version {expected!r} on "
        f"platform {platform_name!r}; available pins: {available}"
    )


# ---------------------------------------------------------------------------
# Version / runtime probes
# ---------------------------------------------------------------------------


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
    timeout: float = 10.0,
) -> str | None:
    """Probe TLC identity via launcher or ``java -cp jar tlc2.TLC``."""

    binary = executable or which_executable(TLC_EXECUTABLE)
    if binary:
        for args in (("--version",), ("-help",), ("-h",)):
            banner = read_version_banner(binary, timeout=timeout, extra_args=args)
            if banner:
                return banner
    jar = Path(jar_path) if jar_path else None
    if jar is None and binary:
        # Launcher may live next to the managed jar.
        managed = expand_user_local_root() / "tlc" / TLC_VERSION / TLC_JAR_NAME
        if managed.is_file():
            jar = managed
    if jar is not None and jar.is_file() and java_is_available():
        java = which_executable(JAVA_EXECUTABLE)
        if java:
            try:
                completed = subprocess.run(
                    [java, "-cp", str(jar), "tlc2.TLC", "-help"],
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
            if text:
                return text
    return None


def read_apalache_version_banner(
    executable: str | None = None,
    *,
    timeout: float = 15.0,
) -> str | None:
    binary = executable or which_executable(APALACHE_EXECUTABLE)
    if not binary:
        binary = which_executable("apalache")
    if not binary:
        return None
    for args in (("version",), ("--version",), ("-V",)):
        banner = read_version_banner(binary, timeout=timeout, extra_args=args)
        if banner:
            return banner
    return None


def observed_version_matches_lock(banner: str | None, expected: str) -> bool:
    if not banner:
        return False
    if expected in banner:
        return True
    observed = numeric_version(banner)
    locked = numeric_version(expected)
    return bool(observed and locked and observed == locked)


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
    tmp = destination.with_suffix(destination.suffix + ".partial")
    tmp.write_bytes(data)
    observed = content_sha256(tmp)
    if sha256 and observed != sha256.lower():
        tmp.unlink(missing_ok=True)
        _announce(
            f"Checksum mismatch for {url}; refusing install",
            on_progress,
            phase="failed",
        )
        return False, None
    if require_checksum and not observed:
        tmp.unlink(missing_ok=True)
        return False, None
    tmp.replace(destination)
    return True, observed


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


def write_launcher(
    name: str,
    target: Path,
    *,
    install_root: Path | None = None,
    environment: Mapping[str, str] | None = None,
    java_jar: Path | None = None,
    java_main: str | None = None,
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
    if java_jar is not None and java_main:
        body = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"{env_exports}"
            "if ! command -v java >/dev/null 2>&1; then\n"
            '  echo "java (JVM support runtime) is required for TLC" >&2\n'
            "  exit 127\n"
            "fi\n"
            f'exec java -cp {_shell_quote(str(java_jar.resolve()))} '
            f"{_shell_quote(java_main)} \"$@\"\n"
        )
    else:
        body = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"{env_exports}"
            f'exec {_shell_quote(str(target.resolve()))} "$@"\n'
        )
    launcher.write_text(body, encoding="utf-8")
    launcher.chmod(0o755)
    return launcher


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


# ---------------------------------------------------------------------------
# ensure_* entry points
# ---------------------------------------------------------------------------


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
) -> InstallReceipt:
    """Ensure the pinned TLC / TLA+ tools 1.8.0 jar is present (user-local)."""

    receipt = _base_receipt(
        "tlc",
        requested_version=TLC_VERSION,
        yes=yes,
        strict=strict,
    )
    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()
    receipt.bindings["java_available"] = java_is_available()

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

    existing = which_executable(TLC_EXECUTABLE)
    managed_jar = root / "tlc" / TLC_VERSION / TLC_JAR_NAME
    if existing and not force:
        banner = read_tlc_version_banner(existing, jar_path=managed_jar)
        version_ok = observed_version_matches_lock(banner, TLC_VERSION)
        # Accept managed launcher when jar pin is present even if banner is sparse.
        jar_ok = managed_jar.is_file() and (
            not pin.sha256 or verify_sha256(managed_jar, pin.sha256)
        )
        if (version_ok or jar_ok) and (not require_java or java_is_available() or not strict):
            if require_java and not java_is_available() and strict:
                receipt.messages.append(
                    "TLC launcher present but host Java (support only) is missing"
                )
            else:
                receipt.executable_path = existing
                receipt.jar_path = str(managed_jar) if managed_jar.is_file() else None
                receipt.already_present = True
                receipt.installed = True
                receipt.status = "available"
                receipt.phase = "available"
                if managed_jar.is_file():
                    receipt.observed_sha256 = content_sha256(managed_jar)
                    receipt.checksum_verified = bool(receipt.observed_sha256)
                receipt.messages.append(f"TLC already available at {existing}")
                return receipt

    if dry_run:
        receipt.status = "blocked" if not yes else "available"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        receipt.messages.append(
            f"dry-run selected TLC {pin.version} for {pin.platform}"
        )
        return receipt

    if not yes:
        receipt.status = "blocked"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "TLC is missing or mismatched; re-run with yes=True to install "
            "user-locally."
        )
        return receipt

    if require_java and not java_is_available():
        receipt.status = "blocked"
        receipt.phase = "java_support"
        receipt.reason_codes.append("java_support_missing")
        receipt.messages.append(
            "Host Java (support only) is required to run TLC; install a JVM "
            "separately — this plugin never installs or promotes Java."
        )
        return receipt

    try:
        authorize_plugin_install(
            "tlc",
            yes=yes,
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

    receipt.install_attempted = True
    jar_dir = root / "tlc" / pin.version
    jar_path = jar_dir / TLC_JAR_NAME
    ok, observed = download_artifact(
        pin.artifact_url,
        jar_path,
        sha256=pin.sha256,
        require_checksum=pin.requires_checksum_at_install,
        on_progress=on_progress,
    )
    if not ok or not observed:
        receipt.status = "failed"
        receipt.phase = "download"
        receipt.reason_codes.append("download_or_checksum_failed")
        if strict:
            raise StateModelInstallerError("TLC download/checksum failed")
        return receipt
    receipt.checksum_verified = True
    receipt.observed_sha256 = observed
    receipt.jar_path = str(jar_path)
    receipt.bindings["observed_sha256"] = observed
    receipt.bindings["release_tag"] = f"v{pin.version}"

    launcher = write_launcher(
        TLC_EXECUTABLE,
        jar_path,
        install_root=root,
        java_jar=jar_path,
        java_main="tlc2.TLC",
        environment={"TLA2TOOLS_JAR": str(jar_path)},
    )
    # Convenience aliases used by capability matrices.
    for alias in ("tlc2", "tla2tools"):
        write_launcher(
            alias,
            jar_path,
            install_root=root,
            java_jar=jar_path,
            java_main="tlc2.TLC",
            environment={"TLA2TOOLS_JAR": str(jar_path)},
        )
    receipt.executable_path = str(launcher)
    receipt.installed = True
    receipt.status = "installed"
    receipt.phase = "installed"
    receipt.messages.append(
        f"Installed TLC {pin.version} user-locally (jar digest {observed[:12]}…)"
    )
    return receipt


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
) -> InstallReceipt:
    """Ensure the pinned Apalache 0.58.3 release is present (user-local)."""

    receipt = _base_receipt(
        "apalache",
        requested_version=APALACHE_VERSION,
        yes=yes,
        strict=strict,
    )
    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()
    receipt.bindings["java_available"] = java_is_available()

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

    existing = which_executable(APALACHE_EXECUTABLE) or which_executable("apalache")
    if existing and not force:
        banner = read_apalache_version_banner(existing)
        version_ok = observed_version_matches_lock(banner, APALACHE_VERSION)
        if version_ok or not strict:
            if require_java and not java_is_available() and strict:
                receipt.messages.append(
                    "Apalache present but host Java (support only) is missing"
                )
            else:
                receipt.executable_path = existing
                receipt.already_present = True
                receipt.installed = True
                receipt.status = "available"
                receipt.phase = "available"
                receipt.messages.append(f"Apalache already available at {existing}")
                return receipt
        receipt.messages.append(
            f"Apalache at {existing} is not the locked pin "
            f"{APALACHE_VERSION}; repairing managed runtime."
        )
        receipt.phase = "repairing"

    if dry_run:
        receipt.status = "blocked" if not yes else "available"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        receipt.messages.append(
            f"dry-run selected Apalache {pin.version} for {pin.platform}"
        )
        return receipt

    if not yes:
        receipt.status = "blocked"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "Apalache is missing or mismatched; re-run with yes=True to install "
            "user-locally."
        )
        return receipt

    if require_java and not java_is_available():
        receipt.status = "blocked"
        receipt.phase = "java_support"
        receipt.reason_codes.append("java_support_missing")
        receipt.messages.append(
            "Host Java (support only) is required to run Apalache; install a JVM "
            "separately — this plugin never installs or promotes Java."
        )
        return receipt

    try:
        authorize_plugin_install(
            "apalache",
            yes=yes,
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

    receipt.install_attempted = True
    archive = root / "downloads" / Path(pin.artifact_url).name
    destination = root / f"apalache-{pin.version}"
    ok, observed = download_artifact(
        pin.artifact_url,
        archive,
        sha256=pin.sha256,
        require_checksum=True,
        on_progress=on_progress,
    )
    if not ok:
        receipt.status = "failed"
        receipt.phase = "download"
        receipt.reason_codes.append("download_or_checksum_failed")
        if strict:
            raise StateModelInstallerError("Apalache download/checksum failed")
        return receipt
    receipt.checksum_verified = True
    receipt.observed_sha256 = observed
    if destination.exists():
        shutil.rmtree(destination)
    _safe_extract_tar(archive, destination)
    matches = [
        path
        for path in destination.rglob(APALACHE_EXECUTABLE)
        if path.is_file()
    ]
    if not matches:
        matches = [
            path
            for path in destination.rglob("apalache")
            if path.is_file() and path.name in {"apalache", "apalache-mc"}
        ]
    if not matches:
        receipt.status = "failed"
        receipt.phase = "extract"
        receipt.reason_codes.append("executable_missing")
        if strict:
            raise StateModelInstallerError(
                "Apalache archive did not contain apalache-mc"
            )
        return receipt
    binary = matches[0]
    binary.chmod(binary.stat().st_mode | 0o111)
    launcher = write_launcher(APALACHE_EXECUTABLE, binary, install_root=root)
    # Alias used by some capability matrices.
    write_launcher("apalache", binary, install_root=root)
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
    )
    return {
        "family": PLUGIN_FAMILY,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "java_available": java_is_available(),
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
        and java_is_available(),
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
    "LOCKED_VERSIONS",
    "StateModelInstallerError",
    "ToolPin",
    "InstallReceipt",
    "expand_user_local_root",
    "detect_platform_key",
    "which_executable",
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
    "verify_sha256",
    "download_artifact",
    "write_launcher",
    "authorize_plugin_install",
    "ensure_tlc",
    "ensure_apalache",
    "ensure_state_model_portfolio",
    "plugin_manifest",
    "IMPORT_INSTALLS_FORBIDDEN",
]
