"""Unified Logic Theorem Optimizer using BaseOptimizer.

This module provides a unified interface for logic theorem optimization
by wrapping existing components (LogicExtractor, LogicCritic, LogicOptimizer)
with the BaseOptimizer interface.

This eliminates duplicate code patterns and provides consistency with other
optimizer types while preserving all existing functionality.

Example:
    >>> from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicTheoremOptimizer
    >>> from ipfs_datasets_py.optimizers.common import OptimizerConfig, OptimizationContext
    >>> 
    >>> config = OptimizerConfig(max_iterations=5, target_score=0.85)
    >>> optimizer = LogicTheoremOptimizer(config=config)
    >>> 
    >>> context = OptimizationContext(
    ...     session_id="session-001",
    ...     input_data=text_data,
    ...     domain="legal"
    ... )
    >>> result = optimizer.run_session(text_data, context)
    >>> print(f"Score: {result['score']}, Valid: {result['valid']}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional, Tuple

from ..common.base_optimizer import (
    BaseOptimizer,
    OptimizerConfig,
    OptimizationContext,
    OptimizationStrategy,
)
from .logic_extractor import (
    LogicExtractor,
    LogicExtractionContext,
    ExtractionMode,
    DataType,
    ExtractionResult,
)
from .logic_critic import (
    LogicCritic,
    CriticScore,
    CriticDimensions,
)
from .logic_optimizer import LogicOptimizer as LegacyLogicOptimizer
from .prover_integration import ProverIntegrationAdapter

logger = logging.getLogger(__name__)


@dataclass
class StatementValidationResult:
    """Result of validating one or more logical statements."""

    all_valid: bool
    provers_used: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


class LogicTheoremOptimizer(BaseOptimizer):
    """Unified optimizer for logic theorem extraction and validation.
    
    This optimizer implements the BaseOptimizer interface for logic theorem
    optimization. It wraps existing logic_theorem_optimizer components:
    
    - LogicExtractor: Generates logical statements from input data
    - LogicCritic: Evaluates logical consistency and quality
    - LogicOptimizer: Provides improvement recommendations
    - ProverIntegration: Validates statements with theorem provers
    
    The optimizer supports multiple logic formalisms (FOL, TDFOL, CEC, Modal,
    Deontic) and can validate using Z3, CVC5, Lean, or Coq theorem provers.
    
    Args:
        config: Optimizer configuration
        llm_backend: Optional LLM backend for extraction
        extraction_mode: Logic formalism to extract (default: AUTO)
        use_provers: List of theorem provers to use (default: ['z3'])
        domain: Domain context (legal, medical, general, etc.)
    
    Example:
        >>> optimizer = LogicTheoremOptimizer(
        ...     config=OptimizerConfig(target_score=0.9),
        ...     extraction_mode=ExtractionMode.TDFOL,
        ...     use_provers=['z3', 'cvc5'],
        ...     domain='legal'
        ... )
        >>> context = OptimizationContext(
        ...     session_id='legal-001',
        ...     input_data=contract_text,
        ...     domain='legal'
        ... )
        >>> result = optimizer.run_session(contract_text, context)
    """
    
    def __init__(
        self,
        config: Optional[OptimizerConfig] = None,
        llm_backend: Optional[Any] = None,
        extraction_mode: ExtractionMode = ExtractionMode.AUTO,
        use_provers: Optional[List[str]] = None,
        enable_caching: bool = True,
        domain: str = "general",
        metrics_collector: Optional[Any] = None,
    ):
        """Initialize the unified logic theorem optimizer.
        
        Args:
            config: Optimizer configuration
            llm_backend: Optional LLM backend for extraction
            extraction_mode: Logic formalism to extract
            use_provers: Theorem provers to use for validation
            domain: Domain context
            metrics_collector: Optional :class:`~ipfs_datasets_py.optimizers.common.PerformanceMetricsCollector`
                instance.  When provided, each ``run_session()`` call records
                timing and success/failure via ``start_cycle`` / ``end_cycle``.
        """
        super().__init__(config=config, llm_backend=llm_backend, metrics_collector=metrics_collector)
        
        # Initialize components
        self.extractor = LogicExtractor(backend=llm_backend)
        self.critic = LogicCritic(use_provers=use_provers or ['z3'])
        self.legacy_optimizer = LegacyLogicOptimizer()
        self.prover_adapter = ProverIntegrationAdapter(
            use_provers=use_provers or ['z3'],
            enable_cache=enable_caching,
        )
        
        # Store settings
        self.extraction_mode = extraction_mode
        self.domain = domain
        
        # Track extraction history for optimization
        self.extraction_history: List[ExtractionResult] = []

    def validate_statements(
        self,
        statements: List[Any],
        context: Optional[OptimizationContext] = None,
        timeout: Optional[float] = None,
    ) -> StatementValidationResult:
        """Validate one or more statements using configured theorem provers.

        This is a lightweight adapter around `ProverIntegrationAdapter.verify_statement`.
        It is intentionally conservative: if no provers are available or any statement
        is not verified as valid, the result is `all_valid=False`.
        """
        errors: List[str] = []
        per_statement: List[Dict[str, Any]] = []
        verified_by: List[str] = []

        for idx, statement in enumerate(statements, start=1):
            aggregated = self.prover_adapter.verify_statement(
                statement,
                timeout=timeout,
            )
            per_statement.append(
                {
                    'index': idx,
                    'statement': str(statement),
                    'overall_valid': aggregated.overall_valid,
                    'confidence': aggregated.confidence,
                    'agreement_rate': aggregated.agreement_rate,
                    'verified_by': aggregated.verified_by,
                }
            )
            verified_by.extend(list(aggregated.verified_by or []))
            if not aggregated.overall_valid:
                errors.append(f"Statement {idx} failed verification")

        provers_used = sorted(set(verified_by)) or list(self.prover_adapter.use_provers)
        all_valid = len(errors) == 0

        return StatementValidationResult(
            all_valid=all_valid,
            provers_used=provers_used,
            errors=errors,
            details={'statements': per_statement},
        )
        
    def generate(
        self,
        input_data: Any,
        context: OptimizationContext,
    ) -> ExtractionResult:
        """Generate initial logical statements from input data.
        
        Uses LogicExtractor to extract formal logic statements from the
        input data. Supports various data types (text, JSON, knowledge graphs)
        and logic formalisms (FOL, TDFOL, CEC, etc.).
        
        Args:
            input_data: Input data to extract logic from
            context: Optimization context
            
        Returns:
            ExtractionResult containing logical statements
            
        Raises:
            ValueError: If input data is invalid
            RuntimeError: If extraction fails
        """
        try:
            # Determine data type
            data_type = self._infer_data_type(input_data)
            
            # Create extraction context
            extraction_context = LogicExtractionContext(
                data=input_data,
                data_type=data_type,
                extraction_mode=self.extraction_mode,
                domain=context.domain or self.domain,
                previous_extractions=self.extraction_history[-3:],  # Last 3 for context
                hints=context.metadata.get('hints'),
            )
            
            # Extract logical statements
            result = self.extractor.extract(extraction_context)
            
            if not result.success:
                raise RuntimeError(f"Extraction failed: {result.errors}")
            
            # Store in history
            self.extraction_history.append(result)
            
            logger.info(
                f"Generated {len(result.statements)} logical statements "
                f"using {self.extraction_mode.value} formalism"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Generation failed: {e}")
            raise RuntimeError(f"Failed to generate logical statements: {e}")
    
    def critique(
        self,
        artifact: ExtractionResult,
        context: OptimizationContext,
    ) -> Tuple[float, List[str]]:
        """Evaluate quality of extracted logical statements.
        
        Uses LogicCritic to evaluate the statements across multiple dimensions:
        - Soundness: Logical validity
        - Completeness: Coverage of input data
        - Consistency: Internal consistency
        - Ontology Alignment: Alignment with knowledge graph
        - Parsability: Can be parsed by theorem provers
        - Expressiveness: Captures nuance
        
        Args:
            artifact: ExtractionResult to evaluate
            context: Optimization context
            
        Returns:
            Tuple of (overall_score, feedback_list)
            - overall_score: Weighted score from 0 to 1
            - feedback_list: List of improvement suggestions
            
        Raises:
            ValueError: If artifact is invalid
        """
        try:
            # Evaluate with critic
            critic_score: CriticScore = self.critic.evaluate(artifact)
            
            # Build feedback list from critic results
            feedback = []
            
            # Add weaknesses as feedback
            feedback.extend(critic_score.weaknesses)
            
            # Add specific recommendations
            feedback.extend(critic_score.recommendations)
            
            # Add dimension-specific feedback
            for dim_score in critic_score.dimension_scores:
                if dim_score.score < 0.7:  # Below acceptable threshold
                    feedback.append(
                        f"Improve {dim_score.dimension.value}: {dim_score.feedback}"
                    )
            
            logger.info(
                f"Critique complete: score={critic_score.overall:.2f}, "
                f"feedback_count={len(feedback)}"
            )
            
            return critic_score.overall, feedback
            
        except Exception as e:
            logger.error(f"Critique failed: {e}")
            raise ValueError(f"Failed to critique artifact: {e}")
    
    def optimize(
        self,
        artifact: ExtractionResult,
        score: float,
        feedback: List[str],
        context: OptimizationContext,
    ) -> ExtractionResult:
        """Improve logical statements based on critique feedback.
        
        Uses LogicOptimizer to analyze feedback and generate improved
        logical statements. Applies recommendations to refine extraction.
        
        Args:
            artifact: Current extraction result
            score: Current quality score
            feedback: List of improvement suggestions
            context: Optimization context
            
        Returns:
            Improved ExtractionResult
            
        Raises:
            RuntimeError: If optimization fails
        """
        try:
            # Analyze feedback with legacy optimizer
            # (This provides strategic guidance for improvement)
            optimization_report = self.legacy_optimizer.analyze_batch(
                [artifact]  # Wrap in list for batch analysis
            )
            
            # Combine feedback from critique and optimizer
            combined_feedback = feedback + optimization_report.recommendations
            
            # Create improved extraction context with feedback
            improved_context = LogicExtractionContext(
                data=artifact.context.data,
                data_type=artifact.context.data_type,
                extraction_mode=artifact.context.extraction_mode,
                domain=artifact.context.domain,
                ontology=artifact.context.ontology,
                previous_extractions=self.extraction_history[-3:],
                hints=combined_feedback,  # Use feedback as hints
            )
            
            # Re-extract with improved context
            improved_result = self.extractor.extract(improved_context)
            
            if not improved_result.success:
                logger.warning(
                    f"Optimization extraction failed, returning original: "
                    f"{improved_result.errors}"
                )
                return artifact  # Return original if optimization fails
            
            # Store improved result
            self.extraction_history.append(improved_result)
            
            logger.info(
                f"Optimization complete: {len(improved_result.statements)} statements, "
                f"previous_score={score:.2f}"
            )
            
            return improved_result
            
        except Exception as e:
            logger.error(f"Optimization failed: {e}")
            # Return original artifact rather than failing completely
            logger.warning("Returning original artifact due to optimization failure")
            return artifact
    
    def validate(
        self,
        artifact: ExtractionResult,
        context: OptimizationContext,
    ) -> bool:
        """Validate logical statements using theorem provers.
        
        Uses ProverIntegration to validate statements with configured
        theorem provers (Z3, CVC5, Lean, Coq). Checks for:
        - Syntactic validity
        - Logical consistency
        - Satisfiability
        
        Args:
            artifact: ExtractionResult to validate
            context: Optimization context
            
        Returns:
            True if statements are valid, False otherwise
        """
        try:
            # Validate each statement with provers
            all_valid = True
            validation_results = []
            
            for statement in artifact.statements:
                # Validate with prover integration
                is_valid = self.prover_adapter.validate_statement(
                    statement.formula,
                    statement.formalism
                )
                validation_results.append(is_valid)
                all_valid = all_valid and is_valid
            
            valid_count = sum(validation_results)
            total_count = len(validation_results)
            
            logger.info(
                f"Validation complete: {valid_count}/{total_count} statements valid"
            )
            
            # Return True if at least 80% are valid (allow some tolerance)
            return valid_count >= (total_count * 0.8) if total_count > 0 else True
            
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            # On validation error, be conservative and return False
            return False
    
    def _infer_data_type(self, input_data: Any) -> DataType:
        """Infer data type from input data.
        
        Args:
            input_data: Input data to infer type from
            
        Returns:
            Inferred DataType
        """
        if isinstance(input_data, str):
            return DataType.TEXT
        elif isinstance(input_data, dict):
            # Check if it's a knowledge graph structure
            if 'nodes' in input_data and 'edges' in input_data:
                return DataType.KNOWLEDGE_GRAPH
            return DataType.JSON
        elif isinstance(input_data, (list, tuple)):
            return DataType.STRUCTURED
        else:
            return DataType.MIXED
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Get optimizer capabilities.
        
        Returns:
            Dictionary describing capabilities including:
            - Base optimizer capabilities
            - Supported logic formalisms
            - Available theorem provers
            - Evaluation dimensions
        """
        base_capabilities = super().get_capabilities()
        
        logic_capabilities = {
            'extraction_modes': [mode.value for mode in ExtractionMode],
            'theorem_provers': self.prover_adapter.get_available_provers(),
            'evaluation_dimensions': [dim.value for dim in CriticDimensions],
            'domain': self.domain,
            'current_extraction_mode': self.extraction_mode.value,
        }
        
        return {**base_capabilities, **logic_capabilities}
