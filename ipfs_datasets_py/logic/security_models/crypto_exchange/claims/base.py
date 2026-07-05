"""Base claim interfaces for exchange security proofs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..compilers.to_z3 import Z3Compilation
from ..ir.schema import SecurityModelIR


@dataclass(slots=True)
class SecurityClaim(ABC):
    """Base class for declarative exchange security claims."""

    claim_id: str
    description: str
    required_assumptions: list[str] = field(default_factory=list)
    severity: str = 'medium'

    @abstractmethod
    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        """Compile the claim into a Z3-checkable artifact."""

    def compile_to_tla(self, model: SecurityModelIR) -> str:
        raise NotImplementedError(f'{self.claim_id} does not yet compile to TLA+')

    def compile_to_datalog(self, model: SecurityModelIR) -> str:
        raise NotImplementedError(f'{self.claim_id} does not yet compile to Datalog')

    @staticmethod
    def policy_enabled(model: SecurityModelIR, name: str) -> bool:
        for policy in model.policies:
            if policy.get('name') == name:
                return bool(policy.get('enabled', False))
        return False

    @staticmethod
    def find_account(model: SecurityModelIR) -> Mapping[str, Any]:
        if not model.accounts:
            raise ValueError('SecurityModelIR.accounts must not be empty for account claims')
        return model.accounts[0]

    @staticmethod
    def find_capability(model: SecurityModelIR) -> Mapping[str, Any]:
        if not model.capabilities:
            raise ValueError('SecurityModelIR.capabilities must not be empty for capability claims')
        return model.capabilities[0]

    @staticmethod
    def find_event(model: SecurityModelIR, event_name: str) -> Mapping[str, Any] | None:
        for event in model.events:
            if event.get('event') == event_name:
                return event
        return None
