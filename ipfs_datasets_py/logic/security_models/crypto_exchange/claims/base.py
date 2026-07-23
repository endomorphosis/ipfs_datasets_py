"""Base claim interfaces for exchange security proofs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..compilers.to_z3 import Z3Compilation
from ..ir.schema import SecurityModelIR, collect_evidence_refs


@dataclass(slots=True)
class SecurityClaim(ABC):
    """Base class for declarative exchange security claims."""

    claim_id: str
    description: str
    required_assumptions: list[str] = field(default_factory=list)
    severity: str = 'medium'
    claim_version: str = '1.0'

    @abstractmethod
    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        """Compile the claim into a Z3-checkable artifact."""

    @staticmethod
    def policy_enabled(model: SecurityModelIR, name: str) -> bool:
        for policy in model.policies:
            if policy.get('name') == name:
                return bool(policy.get('enabled', False))
        return False

    @staticmethod
    def policy_record(model: SecurityModelIR, name: str) -> Mapping[str, Any] | None:
        for policy in model.policies:
            if policy.get('name') == name:
                return policy
        return None

    @staticmethod
    def iter_accounts(model: SecurityModelIR) -> list[Mapping[str, Any]]:
        return list(model.accounts)

    @staticmethod
    def iter_capabilities(model: SecurityModelIR) -> list[Mapping[str, Any]]:
        return list(model.capabilities)

    @staticmethod
    def find_events(model: SecurityModelIR, event_name: str) -> list[Mapping[str, Any]]:
        return [event for event in model.events if event.get('event') == event_name]

    @staticmethod
    def evidence_refs(*records: Mapping[str, Any] | None) -> list[dict[str, Any]]:
        return [dict(reference) for reference in collect_evidence_refs(*records)]

    @staticmethod
    def heuristic_soundness_note(evidence_refs: list[dict[str, Any]]) -> list[str]:
        if not evidence_refs:
            return ['No explicit evidence references were attached to the modeled facts.']
        if all(reference.get('review_status') == 'heuristic' for reference in evidence_refs):
            return ['All supporting facts are heuristic extractions and require review before blocking security use.']
        return []
