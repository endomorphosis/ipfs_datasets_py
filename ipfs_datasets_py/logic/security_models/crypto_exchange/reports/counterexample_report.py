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
    violating_event_ids: list[str] = field(default_factory=list)
    withdrawal_ids: list[str] = field(default_factory=list)
    deposit_ids: list[str] = field(default_factory=list)
    txids: list[str] = field(default_factory=list)
    capability_ids: list[str] = field(default_factory=list)
    wallet_ids: list[str] = field(default_factory=list)
    account_ids: list[str] = field(default_factory=list)
    asset_ids: list[str] = field(default_factory=list)
    source_facts: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    soundness_notes: list[str] = field(default_factory=list)
    compiler_artifact: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def cid(self) -> str:
        return calculate_artifact_cid(self.to_dict())
