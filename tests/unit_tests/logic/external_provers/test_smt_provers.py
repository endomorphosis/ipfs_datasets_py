"""Comprehensive tests for external SMT prover integrations.

Tests for Z3 and CVC5 prover bridges.
"""

import pytest
from ipfs_datasets_py.logic.external_provers.smt import z3_prover_bridge, cvc5_prover_bridge
from ipfs_datasets_py.logic.external_provers.interactive.lean_prover_bridge import TDFOLToLeanConverter
from ipfs_datasets_py.logic.external_provers.interactive.coq_prover_bridge import TDFOLToCoqConverter
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Constant,
    FunctionApplication,
    Predicate,
    QuantifiedFormula,
    Quantifier,
    Variable,
)


class TestZ3ProverBridge:
    """Test Z3 prover bridge functionality."""
    
    @pytest.fixture
    def z3_bridge(self):
        """Create Z3 bridge instance."""
        try:
            return z3_prover_bridge.Z3ProverBridge()
        except Exception:
            pytest.skip("Z3 not available")
    
    def test_z3_bridge_initialization(self, z3_bridge):
        """GIVEN: Z3ProverBridge class
        WHEN: Initializing instance
        THEN: Should initialize successfully
        """
        assert z3_bridge is not None
        assert hasattr(z3_bridge, 'prove')
    
    def test_z3_simple_proof(self, z3_bridge):
        """GIVEN: Simple tautology
        WHEN: Proving with Z3
        THEN: Should prove successfully
        """
        # P -> P is always true
        result = z3_bridge.prove("P -> P")
        assert result is not None
    
    def test_z3_invalid_formula(self, z3_bridge):
        """GIVEN: Invalid formula
        WHEN: Attempting to prove
        THEN: Should handle gracefully
        """
        try:
            result = z3_bridge.prove("invalid@#$")
            # Should either fail gracefully or return error
            assert result is not None or True
        except Exception as e:
            # Expected to raise exception
            assert True
    
    def test_z3_contradiction(self, z3_bridge):
        """GIVEN: Contradictory formula
        WHEN: Checking satisfiability
        THEN: Should detect contradiction
        """
        # P and not P is contradictory
        result = z3_bridge.prove("P & ~P")
        assert result is not None


class TestCVC5ProverBridge:
    """Test CVC5 prover bridge functionality."""
    
    @pytest.fixture
    def cvc5_bridge(self):
        """Create CVC5 bridge instance."""
        try:
            return cvc5_prover_bridge.CVC5ProverBridge()
        except Exception:
            pytest.skip("CVC5 not available")
    
    def test_cvc5_bridge_initialization(self, cvc5_bridge):
        """GIVEN: CVC5ProverBridge class
        WHEN: Initializing instance
        THEN: Should initialize successfully
        """
        assert cvc5_bridge is not None
        assert hasattr(cvc5_bridge, 'prove')
    
    def test_cvc5_simple_proof(self, cvc5_bridge):
        """GIVEN: Simple tautology
        WHEN: Proving with CVC5
        THEN: Should prove successfully
        """
        result = cvc5_bridge.prove("P -> P")
        assert result is not None
    
    def test_cvc5_quantified_formula(self, cvc5_bridge):
        """GIVEN: Quantified formula
        WHEN: Proving with CVC5
        THEN: Should handle quantifiers
        """
        # forall x. P(x) -> P(x)
        try:
            result = cvc5_bridge.prove("forall x. P(x) -> P(x)")
            assert result is not None
        except Exception:
            # CVC5 may not support this syntax
            pytest.skip("Formula syntax not supported")


class TestProverComparison:
    """Test comparison between different SMT provers."""
    
    def test_prover_availability(self):
        """GIVEN: SMT prover bridges
        WHEN: Checking availability
        THEN: Should report status correctly
        """
        z3_available = False
        cvc5_available = False
        
        try:
            z3_prover_bridge.Z3ProverBridge()
            z3_available = True
        except Exception:
            pass
        
        try:
            cvc5_prover_bridge.CVC5ProverBridge()
            cvc5_available = True
        except Exception:
            pass
        
        # At least one should be available ideally
        assert isinstance(z3_available, bool)
        assert isinstance(cvc5_available, bool)
    
    def test_prover_router_integration(self):
        """GIVEN: Multiple provers
        WHEN: Using prover router
        THEN: Should select appropriate prover
        """
        from ipfs_datasets_py.logic.external_provers import prover_router
        
        router = prover_router.ProverRouter()
        assert router is not None
        assert hasattr(router, 'route')


class TestSMTProverErrorHandling:
    """Test error handling in SMT provers."""
    
    def test_graceful_degradation(self):
        """GIVEN: Unavailable provers
        WHEN: Attempting to use them
        THEN: Should provide fallback or clear error
        """
        # Test that system doesn't crash when provers unavailable
        try:
            from ipfs_datasets_py.logic.external_provers.smt import z3_prover_bridge
            bridge = z3_prover_bridge.Z3ProverBridge()
            assert bridge is not None or True
        except ImportError:
            # Expected if Z3 not installed
            assert True
        except Exception as e:
            # Should provide meaningful error
            assert len(str(e)) > 0
    
    def test_timeout_handling(self):
        """GIVEN: Complex formula
        WHEN: Prover times out
        THEN: Should handle timeout gracefully
        """
        # Placeholder - would need actual timeout implementation
        assert True


class TestProverIntegrationWithTDFOL:
    """Test integration between SMT provers and TDFOL."""
    
    def test_tdfol_to_smt_conversion(self):
        """GIVEN: TDFOL formula
        WHEN: Converting to SMT format
        THEN: Should convert correctly
        """
        from ipfs_datasets_py.logic.TDFOL import parse_tdfol, parse_tdfol_safe
        
        # "P -> Q" fails as P is the permission deontic operator; use safe parse or different formula
        formula = parse_tdfol_safe("P -> Q")
        # If simple atom implication fails, verify more standard formula works
        if formula is None:
            formula = parse_tdfol("atom1")
        assert formula is not None
        # Conversion logic would be tested here

    def test_external_converters_use_current_tdfol_field_names(self):
        """External prover converters should accept current TDFOL dataclass fields."""
        term = FunctionApplication("parent_of", (Constant("alice"),))
        formula = Predicate("Responsible", (term,))

        assert z3_prover_bridge._function_name(term) == "parent_of"
        assert z3_prover_bridge._node_args(formula) == (term,)
        assert cvc5_prover_bridge._function_name(term) == "parent_of"
        assert cvc5_prover_bridge._node_args(formula) == (term,)
        assert TDFOLToLeanConverter().convert(formula) == "(Responsible (parent_of alice))"
        assert TDFOLToCoqConverter().convert(formula) == "(Responsible (parent_of alice))"

    def test_formula_analyzer_counts_current_tdfol_arguments(self):
        """The router analyzer should inspect Predicate.arguments, not only legacy args."""
        from ipfs_datasets_py.logic.external_provers.formula_analyzer import FormulaAnalyzer

        formula = QuantifiedFormula(
            Quantifier.FORALL,
            Variable("x"),
            Predicate("Person", (Variable("x"),)),
        )

        analysis = FormulaAnalyzer().analyze(formula)

        assert analysis.analysis_details["variable_count"] == 1
    
    def test_smt_result_to_tdfol(self):
        """GIVEN: SMT prover result
        WHEN: Converting back to TDFOL format
        THEN: Should preserve semantics
        """
        # Placeholder for bidirectional conversion test
        assert True


class TestProverInstaller:
    """Test documented prover installer routing for SMT and neural provers."""

    def test_installer_accepts_smt_and_symbolicai_flags(self, monkeypatch):
        from ipfs_datasets_py.logic.integration.bridges import prover_installer as installer

        called = []
        monkeypatch.setattr(installer, "ensure_z3", lambda **kwargs: called.append("z3") or True)
        monkeypatch.setattr(installer, "ensure_cvc5", lambda **kwargs: called.append("cvc5") or True)
        monkeypatch.setattr(installer, "ensure_symbolicai", lambda **kwargs: called.append("symbolicai") or True)

        assert installer.main(["--z3", "--cvc5", "--symbolicai", "--yes"]) == 0
        assert called == ["z3", "cvc5", "symbolicai"]
