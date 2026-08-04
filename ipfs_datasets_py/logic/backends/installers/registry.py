"""FormalVerificationInstallerRegistry@1 — family plugin map for deployment locks.

``FormalVerificationDeploymentLock@2`` (FVT-G110 / FVT-041) turns every remaining
declared installation gap and incomplete managed pin into a reviewed, licensed,
per-platform, explicitly invoked deployment contract.  This module is the sole
metadata registry that binds those contracts to **family installer plugins**.

``LogicVerificationLazyInstaller@1`` (FVT-G216 / FVT-087) resolves install plans
exclusively through this registry: SMT (solver), ATP, state models, protocols
(tamarin/proverif), kernels (rocq/isabelle/lean), hyperproperties, authorization,
Runtime MTL, advisors, and ZKP.  Authorization never infers permission from a
probe; capability discovery and import remain non-mutating.

Importing this module is pure data.  It never:

* downloads or installs tools;
* opens network sockets;
* probes the host filesystem for executables;
* mutates system package managers;
* loads plugin modules eagerly.

Downstream tasks (FVT-042+) own the per-family plugin modules
(``state_model``, ``tamarin``, ``proverif``, ...).  This registry only declares
the mapping so packaging gates and offline certification can prove that every
reviewed lock entry has an installer entry without performing installation.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

FORMAL_VERIFICATION_DEPLOYMENT_LOCK_INTERFACE: Final = (
    "FormalVerificationDeploymentLock@2"
)
FORMAL_VERIFICATION_INSTALLER_REGISTRY_INTERFACE: Final = (
    "FormalVerificationInstallerRegistry@1"
)
DEPLOYMENT_LOCK_SCHEMA: Final = "formal-verification-deployment-lock/v2"
INSTALLER_ENTRY_SCHEMA: Final = "formal-verification-installer-entry/v1"
INSTALLER_PLUGIN_SCHEMA: Final = "formal-verification-installer-plugin/v1"
GOAL_ID: Final = "FVT-G110"
TASK_ID: Final = "FVT-041"
PROGRAM: Final = "formal-verification-tactician/toolchain-locks"

# Default lock path relative to a monorepo / worktree root.
DEFAULT_LOCK_RELATIVE: Final = Path("config/formal_verification_toolchains.lock.json")

# User-local install root advertised by the deployment lock (never system-wide).
DEFAULT_USER_LOCAL_INSTALL_ROOT: Final = (
    "~/.local/share/ipfs_datasets_py/theorem-provers"
)

# Supported platform matrix (matches deployment lock platform_policy).
SUPPORTED_PLATFORMS: Final[frozenset[str]] = frozenset(
    {
        "linux-x86_64",
        "linux-aarch64",
        "darwin-x86_64",
        "darwin-arm64",
    }
)


class InstallerRegistryError(ValueError):
    """Raised when installer registry metadata or install policy is violated."""


class InstallerPluginFamily(StrEnum):
    """Closed set of family installer plugins (downstream modules)."""

    SOLVER = "solver"
    ATP = "atp"
    STATE_MODEL = "state_model"
    TAMARIN = "tamarin"
    PROVERIF = "proverif"
    ROCQ = "rocq"
    ISABELLE = "isabelle"
    HYPERPROPERTY = "hyperproperty"
    AUTHORIZATION = "authorization"
    RUNTIME_MTL = "runtime_mtl"
    ADVISORS = "advisors"
    KERNEL = "kernel"
    ZKP = "zkp"


class InstallerPublicRole(StrEnum):
    """Public dispatch role for a registry tool (FVT-G227 role closure)."""

    AUTHORITY = "authority"
    ADVISOR = "advisor"
    SHADOW = "shadow"
    SUPPORT = "support"
    ARCHIVAL_INTAKE = "archival_intake"


# Closed dispatch surface vocabulary exposed on installer entries.
DISPATCH_INVENTORY: Final = "inventory"
DISPATCH_PROBE: Final = "probe"
DISPATCH_INSTALL: Final = "install"
DISPATCH_VERIFICATION: Final = "verification"
DISPATCH_ADVISOR: Final = "advisor"
DISPATCH_ARTIFACT_INTAKE: Final = "artifact_intake"
DISPATCH_COMPATIBILITY_LOOKUP: Final = "compatibility_lookup"

CLOSED_DISPATCH_SURFACES: Final[frozenset[str]] = frozenset(
    {
        DISPATCH_INVENTORY,
        DISPATCH_PROBE,
        DISPATCH_INSTALL,
        DISPATCH_VERIFICATION,
        DISPATCH_ADVISOR,
        DISPATCH_ARTIFACT_INTAKE,
        DISPATCH_COMPATIBILITY_LOOKUP,
    }
)

_AUTHORITY_SURFACES: Final[tuple[str, ...]] = (
    DISPATCH_INVENTORY,
    DISPATCH_PROBE,
    DISPATCH_INSTALL,
    DISPATCH_VERIFICATION,
)
_ADVISOR_SURFACES: Final[tuple[str, ...]] = (
    DISPATCH_INVENTORY,
    DISPATCH_PROBE,
    DISPATCH_INSTALL,
    DISPATCH_ADVISOR,
)
_SHADOW_SURFACES: Final[tuple[str, ...]] = (
    DISPATCH_INVENTORY,
    DISPATCH_PROBE,
    DISPATCH_INSTALL,
    DISPATCH_VERIFICATION,
)
_SUPPORT_SURFACES: Final[tuple[str, ...]] = (
    DISPATCH_INVENTORY,
    DISPATCH_PROBE,
    DISPATCH_INSTALL,
)
_ARCHIVAL_SURFACES: Final[tuple[str, ...]] = (
    DISPATCH_INVENTORY,
    DISPATCH_INSTALL,
    DISPATCH_ARTIFACT_INTAKE,
    DISPATCH_COMPATIBILITY_LOOKUP,
)

# Explicit support-only companions (semantic / authority / public verification N/A).
SUPPORT_ONLY_TOOL_IDS: Final[frozenset[str]] = frozenset(
    {
        "stack",
        "temurin-jdk",
        "maude",
        "opam",
    }
)


# Planned plugin module paths.  Modules are not imported here; downstream
# tasks materialize them.  Paths are stable contracts for packaging evidence.
PLUGIN_MODULE_PATHS: Final[Mapping[str, str]] = MappingProxyType(
    {
        InstallerPluginFamily.SOLVER.value: (
            "ipfs_datasets_py.logic.backends.installers.solver"
        ),
        InstallerPluginFamily.ATP.value: (
            "ipfs_datasets_py.logic.backends.installers.atp"
        ),
        InstallerPluginFamily.STATE_MODEL.value: (
            "ipfs_datasets_py.logic.backends.installers.state_model"
        ),
        InstallerPluginFamily.TAMARIN.value: (
            "ipfs_datasets_py.logic.backends.installers.tamarin"
        ),
        InstallerPluginFamily.PROVERIF.value: (
            "ipfs_datasets_py.logic.backends.installers.proverif"
        ),
        InstallerPluginFamily.ROCQ.value: (
            "ipfs_datasets_py.logic.backends.installers.rocq"
        ),
        InstallerPluginFamily.ISABELLE.value: (
            "ipfs_datasets_py.logic.backends.installers.isabelle"
        ),
        InstallerPluginFamily.HYPERPROPERTY.value: (
            "ipfs_datasets_py.logic.backends.installers.hyperproperty"
        ),
        InstallerPluginFamily.AUTHORIZATION.value: (
            "ipfs_datasets_py.logic.backends.installers.authorization"
        ),
        InstallerPluginFamily.RUNTIME_MTL.value: (
            "ipfs_datasets_py.logic.backends.installers.runtime_mtl"
        ),
        InstallerPluginFamily.ADVISORS.value: (
            "ipfs_datasets_py.logic.backends.installers.advisors"
        ),
        InstallerPluginFamily.KERNEL.value: (
            "ipfs_datasets_py.logic.backends.installers.kernel"
        ),
        InstallerPluginFamily.ZKP.value: (
            "ipfs_datasets_py.logic.backends.installers.zkp"
        ),
    }
)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise InstallerRegistryError(f"{label} must be a non-empty trimmed string")
    if "\x00" in value:
        raise InstallerRegistryError(f"{label} must not contain NUL bytes")
    return value


def _optional_text(value: object, label: str) -> str:
    if value in ("", None):
        return ""
    return _text(value, label)


@dataclass(frozen=True, slots=True)
class InstallerPlugin:
    """One family installer plugin declaration (module not imported)."""

    family: InstallerPluginFamily
    module_path: str
    description: str
    schema_version: str = INSTALLER_PLUGIN_SCHEMA

    def __post_init__(self) -> None:
        family = (
            self.family
            if isinstance(self.family, InstallerPluginFamily)
            else InstallerPluginFamily(str(self.family))
        )
        object.__setattr__(self, "family", family)
        object.__setattr__(
            self, "module_path", _text(self.module_path, "module_path")
        )
        object.__setattr__(
            self, "description", _text(self.description, "description")
        )
        if self.schema_version != INSTALLER_PLUGIN_SCHEMA:
            raise InstallerRegistryError(
                f"plugin schema must be {INSTALLER_PLUGIN_SCHEMA}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "family": self.family.value,
            "module_path": self.module_path,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class InstallerEntry:
    """Binding of one tool to a family plugin and ensure_* entrypoint name.

    Metadata only: ``ensure_name`` is the planned function name on the plugin
    module.  Calling install is never performed by this registry.
    """

    tool_id: str
    family: InstallerPluginFamily
    ensure_name: str
    license: str
    source: str
    identity_kind: str
    requires_explicit_yes: bool = True
    user_local_only: bool = True
    never_on_import: bool = True
    never_on_capability_discovery: bool = True
    requires_checksum_for_managed_artifacts: bool = True
    replaces_gap_id: str = ""
    public_role: InstallerPublicRole = InstallerPublicRole.AUTHORITY
    semantic_axis_applicable: bool = True
    authority_axis_applicable: bool = True
    public_verification_applicable: bool = True
    dispatch_surfaces: tuple[str, ...] = _AUTHORITY_SURFACES
    schema_version: str = INSTALLER_ENTRY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_id", _text(self.tool_id, "tool_id"))
        family = (
            self.family
            if isinstance(self.family, InstallerPluginFamily)
            else InstallerPluginFamily(str(self.family))
        )
        object.__setattr__(self, "family", family)
        public_role = (
            self.public_role
            if isinstance(self.public_role, InstallerPublicRole)
            else InstallerPublicRole(str(self.public_role))
        )
        object.__setattr__(self, "public_role", public_role)
        object.__setattr__(
            self, "ensure_name", _text(self.ensure_name, "ensure_name")
        )
        object.__setattr__(self, "license", _text(self.license, "license"))
        object.__setattr__(self, "source", _text(self.source, "source"))
        object.__setattr__(
            self, "identity_kind", _text(self.identity_kind, "identity_kind")
        )
        object.__setattr__(
            self,
            "replaces_gap_id",
            _optional_text(self.replaces_gap_id, "replaces_gap_id"),
        )
        for name in (
            "requires_explicit_yes",
            "user_local_only",
            "never_on_import",
            "never_on_capability_discovery",
            "requires_checksum_for_managed_artifacts",
            "semantic_axis_applicable",
            "authority_axis_applicable",
            "public_verification_applicable",
        ):
            if not isinstance(getattr(self, name), bool):
                raise InstallerRegistryError(f"{name} must be a boolean")
        for name in (
            "requires_explicit_yes",
            "user_local_only",
            "never_on_import",
            "never_on_capability_discovery",
            "requires_checksum_for_managed_artifacts",
        ):
            if not getattr(self, name):
                raise InstallerRegistryError(
                    f"installer entry is fail-closed; {name} must remain true"
                )
        surfaces = tuple(str(item) for item in self.dispatch_surfaces)
        if not surfaces:
            raise InstallerRegistryError(
                f"dispatch_surfaces for {self.tool_id!r} must not be empty"
            )
        unknown = sorted(set(surfaces) - CLOSED_DISPATCH_SURFACES)
        if unknown:
            raise InstallerRegistryError(
                f"unknown dispatch surfaces for {self.tool_id!r}: {unknown}"
            )
        if len(surfaces) != len(set(surfaces)):
            raise InstallerRegistryError(
                f"duplicate dispatch surfaces for {self.tool_id!r}"
            )
        object.__setattr__(self, "dispatch_surfaces", surfaces)
        if self.schema_version != INSTALLER_ENTRY_SCHEMA:
            raise InstallerRegistryError(
                f"installer entry schema must be {INSTALLER_ENTRY_SCHEMA}"
            )
        if not self.ensure_name.startswith("ensure_"):
            raise InstallerRegistryError(
                f"ensure_name for {self.tool_id!r} must start with 'ensure_'"
            )
        self._assert_role_axis_invariants()

    def _assert_role_axis_invariants(self) -> None:
        """Fail closed when public role and axis applicability disagree."""

        role = self.public_role
        surfaces = set(self.dispatch_surfaces)
        if role is InstallerPublicRole.SUPPORT:
            if self.tool_id not in SUPPORT_ONLY_TOOL_IDS and self.tool_id not in {
                "stack",
                "temurin-jdk",
                "maude",
                "opam",
            }:
                # Still allow support role for declared support companions.
                pass
            if (
                self.semantic_axis_applicable
                or self.authority_axis_applicable
                or self.public_verification_applicable
            ):
                raise InstallerRegistryError(
                    f"support tool {self.tool_id!r} must mark semantic, "
                    "authority, and public-verification axes not applicable"
                )
            if DISPATCH_VERIFICATION in surfaces or DISPATCH_ADVISOR in surfaces:
                raise InstallerRegistryError(
                    f"support tool {self.tool_id!r} cannot expose verification "
                    "or advisor dispatch"
                )
        elif role is InstallerPublicRole.ARCHIVAL_INTAKE:
            if (
                self.semantic_axis_applicable
                or self.authority_axis_applicable
                or self.public_verification_applicable
            ):
                raise InstallerRegistryError(
                    f"archival intake tool {self.tool_id!r} cannot claim "
                    "semantic, authority, or public-verification axes"
                )
            if DISPATCH_VERIFICATION in surfaces or DISPATCH_ADVISOR in surfaces:
                raise InstallerRegistryError(
                    f"archival intake tool {self.tool_id!r} cannot expose live "
                    "verification or advisor dispatch"
                )
            if DISPATCH_ARTIFACT_INTAKE not in surfaces:
                raise InstallerRegistryError(
                    f"archival intake tool {self.tool_id!r} must expose "
                    f"{DISPATCH_ARTIFACT_INTAKE}"
                )
        elif role is InstallerPublicRole.ADVISOR:
            if self.authority_axis_applicable or self.public_verification_applicable:
                raise InstallerRegistryError(
                    f"advisor tool {self.tool_id!r} cannot claim authority or "
                    "public-verification axes"
                )
            if DISPATCH_ADVISOR not in surfaces:
                raise InstallerRegistryError(
                    f"advisor tool {self.tool_id!r} must expose advisor dispatch"
                )
            if DISPATCH_VERIFICATION in surfaces:
                raise InstallerRegistryError(
                    f"advisor tool {self.tool_id!r} cannot expose verification dispatch"
                )
        elif role is InstallerPublicRole.SHADOW:
            if self.authority_axis_applicable:
                raise InstallerRegistryError(
                    f"shadow tool {self.tool_id!r} cannot claim authority axis"
                )
            if DISPATCH_VERIFICATION not in surfaces:
                raise InstallerRegistryError(
                    f"shadow tool {self.tool_id!r} must expose verification dispatch"
                )
        elif role is InstallerPublicRole.AUTHORITY:
            if not (
                self.semantic_axis_applicable
                and self.authority_axis_applicable
                and self.public_verification_applicable
            ):
                raise InstallerRegistryError(
                    f"authority tool {self.tool_id!r} must apply semantic, "
                    "authority, and public-verification axes"
                )
            if DISPATCH_VERIFICATION not in surfaces:
                raise InstallerRegistryError(
                    f"authority tool {self.tool_id!r} must expose verification dispatch"
                )

    @property
    def module_path(self) -> str:
        return PLUGIN_MODULE_PATHS[self.family.value]

    @property
    def support_only(self) -> bool:
        return self.public_role is InstallerPublicRole.SUPPORT

    @property
    def is_live_verification_provider(self) -> bool:
        return (
            self.public_verification_applicable
            and DISPATCH_VERIFICATION in self.dispatch_surfaces
            and self.public_role
            in {InstallerPublicRole.AUTHORITY, InstallerPublicRole.SHADOW}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tool_id": self.tool_id,
            "family": self.family.value,
            "ensure_name": self.ensure_name,
            "module_path": self.module_path,
            "license": self.license,
            "source": self.source,
            "identity_kind": self.identity_kind,
            "requires_explicit_yes": self.requires_explicit_yes,
            "user_local_only": self.user_local_only,
            "never_on_import": self.never_on_import,
            "never_on_capability_discovery": self.never_on_capability_discovery,
            "requires_checksum_for_managed_artifacts": (
                self.requires_checksum_for_managed_artifacts
            ),
            "replaces_gap_id": self.replaces_gap_id,
            "public_role": self.public_role.value,
            "support_only": self.support_only,
            "semantic_axis_applicable": self.semantic_axis_applicable,
            "authority_axis_applicable": self.authority_axis_applicable,
            "public_verification_applicable": self.public_verification_applicable,
            "dispatch_surfaces": list(self.dispatch_surfaces),
            "is_live_verification_provider": self.is_live_verification_provider,
        }


def _entry(
    tool_id: str,
    family: InstallerPluginFamily,
    ensure_name: str,
    *,
    license: str,
    source: str,
    identity_kind: str,
    replaces_gap_id: str = "",
    public_role: InstallerPublicRole = InstallerPublicRole.AUTHORITY,
    semantic_axis_applicable: bool | None = None,
    authority_axis_applicable: bool | None = None,
    public_verification_applicable: bool | None = None,
    dispatch_surfaces: tuple[str, ...] | None = None,
) -> InstallerEntry:
    role = public_role
    if semantic_axis_applicable is None:
        semantic_axis_applicable = role in {
            InstallerPublicRole.AUTHORITY,
            InstallerPublicRole.SHADOW,
        }
    if authority_axis_applicable is None:
        authority_axis_applicable = role is InstallerPublicRole.AUTHORITY
    if public_verification_applicable is None:
        public_verification_applicable = role in {
            InstallerPublicRole.AUTHORITY,
            InstallerPublicRole.SHADOW,
        }
    if dispatch_surfaces is None:
        dispatch_surfaces = {
            InstallerPublicRole.AUTHORITY: _AUTHORITY_SURFACES,
            InstallerPublicRole.ADVISOR: _ADVISOR_SURFACES,
            InstallerPublicRole.SHADOW: _SHADOW_SURFACES,
            InstallerPublicRole.SUPPORT: _SUPPORT_SURFACES,
            InstallerPublicRole.ARCHIVAL_INTAKE: _ARCHIVAL_SURFACES,
        }[role]
    return InstallerEntry(
        tool_id=tool_id,
        family=family,
        ensure_name=ensure_name,
        license=license,
        source=source,
        identity_kind=identity_kind,
        replaces_gap_id=replaces_gap_id,
        public_role=role,
        semantic_axis_applicable=semantic_axis_applicable,
        authority_axis_applicable=authority_axis_applicable,
        public_verification_applicable=public_verification_applicable,
        dispatch_surfaces=dispatch_surfaces,
    )


def _build_default_plugins() -> tuple[InstallerPlugin, ...]:
    descriptions = {
        InstallerPluginFamily.SOLVER: "SMT solver managed pins (Z3, CVC5)",
        InstallerPluginFamily.ATP: "First-order ATP pins (Vampire, E)",
        InstallerPluginFamily.STATE_MODEL: "TLA+/Apalache/TLC state-model plugins",
        InstallerPluginFamily.TAMARIN: "Tamarin + Maude + Stack protocol plugins",
        InstallerPluginFamily.PROVERIF: "Isolated OPAM ProVerif plugin",
        InstallerPluginFamily.ROCQ: "Isolated OPAM Rocq/Coq + OPAM bootstrap",
        InstallerPluginFamily.ISABELLE: "Isabelle kernel plugin",
        InstallerPluginFamily.HYPERPROPERTY: "HyperLTL / AutoHyper / MCHyper plugins",
        InstallerPluginFamily.AUTHORIZATION: "External Soufflé / SecPAL plugins",
        InstallerPluginFamily.RUNTIME_MTL: "External Runtime MTL parity plugin",
        InstallerPluginFamily.ADVISORS: "SymbolicAI / ErgoAI / advisor plugins",
        InstallerPluginFamily.KERNEL: "Lean kernel / elan plugin",
        InstallerPluginFamily.ZKP: "Secret-safe ZKP deployment binding plugin",
    }
    return tuple(
        InstallerPlugin(
            family=family,
            module_path=PLUGIN_MODULE_PATHS[family.value],
            description=descriptions[family],
        )
        for family in InstallerPluginFamily
    )


def _build_default_entries() -> tuple[InstallerEntry, ...]:
    """Closed installer entry inventory for reviewed deployment locks.

    Tools that remain in-process or host-optional (java) intentionally have no
    installer entry.  Formerly declared gaps now have explicit ensure_* names
    so packaging evidence can prove the gap→contract replacement.
    """

    return (
        _entry(
            "z3",
            InstallerPluginFamily.SOLVER,
            "ensure_z3",
            license="MIT",
            source="https://github.com/Z3Prover/z3",
            identity_kind="python_package",
        ),
        _entry(
            "cvc5",
            InstallerPluginFamily.SOLVER,
            "ensure_cvc5",
            license="BSD-3-Clause",
            source="https://github.com/cvc5/cvc5",
            identity_kind="release_archive",
        ),
        _entry(
            "vampire",
            InstallerPluginFamily.ATP,
            "ensure_vampire",
            license="BSD-3-Clause",
            source="https://github.com/vprover/vampire",
            identity_kind="release_archive",
        ),
        _entry(
            "eprover",
            InstallerPluginFamily.ATP,
            "ensure_eprover",
            license="GPL-2.0-or-later",
            source="https://wwwlehre.dhbw-stuttgart.de/~sschulz/E/E.html",
            identity_kind="release_archive",
        ),
        _entry(
            "apalache",
            InstallerPluginFamily.STATE_MODEL,
            "ensure_apalache",
            license="Apache-2.0",
            source="https://github.com/apalache-mc/apalache",
            identity_kind="release_archive",
        ),
        _entry(
            "tlc",
            InstallerPluginFamily.STATE_MODEL,
            "ensure_tlc",
            license="MIT",
            source="https://github.com/tlaplus/tlaplus",
            identity_kind="immutable_release_tag",
            replaces_gap_id="tlc",
        ),
        _entry(
            "tamarin",
            InstallerPluginFamily.TAMARIN,
            "ensure_tamarin",
            license="GPL-3.0-or-later",
            source="https://github.com/tamarin-prover/tamarin-prover",
            identity_kind="release_archive",
        ),
        _entry(
            "maude",
            InstallerPluginFamily.TAMARIN,
            "ensure_maude",
            license="GPL-3.0-or-later",
            source="https://github.com/maude-lang/Maude",
            identity_kind="release_archive",
            public_role=InstallerPublicRole.SUPPORT,
        ),
        _entry(
            "stack",
            InstallerPluginFamily.TAMARIN,
            "ensure_stack",
            license="BSD-3-Clause",
            source="https://github.com/commercialhaskell/stack",
            identity_kind="release_archive",
            public_role=InstallerPublicRole.SUPPORT,
        ),
        _entry(
            "proverif",
            InstallerPluginFamily.PROVERIF,
            "ensure_proverif",
            license="GPL-2.0-or-later",
            source="https://proverif.inria.fr/",
            identity_kind="release_archive",
        ),
        _entry(
            "lean",
            InstallerPluginFamily.KERNEL,
            "ensure_lean",
            license="Apache-2.0",
            source="https://github.com/leanprover/lean4",
            identity_kind="immutable_toolchain_identity",
        ),
        _entry(
            "coq",
            InstallerPluginFamily.ROCQ,
            "ensure_coq",
            license="LGPL-2.1-only",
            source="https://rocq-prover.org/",
            identity_kind="opam_package",
        ),
        _entry(
            "opam",
            InstallerPluginFamily.ROCQ,
            "ensure_opam",
            license="LGPL-2.1-only",
            source="https://github.com/ocaml/opam",
            identity_kind="release_archive",
            public_role=InstallerPublicRole.SUPPORT,
        ),
        _entry(
            "isabelle",
            InstallerPluginFamily.ISABELLE,
            "ensure_isabelle",
            license="BSD-3-Clause",
            source="https://isabelle.in.tum.de/",
            identity_kind="release_archive",
        ),
        _entry(
            "hyperltl",
            InstallerPluginFamily.HYPERPROPERTY,
            "ensure_hyperltl",
            license="MIT",
            source="https://github.com/reactive-systems/hyperltl",
            identity_kind="immutable_source_tag",
            replaces_gap_id="hyper_tools",
        ),
        _entry(
            "autohyper",
            InstallerPluginFamily.HYPERPROPERTY,
            "ensure_autohyper",
            license="MIT",
            source="https://github.com/reactive-systems/hyperltl",
            identity_kind="immutable_source_tag",
            replaces_gap_id="hyper_tools",
        ),
        _entry(
            "mchyper",
            InstallerPluginFamily.HYPERPROPERTY,
            "ensure_mchyper",
            license="MIT",
            source="https://github.com/reactive-systems/hyperltl",
            identity_kind="immutable_source_tag",
            replaces_gap_id="hyper_tools",
        ),
        _entry(
            "souffle",
            InstallerPluginFamily.AUTHORIZATION,
            "ensure_souffle",
            license="UPL-1.0",
            source="https://github.com/souffle-lang/souffle",
            identity_kind="immutable_source_tag",
            replaces_gap_id="datalog_secpal_external",
            public_role=InstallerPublicRole.SHADOW,
        ),
        _entry(
            "secpal",
            InstallerPluginFamily.AUTHORIZATION,
            "ensure_secpal",
            license="MS-PL",
            source="https://www.microsoft.com/en-us/research/project/secpal/",
            identity_kind="operator_bound_artifact",
            replaces_gap_id="datalog_secpal_external",
            public_role=InstallerPublicRole.ARCHIVAL_INTAKE,
        ),
        _entry(
            "runtime-mtl-external",
            InstallerPluginFamily.RUNTIME_MTL,
            "ensure_runtime_mtl_external",
            license="Apache-2.0",
            source="ipfs_datasets_py/typescript/logic-runtime-mtl",
            identity_kind="typescript_package",
            replaces_gap_id="runtime_mtl_external",
            public_role=InstallerPublicRole.AUTHORITY,
        ),
        _entry(
            "symbolicai",
            InstallerPluginFamily.ADVISORS,
            "ensure_symbolicai",
            license="BSD-3-Clause",
            source="https://github.com/ExtensityAI/symbolicai",
            identity_kind="python_package",
            public_role=InstallerPublicRole.ADVISOR,
        ),
        _entry(
            "ergoai",
            InstallerPluginFamily.ADVISORS,
            "ensure_ergoai",
            license="Apache-2.0",
            source="https://github.com/ErgoAI/ErgoEngine",
            identity_kind="immutable_release_tag",
            public_role=InstallerPublicRole.ADVISOR,
        ),
        _entry(
            "temurin-jdk",
            InstallerPluginFamily.ADVISORS,
            "ensure_temurin_jdk",
            license="GPL-2.0-with-classpath-exception",
            source="https://adoptium.net/",
            identity_kind="immutable_release_archive",
            public_role=InstallerPublicRole.SUPPORT,
        ),
        _entry(
            "zkp-circuit",
            InstallerPluginFamily.ZKP,
            "ensure_zkp_circuit",
            license="Apache-2.0",
            source="config/formal_verification_zkp_deployment.lock.json",
            identity_kind="deployment_artifact_schema",
            replaces_gap_id="circuit_witness",
        ),
    )


@dataclass(frozen=True, slots=True)
class FormalVerificationInstallerRegistry:
    """Closed installer registry bound to FormalVerificationDeploymentLock@2."""

    plugins: tuple[InstallerPlugin, ...]
    entries: tuple[InstallerEntry, ...]
    interface: str = FORMAL_VERIFICATION_INSTALLER_REGISTRY_INTERFACE
    deployment_lock_interface: str = FORMAL_VERIFICATION_DEPLOYMENT_LOCK_INTERFACE
    goal_id: str = GOAL_ID
    task_id: str = TASK_ID
    program: str = PROGRAM
    user_local_install_root: str = DEFAULT_USER_LOCAL_INSTALL_ROOT
    supported_platforms: frozenset[str] = SUPPORTED_PLATFORMS

    def __post_init__(self) -> None:
        if self.interface != FORMAL_VERIFICATION_INSTALLER_REGISTRY_INTERFACE:
            raise InstallerRegistryError(
                f"interface must be {FORMAL_VERIFICATION_INSTALLER_REGISTRY_INTERFACE}"
            )
        if self.deployment_lock_interface != (
            FORMAL_VERIFICATION_DEPLOYMENT_LOCK_INTERFACE
        ):
            raise InstallerRegistryError(
                "deployment_lock_interface must be "
                f"{FORMAL_VERIFICATION_DEPLOYMENT_LOCK_INTERFACE}"
            )
        object.__setattr__(self, "plugins", tuple(self.plugins))
        object.__setattr__(self, "entries", tuple(self.entries))
        tool_ids = [entry.tool_id for entry in self.entries]
        if len(tool_ids) != len(set(tool_ids)):
            raise InstallerRegistryError("duplicate installer tool_id entries")
        families = {plugin.family for plugin in self.plugins}
        for entry in self.entries:
            if entry.family not in families:
                raise InstallerRegistryError(
                    f"installer entry {entry.tool_id!r} references unknown "
                    f"plugin family {entry.family.value!r}"
                )

    def get(self, tool_id: str) -> InstallerEntry:
        for entry in self.entries:
            if entry.tool_id == tool_id:
                return entry
        raise InstallerRegistryError(f"no installer entry for tool_id={tool_id!r}")

    def list_tool_ids(self) -> tuple[str, ...]:
        return tuple(entry.tool_id for entry in self.entries)

    def entries_replacing_gaps(self) -> tuple[InstallerEntry, ...]:
        return tuple(entry for entry in self.entries if entry.replaces_gap_id)

    def plugin_for(self, family: InstallerPluginFamily | str) -> InstallerPlugin:
        resolved = (
            family
            if isinstance(family, InstallerPluginFamily)
            else InstallerPluginFamily(str(family))
        )
        for plugin in self.plugins:
            if plugin.family is resolved:
                return plugin
        raise InstallerRegistryError(f"no plugin for family={resolved.value!r}")

    def assert_platform_supported(self, platform: str) -> None:
        """Refuse unsupported platforms explicitly (fail-closed)."""

        platform_text = _text(platform, "platform")
        if platform_text not in self.supported_platforms:
            raise InstallerRegistryError(
                f"unsupported platform {platform_text!r}; supported platforms are "
                f"{sorted(self.supported_platforms)}; install and production "
                "certification are refused"
            )

    def authorize_install(
        self,
        tool_id: str,
        *,
        yes: bool,
        explicit_call: bool = True,
        import_context: bool = False,
        capability_discovery: bool = False,
        checksum_verified: bool | None = None,
        platform: str | None = None,
        system_package_mutation: bool = False,
        test_mode: bool = False,
    ) -> InstallerEntry:
        """Fail-closed install authorization for a reviewed lock entry.

        Never performs installation.  Callers must still invoke the family
        plugin with ``yes=True`` after this gate succeeds.
        """

        entry = self.get(tool_id)
        if import_context:
            raise InstallerRegistryError(
                f"install of {tool_id!r} is forbidden during import"
            )
        if capability_discovery:
            raise InstallerRegistryError(
                f"install of {tool_id!r} is forbidden during capability discovery"
            )
        if not explicit_call:
            raise InstallerRegistryError(
                f"install of {tool_id!r} requires an explicit install call"
            )
        if not yes:
            raise InstallerRegistryError(
                f"install of {tool_id!r} requires yes=True opt-in"
            )
        if system_package_mutation and (test_mode or entry.user_local_only):
            raise InstallerRegistryError(
                f"install of {tool_id!r} forbids system package manager mutation "
                "(user-local installs only)"
            )
        if platform is not None:
            self.assert_platform_supported(platform)
        if (
            entry.requires_checksum_for_managed_artifacts
            and checksum_verified is False
        ):
            raise InstallerRegistryError(
                f"install of {tool_id!r} requires checksum verification for "
                "managed artifacts"
            )
        return entry

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "deployment_lock_interface": self.deployment_lock_interface,
            "goal_id": self.goal_id,
            "task_id": self.task_id,
            "program": self.program,
            "user_local_install_root": self.user_local_install_root,
            "supported_platforms": sorted(self.supported_platforms),
            "plugins": [plugin.to_dict() for plugin in self.plugins],
            "entries": [entry.to_dict() for entry in self.entries],
            "replaced_gap_ids": sorted(
                {
                    entry.replaces_gap_id
                    for entry in self.entries
                    if entry.replaces_gap_id
                }
            ),
        }


def build_default_installer_registry() -> FormalVerificationInstallerRegistry:
    return FormalVerificationInstallerRegistry(
        plugins=_build_default_plugins(),
        entries=_build_default_entries(),
    )


_DEFAULT_REGISTRY: FormalVerificationInstallerRegistry | None = None


def default_installer_registry() -> FormalVerificationInstallerRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_default_installer_registry()
    return _DEFAULT_REGISTRY


def reset_default_installer_registry() -> None:
    """Test helper: drop the cached default registry."""

    global _DEFAULT_REGISTRY
    _DEFAULT_REGISTRY = None


def list_installer_entries() -> tuple[InstallerEntry, ...]:
    return default_installer_registry().entries


def list_installer_tool_ids() -> tuple[str, ...]:
    return default_installer_registry().list_tool_ids()


def get_installer_entry(tool_id: str) -> InstallerEntry:
    return default_installer_registry().get(tool_id)


def list_installer_plugins() -> tuple[InstallerPlugin, ...]:
    return default_installer_registry().plugins


def install_is_forbidden_on_import() -> bool:
    return True


def registry_side_effect_free_on_import() -> bool:
    """Packaging gate: importing the registry must never install or download."""

    return True


def network_forbidden_during_offline_certification() -> bool:
    return True


def system_package_mutation_forbidden_in_tests() -> bool:
    return True


def authorize_installer_entry_install(
    tool_id: str,
    *,
    yes: bool,
    explicit_call: bool = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    checksum_verified: bool | None = None,
    platform: str | None = None,
    system_package_mutation: bool = False,
    test_mode: bool = False,
) -> InstallerEntry:
    return default_installer_registry().authorize_install(
        tool_id,
        yes=yes,
        explicit_call=explicit_call,
        import_context=import_context,
        capability_discovery=capability_discovery,
        checksum_verified=checksum_verified,
        platform=platform,
        system_package_mutation=system_package_mutation,
        test_mode=test_mode,
    )


def resolve_lock_path(repo_root: Path | str | None = None) -> Path:
    """Resolve the deployment lock path without reading it."""

    if repo_root is None:
        # Prefer walk-up from this file: .../ipfs_datasets_py/ipfs_datasets_py/logic/...
        here = Path(__file__).resolve()
        candidates = [
            here.parents[5],  # monorepo root when nested under ipfs_datasets_py/
            here.parents[4],
            Path.cwd(),
        ]
        for candidate in candidates:
            lock = candidate / DEFAULT_LOCK_RELATIVE
            if lock.is_file():
                return lock
        return Path.cwd() / DEFAULT_LOCK_RELATIVE
    return Path(repo_root) / DEFAULT_LOCK_RELATIVE


@lru_cache(maxsize=4)
def _load_lock_cached(lock_path: str) -> Mapping[str, Any]:
    path = Path(lock_path)
    if not path.is_file():
        raise InstallerRegistryError(f"deployment lock missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InstallerRegistryError("deployment lock root must be an object")
    return MappingProxyType(payload)


def load_deployment_lock(
    repo_root: Path | str | None = None,
    *,
    lock_path: Path | str | None = None,
) -> Mapping[str, Any]:
    """Load FormalVerificationDeploymentLock@2 (read-only, no install)."""

    path = Path(lock_path) if lock_path is not None else resolve_lock_path(repo_root)
    return _load_lock_cached(str(path.resolve()))


def clear_deployment_lock_cache() -> None:
    _load_lock_cached.cache_clear()


def assert_deployment_lock_contract(
    lock: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
) -> Mapping[str, Any]:
    """Validate the deployment lock shape against FormalVerificationDeploymentLock@2."""

    payload = lock if lock is not None else load_deployment_lock(repo_root)
    if payload.get("interface") != FORMAL_VERIFICATION_DEPLOYMENT_LOCK_INTERFACE:
        raise InstallerRegistryError(
            "lock interface must be "
            f"{FORMAL_VERIFICATION_DEPLOYMENT_LOCK_INTERFACE}"
        )
    if payload.get("schema_version") != DEPLOYMENT_LOCK_SCHEMA:
        raise InstallerRegistryError(
            f"lock schema_version must be {DEPLOYMENT_LOCK_SCHEMA}"
        )
    if payload.get("installer_registry_interface") != (
        FORMAL_VERIFICATION_INSTALLER_REGISTRY_INTERFACE
    ):
        raise InstallerRegistryError(
            "lock installer_registry_interface must be "
            f"{FORMAL_VERIFICATION_INSTALLER_REGISTRY_INTERFACE}"
        )
    install_policy = payload.get("install_policy")
    if not isinstance(install_policy, Mapping):
        raise InstallerRegistryError("lock install_policy must be an object")
    for key in (
        "never_on_import",
        "never_on_capability_discovery",
        "requires_explicit_yes",
        "requires_checksum_for_managed_artifacts",
        "forbid_system_package_mutation_in_tests",
        "user_local_only",
    ):
        if install_policy.get(key) is not True:
            raise InstallerRegistryError(
                f"lock install_policy.{key} must be true (fail-closed)"
            )
    offline = payload.get("offline_verification_policy")
    if not isinstance(offline, Mapping):
        raise InstallerRegistryError(
            "lock offline_verification_policy must be an object"
        )
    for key in (
        "forbid_install",
        "forbid_download",
        "forbid_network",
        "forbid_system_package_mutation",
    ):
        if offline.get(key) is not True:
            raise InstallerRegistryError(
                f"lock offline_verification_policy.{key} must be true"
            )
    platform_policy = payload.get("platform_policy")
    if not isinstance(platform_policy, Mapping):
        raise InstallerRegistryError("lock platform_policy must be an object")
    if platform_policy.get("unsupported_platforms_fail_closed") is not True:
        raise InstallerRegistryError(
            "platform_policy.unsupported_platforms_fail_closed must be true"
        )
    zkp = payload.get("zkp_deployment_artifact_schema")
    if not isinstance(zkp, Mapping) or zkp.get("secret_safe") is not True:
        raise InstallerRegistryError(
            "zkp_deployment_artifact_schema.secret_safe must be true"
        )
    if zkp.get("forbid_private_witness_in_lock") is not True:
        raise InstallerRegistryError(
            "zkp_deployment_artifact_schema.forbid_private_witness_in_lock "
            "must be true"
        )
    return payload


def assert_registry_aligned_with_lock(
    lock: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
    registry: FormalVerificationInstallerRegistry | None = None,
) -> None:
    """Every registry installer entry must appear on the deployment lock."""

    payload = assert_deployment_lock_contract(lock, repo_root=repo_root)
    reg = registry or default_installer_registry()
    tools = payload.get("tools")
    if not isinstance(tools, Sequence):
        raise InstallerRegistryError("lock tools must be a list")
    by_id: dict[str, Mapping[str, Any]] = {}
    for item in tools:
        if not isinstance(item, Mapping):
            raise InstallerRegistryError("each lock tool must be an object")
        tool_id = item.get("tool_id")
        if not isinstance(tool_id, str) or not tool_id:
            raise InstallerRegistryError("lock tool_id must be a non-empty string")
        by_id[tool_id] = item
    for entry in reg.entries:
        if entry.tool_id not in by_id:
            raise InstallerRegistryError(
                f"installer entry {entry.tool_id!r} missing from deployment lock"
            )
        tool = by_id[entry.tool_id]
        installer_entry = tool.get("installer_entry")
        if installer_entry != entry.ensure_name:
            raise InstallerRegistryError(
                f"lock tool {entry.tool_id!r} installer_entry "
                f"{installer_entry!r} != registry ensure_name {entry.ensure_name!r}"
            )
        if tool.get("gap_id") not in (None, ""):
            raise InstallerRegistryError(
                f"lock tool {entry.tool_id!r} still carries gap_id="
                f"{tool.get('gap_id')!r}; deployment lock must replace gaps"
            )
        license_value = tool.get("license") or ""
        if not license_value:
            raise InstallerRegistryError(
                f"lock tool {entry.tool_id!r} missing reviewed license"
            )
        source_value = tool.get("source") or ""
        if not source_value:
            raise InstallerRegistryError(
                f"lock tool {entry.tool_id!r} missing reviewed source"
            )


def reviewed_tools_requiring_installer_entries() -> frozenset[str]:
    """Tools listed in FVT-G110 acceptance that must carry installer entries."""

    return frozenset(
        {
            "tlc",
            "hyperltl",
            "autohyper",
            "mchyper",
            "souffle",
            "secpal",
            "runtime-mtl-external",
            "vampire",
            "lean",
            "coq",
            "isabelle",
            "opam",
            "symbolicai",
            "ergoai",
            "zkp-circuit",
        }
    )


def assert_acceptance_tools_have_installer_entries(
    registry: FormalVerificationInstallerRegistry | None = None,
) -> None:
    reg = registry or default_installer_registry()
    present = set(reg.list_tool_ids())
    missing = sorted(reviewed_tools_requiring_installer_entries() - present)
    if missing:
        raise InstallerRegistryError(
            "acceptance tools missing installer entries: " + ", ".join(missing)
        )


def resolve_installer_implementation(
    tool_id: str,
    *,
    import_callable: bool = False,
    registry: FormalVerificationInstallerRegistry | None = None,
) -> dict[str, Any]:
    """Resolve one registry entry to a real module/ensure binding.

    Metadata resolution never imports plugins.  When ``import_callable`` is
    true, the named ensure_* symbol must be a real callable (still never
    invoked).  Placeholder dispatch is refused.
    """

    reg = registry or default_installer_registry()
    entry = reg.get(tool_id)
    ensure_name = entry.ensure_name
    if ensure_name in {
        "ensure_placeholder",
        "ensure_not_implemented",
        "ensure_todo",
    } or ensure_name.endswith("_placeholder"):
        raise InstallerRegistryError(
            f"installer entry {tool_id!r} resolves to placeholder dispatch "
            f"{ensure_name!r}"
        )
    payload: dict[str, Any] = {
        "tool_id": entry.tool_id,
        "family": entry.family.value,
        "module_path": entry.module_path,
        "ensure_name": ensure_name,
        "public_role": entry.public_role.value,
        "support_only": entry.support_only,
        "dispatch_surfaces": list(entry.dispatch_surfaces),
        "placeholder": False,
        "callable_resolved": False,
    }
    if not import_callable:
        return payload
    import importlib

    module = importlib.import_module(entry.module_path)
    ensure = getattr(module, ensure_name, None)
    if not callable(ensure):
        raise InstallerRegistryError(
            f"installer entry {tool_id!r} module {entry.module_path!r} does not "
            f"export callable {ensure_name!r}"
        )
    payload["callable_resolved"] = True
    return payload


def assert_installer_entries_resolve_to_callables(
    registry: FormalVerificationInstallerRegistry | None = None,
) -> tuple[dict[str, Any], ...]:
    """Prove every registry entry binds a real ensure_* implementation."""

    reg = registry or default_installer_registry()
    resolved: list[dict[str, Any]] = []
    for tool_id in reg.list_tool_ids():
        resolved.append(
            resolve_installer_implementation(
                tool_id, import_callable=True, registry=reg
            )
        )
    return tuple(resolved)


def list_installer_entries_by_role(
    public_role: InstallerPublicRole | str,
    *,
    registry: FormalVerificationInstallerRegistry | None = None,
) -> tuple[InstallerEntry, ...]:
    role = (
        public_role
        if isinstance(public_role, InstallerPublicRole)
        else InstallerPublicRole(str(public_role))
    )
    reg = registry or default_installer_registry()
    return tuple(entry for entry in reg.entries if entry.public_role is role)


def support_only_installer_tool_ids(
    registry: FormalVerificationInstallerRegistry | None = None,
) -> frozenset[str]:
    reg = registry or default_installer_registry()
    return frozenset(
        entry.tool_id for entry in reg.entries if entry.support_only
    )


__all__ = [
    "CLOSED_DISPATCH_SURFACES",
    "DEFAULT_LOCK_RELATIVE",
    "DEFAULT_USER_LOCAL_INSTALL_ROOT",
    "DEPLOYMENT_LOCK_SCHEMA",
    "DISPATCH_ADVISOR",
    "DISPATCH_ARTIFACT_INTAKE",
    "DISPATCH_COMPATIBILITY_LOOKUP",
    "DISPATCH_INSTALL",
    "DISPATCH_INVENTORY",
    "DISPATCH_PROBE",
    "DISPATCH_VERIFICATION",
    "FORMAL_VERIFICATION_DEPLOYMENT_LOCK_INTERFACE",
    "FORMAL_VERIFICATION_INSTALLER_REGISTRY_INTERFACE",
    "FormalVerificationInstallerRegistry",
    "GOAL_ID",
    "INSTALLER_ENTRY_SCHEMA",
    "INSTALLER_PLUGIN_SCHEMA",
    "InstallerEntry",
    "InstallerPlugin",
    "InstallerPluginFamily",
    "InstallerPublicRole",
    "InstallerRegistryError",
    "PLUGIN_MODULE_PATHS",
    "PROGRAM",
    "SUPPORTED_PLATFORMS",
    "SUPPORT_ONLY_TOOL_IDS",
    "TASK_ID",
    "assert_acceptance_tools_have_installer_entries",
    "assert_deployment_lock_contract",
    "assert_installer_entries_resolve_to_callables",
    "assert_registry_aligned_with_lock",
    "authorize_installer_entry_install",
    "build_default_installer_registry",
    "clear_deployment_lock_cache",
    "default_installer_registry",
    "get_installer_entry",
    "install_is_forbidden_on_import",
    "list_installer_entries",
    "list_installer_entries_by_role",
    "list_installer_plugins",
    "list_installer_tool_ids",
    "load_deployment_lock",
    "network_forbidden_during_offline_certification",
    "registry_side_effect_free_on_import",
    "reset_default_installer_registry",
    "resolve_installer_implementation",
    "resolve_lock_path",
    "reviewed_tools_requiring_installer_entries",
    "support_only_installer_tool_ids",
    "system_package_mutation_forbidden_in_tests",
]
