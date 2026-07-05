"""Receipts issued by proof consumers after checking proof reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from .proof_report import PROOF_REPORT_SCHEMA_VERSION, ProofReport

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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'ProofReceipt':
        return cls(**dict(data))

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
        accepted = set(accepted_assumptions)
        allowed = set(allowed_statuses)
        supported = set(supported_schema_versions)
        if not verifier or not verifier_version:
            raise ValueError('verifier name and version are required')
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
        allowed_statuses: Iterable[str] = ('PROVED',),
        supported_schema_versions: Iterable[str] = (PROOF_REPORT_SCHEMA_VERSION,),
    ) -> 'ProofReceipt':
        accepted = list(accepted_assumptions if accepted_assumptions is not None else report.assumptions)
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
        )
