"""Counterexample reports produced by security claim runners."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..ir.cid import calculate_artifact_cid


@dataclass(slots=True)
class CounterexampleReport:
    claim_id: str
    message: str
    witness: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def cid(self) -> str:
        return calculate_artifact_cid(self.to_dict())
