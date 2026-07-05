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

    @property
    def modeled(self) -> bool:
        return self.not_modeled_reason is None


def z3_import() -> Any:
    """Import Z3 lazily so the package remains optional-dependency friendly."""

    import z3
    return z3


def claim_not_modeled(claim: Any, reason: str) -> Z3Compilation:
    """Return a marker stating that the claim is not modeled for Z3."""

    return Z3Compilation(claim=claim, not_modeled_reason=reason)
