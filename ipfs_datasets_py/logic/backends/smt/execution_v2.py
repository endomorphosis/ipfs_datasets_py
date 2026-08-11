"""Execute and replay typed Z3 / cvc5 SMT/CHC evidence (LFP2-028).

Interface: ``SMTProviderEvidence@2``

Runs typed obligations through pinned Z3 and/or cvc5 solvers with:

* models, unsat cores, and (where supported) proof artifacts bound on receipts;
* differential comparison of matched fragments across solvers;
* hermetic fixture runners and live pinned-tool tiers;
* explicit typed outcomes for solver disagreement and unsupported
  theory / proof features; and
* a hard fail-closed rule that **success is never promoted beyond the
  evidence receipt** — mock, fallback, availability, confidence, and fluent
  text never establish satisfiability, theorem, or proof authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.cvc5.compiler import (
    CVC5SoftwareVerificationBackend,
)
from ipfs_datasets_py.logic.backends.results import (
    ResultAuthority,
    ResultStatus,
    TypedBackendResult,
)
from ipfs_datasets_py.logic.backends.smt.compiler import (
    SmtCompilation,
    SmtFeature,
    SmtObligation,
    SmtQueryMode,
    SoftwareVerificationSMTCompiler,
    UnsupportedSmtFeatureError,
)
from ipfs_datasets_py.logic.backends.smt.differential import (
    CVC5_SV_BACKEND_ID,
    DifferentialClassification,
    SmtDifferentialReport,
    SmtDifferentialVerifier,
    SmtRawSolverOutput,
    SmtSolverRunner,
    SmtSolverVerdict,
    SoftwareVerificationSmtBackend,
    SoftwareVerificationSmtOutcome,
    Z3_SV_BACKEND_ID,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.backends.z3.compiler import (
    Z3SoftwareVerificationBackend,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SyntaxContractError,
    _freeze_mapping,
    _record_id,
    _require_mapping,
    _require_sequence,
    _sha256_hex,
    _text,
    _thaw_mapping,
    canonical_json_bytes,
    content_sha256,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

SMT_PROVIDER_EVIDENCE_V2_INTERFACE: Final = "SMTProviderEvidence@2"
SMT_EXECUTION_REQUEST_V2_INTERFACE: Final = "SmtExecutionRequest@2"
SMT_EXECUTION_RESULT_V2_INTERFACE: Final = "SmtExecutionResult@2"
SMT_ARTIFACT_BINDING_V2_INTERFACE: Final = "SmtArtifactBinding@2"
SMT_REPLAY_RECEIPT_V2_INTERFACE: Final = "SmtReplayReceipt@2"
SMT_DIFFERENTIAL_BINDING_V2_INTERFACE: Final = "SmtDifferentialBinding@2"

SMT_PROVIDER_EVIDENCE_SCHEMA: Final = "smt-provider-evidence/v2"
SMT_EXECUTION_REQUEST_SCHEMA: Final = "smt-execution-request/v2"
SMT_EXECUTION_RESULT_SCHEMA: Final = "smt-execution-result/v2"
SMT_ARTIFACT_BINDING_SCHEMA: Final = "smt-artifact-binding/v2"
SMT_REPLAY_RECEIPT_SCHEMA: Final = "smt-replay-receipt/v2"
SMT_DIFFERENTIAL_BINDING_SCHEMA: Final = "smt-differential-binding/v2"

SMT_EXECUTION_V2_MODULE_VERSION: Final = "1.0.0"
SMT_EXECUTION_V2_TASK_ID: Final = "LFP2-028"
SMT_EXECUTION_V2_GOAL_ID: Final = "LFP2-G060"

SMT_LANE_ID: Final = "smt"
SMT_EVIDENCE_KIND: Final = "smt"

_MAX_DIAGNOSTICS: Final = 64
_MAX_METADATA_BYTES: Final = 8_192
_MAX_SOURCE_REFS: Final = 64
_MAX_MODEL_CHARS: Final = 65_536
_MAX_PROOF_CHARS: Final = 65_536
_MAX_CORE_ATOMS: Final = 1_024

_FORBIDDEN_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "arbitrary_payload",
        "claimed_execution",
        "claimed_proof",
        "claimed_replay",
        "claimed_satisfiability",
        "claimed_theorem",
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

# Features that execution treats as hard unsupported theories/features.
_UNSUPPORTED_THEORY_FEATURES: Final[frozenset[SmtFeature]] = frozenset(
    {
        SmtFeature.TEMPORAL,
        SmtFeature.SEPARATION_WAND,
        SmtFeature.UNBOUNDED_CONCURRENCY,
        SmtFeature.UNBOUNDED_REFINEMENT,
    }
)

# Proof production is not a first-class validated SMT-LIB evidence path on v2.
_UNSUPPORTED_PROOF_FEATURE_TOKEN: Final = "smt_proof_production"


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class SmtExecutionError(SyntaxContractError):
    """Raised when SMT execution v2 inputs are malformed."""


class SmtAuthorityError(SmtExecutionError):
    """Raised when a claim would exceed the SMT evidence receipt ceiling."""


class SmtProviderKind(StrEnum):
    """Closed set of SMT/CHC providers."""

    Z3 = "z3"
    CVC5 = "cvc5"
    DIFFERENTIAL = "differential"


class SmtExecutionMode(StrEnum):
    """How the SMT outcome was produced.

    Only ``pinned_solver`` and ``hermetic_fixture`` may establish
    satisfiability / theorem-by-negation authority.  Mock and fallback never do.
    """

    PINNED_SOLVER = "pinned_solver"
    HERMETIC_FIXTURE = "hermetic_fixture"
    FALLBACK = "fallback"
    MOCK = "mock"


class SmtDisposition(StrEnum):
    """Closed set of SMT execution dispositions (typed outcomes)."""

    SATISFIABLE = "satisfiable"
    UNSATISFIABLE = "unsatisfiable"
    PROVED = "proved"
    DISPROVED = "disproved"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    UNSUPPORTED_THEORY = "unsupported_theory"
    UNSUPPORTED_PROOF_FEATURE = "unsupported_proof_feature"
    SOLVER_DISAGREEMENT = "solver_disagreement"
    MALFORMED = "malformed"
    ERROR = "error"
    MOCK_REJECTED = "mock_rejected"
    FALLBACK_REJECTED = "fallback_rejected"
    REPLAY_MISMATCH = "replay_mismatch"
    PARTIAL_UNAVAILABLE = "partial_unavailable"


class SmtArtifactKind(StrEnum):
    """Evidence artifacts that may bind to a solver outcome."""

    NONE = "none"
    MODEL = "model"
    UNSAT_CORE = "unsat_core"
    PROOF = "proof"


class SmtClaimKind(StrEnum):
    """Claims that mock / fallback / availability must never establish alone."""

    SATISFIABILITY = "satisfiability"
    THEOREM = "theorem"
    PROOF = "proof"
    MODEL = "model"
    UNSAT_CORE = "unsat_core"


_PROVIDER_ALIASES: Final[dict[str, SmtProviderKind]] = {
    "z3": SmtProviderKind.Z3,
    "z3py": SmtProviderKind.Z3,
    "microsoft_z3": SmtProviderKind.Z3,
    "microsoft-z3": SmtProviderKind.Z3,
    "cvc5": SmtProviderKind.CVC5,
    "cvc4": SmtProviderKind.CVC5,
    "differential": SmtProviderKind.DIFFERENTIAL,
    "z3_cvc5": SmtProviderKind.DIFFERENTIAL,
    "z3-cvc5": SmtProviderKind.DIFFERENTIAL,
    "z3_cvc5_differential": SmtProviderKind.DIFFERENTIAL,
    "portfolio": SmtProviderKind.DIFFERENTIAL,
}


def normalize_smt_provider(value: SmtProviderKind | str) -> SmtProviderKind:
    """Normalize provider labels into the closed SMT provider set."""

    if isinstance(value, SmtProviderKind):
        return value
    key = str(value).strip().lower().replace("-", "_").replace(".", "_")
    if key not in _PROVIDER_ALIASES:
        alt = str(value).strip().lower()
        if alt in _PROVIDER_ALIASES:
            return _PROVIDER_ALIASES[alt]
        raise SmtExecutionError(
            f"unsupported SMT provider: {value!r}; expected z3, cvc5, or differential"
        )
    return _PROVIDER_ALIASES[key]


def provider_backend_id(provider: SmtProviderKind) -> str:
    if provider is SmtProviderKind.Z3:
        return Z3_SV_BACKEND_ID
    if provider is SmtProviderKind.CVC5:
        return CVC5_SV_BACKEND_ID
    return "z3_cvc5"


def non_authoritative_signal_establishes(
    claim: SmtClaimKind | str,
    *,
    mock_output: object = None,
    fallback_output: object = None,
    available: bool | None = None,
    confidence: float | None = None,
    fluent_text: str | None = None,
) -> bool:
    """Always ``False``: non-solver signals never establish SMT claims."""

    del claim, mock_output, fallback_output, available, confidence, fluent_text
    return False


def mock_or_fallback_establishes_satisfiability(
    *,
    mock_output: object = None,
    fallback_output: object = None,
    available: bool | None = None,
) -> bool:
    """Explicit acceptance helper: mock/fallback never establish SAT authority."""

    return non_authoritative_signal_establishes(
        SmtClaimKind.SATISFIABILITY,
        mock_output=mock_output,
        fallback_output=fallback_output,
        available=available,
    )


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
        raise SmtExecutionError(
            f"{field_name} must be one of: {allowed}; got {value!r}"
        ) from error


def _optional_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise SmtExecutionError(f"{field_name} must be a boolean")


def _unit_interval(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SmtExecutionError(f"{field_name} must be numeric")
    conf = float(value)
    if conf != conf or conf < 0.0 or conf > 1.0:
        raise SmtExecutionError(f"{field_name} must be finite in [0, 1]")
    return conf


def _digest_of(payload: Mapping[str, Any]) -> str:
    return content_sha256(canonical_json_bytes(dict(payload)))


def _source_ref_ids(
    value: object, field_name: str = "source_ref_ids"
) -> tuple[str, ...]:
    items = _require_sequence(value, field_name)
    if len(items) > _MAX_SOURCE_REFS:
        raise SmtExecutionError(
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


def _forbid_authority_metadata(metadata: Mapping[str, Any], field_name: str) -> None:
    for key in metadata:
        if key in _FORBIDDEN_METADATA_KEYS or key in _NON_AUTHORITATIVE_SIGNAL_KEYS:
            raise SmtAuthorityError(
                f"{field_name} rejects free-form authority/signal key {key!r}; "
                "use typed SMTProviderEvidence@2 fields only"
            )


def _bound_diagnostics(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    items = _require_sequence(value, "diagnostics")
    out: list[str] = []
    for index, item in enumerate(items[:_MAX_DIAGNOSTICS]):
        out.append(_text(item, f"diagnostics[{index}]", maximum=512))
    return tuple(out)


def _coerce_obligation(
    value: object,
) -> SmtObligation | Mapping[str, Any] | SmtCompilation:
    if isinstance(value, (SmtObligation, SmtCompilation)):
        return value
    return _require_mapping(value, "obligation")


def _obligation_digest(
    obligation: SmtObligation | Mapping[str, Any] | SmtCompilation,
) -> str:
    if isinstance(obligation, SmtCompilation):
        return _digest_of(
            {
                "compilation_id": obligation.compilation_id,
                "obligation_id": obligation.obligation_id,
                "script_digest": obligation.script.digest,
            }
        )
    if isinstance(obligation, SmtObligation):
        return _digest_of(obligation.to_dict())
    return _digest_of(dict(obligation))


def _default_bounds() -> ExecutionBounds:
    return ExecutionBounds(
        timeout_ms=5_000,
        max_steps=100_000,
        max_memory_bytes=64 * 1024 * 1024,
        max_output_bytes=65_536,
    )


def _coerce_bounds(value: object | None) -> ExecutionBounds:
    if value is None:
        return _default_bounds()
    if isinstance(value, ExecutionBounds):
        return value
    mapping = _require_mapping(value, "bounds")
    return ExecutionBounds(
        timeout_ms=int(mapping.get("timeout_ms", 5_000)),
        max_steps=int(mapping.get("max_steps", 100_000)),
        max_memory_bytes=int(mapping.get("max_memory_bytes", 64 * 1024 * 1024)),
        max_output_bytes=int(mapping.get("max_output_bytes", 65_536)),
    )


def _query_mode_of(
    obligation: SmtObligation | Mapping[str, Any] | SmtCompilation,
) -> SmtQueryMode:
    if isinstance(obligation, SmtCompilation):
        return obligation.query_mode
    if isinstance(obligation, SmtObligation):
        return obligation.query_mode  # type: ignore[return-value]
    mode = obligation.get("query_mode", SmtQueryMode.SATISFIABILITY)
    if isinstance(mode, SmtQueryMode):
        return mode
    return SmtQueryMode(str(mode))


def _features_of(
    obligation: SmtObligation | Mapping[str, Any] | SmtCompilation,
) -> tuple[SmtFeature, ...]:
    if isinstance(obligation, SmtCompilation):
        return obligation.features
    if isinstance(obligation, SmtObligation):
        return obligation.features  # type: ignore[return-value]
    raw = obligation.get("features", ())
    out: list[SmtFeature] = []
    for item in raw if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else ():
        try:
            out.append(item if isinstance(item, SmtFeature) else SmtFeature(str(item)))
        except (TypeError, ValueError):
            continue
    return tuple(out)


def _request_proof_of(
    obligation: SmtObligation | Mapping[str, Any] | SmtCompilation,
) -> bool:
    if isinstance(obligation, Mapping):
        value = obligation.get("request_proof", False)
        return value is True
    attributes = getattr(obligation, "attributes", None)
    if attributes is None:
        return False
    if isinstance(attributes, FrozenMap):
        return attributes.to_dict().get("request_proof") is True
    if isinstance(attributes, Mapping):
        return attributes.get("request_proof") is True
    return False


def _verdict_to_disposition(
    *,
    query_mode: SmtQueryMode,
    verdict: SmtSolverVerdict,
) -> SmtDisposition:
    if verdict is SmtSolverVerdict.TIMEOUT:
        return SmtDisposition.TIMEOUT
    if verdict is SmtSolverVerdict.UNAVAILABLE:
        return SmtDisposition.UNAVAILABLE
    if verdict is SmtSolverVerdict.MALFORMED:
        return SmtDisposition.MALFORMED
    if verdict is SmtSolverVerdict.ERROR:
        return SmtDisposition.ERROR
    if verdict is SmtSolverVerdict.UNSUPPORTED:
        return SmtDisposition.UNSUPPORTED
    if verdict is SmtSolverVerdict.UNKNOWN:
        return SmtDisposition.UNKNOWN
    if query_mode is SmtQueryMode.THEOREM_BY_NEGATION:
        if verdict is SmtSolverVerdict.UNSAT:
            return SmtDisposition.PROVED
        if verdict is SmtSolverVerdict.SAT:
            return SmtDisposition.DISPROVED
        return SmtDisposition.UNKNOWN
    if verdict is SmtSolverVerdict.SAT:
        return SmtDisposition.SATISFIABLE
    if verdict is SmtSolverVerdict.UNSAT:
        return SmtDisposition.UNSATISFIABLE
    return SmtDisposition.UNKNOWN


def _differential_to_disposition(
    classification: DifferentialClassification,
    *,
    query_mode: SmtQueryMode,
    left: SoftwareVerificationSmtOutcome,
) -> SmtDisposition:
    if classification is DifferentialClassification.DISAGREE:
        return SmtDisposition.SOLVER_DISAGREEMENT
    if classification is DifferentialClassification.PARTIAL_UNAVAILABLE:
        return SmtDisposition.PARTIAL_UNAVAILABLE
    if classification is DifferentialClassification.BOTH_UNAVAILABLE:
        return SmtDisposition.UNAVAILABLE
    if classification is DifferentialClassification.MALFORMED:
        return SmtDisposition.MALFORMED
    if classification is DifferentialClassification.ERROR:
        return SmtDisposition.ERROR
    if classification is DifferentialClassification.AGREE_PROVED:
        return SmtDisposition.PROVED
    if classification is DifferentialClassification.AGREE_DISPROVED:
        return SmtDisposition.DISPROVED
    if classification is DifferentialClassification.AGREE_SATISFIABLE:
        return SmtDisposition.SATISFIABLE
    if classification is DifferentialClassification.AGREE_UNSATISFIABLE:
        return SmtDisposition.UNSATISFIABLE
    if classification is DifferentialClassification.AGREE_UNKNOWN:
        return _verdict_to_disposition(query_mode=query_mode, verdict=left.verdict)
    return SmtDisposition.UNKNOWN


def _disposition_to_result_status(disposition: SmtDisposition) -> ResultStatus:
    mapping = {
        SmtDisposition.SATISFIABLE: ResultStatus.SATISFIABLE,
        SmtDisposition.UNSATISFIABLE: ResultStatus.UNSATISFIABLE,
        SmtDisposition.PROVED: ResultStatus.PROVED,
        SmtDisposition.DISPROVED: ResultStatus.DISPROVED,
        SmtDisposition.UNKNOWN: ResultStatus.UNKNOWN,
        SmtDisposition.TIMEOUT: ResultStatus.TIMEOUT,
        SmtDisposition.UNAVAILABLE: ResultStatus.UNAVAILABLE,
        SmtDisposition.UNSUPPORTED: ResultStatus.UNSUPPORTED,
        SmtDisposition.UNSUPPORTED_THEORY: ResultStatus.UNSUPPORTED,
        SmtDisposition.UNSUPPORTED_PROOF_FEATURE: ResultStatus.UNSUPPORTED,
        SmtDisposition.SOLVER_DISAGREEMENT: ResultStatus.UNKNOWN,
        SmtDisposition.MALFORMED: ResultStatus.MALFORMED,
        SmtDisposition.ERROR: ResultStatus.ERROR,
        SmtDisposition.MOCK_REJECTED: ResultStatus.UNKNOWN,
        SmtDisposition.FALLBACK_REJECTED: ResultStatus.UNKNOWN,
        SmtDisposition.REPLAY_MISMATCH: ResultStatus.ERROR,
        SmtDisposition.PARTIAL_UNAVAILABLE: ResultStatus.UNAVAILABLE,
    }
    return mapping[disposition]


def _authority_for_disposition(
    disposition: SmtDisposition,
    *,
    query_mode: SmtQueryMode,
) -> ResultAuthority:
    if disposition in {SmtDisposition.PROVED, SmtDisposition.DISPROVED}:
        return ResultAuthority.THEOREM
    if disposition in {
        SmtDisposition.SATISFIABLE,
        SmtDisposition.UNSATISFIABLE,
    }:
        return ResultAuthority.SATISFIABILITY
    if query_mode is SmtQueryMode.THEOREM_BY_NEGATION:
        return ResultAuthority.THEOREM
    return ResultAuthority.SATISFIABILITY


def _conclusive_dispositions() -> frozenset[SmtDisposition]:
    return frozenset(
        {
            SmtDisposition.SATISFIABLE,
            SmtDisposition.UNSATISFIABLE,
            SmtDisposition.PROVED,
            SmtDisposition.DISPROVED,
        }
    )


def _is_authoritative_mode(mode: SmtExecutionMode) -> bool:
    return mode in {
        SmtExecutionMode.PINNED_SOLVER,
        SmtExecutionMode.HERMETIC_FIXTURE,
    }


# ---------------------------------------------------------------------------
# Artifact / differential / replay bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SmtArtifactBindingV2:
    """Model / unsat-core / proof artifact bound to a solver outcome.

    Interface: ``SmtArtifactBinding@2``.
    """

    kind: SmtArtifactKind | str = SmtArtifactKind.NONE
    present: bool = False
    digest: str = ""
    atoms: tuple[str, ...] | Sequence[str] = ()
    text_excerpt: str = ""
    supported: bool = True
    schema_version: str = SMT_ARTIFACT_BINDING_SCHEMA

    interface: ClassVar[str] = SMT_ARTIFACT_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _enum(self.kind, SmtArtifactKind, "kind")
        )
        present = _optional_bool(self.present, "present")
        supported = _optional_bool(self.supported, "supported")
        object.__setattr__(self, "present", present)
        object.__setattr__(self, "supported", supported)
        if self.digest:
            object.__setattr__(
                self, "digest", _sha256_hex(self.digest, "digest")
            )
        else:
            object.__setattr__(self, "digest", "")
        atoms = tuple(
            _text(item, f"atoms[{index}]", maximum=256)
            for index, item in enumerate(
                _require_sequence(self.atoms, "atoms")[:_MAX_CORE_ATOMS]
            )
        )
        object.__setattr__(self, "atoms", atoms)
        if self.text_excerpt:
            object.__setattr__(
                self,
                "text_excerpt",
                _text(self.text_excerpt, "text_excerpt", maximum=_MAX_MODEL_CHARS),
            )
        else:
            object.__setattr__(self, "text_excerpt", "")
        if present and self.kind is SmtArtifactKind.NONE:
            raise SmtExecutionError("present artifact cannot have kind=none")
        if present and not supported:
            raise SmtAuthorityError(
                "unsupported artifacts cannot be marked present on the receipt"
            )
        if self.schema_version != SMT_ARTIFACT_BINDING_SCHEMA:
            raise SmtExecutionError(
                f"unsupported artifact schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "atoms": list(self.atoms),
            "digest": self.digest,
            "interface": self.interface,
            "kind": (
                self.kind.value
                if isinstance(self.kind, SmtArtifactKind)
                else self.kind
            ),
            "present": self.present,
            "schema_version": self.schema_version,
            "supported": self.supported,
            "text_excerpt": self.text_excerpt,
        }

    @classmethod
    def empty(cls) -> SmtArtifactBindingV2:
        return cls()

    @classmethod
    def from_model(cls, model_text: str) -> SmtArtifactBindingV2:
        text = model_text[:_MAX_MODEL_CHARS] if model_text else ""
        if not text:
            return cls(kind=SmtArtifactKind.MODEL, present=False, supported=True)
        return cls(
            kind=SmtArtifactKind.MODEL,
            present=True,
            digest=_digest_of({"model": text}),
            text_excerpt=text,
            supported=True,
        )

    @classmethod
    def from_unsat_core(cls, core: Sequence[str]) -> SmtArtifactBindingV2:
        atoms = tuple(str(item) for item in core[:_MAX_CORE_ATOMS])
        if not atoms:
            return cls(kind=SmtArtifactKind.UNSAT_CORE, present=False, supported=True)
        return cls(
            kind=SmtArtifactKind.UNSAT_CORE,
            present=True,
            digest=_digest_of({"unsat_core": list(atoms)}),
            atoms=atoms,
            supported=True,
        )

    @classmethod
    def unsupported_proof(cls) -> SmtArtifactBindingV2:
        return cls(
            kind=SmtArtifactKind.PROOF,
            present=False,
            supported=False,
            text_excerpt="",
        )


@dataclass(frozen=True, slots=True)
class SmtDifferentialBindingV2:
    """Differential Z3/cvc5 comparison bound into SMT evidence.

    Interface: ``SmtDifferentialBinding@2``.
    """

    classification: DifferentialClassification | str
    agreement: bool
    classification_reason: str = ""
    left_backend_id: str = ""
    right_backend_id: str = ""
    left_verdict: str = ""
    right_verdict: str = ""
    script_digest: str = ""
    disagreement_preserved: bool = False
    schema_version: str = SMT_DIFFERENTIAL_BINDING_SCHEMA

    interface: ClassVar[str] = SMT_DIFFERENTIAL_BINDING_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "classification",
            _enum(self.classification, DifferentialClassification, "classification"),
        )
        object.__setattr__(
            self, "agreement", _optional_bool(self.agreement, "agreement")
        )
        if self.classification_reason:
            object.__setattr__(
                self,
                "classification_reason",
                _text(
                    self.classification_reason,
                    "classification_reason",
                    maximum=512,
                ),
            )
        else:
            object.__setattr__(self, "classification_reason", "")
        for name in (
            "left_backend_id",
            "right_backend_id",
            "left_verdict",
            "right_verdict",
        ):
            value = getattr(self, name)
            if value:
                object.__setattr__(
                    self, name, _text(value, name, maximum=128)
                )
            else:
                object.__setattr__(self, name, "")
        if self.script_digest:
            object.__setattr__(
                self,
                "script_digest",
                _sha256_hex(self.script_digest, "script_digest"),
            )
        object.__setattr__(
            self,
            "disagreement_preserved",
            _optional_bool(self.disagreement_preserved, "disagreement_preserved"),
        )
        if self.schema_version != SMT_DIFFERENTIAL_BINDING_SCHEMA:
            raise SmtExecutionError(
                f"unsupported differential binding schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agreement": self.agreement,
            "classification": (
                self.classification.value
                if isinstance(self.classification, DifferentialClassification)
                else self.classification
            ),
            "classification_reason": self.classification_reason,
            "disagreement_preserved": self.disagreement_preserved,
            "interface": self.interface,
            "left_backend_id": self.left_backend_id,
            "left_verdict": self.left_verdict,
            "right_backend_id": self.right_backend_id,
            "right_verdict": self.right_verdict,
            "schema_version": self.schema_version,
            "script_digest": self.script_digest,
        }

    @classmethod
    def from_report(cls, report: SmtDifferentialReport) -> SmtDifferentialBindingV2:
        disagreement = report.disagreement_evidence.to_dict()
        return cls(
            classification=report.classification,
            agreement=report.agreement,
            classification_reason=report.classification_reason,
            left_backend_id=report.left.backend_id,
            right_backend_id=report.right.backend_id,
            left_verdict=report.left.verdict.value,
            right_verdict=report.right.verdict.value,
            script_digest=report.script_digest,
            disagreement_preserved=bool(disagreement.get("preserved")),
        )


@dataclass(frozen=True, slots=True)
class SmtReplayReceiptV2:
    """Replay disposition for one SMT execution evidence receipt.

    Interface: ``SmtReplayReceipt@2``.

    ``replay_claimed`` requires matched obligation/script digests and
    matched dispositions/verdicts.  Success is never claimed beyond this
    receipt.
    """

    replay_id: str
    request_id: str
    obligation_digest: str
    script_digest: str
    original_disposition: SmtDisposition | str
    replayed_disposition: SmtDisposition | str
    original_verdict: str = ""
    replayed_verdict: str = ""
    matched: bool = False
    replay_claimed: bool = False
    diagnostics: tuple[str, ...] = ()
    schema_version: str = SMT_REPLAY_RECEIPT_SCHEMA

    interface: ClassVar[str] = SMT_REPLAY_RECEIPT_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "replay_id", _record_id(self.replay_id, "replay_id")
        )
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self,
            "obligation_digest",
            _sha256_hex(self.obligation_digest, "obligation_digest"),
        )
        if self.script_digest:
            object.__setattr__(
                self,
                "script_digest",
                _sha256_hex(self.script_digest, "script_digest"),
            )
        else:
            object.__setattr__(self, "script_digest", "")
        object.__setattr__(
            self,
            "original_disposition",
            _enum(self.original_disposition, SmtDisposition, "original_disposition"),
        )
        object.__setattr__(
            self,
            "replayed_disposition",
            _enum(self.replayed_disposition, SmtDisposition, "replayed_disposition"),
        )
        for name in ("original_verdict", "replayed_verdict"):
            value = getattr(self, name)
            if value:
                object.__setattr__(self, name, _text(value, name, maximum=64))
            else:
                object.__setattr__(self, name, "")
        matched = _optional_bool(self.matched, "matched")
        replay_claimed = _optional_bool(self.replay_claimed, "replay_claimed")
        if replay_claimed and not matched:
            raise SmtAuthorityError(
                "replay_claimed requires matched disposition/verdict/digests"
            )
        object.__setattr__(self, "matched", matched)
        object.__setattr__(self, "replay_claimed", replay_claimed)
        object.__setattr__(self, "diagnostics", _bound_diagnostics(self.diagnostics))
        if self.schema_version != SMT_REPLAY_RECEIPT_SCHEMA:
            raise SmtExecutionError(
                f"unsupported replay receipt schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": list(self.diagnostics),
            "interface": self.interface,
            "matched": self.matched,
            "obligation_digest": self.obligation_digest,
            "original_disposition": (
                self.original_disposition.value
                if isinstance(self.original_disposition, SmtDisposition)
                else self.original_disposition
            ),
            "original_verdict": self.original_verdict,
            "replay_claimed": self.replay_claimed,
            "replay_id": self.replay_id,
            "replayed_disposition": (
                self.replayed_disposition.value
                if isinstance(self.replayed_disposition, SmtDisposition)
                else self.replayed_disposition
            ),
            "replayed_verdict": self.replayed_verdict,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "script_digest": self.script_digest,
        }


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SmtExecutionRequestV2:
    """Typed SMT/CHC execution request.

    Interface: ``SmtExecutionRequest@2``.
    """

    request_id: str
    obligation: SmtObligation | Mapping[str, Any] | SmtCompilation
    provider: SmtProviderKind | str = SmtProviderKind.DIFFERENTIAL
    mode: SmtExecutionMode | str = SmtExecutionMode.HERMETIC_FIXTURE
    bounds: ExecutionBounds | Mapping[str, Any] | None = None
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    request_proof: bool = False
    mock_output: Mapping[str, Any] | None = None
    fallback_output: Mapping[str, Any] | None = None
    available: bool = True
    confidence: float = 0.0
    fluent_text: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SMT_EXECUTION_REQUEST_SCHEMA

    interface: ClassVar[str] = SMT_EXECUTION_REQUEST_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "provider", normalize_smt_provider(self.provider)
        )
        object.__setattr__(self, "obligation", _coerce_obligation(self.obligation))
        object.__setattr__(
            self, "mode", _enum(self.mode, SmtExecutionMode, "mode")
        )
        object.__setattr__(self, "bounds", _coerce_bounds(self.bounds))
        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids)
        )
        object.__setattr__(
            self, "request_proof", _optional_bool(self.request_proof, "request_proof")
        )
        if self.mock_output is not None:
            object.__setattr__(
                self,
                "mock_output",
                dict(_require_mapping(self.mock_output, "mock_output")),
            )
        if self.fallback_output is not None:
            object.__setattr__(
                self,
                "fallback_output",
                dict(_require_mapping(self.fallback_output, "fallback_output")),
            )
        object.__setattr__(
            self, "available", _optional_bool(self.available, "available")
        )
        object.__setattr__(
            self, "confidence", _unit_interval(self.confidence, "confidence")
        )
        if self.fluent_text:
            object.__setattr__(
                self,
                "fluent_text",
                _text(self.fluent_text, "fluent_text", maximum=4096),
            )
        else:
            object.__setattr__(self, "fluent_text", "")
        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_authority_metadata(metadata, "metadata")
        serialized = canonical_json_bytes(_thaw_mapping(metadata))
        if len(serialized) > _MAX_METADATA_BYTES:
            raise SmtExecutionError(
                f"metadata exceeds hard limit {_MAX_METADATA_BYTES} bytes"
            )
        object.__setattr__(self, "metadata", metadata)
        if self.schema_version != SMT_EXECUTION_REQUEST_SCHEMA:
            raise SmtExecutionError(
                f"unsupported request schema: {self.schema_version!r}"
            )

    @property
    def has_mock_output(self) -> bool:
        return self.mock_output is not None

    @property
    def has_fallback_output(self) -> bool:
        return self.fallback_output is not None

    @property
    def obligation_digest(self) -> str:
        return _obligation_digest(self.obligation)

    @property
    def query_mode(self) -> SmtQueryMode:
        return _query_mode_of(self.obligation)

    def to_dict(self) -> dict[str, Any]:
        obligation = self.obligation
        if isinstance(obligation, SmtCompilation):
            obligation_payload: dict[str, Any] = {
                "compilation_id": obligation.compilation_id,
                "obligation_id": obligation.obligation_id,
                "query_mode": obligation.query_mode.value,
                "script_digest": obligation.script.digest,
            }
        elif isinstance(obligation, SmtObligation):
            obligation_payload = obligation.to_dict()
        else:
            obligation_payload = dict(obligation)
        bounds = self.bounds  # type: ignore[assignment]
        return {
            "available": self.available,
            "bounds": {
                "max_memory_bytes": bounds.max_memory_bytes,
                "max_output_bytes": bounds.max_output_bytes,
                "max_steps": bounds.max_steps,
                "timeout_ms": bounds.timeout_ms,
            },
            "confidence": self.confidence,
            "fallback_output": (
                None if self.fallback_output is None else dict(self.fallback_output)
            ),
            "fluent_text": self.fluent_text,
            "has_fallback_output": self.has_fallback_output,
            "has_mock_output": self.has_mock_output,
            "interface": self.interface,
            "metadata": _thaw_mapping(self.metadata),
            "mock_output": (
                None if self.mock_output is None else dict(self.mock_output)
            ),
            "mode": (
                self.mode.value
                if isinstance(self.mode, SmtExecutionMode)
                else self.mode
            ),
            "obligation": obligation_payload,
            "provider": (
                self.provider.value
                if isinstance(self.provider, SmtProviderKind)
                else self.provider
            ),
            "request_id": self.request_id,
            "request_proof": self.request_proof,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SmtExecutionRequestV2:
        payload = _require_mapping(value, "SmtExecutionRequestV2")
        allowed = {
            "request_id",
            "obligation",
            "provider",
            "mode",
            "bounds",
            "source_ref_ids",
            "request_proof",
            "mock_output",
            "fallback_output",
            "available",
            "confidence",
            "fluent_text",
            "metadata",
            "schema_version",
            "interface",
        }
        return cls(
            **{
                key: payload[key]
                for key in allowed
                if key in payload and key != "interface"
            }
        )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SmtProviderEvidenceV2:
    """Pinned Z3 / cvc5 SMT/CHC execution evidence.

    Interface: ``SMTProviderEvidence@2``.

    Satisfiability and theorem-by-negation authority are established only by
    pinned / hermetic solver execution reflected in this receipt.  Mock,
    fallback, availability, confidence, and fluent text never establish
    satisfiability, theorem, or proof.  Solver disagreement and unsupported
    theory / proof features are first-class dispositions — never silent
    success.  Success is never promoted beyond the fields of this receipt.
    """

    evidence_id: str
    request_id: str
    request_digest: str
    provider: SmtProviderKind | str
    disposition: SmtDisposition | str
    mode: SmtExecutionMode | str
    query_mode: SmtQueryMode | str
    obligation_digest: str
    obligation_id: str = ""
    script_digest: str = ""
    compilation_id: str = ""
    translation_receipt_id: str = ""
    solver_backend_id: str = ""
    solver_version: str = ""
    solver_verdict: str = ""
    model: SmtArtifactBindingV2 | Mapping[str, Any] | None = None
    unsat_core: SmtArtifactBindingV2 | Mapping[str, Any] | None = None
    proof: SmtArtifactBindingV2 | Mapping[str, Any] | None = None
    differential: SmtDifferentialBindingV2 | Mapping[str, Any] | None = None
    replay: SmtReplayReceiptV2 | Mapping[str, Any] | None = None
    source_ref_ids: tuple[str, ...] | Sequence[str] = ()
    result_authority: ResultAuthority | str = ResultAuthority.SATISFIABILITY
    result_status: ResultStatus | str = ResultStatus.UNKNOWN
    role: ToolRole | str = ToolRole.AUTHORITY
    authority_ceiling: ToolchainAuthorityCeiling | str = (
        ToolchainAuthorityCeiling.SATISFIABILITY
    )
    translation_ceiling: EvidenceAuthority | str = EvidenceAuthority.BOUNDED
    satisfiability_established: bool = False
    theorem_established: bool = False
    proof_established: bool = False
    mock_output_present: bool = False
    fallback_output_present: bool = False
    available: bool = False
    confidence: float = 0.0
    fluent_text_present: bool = False
    bounds_exhausted: bool = False
    diagnostics: tuple[str, ...] = ()
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SMT_PROVIDER_EVIDENCE_SCHEMA

    interface: ClassVar[str] = SMT_PROVIDER_EVIDENCE_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _record_id(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self,
            "request_digest",
            _sha256_hex(self.request_digest, "request_digest"),
        )
        object.__setattr__(
            self, "provider", normalize_smt_provider(self.provider)
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, SmtDisposition, "disposition"),
        )
        object.__setattr__(
            self, "mode", _enum(self.mode, SmtExecutionMode, "mode")
        )
        object.__setattr__(
            self, "query_mode", _enum(self.query_mode, SmtQueryMode, "query_mode")
        )
        object.__setattr__(
            self,
            "obligation_digest",
            _sha256_hex(self.obligation_digest, "obligation_digest"),
        )
        if self.obligation_id:
            object.__setattr__(
                self,
                "obligation_id",
                _text(self.obligation_id, "obligation_id", maximum=256),
            )
        if self.script_digest:
            object.__setattr__(
                self,
                "script_digest",
                _sha256_hex(self.script_digest, "script_digest"),
            )
        for optional_text in (
            "compilation_id",
            "translation_receipt_id",
            "solver_backend_id",
            "solver_version",
            "solver_verdict",
        ):
            value = getattr(self, optional_text)
            if value:
                object.__setattr__(
                    self,
                    optional_text,
                    _text(value, optional_text, maximum=512),
                )
            else:
                object.__setattr__(self, optional_text, "")

        object.__setattr__(self, "model", self._coerce_artifact(self.model, "model"))
        object.__setattr__(
            self, "unsat_core", self._coerce_artifact(self.unsat_core, "unsat_core")
        )
        object.__setattr__(self, "proof", self._coerce_artifact(self.proof, "proof"))

        if self.differential is None:
            object.__setattr__(self, "differential", None)
        elif isinstance(self.differential, SmtDifferentialBindingV2):
            object.__setattr__(self, "differential", self.differential)
        else:
            object.__setattr__(
                self,
                "differential",
                SmtDifferentialBindingV2(
                    **{
                        key: value
                        for key, value in dict(
                            _require_mapping(self.differential, "differential")
                        ).items()
                        if key
                        in {
                            "classification",
                            "agreement",
                            "classification_reason",
                            "left_backend_id",
                            "right_backend_id",
                            "left_verdict",
                            "right_verdict",
                            "script_digest",
                            "disagreement_preserved",
                            "schema_version",
                        }
                    }
                ),
            )

        if self.replay is None:
            object.__setattr__(self, "replay", None)
        elif isinstance(self.replay, SmtReplayReceiptV2):
            object.__setattr__(self, "replay", self.replay)
        else:
            object.__setattr__(
                self,
                "replay",
                SmtReplayReceiptV2(
                    **{
                        key: value
                        for key, value in dict(
                            _require_mapping(self.replay, "replay")
                        ).items()
                        if key
                        in {
                            "replay_id",
                            "request_id",
                            "obligation_digest",
                            "script_digest",
                            "original_disposition",
                            "replayed_disposition",
                            "original_verdict",
                            "replayed_verdict",
                            "matched",
                            "replay_claimed",
                            "diagnostics",
                            "schema_version",
                        }
                    }
                ),
            )

        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids)
        )

        result_authority = (
            self.result_authority
            if isinstance(self.result_authority, ResultAuthority)
            else ResultAuthority(str(self.result_authority))
        )
        if result_authority not in {
            ResultAuthority.SATISFIABILITY,
            ResultAuthority.THEOREM,
        }:
            raise SmtAuthorityError(
                "SMTProviderEvidence@2 result_authority must be satisfiability "
                f"or theorem; got {result_authority!r}"
            )
        object.__setattr__(self, "result_authority", result_authority)

        result_status = (
            self.result_status
            if isinstance(self.result_status, ResultStatus)
            else ResultStatus(str(self.result_status))
        )
        object.__setattr__(self, "result_status", result_status)

        role = self.role if isinstance(self.role, ToolRole) else ToolRole(str(self.role))
        if role not in {ToolRole.AUTHORITY, ToolRole.SHADOW}:
            raise SmtAuthorityError(
                f"SMTProviderEvidence@2 role must be authority or shadow; got {role!r}"
            )
        object.__setattr__(self, "role", role)

        ceiling = (
            self.authority_ceiling
            if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
            else ToolchainAuthorityCeiling(str(self.authority_ceiling))
        )
        if ceiling is not ToolchainAuthorityCeiling.SATISFIABILITY:
            raise SmtAuthorityError(
                "SMTProviderEvidence@2 authority_ceiling must be satisfiability"
            )
        object.__setattr__(self, "authority_ceiling", ceiling)

        translation_ceiling = (
            self.translation_ceiling
            if isinstance(self.translation_ceiling, EvidenceAuthority)
            else EvidenceAuthority(str(self.translation_ceiling))
        )
        if translation_ceiling in {
            EvidenceAuthority.AUTHORITATIVE,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        }:
            # SMT translation receipts remain bounded; never promote to kernel.
            raise SmtAuthorityError(
                "SMTProviderEvidence@2 translation_ceiling cannot exceed bounded"
            )
        object.__setattr__(self, "translation_ceiling", translation_ceiling)

        for flag_name in (
            "satisfiability_established",
            "theorem_established",
            "proof_established",
            "mock_output_present",
            "fallback_output_present",
            "available",
            "fluent_text_present",
            "bounds_exhausted",
        ):
            object.__setattr__(
                self,
                flag_name,
                _optional_bool(getattr(self, flag_name), flag_name),
            )

        object.__setattr__(
            self, "confidence", _unit_interval(self.confidence, "confidence")
        )
        object.__setattr__(self, "diagnostics", _bound_diagnostics(self.diagnostics))

        # Fail closed: mock / fallback never establish authority claims.
        mode = self.mode  # type: ignore[assignment]
        disposition = self.disposition  # type: ignore[assignment]
        if (
            self.mock_output_present
            or self.fallback_output_present
            or mode in {SmtExecutionMode.MOCK, SmtExecutionMode.FALLBACK}
        ):
            if (
                self.satisfiability_established
                or self.theorem_established
                or self.proof_established
            ):
                raise SmtAuthorityError(
                    "fallback or mock output cannot establish satisfiability, "
                    "theorem, or proof authority"
                )
            object.__setattr__(self, "satisfiability_established", False)
            object.__setattr__(self, "theorem_established", False)
            object.__setattr__(self, "proof_established", False)

        # Proof is never established by SMT-LIB get-proof alone on this route.
        if self.proof_established:
            proof = self.proof  # type: ignore[assignment]
            if (
                proof is None
                or not isinstance(proof, SmtArtifactBindingV2)
                or not proof.present
                or not proof.supported
            ):
                raise SmtAuthorityError(
                    "proof_established requires a present supported proof artifact"
                )

        # Disagreement / unsupported features cannot claim success authority.
        if disposition in {
            SmtDisposition.SOLVER_DISAGREEMENT,
            SmtDisposition.UNSUPPORTED_THEORY,
            SmtDisposition.UNSUPPORTED_PROOF_FEATURE,
            SmtDisposition.UNSUPPORTED,
            SmtDisposition.MOCK_REJECTED,
            SmtDisposition.FALLBACK_REJECTED,
            SmtDisposition.REPLAY_MISMATCH,
            SmtDisposition.PARTIAL_UNAVAILABLE,
            SmtDisposition.UNAVAILABLE,
            SmtDisposition.TIMEOUT,
            SmtDisposition.MALFORMED,
            SmtDisposition.ERROR,
            SmtDisposition.UNKNOWN,
        }:
            if (
                self.satisfiability_established
                or self.theorem_established
                or self.proof_established
            ):
                raise SmtAuthorityError(
                    f"disposition {disposition.value!r} cannot establish "
                    "satisfiability, theorem, or proof authority"
                )

        # Success never exceeds the evidence receipt disposition.
        if self.theorem_established and disposition not in {
            SmtDisposition.PROVED,
            SmtDisposition.DISPROVED,
        }:
            raise SmtAuthorityError(
                "theorem_established requires proved/disproved disposition"
            )
        if self.satisfiability_established and disposition not in {
            SmtDisposition.SATISFIABLE,
            SmtDisposition.UNSATISFIABLE,
            SmtDisposition.PROVED,
            SmtDisposition.DISPROVED,
        }:
            raise SmtAuthorityError(
                "satisfiability_established requires a conclusive SAT disposition"
            )

        if not _is_authoritative_mode(mode) and (
            self.satisfiability_established
            or self.theorem_established
            or self.proof_established
        ):
            raise SmtAuthorityError(
                "only pinned_solver or hermetic_fixture modes may establish "
                "SMT authority"
            )

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_authority_metadata(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != SMT_PROVIDER_EVIDENCE_SCHEMA:
            raise SmtExecutionError(
                f"unsupported SMTProviderEvidence@2 schema: "
                f"{self.schema_version!r}"
            )

        if not self.content_digest:
            object.__setattr__(
                self,
                "content_digest",
                _digest_of(self._identity_payload()),
            )
        else:
            provided = _sha256_hex(self.content_digest, "content_digest")
            expected = _digest_of(self._identity_payload())
            if provided != expected:
                raise SmtExecutionError(
                    "content_digest does not match SMTProviderEvidence@2 content"
                )
            object.__setattr__(self, "content_digest", provided)

    @staticmethod
    def _coerce_artifact(
        value: SmtArtifactBindingV2 | Mapping[str, Any] | None,
        field_name: str,
    ) -> SmtArtifactBindingV2 | None:
        if value is None:
            return None
        if isinstance(value, SmtArtifactBindingV2):
            return value
        mapping = _require_mapping(value, field_name)
        return SmtArtifactBindingV2(
            **{
                key: mapping[key]
                for key in {
                    "kind",
                    "present",
                    "digest",
                    "atoms",
                    "text_excerpt",
                    "supported",
                    "schema_version",
                }
                if key in mapping
            }
        )

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, SmtDisposition)
                else self.disposition
            ),
            "mode": (
                self.mode.value
                if isinstance(self.mode, SmtExecutionMode)
                else self.mode
            ),
            "obligation_digest": self.obligation_digest,
            "proof_established": self.proof_established,
            "provider": (
                self.provider.value
                if isinstance(self.provider, SmtProviderKind)
                else self.provider
            ),
            "query_mode": (
                self.query_mode.value
                if isinstance(self.query_mode, SmtQueryMode)
                else self.query_mode
            ),
            "request_id": self.request_id,
            "satisfiability_established": self.satisfiability_established,
            "schema_version": self.schema_version,
            "script_digest": self.script_digest,
            "solver_verdict": self.solver_verdict,
            "theorem_established": self.theorem_established,
        }

    @property
    def is_conclusive(self) -> bool:
        return self.disposition in _conclusive_dispositions()  # type: ignore[operator]

    @property
    def is_proved(self) -> bool:
        return (
            self.disposition is SmtDisposition.PROVED
            and self.theorem_established
            and not self.proof_established  # SMT never claims kernel proof
        )

    @property
    def claim_satisfiability(self) -> bool:
        return self.satisfiability_established

    @property
    def claim_theorem(self) -> bool:
        return self.theorem_established

    @property
    def claim_proof(self) -> bool:
        return self.proof_established

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": (
                self.authority_ceiling.value
                if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
                else self.authority_ceiling
            ),
            "available": self.available,
            "bounds_exhausted": self.bounds_exhausted,
            "claim_proof": self.claim_proof,
            "claim_satisfiability": self.claim_satisfiability,
            "claim_theorem": self.claim_theorem,
            "compilation_id": self.compilation_id,
            "confidence": self.confidence,
            "content_digest": self.content_digest,
            "diagnostics": list(self.diagnostics),
            "differential": (
                None
                if self.differential is None
                else self.differential.to_dict()  # type: ignore[union-attr]
            ),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, SmtDisposition)
                else self.disposition
            ),
            "evidence_id": self.evidence_id,
            "fallback_output_present": self.fallback_output_present,
            "fluent_text_present": self.fluent_text_present,
            "interface": self.interface,
            "is_conclusive": self.is_conclusive,
            "is_proved": self.is_proved,
            "metadata": _thaw_mapping(self.metadata),
            "mock_output_present": self.mock_output_present,
            "mode": (
                self.mode.value
                if isinstance(self.mode, SmtExecutionMode)
                else self.mode
            ),
            "model": None if self.model is None else self.model.to_dict(),  # type: ignore[union-attr]
            "obligation_digest": self.obligation_digest,
            "obligation_id": self.obligation_id,
            "proof": None if self.proof is None else self.proof.to_dict(),  # type: ignore[union-attr]
            "proof_established": self.proof_established,
            "provider": (
                self.provider.value
                if isinstance(self.provider, SmtProviderKind)
                else self.provider
            ),
            "query_mode": (
                self.query_mode.value
                if isinstance(self.query_mode, SmtQueryMode)
                else self.query_mode
            ),
            "replay": None if self.replay is None else self.replay.to_dict(),  # type: ignore[union-attr]
            "request_digest": self.request_digest,
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
            "role": self.role.value if isinstance(self.role, ToolRole) else self.role,
            "satisfiability_established": self.satisfiability_established,
            "schema_version": self.schema_version,
            "script_digest": self.script_digest,
            "solver_backend_id": self.solver_backend_id,
            "solver_verdict": self.solver_verdict,
            "solver_version": self.solver_version,
            "source_ref_ids": list(self.source_ref_ids),
            "theorem_established": self.theorem_established,
            "translation_ceiling": (
                self.translation_ceiling.value
                if isinstance(self.translation_ceiling, EvidenceAuthority)
                else self.translation_ceiling
            ),
            "translation_receipt_id": self.translation_receipt_id,
            "unsat_core": (
                None
                if self.unsat_core is None
                else self.unsat_core.to_dict()  # type: ignore[union-attr]
            ),
        }


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SmtExecutionResultV2:
    """Typed request + evidence + optional normalized backend result.

    Interface: ``SmtExecutionResult@2``.
    """

    request: SmtExecutionRequestV2
    evidence: SmtProviderEvidenceV2
    backend_result: TypedBackendResult | None = None
    differential_report: SmtDifferentialReport | None = None
    schema_version: str = SMT_EXECUTION_RESULT_SCHEMA

    interface: ClassVar[str] = SMT_EXECUTION_RESULT_V2_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.request, SmtExecutionRequestV2):
            raise SmtExecutionError("request must be SmtExecutionRequestV2")
        if not isinstance(self.evidence, SmtProviderEvidenceV2):
            raise SmtExecutionError("evidence must be SmtProviderEvidenceV2")
        if self.request.request_id != self.evidence.request_id:
            raise SmtExecutionError(
                "result request_id must match evidence.request_id"
            )
        if self.backend_result is not None and not isinstance(
            self.backend_result, TypedBackendResult
        ):
            raise SmtExecutionError("backend_result must be TypedBackendResult")
        if self.differential_report is not None and not isinstance(
            self.differential_report, SmtDifferentialReport
        ):
            raise SmtExecutionError(
                "differential_report must be SmtDifferentialReport"
            )
        if self.schema_version != SMT_EXECUTION_RESULT_SCHEMA:
            raise SmtExecutionError(
                f"unsupported result schema: {self.schema_version!r}"
            )

    @property
    def disposition(self) -> SmtDisposition:
        return self.evidence.disposition  # type: ignore[return-value]

    @property
    def is_conclusive(self) -> bool:
        return self.evidence.is_conclusive

    @property
    def is_proved(self) -> bool:
        return self.evidence.is_proved

    @property
    def satisfiability_established(self) -> bool:
        return self.evidence.satisfiability_established

    @property
    def theorem_established(self) -> bool:
        return self.evidence.theorem_established

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_result": (
                None
                if self.backend_result is None
                else self.backend_result.to_dict()
            ),
            "differential_report": (
                None
                if self.differential_report is None
                else self.differential_report.to_dict()
            ),
            "evidence": self.evidence.to_dict(),
            "interface": self.interface,
            "request": self.request.to_dict(),
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def _fixed_runner(
    stdout: str,
    *,
    stderr: str = "",
    returncode: int | None = 0,
    elapsed_ms: int = 7,
    solver_version: str = "hermetic-smt/1.0",
    timed_out: bool = False,
    unavailable: bool = False,
) -> SmtSolverRunner:
    def run(_smtlib: str, _bounds: ExecutionBounds) -> SmtRawSolverOutput:
        return SmtRawSolverOutput(
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            elapsed_ms=elapsed_ms,
            solver_version=solver_version,
            timed_out=timed_out,
            unavailable=unavailable,
        )

    return run


class SmtExecutionEngineV2:
    """Execute and replay typed Z3 / cvc5 SMT/CHC obligations.

    Interface owner: ``SMTProviderEvidence@2``.

    Hermetic fixture runners are the default for deterministic CI.  Live
    pinned solvers may be injected or constructed when available.  Mock and
    fallback outputs are rejected as non-authoritative typed dispositions.
    """

    INTERFACE: ClassVar[str] = SMT_PROVIDER_EVIDENCE_V2_INTERFACE
    interface: ClassVar[str] = SMT_PROVIDER_EVIDENCE_V2_INTERFACE
    VERSION: ClassVar[str] = SMT_EXECUTION_V2_MODULE_VERSION
    TASK_ID: ClassVar[str] = SMT_EXECUTION_V2_TASK_ID
    GOAL_ID: ClassVar[str] = SMT_EXECUTION_V2_GOAL_ID

    def __init__(
        self,
        *,
        z3: SoftwareVerificationSmtBackend | None = None,
        cvc5: SoftwareVerificationSmtBackend | None = None,
        compiler: SoftwareVerificationSMTCompiler | None = None,
    ) -> None:
        self._compiler = compiler or SoftwareVerificationSMTCompiler()
        self._z3 = z3
        self._cvc5 = cvc5

    @property
    def z3(self) -> SoftwareVerificationSmtBackend:
        if self._z3 is None:
            self._z3 = Z3SoftwareVerificationBackend(compiler=self._compiler)
        return self._z3

    @property
    def cvc5(self) -> SoftwareVerificationSmtBackend:
        if self._cvc5 is None:
            self._cvc5 = CVC5SoftwareVerificationBackend(compiler=self._compiler)
        return self._cvc5

    def execute(
        self,
        request: SmtExecutionRequestV2 | Mapping[str, Any],
    ) -> SmtExecutionResultV2:
        """Execute one typed SMT/CHC obligation request."""

        req = (
            request
            if isinstance(request, SmtExecutionRequestV2)
            else SmtExecutionRequestV2.from_dict(request)
        )
        request_digest = _digest_of(req.to_dict())
        obligation_digest = req.obligation_digest
        query_mode = req.query_mode

        # Mock path: never establishes authority.
        if req.has_mock_output or req.mode is SmtExecutionMode.MOCK:
            return self._reject_non_execution(
                req,
                request_digest=request_digest,
                obligation_digest=obligation_digest,
                disposition=SmtDisposition.MOCK_REJECTED,
                mode=SmtExecutionMode.MOCK,
                diagnostics=(
                    "mock_output_cannot_establish_satisfiability",
                    "mock_output_cannot_establish_theorem",
                    "mock_output_cannot_establish_proof",
                    "success_never_promoted_beyond_evidence_receipt",
                ),
                mock_output_present=True,
            )

        # Fallback path: never establishes authority.
        if req.has_fallback_output or req.mode is SmtExecutionMode.FALLBACK:
            return self._reject_non_execution(
                req,
                request_digest=request_digest,
                obligation_digest=obligation_digest,
                disposition=SmtDisposition.FALLBACK_REJECTED,
                mode=SmtExecutionMode.FALLBACK,
                diagnostics=(
                    "fallback_output_cannot_establish_satisfiability",
                    "fallback_output_cannot_establish_theorem",
                    "success_never_promoted_beyond_evidence_receipt",
                ),
                fallback_output_present=True,
            )

        # Unsupported proof production is a typed outcome (never silent success).
        wants_proof = req.request_proof or _request_proof_of(req.obligation)
        if wants_proof:
            return self._reject_non_execution(
                req,
                request_digest=request_digest,
                obligation_digest=obligation_digest,
                disposition=SmtDisposition.UNSUPPORTED_PROOF_FEATURE,
                mode=(
                    req.mode  # type: ignore[arg-type]
                    if isinstance(req.mode, SmtExecutionMode)
                    else SmtExecutionMode.HERMETIC_FIXTURE
                ),
                diagnostics=(
                    f"unsupported_proof_feature:{_UNSUPPORTED_PROOF_FEATURE_TOKEN}",
                    "smt_proof_artifacts_are_not_first_class_on_v2_route",
                    "success_never_promoted_beyond_evidence_receipt",
                ),
                proof=SmtArtifactBindingV2.unsupported_proof(),
            )

        # Hard-unsupported theories are typed outcomes before solver launch.
        features = _features_of(req.obligation)
        hard = [item for item in features if item in _UNSUPPORTED_THEORY_FEATURES]
        if hard:
            return self._reject_non_execution(
                req,
                request_digest=request_digest,
                obligation_digest=obligation_digest,
                disposition=SmtDisposition.UNSUPPORTED_THEORY,
                mode=(
                    req.mode  # type: ignore[arg-type]
                    if isinstance(req.mode, SmtExecutionMode)
                    else SmtExecutionMode.HERMETIC_FIXTURE
                ),
                diagnostics=tuple(
                    f"unsupported_theory:{item.value}" for item in hard
                )
                + ("success_never_promoted_beyond_evidence_receipt",),
            )

        # Compile (may raise UnsupportedSmtFeatureError for hard features).
        try:
            compilation = self._compile(req.obligation)
        except UnsupportedSmtFeatureError as error:
            detail = " ".join(str(error).split())[:400]
            return self._reject_non_execution(
                req,
                request_digest=request_digest,
                obligation_digest=obligation_digest,
                disposition=SmtDisposition.UNSUPPORTED_THEORY,
                mode=(
                    req.mode  # type: ignore[arg-type]
                    if isinstance(req.mode, SmtExecutionMode)
                    else SmtExecutionMode.HERMETIC_FIXTURE
                ),
                diagnostics=(
                    f"unsupported_theory:{detail}",
                    "success_never_promoted_beyond_evidence_receipt",
                ),
            )
        except Exception as error:  # noqa: BLE001 — fail closed on compile errors
            detail = " ".join(str(error).split())[:400]
            return self._reject_non_execution(
                req,
                request_digest=request_digest,
                obligation_digest=obligation_digest,
                disposition=SmtDisposition.MALFORMED,
                mode=(
                    req.mode  # type: ignore[arg-type]
                    if isinstance(req.mode, SmtExecutionMode)
                    else SmtExecutionMode.HERMETIC_FIXTURE
                ),
                diagnostics=(
                    f"compilation_error:{detail}",
                    "success_never_promoted_beyond_evidence_receipt",
                ),
            )

        mode = (
            req.mode
            if isinstance(req.mode, SmtExecutionMode)
            else SmtExecutionMode(str(req.mode))
        )
        bounds = req.bounds  # type: ignore[assignment]
        provider = req.provider  # type: ignore[assignment]

        if provider is SmtProviderKind.DIFFERENTIAL:
            return self._execute_differential(
                req,
                request_digest=request_digest,
                obligation_digest=obligation_digest,
                compilation=compilation,
                mode=mode,
                bounds=bounds,
            )
        backend = self.z3 if provider is SmtProviderKind.Z3 else self.cvc5
        return self._execute_single(
            req,
            request_digest=request_digest,
            obligation_digest=obligation_digest,
            compilation=compilation,
            mode=mode,
            bounds=bounds,
            backend=backend,
        )

    def replay(self, result: SmtExecutionResultV2) -> SmtReplayReceiptV2:
        """Re-execute the same obligation and compare dispositions/verdicts."""

        if not isinstance(result, SmtExecutionResultV2):
            raise SmtExecutionError("replay requires SmtExecutionResultV2")
        if result.disposition in {
            SmtDisposition.MOCK_REJECTED,
            SmtDisposition.FALLBACK_REJECTED,
            SmtDisposition.UNSUPPORTED_THEORY,
            SmtDisposition.UNSUPPORTED_PROOF_FEATURE,
        }:
            raise SmtExecutionError(
                "non-executable dispositions cannot be replayed as success"
            )
        # Force re-execution without mock/fallback.
        fresh = self.execute(
            SmtExecutionRequestV2(
                request_id=result.request.request_id,
                obligation=result.request.obligation,
                provider=result.request.provider,  # type: ignore[arg-type]
                mode=result.request.mode,  # type: ignore[arg-type]
                bounds=result.request.bounds,  # type: ignore[arg-type]
                source_ref_ids=result.request.source_ref_ids,
                request_proof=result.request.request_proof,
                available=result.request.available,
                confidence=result.request.confidence,
            )
        )
        original = result.evidence
        replayed = fresh.evidence
        matched = (
            original.disposition is replayed.disposition
            and original.solver_verdict == replayed.solver_verdict
            and original.obligation_digest == replayed.obligation_digest
            and (
                not original.script_digest
                or not replayed.script_digest
                or original.script_digest == replayed.script_digest
            )
            and original.satisfiability_established
            == replayed.satisfiability_established
            and original.theorem_established == replayed.theorem_established
            and original.proof_established is False
            and replayed.proof_established is False
        )
        return SmtReplayReceiptV2(
            replay_id=f"replay:smt:{result.request.request_id}",
            request_id=result.request.request_id,
            obligation_digest=original.obligation_digest,
            script_digest=original.script_digest or replayed.script_digest,
            original_disposition=original.disposition,  # type: ignore[arg-type]
            replayed_disposition=replayed.disposition,  # type: ignore[arg-type]
            original_verdict=original.solver_verdict,
            replayed_verdict=replayed.solver_verdict,
            matched=matched,
            replay_claimed=matched,
            diagnostics=(
                ()
                if matched
                else ("disposition_or_verdict_mismatch_on_replay",)
            ),
        )

    # --- internal ----------------------------------------------------------

    def _compile(
        self,
        obligation: SmtObligation | Mapping[str, Any] | SmtCompilation,
    ) -> SmtCompilation:
        if isinstance(obligation, SmtCompilation):
            return obligation
        if isinstance(obligation, SmtObligation):
            return self._compiler.compile(obligation)
        # Mapping may carry request_proof which is not a compiler field.
        payload = dict(obligation)
        payload.pop("request_proof", None)
        return self._compiler.compile(payload)

    def _execute_single(
        self,
        req: SmtExecutionRequestV2,
        *,
        request_digest: str,
        obligation_digest: str,
        compilation: SmtCompilation,
        mode: SmtExecutionMode,
        bounds: ExecutionBounds,
        backend: SoftwareVerificationSmtBackend,
    ) -> SmtExecutionResultV2:
        outcome = backend.run_compilation(compilation, bounds=bounds)
        disposition = _verdict_to_disposition(
            query_mode=compilation.query_mode, verdict=outcome.verdict
        )
        return self._build_result(
            req,
            request_digest=request_digest,
            obligation_digest=obligation_digest,
            compilation=compilation,
            mode=mode,
            disposition=disposition,
            primary=outcome,
            differential=None,
            differential_report=None,
        )

    def _execute_differential(
        self,
        req: SmtExecutionRequestV2,
        *,
        request_digest: str,
        obligation_digest: str,
        compilation: SmtCompilation,
        mode: SmtExecutionMode,
        bounds: ExecutionBounds,
    ) -> SmtExecutionResultV2:
        verifier = SmtDifferentialVerifier(
            left=self.z3,
            right=self.cvc5,
            compiler=self._compiler,
        )
        report = verifier.verify(compilation, bounds=bounds)
        disposition = _differential_to_disposition(
            report.classification,
            query_mode=compilation.query_mode,
            left=report.left,
        )
        return self._build_result(
            req,
            request_digest=request_digest,
            obligation_digest=obligation_digest,
            compilation=compilation,
            mode=mode,
            disposition=disposition,
            primary=report.left,
            differential=SmtDifferentialBindingV2.from_report(report),
            differential_report=report,
        )

    def _build_result(
        self,
        req: SmtExecutionRequestV2,
        *,
        request_digest: str,
        obligation_digest: str,
        compilation: SmtCompilation,
        mode: SmtExecutionMode,
        disposition: SmtDisposition,
        primary: SoftwareVerificationSmtOutcome,
        differential: SmtDifferentialBindingV2 | None,
        differential_report: SmtDifferentialReport | None,
    ) -> SmtExecutionResultV2:
        query_mode = compilation.query_mode
        result_status = _disposition_to_result_status(disposition)
        result_authority = _authority_for_disposition(
            disposition, query_mode=query_mode
        )

        model = SmtArtifactBindingV2.from_model(primary.model_text)
        unsat_core = SmtArtifactBindingV2.from_unsat_core(primary.unsat_core)
        proof = SmtArtifactBindingV2.empty()

        # Authority only when conclusive under authoritative modes and not
        # disagreement/unavailable/etc.
        may_claim = (
            _is_authoritative_mode(mode)
            and disposition in _conclusive_dispositions()
            and (
                differential is None
                or (
                    differential.agreement
                    and differential.classification
                    not in {
                        DifferentialClassification.DISAGREE,
                        DifferentialClassification.PARTIAL_UNAVAILABLE,
                        DifferentialClassification.BOTH_UNAVAILABLE,
                    }
                )
            )
        )
        theorem_established = may_claim and disposition in {
            SmtDisposition.PROVED,
            SmtDisposition.DISPROVED,
        }
        # Satisfiability authority covers both pure SAT and theorem-by-negation
        # (which is still an SMT satisfiability query under the hood).
        satisfiability_established = may_claim

        diagnostics: list[str] = [
            f"solver_verdict:{primary.verdict.value}",
            f"query_mode:{query_mode.value}",
            "success_never_promoted_beyond_evidence_receipt",
        ]
        if differential is not None:
            diagnostics.append(
                f"differential:{differential.classification.value}"  # type: ignore[union-attr]
            )
            if disposition is SmtDisposition.SOLVER_DISAGREEMENT:
                diagnostics.append("solver_disagreement_typed_outcome")
                diagnostics.append("disagreement_never_majority_voted")
        if disposition is SmtDisposition.TIMEOUT:
            diagnostics.append("bounds_timeout")
        if model.present:
            diagnostics.append("model_bound")
        if unsat_core.present:
            diagnostics.append("unsat_core_bound")

        evidence = SmtProviderEvidenceV2(
            evidence_id=(
                f"ev:smt:{req.provider.value}:"  # type: ignore[union-attr]
                f"{req.request_id}:{disposition.value}"
            ),
            request_id=req.request_id,
            request_digest=request_digest,
            provider=req.provider,  # type: ignore[arg-type]
            disposition=disposition,
            mode=mode,
            query_mode=query_mode,
            obligation_digest=obligation_digest,
            obligation_id=compilation.obligation_id,
            script_digest=compilation.script.digest,
            compilation_id=compilation.compilation_id,
            translation_receipt_id=compilation.receipt.receipt_id,
            solver_backend_id=primary.backend_id,
            solver_version=primary.solver_version,
            solver_verdict=primary.verdict.value,
            model=model,
            unsat_core=unsat_core,
            proof=proof,
            differential=differential,
            source_ref_ids=req.source_ref_ids,
            result_authority=result_authority,
            result_status=result_status,
            translation_ceiling=EvidenceAuthority.BOUNDED,
            satisfiability_established=satisfiability_established,
            theorem_established=theorem_established,
            proof_established=False,
            mock_output_present=False,
            fallback_output_present=False,
            available=req.available,
            confidence=req.confidence,
            fluent_text_present=bool(req.fluent_text),
            bounds_exhausted=disposition is SmtDisposition.TIMEOUT,
            diagnostics=tuple(diagnostics),
        )

        # Immediate same-obligation replay binding for conclusive hermetic paths.
        replay: SmtReplayReceiptV2 | None = None
        if may_claim and mode is SmtExecutionMode.HERMETIC_FIXTURE:
            replay = self._immediate_replay(
                req=req,
                obligation_digest=obligation_digest,
                script_digest=compilation.script.digest,
                original_disposition=disposition,
                original_verdict=primary.verdict.value,
                primary=primary,
                compilation=compilation,
                mode=mode,
                bounds=req.bounds,  # type: ignore[arg-type]
            )
            if not replay.matched:
                evidence = SmtProviderEvidenceV2(
                    evidence_id=(
                        f"ev:smt:{req.provider.value}:"  # type: ignore[union-attr]
                        f"{req.request_id}:replay_mismatch"
                    ),
                    request_id=req.request_id,
                    request_digest=request_digest,
                    provider=req.provider,  # type: ignore[arg-type]
                    disposition=SmtDisposition.REPLAY_MISMATCH,
                    mode=mode,
                    query_mode=query_mode,
                    obligation_digest=obligation_digest,
                    obligation_id=compilation.obligation_id,
                    script_digest=compilation.script.digest,
                    compilation_id=compilation.compilation_id,
                    translation_receipt_id=compilation.receipt.receipt_id,
                    solver_backend_id=primary.backend_id,
                    solver_version=primary.solver_version,
                    solver_verdict=primary.verdict.value,
                    model=model,
                    unsat_core=unsat_core,
                    proof=proof,
                    differential=differential,
                    replay=replay,
                    source_ref_ids=req.source_ref_ids,
                    result_authority=result_authority,
                    result_status=ResultStatus.ERROR,
                    translation_ceiling=EvidenceAuthority.BOUNDED,
                    satisfiability_established=False,
                    theorem_established=False,
                    proof_established=False,
                    available=req.available,
                    confidence=req.confidence,
                    fluent_text_present=bool(req.fluent_text),
                    diagnostics=(
                        *diagnostics,
                        "verdict_failed_same_obligation_replay",
                    ),
                )
            else:
                evidence = SmtProviderEvidenceV2(
                    evidence_id=evidence.evidence_id,
                    request_id=evidence.request_id,
                    request_digest=evidence.request_digest,
                    provider=evidence.provider,  # type: ignore[arg-type]
                    disposition=evidence.disposition,  # type: ignore[arg-type]
                    mode=evidence.mode,  # type: ignore[arg-type]
                    query_mode=evidence.query_mode,  # type: ignore[arg-type]
                    obligation_digest=evidence.obligation_digest,
                    obligation_id=evidence.obligation_id,
                    script_digest=evidence.script_digest,
                    compilation_id=evidence.compilation_id,
                    translation_receipt_id=evidence.translation_receipt_id,
                    solver_backend_id=evidence.solver_backend_id,
                    solver_version=evidence.solver_version,
                    solver_verdict=evidence.solver_verdict,
                    model=model,
                    unsat_core=unsat_core,
                    proof=proof,
                    differential=differential,
                    replay=replay,
                    source_ref_ids=evidence.source_ref_ids,
                    result_authority=evidence.result_authority,  # type: ignore[arg-type]
                    result_status=evidence.result_status,  # type: ignore[arg-type]
                    translation_ceiling=EvidenceAuthority.BOUNDED,
                    satisfiability_established=evidence.satisfiability_established,
                    theorem_established=evidence.theorem_established,
                    proof_established=False,
                    available=req.available,
                    confidence=req.confidence,
                    fluent_text_present=bool(req.fluent_text),
                    diagnostics=evidence.diagnostics,
                )

        return SmtExecutionResultV2(
            request=req,
            evidence=evidence,
            backend_result=primary.result,
            differential_report=differential_report,
        )

    def _immediate_replay(
        self,
        *,
        req: SmtExecutionRequestV2,
        obligation_digest: str,
        script_digest: str,
        original_disposition: SmtDisposition,
        original_verdict: str,
        primary: SoftwareVerificationSmtOutcome,
        compilation: SmtCompilation,
        mode: SmtExecutionMode,
        bounds: ExecutionBounds,
    ) -> SmtReplayReceiptV2:
        # Re-run the primary backend on the same compilation (deterministic
        # hermetic runners yield identical verdicts).
        provider = req.provider  # type: ignore[assignment]
        if provider is SmtProviderKind.CVC5:
            backend = self.cvc5
        elif provider is SmtProviderKind.Z3:
            backend = self.z3
        else:
            backend = self.z3
        replayed_outcome = backend.run_compilation(compilation, bounds=bounds)
        replayed_disposition = _verdict_to_disposition(
            query_mode=compilation.query_mode,
            verdict=replayed_outcome.verdict,
        )
        matched = (
            replayed_disposition is original_disposition
            and replayed_outcome.verdict.value == original_verdict
            and primary.verdict is replayed_outcome.verdict
        )
        return SmtReplayReceiptV2(
            replay_id=f"replay:smt:{req.request_id}",
            request_id=req.request_id,
            obligation_digest=obligation_digest,
            script_digest=script_digest,
            original_disposition=original_disposition,
            replayed_disposition=replayed_disposition,
            original_verdict=original_verdict,
            replayed_verdict=replayed_outcome.verdict.value,
            matched=matched,
            replay_claimed=matched,
            diagnostics=(
                ()
                if matched
                else ("disposition_or_verdict_mismatch_on_replay",)
            ),
        )

    def _reject_non_execution(
        self,
        req: SmtExecutionRequestV2,
        *,
        request_digest: str,
        obligation_digest: str,
        disposition: SmtDisposition,
        mode: SmtExecutionMode,
        diagnostics: Sequence[str],
        mock_output_present: bool = False,
        fallback_output_present: bool = False,
        proof: SmtArtifactBindingV2 | None = None,
    ) -> SmtExecutionResultV2:
        query_mode = req.query_mode
        result_status = _disposition_to_result_status(disposition)
        result_authority = _authority_for_disposition(
            disposition, query_mode=query_mode
        )
        obligation_id = ""
        if isinstance(req.obligation, SmtObligation):
            obligation_id = req.obligation.obligation_id
        elif isinstance(req.obligation, SmtCompilation):
            obligation_id = req.obligation.obligation_id
        elif isinstance(req.obligation, Mapping):
            obligation_id = str(req.obligation.get("obligation_id") or "")

        evidence = SmtProviderEvidenceV2(
            evidence_id=(
                f"ev:smt:{req.provider.value}:"  # type: ignore[union-attr]
                f"{req.request_id}:{disposition.value}"
            ),
            request_id=req.request_id,
            request_digest=request_digest,
            provider=req.provider,  # type: ignore[arg-type]
            disposition=disposition,
            mode=mode,
            query_mode=query_mode,
            obligation_digest=obligation_digest,
            obligation_id=obligation_id,
            proof=proof or SmtArtifactBindingV2.empty(),
            source_ref_ids=req.source_ref_ids,
            result_authority=result_authority,
            result_status=result_status,
            translation_ceiling=EvidenceAuthority.NONE,
            satisfiability_established=False,
            theorem_established=False,
            proof_established=False,
            mock_output_present=mock_output_present or req.has_mock_output,
            fallback_output_present=fallback_output_present or req.has_fallback_output,
            available=req.available,
            confidence=req.confidence,
            fluent_text_present=bool(req.fluent_text),
            diagnostics=tuple(diagnostics),
        )
        return SmtExecutionResultV2(request=req, evidence=evidence)


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def execute_smt(
    obligation: SmtObligation | Mapping[str, Any] | SmtCompilation,
    *,
    request_id: str = "req:smt:1",
    provider: SmtProviderKind | str = SmtProviderKind.DIFFERENTIAL,
    mode: SmtExecutionMode | str = SmtExecutionMode.HERMETIC_FIXTURE,
    engine: SmtExecutionEngineV2 | None = None,
    **kwargs: Any,
) -> SmtExecutionResultV2:
    """Execute one obligation through SMTProviderEvidence@2."""

    request = SmtExecutionRequestV2(
        request_id=request_id,
        obligation=obligation,
        provider=provider,
        mode=mode,
        **kwargs,
    )
    return (engine or SmtExecutionEngineV2()).execute(request)


def execute_z3(
    obligation: SmtObligation | Mapping[str, Any] | SmtCompilation,
    **kwargs: Any,
) -> SmtExecutionResultV2:
    return execute_smt(obligation, provider=SmtProviderKind.Z3, **kwargs)


def execute_cvc5(
    obligation: SmtObligation | Mapping[str, Any] | SmtCompilation,
    **kwargs: Any,
) -> SmtExecutionResultV2:
    return execute_smt(obligation, provider=SmtProviderKind.CVC5, **kwargs)


def execute_differential(
    obligation: SmtObligation | Mapping[str, Any] | SmtCompilation,
    **kwargs: Any,
) -> SmtExecutionResultV2:
    return execute_smt(
        obligation, provider=SmtProviderKind.DIFFERENTIAL, **kwargs
    )


def hermetic_engine(
    *,
    z3_stdout: str = "unsat\n",
    cvc5_stdout: str = "unsat\n",
    z3_kwargs: Mapping[str, Any] | None = None,
    cvc5_kwargs: Mapping[str, Any] | None = None,
    compiler: SoftwareVerificationSMTCompiler | None = None,
) -> SmtExecutionEngineV2:
    """Build an engine with injectable hermetic solver runners (CI-safe)."""

    z3_opts = dict(z3_kwargs or {})
    cvc5_opts = dict(cvc5_kwargs or {})
    return SmtExecutionEngineV2(
        z3=Z3SoftwareVerificationBackend(
            runner=_fixed_runner(z3_stdout, **z3_opts),
            availability_probe=lambda: True,
            version_probe=lambda: str(z3_opts.get("solver_version", "z3-hermetic")),
            compiler=compiler,
        ),
        cvc5=CVC5SoftwareVerificationBackend(
            runner=_fixed_runner(cvc5_stdout, **cvc5_opts),
            availability_probe=lambda: True,
            version_probe=lambda: str(
                cvc5_opts.get("solver_version", "cvc5-hermetic")
            ),
            compiler=compiler,
        ),
        compiler=compiler,
    )


__all__ = [
    "SMT_ARTIFACT_BINDING_V2_INTERFACE",
    "SMT_DIFFERENTIAL_BINDING_V2_INTERFACE",
    "SMT_EXECUTION_REQUEST_V2_INTERFACE",
    "SMT_EXECUTION_RESULT_V2_INTERFACE",
    "SMT_EXECUTION_V2_GOAL_ID",
    "SMT_EXECUTION_V2_MODULE_VERSION",
    "SMT_EXECUTION_V2_TASK_ID",
    "SMT_PROVIDER_EVIDENCE_V2_INTERFACE",
    "SMT_REPLAY_RECEIPT_V2_INTERFACE",
    "SmtArtifactBindingV2",
    "SmtArtifactKind",
    "SmtAuthorityError",
    "SmtClaimKind",
    "SmtDifferentialBindingV2",
    "SmtDisposition",
    "SmtExecutionEngineV2",
    "SmtExecutionError",
    "SmtExecutionMode",
    "SmtExecutionRequestV2",
    "SmtExecutionResultV2",
    "SmtProviderEvidenceV2",
    "SmtProviderKind",
    "SmtReplayReceiptV2",
    "execute_cvc5",
    "execute_differential",
    "execute_smt",
    "execute_z3",
    "hermetic_engine",
    "mock_or_fallback_establishes_satisfiability",
    "non_authoritative_signal_establishes",
    "normalize_smt_provider",
    "provider_backend_id",
]
