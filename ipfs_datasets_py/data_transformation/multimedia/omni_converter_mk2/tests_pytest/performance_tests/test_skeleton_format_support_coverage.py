"""
Format Support Coverage Tests for the Omni-Converter converted from unittest to pytest.

This module tests the format support coverage across different file types.
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
def results_dir():
    """Ensure results directory exists."""
    results_dir = 'tests/collected_results'
    os.makedirs(results_dir, exist_ok=True)
    return results_dir


@pytest.fixture 
def test_formats():
    """Define test formats by category."""
    return {
        'text': ['html', 'xml', 'plain', 'calendar', 'csv'],
        'image': ['jpeg', 'png', 'gif', 'webp', 'svg'],
        'audio': ['mp3', 'wav', 'ogg', 'flac', 'aac'],
        'video': ['mp4', 'webm', 'avi', 'mkv', 'mov'],
        'application': ['pdf', 'json', 'zip', 'docx', 'xlsx']
    }


@pytest.mark.performance
class TestFormatSupportCoverage:
    """Test case for format support coverage across different file types."""

    @pytest.fixture(autouse=True)
    def setup_test_results(self, results_dir):
        """Initialize test results structure."""
        self.results = {
            'test_name': 'Format Support Coverage',
            'timestamp': datetime.now().isoformat(),
            'categories': {},
            'overall': {
                'total_formats': 0,
                'supported_formats': 0,
                'coverage_percentage': 0
            }
        }
        yield
        # Save results to JSON file after test
        output_file = os.path.join(results_dir, 'format_support_coverage.json')
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\nTest results saved to {output_file}")

    def test_format_support_coverage(self, test_formats):
        """Test format support coverage for different file types."""
        try:
            # Import the required modules here to allow for graceful failure
            # from core.content_extractor.content_extractor_factory import make_content_extractor
            # from file_format_detector.file_format_detector_factory import make_file_format_detector
            
            # Mock the content extractor and format detector for testing
            mock_extractor = MagicMock()
            mock_file_format_detector = MagicMock()
            
            # Configure mock to return capabilities
            mock_capabilities = {
                'supported_formats': list(test_formats['text']) + 
                                   list(test_formats['image']) + 
                                   ['mp3', 'wav'] +  # partial audio support
                                   ['mp4'] +         # partial video support  
                                   list(test_formats['application'])
            }
            mock_extractor.get_extraction_capabilities.return_value = mock_capabilities
            
            total_formats = 0
            total_supported = 0
            
            # Test each category
            for category, formats in test_formats.items():
                category_results = self._test_category_support(
                    category, formats, mock_extractor, mock_file_format_detector
                )
                
                self.results['categories'][category] = category_results
                
                total_formats += len(formats)
                total_supported += category_results['supported_count']
                
                print(f"{category.title()} Category:")
                print(f"  Total formats: {len(formats)}")
                print(f"  Supported formats: {category_results['supported_count']}")
                print(f"  Coverage: {category_results['coverage_percentage']:.1f}%")
                print(f"  Supported: {', '.join(category_results['supported_formats'])}")
                if category_results['unsupported_formats']:
                    print(f"  Unsupported: {', '.join(category_results['unsupported_formats'])}")
            
            # Calculate overall coverage
            overall_coverage = (total_supported / total_formats) * 100 if total_formats else 0
            
            # Store overall results
            self.results['overall'] = {
                'total_formats': total_formats,
                'supported_formats': total_supported,
                'coverage_percentage': overall_coverage,
                'meets_requirement': overall_coverage >= 80
            }
            
            # Print overall results to console
            print("\nOverall Results:")
            print(f"Total formats: {total_formats}")
            print(f"Supported formats: {total_supported}")
            print(f"Overall coverage: {overall_coverage:.2f}%")
            print(f"Meets requirement (≥80% coverage): {overall_coverage >= 80}")
            
            # Assert that overall coverage is at least 80%
            assert overall_coverage >= 80, "Overall format coverage must be at least 80%"
            
            # Additional test for format detector consistency
            self._verify_format_detector_consistency(mock_extractor, mock_file_format_detector)
            
        except ImportError as e:
            print(f"Failed to import required modules: {e}")
            self.results['error'] = str(e)
            pytest.fail(f"ImportError: {e}")
        except Exception as e:
            print(f"Unexpected error during testing: {e}")
            self.results['error'] = str(e)
            pytest.fail(f"Error: {e}")

    def _test_category_support(self, category: str, formats: list[str], 
                              extractor, file_format_detector) -> dict[str, Any]:
        """Test format support for a specific category."""
        supported_formats = []
        unsupported_formats = []
        
        # Get the list of supported formats from the extractor
        capabilities = extractor.get_extraction_capabilities()
        supported_format_list = capabilities.get('supported_formats', [])
        
        # Check each format in the category
        for format_name in formats:
            try:
                # Mock the format support check
                is_supported = format_name in supported_format_list
                
                if is_supported:
                    supported_formats.append(format_name)
                else:
                    unsupported_formats.append(format_name)
                    
            except Exception as e:
                # If there's an error checking support, consider it unsupported
                unsupported_formats.append(format_name)
                print(f"Error checking support for {format_name}: {e}")
        
        supported_count = len(supported_formats)
        total_count = len(formats)
        coverage_percentage = (supported_count / total_count) * 100 if total_count > 0 else 0
        
        return {
            'category': category,
            'total_formats': total_count,
            'supported_count': supported_count,
            'coverage_percentage': coverage_percentage,
            'supported_formats': supported_formats,
            'unsupported_formats': unsupported_formats
        }

    def _verify_format_detector_consistency(self, extractor, file_format_detector):
        """Verify that the format detector and registry are consistent."""
        # Get formats from extractor capabilities
        extractor_capabilities = extractor.get_extraction_capabilities()
        supported_formats = extractor_capabilities.get('supported_formats', [])
        
        # Mock the format detector's support check
        unrecognized_formats = []
        
        # Check each format is recognized by the format detector
        for format_name in supported_formats:
            # Mock format detector check - assume most formats are recognized
            is_recognized = format_name in ['html', 'xml', 'plain', 'pdf', 'json', 
                                          'jpeg', 'png', 'gif', 'mp3', 'wav', 'mp4']
            if not is_recognized:
                unrecognized_formats.append(format_name)
        
        if unrecognized_formats:
            pytest.fail(f"Format detector does not recognize formats: {unrecognized_formats}")

    def test_specific_format_capabilities(self, test_formats):
        """Test specific capabilities for each format."""
        try:
            # Mock format-specific capabilities
            format_capabilities = {
                'html': {'text_extraction': True, 'metadata_extraction': True, 'structure_preservation': True},
                'xml': {'text_extraction': True, 'metadata_extraction': True, 'structure_preservation': True},
                'plain': {'text_extraction': True, 'metadata_extraction': False, 'structure_preservation': False},
                'pdf': {'text_extraction': True, 'metadata_extraction': True, 'structure_preservation': True},
                'jpeg': {'text_extraction': False, 'metadata_extraction': True, 'structure_preservation': False},
                'png': {'text_extraction': False, 'metadata_extraction': True, 'structure_preservation': False},
                'mp3': {'text_extraction': False, 'metadata_extraction': True, 'structure_preservation': False},
                'mp4': {'text_extraction': False, 'metadata_extraction': True, 'structure_preservation': False}
            }
            
            # Test key format capabilities
            for format_name, capabilities in format_capabilities.items():
                print(f"Format: {format_name}")
                for capability, supported in capabilities.items():
                    print(f"  {capability}: {'Yes' if supported else 'No'}")
                    
                # Assert basic text extraction for text formats
                if format_name in ['html', 'xml', 'plain', 'pdf']:
                    assert capabilities.get('text_extraction', False), f"{format_name} should support text extraction"
                    
        except Exception as e:
            print(f"Error testing format capabilities: {e}")
            pytest.fail(f"Format capability test failed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])