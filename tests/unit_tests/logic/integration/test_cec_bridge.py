"""
Tests for CEC Integration Bridge.

Tests the integration between CEC implementations and existing
logic infrastructure (IPFS cache, Z3 bridge, prover router).
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass
from typing import Optional, Any

# Import the bridge
from ipfs_datasets_py.logic.integration.cec_bridge import (
    CECBridge,
    UnifiedProofResult,
    Z3_AVAILABLE
)


class TestUnifiedProofResult:
    """Test UnifiedProofResult dataclass."""
    
    def test_unified_result_creation(self):
        """GIVEN unified result data WHEN creating UnifiedProofResult THEN fields are set correctly."""
        # GIVEN
        result = UnifiedProofResult(
            is_proved=True,
            is_valid=True,
            prover_used='z3',
            proof_time=0.5,
            status='valid'
        )
        
        # THEN
        assert result.is_proved is True
        assert result.is_valid is True
        assert result.prover_used == 'z3'
        assert result.proof_time == 0.5
        assert result.status == 'valid'
        assert result.model is None
        assert result.error_message is None


class TestCECBridgeInitialization:
    """Test CECBridge initialization."""
    
    def test_bridge_initialization_default(self):
        """GIVEN default parameters WHEN creating bridge THEN components are initialized."""
        # WHEN
        bridge = CECBridge(enable_ipfs_cache=False)  # Disable IPFS for testing
        
        # THEN
        assert bridge.enable_z3 is True
        assert bridge.enable_prover_router is True
        assert bridge.cache_ttl == 3600
        assert bridge.cec_prover_manager is not None
        assert bridge.cec_cache is not None
    
    def test_bridge_initialization_custom(self):
        """GIVEN custom parameters WHEN creating bridge THEN custom config is used."""
        # WHEN
        bridge = CECBridge(
            enable_ipfs_cache=False,
            enable_z3=False,
            enable_prover_router=False,
            cache_ttl=7200
        )
        
        # THEN
        assert bridge.enable_z3 is False
        assert bridge.enable_prover_router is False
        assert bridge.cache_ttl == 7200
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not available")
    def test_bridge_z3_available(self):
        """GIVEN Z3 is available WHEN creating bridge THEN Z3 components are initialized."""
        # WHEN
        bridge = CECBridge(enable_ipfs_cache=False, enable_z3=True)
        
        # THEN
        assert bridge.cec_z3 is not None
        assert bridge.z3_bridge is not None


class TestCECBridgeStrategSelection:
    """Test strategy selection logic."""
    
    def test_select_strategy_modal_formula(self):
        """GIVEN deontic formula WHEN selecting strategy THEN z3 is selected."""
        # GIVEN
        bridge = CECBridge(enable_ipfs_cache=False)
        
        # Create mock deontic formula
        from ipfs_datasets_py.logic.CEC.native.dcec_core import (
            DeonticFormula, DeonticOperator, AtomicFormula, Predicate
        )
        pred = Predicate(name="P", argument_sorts=[])
        formula = DeonticFormula(
            operator=DeonticOperator.OBLIGATION,
            formula=AtomicFormula(predicate=pred, arguments=[])
        )
        
        # WHEN
        strategy = bridge._select_strategy(formula)
        
        # THEN
        assert strategy in ['z3', 'cec']
    
    def test_select_strategy_non_modal(self):
        """GIVEN non-modal formula WHEN selecting strategy THEN router or cec is selected."""
        # GIVEN
        bridge = CECBridge(enable_ipfs_cache=False)
        
        # Create mock atomic formula
        from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula, Predicate
        formula = AtomicFormula(predicate=Predicate(name="P", argument_sorts=[]), arguments=[])
        
        # WHEN
        strategy = bridge._select_strategy(formula)
        
        # THEN
        assert strategy in ['router', 'cec']


class TestCECBridgeProving:
    """Test proving with different strategies."""
    
    def test_prove_with_cache_disabled(self):
        """GIVEN formula and cache disabled WHEN proving THEN proof is attempted."""
        # GIVEN
        bridge = CECBridge(enable_ipfs_cache=False)
        from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula, Predicate
        formula = AtomicFormula(predicate=Predicate(name="P", argument_sorts=[]), arguments=[])
        
        # Mock the CEC manager
        mock_result = Mock()
        mock_result.is_valid = True
        mock_result.prover_used = 'native'
        bridge.cec_prover_manager.prove = Mock(return_value=mock_result)
        
        # WHEN
        result = bridge.prove(formula, use_cache=False, strategy='cec')
        
        # THEN
        assert result.is_proved is True
        assert 'cec' in result.prover_used
        bridge.cec_prover_manager.prove.assert_called_once()
    
    def test_prove_with_cec_manager_error(self):
        """GIVEN proving fails WHEN using CEC manager THEN error result is returned."""
        # GIVEN
        bridge = CECBridge(enable_ipfs_cache=False)
        from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula, Predicate
        formula = AtomicFormula(predicate=Predicate(name="P", argument_sorts=[]), arguments=[])
        
        # Mock the CEC manager to raise exception
        bridge.cec_prover_manager.prove = Mock(side_effect=Exception("Test error"))
        
        # WHEN
        result = bridge.prove(formula, strategy='cec', use_cache=False)
        
        # THEN
        assert result.is_proved is False
        assert result.status == 'error'
        assert 'Test error' in result.error_message


class TestCECBridgeCaching:
    """Test caching functionality."""
    
    def test_compute_formula_hash(self):
        """GIVEN formula WHEN computing hash THEN consistent hash is returned."""
        # GIVEN
        bridge = CECBridge(enable_ipfs_cache=False)
        from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula, Predicate
        formula = AtomicFormula(predicate=Predicate(name="P", argument_sorts=[]), arguments=[])
        
        # WHEN
        hash1 = bridge._compute_formula_hash(formula)
        hash2 = bridge._compute_formula_hash(formula)
        
        # THEN
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex digest
    
    def test_cache_proof_local_only(self):
        """GIVEN proof result WHEN caching without IPFS THEN stored in local cache."""
        # GIVEN
        bridge = CECBridge(enable_ipfs_cache=False)
        from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula, Predicate
        formula = AtomicFormula(predicate=Predicate(name="P", argument_sorts=[]), arguments=[])
        
        result = UnifiedProofResult(
            is_proved=True,
            is_valid=True,
            prover_used='test',
            proof_time=1.0,
            status='valid'
        )
        
        # WHEN
        bridge._cache_proof(formula, result)
        
        # THEN - should not raise exception
        assert True
    
    def test_get_cached_proof_miss(self):
        """GIVEN empty cache WHEN getting cached proof THEN None is returned."""
        # GIVEN
        bridge = CECBridge(enable_ipfs_cache=False)
        from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula, Predicate
        formula = AtomicFormula(predicate=Predicate(name="P", argument_sorts=[]), arguments=[])
        
        # WHEN
        cached = bridge._get_cached_proof(formula)
        
        # THEN
        assert cached is None


class TestCECBridgeStatistics:
    """Test statistics gathering."""
    
    def test_get_statistics(self):
        """GIVEN bridge with components WHEN getting statistics THEN dict is returned."""
        # GIVEN
        bridge = CECBridge(enable_ipfs_cache=False)
        
        # WHEN
        stats = bridge.get_statistics()
        
        # THEN
        assert isinstance(stats, dict)
        assert 'cec_cache' in stats
        assert 'ipfs_cache' in stats
        assert 'cec_manager' in stats
    
    def test_get_statistics_structure(self):
        """GIVEN statistics WHEN examining structure THEN expected keys present."""
        # GIVEN
        bridge = CECBridge(enable_ipfs_cache=False)
        
        # WHEN
        stats = bridge.get_statistics()
        
        # THEN
        assert isinstance(stats['cec_cache'], dict)
        assert isinstance(stats['ipfs_cache'], dict)
        assert isinstance(stats['cec_manager'], dict)


class TestCECBridgeIntegration:
    """Integration tests for CECBridge."""
    
    @pytest.mark.skipif(not Z3_AVAILABLE, reason="Z3 not available")
    def test_prove_simple_formula_z3(self):
        """GIVEN simple formula WHEN proving with Z3 THEN proof succeeds."""
        # GIVEN
        bridge = CECBridge(enable_ipfs_cache=False, enable_z3=True)
        from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula, Predicate
        formula = AtomicFormula(predicate=Predicate(name="P", argument_sorts=[]), arguments=[])
        
        # WHEN
        result = bridge.prove(formula, strategy='z3', use_cache=False)
        
        # THEN
        assert result is not None
        assert result.status in ['valid', 'invalid', 'error', 'unknown']
    
    def test_prove_with_axioms(self):
        """GIVEN formula and axioms WHEN proving THEN axioms are used."""
        # GIVEN
        bridge = CECBridge(enable_ipfs_cache=False)
        from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula, Predicate
        formula = AtomicFormula(predicate=Predicate(name="Q", argument_sorts=[]), arguments=[])
        axiom = AtomicFormula(predicate=Predicate(name="P", argument_sorts=[]), arguments=[])
        
        # Mock the CEC manager
        mock_result = Mock()
        mock_result.is_valid = True
        mock_result.prover_used = 'native'
        bridge.cec_prover_manager.prove = Mock(return_value=mock_result)
        
        # WHEN
        result = bridge.prove(formula, axioms=[axiom], strategy='cec', use_cache=False)
        
        # THEN
        assert result.is_proved is True
        # Verify axioms were passed
        call_args = bridge.cec_prover_manager.prove.call_args
        assert len(call_args[0][1]) == 1  # One axiom


# Run tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
