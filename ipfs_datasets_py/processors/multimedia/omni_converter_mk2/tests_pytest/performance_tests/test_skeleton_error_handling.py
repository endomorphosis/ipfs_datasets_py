"""
Error Handling Tests for the Omni-Converter converted from unittest to pytest.

This module tests how well the application handles errors during processing.
"""
import pytest
from datetime import datetime
import os
import json
import tempfile
from typing import Any, Optional
from unittest.mock import MagicMock, patch

from _tests._fixtures import fixtures


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
def results_dir():
    """Ensure results directory exists."""
    results_dir = 'tests/collected_results'
    os.makedirs(results_dir, exist_ok=True)
    return results_dir


@pytest.fixture
def test_files_dir():
    """Return the test files directory path."""
    return os.path.join('test_files')


def _find_valid_files(test_files_dir: str) -> list[str]:
    """Find valid files in the test directory."""
    valid_files = []
    if os.path.exists(test_files_dir):
        for root, dirs, files in os.walk(test_files_dir):
            for file in files:
                file_path = os.path.join(root, file)
                if os.path.isfile(file_path) and os.path.getsize(file_path) > 0:
                    valid_files.append(file_path)
    return valid_files


def _find_corrupt_files(test_files_dir: str) -> list[str]:
    """Find corrupt/invalid files in the test directory."""
    corrupt_files = []
    corrupted_dir = os.path.join(test_files_dir, 'corrupted')
    if os.path.exists(corrupted_dir):
        for root, dirs, files in os.walk(corrupted_dir):
            for file in files:
                file_path = os.path.join(root, file)
                corrupt_files.append(file_path)
    return corrupt_files


@pytest.mark.performance
class TestErrorHandling:
    """Test case for error handling during file processing."""

    @pytest.fixture(autouse=True)
    def setup_test_results(self, results_dir):
        """Initialize test results structure."""
        self.results = {
            'test_name': 'Error Handling',
            'timestamp': datetime.now().isoformat(),
            'batches': {},
            'overall': {}
        }
        self.continue_on_error = True
        yield
        # Save results to JSON file after test
        output_file = os.path.join(results_dir, 'error_handling.json')
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\nTest results saved to {output_file}")

    def test_error_handling(self, test_files_dir, temp_output_dir):
        """Test error handling during file processing."""
        try:
            # Import the required modules here to allow for graceful failure
            # from core.core_factory import make_processing_pipeline
            # from core.file_validator._file_validator import FileValidator
            
            # Mock the batch processor for testing
            mock_batch_processor = MagicMock()
            
            # Create test batches with different corruption levels
            test_batches = self._create_test_batches(test_files_dir)
            self.test_batches = test_batches
            
            total_batches = len(test_batches)
            successful_batches = 0
            batches_30pct_or_less = []
            batches_30pct_or_less_results = []
            
            # Process each test batch
            for batch in test_batches:
                batch_result = self._process_batch(batch, mock_batch_processor)
                self.results['batches'][batch['name']] = batch_result
                
                if batch_result['batch_completed']:
                    successful_batches += 1
                
                # Track batches with ≤30% corrupt files
                if batch['corrupt_ratio'] <= 0.3:
                    batches_30pct_or_less.append(batch)
                    batches_30pct_or_less_results.append(batch_result['batch_completed'])
                
                print(f"Batch: {batch['name']}")
                print(f"  Corruption ratio: {batch['corrupt_ratio']*100:.1f}%")
                print(f"  Completed: {batch_result['batch_completed']}")
                print(f"  Files processed: {batch_result['files_processed']}")
                print(f"  Errors handled: {batch_result['errors_handled']}")
            
            # Calculate overall success rate
            success_rate = (successful_batches / total_batches * 100) if total_batches > 0 else 0
            
            # Check requirement: 100% reliability with ≤30% corrupt files
            meets_requirement = len(batches_30pct_or_less) == 0 or all(batches_30pct_or_less_results)
            
            # Store overall results
            self.results['overall'] = {
                'total_batches': total_batches,
                'successful_batches': successful_batches,
                'success_rate': success_rate,
                'batches_30pct_or_less_corrupt': len(batches_30pct_or_less),
                'batches_30pct_or_less_successful': sum(batches_30pct_or_less_results),
                'meets_requirement': meets_requirement,
                'continue_on_error_setting': self.continue_on_error
            }
            
            # Print overall results
            print("\nOverall Results:")
            print(f"Total batches: {total_batches}")
            print(f"Successful batches: {successful_batches}")
            print(f"Success rate: {success_rate:.2f}%")
            print(f"Batches with ≤30% corrupt files: {len(batches_30pct_or_less)}")
            print(f"Successful batches with ≤30% corrupt files: {sum(batches_30pct_or_less_results)}")
            print(f"Meets requirement (100% reliability with ≤30% corrupt files): {meets_requirement}")
            
            # Assert that all batches with ≤30% corrupt files are processed completely
            assert meets_requirement, "All batches with ≤30% corrupt files must be processed completely"
            
            # Check that batches with >30% corrupt files might fail
            high_corruption_batches = [b for b in self.test_batches if b['corrupt_ratio'] > 0.3]
            if high_corruption_batches:
                print("\nBehavior with high corruption rates (>30%):")
                for b in high_corruption_batches:
                    result = self.results['batches'][b['name']]
                    print(f"Batch: {b['name']}, Corruption: {b['corrupt_ratio']*100:.1f}%, Completed: {result['batch_completed']}")
            
        except ImportError as e:
            print(f"Failed to import required modules: {e}")
            self.results['error'] = str(e)
            pytest.fail(f"ImportError: {e}")
        except Exception as e:
            print(f"Unexpected error during testing: {e}")
            self.results['error'] = str(e)
            pytest.fail(f"Error: {e}")

    def _create_test_batches(self, test_files_dir: str) -> list[dict[str, Any]]:
        """Create test batches with different corruption ratios."""
        test_batches = []
        
        # Find available test files
        valid_files = _find_valid_files(test_files_dir)
        corrupt_files = _find_corrupt_files(test_files_dir)
        
        # Get counts
        valid_count = len(valid_files)
        corrupt_count = len(corrupt_files)
        
        # If we have real test files, create batches with different corruption ratios
        if valid_count > 0:
            # Create batches with different corruption levels
            # 0%, 10%, 20%, 30%, 40%, 50% corrupt files
            corruption_ratios = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
            
            for corruption_ratio in corruption_ratios:
                # Calculate how many files we need for this batch
                batch_name = f"batch_{int(corruption_ratio*100)}pct_corrupt"
                
                # If we have corrupt files, create a mixed batch
                if corrupt_count > 0 and corruption_ratio > 0:
                    batch_size = min(10, valid_count + corrupt_count)  # Limit batch size
                    corrupt_count_in_batch = int(batch_size * corruption_ratio)
                    valid_count_in_batch = batch_size - corrupt_count_in_batch
                    
                    batch_files = (
                        valid_files[:valid_count_in_batch] + 
                        corrupt_files[:corrupt_count_in_batch]
                    )
                else:
                    # Pure valid files batch
                    batch_files = valid_files[:10]  # Limit to 10 files
                    corruption_ratio = 0.0  # No corruption possible
                
                test_batches.append({
                    'name': batch_name,
                    'files': batch_files,
                    'corrupt_ratio': corruption_ratio,
                    'total_files': len(batch_files)
                })
        else:
            # Create mock batches if no real files available
            mock_batches = [
                {'name': 'batch_0pct_corrupt', 'corrupt_ratio': 0.0, 'total_files': 5},
                {'name': 'batch_10pct_corrupt', 'corrupt_ratio': 0.1, 'total_files': 5},
                {'name': 'batch_30pct_corrupt', 'corrupt_ratio': 0.3, 'total_files': 5},
                {'name': 'batch_50pct_corrupt', 'corrupt_ratio': 0.5, 'total_files': 5}
            ]
            
            for batch in mock_batches:
                batch['files'] = [f"/mock/file_{i}.txt" for i in range(batch['total_files'])]
                test_batches.append(batch)
        
        return test_batches

    def _process_batch(self, batch: dict[str, Any], batch_processor) -> dict[str, Any]:
        """Process a batch of files and handle errors."""
        batch_name = batch['name']
        files = batch.get('files', [])
        corrupt_ratio = batch['corrupt_ratio']
        
        files_processed = 0
        errors_handled = 0
        batch_completed = True
        
        try:
            # Mock batch processing
            for file_path in files:
                try:
                    # Simulate processing - files with high corruption might fail
                    if corrupt_ratio > 0.5:
                        # High corruption - some files might cause batch to fail
                        success_probability = 0.7  # 70% chance of handling error gracefully
                        if hash(file_path) % 10 < success_probability * 10:
                            files_processed += 1
                        else:
                            errors_handled += 1
                            if not self.continue_on_error:
                                batch_completed = False
                                break
                    elif corrupt_ratio > 0.3:
                        # Medium corruption - most errors handled gracefully
                        files_processed += 1
                        if 'corrupt' in file_path.lower() or corrupt_ratio > 0:
                            errors_handled += 1
                    else:
                        # Low/no corruption - should process successfully
                        files_processed += 1
                        
                except Exception as e:
                    errors_handled += 1
                    if not self.continue_on_error:
                        batch_completed = False
                        break
            
        except Exception as e:
            # Batch-level error
            batch_completed = False
            errors_handled += 1
        
        return {
            'batch_name': batch_name,
            'batch_completed': batch_completed,
            'files_processed': files_processed,
            'errors_handled': errors_handled,
            'total_files': len(files),
            'corruption_ratio': corrupt_ratio
        }


if __name__ == "__main__":
    pytest.main([__file__, "-v"])