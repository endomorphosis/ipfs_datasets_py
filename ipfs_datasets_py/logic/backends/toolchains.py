"""Pinned verification toolchain registry and install/isolation policy.

``VerificationToolchainRegistry@1`` is the single declarative surface for:

* explicit pinned tool discovery and installation metadata for every provider;
* resource classes used by portfolio scheduling and process bounds;
* process-isolation, secret, and witness-handling contracts;
* declared gaps for tools that are not yet installable with pins/checksums.

Importing this module is pure data.  It never downloads, installs, probes the
filesystem, launches a process, mutates package managers, or writes disk state.
Installation remains opt-in through the bridges installer or the lazy
execution path, both of which require explicit enablement and ``yes=True``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

VERIFICATION_TOOLCHAIN_REGISTRY_VERSION: Final = "VerificationToolchainRegistry@1"
TOOLCHAIN_DESCRIPTOR_SCHEMA: Final = "verification-toolchain-descriptor/v1"
TOOLCHAIN_PIN_SCHEMA: Final = "verification-toolchain-pin/v1"
TOOLCHAIN_DEPENDENCY_SCHEMA: Final = "verification-toolchain-dependency/v1"
TOOLCHAIN_ISOLATION_SCHEMA: Final = "verification-toolchain-isolation/v1"
TOOLCHAIN_SECRET_POLICY_SCHEMA: Final = "verification-toolchain-secret-policy/v1"
TOOLCHAIN_WITNESS_POLICY_SCHEMA: Final = "verification-toolchain-witness-policy/v1"
TOOLCHAIN_GAP_SCHEMA: Final = "verification-toolchain-gap/v1"
INSTALL_POLICY_SCHEMA: Final = "verification-toolchain-install-policy/v1"


class ToolchainError(ValueError):
    """Raised when toolchain metadata or install policy is violated."""


class ToolchainResourceClass(StrEnum):
    """Operational resource classes for verification providers."""

    CPU_SMALL = "cpu-small"
    CPU_VALIDATION = "cpu-validation"
    SOLVER = "solver"
    ATP = "atp"
    MODEL_CHECKER = "model-checker"
    JVM = "jvm"
    OPAM = "opam"
    KERNEL = "kernel"
    PROTOCOL = "protocol"
    HYPERPROPERTY = "hyperproperty"
    AUTHORIZATION = "authorization"
    MONITOR = "monitor"
    ADVISOR = "advisor"
    CIRCUIT = "circuit"


class ToolRuntimeFamily(StrEnum):
    """Runtime families that must be bound before execution."""

    NATIVE = "native"
    PYTHON = "python"
    JVM = "jvm"
    OPAM = "opam"
    WASM = "wasm"
    IN_PROCESS = "in_process"
    TYPESCRIPT = "typescript"


class InstallAvailability(StrEnum):
    """How a provider obtains its tool, if at all."""

    MANAGED_PIN = "managed_pin"
    PYTHON_PACKAGE = "python_package"
    IN_PROCESS = "in_process"
    DECLARED_GAP = "declared_gap"
    EXTERNAL_OPTIONAL = "external_optional"
    ADVISOR_ONLY = "advisor_only"


class InstallGapKind(StrEnum):
    """Closed vocabulary of install gaps that must remain explicit."""

    TLC = "tlc"
    HYPER_TOOLS = "hyper_tools"
    DATALOG_SECPAL_EXTERNAL = "datalog_secpal_external"
    RUNTIME_MTL_EXTERNAL = "runtime_mtl_external"
    CIRCUIT_WITNESS = "circuit_witness"


class DependencyKind(StrEnum):
    """Host or companion dependencies that must be bound to a toolchain."""

    JVM = "jvm"
    OPAM = "opam"
    MAUDE = "maude"
    JAVA = "java"
    CIRCUIT = "circuit"
    STACK = "stack"
    ELAN = "elan"
    PYTHON = "python"
    NODE = "node"


class IsolationMode(StrEnum):
    """Process isolation modes enforced by the shared lifecycle."""

    PRIVATE_WORKSPACE = "private_workspace"
    PROCESS_GROUP = "process_group"
    RESOURCE_LIMITS = "resource_limits"
    PATH_CONTAINMENT = "path_containment"
    OUTPUT_BOUNDS = "output_bounds"
    ENVIRONMENT_MINIMAL = "environment_minimal"
    SECRET_REDACTION = "secret_redaction"
    WITNESS_REDACTION = "witness_redaction"


@dataclass(frozen=True, slots=True)
class ToolPin:
    """One reviewed, checksummed install artifact identity."""

    tool_id: str
    version: str
    artifact_url: str = ""
    sha256: str = ""
    platform: str = "any"
    notes: str = ""
    schema_version: str = TOOLCHAIN_PIN_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_id", _text(self.tool_id, "tool_id"))
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(
            self, "artifact_url", _optional_text(self.artifact_url, "artifact_url")
        )
        object.__setattr__(self, "sha256", _optional_text(self.sha256, "sha256"))
        object.__setattr__(self, "platform", _text(self.platform, "platform"))
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        if self.schema_version != TOOLCHAIN_PIN_SCHEMA:
            raise ToolchainError(
                f"tool pin schema must be {TOOLCHAIN_PIN_SCHEMA}"
            )
        if self.sha256 and (
            len(self.sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.sha256)
        ):
            raise ToolchainError(
                f"sha256 for {self.tool_id!r} must be a lowercase hex digest"
            )

    @property
    def is_checksummed(self) -> bool:
        return bool(self.sha256) and bool(self.artifact_url)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tool_id": self.tool_id,
            "version": self.version,
            "artifact_url": self.artifact_url,
            "sha256": self.sha256,
            "platform": self.platform,
            "notes": self.notes,
            "is_checksummed": self.is_checksummed,
        }


@dataclass(frozen=True, slots=True)
class ToolchainDependency:
    """Companion dependency required by a provider (JVM, opam, Maude, ...)."""

    kind: DependencyKind
    required: bool
    description: str
    bound_tool_ids: tuple[str, ...] = ()
    schema_version: str = TOOLCHAIN_DEPENDENCY_SCHEMA

    def __post_init__(self) -> None:
        kind = (
            self.kind
            if isinstance(self.kind, DependencyKind)
            else DependencyKind(str(self.kind))
        )
        object.__setattr__(self, "kind", kind)
        if not isinstance(self.required, bool):
            raise ToolchainError("dependency.required must be a boolean")
        object.__setattr__(
            self, "description", _text(self.description, "description")
        )
        object.__setattr__(
            self,
            "bound_tool_ids",
            tuple(_text(item, "bound_tool_id") for item in self.bound_tool_ids),
        )
        if self.schema_version != TOOLCHAIN_DEPENDENCY_SCHEMA:
            raise ToolchainError(
                f"dependency schema must be {TOOLCHAIN_DEPENDENCY_SCHEMA}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "required": self.required,
            "description": self.description,
            "bound_tool_ids": list(self.bound_tool_ids),
        }


@dataclass(frozen=True, slots=True)
class IsolationPolicy:
    """Process isolation and containment contract for a toolchain."""

    modes: tuple[IsolationMode, ...]
    private_workspace: bool = True
    process_group_termination: bool = True
    path_traversal_rejected: bool = True
    secret_redaction: bool = True
    witness_redaction: bool = True
    shell_disabled: bool = True
    max_output_bytes: int = 1_048_576
    schema_version: str = TOOLCHAIN_ISOLATION_SCHEMA

    def __post_init__(self) -> None:
        modes = tuple(
            mode if isinstance(mode, IsolationMode) else IsolationMode(str(mode))
            for mode in self.modes
        )
        if not modes:
            raise ToolchainError("isolation policy requires at least one mode")
        object.__setattr__(self, "modes", modes)
        for name in (
            "private_workspace",
            "process_group_termination",
            "path_traversal_rejected",
            "secret_redaction",
            "witness_redaction",
            "shell_disabled",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ToolchainError(f"{name} must be a boolean")
        if (
            isinstance(self.max_output_bytes, bool)
            or not isinstance(self.max_output_bytes, int)
            or self.max_output_bytes <= 0
        ):
            raise ToolchainError("max_output_bytes must be a positive integer")
        if self.schema_version != TOOLCHAIN_ISOLATION_SCHEMA:
            raise ToolchainError(
                f"isolation schema must be {TOOLCHAIN_ISOLATION_SCHEMA}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "modes": [mode.value for mode in self.modes],
            "private_workspace": self.private_workspace,
            "process_group_termination": self.process_group_termination,
            "path_traversal_rejected": self.path_traversal_rejected,
            "secret_redaction": self.secret_redaction,
            "witness_redaction": self.witness_redaction,
            "shell_disabled": self.shell_disabled,
            "max_output_bytes": self.max_output_bytes,
        }


@dataclass(frozen=True, slots=True)
class SecretHandlingPolicy:
    """How secrets are kept out of argv, logs, caches, and witnesses."""

    redact_argv: bool = True
    redact_environment: bool = True
    redact_stdout: bool = True
    redact_stderr: bool = True
    redact_output_files: bool = True
    redact_errors: bool = True
    forbid_secret_cache_keys: bool = True
    schema_version: str = TOOLCHAIN_SECRET_POLICY_SCHEMA

    def __post_init__(self) -> None:
        for name in (
            "redact_argv",
            "redact_environment",
            "redact_stdout",
            "redact_stderr",
            "redact_output_files",
            "redact_errors",
            "forbid_secret_cache_keys",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ToolchainError(f"{name} must be a boolean")
        if self.schema_version != TOOLCHAIN_SECRET_POLICY_SCHEMA:
            raise ToolchainError(
                f"secret policy schema must be {TOOLCHAIN_SECRET_POLICY_SCHEMA}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "redact_argv": self.redact_argv,
            "redact_environment": self.redact_environment,
            "redact_stdout": self.redact_stdout,
            "redact_stderr": self.redact_stderr,
            "redact_output_files": self.redact_output_files,
            "redact_errors": self.redact_errors,
            "forbid_secret_cache_keys": self.forbid_secret_cache_keys,
        }


@dataclass(frozen=True, slots=True)
class WitnessHandlingPolicy:
    """Private witness and counterexample materialization rules."""

    allow_private_witness_in_logs: bool = False
    allow_private_witness_in_cache_keys: bool = False
    redacted_public_references_only: bool = True
    bind_witness_to_source_digest: bool = True
    schema_version: str = TOOLCHAIN_WITNESS_POLICY_SCHEMA

    def __post_init__(self) -> None:
        for name in (
            "allow_private_witness_in_logs",
            "allow_private_witness_in_cache_keys",
            "redacted_public_references_only",
            "bind_witness_to_source_digest",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ToolchainError(f"{name} must be a boolean")
        if self.allow_private_witness_in_logs or self.allow_private_witness_in_cache_keys:
            raise ToolchainError(
                "private witnesses must not appear in logs or cache keys"
            )
        if not self.redacted_public_references_only:
            raise ToolchainError(
                "witness policy must expose only redacted public references"
            )
        if self.schema_version != TOOLCHAIN_WITNESS_POLICY_SCHEMA:
            raise ToolchainError(
                f"witness policy schema must be {TOOLCHAIN_WITNESS_POLICY_SCHEMA}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "allow_private_witness_in_logs": self.allow_private_witness_in_logs,
            "allow_private_witness_in_cache_keys": (
                self.allow_private_witness_in_cache_keys
            ),
            "redacted_public_references_only": self.redacted_public_references_only,
            "bind_witness_to_source_digest": self.bind_witness_to_source_digest,
        }


@dataclass(frozen=True, slots=True)
class InstallPolicy:
    """Fail-closed rules for every install entry point."""

    never_on_import: bool = True
    never_on_capability_discovery: bool = True
    requires_explicit_yes: bool = True
    requires_pin_or_declared_gap: bool = True
    requires_checksum_for_managed_artifacts: bool = True
    forbid_system_package_mutation_in_tests: bool = True
    forbid_curl_pipe_shell: bool = True
    schema_version: str = INSTALL_POLICY_SCHEMA

    def __post_init__(self) -> None:
        for name in (
            "never_on_import",
            "never_on_capability_discovery",
            "requires_explicit_yes",
            "requires_pin_or_declared_gap",
            "requires_checksum_for_managed_artifacts",
            "forbid_system_package_mutation_in_tests",
            "forbid_curl_pipe_shell",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ToolchainError(f"{name} must be a boolean")
            if not getattr(self, name):
                raise ToolchainError(
                    f"install policy is fail-closed; {name} must remain true"
                )
        if self.schema_version != INSTALL_POLICY_SCHEMA:
            raise ToolchainError(
                f"install policy schema must be {INSTALL_POLICY_SCHEMA}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "never_on_import": self.never_on_import,
            "never_on_capability_discovery": self.never_on_capability_discovery,
            "requires_explicit_yes": self.requires_explicit_yes,
            "requires_pin_or_declared_gap": self.requires_pin_or_declared_gap,
            "requires_checksum_for_managed_artifacts": (
                self.requires_checksum_for_managed_artifacts
            ),
            "forbid_system_package_mutation_in_tests": (
                self.forbid_system_package_mutation_in_tests
            ),
            "forbid_curl_pipe_shell": self.forbid_curl_pipe_shell,
        }


@dataclass(frozen=True, slots=True)
class InstallGap:
    """Explicit declaration that a provider has no managed install path yet."""

    gap_id: InstallGapKind
    provider_ids: tuple[str, ...]
    reason: str
    fallback: str
    schema_version: str = TOOLCHAIN_GAP_SCHEMA

    def __post_init__(self) -> None:
        gap_id = (
            self.gap_id
            if isinstance(self.gap_id, InstallGapKind)
            else InstallGapKind(str(self.gap_id))
        )
        object.__setattr__(self, "gap_id", gap_id)
        providers = tuple(
            _text(item, "provider_id") for item in self.provider_ids
        )
        if not providers:
            raise ToolchainError("install gap requires at least one provider_id")
        object.__setattr__(self, "provider_ids", providers)
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(self, "fallback", _text(self.fallback, "fallback"))
        if self.schema_version != TOOLCHAIN_GAP_SCHEMA:
            raise ToolchainError(f"gap schema must be {TOOLCHAIN_GAP_SCHEMA}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "gap_id": self.gap_id.value,
            "provider_ids": list(self.provider_ids),
            "reason": self.reason,
            "fallback": self.fallback,
        }


@dataclass(frozen=True, slots=True)
class ToolchainDescriptor:
    """Complete install, resource, isolation, and gap metadata for one provider."""

    provider_id: str
    display_name: str
    executable_candidates: tuple[str, ...]
    resource_class: ToolchainResourceClass
    runtime: ToolRuntimeFamily
    availability: InstallAvailability
    installer_entry: str = ""
    pins: tuple[ToolPin, ...] = ()
    dependencies: tuple[ToolchainDependency, ...] = ()
    gap: InstallGap | None = None
    families: tuple[str, ...] = ()
    isolation: IsolationPolicy = field(
        default_factory=lambda: DEFAULT_ISOLATION_POLICY
    )
    secret_policy: SecretHandlingPolicy = field(
        default_factory=SecretHandlingPolicy
    )
    witness_policy: WitnessHandlingPolicy = field(
        default_factory=WitnessHandlingPolicy
    )
    notes: str = ""
    schema_version: str = TOOLCHAIN_DESCRIPTOR_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider_id", _text(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self, "display_name", _text(self.display_name, "display_name")
        )
        object.__setattr__(
            self,
            "executable_candidates",
            tuple(
                _text(item, "executable_candidate")
                for item in self.executable_candidates
            ),
        )
        resource = (
            self.resource_class
            if isinstance(self.resource_class, ToolchainResourceClass)
            else ToolchainResourceClass(str(self.resource_class))
        )
        runtime = (
            self.runtime
            if isinstance(self.runtime, ToolRuntimeFamily)
            else ToolRuntimeFamily(str(self.runtime))
        )
        availability = (
            self.availability
            if isinstance(self.availability, InstallAvailability)
            else InstallAvailability(str(self.availability))
        )
        object.__setattr__(self, "resource_class", resource)
        object.__setattr__(self, "runtime", runtime)
        object.__setattr__(self, "availability", availability)
        object.__setattr__(
            self,
            "installer_entry",
            _optional_text(self.installer_entry, "installer_entry"),
        )
        object.__setattr__(self, "pins", tuple(self.pins))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(
            self,
            "families",
            tuple(_text(item, "family") for item in self.families),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        if not isinstance(self.isolation, IsolationPolicy):
            raise ToolchainError("isolation must be IsolationPolicy")
        if not isinstance(self.secret_policy, SecretHandlingPolicy):
            raise ToolchainError("secret_policy must be SecretHandlingPolicy")
        if not isinstance(self.witness_policy, WitnessHandlingPolicy):
            raise ToolchainError("witness_policy must be WitnessHandlingPolicy")
        if self.gap is not None and not isinstance(self.gap, InstallGap):
            raise ToolchainError("gap must be InstallGap or None")
        if self.schema_version != TOOLCHAIN_DESCRIPTOR_SCHEMA:
            raise ToolchainError(
                f"descriptor schema must be {TOOLCHAIN_DESCRIPTOR_SCHEMA}"
            )
        if (
            self.availability is InstallAvailability.MANAGED_PIN
            and not any(pin.is_checksummed or pin.version for pin in self.pins)
        ):
            raise ToolchainError(
                f"managed pin provider {self.provider_id!r} requires pin metadata"
            )
        if self.availability is InstallAvailability.DECLARED_GAP and self.gap is None:
            raise ToolchainError(
                f"declared gap provider {self.provider_id!r} requires gap metadata"
            )
        if self.availability is not InstallAvailability.DECLARED_GAP and self.gap is not None:
            raise ToolchainError(
                f"provider {self.provider_id!r} cannot carry a gap unless availability "
                "is declared_gap"
            )

    @property
    def is_installable(self) -> bool:
        return self.availability in {
            InstallAvailability.MANAGED_PIN,
            InstallAvailability.PYTHON_PACKAGE,
            InstallAvailability.EXTERNAL_OPTIONAL,
        }

    @property
    def requires_explicit_install(self) -> bool:
        return self.is_installable

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "executable_candidates": list(self.executable_candidates),
            "resource_class": self.resource_class.value,
            "runtime": self.runtime.value,
            "availability": self.availability.value,
            "installer_entry": self.installer_entry,
            "pins": [pin.to_dict() for pin in self.pins],
            "dependencies": [dep.to_dict() for dep in self.dependencies],
            "gap": None if self.gap is None else self.gap.to_dict(),
            "families": list(self.families),
            "isolation": self.isolation.to_dict(),
            "secret_policy": self.secret_policy.to_dict(),
            "witness_policy": self.witness_policy.to_dict(),
            "notes": self.notes,
            "is_installable": self.is_installable,
            "requires_explicit_install": self.requires_explicit_install,
        }


DEFAULT_ISOLATION_POLICY: Final = IsolationPolicy(
    modes=(
        IsolationMode.PRIVATE_WORKSPACE,
        IsolationMode.PROCESS_GROUP,
        IsolationMode.RESOURCE_LIMITS,
        IsolationMode.PATH_CONTAINMENT,
        IsolationMode.OUTPUT_BOUNDS,
        IsolationMode.ENVIRONMENT_MINIMAL,
        IsolationMode.SECRET_REDACTION,
        IsolationMode.WITNESS_REDACTION,
    )
)

DEFAULT_INSTALL_POLICY: Final = InstallPolicy()
DEFAULT_SECRET_POLICY: Final = SecretHandlingPolicy()
DEFAULT_WITNESS_POLICY: Final = WitnessHandlingPolicy()


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ToolchainError(f"{field_name} must be a non-empty trimmed string")
    if "\x00" in value:
        raise ToolchainError(f"{field_name} must not contain NUL bytes")
    return value


def _optional_text(value: object, field_name: str) -> str:
    if value in ("", None):
        return ""
    return _text(value, field_name)


def _pin(
    tool_id: str,
    version: str,
    *,
    url: str = "",
    sha256: str = "",
    platform: str = "any",
    notes: str = "",
) -> ToolPin:
    return ToolPin(
        tool_id=tool_id,
        version=version,
        artifact_url=url,
        sha256=sha256,
        platform=platform,
        notes=notes,
    )


def _dep(
    kind: DependencyKind,
    description: str,
    *,
    required: bool = True,
    bound: Sequence[str] = (),
) -> ToolchainDependency:
    return ToolchainDependency(
        kind=kind,
        required=required,
        description=description,
        bound_tool_ids=tuple(bound),
    )


def _gap(
    gap_id: InstallGapKind,
    providers: Sequence[str],
    reason: str,
    fallback: str,
) -> InstallGap:
    return InstallGap(
        gap_id=gap_id,
        provider_ids=tuple(providers),
        reason=reason,
        fallback=fallback,
    )


def _descriptor(**kwargs: Any) -> ToolchainDescriptor:
    return ToolchainDescriptor(**kwargs)


def _build_default_descriptors() -> tuple[ToolchainDescriptor, ...]:
    """Return the closed default provider inventory.

    Pin versions mirror ``prover_installer`` managed constants.  Artifact URLs
    and digests for multi-platform releases are summarized at the version
    level here; the installer still validates the platform-specific digest at
    download time.
    """

    jvm_dep = _dep(
        DependencyKind.JVM,
        "Java runtime required for TLA+/Apalache model checking",
        bound=("java",),
    )
    maude_dep = _dep(
        DependencyKind.MAUDE,
        "Maude rewrite engine required by Tamarin",
        bound=("maude",),
    )
    opam_dep = _dep(
        DependencyKind.OPAM,
        "Isolated OPAM root for Rocq/Coq and ProVerif builds",
        bound=("opam",),
    )
    stack_dep = _dep(
        DependencyKind.STACK,
        "Haskell Stack for source builds of Tamarin when no binary exists",
        required=False,
        bound=("stack",),
    )
    elan_dep = _dep(
        DependencyKind.ELAN,
        "Elan toolchain manager for Lean 4",
        required=False,
        bound=("elan",),
    )
    circuit_dep = _dep(
        DependencyKind.CIRCUIT,
        "ZKP circuit / proving-key material for production attestation only",
        required=False,
        bound=("circuit",),
    )

    tlc_gap = _gap(
        InstallGapKind.TLC,
        ("tlc",),
        "TLC is not shipped as a checksummed portable artifact; operators must "
        "provide a JVM-hosted tlc/tla2tools binary explicitly.",
        "Return unavailable until an operator-provided TLC executable is probed; "
        "Apalache remains the managed TLA+ pin.",
    )
    hyper_gap = _gap(
        InstallGapKind.HYPER_TOOLS,
        ("hyperltl", "autohyper", "mchyper"),
        "HyperLTL-family engines have no reviewed checksummed installer yet.",
        "Adapters declare unavailable and may use bounded self-composition only "
        "as a non-authoritative fallback.",
    )
    datalog_gap = _gap(
        InstallGapKind.DATALOG_SECPAL_EXTERNAL,
        ("souffle", "secpal"),
        "External Soufflé/SecPAL engines are optional; no managed pin is published.",
        "In-process Datalog/SecPAL reference engines remain authoritative for "
        "authorization decisions when external tools are absent.",
    )
    runtime_mtl_gap = _gap(
        InstallGapKind.RUNTIME_MTL_EXTERNAL,
        ("runtime-mtl-external",),
        "Runtime MTL does not depend on an external monitor binary; an external "
        "monitor pin is intentionally absent.",
        "Use the in-process Python monitor and TypeScript parity package; "
        "finite-prefix results never claim universal proof.",
    )
    circuit_gap = _gap(
        InstallGapKind.CIRCUIT_WITNESS,
        ("zkp-circuit",),
        "Production ZKP circuit artifacts are bound per deployment and are not "
        "auto-installed.",
        "Attestation backends require an explicit circuit binding; simulated ZKP "
        "never grants production attestation.",
    )

    return (
        _descriptor(
            provider_id="z3",
            display_name="Z3 SMT solver",
            executable_candidates=("z3",),
            resource_class=ToolchainResourceClass.SOLVER,
            runtime=ToolRuntimeFamily.PYTHON,
            availability=InstallAvailability.PYTHON_PACKAGE,
            installer_entry="ensure_z3",
            pins=(_pin("z3", ">=4.12.0,<5.0.0", notes="Python package pin"),),
            families=("smt", "software_verification"),
        ),
        _descriptor(
            provider_id="cvc5",
            display_name="CVC5 SMT solver",
            executable_candidates=("cvc5",),
            resource_class=ToolchainResourceClass.SOLVER,
            runtime=ToolRuntimeFamily.NATIVE,
            availability=InstallAvailability.MANAGED_PIN,
            installer_entry="ensure_cvc5",
            pins=(
                _pin(
                    "cvc5",
                    "1.3.3",
                    notes="Platform-specific static binary digests in prover_installer",
                ),
            ),
            families=("smt", "software_verification"),
        ),
        _descriptor(
            provider_id="vampire",
            display_name="Vampire ATP",
            executable_candidates=("vampire",),
            resource_class=ToolchainResourceClass.ATP,
            runtime=ToolRuntimeFamily.NATIVE,
            availability=InstallAvailability.MANAGED_PIN,
            installer_entry="ensure_vampire",
            pins=(_pin("vampire", "5.0.1"),),
            families=("atp",),
        ),
        _descriptor(
            provider_id="eprover",
            display_name="E theorem prover",
            executable_candidates=("eprover",),
            resource_class=ToolchainResourceClass.ATP,
            runtime=ToolRuntimeFamily.NATIVE,
            availability=InstallAvailability.MANAGED_PIN,
            installer_entry="ensure_eprover",
            pins=(
                _pin(
                    "eprover",
                    "3.2.5",
                    url="https://wwwlehre.dhbw-stuttgart.de/~sschulz/WORK/E_DOWNLOAD/V_3.2/E.tgz",
                    sha256=(
                        "074c8e5fc3062476341ce790fd15ad8004d322d6b6627844bd2768a8830bd4ae"
                    ),
                ),
            ),
            families=("atp",),
        ),
        _descriptor(
            provider_id="apalache",
            display_name="Apalache symbolic model checker",
            executable_candidates=("apalache-mc", "apalache"),
            resource_class=ToolchainResourceClass.JVM,
            runtime=ToolRuntimeFamily.JVM,
            availability=InstallAvailability.MANAGED_PIN,
            installer_entry="ensure_apalache",
            pins=(
                _pin(
                    "apalache",
                    "0.58.3",
                    url=(
                        "https://github.com/apalache-mc/apalache/releases/download/"
                        "v0.58.3/apalache-0.58.3.tgz"
                    ),
                    sha256=(
                        "ba622db9538aebf942cc7a7815f942a6b2b419012707e16dfdc25a73ff95d0a5"
                    ),
                ),
            ),
            dependencies=(jvm_dep,),
            families=("tla", "state_model"),
        ),
        _descriptor(
            provider_id="tlc",
            display_name="TLC explicit-state model checker",
            executable_candidates=("tlc", "tlc2", "tla2tools"),
            resource_class=ToolchainResourceClass.JVM,
            runtime=ToolRuntimeFamily.JVM,
            availability=InstallAvailability.DECLARED_GAP,
            dependencies=(jvm_dep,),
            gap=tlc_gap,
            families=("tla", "state_model"),
            notes="Declared install gap; JVM dependency is still bound.",
        ),
        _descriptor(
            provider_id="tamarin",
            display_name="Tamarin protocol prover",
            executable_candidates=("tamarin-prover",),
            resource_class=ToolchainResourceClass.PROTOCOL,
            runtime=ToolRuntimeFamily.NATIVE,
            availability=InstallAvailability.MANAGED_PIN,
            installer_entry="ensure_tamarin",
            pins=(_pin("tamarin", "1.12.0"),),
            dependencies=(maude_dep, stack_dep),
            families=("protocol",),
        ),
        _descriptor(
            provider_id="maude",
            display_name="Maude rewrite engine",
            executable_candidates=("maude",),
            resource_class=ToolchainResourceClass.PROTOCOL,
            runtime=ToolRuntimeFamily.NATIVE,
            availability=InstallAvailability.MANAGED_PIN,
            installer_entry="ensure_maude",
            pins=(_pin("maude", "3.5.1"),),
            families=("protocol",),
            notes="Bound companion dependency for Tamarin compatibility.",
        ),
        _descriptor(
            provider_id="proverif",
            display_name="ProVerif protocol analyzer",
            executable_candidates=("proverif",),
            resource_class=ToolchainResourceClass.PROTOCOL,
            runtime=ToolRuntimeFamily.OPAM,
            availability=InstallAvailability.MANAGED_PIN,
            installer_entry="ensure_proverif",
            pins=(
                _pin(
                    "proverif",
                    "2.05",
                    url="https://proverif.inria.fr/proverif2.05.tar.gz",
                    sha256=(
                        "4871f53c32ab4a04669a060c4886ba5d9080496963fb980a9a62d2c429ceabc4"
                    ),
                ),
            ),
            dependencies=(opam_dep,),
            families=("protocol",),
        ),
        _descriptor(
            provider_id="lean",
            display_name="Lean 4 kernel",
            executable_candidates=("lean",),
            resource_class=ToolchainResourceClass.KERNEL,
            runtime=ToolRuntimeFamily.NATIVE,
            availability=InstallAvailability.MANAGED_PIN,
            installer_entry="ensure_lean",
            pins=(_pin("lean", "v4.31.0"),),
            dependencies=(elan_dep,),
            families=("kernel", "reconstruction"),
        ),
        _descriptor(
            provider_id="coq",
            display_name="Rocq/Coq kernel",
            executable_candidates=("coqc", "rocq"),
            resource_class=ToolchainResourceClass.OPAM,
            runtime=ToolRuntimeFamily.OPAM,
            availability=InstallAvailability.MANAGED_PIN,
            installer_entry="ensure_coq",
            pins=(_pin("rocq", "9.1.1"),),
            dependencies=(opam_dep,),
            families=("kernel", "reconstruction"),
        ),
        _descriptor(
            provider_id="isabelle",
            display_name="Isabelle reconstruction kernel",
            executable_candidates=("isabelle",),
            resource_class=ToolchainResourceClass.KERNEL,
            runtime=ToolRuntimeFamily.NATIVE,
            availability=InstallAvailability.MANAGED_PIN,
            installer_entry="ensure_isabelle",
            pins=(_pin("isabelle", "Isabelle2025-2"),),
            families=("kernel", "reconstruction", "hammer"),
        ),
        _descriptor(
            provider_id="hyperltl",
            display_name="HyperLTL external engine",
            executable_candidates=("hyperltl", "hyperltl-sat"),
            resource_class=ToolchainResourceClass.HYPERPROPERTY,
            runtime=ToolRuntimeFamily.NATIVE,
            availability=InstallAvailability.DECLARED_GAP,
            gap=hyper_gap,
            families=("hyperproperty",),
        ),
        _descriptor(
            provider_id="autohyper",
            display_name="AutoHyper external engine",
            executable_candidates=("AutoHyper", "autohyper"),
            resource_class=ToolchainResourceClass.HYPERPROPERTY,
            runtime=ToolRuntimeFamily.NATIVE,
            availability=InstallAvailability.DECLARED_GAP,
            gap=hyper_gap,
            families=("hyperproperty",),
        ),
        _descriptor(
            provider_id="mchyper",
            display_name="MCHyper external engine",
            executable_candidates=("mchyper", "MCHyper"),
            resource_class=ToolchainResourceClass.HYPERPROPERTY,
            runtime=ToolRuntimeFamily.NATIVE,
            availability=InstallAvailability.DECLARED_GAP,
            gap=hyper_gap,
            families=("hyperproperty",),
        ),
        _descriptor(
            provider_id="datalog-authorization",
            display_name="In-process Datalog authorization engine",
            executable_candidates=(),
            resource_class=ToolchainResourceClass.AUTHORIZATION,
            runtime=ToolRuntimeFamily.IN_PROCESS,
            availability=InstallAvailability.IN_PROCESS,
            families=("authorization", "datalog"),
            notes="Reference engine; no install required.",
        ),
        _descriptor(
            provider_id="secpal-authorization",
            display_name="In-process SecPAL-style authorization engine",
            executable_candidates=(),
            resource_class=ToolchainResourceClass.AUTHORIZATION,
            runtime=ToolRuntimeFamily.IN_PROCESS,
            availability=InstallAvailability.IN_PROCESS,
            families=("authorization", "secpal"),
            notes="Reference engine; no install required.",
        ),
        _descriptor(
            provider_id="souffle",
            display_name="External Soufflé Datalog engine",
            executable_candidates=("souffle",),
            resource_class=ToolchainResourceClass.AUTHORIZATION,
            runtime=ToolRuntimeFamily.NATIVE,
            availability=InstallAvailability.DECLARED_GAP,
            gap=datalog_gap,
            families=("authorization", "datalog"),
        ),
        _descriptor(
            provider_id="secpal",
            display_name="External SecPAL engine",
            executable_candidates=("secpal",),
            resource_class=ToolchainResourceClass.AUTHORIZATION,
            runtime=ToolRuntimeFamily.NATIVE,
            availability=InstallAvailability.DECLARED_GAP,
            gap=datalog_gap,
            families=("authorization", "secpal"),
        ),
        _descriptor(
            provider_id="runtime-mtl",
            display_name="In-process runtime MTL monitor",
            executable_candidates=(),
            resource_class=ToolchainResourceClass.MONITOR,
            runtime=ToolRuntimeFamily.IN_PROCESS,
            availability=InstallAvailability.IN_PROCESS,
            families=("temporal", "runtime_mtl"),
            notes="Python reference monitor with TypeScript parity package.",
        ),
        _descriptor(
            provider_id="runtime-mtl-external",
            display_name="External runtime MTL monitor (gap)",
            executable_candidates=("runtime-mtl", "mtl-monitor"),
            resource_class=ToolchainResourceClass.MONITOR,
            runtime=ToolRuntimeFamily.NATIVE,
            availability=InstallAvailability.DECLARED_GAP,
            gap=runtime_mtl_gap,
            families=("temporal", "runtime_mtl"),
        ),
        _descriptor(
            provider_id="symbolicai",
            display_name="SymbolicAI advisor",
            executable_candidates=(),
            resource_class=ToolchainResourceClass.ADVISOR,
            runtime=ToolRuntimeFamily.PYTHON,
            availability=InstallAvailability.ADVISOR_ONLY,
            installer_entry="ensure_symbolicai",
            pins=(_pin("symbolicai", ">=1.14.0,<2.0.0"),),
            families=("advisor",),
            notes="Untrusted proposal provider; never proof authority.",
        ),
        _descriptor(
            provider_id="ergoai",
            display_name="ErgoAI/ErgoEngine",
            executable_candidates=("ergoai", "runErgo.sh", "runergo"),
            resource_class=ToolchainResourceClass.ATP,
            runtime=ToolRuntimeFamily.NATIVE,
            availability=InstallAvailability.MANAGED_PIN,
            installer_entry="ensure_ergoai",
            pins=(_pin("ergoai", "3.0"),),
            families=("flogic", "atp"),
        ),
        _descriptor(
            provider_id="zkp-circuit",
            display_name="Production ZKP circuit binding",
            executable_candidates=(),
            resource_class=ToolchainResourceClass.CIRCUIT,
            runtime=ToolRuntimeFamily.IN_PROCESS,
            availability=InstallAvailability.DECLARED_GAP,
            dependencies=(circuit_dep,),
            gap=circuit_gap,
            families=("attestation", "zkp"),
            notes="Circuit/proving-key dependency is bound, never auto-installed.",
        ),
        _descriptor(
            provider_id="opam",
            display_name="Managed OPAM binary",
            executable_candidates=("opam",),
            resource_class=ToolchainResourceClass.OPAM,
            runtime=ToolRuntimeFamily.NATIVE,
            availability=InstallAvailability.MANAGED_PIN,
            pins=(_pin("opam", "2.5.2"),),
            families=("kernel", "protocol"),
            notes="Companion dependency for Rocq/ProVerif isolated installs.",
        ),
        _descriptor(
            provider_id="java",
            display_name="Host JVM (java)",
            executable_candidates=("java",),
            resource_class=ToolchainResourceClass.JVM,
            runtime=ToolRuntimeFamily.JVM,
            availability=InstallAvailability.EXTERNAL_OPTIONAL,
            families=("tla", "state_model"),
            notes="Bound host dependency for TLC/Apalache; not auto-installed.",
        ),
    )


@dataclass(frozen=True, slots=True)
class VerificationToolchainRegistry:
    """Immutable ``VerificationToolchainRegistry@1`` inventory."""

    interface_version: str = VERIFICATION_TOOLCHAIN_REGISTRY_VERSION
    install_policy: InstallPolicy = field(default_factory=lambda: DEFAULT_INSTALL_POLICY)
    descriptors: tuple[ToolchainDescriptor, ...] = field(
        default_factory=_build_default_descriptors
    )

    def __post_init__(self) -> None:
        if self.interface_version != VERIFICATION_TOOLCHAIN_REGISTRY_VERSION:
            raise ToolchainError(
                "interface_version must be "
                f"{VERIFICATION_TOOLCHAIN_REGISTRY_VERSION}"
            )
        if not isinstance(self.install_policy, InstallPolicy):
            raise ToolchainError("install_policy must be InstallPolicy")
        descriptors = tuple(self.descriptors)
        if not descriptors:
            raise ToolchainError("registry requires at least one descriptor")
        seen: set[str] = set()
        for descriptor in descriptors:
            if not isinstance(descriptor, ToolchainDescriptor):
                raise ToolchainError("descriptors must be ToolchainDescriptor values")
            if descriptor.provider_id in seen:
                raise ToolchainError(
                    f"duplicate provider_id {descriptor.provider_id!r}"
                )
            seen.add(descriptor.provider_id)
        object.__setattr__(self, "descriptors", descriptors)

    def __iter__(self):
        return iter(self.descriptors)

    def __len__(self) -> int:
        return len(self.descriptors)

    def get(self, provider_id: str) -> ToolchainDescriptor:
        key = _text(provider_id, "provider_id").lower().replace("_", "-")
        for descriptor in self.descriptors:
            if descriptor.provider_id == provider_id or descriptor.provider_id == key:
                return descriptor
            if provider_id in descriptor.executable_candidates:
                return descriptor
        # Second pass for alias-style lookups.
        normalized = (
            str(provider_id).strip().lower().replace("-", "_").replace(" ", "_")
        )
        aliases = {
            "cvc5_cli": "cvc5",
            "tamarin_prover": "tamarin",
            "rocq": "coq",
            "coqc": "coq",
            "apalache_mc": "apalache",
            "runtime_mtl": "runtime-mtl",
            "datalog": "datalog-authorization",
            "secpal_auth": "secpal-authorization",
        }
        resolved = aliases.get(normalized, normalized.replace("_", "-"))
        for descriptor in self.descriptors:
            if descriptor.provider_id == resolved:
                return descriptor
        raise ToolchainError(f"unknown provider_id {provider_id!r}")

    def list_provider_ids(self) -> tuple[str, ...]:
        return tuple(item.provider_id for item in self.descriptors)

    def declared_gaps(self) -> tuple[InstallGap, ...]:
        gaps: list[InstallGap] = []
        seen: set[str] = set()
        for descriptor in self.descriptors:
            if descriptor.gap is None:
                continue
            key = descriptor.gap.gap_id.value
            if key in seen:
                continue
            seen.add(key)
            gaps.append(descriptor.gap)
        return tuple(gaps)

    def required_gap_kinds(self) -> frozenset[InstallGapKind]:
        return frozenset(gap.gap_id for gap in self.declared_gaps())

    def providers_for_gap(self, gap_id: InstallGapKind | str) -> tuple[str, ...]:
        kind = (
            gap_id
            if isinstance(gap_id, InstallGapKind)
            else InstallGapKind(str(gap_id))
        )
        return tuple(
            descriptor.provider_id
            for descriptor in self.descriptors
            if descriptor.gap is not None and descriptor.gap.gap_id is kind
        )

    def dependencies_of_kind(
        self, kind: DependencyKind | str
    ) -> tuple[tuple[str, ToolchainDependency], ...]:
        dependency_kind = (
            kind if isinstance(kind, DependencyKind) else DependencyKind(str(kind))
        )
        bound: list[tuple[str, ToolchainDependency]] = []
        for descriptor in self.descriptors:
            for dependency in descriptor.dependencies:
                if dependency.kind is dependency_kind:
                    bound.append((descriptor.provider_id, dependency))
        return tuple(bound)

    def resource_class_for(self, provider_id: str) -> ToolchainResourceClass:
        return self.get(provider_id).resource_class

    def isolation_for(self, provider_id: str) -> IsolationPolicy:
        return self.get(provider_id).isolation

    def assert_required_gaps_declared(self) -> None:
        required = {
            InstallGapKind.TLC,
            InstallGapKind.HYPER_TOOLS,
            InstallGapKind.DATALOG_SECPAL_EXTERNAL,
            InstallGapKind.RUNTIME_MTL_EXTERNAL,
        }
        present = self.required_gap_kinds()
        missing = required - present
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ToolchainError(f"required install gaps not declared: {names}")

    def assert_runtime_dependencies_bound(self) -> None:
        """Fail if JVM/opam/Maude/circuit dependency bindings are absent."""

        checks = (
            (DependencyKind.JVM, ("apalache", "tlc")),
            (DependencyKind.OPAM, ("coq", "proverif")),
            (DependencyKind.MAUDE, ("tamarin",)),
            (DependencyKind.CIRCUIT, ("zkp-circuit",)),
        )
        known = set(self.list_provider_ids())
        for kind, providers in checks:
            for provider in providers:
                if provider not in known:
                    raise ToolchainError(
                        f"missing provider {provider!r} required for "
                        f"dependency binding {kind.value}"
                    )
                descriptor = self.get(provider)
                if not any(dep.kind is kind for dep in descriptor.dependencies):
                    raise ToolchainError(
                        f"provider {provider!r} must bind dependency {kind.value}"
                    )
        # Companion carriers themselves must also be registered.
        for carrier in ("java", "opam", "maude", "zkp-circuit"):
            if carrier not in known:
                raise ToolchainError(
                    f"dependency carrier provider {carrier!r} is not registered"
                )

    def authorize_install(
        self,
        provider_id: str,
        *,
        yes: bool,
        explicit_call: bool,
        import_context: bool = False,
        capability_discovery: bool = False,
        test_mode: bool = False,
        system_package_mutation: bool = False,
        checksum_verified: bool | None = None,
    ) -> None:
        """Raise when an install request violates the fail-closed policy."""

        policy = self.install_policy
        if import_context and policy.never_on_import:
            raise ToolchainError(
                "installation is forbidden during import or module initialization"
            )
        if capability_discovery and policy.never_on_capability_discovery:
            raise ToolchainError(
                "installation is forbidden during capability discovery"
            )
        if not explicit_call:
            raise ToolchainError(
                "installation requires an explicit install_provider/ensure_* call"
            )
        if policy.requires_explicit_yes and not yes:
            raise ToolchainError(
                "installation requires explicit yes=True consent"
            )
        if (
            test_mode
            and system_package_mutation
            and policy.forbid_system_package_mutation_in_tests
        ):
            raise ToolchainError(
                "system package manager mutation is forbidden in tests"
            )
        descriptor = self.get(provider_id)
        if descriptor.availability is InstallAvailability.DECLARED_GAP:
            raise ToolchainError(
                f"provider {descriptor.provider_id!r} is a declared install gap "
                f"({descriptor.gap.gap_id.value if descriptor.gap else 'unknown'}); "
                "refusing managed install"
            )
        if descriptor.availability is InstallAvailability.IN_PROCESS:
            raise ToolchainError(
                f"provider {descriptor.provider_id!r} is in-process and has no installer"
            )
        if descriptor.availability is InstallAvailability.ADVISOR_ONLY and not yes:
            raise ToolchainError(
                "advisor package install still requires explicit yes=True"
            )
        if (
            descriptor.availability is InstallAvailability.MANAGED_PIN
            and policy.requires_checksum_for_managed_artifacts
        ):
            if checksum_verified is False:
                raise ToolchainError(
                    f"managed install for {descriptor.provider_id!r} requires "
                    "verified checksum pins"
                )
            if not descriptor.pins:
                raise ToolchainError(
                    f"managed install for {descriptor.provider_id!r} has no pins"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface_version": self.interface_version,
            "install_policy": self.install_policy.to_dict(),
            "providers": [item.to_dict() for item in self.descriptors],
            "declared_gaps": [gap.to_dict() for gap in self.declared_gaps()],
            "provider_ids": list(self.list_provider_ids()),
        }


_DEFAULT_REGISTRY: VerificationToolchainRegistry | None = None


def default_registry() -> VerificationToolchainRegistry:
    """Return the process-wide default registry (pure data, built once)."""

    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        registry = VerificationToolchainRegistry()
        registry.assert_required_gaps_declared()
        registry.assert_runtime_dependencies_bound()
        _DEFAULT_REGISTRY = registry
    return _DEFAULT_REGISTRY


def reset_default_registry() -> None:
    """Clear the cached default registry (tests only)."""

    global _DEFAULT_REGISTRY
    _DEFAULT_REGISTRY = None


def list_toolchains() -> tuple[ToolchainDescriptor, ...]:
    """Return every registered toolchain descriptor."""

    return default_registry().descriptors


def get_toolchain(provider_id: str) -> ToolchainDescriptor:
    """Return one provider toolchain descriptor."""

    return default_registry().get(provider_id)


def list_declared_install_gaps() -> tuple[InstallGap, ...]:
    """Return unique declared install gaps (TLC, Hyper, Datalog, runtime-MTL, ...)."""

    return default_registry().declared_gaps()


def install_is_forbidden_on_import() -> bool:
    """Return True; install side effects must never run at import time."""

    return default_registry().install_policy.never_on_import


def authorize_provider_install(
    provider_id: str,
    *,
    yes: bool = False,
    explicit_call: bool = True,
    import_context: bool = False,
    capability_discovery: bool = False,
    test_mode: bool = False,
    system_package_mutation: bool = False,
    checksum_verified: bool | None = None,
) -> None:
    """Validate an install request against the default registry policy."""

    default_registry().authorize_install(
        provider_id,
        yes=yes,
        explicit_call=explicit_call,
        import_context=import_context,
        capability_discovery=capability_discovery,
        test_mode=test_mode,
        system_package_mutation=system_package_mutation,
        checksum_verified=checksum_verified,
    )


def isolation_policy_for(provider_id: str) -> IsolationPolicy:
    """Return the isolation contract for a provider."""

    return default_registry().isolation_for(provider_id)


def resource_class_for(provider_id: str) -> ToolchainResourceClass:
    """Return the operational resource class for a provider."""

    return default_registry().resource_class_for(provider_id)


def secret_handling_policy(provider_id: str | None = None) -> SecretHandlingPolicy:
    """Return the secret-handling contract (global or per-provider)."""

    if provider_id is None:
        return DEFAULT_SECRET_POLICY
    return default_registry().get(provider_id).secret_policy


def witness_handling_policy(provider_id: str | None = None) -> WitnessHandlingPolicy:
    """Return the witness-handling contract (global or per-provider)."""

    if provider_id is None:
        return DEFAULT_WITNESS_POLICY
    return default_registry().get(provider_id).witness_policy


def bound_dependency_kinds() -> Mapping[str, tuple[str, ...]]:
    """Map dependency kinds to provider ids that bind them."""

    registry = default_registry()
    result: dict[str, list[str]] = {}
    for kind in DependencyKind:
        providers = [provider for provider, _ in registry.dependencies_of_kind(kind)]
        if providers:
            result[kind.value] = providers
    return MappingProxyType({key: tuple(value) for key, value in result.items()})


def managed_pin_versions() -> Mapping[str, str]:
    """Return provider_id -> version for managed pins."""

    versions: dict[str, str] = {}
    for descriptor in default_registry().descriptors:
        if descriptor.availability is not InstallAvailability.MANAGED_PIN:
            continue
        if descriptor.pins:
            versions[descriptor.provider_id] = descriptor.pins[0].version
    return MappingProxyType(versions)


def registry_side_effect_free_on_import() -> bool:
    """Document and assert that registry construction is side-effect free.

    This helper is itself pure: it only builds in-memory dataclasses.
    """

    registry = VerificationToolchainRegistry()
    registry.assert_required_gaps_declared()
    registry.assert_runtime_dependencies_bound()
    return (
        registry.install_policy.never_on_import
        and registry.install_policy.never_on_capability_discovery
        and not any(
            descriptor.availability is InstallAvailability.MANAGED_PIN
            and not descriptor.pins
            for descriptor in registry.descriptors
        )
    )


__all__ = [
    "VERIFICATION_TOOLCHAIN_REGISTRY_VERSION",
    "TOOLCHAIN_DESCRIPTOR_SCHEMA",
    "DEFAULT_INSTALL_POLICY",
    "DEFAULT_ISOLATION_POLICY",
    "DEFAULT_SECRET_POLICY",
    "DEFAULT_WITNESS_POLICY",
    "ToolchainError",
    "ToolchainResourceClass",
    "ToolRuntimeFamily",
    "InstallAvailability",
    "InstallGapKind",
    "DependencyKind",
    "IsolationMode",
    "ToolPin",
    "ToolchainDependency",
    "IsolationPolicy",
    "SecretHandlingPolicy",
    "WitnessHandlingPolicy",
    "InstallPolicy",
    "InstallGap",
    "ToolchainDescriptor",
    "VerificationToolchainRegistry",
    "default_registry",
    "reset_default_registry",
    "list_toolchains",
    "get_toolchain",
    "list_declared_install_gaps",
    "install_is_forbidden_on_import",
    "authorize_provider_install",
    "isolation_policy_for",
    "resource_class_for",
    "secret_handling_policy",
    "witness_handling_policy",
    "bound_dependency_kinds",
    "managed_pin_versions",
    "registry_side_effect_free_on_import",
]
