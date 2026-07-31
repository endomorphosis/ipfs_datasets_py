"""ProVerif + isolated OPAM installer plugin (FVT-G131 / FVT-044).

``FormalVerificationInstallerPlugin@1`` for the protocol lane (ProVerif):

* ``ensure_proverif`` — pinned ProVerif 2.05 authority tool
* ``ensure_opam`` — OPAM 2.5.2 support binary under a repository-local
  isolated root (**support only**, never global switch mutation)

Fail-closed installation contract
---------------------------------
* never installs on import or capability discovery;
* requires an explicit ``ensure_*`` call with ``yes=True``;
* installs only into a user-local or repository-local isolated root;
* never mutates a global OPAM switch (``~/.opam``, system roots);
* managed artifacts require checksum verification before extract/use;
* under ``strict=True``, only the locked pin versions are accepted:
  ProVerif ``2.05`` and OPAM ``2.5.2``;
* OPAM presence alone never grants protocol authority;
* this plugin never edits the shared multi-prover certificate or Tamarin lane.

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
PLUGIN_FAMILY: Final = InstallerPluginFamily.PROVERIF.value
PLUGIN_MODULE: Final = "ipfs_datasets_py.logic.backends.installers.proverif"
GOAL_ID: Final = "FVT-G131"
TASK_ID: Final = "FVT-044"
PROGRAM: Final = "formal-verification-tactician/proverif-toolchain"

# Locked managed-pin versions (must match deployment lock).
PROVERIF_VERSION: Final = "2.05"
OPAM_VERSION: Final = "2.5.2"

PROVERIF_EXECUTABLE: Final = "proverif"
OPAM_EXECUTABLE: Final = "opam"

# Relative path under install root for the isolated OPAM root.
ISOLATED_OPAM_ROOT_SEGMENT: Final = ("opam-roots", "proverif")
# Repository-local cache path used when a repo root is provided.
REPO_ISOLATED_OPAM_RELATIVE: Final = Path(".cache/formal_verification/opam-roots/proverif")

# Reviewed fallback pins when the lock file is unavailable (tests / offline).
_FALLBACK_PINS: Final[dict[str, tuple[dict[str, Any], ...]]] = {
    "proverif": (
        {
            "tool_id": "proverif",
            "version": PROVERIF_VERSION,
            "platform": "any",
            "artifact_url": "https://proverif.inria.fr/proverif2.05.tar.gz",
            "sha256": (
                "4871f53c32ab4a04669a060c4886ba5d9080496963fb980a9a62d2c429ceabc4"
            ),
            "identity_kind": "release_archive",
        },
    ),
    "opam": (
        {
            "tool_id": "opam",
            "version": OPAM_VERSION,
            "platform": "linux-x86_64",
            "artifact_url": (
                "https://github.com/ocaml/opam/releases/download/"
                f"{OPAM_VERSION}/opam-{OPAM_VERSION}-x86_64-linux"
            ),
            "sha256": (
                "edfca2630c373b44b7ee1c2f81cd8dcf67468d0db57d6c02158de553ac63dbd4"
            ),
            "identity_kind": "release_archive",
        },
        {
            "tool_id": "opam",
            "version": OPAM_VERSION,
            "platform": "linux-aarch64",
            "artifact_url": (
                "https://github.com/ocaml/opam/releases/download/"
                f"{OPAM_VERSION}/opam-{OPAM_VERSION}-arm64-linux"
            ),
            "sha256": (
                "c4106ece84bcb60c68342573d2d6b4f0d6770ee088015c2216adc83d8854dcf9"
            ),
            "identity_kind": "release_archive",
        },
    ),
}

LOCKED_VERSIONS: Final[Mapping[str, str]] = {
    "proverif": PROVERIF_VERSION,
    "opam": OPAM_VERSION,
}

# Paths that must never be used as the ProVerif OPAM root.
_FORBIDDEN_GLOBAL_OPAM_MARKERS: Final[tuple[str, ...]] = (
    ".opam",
)

ProgressCallback = Callable[[str, str], None]

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)+)")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ProVerifInstallerError(RuntimeError):
    """Raised when a strict ProVerif/OPAM install policy is violated."""


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
                raise ProVerifInstallerError(f"{name} must be a non-empty trimmed string")
        digest = self.sha256.lower()
        if not _HEX64.match(digest):
            raise ProVerifInstallerError(
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
    isolated_opam_root: str | None = None
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
# Isolated OPAM root contract
# ---------------------------------------------------------------------------


def default_isolated_opam_root(
    *,
    repo_root: Path | str | None = None,
    install_root: str | Path | None = None,
) -> Path:
    """Return the repository-local / managed isolated OPAM root for ProVerif.

    Never returns ``~/.opam`` or another global switch path.
    """

    if install_root is not None:
        root = expand_user_local_root(install_root)
        return (root.joinpath(*ISOLATED_OPAM_ROOT_SEGMENT)).resolve()
    if repo_root is not None:
        return (Path(repo_root).resolve() / REPO_ISOLATED_OPAM_RELATIVE).resolve()
    return (expand_user_local_root().joinpath(*ISOLATED_OPAM_ROOT_SEGMENT)).resolve()


def is_forbidden_global_opam_root(path: Path | str) -> bool:
    """Return True when ``path`` is (or is inside) a global OPAM switch root."""

    try:
        resolved = Path(os.path.expanduser(str(path))).resolve()
    except OSError:
        return True
    home_opam = (Path.home() / ".opam").resolve()
    if resolved == home_opam:
        return True
    # Exact system markers only — managed roots under home are fine when
    # they are not the default ``~/.opam`` switch.
    if resolved.name == ".opam" and resolved.parent in {
        Path.home().resolve(),
        Path("/root").resolve(),
        Path("/var/lib").resolve(),
    }:
        return True
    if str(resolved) in {"/usr/local/opam", "/opt/opam"}:
        return True
    return False


def assert_isolated_opam_root(path: Path | str) -> Path:
    """Fail closed when a caller would bind a global OPAM switch."""

    resolved = Path(os.path.expanduser(str(path))).resolve()
    if is_forbidden_global_opam_root(resolved):
        raise ProVerifInstallerError(
            f"refusing global OPAM root {resolved}; ProVerif requires an "
            "isolated repository-local or managed root"
        )
    # Disallow binding the ambient OPAMROOT when it is the global default.
    ambient = os.environ.get("OPAMROOT")
    if ambient:
        try:
            ambient_path = Path(os.path.expanduser(ambient)).resolve()
        except OSError:
            ambient_path = None
        if ambient_path is not None and is_forbidden_global_opam_root(ambient_path):
            if resolved == ambient_path:
                raise ProVerifInstallerError(
                    "refusing to use ambient global OPAMROOT for ProVerif"
                )
    return resolved


def isolated_opam_env(
    opam_root: Path | str,
    *,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build an environment that forces OPAMROOT to the isolated root."""

    root = assert_isolated_opam_root(opam_root)
    env = dict(base if base is not None else os.environ)
    env["OPAMROOT"] = str(root)
    # Prevent accidental switch mutation of a default global config.
    env.setdefault("OPAMYES", "0")
    env.setdefault("OPAMCOLOR", "never")
    return env


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
        raise ProVerifInstallerError("deployment lock must be a JSON object")
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
            raise ProVerifInstallerError("deployment lock tools must be a list")
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
        raise ProVerifInstallerError(f"no managed pins registered for {tool_id!r}")
    return tuple(pins)


def locked_version_for(tool_id: str, *, lock: Mapping[str, Any] | None = None) -> str:
    """Return the exact managed pin version required under strict install."""

    if lock is not None:
        versions = lock.get("managed_pin_versions") or {}
        if isinstance(versions, Mapping) and tool_id in versions:
            return str(versions[tool_id])
    if tool_id in LOCKED_VERSIONS:
        return LOCKED_VERSIONS[tool_id]
    raise ProVerifInstallerError(f"no locked version for tool_id={tool_id!r}")


def select_strict_pin(
    tool_id: str,
    *,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    lock: Mapping[str, Any] | None = None,
    allow_source_fallback: bool = True,
    allow_any_platform: bool | None = None,
) -> ToolPin:
    """Select the exact locked pin for ``tool_id`` on the host platform.

    Under the FVT-G131 contract this is the only pin that strict installation
    may materialize.  Version mismatches fail closed rather than upgrading.
    ProVerif ships a portable source archive under platform ``any``.
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
    use_any = allow_source_fallback if allow_any_platform is None else allow_any_platform
    if use_any:
        any_pin = [
            pin
            for pin in candidates
            if pin.version == expected and pin.platform in {"any", "source", "portable"}
        ]
        if any_pin:
            return any_pin[0]
    available = sorted({f"{pin.platform}@{pin.version}" for pin in candidates})
    raise ProVerifInstallerError(
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
    """Download ``url`` to ``destination`` and verify the checksum."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and verify_sha256(destination, sha256):
        _announce(
            f"Reusing checksummed artifact at {destination}",
            on_progress,
            phase="available",
        )
        return True
    _announce(f"Downloading {url}", on_progress, phase="downloading")
    request = Request(
        url, headers={"User-Agent": "ipfs-datasets-py-proverif-installer/1"}
    )
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
    """Fail-closed gate shared by ensure_proverif / ensure_opam."""

    if tool_id not in {"proverif", "opam"}:
        raise ProVerifInstallerError(
            f"proverif plugin does not own tool_id={tool_id!r}"
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
        raise ProVerifInstallerError(str(exc)) from exc
    entry = get_installer_entry(tool_id)
    if tool_id == "proverif":
        if entry.family is not InstallerPluginFamily.PROVERIF:
            raise ProVerifInstallerError(
                f"tool {tool_id!r} is not bound to the proverif installer plugin"
            )
    elif tool_id == "opam":
        # Registry may assign OPAM to the Rocq family for shared bootstrap
        # ownership; ProVerif still enforces the isolated-root contract.
        if entry.family not in {
            InstallerPluginFamily.PROVERIF,
            InstallerPluginFamily.ROCQ,
        }:
            raise ProVerifInstallerError(
                f"tool {tool_id!r} is not an allowed OPAM support entry"
            )
    if strict:
        select_strict_pin(tool_id, platform_key=platform_key)


# ---------------------------------------------------------------------------
# ensure_* entry points
# ---------------------------------------------------------------------------


def ensure_opam(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
    install_root: str | Path | None = None,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    isolated_opam_root: str | Path | None = None,
    dry_run: bool = False,
    test_mode: bool = False,
) -> InstallReceipt:
    """Ensure the pinned OPAM binary is present (support only, isolated root)."""

    receipt = InstallReceipt(
        tool_id="opam",
        requested_version=OPAM_VERSION,
        strict=strict,
        yes=yes,
        support_only=True,
        authority_tool=False,
    )
    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()
    opam_root = assert_isolated_opam_root(
        isolated_opam_root
        if isolated_opam_root is not None
        else default_isolated_opam_root(repo_root=repo_root, install_root=root)
    )
    receipt.isolated_opam_root = str(opam_root)

    try:
        pin = select_strict_pin(
            "opam",
            platform_key=platform_name,
            repo_root=repo_root,
        )
    except ProVerifInstallerError as exc:
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
        "tool_id": "opam",
        "locked_version": OPAM_VERSION,
        "selected_version": pin.version,
        "platform": pin.platform,
        "role": "support",
        "authority_ceiling": "none",
        "can_promote_protocol_lane": False,
        "isolated_opam_root": str(opam_root),
        "global_switch_mutation_forbidden": True,
        "never_uses_global_opam_root": True,
    }

    managed_bin = root / "bin"
    path_env = os.pathsep.join(
        part for part in (str(managed_bin), os.environ.get("PATH", "")) if part
    )
    existing = which_executable(OPAM_EXECUTABLE, path_env=path_env)
    if existing and not force:
        banner = read_version_banner(existing) or ""
        version_ok = observed_version_matches_lock(banner, OPAM_VERSION)
        if version_ok or not strict:
            receipt.executable_path = existing
            receipt.already_present = True
            receipt.installed = True
            receipt.status = "available"
            receipt.phase = "available"
            receipt.messages.append(
                f"Locked OPAM already available at {existing} "
                f"(isolated root {opam_root})"
            )
            return receipt
        receipt.messages.append(
            f"OPAM at {existing} is not the locked pin {OPAM_VERSION}; "
            "repairing managed runtime."
        )
        receipt.phase = "repairing"

    if dry_run:
        receipt.status = "blocked" if not yes else "available"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        receipt.messages.append(
            f"dry-run selected OPAM {pin.version} for {pin.platform} "
            f"with isolated root {opam_root}"
        )
        return receipt

    if not yes:
        receipt.status = "blocked"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "OPAM is missing or mismatched; re-run with yes=True to install "
            "user-locally under an isolated root."
        )
        return receipt

    try:
        authorize_plugin_install(
            "opam",
            yes=yes,
            strict=strict,
            checksum_verified=True,
            platform_key=platform_name,
            test_mode=test_mode,
        )
    except ProVerifInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "authorization"
        receipt.reason_codes.append("authorization_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    # Platform-native OPAM binary install (single-file release).
    if pin.artifact_url and "opam-" in pin.artifact_url:
        archive_name = Path(pin.artifact_url).name
        archive = root / "downloads" / archive_name
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
                raise ProVerifInstallerError("OPAM download/checksum failed")
            return receipt
        receipt.checksum_verified = True
        opam_root.mkdir(parents=True, exist_ok=True)
        managed_bin.mkdir(parents=True, exist_ok=True)
        target = managed_bin / OPAM_EXECUTABLE
        shutil.copy2(archive, target)
        target.chmod(0o755)
        # Bind launcher that forces OPAMROOT to the isolated root.
        launcher = write_launcher(
            OPAM_EXECUTABLE,
            target,
            install_root=root,
            environment={"OPAMROOT": str(opam_root)},
        )
        # Prefer the real binary path; launcher is available on PATH.
        receipt.executable_path = str(target)
        receipt.bindings["launcher_path"] = str(launcher)
        receipt.installed = True
        receipt.status = "installed"
        receipt.phase = "installed"
        receipt.messages.append(
            f"Installed OPAM {pin.version} under isolated root {opam_root}"
        )
        return receipt

    receipt.status = "blocked"
    receipt.phase = "blocked"
    receipt.reason_codes.append("no_native_artifact_for_platform")
    receipt.messages.append(
        f"No direct OPAM binary for platform {pin.platform}; "
        "provide a managed pin or set IPFS_DATASETS_PY_OPAM_INSTALL_COMMAND."
    )
    return receipt


def ensure_proverif(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
    install_root: str | Path | None = None,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    isolated_opam_root: str | Path | None = None,
    dry_run: bool = False,
    test_mode: bool = False,
    ensure_opam_first: bool = True,
) -> InstallReceipt:
    """Ensure ProVerif 2.05 is installed into an isolated OPAM root."""

    receipt = InstallReceipt(
        tool_id="proverif",
        requested_version=PROVERIF_VERSION,
        strict=strict,
        yes=yes,
        support_only=False,
        authority_tool=True,
    )
    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()
    opam_root = assert_isolated_opam_root(
        isolated_opam_root
        if isolated_opam_root is not None
        else default_isolated_opam_root(repo_root=repo_root, install_root=root)
    )
    receipt.isolated_opam_root = str(opam_root)

    try:
        pin = select_strict_pin(
            "proverif",
            platform_key=platform_name,
            repo_root=repo_root,
        )
    except ProVerifInstallerError as exc:
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
        "tool_id": "proverif",
        "locked_version": PROVERIF_VERSION,
        "selected_version": pin.version,
        "platform": pin.platform,
        "opam_locked_version": OPAM_VERSION,
        "role": "authority",
        "authority_ceiling": "protocol",
        "opam_is_support_only": True,
        "isolated_opam_root": str(opam_root),
        "global_switch_mutation_forbidden": True,
        "never_uses_global_opam_root": True,
    }

    if ensure_opam_first:
        opam_receipt = ensure_opam(
            yes=yes,
            strict=strict,
            force=force,
            on_progress=on_progress,
            install_root=root,
            platform_key=platform_name,
            repo_root=repo_root,
            isolated_opam_root=opam_root,
            dry_run=dry_run,
            test_mode=test_mode,
        )
        receipt.bindings["opam_install"] = opam_receipt.to_dict()
        if opam_receipt.status not in {"available", "installed"} and not dry_run:
            receipt.status = opam_receipt.status
            receipt.phase = "opam_dependency"
            receipt.reason_codes.append("opam_not_ready")
            receipt.messages.extend(opam_receipt.messages)
            return receipt

    managed_bin = root / "bin"
    path_env = os.pathsep.join(
        part for part in (str(managed_bin), os.environ.get("PATH", "")) if part
    )
    existing = which_executable(PROVERIF_EXECUTABLE, path_env=path_env)
    if existing and not force and not dry_run:
        banner = read_version_banner(existing) or ""
        version_ok = observed_version_matches_lock(banner, PROVERIF_VERSION)
        if version_ok:
            receipt.executable_path = existing
            receipt.already_present = True
            receipt.installed = True
            receipt.status = "available"
            receipt.phase = "available"
            receipt.bindings["opam_executable"] = which_executable(
                OPAM_EXECUTABLE, path_env=path_env
            )
            receipt.messages.append(
                f"ProVerif {PROVERIF_VERSION} available at {existing} "
                f"(isolated OPAM root {opam_root})"
            )
            return receipt
        receipt.messages.append(
            "ProVerif present but failed strict version validation; "
            "re-run with force=True and yes=True to repair."
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
            f"dry-run selected ProVerif {pin.version} for {pin.platform} "
            f"with OPAM {OPAM_VERSION} at isolated root {opam_root}"
        )
        return receipt

    if not yes:
        receipt.status = "blocked"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "ProVerif is missing; re-run with yes=True to install under an "
            "isolated OPAM root."
        )
        return receipt

    try:
        authorize_plugin_install(
            "proverif",
            yes=yes,
            strict=strict,
            checksum_verified=True,
            platform_key=platform_name,
            test_mode=test_mode,
        )
    except ProVerifInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "authorization"
        receipt.reason_codes.append("authorization_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    # Download the pinned ProVerif source archive, then attempt an OPAM/local build
    # inside the isolated root only.
    archive = root / "downloads" / f"proverif-{pin.version}.tar.gz"
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
            raise ProVerifInstallerError("ProVerif download/checksum failed")
        return receipt
    receipt.checksum_verified = True
    source_dest = root / f"proverif-{pin.version}-src"
    _announce(f"Extracting ProVerif {pin.version} into {source_dest}", on_progress)
    if source_dest.exists():
        shutil.rmtree(source_dest)
    _safe_extract_tar(archive, source_dest)

    opam_path = which_executable(OPAM_EXECUTABLE, path_env=path_env)
    if not opam_path:
        receipt.status = "failed"
        receipt.phase = "opam_missing"
        receipt.reason_codes.append("opam_not_ready")
        receipt.messages.append(
            "OPAM binary missing after ensure_opam; cannot build ProVerif"
        )
        if strict:
            raise ProVerifInstallerError("OPAM missing for ProVerif build")
        return receipt

    opam_env = isolated_opam_env(opam_root)
    # Prefer an already-built binary inside the archive (some releases ship one).
    matches = [
        path
        for path in source_dest.rglob(PROVERIF_EXECUTABLE)
        if path.is_file() and os.access(path, os.X_OK)
    ]
    if len(matches) == 1:
        launcher = write_launcher(
            PROVERIF_EXECUTABLE,
            matches[0],
            install_root=root,
            environment={"OPAMROOT": str(opam_root)},
        )
        receipt.executable_path = str(launcher)
        receipt.installed = True
        receipt.status = "installed"
        receipt.phase = "installed"
        receipt.bindings["opam_executable"] = opam_path
        receipt.bindings["source_path"] = str(source_dest)
        receipt.messages.append(
            f"Installed ProVerif {pin.version} from archive under isolated "
            f"OPAM root {opam_root}"
        )
        return receipt

    # Fall back to opam install into the isolated root (no global switch).
    _announce(
        f"Building ProVerif {pin.version} via OPAM in {opam_root}",
        on_progress,
        phase="building",
    )
    try:
        init = subprocess.run(
            [
                opam_path,
                "init",
                "--bare",
                "--disable-sandboxing",
                "--no-setup",
                "--root",
                str(opam_root),
                "-y",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
            env=opam_env,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        receipt.status = "failed"
        receipt.phase = "opam_init"
        receipt.reason_codes.append("opam_init_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise ProVerifInstallerError(f"OPAM init failed: {exc}") from exc
        return receipt

    if init.returncode not in {0, 1}:
        # returncode 1 can mean already initialized.
        receipt.messages.append(
            f"opam init returned {init.returncode}; continuing if root is usable"
        )

    try:
        install = subprocess.run(
            [
                opam_path,
                "install",
                f"proverif.{PROVERIF_VERSION}",
                "--root",
                str(opam_root),
                "-y",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=3600,
            env=opam_env,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        receipt.status = "failed"
        receipt.phase = "opam_install"
        receipt.reason_codes.append("opam_install_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise ProVerifInstallerError(f"OPAM install failed: {exc}") from exc
        return receipt

    if install.returncode != 0:
        receipt.status = "failed"
        receipt.phase = "opam_install"
        receipt.reason_codes.append("opam_install_failed")
        detail = (install.stderr or install.stdout or "").strip()[:500]
        receipt.messages.append(
            f"opam install proverif.{PROVERIF_VERSION} failed: {detail}"
        )
        if strict:
            raise ProVerifInstallerError(receipt.messages[-1])
        return receipt

    # Resolve the installed binary via `opam exec`.
    try:
        which_out = subprocess.run(
            [
                opam_path,
                "exec",
                "--root",
                str(opam_root),
                "--",
                "which",
                PROVERIF_EXECUTABLE,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=opam_env,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        which_out = None

    binary: Path | None = None
    if which_out is not None and which_out.returncode == 0:
        candidate = (which_out.stdout or "").strip().splitlines()
        if candidate:
            path = Path(candidate[0].strip())
            if path.is_file():
                binary = path

    if binary is None:
        # Search the isolated root for the executable.
        found = [
            path
            for path in opam_root.rglob(PROVERIF_EXECUTABLE)
            if path.is_file() and os.access(path, os.X_OK)
        ]
        if found:
            binary = found[0]

    if binary is None:
        receipt.status = "failed"
        receipt.phase = "executable_missing"
        receipt.reason_codes.append("executable_missing")
        receipt.messages.append(
            "ProVerif OPAM install completed but executable was not found"
        )
        if strict:
            raise ProVerifInstallerError(receipt.messages[-1])
        return receipt

    launcher = write_launcher(
        PROVERIF_EXECUTABLE,
        binary,
        install_root=root,
        environment={"OPAMROOT": str(opam_root)},
    )
    receipt.executable_path = str(launcher)
    receipt.installed = True
    receipt.status = "installed"
    receipt.phase = "installed"
    receipt.bindings["opam_executable"] = opam_path
    receipt.bindings["binary_path"] = str(binary)
    receipt.messages.append(
        f"Installed ProVerif {pin.version} via isolated OPAM root {opam_root}"
    )
    return receipt


def plugin_manifest() -> dict[str, Any]:
    """Describe this family plugin for packaging and certification evidence."""

    registry = default_installer_registry()
    plugin = registry.plugin_for(InstallerPluginFamily.PROVERIF)
    entries = [
        entry.to_dict()
        for entry in registry.entries
        if entry.family is InstallerPluginFamily.PROVERIF
        or entry.tool_id in {"proverif", "opam"}
    ]
    # Deduplicate by tool_id while preferring PROVERIF-family entries.
    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        tool_id = str(entry.get("tool_id") or "")
        if tool_id and tool_id not in by_id:
            by_id[tool_id] = entry
    return {
        "interface": PLUGIN_INTERFACE,
        "family": PLUGIN_FAMILY,
        "module_path": PLUGIN_MODULE,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "program": PROGRAM,
        "locked_versions": dict(LOCKED_VERSIONS),
        "ensure_entrypoints": {
            "proverif": "ensure_proverif",
            "opam": "ensure_opam",
        },
        "roles": {
            "proverif": "authority",
            "opam": "support",
        },
        "opam_is_support_only": True,
        "opam_cannot_promote_protocol_lane": True,
        "isolated_opam_root_required": True,
        "global_switch_mutation_forbidden": True,
        "plugin": plugin.to_dict(),
        "entries": list(by_id.values()),
        "policy": {
            "never_on_import": True,
            "requires_explicit_yes": True,
            "user_local_only": True,
            "isolated_opam_root_only": True,
            "never_mutate_global_opam_switch": True,
            "requires_checksum_for_managed_artifacts": True,
            "strict_selects_locked_versions": True,
            "does_not_edit_shared_lock": True,
            "does_not_edit_central_certificate": True,
            "does_not_edit_tamarin_lane": True,
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
    "PROVERIF_VERSION",
    "OPAM_VERSION",
    "LOCKED_VERSIONS",
    "ProVerifInstallerError",
    "ToolPin",
    "InstallReceipt",
    "expand_user_local_root",
    "detect_platform_key",
    "which_executable",
    "numeric_version",
    "default_isolated_opam_root",
    "is_forbidden_global_opam_root",
    "assert_isolated_opam_root",
    "isolated_opam_env",
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
    "ensure_opam",
    "ensure_proverif",
    "plugin_manifest",
    "IMPORT_INSTALLS_FORBIDDEN",
]
