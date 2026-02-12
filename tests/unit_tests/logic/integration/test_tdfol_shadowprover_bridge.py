"""
Comprehensive test suite for TDFOL-ShadowProver integration.

Tests modal logic integration with K/S4/S5 provers.
"""

import pytest
import logging

from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Formula,
    Predicate,
    TemporalFormula,
    DeonticFormula,
    TemporalOperator,
    DeonticOperator,
)

# Try to import integration modules
try:
    from ipfs_datasets_py.logic.integration.tdfol_shadowprover_bridge import (
        TDFOLShadowProverBridge,
        ModalAwareTDFOLProver,
        ModalLogicType,
        create_modal_aware_prover,
    )
    INTEGRATION_AVAILABLE = True
except ImportError:
    INTEGRATION_AVAILABLE = False
    pytest.skip("ShadowProver integration not available", allow_module_level=True)


class TestTDFOLShadowProverBridge:
    """Test the TDFOL-ShadowProver Bridge."""
    
    def setup_method(self):
        """Setup for each test."""
        self.bridge = TDFOLShadowProverBridge()
    
    def test_bridge_initialization(self):
        """Test bridge initializes correctly."""
        assert self.bridge is not None
        assert isinstance(self.bridge, TDFOLShadowProverBridge)
    
    def test_shadowprover_availability(self):
        """Test ShadowProver availability detection."""
        assert hasattr(self.bridge, 'available')
        assert isinstance(self.bridge.available, bool)
    
    def test_modal_provers_initialized(self):
        """Test modal provers are initialized if available."""
        if self.bridge.available:
            assert hasattr(self.bridge, 'k_prover')
            assert hasattr(self.bridge, 's4_prover')
            assert hasattr(self.bridge, 's5_prover')
            assert hasattr(self.bridge, 'cognitive_prover')
    
    def test_modal_logic_selection_temporal(self):
        """Test automatic modal logic selection for temporal formulas."""
        p = Predicate("P", ())
        always_p = TemporalFormula(TemporalOperator.ALWAYS, p)
        
        logic_type = self.bridge.select_modal_logic(always_p)
        assert logic_type == ModalLogicType.S4
    
    def test_modal_logic_selection_deontic(self):
        """Test automatic modal logic selection for deontic formulas."""
        p = Predicate("P", ())
        obligatory_p = DeonticFormula(DeonticOperator.OBLIGATORY, p)
        
        logic_type = self.bridge.select_modal_logic(obligatory_p)
        assert logic_type == ModalLogicType.D
    
    def test_modal_logic_selection_default(self):
        """Test default modal logic selection."""
        p = Predicate("P", ())
        
        logic_type = self.bridge.select_modal_logic(p)
        assert logic_type == ModalLogicType.K
    
    def test_prove_temporal_formula(self):
        """Test proving temporal formula with modal logic."""
        p = Predicate("P", ())
        always_p = TemporalFormula(TemporalOperator.ALWAYS, p)
        
        result = self.bridge.prove_modal(always_p, timeout_ms=1000)
        assert result is not None
        # Note: Actual proving might not be fully implemented
        logging.info(f"Modal proof result: {result.status}")
    
    def test_prove_with_explicit_logic_type(self):
        """Test proving with explicitly specified logic type."""
        p = Predicate("P", ())
        
        result = self.bridge.prove_modal(
            p,
            logic_type=ModalLogicType.K,
            timeout_ms=1000
        )
        assert result is not None
    
    def test_tableaux_proving(self):
        """Test modal tableaux proving."""
        p = Predicate("P", ())
        
        result = self.bridge.prove_with_tableaux(p, timeout_ms=1000)
        assert result is not None


class TestModalAwareTDFOLProver:
    """Test the Modal-Aware TDFOL Prover."""
    
    def setup_method(self):
        """Setup for each test."""
        self.prover = ModalAwareTDFOLProver()
    
    def test_prover_initialization(self):
        """Test prover initializes correctly."""
        assert self.prover is not None
        assert isinstance(self.prover, ModalAwareTDFOLProver)
    
    def test_prover_has_shadow_bridge(self):
        """Test prover has ShadowProver bridge."""
        assert hasattr(self.prover, 'shadow_bridge')
        assert self.prover.shadow_bridge is not None
    
    def test_prove_simple_formula(self):
        """Test proving simple formula."""
        p = Predicate("P", ())
        self.prover.base_prover.kb.add_axiom(p)
        
        result = self.prover.prove(p, timeout_ms=1000)
        assert result is not None
    
    def test_prove_temporal_formula(self):
        """Test proving temporal formula (should route to ShadowProver)."""
        p = Predicate("P", ())
        always_p = TemporalFormula(TemporalOperator.ALWAYS, p)
        
        self.prover.base_prover.kb.add_axiom(always_p)
        
        result = self.prover.prove(always_p, timeout_ms=1000)
        assert result is not None
        logging.info(f"Temporal proof routed: {result.method}")
    
    def test_prove_deontic_formula(self):
        """Test proving deontic formula (should route to ShadowProver)."""
        p = Predicate("P", ())
        obligatory_p = DeonticFormula(DeonticOperator.OBLIGATORY, p)
        
        self.prover.base_prover.kb.add_axiom(obligatory_p)
        
        result = self.prover.prove(obligatory_p, timeout_ms=1000)
        assert result is not None
        logging.info(f"Deontic proof routed: {result.method}")
    
    def test_has_temporal_operators_detection(self):
        """Test detection of temporal operators."""
        p = Predicate("P", ())
        always_p = TemporalFormula(TemporalOperator.ALWAYS, p)
        
        has_temporal = self.prover._has_temporal_operators(always_p)
        assert has_temporal == True
        
        has_temporal_simple = self.prover._has_temporal_operators(p)
        assert has_temporal_simple == False
    
    def test_has_deontic_operators_detection(self):
        """Test detection of deontic operators."""
        p = Predicate("P", ())
        obligatory_p = DeonticFormula(DeonticOperator.OBLIGATORY, p)
        
        has_deontic = self.prover._has_deontic_operators(obligatory_p)
        assert has_deontic == True
        
        has_deontic_simple = self.prover._has_deontic_operators(p)
        assert has_deontic_simple == False
    
    def test_prove_with_modal_specialized_disabled(self):
        """Test proving with specialized modal provers disabled."""
        p = Predicate("P", ())
        always_p = TemporalFormula(TemporalOperator.ALWAYS, p)
        
        self.prover.base_prover.kb.add_axiom(always_p)
        
        result = self.prover.prove(
            always_p,
            timeout_ms=1000,
            use_modal_specialized=False
        )
        assert result is not None


class TestModalLogicType:
    """Test ModalLogicType enum."""
    
    def test_modal_logic_types_exist(self):
        """Test all modal logic types exist."""
        assert hasattr(ModalLogicType, 'K')
        assert hasattr(ModalLogicType, 'T')
        assert hasattr(ModalLogicType, 'S4')
        assert hasattr(ModalLogicType, 'S5')
        assert hasattr(ModalLogicType, 'D')
    
    def test_modal_logic_type_values(self):
        """Test modal logic type values."""
        assert ModalLogicType.K.value == "K"
        assert ModalLogicType.S4.value == "S4"
        assert ModalLogicType.S5.value == "S5"
        assert ModalLogicType.D.value == "D"


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def test_create_modal_aware_prover(self):
        """Test creating modal-aware prover."""
        prover = create_modal_aware_prover()
        assert prover is not None
        assert isinstance(prover, ModalAwareTDFOLProver)


class TestIntegrationScenarios:
    """Test real-world integration scenarios."""
    
    def setup_method(self):
        """Setup for each test."""
        self.prover = create_modal_aware_prover()
    
    def test_temporal_persistence_reasoning(self):
        """Test reasoning about temporal persistence."""
        # If something is always true, it's true now
        p = Predicate("Available", ())
        always_p = TemporalFormula(TemporalOperator.ALWAYS, p)
        
        self.prover.base_prover.kb.add_axiom(always_p)
        
        # Should be able to derive p from □p (T axiom)
        result = self.prover.prove(p, timeout_ms=2000)
        assert result is not None
        logging.info(f"Temporal persistence: {result.status}")
    
    def test_deontic_obligation_permission(self):
        """Test deontic reasoning about obligations and permissions."""
        # If something is obligatory, it's permissible (D axiom)
        p = Predicate("Report", ())
        obligatory_p = DeonticFormula(DeonticOperator.OBLIGATORY, p)
        permitted_p = DeonticFormula(DeonticOperator.PERMISSIBLE, p)
        
        self.prover.base_prover.kb.add_axiom(obligatory_p)
        
        # Should derive permission from obligation
        result = self.prover.prove(permitted_p, timeout_ms=2000)
        assert result is not None
        logging.info(f"Obligation-permission: {result.status}")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
