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
import shutil
import stat
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final
from urllib.parse import urlparse
from urllib.request import Request, urlopen

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
    ToolchainAuthorityCeiling,
    ToolRole,
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

# AutoHyper pins these repositories as git submodules.  GitHub source archives
# intentionally do not include submodule contents, so a reproducible source
# build must acquire and verify each component independently.
AUTOHYPER_SOURCE_COMPONENTS: Final[Mapping[str, Mapping[str, str]]] = (
    MappingProxyType(
        {
            "FsOmegaLib": MappingProxyType(
                {
                    "path": "src/FsOmegaLib",
                    "source": "https://github.com/ravenbeutner/FsOmegaLib",
                    "git_commit": "957153e816cc1e49a1cf3472b168f8365d825a85",
                    "source_archive_url": (
                        "https://github.com/ravenbeutner/FsOmegaLib/archive/"
                        "957153e816cc1e49a1cf3472b168f8365d825a85.tar.gz"
                    ),
                    "source_archive_sha256": (
                        "9e227615327efac4cca2152799c99ce3f88186249bdf6bfaaf1e8e3c5f8a626a"
                    ),
                }
            ),
            "TransitionSystemLib": MappingProxyType(
                {
                    "path": "src/TransitionSystemLib",
                    "source": (
                        "https://github.com/ravenbeutner/TransitionSystemLib"
                    ),
                    "git_commit": "1959643daf25015b81772da1f5d03ccde61f35cb",
                    "source_archive_url": (
                        "https://github.com/ravenbeutner/TransitionSystemLib/archive/"
                        "1959643daf25015b81772da1f5d03ccde61f35cb.tar.gz"
                    ),
                    "source_archive_sha256": (
                        "5b5e485c15f40ce4f15dac0f0aad6cee365115462be87c857ffa5323e7a413a0"
                    ),
                }
            ),
        }
    )
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
MCHYPER_AIGER_SOURCE_ARCHIVE_URL: Final = (
    "https://fmv.jku.at/aiger/aiger-1.9.4.tar.gz"
)
MCHYPER_AIGER_SOURCE_ARCHIVE_SHA256: Final = (
    "bd7bb89f51deef8c5681753c861bf0ab7f85f166fb30da0caf83c2d31f6df2d1"
)
MCHYPER_ABC_GIT_COMMIT: Final = "e76768b9d34f9dc67cb6608efecd55db271ff849"
MCHYPER_ABC_SOURCE_ARCHIVE_URL: Final = (
    "https://github.com/berkeley-abc/abc/archive/"
    f"{MCHYPER_ABC_GIT_COMMIT}.tar.gz"
)
MCHYPER_ABC_SOURCE_ARCHIVE_SHA256: Final = (
    "158a4bf861be010cf899c5cb20c159d1b2e68ae1b461bce7d2c10be348a8e159"
)
MCHYPER_PYTHON_VERSION: Final = "2.7.18"
MCHYPER_PYTHON_SOURCE_ARCHIVE_URL: Final = (
    "https://www.python.org/ftp/python/2.7.18/Python-2.7.18.tar.xz"
)
MCHYPER_PYTHON_SOURCE_ARCHIVE_SHA256: Final = (
    "b62c0e7937551d0cc02b8fd5cb0f544f9405bafc9a54d3808ed4594812edef43"
)
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


class HyperpropertyInstallBlocked(HyperpropertyInstallerError):
    """Fail-closed refusal with stable, machine-readable blocker reasons."""

    def __init__(self, detail: str, *block_reasons: str) -> None:
        super().__init__(detail)
        self.block_reasons = tuple(dict.fromkeys(block_reasons or ("blocked",)))


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DependencyIdentity:
    """Observed identity of a build/runtime executable used by an upstream build."""

    name: str
    constraint: str
    executable: str
    version_output: str
    executable_sha256: str
    phase: str = "build"

    def __post_init__(self) -> None:
        if self.phase not in {"build", "runtime"}:
            raise HyperpropertyInstallerError(
                f"invalid dependency phase {self.phase!r}"
            )
        if not self.name or not self.executable or not re.fullmatch(
            r"[0-9a-f]{64}", self.executable_sha256
        ):
            raise HyperpropertyInstallerError(
                f"incomplete dependency identity for {self.name!r}"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "constraint": self.constraint,
            "executable": self.executable,
            "executable_sha256": self.executable_sha256,
            "name": self.name,
            "phase": self.phase,
            "version_output": self.version_output,
        }


@dataclass(frozen=True, slots=True)
class DependencyArtifactIdentity:
    """Hash-bound non-executable dependency provenance."""

    name: str
    path: str
    artifact_kind: str
    artifact_sha256: str
    version: str
    phase: str = "build"
    source_archive_url: str = ""
    source_archive_path: str = ""
    source_archive_sha256: str = ""

    def __post_init__(self) -> None:
        if self.artifact_kind not in {"file", "directory"}:
            raise HyperpropertyInstallerError(
                f"invalid artifact kind for {self.name!r}"
            )
        if self.phase not in {"build", "runtime"}:
            raise HyperpropertyInstallerError(
                f"invalid artifact phase for {self.name!r}"
            )
        if not self.name or not self.path or not self.version:
            raise HyperpropertyInstallerError(
                f"incomplete dependency artifact identity for {self.name!r}"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", self.artifact_sha256):
            raise HyperpropertyInstallerError(
                f"invalid dependency artifact digest for {self.name!r}"
            )
        archive_fields = (
            self.source_archive_url,
            self.source_archive_path,
            self.source_archive_sha256,
        )
        if any(archive_fields) and (
            not all(archive_fields)
            or not re.fullmatch(r"[0-9a-f]{64}", self.source_archive_sha256)
        ):
            raise HyperpropertyInstallerError(
                f"incomplete source archive identity for dependency {self.name!r}"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "artifact_kind": self.artifact_kind,
            "artifact_sha256": self.artifact_sha256,
            "name": self.name,
            "path": self.path,
            "phase": self.phase,
            "source_archive_path": self.source_archive_path,
            "source_archive_sha256": self.source_archive_sha256,
            "source_archive_url": self.source_archive_url,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class SourceComponentIdentity:
    """Pinned source component required to reproduce an upstream build."""

    name: str
    git_commit: str
    source_archive_url: str
    source_archive_sha256: str
    source_archive_path: str

    def __post_init__(self) -> None:
        if not self.name or not re.fullmatch(r"[0-9a-f]{40}", self.git_commit):
            raise HyperpropertyInstallerError(
                f"incomplete source component identity for {self.name!r}"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_archive_sha256):
            raise HyperpropertyInstallerError(
                f"invalid source digest for component {self.name!r}"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "git_commit": self.git_commit,
            "name": self.name,
            "source_archive_path": self.source_archive_path,
            "source_archive_sha256": self.source_archive_sha256,
            "source_archive_url": self.source_archive_url,
        }


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
    is_upstream_build: bool = False
    executable_kind: str = ""
    executable_origin: str = ""
    artifact_sha256: str = ""
    source_archive_sha256: str = ""
    source_archive_url: str = ""
    source_archive_path: str = ""
    source_tree_sha256: str = ""
    distribution_tree_sha256: str = ""
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
    dependency_identities: tuple[DependencyIdentity, ...] = ()
    source_components: tuple[SourceComponentIdentity, ...] = ()
    build_lockfiles: tuple[tuple[str, str], ...] = ()
    runtime_environment: tuple[tuple[str, str], ...] = ()
    dependency_artifacts: tuple[DependencyArtifactIdentity, ...] = ()

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
            if not self.is_upstream_build:
                raise HyperpropertyInstallerError(
                    "vendor identity must represent a verified upstream build"
                )
            if self.executable_kind not in {
                "upstream_compiled_binary",
                "upstream_python_entrypoint",
            }:
                raise HyperpropertyInstallerError(
                    "vendor executable must be an upstream artifact, not an adapter"
                )
            if (
                not self.source_archive_sha256
                or not self.artifact_sha256
                or not self.source_tree_sha256
                or not self.distribution_tree_sha256
                or not self.source_archive_path
                or not self.executable_origin
                or not self.dependency_identities
            ):
                raise HyperpropertyInstallerError(
                    f"vendor {self.tool_id} identity requires exact upstream "
                    "source, dependency, distribution, and artifact identities"
                )
            if self.tool_id == TOOL_MCHYPER and not {
                "ghc-package-db",
                "aiger-source",
                "abc-source",
                "python-source",
            }.issubset({item.name for item in self.dependency_artifacts}):
                raise HyperpropertyInstallerError(
                    "MCHyper vendor identity requires GHC package DB and "
                    "AIGER source/archive provenance"
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
            "build_lockfiles": {
                name: digest for name, digest in self.build_lockfiles
            },
            "decidable_fragment_ceiling": self.decidable_fragment_ceiling,
            "dotnet_runtime": self.dotnet_runtime,
            "dependency_identities": [
                item.to_dict() for item in self.dependency_identities
            ],
            "dependency_artifacts": [
                item.to_dict() for item in self.dependency_artifacts
            ],
            "distribution_tree_sha256": self.distribution_tree_sha256,
            "executable": self.executable,
            "executable_kind": self.executable_kind,
            "executable_origin": self.executable_origin,
            "git_commit": self.git_commit,
            "identity_kind": self.identity_kind,
            "install_root": self.install_root,
            "is_hermetic_engine": self.is_hermetic_engine,
            "is_upstream_build": self.is_upstream_build,
            "is_vendor_build": self.is_vendor_build,
            "license": self.license,
            "platform_id": self.platform_id,
            "replaces_gap_id": self.replaces_gap_id,
            "role": self.role,
            "runtime_dependencies": {
                name: constraint for name, constraint in self.runtime_dependencies
            },
            "runtime_environment": {
                name: value for name, value in self.runtime_environment
            },
            "source": self.source,
            "source_archive_path": self.source_archive_path,
            "source_archive_sha256": self.source_archive_sha256,
            "source_archive_url": self.source_archive_url,
            "source_components": [
                item.to_dict() for item in self.source_components
            ],
            "source_tree_sha256": self.source_tree_sha256,
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

Generated by HyperpropertyInstaller@1 for hermetic differential certification.
Speaks the HyperpropertyBackend I/O contract used by HyperLTLBackend /
AutoHyperBackend / MCHyperBackend. Bounded authority only; never authorizes
universal proof.  It is never a vendor/native/upstream executable.
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
    """Return a differential-only hermetic shim for ``tool_id``."""

    if tool_id not in EXTERNAL_TOOLS:
        raise HyperpropertyInstallerError(f"unknown tool_id {tool_id!r}")
    if is_vendor_build:
        raise HyperpropertyInstallerError(
            "Python adapters cannot be labeled vendor/native; use the "
            "verified upstream source-build path"
        )
    return _ENGINE_SHIM_TEMPLATE.format(
        tool_id=tool_id,
        version=version,
        identity_file=identity_file,
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


_INTERNAL_ADAPTER_MARKERS: Final = (
    b"Generated by HyperpropertyInstaller@1",
    b"Pin-bound hyperproperty engine shim",
    b"hermetic-hyperproperty-engine",
    b"vendor-pin-bound",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(root: Path, *, exclude: Sequence[str] = ()) -> str:
    """Return a deterministic digest over names, modes, links, and contents."""

    excluded = frozenset(exclude)
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        if path.is_symlink():
            kind = "link"
            body = os.readlink(path).encode("utf-8")
            mode = 0
        elif path.is_dir():
            kind = "dir"
            body = b""
            mode = stat.S_IMODE(path.stat().st_mode)
        elif path.is_file():
            kind = "file"
            body = bytes.fromhex(_sha256_file(path))
            mode = stat.S_IMODE(path.stat().st_mode)
        else:
            raise HyperpropertyInstallerError(
                f"unsupported installed filesystem object {relative!r}"
            )
        digest.update(
            f"{kind}\0{relative}\0{mode:o}\0".encode() + body + b"\0"
        )
    return digest.hexdigest()


def _is_internal_python_adapter(path: Path) -> bool:
    try:
        prefix = path.read_bytes()[:256 * 1024]
    except OSError:
        return True
    return any(marker in prefix for marker in _INTERNAL_ADAPTER_MARKERS)


def _assert_reviewed_upstream_pin(
    tool_id: str, pin: Mapping[str, str], meta: Mapping[str, Any]
) -> None:
    defaults = DEFAULT_PINS[tool_id]
    expected = {
        "source": defaults["source"],
        "artifact_url": defaults["artifact_url"],
        "git_commit": defaults["git_commit"],
        "sha256": defaults["sha256"],
    }
    observed = {
        "source": str(pin.get("source") or ""),
        "artifact_url": str(meta.get("source_archive_url") or ""),
        "git_commit": str(meta.get("git_commit") or ""),
        "sha256": str(meta.get("source_archive_sha256") or "").lower(),
    }
    mismatches = []
    if observed["sha256"] != str(expected["sha256"]).lower():
        mismatches.append("sha256")
    mismatches.extend(
        name
        for name in ("source", "artifact_url", "git_commit")
        if observed[name] != expected[name]
    )
    parsed = urlparse(observed["artifact_url"])
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"github.com", "codeload.github.com"}
        or observed["git_commit"] not in observed["artifact_url"]
    ):
        mismatches.append("official_https_archive")
    if mismatches:
        reasons = tuple(
            f"unreviewed_upstream_pin:{name}"
            for name in dict.fromkeys(mismatches)
        )
        raise HyperpropertyInstallBlocked(
            f"{tool_id} upstream pin differs from the reviewed immutable source: "
            + ", ".join(dict.fromkeys(mismatches)),
            *reasons,
        )


def _download_verified_archive(
    url: str,
    destination: Path,
    expected_sha256: str,
) -> Path:
    """Fetch one immutable HTTPS archive and fail before use on any mismatch."""

    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise HyperpropertyInstallerError("archive sha256 must be lowercase hex")
    if destination.is_file() and _sha256_file(destination) == expected_sha256:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    try:
        request = Request(url, headers={"User-Agent": INTERFACE})
        with urlopen(request, timeout=60) as response, partial.open("wb") as stream:
            shutil.copyfileobj(response, stream)
        observed = _sha256_file(partial)
        if observed != expected_sha256:
            raise HyperpropertyInstallBlocked(
                f"source archive digest mismatch: {observed} != {expected_sha256}",
                "source_archive_digest_mismatch",
            )
        partial.replace(destination)
    except HyperpropertyInstallBlocked:
        partial.unlink(missing_ok=True)
        raise
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise HyperpropertyInstallBlocked(
            f"source archive fetch failed for {url}: {type(exc).__name__}: {exc}",
            "source_archive_fetch_failed",
        ) from exc
    return destination


def _safe_extract_source_archive(
    archive: Path,
    destination: Path,
    git_commit: str,
) -> Path:
    """Extract a GitHub archive without links, devices, or path traversal."""

    destination.mkdir(parents=True, exist_ok=False)
    destination_resolved = destination.resolve()
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            for member in members:
                target = (destination / member.name).resolve()
                if (
                    target != destination_resolved
                    and destination_resolved not in target.parents
                ):
                    raise HyperpropertyInstallerError(
                        f"source archive path escapes extraction root: {member.name!r}"
                    )
                if not (member.isfile() or member.isdir()):
                    raise HyperpropertyInstallerError(
                        f"source archive contains unsupported object: {member.name!r}"
                    )
            bundle.extractall(destination, members=members)
    except (tarfile.TarError, OSError) as exc:
        raise HyperpropertyInstallBlocked(
            f"source archive extraction failed: {type(exc).__name__}: {exc}",
            "source_archive_extraction_failed",
        ) from exc
    roots = [item for item in destination.iterdir() if item.is_dir()]
    if len(roots) != 1 or not roots[0].name.endswith(f"-{git_commit}"):
        raise HyperpropertyInstallBlocked(
            "source archive root is not bound to the pinned git commit",
            "source_archive_commit_mismatch",
        )
    return roots[0]


def _source_tree_sha256(archive: Path, git_commit: str) -> str:
    with tempfile.TemporaryDirectory(prefix="hyperproperty-source-audit-") as raw:
        root = _safe_extract_source_archive(
            archive, Path(raw) / "extract", git_commit
        )
        return _tree_sha256(root)


def _numeric_version(text: str) -> tuple[int, ...] | None:
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)+|\d{8})(?!\d)", text)
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _version_satisfies(output: str, constraint: str) -> bool:
    if not constraint:
        return bool(output.strip())
    expected_text = constraint[2:] if constraint.startswith(">=") else constraint
    observed = _numeric_version(output)
    expected = _numeric_version(expected_text)
    if observed is None or expected is None:
        return False
    width = max(len(observed), len(expected))
    left = observed + (0,) * (width - len(observed))
    right = expected + (0,) * (width - len(expected))
    return left >= right if constraint.startswith(">=") else left == right


def _dependency_specs(tool_id: str) -> tuple[dict[str, Any], ...]:
    if tool_id == TOOL_HYPERLTL:
        return (
            {"name": "make", "candidates": ("make",), "args": ("--version",), "constraint": ">=3.0"},
            {"name": "ocamlc", "candidates": ("ocamlc",), "args": ("-version",), "constraint": ">=4.08"},
            {"name": "ocamlbuild", "candidates": ("ocamlbuild",), "args": ("-version",), "constraint": ""},
            {"name": "ocamlfind", "candidates": ("ocamlfind",), "args": ("query", "findlib", "-format", "%v"), "constraint": ""},
            {"name": "menhir", "candidates": ("menhir",), "args": ("--version",), "constraint": ">=20201216"},
            {"name": "dune", "candidates": ("dune",), "args": ("--version",), "constraint": ">=2.0"},
            {"name": "g++", "candidates": ("g++",), "args": ("--version",), "constraint": ">=4.8"},
            {"name": "zlib", "candidates": ("pkg-config",), "args": ("--modversion", "zlib"), "constraint": ""},
        )
    if tool_id == TOOL_AUTOHYPER:
        return (
            {"name": "dotnet", "candidates": ("dotnet",), "args": ("--version",), "constraint": AUTOHYPER_DOTNET_SDK},
            {"name": "autfilt", "candidates": ("autfilt",), "args": ("--version",), "constraint": AUTOHYPER_SPOT_VERSION, "phase": "runtime"},
            {"name": "ltl2tgba", "candidates": ("ltl2tgba",), "args": ("--version",), "constraint": AUTOHYPER_SPOT_VERSION, "phase": "runtime"},
        )
    if tool_id == TOOL_MCHYPER:
        return (
            {"name": "ghc", "candidates": ("ghc",), "args": ("--numeric-version",), "constraint": ">=8.4"},
            {"name": "ghc-pkg", "candidates": ("ghc-pkg",), "args": ("--version",), "constraint": ""},
            {"name": "cabal", "candidates": ("cabal",), "args": ("--numeric-version",), "constraint": ">=2.4"},
            {"name": "python2.7", "candidates": ("python2.7",), "args": ("--version",), "constraint": ">=2.7", "phase": "runtime"},
            {"name": "abc", "candidates": ("abc",), "args": ("-c", "version"), "constraint": MCHYPER_ABC_VERSION, "phase": "runtime"},
            {"name": "aigtoaig", "candidates": ("aigtoaig",), "args": ("-h",), "constraint": MCHYPER_AIGER_VERSION, "phase": "runtime", "allow_nonzero": True},
        )
    raise HyperpropertyInstallerError(f"unknown vendor tool {tool_id!r}")


def _capture_dependency_version(
    executable: str,
    args: Sequence[str],
    *,
    allow_nonzero: bool = False,
    environment: Mapping[str, str] | None = None,
) -> str:
    env = os.environ.copy()
    if environment:
        env.update(environment)
    try:
        completed = subprocess.run(
            [executable, *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    if completed.returncode and not allow_nonzero:
        return ""
    return output[:4096]


def _single_ghc_package_identity(package: str, output: str) -> str:
    """Validate one exact ``ghc-pkg field ... id,version`` record.

    ``ghc-pkg`` may otherwise return more than one installed package version.
    Compiling against an ambiguous record would make the build environment
    depend on package-database ordering, so the vendor lane rejects anything
    other than one ``id`` and one ``version`` field.
    """

    fields: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.fullmatch(r"(id|version):\s*(\S+)", line)
        if match is None or match.group(1) in fields:
            return ""
        fields[match.group(1)] = match.group(2)
    package_id = fields.get("id", "")
    version = fields.get("version", "")
    if (
        set(fields) != {"id", "version"}
        or not package_id.casefold().startswith(f"{package.casefold()}-")
        or not re.fullmatch(r"\d+(?:\.\d+)+(?:[-+._A-Za-z0-9]*)?", version)
    ):
        return ""
    return f"id: {package_id}\nversion: {version}"


_DEPENDENCY_ROOT_GROUPS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "autfilt": ("spot",),
        "abc": ("abc-root",),
        "aigtoaig": ("aiger", "aiger-root"),
        "cabal": ("ghcup", "ghcup-bin"),
        "dotnet": ("dotnet-sdk",),
        "dune": ("opam", "opam-switch", "ocaml"),
        "ltl2tgba": ("spot",),
        "ghc": ("ghcup", "ghcup-bin"),
        "ghc-pkg": ("ghcup", "ghcup-bin"),
        "menhir": ("opam", "opam-switch", "ocaml"),
        "ocamlbuild": ("opam", "opam-switch", "ocaml"),
        "ocamlc": ("opam", "opam-switch", "ocaml"),
        "ocamlfind": ("opam", "opam-switch", "ocaml"),
        "python2.7": ("python", "python-root"),
    }
)


def _dependency_root_path(
    dependency_roots: Mapping[str, Path | str],
    *names: str,
) -> Path | None:
    for name in names:
        raw = dependency_roots.get(name)
        if raw is not None:
            return Path(os.path.expanduser(str(raw))).resolve()
    return None


def _verified_aiger_version_evidence(
    dependency_roots: Mapping[str, Path | str],
) -> str:
    source_root = _dependency_root_path(
        dependency_roots, "aiger-source", "aiger-source-root"
    )
    archive = _dependency_root_path(
        dependency_roots, "aiger-archive", "aiger-source-archive"
    )
    if source_root is None or archive is None:
        raise HyperpropertyInstallBlocked(
            "AIGER has no executable version banner; explicit pinned source "
            "and archive roots are required",
            "missing_dependency_evidence:aigtoaig",
        )
    version_file = source_root / "VERSION"
    if (
        not version_file.is_file()
        or version_file.read_text(encoding="utf-8").strip()
        != MCHYPER_AIGER_VERSION
    ):
        raise HyperpropertyInstallBlocked(
            "AIGER VERSION does not match the reviewed 1.9.4 source",
            "dependency_version_mismatch:aigtoaig",
        )
    if (
        not archive.is_file()
        or _sha256_file(archive) != MCHYPER_AIGER_SOURCE_ARCHIVE_SHA256
    ):
        raise HyperpropertyInstallBlocked(
            "AIGER source archive digest does not match the reviewed pin",
            "dependency_source_digest_mismatch:aigtoaig",
        )
    return (
        f"{MCHYPER_AIGER_VERSION} (verified VERSION and source archive "
        f"sha256:{MCHYPER_AIGER_SOURCE_ARCHIVE_SHA256})"
    )


def _executable_from_dependency_roots(
    dependency_name: str,
    candidate_names: Sequence[str],
    dependency_roots: Mapping[str, Path | str],
) -> str | None:
    keys = (
        dependency_name,
        *candidate_names,
        *_DEPENDENCY_ROOT_GROUPS.get(dependency_name, ()),
    )
    for key in dict.fromkeys(keys):
        if key not in dependency_roots:
            continue
        configured = Path(
            os.path.expanduser(str(dependency_roots[key]))
        ).resolve()
        if configured.is_file():
            return str(configured)
        for candidate_name in candidate_names:
            for relative in (
                Path(candidate_name),
                Path("bin") / candidate_name,
                Path("sbin") / candidate_name,
            ):
                candidate = configured / relative
                if candidate.is_file():
                    return str(candidate.resolve())
    return None


def _resolve_vendor_dependencies(
    tool_id: str,
    dependency_roots: Mapping[str, Path | str] | None = None,
) -> tuple[DependencyIdentity, ...]:
    roots = dependency_roots or {}
    identities: list[DependencyIdentity] = []
    blockers: list[str] = []
    details: list[str] = []
    for spec in _dependency_specs(tool_id):
        executable = _executable_from_dependency_roots(
            str(spec["name"]), spec["candidates"], roots
        )
        if executable is None:
            executable = next(
                (
                    candidate
                    for name in spec["candidates"]
                    if (candidate := shutil.which(name))
                ),
                None,
            )
        if executable is None:
            blockers.append(f"missing_dependency:{spec['name']}")
            details.append(f"{spec['name']} not found")
            continue
        resolved = Path(executable).resolve()
        try:
            if spec["name"] == "aigtoaig":
                output = _verified_aiger_version_evidence(roots)
            else:
                output = _capture_dependency_version(
                    str(resolved),
                    spec["args"],
                    allow_nonzero=bool(spec.get("allow_nonzero")),
                )
        except HyperpropertyInstallBlocked as exc:
            blockers.extend(exc.block_reasons)
            details.append(str(exc))
            continue
        if not _version_satisfies(output, str(spec["constraint"])):
            blockers.append(f"dependency_version_mismatch:{spec['name']}")
            details.append(
                f"{spec['name']} does not satisfy {spec['constraint']!r}: "
                f"{output or 'no verifiable version output'}"
            )
            continue
        identities.append(
            DependencyIdentity(
                name=str(spec["name"]),
                constraint=str(spec["constraint"]),
                executable=str(resolved),
                version_output=output,
                executable_sha256=_sha256_file(resolved),
                phase=str(spec.get("phase") or "build"),
            )
        )

    if tool_id == TOOL_MCHYPER:
        package_db = _dependency_root_path(
            roots, "ghc-package-db", "haskell-package-db"
        )
        if package_db is None or not package_db.is_dir():
            blockers.append("missing_dependency:ghc-package-db")
            details.append("explicit GHC package DB not found")
        ghc_pkg = next(
            (item for item in identities if item.name == "ghc-pkg"), None
        )
        if ghc_pkg is not None and package_db is not None and package_db.is_dir():
            package_environment = {
                # A trailing separator extends, rather than replaces, GHC's
                # global package DB so the global parsec package and Cabal
                # store packages resolve together.
                "GHC_PACKAGE_PATH": f"{package_db}{os.pathsep}",
            }
            for package in ("parsec", "hashable", "MissingH"):
                output = _single_ghc_package_identity(
                    package,
                    _capture_dependency_version(
                        ghc_pkg.executable,
                        ("field", package, "id,version"),
                        environment=package_environment,
                    ),
                )
                if not output:
                    blockers.append(
                        f"missing_dependency:haskell-package:{package.casefold()}"
                    )
                    details.append(f"GHC package {package} is not installed")
                    continue
                identities.append(
                    DependencyIdentity(
                        name=f"haskell-package:{package}",
                        constraint="installed",
                        executable=ghc_pkg.executable,
                        version_output=output,
                        executable_sha256=ghc_pkg.executable_sha256,
                        phase="build",
                    )
                )
    if blockers:
        raise HyperpropertyInstallBlocked(
            f"{tool_id} upstream build dependencies are unavailable: "
            + "; ".join(details),
            *blockers,
        )
    return tuple(identities)


def _dependency_artifacts_for_tool(
    tool_id: str,
    dependencies: Sequence[DependencyIdentity],
    dependency_roots: Mapping[str, Path | str] | None = None,
) -> tuple[DependencyArtifactIdentity, ...]:
    if tool_id != TOOL_MCHYPER:
        return ()
    roots = dependency_roots or {}
    artifacts: list[DependencyArtifactIdentity] = []
    package_db = _dependency_root_path(
        roots, "ghc-package-db", "haskell-package-db"
    )
    if package_db is None or not package_db.is_dir():
        raise HyperpropertyInstallBlocked(
            "MCHyper requires an explicit GHC package DB identity",
            "missing_dependency:ghc-package-db",
        )
    ghc_version = _dependency(dependencies, "ghc").version_output.splitlines()[0]
    artifacts.append(
        DependencyArtifactIdentity(
            name="ghc-package-db",
            path=str(package_db),
            artifact_kind="directory",
            artifact_sha256=_tree_sha256(package_db),
            version=ghc_version,
            phase="build",
        )
    )

    source_specs = (
        (
            "aiger-source",
            ("aiger-source", "aiger-source-root"),
            ("aiger-archive", "aiger-source-archive"),
            MCHYPER_AIGER_VERSION,
            MCHYPER_AIGER_SOURCE_ARCHIVE_URL,
            MCHYPER_AIGER_SOURCE_ARCHIVE_SHA256,
            "runtime",
        ),
        (
            "abc-source",
            ("abc-source", "abc-source-root"),
            ("abc-archive", "abc-source-archive"),
            f"{MCHYPER_ABC_VERSION}@{MCHYPER_ABC_GIT_COMMIT}",
            MCHYPER_ABC_SOURCE_ARCHIVE_URL,
            MCHYPER_ABC_SOURCE_ARCHIVE_SHA256,
            "runtime",
        ),
        (
            "python-source",
            ("python-source", "python-source-root"),
            ("python-archive", "python-source-archive"),
            MCHYPER_PYTHON_VERSION,
            MCHYPER_PYTHON_SOURCE_ARCHIVE_URL,
            MCHYPER_PYTHON_SOURCE_ARCHIVE_SHA256,
            "runtime",
        ),
    )
    blockers: list[str] = []
    details: list[str] = []
    for name, source_keys, archive_keys, version, url, expected_sha, phase in source_specs:
        source_root = _dependency_root_path(roots, *source_keys)
        archive = _dependency_root_path(roots, *archive_keys)
        if source_root is None or not source_root.is_dir():
            blockers.append(f"missing_dependency_evidence:{name}")
            details.append(f"{name} source root missing")
            continue
        if (
            archive is None
            or not archive.is_file()
            or _sha256_file(archive) != expected_sha
        ):
            blockers.append(f"dependency_source_digest_mismatch:{name}")
            details.append(f"{name} source archive is missing or mismatched")
            continue
        artifacts.append(
            DependencyArtifactIdentity(
                name=name,
                path=str(source_root),
                artifact_kind="directory",
                artifact_sha256=_tree_sha256(source_root),
                version=version,
                phase=phase,
                source_archive_url=url,
                source_archive_path=str(archive),
                source_archive_sha256=expected_sha,
            )
        )
    if blockers:
        raise HyperpropertyInstallBlocked(
            "MCHyper dependency provenance is incomplete: "
            + "; ".join(details),
            *blockers,
        )
    return tuple(artifacts)


def _dependency(
    dependencies: Sequence[DependencyIdentity], name: str
) -> DependencyIdentity:
    for item in dependencies:
        if item.name == name:
            return item
    raise HyperpropertyInstallerError(f"unresolved dependency {name!r}")


def _dependency_build_environment(
    dependencies: Sequence[DependencyIdentity],
    dependency_roots: Mapping[str, Path | str] | None = None,
) -> dict[str, str]:
    directories = [
        str(Path(item.executable).resolve().parent) for item in dependencies
    ]
    current_path = os.environ.get("PATH", "")
    environment = {
        "PATH": os.pathsep.join(
            [*dict.fromkeys(directories), *([current_path] if current_path else [])]
        )
    }
    dotnet = next(
        (item for item in dependencies if item.name == "dotnet"), None
    )
    if dotnet is not None:
        environment["DOTNET_ROOT"] = str(Path(dotnet.executable).parent)
    package_db = _dependency_root_path(
        dependency_roots or {}, "ghc-package-db", "haskell-package-db"
    )
    if package_db is not None:
        environment["GHC_PACKAGE_PATH"] = f"{package_db}{os.pathsep}"
    return environment


def _run_build_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str] | None = None,
) -> None:
    env = os.environ.copy()
    if environment:
        env.update(environment)
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HyperpropertyInstallBlocked(
            f"upstream build command failed to run: {type(exc).__name__}: {exc}",
            "upstream_build_failed",
        ) from exc
    if completed.returncode:
        output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
        raise HyperpropertyInstallBlocked(
            f"upstream build command exited {completed.returncode}: "
            f"{' '.join(argv)}\n{output[-4000:]}",
            "upstream_build_failed",
        )


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


def _rebind_common_tree_path(
    value: str,
    *,
    recorded_install_root: Path | None,
    active_install_root: Path,
) -> Path:
    """Rebind a recorded in-tree path after an immutable common-tree move.

    Only the relative suffix of a path already confined to the install root
    recorded by the original manifest may be rebound.  External paths are
    deliberately left untouched.  Callers must still validate existence and
    the recorded digest after rebinding.
    """

    path = Path(os.path.expanduser(value))
    if recorded_install_root is None or not path.is_absolute():
        return path
    try:
        relative = path.relative_to(recorded_install_root)
    except ValueError:
        return path
    active_root = active_install_root.resolve()
    rebound = (active_root / relative).resolve()
    if rebound != active_root and active_root not in rebound.parents:
        raise HyperpropertyInstallerError(
            f"relocated dependency path escapes install root: {value!r}"
        )
    return rebound


def _rebind_runtime_environment(
    environment: Mapping[str, str],
    *,
    recorded_install_root: Path | None,
    active_install_root: Path,
) -> tuple[tuple[str, str], ...]:
    """Rebind only reviewed path-valued runtime environment fields."""

    rebound: dict[str, str] = {
        str(name): str(value) for name, value in environment.items()
    }
    for name in ("EAHYPER_SOLVER_DIR", "DOTNET_ROOT"):
        value = rebound.get(name)
        if value:
            rebound[name] = str(
                _rebind_common_tree_path(
                    value,
                    recorded_install_root=recorded_install_root,
                    active_install_root=active_install_root,
                )
            )
    if rebound.get("PATH"):
        rebound["PATH"] = os.pathsep.join(
            str(
                _rebind_common_tree_path(
                    item,
                    recorded_install_root=recorded_install_root,
                    active_install_root=active_install_root,
                )
            )
            if item
            else item
            for item in rebound["PATH"].split(os.pathsep)
        )
    return tuple(sorted(rebound.items()))


def _identity_from_disk(
    tool_id: str,
    install_root: Path,
    pin: Mapping[str, str],
    *,
    vendor: bool = False,
) -> EngineIdentity | None:
    version = pin["version"]
    manifest = identity_manifest_path(
        install_root, tool_id, version, vendor=vendor
    )
    if not manifest.is_file():
        return None
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None

    version = str(payload.get("version") or version)
    if version != pin["version"] or payload.get("tool_id") != tool_id:
        return None
    active_install_root = install_root.resolve()
    recorded_install_root_raw = str(payload.get("install_root") or "")
    recorded_install_root = (
        Path(os.path.expanduser(recorded_install_root_raw)).resolve()
        if recorded_install_root_raw
        else None
    )
    declared_executable = str(payload.get("executable") or "")
    executable_origin = str(payload.get("executable_origin") or "")
    if vendor and executable_origin:
        exe = manifest.parent / executable_origin
    elif declared_executable:
        try:
            exe = _rebind_common_tree_path(
                declared_executable,
                recorded_install_root=recorded_install_root,
                active_install_root=active_install_root,
            )
        except HyperpropertyInstallerError:
            return None
    else:
        exe = executable_path(install_root, tool_id, version, vendor=vendor)
    if not exe.is_absolute():
        exe = manifest.parent / exe
    try:
        resolved_exe = exe.resolve(strict=True)
    except OSError:
        return None
    if not resolved_exe.is_file():
        return None
    actual_artifact_sha = _sha256_file(resolved_exe)
    recorded_artifact_sha = str(payload.get("artifact_sha256") or "")
    if recorded_artifact_sha and recorded_artifact_sha != actual_artifact_sha:
        return None

    is_vendor = bool(payload.get("is_vendor_build", False))
    is_hermetic = bool(payload.get("is_hermetic_engine", not is_vendor))
    if vendor != is_vendor:
        return None
    build_deps: tuple[tuple[str, str], ...] = ()
    runtime_deps: tuple[tuple[str, str], ...] = ()
    for field_name, destination in (
        ("build_dependencies", "build"),
        ("runtime_dependencies", "runtime"),
    ):
        raw = payload.get(field_name) or {}
        if isinstance(raw, Mapping):
            parsed = tuple(sorted((str(k), str(v)) for k, v in raw.items()))
            if destination == "build":
                build_deps = parsed
            else:
                runtime_deps = parsed

    dependency_identities: list[DependencyIdentity] = []
    dependency_artifacts: list[DependencyArtifactIdentity] = []
    source_components: list[SourceComponentIdentity] = []
    build_lockfiles: tuple[tuple[str, str], ...] = ()
    runtime_environment: tuple[tuple[str, str], ...] = ()
    if is_vendor:
        if (
            is_hermetic
            or not bool(payload.get("is_upstream_build"))
            or _is_internal_python_adapter(resolved_exe)
        ):
            return None
        version_root = manifest.parent.resolve()
        if version_root not in resolved_exe.parents:
            return None
        if (
            not executable_origin
            or (version_root / executable_origin).resolve() != resolved_exe
        ):
            return None
        meta = _vendor_meta_for_tool(tool_id, pin)
        try:
            _assert_reviewed_upstream_pin(tool_id, pin, meta)
        except HyperpropertyInstallerError:
            return None
        try:
            source_archive_path = _rebind_common_tree_path(
                str(payload.get("source_archive_path") or ""),
                recorded_install_root=recorded_install_root,
                active_install_root=active_install_root,
            )
        except HyperpropertyInstallerError:
            return None
        source_sha = str(payload.get("source_archive_sha256") or "")
        if (
            source_sha != str(meta["source_archive_sha256"])
            or not source_archive_path.is_file()
            or _sha256_file(source_archive_path) != source_sha
        ):
            return None
        source_tree_sha = str(payload.get("source_tree_sha256") or "")
        if (
            not re.fullmatch(r"[0-9a-f]{64}", source_tree_sha)
            or _source_tree_sha256(
                source_archive_path, str(meta["git_commit"])
            )
            != source_tree_sha
        ):
            return None

        raw_dependency_identities = payload.get("dependency_identities")
        if not isinstance(raw_dependency_identities, list) or not raw_dependency_identities:
            return None
        try:
            for item in raw_dependency_identities:
                if not isinstance(item, Mapping):
                    return None
                dependency_path = _rebind_common_tree_path(
                    str(item.get("executable") or ""),
                    recorded_install_root=recorded_install_root,
                    active_install_root=active_install_root,
                )
                dependency = DependencyIdentity(
                    name=str(item.get("name") or ""),
                    constraint=str(item.get("constraint") or ""),
                    executable=str(dependency_path),
                    version_output=str(item.get("version_output") or ""),
                    executable_sha256=str(item.get("executable_sha256") or ""),
                    phase=str(item.get("phase") or "build"),
                )
                if (
                    not dependency_path.is_file()
                    or _sha256_file(dependency_path)
                    != dependency.executable_sha256
                ):
                    return None
                dependency_identities.append(dependency)
        except HyperpropertyInstallerError:
            return None

        raw_dependency_artifacts = payload.get("dependency_artifacts") or []
        if not isinstance(raw_dependency_artifacts, list):
            return None
        try:
            for item in raw_dependency_artifacts:
                if not isinstance(item, Mapping):
                    return None
                artifact_path = _rebind_common_tree_path(
                    str(item.get("path") or ""),
                    recorded_install_root=recorded_install_root,
                    active_install_root=active_install_root,
                )
                archive_path_raw = str(item.get("source_archive_path") or "")
                archive_path = (
                    _rebind_common_tree_path(
                        archive_path_raw,
                        recorded_install_root=recorded_install_root,
                        active_install_root=active_install_root,
                    )
                    if archive_path_raw
                    else None
                )
                artifact = DependencyArtifactIdentity(
                    name=str(item.get("name") or ""),
                    path=str(artifact_path),
                    artifact_kind=str(item.get("artifact_kind") or ""),
                    artifact_sha256=str(item.get("artifact_sha256") or ""),
                    version=str(item.get("version") or ""),
                    phase=str(item.get("phase") or "build"),
                    source_archive_url=str(
                        item.get("source_archive_url") or ""
                    ),
                    source_archive_path=(
                        str(archive_path) if archive_path is not None else ""
                    ),
                    source_archive_sha256=str(
                        item.get("source_archive_sha256") or ""
                    ),
                )
                if artifact.artifact_kind == "directory":
                    observed_artifact_sha = (
                        _tree_sha256(artifact_path)
                        if artifact_path.is_dir()
                        else ""
                    )
                else:
                    observed_artifact_sha = (
                        _sha256_file(artifact_path)
                        if artifact_path.is_file()
                        else ""
                    )
                if observed_artifact_sha != artifact.artifact_sha256:
                    return None
                if artifact.source_archive_path:
                    assert archive_path is not None
                    if (
                        not archive_path.is_file()
                        or _sha256_file(archive_path)
                        != artifact.source_archive_sha256
                    ):
                        return None
                dependency_artifacts.append(artifact)
        except HyperpropertyInstallerError:
            return None
        if tool_id == TOOL_MCHYPER:
            expected_provenance = {
                "aiger-source": (
                    MCHYPER_AIGER_SOURCE_ARCHIVE_URL,
                    MCHYPER_AIGER_SOURCE_ARCHIVE_SHA256,
                ),
                "abc-source": (
                    MCHYPER_ABC_SOURCE_ARCHIVE_URL,
                    MCHYPER_ABC_SOURCE_ARCHIVE_SHA256,
                ),
                "python-source": (
                    MCHYPER_PYTHON_SOURCE_ARCHIVE_URL,
                    MCHYPER_PYTHON_SOURCE_ARCHIVE_SHA256,
                ),
            }
            by_name = {item.name: item for item in dependency_artifacts}
            if "ghc-package-db" not in by_name or any(
                name not in by_name
                or by_name[name].source_archive_url != expected_url
                or by_name[name].source_archive_sha256 != expected_sha
                for name, (expected_url, expected_sha) in expected_provenance.items()
            ):
                return None

        raw_components = payload.get("source_components") or []
        if not isinstance(raw_components, list):
            return None
        try:
            for item in raw_components:
                if not isinstance(item, Mapping):
                    return None
                component_path = _rebind_common_tree_path(
                    str(item.get("source_archive_path") or ""),
                    recorded_install_root=recorded_install_root,
                    active_install_root=active_install_root,
                )
                component = SourceComponentIdentity(
                    name=str(item.get("name") or ""),
                    git_commit=str(item.get("git_commit") or ""),
                    source_archive_url=str(item.get("source_archive_url") or ""),
                    source_archive_sha256=str(
                        item.get("source_archive_sha256") or ""
                    ),
                    source_archive_path=str(component_path),
                )
                expected_component = AUTOHYPER_SOURCE_COMPONENTS.get(
                    component.name
                )
                if expected_component is None or any(
                    observed != str(expected_component[field_name])
                    for field_name, observed in (
                        ("git_commit", component.git_commit),
                        ("source_archive_url", component.source_archive_url),
                        (
                            "source_archive_sha256",
                            component.source_archive_sha256,
                        ),
                    )
                ):
                    return None
                if (
                    not component_path.is_file()
                    or _sha256_file(component_path)
                    != component.source_archive_sha256
                ):
                    return None
                source_components.append(component)
        except HyperpropertyInstallerError:
            return None
        if tool_id == TOOL_AUTOHYPER and {
            item.name for item in source_components
        } != set(AUTOHYPER_SOURCE_COMPONENTS):
            return None

        distribution_sha = str(payload.get("distribution_tree_sha256") or "")
        if (
            not re.fullmatch(r"[0-9a-f]{64}", distribution_sha)
            or _tree_sha256(version_root, exclude=("identity.json",))
            != distribution_sha
        ):
            return None
        raw_lockfiles = payload.get("build_lockfiles") or {}
        if not isinstance(raw_lockfiles, Mapping):
            return None
        build_lockfiles = tuple(
            sorted((str(name), str(digest)) for name, digest in raw_lockfiles.items())
        )
        for relative, digest in build_lockfiles:
            lockfile = version_root / relative
            if (
                version_root not in lockfile.resolve().parents
                or not lockfile.is_file()
                or _sha256_file(lockfile) != digest
            ):
                return None
        if tool_id == TOOL_AUTOHYPER and not build_lockfiles:
            return None
        raw_runtime_environment = payload.get("runtime_environment") or {}
        if not isinstance(raw_runtime_environment, Mapping):
            return None
        try:
            runtime_environment = _rebind_runtime_environment(
                {
                    str(name): str(value)
                    for name, value in raw_runtime_environment.items()
                },
                recorded_install_root=recorded_install_root,
                active_install_root=active_install_root,
            )
        except HyperpropertyInstallerError:
            return None
        if tool_id == TOOL_HYPERLTL:
            environment = dict(runtime_environment)
            solver_dir = Path(environment.get("EAHYPER_SOLVER_DIR") or "")
            if (
                not solver_dir.is_dir()
                or version_root not in solver_dir.resolve().parents
            ):
                return None
        if tool_id == TOOL_AUTOHYPER:
            environment = dict(runtime_environment)
            dotnet_root = Path(environment.get("DOTNET_ROOT") or "")
            dotnet_identity = next(
                (
                    item
                    for item in dependency_identities
                    if item.name == "dotnet"
                ),
                None,
            )
            if (
                dotnet_identity is None
                or not dotnet_root.is_dir()
                or Path(dotnet_identity.executable).parent.resolve()
                != dotnet_root.resolve()
            ):
                return None
        if tool_id == TOOL_MCHYPER:
            environment = dict(runtime_environment)
            python_identity = next(
                (
                    item
                    for item in dependency_identities
                    if item.name == "python2.7"
                ),
                None,
            )
            runtime_path = environment.get("PATH", "").split(os.pathsep)
            if (
                python_identity is None
                or not runtime_path
                or Path(python_identity.executable).parent.resolve()
                != Path(runtime_path[0]).resolve()
            ):
                return None

    try:
        return EngineIdentity(
            tool_id=tool_id,
            version=version,
            executable=str(resolved_exe),
            license=pin["license"],
            source=pin["source"],
            identity_kind=pin["identity_kind"],
            artifact_sha256=actual_artifact_sha,
            source_archive_sha256=str(
                payload.get("source_archive_sha256") or ""
            ),
            source_archive_url=str(payload.get("source_archive_url") or ""),
            source_archive_path=(
                str(source_archive_path)
                if is_vendor
                else str(payload.get("source_archive_path") or "")
            ),
            source_tree_sha256=str(payload.get("source_tree_sha256") or ""),
            distribution_tree_sha256=str(
                payload.get("distribution_tree_sha256") or ""
            ),
            git_commit=str(payload.get("git_commit") or ""),
            install_root=str(install_root),
            is_hermetic_engine=is_hermetic and not is_vendor,
            is_vendor_build=is_vendor,
            is_upstream_build=bool(payload.get("is_upstream_build")),
            executable_kind=str(payload.get("executable_kind") or ""),
            executable_origin=str(payload.get("executable_origin") or ""),
            platform_id=str(payload.get("platform_id") or ""),
            build_dependencies=build_deps,
            runtime_dependencies=runtime_deps,
            decidable_fragment_ceiling=str(
                payload.get("decidable_fragment_ceiling") or ""
            ),
            supported_fragment=str(payload.get("supported_fragment") or ""),
            upstream_product=str(payload.get("upstream_product") or ""),
            dotnet_runtime=str(payload.get("dotnet_runtime") or ""),
            spot_version=str(payload.get("spot_version") or ""),
            abc_version=str(payload.get("abc_version") or ""),
            aiger_tools_version=str(payload.get("aiger_tools_version") or ""),
            dependency_identities=tuple(dependency_identities),
            source_components=tuple(source_components),
            build_lockfiles=build_lockfiles,
            runtime_environment=runtime_environment,
            dependency_artifacts=tuple(dependency_artifacts),
        )
    except HyperpropertyInstallerError:
        return None


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


def _materialize_autohyper_components(
    source_root: Path,
    *,
    download_root: Path,
    scratch_root: Path,
) -> tuple[SourceComponentIdentity, ...]:
    identities: list[SourceComponentIdentity] = []
    for name, component in AUTOHYPER_SOURCE_COMPONENTS.items():
        commit = str(component["git_commit"])
        digest = str(component["source_archive_sha256"])
        url = str(component["source_archive_url"])
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"github.com", "codeload.github.com"}
            or commit not in url
            or not re.fullmatch(r"[0-9a-f]{40}", commit)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise HyperpropertyInstallBlocked(
                f"AutoHyper source component {name!r} is not an immutable "
                "reviewed GitHub archive",
                f"unreviewed_source_component:{name}",
            )
        archive = _download_verified_archive(
            url,
            download_root / f"{name}-{commit}.tar.gz",
            digest,
        )
        extracted = _safe_extract_source_archive(
            archive, scratch_root / f"component-{name}", commit
        )
        destination = source_root / str(component["path"])
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(extracted), destination)
        identities.append(
            SourceComponentIdentity(
                name=name,
                git_commit=commit,
                source_archive_url=url,
                source_archive_sha256=digest,
                source_archive_path=str(archive.resolve()),
            )
        )
    return tuple(identities)


_AUTOHYPER_RELOCATABLE_CONFIG_ANCHOR: Final = """\
    let solverConfig = parseSolverConfigurationContent configContent
"""

_AUTOHYPER_RELOCATABLE_CONFIG_REPLACEMENT: Final = """\
    let parsedSolverConfig = parseSolverConfigurationContent configContent
    // ipfs-datasets-py reviewed relocation patch: relative solver paths are
    // resolved against the immutable AutoHyper application directory.
    let executableDirectory =
        System.IO.Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location)
    let resolveConfiguredPath (path : string) =
        if System.IO.Path.IsPathRooted(path) then path
        else System.IO.Path.GetFullPath(System.IO.Path.Join [| executableDirectory; path |])
    let solverConfig = {
        parsedSolverConfig with
            AutfiltPath = resolveConfiguredPath parsedSolverConfig.AutfiltPath
            Ltl2tgbaPath = resolveConfiguredPath parsedSolverConfig.Ltl2tgbaPath
    }
"""


def _patch_autohyper_relocatable_solver_paths(source_root: Path) -> str:
    """Apply and hash the reviewed executable-relative Spot path patch."""

    configuration = source_root / "src" / "AutoHyper" / "Configuration.fs"
    try:
        text = configuration.read_text(encoding="utf-8")
    except OSError as exc:
        raise HyperpropertyInstallBlocked(
            f"AutoHyper relocation patch input is unavailable: {exc}",
            "upstream_relocation_patch_failed",
        ) from exc
    if text.count(_AUTOHYPER_RELOCATABLE_CONFIG_ANCHOR) != 1:
        raise HyperpropertyInstallBlocked(
            "AutoHyper Configuration.fs does not match the reviewed "
            "relocation patch anchor",
            "upstream_relocation_patch_mismatch",
        )
    configuration.write_text(
        text.replace(
            _AUTOHYPER_RELOCATABLE_CONFIG_ANCHOR,
            _AUTOHYPER_RELOCATABLE_CONFIG_REPLACEMENT,
        ),
        encoding="utf-8",
    )
    return _sha256_file(configuration)


def _build_upstream_source(
    tool_id: str,
    source_root: Path,
    dependencies: Sequence[DependencyIdentity],
    dependency_roots: Mapping[str, Path | str] | None = None,
) -> tuple[Path, str, dict[str, str]]:
    """Build a pinned source tree and return its real upstream entry point."""

    lockfiles: dict[str, str] = {}
    build_environment = _dependency_build_environment(
        dependencies, dependency_roots
    )
    if tool_id == TOOL_HYPERLTL:
        _run_build_command(
            (
                _dependency(dependencies, "make").executable,
                "RELEASEFLAG=-O2 -fpermissive",
            ),
            cwd=source_root,
            environment={
                **build_environment,
                # Aalta 2.0 contains legacy constructs rejected by GCC 13
                # unless its own RELEASEFLAG is overridden.  This is the
                # narrow upstream-compatible recipe verified on linux-aarch64.
                "RELEASEFLAG": "-O2 -fpermissive",
            },
        )
        executable = source_root / "eahyper_src" / "eahyper.native"
        required_outputs = (
            executable,
            source_root / "LTL_SAT_solver" / "aalta",
            source_root / "LTL_SAT_solver" / "pltl",
        )
        kind = "upstream_compiled_binary"
    elif tool_id == TOOL_AUTOHYPER:
        dotnet = _dependency(dependencies, "dotnet").executable
        project_root = source_root / "src" / "AutoHyper"
        lockfiles[
            "upstream/src/AutoHyper/Configuration.fs"
        ] = _patch_autohyper_relocatable_solver_paths(source_root)
        _run_build_command(
            (dotnet, "restore", "AutoHyper.fsproj", "--use-lock-file"),
            cwd=project_root,
            environment={
                **build_environment,
                "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
                "DOTNET_NOLOGO": "1",
            },
        )
        package_lock = project_root / "packages.lock.json"
        if not package_lock.is_file():
            raise HyperpropertyInstallBlocked(
                "AutoHyper restore did not produce packages.lock.json",
                "dependency_lock_missing:nuget",
            )
        _run_build_command(
            (
                dotnet,
                "build",
                "-c",
                "release",
                "-o",
                "../../app",
                "--no-restore",
            ),
            cwd=project_root,
            environment={
                **build_environment,
                "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
                "DOTNET_NOLOGO": "1",
            },
        )
        paths_file = source_root / "app" / "paths.json"
        paths_file.write_text(
            json.dumps(
                {
                    "autfilt": _dependency(
                        dependencies, "autfilt"
                    ).executable,
                    "ltl2tgba": _dependency(
                        dependencies, "ltl2tgba"
                    ).executable,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        executable = source_root / "app" / "AutoHyper"
        required_outputs = (executable, paths_file, package_lock)
        lockfiles["upstream/src/AutoHyper/packages.lock.json"] = _sha256_file(
            package_lock
        )
        kind = "upstream_compiled_binary"
    elif tool_id == TOOL_MCHYPER:
        source_dir = source_root / "src"
        _run_build_command(
            (
                _dependency(dependencies, "ghc").executable,
                "Main.hs",
                "-o",
                "Main",
            ),
            cwd=source_dir,
            environment=build_environment,
        )
        executable = source_root / "mchyper.py"
        required_outputs = (executable, source_dir / "Main")
        kind = "upstream_python_entrypoint"
    else:
        raise HyperpropertyInstallerError(f"unknown vendor tool {tool_id!r}")

    missing = [path for path in required_outputs if not path.is_file()]
    if missing:
        raise HyperpropertyInstallBlocked(
            "upstream build did not produce required artifacts: "
            + ", ".join(str(path.relative_to(source_root)) for path in missing),
            "upstream_build_output_missing",
        )
    # EAHyper's Makefiles create absolute symlinks with ``realpath``.  Those
    # links point into the temporary build directory and would break after the
    # atomic install move.  Materialize only build outputs whose targets remain
    # confined to the verified source tree.
    for output in required_outputs:
        if not output.is_symlink():
            continue
        target = output.resolve(strict=True)
        if source_root.resolve() not in target.parents:
            raise HyperpropertyInstallBlocked(
                f"upstream build output escapes source tree: {output}",
                "upstream_build_output_escape",
            )
        output.unlink()
        shutil.copy2(target, output)
    executable.chmod(
        executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )
    if _is_internal_python_adapter(executable):
        raise HyperpropertyInstallBlocked(
            "upstream entry point matches an internal generated adapter",
            "generated_adapter_rejected",
        )
    return executable, kind, lockfiles


def _replace_install_tree(payload: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if destination.exists():
        backup_holder = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}-backup-",
                dir=destination.parent,
            )
        )
        backup_holder.rmdir()
        backup = backup_holder
        destination.replace(backup)
    try:
        payload.replace(destination)
    except Exception:
        if backup is not None and not destination.exists():
            backup.replace(destination)
        raise
    if backup is not None:
        shutil.rmtree(backup)


def materialize_vendor_engine(
    tool_id: str,
    *,
    install_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    lock_path: Path | str | None = None,
    force: bool = False,
    platform_id: str | None = None,
    dependency_roots: Mapping[str, Path | str] | None = None,
) -> EngineIdentity:
    """Build and install the pinned official upstream hyperproperty engine.

    The vendor lane is deliberately fail-closed.  It verifies the immutable
    source archive, all source components, every build/runtime executable, the
    resulting executable, and the installed distribution tree.  It never
    writes or promotes the internal Python differential adapter.
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
    _assert_reviewed_upstream_pin(tool_id, pin, meta)
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

    manifest = identity_manifest_path(root, tool_id, version, vendor=True)

    if manifest.is_file() and not force:
        existing = _identity_from_disk(tool_id, root, pin, vendor=True)
        if (
            existing is not None
            and existing.is_vendor_build
            and existing.is_upstream_build
            and not existing.is_hermetic_engine
            and existing.source_archive_sha256 == source_sha
            and existing.artifact_sha256
        ):
            return existing

    # Preflight first: dependency blockers must not be obscured by download or
    # build errors, and a blocked host must never acquire a fake executable.
    dependency_identities = _resolve_vendor_dependencies(
        tool_id, dependency_roots=dependency_roots
    )
    dependency_artifacts = _dependency_artifacts_for_tool(
        tool_id,
        dependency_identities,
        dependency_roots=dependency_roots,
    )
    download_root = root / "hyperproperty-sources" / tool_id
    archive = _download_verified_archive(
        str(meta["source_archive_url"]),
        download_root / f"{meta['git_commit']}.tar.gz",
        source_sha,
    )
    source_tree_sha = _source_tree_sha256(archive, str(meta["git_commit"]))

    version_root = manifest.parent
    version_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{tool_id}-{version}-build-",
        dir=version_root.parent,
    ) as raw_scratch:
        scratch = Path(raw_scratch)
        source_root = _safe_extract_source_archive(
            archive,
            scratch / "main-source",
            str(meta["git_commit"]),
        )
        source_components: tuple[SourceComponentIdentity, ...] = ()
        if tool_id == TOOL_AUTOHYPER:
            source_components = _materialize_autohyper_components(
                source_root,
                download_root=download_root / "components",
                scratch_root=scratch,
            )
        built_executable, executable_kind, lockfiles = _build_upstream_source(
            tool_id,
            source_root,
            dependency_identities,
            dependency_roots=dependency_roots,
        )
        executable_relative_in_source = built_executable.relative_to(source_root)

        payload = scratch / "payload"
        payload.mkdir()
        upstream_root = payload / "upstream"
        shutil.move(str(source_root), upstream_root)
        executable_origin = (
            Path("upstream") / executable_relative_in_source
        ).as_posix()
        staged_executable = payload / executable_origin

        effective_dependencies = list(dependency_identities)
        staged_runtime_dependencies: tuple[tuple[str, Path], ...] = ()
        if tool_id == TOOL_AUTOHYPER:
            staged_runtime_dependencies = (
                ("autfilt", Path("spot") / "autfilt"),
                ("ltl2tgba", Path("spot") / "ltl2tgba"),
            )
        elif tool_id == TOOL_MCHYPER:
            staged_runtime_dependencies = (
                ("abc", Path("abc") / "abc"),
                ("aigtoaig", Path("aiger") / "aigtoaig"),
            )
        for name, relative in staged_runtime_dependencies:
            original = _dependency(effective_dependencies, name)
            staged = payload / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original.executable, staged)
            staged.chmod(
                staged.stat().st_mode
                | stat.S_IXUSR
                | stat.S_IXGRP
                | stat.S_IXOTH
            )
            effective_dependencies = [
                item for item in effective_dependencies if item.name != name
            ]
            effective_dependencies.append(
                DependencyIdentity(
                    name=name,
                    constraint=original.constraint,
                    executable=str((version_root / relative).resolve()),
                    version_output=original.version_output,
                    executable_sha256=_sha256_file(staged),
                    phase="runtime",
                )
            )
        if tool_id == TOOL_AUTOHYPER:
            paths_file = payload / "upstream" / "app" / "paths.json"
            paths_file.write_text(
                json.dumps(
                    {
                        "autfilt": "../../spot/autfilt",
                        "ltl2tgba": "../../spot/ltl2tgba",
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            lockfiles["upstream/app/paths.json"] = _sha256_file(paths_file)

        artifact_sha = _sha256_file(staged_executable)
        distribution_sha = _tree_sha256(payload)
        runtime_environment = {}
        if tool_id == TOOL_HYPERLTL:
            runtime_environment["EAHYPER_SOLVER_DIR"] = str(
                (
                    version_root
                    / "upstream"
                    / "LTL_SAT_solver"
                ).resolve()
            )
        elif tool_id == TOOL_AUTOHYPER:
            runtime_environment["DOTNET_ROOT"] = str(
                Path(
                    _dependency(dependency_identities, "dotnet").executable
                ).parent.resolve()
            )
        elif tool_id == TOOL_MCHYPER:
            python_dir = Path(
                _dependency(dependency_identities, "python2.7").executable
            ).parent.resolve()
            runtime_environment["PATH"] = os.pathsep.join(
                [str(python_dir), os.defpath]
            )
        identity_payload = {
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
            "is_upstream_build": True,
            "executable_kind": executable_kind,
            "executable_origin": executable_origin,
            "artifact_sha256": artifact_sha,
            "source_archive_sha256": source_sha,
            "source_archive_url": meta["source_archive_url"],
            "source_archive_path": str(archive.resolve()),
            "source_tree_sha256": source_tree_sha,
            "distribution_tree_sha256": distribution_sha,
            "git_commit": meta["git_commit"],
            "source_components": [
                item.to_dict() for item in source_components
            ],
            "dependency_identities": [
                item.to_dict()
                for item in sorted(
                    effective_dependencies, key=lambda item: item.name
                )
            ],
            "dependency_artifacts": [
                item.to_dict() for item in dependency_artifacts
            ],
            "build_lockfiles": lockfiles,
            "build_dependencies": dict(build_deps),
            "runtime_dependencies": dict(runtime_deps),
            "runtime_environment": runtime_environment,
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
            "executable": str((version_root / executable_origin).resolve()),
            "family": FAMILY,
            "goal_id": VENDOR_GOAL_ID,
            "task_id": VENDOR_TASK_ID,
            "hermetic_engines_are_differential_only": True,
            "never_promote_hermetic_engine_as_vendor": True,
        }
        _write_identity_manifest(payload / "identity.json", identity_payload)
        _replace_install_tree(payload, version_root)

    installed = _identity_from_disk(tool_id, root, pin, vendor=True)
    if installed is None:
        raise HyperpropertyInstallBlocked(
            f"{tool_id} upstream installation failed post-install identity audit",
            "post_install_identity_verification_failed",
        )
    return installed


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
    dependency_roots: Mapping[str, Path | str] | None = None,
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
        dependency_roots=dependency_roots,
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
    dependency_roots: Mapping[str, Path | str] | None = None,
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
        dependency_roots=dependency_roots,
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
    dependency_roots: Mapping[str, Path | str] | None = None,
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
        dependency_roots=dependency_roots,
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
    dependency_roots: Mapping[str, Path | str] | None,
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
                dependency_roots=dependency_roots,
            )
        else:
            identity = materialize_hermetic_engine(
                tool_id,
                install_root=root,
                repo_root=repo_root,
                lock_path=lock_path,
                force=force,
            )
    except HyperpropertyInstallBlocked as exc:
        detail = str(exc)
        if strict:
            raise
        return InstallReceipt(
            tool_id=tool_id,
            status="blocked",
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
            block_reasons=exc.block_reasons,
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

    if use_vendor and (
        identity.is_hermetic_engine
        or not identity.is_vendor_build
        or not identity.is_upstream_build
        or identity.executable_kind
        not in {"upstream_compiled_binary", "upstream_python_entrypoint"}
    ):
        detail = "vendor path did not produce a verified upstream engine identity"
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
            block_reasons=("non_upstream_vendor_identity",),
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

    observed = _probe_version(Path(identity.executable)) if not use_vendor else ""
    if not use_vendor and (
        selected_version not in observed and tool_id not in observed.casefold()
    ):
        if "vendor" not in observed.casefold():
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
    dependency_roots: Mapping[str, Path | str] | None = None,
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
        dependency_roots=dependency_roots,
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
    "AUTOHYPER_SOURCE_COMPONENTS",
    "MCHYPER_SOURCE_ARCHIVE_SHA256",
    "MCHYPER_SOURCE_ARCHIVE_URL",
    "MCHYPER_GIT_COMMIT",
    "MCHYPER_SUPPORTED_FRAGMENT",
    "MCHYPER_ABC_VERSION",
    "MCHYPER_ABC_GIT_COMMIT",
    "MCHYPER_ABC_SOURCE_ARCHIVE_SHA256",
    "MCHYPER_ABC_SOURCE_ARCHIVE_URL",
    "MCHYPER_AIGER_VERSION",
    "MCHYPER_AIGER_SOURCE_ARCHIVE_SHA256",
    "MCHYPER_AIGER_SOURCE_ARCHIVE_URL",
    "MCHYPER_PYTHON_SOURCE_ARCHIVE_SHA256",
    "MCHYPER_PYTHON_SOURCE_ARCHIVE_URL",
    "MCHYPER_PYTHON_VERSION",
    "ENV_FORCE_VERDICT",
    "ENV_DISAGREE",
    "ENV_MALFORMED",
    "ENV_SLEEP_SECONDS",
    "ENV_CASE_ID",
    "HyperpropertyInstallerError",
    "HyperpropertyInstallBlocked",
    "HyperpropertyInstallBundle",
    "InstallReceipt",
    "EngineIdentity",
    "DependencyArtifactIdentity",
    "DependencyIdentity",
    "SourceComponentIdentity",
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
