#!/usr/bin/env python3
"""
Resource Utilization Tests for the Omni-Converter.

This module tests the memory and CPU usage of the application during processing.
"""
from datetime import datetime
import json
import multiprocessing
import os
import platform
import tempfile
import time
from typing import Any
import unittest


# Import psutil for actual resource monitoring
try:
    import psutil
except ImportError:
    raise ImportError("psutil is required for this module. Please install it with 'pip install psutil'.")


from configs import configs
from _tests._fixtures import fixtures


class ResourceUtilizationTest(unittest.TestCase):
    """Test case for resource utilization during file processing."""

    def setUp(self):
        """Set up test case with necessary data structures."""
        # Define the test batches with different file types and sizes
        self.test_batches = self._create_test_batches()
        
        # Get resource limits from config
        self.memory_limit_gb = configs.get_config_value('resources.memory_limit_gb', 6)
        self.cpu_limit_percent = configs.get_config_value('resources.cpu_limit_percent', 80)
        
        # Create the results directory if it doesn't exist
        os.makedirs('tests/collected_results', exist_ok=True)
        
        # Create temp directory for output
        self.temp_output_dir = tempfile.mkdtemp()
        
        # Set up resource monitor
        self.resource_monitor = fixtures['resource_monitor']
        
        # Results will be stored here
        self.results = {
            'test_name': 'Resource Utilization',
            'timestamp': datetime.now().isoformat(),
            'system_info': self._get_system_info(),
            'batches': {},
            'overall': {
                'peak_memory_usage_gb': 0,
                'peak_cpu_percent': 0,
                'within_memory_limit': False,
                'within_cpu_limit': False
            }
        }

    def _get_system_info(self) -> dict[str, Any]:
        """Get system information for context.
        
        Returns:
            Dictionary containing system information
        """
        system_info = {
            'platform': platform.platform(),
            'python_version': platform.python_version(),
            'processor': platform.processor(),
            'cpu_count': multiprocessing.cpu_count(),
            'architecture': platform.architecture(),
            'memory_gb': round(psutil.virtual_memory().total / (1024**3), 2)
        }
        return system_info

    def _create_test_batches(self) -> list[dict[str, Any]]:
        """Create test batch data.
        
        Returns:
            List of dictionaries representing test batches
        """
        # Define test files directory
        test_files_dir = os.path.join('test_files')
        
        # Create different batches representing different workloads
        batches = []
        
        # Small Text Batch
        text_files = self._find_files_of_category(test_files_dir, 'text', ['html', 'xml', 'txt', 'csv', 'ics'])
        if text_files:
            batches.append({
                'name': 'Small Text Batch',
                'description': f'{len(text_files)} text files',
                'files': text_files,
                'expected_memory_gb': 0.2,
                'expected_cpu_percent': 20
            })
        
        # Mixed Media Batch
        image_files = self._find_files_of_category(test_files_dir, 'image', ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'])
        audio_files = self._find_files_of_category(test_files_dir, 'audio', ['mp3', 'wav', 'ogg', 'flac', 'aac'])
        video_files = self._find_files_of_category(test_files_dir, 'video', ['mp4', 'webm', 'avi', 'mkv', 'mov'])
        
        mixed_files = image_files + audio_files + video_files
        if mixed_files:
            batches.append({
                'name': 'Mixed Media Batch',
                'description': f'{len(image_files)} images, {len(audio_files)} audio files, {len(video_files)} videos',
                'files': mixed_files,
                'expected_memory_gb': 1.5,
                'expected_cpu_percent': 60
            })
        
        # Application Batch
        app_files = self._find_files_of_category(test_files_dir, 'application', ['pdf', 'json', 'zip', 'docx', 'xlsx'])
        if app_files:
            batches.append({
                'name': 'Application Files Batch',
                'description': f'{len(app_files)} application files',
                'files': app_files,
                'expected_memory_gb': 1.0,
                'expected_cpu_percent': 40
            })
        
        # If we don't have any real test files, create a synthetic batch for testing
        if not batches:
            batches.append({
                'name': 'Synthetic Test Batch',
                'description': 'Synthetic batch for testing resource monitoring',
                'files': [{'category': 'text', 'size_kb': 1, 'synthetic': True} for _ in range(10)],
                'expected_memory_gb': 0.1,
                'expected_cpu_percent': 10
            })
        
        return batches

    def _find_files_of_category(self, test_files_dir: str, category: str, extensions: list[str]) -> list[dict[str, Any]]:
        """Find test files of a specific category.
        
        Args:
            test_files_dir: Path to test files directory
            category: File category (text, image, etc.)
            extensions: list of file extensions to look for
            
        Returns:
            List of dictionaries with file information
        """
        files = []
        
        # Check if category directory exists
        category_dir = os.path.join(test_files_dir, category)
        if os.path.exists(category_dir) and os.path.isdir(category_dir):
            # Look for files in the category directory
            for file_name in os.listdir(category_dir):
                file_path = os.path.join(category_dir, file_name)
                if os.path.isfile(file_path):
                    # Check if the file has one of the specified extensions
                    _, ext = os.path.splitext(file_name)
                    if ext.lower().lstrip('.') in extensions:
                        # Get file size in KB
                        size_kb = os.path.getsize(file_path) / 1024
                        
                        files.append({
                            'file_name': file_name,
                            'file_path': file_path,
                            'category': category,
                            'size_kb': size_kb,
                            'synthetic': False
                        })
        
        # Also check the main test_files directory
        if os.path.exists(test_files_dir) and os.path.isdir(test_files_dir):
            for file_name in os.listdir(test_files_dir):
                file_path = os.path.join(test_files_dir, file_name)
                if os.path.isfile(file_path):
                    # Check if the file has one of the specified extensions
                    _, ext = os.path.splitext(file_name)
                    if ext.lower().lstrip('.') in extensions:
                        # Get file size in KB
                        size_kb = os.path.getsize(file_path) / 1024
                        
                        files.append({
                            'file_name': file_name,
                            'file_path': file_path,
                            'category': category,
                            'size_kb': size_kb,
                            'synthetic': False
                        })
        
        return files

    def test_resource_utilization(self):
        """Test resource utilization during file processing."""
        try:
            batch_processor = fixtures['batch_processor']

            # Start resource monitoring
            self.resource_monitor.start_monitoring()
            
            # Track overall peak values
            overall_peak_memory_gb = 0
            overall_peak_cpu_percent = 0
            
            # Process each batch
            for i, batch in enumerate(self.test_batches):
                print(f"\nBatch {i+1}: {batch['name']}")
                print(f"Description: {batch['description']}")
                print(f"Files: {len(batch['files'])} files")
                
                # Skip empty batches
                if not batch['files']:
                    print("Skipping empty batch")
                    continue
                
                # Reset the resource monitor's statistics
                initial_usage = self.resource_monitor.current_resource_usage
                
                # If we have real files, process them with the batch processor
                if not batch.get('synthetic', False) and not batch['files'][0].get('synthetic', False):
                    real_files = [f['file_path'] for f in batch['files']]
                    
                    # Process the batch
                    print(f"Processing {len(real_files)} files...")
                    
                    # Process the batch using the batch processor
                    batch_processor.process_batch(
                        real_files,
                        self.temp_output_dir,
                        {'format': 'txt'},
                        progress_callback=lambda current, total, file: print(f"Processing {current}/{total}: {os.path.basename(file)}", end="\r")
                    )
                else:
                    # For synthetic batches, simulate processing by using memory and CPU
                    print("Simulating batch processing...")
                    self._simulate_batch_processing(batch)
                
                # Get resource usage after processing
                current_resource_usage = self.resource_monitor.current_resource_usage
                peak_memory_gb = current_resource_usage.get('memory', 0) / 1024  # Convert MB to GB
                peak_cpu_percent = current_resource_usage.get('cpu', 0)
                
                # For more accurate memory measurement, also check process directly
                try:
                    process = psutil.Process(os.getpid())
                    memory_info = process.memory_info()
                    process_memory_gb = memory_info.rss / (1024 ** 3)
                    if process_memory_gb > peak_memory_gb:
                        peak_memory_gb = process_memory_gb
                except Exception as e:
                    print(f"Warning: Could not get process memory: {e}")
                
                # Check if usage is within limits
                within_memory_limit = peak_memory_gb < self.memory_limit_gb
                within_cpu_limit = peak_cpu_percent < self.cpu_limit_percent
                
                # Update overall peaks
                overall_peak_memory_gb = max(overall_peak_memory_gb, peak_memory_gb)
                overall_peak_cpu_percent = max(overall_peak_cpu_percent, peak_cpu_percent)
                
                # Store batch results
                self.results['batches'][batch['name']] = {
                    'description': batch['description'],
                    'file_count': len(batch['files']),
                    'peak_memory_usage_gb': peak_memory_gb,
                    'peak_cpu_percent': peak_cpu_percent,
                    'within_memory_limit': within_memory_limit,
                    'within_cpu_limit': within_cpu_limit,
                    'memory_limit_gb': self.memory_limit_gb,
                    'cpu_limit_percent': self.cpu_limit_percent
                }
                
                # Print batch results to console
                print(f"Peak memory usage: {peak_memory_gb:.2f} GB (Limit: {self.memory_limit_gb} GB)")
                print(f"Peak CPU usage: {peak_cpu_percent:.2f}% (Limit: {self.cpu_limit_percent}%)")
                print(f"Within memory limit: {within_memory_limit}")
                print(f"Within CPU limit: {within_cpu_limit}")
                
                # Force garbage collection to clean up between batches
                try:
                    import gc
                    gc.collect()
                except ImportError:
                    pass
            
            # Stop resource monitoring
            self.resource_monitor.stop_monitoring()
            
            # Store overall results
            overall_within_memory_limit = overall_peak_memory_gb < self.memory_limit_gb
            overall_within_cpu_limit = overall_peak_cpu_percent < self.cpu_limit_percent
            
            self.results['overall'] = {
                'peak_memory_usage_gb': overall_peak_memory_gb,
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
            self.assertLess(overall_peak_memory_gb, self.memory_limit_gb, 
                          f"Memory usage ({overall_peak_memory_gb:.2f} GB) exceeds limit ({self.memory_limit_gb} GB)")
            self.assertLess(overall_peak_cpu_percent, self.cpu_limit_percent, 
                          f"CPU usage ({overall_peak_cpu_percent:.2f}%) exceeds limit ({self.cpu_limit_percent}%)")
            
        except ImportError as e:
            print(f"Failed to import required modules: {e}")
            self.results['error'] = str(e)
            self.fail(f"ImportError: {e}")
        except Exception as e:
            print(f"Unexpected error during testing: {e}")
            self.results['error'] = str(e)
            self.fail(f"Error: {e}")
        finally:
            # Make sure to stop monitoring
            self.resource_monitor.stop_monitoring()

    def _simulate_batch_processing(self, batch: dict[str, Any]) -> None:
        """
        Simulate batch processing to test resource monitoring.
        
        Args:
            batch: Batch information
        """
        # Simulate processing by allocating memory and using CPU
        total_files = len(batch['files'])
        
        print(f"Simulating processing of {total_files} files...")
        
        # Create some objects to use memory
        memory_objects = []
        
        # Process each simulated file
        for i, file_info in enumerate(batch['files']):
            print(f"Simulating file {i+1}/{total_files}: {file_info.get('file_name', f'synthetic_{i}')}")
            
            # Simulate memory usage
            size_kb = file_info.get('size_kb', 1)
            # Allocate a small fraction of the "file size" to memory to avoid OOM
            memory_chunk = bytearray(int(size_kb * 10))  # Scaled down for safety
            memory_objects.append(memory_chunk)
            
            # Simulate CPU usage
            start_time = time.time()
            while time.time() - start_time < 0.1:  # Short CPU burst
                # Do something CPU-intensive
                for _ in range(10000):
                    _ = 3.1415 ** 2.7182
            
            # Check current usage
            current_resource_usage = self.resource_monitor.current_resource_usage
            memory_mb = current_resource_usage.get('memory', 0)
            cpu_percent = current_resource_usage.get('cpu', 0)
            
            print(f"Current usage - Memory: {memory_mb:.2f} MB, CPU: {cpu_percent:.2f}%")
            
            # Sleep briefly to allow resource monitor to take measurements
            time.sleep(0.05)
        
        # Hold the allocated memory briefly
        time.sleep(0.5)
        
        # Clear memory objects to release memory
        memory_objects.clear()

    def tearDown(self):
        """Save test results to a JSON file and clean up."""
        # Save results to JSON file
        output_file = os.path.join('tests', 'collected_results', 'resource_utilization.json')
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\nTest results saved to {output_file}")
        
        # Clean up temporary directory
        if self.temp_output_dir and os.path.exists(self.temp_output_dir):
            import shutil
            try:
                shutil.rmtree(self.temp_output_dir)
            except Exception as e:
                print(f"Warning: Failed to remove temporary directory: {e}")


if __name__ == '__main__':
    unittest.main()