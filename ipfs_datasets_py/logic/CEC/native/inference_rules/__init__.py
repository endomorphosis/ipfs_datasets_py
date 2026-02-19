"""
Inference rules package for DCEC theorem proving.

This package contains all inference rules organized by category:
- base: Base classes and enums
- propositional: Basic propositional logic rules (10 rules)
- temporal: Temporal reasoning rules (15 rules)
- deontic: Deontic logic rules (7 rules)
- cognitive: Cognitive operator rules (13 rules)
- modal: Modal logic rules (5 rules)
- resolution: Resolution-based rules (7 rules)
- specialized: Advanced and specialized rules (10 rules)

Total: 67 inference rules + base classes
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
from .modal import (
    NecessityElimination,
    PossibilityIntroduction,
    NecessityDistribution,
    PossibilityDuality,
    NecessityConjunction,
)
from .resolution import (
    ResolutionRule,
    UnitResolutionRule,
    FactoringRule,
    SubsumptionRule,
    CaseAnalysisRule,
    ProofByContradictionRule,
)
from .specialized import (
    BiconditionalIntroduction,
    BiconditionalElimination,
    ConstructiveDilemma,
    DestructiveDilemma,
    ExportationRule,
    AbsorptionRule,
    AdditionRule,
    TautologyRule,
    CommutativityConjunction,
)

__all__ = [
    # Base
    'ProofResult',
    'InferenceRule',
    # Propositional (10 rules)
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
    # Temporal (15 rules)
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
    # Deontic (7 rules)
    'ObligationDistribution',
    'ObligationImplication',
    'PermissionFromNonObligation',
    'ObligationConjunction',
    'PermissionDistribution',
    'ObligationConsistency',
    'ProhibitionEquivalence',
    # Cognitive (13 rules)
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
    # Modal (5 rules)
    'NecessityElimination',
    'PossibilityIntroduction',
    'NecessityDistribution',
    'PossibilityDuality',
    'NecessityConjunction',
    # Resolution (6 rules)
    'ResolutionRule',
    'UnitResolutionRule',
    'FactoringRule',
    'SubsumptionRule',
    'CaseAnalysisRule',
    'ProofByContradictionRule',
    # Specialized (9 rules)
    'BiconditionalIntroduction',
    'BiconditionalElimination',
    'ConstructiveDilemma',
    'DestructiveDilemma',
    'ExportationRule',
    'AbsorptionRule',
    'AdditionRule',
    'TautologyRule',
    'CommutativityConjunction',
]
