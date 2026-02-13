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
        """Convert DCEC Formula object to TDFOL.
        
        This method converts a DCEC Formula object (from the native CEC implementation)
        into the corresponding TDFOL Formula representation.
        
        Args:
            dcec_formula: DCEC Formula object from ipfs_datasets_py.logic.CEC.native.dcec_core
            
        Returns:
            Equivalent TDFOL Formula
        """
        from ipfs_datasets_py.logic.CEC.native import dcec_core
        
        # Handle different DCEC formula types
        formula_type = type(dcec_formula).__name__
        
        # Atom/Predicate
        if hasattr(dcec_formula, 'name') and hasattr(dcec_formula, 'arguments'):
            # This is a predicate/atom
            args = []
            if hasattr(dcec_formula, 'arguments') and dcec_formula.arguments:
                for arg in dcec_formula.arguments:
                    args.append(self._convert_dcec_term(arg))
            return Predicate(dcec_formula.name, tuple(args))
        
        # Binary formulas (And, Or, Implies, Iff)
        if hasattr(dcec_formula, 'left') and hasattr(dcec_formula, 'right'):
            left = self._convert_dcec_formula(dcec_formula.left)
            right = self._convert_dcec_formula(dcec_formula.right)
            
            # Map DCEC operators to TDFOL operators
            if formula_type == 'And' or (hasattr(dcec_formula, 'operator') and dcec_formula.operator == 'and'):
                return BinaryFormula(LogicOperator.AND, left, right)
            elif formula_type == 'Or' or (hasattr(dcec_formula, 'operator') and dcec_formula.operator == 'or'):
                return BinaryFormula(LogicOperator.OR, left, right)
            elif formula_type == 'Implies' or (hasattr(dcec_formula, 'operator') and dcec_formula.operator == 'implies'):
                return BinaryFormula(LogicOperator.IMPLIES, left, right)
            elif formula_type == 'Iff' or (hasattr(dcec_formula, 'operator') and dcec_formula.operator == 'iff'):
                return BinaryFormula(LogicOperator.IFF, left, right)
        
        # Unary formulas (Not)
        if hasattr(dcec_formula, 'formula') and (formula_type == 'Not' or (hasattr(dcec_formula, 'operator') and dcec_formula.operator == 'not')):
            inner = self._convert_dcec_formula(dcec_formula.formula)
            return UnaryFormula(LogicOperator.NOT, inner)
        
        # Quantified formulas (Forall, Exists)
        if hasattr(dcec_formula, 'variable') and hasattr(dcec_formula, 'body'):
            var = self._convert_dcec_term(dcec_formula.variable)
            body = self._convert_dcec_formula(dcec_formula.body)
            
            if formula_type == 'Forall' or (hasattr(dcec_formula, 'quantifier') and dcec_formula.quantifier == 'forall'):
                return QuantifiedFormula(Quantifier.FORALL, var, body)
            elif formula_type == 'Exists' or (hasattr(dcec_formula, 'quantifier') and dcec_formula.quantifier == 'exists'):
                return QuantifiedFormula(Quantifier.EXISTS, var, body)
        
        # Deontic formulas (Obligation, Permission, Prohibition)
        if hasattr(dcec_formula, 'deontic_operator') or formula_type in ['Obligation', 'Permission', 'Prohibition']:
            inner = self._convert_dcec_formula(dcec_formula.formula if hasattr(dcec_formula, 'formula') else dcec_formula)
            
            if formula_type == 'Obligation' or (hasattr(dcec_formula, 'deontic_operator') and dcec_formula.deontic_operator == 'O'):
                return DeonticFormula(DeonticOperator.OBLIGATION, inner)
            elif formula_type == 'Permission' or (hasattr(dcec_formula, 'deontic_operator') and dcec_formula.deontic_operator == 'P'):
                return DeonticFormula(DeonticOperator.PERMISSION, inner)
            elif formula_type == 'Prohibition' or (hasattr(dcec_formula, 'deontic_operator') and dcec_formula.deontic_operator == 'F'):
                return DeonticFormula(DeonticOperator.PROHIBITION, inner)
        
        # Temporal formulas (Always, Eventually, Next)
        if hasattr(dcec_formula, 'temporal_operator') or formula_type in ['Always', 'Eventually', 'Next', 'Until', 'Since']:
            if formula_type in ['Until', 'Since'] or (hasattr(dcec_formula, 'left') and hasattr(dcec_formula, 'right')):
                # Binary temporal
                left = self._convert_dcec_formula(dcec_formula.left)
                right = self._convert_dcec_formula(dcec_formula.right)
                
                if formula_type == 'Until' or (hasattr(dcec_formula, 'temporal_operator') and dcec_formula.temporal_operator == 'U'):
                    return BinaryTemporalFormula(TemporalOperator.UNTIL, left, right)
                elif formula_type == 'Since' or (hasattr(dcec_formula, 'temporal_operator') and dcec_formula.temporal_operator == 'S'):
                    return BinaryTemporalFormula(TemporalOperator.SINCE, left, right)
            else:
                # Unary temporal
                inner = self._convert_dcec_formula(dcec_formula.formula if hasattr(dcec_formula, 'formula') else dcec_formula)
                
                if formula_type == 'Always' or (hasattr(dcec_formula, 'temporal_operator') and dcec_formula.temporal_operator == 'G'):
                    return TemporalFormula(TemporalOperator.ALWAYS, inner)
                elif formula_type == 'Eventually' or (hasattr(dcec_formula, 'temporal_operator') and dcec_formula.temporal_operator == 'F'):
                    return TemporalFormula(TemporalOperator.EVENTUALLY, inner)
                elif formula_type == 'Next' or (hasattr(dcec_formula, 'temporal_operator') and dcec_formula.temporal_operator == 'X'):
                    return TemporalFormula(TemporalOperator.NEXT, inner)
        
        # If we couldn't convert, try to parse as string
        logger.warning(f"Unknown DCEC formula type: {formula_type}, attempting string conversion")
        return self._parse_dcec_string(str(dcec_formula))
    
    def _convert_dcec_term(self, dcec_term: Any) -> Term:
        """Convert DCEC term to TDFOL term.
        
        Args:
            dcec_term: DCEC term object
            
        Returns:
            TDFOL Term (Variable, Constant, or FunctionApplication)
        """
        from ipfs_datasets_py.logic.CEC.native import dcec_core
        
        term_type = type(dcec_term).__name__
        
        # Variable
        if term_type == 'Variable' or (hasattr(dcec_term, 'is_variable') and dcec_term.is_variable):
            return Variable(dcec_term.name, Sort.OBJECT)
        
        # Constant
        if term_type == 'Constant' or not hasattr(dcec_term, 'arguments'):
            return Constant(str(dcec_term), Sort.OBJECT)
        
        # Function application
        if hasattr(dcec_term, 'function') and hasattr(dcec_term, 'arguments'):
            args = [self._convert_dcec_term(arg) for arg in dcec_term.arguments]
            return FunctionApplication(dcec_term.function, tuple(args))
        
        # Fallback: treat as constant
        return Constant(str(dcec_term), Sort.OBJECT)


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
