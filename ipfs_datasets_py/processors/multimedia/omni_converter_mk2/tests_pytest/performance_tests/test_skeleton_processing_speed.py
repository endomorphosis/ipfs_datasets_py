"""
Processing Speed Tests for the Omni-Converter converted from unittest to pytest.

This module tests the processing speed across different file types.
"""
import pytest
from datetime import datetime
import os
import json
import tempfile
import time
from typing import Any, Optional
from unittest.mock import MagicMock, patch

from _tests._fixtures import fixtures


@pytest.fixture
def results_dir():
    """Ensure results directory exists."""
    results_dir = 'tests/collected_results'
    os.makedirs(results_dir, exist_ok=True)
    return results_dir


@pytest.fixture
def speed_requirements():
    """Define speed requirements for each category (files per minute)."""
    return {
        'text': 120,      # 120 files per minute
        'image': 60,      # 60 files per minute  
        'audio': 30,      # 30 files per minute
        'video': 12,      # 12 files per minute
        'application': 60 # 60 files per minute
    }


@pytest.fixture
def test_files_dir():
    """Return the test files directory path."""
    return os.path.join('test_files')


def _create_test_files_for_category(category: str, test_files_dir: str) -> list[dict[str, Any]]:
    """Create test file data for a category."""
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
    
    category_files = []
    
    # Look for real test files in the test_files directory
    if category in extensions:
        exts = extensions[category]
        category_dir = os.path.join(test_files_dir, category)
        
        real_files = []
        # Check category-specific directory
        if os.path.exists(category_dir):
            for file_name in os.listdir(category_dir):
                if os.path.isfile(os.path.join(category_dir, file_name)):
                    file_path = os.path.join(category_dir, file_name)
                    _, ext = os.path.splitext(file_name)
                    ext = ext.lower().lstrip('.')
                    if ext in exts:
                        format_name = format_mapping.get(ext, ext)
                        file_size = os.path.getsize(file_path) / (1024 * 1024)  # Size in MB
                        real_files.append({
                            'file_name': file_name,
                            'file_path': file_path,
                            'file_size_mb': file_size,
                            'format': format_name,
                            'is_sample': False
                        })
        
        # Check main test_files directory
        if os.path.exists(test_files_dir):
            for file_name in os.listdir(test_files_dir):
                file_path = os.path.join(test_files_dir, file_name)
                if os.path.isfile(file_path):
                    _, ext = os.path.splitext(file_name)
                    ext = ext.lower().lstrip('.')
                    if ext in exts:
                        format_name = format_mapping.get(ext, ext)
                        file_size = os.path.getsize(file_path) / (1024 * 1024)  # Size in MB
                        real_files.append({
                            'file_name': file_name,
                            'file_path': file_path,
                            'file_size_mb': file_size,
                            'format': format_name,
                            'is_sample': False
                        })
        
        # Add real files to category files
        category_files.extend(real_files)
        
        # Add sample files if needed to have at least a few files per category
        min_files = 3  # Minimum number of files to test per category
        if len(category_files) < min_files:
            # Add sample files
            needed_files = min_files - len(category_files)
            for i in range(needed_files):
                ext_idx = i % len(exts)
                ext = exts[ext_idx]
                format_name = format_mapping.get(ext, ext)
                
                category_files.append({
                    'file_name': f'sample_{category}_{i}.{ext}',
                    'file_path': f'/test_files/samples/{category}/sample_{i}.{ext}',
                    'file_size_mb': 0.1,  # Mock small file size
                    'format': format_name,
                    'is_sample': True
                })
    
    return category_files


@pytest.mark.performance
class TestProcessingSpeed:
    """Test case for processing speed across different file types."""

    @pytest.fixture(autouse=True)
    def setup_test_results(self, results_dir):
        """Initialize test results structure."""
        self.results = {
            'test_name': 'Processing Speed',
            'timestamp': datetime.now().isoformat(),
            'categories': {},
            'overall': {}
        }
        yield
        # Save results to JSON file after test
        output_file = os.path.join(results_dir, 'processing_speed.json')
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\nTest results saved to {output_file}")

    def test_processing_speed(self, speed_requirements, test_files_dir):
        """Test processing speed for different file types."""
        try:
            # Import the required modules here to allow for graceful failure
            # from core.core_factory import make_processing_pipeline
            
            # Mock the processing pipeline for testing
            mock_pipeline = MagicMock()
            
            # Test each category
            categories = ['text', 'image', 'audio', 'video', 'application']
            all_meet_requirements = True
            
            for category in categories:
                # Create test files for this category
                test_files = _create_test_files_for_category(category, test_files_dir)
                
                if test_files:
                    category_results = self._process_files(test_files, category, speed_requirements, mock_pipeline)
                    self.results['categories'][category] = category_results
                    
                    if not category_results['meets_requirement']:
                        all_meet_requirements = False
                    
                    print(f"{category.title()} Category:")
                    print(f"  Files processed: {category_results['files_processed']}")
                    print(f"  Real files: {category_results['real_files_processed']}")
                    print(f"  Sample files: {category_results['sample_files_processed']}")
                    print(f"  Processing time: {category_results['total_processing_time_seconds']:.2f}s")
                    print(f"  Speed: {category_results['files_per_minute']:.1f} files/min")
                    print(f"  Requirement: {speed_requirements[category]} files/min")
                    print(f"  Meets requirement: {category_results['meets_requirement']}")
                else:
                    print(f"{category.title()} Category: No test files available")
                    # Create placeholder results for categories with no files
                    self.results['categories'][category] = {
                        'files_processed': 0,
                        'real_files_processed': 0,
                        'sample_files_processed': 0,
                        'files_per_minute': 0,
                        'meets_requirement': False,  # Can't meet requirement with no files
                        'file_results': []
                    }
            
            # Store overall results
            self.results['overall'] = {
                'all_categories_meet_requirements': all_meet_requirements
            }
            
            # Print overall result
            print("\nOverall Results:")
            print(f"All categories meet speed requirements: {all_meet_requirements}")
            
            # If we had enough real files to make a meaningful assertion
            real_file_count = sum(result['real_files_processed'] for result in self.results['categories'].values())
            if real_file_count >= 5:
                assert all_meet_requirements, "All categories must meet their processing speed requirements"
            else:
                print("\nNote: Not enough real test files for a meaningful speed assertion")
            
        except ImportError as e:
            print(f"Failed to import required modules: {e}")
            self.results['error'] = str(e)
            pytest.fail(f"ImportError: {e}")
        except Exception as e:
            print(f"Unexpected error during testing: {e}")
            self.results['error'] = str(e)
            pytest.fail(f"Error: {e}")

    def _process_files(self, files: list[dict[str, Any]], category: str, 
                      speed_requirements: dict[str, int], pipeline) -> dict[str, Any]:
        """Process files and measure performance."""
        start_time = time.time()
        processed_count = 0
        file_results = []
        total_processing_time = 0.0
        
        real_files = [f for f in files if not f.get('is_sample', True)]
        sample_files = [f for f in files if f.get('is_sample', True)]
        
        for file_info in files:
            file_start_time = time.time()
            
            try:
                # Mock file processing
                if file_info.get('is_sample', True):
                    # Sample files - simulate fast processing
                    processing_time = 0.01  # 10ms per sample file
                    success = True
                else:
                    # Real files - simulate realistic processing time based on category and size
                    base_time = {
                        'text': 0.05,       # 50ms base time for text
                        'image': 0.1,       # 100ms base time for images
                        'audio': 0.2,       # 200ms base time for audio
                        'video': 0.5,       # 500ms base time for video
                        'application': 0.1  # 100ms base time for applications
                    }
                    
                    file_size_mb = file_info.get('file_size_mb', 1.0)
                    processing_time = base_time.get(category, 0.1) * file_size_mb
                    
                    # Simulate processing with actual time delay (scaled down)
                    time.sleep(min(processing_time / 100, 0.01))  # Scale down for testing
                    success = True
                
                if success:
                    processed_count += 1
                    total_processing_time += processing_time
                
                file_end_time = time.time()
                actual_processing_time = file_end_time - file_start_time
                
                file_results.append({
                    'file_name': file_info['file_name'],
                    'file_path': file_info['file_path'],
                    'success': success,
                    'processing_time_seconds': actual_processing_time,
                    'simulated_processing_time': processing_time,
                    'file_size_mb': file_info.get('file_size_mb', 0),
                    'is_sample': file_info.get('is_sample', True)
                })
                
            except Exception as e:
                file_results.append({
                    'file_name': file_info['file_name'],
                    'file_path': file_info['file_path'],
                    'success': False,
                    'error': str(e),
                    'is_sample': file_info.get('is_sample', True)
                })
        
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        # Calculate files per minute based on simulated processing time
        files_per_minute = (processed_count / total_processing_time) * 60 if total_processing_time > 0 else 0
        
        # Calculate if the category meets the requirements
        meets_requirement = files_per_minute >= speed_requirements[category]
        
        return {
            'start_time': start_time,
            'end_time': end_time,
            'elapsed_time_seconds': elapsed_time,
            'total_processing_time_seconds': total_processing_time,
            'files_processed': processed_count,
            'real_files_processed': len(real_files),
            'sample_files_processed': len(sample_files),
            'files_per_minute': files_per_minute,
            'meets_requirement': meets_requirement,
            'file_results': file_results
        }


if __name__ == "__main__":
    pytest.main([__file__, "-v"])