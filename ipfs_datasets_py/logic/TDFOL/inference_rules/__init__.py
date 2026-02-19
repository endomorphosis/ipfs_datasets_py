"""
TDFOL Inference Rules Package

This package contains all inference rules for TDFOL theorem proving, organized into
logical categories for better maintainability and discoverability.

Modules:
- base: Abstract base class (TDFOLInferenceRule)
- propositional: 13 propositional logic rules
- first_order: 2 first-order logic rules (quantifiers)
- temporal: 20 temporal logic rules (LTL operators)
- deontic: 16 deontic logic rules (SDL operators)
- temporal_deontic: 9 combined temporal-deontic rules

Total: 60 inference rules

Usage:
    >>> from ipfs_datasets_py.logic.TDFOL.inference_rules import ModusPonensRule
    >>> rule = ModusPonensRule()
    >>> # Or import from old location (backward compatible):
    >>> from ipfs_datasets_py.logic.TDFOL.tdfol_inference_rules import ModusPonensRule

Author: TDFOL Team
Date: 2026-02-19
Phase: 2 (Architecture Improvements)
Task: 2.1 (Split Inference Rules Monolith)
"""

from __future__ import annotations

# Base class
from .base import TDFOLInferenceRule

# Propositional rules (13 rules)
from .propositional import (
    ModusPonensRule,
    ModusTollensRule,
    DisjunctiveSyllogismRule,
    HypotheticalSyllogismRule,
    ConjunctionIntroductionRule,
    ConjunctionEliminationLeftRule,
    ConjunctionEliminationRightRule,
    DisjunctionIntroductionLeftRule,
    DoubleNegationEliminationRule,
    DoubleNegationIntroductionRule,
    ContrapositionRule,
    DeMorganAndRule,
    DeMorganOrRule,
)

# First-order rules (2 rules)
from .first_order import (
    UniversalInstantiationRule,
    ExistentialGeneralizationRule,
)

# Temporal rules (20 rules)
from .temporal import (
    TemporalKAxiomRule,
    TemporalTAxiomRule,
    TemporalS4AxiomRule,
    TemporalS5AxiomRule,
    EventuallyIntroductionRule,
    AlwaysNecessitationRule,
    UntilUnfoldingRule,
    UntilInductionRule,
    EventuallyExpansionRule,
    AlwaysDistributionRule,
    AlwaysEventuallyExpansionRule,
    EventuallyAlwaysContractionRule,
    UntilReleaseDualityRule,
    WeakUntilExpansionRule,
    NextDistributionRule,
    EventuallyAggregationRule,
    TemporalInductionRule,
    UntilInductionStepRule,
    ReleaseCoinductionRule,
    EventuallyDistributionRule,
)

# Deontic rules (16 rules)
from .deontic import (
    DeonticKAxiomRule,
    DeonticDAxiomRule,
    ProhibitionEquivalenceRule,
    PermissionNegationRule,
    ObligationConsistencyRule,
    PermissionIntroductionRule,
    DeonticNecessitationRule,
    ProhibitionFromObligationRule,
    ObligationWeakeningRule,
    PermissionStrengtheningRule,
    ProhibitionContrapositionRule,
    DeonticDistributionRule,
    PermissionProhibitionDualityRule,
    ObligationPermissionImplicationRule,
    ContraryToDutyRule,
    DeonticDetachmentRule,
)

# Temporal-Deontic rules (9 rules)
from .temporal_deontic import (
    TemporalObligationPersistenceRule,
    DeonticTemporalIntroductionRule,
    UntilObligationRule,
    AlwaysPermissionRule,
    EventuallyForbiddenRule,
    ObligationEventuallyRule,
    PermissionTemporalWeakeningRule,
    AlwaysObligationDistributionRule,
    FutureObligationPersistenceRule,
)


# All propositional rules
__all__ = [
    # Base
    'TDFOLInferenceRule',
    
    # Propositional (13)
    'ModusPonensRule',
    'ModusTollensRule',
    'DisjunctiveSyllogismRule',
    'HypotheticalSyllogismRule',
    'ConjunctionIntroductionRule',
    'ConjunctionEliminationLeftRule',
    'ConjunctionEliminationRightRule',
    'DisjunctionIntroductionLeftRule',
    'DoubleNegationEliminationRule',
    'DoubleNegationIntroductionRule',
    'ContrapositionRule',
    'DeMorganAndRule',
    'DeMorganOrRule',
    
    # First-Order (2)
    'UniversalInstantiationRule',
    'ExistentialGeneralizationRule',
    
    # Temporal (20)
    'TemporalKAxiomRule',
    'TemporalTAxiomRule',
    'TemporalS4AxiomRule',
    'TemporalS5AxiomRule',
    'EventuallyIntroductionRule',
    'AlwaysNecessitationRule',
    'UntilUnfoldingRule',
    'UntilInductionRule',
    'EventuallyExpansionRule',
    'AlwaysDistributionRule',
    'AlwaysEventuallyExpansionRule',
    'EventuallyAlwaysContractionRule',
    'UntilReleaseDualityRule',
    'WeakUntilExpansionRule',
    'NextDistributionRule',
    'EventuallyAggregationRule',
    'TemporalInductionRule',
    'UntilInductionStepRule',
    'ReleaseCoinductionRule',
    'EventuallyDistributionRule',
    
    # Deontic (16)
    'DeonticKAxiomRule',
    'DeonticDAxiomRule',
    'ProhibitionEquivalenceRule',
    'PermissionNegationRule',
    'ObligationConsistencyRule',
    'PermissionIntroductionRule',
    'DeonticNecessitationRule',
    'ProhibitionFromObligationRule',
    'ObligationWeakeningRule',
    'PermissionStrengtheningRule',
    'ProhibitionContrapositionRule',
    'DeonticDistributionRule',
    'PermissionProhibitionDualityRule',
    'ObligationPermissionImplicationRule',
    'ContraryToDutyRule',
    'DeonticDetachmentRule',
    
    # Temporal-Deontic (9)
    'TemporalObligationPersistenceRule',
    'DeonticTemporalIntroductionRule',
    'UntilObligationRule',
    'AlwaysPermissionRule',
    'EventuallyForbiddenRule',
    'ObligationEventuallyRule',
    'PermissionTemporalWeakeningRule',
    'AlwaysObligationDistributionRule',
    'FutureObligationPersistenceRule',
    
    # Utility function
    'get_all_tdfol_rules',
]


def get_all_tdfol_rules():
    """
    Get all TDFOL inference rules (60 total).
    
    Returns a list containing one instance of each of the 60 inference rules
    organized across propositional logic, first-order logic, temporal logic,
    deontic logic, and combined temporal-deontic logic.
    
    Returns:
        List[TDFOLInferenceRule]: List of all 60 inference rule instances
        
    Example:
        >>> from ipfs_datasets_py.logic.TDFOL.inference_rules import get_all_tdfol_rules
        >>> rules = get_all_tdfol_rules()
        >>> len(rules)
        60
        >>> assert any(isinstance(r, ModusPonensRule) for r in rules)
    """
    from typing import List
    
    return [
        # Propositional Logic (13 rules)
        ModusPonensRule(),
        ModusTollensRule(),
        DisjunctiveSyllogismRule(),
        HypotheticalSyllogismRule(),
        ConjunctionIntroductionRule(),
        ConjunctionEliminationLeftRule(),
        ConjunctionEliminationRightRule(),
        DisjunctionIntroductionLeftRule(),
        DoubleNegationEliminationRule(),
        DoubleNegationIntroductionRule(),
        ContrapositionRule(),
        DeMorganAndRule(),
        DeMorganOrRule(),
        
        # First-Order Logic (2 rules)
        UniversalInstantiationRule(),
        ExistentialGeneralizationRule(),
        
        # Temporal Logic (20 rules)
        TemporalKAxiomRule(),
        TemporalTAxiomRule(),
        TemporalS4AxiomRule(),
        TemporalS5AxiomRule(),
        EventuallyIntroductionRule(),
        AlwaysNecessitationRule(),
        UntilUnfoldingRule(),
        UntilInductionRule(),
        EventuallyExpansionRule(),
        AlwaysDistributionRule(),
        AlwaysEventuallyExpansionRule(),
        EventuallyAlwaysContractionRule(),
        UntilReleaseDualityRule(),
        WeakUntilExpansionRule(),
        NextDistributionRule(),
        EventuallyAggregationRule(),
        TemporalInductionRule(),
        UntilInductionStepRule(),
        ReleaseCoinductionRule(),
        EventuallyDistributionRule(),
        
        # Deontic Logic (16 rules)
        DeonticKAxiomRule(),
        DeonticDAxiomRule(),
        ProhibitionEquivalenceRule(),
        PermissionNegationRule(),
        ObligationConsistencyRule(),
        PermissionIntroductionRule(),
        DeonticNecessitationRule(),
        ProhibitionFromObligationRule(),
        ObligationWeakeningRule(),
        PermissionStrengtheningRule(),
        ProhibitionContrapositionRule(),
        DeonticDistributionRule(),
        PermissionProhibitionDualityRule(),
        ObligationPermissionImplicationRule(),
        ContraryToDutyRule(),
        DeonticDetachmentRule(),
        
        # Combined Temporal-Deontic (9 rules)
        TemporalObligationPersistenceRule(),
        DeonticTemporalIntroductionRule(),
        UntilObligationRule(),
        AlwaysPermissionRule(),
        EventuallyForbiddenRule(),
        ObligationEventuallyRule(),
        PermissionTemporalWeakeningRule(),
        AlwaysObligationDistributionRule(),
        FutureObligationPersistenceRule(),
    ]
