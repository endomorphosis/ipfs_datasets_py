"""Bounded sandboxed simulation over exact state snapshots (CRYPTOIR-G330).

Simulation is **monitor/evidence** authority only.  A successful trace or
``MONITOR_SATISFIED`` result never promotes to theorem proof.  A violating
trace may supply a counterexample that *disproves* an obligation (see
:mod:`.counterexamples`) without elevating successful simulations to proofs.

Design constraints (acceptance):

* state, block/slot, VM, tool, input, time, memory, trace, and network bounds
  are receipt-bound;
* state mutation is isolated to sandbox working copies;
* production forks remain opt-in;
* offline deterministic sandboxes are the default path for tests and CI.
"""

from __future__ import annotations

import copy
import hashlib
import re
import time
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Final, Protocol, runtime_checkable

from ..ir_core.canonical import canonical_json_bytes
from ..ir_core.identity import CanonicalIdentity
from ..ir_core.provenance import ProvenanceValidationError, thaw_json
from .identity import crypto_ir_identity
from .model import CryptoIRValidationError
from .provenance import AuthorityKind, CryptoIRProvenanceError, freeze_json_mapping
from .schema_versions import CRYPTO_IR_KERNEL_SCHEMA_VERSION
from .verdicts import AnalysisOutcome, MonitorOutcome, refuse_verdict_coercion, VerdictFamily


CRYPTO_IR_SIMULATION_DOMAIN: Final[str] = "crypto-ir.simulation"
CRYPTO_IR_SIMULATION_SCHEMA_VERSION: Final[str] = CRYPTO_IR_KERNEL_SCHEMA_VERSION
SIMULATION_REQUEST_SCHEMA_VERSION: Final[str] = "crypto-ir.simulation-request@1.0.0"
SIMULATION_RECEIPT_SCHEMA_VERSION: Final[str] = "crypto-ir.simulation-receipt@1.0.0"
STATE_SNAPSHOT_SCHEMA_VERSION: Final[str] = "crypto-ir.state-snapshot@1.0.0"
SIMULATION_BOUNDS_SCHEMA_VERSION: Final[str] = "crypto-ir.simulation-bounds@1.0.0"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class SimulationError(CryptoIRValidationError):
    """Raised when a simulation request, receipt, or sandbox is malformed."""


class SimulationAuthority(str, Enum):
    """Closed authority lattice for simulation outcomes.

    Simulation never produces theorem :attr:`PROOF`.  Successful runs are at
    most :attr:`MONITOR_ONLY` or :attr:`EVIDENCE_ONLY`.  A violating trace may
    carry :attr:`DISPROOF_WITNESS` so a counterexample can disprove an
    obligation without elevating successes to proofs.
    """

    MONITOR_ONLY = "monitor_only"
    EVIDENCE_ONLY = "evidence_only"
    DISPROOF_WITNESS = "disproof_witness"
    NON_PROOF = "non_proof"


class SimulationOutcome(str, Enum):
    """Terminal sandbox outcome for one bounded run."""

    SUCCESS = "success"
    REVERT = "revert"
    VIOLATION = "violation"
    TIMEOUT = "timeout"
    BOUND_EXCEEDED = "bound_exceeded"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    UNKNOWN = "unknown"
    REFUSED = "refused"


class SandboxMode(str, Enum):
    """How the sandbox materializes state."""

    OFFLINE_DETERMINISTIC = "offline_deterministic"
    INJECTED_FIXTURE = "injected_fixture"
    PRODUCTION_FORK = "production_fork"


# Outcomes that cannot claim execution completed successfully.
_NON_SUCCESS: Final[frozenset[SimulationOutcome]] = frozenset(
    {
        SimulationOutcome.REVERT,
        SimulationOutcome.VIOLATION,
        SimulationOutcome.TIMEOUT,
        SimulationOutcome.BOUND_EXCEEDED,
        SimulationOutcome.UNAVAILABLE,
        SimulationOutcome.ERROR,
        SimulationOutcome.UNKNOWN,
        SimulationOutcome.REFUSED,
    }
)


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SimulationError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise SimulationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise SimulationError(f"{name} must not have surrounding whitespace")
    return value


def _identifier(value: Any, name: str) -> str:
    normalized = _text(value, name)
    if not _ID_RE.fullmatch(normalized):
        raise SimulationError(f"{name} is not a stable identifier")
    return normalized


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SimulationError(f"{name} must be a mapping")
    return value


def _known_fields(
    value: Mapping[str, Any], allowed: frozenset[str], name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise SimulationError(f"unknown {name} field(s): {', '.join(unknown)}")


def _attributes(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except (
        ProvenanceValidationError,
        CryptoIRProvenanceError,
        TypeError,
        ValueError,
    ) as exc:
        raise SimulationError(str(exc)) from exc


def _enum(enum_type: type[Enum], value: Any, name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise SimulationError(f"unsupported {name}: {value!r}") from exc


def _non_negative_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise SimulationError(f"{name} must be a non-negative int")
    return value


def _unique_ids(values: Sequence[str] | None, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise SimulationError(f"{name} must be a sequence")
    result = tuple(_identifier(item, name) for item in values)
    if len(result) != len(set(result)):
        raise SimulationError(f"{name} values must be unique")
    return result


def _digest_of(payload: Mapping[str, Any] | Sequence[Any] | str) -> str:
    """Stable SHA-256 hex digest over canonical JSON (or UTF-8 text)."""

    if isinstance(payload, str):
        data = payload.encode("utf-8")
    else:
        data = canonical_json_bytes(payload)
    return hashlib.sha256(data).hexdigest()


def authority_for_outcome(outcome: SimulationOutcome | str) -> SimulationAuthority:
    """Map a simulation outcome onto its non-elevating authority."""

    value = _enum(SimulationOutcome, outcome, "outcome")
    if value is SimulationOutcome.VIOLATION:
        return SimulationAuthority.DISPROOF_WITNESS
    if value is SimulationOutcome.SUCCESS:
        return SimulationAuthority.MONITOR_ONLY
    if value in {
        SimulationOutcome.REVERT,
        SimulationOutcome.TIMEOUT,
        SimulationOutcome.BOUND_EXCEEDED,
    }:
        return SimulationAuthority.EVIDENCE_ONLY
    return SimulationAuthority.NON_PROOF


def monitor_outcome_for_simulation(
    outcome: SimulationOutcome | str,
) -> MonitorOutcome:
    """Project simulation onto the monitor vocabulary (never analysis proof)."""

    value = _enum(SimulationOutcome, outcome, "outcome")
    if value is SimulationOutcome.SUCCESS:
        return MonitorOutcome.MONITOR_SATISFIED
    if value is SimulationOutcome.VIOLATION:
        return MonitorOutcome.MONITOR_VIOLATED
    if value is SimulationOutcome.ERROR:
        return MonitorOutcome.ERROR
    return MonitorOutcome.UNKNOWN


def analysis_outcome_for_simulation(
    outcome: SimulationOutcome | str,
) -> AnalysisOutcome:
    """Project simulation onto analysis vocabulary without proof promotion.

    Only a violating trace may become :attr:`AnalysisOutcome.DISPROVED`.
    Successful traces remain :attr:`AnalysisOutcome.UNKNOWN` (monitor evidence
    is not a theorem).
    """

    value = _enum(SimulationOutcome, outcome, "outcome")
    if value is SimulationOutcome.VIOLATION:
        return AnalysisOutcome.DISPROVED
    if value is SimulationOutcome.ERROR:
        return AnalysisOutcome.ERROR
    if value is SimulationOutcome.UNAVAILABLE:
        return AnalysisOutcome.UNKNOWN
    if value is SimulationOutcome.REFUSED:
        return AnalysisOutcome.UNSUPPORTED
    # success / revert / timeout / bound_exceeded / unknown → non-proof
    return AnalysisOutcome.UNKNOWN


def assert_simulation_not_proof(authority: SimulationAuthority | str) -> None:
    """Validate that *authority* remains on the non-proof simulation lattice.

    Simulation has no theorem-proof member.  :attr:`DISPROOF_WITNESS` may
    support obligation *disproof* but never elevates to analysis ``PROVED``.
    """

    value = _enum(SimulationAuthority, authority, "authority")
    if value not in {
        SimulationAuthority.MONITOR_ONLY,
        SimulationAuthority.EVIDENCE_ONLY,
        SimulationAuthority.DISPROOF_WITNESS,
        SimulationAuthority.NON_PROOF,
    }:
        raise SimulationError(f"unsupported simulation authority: {value!r}")


def refuse_simulation_as_theorem_proof() -> None:
    """Fail closed: monitor/simulation families must not coerce into analysis proof."""

    refuse_verdict_coercion(
        VerdictFamily.MONITOR,
        VerdictFamily.ANALYSIS,
        context="simulation cannot be promoted to theorem proof",
    )


def assert_not_promoted_to_proof(
    *,
    simulation_outcome: SimulationOutcome | str,
    claimed_analysis: AnalysisOutcome | str,
) -> None:
    """Refuse silent promotion of monitor satisfaction to theorem PROVED."""

    sim = _enum(SimulationOutcome, simulation_outcome, "simulation_outcome")
    claimed = _enum(AnalysisOutcome, claimed_analysis, "claimed_analysis")
    if claimed is AnalysisOutcome.PROVED:
        raise SimulationError(
            "simulation and monitor satisfaction cannot be promoted to theorem proof "
            f"(simulation_outcome={sim.value})"
        )
    if sim is not SimulationOutcome.VIOLATION and claimed is AnalysisOutcome.DISPROVED:
        raise SimulationError(
            "only a violating simulation trace may claim analysis DISPROVED"
        )


# ---------------------------------------------------------------------------
# Bounds, snapshot, steps, request, receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SimulationBounds:
    """Hard resource bounds that every receipt must re-bind.

    All limits are non-negative integers.  ``allow_network`` defaults to
    ``False`` so offline sandboxes remain the default.
    """

    max_steps: int = 256
    max_time_ms: int = 5_000
    max_memory_bytes: int = 16 * 1024 * 1024
    max_trace_events: int = 1_024
    max_network_calls: int = 0
    allow_network: bool = False
    max_input_bytes: int = 64 * 1024
    schema_version: str = SIMULATION_BOUNDS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "max_steps",
            "max_time_ms",
            "max_memory_bytes",
            "max_trace_events",
            "max_network_calls",
            "max_input_bytes",
        ):
            object.__setattr__(
                self, name, _non_negative_int(getattr(self, name), name)
            )
        if not isinstance(self.allow_network, bool):
            raise SimulationError("allow_network must be a bool")
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_network": self.allow_network,
            "max_input_bytes": self.max_input_bytes,
            "max_memory_bytes": self.max_memory_bytes,
            "max_network_calls": self.max_network_calls,
            "max_steps": self.max_steps,
            "max_time_ms": self.max_time_ms,
            "max_trace_events": self.max_trace_events,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SimulationBounds":
        value = _as_mapping(value, "SimulationBounds")
        _known_fields(
            value,
            frozenset(
                {
                    "max_steps",
                    "max_time_ms",
                    "max_memory_bytes",
                    "max_trace_events",
                    "max_network_calls",
                    "allow_network",
                    "max_input_bytes",
                    "schema_version",
                }
            ),
            "SimulationBounds",
        )
        return cls(
            max_steps=value.get("max_steps", 256),
            max_time_ms=value.get("max_time_ms", 5_000),
            max_memory_bytes=value.get("max_memory_bytes", 16 * 1024 * 1024),
            max_trace_events=value.get("max_trace_events", 1_024),
            max_network_calls=value.get("max_network_calls", 0),
            allow_network=value.get("allow_network", False),
            max_input_bytes=value.get("max_input_bytes", 64 * 1024),
            schema_version=value.get(
                "schema_version", SIMULATION_BOUNDS_SCHEMA_VERSION
            ),
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_SIMULATION_DOMAIN}.bounds",
        )


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    """Exact chain-state snapshot bound into a simulation request/receipt.

    The snapshot is immutable.  Sandboxes receive a *working copy* of
    ``storage``; the original mapping and digests must remain unchanged after
    a run (isolation).
    """

    snapshot_id: str
    chain_namespace: str
    block_or_slot: str
    state_digest: str
    storage: Mapping[str, Any] = field(default_factory=dict)
    code_digest: str = ""
    vm_id: str = "offline.v1"
    subject_id: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = STATE_SNAPSHOT_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.OBSERVATION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "snapshot_id", _identifier(self.snapshot_id, "snapshot_id")
        )
        object.__setattr__(
            self,
            "chain_namespace",
            _identifier(self.chain_namespace, "chain_namespace"),
        )
        object.__setattr__(
            self, "block_or_slot", _text(self.block_or_slot, "block_or_slot")
        )
        object.__setattr__(self, "state_digest", _text(self.state_digest, "state_digest"))
        object.__setattr__(self, "storage", _attributes(self.storage))
        object.__setattr__(
            self, "code_digest", _text(self.code_digest, "code_digest", allow_empty=True)
        )
        object.__setattr__(self, "vm_id", _identifier(self.vm_id, "vm_id"))
        object.__setattr__(
            self, "subject_id", _text(self.subject_id, "subject_id", allow_empty=True)
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    def storage_digest(self) -> str:
        return _digest_of(dict(self.storage))

    def working_storage(self) -> dict[str, Any]:
        """Deep-copied mutable storage for isolated sandbox mutation."""

        return copy.deepcopy(dict(thaw_json(self.storage)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "block_or_slot": self.block_or_slot,
            "chain_namespace": self.chain_namespace,
            "code_digest": self.code_digest,
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "state_digest": self.state_digest,
            "storage": thaw_json(self.storage),
            "subject_id": self.subject_id,
            "vm_id": self.vm_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StateSnapshot":
        value = _as_mapping(value, "StateSnapshot")
        _known_fields(
            value,
            frozenset(
                {
                    "snapshot_id",
                    "chain_namespace",
                    "block_or_slot",
                    "state_digest",
                    "storage",
                    "code_digest",
                    "vm_id",
                    "subject_id",
                    "attributes",
                    "schema_version",
                }
            ),
            "StateSnapshot",
        )
        return cls(
            snapshot_id=value.get("snapshot_id", ""),
            chain_namespace=value.get("chain_namespace", ""),
            block_or_slot=value.get("block_or_slot", ""),
            state_digest=value.get("state_digest", ""),
            storage=value.get("storage", {}),
            code_digest=value.get("code_digest", ""),
            vm_id=value.get("vm_id", "offline.v1"),
            subject_id=value.get("subject_id", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", STATE_SNAPSHOT_SCHEMA_VERSION
            ),
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_SIMULATION_DOMAIN}.snapshot",
        )


@dataclass(frozen=True, slots=True)
class SimulationStep:
    """One ordered step in a bounded simulation trace."""

    step_index: int
    op: str
    target: str = ""
    value: str = ""
    storage_writes: Mapping[str, Any] = field(default_factory=dict)
    gas_or_compute: int = 0
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "step_index", _non_negative_int(self.step_index, "step_index")
        )
        object.__setattr__(self, "op", _identifier(self.op, "op"))
        object.__setattr__(
            self, "target", _text(self.target, "target", allow_empty=True)
        )
        object.__setattr__(self, "value", _text(self.value, "value", allow_empty=True))
        object.__setattr__(self, "storage_writes", _attributes(self.storage_writes))
        object.__setattr__(
            self,
            "gas_or_compute",
            _non_negative_int(self.gas_or_compute, "gas_or_compute"),
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "gas_or_compute": self.gas_or_compute,
            "op": self.op,
            "step_index": self.step_index,
            "storage_writes": thaw_json(self.storage_writes),
            "target": self.target,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SimulationStep":
        value = _as_mapping(value, "SimulationStep")
        return cls(
            step_index=value.get("step_index", 0),
            op=value.get("op", "noop"),
            target=value.get("target", ""),
            value=value.get("value", ""),
            storage_writes=value.get("storage_writes", {}),
            gas_or_compute=value.get("gas_or_compute", 0),
            attributes=value.get("attributes", {}),
        )


@dataclass(frozen=True, slots=True)
class SimulationRequest:
    """Bounded request to simulate a call against an exact state snapshot."""

    request_id: str
    snapshot: StateSnapshot
    call_input: Mapping[str, Any]
    bounds: SimulationBounds = field(default_factory=SimulationBounds)
    chain_namespace: str = ""
    tool_name: str = "crypto-ir-offline-sandbox"
    tool_version: str = "1.0.0"
    vm_id: str = ""
    obligation_id: str = ""
    monitor_predicate_ids: tuple[str, ...] = ()
    allow_production_fork: bool = False
    sandbox_mode: SandboxMode = SandboxMode.OFFLINE_DETERMINISTIC
    provider_id: str = "offline"
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SIMULATION_REQUEST_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _identifier(self.request_id, "request_id")
        )
        if not isinstance(self.snapshot, StateSnapshot):
            object.__setattr__(
                self,
                "snapshot",
                StateSnapshot.from_dict(_as_mapping(self.snapshot, "snapshot")),
            )
        object.__setattr__(self, "call_input", _attributes(self.call_input))
        if not isinstance(self.bounds, SimulationBounds):
            object.__setattr__(
                self,
                "bounds",
                SimulationBounds.from_dict(_as_mapping(self.bounds, "bounds")),
            )
        chain = self.chain_namespace or self.snapshot.chain_namespace
        object.__setattr__(
            self, "chain_namespace", _identifier(chain, "chain_namespace")
        )
        object.__setattr__(self, "tool_name", _identifier(self.tool_name, "tool_name"))
        object.__setattr__(
            self, "tool_version", _text(self.tool_version, "tool_version")
        )
        vm = self.vm_id or self.snapshot.vm_id
        object.__setattr__(self, "vm_id", _identifier(vm, "vm_id"))
        object.__setattr__(
            self,
            "obligation_id",
            _text(self.obligation_id, "obligation_id", allow_empty=True),
        )
        object.__setattr__(
            self,
            "monitor_predicate_ids",
            _unique_ids(self.monitor_predicate_ids, "monitor_predicate_ids"),
        )
        if not isinstance(self.allow_production_fork, bool):
            raise SimulationError("allow_production_fork must be a bool")
        object.__setattr__(
            self, "sandbox_mode", _enum(SandboxMode, self.sandbox_mode, "sandbox_mode")
        )
        object.__setattr__(
            self, "provider_id", _identifier(self.provider_id, "provider_id")
        )
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        # Input size bound.
        input_bytes = len(canonical_json_bytes(dict(self.call_input)))
        if input_bytes > self.bounds.max_input_bytes:
            raise SimulationError(
                f"call_input exceeds max_input_bytes "
                f"({input_bytes} > {self.bounds.max_input_bytes})"
            )
        if (
            self.sandbox_mode is SandboxMode.PRODUCTION_FORK
            and not self.allow_production_fork
        ):
            raise SimulationError(
                "production fork sandboxes require allow_production_fork=True"
            )

    def input_digest(self) -> str:
        return _digest_of(dict(self.call_input))

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_production_fork": self.allow_production_fork,
            "attributes": thaw_json(self.attributes),
            "bounds": self.bounds.to_dict(),
            "call_input": thaw_json(self.call_input),
            "chain_namespace": self.chain_namespace,
            "monitor_predicate_ids": list(self.monitor_predicate_ids),
            "obligation_id": self.obligation_id,
            "provider_id": self.provider_id,
            "request_id": self.request_id,
            "sandbox_mode": (
                self.sandbox_mode.value
                if isinstance(self.sandbox_mode, SandboxMode)
                else self.sandbox_mode
            ),
            "schema_version": self.schema_version,
            "snapshot": self.snapshot.to_dict(),
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "vm_id": self.vm_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SimulationRequest":
        value = _as_mapping(value, "SimulationRequest")
        _known_fields(
            value,
            frozenset(
                {
                    "request_id",
                    "snapshot",
                    "call_input",
                    "bounds",
                    "chain_namespace",
                    "tool_name",
                    "tool_version",
                    "vm_id",
                    "obligation_id",
                    "monitor_predicate_ids",
                    "allow_production_fork",
                    "sandbox_mode",
                    "provider_id",
                    "attributes",
                    "schema_version",
                }
            ),
            "SimulationRequest",
        )
        return cls(
            request_id=value.get("request_id", ""),
            snapshot=StateSnapshot.from_dict(
                _as_mapping(value.get("snapshot", {}), "snapshot")
            ),
            call_input=value.get("call_input", {}),
            bounds=SimulationBounds.from_dict(
                _as_mapping(value.get("bounds", {}), "bounds")
            ),
            chain_namespace=value.get("chain_namespace", ""),
            tool_name=value.get("tool_name", "crypto-ir-offline-sandbox"),
            tool_version=value.get("tool_version", "1.0.0"),
            vm_id=value.get("vm_id", ""),
            obligation_id=value.get("obligation_id", ""),
            monitor_predicate_ids=tuple(value.get("monitor_predicate_ids", ())),
            allow_production_fork=value.get("allow_production_fork", False),
            sandbox_mode=value.get(
                "sandbox_mode", SandboxMode.OFFLINE_DETERMINISTIC
            ),
            provider_id=value.get("provider_id", "offline"),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", SIMULATION_REQUEST_SCHEMA_VERSION
            ),
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_SIMULATION_DOMAIN}.request",
        )


@dataclass(frozen=True, slots=True)
class SimulationReceipt:
    """Evidence-bound receipt for one sandboxed simulation run.

    Re-binds every bound from the request (state, block/slot, VM, tool, input,
    time, memory, trace, network) and records isolation digests so callers can
    prove the source snapshot was not mutated.
    """

    receipt_id: str
    request_id: str
    outcome: SimulationOutcome
    authority: SimulationAuthority
    executed: bool
    snapshot_id: str
    snapshot_state_digest: str
    post_state_digest: str
    isolation_source_digest: str
    bounds: SimulationBounds
    steps: tuple[SimulationStep, ...] = ()
    block_or_slot: str = ""
    chain_namespace: str = ""
    vm_id: str = ""
    tool_name: str = ""
    tool_version: str = ""
    provider_id: str = ""
    input_digest: str = ""
    obligation_id: str = ""
    monitor_predicate_ids: tuple[str, ...] = ()
    sandbox_mode: SandboxMode = SandboxMode.OFFLINE_DETERMINISTIC
    elapsed_ms: int = 0
    memory_bytes_used: int = 0
    network_calls: int = 0
    reason: str = ""
    monitor_outcome: MonitorOutcome = MonitorOutcome.UNKNOWN
    analysis_outcome: AnalysisOutcome = AnalysisOutcome.UNKNOWN
    final_storage: Mapping[str, Any] = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SIMULATION_RECEIPT_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self, "request_id", _identifier(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "outcome", _enum(SimulationOutcome, self.outcome, "outcome")
        )
        object.__setattr__(
            self, "authority", _enum(SimulationAuthority, self.authority, "authority")
        )
        expected_authority = authority_for_outcome(self.outcome)
        if self.authority is not expected_authority:
            raise SimulationError(
                f"authority {self.authority.value} inconsistent with outcome "
                f"{self.outcome.value} (expected {expected_authority.value})"
            )
        if not isinstance(self.executed, bool):
            raise SimulationError("executed must be a bool")
        if not self.executed and self.outcome in {
            SimulationOutcome.SUCCESS,
            SimulationOutcome.VIOLATION,
            SimulationOutcome.REVERT,
        }:
            raise SimulationError(
                "non-executed receipt cannot claim success/violation/revert"
            )
        object.__setattr__(
            self, "snapshot_id", _identifier(self.snapshot_id, "snapshot_id")
        )
        object.__setattr__(
            self,
            "snapshot_state_digest",
            _text(self.snapshot_state_digest, "snapshot_state_digest"),
        )
        object.__setattr__(
            self,
            "post_state_digest",
            _text(self.post_state_digest, "post_state_digest", allow_empty=True),
        )
        object.__setattr__(
            self,
            "isolation_source_digest",
            _text(self.isolation_source_digest, "isolation_source_digest"),
        )
        if not isinstance(self.bounds, SimulationBounds):
            object.__setattr__(
                self,
                "bounds",
                SimulationBounds.from_dict(_as_mapping(self.bounds, "bounds")),
            )
        steps = tuple(
            item
            if isinstance(item, SimulationStep)
            else SimulationStep.from_dict(_as_mapping(item, "steps"))
            for item in (self.steps or ())
        )
        if len(steps) > self.bounds.max_trace_events:
            raise SimulationError("steps exceed max_trace_events bound")
        if len(steps) > self.bounds.max_steps and self.outcome not in {
            SimulationOutcome.BOUND_EXCEEDED,
            SimulationOutcome.TIMEOUT,
            SimulationOutcome.ERROR,
        }:
            raise SimulationError(
                "steps exceed max_steps without bound_exceeded/timeout/error outcome"
            )
        object.__setattr__(self, "steps", steps)
        for name in (
            "block_or_slot",
            "chain_namespace",
            "vm_id",
            "tool_name",
            "tool_version",
            "provider_id",
            "input_digest",
            "obligation_id",
            "reason",
        ):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=True)
            )
        object.__setattr__(
            self,
            "monitor_predicate_ids",
            _unique_ids(self.monitor_predicate_ids, "monitor_predicate_ids"),
        )
        object.__setattr__(
            self, "sandbox_mode", _enum(SandboxMode, self.sandbox_mode, "sandbox_mode")
        )
        for name in ("elapsed_ms", "memory_bytes_used", "network_calls"):
            object.__setattr__(
                self, name, _non_negative_int(getattr(self, name), name)
            )
        if self.elapsed_ms > self.bounds.max_time_ms and self.outcome not in {
            SimulationOutcome.TIMEOUT,
            SimulationOutcome.BOUND_EXCEEDED,
            SimulationOutcome.ERROR,
        }:
            raise SimulationError(
                "elapsed_ms exceeds max_time_ms without timeout/bound_exceeded outcome"
            )
        if (
            self.memory_bytes_used > self.bounds.max_memory_bytes
            and self.outcome
            not in {
                SimulationOutcome.BOUND_EXCEEDED,
                SimulationOutcome.ERROR,
            }
        ):
            raise SimulationError(
                "memory_bytes_used exceeds max_memory_bytes without bound_exceeded"
            )
        if self.network_calls > 0 and not self.bounds.allow_network:
            raise SimulationError(
                "network_calls recorded while bounds.allow_network is false"
            )
        if self.network_calls > self.bounds.max_network_calls:
            raise SimulationError("network_calls exceed max_network_calls bound")
        object.__setattr__(
            self,
            "monitor_outcome",
            _enum(MonitorOutcome, self.monitor_outcome, "monitor_outcome"),
        )
        object.__setattr__(
            self,
            "analysis_outcome",
            _enum(AnalysisOutcome, self.analysis_outcome, "analysis_outcome"),
        )
        # Authority lattice: never allow analysis PROVED from simulation.
        if self.analysis_outcome is AnalysisOutcome.PROVED:
            raise SimulationError(
                "simulation receipt cannot claim analysis PROVED"
            )
        expected_monitor = monitor_outcome_for_simulation(self.outcome)
        if self.monitor_outcome is not expected_monitor:
            raise SimulationError(
                f"monitor_outcome {self.monitor_outcome.value} inconsistent with "
                f"outcome {self.outcome.value} (expected {expected_monitor.value})"
            )
        expected_analysis = analysis_outcome_for_simulation(self.outcome)
        if self.analysis_outcome is not expected_analysis:
            raise SimulationError(
                f"analysis_outcome {self.analysis_outcome.value} inconsistent with "
                f"outcome {self.outcome.value} (expected {expected_analysis.value})"
            )
        object.__setattr__(self, "final_storage", _attributes(self.final_storage))
        object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        # Isolation: source digest on the receipt must match the snapshot digest
        # that was provided at request time (caller re-binds it).
        if self.isolation_source_digest != self.snapshot_state_digest:
            raise SimulationError(
                "isolation_source_digest must equal snapshot_state_digest "
                "(source snapshot must remain unmodified)"
            )

    @property
    def is_non_proof(self) -> bool:
        return self.authority is not SimulationAuthority.DISPROOF_WITNESS or (
            self.analysis_outcome is not AnalysisOutcome.PROVED
        )

    @property
    def is_disproof_witness(self) -> bool:
        return (
            self.executed
            and self.outcome is SimulationOutcome.VIOLATION
            and self.authority is SimulationAuthority.DISPROOF_WITNESS
        )

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
                if isinstance(self.authority, SimulationAuthority)
                else self.authority
            ),
            "block_or_slot": self.block_or_slot,
            "bounds": self.bounds.to_dict(),
            "chain_namespace": self.chain_namespace,
            "elapsed_ms": self.elapsed_ms,
            "executed": self.executed,
            "final_storage": thaw_json(self.final_storage),
            "input_digest": self.input_digest,
            "isolation_source_digest": self.isolation_source_digest,
            "memory_bytes_used": self.memory_bytes_used,
            "monitor_outcome": (
                self.monitor_outcome.value
                if isinstance(self.monitor_outcome, MonitorOutcome)
                else self.monitor_outcome
            ),
            "monitor_predicate_ids": list(self.monitor_predicate_ids),
            "network_calls": self.network_calls,
            "obligation_id": self.obligation_id,
            "outcome": (
                self.outcome.value
                if isinstance(self.outcome, SimulationOutcome)
                else self.outcome
            ),
            "post_state_digest": self.post_state_digest,
            "provider_id": self.provider_id,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "request_id": self.request_id,
            "sandbox_mode": (
                self.sandbox_mode.value
                if isinstance(self.sandbox_mode, SandboxMode)
                else self.sandbox_mode
            ),
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "snapshot_state_digest": self.snapshot_state_digest,
            "steps": [step.to_dict() for step in self.steps],
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "vm_id": self.vm_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SimulationReceipt":
        value = _as_mapping(value, "SimulationReceipt")
        steps_raw = value.get("steps", ())
        steps = tuple(
            SimulationStep.from_dict(_as_mapping(item, "steps")) for item in steps_raw
        )
        return cls(
            receipt_id=value.get("receipt_id", ""),
            request_id=value.get("request_id", ""),
            outcome=value.get("outcome", SimulationOutcome.UNKNOWN),
            authority=value.get("authority", SimulationAuthority.NON_PROOF),
            executed=value.get("executed", False),
            snapshot_id=value.get("snapshot_id", ""),
            snapshot_state_digest=value.get("snapshot_state_digest", ""),
            post_state_digest=value.get("post_state_digest", ""),
            isolation_source_digest=value.get("isolation_source_digest", ""),
            bounds=SimulationBounds.from_dict(
                _as_mapping(value.get("bounds", {}), "bounds")
            ),
            steps=steps,
            block_or_slot=value.get("block_or_slot", ""),
            chain_namespace=value.get("chain_namespace", ""),
            vm_id=value.get("vm_id", ""),
            tool_name=value.get("tool_name", ""),
            tool_version=value.get("tool_version", ""),
            provider_id=value.get("provider_id", ""),
            input_digest=value.get("input_digest", ""),
            obligation_id=value.get("obligation_id", ""),
            monitor_predicate_ids=tuple(value.get("monitor_predicate_ids", ())),
            sandbox_mode=value.get(
                "sandbox_mode", SandboxMode.OFFLINE_DETERMINISTIC
            ),
            elapsed_ms=value.get("elapsed_ms", 0),
            memory_bytes_used=value.get("memory_bytes_used", 0),
            network_calls=value.get("network_calls", 0),
            reason=value.get("reason", ""),
            monitor_outcome=value.get("monitor_outcome", MonitorOutcome.UNKNOWN),
            analysis_outcome=value.get(
                "analysis_outcome", AnalysisOutcome.UNKNOWN
            ),
            final_storage=value.get("final_storage", {}),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", SIMULATION_RECEIPT_SCHEMA_VERSION
            ),
        )

    @property
    def identity(self) -> CanonicalIdentity:
        return crypto_ir_identity(
            self.to_dict(),
            schema_version=self.schema_version,
            domain=f"{CRYPTO_IR_SIMULATION_DOMAIN}.receipt",
        )


# ---------------------------------------------------------------------------
# Sandbox protocol and offline implementations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SandboxRunResult:
    """Internal sandbox result before receipt assembly."""

    outcome: SimulationOutcome
    steps: tuple[SimulationStep, ...]
    final_storage: Mapping[str, Any]
    post_state_digest: str
    elapsed_ms: int
    memory_bytes_used: int
    network_calls: int
    reason: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class OfflineSandbox(Protocol):
    """Injected offline sandbox protocol (deterministic, no network by default)."""

    @property
    def provider_id(self) -> str: ...

    @property
    def tool_name(self) -> str: ...

    @property
    def tool_version(self) -> str: ...

    @property
    def mode(self) -> SandboxMode: ...

    def is_available(self) -> bool: ...

    def simulate(self, request: SimulationRequest) -> SandboxRunResult: ...


def _estimate_memory(storage: Mapping[str, Any], steps: Sequence[SimulationStep]) -> int:
    return len(canonical_json_bytes(dict(storage))) + sum(
        len(canonical_json_bytes(step.to_dict())) for step in steps
    )


class DeterministicOfflineSandbox:
    """Pure-Python offline sandbox for deterministic fixtures and CI.

    Interprets a tiny call-input dialect:

    * ``{"op": "noop"}`` — success, no storage change
    * ``{"op": "set", "key": K, "value": V}`` — write storage[K]=V
    * ``{"op": "transfer", "from": A, "to": B, "amount": N}`` — balance move
    * ``{"op": "assert_eq", "key": K, "value": V}`` — violation if mismatch
    * ``{"op": "revert"}`` — explicit revert
    * ``{"op": "violate", "predicate": P}`` — explicit monitor violation
    * ``{"op": "sequence", "steps": [...]}`` — ordered sub-ops

    Optional ``call_input["force_outcome"]`` overrides the natural outcome for
    fixture control (``timeout``, ``bound_exceeded``, ``error``, ``unavailable``).
    """

    def __init__(
        self,
        *,
        provider_id: str = "offline.deterministic",
        tool_name: str = "crypto-ir-offline-sandbox",
        tool_version: str = "1.0.0",
    ) -> None:
        self._provider_id = _identifier(provider_id, "provider_id")
        self._tool_name = _identifier(tool_name, "tool_name")
        self._tool_version = _text(tool_version, "tool_version")

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def tool_name(self) -> str:
        return self._tool_name

    @property
    def tool_version(self) -> str:
        return self._tool_version

    @property
    def mode(self) -> SandboxMode:
        return SandboxMode.OFFLINE_DETERMINISTIC

    def is_available(self) -> bool:
        return True

    def simulate(self, request: SimulationRequest) -> SandboxRunResult:
        started = time.perf_counter()
        force = str(request.call_input.get("force_outcome", "") or "")
        if force == "unavailable":
            return SandboxRunResult(
                outcome=SimulationOutcome.UNAVAILABLE,
                steps=(),
                final_storage={},
                post_state_digest="",
                elapsed_ms=0,
                memory_bytes_used=0,
                network_calls=0,
                reason="sandbox forced unavailable",
            )
        if force == "error":
            return SandboxRunResult(
                outcome=SimulationOutcome.ERROR,
                steps=(),
                final_storage={},
                post_state_digest="",
                elapsed_ms=0,
                memory_bytes_used=0,
                network_calls=0,
                reason="sandbox forced error",
            )

        storage = request.snapshot.working_storage()
        steps: list[SimulationStep] = []
        reason = ""
        outcome = SimulationOutcome.SUCCESS

        try:
            ops = _expand_ops(dict(thaw_json(request.call_input)))
            for index, op in enumerate(ops):
                if index >= request.bounds.max_steps:
                    outcome = SimulationOutcome.BOUND_EXCEEDED
                    reason = "max_steps exceeded"
                    break
                elapsed = int((time.perf_counter() - started) * 1000)
                if elapsed > request.bounds.max_time_ms or force == "timeout":
                    outcome = SimulationOutcome.TIMEOUT
                    reason = "max_time_ms exceeded" if force != "timeout" else "forced timeout"
                    break
                if force == "bound_exceeded":
                    outcome = SimulationOutcome.BOUND_EXCEEDED
                    reason = "forced bound_exceeded"
                    break

                step_outcome, step, reason = _apply_op(index, op, storage)
                steps.append(step)
                mem = _estimate_memory(storage, steps)
                if mem > request.bounds.max_memory_bytes:
                    outcome = SimulationOutcome.BOUND_EXCEEDED
                    reason = "max_memory_bytes exceeded"
                    break
                if len(steps) > request.bounds.max_trace_events:
                    outcome = SimulationOutcome.BOUND_EXCEEDED
                    reason = "max_trace_events exceeded"
                    break
                if step_outcome is not SimulationOutcome.SUCCESS:
                    outcome = step_outcome
                    break
        except SimulationError as exc:
            outcome = SimulationOutcome.ERROR
            reason = str(exc)
        except Exception as exc:  # noqa: BLE001 — sandbox must fail closed
            outcome = SimulationOutcome.ERROR
            reason = f"sandbox error: {exc}"

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        post_digest = _digest_of(storage) if outcome is not SimulationOutcome.ERROR else ""
        return SandboxRunResult(
            outcome=outcome,
            steps=tuple(steps),
            final_storage=storage,
            post_state_digest=post_digest,
            elapsed_ms=elapsed_ms,
            memory_bytes_used=_estimate_memory(storage, steps),
            network_calls=0,
            reason=reason or f"offline simulation {outcome.value}",
            attributes={"provider": self.provider_id},
        )


def _expand_ops(call_input: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    op = str(call_input.get("op", "noop") or "noop")
    if op == "sequence":
        steps = call_input.get("steps", [])
        if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
            raise SimulationError("sequence.steps must be a list of ops")
        return [dict(item) for item in steps]
    return [dict(call_input)]


def _apply_op(
    index: int,
    op: Mapping[str, Any],
    storage: MutableMapping[str, Any],
) -> tuple[SimulationOutcome, SimulationStep, str]:
    name = str(op.get("op", "noop") or "noop")
    writes: dict[str, Any] = {}
    reason = ""
    outcome = SimulationOutcome.SUCCESS

    if name == "noop":
        pass
    elif name == "set":
        key = str(op.get("key", ""))
        if not key:
            raise SimulationError("set requires key")
        value = op.get("value")
        storage[key] = value
        writes[key] = value
    elif name == "transfer":
        src = str(op.get("from", ""))
        dst = str(op.get("to", ""))
        amount = op.get("amount", 0)
        if type(amount) is not int or isinstance(amount, bool) or amount < 0:
            raise SimulationError("transfer.amount must be a non-negative int")
        if not src or not dst:
            raise SimulationError("transfer requires from and to")
        balances = storage.setdefault("balances", {})
        if not isinstance(balances, MutableMapping):
            raise SimulationError("storage.balances must be a mapping")
        src_bal = int(balances.get(src, 0))
        if src_bal < amount:
            outcome = SimulationOutcome.REVERT
            reason = f"insufficient balance for {src}"
        else:
            balances[src] = src_bal - amount
            balances[dst] = int(balances.get(dst, 0)) + amount
            writes["balances"] = dict(balances)
    elif name == "assert_eq":
        key = str(op.get("key", ""))
        expected = op.get("value")
        actual = storage.get(key)
        if actual != expected:
            outcome = SimulationOutcome.VIOLATION
            reason = f"assert_eq failed: {key}={actual!r} expected {expected!r}"
    elif name == "revert":
        outcome = SimulationOutcome.REVERT
        reason = str(op.get("reason", "explicit revert"))
    elif name == "violate":
        outcome = SimulationOutcome.VIOLATION
        reason = str(op.get("predicate", op.get("reason", "explicit violation")))
    elif name == "network":
        # Offline sandbox refuses network ops.
        outcome = SimulationOutcome.ERROR
        reason = "network op refused by offline sandbox"
    else:
        raise SimulationError(f"unsupported op: {name!r}")

    step = SimulationStep(
        step_index=index,
        op=name if _ID_RE.fullmatch(name) else "unknown",
        target=str(op.get("key", op.get("to", op.get("target", ""))) or ""),
        value=str(op.get("value", op.get("amount", ""))),
        storage_writes=writes,
        gas_or_compute=1,
        attributes={"raw_op": name},
    )
    return outcome, step, reason


class InjectedFixtureSandbox:
    """Sandbox that returns a pre-injected :class:`SandboxRunResult` (tests)."""

    def __init__(
        self,
        result: SandboxRunResult,
        *,
        provider_id: str = "offline.injected",
        tool_name: str = "crypto-ir-injected-sandbox",
        tool_version: str = "1.0.0",
        available: bool = True,
    ) -> None:
        self._result = result
        self._provider_id = _identifier(provider_id, "provider_id")
        self._tool_name = _identifier(tool_name, "tool_name")
        self._tool_version = _text(tool_version, "tool_version")
        self._available = available

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def tool_name(self) -> str:
        return self._tool_name

    @property
    def tool_version(self) -> str:
        return self._tool_version

    @property
    def mode(self) -> SandboxMode:
        return SandboxMode.INJECTED_FIXTURE

    def is_available(self) -> bool:
        return self._available

    def simulate(self, request: SimulationRequest) -> SandboxRunResult:
        if not self._available:
            return SandboxRunResult(
                outcome=SimulationOutcome.UNAVAILABLE,
                steps=(),
                final_storage={},
                post_state_digest="",
                elapsed_ms=0,
                memory_bytes_used=0,
                network_calls=0,
                reason="injected sandbox unavailable",
            )
        # Isolation: still force a working copy path by ignoring request storage
        # mutations — return the pre-baked result as-is.
        _ = request
        return self._result


class ProductionForkSandbox:
    """Opt-in production-fork placeholder that refuses unless explicitly allowed.

    Real fork providers are integration-only.  This class records the refusal
    path for offline suites and only claims execution when a result injector is
    supplied (tests / future adapters).
    """

    def __init__(
        self,
        *,
        provider_id: str = "fork.production",
        tool_name: str = "crypto-ir-production-fork",
        tool_version: str = "1.0.0",
        injector: OfflineSandbox | None = None,
    ) -> None:
        self._provider_id = _identifier(provider_id, "provider_id")
        self._tool_name = _identifier(tool_name, "tool_name")
        self._tool_version = _text(tool_version, "tool_version")
        self._injector = injector

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def tool_name(self) -> str:
        return self._tool_name

    @property
    def tool_version(self) -> str:
        return self._tool_version

    @property
    def mode(self) -> SandboxMode:
        return SandboxMode.PRODUCTION_FORK

    def is_available(self) -> bool:
        # Always "available" as a policy gate so refuse/unavailable outcomes
        # are produced inside :meth:`simulate` rather than short-circuited.
        return True

    def simulate(self, request: SimulationRequest) -> SandboxRunResult:
        if not request.allow_production_fork:
            return SandboxRunResult(
                outcome=SimulationOutcome.REFUSED,
                steps=(),
                final_storage={},
                post_state_digest="",
                elapsed_ms=0,
                memory_bytes_used=0,
                network_calls=0,
                reason="production fork refused: allow_production_fork is false",
            )
        if self._injector is None:
            return SandboxRunResult(
                outcome=SimulationOutcome.UNAVAILABLE,
                steps=(),
                final_storage={},
                post_state_digest="",
                elapsed_ms=0,
                memory_bytes_used=0,
                network_calls=0,
                reason="production fork backend not configured",
            )
        return self._injector.simulate(request)


def build_simulation_receipt(
    request: SimulationRequest,
    run: SandboxRunResult,
    *,
    receipt_id: str,
    provider_id: str | None = None,
    tool_name: str | None = None,
    tool_version: str | None = None,
    sandbox_mode: SandboxMode | None = None,
) -> SimulationReceipt:
    """Assemble a receipt that re-binds every request bound and isolation digest."""

    outcome = run.outcome
    executed = outcome not in {
        SimulationOutcome.UNAVAILABLE,
        SimulationOutcome.REFUSED,
        SimulationOutcome.ERROR,
    } or bool(run.steps)
    # ERROR with no steps is non-executed; UNAVAILABLE/REFUSED never execute.
    if outcome in {
        SimulationOutcome.UNAVAILABLE,
        SimulationOutcome.REFUSED,
    }:
        executed = False
    if outcome is SimulationOutcome.ERROR and not run.steps:
        executed = False
    if outcome in {
        SimulationOutcome.SUCCESS,
        SimulationOutcome.VIOLATION,
        SimulationOutcome.REVERT,
        SimulationOutcome.TIMEOUT,
        SimulationOutcome.BOUND_EXCEEDED,
    }:
        executed = True

    return SimulationReceipt(
        receipt_id=receipt_id,
        request_id=request.request_id,
        outcome=outcome,
        authority=authority_for_outcome(outcome),
        executed=executed,
        snapshot_id=request.snapshot.snapshot_id,
        snapshot_state_digest=request.snapshot.state_digest,
        post_state_digest=run.post_state_digest,
        isolation_source_digest=request.snapshot.state_digest,
        bounds=request.bounds,
        steps=run.steps,
        block_or_slot=request.snapshot.block_or_slot,
        chain_namespace=request.chain_namespace,
        vm_id=request.vm_id,
        tool_name=tool_name or request.tool_name,
        tool_version=tool_version or request.tool_version,
        provider_id=provider_id or request.provider_id,
        input_digest=request.input_digest(),
        obligation_id=request.obligation_id,
        monitor_predicate_ids=request.monitor_predicate_ids,
        sandbox_mode=sandbox_mode or request.sandbox_mode,
        elapsed_ms=run.elapsed_ms,
        memory_bytes_used=run.memory_bytes_used,
        network_calls=run.network_calls,
        reason=run.reason,
        monitor_outcome=monitor_outcome_for_simulation(outcome),
        analysis_outcome=analysis_outcome_for_simulation(outcome),
        final_storage=run.final_storage,
        attributes=run.attributes,
    )


def run_simulation(
    request: SimulationRequest,
    sandbox: OfflineSandbox,
    *,
    receipt_id: str | None = None,
) -> SimulationReceipt:
    """Execute *request* on *sandbox* and return a receipt-bound result.

    Verifies source-snapshot isolation after the run: the request snapshot
    storage digest and state_digest must be unchanged.
    """

    source_storage_before = request.snapshot.storage_digest()
    source_state_digest = request.snapshot.state_digest
    source_storage_mapping = dict(thaw_json(request.snapshot.storage))

    # Production fork mode requires opt-in on the request before availability.
    if (
        sandbox.mode is SandboxMode.PRODUCTION_FORK
        and not request.allow_production_fork
    ):
        run = SandboxRunResult(
            outcome=SimulationOutcome.REFUSED,
            steps=(),
            final_storage={},
            post_state_digest="",
            elapsed_ms=0,
            memory_bytes_used=0,
            network_calls=0,
            reason="production fork refused without allow_production_fork",
        )
    elif not sandbox.is_available():
        run = SandboxRunResult(
            outcome=SimulationOutcome.UNAVAILABLE,
            steps=(),
            final_storage={},
            post_state_digest="",
            elapsed_ms=0,
            memory_bytes_used=0,
            network_calls=0,
            reason=f"sandbox {sandbox.provider_id} unavailable",
        )
    else:
        run = sandbox.simulate(request)

    # Isolation check: original snapshot must be byte-stable.
    if request.snapshot.storage_digest() != source_storage_before:
        raise SimulationError(
            "sandbox mutated source StateSnapshot.storage (isolation violated)"
        )
    if request.snapshot.state_digest != source_state_digest:
        raise SimulationError(
            "sandbox mutated source StateSnapshot.state_digest (isolation violated)"
        )
    if dict(thaw_json(request.snapshot.storage)) != source_storage_mapping:
        raise SimulationError(
            "sandbox mutated source StateSnapshot.storage contents (isolation violated)"
        )

    rid = receipt_id or f"receipt.sim.{request.request_id}"
    return build_simulation_receipt(
        request,
        run,
        receipt_id=rid,
        provider_id=sandbox.provider_id,
        tool_name=sandbox.tool_name,
        tool_version=sandbox.tool_version,
        sandbox_mode=sandbox.mode,
    )


__all__ = [
    "CRYPTO_IR_SIMULATION_DOMAIN",
    "CRYPTO_IR_SIMULATION_SCHEMA_VERSION",
    "SIMULATION_BOUNDS_SCHEMA_VERSION",
    "SIMULATION_RECEIPT_SCHEMA_VERSION",
    "SIMULATION_REQUEST_SCHEMA_VERSION",
    "STATE_SNAPSHOT_SCHEMA_VERSION",
    "DeterministicOfflineSandbox",
    "InjectedFixtureSandbox",
    "OfflineSandbox",
    "ProductionForkSandbox",
    "SandboxMode",
    "SandboxRunResult",
    "SimulationAuthority",
    "SimulationBounds",
    "SimulationError",
    "SimulationOutcome",
    "SimulationReceipt",
    "SimulationRequest",
    "SimulationStep",
    "StateSnapshot",
    "analysis_outcome_for_simulation",
    "assert_not_promoted_to_proof",
    "assert_simulation_not_proof",
    "authority_for_outcome",
    "build_simulation_receipt",
    "monitor_outcome_for_simulation",
    "refuse_simulation_as_theorem_proof",
    "run_simulation",
]
