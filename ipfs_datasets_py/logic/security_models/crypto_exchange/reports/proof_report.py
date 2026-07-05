"""Proof report envelope for exchange security claims."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from ..ir.cid import calculate_artifact_cid


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
    created_at: str = field(default_factory=_utc_now)
    counterexample: dict[str, Any] | None = None
    risk: str = 'medium'
    signatures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> 'ProofReport':
        return cls(**dict(data))

    @classmethod
    def content_cid(cls, payload: Mapping[str, Any]) -> str:
        return calculate_artifact_cid(dict(payload))

    @property
    def cid(self) -> str:
        return self.content_cid(self.to_dict())
