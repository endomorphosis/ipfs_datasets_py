"""
Formula Complexity Analyzer for Intelligent Prover Selection

This module analyzes TDFOL formulas to determine their characteristics
and recommend the best prover for solving them.

Features:
- Complexity scoring (quantifier depth, nesting, operator count)
- Formula classification (FOL, modal, temporal, deontic, arithmetic)
- Prover recommendations based on formula characteristics
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Set
import logging

logger = logging.getLogger(__name__)


class FormulaType(Enum):
    """Types of logical formulas."""
    PURE_FOL = "pure_fol"  # No modal/temporal/deontic operators
    MODAL = "modal"  # Contains modal operators
    TEMPORAL = "temporal"  # Contains temporal operators
    DEONTIC = "deontic"  # Contains deontic operators
    MIXED_MODAL = "mixed_modal"  # Multiple modal types
    MIXED = "mixed_modal"  # alias for MIXED_MODAL
    ARITHMETIC = "arithmetic"  # Contains arithmetic
    QUANTIFIED = "quantified"  # Contains quantifiers
    PROPOSITIONAL = "propositional"  # No quantifiers or modal


class FormulaComplexity(Enum):
    """Complexity levels for formulas."""
    TRIVIAL = 1  # Single predicate or atomic
    SIMPLE = 2  # Few operators, no quantifiers
    MODERATE = 3  # Some quantifiers/nesting
    COMPLEX = 4  # Deep nesting or many quantifiers
    VERY_COMPLEX = 5  # Highly nested with multiple modalities


@dataclass
class FormulaAnalysis:
    """Analysis result for a formula.
    
    Attributes:
        formula_type: Primary type of the formula
        complexity: Complexity level
        quantifier_depth: Maximum nesting depth of quantifiers
        nesting_level: Maximum nesting of operators
        operator_count: Total number of operators
        has_arithmetic: Whether formula contains arithmetic
        has_modal: Whether formula has modal operators
        has_temporal: Whether formula has temporal operators
        has_deontic: Whether formula has deontic operators
        recommended_provers: List of recommended prover names (ordered)
        complexity_score: Numeric complexity score (0-100)
        analysis_details: Additional analysis information
    """
    formula_type: FormulaType
    complexity: FormulaComplexity
    quantifier_depth: int
    nesting_level: int
    operator_count: int
    has_arithmetic: bool
    has_modal: bool
    has_temporal: bool
    has_deontic: bool
    recommended_provers: List[str]
    complexity_score: float
    analysis_details: Dict[str, Any]

    @property
    def has_quantifiers(self) -> bool:
        """Backward-compat alias: True if quantifier_depth > 0."""
        return self.quantifier_depth > 0

    @property
    def has_modal_operators(self) -> bool:
        """Backward-compat alias for has_modal."""
        return self.has_modal

    @property
    def has_temporal_operators(self) -> bool:
        """Backward-compat alias for has_temporal."""
        return self.has_temporal

    @property
    def has_deontic_operators(self) -> bool:
        """Backward-compat alias for has_deontic."""
        return self.has_deontic

    @property
    def complexity_level(self) -> 'FormulaComplexity':
        """Backward-compat alias for complexity."""
        return self.complexity


class FormulaAnalyzer:
    """Analyzes TDFOL formulas to recommend optimal provers.
    
    This class examines formula structure and characteristics to:
    1. Classify the type of logic being used
    2. Measure complexity metrics
    3. Recommend the best prover(s) for the formula
    """
    
    def __init__(self):
        """Initialize the formula analyzer."""
        self.prover_capabilities = self._init_prover_capabilities()
        # Add compat 'capabilities' and 'performance' keys if not present
        for name, profile in self.prover_capabilities.items():
            profile.setdefault('capabilities', {
                'modal': profile.get('supports_modal', False),
                'temporal': profile.get('supports_temporal', False),
                'deontic': profile.get('supports_deontic', False),
                'arithmetic': profile.get('supports_arithmetic', False),
                'quantifiers': profile.get('quantifier_handling', 'unknown'),
            })
            profile.setdefault('performance', {
                'speed': profile.get('speed', 'unknown'),
                'max_complexity': str(profile.get('max_complexity', 'unknown')),
            })
        self.prover_profiles = self.prover_capabilities  # compat alias
    
    def _init_prover_capabilities(self) -> Dict[str, Dict[str, Any]]:
        """Initialize prover capability profiles.
        
        Returns:
            Dictionary mapping prover names to their capabilities
        """
        return {
            'z3': {
                'good_for': [FormulaType.PURE_FOL, FormulaType.QUANTIFIED, FormulaType.ARITHMETIC],
                'max_complexity': FormulaComplexity.COMPLEX,
                'supports_modal': False,
                'supports_temporal': False,
                'supports_deontic': False,
                'supports_arithmetic': True,
                'speed': 'fast',  # 10-100ms
                'quantifier_handling': 'good',
            },
            'cvc5': {
                'good_for': [FormulaType.QUANTIFIED, FormulaType.PURE_FOL],
                'max_complexity': FormulaComplexity.VERY_COMPLEX,
                'supports_modal': False,
                'supports_temporal': False,
                'supports_deontic': False,
                'supports_arithmetic': True,
                'speed': 'medium',  # 50-200ms
                'quantifier_handling': 'excellent',
            },
            'lean': {
                'good_for': [FormulaType.PURE_FOL, FormulaType.MODAL, FormulaType.QUANTIFIED],
                'max_complexity': FormulaComplexity.VERY_COMPLEX,
                'supports_modal': True,
                'supports_temporal': True,
                'supports_deontic': True,
                'supports_arithmetic': True,
                'speed': 'slow',  # 1-10s
                'quantifier_handling': 'excellent',
            },
            'coq': {
                'good_for': [FormulaType.PURE_FOL, FormulaType.MODAL, FormulaType.QUANTIFIED],
                'max_complexity': FormulaComplexity.VERY_COMPLEX,
                'supports_modal': True,
                'supports_temporal': True,
                'supports_deontic': True,
                'supports_arithmetic': True,
                'speed': 'slow',  # 1-10s
                'quantifier_handling': 'excellent',
            },
            'symbolicai': {
                'good_for': [FormulaType.PURE_FOL, FormulaType.MODAL, FormulaType.TEMPORAL, FormulaType.DEONTIC],
                'max_complexity': FormulaComplexity.COMPLEX,
                'supports_modal': True,
                'supports_temporal': True,
                'supports_deontic': True,
                'supports_arithmetic': False,
                'speed': 'very_slow',  # 1000ms+
                'quantifier_handling': 'good',
            },
            'native': {
                'good_for': [FormulaType.PURE_FOL, FormulaType.PROPOSITIONAL],
                'max_complexity': FormulaComplexity.MODERATE,
                'supports_modal': False,
                'supports_temporal': False,
                'supports_deontic': False,
                'supports_arithmetic': False,
                'speed': 'very_fast',  # 1-10ms
                'quantifier_handling': 'fair',
            },
        }
    
    def analyze(self, formula) -> FormulaAnalysis:
        """Analyze a TDFOL formula.
        
        Args:
            formula: TDFOL formula to analyze
            
        Returns:
            FormulaAnalysis with detailed metrics and recommendations
        """
        # Calculate metrics
        quantifier_depth = self._measure_quantifier_depth(formula)
        nesting_level = self._measure_nesting_level(formula)
        operator_count = self._count_operators(formula)
        
        # Detect formula characteristics
        has_arithmetic = self._has_arithmetic(formula)
        has_modal = self._has_modal_operators(formula)
        has_temporal = self._has_temporal_operators(formula)
        has_deontic = self._has_deontic_operators(formula)
        
        # Classify formula type
        formula_type = self._classify_formula_type(
            quantifier_depth, has_modal, has_temporal, has_deontic, has_arithmetic
        )
        
        # Calculate complexity
        complexity_score = self._calculate_complexity_score(
            quantifier_depth, nesting_level, operator_count, has_modal, has_temporal, has_deontic
        )
        complexity = self._score_to_complexity(complexity_score)
        
        # Recommend provers
        recommended_provers = self._recommend_provers(
            formula_type, complexity, has_arithmetic, quantifier_depth
        )
        
        # Build analysis details
        analysis_details = {
            'quantifier_count': self._count_quantifiers(formula),
            'modal_operator_count': self._count_modal_operators(formula),
            'temporal_operator_count': self._count_temporal_operators(formula),
            'deontic_operator_count': self._count_deontic_operators(formula),
            'predicate_count': self._count_predicates(formula),
            'variable_count': self._count_variables(formula),
        }
        
        return FormulaAnalysis(
            formula_type=formula_type,
            complexity=complexity,
            quantifier_depth=quantifier_depth,
            nesting_level=nesting_level,
            operator_count=operator_count,
            has_arithmetic=has_arithmetic,
            has_modal=has_modal,
            has_temporal=has_temporal,
            has_deontic=has_deontic,
            recommended_provers=recommended_provers,
            complexity_score=complexity_score,
            analysis_details=analysis_details
        )
    
    def _measure_quantifier_depth(self, formula, current_depth: int = 0) -> int:
        """Measure maximum quantifier nesting depth."""
        try:
            from ..TDFOL.tdfol_core import QuantifiedFormula, BinaryFormula, UnaryFormula
            from ..TDFOL.tdfol_core import TemporalFormula, DeonticFormula, BinaryTemporalFormula
            
            if isinstance(formula, QuantifiedFormula):
                return self._measure_quantifier_depth(formula.formula, current_depth + 1)
            elif isinstance(formula, (BinaryFormula, BinaryTemporalFormula)):
                left_depth = self._measure_quantifier_depth(formula.left, current_depth)
                right_depth = self._measure_quantifier_depth(formula.right, current_depth)
                return max(left_depth, right_depth)
            elif isinstance(formula, (UnaryFormula, TemporalFormula, DeonticFormula)):
                return self._measure_quantifier_depth(formula.formula, current_depth)
            else:
                return current_depth
        except (AttributeError, ImportError, TypeError) as exc:
            logger.debug(
                "Could not measure quantifier depth for formula: %s",
                exc,
                exc_info=True
            )
            return current_depth
    
    def _measure_nesting_level(self, formula, current_level: int = 0) -> int:
        """Measure maximum formula nesting level."""
        try:
            from ..TDFOL.tdfol_core import (
                QuantifiedFormula, BinaryFormula, UnaryFormula,
                TemporalFormula, DeonticFormula, BinaryTemporalFormula, Predicate
            )
            
            if isinstance(formula, Predicate):
                return current_level + 1
            elif isinstance(formula, (BinaryFormula, BinaryTemporalFormula)):
                left_level = self._measure_nesting_level(formula.left, current_level + 1)
                right_level = self._measure_nesting_level(formula.right, current_level + 1)
                return max(left_level, right_level)
            elif isinstance(formula, (UnaryFormula, QuantifiedFormula, TemporalFormula, DeonticFormula)):
                return self._measure_nesting_level(formula.formula, current_level + 1)
            else:
                return current_level
        except (AttributeError, ImportError, TypeError) as exc:
            logger.debug(
                "Could not measure nesting level for formula: %s",
                exc,
                exc_info=True
            )
            return current_level
    
    def _count_operators(self, formula) -> int:
        """Count total number of operators in formula."""
        try:
            from ..TDFOL.tdfol_core import (
                BinaryFormula, UnaryFormula, QuantifiedFormula,
                TemporalFormula, DeonticFormula, BinaryTemporalFormula, Predicate
            )
            
            if isinstance(formula, Predicate):
                return 0
            elif isinstance(formula, (BinaryFormula, BinaryTemporalFormula)):
                return 1 + self._count_operators(formula.left) + self._count_operators(formula.right)
            elif isinstance(formula, (UnaryFormula, QuantifiedFormula, TemporalFormula, DeonticFormula)):
                return 1 + self._count_operators(formula.formula)
            else:
                return 0
        except (AttributeError, ImportError, TypeError) as exc:
            logger.debug("Could not count operators: %s", exc, exc_info=True)
            return 0
    
    def _has_arithmetic(self, formula) -> bool:
        """Check if formula contains arithmetic operations."""
        # Simplified check - can be enhanced
        formula_str = str(formula)
        arithmetic_ops = ['+', '-', '*', '/', '<', '>', '<=', '>=', '=']
        return any(op in formula_str for op in arithmetic_ops)
    
    def _has_modal_operators(self, formula) -> bool:
        """Check if formula has modal operators (□, ◊) or modal predicate names."""
        try:
            from ..TDFOL.tdfol_core import TemporalFormula, TemporalOperator, Predicate as TDFOLPredicate

            modal_pred_names = {'always', 'necessarily', 'possibly', 'box', 'diamond'}

            def check(f):
                if isinstance(f, TemporalFormula):
                    if f.operator in [TemporalOperator.ALWAYS, TemporalOperator.EVENTUALLY]:
                        return True
                    return check(f.formula)
                if isinstance(f, TDFOLPredicate):
                    if f.name.lower() in modal_pred_names:
                        return True
                    for arg in (f.arguments or []):
                        if check(arg):
                            return True
                elif hasattr(f, 'left') and hasattr(f, 'right'):
                    return check(f.left) or check(f.right)
                elif hasattr(f, 'formula'):
                    return check(f.formula)
                return False

            return check(formula)
        except Exception:
            return False
    
    def _has_temporal_operators(self, formula) -> bool:
        """Check if formula has temporal operators (X, U, S) or temporal predicate names."""
        try:
            from ..TDFOL.tdfol_core import TemporalFormula, BinaryTemporalFormula, Predicate as TDFOLPredicate
            temporal_pred_names = {'eventually', 'next', 'until', 'since', 'release', 'before', 'after'}
            if isinstance(formula, TDFOLPredicate) and formula.name.lower() in temporal_pred_names:
                return True
            return self._contains_type(formula, (TemporalFormula, BinaryTemporalFormula))
        except Exception:
            return False
    
    def _has_deontic_operators(self, formula) -> bool:
        """Check if formula has deontic operators (O, P, F) or deontic predicate names."""
        try:
            from ..TDFOL.tdfol_core import DeonticFormula, Predicate as TDFOLPredicate
            deontic_pred_names = {'obligatory', 'obligated', 'permitted', 'forbidden', 'prohibited',
                                  'obligation', 'permission', 'prohibition', 'required', 'allowed'}
            if isinstance(formula, TDFOLPredicate) and formula.name.lower() in deontic_pred_names:
                return True
            return self._contains_type(formula, DeonticFormula)
        except Exception:
            return False
    
    def _contains_type(self, formula, target_type) -> bool:
        """Check if formula contains a specific type."""
        if isinstance(formula, target_type):
            return True
        
        if hasattr(formula, 'left') and hasattr(formula, 'right'):
            return self._contains_type(formula.left, target_type) or self._contains_type(formula.right, target_type)
        elif hasattr(formula, 'formula'):
            return self._contains_type(formula.formula, target_type)
        
        return False
    
    def _count_quantifiers(self, formula) -> int:
        """Count total quantifiers."""
        try:
            from ..TDFOL.tdfol_core import QuantifiedFormula
            
            if isinstance(formula, QuantifiedFormula):
                return 1 + self._count_quantifiers(formula.formula)
            elif hasattr(formula, 'left') and hasattr(formula, 'right'):
                return self._count_quantifiers(formula.left) + self._count_quantifiers(formula.right)
            elif hasattr(formula, 'formula'):
                return self._count_quantifiers(formula.formula)
            return 0
        except:
            return 0
    
    def _count_modal_operators(self, formula) -> int:
        """Count modal operators."""
        try:
            from ..TDFOL.tdfol_core import TemporalFormula, TemporalOperator
            
            count = 0
            if isinstance(formula, TemporalFormula):
                if formula.operator in [TemporalOperator.ALWAYS, TemporalOperator.EVENTUALLY]:
                    count = 1
                count += self._count_modal_operators(formula.formula)
            elif hasattr(formula, 'left') and hasattr(formula, 'right'):
                count = self._count_modal_operators(formula.left) + self._count_modal_operators(formula.right)
            elif hasattr(formula, 'formula'):
                count = self._count_modal_operators(formula.formula)
            return count
        except:
            return 0
    
    def _count_temporal_operators(self, formula) -> int:
        """Count temporal operators."""
        try:
            from ..TDFOL.tdfol_core import TemporalFormula, BinaryTemporalFormula
            
            count = 0
            if isinstance(formula, (TemporalFormula, BinaryTemporalFormula)):
                count = 1
            
            if hasattr(formula, 'left') and hasattr(formula, 'right'):
                count += self._count_temporal_operators(formula.left) + self._count_temporal_operators(formula.right)
            elif hasattr(formula, 'formula'):
                count += self._count_temporal_operators(formula.formula)
            
            return count
        except:
            return 0
    
    def _count_deontic_operators(self, formula) -> int:
        """Count deontic operators."""
        try:
            from ..TDFOL.tdfol_core import DeonticFormula
            
            count = 0
            if isinstance(formula, DeonticFormula):
                count = 1
            
            if hasattr(formula, 'left') and hasattr(formula, 'right'):
                count += self._count_deontic_operators(formula.left) + self._count_deontic_operators(formula.right)
            elif hasattr(formula, 'formula'):
                count += self._count_deontic_operators(formula.formula)
            
            return count
        except:
            return 0
    
    def _count_predicates(self, formula) -> int:
        """Count predicates in formula."""
        try:
            from ..TDFOL.tdfol_core import Predicate
            
            count = 0
            if isinstance(formula, Predicate):
                count = 1
            
            if hasattr(formula, 'left') and hasattr(formula, 'right'):
                count += self._count_predicates(formula.left) + self._count_predicates(formula.right)
            elif hasattr(formula, 'formula'):
                count += self._count_predicates(formula.formula)
            
            return count
        except:
            return 0
    
    def _count_variables(self, formula) -> int:
        """Count unique variables."""
        try:
            vars_set = set()
            self._collect_variables(formula, vars_set)
            return len(vars_set)
        except:
            return 0
    
    def _collect_variables(self, formula, vars_set: Set[str]):
        """Collect all variables in formula."""
        try:
            from ..TDFOL.tdfol_core import Variable, QuantifiedFormula, Predicate
            
            if isinstance(formula, QuantifiedFormula):
                vars_set.add(formula.variable.name)
                self._collect_variables(formula.formula, vars_set)
            elif isinstance(formula, Predicate):
                for arg in formula.args:
                    if isinstance(arg, Variable):
                        vars_set.add(arg.name)
            elif hasattr(formula, 'left') and hasattr(formula, 'right'):
                self._collect_variables(formula.left, vars_set)
                self._collect_variables(formula.right, vars_set)
            elif hasattr(formula, 'formula'):
                self._collect_variables(formula.formula, vars_set)
        except:
            pass
    
    def _classify_formula_type(
        self,
        quantifier_depth: int,
        has_modal: bool,
        has_temporal: bool,
        has_deontic: bool,
        has_arithmetic: bool
    ) -> FormulaType:
        """Classify the primary type of formula."""
        modal_count = sum([has_modal, has_temporal, has_deontic])
        
        if modal_count >= 2:
            return FormulaType.MIXED_MODAL
        elif has_deontic:
            return FormulaType.DEONTIC
        elif has_temporal:
            return FormulaType.TEMPORAL
        elif has_modal:
            return FormulaType.MODAL
        elif has_arithmetic:
            return FormulaType.ARITHMETIC
        elif quantifier_depth > 0:
            return FormulaType.QUANTIFIED
        elif quantifier_depth == 0:
            return FormulaType.PROPOSITIONAL
        else:
            return FormulaType.PURE_FOL
    
    def _calculate_complexity_score(
        self,
        quantifier_depth: int,
        nesting_level: int,
        operator_count: int,
        has_modal: bool,
        has_temporal: bool,
        has_deontic: bool
    ) -> float:
        """Calculate numeric complexity score (0-100)."""
        score = 0.0
        
        # Quantifier depth contributes significantly
        score += quantifier_depth * 15
        
        # Nesting level
        score += nesting_level * 5
        
        # Operator count
        score += operator_count * 2
        
        # Modal operators add complexity
        if has_modal:
            score += 15
        if has_temporal:
            score += 15
        if has_deontic:
            score += 15
        
        # Cap at 100
        return min(score, 100.0)
    
    def _score_to_complexity(self, score: float) -> FormulaComplexity:
        """Convert numeric score to complexity level."""
        if score < 10:
            return FormulaComplexity.TRIVIAL
        elif score < 25:
            return FormulaComplexity.SIMPLE
        elif score < 50:
            return FormulaComplexity.MODERATE
        elif score < 75:
            return FormulaComplexity.COMPLEX
        else:
            return FormulaComplexity.VERY_COMPLEX
    
    def _recommend_provers(
        self,
        formula_type: FormulaType,
        complexity: FormulaComplexity,
        has_arithmetic: bool,
        quantifier_depth: int
    ) -> List[str]:
        """Recommend provers in order of suitability."""
        recommendations = []
        
        # Modal/temporal/deontic formulas
        if formula_type in [FormulaType.MODAL, FormulaType.TEMPORAL, FormulaType.DEONTIC, FormulaType.MIXED_MODAL]:
            if complexity.value >= FormulaComplexity.COMPLEX.value:
                recommendations.extend(['lean', 'coq', 'symbolicai'])
            else:
                recommendations.extend(['symbolicai', 'lean', 'coq'])
        
        # Quantified formulas
        elif formula_type == FormulaType.QUANTIFIED:
            if quantifier_depth >= 3 or complexity.value >= FormulaComplexity.COMPLEX.value:
                recommendations.extend(['cvc5', 'lean', 'coq', 'z3'])
            else:
                recommendations.extend(['z3', 'cvc5'])
        
        # Arithmetic formulas
        elif has_arithmetic or formula_type == FormulaType.ARITHMETIC:
            recommendations.extend(['z3', 'cvc5'])
        
        # Simple FOL or propositional
        elif formula_type in [FormulaType.PROPOSITIONAL, FormulaType.PURE_FOL]:
            if complexity.value <= FormulaComplexity.SIMPLE.value:
                recommendations.extend(['native', 'z3'])
            else:
                recommendations.extend(['z3', 'cvc5'])
        
        # Default fallback
        else:
            recommendations.extend(['z3', 'native'])
        
        # Remove duplicates while preserving order
        seen = set()
        result = []
        for prover in recommendations:
            if prover not in seen:
                seen.add(prover)
                result.append(prover)

        # Ensure at least 3 recommendations by adding fallbacks
        fallbacks = ['native', 'z3', 'cvc5', 'lean']
        for fb in fallbacks:
            if len(result) >= 3:
                break
            if fb not in seen:
                seen.add(fb)
                result.append(fb)

        return result


__all__ = ['FormulaAnalyzer', 'FormulaAnalysis', 'FormulaType', 'FormulaComplexity']
