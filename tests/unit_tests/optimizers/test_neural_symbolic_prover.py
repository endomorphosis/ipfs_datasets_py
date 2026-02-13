"""Tests for Neural-Symbolic Hybrid Prover.

This module contains comprehensive tests for the neural-symbolic hybrid prover
that combines neural LLM-based reasoning with symbolic theorem proving.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover import (
    NeuralSymbolicHybridProver,
    HybridStrategy,
    NeuralResult,
    SymbolicResult,
    HybridProverResult,
)


class TestHybridStrategy:
    """Tests for HybridStrategy enum."""
    
    def test_hybrid_strategy_values(self):
        """
        GIVEN the HybridStrategy enum
        WHEN accessing strategy values
        THEN all expected strategies should be available
        """
        assert HybridStrategy.NEURAL_FIRST.value == "neural_first"
        assert HybridStrategy.SYMBOLIC_FIRST.value == "symbolic_first"
        assert HybridStrategy.PARALLEL.value == "parallel"
        assert HybridStrategy.ENSEMBLE.value == "ensemble"
        assert HybridStrategy.ADAPTIVE.value == "adaptive"


class TestNeuralResult:
    """Tests for NeuralResult dataclass."""
    
    def test_neural_result_creation(self):
        """
        GIVEN neural prover result data
        WHEN creating a NeuralResult
        THEN the result should have correct attributes
        """
        result = NeuralResult(
            is_valid=True,
            confidence=0.85,
            reasoning_steps=["Step 1", "Step 2"],
            proof_sketch="Informal proof",
            llm_used="gpt-4",
            execution_time=1.5
        )
        
        assert result.is_valid is True
        assert result.confidence == 0.85
        assert len(result.reasoning_steps) == 2
        assert result.proof_sketch == "Informal proof"
        assert result.llm_used == "gpt-4"
        assert result.execution_time == 1.5
    
    def test_neural_result_defaults(self):
        """
        GIVEN minimal neural result data
        WHEN creating a NeuralResult with defaults
        THEN default values should be applied
        """
        result = NeuralResult(
            is_valid=False,
            confidence=0.5,
            execution_time=0.0
        )
        
        assert result.reasoning_steps == []
        assert result.proof_sketch is None
        assert result.llm_used is None
        assert result.error_message is None


class TestSymbolicResult:
    """Tests for SymbolicResult dataclass."""
    
    def test_symbolic_result_creation(self):
        """
        GIVEN symbolic prover result data
        WHEN creating a SymbolicResult
        THEN the result should have correct attributes
        """
        result = SymbolicResult(
            is_valid=True,
            confidence=1.0,
            proof="Formal proof",
            prover_used="z3",
            execution_time=0.5
        )
        
        assert result.is_valid is True
        assert result.confidence == 1.0
        assert result.proof == "Formal proof"
        assert result.prover_used == "z3"
        assert result.execution_time == 0.5
    
    def test_symbolic_result_defaults(self):
        """
        GIVEN minimal symbolic result data
        WHEN creating a SymbolicResult with defaults
        THEN default values should be applied
        """
        result = SymbolicResult(
            is_valid=False,
            confidence=0.0,
            execution_time=0.0
        )
        
        assert result.proof is None
        assert result.prover_used is None
        assert result.error_message is None


class TestHybridProverResult:
    """Tests for HybridProverResult dataclass."""
    
    def test_hybrid_result_with_agreement(self):
        """
        GIVEN neural and symbolic results that agree
        WHEN creating a HybridProverResult
        THEN agreement should be True
        """
        neural = NeuralResult(is_valid=True, confidence=0.9, execution_time=1.0)
        symbolic = SymbolicResult(is_valid=True, confidence=1.0, execution_time=0.5)
        
        result = HybridProverResult(
            is_valid=True,
            confidence=0.95,
            neural_result=neural,
            symbolic_result=symbolic,
            strategy_used=HybridStrategy.PARALLEL,
            agreement=True,
            execution_time=1.5,
            explanation="Both agree: valid"
        )
        
        assert result.is_valid is True
        assert result.agreement is True
        assert result.strategy_used == HybridStrategy.PARALLEL
    
    def test_hybrid_result_with_disagreement(self):
        """
        GIVEN neural and symbolic results that disagree
        WHEN creating a HybridProverResult
        THEN agreement should be False
        """
        neural = NeuralResult(is_valid=True, confidence=0.7, execution_time=1.0)
        symbolic = SymbolicResult(is_valid=False, confidence=1.0, execution_time=0.5)
        
        result = HybridProverResult(
            is_valid=False,
            confidence=0.6,
            neural_result=neural,
            symbolic_result=symbolic,
            strategy_used=HybridStrategy.PARALLEL,
            agreement=False,
            execution_time=1.5,
            explanation="Disagreement: using symbolic"
        )
        
        assert result.agreement is False


class TestNeuralSymbolicHybridProver:
    """Tests for NeuralSymbolicHybridProver."""
    
    def test_init_default_params(self):
        """
        GIVEN default parameters
        WHEN initializing NeuralSymbolicHybridProver
        THEN the prover should be initialized with correct defaults
        """
        prover = NeuralSymbolicHybridProver()
        
        assert prover.strategy == HybridStrategy.PARALLEL
        assert prover.neural_provers == ['symbolicai']
        assert prover.symbolic_provers == ['z3']
        assert prover.enable_embeddings is True
        assert prover.cache_results is True
        assert len(prover.result_cache) == 0
    
    def test_init_custom_params(self):
        """
        GIVEN custom parameters
        WHEN initializing NeuralSymbolicHybridProver
        THEN the prover should use custom values
        """
        prover = NeuralSymbolicHybridProver(
            strategy=HybridStrategy.NEURAL_FIRST,
            neural_provers=['symbolicai', 'gpt4'],
            symbolic_provers=['z3', 'cvc5'],
            neural_weight=0.3,
            symbolic_weight=0.7,
            enable_embeddings=False,
            cache_results=False
        )
        
        assert prover.strategy == HybridStrategy.NEURAL_FIRST
        assert prover.neural_provers == ['symbolicai', 'gpt4']
        assert prover.symbolic_provers == ['z3', 'cvc5']
        assert abs(prover.neural_weight - 0.3) < 0.01
        assert abs(prover.symbolic_weight - 0.7) < 0.01
        assert prover.enable_embeddings is False
        assert prover.cache_results is False
    
    def test_weight_normalization(self):
        """
        GIVEN non-normalized weights
        WHEN initializing NeuralSymbolicHybridProver
        THEN weights should be normalized to sum to 1.0
        """
        prover = NeuralSymbolicHybridProver(
            neural_weight=2.0,
            symbolic_weight=3.0
        )
        
        # 2/(2+3) = 0.4, 3/(2+3) = 0.6
        assert abs(prover.neural_weight - 0.4) < 0.01
        assert abs(prover.symbolic_weight - 0.6) < 0.01
        assert abs(prover.neural_weight + prover.symbolic_weight - 1.0) < 0.01
    
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_neural_prover')
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_symbolic_prover')
    def test_prove_parallel_both_agree(self, mock_symbolic, mock_neural):
        """
        GIVEN both neural and symbolic provers available
        WHEN proving with PARALLEL strategy and both agree
        THEN result should have high confidence and agreement=True
        """
        # Setup mocks
        mock_neural.return_value = NeuralResult(
            is_valid=True,
            confidence=0.85,
            reasoning_steps=["Step 1"],
            execution_time=1.0
        )
        mock_symbolic.return_value = SymbolicResult(
            is_valid=True,
            confidence=1.0,
            prover_used="z3",
            execution_time=0.5
        )
        
        prover = NeuralSymbolicHybridProver(strategy=HybridStrategy.PARALLEL)
        result = prover.prove("∀x P(x) → Q(x)")
        
        assert result.is_valid is True
        assert result.agreement is True
        assert result.confidence >= 0.85
        assert result.neural_result is not None
        assert result.symbolic_result is not None
        assert result.strategy_used == HybridStrategy.PARALLEL
    
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_neural_prover')
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_symbolic_prover')
    def test_prove_parallel_disagree(self, mock_symbolic, mock_neural):
        """
        GIVEN both provers available but disagree
        WHEN proving with PARALLEL strategy
        THEN result should use weighted combination
        """
        # Neural says valid, symbolic says invalid
        mock_neural.return_value = NeuralResult(
            is_valid=True,
            confidence=0.8,
            execution_time=1.0
        )
        mock_symbolic.return_value = SymbolicResult(
            is_valid=False,
            confidence=1.0,
            execution_time=0.5
        )
        
        prover = NeuralSymbolicHybridProver(
            strategy=HybridStrategy.PARALLEL,
            neural_weight=0.3,
            symbolic_weight=0.7
        )
        result = prover.prove("∃x P(x)")
        
        assert result.agreement is False
        assert result.neural_result.is_valid is True
        assert result.symbolic_result.is_valid is False
        # Weighted: 0.8*0.3 + 0.0*0.7 = 0.24 < 0.5, so invalid
        assert result.is_valid is False
    
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_neural_prover')
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_symbolic_prover')
    def test_prove_neural_first_high_confidence(self, mock_symbolic, mock_neural):
        """
        GIVEN NEURAL_FIRST strategy
        WHEN neural has high confidence (>= 0.85)
        THEN neural result should be trusted but verified
        """
        mock_neural.return_value = NeuralResult(
            is_valid=True,
            confidence=0.9,
            execution_time=1.0
        )
        mock_symbolic.return_value = SymbolicResult(
            is_valid=True,
            confidence=1.0,
            execution_time=0.5
        )
        
        prover = NeuralSymbolicHybridProver(strategy=HybridStrategy.NEURAL_FIRST)
        result = prover.prove("P → Q")
        
        assert result.is_valid is True
        assert result.confidence == 0.9
        assert result.strategy_used == HybridStrategy.NEURAL_FIRST
        # Both should be called
        mock_neural.assert_called_once()
        mock_symbolic.assert_called_once()
    
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_neural_prover')
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_symbolic_prover')
    def test_prove_neural_first_low_confidence(self, mock_symbolic, mock_neural):
        """
        GIVEN NEURAL_FIRST strategy
        WHEN neural has low confidence (< 0.85)
        THEN symbolic prover should be used
        """
        mock_neural.return_value = NeuralResult(
            is_valid=True,
            confidence=0.6,
            execution_time=1.0
        )
        mock_symbolic.return_value = SymbolicResult(
            is_valid=False,
            confidence=1.0,
            execution_time=0.5
        )
        
        prover = NeuralSymbolicHybridProver(strategy=HybridStrategy.NEURAL_FIRST)
        result = prover.prove("P → Q")
        
        # Should use symbolic result due to low neural confidence
        assert result.is_valid is False
        assert result.confidence == 1.0
    
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_neural_prover')
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_symbolic_prover')
    def test_prove_symbolic_first(self, mock_symbolic, mock_neural):
        """
        GIVEN SYMBOLIC_FIRST strategy
        WHEN symbolic succeeds with high confidence
        THEN symbolic result should be trusted
        """
        mock_symbolic.return_value = SymbolicResult(
            is_valid=True,
            confidence=1.0,
            prover_used="z3",
            execution_time=0.5
        )
        mock_neural.return_value = NeuralResult(
            is_valid=True,
            confidence=0.8,
            execution_time=1.0
        )
        
        prover = NeuralSymbolicHybridProver(strategy=HybridStrategy.SYMBOLIC_FIRST)
        result = prover.prove("∀x P(x)")
        
        assert result.is_valid is True
        assert result.confidence == 1.0
        assert result.strategy_used == HybridStrategy.SYMBOLIC_FIRST
    
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_neural_prover')
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_symbolic_prover')
    def test_prove_adaptive_complex_formula(self, mock_symbolic, mock_neural):
        """
        GIVEN ADAPTIVE strategy and complex formula
        WHEN proving a formula with quantifiers
        THEN neural-first approach should be used
        """
        mock_neural.return_value = NeuralResult(
            is_valid=True,
            confidence=0.9,
            execution_time=1.0
        )
        mock_symbolic.return_value = SymbolicResult(
            is_valid=True,
            confidence=1.0,
            execution_time=0.5
        )
        
        prover = NeuralSymbolicHybridProver(strategy=HybridStrategy.ADAPTIVE)
        
        # Complex formula with quantifiers
        result = prover.prove("∀x ∃y (P(x) → Q(y))")
        
        assert result.strategy_used == HybridStrategy.NEURAL_FIRST
    
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_neural_prover')
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_symbolic_prover')
    def test_prove_adaptive_simple_formula(self, mock_symbolic, mock_neural):
        """
        GIVEN ADAPTIVE strategy and simple formula
        WHEN proving a simple propositional formula
        THEN symbolic-first approach should be used
        """
        mock_symbolic.return_value = SymbolicResult(
            is_valid=True,
            confidence=1.0,
            execution_time=0.1
        )
        mock_neural.return_value = None
        
        prover = NeuralSymbolicHybridProver(strategy=HybridStrategy.ADAPTIVE)
        
        # Simple formula
        result = prover.prove("P → Q")
        
        assert result.strategy_used == HybridStrategy.SYMBOLIC_FIRST
    
    def test_cache_results(self):
        """
        GIVEN cache_results=True
        WHEN proving the same formula twice
        THEN second call should use cached result
        """
        prover = NeuralSymbolicHybridProver(cache_results=True)
        
        # Mock the proving methods
        with patch.object(prover, '_prove_parallel') as mock_prove:
            mock_result = HybridProverResult(
                is_valid=True,
                confidence=0.9,
                neural_result=None,
                symbolic_result=None,
                strategy_used=HybridStrategy.PARALLEL,
                agreement=True,
                execution_time=1.0,
                explanation="Cached result"
            )
            mock_prove.return_value = mock_result
            
            # First call
            result1 = prover.prove("P → Q")
            assert mock_prove.call_count == 1
            
            # Second call - should use cache
            result2 = prover.prove("P → Q")
            assert mock_prove.call_count == 1  # Not called again
            assert result1 is result2  # Same object from cache
    
    def test_cache_disabled(self):
        """
        GIVEN cache_results=False
        WHEN proving the same formula twice
        THEN both calls should execute proving
        """
        prover = NeuralSymbolicHybridProver(cache_results=False)
        
        with patch.object(prover, '_prove_parallel') as mock_prove:
            mock_result = HybridProverResult(
                is_valid=True,
                confidence=0.9,
                neural_result=None,
                symbolic_result=None,
                strategy_used=HybridStrategy.PARALLEL,
                agreement=True,
                execution_time=1.0,
                explanation="Result"
            )
            mock_prove.return_value = mock_result
            
            # First call
            prover.prove("P → Q")
            assert mock_prove.call_count == 1
            
            # Second call - should execute again
            prover.prove("P → Q")
            assert mock_prove.call_count == 2
    
    def test_get_statistics(self):
        """
        GIVEN an initialized prover
        WHEN getting statistics
        THEN statistics should contain correct information
        """
        prover = NeuralSymbolicHybridProver(
            strategy=HybridStrategy.PARALLEL,
            neural_weight=0.4,
            symbolic_weight=0.6
        )
        
        stats = prover.get_statistics()
        
        assert 'cache_size' in stats
        assert stats['strategy'] == 'parallel'
        assert abs(stats['neural_weight'] - 0.4) < 0.01
        assert abs(stats['symbolic_weight'] - 0.6) < 0.01
        assert 'neural_available' in stats
        assert 'symbolic_available' in stats
        assert 'embedding_available' in stats
    
    def test_clear_cache(self):
        """
        GIVEN a prover with cached results
        WHEN clearing the cache
        THEN cache should be empty
        """
        prover = NeuralSymbolicHybridProver(cache_results=True)
        
        # Add something to cache manually
        prover.result_cache['test_key'] = Mock()
        assert len(prover.result_cache) == 1
        
        # Clear cache
        prover.clear_cache()
        assert len(prover.result_cache) == 0
    
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_neural_prover')
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_symbolic_prover')
    def test_prove_only_neural_available(self, mock_symbolic, mock_neural):
        """
        GIVEN only neural prover available
        WHEN proving with PARALLEL strategy
        THEN result should use neural with reduced confidence
        """
        mock_neural.return_value = NeuralResult(
            is_valid=True,
            confidence=0.9,
            execution_time=1.0
        )
        mock_symbolic.return_value = None  # Not available
        
        prover = NeuralSymbolicHybridProver(strategy=HybridStrategy.PARALLEL)
        result = prover.prove("P → Q")
        
        assert result.is_valid is True
        assert result.confidence < 0.9  # Reduced confidence
        assert result.neural_result is not None
        assert result.symbolic_result is None
        assert result.agreement is False
    
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_neural_prover')
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_symbolic_prover')
    def test_prove_only_symbolic_available(self, mock_symbolic, mock_neural):
        """
        GIVEN only symbolic prover available
        WHEN proving with PARALLEL strategy
        THEN result should use symbolic
        """
        mock_neural.return_value = None  # Not available
        mock_symbolic.return_value = SymbolicResult(
            is_valid=True,
            confidence=1.0,
            execution_time=0.5
        )
        
        prover = NeuralSymbolicHybridProver(strategy=HybridStrategy.PARALLEL)
        result = prover.prove("P → Q")
        
        assert result.is_valid is True
        assert result.confidence == 1.0
        assert result.neural_result is None
        assert result.symbolic_result is not None
        assert result.agreement is False
    
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_neural_prover')
    @patch('ipfs_datasets_py.optimizers.logic_theorem_optimizer.neural_symbolic_prover.NeuralSymbolicHybridProver._run_symbolic_prover')
    def test_prove_neither_available(self, mock_symbolic, mock_neural):
        """
        GIVEN neither prover available
        WHEN proving with PARALLEL strategy
        THEN result should indicate failure
        """
        mock_neural.return_value = None
        mock_symbolic.return_value = None
        
        prover = NeuralSymbolicHybridProver(strategy=HybridStrategy.PARALLEL)
        result = prover.prove("P → Q")
        
        assert result.is_valid is False
        assert result.confidence == 0.0
        assert result.neural_result is None
        assert result.symbolic_result is None
    
    def test_compute_cache_key_same_formula(self):
        """
        GIVEN the same formula
        WHEN computing cache keys
        THEN keys should be identical
        """
        prover = NeuralSymbolicHybridProver()
        
        key1 = prover._compute_cache_key("P → Q", None)
        key2 = prover._compute_cache_key("P → Q", None)
        
        assert key1 == key2
    
    def test_compute_cache_key_different_formulas(self):
        """
        GIVEN different formulas
        WHEN computing cache keys
        THEN keys should be different
        """
        prover = NeuralSymbolicHybridProver()
        
        key1 = prover._compute_cache_key("P → Q", None)
        key2 = prover._compute_cache_key("Q → P", None)
        
        assert key1 != key2
    
    def test_compute_cache_key_with_context(self):
        """
        GIVEN formulas with different contexts
        WHEN computing cache keys
        THEN keys should be different
        """
        prover = NeuralSymbolicHybridProver()
        
        key1 = prover._compute_cache_key("P → Q", {"axiom": "A"})
        key2 = prover._compute_cache_key("P → Q", {"axiom": "B"})
        
        assert key1 != key2
    
    def test_generate_explanation_both_available(self):
        """
        GIVEN both neural and symbolic results
        WHEN generating explanation
        THEN explanation should include both results
        """
        prover = NeuralSymbolicHybridProver()
        
        neural = NeuralResult(
            is_valid=True,
            confidence=0.9,
            reasoning_steps=["Step 1", "Step 2"],
            llm_used="gpt-4",
            execution_time=1.0
        )
        symbolic = SymbolicResult(
            is_valid=True,
            confidence=1.0,
            prover_used="z3",
            execution_time=0.5
        )
        
        explanation = prover._generate_explanation(neural, symbolic)
        
        assert "gpt-4" in explanation
        assert "z3" in explanation
        assert "Valid" in explanation
        assert "agree" in explanation.lower()
    
    def test_generate_explanation_disagreement(self):
        """
        GIVEN neural and symbolic results that disagree
        WHEN generating explanation
        THEN explanation should mention disagreement
        """
        prover = NeuralSymbolicHybridProver()
        
        neural = NeuralResult(
            is_valid=True,
            confidence=0.8,
            llm_used="gpt-4",
            execution_time=1.0
        )
        symbolic = SymbolicResult(
            is_valid=False,
            confidence=1.0,
            prover_used="z3",
            execution_time=0.5
        )
        
        explanation = prover._generate_explanation(neural, symbolic)
        
        assert "disagree" in explanation.lower()
    
    def test_invalid_strategy_raises_error(self):
        """
        GIVEN an invalid strategy value
        WHEN proving
        THEN ValueError should be raised
        """
        prover = NeuralSymbolicHybridProver()
        prover.strategy = "invalid_strategy"  # Hack to set invalid strategy
        
        with pytest.raises(ValueError, match="Unknown strategy"):
            prover.prove("P → Q")
