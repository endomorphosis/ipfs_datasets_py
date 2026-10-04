"""Planning proof obligations (EAAEF-072)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final


OBLIGATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/logic/external-work-plan-obligations@1"
)
KINDS: Final[frozenset[str]] = frozenset(
    {
        "child_covers_parent",
        "safe_parallel_effects",
        "validation_before_acceptance",
        "immutable_criteria",
        "no_self_granted_authority",
    }
)


class ObligationError(ValueError):
    """Plan obligation failed."""


@dataclass(frozen=True)
class PlanObligation:
    kind: str
    holds: bool
    reason_code: str = "holds"

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ObligationError(f"unknown obligation: {self.kind}")
        if self.kind == "no_self_granted_authority" and not self.holds:
            raise ObligationError("self-granted authority is not admitted")

    def to_dict(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": OBLIGATION_SCHEMA,
                "kind": self.kind,
                "holds": bool(self.holds),
                "reason_code": self.reason_code,
            }
        )


def prove(obligations: Sequence[Mapping[str, Any] | PlanObligation]) -> tuple[PlanObligation, ...]:
    compiled = []
    for item in obligations:
        if isinstance(item, PlanObligation):
            compiled.append(item)
        else:
            compiled.append(
                PlanObligation(
                    kind=str(item.get("kind") or ""),
                    holds=bool(item.get("holds", True)),
                    reason_code=str(item.get("reason_code") or "holds"),
                )
            )
    missing = KINDS.difference(item.kind for item in compiled)
    if missing:
        raise ObligationError(f"missing obligation {sorted(missing)[0]}")
    if any(not item.holds for item in compiled):
        raise ObligationError("plan obligations do not all hold")
    return tuple(compiled)
