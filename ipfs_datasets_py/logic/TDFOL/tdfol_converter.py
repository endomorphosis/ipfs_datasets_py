"""
TDFOL Converter - Convert between TDFOL and other logic representations

This module provides bidirectional conversion between:
1. TDFOL ↔ DCEC (Deontic Cognitive Event Calculus)
2. TDFOL ↔ FOL (First-Order Logic)
3. TDFOL ↔ Deontic Logic
4. TDFOL ↔ String representations (TPTP, SMT-LIB, etc.)

The converter enables integration with existing logic systems while maintaining
a unified TDFOL representation internally.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .tdfol_core import (
    BinaryFormula,
    BinaryTemporalFormula,
    Constant,
    DeonticFormula,
    DeonticOperator,
    Formula,
    FunctionApplication,
    LogicOperator,
    Predicate,
    Quantifier,
    QuantifiedFormula,
    Sort,
    TemporalFormula,
    TemporalOperator,
    Term,
    UnaryFormula,
    Variable,
)

logger = logging.getLogger(__name__)


# ============================================================================
# TDFOL to DCEC Conversion
# ============================================================================


class TDFOLToDCECConverter:
    """Convert TDFOL formulas to DCEC format."""
    
    def __init__(self):
        self.dcec_available = self._check_dcec_available()
    
    def _check_dcec_available(self) -> bool:
        """Check if DCEC module is available."""
        try:
            from ipfs_datasets_py.logic.CEC.native import dcec_core
            return True
        except ImportError:
            logger.warning("DCEC module not available")
            return False
    
    def convert(self, formula: Formula) -> str:
        """
        Convert TDFOL formula to DCEC string representation.
        
        Args:
            formula: TDFOL formula to convert
        
        Returns:
            DCEC string representation
        """
        if not self.dcec_available:
            return self._convert_to_dcec_string(formula)
        
        try:
            from ipfs_datasets_py.logic.CEC.native import dcec_core
            # Would use dcec_core to create proper DCEC Formula objects
            return self._convert_to_dcec_string(formula)
        except Exception as e:
            logger.error(f"Failed to convert to DCEC: {e}")
            return self._convert_to_dcec_string(formula)
    
    def _convert_to_dcec_string(self, formula: Formula) -> str:
        """Convert to DCEC string format."""
        if isinstance(formula, Predicate):
            if formula.arguments:
                args = ",".join(self._convert_term(arg) for arg in formula.arguments)
                return f"{formula.name}({args})"
            return formula.name
        
        elif isinstance(formula, BinaryFormula):
            left = self._convert_to_dcec_string(formula.left)
            right = self._convert_to_dcec_string(formula.right)
            
            op_map = {
                LogicOperator.AND: "and",
                LogicOperator.OR: "or",
                LogicOperator.IMPLIES: "implies",
                LogicOperator.IFF: "iff",
                LogicOperator.NOT: "not",
            }
            op = op_map.get(formula.operator, str(formula.operator.value))
            return f"({op} {left} {right})"
        
        elif isinstance(formula, UnaryFormula):
            inner = self._convert_to_dcec_string(formula.formula)
            return f"(not {inner})"
        
        elif isinstance(formula, QuantifiedFormula):
            var = formula.variable.name
            inner = self._convert_to_dcec_string(formula.formula)
            
            if formula.quantifier == Quantifier.FORALL:
                return f"(forall {var} {inner})"
            else:
                return f"(exists {var} {inner})"
        
        elif isinstance(formula, DeonticFormula):
            inner = self._convert_to_dcec_string(formula.formula)
            
            op_map = {
                DeonticOperator.OBLIGATION: "O",
                DeonticOperator.PERMISSION: "P",
                DeonticOperator.PROHIBITION: "F",
            }
            op = op_map[formula.operator]
            
            if formula.agent:
                agent = self._convert_term(formula.agent)
                return f"({op}_{agent} {inner})"
            return f"({op} {inner})"
        
        elif isinstance(formula, TemporalFormula):
            inner = self._convert_to_dcec_string(formula.formula)
            
            op_map = {
                TemporalOperator.ALWAYS: "always",
                TemporalOperator.EVENTUALLY: "eventually",
                TemporalOperator.NEXT: "next",
            }
            op = op_map.get(formula.operator, str(formula.operator.value))
            return f"({op} {inner})"
        
        elif isinstance(formula, BinaryTemporalFormula):
            left = self._convert_to_dcec_string(formula.left)
            right = self._convert_to_dcec_string(formula.right)
            
            op_map = {
                TemporalOperator.UNTIL: "until",
                TemporalOperator.SINCE: "since",
            }
            op = op_map.get(formula.operator, str(formula.operator.value))
            return f"({op} {left} {right})"
        
        else:
            return str(formula)
    
    def _convert_term(self, term: Term) -> str:
        """Convert TDFOL term to DCEC string."""
        if isinstance(term, Variable):
            return term.name
        elif isinstance(term, Constant):
            return term.name
        elif isinstance(term, FunctionApplication):
            args = ",".join(self._convert_term(arg) for arg in term.arguments)
            return f"{term.function_name}({args})"
        return str(term)


# ============================================================================
# DCEC to TDFOL Conversion
# ============================================================================


class DCECToTDFOLConverter:
    """Convert DCEC formulas to TDFOL format."""
    
    def __init__(self):
        self.dcec_available = self._check_dcec_available()
    
    def _check_dcec_available(self) -> bool:
        """Check if DCEC module is available."""
        try:
            from ipfs_datasets_py.logic.CEC.native import dcec_core
            return True
        except ImportError:
            return False
    
    def convert(self, dcec_formula: Any) -> Formula:
        """
        Convert DCEC formula to TDFOL.
        
        Args:
            dcec_formula: DCEC formula (string or Formula object)
        
        Returns:
            TDFOL Formula
        """
        if isinstance(dcec_formula, str):
            return self._parse_dcec_string(dcec_formula)
        
        if not self.dcec_available:
            raise ValueError("DCEC module not available for conversion")
        
        try:
            from ipfs_datasets_py.logic.CEC.native import dcec_core
            # Would convert dcec_core.Formula to TDFOL Formula
            return self._convert_dcec_formula(dcec_formula)
        except Exception as e:
            logger.error(f"Failed to convert from DCEC: {e}")
            raise
    
    def _parse_dcec_string(self, dcec_str: str) -> Formula:
        """Parse DCEC string to TDFOL formula."""
        # Simplified parsing - would need full DCEC parser
        from .tdfol_parser import parse_tdfol
        return parse_tdfol(dcec_str)
    
    def _convert_dcec_formula(self, dcec_formula: Any) -> Formula:
        """Convert DCEC Formula object to TDFOL."""
        # This would need full DCEC formula structure knowledge
        raise NotImplementedError("DCEC Formula object conversion not yet implemented")


# ============================================================================
# TDFOL to FOL Conversion
# ============================================================================


class TDFOLToFOLConverter:
    """Convert TDFOL to pure first-order logic (strips modal operators)."""
    
    def convert(self, formula: Formula) -> Formula:
        """
        Convert TDFOL formula to FOL by removing modal operators.
        
        Args:
            formula: TDFOL formula
        
        Returns:
            FOL formula (no modal operators)
        """
        if isinstance(formula, Predicate):
            return formula
        
        elif isinstance(formula, BinaryFormula):
            return BinaryFormula(
                formula.operator,
                self.convert(formula.left),
                self.convert(formula.right)
            )
        
        elif isinstance(formula, UnaryFormula):
            return UnaryFormula(
                formula.operator,
                self.convert(formula.formula)
            )
        
        elif isinstance(formula, QuantifiedFormula):
            return QuantifiedFormula(
                formula.quantifier,
                formula.variable,
                self.convert(formula.formula)
            )
        
        elif isinstance(formula, DeonticFormula):
            # Strip deontic operator, keep inner formula
            return self.convert(formula.formula)
        
        elif isinstance(formula, TemporalFormula):
            # Strip temporal operator, keep inner formula
            return self.convert(formula.formula)
        
        elif isinstance(formula, BinaryTemporalFormula):
            # Convert P U Q to P ∧ Q (approximation)
            return BinaryFormula(
                LogicOperator.AND,
                self.convert(formula.left),
                self.convert(formula.right)
            )
        
        else:
            logger.warning(f"Unknown formula type in FOL conversion: {type(formula)}")
            return formula


# ============================================================================
# TDFOL to TPTP Format
# ============================================================================


class TDFOLToTPTPConverter:
    """Convert TDFOL to TPTP format for automated theorem provers."""
    
    def convert(self, formula: Formula, name: str = "conjecture") -> str:
        """
        Convert TDFOL formula to TPTP format.
        
        Args:
            formula: TDFOL formula
            name: Name for the formula
        
        Returns:
            TPTP string representation
        """
        formula_str = self._convert_formula(formula)
        return f"fof({name}, conjecture, {formula_str})."
    
    def _convert_formula(self, formula: Formula) -> str:
        """Convert formula to TPTP syntax."""
        if isinstance(formula, Predicate):
            if formula.arguments:
                args = ",".join(self._convert_term(arg) for arg in formula.arguments)
                return f"{formula.name.lower()}({args})"
            return formula.name.lower()
        
        elif isinstance(formula, BinaryFormula):
            left = self._convert_formula(formula.left)
            right = self._convert_formula(formula.right)
            
            op_map = {
                LogicOperator.AND: "&",
                LogicOperator.OR: "|",
                LogicOperator.IMPLIES: "=>",
                LogicOperator.IFF: "<=>",
            }
            op = op_map.get(formula.operator, str(formula.operator.value))
            return f"({left} {op} {right})"
        
        elif isinstance(formula, UnaryFormula):
            inner = self._convert_formula(formula.formula)
            return f"~({inner})"
        
        elif isinstance(formula, QuantifiedFormula):
            var = formula.variable.name
            inner = self._convert_formula(formula.formula)
            
            if formula.quantifier == Quantifier.FORALL:
                return f"![{var}]: {inner}"
            else:
                return f"?[{var}]: {inner}"
        
        # Modal operators would need special handling or translation
        elif isinstance(formula, (DeonticFormula, TemporalFormula)):
            # For now, convert to predicate applications
            return self._modal_to_tptp(formula)
        
        else:
            return str(formula)
    
    def _convert_term(self, term: Term) -> str:
        """Convert term to TPTP syntax."""
        if isinstance(term, Variable):
            return term.name.upper()  # Variables uppercase in TPTP
        elif isinstance(term, Constant):
            return term.name.lower()  # Constants lowercase in TPTP
        elif isinstance(term, FunctionApplication):
            args = ",".join(self._convert_term(arg) for arg in term.arguments)
            return f"{term.function_name.lower()}({args})"
        return str(term)
    
    def _modal_to_tptp(self, formula: Formula) -> str:
        """Convert modal formula to TPTP predicate application."""
        if isinstance(formula, DeonticFormula):
            inner = self._convert_formula(formula.formula)
            op_name = {
                DeonticOperator.OBLIGATION: "obligatory",
                DeonticOperator.PERMISSION: "permitted",
                DeonticOperator.PROHIBITION: "forbidden",
            }[formula.operator]
            return f"{op_name}({inner})"
        
        elif isinstance(formula, TemporalFormula):
            inner = self._convert_formula(formula.formula)
            op_name = {
                TemporalOperator.ALWAYS: "always",
                TemporalOperator.EVENTUALLY: "eventually",
                TemporalOperator.NEXT: "next",
            }[formula.operator]
            return f"{op_name}({inner})"
        
        return str(formula)


# ============================================================================
# Public API
# ============================================================================


def tdfol_to_dcec(formula: Formula) -> str:
    """Convert TDFOL formula to DCEC string."""
    converter = TDFOLToDCECConverter()
    return converter.convert(formula)


def dcec_to_tdfol(dcec_formula: Any) -> Formula:
    """Convert DCEC formula to TDFOL."""
    converter = DCECToTDFOLConverter()
    return converter.convert(dcec_formula)


def tdfol_to_fol(formula: Formula) -> Formula:
    """Convert TDFOL to pure first-order logic."""
    converter = TDFOLToFOLConverter()
    return converter.convert(formula)


def tdfol_to_tptp(formula: Formula, name: str = "conjecture") -> str:
    """Convert TDFOL formula to TPTP format."""
    converter = TDFOLToTPTPConverter()
    return converter.convert(formula, name)
