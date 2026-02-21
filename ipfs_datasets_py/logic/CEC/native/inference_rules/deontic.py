"""
Deontic Logic Inference Rules for CEC.

This module contains inference rules for deontic logic, which deals with:
- Obligation (O): something that must be done
- Permission (P): something that may be done
- Prohibition (F): something that must not be done

Deontic operators capture normative reasoning about rights, duties, and permissions.

Author: CEC Native Refactoring
Date: 2026-02-19
"""

from typing import List, Optional, Set
from .base import InferenceRule, ProofResult
from ..dcec_core import Formula, DeonticOperator, LogicalConnective


class ObligationDistribution(InferenceRule):
    """
    Obligation distributes over conjunction.
    
    Rule: O(P∧Q) ⊢ O(P) ∧ O(Q)
    
    If there is an obligation to do both P and Q, then there is an obligation
    to do P and an obligation to do Q separately.
    
    Example:
        O(study ∧ exercise) ⊢ O(study) ∧ O(exercise)
    """
    
    def name(self) -> str:
        return "ObligationDistribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if obligation distribution can be applied."""
        for f in formulas:
            if (hasattr(f, 'operator') and 
                f.operator == DeonticOperator.OBLIGATION and
                hasattr(f, 'operand') and
                hasattr(f.operand, 'operator') and
                f.operand.operator == LogicalConnective.AND):
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> ProofResult:
        """Apply obligation distribution rule."""
        for f in formulas:
            if (hasattr(f, 'operator') and 
                f.operator == DeonticOperator.OBLIGATION and
                hasattr(f, 'operand') and
                hasattr(f.operand, 'operator') and
                f.operand.operator == LogicalConnective.AND):
                
                # O(P∧Q) → O(P) ∧ O(Q)
                left = f.operand.left
                right = f.operand.right
                
                # Create O(P)
                from ..dcec_core import Formula as F
                oblig_left = F(operator=DeonticOperator.OBLIGATION, operand=left)
                # Create O(Q)
                oblig_right = F(operator=DeonticOperator.OBLIGATION, operand=right)
                # Create O(P) ∧ O(Q)
                result = F(operator=LogicalConnective.AND, left=oblig_left, right=oblig_right)
                
                return ProofResult.SUCCESS, [result]
        
        return ProofResult.FAILURE, []


class ObligationImplication(InferenceRule):
    """
    Obligation propagates through implication.
    
    Rule: O(P) ∧ (P→Q) ⊢ O(Q)
    
    If there is an obligation to do P, and P implies Q, then there is an
    obligation to do Q.
    
    Example:
        O(attend_class) ∧ (attend_class → arrive_early) ⊢ O(arrive_early)
    """
    
    def name(self) -> str:
        return "Obligation Implication"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if obligation implication can be applied."""
        obligations = []
        implications = []
        
        for f in formulas:
            if hasattr(f, 'operator'):
                if f.operator == DeonticOperator.OBLIGATION:
                    obligations.append(f)
                elif f.operator == Operator.IMPLIES:
                    implications.append(f)
        
        # Check if we have O(P) and (P→Q)
        for obl in obligations:
            if hasattr(obl, 'operand'):
                oblig_content = obl.operand
                for impl in implications:
                    if (hasattr(impl, 'left') and 
                        impl.left == oblig_content):
                        return True
        
        return False
    
    def apply(self, formulas: List[Formula]) -> ProofResult:
        """Apply obligation implication rule."""
        obligations = []
        implications = []
        
        for f in formulas:
            if hasattr(f, 'operator'):
                if f.operator == DeonticOperator.OBLIGATION:
                    obligations.append(f)
                elif f.operator == Operator.IMPLIES:
                    implications.append(f)
        
        # Find matching O(P) and (P→Q)
        for obl in obligations:
            if hasattr(obl, 'operand'):
                oblig_content = obl.operand
                for impl in implications:
                    if (hasattr(impl, 'left') and hasattr(impl, 'right') and
                        impl.left == oblig_content):
                        # Create O(Q)
                        from ..dcec_core import Formula as F
                        result = F(operator=DeonticOperator.OBLIGATION, operand=impl.right)
                        return ProofResult.SUCCESS, [result]
        
        return ProofResult.FAILURE, []


class PermissionFromNonObligation(InferenceRule):
    """
    Permission is the dual of obligation.
    
    Rule: ¬O(¬P) ⊢ P(P)
    
    If it's not obligatory to not do P, then P is permitted.
    This captures the deontic duality principle.
    
    Example:
        ¬O(¬speak) ⊢ P(speak)
    """
    
    def name(self) -> str:
        return "Permission from Non-Obligation"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if permission derivation can be applied."""
        for f in formulas:
            if (hasattr(f, 'operator') and 
                f.operator == LogicalConnective.NOT and
                hasattr(f, 'operand') and
                hasattr(f.operand, 'operator') and
                f.operand.operator == DeonticOperator.OBLIGATION and
                hasattr(f.operand, 'operand') and
                hasattr(f.operand.operand, 'operator') and
                f.operand.operand.operator == LogicalConnective.NOT):
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> ProofResult:
        """Apply permission from non-obligation rule."""
        for f in formulas:
            if (hasattr(f, 'operator') and 
                f.operator == LogicalConnective.NOT and
                hasattr(f, 'operand') and
                hasattr(f.operand, 'operator') and
                f.operand.operator == DeonticOperator.OBLIGATION and
                hasattr(f.operand, 'operand') and
                hasattr(f.operand.operand, 'operator') and
                f.operand.operand.operator == LogicalConnective.NOT):
                
                # ¬O(¬P) → P(P)
                inner_content = f.operand.operand.operand
                
                # Create P(P)
                from ..dcec_core import Formula as F
                result = F(operator=DeonticOperator.PERMISSION, operand=inner_content)
                
                return ProofResult.SUCCESS, [result]
        
        return ProofResult.FAILURE, []


class ObligationConjunction(InferenceRule):
    """
    Combine separate obligations into a single conjunction obligation.
    
    Rule: O(P) ∧ O(Q) ⊢ O(P∧Q)
    
    If there is an obligation to do P and an obligation to do Q, then there
    is an obligation to do both P and Q.
    
    Example:
        O(study) ∧ O(exercise) ⊢ O(study ∧ exercise)
    """
    
    def name(self) -> str:
        return "Obligation Conjunction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if obligation conjunction can be applied."""
        obligations = [f for f in formulas 
                      if hasattr(f, 'operator') and f.operator == DeonticOperator.OBLIGATION]
        return len(obligations) >= 2
    
    def apply(self, formulas: List[Formula]) -> ProofResult:
        """Apply obligation conjunction rule."""
        obligations = [f for f in formulas 
                      if hasattr(f, 'operator') and f.operator == DeonticOperator.OBLIGATION]
        
        if len(obligations) >= 2:
            # Take first two obligations
            obl1, obl2 = obligations[0], obligations[1]
            
            if hasattr(obl1, 'operand') and hasattr(obl2, 'operand'):
                # Create P∧Q
                from ..dcec_core import Formula as F
                conjunction = F(operator=LogicalConnective.AND, 
                              left=obl1.operand, 
                              right=obl2.operand)
                # Create O(P∧Q)
                result = F(operator=DeonticOperator.OBLIGATION, operand=conjunction)
                
                return ProofResult.SUCCESS, [result]
        
        return ProofResult.FAILURE, []


class PermissionDistribution(InferenceRule):
    """
    Permission distributes over disjunction.
    
    Rule: P(P∨Q) ⊢ P(P) ∨ P(Q)
    
    If it's permitted to do either P or Q, then either P is permitted or
    Q is permitted (or both).
    
    Example:
        P(coffee ∨ tea) ⊢ P(coffee) ∨ P(tea)
    """
    
    def name(self) -> str:
        return "Permission Distribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if permission distribution can be applied."""
        for f in formulas:
            if (hasattr(f, 'operator') and 
                f.operator == DeonticOperator.PERMISSION and
                hasattr(f, 'operand') and
                hasattr(f.operand, 'operator') and
                f.operand.operator == LogicalConnective.OR):
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> ProofResult:
        """Apply permission distribution rule."""
        for f in formulas:
            if (hasattr(f, 'operator') and 
                f.operator == DeonticOperator.PERMISSION and
                hasattr(f, 'operand') and
                hasattr(f.operand, 'operator') and
                f.operand.operator == LogicalConnective.OR):
                
                # P(P∨Q) → P(P) ∨ P(Q)
                left = f.operand.left
                right = f.operand.right
                
                # Create P(P)
                from ..dcec_core import Formula as F
                perm_left = F(operator=DeonticOperator.PERMISSION, operand=left)
                # Create P(Q)
                perm_right = F(operator=DeonticOperator.PERMISSION, operand=right)
                # Create P(P) ∨ P(Q)
                result = F(operator=LogicalConnective.OR, left=perm_left, right=perm_right)
                
                return ProofResult.SUCCESS, [result]
        
        return ProofResult.FAILURE, []


class ObligationConsistency(InferenceRule):
    """
    Detect contradictory obligations.
    
    Rule: O(P) ∧ O(¬P) ⊢ ⊥
    
    If there is both an obligation to do P and an obligation to not do P,
    this represents an inconsistency (contradiction).
    
    Example:
        O(speak) ∧ O(¬speak) ⊢ ⊥ (inconsistent)
    """
    
    def name(self) -> str:
        return "Obligation Consistency"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we can detect obligation inconsistency."""
        obligations = [f for f in formulas 
                      if hasattr(f, 'operator') and f.operator == DeonticOperator.OBLIGATION]
        
        # Check for O(P) and O(¬P)
        for obl1 in obligations:
            if hasattr(obl1, 'operand'):
                content1 = obl1.operand
                for obl2 in obligations:
                    if obl1 != obl2 and hasattr(obl2, 'operand'):
                        content2 = obl2.operand
                        # Check if content2 is ¬content1
                        if (hasattr(content2, 'operator') and
                            content2.operator == LogicalConnective.NOT and
                            hasattr(content2, 'operand') and
                            content2.operand == content1):
                            return True
        
        return False
    
    def apply(self, formulas: List[Formula]) -> ProofResult:
        """Apply obligation consistency check."""
        obligations = [f for f in formulas 
                      if hasattr(f, 'operator') and f.operator == DeonticOperator.OBLIGATION]
        
        # Check for O(P) and O(¬P)
        for obl1 in obligations:
            if hasattr(obl1, 'operand'):
                content1 = obl1.operand
                for obl2 in obligations:
                    if obl1 != obl2 and hasattr(obl2, 'operand'):
                        content2 = obl2.operand
                        # Check if content2 is ¬content1
                        if (hasattr(content2, 'operator') and
                            content2.operator == LogicalConnective.NOT and
                            hasattr(content2, 'operand') and
                            content2.operand == content1):
                            # Inconsistency detected - return empty list
                            return ProofResult.FAILURE, []
        
        return ProofResult.FAILURE, []


class ProhibitionEquivalence(InferenceRule):
    """
    Prohibition is equivalent to obligation of negation.
    
    Rule: F(P) ⊣⊢ O(¬P)
    
    To be forbidden from doing P is the same as being obligated to not do P.
    This is a bidirectional equivalence.
    
    Example:
        F(smoke) ⊣⊢ O(¬smoke)
    """
    
    def name(self) -> str:
        return "Prohibition Equivalence"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if prohibition equivalence can be applied."""
        for f in formulas:
            if hasattr(f, 'operator'):
                # Check for F(P) to convert to O(¬P)
                if f.operator == DeonticOperator.PROHIBITION:
                    return True
                # Check for O(¬P) to convert to F(P)
                if (f.operator == DeonticOperator.OBLIGATION and
                    hasattr(f, 'operand') and
                    hasattr(f.operand, 'operator') and
                    f.operand.operator == LogicalConnective.NOT):
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> ProofResult:
        """Apply prohibition equivalence rule."""
        for f in formulas:
            if hasattr(f, 'operator'):
                from ..dcec_core import Formula as F
                
                # F(P) → O(¬P)
                if f.operator == DeonticOperator.PROHIBITION and hasattr(f, 'operand'):
                    negation = F(operator=LogicalConnective.NOT, operand=f.operand)
                    result = F(operator=DeonticOperator.OBLIGATION, operand=negation)
                    return ProofResult.SUCCESS, [result]
                
                # O(¬P) → F(P)
                if (f.operator == DeonticOperator.OBLIGATION and
                    hasattr(f, 'operand') and
                    hasattr(f.operand, 'operator') and
                    f.operand.operator == LogicalConnective.NOT and
                    hasattr(f.operand, 'operand')):
                    result = F(operator=DeonticOperator.PROHIBITION, 
                             operand=f.operand.operand)
                    return ProofResult.SUCCESS, [result]
        
        return ProofResult.FAILURE, []


# Export all deontic rules
__all__ = [
    'ObligationDistribution',
    'ObligationImplication',
    'PermissionFromNonObligation',
    'ObligationConjunction',
    'PermissionDistribution',
    'ObligationConsistency',
    'ProhibitionEquivalence',
]
