"""
Tests package for the Omni-Converter.

This package contains test modules for each aspect of the converter:
- Format support coverage tests
- Processing success rate tests
- Resource utilization tests
- Processing speed tests
- Error handling effectiveness tests
- Security effectiveness tests
- Text quality tests
"""

import sys
import os

# Add project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import test modules for easier access
try:
    #from .test_skeleton_format_support_coverage import FormatSupportCoverageTest
    # from .test_skeleton_processing_success_rate import ProcessingSuccessRateTest
    # from .test_skeleton_resource_utilization import ResourceUtilizationTest
    # from .test_skeleton_processing_speed import ProcessingSpeedTest
    # #from .test_skeleton_error_handling import ErrorHandlingTest
    # from .test_skeleton_security_effectiveness import SecurityEffectivenessTest
    # from .test_skeleton_text_quality import TextQualityTest
    from _tests.integration_tests.test_vertical_slice import TestVerticalSlice
except ImportError as e:
    # Allow tests to run even if individual modules have import issues
    print(f"Warning: Could not import some test modules: {e}")
