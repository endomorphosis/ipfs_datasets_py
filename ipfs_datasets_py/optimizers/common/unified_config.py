"""Standardized configuration and context dataclasses for all optimizers.

Provides a unified approach to optimizer configuration across GraphRAG, logic,
and agentic domains while allowing domain-specific extensions.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Set


class DomainType(Enum):
    """Supported optimization domains."""
    GRAPHRAG = "graphrag"
    LOGIC = "logic"
    AGENTIC = "agentic"
    CODE = "code"
    HYBRID = "hybrid"


@dataclass
class BaseConfig:
    """Base configuration allowing field extension."""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        from dataclasses import asdict
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseConfig":
        """Create config from dictionary."""
        from dataclasses import fields
        field_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered)
    
    def merge(self, other: "BaseConfig") -> "BaseConfig":
        """Merge two configs, other's values override self's."""
        from dataclasses import replace
        return replace(self, **other.to_dict())


@dataclass
class GraphRAGConfig(BaseConfig):
    """Configuration specific to GraphRAG optimizer."""
    extraction_strategy: str = "heuristic"  # heuristic, llm, hybrid
    confidence_threshold: float = 0.5
    relationship_inference: str = "heuristic"  # heuristic, llm, hybrid
    domain_specific_rules: Optional[Set[str]] = None
    language: str = "en"
    max_entity_types: int = 50
    max_relationship_types: int = 100
    enable_semantic_deduplication: bool = False
    deduplication_threshold: float = 0.8
    
    def __post_init__(self):
        if self.domain_specific_rules is None:
            self.domain_specific_rules = set()
    
    def __repr__(self) -> str:
        """Return concise string representation."""
        return (
            f"GraphRAGConfig(strategy={self.extraction_strategy}, "
            f"confidence={self.confidence_threshold}, "
            f"semantic_dedup={self.enable_semantic_deduplication})"
        )


@dataclass
class LogicConfig(BaseConfig):
    """Configuration specific to logic theorem optimizer."""
    formula_format: str = "tdfol"  # tdfol, first-order, horn
    prover_backend: str = "z3"  # z3, vampire, eprover
    proof_timeout_ms: int = 5000
    max_proof_depth: int = 20
    enable_neural_symbolic: bool = False
    neural_confidence_threshold: float = 0.7
    enable_conflict_resolution: bool = True
    enable_knowledge_graph_integration: bool = True
    enable_rag_integration: bool = True
    
    def __repr__(self) -> str:
        """Return concise string representation."""
        return (
            f"LogicConfig(backend={self.prover_backend}, "
            f"format={self.formula_format}, "
            f"timeout_ms={self.proof_timeout_ms}, "
            f"neural_symbolic={self.enable_neural_symbolic})"
        )


@dataclass
class AgenticConfig(BaseConfig):
    """Configuration specific to agentic optimizer."""
    mode: str = "autonomous"  # autonomous, supervised, interactive
    decision_threshold: float = 0.8
    enable_chaos_testing: bool = False
    max_parallel_actions: int = 4
    enable_github_integration: bool = False
    required_approvals: int = 1
    enable_logging: bool = True
    log_level: str = "INFO"
    
    def __repr__(self) -> str:
        """Return concise string representation."""
        return (
            f"AgenticConfig(mode={self.mode}, "
            f"threshold={self.decision_threshold}, "
            f"parallel_actions={self.max_parallel_actions}, "
            f"github_integration={self.enable_github_integration})"
        )


@dataclass
class UnifiedOptimizerConfig(BaseConfig):
    """Master configuration that combines all domain-specific configs."""
    
    # Core settings
    domain: DomainType = DomainType.HYBRID
    strategy: str = "sgd"
    max_iterations: int = 10
    target_score: float = 0.85
    learning_rate: float = 0.1
    convergence_threshold: float = 0.01
    early_stopping: bool = True
    validation_enabled: bool = True
    metrics_enabled: bool = True
    seed: Optional[int] = None
    
    # Domain-specific configs
    graphrag_config: Optional[GraphRAGConfig] = None
    logic_config: Optional[LogicConfig] = None
    agentic_config: Optional[AgenticConfig] = None
    
    # Feature flags
    enable_prometheus: bool = True
    enable_opentelemetry: bool = False
    enable_caching: bool = True
    cache_size_mb: int = 100
    
    def __post_init__(self):
        """Initialize domain-specific configs if not provided."""
        if self.graphrag_config is None:
            self.graphrag_config = GraphRAGConfig()
        if self.logic_config is None:
            self.logic_config = LogicConfig()
        if self.agentic_config is None:
            self.agentic_config = AgenticConfig()
    
    def get_domain_config(self, domain: DomainType) -> BaseConfig:
        """Get the configuration for a specific domain."""
        if domain == DomainType.GRAPHRAG:
            return self.graphrag_config
        elif domain == DomainType.LOGIC:
            return self.logic_config
        elif domain == DomainType.AGENTIC:
            return self.agentic_config
        else:
            raise ValueError(f"Unknown domain: {domain}")
    
    def __repr__(self) -> str:
        """Return concise string representation."""
        return (
            f"UnifiedOptimizerConfig(domain={self.domain.value}, "
            f"strategy={self.strategy}, "
            f"target_score={self.target_score}, "
            f"max_iterations={self.max_iterations})"
        )


@dataclass
class BaseContext:
    """Base context for optimization sessions."""
    
    session_id: str
    domain: DomainType
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary."""
        from dataclasses import asdict
        return asdict(self)
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get metadata value by key."""
        return self.metadata.get(key, default)
    
    def set_metadata(self, key: str, value: Any) -> None:
        """Set metadata value."""
        self.metadata[key] = value
    
    def __repr__(self) -> str:
        """Return concise string representation."""
        return (
            f"BaseContext(session_id={self.session_id}, "
            f"domain={self.domain.value}, "
            f"metadata_keys={len(self.metadata)})"
        )


@dataclass
class GraphRAGContext(BaseContext):
    """Context specific to GraphRAG optimization."""
    input_text: Optional[str] = None
    input_documents: Optional[Dict[str, Any]] = None
    extraction_context: Optional[Dict[str, Any]] = None
    ontology_domain: Optional[str] = None
    
    def __repr__(self) -> str:
        """Return concise string representation."""
        doc_count = len(self.input_documents) if self.input_documents else 0
        text_len = len(self.input_text) if self.input_text else 0
        return (
            f"GraphRAGContext(session_id={self.session_id}, "
            f"docs={doc_count}, text_len={text_len}, "
            f"domain={self.ontology_domain})"
        )


@dataclass
class LogicContext(BaseContext):
    """Context specific to logic optimization."""
    formulas: Optional[Dict[str, str]] = None
    theory: Optional[Dict[str, Any]] = None
    proof_objectives: Optional[Dict[str, str]] = None
    
    def __repr__(self) -> str:
        """Return concise string representation."""
        formula_count = len(self.formulas) if self.formulas else 0
        objective_count = len(self.proof_objectives) if self.proof_objectives else 0
        return (
            f"LogicContext(session_id={self.session_id}, "
            f"formulas={formula_count}, objectives={objective_count})"
        )


@dataclass
class AgenticContext(BaseContext):
    """Context specific to agentic optimization."""
    action_history: Dict[str, int] = field(default_factory=dict)
    decision_log: Dict[str, str] = field(default_factory=dict)
    approval_status: Dict[str, bool] = field(default_factory=dict)
    
    def __repr__(self) -> str:
        """Return concise string representation."""
        action_count = sum(self.action_history.values()) if self.action_history else 0
        approved = sum(1 for v in self.approval_status.values() if v) if self.approval_status else 0
        return (
            f"AgenticContext(session_id={self.session_id}, "
            f"actions={action_count}, approved={approved})"
        )


def create_context(
    session_id: str,
    domain: DomainType,
    **kwargs
) -> BaseContext:
    """Factory function to create appropriate context based on domain."""
    if domain == DomainType.GRAPHRAG:
        return GraphRAGContext(session_id=session_id, domain=domain, **kwargs)
    elif domain == DomainType.LOGIC:
        return LogicContext(session_id=session_id, domain=domain, **kwargs)
    elif domain == DomainType.AGENTIC:
        return AgenticContext(session_id=session_id, domain=domain, **kwargs)
    else:
        return BaseContext(session_id=session_id, domain=domain, **kwargs)


def domain_type_from_value(domain: Any) -> DomainType:
    """Best-effort normalize domain values to :class:`DomainType`."""
    if isinstance(domain, DomainType):
        return domain
    if isinstance(domain, str):
        normalized = domain.strip().lower()
        mapping = {
            "graphrag": DomainType.GRAPHRAG,
            "graph": DomainType.GRAPHRAG,
            "logic": DomainType.LOGIC,
            "agentic": DomainType.AGENTIC,
            "code": DomainType.CODE,
            "hybrid": DomainType.HYBRID,
        }
        return mapping.get(normalized, DomainType.HYBRID)
    return DomainType.HYBRID


def context_from_optimization_context(context: Any) -> BaseContext:
    """Adapt legacy ``OptimizationContext``-like objects into unified contexts."""
    session_id = str(getattr(context, "session_id", ""))
    domain_raw = getattr(context, "domain", DomainType.HYBRID)
    domain = domain_type_from_value(domain_raw)
    metadata = dict(getattr(context, "metadata", {}) or {})
    input_data = getattr(context, "input_data", None)

    if domain == DomainType.GRAPHRAG:
        return GraphRAGContext(
            session_id=session_id,
            domain=domain,
            metadata=metadata,
            input_text=input_data if isinstance(input_data, str) else None,
            input_documents=input_data if isinstance(input_data, dict) else None,
            ontology_domain=str(domain_raw) if domain_raw is not None else None,
        )
    if domain == DomainType.LOGIC:
        return LogicContext(session_id=session_id, domain=domain, metadata=metadata)
    if domain == DomainType.AGENTIC:
        return AgenticContext(session_id=session_id, domain=domain, metadata=metadata)
    return BaseContext(session_id=session_id, domain=domain, metadata=metadata)


def context_from_ontology_generation_context(
    context: Any,
    *,
    session_id: str = "graphrag-session",
) -> GraphRAGContext:
    """Adapt ``OntologyGenerationContext``-like objects into ``GraphRAGContext``."""
    data_source = getattr(context, "data_source", None)
    data_type = getattr(context, "data_type", None)
    domain = str(getattr(context, "domain", "graphrag"))
    extraction_strategy = getattr(context, "extraction_strategy", None)
    base_ontology = getattr(context, "base_ontology", None)
    extraction_config = getattr(context, "config", None)
    extraction_context: Optional[Dict[str, Any]] = None
    if extraction_config is not None:
        if hasattr(extraction_config, "to_dict"):
            extraction_context = extraction_config.to_dict()
        elif isinstance(extraction_config, dict):
            extraction_context = dict(extraction_config)

    return GraphRAGContext(
        session_id=session_id,
        domain=DomainType.GRAPHRAG,
        metadata={
            "data_source": data_source,
            "data_type": str(data_type) if data_type is not None else None,
            "extraction_strategy": str(extraction_strategy)
            if extraction_strategy is not None
            else None,
        },
        input_documents=base_ontology if isinstance(base_ontology, dict) else None,
        extraction_context=extraction_context,
        ontology_domain=domain,
    )


__all__ = [
    "DomainType",
    "BaseConfig",
    "GraphRAGConfig",
    "LogicConfig",
    "AgenticConfig",
    "UnifiedOptimizerConfig",
    "BaseContext",
    "GraphRAGContext",
    "LogicContext",
    "AgenticContext",
    "create_context",
    "domain_type_from_value",
    "context_from_optimization_context",
    "context_from_ontology_generation_context",
]
