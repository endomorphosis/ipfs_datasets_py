"""
Cognitive Logic Inference Rules for DCEC.

This module contains inference rules for cognitive operators including:
- Belief (B): What an agent believes
- Knowledge (K): What an agent knows (justified true belief)
- Intention (I): What an agent intends to do
- Perception (P): What an agent directly observes
- Common Knowledge (C): What all agents know and know that others know

These rules are fundamental to multi-agent systems and theory of mind reasoning.
"""

from typing import List, Optional
from ..dcec_core import (
    Formula,
    CognitiveFormula,
    ConnectiveFormula,
    LogicalConnective,
    CognitiveOperator,
)
from ..exceptions import CECError
from .base import InferenceRule


class BeliefDistribution(InferenceRule):
    """
    Distributes conjunction over belief operator.
    
    Rule: B(agent, P∧Q) ⊢ B(agent, P) ∧ B(agent, Q)
    
    If an agent believes (P and Q), then the agent believes P and the agent believes Q.
    
    Example:
        If Alice believes "it's raining and cold",
        then Alice believes "it's raining" and Alice believes "it's cold".
    """
    
    def name(self) -> str:
        return "BeliefDistribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have B(agent, P∧Q)."""
        for formula in formulas:
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.BELIEF and
                isinstance(formula.formula, ConnectiveFormula) and
                formula.formula.connective == LogicalConnective.AND):
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply belief distribution: B(agent, P∧Q) → B(agent, P) ∧ B(agent, Q)."""
        for formula in formulas:
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.BELIEF and
                isinstance(formula.formula, ConnectiveFormula) and
                formula.formula.connective == LogicalConnective.AND and
                len(formula.formula.formulas) >= 2):
                agent = formula.agent
                p = formula.formula.formulas[0]
                q = formula.formula.formulas[1]
                return [
                    CognitiveFormula(CognitiveOperator.BELIEF, agent, p),
                    CognitiveFormula(CognitiveOperator.BELIEF, agent, q),
                ]
        return []


class KnowledgeImpliesBelief(InferenceRule):
    """
    Knowledge is stronger than belief.
    
    Rule: K(agent, P) ⊢ B(agent, P)
    
    If an agent knows P, then the agent believes P.
    Knowledge implies belief (but not vice versa).
    
    Example:
        If Alice knows "2+2=4", then Alice believes "2+2=4".
    """
    
    def name(self) -> str:
        return "KnowledgeImpliesBelief"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have K(agent, P)."""
        for formula in formulas:
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.KNOWLEDGE):
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply knowledge→belief: K(agent, P) → B(agent, P)."""
        for formula in formulas:
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.KNOWLEDGE):
                return [CognitiveFormula(CognitiveOperator.BELIEF, formula.agent, formula.formula)]
        return []


class BeliefMonotonicity(InferenceRule):
    """
    Monotonicity of belief under implication.
    
    Rule: B(agent, P) ∧ (P→Q) ⊢ B(agent, Q)
    
    If an agent believes P and (P implies Q), then the agent believes Q.
    Beliefs are closed under logical consequence.
    
    Example:
        If Alice believes "it's raining" and "raining→wet",
        then Alice believes "it's wet".
    """
    
    def name(self) -> str:
        return "BeliefMonotonicity"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have B(agent, P) and (P→Q)."""
        has_belief = any(
            isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.BELIEF
            for f in formulas
        )
        has_implication = any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES
            for f in formulas
        )
        return has_belief and has_implication
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply belief monotonicity: B(agent, P) ∧ (P→Q) → B(agent, Q)."""
        for f_belief in [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.BELIEF]:
            for f_impl in [f for f in formulas if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES and len(f.formulas) == 2]:
                if f_impl.formulas[0] == f_belief.formula:
                    return [CognitiveFormula(CognitiveOperator.BELIEF, f_belief.agent, f_impl.formulas[1])]
        return []


class IntentionCommitment(InferenceRule):
    """
    Intention follows from means-ends belief.
    
    Rule: I(agent, P) ∧ B(agent, P→Q) ⊢ I(agent, Q)
    
    If an agent intends P and believes (P implies Q), then the agent intends Q.
    Agents are committed to the logical consequences of their intentions.
    
    Example:
        If Alice intends to "go to the store" and believes 
        "going to store→buying milk", then Alice intends to "buy milk".
    """
    
    def name(self) -> str:
        return "IntentionCommitment"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have I(agent, P) and B(agent, P→Q)."""
        has_intention = False
        has_belief_implication = False
        
        for formula in formulas:
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.INTENTION):
                has_intention = True
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.BELIEF and
                isinstance(formula.formula, ConnectiveFormula) and
                formula.formula.connective == LogicalConnective.IMPLIES):
                has_belief_implication = True
        
        return has_intention and has_belief_implication
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply intention commitment: I(agent, P) ∧ B(agent, P→Q) → I(agent, Q)."""
        for f_int in [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.INTENTION]:
            for f_bel in [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.BELIEF]:
                if (isinstance(f_bel.formula, ConnectiveFormula) and
                        f_bel.formula.connective == LogicalConnective.IMPLIES and
                        len(f_bel.formula.formulas) == 2 and
                        f_bel.formula.formulas[0] == f_int.formula):
                    return [CognitiveFormula(CognitiveOperator.INTENTION, f_int.agent, f_bel.formula.formulas[1])]
        return []


class BeliefConjunction(InferenceRule):
    """
    Combines beliefs into conjunction.
    
    Rule: B(agent, P) ∧ B(agent, Q) ⊢ B(agent, P∧Q)
    
    If an agent believes P and believes Q, then the agent believes (P and Q).
    
    Example:
        If Alice believes "it's raining" and Alice believes "it's cold",
        then Alice believes "it's raining and cold".
    """
    
    def name(self) -> str:
        return "BeliefConjunction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have at least two beliefs by the same agent."""
        beliefs = [f for f in formulas if
                  isinstance(f, CognitiveFormula) and
                  f.operator == CognitiveOperator.BELIEF]
        return len(beliefs) >= 2
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply belief conjunction: B(agent, P) ∧ B(agent, Q) → B(agent, P∧Q)."""
        beliefs = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.BELIEF]
        if len(beliefs) >= 2:
            agent = beliefs[0].agent
            p = beliefs[0].formula
            q = beliefs[1].formula
            return [CognitiveFormula(CognitiveOperator.BELIEF, agent, ConnectiveFormula(LogicalConnective.AND, [p, q]))]
        return []


class KnowledgeDistribution(InferenceRule):
    """
    Distributes conjunction over knowledge operator.
    
    Rule: K(agent, P∧Q) ⊢ K(agent, P) ∧ K(agent, Q)
    
    If an agent knows (P and Q), then the agent knows P and the agent knows Q.
    
    Example:
        If Alice knows "2+2=4 and 3+3=6",
        then Alice knows "2+2=4" and Alice knows "3+3=6".
    """
    
    def name(self) -> str:
        return "KnowledgeDistribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have K(agent, P∧Q)."""
        for formula in formulas:
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.KNOWLEDGE and
                isinstance(formula.formula, ConnectiveFormula) and
                formula.formula.connective == LogicalConnective.AND):
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply knowledge distribution: K(agent, P∧Q) → K(agent, P) ∧ K(agent, Q)."""
        for formula in formulas:
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.KNOWLEDGE and
                isinstance(formula.formula, ConnectiveFormula) and
                formula.formula.connective == LogicalConnective.AND and
                len(formula.formula.formulas) >= 2):
                agent = formula.agent
                p = formula.formula.formulas[0]
                q = formula.formula.formulas[1]
                return [
                    CognitiveFormula(CognitiveOperator.KNOWLEDGE, agent, p),
                    CognitiveFormula(CognitiveOperator.KNOWLEDGE, agent, q),
                ]
        return []


class IntentionMeansEnd(InferenceRule):
    """
    Means-end reasoning for intentions.
    
    Rule: I(agent, goal) ∧ B(agent, action→goal) ⊢ I(agent, action)
    
    If an agent intends a goal and believes an action achieves the goal,
    then the agent intends the action (means-end reasoning).
    
    Example:
        If Alice intends to "be at work by 9am" and believes 
        "taking the 8am bus→being at work by 9am",
        then Alice intends to "take the 8am bus".
    """
    
    def name(self) -> str:
        return "IntentionMeansEnd"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have I(agent, goal) and B(agent, action→goal)."""
        has_intention = False
        has_belief_means = False
        
        for formula in formulas:
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.INTENTION):
                has_intention = True
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.BELIEF and
                isinstance(formula.formula, ConnectiveFormula) and
                formula.formula.connective == LogicalConnective.IMPLIES):
                has_belief_means = True
        
        return has_intention and has_belief_means
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply means-end reasoning: I(agent, goal) ∧ B(agent, action→goal) → I(agent, action)."""
        for f_int in [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.INTENTION]:
            for f_bel in [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.BELIEF]:
                if (isinstance(f_bel.formula, ConnectiveFormula) and
                        f_bel.formula.connective == LogicalConnective.IMPLIES and
                        len(f_bel.formula.formulas) == 2 and
                        f_bel.formula.formulas[1] == f_int.formula):
                    return [CognitiveFormula(CognitiveOperator.INTENTION, f_int.agent, f_bel.formula.formulas[0])]
        return []


class PerceptionImpliesKnowledge(InferenceRule):
    """
    Direct perception leads to knowledge.
    
    Rule: P(agent, φ) ⊢ K(agent, φ)
    
    If an agent directly perceives φ, then the agent knows φ.
    Direct observation provides knowledge (assuming reliable perception).
    
    Example:
        If Alice perceives "the light is on",
        then Alice knows "the light is on".
    """
    
    def name(self) -> str:
        return "PerceptionImpliesKnowledge"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have P(agent, φ)."""
        for formula in formulas:
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.PERCEPTION):
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply perception→knowledge: P(agent, φ) → K(agent, φ)."""
        for formula in formulas:
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.PERCEPTION):
                return [CognitiveFormula(CognitiveOperator.KNOWLEDGE, formula.agent, formula.formula)]
        return []


class BeliefNegation(InferenceRule):
    """
    Handles negation in beliefs.
    
    Rule: B(agent, ¬P) ⊢ ¬B(agent, P)
    
    If an agent believes not-P, then the agent does not believe P.
    (Note: This is a simplification; in general doxastic logic this doesn't always hold)
    
    Example:
        If Alice believes "it's not raining",
        then Alice does not believe "it's raining".
    """
    
    def name(self) -> str:
        return "BeliefNegation"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have B(agent, ¬P)."""
        for formula in formulas:
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.BELIEF and
                isinstance(formula.formula, ConnectiveFormula) and
                formula.formula.connective == LogicalConnective.NOT):
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply belief negation: B(agent, ¬P) → ¬B(agent, P)."""
        for formula in formulas:
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.BELIEF and
                isinstance(formula.formula, ConnectiveFormula) and
                formula.formula.connective == LogicalConnective.NOT and
                len(formula.formula.formulas) == 1):
                p = formula.formula.formulas[0]
                belief_p = CognitiveFormula(CognitiveOperator.BELIEF, formula.agent, p)
                return [ConnectiveFormula(LogicalConnective.NOT, [belief_p])]
        return []


class KnowledgeConjunction(InferenceRule):
    """
    Combines knowledge into conjunction.
    
    Rule: K(agent, P) ∧ K(agent, Q) ⊢ K(agent, P∧Q)
    
    If an agent knows P and knows Q, then the agent knows (P and Q).
    
    Example:
        If Alice knows "2+2=4" and Alice knows "3+3=6",
        then Alice knows "2+2=4 and 3+3=6".
    """
    
    def name(self) -> str:
        return "KnowledgeConjunction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have at least two knowledge statements by the same agent."""
        knowledge_formulas = [f for f in formulas if
                            isinstance(f, CognitiveFormula) and
                            f.operator == CognitiveOperator.KNOWLEDGE]
        return len(knowledge_formulas) >= 2
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply knowledge conjunction: K(agent, P) ∧ K(agent, Q) → K(agent, P∧Q)."""
        knowledge = [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.KNOWLEDGE]
        if len(knowledge) >= 2:
            agent = knowledge[0].agent
            p = knowledge[0].formula
            q = knowledge[1].formula
            return [CognitiveFormula(CognitiveOperator.KNOWLEDGE, agent, ConnectiveFormula(LogicalConnective.AND, [p, q]))]
        return []


class IntentionPersistence(InferenceRule):
    """
    Intentions persist until believed to be achieved.
    
    Rule: I(agent, P) ∧ ¬B(agent, P) ⊢ I(agent, P)'
    
    If an agent intends P and does not believe P (not yet achieved),
    then the agent continues to intend P in the next state.
    
    Example:
        If Alice intends to "go to the store" and doesn't believe 
        she's at the store yet, she continues intending to go.
    """
    
    def name(self) -> str:
        return "IntentionPersistence"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have I(agent, P) and ¬B(agent, P)."""
        has_intention = False
        has_not_belief = False
        
        for formula in formulas:
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.INTENTION):
                has_intention = True
            # Check for negated belief: ConnectiveFormula(NOT, [CognitiveFormula(BELIEF, ...)])
            if (isinstance(formula, ConnectiveFormula) and
                formula.connective == LogicalConnective.NOT and
                len(formula.formulas) == 1 and
                isinstance(formula.formulas[0], CognitiveFormula) and
                formula.formulas[0].operator == CognitiveOperator.BELIEF):
                has_not_belief = True
        
        return has_intention and has_not_belief
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply intention persistence: I(agent, P) ∧ ¬B(agent, P) → I(agent, P)'."""
        has_not_belief = any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.NOT and
            len(f.formulas) == 1 and isinstance(f.formulas[0], CognitiveFormula) and
            f.formulas[0].operator == CognitiveOperator.BELIEF
            for f in formulas
        )
        if not has_not_belief:
            return []
        for formula in formulas:
            if (isinstance(formula, CognitiveFormula) and
                formula.operator == CognitiveOperator.INTENTION):
                return [formula]
        return []


class BeliefRevision(InferenceRule):
    """
    Updates belief based on perception.
    
    Rule: B(agent, P) ∧ P(agent, ¬P) ⊢ B(agent, ¬P)
    
    If an agent believes P but then perceives not-P,
    the agent revises their belief to not-P (perception overrides belief).
    
    Example:
        If Alice believed "the light is off" but then perceives 
        "the light is on", she revises to believe "the light is on".
    """
    
    def name(self) -> str:
        return "BeliefRevision"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have B(agent, P) and P(agent, ¬P)."""
        has_belief = any(
            isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.BELIEF
            for f in formulas
        )
        has_contradictory_perception = any(
            isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.PERCEPTION
            for f in formulas
        )
        return has_belief and has_contradictory_perception
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply belief revision: B(agent, P) ∧ P(agent, ¬P) → B(agent, ¬P)."""
        for f_bel in [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.BELIEF]:
            for f_per in [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.PERCEPTION]:
                if (isinstance(f_per.formula, ConnectiveFormula) and
                        f_per.formula.connective == LogicalConnective.NOT and
                        len(f_per.formula.formulas) == 1 and
                        f_per.formula.formulas[0] == f_bel.formula):
                    return [CognitiveFormula(CognitiveOperator.BELIEF, f_bel.agent, f_per.formula)]
        return []


class KnowledgeMonotonicity(InferenceRule):
    """
    Monotonicity of knowledge under implication.
    
    Rule: K(agent, P) ∧ (P→Q) ⊢ K(agent, Q)
    
    If an agent knows P and (P implies Q), then the agent knows Q.
    Knowledge is closed under logical consequence.
    
    Example:
        If Alice knows "all humans are mortal" and "Socrates is human",
        and "Socrates is human→Socrates is mortal",
        then Alice knows "Socrates is mortal".
    """
    
    def name(self) -> str:
        return "KnowledgeMonotonicity"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have K(agent, P) and (P→Q)."""
        has_knowledge = any(
            isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.KNOWLEDGE
            for f in formulas
        )
        has_implication = any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES
            for f in formulas
        )
        return has_knowledge and has_implication
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply knowledge monotonicity: K(agent, P) ∧ (P→Q) → K(agent, Q)."""
        for f_know in [f for f in formulas if isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.KNOWLEDGE]:
            for f_impl in [f for f in formulas if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES and len(f.formulas) == 2]:
                if f_impl.formulas[0] == f_know.formula:
                    return [CognitiveFormula(CognitiveOperator.KNOWLEDGE, f_know.agent, f_impl.formulas[1])]
        return []


# Export all cognitive rules
__all__ = [
    'BeliefDistribution',
    'KnowledgeImpliesBelief',
    'BeliefMonotonicity',
    'IntentionCommitment',
    'BeliefConjunction',
    'KnowledgeDistribution',
    'IntentionMeansEnd',
    'PerceptionImpliesKnowledge',
    'BeliefNegation',
    'KnowledgeConjunction',
    'IntentionPersistence',
    'BeliefRevision',
    'KnowledgeMonotonicity',
]
