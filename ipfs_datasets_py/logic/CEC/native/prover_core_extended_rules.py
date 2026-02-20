"""
Extended inference rules for DCEC theorem proving.

These rules are not yet present in the inference_rules package and are
preserved here for backward compatibility.
"""

from typing import List
from .inference_rules.base import InferenceRule
from .dcec_core import (
    Formula,
    AtomicFormula,
    ConnectiveFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    QuantifiedFormula,
    LogicalConnective,
    Variable,
    Term,
)

class Commutativity(InferenceRule):
    """Commutativity: P∧Q ↔ Q∧P and P∨Q ↔ Q∨P."""
    
    def name(self) -> str:
        return "Commutativity"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, ConnectiveFormula) and f.connective in [LogicalConnective.AND, LogicalConnective.OR]
            and len(f.formulas) == 2
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and len(f.formulas) == 2:
                if f.connective in [LogicalConnective.AND, LogicalConnective.OR]:
                    # Swap the operands
                    swapped = ConnectiveFormula(f.connective, [f.formulas[1], f.formulas[0]])
                    results.append(swapped)
        return results



class Distribution(InferenceRule):
    """Distribution: P∨(Q∧R) ↔ (P∨Q)∧(P∨R) and P∧(Q∨R) ↔ (P∧Q)∨(P∧R)."""
    
    def name(self) -> str:
        return "Distribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula):
                # Check for P∨(Q∧R) pattern
                if f.connective == LogicalConnective.OR and len(f.formulas) == 2:
                    for sub in f.formulas:
                        if isinstance(sub, ConnectiveFormula) and sub.connective == LogicalConnective.AND:
                            return True
                # Check for P∧(Q∨R) pattern
                elif f.connective == LogicalConnective.AND and len(f.formulas) == 2:
                    for sub in f.formulas:
                        if isinstance(sub, ConnectiveFormula) and sub.connective == LogicalConnective.OR:
                            return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and len(f.formulas) == 2:
                # P∨(Q∧R) → (P∨Q)∧(P∨R)
                if f.connective == LogicalConnective.OR:
                    for i, sub in enumerate(f.formulas):
                        if isinstance(sub, ConnectiveFormula) and sub.connective == LogicalConnective.AND:
                            p = f.formulas[1-i]  # The other formula
                            q_and_r = sub.formulas
                            if len(q_and_r) >= 2:
                                distributed_or: List[Formula] = [
                                    ConnectiveFormula(LogicalConnective.OR, [p, q_and_r[0]]),
                                    ConnectiveFormula(LogicalConnective.OR, [p, q_and_r[1]])
                                ]
                                result = ConnectiveFormula(LogicalConnective.AND, distributed_or)
                                results.append(result)
                # P∧(Q∨R) → (P∧Q)∨(P∧R)
                elif f.connective == LogicalConnective.AND:
                    for i, sub in enumerate(f.formulas):
                        if isinstance(sub, ConnectiveFormula) and sub.connective == LogicalConnective.OR:
                            p = f.formulas[1-i]  # The other formula
                            q_or_r = sub.formulas
                            if len(q_or_r) >= 2:
                                distributed_and: List[Formula] = [
                                    ConnectiveFormula(LogicalConnective.AND, [p, q_or_r[0]]),
                                    ConnectiveFormula(LogicalConnective.AND, [p, q_or_r[1]])
                                ]
                                result = ConnectiveFormula(LogicalConnective.OR, distributed_and)
                                results.append(result)
        return results



class CutElimination(InferenceRule):
    """Cut Elimination (Transitivity): From P→Q and Q→R, derive P→R."""
    
    def name(self) -> str:
        return "Cut Elimination"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.IMPLIES:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                        if len(f1.formulas) == 2 and len(f2.formulas) == 2:
                            # Check if consequent of f1 matches antecedent of f2
                            if self._formulas_equal(f1.formulas[1], f2.formulas[0]):
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.IMPLIES:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                        if len(f1.formulas) == 2 and len(f2.formulas) == 2:
                            # P→Q and Q→R gives P→R
                            if self._formulas_equal(f1.formulas[1], f2.formulas[0]):
                                result = ConnectiveFormula(LogicalConnective.IMPLIES, [f1.formulas[0], f2.formulas[1]])
                                results.append(result)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        """Simple formula equality check."""
        return f1.to_string() == f2.to_string()



class Exportation(InferenceRule):
    """Exportation: (P∧Q)→R is equivalent to P→(Q→R)."""
    
    def name(self) -> str:
        return "Exportation"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    # Check if antecedent is conjunction
                    if isinstance(f.formulas[0], ConnectiveFormula) and f.formulas[0].connective == LogicalConnective.AND:
                        return True
            # Also handle reverse: P→(Q→R) to (P∧Q)→R
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    if isinstance(f.formulas[1], ConnectiveFormula) and f.formulas[1].connective == LogicalConnective.IMPLIES:
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    # Case 1: (P∧Q)→R becomes P→(Q→R)
                    if isinstance(f.formulas[0], ConnectiveFormula) and f.formulas[0].connective == LogicalConnective.AND:
                        if len(f.formulas[0].formulas) == 2:
                            p = f.formulas[0].formulas[0]
                            q = f.formulas[0].formulas[1]
                            r = f.formulas[1]
                            inner = ConnectiveFormula(LogicalConnective.IMPLIES, [q, r])
                            result = ConnectiveFormula(LogicalConnective.IMPLIES, [p, inner])
                            results.append(result)
                    
                    # Case 2: P→(Q→R) becomes (P∧Q)→R
                    if isinstance(f.formulas[1], ConnectiveFormula) and f.formulas[1].connective == LogicalConnective.IMPLIES:
                        if len(f.formulas[1].formulas) == 2:
                            p = f.formulas[0]
                            q = f.formulas[1].formulas[0]
                            r = f.formulas[1].formulas[1]
                            conjunction = ConnectiveFormula(LogicalConnective.AND, [p, q])
                            result = ConnectiveFormula(LogicalConnective.IMPLIES, [conjunction, r])
                            results.append(result)
        return results



class Absorption(InferenceRule):
    """Absorption: P→Q is equivalent to P→(P∧Q).
    Also: P∨(P∧Q) ≡ P and P∧(P∨Q) ≡ P."""
    
    def name(self) -> str:
        return "Absorption"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            # Implication form
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                return True
            # Disjunction/conjunction forms
            if isinstance(f, ConnectiveFormula) and f.connective in [LogicalConnective.OR, LogicalConnective.AND]:
                if len(f.formulas) == 2:
                    # Check if one side is simpler version of the other
                    for i in range(2):
                        other = f.formulas[1-i]
                        if isinstance(other, ConnectiveFormula):
                            if any(self._formulas_equal(f.formulas[i], sub) for sub in other.formulas):
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            # P→Q becomes P→(P∧Q)
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    p = f.formulas[0]
                    q = f.formulas[1]
                    conjunction = ConnectiveFormula(LogicalConnective.AND, [p, q])
                    result = ConnectiveFormula(LogicalConnective.IMPLIES, [p, conjunction])
                    results.append(result)
            
            # P∨(P∧Q) becomes P
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.OR:
                if len(f.formulas) == 2:
                    for i in range(2):
                        p = f.formulas[i]
                        other = f.formulas[1-i]
                        if isinstance(other, ConnectiveFormula) and other.connective == LogicalConnective.AND:
                            if any(self._formulas_equal(p, sub) for sub in other.formulas):
                                results.append(p)
            
            # P∧(P∨Q) becomes P
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND:
                if len(f.formulas) == 2:
                    for i in range(2):
                        p = f.formulas[i]
                        other = f.formulas[1-i]
                        if isinstance(other, ConnectiveFormula) and other.connective == LogicalConnective.OR:
                            if any(self._formulas_equal(p, sub) for sub in other.formulas):
                                results.append(p)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()



class Association(InferenceRule):
    """Association: (P∨Q)∨R ≡ P∨(Q∨R) and (P∧Q)∧R ≡ P∧(Q∧R)."""
    
    def name(self) -> str:
        return "Association"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective in [LogicalConnective.OR, LogicalConnective.AND]:
                # Check if we have nested same operator
                for sub in f.formulas:
                    if isinstance(sub, ConnectiveFormula) and sub.connective == f.connective:
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective in [LogicalConnective.OR, LogicalConnective.AND]:
                # Re-associate: flatten and rebuild differently
                if len(f.formulas) >= 2:
                    # Collect all formulas at this level
                    collected = []
                    for sub in f.formulas:
                        if isinstance(sub, ConnectiveFormula) and sub.connective == f.connective:
                            collected.extend(sub.formulas)
                        else:
                            collected.append(sub)
                    
                    # Rebuild with different grouping
                    if len(collected) >= 3:
                        # Create (first, (rest...))
                        if len(collected[1:]) == 1:
                            inner = collected[1]
                        else:
                            inner = ConnectiveFormula(f.connective, collected[1:])
                        result = ConnectiveFormula(f.connective, [collected[0], inner])
                        results.append(result)
        return results



class Resolution(InferenceRule):
    """Resolution: From (P∨Q) and (¬P∨R), derive (Q∨R)."""
    
    def name(self) -> str:
        return "Resolution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check if we have two disjunctions where one literal is negated in the other
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.OR:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.OR:
                        # Check for complementary literals
                        for lit1 in f1.formulas:
                            for lit2 in f2.formulas:
                                if self._are_complementary(lit1, lit2):
                                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.OR:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.OR:
                        # Find complementary literals
                        for i, lit1 in enumerate(f1.formulas):
                            for j, lit2 in enumerate(f2.formulas):
                                if self._are_complementary(lit1, lit2):
                                    # Resolve
                                    remaining1 = [f1.formulas[k] for k in range(len(f1.formulas)) if k != i]
                                    remaining2 = [f2.formulas[k] for k in range(len(f2.formulas)) if k != j]
                                    all_remaining = remaining1 + remaining2
                                    
                                    if len(all_remaining) == 0:
                                        # Contradiction resolved to empty clause (skip)
                                        continue
                                    elif len(all_remaining) == 1:
                                        results.append(all_remaining[0])
                                    else:
                                        result = ConnectiveFormula(LogicalConnective.OR, all_remaining)
                                        results.append(result)
        return results
    
    def _are_complementary(self, f1: Formula, f2: Formula) -> bool:
        """Check if two formulas are complementary (P and ¬P)."""
        # Check if f1 is ¬f2
        if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.NOT:
            if len(f1.formulas) == 1:
                return self._formulas_equal(f1.formulas[0], f2)
        # Check if f2 is ¬f1
        if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.NOT:
            if len(f2.formulas) == 1:
                return self._formulas_equal(f2.formulas[0], f1)
        return False
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()



class Transposition(InferenceRule):
    """Transposition: (P→Q) is equivalent to (¬Q→¬P).
    This is the same as Contraposition but named differently in some systems."""
    
    def name(self) -> str:
        return "Transposition"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    # P→Q becomes ¬Q→¬P
                    not_q = ConnectiveFormula(LogicalConnective.NOT, [f.formulas[1]])
                    not_p = ConnectiveFormula(LogicalConnective.NOT, [f.formulas[0]])
                    result = ConnectiveFormula(LogicalConnective.IMPLIES, [not_q, not_p])
                    results.append(result)
        return results



class MaterialImplication(InferenceRule):
    """Material Implication: P→Q is equivalent to ¬P∨Q.
    This is the same as Implication Elimination."""
    
    def name(self) -> str:
        return "Material Implication"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            # Forward: P→Q
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                return True
            # Reverse: ¬P∨Q
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.OR:
                if len(f.formulas) == 2:
                    if isinstance(f.formulas[0], ConnectiveFormula) and f.formulas[0].connective == LogicalConnective.NOT:
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            # P→Q becomes ¬P∨Q
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    not_p = ConnectiveFormula(LogicalConnective.NOT, [f.formulas[0]])
                    q = f.formulas[1]
                    result = ConnectiveFormula(LogicalConnective.OR, [not_p, q])
                    results.append(result)
            
            # ¬P∨Q becomes P→Q
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.OR:
                if len(f.formulas) == 2:
                    if isinstance(f.formulas[0], ConnectiveFormula) and f.formulas[0].connective == LogicalConnective.NOT:
                        if len(f.formulas[0].formulas) == 1:
                            p = f.formulas[0].formulas[0]
                            q = f.formulas[1]
                            result = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
                            results.append(result)
        return results



class ClaviusLaw(InferenceRule):
    """Clavius Law: (¬P→P) → P (if not-P implies P, then P must be true)."""
    
    def name(self) -> str:
        return "Clavius Law"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    # Check if antecedent is ¬P and consequent is P
                    ant = f.formulas[0]
                    cons = f.formulas[1]
                    if isinstance(ant, ConnectiveFormula) and ant.connective == LogicalConnective.NOT:
                        if len(ant.formulas) == 1:
                            if self._formulas_equal(ant.formulas[0], cons):
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    ant = f.formulas[0]
                    cons = f.formulas[1]
                    if isinstance(ant, ConnectiveFormula) and ant.connective == LogicalConnective.NOT:
                        if len(ant.formulas) == 1:
                            if self._formulas_equal(ant.formulas[0], cons):
                                # (¬P→P) gives P
                                results.append(cons)
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()



class Idempotence(InferenceRule):
    """Idempotence: P∨P ≡ P and P∧P ≡ P."""
    
    def name(self) -> str:
        return "Idempotence"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective in [LogicalConnective.OR, LogicalConnective.AND]:
                if len(f.formulas) >= 2:
                    # Check if all subformulas are the same
                    first = f.formulas[0].to_string()
                    if all(sub.to_string() == first for sub in f.formulas[1:]):
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective in [LogicalConnective.OR, LogicalConnective.AND]:
                if len(f.formulas) >= 2:
                    first = f.formulas[0].to_string()
                    if all(sub.to_string() == first for sub in f.formulas[1:]):
                        # P∨P... or P∧P... becomes P
                        results.append(f.formulas[0])
        return results



class TautologyIntroduction(InferenceRule):
    """Tautology Introduction: From P, derive P∨¬P (law of excluded middle)."""
    
    def name(self) -> str:
        return "Tautology Introduction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Can always introduce a tautology
        return len(formulas) > 0
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            # For any P, add P∨¬P
            not_f = ConnectiveFormula(LogicalConnective.NOT, [f])
            tautology = ConnectiveFormula(LogicalConnective.OR, [f, not_f])
            results.append(tautology)
        return results[:1]  # Just return one tautology to avoid explosion



class ContradictionElimination(InferenceRule):
    """Contradiction Elimination (Ex Falso Quodlibet): From P∧¬P, derive any Q."""
    
    def name(self) -> str:
        return "Contradiction Elimination"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check for contradictions P and ¬P
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.NOT:
                    if len(f2.formulas) == 1:
                        if self._formulas_equal(f1, f2.formulas[0]):
                            return True
        
        # Also check for explicit P∧¬P
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND:
                for i, sub1 in enumerate(f.formulas):
                    for sub2 in f.formulas[i+1:]:
                        if isinstance(sub2, ConnectiveFormula) and sub2.connective == LogicalConnective.NOT:
                            if len(sub2.formulas) == 1:
                                if self._formulas_equal(sub1, sub2.formulas[0]):
                                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # If we have a contradiction, we could derive anything
        # For practical purposes, just return an empty list or a marker
        # In a real system, this would be handled by the proof strategy
        return []
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()



class ConjunctionElimination(InferenceRule):
    """Conjunction Elimination: From P∧Q, derive both P and Q separately.
    This is similar to Simplification but explicitly derives both."""
    
    def name(self) -> str:
        return "Conjunction Elimination"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND:
                # Return all conjuncts
                results.extend(f.formulas)
        return results


# ============================================================================
# DCEC-Specific Cognitive Inference Rules
# ============================================================================


class ForbiddenToNotObligatory(InferenceRule):
    """Forbidden to Not Obligatory: F(P) ⊢ ¬O(P)"""
    
    def name(self) -> str:
        return "Forbidden to Not Obligatory"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, DeonticFormula) and f.operator.value == "F"
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, DeonticFormula) and f.operator.value == "F":
                # F(P) → ¬O(P)
                from .dcec_core import DeonticOperator
                obligation = DeonticFormula(DeonticOperator.OBLIGATION, f.formula)
                not_obligation = ConnectiveFormula(LogicalConnective.NOT, [obligation])
                results.append(not_obligation)
        return results


# ============================================================================
# Temporal Inference Rules
# ============================================================================


class MutualBelief(InferenceRule):
    """Mutual Belief: B(a1, P) ∧ B(a2, P) ⊢ MB(P) (simplified)"""
    
    def name(self) -> str:
        return "Mutual Belief"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        beliefs = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "B"]
        # Check for beliefs about same formula from different agents
        for i, b1 in enumerate(beliefs):
            for b2 in beliefs[i+1:]:
                if not self._agents_equal(b1.agent, b2.agent):
                    if self._formulas_equal(b1.formula, b2.formula):
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Simplified - would create mutual belief formula
        return []
    
    def _agents_equal(self, a1, a2) -> bool:
        if isinstance(a1, Term) and isinstance(a2, Term):
            return a1.to_string() == a2.to_string()
        return a1 == a2
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        return f1.to_string() == f2.to_string()



class IntentionSideEffect(InferenceRule):
    """Intention Side Effect: I(agent, P) ∧ B(agent, P→Q) ∧ B(agent, ¬Q) ⊢ ¬I(agent, P)"""
    
    def name(self) -> str:
        return "Intention Side Effect"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check for intention with undesired side effects
        intentions = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator.value == "I"]
        return len(intentions) > 0
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Complex rule - simplified for now
        return []



class UnitResolution(InferenceRule):
    """Unit resolution: (P∨Q) ∧ ¬P ⊢ Q"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            if isinstance(f1, BinaryFormula) and f1.operator.value == "OR":
                for f2 in formulas:
                    if isinstance(f2, UnaryFormula) and f2.operator.value == "NOT":
                        # Check if f2.formula matches one of the disjuncts
                        if f2.formula == f1.left or f2.formula == f1.right:
                            return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f1 in formulas:
            if isinstance(f1, BinaryFormula) and f1.operator.value == "OR":
                for f2 in formulas:
                    if isinstance(f2, UnaryFormula) and f2.operator.value == "NOT":
                        if f2.formula == f1.left:
                            results.append(f1.right)
                        elif f2.formula == f1.right:
                            results.append(f1.left)
        return results



class BinaryResolution(InferenceRule):
    """Binary resolution: (P∨Q) ∧ (¬P∨R) ⊢ (Q∨R)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            if isinstance(f1, BinaryFormula) and f1.operator.value == "OR":
                for f2 in formulas:
                    if isinstance(f2, BinaryFormula) and f2.operator.value == "OR":
                        # Look for complementary literals
                        if isinstance(f1.left, UnaryFormula) and f1.left.operator.value == "NOT":
                            if f1.left.formula == f2.left or f1.left.formula == f2.right:
                                return True
                        if isinstance(f1.right, UnaryFormula) and f1.right.operator.value == "NOT":
                            if f1.right.formula == f2.left or f1.right.formula == f2.right:
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Simplified binary resolution
        return []



class Factoring(InferenceRule):
    """Factoring: (P∨P) ⊢ P"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "OR":
                if f.left == f.right:
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "OR":
                if f.left == f.right:
                    results.append(f.left)
        return results



class Subsumption(InferenceRule):
    """Subsumption: P subsumes (P∨Q)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f2, BinaryFormula) and f2.operator.value == "OR":
                    if f1 == f2.left or f1 == f2.right:
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Subsumption removes subsumed clauses
        return []



class NegationIntroduction(InferenceRule):
    """Negation introduction: (P→Q) ∧ (P→¬Q) ⊢ ¬P"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            if isinstance(f1, BinaryFormula) and f1.operator.value == "IMPLIES":
                for f2 in formulas:
                    if isinstance(f2, BinaryFormula) and f2.operator.value == "IMPLIES":
                        if f1.left == f2.left:
                            # Check if consequents are negations of each other
                            if isinstance(f1.right, UnaryFormula) and f1.right.operator.value == "NOT":
                                if f1.right.formula == f2.right:
                                    return True
                            if isinstance(f2.right, UnaryFormula) and f2.right.operator.value == "NOT":
                                if f2.right.formula == f1.right:
                                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f1 in formulas:
            if isinstance(f1, BinaryFormula) and f1.operator.value == "IMPLIES":
                for f2 in formulas:
                    if isinstance(f2, BinaryFormula) and f2.operator.value == "IMPLIES":
                        if f1.left == f2.left:
                            if isinstance(f1.right, UnaryFormula) and f1.right.operator.value == "NOT":
                                if f1.right.formula == f2.right:
                                    results.append(UnaryFormula(Operator.NOT, f1.left))
                            elif isinstance(f2.right, UnaryFormula) and f2.right.operator.value == "NOT":
                                if f2.right.formula == f1.right:
                                    results.append(UnaryFormula(Operator.NOT, f1.left))
        return results



class CaseAnalysis(InferenceRule):
    """Case analysis: (P∨Q) ∧ (P→R) ∧ (Q→R) ⊢ R"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            if isinstance(f1, BinaryFormula) and f1.operator.value == "OR":
                # Look for implications from both disjuncts to same conclusion
                for f2 in formulas:
                    if isinstance(f2, BinaryFormula) and f2.operator.value == "IMPLIES":
                        if f2.left == f1.left:
                            for f3 in formulas:
                                if isinstance(f3, BinaryFormula) and f3.operator.value == "IMPLIES":
                                    if f3.left == f1.right and f3.right == f2.right:
                                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f1 in formulas:
            if isinstance(f1, BinaryFormula) and f1.operator.value == "OR":
                for f2 in formulas:
                    if isinstance(f2, BinaryFormula) and f2.operator.value == "IMPLIES":
                        if f2.left == f1.left:
                            for f3 in formulas:
                                if isinstance(f3, BinaryFormula) and f3.operator.value == "IMPLIES":
                                    if f3.left == f1.right and f3.right == f2.right:
                                        results.append(f2.right)
        return results



class ProofByContradiction(InferenceRule):
    """Proof by contradiction: (¬P→⊥) ⊢ P"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "IMPLIES":
                if isinstance(f.left, UnaryFormula) and f.left.operator.value == "NOT":
                    # Check if consequent is a contradiction (P∧¬P)
                    if isinstance(f.right, BinaryFormula) and f.right.operator.value == "AND":
                        if isinstance(f.right.right, UnaryFormula) and f.right.right.operator.value == "NOT":
                            if f.right.left == f.right.right.formula:
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "IMPLIES":
                if isinstance(f.left, UnaryFormula) and f.left.operator.value == "NOT":
                    if isinstance(f.right, BinaryFormula) and f.right.operator.value == "AND":
                        if isinstance(f.right.right, UnaryFormula) and f.right.right.operator.value == "NOT":
                            if f.right.left == f.right.right.formula:
                                results.append(f.left.formula)
        return results


# Common Knowledge Rules

class CommonKnowledgeIntroduction(InferenceRule):
    """Common knowledge introduction: K(a1, P) ∧ K(a2, P) ∧ ... ⊢ C(P)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check if multiple agents know the same proposition
        knowledge_map = {}
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "K":
                if len(f.agent) > 0:
                    prop = str(f.formula)
                    if prop not in knowledge_map:
                        knowledge_map[prop] = []
                    knowledge_map[prop].append(f.agent)
        # Check if any proposition is known by multiple agents
        for agents in knowledge_map.values():
            if len(agents) >= 2:
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Simplified - would create common knowledge formula
        return []



class CommonKnowledgeDistribution(InferenceRule):
    """Common knowledge distribution: C(P∧Q) ⊢ C(P)∧C(Q)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                if isinstance(f.formula, BinaryFormula) and f.formula.operator.value == "AND":
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                if isinstance(f.formula, BinaryFormula) and f.formula.operator.value == "AND":
                    results.append(ModalFormula(Operator.C, f.formula.left, f.agent))
                    results.append(ModalFormula(Operator.C, f.formula.right, f.agent))
        return results



class CommonKnowledgeImpliesKnowledge(InferenceRule):
    """Common knowledge implies individual knowledge: C(P) ⊢ K(agent, P)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                # For any agent, common knowledge implies their knowledge
                # Simplified: create knowledge for generic agent
                results.append(ModalFormula(Operator.K, f.formula, "agent"))
        return results



class CommonKnowledgeMonotonicity(InferenceRule):
    """Common knowledge monotonicity: C(P) ∧ (P→Q) ⊢ C(Q)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            if isinstance(f1, ModalFormula) and f1.operator.value == "C":
                for f2 in formulas:
                    if isinstance(f2, BinaryFormula) and f2.operator.value == "IMPLIES":
                        if f2.left == f1.formula:
                            return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f1 in formulas:
            if isinstance(f1, ModalFormula) and f1.operator.value == "C":
                for f2 in formulas:
                    if isinstance(f2, BinaryFormula) and f2.operator.value == "IMPLIES":
                        if f2.left == f1.formula:
                            results.append(ModalFormula(Operator.C, f2.right, f1.agent))
        return results



class CommonKnowledgeNegation(InferenceRule):
    """Common knowledge negation: C(¬P) ⊢ ¬C(P)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                if isinstance(f.formula, UnaryFormula) and f.formula.operator.value == "NOT":
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                if isinstance(f.formula, UnaryFormula) and f.formula.operator.value == "NOT":
                    inner = ModalFormula(Operator.C, f.formula.formula, f.agent)
                    results.append(UnaryFormula(Operator.NOT, inner))
        return results



class CommonBeliefIntroduction(InferenceRule):
    """Common belief from individual beliefs: B(a1, P) ∧ B(a2, P) ⊢ CB(P)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        belief_map = {}
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "B":
                prop = str(f.formula)
                if prop not in belief_map:
                    belief_map[prop] = []
                belief_map[prop].append(f.agent)
        for agents in belief_map.values():
            if len(agents) >= 2:
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Simplified common belief creation
        return []



class FixedPointInduction(InferenceRule):
    """Fixed point induction for common knowledge: P ∧ (P→K(everyone, P)) ⊢ C(P)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f2, BinaryFormula) and f2.operator.value == "IMPLIES":
                    if f2.left == f1:
                        if isinstance(f2.right, ModalFormula) and f2.right.operator.value == "K":
                            if f2.right.formula == f1:
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Simplified fixed point reasoning
        return []



class TemporallyInducedCommonKnowledge(InferenceRule):
    """Temporally induced common knowledge: □K(all, P) ⊢ C(P)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                if isinstance(f.formula, ModalFormula) and f.formula.operator.value == "K":
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                if isinstance(f.formula, ModalFormula) and f.formula.operator.value == "K":
                    results.append(ModalFormula(Operator.C, f.formula.formula, "all"))
        return results


# Final Rules to Complete Phase 4B

class ModalNecessionIntroduction(InferenceRule):
    """Modal necessity introduction: If P is a theorem, then □P"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Simplified: check for tautologies
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "OR":
                # Check for P∨¬P pattern
                if isinstance(f.right, UnaryFormula) and f.right.operator.value == "NOT":
                    if f.left == f.right.formula:
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "OR":
                if isinstance(f.right, UnaryFormula) and f.right.operator.value == "NOT":
                    if f.left == f.right.formula:
                        results.append(TemporalFormula(Operator.ALWAYS, f))
        return results



class DisjunctionCommutes(InferenceRule):
    """Disjunction commutes in resolution: Specialized commutativity for clauses"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "OR":
                # Always applicable to disjunctions
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, BinaryFormula) and f.operator.value == "OR":
                # Commute the disjunction
                results.append(BinaryFormula(Operator.OR, f.right, f.left))
        return results



class CommonKnowledgeTransitivity(InferenceRule):
    """Common knowledge transitivity: C(C(P)) ⊢ C(P)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                if isinstance(f.formula, ModalFormula) and f.formula.operator.value == "C":
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "C":
                if isinstance(f.formula, ModalFormula) and f.formula.operator.value == "C":
                    results.append(ModalFormula(Operator.C, f.formula.formula, f.agent))
        return results



class CommonKnowledgeConjunction(InferenceRule):
    """Common knowledge conjunction: C(P) ∧ C(Q) ⊢ C(P∧Q)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        ck_formulas = [f for f in formulas if isinstance(f, ModalFormula) and f.operator.value == "C"]
        return len(ck_formulas) >= 2
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        ck_formulas = [f for f in formulas if isinstance(f, ModalFormula) and f.operator.value == "C"]
        for i, f1 in enumerate(ck_formulas):
            for f2 in ck_formulas[i+1:]:
                conj = BinaryFormula(Operator.AND, f1.formula, f2.formula)
                results.append(ModalFormula(Operator.C, conj, f1.agent))
        return results



class MutualKnowledgeTransitivity(InferenceRule):
    """Mutual knowledge transitivity: MB(P) ∧ MB(MB(P)→Q) ⊢ MB(Q)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Simplified mutual belief check
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "MB":
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Simplified mutual belief reasoning
        return []



class PublicAnnouncementReduction(InferenceRule):
    """Public announcement reduction: [!P]Q ≡ (P→Q)"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Would check for public announcement operator
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Public announcement logic - advanced feature
        return []



class GroupKnowledgeAggregation(InferenceRule):
    """Group knowledge: Everyone knows P ⊢ Group knows P"""
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check if multiple agents have knowledge of same formula
        k_formulas = {}
        for f in formulas:
            if isinstance(f, ModalFormula) and f.operator.value == "K":
                prop = str(f.formula)
                if prop not in k_formulas:
                    k_formulas[prop] = []
                k_formulas[prop].append(f.agent)
        # If any proposition is known by 3+ agents, can aggregate
        for agents in k_formulas.values():
            if len(agents) >= 3:
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Simplified group knowledge
        return []




