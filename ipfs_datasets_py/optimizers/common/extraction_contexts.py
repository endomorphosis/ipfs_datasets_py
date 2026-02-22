"""Unified extraction context classes for cross-optimizer standardization.

This module provides a unified set of typed dataclasses for extraction
configuration that work across GraphRAG, logic, and agentic optimizers.

The design pattern:
- BaseExtractionConfig: Provides common fields shared across all extractors
  (confidence_threshold, max_entities, domain, custom_rules, etc.)
- Concrete subclasses (GraphRAGExtractionConfig, LogicExtractionConfig):
  Add optimizer-specific fields while inheriting common base
- Context classes (OntologyGenerationContext, LogicExtractionContext):
  Accept either explicit typed config or backward-compat dicts/enums

This standardization enables:
- Uniform configuration across optimizer types
- Cleaner type checking and IDE support
- Easier context serialization/deserialization
- Foundation for unified OptimizationContext

Example:
    # GraphRAG usage (typed)
    >>> config = GraphRAGExtractionConfig(
    ...     confidence_threshold=0.7,
    ...     domain='legal',
    ...     min_entity_length=3
    ... )
    >>> context = OntologyGenerationContext(
    ...     data_source='contract.pdf',
    ...     data_type='pdf',
    ...     domain='legal',
    ...     config=config
    ... )
    
    # Logic usage (typed)
    >>> config = LogicExtractionConfig(
    ...     confidence_threshold=0.8,
    ...     domain='legal',
    ...     extraction_mode=ExtractionMode.TDFOL
    ... )
    >>> context = LogicExtractionContext(
    ...     data=legal_text,
    ...     data_type=DataType.TEXT,
    ...     config=config
    ... )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class BaseExtractionConfig:
    """Base configuration for all extraction types.
    
    This dataclass provides a common set of configuration fields used by all
    extractors (GraphRAG, logic, agentic). Subclasses add optimizer-specific
    fields while inheriting these core parameters.
    
    Attributes:
        confidence_threshold: Minimum confidence score to include assertions (0.0-1.0).
        max_entities: Maximum number of entities to extract (0 = unlimited).
        max_assertions: Maximum number of assertions/relationships (0 = unlimited).
        domain: Domain context for extraction (e.g., 'legal', 'medical', 'general').
        custom_rules: List of (pattern, type) tuples for rule-based extraction.
        llm_fallback_threshold: Confidence below which to attempt LLM fallback (0.0 = disabled).
        min_entity_length: Minimum character length for entity text (default: 2).
        stopwords: List of entity texts to skip (case-insensitive).
        allowed_entity_types: Whitelist of entity types (empty = allow all).
        max_confidence: Upper bound on confidence scores (clamp to this value).
    """
    
    confidence_threshold: float = 0.5
    max_entities: int = 0
    max_assertions: int = 0
    domain: str = "general"
    custom_rules: List[tuple] = field(default_factory=list)
    llm_fallback_threshold: float = 0.0
    min_entity_length: int = 2
    stopwords: List[str] = field(default_factory=list)
    allowed_entity_types: List[str] = field(default_factory=list)
    max_confidence: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Return plain-dict representation (backward-compat)."""
        return {
            "confidence_threshold": self.confidence_threshold,
            "max_entities": self.max_entities,
            "max_assertions": self.max_assertions,
            "domain": self.domain,
            "custom_rules": list(self.custom_rules),
            "llm_fallback_threshold": self.llm_fallback_threshold,
            "min_entity_length": self.min_entity_length,
            "stopwords": list(self.stopwords),
            "allowed_entity_types": list(self.allowed_entity_types),
            "max_confidence": self.max_confidence,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> BaseExtractionConfig:
        """Construct from plain dict (backward-compat)."""
        return cls(
            confidence_threshold=float(d.get("confidence_threshold", 0.5)),
            max_entities=int(d.get("max_entities", 0)),
            max_assertions=int(d.get("max_assertions", 0)),
            domain=str(d.get("domain", "general")),
            custom_rules=list(d.get("custom_rules", [])),
            llm_fallback_threshold=float(d.get("llm_fallback_threshold", 0.0)),
            min_entity_length=int(d.get("min_entity_length", 2)),
            stopwords=list(d.get("stopwords", [])),
            allowed_entity_types=list(d.get("allowed_entity_types", [])),
            max_confidence=float(d.get("max_confidence", 1.0)),
        )


@dataclass
class GraphRAGExtractionConfig(BaseExtractionConfig):
    """GraphRAG-specific extraction configuration.
    
    Extends BaseExtractionConfig with fields specific to ontology/entity/
    relationship extraction in the GraphRAG optimizer.
    
    Attributes:
        window_size: Co-occurrence window for relationship inference (default: 5).
        include_properties: Emit property predicates in formula set (default: True).
        domain_vocab: Domain-specific vocabulary dict {type: [terms]} (default: {}).
        max_relationships: (inherited) max relationships to extract (0 = unlimited).
    """
    
    window_size: int = 5
    include_properties: bool = True
    domain_vocab: Dict[str, List[str]] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Return plain-dict representation (backward-compat)."""
        d = super().to_dict()
        d.update({
            "window_size": self.window_size,
            "include_properties": self.include_properties,
            "domain_vocab": {k: list(v) for k, v in self.domain_vocab.items()},
        })
        return d
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GraphRAGExtractionConfig:
        """Construct from plain dict (backward-compat)."""
        base = BaseExtractionConfig.from_dict(d)
        return cls(
            confidence_threshold=base.confidence_threshold,
            max_entities=base.max_entities,
            max_assertions=base.max_assertions,
            domain=base.domain,
            custom_rules=base.custom_rules,
            llm_fallback_threshold=base.llm_fallback_threshold,
            min_entity_length=base.min_entity_length,
            stopwords=base.stopwords,
            allowed_entity_types=base.allowed_entity_types,
            max_confidence=base.max_confidence,
            window_size=int(d.get("window_size", 5)),
            include_properties=bool(d.get("include_properties", True)),
            domain_vocab=dict(d.get("domain_vocab", {})),
        )


class ExtractionMode(Enum):
    """Mode of logic extraction."""
    TDFOL = "tdfol"  # Temporal Deontic First-Order Logic
    FOL = "fol"  # First-Order Logic
    CEC = "cec"  # Cognitive Event Calculus
    MODAL = "modal"  # Modal Logic
    DEONTIC = "deontic"  # Deontic Logic
    AUTO = "auto"  # Automatic mode selection


@dataclass
class LogicExtractionConfig(BaseExtractionConfig):
    """Logic theorem optimizer extraction configuration.
    
    Extends BaseExtractionConfig with fields specific to logical statement
    extraction and formal verification in the logic optimizer.
    
    Attributes:
        extraction_mode: Formalism to extract into (TDFOL, FOL, etc.).
        formalism_hint: Hint for formalism selection (default: None).
        prover_list: List of applicable theorem provers (default: []).
        include_schema: Include type/predicate schema in output (default: True).
    """
    
    extraction_mode: ExtractionMode = ExtractionMode.AUTO
    formalism_hint: Optional[str] = None
    prover_list: List[str] = field(default_factory=list)
    include_schema: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Return plain-dict representation (backward-compat)."""
        d = super().to_dict()
        d.update({
            "extraction_mode": self.extraction_mode.value if isinstance(self.extraction_mode, ExtractionMode) else self.extraction_mode,
            "formalism_hint": self.formalism_hint,
            "prover_list": list(self.prover_list),
            "include_schema": self.include_schema,
        })
        return d
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> LogicExtractionConfig:
        """Construct from plain dict (backward-compat)."""
        base = BaseExtractionConfig.from_dict(d)
        mode_str = d.get("extraction_mode", "auto")
        try:
            extraction_mode = ExtractionMode(mode_str) if isinstance(mode_str, str) else mode_str
        except ValueError:
            extraction_mode = ExtractionMode.AUTO
        return cls(
            confidence_threshold=base.confidence_threshold,
            max_entities=base.max_entities,
            max_assertions=base.max_assertions,
            domain=base.domain,
            custom_rules=base.custom_rules,
            llm_fallback_threshold=base.llm_fallback_threshold,
            min_entity_length=base.min_entity_length,
            stopwords=base.stopwords,
            allowed_entity_types=base.allowed_entity_types,
            max_confidence=base.max_confidence,
            extraction_mode=extraction_mode,
            formalism_hint=d.get("formalism_hint"),
            prover_list=list(d.get("prover_list", [])),
            include_schema=bool(d.get("include_schema", True)),
        )


class OptimizationMethod(Enum):
    """Type of optimization method to use."""
    
    ADVERSARIAL = "adversarial"  # Generate competing solutions
    ACTOR_CRITIC = "actor_critic"  # Reward-based learning
    TEST_DRIVEN = "test_driven"  # Test-first optimization
    CHAOS = "chaos"  # Chaos engineering


@dataclass
class AgenticExtractionConfig(BaseExtractionConfig):
    """Agentic optimizer extraction configuration.
    
    Extends BaseExtractionConfig with fields specific to agentic multi-method
    optimization (adversarial, actor-critic, test-driven, chaos).
    
    Attributes:
        optimization_method: Which optimization strategy to use.
        enable_validation: Run multi-level validation post-extraction (default: True).
        validation_level: Depth of validation ('basic', 'full', 'extended').
        enable_change_control: Use GitHub/patch-based change control (default: True).
        change_control_method: GitHub or patch-based control (default: 'patch').
    """
    
    optimization_method: OptimizationMethod = OptimizationMethod.TEST_DRIVEN
    enable_validation: bool = True
    validation_level: str = "full"  # Options: 'basic', 'full', 'extended'
    enable_change_control: bool = True
    change_control_method: str = "patch"  # Options: 'github', 'patch'
    
    def to_dict(self) -> Dict[str, Any]:
        """Return plain-dict representation (backward-compat)."""
        d = super().to_dict()
        d.update({
            "optimization_method": self.optimization_method.value if isinstance(self.optimization_method, OptimizationMethod) else self.optimization_method,
            "enable_validation": self.enable_validation,
            "validation_level": self.validation_level,
            "enable_change_control": self.enable_change_control,
            "change_control_method": self.change_control_method,
        })
        return d
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> AgenticExtractionConfig:
        """Construct from plain dict (backward-compat)."""
        base = BaseExtractionConfig.from_dict(d)
        method_str = d.get("optimization_method", "test_driven")
        try:
            opt_method = OptimizationMethod(method_str) if isinstance(method_str, str) else method_str
        except ValueError:
            opt_method = OptimizationMethod.TEST_DRIVEN
        return cls(
            confidence_threshold=base.confidence_threshold,
            max_entities=base.max_entities,
            max_assertions=base.max_assertions,
            domain=base.domain,
            custom_rules=base.custom_rules,
            llm_fallback_threshold=base.llm_fallback_threshold,
            min_entity_length=base.min_entity_length,
            stopwords=base.stopwords,
            allowed_entity_types=base.allowed_entity_types,
            max_confidence=base.max_confidence,
            optimization_method=opt_method,
            enable_validation=bool(d.get("enable_validation", True)),
            validation_level=str(d.get("validation_level", "full")),
            enable_change_control=bool(d.get("enable_change_control", True)),
            change_control_method=str(d.get("change_control_method", "patch")),
        )


__all__ = [
    "BaseExtractionConfig",
    "GraphRAGExtractionConfig",
    "LogicExtractionConfig",
    "ExtractionMode",
    "AgenticExtractionConfig",
    "OptimizationMethod",
]
