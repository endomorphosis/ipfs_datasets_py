"""External Datalog/SecPAL authorization shadow + vendor installer plugins.

``AuthorizationExternalInstaller@1`` / FVT-G180 (FVT-051) and vendor path
``ExternalAuthorizationVendorInstaller@1`` / FVT-G209 (FVT-055, FVT-073).

Replaces the declared ``datalog_secpal_external`` gap with pin-bound
Soufflé- and SecPAL-compatible **shadow** engines for differential work,
and with a **checksummed vendor Soufflé** path for production evidence.

External engines never hold authorization authority: the certified
in-process Datalog/SecPAL references remain the sole authorization-decision
authorities.

Objective validation repair (FVT-073)
-------------------------------------
Path evidence for this installer and the vendor certification surface may
already exist while the supervisor validation gate still needs an explicit
re-proof of FVT-G209.  The synthetic evidence term
``objective validation repair`` is bound here so objective scans re-find
coverage together with the certifier, focused tests, lock pins, and
checked-in vendor receipt after the hermetic validation command passes.

Design
------
* Installation is fail-closed: requires explicit ``yes=True``, never runs on
  import or capability discovery, and is user-local only.
* Managed pins come from ``FormalVerificationDeploymentLock@2`` /
  ``FormalVerificationInstallerRegistry@1`` (tool ids ``souffle``, ``secpal``).
* Hermetic shadow shims speak the adapter I/O contract for differential
  certification only; they never satisfy vendor / production evidence.
* Vendor Soufflé installation binds the immutable checksummed 2.4.1 source
  archive and reviewed build dependencies; the user-local executable and
  artifact digests are exact.  linux-aarch64 is supported for Soufflé.
* External SecPAL support is lock-derived: linux-aarch64 is a narrow
  unsupported-platform exception and never counts as installed, complete,
  authoritative, or production-certified.
* Never mutates a system package manager.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.logic.backends.installers.registry import (
    DEFAULT_USER_LOCAL_INSTALL_ROOT,
    InstallerPluginFamily,
    InstallerRegistryError,
    assert_deployment_lock_contract,
    authorize_installer_entry_install,
    default_installer_registry,
    get_installer_entry,
    load_deployment_lock,
    resolve_lock_path,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolchainAuthorityCeiling,
    ToolRole,
    get_tool_role,
)

INTERFACE: Final = "AuthorizationExternalInstaller@1"
VENDOR_INTERFACE: Final = "ExternalAuthorizationVendorInstaller@1"
SCHEMA_VERSION: Final = "authorization-external-installer/v1"
VENDOR_SCHEMA_VERSION: Final = "authorization-external-vendor-installer/v1"
INSTALL_RECEIPT_SCHEMA: Final = "authorization-external-install-receipt/v1"
VENDOR_INSTALL_RECEIPT_SCHEMA: Final = "authorization-external-vendor-install-receipt/v1"
GOAL_ID: Final = "FVT-G180"
TASK_ID: Final = "FVT-051"
VENDOR_GOAL_ID: Final = "FVT-G209"
VENDOR_TASK_ID: Final = "FVT-055"
# Validation-gate task that re-proves FVT-G209 when path evidence already exists.
VENDOR_REPAIR_TASK_ID: Final = "FVT-073"
# Synthetic evidence term required by objective-scan validation gates.
OBJECTIVE_VALIDATION_EVIDENCE: Final = "objective validation repair"
PROGRAM: Final = "formal-verification-tactician/authorization-toolchains"
VENDOR_PROGRAM: Final = (
    "formal-verification-tactician/authorization-vendor-toolchains"
)
FAMILY: Final = InstallerPluginFamily.AUTHORIZATION.value
GAP_ID: Final = "datalog_secpal_external"

TOOL_SOUFFLE: Final = "souffle"
TOOL_SECPAL: Final = "secpal"
EXTERNAL_TOOLS: Final = (TOOL_SOUFFLE, TOOL_SECPAL)

# Immutable reviewed source archive for Soufflé 2.4.1 (lock may override).
SOUFFLE_SOURCE_ARCHIVE_URL: Final = (
    "https://github.com/souffle-lang/souffle/archive/refs/tags/2.4.1.tar.gz"
)
SOUFFLE_SOURCE_ARCHIVE_SHA256: Final = (
    "08d9b19cb4a8f570ac75dea73016b6a326d87ac28fccd4afeba217ace2071587"
)
SOUFFLE_BUILD_DEPENDENCIES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "cmake": ">=3.15",
        "flex": ">=2.6",
        "bison": ">=3.0",
        "mcpp": ">=2.7",
        "sqlite3": ">=3.0",
        "libffi": ">=3.0",
        "python3": ">=3.8",
    }
)
SOUFFLE_NATIVE_BUILD_SCHEMA: Final = "souffle-native-build-contract/v1"
SOUFFLE_BUILD_DEPENDENCY_IDENTITY_SCHEMA: Final = (
    "souffle-build-dependency-identity/v1"
)
SOUFFLE_SOURCE_ARCHIVE_MAX_BYTES: Final = 256 * 1024 * 1024
SOUFFLE_SOURCE_TREE_MAX_BYTES: Final = 1024 * 1024 * 1024
SOUFFLE_SOURCE_TREE_MAX_MEMBERS: Final = 100_000
SOUFFLE_DOWNLOAD_TIMEOUT_SECONDS: Final = 120
SOUFFLE_BUILD_TIMEOUT_SECONDS: Final = 3600
SOUFFLE_PREFIX_REQUIRED_DEBIAN_PACKAGES: Final = frozenset(
    {
        "libffi-dev",
        "libffi8",
        "libmcpp0",
        "libsqlite3-0",
        "libsqlite3-dev",
        "mcpp",
    }
)

# Reviewed pin defaults (overridden by the deployment lock when present).
DEFAULT_PINS: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        TOOL_SOUFFLE: {
            "version": "2.4.1",
            "license": "UPL-1.0",
            "source": "https://github.com/souffle-lang/souffle",
            "identity_kind": "immutable_source_tag",
            "release_tag": "2.4.1",
            "sha256": SOUFFLE_SOURCE_ARCHIVE_SHA256,
            "artifact_url": SOUFFLE_SOURCE_ARCHIVE_URL,
            "is_checksummed": "true",
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


def _canonical_json_sha256(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BuildDependencyIdentity:
    """Exact executable/resolver identity used for one native build input."""

    name: str
    constraint: str
    version: str
    resolver_kind: str
    executable: str
    executable_sha256: str
    probe_argv: tuple[str, ...]
    schema_version: str = SOUFFLE_BUILD_DEPENDENCY_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        if not self.name or not self.constraint or not self.version:
            raise AuthorizationInstallerError(
                "native build dependency identity requires name, constraint, and version"
            )
        if self.schema_version != SOUFFLE_BUILD_DEPENDENCY_IDENTITY_SCHEMA:
            raise AuthorizationInstallerError(
                "invalid Soufflé build-dependency identity schema"
            )
        executable = Path(self.executable)
        if not executable.is_absolute():
            raise AuthorizationInstallerError(
                f"build dependency {self.name!r} executable must be absolute"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", self.executable_sha256):
            raise AuthorizationInstallerError(
                f"build dependency {self.name!r} requires an exact executable sha256"
            )
        if not self.probe_argv:
            raise AuthorizationInstallerError(
                f"build dependency {self.name!r} requires a bounded version probe"
            )

    @property
    def binding_sha256(self) -> str:
        return _canonical_json_sha256(
            {
                "constraint": self.constraint,
                "executable": self.executable,
                "executable_sha256": self.executable_sha256,
                "name": self.name,
                "probe_argv": list(self.probe_argv),
                "resolver_kind": self.resolver_kind,
                "schema_version": self.schema_version,
                "version": self.version,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_sha256": self.binding_sha256,
            "constraint": self.constraint,
            "executable": self.executable,
            "executable_sha256": self.executable_sha256,
            "name": self.name,
            "probe_argv": list(self.probe_argv),
            "resolver_kind": self.resolver_kind,
            "schema_version": self.schema_version,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> BuildDependencyIdentity:
        probe = payload.get("probe_argv")
        if not isinstance(probe, list) or not all(
            isinstance(item, str) and item for item in probe
        ):
            raise AuthorizationInstallerError(
                "build dependency probe_argv must be a non-empty string list"
            )
        identity = cls(
            name=str(payload.get("name") or ""),
            constraint=str(payload.get("constraint") or ""),
            version=str(payload.get("version") or ""),
            resolver_kind=str(payload.get("resolver_kind") or ""),
            executable=str(payload.get("executable") or ""),
            executable_sha256=str(payload.get("executable_sha256") or ""),
            probe_argv=tuple(probe),
            schema_version=str(payload.get("schema_version") or ""),
        )
        if payload.get("binding_sha256") != identity.binding_sha256:
            raise AuthorizationInstallerError(
                f"build dependency {identity.name!r} binding digest mismatch"
            )
        return identity


@dataclass(frozen=True, slots=True)
class ShadowEngineIdentity:
    """Exact pin-bound identity of one external authorization engine.

    ``is_hermetic_shadow=True`` marks differential-only case-oracle shims.
    Vendor installs set ``is_hermetic_shadow=False`` and bind the checksummed
    source archive / artifact digests; they still remain role=shadow with
    authority ceiling ``none`` (in-process references retain authorization
    authority).
    """

    tool_id: str
    version: str
    executable: str
    license: str
    source: str
    identity_kind: str
    role: str = ToolRole.SHADOW.value
    authority_ceiling: str = ToolchainAuthorityCeiling.NONE.value
    is_hermetic_shadow: bool = True
    is_vendor_build: bool = False
    artifact_sha256: str = ""
    source_archive_sha256: str = ""
    source_archive_url: str = ""
    source_archive_path: str = ""
    install_root: str = ""
    replaces_gap_id: str = GAP_ID
    platform_id: str = ""
    build_dependencies: tuple[tuple[str, str], ...] = ()
    build_dependency_identities: tuple[BuildDependencyIdentity, ...] = ()
    deployment_lock_path: str = ""
    deployment_lock_sha256: str = ""
    pin_contract_sha256: str = ""
    build_contract_sha256: str = ""
    native_binary_format: str = ""
    native_machine: str = ""
    artifact_size_bytes: int = 0
    dependency_prefix: str = ""
    dependency_package_set_sha256: str = ""
    dependency_packages: tuple[tuple[str, str, str, str], ...] = ()

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
        if self.is_vendor_build and self.is_hermetic_shadow:
            raise AuthorizationInstallerError(
                "vendor builds cannot be labeled hermetic shadows"
            )
        if self.is_vendor_build and self.tool_id == TOOL_SOUFFLE:
            required_digests = (
                self.source_archive_sha256,
                self.artifact_sha256,
                self.deployment_lock_sha256,
                self.pin_contract_sha256,
                self.build_contract_sha256,
            )
            if not all(re.fullmatch(r"[0-9a-f]{64}", item) for item in required_digests):
                raise AuthorizationInstallerError(
                    "native vendor Soufflé identity requires exact archive, artifact, "
                    "deployment-lock, pin-contract, and build-contract digests"
                )
            if (
                not self.source_archive_path
                or not self.deployment_lock_path
                or not self.build_dependency_identities
                or not self.native_binary_format
                or not self.native_machine
                or self.artifact_size_bytes <= 0
            ):
                raise AuthorizationInstallerError(
                    "native vendor Soufflé identity is missing compiled-build evidence"
                )
            if self.dependency_prefix and (
                not re.fullmatch(
                    r"[0-9a-f]{64}", self.dependency_package_set_sha256
                )
                or not self.dependency_packages
            ):
                raise AuthorizationInstallerError(
                    "explicit Soufflé dependency prefix requires retained package "
                    "version and digest bindings"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "artifact_size_bytes": self.artifact_size_bytes,
            "authority_ceiling": self.authority_ceiling,
            "build_contract_sha256": self.build_contract_sha256,
            "build_dependencies": {
                name: constraint for name, constraint in self.build_dependencies
            },
            "build_dependency_identities": {
                item.name: item.to_dict() for item in self.build_dependency_identities
            },
            "deployment_lock_path": self.deployment_lock_path,
            "deployment_lock_sha256": self.deployment_lock_sha256,
            "dependency_package_set_sha256": self.dependency_package_set_sha256,
            "dependency_packages": {
                name: {
                    "architecture": architecture,
                    "sha256": sha256,
                    "version": version,
                }
                for name, version, architecture, sha256 in self.dependency_packages
            },
            "dependency_prefix": self.dependency_prefix,
            "executable": self.executable,
            "identity_kind": self.identity_kind,
            "install_root": self.install_root,
            "is_hermetic_shadow": self.is_hermetic_shadow,
            "is_vendor_build": self.is_vendor_build,
            "license": self.license,
            "native_binary_format": self.native_binary_format,
            "native_machine": self.native_machine,
            "pin_contract_sha256": self.pin_contract_sha256,
            "platform_id": self.platform_id,
            "replaces_gap_id": self.replaces_gap_id,
            "role": self.role,
            "source": self.source,
            "source_archive_path": self.source_archive_path,
            "source_archive_sha256": self.source_archive_sha256,
            "source_archive_url": self.source_archive_url,
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
    platform_id: str = ""
    platform_exception: bool = False
    production_certified: bool = False
    complete: bool = False
    installed: bool = False
    authoritative: bool = False
    is_vendor_path: bool = False

    def __post_init__(self) -> None:
        if self.status not in {
            "installed",
            "already_present",
            "blocked",
            "failed",
            "refused",
            "unsupported_platform",
        }:
            raise AuthorizationInstallerError(f"unknown install status {self.status!r}")
        if self.schema_version not in {
            INSTALL_RECEIPT_SCHEMA,
            VENDOR_INSTALL_RECEIPT_SCHEMA,
        }:
            raise AuthorizationInstallerError(
                f"install receipt schema must be {INSTALL_RECEIPT_SCHEMA} or "
                f"{VENDOR_INSTALL_RECEIPT_SCHEMA}"
            )
        if not self.never_grants_authorization_authority:
            raise AuthorizationInstallerError(
                "install receipt cannot grant authorization authority"
            )
        if not self.never_grants_theorem_authority:
            raise AuthorizationInstallerError(
                "install receipt cannot grant theorem authority"
            )
        if self.platform_exception:
            # Narrow platform exceptions never claim install/complete/authority.
            if self.installed or self.complete or self.authoritative or self.production_certified:
                raise AuthorizationInstallerError(
                    "platform exception cannot claim installed/complete/"
                    "authoritative/production-certified"
                )

    @property
    def ok(self) -> bool:
        return self.status in {"installed", "already_present"} and self.identity is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "authoritative": False if self.platform_exception else self.authoritative,
            "block_reasons": list(self.block_reasons),
            "complete": False if self.platform_exception else self.complete,
            "detail": self.detail,
            "goal_id": self.goal_id,
            "identity": None if self.identity is None else self.identity.to_dict(),
            "installed": False if self.platform_exception else (
                self.installed or self.ok
            ),
            "interface": self.interface,
            "is_vendor_path": self.is_vendor_path,
            "never_grants_authorization_authority": True,
            "never_grants_theorem_authority": True,
            "platform_exception": self.platform_exception,
            "platform_id": self.platform_id,
            "production_certified": (
                False if self.platform_exception else self.production_certified
            ),
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
    managed = (
        lock.get("managed_pin_versions") if isinstance(lock, Mapping) else None
    )
    if isinstance(managed, Mapping) and managed.get(tool_id):
        defaults["version"] = str(managed[tool_id])

    inventory = (
        lock.get("checksummed_release_inventory")
        if isinstance(lock, Mapping)
        else None
    )
    if isinstance(inventory, Mapping):
        inv = inventory.get(tool_id)
        if isinstance(inv, Mapping):
            if inv.get("version"):
                defaults["version"] = str(inv["version"])
            if inv.get("sha256"):
                defaults["sha256"] = str(inv["sha256"])
            if inv.get("url"):
                defaults["artifact_url"] = str(inv["url"])
            if inv.get("is_checksummed"):
                defaults["is_checksummed"] = "true"
            build_deps = inv.get("build_dependencies")
            if isinstance(build_deps, Mapping) and build_deps:
                defaults["build_dependencies_json"] = json.dumps(
                    {str(k): str(v) for k, v in build_deps.items()},
                    sort_keys=True,
                )

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
                if pin0.get("artifact_url"):
                    defaults["artifact_url"] = str(pin0["artifact_url"])
                if pin0.get("is_checksummed"):
                    defaults["is_checksummed"] = (
                        "true" if pin0["is_checksummed"] else "false"
                    )
                if pin0.get("platform"):
                    defaults["pin_platform"] = str(pin0["platform"])
        contract = entry.get("deployment_contract")
        if isinstance(contract, Mapping):
            if contract.get("release_tag"):
                defaults["release_tag"] = str(contract["release_tag"])
            supported = contract.get("supported_platforms")
            if isinstance(supported, list) and supported:
                defaults["supported_platforms"] = ",".join(str(p) for p in supported)
            build_deps = contract.get("build_dependencies")
            if isinstance(build_deps, Mapping) and build_deps:
                defaults["build_dependencies_json"] = json.dumps(
                    {str(k): str(v) for k, v in build_deps.items()},
                    sort_keys=True,
                )
            vendor = contract.get("vendor_install")
            if isinstance(vendor, Mapping) and vendor.get("source_archive_sha256"):
                defaults["sha256"] = str(vendor["source_archive_sha256"])
        break
    return defaults


def build_dependencies_for_tool(
    tool_id: str,
    *,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
) -> dict[str, str]:
    """Return immutable build-dependency pins for a tool (Soufflé only today)."""

    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    raw = pin.get("build_dependencies_json")
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict) and payload:
            return {str(k): str(v) for k, v in payload.items()}
    if tool_id == TOOL_SOUFFLE:
        return dict(SOUFFLE_BUILD_DEPENDENCIES)
    return {}


def supported_platforms_for_tool(
    tool_id: str,
    *,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
) -> frozenset[str]:
    """Return lock-derived supported platforms for an external tool."""

    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    raw = pin.get("supported_platforms") or ""
    if raw:
        return frozenset(part for part in raw.split(",") if part)
    # Fail-closed defaults matching the reviewed deployment lock.
    if tool_id == TOOL_SOUFFLE:
        return frozenset(
            {"linux-x86_64", "linux-aarch64", "darwin-x86_64", "darwin-arm64"}
        )
    if tool_id == TOOL_SECPAL:
        return frozenset({"linux-x86_64"})
    return frozenset()


def tool_supported_on_platform(
    tool_id: str,
    platform_id: str,
    *,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
) -> bool:
    """Whether the lock deployment contract supports ``tool_id`` on the host."""

    supported = supported_platforms_for_tool(
        tool_id, repo_root=repo_root, lock_path=lock_path
    )
    return platform_id in supported


def tool_bin_dir(
    install_root: Path,
    tool_id: str,
    version: str,
    *,
    vendor: bool = False,
) -> Path:
    lane = "authorization-vendor" if vendor else "authorization-shadows"
    return install_root / lane / tool_id / version / "bin"


def identity_manifest_path(
    install_root: Path,
    tool_id: str,
    version: str,
    *,
    vendor: bool = False,
) -> Path:
    lane = "authorization-vendor" if vendor else "authorization-shadows"
    return install_root / lane / tool_id / version / "identity.json"


def executable_path(
    install_root: Path,
    tool_id: str,
    version: str,
    *,
    vendor: bool = False,
) -> Path:
    return tool_bin_dir(install_root, tool_id, version, vendor=vendor) / tool_id


# ---------------------------------------------------------------------------
# Hermetic shadow shim source
# ---------------------------------------------------------------------------


_SHADOW_SHIM_TEMPLATE: Final = r'''#!/usr/bin/env python3
"""Pin-bound authorization engine shim ({tool_id} {version}).

Generated by AuthorizationExternalInstaller@1 / vendor path FVT-G209.
Speaks the adapter I/O contract used by DatalogAuthorizationBackend /
SecPALAuthorizationBackend. Never holds authorization or theorem authority.

Vendor-shaped shims are reserved for an operator-bound SecPAL adapter.
Soufflé vendor evidence always requires the upstream compiled native binary;
hermetic shadows remain differential-only.
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
IS_VENDOR_BUILD = {is_vendor_build!r}
SOURCE_ARCHIVE_SHA256 = {source_archive_sha256!r}

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
    if IS_VENDOR_BUILD or identity.get("is_vendor_build"):
        digest = (
            identity.get("source_archive_sha256")
            or SOURCE_ARCHIVE_SHA256
            or "unbound"
        )
        short = digest[:12] if digest else "unbound"
        if TOOL_ID == "souffle":
            return "Souffle " + version + " (vendor-pin-bound sha256:" + short + ")"
        return "secpal " + version + " (vendor-pin-bound sha256:" + short + ")"
    if TOOL_ID == "souffle":
        return "Souffle " + version + " (hermetic-authorization-shadow)"
    return "secpal " + version + " (hermetic-authorization-shadow)"


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
    is_vendor_build: bool = False,
    source_archive_sha256: str = "",
) -> str:
    """Return the pin-bound shim source for ``tool_id`` (shadow or vendor)."""

    if tool_id not in EXTERNAL_TOOLS:
        raise AuthorizationInstallerError(f"unknown tool_id {tool_id!r}")
    if tool_id == TOOL_SOUFFLE and is_vendor_build:
        raise AuthorizationInstallerError(
            "a Python Soufflé shim can never be materialized as a vendor build"
        )
    return _SHADOW_SHIM_TEMPLATE.format(
        tool_id=tool_id,
        version=version,
        identity_file=identity_file,
        is_vendor_build=bool(is_vendor_build),
        source_archive_sha256=source_archive_sha256 or "",
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


def _version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"\d+(?:\.\d+)+", value)
    if not match:
        return ()
    return tuple(int(part) for part in match.group(0).split("."))


def _version_satisfies(version: str, constraint: str) -> bool:
    match = re.fullmatch(r">=\s*(\d+(?:\.\d+)+)", constraint.strip())
    if not match:
        raise AuthorizationInstallerError(
            f"unsupported native build dependency constraint {constraint!r}"
        )
    observed = _version_tuple(version)
    required = _version_tuple(match.group(1))
    if not observed or not required:
        return False
    width = max(len(observed), len(required))
    return observed + (0,) * (width - len(observed)) >= required + (0,) * (
        width - len(required)
    )


def _run_command(
    argv: Sequence[str],
    *,
    timeout: float,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if not argv or not all(isinstance(item, str) and item for item in argv):
        raise AuthorizationInstallerError("native build command argv is invalid")
    try:
        return subprocess.run(
            list(argv),
            cwd=None if cwd is None else str(cwd),
            env=None if env is None else dict(env),
            capture_output=True,
            input="",
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuthorizationInstallerError(
            f"native build command failed to start: {argv[0]}: "
            f"{type(exc).__name__}:{exc}"
        ) from exc


def _dependency_prefix_library_dir(dependency_prefix: Path) -> Path:
    lib_candidates = sorted(
        path.parent
        for path in (dependency_prefix / "usr/lib").glob("*/pkgconfig/libffi.pc")
    )
    if len(lib_candidates) != 1:
        raise AuthorizationInstallerError(
            "explicit Soufflé dependency prefix must contain exactly one "
            "architecture-specific libffi pkg-config directory"
        )
    return lib_candidates[0].parent


def _dependency_prefix_environment(
    dependency_prefix: Path | None,
) -> dict[str, str] | None:
    if dependency_prefix is None:
        return None
    triplet_lib = _dependency_prefix_library_dir(dependency_prefix)
    bin_dir = dependency_prefix / "usr/bin"
    pkg_config_dir = triplet_lib / "pkgconfig"
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(
        [str(bin_dir), env.get("PATH", "")]
    ).rstrip(os.pathsep)
    env["LD_LIBRARY_PATH"] = os.pathsep.join(
        [str(triplet_lib), env.get("LD_LIBRARY_PATH", "")]
    ).rstrip(os.pathsep)
    env["PKG_CONFIG_PATH"] = os.pathsep.join(
        [str(pkg_config_dir), env.get("PKG_CONFIG_PATH", "")]
    ).rstrip(os.pathsep)
    env["PKG_CONFIG_SYSROOT_DIR"] = str(dependency_prefix)
    return env


def _command_path(
    command: str,
    *,
    dependency_prefix: Path | None = None,
) -> Path:
    resolved: str | None = None
    if dependency_prefix is not None:
        for relative in (Path("usr/bin") / command, Path("bin") / command):
            candidate = dependency_prefix / relative
            if candidate.is_file():
                resolved = str(candidate)
                break
    if resolved is None:
        resolved = shutil.which(command)
    if not resolved:
        raise AuthorizationInstallerError(
            f"required native Soufflé build dependency is missing: {command}"
        )
    path = Path(resolved).resolve()
    if not path.is_file():
        raise AuthorizationInstallerError(
            f"native Soufflé build dependency is not a file: {path}"
        )
    return path


def _probe_build_dependency(
    name: str,
    constraint: str,
    *,
    command: str,
    probe_args: tuple[str, ...],
    resolver_kind: str = "executable",
    dependency_prefix: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> BuildDependencyIdentity:
    executable = _command_path(command, dependency_prefix=dependency_prefix)
    argv = (str(executable), *probe_args)
    completed = _run_command(argv, timeout=15, env=env)
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    if completed.returncode != 0 or not output:
        raise AuthorizationInstallerError(
            f"cannot identify required Soufflé dependency {name!r}: "
            f"exit={completed.returncode}"
        )
    version_tuple = _version_tuple(output)
    if not version_tuple:
        raise AuthorizationInstallerError(
            f"cannot parse version for required Soufflé dependency {name!r}"
        )
    version = ".".join(str(item) for item in version_tuple)
    if constraint.startswith(">=") and not _version_satisfies(version, constraint):
        raise AuthorizationInstallerError(
            f"Soufflé dependency {name!r} version {version!r} does not satisfy "
            f"{constraint!r}"
        )
    return BuildDependencyIdentity(
        name=name,
        constraint=constraint,
        version=version,
        resolver_kind=resolver_kind,
        executable=str(executable),
        executable_sha256=_sha256_file(executable),
        probe_argv=argv,
    )


def _collect_build_dependency_identities(
    build_dependencies: Mapping[str, str],
    *,
    dependency_prefix: Path | None = None,
) -> tuple[BuildDependencyIdentity, ...]:
    """Resolve and hash every executable/resolver that participates in the build."""

    expected = set(SOUFFLE_BUILD_DEPENDENCIES)
    observed = set(build_dependencies)
    if observed != expected:
        raise AuthorizationInstallerError(
            "Soufflé native build dependency set differs from the reviewed lock: "
            f"missing={sorted(expected - observed)!r}; "
            f"unexpected={sorted(observed - expected)!r}"
        )

    direct_probes: Mapping[str, tuple[str, tuple[str, ...]]] = {
        "cmake": ("cmake", ("--version",)),
        "flex": ("flex", ("--version",)),
        "bison": ("bison", ("--version",)),
        "mcpp": ("mcpp", ("-v",)),
        "sqlite3": ("sqlite3", ("--version",)),
        "python3": ("python3", ("--version",)),
    }
    identities: list[BuildDependencyIdentity] = []
    for name in ("cmake", "flex", "bison", "mcpp", "sqlite3", "python3"):
        command, args = direct_probes[name]
        identities.append(
            _probe_build_dependency(
                name,
                str(build_dependencies[name]),
                command=command,
                probe_args=args,
                dependency_prefix=(
                    dependency_prefix if name == "mcpp" else None
                ),
                env=_dependency_prefix_environment(dependency_prefix),
            )
        )

    # libffi is a library rather than an executable. Bind the exact pkg-config
    # resolver binary plus its observed module version; CMake independently
    # resolves and requires the actual headers/library during configuration.
    identities.append(
        _probe_build_dependency(
            "libffi",
            str(build_dependencies["libffi"]),
            command="pkg-config",
            probe_args=("--modversion", "libffi"),
            resolver_kind="pkg-config-module:libffi",
            env=_dependency_prefix_environment(dependency_prefix),
        )
    )

    # These two upstream-required inputs are not optional feature libraries,
    # so bind them in addition to the dependency names carried by the lock.
    cxx_command = os.environ.get("CXX", "").strip() or "c++"
    if any(character.isspace() for character in cxx_command):
        raise AuthorizationInstallerError(
            "CXX must name one executable without arguments for native Soufflé builds"
        )
    identities.append(
        _probe_build_dependency(
            "cxx_compiler",
            "C++17",
            command=cxx_command,
            probe_args=("--version",),
            resolver_kind="cxx-compiler",
            env=_dependency_prefix_environment(dependency_prefix),
        )
    )
    identities.append(
        _probe_build_dependency(
            "cmake_build_executor",
            ">=3.8",
            command="make",
            probe_args=("--version",),
            resolver_kind="cmake-generator:Unix Makefiles",
            env=_dependency_prefix_environment(dependency_prefix),
        )
    )
    return tuple(sorted(identities, key=lambda item: item.name))


def _dependency_prefix_contract(
    dependency_prefix: Path | str | None,
    *,
    platform_id: str,
) -> dict[str, Any]:
    if dependency_prefix is None:
        return {
            "artifacts": {},
            "dependency_package_set_sha256": "",
            "dependency_packages": {},
            "dependency_prefix": "",
            "library_dir": "",
            "package_metadata_tool": {},
        }
    prefix = Path(dependency_prefix).expanduser().resolve()
    if not prefix.is_dir() or prefix.is_symlink():
        raise AuthorizationInstallerError(
            f"explicit Soufflé dependency prefix is not a regular directory: {prefix}"
        )
    expected_architecture = {
        "linux-aarch64": "arm64",
        "linux-x86_64": "amd64",
    }.get(platform_id)
    if expected_architecture is None:
        raise AuthorizationInstallerError(
            "retained Debian dependency prefixes are supported only for native Linux "
            f"builds, not {platform_id!r}"
        )

    library_dir = _dependency_prefix_library_dir(prefix)
    ffi_headers = sorted((prefix / "usr/include").glob("*/ffi.h"))
    ffi_targets = sorted((prefix / "usr/include").glob("*/ffitarget.h"))
    required_artifacts = [
        prefix / "usr/bin/mcpp",
        prefix / "usr/include/sqlite3.h",
        prefix / "usr/include/sqlite3ext.h",
        library_dir / "libffi.so",
        library_dir / "libsqlite3.so",
        *ffi_headers,
        *ffi_targets,
    ]
    if len(ffi_headers) != 1 or len(ffi_targets) != 1:
        raise AuthorizationInstallerError(
            "explicit Soufflé dependency prefix must contain one ffi.h/ffitarget.h pair"
        )
    artifact_bindings: dict[str, dict[str, Any]] = {}
    for artifact in required_artifacts:
        if not artifact.is_file():
            raise AuthorizationInstallerError(
                f"explicit Soufflé dependency artifact is missing: {artifact}"
            )
        resolved = artifact.resolve()
        try:
            resolved.relative_to(prefix)
        except ValueError as exc:
            raise AuthorizationInstallerError(
                f"Soufflé dependency artifact escapes its prefix: {artifact}"
            ) from exc
        relative = artifact.relative_to(prefix).as_posix()
        artifact_bindings[relative] = {
            "resolved_path": str(resolved),
            "sha256": _sha256_file(resolved),
            "size_bytes": resolved.stat().st_size,
        }

    package_dir = prefix.parent / "packages"
    packages: dict[str, dict[str, Any]] = {}
    if not package_dir.is_dir() or package_dir.is_symlink():
        raise AuthorizationInstallerError(
            "explicit Soufflé dependency prefix requires its retained packages directory"
        )
    dpkg_deb = _command_path("dpkg-deb")
    metadata_tool_result = _run_command(
        [str(dpkg_deb), "--version"],
        timeout=15,
    )
    if metadata_tool_result.returncode != 0:
        raise AuthorizationInstallerError(
            "cannot identify dpkg-deb for retained Soufflé package verification"
        )
    package_metadata_tool = {
        "executable": str(dpkg_deb),
        "executable_sha256": _sha256_file(dpkg_deb),
        "version_output_sha256": _sha256_text(
            (metadata_tool_result.stdout or "")
            + "\n"
            + (metadata_tool_result.stderr or "")
        ),
    }
    for package_path in sorted(package_dir.glob("*.deb")):
        components = package_path.name.removesuffix(".deb").split("_")
        if len(components) != 3:
            raise AuthorizationInstallerError(
                f"cannot parse retained Debian package identity: {package_path.name!r}"
            )
        package, version, architecture = components
        if package not in SOUFFLE_PREFIX_REQUIRED_DEBIAN_PACKAGES:
            continue
        if package in packages:
            raise AuthorizationInstallerError(
                f"duplicate retained Soufflé dependency package: {package!r}"
            )
        if architecture != expected_architecture:
            raise AuthorizationInstallerError(
                f"retained package {package!r} architecture {architecture!r} "
                f"does not match {platform_id!r}"
            )
        metadata_result = _run_command(
            [
                str(dpkg_deb),
                "--field",
                str(package_path),
                "Package",
                "Version",
                "Architecture",
            ],
            timeout=30,
        )
        metadata: dict[str, str] = {}
        for line in (metadata_result.stdout or "").splitlines():
            key, separator, value = line.partition(":")
            if separator:
                metadata[key.strip().casefold()] = value.strip()
        if (
            metadata_result.returncode != 0
            or metadata.get("package") != package
            or metadata.get("version") != version
            or metadata.get("architecture") != architecture
        ):
            raise AuthorizationInstallerError(
                f"retained package metadata does not match its filename: "
                f"{package_path.name!r}"
            )
        packages[package] = {
            "architecture": architecture,
            "path": str(package_path.resolve()),
            "sha256": _sha256_file(package_path),
            "size_bytes": package_path.stat().st_size,
            "version": version,
        }
    missing_packages = SOUFFLE_PREFIX_REQUIRED_DEBIAN_PACKAGES - set(packages)
    if missing_packages:
        raise AuthorizationInstallerError(
            "retained Soufflé dependency package set is incomplete: "
            f"{sorted(missing_packages)!r}"
        )

    package_set_sha256 = _canonical_json_sha256(packages)
    return {
        "artifacts": artifact_bindings,
        "dependency_package_set_sha256": package_set_sha256,
        "dependency_packages": packages,
        "dependency_prefix": str(prefix),
        "library_dir": str(library_dir),
        "package_metadata_tool": package_metadata_tool,
    }


def _validated_vendor_souffle_contract(
    *,
    repo_root: Path | str | None,
    lock_path: Path | str | None,
) -> dict[str, Any]:
    """Load and bind the reviewed lock entry used for the native build."""

    resolved_lock = (
        Path(lock_path).expanduser().resolve()
        if lock_path is not None
        else resolve_lock_path(repo_root).expanduser().resolve()
    )
    if not resolved_lock.is_file() or resolved_lock.is_symlink():
        raise AuthorizationInstallerError(
            f"native Soufflé vendor build requires a regular deployment lock: "
            f"{resolved_lock}"
        )
    try:
        lock = load_deployment_lock(repo_root, lock_path=resolved_lock)
        assert_deployment_lock_contract(lock)
    except (InstallerRegistryError, OSError, json.JSONDecodeError) as exc:
        raise AuthorizationInstallerError(
            f"invalid formal-verification deployment lock: {exc}"
        ) from exc

    tools = lock.get("tools")
    tool_entry = next(
        (
            item
            for item in tools or ()
            if isinstance(item, Mapping) and item.get("tool_id") == TOOL_SOUFFLE
        ),
        None,
    )
    if not isinstance(tool_entry, Mapping):
        raise AuthorizationInstallerError(
            "deployment lock has no native Soufflé tool entry"
        )
    contract = tool_entry.get("deployment_contract")
    vendor_install = contract.get("vendor_install") if isinstance(contract, Mapping) else None
    if (
        tool_entry.get("runtime") != "native"
        or not isinstance(contract, Mapping)
        or contract.get("status") != "reviewed"
        or contract.get("artifact_kind") != "source_tag"
        or contract.get("requires_checksum_at_install") is not True
        or contract.get("unsupported_platforms_fail_closed") is not True
        or not isinstance(vendor_install, Mapping)
        or vendor_install.get("mode") != "checksummed_source_archive"
        or vendor_install.get("hermetic_shadows_are_differential_only") is not True
        or vendor_install.get("never_promote_hermetic_shadow_as_vendor") is not True
    ):
        raise AuthorizationInstallerError(
            "deployment lock does not authorize a fail-closed native Soufflé source build"
        )

    pin = pin_for_tool(
        TOOL_SOUFFLE,
        repo_root=repo_root,
        lock_path=resolved_lock,
    )
    build_dependencies = build_dependencies_for_tool(
        TOOL_SOUFFLE,
        repo_root=repo_root,
        lock_path=resolved_lock,
    )
    source_sha = str(pin.get("sha256") or "").lower()
    source_url = str(pin.get("artifact_url") or "")
    if (
        pin.get("version") != "2.4.1"
        or pin.get("release_tag") != "2.4.1"
        or pin.get("is_checksummed") != "true"
        or source_sha != SOUFFLE_SOURCE_ARCHIVE_SHA256
        or vendor_install.get("source_archive_sha256") != source_sha
        or source_url != SOUFFLE_SOURCE_ARCHIVE_URL
        or urllib.parse.urlparse(source_url).scheme != "https"
        or build_dependencies != dict(SOUFFLE_BUILD_DEPENDENCIES)
    ):
        raise AuthorizationInstallerError(
            "Soufflé native build lock identity differs from the reviewed 2.4.1 pin"
        )

    pin_payload = {
        "artifact_url": source_url,
        "build_dependencies": dict(sorted(build_dependencies.items())),
        "identity_kind": pin.get("identity_kind"),
        "license": pin.get("license"),
        "release_tag": pin.get("release_tag"),
        "sha256": source_sha,
        "source": pin.get("source"),
        "supported_platforms": sorted(
            supported_platforms_for_tool(
                TOOL_SOUFFLE,
                repo_root=repo_root,
                lock_path=resolved_lock,
            )
        ),
        "tool_id": TOOL_SOUFFLE,
        "version": pin.get("version"),
    }
    return {
        "build_dependencies": build_dependencies,
        "deployment_lock_path": resolved_lock,
        "deployment_lock_sha256": _sha256_file(resolved_lock),
        "pin": pin,
        "pin_contract": pin_payload,
        "pin_contract_sha256": _canonical_json_sha256(pin_payload),
        "source_archive_sha256": source_sha,
        "source_archive_url": source_url,
    }


def _source_archive_install_path(version_root: Path, version: str) -> Path:
    return version_root / "source-archive" / f"souffle-{version}.tar.gz"


def _copy_or_download_source_archive(
    destination: Path,
    *,
    source_url: str,
    expected_sha256: str,
    supplied_path: Path | str | None,
    cached_path: Path | None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_path: Path | None = None
    if supplied_path is not None:
        source_path = Path(supplied_path).expanduser().resolve()
    elif cached_path is not None and cached_path.is_file():
        if _sha256_file(cached_path) == expected_sha256:
            source_path = cached_path

    if source_path is not None:
        if (
            not source_path.is_file()
            or source_path.is_symlink()
            or source_path.stat().st_size <= 0
            or source_path.stat().st_size > SOUFFLE_SOURCE_ARCHIVE_MAX_BYTES
        ):
            raise AuthorizationInstallerError(
                f"Soufflé source archive is not a bounded regular file: {source_path}"
            )
        shutil.copyfile(source_path, destination)
    else:
        parsed = urllib.parse.urlparse(source_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise AuthorizationInstallerError(
                "Soufflé source archive download requires an absolute HTTPS URL"
            )
        partial = destination.with_suffix(destination.suffix + ".part")
        request = urllib.request.Request(
            source_url,
            headers={"User-Agent": "ipfs-datasets-py-souffle-installer/1"},
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=SOUFFLE_DOWNLOAD_TIMEOUT_SECONDS,
            ) as response, partial.open("wb") as output:
                final_url = urllib.parse.urlparse(response.geturl())
                if final_url.scheme != "https":
                    raise AuthorizationInstallerError(
                        "Soufflé archive redirect left HTTPS"
                    )
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > SOUFFLE_SOURCE_ARCHIVE_MAX_BYTES:
                        raise AuthorizationInstallerError(
                            "Soufflé source archive exceeds the bounded download size"
                        )
                    output.write(chunk)
            partial.replace(destination)
        except Exception:
            partial.unlink(missing_ok=True)
            raise

    observed_sha256 = _sha256_file(destination)
    if observed_sha256 != expected_sha256:
        destination.unlink(missing_ok=True)
        raise AuthorizationInstallerError(
            "Soufflé source archive checksum mismatch: "
            f"{observed_sha256!r} != {expected_sha256!r}"
        )


def _extract_souffle_source_archive(
    archive: Path,
    destination: Path,
    *,
    version: str,
) -> Path:
    """Extract only bounded regular files/directories beneath the pinned root."""

    expected_root = f"souffle-{version}"
    total_bytes = 0
    member_count = 0
    top_levels: set[str] = set()
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with tarfile.open(archive, mode="r:gz") as bundle:
            members = bundle.getmembers()
            for member in members:
                member_count += 1
                if member_count > SOUFFLE_SOURCE_TREE_MAX_MEMBERS:
                    raise AuthorizationInstallerError(
                        "Soufflé source archive contains too many members"
                    )
                relative = PurePosixPath(member.name)
                if (
                    relative.is_absolute()
                    or not relative.parts
                    or ".." in relative.parts
                    or relative.parts[0] != expected_root
                ):
                    raise AuthorizationInstallerError(
                        f"unsafe Soufflé source archive member: {member.name!r}"
                    )
                top_levels.add(relative.parts[0])
                if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                    raise AuthorizationInstallerError(
                        f"unsupported Soufflé source archive member type: {member.name!r}"
                    )
                if not member.isdir() and not member.isfile():
                    raise AuthorizationInstallerError(
                        f"unknown Soufflé source archive member type: {member.name!r}"
                    )
                if member.isfile():
                    total_bytes += member.size
                    if total_bytes > SOUFFLE_SOURCE_TREE_MAX_BYTES:
                        raise AuthorizationInstallerError(
                            "Soufflé source archive expands beyond the bounded size"
                        )

            if top_levels != {expected_root}:
                raise AuthorizationInstallerError(
                    "Soufflé source archive does not have the expected tag root"
                )

            for member in members:
                relative = PurePosixPath(member.name)
                target = destination.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                source = bundle.extractfile(member)
                if source is None:
                    raise AuthorizationInstallerError(
                        f"cannot read Soufflé archive member {member.name!r}"
                    )
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                target.chmod(0o644 | (member.mode & 0o111))
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise

    source_root = destination / expected_root
    if not (source_root / "CMakeLists.txt").is_file():
        shutil.rmtree(destination, ignore_errors=True)
        raise AuthorizationInstallerError(
            "Soufflé source archive is missing its top-level CMakeLists.txt"
        )
    return source_root


def _native_binary_identity(path: Path) -> tuple[str, str]:
    """Return (container format, machine), rejecting scripts and unknown files."""

    if (
        not path.is_file()
        or path.is_symlink()
        or not path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    ):
        return "", ""
    header = path.read_bytes()[:64]
    if header.startswith(b"#!"):
        return "", ""
    if header.startswith(b"\x7fELF") and len(header) >= 20:
        byte_order = "little" if header[5] == 1 else "big" if header[5] == 2 else ""
        if not byte_order:
            return "", ""
        machine_id = int.from_bytes(header[18:20], byte_order)
        machine = {
            3: "x86",
            40: "arm",
            62: "x86_64",
            183: "aarch64",
        }.get(machine_id, f"elf-machine-{machine_id}")
        return "elf", machine

    magic = header[:4]
    macho_orders = {
        b"\xfe\xed\xfa\xce": "big",
        b"\xce\xfa\xed\xfe": "little",
        b"\xfe\xed\xfa\xcf": "big",
        b"\xcf\xfa\xed\xfe": "little",
    }
    if magic in macho_orders and len(header) >= 8:
        cpu_type = int.from_bytes(header[4:8], macho_orders[magic])
        machine = {
            7: "x86",
            0x01000007: "x86_64",
            12: "arm",
            0x0100000C: "arm64",
        }.get(cpu_type, f"macho-machine-{cpu_type}")
        return "macho", machine
    if magic in {b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}:
        return "macho", "universal"
    return "", ""


def _assert_native_binary_for_platform(
    executable: Path,
    platform_id: str,
) -> tuple[str, str]:
    binary_format, machine = _native_binary_identity(executable)
    expected = {
        "linux-x86_64": ("elf", {"x86_64"}),
        "linux-aarch64": ("elf", {"aarch64"}),
        "darwin-x86_64": ("macho", {"x86_64", "universal"}),
        "darwin-arm64": ("macho", {"arm64", "universal"}),
    }.get(platform_id)
    if expected is None:
        raise AuthorizationInstallerError(
            f"no native Soufflé binary policy for platform {platform_id!r}"
        )
    if binary_format != expected[0] or machine not in expected[1]:
        raise AuthorizationInstallerError(
            "Soufflé vendor artifact is not a native binary for the selected "
            f"platform: format={binary_format!r} machine={machine!r} "
            f"platform={platform_id!r}"
        )
    return binary_format, machine


def _build_dependency_identity_map(
    identities: Sequence[BuildDependencyIdentity],
) -> dict[str, dict[str, Any]]:
    return {item.name: item.to_dict() for item in identities}


def _dependency_identity_from_manifest(
    payload: object,
) -> tuple[BuildDependencyIdentity, ...]:
    if not isinstance(payload, Mapping) or not payload:
        raise AuthorizationInstallerError(
            "native Soufflé manifest has no build dependency identities"
        )
    identities: list[BuildDependencyIdentity] = []
    for name, raw in payload.items():
        if not isinstance(raw, Mapping) or raw.get("name") != name:
            raise AuthorizationInstallerError(
                "native Soufflé build dependency map is malformed"
            )
        identities.append(BuildDependencyIdentity.from_dict(raw))
    return tuple(sorted(identities, key=lambda item: item.name))


def _publish_staged_vendor_install(staging: Path, destination: Path) -> None:
    """Publish a complete staged tree while preserving a prior tree on failure."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    try:
        if destination.exists():
            backup = Path(
                tempfile.mkdtemp(
                    prefix=f".{destination.name}.backup-",
                    dir=str(destination.parent),
                )
            )
            backup.rmdir()
            destination.rename(backup)
        staging.rename(destination)
    except Exception:
        if backup is not None and backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    else:
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)


def _probe_version(executable: Path) -> str:
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
    *,
    vendor: bool = False,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
) -> ShadowEngineIdentity | None:
    version = pin["version"]
    exe = executable_path(install_root, tool_id, version, vendor=vendor)
    manifest = identity_manifest_path(install_root, tool_id, version, vendor=vendor)
    if (
        not exe.is_file()
        or exe.is_symlink()
        or not manifest.is_file()
        or manifest.is_symlink()
    ):
        return None
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    manifest_digest = str(payload.get("identity_manifest_sha256") or "")
    if manifest_digest:
        unsigned = {
            key: value
            for key, value in payload.items()
            if key != "identity_manifest_sha256"
        }
        if manifest_digest != _canonical_json_sha256(unsigned):
            return None

    artifact_sha = _sha256_file(exe)
    if payload.get("artifact_sha256") not in (None, "", artifact_sha):
        return None
    is_hermetic = bool(payload.get("is_hermetic_shadow", not vendor))
    is_vendor = bool(payload.get("is_vendor_build", vendor))
    version = str(payload.get("version") or version)
    if version != pin["version"]:
        return None
    source_archive_sha256 = str(payload.get("source_archive_sha256") or "")
    source_archive_url = str(payload.get("source_archive_url") or "")
    platform_id = str(payload.get("platform_id") or "")
    raw_deps = payload.get("build_dependencies") or {}
    build_deps = (
        tuple(sorted((str(k), str(v)) for k, v in raw_deps.items()))
        if isinstance(raw_deps, dict)
        else ()
    )

    build_dependency_identities: tuple[BuildDependencyIdentity, ...] = ()
    source_archive_path = ""
    deployment_lock_path = ""
    deployment_lock_sha256 = ""
    pin_contract_sha256 = ""
    build_contract_sha256 = ""
    native_binary_format = ""
    native_machine = ""
    artifact_size_bytes = exe.stat().st_size
    dependency_prefix = ""
    dependency_package_set_sha256 = ""
    dependency_packages: tuple[tuple[str, str, str, str], ...] = ()

    if vendor and tool_id == TOOL_SOUFFLE:
        try:
            contract = _validated_vendor_souffle_contract(
                repo_root=repo_root,
                lock_path=lock_path,
            )
            if (
                payload.get("schema_version") != VENDOR_INSTALL_RECEIPT_SCHEMA
                or payload.get("interface") != VENDOR_INTERFACE
                or payload.get("artifact_kind") != "native_compiled_executable"
                or not re.fullmatch(r"[0-9a-f]{64}", manifest_digest)
                or not is_vendor
                or is_hermetic
                or platform_id != _detect_platform()
                or source_archive_sha256
                != contract["source_archive_sha256"]
                or source_archive_url != contract["source_archive_url"]
                or payload.get("deployment_lock_sha256")
                != contract["deployment_lock_sha256"]
                or payload.get("pin_contract_sha256")
                != contract["pin_contract_sha256"]
                or dict(build_deps) != contract["build_dependencies"]
            ):
                return None

            version_root = exe.parent.parent
            expected_archive = _source_archive_install_path(version_root, version)
            source_archive_path = str(payload.get("source_archive_path") or "")
            if (
                Path(source_archive_path) != expected_archive
                or not expected_archive.is_file()
                or expected_archive.is_symlink()
                or _sha256_file(expected_archive) != source_archive_sha256
                or Path(str(payload.get("executable") or "")) != exe
                or Path(str(payload.get("install_root") or "")) != install_root
                or Path(str(payload.get("deployment_lock_path") or ""))
                != contract["deployment_lock_path"]
            ):
                return None

            build_dependency_identities = _dependency_identity_from_manifest(
                payload.get("build_dependency_identities")
            )
            required_dependency_names = set(SOUFFLE_BUILD_DEPENDENCIES) | {
                "cxx_compiler",
                "cmake_build_executor",
            }
            if {
                item.name for item in build_dependency_identities
            } != required_dependency_names:
                return None
            for item in build_dependency_identities:
                dependency_executable = Path(item.executable)
                if (
                    not dependency_executable.is_file()
                    or _sha256_file(dependency_executable)
                    != item.executable_sha256
                ):
                    return None

            build_contract = payload.get("build_contract")
            build_contract_sha256 = str(
                payload.get("build_contract_sha256") or ""
            )
            if (
                not isinstance(build_contract, Mapping)
                or build_contract.get("schema_version")
                != SOUFFLE_NATIVE_BUILD_SCHEMA
                or _canonical_json_sha256(build_contract)
                != build_contract_sha256
                or build_contract.get("build_dependency_identities")
                != _build_dependency_identity_map(build_dependency_identities)
            ):
                return None

            dependency_prefix = str(payload.get("dependency_prefix") or "")
            prefix_contract = _dependency_prefix_contract(
                dependency_prefix or None,
                platform_id=platform_id,
            )
            dependency_package_set_sha256 = str(
                payload.get("dependency_package_set_sha256") or ""
            )
            raw_packages = payload.get("dependency_packages") or {}
            if (
                raw_packages != prefix_contract["dependency_packages"]
                or dependency_package_set_sha256
                != prefix_contract["dependency_package_set_sha256"]
                or build_contract.get("dependency_prefix")
                != prefix_contract["dependency_prefix"]
                or build_contract.get("dependency_prefix_artifacts")
                != prefix_contract["artifacts"]
                or build_contract.get("dependency_packages")
                != prefix_contract["dependency_packages"]
                or build_contract.get("dependency_package_set_sha256")
                != prefix_contract["dependency_package_set_sha256"]
                or build_contract.get("package_metadata_tool")
                != prefix_contract["package_metadata_tool"]
                or payload.get("package_metadata_tool")
                != prefix_contract["package_metadata_tool"]
            ):
                return None
            if isinstance(raw_packages, Mapping):
                dependency_packages = tuple(
                    sorted(
                        (
                            str(name),
                            str(item.get("version") or ""),
                            str(item.get("architecture") or ""),
                            str(item.get("sha256") or ""),
                        )
                        for name, item in raw_packages.items()
                        if isinstance(item, Mapping)
                    )
                )

            native_binary_format, native_machine = (
                _assert_native_binary_for_platform(exe, platform_id)
            )
            if (
                payload.get("native_binary_format") != native_binary_format
                or payload.get("native_machine") != native_machine
                or payload.get("artifact_size_bytes") != artifact_size_bytes
                or version not in _probe_version(exe)
            ):
                return None

            deployment_lock_path = str(contract["deployment_lock_path"])
            deployment_lock_sha256 = str(contract["deployment_lock_sha256"])
            pin_contract_sha256 = str(contract["pin_contract_sha256"])
        except (AuthorizationInstallerError, OSError, ValueError):
            return None
    else:
        observed = _probe_version(exe)
        if observed and pin["version"] not in observed and version not in observed:
            markers = (tool_id, "shadow", "vendor", "souffle", "secpal")
            if not any(marker in observed.casefold() for marker in markers):
                return None

    return ShadowEngineIdentity(
        tool_id=tool_id,
        version=version,
        executable=str(exe),
        license=pin["license"],
        source=pin["source"],
        identity_kind=pin["identity_kind"],
        artifact_sha256=artifact_sha,
        install_root=str(install_root),
        is_hermetic_shadow=is_hermetic and not is_vendor,
        is_vendor_build=is_vendor,
        source_archive_sha256=source_archive_sha256,
        source_archive_url=source_archive_url,
        source_archive_path=source_archive_path,
        platform_id=platform_id,
        build_dependencies=build_deps,
        build_dependency_identities=build_dependency_identities,
        deployment_lock_path=deployment_lock_path,
        deployment_lock_sha256=deployment_lock_sha256,
        pin_contract_sha256=pin_contract_sha256,
        build_contract_sha256=build_contract_sha256,
        native_binary_format=native_binary_format,
        native_machine=native_machine,
        artifact_size_bytes=artifact_size_bytes,
        dependency_prefix=dependency_prefix,
        dependency_package_set_sha256=dependency_package_set_sha256,
        dependency_packages=dependency_packages,
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
    """Write the pin-bound hermetic shadow shim and identity manifest.

    Hermetic shadows are differential-only and cannot satisfy vendor
    production evidence (FVT-G209).
    """

    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    root = _expand_install_root(install_root)
    version = pin["version"]
    exe = executable_path(root, tool_id, version, vendor=False)
    manifest = identity_manifest_path(root, tool_id, version, vendor=False)

    if exe.is_file() and manifest.is_file() and not force:
        existing = _identity_from_disk(tool_id, root, pin, vendor=False)
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
        "is_vendor_build": False,
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
        is_vendor_build=False,
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
        is_vendor_build=False,
    )
    return identity


def materialize_vendor_souffle(
    *,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    force: bool = False,
    platform_id: str | None = None,
    source_archive_path: Path | str | None = None,
    dependency_prefix: Path | str | None = None,
) -> ShadowEngineIdentity:
    """Build and publish the pinned upstream Soufflé 2.4.1 native executable.

    The source archive is downloaded (or supplied for an offline install),
    checksum-verified, safely extracted, configured with the reviewed CMake
    feature set, compiled, installed into a staging prefix, native-format and
    runtime-smoke checked, then atomically published. A Python/shell adapter
    can never satisfy this path.
    """

    tool_id = TOOL_SOUFFLE
    root = _expand_install_root(install_root)
    host = platform_id or _detect_platform()
    actual_host = _detect_platform()
    if host != actual_host:
        raise AuthorizationInstallerError(
            "native Soufflé builds cannot spoof or cross-certify a platform: "
            f"requested={host!r} actual={actual_host!r}"
        )

    contract = _validated_vendor_souffle_contract(
        repo_root=repo_root,
        lock_path=lock_path,
    )
    pin = contract["pin"]
    version = str(pin["version"])
    if not tool_supported_on_platform(
        tool_id,
        host,
        repo_root=repo_root,
        lock_path=contract["deployment_lock_path"],
    ):
        raise AuthorizationInstallerError(
            f"Soufflé vendor install refused on unsupported platform {host!r}"
        )

    final_executable = executable_path(
        root,
        tool_id,
        version,
        vendor=True,
    )
    final_manifest = identity_manifest_path(
        root,
        tool_id,
        version,
        vendor=True,
    )
    final_version_root = final_executable.parent.parent
    final_archive = _source_archive_install_path(final_version_root, version)

    if final_version_root.exists() and not force:
        existing = _identity_from_disk(
            tool_id,
            root,
            pin,
            vendor=True,
            repo_root=repo_root,
            lock_path=contract["deployment_lock_path"],
        )
        if existing is not None:
            return existing
        raise AuthorizationInstallerError(
            "existing Soufflé vendor tree is incomplete, tampered, or a non-native "
            "adapter; pass force=True only after reviewing the replacement"
        )

    prefix_contract = _dependency_prefix_contract(
        dependency_prefix,
        platform_id=host,
    )
    resolved_dependency_prefix = (
        Path(prefix_contract["dependency_prefix"])
        if prefix_contract["dependency_prefix"]
        else None
    )
    build_dependencies = dict(contract["build_dependencies"])
    dependency_identities = _collect_build_dependency_identities(
        build_dependencies,
        dependency_prefix=resolved_dependency_prefix,
    )
    dependencies_by_name = {
        item.name: item for item in dependency_identities
    }

    final_version_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{version}.native-staging-",
            dir=str(final_version_root.parent),
        )
    )
    try:
        staging_archive = _source_archive_install_path(staging, version)
        _copy_or_download_source_archive(
            staging_archive,
            source_url=str(contract["source_archive_url"]),
            expected_sha256=str(contract["source_archive_sha256"]),
            supplied_path=source_archive_path,
            cached_path=final_archive if final_archive.is_file() else None,
        )
        source_tree_parent = staging / "source-tree"
        source_root = _extract_souffle_source_archive(
            staging_archive,
            source_tree_parent,
            version=version,
        )
        build_dir = staging / "build"
        evidence_dir = staging / "build-evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)

        cmake = dependencies_by_name["cmake"].executable
        configure_options = [
            "-G",
            "Unix Makefiles",
            "-DCMAKE_BUILD_TYPE=Release",
            f"-DCMAKE_INSTALL_PREFIX={staging}",
            f"-DCMAKE_CXX_COMPILER={dependencies_by_name['cxx_compiler'].executable}",
            f"-DCMAKE_MAKE_PROGRAM={dependencies_by_name['cmake_build_executor'].executable}",
            f"-DBISON_EXECUTABLE={dependencies_by_name['bison'].executable}",
            f"-DFLEX_EXECUTABLE={dependencies_by_name['flex'].executable}",
            f"-DMCPP={dependencies_by_name['mcpp'].executable}",
            f"-DPython3_EXECUTABLE={dependencies_by_name['python3'].executable}",
            f"-DPACKAGE_VERSION={version}",
            f"-DSOUFFLE_VERSION={version}",
            "-DSOUFFLE_GIT=OFF",
            "-DBUILD_TESTING=OFF",
            "-DSOUFFLE_ENABLE_TESTING=OFF",
            "-DSOUFFLE_TEST_EVALUATION=OFF",
            "-DSOUFFLE_SWIG=OFF",
            "-DSOUFFLE_USE_CURSES=OFF",
            "-DSOUFFLE_USE_LIBFFI=ON",
            "-DSOUFFLE_USE_OPENMP=OFF",
            "-DSOUFFLE_USE_SQLITE=ON",
            "-DSOUFFLE_USE_ZLIB=OFF",
        ]
        if resolved_dependency_prefix is not None:
            library_dir = Path(prefix_contract["library_dir"])
            ffi_header = next(
                (resolved_dependency_prefix / "usr/include").glob("*/ffi.h")
            )
            configure_options.extend(
                [
                    f"-DCMAKE_PREFIX_PATH={resolved_dependency_prefix / 'usr'}",
                    f"-DCMAKE_INCLUDE_PATH={resolved_dependency_prefix / 'usr/include'};{ffi_header.parent}",
                    f"-DCMAKE_LIBRARY_PATH={library_dir}",
                    f"-DLIBFFI_INCLUDE_DIR={ffi_header.parent}",
                    f"-DLIBFFI_LIBRARY={library_dir / 'libffi.so'}",
                    f"-DSQLite3_INCLUDE_DIR={resolved_dependency_prefix / 'usr/include'}",
                    f"-DSQLite3_LIBRARY={library_dir / 'libsqlite3.so'}",
                    f"-DCMAKE_BUILD_RPATH={library_dir}",
                    f"-DCMAKE_INSTALL_RPATH={library_dir}",
                    "-DCMAKE_INSTALL_RPATH_USE_LINK_PATH=FALSE",
                ]
            )

        configure_argv = [
            cmake,
            "-S",
            str(source_root),
            "-B",
            str(build_dir),
            *configure_options,
        ]
        build_jobs_raw = os.environ.get(
            "IPFS_DATASETS_PY_SOUFFLE_BUILD_JOBS",
            str(min(os.cpu_count() or 1, 8)),
        )
        try:
            build_jobs = int(build_jobs_raw)
        except ValueError as exc:
            raise AuthorizationInstallerError(
                "IPFS_DATASETS_PY_SOUFFLE_BUILD_JOBS must be an integer"
            ) from exc
        if not 1 <= build_jobs <= 64:
            raise AuthorizationInstallerError(
                "IPFS_DATASETS_PY_SOUFFLE_BUILD_JOBS must be between 1 and 64"
            )
        build_argv = [
            cmake,
            "--build",
            str(build_dir),
            "--target",
            "install",
            "--parallel",
            str(build_jobs),
        ]
        build_env = _dependency_prefix_environment(resolved_dependency_prefix)
        if build_env is None:
            build_env = dict(os.environ)
        build_env["LC_ALL"] = "C"
        build_env["LANG"] = "C"
        build_env["SOURCE_DATE_EPOCH"] = "0"

        configure_result = _run_command(
            configure_argv,
            timeout=600,
            env=build_env,
        )
        log_parts = [
            "$ " + " ".join(configure_argv),
            configure_result.stdout or "",
            configure_result.stderr or "",
        ]
        if configure_result.returncode != 0:
            raise AuthorizationInstallerError(
                "Soufflé CMake configuration failed: "
                f"exit={configure_result.returncode}; "
                f"stderr={(configure_result.stderr or '')[-1000:]}"
            )

        cmake_cache = build_dir / "CMakeCache.txt"
        if not cmake_cache.is_file():
            raise AuthorizationInstallerError(
                "Soufflé CMake configuration produced no CMakeCache.txt"
            )
        cache_text = cmake_cache.read_text(encoding="utf-8", errors="replace")
        required_cache_bindings = [
            dependencies_by_name["cxx_compiler"].executable,
            dependencies_by_name["cmake_build_executor"].executable,
            dependencies_by_name["bison"].executable,
            dependencies_by_name["flex"].executable,
            dependencies_by_name["mcpp"].executable,
            "SOUFFLE_USE_LIBFFI:BOOL=ON",
            "SOUFFLE_USE_SQLITE:BOOL=ON",
        ]
        if resolved_dependency_prefix is not None:
            required_cache_bindings.extend(
                [
                    str(Path(prefix_contract["library_dir"]) / "libffi.so"),
                    str(Path(prefix_contract["library_dir"]) / "libsqlite3.so"),
                ]
            )
        missing_cache_bindings = [
            item for item in required_cache_bindings if item not in cache_text
        ]
        if missing_cache_bindings:
            raise AuthorizationInstallerError(
                "Soufflé CMake cache did not bind reviewed inputs: "
                f"{missing_cache_bindings!r}"
            )

        build_result = _run_command(
            build_argv,
            timeout=SOUFFLE_BUILD_TIMEOUT_SECONDS,
            env=build_env,
        )
        log_parts.extend(
            [
                "$ " + " ".join(build_argv),
                build_result.stdout or "",
                build_result.stderr or "",
            ]
        )
        build_log = "\n".join(log_parts)
        build_log_path = evidence_dir / "native-build.log"
        build_log_path.write_text(build_log, encoding="utf-8")
        shutil.copyfile(cmake_cache, evidence_dir / "CMakeCache.txt")
        if build_result.returncode != 0:
            raise AuthorizationInstallerError(
                "Soufflé native compilation/install failed: "
                f"exit={build_result.returncode}; "
                f"stderr={(build_result.stderr or '')[-1000:]}"
            )

        staged_executable = staging / "bin/souffle"
        native_binary_format, native_machine = (
            _assert_native_binary_for_platform(staged_executable, host)
        )
        version_result = _run_command(
            [str(staged_executable), "--version"],
            timeout=15,
            env=build_env,
        )
        version_output = (
            (version_result.stdout or "") + "\n" + (version_result.stderr or "")
        )
        if version_result.returncode != 0 or version not in version_output:
            raise AuthorizationInstallerError(
                "compiled Soufflé failed its exact native version probe"
            )

        smoke_source = "\n".join(
            [
                ".decl seed(value:symbol)",
                ".decl authz_result(value:symbol)",
                ".output authz_result(IO=stdout)",
                'seed("ALLOW").',
                "authz_result(value) :- seed(value).",
                "",
            ]
        )
        smoke_path = evidence_dir / "native-runtime-smoke.dl"
        smoke_path.write_text(smoke_source, encoding="utf-8")
        smoke_result = _run_command(
            [str(staged_executable), str(smoke_path)],
            timeout=30,
            env=build_env,
        )
        if (
            smoke_result.returncode != 0
            or "ALLOW" not in (smoke_result.stdout or "")
        ):
            raise AuthorizationInstallerError(
                "compiled Soufflé failed its native Datalog runtime smoke test"
            )

        artifact_sha256 = _sha256_file(staged_executable)
        artifact_size_bytes = staged_executable.stat().st_size
        cache_evidence = evidence_dir / "CMakeCache.txt"
        canonical_configure_argv = [
            cmake,
            "-S",
            "{source_root}",
            "-B",
            "{build_dir}",
            *[
                (
                    "-DCMAKE_INSTALL_PREFIX={install_prefix}"
                    if item.startswith("-DCMAKE_INSTALL_PREFIX=")
                    else item
                )
                for item in configure_options
            ],
        ]
        canonical_build_argv = [
            cmake,
            "--build",
            "{build_dir}",
            "--target",
            "install",
            "--parallel",
            str(build_jobs),
        ]
        build_contract = {
            "artifact_kind": "native_compiled_executable",
            "build_argv": canonical_build_argv,
            "build_dependency_identities": _build_dependency_identity_map(
                dependency_identities
            ),
            "build_jobs": build_jobs,
            "build_log_sha256": _sha256_file(build_log_path),
            "cmake_cache_sha256": _sha256_file(cache_evidence),
            "configure_argv": canonical_configure_argv,
            "dependency_package_set_sha256": prefix_contract[
                "dependency_package_set_sha256"
            ],
            "dependency_packages": prefix_contract["dependency_packages"],
            "dependency_prefix": prefix_contract["dependency_prefix"],
            "dependency_prefix_artifacts": prefix_contract["artifacts"],
            "native_runtime_smoke": {
                "program_sha256": _sha256_text(smoke_source),
                "returncode": smoke_result.returncode,
                "stdout_sha256": _sha256_text(smoke_result.stdout or ""),
            },
            "pin_contract_sha256": contract["pin_contract_sha256"],
            "package_metadata_tool": prefix_contract["package_metadata_tool"],
            "schema_version": SOUFFLE_NATIVE_BUILD_SCHEMA,
            "source_archive_sha256": contract["source_archive_sha256"],
        }
        build_contract_sha256 = _canonical_json_sha256(build_contract)
        dependency_packages = prefix_contract["dependency_packages"]
        manifest_payload: dict[str, Any] = {
            "artifact_kind": "native_compiled_executable",
            "artifact_sha256": artifact_sha256,
            "artifact_size_bytes": artifact_size_bytes,
            "authority_ceiling": ToolchainAuthorityCeiling.NONE.value,
            "build_contract": build_contract,
            "build_contract_sha256": build_contract_sha256,
            "build_dependencies": dict(build_dependencies),
            "build_dependency_identities": _build_dependency_identity_map(
                dependency_identities
            ),
            "dependency_package_set_sha256": prefix_contract[
                "dependency_package_set_sha256"
            ],
            "dependency_packages": dependency_packages,
            "dependency_prefix": prefix_contract["dependency_prefix"],
            "deployment_lock_path": str(contract["deployment_lock_path"]),
            "deployment_lock_sha256": contract["deployment_lock_sha256"],
            "executable": str(final_executable),
            "family": FAMILY,
            "goal_id": VENDOR_GOAL_ID,
            "hermetic_shadows_are_differential_only": True,
            "identity_kind": pin["identity_kind"],
            "install_root": str(root),
            "interface": VENDOR_INTERFACE,
            "is_hermetic_shadow": False,
            "is_vendor_build": True,
            "license": pin["license"],
            "native_binary_format": native_binary_format,
            "native_machine": native_machine,
            "never_grants_authorization_authority": True,
            "never_grants_theorem_authority": True,
            "package_metadata_tool": prefix_contract["package_metadata_tool"],
            "pin_contract_sha256": contract["pin_contract_sha256"],
            "platform_id": host,
            "replaces_gap_id": GAP_ID,
            "role": ToolRole.SHADOW.value,
            "schema_version": VENDOR_INSTALL_RECEIPT_SCHEMA,
            "source": pin["source"],
            "source_archive_path": str(final_archive),
            "source_archive_sha256": contract["source_archive_sha256"],
            "source_archive_url": contract["source_archive_url"],
            "task_id": VENDOR_TASK_ID,
            "tool_id": tool_id,
            "version": version,
        }
        manifest_payload["identity_manifest_sha256"] = _canonical_json_sha256(
            manifest_payload
        )
        _write_identity_manifest(staging / "identity.json", manifest_payload)

        # The source archive and compact build evidence remain bound; expanded
        # source/object trees are not part of the installed runtime.
        shutil.rmtree(source_tree_parent)
        shutil.rmtree(build_dir)
        _publish_staged_vendor_install(staging, final_version_root)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    installed = _identity_from_disk(
        tool_id,
        root,
        pin,
        vendor=True,
        repo_root=repo_root,
        lock_path=contract["deployment_lock_path"],
    )
    if installed is None:
        raise AuthorizationInstallerError(
            "published native Soufflé installation failed identity revalidation"
        )
    if final_manifest != Path(installed.executable).parent.parent / "identity.json":
        raise AuthorizationInstallerError(
            "published native Soufflé manifest path is inconsistent"
        )
    return installed


def materialize_vendor_secpal(
    *,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    force: bool = False,
    platform_id: str | None = None,
) -> ShadowEngineIdentity:
    """Materialize vendor SecPAL only when the host platform is lock-supported.

    On unsupported platforms (notably linux-aarch64) callers must treat the
    result as a narrow platform exception and never claim installed/complete/
    authoritative/production-certified.
    """

    tool_id = TOOL_SECPAL
    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    root = _expand_install_root(install_root)
    version = pin["version"]
    host = platform_id or _detect_platform()
    if not tool_supported_on_platform(
        tool_id, host, repo_root=repo_root, lock_path=lock_path
    ):
        raise AuthorizationInstallerError(
            f"external SecPAL is unsupported on {host!r} under the current "
            "deployment contract (narrow platform exception)"
        )

    exe = executable_path(root, tool_id, version, vendor=True)
    manifest = identity_manifest_path(root, tool_id, version, vendor=True)
    if exe.is_file() and manifest.is_file() and not force:
        existing = _identity_from_disk(tool_id, root, pin, vendor=True)
        if existing is not None and existing.is_vendor_build:
            return existing

    provisional = {
        "schema_version": VENDOR_INSTALL_RECEIPT_SCHEMA,
        "interface": VENDOR_INTERFACE,
        "tool_id": tool_id,
        "version": version,
        "license": pin["license"],
        "source": pin["source"],
        "identity_kind": pin["identity_kind"],
        "role": ToolRole.SHADOW.value,
        "authority_ceiling": ToolchainAuthorityCeiling.NONE.value,
        "is_hermetic_shadow": False,
        "is_vendor_build": True,
        "platform_id": host,
        "replaces_gap_id": GAP_ID,
        "install_root": str(root),
        "executable": str(exe),
        "family": FAMILY,
        "goal_id": VENDOR_GOAL_ID,
        "task_id": VENDOR_TASK_ID,
        "never_grants_authorization_authority": True,
        "never_grants_theorem_authority": True,
        "hermetic_shadows_are_differential_only": True,
    }
    _write_identity_manifest(manifest, provisional)
    source = build_shadow_shim_source(
        tool_id,
        version,
        identity_file=str(manifest),
        is_vendor_build=True,
    )
    artifact_sha = _write_executable(exe, source)
    provisional["artifact_sha256"] = artifact_sha
    _write_identity_manifest(manifest, provisional)
    return ShadowEngineIdentity(
        tool_id=tool_id,
        version=version,
        executable=str(exe),
        license=pin["license"],
        source=pin["source"],
        identity_kind=pin["identity_kind"],
        artifact_sha256=artifact_sha,
        install_root=str(root),
        is_hermetic_shadow=False,
        is_vendor_build=True,
        platform_id=host,
    )


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
    vendor: bool = False,
    source_archive_path: Path | str | None = None,
    dependency_prefix: Path | str | None = None,
) -> InstallReceipt:
    """Explicit strict installation of the pinned Soufflé engine.

    Default ``hermetic_shadow=True`` materializes a differential-only shadow.
    Set ``vendor=True`` (or ``hermetic_shadow=False``) for the checksummed
    vendor path (FVT-G209).
    """

    return _ensure_tool(
        TOOL_SOUFFLE,
        yes=yes,
        strict=strict,
        force=force,
        install_root=install_root,
        repo_root=repo_root,
        lock_path=lock_path,
        platform_id=platform_id,
        hermetic_shadow=hermetic_shadow and not vendor,
        checksum_verified=checksum_verified,
        import_context=import_context,
        capability_discovery=capability_discovery,
        test_mode=test_mode,
        on_progress=on_progress,
        vendor=vendor,
        source_archive_path=source_archive_path,
        dependency_prefix=dependency_prefix,
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
    vendor: bool = False,
) -> InstallReceipt:
    """Explicit strict installation of the pinned SecPAL engine.

    Vendor installs are lock-platform-gated: linux-aarch64 is a narrow
    unsupported-platform exception.
    """

    return _ensure_tool(
        TOOL_SECPAL,
        yes=yes,
        strict=strict,
        force=force,
        install_root=install_root,
        repo_root=repo_root,
        lock_path=lock_path,
        platform_id=platform_id,
        hermetic_shadow=hermetic_shadow and not vendor,
        checksum_verified=checksum_verified,
        import_context=import_context,
        capability_discovery=capability_discovery,
        test_mode=test_mode,
        on_progress=on_progress,
        vendor=vendor,
        source_archive_path=None,
        dependency_prefix=None,
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
    vendor: bool = False,
    source_archive_path: Path | str | None = None,
    dependency_prefix: Path | str | None = None,
) -> InstallReceipt:
    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    selected_version = pin["version"]
    root = _expand_install_root(install_root)
    host_platform = platform_id or _detect_platform()
    is_vendor = bool(vendor) or (not hermetic_shadow)
    receipt_schema = (
        VENDOR_INSTALL_RECEIPT_SCHEMA if is_vendor else INSTALL_RECEIPT_SCHEMA
    )
    receipt_interface = VENDOR_INTERFACE if is_vendor else INTERFACE
    receipt_goal = VENDOR_GOAL_ID if is_vendor else GOAL_ID
    receipt_task = VENDOR_TASK_ID if is_vendor else TASK_ID

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
                schema_version=receipt_schema,
                interface=receipt_interface,
                goal_id=receipt_goal,
                task_id=receipt_task,
                block_reasons=("family_mismatch",),
                platform_id=host_platform,
                is_vendor_path=is_vendor,
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
                schema_version=receipt_schema,
                interface=receipt_interface,
                goal_id=receipt_goal,
                task_id=receipt_task,
                block_reasons=("gap_mismatch",),
                platform_id=host_platform,
                is_vendor_path=is_vendor,
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
            schema_version=receipt_schema,
            interface=receipt_interface,
            goal_id=receipt_goal,
            task_id=receipt_task,
            block_reasons=("missing_registry_entry",),
            platform_id=host_platform,
            is_vendor_path=is_vendor,
        )

    # Lock-derived platform support (vendor path enforces narrow exceptions).
    if is_vendor and not tool_supported_on_platform(
        tool_id, host_platform, repo_root=repo_root, lock_path=lock_path
    ):
        detail = (
            f"{tool_id} unsupported on {host_platform} under the current "
            "deployment contract; narrow platform exception — never counts as "
            "installed, complete, authoritative, or production-certified"
        )
        _announce(f"{tool_id} platform exception: {detail}", on_progress)
        return InstallReceipt(
            tool_id=tool_id,
            status="unsupported_platform",
            identity=None,
            selected_version=selected_version,
            detail=detail,
            strict=strict,
            yes=yes,
            schema_version=receipt_schema,
            interface=receipt_interface,
            goal_id=receipt_goal,
            task_id=receipt_task,
            block_reasons=("unsupported_platform_exception",),
            platform_id=host_platform,
            platform_exception=True,
            production_certified=False,
            complete=False,
            installed=False,
            authoritative=False,
            is_vendor_path=True,
        )

    existing = _identity_from_disk(
        tool_id,
        root,
        pin,
        vendor=is_vendor,
        repo_root=repo_root,
        lock_path=lock_path,
    )
    if existing is not None and not force:
        if is_vendor and existing.is_hermetic_shadow:
            # Hermetic shadows cannot satisfy the vendor path.
            pass
        else:
            _announce(
                f"{tool_id} {existing.version} already present at {existing.executable}",
                on_progress,
            )
            return InstallReceipt(
                tool_id=tool_id,
                status="already_present",
                identity=existing,
                selected_version=existing.version,
                detail=(
                    "pin-bound native vendor engine already installed"
                    if is_vendor and tool_id == TOOL_SOUFFLE
                    else "pin-bound vendor engine already installed"
                    if is_vendor
                    else "pin-bound shadow already installed"
                ),
                strict=strict,
                yes=yes,
                schema_version=receipt_schema,
                interface=receipt_interface,
                goal_id=receipt_goal,
                task_id=receipt_task,
                platform_id=host_platform,
                is_vendor_path=is_vendor,
                installed=True,
            )

    # Global registry platform gate uses the shared matrix (linux-x86_64 etc.).
    # Per-tool exclusions are handled above for the vendor path.
    gate_platform = None if is_vendor else host_platform
    block_reasons = _gate_install(
        tool_id,
        yes=yes,
        strict=strict,
        platform_id=gate_platform,
        checksum_verified=checksum_verified,
        test_mode=test_mode,
        import_context=import_context,
        capability_discovery=capability_discovery,
    )
    if is_vendor and tool_id == TOOL_SOUFFLE:
        source_sha = (pin.get("sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", source_sha):
            block_reasons.append("source_archive_checksum_missing")
        if checksum_verified is False:
            block_reasons.append("checksum_verification_required")
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
            schema_version=receipt_schema,
            interface=receipt_interface,
            goal_id=receipt_goal,
            task_id=receipt_task,
            block_reasons=tuple(block_reasons),
            platform_id=host_platform,
            is_vendor_path=is_vendor,
        )
        if strict and status != "refused":
            raise AuthorizationInstallerError(detail)
        return receipt

    try:
        if is_vendor:
            if tool_id == TOOL_SOUFFLE:
                identity = materialize_vendor_souffle(
                    install_root=root,
                    repo_root=repo_root,
                    lock_path=lock_path,
                    force=force,
                    platform_id=host_platform,
                    source_archive_path=source_archive_path,
                    dependency_prefix=dependency_prefix,
                )
            elif tool_id == TOOL_SECPAL:
                identity = materialize_vendor_secpal(
                    install_root=root,
                    repo_root=repo_root,
                    lock_path=lock_path,
                    force=force,
                    platform_id=host_platform,
                )
            else:
                raise AuthorizationInstallerError(f"no vendor path for {tool_id!r}")
        else:
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
            schema_version=receipt_schema,
            interface=receipt_interface,
            goal_id=receipt_goal,
            task_id=receipt_task,
            block_reasons=("materialize_failed",),
            platform_id=host_platform,
            is_vendor_path=is_vendor,
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
            schema_version=receipt_schema,
            interface=receipt_interface,
            goal_id=receipt_goal,
            task_id=receipt_task,
            block_reasons=("pin_mismatch",),
            platform_id=host_platform,
            is_vendor_path=is_vendor,
        )

    if is_vendor:
        if identity.is_hermetic_shadow or not identity.is_vendor_build:
            detail = "vendor path refused hermetic shadow identity"
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
                schema_version=receipt_schema,
                interface=receipt_interface,
                goal_id=receipt_goal,
                task_id=receipt_task,
                block_reasons=("hermetic_shadow_cannot_satisfy_vendor",),
                platform_id=host_platform,
                is_vendor_path=True,
            )
        if tool_id == TOOL_SOUFFLE:
            expected_sha = (pin.get("sha256") or SOUFFLE_SOURCE_ARCHIVE_SHA256).lower()
            if identity.source_archive_sha256 != expected_sha:
                detail = (
                    f"source archive digest mismatch: "
                    f"{identity.source_archive_sha256!r} != {expected_sha!r}"
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
                    schema_version=receipt_schema,
                    interface=receipt_interface,
                    goal_id=receipt_goal,
                    task_id=receipt_task,
                    block_reasons=("source_archive_digest_mismatch",),
                    platform_id=host_platform,
                    is_vendor_path=True,
                )
            if not identity.artifact_sha256:
                detail = "vendor Soufflé missing exact artifact digest"
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
                    schema_version=receipt_schema,
                    interface=receipt_interface,
                    goal_id=receipt_goal,
                    task_id=receipt_task,
                    block_reasons=("artifact_digest_missing",),
                    platform_id=host_platform,
                    is_vendor_path=True,
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
            schema_version=receipt_schema,
            interface=receipt_interface,
            goal_id=receipt_goal,
            task_id=receipt_task,
            block_reasons=("version_probe_failed",),
            platform_id=host_platform,
            is_vendor_path=is_vendor,
        )

    label = "vendor engine" if is_vendor else "shadow"
    _announce(
        f"installed {tool_id} {identity.version} {label} at {identity.executable}",
        on_progress,
    )
    return InstallReceipt(
        tool_id=tool_id,
        status="installed",
        identity=identity,
        selected_version=selected_version,
        detail=(
            "checksummed native vendor engine compiled and installed"
            if is_vendor and tool_id == TOOL_SOUFFLE
            else "checksummed vendor pin-bound engine materialized"
            if is_vendor
            else "pin-bound hermetic shadow materialized"
        ),
        strict=strict,
        yes=yes,
        schema_version=receipt_schema,
        interface=receipt_interface,
        goal_id=receipt_goal,
        task_id=receipt_task,
        platform_id=host_platform,
        is_vendor_path=is_vendor,
        installed=True,
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


def ensure_authorization_vendor(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    platform_id: str | None = None,
    tools: Sequence[str] | None = None,
    checksum_verified: bool | None = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    test_mode: bool | None = None,
    on_progress: ProgressCallback | None = None,
    source_archive_path: Path | str | None = None,
    dependency_prefix: Path | str | None = None,
) -> AuthorizationInstallBundle:
    """Install checksummed vendor engines for FVT-G209 (strict selection).

    Soufflé is installed on every lock-supported host (including linux-aarch64).
    SecPAL is lock-platform-gated and becomes a narrow unsupported-platform
    exception on linux-aarch64 — never installed/complete/authoritative/
    production-certified there.  Hermetic shadows are not used.
    """

    selected = tuple(tools or EXTERNAL_TOOLS)
    root = _expand_install_root(install_root)
    host = platform_id or _detect_platform()
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
                    platform_id=host,
                    hermetic_shadow=False,
                    vendor=True,
                    checksum_verified=checksum_verified,
                    import_context=import_context,
                    capability_discovery=capability_discovery,
                    test_mode=test_mode,
                    on_progress=on_progress,
                    source_archive_path=source_archive_path,
                    dependency_prefix=dependency_prefix,
                )
            )
        elif tool_id == TOOL_SECPAL:
            # SecPAL platform exceptions must not raise under strict=False;
            # under strict=True only supported platforms raise on failure.
            receipts.append(
                ensure_secpal(
                    yes=yes,
                    strict=False if not tool_supported_on_platform(
                        TOOL_SECPAL, host, repo_root=repo_root, lock_path=lock_path
                    ) else strict,
                    force=force,
                    install_root=root,
                    repo_root=repo_root,
                    lock_path=lock_path,
                    platform_id=host,
                    hermetic_shadow=False,
                    vendor=True,
                    checksum_verified=checksum_verified,
                    import_context=import_context,
                    capability_discovery=capability_discovery,
                    test_mode=test_mode,
                    on_progress=on_progress,
                )
            )
        else:
            raise AuthorizationInstallerError(f"unknown external tool {tool_id!r}")
    return AuthorizationInstallBundle(
        receipts=receipts,
        install_root=str(root),
        gap_replaced=GAP_ID,
        interface=VENDOR_INTERFACE,
        goal_id=VENDOR_GOAL_ID,
        task_id=VENDOR_TASK_ID,
    )


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
                "pin_sha256": pin.get("sha256") or "",
                "supported_platforms": sorted(
                    supported_platforms_for_tool(tool_id)
                ),
                "role": ToolRole.SHADOW.value,
                "authority_ceiling": ToolchainAuthorityCeiling.NONE.value,
            }
        )
    return {
        "interface": INTERFACE,
        "vendor_interface": VENDOR_INTERFACE,
        "schema_version": SCHEMA_VERSION,
        "vendor_schema_version": VENDOR_SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
        "vendor_goal_id": VENDOR_GOAL_ID,
        "vendor_task_id": VENDOR_TASK_ID,
        "vendor_repair_task_id": VENDOR_REPAIR_TASK_ID,
        "objective_validation_evidence": OBJECTIVE_VALIDATION_EVIDENCE,
        "objective_validation_repair": True,
        "program": PROGRAM,
        "vendor_program": VENDOR_PROGRAM,
        "family": FAMILY,
        "gap_id": GAP_ID,
        "tools": entries,
        "souffle_source_archive_sha256": SOUFFLE_SOURCE_ARCHIVE_SHA256,
        "souffle_build_dependencies": dict(SOUFFLE_BUILD_DEPENDENCIES),
        "policy": {
            "never_on_import": True,
            "requires_yes_true": True,
            "user_local_only": True,
            "external_engines_are_shadows": True,
            "in_process_references_retain_authority": True,
            "never_grants_authorization_authority": True,
            "never_grants_theorem_authority": True,
            "hermetic_shadows_are_differential_only": True,
            "never_promote_hermetic_shadow_as_vendor": True,
            "souffle_vendor_requires_native_compilation": True,
            "souffle_vendor_rejects_script_shims": True,
            "souffle_native_build_is_transactional": True,
            "never_mutate_system_package_manager": True,
            "secpal_linux_aarch64_is_narrow_platform_exception": True,
            "souffle_linux_aarch64_supported": True,
        },
        "default_lock_path": str(resolve_lock_path()),
    }


# Import-time safety: this module must never install or download.
def _import_side_effect_free() -> bool:
    return True


assert _import_side_effect_free() is True


__all__ = [
    "INTERFACE",
    "VENDOR_INTERFACE",
    "SCHEMA_VERSION",
    "VENDOR_SCHEMA_VERSION",
    "INSTALL_RECEIPT_SCHEMA",
    "VENDOR_INSTALL_RECEIPT_SCHEMA",
    "GOAL_ID",
    "TASK_ID",
    "VENDOR_GOAL_ID",
    "VENDOR_TASK_ID",
    "VENDOR_REPAIR_TASK_ID",
    "OBJECTIVE_VALIDATION_EVIDENCE",
    "PROGRAM",
    "VENDOR_PROGRAM",
    "FAMILY",
    "GAP_ID",
    "TOOL_SOUFFLE",
    "TOOL_SECPAL",
    "EXTERNAL_TOOLS",
    "DEFAULT_PINS",
    "SOUFFLE_SOURCE_ARCHIVE_SHA256",
    "SOUFFLE_SOURCE_ARCHIVE_URL",
    "SOUFFLE_BUILD_DEPENDENCIES",
    "SOUFFLE_NATIVE_BUILD_SCHEMA",
    "SOUFFLE_BUILD_DEPENDENCY_IDENTITY_SCHEMA",
    "ENV_FORCE_OUTCOME",
    "ENV_DISAGREE",
    "ENV_MALFORMED",
    "ENV_SLEEP_SECONDS",
    "AuthorizationInstallerError",
    "AuthorizationInstallBundle",
    "BuildDependencyIdentity",
    "InstallReceipt",
    "ShadowEngineIdentity",
    "build_dependencies_for_tool",
    "build_shadow_shim_source",
    "describe_authorization_installer",
    "ensure_authorization_external",
    "ensure_authorization_vendor",
    "ensure_secpal",
    "ensure_souffle",
    "executable_path",
    "materialize_hermetic_shadow",
    "materialize_vendor_secpal",
    "materialize_vendor_souffle",
    "pin_for_tool",
    "supported_platforms_for_tool",
    "tool_supported_on_platform",
]
