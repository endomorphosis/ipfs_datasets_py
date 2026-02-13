"""
Base Prover Bridge Abstract Base Class

This module defines the standard interface that all prover bridges must implement
for consistent integration across different theorem proving systems.

All bridges (TDFOL-CEC, TDFOL-ShadowProver, TDFOL-Grammar, etc.) should inherit
from BaseProverBridge to ensure uniform behavior and simplify maintenance.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

from ..TDFOL.tdfol_core import Formula
from ..TDFOL.tdfol_prover import ProofResult


class BridgeCapability(Enum):
    """Capabilities that a bridge may support."""
    BIDIRECTIONAL_CONVERSION = "bidirectional"  # Can convert both directions
    INCREMENTAL_PROVING = "incremental"  # Can prove incrementally
    RULE_EXTRACTION = "rule_extraction"  # Can extract inference rules
    OPTIMIZATION = "optimization"  # Provides proof optimization
    PARALLEL_PROVING = "parallel"  # Supports parallel proof search


@dataclass
class BridgeMetadata:
    """Metadata about a prover bridge."""
    name: str
    version: str
    target_system: str  # CEC, ShadowProver, Grammar, etc.
    capabilities: List[BridgeCapability]
    requires_external_prover: bool
    description: str


class BaseProverBridge(ABC):
    """
    Abstract base class for all prover bridges.
    
    A prover bridge connects TDFOL to another theorem proving system,
    handling format conversion, proof delegation, and result translation.
    
    All bridge implementations must implement:
    - to_target_format: Convert TDFOL formula to target system format
    - from_target_format: Convert target system result back to TDFOL
    - prove: Execute proof using the target system
    - is_available: Check if target system is available
    """
    
    def __init__(self):
        """Initialize the bridge."""
        self._metadata = self._init_metadata()
        self._available = self._check_availability()
    
    @abstractmethod
    def _init_metadata(self) -> BridgeMetadata:
        """
        Initialize bridge metadata.
        
        Returns:
            BridgeMetadata describing this bridge
        """
        pass
    
    @abstractmethod
    def _check_availability(self) -> bool:
        """
        Check if the target proving system is available.
        
        Returns:
            True if target system can be used, False otherwise
        """
        pass
    
    @abstractmethod
    def to_target_format(self, formula: Formula) -> str:
        """
        Convert TDFOL formula to target system format.
        
        Args:
            formula: TDFOL formula to convert
            
        Returns:
            String representation in target format
            
        Raises:
            ValueError: If formula cannot be converted
        """
        pass
    
    @abstractmethod
    def from_target_format(self, target_result: Any) -> ProofResult:
        """
        Convert target system result back to TDFOL ProofResult.
        
        Args:
            target_result: Result from target proving system
            
        Returns:
            ProofResult with standardized format
        """
        pass
    
    @abstractmethod
    def prove(
        self,
        formula: Formula,
        timeout: Optional[int] = None,
        **kwargs
    ) -> ProofResult:
        """
        Prove a formula using the target system.
        
        Args:
            formula: TDFOL formula to prove
            timeout: Optional timeout in seconds
            **kwargs: Additional system-specific parameters
            
        Returns:
            ProofResult with status and details
        """
        pass
    
    def is_available(self) -> bool:
        """
        Check if the bridge is available for use.
        
        Returns:
            True if the target system is available
        """
        return self._available
    
    def get_metadata(self) -> BridgeMetadata:
        """
        Get bridge metadata.
        
        Returns:
            BridgeMetadata for this bridge
        """
        return self._metadata
    
    def get_capabilities(self) -> List[BridgeCapability]:
        """
        Get list of capabilities supported by this bridge.
        
        Returns:
            List of supported capabilities
        """
        return self._metadata.capabilities
    
    def has_capability(self, capability: BridgeCapability) -> bool:
        """
        Check if bridge supports a specific capability.
        
        Args:
            capability: Capability to check
            
        Returns:
            True if capability is supported
        """
        return capability in self._metadata.capabilities
    
    def validate_formula(self, formula: Formula) -> bool:
        """
        Validate that a formula can be processed by this bridge.
        
        Args:
            formula: Formula to validate
            
        Returns:
            True if formula is valid for this bridge
        """
        # Default implementation - can be overridden
        try:
            self.to_target_format(formula)
            return True
        except Exception:
            return False
    
    def __repr__(self) -> str:
        """String representation of the bridge."""
        return (
            f"{self.__class__.__name__}("
            f"target={self._metadata.target_system}, "
            f"available={self._available})"
        )


class BridgeRegistry:
    """
    Registry for managing available prover bridges.
    
    Provides centralized access to all registered bridges and
    automatic selection based on formula requirements.
    """
    
    def __init__(self):
        """Initialize the bridge registry."""
        self._bridges: Dict[str, BaseProverBridge] = {}
    
    def register(self, name: str, bridge: BaseProverBridge) -> None:
        """
        Register a bridge.
        
        Args:
            name: Unique name for the bridge
            bridge: Bridge instance to register
        """
        self._bridges[name] = bridge
    
    def get(self, name: str) -> Optional[BaseProverBridge]:
        """
        Get a bridge by name.
        
        Args:
            name: Bridge name
            
        Returns:
            Bridge instance or None if not found
        """
        return self._bridges.get(name)
    
    def list_available(self) -> List[str]:
        """
        List all available bridges.
        
        Returns:
            List of names of available bridges
        """
        return [
            name for name, bridge in self._bridges.items()
            if bridge.is_available()
        ]
    
    def list_all(self) -> List[str]:
        """
        List all registered bridges.
        
        Returns:
            List of all bridge names
        """
        return list(self._bridges.keys())
    
    def find_capable(self, capability: BridgeCapability) -> List[str]:
        """
        Find all bridges with a specific capability.
        
        Args:
            capability: Capability to search for
            
        Returns:
            List of bridge names with the capability
        """
        return [
            name for name, bridge in self._bridges.items()
            if bridge.has_capability(capability) and bridge.is_available()
        ]
    
    def select_best(
        self,
        formula: Formula,
        preferred: Optional[str] = None
    ) -> Optional[BaseProverBridge]:
        """
        Select the best bridge for a given formula.
        
        Args:
            formula: Formula to prove
            preferred: Preferred bridge name (if available)
            
        Returns:
            Best bridge for the formula, or None if none available
        """
        # Try preferred bridge first
        if preferred and preferred in self._bridges:
            bridge = self._bridges[preferred]
            if bridge.is_available() and bridge.validate_formula(formula):
                return bridge
        
        # Try all available bridges
        for bridge in self._bridges.values():
            if bridge.is_available() and bridge.validate_formula(formula):
                return bridge
        
        return None


# Global bridge registry instance
_registry = BridgeRegistry()


def get_bridge_registry() -> BridgeRegistry:
    """
    Get the global bridge registry.
    
    Returns:
        Global BridgeRegistry instance
    """
    return _registry
