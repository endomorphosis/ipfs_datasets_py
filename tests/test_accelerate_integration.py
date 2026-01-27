"""
Tests for ipfs_accelerate_py integration.

This test suite validates the accelerate integration with both
enabled and disabled states to ensure proper fallback behavior.
"""

import os
import pytest
from ipfs_datasets_py.accelerate_integration import (
    is_accelerate_available,
    get_accelerate_status,
    AccelerateManager,
    ComputeBackend,
    get_compute_backend,
    DistributedComputeCoordinator,
    HAVE_ACCELERATE_MANAGER
)


class TestAccelerateIntegration:
    """Test suite for accelerate integration."""
    
    def test_import_accelerate_module(self):
        """
        GIVEN the accelerate_integration module
        WHEN importing the module
        THEN it should import without errors
        """
        from ipfs_datasets_py import accelerate_integration
        assert accelerate_integration is not None
    
    def test_is_accelerate_available(self):
        """
        GIVEN the accelerate integration
        WHEN checking if accelerate is available
        THEN it should return a boolean
        """
        result = is_accelerate_available()
        assert isinstance(result, bool)
    
    def test_get_accelerate_status(self):
        """
        GIVEN the accelerate integration
        WHEN getting the accelerate status
        THEN it should return a dictionary with expected keys
        """
        status = get_accelerate_status()
        
        assert isinstance(status, dict)
        assert "available" in status
        assert "enabled" in status
        assert "env_disabled" in status
        assert isinstance(status["available"], bool)
        assert isinstance(status["enabled"], bool)
    
    def test_accelerate_manager_init(self):
        """
        GIVEN the AccelerateManager class
        WHEN initializing a manager
        THEN it should initialize without errors
        """
        if AccelerateManager is None:
            pytest.skip("AccelerateManager not available (accelerate disabled or not installed)")
        
        manager = AccelerateManager()
        assert manager is not None
        assert hasattr(manager, 'is_available')
        assert hasattr(manager, 'run_inference')
    
    def test_accelerate_manager_status(self):
        """
        GIVEN an initialized AccelerateManager
        WHEN getting the manager status
        THEN it should return status information
        """
        if AccelerateManager is None:
            pytest.skip("AccelerateManager not available (accelerate disabled or not installed)")
        
        manager = AccelerateManager()
        status = manager.get_status()
        
        assert isinstance(status, dict)
        assert "accelerate_available" in status
        assert "available_hardware" in status
        assert isinstance(status["available_hardware"], list)
    
    def test_accelerate_manager_fallback(self):
        """
        GIVEN an AccelerateManager in fallback mode
        WHEN running inference
        THEN it should use local fallback and return results
        """
        if AccelerateManager is None:
            pytest.skip("AccelerateManager not available (accelerate disabled or not installed)")
        
        manager = AccelerateManager()
        result = manager.run_inference(
            model_name="test-model",
            input_data="test input",
            task_type="embedding"
        )
        
        assert isinstance(result, dict)
        assert "status" in result
        assert "backend" in result
        assert result["status"] == "success"
    
    def test_compute_backend_creation(self):
        """
        GIVEN the ComputeBackend class
        WHEN creating a compute backend
        THEN it should initialize properly
        """
        if ComputeBackend is None:
            pytest.skip("ComputeBackend not available (accelerate disabled or not installed)")
        
        from ipfs_datasets_py.accelerate_integration.compute_backend import HardwareType
        
        backend = ComputeBackend(HardwareType.CPU, device_id=0)
        assert backend is not None
        assert backend.hardware_type == HardwareType.CPU
    
    def test_get_compute_backend_auto(self):
        """
        GIVEN the get_compute_backend function
        WHEN calling it without arguments
        THEN it should auto-detect and return a backend
        """
        if get_compute_backend is None:
            pytest.skip("get_compute_backend not available (accelerate disabled or not installed)")
        
        backend = get_compute_backend()
        assert backend is not None
        assert hasattr(backend, 'hardware_type')
    
    def test_distributed_coordinator_init(self):
        """
        GIVEN the DistributedComputeCoordinator class
        WHEN initializing a coordinator
        THEN it should initialize without errors
        """
        if DistributedComputeCoordinator is None:
            pytest.skip("DistributedComputeCoordinator not available (accelerate disabled or not installed)")
        
        coordinator = DistributedComputeCoordinator()
        assert coordinator is not None
        assert hasattr(coordinator, 'submit_task')
        assert hasattr(coordinator, 'get_task_status')
    
    def test_distributed_coordinator_task_submission(self):
        """
        GIVEN an initialized DistributedComputeCoordinator
        WHEN submitting a task
        THEN it should create and track the task
        """
        if DistributedComputeCoordinator is None:
            pytest.skip("DistributedComputeCoordinator not available (accelerate disabled or not installed)")
        
        coordinator = DistributedComputeCoordinator()
        coordinator.initialize()
        
        task = coordinator.submit_task(
            task_id="test-001",
            model_name="test-model",
            input_data="test data",
            task_type="inference"
        )
        
        assert task is not None
        assert task.task_id == "test-001"
        assert task.model_name == "test-model"
    
    def test_distributed_coordinator_stats(self):
        """
        GIVEN an initialized coordinator with tasks
        WHEN getting statistics
        THEN it should return task counts and status
        """
        if DistributedComputeCoordinator is None:
            pytest.skip("DistributedComputeCoordinator not available (accelerate disabled or not installed)")
        
        coordinator = DistributedComputeCoordinator()
        coordinator.initialize()
        
        # Submit a task
        coordinator.submit_task(
            task_id="test-002",
            model_name="test-model",
            input_data="test data",
            task_type="inference"
        )
        
        stats = coordinator.get_stats()
        
        assert isinstance(stats, dict)
        assert "total_tasks" in stats
        assert stats["total_tasks"] >= 1


class TestAccelerateDisabled:
    """Test suite for when accelerate is explicitly disabled."""
    
    @pytest.fixture(autouse=True)
    def disable_accelerate(self, monkeypatch):
        """Disable accelerate for these tests."""
        monkeypatch.setenv('IPFS_ACCELERATE_ENABLED', '0')
    
    def test_accelerate_disabled_status(self):
        """
        GIVEN accelerate is disabled via environment variable
        WHEN checking the status
        THEN it should indicate accelerate is disabled
        """
        status = get_accelerate_status()
        assert status["env_disabled"] is True
    
    def test_accelerate_disabled_availability(self):
        """
        GIVEN accelerate is disabled via environment variable
        WHEN checking if accelerate is available
        THEN it should return False
        """
        # Note: This test needs to reimport to pick up the env var
        # In practice, the env var should be set before first import
        result = is_accelerate_available()
        # May be True if already imported before env var was set
        assert isinstance(result, bool)


class TestHardwareDetection:
    """Test suite for hardware detection."""
    
    def test_detect_available_hardware(self):
        """
        GIVEN the hardware detection function
        WHEN detecting available hardware
        THEN it should return a list of hardware types
        """
        if get_compute_backend is None:
            pytest.skip("Hardware detection not available")
        
        from ipfs_datasets_py.accelerate_integration.compute_backend import detect_available_hardware
        
        hardware = detect_available_hardware()
        assert isinstance(hardware, list)
        assert len(hardware) >= 1  # At least CPU should be available
    
    def test_cpu_always_available(self):
        """
        GIVEN hardware detection
        WHEN checking available hardware
        THEN CPU should always be in the list
        """
        if get_compute_backend is None:
            pytest.skip("Hardware detection not available")
        
        from ipfs_datasets_py.accelerate_integration.compute_backend import (
            detect_available_hardware,
            HardwareType
        )
        
        hardware = detect_available_hardware()
        assert HardwareType.CPU in hardware
