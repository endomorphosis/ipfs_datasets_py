"""Counterexample traces that can disprove obligations (CRYPTOIR-G330).

A useful counterexample can **disprove** an obligation even when successful
simulation traces cannot **prove** it.  Counterexample authority is therefore:

* :attr:`CounterexampleAuthority.DISPROOF_WITNESS` — violating trace that
  supports analysis :attr:`~.verdicts.AnalysisOutcome.DISPROVED`;
* :attr:`CounterexampleAuthority.MONITOR_ONLY` / ``EVIDENCE_ONLY`` — non-proof;
* never theorem :attr:`~.verdicts.AnalysisOutcome.PROVED`.

Traces are replayable against offline sandboxes so witnesses remain checkable.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final

from ..ir_core.identity import CanonicalIdentity
from ..ir_core.provenance import ProvenanceValidationError, thaw_json
from .identity import crypto_ir_identity
from .model import CryptoIRValidationError
from .provenance import AuthorityKind, CryptoIRProvenanceError, freeze_json_mapping
from .schema_versions import CRYPTO_IR_KERNEL_SCHEMA_VERSION
from .simulation import (
    DeterministicOfflineSandbox,
    OfflineSandbox,
    SimulationError,
    SimulationOutcome,
    SimulationReceipt,
    SimulationRequest,
    SimulationStep,
    StateSnapshot,
    analysis_outcome_for_simulation,
    run_simulation,
)
from .verdicts import AnalysisOutcome, MonitorOutcome


CRYPTO_IR_COUNTEREXAMPLE_DOMAIN: Final[str] = "crypto-ir.counterexample"
CRYPTO_IR_COUNTEREXAMPLE_SCHEMA_VERSION: Final[str] = CRYPTO_IR_KERNEL_SCHEMA_VERSION
COUNTEREXAMPLE_TRACE_SCHEMA_VERSION: Final[str] = "crypto-ir.counterexample-trace@1.0.0"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class CounterexampleError(CryptoIRValidationError):
    """Raised when a counterexample trace is malformed or fails replay."""


class CounterexampleAuthority(str, Enum):
    """Authority of a counterexample witness.

    Disproof witnesses can support obligation disproof.  They never promote a
    successful monitor run into theorem proof.
    """

    DISPROOF_WITNESS = "disproof_witness"
    MONITOR_ONLY = "monitor_only"
    EVIDENCE_ONLY = "evidence_only"
    NON_PROOF = "non_proof"


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CounterexampleError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise CounterexampleError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise CounterexampleError(f"{name} must not have surrounding whitespace")
    return value


def _identifier(value: Any, name: str) -> str:
    normalized = _text(value, name)
    if not _ID_RE.fullmatch(normalized):
        raise CounterexampleError(f"{name} is not a stable identifier")
    return normalized


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CounterexampleError(f"{name} must be a mapping")
    return value


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (
        ProvenanceValidationError,
        CryptoIRProvenanceError,
        TypeError,
        ValueError,
    ) as exc:
        raise CounterexampleError(str(exc)) from exc


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise CounterexampleError(f"unsupported {name}: {value!r}") from exc


def authority_for_counterexample(
    outcome: SimulationOutcome | str,
) -> CounterexampleAuthority:
    """Map a simulation outcome onto counterexample authority."""

    value = _enum(SimulationOutcome, outcome, "outcome")
    if value is SimulationOutcome.VIOLATION:
        return CounterexampleAuthority.DISPROOF_WITNESS
    if value is SimulationOutcome.SUCCESS:
        return CounterexampleAuthority.MONITOR_ONLY
    if value in {
        SimulationOutcome.REVERT,
        SimulationOutcome.TIMEOUT,
        SimulationOutcome.BOUND_EXCEEDED,
    }:
        return CounterexampleAuthority.EVIDENCE_ONLY
    return CounterexampleAuthority.NON_PROOF


@dataclass(frozen=True, slots=True)
class CounterexampleTrace:
    """Replayable witness trace that may disprove a named obligation.

    ``replayable`` is true only when the trace binds enough state (snapshot,
    call input, steps) to re-execute deterministically offline.
    """

    trace_id: str
    obligation_id: str
    outcome: SimulationOutcome
    authority: CounterexampleAuthority
    snapshot_digest: str
    input_digest: str
    steps: tuple[SimulationStep, ...] = ()
    receipt_id: str = ""
    request_id: str = ""
    chain_namespace: str = ""
    block_or_slot: str = ""
    call_input: Mapping[str, Any] = field(default_factory=dict)
    snapshot: StateSnapshot | None = None
    post_state_digest: str = ""
    reason: str = ""
    replayable: bool = False
    analysis_outcome: AnalysisOutcome = AnalysisOutcome.UNKNOWN
    monitor_outcome: MonitorOutcome = MonitorOutcome.UNKNOWN
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = COUNTEREXAMPLE_TRACE_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _identifier(self.trace_id, "trace_id"))
        object.__setattr__(
            self, "obligation_id", _identifier(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self, "outcome", _enum(SimulationOutcome, self.outcome, "outcome")
        )
        object.__setattr__(
            self,
            "authority",
            _enum(CounterexampleAuthority, self.authority, "authority"),
        )
        expected = authority_for_counterexample(self.outcome)
        if self.authority is not expected:
            raise CounterexampleError(
                f"authority {self.authority.value} inconsistent with outcome "
                f"{self.outcome.value} (expected {expected.value})"
            )
        object.__setattr__(
            self, "snapshot_digest", _text(self.snapshot_digest, "snapshot_digest")
        )
        object.__setattr__(
            self, "input_digest", _text(self.input_digest, "input_digest")
        )
        steps = tuple(
            item
            if isinstance(item, SimulationStep)
            else SimulationStep.from_dict(_as_mapping(item, "steps"))
            for item in (self.steps or ())
        )
        object.__setattr__(self, "steps", steps)
        for name in (
            "receipt_id",
            "request_id",
            "chain_namespace",
            "block_or_slot",
            "post_state_digest",
            "reason",
        ):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        object.__setattr__(self, "call_input", _attributes(self.call_input))
        if self.snapshot is not None and not isinstance(self.snapshot, StateSnapshot):
            object.__setattr__(
                self,
                "snapshot",
                StateSnapshot.from_dict(_as_mapping(self.snapshot, "snapshot")),
            )
        if not isinstance(self.replayable, bool):
            raise CounterexampleError("replayable must be a bool")
        # Replayability requires snapshot + call_input binding.
        can_replay = self.snapshot is not None and bool(self.call_input)
        if self.replayable and not can_replay:
            raise CounterexampleError(
                "replayable counterexample requires snapshot and call_input"
            )
        object.__setattr__(
            self,
            "analysis_outcome",
            _enum(AnalysisOutcome, self.analysis_outcome, "analysis_outcome"),
        )
        object.__setattr__(
            self,
            "monitor_outcome",
            _enum(MonitorOutcome, self.monitor_outcome, "monitor_outcome"),
        )
        if self.analysis_outcome is AnalysisOutcome.PROVED:
            raise CounterexampleError(
                "counterexample cannot claim analysis PROVED"
            )
        if (
            self.authority is CounterexampleAuthority.DISPROOF_WITNESS
            and self.analysis_outcome is not AnalysisOutcome.DISPROVED
        ):
            raise CounterexampleError(
                "disproof witness must project to analysis DISPROVED"
            )
        if (
            self.authority is not CounterexampleAuthority.DISPROOF_WITNESS
            and self.analysis_outcome is AnalysisOutcome.DISPROVED
        ):
            raise CounterexampleError(
                "analysis DISPROVED requires disproof_witness authority"
            )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def disproves_obligation(self) -> bool:
        """True when this witness is sufficient to disprove the obligation."""

        return (
            self.authority is CounterexampleAuthority.DISPROOF_WITNESS
            and self.analysis_outcome is AnalysisOutcome.DISPROVED
            and self.outcome is SimulationOutcome.VIOLATION
        )

    @property
    def is_non_proof(self) -> bool:
        return self.analysis_outcome is not AnalysisOutcome.PROVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_outcome": (
                self.analysis_outcome.value
                if isinstance(self.analysis_outcome, AnalysisOutcome)
                else self.analysis_outcome
            ),
            "attributes": thaw_json(self.attributes),
            "authority": (
                self.authority.value
                if isinstance(self.authority, CounterexampleAuthority)
                else self.authority
            ),
            "block_or_slot": self.block_or_slot,
            "call_input": thaw_json(self.call_input),
            "chain_namespace": self.chain_namespace,
            "input_digest": self.input_digest,
            "monitor_outcome": (
                self.monitor_outcome.value
                if isinstance(self.monitor_outcome, MonitorOutcome)
                else self.monitor_outcome
            ),
            "obligation_id": self.obligation_id,
            "outcome": (
                self.outcome.value
                if isinstance(self.outcome, SimulationOutcome)
                else self.outcome
            ),
            "post_state_digest": self.post_state_digest,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "replayable": self.replayable,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "snapshot": None if self.snapshot is None else self.snapshot.to_dict(),
            "snapshot_digest": self.snapshot_digest,
            "steps": [step.to_dict() for step in self.steps],
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CounterexampleTrace":
        value = _as_mapping(value, "CounterexampleTrace")
        snap_raw = value.get("snapshot")
        snapshot = (
            None
            if snap_raw is None
            else StateSnapshot.from_dict(_as_mapping(snap_raw, "snapshot"))
        )
        steps = tuple(
            SimulationStep.from_dict(_as_mapping(item, "steps"))
            for item in value.get("steps", ())
        )
        return cls(
            trace_id=value.get("trace_id", ""),
            obligation_id=value.get("obligation_id", ""),
            outcome=value.get("outcome", SimulationOutcome.UNKNOWN),
            authority=value.get("authority", CounterexampleAuthority.NON_PROOF),
            snapshot_digest=value.get("snapshot_digest", ""),
            input_digest=value.get("input_digest", ""),
            steps=steps,
            receipt_id=value.get("receipt_id", ""),
            request_id=value.get("request_id", ""),
            chain_namespace=value.get("chain_namespace", ""),
            block_or_slot=value.get("block_or_slot", ""),
            call_input=value.get("call_input", {}),
            snapshot=snapshot,
            post_state_digest=value.get("post_state_digest", ""),
            reason=value.get("reason", ""),
            replayable=value.get("replayable", False),
            analysis_outcome=value.get(
                "analysis_outcome", AnalysisOutcome.UNKNOWN
            ),
            monitor_outcome=value.get("monitor_outcome", MonitorOutcome.UNKNOWN),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", COUNTEREXAMPLE_TRACE_SCHEMA_VERSION
            ),
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_COUNTEREXAMPLE_DOMAIN}.trace",
        )


def build_counterexample_from_receipt(
    receipt: SimulationReceipt,
    *,
    trace_id: str,
    request: SimulationRequest | None = None,
    obligation_id: str | None = None,
) -> CounterexampleTrace:
    """Build a counterexample trace from a simulation receipt.

    When *request* is supplied, the trace is marked replayable and binds the
    exact snapshot and call input.
    """

    if not isinstance(receipt, SimulationReceipt):
        raise CounterexampleError("receipt must be a SimulationReceipt")

    obl = obligation_id or receipt.obligation_id
    if not obl:
        raise CounterexampleError(
            "obligation_id is required to bind a counterexample to an obligation"
        )

    snapshot = request.snapshot if request is not None else None
    call_input = dict(thaw_json(request.call_input)) if request is not None else {}
    replayable = snapshot is not None and bool(call_input)

    # Prefer receipt-bound digests; fall back to request digests.
    snapshot_digest = receipt.snapshot_state_digest
    input_digest = receipt.input_digest
    if request is not None:
        if not input_digest:
            input_digest = request.input_digest()
        if not snapshot_digest:
            snapshot_digest = request.snapshot.state_digest

    return CounterexampleTrace(
        trace_id=trace_id,
        obligation_id=obl,
        outcome=receipt.outcome,
        authority=authority_for_counterexample(receipt.outcome),
        snapshot_digest=snapshot_digest,
        input_digest=input_digest,
        steps=receipt.steps,
        receipt_id=receipt.receipt_id,
        request_id=receipt.request_id,
        chain_namespace=receipt.chain_namespace,
        block_or_slot=receipt.block_or_slot,
        call_input=call_input,
        snapshot=snapshot,
        post_state_digest=receipt.post_state_digest,
        reason=receipt.reason,
        replayable=replayable,
        analysis_outcome=receipt.analysis_outcome,
        monitor_outcome=receipt.monitor_outcome,
        attributes={
            "provider_id": receipt.provider_id,
            "tool_name": receipt.tool_name,
        },
    )


def replay_counterexample(
    trace: CounterexampleTrace,
    *,
    sandbox: OfflineSandbox | None = None,
    request_id: str | None = None,
) -> SimulationReceipt:
    """Re-execute a replayable counterexample against an offline sandbox.

    Raises :class:`CounterexampleError` when the trace is not replayable or
    when the replayed outcome diverges from the recorded violation.
    """

    if not isinstance(trace, CounterexampleTrace):
        raise CounterexampleError("trace must be a CounterexampleTrace")
    if not trace.replayable or trace.snapshot is None:
        raise CounterexampleError("counterexample is not replayable")
    if not trace.call_input:
        raise CounterexampleError("counterexample missing call_input for replay")

    sb = sandbox or DeterministicOfflineSandbox()
    request = SimulationRequest(
        request_id=request_id or f"replay.{trace.trace_id}",
        snapshot=trace.snapshot,
        call_input=dict(thaw_json(trace.call_input)),
        obligation_id=trace.obligation_id,
        chain_namespace=trace.chain_namespace or trace.snapshot.chain_namespace,
        provider_id=sb.provider_id,
        tool_name=sb.tool_name,
        tool_version=sb.tool_version,
        sandbox_mode=sb.mode,
    )
    try:
        receipt = run_simulation(
            request,
            sb,
            receipt_id=f"receipt.replay.{trace.trace_id}",
        )
    except SimulationError as exc:
        raise CounterexampleError(f"replay failed: {exc}") from exc

    # For disproof witnesses, replay must reproduce a violation.
    if trace.disproves_obligation:
        if receipt.outcome is not SimulationOutcome.VIOLATION:
            raise CounterexampleError(
                f"replay did not reproduce violation "
                f"(got {receipt.outcome.value}): {receipt.reason}"
            )
        if receipt.analysis_outcome is not AnalysisOutcome.DISPROVED:
            raise CounterexampleError(
                "replay of disproof witness must project to DISPROVED"
            )
    elif receipt.outcome != trace.outcome:
        raise CounterexampleError(
            f"replay outcome mismatch: recorded={trace.outcome.value} "
            f"replayed={receipt.outcome.value}"
        )
    return receipt


def counterexample_disproves(
    trace: CounterexampleTrace,
    *,
    require_replay: bool = False,
    sandbox: OfflineSandbox | None = None,
) -> bool:
    """Return True when *trace* is a sound disproof witness for its obligation.

    Successful traces never return True (they cannot prove, and they do not
    disprove).  When *require_replay* is set, the witness must re-execute.
    """

    if not trace.disproves_obligation:
        return False
    if require_replay:
        replay_counterexample(trace, sandbox=sandbox)
    return True


def successful_trace_cannot_prove(receipt: SimulationReceipt) -> AnalysisOutcome:
    """Document the asymmetry: success → UNKNOWN, violation → DISPROVED.

    Returns the projected analysis outcome.  Success is never ``PROVED``.
    """

    outcome = analysis_outcome_for_simulation(receipt.outcome)
    if receipt.outcome is SimulationOutcome.SUCCESS and outcome is AnalysisOutcome.PROVED:
        raise CounterexampleError("successful simulation must not project to PROVED")
    return outcome


__all__ = [
    "COUNTEREXAMPLE_TRACE_SCHEMA_VERSION",
    "CRYPTO_IR_COUNTEREXAMPLE_DOMAIN",
    "CRYPTO_IR_COUNTEREXAMPLE_SCHEMA_VERSION",
    "CounterexampleAuthority",
    "CounterexampleError",
    "CounterexampleTrace",
    "authority_for_counterexample",
    "build_counterexample_from_receipt",
    "counterexample_disproves",
    "replay_counterexample",
    "successful_trace_cannot_prove",
]
