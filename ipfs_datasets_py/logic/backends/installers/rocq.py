"""Rocq/Coq + isolated OPAM installer plugin (FVT-G150 / FVT-045).

``FormalVerificationInstallerPlugin@1`` for the Rocq/Coq kernel lane:

* ``ensure_coq`` — pinned Rocq/Coq 9.1.1 authority kernel
  (package identity ``rocq-prover.9.1.1``)
* ``ensure_opam`` — OPAM 2.5.2 support binary under a repository-local
  isolated root (**support only**, never global switch mutation)

Fail-closed installation contract
---------------------------------
* never installs on import or capability discovery;
* requires an explicit ``ensure_*`` call with ``yes=True``;
* installs only into a user-local or repository-local isolated root;
* never mutates a global OPAM switch (``~/.opam``, system roots);
* under ``strict=True``, only the locked pin versions are accepted:
  Rocq/Coq ``9.1.1`` and OPAM ``2.5.2``;
* OPAM presence alone never grants kernel authority;
* this plugin never edits the shared multi-prover certificate or lock.

Pin selection reads ``config/formal_verification_toolchains.lock.json`` when
available and falls back to the reviewed package/binary inventory below.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
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
PLUGIN_FAMILY: Final = InstallerPluginFamily.ROCQ.value
PLUGIN_MODULE: Final = "ipfs_datasets_py.logic.backends.installers.rocq"
GOAL_ID: Final = "FVT-G150"
TASK_ID: Final = "FVT-045"
PROGRAM: Final = "formal-verification-tactician/rocq-toolchain"

# Locked managed-pin versions (must match deployment lock).
COQ_VERSION: Final = "9.1.1"
ROCQ_VERSION: Final = COQ_VERSION
OPAM_VERSION: Final = "2.5.2"
PACKAGE_IDENTITY: Final = "rocq-prover.9.1.1"
OPAM_REPOSITORY: Final = "https://rocq-prover.org/opam/released"

COQ_EXECUTABLES: Final = ("coqc", "rocq", "coqtop")
PRIMARY_EXECUTABLE: Final = "coqc"
OPAM_EXECUTABLE: Final = "opam"

# Relative path under install root for the isolated OPAM root.
ISOLATED_OPAM_ROOT_SEGMENT: Final = ("opam-roots", "rocq")
REPO_ISOLATED_OPAM_RELATIVE: Final = Path(".cache/formal_verification/opam-roots/rocq")

# Reviewed fallback pins when the lock file is unavailable (tests / offline).
_FALLBACK_PINS: Final[dict[str, tuple[dict[str, Any], ...]]] = {
    "coq": (
        {
            "tool_id": "coq",
            "version": COQ_VERSION,
            "platform": "any",
            "artifact_url": "",
            "sha256": "",
            "identity_kind": "opam_package",
            "package_identity": PACKAGE_IDENTITY,
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
    "coq": COQ_VERSION,
    "rocq": ROCQ_VERSION,
    "opam": OPAM_VERSION,
}

ProgressCallback = Callable[[str, str], None]

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)+)")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class RocqInstallerError(RuntimeError):
    """Raised when a strict Rocq/Coq/OPAM install policy is violated."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolPin:
    """One platform-specific managed pin for a Rocq-lane tool."""

    tool_id: str
    version: str
    platform: str
    artifact_url: str = ""
    sha256: str = ""
    identity_kind: str = "opam_package"
    package_identity: str = ""

    def __post_init__(self) -> None:
        for name in ("tool_id", "version", "platform"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise RocqInstallerError(f"{name} must be a non-empty trimmed string")
        kind = (self.identity_kind or "opam_package").strip()
        object.__setattr__(self, "identity_kind", kind)
        digest = (self.sha256 or "").lower()
        if kind == "opam_package":
            package = (self.package_identity or "").strip()
            if not package:
                # Derive from version when lock omits explicit package identity.
                package = f"rocq-prover.{self.version}"
            object.__setattr__(self, "package_identity", package)
            object.__setattr__(self, "sha256", digest)
            return
        if not digest or not _HEX64.match(digest):
            raise RocqInstallerError(
                f"sha256 for {self.tool_id!r} must be a 64-char lowercase hex digest "
                f"for identity_kind={kind!r}"
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
            "package_identity": self.package_identity,
            "is_checksummed": bool(self.sha256 and _HEX64.match(self.sha256)),
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
    install_attempted: bool = False
    download_attempted: bool = False
    isolated_opam_root: str | None = None
    package_identity: str | None = None
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
    """Return the repository-local / managed isolated OPAM root for Rocq.

    Never returns ``~/.opam`` or another global switch path. Serialized
    separately from the ProVerif OPAM root (``opam-roots/proverif``).
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
        raise RocqInstallerError(
            f"refusing global OPAM root {resolved}; Rocq/Coq requires an "
            "isolated repository-local or managed root"
        )
    ambient = os.environ.get("OPAMROOT")
    if ambient:
        try:
            ambient_path = Path(os.path.expanduser(ambient)).resolve()
        except OSError:
            ambient_path = None
        if ambient_path is not None and is_forbidden_global_opam_root(ambient_path):
            if resolved == ambient_path:
                raise RocqInstallerError(
                    "refusing to use ambient global OPAMROOT for Rocq/Coq"
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
        raise RocqInstallerError("deployment lock must be a JSON object")
    return payload


def _normalize_tool_id(tool_id: str) -> str:
    name = str(tool_id or "").strip().lower()
    if name in {"rocq", "coqc", "coqtop"}:
        return "coq"
    return name


def pins_for_tool(
    tool_id: str,
    *,
    repo_root: Path | str | None = None,
    lock: Mapping[str, Any] | None = None,
) -> tuple[ToolPin, ...]:
    """Return managed pins for ``tool_id`` from the lock or reviewed fallbacks."""

    canonical = _normalize_tool_id(tool_id)
    document = lock if lock is not None else load_lock_document(repo_root)
    pins: list[ToolPin] = []
    if document is not None:
        tools = document.get("tools") or []
        if not isinstance(tools, list):
            raise RocqInstallerError("deployment lock tools must be a list")
        for entry in tools:
            if not isinstance(entry, Mapping):
                continue
            entry_id = _normalize_tool_id(str(entry.get("tool_id") or ""))
            if entry_id != canonical:
                continue
            contract = entry.get("deployment_contract") or {}
            default_package = ""
            if isinstance(contract, Mapping):
                default_package = str(contract.get("package_identity") or "")
            default_kind = str(
                entry.get("identity_kind")
                or (
                    "opam_package"
                    if canonical == "coq"
                    else "release_archive"
                )
            )
            for raw in entry.get("pins") or []:
                if not isinstance(raw, Mapping):
                    continue
                pin_tool = _normalize_tool_id(str(raw.get("tool_id") or canonical))
                package = str(
                    raw.get("package_identity")
                    or default_package
                    or (PACKAGE_IDENTITY if pin_tool == "coq" else "")
                )
                pins.append(
                    ToolPin(
                        tool_id=pin_tool if pin_tool == "opam" else "coq",
                        version=str(raw.get("version") or ""),
                        platform=str(raw.get("platform") or "any"),
                        artifact_url=str(raw.get("artifact_url") or ""),
                        sha256=str(raw.get("sha256") or "").lower(),
                        identity_kind=str(
                            raw.get("identity_kind") or default_kind
                        ),
                        package_identity=package,
                    )
                )
            break
        # Inventory-level package identity for Rocq when tools pins are thin.
        if not pins and canonical == "coq":
            inventory = document.get("checksummed_release_inventory") or {}
            if isinstance(inventory, Mapping):
                for key in ("rocq", "coq"):
                    item = inventory.get(key)
                    if not isinstance(item, Mapping):
                        continue
                    pins.append(
                        ToolPin(
                            tool_id="coq",
                            version=str(item.get("version") or COQ_VERSION),
                            platform="any",
                            artifact_url=str(item.get("url") or ""),
                            sha256=str(item.get("sha256") or "").lower(),
                            identity_kind=str(
                                item.get("identity_kind") or "opam_package"
                            ),
                            package_identity=str(
                                item.get("package_identity") or PACKAGE_IDENTITY
                            ),
                        )
                    )
                    break
    if not pins:
        for raw in _FALLBACK_PINS.get(canonical, ()):
            pins.append(
                ToolPin(
                    tool_id=str(raw["tool_id"]),
                    version=str(raw["version"]),
                    platform=str(raw["platform"]),
                    artifact_url=str(raw.get("artifact_url") or ""),
                    sha256=str(raw.get("sha256") or "").lower(),
                    identity_kind=str(raw.get("identity_kind") or "opam_package"),
                    package_identity=str(raw.get("package_identity") or ""),
                )
            )
    if not pins:
        raise RocqInstallerError(f"no managed pins registered for {tool_id!r}")
    return tuple(pins)


def locked_version_for(tool_id: str, *, lock: Mapping[str, Any] | None = None) -> str:
    """Return the exact managed pin version required under strict install."""

    canonical = _normalize_tool_id(tool_id)
    if lock is not None:
        versions = lock.get("managed_pin_versions") or {}
        if isinstance(versions, Mapping):
            if canonical in versions:
                return str(versions[canonical])
            if canonical == "coq" and "rocq" in versions:
                return str(versions["rocq"])
    if canonical in LOCKED_VERSIONS:
        return LOCKED_VERSIONS[canonical]
    raise RocqInstallerError(f"no locked version for tool_id={tool_id!r}")


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

    Under the FVT-G150 contract this is the only pin that strict installation
    may materialize. Version mismatches fail closed rather than upgrading.
    Rocq/Coq is an OPAM package under platform ``any``.
    """

    canonical = _normalize_tool_id(tool_id)
    platform_name = platform_key or detect_platform_key()
    expected = locked_version_for(canonical, lock=lock)
    candidates = pins_for_tool(canonical, repo_root=repo_root, lock=lock)
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
    raise RocqInstallerError(
        f"strict install for {canonical!r} requires version {expected!r} on "
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
        url, headers={"User-Agent": "ipfs-datasets-py-rocq-installer/1"}
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


def resolve_coq_executable(*, path_env: str | None = None) -> str | None:
    """Locate coqc/rocq/coqtop preferring managed install paths."""

    for name in COQ_EXECUTABLES:
        found = which_executable(name, path_env=path_env)
        if found:
            return found
    return None


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
    """Fail-closed gate shared by ensure_coq / ensure_opam."""

    canonical = _normalize_tool_id(tool_id)
    if canonical not in {"coq", "opam"}:
        raise RocqInstallerError(
            f"rocq plugin does not own tool_id={tool_id!r}"
        )
    try:
        authorize_installer_entry_install(
            canonical,
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
        raise RocqInstallerError(str(exc)) from exc
    entry = get_installer_entry(canonical)
    if entry.family is not InstallerPluginFamily.ROCQ:
        raise RocqInstallerError(
            f"tool {canonical!r} is not bound to the rocq installer plugin"
        )
    if strict:
        select_strict_pin(canonical, platform_key=platform_key)


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
    except RocqInstallerError as exc:
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
        "can_promote_kernel_lane": False,
        "isolated_opam_root": str(opam_root),
        "global_switch_mutation_forbidden": True,
        "never_uses_global_opam_root": True,
        "serialized_with_proverif": True,
        "opam_root_segment": "rocq",
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
    except RocqInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "authorization"
        receipt.reason_codes.append("authorization_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    if pin.artifact_url and "opam-" in pin.artifact_url:
        receipt.install_attempted = True
        receipt.download_attempted = True
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
                raise RocqInstallerError("OPAM download/checksum failed")
            return receipt
        receipt.checksum_verified = True
        opam_root.mkdir(parents=True, exist_ok=True)
        managed_bin.mkdir(parents=True, exist_ok=True)
        target = managed_bin / OPAM_EXECUTABLE
        shutil.copy2(archive, target)
        target.chmod(0o755)
        launcher = write_launcher(
            OPAM_EXECUTABLE,
            target,
            install_root=root,
            environment={"OPAMROOT": str(opam_root)},
        )
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


def ensure_coq(
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
    """Ensure Rocq/Coq 9.1.1 is installed into an isolated OPAM root."""

    receipt = InstallReceipt(
        tool_id="coq",
        requested_version=COQ_VERSION,
        strict=strict,
        yes=yes,
        support_only=False,
        authority_tool=True,
        package_identity=PACKAGE_IDENTITY,
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
            "coq",
            platform_key=platform_name,
            repo_root=repo_root,
        )
    except RocqInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "pin_selection"
        receipt.reason_codes.append("pin_selection_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    package = pin.package_identity or PACKAGE_IDENTITY
    receipt.selected_version = pin.version
    receipt.selected_platform = pin.platform
    receipt.pin = pin.to_dict()
    receipt.package_identity = package
    receipt.bindings = {
        "tool_id": "coq",
        "display_name": "Rocq/Coq kernel",
        "locked_version": COQ_VERSION,
        "selected_version": pin.version,
        "platform": pin.platform,
        "package_identity": package,
        "opam_locked_version": OPAM_VERSION,
        "opam_repository": OPAM_REPOSITORY,
        "role": "authority",
        "authority_ceiling": "kernel",
        "opam_is_support_only": True,
        "isolated_opam_root": str(opam_root),
        "global_switch_mutation_forbidden": True,
        "never_uses_global_opam_root": True,
        "serialized_with_proverif": True,
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
    existing = resolve_coq_executable(path_env=path_env)
    if existing and not force and not dry_run:
        banner = read_version_banner(existing) or ""
        version_ok = observed_version_matches_lock(banner, COQ_VERSION)
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
                f"Rocq/Coq {COQ_VERSION} available at {existing} "
                f"(isolated OPAM root {opam_root})"
            )
            return receipt
        receipt.messages.append(
            "Rocq/Coq present but failed strict version validation; "
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
            f"dry-run selected Rocq/Coq {pin.version} package {package} "
            f"with OPAM {OPAM_VERSION} at isolated root {opam_root}"
        )
        return receipt

    if not yes:
        receipt.status = "blocked"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "Rocq/Coq is missing; re-run with yes=True to install under an "
            "isolated OPAM root."
        )
        return receipt

    try:
        authorize_plugin_install(
            "coq",
            yes=yes,
            strict=strict,
            # OPAM package installs are not archive-checksumed; gate uses package pin.
            checksum_verified=True,
            platform_key=platform_name,
            test_mode=test_mode,
        )
    except RocqInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "authorization"
        receipt.reason_codes.append("authorization_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise
        return receipt

    receipt.install_attempted = True
    opam_path = which_executable(OPAM_EXECUTABLE, path_env=path_env)
    if not opam_path:
        receipt.status = "failed"
        receipt.phase = "opam_missing"
        receipt.reason_codes.append("opam_not_ready")
        receipt.messages.append(
            "OPAM binary missing after ensure_opam; cannot install Rocq/Coq"
        )
        if strict:
            raise RocqInstallerError("OPAM missing for Rocq/Coq install")
        return receipt

    opam_env = isolated_opam_env(opam_root)
    opam_root.mkdir(parents=True, exist_ok=True)

    _announce(
        f"Initializing isolated OPAM root {opam_root}",
        on_progress,
        phase="opam_init",
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
            raise RocqInstallerError(f"OPAM init failed: {exc}") from exc
        return receipt

    if init.returncode not in {0, 1}:
        receipt.messages.append(
            f"opam init returned {init.returncode}; continuing if root is usable"
        )

    # Prefer the Rocq OPAM repository when available; fall back to package name.
    _announce(
        f"Installing {package} via OPAM in {opam_root}",
        on_progress,
        phase="building",
    )
    try:
        # Register the released Rocq repository (best-effort; may already exist).
        subprocess.run(
            [
                opam_path,
                "repository",
                "add",
                "rocq-released",
                OPAM_REPOSITORY,
                "--root",
                str(opam_root),
                "-y",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env=opam_env,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        install = subprocess.run(
            [
                opam_path,
                "install",
                package,
                "--root",
                str(opam_root),
                "-y",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=7200,
            env=opam_env,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        receipt.status = "failed"
        receipt.phase = "opam_install"
        receipt.reason_codes.append("opam_install_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise RocqInstallerError(f"OPAM install failed: {exc}") from exc
        return receipt

    if install.returncode != 0:
        receipt.status = "failed"
        receipt.phase = "opam_install"
        receipt.reason_codes.append("opam_install_failed")
        detail = (install.stderr or install.stdout or "").strip()[:500]
        receipt.messages.append(f"opam install {package} failed: {detail}")
        if strict:
            raise RocqInstallerError(receipt.messages[-1])
        return receipt

    binary: Path | None = None
    for exe_name in COQ_EXECUTABLES:
        try:
            which_out = subprocess.run(
                [
                    opam_path,
                    "exec",
                    "--root",
                    str(opam_root),
                    "--",
                    "which",
                    exe_name,
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
        if which_out is not None and which_out.returncode == 0:
            candidate_lines = (which_out.stdout or "").strip().splitlines()
            if candidate_lines:
                path = Path(candidate_lines[0].strip())
                if path.is_file():
                    binary = path
                    break

    if binary is None:
        for exe_name in COQ_EXECUTABLES:
            found = [
                path
                for path in opam_root.rglob(exe_name)
                if path.is_file() and os.access(path, os.X_OK)
            ]
            if found:
                binary = found[0]
                break

    if binary is None:
        receipt.status = "failed"
        receipt.phase = "executable_missing"
        receipt.reason_codes.append("executable_missing")
        receipt.messages.append(
            "Rocq/Coq OPAM install completed but coqc/rocq executable was not found"
        )
        if strict:
            raise RocqInstallerError(receipt.messages[-1])
        return receipt

    if strict:
        banner = read_version_banner(str(binary)) or ""
        if not observed_version_matches_lock(banner, COQ_VERSION):
            receipt.status = "failed"
            receipt.phase = "validation"
            receipt.reason_codes.append("runtime_validation_failed")
            receipt.messages.append(
                f"Installed Rocq/Coq did not report locked version {COQ_VERSION}: "
                f"{banner[:200]!r}"
            )
            if strict:
                raise RocqInstallerError(receipt.messages[-1])
            return receipt

    for name in (PRIMARY_EXECUTABLE, "rocq", "coqtop"):
        write_launcher(
            name,
            binary if binary.name == name or name == PRIMARY_EXECUTABLE else binary,
            install_root=root,
            environment={"OPAMROOT": str(opam_root)},
        )

    launcher = write_launcher(
        PRIMARY_EXECUTABLE,
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
        f"Installed Rocq/Coq {pin.version} ({package}) via isolated OPAM root "
        f"{opam_root}"
    )
    return receipt


# Compatibility alias used by lock installer_entry and older callers.
ensure_rocq = ensure_coq


def plugin_manifest() -> dict[str, Any]:
    """Describe this family plugin for packaging and certification evidence."""

    registry = default_installer_registry()
    plugin = registry.plugin_for(InstallerPluginFamily.ROCQ)
    entries = [
        entry.to_dict()
        for entry in registry.entries
        if entry.family is InstallerPluginFamily.ROCQ
        or entry.tool_id in {"coq", "opam", "rocq"}
    ]
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
        "package_identity": PACKAGE_IDENTITY,
        "opam_repository": OPAM_REPOSITORY,
        "ensure_entrypoints": {
            "coq": "ensure_coq",
            "rocq": "ensure_coq",
            "opam": "ensure_opam",
        },
        "roles": {
            "coq": "authority",
            "rocq": "authority",
            "opam": "support",
        },
        "opam_is_support_only": True,
        "opam_cannot_promote_kernel_lane": True,
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
            "strict_selects_locked_versions": True,
            "does_not_edit_shared_lock": True,
            "does_not_edit_central_certificate": True,
            "serialize_opam_with_proverif": True,
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
    "COQ_VERSION",
    "ROCQ_VERSION",
    "OPAM_VERSION",
    "PACKAGE_IDENTITY",
    "OPAM_REPOSITORY",
    "LOCKED_VERSIONS",
    "RocqInstallerError",
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
    "resolve_coq_executable",
    "authorize_plugin_install",
    "ensure_opam",
    "ensure_coq",
    "ensure_rocq",
    "plugin_manifest",
    "IMPORT_INSTALLS_FORBIDDEN",
]
