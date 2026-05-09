"""Typed routing from modal profiles to available prover backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from .modal_registry import ModalSystem


class ModalProverStatus(Enum):
    """Status for modal prover routing and execution."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class ModalProverRouteResult:
    """Result of routing a modal formula/profile to a prover."""

    status: ModalProverStatus
    system: str
    backend: Optional[str] = None
    result: Any = None
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class ModalProverRouter:
    """Route modal systems to the strongest currently available prover."""

    TDFOL_TABLEAUX_SYSTEMS = {
        ModalSystem.K,
        ModalSystem.T,
        ModalSystem.D,
        ModalSystem.S4,
        ModalSystem.S5,
    }

    def route(
        self,
        *,
        formula: Any,
        system: ModalSystem | str,
    ) -> ModalProverRouteResult:
        """Route and optionally prove a formula for a modal system."""
        resolved_system = system if isinstance(system, ModalSystem) else ModalSystem(str(system))
        if resolved_system in self.TDFOL_TABLEAUX_SYSTEMS:
            return self._route_tdfol_tableaux(formula, resolved_system)
        if resolved_system in {ModalSystem.KD, ModalSystem.KD45}:
            return ModalProverRouteResult(
                status=ModalProverStatus.UNAVAILABLE,
                system=resolved_system.value,
                reason=f"{resolved_system.value} routing is registered, but no KD/KD45 tableaux adapter is available yet.",
                metadata={"registered": True},
            )
        return ModalProverRouteResult(
            status=ModalProverStatus.UNAVAILABLE,
            system=resolved_system.value,
            reason=f"No modal prover adapter is registered for {resolved_system.value}.",
            metadata={"registered": False},
        )

    def _route_tdfol_tableaux(self, formula: Any, system: ModalSystem) -> ModalProverRouteResult:
        try:
            from ipfs_datasets_py.logic.TDFOL.modal_tableaux import (
                ModalLogicType,
                prove_modal_formula,
            )
            logic_type = ModalLogicType(system.value)
            if formula is None:
                return ModalProverRouteResult(
                    status=ModalProverStatus.AVAILABLE,
                    system=system.value,
                    backend="tdfol_modal_tableaux",
                    reason="TDFOL modal tableaux adapter is available; no formula was provided.",
                    metadata={"logic_type": logic_type.value},
                )
            return ModalProverRouteResult(
                status=ModalProverStatus.AVAILABLE,
                system=system.value,
                backend="tdfol_modal_tableaux",
                result=prove_modal_formula(formula, logic_type),
                metadata={"logic_type": logic_type.value},
            )
        except (ImportError, AttributeError, RuntimeError, TypeError, ValueError) as error:
            return ModalProverRouteResult(
                status=ModalProverStatus.UNAVAILABLE,
                system=system.value,
                backend="tdfol_modal_tableaux",
                reason=str(error),
            )


__all__ = [
    "ModalProverRouteResult",
    "ModalProverRouter",
    "ModalProverStatus",
]
