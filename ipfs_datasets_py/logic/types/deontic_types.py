"""Deontic logic type definitions (import-safe).

This module intentionally avoids importing anything from
`ipfs_datasets_py.logic.integration` so that importing
`ipfs_datasets_py.logic.api` stays lightweight and does not trigger optional
dependencies, logging configuration, or warning cascades.

The types here mirror the public shape of the integration equivalents closely
enough for the core logic layer and typing usage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class DeonticOperator(Enum):
    """Deontic operators for representing normative concepts."""

    OBLIGATION = "O"
    PERMISSION = "P"
    PROHIBITION = "F"
    SUPEREROGATION = "S"
    RIGHT = "R"
    LIBERTY = "L"
    POWER = "POW"
    IMMUNITY = "IMM"


class TemporalOperator(Enum):
    """Temporal operators for time-dependent concepts."""

    ALWAYS = "□"
    EVENTUALLY = "◊"
    NEXT = "X"
    UNTIL = "U"
    SINCE = "S"


@dataclass
class LegalAgent:
    """Represents a legal agent (person, organization, role)."""

    identifier: str
    name: str
    agent_type: str
    properties: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.hash = hashlib.md5(
            f"{self.identifier}:{self.name}:{self.agent_type}".encode()
        ).hexdigest()[:8]


@dataclass
class TemporalCondition:
    """Represents temporal conditions in legal formulas."""

    operator: TemporalOperator
    condition: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration: Optional[str] = None


@dataclass
class LegalContext:
    """Represents the context in which a deontic formula applies."""

    jurisdiction: Optional[str] = None
    legal_domain: Optional[str] = None
    applicable_law: Optional[str] = None
    precedents: List[str] = field(default_factory=list)
    exceptions: List[str] = field(default_factory=list)


@dataclass
class DeonticFormula:
    """Represents a deontic first-order logic formula."""

    operator: DeonticOperator
    proposition: str
    agent: Optional[LegalAgent] = None
    beneficiary: Optional[LegalAgent] = None
    conditions: List[str] = field(default_factory=list)
    temporal_conditions: List[TemporalCondition] = field(default_factory=list)
    legal_context: Optional[LegalContext] = None
    confidence: float = 1.0
    source_text: str = ""
    variables: Dict[str, str] = field(default_factory=dict)
    quantifiers: List[Tuple[str, str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.formula_id = self._generate_formula_id()
        self.creation_timestamp = datetime.now().isoformat()

    def _generate_formula_id(self) -> str:
        content = f"{self.operator.value}:{self.proposition}:{self.agent}:{self.conditions}"
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def to_fol_string(self) -> str:
        formula_parts = [self.operator.value]
        if self.agent:
            formula_parts.append(f"[{self.agent.identifier}]")
        prop = self.proposition
        for quantifier, variable, domain in self.quantifiers:
            prop = f"{quantifier}{variable}:{domain} ({prop})"
        if self.conditions:
            conditions_str = " ∧ ".join(self.conditions)
            prop = f"({conditions_str}) → ({prop})"
        for temp_cond in self.temporal_conditions:
            prop = f"{temp_cond.operator.value}({prop})"
        formula_parts.append(f"({prop})")
        return "".join(formula_parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "formula_id": self.formula_id,
            "operator": self.operator.value,
            "proposition": self.proposition,
            "agent": self.agent.__dict__ if self.agent else None,
            "beneficiary": self.beneficiary.__dict__ if self.beneficiary else None,
            "conditions": self.conditions,
            "temporal_conditions": [
                {
                    "operator": tc.operator.value,
                    "condition": tc.condition,
                    "start_time": tc.start_time,
                    "end_time": tc.end_time,
                    "duration": tc.duration,
                }
                for tc in self.temporal_conditions
            ],
            "legal_context": self.legal_context.__dict__ if self.legal_context else None,
            "confidence": self.confidence,
            "source_text": self.source_text,
            "variables": self.variables,
            "quantifiers": self.quantifiers,
            "fol_string": self.to_fol_string(),
            "creation_timestamp": self.creation_timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeonticFormula":
        agent = None
        if data.get("agent"):
            agent_data = data["agent"]
            agent = LegalAgent(
                identifier=agent_data["identifier"],
                name=agent_data["name"],
                agent_type=agent_data["agent_type"],
                properties=agent_data.get("properties", {}),
            )

        beneficiary = None
        if data.get("beneficiary"):
            ben_data = data["beneficiary"]
            beneficiary = LegalAgent(
                identifier=ben_data["identifier"],
                name=ben_data["name"],
                agent_type=ben_data["agent_type"],
                properties=ben_data.get("properties", {}),
            )

        temporal_conditions: List[TemporalCondition] = []
        for tc_data in data.get("temporal_conditions", []):
            temporal_conditions.append(
                TemporalCondition(
                    operator=TemporalOperator(tc_data["operator"]),
                    condition=tc_data["condition"],
                    start_time=tc_data.get("start_time"),
                    end_time=tc_data.get("end_time"),
                    duration=tc_data.get("duration"),
                )
            )

        legal_context = None
        if data.get("legal_context"):
            ctx = data["legal_context"]
            legal_context = LegalContext(
                jurisdiction=ctx.get("jurisdiction"),
                legal_domain=ctx.get("legal_domain"),
                applicable_law=ctx.get("applicable_law"),
                precedents=ctx.get("precedents", []),
                exceptions=ctx.get("exceptions", []),
            )

        formula = cls(
            operator=DeonticOperator(data["operator"]),
            proposition=data.get("proposition", ""),
            agent=agent,
            beneficiary=beneficiary,
            conditions=data.get("conditions", []),
            temporal_conditions=temporal_conditions,
            legal_context=legal_context,
            confidence=float(data.get("confidence", 1.0)),
            source_text=data.get("source_text", ""),
            variables=data.get("variables", {}),
            quantifiers=data.get("quantifiers", []),
        )

        # Preserve IDs/timestamps when present.
        if data.get("formula_id"):
            formula.formula_id = data["formula_id"]
        if data.get("creation_timestamp"):
            formula.creation_timestamp = data["creation_timestamp"]
        return formula

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class DeonticRuleSet:
    """A collection of related deontic formulas forming a rule set."""

    name: str
    formulas: List[DeonticFormula]
    description: str = ""
    version: str = "1.0"
    source_document: Optional[str] = None
    legal_context: Optional[LegalContext] = None

    def __post_init__(self) -> None:
        self.rule_set_id = hashlib.md5(f"{self.name}:{self.version}".encode()).hexdigest()[:10]
        self.creation_timestamp = datetime.now().isoformat()

    def add_formula(self, formula: DeonticFormula) -> None:
        self.formulas.append(formula)

    def remove_formula(self, formula_id: str) -> bool:
        for i, formula in enumerate(self.formulas):
            if getattr(formula, "formula_id", None) == formula_id:
                del self.formulas[i]
                return True
        return False

    def find_formulas_by_agent(self, agent_identifier: str) -> List[DeonticFormula]:
        return [f for f in self.formulas if f.agent and f.agent.identifier == agent_identifier]

    def find_formulas_by_operator(self, operator: DeonticOperator) -> List[DeonticFormula]:
        return [f for f in self.formulas if f.operator == operator]

    def check_consistency(self) -> List[Tuple[DeonticFormula, DeonticFormula, str]]:
        conflicts: List[Tuple[DeonticFormula, DeonticFormula, str]] = []
        for i, formula1 in enumerate(self.formulas):
            for formula2 in self.formulas[i + 1 :]:
                if (
                    formula1.operator == DeonticOperator.OBLIGATION
                    and formula2.operator == DeonticOperator.PROHIBITION
                    and formula1.proposition == formula2.proposition
                    and formula1.agent == formula2.agent
                ):
                    conflicts.append((formula1, formula2, "Direct conflict: obligation vs prohibition"))
                elif (
                    formula1.operator == DeonticOperator.PERMISSION
                    and formula2.operator == DeonticOperator.PROHIBITION
                    and formula1.proposition == formula2.proposition
                    and formula1.agent == formula2.agent
                ):
                    conflicts.append((formula1, formula2, "Conflict: permission vs prohibition"))
        return conflicts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_set_id": self.rule_set_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "source_document": self.source_document,
            "legal_context": self.legal_context.__dict__ if self.legal_context else None,
            "formulas": [f.to_dict() for f in self.formulas],
            "creation_timestamp": self.creation_timestamp,
            "formula_count": len(self.formulas),
        }


__all__ = [
    "DeonticOperator",
    "DeonticFormula",
    "DeonticRuleSet",
    "LegalAgent",
    "LegalContext",
    "TemporalCondition",
    "TemporalOperator",
]
