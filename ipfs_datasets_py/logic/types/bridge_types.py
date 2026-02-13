"""Bridge Type Definitions

This module provides type definitions for prover bridges and conversion operations.
"""

from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


class BridgeCapability(Enum):
    """Capabilities that a bridge may support."""
    BIDIRECTIONAL_CONVERSION = "bidirectional"  # Can convert both directions
    INCREMENTAL_PROVING = "incremental"  # Can prove incrementally
    RULE_EXTRACTION = "rule_extraction"  # Can extract inference rules
    OPTIMIZATION = "optimization"  # Provides proof optimization
    PARALLEL_PROVING = "parallel"  # Supports parallel proof search


class ConversionStatus(Enum):
    """Status of a conversion operation."""
    SUCCESS = "success"
    PARTIAL = "partial"  # Partially converted, some elements lost
    FAILED = "failed"
    UNSUPPORTED = "unsupported"  # Target format doesn't support source features


@dataclass
class BridgeMetadata:
    """Metadata about a prover bridge."""
    name: str
    version: str
    target_system: str  # CEC, ShadowProver, Grammar, etc.
    capabilities: List[BridgeCapability]
    requires_external_prover: bool
    description: str
    
    def supports_capability(self, capability: BridgeCapability) -> bool:
        """Check if this bridge supports a specific capability."""
        return capability in self.capabilities


@dataclass
class ConversionResult:
    """Result of a logic conversion operation."""
    status: ConversionStatus
    source_formula: str
    target_formula: str
    source_format: str
    target_format: str
    confidence: float = 1.0
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_successful(self) -> bool:
        """Check if conversion was successful."""
        return self.status == ConversionStatus.SUCCESS
    
    def has_warnings(self) -> bool:
        """Check if conversion has warnings."""
        return len(self.warnings) > 0


@dataclass
class BridgeConfig:
    """Configuration for a prover bridge."""
    name: str
    target_system: str
    timeout: int = 30
    max_retries: int = 3
    enable_caching: bool = True
    cache_ttl: int = 3600  # Cache time-to-live in seconds
    custom_settings: Dict[str, Any] = field(default_factory=dict)
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a custom setting value."""
        return self.custom_settings.get(key, default)


@dataclass
class ProverRecommendation:
    """Recommendation for which prover to use."""
    prover_name: str
    confidence: float
    reasons: List[str]
    estimated_time: Optional[float] = None
    
    def __lt__(self, other: 'ProverRecommendation') -> bool:
        """Enable sorting by confidence (descending)."""
        return self.confidence > other.confidence


__all__ = [
    "BridgeCapability",
    "ConversionStatus",
    "BridgeMetadata",
    "ConversionResult",
    "BridgeConfig",
    "ProverRecommendation",
]
