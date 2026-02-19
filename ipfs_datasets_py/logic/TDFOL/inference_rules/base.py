"""
TDFOL Inference Rules Base - Abstract base class for all inference rules

This module defines the base interface that all TDFOL inference rules must implement,
ensuring consistent behavior across propositional, first-order, temporal, and deontic rules.

Author: TDFOL Team
Date: 2026-02-19
Phase: 2 (Architecture Improvements)
Task: 2.1 (Split Inference Rules Monolith)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Set, Tuple

from ..tdfol_core import Formula

logger = logging.getLogger(__name__)


# ============================================================================
# Abstract Base Class
# ============================================================================


class TDFOLInferenceRule(ABC):
    """
    Abstract base class for TDFOL inference rules.
    
    All inference rules in TDFOL must implement this interface, providing:
    - Rule identification (name, description)
    - Applicability checking (can_apply)
    - Rule application (apply)
    
    Attributes:
        name: Rule name (e.g., "ModusPonens", "TemporalKAxiom")
        description: Human-readable rule description
    
    Example:
        >>> class MyCustomRule(TDFOLInferenceRule):
        ...     def __init__(self):
        ...         super().__init__("MyRule", "Custom inference rule")
        ...     
        ...     def can_apply(self, *formulas: Formula) -> bool:
        ...         return len(formulas) >= 1
        ...     
        ...     def apply(self, *formulas: Formula) -> Formula:
        ...         return formulas[0]
    """
    
    def __init__(self, name: str, description: str):
        """
        Initialize inference rule.
        
        Args:
            name: Rule name (should be unique)
            description: Human-readable description of what the rule does
        """
        self.name = name
        self.description = description
    
    @abstractmethod
    def can_apply(self, *formulas: Formula) -> bool:
        """
        Check if rule can be applied to given formulas.
        
        Args:
            *formulas: Input formulas to check
        
        Returns:
            True if rule is applicable, False otherwise
            
        Note:
            This method should be fast, as it's called frequently
            during proof search. Avoid expensive computations.
        """
        pass
    
    @abstractmethod
    def apply(self, *formulas: Formula) -> Formula:
        """
        Apply rule to formulas and return result.
        
        Args:
            *formulas: Input formulas (must satisfy can_apply)
        
        Returns:
            The formula resulting from rule application
            
        Raises:
            ValueError: If rule cannot be applied (check with can_apply first)
            
        Note:
            Callers should check can_apply() before calling apply().
            This method may raise exceptions if preconditions aren't met.
        """
        pass
    
    def __repr__(self) -> str:
        """String representation of rule."""
        return f"{self.name}: {self.description}"
    
    def __str__(self) -> str:
        """String representation of rule."""
        return self.name


# Export all
__all__ = ['TDFOLInferenceRule']
