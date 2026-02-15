# #!/usr/bin/env python3
# """
# Format Support Coverage Tests for the Omni-Converter.

# This module tests the coverage of format support across different MIME type categories.
# """

# import os
# import json
# import unittest
# from datetime import datetime


# from format_registery.format_registry import format_registry
# from deprecated.content_extractor import ContentExtractor


# from tests._fixtures import fixtures


# class FormatSupportCoverageTest(unittest.TestCase):
#     """Test case for format support coverage across different file types."""
#     # TODO Redo these tests as the format registry has been removed.
#     # TODO Add a test for the format detector to ensure it is consistent with the registry.

#     def setUp(self):
#         """Set up test case with necessary data structures."""
#         self.file_format_detector = fixtures['file_format_detector']
#         self.format_registry = fixtures['format_registry']
#         self.extractor = fixtures['content_extractor_object']()

#         # Define the formats to test in each category
#         self.formats_to_test = {
#             'text': ['html', 'xml', 'plain', 'calendar', 'csv'],
#             'image': ['jpeg', 'png', 'gif', 'webp', 'svg'],
#             'audio': ['mp3', 'wav', 'ogg', 'flac', 'aac'],
#             'video': ['mp4', 'webm', 'avi', 'mkv', 'mov'],
#             'application': ['pdf', 'json', 'zip', 'docx', 'xlsx']
#         }
        
#         # Create the results directory if it doesn't exist
#         os.makedirs('tests/collected_results', exist_ok=True)
        
#         # Results will be stored here
#         self.results = {
#             'test_name': 'Format Support Coverage',
#             'timestamp': datetime.now().isoformat(),
#             'categories': {},
#             'overall': {
#                 'total_formats': 0,
#                 'supported_formats': 0,
#                 'coverage_percentage': 0
#             }
#         }

#     def test_format_support_coverage(self):
#         """Test if the required number of formats are supported in each category."""
#         try:
#             # Get the supported formats from the format registry
#             formats_by_category = format_registry.get_formats_by_category()
            
#             # Test each category
#             total_formats = 0
#             total_supported = 0
            
#             for category, formats in self.formats_to_test.items():
#                 # Get the supported formats for this category
#                 supported_in_category = formats_by_category.get(category, [])
#                 supported_formats = [fmt for fmt in formats if fmt in supported_in_category]
                
#                 total_formats += len(formats)
#                 total_supported += len(supported_formats)
                
#                 # Calculate coverage for this category
#                 coverage_percentage = (len(supported_formats) / len(formats)) * 100 if formats else 0
#                 meets_requirement = len(supported_formats) >= 5
                
#                 # Store results for this category
#                 self.results['categories'][category] = {
#                     'total_formats': len(formats),
#                     'supported_formats': len(supported_formats),
#                     'formats_tested': formats,
#                     'formats_supported': supported_formats,
#                     'coverage_percentage': coverage_percentage,
#                     'meets_requirement': meets_requirement
#                 }
                
#                 # Print results to console
#                 print(f"\nCategory: {category}")
#                 print(f"Formats tested: {formats}")
#                 print(f"Formats supported: {supported_formats}")
#                 print(f"Coverage: {len(supported_formats)}/{len(formats)} ({coverage_percentage:.2f}%)")
#                 print(f"Meets requirement (≥5 formats): {meets_requirement}")
                
#                 # Assert that at least 5 formats are supported in this category
#                 self.assertGreaterEqual(len(supported_formats), 5, 
#                                       f"Category {category} must support at least 5 formats")
            
#             # Calculate overall coverage
#             overall_coverage = (total_supported / total_formats) * 100 if total_formats else 0
            
#             # Store overall results
#             self.results['overall'] = {
#                 'total_formats': total_formats,
#                 'supported_formats': total_supported,
#                 'coverage_percentage': overall_coverage,
#                 'meets_requirement': overall_coverage >= 80
#             }
            
#             # Print overall results to console
#             print("\nOverall Results:")
#             print(f"Total formats: {total_formats}")
#             print(f"Supported formats: {total_supported}")
#             print(f"Overall coverage: {overall_coverage:.2f}%")
#             print(f"Meets requirement (≥80% coverage): {overall_coverage >= 80}")
            
#             # Assert that overall coverage is at least 80%
#             self.assertGreaterEqual(overall_coverage, 80, 
#                                   "Overall format coverage must be at least 80%")
            
#             # Additional test for format detector
#             self.verify_format_detector_consistency()
            
#         except ImportError as e:
#             print(f"Failed to import required modules: {e}")
#             self.results['error'] = str(e)
#             self.fail(f"ImportError: {e}")
#         except Exception as e:
#             print(f"Unexpected error during testing: {e}")
#             self.results['error'] = str(e)
#             self.fail(f"Error: {e}")

#     def verify_format_detector_consistency(self):
#         """Verify that the format detector and registry are consistent."""
#         # Get formats from extractor capabilities
#         extractor_capabilities = self.extractor.get_extraction_capabilities()
#         supported_formats = extractor_capabilities.get('supported_formats', [])
        
#         # Check each format is recognized by the format detector
#         unrecognized_formats = []
#         for format_name in supported_formats:
#             if not self.file_format_detector.is_format_supported(format_name):
#                 unrecognized_formats.append(format_name)
        
#         if unrecognized_formats:
#             self.fail(f"Format detector does not recognize formats: {unrecognized_formats}")
        
#         # Get format registry capabilities
#         registry_formats = format_registry.supported_formats
        
#         # Check for consistency between extractor and registry
#         if sorted(supported_formats) != sorted(registry_formats):
#             self.fail("Inconsistency between extractor supported formats and registry formats")
            
#         print("\nFormat Detector and Registry are consistent.")

#     def tearDown(self):
#         """Save test results to a JSON file."""
#         # Save results to JSON file
#         output_file = os.path.join('tests', 'collected_results', 'format_support_coverage.json')
#         with open(output_file, 'w') as f:
#             json.dump(self.results, f, indent=2)
#         print(f"\nTest results saved to {output_file}")


# if __name__ == '__main__':
#     unittest.main()