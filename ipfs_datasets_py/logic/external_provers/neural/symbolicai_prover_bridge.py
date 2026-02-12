"""
SymbolicAI Neural Prover Integration for TDFOL

This module integrates the ExtensityAI/SymbolicAI framework as a "neural prover"
that uses LLMs to guide theorem proving, validate formulas, and provide
natural language explanations.

SymbolicAI provides:
- LLM-powered semantic reasoning
- Natural language ↔ Logic conversion  
- Neural-guided proof search
- Confidence scoring and validation
- Multi-engine fallback (OpenAI, Anthropic, etc.)

This complements traditional provers (Z3, CVC5) and native inference rules
by adding neural pattern matching and semantic understanding.

Usage:
    >>> from ipfs_datasets_py.logic.external_provers import SymbolicAIProverBridge
    >>> prover = SymbolicAIProverBridge()
    >>> result = prover.prove(formula, strategy='neural_guided')
    
    >>> # Get natural language explanation
    >>> explanation = prover.explain(formula)
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union
import time
import logging

logger = logging.getLogger(__name__)

# Check SymbolicAI availability
try:
    from symai import Symbol, Expression
    SYMBOLICAI_AVAILABLE = True
except (ImportError, SystemExit):
    SYMBOLICAI_AVAILABLE = False
    Symbol = None
    Expression = None
    logger.warning("SymbolicAI not available. Install with: pip install symbolicai")

# Import existing SymbolicAI integration for code reuse
try:
    from ipfs_datasets_py.logic.integration.symbolic_fol_bridge import (
        SymbolicFOLBridge,
        FOLConversionResult,
        LogicalComponents
    )
    SYMBOLIC_FOL_BRIDGE_AVAILABLE = True
except ImportError:
    SYMBOLIC_FOL_BRIDGE_AVAILABLE = False
    logger.warning("SymbolicFOLBridge not available")


@dataclass
class NeuralProofResult:
    """Result from SymbolicAI neural prover.
    
    Attributes:
        is_valid: True if formula appears valid based on neural reasoning
        confidence: Confidence score (0.0 to 1.0)
        reasoning: Natural language reasoning steps
        proof_sketch: Informal proof sketch
        counterexample: Potential counterexample if not valid
        fallback_used: Whether fallback to symbolic prover was used
        proof_time: Time taken to reason
        llm_used: LLM engine used (gpt-4, claude, etc.)
    """
    is_valid: bool
    confidence: float
    reasoning: List[str]
    proof_sketch: Optional[str]
    counterexample: Optional[str]
    fallback_used: bool
    proof_time: float
    llm_used: Optional[str]
    
    def is_proved(self) -> bool:
        """Check if formula was proved with high confidence."""
        return self.is_valid and self.confidence >= 0.8


class SymbolicAIProverBridge:
    """Bridge between TDFOL and SymbolicAI for neural-guided proving.
    
    This prover uses LLMs to:
    1. Understand formula semantics
    2. Suggest proof strategies
    3. Validate logical steps
    4. Generate natural language explanations
    5. Guide symbolic proof search
    
    This is a "neural prover" that complements traditional SMT solvers
    and native inference rules by adding semantic understanding and
    natural language reasoning capabilities.
    
    Attributes:
        confidence_threshold: Minimum confidence for accepting proofs
        use_symbolic_fallback: Fall back to symbolic prover if confidence low
        enable_explanation: Generate natural language explanations
        llm_engine: LLM engine to use (default: auto)
    """
    
    def __init__(
        self,
        confidence_threshold: float = 0.8,
        use_symbolic_fallback: bool = True,
        enable_explanation: bool = True,
        llm_engine: Optional[str] = None,
        timeout: Optional[float] = 30.0,
        enable_cache: bool = True
    ):
        """Initialize SymbolicAI prover bridge.
        
        Args:
            confidence_threshold: Minimum confidence for accepting proofs
            use_symbolic_fallback: Fall back to symbolic prover
            enable_explanation: Generate explanations
            llm_engine: LLM engine name (None = auto)
            timeout: Timeout in seconds
            enable_cache: Whether to enable proof caching
        """
        if not SYMBOLICAI_AVAILABLE:
            raise ImportError(
                "SymbolicAI not available. Install with: pip install symbolicai"
            )
        
        self.confidence_threshold = confidence_threshold
        self.use_symbolic_fallback = use_symbolic_fallback
        self.enable_explanation = enable_explanation
        self.llm_engine = llm_engine
        self.timeout = timeout
        self.enable_cache = enable_cache
        
        # Initialize cache if enabled
        self._cache = None
        if self.enable_cache:
            try:
                from ..proof_cache import get_global_cache
                self._cache = get_global_cache()
            except ImportError:
                self.enable_cache = False
                logger.warning("Proof cache not available")
        
        # Initialize SymbolicFOL bridge if available (code reuse!)
        self.fol_bridge = None
        if SYMBOLIC_FOL_BRIDGE_AVAILABLE:
            self.fol_bridge = SymbolicFOLBridge(
                confidence_threshold=confidence_threshold,
                fallback_enabled=use_symbolic_fallback,
                enable_caching=True
            )
    
    def prove(
        self,
        formula,
        axioms: Optional[List] = None,
        strategy: str = 'neural_guided',
        timeout: Optional[float] = None
    ) -> NeuralProofResult:
        """Prove a TDFOL formula using neural reasoning.
        
        Args:
            formula: TDFOL formula to prove
            axioms: Optional list of axiom formulas
            strategy: Proving strategy ('neural_guided', 'pure_neural', 'hybrid')
            timeout: Timeout in seconds
            
        Returns:
            NeuralProofResult with proof status and reasoning
        """
        # Check cache first (O(1) lookup via CID)
        # This is especially important for LLM-based proving to avoid expensive API calls!
        if self.enable_cache and self._cache is not None:
            cached_result = self._cache.get(
                formula,
                axioms=axioms,
                prover_name="SymbolicAI",
                prover_config={'strategy': strategy, 'timeout': timeout}
            )
            if cached_result is not None:
                logger.info("SymbolicAI cache HIT - avoiding expensive LLM call")
                return cached_result
        
        start_time = time.time()
        timeout = timeout or self.timeout
        
        try:
            # Convert formula to string for LLM
            formula_str = str(formula)
            
            # Build context with axioms
            context = self._build_context(formula_str, axioms)
            
            # Use SymbolicAI to reason about the formula
            if strategy == 'neural_guided':
                result = self._prove_neural_guided(formula_str, context, timeout)
            elif strategy == 'pure_neural':
                result = self._prove_pure_neural(formula_str, context, timeout)
            elif strategy == 'hybrid':
                result = self._prove_hybrid(formula, formula_str, context, timeout)
            else:
                raise ValueError(f"Unknown strategy: {strategy}")
            
            result.proof_time = time.time() - start_time
            
            # Cache the result (especially important for expensive LLM calls!)
            if self.enable_cache and self._cache is not None:
                self._cache.set(
                    formula,
                    result,
                    axioms=axioms,
                    prover_name="SymbolicAI",
                    prover_config={'strategy': strategy, 'timeout': timeout}
                )
            
            return result
        
        except Exception as e:
            logger.error(f"Error in neural proving: {e}")
            return NeuralProofResult(
                is_valid=False,
                confidence=0.0,
                reasoning=[f"Error: {str(e)}"],
                proof_sketch=None,
                counterexample=None,
                fallback_used=False,
                proof_time=time.time() - start_time,
                llm_used=self.llm_engine
            )
    
    def _build_context(self, formula_str: str, axioms: Optional[List]) -> str:
        """Build context string for LLM."""
        context = f"Formula to prove: {formula_str}\n"
        
        if axioms:
            context += "\nGiven axioms:\n"
            for i, axiom in enumerate(axioms, 1):
                context += f"{i}. {str(axiom)}\n"
        
        return context
    
    def _prove_neural_guided(
        self,
        formula_str: str,
        context: str,
        timeout: float
    ) -> NeuralProofResult:
        """Prove using neural guidance with symbolic fallback."""
        
        # Create a Symbol for the proving task
        proving_task = Symbol(f"""
You are a mathematical logic expert. Analyze the following logical formula:

{context}

Task:
1. Determine if this formula is valid (always true)
2. Explain your reasoning step by step
3. Provide a proof sketch if valid, or a counterexample if not
4. Rate your confidence (0-100%)

Respond in this format:
VALID: [yes/no]
CONFIDENCE: [0-100]
REASONING:
[step by step reasoning]
PROOF/COUNTEREXAMPLE:
[proof sketch or counterexample]
""", semantic=True)
        
        # Query the LLM
        response = proving_task.query(
            "Analyze this logical formula and provide your assessment."
        )
        
        # Parse response
        return self._parse_llm_response(response, fallback_used=False)
    
    def _prove_pure_neural(
        self,
        formula_str: str,
        context: str,
        timeout: float
    ) -> NeuralProofResult:
        """Prove using pure neural reasoning (no symbolic fallback)."""
        return self._prove_neural_guided(formula_str, context, timeout)
    
    def _prove_hybrid(
        self,
        formula,
        formula_str: str,
        context: str,
        timeout: float
    ) -> NeuralProofResult:
        """Prove using hybrid neural + symbolic approach."""
        
        # First try neural reasoning
        neural_result = self._prove_neural_guided(formula_str, context, timeout)
        
        # If confidence is low, try symbolic prover
        if neural_result.confidence < self.confidence_threshold:
            if self.use_symbolic_fallback:
                try:
                    # Try TDFOL prover
                    from ipfs_datasets_py.logic.TDFOL import TDFOLProver
                    symbolic_prover = TDFOLProver()
                    symbolic_result = symbolic_prover.prove(formula)
                    
                    if symbolic_result.is_proved():
                        # Symbolic prover confirmed
                        neural_result.is_valid = True
                        neural_result.confidence = 0.95
                        neural_result.reasoning.append(
                            "Symbolic prover confirmed the result"
                        )
                        neural_result.fallback_used = True
                except Exception as e:
                    logger.warning(f"Symbolic fallback failed: {e}")
        
        return neural_result
    
    def _parse_llm_response(
        self,
        response: str,
        fallback_used: bool = False
    ) -> NeuralProofResult:
        """Parse LLM response into NeuralProofResult."""
        
        # Extract is_valid
        is_valid = False
        if 'valid:' in response.lower():
            valid_line = response.lower().split('valid:')[1].split('\n')[0]
            is_valid = 'yes' in valid_line
        
        # Extract confidence
        confidence = 0.5  # default
        if 'confidence:' in response.lower():
            try:
                conf_str = response.lower().split('confidence:')[1].split('\n')[0]
                confidence = float(''.join(filter(str.isdigit, conf_str))) / 100.0
            except:
                pass
        
        # Extract reasoning
        reasoning = []
        if 'reasoning:' in response.lower():
            reasoning_section = response.split('REASONING:')[1].split('PROOF')[0] if 'PROOF' in response else response.split('REASONING:')[1]
            reasoning = [line.strip() for line in reasoning_section.split('\n') if line.strip()]
        
        # Extract proof sketch or counterexample
        proof_sketch = None
        counterexample = None
        if 'PROOF' in response:
            proof_sketch = response.split('PROOF')[1].strip()
        elif 'COUNTEREXAMPLE' in response:
            counterexample = response.split('COUNTEREXAMPLE')[1].strip()
        
        return NeuralProofResult(
            is_valid=is_valid,
            confidence=confidence,
            reasoning=reasoning,
            proof_sketch=proof_sketch,
            counterexample=counterexample,
            fallback_used=fallback_used,
            proof_time=0.0,  # Set by caller
            llm_used=self.llm_engine
        )
    
    def explain(self, formula) -> str:
        """Generate natural language explanation of a formula.
        
        Args:
            formula: TDFOL formula to explain
            
        Returns:
            Natural language explanation
        """
        if not self.enable_explanation:
            return str(formula)
        
        formula_str = str(formula)
        
        explanation_task = Symbol(f"""
Explain the following logical formula in simple, clear English:

{formula_str}

Provide:
1. What the formula means in plain language
2. What conditions make it true
3. An example scenario that satisfies it
""", semantic=True)
        
        response = explanation_task.query("Explain this formula clearly.")
        return response
    
    def suggest_proof_strategy(self, formula) -> List[str]:
        """Suggest proof strategies for a formula.
        
        Args:
            formula: TDFOL formula
            
        Returns:
            List of suggested proof strategies
        """
        formula_str = str(formula)
        
        strategy_task = Symbol(f"""
Given this logical formula:

{formula_str}

Suggest the best proof strategies and inference rules to use.
List 3-5 specific approaches.
""", semantic=True)
        
        response = strategy_task.query("What proof strategies should be used?")
        
        # Parse response into list of strategies
        strategies = [
            line.strip() 
            for line in response.split('\n') 
            if line.strip() and (line.strip()[0].isdigit() or line.strip().startswith('-'))
        ]
        
        return strategies


# Convenience function
def prove_with_neural(
    formula,
    axioms=None,
    strategy='neural_guided',
    timeout=30.0
) -> NeuralProofResult:
    """Prove a formula using neural reasoning (convenience function).
    
    Args:
        formula: TDFOL formula to prove
        axioms: Optional list of axioms
        strategy: Proving strategy
        timeout: Timeout in seconds
        
    Returns:
        NeuralProofResult
    """
    prover = SymbolicAIProverBridge(timeout=timeout)
    return prover.prove(formula, axioms=axioms, strategy=strategy)


__all__ = [
    "SymbolicAIProverBridge",
    "NeuralProofResult",
    "prove_with_neural",
    "SYMBOLICAI_AVAILABLE",
]
