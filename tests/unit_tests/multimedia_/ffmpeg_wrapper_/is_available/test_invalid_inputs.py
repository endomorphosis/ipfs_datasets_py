"""
Invalid input scenarios for FFmpegWrapper.is_available method.

This module tests the is_available method with invalid usage patterns
to ensure the method handles all edge cases gracefully.

Note: The is_available method takes no parameters, so traditional invalid input
testing focuses on method call patterns and environmental conditions.

Terminology:
- method_parameter_provision: Attempting to pass parameters to parameterless method
- invalid_calling_context: Calling method in inappropriate context or state
"""
import pytest
from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper


class TestFFmpegWrapperIsAvailableInvalidInputs:
    """
    Invalid usage scenarios for FFmpegWrapper.is_available method.
    
    Tests the is_available method with invalid calling patterns
    to ensure robust error handling.
    """

    def test_when_called_with_parameters_then_raises_type_error(self):
        """
        GIVEN is_available method call with unexpected parameters provided
        WHEN is_available is called with any parameter arguments
        THEN raises TypeError indicating method takes no arguments
        """
        # Since is_available() has a working implementation, test parameter validation
        from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper
        
        wrapper = FFmpegWrapper()
        
        # Test that method properly rejects parameters
        with pytest.raises(TypeError):
            wrapper.is_available("unexpected_parameter")

    def test_when_called_with_keyword_arguments_then_raises_type_error(self):
        """
        GIVEN is_available method call with keyword arguments provided
        WHEN is_available is called with any keyword parameter arguments
        THEN raises TypeError indicating method takes no arguments
        """
        # Since is_available() has a working implementation, test keyword argument validation
        from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper
        
        wrapper = FFmpegWrapper()
        
        # Test that method properly rejects keyword arguments
        with pytest.raises(TypeError):
            wrapper.is_available(check_path=True)

    def test_when_called_on_uninitialized_class_then_raises_attribute_error(self):
        """
        GIVEN is_available method called on class rather than instance
        WHEN is_available is called on FFmpegWrapper class directly
        THEN raises AttributeError or TypeError indicating method requires instance
        """
        # Since is_available() has a working implementation, test class vs instance access
        from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper
        
        # Test that method requires instance, not class access
        with pytest.raises((AttributeError, TypeError)):
            FFmpegWrapper.is_available()  # Should fail - no instance