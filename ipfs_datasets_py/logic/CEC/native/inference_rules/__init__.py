"""
Inference rules package for DCEC theorem proving.

This package contains all inference rules organized by category:
- base: Base classes and enums
- propositional: Basic propositional logic rules
- first_order: Quantifier rules
- temporal: Temporal reasoning rules
- deontic: Deontic logic rules
- modal: Modal logic rules
- cognitive: Cognitive operator rules
- specialized: Advanced and specialized rules
"""

from .base import ProofResult, InferenceRule
from .propositional import (
    ModusPonens,
    Simplification,
    ConjunctionIntroduction,
    Weakening,
    DeMorgan,
    DoubleNegation,
    DisjunctiveSyllogism,
    Contraposition,
    HypotheticalSyllogism,
    ImplicationElimination,
)
from .temporal import (
    AlwaysDistribution,
    AlwaysImplication,
    AlwaysTransitive,
    AlwaysImpliesNext,
    AlwaysInduction,
    EventuallyFromAlways,
    EventuallyDistribution,
    EventuallyTransitive,
    EventuallyImplication,
    NextDistribution,
    NextImplication,
    UntilWeakening,
    SinceWeakening,
    TemporalUntilElimination,
    TemporalNegation,
)
from .deontic import (
    ObligationDistribution,
    ObligationImplication,
    PermissionFromNonObligation,
    ObligationConjunction,
    PermissionDistribution,
    ObligationConsistency,
    ProhibitionEquivalence,
)
from .cognitive import (
    BeliefDistribution,
    KnowledgeImpliesBelief,
    BeliefMonotonicity,
    IntentionCommitment,
    BeliefConjunction,
    KnowledgeDistribution,
    IntentionMeansEnd,
    PerceptionImpliesKnowledge,
    BeliefNegation,
    KnowledgeConjunction,
    IntentionPersistence,
    BeliefRevision,
    KnowledgeMonotonicity,
)

__all__ = [
    # Base
    'ProofResult',
    'InferenceRule',
    # Propositional
    'ModusPonens',
    'Simplification',
    'ConjunctionIntroduction',
    'Weakening',
    'DeMorgan',
    'DoubleNegation',
    'DisjunctiveSyllogism',
    'Contraposition',
    'HypotheticalSyllogism',
    'ImplicationElimination',
    # Temporal
    'AlwaysDistribution',
    'AlwaysImplication',
    'AlwaysTransitive',
    'AlwaysImpliesNext',
    'AlwaysInduction',
    'EventuallyFromAlways',
    'EventuallyDistribution',
    'EventuallyTransitive',
    'EventuallyImplication',
    'NextDistribution',
    'NextImplication',
    'UntilWeakening',
    'SinceWeakening',
    'TemporalUntilElimination',
    'TemporalNegation',
    # Deontic
    'ObligationDistribution',
    'ObligationImplication',
    'PermissionFromNonObligation',
    'ObligationConjunction',
    'PermissionDistribution',
    'ObligationConsistency',
    'ProhibitionEquivalence',
    # Cognitive
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
