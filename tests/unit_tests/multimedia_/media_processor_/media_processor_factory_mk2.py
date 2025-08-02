#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test data factory for generating MediaProcessor instances and test data.

Provides methods to create valid baseline data, invalid variations, and edge cases
for comprehensive testing of the MediaProcessor class validation logic.
"""
from typing import Dict, Any, Optional
from pathlib import Path
import tempfile
import logging

from ipfs_datasets_py.multimedia.media_processor import MediaProcessor, make_media_processor
from ipfs_datasets_py.multimedia.ytdlp_wrapper import YtDlpWrapper
from ipfs_datasets_py.multimedia.ffmpeg_wrapper import FFmpegWrapper

from tests.unit_tests.multimedia_.ytdlp_wrapper_.ytdlp_wrapper_factory import YtDlpWrapperTestDataFactory
from tests.unit_tests.multimedia_.ffmpeg_wrapper_.ffmpeg_wrapper_test_data_factory import FFmpegWrapperTestDataFactory


class MediaProcessorTestDataFactory:
    """
    Test data factory for generating MediaProcessor instances and test data.
    
    Provides methods to create valid baseline data, invalid variations, and edge cases
    for comprehensive testing of the MediaProcessor class validation logic.
    
    Class Methods:
        create_valid_initialization_data(): Create valid initialization parameters
        create_minimal_initialization_data(): Create minimal initialization parameters
        create_initialization_with_pre_configured_wrappers(): Create initialization with custom wrappers
        create_processor_instance(**initialization_overrides): Create MediaProcessor instance with initialization_overrides
        create_minimal_processor_instance(**initialization_overrides): Create minimal MediaProcessor instance
        create_processor_with_custom_wrappers(**initialization_overrides): Create processor with custom wrappers
        create_valid_processor(**initialization_overrides): Create processor using factory function
    
    Examples:
        >>> # Create a MediaProcessor instance for testing
        >>> processor = MediaProcessorTestDataFactory.create_processor_instance()
        >>> 
        >>> # Get download and convert test data
        >>> test_data = MediaProcessorTestDataFactory.create_download_and_convert_test_data()
        >>> basic_test = test_data['basic_download_convert']
        >>> url = basic_test['url']  # "https://youtube.com/watch?v=example"
        >>> 
        >>> # Get expected capabilities for different scenarios
        >>> capabilities = MediaProcessorTestDataFactory.create_expected_capabilities()
        >>> full_caps = capabilities['full_capabilities']  # Both ytdlp and ffmpeg available
        >>> 
        >>> # Create processor with custom wrappers
        >>> custom_processor = MediaProcessorTestDataFactory.create_processor_with_custom_wrappers(
        ...     enable_logging=False
        ... )
    """

    @classmethod
    def create_valid_initialization_data(cls) -> Dict[str, Any]:
        """
        Create valid initialization parameters for MediaProcessor.
        
        Returns:
            Dict[str, Any]: Dictionary with valid initialization parameters.
                Keys:
                - 'default_output_dir': str - Directory for output files (temp directory)
                - 'enable_logging': bool - Whether to enable logging (True)
                - 'logger': None - Logger instance (None for default)
                - 'ytdlp': None - YtDlpWrapper instance (None for auto-creation)
                - 'ffmpeg': None - FFmpegWrapper instance (None for auto-creation)
                
        Examples:
            >>> factory = MediaProcessorTestDataFactory()
            >>> init_data = factory.create_valid_initialization_data()
            >>> init_data['enable_logging']
            True
        """
        logger = logging.getLogger("MediaProcessorTestDataFactory")
        ytdlp_wrapper = YtDlpWrapperTestDataFactory.create_wrapper_instance()
        ffmpeg_wrapper = FFmpegWrapperTestDataFactory.create_wrapper_instance()
        return {
            "default_output_dir": tempfile.gettempdir(),
            "enable_logging": True,
            "logger": logger, # Will use default logger
            "ytdlp": ytdlp_wrapper,
            "ffmpeg": ffmpeg_wrapper
        }

    @classmethod
    def create_minimal_initialization_data(cls) -> Dict[str, Any]:
        """
        Create minimal initialization parameters for MediaProcessor.
        
        Returns:
            Dict[str, Any]: Dictionary with minimal initialization parameters.
                Keys:
                - 'default_output_dir': None - No output directory specified
                - 'enable_logging': bool - Logging disabled (False)
                - 'logger': None - No logger specified
                - 'ytdlp': None - No YtDlpWrapper instance
                - 'ffmpeg': None - No FFmpegWrapper instance
                
        Examples:
            >>> factory = MediaProcessorTestDataFactory()
            >>> minimal_data = factory.create_minimal_initialization_data()
            >>> minimal_data['enable_logging']
            False
        """
        return {
            "default_output_dir": None,
            "enable_logging": False,
            "logger": None,
            "ytdlp": None,
            "ffmpeg": None
        }

    @classmethod
    def create_processor_instance(cls, **initialization_overrides) -> MediaProcessor:
        """
        Create a MediaProcessor instance with optional initialization_overrides.
        
        Args:
            **initialization_overrides: Parameters to override in the initialization.
                Valid Keys:
                - 'default_output_dir': None - No output directory specified
                - 'enable_logging': bool - Logging disabled (False)
                - 'logger': None - No logger specified
                - 'ytdlp': None - No YtDlpWrapper instance
                - 'ffmpeg': None - No FFmpegWrapper instance
            
        Returns:
            MediaProcessor: Configured MediaProcessor instance.
        """
        data = cls.create_valid_initialization_data()
        data.update(initialization_overrides)
        return MediaProcessor(**data)

    @classmethod
    def create_minimal_processor_instance(cls, **initialization_overrides) -> MediaProcessor:
        """
        Create a minimal MediaProcessor instance with optional initialization_overrides.
        
        Args:
            **initialization_overrides: Parameters to override in the minimal initialization.
            
        Returns:
            MediaProcessor: Minimal MediaProcessor instance.
        """
        data = cls.create_minimal_initialization_data()
        data.update(initialization_overrides)
        return MediaProcessor(**data)
