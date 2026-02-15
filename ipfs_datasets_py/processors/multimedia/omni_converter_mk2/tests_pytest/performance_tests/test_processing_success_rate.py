#!/usr/bin/env python3
"""
Pytest migration of test_skeleton_processing_success_rate.py

Processing Success Rate Tests for the Omni-Converter.
This module tests the rate of successful processing across different file types.
Converted from unittest to pytest format while preserving all test logic.
"""
from datetime import datetime
import os
import json
import tempfile
from typing import Any, Optional
import pytest

from _tests._fixtures import fixtures


@pytest.mark.performance
class TestProcessingSuccessRate:
    """Test case for processing success rate across different file types."""

    def setup_method(self):
        """Set up test case with necessary data structures."""

        # Define test files directory
        self.test_files_dir = os.path.join('test_files')
        
        # Create temp directory for output
        self.temp_output_dir = tempfile.mkdtemp()

        # Define the test datasets for each category
        self.test_datasets = {
            'text': self._create_test_files('text', 10),
            'image': self._create_test_files('image', 10),
            'audio': self._create_test_files('audio', 10),
            'video': self._create_test_files('video', 5),
            'application': self._create_test_files('application', 10)
        }
        
        # Include some invalid files to test error handling
        self.invalid_files = self._create_invalid_files(5)
        
        # Create the results directory if it doesn't exist
        os.makedirs('tests/collected_results', exist_ok=True)
        
        # Results will be stored here
        self.results = {
            'test_name': 'Processing Success Rate',
            'timestamp': datetime.now().isoformat(),
            'categories': {},
            'overall': {
                'total_valid_files': 0,
                'successfully_processed': 0,
                'success_rate': 0
            }
        }

    def teardown_method(self):
        """Save test results to a JSON file and clean up."""
        # Save results to JSON file
        output_file = os.path.join('tests', 'collected_results', 'processing_success_rate.json')
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\nTest results saved to {output_file}")
        
        # Clean up temporary output directory if it exists
        if os.path.exists(self.temp_output_dir):
            import shutil
            try:
                shutil.rmtree(self.temp_output_dir)
            except Exception as e:
                print(f"Warning: Failed to remove temporary directory: {e}")

    def _create_test_files(self, category: str, count: int) -> list[dict[str, Any]]:
        """Create test file data for a category.
        
        This method looks for real test files in test_files directory if available,
        otherwise creates test file entries that point to sample files.
        
        Args:
            category: The file category (text, image, etc.)
            count: Number of test files to create
            
        Returns:
            List of dictionaries representing test files
        """
        extensions = {
            'text': ['html', 'xml', 'txt', 'csv', 'ics'],
            'image': ['jpg', 'png', 'gif', 'webp', 'svg'],
            'audio': ['mp3', 'wav', 'ogg', 'flac', 'aac'],
            'video': ['mp4', 'webm', 'avi', 'mkv', 'mov'],
            'application': ['pdf', 'json', 'zip', 'docx', 'xlsx']
        }
        
        format_mapping = {
            'txt': 'plain',
            'ics': 'calendar',
            'jpg': 'jpeg'
        }
        
        exts = extensions[category]
        files = []
        
        # First, try to find real test files
        real_files = []
        category_dir = os.path.join(self.test_files_dir, category)
        
        # Check category subdirectory
        if os.path.exists(category_dir) and os.path.isdir(category_dir):
            for file_name in os.listdir(category_dir):
                file_path = os.path.join(category_dir, file_name)
                if os.path.isfile(file_path):
                    _, ext = os.path.splitext(file_name)
                    ext = ext.lower().lstrip('.')
                    if ext in exts:
                        format_name = format_mapping.get(ext, ext)
                        file_size = os.path.getsize(file_path) / (1024 * 1024)  # Size in MB
                        real_files.append({
                            'file_name': file_name,
                            'file_path': file_path,
                            'format': format_name,
                            'category': category,
                            'file_size_mb': file_size,
                            'is_valid': True,
                            'expect_success': True,
                            'is_sample': False
                        })
        
        # Also check main test files directory for any matching files
        if os.path.exists(self.test_files_dir) and os.path.isdir(self.test_files_dir):
            for file_name in os.listdir(self.test_files_dir):
                file_path = os.path.join(self.test_files_dir, file_name)
                if os.path.isfile(file_path):
                    _, ext = os.path.splitext(file_name)
                    ext = ext.lower().lstrip('.')
                    if ext in exts:
                        format_name = format_mapping.get(ext, ext)
                        file_size = os.path.getsize(file_path) / (1024 * 1024)  # Size in MB
                        real_files.append({
                            'file_name': file_name,
                            'file_path': file_path,
                            'format': format_name,
                            'category': category,
                            'file_size_mb': file_size,
                            'is_valid': True,
                            'expect_success': True,
                            'is_sample': False
                        })
        
        # Add real files to our test set
        files.extend(real_files)
        
        # Create sample files to reach the desired count
        for i in range(len(files), count):
            ext = exts[i % len(exts)]
            format_name = format_mapping.get(ext, ext)
            
            files.append({
                'file_name': f"sample_{category}_{i+1}.{ext}",
                'file_path': f"/sample/path/sample_{category}_{i+1}.{ext}",
                'format': format_name,
                'category': category,
                'file_size_mb': 1.0,
                'is_valid': True,
                'expect_success': True,
                'is_sample': True
            })
        
        return files

    def _create_invalid_files(self, count: int) -> list[dict[str, Any]]:
        """Create invalid/corrupted test file entries for error handling tests.
        
        Args:
            count: Number of invalid files to create
            
        Returns:
            List of invalid file dictionaries
        """
        corrupt_types = [
            'truncated',        # File is cut off mid-stream
            'invalid_header',   # File header is corrupted
            'wrong_extension',  # Extension doesn't match content
            'empty_file',       # Zero-byte file
            'binary_garbage'    # Random binary data
        ]
        
        invalid_files = []
        
        for i in range(count):
            corrupt_type = corrupt_types[i % len(corrupt_types)]
            
            # Try to find a real corrupted file or create a sample one
            file_path = f"/sample/path/corrupted_file_{i+1}.txt"
            is_sample = True
            
            # In a real implementation, we would have actual corrupted test files
            # For now, we simulate them
            invalid_files.append({
                'file_name': os.path.basename(file_path),
                'file_path': file_path,
                'format': 'unknown',
                'category': 'invalid',
                'is_valid': False,
                'is_corrupted': True,
                'corrupt_type': corrupt_type,
                'expect_success': False,
                'is_sample': is_sample
            })
        
        return invalid_files

    @pytest.mark.slow
    def test_processing_success_rate(self):
        """Test the success rate of processing valid files."""
        try:
            processing_pipeline = fixtures["processing_pipeline"]

            # Track overall statistics
            total_valid_files = 0
            successfully_processed = 0
            
            # Process files by category
            for category, files in self.test_datasets.items():
                # Count only real files that can be processed
                real_files = [f for f in files if not f['is_sample'] and os.path.exists(f['file_path'])]
                category_valid_files = len(real_files)
                category_successful = 0
                category_results = []
                
                print(f"\nProcessing {category} files:")
                
                # Process each real file in the category
                for file_data in real_files:
                    try:
                        # Process the file using the actual processing pipeline
                        output_path = os.path.join(
                            self.temp_output_dir, 
                            f"{os.path.splitext(file_data['file_name'])[0]}.txt"
                        )
                        
                        # Process using the actual pipeline
                        result = processing_pipeline.process_file(
                            file_data['file_path'], 
                            output_path,
                            {'format': 'txt'}
                        )
                        
                        # Evaluate success based on result
                        success = result.success
                        
                        if success:
                            category_successful += 1
                            print(f"  ✓ {file_data['file_name']}")
                        else:
                            print(f"  ✗ {file_data['file_name']} - {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}")
                        
                        category_results.append({
                            'file_name': file_data['file_name'],
                            'format': file_data['format'],
                            'success': success,
                            'is_sample': False,
                            'file_size_mb': file_data.get('file_size_mb', 0)
                        })
                        
                    except Exception as e:
                        print(f"  ✗ {file_data['file_name']} - Exception: {e}")
                        category_results.append({
                            'file_name': file_data['file_name'],
                            'format': file_data['format'],
                            'success': False,
                            'is_sample': False,
                            'error': str(e),
                            'file_size_mb': file_data.get('file_size_mb', 0)
                        })
                
                # For sample files, simulate processing with high success rate
                sample_files = [f for f in files if f['is_sample']]
                for file_data in sample_files:
                    # Simulate 90% success rate for sample files
                    import random
                    success = random.random() < 0.9
                    
                    if success:
                        category_successful += 1
                        
                    category_results.append({
                        'file_name': file_data['file_name'],
                        'format': file_data['format'],
                        'success': success,
                        'is_sample': True,
                        'simulated': True,
                        'file_size_mb': file_data.get('file_size_mb', 1.0)
                    })
                
                # Calculate category statistics
                category_total_files = len(files)
                category_success_rate = (category_successful / category_total_files) * 100 if category_total_files > 0 else 0
                
                # Store category results
                self.results['categories'][category] = {
                    'total_files': category_total_files,
                    'real_files': len(real_files),
                    'sample_files': len(sample_files),
                    'successful_files': category_successful,
                    'success_rate': category_success_rate,
                    'meets_requirement': category_success_rate >= 95,
                    'file_results': category_results
                }
                
                print(f"{category} results: {category_successful}/{category_total_files} ({category_success_rate:.1f}% success rate)")
                
                # Update overall statistics
                total_valid_files += category_total_files
                successfully_processed += category_successful
            
            # Calculate overall success rate
            overall_success_rate = (successfully_processed / total_valid_files) * 100 if total_valid_files > 0 else 0
            meets_overall_requirement = overall_success_rate >= 95
            
            # Store overall results
            self.results['overall'] = {
                'total_valid_files': total_valid_files,
                'successfully_processed': successfully_processed,
                'success_rate': overall_success_rate,
                'meets_requirement': meets_overall_requirement,
                'real_files_count': sum(len([f for f in files if not f['is_sample']]) 
                                      for files in self.test_datasets.values()),
                'sample_files_count': sum(len([f for f in files if f['is_sample']]) 
                                          for files in self.test_datasets.values())
            }
            
            # Print overall results to console
            print("\nOverall Results:")
            print(f"Total valid files: {total_valid_files}")
            print(f"Successfully processed: {successfully_processed}")
            print(f"Overall success rate: {overall_success_rate:.2f}%")
            print(f"Meets requirement (≥95% success rate): {meets_overall_requirement}")
            
            # Assert that success rate is at least 95%
            # If there are enough real files to make a meaningful assertion
            if total_valid_files >= 5:  # TODO Should be 30 when we have enough test files.
                assert overall_success_rate >= 95, "Overall processing success rate must be at least 95%"
            else:
                print("\nNote: Not enough real test files to make a meaningful assertion on success rate")
            
        except ImportError as e:
            print(f"Failed to import required modules: {e}")
            self.results['error'] = str(e)
            pytest.fail(f"ImportError: {e}")
        except Exception as e:
            print(f"Unexpected error during testing: {e}")
            self.results['error'] = str(e)
            pytest.fail(f"Error: {e}")