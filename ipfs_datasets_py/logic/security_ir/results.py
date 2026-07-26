"""Typed Security IR verification results and legacy-result adaptation.

Security declarations do not contain verification state.  This module binds
observations to the solver-neutral result contracts in :mod:`logic.ir_core`
while retaining a Security-specific distinction between an affirmative proof
and a counterexample-backed disproof.

Legacy reports mixed solver conclusions, runtime observations, evidence
readiness, and release decisions in similarly shaped dictionaries.  Adapting
one therefore always returns structured diagnostics describing the
classification and any lossy status normalization.  In particular, a query
about whether Xaman blockers are satisfiable is an evidence-readiness query:
finding a blocker makes the gate ``NOT_READY`` and never proves or disproves a
security theorem.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, TypeAlias

from ..ir_core.claims import FrozenMap, stable_digest
from ..ir_core.protocols import (
    AuthorityMismatchError,
    BackendAttempt,
    BackendRequest,
    BoundedResult,
    EvidenceGateResult,
    MonitorResult,
    PolicyDecision,
    ProofReceipt,
    ProofResult as CoreProofResult,
    QueryKind,
    ResultAuthority,
    ResultStatus,
    SatisfiabilityResult,
)


SECURITY_RESULT_INTERFACE_VERSION: Final = "security-result-authority/v1"
LEGACY_RESULT_MAPPING_VERSION: Final = "security-legacy-result-mapping/v1"


class SecurityResultValidationError(ValueError):
    """Raised when a Security result cannot be classified without guessing."""


class SecurityResultFamily(str, Enum):
    """Closed Security result families with no authority hierarchy."""

    PROOF = "proof"
    DISPROOF = "disproof"
    RUNTIME_MONITOR = "runtime_monitor"
    EVIDENCE_GATE = "evidence_gate"
    RELEASE_POLICY = "release_policy"
    SATISFIABILITY = "satisfiability"

    @property
    def query_kind(self) -> QueryKind:
        return {
            SecurityResultFamily.PROOF: QueryKind.THEOREM_PROOF,
            SecurityResultFamily.DISPROOF: QueryKind.THEOREM_PROOF,
            SecurityResultFamily.RUNTIME_MONITOR: QueryKind.RUNTIME_MONITOR,
            SecurityResultFamily.EVIDENCE_GATE: QueryKind.EVIDENCE_READINESS,
            SecurityResultFamily.RELEASE_POLICY: QueryKind.POLICY_APPROVAL,
            SecurityResultFamily.SATISFIABILITY: QueryKind.SATISFIABILITY,
        }[self]


@dataclass(frozen=True, slots=True)
class ProofResult(CoreProofResult):
    """Security theorem result that cannot carry an accepted disproof status."""

    def __post_init__(self) -> None:
        super(ProofResult, self).__post_init__()
        if self.status is ResultStatus.DISPROVED:
            raise AuthorityMismatchError(
                "a Security disproof must use DisproofResult, not ProofResult"
            )


@dataclass(frozen=True, slots=True)
class DisproofResult(CoreProofResult):
    """Counterexample-backed theorem disproof, distinct from proof output."""

    result_type = "disproof"

    def __post_init__(self) -> None:
        super(DisproofResult, self).__post_init__()
        if self.status is not ResultStatus.DISPROVED:
            raise AuthorityMismatchError(
                "DisproofResult requires a disproved theorem conclusion"
            )
        payload = self.payload.to_dict()
        if not any(
            payload.get(field_name)
            for field_name in ("counterexample", "counterexample_cid", "witness")
        ):
            raise SecurityResultValidationError(
                "DisproofResult requires a counterexample or witness binding"
            )


SecurityResult: TypeAlias = (
    CoreProofResult
    | MonitorResult
    | EvidenceGateResult
    | PolicyDecision
    | SatisfiabilityResult
)


@dataclass(frozen=True, slots=True)
class LegacyResultDiagnostic:
    """Stable explanation emitted while interpreting one legacy result."""

    code: str
    message: str
    source_field: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.code, str)
            or not self.code.startswith("security.result.")
            or self.code != self.code.strip()
        ):
            raise SecurityResultValidationError(
                "diagnostic code must use the security.result namespace"
            )
        if (
            not isinstance(self.message, str)
            or not self.message.strip()
            or self.message != self.message.strip()
        ):
            raise SecurityResultValidationError(
                "diagnostic message must be a non-empty trimmed string"
            )
        if not isinstance(self.source_field, str):
            raise SecurityResultValidationError("source_field must be a string")
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "metadata": self.metadata.to_dict(),
            "source_field": self.source_field,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegacyResultDiagnostic":
        if not isinstance(value, Mapping):
            raise SecurityResultValidationError("diagnostic must be a mapping")
        unknown = sorted(
            set(value) - {"code", "message", "metadata", "source_field"}
        )
        if unknown:
            raise SecurityResultValidationError(
                f"unknown diagnostic field(s): {', '.join(unknown)}"
            )
        return cls(
            code=value.get("code", ""),
            message=value.get("message", ""),
            source_field=value.get("source_field", ""),
            metadata=FrozenMap(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class LegacyResultMapping:
    """One mapped result plus explicit, immutable adaptation diagnostics."""

    result: SecurityResult
    family: SecurityResultFamily
    source_schema_version: str
    source_digest: str
    diagnostics: tuple[LegacyResultDiagnostic, ...]
    schema_version: str = LEGACY_RESULT_MAPPING_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.result, BoundedResult):
            raise SecurityResultValidationError("result must be a bounded result")
        object.__setattr__(self, "family", SecurityResultFamily(self.family))
        if result_family(self.result) is not self.family:
            raise SecurityResultValidationError(
                "mapping family does not match the typed result"
            )
        if not isinstance(self.source_schema_version, str):
            raise SecurityResultValidationError(
                "source_schema_version must be a string"
            )
        if (
            not isinstance(self.source_digest, str)
            or len(self.source_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.source_digest)
        ):
            raise SecurityResultValidationError(
                "source_digest must be a lowercase SHA-256 digest"
            )
        if not self.diagnostics or any(
            not isinstance(item, LegacyResultDiagnostic) for item in self.diagnostics
        ):
            raise SecurityResultValidationError(
                "legacy mappings require explicit diagnostics"
            )
        if self.schema_version != LEGACY_RESULT_MAPPING_VERSION:
            raise SecurityResultValidationError(
                f"unsupported legacy mapping version: {self.schema_version}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "family": self.family.value,
            "result": self.result.to_dict(),
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_schema_version": self.source_schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegacyResultMapping":
        if not isinstance(value, Mapping):
            raise SecurityResultValidationError(
                "legacy result mapping must be a mapping"
            )
        allowed = {
            "diagnostics",
            "family",
            "result",
            "schema_version",
            "source_digest",
            "source_schema_version",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise SecurityResultValidationError(
                f"unknown legacy mapping field(s): {', '.join(unknown)}"
            )
        try:
            family = SecurityResultFamily(value.get("family", ""))
        except ValueError as exc:
            raise SecurityResultValidationError(
                f"unsupported result family: {value.get('family', '')}"
            ) from exc
        result_value = value.get("result")
        if not isinstance(result_value, Mapping):
            raise SecurityResultValidationError("mapping result must be a mapping")
        diagnostics_value = value.get("diagnostics", ())
        if isinstance(diagnostics_value, (str, bytes, bytearray)) or not isinstance(
            diagnostics_value, Sequence
        ):
            raise SecurityResultValidationError(
                "mapping diagnostics must be a sequence"
            )
        result_class = _FAMILY_RESULT_CLASS[family]
        return cls(
            result=result_class.from_dict(result_value),
            family=family,
            source_schema_version=value.get("source_schema_version", ""),
            source_digest=value.get("source_digest", ""),
            diagnostics=tuple(
                LegacyResultDiagnostic.from_dict(item)
                for item in diagnostics_value
            ),
            schema_version=value.get(
                "schema_version", LEGACY_RESULT_MAPPING_VERSION
            ),
        )


_FAMILY_RESULT_CLASS: Final[dict[SecurityResultFamily, type[BoundedResult]]] = {
    SecurityResultFamily.PROOF: ProofResult,
    SecurityResultFamily.DISPROOF: DisproofResult,
    SecurityResultFamily.RUNTIME_MONITOR: MonitorResult,
    SecurityResultFamily.EVIDENCE_GATE: EvidenceGateResult,
    SecurityResultFamily.RELEASE_POLICY: PolicyDecision,
    SecurityResultFamily.SATISFIABILITY: SatisfiabilityResult,
}

_FAMILY_DIAGNOSTIC: Final[dict[SecurityResultFamily, str]] = {
    SecurityResultFamily.PROOF: "security.result.legacy_proof_mapped",
    SecurityResultFamily.DISPROOF: "security.result.legacy_disproof_mapped",
    SecurityResultFamily.RUNTIME_MONITOR: "security.result.legacy_monitor_mapped",
    SecurityResultFamily.EVIDENCE_GATE: "security.result.legacy_evidence_gate_mapped",
    SecurityResultFamily.RELEASE_POLICY: "security.result.legacy_policy_mapped",
    SecurityResultFamily.SATISFIABILITY: "security.result.legacy_satisfiability_mapped",
}


def _legacy_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        payload = dict(value)
    else:
        to_dict = getattr(value, "to_dict", None)
        if not callable(to_dict):
            raise SecurityResultValidationError(
                "legacy output must be a mapping or provide to_dict()"
            )
        payload = to_dict()
        if not isinstance(payload, Mapping):
            raise SecurityResultValidationError(
                "legacy output to_dict() must return a mapping"
            )
        payload = dict(payload)
    try:
        FrozenMap(payload)
    except (TypeError, ValueError) as exc:
        raise SecurityResultValidationError(
            "legacy output must contain only JSON-compatible values"
        ) from exc
    return payload


def _sequence(value: Any) -> tuple[Any, ...] | None:
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(value)
    return None


def _family_hint(payload: Mapping[str, Any]) -> SecurityResultFamily | None:
    for field_name in ("result_family", "family", "kind", "query_kind"):
        value = payload.get(field_name)
        if not isinstance(value, str):
            continue
        normalized = value.strip().lower().replace("-", "_")
        aliases = {
            "proof": SecurityResultFamily.PROOF,
            "theorem_proof": SecurityResultFamily.PROOF,
            "disproof": SecurityResultFamily.DISPROOF,
            "counterexample": SecurityResultFamily.DISPROOF,
            "runtime_monitor": SecurityResultFamily.RUNTIME_MONITOR,
            "monitor": SecurityResultFamily.RUNTIME_MONITOR,
            "evidence_gate": SecurityResultFamily.EVIDENCE_GATE,
            "evidence_readiness": SecurityResultFamily.EVIDENCE_GATE,
            "xaman_blocker_satisfiability": SecurityResultFamily.EVIDENCE_GATE,
            "release_policy": SecurityResultFamily.RELEASE_POLICY,
            "policy_decision": SecurityResultFamily.RELEASE_POLICY,
            "policy_approval": SecurityResultFamily.RELEASE_POLICY,
            "satisfiability": SecurityResultFamily.SATISFIABILITY,
        }
        if normalized in aliases:
            return aliases[normalized]
    return None


def _infer_family(
    payload: Mapping[str, Any],
) -> tuple[SecurityResultFamily, str]:
    hinted = _family_hint(payload)
    if hinted is not None:
        return hinted, "explicit family discriminator"

    schema = str(payload.get("schema_version", "")).lower()
    status = str(payload.get("status", "")).upper()
    if status == "DISPROVED" or payload.get("counterexample"):
        return SecurityResultFamily.DISPROOF, "legacy disproof signal"
    if "runtime" in schema or "trace" in schema:
        return SecurityResultFamily.RUNTIME_MONITOR, "runtime/trace schema"
    if "policy" in schema or "verdict" in schema or "release_ready" in payload:
        return SecurityResultFamily.RELEASE_POLICY, "release-policy signal"
    if (
        "evidence" in schema
        or "blocker" in schema
        or any(
            field_name in payload
            for field_name in (
                "blockers",
                "blocking_gaps",
                "open_blockers",
                "remaining_blockers",
            )
        )
    ):
        return SecurityResultFamily.EVIDENCE_GATE, "evidence/blocker signal"
    if schema == "proof-report/v1" or (
        "claim_id" in payload and ("status" in payload or "solver_result" in payload)
    ):
        return SecurityResultFamily.PROOF, "legacy proof-report signal"
    raise SecurityResultValidationError(
        "legacy result family is ambiguous; provide an explicit family"
    )


def _status_text(payload: Mapping[str, Any]) -> str:
    for field_name in (
        "status",
        "result",
        "solver_result",
        "overall_status",
        "security_decision",
    ):
        value = payload.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip().lower().replace("-", "_")
    return ""


def _proof_status(
    payload: Mapping[str, Any],
    family: SecurityResultFamily,
) -> tuple[ResultStatus, tuple[LegacyResultDiagnostic, ...]]:
    raw = _status_text(payload)
    solver_raw = str(payload.get("solver_result", "")).strip().lower().replace("-", "_")
    diagnostics: list[LegacyResultDiagnostic] = []
    if family is SecurityResultFamily.DISPROOF:
        if raw in {"proved", "prove", "valid", "unsat", "unsatisfiable"}:
            raise SecurityResultValidationError(
                "legacy output has a proof conclusion and cannot be relabeled as disproof"
            )
        status = ResultStatus.DISPROVED
    elif raw in {"proved", "prove", "valid", "unsat", "unsatisfiable"}:
        status = ResultStatus.PROVED
    elif raw in {"disproved", "disprove", "invalid", "sat", "satisfiable"}:
        status = ResultStatus.DISPROVED
    elif raw in {"error", "failed", "parser_error"}:
        status = ResultStatus.ERROR
    else:
        status = ResultStatus.UNKNOWN
        diagnostics.append(
            LegacyResultDiagnostic(
                code="security.result.legacy_status_normalized",
                message=(
                    f"Legacy proof status {raw or '<missing>'!r} was normalized "
                    "to unknown."
                ),
                source_field="status",
                metadata={"legacy_status": raw},
            )
        )
    if status is ResultStatus.PROVED and solver_raw in {"sat", "satisfiable"}:
        raise SecurityResultValidationError(
            "legacy proof status conflicts with a satisfiable solver result"
        )
    if status is ResultStatus.DISPROVED and solver_raw in {
        "unsat",
        "unsatisfiable",
    }:
        raise SecurityResultValidationError(
            "legacy disproof status conflicts with an unsatisfiable solver result"
        )
    if status is ResultStatus.DISPROVED and family is SecurityResultFamily.PROOF:
        family_name = SecurityResultFamily.DISPROOF.value
        raise SecurityResultValidationError(
            f"legacy conclusion is a {family_name}; map it to DisproofResult"
        )
    return status, tuple(diagnostics)


def _monitor_status(payload: Mapping[str, Any]) -> ResultStatus:
    raw = _status_text(payload)
    if raw in {
        "monitor_satisfied",
        "satisfied",
        "passed",
        "pass",
        "conformant",
        "checked",
    }:
        return ResultStatus.MONITOR_SATISFIED
    if raw in {
        "monitor_violated",
        "violated",
        "failed",
        "fail",
        "nonconformant",
    }:
        return ResultStatus.MONITOR_VIOLATED
    if raw in {"error", "parser_error"}:
        return ResultStatus.ERROR
    return ResultStatus.UNKNOWN


def _blockers(payload: Mapping[str, Any]) -> tuple[Any, ...] | None:
    for field_name in (
        "blockers",
        "blocking_gaps",
        "open_blockers",
        "remaining_blockers",
    ):
        if field_name in payload:
            return _sequence(payload.get(field_name))
    return None


def _evidence_status(payload: Mapping[str, Any]) -> ResultStatus:
    blockers = _blockers(payload)
    if blockers is not None:
        return ResultStatus.READY if not blockers else ResultStatus.NOT_READY
    blocked = payload.get(
        "production_release_blocked",
        payload.get("testnet_assurance_blocked"),
    )
    if isinstance(blocked, bool):
        return ResultStatus.NOT_READY if blocked else ResultStatus.READY
    raw = _status_text(payload)
    # For a blocker-existence query SAT means a blocker exists and the
    # evidence gate is not ready. UNSAT means no modeled blocker exists.
    if raw in {"sat", "satisfiable", "not_ready", "blocked", "missing"}:
        return ResultStatus.NOT_READY
    if raw in {"unsat", "unsatisfiable", "ready", "complete", "accepted"}:
        return ResultStatus.READY
    if raw in {"error", "failed", "parser_error"}:
        return ResultStatus.ERROR
    return ResultStatus.UNKNOWN


def _policy_status(payload: Mapping[str, Any]) -> ResultStatus:
    release_ready = payload.get(
        "release_ready",
        payload.get("production_release_ready"),
    )
    if isinstance(release_ready, bool):
        return ResultStatus.APPROVED if release_ready else ResultStatus.REJECTED
    blocked = payload.get("production_release_blocked")
    if isinstance(blocked, bool):
        return ResultStatus.REJECTED if blocked else ResultStatus.APPROVED
    raw = _status_text(payload)
    if raw in {"approved", "allow", "release", "release_ready", "secure"}:
        return ResultStatus.APPROVED
    if raw in {
        "rejected",
        "reject",
        "block",
        "blocked",
        "blocked_production",
        "non_secure",
    }:
        return ResultStatus.REJECTED
    if raw in {"error", "failed", "parser_error"}:
        return ResultStatus.ERROR
    return ResultStatus.UNKNOWN


def _satisfiability_status(payload: Mapping[str, Any]) -> ResultStatus:
    raw = _status_text(payload)
    if raw in {"sat", "satisfiable"}:
        return ResultStatus.SATISFIABLE
    if raw in {"unsat", "unsatisfiable"}:
        return ResultStatus.UNSATISFIABLE
    if raw in {"error", "failed", "parser_error"}:
        return ResultStatus.ERROR
    return ResultStatus.UNKNOWN


def _status_for(
    payload: Mapping[str, Any],
    family: SecurityResultFamily,
) -> tuple[ResultStatus, tuple[LegacyResultDiagnostic, ...]]:
    if family in {SecurityResultFamily.PROOF, SecurityResultFamily.DISPROOF}:
        return _proof_status(payload, family)
    if family is SecurityResultFamily.RUNTIME_MONITOR:
        return _monitor_status(payload), ()
    if family is SecurityResultFamily.EVIDENCE_GATE:
        return _evidence_status(payload), ()
    if family is SecurityResultFamily.RELEASE_POLICY:
        return _policy_status(payload), ()
    return _satisfiability_status(payload), ()


def _result_payload(
    payload: Mapping[str, Any],
    family: SecurityResultFamily,
    source_digest: str,
) -> dict[str, Any]:
    result_payload: dict[str, Any] = {
        "legacy_schema_version": str(payload.get("schema_version", "")),
        "legacy_source_digest": source_digest,
        "mapped_family": family.value,
    }
    if family is SecurityResultFamily.DISPROOF:
        counterexample = payload.get("counterexample")
        if counterexample:
            result_payload["counterexample"] = counterexample
        else:
            witness = payload.get("witness", payload.get("proof_or_trace_cid"))
            if witness:
                result_payload["witness"] = witness
    blockers = _blockers(payload)
    if blockers is not None:
        result_payload["blocker_count"] = len(blockers)
        result_payload["blockers"] = list(blockers)
    for field_name in (
        "solver_result",
        "reason_unknown",
        "release_ready",
        "production_release_blocked",
    ):
        if field_name in payload:
            result_payload[field_name] = payload[field_name]
    return result_payload


def map_legacy_result(
    legacy_output: Any,
    *,
    request: BackendRequest,
    attempt: BackendAttempt,
    family: SecurityResultFamily | str | None = None,
    issuer: str = "security-ir-legacy-result-adapter",
    method: str = LEGACY_RESULT_MAPPING_VERSION,
    configuration_digest: str = "",
) -> LegacyResultMapping:
    """Map one legacy output into its exact Security result family.

    The request is part of the authority boundary.  A proof request cannot be
    relabeled as a monitor, evidence gate, policy decision, or raw
    satisfiability result, and vice versa.
    """

    if not isinstance(request, BackendRequest):
        raise TypeError("request must be a BackendRequest")
    if not isinstance(attempt, BackendAttempt):
        raise TypeError("attempt must be a BackendAttempt")
    payload = _legacy_payload(legacy_output)
    source_digest = stable_digest(payload)
    source_schema = str(payload.get("schema_version", ""))

    if family is None:
        selected_family, inference_reason = _infer_family(payload)
    else:
        try:
            selected_family = SecurityResultFamily(family)
        except (TypeError, ValueError) as exc:
            allowed = ", ".join(item.value for item in SecurityResultFamily)
            raise SecurityResultValidationError(
                f"family must be one of: {allowed}"
            ) from exc
        inference_reason = "caller-supplied family"

    if request.query_kind is not selected_family.query_kind:
        raise AuthorityMismatchError(
            f"legacy {selected_family.value} output requires a "
            f"{selected_family.query_kind.value} request, not "
            f"{request.query_kind.value}"
        )

    status, status_diagnostics = _status_for(payload, selected_family)
    if (
        selected_family is SecurityResultFamily.DISPROOF
        and not any(
            payload.get(field_name)
            for field_name in ("counterexample", "witness", "proof_or_trace_cid")
        )
    ):
        raise SecurityResultValidationError(
            "legacy disproof has no counterexample or witness binding"
        )

    diagnostics = [
        LegacyResultDiagnostic(
            code=_FAMILY_DIAGNOSTIC[selected_family],
            message=(
                f"Legacy output was classified as {selected_family.value} "
                f"using {inference_reason}."
            ),
            source_field="result_family" if family is not None else "schema_version",
            metadata={
                "authority_kind": selected_family.query_kind.authority_kind.value,
                "inference": inference_reason,
            },
        ),
        *status_diagnostics,
    ]
    if selected_family is SecurityResultFamily.EVIDENCE_GATE and (
        _family_hint(payload) is SecurityResultFamily.EVIDENCE_GATE
        or "xaman" in source_schema.lower()
        or _blockers(payload) is not None
    ):
        diagnostics.append(
            LegacyResultDiagnostic(
                code="security.result.xaman_blocker_is_evidence_gate",
                message=(
                    "Blocker satisfiability was mapped to evidence readiness "
                    "and carries no theorem authority."
                ),
                source_field="solver_result",
            )
        )

    authority = ResultAuthority(
        kind=selected_family.query_kind.authority_kind,
        issuer=issuer,
        method=method,
        scope_digest=request.digest,
        configuration_digest=configuration_digest,
    )
    result_class = _FAMILY_RESULT_CLASS[selected_family]
    result = result_class.for_attempt(
        request,
        attempt,
        result_id=f"security-result:{source_digest[:24]}",
        authority=authority,
        status=status,
        payload=_result_payload(payload, selected_family, source_digest),
        diagnostics=tuple(item.code for item in diagnostics),
    )
    return LegacyResultMapping(
        result=result,
        family=selected_family,
        source_schema_version=source_schema,
        source_digest=source_digest,
        diagnostics=tuple(diagnostics),
    )


def map_xaman_blocker_satisfiability(
    legacy_output: Any,
    *,
    request: BackendRequest,
    attempt: BackendAttempt,
    issuer: str = "security-ir-xaman-evidence-gate-adapter",
    configuration_digest: str = "",
) -> LegacyResultMapping:
    """Map a Xaman blocker-existence check to evidence readiness only."""

    return map_legacy_result(
        legacy_output,
        request=request,
        attempt=attempt,
        family=SecurityResultFamily.EVIDENCE_GATE,
        issuer=issuer,
        method="xaman-blocker-evidence-gate/v1",
        configuration_digest=configuration_digest,
    )


def issue_proof_receipt(
    claim: Any,
    request: BackendRequest,
    attempt: BackendAttempt,
    result: BoundedResult,
    *,
    receipt_id: str,
    verifier: str,
) -> ProofReceipt:
    """Issue a theorem receipt only from an affirmative Security proof."""

    if not isinstance(result, CoreProofResult) or isinstance(result, DisproofResult):
        raise AuthorityMismatchError(
            f"{type(result).__name__} cannot construct a Security proof receipt"
        )
    return ProofReceipt.issue(
        claim,
        request,
        attempt,
        result,
        receipt_id=receipt_id,
        verifier=verifier,
    )


# Descriptive aliases used by migration and downstream Security adapters.
RuntimeMonitorResult = MonitorResult
ReleasePolicyDecision = PolicyDecision
SecurityProofReceipt = ProofReceipt


def result_family(result: BoundedResult) -> SecurityResultFamily:
    """Return the exact Security family for a typed shared/backend result."""

    if isinstance(result, DisproofResult):
        return SecurityResultFamily.DISPROOF
    if isinstance(result, CoreProofResult):
        return (
            SecurityResultFamily.DISPROOF
            if result.status is ResultStatus.DISPROVED
            else SecurityResultFamily.PROOF
        )
    if isinstance(result, MonitorResult):
        return SecurityResultFamily.RUNTIME_MONITOR
    if isinstance(result, EvidenceGateResult):
        return SecurityResultFamily.EVIDENCE_GATE
    if isinstance(result, PolicyDecision):
        return SecurityResultFamily.RELEASE_POLICY
    if isinstance(result, SatisfiabilityResult):
        return SecurityResultFamily.SATISFIABILITY
    raise SecurityResultValidationError(
        f"unsupported Security result type: {type(result).__name__}"
    )


__all__ = [
    "DisproofResult",
    "EvidenceGateResult",
    "LEGACY_RESULT_MAPPING_VERSION",
    "LegacyResultDiagnostic",
    "LegacyResultMapping",
    "MonitorResult",
    "PolicyDecision",
    "ProofReceipt",
    "ProofResult",
    "ReleasePolicyDecision",
    "RuntimeMonitorResult",
    "SECURITY_RESULT_INTERFACE_VERSION",
    "SatisfiabilityResult",
    "SecurityProofReceipt",
    "SecurityResult",
    "SecurityResultFamily",
    "SecurityResultValidationError",
    "issue_proof_receipt",
    "map_legacy_result",
    "map_xaman_blocker_satisfiability",
    "result_family",
]
