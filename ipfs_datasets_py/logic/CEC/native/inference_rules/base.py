"""
Base classes and enums for inference rules.

This module provides the foundational types for the inference rule system.
"""

from typing import List
from enum import Enum
from abc import ABC, abstractmethod

# Import Formula type - will be from parent when dcec_core is split
from ..dcec_core import Formula


class ProofResult(Enum):
    """
    Result of a proof attempt.
    
    Attributes:
        PROVED: The goal was successfully proved
        DISPROVED: The goal was shown to be false
        TIMEOUT: Proof search exceeded time limit
        UNKNOWN: Could not determine proof status
        ERROR: An error occurred during proving
    """
    PROVED = "proved"
    DISPROVED = "disproved"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"
    ERROR = "error"


class InferenceRule(ABC):
    """
    Abstract base class for all inference rules.
    
    An inference rule defines a logical transformation that can derive
    new formulas from existing ones. Each rule must implement methods
    to check applicability and perform the transformation.
    
    Example:
        class MyRule(InferenceRule):
            def name(self) -> str:
                return "My Custom Rule"
            
            def can_apply(self, formulas: List[Formula]) -> bool:
                # Check if rule can be applied
                return True
            
            def apply(self, formulas: List[Formula]) -> List[Formula]:
                # Apply rule and return new formulas
                return [...]
    """
    
    @abstractmethod
    def name(self) -> str:
        """
        Get the name of this inference rule.
        
        Returns:
            Human-readable name of the rule
        """
        pass
    
    @abstractmethod
    def can_apply(self, formulas: List[Formula]) -> bool:
        """
        Check if this rule can be applied to the given formulas.
        
        Args:
            formulas: List of formulas to check
            
        Returns:
            True if the rule can be applied, False otherwise
        """
        pass
    
    @abstractmethod
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """
        Apply this rule and return newly derived formulas.
        
        Args:
            formulas: List of formulas to apply the rule to
            
        Returns:
            List of newly derived formulas (may be empty)
        """
        pass


__all__ = [
    'ProofResult',
    'InferenceRule',
]
