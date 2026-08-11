"""Separate Hammer, reconstruction, and official kernel phases (LFP2-034).

Interface: ``KernelProviderEvidence@2``

Orchestrates Lean / Rocq / Isabelle kernel execution as **distinct phases**:

1. **premise_selection** — Hammer premise ranking (candidate authority only);
2. **atp_candidate** — untrusted ATP/SMT solver portfolio (candidate only);
3. **reconstruction** — independent native tactic/term reconstruction
   (reconstruction authority; still not theorem);
4. **target_compilation** — controlled theory → kernel compilation candidate;
5. **elaboration** — elaborator / type-check of reconstructed source; and
6. **official_kernel** — Lean / Rocq / Isabelle kernel receipt (sole theorem
   authority path).

Every result binds:

* imports,
* axioms,
* admits (detected incomplete-proof markers),
* trust escapes,
* environment identity,
* source theorem, and
* official kernel result.

Fail-closed authority (acceptance LFP2-034):

* **Hammer never becomes proof authority.**  Premise selection, ATP success,
  or reconstruction alone cannot mint ``proved`` / theorem authority.
* Mock / fallback / availability / confidence never establish proof.
* Only an official-kernel acceptance whose environment, theorem identity,
  imports, and axioms match the bound candidate may yield theorem authority.
* Detected admits / trust escapes block theorem authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.results import (
    CandidateResult,
    ReconstructionResult,
    ResultAuthority,
    ResultStatus,
    TheoremResult,
    TypedBackendResult,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    provider_id,
)
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds, ResourceUsage
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SyntaxContractError,
    _freeze_mapping,
    _record_id,
    _require_mapping,
    _require_sequence,
    _sha256_hex,
    _text,
    canonical_json_bytes,
    content_sha256,
)
from ipfs_datasets_py.logic.translations.kernel_targets import (
    CompilationStatus,
    KernelCompilationCandidate,
    KernelTargetCompiler,
    KernelTargetKind,
    KernelTargetTranslationError,
    SourceSurface,
    TargetTheoryArtifact,
    content_digest as kernel_content_digest,
    is_official_kernel,
    reject_trust_escapes,
    scan_trust_escapes,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

KERNEL_PROVIDER_EVIDENCE_V2_INTERFACE: Final = "KernelProviderEvidence@2"
KERNEL_EXECUTION_REQUEST_V2_INTERFACE: Final = "KernelExecutionRequest@2"
KERNEL_EXECUTION_RESULT_V2_INTERFACE: Final = "KernelExecutionResult@2"
KERNEL_PHASE_RECEIPT_V2_INTERFACE: Final = "KernelPhaseReceipt@2"
KERNEL_IMPORT_BINDING_V2_INTERFACE: Final = "KernelImportBinding@2"
KERNEL_AXIOM_BINDING_V2_INTERFACE: Final = "KernelAxiomBinding@2"
KERNEL_ADMIT_BINDING_V2_INTERFACE: Final = "KernelAdmitBinding@2"
KERNEL_TRUST_ESCAPE_BINDING_V2_INTERFACE: Final = "KernelTrustEscapeBinding@2"
KERNEL_ENVIRONMENT_BINDING_V2_INTERFACE: Final = "KernelEnvironmentBinding@2"
KERNEL_SOURCE_THEOREM_BINDING_V2_INTERFACE: Final = "KernelSourceTheoremBinding@2"
KERNEL_OFFICIAL_RESULT_BINDING_V2_INTERFACE: Final = "KernelOfficialResultBinding@2"

KERNEL_PROVIDER_EVIDENCE_SCHEMA: Final = "kernel-provider-evidence/v2"
KERNEL_EXECUTION_REQUEST_SCHEMA: Final = "kernel-execution-request/v2"
KERNEL_EXECUTION_RESULT_SCHEMA: Final = "kernel-execution-result/v2"
KERNEL_PHASE_RECEIPT_SCHEMA: Final = "kernel-phase-receipt/v2"
KERNEL_IMPORT_BINDING_SCHEMA: Final = "kernel-import-binding/v2"
KERNEL_AXIOM_BINDING_SCHEMA: Final = "kernel-axiom-binding/v2"
KERNEL_ADMIT_BINDING_SCHEMA: Final = "kernel-admit-binding/v2"
KERNEL_TRUST_ESCAPE_BINDING_SCHEMA: Final = "kernel-trust-escape-binding/v2"
KERNEL_ENVIRONMENT_BINDING_SCHEMA: Final = "kernel-environment-binding/v2"
KERNEL_SOURCE_THEOREM_BINDING_SCHEMA: Final = "kernel-source-theorem-binding/v2"
KERNEL_OFFICIAL_RESULT_BINDING_SCHEMA: Final = "kernel-official-result-binding/v2"

KERNEL_EXECUTION_V2_MODULE_VERSION: Final = "1.0.0"
KERNEL_EXECUTION_V2_TASK_ID: Final = "LFP2-034"
KERNEL_EXECUTION_V2_GOAL_ID: Final = "LFP2-G060"

KERNEL_LANE_ID: Final = "kernel"
KERNEL_EVIDENCE_KIND: Final = "kernel_receipt"

_MAX_DIAGNOSTICS: Final = 64
_MAX_METADATA_BYTES: Final = 8_192
_MAX_SOURCE_REFS: Final = 64
_MAX_PHASE_DIAGNOSTICS: Final = 32

_FORBIDDEN_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "arbitrary_payload",
        "claimed_execution",
        "claimed_proof",
        "execution_result",
        "fake_replay",
        "family_string",
        "free_form_family",
        "is_proved",
        "logic_family",
        "mock_execution",
        "mock_result",
        "opaque_extension",
        "payload",
        "proof_result",
        "proof_status",
        "proved",
        "raw_formula",
        "raw_result",
        "raw_source",
        "solver_result",
        "target_source",
        "theorem_status",
        "verification_result",
        "verification_status",
    }
)

_NON_AUTHORITATIVE_SIGNAL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "availability",
        "available",
        "confidence",
        "fallback",
        "fallback_output",
        "fluent_text",
        "is_valid",
        "mock",
        "mock_output",
        "similarity",
    }
)

# Phase order is fixed and auditable; never reorder without a schema bump.
_PHASE_ORDER: Final[tuple[str, ...]] = (
    "premise_selection",
    "atp_candidate",
    "reconstruction",
    "target_compilation",
    "elaboration",
    "official_kernel",
)


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class KernelExecutionError(SyntaxContractError):
    """Raised when kernel execution v2 inputs or evidence are malformed."""


class KernelAuthorityError(KernelExecutionError):
    """Raised when a claim would exceed the kernel authority ceiling."""


class KernelProviderKind(StrEnum):
    """Closed set of official kernel providers."""

    LEAN = "lean"
    ROCQ = "rocq"
    ISABELLE = "isabelle"


class KernelPhase(StrEnum):
    """Named pipeline phases kept strictly separate for auditability.

    Only :attr:`OFFICIAL_KERNEL` may mint theorem authority, and only when
    the official kernel receipt is accepted with matching bindings.
    """

    PREMISE_SELECTION = "premise_selection"
    ATP_CANDIDATE = "atp_candidate"
    RECONSTRUCTION = "reconstruction"
    TARGET_COMPILATION = "target_compilation"
    ELABORATION = "elaboration"
    OFFICIAL_KERNEL = "official_kernel"


class KernelPhaseStatus(StrEnum):
    """Outcome of one isolated phase — never promotes authority alone."""

    COMPLETED = "completed"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    CANDIDATE_ONLY = "candidate_only"
    RECONSTRUCTED = "reconstructed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    MOCK_REJECTED = "mock_rejected"


class KernelExecutionMode(StrEnum):
    """How the pipeline was driven.

    Only ``official_kernel`` (with real or injected official-kernel outcome
    that passes binding checks) may establish theorem authority.  Hammer-only,
    reconstruction-only, mock, and fallback modes never do.
    """

    FULL_PIPELINE = "full_pipeline"
    HAMMER_ONLY = "hammer_only"
    RECONSTRUCTION_ONLY = "reconstruction_only"
    COMPILE_AND_CHECK = "compile_and_check"
    OFFICIAL_KERNEL = "official_kernel"
    FALLBACK = "fallback"
    MOCK = "mock"


class KernelDisposition(StrEnum):
    """Closed set of kernel execution dispositions."""

    PROVED = "proved"
    DISPROVED = "disproved"
    CANDIDATE = "candidate"
    RECONSTRUCTED = "reconstructed"
    RECONSTRUCTION_FAILED = "reconstruction_failed"
    KERNEL_REJECTED = "kernel_rejected"
    TRUST_ESCAPE_REJECTED = "trust_escape_rejected"
    ADMIT_REJECTED = "admit_rejected"
    BINDING_MISMATCH = "binding_mismatch"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    ERROR = "error"
    MALFORMED = "malformed"
    MOCK_REJECTED = "mock_rejected"
    FALLBACK_REJECTED = "fallback_rejected"
    HAMMER_CANDIDATE_ONLY = "hammer_candidate_only"


class KernelClaimKind(StrEnum):
    """Claims that Hammer / mock / fallback must never establish alone."""

    PROOF = "proof"
    THEOREM = "theorem"
    SATISFIABILITY = "satisfiability"
    POLICY = "policy"


_PROVIDER_ALIASES: Final[dict[str, KernelProviderKind]] = {
    "lean": KernelProviderKind.LEAN,
    "lean4": KernelProviderKind.LEAN,
    "lean_4": KernelProviderKind.LEAN,
    "rocq": KernelProviderKind.ROCQ,
    "coq": KernelProviderKind.ROCQ,
    "coq_kernel": KernelProviderKind.ROCQ,
    "isabelle": KernelProviderKind.ISABELLE,
    "isabelle_hol": KernelProviderKind.ISABELLE,
    "isabelle-hol": KernelProviderKind.ISABELLE,
}


def normalize_kernel_provider(
    value: KernelProviderKind | KernelTargetKind | str,
) -> KernelProviderKind:
    """Normalize provider labels into the closed official-kernel set."""

    if isinstance(value, KernelProviderKind):
        return value
    if isinstance(value, KernelTargetKind):
        if value is KernelTargetKind.LEAN:
            return KernelProviderKind.LEAN
        if value is KernelTargetKind.ROCQ:
            return KernelProviderKind.ROCQ
        if value is KernelTargetKind.ISABELLE:
            return KernelProviderKind.ISABELLE
        raise KernelExecutionError(f"unsupported kernel target kind: {value!r}")
    key = str(value).strip().lower().replace("-", "_")
    if key not in _PROVIDER_ALIASES:
        raise KernelExecutionError(
            f"unsupported kernel provider: {value!r}; "
            f"expected lean, rocq, or isabelle"
        )
    return _PROVIDER_ALIASES[key]


def provider_to_kernel_target(provider: KernelProviderKind) -> KernelTargetKind:
    if provider is KernelProviderKind.LEAN:
        return KernelTargetKind.LEAN
    if provider is KernelProviderKind.ROCQ:
        return KernelTargetKind.ROCQ
    return KernelTargetKind.ISABELLE


def provider_logic_identity(provider: KernelProviderKind) -> LogicIdentity:
    return provider_id(provider.value)


def provider_role(provider: KernelProviderKind) -> ToolRole:
    del provider
    return ToolRole.AUTHORITY


def provider_authority_ceiling(
    provider: KernelProviderKind,
) -> ToolchainAuthorityCeiling:
    del provider
    return ToolchainAuthorityCeiling.KERNEL


def hammer_establishes_proof(
    *,
    premise_selected: bool = False,
    atp_success: bool = False,
    reconstruction_ok: bool = False,
    hammer_available: bool = True,
    confidence: float | None = None,
    mock_output: object = None,
) -> bool:
    """Always ``False``: Hammer / reconstruction alone never mint proof.

    LFP2-034 acceptance: Hammer never becomes proof authority.
    """

    del (
        premise_selected,
        atp_success,
        reconstruction_ok,
        hammer_available,
        confidence,
        mock_output,
    )
    return False


def non_authoritative_signal_establishes(
    claim: KernelClaimKind | str,
    *,
    mock_output: object = None,
    fallback_output: object = None,
    available: bool | None = None,
    confidence: float | None = None,
    fluent_text: str | None = None,
    hammer_success: bool | None = None,
    reconstruction_success: bool | None = None,
) -> bool:
    """Always ``False``: non-kernel signals never establish claims."""

    del (
        claim,
        mock_output,
        fallback_output,
        available,
        confidence,
        fluent_text,
        hammer_success,
        reconstruction_success,
    )
    return False


# ---------------------------------------------------------------------------
# Primitive validators
# ---------------------------------------------------------------------------


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip())
    except (TypeError, ValueError) as error:
        allowed = ", ".join(item.value for item in enum_type)
        raise KernelExecutionError(
            f"{field_name} must be one of: {allowed}; got {value!r}"
        ) from error


def _optional_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise KernelExecutionError(f"{field_name} must be a boolean")


def _unit_interval(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KernelExecutionError(f"{field_name} must be numeric")
    conf = float(value)
    if conf != conf or conf < 0.0 or conf > 1.0:
        raise KernelExecutionError(f"{field_name} must be finite in [0, 1]")
    return conf


def _digest_of(payload: Mapping[str, Any]) -> str:
    return content_sha256(canonical_json_bytes(dict(payload)))


def _source_ref_ids(
    value: object, field_name: str = "source_ref_ids"
) -> tuple[str, ...]:
    items = _require_sequence(value, field_name)
    if len(items) > _MAX_SOURCE_REFS:
        raise KernelExecutionError(
            f"{field_name} exceeds hard limit {_MAX_SOURCE_REFS}"
        )
    refs: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        ref = _record_id(item, f"{field_name}[{index}]")
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return tuple(refs)


def _string_tuple(
    value: object,
    field_name: str,
    *,
    allow_empty: bool = True,
    maximum: int = 256,
) -> tuple[str, ...]:
    items = _require_sequence(value, field_name)
    if len(items) > maximum:
        raise KernelExecutionError(
            f"{field_name} exceeds hard limit {maximum}"
        )
    out: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        text = _text(item, f"{field_name}[{index}]", maximum=1_024)
        if text not in seen:
            seen.add(text)
            out.append(text)
    if not allow_empty and not out:
        raise KernelExecutionError(f"{field_name} must be non-empty")
    return tuple(out)


def _forbid_authority_metadata(metadata: Mapping[str, Any], field_name: str) -> None:
    for key in metadata:
        if key in _FORBIDDEN_METADATA_KEYS or key in _NON_AUTHORITATIVE_SIGNAL_KEYS:
            raise KernelAuthorityError(
                f"{field_name} rejects free-form authority/signal key {key!r}; "
                "use typed kernel evidence fields only"
            )


def _bound_diagnostics(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    items = _require_sequence(value, "diagnostics")
    out: list[str] = []
    for index, item in enumerate(items[:_MAX_DIAGNOSTICS]):
        out.append(_text(item, f"diagnostics[{index}]", maximum=512))
    return tuple(out)


def _phase_authority(phase: KernelPhase, status: KernelPhaseStatus) -> ResultAuthority:
    """Authority ceiling for one phase receipt.

    Fail-closed: only official_kernel + ACCEPTED may claim theorem authority.
    """

    if phase is KernelPhase.OFFICIAL_KERNEL and status is KernelPhaseStatus.ACCEPTED:
        return ResultAuthority.THEOREM
    if phase is KernelPhase.RECONSTRUCTION:
        return ResultAuthority.RECONSTRUCTION
    return ResultAuthority.CANDIDATE


def _theory_from_value(value: object) -> TargetTheoryArtifact:
    if isinstance(value, TargetTheoryArtifact):
        return value
    if isinstance(value, Mapping):
        try:
            return TargetTheoryArtifact.from_dict(value)
        except (KernelTargetTranslationError, TypeError, ValueError) as error:
            raise KernelExecutionError(
                f"invalid target theory: {error}"
            ) from error
    raise KernelExecutionError(
        "theory must be TargetTheoryArtifact or mapping"
    )


def _scan_admits(source: str) -> tuple[str, ...]:
    """Return admit / incomplete-proof markers present in *source*."""

    found = scan_trust_escapes(source)
    admits = tuple(
        kind
        for kind in found
        if kind in {"sorry", "admit", "oops"}
    )
    return admits


# ---------------------------------------------------------------------------
# Bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KernelImportBindingV2:
    """Imports bound into every kernel evidence record.

    Interface: ``KernelImportBinding@2``.
    """

    imports: tuple[str, ...]
    import_digest: str
    schema_version: str = KERNEL_IMPORT_BINDING_SCHEMA

    interface: ClassVar[str] = KERNEL_IMPORT_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        imports = _string_tuple(self.imports, "imports", allow_empty=True)
        object.__setattr__(self, "imports", imports)
        expected = _digest_of({"imports": list(imports)})
        digest = _sha256_hex(self.import_digest, "import_digest")
        if digest != expected:
            raise KernelExecutionError(
                "import_digest does not match bound imports"
            )
        object.__setattr__(self, "import_digest", digest)
        if self.schema_version != KERNEL_IMPORT_BINDING_SCHEMA:
            raise KernelExecutionError(
                f"unsupported import binding schema: {self.schema_version!r}"
            )

    @classmethod
    def bind(cls, imports: Sequence[str]) -> KernelImportBindingV2:
        frozen = _string_tuple(imports, "imports", allow_empty=True)
        return cls(
            imports=frozen,
            import_digest=_digest_of({"imports": list(frozen)}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "import_digest": self.import_digest,
            "imports": list(self.imports),
            "interface": self.interface,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class KernelAxiomBindingV2:
    """Axioms bound into every kernel evidence record.

    Interface: ``KernelAxiomBinding@2``.
    """

    axioms: tuple[str, ...]
    axiom_digest: str
    unreviewed_axioms_present: bool = False
    schema_version: str = KERNEL_AXIOM_BINDING_SCHEMA

    interface: ClassVar[str] = KERNEL_AXIOM_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        axioms = _string_tuple(self.axioms, "axioms", allow_empty=True)
        object.__setattr__(self, "axioms", axioms)
        expected = _digest_of({"axioms": list(axioms)})
        digest = _sha256_hex(self.axiom_digest, "axiom_digest")
        if digest != expected:
            raise KernelExecutionError(
                "axiom_digest does not match bound axioms"
            )
        object.__setattr__(self, "axiom_digest", digest)
        object.__setattr__(
            self,
            "unreviewed_axioms_present",
            _optional_bool(
                self.unreviewed_axioms_present, "unreviewed_axioms_present"
            ),
        )
        if self.schema_version != KERNEL_AXIOM_BINDING_SCHEMA:
            raise KernelExecutionError(
                f"unsupported axiom binding schema: {self.schema_version!r}"
            )

    @classmethod
    def bind(
        cls,
        axioms: Sequence[str],
        *,
        unreviewed_axioms_present: bool = False,
    ) -> KernelAxiomBindingV2:
        frozen = _string_tuple(axioms, "axioms", allow_empty=True)
        return cls(
            axioms=frozen,
            axiom_digest=_digest_of({"axioms": list(frozen)}),
            unreviewed_axioms_present=unreviewed_axioms_present,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "axiom_digest": self.axiom_digest,
            "axioms": list(self.axioms),
            "interface": self.interface,
            "schema_version": self.schema_version,
            "unreviewed_axioms_present": self.unreviewed_axioms_present,
        }


@dataclass(frozen=True, slots=True)
class KernelAdmitBindingV2:
    """Admits / incomplete-proof markers bound into every answer.

    Interface: ``KernelAdmitBinding@2``.

    Detected admits **block** theorem authority.
    """

    admits: tuple[str, ...]
    admit_digest: str
    admits_present: bool
    blocks_theorem_authority: bool
    schema_version: str = KERNEL_ADMIT_BINDING_SCHEMA

    interface: ClassVar[str] = KERNEL_ADMIT_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        admits = _string_tuple(self.admits, "admits", allow_empty=True)
        object.__setattr__(self, "admits", admits)
        expected = _digest_of({"admits": list(admits)})
        digest = _sha256_hex(self.admit_digest, "admit_digest")
        if digest != expected:
            raise KernelExecutionError(
                "admit_digest does not match bound admits"
            )
        object.__setattr__(self, "admit_digest", digest)
        present = _optional_bool(self.admits_present, "admits_present")
        object.__setattr__(self, "admits_present", present)
        if present != bool(admits):
            raise KernelExecutionError(
                "admits_present must equal bool(admits)"
            )
        blocks = _optional_bool(
            self.blocks_theorem_authority, "blocks_theorem_authority"
        )
        object.__setattr__(self, "blocks_theorem_authority", blocks)
        if present and not blocks:
            raise KernelAuthorityError(
                "detected admits must block theorem authority"
            )
        if self.schema_version != KERNEL_ADMIT_BINDING_SCHEMA:
            raise KernelExecutionError(
                f"unsupported admit binding schema: {self.schema_version!r}"
            )

    @classmethod
    def bind(cls, source: str) -> KernelAdmitBindingV2:
        admits = _scan_admits(source)
        return cls(
            admits=admits,
            admit_digest=_digest_of({"admits": list(admits)}),
            admits_present=bool(admits),
            blocks_theorem_authority=bool(admits),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admit_digest": self.admit_digest,
            "admits": list(self.admits),
            "admits_present": self.admits_present,
            "blocks_theorem_authority": self.blocks_theorem_authority,
            "interface": self.interface,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class KernelTrustEscapeBindingV2:
    """Trust-escape scan bound into every answer.

    Interface: ``KernelTrustEscapeBinding@2``.
    """

    trust_escapes: tuple[str, ...]
    trust_escape_digest: str
    escapes_present: bool
    blocks_theorem_authority: bool
    schema_version: str = KERNEL_TRUST_ESCAPE_BINDING_SCHEMA

    interface: ClassVar[str] = KERNEL_TRUST_ESCAPE_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        escapes = _string_tuple(
            self.trust_escapes, "trust_escapes", allow_empty=True
        )
        object.__setattr__(self, "trust_escapes", escapes)
        expected = _digest_of({"trust_escapes": list(escapes)})
        digest = _sha256_hex(self.trust_escape_digest, "trust_escape_digest")
        if digest != expected:
            raise KernelExecutionError(
                "trust_escape_digest does not match bound trust_escapes"
            )
        object.__setattr__(self, "trust_escape_digest", digest)
        present = _optional_bool(self.escapes_present, "escapes_present")
        object.__setattr__(self, "escapes_present", present)
        if present != bool(escapes):
            raise KernelExecutionError(
                "escapes_present must equal bool(trust_escapes)"
            )
        blocks = _optional_bool(
            self.blocks_theorem_authority, "blocks_theorem_authority"
        )
        object.__setattr__(self, "blocks_theorem_authority", blocks)
        if present and not blocks:
            raise KernelAuthorityError(
                "detected trust escapes must block theorem authority"
            )
        if self.schema_version != KERNEL_TRUST_ESCAPE_BINDING_SCHEMA:
            raise KernelExecutionError(
                f"unsupported trust-escape binding schema: {self.schema_version!r}"
            )

    @classmethod
    def bind(cls, source: str) -> KernelTrustEscapeBindingV2:
        escapes = scan_trust_escapes(source)
        return cls(
            trust_escapes=escapes,
            trust_escape_digest=_digest_of(
                {"trust_escapes": list(escapes)}
            ),
            escapes_present=bool(escapes),
            blocks_theorem_authority=bool(escapes),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocks_theorem_authority": self.blocks_theorem_authority,
            "escapes_present": self.escapes_present,
            "interface": self.interface,
            "schema_version": self.schema_version,
            "trust_escape_digest": self.trust_escape_digest,
            "trust_escapes": list(self.trust_escapes),
        }


@dataclass(frozen=True, slots=True)
class KernelEnvironmentBindingV2:
    """Pinned environment identity bound into every answer.

    Interface: ``KernelEnvironmentBinding@2``.
    """

    environment_id: str
    environment_digest: str
    kernel_target: KernelProviderKind | str
    toolchain_id: str
    toolchain_version: str
    environment: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = KERNEL_ENVIRONMENT_BINDING_SCHEMA

    interface: ClassVar[str] = KERNEL_ENVIRONMENT_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "environment_id",
            _record_id(self.environment_id, "environment_id"),
        )
        object.__setattr__(
            self, "kernel_target", normalize_kernel_provider(self.kernel_target)
        )
        object.__setattr__(
            self,
            "toolchain_id",
            _text(self.toolchain_id, "toolchain_id", maximum=256),
        )
        object.__setattr__(
            self,
            "toolchain_version",
            _text(self.toolchain_version, "toolchain_version", maximum=256),
        )
        env = dict(_require_mapping(self.environment, "environment"))
        object.__setattr__(
            self, "environment", dict(_freeze_mapping(env, "environment"))
        )
        expected = _digest_of(
            {
                "environment": dict(self.environment),
                "environment_id": self.environment_id,
                "kernel_target": (
                    self.kernel_target.value
                    if isinstance(self.kernel_target, KernelProviderKind)
                    else self.kernel_target
                ),
                "toolchain_id": self.toolchain_id,
                "toolchain_version": self.toolchain_version,
            }
        )
        digest = _sha256_hex(self.environment_digest, "environment_digest")
        if digest != expected:
            raise KernelExecutionError(
                "environment_digest does not match bound environment"
            )
        object.__setattr__(self, "environment_digest", digest)
        if self.schema_version != KERNEL_ENVIRONMENT_BINDING_SCHEMA:
            raise KernelExecutionError(
                f"unsupported environment binding schema: {self.schema_version!r}"
            )

    @classmethod
    def bind(
        cls,
        *,
        environment_id: str,
        kernel_target: KernelProviderKind | str,
        toolchain_id: str,
        toolchain_version: str,
        environment: Mapping[str, Any] | None = None,
    ) -> KernelEnvironmentBindingV2:
        provider = normalize_kernel_provider(kernel_target)
        env = dict(environment or {})
        # Force identity fields so free-form environment maps cannot drift.
        env["environment_id"] = environment_id
        env["kernel_target"] = provider.value
        env["toolchain_id"] = toolchain_id
        env["toolchain_version"] = toolchain_version
        frozen = dict(_freeze_mapping(env, "environment"))
        digest = _digest_of(
            {
                "environment": frozen,
                "environment_id": environment_id,
                "kernel_target": provider.value,
                "toolchain_id": toolchain_id,
                "toolchain_version": toolchain_version,
            }
        )
        return cls(
            environment_id=environment_id,
            environment_digest=digest,
            kernel_target=provider,
            toolchain_id=toolchain_id,
            toolchain_version=toolchain_version,
            environment=frozen,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "environment": dict(self.environment),
            "environment_digest": self.environment_digest,
            "environment_id": self.environment_id,
            "interface": self.interface,
            "kernel_target": (
                self.kernel_target.value
                if isinstance(self.kernel_target, KernelProviderKind)
                else self.kernel_target
            ),
            "schema_version": self.schema_version,
            "toolchain_id": self.toolchain_id,
            "toolchain_version": self.toolchain_version,
        }


@dataclass(frozen=True, slots=True)
class KernelSourceTheoremBindingV2:
    """Source theorem identity bound into every answer.

    Interface: ``KernelSourceTheoremBinding@2``.
    """

    theorem_id: str
    theorem_name: str
    statement: str
    statement_digest: str
    theory_id: str
    source_digest: str = ""
    schema_version: str = KERNEL_SOURCE_THEOREM_BINDING_SCHEMA

    interface: ClassVar[str] = KERNEL_SOURCE_THEOREM_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "theorem_id", _record_id(self.theorem_id, "theorem_id")
        )
        object.__setattr__(
            self,
            "theorem_name",
            _text(self.theorem_name, "theorem_name", maximum=512),
        )
        statement = _text(self.statement, "statement", maximum=65_536)
        object.__setattr__(self, "statement", statement)
        expected = kernel_content_digest(statement)
        digest = _sha256_hex(self.statement_digest, "statement_digest")
        if digest != expected:
            raise KernelExecutionError(
                "statement_digest does not match bound statement"
            )
        object.__setattr__(self, "statement_digest", digest)
        object.__setattr__(
            self, "theory_id", _record_id(self.theory_id, "theory_id")
        )
        if self.source_digest:
            object.__setattr__(
                self,
                "source_digest",
                _sha256_hex(self.source_digest, "source_digest"),
            )
        else:
            object.__setattr__(self, "source_digest", "")
        if self.schema_version != KERNEL_SOURCE_THEOREM_BINDING_SCHEMA:
            raise KernelExecutionError(
                f"unsupported source-theorem binding schema: {self.schema_version!r}"
            )

    @classmethod
    def bind(
        cls,
        *,
        theorem_id: str,
        theorem_name: str,
        statement: str,
        theory_id: str,
        source_digest: str = "",
    ) -> KernelSourceTheoremBindingV2:
        return cls(
            theorem_id=theorem_id,
            theorem_name=theorem_name,
            statement=statement,
            statement_digest=kernel_content_digest(statement),
            theory_id=theory_id,
            source_digest=source_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "statement": self.statement,
            "statement_digest": self.statement_digest,
            "theorem_id": self.theorem_id,
            "theorem_name": self.theorem_name,
            "theory_id": self.theory_id,
        }


@dataclass(frozen=True, slots=True)
class KernelOfficialResultBindingV2:
    """Official kernel check result bound into every answer.

    Interface: ``KernelOfficialResultBinding@2``.

    This is the *only* binding that may authorize theorem proof when
    ``accepted`` is True and all peer bindings match.
    """

    accepted: bool
    kernel_provider: KernelProviderKind | str
    receipt_id: str
    result_status: ResultStatus | str
    environment_id: str
    theorem_digest: str
    phase: KernelPhase | str = KernelPhase.OFFICIAL_KERNEL
    authority: ResultAuthority | str = ResultAuthority.CANDIDATE
    diagnostics: tuple[str, ...] = ()
    schema_version: str = KERNEL_OFFICIAL_RESULT_BINDING_SCHEMA

    interface: ClassVar[str] = KERNEL_OFFICIAL_RESULT_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "accepted", _optional_bool(self.accepted, "accepted")
        )
        object.__setattr__(
            self,
            "kernel_provider",
            normalize_kernel_provider(self.kernel_provider),
        )
        if self.receipt_id:
            object.__setattr__(
                self, "receipt_id", _record_id(self.receipt_id, "receipt_id")
            )
        else:
            object.__setattr__(self, "receipt_id", "")
        object.__setattr__(
            self,
            "result_status",
            _enum(self.result_status, ResultStatus, "result_status"),
        )
        if self.environment_id:
            object.__setattr__(
                self,
                "environment_id",
                _record_id(self.environment_id, "environment_id"),
            )
        else:
            object.__setattr__(self, "environment_id", "")
        if self.theorem_digest:
            object.__setattr__(
                self,
                "theorem_digest",
                _sha256_hex(self.theorem_digest, "theorem_digest"),
            )
        else:
            object.__setattr__(self, "theorem_digest", "")
        object.__setattr__(
            self, "phase", _enum(self.phase, KernelPhase, "phase")
        )
        if self.phase is not KernelPhase.OFFICIAL_KERNEL:
            raise KernelAuthorityError(
                "official kernel result must bind phase=official_kernel"
            )
        object.__setattr__(
            self,
            "authority",
            _enum(self.authority, ResultAuthority, "authority"),
        )
        # Fail-closed: theorem authority only with accepted=True.
        if self.authority is ResultAuthority.THEOREM and not self.accepted:
            raise KernelAuthorityError(
                "theorem authority requires official kernel accepted=True"
            )
        if self.accepted and self.authority is not ResultAuthority.THEOREM:
            # Accepted but not yet elevated is allowed only when status is
            # not proved; enforce consistency with status.
            if self.result_status is ResultStatus.PROVED:
                raise KernelAuthorityError(
                    "accepted official kernel with proved status requires "
                    "theorem authority"
                )
        object.__setattr__(
            self, "diagnostics", _bound_diagnostics(self.diagnostics)
        )
        if self.schema_version != KERNEL_OFFICIAL_RESULT_BINDING_SCHEMA:
            raise KernelExecutionError(
                f"unsupported official-result binding schema: {self.schema_version!r}"
            )

    @classmethod
    def unbound(
        cls,
        *,
        kernel_provider: KernelProviderKind | str,
        environment_id: str = "",
        theorem_digest: str = "",
        reason: str = "official kernel not executed",
    ) -> KernelOfficialResultBindingV2:
        return cls(
            accepted=False,
            kernel_provider=kernel_provider,
            receipt_id="",
            result_status=ResultStatus.UNAVAILABLE,
            environment_id=environment_id,
            theorem_digest=theorem_digest,
            phase=KernelPhase.OFFICIAL_KERNEL,
            authority=ResultAuthority.CANDIDATE,
            diagnostics=(reason,) if reason else (),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "authority": (
                self.authority.value
                if isinstance(self.authority, ResultAuthority)
                else self.authority
            ),
            "diagnostics": list(self.diagnostics),
            "environment_id": self.environment_id,
            "interface": self.interface,
            "kernel_provider": (
                self.kernel_provider.value
                if isinstance(self.kernel_provider, KernelProviderKind)
                else self.kernel_provider
            ),
            "phase": (
                self.phase.value
                if isinstance(self.phase, KernelPhase)
                else self.phase
            ),
            "receipt_id": self.receipt_id,
            "result_status": (
                self.result_status.value
                if isinstance(self.result_status, ResultStatus)
                else self.result_status
            ),
            "schema_version": self.schema_version,
            "theorem_digest": self.theorem_digest,
        }


# ---------------------------------------------------------------------------
# Phase receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KernelPhaseReceiptV2:
    """Auditable receipt for exactly one pipeline phase.

    Interface: ``KernelPhaseReceipt@2``.

    No phase except ``official_kernel`` with ``status=accepted`` may claim
    theorem authority.  Hammer stages are permanently candidate-only.
    """

    phase: KernelPhase | str
    status: KernelPhaseStatus | str
    authority: ResultAuthority | str = ResultAuthority.CANDIDATE
    provider_ids: tuple[str, ...] = ()
    payload: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
    schema_version: str = KERNEL_PHASE_RECEIPT_SCHEMA

    interface: ClassVar[str] = KERNEL_PHASE_RECEIPT_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "phase", _enum(self.phase, KernelPhase, "phase")
        )
        object.__setattr__(
            self, "status", _enum(self.status, KernelPhaseStatus, "status")
        )
        object.__setattr__(
            self,
            "authority",
            _enum(self.authority, ResultAuthority, "authority"),
        )
        object.__setattr__(
            self,
            "provider_ids",
            _string_tuple(self.provider_ids, "provider_ids", allow_empty=True),
        )
        payload = dict(_require_mapping(self.payload, "payload"))
        object.__setattr__(
            self, "payload", dict(_freeze_mapping(payload, "payload"))
        )
        object.__setattr__(
            self, "diagnostics", _bound_diagnostics(self.diagnostics)
        )
        # Fail-closed authority gates.
        phase = self.phase  # type: ignore[assignment]
        status = self.status  # type: ignore[assignment]
        authority = self.authority  # type: ignore[assignment]
        if authority is ResultAuthority.THEOREM:
            if phase is not KernelPhase.OFFICIAL_KERNEL:
                raise KernelAuthorityError(
                    "only the official_kernel phase may claim theorem authority"
                )
            if status is not KernelPhaseStatus.ACCEPTED:
                raise KernelAuthorityError(
                    "theorem authority requires official_kernel status=accepted"
                )
        if phase in {
            KernelPhase.PREMISE_SELECTION,
            KernelPhase.ATP_CANDIDATE,
        } and authority is not ResultAuthority.CANDIDATE:
            raise KernelAuthorityError(
                "Hammer premise selection and ATP candidate phases are "
                "candidate authority only"
            )
        if (
            phase is KernelPhase.RECONSTRUCTION
            and authority
            not in {ResultAuthority.RECONSTRUCTION, ResultAuthority.CANDIDATE}
        ):
            raise KernelAuthorityError(
                "reconstruction phase cannot claim theorem authority"
            )
        if self.schema_version != KERNEL_PHASE_RECEIPT_SCHEMA:
            raise KernelExecutionError(
                f"unsupported phase receipt schema: {self.schema_version!r}"
            )

    @property
    def receipt_id(self) -> str:
        return f"kernel-phase:{self.phase.value}:{_digest_of(self.to_dict())[:24]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": (
                self.authority.value
                if isinstance(self.authority, ResultAuthority)
                else self.authority
            ),
            "diagnostics": list(self.diagnostics),
            "interface": self.interface,
            "payload": dict(self.payload),
            "phase": (
                self.phase.value
                if isinstance(self.phase, KernelPhase)
                else self.phase
            ),
            "provider_ids": list(self.provider_ids),
            "schema_version": self.schema_version,
            "status": (
                self.status.value
                if isinstance(self.status, KernelPhaseStatus)
                else self.status
            ),
        }


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KernelExecutionRequestV2:
    """Typed Hammer → reconstruction → official-kernel execution request.

    Interface: ``KernelExecutionRequest@2``.
    """

    request_id: str
    provider: KernelProviderKind | str
    theory: TargetTheoryArtifact | Mapping[str, Any]
    mode: KernelExecutionMode | str = KernelExecutionMode.FULL_PIPELINE
    theorem_id: str | None = None
    proof_body: str = ""
    environment_id: str = ""
    environment: Mapping[str, Any] = field(default_factory=dict)
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    bounds: ExecutionBounds | None = None
    # Injected phase outcomes (hermetic tests / pinned runners).
    hammer_premises: Sequence[str] | tuple[str, ...] = ()
    hammer_atp_verdict: str = ""
    hammer_candidate_id: str = ""
    reconstruction_accepted: bool | None = None
    reconstruction_source: str = ""
    official_kernel_accepted: bool | None = None
    official_kernel_receipt_id: str = ""
    official_kernel_diagnostics: Sequence[str] | tuple[str, ...] = ()
    mock_output: Mapping[str, Any] | None = None
    fallback_output: Mapping[str, Any] | None = None
    available: bool = True
    confidence: float = 0.0
    fluent_text: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = KERNEL_EXECUTION_REQUEST_SCHEMA

    interface: ClassVar[str] = KERNEL_EXECUTION_REQUEST_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "provider", normalize_kernel_provider(self.provider)
        )
        theory = _theory_from_value(self.theory)
        object.__setattr__(self, "theory", theory)
        object.__setattr__(
            self, "mode", _enum(self.mode, KernelExecutionMode, "mode")
        )
        if self.theorem_id is not None:
            object.__setattr__(
                self, "theorem_id", _record_id(self.theorem_id, "theorem_id")
            )
        if self.proof_body:
            if not isinstance(self.proof_body, str) or "\x00" in self.proof_body:
                raise KernelExecutionError(
                    "proof_body must be text without NUL bytes"
                )
        else:
            object.__setattr__(self, "proof_body", "")
        if self.environment_id:
            object.__setattr__(
                self,
                "environment_id",
                _record_id(self.environment_id, "environment_id"),
            )
        else:
            provider = self.provider  # type: ignore[assignment]
            object.__setattr__(
                self,
                "environment_id",
                f"env:{provider.value}:default",
            )
        env = dict(_require_mapping(self.environment, "environment"))
        object.__setattr__(
            self, "environment", dict(_freeze_mapping(env, "environment"))
        )
        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids or ())
        )
        if self.bounds is None:
            object.__setattr__(
                self,
                "bounds",
                ExecutionBounds(timeout_ms=5_000, max_steps=1_000),
            )
        elif not isinstance(self.bounds, ExecutionBounds):
            raise KernelExecutionError("bounds must be ExecutionBounds")
        object.__setattr__(
            self,
            "hammer_premises",
            _string_tuple(
                self.hammer_premises or (), "hammer_premises", allow_empty=True
            ),
        )
        object.__setattr__(
            self,
            "hammer_atp_verdict",
            _text(
                self.hammer_atp_verdict,
                "hammer_atp_verdict",
                maximum=64,
                allow_empty=True,
            ),
        )
        if self.hammer_candidate_id:
            object.__setattr__(
                self,
                "hammer_candidate_id",
                _record_id(self.hammer_candidate_id, "hammer_candidate_id"),
            )
        else:
            object.__setattr__(self, "hammer_candidate_id", "")
        if self.reconstruction_accepted is not None:
            object.__setattr__(
                self,
                "reconstruction_accepted",
                _optional_bool(
                    self.reconstruction_accepted, "reconstruction_accepted"
                ),
            )
        if self.reconstruction_source:
            if (
                not isinstance(self.reconstruction_source, str)
                or "\x00" in self.reconstruction_source
            ):
                raise KernelExecutionError(
                    "reconstruction_source must be text without NUL bytes"
                )
        else:
            object.__setattr__(self, "reconstruction_source", "")
        if self.official_kernel_accepted is not None:
            object.__setattr__(
                self,
                "official_kernel_accepted",
                _optional_bool(
                    self.official_kernel_accepted, "official_kernel_accepted"
                ),
            )
        if self.official_kernel_receipt_id:
            object.__setattr__(
                self,
                "official_kernel_receipt_id",
                _record_id(
                    self.official_kernel_receipt_id,
                    "official_kernel_receipt_id",
                ),
            )
        else:
            object.__setattr__(self, "official_kernel_receipt_id", "")
        object.__setattr__(
            self,
            "official_kernel_diagnostics",
            _bound_diagnostics(self.official_kernel_diagnostics or ()),
        )
        object.__setattr__(
            self, "available", _optional_bool(self.available, "available")
        )
        object.__setattr__(
            self, "confidence", _unit_interval(self.confidence, "confidence")
        )
        object.__setattr__(
            self,
            "fluent_text",
            _text(
                self.fluent_text, "fluent_text", maximum=8_192, allow_empty=True
            ),
        )
        if self.mock_output is None:
            object.__setattr__(self, "mock_output", None)
        else:
            mock = _require_mapping(self.mock_output, "mock_output")
            object.__setattr__(
                self, "mock_output", dict(_freeze_mapping(mock, "mock_output"))
            )
        if self.fallback_output is None:
            object.__setattr__(self, "fallback_output", None)
        else:
            fb = _require_mapping(self.fallback_output, "fallback_output")
            object.__setattr__(
                self,
                "fallback_output",
                dict(_freeze_mapping(fb, "fallback_output")),
            )
        meta = dict(_require_mapping(self.metadata, "metadata"))
        _forbid_authority_metadata(meta, "metadata")
        encoded = canonical_json_bytes(meta)
        if len(encoded) > _MAX_METADATA_BYTES:
            raise KernelExecutionError(
                f"metadata exceeds hard limit {_MAX_METADATA_BYTES} bytes"
            )
        object.__setattr__(
            self, "metadata", dict(_freeze_mapping(meta, "metadata"))
        )
        if self.schema_version != KERNEL_EXECUTION_REQUEST_SCHEMA:
            raise KernelExecutionError(
                f"unsupported request schema: {self.schema_version!r}"
            )

    def selected_theorem(self) -> dict[str, Any]:
        theory = self.theory  # type: ignore[assignment]
        assert isinstance(theory, TargetTheoryArtifact)
        if self.theorem_id is None:
            if not theory.theorems:
                raise KernelExecutionError("theory has no theorems")
            return dict(theory.theorems[0])
        for item in theory.theorems:
            if item["theorem_id"] == self.theorem_id:
                return dict(item)
        raise KernelExecutionError(
            f"unknown theorem_id {self.theorem_id!r}"
        )

    def to_dict(self) -> dict[str, Any]:
        theory = self.theory
        return {
            "available": self.available,
            "bounds": self.bounds.to_dict() if self.bounds else {},
            "confidence": self.confidence,
            "environment": dict(self.environment),
            "environment_id": self.environment_id,
            "fallback_output": (
                None
                if self.fallback_output is None
                else dict(self.fallback_output)
            ),
            "fluent_text": self.fluent_text,
            "hammer_atp_verdict": self.hammer_atp_verdict,
            "hammer_candidate_id": self.hammer_candidate_id,
            "hammer_premises": list(self.hammer_premises),
            "interface": self.interface,
            "metadata": dict(self.metadata),
            "mode": (
                self.mode.value
                if isinstance(self.mode, KernelExecutionMode)
                else self.mode
            ),
            "mock_output": (
                None if self.mock_output is None else dict(self.mock_output)
            ),
            "official_kernel_accepted": self.official_kernel_accepted,
            "official_kernel_diagnostics": list(
                self.official_kernel_diagnostics
            ),
            "official_kernel_receipt_id": self.official_kernel_receipt_id,
            "proof_body": self.proof_body,
            "provider": (
                self.provider.value
                if isinstance(self.provider, KernelProviderKind)
                else self.provider
            ),
            "reconstruction_accepted": self.reconstruction_accepted,
            "reconstruction_source": self.reconstruction_source,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "theorem_id": self.theorem_id,
            "theory": (
                theory.to_dict()
                if isinstance(theory, TargetTheoryArtifact)
                else dict(theory)
            ),
        }


# ---------------------------------------------------------------------------
# Evidence / result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KernelProviderEvidenceV2:
    """Complete KernelProviderEvidence@2 record.

    Binds imports, axioms, admits, trust escapes, environment, source
    theorem, official kernel result, and separated phase receipts.
    """

    evidence_id: str
    request_id: str
    provider: KernelProviderKind | str
    disposition: KernelDisposition | str
    phases: tuple[KernelPhaseReceiptV2, ...]
    imports: KernelImportBindingV2
    axioms: KernelAxiomBindingV2
    admits: KernelAdmitBindingV2
    trust_escapes: KernelTrustEscapeBindingV2
    environment: KernelEnvironmentBindingV2
    source_theorem: KernelSourceTheoremBindingV2
    official_kernel: KernelOfficialResultBindingV2
    result_authority: ResultAuthority | str = ResultAuthority.CANDIDATE
    result_status: ResultStatus | str = ResultStatus.CANDIDATE
    role: ToolRole | str = ToolRole.AUTHORITY
    authority_ceiling: ToolchainAuthorityCeiling | str = (
        ToolchainAuthorityCeiling.KERNEL
    )
    candidate_id: str = ""
    reconstruction_id: str = ""
    hammer_is_proof_authority: bool = False
    proof_established: bool = False
    diagnostics: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = KERNEL_PROVIDER_EVIDENCE_SCHEMA

    interface: ClassVar[str] = KERNEL_PROVIDER_EVIDENCE_V2_INTERFACE
    TASK_ID: ClassVar[str] = KERNEL_EXECUTION_V2_TASK_ID

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _record_id(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "provider", normalize_kernel_provider(self.provider)
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, KernelDisposition, "disposition"),
        )
        phases = tuple(self.phases)
        if not all(isinstance(item, KernelPhaseReceiptV2) for item in phases):
            raise KernelExecutionError(
                "phases must be KernelPhaseReceiptV2 values"
            )
        phase_names = [item.phase for item in phases]
        if len(phase_names) != len(set(phase_names)):
            raise KernelExecutionError("phase receipts must be unique by phase")
        object.__setattr__(self, "phases", phases)
        for field_name, expected_type in (
            ("imports", KernelImportBindingV2),
            ("axioms", KernelAxiomBindingV2),
            ("admits", KernelAdmitBindingV2),
            ("trust_escapes", KernelTrustEscapeBindingV2),
            ("environment", KernelEnvironmentBindingV2),
            ("source_theorem", KernelSourceTheoremBindingV2),
            ("official_kernel", KernelOfficialResultBindingV2),
        ):
            value = getattr(self, field_name)
            if not isinstance(value, expected_type):
                raise KernelExecutionError(
                    f"{field_name} must be {expected_type.__name__}"
                )
        object.__setattr__(
            self,
            "result_authority",
            _enum(self.result_authority, ResultAuthority, "result_authority"),
        )
        object.__setattr__(
            self,
            "result_status",
            _enum(self.result_status, ResultStatus, "result_status"),
        )
        object.__setattr__(
            self, "role", _enum(self.role, ToolRole, "role")
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _enum(
                self.authority_ceiling,
                ToolchainAuthorityCeiling,
                "authority_ceiling",
            ),
        )
        if self.candidate_id:
            object.__setattr__(
                self,
                "candidate_id",
                _record_id(self.candidate_id, "candidate_id"),
            )
        if self.reconstruction_id:
            object.__setattr__(
                self,
                "reconstruction_id",
                _record_id(self.reconstruction_id, "reconstruction_id"),
            )
        # Hard invariant: Hammer is never proof authority.
        object.__setattr__(
            self,
            "hammer_is_proof_authority",
            _optional_bool(
                self.hammer_is_proof_authority, "hammer_is_proof_authority"
            ),
        )
        if self.hammer_is_proof_authority:
            raise KernelAuthorityError(
                "Hammer never becomes proof authority "
                "(hammer_is_proof_authority must be False)"
            )
        object.__setattr__(
            self,
            "proof_established",
            _optional_bool(self.proof_established, "proof_established"),
        )
        # Proof only when official kernel accepted + theorem authority.
        if self.proof_established:
            if not self.official_kernel.accepted:
                raise KernelAuthorityError(
                    "proof_established requires official kernel acceptance"
                )
            if self.result_authority is not ResultAuthority.THEOREM:
                raise KernelAuthorityError(
                    "proof_established requires theorem result authority"
                )
            if self.admits.blocks_theorem_authority:
                raise KernelAuthorityError(
                    "proof_established blocked by detected admits"
                )
            if self.trust_escapes.blocks_theorem_authority:
                raise KernelAuthorityError(
                    "proof_established blocked by trust escapes"
                )
            if (
                self.official_kernel.environment_id
                and self.official_kernel.environment_id
                != self.environment.environment_id
            ):
                raise KernelAuthorityError(
                    "proof_established blocked by environment binding mismatch"
                )
            if (
                self.official_kernel.theorem_digest
                and self.official_kernel.theorem_digest
                != self.source_theorem.statement_digest
            ):
                raise KernelAuthorityError(
                    "proof_established blocked by source-theorem mismatch"
                )
        object.__setattr__(
            self, "diagnostics", _bound_diagnostics(self.diagnostics)
        )
        meta = dict(_require_mapping(self.metadata, "metadata"))
        _forbid_authority_metadata(meta, "metadata")
        object.__setattr__(
            self, "metadata", dict(_freeze_mapping(meta, "metadata"))
        )
        if self.schema_version != KERNEL_PROVIDER_EVIDENCE_SCHEMA:
            raise KernelExecutionError(
                f"unsupported evidence schema: {self.schema_version!r}"
            )

    @property
    def is_proved(self) -> bool:
        return (
            self.proof_established
            and self.result_authority is ResultAuthority.THEOREM
            and self.result_status is ResultStatus.PROVED
            and self.official_kernel.accepted
            and not self.hammer_is_proof_authority
        )

    def phase(self, name: KernelPhase | str) -> KernelPhaseReceiptV2 | None:
        target = name if isinstance(name, KernelPhase) else KernelPhase(name)
        for receipt in self.phases:
            if receipt.phase is target:
                return receipt
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "admits": self.admits.to_dict(),
            "authority_ceiling": (
                self.authority_ceiling.value
                if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
                else self.authority_ceiling
            ),
            "axioms": self.axioms.to_dict(),
            "candidate_id": self.candidate_id,
            "diagnostics": list(self.diagnostics),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, KernelDisposition)
                else self.disposition
            ),
            "environment": self.environment.to_dict(),
            "evidence_id": self.evidence_id,
            "hammer_is_proof_authority": False,
            "imports": self.imports.to_dict(),
            "interface": self.interface,
            "metadata": dict(self.metadata),
            "official_kernel": self.official_kernel.to_dict(),
            "phases": [item.to_dict() for item in self.phases],
            "proof_established": self.proof_established,
            "provider": (
                self.provider.value
                if isinstance(self.provider, KernelProviderKind)
                else self.provider
            ),
            "reconstruction_id": self.reconstruction_id,
            "request_id": self.request_id,
            "result_authority": (
                self.result_authority.value
                if isinstance(self.result_authority, ResultAuthority)
                else self.result_authority
            ),
            "result_status": (
                self.result_status.value
                if isinstance(self.result_status, ResultStatus)
                else self.result_status
            ),
            "role": (
                self.role.value if isinstance(self.role, ToolRole) else self.role
            ),
            "schema_version": self.schema_version,
            "source_theorem": self.source_theorem.to_dict(),
            "trust_escapes": self.trust_escapes.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class KernelExecutionResultV2:
    """Typed execution result wrapping :class:`KernelProviderEvidenceV2`.

    Interface: ``KernelExecutionResult@2``.
    """

    request_id: str
    disposition: KernelDisposition | str
    evidence: KernelProviderEvidenceV2
    typed_result: TypedBackendResult | None = None
    candidate: KernelCompilationCandidate | None = None
    schema_version: str = KERNEL_EXECUTION_RESULT_SCHEMA

    interface: ClassVar[str] = KERNEL_EXECUTION_RESULT_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, KernelDisposition, "disposition"),
        )
        if not isinstance(self.evidence, KernelProviderEvidenceV2):
            raise KernelExecutionError(
                "evidence must be KernelProviderEvidenceV2"
            )
        if self.request_id != self.evidence.request_id:
            raise KernelExecutionError(
                "result request_id must match evidence.request_id"
            )
        if self.disposition is not self.evidence.disposition:
            raise KernelExecutionError(
                "result disposition must match evidence.disposition"
            )
        if self.typed_result is not None and not isinstance(
            self.typed_result, TypedBackendResult
        ):
            raise KernelExecutionError(
                "typed_result must be TypedBackendResult when provided"
            )
        if self.candidate is not None and not isinstance(
            self.candidate, KernelCompilationCandidate
        ):
            raise KernelExecutionError(
                "candidate must be KernelCompilationCandidate when provided"
            )
        if self.schema_version != KERNEL_EXECUTION_RESULT_SCHEMA:
            raise KernelExecutionError(
                f"unsupported result schema: {self.schema_version!r}"
            )

    @property
    def is_proved(self) -> bool:
        return self.evidence.is_proved

    @property
    def proof_established(self) -> bool:
        return self.evidence.proof_established

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": (
                self.candidate.to_dict() if self.candidate is not None else None
            ),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, KernelDisposition)
                else self.disposition
            ),
            "evidence": self.evidence.to_dict(),
            "interface": self.interface,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "typed_result": (
                self.typed_result.to_dict()
                if self.typed_result is not None
                else None
            ),
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class KernelExecutionEngineV2:
    """Orchestrate separated Hammer / reconstruction / official-kernel phases.

    Interface: ``KernelProviderEvidence@2``.
    """

    INTERFACE: ClassVar[str] = KERNEL_PROVIDER_EVIDENCE_V2_INTERFACE
    TASK_ID: ClassVar[str] = KERNEL_EXECUTION_V2_TASK_ID
    MODULE_VERSION: ClassVar[str] = KERNEL_EXECUTION_V2_MODULE_VERSION
    PHASE_ORDER: ClassVar[tuple[str, ...]] = _PHASE_ORDER

    def __init__(
        self,
        *,
        compiler: KernelTargetCompiler | None = None,
        kernel_checker: Callable[
            [KernelExecutionRequestV2, KernelCompilationCandidate],
            Mapping[str, Any],
        ]
        | None = None,
    ) -> None:
        self._compiler = compiler or KernelTargetCompiler()
        self._kernel_checker = kernel_checker

    @property
    def interface(self) -> str:
        return self.INTERFACE

    def execute(
        self, request: KernelExecutionRequestV2 | Mapping[str, Any]
    ) -> KernelExecutionResultV2:
        if isinstance(request, Mapping):
            request = KernelExecutionRequestV2(**dict(request))  # type: ignore[arg-type]
        if not isinstance(request, KernelExecutionRequestV2):
            raise KernelExecutionError(
                "request must be KernelExecutionRequestV2 or mapping"
            )
        return self._execute(request)

    def _execute(
        self, request: KernelExecutionRequestV2
    ) -> KernelExecutionResultV2:
        provider = request.provider  # type: ignore[assignment]
        assert isinstance(provider, KernelProviderKind)
        mode = request.mode  # type: ignore[assignment]
        assert isinstance(mode, KernelExecutionMode)

        # Mode gates that never establish proof.
        if mode is KernelExecutionMode.MOCK or request.mock_output is not None:
            return self._reject_non_authoritative(
                request,
                disposition=KernelDisposition.MOCK_REJECTED,
                reason="mock output cannot establish kernel proof authority",
            )
        if (
            mode is KernelExecutionMode.FALLBACK
            or request.fallback_output is not None
        ):
            return self._reject_non_authoritative(
                request,
                disposition=KernelDisposition.FALLBACK_REJECTED,
                reason="fallback output cannot establish kernel proof authority",
            )

        theory = request.theory  # type: ignore[assignment]
        assert isinstance(theory, TargetTheoryArtifact)
        theorem = request.selected_theorem()
        phases: list[KernelPhaseReceiptV2] = []
        diagnostics: list[str] = []

        # --- Phase 1: premise selection (Hammer, candidate only) ----------
        premises = tuple(request.hammer_premises)
        if mode in {
            KernelExecutionMode.FULL_PIPELINE,
            KernelExecutionMode.HAMMER_ONLY,
        }:
            if premises:
                phases.append(
                    KernelPhaseReceiptV2(
                        phase=KernelPhase.PREMISE_SELECTION,
                        status=KernelPhaseStatus.COMPLETED,
                        authority=ResultAuthority.CANDIDATE,
                        provider_ids=("hammer", "deterministic_baseline"),
                        payload={
                            "premise_ids": list(premises),
                            "selected_count": len(premises),
                            "theorem_authority_forbidden": True,
                        },
                    )
                )
            else:
                phases.append(
                    KernelPhaseReceiptV2(
                        phase=KernelPhase.PREMISE_SELECTION,
                        status=KernelPhaseStatus.SKIPPED,
                        authority=ResultAuthority.CANDIDATE,
                        provider_ids=("hammer",),
                        payload={"theorem_authority_forbidden": True},
                        diagnostics=(
                            "no premises supplied; premise selection skipped",
                        ),
                    )
                )
        else:
            phases.append(
                KernelPhaseReceiptV2(
                    phase=KernelPhase.PREMISE_SELECTION,
                    status=KernelPhaseStatus.SKIPPED,
                    authority=ResultAuthority.CANDIDATE,
                    payload={"theorem_authority_forbidden": True},
                    diagnostics=(f"skipped under mode={mode.value}",),
                )
            )

        # --- Phase 2: ATP candidate (Hammer, candidate only) --------------
        atp_verdict = (request.hammer_atp_verdict or "").strip().lower()
        candidate_id = request.hammer_candidate_id
        atp_success = atp_verdict in {
            "proved",
            "unsat",
            "theorem",
            "verified",
            "sat",
            "candidate",
        }
        if mode in {
            KernelExecutionMode.FULL_PIPELINE,
            KernelExecutionMode.HAMMER_ONLY,
        }:
            if atp_verdict:
                if not candidate_id:
                    candidate_id = (
                        f"candidate:hammer:{provider.value}:"
                        f"{_digest_of({'verdict': atp_verdict, 'request': request.request_id})[:16]}"
                    )
                phases.append(
                    KernelPhaseReceiptV2(
                        phase=KernelPhase.ATP_CANDIDATE,
                        status=KernelPhaseStatus.CANDIDATE_ONLY,
                        authority=ResultAuthority.CANDIDATE,
                        provider_ids=("hammer", "atp"),
                        payload={
                            "candidate_id": candidate_id,
                            "verdict": atp_verdict,
                            "unreconstructed": True,
                            "theorem_authority_forbidden": True,
                            "hammer_is_proof_authority": False,
                        },
                    )
                )
            else:
                phases.append(
                    KernelPhaseReceiptV2(
                        phase=KernelPhase.ATP_CANDIDATE,
                        status=KernelPhaseStatus.SKIPPED,
                        authority=ResultAuthority.CANDIDATE,
                        provider_ids=("hammer",),
                        payload={
                            "theorem_authority_forbidden": True,
                            "hammer_is_proof_authority": False,
                        },
                        diagnostics=("no ATP verdict supplied",),
                    )
                )
        else:
            phases.append(
                KernelPhaseReceiptV2(
                    phase=KernelPhase.ATP_CANDIDATE,
                    status=KernelPhaseStatus.SKIPPED,
                    authority=ResultAuthority.CANDIDATE,
                    payload={
                        "theorem_authority_forbidden": True,
                        "hammer_is_proof_authority": False,
                    },
                    diagnostics=(f"skipped under mode={mode.value}",),
                )
            )

        # Hammer-only mode terminates as candidate — never proved.
        if mode is KernelExecutionMode.HAMMER_ONLY:
            return self._finish_candidate(
                request=request,
                theory=theory,
                theorem=theorem,
                phases=phases,
                candidate_id=candidate_id,
                diagnostics=diagnostics
                + [
                    "hammer_only mode: Hammer success remains candidate evidence",
                    "hammer never becomes proof authority",
                ],
                disposition=KernelDisposition.HAMMER_CANDIDATE_ONLY,
                candidate=None,
            )

        # --- Phase 3: reconstruction -------------------------------------
        reconstruction_id = ""
        reconstruction_source = request.reconstruction_source or ""
        reconstruction_ok = False
        if mode in {
            KernelExecutionMode.FULL_PIPELINE,
            KernelExecutionMode.RECONSTRUCTION_ONLY,
            KernelExecutionMode.COMPILE_AND_CHECK,
            KernelExecutionMode.OFFICIAL_KERNEL,
        }:
            if request.reconstruction_accepted is True:
                reconstruction_ok = True
                reconstruction_id = (
                    f"reconstruction:{request.request_id}:"
                    f"{_digest_of({'source': reconstruction_source[:256]})[:16]}"
                )
                phases.append(
                    KernelPhaseReceiptV2(
                        phase=KernelPhase.RECONSTRUCTION,
                        status=KernelPhaseStatus.RECONSTRUCTED,
                        authority=ResultAuthority.RECONSTRUCTION,
                        provider_ids=("reconstructor", provider.value),
                        payload={
                            "reconstruction_id": reconstruction_id,
                            "kernel_accepted": False,
                            "independent_of_hammer_authority": True,
                            "candidate_id": candidate_id,
                        },
                    )
                )
            elif request.reconstruction_accepted is False:
                phases.append(
                    KernelPhaseReceiptV2(
                        phase=KernelPhase.RECONSTRUCTION,
                        status=KernelPhaseStatus.FAILED,
                        authority=ResultAuthority.RECONSTRUCTION,
                        provider_ids=("reconstructor", provider.value),
                        payload={
                            "kernel_accepted": False,
                            "candidate_id": candidate_id,
                        },
                        diagnostics=("reconstruction rejected by reconstructor",),
                    )
                )
                if mode is KernelExecutionMode.RECONSTRUCTION_ONLY:
                    return self._finish_candidate(
                        request=request,
                        theory=theory,
                        theorem=theorem,
                        phases=phases,
                        candidate_id=candidate_id,
                        reconstruction_id=reconstruction_id,
                        diagnostics=diagnostics
                        + ["reconstruction failed; no theorem authority"],
                        disposition=KernelDisposition.RECONSTRUCTION_FAILED,
                        candidate=None,
                        source_override=reconstruction_source,
                    )
            else:
                phases.append(
                    KernelPhaseReceiptV2(
                        phase=KernelPhase.RECONSTRUCTION,
                        status=KernelPhaseStatus.SKIPPED,
                        authority=ResultAuthority.RECONSTRUCTION,
                        payload={"kernel_accepted": False},
                        diagnostics=("reconstruction not requested",),
                    )
                )
        else:
            phases.append(
                KernelPhaseReceiptV2(
                    phase=KernelPhase.RECONSTRUCTION,
                    status=KernelPhaseStatus.SKIPPED,
                    authority=ResultAuthority.RECONSTRUCTION,
                    diagnostics=(f"skipped under mode={mode.value}",),
                )
            )

        if mode is KernelExecutionMode.RECONSTRUCTION_ONLY:
            disposition = (
                KernelDisposition.RECONSTRUCTED
                if reconstruction_ok
                else KernelDisposition.RECONSTRUCTION_FAILED
            )
            return self._finish_candidate(
                request=request,
                theory=theory,
                theorem=theorem,
                phases=phases,
                candidate_id=candidate_id,
                reconstruction_id=reconstruction_id,
                diagnostics=diagnostics
                + [
                    "reconstruction_only mode: reconstruction is not theorem authority",
                    "official kernel acceptance required for proof",
                ],
                disposition=disposition,
                candidate=None,
                source_override=reconstruction_source,
                reconstruction_authority=reconstruction_ok,
            )

        # --- Phase 4: target compilation ---------------------------------
        target = provider_to_kernel_target(provider)
        if not is_official_kernel(target):
            return self._finish_candidate(
                request=request,
                theory=theory,
                theorem=theorem,
                phases=phases,
                candidate_id=candidate_id,
                diagnostics=diagnostics + [f"unsupported kernel target {target!r}"],
                disposition=KernelDisposition.UNSUPPORTED,
                candidate=None,
            )

        env = dict(request.environment)
        env.setdefault("environment_id", request.environment_id)
        env.setdefault("kernel_target", provider.value)
        env.setdefault("toolchain_id", provider.value)
        env.setdefault("toolchain_version", "pinned-unspecified")

        proof_body = request.proof_body
        if reconstruction_source and not proof_body:
            # Prefer reconstructed proof body when provided.
            proof_body = reconstruction_source

        try:
            if proof_body:
                # Reject trust escapes early when caller supplies proof body.
                reject_trust_escapes(proof_body, path="proof_body")
            candidate = self._compiler.compile(
                theory,
                kernel_target=target,
                theorem_id=theorem["theorem_id"],
                environment=env,
                proof_body=proof_body,
            )
        except (KernelTargetTranslationError, KernelExecutionError) as error:
            msg = str(error)
            if "trust escape" in msg.lower() or "sorry" in msg.lower() or "admit" in msg.lower():
                phases.append(
                    KernelPhaseReceiptV2(
                        phase=KernelPhase.TARGET_COMPILATION,
                        status=KernelPhaseStatus.REJECTED,
                        authority=ResultAuthority.CANDIDATE,
                        diagnostics=(msg[:512],),
                    )
                )
                # Still emit remaining phases as skipped for audit completeness.
                for phase in (
                    KernelPhase.ELABORATION,
                    KernelPhase.OFFICIAL_KERNEL,
                ):
                    phases.append(
                        KernelPhaseReceiptV2(
                            phase=phase,
                            status=KernelPhaseStatus.SKIPPED,
                            authority=ResultAuthority.CANDIDATE,
                            diagnostics=("skipped after trust-escape rejection",),
                        )
                    )
                return self._finish_candidate(
                    request=request,
                    theory=theory,
                    theorem=theorem,
                    phases=phases,
                    candidate_id=candidate_id,
                    reconstruction_id=reconstruction_id,
                    diagnostics=diagnostics + [msg],
                    disposition=KernelDisposition.TRUST_ESCAPE_REJECTED,
                    candidate=None,
                    source_override=proof_body or reconstruction_source,
                )
            phases.append(
                KernelPhaseReceiptV2(
                    phase=KernelPhase.TARGET_COMPILATION,
                    status=KernelPhaseStatus.FAILED,
                    authority=ResultAuthority.CANDIDATE,
                    diagnostics=(msg[:512],),
                )
            )
            for phase in (KernelPhase.ELABORATION, KernelPhase.OFFICIAL_KERNEL):
                phases.append(
                    KernelPhaseReceiptV2(
                        phase=phase,
                        status=KernelPhaseStatus.SKIPPED,
                        authority=ResultAuthority.CANDIDATE,
                        diagnostics=("skipped after compilation failure",),
                    )
                )
            return self._finish_candidate(
                request=request,
                theory=theory,
                theorem=theorem,
                phases=phases,
                candidate_id=candidate_id,
                reconstruction_id=reconstruction_id,
                diagnostics=diagnostics + [msg],
                disposition=KernelDisposition.ERROR,
                candidate=None,
            )

        phases.append(
            KernelPhaseReceiptV2(
                phase=KernelPhase.TARGET_COMPILATION,
                status=KernelPhaseStatus.CANDIDATE_ONLY,
                authority=ResultAuthority.CANDIDATE,
                provider_ids=("kernel_target_compiler", provider.value),
                payload={
                    "candidate_id": candidate.candidate_id,
                    "kernel_accepted": False,
                    "status": candidate.status.value
                    if isinstance(candidate.status, CompilationStatus)
                    else str(candidate.status),
                    "source_digest": candidate.source_digest,
                },
            )
        )

        # --- Phase 5: elaboration (binding scan of generated source) -----
        source_for_scan = candidate.source
        admit_binding = KernelAdmitBindingV2.bind(source_for_scan)
        escape_binding = KernelTrustEscapeBindingV2.bind(source_for_scan)
        if admit_binding.admits_present or escape_binding.escapes_present:
            phases.append(
                KernelPhaseReceiptV2(
                    phase=KernelPhase.ELABORATION,
                    status=KernelPhaseStatus.REJECTED,
                    authority=ResultAuthority.CANDIDATE,
                    provider_ids=(provider.value,),
                    payload={
                        "admits": list(admit_binding.admits),
                        "trust_escapes": list(escape_binding.trust_escapes),
                    },
                    diagnostics=(
                        "elaboration rejected: admits or trust escapes present",
                    ),
                )
            )
            phases.append(
                KernelPhaseReceiptV2(
                    phase=KernelPhase.OFFICIAL_KERNEL,
                    status=KernelPhaseStatus.SKIPPED,
                    authority=ResultAuthority.CANDIDATE,
                    diagnostics=(
                        "skipped: admits/trust escapes block official kernel acceptance",
                    ),
                )
            )
            disposition = (
                KernelDisposition.ADMIT_REJECTED
                if admit_binding.admits_present
                else KernelDisposition.TRUST_ESCAPE_REJECTED
            )
            return self._assemble(
                request=request,
                theory=theory,
                theorem=theorem,
                phases=phases,
                candidate=candidate,
                candidate_id=candidate.candidate_id,
                reconstruction_id=reconstruction_id,
                admit_binding=admit_binding,
                escape_binding=escape_binding,
                official=KernelOfficialResultBindingV2.unbound(
                    kernel_provider=provider,
                    environment_id=request.environment_id,
                    theorem_digest=candidate.statement_digest,
                    reason="blocked by admits or trust escapes",
                ),
                disposition=disposition,
                result_authority=ResultAuthority.CANDIDATE,
                result_status=ResultStatus.CANDIDATE,
                proof_established=False,
                diagnostics=diagnostics
                + ["admits/trust escapes block theorem authority"],
            )

        phases.append(
            KernelPhaseReceiptV2(
                phase=KernelPhase.ELABORATION,
                status=KernelPhaseStatus.COMPLETED,
                authority=ResultAuthority.CANDIDATE,
                provider_ids=(provider.value, "elaborator"),
                payload={
                    "source_digest": candidate.source_digest,
                    "admits_present": False,
                    "trust_escapes_present": False,
                },
            )
        )

        # --- Phase 6: official kernel (sole theorem authority) -----------
        return self._run_official_kernel(
            request=request,
            theory=theory,
            theorem=theorem,
            phases=phases,
            candidate=candidate,
            reconstruction_id=reconstruction_id,
            admit_binding=admit_binding,
            escape_binding=escape_binding,
            diagnostics=diagnostics,
            atp_success=atp_success,
            reconstruction_ok=reconstruction_ok,
        )

    def _run_official_kernel(
        self,
        *,
        request: KernelExecutionRequestV2,
        theory: TargetTheoryArtifact,
        theorem: Mapping[str, Any],
        phases: list[KernelPhaseReceiptV2],
        candidate: KernelCompilationCandidate,
        reconstruction_id: str,
        admit_binding: KernelAdmitBindingV2,
        escape_binding: KernelTrustEscapeBindingV2,
        diagnostics: list[str],
        atp_success: bool,
        reconstruction_ok: bool,
    ) -> KernelExecutionResultV2:
        provider = request.provider  # type: ignore[assignment]
        assert isinstance(provider, KernelProviderKind)

        accepted: bool | None = request.official_kernel_accepted
        receipt_id = request.official_kernel_receipt_id
        kernel_diagnostics = list(request.official_kernel_diagnostics)

        if self._kernel_checker is not None and accepted is None:
            try:
                raw = self._kernel_checker(request, candidate)
            except Exception as error:  # noqa: BLE001 — phase isolation
                raw = {
                    "accepted": False,
                    "diagnostics": (str(error)[:512],),
                    "status": "error",
                }
            accepted = bool(raw.get("accepted", False))
            receipt_id = str(
                raw.get("receipt_id")
                or receipt_id
                or f"receipt:{provider.value}:{candidate.source_digest[:16]}"
            )
            kernel_diagnostics.extend(
                str(item) for item in (raw.get("diagnostics") or ()) if item
            )

        if accepted is None:
            # No official kernel outcome available.
            phases.append(
                KernelPhaseReceiptV2(
                    phase=KernelPhase.OFFICIAL_KERNEL,
                    status=KernelPhaseStatus.UNAVAILABLE,
                    authority=ResultAuthority.CANDIDATE,
                    provider_ids=(provider.value,),
                    payload={
                        "accepted": False,
                        "hammer_cannot_substitute": True,
                        "atp_success": atp_success,
                        "reconstruction_ok": reconstruction_ok,
                    },
                    diagnostics=(
                        "official kernel not executed; "
                        "Hammer/reconstruction cannot substitute",
                    ),
                )
            )
            # Even with ATP success + reconstruction, remain candidate.
            if atp_success or reconstruction_ok:
                diagnostics = diagnostics + [
                    "Hammer/reconstruction success without official kernel "
                    "remains non-theorem evidence",
                ]
            return self._assemble(
                request=request,
                theory=theory,
                theorem=theorem,
                phases=phases,
                candidate=candidate,
                candidate_id=candidate.candidate_id,
                reconstruction_id=reconstruction_id,
                admit_binding=admit_binding,
                escape_binding=escape_binding,
                official=KernelOfficialResultBindingV2.unbound(
                    kernel_provider=provider,
                    environment_id=request.environment_id,
                    theorem_digest=candidate.statement_digest,
                    reason="official kernel unavailable",
                ),
                disposition=(
                    KernelDisposition.RECONSTRUCTED
                    if reconstruction_ok
                    else KernelDisposition.CANDIDATE
                ),
                result_authority=(
                    ResultAuthority.RECONSTRUCTION
                    if reconstruction_ok
                    else ResultAuthority.CANDIDATE
                ),
                result_status=(
                    ResultStatus.RECONSTRUCTED
                    if reconstruction_ok
                    else ResultStatus.CANDIDATE
                ),
                proof_established=False,
                diagnostics=diagnostics,
            )

        if not accepted:
            phases.append(
                KernelPhaseReceiptV2(
                    phase=KernelPhase.OFFICIAL_KERNEL,
                    status=KernelPhaseStatus.REJECTED,
                    authority=ResultAuthority.CANDIDATE,
                    provider_ids=(provider.value,),
                    payload={
                        "accepted": False,
                        "receipt_id": receipt_id,
                        "hammer_cannot_substitute": True,
                    },
                    diagnostics=tuple(kernel_diagnostics)
                    or ("official kernel rejected the candidate",),
                )
            )
            return self._assemble(
                request=request,
                theory=theory,
                theorem=theorem,
                phases=phases,
                candidate=candidate,
                candidate_id=candidate.candidate_id,
                reconstruction_id=reconstruction_id,
                admit_binding=admit_binding,
                escape_binding=escape_binding,
                official=KernelOfficialResultBindingV2(
                    accepted=False,
                    kernel_provider=provider,
                    receipt_id=receipt_id
                    or f"receipt:{provider.value}:rejected",
                    result_status=ResultStatus.DISPROVED
                    if "disproved" in " ".join(kernel_diagnostics).lower()
                    else ResultStatus.CANDIDATE,
                    environment_id=request.environment_id,
                    theorem_digest=candidate.statement_digest,
                    phase=KernelPhase.OFFICIAL_KERNEL,
                    authority=ResultAuthority.CANDIDATE,
                    diagnostics=tuple(kernel_diagnostics),
                ),
                disposition=KernelDisposition.KERNEL_REJECTED,
                result_authority=ResultAuthority.CANDIDATE,
                result_status=ResultStatus.CANDIDATE,
                proof_established=False,
                diagnostics=diagnostics + kernel_diagnostics,
            )

        # Official kernel accepted — still require binding coherence.
        if not receipt_id:
            receipt_id = (
                f"receipt:{provider.value}:{candidate.source_digest[:16]}"
            )
        phases.append(
            KernelPhaseReceiptV2(
                phase=KernelPhase.OFFICIAL_KERNEL,
                status=KernelPhaseStatus.ACCEPTED,
                authority=ResultAuthority.THEOREM,
                provider_ids=(provider.value, "official_kernel"),
                payload={
                    "accepted": True,
                    "receipt_id": receipt_id,
                    "environment_id": request.environment_id,
                    "theorem_digest": candidate.statement_digest,
                    "imports_digest": _digest_of(
                        {"imports": list(candidate.imports)}
                    ),
                    "axioms_digest": _digest_of(
                        {"axioms": list(candidate.axioms)}
                    ),
                    "hammer_is_proof_authority": False,
                },
                diagnostics=tuple(kernel_diagnostics),
            )
        )
        return self._assemble(
            request=request,
            theory=theory,
            theorem=theorem,
            phases=phases,
            candidate=candidate,
            candidate_id=candidate.candidate_id,
            reconstruction_id=reconstruction_id,
            admit_binding=admit_binding,
            escape_binding=escape_binding,
            official=KernelOfficialResultBindingV2(
                accepted=True,
                kernel_provider=provider,
                receipt_id=receipt_id,
                result_status=ResultStatus.PROVED,
                environment_id=request.environment_id,
                theorem_digest=candidate.statement_digest,
                phase=KernelPhase.OFFICIAL_KERNEL,
                authority=ResultAuthority.THEOREM,
                diagnostics=tuple(kernel_diagnostics),
            ),
            disposition=KernelDisposition.PROVED,
            result_authority=ResultAuthority.THEOREM,
            result_status=ResultStatus.PROVED,
            proof_established=True,
            diagnostics=diagnostics
            + [
                "official kernel accepted; theorem authority established",
                "hammer is not proof authority",
            ],
        )

    def _reject_non_authoritative(
        self,
        request: KernelExecutionRequestV2,
        *,
        disposition: KernelDisposition,
        reason: str,
    ) -> KernelExecutionResultV2:
        theory = request.theory  # type: ignore[assignment]
        assert isinstance(theory, TargetTheoryArtifact)
        theorem = request.selected_theorem()
        provider = request.provider  # type: ignore[assignment]
        assert isinstance(provider, KernelProviderKind)
        phases = tuple(
            KernelPhaseReceiptV2(
                phase=phase,
                status=KernelPhaseStatus.MOCK_REJECTED
                if disposition is KernelDisposition.MOCK_REJECTED
                else KernelPhaseStatus.SKIPPED,
                authority=ResultAuthority.CANDIDATE,
                diagnostics=(reason,),
            )
            for phase in (
                KernelPhase.PREMISE_SELECTION,
                KernelPhase.ATP_CANDIDATE,
                KernelPhase.RECONSTRUCTION,
                KernelPhase.TARGET_COMPILATION,
                KernelPhase.ELABORATION,
                KernelPhase.OFFICIAL_KERNEL,
            )
        )
        source = theorem["statement"]
        return self._assemble(
            request=request,
            theory=theory,
            theorem=theorem,
            phases=list(phases),
            candidate=None,
            candidate_id="",
            reconstruction_id="",
            admit_binding=KernelAdmitBindingV2.bind(source),
            escape_binding=KernelTrustEscapeBindingV2.bind(source),
            official=KernelOfficialResultBindingV2.unbound(
                kernel_provider=provider,
                environment_id=request.environment_id,
                theorem_digest=kernel_content_digest(source),
                reason=reason,
            ),
            disposition=disposition,
            result_authority=ResultAuthority.CANDIDATE,
            result_status=ResultStatus.CANDIDATE,
            proof_established=False,
            diagnostics=[reason],
        )

    def _finish_candidate(
        self,
        *,
        request: KernelExecutionRequestV2,
        theory: TargetTheoryArtifact,
        theorem: Mapping[str, Any],
        phases: list[KernelPhaseReceiptV2],
        candidate_id: str,
        diagnostics: list[str],
        disposition: KernelDisposition,
        candidate: KernelCompilationCandidate | None,
        reconstruction_id: str = "",
        source_override: str = "",
        reconstruction_authority: bool = False,
    ) -> KernelExecutionResultV2:
        provider = request.provider  # type: ignore[assignment]
        assert isinstance(provider, KernelProviderKind)
        # Ensure all six phases are present for auditability.
        present = {item.phase for item in phases}
        for phase in (
            KernelPhase.PREMISE_SELECTION,
            KernelPhase.ATP_CANDIDATE,
            KernelPhase.RECONSTRUCTION,
            KernelPhase.TARGET_COMPILATION,
            KernelPhase.ELABORATION,
            KernelPhase.OFFICIAL_KERNEL,
        ):
            if phase not in present:
                phases.append(
                    KernelPhaseReceiptV2(
                        phase=phase,
                        status=KernelPhaseStatus.SKIPPED,
                        authority=(
                            ResultAuthority.RECONSTRUCTION
                            if phase is KernelPhase.RECONSTRUCTION
                            else ResultAuthority.CANDIDATE
                        ),
                        diagnostics=("phase not executed in this mode",),
                    )
                )
        source = source_override or theorem["statement"]
        if candidate is not None:
            source = candidate.source
            statement_digest = candidate.statement_digest
            imports = candidate.imports
            axioms = candidate.axioms
        else:
            statement_digest = kernel_content_digest(theorem["statement"])
            imports = theory.imports
            axioms = theory.axioms
        return self._assemble(
            request=request,
            theory=theory,
            theorem=theorem,
            phases=phases,
            candidate=candidate,
            candidate_id=candidate_id,
            reconstruction_id=reconstruction_id,
            admit_binding=KernelAdmitBindingV2.bind(source),
            escape_binding=KernelTrustEscapeBindingV2.bind(source),
            official=KernelOfficialResultBindingV2.unbound(
                kernel_provider=provider,
                environment_id=request.environment_id,
                theorem_digest=statement_digest,
                reason="official kernel not establishing theorem authority",
            ),
            disposition=disposition,
            result_authority=(
                ResultAuthority.RECONSTRUCTION
                if reconstruction_authority
                else ResultAuthority.CANDIDATE
            ),
            result_status=(
                ResultStatus.RECONSTRUCTED
                if reconstruction_authority
                else ResultStatus.CANDIDATE
            ),
            proof_established=False,
            diagnostics=diagnostics,
            imports=imports,
            axioms=axioms,
            source_digest=candidate.source_digest if candidate else "",
        )

    def _assemble(
        self,
        *,
        request: KernelExecutionRequestV2,
        theory: TargetTheoryArtifact,
        theorem: Mapping[str, Any],
        phases: list[KernelPhaseReceiptV2],
        candidate: KernelCompilationCandidate | None,
        candidate_id: str,
        reconstruction_id: str,
        admit_binding: KernelAdmitBindingV2,
        escape_binding: KernelTrustEscapeBindingV2,
        official: KernelOfficialResultBindingV2,
        disposition: KernelDisposition,
        result_authority: ResultAuthority,
        result_status: ResultStatus,
        proof_established: bool,
        diagnostics: list[str],
        imports: Sequence[str] | None = None,
        axioms: Sequence[str] | None = None,
        source_digest: str = "",
    ) -> KernelExecutionResultV2:
        provider = request.provider  # type: ignore[assignment]
        assert isinstance(provider, KernelProviderKind)

        import_binding = KernelImportBindingV2.bind(
            imports if imports is not None else theory.imports
        )
        axiom_binding = KernelAxiomBindingV2.bind(
            axioms if axioms is not None else theory.axioms
        )
        env_binding = KernelEnvironmentBindingV2.bind(
            environment_id=request.environment_id,
            kernel_target=provider,
            toolchain_id=str(
                request.environment.get("toolchain_id") or provider.value
            ),
            toolchain_version=str(
                request.environment.get("toolchain_version")
                or "pinned-unspecified"
            ),
            environment=request.environment,
        )
        source_binding = KernelSourceTheoremBindingV2.bind(
            theorem_id=str(theorem["theorem_id"]),
            theorem_name=str(theorem["theorem_name"]),
            statement=str(theorem["statement"]),
            theory_id=theory.theory_id,
            source_digest=source_digest
            or (candidate.source_digest if candidate is not None else ""),
        )

        evidence = KernelProviderEvidenceV2(
            evidence_id=f"ev:kernel:{provider.value}:{request.request_id}",
            request_id=request.request_id,
            provider=provider,
            disposition=disposition,
            phases=tuple(phases),
            imports=import_binding,
            axioms=axiom_binding,
            admits=admit_binding,
            trust_escapes=escape_binding,
            environment=env_binding,
            source_theorem=source_binding,
            official_kernel=official,
            result_authority=result_authority,
            result_status=result_status,
            role=provider_role(provider),
            authority_ceiling=provider_authority_ceiling(provider),
            candidate_id=candidate_id,
            reconstruction_id=reconstruction_id,
            hammer_is_proof_authority=False,
            proof_established=proof_established,
            diagnostics=tuple(diagnostics),
            metadata={
                "lane_id": KERNEL_LANE_ID,
                "task_id": KERNEL_EXECUTION_V2_TASK_ID,
                "module_version": KERNEL_EXECUTION_V2_MODULE_VERSION,
            },
        )

        bounds = request.bounds or ExecutionBounds(timeout_ms=5_000, max_steps=1_000)
        result_id = f"result:kernel:{provider.value}:{request.request_id}"
        # TypedBackendResult requires unique diagnostics.
        unique_diagnostics = tuple(dict.fromkeys(diagnostics))

        if result_authority is ResultAuthority.THEOREM:
            typed: TypedBackendResult = TheoremResult(
                result_id=result_id,
                backend_id=provider.value,
                backend_version=KERNEL_EXECUTION_V2_MODULE_VERSION,
                authority=ResultAuthority.THEOREM,
                status=result_status,
                bounds=bounds,
                translation_ceiling=EvidenceAuthority.AUTHORITATIVE,
                usage=ResourceUsage(),
                diagnostics=unique_diagnostics,
                reason="official kernel accepted",
            )
        elif result_authority is ResultAuthority.RECONSTRUCTION:
            typed = ReconstructionResult(
                result_id=result_id,
                backend_id=provider.value,
                backend_version=KERNEL_EXECUTION_V2_MODULE_VERSION,
                authority=ResultAuthority.RECONSTRUCTION,
                status=result_status,
                bounds=bounds,
                translation_ceiling=EvidenceAuthority.NONE,
                usage=ResourceUsage(),
                diagnostics=unique_diagnostics,
                reason="reconstruction without official kernel acceptance",
            )
        else:
            candidate_status = (
                result_status
                if result_status
                in {
                    ResultStatus.CANDIDATE,
                    ResultStatus.UNKNOWN,
                    ResultStatus.UNAVAILABLE,
                    ResultStatus.UNSUPPORTED,
                    ResultStatus.ERROR,
                    ResultStatus.MALFORMED,
                }
                else ResultStatus.CANDIDATE
            )
            typed = CandidateResult(
                result_id=result_id,
                backend_id=provider.value,
                backend_version=KERNEL_EXECUTION_V2_MODULE_VERSION,
                authority=ResultAuthority.CANDIDATE,
                status=candidate_status,
                bounds=bounds,
                translation_ceiling=EvidenceAuthority.NONE,
                usage=ResourceUsage(),
                diagnostics=unique_diagnostics,
                reason="candidate until official kernel acceptance",
            )

        return KernelExecutionResultV2(
            request_id=request.request_id,
            disposition=disposition,
            evidence=evidence,
            typed_result=typed,
            candidate=candidate,
        )


# ---------------------------------------------------------------------------
# Convenience entry points
# ---------------------------------------------------------------------------


def execute_kernel(
    request: KernelExecutionRequestV2 | Mapping[str, Any],
    *,
    compiler: KernelTargetCompiler | None = None,
    kernel_checker: Callable[
        [KernelExecutionRequestV2, KernelCompilationCandidate],
        Mapping[str, Any],
    ]
    | None = None,
) -> KernelExecutionResultV2:
    """Execute the full separated-phase kernel pipeline."""

    return KernelExecutionEngineV2(
        compiler=compiler, kernel_checker=kernel_checker
    ).execute(request)


def execute_lean(
    theory: TargetTheoryArtifact | Mapping[str, Any],
    **kwargs: Any,
) -> KernelExecutionResultV2:
    return _execute_for_provider(KernelProviderKind.LEAN, theory, **kwargs)


def execute_rocq(
    theory: TargetTheoryArtifact | Mapping[str, Any],
    **kwargs: Any,
) -> KernelExecutionResultV2:
    return _execute_for_provider(KernelProviderKind.ROCQ, theory, **kwargs)


def execute_isabelle(
    theory: TargetTheoryArtifact | Mapping[str, Any],
    **kwargs: Any,
) -> KernelExecutionResultV2:
    return _execute_for_provider(KernelProviderKind.ISABELLE, theory, **kwargs)


def _execute_for_provider(
    provider: KernelProviderKind,
    theory: TargetTheoryArtifact | Mapping[str, Any],
    **kwargs: Any,
) -> KernelExecutionResultV2:
    request_id = str(kwargs.pop("request_id", f"req:kernel:{provider.value}"))
    request = KernelExecutionRequestV2(
        request_id=request_id,
        provider=provider,
        theory=theory,
        **kwargs,
    )
    return execute_kernel(request)


def build_minimal_theory(
    *,
    theory_id: str = "theory:demo",
    name: str = "Demo",
    theorem_id: str = "thm:goal",
    theorem_name: str = "goal",
    statement: str = "True",
    imports: Sequence[str] = (),
    axioms: Sequence[str] = (),
) -> TargetTheoryArtifact:
    """Compact recipe for integration tests (not a golden dump)."""

    return TargetTheoryArtifact(
        theory_id=theory_id,
        name=name,
        source_surface=SourceSurface.TARGET_THEORY,
        imports=tuple(imports),
        axioms=tuple(axioms),
        theorems=(
            {
                "theorem_id": theorem_id,
                "theorem_name": theorem_name,
                "statement": statement,
            },
        ),
    )


__all__ = [
    "KERNEL_PROVIDER_EVIDENCE_V2_INTERFACE",
    "KERNEL_EXECUTION_REQUEST_V2_INTERFACE",
    "KERNEL_EXECUTION_RESULT_V2_INTERFACE",
    "KERNEL_EXECUTION_V2_MODULE_VERSION",
    "KERNEL_EXECUTION_V2_TASK_ID",
    "KERNEL_EXECUTION_V2_GOAL_ID",
    "KERNEL_LANE_ID",
    "KernelAdmitBindingV2",
    "KernelAuthorityError",
    "KernelAxiomBindingV2",
    "KernelClaimKind",
    "KernelDisposition",
    "KernelEnvironmentBindingV2",
    "KernelExecutionEngineV2",
    "KernelExecutionError",
    "KernelExecutionMode",
    "KernelExecutionRequestV2",
    "KernelExecutionResultV2",
    "KernelImportBindingV2",
    "KernelOfficialResultBindingV2",
    "KernelPhase",
    "KernelPhaseReceiptV2",
    "KernelPhaseStatus",
    "KernelProviderEvidenceV2",
    "KernelProviderKind",
    "KernelSourceTheoremBindingV2",
    "KernelTrustEscapeBindingV2",
    "build_minimal_theory",
    "execute_isabelle",
    "execute_kernel",
    "execute_lean",
    "execute_rocq",
    "hammer_establishes_proof",
    "non_authoritative_signal_establishes",
    "normalize_kernel_provider",
    "provider_authority_ceiling",
    "provider_logic_identity",
    "provider_role",
    "provider_to_kernel_target",
]
