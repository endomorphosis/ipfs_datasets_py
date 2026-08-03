"""Advisor family installer plugin (FVT-G160 / FVT-050).

``FormalVerificationInstallerPlugin@1`` for the hammer/advisor lane:

* ``ensure_symbolicai`` — locked SymbolicAI Python package identity
* ``ensure_ergoai`` — locked ErgoAI/ErgoEngine 3.0 identity

Fail-closed installation contract
---------------------------------
* never installs on import or capability discovery;
* requires an explicit ``ensure_*`` call with ``yes=True``;
* user-local installs only (no system package manager mutation);
* under ``strict=True``, only the locked pin identities are accepted:
  SymbolicAI ``>=1.14.0,<2.0.0`` and ErgoAI ``3.0``;
* advisors remain **advisor/candidate** role with advisory authority ceiling;
* presence or successful install never grants theorem / kernel / solver proof
  authority;
* this plugin never edits the shared multi-prover certificate or model runtimes.

Pin selection reads ``config/formal_verification_toolchains.lock.json`` when
available and falls back to the reviewed identities below.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
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
    load_deployment_lock,
)

PLUGIN_INTERFACE: Final = "FormalVerificationInstallerPlugin@1"
PLUGIN_FAMILY: Final = InstallerPluginFamily.ADVISORS.value
PLUGIN_MODULE: Final = "ipfs_datasets_py.logic.backends.installers.advisors"
GOAL_ID: Final = "FVT-G160"
TASK_ID: Final = "FVT-050"
PROGRAM: Final = "formal-verification-tactician/advisor-toolchains"

TOOL_SYMBOLICAI: Final = "symbolicai"
TOOL_ERGOAI: Final = "ergoai"
ADVISOR_INSTALL_TOOLS: Final = (TOOL_SYMBOLICAI, TOOL_ERGOAI)

# Locked managed-pin identities (must match deployment lock).
SYMBOLICAI_VERSION: Final = ">=1.14.0,<2.0.0"
SYMBOLICAI_PACKAGE: Final = "symbolicai"
ERGOAI_VERSION: Final = "3.0"
ERGOAI_EXECUTABLES: Final = ("ergoai", "runErgo.sh", "runergo")
ERGOAI_RELEASE_TAG: Final = "v3.0_release"
ERGOAI_RELEASE_URL: Final = (
    "https://github.com/ErgoAI/.github/releases/download/"
    "v3.0_release/ergoAI_3.0.run"
)
# SHA-256 of the official GitHub release asset published under
# ``ErgoAI/.github@v3.0_release``.  A live installer must never execute the
# self-extracting archive unless this digest matches exactly.
ERGOAI_RELEASE_SHA256: Final = (
    "46f9747db118567a7da50f70b439e35ee36ea02c3dfde971a57c77a8ce94aa01"
)
ERGOAI_RELEASE_SIZE_BYTES: Final = 53_064_767
# The shared Linux/Mac release is source-bearing and compiles XSB for the host.
# These are the platforms for which this project carries an exact reviewed pin;
# other hosts fail closed until their artifact is independently exercised.
ERGOAI_SUPPORTED_PLATFORMS: Final = (
    "linux-x86_64",
    "linux-aarch64",
)
ERGOAI_BUILD_COMMANDS: Final = ("sh", "make", "gcc", "flex", "bison")
ERGOAI_LICENSE_COMPONENTS: Final = ("Apache-2.0", "LGPL-2.0")

LOCKED_VERSIONS: Final[Mapping[str, str]] = {
    TOOL_SYMBOLICAI: SYMBOLICAI_VERSION,
    TOOL_ERGOAI: ERGOAI_VERSION,
}

# Reviewed fallback pins when the lock file is unavailable (tests / offline).
_FALLBACK_PINS: Final[dict[str, tuple[dict[str, Any], ...]]] = {
    TOOL_SYMBOLICAI: (
        {
            "tool_id": TOOL_SYMBOLICAI,
            "version": SYMBOLICAI_VERSION,
            "platform": "any",
            "artifact_url": "https://pypi.org/project/symbolicai/",
            "sha256": "",
            "identity_kind": "python_package",
            "license": "BSD-3-Clause",
            "source": "https://github.com/ExtensityAI/symbolicai",
            "package_name": SYMBOLICAI_PACKAGE,
            "is_checksummed": False,
        },
    ),
    TOOL_ERGOAI: (
        {
            "tool_id": TOOL_ERGOAI,
            "version": ERGOAI_VERSION,
            "platform": "linux-x86_64",
            "artifact_url": ERGOAI_RELEASE_URL,
            "sha256": ERGOAI_RELEASE_SHA256,
            "identity_kind": "immutable_release_tag",
            "license": "Apache-2.0",
            "source": "https://github.com/ErgoAI/ErgoEngine",
            "is_checksummed": True,
            "requires_checksum_at_install": True,
            "release_tag": ERGOAI_RELEASE_TAG,
            "artifact_size_bytes": ERGOAI_RELEASE_SIZE_BYTES,
        },
        {
            "tool_id": TOOL_ERGOAI,
            "version": ERGOAI_VERSION,
            "platform": "linux-aarch64",
            "artifact_url": ERGOAI_RELEASE_URL,
            "sha256": ERGOAI_RELEASE_SHA256,
            "identity_kind": "immutable_release_tag",
            "license": "Apache-2.0",
            "source": "https://github.com/ErgoAI/ErgoEngine",
            "is_checksummed": True,
            "requires_checksum_at_install": True,
            "release_tag": ERGOAI_RELEASE_TAG,
            "artifact_size_bytes": ERGOAI_RELEASE_SIZE_BYTES,
        },
    ),
}

# Role boundary: installers never elevate advisors past advisory authority.
ADVISOR_ROLE: Final = "advisor"
ADVISOR_AUTHORITY_CEILING: Final = "advisory"
IMPORT_INSTALLS_FORBIDDEN: Final = True

ProgressCallback = Callable[[str, str], None]

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)+)")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SYMBOLICAI_RANGE_RE = re.compile(
    r"^>=\s*(\d+(?:\.\d+)*)\s*,\s*<\s*(\d+(?:\.\d+)*)$"
)


class AdvisorInstallerError(RuntimeError):
    """Raised when a strict advisor install policy is violated."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolPin:
    """One platform-specific managed pin for an advisor-lane tool."""

    tool_id: str
    version: str
    platform: str
    artifact_url: str = ""
    sha256: str = ""
    identity_kind: str = "python_package"
    license: str = ""
    source: str = ""
    package_name: str = ""
    is_checksummed: bool = False
    requires_checksum_at_install: bool = False
    release_tag: str = ""
    artifact_size_bytes: int = 0

    def __post_init__(self) -> None:
        for name in ("tool_id", "version", "platform"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise AdvisorInstallerError(f"{name} must be a non-empty trimmed string")
        digest = (self.sha256 or "").lower()
        if digest and not _HEX64.match(digest):
            raise AdvisorInstallerError(
                f"sha256 for {self.tool_id!r} must be empty or a 64-char hex digest"
            )
        object.__setattr__(self, "sha256", digest)
        if self.artifact_size_bytes < 0:
            raise AdvisorInstallerError("artifact_size_bytes must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "version": self.version,
            "platform": self.platform,
            "artifact_url": self.artifact_url,
            "sha256": self.sha256,
            "identity_kind": self.identity_kind,
            "license": self.license,
            "source": self.source,
            "package_name": self.package_name,
            "is_checksummed": self.is_checksummed,
            "requires_checksum_at_install": self.requires_checksum_at_install,
            "release_tag": self.release_tag,
            "artifact_size_bytes": self.artifact_size_bytes,
        }


@dataclass(slots=True)
class InstallReceipt:
    """Machine-readable result of one ensure_* invocation."""

    tool_id: str
    requested_version: str
    selected_version: str | None = None
    selected_platform: str | None = None
    executable_path: str | None = None
    package_name: str | None = None
    pin: dict[str, Any] | None = None
    status: str = "blocked"  # available | installed | blocked | failed | refused
    phase: str = "init"
    installed: bool = False
    already_present: bool = False
    install_attempted: bool = False
    checksum_verified: bool = False
    strict: bool = True
    yes: bool = False
    user_local: bool = True
    role: str = ADVISOR_ROLE
    authority_ceiling: str = ADVISOR_AUTHORITY_CEILING
    grants_theorem_authority: bool = False
    grants_proof_authority: bool = False
    reason_codes: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    bindings: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.grants_theorem_authority or self.grants_proof_authority:
            raise AdvisorInstallerError(
                "advisor install receipts cannot grant theorem or proof authority"
            )
        if self.role not in {ADVISOR_ROLE, "candidate"}:
            raise AdvisorInstallerError(
                f"advisor install receipts must remain role=advisor/candidate, got {self.role!r}"
            )
        if self.authority_ceiling != ADVISOR_AUTHORITY_CEILING:
            raise AdvisorInstallerError(
                "advisor install receipts must keep authority_ceiling=advisory"
            )

    @property
    def ok(self) -> bool:
        return self.status in {"available", "installed"} and bool(self.selected_version)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Path / platform helpers
# ---------------------------------------------------------------------------


def expand_user_local_root(root: str | Path | None = None) -> Path:
    """Return the user-local theorem-prover / advisor install root."""

    if root is not None:
        return Path(os.path.expanduser(str(root))).resolve()
    env = os.environ.get("IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    env = os.environ.get("IPFS_DATASETS_PY_THEOREM_PROVERS_ROOT")
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
    return shutil.which(name, path=search_path)


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


def _ergoai_version_root(install_root: Path, version: str) -> Path:
    return install_root / "advisors" / TOOL_ERGOAI / version


def _ergoai_identity_path(install_root: Path, version: str) -> Path:
    return _ergoai_version_root(install_root, version) / "identity.json"


def _ergoai_vendor_root(install_root: Path, version: str, digest: str) -> Path:
    # Content-address the extracted tree so a failed/partial install never
    # overwrites a previously certified vendor payload.
    return _ergoai_version_root(install_root, version) / f"vendor-{digest[:16]}"


def _load_identity_manifest(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _copy_or_download_ergoai_artifact(
    pin: ToolPin,
    destination: Path,
    *,
    artifact_path: str | Path | None = None,
    timeout: float = 180.0,
    on_progress: ProgressCallback | None = None,
) -> tuple[bool, str | None, int | None]:
    """Materialize the reviewed release asset and verify it before execution."""

    if not pin.sha256 or not _HEX64.fullmatch(pin.sha256):
        _announce(
            "ErgoAI live installation has no reviewed SHA-256 pin; refusing",
            on_progress,
            phase="failed",
        )
        return False, None, None

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        observed = content_sha256(destination)
        observed_size = destination.stat().st_size
        if observed == pin.sha256 and (
            not pin.artifact_size_bytes
            or observed_size == pin.artifact_size_bytes
        ):
            _announce(
                f"Reusing checksummed ErgoAI artifact at {destination}",
                on_progress,
                phase="available",
            )
            return True, observed, observed_size

    source = Path(artifact_path).expanduser() if artifact_path else None
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".partial",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            if source is not None:
                if not source.is_file():
                    _announce(
                        f"Configured ErgoAI release file does not exist: {source}",
                        on_progress,
                        phase="failed",
                    )
                    return False, None, None
                _announce(
                    f"Copying operator-provided ErgoAI release asset {source}",
                    on_progress,
                    phase="installing",
                )
                with source.open("rb") as input_stream:
                    shutil.copyfileobj(input_stream, handle, length=1024 * 1024)
            else:
                if not pin.artifact_url:
                    _announce(
                        "ErgoAI pin has no artifact URL; refusing live install",
                        on_progress,
                        phase="failed",
                    )
                    return False, None, None
                _announce(
                    f"Downloading checksummed ErgoAI {pin.version} release",
                    on_progress,
                    phase="installing",
                )
                request = Request(
                    pin.artifact_url,
                    headers={
                        "User-Agent": "ipfs-datasets-py-ergoai-installer/1"
                    },
                )
                with urlopen(request, timeout=timeout) as response:  # noqa: S310
                    shutil.copyfileobj(response, handle, length=1024 * 1024)
            handle.flush()
            os.fsync(handle.fileno())

        observed = content_sha256(temporary)
        observed_size = temporary.stat().st_size
        if observed != pin.sha256:
            _announce(
                "ErgoAI release checksum mismatch; refusing to execute artifact",
                on_progress,
                phase="failed",
            )
            return False, observed, observed_size
        if pin.artifact_size_bytes and observed_size != pin.artifact_size_bytes:
            _announce(
                "ErgoAI release size mismatch; refusing to execute artifact",
                on_progress,
                phase="failed",
            )
            return False, observed, observed_size
        temporary.replace(destination)
        temporary = None
        return True, observed, observed_size
    except Exception as exc:  # pragma: no cover - network/host-specific failure
        _announce(f"ErgoAI artifact acquisition failed: {exc}", on_progress, phase="failed")
        return False, None, None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _ergoai_missing_build_commands() -> list[str]:
    return [name for name in ERGOAI_BUILD_COMMANDS if shutil.which(name) is None]


def _find_vendor_ergoai_binary(vendor_root: Path, version: str) -> Path | None:
    expected = (
        vendor_root
        / f"ERGOAI_{version}"
        / "ErgoAI"
        / "runergo"
    )
    candidates = [expected]
    try:
        candidates.extend(sorted(vendor_root.glob("ERGOAI_*/ErgoAI/runergo")))
    except OSError:
        pass
    for candidate in candidates:
        try:
            if (
                candidate.is_file()
                and (candidate.parent / ".ergo_paths").is_file()
            ):
                candidate.chmod(candidate.stat().st_mode | stat.S_IXUSR)
                return candidate.resolve()
        except OSError:
            continue
    return None


def _find_vendor_xsb_binary(vendor_binary: Path) -> Path | None:
    version_root = vendor_binary.parents[1]
    config_root = version_root / "XSB" / "config"
    try:
        candidates = sorted(config_root.glob("*/bin/xsb"))
    except OSError:
        return None
    executable = [
        path
        for path in candidates
        if path.is_file() and os.access(path, os.X_OK)
    ]
    return executable[0].resolve() if len(executable) == 1 else None


def _write_vendor_ergoai_launchers(
    *,
    install_root: Path,
    vendor_binary: Path,
    version: str,
    platform_key: str,
) -> dict[str, str]:
    """Write launchers that expose a deterministic pin identity probe."""

    bin_dir = install_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    launchers: dict[str, str] = {}
    for name in ERGOAI_EXECUTABLES:
        launcher = bin_dir / name
        source = (
            "#!/bin/sh\n"
            "set -eu\n"
            "case \"${1:-}\" in\n"
            "  --version|-v|version)\n"
            f"    printf '%s\\n' 'ErgoAI {version} (managed {platform_key}; "
            f"{ERGOAI_RELEASE_TAG})'\n"
            "    exit 0\n"
            "    ;;\n"
            "esac\n"
            f"exec {_shell_quote(str(vendor_binary))} \"$@\"\n"
        )
        digest = _write_executable(launcher, source)
        launchers[name] = digest
    return launchers


def _normalize_ergoai_verdict(output: str) -> str:
    if "++Error" in output or "++Abort" in output:
        return "error"
    verdicts = re.findall(r"(?m)^\s*(Yes|No)\s*$", output)
    if not verdicts:
        return "unknown"
    return verdicts[-1].lower()


def _run_ergoai_semantic_case(
    executable: str | Path,
    *,
    program: str,
    query: str,
    timeout: float,
) -> dict[str, Any]:
    source_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".ergo",
            prefix="ipfs-datasets-ergoai-cert-",
            delete=False,
        ) as handle:
            handle.write(program)
            source_path = Path(handle.name)
        commands = f"load{{'{source_path}'}}.\n{query}.\n\\halt.\n"
        completed = subprocess.run(
            [str(executable)],
            input=commands,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        combined = "\n".join(
            part for part in (completed.stdout, completed.stderr) if part
        )
        verdict = _normalize_ergoai_verdict(combined)
        return {
            "returncode": completed.returncode,
            "verdict": verdict,
            "output_digest_sha256": hashlib.sha256(
                combined.encode("utf-8")
            ).hexdigest(),
            "program_digest_sha256": hashlib.sha256(
                program.encode("utf-8")
            ).hexdigest(),
            "query_digest_sha256": hashlib.sha256(
                query.encode("utf-8")
            ).hexdigest(),
            "passed_process_boundary": completed.returncode == 0,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "returncode": None,
            "verdict": "error",
            "error": str(exc)[:300],
            "passed_process_boundary": False,
        }
    finally:
        if source_path is not None:
            source_path.unlink(missing_ok=True)


def run_ergoai_semantic_checks(
    executable: str | Path,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Run bounded positive/negative/mutation/replay checks on real ErgoAI."""

    base_program = "fvt_ergo_subject : fvt_ergo_expected.\n"
    mutated_program = "fvt_ergo_subject : fvt_ergo_mutated.\n"
    positive = _run_ergoai_semantic_case(
        executable,
        program=base_program,
        query="fvt_ergo_subject : fvt_ergo_expected",
        timeout=timeout,
    )
    negative = _run_ergoai_semantic_case(
        executable,
        program=base_program,
        query="fvt_ergo_subject : fvt_ergo_absent",
        timeout=timeout,
    )
    mutation = _run_ergoai_semantic_case(
        executable,
        program=mutated_program,
        query="fvt_ergo_subject : fvt_ergo_expected",
        timeout=timeout,
    )
    replay = _run_ergoai_semantic_case(
        executable,
        program=base_program,
        query="fvt_ergo_subject : fvt_ergo_expected",
        timeout=timeout,
    )
    checks = {
        "positive": {**positive, "expected": "yes"},
        "negative": {**negative, "expected": "no"},
        "mutation": {**mutation, "expected": "no"},
        "replay": {**replay, "expected": "yes"},
    }
    for value in checks.values():
        value["passed"] = bool(
            value.get("passed_process_boundary")
            and value.get("verdict") == value.get("expected")
        )
    replay_bound = (
        positive.get("verdict") == replay.get("verdict") == "yes"
        and positive.get("program_digest_sha256")
        == replay.get("program_digest_sha256")
        and positive.get("query_digest_sha256")
        == replay.get("query_digest_sha256")
    )
    passed = all(value["passed"] for value in checks.values()) and replay_bound
    normalized_evidence = {
        name: {
            "expected": value["expected"],
            "verdict": value.get("verdict"),
            "returncode": value.get("returncode"),
            "program_digest_sha256": value.get("program_digest_sha256"),
            "query_digest_sha256": value.get("query_digest_sha256"),
            "passed": value["passed"],
        }
        for name, value in checks.items()
    }
    return {
        "schema_version": "ergoai-live-semantic-checks/v1",
        "tool_id": TOOL_ERGOAI,
        "checks": checks,
        "replay_bound": replay_bound,
        "passed": passed,
        "normalized_evidence_digest_sha256": hashlib.sha256(
            json.dumps(
                {
                    "checks": normalized_evidence,
                    "replay_bound": replay_bound,
                    "passed": passed,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "network_used": False,
        "install_attempted": False,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "grants_proof_authority": False,
    }


def _announce(
    message: str,
    on_progress: ProgressCallback | None,
    *,
    phase: str = "info",
) -> None:
    if on_progress is not None:
        on_progress(phase, message)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


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
    try:
        payload = load_deployment_lock(repo_root, lock_path=path)
    except Exception:
        payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, Mapping):
        return dict(payload)
    raise AdvisorInstallerError("deployment lock must be a JSON object")


def pins_for_tool(
    tool_id: str,
    *,
    repo_root: Path | str | None = None,
    lock: Mapping[str, Any] | None = None,
) -> tuple[ToolPin, ...]:
    """Return managed pins for ``tool_id`` from the lock or reviewed fallbacks."""

    if tool_id not in ADVISOR_INSTALL_TOOLS:
        raise AdvisorInstallerError(f"advisors plugin does not own tool_id={tool_id!r}")

    document = lock if lock is not None else load_lock_document(repo_root)
    pins: list[ToolPin] = []
    if document is not None:
        tools = document.get("tools") or []
        if not isinstance(tools, list):
            raise AdvisorInstallerError("deployment lock tools must be a list")
        for entry in tools:
            if not isinstance(entry, Mapping):
                continue
            if str(entry.get("tool_id") or "") != tool_id:
                continue
            license_text = str(entry.get("license") or "")
            source_text = str(entry.get("source") or "")
            identity_kind = str(entry.get("identity_kind") or "")
            for raw in entry.get("pins") or []:
                if not isinstance(raw, Mapping):
                    continue
                pins.append(
                    ToolPin(
                        tool_id=str(raw.get("tool_id") or tool_id),
                        version=str(raw.get("version") or ""),
                        platform=str(raw.get("platform") or "any"),
                        artifact_url=str(raw.get("artifact_url") or ""),
                        sha256=str(raw.get("sha256") or "").lower(),
                        identity_kind=str(
                            raw.get("identity_kind") or identity_kind or "python_package"
                        ),
                        license=str(raw.get("license") or license_text),
                        source=str(raw.get("source") or source_text),
                        package_name=str(
                            raw.get("package_name")
                            or (SYMBOLICAI_PACKAGE if tool_id == TOOL_SYMBOLICAI else "")
                        ),
                        is_checksummed=bool(raw.get("is_checksummed")),
                        requires_checksum_at_install=bool(
                            (entry.get("deployment_contract") or {}).get(
                                "requires_checksum_at_install"
                            )
                            if isinstance(entry.get("deployment_contract"), Mapping)
                            else False
                        ),
                        release_tag=str(
                            raw.get("release_tag")
                            or (
                                (entry.get("deployment_contract") or {}).get(
                                    "release_tag"
                                )
                                if isinstance(
                                    entry.get("deployment_contract"), Mapping
                                )
                                else ""
                            )
                            or ""
                        ),
                        artifact_size_bytes=int(
                            raw.get("artifact_size_bytes") or 0
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
                    artifact_url=str(raw.get("artifact_url") or ""),
                    sha256=str(raw.get("sha256") or "").lower(),
                    identity_kind=str(raw.get("identity_kind") or "python_package"),
                    license=str(raw.get("license") or ""),
                    source=str(raw.get("source") or ""),
                    package_name=str(raw.get("package_name") or ""),
                    is_checksummed=bool(raw.get("is_checksummed")),
                    requires_checksum_at_install=bool(
                        raw.get("requires_checksum_at_install")
                    ),
                    release_tag=str(raw.get("release_tag") or ""),
                    artifact_size_bytes=int(raw.get("artifact_size_bytes") or 0),
                )
            )
    if not pins:
        raise AdvisorInstallerError(f"no managed pins registered for {tool_id!r}")
    return tuple(pins)


def locked_version_for(tool_id: str, *, lock: Mapping[str, Any] | None = None) -> str:
    """Return the exact managed pin version required under strict install."""

    if lock is not None:
        versions = lock.get("managed_pin_versions") or {}
        if isinstance(versions, Mapping) and tool_id in versions:
            return str(versions[tool_id])
        versions = lock.get("versions") or {}
        if isinstance(versions, Mapping) and tool_id in versions:
            return str(versions[tool_id])
    if tool_id in LOCKED_VERSIONS:
        return LOCKED_VERSIONS[tool_id]
    raise AdvisorInstallerError(f"no locked version for tool_id={tool_id!r}")


def select_strict_pin(
    tool_id: str,
    *,
    platform_key: str | None = None,
    repo_root: Path | str | None = None,
    lock: Mapping[str, Any] | None = None,
    allow_source_fallback: bool = True,
) -> ToolPin:
    """Select the exact locked pin for ``tool_id`` on the host platform.

    Under the FVT-G160 contract this is the only identity that strict
    installation may materialize.  Version mismatches fail closed.
    """

    if tool_id not in ADVISOR_INSTALL_TOOLS:
        raise AdvisorInstallerError(f"advisors plugin does not own tool_id={tool_id!r}")

    platform_name = platform_key or detect_platform_key()
    expected = locked_version_for(tool_id, lock=lock)
    candidates = pins_for_tool(tool_id, repo_root=repo_root, lock=lock)

    # SymbolicAI is a Python package range pin (platform=any).
    if tool_id == TOOL_SYMBOLICAI:
        exact = [
            pin
            for pin in candidates
            if pin.version == expected and pin.platform in {"any", platform_name, "*"}
        ]
        if exact:
            return exact[0]
        raise AdvisorInstallerError(
            f"strict install for {tool_id!r} requires package identity "
            f"{expected!r}; available pins: "
            f"{sorted({f'{p.platform}@{p.version}' for p in candidates})}"
        )

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
    raise AdvisorInstallerError(
        f"strict install for {tool_id!r} requires version {expected!r} on "
        f"platform {platform_name!r}; available pins: {available}"
    )


def python_version_satisfies_range(observed: str, version_range: str) -> bool:
    """Return True when ``observed`` satisfies a simple ``>=X,<Y`` range pin."""

    match = _SYMBOLICAI_RANGE_RE.match((version_range or "").replace(" ", ""))
    if match is None:
        # Exact string or substring match for non-range pins.
        return observed == version_range or version_range in observed
    lo = numeric_version(match.group(1))
    hi = numeric_version(match.group(2))
    current = numeric_version(observed)
    if not current or not lo or not hi:
        return False
    return lo <= current < hi


# ---------------------------------------------------------------------------
# Version / runtime probes
# ---------------------------------------------------------------------------


def probe_symbolicai_package(
    *,
    package_name: str = SYMBOLICAI_PACKAGE,
    expected_range: str = SYMBOLICAI_VERSION,
) -> dict[str, Any]:
    """Probe the installed SymbolicAI package without installing anything."""

    result: dict[str, Any] = {
        "tool_id": TOOL_SYMBOLICAI,
        "package_name": package_name,
        "present": False,
        "version_string": None,
        "version_match": False,
        "locked_version": expected_range,
        "identity_kind": "python_package",
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "probe_error": None,
        "network_used": False,
        "install_attempted": False,
    }
    try:
        from importlib import metadata as importlib_metadata
    except ImportError:  # pragma: no cover
        importlib_metadata = None  # type: ignore[assignment]

    version: str | None = None
    if importlib_metadata is not None:
        try:
            version = importlib_metadata.version(package_name)
        except Exception:
            version = None
    if version is None:
        # Alternate distribution names occasionally used by SymbolicAI.
        for alt in ("symai", "SymbolicAI"):
            if importlib_metadata is None:
                break
            try:
                version = importlib_metadata.version(alt)
                break
            except Exception:
                continue
    if version is None:
        # Spec presence without metadata is not a version match.
        if importlib.util.find_spec("symai") is not None:
            result["present"] = True
            result["probe_error"] = "version_metadata_unavailable"
            return result
        result["probe_error"] = "package_not_installed"
        return result

    result["present"] = True
    result["version_string"] = version
    result["version_match"] = python_version_satisfies_range(version, expected_range)
    if not result["version_match"]:
        result["probe_error"] = "locked_version_mismatch"
    return result


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


def read_ergoai_version_banner(
    executable: str,
    *,
    timeout: float = 15.0,
) -> str | None:
    """Read an ErgoAI banner from a managed launcher or the vendor runner.

    The upstream ``runergo`` script forwards ``--version`` to XSB and therefore
    prints the XSB 5.0 banner rather than the ErgoAI 3.0 identity.  Fall back to
    a bounded no-query session and halt it through stdin; this observes the
    actual ErgoAI Reasoner banner without mutating the installation.
    """

    banner = read_version_banner(executable, timeout=timeout)
    if banner and "ergoai" in banner.casefold():
        return banner
    try:
        completed = subprocess.run(
            [executable],
            input="\\halt.\n",
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return banner
    observed = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    ).strip()
    if completed.returncode == 0 and "ergoai" in observed.casefold():
        return observed
    return banner


def _validate_ergoai_managed_provenance(
    *,
    install_root: Path,
    expected_version: str,
    expected_platform: str,
) -> dict[str, Any]:
    manifest_path = _ergoai_identity_path(install_root, expected_version)
    manifest = _load_identity_manifest(manifest_path)
    result: dict[str, Any] = {
        "identity_manifest_path": str(manifest_path),
        "identity_manifest_present": manifest is not None,
        "managed_vendor_provenance_verified": False,
        "is_hermetic_advisor_shim": False,
        "manifest": manifest,
        "reason_codes": [],
    }
    if manifest is None:
        result["reason_codes"].append("managed_identity_manifest_missing")
        return result
    result["is_hermetic_advisor_shim"] = bool(
        manifest.get("is_hermetic_advisor_shim")
    )
    if result["is_hermetic_advisor_shim"]:
        result["reason_codes"].append("hermetic_advisor_shim_is_not_vendor")
        return result

    scalar_checks = {
        "tool_id": manifest.get("tool_id") == TOOL_ERGOAI,
        "version": str(manifest.get("version") or "") == expected_version,
        "platform": str(manifest.get("selected_platform") or "")
        == expected_platform,
        "release_tag": str(manifest.get("release_tag") or "")
        == ERGOAI_RELEASE_TAG,
        "release_sha256": str(
            manifest.get("release_artifact_sha256") or ""
        ).lower()
        == ERGOAI_RELEASE_SHA256,
        "release_size": int(manifest.get("release_artifact_size_bytes") or 0)
        == ERGOAI_RELEASE_SIZE_BYTES,
        "checksum_verified": manifest.get("checksum_verified") is True,
        "live_vendor": manifest.get("is_live_vendor") is True,
        "proof_authority_false": manifest.get("grants_proof_authority") is False,
    }
    for name, passed in scalar_checks.items():
        if not passed:
            result["reason_codes"].append(f"manifest_{name}_mismatch")

    path_checks: dict[str, bool] = {}
    for label, path_key, digest_key in (
        ("release_artifact", "release_artifact_path", "release_artifact_sha256"),
        ("vendor_executable", "vendor_executable", "vendor_executable_sha256"),
        ("xsb_executable", "xsb_executable", "xsb_executable_sha256"),
    ):
        raw_path = str(manifest.get(path_key) or "")
        expected_digest = str(manifest.get(digest_key) or "").lower()
        path = Path(raw_path) if raw_path else None
        inside_managed_root = False
        if path is not None:
            try:
                path.resolve().relative_to(install_root.resolve())
                inside_managed_root = True
            except (OSError, ValueError):
                inside_managed_root = False
        valid = bool(
            path
            and inside_managed_root
            and path.is_file()
            and _HEX64.fullmatch(expected_digest)
            and content_sha256(path) == expected_digest
        )
        path_checks[label] = valid
        if not valid:
            result["reason_codes"].append(f"{label}_digest_mismatch")

    result["scalar_checks"] = scalar_checks
    result["path_checks"] = path_checks
    result["managed_vendor_provenance_verified"] = bool(
        all(scalar_checks.values()) and all(path_checks.values())
    )
    return result


def probe_ergoai_identity(
    *,
    expected_version: str = ERGOAI_VERSION,
    executable: str | None = None,
    install_root: str | Path | None = None,
    require_managed_vendor: bool = False,
    platform_key: str | None = None,
) -> dict[str, Any]:
    """Probe ErgoAI without installing or opening the network."""

    result: dict[str, Any] = {
        "tool_id": TOOL_ERGOAI,
        "path_present": False,
        "executable_path": None,
        "version_string": None,
        "version_match": False,
        "locked_version": expected_version,
        "identity_kind": "immutable_release_tag",
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "probe_error": None,
        "network_used": False,
        "install_attempted": False,
        "managed_vendor_provenance_verified": False,
        "is_hermetic_advisor_shim": False,
    }
    root = expand_user_local_root(install_root)
    expected_platform = platform_key or detect_platform_key()
    binary = executable
    if binary is None:
        # Prefer managed install root, then PATH.
        managed_candidates = [
            root / "bin" / name for name in ERGOAI_EXECUTABLES
        ] + [
            root / "advisors" / "ergoai" / expected_version / "bin" / name
            for name in ERGOAI_EXECUTABLES
        ]
        for candidate in managed_candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                binary = str(candidate)
                break
        if binary is None:
            for name in ERGOAI_EXECUTABLES:
                found = which_executable(name)
                if found:
                    binary = found
                    break
    if binary is None:
        result["probe_error"] = "executable_not_on_path"
        return result

    result["path_present"] = True
    result["executable_path"] = binary
    banner = read_ergoai_version_banner(binary)
    if not banner:
        result["probe_error"] = "empty_version_banner"
        return result
    result["version_string"] = banner
    result["version_match"] = bool(
        expected_version in banner
        or numeric_version(banner) == numeric_version(expected_version)
    )
    if not result["version_match"]:
        result["probe_error"] = "locked_version_mismatch"
        return result

    provenance = _validate_ergoai_managed_provenance(
        install_root=root,
        expected_version=expected_version,
        expected_platform=expected_platform,
    )
    result.update(provenance)
    if require_managed_vendor and not result[
        "managed_vendor_provenance_verified"
    ]:
        result["probe_error"] = "managed_vendor_provenance_unverified"
    return result


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
    """Fail-closed gate shared by ensure_symbolicai / ensure_ergoai."""

    if tool_id not in ADVISOR_INSTALL_TOOLS:
        raise AdvisorInstallerError(
            f"advisors plugin does not own tool_id={tool_id!r}"
        )
    try:
        authorize_installer_entry_install(
            tool_id,
            yes=yes,
            explicit_call=explicit_call,
            import_context=import_context,
            capability_discovery=capability_discovery,
            checksum_verified=checksum_verified,
            platform=platform_key if tool_id == TOOL_ERGOAI else None,
            system_package_mutation=system_package_mutation,
            test_mode=test_mode,
        )
    except InstallerRegistryError as exc:
        raise AdvisorInstallerError(str(exc)) from exc
    entry = get_installer_entry(tool_id)
    if entry.family is not InstallerPluginFamily.ADVISORS:
        raise AdvisorInstallerError(
            f"tool {tool_id!r} is not bound to the advisors installer plugin"
        )
    if strict:
        select_strict_pin(tool_id, platform_key=platform_key)


# ---------------------------------------------------------------------------
# Hermetic identity markers (offline / test installs)
# ---------------------------------------------------------------------------


def _write_identity_manifest(path: Path, identity: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(identity), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_executable(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


_ERGOAI_SHIM_TEMPLATE: Final = '''#!/usr/bin/env python3
"""Pin-bound hermetic ErgoAI advisor identity shim ({version}).

Generated by FormalVerificationInstallerPlugin@1 advisors family.
Speaks only --version / version probes. Never holds theorem authority.
"""
from __future__ import annotations
import sys

VERSION = {version!r}
TOOL_ID = "ergoai"


def main(argv: list[str]) -> int:
    if any(arg in {{"--version", "-v", "version"}} for arg in argv[1:]) or len(argv) == 1:
        sys.stdout.write(f"ErgoAI {{VERSION}} (hermetic-advisor-shim)\\n")
        return 0
    sys.stderr.write(
        "ergoai advisor shim: only --version is supported offline; "
        "proposals remain unverified_candidate_only\\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''


def materialize_hermetic_ergoai(
    *,
    install_root: Path,
    version: str = ERGOAI_VERSION,
    pin: ToolPin | None = None,
) -> dict[str, Any]:
    """Materialize a pin-bound offline ErgoAI identity under user-local root."""

    root = install_root / "advisors" / TOOL_ERGOAI / version
    bin_dir = root / "bin"
    executable = bin_dir / "ergoai"
    identity_path = root / "identity.json"
    source = _ERGOAI_SHIM_TEMPLATE.format(version=version)
    digest = _write_executable(executable, source)
    # Convenience launchers matching lock executable_candidates.
    for alias in ("runErgo.sh", "runergo"):
        launcher = bin_dir / alias
        launcher.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f'exec {_shell_quote(str(executable))} "$@"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)
    # Also expose under $root/bin for PATH discovery.
    user_bin = install_root / "bin"
    user_bin.mkdir(parents=True, exist_ok=True)
    for name in ("ergoai", "runErgo.sh", "runergo"):
        target = user_bin / name
        target.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f'exec {_shell_quote(str(bin_dir / ("ergoai" if name == "ergoai" else name)))} "$@"\n',
            encoding="utf-8",
        )
        target.chmod(0o755)

    identity = {
        "tool_id": TOOL_ERGOAI,
        "version": version,
        "executable": str(executable),
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "identity_kind": pin.identity_kind if pin else "immutable_release_tag",
        "license": pin.license if pin else "Apache-2.0",
        "source": pin.source if pin else "https://github.com/ErgoAI/ErgoEngine",
        "is_hermetic_advisor_shim": True,
        "artifact_sha256": digest,
        "grants_theorem_authority": False,
        "grants_proof_authority": False,
    }
    _write_identity_manifest(identity_path, identity)
    return identity


def materialize_hermetic_symbolicai_marker(
    *,
    install_root: Path,
    version_range: str = SYMBOLICAI_VERSION,
    pin: ToolPin | None = None,
) -> dict[str, Any]:
    """Write a reviewed offline identity marker for SymbolicAI package pin.

    Does not pip-install the package.  Certification and dry-run paths use the
    marker to prove the locked range was selected.  Live package presence is
    still probed separately via importlib.metadata.
    """

    root = install_root / "advisors" / TOOL_SYMBOLICAI
    root.mkdir(parents=True, exist_ok=True)
    identity_path = root / "identity.json"
    identity = {
        "tool_id": TOOL_SYMBOLICAI,
        "version": version_range,
        "package_name": SYMBOLICAI_PACKAGE,
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "identity_kind": pin.identity_kind if pin else "python_package",
        "license": pin.license if pin else "BSD-3-Clause",
        "source": pin.source if pin else "https://github.com/ExtensityAI/symbolicai",
        "is_hermetic_package_marker": True,
        "grants_theorem_authority": False,
        "grants_proof_authority": False,
    }
    _write_identity_manifest(identity_path, identity)
    return identity


# ---------------------------------------------------------------------------
# ensure_* entry points
# ---------------------------------------------------------------------------


def ensure_symbolicai(
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
    hermetic_marker: bool = False,
    import_context: bool = False,
    capability_discovery: bool = False,
    lock: Mapping[str, Any] | None = None,
) -> InstallReceipt:
    """Ensure the locked SymbolicAI package identity is selected.

    Strict mode selects the reviewed PyPI range pin
    ``>=1.14.0,<2.0.0``.  Actual pip installation is only attempted when
    ``yes=True`` and not ``dry_run`` / ``hermetic_marker``.  Hermetic marker
    mode records the locked identity offline without network access.
    """

    del platform_key  # package pin is platform-agnostic
    receipt = InstallReceipt(
        tool_id=TOOL_SYMBOLICAI,
        requested_version=SYMBOLICAI_VERSION,
        strict=strict,
        yes=yes,
        package_name=SYMBOLICAI_PACKAGE,
    )
    root = expand_user_local_root(install_root)

    try:
        pin = select_strict_pin(
            TOOL_SYMBOLICAI,
            platform_key="any",
            repo_root=repo_root,
            lock=lock,
        )
    except AdvisorInstallerError as exc:
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
        "tool_id": TOOL_SYMBOLICAI,
        "locked_version": SYMBOLICAI_VERSION,
        "selected_version": pin.version,
        "platform": pin.platform,
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "identity_kind": pin.identity_kind,
        "package_name": SYMBOLICAI_PACKAGE,
        "grants_theorem_authority": False,
        "grants_proof_authority": False,
        "proposals_only": True,
    }

    # Fail closed before any availability short-circuit when called from import
    # or capability discovery — presence never legitimizes install side effects.
    if import_context or capability_discovery:
        try:
            authorize_plugin_install(
                TOOL_SYMBOLICAI,
                yes=yes,
                strict=strict,
                import_context=import_context,
                capability_discovery=capability_discovery,
                test_mode=test_mode,
            )
        except AdvisorInstallerError as exc:
            receipt.status = "refused"
            receipt.phase = "authorization"
            receipt.reason_codes.append(
                "forbidden_on_import"
                if import_context
                else "forbidden_on_capability_discovery"
            )
            receipt.messages.append(str(exc))
            return receipt

    probe = probe_symbolicai_package(
        package_name=SYMBOLICAI_PACKAGE,
        expected_range=pin.version,
    )
    if probe.get("present") and probe.get("version_match") and not force:
        receipt.already_present = True
        receipt.installed = True
        receipt.status = "available"
        receipt.phase = "available"
        receipt.messages.append(
            f"SymbolicAI {probe.get('version_string')} already satisfies {pin.version}"
        )
        receipt.bindings["observed_version"] = probe.get("version_string")
        return receipt

    if dry_run:
        receipt.status = "blocked" if not yes else "available"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        receipt.messages.append(
            f"dry-run selected SymbolicAI package identity {pin.version}"
        )
        return receipt

    if not yes:
        receipt.status = "refused"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "SymbolicAI missing or mismatched; re-run with yes=True to install "
            "user-locally or record hermetic identity."
        )
        return receipt

    try:
        authorize_plugin_install(
            TOOL_SYMBOLICAI,
            yes=yes,
            strict=strict,
            import_context=import_context,
            capability_discovery=capability_discovery,
            checksum_verified=True,  # package range pin; no archive checksum
            test_mode=test_mode,
        )
    except AdvisorInstallerError as exc:
        receipt.status = "failed"
        receipt.phase = "authorization"
        receipt.reason_codes.append("authorization_failed")
        receipt.messages.append(str(exc))
        if strict and not hermetic_marker:
            raise
        if not hermetic_marker:
            return receipt

    # Offline / certification path: record locked identity without pip/network.
    if hermetic_marker or test_mode or os.environ.get(
        "FORMAL_VERIFICATION_FORBID_NETWORK"
    ) == "1" or os.environ.get("FORMAL_VERIFICATION_CERTIFY_OFFLINE") == "1":
        identity = materialize_hermetic_symbolicai_marker(
            install_root=root,
            version_range=pin.version,
            pin=pin,
        )
        receipt.installed = True
        receipt.status = "installed"
        receipt.phase = "hermetic_marker"
        receipt.install_attempted = True
        receipt.executable_path = str(
            root / "advisors" / TOOL_SYMBOLICAI / "identity.json"
        )
        receipt.bindings["identity"] = identity
        receipt.messages.append(
            f"Recorded hermetic SymbolicAI identity marker for {pin.version}"
        )
        _announce(
            f"Hermetic SymbolicAI marker at {receipt.executable_path}",
            on_progress,
            phase="installed",
        )
        return receipt

    # Live pip install (explicit opt-in only; never during certification).
    receipt.install_attempted = True
    _announce(
        f"Installing {SYMBOLICAI_PACKAGE}{pin.version} user-locally via pip",
        on_progress,
        phase="installing",
    )
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--user",
                f"{SYMBOLICAI_PACKAGE}{pin.version}",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        receipt.status = "failed"
        receipt.phase = "pip_install"
        receipt.reason_codes.append("pip_install_failed")
        receipt.messages.append(str(exc))
        if strict:
            raise AdvisorInstallerError(f"SymbolicAI pip install failed: {exc}") from exc
        return receipt

    if completed.returncode != 0:
        receipt.status = "failed"
        receipt.phase = "pip_install"
        receipt.reason_codes.append("pip_install_failed")
        receipt.messages.append(
            (completed.stderr or completed.stdout or "pip failed").strip()[:500]
        )
        if strict:
            raise AdvisorInstallerError(
                f"SymbolicAI pip install failed with code {completed.returncode}"
            )
        return receipt

    post = probe_symbolicai_package(expected_range=pin.version)
    if not post.get("version_match"):
        # Still record the marker so operators can see the intended pin.
        materialize_hermetic_symbolicai_marker(
            install_root=root, version_range=pin.version, pin=pin
        )
        receipt.status = "failed"
        receipt.phase = "validation"
        receipt.reason_codes.append("locked_version_mismatch")
        receipt.messages.append(
            f"post-install version {post.get('version_string')!r} does not "
            f"satisfy {pin.version!r}"
        )
        if strict:
            raise AdvisorInstallerError(receipt.messages[-1])
        return receipt

    receipt.installed = True
    receipt.status = "installed"
    receipt.phase = "installed"
    receipt.bindings["observed_version"] = post.get("version_string")
    receipt.messages.append(
        f"Installed SymbolicAI {post.get('version_string')} satisfying {pin.version}"
    )
    return receipt


def ensure_ergoai(
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
    hermetic_shim: bool = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    lock: Mapping[str, Any] | None = None,
    artifact_path: str | Path | None = None,
    download_timeout: float = 180.0,
    install_timeout: float = 900.0,
) -> InstallReceipt:
    """Ensure the checksum-pinned ErgoAI 3.0 runtime (advisor only).

    ``hermetic_shim=True`` is reserved for offline role-contract tests and only
    materializes an identity shim.  A real lazy execution request passes
    ``hermetic_shim=False``; that path downloads (or consumes
    ``artifact_path``), verifies, builds, probes, and semantically exercises
    the official release before exposing a launcher.  Neither path grants
    theorem or proof authority.
    """

    receipt = InstallReceipt(
        tool_id=TOOL_ERGOAI,
        requested_version=ERGOAI_VERSION,
        strict=strict,
        yes=yes,
    )
    root = expand_user_local_root(install_root)
    platform_name = platform_key or detect_platform_key()

    def fail(phase: str, code: str, message: str) -> InstallReceipt:
        receipt.status = "blocked" if code in {
            "unsupported_platform",
            "offline_policy_blocks_live_install",
            "missing_build_dependency",
        } else "failed"
        receipt.phase = phase
        receipt.reason_codes.append(code)
        receipt.messages.append(message)
        _announce(message, on_progress, phase="failed")
        if strict:
            raise AdvisorInstallerError(message)
        return receipt

    try:
        pin = select_strict_pin(
            TOOL_ERGOAI,
            platform_key=platform_name,
            repo_root=repo_root,
            lock=lock,
            allow_source_fallback=False,
        )
    except AdvisorInstallerError as exc:
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
        "tool_id": TOOL_ERGOAI,
        "locked_version": ERGOAI_VERSION,
        "selected_version": pin.version,
        "platform": pin.platform,
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "identity_kind": pin.identity_kind,
        "grants_theorem_authority": False,
        "grants_proof_authority": False,
        "proposals_only": True,
        "supported_platforms": list(ERGOAI_SUPPORTED_PLATFORMS),
        "release_tag": pin.release_tag or ERGOAI_RELEASE_TAG,
        "release_artifact_sha256": pin.sha256,
        "release_artifact_size_bytes": pin.artifact_size_bytes,
        "license_components": list(ERGOAI_LICENSE_COMPONENTS),
        "required_build_commands": list(ERGOAI_BUILD_COMMANDS),
    }

    if platform_name not in ERGOAI_SUPPORTED_PLATFORMS:
        return fail(
            "platform",
            "unsupported_platform",
            f"ErgoAI live install is not reviewed for {platform_name!r}; "
            f"supported pins are {list(ERGOAI_SUPPORTED_PLATFORMS)!r}",
        )
    if pin.platform != platform_name:
        return fail(
            "platform",
            "platform_pin_mismatch",
            f"ErgoAI pin platform {pin.platform!r} does not match "
            f"host platform {platform_name!r}",
        )

    if import_context or capability_discovery:
        try:
            authorize_plugin_install(
                TOOL_ERGOAI,
                yes=yes,
                strict=strict,
                import_context=import_context,
                capability_discovery=capability_discovery,
                checksum_verified=True if hermetic_shim else None,
                platform_key=platform_name,
                test_mode=test_mode,
            )
        except AdvisorInstallerError as exc:
            receipt.status = "refused"
            receipt.phase = "authorization"
            message = str(exc)
            code = (
                "forbidden_on_import"
                if import_context or "import" in message.lower()
                else "forbidden_on_capability_discovery"
            )
            receipt.reason_codes.append(code)
            receipt.messages.append(message)
            return receipt

    probe = probe_ergoai_identity(
        expected_version=pin.version,
        install_root=root,
        require_managed_vendor=not hermetic_shim,
        platform_key=platform_name,
    )
    managed_identity_acceptable = bool(
        hermetic_shim or probe.get("managed_vendor_provenance_verified")
    )
    if (
        probe.get("path_present")
        and probe.get("version_match")
        and managed_identity_acceptable
        and not force
    ):
        receipt.executable_path = probe.get("executable_path")
        receipt.already_present = True
        receipt.installed = True
        receipt.status = "available"
        receipt.phase = "available"
        receipt.messages.append(
            f"ErgoAI {pin.version} already available at {receipt.executable_path}"
        )
        receipt.bindings["observed_version"] = probe.get("version_string")
        receipt.bindings["managed_provenance"] = {
            key: probe.get(key)
            for key in (
                "identity_manifest_path",
                "managed_vendor_provenance_verified",
                "is_hermetic_advisor_shim",
                "reason_codes",
            )
        }
        receipt.checksum_verified = bool(
            probe.get("managed_vendor_provenance_verified")
            or probe.get("is_hermetic_advisor_shim")
        )
        return receipt

    if dry_run:
        receipt.status = "blocked" if not yes else "available"
        receipt.phase = "dry_run"
        receipt.reason_codes.append("dry_run")
        receipt.messages.append(
            f"dry-run selected ErgoAI {pin.version} for {pin.platform}"
        )
        return receipt

    if not yes:
        receipt.status = "refused"
        receipt.phase = "blocked"
        receipt.reason_codes.append("yes_required")
        receipt.messages.append(
            "ErgoAI missing or mismatched; re-run with yes=True to install "
            "user-locally (or hermetic advisor shim)."
        )
        return receipt

    try:
        authorize_plugin_install(
            TOOL_ERGOAI,
            yes=yes,
            strict=strict,
            import_context=import_context,
            capability_discovery=capability_discovery,
            # Vendor bytes are authorized again after their digest is observed.
            checksum_verified=True if hermetic_shim else None,
            platform_key=platform_name,
            test_mode=test_mode,
        )
    except AdvisorInstallerError as exc:
        receipt.status = "refused" if import_context or capability_discovery else "failed"
        receipt.phase = "authorization"
        code = "authorization_failed"
        message = str(exc)
        if import_context or "import" in message.lower():
            code = "forbidden_on_import"
        elif capability_discovery or "capability" in message.lower():
            code = "forbidden_on_capability_discovery"
        receipt.reason_codes.append(code)
        receipt.messages.append(message)
        return receipt

    # Hermetic shims are explicit role-contract fixtures.  Never silently
    # substitute one for a requested vendor execution path.
    if hermetic_shim:
        receipt.install_attempted = True
        identity = materialize_hermetic_ergoai(
            install_root=root,
            version=pin.version,
            pin=pin,
        )
        receipt.executable_path = str(identity["executable"])
        receipt.installed = True
        receipt.status = "installed"
        receipt.phase = "hermetic_shim"
        receipt.checksum_verified = True
        receipt.bindings["identity"] = identity
        receipt.messages.append(
            f"Installed hermetic ErgoAI {pin.version} advisor shim (proposals only)"
        )
        _announce(
            f"Hermetic ErgoAI shim at {receipt.executable_path}",
            on_progress,
            phase="installed",
        )
        return receipt

    certification_forbids_install = bool(
        os.environ.get("FORMAL_VERIFICATION_CERTIFY_OFFLINE") == "1"
        or os.environ.get("FORMAL_VERIFICATION_FORBID_INSTALL") == "1"
    )
    network_forbidden_without_artifact = bool(
        os.environ.get("FORMAL_VERIFICATION_FORBID_NETWORK") == "1"
        and artifact_path is None
        and not os.environ.get("IPFS_DATASETS_PY_ERGOAI_RELEASE_FILE")
    )
    if certification_forbids_install or network_forbidden_without_artifact:
        return fail(
            "offline_policy",
            "offline_policy_blocks_live_install",
            "Offline certification forbids an ErgoAI vendor download/install; "
            "provide a pre-fetched checksummed artifact outside certification "
            "or use the explicit hermetic role fixture.",
        )

    if not pin.sha256 or not pin.is_checksummed:
        return fail(
            "checksum",
            "checksum_required_for_live_install",
            "Live ErgoAI install requires an exact reviewed SHA-256 pin.",
        )
    missing_commands = _ergoai_missing_build_commands()
    if missing_commands:
        return fail(
            "dependencies",
            "missing_build_dependency",
            "ErgoAI build dependencies are missing: " + ", ".join(missing_commands),
        )

    configured_artifact = artifact_path or os.environ.get(
        "IPFS_DATASETS_PY_ERGOAI_RELEASE_FILE"
    )
    release_name = Path(pin.artifact_url).name or "ergoAI_3.0.run"
    release_path = root / "downloads" / release_name
    ok, observed_digest, observed_size = _copy_or_download_ergoai_artifact(
        pin,
        release_path,
        artifact_path=configured_artifact,
        timeout=download_timeout,
        on_progress=on_progress,
    )
    if not ok or observed_digest != pin.sha256:
        return fail(
            "checksum",
            "download_or_checksum_failed",
            "ErgoAI release acquisition or checksum verification failed.",
        )
    receipt.checksum_verified = True
    receipt.bindings["observed_release_artifact_sha256"] = observed_digest
    receipt.bindings["observed_release_artifact_size_bytes"] = observed_size

    # Re-authorize after the bytes, rather than only the metadata, have been
    # verified.  This keeps the registry gate evidence truthful.
    try:
        authorize_plugin_install(
            TOOL_ERGOAI,
            yes=yes,
            strict=strict,
            checksum_verified=True,
            platform_key=platform_name,
            test_mode=test_mode,
        )
    except AdvisorInstallerError as exc:
        return fail("authorization", "authorization_failed", str(exc))

    version_root = _ergoai_version_root(root, pin.version)
    version_root.mkdir(parents=True, exist_ok=True)
    vendor_root = _ergoai_vendor_root(root, pin.version, pin.sha256)
    vendor_binary = _find_vendor_ergoai_binary(vendor_root, pin.version)
    if vendor_binary is None and vendor_root.exists() and any(vendor_root.iterdir()):
        return fail(
            "install",
            "partial_install_requires_manual_cleanup",
            f"ErgoAI vendor directory exists without a configured runtime: {vendor_root}",
        )

    if vendor_binary is None:
        install_home = version_root / "install-home"
        install_home.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment["HOME"] = str(install_home)
        environment["TERM"] = "dumb"
        shell = shutil.which("sh")
        if shell is None:  # guarded by dependency preflight, defensive only
            return fail("dependencies", "missing_build_dependency", "sh is unavailable")
        receipt.install_attempted = True
        _announce(
            f"Building checksummed ErgoAI {pin.version} for {platform_name}",
            on_progress,
            phase="installing",
        )
        try:
            completed = subprocess.run(
                [
                    shell,
                    str(release_path),
                    "--target",
                    str(vendor_root),
                    "--",
                    "noninteractive",
                ],
                cwd=version_root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=install_timeout,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return fail("install", "vendor_install_failed", f"ErgoAI install failed: {exc}")
        receipt.bindings["installer_output_digest_sha256"] = hashlib.sha256(
            f"{completed.stdout}\n{completed.stderr}".encode()
        ).hexdigest()
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[-500:]
            return fail(
                "install",
                "vendor_install_failed",
                f"ErgoAI installer exited {completed.returncode}: {detail}",
            )
        vendor_binary = _find_vendor_ergoai_binary(vendor_root, pin.version)

    if vendor_binary is None:
        return fail(
            "validation",
            "vendor_executable_missing",
            "Checksummed ErgoAI installer did not produce a configured runergo.",
        )
    xsb_binary = _find_vendor_xsb_binary(vendor_binary)
    if xsb_binary is None:
        return fail(
            "validation",
            "xsb_executable_missing",
            "ErgoAI installation did not produce exactly one executable XSB runtime.",
        )
    expected_arch_token = "aarch64" if platform_name == "linux-aarch64" else "x86_64"
    xsb_configuration = xsb_binary.parent.parent.name
    if expected_arch_token not in xsb_configuration:
        return fail(
            "platform",
            "compiled_platform_mismatch",
            f"ErgoAI XSB configuration {xsb_configuration!r} does not match "
            f"the selected platform {platform_name!r}",
        )

    banner = read_ergoai_version_banner(str(vendor_binary), timeout=30.0)
    if not banner or pin.version not in banner or "ergoai" not in banner.casefold():
        return fail(
            "validation",
            "locked_version_mismatch",
            "Installed ErgoAI runtime did not report the locked 3.0 identity.",
        )
    semantics = run_ergoai_semantic_checks(vendor_binary, timeout=30.0)
    if not semantics.get("passed"):
        return fail(
            "semantic_validation",
            "semantic_checks_failed",
            "Installed ErgoAI failed positive/negative/mutation/replay checks.",
        )

    launcher_digests = _write_vendor_ergoai_launchers(
        install_root=root,
        vendor_binary=vendor_binary,
        version=pin.version,
        platform_key=platform_name,
    )
    primary_launcher = root / "bin" / "ergoai"
    identity = {
        "schema_version": "ergoai-managed-vendor-identity/v1",
        "tool_id": TOOL_ERGOAI,
        "version": pin.version,
        "selected_platform": platform_name,
        "release_tag": pin.release_tag or ERGOAI_RELEASE_TAG,
        "release_url": pin.artifact_url,
        "release_artifact_path": str(release_path.resolve()),
        "release_artifact_sha256": content_sha256(release_path),
        "release_artifact_size_bytes": release_path.stat().st_size,
        "vendor_executable": str(vendor_binary),
        "vendor_executable_sha256": content_sha256(vendor_binary),
        "xsb_executable": str(xsb_binary),
        "xsb_executable_sha256": content_sha256(xsb_binary),
        "xsb_configuration": xsb_configuration,
        "launcher": str(primary_launcher.resolve()),
        "launcher_sha256": launcher_digests["ergoai"],
        "launcher_digests": launcher_digests,
        "version_banner_digest_sha256": hashlib.sha256(
            banner.encode("utf-8")
        ).hexdigest(),
        "semantic_checks": semantics,
        "checksum_verified": True,
        "is_live_vendor": True,
        "is_hermetic_advisor_shim": False,
        "role": ADVISOR_ROLE,
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "grants_theorem_authority": False,
        "grants_proof_authority": False,
        "license": pin.license,
        "license_components": list(ERGOAI_LICENSE_COMPONENTS),
        "source": pin.source,
    }
    identity["identity_digest_sha256"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    identity_path = _ergoai_identity_path(root, pin.version)
    _write_identity_manifest(identity_path, identity)

    provenance = _validate_ergoai_managed_provenance(
        install_root=root,
        expected_version=pin.version,
        expected_platform=platform_name,
    )
    if not provenance.get("managed_vendor_provenance_verified"):
        return fail(
            "provenance",
            "managed_vendor_provenance_unverified",
            "ErgoAI identity manifest did not replay against installed artifacts.",
        )

    os.environ["ERGOAI_BINARY"] = str(primary_launcher)
    receipt.executable_path = str(primary_launcher)
    receipt.installed = True
    receipt.status = "installed"
    receipt.phase = "installed"
    receipt.bindings["managed_provenance"] = {
        "identity_manifest_path": str(identity_path),
        "identity_digest_sha256": identity["identity_digest_sha256"],
        "managed_vendor_provenance_verified": True,
        "is_hermetic_advisor_shim": False,
    }
    receipt.bindings["semantic_checks"] = semantics
    receipt.messages.append(
        f"Installed checksummed ErgoAI {pin.version} for {platform_name}; "
        "runtime remains advisor/candidate only"
    )
    _announce(receipt.messages[-1], on_progress, phase="installed")
    return receipt


def ensure_advisors(
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
    hermetic: bool = True,
    lock: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Ensure both SymbolicAI and ErgoAI locked identities (advisor only)."""

    root = expand_user_local_root(install_root)
    symai = ensure_symbolicai(
        yes=yes,
        strict=strict,
        force=force,
        on_progress=on_progress,
        install_root=root,
        platform_key=platform_key,
        repo_root=repo_root,
        dry_run=dry_run,
        test_mode=test_mode,
        hermetic_marker=hermetic,
        lock=lock,
    )
    ergo = ensure_ergoai(
        yes=yes,
        strict=strict,
        force=force,
        on_progress=on_progress,
        install_root=root,
        platform_key=platform_key,
        repo_root=repo_root,
        dry_run=dry_run,
        test_mode=test_mode,
        hermetic_shim=hermetic,
        lock=lock,
    )
    return {
        "interface": PLUGIN_INTERFACE,
        "family": PLUGIN_FAMILY,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "program": PROGRAM,
        "install_root": str(root),
        "ok": symai.ok and ergo.ok,
        "receipts": {
            TOOL_SYMBOLICAI: symai.to_dict(),
            TOOL_ERGOAI: ergo.to_dict(),
        },
        "policy": {
            "never_on_import": True,
            "requires_explicit_yes": True,
            "user_local_only": True,
            "advisors_never_grant_proof_authority": True,
            "strict_selects_locked_identities": True,
        },
    }


# ---------------------------------------------------------------------------
# Plugin manifest
# ---------------------------------------------------------------------------


def plugin_manifest() -> dict[str, Any]:
    """Machine-readable plugin declaration for packaging / certification."""

    registry = default_installer_registry()
    return {
        "interface": PLUGIN_INTERFACE,
        "family": PLUGIN_FAMILY,
        "module": PLUGIN_MODULE,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "program": PROGRAM,
        "locked_versions": dict(LOCKED_VERSIONS),
        "roles": {
            TOOL_SYMBOLICAI: ADVISOR_ROLE,
            TOOL_ERGOAI: ADVISOR_ROLE,
        },
        "authority_ceiling": ADVISOR_AUTHORITY_CEILING,
        "entries": [
            get_installer_entry(tool_id).to_dict()
            for tool_id in ADVISOR_INSTALL_TOOLS
        ],
        "registry_tools": list(registry.list_tool_ids()),
        "policy": {
            "never_on_import": True,
            "never_on_capability_discovery": True,
            "requires_explicit_yes": True,
            "user_local_only": True,
            "strict_selects_locked_versions": True,
            "advisors_are_candidate_generation_only": True,
            "confidence_never_yields_proof": True,
            "availability_is_not_authority": True,
            "does_not_edit_central_certificate": True,
            "does_not_change_model_runtimes": True,
        },
        "ensure_entrypoints": {
            TOOL_SYMBOLICAI: "ensure_symbolicai",
            TOOL_ERGOAI: "ensure_ergoai",
            "stack": "ensure_advisors",
        },
    }


def describe_advisors_installer() -> dict[str, Any]:
    """Operator-facing summary of the advisors installer plugin."""

    return plugin_manifest()


__all__ = [
    "PLUGIN_INTERFACE",
    "PLUGIN_FAMILY",
    "PLUGIN_MODULE",
    "GOAL_ID",
    "TASK_ID",
    "PROGRAM",
    "TOOL_SYMBOLICAI",
    "TOOL_ERGOAI",
    "ADVISOR_INSTALL_TOOLS",
    "SYMBOLICAI_VERSION",
    "ERGOAI_VERSION",
    "ERGOAI_RELEASE_TAG",
    "ERGOAI_RELEASE_URL",
    "ERGOAI_RELEASE_SHA256",
    "ERGOAI_RELEASE_SIZE_BYTES",
    "ERGOAI_SUPPORTED_PLATFORMS",
    "ERGOAI_BUILD_COMMANDS",
    "ERGOAI_LICENSE_COMPONENTS",
    "LOCKED_VERSIONS",
    "ADVISOR_ROLE",
    "ADVISOR_AUTHORITY_CEILING",
    "IMPORT_INSTALLS_FORBIDDEN",
    "AdvisorInstallerError",
    "ToolPin",
    "InstallReceipt",
    "expand_user_local_root",
    "detect_platform_key",
    "which_executable",
    "resolve_lock_path",
    "load_lock_document",
    "pins_for_tool",
    "locked_version_for",
    "select_strict_pin",
    "python_version_satisfies_range",
    "probe_symbolicai_package",
    "probe_ergoai_identity",
    "read_ergoai_version_banner",
    "run_ergoai_semantic_checks",
    "authorize_plugin_install",
    "materialize_hermetic_ergoai",
    "materialize_hermetic_symbolicai_marker",
    "ensure_symbolicai",
    "ensure_ergoai",
    "ensure_advisors",
    "plugin_manifest",
    "describe_advisors_installer",
]
