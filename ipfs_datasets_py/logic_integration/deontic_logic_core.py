"""
Deontic Logic Core Module

This module provides core primitives for deontic first-order logic (deontic FOL),
which is essential for representing legal concepts such as obligations, permissions,
prohibitions, and rights in formal logical notation.

Deontic logic extends classical logic with modal operators that capture the 
normative aspects of legal reasoning.
"""

import logging
from enum import Enum
from typing import Dict, List, Optional, Union, Any, Tuple, Set
from dataclasses import dataclass, field
from beartype import beartype
import json
import hashlib
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DeonticOperator(Enum):
    """Deontic operators for representing normative concepts."""
    OBLIGATION = "O"         # O(φ) - it is obligatory that φ
    PERMISSION = "P"         # P(φ) - it is permitted that φ  
    PROHIBITION = "F"        # F(φ) - it is forbidden that φ
    SUPEREROGATION = "S"     # S(φ) - it is supererogatory that φ (above and beyond duty)
    RIGHT = "R"              # R(φ) - φ is a right
    LIBERTY = "L"            # L(φ) - φ is a liberty/privilege
    POWER = "POW"            # POW(φ) - power to bring about φ
    IMMUNITY = "IMM"         # IMM(φ) - immunity from φ


class LogicConnective(Enum):
    """Logical connectives for building complex formulas."""
    AND = "∧"
    OR = "∨"
    NOT = "¬"
    IMPLIES = "→"
    BICONDITIONAL = "↔"
    EXISTS = "∃"
    FORALL = "∀"


class TemporalOperator(Enum):
    """Temporal operators for time-dependent legal concepts."""
    ALWAYS = "□"             # Always/necessarily
    EVENTUALLY = "◊"         # Eventually/possibly
    NEXT = "X"               # Next time point
    UNTIL = "U"              # Until
    SINCE = "S"              # Since


@dataclass
class LegalAgent:
    """Represents a legal agent (person, organization, role)."""
    identifier: str
    name: str
    agent_type: str  # "person", "organization", "role", "government"
    properties: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        # Generate a hash for consistent identification
        self.hash = hashlib.md5(f"{self.identifier}:{self.name}:{self.agent_type}".encode()).hexdigest()[:8]


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
    legal_domain: Optional[str] = None  # "contract", "tort", "criminal", "constitutional"
    applicable_law: Optional[str] = None
    precedents: List[str] = field(default_factory=list)
    exceptions: List[str] = field(default_factory=list)


@dataclass
class DeonticFormula:
    """
    Represents a deontic first-order logic formula.
    
    This is the core data structure for representing legal concepts
    in formal logical notation.
    """
    operator: DeonticOperator
    proposition: str                     # The main proposition/action
    agent: Optional[LegalAgent] = None   # Who has the obligation/permission
    beneficiary: Optional[LegalAgent] = None  # Who benefits from the obligation/permission
    conditions: List[str] = field(default_factory=list)  # Conditions under which formula applies
    temporal_conditions: List[TemporalCondition] = field(default_factory=list)
    legal_context: Optional[LegalContext] = None
    confidence: float = 1.0              # Confidence in the extraction/interpretation
    source_text: str = ""                # Original text from which formula was extracted
    variables: Dict[str, str] = field(default_factory=dict)  # Variable bindings
    quantifiers: List[Tuple[str, str, str]] = field(default_factory=list)  # (quantifier, variable, domain)
    
    def __post_init__(self):
        """Initialize computed fields."""
        self.formula_id = self._generate_formula_id()
        self.creation_timestamp = datetime.now().isoformat()
    
    def _generate_formula_id(self) -> str:
        """Generate a unique identifier for this formula."""
        content = f"{self.operator.value}:{self.proposition}:{self.agent}:{self.conditions}"
        return hashlib.md5(content.encode()).hexdigest()[:12]
    
    def to_fol_string(self) -> str:
        """Convert to first-order logic string representation."""
        # Start with the deontic operator
        formula_parts = [self.operator.value]
        
        # Add agent if present
        if self.agent:
            formula_parts.append(f"[{self.agent.identifier}]")
        
        # Build the main proposition
        prop = self.proposition
        
        # Add quantifiers
        for quantifier, variable, domain in self.quantifiers:
            prop = f"{quantifier}{variable}:{domain} ({prop})"
        
        # Add conditions
        if self.conditions:
            conditions_str = " ∧ ".join(self.conditions)
            prop = f"({conditions_str}) → ({prop})"
        
        # Add temporal conditions
        for temp_cond in self.temporal_conditions:
            prop = f"{temp_cond.operator.value}({prop})"
        
        formula_parts.append(f"({prop})")
        
        return "".join(formula_parts)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
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
                    "duration": tc.duration
                }
                for tc in self.temporal_conditions
            ],
            "legal_context": self.legal_context.__dict__ if self.legal_context else None,
            "confidence": self.confidence,
            "source_text": self.source_text,
            "variables": self.variables,
            "quantifiers": self.quantifiers,
            "fol_string": self.to_fol_string(),
            "creation_timestamp": self.creation_timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DeonticFormula':
        """Create DeonticFormula from dictionary representation."""
        # Reconstruct agent
        agent = None
        if data.get("agent"):
            agent_data = data["agent"]
            agent = LegalAgent(
                identifier=agent_data["identifier"],
                name=agent_data["name"],
                agent_type=agent_data["agent_type"],
                properties=agent_data.get("properties", {})
            )
        
        # Reconstruct beneficiary
        beneficiary = None
        if data.get("beneficiary"):
            ben_data = data["beneficiary"]
            beneficiary = LegalAgent(
                identifier=ben_data["identifier"],
                name=ben_data["name"],
                agent_type=ben_data["agent_type"],
                properties=ben_data.get("properties", {})
            )
        
        # Reconstruct temporal conditions
        temporal_conditions = []
        for tc_data in data.get("temporal_conditions", []):
            temporal_conditions.append(TemporalCondition(
                operator=TemporalOperator(tc_data["operator"]),
                condition=tc_data["condition"],
                start_time=tc_data.get("start_time"),
                end_time=tc_data.get("end_time"),
                duration=tc_data.get("duration")
            ))
        
        # Reconstruct legal context
        legal_context = None
        if data.get("legal_context"):
            ctx_data = data["legal_context"]
            legal_context = LegalContext(
                jurisdiction=ctx_data.get("jurisdiction"),
                legal_domain=ctx_data.get("legal_domain"),
                applicable_law=ctx_data.get("applicable_law"),
                precedents=ctx_data.get("precedents", []),
                exceptions=ctx_data.get("exceptions", [])
            )
        
        return cls(
            operator=DeonticOperator(data["operator"]),
            proposition=data["proposition"],
            agent=agent,
            beneficiary=beneficiary,
            conditions=data.get("conditions", []),
            temporal_conditions=temporal_conditions,
            legal_context=legal_context,
            confidence=data.get("confidence", 1.0),
            source_text=data.get("source_text", ""),
            variables=data.get("variables", {}),
            quantifiers=data.get("quantifiers", [])
        )


@dataclass
class DeonticRuleSet:
    """A collection of related deontic formulas forming a rule set."""
    name: str
    formulas: List[DeonticFormula]
    description: str = ""
    version: str = "1.0"
    source_document: Optional[str] = None
    legal_context: Optional[LegalContext] = None
    
    def __post_init__(self):
        self.rule_set_id = hashlib.md5(f"{self.name}:{self.version}".encode()).hexdigest()[:10]
        self.creation_timestamp = datetime.now().isoformat()
    
    def add_formula(self, formula: DeonticFormula) -> None:
        """Add a formula to this rule set."""
        self.formulas.append(formula)
    
    def remove_formula(self, formula_id: str) -> bool:
        """Remove a formula by ID."""
        for i, formula in enumerate(self.formulas):
            if formula.formula_id == formula_id:
                del self.formulas[i]
                return True
        return False
    
    def find_formulas_by_agent(self, agent_identifier: str) -> List[DeonticFormula]:
        """Find all formulas that apply to a specific agent."""
        return [f for f in self.formulas if f.agent and f.agent.identifier == agent_identifier]
    
    def find_formulas_by_operator(self, operator: DeonticOperator) -> List[DeonticFormula]:
        """Find all formulas with a specific deontic operator."""
        return [f for f in self.formulas if f.operator == operator]
    
    def check_consistency(self) -> List[Tuple[DeonticFormula, DeonticFormula, str]]:
        """
        Check for logical inconsistencies between formulas.
        Returns list of (formula1, formula2, conflict_description) tuples.
        """
        conflicts = []
        
        for i, formula1 in enumerate(self.formulas):
            for j, formula2 in enumerate(self.formulas[i+1:], i+1):
                # Check for direct conflicts (obligation vs prohibition)
                if (formula1.operator == DeonticOperator.OBLIGATION and 
                    formula2.operator == DeonticOperator.PROHIBITION and
                    formula1.proposition == formula2.proposition and
                    formula1.agent == formula2.agent):
                    conflicts.append((formula1, formula2, "Direct conflict: obligation vs prohibition"))
                
                # Check for permission vs prohibition conflicts
                elif (formula1.operator == DeonticOperator.PERMISSION and 
                      formula2.operator == DeonticOperator.PROHIBITION and
                      formula1.proposition == formula2.proposition and
                      formula1.agent == formula2.agent):
                    conflicts.append((formula1, formula2, "Conflict: permission vs prohibition"))
        
        return conflicts
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert rule set to dictionary representation."""
        return {
            "rule_set_id": self.rule_set_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "source_document": self.source_document,
            "legal_context": self.legal_context.__dict__ if self.legal_context else None,
            "formulas": [f.to_dict() for f in self.formulas],
            "creation_timestamp": self.creation_timestamp,
            "formula_count": len(self.formulas)
        }


class DeonticLogicValidator:
    """Validator for deontic logic formulas and rule sets."""
    
    @staticmethod
    def validate_formula(formula: DeonticFormula) -> List[str]:
        """
        Validate a deontic formula for logical consistency and completeness.
        Returns list of validation errors.
        """
        errors = []
        
        # Check required fields
        if not formula.proposition:
            errors.append("Formula must have a proposition")
        
        if not isinstance(formula.operator, DeonticOperator):
            errors.append("Formula must have a valid deontic operator")
        
        # Check confidence range
        if not 0.0 <= formula.confidence <= 1.0:
            errors.append("Confidence must be between 0.0 and 1.0")
        
        # Check temporal conditions
        for tc in formula.temporal_conditions:
            if tc.start_time and tc.end_time:
                try:
                    start = datetime.fromisoformat(tc.start_time)
                    end = datetime.fromisoformat(tc.end_time)
                    if start >= end:
                        errors.append("Start time must be before end time in temporal conditions")
                except ValueError:
                    errors.append("Invalid datetime format in temporal conditions")
        
        # Check quantifier structure
        for quantifier, variable, domain in formula.quantifiers:
            if quantifier not in ["∀", "∃"]:
                errors.append(f"Invalid quantifier: {quantifier}")
            if not variable:
                errors.append("Quantifier variable cannot be empty")
            if not domain:
                errors.append("Quantifier domain cannot be empty")
        
        return errors
    
    @staticmethod
    def validate_rule_set(rule_set: DeonticRuleSet) -> List[str]:
        """
        Validate a deontic rule set for consistency and completeness.
        Returns list of validation errors.
        """
        errors = []
        
        # Check basic fields
        if not rule_set.name:
            errors.append("Rule set must have a name")
        
        if not rule_set.formulas:
            errors.append("Rule set must contain at least one formula")
        
        # Validate each formula
        for i, formula in enumerate(rule_set.formulas):
            formula_errors = DeonticLogicValidator.validate_formula(formula)
            for error in formula_errors:
                errors.append(f"Formula {i}: {error}")
        
        # Check for inconsistencies
        conflicts = rule_set.check_consistency()
        for formula1, formula2, conflict_desc in conflicts:
            errors.append(f"Consistency conflict: {conflict_desc} between formulas {formula1.formula_id} and {formula2.formula_id}")
        
        return errors


def create_obligation(proposition: str, agent: LegalAgent, 
                     conditions: List[str] = None, **kwargs) -> DeonticFormula:
    """Helper function to create an obligation formula."""
    return DeonticFormula(
        operator=DeonticOperator.OBLIGATION,
        proposition=proposition,
        agent=agent,
        conditions=conditions or [],
        **kwargs
    )


def create_permission(proposition: str, agent: LegalAgent, 
                     conditions: List[str] = None, **kwargs) -> DeonticFormula:
    """Helper function to create a permission formula."""
    return DeonticFormula(
        operator=DeonticOperator.PERMISSION,
        proposition=proposition,
        agent=agent,
        conditions=conditions or [],
        **kwargs
    )


def create_prohibition(proposition: str, agent: LegalAgent, 
                      conditions: List[str] = None, **kwargs) -> DeonticFormula:
    """Helper function to create a prohibition formula."""
    return DeonticFormula(
        operator=DeonticOperator.PROHIBITION,
        proposition=proposition,
        agent=agent,
        conditions=conditions or [],
        **kwargs
    )


# Example usage and demonstrations
def demonstrate_deontic_logic():
    """Demonstrate the deontic logic system with legal examples."""
    
    # Create legal agents
    contractor = LegalAgent("contractor_001", "ABC Construction LLC", "organization")
    client = LegalAgent("client_001", "City of Springfield", "government")
    
    # Create legal context
    context = LegalContext(
        jurisdiction="State of Illinois",
        legal_domain="contract",
        applicable_law="Illinois Construction Code"
    )
    
    # Create deontic formulas
    
    # Obligation: Contractor must complete work by deadline
    obligation1 = create_obligation(
        proposition="complete_construction_work_by_deadline",
        agent=contractor,
        conditions=["contract_is_valid", "no_force_majeure_events"],
        legal_context=context,
        source_text="The Contractor shall complete all work by December 31, 2024."
    )
    
    # Permission: Client may inspect work at any time
    permission1 = create_permission(
        proposition="inspect_construction_work",
        agent=client,
        conditions=["provide_24_hour_notice"],
        legal_context=context,
        source_text="The Client may inspect the work at any time with 24 hours notice."
    )
    
    # Prohibition: Contractor may not use substandard materials
    prohibition1 = create_prohibition(
        proposition="use_substandard_materials",
        agent=contractor,
        legal_context=context,
        source_text="The Contractor shall not use any materials that do not meet specifications."
    )
    
    # Create rule set
    construction_contract = DeonticRuleSet(
        name="Springfield Construction Contract",
        formulas=[obligation1, permission1, prohibition1],
        description="Legal rules for the Springfield civic center construction project",
        source_document="SpringfieldContract_2024.pdf",
        legal_context=context
    )
    
    # Validate the rule set
    validator = DeonticLogicValidator()
    errors = validator.validate_rule_set(construction_contract)
    
    print("=== Deontic Logic Demonstration ===")
    print(f"Rule Set: {construction_contract.name}")
    print(f"Number of formulas: {len(construction_contract.formulas)}")
    print()
    
    for i, formula in enumerate(construction_contract.formulas):
        print(f"Formula {i+1}:")
        print(f"  Type: {formula.operator.value}")
        print(f"  Agent: {formula.agent.name if formula.agent else 'None'}")
        print(f"  Proposition: {formula.proposition}")
        print(f"  FOL String: {formula.to_fol_string()}")
        print(f"  Confidence: {formula.confidence}")
        print()
    
    print("Validation Results:")
    if errors:
        for error in errors:
            print(f"  ERROR: {error}")
    else:
        print("  All formulas valid!")
    
    print("\nConsistency Check:")
    conflicts = construction_contract.check_consistency()
    if conflicts:
        for f1, f2, desc in conflicts:
            print(f"  CONFLICT: {desc}")
    else:
        print("  No conflicts detected!")
    
    return construction_contract


if __name__ == "__main__":
    demonstrate_deontic_logic()