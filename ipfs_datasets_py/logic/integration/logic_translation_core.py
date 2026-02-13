"""
Logic Translation Core Module

This module provides the core infrastructure for translating deontic logic formulas
to multiple theorem prover formats (Lean, Coq, SMT-LIB, TPTP, etc.).
"""

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional, Union, Any, Tuple
from dataclasses import dataclass, field
import json
import re

from .deontic_logic_core import DeonticFormula, DeonticOperator, DeonticRuleSet
from ..security.rate_limiting import RateLimiter
from ..security.input_validation import InputValidator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LogicTranslationTarget(Enum):
    """Supported theorem prover and logic system targets."""
    LEAN = "lean"
    COQ = "coq"
    ISABELLE = "isabelle"
    SMT_LIB = "smt-lib"
    TPTP = "tptp"
    Z3 = "z3"
    VAMPIRE = "vampire"
    E_PROVER = "eprover"
    AGDA = "agda"
    HOL = "hol"
    PVS = "pvs"


@dataclass
class TranslationResult:
    """Result of translating a formula to a target format."""
    target: LogicTranslationTarget
    translated_formula: str
    success: bool
    confidence: float = 1.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)  # Required imports/dependencies
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "target": self.target.value,
            "translated_formula": self.translated_formula,
            "success": self.success,
            "confidence": self.confidence,
            "errors": self.errors,
            "warnings": self.warnings,
            "metadata": self.metadata,
            "dependencies": self.dependencies
        }


@dataclass
class AbstractLogicFormula:
    """
    Platform-independent representation of logic formulas for translation.
    This serves as an intermediate format between deontic formulas and target formats.
    """
    formula_type: str  # "deontic", "first_order", "modal", "temporal"
    operators: List[str]
    variables: List[Tuple[str, str]]  # (variable_name, type)
    quantifiers: List[Tuple[str, str, str]]  # (quantifier, variable, domain)
    propositions: List[str]
    logical_structure: Dict[str, Any]
    source_formula: Optional[DeonticFormula] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "formula_type": self.formula_type,
            "operators": self.operators,
            "variables": self.variables,
            "quantifiers": self.quantifiers,
            "propositions": self.propositions,
            "logical_structure": self.logical_structure,
            "source_formula_id": self.source_formula.formula_id if self.source_formula else None
        }


class LogicTranslator(ABC):
    """
    Abstract base class for logic translators.
    Each target system should implement this interface.
    """
    
    def __init__(self, target: LogicTranslationTarget,
                 enable_rate_limiting: bool = True,
                 enable_validation: bool = True):
        self.target = target
        self.translation_cache: Dict[str, TranslationResult] = {}
        
        # Security features
        self.enable_rate_limiting = enable_rate_limiting
        self.enable_validation = enable_validation
        if enable_rate_limiting:
            self.rate_limiter = RateLimiter(calls=150, period=60)
        if enable_validation:
            self.validator = InputValidator()
        
    @abstractmethod
    def translate_deontic_formula(self, formula: DeonticFormula) -> TranslationResult:
        """Translate a deontic formula to the target format."""
        pass
    
    @abstractmethod
    def translate_rule_set(self, rule_set: DeonticRuleSet) -> TranslationResult:
        """Translate a complete rule set to the target format."""
        pass
    
    @abstractmethod
    def generate_theory_file(self, formulas: List[DeonticFormula], 
                           theory_name: str = "LegalTheory") -> str:
        """Generate a complete theory/module file for the target system."""
        pass
    
    @abstractmethod
    def get_dependencies(self) -> List[str]:
        """Get list of required imports/dependencies for the target system."""
        pass
    
    @abstractmethod
    def validate_translation(self, original: DeonticFormula, 
                           translated: str) -> Tuple[bool, List[str]]:
        """Validate that the translation preserves the original semantics."""
        pass
    
    def clear_cache(self):
        """Clear the translation cache."""
        self.translation_cache.clear()
    
    def _normalize_identifier(self, identifier: str) -> str:
        """Normalize identifiers for the target system."""
        # Remove spaces and special characters, replace with underscores
        normalized = re.sub(r'[^a-zA-Z0-9_]', '_', identifier)
        # Ensure it starts with a letter
        if normalized and normalized[0].isdigit():
            normalized = 'id_' + normalized
        return normalized or 'unnamed'


class LeanTranslator(LogicTranslator):
    """Translator for Lean theorem prover (Lean 4)."""
    
    def __init__(self):
        super().__init__(LogicTranslationTarget.LEAN)
        
    def translate_deontic_formula(self, formula: DeonticFormula) -> TranslationResult:
        """Translate deontic formula to Lean 4 syntax."""
        try:
            # Check cache first
            cache_key = formula.formula_id
            if cache_key in self.translation_cache:
                return self.translation_cache[cache_key]
            
            dependencies = self.get_dependencies()
            errors = []
            warnings = []
            
            # Map deontic operators to Lean definitions
            operator_map = {
                DeonticOperator.OBLIGATION: "Obligatory",
                DeonticOperator.PERMISSION: "Permitted", 
                DeonticOperator.PROHIBITION: "Forbidden",
                DeonticOperator.RIGHT: "Right",
                DeonticOperator.LIBERTY: "Liberty"
            }
            
            lean_operator = operator_map.get(formula.operator, "Obligatory")
            
            # Generate Lean formula
            proposition = self._normalize_identifier(formula.proposition)
            
            # Build the main formula.
            # NOTE: Keep the smoke-test Lean output compatible with core Lean execution
            # (no custom structures for agent/conditions).
            lean_formula = f"{lean_operator} {proposition}"
            
            # Add quantifiers if present
            for quantifier, variable, domain in formula.quantifiers:
                lean_quantifier = "∀" if quantifier == "∀" else "∃"
                var_name = self._normalize_identifier(variable)
                domain_name = self._normalize_identifier(domain)
                lean_formula = f"{lean_quantifier} ({var_name} : {domain_name}), {lean_formula}"
            
            result = TranslationResult(
                target=self.target,
                translated_formula=lean_formula,
                success=True,
                confidence=0.85,
                dependencies=dependencies,
                metadata={
                    "syntax_version": "lean4",
                    "deontic_operator": formula.operator.value,
                    "has_agent": formula.agent is not None,
                    "has_conditions": len(formula.conditions) > 0,
                    "proposition_id": proposition,
                }
            )
            
            # Cache the result
            self.translation_cache[cache_key] = result
            return result
            
        except Exception as e:
            logger.error(f"Error translating to Lean: {e}")
            return TranslationResult(
                target=self.target,
                translated_formula="",
                success=False,
                errors=[str(e)]
            )
    
    def translate_rule_set(self, rule_set: DeonticRuleSet) -> TranslationResult:
        """Translate a rule set to Lean theory."""
        try:
            theory_content = self.generate_theory_file(rule_set.formulas, rule_set.name)
            
            return TranslationResult(
                target=self.target,
                translated_formula=theory_content,
                success=True,
                confidence=0.8,
                dependencies=self.get_dependencies(),
                metadata={
                    "theory_name": rule_set.name,
                    "formula_count": len(rule_set.formulas),
                    "type": "theory_file"
                }
            )
        except Exception as e:
            return TranslationResult(
                target=self.target,
                translated_formula="",
                success=False,
                errors=[str(e)]
            )
    
    def generate_theory_file(self, formulas: List[DeonticFormula], 
                           theory_name: str = "LegalTheory") -> str:
        """Generate a complete Lean theory file."""
        theory_name_normalized = self._normalize_identifier(theory_name)
        
        lines = [
            f"-- Legal Theory: {theory_name}",
            f"-- Generated deontic logic formulas",
            "",
            "import Mathlib.Logic.Basic",
            "import Mathlib.Data.Set.Basic",
            "",
            f"namespace {theory_name_normalized}",
            "",
            "-- Deontic logic operators",
            "def Obligatory (P : Prop) : Prop := P",
            "def Permitted (P : Prop) : Prop := ¬¬P", 
            "def Forbidden (P : Prop) : Prop := ¬P",
            "def Right (P : Prop) : Prop := P",
            "def Liberty (P : Prop) : Prop := P ∨ ¬P",
            "",
            "-- Agent type",
            "structure Agent where",
            "  id : String",
            "  name : String",
            "",
            "-- Proposition with agent and conditions",
            "structure DeonticProp where",
            "  proposition : Prop",
            "  agent : Option Agent := none",
            "  conditions : List Prop := []",
            "",
        ]
        
        # Add individual formulas
        lines.append("-- Extracted legal formulas")
        for i, formula in enumerate(formulas):
            result = self.translate_deontic_formula(formula)
            if result.success:
                formula_name = f"formula_{i+1}"
                lines.append(f"def {formula_name} : Prop := {result.translated_formula}")
                lines.append(f"-- Source: {formula.source_text[:60]}...")
                lines.append("")
        
        # Add consistency axioms
        lines.extend([
            "-- Consistency axioms",
            "axiom no_obligation_and_prohibition (P : Prop) : ¬(Obligatory P ∧ Forbidden P)",
            "axiom permission_consistency (P : Prop) : Permitted P → ¬Forbidden P",
            "",
            f"end {theory_name_normalized}"
        ])
        
        return "\n".join(lines)
    
    def get_dependencies(self) -> List[str]:
        """Get required Lean imports."""
        return [
            "Mathlib.Logic.Basic",
            "Mathlib.Data.Set.Basic",
            "Mathlib.Logic.Relation"
        ]
    
    def validate_translation(self, original: DeonticFormula, 
                           translated: str) -> Tuple[bool, List[str]]:
        """Validate Lean translation."""
        errors = []
        
        # Basic syntax checks
        if not translated.strip():
            errors.append("Empty translation")
        
        # Check for balanced parentheses
        if translated.count('(') != translated.count(')'):
            errors.append("Unbalanced parentheses")
        
        # Check for valid Lean identifiers
        if re.search(r'[^a-zA-Z0-9_∀∃∧∨¬→↔\(\)\s:]', translated):
            errors.append("Invalid characters for Lean syntax")
        
        return len(errors) == 0, errors


class CoqTranslator(LogicTranslator):
    """Translator for Coq proof assistant."""
    
    def __init__(self):
        super().__init__(LogicTranslationTarget.COQ)
    
    def translate_deontic_formula(self, formula: DeonticFormula) -> TranslationResult:
        """Translate deontic formula to Coq syntax."""
        try:
            # Check cache first
            cache_key = formula.formula_id
            if cache_key in self.translation_cache:
                return self.translation_cache[cache_key]
            
            # Map deontic operators to Coq definitions
            operator_map = {
                DeonticOperator.OBLIGATION: "Obligatory",
                DeonticOperator.PERMISSION: "Permitted",
                DeonticOperator.PROHIBITION: "Forbidden", 
                DeonticOperator.RIGHT: "Right",
                DeonticOperator.LIBERTY: "Liberty"
            }
            
            coq_operator = operator_map.get(formula.operator, "Obligatory")
            proposition = self._normalize_identifier(formula.proposition)
            
            # Build Coq formula
            coq_formula = f"{coq_operator} {proposition}"
            
            # Add quantifiers
            for quantifier, variable, domain in formula.quantifiers:
                coq_quantifier = "forall" if quantifier == "∀" else "exists"
                var_name = self._normalize_identifier(variable)
                domain_name = self._normalize_identifier(domain)
                coq_formula = f"{coq_quantifier} ({var_name} : {domain_name}), {coq_formula}"
            
            # Handle conditions
            if formula.conditions:
                condition_props = [self._normalize_identifier(cond) for cond in formula.conditions]
                conditions_conjunction = " /\\ ".join(condition_props)
                coq_formula = f"({conditions_conjunction}) -> ({coq_formula})"
            
            result = TranslationResult(
                target=self.target,
                translated_formula=coq_formula,
                success=True,
                confidence=0.85,
                dependencies=self.get_dependencies(),
                metadata={
                    "syntax_version": "coq8.15",
                    "deontic_operator": formula.operator.value
                }
            )
            
            self.translation_cache[cache_key] = result
            return result
            
        except Exception as e:
            logger.error(f"Error translating to Coq: {e}")
            return TranslationResult(
                target=self.target,
                translated_formula="",
                success=False,
                errors=[str(e)]
            )
    
    def translate_rule_set(self, rule_set: DeonticRuleSet) -> TranslationResult:
        """Translate rule set to Coq module."""
        try:
            module_content = self.generate_theory_file(rule_set.formulas, rule_set.name)
            
            return TranslationResult(
                target=self.target,
                translated_formula=module_content,
                success=True,
                confidence=0.8,
                dependencies=self.get_dependencies()
            )
        except Exception as e:
            return TranslationResult(
                target=self.target,
                translated_formula="",
                success=False,
                errors=[str(e)]
            )
    
    def generate_theory_file(self, formulas: List[DeonticFormula], 
                           theory_name: str = "LegalTheory") -> str:
        """Generate Coq module."""
        module_name = self._normalize_identifier(theory_name)
        
        lines = [
            f"(* Legal Theory: {theory_name} *)",
            f"(* Generated deontic logic formulas *)",
            "",
            "Require Import Coq.Logic.Classical.",
            "Require Import Coq.Sets.Ensembles.",
            "",
            f"Module {module_name}.",
            "",
            "(* Deontic logic operators *)",
            "Definition Obligatory (P : Prop) : Prop := P.",
            "Definition Permitted (P : Prop) : Prop := ~ ~ P.",
            "Definition Forbidden (P : Prop) : Prop := ~ P.",
            "Definition Right (P : Prop) : Prop := P.",
            "Definition Liberty (P : Prop) : Prop := P \\/ ~ P.",
            "",
            "(* Agent type *)",
            "Record Agent : Type := mkAgent {",
            "  agent_id : string;",
            "  agent_name : string",
            "}.",
            "",
        ]
        
        # Add formulas
        lines.append("(* Legal formulas *)")
        for i, formula in enumerate(formulas):
            result = self.translate_deontic_formula(formula)
            if result.success:
                formula_name = f"formula_{i+1}"
                lines.append(f"Definition {formula_name} : Prop := {result.translated_formula}.")
                lines.append(f"(* Source: {formula.source_text[:60]}... *)")
                lines.append("")
        
        # Add axioms
        lines.extend([
            "(* Consistency axioms *)",
            "Axiom no_obligation_and_prohibition :",
            "  forall P : Prop, ~ (Obligatory P /\\ Forbidden P).",
            "",
            "Axiom permission_consistency :",
            "  forall P : Prop, Permitted P -> ~ Forbidden P.",
            "",
            f"End {module_name}."
        ])
        
        return "\n".join(lines)
    
    def get_dependencies(self) -> List[str]:
        """Get required Coq imports."""
        return [
            "Coq.Logic.Classical",
            "Coq.Sets.Ensembles",
            "Coq.Logic.Classical_Pred_Type"
        ]
    
    def validate_translation(self, original: DeonticFormula, 
                           translated: str) -> Tuple[bool, List[str]]:
        """Validate Coq translation."""
        errors = []
        
        if not translated.strip():
            errors.append("Empty translation")
        
        # Check for balanced parentheses
        if translated.count('(') != translated.count(')'):
            errors.append("Unbalanced parentheses")
        
        return len(errors) == 0, errors


class SMTTranslator(LogicTranslator):
    """Translator for SMT-LIB format (SMT solvers like Z3, CVC4)."""
    
    def __init__(self):
        super().__init__(LogicTranslationTarget.SMT_LIB)
    
    def translate_deontic_formula(self, formula: DeonticFormula) -> TranslationResult:
        """Translate deontic formula to SMT-LIB format."""
        try:
            cache_key = formula.formula_id
            if cache_key in self.translation_cache:
                return self.translation_cache[cache_key]
            
            proposition = self._normalize_identifier(formula.proposition)
            
            # In SMT-LIB, we model deontic operators as predicates
            operator_predicate = {
                DeonticOperator.OBLIGATION: "obligatory",
                DeonticOperator.PERMISSION: "permitted",
                DeonticOperator.PROHIBITION: "forbidden",
                DeonticOperator.RIGHT: "right",
                DeonticOperator.LIBERTY: "liberty"
            }
            
            pred = operator_predicate.get(formula.operator, "obligatory")
            
            # Build SMT formula
            if formula.agent:
                agent_id = self._normalize_identifier(formula.agent.identifier)
                smt_formula = f"({pred} {agent_id} {proposition})"
            else:
                smt_formula = f"({pred} {proposition})"
            
            # Add conditions as implications
            if formula.conditions:
                condition_props = [self._normalize_identifier(cond) for cond in formula.conditions]
                conditions_conjunction = f"(and {' '.join(condition_props)})"
                smt_formula = f"(=> {conditions_conjunction} {smt_formula})"
            
            # Add quantifiers
            for quantifier, variable, domain in formula.quantifiers:
                var_name = self._normalize_identifier(variable)
                domain_name = self._normalize_identifier(domain)
                smt_quantifier = "forall" if quantifier == "∀" else "exists"
                smt_formula = f"({smt_quantifier} (({var_name} {domain_name})) {smt_formula})"
            
            result = TranslationResult(
                target=self.target,
                translated_formula=smt_formula,
                success=True,
                confidence=0.9,
                dependencies=self.get_dependencies(),
                metadata={
                    "logic": "QF_UF",  # Quantifier-free uninterpreted functions
                    "deontic_operator": formula.operator.value
                }
            )
            
            self.translation_cache[cache_key] = result
            return result
            
        except Exception as e:
            logger.error(f"Error translating to SMT-LIB: {e}")
            return TranslationResult(
                target=self.target,
                translated_formula="",
                success=False,
                errors=[str(e)]
            )
    
    def translate_rule_set(self, rule_set: DeonticRuleSet) -> TranslationResult:
        """Translate rule set to SMT-LIB script."""
        try:
            script_content = self.generate_theory_file(rule_set.formulas, rule_set.name)
            
            return TranslationResult(
                target=self.target,
                translated_formula=script_content,
                success=True,
                confidence=0.85,
                dependencies=self.get_dependencies()
            )
        except Exception as e:
            return TranslationResult(
                target=self.target,
                translated_formula="",
                success=False,
                errors=[str(e)]
            )
    
    def generate_theory_file(self, formulas: List[DeonticFormula], 
                           theory_name: str = "LegalTheory") -> str:
        """Generate SMT-LIB script."""
        lines = [
            f"; Legal Theory: {theory_name}",
            f"; Generated deontic logic formulas",
            "",
            "(set-logic QF_UF)",
            "(set-info :source |Generated from deontic logic formulas|)",
            "",
            "; Agent sort",
            "(declare-sort Agent 0)",
            "",
            "; Deontic predicates",
            "(declare-fun obligatory (Agent Bool) Bool)",
            "(declare-fun permitted (Agent Bool) Bool)", 
            "(declare-fun forbidden (Agent Bool) Bool)",
            "(declare-fun right (Agent Bool) Bool)",
            "(declare-fun liberty (Agent Bool) Bool)",
            "",
            "; Proposition predicates",
        ]
        
        # Collect all propositions and agents
        propositions = set()
        agents = set()
        
        for formula in formulas:
            propositions.add(formula.proposition)
            if formula.agent:
                agents.add(formula.agent.identifier)
        
        # Declare proposition predicates
        for prop in propositions:
            prop_norm = self._normalize_identifier(prop)
            lines.append(f"(declare-fun {prop_norm} () Bool)")
        
        # Declare agent constants
        for agent in agents:
            agent_norm = self._normalize_identifier(agent)
            lines.append(f"(declare-const {agent_norm} Agent)")
        
        lines.append("")
        lines.append("; Legal formulas")
        
        # Add formulas as assertions
        for i, formula in enumerate(formulas):
            result = self.translate_deontic_formula(formula)
            if result.success:
                lines.append(f"(assert {result.translated_formula})")
                lines.append(f"; Source: {formula.source_text[:60]}...")
        
        lines.extend([
            "",
            "; Consistency constraints",
            "(assert (forall ((a Agent) (p Bool))",
            "  (not (and (obligatory a p) (forbidden a p)))))",
            "",
            "(assert (forall ((a Agent) (p Bool))",
            "  (=> (permitted a p) (not (forbidden a p)))))",
            "",
            "(check-sat)",
            "(get-model)"
        ])
        
        return "\n".join(lines)
    
    def get_dependencies(self) -> List[str]:
        """Get SMT solver requirements."""
        return ["z3", "cvc4", "smt-lib2"]
    
    def validate_translation(self, original: DeonticFormula, 
                           translated: str) -> Tuple[bool, List[str]]:
        """Validate SMT-LIB translation."""
        errors = []
        
        if not translated.strip():
            errors.append("Empty translation")
        
        # Check for balanced parentheses
        if translated.count('(') != translated.count(')'):
            errors.append("Unbalanced parentheses in SMT-LIB syntax")
        
        # Check for valid SMT-LIB syntax
        if not translated.startswith('(') or not translated.endswith(')'):
            errors.append("Invalid SMT-LIB syntax - must be S-expression")
        
        return len(errors) == 0, errors


def demonstrate_logic_translation():
    """Demonstrate the logic translation system."""
    from .deontic_logic_core import create_obligation, LegalAgent, LegalContext
    
    # Create test data
    contractor = LegalAgent("contractor_001", "ABC Construction", "organization")
    context = LegalContext(jurisdiction="Illinois", legal_domain="contract")
    
    obligation = create_obligation(
        proposition="complete_work_by_deadline",
        agent=contractor,
        conditions=["contract_valid", "no_force_majeure"],
        legal_context=context,
        source_text="The contractor shall complete all work by the deadline."
    )
    
    # Test translators
    translators = [
        LeanTranslator(),
        CoqTranslator(), 
        SMTTranslator()
    ]
    
    print("=== Logic Translation Demonstration ===\n")
    print(f"Original Formula: {obligation.to_fol_string()}")
    print(f"Source: {obligation.source_text}")
    print()
    
    for translator in translators:
        print(f"=== {translator.target.value.upper()} Translation ===")
        result = translator.translate_deontic_formula(obligation)
        
        print(f"Success: {result.success}")
        print(f"Confidence: {result.confidence}")
        
        if result.success:
            print(f"Translation:\n{result.translated_formula}")
            print(f"Dependencies: {result.dependencies}")
        else:
            print(f"Errors: {result.errors}")
        
        print()


if __name__ == "__main__":
    demonstrate_logic_translation()