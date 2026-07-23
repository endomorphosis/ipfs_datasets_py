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
    TDFOL_SOUND_FALLBACK_SYSTEMS = {
        ModalSystem.KD: ModalSystem.D,
        ModalSystem.KD45: ModalSystem.D,
    }
    COMPILE_ONLY_SYSTEMS = {
        ModalSystem.FRAME_BM25,
        ModalSystem.LTL,
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
        if resolved_system in self.TDFOL_SOUND_FALLBACK_SYSTEMS:
            return self._route_tdfol_sound_fallback(formula, resolved_system)
        if resolved_system in self.COMPILE_ONLY_SYSTEMS:
            return self._route_compile_only(formula, resolved_system)
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

    def _route_tdfol_sound_fallback(
        self,
        formula: Any,
        system: ModalSystem,
    ) -> ModalProverRouteResult:
        """Route stronger registered systems through a sound weaker fallback."""

        fallback = self.TDFOL_SOUND_FALLBACK_SYSTEMS[system]
        routed = self._route_tdfol_tableaux(formula, fallback)
        metadata = dict(routed.metadata)
        metadata.update(
            {
                "fallback_complete": False,
                "fallback_sound_when_proved": True,
                "fallback_system": fallback.value,
                "original_system": system.value,
                "registered": True,
            }
        )
        if routed.status != ModalProverStatus.AVAILABLE:
            return ModalProverRouteResult(
                status=routed.status,
                system=system.value,
                backend=routed.backend,
                result=routed.result,
                reason=(
                    f"{system.value} fallback to {fallback.value} was attempted, "
                    f"but the fallback route is unavailable: {routed.reason}"
                ),
                metadata=metadata,
            )
        return ModalProverRouteResult(
            status=ModalProverStatus.AVAILABLE,
            system=system.value,
            backend="tdfol_modal_tableaux_fallback",
            result=routed.result,
            reason=(
                f"{system.value} routed through sound weaker-system fallback "
                f"{fallback.value}; non-proofs remain inconclusive for {system.value}."
            ),
            metadata=metadata,
        )

    def _route_compile_only(
        self,
        formula: Any,
        system: ModalSystem,
    ) -> ModalProverRouteResult:
        """Expose registered non-tableaux systems as bounded compile checks."""

        compiled = (
            formula.to_string(pretty=True)
            if hasattr(formula, "to_string")
            else str(formula)
            if formula is not None
            else ""
        )
        return ModalProverRouteResult(
            status=ModalProverStatus.AVAILABLE,
            system=system.value,
            backend=f"{system.value.lower()}_compile_only",
            result={
                "compile_only": True,
                "compiled_formula": compiled,
                "is_valid": False,
                "proof_supported": False,
            },
            reason=(
                f"{system.value} has a registered compiler/profile route but no "
                "complete local theorem prover adapter; treating it as compile-only."
            ),
            metadata={
                "proof_supported": False,
                "registered": True,
                "validation_mode": "compile_only",
            },
        )


__all__ = [
    "ModalProverRouteResult",
    "ModalProverRouter",
    "ModalProverStatus",
]
