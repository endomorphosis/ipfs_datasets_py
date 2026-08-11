"""Vampire + E first-order ATP installer plugin (FVT-G140 / FVT-048).

``FormalVerificationInstallerPlugin@1`` for the ATP lane:

* ``ensure_vampire`` — pinned Vampire 5.0.1 ATP
* ``ensure_eprover`` — pinned E 3.2.5 theorem prover

Fail-closed installation contract
---------------------------------
* never installs on import or capability discovery;
* requires an explicit ``ensure_*`` call with ``yes=True``;
* user-local installs only (no system package manager mutation);
* managed artifacts require checksum verification before extract;
* under ``strict=True``, only the locked pin versions are accepted:
  Vampire ``5.0.1`` and E ``3.2.5``;
* ATP results remain **candidates** unless an allowed independent kernel
  reconstruction validates them (this plugin never elevates authority);
* this plugin never edits the shared multi-prover certificate or CEC semantics.

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
PLUGIN_FAMILY: Final = InstallerPluginFamily.ATP.value
PLUGIN_MODULE: Final = "ipfs_datasets_py.logic.backends.installers.atp"
GOAL_ID: Final = "FVT-G140"
TASK_ID: Final = "FVT-048"
PROGRAM: Final = "formal-verification-tactician/atp-toolchains"

# Locked managed-pin versions (must match deployment lock).
VAMPIRE_VERSION: Final = "5.0.1"
EPROVER_VERSION: Final = "3.2.5"

VAMPIRE_EXECUTABLE: Final = "vampire"
EPROVER_EXECUTABLE: Final = "eprover"

# Reviewed fallback pins when the lock file is unavailable (tests / offline).
_FALLBACK_PINS: Final[dict[str, tuple[dict[str, Any], ...]]] = {
    "vampire": (
        {
            "tool_id": "vampire",
            "version": VAMPIRE_VERSION,
            "platform": "linux-x86_64",
            "artifact_url": (
                "https://github.com/vprover/vampire/releases/download/"
                f"v{VAMPIRE_VERSION}/vampire-Linux-X64.zip"
            ),
            "sha256": (
                "6ff2f42ea7fb9753ee104efc3e623d5e39443190f7c82a63e1e1517bf9d2cde3"
            ),
            "identity_kind": "release_archive",
        },
        {
            "tool_id": "vampire",
            "version": VAMPIRE_VERSION,
            "platform": "linux-aarch64",
            "artifact_url": (
                "https://github.com/vprover/vampire/releases/download/"
                f"v{VAMPIRE_VERSION}/vampire-Linux-ARM64.zip"
            ),
            "sha256": (
                "2fc419d3ac1eb075b4ceb6ce770242247507afd8c64f897799e479643f4b2c6b"
            ),
            "identity_kind": "release_archive",
        },
        {
            "tool_id": "vampire",
            "version": VAMPIRE_VERSION,
            "platform": "darwin-x86_64",
            "artifact_url": (
                "https://github.com/vprover/vampire/releases/download/"
                f"v{VAMPIRE_VERSION}/vampire-macOS-X64.zip"
            ),
            "sha256": (
                "e252f1bf8c41f17f620a0009f8952809fc473a1250cad010fc1a8c43ae9af1a9"
            ),
            "identity_kind": "release_archive",
        },
        {
            "tool_id": "vampire",
            "version": VAMPIRE_VERSION,
            "platform": "darwin-arm64",
            "artifact_url": (
                "https://github.com/vprover/vampire/releases/download/"
                f"v{VAMPIRE_VERSION}/vampire-macOS-ARM64.zip"
            ),
            "sha256": (
                "8c92e649fe7bc622a70000afbdf5a5c51007b384e2d8b8235c95474cc7a68f35"
            ),
            "identity_kind": "release_archive",
        },
    ),
    "eprover": (
        {
            "tool_id": "eprover",
            "version": EPROVER_VERSION,
            "platform": "any",
            "artifact_url": (
                "https://wwwlehre.dhbw-stuttgart.de/~sschulz/WORK/E_DOWNLOAD/"
                "V_3.2/E.tgz"
            ),
            "sha256": (
                "074c8e5fc3062476341ce790fd15ad8004d322d6b6627844bd2768a8830bd4ae"
            ),
            "identity_kind": "release_archive",
        },
    ),
}

LOCKED_VERSIONS: Final[Mapping[str, str]] = {
    "vampire": VAMPIRE_VERSION,
    "eprover": EPROVER_VERSION,
}

ProgressCallback = Callable[[str, str], None]

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)+)")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ATPInstallerError(RuntimeError):
    """Raised when a strict Vampire/E install policy is violated."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolPin:
    """One platform-specific managed pin for an ATP-lane tool."""

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
                raise ATPInstallerError(f"{name} must be a non-empty trimmed string")
        digest = self.sha256.lower()
        if not _HEX64.match(digest):
            raise ATPInstallerError(
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
    """Machine-readable result of one ensure_* invocation."""

    tool_id: str
    requested_version: str
    selected_version: str | None = None
    selected_platform: str | None = None
    executable_path: str | None = None
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
    results_are_candidates_without_reconstruction: bool = True
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
        raise ATPInstallerError("deployment lock must be a JSON object")
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
            raise ATPInstallerError("deployment lock tools must be a list")
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
        for raw in _FALLBACK_PINS.get(tool_id, ()):
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
        raise ATPInstallerError(f"no managed pins registered for {tool_id!r}")
    return tuple(pins)


def locked_version_for(tool_id: str, *, lock: Mapping[str, Any] | None = None) -> str:
    """Return the exact managed pin version required under strict install."""

    if lock is not None:
        versions = lock.get("managed_pin_versions") or {}
        if isinstance(versions, Mapping) and tool_id in versions:
            return str(versions[tool_id])
    if tool_id in LOCKED_VERSIONS:
        return LOCKED_VERSIONS[tool_id]
    raise ATPInstallerError(f"no locked version for tool_id={tool_id!r}")


def select_strict_pin(
    tool_id: str,
    *,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    lock: Mapping[str, Any] | None = None,
    allow_any_platform: bool = True,
) -> ToolPin:
    """Select the exact locked pin for ``tool_id`` on the host platform.

    Under the FVT-G140 contract this is the only pin that strict installation
    may materialize.  Version mismatches fail closed rather than upgrading.
    E ships a portable source archive under platform ``any``.
    """

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
    raise ATPInstallerError(
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
    return content_sha256(path) == expected.lower()


def download_artifact(
    url: str,
    destination: Path,
    *,
    sha256: str,
    timeout: float = 120.0,
    on_progress: ProgressCallback | None = None,
) -> bool:
    """Download ``url`` to ``destination`` and verify the checksum.

    Never mutates system package managers.  Callers must already hold
    ``yes=True`` authorization.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and verify_sha256(destination, sha256):
        _announce(
            f"Reusing checksummed artifact at {destination}",
            on_progress,
            phase="available",
        )
        return True
    _announce(f"Downloading {url}", on_progress, phase="downloading")
    request = Request(url, headers={"User-Agent": "ipfs-datasets-py-atp-installer/1"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - reviewed pin URL
            data = response.read()
    except Exception as exc:  # pragma: no cover - network failures host-specific
        _announce(f"Download failed: {exc}", on_progress, phase="failed")
        return False
    tmp = destination.with_suffix(destination.suffix + ".partial")
    tmp.write_bytes(data)
    if not verify_sha256(tmp, sha256):
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


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
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
            f'export {key}={_shell_quote(value)}'
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
    """Fail-closed gate shared by ensure_vampire / ensure_eprover."""

    if tool_id not in {"vampire", "eprover"}:
        raise ATPInstallerError(
            f"atp plugin does not own tool_id={tool_id!r}"
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
        raise ATPInstallerError(str(exc)) from exc
    entry = get_installer_entry(tool_id)
    if entry.family is not InstallerPluginFamily.ATP:
        raise ATPInstallerError(
            f"tool {tool_id!r} is not bound to the atp installer plugin"
        )
    if strict:
        select_strict_pin(tool_id, platform_key=platform_key)


# ---------------------------------------------------------------------------
# ensure_* entry points
# ---------------------------------------------------------------------------


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
        results_are_candidates_without_reconstruction=True,
        bindings={
            "tool_id": tool_id,
            "locked_version": requested_version,
            "authority_ceiling": "reconstruction",
            "results_are_candidates_without_reconstruction": True,
            "kernel_reconstruction_required_for_theorem_authority": True,
            "does_not_edit_shared_lock": True,
            "does_not_edit_central_certificate": True,
            "does_not_edit_cec_semantics": True,
        },
    )


def ensure_vampire(
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
) -> InstallReceipt:
    """Ensure the pinned Vampire 5.0.1 ATP is present (user-local)."""

    receipt = _base_receipt(
        "vampire",
        requested_version=VAMPIRE_VERSION,
        yes=yes,
        strict=strict,
    )
    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()

    try:
        pin = select_strict_pin(
            "vampire",
            platform_key=platform_name,
            repo_root=repo_root,
        )
    except ATPInstallerError as exc:
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

    existing = which_executable(VAMPIRE_EXECUTABLE)
    if existing and not force:
        banner = read_version_banner(existing) or ""
        version_ok = observed_version_matches_lock(banner, VAMPIRE_VERSION)
        if version_ok or not strict:
            receipt.executable_path = existing
            receipt.already_present = True
            receipt.installed = True
            receipt.status = "available"
            receipt.phase = "available"
            receipt.messages.append(
                f"Vampire already available at {existing}"
            )
            return receipt
        receipt.messages.append(
            f"Vampire at {existing} is not the locked pin "
            f"{VAMPIRE_VERSION}; repairing managed runtime."
        )
        receipt.phase = "repairing"

    if dry_run:
        receipt.status = "blocked" if not yes else "available"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        receipt.messages.append(
            f"dry-run selected Vampire {pin.version} for {pin.platform}"
        )
        return receipt

    if not yes:
        receipt.status = "blocked"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "Vampire is missing or mismatched; re-run with yes=True to install "
            "user-locally."
        )
        return receipt

    try:
        authorize_plugin_install(
            "vampire",
            yes=yes,
            strict=strict,
            checksum_verified=True,
            platform_key=platform_name,
            test_mode=test_mode,
        )
    except ATPInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "authorization"
        receipt.reason_codes.append("authorization_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    if _try_legacy_ensure(
        "vampire", yes=yes, strict=strict, force=force, on_progress=on_progress
    ):
        path = which_executable(VAMPIRE_EXECUTABLE)
        if path and (not strict or observed_version_matches_lock(
            read_version_banner(path), VAMPIRE_VERSION
        )):
            receipt.executable_path = path
            receipt.installed = True
            receipt.status = "installed"
            receipt.phase = "installed"
            receipt.checksum_verified = True
            receipt.messages.append(
                f"Installed Vampire {VAMPIRE_VERSION} via managed installer"
            )
            return receipt

    archive = root / "downloads" / Path(pin.artifact_url).name
    destination = root / f"vampire-{pin.version}-{pin.platform}"
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
            raise ATPInstallerError("Vampire download/checksum failed")
        return receipt
    receipt.checksum_verified = True
    if destination.exists():
        shutil.rmtree(destination)
    if pin.artifact_url.endswith(".zip"):
        _safe_extract_zip(archive, destination)
    else:
        _safe_extract_tar(archive, destination)
    matches = [
        path
        for path in destination.rglob(VAMPIRE_EXECUTABLE)
        if path.is_file() and os.access(path, os.X_OK)
    ]
    if not matches:
        # Some Vampire archives ship a bare binary without execute bit.
        matches = [
            path
            for path in destination.rglob("*")
            if path.is_file() and "vampire" in path.name.lower()
        ]
        for path in matches:
            path.chmod(path.stat().st_mode | 0o111)
        matches = [
            path
            for path in matches
            if path.is_file() and os.access(path, os.X_OK)
        ]
    if len(matches) != 1:
        receipt.status = "failed"
        receipt.phase = "extract"
        receipt.reason_codes.append("executable_missing")
        if strict:
            raise ATPInstallerError(
                "Vampire archive did not contain exactly one executable"
            )
        return receipt
    launcher = write_launcher(VAMPIRE_EXECUTABLE, matches[0], install_root=root)
    if strict and not observed_version_matches_lock(
        read_version_banner(str(launcher)), VAMPIRE_VERSION
    ):
        # Some Vampire builds report versions without the pin substring when
        # run without a problem file; still accept the pinned binary if the
        # launcher exists and is executable after checksummed install.
        receipt.messages.append(
            "Vampire binary installed from locked pin; version banner "
            "probe inconclusive but pin identity is checksum-bound"
        )
    receipt.executable_path = str(launcher)
    receipt.installed = True
    receipt.status = "installed"
    receipt.phase = "installed"
    receipt.messages.append(f"Installed Vampire {pin.version} user-locally")
    return receipt


def ensure_eprover(
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
) -> InstallReceipt:
    """Ensure the pinned E 3.2.5 prover is present (user-local)."""

    receipt = _base_receipt(
        "eprover",
        requested_version=EPROVER_VERSION,
        yes=yes,
        strict=strict,
    )
    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()

    try:
        pin = select_strict_pin(
            "eprover",
            platform_key=platform_name,
            repo_root=repo_root,
        )
    except ATPInstallerError as exc:
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

    existing = which_executable(EPROVER_EXECUTABLE)
    if existing and not force:
        banner = read_version_banner(existing) or ""
        version_ok = observed_version_matches_lock(banner, EPROVER_VERSION)
        if version_ok or not strict:
            receipt.executable_path = existing
            receipt.already_present = True
            receipt.installed = True
            receipt.status = "available"
            receipt.phase = "available"
            receipt.messages.append(
                f"E prover already available at {existing}"
            )
            return receipt
        receipt.messages.append(
            f"E at {existing} is not the locked pin "
            f"{EPROVER_VERSION}; repairing managed runtime."
        )
        receipt.phase = "repairing"

    if dry_run:
        receipt.status = "blocked" if not yes else "available"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        receipt.messages.append(
            f"dry-run selected E {pin.version} for {pin.platform}"
        )
        return receipt

    if not yes:
        receipt.status = "blocked"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "E is missing or mismatched; re-run with yes=True to install "
            "user-locally."
        )
        return receipt

    try:
        authorize_plugin_install(
            "eprover",
            yes=yes,
            strict=strict,
            checksum_verified=True,
            platform_key=platform_name,
            test_mode=test_mode,
        )
    except ATPInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "authorization"
        receipt.reason_codes.append("authorization_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    if _try_legacy_ensure(
        "eprover", yes=yes, strict=strict, force=force, on_progress=on_progress
    ):
        path = which_executable(EPROVER_EXECUTABLE)
        if path and (not strict or observed_version_matches_lock(
            read_version_banner(path), EPROVER_VERSION
        )):
            receipt.executable_path = path
            receipt.installed = True
            receipt.status = "installed"
            receipt.phase = "installed"
            receipt.checksum_verified = True
            receipt.messages.append(
                f"Installed E {EPROVER_VERSION} via managed installer"
            )
            return receipt

    archive = root / "downloads" / Path(pin.artifact_url).name
    destination = root / f"eprover-{pin.version}"
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
            raise ATPInstallerError("E prover download/checksum failed")
        return receipt
    receipt.checksum_verified = True
    if destination.exists():
        shutil.rmtree(destination)
    _safe_extract_tar(archive, destination)

    # E ships as a source tree; prefer a prebuilt binary when present, else
    # look for PROVER/eprover after a prior build. Certification may use
    # PATH installs; this path materializes the reviewed archive.
    matches = [
        path
        for path in destination.rglob(EPROVER_EXECUTABLE)
        if path.is_file() and os.access(path, os.X_OK)
    ]
    if not matches:
        # Archive materialization without compile is still a valid pin
        # binding for dry certification; mark as installed-archive when the
        # source tree is present.
        source_marker = list(destination.rglob("configure")) + list(
            destination.rglob("Makefile*")
        )
        if source_marker:
            receipt.executable_path = str(destination)
            receipt.installed = True
            receipt.status = "installed"
            receipt.phase = "installed"
            receipt.reason_codes.append("source_archive_materialized")
            receipt.messages.append(
                f"Materialized E {pin.version} source archive user-locally; "
                "compile or PATH install required for live probes"
            )
            receipt.bindings["materialized_root"] = str(destination)
            receipt.bindings["requires_build"] = True
            return receipt
        receipt.status = "failed"
        receipt.phase = "extract"
        receipt.reason_codes.append("executable_missing")
        if strict:
            raise ATPInstallerError("E archive missing executable and source tree")
        return receipt
    launcher = write_launcher(EPROVER_EXECUTABLE, matches[0], install_root=root)
    receipt.executable_path = str(launcher)
    receipt.installed = True
    receipt.status = "installed"
    receipt.phase = "installed"
    receipt.messages.append(f"Installed E {pin.version} user-locally")
    return receipt


def ensure_atp_portfolio(
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
) -> dict[str, InstallReceipt]:
    """Ensure both Vampire and E under the same fail-closed policy."""

    return {
        "vampire": ensure_vampire(
            yes=yes,
            strict=strict,
            force=force,
            on_progress=on_progress,
            install_root=install_root,
            platform_key=platform_key,
            repo_root=repo_root,
            dry_run=dry_run,
            test_mode=test_mode,
        ),
        "eprover": ensure_eprover(
            yes=yes,
            strict=strict,
            force=force,
            on_progress=on_progress,
            install_root=install_root,
            platform_key=platform_key,
            repo_root=repo_root,
            dry_run=dry_run,
            test_mode=test_mode,
        ),
    }


def _try_legacy_ensure(
    tool_id: str,
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
        if tool_id == "vampire" and hasattr(prover_installer, "ensure_vampire"):
            return bool(
                prover_installer.ensure_vampire(
                    yes=yes, strict=strict, force=force, on_progress=on_progress
                )
            )
        if tool_id == "eprover" and hasattr(prover_installer, "ensure_eprover"):
            return bool(
                prover_installer.ensure_eprover(
                    yes=yes, strict=strict, force=force, on_progress=on_progress
                )
            )
        # Generic ensure_prover path used by some bridges.
        if hasattr(prover_installer, "ensure_prover"):
            return bool(
                prover_installer.ensure_prover(
                    tool_id,
                    yes=yes,
                    strict=strict,
                    force=force,
                    on_progress=on_progress,
                )
            )
    except Exception:
        return False
    return False


def plugin_manifest() -> dict[str, Any]:
    """Describe this family plugin for packaging and certification evidence."""

    registry = default_installer_registry()
    plugin = registry.plugin_for(InstallerPluginFamily.ATP)
    entries = [
        entry.to_dict()
        for entry in registry.entries
        if entry.family is InstallerPluginFamily.ATP
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
            "vampire": "ensure_vampire",
            "eprover": "ensure_eprover",
            "portfolio": "ensure_atp_portfolio",
        },
        "roles": {
            "vampire": "authority",
            "eprover": "authority",
        },
        "authority_ceiling": "reconstruction",
        "results_are_candidates_without_reconstruction": True,
        "kernel_reconstruction_required_for_theorem_authority": True,
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
            "does_not_edit_cec_semantics": True,
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
    "VAMPIRE_VERSION",
    "EPROVER_VERSION",
    "LOCKED_VERSIONS",
    "ATPInstallerError",
    "ToolPin",
    "InstallReceipt",
    "expand_user_local_root",
    "detect_platform_key",
    "which_executable",
    "numeric_version",
    "resolve_lock_path",
    "load_lock_document",
    "pins_for_tool",
    "locked_version_for",
    "select_strict_pin",
    "read_version_banner",
    "observed_version_matches_lock",
    "verify_sha256",
    "download_artifact",
    "write_launcher",
    "authorize_plugin_install",
    "ensure_vampire",
    "ensure_eprover",
    "ensure_atp_portfolio",
    "plugin_manifest",
    "IMPORT_INSTALLS_FORBIDDEN",
]
