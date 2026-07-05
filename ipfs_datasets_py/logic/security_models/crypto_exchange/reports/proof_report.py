"""Proof report envelope for exchange security claims."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping

from ..ir.cid import calculate_artifact_cid

PROOF_REPORT_SCHEMA_VERSION = 'proof-report/v1'
PROOF_STATUS_PROVED = 'PROVED'
PROOF_STATUS_DISPROVED = 'DISPROVED'
PROOF_STATUS_UNKNOWN = 'UNKNOWN'
PROOF_STATUS_NOT_MODELED = 'NOT_MODELED'
PROOF_STATUSES = frozenset(
    {
        PROOF_STATUS_PROVED,
        PROOF_STATUS_DISPROVED,
        PROOF_STATUS_UNKNOWN,
        PROOF_STATUS_NOT_MODELED,
    }
)
PROOF_RISK_BLOCKING = 'blocking'
PROOF_RISK_HIGH = 'high'
PROOF_RISK_MEDIUM = 'medium'
PROOF_RISK_LOW = 'low'
PROOF_RISKS = frozenset(
    {
        PROOF_RISK_BLOCKING,
        PROOF_RISK_HIGH,
        PROOF_RISK_MEDIUM,
        PROOF_RISK_LOW,
    }
)
ProofStatus = Literal['PROVED', 'DISPROVED', 'UNKNOWN', 'NOT_MODELED']
ProofRisk = Literal['blocking', 'high', 'medium', 'low']



def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class ProofReport:
    claim_id: str
    model_cid: str
    status: ProofStatus
    prover: str
    proof_or_trace_cid: str
    assumptions: list[str]
    compiler_cid: str
    created_at: str | None = None
    counterexample: dict[str, Any] | None = None
    risk: ProofRisk = 'medium'
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
        _validate_proof_report_instance(self)

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


def _require_non_empty_string(field_name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field_name} must be a non-empty string')


def _require_string_list(field_name: str, value: Any) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f'{field_name} must be a list of non-empty strings')


def _require_non_negative_int(field_name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f'{field_name} must be a non-negative integer when present')



def _validate_proof_report_instance(report: ProofReport) -> None:
    _require_non_empty_string('schema_version', report.schema_version)
    _require_non_empty_string('claim_id', report.claim_id)
    _require_non_empty_string('claim_version', report.claim_version)
    _require_non_empty_string('model_cid', report.model_cid)
    _require_non_empty_string('model_schema_version', report.model_schema_version)
    _require_non_empty_string('prover', report.prover)
    _require_non_empty_string('solver_name', report.solver_name)
    _require_non_empty_string('solver_result', report.solver_result)
    _require_non_empty_string('deterministic_payload_cid', report.deterministic_payload_cid)
    _require_non_empty_string('nondeterministic_report_cid', report.nondeterministic_report_cid)
    if report.status not in PROOF_STATUSES:
        raise ValueError(f'unsupported proof status: {report.status}')
    if report.risk not in PROOF_RISKS:
        raise ValueError(f'unsupported proof risk: {report.risk}')
    _require_string_list('assumptions', report.assumptions)
    if not isinstance(report.signatures, list):
        raise ValueError('signatures must be a list')
    if not isinstance(report.evidence_refs, list):
        raise ValueError('evidence_refs must be a list')
    if not isinstance(report.soundness_notes, list) or any(not isinstance(item, str) for item in report.soundness_notes):
        raise ValueError('soundness_notes must be a list of strings')
    if report.unsat_core is not None:
        _require_string_list('unsat_core', report.unsat_core)
    if report.counterexample is not None and not isinstance(report.counterexample, dict):
        raise ValueError('counterexample must be a mapping when present')
    if report.timeout_ms is not None:
        _require_non_negative_int('timeout_ms', report.timeout_ms)
    if report.assertion_count is not None:
        _require_non_negative_int('assertion_count', report.assertion_count)


def validate_proof_report(report: ProofReport | Mapping[str, Any]) -> ProofReport:
    """Validate *report* and return a normalized :class:`ProofReport`."""

    normalized = report if isinstance(report, ProofReport) else ProofReport.from_dict(report)
    _validate_proof_report_instance(normalized)
    return normalized
