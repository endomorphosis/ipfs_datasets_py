"""
TPTP Format Utilities for External Provers (Phase 6 Week 2).

This module provides utilities for converting CEC formulas to TPTP
(Thousands of Problems for Theorem Provers) format, used by Vampire,
E, and other first-order theorem provers.

TPTP Format:
    - Standard format for first-order logic problems
    - Used by automated theorem provers worldwide
    - Includes formulas, axioms, and problem metadata

Functions:
    formula_to_tptp: Convert CEC formula to TPTP format
    create_tptp_problem: Create complete TPTP problem file

Usage:
    >>> from ipfs_datasets_py.logic.CEC.provers.tptp_utils import formula_to_tptp
    >>> tptp_str = formula_to_tptp(formula, "conjecture")
"""

from typing import List, Optional, Dict
from dataclasses import dataclass, field
from ..native.dcec_core import (
    Formula,
    AtomicFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    ConnectiveFormula,
    QuantifiedFormula,
    DeonticOperator,
    CognitiveOperator,
    TemporalOperator,
    LogicalConnective,
)


def formula_to_tptp(
    formula: Formula,
    role: str = "conjecture",
    name: str = "formula"
) -> str:
    """Convert CEC formula to TPTP format.
    
    Args:
        formula: CEC Formula to convert
        role: TPTP role (axiom, conjecture, hypothesis, etc.)
        name: Formula name
        
    Returns:
        TPTP format string
        
    Example:
        >>> tptp = formula_to_tptp(formula, "axiom", "ax1")
        >>> print(tptp)
        fof(ax1, axiom, obligated(action(agent))).
    """
    tptp_formula = _translate_formula(formula)
    return f"fof({name}, {role}, {tptp_formula})."


def _translate_formula(formula: Formula) -> str:
    """Translate formula to TPTP syntax.
    
    Args:
        formula: Formula to translate
        
    Returns:
        TPTP formula string
    """
    if isinstance(formula, AtomicFormula):
        return _translate_atomic(formula)
    
    elif isinstance(formula, DeonticFormula):
        return _translate_deontic(formula)
    
    elif isinstance(formula, CognitiveFormula):
        return _translate_cognitive(formula)
    
    elif isinstance(formula, TemporalFormula):
        return _translate_temporal(formula)
    
    elif isinstance(formula, ConnectiveFormula):
        return _translate_connective(formula)
    
    elif isinstance(formula, QuantifiedFormula):
        return _translate_quantified(formula)
    
    else:
        raise NotImplementedError(f"Unsupported formula type: {type(formula)}")


def _translate_atomic(formula: AtomicFormula) -> str:
    """Translate atomic formula to TPTP."""
    pred_name = formula.predicate.name
    args = []
    
    for term in formula.arguments:
        # Simple variable terms for now
        args.append(term.variable.name if hasattr(term, 'variable') else str(term))
    
    if args:
        return f"{pred_name}({', '.join(args)})"
    else:
        return pred_name


def _translate_deontic(formula: DeonticFormula) -> str:
    """Translate deontic formula to TPTP."""
    inner = _translate_formula(formula.formula)
    
    if formula.operator == DeonticOperator.OBLIGATION:
        return f"obligated({inner})"
    elif formula.operator == DeonticOperator.PERMISSION:
        return f"permitted({inner})"
    elif formula.operator == DeonticOperator.PROHIBITION:
        return f"forbidden({inner})"
    else:
        raise NotImplementedError(f"Unsupported deontic operator: {formula.operator}")


def _translate_cognitive(formula: CognitiveFormula) -> str:
    """Translate cognitive formula to TPTP."""
    inner = _translate_formula(formula.formula)
    
    if formula.operator == CognitiveOperator.BELIEF:
        return f"believes({inner})"
    elif formula.operator == CognitiveOperator.KNOWLEDGE:
        return f"knows({inner})"
    elif formula.operator == CognitiveOperator.INTENTION:
        return f"intends({inner})"
    elif formula.operator == CognitiveOperator.DESIRE:
        return f"desires({inner})"
    elif formula.operator == CognitiveOperator.GOAL:
        return f"has_goal({inner})"
    else:
        raise NotImplementedError(f"Unsupported cognitive operator: {formula.operator}")


def _translate_temporal(formula: TemporalFormula) -> str:
    """Translate temporal formula to TPTP."""
    inner = _translate_formula(formula.formula)
    
    if formula.operator == TemporalOperator.ALWAYS:
        return f"always({inner})"
    elif formula.operator == TemporalOperator.EVENTUALLY:
        return f"eventually({inner})"
    elif formula.operator == TemporalOperator.NEXT:
        return f"next({inner})"
    else:
        raise NotImplementedError(f"Unsupported temporal operator: {formula.operator}")


def _translate_connective(formula: ConnectiveFormula) -> str:
    """Translate connective formula to TPTP."""
    translated = [_translate_formula(f) for f in formula.formulas]
    
    if formula.connective == LogicalConnective.AND:
        return f"({' & '.join(translated)})"
    elif formula.connective == LogicalConnective.OR:
        return f"({' | '.join(translated)})"
    elif formula.connective == LogicalConnective.NOT:
        return f"~({translated[0]})"
    elif formula.connective == LogicalConnective.IMPLIES:
        return f"({translated[0]} => {translated[1]})"
    elif formula.connective == LogicalConnective.BICONDITIONAL:
        return f"({translated[0]} <=> {translated[1]})"
    else:
        raise NotImplementedError(f"Unsupported connective: {formula.connective}")


def _translate_quantified(formula: QuantifiedFormula) -> str:
    """Translate quantified formula to TPTP."""
    var_name = formula.variable.name.upper()  # TPTP variables are uppercase
    body = _translate_formula(formula.formula)
    
    if formula.quantifier == LogicalConnective.FORALL:
        return f"(! [{var_name}] : {body})"
    elif formula.quantifier == LogicalConnective.EXISTS:
        return f"(? [{var_name}] : {body})"
    else:
        raise NotImplementedError(f"Unsupported quantifier: {formula.quantifier}")


def create_tptp_problem(
    conjecture: Formula,
    axioms: Optional[List[Formula]] = None,
    problem_name: str = "cec_problem"
) -> str:
    """Create complete TPTP problem file.
    
    Args:
        conjecture: Formula to prove
        axioms: Optional list of axioms
        problem_name: Problem identifier
        
    Returns:
        Complete TPTP problem as string
        
    Example:
        >>> problem = create_tptp_problem(goal, [ax1, ax2], "test")
        >>> with open("problem.p", "w") as f:
        ...     f.write(problem)
    """
    lines = [
        f"% Problem: {problem_name}",
        f"% Generated by CEC TPTP utilities",
        ""
    ]
    
    # Add axioms
    if axioms:
        for i, axiom in enumerate(axioms):
            tptp_axiom = formula_to_tptp(axiom, "axiom", f"ax{i+1}")
            lines.append(tptp_axiom)
        lines.append("")
    
    # Add conjecture
    tptp_conjecture = formula_to_tptp(conjecture, "conjecture", "goal")
    lines.append(tptp_conjecture)
    
    return "\n".join(lines)


@dataclass
class TPTPFormula:
    """A TPTP-formatted formula with metadata."""
    formula: Formula
    role: str = "conjecture"
    name: str = "f1"
    tptp_str: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.tptp_str = formula_to_tptp(self.formula, self.role, self.name)

    def __str__(self) -> str:
        return self.tptp_str


class TPTPConverter:
    """Converter for CEC formulas to TPTP format."""

    def convert(self, formula: Formula, role: str = "conjecture", name: str = "f1") -> str:
        """Convert a formula to TPTP string."""
        return formula_to_tptp(formula, role, name)

    def create_problem(
        self,
        conjecture: Formula,
        axioms: Optional[List[Formula]] = None,
        problem_name: str = "problem",
    ) -> str:
        """Create a complete TPTP problem string."""
        return create_tptp_problem(conjecture, axioms, problem_name)

    def convert_formula(self, formula: Formula) -> "TPTPFormula":
        """Convert a formula to a TPTPFormula object."""
        return TPTPFormula(formula)
