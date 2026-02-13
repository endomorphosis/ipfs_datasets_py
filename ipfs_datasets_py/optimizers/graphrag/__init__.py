"""
GraphRAG Ontology Optimizer - Complete System for Knowledge Graph Optimization.

This module provides a comprehensive framework for generating, validating, and
optimizing knowledge graph ontologies from arbitrary data types. It combines
multi-agent architecture with theorem prover integration for logically consistent
ontologies.

Inspired by the adversarial harness from complaint-generator, adapted for ontology
generation with focus on logical consistency and automated improvement through
stochastic gradient descent (SGD) cycles.

Components:
    - OntologyGenerator: Generate ontologies from arbitrary data
    - OntologyCritic: LLM-based multi-dimensional evaluation
    - LogicValidator: TDFOL theorem prover integration
    - OntologyMediator: Coordinate refinement cycles (planned)
    - OntologyOptimizer: SGD-based optimization (planned)
    - OntologySession: Single optimization session (planned)
    - OntologyHarness: Parallel batch orchestrator (planned)

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
    Entity,
    Relationship,
    EntityExtractionResult,
    ExtractionStrategy,
    DataType,
)

from .ontology_critic import (
    OntologyCritic,
    CriticScore,
    DIMENSION_WEIGHTS,
)

from .logic_validator import (
    LogicValidator,
    ValidationResult,
)

# Future components (placeholders)
# These will be implemented in Phase 2
# from .ontology_mediator import OntologyMediator, MediatorState
# from .ontology_optimizer import OntologyOptimizer, OptimizationReport
# from .ontology_session import OntologySession, SessionResult
# from .ontology_harness import OntologyHarness, BatchResult

# Export public API
__all__ = [
    # Generator
    'OntologyGenerator',
    'OntologyGenerationContext',
    'Entity',
    'Relationship',
    'EntityExtractionResult',
    'ExtractionStrategy',
    'DataType',
    # Critic
    'OntologyCritic',
    'CriticScore',
    'DIMENSION_WEIGHTS',
    # Validator
    'LogicValidator',
    'ValidationResult',
    # Future (Phase 2)
    # 'OntologyMediator',
    # 'MediatorState',
    # 'OntologyOptimizer',
    # 'OptimizationReport',
    # 'OntologySession',
    # 'SessionResult',
    # 'OntologyHarness',
    # 'BatchResult',
]

__version__ = '0.1.0'
__author__ = 'IPFS Datasets Team'
__status__ = 'Scaffolding'  # Will change to 'Production' after Phase 6
