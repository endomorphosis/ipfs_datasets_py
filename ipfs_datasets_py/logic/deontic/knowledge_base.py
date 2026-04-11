"""Generic temporal and deontic knowledge-base primitives."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Optional, Set, Tuple


class KnowledgeDeonticModality(Enum):
    OBLIGATORY = "O"
    PERMITTED = "P"
    PROHIBITED = "F"
    OPTIONAL = "OPT"


class KnowledgeTemporalOperator(Enum):
    BEFORE = "before"
    AFTER = "after"
    COINCIDENT = "coincident"
    DURING = "during"
    OVERLAPS = "overlaps"
    STARTS = "starts"
    FINISHES = "finishes"
    EQUALS = "equals"


class KnowledgeLogicalOperator(Enum):
    AND = "and"
    OR = "or"
    NOT = "not"
    IMPLIES = "implies"
    IFF = "iff"
    FORALL = "forall"
    EXISTS = "exists"


@dataclass(frozen=True)
class TimeInterval:
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    duration_days: Optional[int] = None

    def resolved_end(self) -> Optional[datetime]:
        if self.end is not None:
            return self.end
        if self.start is not None and self.duration_days is not None:
            return self.start + timedelta(days=self.duration_days)
        return None

    def contains(self, at_time: datetime) -> bool:
        resolved_end = self.resolved_end()
        if self.start is not None and at_time < self.start:
            return False
        if resolved_end is not None and at_time > resolved_end:
            return False
        return True


@dataclass(frozen=True)
class Party:
    name: str
    role: str
    entity_id: str

    def __str__(self) -> str:
        return f"{self.name} ({self.role})"


@dataclass(frozen=True)
class Action:
    verb: str
    object_noun: str
    action_id: str

    def __str__(self) -> str:
        return f"{self.verb} {self.object_noun}"


class Proposition(ABC):
    @abstractmethod
    def __str__(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def evaluate(self, model: Dict[str, Any]) -> bool:
        raise NotImplementedError


@dataclass(frozen=True)
class Predicate(Proposition):
    name: str
    args: Tuple[Any, ...] = field(default_factory=tuple)

    def __str__(self) -> str:
        return f"{self.name}({', '.join(str(arg) for arg in self.args)})"

    def evaluate(self, model: Dict[str, Any]) -> bool:
        return bool(model.get(str(self), False))


@dataclass(frozen=True)
class Conjunction(Proposition):
    left: Proposition
    right: Proposition

    def __str__(self) -> str:
        return f"({self.left} and {self.right})"

    def evaluate(self, model: Dict[str, Any]) -> bool:
        return self.left.evaluate(model) and self.right.evaluate(model)


@dataclass(frozen=True)
class Disjunction(Proposition):
    left: Proposition
    right: Proposition

    def __str__(self) -> str:
        return f"({self.left} or {self.right})"

    def evaluate(self, model: Dict[str, Any]) -> bool:
        return self.left.evaluate(model) or self.right.evaluate(model)


@dataclass(frozen=True)
class Negation(Proposition):
    prop: Proposition

    def __str__(self) -> str:
        return f"not ({self.prop})"

    def evaluate(self, model: Dict[str, Any]) -> bool:
        return not self.prop.evaluate(model)


@dataclass(frozen=True)
class Implication(Proposition):
    antecedent: Proposition
    consequent: Proposition

    def __str__(self) -> str:
        return f"({self.antecedent} -> {self.consequent})"

    def evaluate(self, model: Dict[str, Any]) -> bool:
        return (not self.antecedent.evaluate(model)) or self.consequent.evaluate(model)


@dataclass(frozen=True)
class DeonticStatement:
    modality: KnowledgeDeonticModality
    actor: Party
    action: Action
    recipient: Optional[Party] = None
    time_interval: Optional[TimeInterval] = None
    condition: Optional[Proposition] = None


class DeonticKnowledgeBase:
    """Stores deontic statements, rules, and ground facts."""

    def __init__(self) -> None:
        self.statements: Set[DeonticStatement] = set()
        self.rules: list[tuple[Proposition, DeonticStatement]] = []
        self.facts: Dict[str, bool] = {}
        self.derived_statements: Set[DeonticStatement] = set()

    def add_statement(self, statement: DeonticStatement) -> None:
        self.statements.add(statement)

    def add_rule(self, condition: Proposition, statement: DeonticStatement) -> None:
        self.rules.append((condition, statement))

    def add_fact(self, fact_name: str, value: bool = True) -> None:
        self.facts[fact_name] = value

    def infer_statements(self) -> Set[DeonticStatement]:
        derived = set(self.statements)
        changed = True
        while changed:
            changed = False
            for condition, statement in self.rules:
                if condition.evaluate(self.facts) and statement not in derived:
                    derived.add(statement)
                    changed = True
        self.derived_statements = derived
        return derived

    def check_compliance(self, actor: Party, action: Action, at_time: datetime) -> tuple[bool, str]:
        statements = self.derived_statements or self.statements
        matching = [statement for statement in statements if statement.actor == actor and statement.action == action]
        for statement in matching:
            if statement.modality == KnowledgeDeonticModality.PROHIBITED:
                return False, f"{actor} violates prohibition against {action}"
            if statement.modality == KnowledgeDeonticModality.OBLIGATORY:
                if statement.time_interval and not statement.time_interval.contains(at_time):
                    return False, f"{actor} is outside the obligation window for {action}"
                return True, f"{actor} complies with obligation to {action}"
        return True, f"No active contrary deontic rule found for {actor} and {action}"


__all__ = [
    "Action",
    "Conjunction",
    "DeonticKnowledgeBase",
    "DeonticStatement",
    "Disjunction",
    "Implication",
    "KnowledgeDeonticModality",
    "KnowledgeLogicalOperator",
    "KnowledgeTemporalOperator",
    "Negation",
    "Party",
    "Predicate",
    "Proposition",
    "TimeInterval",
]


# ---------------------------------------------------------------------------
# Opportunistic bridge — when lib.formal_logic.core is on sys.path, replace
# the standalone pure-data types with the canonical lib implementations.
# DeonticKnowledgeBase is kept local (its check_compliance semantics differ).
# The `Knowledge*` aliases map lib's shorter names to this module's public API.
# ---------------------------------------------------------------------------
try:
    from lib.formal_logic.core import (  # noqa: E402
        DeonticModality as KnowledgeDeonticModality,
        TemporalOperator as KnowledgeTemporalOperator,
        LogicalOperator as KnowledgeLogicalOperator,
        TimeInterval,
        Party,
        Action,
        Proposition,
        Predicate,
        Conjunction,
        Disjunction,
        Negation,
        Implication,
        DeonticStatement,
    )
except ImportError:  # pragma: no cover - standalone path; definitions above apply
    pass
