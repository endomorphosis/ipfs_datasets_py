"""Receipts issued by proof consumers after checking proof reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from .proof_report import PROOF_REPORT_SCHEMA_VERSION, PROOF_STATUSES, ProofReport, validate_proof_report

PROOF_RECEIPT_SCHEMA_VERSION = 'proof-receipt/v1'


@dataclass(slots=True)
class ProofReceipt:
    claim_id: str
    model_cid: str
    proof_report_cid: str
    accepted_assumptions: list[str]
    verifier: str
    verifier_version: str
    valid: bool
    schema_version: str = PROOF_RECEIPT_SCHEMA_VERSION
    report_schema_version: str = PROOF_REPORT_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_proof_receipt(self)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'ProofReceipt':
        return cls(**dict(data))

    @classmethod
    def from_untrusted_dict(cls, data: Mapping[str, Any], *, report: ProofReport | None = None) -> 'ProofReceipt':
        if not isinstance(data, Mapping):
            raise ValueError('proof receipt payload must be a mapping')
        payload = dict(data)
        required = {
            'schema_version',
            'report_schema_version',
            'claim_id',
            'model_cid',
            'proof_report_cid',
            'accepted_assumptions',
            'verifier',
            'verifier_version',
            'valid',
            'metadata',
        }
        allowed = {field_name for field_name in cls.__dataclass_fields__}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f'Unknown proof receipt field(s): {", ".join(unknown)}')
        missing = sorted(field_name for field_name in required if field_name not in payload)
        if missing:
            raise ValueError(f'Missing required proof receipt field(s): {", ".join(missing)}')
        aa = payload.get('accepted_assumptions')
        if not isinstance(aa, list) or len(aa) == 0:
            raise ValueError('accepted_assumptions must be a non-empty list of assumption IDs')
        if report is not None:
            valid_assumption_ids = set(report.assumptions)
            unknown_assumptions = sorted(set(aa) - valid_assumption_ids)
            if unknown_assumptions:
                raise ValueError(
                    f'accepted_assumptions contains IDs not declared in the report: {", ".join(unknown_assumptions)}'
                )
            stored_cid = payload.get('proof_report_cid', '')
            if stored_cid and stored_cid != report.cid:
                raise ValueError('proof_report_cid does not match the provided report CID')
        return cls(**payload)

    @staticmethod
    def validate_report(
        report: ProofReport,
        *,
        accepted_assumptions: Iterable[str],
        allowed_statuses: Iterable[str] = ('PROVED',),
        supported_schema_versions: Iterable[str] = (PROOF_REPORT_SCHEMA_VERSION,),
        expected_model_cid: str | None = None,
        expected_claim_id: str | None = None,
        verifier: str,
        verifier_version: str,
    ) -> None:
        validate_proof_report(report)
        accepted = set(accepted_assumptions)
        allowed = set(allowed_statuses)
        supported = set(supported_schema_versions)
        if not verifier or not verifier_version:
            raise ValueError('verifier name and version are required')
        unsupported_statuses = sorted(status for status in allowed if status not in PROOF_STATUSES)
        if unsupported_statuses:
            raise ValueError(f'unsupported accepted proof statuses: {", ".join(unsupported_statuses)}')
        if expected_model_cid is not None and report.model_cid != expected_model_cid:
            raise ValueError('model_cid does not match report.model_cid')
        if expected_claim_id is not None and report.claim_id != expected_claim_id:
            raise ValueError('claim_id does not match report.claim_id')
        if report.status not in allowed:
            raise ValueError(f'report status {report.status} is not accepted as secure')
        if any(assumption not in accepted for assumption in report.assumptions):
            raise ValueError('report contains assumptions that were not accepted by the verifier')
        if report.schema_version not in supported:
            raise ValueError(f'unsupported proof report schema version: {report.schema_version}')

    @classmethod
    def from_report(
        cls,
        report: ProofReport,
        *,
        verifier: str,
        verifier_version: str,
        accepted_assumptions: Iterable[str] | None = None,
        allow_report_assumptions: bool = False,
        allowed_statuses: Iterable[str] = ('PROVED',),
        supported_schema_versions: Iterable[str] = (PROOF_REPORT_SCHEMA_VERSION,),
    ) -> 'ProofReceipt':
        if accepted_assumptions is None:
            if not allow_report_assumptions:
                raise ValueError('accepted_assumptions must be provided explicitly unless allow_report_assumptions=True (unsafe/test-only)')
            accepted = list(report.assumptions)
            metadata = {'unsafe_assumption_source': 'report'}
        else:
            accepted = list(accepted_assumptions)
            metadata = {}
        cls.validate_report(
            report,
            accepted_assumptions=accepted,
            allowed_statuses=allowed_statuses,
            supported_schema_versions=supported_schema_versions,
            expected_model_cid=report.model_cid,
            expected_claim_id=report.claim_id,
            verifier=verifier,
            verifier_version=verifier_version,
        )
        return cls(
            claim_id=report.claim_id,
            model_cid=report.model_cid,
            proof_report_cid=report.cid,
            accepted_assumptions=accepted,
            verifier=verifier,
            verifier_version=verifier_version,
            valid=True,
            report_schema_version=report.schema_version,
            metadata=metadata,
        )


def _require_non_empty_string(field_name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field_name} must be a non-empty string')


def _require_string_list(field_name: str, value: Any) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f'{field_name} must be a list of non-empty strings')



def validate_proof_receipt(receipt: ProofReceipt | Mapping[str, Any]) -> ProofReceipt:
    """Validate *receipt* and return a normalized :class:`ProofReceipt`."""

    normalized = receipt if isinstance(receipt, ProofReceipt) else ProofReceipt.from_untrusted_dict(receipt)
    _require_non_empty_string('schema_version', normalized.schema_version)
    _require_non_empty_string('report_schema_version', normalized.report_schema_version)
    _require_non_empty_string('claim_id', normalized.claim_id)
    _require_non_empty_string('model_cid', normalized.model_cid)
    _require_non_empty_string('proof_report_cid', normalized.proof_report_cid)
    _require_non_empty_string('verifier', normalized.verifier)
    _require_non_empty_string('verifier_version', normalized.verifier_version)
    if normalized.schema_version != PROOF_RECEIPT_SCHEMA_VERSION:
        raise ValueError(f'unsupported proof receipt schema version: {normalized.schema_version}')
    _require_string_list('accepted_assumptions', normalized.accepted_assumptions)
    if not normalized.accepted_assumptions:
        raise ValueError('accepted_assumptions must be non-empty')
    if not isinstance(normalized.valid, bool):
        raise ValueError('valid must be a boolean')
    if not isinstance(normalized.metadata, dict):
        raise ValueError('metadata must be a mapping')
    return normalized
