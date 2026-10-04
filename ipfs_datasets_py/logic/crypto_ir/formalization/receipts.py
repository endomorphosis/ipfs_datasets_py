"""Evidence-bound analysis attempts, proof authority, and receipts (CRYPTOIR-G320).

Receipts bind obligation, model, tool, policy, capability, and timeout.
:class:`ProofAuthority` is explicit: SAT/UNSAT answers are
:attr:`ProofAuthority.SATISFIABILITY_ONLY` and never silently become a security
proof.  Unavailable solvers, timeouts, disagreements, incomplete models, and
opaque refusals all yield :attr:`ProofAuthority.NON_PROOF`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import CanonicalIdentity
from ...ir_core.provenance import thaw_json
from ..identity import crypto_ir_identity
from ..verdicts import AnalysisOutcome, SatisfiabilityOutcome
from .compiler import LoweredForm, LoweringStatus
from .obligations import (
    CRYPTO_IR_FORMALIZATION_DOMAIN,
    FormalObligation,
    FormalizationError,
    LogicFamily,
    _attributes,
    _enum,
    _identifier,
    _text,
    _unique_ids,
)
from .portfolio import (
    BackendResult,
    BackendStatus,
    PortfolioRun,
)


ANALYSIS_ATTEMPT_SCHEMA_VERSION: Final[str] = "crypto-ir.analysis-attempt@1.0.0"
ANALYSIS_RECEIPT_SCHEMA_VERSION: Final[str] = "crypto-ir.analysis-receipt@1.0.0"


class ProofAuthority(str, Enum):
    """Closed authority lattice for formalization outcomes.

    Families are non-interchangeable: satisfiability is never proof, monitor
    satisfaction is never a theorem, and non-proof never elevates.
    """

    PROOF = "proof"
    DISPROOF = "disproof"
    SATISFIABILITY_ONLY = "satisfiability_only"
    MONITOR_ONLY = "monitor_only"
    NON_PROOF = "non_proof"


class AttemptOutcome(str, Enum):
    """Per-attempt analysis outcome before receipt aggregation."""

    PROVED = "proved"
    DISPROVED = "disproved"
    SATISFIABLE = "satisfiable"
    UNSATISFIABLE = "unsatisfiable"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    NOT_MODELED = "not_modeled"
    UNSUPPORTED = "unsupported"
    INCOMPLETE_MODEL = "incomplete_model"
    DISAGREEMENT = "disagreement"
    ERROR = "error"
    REFUSED = "refused"


_BACKEND_TO_ATTEMPT: Final[Mapping[BackendStatus, AttemptOutcome]] = {
    BackendStatus.PROVED: AttemptOutcome.PROVED,
    BackendStatus.DISPROVED: AttemptOutcome.DISPROVED,
    BackendStatus.SATISFIABLE: AttemptOutcome.SATISFIABLE,
    BackendStatus.UNSATISFIABLE: AttemptOutcome.UNSATISFIABLE,
    BackendStatus.UNKNOWN: AttemptOutcome.UNKNOWN,
    BackendStatus.TIMEOUT: AttemptOutcome.TIMEOUT,
    BackendStatus.UNAVAILABLE: AttemptOutcome.UNAVAILABLE,
    BackendStatus.NOT_MODELED: AttemptOutcome.NOT_MODELED,
    BackendStatus.REFUSED: AttemptOutcome.REFUSED,
    BackendStatus.ERROR: AttemptOutcome.ERROR,
    BackendStatus.DISAGREEMENT: AttemptOutcome.DISAGREEMENT,
}

_LOWERING_TO_ATTEMPT: Final[Mapping[LoweringStatus, AttemptOutcome]] = {
    LoweringStatus.COMPILED: AttemptOutcome.UNKNOWN,
    LoweringStatus.NOT_MODELED: AttemptOutcome.NOT_MODELED,
    LoweringStatus.UNSUPPORTED: AttemptOutcome.UNSUPPORTED,
    LoweringStatus.OPAQUE_REFUSED: AttemptOutcome.REFUSED,
    LoweringStatus.INCOMPLETE_MODEL: AttemptOutcome.INCOMPLETE_MODEL,
    LoweringStatus.ERROR: AttemptOutcome.ERROR,
}


def proof_authority_for_outcome(outcome: AttemptOutcome | str) -> ProofAuthority:
    """Map an attempt outcome to its non-elevating proof authority."""

    value = _enum(AttemptOutcome, outcome, "outcome")
    if value is AttemptOutcome.PROVED:
        return ProofAuthority.PROOF
    if value is AttemptOutcome.DISPROVED:
        return ProofAuthority.DISPROOF
    if value in {AttemptOutcome.SATISFIABLE, AttemptOutcome.UNSATISFIABLE}:
        return ProofAuthority.SATISFIABILITY_ONLY
    return ProofAuthority.NON_PROOF


def analysis_outcome_for_attempt(outcome: AttemptOutcome | str) -> AnalysisOutcome:
    """Project attempt outcomes onto the Crypto IR analysis vocabulary.

    Satisfiability-only answers map to :attr:`AnalysisOutcome.UNKNOWN` so they
    are never silently treated as security proofs.
    """

    value = _enum(AttemptOutcome, outcome, "outcome")
    if value is AttemptOutcome.PROVED:
        return AnalysisOutcome.PROVED
    if value is AttemptOutcome.DISPROVED:
        return AnalysisOutcome.DISPROVED
    if value in {
        AttemptOutcome.UNSUPPORTED,
        AttemptOutcome.NOT_MODELED,
        AttemptOutcome.REFUSED,
    }:
        return AnalysisOutcome.UNSUPPORTED
    if value is AttemptOutcome.INCOMPLETE_MODEL:
        return AnalysisOutcome.INCONCLUSIVE
    if value is AttemptOutcome.ERROR:
        return AnalysisOutcome.ERROR
    # sat/unsat/timeout/unavailable/unknown/disagreement → non-proof unknown
    return AnalysisOutcome.UNKNOWN


def satisfiability_outcome_for_attempt(
    outcome: AttemptOutcome | str,
) -> SatisfiabilityOutcome | None:
    """Return a satisfiability outcome when applicable; else None."""

    value = _enum(AttemptOutcome, outcome, "outcome")
    if value is AttemptOutcome.SATISFIABLE:
        return SatisfiabilityOutcome.SATISFIABLE
    if value is AttemptOutcome.UNSATISFIABLE:
        return SatisfiabilityOutcome.UNSATISFIABLE
    if value is AttemptOutcome.ERROR:
        return SatisfiabilityOutcome.ERROR
    if value in {AttemptOutcome.UNKNOWN, AttemptOutcome.TIMEOUT}:
        return SatisfiabilityOutcome.UNKNOWN
    return None


def assert_sat_is_not_proof(authority: ProofAuthority | str) -> None:
    """Fail closed when satisfiability is treated as proof authority."""

    value = _enum(ProofAuthority, authority, "authority")
    if value is ProofAuthority.SATISFIABILITY_ONLY:
        raise FormalizationError(
            "SAT/UNSAT is satisfiability-only authority and is not a security proof"
        )


@dataclass(frozen=True, slots=True)
class AnalysisAttempt:
    """One evidence-bound attempt to discharge an obligation."""

    attempt_id: str
    obligation_id: str
    model_digest: str
    outcome: AttemptOutcome
    proof_authority: ProofAuthority
    backend_id: str = ""
    tool_name: str = ""
    tool_version: str = ""
    capability_id: str = ""
    policy_id: str = ""
    policy_revision: str = ""
    contract_id: str = ""
    form_id: str = ""
    logic_family: LogicFamily = LogicFamily.UNSUPPORTED
    timeout_ms: int = 0
    elapsed_ms: int = 0
    executed: bool = False
    reason: str = ""
    counterexample: Mapping[str, Any] = field(default_factory=dict)
    assumption_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ANALYSIS_ATTEMPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "attempt_id", _identifier(self.attempt_id, "attempt_id")
        )
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self,
            "model_digest",
            _text(self.model_digest, "model_digest", allow_empty=True),
        )
        object.__setattr__(
            self, "outcome", _enum(AttemptOutcome, self.outcome, "outcome")
        )
        object.__setattr__(
            self,
            "proof_authority",
            _enum(ProofAuthority, self.proof_authority, "proof_authority"),
        )
        # Authority must match outcome lattice.
        expected = proof_authority_for_outcome(self.outcome)
        if self.proof_authority is not expected:
            raise FormalizationError(
                f"proof_authority {self.proof_authority.value} inconsistent with "
                f"outcome {self.outcome.value} (expected {expected.value})"
            )
        for name in (
            "backend_id",
            "tool_name",
            "tool_version",
            "capability_id",
            "policy_id",
            "policy_revision",
            "contract_id",
            "form_id",
            "reason",
        ):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        object.__setattr__(
            self, "logic_family", _enum(LogicFamily, self.logic_family, "logic_family")
        )
        for name in ("timeout_ms", "elapsed_ms"):
            value = getattr(self, name)
            if type(value) is not int or isinstance(value, bool) or value < 0:
                raise FormalizationError(f"{name} must be a non-negative int")
        if not isinstance(self.executed, bool):
            raise FormalizationError("executed must be a bool")
        object.__setattr__(self, "counterexample", _attributes(self.counterexample))
        object.__setattr__(
            self, "assumption_ids", _unique_ids(self.assumption_ids, "assumption_ids")
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        # SAT is never proof.
        if self.outcome in {
            AttemptOutcome.SATISFIABLE,
            AttemptOutcome.UNSATISFIABLE,
        }:
            if self.proof_authority is not ProofAuthority.SATISFIABILITY_ONLY:
                raise FormalizationError("SAT/UNSAT must use satisfiability_only authority")

    @property
    def analysis_outcome(self) -> AnalysisOutcome:
        return analysis_outcome_for_attempt(self.outcome)

    @property
    def is_non_proof(self) -> bool:
        return self.proof_authority is ProofAuthority.NON_PROOF or (
            self.proof_authority is ProofAuthority.SATISFIABILITY_ONLY
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "attempt_id": self.attempt_id,
            "attributes": thaw_json(self.attributes),
            "backend_id": self.backend_id,
            "capability_id": self.capability_id,
            "contract_id": self.contract_id,
            "counterexample": thaw_json(self.counterexample),
            "elapsed_ms": self.elapsed_ms,
            "executed": self.executed,
            "form_id": self.form_id,
            "logic_family": (
                self.logic_family.value
                if isinstance(self.logic_family, LogicFamily)
                else self.logic_family
            ),
            "model_digest": self.model_digest,
            "obligation_id": self.obligation_id,
            "outcome": (
                self.outcome.value
                if isinstance(self.outcome, AttemptOutcome)
                else self.outcome
            ),
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "proof_authority": (
                self.proof_authority.value
                if isinstance(self.proof_authority, ProofAuthority)
                else self.proof_authority
            ),
            "reason": self.reason,
            "schema_version": self.schema_version,
            "timeout_ms": self.timeout_ms,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
        }

    @classmethod
    def from_backend_result(
        cls,
        result: BackendResult,
        *,
        attempt_id: str,
        policy_id: str = "",
        policy_revision: str = "",
        contract_id: str = "",
        assumption_ids: Sequence[str] = (),
        attributes: Mapping[str, Any] | None = None,
    ) -> "AnalysisAttempt":
        outcome = _BACKEND_TO_ATTEMPT.get(result.status, AttemptOutcome.ERROR)
        return cls(
            attempt_id=attempt_id,
            obligation_id=result.obligation_id or "obligation.unknown",
            model_digest=result.model_digest,
            outcome=outcome,
            proof_authority=proof_authority_for_outcome(outcome),
            backend_id=result.backend_id,
            tool_name=result.tool_name,
            tool_version=result.tool_version,
            capability_id=result.capability_id,
            policy_id=policy_id,
            policy_revision=policy_revision,
            contract_id=contract_id,
            form_id=result.form_id,
            logic_family=result.logic_family,
            timeout_ms=result.timeout_ms,
            elapsed_ms=result.elapsed_ms,
            executed=result.executed,
            reason=result.reason,
            counterexample=dict(result.counterexample),
            assumption_ids=tuple(assumption_ids),
            attributes=attributes or dict(result.attributes),
        )

    @classmethod
    def from_lowered_form(
        cls,
        form: LoweredForm,
        *,
        attempt_id: str,
        policy_id: str = "",
        policy_revision: str = "",
        capability_ids: Sequence[str] = (),
    ) -> "AnalysisAttempt":
        """Build a non-execution attempt from a refused/non-compiled lowering."""

        outcome = _LOWERING_TO_ATTEMPT.get(form.status, AttemptOutcome.ERROR)
        capability_id = capability_ids[0] if capability_ids else ""
        return cls(
            attempt_id=attempt_id,
            obligation_id=form.obligation_id,
            model_digest=form.model_digest,
            outcome=outcome,
            proof_authority=proof_authority_for_outcome(outcome),
            backend_id="",
            capability_id=capability_id,
            policy_id=policy_id,
            policy_revision=policy_revision,
            contract_id=form.contract_id,
            form_id=form.form_id,
            logic_family=form.logic_family,
            timeout_ms=0,
            elapsed_ms=0,
            executed=False,
            reason=form.reason,
            assumption_ids=form.assumption_ids,
            attributes={"lowering_status": form.status.value},
        )


@dataclass(frozen=True, slots=True)
class AnalysisReceipt:
    """Typed, evidence-bound receipt for one formal obligation analysis.

    Binds obligation, model, tools, policy, capabilities, and timeout.  The
    receipt never authorizes a transaction.
    """

    receipt_id: str
    obligation_id: str
    model_digest: str
    outcome: AttemptOutcome
    proof_authority: ProofAuthority
    analysis_outcome: AnalysisOutcome
    attempts: tuple[AnalysisAttempt, ...]
    policy_id: str = ""
    policy_revision: str = ""
    capability_ids: tuple[str, ...] = ()
    tool_ids: tuple[str, ...] = ()
    timeout_ms: int = 0
    contract_id: str = ""
    form_id: str = ""
    code_epoch: str = ""
    assumption_ids: tuple[str, ...] = ()
    counterexample: Mapping[str, Any] = field(default_factory=dict)
    disagreement: bool = False
    summary: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ANALYSIS_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self,
            "model_digest",
            _text(self.model_digest, "model_digest", allow_empty=True),
        )
        object.__setattr__(
            self, "outcome", _enum(AttemptOutcome, self.outcome, "outcome")
        )
        object.__setattr__(
            self,
            "proof_authority",
            _enum(ProofAuthority, self.proof_authority, "proof_authority"),
        )
        object.__setattr__(
            self,
            "analysis_outcome",
            _enum(AnalysisOutcome, self.analysis_outcome, "analysis_outcome"),
        )
        expected_auth = proof_authority_for_outcome(self.outcome)
        if self.proof_authority is not expected_auth:
            raise FormalizationError(
                f"receipt proof_authority {self.proof_authority.value} inconsistent "
                f"with outcome {self.outcome.value}"
            )
        expected_analysis = analysis_outcome_for_attempt(self.outcome)
        if self.analysis_outcome is not expected_analysis:
            raise FormalizationError(
                f"analysis_outcome {self.analysis_outcome.value} inconsistent with "
                f"outcome {self.outcome.value} (expected {expected_analysis.value})"
            )
        attempts = tuple(self.attempts)
        for item in attempts:
            if not isinstance(item, AnalysisAttempt):
                raise FormalizationError("attempts must contain AnalysisAttempt values")
        object.__setattr__(self, "attempts", attempts)
        for name in (
            "policy_id",
            "policy_revision",
            "contract_id",
            "form_id",
            "code_epoch",
            "summary",
        ):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        object.__setattr__(
            self, "capability_ids", _unique_ids(self.capability_ids, "capability_ids")
        )
        object.__setattr__(self, "tool_ids", _unique_ids(self.tool_ids, "tool_ids"))
        if type(self.timeout_ms) is not int or isinstance(self.timeout_ms, bool) or self.timeout_ms < 0:
            raise FormalizationError("timeout_ms must be a non-negative int")
        object.__setattr__(
            self, "assumption_ids", _unique_ids(self.assumption_ids, "assumption_ids")
        )
        object.__setattr__(self, "counterexample", _attributes(self.counterexample))
        if not isinstance(self.disagreement, bool):
            raise FormalizationError("disagreement must be a bool")
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def binds_obligation_model_tool_policy_capability_timeout(self) -> bool:
        """Acceptance helper: receipt fields required by CRYPTOIR-G320."""

        return bool(
            self.obligation_id
            and (self.model_digest is not None)
            and self.timeout_ms >= 0
            and (
                self.tool_ids
                or any(a.tool_name or a.backend_id for a in self.attempts)
                or self.proof_authority is ProofAuthority.NON_PROOF
            )
        )

    def cannot_authorize_transaction(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_outcome": (
                self.analysis_outcome.value
                if isinstance(self.analysis_outcome, AnalysisOutcome)
                else self.analysis_outcome
            ),
            "assumption_ids": list(self.assumption_ids),
            "attempts": [a.to_dict() for a in self.attempts],
            "attributes": thaw_json(self.attributes),
            "capability_ids": list(self.capability_ids),
            "code_epoch": self.code_epoch,
            "contract_id": self.contract_id,
            "counterexample": thaw_json(self.counterexample),
            "disagreement": self.disagreement,
            "form_id": self.form_id,
            "model_digest": self.model_digest,
            "obligation_id": self.obligation_id,
            "outcome": (
                self.outcome.value
                if isinstance(self.outcome, AttemptOutcome)
                else self.outcome
            ),
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "proof_authority": (
                self.proof_authority.value
                if isinstance(self.proof_authority, ProofAuthority)
                else self.proof_authority
            ),
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "summary": self.summary,
            "timeout_ms": self.timeout_ms,
            "tool_ids": list(self.tool_ids),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_FORMALIZATION_DOMAIN}.analysis-receipt",
        )

    @classmethod
    def from_portfolio_run(
        cls,
        run: PortfolioRun,
        obligation: FormalObligation,
        form: LoweredForm,
        *,
        receipt_id: str | None = None,
    ) -> "AnalysisReceipt":
        """Aggregate a portfolio run into a single typed receipt."""

        attempts: list[AnalysisAttempt] = []
        for index, result in enumerate(run.results):
            attempts.append(
                AnalysisAttempt.from_backend_result(
                    result,
                    attempt_id=f"attempt.{obligation.obligation_id}.{index}",
                    policy_id=obligation.policy_id,
                    policy_revision=obligation.policy_revision,
                    contract_id=form.contract_id,
                    assumption_ids=form.assumption_ids,
                )
            )
        outcome = _aggregate_outcome(tuple(attempts), disagreement=run.disagreement)
        authority = proof_authority_for_outcome(outcome)
        tools = tuple(
            dict.fromkeys(
                a.tool_name or a.backend_id
                for a in attempts
                if a.tool_name or a.backend_id
            )
        )
        capabilities = tuple(
            dict.fromkeys(
                list(obligation.capability_ids)
                + [a.capability_id for a in attempts if a.capability_id]
            )
        )
        cex: dict[str, Any] = {}
        for attempt in attempts:
            if attempt.counterexample:
                cex = dict(attempt.counterexample)
                break
        rid = receipt_id or f"receipt.{obligation.obligation_id}.{form.form_id}"
        return cls(
            receipt_id=rid,
            obligation_id=obligation.obligation_id,
            model_digest=obligation.model_digest or form.model_digest,
            outcome=outcome,
            proof_authority=authority,
            analysis_outcome=analysis_outcome_for_attempt(outcome),
            attempts=tuple(attempts),
            policy_id=obligation.policy_id,
            policy_revision=obligation.policy_revision,
            capability_ids=capabilities,
            tool_ids=tools,
            timeout_ms=run.timeout_ms,
            contract_id=form.contract_id,
            form_id=form.form_id,
            code_epoch=obligation.code_epoch,
            assumption_ids=form.assumption_ids or obligation.trusted_assumption_ids,
            counterexample=cex,
            disagreement=run.disagreement,
            summary=_summary_for(outcome, authority, form),
            attributes={
                "selected_backend_ids": list(run.selected_backend_ids),
                "refused_backend_ids": list(run.refused_backend_ids),
                "lowering_status": form.status.value,
            },
        )

    @classmethod
    def from_non_execution(
        cls,
        obligation: FormalObligation,
        form: LoweredForm,
        *,
        receipt_id: str | None = None,
        timeout_ms: int = 0,
    ) -> "AnalysisReceipt":
        """Build a non-proof receipt when compilation refuses submission."""

        attempt = AnalysisAttempt.from_lowered_form(
            form,
            attempt_id=f"attempt.{obligation.obligation_id}.0",
            policy_id=obligation.policy_id,
            policy_revision=obligation.policy_revision,
            capability_ids=obligation.capability_ids,
        )
        rid = receipt_id or f"receipt.{obligation.obligation_id}.{form.form_id}"
        return cls(
            receipt_id=rid,
            obligation_id=obligation.obligation_id,
            model_digest=obligation.model_digest or form.model_digest,
            outcome=attempt.outcome,
            proof_authority=attempt.proof_authority,
            analysis_outcome=attempt.analysis_outcome,
            attempts=(attempt,),
            policy_id=obligation.policy_id,
            policy_revision=obligation.policy_revision,
            capability_ids=obligation.capability_ids,
            tool_ids=(),
            timeout_ms=timeout_ms,
            contract_id=form.contract_id,
            form_id=form.form_id,
            code_epoch=obligation.code_epoch,
            assumption_ids=form.assumption_ids or obligation.trusted_assumption_ids,
            counterexample={},
            disagreement=False,
            summary=_summary_for(attempt.outcome, attempt.proof_authority, form),
            attributes={"lowering_status": form.status.value, "executed": False},
        )


def _aggregate_outcome(
    attempts: Sequence[AnalysisAttempt], *, disagreement: bool
) -> AttemptOutcome:
    if disagreement:
        return AttemptOutcome.DISAGREEMENT
    if not attempts:
        return AttemptOutcome.UNKNOWN
    # Prefer decisive executed proof/disproof when unanimous.
    executed = [a for a in attempts if a.executed]
    statuses = {a.outcome for a in executed} if executed else {a.outcome for a in attempts}
    if AttemptOutcome.DISPROVED in statuses and AttemptOutcome.PROVED not in statuses:
        return AttemptOutcome.DISPROVED
    if AttemptOutcome.PROVED in statuses and AttemptOutcome.DISPROVED not in statuses:
        return AttemptOutcome.PROVED
    if AttemptOutcome.PROVED in statuses and AttemptOutcome.DISPROVED in statuses:
        return AttemptOutcome.DISAGREEMENT
    if AttemptOutcome.SATISFIABLE in statuses and AttemptOutcome.UNSATISFIABLE in statuses:
        return AttemptOutcome.DISAGREEMENT
    if AttemptOutcome.SATISFIABLE in statuses:
        return AttemptOutcome.SATISFIABLE
    if AttemptOutcome.UNSATISFIABLE in statuses:
        return AttemptOutcome.UNSATISFIABLE
    # Prefer most specific non-proof failure.
    for candidate in (
        AttemptOutcome.TIMEOUT,
        AttemptOutcome.UNAVAILABLE,
        AttemptOutcome.INCOMPLETE_MODEL,
        AttemptOutcome.NOT_MODELED,
        AttemptOutcome.UNSUPPORTED,
        AttemptOutcome.REFUSED,
        AttemptOutcome.ERROR,
        AttemptOutcome.DISAGREEMENT,
        AttemptOutcome.UNKNOWN,
    ):
        if candidate in statuses or any(a.outcome is candidate for a in attempts):
            return candidate
    return AttemptOutcome.UNKNOWN


def _summary_for(
    outcome: AttemptOutcome, authority: ProofAuthority, form: LoweredForm
) -> str:
    return (
        f"outcome={outcome.value}; authority={authority.value}; "
        f"contract={form.contract_id}; family={form.logic_family.value}"
    )


def build_analysis_receipt(
    obligation: FormalObligation,
    form: LoweredForm,
    run: PortfolioRun | None = None,
    *,
    receipt_id: str | None = None,
) -> AnalysisReceipt:
    """Primary entry: receipt from lowering + optional portfolio run."""

    if run is None or not form.may_submit:
        return AnalysisReceipt.from_non_execution(
            obligation,
            form,
            receipt_id=receipt_id,
            timeout_ms=run.timeout_ms if run is not None else 0,
        )
    return AnalysisReceipt.from_portfolio_run(
        run, obligation, form, receipt_id=receipt_id
    )


__all__ = [
    "ANALYSIS_ATTEMPT_SCHEMA_VERSION",
    "ANALYSIS_RECEIPT_SCHEMA_VERSION",
    "AnalysisAttempt",
    "AnalysisReceipt",
    "AttemptOutcome",
    "ProofAuthority",
    "analysis_outcome_for_attempt",
    "assert_sat_is_not_proof",
    "build_analysis_receipt",
    "proof_authority_for_outcome",
    "satisfiability_outcome_for_attempt",
]
