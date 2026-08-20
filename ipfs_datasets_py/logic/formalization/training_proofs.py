"""Statement-bound proof-attempt and tactic-trace contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind

from .training_shared import (
    IR_PROOF_TRACE_INTERFACE,
    IR_PROOF_TRACE_SCHEMA_VERSION,
    IR_TACTIC_TRACE_INTERFACE,
    IR_TACTIC_TRACE_SCHEMA_VERSION,
    TACTIC_STEP_INTERFACE,
    TACTIC_STEP_SCHEMA_VERSION,
    EvidenceStatus,
    ExampleKind,
    LabelAuthority,
    LabelEvidence,
    LineageBinding,
    ProducerKind,
    ProofOutcome,
    StatementBinding,
    TacticOutcome,
    TacticStepOutcome,
    ToolBinding,
    TrainingContractValidationError,
    _bind_statement_to_lineage,
    _CanonicalRecord,
    _digest,
    _enum,
    _identifier,
    _mapping,
    _normalize_evidence,
    _reject_unknown,
    _sequence,
    _text,
    _unique_texts,
    _validate_evidence_subjects,
)


def _optional_tool(value: Any, field_name: str) -> ToolBinding | None:
    if value is None:
        return None
    if isinstance(value, ToolBinding):
        return value
    return ToolBinding.from_dict(_mapping(value, field_name))


def _normalize_assumptions(ids: Any, digests: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    raw_ids = tuple(
        _identifier(item, "assumption_ids") for item in _sequence(ids, "assumption_ids")
    )
    raw_digests = tuple(
        _digest(item, "assumption_digests") for item in _sequence(digests, "assumption_digests")
    )
    if len(raw_ids) != len(raw_digests):
        raise TrainingContractValidationError("assumption IDs and digests must have equal lengths")
    if len(raw_ids) != len(set(raw_ids)):
        raise TrainingContractValidationError("assumption IDs must be unique")
    pairs = tuple(sorted(zip(raw_ids, raw_digests, strict=True)))
    return tuple(item[0] for item in pairs), tuple(item[1] for item in pairs)


def _verified_proof_evidence(
    evidence: tuple[LabelEvidence, ...],
    statement: StatementBinding,
    checker: ToolBinding | None,
    receipt_digest: str,
) -> bool:
    if checker is None or not receipt_digest:
        return False
    return any(
        item.status is EvidenceStatus.VERIFIED
        and item.authority is LabelAuthority.INDEPENDENT_PROOF_CHECKER
        and item.independent
        and item.result_authority is AuthorityKind.THEOREM_PROOF
        and item.subject_statement_ids == (statement.statement_id,)
        and item.subject_statement_digests == (statement.statement_digest,)
        and item.producer_id == checker.tool_id
        and item.producer_version == checker.tool_version
        and item.evidence_digest == receipt_digest
        for item in evidence
    )


def _verified_negative_evidence(
    evidence: tuple[LabelEvidence, ...],
    statement: StatementBinding,
    checker: ToolBinding | None,
    receipt_digest: str,
) -> bool:
    if checker is None or not receipt_digest:
        return False
    return any(
        item.status is EvidenceStatus.VERIFIED
        and item.authority is LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER
        and item.independent
        and item.result_authority is AuthorityKind.SATISFIABILITY
        and item.subject_statement_ids == (statement.statement_id,)
        and item.subject_statement_digests == (statement.statement_digest,)
        and item.producer_id == checker.tool_id
        and item.producer_version == checker.tool_version
        and item.evidence_digest == receipt_digest
        for item in evidence
    )


@dataclass(frozen=True, slots=True)
class IRProofTrace(_CanonicalRecord):
    """Complete proof attempt; only an independently checked receipt is authoritative."""

    INTERFACE: ClassVar[str] = IR_PROOF_TRACE_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = IR_PROOF_TRACE_SCHEMA_VERSION
    IDENTITY_SUFFIX: ClassVar[str] = "proof-trace"
    COLLECTION_SCHEMA: ClassVar[Mapping[str, str]] = {
        "/assumption_ids": "ordered",
        "/assumption_digests": "ordered",
        "/evidence": "set-like",
        "/diagnostics": "set-like",
    }
    KIND: ClassVar[ExampleKind] = ExampleKind.PROOF

    trace_id: str
    lineage: LineageBinding
    statement: StatementBinding
    claim_id: str
    claim_digest: str
    obligation_id: str
    obligation_digest: str
    assumption_ids: tuple[str, ...]
    assumption_digests: tuple[str, ...]
    request_digest: str
    attempt_digest: str
    result_digest: str
    output_digest: str
    producer: ToolBinding
    outcome: ProofOutcome
    evidence: tuple[LabelEvidence, ...] = ()
    checker: ToolBinding | None = None
    proof_receipt_digest: str = ""
    diagnostics: tuple[str, ...] = ()
    schema_version: str = IR_PROOF_TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _identifier(self.trace_id, "trace_id"))
        if not isinstance(self.lineage, LineageBinding):
            object.__setattr__(
                self, "lineage", LineageBinding.from_dict(_mapping(self.lineage, "lineage"))
            )
        if not isinstance(self.statement, StatementBinding):
            object.__setattr__(
                self,
                "statement",
                StatementBinding.from_dict(_mapping(self.statement, "statement")),
            )
        object.__setattr__(self, "claim_id", _identifier(self.claim_id, "claim_id"))
        object.__setattr__(self, "claim_digest", _digest(self.claim_digest, "claim_digest"))
        object.__setattr__(self, "obligation_id", _identifier(self.obligation_id, "obligation_id"))
        object.__setattr__(
            self,
            "obligation_digest",
            _digest(self.obligation_digest, "obligation_digest"),
        )
        ids, digests = _normalize_assumptions(self.assumption_ids, self.assumption_digests)
        object.__setattr__(self, "assumption_ids", ids)
        object.__setattr__(self, "assumption_digests", digests)
        object.__setattr__(self, "request_digest", _digest(self.request_digest, "request_digest"))
        object.__setattr__(self, "attempt_digest", _digest(self.attempt_digest, "attempt_digest"))
        object.__setattr__(
            self, "result_digest", _digest(self.result_digest, "result_digest", allow_empty=True)
        )
        object.__setattr__(
            self,
            "output_digest",
            _digest(self.output_digest, "output_digest", allow_empty=True),
        )
        if not isinstance(self.producer, ToolBinding):
            object.__setattr__(
                self, "producer", ToolBinding.from_dict(_mapping(self.producer, "producer"))
            )
        object.__setattr__(self, "outcome", _enum(self.outcome, ProofOutcome, "outcome"))
        object.__setattr__(self, "evidence", _normalize_evidence(self.evidence))
        object.__setattr__(self, "checker", _optional_tool(self.checker, "checker"))
        object.__setattr__(
            self,
            "proof_receipt_digest",
            _digest(
                self.proof_receipt_digest,
                "proof_receipt_digest",
                allow_empty=True,
            ),
        )
        object.__setattr__(self, "diagnostics", _unique_texts(self.diagnostics, "diagnostics"))
        object.__setattr__(self, "schema_version", _text(self.schema_version, "schema_version"))
        if self.schema_version != self.SCHEMA_VERSION:
            raise TrainingContractValidationError(
                f"unsupported proof trace schema: {self.schema_version!r}"
            )
        _bind_statement_to_lineage(self.statement, self.lineage)
        _validate_evidence_subjects(self.evidence, (self.statement,))
        if self.producer.producer_kind not in {
            ProducerKind.MODEL,
            ProducerKind.PROVER,
            ProducerKind.SOLVER,
            ProducerKind.GENERIC_DETERMINISTIC,
        }:
            raise TrainingContractValidationError(
                f"{self.producer.producer_kind.value} cannot produce a proof attempt"
            )
        if self.checker is not None:
            if self.checker.producer_kind is not ProducerKind.CHECKER:
                raise TrainingContractValidationError("proof checker must have checker role")
            if self.checker.tool_id == self.producer.tool_id:
                raise TrainingContractValidationError(
                    "proof producer cannot independently check itself"
                )
        if self.outcome is ProofOutcome.PROVED:
            if not self.result_digest or not self.output_digest or not self.proof_receipt_digest:
                raise TrainingContractValidationError(
                    "proved trace must bind output and affirmative proof receipt"
                )
            if self.checker is None or not _verified_proof_evidence(
                self.evidence,
                self.statement,
                self.checker,
                self.proof_receipt_digest,
            ):
                raise TrainingContractValidationError(
                    "proved trace requires exact independent theorem-proof evidence"
                )
        elif self.outcome is ProofOutcome.DISPROVED:
            if not self.result_digest or not self.output_digest:
                raise TrainingContractValidationError(
                    "disproved trace must bind a checked counterexample or refutation"
                )
            if self.checker is None or not _verified_negative_evidence(
                self.evidence,
                self.statement,
                self.checker,
                self.output_digest,
            ):
                raise TrainingContractValidationError(
                    "disproved trace requires independent negative evidence"
                )
            if self.proof_receipt_digest:
                raise TrainingContractValidationError(
                    "disproved trace cannot carry an affirmative proof receipt"
                )
        else:
            if self.proof_receipt_digest:
                raise TrainingContractValidationError(
                    "non-proved trace cannot carry an affirmative proof receipt"
                )
            if any(
                item.status is EvidenceStatus.VERIFIED
                and item.authority
                in {
                    LabelAuthority.INDEPENDENT_PROOF_CHECKER,
                    LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER,
                }
                for item in self.evidence
            ):
                raise TrainingContractValidationError(
                    "unknown/timeout proof outcome cannot retain a verified proof label"
                )

    @property
    def kind(self) -> ExampleKind:
        return self.KIND

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_digests": list(self.assumption_digests),
            "assumption_ids": list(self.assumption_ids),
            "attempt_digest": self.attempt_digest,
            "checker": self.checker.to_dict() if self.checker else None,
            "claim_digest": self.claim_digest,
            "claim_id": self.claim_id,
            "diagnostics": list(self.diagnostics),
            "evidence": [item.to_dict() for item in self.evidence],
            "lineage": self.lineage.to_dict(),
            "obligation_digest": self.obligation_digest,
            "obligation_id": self.obligation_id,
            "outcome": self.outcome.value,
            "output_digest": self.output_digest,
            "producer": self.producer.to_dict(),
            "proof_receipt_digest": self.proof_receipt_digest,
            "request_digest": self.request_digest,
            "result_digest": self.result_digest,
            "schema_version": self.schema_version,
            "statement": self.statement.to_dict(),
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> IRProofTrace:
        value = _mapping(value, "proof trace")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumption_digests",
                    "assumption_ids",
                    "attempt_digest",
                    "checker",
                    "claim_digest",
                    "claim_id",
                    "diagnostics",
                    "evidence",
                    "lineage",
                    "obligation_digest",
                    "obligation_id",
                    "outcome",
                    "output_digest",
                    "producer",
                    "proof_receipt_digest",
                    "request_digest",
                    "result_digest",
                    "schema_version",
                    "statement",
                    "trace_id",
                }
            ),
            "proof trace",
        )
        return cls(
            trace_id=value.get("trace_id", ""),
            lineage=LineageBinding.from_dict(_mapping(value.get("lineage", {}), "lineage")),
            statement=StatementBinding.from_dict(_mapping(value.get("statement", {}), "statement")),
            claim_id=value.get("claim_id", ""),
            claim_digest=value.get("claim_digest", ""),
            obligation_id=value.get("obligation_id", ""),
            obligation_digest=value.get("obligation_digest", ""),
            assumption_ids=tuple(_sequence(value.get("assumption_ids", ()), "assumption_ids")),
            assumption_digests=tuple(
                _sequence(value.get("assumption_digests", ()), "assumption_digests")
            ),
            request_digest=value.get("request_digest", ""),
            attempt_digest=value.get("attempt_digest", ""),
            result_digest=value.get("result_digest", ""),
            output_digest=value.get("output_digest", ""),
            producer=ToolBinding.from_dict(_mapping(value.get("producer", {}), "producer")),
            outcome=value.get("outcome", ProofOutcome.UNKNOWN.value),
            evidence=tuple(_sequence(value.get("evidence", ()), "evidence")),
            checker=(
                ToolBinding.from_dict(_mapping(value["checker"], "checker"))
                if value.get("checker") is not None
                else None
            ),
            proof_receipt_digest=value.get("proof_receipt_digest", ""),
            diagnostics=tuple(_sequence(value.get("diagnostics", ()), "diagnostics")),
            schema_version=value.get("schema_version", IR_PROOF_TRACE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class TacticStep(_CanonicalRecord):
    """One ordered tactic transition; success is not itself proof authority."""

    INTERFACE: ClassVar[str] = TACTIC_STEP_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = TACTIC_STEP_SCHEMA_VERSION
    IDENTITY_SUFFIX: ClassVar[str] = "tactic-step"
    COLLECTION_SCHEMA: ClassVar[Mapping[str, str]] = {
        "/premise_statement_ids": "ordered",
        "/premise_statement_digests": "ordered",
    }

    step_id: str
    index: int
    input_state_digest: str
    tactic: str
    output_state_digest: str
    premise_statement_ids: tuple[str, ...]
    premise_statement_digests: tuple[str, ...]
    outcome: TacticStepOutcome
    schema_version: str = TACTIC_STEP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _identifier(self.step_id, "step_id"))
        if isinstance(self.index, bool) or not isinstance(self.index, int) or self.index < 0:
            raise TrainingContractValidationError(
                "tactic step index must be a non-negative integer"
            )
        object.__setattr__(
            self,
            "input_state_digest",
            _digest(self.input_state_digest, "input_state_digest"),
        )
        object.__setattr__(self, "tactic", _text(self.tactic, "tactic"))
        object.__setattr__(
            self,
            "output_state_digest",
            _digest(self.output_state_digest, "output_state_digest", allow_empty=True),
        )
        ids, digests = _normalize_assumptions(
            self.premise_statement_ids, self.premise_statement_digests
        )
        object.__setattr__(self, "premise_statement_ids", ids)
        object.__setattr__(self, "premise_statement_digests", digests)
        object.__setattr__(self, "outcome", _enum(self.outcome, TacticStepOutcome, "outcome"))
        object.__setattr__(self, "schema_version", _text(self.schema_version, "schema_version"))
        if self.schema_version != self.SCHEMA_VERSION:
            raise TrainingContractValidationError(
                f"unsupported tactic step schema: {self.schema_version!r}"
            )
        if self.outcome is TacticStepOutcome.SUCCEEDED and not self.output_state_digest:
            raise TrainingContractValidationError(
                "successful tactic step must bind its output state"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "input_state_digest": self.input_state_digest,
            "outcome": self.outcome.value,
            "output_state_digest": self.output_state_digest,
            "premise_statement_digests": list(self.premise_statement_digests),
            "premise_statement_ids": list(self.premise_statement_ids),
            "schema_version": self.schema_version,
            "step_id": self.step_id,
            "tactic": self.tactic,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TacticStep:
        value = _mapping(value, "tactic step")
        _reject_unknown(
            value,
            frozenset(
                {
                    "index",
                    "input_state_digest",
                    "outcome",
                    "output_state_digest",
                    "premise_statement_digests",
                    "premise_statement_ids",
                    "schema_version",
                    "step_id",
                    "tactic",
                }
            ),
            "tactic step",
        )
        return cls(
            step_id=value.get("step_id", ""),
            index=value.get("index", -1),
            input_state_digest=value.get("input_state_digest", ""),
            tactic=value.get("tactic", ""),
            output_state_digest=value.get("output_state_digest", ""),
            premise_statement_ids=tuple(
                _sequence(value.get("premise_statement_ids", ()), "premise_statement_ids")
            ),
            premise_statement_digests=tuple(
                _sequence(
                    value.get("premise_statement_digests", ()),
                    "premise_statement_digests",
                )
            ),
            outcome=value.get("outcome", TacticStepOutcome.UNKNOWN.value),
            schema_version=value.get("schema_version", TACTIC_STEP_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class IRTacticTrace(_CanonicalRecord):
    """Ordered tactic proposal/transition trace with an independent proof gate."""

    INTERFACE: ClassVar[str] = IR_TACTIC_TRACE_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = IR_TACTIC_TRACE_SCHEMA_VERSION
    IDENTITY_SUFFIX: ClassVar[str] = "tactic-trace"
    COLLECTION_SCHEMA: ClassVar[Mapping[str, str]] = {
        "/steps": "ordered",
        "/evidence": "set-like",
        "/diagnostics": "set-like",
    }
    KIND: ClassVar[ExampleKind] = ExampleKind.TACTIC

    trace_id: str
    lineage: LineageBinding
    statement: StatementBinding
    obligation_id: str
    obligation_digest: str
    initial_state_digest: str
    final_state_digest: str
    producer: ToolBinding
    steps: tuple[TacticStep, ...]
    outcome: TacticOutcome
    evidence: tuple[LabelEvidence, ...] = ()
    checker: ToolBinding | None = None
    proof_trace_digest: str = ""
    diagnostics: tuple[str, ...] = ()
    schema_version: str = IR_TACTIC_TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _identifier(self.trace_id, "trace_id"))
        if not isinstance(self.lineage, LineageBinding):
            object.__setattr__(
                self, "lineage", LineageBinding.from_dict(_mapping(self.lineage, "lineage"))
            )
        if not isinstance(self.statement, StatementBinding):
            object.__setattr__(
                self,
                "statement",
                StatementBinding.from_dict(_mapping(self.statement, "statement")),
            )
        object.__setattr__(self, "obligation_id", _identifier(self.obligation_id, "obligation_id"))
        object.__setattr__(
            self,
            "obligation_digest",
            _digest(self.obligation_digest, "obligation_digest"),
        )
        object.__setattr__(
            self,
            "initial_state_digest",
            _digest(self.initial_state_digest, "initial_state_digest"),
        )
        object.__setattr__(
            self,
            "final_state_digest",
            _digest(self.final_state_digest, "final_state_digest", allow_empty=True),
        )
        if not isinstance(self.producer, ToolBinding):
            object.__setattr__(
                self, "producer", ToolBinding.from_dict(_mapping(self.producer, "producer"))
            )
        steps = tuple(
            item
            if isinstance(item, TacticStep)
            else TacticStep.from_dict(_mapping(item, "tactic step"))
            for item in _sequence(self.steps, "steps")
        )
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "outcome", _enum(self.outcome, TacticOutcome, "outcome"))
        object.__setattr__(self, "evidence", _normalize_evidence(self.evidence))
        object.__setattr__(self, "checker", _optional_tool(self.checker, "checker"))
        object.__setattr__(
            self,
            "proof_trace_digest",
            _digest(self.proof_trace_digest, "proof_trace_digest", allow_empty=True),
        )
        object.__setattr__(self, "diagnostics", _unique_texts(self.diagnostics, "diagnostics"))
        object.__setattr__(self, "schema_version", _text(self.schema_version, "schema_version"))
        if self.schema_version != self.SCHEMA_VERSION:
            raise TrainingContractValidationError(
                f"unsupported tactic trace schema: {self.schema_version!r}"
            )
        _bind_statement_to_lineage(self.statement, self.lineage)
        _validate_evidence_subjects(self.evidence, (self.statement,))
        if self.producer.producer_kind not in {
            ProducerKind.TACTICIAN,
            ProducerKind.MODEL,
            ProducerKind.GENERIC_DETERMINISTIC,
        }:
            raise TrainingContractValidationError(
                f"{self.producer.producer_kind.value} cannot produce a tactic trace"
            )
        ids = tuple(item.step_id for item in self.steps)
        indices = tuple(item.index for item in self.steps)
        if len(ids) != len(set(ids)):
            raise TrainingContractValidationError("tactic step IDs must be unique")
        if indices != tuple(range(len(self.steps))):
            raise TrainingContractValidationError(
                "tactic step indices must be contiguous and begin at zero"
            )
        if self.steps:
            if self.steps[0].input_state_digest != self.initial_state_digest:
                raise TrainingContractValidationError(
                    "first tactic step does not begin at initial state"
                )
            for previous, current in zip(self.steps, self.steps[1:], strict=False):
                previous_state = previous.output_state_digest or previous.input_state_digest
                if previous_state != current.input_state_digest:
                    raise TrainingContractValidationError(
                        "adjacent tactic states are not contiguous"
                    )
            terminal_state = self.steps[-1].output_state_digest or self.steps[-1].input_state_digest
            if self.final_state_digest and terminal_state != self.final_state_digest:
                raise TrainingContractValidationError("last tactic step does not bind final state")
        elif self.final_state_digest and self.final_state_digest != self.initial_state_digest:
            raise TrainingContractValidationError("empty tactic trace cannot change proof state")
        if self.checker is not None:
            if self.checker.producer_kind is not ProducerKind.CHECKER:
                raise TrainingContractValidationError("tactic checker must have checker role")
            if self.checker.tool_id == self.producer.tool_id:
                raise TrainingContractValidationError(
                    "tactic producer cannot independently check itself"
                )
        if self.outcome in {
            TacticOutcome.VERIFIED_SUCCESS,
            TacticOutcome.CANDIDATE_SUCCESS,
        } and (
            not self.steps
            or self.steps[-1].outcome is not TacticStepOutcome.SUCCEEDED
            or not self.final_state_digest
        ):
            raise TrainingContractValidationError(
                "successful tactic outcome requires a successful final step and state"
            )
        if self.outcome is TacticOutcome.VERIFIED_SUCCESS:
            if (
                not self.proof_trace_digest
                or self.checker is None
                or not _verified_proof_evidence(
                    self.evidence,
                    self.statement,
                    self.checker,
                    self.proof_trace_digest,
                )
            ):
                raise TrainingContractValidationError(
                    "verified tactic success requires a bound independently checked proof trace"
                )
        elif self.outcome is TacticOutcome.COUNTEREXAMPLE:
            if (
                not self.final_state_digest
                or self.proof_trace_digest
                or self.checker is None
                or not _verified_negative_evidence(
                    self.evidence,
                    self.statement,
                    self.checker,
                    self.final_state_digest,
                )
            ):
                raise TrainingContractValidationError(
                    "counterexample tactic outcome requires independent checked evidence"
                )
        else:
            if self.proof_trace_digest:
                raise TrainingContractValidationError(
                    "non-verified tactic outcome cannot carry proof authority"
                )
            if any(
                item.status is EvidenceStatus.VERIFIED
                and item.authority is LabelAuthority.INDEPENDENT_PROOF_CHECKER
                for item in self.evidence
            ):
                raise TrainingContractValidationError(
                    "non-verified tactic outcome cannot retain a verified proof label"
                )

    @property
    def kind(self) -> ExampleKind:
        return self.KIND

    def to_dict(self) -> dict[str, Any]:
        return {
            "checker": self.checker.to_dict() if self.checker else None,
            "diagnostics": list(self.diagnostics),
            "evidence": [item.to_dict() for item in self.evidence],
            "final_state_digest": self.final_state_digest,
            "initial_state_digest": self.initial_state_digest,
            "lineage": self.lineage.to_dict(),
            "obligation_digest": self.obligation_digest,
            "obligation_id": self.obligation_id,
            "outcome": self.outcome.value,
            "producer": self.producer.to_dict(),
            "proof_trace_digest": self.proof_trace_digest,
            "schema_version": self.schema_version,
            "statement": self.statement.to_dict(),
            "steps": [item.to_dict() for item in self.steps],
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> IRTacticTrace:
        value = _mapping(value, "tactic trace")
        _reject_unknown(
            value,
            frozenset(
                {
                    "checker",
                    "diagnostics",
                    "evidence",
                    "final_state_digest",
                    "initial_state_digest",
                    "lineage",
                    "obligation_digest",
                    "obligation_id",
                    "outcome",
                    "producer",
                    "proof_trace_digest",
                    "schema_version",
                    "statement",
                    "steps",
                    "trace_id",
                }
            ),
            "tactic trace",
        )
        return cls(
            trace_id=value.get("trace_id", ""),
            lineage=LineageBinding.from_dict(_mapping(value.get("lineage", {}), "lineage")),
            statement=StatementBinding.from_dict(_mapping(value.get("statement", {}), "statement")),
            obligation_id=value.get("obligation_id", ""),
            obligation_digest=value.get("obligation_digest", ""),
            initial_state_digest=value.get("initial_state_digest", ""),
            final_state_digest=value.get("final_state_digest", ""),
            producer=ToolBinding.from_dict(_mapping(value.get("producer", {}), "producer")),
            steps=tuple(
                TacticStep.from_dict(_mapping(item, "tactic step"))
                for item in _sequence(value.get("steps", ()), "steps")
            ),
            outcome=value.get("outcome", TacticOutcome.UNKNOWN.value),
            evidence=tuple(_sequence(value.get("evidence", ()), "evidence")),
            checker=(
                ToolBinding.from_dict(_mapping(value["checker"], "checker"))
                if value.get("checker") is not None
                else None
            ),
            proof_trace_digest=value.get("proof_trace_digest", ""),
            diagnostics=tuple(_sequence(value.get("diagnostics", ()), "diagnostics")),
            schema_version=value.get("schema_version", IR_TACTIC_TRACE_SCHEMA_VERSION),
        )


__all__ = ["IRProofTrace", "IRTacticTrace", "TacticStep"]
