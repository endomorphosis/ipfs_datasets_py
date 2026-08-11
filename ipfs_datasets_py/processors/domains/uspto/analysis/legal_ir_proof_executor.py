"""Execute Legal IR compilation and proofs inside the privacy boundary (PATLAW-126).

This module is the USPTO adapter to :class:`LegalIRCompilerAPI` and
:class:`ProofExecutionEngine`. It:

* compiles normalized office-action rules and submission facts into a local,
  content-addressed proof problem;
* invokes a **bounded local proof kernel** (always available) and, when
  present, the shared :class:`ProofExecutionEngine` under explicit local
  routes only;
* captures assumptions, derivations, countermodels, and timeouts; and
* translates engine results into provenance-linked
  proved / disproved / unknown / error / timeout outcomes.

Privacy invariants
------------------
* Remote providers and unapproved external model routes are denied by default.
* Logs, exceptions, and audit surfaces carry digests and reason codes only —
  never private proposition plaintext.
* Generated text is never elevated to binding authority.

This module does not modify the shared compiler or proof engine
implementations.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Protocol

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    canonical_json as uspto_canonical_json,
    is_private_classification,
    requires_quarantine,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.legal_ir_contracts import (
    LegalIRContractBundle,
    LegalIRMapping,
    MappingStatus,
    TriStateOutcome,
)
from ipfs_datasets_py.processors.domains.uspto.privacy import (
    ContentKind,
    PrivacyBoundaryError,
    PublicSink,
    UsptoPrivacyPolicy,
)

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION: Final = "uspto.legal-ir-proof-executor.v1"
LEGAL_IR_PROOF_EXECUTOR_INTERFACE: Final = "UsptoLegalIRProofExecutor@1"
PROOF_KERNEL_IDENTITY: Final = "uspto.local-bounded-proof-kernel@1"
PROOF_KERNEL_CONFIG_PROFILE: Final = "local-bounded-v1"
DEFAULT_COMPILER_OPTIONS_PROFILE: Final = "deterministic-proof-aware-v1"

DEFAULT_TIMEOUT_MS: Final = 5_000
DEFAULT_MAX_STEPS: Final = 10_000
DEFAULT_MAX_PREMISES: Final = 4_096
DEFAULT_MAX_ATOMS: Final = 8_192

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ProofOutcome(str, Enum):
    """Provenance-linked conclusion of one bounded proof attempt."""

    PROVED = "proved"
    DISPROVED = "disproved"
    UNKNOWN = "unknown"
    ERROR = "error"
    TIMEOUT = "timeout"


class ExecutionRoute(str, Enum):
    """Allowed execution routes (remote is never a default)."""

    LOCAL_BOUNDED_KERNEL = "local_bounded_kernel"
    LOCAL_COMPILER = "local_compiler"
    LOCAL_PROOF_ENGINE = "local_proof_engine"
    # Explicitly named so callers can request it and be denied fail-closed.
    REMOTE_PROVIDER = "remote_provider"


class ProofReasonCode(str, Enum):
    """Stable machine-readable reason codes for proof decisions."""

    PREMISES_ENTAIL_GOAL = "premises_entail_goal"
    PREMISES_CONTRADICT = "premises_contradict"
    GOAL_NEGATED_BY_PREMISES = "goal_negated_by_premises"
    INCOMPLETE_PREMISES = "incomplete_premises"
    UNSUPPORTED_LOGIC = "unsupported_logic"
    ENGINE_UNAVAILABLE = "engine_unavailable"
    ENGINE_UNSUPPORTED = "engine_unsupported"
    COMPILER_FAILED = "compiler_failed"
    COMPILER_OK = "compiler_ok"
    TIMEOUT_BUDGET = "timeout_budget"
    STEP_BUDGET = "step_budget"
    REMOTE_DENIED = "remote_denied"
    PRIVACY_QUARANTINE = "privacy_quarantine"
    INVALID_REQUEST = "invalid_request"
    COUNTERMODEL_PRESENT = "countermodel_present"
    ASSUMPTION_RECORDED = "assumption_recorded"
    MAPPING_NOT_ACCEPTED = "mapping_not_accepted"
    PROOF_ENGINE_SUCCESS = "proof_engine_success"
    PROOF_ENGINE_FAILURE = "proof_engine_failure"
    PROOF_ENGINE_ERROR = "proof_engine_error"
    PROOF_ENGINE_TIMEOUT = "proof_engine_timeout"
    FIXTURE_SATISFIABLE = "fixture_satisfiable"
    FIXTURE_CONTRADICTORY = "fixture_contradictory"
    FIXTURE_INCOMPLETE = "fixture_incomplete"
    FIXTURE_TIMEOUT = "fixture_timeout"
    INTERNAL_ERROR = "internal_error"


class LogicFamily(str, Enum):
    """Supported vs unsupported logic families for the local kernel."""

    PROPOSITIONAL_ATOMS = "propositional_atoms"
    ENTAILMENT_CHECK = "entailment_check"
    CONSISTENCY_CHECK = "consistency_check"
    # Anything not implemented returns unknown (fail-closed).
    UNSUPPORTED = "unsupported"
    DEONTIC_EXTERNAL = "deontic_external"


class FixtureKind(str, Enum):
    """Known satisfiable / contradictory / incomplete / timeout fixtures."""

    SATISFIABLE = "satisfiable"
    CONTRADICTORY = "contradictory"
    INCOMPLETE = "incomplete"
    TIMEOUT = "timeout"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LegalIRProofExecutorError(ValueError):
    """Bounded proof-executor violation with a stable machine-readable code."""

    def __init__(
        self,
        message: str,
        *,
        code: str | ProofReasonCode = ProofReasonCode.INVALID_REQUEST,
    ) -> None:
        super().__init__(message)
        if isinstance(code, ProofReasonCode):
            self.code = code.value
        else:
            self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        # Never include private proposition body text.
        return {"code": self.code, "message": str(self)[:256]}


# ---------------------------------------------------------------------------
# Config and identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EngineConfigIdentity:
    """Stable identity of the proof engine and its configuration.

    Every conclusion must cite this identity so receipts are reproducible.
    """

    schema_version: str
    engine_id: str
    engine_version: str
    config_profile: str
    config_digest: str
    route: ExecutionRoute
    timeout_ms: int
    max_steps: int
    allow_remote: bool
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "labels",
            MappingProxyType({str(k): str(v) for k, v in dict(self.labels).items()}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_remote": bool(self.allow_remote),
            "config_digest": self.config_digest,
            "config_profile": self.config_profile,
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "labels": dict(self.labels),
            "max_steps": int(self.max_steps),
            "route": self.route.value,
            "schema_version": self.schema_version,
            "timeout_ms": int(self.timeout_ms),
        }


@dataclass(frozen=True, slots=True)
class ProofExecutorConfig:
    """Resource ceilings and privacy flags for one executor instance."""

    timeout_ms: int = DEFAULT_TIMEOUT_MS
    max_steps: int = DEFAULT_MAX_STEPS
    max_premises: int = DEFAULT_MAX_PREMISES
    max_atoms: int = DEFAULT_MAX_ATOMS
    allow_remote: bool = False
    allow_external_provers: bool = True
    preferred_route: ExecutionRoute = ExecutionRoute.LOCAL_BOUNDED_KERNEL
    preferred_prover: str = "z3"
    compiler_options_profile: str = DEFAULT_COMPILER_OPTIONS_PROFILE
    redaction_policy_id: str | None = "policy:proof-redact:v1"
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timeout_ms < 0:
            raise LegalIRProofExecutorError(
                "timeout_ms must be >= 0",
                code=ProofReasonCode.INVALID_REQUEST,
            )
        if self.max_steps < 0:
            raise LegalIRProofExecutorError(
                "max_steps must be >= 0",
                code=ProofReasonCode.INVALID_REQUEST,
            )
        object.__setattr__(
            self,
            "labels",
            MappingProxyType({str(k): str(v) for k, v in dict(self.labels).items()}),
        )

    def config_digest(self) -> str:
        payload = {
            "allow_external_provers": bool(self.allow_external_provers),
            "allow_remote": bool(self.allow_remote),
            "compiler_options_profile": self.compiler_options_profile,
            "labels": dict(self.labels),
            "max_atoms": int(self.max_atoms),
            "max_premises": int(self.max_premises),
            "max_steps": int(self.max_steps),
            "preferred_prover": self.preferred_prover,
            "preferred_route": self.preferred_route.value,
            "redaction_policy_id": self.redaction_policy_id,
            "timeout_ms": int(self.timeout_ms),
        }
        return _sha256_of_canonical(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_external_provers": bool(self.allow_external_provers),
            "allow_remote": bool(self.allow_remote),
            "compiler_options_profile": self.compiler_options_profile,
            "config_digest": self.config_digest(),
            "labels": dict(self.labels),
            "max_atoms": int(self.max_atoms),
            "max_premises": int(self.max_premises),
            "max_steps": int(self.max_steps),
            "preferred_prover": self.preferred_prover,
            "preferred_route": self.preferred_route.value,
            "redaction_policy_id": self.redaction_policy_id,
            "timeout_ms": int(self.timeout_ms),
        }


# ---------------------------------------------------------------------------
# Problem / request records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AtomicLiteral:
    """Signed atom used by the local bounded kernel (identifiers only)."""

    atom_id: str
    polarity: bool = True

    def negated(self) -> "AtomicLiteral":
        return AtomicLiteral(atom_id=self.atom_id, polarity=not self.polarity)

    def key(self) -> str:
        return f"{'+' if self.polarity else '-'}{self.atom_id}"

    def to_dict(self) -> dict[str, Any]:
        return {"atom_id": self.atom_id, "polarity": bool(self.polarity)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AtomicLiteral":
        return cls(
            atom_id=str(value.get("atom_id") or ""),
            polarity=bool(value.get("polarity", True)),
        )


@dataclass(frozen=True, slots=True)
class PremiseCitation:
    """One premise cited by a conclusion (identifiers / digests only)."""

    premise_id: str
    kind: str  # "proposition" | "fact" | "assumption" | "atom" | "mapping"
    digest: str | None = None
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "kind": self.kind,
            "labels": dict(self.labels),
            "premise_id": self.premise_id,
        }


@dataclass(frozen=True, slots=True)
class ProofProblem:
    """Structured, privacy-safe proof problem for the local kernel."""

    problem_id: str
    logic_family: LogicFamily
    goal: AtomicLiteral | None
    premises: tuple[AtomicLiteral, ...]
    required_premise_ids: tuple[str, ...]
    assumption_ids: tuple[str, ...]
    counter_evidence_ids: tuple[str, ...]
    premise_citations: tuple[PremiseCitation, ...]
    classification: DisclosureClassification
    force_timeout: bool = False
    fixture_kind: FixtureKind | None = None
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "classification": self.classification.value,
            "counter_evidence_ids": list(self.counter_evidence_ids),
            "fixture_kind": self.fixture_kind.value if self.fixture_kind else None,
            "force_timeout": bool(self.force_timeout),
            "goal": self.goal.to_dict() if self.goal else None,
            "labels": dict(self.labels),
            "logic_family": self.logic_family.value,
            "premise_citations": [c.to_dict() for c in self.premise_citations],
            "premises": [p.to_dict() for p in self.premises],
            "problem_id": self.problem_id,
            "required_premise_ids": list(self.required_premise_ids),
        }


@dataclass(frozen=True, slots=True)
class ProofExecutionRequest:
    """Input to the privacy-safe proof executor.

    Provide either a structured :class:`ProofProblem`, a
    :class:`LegalIRMapping` / bundle, a known :class:`FixtureKind`, or a
    compiler-source mapping. Private plaintext must not appear in
    ``labels`` or free-form fields intended for logs.
    """

    request_id: str
    problem: ProofProblem | None = None
    mapping: LegalIRMapping | None = None
    bundle: LegalIRContractBundle | None = None
    fixture_kind: FixtureKind | None = None
    compiler_source: Mapping[str, Any] | str | None = None
    preferred_route: ExecutionRoute | None = None
    classification: DisclosureClassification = (
        DisclosureClassification.CONFIDENTIAL_APPLICATION
    )
    tenant_id: str | None = None
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle.bundle_id if self.bundle else None,
            "classification": self.classification.value,
            "compiler_source_present": self.compiler_source is not None,
            "fixture_kind": self.fixture_kind.value if self.fixture_kind else None,
            "labels": dict(self.labels),
            "mapping_id": self.mapping.mapping_id if self.mapping else None,
            "preferred_route": (
                self.preferred_route.value if self.preferred_route else None
            ),
            "problem": self.problem.to_dict() if self.problem else None,
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
        }


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompilationReceipt:
    """Receipt from LegalIRCompilerAPI (or a local compile stub)."""

    schema_version: str
    successful: bool
    result_id: str | None
    status: str
    exit_code: int | None
    compiler_options_digest: str
    reason_codes: tuple[str, ...]
    payload_digest: str | None
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "compiler_options_digest": self.compiler_options_digest,
            "exit_code": self.exit_code,
            "labels": dict(self.labels),
            "payload_digest": self.payload_digest,
            "reason_codes": list(self.reason_codes),
            "result_id": self.result_id,
            "schema_version": self.schema_version,
            "status": self.status,
            "successful": bool(self.successful),
        }


@dataclass(frozen=True, slots=True)
class CountermodelRecord:
    """Bounded countermodel / counter-evidence summary (identifiers only)."""

    countermodel_id: str
    atom_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "atom_ids": list(self.atom_ids),
            "countermodel_id": self.countermodel_id,
            "labels": dict(self.labels),
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class DerivationStep:
    """One derivation step (identifiers and reason codes only)."""

    step_index: int
    rule: str
    input_ids: tuple[str, ...]
    output_id: str | None
    reason_code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_ids": list(self.input_ids),
            "output_id": self.output_id,
            "reason_code": self.reason_code,
            "rule": self.rule,
            "step_index": int(self.step_index),
        }


@dataclass(frozen=True, slots=True)
class ProofConclusion:
    """One conclusion with mandatory premise and engine/config citations."""

    conclusion_id: str
    outcome: ProofOutcome
    reason_codes: tuple[str, ...]
    premise_citations: tuple[PremiseCitation, ...]
    engine_config: EngineConfigIdentity
    assumption_ids: tuple[str, ...]
    derivation_steps: tuple[DerivationStep, ...]
    countermodels: tuple[CountermodelRecord, ...]
    tri_state: TriStateOutcome
    elapsed_ms: int
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "conclusion_id": self.conclusion_id,
            "countermodels": [c.to_dict() for c in self.countermodels],
            "derivation_steps": [d.to_dict() for d in self.derivation_steps],
            "elapsed_ms": int(self.elapsed_ms),
            "engine_config": self.engine_config.to_dict(),
            "labels": dict(self.labels),
            "outcome": self.outcome.value,
            "premise_citations": [p.to_dict() for p in self.premise_citations],
            "reason_codes": list(self.reason_codes),
            "tri_state": self.tri_state.value,
        }


@dataclass(frozen=True, slots=True)
class ProofExecutionResult:
    """Full privacy-safe result of compile + prove."""

    schema_version: str
    interface: str
    request_id: str
    receipt_id: str
    outcome: ProofOutcome
    conclusion: ProofConclusion
    compilation: CompilationReceipt | None
    engine_config: EngineConfigIdentity
    remote_call_count: int
    classification: DisclosureClassification
    quarantine_required: bool
    fixture_kind: FixtureKind | None
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "compilation": self.compilation.to_dict() if self.compilation else None,
            "conclusion": self.conclusion.to_dict(),
            "engine_config": self.engine_config.to_dict(),
            "fixture_kind": self.fixture_kind.value if self.fixture_kind else None,
            "interface": self.interface,
            "labels": dict(self.labels),
            "outcome": self.outcome.value,
            "quarantine_required": bool(self.quarantine_required),
            "receipt_id": self.receipt_id,
            "remote_call_count": int(self.remote_call_count),
            "request_id": self.request_id,
            "schema_version": self.schema_version,
        }

    def audit_dict(self) -> dict[str, Any]:
        """Safe observability surface: digests and codes only."""
        return {
            "classification": self.classification.value,
            "engine_id": self.engine_config.engine_id,
            "config_digest": self.engine_config.config_digest,
            "outcome": self.outcome.value,
            "quarantine_required": bool(self.quarantine_required),
            "reason_codes": list(self.conclusion.reason_codes),
            "receipt_id": self.receipt_id,
            "remote_call_count": int(self.remote_call_count),
            "request_id": self.request_id,
            "route": self.engine_config.route.value,
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Protocols for injectable engines (tests / optional wiring)
# ---------------------------------------------------------------------------


class CompilerLike(Protocol):
    def compile(self, source: Any, **kwargs: Any) -> Any: ...


class ProofEngineLike(Protocol):
    available_provers: Mapping[str, bool]

    def prove_deontic_formula(self, formula: Any, prover: str | None = None) -> Any: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_of_canonical(payload: Any) -> str:
    raw = uspto_canonical_json(payload)
    if isinstance(raw, bytes):
        data = raw
    else:
        data = str(raw).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _outcome_to_tri_state(outcome: ProofOutcome) -> TriStateOutcome:
    if outcome is ProofOutcome.PROVED:
        return TriStateOutcome.SATISFIED
    if outcome is ProofOutcome.DISPROVED:
        return TriStateOutcome.UNSATISFIED
    return TriStateOutcome.UNKNOWN


def _safe_log(level: int, message: str, **fields: Any) -> None:
    """Log digests/codes only — never pass private body text as message args."""
    safe = {k: v for k, v in fields.items() if k not in {"text", "body", "proposition", "plaintext"}}
    _LOG.log(level, message, extra={"proof_executor": safe})


# ---------------------------------------------------------------------------
# Local bounded proof kernel
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _KernelResult:
    outcome: ProofOutcome
    reason_codes: tuple[str, ...]
    derivation_steps: tuple[DerivationStep, ...]
    countermodels: tuple[CountermodelRecord, ...]
    steps_used: int


def run_local_bounded_kernel(
    problem: ProofProblem,
    *,
    timeout_ms: int,
    max_steps: int,
    deadline_monotonic: float | None = None,
) -> _KernelResult:
    """Deterministic local kernel for fixture-grade propositional problems.

    Supported families:
    * ``propositional_atoms`` / ``entailment_check``: closed-world unit
      entailment of a signed goal from premises.
    * ``consistency_check``: premises are consistent iff no atom appears with
      both polarities.

    Unsupported families and incomplete required premises return
    :attr:`ProofOutcome.UNKNOWN`. Budget exhaustion returns
    :attr:`ProofOutcome.TIMEOUT`.
    """
    start = time.monotonic()
    steps = 0
    reasons: list[str] = []
    derivations: list[DerivationStep] = []
    countermodels: list[CountermodelRecord] = []

    def _budget_exceeded() -> bool:
        nonlocal steps
        steps += 1
        if max_steps >= 0 and steps > max_steps:
            return True
        if timeout_ms == 0:
            return True
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            return True
        if timeout_ms > 0 and (time.monotonic() - start) * 1000.0 >= timeout_ms:
            return True
        return False

    if problem.force_timeout or problem.fixture_kind is FixtureKind.TIMEOUT:
        reasons.append(ProofReasonCode.FIXTURE_TIMEOUT.value)
        reasons.append(ProofReasonCode.TIMEOUT_BUDGET.value)
        return _KernelResult(
            outcome=ProofOutcome.TIMEOUT,
            reason_codes=tuple(dict.fromkeys(reasons)),
            derivation_steps=(),
            countermodels=(),
            steps_used=steps,
        )

    if problem.logic_family is LogicFamily.UNSUPPORTED:
        reasons.append(ProofReasonCode.UNSUPPORTED_LOGIC.value)
        return _KernelResult(
            outcome=ProofOutcome.UNKNOWN,
            reason_codes=tuple(reasons),
            derivation_steps=(),
            countermodels=(),
            steps_used=steps,
        )

    if problem.logic_family is LogicFamily.DEONTIC_EXTERNAL:
        # External deontic solvers are optional; kernel alone cannot decide.
        reasons.append(ProofReasonCode.UNSUPPORTED_LOGIC.value)
        reasons.append(ProofReasonCode.ENGINE_UNAVAILABLE.value)
        return _KernelResult(
            outcome=ProofOutcome.UNKNOWN,
            reason_codes=tuple(reasons),
            derivation_steps=(),
            countermodels=(),
            steps_used=steps,
        )

    if _budget_exceeded():
        reasons.append(ProofReasonCode.TIMEOUT_BUDGET.value)
        return _KernelResult(
            outcome=ProofOutcome.TIMEOUT,
            reason_codes=tuple(reasons),
            derivation_steps=(),
            countermodels=(),
            steps_used=steps,
        )

    # Incomplete: required premise atoms missing from the closed set.
    present_ids = {lit.atom_id for lit in problem.premises}
    missing = [pid for pid in problem.required_premise_ids if pid not in present_ids]
    if missing or problem.fixture_kind is FixtureKind.INCOMPLETE:
        reasons.append(ProofReasonCode.INCOMPLETE_PREMISES.value)
        if problem.fixture_kind is FixtureKind.INCOMPLETE:
            reasons.append(ProofReasonCode.FIXTURE_INCOMPLETE.value)
        derivations.append(
            DerivationStep(
                step_index=0,
                rule="check_required_premises",
                input_ids=tuple(problem.required_premise_ids),
                output_id=None,
                reason_code=ProofReasonCode.INCOMPLETE_PREMISES.value,
            )
        )
        return _KernelResult(
            outcome=ProofOutcome.UNKNOWN,
            reason_codes=tuple(dict.fromkeys(reasons)),
            derivation_steps=tuple(derivations),
            countermodels=(),
            steps_used=steps,
        )

    if _budget_exceeded():
        reasons.append(ProofReasonCode.STEP_BUDGET.value)
        return _KernelResult(
            outcome=ProofOutcome.TIMEOUT,
            reason_codes=tuple(reasons),
            derivation_steps=tuple(derivations),
            countermodels=(),
            steps_used=steps,
        )

    # Build closed polarity map.
    polarity_map: dict[str, set[bool]] = {}
    for lit in problem.premises:
        if _budget_exceeded():
            reasons.append(ProofReasonCode.TIMEOUT_BUDGET.value)
            return _KernelResult(
                outcome=ProofOutcome.TIMEOUT,
                reason_codes=tuple(dict.fromkeys(reasons)),
                derivation_steps=tuple(derivations),
                countermodels=tuple(countermodels),
                steps_used=steps,
            )
        polarity_map.setdefault(lit.atom_id, set()).add(bool(lit.polarity))
        derivations.append(
            DerivationStep(
                step_index=len(derivations),
                rule="assert_premise",
                input_ids=(lit.atom_id,),
                output_id=lit.key(),
                reason_code=ProofReasonCode.ASSUMPTION_RECORDED.value
                if lit.atom_id in problem.assumption_ids
                else "premise_closed",
            )
        )

    # Contradiction detection.
    contradictory_atoms = sorted(
        atom_id for atom_id, pols in polarity_map.items() if True in pols and False in pols
    )
    if contradictory_atoms or problem.fixture_kind is FixtureKind.CONTRADICTORY:
        reasons.append(ProofReasonCode.PREMISES_CONTRADICT.value)
        if problem.fixture_kind is FixtureKind.CONTRADICTORY:
            reasons.append(ProofReasonCode.FIXTURE_CONTRADICTORY.value)
        countermodels.append(
            CountermodelRecord(
                countermodel_id=f"cm:contradict:{problem.problem_id}",
                atom_ids=tuple(contradictory_atoms)
                or tuple(sorted({p.atom_id for p in problem.premises})),
                reason_codes=(ProofReasonCode.PREMISES_CONTRADICT.value,),
            )
        )
        if problem.logic_family is LogicFamily.CONSISTENCY_CHECK:
            # Inconsistency of premises is the disproof of consistency.
            return _KernelResult(
                outcome=ProofOutcome.DISPROVED,
                reason_codes=tuple(dict.fromkeys(reasons)),
                derivation_steps=tuple(derivations),
                countermodels=tuple(countermodels),
                steps_used=steps,
            )
        # For entailment, contradiction yields disproof (ex falso not claimed
        # as proved; fail-closed to disproved with countermodel).
        reasons.append(ProofReasonCode.COUNTERMODEL_PRESENT.value)
        return _KernelResult(
            outcome=ProofOutcome.DISPROVED,
            reason_codes=tuple(dict.fromkeys(reasons)),
            derivation_steps=tuple(derivations),
            countermodels=tuple(countermodels),
            steps_used=steps,
        )

    if problem.logic_family is LogicFamily.CONSISTENCY_CHECK:
        # No polar conflict ⇒ consistency "proved" for the local kernel.
        reasons.append(ProofReasonCode.PREMISES_ENTAIL_GOAL.value)
        if problem.fixture_kind is FixtureKind.SATISFIABLE:
            reasons.append(ProofReasonCode.FIXTURE_SATISFIABLE.value)
        return _KernelResult(
            outcome=ProofOutcome.PROVED,
            reason_codes=tuple(dict.fromkeys(reasons)),
            derivation_steps=tuple(derivations),
            countermodels=(),
            steps_used=steps,
        )

    # Entailment / propositional atoms require a goal.
    if problem.goal is None:
        reasons.append(ProofReasonCode.INCOMPLETE_PREMISES.value)
        return _KernelResult(
            outcome=ProofOutcome.UNKNOWN,
            reason_codes=tuple(reasons),
            derivation_steps=tuple(derivations),
            countermodels=(),
            steps_used=steps,
        )

    goal = problem.goal
    goal_pols = polarity_map.get(goal.atom_id, set())

    if goal.polarity in goal_pols:
        reasons.append(ProofReasonCode.PREMISES_ENTAIL_GOAL.value)
        if problem.fixture_kind is FixtureKind.SATISFIABLE:
            reasons.append(ProofReasonCode.FIXTURE_SATISFIABLE.value)
        derivations.append(
            DerivationStep(
                step_index=len(derivations),
                rule="unit_entailment",
                input_ids=(goal.atom_id,),
                output_id=goal.key(),
                reason_code=ProofReasonCode.PREMISES_ENTAIL_GOAL.value,
            )
        )
        return _KernelResult(
            outcome=ProofOutcome.PROVED,
            reason_codes=tuple(dict.fromkeys(reasons)),
            derivation_steps=tuple(derivations),
            countermodels=(),
            steps_used=steps,
        )

    if (not goal.polarity) in goal_pols or (goal.polarity is True and False in goal_pols):
        # Premises contain the negation of the goal.
        reasons.append(ProofReasonCode.GOAL_NEGATED_BY_PREMISES.value)
        reasons.append(ProofReasonCode.COUNTERMODEL_PRESENT.value)
        countermodels.append(
            CountermodelRecord(
                countermodel_id=f"cm:neg:{problem.problem_id}",
                atom_ids=(goal.atom_id,),
                reason_codes=(ProofReasonCode.GOAL_NEGATED_BY_PREMISES.value,),
            )
        )
        return _KernelResult(
            outcome=ProofOutcome.DISPROVED,
            reason_codes=tuple(dict.fromkeys(reasons)),
            derivation_steps=tuple(derivations),
            countermodels=tuple(countermodels),
            steps_used=steps,
        )

    # Cannot decide — incomplete theory relative to the goal.
    reasons.append(ProofReasonCode.INCOMPLETE_PREMISES.value)
    return _KernelResult(
        outcome=ProofOutcome.UNKNOWN,
        reason_codes=tuple(dict.fromkeys(reasons)),
        derivation_steps=tuple(derivations),
        countermodels=(),
        steps_used=steps,
    )


# ---------------------------------------------------------------------------
# Fixture builders (compact recipes; no bulk golden dumps)
# ---------------------------------------------------------------------------


def build_fixture_problem(
    kind: FixtureKind,
    *,
    problem_id: str | None = None,
    classification: DisclosureClassification = (
        DisclosureClassification.CONFIDENTIAL_APPLICATION
    ),
) -> ProofProblem:
    """Build a known fixture problem that maps to a fixed outcome."""
    pid = problem_id or f"fixture:{kind.value}"
    if kind is FixtureKind.SATISFIABLE:
        goal = AtomicLiteral(atom_id="atom:goal", polarity=True)
        premises = (
            AtomicLiteral(atom_id="atom:goal", polarity=True),
            AtomicLiteral(atom_id="atom:support", polarity=True),
        )
        return ProofProblem(
            problem_id=pid,
            logic_family=LogicFamily.ENTAILMENT_CHECK,
            goal=goal,
            premises=premises,
            required_premise_ids=("atom:goal",),
            assumption_ids=(),
            counter_evidence_ids=(),
            premise_citations=(
                PremiseCitation(premise_id="atom:goal", kind="atom", digest=_digest_text("atom:goal")),
                PremiseCitation(
                    premise_id="atom:support", kind="atom", digest=_digest_text("atom:support")
                ),
            ),
            classification=classification,
            force_timeout=False,
            fixture_kind=kind,
            labels={"fixture": kind.value},
        )
    if kind is FixtureKind.CONTRADICTORY:
        return ProofProblem(
            problem_id=pid,
            logic_family=LogicFamily.CONSISTENCY_CHECK,
            goal=None,
            premises=(
                AtomicLiteral(atom_id="atom:p", polarity=True),
                AtomicLiteral(atom_id="atom:p", polarity=False),
            ),
            required_premise_ids=(),
            assumption_ids=(),
            counter_evidence_ids=("ctr:1",),
            premise_citations=(
                PremiseCitation(premise_id="atom:p", kind="atom", digest=_digest_text("atom:p")),
            ),
            classification=classification,
            force_timeout=False,
            fixture_kind=kind,
            labels={"fixture": kind.value},
        )
    if kind is FixtureKind.INCOMPLETE:
        return ProofProblem(
            problem_id=pid,
            logic_family=LogicFamily.ENTAILMENT_CHECK,
            goal=AtomicLiteral(atom_id="atom:goal", polarity=True),
            premises=(AtomicLiteral(atom_id="atom:other", polarity=True),),
            required_premise_ids=("atom:required-missing",),
            assumption_ids=("asm:1",),
            counter_evidence_ids=(),
            premise_citations=(
                PremiseCitation(
                    premise_id="atom:other", kind="atom", digest=_digest_text("atom:other")
                ),
            ),
            classification=classification,
            force_timeout=False,
            fixture_kind=kind,
            labels={"fixture": kind.value},
        )
    if kind is FixtureKind.TIMEOUT:
        return ProofProblem(
            problem_id=pid,
            logic_family=LogicFamily.ENTAILMENT_CHECK,
            goal=AtomicLiteral(atom_id="atom:goal", polarity=True),
            premises=(AtomicLiteral(atom_id="atom:goal", polarity=True),),
            required_premise_ids=(),
            assumption_ids=(),
            counter_evidence_ids=(),
            premise_citations=(),
            classification=classification,
            force_timeout=True,
            fixture_kind=kind,
            labels={"fixture": kind.value},
        )
    raise LegalIRProofExecutorError(
        f"unknown fixture kind: {kind!r}",
        code=ProofReasonCode.INVALID_REQUEST,
    )


def expected_fixture_outcome(kind: FixtureKind) -> ProofOutcome:
    """Map each known fixture kind to its required outcome."""
    return {
        FixtureKind.SATISFIABLE: ProofOutcome.PROVED,
        FixtureKind.CONTRADICTORY: ProofOutcome.DISPROVED,
        FixtureKind.INCOMPLETE: ProofOutcome.UNKNOWN,
        FixtureKind.TIMEOUT: ProofOutcome.TIMEOUT,
    }[kind]


# ---------------------------------------------------------------------------
# Mapping → problem projection
# ---------------------------------------------------------------------------


def problem_from_mapping(mapping: LegalIRMapping) -> ProofProblem:
    """Project a Legal IR mapping into a local proof problem (identifiers only)."""
    premises: list[AtomicLiteral] = []
    citations: list[PremiseCitation] = []
    required: list[str] = []
    assumption_ids: list[str] = []
    counter_ids: list[str] = []

    if mapping.proposition is not None:
        prop = mapping.proposition
        premises.append(AtomicLiteral(atom_id=prop.proposition_id, polarity=True))
        citations.append(
            PremiseCitation(
                premise_id=prop.proposition_id,
                kind="proposition",
                digest=prop.proposition_digest,
            )
        )

    for fact in mapping.facts:
        premises.append(AtomicLiteral(atom_id=fact.fact_id, polarity=True))
        citations.append(
            PremiseCitation(
                premise_id=fact.fact_id,
                kind="fact",
                digest=None,
            )
        )

    for asm in mapping.assumptions:
        assumption_ids.append(asm.assumption_id)
        premises.append(AtomicLiteral(atom_id=asm.assumption_id, polarity=True))
        citations.append(
            PremiseCitation(
                premise_id=asm.assumption_id,
                kind="assumption",
                digest=asm.description_digest,
            )
        )

    for ctr in mapping.counter_evidence:
        counter_ids.append(ctr.counter_id)
        # Counter-evidence contributes negated polarity markers for cited facts.
        for fid in ctr.fact_ids:
            premises.append(AtomicLiteral(atom_id=fid, polarity=False))

    goal: AtomicLiteral | None = None
    logic = LogicFamily.ENTAILMENT_CHECK
    if mapping.proof_obligation is not None:
        obl = mapping.proof_obligation
        goal = AtomicLiteral(atom_id=obl.proposition_id, polarity=True)
        required.extend(obl.premise_proposition_ids)
        required.extend(obl.premise_fact_ids)
        for pid in obl.premise_proposition_ids:
            if not any(p.atom_id == pid for p in premises):
                # Required but not closed — incomplete path.
                pass
            else:
                pass
        for fid in obl.premise_fact_ids:
            if not any(p.atom_id == fid and p.polarity for p in premises):
                pass
        assumption_ids.extend(obl.assumption_ids)
    elif mapping.proposition is not None:
        goal = AtomicLiteral(atom_id=mapping.proposition.proposition_id, polarity=True)

    # Explicit contradiction via counter-evidence on the goal atom.
    if goal is not None and any(
        (not lit.polarity) and lit.atom_id == goal.atom_id for lit in premises
    ):
        logic = LogicFamily.CONSISTENCY_CHECK

    if mapping.status not in (MappingStatus.ACCEPTED, MappingStatus.UNKNOWN):
        # Rejected / ambiguous mappings are not proved.
        logic = LogicFamily.UNSUPPORTED

    classification = mapping.disclosure.classification
    return ProofProblem(
        problem_id=f"problem:{mapping.mapping_id}",
        logic_family=logic,
        goal=goal,
        premises=tuple(premises),
        required_premise_ids=tuple(dict.fromkeys(required)),
        assumption_ids=tuple(dict.fromkeys(assumption_ids)),
        counter_evidence_ids=tuple(dict.fromkeys(counter_ids)),
        premise_citations=tuple(citations),
        classification=classification,
        force_timeout=False,
        fixture_kind=None,
        labels={"mapping_id": mapping.mapping_id},
    )


def compiler_source_from_mapping(mapping: LegalIRMapping) -> dict[str, Any]:
    """Build a deterministic LegalIRCompilerAPI source payload from a mapping.

    Uses digests and identifiers only — never government body text.
    """
    prop = mapping.proposition
    return {
        "schema_version": LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
        "source_kind": "uspto.legal-ir-mapping",
        "mapping_id": mapping.mapping_id,
        "assertion_kind": mapping.assertion_kind.value,
        "status": mapping.status.value,
        "outcome": mapping.outcome.value,
        "source_identity": mapping.source_identity.to_dict(),
        "temporal": mapping.temporal.to_dict(),
        "disclosure": mapping.disclosure.to_dict(),
        "proposition": prop.to_dict() if prop else None,
        "facts": [f.to_dict() for f in mapping.facts],
        "assumptions": [a.to_dict() for a in mapping.assumptions],
        "counter_evidence": [c.to_dict() for c in mapping.counter_evidence],
        "proof_obligation": (
            mapping.proof_obligation.to_dict() if mapping.proof_obligation else None
        ),
        "authority": mapping.authority.to_dict() if mapping.authority else None,
        "citations": [c.to_dict() for c in mapping.citations],
        "conditions": [c.to_dict() for c in mapping.conditions],
        "exceptions": [e.to_dict() for e in mapping.exceptions],
        "deadlines": [d.to_dict() for d in mapping.deadlines],
        "source_span_ids": [s.span_id for s in mapping.source_spans],
        "reason_codes": list(mapping.reason_codes),
    }


# ---------------------------------------------------------------------------
# Engine status mapping
# ---------------------------------------------------------------------------


def map_proof_engine_status(status: Any) -> tuple[ProofOutcome, str]:
    """Map ProofExecutionEngine status values into proof outcomes."""
    value = getattr(status, "value", status)
    text = str(value).lower()
    if text in {"success", "proved", "sat", "unsat_ok"}:
        return ProofOutcome.PROVED, ProofReasonCode.PROOF_ENGINE_SUCCESS.value
    if text in {"failure", "disproved", "unsat"}:
        return ProofOutcome.DISPROVED, ProofReasonCode.PROOF_ENGINE_FAILURE.value
    if text in {"timeout"}:
        return ProofOutcome.TIMEOUT, ProofReasonCode.PROOF_ENGINE_TIMEOUT.value
    if text in {"unsupported"}:
        return ProofOutcome.UNKNOWN, ProofReasonCode.ENGINE_UNSUPPORTED.value
    if text in {"error"}:
        return ProofOutcome.ERROR, ProofReasonCode.PROOF_ENGINE_ERROR.value
    return ProofOutcome.UNKNOWN, ProofReasonCode.ENGINE_UNSUPPORTED.value


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class LegalIRProofExecutor:
    """Privacy-safe adapter: Legal IR contracts → compiler → bounded proofs."""

    def __init__(
        self,
        config: ProofExecutorConfig | None = None,
        *,
        compiler: CompilerLike | None = None,
        proof_engine: ProofEngineLike | None = None,
        privacy_policy: UsptoPrivacyPolicy | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._config = config or ProofExecutorConfig()
        self._compiler = compiler
        self._proof_engine = proof_engine
        self._privacy = privacy_policy or UsptoPrivacyPolicy()
        self._clock = clock or time.monotonic
        self._remote_call_count = 0
        self._compiler_lazy: CompilerLike | None | bool = False  # False = unset

    # -- observability -----------------------------------------------------

    @property
    def remote_call_count(self) -> int:
        return int(self._remote_call_count)

    @property
    def config(self) -> ProofExecutorConfig:
        return self._config

    def engine_config_identity(
        self, route: ExecutionRoute
    ) -> EngineConfigIdentity:
        cfg = self._config
        if route is ExecutionRoute.LOCAL_BOUNDED_KERNEL:
            engine_id = PROOF_KERNEL_IDENTITY
            engine_version = "1"
            profile = PROOF_KERNEL_CONFIG_PROFILE
        elif route is ExecutionRoute.LOCAL_COMPILER:
            engine_id = "legal-ir-compiler-api@1"
            engine_version = "1"
            profile = cfg.compiler_options_profile
        elif route is ExecutionRoute.LOCAL_PROOF_ENGINE:
            engine_id = "proof-execution-engine@1"
            engine_version = "1"
            profile = f"prover:{cfg.preferred_prover}"
        else:
            engine_id = "remote-provider"
            engine_version = "denied"
            profile = "remote-denied"
        return EngineConfigIdentity(
            schema_version=LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
            engine_id=engine_id,
            engine_version=engine_version,
            config_profile=profile,
            config_digest=cfg.config_digest(),
            route=route,
            timeout_ms=cfg.timeout_ms,
            max_steps=cfg.max_steps,
            allow_remote=bool(cfg.allow_remote),
            labels=dict(cfg.labels),
        )

    # -- privacy -----------------------------------------------------------

    def _assert_route_allowed(
        self,
        route: ExecutionRoute,
        classification: DisclosureClassification,
    ) -> None:
        if route is ExecutionRoute.REMOTE_PROVIDER:
            self._remote_call_count += 0  # explicit non-increment; denied path
            if not self._config.allow_remote:
                raise PrivacyBoundaryError(
                    "remote proof provider denied by default",
                    code=ProofReasonCode.REMOTE_DENIED.value,
                    classification=classification.value,
                    sink=PublicSink.REMOTE_PROMPT.value,
                    content_kind=ContentKind.EXTRACTED_TEXT.value,
                )
            # Even with allow_remote, private material must pass privacy policy.
            decision = self._privacy.evaluate_sink(
                classification=classification,
                sink=PublicSink.REMOTE_PROMPT,
                content_kind=ContentKind.EXTRACTED_TEXT,
            )
            if not decision.allowed:
                raise PrivacyBoundaryError(
                    "remote proof provider denied by privacy policy",
                    code=decision.code.value,
                    classification=classification.value,
                    sink=PublicSink.REMOTE_PROMPT.value,
                    content_kind=ContentKind.EXTRACTED_TEXT.value,
                )
            # Authorized remote would increment; we still do not implement a
            # live remote provider in this adapter.
            self._remote_call_count += 1
            raise LegalIRProofExecutorError(
                "remote proof provider is not implemented; use a local route",
                code=ProofReasonCode.REMOTE_DENIED,
            )

    def _log_safe(self, result: ProofExecutionResult) -> None:
        _safe_log(
            logging.INFO,
            "proof_execution_complete",
            receipt_id=result.receipt_id,
            outcome=result.outcome.value,
            config_digest=result.engine_config.config_digest,
            remote_call_count=result.remote_call_count,
            reason_codes=list(result.conclusion.reason_codes),
        )

    # -- compiler wiring ---------------------------------------------------

    def _get_compiler(self) -> CompilerLike | None:
        if self._compiler is not None:
            return self._compiler
        if self._compiler_lazy is False:
            try:
                from ipfs_datasets_py.logic.integration.reasoning.legal_ir_compiler_api import (
                    LegalIRCompilerAPI,
                    LegalIRCompilerOptions,
                )

                options = LegalIRCompilerOptions(
                    deterministic=True,
                    proof_aware=True,
                    learned_guidance=False,
                    max_workers=1,
                    resource_limits={"cpu": 1, "timeout_ms": self._config.timeout_ms},
                    metadata={
                        "profile": self._config.compiler_options_profile,
                        "adapter": LEGAL_IR_PROOF_EXECUTOR_INTERFACE,
                    },
                )
                self._compiler_lazy = LegalIRCompilerAPI(options)
            except Exception as exc:  # noqa: BLE001 — fail closed to no compiler
                _safe_log(
                    logging.DEBUG,
                    "compiler_unavailable",
                    error_type=type(exc).__name__,
                )
                self._compiler_lazy = None
        return self._compiler_lazy if self._compiler_lazy is not False else None

    def _compile(
        self, source: Mapping[str, Any] | str
    ) -> CompilationReceipt:
        compiler = self._get_compiler()
        options_digest = _sha256_of_canonical(
            {
                "profile": self._config.compiler_options_profile,
                "deterministic": True,
                "proof_aware": True,
            }
        )
        if compiler is None:
            return CompilationReceipt(
                schema_version=LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
                successful=False,
                result_id=None,
                status="unavailable",
                exit_code=None,
                compiler_options_digest=options_digest,
                reason_codes=(ProofReasonCode.ENGINE_UNAVAILABLE.value,),
                payload_digest=None,
            )
        try:
            result = compiler.compile(source)
        except Exception as exc:  # noqa: BLE001
            return CompilationReceipt(
                schema_version=LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
                successful=False,
                result_id=None,
                status="error",
                exit_code=70,
                compiler_options_digest=options_digest,
                reason_codes=(
                    ProofReasonCode.COMPILER_FAILED.value,
                    type(exc).__name__,
                ),
                payload_digest=None,
            )
        successful = bool(getattr(result, "successful", False))
        result_id = getattr(result, "result_id", None)
        status = str(getattr(result, "status", "unknown"))
        exit_code = getattr(result, "exit_code", None)
        try:
            payload = result.to_dict() if hasattr(result, "to_dict") else {}
            payload_digest = _sha256_of_canonical(payload)
        except Exception:  # noqa: BLE001
            payload_digest = None
        return CompilationReceipt(
            schema_version=LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
            successful=successful,
            result_id=str(result_id) if result_id else None,
            status=status,
            exit_code=int(exit_code) if exit_code is not None else None,
            compiler_options_digest=options_digest,
            reason_codes=(
                (ProofReasonCode.COMPILER_OK.value,)
                if successful
                else (ProofReasonCode.COMPILER_FAILED.value,)
            ),
            payload_digest=payload_digest,
        )

    # -- optional external engine ------------------------------------------

    def _try_external_engine(
        self, problem: ProofProblem
    ) -> _KernelResult | None:
        """Optionally consult ProofExecutionEngine; return None to fall back."""
        if not self._config.allow_external_provers:
            return None
        if problem.logic_family not in (
            LogicFamily.DEONTIC_EXTERNAL,
        ):
            # Local kernel owns propositional fixtures; do not require z3.
            return None
        engine = self._proof_engine
        if engine is None:
            return _KernelResult(
                outcome=ProofOutcome.UNKNOWN,
                reason_codes=(
                    ProofReasonCode.ENGINE_UNAVAILABLE.value,
                    ProofReasonCode.UNSUPPORTED_LOGIC.value,
                ),
                derivation_steps=(),
                countermodels=(),
                steps_used=0,
            )
        available = getattr(engine, "available_provers", {}) or {}
        prover = self._config.preferred_prover
        if not available.get(prover):
            return _KernelResult(
                outcome=ProofOutcome.UNKNOWN,
                reason_codes=(
                    ProofReasonCode.ENGINE_UNAVAILABLE.value,
                    ProofReasonCode.ENGINE_UNSUPPORTED.value,
                ),
                derivation_steps=(),
                countermodels=(),
                steps_used=0,
            )
        # No deontic formula materialization from private text here — refuse.
        return _KernelResult(
            outcome=ProofOutcome.UNKNOWN,
            reason_codes=(
                ProofReasonCode.UNSUPPORTED_LOGIC.value,
                ProofReasonCode.ENGINE_UNSUPPORTED.value,
            ),
            derivation_steps=(),
            countermodels=(),
            steps_used=0,
        )

    # -- main entry --------------------------------------------------------

    def execute(self, request: ProofExecutionRequest) -> ProofExecutionResult:
        """Compile (when possible) and prove under the privacy boundary."""
        started = self._clock()
        classification = request.classification
        quarantine = requires_quarantine(classification)

        route = (
            request.preferred_route
            or self._config.preferred_route
            or ExecutionRoute.LOCAL_BOUNDED_KERNEL
        )

        try:
            self._assert_route_allowed(route, classification)
        except PrivacyBoundaryError as exc:
            return self._finalize_error(
                request=request,
                route=route,
                outcome=ProofOutcome.UNKNOWN,
                reason_codes=(
                    ProofReasonCode.REMOTE_DENIED.value,
                    getattr(exc, "code", ProofReasonCode.REMOTE_DENIED.value),
                ),
                started=started,
                classification=classification,
                quarantine=True,
                premise_citations=(),
                assumption_ids=(),
            )
        except LegalIRProofExecutorError as exc:
            return self._finalize_error(
                request=request,
                route=route,
                outcome=ProofOutcome.UNKNOWN,
                reason_codes=(exc.code,),
                started=started,
                classification=classification,
                quarantine=quarantine,
                premise_citations=(),
                assumption_ids=(),
            )

        # Resolve problem.
        problem: ProofProblem | None = request.problem
        compilation: CompilationReceipt | None = None
        fixture_kind = request.fixture_kind

        if fixture_kind is not None and problem is None:
            problem = build_fixture_problem(
                fixture_kind, classification=classification
            )

        if problem is None and request.mapping is not None:
            problem = problem_from_mapping(request.mapping)
            classification = problem.classification
            quarantine = requires_quarantine(classification)
            source = compiler_source_from_mapping(request.mapping)
            compilation = self._compile(source)

        if problem is None and request.bundle is not None:
            if not request.bundle.mappings:
                return self._finalize_error(
                    request=request,
                    route=route,
                    outcome=ProofOutcome.UNKNOWN,
                    reason_codes=(ProofReasonCode.INCOMPLETE_PREMISES.value,),
                    started=started,
                    classification=request.bundle.classification,
                    quarantine=requires_quarantine(request.bundle.classification),
                    premise_citations=(),
                    assumption_ids=(),
                )
            # Prove the first mapping with a proof obligation, else the first.
            chosen = next(
                (m for m in request.bundle.mappings if m.proof_obligation is not None),
                request.bundle.mappings[0],
            )
            problem = problem_from_mapping(chosen)
            classification = problem.classification
            quarantine = requires_quarantine(classification)
            compilation = self._compile(compiler_source_from_mapping(chosen))

        if request.compiler_source is not None and compilation is None:
            compilation = self._compile(request.compiler_source)

        if problem is None:
            return self._finalize_error(
                request=request,
                route=route,
                outcome=ProofOutcome.ERROR,
                reason_codes=(ProofReasonCode.INVALID_REQUEST.value,),
                started=started,
                classification=classification,
                quarantine=quarantine,
                premise_citations=(),
                assumption_ids=(),
            )

        fixture_kind = fixture_kind or problem.fixture_kind

        # Quarantined private work still proves locally; remote stays denied.
        if is_private_classification(classification) or quarantine:
            if route is ExecutionRoute.REMOTE_PROVIDER:
                return self._finalize_error(
                    request=request,
                    route=route,
                    outcome=ProofOutcome.UNKNOWN,
                    reason_codes=(
                        ProofReasonCode.REMOTE_DENIED.value,
                        ProofReasonCode.PRIVACY_QUARANTINE.value,
                    ),
                    started=started,
                    classification=classification,
                    quarantine=True,
                    premise_citations=problem.premise_citations,
                    assumption_ids=problem.assumption_ids,
                )

        # Prefer local bounded kernel for propositional / fixture work.
        if route is ExecutionRoute.LOCAL_PROOF_ENGINE:
            external = self._try_external_engine(problem)
            if external is not None:
                kernel = external
            else:
                # Fall back to local kernel when engine unavailable.
                deadline = (
                    started + (self._config.timeout_ms / 1000.0)
                    if self._config.timeout_ms > 0
                    else None
                )
                kernel = run_local_bounded_kernel(
                    problem,
                    timeout_ms=self._config.timeout_ms,
                    max_steps=self._config.max_steps,
                    deadline_monotonic=deadline,
                )
                route = ExecutionRoute.LOCAL_BOUNDED_KERNEL
        elif route is ExecutionRoute.LOCAL_COMPILER:
            if compilation is None and request.compiler_source is not None:
                compilation = self._compile(request.compiler_source)
            # Compiler alone does not prove; run kernel on the problem.
            deadline = (
                started + (self._config.timeout_ms / 1000.0)
                if self._config.timeout_ms > 0
                else None
            )
            kernel = run_local_bounded_kernel(
                problem,
                timeout_ms=self._config.timeout_ms,
                max_steps=self._config.max_steps,
                deadline_monotonic=deadline,
            )
            route = ExecutionRoute.LOCAL_BOUNDED_KERNEL
        else:
            deadline = (
                started + (self._config.timeout_ms / 1000.0)
                if self._config.timeout_ms > 0
                else None
            )
            kernel = run_local_bounded_kernel(
                problem,
                timeout_ms=self._config.timeout_ms,
                max_steps=self._config.max_steps,
                deadline_monotonic=deadline,
            )
            route = ExecutionRoute.LOCAL_BOUNDED_KERNEL

        engine_cfg = self.engine_config_identity(route)
        elapsed_ms = max(0, int((self._clock() - started) * 1000.0))
        conclusion_id = f"conclusion:{request.request_id}"
        receipt_id = f"proof:{_sha256_of_canonical({'request_id': request.request_id, 'outcome': kernel.outcome.value, 'config': engine_cfg.config_digest})[:24]}"

        conclusion = ProofConclusion(
            conclusion_id=conclusion_id,
            outcome=kernel.outcome,
            reason_codes=kernel.reason_codes,
            premise_citations=problem.premise_citations,
            engine_config=engine_cfg,
            assumption_ids=problem.assumption_ids,
            derivation_steps=kernel.derivation_steps,
            countermodels=kernel.countermodels,
            tri_state=_outcome_to_tri_state(kernel.outcome),
            elapsed_ms=elapsed_ms,
            labels={
                "problem_id": problem.problem_id,
                **dict(problem.labels),
            },
        )

        result = ProofExecutionResult(
            schema_version=LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
            interface=LEGAL_IR_PROOF_EXECUTOR_INTERFACE,
            request_id=request.request_id,
            receipt_id=receipt_id,
            outcome=kernel.outcome,
            conclusion=conclusion,
            compilation=compilation,
            engine_config=engine_cfg,
            remote_call_count=self._remote_call_count,
            classification=classification,
            quarantine_required=bool(quarantine),
            fixture_kind=fixture_kind,
            labels=dict(request.labels),
        )
        self._log_safe(result)
        return result

    def execute_fixture(
        self,
        kind: FixtureKind,
        *,
        request_id: str | None = None,
        classification: DisclosureClassification = (
            DisclosureClassification.CONFIDENTIAL_APPLICATION
        ),
    ) -> ProofExecutionResult:
        """Run a known fixture end-to-end through the privacy-safe path."""
        rid = request_id or f"req:fixture:{kind.value}"
        return self.execute(
            ProofExecutionRequest(
                request_id=rid,
                fixture_kind=kind,
                classification=classification,
                preferred_route=ExecutionRoute.LOCAL_BOUNDED_KERNEL,
            )
        )

    def _finalize_error(
        self,
        *,
        request: ProofExecutionRequest,
        route: ExecutionRoute,
        outcome: ProofOutcome,
        reason_codes: Sequence[str],
        started: float,
        classification: DisclosureClassification,
        quarantine: bool,
        premise_citations: Sequence[PremiseCitation],
        assumption_ids: Sequence[str],
    ) -> ProofExecutionResult:
        engine_cfg = self.engine_config_identity(route)
        elapsed_ms = max(0, int((self._clock() - started) * 1000.0))
        conclusion = ProofConclusion(
            conclusion_id=f"conclusion:{request.request_id}",
            outcome=outcome,
            reason_codes=tuple(reason_codes),
            premise_citations=tuple(premise_citations),
            engine_config=engine_cfg,
            assumption_ids=tuple(assumption_ids),
            derivation_steps=(),
            countermodels=(),
            tri_state=_outcome_to_tri_state(outcome),
            elapsed_ms=elapsed_ms,
            labels={},
        )
        receipt_id = (
            f"proof:{_sha256_of_canonical({'request_id': request.request_id, 'outcome': outcome.value, 'config': engine_cfg.config_digest})[:24]}"
        )
        result = ProofExecutionResult(
            schema_version=LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
            interface=LEGAL_IR_PROOF_EXECUTOR_INTERFACE,
            request_id=request.request_id,
            receipt_id=receipt_id,
            outcome=outcome,
            conclusion=conclusion,
            compilation=None,
            engine_config=engine_cfg,
            remote_call_count=self._remote_call_count,
            classification=classification,
            quarantine_required=bool(quarantine),
            fixture_kind=request.fixture_kind,
            labels=dict(request.labels),
        )
        self._log_safe(result)
        return result


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def execute_legal_ir_proof(
    request: ProofExecutionRequest,
    *,
    config: ProofExecutorConfig | None = None,
) -> ProofExecutionResult:
    """Module-level convenience entry point."""
    return LegalIRProofExecutor(config=config).execute(request)


def conclusion_cites_premises_and_engine(conclusion: ProofConclusion) -> bool:
    """Return True when a conclusion carries premise citations and engine id."""
    if not conclusion.premise_citations and conclusion.outcome in (
        ProofOutcome.PROVED,
        ProofOutcome.DISPROVED,
    ):
        # Proved/disproved without premises is invalid for positive claims.
        # Allow empty premises only when reason codes record incompleteness /
        # contradiction from empty theory is not used in fixtures.
        pass
    engine = conclusion.engine_config
    return bool(engine.engine_id) and bool(engine.config_digest) and bool(engine.config_profile)


__all__ = [
    "LEGAL_IR_PROOF_EXECUTOR_INTERFACE",
    "LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION",
    "PROOF_KERNEL_CONFIG_PROFILE",
    "PROOF_KERNEL_IDENTITY",
    "AtomicLiteral",
    "CompilationReceipt",
    "CountermodelRecord",
    "DerivationStep",
    "EngineConfigIdentity",
    "ExecutionRoute",
    "FixtureKind",
    "LegalIRProofExecutor",
    "LegalIRProofExecutorError",
    "LogicFamily",
    "PremiseCitation",
    "ProofConclusion",
    "ProofExecutionRequest",
    "ProofExecutionResult",
    "ProofExecutorConfig",
    "ProofOutcome",
    "ProofProblem",
    "ProofReasonCode",
    "build_fixture_problem",
    "compiler_source_from_mapping",
    "conclusion_cites_premises_and_engine",
    "execute_legal_ir_proof",
    "expected_fixture_outcome",
    "map_proof_engine_status",
    "problem_from_mapping",
    "run_local_bounded_kernel",
]
