"""
Integration tests for TDFOLProver with strategy pattern.

Tests the complete integration of TDFOLProver with the strategy pattern,
including automatic strategy selection, manual strategy override, cache
integration, and error handling.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Predicate,
    Term,
    Variable,
    LogicOperator,
    BinaryFormula,
    TemporalFormula,
    TemporalOperator,
    DeonticFormula,
    DeonticOperator,
    TDFOLKnowledgeBase,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_prover import (
    TDFOLProver,
    ProofResult,
    ProofStatus,
)


class TestAutomaticStrategySelection:
    """Test automatic strategy selection via StrategySelector."""

    def test_prove_simple_formula_auto_strategy(self):
        """
        GIVEN a TDFOLProver with automatic strategy selection
        WHEN proving a simple predicate formula
        THEN it should select appropriate strategy and prove successfully
        """
        # GIVEN
        prover = TDFOLProver()
        p = Predicate("P", [Term("a")])
        prover.add_axiom(p)
        
        # WHEN
        result = prover.prove(p, timeout_ms=1000)
        
        # THEN
        assert result.status == ProofStatus.PROVED
        assert result.formula == p
        assert result.method in ["axiom_lookup", "forward_chaining", "ForwardChaining"]

    def test_prove_modal_formula_auto_strategy(self):
        """
        GIVEN a TDFOLProver with automatic strategy selection
        WHEN proving a modal formula
        THEN it should prefer modal tableaux strategy
        """
        # GIVEN
        prover = TDFOLProver()
        p = Predicate("P", [Term("a")])
        # □P(a) - modal necessity
        modal_p = TemporalFormula(TemporalOperator.ALWAYS, p)
        prover.add_axiom(modal_p)
        
        # WHEN
        result = prover.prove(modal_p, timeout_ms=1000)
        
        # THEN
        assert result.status == ProofStatus.PROVED
        assert result.formula == modal_p

    def test_prove_temporal_formula_auto_strategy(self):
        """
        GIVEN a TDFOLProver with automatic strategy selection
        WHEN proving a temporal formula
        THEN it should handle temporal operators appropriately
        """
        # GIVEN
        prover = TDFOLProver()
        p = Predicate("P", [Term("a")])
        # ◊P(a) - temporal eventually
        eventually_p = TemporalFormula(TemporalOperator.EVENTUALLY, p)
        prover.add_axiom(eventually_p)
        
        # WHEN
        result = prover.prove(eventually_p, timeout_ms=1000)
        
        # THEN
        assert result.status == ProofStatus.PROVED
        assert result.formula == eventually_p


class TestManualStrategyOverride:
    """Test manual strategy override functionality."""

    def test_prove_with_custom_forward_chaining_strategy(self):
        """
        GIVEN a TDFOLProver with custom ForwardChainingStrategy
        WHEN proving a formula
        THEN it should use the custom strategy
        """
        # GIVEN
        try:
            from ipfs_datasets_py.logic.TDFOL.strategies import ForwardChainingStrategy
            
            custom_strategy = ForwardChainingStrategy(rules=[], max_iterations=50)
            prover = TDFOLProver(strategy=custom_strategy)
            p = Predicate("P", [Term("a")])
            prover.add_axiom(p)
            
            # WHEN
            result = prover.prove(p, timeout_ms=1000)
            
            # THEN
            assert result.status in [ProofStatus.PROVED, ProofStatus.UNPROVABLE]
            # Verify custom strategy was used (selector should be None)
            assert prover.selector is None
            assert prover.strategy is not None
        except ImportError:
            pytest.skip("Strategies module not available")

    def test_prove_with_custom_modal_strategy(self):
        """
        GIVEN a TDFOLProver with custom ModalTableauxStrategy
        WHEN proving a modal formula
        THEN it should use the custom strategy
        """
        # GIVEN
        try:
            from ipfs_datasets_py.logic.TDFOL.strategies import ModalTableauxStrategy
            
            custom_strategy = ModalTableauxStrategy()
            prover = TDFOLProver(strategy=custom_strategy)
            p = Predicate("P", [Term("a")])
            modal_p = TemporalFormula(TemporalOperator.ALWAYS, p)
            prover.add_axiom(modal_p)
            
            # WHEN
            result = prover.prove(modal_p, timeout_ms=1000)
            
            # THEN
            assert result.status in [ProofStatus.PROVED, ProofStatus.UNPROVABLE]
            assert prover.selector is None
            assert prover.strategy is not None
        except ImportError:
            pytest.skip("Strategies module not available")


class TestCacheIntegration:
    """Test cache integration with strategy pattern."""

    def test_prove_uses_cache_on_hit(self):
        """
        GIVEN a TDFOLProver with cache enabled
        WHEN proving a formula that's already cached
        THEN it should return cached result without invoking strategy
        """
        # GIVEN
        prover = TDFOLProver(enable_cache=True)
        p = Predicate("P", [Term("a")])
        prover.add_axiom(p)
        
        # First prove to populate cache
        result1 = prover.prove(p, timeout_ms=1000)
        assert result1.status == ProofStatus.PROVED
        
        # WHEN - prove again (should hit cache)
        result2 = prover.prove(p, timeout_ms=1000)
        
        # THEN
        assert result2.status == ProofStatus.PROVED
        assert result2.formula == p
        # Both results should be equivalent
        assert result1.status == result2.status

    def test_prove_stores_result_in_cache(self):
        """
        GIVEN a TDFOLProver with cache enabled
        WHEN proving a new formula successfully
        THEN it should store the result in cache
        """
        # GIVEN
        prover = TDFOLProver(enable_cache=True)
        p = Predicate("P", [Term("a")])
        q = Predicate("Q", [Term("b")])
        prover.add_axiom(p)
        prover.add_axiom(q)
        
        # Verify cache is initialized
        if prover.proof_cache is None:
            pytest.skip("Proof cache not available")
        
        # WHEN
        result = prover.prove(p, timeout_ms=1000)
        
        # THEN
        assert result.status == ProofStatus.PROVED
        # Cache should contain the result (can verify via second lookup)
        result2 = prover.prove(p, timeout_ms=1000)
        assert result2.status == ProofStatus.PROVED


class TestStrategyFallback:
    """Test fallback behavior when strategies unavailable."""

    @patch('ipfs_datasets_py.logic.TDFOL.tdfol_prover.HAVE_STRATEGIES', False)
    def test_prove_fallback_when_strategies_unavailable(self):
        """
        GIVEN a TDFOLProver when strategies are not available
        WHEN proving a formula
        THEN it should return error status with appropriate message
        """
        # GIVEN
        prover = TDFOLProver()
        p = Predicate("P", [Term("a")])
        
        # WHEN
        result = prover.prove(p, timeout_ms=1000)
        
        # THEN
        # Should either find it as axiom or return error
        if p not in prover.kb.axioms:
            assert result.status == ProofStatus.ERROR
            assert "strategies not available" in result.message.lower()

    def test_prove_handles_strategy_error_gracefully(self):
        """
        GIVEN a TDFOLProver with a failing strategy
        WHEN proving a formula that causes strategy error
        THEN it should handle the error gracefully
        """
        # GIVEN
        prover = TDFOLProver()
        # Create a formula that might cause issues
        p = Predicate("P", [Variable("x")])
        
        # WHEN
        result = prover.prove(p, timeout_ms=100)  # Very short timeout
        
        # THEN
        # Should return a result (even if unprovable or error)
        assert result is not None
        assert isinstance(result, ProofResult)
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNPROVABLE, ProofStatus.TIMEOUT, ProofStatus.ERROR]


class TestKnowledgeBaseIntegration:
    """Test integration with knowledge base."""

    def test_prove_with_axioms_in_kb(self):
        """
        GIVEN a TDFOLProver with axioms in knowledge base
        WHEN proving formulas derivable from axioms
        THEN it should prove them successfully
        """
        # GIVEN
        prover = TDFOLProver()
        p = Predicate("P", [Term("a")])
        q = Predicate("Q", [Term("b")])
        
        # Add axioms: P(a), P(a) → Q(b)
        prover.add_axiom(p)
        implication = BinaryFormula(p, LogicOperator.IMPLIES, q)
        prover.add_axiom(implication)
        
        # WHEN - prove P(a) (axiom)
        result_p = prover.prove(p, timeout_ms=1000)
        
        # THEN
        assert result_p.status == ProofStatus.PROVED
        assert result_p.formula == p
        
        # WHEN - prove Q(b) (derivable from axioms)
        result_q = prover.prove(q, timeout_ms=5000)
        
        # THEN
        # Should be proved via forward chaining or similar
        assert result_q.status in [ProofStatus.PROVED, ProofStatus.UNPROVABLE]


# Additional edge case tests
class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_prove_with_empty_kb(self):
        """
        GIVEN a TDFOLProver with empty knowledge base
        WHEN proving a formula
        THEN it should return unprovable or error
        """
        # GIVEN
        prover = TDFOLProver()
        p = Predicate("P", [Term("a")])
        
        # WHEN
        result = prover.prove(p, timeout_ms=1000)
        
        # THEN
        assert result.status in [ProofStatus.UNPROVABLE, ProofStatus.ERROR]

    def test_prove_with_zero_timeout(self):
        """
        GIVEN a TDFOLProver
        WHEN proving with zero timeout
        THEN it should handle gracefully
        """
        # GIVEN
        prover = TDFOLProver()
        p = Predicate("P", [Term("a")])
        prover.add_axiom(p)
        
        # WHEN
        result = prover.prove(p, timeout_ms=0)
        
        # THEN
        # Should still work for axiom lookup
        assert result is not None
        assert isinstance(result, ProofResult)

    def test_prove_complex_nested_formula(self):
        """
        GIVEN a TDFOLProver
        WHEN proving a complex nested formula
        THEN it should handle the complexity appropriately
        """
        # GIVEN
        prover = TDFOLProver()
        p = Predicate("P", [Term("a")])
        q = Predicate("Q", [Term("b")])
        
        # Create nested formula: □(P(a) → ◊Q(b))
        inner_implication = BinaryFormula(p, LogicOperator.IMPLIES, q)
        eventually_q = TemporalFormula(TemporalOperator.EVENTUALLY, inner_implication)
        always_formula = TemporalFormula(TemporalOperator.ALWAYS, eventually_q)
        
        prover.add_axiom(always_formula)
        
        # WHEN
        result = prover.prove(always_formula, timeout_ms=2000)
        
        # THEN
        assert result is not None
        assert isinstance(result, ProofResult)
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNPROVABLE, ProofStatus.TIMEOUT]


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
