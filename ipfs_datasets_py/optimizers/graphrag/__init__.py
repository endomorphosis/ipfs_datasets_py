"""
GraphRAG Ontology Optimizer - Complete System for Knowledge Graph Optimization.

This module provides a comprehensive framework for generating, validating, and
optimizing knowledge graph ontologies from arbitrary data types. It combines
multi-agent architecture with theorem prover integration for logically consistent
ontologies.

Inspired by the adversarial harness from complaint-generator, adapted for ontology
generation with focus on logical consistency and automated improvement through
stochastic gradient descent (SGD) cycles.

Architecture (generate → critique → optimize → validate loop)::

    ┌─────────────────────────────────────────────────────────────────┐
    │                    OntologyHarness (batch)                      │
    │  ┌────────────────────────────────────────────────────────────┐ │
    │  │                  OntologySession (single)                  │ │
    │  │                                                            │ │
    │  │  ┌───────────────┐   ontology   ┌──────────────────────┐  │ │
    │  │  │OntologyGener- │ ──────────── │   OntologyCritic     │  │ │
    │  │  │ator           │              │  (5-dim evaluation)  │  │ │
    │  │  │ExtractionConf.│ ◄──actions── │  CriticResult        │  │ │
    │  │  └───────────────┘              └──────────┬───────────┘  │ │
    │  │         ▲                                   │              │ │
    │  │         │ refined ontology                  │ feedback     │ │
    │  │  ┌──────┴──────────┐              ┌─────────▼──────────┐  │ │
    │  │  │OntologyOptimizer│              │ OntologyMediator   │  │ │
    │  │  │(SGD, history,   │ ◄──actions── │ (action selection) │  │ │
    │  │  │ export)         │              └────────────────────┘  │ │
    │  │  └─────────────────┘                                      │ │
    │  │                           ┌─────────────────────────────┐  │ │
    │  │       TDFOL formulas      │     LogicValidator          │  │ │
    │  │  ─────────────────────────│  (theorem prover, cache)    │  │ │
    │  │                           └─────────────────────────────┘  │ │
    │  │                                                            │ │
    │  │  OntologyLearningAdapter (feedback-driven threshold tuning) │ │
    │  └────────────────────────────────────────────────────────────┘ │
    └─────────────────────────────────────────────────────────────────┘

Components:
    - OntologyGenerator: Generate ontologies from arbitrary data
    - OntologyCritic: LLM-based multi-dimensional evaluation
    - LogicValidator: TDFOL theorem prover integration
    - OntologyMediator: Coordinate refinement cycles
    - OntologyOptimizer: SGD-based optimization, export, history
    - OntologySession: Single optimization session
    - OntologyHarness: Parallel batch orchestrator
    - OntologyLearningAdapter: Feedback-driven extraction threshold tuning

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag import (
    ...     OntologyGenerator,
    ...     OntologyCritic,
    ...     LogicValidator,
    ...     OntologyGenerationContext,
    ...     ExtractionStrategy
    ... )
    >>> 
    >>> # Generate ontology
    >>> generator = OntologyGenerator()
    >>> context = OntologyGenerationContext(
    ...     data_source='document.pdf',
    ...     data_type='pdf',
    ...     domain='legal',
    ...     extraction_strategy=ExtractionStrategy.HYBRID
    ... )
    >>> ontology = generator.generate_ontology(data, context)
    >>> 
    >>> # Evaluate quality
    >>> critic = OntologyCritic()
    >>> score = critic.evaluate_ontology(ontology, context, data)
    >>> print(f"Quality: {score.overall:.2f}")
    >>> 
    >>> # Validate logic
    >>> validator = LogicValidator()
    >>> result = validator.check_consistency(ontology)
    >>> print(f"Consistent: {result.is_consistent}")

References:
    - complaint-generator: https://github.com/endomorphosis/complaint-generator
    - TDFOL: ipfs_datasets_py/logic/TDFOL/
    - GraphRAG Integration: GRAPHRAG_INTEGRATION_DETAILED.md
"""

# Core components (scaffolding complete)
from .ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionConfig,
    Entity,
    Relationship,
    EntityExtractionResult,
    OntologyGenerationResult,
    ExtractionStrategy,
    DataType,
)

from .ontology_critic import (
    OntologyCritic,
    CriticScore,
    BackendConfig,
    DIMENSION_WEIGHTS,
)

from .logic_validator import (
    LogicValidator,
    ValidationResult,
    ProverConfig,
)

# Phase 2 components (complete)
from .ontology_mediator import (
    OntologyMediator,
    MediatorState,
)

from .ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)

from .ontology_session import (
    OntologySession,
    SessionResult,
)

from .ontology_harness import (
    OntologyHarness,
    OntologyPipelineHarness,
    BatchResult,
)

from .prompt_generator import (
    PromptGenerator,
    PromptTemplate,
)

# Phase 3 components (complete)
from .ontology_templates import (
    OntologyTemplate,
    OntologyTemplateLibrary,
)

from .metrics_collector import (
    MetricsCollector,
    SessionMetrics,
)

from .visualization import (
    OntologyVisualizer,
    MetricsVisualizer,
    GraphVisualization,
)

from .ontology_learning_adapter import OntologyLearningAdapter, FeedbackRecord

# Export public API
__all__ = [
    # Generator
    'OntologyGenerator',
    'OntologyGenerationContext',
    'ExtractionConfig',
    'Entity',
    'Relationship',
    'EntityExtractionResult',
    'OntologyGenerationResult',
    'ExtractionStrategy',
    'DataType',
    # Critic
    'OntologyCritic',
    'CriticScore',
    'BackendConfig',
    'DIMENSION_WEIGHTS',
    # Validator
    'LogicValidator',
    'ValidationResult',
    'ProverConfig',
    # Mediator (Phase 2)
    'OntologyMediator',
    'MediatorState',
    # Optimizer (Phase 2)
    'OntologyOptimizer',
    'OptimizationReport',
    # Session (Phase 2)
    'OntologySession',
    'SessionResult',
    # Harness (Phase 2)
    'OntologyHarness',
    'OntologyPipelineHarness',
    'BatchResult',
    # Prompt Generator (Phase 2)
    'PromptGenerator',
    'PromptTemplate',
    # Templates (Phase 3)
    'OntologyTemplate',
    'OntologyTemplateLibrary',
    # Metrics (Phase 3)
    'MetricsCollector',
    'SessionMetrics',
    # Visualization (Phase 3)
    'OntologyVisualizer',
    'MetricsVisualizer',
    'GraphVisualization',
    # Learning Adapter
    'OntologyLearningAdapter',
    'FeedbackRecord',
]

__version__ = '0.1.0'
__author__ = 'IPFS Datasets Team'
__status__ = 'Scaffolding'  # Will change to 'Production' after Phase 6
