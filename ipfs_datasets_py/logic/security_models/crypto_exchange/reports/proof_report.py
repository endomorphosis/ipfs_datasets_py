"""Proof report envelope for exchange security claims."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from ..ir.cid import calculate_artifact_cid

PROOF_REPORT_SCHEMA_VERSION = 'proof-report/v1'



def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class ProofReport:
    claim_id: str
    model_cid: str
    status: str
    prover: str
    proof_or_trace_cid: str
    assumptions: list[str]
    compiler_cid: str
    created_at: str | None = None
    counterexample: dict[str, Any] | None = None
    risk: str = 'medium'
    signatures: list[dict[str, Any]] = field(default_factory=list)
    schema_version: str = PROOF_REPORT_SCHEMA_VERSION
    claim_version: str = '1.0'
    model_schema_version: str = ''
    solver_name: str = ''
    solver_version: str = ''
    solver_result: str = ''
    timeout_ms: int | None = None
    reason_unknown: str | None = None
    assertion_count: int | None = None
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    soundness_notes: list[str] = field(default_factory=list)
    unsat_core: list[str] | None = None
    generated_at: str | None = None
    deterministic_payload_cid: str = ''
    nondeterministic_report_cid: str = ''

    def __post_init__(self) -> None:
        timestamp = self.generated_at or self.created_at or _utc_now()
        self.generated_at = timestamp
        self.created_at = timestamp
        if not self.solver_name:
            self.solver_name = self.prover
        if not self.deterministic_payload_cid:
            self.deterministic_payload_cid = self.content_cid(self.deterministic_payload())
        if not self.nondeterministic_report_cid:
            self.nondeterministic_report_cid = self.content_cid(self.nondeterministic_payload())

    def deterministic_payload(self) -> dict[str, Any]:
        payload = {
            'schema_version': self.schema_version,
            'claim_id': self.claim_id,
            'claim_version': self.claim_version,
            'model_cid': self.model_cid,
            'model_schema_version': self.model_schema_version,
            'status': self.status,
            'prover': self.prover,
            'solver_name': self.solver_name,
            'solver_version': self.solver_version,
            'solver_result': self.solver_result,
            'proof_or_trace_cid': self.proof_or_trace_cid,
            'assumptions': list(self.assumptions),
            'compiler_cid': self.compiler_cid,
            'counterexample': self.counterexample,
            'risk': self.risk,
            'signatures': list(self.signatures),
            'timeout_ms': self.timeout_ms,
            'reason_unknown': self.reason_unknown,
            'assertion_count': self.assertion_count,
            'evidence_refs': list(self.evidence_refs),
            'soundness_notes': list(self.soundness_notes),
            'unsat_core': list(self.unsat_core) if self.unsat_core is not None else None,
        }
        return payload

    def nondeterministic_payload(self) -> dict[str, Any]:
        payload = self.deterministic_payload()
        payload.update(
            {
                'created_at': self.created_at,
                'generated_at': self.generated_at,
                'deterministic_payload_cid': self.deterministic_payload_cid,
            }
        )
        return payload

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload['deterministic_payload_cid'] = self.deterministic_payload_cid
        payload['nondeterministic_report_cid'] = self.nondeterministic_report_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'ProofReport':
        payload = dict(data)
        if 'generated_at' not in payload and 'created_at' in payload:
            payload['generated_at'] = payload['created_at']
        return cls(**payload)

    @classmethod
    def content_cid(cls, payload: Mapping[str, Any]) -> str:
        return calculate_artifact_cid(dict(payload))

    @property
    def cid(self) -> str:
        return self.nondeterministic_report_cid
