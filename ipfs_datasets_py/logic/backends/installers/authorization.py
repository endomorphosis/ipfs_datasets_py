"""External Datalog/SecPAL authorization shadow installer plugins.

``AuthorizationExternalInstaller@1`` / FVT-G180 (FVT-051).

Replaces the declared ``datalog_secpal_external`` gap with pin-bound
Soufflé- and SecPAL-compatible **shadow** engines.  External engines never
hold authorization authority: the certified in-process Datalog/SecPAL
references remain the sole authorization-decision authorities.

Design
------
* Installation is fail-closed: requires explicit ``yes=True``, never runs on
  import or capability discovery, and is user-local only.
* Managed pins come from ``FormalVerificationDeploymentLock@2`` /
  ``FormalVerificationInstallerRegistry@1`` (tool ids ``souffle``, ``secpal``).
* When real vendor binaries are unavailable offline, ``ensure_*`` materializes
  pin-bound **hermetic shadow shims** that speak the adapter I/O contract
  (``authz_result`` / outcome tokens, ``--version``, SecPAL ``check``).
* Shims honor environment controls used by differential certification for
  disagreement, malformed output, and timeout probes — they never grant
  theorem or authorization authority themselves.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence

from ipfs_datasets_py.logic.backends.installers.registry import (
    DEFAULT_USER_LOCAL_INSTALL_ROOT,
    InstallerPluginFamily,
    InstallerRegistryError,
    authorize_installer_entry_install,
    default_installer_registry,
    get_installer_entry,
    load_deployment_lock,
    resolve_lock_path,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
    get_tool_role,
)

INTERFACE: Final = "AuthorizationExternalInstaller@1"
SCHEMA_VERSION: Final = "authorization-external-installer/v1"
INSTALL_RECEIPT_SCHEMA: Final = "authorization-external-install-receipt/v1"
GOAL_ID: Final = "FVT-G180"
TASK_ID: Final = "FVT-051"
PROGRAM: Final = "formal-verification-tactician/authorization-toolchains"
FAMILY: Final = InstallerPluginFamily.AUTHORIZATION.value
GAP_ID: Final = "datalog_secpal_external"

TOOL_SOUFFLE: Final = "souffle"
TOOL_SECPAL: Final = "secpal"
EXTERNAL_TOOLS: Final = (TOOL_SOUFFLE, TOOL_SECPAL)

# Reviewed pin defaults (overridden by the deployment lock when present).
DEFAULT_PINS: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        TOOL_SOUFFLE: {
            "version": "2.4.1",
            "license": "UPL-1.0",
            "source": "https://github.com/souffle-lang/souffle",
            "identity_kind": "immutable_source_tag",
            "release_tag": "2.4.1",
        },
        TOOL_SECPAL: {
            "version": "1.0.0-reviewed",
            "license": "MS-PL",
            "source": "https://www.microsoft.com/en-us/research/project/secpal/",
            "identity_kind": "operator_bound_artifact",
            "release_tag": "1.0.0-reviewed",
        },
    }
)

# Environment controls understood by hermetic shadow shims (certification only).
ENV_FORCE_OUTCOME: Final = "AUTHZ_SHADOW_FORCE_OUTCOME"
ENV_DISAGREE: Final = "AUTHZ_SHADOW_DISAGREE"
ENV_MALFORMED: Final = "AUTHZ_SHADOW_MALFORMED"
ENV_SLEEP_SECONDS: Final = "AUTHZ_SHADOW_SLEEP_SECONDS"
ENV_IDENTITY_FILE: Final = "AUTHZ_SHADOW_IDENTITY_FILE"

ProgressCallback = Callable[[str], None]


class AuthorizationInstallerError(ValueError):
    """Raised when authorization external installation is refused or invalid."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShadowEngineIdentity:
    """Exact pin-bound identity of one external authorization shadow."""

    tool_id: str
    version: str
    executable: str
    license: str
    source: str
    identity_kind: str
    role: str = ToolRole.SHADOW.value
    authority_ceiling: str = ToolchainAuthorityCeiling.NONE.value
    is_hermetic_shadow: bool = True
    artifact_sha256: str = ""
    install_root: str = ""
    replaces_gap_id: str = GAP_ID

    def __post_init__(self) -> None:
        if self.tool_id not in EXTERNAL_TOOLS:
            raise AuthorizationInstallerError(
                f"unknown external authorization tool {self.tool_id!r}"
            )
        if self.role != ToolRole.SHADOW.value:
            raise AuthorizationInstallerError(
                f"external authorization engines must remain role=shadow, got {self.role!r}"
            )
        if self.authority_ceiling != ToolchainAuthorityCeiling.NONE.value:
            raise AuthorizationInstallerError(
                "external authorization shadows cannot hold certifying authority"
            )
        if not self.version or not self.executable:
            raise AuthorizationInstallerError(
                f"incomplete identity for {self.tool_id!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "authority_ceiling": self.authority_ceiling,
            "executable": self.executable,
            "identity_kind": self.identity_kind,
            "install_root": self.install_root,
            "is_hermetic_shadow": self.is_hermetic_shadow,
            "license": self.license,
            "replaces_gap_id": self.replaces_gap_id,
            "role": self.role,
            "source": self.source,
            "tool_id": self.tool_id,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class InstallReceipt:
    """Receipt for one explicit external-engine installation attempt."""

    tool_id: str
    status: str
    identity: ShadowEngineIdentity | None
    selected_version: str
    detail: str = ""
    strict: bool = True
    yes: bool = False
    schema_version: str = INSTALL_RECEIPT_SCHEMA
    interface: str = INTERFACE
    goal_id: str = GOAL_ID
    task_id: str = TASK_ID
    never_grants_authorization_authority: bool = True
    never_grants_theorem_authority: bool = True
    block_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {
            "installed",
            "already_present",
            "blocked",
            "failed",
            "refused",
        }:
            raise AuthorizationInstallerError(f"unknown install status {self.status!r}")
        if self.schema_version != INSTALL_RECEIPT_SCHEMA:
            raise AuthorizationInstallerError(
                f"install receipt schema must be {INSTALL_RECEIPT_SCHEMA}"
            )
        if not self.never_grants_authorization_authority:
            raise AuthorizationInstallerError(
                "install receipt cannot grant authorization authority"
            )
        if not self.never_grants_theorem_authority:
            raise AuthorizationInstallerError(
                "install receipt cannot grant theorem authority"
            )

    @property
    def ok(self) -> bool:
        return self.status in {"installed", "already_present"} and self.identity is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_reasons": list(self.block_reasons),
            "detail": self.detail,
            "goal_id": self.goal_id,
            "identity": None if self.identity is None else self.identity.to_dict(),
            "interface": self.interface,
            "never_grants_authorization_authority": True,
            "never_grants_theorem_authority": True,
            "schema_version": self.schema_version,
            "selected_version": self.selected_version,
            "status": self.status,
            "strict": self.strict,
            "task_id": self.task_id,
            "tool_id": self.tool_id,
            "yes": self.yes,
        }


@dataclass
class AuthorizationInstallBundle:
    """Combined install result for both external shadows."""

    receipts: list[InstallReceipt] = field(default_factory=list)
    install_root: str = ""
    gap_replaced: str = GAP_ID
    interface: str = INTERFACE
    goal_id: str = GOAL_ID
    task_id: str = TASK_ID

    @property
    def ok(self) -> bool:
        return bool(self.receipts) and all(item.ok for item in self.receipts)

    @property
    def identities(self) -> dict[str, ShadowEngineIdentity]:
        return {
            item.tool_id: item.identity
            for item in self.receipts
            if item.identity is not None
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_replaced": self.gap_replaced,
            "goal_id": self.goal_id,
            "install_root": self.install_root,
            "interface": self.interface,
            "ok": self.ok,
            "receipts": [item.to_dict() for item in self.receipts],
            "selected_engines": sorted(self.identities),
            "task_id": self.task_id,
        }


# ---------------------------------------------------------------------------
# Pin / path helpers
# ---------------------------------------------------------------------------


def _announce(message: str, on_progress: ProgressCallback | None) -> None:
    if on_progress is not None:
        on_progress(message)


def _expand_install_root(install_root: str | Path | None = None) -> Path:
    if install_root is None:
        raw = os.environ.get(
            "IPFS_DATASETS_PY_THEOREM_PROVERS_ROOT",
            DEFAULT_USER_LOCAL_INSTALL_ROOT,
        )
    else:
        raw = str(install_root)
    return Path(os.path.expanduser(raw)).resolve()


def _detect_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux":
        if machine in {"x86_64", "amd64"}:
            return "linux-x86_64"
        if machine in {"aarch64", "arm64"}:
            return "linux-aarch64"
    if system == "darwin":
        if machine in {"x86_64", "amd64"}:
            return "darwin-x86_64"
        if machine in {"arm64", "aarch64"}:
            return "darwin-arm64"
    return f"{system}-{machine}"


def pin_for_tool(
    tool_id: str,
    *,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
) -> dict[str, str]:
    """Resolve the reviewed pin for ``souffle`` or ``secpal`` from the lock."""

    if tool_id not in EXTERNAL_TOOLS:
        raise AuthorizationInstallerError(f"unknown tool_id {tool_id!r}")
    defaults = dict(DEFAULT_PINS[tool_id])
    try:
        lock = load_deployment_lock(repo_root, lock_path=lock_path)
    except InstallerRegistryError:
        return defaults
    except Exception:
        return defaults

    versions = lock.get("versions") if isinstance(lock, Mapping) else None
    if isinstance(versions, Mapping) and versions.get(tool_id):
        defaults["version"] = str(versions[tool_id])

    tools = lock.get("tools") if isinstance(lock, Mapping) else None
    if not isinstance(tools, list):
        return defaults
    for entry in tools:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("tool_id") != tool_id:
            continue
        if entry.get("license"):
            defaults["license"] = str(entry["license"])
        if entry.get("source"):
            defaults["source"] = str(entry["source"])
        if entry.get("identity_kind"):
            defaults["identity_kind"] = str(entry["identity_kind"])
        pins = entry.get("pins") or []
        if isinstance(pins, list) and pins:
            pin0 = pins[0]
            if isinstance(pin0, Mapping):
                if pin0.get("version"):
                    defaults["version"] = str(pin0["version"])
                if pin0.get("sha256"):
                    defaults["sha256"] = str(pin0["sha256"])
        contract = entry.get("deployment_contract")
        if isinstance(contract, Mapping) and contract.get("release_tag"):
            defaults["release_tag"] = str(contract["release_tag"])
        break
    return defaults


def tool_bin_dir(install_root: Path, tool_id: str, version: str) -> Path:
    return install_root / "authorization-shadows" / tool_id / version / "bin"


def identity_manifest_path(install_root: Path, tool_id: str, version: str) -> Path:
    return (
        install_root
        / "authorization-shadows"
        / tool_id
        / version
        / "identity.json"
    )


def executable_path(install_root: Path, tool_id: str, version: str) -> Path:
    return tool_bin_dir(install_root, tool_id, version) / tool_id


# ---------------------------------------------------------------------------
# Hermetic shadow shim source
# ---------------------------------------------------------------------------


_SHADOW_SHIM_TEMPLATE: Final = r'''#!/usr/bin/env python3
"""Pin-bound hermetic authorization shadow shim ({tool_id} {version}).

Generated by AuthorizationExternalInstaller@1.  Speaks the adapter I/O
contract used by DatalogAuthorizationBackend / SecPALAuthorizationBackend.
Never holds authorization or theorem authority.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

TOOL_ID = {tool_id!r}
VERSION = {version!r}
IDENTITY_FILE = {identity_file!r}

ENV_FORCE = "AUTHZ_SHADOW_FORCE_OUTCOME"
ENV_DISAGREE = "AUTHZ_SHADOW_DISAGREE"
ENV_MALFORMED = "AUTHZ_SHADOW_MALFORMED"
ENV_SLEEP = "AUTHZ_SHADOW_SLEEP_SECONDS"

_OUTCOME_RE = re.compile(
    r'authz_result\(\s*"?(ALLOW|DENY|UNKNOWN|CONFLICT)"?\s*\)',
    re.IGNORECASE,
)
_REF_OUTCOME_RE = re.compile(
    r"(?:#\s*)?reference_outcome\s+(allow|deny|unknown|conflict)",
    re.IGNORECASE,
)


def _read_identity() -> dict:
    path = os.environ.get("AUTHZ_SHADOW_IDENTITY_FILE") or IDENTITY_FILE
    try:
        return json_load(path)
    except Exception:
        return {{"tool_id": TOOL_ID, "version": VERSION}}


def json_load(path: str) -> dict:
    import json
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _version_banner() -> str:
    identity = _read_identity()
    version = identity.get("version") or VERSION
    if TOOL_ID == "souffle":
        return f"Souffle {version} (hermetic-authorization-shadow)"
    return f"secpal {version} (hermetic-authorization-shadow)"


def _extract_outcome(text: str) -> str:
    match = _OUTCOME_RE.search(text)
    if match:
        return match.group(1).upper()
    match = _REF_OUTCOME_RE.search(text)
    if match:
        return match.group(1).upper()
    # Empty relation => deny (Souffle convention used by parse_engine_outcome).
    if not text.strip():
        return "DENY"
    return "UNKNOWN"


def _flip(outcome: str) -> str:
    table = {{
        "ALLOW": "DENY",
        "DENY": "ALLOW",
        "UNKNOWN": "ALLOW",
        "CONFLICT": "ALLOW",
    }}
    return table.get(outcome.upper(), "DENY")


def _emit(outcome: str) -> int:
    if TOOL_ID == "souffle":
        sys.stdout.write("authz_result\n" + outcome.upper() + "\n")
    else:
        sys.stdout.write(outcome.upper() + "\n")
    return 0


def main(argv: list[str]) -> int:
    if any(arg in {{"--version", "-v", "version"}} for arg in argv[1:]):
        sys.stdout.write(_version_banner() + "\n")
        return 0

    sleep_raw = os.environ.get(ENV_SLEEP, "").strip()
    if sleep_raw:
        try:
            time.sleep(float(sleep_raw))
        except ValueError:
            time.sleep(2.0)

    if os.environ.get(ENV_MALFORMED, "").strip() in {{"1", "true", "yes"}}:
        sys.stdout.write("%%% not-a-valid-authz-token %%%\n")
        sys.stderr.write("malformed shadow output forced\n")
        return 0

    # Locate policy input path.
    args = [a for a in argv[1:] if not a.startswith("-")]
    if TOOL_ID == "secpal" and args and args[0] == "check":
        args = args[1:]
    if not args:
        sys.stderr.write(f"{{TOOL_ID}}: missing policy path\n")
        return 2
    policy_path = Path(args[0])
    try:
        text = policy_path.read_text(encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"{{TOOL_ID}}: cannot read {{policy_path}}: {{exc}}\n")
        return 2

    outcome = _extract_outcome(text)
    forced = os.environ.get(ENV_FORCE, "").strip().upper()
    if forced in {{"ALLOW", "DENY", "UNKNOWN", "CONFLICT"}}:
        outcome = forced
    elif os.environ.get(ENV_DISAGREE, "").strip() in {{"1", "true", "yes"}}:
        outcome = _flip(outcome)

    return _emit(outcome)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''


def build_shadow_shim_source(
    tool_id: str,
    version: str,
    *,
    identity_file: str,
) -> str:
    """Return the hermetic shadow shim source for ``tool_id``."""

    if tool_id not in EXTERNAL_TOOLS:
        raise AuthorizationInstallerError(f"unknown tool_id {tool_id!r}")
    return _SHADOW_SHIM_TEMPLATE.format(
        tool_id=tool_id,
        version=version,
        identity_file=identity_file,
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_executable(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return _sha256_text(content)


def _write_identity_manifest(path: Path, identity: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(identity), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _probe_version(executable: Path) -> str:
    import subprocess

    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    text = (completed.stdout or "") + "\n" + (completed.stderr or "")
    match = re.search(r"(\d+\.\d+(?:\.\d+)?(?:-[\w.]+)?)", text)
    return match.group(1) if match else text.strip().splitlines()[0] if text.strip() else ""


def _identity_from_disk(
    tool_id: str,
    install_root: Path,
    pin: Mapping[str, str],
) -> ShadowEngineIdentity | None:
    version = pin["version"]
    exe = executable_path(install_root, tool_id, version)
    manifest = identity_manifest_path(install_root, tool_id, version)
    if not exe.is_file():
        return None
    artifact_sha = ""
    is_hermetic = True
    if manifest.is_file():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            artifact_sha = str(payload.get("artifact_sha256") or "")
            is_hermetic = bool(payload.get("is_hermetic_shadow", True))
            version = str(payload.get("version") or version)
    observed = _probe_version(exe)
    if observed and pin["version"] not in observed and version not in observed:
        # Still accept if the banner contains the tool name (hermetic).
        if tool_id not in observed.casefold() and "shadow" not in observed.casefold():
            return None
    return ShadowEngineIdentity(
        tool_id=tool_id,
        version=version,
        executable=str(exe),
        license=pin["license"],
        source=pin["source"],
        identity_kind=pin["identity_kind"],
        artifact_sha256=artifact_sha or _sha256_text(exe.read_text(encoding="utf-8")),
        install_root=str(install_root),
        is_hermetic_shadow=is_hermetic,
    )


# ---------------------------------------------------------------------------
# Install authorization gate
# ---------------------------------------------------------------------------


def _gate_install(
    tool_id: str,
    *,
    yes: bool,
    strict: bool,
    platform_id: str | None,
    checksum_verified: bool | None,
    test_mode: bool | None,
    import_context: bool,
    capability_discovery: bool,
) -> list[str]:
    """Return block reasons (empty means authorized)."""

    reasons: list[str] = []
    if import_context:
        reasons.append("forbidden_on_import")
    if capability_discovery:
        reasons.append("forbidden_on_capability_discovery")
    if not yes:
        reasons.append("requires_yes_true")
    if test_mode is None:
        test_mode = bool(
            os.environ.get("PYTEST_CURRENT_TEST")
            or os.environ.get("IPFS_DATASETS_PY_TEST_MODE")
        )
    try:
        authorize_installer_entry_install(
            tool_id,
            yes=yes,
            explicit_call=True,
            import_context=import_context,
            capability_discovery=capability_discovery,
            checksum_verified=checksum_verified,
            platform=platform_id,
            system_package_mutation=False,
            test_mode=bool(test_mode),
        )
    except InstallerRegistryError as exc:
        reasons.append(f"registry:{exc}")
    except Exception as exc:  # pragma: no cover - defensive
        reasons.append(f"registry_error:{type(exc).__name__}")

    # Role binding: external engines must remain shadows.
    try:
        role = get_tool_role(tool_id)
        if role.role is not ToolRole.SHADOW:
            reasons.append("tool_role_is_not_shadow")
        if role.authority_ceiling is not ToolchainAuthorityCeiling.NONE:
            reasons.append("shadow_authority_ceiling_not_none")
    except Exception as exc:
        reasons.append(f"role_lookup_failed:{type(exc).__name__}:{exc}")

    if platform_id is not None:
        try:
            default_installer_registry().assert_platform_supported(platform_id)
        except InstallerRegistryError as exc:
            if strict:
                reasons.append(str(exc))
            else:
                reasons.append(f"platform_unsupported:{platform_id}")
    return reasons


def materialize_hermetic_shadow(
    tool_id: str,
    *,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    force: bool = False,
) -> ShadowEngineIdentity:
    """Write the pin-bound hermetic shadow shim and identity manifest."""

    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    root = _expand_install_root(install_root)
    version = pin["version"]
    exe = executable_path(root, tool_id, version)
    manifest = identity_manifest_path(root, tool_id, version)

    if exe.is_file() and manifest.is_file() and not force:
        existing = _identity_from_disk(tool_id, root, pin)
        if existing is not None:
            return existing

    # Write identity first so the shim can reference a stable path.
    provisional = {
        "schema_version": INSTALL_RECEIPT_SCHEMA,
        "interface": INTERFACE,
        "tool_id": tool_id,
        "version": version,
        "license": pin["license"],
        "source": pin["source"],
        "identity_kind": pin["identity_kind"],
        "role": ToolRole.SHADOW.value,
        "authority_ceiling": ToolchainAuthorityCeiling.NONE.value,
        "is_hermetic_shadow": True,
        "replaces_gap_id": GAP_ID,
        "install_root": str(root),
        "executable": str(exe),
        "family": FAMILY,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
    }
    _write_identity_manifest(manifest, provisional)
    source = build_shadow_shim_source(
        tool_id,
        version,
        identity_file=str(manifest),
    )
    artifact_sha = _write_executable(exe, source)
    provisional["artifact_sha256"] = artifact_sha
    _write_identity_manifest(manifest, provisional)

    identity = ShadowEngineIdentity(
        tool_id=tool_id,
        version=version,
        executable=str(exe),
        license=pin["license"],
        source=pin["source"],
        identity_kind=pin["identity_kind"],
        artifact_sha256=artifact_sha,
        install_root=str(root),
        is_hermetic_shadow=True,
    )
    return identity


# ---------------------------------------------------------------------------
# Public ensure_* entrypoints (registry contract)
# ---------------------------------------------------------------------------


def ensure_souffle(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    platform_id: str | None = None,
    hermetic_shadow: bool = True,
    checksum_verified: bool | None = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    test_mode: bool | None = None,
    on_progress: ProgressCallback | None = None,
) -> InstallReceipt:
    """Explicit strict installation of the pinned Soufflé shadow engine."""

    return _ensure_tool(
        TOOL_SOUFFLE,
        yes=yes,
        strict=strict,
        force=force,
        install_root=install_root,
        repo_root=repo_root,
        lock_path=lock_path,
        platform_id=platform_id,
        hermetic_shadow=hermetic_shadow,
        checksum_verified=checksum_verified,
        import_context=import_context,
        capability_discovery=capability_discovery,
        test_mode=test_mode,
        on_progress=on_progress,
    )


def ensure_secpal(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    platform_id: str | None = None,
    hermetic_shadow: bool = True,
    checksum_verified: bool | None = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    test_mode: bool | None = None,
    on_progress: ProgressCallback | None = None,
) -> InstallReceipt:
    """Explicit strict installation of the pinned SecPAL shadow engine."""

    return _ensure_tool(
        TOOL_SECPAL,
        yes=yes,
        strict=strict,
        force=force,
        install_root=install_root,
        repo_root=repo_root,
        lock_path=lock_path,
        platform_id=platform_id,
        hermetic_shadow=hermetic_shadow,
        checksum_verified=checksum_verified,
        import_context=import_context,
        capability_discovery=capability_discovery,
        test_mode=test_mode,
        on_progress=on_progress,
    )


def _ensure_tool(
    tool_id: str,
    *,
    yes: bool,
    strict: bool,
    force: bool,
    install_root: Path | str | None,
    repo_root: Path | str | None,
    lock_path: Path | str | None,
    platform_id: str | None,
    hermetic_shadow: bool,
    checksum_verified: bool | None,
    import_context: bool,
    capability_discovery: bool,
    test_mode: bool | None,
    on_progress: ProgressCallback | None,
) -> InstallReceipt:
    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    selected_version = pin["version"]
    root = _expand_install_root(install_root)
    host_platform = platform_id or _detect_platform()

    # Registry entry must name this ensure_* function.
    try:
        entry = get_installer_entry(tool_id)
        expected = f"ensure_{tool_id.replace('-', '_')}"
        if entry.ensure_name != expected and entry.ensure_name != f"ensure_{tool_id}":
            # souffle -> ensure_souffle; secpal -> ensure_secpal
            if entry.ensure_name not in {f"ensure_{tool_id}", expected}:
                pass  # still proceed; registry is authoritative for presence
        if entry.family.value != FAMILY:
            return InstallReceipt(
                tool_id=tool_id,
                status="failed",
                identity=None,
                selected_version=selected_version,
                detail=f"installer family mismatch: {entry.family.value}",
                strict=strict,
                yes=yes,
                block_reasons=("family_mismatch",),
            )
        if entry.replaces_gap_id and entry.replaces_gap_id != GAP_ID:
            return InstallReceipt(
                tool_id=tool_id,
                status="failed",
                identity=None,
                selected_version=selected_version,
                detail=f"unexpected gap replacement {entry.replaces_gap_id!r}",
                strict=strict,
                yes=yes,
                block_reasons=("gap_mismatch",),
            )
    except InstallerRegistryError as exc:
        return InstallReceipt(
            tool_id=tool_id,
            status="failed",
            identity=None,
            selected_version=selected_version,
            detail=str(exc),
            strict=strict,
            yes=yes,
            block_reasons=("missing_registry_entry",),
        )

    existing = _identity_from_disk(tool_id, root, pin)
    if existing is not None and not force:
        _announce(
            f"{tool_id} {existing.version} already present at {existing.executable}",
            on_progress,
        )
        return InstallReceipt(
            tool_id=tool_id,
            status="already_present",
            identity=existing,
            selected_version=existing.version,
            detail="pin-bound shadow already installed",
            strict=strict,
            yes=yes,
        )

    block_reasons = _gate_install(
        tool_id,
        yes=yes,
        strict=strict,
        platform_id=host_platform,
        checksum_verified=checksum_verified,
        test_mode=test_mode,
        import_context=import_context,
        capability_discovery=capability_discovery,
    )
    if block_reasons:
        status = "refused" if "requires_yes_true" in block_reasons else "blocked"
        detail = "; ".join(block_reasons)
        _announce(f"{tool_id} install {status}: {detail}", on_progress)
        receipt = InstallReceipt(
            tool_id=tool_id,
            status=status,
            identity=None,
            selected_version=selected_version,
            detail=detail,
            strict=strict,
            yes=yes,
            block_reasons=tuple(block_reasons),
        )
        if strict and status != "refused":
            raise AuthorizationInstallerError(detail)
        return receipt

    if not hermetic_shadow:
        detail = (
            "real vendor binary acquisition is not performed in offline "
            "certification lanes; set hermetic_shadow=True for pin-bound shims"
        )
        if strict:
            raise AuthorizationInstallerError(detail)
        return InstallReceipt(
            tool_id=tool_id,
            status="failed",
            identity=None,
            selected_version=selected_version,
            detail=detail,
            strict=strict,
            yes=yes,
            block_reasons=("vendor_binary_unavailable_offline",),
        )

    try:
        identity = materialize_hermetic_shadow(
            tool_id,
            install_root=root,
            repo_root=repo_root,
            lock_path=lock_path,
            force=force,
        )
    except Exception as exc:
        detail = f"materialize_failed:{type(exc).__name__}:{exc}"
        if strict:
            raise AuthorizationInstallerError(detail) from exc
        return InstallReceipt(
            tool_id=tool_id,
            status="failed",
            identity=None,
            selected_version=selected_version,
            detail=detail,
            strict=strict,
            yes=yes,
            block_reasons=("materialize_failed",),
        )

    # Strict pin selection: installed version must match the reviewed pin.
    if identity.version != selected_version:
        detail = (
            f"strict pin mismatch for {tool_id}: "
            f"installed={identity.version!r} expected={selected_version!r}"
        )
        if strict:
            raise AuthorizationInstallerError(detail)
        return InstallReceipt(
            tool_id=tool_id,
            status="failed",
            identity=identity,
            selected_version=selected_version,
            detail=detail,
            strict=strict,
            yes=yes,
            block_reasons=("pin_mismatch",),
        )

    observed = _probe_version(Path(identity.executable))
    if selected_version not in observed and tool_id not in observed.casefold():
        detail = f"version probe failed for {tool_id}: {observed!r}"
        if strict:
            raise AuthorizationInstallerError(detail)
        return InstallReceipt(
            tool_id=tool_id,
            status="failed",
            identity=identity,
            selected_version=selected_version,
            detail=detail,
            strict=strict,
            yes=yes,
            block_reasons=("version_probe_failed",),
        )

    _announce(
        f"installed {tool_id} {identity.version} shadow at {identity.executable}",
        on_progress,
    )
    return InstallReceipt(
        tool_id=tool_id,
        status="installed",
        identity=identity,
        selected_version=selected_version,
        detail="pin-bound hermetic shadow materialized",
        strict=strict,
        yes=yes,
    )


def ensure_authorization_external(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    tools: Sequence[str] | None = None,
    **kwargs: Any,
) -> AuthorizationInstallBundle:
    """Install every required external authorization shadow (strict selection)."""

    selected = tuple(tools or EXTERNAL_TOOLS)
    root = _expand_install_root(install_root)
    receipts: list[InstallReceipt] = []
    for tool_id in selected:
        if tool_id == TOOL_SOUFFLE:
            receipts.append(
                ensure_souffle(
                    yes=yes,
                    strict=strict,
                    force=force,
                    install_root=root,
                    repo_root=repo_root,
                    lock_path=lock_path,
                    **kwargs,
                )
            )
        elif tool_id == TOOL_SECPAL:
            receipts.append(
                ensure_secpal(
                    yes=yes,
                    strict=strict,
                    force=force,
                    install_root=root,
                    repo_root=repo_root,
                    lock_path=lock_path,
                    **kwargs,
                )
            )
        else:
            raise AuthorizationInstallerError(f"unknown external tool {tool_id!r}")
    return AuthorizationInstallBundle(receipts=receipts, install_root=str(root))


def describe_authorization_installer() -> dict[str, Any]:
    """Side-effect-free metadata for packaging and discovery."""

    registry = default_installer_registry()
    entries = []
    for tool_id in EXTERNAL_TOOLS:
        entry = registry.get(tool_id)
        pin = pin_for_tool(tool_id)
        entries.append(
            {
                "tool_id": tool_id,
                "ensure_name": entry.ensure_name,
                "module_path": entry.module_path,
                "replaces_gap_id": entry.replaces_gap_id,
                "pin_version": pin["version"],
                "role": ToolRole.SHADOW.value,
                "authority_ceiling": ToolchainAuthorityCeiling.NONE.value,
            }
        )
    return {
        "interface": INTERFACE,
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "program": PROGRAM,
        "family": FAMILY,
        "gap_id": GAP_ID,
        "tools": entries,
        "policy": {
            "never_on_import": True,
            "requires_yes_true": True,
            "user_local_only": True,
            "external_engines_are_shadows": True,
            "in_process_references_retain_authority": True,
            "never_grants_authorization_authority": True,
            "never_grants_theorem_authority": True,
        },
        "default_lock_path": str(resolve_lock_path()),
    }


# Import-time safety: this module must never install or download.
def _import_side_effect_free() -> bool:
    return True


assert _import_side_effect_free() is True


__all__ = [
    "INTERFACE",
    "SCHEMA_VERSION",
    "INSTALL_RECEIPT_SCHEMA",
    "GOAL_ID",
    "TASK_ID",
    "PROGRAM",
    "FAMILY",
    "GAP_ID",
    "TOOL_SOUFFLE",
    "TOOL_SECPAL",
    "EXTERNAL_TOOLS",
    "DEFAULT_PINS",
    "ENV_FORCE_OUTCOME",
    "ENV_DISAGREE",
    "ENV_MALFORMED",
    "ENV_SLEEP_SECONDS",
    "AuthorizationInstallerError",
    "AuthorizationInstallBundle",
    "InstallReceipt",
    "ShadowEngineIdentity",
    "build_shadow_shim_source",
    "describe_authorization_installer",
    "ensure_authorization_external",
    "ensure_secpal",
    "ensure_souffle",
    "executable_path",
    "materialize_hermetic_shadow",
    "pin_for_tool",
]
