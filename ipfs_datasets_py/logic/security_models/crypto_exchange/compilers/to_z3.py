"""Z3 compiler contracts for exchange security claims."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Z3Compilation:
    """Compiled Z3 artifact for a single security claim."""

    claim: Any
    assertions: list[Any] = field(default_factory=list)
    property_formula: Any | None = None
    violation_formula: Any | None = None
    compiler_artifact: dict[str, Any] = field(default_factory=dict)
    not_modeled_reason: str | None = None
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    soundness_notes: list[str] = field(default_factory=list)
    violation_scope_explanation: str | None = None

    def __post_init__(self) -> None:
        if self.not_modeled_reason is not None:
            return
        if self.property_formula is None:
            raise ValueError('modeled Z3 compilations must define a property_formula')
        if self.violation_formula is None:
            z3 = z3_import()
            self.violation_formula = z3.Not(self.property_formula)
            return
        if self.violation_scope_explanation is not None:
            return
        z3 = z3_import()
        if not (z3.is_not(self.violation_formula) and self.violation_formula.arg(0).eq(self.property_formula)):
            raise ValueError('custom violation_formula requires violation_scope_explanation')

    @property
    def modeled(self) -> bool:
        return self.not_modeled_reason is None



def z3_import() -> Any:
    """Import Z3 lazily so the package remains optional-dependency friendly."""

    import z3

    return z3



def claim_not_modeled(
    claim: Any,
    reason: str,
    *,
    evidence_refs: list[dict[str, Any]] | None = None,
    soundness_notes: list[str] | None = None,
) -> Z3Compilation:
    """Return a marker stating that the claim is not modeled for Z3."""

    return Z3Compilation(
        claim=claim,
        not_modeled_reason=reason,
        evidence_refs=list(evidence_refs or []),
        soundness_notes=list(soundness_notes or []),
    )
