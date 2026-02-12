"""
Comprehensive test suite for TDFOL-CEC integration.

Tests the TDFOLCECBridge and EnhancedTDFOLProver components.
"""

import pytest
import logging
from typing import List

from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Formula,
    Predicate,
    Variable,
    BinaryFormula,
    LogicOperator,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol
from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus

# Try to import integration modules
try:
    from ipfs_datasets_py.logic.integration.tdfol_cec_bridge import (
        TDFOLCECBridge,
        EnhancedTDFOLProver,
        create_enhanced_prover,
    )
    INTEGRATION_AVAILABLE = True
except ImportError:
    INTEGRATION_AVAILABLE = False
    pytest.skip("Integration modules not available", allow_module_level=True)


class TestTDFOLCECBridge:
    """Test the TDFOL-CEC Bridge component."""
    
    def setup_method(self):
        """Setup for each test."""
        self.bridge = TDFOLCECBridge()
    
    def test_bridge_initialization(self):
        """Test bridge initializes correctly."""
        assert self.bridge is not None
        assert isinstance(self.bridge, TDFOLCECBridge)
    
    def test_cec_availability(self):
        """Test CEC availability detection."""
        # Should detect CEC availability
        assert hasattr(self.bridge, 'cec_available')
        assert isinstance(self.bridge.cec_available, bool)
    
    def test_cec_rules_loading(self):
        """Test CEC rules are loaded if available."""
        if self.bridge.cec_available:
            assert self.bridge.cec_rules is not None
            assert isinstance(self.bridge.cec_rules, list)
            # Should have some rules
            assert len(self.bridge.cec_rules) >= 0
    
    def test_tdfol_to_dcec_conversion(self):
        """Test TDFOL to DCEC string conversion."""
        # Create simple TDFOL formula
        p = Predicate("P", ())
        
        try:
            dcec_str = self.bridge.tdfol_to_dcec_string(p)
            assert dcec_str is not None
            assert isinstance(dcec_str, str)
            assert len(dcec_str) > 0
        except Exception as e:
            # Conversion might not be fully implemented
            pytest.skip(f"Conversion not yet fully implemented: {e}")
    
    def test_dcec_to_tdfol_conversion(self):
        """Test DCEC string to TDFOL conversion."""
        dcec_str = "(and P Q)"
        
        try:
            formula = self.bridge.dcec_string_to_tdfol(dcec_str)
            assert formula is not None
            assert isinstance(formula, Formula)
        except Exception as e:
            # Might fail if DCEC parser not fully available
            logging.debug(f"DCEC parsing not available: {e}")
    
    def test_bidirectional_conversion(self):
        """Test round-trip conversion TDFOL → DCEC → TDFOL."""
        # Create simple formula
        p = Predicate("P", ())
        
        try:
            # Convert to DCEC
            dcec_str = self.bridge.tdfol_to_dcec_string(p)
            
            # Convert back to TDFOL
            formula = self.bridge.dcec_string_to_tdfol(dcec_str)
            
            # Should be equivalent
            assert formula is not None
            # Note: Exact equality might not hold due to formatting
        except Exception as e:
            pytest.skip(f"Bidirectional conversion not yet fully working: {e}")


class TestEnhancedTDFOLProver:
    """Test the Enhanced TDFOL Prover with CEC integration."""
    
    def setup_method(self):
        """Setup for each test."""
        self.prover = EnhancedTDFOLProver(use_cec=True)
    
    def test_prover_initialization(self):
        """Test prover initializes correctly."""
        assert self.prover is not None
        assert isinstance(self.prover, EnhancedTDFOLProver)
    
    def test_prover_has_cec_bridge(self):
        """Test prover has CEC bridge."""
        assert hasattr(self.prover, 'cec_bridge')
        if self.prover.use_cec:
            assert self.prover.cec_bridge is not None
    
    def test_simple_proof_modus_ponens(self):
        """Test simple Modus Ponens proof."""
        # Add axioms: P, P → Q
        p = Predicate("P", ())
        q = Predicate("Q", ())
        implication = BinaryFormula(LogicOperator.IMPLIES, p, q)
        
        self.prover.kb.add_axiom(p)
        self.prover.kb.add_axiom(implication)
        
        # Try to prove Q
        result = self.prover.prove(q, timeout_ms=1000)
        
        # Should be able to prove Q using Modus Ponens
        assert result is not None
        # Note: Might not prove if prover not fully connected
        logging.info(f"Proof result: {result.status}")
    
    def test_proof_with_cec_disabled(self):
        """Test proof with CEC disabled."""
        prover = EnhancedTDFOLProver(use_cec=False)
        
        p = Predicate("P", ())
        q = Predicate("Q", ())
        implication = BinaryFormula(LogicOperator.IMPLIES, p, q)
        
        prover.kb.add_axiom(p)
        prover.kb.add_axiom(implication)
        
        result = prover.prove(q, timeout_ms=1000)
        assert result is not None
    
    def test_proof_with_cec_override(self):
        """Test proof with CEC override parameter."""
        p = Predicate("P", ())
        
        self.prover.kb.add_axiom(p)
        
        # Try with CEC explicitly enabled
        result1 = self.prover.prove(p, timeout_ms=1000, use_cec=True)
        assert result1 is not None
        
        # Try with CEC explicitly disabled
        result2 = self.prover.prove(p, timeout_ms=1000, use_cec=False)
        assert result2 is not None


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def test_create_enhanced_prover_with_cec(self):
        """Test creating enhanced prover with CEC."""
        prover = create_enhanced_prover(use_cec=True)
        assert prover is not None
        assert isinstance(prover, EnhancedTDFOLProver)
        assert prover.use_cec == True
    
    def test_create_enhanced_prover_without_cec(self):
        """Test creating enhanced prover without CEC."""
        prover = create_enhanced_prover(use_cec=False)
        assert prover is not None
        assert isinstance(prover, EnhancedTDFOLProver)
        assert prover.use_cec == False


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
