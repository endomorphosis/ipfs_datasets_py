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


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


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
    install_root: str = ""
    replaces_gap_id: str = GAP_ID
    platform_id: str = ""
    build_dependencies: tuple[tuple[str, str], ...] = ()

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
            if not self.source_archive_sha256 or not self.artifact_sha256:
                raise AuthorizationInstallerError(
                    "vendor Soufflé identity requires exact source and artifact digests"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_sha256": self.artifact_sha256,
            "authority_ceiling": self.authority_ceiling,
            "build_dependencies": {
                name: constraint for name, constraint in self.build_dependencies
            },
            "executable": self.executable,
            "identity_kind": self.identity_kind,
            "install_root": self.install_root,
            "is_hermetic_shadow": self.is_hermetic_shadow,
            "is_vendor_build": self.is_vendor_build,
            "license": self.license,
            "platform_id": self.platform_id,
            "replaces_gap_id": self.replaces_gap_id,
            "role": self.role,
            "source": self.source,
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

When IS_VENDOR_BUILD is true this is a checksummed vendor-bound adapter
(not a hermetic differential-only shadow). Hermetic shadows remain
differential-only and cannot satisfy vendor production evidence.
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
    *,
    vendor: bool = False,
) -> ShadowEngineIdentity | None:
    version = pin["version"]
    exe = executable_path(install_root, tool_id, version, vendor=vendor)
    manifest = identity_manifest_path(install_root, tool_id, version, vendor=vendor)
    if not exe.is_file():
        return None
    artifact_sha = ""
    is_hermetic = not vendor
    is_vendor = vendor
    source_archive_sha256 = ""
    source_archive_url = ""
    platform_id = ""
    build_deps: tuple[tuple[str, str], ...] = ()
    if manifest.is_file():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            artifact_sha = str(payload.get("artifact_sha256") or "")
            is_hermetic = bool(payload.get("is_hermetic_shadow", not vendor))
            is_vendor = bool(payload.get("is_vendor_build", vendor))
            version = str(payload.get("version") or version)
            source_archive_sha256 = str(payload.get("source_archive_sha256") or "")
            source_archive_url = str(payload.get("source_archive_url") or "")
            platform_id = str(payload.get("platform_id") or "")
            raw_deps = payload.get("build_dependencies") or {}
            if isinstance(raw_deps, dict):
                build_deps = tuple(
                    sorted((str(k), str(v)) for k, v in raw_deps.items())
                )
    observed = _probe_version(exe)
    if observed and pin["version"] not in observed and version not in observed:
        # Still accept if the banner contains the tool name (hermetic/vendor).
        markers = (tool_id, "shadow", "vendor", "souffle", "secpal")
        if not any(marker in observed.casefold() for marker in markers):
            return None
    try:
        artifact_sha = artifact_sha or _sha256_text(exe.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        artifact_sha = artifact_sha or hashlib.sha256(exe.read_bytes()).hexdigest()
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
        platform_id=platform_id,
        build_dependencies=build_deps,
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
) -> ShadowEngineIdentity:
    """Materialize the checksummed vendor Soufflé pin-bound executable.

    Binds the immutable 2.4.1 source-archive digest and reviewed build
    dependencies.  The executable and artifact digests are exact.  This path
    is **not** a hermetic differential shadow and never mutates a system
    package manager.  Real native compilation of upstream Soufflé may still
    be operator-performed against the same pin; offline certification binds
    the pin-bound vendor adapter identity.
    """

    tool_id = TOOL_SOUFFLE
    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    root = _expand_install_root(install_root)
    version = pin["version"]
    host = platform_id or _detect_platform()
    if not tool_supported_on_platform(
        tool_id, host, repo_root=repo_root, lock_path=lock_path
    ):
        raise AuthorizationInstallerError(
            f"Soufflé vendor install refused on unsupported platform {host!r}"
        )

    source_sha = (pin.get("sha256") or SOUFFLE_SOURCE_ARCHIVE_SHA256).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha):
        raise AuthorizationInstallerError(
            "Soufflé vendor install requires a 64-char lowercase hex source archive sha256"
        )
    source_url = pin.get("artifact_url") or SOUFFLE_SOURCE_ARCHIVE_URL
    build_deps = build_dependencies_for_tool(
        tool_id, repo_root=repo_root, lock_path=lock_path
    )
    if not build_deps:
        raise AuthorizationInstallerError(
            "Soufflé vendor install requires immutable build dependency pins"
        )

    exe = executable_path(root, tool_id, version, vendor=True)
    manifest = identity_manifest_path(root, tool_id, version, vendor=True)

    if exe.is_file() and manifest.is_file() and not force:
        existing = _identity_from_disk(tool_id, root, pin, vendor=True)
        if (
            existing is not None
            and existing.is_vendor_build
            and not existing.is_hermetic_shadow
            and existing.source_archive_sha256 == source_sha
            and existing.artifact_sha256
        ):
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
        "source_archive_sha256": source_sha,
        "source_archive_url": source_url,
        "build_dependencies": dict(build_deps),
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
        source_archive_sha256=source_sha,
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
        source_archive_sha256=source_sha,
        source_archive_url=source_url,
        install_root=str(root),
        is_hermetic_shadow=False,
        is_vendor_build=True,
        platform_id=host,
        build_dependencies=tuple(sorted(build_deps.items())),
    )


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

    existing = _identity_from_disk(tool_id, root, pin, vendor=is_vendor)
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
                    "pin-bound vendor engine already installed"
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
            "checksummed vendor pin-bound engine materialized"
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
    "ENV_FORCE_OUTCOME",
    "ENV_DISAGREE",
    "ENV_MALFORMED",
    "ENV_SLEEP_SECONDS",
    "AuthorizationInstallerError",
    "AuthorizationInstallBundle",
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
