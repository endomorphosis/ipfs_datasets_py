from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence


Direction = Literal["outgoing", "incoming", "both"]


@dataclass(frozen=True)
class Op:
    """Base class for IR operators."""


@dataclass(frozen=True)
class SeedEntities(Op):
    entity_ids: Sequence[str]


@dataclass(frozen=True)
class ScanType(Op):
    entity_type: str
    # Optional scope constraint (e.g., dataset/graph roots). Backend-defined.
    scope: Sequence[str] | None = None


@dataclass(frozen=True)
class Expand(Op):
    relationship_types: Sequence[str] | None = None
    direction: Direction = "both"
    max_per_node: int | None = None


@dataclass(frozen=True)
class Limit(Op):
    n: int


@dataclass(frozen=True)
class Project(Op):
    fields: Sequence[str] = ("id", "type", "name")


@dataclass
class QueryIR:
    """A linear pipeline IR for v1."""

    ops: list[Op] = field(default_factory=list)

    def add(self, op: Op) -> "QueryIR":
        self.ops.append(op)
        return self

    @classmethod
    def from_ops(cls, ops: Sequence[Op]) -> "QueryIR":
        return cls(list(ops))


@dataclass(frozen=True)
class ExecutionResult:
    items: list[dict[str, Any]]
    stats: dict[str, Any]
