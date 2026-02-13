"""Neural-Symbolic Hybrid Prover for Logic Theorem Optimizer.

This module implements a hybrid prover that combines:
1. Neural reasoning (LLM-based semantic understanding)
2. Symbolic reasoning (traditional theorem provers)
3. Embedding-based similarity matching

The hybrid approach:
- Uses neural models to guide proof search
- Validates results with symbolic provers
- Falls back intelligently when one approach fails
- Combines confidence scores from both paradigms

Integration:
- Works with existing ProverIntegrationAdapter
- Uses SymbolicAI for neural reasoning
- Uses Z3/CVC5/Lean/Coq for symbolic verification
- Uses EmbeddingEnhancedProver for similarity matching
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time

logger = logging.getLogger(__name__)


class HybridStrategy(Enum):
    """Strategy for combining neural and symbolic provers."""
    NEURAL_FIRST = "neural_first"  # Try neural, fallback to symbolic
    SYMBOLIC_FIRST = "symbolic_first"  # Try symbolic, fallback to neural
    PARALLEL = "parallel"  # Run both concurrently
    ENSEMBLE = "ensemble"  # Weighted combination of both
    ADAPTIVE = "adaptive"  # Choose based on formula characteristics


@dataclass
class NeuralResult:
    """Result from neural prover component.
    
    Attributes:
        is_valid: Neural prediction of validity
        confidence: Neural confidence score (0.0-1.0)
        reasoning_steps: Natural language reasoning steps
        proof_sketch: Informal proof sketch
        llm_used: LLM model used for reasoning
        execution_time: Time taken for neural reasoning
        error_message: Error message if neural reasoning failed
    """
    is_valid: bool
    confidence: float
    reasoning_steps: List[str] = field(default_factory=list)
    proof_sketch: Optional[str] = None
    llm_used: Optional[str] = None
    execution_time: float = 0.0
    error_message: Optional[str] = None


@dataclass
class SymbolicResult:
    """Result from symbolic prover component.
    
    Attributes:
        is_valid: Symbolic verification result
        confidence: Symbolic confidence (1.0 if proved, 0.0 if not)
        proof: Formal proof if available
        prover_used: Symbolic prover used (z3, cvc5, etc.)
        execution_time: Time taken for symbolic verification
        error_message: Error message if verification failed
    """
    is_valid: bool
    confidence: float
    proof: Optional[str] = None
    prover_used: Optional[str] = None
    execution_time: float = 0.0
    error_message: Optional[str] = None


@dataclass
class HybridProverResult:
    """Result from hybrid neural-symbolic prover.
    
    Attributes:
        is_valid: Final validity decision
        confidence: Combined confidence score (0.0-1.0)
        neural_result: Result from neural component
        symbolic_result: Result from symbolic component
        strategy_used: Strategy that was used
        agreement: Whether neural and symbolic agree
        execution_time: Total execution time
        explanation: Human-readable explanation of result
    """
    is_valid: bool
    confidence: float
    neural_result: Optional[NeuralResult]
    symbolic_result: Optional[SymbolicResult]
    strategy_used: HybridStrategy
    agreement: bool
    execution_time: float
    explanation: str


class NeuralSymbolicHybridProver:
    """Hybrid prover combining neural and symbolic reasoning.
    
    This prover intelligently combines:
    - Neural LLM-based reasoning for semantic understanding
    - Symbolic theorem proving for rigorous verification
    - Embedding-based similarity for pattern matching
    
    Benefits:
    - Neural helps with complex formulas where symbolic provers struggle
    - Symbolic validates neural predictions
    - Hybrid approach is more robust than either alone
    - Can explain reasoning in natural language
    
    Example:
        >>> prover = NeuralSymbolicHybridProver(
        ...     strategy=HybridStrategy.PARALLEL,
        ...     neural_provers=['symbolicai'],
        ...     symbolic_provers=['z3', 'cvc5']
        ... )
        >>> result = prover.prove(formula, context)
        >>> print(f"Valid: {result.is_valid}, Confidence: {result.confidence:.2f}")
        >>> print(f"Explanation: {result.explanation}")
    """
    
    def __init__(
        self,
        strategy: HybridStrategy = HybridStrategy.PARALLEL,
        neural_provers: Optional[List[str]] = None,
        symbolic_provers: Optional[List[str]] = None,
        neural_weight: float = 0.4,
        symbolic_weight: float = 0.6,
        enable_embeddings: bool = True,
        cache_results: bool = True
    ):
        """Initialize the hybrid prover.
        
        Args:
            strategy: Strategy for combining provers
            neural_provers: List of neural prover names
            symbolic_provers: List of symbolic prover names
            neural_weight: Weight for neural results (0.0-1.0)
            symbolic_weight: Weight for symbolic results (0.0-1.0)
            enable_embeddings: Whether to use embedding similarity
            cache_results: Whether to cache proof results
        """
        self.strategy = strategy
        self.neural_provers = neural_provers or ['symbolicai']
        self.symbolic_provers = symbolic_provers or ['z3']
        self.neural_weight = neural_weight
        self.symbolic_weight = symbolic_weight
        self.enable_embeddings = enable_embeddings
        self.cache_results = cache_results
        
        # Normalize weights
        total_weight = neural_weight + symbolic_weight
        self.neural_weight = neural_weight / total_weight
        self.symbolic_weight = symbolic_weight / total_weight
        
        # Initialize components
        self._init_neural_component()
        self._init_symbolic_component()
        self._init_embedding_component()
        
        # Cache for results
        self.result_cache: Dict[str, HybridProverResult] = {}
        
        logger.info(
            f"Initialized NeuralSymbolicHybridProver with strategy={strategy.value}, "
            f"neural_weight={self.neural_weight:.2f}, symbolic_weight={self.symbolic_weight:.2f}"
        )
    
    def _init_neural_component(self) -> None:
        """Initialize neural prover component."""
        self.neural_component = None
        
        try:
            from ipfs_datasets_py.logic.external_provers.neural.symbolicai_prover_bridge import (
                SymbolicAIProverBridge
            )
            self.neural_component = SymbolicAIProverBridge()
            logger.info("Neural component initialized successfully")
        except ImportError:
            logger.warning("Neural prover component not available")
    
    def _init_symbolic_component(self) -> None:
        """Initialize symbolic prover component."""
        self.symbolic_component = None
        
        try:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prover_integration import (
                ProverIntegrationAdapter
            )
            self.symbolic_component = ProverIntegrationAdapter(
                use_provers=self.symbolic_provers
            )
            logger.info("Symbolic component initialized successfully")
        except ImportError:
            logger.warning("Symbolic prover component not available")
    
    def _init_embedding_component(self) -> None:
        """Initialize embedding-based similarity component."""
        self.embedding_component = None
        
        if not self.enable_embeddings:
            return
        
        try:
            from ipfs_datasets_py.logic.integration.neurosymbolic.embedding_prover import (
                EmbeddingEnhancedProver
            )
            self.embedding_component = EmbeddingEnhancedProver()
            logger.info("Embedding component initialized successfully")
        except ImportError:
            logger.warning("Embedding prover component not available")
    
    def prove(
        self,
        formula: str,
        context: Optional[Dict[str, Any]] = None,
        timeout: float = 10.0
    ) -> HybridProverResult:
        """Prove a formula using hybrid neural-symbolic approach.
        
        Args:
            formula: Formula to prove
            context: Additional context (axioms, definitions, etc.)
            timeout: Timeout for proof attempt (seconds)
        
        Returns:
            HybridProverResult with combined result
        """
        start_time = time.time()
        
        # Check cache
        if self.cache_results:
            cache_key = self._compute_cache_key(formula, context)
            if cache_key in self.result_cache:
                logger.info("Using cached hybrid proof result")
                return self.result_cache[cache_key]
        
        # Choose strategy
        if self.strategy == HybridStrategy.NEURAL_FIRST:
            result = self._prove_neural_first(formula, context, timeout)
        elif self.strategy == HybridStrategy.SYMBOLIC_FIRST:
            result = self._prove_symbolic_first(formula, context, timeout)
        elif self.strategy == HybridStrategy.PARALLEL:
            result = self._prove_parallel(formula, context, timeout)
        elif self.strategy == HybridStrategy.ENSEMBLE:
            result = self._prove_ensemble(formula, context, timeout)
        elif self.strategy == HybridStrategy.ADAPTIVE:
            result = self._prove_adaptive(formula, context, timeout)
        else:
            raise ValueError(f"Unknown strategy: {self.strategy}")
        
        result.execution_time = time.time() - start_time
        
        # Cache result
        if self.cache_results:
            self.result_cache[cache_key] = result
        
        return result
    
    def _prove_neural_first(
        self,
        formula: str,
        context: Optional[Dict[str, Any]],
        timeout: float
    ) -> HybridProverResult:
        """Try neural first, fallback to symbolic if needed."""
        neural_result = self._run_neural_prover(formula, context, timeout / 2)
        
        # If neural has high confidence, trust it
        if neural_result and neural_result.confidence >= 0.85:
            # But still verify with symbolic if available
            symbolic_result = self._run_symbolic_prover(formula, context, timeout / 2)
            agreement = (
                symbolic_result is not None 
                and symbolic_result.is_valid == neural_result.is_valid
            )
            
            return HybridProverResult(
                is_valid=neural_result.is_valid,
                confidence=neural_result.confidence,
                neural_result=neural_result,
                symbolic_result=symbolic_result,
                strategy_used=HybridStrategy.NEURAL_FIRST,
                agreement=agreement,
                execution_time=0.0,
                explanation=self._generate_explanation(neural_result, symbolic_result)
            )
        
        # Low neural confidence, use symbolic
        symbolic_result = self._run_symbolic_prover(formula, context, timeout / 2)
        
        if symbolic_result:
            agreement = (
                neural_result is not None 
                and symbolic_result.is_valid == neural_result.is_valid
            )
            
            return HybridProverResult(
                is_valid=symbolic_result.is_valid,
                confidence=symbolic_result.confidence,
                neural_result=neural_result,
                symbolic_result=symbolic_result,
                strategy_used=HybridStrategy.NEURAL_FIRST,
                agreement=agreement,
                execution_time=0.0,
                explanation=self._generate_explanation(neural_result, symbolic_result)
            )
        
        # Only neural available
        return HybridProverResult(
            is_valid=neural_result.is_valid if neural_result else False,
            confidence=neural_result.confidence if neural_result else 0.0,
            neural_result=neural_result,
            symbolic_result=None,
            strategy_used=HybridStrategy.NEURAL_FIRST,
            agreement=False,
            execution_time=0.0,
            explanation="Only neural prover available, low confidence"
        )
    
    def _prove_symbolic_first(
        self,
        formula: str,
        context: Optional[Dict[str, Any]],
        timeout: float
    ) -> HybridProverResult:
        """Try symbolic first, fallback to neural if needed."""
        symbolic_result = self._run_symbolic_prover(formula, context, timeout / 2)
        
        # If symbolic succeeds, trust it
        if symbolic_result and symbolic_result.confidence >= 0.95:
            # But get neural explanation
            neural_result = self._run_neural_prover(formula, context, timeout / 2)
            agreement = (
                neural_result is not None 
                and neural_result.is_valid == symbolic_result.is_valid
            )
            
            return HybridProverResult(
                is_valid=symbolic_result.is_valid,
                confidence=symbolic_result.confidence,
                neural_result=neural_result,
                symbolic_result=symbolic_result,
                strategy_used=HybridStrategy.SYMBOLIC_FIRST,
                agreement=agreement,
                execution_time=0.0,
                explanation=self._generate_explanation(neural_result, symbolic_result)
            )
        
        # Symbolic failed or unavailable, try neural
        neural_result = self._run_neural_prover(formula, context, timeout / 2)
        
        if neural_result:
            agreement = (
                symbolic_result is not None 
                and neural_result.is_valid == symbolic_result.is_valid
            )
            
            return HybridProverResult(
                is_valid=neural_result.is_valid,
                confidence=neural_result.confidence,
                neural_result=neural_result,
                symbolic_result=symbolic_result,
                strategy_used=HybridStrategy.SYMBOLIC_FIRST,
                agreement=agreement,
                execution_time=0.0,
                explanation=self._generate_explanation(neural_result, symbolic_result)
            )
        
        # Both failed
        return HybridProverResult(
            is_valid=False,
            confidence=0.0,
            neural_result=None,
            symbolic_result=symbolic_result,
            strategy_used=HybridStrategy.SYMBOLIC_FIRST,
            agreement=False,
            execution_time=0.0,
            explanation="Both symbolic and neural provers failed"
        )
    
    def _prove_parallel(
        self,
        formula: str,
        context: Optional[Dict[str, Any]],
        timeout: float
    ) -> HybridProverResult:
        """Run neural and symbolic provers in parallel."""
        # For now, run sequentially (true parallelism would require threading)
        neural_result = self._run_neural_prover(formula, context, timeout)
        symbolic_result = self._run_symbolic_prover(formula, context, timeout)
        
        # Combine results
        if neural_result and symbolic_result:
            agreement = neural_result.is_valid == symbolic_result.is_valid
            
            # If they agree, high confidence
            if agreement:
                confidence = max(neural_result.confidence, symbolic_result.confidence)
                is_valid = neural_result.is_valid
            else:
                # They disagree, use weighted combination
                neural_score = neural_result.confidence if neural_result.is_valid else 0.0
                symbolic_score = symbolic_result.confidence if symbolic_result.is_valid else 0.0
                combined_score = (
                    neural_score * self.neural_weight +
                    symbolic_score * self.symbolic_weight
                )
                confidence = combined_score
                is_valid = combined_score >= 0.5
            
            return HybridProverResult(
                is_valid=is_valid,
                confidence=confidence,
                neural_result=neural_result,
                symbolic_result=symbolic_result,
                strategy_used=HybridStrategy.PARALLEL,
                agreement=agreement,
                execution_time=0.0,
                explanation=self._generate_explanation(neural_result, symbolic_result)
            )
        
        # Only one available
        if neural_result:
            return HybridProverResult(
                is_valid=neural_result.is_valid,
                confidence=neural_result.confidence * 0.7,  # Reduced confidence
                neural_result=neural_result,
                symbolic_result=None,
                strategy_used=HybridStrategy.PARALLEL,
                agreement=False,
                execution_time=0.0,
                explanation="Only neural prover available"
            )
        
        if symbolic_result:
            return HybridProverResult(
                is_valid=symbolic_result.is_valid,
                confidence=symbolic_result.confidence,
                neural_result=None,
                symbolic_result=symbolic_result,
                strategy_used=HybridStrategy.PARALLEL,
                agreement=False,
                execution_time=0.0,
                explanation="Only symbolic prover available"
            )
        
        # Neither available
        return HybridProverResult(
            is_valid=False,
            confidence=0.0,
            neural_result=None,
            symbolic_result=None,
            strategy_used=HybridStrategy.PARALLEL,
            agreement=False,
            execution_time=0.0,
            explanation="No provers available"
        )
    
    def _prove_ensemble(
        self,
        formula: str,
        context: Optional[Dict[str, Any]],
        timeout: float
    ) -> HybridProverResult:
        """Use weighted ensemble of both approaches."""
        return self._prove_parallel(formula, context, timeout)
    
    def _prove_adaptive(
        self,
        formula: str,
        context: Optional[Dict[str, Any]],
        timeout: float
    ) -> HybridProverResult:
        """Adaptively choose strategy based on formula characteristics."""
        # Simple heuristic: use neural for complex formulas, symbolic for simple ones
        if len(formula) > 200 or "∀" in formula or "∃" in formula:
            # Complex formula, prefer neural
            return self._prove_neural_first(formula, context, timeout)
        else:
            # Simple formula, prefer symbolic
            return self._prove_symbolic_first(formula, context, timeout)
    
    def _run_neural_prover(
        self,
        formula: str,
        context: Optional[Dict[str, Any]],
        timeout: float
    ) -> Optional[NeuralResult]:
        """Run neural prover component."""
        if not self.neural_component:
            return None
        
        start_time = time.time()
        
        try:
            # Call SymbolicAI prover
            result = self.neural_component.prove(
                formula,
                strategy='neural_guided',
                timeout=timeout
            )
            
            return NeuralResult(
                is_valid=result.is_valid,
                confidence=result.confidence,
                reasoning_steps=result.reasoning,
                proof_sketch=result.proof_sketch,
                llm_used=result.llm_used,
                execution_time=time.time() - start_time
            )
        except Exception as e:
            logger.warning(f"Neural prover failed: {e}")
            return NeuralResult(
                is_valid=False,
                confidence=0.0,
                execution_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def _run_symbolic_prover(
        self,
        formula: str,
        context: Optional[Dict[str, Any]],
        timeout: float
    ) -> Optional[SymbolicResult]:
        """Run symbolic prover component."""
        if not self.symbolic_component:
            return None
        
        start_time = time.time()
        
        try:
            # Create statement for prover
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor import (
                LogicalStatement
            )
            
            statement = LogicalStatement(
                formula=formula,
                formalism="fol",
                confidence=1.0,
                metadata=context or {}
            )
            
            # Call symbolic prover
            result = self.symbolic_component.verify_statement(statement)
            
            return SymbolicResult(
                is_valid=result.overall_valid,
                confidence=result.confidence,
                prover_used=result.verified_by[0] if result.verified_by else None,
                execution_time=time.time() - start_time
            )
        except Exception as e:
            logger.warning(f"Symbolic prover failed: {e}")
            return SymbolicResult(
                is_valid=False,
                confidence=0.0,
                execution_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def _compute_cache_key(
        self,
        formula: str,
        context: Optional[Dict[str, Any]]
    ) -> str:
        """Compute cache key for formula and context."""
        import hashlib
        
        context_str = str(sorted(context.items())) if context else ""
        key_str = f"{formula}:{context_str}"
        return hashlib.sha256(key_str.encode()).hexdigest()
    
    def _generate_explanation(
        self,
        neural_result: Optional[NeuralResult],
        symbolic_result: Optional[SymbolicResult]
    ) -> str:
        """Generate human-readable explanation of result."""
        parts = []
        
        if neural_result:
            parts.append(
                f"Neural prover ({neural_result.llm_used or 'unknown'}): "
                f"{'Valid' if neural_result.is_valid else 'Invalid'} "
                f"(confidence {neural_result.confidence:.2f})"
            )
            if neural_result.reasoning_steps:
                parts.append("Reasoning: " + " → ".join(neural_result.reasoning_steps[:3]))
        
        if symbolic_result:
            parts.append(
                f"Symbolic prover ({symbolic_result.prover_used or 'unknown'}): "
                f"{'Valid' if symbolic_result.is_valid else 'Invalid'} "
                f"(confidence {symbolic_result.confidence:.2f})"
            )
        
        if neural_result and symbolic_result:
            if neural_result.is_valid == symbolic_result.is_valid:
                parts.append("✓ Neural and symbolic provers agree")
            else:
                parts.append("✗ Neural and symbolic provers disagree")
        
        return " | ".join(parts) if parts else "No explanation available"
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about hybrid prover usage.
        
        Returns:
            Dictionary with statistics
        """
        return {
            'cache_size': len(self.result_cache),
            'strategy': self.strategy.value,
            'neural_weight': self.neural_weight,
            'symbolic_weight': self.symbolic_weight,
            'neural_available': self.neural_component is not None,
            'symbolic_available': self.symbolic_component is not None,
            'embedding_available': self.embedding_component is not None
        }
    
    def clear_cache(self) -> None:
        """Clear the result cache."""
        self.result_cache.clear()
        logger.info("Hybrid prover cache cleared")
