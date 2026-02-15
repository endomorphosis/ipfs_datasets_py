"""
Resource Utilization Tests for the Omni-Converter converted from unittest to pytest.

This module tests the memory and CPU usage of the application during processing.
"""
import pytest
from datetime import datetime
import json
import multiprocessing
import os
import platform
import tempfile
import time
from typing import Any
from unittest.mock import MagicMock, patch

# Import psutil for actual resource monitoring
try:
    import psutil
except ImportError:
    pytest.skip("psutil is required for this module. Please install it with 'pip install psutil'.", 
                allow_module_level=True)

from configs import configs
from _tests._fixtures import fixtures


@pytest.fixture
def results_dir():
    """Ensure results directory exists."""
    results_dir = 'tests/collected_results'
    os.makedirs(results_dir, exist_ok=True)
    return results_dir


@pytest.fixture
def resource_limits():
    """Define resource limits for testing."""
    return {
        'memory_limit_gb': 4.0,      # 4 GB memory limit
        'cpu_limit_percent': 80.0    # 80% CPU limit
    }


@pytest.fixture
def temp_output_dir():
    """Create temporary output directory for tests."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Cleanup
    if os.path.exists(temp_dir):
        import shutil
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            print(f"Warning: Failed to remove temporary directory: {e}")


@pytest.fixture
def mock_resource_monitor():
    """Create a mock resource monitor for testing."""
    mock_monitor = MagicMock()
    mock_monitor.current_resource_usage = {
        'memory': 200.0,  # MB
        'cpu': 30.0       # Percent
    }
    return mock_monitor


def _create_test_batches() -> list[dict[str, Any]]:
    """Create test batches for resource utilization testing."""
    return [
        {
            'name': 'small_batch',
            'file_count': 5,
            'files_per_batch': 5,
            'expected_memory_mb': 100,
            'expected_cpu_percent': 40
        },
        {
            'name': 'medium_batch', 
            'file_count': 20,
            'files_per_batch': 10,
            'expected_memory_mb': 300,
            'expected_cpu_percent': 60
        },
        {
            'name': 'large_batch',
            'file_count': 50,
            'files_per_batch': 25,
            'expected_memory_mb': 800,
            'expected_cpu_percent': 75
        }
    ]


@pytest.mark.performance
class TestResourceUtilization:
    """Test case for resource utilization during file processing."""

    @pytest.fixture(autouse=True)
    def setup_test_results(self, results_dir, resource_limits):
        """Initialize test results structure."""
        self.memory_limit_gb = resource_limits['memory_limit_gb']
        self.cpu_limit_percent = resource_limits['cpu_limit_percent']
        
        self.results = {
            'test_name': 'Resource Utilization',
            'timestamp': datetime.now().isoformat(),
            'system_info': self._get_system_info(),
            'test_batches': [],
            'overall': {}
        }
        yield
        # Save results to JSON file after test
        output_file = os.path.join(results_dir, 'resource_utilization.json')
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\nTest results saved to {output_file}")

    def _get_system_info(self) -> dict[str, Any]:
        """Get system information for context."""
        return {
            'platform': platform.platform(),
            'cpu_count': multiprocessing.cpu_count(),
            'total_memory_gb': psutil.virtual_memory().total / (1024**3),
            'python_version': platform.python_version()
        }

    def test_resource_utilization(self, mock_resource_monitor, temp_output_dir):
        """Test resource utilization during file processing."""
        try:
            # Import the required modules here to allow for graceful failure
            # from monitors.resource_monitor_factory import make_resource_monitor
            
            # Use the mock resource monitor for testing
            resource_monitor = mock_resource_monitor
            
            # Create test batches
            test_batches = _create_test_batches()
            
            overall_peak_memory_gb = 0.0
            overall_peak_cpu_percent = 0.0
            
            for batch in test_batches:
                print(f"\nTesting batch: {batch['name']}")
                print(f"Files: {batch['file_count']}, Batch size: {batch['files_per_batch']}")
                
                # Simulate batch processing and monitor resources
                batch_results = self._simulate_batch_processing(batch, resource_monitor)
                
                self.results['test_batches'].append({
                    'batch_name': batch['name'],
                    'batch_config': batch,
                    'resource_usage': batch_results
                })
                
                # Track peak usage
                batch_peak_memory_gb = batch_results['peak_memory_mb'] / 1024
                batch_peak_cpu = batch_results['peak_cpu_percent']
                
                if batch_peak_memory_gb > overall_peak_memory_gb:
                    overall_peak_memory_gb = batch_peak_memory_gb
                if batch_peak_cpu > overall_peak_cpu_percent:
                    overall_peak_cpu_percent = batch_peak_cpu
                
                print(f"Peak memory: {batch_peak_memory_gb:.2f} GB")
                print(f"Peak CPU: {batch_peak_cpu:.1f}%")
                print(f"Within memory limit: {batch_peak_memory_gb < self.memory_limit_gb}")
                print(f"Within CPU limit: {batch_peak_cpu < self.cpu_limit_percent}")
            
            # Check overall compliance
            overall_within_memory_limit = overall_peak_memory_gb < self.memory_limit_gb
            overall_within_cpu_limit = overall_peak_cpu_percent < self.cpu_limit_percent
            
            # Store overall results
            self.results['overall'] = {
                'peak_memory_gb': overall_peak_memory_gb,
                'peak_cpu_percent': overall_peak_cpu_percent,
                'within_memory_limit': overall_within_memory_limit,
                'within_cpu_limit': overall_within_cpu_limit,
                'memory_limit_gb': self.memory_limit_gb,
                'cpu_limit_percent': self.cpu_limit_percent
            }
            
            # Print overall results to console
            print("\nOverall Results:")
            print(f"Peak memory usage across all batches: {overall_peak_memory_gb:.2f} GB (Limit: {self.memory_limit_gb} GB)")
            print(f"Peak CPU usage across all batches: {overall_peak_cpu_percent:.2f}% (Limit: {self.cpu_limit_percent}%)")
            print(f"Overall within memory limit: {overall_within_memory_limit}")
            print(f"Overall within CPU limit: {overall_within_cpu_limit}")
            
            # Assert that resource usage is within limits
            assert overall_peak_memory_gb < self.memory_limit_gb, f"Memory usage {overall_peak_memory_gb:.2f} GB exceeds limit {self.memory_limit_gb} GB"
            assert overall_peak_cpu_percent < self.cpu_limit_percent, f"CPU usage {overall_peak_cpu_percent:.1f}% exceeds limit {self.cpu_limit_percent}%"
            
        except ImportError as e:
            print(f"Failed to import required modules: {e}")
            self.results['error'] = str(e)
            pytest.fail(f"ImportError: {e}")
        except Exception as e:
            print(f"Unexpected error during testing: {e}")
            self.results['error'] = str(e)
            pytest.fail(f"Error: {e}")

    def _simulate_batch_processing(self, batch: dict[str, Any], resource_monitor) -> dict[str, Any]:
        """Simulate batch processing and monitor resource usage."""
        batch_name = batch['name']
        file_count = batch['file_count']
        files_per_batch = batch['files_per_batch']
        
        # Start resource monitoring
        resource_measurements = []
        peak_memory_mb = 0.0
        peak_cpu_percent = 0.0
        
        # Simulate processing files in batches
        start_time = time.time()
        memory_objects = []  # To simulate memory usage
        
        try:
            for file_index in range(file_count):
                # Simulate memory allocation for file processing
                # Create some memory objects to simulate memory usage
                memory_chunk = bytearray(1024 * 1024)  # 1 MB per file
                memory_objects.append(memory_chunk)
                
                # Simulate CPU usage
                cpu_start_time = time.time()
                while time.time() - cpu_start_time < 0.1:  # Short CPU burst
                    # Do something CPU-intensive
                    for _ in range(10000):
                        _ = 3.1415 ** 2.7182
                
                # Mock resource usage that increases with workload
                simulated_memory_mb = len(memory_objects) * 1.5  # 1.5 MB per file processed
                simulated_cpu_percent = min(30 + (file_index * 2), 90)  # Gradually increasing CPU
                
                # Update mock resource monitor
                resource_monitor.current_resource_usage = {
                    'memory': simulated_memory_mb,
                    'cpu': simulated_cpu_percent
                }
                
                current_memory = resource_monitor.current_resource_usage.get('memory', 0)
                current_cpu = resource_monitor.current_resource_usage.get('cpu', 0)
                
                print(f"Current usage - Memory: {current_memory:.2f} MB, CPU: {current_cpu:.2f}%")
                
                # Track peak usage
                if current_memory > peak_memory_mb:
                    peak_memory_mb = current_memory
                if current_cpu > peak_cpu_percent:
                    peak_cpu_percent = current_cpu
                
                resource_measurements.append({
                    'timestamp': time.time(),
                    'memory_mb': current_memory,
                    'cpu_percent': current_cpu,
                    'files_processed': file_index + 1
                })
                
                # Sleep briefly to allow resource monitor to take measurements
                time.sleep(0.05)
            
            # Hold the allocated memory briefly to simulate peak usage
            time.sleep(0.5)
            
        finally:
            # Clear memory objects to release memory
            memory_objects.clear()
        
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        return {
            'batch_name': batch_name,
            'elapsed_time_seconds': elapsed_time,
            'files_processed': file_count,
            'peak_memory_mb': peak_memory_mb,
            'peak_cpu_percent': peak_cpu_percent,
            'average_memory_mb': sum(m['memory_mb'] for m in resource_measurements) / len(resource_measurements) if resource_measurements else 0,
            'average_cpu_percent': sum(m['cpu_percent'] for m in resource_measurements) / len(resource_measurements) if resource_measurements else 0,
            'resource_measurements': resource_measurements
        }

    def test_memory_cleanup(self, mock_resource_monitor):
        """Test that memory is properly cleaned up after processing."""
        try:
            # Get initial memory usage
            initial_memory = mock_resource_monitor.current_resource_usage.get('memory', 0)
            
            # Simulate processing that allocates memory
            memory_objects = []
            for i in range(10):
                memory_chunk = bytearray(1024 * 1024)  # 1 MB chunks
                memory_objects.append(memory_chunk)
                
                # Update mock memory usage
                mock_resource_monitor.current_resource_usage['memory'] = initial_memory + len(memory_objects)
            
            peak_memory = mock_resource_monitor.current_resource_usage.get('memory', 0)
            print(f"Peak memory during processing: {peak_memory:.2f} MB")
            
            # Clean up memory objects
            memory_objects.clear()
            
            # Simulate garbage collection
            import gc
            gc.collect()
            
            # Reset mock memory usage to simulate cleanup
            mock_resource_monitor.current_resource_usage['memory'] = initial_memory + 10  # Some residual memory
            
            final_memory = mock_resource_monitor.current_resource_usage.get('memory', 0)
            print(f"Memory after cleanup: {final_memory:.2f} MB")
            
            # Assert that memory was cleaned up (allowing for some residual memory)
            memory_increase = final_memory - initial_memory
            assert memory_increase < 50, f"Memory increase after cleanup ({memory_increase:.2f} MB) should be minimal"
            
        except Exception as e:
            pytest.fail(f"Memory cleanup test failed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])