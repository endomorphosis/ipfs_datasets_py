"""Receipts issued by proof consumers after checking proof reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .proof_report import ProofReport


@dataclass(slots=True)
class ProofReceipt:
    claim_id: str
    model_cid: str
    proof_report_cid: str
    accepted_assumptions: list[str]
    verifier: str
    verifier_version: str
    valid: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'ProofReceipt':
        return cls(**dict(data))

    @classmethod
    def from_report(
        cls,
        report: ProofReport,
        *,
        verifier: str,
        verifier_version: str,
        valid: bool,
    ) -> 'ProofReceipt':
        return cls(
            claim_id=report.claim_id,
            model_cid=report.model_cid,
            proof_report_cid=report.cid,
            accepted_assumptions=list(report.assumptions),
            verifier=verifier,
            verifier_version=verifier_version,
            valid=valid,
        )
