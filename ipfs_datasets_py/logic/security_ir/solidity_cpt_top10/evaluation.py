"""Held-out and adversarial evaluation for Solidity CPT formalization.

Evaluation is CID-bound and deliberately multi-metric.  Leakage, retrieval
accuracy, graph-path validity, attribution, latency, memory, schema validity,
source-span grounding, obligation coverage, executable-lowering quality,
prover outcomes (proof / disproof / unknown / timeout / unavailable /
disagreement), calibration, and abstention are measured separately.  A single
accuracy score is never treated as promotion authority.

Approximate, model, SAT, simulation, and unexecuted results are never counted
as proof.  External label corpora require a separate pin, license, and leakage
admission.  Importing this module performs no network access, compilation,
training, proving, or publication.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Any, Final

from ...ir_core.identity import canonical_identity
from ...ir_core.provenance import (
    ProvenanceValidationError,
    freeze_json_mapping,
    thaw_json,
)
from .partitions import (
    ADVERSARIAL_PARTITION,
    HELD_OUT_PARTITION,
    SOLIDITY_PARTITIONS,
    TEST_PARTITION,
    VALIDATION_PARTITION,
)

EVALUATION_SCHEMA_VERSION: Final = "solidity-cpt-formal-evaluation/v1"
EVALUATION_CASE_SCHEMA_VERSION: Final = "solidity-cpt-evaluation-case/v1"
PROVER_AGREEMENT_SCHEMA_VERSION: Final = "solidity-cpt-prover-agreement/v1"
PROMOTION_GATE_SCHEMA_VERSION: Final = "solidity-cpt-promotion-gate/v1"
EXTERNAL_LABEL_ADMISSION_SCHEMA_VERSION: Final = (
    "solidity-cpt-external-label-admission/v1"
)
EVALUATION_IDENTITY_DOMAIN: Final = "solidity-cpt-security-ir/formal-evaluation"

CANDIDATE_AUTHORITY: Final = "candidate"
NO_PROOF_AUTHORITY: Final = False
NO_TRANSACTION_AUTHORITY: Final = False

DEFAULT_EVALUATION_PARTITIONS: Final = (
    VALIDATION_PARTITION,
    TEST_PARTITION,
    HELD_OUT_PARTITION,
    ADVERSARIAL_PARTITION,
)

# Claim classes that must never be counted as executable proof.
NON_PROOF_CLAIM_KINDS: Final = frozenset(
    {
        "approximate",
        "model",
        "sat",
        "simulation",
        "unexecuted",
    }
)

_CID_RE = re.compile(r"b[a-z2-7]{58}")
_SHA256_RE = re.compile(r"(?:sha256:)?[0-9a-f]{64}")


class EvaluationContractError(ValueError):
    """Base class for malformed evaluation contracts."""


class EvaluationIntegrityError(EvaluationContractError):
    """Raised when a case or report fails rehashing."""


class EvaluationAuthorityError(EvaluationContractError):
    """Raised when evaluation evidence is misused as proof or enforcement."""


class EvaluationLeakageError(EvaluationContractError):
    """Raised when cross-partition or source-family leakage is detected."""


class EvaluationPromotionError(EvaluationContractError):
    """Raised when a promotion gate fails closed."""


class ControlKind(StrEnum):
    """Held-out and adversarial control classes required by acceptance."""

    HELD_OUT = "held_out"
    POISONED_TEXT = "poisoned_text"
    PROMPT_LIKE = "prompt_like"
    AMBIGUOUS_LICENSE = "ambiguous_license"
    UNSUPPORTED_SYNTAX = "unsupported_syntax"
    COMPILER_SOURCE_DEPLOYMENT_MISMATCH = "compiler_source_deployment_mismatch"
    MUTATION = "mutation"
    CORRUPT_GRAPH_INDEX = "corrupt_graph_index"
    CROSS_SOLVER = "cross_solver"


class ProverOutcomeKind(StrEnum):
    """Closed vocabulary of prover outcomes measured separately."""

    PROOF = "proof"
    DISPROOF = "disproof"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    DISAGREEMENT = "disagreement"


class ClaimKind(StrEnum):
    """How a reported solver/model result was produced."""

    EXECUTABLE_PROOF = "executable_proof"
    APPROXIMATE = "approximate"
    MODEL = "model"
    SAT = "sat"
    SIMULATION = "simulation"
    UNEXECUTED = "unexecuted"


class EvaluationMode(StrEnum):
    """Offline evaluation modes; dry-run is the safe default."""

    DRY_RUN = "dry_run"
    FIXTURE_OFFLINE = "fixture_offline"


class MetricSliceName(StrEnum):
    """Every acceptance metric is reported as its own slice."""

    LEAKAGE = "leakage"
    RETRIEVAL_ACCURACY = "retrieval_accuracy"
    GRAPH_PATH_VALIDITY = "graph_path_validity"
    ATTRIBUTION = "attribution"
    LATENCY = "latency"
    MEMORY = "memory"
    SCHEMA_VALIDITY = "schema_validity"
    SOURCE_SPAN_GROUNDING = "source_span_grounding"
    OBLIGATION_COVERAGE = "obligation_coverage"
    EXECUTABLE_LOWERING = "executable_lowering"
    PROVER_OUTCOMES = "prover_outcomes"
    CALIBRATION = "calibration"
    ABSTENTION = "abstention"
    UNSUPPORTED_COVERAGE = "unsupported_coverage"
    UNCERTAINTY = "uncertainty"


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        choices = ", ".join(item.value for item in enum_type)
        raise EvaluationContractError(f"{name} must be one of: {choices}") from exc


def _text(
    value: Any,
    name: str,
    *,
    maximum: int = 512,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise EvaluationContractError(f"{name} must be a string")
    if value != value.strip() or "\x00" in value or len(value) > maximum:
        raise EvaluationContractError(f"{name} must be bounded trimmed text")
    if not allow_empty and not value:
        raise EvaluationContractError(f"{name} must be non-empty")
    return value


def _cid(value: Any, name: str, *, allow_empty: bool = False) -> str:
    result = _text(value, name, maximum=128, allow_empty=allow_empty)
    if result and not _CID_RE.fullmatch(result):
        raise EvaluationContractError(
            f"{name} must be a canonical CIDv1 sha2-256 identity"
        )
    return result


def _sha256(value: Any, name: str, *, allow_empty: bool = False) -> str:
    result = _text(value, name, maximum=71, allow_empty=allow_empty)
    if result and not _SHA256_RE.fullmatch(result):
        raise EvaluationContractError(f"{name} must be lowercase SHA-256")
    if result and not result.startswith("sha256:"):
        result = f"sha256:{result}"
    return result


def _non_negative_int(value: Any, name: str, maximum: int = 1 << 50) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise EvaluationContractError(
            f"{name} must be a non-negative integer no greater than {maximum}"
        )
    return value


def _finite_unit_interval(value: Any, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise EvaluationContractError(
            f"{name} must be a finite number in [0, 1]"
        )
    return float(value)


def _finite_nonnegative(value: Any, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
    ):
        raise EvaluationContractError(
            f"{name} must be a finite non-negative number"
        )
    return float(value)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvaluationContractError(f"{name} must be a mapping")
    return value


def _frozen_mapping(value: Any, name: str) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(_mapping(value, name))
    except ProvenanceValidationError as exc:
        raise EvaluationContractError(f"{name}: {exc}") from exc


def _strict_wire_fields(
    value: Mapping[str, Any],
    fields: frozenset[str],
    name: str,
    *,
    optional: frozenset[str] = frozenset(),
) -> None:
    unknown = sorted(set(value) - fields)
    missing = sorted(fields - optional - set(value))
    if unknown or missing:
        details: list[str] = []
        if unknown:
            details.append("unknown fields: " + ", ".join(unknown))
        if missing:
            details.append("missing fields: " + ", ".join(missing))
        raise EvaluationIntegrityError(f"{name}: {'; '.join(details)}")


def _strings(
    value: Any,
    name: str,
    *,
    maximum_items: int = 256,
    allowed: frozenset[str] | None = None,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise EvaluationContractError(f"{name} must be a sequence")
    result = tuple(_text(item, f"{name} item") for item in value)
    if len(result) > maximum_items or len(result) != len(set(result)):
        raise EvaluationContractError(f"{name} is too large or contains duplicates")
    if allowed is not None and not set(result) <= allowed:
        raise EvaluationContractError(f"{name} contains an unsupported value")
    return tuple(sorted(result))


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _rate(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _identity(payload: Mapping[str, Any], suffix: str, schema: str) -> str:
    return canonical_identity(
        payload,
        domain=f"{EVALUATION_IDENTITY_DOMAIN}/{suffix}",
        schema_version=schema,
    ).cid


def _fixture_cid(label: str) -> str:
    return canonical_identity(
        {"fixture": label},
        domain=f"{EVALUATION_IDENTITY_DOMAIN}/offline-fixture",
        schema_version="solidity-cpt-evaluation-offline-fixture/v1",
    ).cid


def counts_as_executable_proof(
    claim_kind: ClaimKind | str,
    *,
    executed: bool = False,
    authoritative: bool = False,
) -> bool:
    """Return whether a claim may be counted as an executable proof outcome.

    Approximate, model, SAT, simulation, and unexecuted claims always return
    ``False``.  Only an actually executed authoritative executable-proof claim
    may contribute to proof counts.
    """

    kind = _enum(ClaimKind, claim_kind, "claim_kind")
    if kind is not ClaimKind.EXECUTABLE_PROOF:
        return False
    if kind.value in NON_PROOF_CLAIM_KINDS:
        return False
    return bool(executed and authoritative)


@dataclass(frozen=True, slots=True)
class CalibrationMetrics:
    """Separate calibration slice; never folded into a single accuracy score."""

    count: int = 0
    brier_score: float = 0.0
    expected_calibration_error: float = 0.0

    def __post_init__(self) -> None:
        _non_negative_int(self.count, "calibration count", 10_000_000)
        _finite_nonnegative(self.brier_score, "brier_score")
        _finite_nonnegative(
            self.expected_calibration_error, "expected_calibration_error"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "brier_score": self.brier_score,
            "count": self.count,
            "expected_calibration_error": self.expected_calibration_error,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CalibrationMetrics:
        value = _mapping(value, "calibration")
        return cls(
            count=value.get("count", 0),
            brier_score=value.get("brier_score", 0.0),
            expected_calibration_error=value.get(
                "expected_calibration_error", 0.0
            ),
        )


def compute_calibration(
    pairs: Sequence[tuple[float, bool]],
    *,
    bin_count: int = 10,
) -> CalibrationMetrics:
    """Compute Brier score and expected calibration error for confidence pairs."""

    if not pairs:
        return CalibrationMetrics()
    if bin_count < 1:
        raise EvaluationContractError("bin_count must be positive")
    normalized: list[tuple[float, bool]] = []
    for confidence, correct in pairs:
        conf = _finite_unit_interval(confidence, "confidence")
        if type(correct) is not bool:
            raise EvaluationContractError("calibration labels must be boolean")
        normalized.append((conf, correct))
    brier = _mean([(c - float(ok)) ** 2 for c, ok in normalized])
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(bin_count)]
    for conf, ok in normalized:
        bins[min(bin_count - 1, int(conf * bin_count))].append((conf, ok))
    ece = sum(
        (len(items) / len(normalized))
        * abs(
            _mean([c for c, _ in items])
            - _mean([float(ok) for _, ok in items])
        )
        for items in bins
        if items
    )
    return CalibrationMetrics(
        count=len(normalized),
        brier_score=brier,
        expected_calibration_error=ece,
    )


@dataclass(frozen=True, slots=True)
class ProverOutcomeCounts:
    """Separate counters for each prover outcome class."""

    proof: int = 0
    disproof: int = 0
    unknown: int = 0
    timeout: int = 0
    unavailable: int = 0
    disagreement: int = 0
    rejected_non_proof_claims: int = 0

    def __post_init__(self) -> None:
        for name in (
            "proof",
            "disproof",
            "unknown",
            "timeout",
            "unavailable",
            "disagreement",
            "rejected_non_proof_claims",
        ):
            _non_negative_int(getattr(self, name), name, 10_000_000)

    @property
    def total(self) -> int:
        return (
            self.proof
            + self.disproof
            + self.unknown
            + self.timeout
            + self.unavailable
            + self.disagreement
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "disagreement": self.disagreement,
            "disproof": self.disproof,
            "proof": self.proof,
            "rejected_non_proof_claims": self.rejected_non_proof_claims,
            "timeout": self.timeout,
            "unavailable": self.unavailable,
            "unknown": self.unknown,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProverOutcomeCounts:
        value = _mapping(value, "prover_outcomes")
        return cls(
            proof=value.get("proof", 0),
            disproof=value.get("disproof", 0),
            unknown=value.get("unknown", 0),
            timeout=value.get("timeout", 0),
            unavailable=value.get("unavailable", 0),
            disagreement=value.get("disagreement", 0),
            rejected_non_proof_claims=value.get("rejected_non_proof_claims", 0),
        )


@dataclass(frozen=True, slots=True)
class ProverAgreement:
    """Multi-solver agreement record; disagreement is never folded into proof."""

    case_id: str
    solver_ids: tuple[str, ...]
    outcomes_by_solver: Mapping[str, str]
    agreement: bool
    outcome: ProverOutcomeKind
    schema_version: str = PROVER_AGREEMENT_SCHEMA_VERSION
    agreement_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _text(self.case_id, "case_id"))
        solvers = _strings(self.solver_ids, "solver_ids", maximum_items=32)
        if len(solvers) < 2:
            raise EvaluationContractError(
                "prover agreement requires at least two solvers"
            )
        object.__setattr__(self, "solver_ids", solvers)
        raw = _mapping(self.outcomes_by_solver, "outcomes_by_solver")
        normalized: dict[str, str] = {}
        for solver, outcome in raw.items():
            key = _text(solver, "solver id")
            kind = _enum(ProverOutcomeKind, outcome, f"outcome for {key}")
            normalized[key] = kind.value
        if set(normalized) != set(solvers):
            raise EvaluationContractError(
                "outcomes_by_solver must cover exactly the solver_ids set"
            )
        object.__setattr__(
            self, "outcomes_by_solver", MappingProxyType(dict(sorted(normalized.items())))
        )
        unique = set(normalized.values())
        computed_agreement = len(unique) == 1
        if type(self.agreement) is not bool:
            raise EvaluationContractError("agreement must be boolean")
        if self.agreement != computed_agreement:
            raise EvaluationIntegrityError(
                "agreement flag does not match solver outcomes"
            )
        object.__setattr__(
            self, "outcome", _enum(ProverOutcomeKind, self.outcome, "outcome")
        )
        if computed_agreement:
            expected = ProverOutcomeKind(next(iter(unique)))
            if self.outcome is not expected:
                raise EvaluationIntegrityError(
                    "agreed outcome must match the shared solver outcome"
                )
        elif self.outcome is not ProverOutcomeKind.DISAGREEMENT:
            raise EvaluationIntegrityError(
                "disagreement must be recorded as outcome=disagreement"
            )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != PROVER_AGREEMENT_SCHEMA_VERSION:
            raise EvaluationContractError("unsupported prover agreement schema")
        computed = self.identity
        if self.agreement_id and self.agreement_id != computed:
            raise EvaluationIntegrityError(
                "agreement_id does not match rehashed prover agreement"
            )
        object.__setattr__(self, "agreement_id", computed)

    @property
    def identity(self) -> str:
        return _identity(
            self.deterministic_dict(),
            "prover-agreement",
            PROVER_AGREEMENT_SCHEMA_VERSION,
        )

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "agreement": self.agreement,
            "case_id": self.case_id,
            "outcome": self.outcome.value,
            "outcomes_by_solver": dict(self.outcomes_by_solver),
            "schema_version": self.schema_version,
            "solver_ids": list(self.solver_ids),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"agreement_id": self.agreement_id, **self.deterministic_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProverAgreement:
        value = _mapping(value, "prover agreement")
        _strict_wire_fields(
            value,
            frozenset(
                {
                    "agreement",
                    "agreement_id",
                    "case_id",
                    "outcome",
                    "outcomes_by_solver",
                    "schema_version",
                    "solver_ids",
                }
            ),
            "prover agreement",
            optional=frozenset({"agreement_id"}),
        )
        return cls(
            case_id=value.get("case_id", ""),
            solver_ids=tuple(value.get("solver_ids", ())),
            outcomes_by_solver=value.get("outcomes_by_solver", {}),
            agreement=value.get("agreement", False),
            outcome=value.get("outcome", ""),
            schema_version=value.get(
                "schema_version", PROVER_AGREEMENT_SCHEMA_VERSION
            ),
            agreement_id=value.get("agreement_id", ""),
        )

    @classmethod
    def from_solver_outcomes(
        cls,
        case_id: str,
        outcomes_by_solver: Mapping[str, ProverOutcomeKind | str],
    ) -> ProverAgreement:
        solvers = tuple(sorted(outcomes_by_solver))
        wire = {
            solver: _enum(ProverOutcomeKind, outcomes_by_solver[solver], solver).value
            for solver in solvers
        }
        unique = set(wire.values())
        if len(unique) == 1:
            agreement = True
            outcome = ProverOutcomeKind(next(iter(unique)))
        else:
            agreement = False
            outcome = ProverOutcomeKind.DISAGREEMENT
        return cls(
            case_id=case_id,
            solver_ids=solvers,
            outcomes_by_solver=wire,
            agreement=agreement,
            outcome=outcome,
        )


@dataclass(frozen=True, slots=True)
class ExternalLabelCorpusAdmission:
    """Separate pin/license/leakage admission required for external labels."""

    corpus_id: str
    pin_cid: str
    license_cid: str
    leakage_admission: bool
    license_admitted: bool
    pin_verified: bool
    diagnostics: tuple[str, ...] = ()
    schema_version: str = EXTERNAL_LABEL_ADMISSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "corpus_id", _text(self.corpus_id, "corpus_id"))
        object.__setattr__(self, "pin_cid", _cid(self.pin_cid, "pin_cid"))
        object.__setattr__(
            self, "license_cid", _cid(self.license_cid, "license_cid")
        )
        for name in ("leakage_admission", "license_admitted", "pin_verified"):
            if type(getattr(self, name)) is not bool:
                raise EvaluationContractError(f"{name} must be boolean")
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                _text(item, "diagnostic", maximum=1024)
                for item in self.diagnostics
            ),
        )
        if self.schema_version != EXTERNAL_LABEL_ADMISSION_SCHEMA_VERSION:
            raise EvaluationContractError(
                "unsupported external label admission schema"
            )

    @property
    def admitted(self) -> bool:
        return (
            self.pin_verified
            and self.license_admitted
            and self.leakage_admission
        )

    def require_admitted(self) -> ExternalLabelCorpusAdmission:
        if not self.admitted:
            raise EvaluationAuthorityError(
                "external label corpus lacks pin/license/leakage admission"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "corpus_id": self.corpus_id,
            "diagnostics": list(self.diagnostics),
            "leakage_admission": self.leakage_admission,
            "license_admitted": self.license_admitted,
            "license_cid": self.license_cid,
            "pin_cid": self.pin_cid,
            "pin_verified": self.pin_verified,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ExternalLabelCorpusAdmission:
        value = _mapping(value, "external label admission")
        return cls(
            corpus_id=value.get("corpus_id", ""),
            pin_cid=value.get("pin_cid", ""),
            license_cid=value.get("license_cid", ""),
            leakage_admission=value.get("leakage_admission", False),
            license_admitted=value.get("license_admitted", False),
            pin_verified=value.get("pin_verified", False),
            diagnostics=tuple(value.get("diagnostics", ())),
            schema_version=value.get(
                "schema_version", EXTERNAL_LABEL_ADMISSION_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    """One held-out or adversarial evaluation observation."""

    case_id: str
    partition: str
    control_kind: ControlKind
    source_family_id: str
    claim_kind: ClaimKind
    prover_outcome: ProverOutcomeKind
    expected_abstention: bool
    abstained: bool
    schema_valid: bool
    source_span_grounded: bool
    obligation_covered: bool
    executable_lowering_ok: bool
    graph_path_valid: bool
    retrieval_hit: bool
    attribution_correct: bool
    confidence: float
    correct: bool
    latency_ms: float
    peak_memory_bytes: int
    unsupported: bool = False
    uncertainty_flag: bool = False
    claim_executed: bool = False
    claim_authoritative: bool = False
    proof_authority: bool = NO_PROOF_AUTHORITY
    transaction_authority: bool = NO_TRANSACTION_AUTHORITY
    learned_output_authority: str = CANDIDATE_AUTHORITY
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = EVALUATION_CASE_SCHEMA_VERSION
    case_cid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _text(self.case_id, "case_id"))
        partition = _text(self.partition, "partition", maximum=64)
        if partition not in SOLIDITY_PARTITIONS:
            raise EvaluationContractError(
                f"partition must be one of: {', '.join(SOLIDITY_PARTITIONS)}"
            )
        object.__setattr__(self, "partition", partition)
        object.__setattr__(
            self, "control_kind", _enum(ControlKind, self.control_kind, "control_kind")
        )
        object.__setattr__(
            self,
            "source_family_id",
            _text(self.source_family_id, "source_family_id"),
        )
        object.__setattr__(
            self, "claim_kind", _enum(ClaimKind, self.claim_kind, "claim_kind")
        )
        object.__setattr__(
            self,
            "prover_outcome",
            _enum(ProverOutcomeKind, self.prover_outcome, "prover_outcome"),
        )
        for name in (
            "expected_abstention",
            "abstained",
            "schema_valid",
            "source_span_grounded",
            "obligation_covered",
            "executable_lowering_ok",
            "graph_path_valid",
            "retrieval_hit",
            "attribution_correct",
            "correct",
            "unsupported",
            "uncertainty_flag",
            "claim_executed",
            "claim_authoritative",
        ):
            if type(getattr(self, name)) is not bool:
                raise EvaluationContractError(f"{name} must be boolean")
        object.__setattr__(
            self, "confidence", _finite_unit_interval(self.confidence, "confidence")
        )
        object.__setattr__(
            self, "latency_ms", _finite_nonnegative(self.latency_ms, "latency_ms")
        )
        object.__setattr__(
            self,
            "peak_memory_bytes",
            _non_negative_int(self.peak_memory_bytes, "peak_memory_bytes"),
        )
        if (
            self.learned_output_authority != CANDIDATE_AUTHORITY
            or self.proof_authority is not False
            or self.transaction_authority is not False
        ):
            raise EvaluationAuthorityError(
                "evaluation cases remain candidate-only and non-authoritative"
            )
        # Non-proof claim kinds may never contribute a proof outcome.
        if (
            self.prover_outcome is ProverOutcomeKind.PROOF
            and not counts_as_executable_proof(
                self.claim_kind,
                executed=self.claim_executed,
                authoritative=self.claim_authoritative,
            )
        ):
            raise EvaluationAuthorityError(
                "non-executable claims cannot be recorded as proof outcomes"
            )
        object.__setattr__(
            self, "metadata", _frozen_mapping(self.metadata, "metadata")
        )
        if self.schema_version != EVALUATION_CASE_SCHEMA_VERSION:
            raise EvaluationContractError("unsupported evaluation case schema")
        computed = self.identity
        if self.case_cid and self.case_cid != computed:
            raise EvaluationIntegrityError(
                "case_cid does not match rehashed evaluation case"
            )
        object.__setattr__(self, "case_cid", computed)

    @property
    def identity(self) -> str:
        return _identity(
            self.deterministic_dict(),
            "case",
            EVALUATION_CASE_SCHEMA_VERSION,
        )

    @property
    def counts_as_proof(self) -> bool:
        return (
            self.prover_outcome is ProverOutcomeKind.PROOF
            and counts_as_executable_proof(
                self.claim_kind,
                executed=self.claim_executed,
                authoritative=self.claim_authoritative,
            )
        )

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "abstained": self.abstained,
            "attribution_correct": self.attribution_correct,
            "case_id": self.case_id,
            "claim_authoritative": self.claim_authoritative,
            "claim_executed": self.claim_executed,
            "claim_kind": self.claim_kind.value,
            "confidence": self.confidence,
            "control_kind": self.control_kind.value,
            "correct": self.correct,
            "executable_lowering_ok": self.executable_lowering_ok,
            "expected_abstention": self.expected_abstention,
            "graph_path_valid": self.graph_path_valid,
            "latency_ms": self.latency_ms,
            "learned_output_authority": CANDIDATE_AUTHORITY,
            "metadata": thaw_json(self.metadata),
            "obligation_covered": self.obligation_covered,
            "partition": self.partition,
            "peak_memory_bytes": self.peak_memory_bytes,
            "proof_authority": False,
            "prover_outcome": self.prover_outcome.value,
            "retrieval_hit": self.retrieval_hit,
            "schema_valid": self.schema_valid,
            "schema_version": self.schema_version,
            "source_family_id": self.source_family_id,
            "source_span_grounded": self.source_span_grounded,
            "transaction_authority": False,
            "uncertainty_flag": self.uncertainty_flag,
            "unsupported": self.unsupported,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"case_cid": self.case_cid, **self.deterministic_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EvaluationCase:
        value = _mapping(value, "evaluation case")
        return cls(
            case_id=value.get("case_id", ""),
            partition=value.get("partition", ""),
            control_kind=value.get("control_kind", ""),
            source_family_id=value.get("source_family_id", ""),
            claim_kind=value.get("claim_kind", ClaimKind.UNEXECUTED),
            prover_outcome=value.get("prover_outcome", ""),
            expected_abstention=value.get("expected_abstention", False),
            abstained=value.get("abstained", False),
            schema_valid=value.get("schema_valid", False),
            source_span_grounded=value.get("source_span_grounded", False),
            obligation_covered=value.get("obligation_covered", False),
            executable_lowering_ok=value.get("executable_lowering_ok", False),
            graph_path_valid=value.get("graph_path_valid", False),
            retrieval_hit=value.get("retrieval_hit", False),
            attribution_correct=value.get("attribution_correct", False),
            confidence=value.get("confidence", 0.0),
            correct=value.get("correct", False),
            latency_ms=value.get("latency_ms", 0.0),
            peak_memory_bytes=value.get("peak_memory_bytes", 0),
            unsupported=value.get("unsupported", False),
            uncertainty_flag=value.get("uncertainty_flag", False),
            claim_executed=value.get("claim_executed", False),
            claim_authoritative=value.get("claim_authoritative", False),
            proof_authority=value.get("proof_authority", False),
            transaction_authority=value.get("transaction_authority", False),
            learned_output_authority=value.get(
                "learned_output_authority", CANDIDATE_AUTHORITY
            ),
            metadata=value.get("metadata", {}),
            schema_version=value.get(
                "schema_version", EVALUATION_CASE_SCHEMA_VERSION
            ),
            case_cid=value.get("case_cid", ""),
        )


@dataclass(frozen=True, slots=True)
class SeparateMetricReport:
    """Every acceptance metric reported as an independent slice."""

    case_count: int
    leakage_count: int
    retrieval_accuracy: float
    graph_path_validity: float
    attribution: float
    mean_latency_ms: float
    peak_memory_bytes: int
    schema_validity: float
    source_span_grounding: float
    obligation_coverage: float
    executable_lowering: float
    prover_outcomes: ProverOutcomeCounts
    calibration: CalibrationMetrics
    abstention_rate: float
    abstention_precision: float
    abstention_recall: float
    unsupported_coverage: float
    uncertainty_rate: float
    # Explicit non-single-score notice for consumers.
    single_accuracy_score: None = None
    misleading_accuracy_optimized: bool = False

    def __post_init__(self) -> None:
        _non_negative_int(self.case_count, "case_count", 10_000_000)
        _non_negative_int(self.leakage_count, "leakage_count", 10_000_000)
        for name in (
            "retrieval_accuracy",
            "graph_path_validity",
            "attribution",
            "schema_validity",
            "source_span_grounding",
            "obligation_coverage",
            "executable_lowering",
            "abstention_rate",
            "abstention_precision",
            "abstention_recall",
            "unsupported_coverage",
            "uncertainty_rate",
        ):
            _finite_unit_interval(getattr(self, name), name)
        _finite_nonnegative(self.mean_latency_ms, "mean_latency_ms")
        _non_negative_int(self.peak_memory_bytes, "peak_memory_bytes")
        if not isinstance(self.prover_outcomes, ProverOutcomeCounts):
            raise EvaluationContractError(
                "prover_outcomes must be ProverOutcomeCounts"
            )
        if not isinstance(self.calibration, CalibrationMetrics):
            raise EvaluationContractError("calibration must be CalibrationMetrics")
        if self.single_accuracy_score is not None:
            raise EvaluationAuthorityError(
                "evaluation must not optimize or publish a single accuracy score"
            )
        if self.misleading_accuracy_optimized is not False:
            raise EvaluationAuthorityError(
                "evaluation must not optimize a single misleading accuracy score"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "abstention_precision": self.abstention_precision,
            "abstention_rate": self.abstention_rate,
            "abstention_recall": self.abstention_recall,
            "attribution": self.attribution,
            "calibration": self.calibration.to_dict(),
            "case_count": self.case_count,
            "executable_lowering": self.executable_lowering,
            "graph_path_validity": self.graph_path_validity,
            "leakage_count": self.leakage_count,
            "mean_latency_ms": self.mean_latency_ms,
            "misleading_accuracy_optimized": False,
            "obligation_coverage": self.obligation_coverage,
            "peak_memory_bytes": self.peak_memory_bytes,
            "prover_outcomes": self.prover_outcomes.to_dict(),
            "retrieval_accuracy": self.retrieval_accuracy,
            "schema_validity": self.schema_validity,
            "single_accuracy_score": None,
            "source_span_grounding": self.source_span_grounding,
            "uncertainty_rate": self.uncertainty_rate,
            "unsupported_coverage": self.unsupported_coverage,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SeparateMetricReport:
        value = _mapping(value, "metrics")
        return cls(
            case_count=value.get("case_count", 0),
            leakage_count=value.get("leakage_count", 0),
            retrieval_accuracy=value.get("retrieval_accuracy", 0.0),
            graph_path_validity=value.get("graph_path_validity", 0.0),
            attribution=value.get("attribution", 0.0),
            mean_latency_ms=value.get("mean_latency_ms", 0.0),
            peak_memory_bytes=value.get("peak_memory_bytes", 0),
            schema_validity=value.get("schema_validity", 0.0),
            source_span_grounding=value.get("source_span_grounding", 0.0),
            obligation_coverage=value.get("obligation_coverage", 0.0),
            executable_lowering=value.get("executable_lowering", 0.0),
            prover_outcomes=ProverOutcomeCounts.from_dict(
                value.get("prover_outcomes", {})
            ),
            calibration=CalibrationMetrics.from_dict(
                value.get("calibration", {})
            ),
            abstention_rate=value.get("abstention_rate", 0.0),
            abstention_precision=value.get("abstention_precision", 0.0),
            abstention_recall=value.get("abstention_recall", 0.0),
            unsupported_coverage=value.get("unsupported_coverage", 0.0),
            uncertainty_rate=value.get("uncertainty_rate", 0.0),
            single_accuracy_score=value.get("single_accuracy_score", None),
            misleading_accuracy_optimized=value.get(
                "misleading_accuracy_optimized", False
            ),
        )


def detect_cross_partition_leakage(
    cases: Sequence[EvaluationCase],
) -> tuple[Mapping[str, Any], ...]:
    """Detect source-family or case_id reuse across evaluation partitions."""

    by_family: dict[str, set[str]] = {}
    by_case: dict[str, set[str]] = {}
    for case in cases:
        by_family.setdefault(case.source_family_id, set()).add(case.partition)
        by_case.setdefault(case.case_id, set()).add(case.partition)
    findings: list[dict[str, Any]] = []
    for family_id, partitions in sorted(by_family.items()):
        if len(partitions) > 1:
            findings.append(
                {
                    "kind": "source_family_cross_partition",
                    "key": family_id,
                    "partitions": sorted(partitions),
                }
            )
    for case_id, partitions in sorted(by_case.items()):
        if len(partitions) > 1:
            findings.append(
                {
                    "kind": "case_id_cross_partition",
                    "key": case_id,
                    "partitions": sorted(partitions),
                }
            )
    return tuple(findings)


def aggregate_metrics(
    cases: Sequence[EvaluationCase],
    *,
    leakage_findings: Sequence[Mapping[str, Any]] = (),
) -> SeparateMetricReport:
    """Aggregate per-case observations into independent metric slices."""

    if not cases:
        raise EvaluationContractError("evaluation requires at least one case")
    n = len(cases)
    leakage_count = len(leakage_findings)

    def ratio(predicate) -> float:
        return _rate(sum(1 for item in cases if predicate(item)), n)

    expected_abstain = [item for item in cases if item.expected_abstention]
    predicted_abstain = [item for item in cases if item.abstained]
    true_positive = sum(
        1 for item in cases if item.expected_abstention and item.abstained
    )
    abstention_precision = _rate(true_positive, len(predicted_abstain))
    abstention_recall = _rate(true_positive, len(expected_abstain))

    outcome_counts = {
        "proof": 0,
        "disproof": 0,
        "unknown": 0,
        "timeout": 0,
        "unavailable": 0,
        "disagreement": 0,
        "rejected_non_proof_claims": 0,
    }
    for item in cases:
        # Count only executable proofs toward the proof bucket.
        if item.prover_outcome is ProverOutcomeKind.PROOF:
            if item.counts_as_proof:
                outcome_counts["proof"] += 1
            else:
                outcome_counts["rejected_non_proof_claims"] += 1
                outcome_counts["unknown"] += 1
        else:
            outcome_counts[item.prover_outcome.value] += 1

    calibration = compute_calibration(
        [(item.confidence, item.correct) for item in cases if not item.abstained]
    )
    return SeparateMetricReport(
        case_count=n,
        leakage_count=leakage_count,
        retrieval_accuracy=ratio(lambda c: c.retrieval_hit),
        graph_path_validity=ratio(lambda c: c.graph_path_valid),
        attribution=ratio(lambda c: c.attribution_correct),
        mean_latency_ms=_mean([item.latency_ms for item in cases]),
        peak_memory_bytes=max(item.peak_memory_bytes for item in cases),
        schema_validity=ratio(lambda c: c.schema_valid),
        source_span_grounding=ratio(lambda c: c.source_span_grounded),
        obligation_coverage=ratio(lambda c: c.obligation_covered),
        executable_lowering=ratio(lambda c: c.executable_lowering_ok),
        prover_outcomes=ProverOutcomeCounts(**outcome_counts),
        calibration=calibration,
        abstention_rate=ratio(lambda c: c.abstained),
        abstention_precision=abstention_precision if predicted_abstain else 1.0,
        abstention_recall=abstention_recall if expected_abstain else 1.0,
        unsupported_coverage=ratio(lambda c: c.unsupported),
        uncertainty_rate=ratio(lambda c: c.uncertainty_flag),
    )


@dataclass(frozen=True, slots=True)
class PromotionGate:
    """Fail-closed promotion gate over evaluation evidence.

    Promotion requires zero leakage and zero false executable-proof claims.
    Quality metrics are reported but never reduced to one accuracy score.
    """

    evaluation_cid: str
    leakage_count: int
    false_proof_count: int
    authority_violation_count: int
    external_label_admitted: bool
    controls_covered: tuple[str, ...]
    metrics_complete: bool
    diagnostics: tuple[str, ...] = ()
    schema_version: str = PROMOTION_GATE_SCHEMA_VERSION
    gate_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evaluation_cid", _cid(self.evaluation_cid, "evaluation_cid")
        )
        for name in (
            "leakage_count",
            "false_proof_count",
            "authority_violation_count",
        ):
            _non_negative_int(getattr(self, name), name, 10_000_000)
        if type(self.external_label_admitted) is not bool:
            raise EvaluationContractError("external_label_admitted must be boolean")
        if type(self.metrics_complete) is not bool:
            raise EvaluationContractError("metrics_complete must be boolean")
        object.__setattr__(
            self,
            "controls_covered",
            _strings(
                self.controls_covered,
                "controls_covered",
                allowed=frozenset(item.value for item in ControlKind),
            ),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                _text(item, "diagnostic", maximum=1024)
                for item in self.diagnostics
            ),
        )
        if self.schema_version != PROMOTION_GATE_SCHEMA_VERSION:
            raise EvaluationContractError("unsupported promotion gate schema")
        computed = self.identity
        if self.gate_id and self.gate_id != computed:
            raise EvaluationIntegrityError(
                "gate_id does not match rehashed promotion gate"
            )
        object.__setattr__(self, "gate_id", computed)

    @property
    def identity(self) -> str:
        return _identity(
            self.deterministic_dict(),
            "promotion-gate",
            PROMOTION_GATE_SCHEMA_VERSION,
        )

    @property
    def passed(self) -> bool:
        required = {item.value for item in ControlKind}
        return (
            self.leakage_count == 0
            and self.false_proof_count == 0
            and self.authority_violation_count == 0
            and self.external_label_admitted
            and self.metrics_complete
            and required <= set(self.controls_covered)
        )

    def require_passed(self) -> PromotionGate:
        if not self.passed:
            raise EvaluationPromotionError(
                "promotion gate failed closed: "
                f"leakage={self.leakage_count}, "
                f"false_proofs={self.false_proof_count}, "
                f"authority_violations={self.authority_violation_count}, "
                f"external_label_admitted={self.external_label_admitted}, "
                f"metrics_complete={self.metrics_complete}, "
                f"controls={list(self.controls_covered)}"
            )
        return self

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "authority_violation_count": self.authority_violation_count,
            "controls_covered": list(self.controls_covered),
            "diagnostics": list(self.diagnostics),
            "evaluation_cid": self.evaluation_cid,
            "external_label_admitted": self.external_label_admitted,
            "false_proof_count": self.false_proof_count,
            "leakage_count": self.leakage_count,
            "metrics_complete": self.metrics_complete,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "passed": self.passed,
            **self.deterministic_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PromotionGate:
        value = _mapping(value, "promotion gate")
        return cls(
            evaluation_cid=value.get("evaluation_cid", ""),
            leakage_count=value.get("leakage_count", 0),
            false_proof_count=value.get("false_proof_count", 0),
            authority_violation_count=value.get("authority_violation_count", 0),
            external_label_admitted=value.get("external_label_admitted", False),
            controls_covered=tuple(value.get("controls_covered", ())),
            metrics_complete=value.get("metrics_complete", False),
            diagnostics=tuple(value.get("diagnostics", ())),
            schema_version=value.get(
                "schema_version", PROMOTION_GATE_SCHEMA_VERSION
            ),
            gate_id=value.get("gate_id", ""),
        )


@dataclass(frozen=True, slots=True)
class SolidityFormalEvaluation:
    """CID-bound multi-metric evaluation receipt for Solidity CPT formalization."""

    source_cid: str
    graph_cid: str
    index_cid: str
    partition_cid: str
    license_cid: str
    model_or_checkpoint_cid: str
    evaluation_partitions: tuple[str, ...]
    cases: tuple[EvaluationCase, ...]
    metrics: SeparateMetricReport
    leakage_findings: tuple[Mapping[str, Any], ...] = ()
    prover_agreements: tuple[ProverAgreement, ...] = ()
    external_label_admission: ExternalLabelCorpusAdmission | None = None
    mode: EvaluationMode = EvaluationMode.DRY_RUN
    diagnostics: tuple[str, ...] = ()
    proof_authority: bool = NO_PROOF_AUTHORITY
    transaction_authority: bool = NO_TRANSACTION_AUTHORITY
    learned_output_authority: str = CANDIDATE_AUTHORITY
    schema_version: str = EVALUATION_SCHEMA_VERSION
    evaluation_cid: str = ""

    def __post_init__(self) -> None:
        for name in (
            "source_cid",
            "graph_cid",
            "index_cid",
            "partition_cid",
            "license_cid",
            "model_or_checkpoint_cid",
        ):
            object.__setattr__(self, name, _cid(getattr(self, name), name))
        partitions = _strings(
            self.evaluation_partitions,
            "evaluation_partitions",
            allowed=frozenset(SOLIDITY_PARTITIONS),
        )
        if not partitions:
            raise EvaluationContractError(
                "evaluation_partitions must be non-empty"
            )
        object.__setattr__(self, "evaluation_partitions", partitions)
        if not self.cases:
            raise EvaluationContractError("evaluation requires at least one case")
        normalized_cases: list[EvaluationCase] = []
        for item in self.cases:
            if isinstance(item, EvaluationCase):
                normalized_cases.append(item)
            elif isinstance(item, Mapping):
                normalized_cases.append(EvaluationCase.from_dict(item))
            else:
                raise EvaluationContractError(
                    "cases must contain EvaluationCase values or mappings"
                )
        case_ids = [item.case_id for item in normalized_cases]
        if len(case_ids) != len(set(case_ids)):
            raise EvaluationContractError("case_id values must be unique")
        object.__setattr__(
            self,
            "cases",
            tuple(sorted(normalized_cases, key=lambda item: item.case_id)),
        )
        if not isinstance(self.metrics, SeparateMetricReport):
            if isinstance(self.metrics, Mapping):
                object.__setattr__(
                    self, "metrics", SeparateMetricReport.from_dict(self.metrics)
                )
            else:
                raise EvaluationContractError(
                    "metrics must be a SeparateMetricReport"
                )
        findings = tuple(
            MappingProxyType(dict(sorted(_mapping(item, "leakage finding").items())))
            for item in self.leakage_findings
        )
        object.__setattr__(self, "leakage_findings", findings)
        agreements: list[ProverAgreement] = []
        for item in self.prover_agreements:
            if isinstance(item, ProverAgreement):
                agreements.append(item)
            elif isinstance(item, Mapping):
                agreements.append(ProverAgreement.from_dict(item))
            else:
                raise EvaluationContractError(
                    "prover_agreements must contain ProverAgreement values"
                )
        object.__setattr__(
            self,
            "prover_agreements",
            tuple(sorted(agreements, key=lambda item: item.case_id)),
        )
        if self.external_label_admission is not None and not isinstance(
            self.external_label_admission, ExternalLabelCorpusAdmission
        ):
            object.__setattr__(
                self,
                "external_label_admission",
                ExternalLabelCorpusAdmission.from_dict(
                    _mapping(
                        self.external_label_admission,
                        "external_label_admission",
                    )
                ),
            )
        object.__setattr__(self, "mode", _enum(EvaluationMode, self.mode, "mode"))
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                _text(item, "diagnostic", maximum=1024)
                for item in self.diagnostics
            ),
        )
        if (
            self.learned_output_authority != CANDIDATE_AUTHORITY
            or self.proof_authority is not False
            or self.transaction_authority is not False
        ):
            raise EvaluationAuthorityError(
                "evaluation receipts are candidate-only and non-authoritative"
            )
        if self.schema_version != EVALUATION_SCHEMA_VERSION:
            raise EvaluationContractError("unsupported evaluation schema")
        # Integrity: metrics and leakage must match the cases.
        recomputed_findings = detect_cross_partition_leakage(self.cases)
        if len(recomputed_findings) != len(self.leakage_findings):
            raise EvaluationIntegrityError(
                "leakage_findings do not match recomputed leakage detection"
            )
        recomputed_metrics = aggregate_metrics(
            self.cases, leakage_findings=self.leakage_findings
        )
        if recomputed_metrics.to_dict() != self.metrics.to_dict():
            raise EvaluationIntegrityError(
                "metrics do not match recomputed case aggregation"
            )
        computed = self.identity
        if self.evaluation_cid and self.evaluation_cid != computed:
            raise EvaluationIntegrityError(
                "evaluation_cid does not match rehashed evaluation"
            )
        object.__setattr__(self, "evaluation_cid", computed)

    @property
    def identity(self) -> str:
        return _identity(
            self.deterministic_dict(),
            "report",
            EVALUATION_SCHEMA_VERSION,
        )

    @property
    def control_kinds_covered(self) -> tuple[str, ...]:
        return tuple(
            sorted({item.control_kind.value for item in self.cases})
        )

    @property
    def false_proof_count(self) -> int:
        return sum(
            1
            for item in self.cases
            if item.prover_outcome is ProverOutcomeKind.PROOF
            and not item.counts_as_proof
        )

    @property
    def metrics_complete(self) -> bool:
        wire = self.metrics.to_dict()
        required = {item.value for item in MetricSliceName}
        # Map metric slice names onto wire keys present in SeparateMetricReport.
        present = {
            "leakage" if "leakage_count" in wire else "",
            "retrieval_accuracy" if "retrieval_accuracy" in wire else "",
            "graph_path_validity" if "graph_path_validity" in wire else "",
            "attribution" if "attribution" in wire else "",
            "latency" if "mean_latency_ms" in wire else "",
            "memory" if "peak_memory_bytes" in wire else "",
            "schema_validity" if "schema_validity" in wire else "",
            "source_span_grounding" if "source_span_grounding" in wire else "",
            "obligation_coverage" if "obligation_coverage" in wire else "",
            "executable_lowering" if "executable_lowering" in wire else "",
            "prover_outcomes" if "prover_outcomes" in wire else "",
            "calibration" if "calibration" in wire else "",
            "abstention" if "abstention_rate" in wire else "",
            "unsupported_coverage" if "unsupported_coverage" in wire else "",
            "uncertainty" if "uncertainty_rate" in wire else "",
        }
        present.discard("")
        return required <= present

    def promotion_gate(self) -> PromotionGate:
        external_ok = (
            True
            if self.external_label_admission is None
            else self.external_label_admission.admitted
        )
        diagnostics: list[str] = list(self.diagnostics)
        if self.metrics.leakage_count:
            diagnostics.append("cross_partition_or_source_family_leakage")
        if self.false_proof_count:
            diagnostics.append("non_executable_proof_claims_present")
        if not external_ok:
            diagnostics.append("external_label_corpus_not_admitted")
        if not self.metrics_complete:
            diagnostics.append("metric_slices_incomplete")
        return PromotionGate(
            evaluation_cid=self.evaluation_cid,
            leakage_count=self.metrics.leakage_count,
            false_proof_count=self.false_proof_count,
            authority_violation_count=0,
            external_label_admitted=external_ok,
            controls_covered=self.control_kinds_covered,
            metrics_complete=self.metrics_complete,
            diagnostics=tuple(diagnostics),
        )

    def require_promotion_safe(self) -> SolidityFormalEvaluation:
        self.promotion_gate().require_passed()
        if self.metrics.leakage_count != 0:
            raise EvaluationLeakageError(
                "evaluation reports non-zero leakage"
            )
        return self

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "cases": [item.to_dict() for item in self.cases],
            "diagnostics": list(self.diagnostics),
            "evaluation_partitions": list(self.evaluation_partitions),
            "external_label_admission": (
                None
                if self.external_label_admission is None
                else self.external_label_admission.to_dict()
            ),
            "graph_cid": self.graph_cid,
            "index_cid": self.index_cid,
            "leakage_findings": [dict(item) for item in self.leakage_findings],
            "learned_output_authority": CANDIDATE_AUTHORITY,
            "license_cid": self.license_cid,
            "metrics": self.metrics.to_dict(),
            "mode": self.mode.value,
            "model_or_checkpoint_cid": self.model_or_checkpoint_cid,
            "partition_cid": self.partition_cid,
            "proof_authority": False,
            "prover_agreements": [item.to_dict() for item in self.prover_agreements],
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "transaction_authority": False,
        }

    def to_dict(self) -> dict[str, Any]:
        result = {
            "evaluation_cid": self.evaluation_cid,
            "promotion_gate": self.promotion_gate().to_dict(),
            **self.deterministic_dict(),
        }
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SolidityFormalEvaluation:
        value = _mapping(value, "evaluation")
        # promotion_gate is derived; accept but do not require on the wire.
        payload = dict(value)
        payload.pop("promotion_gate", None)
        return cls(
            source_cid=payload.get("source_cid", ""),
            graph_cid=payload.get("graph_cid", ""),
            index_cid=payload.get("index_cid", ""),
            partition_cid=payload.get("partition_cid", ""),
            license_cid=payload.get("license_cid", ""),
            model_or_checkpoint_cid=payload.get("model_or_checkpoint_cid", ""),
            evaluation_partitions=tuple(payload.get("evaluation_partitions", ())),
            cases=tuple(payload.get("cases", ())),
            metrics=payload.get("metrics", {}),
            leakage_findings=tuple(payload.get("leakage_findings", ())),
            prover_agreements=tuple(payload.get("prover_agreements", ())),
            external_label_admission=payload.get("external_label_admission"),
            mode=payload.get("mode", EvaluationMode.DRY_RUN),
            diagnostics=tuple(payload.get("diagnostics", ())),
            proof_authority=payload.get("proof_authority", False),
            transaction_authority=payload.get("transaction_authority", False),
            learned_output_authority=payload.get(
                "learned_output_authority", CANDIDATE_AUTHORITY
            ),
            schema_version=payload.get(
                "schema_version", EVALUATION_SCHEMA_VERSION
            ),
            evaluation_cid=payload.get("evaluation_cid", ""),
        )


def build_evaluation_case(
    case_id: str,
    *,
    partition: str,
    control_kind: ControlKind | str,
    source_family_id: str,
    claim_kind: ClaimKind | str = ClaimKind.UNEXECUTED,
    prover_outcome: ProverOutcomeKind | str = ProverOutcomeKind.UNKNOWN,
    expected_abstention: bool = False,
    abstained: bool | None = None,
    schema_valid: bool = True,
    source_span_grounded: bool = True,
    obligation_covered: bool = True,
    executable_lowering_ok: bool = True,
    graph_path_valid: bool = True,
    retrieval_hit: bool = True,
    attribution_correct: bool = True,
    confidence: float = 0.5,
    correct: bool = True,
    latency_ms: float = 1.0,
    peak_memory_bytes: int = 1024,
    unsupported: bool = False,
    uncertainty_flag: bool = False,
    claim_executed: bool = False,
    claim_authoritative: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> EvaluationCase:
    """Construct one validated evaluation case with safe defaults."""

    kind = _enum(ControlKind, control_kind, "control_kind")
    if abstained is None:
        abstained = expected_abstention
    return EvaluationCase(
        case_id=case_id,
        partition=partition,
        control_kind=kind,
        source_family_id=source_family_id,
        claim_kind=claim_kind,
        prover_outcome=prover_outcome,
        expected_abstention=expected_abstention,
        abstained=abstained,
        schema_valid=schema_valid,
        source_span_grounded=source_span_grounded,
        obligation_covered=obligation_covered,
        executable_lowering_ok=executable_lowering_ok,
        graph_path_valid=graph_path_valid,
        retrieval_hit=retrieval_hit,
        attribution_correct=attribution_correct,
        confidence=confidence,
        correct=correct,
        latency_ms=latency_ms,
        peak_memory_bytes=peak_memory_bytes,
        unsupported=unsupported,
        uncertainty_flag=uncertainty_flag,
        claim_executed=claim_executed,
        claim_authoritative=claim_authoritative,
        metadata=metadata or {},
    )


def build_offline_fixture_cases() -> tuple[EvaluationCase, ...]:
    """Deterministic held-out and adversarial fixtures covering every control."""

    cases = (
        build_evaluation_case(
            "case:held-out:grounded",
            partition=HELD_OUT_PARTITION,
            control_kind=ControlKind.HELD_OUT,
            source_family_id="family:held-out-a",
            claim_kind=ClaimKind.EXECUTABLE_PROOF,
            prover_outcome=ProverOutcomeKind.PROOF,
            claim_executed=True,
            claim_authoritative=True,
            confidence=0.9,
            correct=True,
            latency_ms=2.0,
            peak_memory_bytes=2048,
        ),
        build_evaluation_case(
            "case:poisoned:prompt-injection",
            partition=ADVERSARIAL_PARTITION,
            control_kind=ControlKind.POISONED_TEXT,
            source_family_id="family:poisoned",
            claim_kind=ClaimKind.MODEL,
            prover_outcome=ProverOutcomeKind.UNKNOWN,
            expected_abstention=True,
            abstained=True,
            confidence=0.1,
            correct=True,
            uncertainty_flag=True,
            metadata={"reason": "poisoned_text_control"},
        ),
        build_evaluation_case(
            "case:prompt-like:ignore-previous",
            partition=ADVERSARIAL_PARTITION,
            control_kind=ControlKind.PROMPT_LIKE,
            source_family_id="family:prompt-like",
            claim_kind=ClaimKind.MODEL,
            prover_outcome=ProverOutcomeKind.UNKNOWN,
            expected_abstention=True,
            abstained=True,
            confidence=0.05,
            correct=True,
            uncertainty_flag=True,
        ),
        build_evaluation_case(
            "case:license:ambiguous",
            partition=ADVERSARIAL_PARTITION,
            control_kind=ControlKind.AMBIGUOUS_LICENSE,
            source_family_id="family:ambiguous-license",
            claim_kind=ClaimKind.UNEXECUTED,
            prover_outcome=ProverOutcomeKind.UNAVAILABLE,
            expected_abstention=True,
            abstained=True,
            confidence=0.0,
            correct=True,
            unsupported=True,
        ),
        build_evaluation_case(
            "case:syntax:unsupported-assembly",
            partition=ADVERSARIAL_PARTITION,
            control_kind=ControlKind.UNSUPPORTED_SYNTAX,
            source_family_id="family:unsupported-syntax",
            claim_kind=ClaimKind.UNEXECUTED,
            prover_outcome=ProverOutcomeKind.UNKNOWN,
            expected_abstention=True,
            abstained=True,
            executable_lowering_ok=False,
            unsupported=True,
            uncertainty_flag=True,
            confidence=0.2,
            correct=True,
        ),
        build_evaluation_case(
            "case:mismatch:compiler-source-deploy",
            partition=ADVERSARIAL_PARTITION,
            control_kind=ControlKind.COMPILER_SOURCE_DEPLOYMENT_MISMATCH,
            source_family_id="family:mismatch",
            claim_kind=ClaimKind.UNEXECUTED,
            prover_outcome=ProverOutcomeKind.UNAVAILABLE,
            expected_abstention=True,
            abstained=True,
            schema_valid=True,
            source_span_grounded=False,
            confidence=0.0,
            correct=True,
            uncertainty_flag=True,
        ),
        build_evaluation_case(
            "case:mutation:semantic-edit",
            partition=ADVERSARIAL_PARTITION,
            control_kind=ControlKind.MUTATION,
            source_family_id="family:mutation",
            claim_kind=ClaimKind.SIMULATION,
            prover_outcome=ProverOutcomeKind.DISPROOF,
            confidence=0.7,
            correct=True,
            latency_ms=3.0,
            peak_memory_bytes=4096,
            metadata={"mutation": "rename_and_reorder"},
        ),
        build_evaluation_case(
            "case:corrupt:graph-index",
            partition=ADVERSARIAL_PARTITION,
            control_kind=ControlKind.CORRUPT_GRAPH_INDEX,
            source_family_id="family:corrupt",
            claim_kind=ClaimKind.UNEXECUTED,
            prover_outcome=ProverOutcomeKind.UNAVAILABLE,
            expected_abstention=True,
            abstained=True,
            graph_path_valid=False,
            retrieval_hit=False,
            attribution_correct=False,
            confidence=0.0,
            correct=True,
            uncertainty_flag=True,
        ),
        build_evaluation_case(
            "case:cross-solver:disagreement",
            partition=TEST_PARTITION,
            control_kind=ControlKind.CROSS_SOLVER,
            source_family_id="family:cross-solver",
            claim_kind=ClaimKind.EXECUTABLE_PROOF,
            prover_outcome=ProverOutcomeKind.DISAGREEMENT,
            claim_executed=True,
            claim_authoritative=True,
            confidence=0.4,
            correct=True,
            uncertainty_flag=True,
            latency_ms=5.0,
            peak_memory_bytes=8192,
        ),
        build_evaluation_case(
            "case:validation:sat-not-proof",
            partition=VALIDATION_PARTITION,
            control_kind=ControlKind.HELD_OUT,
            source_family_id="family:validation-sat",
            claim_kind=ClaimKind.SAT,
            # SAT must never be recorded as proof; use unknown.
            prover_outcome=ProverOutcomeKind.UNKNOWN,
            confidence=0.6,
            correct=True,
            uncertainty_flag=True,
            metadata={"note": "sat_is_not_proof"},
        ),
        build_evaluation_case(
            "case:validation:approximate-not-proof",
            partition=VALIDATION_PARTITION,
            control_kind=ControlKind.HELD_OUT,
            source_family_id="family:validation-approx",
            claim_kind=ClaimKind.APPROXIMATE,
            prover_outcome=ProverOutcomeKind.UNKNOWN,
            confidence=0.55,
            correct=True,
            uncertainty_flag=True,
            metadata={"note": "approximate_is_not_proof"},
        ),
        build_evaluation_case(
            "case:held-out:timeout",
            partition=HELD_OUT_PARTITION,
            control_kind=ControlKind.HELD_OUT,
            source_family_id="family:held-out-b",
            claim_kind=ClaimKind.EXECUTABLE_PROOF,
            prover_outcome=ProverOutcomeKind.TIMEOUT,
            claim_executed=True,
            claim_authoritative=True,
            confidence=0.3,
            correct=True,
            uncertainty_flag=True,
            latency_ms=10.0,
            peak_memory_bytes=16384,
        ),
    )
    return cases


def build_offline_fixture_agreements() -> tuple[ProverAgreement, ...]:
    """Cross-solver fixture covering agreement and disagreement paths."""

    return (
        ProverAgreement.from_solver_outcomes(
            "case:cross-solver:disagreement",
            {
                "z3": ProverOutcomeKind.PROOF,
                "cvc5": ProverOutcomeKind.UNKNOWN,
            },
        ),
        ProverAgreement.from_solver_outcomes(
            "case:held-out:grounded",
            {
                "z3": ProverOutcomeKind.PROOF,
                "cvc5": ProverOutcomeKind.PROOF,
            },
        ),
    )


def build_offline_fixture_evaluation(
    *,
    mode: EvaluationMode | str = EvaluationMode.FIXTURE_OFFLINE,
) -> SolidityFormalEvaluation:
    """Return the deterministic offline evaluation used by CLI and unit tests."""

    cases = build_offline_fixture_cases()
    findings = detect_cross_partition_leakage(cases)
    metrics = aggregate_metrics(cases, leakage_findings=findings)
    external = ExternalLabelCorpusAdmission(
        corpus_id="offline-fixture/no-external-labels",
        pin_cid=_fixture_cid("external-pin"),
        license_cid=_fixture_cid("external-license"),
        leakage_admission=True,
        license_admitted=True,
        pin_verified=True,
        diagnostics=("no_external_label_corpus_required_for_fixture",),
    )
    return SolidityFormalEvaluation(
        source_cid=_fixture_cid("source"),
        graph_cid=_fixture_cid("graph"),
        index_cid=_fixture_cid("index"),
        partition_cid=_fixture_cid("partition"),
        license_cid=_fixture_cid("license"),
        model_or_checkpoint_cid=_fixture_cid("checkpoint"),
        evaluation_partitions=DEFAULT_EVALUATION_PARTITIONS,
        cases=cases,
        metrics=metrics,
        leakage_findings=findings,
        prover_agreements=build_offline_fixture_agreements(),
        external_label_admission=external,
        mode=mode,
        diagnostics=(
            "fixture_offline_multi_metric_evaluation",
            "uncertainty_and_unsupported_reported_separately",
            "no_single_accuracy_score",
        ),
    )


class SolidityFormalEvaluator:
    """Aggregate validated cases into a CID-bound evaluation receipt."""

    version: Final = EVALUATION_SCHEMA_VERSION

    def __init__(
        self,
        *,
        source_cid: str,
        graph_cid: str,
        index_cid: str,
        partition_cid: str,
        license_cid: str,
        model_or_checkpoint_cid: str,
        evaluation_partitions: Sequence[str] = DEFAULT_EVALUATION_PARTITIONS,
        external_label_admission: ExternalLabelCorpusAdmission | None = None,
        mode: EvaluationMode | str = EvaluationMode.DRY_RUN,
        diagnostics: Sequence[str] = (),
    ) -> None:
        self.source_cid = source_cid
        self.graph_cid = graph_cid
        self.index_cid = index_cid
        self.partition_cid = partition_cid
        self.license_cid = license_cid
        self.model_or_checkpoint_cid = model_or_checkpoint_cid
        self.evaluation_partitions = tuple(evaluation_partitions)
        self.external_label_admission = external_label_admission
        self.mode = mode
        self.diagnostics = tuple(diagnostics)

    def evaluate(
        self,
        cases: Sequence[EvaluationCase | Mapping[str, Any]],
        *,
        prover_agreements: Sequence[
            ProverAgreement | Mapping[str, Any]
        ] = (),
    ) -> SolidityFormalEvaluation:
        normalized: list[EvaluationCase] = []
        for item in cases:
            if isinstance(item, EvaluationCase):
                normalized.append(item)
            else:
                normalized.append(EvaluationCase.from_dict(_mapping(item, "case")))
        findings = detect_cross_partition_leakage(normalized)
        metrics = aggregate_metrics(normalized, leakage_findings=findings)
        return SolidityFormalEvaluation(
            source_cid=self.source_cid,
            graph_cid=self.graph_cid,
            index_cid=self.index_cid,
            partition_cid=self.partition_cid,
            license_cid=self.license_cid,
            model_or_checkpoint_cid=self.model_or_checkpoint_cid,
            evaluation_partitions=self.evaluation_partitions,
            cases=tuple(normalized),
            metrics=metrics,
            leakage_findings=findings,
            prover_agreements=tuple(prover_agreements),
            external_label_admission=self.external_label_admission,
            mode=self.mode,
            diagnostics=self.diagnostics,
        )


def evaluate_solidity_formalizer(
    cases: Sequence[EvaluationCase | Mapping[str, Any]],
    *,
    source_cid: str,
    graph_cid: str,
    index_cid: str,
    partition_cid: str,
    license_cid: str,
    model_or_checkpoint_cid: str,
    evaluation_partitions: Sequence[str] = DEFAULT_EVALUATION_PARTITIONS,
    prover_agreements: Sequence[ProverAgreement | Mapping[str, Any]] = (),
    external_label_admission: ExternalLabelCorpusAdmission | None = None,
    mode: EvaluationMode | str = EvaluationMode.DRY_RUN,
    diagnostics: Sequence[str] = (),
) -> SolidityFormalEvaluation:
    """Convenience entry point for multi-metric Solidity formalizer evaluation."""

    return SolidityFormalEvaluator(
        source_cid=source_cid,
        graph_cid=graph_cid,
        index_cid=index_cid,
        partition_cid=partition_cid,
        license_cid=license_cid,
        model_or_checkpoint_cid=model_or_checkpoint_cid,
        evaluation_partitions=evaluation_partitions,
        external_label_admission=external_label_admission,
        mode=mode,
        diagnostics=diagnostics,
    ).evaluate(cases, prover_agreements=prover_agreements)


def verify_evaluation_receipt(
    value: Mapping[str, Any] | SolidityFormalEvaluation,
) -> SolidityFormalEvaluation:
    """Reparse and rehash an evaluation receipt, failing closed on drift."""

    if isinstance(value, SolidityFormalEvaluation):
        parsed = SolidityFormalEvaluation.from_dict(value.to_dict())
    else:
        parsed = SolidityFormalEvaluation.from_dict(value)
    if parsed.evaluation_cid != parsed.identity:
        raise EvaluationIntegrityError("evaluation receipt rehash mismatch")
    return parsed


__all__ = [
    "CANDIDATE_AUTHORITY",
    "CalibrationMetrics",
    "ClaimKind",
    "ControlKind",
    "DEFAULT_EVALUATION_PARTITIONS",
    "EVALUATION_SCHEMA_VERSION",
    "EvaluationAuthorityError",
    "EvaluationCase",
    "EvaluationContractError",
    "EvaluationIntegrityError",
    "EvaluationLeakageError",
    "EvaluationMode",
    "EvaluationPromotionError",
    "ExternalLabelCorpusAdmission",
    "MetricSliceName",
    "NON_PROOF_CLAIM_KINDS",
    "PromotionGate",
    "ProverAgreement",
    "ProverOutcomeCounts",
    "ProverOutcomeKind",
    "SeparateMetricReport",
    "SolidityFormalEvaluation",
    "SolidityFormalEvaluator",
    "aggregate_metrics",
    "build_evaluation_case",
    "build_offline_fixture_agreements",
    "build_offline_fixture_cases",
    "build_offline_fixture_evaluation",
    "compute_calibration",
    "counts_as_executable_proof",
    "detect_cross_partition_leakage",
    "evaluate_solidity_formalizer",
    "verify_evaluation_receipt",
]
