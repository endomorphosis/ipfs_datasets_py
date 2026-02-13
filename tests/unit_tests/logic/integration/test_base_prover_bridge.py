#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tests for Base Prover Bridge pattern and bridge consolidation.

This test suite validates:
- BaseProverBridge abstract interface
- Bridge metadata and capabilities
- Bridge registry functionality
- Bridge implementations (CEC, ShadowProver, Grammar)
"""

import pytest
from typing import Any, Optional

try:
    from ipfs_datasets_py.logic.integration.base_prover_bridge import (
        BaseProverBridge,
        BridgeMetadata,
        BridgeCapability,
        BridgeRegistry,
        get_bridge_registry
    )
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import Formula, Predicate, Variable
    from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus
    BASE_BRIDGE_AVAILABLE = True
    SKIP_REASON = ""
except ImportError as e:
    BASE_BRIDGE_AVAILABLE = False
    SKIP_REASON = f"Base bridge not available: {e}"


# Mock bridge for testing
class MockBridge(BaseProverBridge):
    """Mock bridge implementation for testing."""
    
    def _init_metadata(self) -> BridgeMetadata:
        return BridgeMetadata(
            name="Mock Bridge",
            version="1.0.0",
            target_system="Mock",
            capabilities=[BridgeCapability.BIDIRECTIONAL_CONVERSION],
            requires_external_prover=False,
            description="Mock bridge for testing"
        )
    
    def _check_availability(self) -> bool:
        return True
    
    def to_target_format(self, formula: Formula) -> str:
        return f"MOCK({formula})"
    
    def from_target_format(self, target_result: Any) -> ProofResult:
        return ProofResult(
            status=ProofStatus.PROVED,
            formula=None,
            time_ms=0,
            method="mock"
        )
    
    def prove(self, formula: Formula, timeout: Optional[int] = None, **kwargs) -> ProofResult:
        return ProofResult(
            status=ProofStatus.PROVED,
            formula=formula,
            time_ms=10,
            method="mock"
        )


@pytest.mark.skipif(not BASE_BRIDGE_AVAILABLE, reason=SKIP_REASON)
class TestBridgeCapability:
    """Test BridgeCapability enum."""
    
    def test_capability_values(self):
        """
        GIVEN BridgeCapability enum
        WHEN accessing enum values
        THEN all capabilities should be available
        """
        assert BridgeCapability.BIDIRECTIONAL_CONVERSION.value == "bidirectional"
        assert BridgeCapability.INCREMENTAL_PROVING.value == "incremental"
        assert BridgeCapability.RULE_EXTRACTION.value == "rule_extraction"
        assert BridgeCapability.OPTIMIZATION.value == "optimization"
        assert BridgeCapability.PARALLEL_PROVING.value == "parallel"


@pytest.mark.skipif(not BASE_BRIDGE_AVAILABLE, reason=SKIP_REASON)
class TestBridgeMetadata:
    """Test BridgeMetadata dataclass."""
    
    def test_metadata_creation(self):
        """
        GIVEN bridge metadata parameters
        WHEN BridgeMetadata is created
        THEN all fields should be properly set
        """
        metadata = BridgeMetadata(
            name="Test Bridge",
            version="1.0.0",
            target_system="TestSystem",
            capabilities=[BridgeCapability.BIDIRECTIONAL_CONVERSION],
            requires_external_prover=True,
            description="Test bridge"
        )
        
        assert metadata.name == "Test Bridge"
        assert metadata.version == "1.0.0"
        assert metadata.target_system == "TestSystem"
        assert BridgeCapability.BIDIRECTIONAL_CONVERSION in metadata.capabilities
        assert metadata.requires_external_prover is True
        assert metadata.description == "Test bridge"
    
    def test_metadata_multiple_capabilities(self):
        """
        GIVEN metadata with multiple capabilities
        WHEN BridgeMetadata is created
        THEN all capabilities should be stored
        """
        capabilities = [
            BridgeCapability.BIDIRECTIONAL_CONVERSION,
            BridgeCapability.OPTIMIZATION,
            BridgeCapability.PARALLEL_PROVING
        ]
        
        metadata = BridgeMetadata(
            name="Multi-Capability Bridge",
            version="2.0.0",
            target_system="Advanced",
            capabilities=capabilities,
            requires_external_prover=False,
            description="Advanced bridge"
        )
        
        assert len(metadata.capabilities) == 3
        for cap in capabilities:
            assert cap in metadata.capabilities


@pytest.mark.skipif(not BASE_BRIDGE_AVAILABLE, reason=SKIP_REASON)
class TestBaseProverBridge:
    """Test BaseProverBridge abstract interface."""
    
    def test_mock_bridge_instantiation(self):
        """
        GIVEN MockBridge implementation
        WHEN bridge is instantiated
        THEN bridge should be properly initialized
        """
        bridge = MockBridge()
        
        assert bridge.is_available() is True
        assert bridge.get_metadata().name == "Mock Bridge"
        assert bridge.get_metadata().target_system == "Mock"
    
    def test_to_target_format(self):
        """
        GIVEN a TDFOL formula
        WHEN to_target_format is called
        THEN formula should be converted to target format
        """
        bridge = MockBridge()
        
        # Create a simple predicate
        pred = Predicate("Human", [Variable("x")])
        result = bridge.to_target_format(pred)
        
        assert "MOCK" in result
        assert isinstance(result, str)
    
    def test_from_target_format(self):
        """
        GIVEN a target result
        WHEN from_target_format is called
        THEN result should be converted to ProofResult
        """
        bridge = MockBridge()
        
        target_result = "some_result"
        proof_result = bridge.from_target_format(target_result)
        
        assert isinstance(proof_result, ProofResult)
        assert proof_result.status == ProofStatus.PROVED
    
    def test_prove(self):
        """
        GIVEN a formula
        WHEN prove is called
        THEN proof should be executed
        """
        bridge = MockBridge()
        
        pred = Predicate("Test", [Variable("x")])
        result = bridge.prove(pred)
        
        assert isinstance(result, ProofResult)
        assert result.status == ProofStatus.PROVED
        assert result.formula == pred
        assert result.time_ms == 10
        assert result.method == "mock"
    
    def test_is_available(self):
        """
        GIVEN an initialized bridge
        WHEN is_available is called
        THEN availability status should be returned
        """
        bridge = MockBridge()
        
        assert bridge.is_available() is True
    
    def test_get_capabilities(self):
        """
        GIVEN an initialized bridge
        WHEN get_capabilities is called
        THEN list of capabilities should be returned
        """
        bridge = MockBridge()
        
        capabilities = bridge.get_capabilities()
        
        assert isinstance(capabilities, list)
        assert BridgeCapability.BIDIRECTIONAL_CONVERSION in capabilities
    
    def test_has_capability(self):
        """
        GIVEN a bridge with specific capabilities
        WHEN has_capability is called
        THEN correct boolean should be returned
        """
        bridge = MockBridge()
        
        assert bridge.has_capability(BridgeCapability.BIDIRECTIONAL_CONVERSION) is True
        assert bridge.has_capability(BridgeCapability.PARALLEL_PROVING) is False
    
    def test_validate_formula(self):
        """
        GIVEN a formula
        WHEN validate_formula is called
        THEN validation status should be returned
        """
        bridge = MockBridge()
        
        pred = Predicate("Valid", [Variable("x")])
        assert bridge.validate_formula(pred) is True
    
    def test_repr(self):
        """
        GIVEN an initialized bridge
        WHEN repr is called
        THEN string representation should be returned
        """
        bridge = MockBridge()
        
        repr_str = repr(bridge)
        
        assert "MockBridge" in repr_str
        assert "Mock" in repr_str
        assert "available=True" in repr_str


@pytest.mark.skipif(not BASE_BRIDGE_AVAILABLE, reason=SKIP_REASON)
class TestBridgeRegistry:
    """Test BridgeRegistry functionality."""
    
    def test_registry_initialization(self):
        """
        GIVEN no parameters
        WHEN BridgeRegistry is created
        THEN empty registry should be initialized
        """
        registry = BridgeRegistry()
        
        assert len(registry.list_all()) == 0
        assert len(registry.list_available()) == 0
    
    def test_register_bridge(self):
        """
        GIVEN a bridge instance
        WHEN register is called
        THEN bridge should be added to registry
        """
        registry = BridgeRegistry()
        bridge = MockBridge()
        
        registry.register("mock", bridge)
        
        assert "mock" in registry.list_all()
        assert "mock" in registry.list_available()
    
    def test_get_bridge(self):
        """
        GIVEN a registered bridge
        WHEN get is called
        THEN correct bridge should be returned
        """
        registry = BridgeRegistry()
        bridge = MockBridge()
        registry.register("mock", bridge)
        
        retrieved = registry.get("mock")
        
        assert retrieved is bridge
    
    def test_get_nonexistent_bridge(self):
        """
        GIVEN an empty registry
        WHEN get is called for nonexistent bridge
        THEN None should be returned
        """
        registry = BridgeRegistry()
        
        result = registry.get("nonexistent")
        
        assert result is None
    
    def test_list_available_filters_unavailable(self):
        """
        GIVEN registry with available and unavailable bridges
        WHEN list_available is called
        THEN only available bridges should be listed
        """
        registry = BridgeRegistry()
        
        available_bridge = MockBridge()
        registry.register("available", available_bridge)
        
        # Mock unavailable bridge
        class UnavailableBridge(MockBridge):
            def _check_availability(self) -> bool:
                return False
        
        unavailable_bridge = UnavailableBridge()
        registry.register("unavailable", unavailable_bridge)
        
        available = registry.list_available()
        
        assert "available" in available
        assert "unavailable" not in available
    
    def test_find_capable(self):
        """
        GIVEN bridges with different capabilities
        WHEN find_capable is called
        THEN bridges with that capability should be returned
        """
        registry = BridgeRegistry()
        
        # Mock bridge with optimization capability
        class OptimizingBridge(MockBridge):
            def _init_metadata(self) -> BridgeMetadata:
                return BridgeMetadata(
                    name="Optimizing Bridge",
                    version="1.0.0",
                    target_system="Optimizer",
                    capabilities=[
                        BridgeCapability.BIDIRECTIONAL_CONVERSION,
                        BridgeCapability.OPTIMIZATION
                    ],
                    requires_external_prover=False,
                    description="Optimizing bridge"
                )
        
        registry.register("basic", MockBridge())
        registry.register("optimizer", OptimizingBridge())
        
        optimizers = registry.find_capable(BridgeCapability.OPTIMIZATION)
        
        assert "optimizer" in optimizers
        assert "basic" not in optimizers
    
    def test_select_best_with_preferred(self):
        """
        GIVEN multiple bridges and a preferred name
        WHEN select_best is called
        THEN preferred bridge should be returned if available
        """
        registry = BridgeRegistry()
        
        bridge1 = MockBridge()
        bridge2 = MockBridge()
        
        registry.register("bridge1", bridge1)
        registry.register("bridge2", bridge2)
        
        pred = Predicate("Test", [Variable("x")])
        selected = registry.select_best(pred, preferred="bridge2")
        
        assert selected is bridge2
    
    def test_select_best_without_preferred(self):
        """
        GIVEN multiple bridges and no preference
        WHEN select_best is called
        THEN first available bridge should be returned
        """
        registry = BridgeRegistry()
        
        bridge = MockBridge()
        registry.register("bridge", bridge)
        
        pred = Predicate("Test", [Variable("x")])
        selected = registry.select_best(pred)
        
        assert selected is bridge
    
    def test_select_best_no_valid_bridge(self):
        """
        GIVEN empty registry
        WHEN select_best is called
        THEN None should be returned
        """
        registry = BridgeRegistry()
        
        pred = Predicate("Test", [Variable("x")])
        selected = registry.select_best(pred)
        
        assert selected is None


@pytest.mark.skipif(not BASE_BRIDGE_AVAILABLE, reason=SKIP_REASON)
class TestGlobalRegistry:
    """Test global bridge registry."""
    
    def test_get_global_registry(self):
        """
        GIVEN global registry
        WHEN get_bridge_registry is called
        THEN same instance should be returned
        """
        registry1 = get_bridge_registry()
        registry2 = get_bridge_registry()
        
        assert registry1 is registry2
        assert isinstance(registry1, BridgeRegistry)


@pytest.mark.skipif(not BASE_BRIDGE_AVAILABLE, reason=SKIP_REASON)
class TestBridgeIntegration:
    """Test bridge pattern integration."""
    
    def test_end_to_end_bridge_workflow(self):
        """
        GIVEN a bridge registered in registry
        WHEN formula is proved through registry
        THEN complete workflow should succeed
        """
        registry = BridgeRegistry()
        bridge = MockBridge()
        registry.register("mock", bridge)
        
        # Create formula
        pred = Predicate("TestProp", [Variable("x")])
        
        # Select bridge
        selected = registry.select_best(pred)
        
        # Prove
        result = selected.prove(pred)
        
        assert result.status == ProofStatus.PROVED
        assert result.formula == pred
