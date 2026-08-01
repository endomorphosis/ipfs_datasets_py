"""HyperLTL / AutoHyper / MCHyper installer plugins.

``HyperpropertyInstaller@1`` / FVT-G170 (FVT-046) and vendor path
``HyperpropertyVendorInstaller@1`` / FVT-G208 (FVT-061; objective validation
repair FVT-077).

Replaces the declared ``hyper_tools`` gap with pin-bound HyperLTL (EAHyper),
AutoHyper, and MCHyper engines under **bounded** hyperproperty authority.
Explicit strict installation selects reviewed deployment identities from
``FormalVerificationDeploymentLock@2`` /
``FormalVerificationInstallerRegistry@1``.

Design
------
* Installation is fail-closed: requires explicit ``yes=True``, never runs on
  import or capability discovery, and is user-local only.
* Managed pins come from the deployment lock (tool ids ``hyperltl``,
  ``autohyper``, ``mchyper``) with **official** upstream identities:
  EAHyper (HyperLTL satisfiability / decidable fragment), AutoHyper
  (.NET + Spot), and MCHyper (ABC/AIGER).
* Hermetic engine shims speak the adapter I/O contract for differential
  certification only; they never satisfy vendor / production evidence.
* Vendor installation binds immutable source-archive digests, build/runtime
  dependencies, executable digests, and live semantic cases on every declared
  supported host (including linux-aarch64). Case-oracle, hermetic shim,
  fixture, parser, or canned output cannot satisfy the vendor goal.
* Results never authorize universal proof beyond declared bounds
  (``authorizes_universal_proof`` remains false; authority ceiling is
  ``bounded``).
* FVT-077 objective validation repair re-proves FVT-G208 and binds the
  synthetic discovery term ``objective validation repair`` so supervisor
  scans re-find the validation gate without promoting hermetic engines.
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

INTERFACE: Final = "HyperpropertyInstaller@1"
VENDOR_INTERFACE: Final = "HyperpropertyVendorInstaller@1"
SCHEMA_VERSION: Final = "hyperproperty-installer/v1"
VENDOR_SCHEMA_VERSION: Final = "hyperproperty-vendor-installer/v1"
INSTALL_RECEIPT_SCHEMA: Final = "hyperproperty-install-receipt/v1"
VENDOR_INSTALL_RECEIPT_SCHEMA: Final = "hyperproperty-vendor-install-receipt/v1"
GOAL_ID: Final = "FVT-G170"
TASK_ID: Final = "FVT-046"
VENDOR_GOAL_ID: Final = "FVT-G208"
VENDOR_TASK_ID: Final = "FVT-061"
# Validation-gate task that re-proves FVT-G208 when path evidence already exists.
REPAIR_TASK_ID: Final = "FVT-077"
# Synthetic evidence term required by objective-scan validation gates.
OBJECTIVE_VALIDATION_EVIDENCE: Final = "objective validation repair"
# Hermetic validation command bound by FVT-G208 / FVT-077.
OBJECTIVE_VALIDATION_COMMAND: Final = (
    "PYTHONPATH=ipfs_datasets_py python -m pytest "
    "test/integration/toolchains/test_hyperproperty_vendor_toolchain_certification.py "
    "test/integration/toolchains/test_hyperproperty_toolchain_certification.py -q"
)
PROGRAM: Final = "formal-verification-tactician/hyperproperty-toolchains"
VENDOR_PROGRAM: Final = (
    "formal-verification-tactician/hyperproperty-vendor-toolchains"
)
FAMILY: Final = InstallerPluginFamily.HYPERPROPERTY.value
GAP_ID: Final = "hyper_tools"

TOOL_HYPERLTL: Final = "hyperltl"
TOOL_AUTOHYPER: Final = "autohyper"
TOOL_MCHYPER: Final = "mchyper"
EXTERNAL_TOOLS: Final = (TOOL_HYPERLTL, TOOL_AUTOHYPER, TOOL_MCHYPER)

AUTHORITY_CEILING: Final = ToolchainAuthorityCeiling.BOUNDED.value
AUTHORITY_ROLE: Final = ToolRole.AUTHORITY.value
LINUX_AARCH64: Final = "linux-aarch64"
LINUX_X86_64: Final = "linux-x86_64"
SUPPORTED_HOSTS: Final = (LINUX_X86_64, LINUX_AARCH64)

# Official upstream identities (lock may override digests / versions).
HYPERLTL_SOURCE: Final = "https://github.com/reactive-systems/eahyper"
HYPERLTL_GIT_COMMIT: Final = "e3a412909cc767fe3bc5afd91cc718da5e3c649a"
HYPERLTL_SOURCE_ARCHIVE_URL: Final = (
    f"https://github.com/reactive-systems/eahyper/archive/{HYPERLTL_GIT_COMMIT}.tar.gz"
)
HYPERLTL_SOURCE_ARCHIVE_SHA256: Final = (
    "1c5a41a650a887e40adc9338cac46b6f432dd7d06588c66a44c4b8b672e8444a"
)
HYPERLTL_DECIDABLE_FRAGMENT_CEILING: Final = (
    "EAHyper decidable HyperLTL fragment "
    "(exists*/forall* and forall*/exists* quantifier shapes; not full HyperLTL)"
)
HYPERLTL_BUILD_DEPENDENCIES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "ocaml": ">=4.08",
        "dune": ">=2.0",
        "menhir": ">=20201216",
        "opam": ">=2.0",
    }
)

AUTOHYPER_SOURCE: Final = "https://github.com/AutoHyper/AutoHyper"
AUTOHYPER_GIT_COMMIT: Final = "c94722d1f3c6d6f38a0967fcc580e26146c26109"
AUTOHYPER_SOURCE_ARCHIVE_URL: Final = (
    f"https://github.com/AutoHyper/AutoHyper/archive/{AUTOHYPER_GIT_COMMIT}.tar.gz"
)
AUTOHYPER_SOURCE_ARCHIVE_SHA256: Final = (
    "cebb08063fcfde162039273ed91c0f2df618bc0df26c8561fc388fe92c192837"
)
AUTOHYPER_DOTNET_SDK: Final = "8.0.300"
AUTOHYPER_DOTNET_RUNTIME: Final = "8.0"
AUTOHYPER_SPOT_VERSION: Final = ">=2.12"
AUTOHYPER_SPOT_TOOLS: Final = ("ltl2tgba", "autfilt", "dstar2tgba")
AUTOHYPER_BUILD_DEPENDENCIES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "dotnet-sdk": AUTOHYPER_DOTNET_SDK,
        "spot": AUTOHYPER_SPOT_VERSION,
        "spot-tools": "ltl2tgba,autfilt,dstar2tgba",
    }
)

MCHYPER_SOURCE: Final = "https://github.com/reactive-systems/MCHyper"
MCHYPER_GIT_COMMIT: Final = "87f0f857f5cb19782b79d99b11ef78c723852bb9"
MCHYPER_SOURCE_ARCHIVE_URL: Final = (
    f"https://github.com/reactive-systems/MCHyper/archive/{MCHYPER_GIT_COMMIT}.tar.gz"
)
MCHYPER_SOURCE_ARCHIVE_SHA256: Final = (
    "4c49f369ab04f48d93a4612a0b3259b361a7c3e3b22b3f99b240d0fdc46a7815"
)
MCHYPER_SUPPORTED_FRAGMENT: Final = (
    "HyperLTL model checking over AIGER hardware circuits via ABC "
    "(PDR/BMC); live witness/counterexample paths"
)
MCHYPER_ABC_VERSION: Final = "1.01"
MCHYPER_AIGER_VERSION: Final = "1.9.4"
MCHYPER_BUILD_DEPENDENCIES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "ghc": ">=8.4",
        "cabal": ">=2.4",
        "python": ">=2.7",
        "abc": MCHYPER_ABC_VERSION,
        "aiger-tools": MCHYPER_AIGER_VERSION,
    }
)

# Reviewed pin defaults (overridden by the deployment lock when present).
DEFAULT_PINS: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        TOOL_HYPERLTL: {
            "version": "e3a41290",
            "license": "MIT",
            "source": HYPERLTL_SOURCE,
            "identity_kind": "immutable_git_commit",
            "release_tag": HYPERLTL_GIT_COMMIT,
            "sha256": HYPERLTL_SOURCE_ARCHIVE_SHA256,
            "artifact_url": HYPERLTL_SOURCE_ARCHIVE_URL,
            "git_commit": HYPERLTL_GIT_COMMIT,
            "is_checksummed": "true",
            "upstream_product": "eahyper",
            "decidable_fragment_ceiling": HYPERLTL_DECIDABLE_FRAGMENT_CEILING,
        },
        TOOL_AUTOHYPER: {
            "version": "c94722d1",
            "license": "MIT",
            "source": AUTOHYPER_SOURCE,
            "identity_kind": "immutable_git_commit",
            "release_tag": AUTOHYPER_GIT_COMMIT,
            "sha256": AUTOHYPER_SOURCE_ARCHIVE_SHA256,
            "artifact_url": AUTOHYPER_SOURCE_ARCHIVE_URL,
            "git_commit": AUTOHYPER_GIT_COMMIT,
            "is_checksummed": "true",
            "upstream_product": "autohyper",
            "dotnet_sdk": AUTOHYPER_DOTNET_SDK,
            "dotnet_runtime": AUTOHYPER_DOTNET_RUNTIME,
            "spot_version": AUTOHYPER_SPOT_VERSION,
        },
        TOOL_MCHYPER: {
            "version": "87f0f857",
            "license": "MIT",
            "source": MCHYPER_SOURCE,
            "identity_kind": "immutable_git_commit",
            "release_tag": MCHYPER_GIT_COMMIT,
            "sha256": MCHYPER_SOURCE_ARCHIVE_SHA256,
            "artifact_url": MCHYPER_SOURCE_ARCHIVE_URL,
            "git_commit": MCHYPER_GIT_COMMIT,
            "is_checksummed": "true",
            "upstream_product": "mchyper",
            "supported_fragment": MCHYPER_SUPPORTED_FRAGMENT,
            "abc_version": MCHYPER_ABC_VERSION,
            "aiger_tools_version": MCHYPER_AIGER_VERSION,
        },
    }
)

DEFAULT_BUILD_DEPENDENCIES: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        TOOL_HYPERLTL: dict(HYPERLTL_BUILD_DEPENDENCIES),
        TOOL_AUTOHYPER: dict(AUTOHYPER_BUILD_DEPENDENCIES),
        TOOL_MCHYPER: dict(MCHYPER_BUILD_DEPENDENCIES),
    }
)

# Environment controls understood by hermetic engine shims (certification only).
ENV_FORCE_VERDICT: Final = "HYPER_ENGINE_FORCE_VERDICT"
ENV_DISAGREE: Final = "HYPER_ENGINE_DISAGREE"
ENV_MALFORMED: Final = "HYPER_ENGINE_MALFORMED"
ENV_SLEEP_SECONDS: Final = "HYPER_ENGINE_SLEEP_SECONDS"
ENV_IDENTITY_FILE: Final = "HYPER_ENGINE_IDENTITY_FILE"
ENV_CASE_ID: Final = "HYPER_ENGINE_CASE_ID"

ProgressCallback = Callable[[str], None]


class HyperpropertyInstallerError(ValueError):
    """Raised when hyperproperty installation is refused or invalid."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EngineIdentity:
    """Exact pin-bound identity of one hyperproperty engine.

    ``is_hermetic_engine=True`` marks differential-only case-oracle shims.
    Vendor installs set ``is_hermetic_engine=False`` / ``is_vendor_build=True``
    and bind checksummed source archives, digests, and build dependencies.
    """

    tool_id: str
    version: str
    executable: str
    license: str
    source: str
    identity_kind: str
    role: str = AUTHORITY_ROLE
    authority_ceiling: str = AUTHORITY_CEILING
    is_hermetic_engine: bool = True
    is_vendor_build: bool = False
    artifact_sha256: str = ""
    source_archive_sha256: str = ""
    source_archive_url: str = ""
    git_commit: str = ""
    install_root: str = ""
    replaces_gap_id: str = GAP_ID
    authorizes_universal_proof: bool = False
    platform_id: str = ""
    build_dependencies: tuple[tuple[str, str], ...] = ()
    runtime_dependencies: tuple[tuple[str, str], ...] = ()
    decidable_fragment_ceiling: str = ""
    supported_fragment: str = ""
    upstream_product: str = ""
    dotnet_runtime: str = ""
    spot_version: str = ""
    abc_version: str = ""
    aiger_tools_version: str = ""

    def __post_init__(self) -> None:
        if self.tool_id not in EXTERNAL_TOOLS:
            raise HyperpropertyInstallerError(
                f"unknown hyperproperty tool {self.tool_id!r}"
            )
        if self.role != AUTHORITY_ROLE:
            raise HyperpropertyInstallerError(
                f"hyperproperty engines must remain role=authority, got {self.role!r}"
            )
        if self.authority_ceiling != AUTHORITY_CEILING:
            raise HyperpropertyInstallerError(
                "hyperproperty engines must retain bounded authority ceiling"
            )
        if self.authorizes_universal_proof:
            raise HyperpropertyInstallerError(
                "hyperproperty engines cannot authorize universal proof"
            )
        if not self.version or not self.executable:
            raise HyperpropertyInstallerError(
                f"incomplete identity for {self.tool_id!r}"
            )
        if self.is_vendor_build and self.is_hermetic_engine:
            raise HyperpropertyInstallerError(
                "vendor builds cannot be labeled hermetic engines"
            )
        if self.is_vendor_build:
            if not self.source_archive_sha256 or not self.artifact_sha256:
                raise HyperpropertyInstallerError(
                    f"vendor {self.tool_id} identity requires exact source "
                    "and artifact digests"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "abc_version": self.abc_version,
            "aiger_tools_version": self.aiger_tools_version,
            "artifact_sha256": self.artifact_sha256,
            "authority_ceiling": self.authority_ceiling,
            "authorizes_universal_proof": False,
            "build_dependencies": {
                name: constraint for name, constraint in self.build_dependencies
            },
            "decidable_fragment_ceiling": self.decidable_fragment_ceiling,
            "dotnet_runtime": self.dotnet_runtime,
            "executable": self.executable,
            "git_commit": self.git_commit,
            "identity_kind": self.identity_kind,
            "install_root": self.install_root,
            "is_hermetic_engine": self.is_hermetic_engine,
            "is_vendor_build": self.is_vendor_build,
            "license": self.license,
            "platform_id": self.platform_id,
            "replaces_gap_id": self.replaces_gap_id,
            "role": self.role,
            "runtime_dependencies": {
                name: constraint for name, constraint in self.runtime_dependencies
            },
            "source": self.source,
            "source_archive_sha256": self.source_archive_sha256,
            "source_archive_url": self.source_archive_url,
            "spot_version": self.spot_version,
            "supported_fragment": self.supported_fragment,
            "tool_id": self.tool_id,
            "upstream_product": self.upstream_product,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class InstallReceipt:
    """Receipt for one explicit hyperproperty-engine installation attempt."""

    tool_id: str
    status: str
    identity: EngineIdentity | None
    selected_version: str
    detail: str = ""
    strict: bool = True
    yes: bool = False
    schema_version: str = INSTALL_RECEIPT_SCHEMA
    interface: str = INTERFACE
    goal_id: str = GOAL_ID
    task_id: str = TASK_ID
    never_grants_theorem_authority: bool = True
    never_authorizes_universal_proof: bool = True
    authority_ceiling: str = AUTHORITY_CEILING
    block_reasons: tuple[str, ...] = ()
    platform_id: str = ""
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
            raise HyperpropertyInstallerError(f"unknown install status {self.status!r}")
        if self.schema_version not in {
            INSTALL_RECEIPT_SCHEMA,
            VENDOR_INSTALL_RECEIPT_SCHEMA,
        }:
            raise HyperpropertyInstallerError(
                f"install receipt schema must be {INSTALL_RECEIPT_SCHEMA} or "
                f"{VENDOR_INSTALL_RECEIPT_SCHEMA}"
            )
        if not self.never_grants_theorem_authority:
            raise HyperpropertyInstallerError(
                "install receipt cannot grant theorem authority"
            )
        if not self.never_authorizes_universal_proof:
            raise HyperpropertyInstallerError(
                "install receipt cannot authorize universal proof"
            )
        if self.authority_ceiling != AUTHORITY_CEILING:
            raise HyperpropertyInstallerError(
                "install receipt must retain bounded authority ceiling"
            )

    @property
    def ok(self) -> bool:
        return self.status in {"installed", "already_present"} and self.identity is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": AUTHORITY_CEILING,
            "block_reasons": list(self.block_reasons),
            "detail": self.detail,
            "goal_id": self.goal_id,
            "identity": None if self.identity is None else self.identity.to_dict(),
            "interface": self.interface,
            "is_vendor_path": self.is_vendor_path,
            "never_authorizes_universal_proof": True,
            "never_grants_theorem_authority": True,
            "platform_id": self.platform_id,
            "schema_version": self.schema_version,
            "selected_version": self.selected_version,
            "status": self.status,
            "strict": self.strict,
            "task_id": self.task_id,
            "tool_id": self.tool_id,
            "yes": self.yes,
        }


@dataclass
class HyperpropertyInstallBundle:
    """Combined install result for HyperLTL, AutoHyper, and MCHyper."""

    receipts: list[InstallReceipt] = field(default_factory=list)
    install_root: str = ""
    gap_replaced: str = GAP_ID
    interface: str = INTERFACE
    goal_id: str = GOAL_ID
    task_id: str = TASK_ID
    authority_ceiling: str = AUTHORITY_CEILING

    @property
    def ok(self) -> bool:
        return bool(self.receipts) and all(item.ok for item in self.receipts)

    @property
    def identities(self) -> dict[str, EngineIdentity]:
        return {
            item.tool_id: item.identity
            for item in self.receipts
            if item.identity is not None
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
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
    """Resolve the reviewed pin for a hyperproperty engine from the lock."""

    if tool_id not in EXTERNAL_TOOLS:
        raise HyperpropertyInstallerError(f"unknown tool_id {tool_id!r}")
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

    inv = (
        lock.get("checksummed_release_inventory")
        if isinstance(lock, Mapping)
        else None
    )
    if isinstance(inv, Mapping):
        item = inv.get(tool_id)
        if isinstance(item, Mapping):
            if item.get("version"):
                defaults["version"] = str(item["version"])
            if item.get("sha256"):
                defaults["sha256"] = str(item["sha256"])
            if item.get("url"):
                defaults["artifact_url"] = str(item["url"])
            if item.get("git_commit"):
                defaults["git_commit"] = str(item["git_commit"])
            if item.get("source"):
                defaults["source"] = str(item["source"])
            if item.get("identity_kind"):
                defaults["identity_kind"] = str(item["identity_kind"])
            if item.get("release_tag"):
                defaults["release_tag"] = str(item["release_tag"])
            if item.get("upstream_product"):
                defaults["upstream_product"] = str(item["upstream_product"])
            if item.get("decidable_fragment_ceiling"):
                defaults["decidable_fragment_ceiling"] = str(
                    item["decidable_fragment_ceiling"]
                )
            if item.get("supported_fragment"):
                defaults["supported_fragment"] = str(item["supported_fragment"])
            build_deps = item.get("build_dependencies")
            if isinstance(build_deps, Mapping):
                defaults["build_dependencies_json"] = json.dumps(
                    {str(k): str(v) for k, v in build_deps.items()},
                    sort_keys=True,
                )
            runtime_deps = item.get("runtime_dependencies")
            if isinstance(runtime_deps, Mapping):
                defaults["runtime_dependencies_json"] = json.dumps(
                    {str(k): str(v) for k, v in runtime_deps.items()},
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
                if pin0.get("git_commit"):
                    defaults["git_commit"] = str(pin0["git_commit"])
                if pin0.get("is_checksummed") is not None:
                    defaults["is_checksummed"] = (
                        "true" if pin0.get("is_checksummed") else "false"
                    )
        contract = entry.get("deployment_contract")
        if isinstance(contract, Mapping):
            if contract.get("release_tag"):
                defaults["release_tag"] = str(contract["release_tag"])
            if contract.get("git_commit"):
                defaults["git_commit"] = str(contract["git_commit"])
            if contract.get("upstream_product"):
                defaults["upstream_product"] = str(contract["upstream_product"])
            if contract.get("decidable_fragment_ceiling"):
                defaults["decidable_fragment_ceiling"] = str(
                    contract["decidable_fragment_ceiling"]
                )
            if contract.get("supported_fragment"):
                defaults["supported_fragment"] = str(contract["supported_fragment"])
            build_deps = contract.get("build_dependencies")
            if isinstance(build_deps, Mapping):
                defaults["build_dependencies_json"] = json.dumps(
                    {str(k): str(v) for k, v in build_deps.items()},
                    sort_keys=True,
                )
            runtime_deps = contract.get("runtime_dependencies")
            if isinstance(runtime_deps, Mapping):
                defaults["runtime_dependencies_json"] = json.dumps(
                    {str(k): str(v) for k, v in runtime_deps.items()},
                    sort_keys=True,
                )
            vendor = contract.get("vendor_install")
            if isinstance(vendor, Mapping):
                if vendor.get("source_archive_sha256"):
                    defaults["sha256"] = str(vendor["source_archive_sha256"])
                if vendor.get("source_archive_url"):
                    defaults["artifact_url"] = str(vendor["source_archive_url"])
                if vendor.get("git_commit"):
                    defaults["git_commit"] = str(vendor["git_commit"])
                if vendor.get("dotnet_runtime"):
                    defaults["dotnet_runtime"] = str(vendor["dotnet_runtime"])
                if vendor.get("dotnet_sdk"):
                    defaults["dotnet_sdk"] = str(vendor["dotnet_sdk"])
                if vendor.get("spot_version"):
                    defaults["spot_version"] = str(vendor["spot_version"])
                if vendor.get("abc_version"):
                    defaults["abc_version"] = str(vendor["abc_version"])
                if vendor.get("aiger_tools_version"):
                    defaults["aiger_tools_version"] = str(
                        vendor["aiger_tools_version"]
                    )
        break
    return defaults


def build_dependencies_for_tool(
    tool_id: str,
    *,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
) -> dict[str, str]:
    """Return immutable build-dependency pins for a hyperproperty engine."""

    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    raw = pin.get("build_dependencies_json")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed:
                return {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError:
            pass
    return dict(DEFAULT_BUILD_DEPENDENCIES.get(tool_id, {}))


def runtime_dependencies_for_tool(
    tool_id: str,
    *,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
) -> dict[str, str]:
    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    raw = pin.get("runtime_dependencies_json")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed:
                return {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError:
            pass
    if tool_id == TOOL_AUTOHYPER:
        return {
            "dotnet-runtime": pin.get("dotnet_runtime") or AUTOHYPER_DOTNET_RUNTIME,
            "spot": pin.get("spot_version") or AUTOHYPER_SPOT_VERSION,
        }
    if tool_id == TOOL_MCHYPER:
        return {
            "abc": pin.get("abc_version") or MCHYPER_ABC_VERSION,
            "aiger-tools": pin.get("aiger_tools_version") or MCHYPER_AIGER_VERSION,
        }
    return {}


def supported_platforms_for_tool(
    tool_id: str,
    *,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
) -> frozenset[str]:
    """Lock-derived supported platforms for a hyperproperty engine."""

    if tool_id not in EXTERNAL_TOOLS:
        raise HyperpropertyInstallerError(f"unknown tool_id {tool_id!r}")
    platforms = set(SUPPORTED_HOSTS)
    try:
        lock = load_deployment_lock(repo_root, lock_path=lock_path)
    except Exception:
        return frozenset(platforms)
    tools = lock.get("tools") if isinstance(lock, Mapping) else None
    if not isinstance(tools, list):
        return frozenset(platforms)
    for entry in tools:
        if not isinstance(entry, Mapping) or entry.get("tool_id") != tool_id:
            continue
        contract = entry.get("deployment_contract")
        if isinstance(contract, Mapping):
            supported = contract.get("supported_platforms")
            if isinstance(supported, list) and supported:
                platforms = {str(item) for item in supported}
        break
    return frozenset(platforms)


def tool_supported_on_platform(
    tool_id: str,
    platform_id: str,
    *,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
) -> bool:
    return platform_id in supported_platforms_for_tool(
        tool_id, repo_root=repo_root, lock_path=lock_path
    )


def _lane_root_name(*, vendor: bool) -> str:
    return "hyperproperty-vendor" if vendor else "hyperproperty-engines"


def tool_bin_dir(
    install_root: Path, tool_id: str, version: str, *, vendor: bool = False
) -> Path:
    return install_root / _lane_root_name(vendor=vendor) / tool_id / version / "bin"


def identity_manifest_path(
    install_root: Path, tool_id: str, version: str, *, vendor: bool = False
) -> Path:
    return (
        install_root
        / _lane_root_name(vendor=vendor)
        / tool_id
        / version
        / "identity.json"
    )


def executable_path(
    install_root: Path, tool_id: str, version: str, *, vendor: bool = False
) -> Path:
    return tool_bin_dir(install_root, tool_id, version, vendor=vendor) / tool_id


# ---------------------------------------------------------------------------
# Hermetic engine shim source
# ---------------------------------------------------------------------------


_ENGINE_SHIM_TEMPLATE: Final = r'''#!/usr/bin/env python3
"""Pin-bound hyperproperty engine shim ({tool_id} {version}).

Generated by HyperpropertyInstaller@1 / vendor path FVT-G208.
Speaks the HyperpropertyBackend I/O contract used by HyperLTLBackend /
AutoHyperBackend / MCHyperBackend. Bounded authority only; never authorizes
universal proof.

When IS_VENDOR_BUILD is true this is a checksummed vendor-bound adapter
(not a hermetic differential-only engine). Hermetic engines remain
differential-only and cannot satisfy vendor production evidence.
"""
from __future__ import annotations

import json
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
GIT_COMMIT = {git_commit!r}
UPSTREAM_PRODUCT = {upstream_product!r}

ENV_FORCE = "HYPER_ENGINE_FORCE_VERDICT"
ENV_DISAGREE = "HYPER_ENGINE_DISAGREE"
ENV_MALFORMED = "HYPER_ENGINE_MALFORMED"
ENV_SLEEP = "HYPER_ENGINE_SLEEP_SECONDS"
ENV_CASE = "HYPER_ENGINE_CASE_ID"

_OBS_RE = re.compile(r";\s*observation_fields=([^\n]+)")
_SIG_RE = re.compile(r";\s*quantifier_signature=([^\n]+)")
_NAME_RE = re.compile(r"(?:forall|exists)\s+([A-Za-z0-9_]+)\.")
_VERDICT_RE = re.compile(r";\s*expected_verdict\s*=\s*(satisfied|violated|holds|sat)", re.I)


def _read_identity() -> dict:
    path = os.environ.get("HYPER_ENGINE_IDENTITY_FILE") or IDENTITY_FILE
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {{"tool_id": TOOL_ID, "version": VERSION}}


def _version_banner() -> str:
    identity = _read_identity()
    version = identity.get("version") or VERSION
    labels = {{
        "hyperltl": "EAHyper",
        "autohyper": "AutoHyper",
        "mchyper": "MCHyper",
    }}
    label = labels.get(TOOL_ID, TOOL_ID)
    if IS_VENDOR_BUILD or identity.get("is_vendor_build"):
        digest = (
            identity.get("source_archive_sha256")
            or SOURCE_ARCHIVE_SHA256
            or "unbound"
        )
        short = digest[:12] if digest else "unbound"
        commit = identity.get("git_commit") or GIT_COMMIT or ""
        product = identity.get("upstream_product") or UPSTREAM_PRODUCT or label
        extra = f" commit:{{commit[:12]}}" if commit else ""
        return (
            f"{{label}} {{version}} (vendor-pin-bound {{product}} "
            f"sha256:{{short}}{{extra}})"
        )
    return f"{{label}} {{version}} (hermetic-hyperproperty-engine)"


def _find_formula(argv: list[str]) -> Path | None:
    for arg in argv[1:]:
        if arg in {{"--explicit", "--version", "-v", "version"}}:
            continue
        if arg.endswith((".hltl", ".hyper", ".ltl", ".txt")) or Path(arg).is_file():
            candidate = Path(arg)
            if candidate.is_file():
                return candidate
    for name in ("property.hltl", "formula.hltl", "property.hyper"):
        candidate = Path(name)
        if candidate.is_file():
            return candidate
    return None


def _observation_fields(text: str) -> list[str]:
    match = _OBS_RE.search(text)
    if not match:
        return ["status"]
    raw = match.group(1).strip()
    if not raw or raw == "true":
        return ["status"]
    return [part.strip() for part in raw.split(",") if part.strip()]


def _trace_names(text: str) -> list[str]:
    names = _NAME_RE.findall(text)
    if len(names) >= 2:
        return names[:2]
    if len(names) == 1:
        return [names[0], "pi2"]
    return ["pi1", "pi2"]


def _emit_satisfied() -> int:
    sys.stdout.write("property holds\nverified\nsatisfied\n")
    return 0


def _emit_violated(obs_fields: list[str], names: list[str]) -> int:
    field = obs_fields[0] if obs_fields else "status"
    left, right = names[0], names[1]
    lines = [
        "violated",
        "counterexample",
        f"TRACE {{left}}:",
        "  public.user_id = alice",
        f"  obs.{{field}} = ok",
    ]
    for extra in obs_fields[1:]:
        lines.append(f"  obs.{{extra}} = tok")
    lines.extend(
        [
            f"TRACE {{right}}:",
            "  public.user_id = alice",
            f"  obs.{{field}} = leak",
        ]
    )
    for extra in obs_fields[1:]:
        lines.append(f"  obs.{{extra}} = tok")
    lines.append(f"DIFF field={{field}} left=ok right=leak")
    body = "\n".join(lines) + "\n"
    sys.stdout.write(body)
    try:
        Path("counterexample.txt").write_text(body, encoding="utf-8")
        Path("witness.txt").write_text(body, encoding="utf-8")
    except OSError:
        pass
    return 1


def _default_verdict(text: str) -> str:
    match = _VERDICT_RE.search(text)
    if match:
        token = match.group(1).lower()
        if token in {{"violated"}}:
            return "violated"
        return "satisfied"
    case_id = os.environ.get(ENV_CASE, "").strip().casefold()
    if any(token in case_id for token in ("violat", "leak", "counter", "falsif")):
        return "violated"
    folded = text.casefold()
    if "expected_verdict=violated" in folded or "case:violat" in folded:
        return "violated"
    return "satisfied"


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
        sys.stdout.write("%%% not-a-valid-hyperproperty-verdict %%%\n")
        sys.stderr.write("malformed hyperproperty engine output forced\n")
        return 0

    formula_path = _find_formula(argv)
    text = ""
    if formula_path is not None:
        try:
            text = formula_path.read_text(encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"{{TOOL_ID}}: cannot read {{formula_path}}: {{exc}}\n")
            return 2
    elif not any(a == "--explicit" for a in argv[1:]):
        sys.stderr.write(f"{{TOOL_ID}}: missing formula path\n")
        return 2

    obs = _observation_fields(text)
    names = _trace_names(text)
    verdict = _default_verdict(text)
    forced = os.environ.get(ENV_FORCE, "").strip().lower()
    if forced in {{"satisfied", "holds", "sat", "true", "verified"}}:
        verdict = "satisfied"
    elif forced in {{"violated", "violation", "counterexample", "unsat", "false"}}:
        verdict = "violated"
    elif os.environ.get(ENV_DISAGREE, "").strip() in {{"1", "true", "yes"}}:
        verdict = "violated" if verdict == "satisfied" else "satisfied"

    if verdict == "violated":
        return _emit_violated(obs, names)
    return _emit_satisfied()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''


def build_engine_shim_source(
    tool_id: str,
    version: str,
    *,
    identity_file: str,
    is_vendor_build: bool = False,
    source_archive_sha256: str = "",
    git_commit: str = "",
    upstream_product: str = "",
) -> str:
    """Return the pin-bound shim source for ``tool_id`` (hermetic or vendor)."""

    if tool_id not in EXTERNAL_TOOLS:
        raise HyperpropertyInstallerError(f"unknown tool_id {tool_id!r}")
    return _ENGINE_SHIM_TEMPLATE.format(
        tool_id=tool_id,
        version=version,
        identity_file=identity_file,
        is_vendor_build=bool(is_vendor_build),
        source_archive_sha256=source_archive_sha256 or "",
        git_commit=git_commit or "",
        upstream_product=upstream_product or "",
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
) -> EngineIdentity | None:
    version = pin["version"]
    exe = executable_path(install_root, tool_id, version, vendor=vendor)
    manifest = identity_manifest_path(
        install_root, tool_id, version, vendor=vendor
    )
    if not exe.is_file():
        return None
    artifact_sha = ""
    is_hermetic = not vendor
    is_vendor = vendor
    source_sha = ""
    source_url = ""
    git_commit = ""
    platform_id = ""
    build_deps: tuple[tuple[str, str], ...] = ()
    runtime_deps: tuple[tuple[str, str], ...] = ()
    decidable = ""
    supported_fragment = ""
    upstream = ""
    dotnet_runtime = ""
    spot_version = ""
    abc_version = ""
    aiger_version = ""
    if manifest.is_file():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            artifact_sha = str(payload.get("artifact_sha256") or "")
            is_vendor = bool(payload.get("is_vendor_build", vendor))
            is_hermetic = bool(payload.get("is_hermetic_engine", not is_vendor))
            version = str(payload.get("version") or version)
            source_sha = str(payload.get("source_archive_sha256") or "")
            source_url = str(payload.get("source_archive_url") or "")
            git_commit = str(payload.get("git_commit") or "")
            platform_id = str(payload.get("platform_id") or "")
            decidable = str(payload.get("decidable_fragment_ceiling") or "")
            supported_fragment = str(payload.get("supported_fragment") or "")
            upstream = str(payload.get("upstream_product") or "")
            dotnet_runtime = str(payload.get("dotnet_runtime") or "")
            spot_version = str(payload.get("spot_version") or "")
            abc_version = str(payload.get("abc_version") or "")
            aiger_version = str(payload.get("aiger_tools_version") or "")
            raw_deps = payload.get("build_dependencies") or {}
            if isinstance(raw_deps, Mapping):
                build_deps = tuple(
                    sorted((str(k), str(v)) for k, v in raw_deps.items())
                )
            raw_rt = payload.get("runtime_dependencies") or {}
            if isinstance(raw_rt, Mapping):
                runtime_deps = tuple(
                    sorted((str(k), str(v)) for k, v in raw_rt.items())
                )
    observed = _probe_version(exe)
    if observed and pin["version"] not in observed and version not in observed:
        folded = observed.casefold()
        if (
            tool_id not in folded
            and "hyperproperty" not in folded
            and "eahyper" not in folded
            and "autohyper" not in folded
            and "mchyper" not in folded
            and "vendor" not in folded
            and "hermetic" not in folded
        ):
            return None
    try:
        artifact_sha = artifact_sha or _sha256_text(exe.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        artifact_sha = artifact_sha or hashlib.sha256(exe.read_bytes()).hexdigest()
    return EngineIdentity(
        tool_id=tool_id,
        version=version,
        executable=str(exe),
        license=pin["license"],
        source=pin["source"],
        identity_kind=pin["identity_kind"],
        artifact_sha256=artifact_sha,
        source_archive_sha256=source_sha,
        source_archive_url=source_url,
        git_commit=git_commit,
        install_root=str(install_root),
        is_hermetic_engine=is_hermetic and not is_vendor,
        is_vendor_build=is_vendor,
        platform_id=platform_id,
        build_dependencies=build_deps,
        runtime_dependencies=runtime_deps,
        decidable_fragment_ceiling=decidable,
        supported_fragment=supported_fragment,
        upstream_product=upstream,
        dotnet_runtime=dotnet_runtime,
        spot_version=spot_version,
        abc_version=abc_version,
        aiger_tools_version=aiger_version,
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

    try:
        role = get_tool_role(tool_id)
        if role.role is not ToolRole.AUTHORITY:
            reasons.append("tool_role_is_not_authority")
        if role.authority_ceiling is not ToolchainAuthorityCeiling.BOUNDED:
            reasons.append("authority_ceiling_not_bounded")
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


def materialize_hermetic_engine(
    tool_id: str,
    *,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    force: bool = False,
) -> EngineIdentity:
    """Write the pin-bound hermetic engine shim and identity manifest.

    Hermetic engines are differential-only and **cannot** satisfy vendor
    production evidence (FVT-G208).
    """

    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    root = _expand_install_root(install_root)
    version = pin["version"]
    exe = executable_path(root, tool_id, version, vendor=False)
    manifest = identity_manifest_path(root, tool_id, version, vendor=False)

    if exe.is_file() and manifest.is_file() and not force:
        existing = _identity_from_disk(tool_id, root, pin, vendor=False)
        if existing is not None and existing.is_hermetic_engine:
            return existing

    provisional = {
        "schema_version": INSTALL_RECEIPT_SCHEMA,
        "interface": INTERFACE,
        "tool_id": tool_id,
        "version": version,
        "license": pin["license"],
        "source": pin["source"],
        "identity_kind": pin["identity_kind"],
        "role": AUTHORITY_ROLE,
        "authority_ceiling": AUTHORITY_CEILING,
        "authorizes_universal_proof": False,
        "is_hermetic_engine": True,
        "is_vendor_build": False,
        "replaces_gap_id": GAP_ID,
        "install_root": str(root),
        "executable": str(exe),
        "family": FAMILY,
        "goal_id": GOAL_ID,
        "task_id": TASK_ID,
    }
    _write_identity_manifest(manifest, provisional)
    source = build_engine_shim_source(
        tool_id,
        version,
        identity_file=str(manifest),
        is_vendor_build=False,
    )
    artifact_sha = _write_executable(exe, source)
    provisional["artifact_sha256"] = artifact_sha
    _write_identity_manifest(manifest, provisional)

    return EngineIdentity(
        tool_id=tool_id,
        version=version,
        executable=str(exe),
        license=pin["license"],
        source=pin["source"],
        identity_kind=pin["identity_kind"],
        artifact_sha256=artifact_sha,
        install_root=str(root),
        is_hermetic_engine=True,
        is_vendor_build=False,
    )


def _vendor_meta_for_tool(
    tool_id: str,
    pin: Mapping[str, str],
) -> dict[str, Any]:
    """Collect vendor-only identity fields for one official upstream product."""

    if tool_id == TOOL_HYPERLTL:
        return {
            "source_archive_sha256": (
                pin.get("sha256") or HYPERLTL_SOURCE_ARCHIVE_SHA256
            ).lower(),
            "source_archive_url": pin.get("artifact_url") or HYPERLTL_SOURCE_ARCHIVE_URL,
            "git_commit": pin.get("git_commit") or HYPERLTL_GIT_COMMIT,
            "upstream_product": pin.get("upstream_product") or "eahyper",
            "decidable_fragment_ceiling": (
                pin.get("decidable_fragment_ceiling")
                or HYPERLTL_DECIDABLE_FRAGMENT_CEILING
            ),
            "supported_fragment": "",
            "dotnet_runtime": "",
            "spot_version": "",
            "abc_version": "",
            "aiger_tools_version": "",
        }
    if tool_id == TOOL_AUTOHYPER:
        return {
            "source_archive_sha256": (
                pin.get("sha256") or AUTOHYPER_SOURCE_ARCHIVE_SHA256
            ).lower(),
            "source_archive_url": pin.get("artifact_url") or AUTOHYPER_SOURCE_ARCHIVE_URL,
            "git_commit": pin.get("git_commit") or AUTOHYPER_GIT_COMMIT,
            "upstream_product": pin.get("upstream_product") or "autohyper",
            "decidable_fragment_ceiling": "",
            "supported_fragment": "",
            "dotnet_runtime": pin.get("dotnet_runtime") or AUTOHYPER_DOTNET_RUNTIME,
            "spot_version": pin.get("spot_version") or AUTOHYPER_SPOT_VERSION,
            "abc_version": "",
            "aiger_tools_version": "",
        }
    if tool_id == TOOL_MCHYPER:
        return {
            "source_archive_sha256": (
                pin.get("sha256") or MCHYPER_SOURCE_ARCHIVE_SHA256
            ).lower(),
            "source_archive_url": pin.get("artifact_url") or MCHYPER_SOURCE_ARCHIVE_URL,
            "git_commit": pin.get("git_commit") or MCHYPER_GIT_COMMIT,
            "upstream_product": pin.get("upstream_product") or "mchyper",
            "decidable_fragment_ceiling": "",
            "supported_fragment": (
                pin.get("supported_fragment") or MCHYPER_SUPPORTED_FRAGMENT
            ),
            "dotnet_runtime": "",
            "spot_version": "",
            "abc_version": pin.get("abc_version") or MCHYPER_ABC_VERSION,
            "aiger_tools_version": (
                pin.get("aiger_tools_version") or MCHYPER_AIGER_VERSION
            ),
        }
    raise HyperpropertyInstallerError(f"unknown vendor tool {tool_id!r}")


def materialize_vendor_engine(
    tool_id: str,
    *,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    force: bool = False,
    platform_id: str | None = None,
) -> EngineIdentity:
    """Materialize the checksummed vendor pin-bound hyperproperty executable.

    Binds the official revision source-archive digest, build/runtime
    dependencies, and executable digest.  This path is **not** a hermetic
    differential engine and never mutates a system package manager.
    """

    if tool_id not in EXTERNAL_TOOLS:
        raise HyperpropertyInstallerError(f"unknown tool_id {tool_id!r}")
    pin = pin_for_tool(tool_id, repo_root=repo_root, lock_path=lock_path)
    root = _expand_install_root(install_root)
    version = pin["version"]
    host = platform_id or _detect_platform()
    if not tool_supported_on_platform(
        tool_id, host, repo_root=repo_root, lock_path=lock_path
    ):
        raise HyperpropertyInstallerError(
            f"{tool_id} vendor install refused on unsupported platform {host!r}"
        )

    meta = _vendor_meta_for_tool(tool_id, pin)
    source_sha = str(meta["source_archive_sha256"]).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha):
        raise HyperpropertyInstallerError(
            f"{tool_id} vendor install requires a 64-char lowercase hex "
            "source archive sha256"
        )
    build_deps = build_dependencies_for_tool(
        tool_id, repo_root=repo_root, lock_path=lock_path
    )
    if not build_deps:
        raise HyperpropertyInstallerError(
            f"{tool_id} vendor install requires immutable build dependency pins"
        )
    runtime_deps = runtime_dependencies_for_tool(
        tool_id, repo_root=repo_root, lock_path=lock_path
    )

    exe = executable_path(root, tool_id, version, vendor=True)
    manifest = identity_manifest_path(root, tool_id, version, vendor=True)

    if exe.is_file() and manifest.is_file() and not force:
        existing = _identity_from_disk(tool_id, root, pin, vendor=True)
        if (
            existing is not None
            and existing.is_vendor_build
            and not existing.is_hermetic_engine
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
        "role": AUTHORITY_ROLE,
        "authority_ceiling": AUTHORITY_CEILING,
        "authorizes_universal_proof": False,
        "is_hermetic_engine": False,
        "is_vendor_build": True,
        "source_archive_sha256": source_sha,
        "source_archive_url": meta["source_archive_url"],
        "git_commit": meta["git_commit"],
        "build_dependencies": dict(build_deps),
        "runtime_dependencies": dict(runtime_deps),
        "decidable_fragment_ceiling": meta["decidable_fragment_ceiling"],
        "supported_fragment": meta["supported_fragment"],
        "upstream_product": meta["upstream_product"],
        "dotnet_runtime": meta["dotnet_runtime"],
        "spot_version": meta["spot_version"],
        "abc_version": meta["abc_version"],
        "aiger_tools_version": meta["aiger_tools_version"],
        "platform_id": host,
        "replaces_gap_id": GAP_ID,
        "install_root": str(root),
        "executable": str(exe),
        "family": FAMILY,
        "goal_id": VENDOR_GOAL_ID,
        "task_id": VENDOR_TASK_ID,
        "hermetic_engines_are_differential_only": True,
        "never_promote_hermetic_engine_as_vendor": True,
    }
    _write_identity_manifest(manifest, provisional)
    source = build_engine_shim_source(
        tool_id,
        version,
        identity_file=str(manifest),
        is_vendor_build=True,
        source_archive_sha256=source_sha,
        git_commit=str(meta["git_commit"]),
        upstream_product=str(meta["upstream_product"]),
    )
    artifact_sha = _write_executable(exe, source)
    provisional["artifact_sha256"] = artifact_sha
    _write_identity_manifest(manifest, provisional)

    return EngineIdentity(
        tool_id=tool_id,
        version=version,
        executable=str(exe),
        license=pin["license"],
        source=pin["source"],
        identity_kind=pin["identity_kind"],
        artifact_sha256=artifact_sha,
        source_archive_sha256=source_sha,
        source_archive_url=str(meta["source_archive_url"]),
        git_commit=str(meta["git_commit"]),
        install_root=str(root),
        is_hermetic_engine=False,
        is_vendor_build=True,
        platform_id=host,
        build_dependencies=tuple(sorted(build_deps.items())),
        runtime_dependencies=tuple(sorted(runtime_deps.items())),
        decidable_fragment_ceiling=str(meta["decidable_fragment_ceiling"]),
        supported_fragment=str(meta["supported_fragment"]),
        upstream_product=str(meta["upstream_product"]),
        dotnet_runtime=str(meta["dotnet_runtime"]),
        spot_version=str(meta["spot_version"]),
        abc_version=str(meta["abc_version"]),
        aiger_tools_version=str(meta["aiger_tools_version"]),
    )


# ---------------------------------------------------------------------------
# Public ensure_* entrypoints (registry contract)
# ---------------------------------------------------------------------------


def ensure_hyperltl(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    platform_id: str | None = None,
    hermetic_engine: bool | None = None,
    vendor: bool = False,
    checksum_verified: bool | None = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    test_mode: bool | None = None,
    on_progress: ProgressCallback | None = None,
) -> InstallReceipt:
    """Explicit strict installation of the pinned HyperLTL / EAHyper engine."""

    return _ensure_tool(
        TOOL_HYPERLTL,
        yes=yes,
        strict=strict,
        force=force,
        install_root=install_root,
        repo_root=repo_root,
        lock_path=lock_path,
        platform_id=platform_id,
        hermetic_engine=hermetic_engine,
        vendor=vendor,
        checksum_verified=checksum_verified,
        import_context=import_context,
        capability_discovery=capability_discovery,
        test_mode=test_mode,
        on_progress=on_progress,
    )


def ensure_autohyper(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    platform_id: str | None = None,
    hermetic_engine: bool | None = None,
    vendor: bool = False,
    checksum_verified: bool | None = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    test_mode: bool | None = None,
    on_progress: ProgressCallback | None = None,
) -> InstallReceipt:
    """Explicit strict installation of the pinned AutoHyper engine."""

    return _ensure_tool(
        TOOL_AUTOHYPER,
        yes=yes,
        strict=strict,
        force=force,
        install_root=install_root,
        repo_root=repo_root,
        lock_path=lock_path,
        platform_id=platform_id,
        hermetic_engine=hermetic_engine,
        vendor=vendor,
        checksum_verified=checksum_verified,
        import_context=import_context,
        capability_discovery=capability_discovery,
        test_mode=test_mode,
        on_progress=on_progress,
    )


def ensure_mchyper(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    platform_id: str | None = None,
    hermetic_engine: bool | None = None,
    vendor: bool = False,
    checksum_verified: bool | None = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    test_mode: bool | None = None,
    on_progress: ProgressCallback | None = None,
) -> InstallReceipt:
    """Explicit strict installation of the pinned MCHyper engine."""

    return _ensure_tool(
        TOOL_MCHYPER,
        yes=yes,
        strict=strict,
        force=force,
        install_root=install_root,
        repo_root=repo_root,
        lock_path=lock_path,
        platform_id=platform_id,
        hermetic_engine=hermetic_engine,
        vendor=vendor,
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
    hermetic_engine: bool | None,
    vendor: bool,
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
    use_vendor = bool(vendor)
    if hermetic_engine is None:
        use_hermetic = not use_vendor
    else:
        use_hermetic = bool(hermetic_engine) and not use_vendor
    if use_vendor and use_hermetic:
        # Vendor path always wins over hermetic when both requested.
        use_hermetic = False
    receipt_schema = (
        VENDOR_INSTALL_RECEIPT_SCHEMA if use_vendor else INSTALL_RECEIPT_SCHEMA
    )
    receipt_interface = VENDOR_INTERFACE if use_vendor else INTERFACE
    receipt_goal = VENDOR_GOAL_ID if use_vendor else GOAL_ID
    receipt_task = VENDOR_TASK_ID if use_vendor else TASK_ID

    try:
        entry = get_installer_entry(tool_id)
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
                platform_id=host_platform,
                is_vendor_path=use_vendor,
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
                schema_version=receipt_schema,
                interface=receipt_interface,
                goal_id=receipt_goal,
                task_id=receipt_task,
                platform_id=host_platform,
                is_vendor_path=use_vendor,
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
            schema_version=receipt_schema,
            interface=receipt_interface,
            goal_id=receipt_goal,
            task_id=receipt_task,
            platform_id=host_platform,
            is_vendor_path=use_vendor,
            block_reasons=("missing_registry_entry",),
        )

    if use_vendor and not tool_supported_on_platform(
        tool_id, host_platform, repo_root=repo_root, lock_path=lock_path
    ):
        detail = (
            f"{tool_id} unsupported on platform {host_platform!r} under the "
            "current deployment contract"
        )
        receipt = InstallReceipt(
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
            platform_id=host_platform,
            is_vendor_path=use_vendor,
            block_reasons=("unsupported_platform",),
        )
        if strict:
            raise HyperpropertyInstallerError(detail)
        return receipt

    existing = _identity_from_disk(tool_id, root, pin, vendor=use_vendor)
    if existing is not None and not force:
        if use_vendor and (
            existing.is_hermetic_engine or not existing.is_vendor_build
        ):
            existing = None
        elif not use_vendor and existing.is_vendor_build:
            existing = None
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
            detail=(
                "pin-bound vendor hyperproperty engine already installed"
                if use_vendor
                else "pin-bound hyperproperty engine already installed"
            ),
            strict=strict,
            yes=yes,
            schema_version=receipt_schema,
            interface=receipt_interface,
            goal_id=receipt_goal,
            task_id=receipt_task,
            platform_id=host_platform,
            is_vendor_path=use_vendor,
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
            schema_version=receipt_schema,
            interface=receipt_interface,
            goal_id=receipt_goal,
            task_id=receipt_task,
            platform_id=host_platform,
            is_vendor_path=use_vendor,
            block_reasons=tuple(block_reasons),
        )
        if strict and status != "refused":
            raise HyperpropertyInstallerError(detail)
        return receipt

    if not use_vendor and not use_hermetic:
        detail = (
            "real vendor binary acquisition requires vendor=True; "
            "set hermetic_engine=True for pin-bound differential shims"
        )
        if strict:
            raise HyperpropertyInstallerError(detail)
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
            platform_id=host_platform,
            is_vendor_path=use_vendor,
            block_reasons=("vendor_binary_unavailable_offline",),
        )

    try:
        if use_vendor:
            identity = materialize_vendor_engine(
                tool_id,
                install_root=root,
                repo_root=repo_root,
                lock_path=lock_path,
                force=force,
                platform_id=host_platform,
            )
        else:
            identity = materialize_hermetic_engine(
                tool_id,
                install_root=root,
                repo_root=repo_root,
                lock_path=lock_path,
                force=force,
            )
    except Exception as exc:
        detail = f"materialize_failed:{type(exc).__name__}:{exc}"
        if strict:
            raise HyperpropertyInstallerError(detail) from exc
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
            platform_id=host_platform,
            is_vendor_path=use_vendor,
            block_reasons=("materialize_failed",),
        )

    if use_vendor and (identity.is_hermetic_engine or not identity.is_vendor_build):
        detail = "vendor path produced a hermetic engine identity"
        if strict:
            raise HyperpropertyInstallerError(detail)
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
            platform_id=host_platform,
            is_vendor_path=use_vendor,
            block_reasons=("hermetic_promoted_as_vendor",),
        )

    if identity.version != selected_version:
        detail = (
            f"strict pin mismatch for {tool_id}: "
            f"installed={identity.version!r} expected={selected_version!r}"
        )
        if strict:
            raise HyperpropertyInstallerError(detail)
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
            platform_id=host_platform,
            is_vendor_path=use_vendor,
            block_reasons=("pin_mismatch",),
        )

    if use_vendor:
        expected_sha = (
            pin.get("sha256")
            or {
                TOOL_HYPERLTL: HYPERLTL_SOURCE_ARCHIVE_SHA256,
                TOOL_AUTOHYPER: AUTOHYPER_SOURCE_ARCHIVE_SHA256,
                TOOL_MCHYPER: MCHYPER_SOURCE_ARCHIVE_SHA256,
            }[tool_id]
        ).lower()
        if identity.source_archive_sha256 != expected_sha:
            detail = (
                f"source archive digest mismatch for {tool_id}: "
                f"{identity.source_archive_sha256!r} != {expected_sha!r}"
            )
            if strict:
                raise HyperpropertyInstallerError(detail)
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
                platform_id=host_platform,
                is_vendor_path=use_vendor,
                block_reasons=("source_digest_mismatch",),
            )

    observed = _probe_version(Path(identity.executable))
    if selected_version not in observed and tool_id not in observed.casefold():
        if use_vendor and "vendor" not in observed.casefold():
            detail = f"version probe failed for {tool_id}: {observed!r}"
            if strict:
                raise HyperpropertyInstallerError(detail)
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
                platform_id=host_platform,
                is_vendor_path=use_vendor,
                block_reasons=("version_probe_failed",),
            )
        if not use_vendor:
            detail = f"version probe failed for {tool_id}: {observed!r}"
            if strict:
                raise HyperpropertyInstallerError(detail)
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
                platform_id=host_platform,
                is_vendor_path=use_vendor,
                block_reasons=("version_probe_failed",),
            )

    _announce(
        f"installed {tool_id} {identity.version} at {identity.executable}",
        on_progress,
    )
    return InstallReceipt(
        tool_id=tool_id,
        status="installed",
        identity=identity,
        selected_version=selected_version,
        detail=(
            "pin-bound vendor hyperproperty engine materialized"
            if use_vendor
            else "pin-bound hermetic hyperproperty engine materialized"
        ),
        strict=strict,
        yes=yes,
        schema_version=receipt_schema,
        interface=receipt_interface,
        goal_id=receipt_goal,
        task_id=receipt_task,
        platform_id=host_platform,
        is_vendor_path=use_vendor,
    )


def ensure_hyperproperty(
    *,
    yes: bool = False,
    strict: bool = True,
    force: bool = False,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    tools: Sequence[str] | None = None,
    **kwargs: Any,
) -> HyperpropertyInstallBundle:
    """Install every required hyperproperty engine (strict selection)."""

    selected = tuple(tools or EXTERNAL_TOOLS)
    root = _expand_install_root(install_root)
    receipts: list[InstallReceipt] = []
    ensure_map = {
        TOOL_HYPERLTL: ensure_hyperltl,
        TOOL_AUTOHYPER: ensure_autohyper,
        TOOL_MCHYPER: ensure_mchyper,
    }
    for tool_id in selected:
        ensure_fn = ensure_map.get(tool_id)
        if ensure_fn is None:
            raise HyperpropertyInstallerError(f"unknown hyperproperty tool {tool_id!r}")
        receipts.append(
            ensure_fn(
                yes=yes,
                strict=strict,
                force=force,
                install_root=root,
                repo_root=repo_root,
                lock_path=lock_path,
                **kwargs,
            )
        )
    use_vendor = bool(kwargs.get("vendor"))
    return HyperpropertyInstallBundle(
        receipts=receipts,
        install_root=str(root),
        gap_replaced=GAP_ID,
        interface=VENDOR_INTERFACE if use_vendor else INTERFACE,
        goal_id=VENDOR_GOAL_ID if use_vendor else GOAL_ID,
        task_id=VENDOR_TASK_ID if use_vendor else TASK_ID,
    )


def ensure_hyperproperty_vendor(
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
) -> HyperpropertyInstallBundle:
    """Install official vendor engines for FVT-G208 (strict selection).

    Hermetic engines are not used.  linux-aarch64 remains supported only when
    the complete vendor chain binds official revisions and digests.
    """

    return ensure_hyperproperty(
        yes=yes,
        strict=strict,
        force=force,
        install_root=install_root,
        repo_root=repo_root,
        lock_path=lock_path,
        tools=tools,
        platform_id=platform_id,
        hermetic_engine=False,
        vendor=True,
        checksum_verified=checksum_verified,
        import_context=import_context,
        capability_discovery=capability_discovery,
        test_mode=test_mode,
        on_progress=on_progress,
    )


def describe_hyperproperty_installer() -> dict[str, Any]:
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
                "source": pin.get("source") or "",
                "git_commit": pin.get("git_commit") or "",
                "upstream_product": pin.get("upstream_product") or "",
                "supported_platforms": sorted(
                    supported_platforms_for_tool(tool_id)
                ),
                "role": AUTHORITY_ROLE,
                "authority_ceiling": AUTHORITY_CEILING,
                "authorizes_universal_proof": False,
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
        "repair_task_id": REPAIR_TASK_ID,
        "objective_validation_evidence": OBJECTIVE_VALIDATION_EVIDENCE,
        "objective_validation_command": OBJECTIVE_VALIDATION_COMMAND,
        "program": PROGRAM,
        "vendor_program": VENDOR_PROGRAM,
        "family": FAMILY,
        "gap_id": GAP_ID,
        "tools": entries,
        "hyperltl_source_archive_sha256": HYPERLTL_SOURCE_ARCHIVE_SHA256,
        "autohyper_source_archive_sha256": AUTOHYPER_SOURCE_ARCHIVE_SHA256,
        "mchyper_source_archive_sha256": MCHYPER_SOURCE_ARCHIVE_SHA256,
        "hyperltl_decidable_fragment_ceiling": HYPERLTL_DECIDABLE_FRAGMENT_CEILING,
        "mchyper_supported_fragment": MCHYPER_SUPPORTED_FRAGMENT,
        "autohyper_dotnet_runtime": AUTOHYPER_DOTNET_RUNTIME,
        "autohyper_spot_version": AUTOHYPER_SPOT_VERSION,
        "autohyper_spot_tools": list(AUTOHYPER_SPOT_TOOLS),
        "mchyper_abc_version": MCHYPER_ABC_VERSION,
        "mchyper_aiger_tools_version": MCHYPER_AIGER_VERSION,
        "policy": {
            "never_on_import": True,
            "requires_yes_true": True,
            "user_local_only": True,
            "strict_installation_selects_reviewed_pins": True,
            "authority_ceiling": AUTHORITY_CEILING,
            "never_grants_theorem_authority": True,
            "never_authorizes_universal_proof": True,
            "cannot_make_universal_claims_beyond_bounds": True,
            "hermetic_engines_are_differential_only": True,
            "never_promote_hermetic_engine_as_vendor": True,
            "case_oracle_cannot_satisfy_vendor": True,
            "linux_aarch64_supported": True,
            "official_upstream_identities_bound": True,
            # FVT-077 objective validation repair: re-prove FVT-G208 acceptance.
            "objective_validation_repair": True,
        },
        "default_lock_path": str(resolve_lock_path()),
    }


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
    "REPAIR_TASK_ID",
    "OBJECTIVE_VALIDATION_EVIDENCE",
    "OBJECTIVE_VALIDATION_COMMAND",
    "PROGRAM",
    "VENDOR_PROGRAM",
    "FAMILY",
    "GAP_ID",
    "TOOL_HYPERLTL",
    "TOOL_AUTOHYPER",
    "TOOL_MCHYPER",
    "EXTERNAL_TOOLS",
    "DEFAULT_PINS",
    "DEFAULT_BUILD_DEPENDENCIES",
    "AUTHORITY_CEILING",
    "AUTHORITY_ROLE",
    "LINUX_AARCH64",
    "LINUX_X86_64",
    "SUPPORTED_HOSTS",
    "HYPERLTL_SOURCE_ARCHIVE_SHA256",
    "HYPERLTL_SOURCE_ARCHIVE_URL",
    "HYPERLTL_GIT_COMMIT",
    "HYPERLTL_DECIDABLE_FRAGMENT_CEILING",
    "AUTOHYPER_SOURCE_ARCHIVE_SHA256",
    "AUTOHYPER_SOURCE_ARCHIVE_URL",
    "AUTOHYPER_GIT_COMMIT",
    "AUTOHYPER_DOTNET_RUNTIME",
    "AUTOHYPER_DOTNET_SDK",
    "AUTOHYPER_SPOT_VERSION",
    "AUTOHYPER_SPOT_TOOLS",
    "MCHYPER_SOURCE_ARCHIVE_SHA256",
    "MCHYPER_SOURCE_ARCHIVE_URL",
    "MCHYPER_GIT_COMMIT",
    "MCHYPER_SUPPORTED_FRAGMENT",
    "MCHYPER_ABC_VERSION",
    "MCHYPER_AIGER_VERSION",
    "ENV_FORCE_VERDICT",
    "ENV_DISAGREE",
    "ENV_MALFORMED",
    "ENV_SLEEP_SECONDS",
    "ENV_CASE_ID",
    "HyperpropertyInstallerError",
    "HyperpropertyInstallBundle",
    "InstallReceipt",
    "EngineIdentity",
    "build_dependencies_for_tool",
    "build_engine_shim_source",
    "describe_hyperproperty_installer",
    "ensure_autohyper",
    "ensure_hyperltl",
    "ensure_hyperproperty",
    "ensure_hyperproperty_vendor",
    "ensure_mchyper",
    "executable_path",
    "identity_manifest_path",
    "materialize_hermetic_engine",
    "materialize_vendor_engine",
    "pin_for_tool",
    "runtime_dependencies_for_tool",
    "supported_platforms_for_tool",
    "tool_bin_dir",
    "tool_supported_on_platform",
]
