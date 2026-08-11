"""Tamarin + Maude + Stack family installer plugin (FVT-G130 / FVT-043).

``FormalVerificationInstallerPlugin@1`` for the protocol lane:

* ``ensure_tamarin`` — pinned Tamarin prover (authority tool)
* ``ensure_maude`` — compatible Maude rewrite engine (**support only**)
* ``ensure_stack`` — Haskell Stack bootstrap for source builds (support)

Fail-closed installation contract
---------------------------------
* never installs on import or capability discovery;
* requires an explicit ``ensure_*`` call with ``yes=True``;
* user-local installs only (no system package manager mutation);
* managed artifacts require checksum verification before extract;
* under ``strict=True``, only the locked pin versions are accepted:
  Tamarin ``1.12.0`` and Maude ``3.5.1`` (and Stack ``3.11.1``);
* Maude presence alone never grants protocol authority;
* this plugin never edits the shared multi-prover certificate or ProVerif lane.

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
PLUGIN_FAMILY: Final = InstallerPluginFamily.TAMARIN.value
PLUGIN_MODULE: Final = "ipfs_datasets_py.logic.backends.installers.tamarin"
GOAL_ID: Final = "FVT-G130"
TASK_ID: Final = "FVT-043"
PROGRAM: Final = "formal-verification-tactician/tamarin-toolchain"

# Locked managed-pin versions (must match deployment lock).
TAMARIN_VERSION: Final = "1.12.0"
MAUDE_VERSION: Final = "3.5.1"
STACK_VERSION: Final = "3.11.1"

TAMARIN_EXECUTABLE: Final = "tamarin-prover"
MAUDE_EXECUTABLE: Final = "maude"
STACK_EXECUTABLE: Final = "stack"

# Reviewed fallback pins when the lock file is unavailable (tests / offline).
_FALLBACK_PINS: Final[dict[str, tuple[dict[str, Any], ...]]] = {
    "tamarin": (
        {
            "tool_id": "tamarin",
            "version": TAMARIN_VERSION,
            "platform": "linux-x86_64",
            "artifact_url": (
                "https://github.com/tamarin-prover/tamarin-prover/releases/"
                f"download/{TAMARIN_VERSION}/"
                f"tamarin-prover-{TAMARIN_VERSION}-linux64-ubuntu.tar.gz"
            ),
            "sha256": (
                "201be06f469e47cff554df6ca93db8366fc2c69d70c61fcbd1370a1074b469c6"
            ),
            "identity_kind": "release_archive",
        },
        {
            "tool_id": "tamarin",
            "version": TAMARIN_VERSION,
            "platform": "source",
            "artifact_url": (
                "https://github.com/tamarin-prover/tamarin-prover/archive/"
                f"refs/tags/{TAMARIN_VERSION}.tar.gz"
            ),
            "sha256": (
                "35f0262e770db3632fcb297deb6ecc2d7c724c693fecfe97892e8224fa161956"
            ),
            "identity_kind": "source_archive",
        },
    ),
    "maude": (
        {
            "tool_id": "maude",
            "version": MAUDE_VERSION,
            "platform": "linux-x86_64",
            "artifact_url": (
                "https://github.com/maude-lang/Maude/releases/download/"
                f"Maude{MAUDE_VERSION}/Maude-{MAUDE_VERSION}-linux-x86_64.zip"
            ),
            "sha256": (
                "72ed1ca87e3b3d0dfc6ee1436baf154bf04c45ff97d521bec040c5e8dfc8f92c"
            ),
            "identity_kind": "release_archive",
        },
        {
            "tool_id": "maude",
            "version": MAUDE_VERSION,
            "platform": "linux-aarch64",
            "artifact_url": (
                "https://deb.debian.org/debian/pool/main/m/maude/"
                "maude_3.5.1-1+b1_arm64.deb"
            ),
            "sha256": (
                "4ed71228ef698a6019ee011e54fbb04fe74145fce465e65838a6c92f743ef730"
            ),
            "identity_kind": "deb_package",
        },
    ),
    "stack": (
        {
            "tool_id": "stack",
            "version": STACK_VERSION,
            "platform": "linux-x86_64",
            "artifact_url": (
                "https://github.com/commercialhaskell/stack/releases/download/"
                f"v{STACK_VERSION}/stack-{STACK_VERSION}-linux-x86_64.tar.gz"
            ),
            "sha256": (
                "1fda71e657cd8d355625cc66b61b352699279dfee2664c014a392163bd19a952"
            ),
            "identity_kind": "release_archive",
        },
        {
            "tool_id": "stack",
            "version": STACK_VERSION,
            "platform": "linux-aarch64",
            "artifact_url": (
                "https://github.com/commercialhaskell/stack/releases/download/"
                f"v{STACK_VERSION}/stack-{STACK_VERSION}-linux-aarch64.tar.gz"
            ),
            "sha256": (
                "1617ae9976a5cd38ad4daec583b026b589eb45d5482afb045cd4ca8c8d0de6d0"
            ),
            "identity_kind": "release_archive",
        },
    ),
}

LOCKED_VERSIONS: Final[Mapping[str, str]] = {
    "tamarin": TAMARIN_VERSION,
    "maude": MAUDE_VERSION,
    "stack": STACK_VERSION,
}

# Exact Maude releases accepted by Tamarin 1.12 runtime validation.
TAMARIN_MAUDE_COMPATIBLE_VERSIONS: Final[frozenset[tuple[int, ...]]] = frozenset(
    {
        (2, 7, 1),
        (3, 0),
        (3, 1),
        (3, 2, 1),
        (3, 2, 2),
        (3, 3),
        (3, 3, 1),
        (3, 4),
        (3, 5),
        (3, 5, 1),
    }
)

ProgressCallback = Callable[[str, str], None]

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)+)")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class TamarinInstallerError(RuntimeError):
    """Raised when a strict Tamarin/Maude install policy is violated."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolPin:
    """One platform-specific managed pin for a protocol-lane tool."""

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
                raise TamarinInstallerError(f"{name} must be a non-empty trimmed string")
        digest = self.sha256.lower()
        if not _HEX64.match(digest):
            raise TamarinInstallerError(
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
    authority_tool: bool = False
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
        raise TamarinInstallerError("deployment lock must be a JSON object")
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
            raise TamarinInstallerError("deployment lock tools must be a list")
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
        raise TamarinInstallerError(f"no managed pins registered for {tool_id!r}")
    return tuple(pins)


def locked_version_for(tool_id: str, *, lock: Mapping[str, Any] | None = None) -> str:
    """Return the exact managed pin version required under strict install."""

    if lock is not None:
        versions = lock.get("managed_pin_versions") or {}
        if isinstance(versions, Mapping) and tool_id in versions:
            return str(versions[tool_id])
    if tool_id in LOCKED_VERSIONS:
        return LOCKED_VERSIONS[tool_id]
    raise TamarinInstallerError(f"no locked version for tool_id={tool_id!r}")


def select_strict_pin(
    tool_id: str,
    *,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    lock: Mapping[str, Any] | None = None,
    allow_source_fallback: bool = True,
) -> ToolPin:
    """Select the exact locked pin for ``tool_id`` on the host platform.

    Under the FVT-G130 contract this is the only pin that strict installation
    may materialize.  Version mismatches fail closed rather than upgrading.
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
    if allow_source_fallback:
        source = [
            pin
            for pin in candidates
            if pin.version == expected and pin.platform == "source"
        ]
        if source:
            return source[0]
    available = sorted({f"{pin.platform}@{pin.version}" for pin in candidates})
    raise TamarinInstallerError(
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


def maude_version_is_compatible(version_text: str) -> bool:
    """Return True when Maude's version is on Tamarin's exact allowlist.

    Tamarin 1.12 validates specific Maude releases rather than intervals.
    In particular Maude 3.2 is rejected while 3.2.1 is accepted, so only
    exact allowlist membership is safe.
    """

    version = numeric_version(version_text)
    if not version:
        return False
    return version in TAMARIN_MAUDE_COMPATIBLE_VERSIONS


def maude_is_tamarin_compatible(executable: str) -> bool:
    banner = read_version_banner(executable)
    if not banner:
        return False
    return maude_version_is_compatible(banner)


def tamarin_accepts_maude(
    tamarin: str | None,
    maude: str | None,
    *,
    expected_tamarin_version: str = TAMARIN_VERSION,
    timeout: float = 30.0,
) -> bool:
    """Ask Tamarin itself whether the paired Maude runtime is accepted."""

    if not tamarin or not maude:
        return False
    try:
        completed = subprocess.run(
            [tamarin, f"--with-maude={maude}", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = "\n".join(
        value for value in (completed.stdout, completed.stderr) if value
    )
    maude_match = re.search(
        r"\bMaude(?:\s+version)?\s+(\d+(?:\.\d+)+)",
        output,
        re.IGNORECASE,
    )
    maude_version = numeric_version(maude_match.group(1) if maude_match else "")
    return bool(
        completed.returncode == 0
        and expected_tamarin_version in output
        and maude_version
        and maude_version_is_compatible(".".join(str(p) for p in maude_version))
        and "checking installation: OK" in output
    )


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
    request = Request(url, headers={"User-Agent": "ipfs-datasets-py-tamarin-installer/1"})
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
        # Python 3.12+ supports filter=; fall back for older runtimes.
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
    """Fail-closed gate shared by ensure_tamarin / ensure_maude / ensure_stack."""

    if tool_id not in {"tamarin", "maude", "stack"}:
        raise TamarinInstallerError(
            f"tamarin plugin does not own tool_id={tool_id!r}"
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
        raise TamarinInstallerError(str(exc)) from exc
    entry = get_installer_entry(tool_id)
    if entry.family is not InstallerPluginFamily.TAMARIN:
        raise TamarinInstallerError(
            f"tool {tool_id!r} is not bound to the tamarin installer plugin"
        )
    if strict:
        # Selecting the pin proves the lock has an exact version binding.
        select_strict_pin(tool_id, platform_key=platform_key)


# ---------------------------------------------------------------------------
# ensure_* entry points
# ---------------------------------------------------------------------------


def ensure_maude(
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
    """Ensure the pinned Maude rewrite engine is present (support only)."""

    receipt = InstallReceipt(
        tool_id="maude",
        requested_version=MAUDE_VERSION,
        strict=strict,
        yes=yes,
        support_only=True,
        authority_tool=False,
    )
    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()

    try:
        pin = select_strict_pin(
            "maude",
            platform_key=platform_name,
            repo_root=repo_root,
        )
    except TamarinInstallerError as exc:
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
        "tool_id": "maude",
        "locked_version": MAUDE_VERSION,
        "selected_version": pin.version,
        "platform": pin.platform,
        "role": "support",
        "authority_ceiling": "none",
        "can_promote_protocol_lane": False,
    }

    existing = which_executable(MAUDE_EXECUTABLE)
    if existing and not force:
        banner = read_version_banner(existing) or ""
        compatible = maude_is_tamarin_compatible(existing)
        version_ok = observed_version_matches_lock(banner, MAUDE_VERSION)
        if compatible and (version_ok or not strict):
            receipt.executable_path = existing
            receipt.already_present = True
            receipt.installed = True
            receipt.status = "available"
            receipt.phase = "available"
            receipt.messages.append(
                f"Tamarin-compatible Maude already available at {existing}"
            )
            return receipt
        receipt.messages.append(
            f"Maude at {existing} is not the locked Tamarin-compatible pin "
            f"{MAUDE_VERSION}; repairing managed runtime."
        )
        receipt.phase = "repairing"

    if dry_run:
        receipt.status = "blocked" if not yes else "available"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        receipt.messages.append(
            f"dry-run selected Maude {pin.version} for {pin.platform}"
        )
        return receipt

    if not yes:
        receipt.status = "blocked"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "Maude is missing or mismatched; re-run with yes=True to install "
            "user-locally."
        )
        return receipt

    try:
        authorize_plugin_install(
            "maude",
            yes=yes,
            strict=strict,
            checksum_verified=True,
            platform_key=platform_name,
            test_mode=test_mode,
        )
    except TamarinInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "authorization"
        receipt.reason_codes.append("authorization_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    # Prefer the legacy prover_installer path when available so operators keep
    # a single managed root; fall back to a direct pin install.
    if _try_legacy_ensure("maude", yes=yes, strict=strict, force=force, on_progress=on_progress):
        path = which_executable(MAUDE_EXECUTABLE)
        if path and (not strict or maude_is_tamarin_compatible(path)):
            receipt.executable_path = path
            receipt.installed = True
            receipt.status = "installed"
            receipt.phase = "installed"
            receipt.checksum_verified = True
            receipt.messages.append(f"Installed Maude {MAUDE_VERSION} via managed installer")
            return receipt

    if pin.platform == "linux-x86_64" and pin.artifact_url.endswith(".zip"):
        archive = root / "downloads" / f"Maude-{pin.version}-linux-x86_64.zip"
        destination = root / f"maude-{pin.version}"
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
                raise TamarinInstallerError("Maude download/checksum failed")
            return receipt
        receipt.checksum_verified = True
        _announce(f"Extracting Maude {pin.version} into {destination}", on_progress)
        if destination.exists():
            shutil.rmtree(destination)
        _safe_extract_zip(archive, destination)
        executable = destination / "maude"
        if not executable.is_file():
            # Some archives nest the binary one level down.
            matches = [
                path
                for path in destination.rglob("maude")
                if path.is_file() and os.access(path, os.X_OK)
            ]
            if len(matches) != 1:
                receipt.status = "failed"
                receipt.phase = "extract"
                receipt.reason_codes.append("executable_missing")
                if strict:
                    raise TamarinInstallerError("Maude archive missing executable")
                return receipt
            executable = matches[0]
        launcher = write_launcher(
            "maude",
            executable,
            install_root=root,
            environment={"MAUDE_LIB": str(executable.parent)},
        )
        if strict and not maude_is_tamarin_compatible(str(launcher)):
            receipt.status = "failed"
            receipt.phase = "validation"
            receipt.reason_codes.append("maude_not_tamarin_compatible")
            if strict:
                raise TamarinInstallerError(
                    f"installed Maude is not accepted by Tamarin {TAMARIN_VERSION}"
                )
            return receipt
        receipt.executable_path = str(launcher)
        receipt.installed = True
        receipt.status = "installed"
        receipt.phase = "installed"
        receipt.messages.append(f"Installed Maude {pin.version} user-locally")
        return receipt

    receipt.status = "blocked"
    receipt.phase = "blocked"
    receipt.reason_codes.append("no_native_artifact_for_platform")
    receipt.messages.append(
        f"No direct Maude artifact installer for platform {pin.platform}; "
        "set IPFS_DATASETS_PY_MAUDE_INSTALL_COMMAND or use a reviewed path."
    )
    return receipt


def ensure_stack(
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
    """Ensure Haskell Stack is present for Tamarin source builds (support)."""

    receipt = InstallReceipt(
        tool_id="stack",
        requested_version=STACK_VERSION,
        strict=strict,
        yes=yes,
        support_only=True,
        authority_tool=False,
    )
    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()

    try:
        pin = select_strict_pin(
            "stack",
            platform_key=platform_name,
            repo_root=repo_root,
            allow_source_fallback=False,
        )
    except TamarinInstallerError as exc:
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

    existing = which_executable(STACK_EXECUTABLE)
    if existing and not force:
        receipt.executable_path = existing
        receipt.already_present = True
        receipt.installed = True
        receipt.status = "available"
        receipt.phase = "available"
        return receipt

    if dry_run:
        receipt.status = "blocked" if not yes else "available"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        return receipt

    if not yes:
        receipt.status = "blocked"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        return receipt

    try:
        authorize_plugin_install(
            "stack",
            yes=yes,
            strict=strict,
            checksum_verified=True,
            platform_key=platform_name,
            test_mode=test_mode,
        )
    except TamarinInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "authorization"
        receipt.reason_codes.append("authorization_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    archive = root / "downloads" / Path(pin.artifact_url).name
    destination = root / f"stack-{pin.version}-{pin.platform}"
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
            raise TamarinInstallerError("Stack download/checksum failed")
        return receipt
    receipt.checksum_verified = True
    if destination.exists():
        shutil.rmtree(destination)
    _safe_extract_tar(archive, destination)
    matches = [
        path
        for path in destination.rglob("stack")
        if path.is_file() and os.access(path, os.X_OK)
    ]
    if len(matches) != 1:
        receipt.status = "failed"
        receipt.phase = "extract"
        receipt.reason_codes.append("executable_missing")
        if strict:
            raise TamarinInstallerError("Stack archive missing executable")
        return receipt
    launcher = write_launcher("stack", matches[0], install_root=root)
    receipt.executable_path = str(launcher)
    receipt.installed = True
    receipt.status = "installed"
    receipt.phase = "installed"
    return receipt


def ensure_tamarin(
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
    ensure_maude_first: bool = True,
) -> InstallReceipt:
    """Ensure Tamarin 1.12.0 and its compatible Maude pair are installed."""

    receipt = InstallReceipt(
        tool_id="tamarin",
        requested_version=TAMARIN_VERSION,
        strict=strict,
        yes=yes,
        support_only=False,
        authority_tool=True,
    )
    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()

    try:
        pin = select_strict_pin(
            "tamarin",
            platform_key=platform_name,
            repo_root=repo_root,
        )
    except TamarinInstallerError as exc:
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
        "tool_id": "tamarin",
        "locked_version": TAMARIN_VERSION,
        "selected_version": pin.version,
        "platform": pin.platform,
        "maude_locked_version": MAUDE_VERSION,
        "role": "authority",
        "authority_ceiling": "protocol",
        "maude_is_support_only": True,
    }

    if ensure_maude_first:
        maude_receipt = ensure_maude(
            yes=yes,
            strict=strict,
            force=force,
            on_progress=on_progress,
            install_root=root,
            platform_key=platform_name,
            repo_root=repo_root,
            dry_run=dry_run,
            test_mode=test_mode,
        )
        receipt.bindings["maude_install"] = maude_receipt.to_dict()
        if maude_receipt.status not in {"available", "installed"} and not dry_run:
            receipt.status = maude_receipt.status
            receipt.phase = "maude_dependency"
            receipt.reason_codes.append("maude_not_ready")
            receipt.messages.extend(maude_receipt.messages)
            return receipt

    existing = which_executable(TAMARIN_EXECUTABLE)
    maude = which_executable(MAUDE_EXECUTABLE)
    if existing and not force and not dry_run:
        banner = read_version_banner(existing) or ""
        version_ok = observed_version_matches_lock(banner, TAMARIN_VERSION)
        pair_ok = tamarin_accepts_maude(existing, maude)
        if version_ok and pair_ok:
            receipt.executable_path = existing
            receipt.already_present = True
            receipt.installed = True
            receipt.status = "available"
            receipt.phase = "available"
            receipt.bindings["maude_executable"] = maude
            receipt.messages.append(
                f"Tamarin {TAMARIN_VERSION} accepts Maude {MAUDE_VERSION} at {maude}"
            )
            return receipt
        if existing and (not version_ok or not pair_ok):
            receipt.messages.append(
                "Tamarin/Maude pair present but failed strict version or runtime "
                "validation; re-run with force=True and yes=True to repair."
            )
            if not yes:
                receipt.status = "failed"
                receipt.phase = "validation"
                receipt.reason_codes.append("runtime_validation_failed")
                return receipt

    if dry_run:
        receipt.status = "blocked" if not yes else "available"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        receipt.messages.append(
            f"dry-run selected Tamarin {pin.version} for {pin.platform} "
            f"with Maude {MAUDE_VERSION}"
        )
        return receipt

    if not yes:
        receipt.status = "blocked"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "Tamarin is missing; re-run with yes=True to install user-locally."
        )
        return receipt

    try:
        authorize_plugin_install(
            "tamarin",
            yes=yes,
            strict=strict,
            checksum_verified=True,
            platform_key=platform_name,
            test_mode=test_mode,
        )
    except TamarinInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "authorization"
        receipt.reason_codes.append("authorization_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    if _try_legacy_ensure(
        "tamarin", yes=yes, strict=strict, force=force, on_progress=on_progress
    ):
        path = which_executable(TAMARIN_EXECUTABLE)
        maude_path = which_executable(MAUDE_EXECUTABLE)
        if path and (not strict or tamarin_accepts_maude(path, maude_path)):
            receipt.executable_path = path
            receipt.installed = True
            receipt.status = "installed"
            receipt.phase = "installed"
            receipt.checksum_verified = True
            receipt.bindings["maude_executable"] = maude_path
            receipt.messages.append(
                f"Installed Tamarin {TAMARIN_VERSION} with Maude {MAUDE_VERSION}"
            )
            return receipt

    if pin.platform == "linux-x86_64" and pin.artifact_url.endswith(".tar.gz"):
        archive = (
            root
            / "downloads"
            / f"tamarin-prover-{pin.version}-linux64-ubuntu.tar.gz"
        )
        destination = root / f"tamarin-prover-{pin.version}"
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
                raise TamarinInstallerError("Tamarin download/checksum failed")
            return receipt
        receipt.checksum_verified = True
        _announce(f"Extracting Tamarin {pin.version} into {destination}", on_progress)
        if destination.exists():
            shutil.rmtree(destination)
        _safe_extract_tar(archive, destination)
        matches = [
            path
            for path in destination.rglob(TAMARIN_EXECUTABLE)
            if path.is_file() and os.access(path, os.X_OK)
        ]
        if len(matches) != 1:
            receipt.status = "failed"
            receipt.phase = "extract"
            receipt.reason_codes.append("executable_missing")
            if strict:
                raise TamarinInstallerError(
                    "Tamarin archive did not contain exactly one executable"
                )
            return receipt
        launcher = write_launcher(TAMARIN_EXECUTABLE, matches[0], install_root=root)
        tamarin_path = str(launcher)
        maude_path = which_executable(MAUDE_EXECUTABLE)
        if strict and not tamarin_accepts_maude(tamarin_path, maude_path):
            receipt.status = "failed"
            receipt.phase = "validation"
            receipt.reason_codes.append("runtime_validation_failed")
            receipt.executable_path = tamarin_path
            if strict:
                raise TamarinInstallerError(
                    "Tamarin/Maude installation did not pass runtime validation"
                )
            return receipt
        receipt.executable_path = tamarin_path
        receipt.installed = True
        receipt.status = "installed"
        receipt.phase = "installed"
        receipt.bindings["maude_executable"] = maude_path
        receipt.messages.append(
            f"Installed Tamarin {pin.version} with Maude {MAUDE_VERSION}"
        )
        return receipt

    receipt.status = "blocked"
    receipt.phase = "blocked"
    receipt.reason_codes.append("no_native_artifact_for_platform")
    receipt.messages.append(
        f"No direct Tamarin binary for platform {pin.platform}; "
        "source build via ensure_stack is required, or set "
        "IPFS_DATASETS_PY_TAMARIN_INSTALL_COMMAND."
    )
    return receipt


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
        if tool_id == "maude":
            return bool(
                prover_installer.ensure_maude(
                    yes=yes, strict=strict, force=force, on_progress=on_progress
                )
            )
        if tool_id == "tamarin":
            return bool(
                prover_installer.ensure_tamarin(
                    yes=yes, strict=strict, force=force, on_progress=on_progress
                )
            )
    except Exception:
        return False
    return False


def plugin_manifest() -> dict[str, Any]:
    """Describe this family plugin for packaging and certification evidence."""

    registry = default_installer_registry()
    plugin = registry.plugin_for(InstallerPluginFamily.TAMARIN)
    entries = [
        entry.to_dict()
        for entry in registry.entries
        if entry.family is InstallerPluginFamily.TAMARIN
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
            "tamarin": "ensure_tamarin",
            "maude": "ensure_maude",
            "stack": "ensure_stack",
        },
        "roles": {
            "tamarin": "authority",
            "maude": "support",
            "stack": "support",
        },
        "maude_is_support_only": True,
        "maude_cannot_promote_protocol_lane": True,
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
            "does_not_edit_proverif_lane": True,
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
    "TAMARIN_VERSION",
    "MAUDE_VERSION",
    "STACK_VERSION",
    "LOCKED_VERSIONS",
    "TAMARIN_MAUDE_COMPATIBLE_VERSIONS",
    "TamarinInstallerError",
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
    "maude_version_is_compatible",
    "maude_is_tamarin_compatible",
    "tamarin_accepts_maude",
    "observed_version_matches_lock",
    "verify_sha256",
    "download_artifact",
    "write_launcher",
    "authorize_plugin_install",
    "ensure_maude",
    "ensure_stack",
    "ensure_tamarin",
    "plugin_manifest",
    "IMPORT_INSTALLS_FORBIDDEN",
]
