"""Formalized contracts for logic extraction sessions.

This module provides strongly-typed, validated configuration and result schemas
for logic theorem extraction and optimization sessions. These contracts provide:

- Type-safe configuration with validation and constraints
- Standardized result schemas with serialization support
- Integration with the broader optimizer framework (OptimizerConfig, OptimizationContext)
- Proper documentation of session lifecycle and guarantees

The contracts support incremental refinement through rounds, tracking metrics
at each iteration, and ensuring schema consistency across session lifetime.

Example:
    >>> from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    ...     LogicSessionConfig,
    ...     LogicSessionResult,
    ...     RoundResult,
    ...     ExtractionMetrics
    ... )
    >>>
    >>> config = LogicSessionConfig(
    ...     max_rounds=10,
    ...     convergence_threshold=0.85,
    ...     extraction_mode="AUTO",
    ...     use_provers=["z3", "cvc5"],
    ...     domain="legal"
    ... )
    >>> config.validate()  # Raises ValueError if invalid
    >>>
    >>> result = LogicSessionResult(
    ...     session_id="sess-001",
    ...     success=True,
    ...     converged=True,
    ...     num_rounds=5,
    ...     final_score=0.92,
    ...     total_time=12.5
    ... )
    >>> result_dict = result.to_dict()
    >>> restored = LogicSessionResult.from_dict(result_dict)
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Literal
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ExtractionMode(str, Enum):
    """Logic extraction formalism mode."""
    AUTO = "AUTO"
    FOL = "FOL"  # First-Order Logic
    TDFOL = "TDFOL"  # Temporal Deontic First-Order Logic
    CEC = "CEC"  # Constraint Execution Calculus
    MODAL = "MODAL"  # Modal logic
    DEONTIC = "DEONTIC"  # Deontic logic


class ConvergenceReason(str, Enum):
    """Reason for session convergence."""
    THRESHOLD_MET = "threshold_met"  # Score reached convergence threshold
    MAX_ROUNDS = "max_rounds"  # Reached maximum number of rounds
    NO_IMPROVEMENT = "no_improvement"  # Last round showed no improvement
    MANUAL_STOP = "manual_stop"  # Manually stopped by caller
    ERROR = "error"  # Stopped due to unrecoverable error


@dataclass
class ExtractionMetrics:
    """Metrics for a single extraction round.
    
    Tracks quality and performance metrics for each round of extraction
    and refinement.
    
    Attributes:
        num_statements: Number of logical statements extracted
        avg_confidence: Average confidence of statements (0-1)
        num_entities: Number of unique entities in statements
        num_relationships: Number of unique relationships
        num_contradictions: Number of detected contradictions
        prover_validation_success: Fraction of statements validated by prover
        extraction_time: Time spent on extraction in seconds
        critique_time: Time spent on critique in seconds
    """
    num_statements: int = 0
    avg_confidence: float = 0.0
    num_entities: int = 0
    num_relationships: int = 0
    num_contradictions: int = 0
    prover_validation_success: float = 0.0
    extraction_time: float = 0.0
    critique_time: float = 0.0
    
    def validate(self) -> None:
        """Validate metric constraints."""
        if self.num_statements < 0:
            raise ValueError("num_statements must be non-negative")
        if not (0.0 <= self.avg_confidence <= 1.0):
            raise ValueError("avg_confidence must be in [0, 1]")
        if self.num_entities < 0:
            raise ValueError("num_entities must be non-negative")
        if self.num_relationships < 0:
            raise ValueError("num_relationships must be non-negative")
        if self.num_contradictions < 0:
            raise ValueError("num_contradictions must be non-negative")
        if not (0.0 <= self.prover_validation_success <= 1.0):
            raise ValueError("prover_validation_success must be in [0, 1]")
        if self.extraction_time < 0:
            raise ValueError("extraction_time must be non-negative")
        if self.critique_time < 0:
            raise ValueError("critique_time must be non-negative")


@dataclass
class RoundResult:
    """Result of a single session round.
    
    Records all data from a single iteration of extraction-critique-optimize.
    
    Attributes:
        round_number: 1-indexed round number
        score: Overall quality score (0-1)
        dimension_scores: Dict of dimension → score (0-1)
        metrics: Extraction metrics for this round
        strengths: List of identified strengths
        weaknesses: List of identified weaknesses
        recommendations: List of improvement recommendations
        error: Error message if round failed, None otherwise
        timestamp: When this round completed
    """
    round_number: int
    score: float
    dimension_scores: Dict[str, float] = field(default_factory=dict)
    metrics: Optional[ExtractionMetrics] = None
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def validate(self) -> None:
        """Validate round result constraints."""
        if self.round_number <= 0:
            raise ValueError("round_number must be positive")
        if not (0.0 <= self.score <= 1.0):
            raise ValueError("score must be in [0, 1]")
        for dim, score in self.dimension_scores.items():
            if not isinstance(dim, str):
                raise ValueError(f"dimension keys must be strings, got {type(dim)}")
            if not (0.0 <= score <= 1.0):
                raise ValueError(f"dimension score {dim}={score} must be in [0, 1]")
        if self.metrics is not None:
            self.metrics.validate()
        if (self.error is not None) and self.score > 0.0:
            logger.warning(
                f"Round {self.round_number} has both error and score={self.score}"
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self, dict_factory=dict)
        result['timestamp'] = self.timestamp.isoformat()
        if self.metrics:
            result['metrics'] = asdict(self.metrics)
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RoundResult:
        """Create from dictionary."""
        data = dict(data)  # Copy to avoid mutation
        if isinstance(data.get('timestamp'), str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        if data.get('metrics'):
            data['metrics'] = ExtractionMetrics(**data['metrics'])
        return cls(**data)


@dataclass
class LogicSessionConfig:
    """Configuration for a logic extraction session.
    
    Strongly-typed configuration for logic theorem optimization sessions.
    All fields have proper type hints, constraints are validated, and
    the schema is compatible with the broader optimizer framework.
    
    Attributes:
        max_rounds: Maximum rounds of extraction and refinement (1-1000)
        convergence_threshold: Score needed to converge (0-1)
        extraction_mode: Logic formalism to use
        use_provers: List of theorem provers (e.g., ['z3', 'cvc5'])
        domain: Domain context (legal, medical, general, etc.)
        use_ontology: Whether to use ontology for consistency checking
        strict_evaluation: Whether to enforce strict evaluation criteria
        enable_caching: Whether to cache extraction results
        cache_max_size: Maximum cache size in MB (0 = disabled)
        learning_rate: Learning rate for adaptation (0-1)
        seed: Random seed for reproducibility
    """
    max_rounds: int = 10
    convergence_threshold: float = 0.85
    extraction_mode: ExtractionMode = ExtractionMode.AUTO
    use_provers: List[str] = field(default_factory=lambda: ["z3"])
    domain: str = "general"
    use_ontology: bool = True
    strict_evaluation: bool = False
    enable_caching: bool = True
    cache_max_size: int = 100  # MB
    learning_rate: float = 0.1
    seed: Optional[int] = None
    
    def validate(self) -> None:
        """Validate all field constraints."""
        if not (1 <= self.max_rounds <= 1000):
            raise ValueError("max_rounds must be in [1, 1000]")
        if not (0.0 <= self.convergence_threshold <= 1.0):
            raise ValueError("convergence_threshold must be in [0, 1]")
        if not isinstance(self.extraction_mode, ExtractionMode):
            raise ValueError(
                f"extraction_mode must be ExtractionMode, got {type(self.extraction_mode)}"
            )
        if not self.use_provers:
            raise ValueError("use_provers must not be empty")
        if not all(isinstance(p, str) for p in self.use_provers):
            raise ValueError("all prover names must be strings")
        if not isinstance(self.domain, str) or not self.domain:
            raise ValueError("domain must be a non-empty string")
        if not isinstance(self.use_ontology, bool):
            raise ValueError("use_ontology must be a boolean")
        if not isinstance(self.strict_evaluation, bool):
            raise ValueError("strict_evaluation must be a boolean")
        if not isinstance(self.enable_caching, bool):
            raise ValueError("enable_caching must be a boolean")
        if not (0 <= self.cache_max_size <= 10000):
            raise ValueError("cache_max_size must be in [0, 10000] MB")
        if not (0.0 <= self.learning_rate <= 1.0):
            raise ValueError("learning_rate must be in [0, 1]")
        if self.seed is not None and not isinstance(self.seed, int):
            raise ValueError("seed must be an integer or None")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        data['extraction_mode'] = self.extraction_mode.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LogicSessionConfig:
        """Create from dictionary."""
        data = dict(data)  # Copy to avoid mutation
        if isinstance(data.get('extraction_mode'), str):
            data['extraction_mode'] = ExtractionMode(data['extraction_mode'])
        return cls(**data)


@dataclass
class LogicSessionResult:
    """Result of a complete logic extraction session.
    
    Comprehensive result schema for a single extraction-critique-optimize
    session. Includes all metrics, history, and outcome information.
    
    Attributes:
        session_id: Unique session identifier
        success: Whether session completed successfully
        converged: Whether session converged to threshold
        convergence_reason: Reason for convergence (if converged)
        num_rounds: Number of rounds executed
        final_score: Final quality score (0-1)
        best_score: Best score achieved across all rounds
        improvement: Score improvement from first to last round
        total_time: Total execution time in seconds
        round_results: Per-round detailed results
        final_extraction: Final extracted logical statements (serialized)
        final_critic_score: Final critic score object (serialized)
        errors: List of errors encountered (if any)
        warnings: List of warnings encountered
        config: Session configuration snapshot
        created_at: When session was created
        completed_at: When session completed
    """
    session_id: str
    success: bool
    converged: bool
    num_rounds: int
    final_score: float
    total_time: float
    convergence_reason: Optional[ConvergenceReason] = None
    best_score: float = 0.0
    improvement: float = 0.0
    round_results: List[RoundResult] = field(default_factory=list)
    final_extraction: Optional[Dict[str, Any]] = None
    final_critic_score: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    config: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    def validate(self) -> None:
        """Validate result constraints."""
        if not self.session_id:
            raise ValueError("session_id must be non-empty")
        if not isinstance(self.success, bool):
            raise ValueError("success must be a boolean")
        if not isinstance(self.converged, bool):
            raise ValueError("converged must be a boolean")
        if self.num_rounds <= 0:
            raise ValueError("num_rounds must be positive")
        if not (0.0 <= self.final_score <= 1.0):
            raise ValueError("final_score must be in [0, 1]")
        if not (0.0 <= self.best_score <= 1.0):
            raise ValueError("best_score must be in [0, 1]")
        if self.total_time < 0:
            raise ValueError("total_time must be non-negative")
        if self.best_score < self.final_score:
            raise ValueError("best_score must be >= final_score")
        if len(self.round_results) != self.num_rounds:
            raise ValueError(
                f"round_results length ({len(self.round_results)}) "
                f"must match num_rounds ({self.num_rounds})"
            )
        for round_result in self.round_results:
            round_result.validate()
        if self.converged and self.convergence_reason is None:
            raise ValueError(
                "convergence_reason must be set when converged=True"
            )
        if not self.converged and self.convergence_reason is not None:
            raise ValueError(
                "convergence_reason should be None when converged=False"
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = {
            'session_id': self.session_id,
            'success': self.success,
            'converged': self.converged,
            'convergence_reason': (
                self.convergence_reason.value
                if self.convergence_reason
                else None
            ),
            'num_rounds': self.num_rounds,
            'final_score': self.final_score,
            'best_score': self.best_score,
            'improvement': self.improvement,
            'total_time': self.total_time,
            'round_results': [r.to_dict() for r in self.round_results],
            'final_extraction': self.final_extraction,
            'final_critic_score': self.final_critic_score,
            'errors': self.errors,
            'warnings': self.warnings,
            'config': self.config,
            'created_at': self.created_at.isoformat(),
            'completed_at': (
                self.completed_at.isoformat()
                if self.completed_at
                else None
            ),
        }
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LogicSessionResult:
        """Create from dictionary."""
        data = dict(data)  # Copy to avoid mutation
        
        # Parse datetime fields
        if isinstance(data.get('created_at'), str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if isinstance(data.get('completed_at'), str):
            data['completed_at'] = datetime.fromisoformat(data['completed_at'])
        
        # Parse convergence reason enum
        if isinstance(data.get('convergence_reason'), str):
            data['convergence_reason'] = ConvergenceReason(
                data['convergence_reason']
            )
        
        # Parse round results
        if data.get('round_results'):
            data['round_results'] = [
                RoundResult.from_dict(r) for r in data['round_results']
            ]
        
        return cls(**data)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a brief summary of session results.
        
        Returns:
            Dictionary with key metrics for quick review
        """
        if not self.success:
            return {
                'success': False,
                'num_rounds': self.num_rounds,
                'total_time': self.total_time,
                'errors': self.errors,
            }
        
        return {
            'success': True,
            'converged': self.converged,
            'convergence_reason': (
                self.convergence_reason.value
                if self.convergence_reason
                else None
            ),
            'num_rounds': self.num_rounds,
            'final_score': self.final_score,
            'best_score': self.best_score,
            'improvement': self.improvement,
            'total_time': self.total_time,
            'avg_round_time': self.total_time / self.num_rounds,
        }
