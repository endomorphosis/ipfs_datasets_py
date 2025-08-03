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
        return {
            "default_output_dir": tempfile.gettempdir(),
            "enable_logging": True,
            "logger": None,  # Will use default logger
            "ytdlp": None,   # Will create default instance
            "ffmpeg": None   # Will create default instance
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
    def create_initialization_with_custom_wrappers(cls) -> Dict[str, Any]:
        """
        Create initialization data with custom wrapper instances.
        
        Returns:
            Dict[str, Any]: Dictionary with custom wrapper initialization parameters.
                Keys:
                - 'default_output_dir': str - Output directory (temp directory)
                - 'enable_logging': bool - Logging enabled (True)
                - 'logger': None - Default logger
                - 'ytdlp': YtDlpWrapper - Pre-configured YT-DLP wrapper instance
                - 'ffmpeg': FFmpegWrapper - Pre-configured FFmpeg wrapper instance
                
        Examples:
            >>> factory = MediaProcessorTestDataFactory()
            >>> custom_data = factory.create_initialization_with_custom_wrappers()
            >>> isinstance(custom_data['ytdlp'], YtDlpWrapper)
            True
        """
        ytdlp_wrapper = YtDlpWrapperTestDataFactory.create_wrapper_instance()
        ffmpeg_wrapper = FFmpegWrapperTestDataFactory.create_wrapper_instance()
        
        return {
            "default_output_dir": tempfile.gettempdir(),
            "enable_logging": True,
            "logger": None,
            "ytdlp": ytdlp_wrapper,
            "ffmpeg": ffmpeg_wrapper
        }

    @classmethod
    def create_download_and_convert_test_data(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create test data for download and convert operations.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with download and convert test scenarios.
                Keys:
                - 'basic_download_convert': Dict - Basic download and convert test
                  - 'url': str - Video URL to download
                  - 'output_format': str - Desired output format ("mp4")
                  - 'quality': str - Quality setting ("best")
                - 'download_to_avi': Dict - Download and convert to AVI format
                - 'audio_download': Dict - Audio-only download test
                - 'high_quality_convert': Dict - High quality conversion test
                - 'format_no_conversion': Dict - Test where no conversion is needed
        """
        return {
            "basic_download_convert": {
                "url": "https://youtube.com/watch?v=example",
                "output_format": "mp4",
                "quality": "best"
            },
            "download_to_avi": {
                "url": "https://vimeo.com/123456789",
                "output_format": "avi",
                "quality": "720p"
            },
            "audio_download": {
                "url": "https://soundcloud.com/track",
                "output_format": "mp3",
                "quality": "best"
            },
            "high_quality_convert": {
                "url": "https://youtube.com/watch?v=example",
                "output_format": "mkv",
                "quality": "best[height<=1080]"
            },
            "format_no_conversion": {
                "url": "https://youtube.com/watch?v=example",
                "output_format": "mp4",  # Same as likely download format
                "quality": "best"
            }
        }

    @classmethod
    def create_invalid_download_convert_data(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create invalid download and convert test data.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with invalid test scenarios.
                Keys:
                - 'empty_url': Dict - Empty URL test case
                  - 'url': str - Empty URL string ("")
                  - 'output_format': str - Valid format ("mp4")
                  - 'quality': str - Valid quality ("best")
                - 'invalid_url': Dict - Malformed URL test case
                  - 'url': str - Invalid URL ("not-a-valid-url")
                  - 'output_format': str - Valid format
                  - 'quality': str - Valid quality
                - 'unsupported_format': Dict - Invalid output format
                  - 'url': str - Valid URL
                  - 'output_format': str - Unsupported format ("unsupported_format")
                  - 'quality': str - Valid quality
                - 'invalid_quality': Dict - Invalid quality setting
                  - 'url': str - Valid URL
                  - 'output_format': str - Valid format
                  - 'quality': str - Invalid quality ("invalid_quality")
                  
        Examples:
            >>> factory = MediaProcessorTestDataFactory()
            >>> invalid_data = factory.create_invalid_download_convert_data()
            >>> invalid_data['empty_url']['url']
            ''
        """
        return {
            "empty_url": {
                "url": "",
                "output_format": "mp4",
                "quality": "best"
            },
            "invalid_url": {
                "url": "not-a-valid-url",
                "output_format": "mp4",
                "quality": "best"
            },
            "unsupported_format": {
                "url": "https://youtube.com/watch?v=example",
                "output_format": "unsupported_format",
                "quality": "best"
            },
            "invalid_quality": {
                "url": "https://youtube.com/watch?v=example",
                "output_format": "mp4",
                "quality": "invalid_quality"
            }
        }

    @classmethod
    def create_expected_capabilities(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create expected capabilities response structures.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with expected capabilities.
                Keys:
                - 'full_capabilities': Dict - All features available
                  - 'ytdlp_available': bool - YT-DLP availability (True)
                  - 'ffmpeg_available': bool - FFmpeg availability (True)
                  - 'supported_operations': Dict - Available operations
                    - 'download': bool - Download capability (True)
                    - 'convert': bool - Convert capability (True)
                    - 'download_and_convert': bool - Combined workflow capability (True)
                - 'ytdlp_only': Dict - Only YT-DLP available
                - 'ffmpeg_only': Dict - Only FFmpeg available
                - 'no_capabilities': Dict - No features available
        """
        return {
            "full_capabilities": {
                "ytdlp_available": True,
                "ffmpeg_available": True,
                "supported_operations": {
                    "download": True,
                    "convert": True,
                    "download_and_convert": True
                }
            },
            "ytdlp_only": {
                "ytdlp_available": True,
                "ffmpeg_available": False,
                "supported_operations": {
                    "download": True,
                    "convert": False,
                    "download_and_convert": False
                }
            },
            "ffmpeg_only": {
                "ytdlp_available": False,
                "ffmpeg_available": True,
                "supported_operations": {
                    "download": False,
                    "convert": True,
                    "download_and_convert": False
                }
            },
            "no_capabilities": {
                "ytdlp_available": False,
                "ffmpeg_available": False,
                "supported_operations": {
                    "download": False,
                    "convert": False,
                    "download_and_convert": False
                }
            }
        }

    @classmethod
    def create_expected_success_responses(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create expected success response structures.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with expected success responses.
                Keys:
                - 'download_only_success': Dict - Download without conversion
                  - 'status': str - Success status ("success")
                  - 'output_path': str - Path to downloaded file
                  - 'title': str - Video title
                  - 'duration': int - Video duration in seconds
                  - 'filesize': int - File size in bytes
                  - 'format': str - Downloaded format
                - 'download_and_convert_success': Dict - Download with conversion
                  - 'converted_path': str - Path to converted file
                  - 'conversion_result': Dict - Conversion operation result
                    - 'status': str - Conversion status
                    - 'input_path': str - Source file for conversion
                    - 'output_path': str - Converted file path
                    - 'message': str - Conversion completion message
        """
        return {
            "download_only_success": {
                "status": "success",
                "output_path": "/path/to/downloaded.mp4",
                "title": "Example Video",
                "duration": 300,
                "filesize": 50000000,
                "format": "mp4"
            },
            "download_and_convert_success": {
                "status": "success",
                "output_path": "/path/to/downloaded.mp4",
                "title": "Example Video",
                "duration": 300,
                "filesize": 50000000,
                "format": "mp4",
                "converted_path": "/path/to/converted.avi",
                "conversion_result": {
                    "status": "success",
                    "input_path": "/path/to/downloaded.mp4",
                    "output_path": "/path/to/converted.avi",
                    "message": "Video conversion completed"
                }
            }
        }

    @classmethod
    def create_expected_error_responses(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create expected error response structures.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with expected error responses.
                Keys:
                - 'ytdlp_unavailable': Dict - YT-DLP not available error
                  - 'status': str - Error status ("error")
                  - 'error': str - Error message about YT-DLP availability
                - 'download_failed': Dict - Download operation failure
                  - 'status': str - Error status ("error")
                  - 'error': str - Download failure message
                - 'conversion_failed': Dict - Conversion operation failure
                  - 'status': str - Error status ("error")
                  - 'error': str - FFmpeg unavailability message
                - 'invalid_url_error': Dict - URL validation failure
                  - 'status': str - Error status ("error")
                  - 'error': str - URL format error message
                  
        Examples:
            >>> factory = MediaProcessorTestDataFactory()
            >>> error_responses = factory.create_expected_error_responses()
            >>> error_responses['download_failed']['status']
            'error'
        """
        return {
            "ytdlp_unavailable": {
                "status": "error",
                "error": "YT-DLP not available for download"
            },
            "download_failed": {
                "status": "error",
                "error": "Download failed: Video unavailable"
            },
            "conversion_failed": {
                "status": "error",
                "error": "Conversion failed: FFmpeg not available"
            },
            "invalid_url_error": {
                "status": "error",
                "error": "Invalid URL format"
            }
        }

    @classmethod
    def create_processor_instance(cls, **overrides) -> MediaProcessor:
        """
        Create a MediaProcessor instance with optional overrides.
        
        Args:
            **overrides: Parameters to override in the initialization.
            
        Returns:
            MediaProcessor: Configured MediaProcessor instance.
        """
        data = cls.create_valid_initialization_data()
        data.update(overrides)
        return MediaProcessor(**data)

    @classmethod
    def create_minimal_processor_instance(cls, **overrides) -> MediaProcessor:
        """
        Create a minimal MediaProcessor instance with optional overrides.
        
        Args:
            **overrides: Parameters to override in the minimal initialization.
            
        Returns:
            MediaProcessor: Minimal MediaProcessor instance.
        """
        data = cls.create_minimal_initialization_data()
        data.update(overrides)
        return MediaProcessor(**data)

    @classmethod
    def create_processor_with_custom_wrappers(cls, **overrides) -> MediaProcessor:
        """
        Create a MediaProcessor instance with custom wrapper instances.
        
        Args:
            **overrides: Parameters to override in the initialization.
            
        Returns:
            MediaProcessor: MediaProcessor instance with custom wrappers.
        """
        data = cls.create_initialization_with_custom_wrappers()
        data.update(overrides)
        return MediaProcessor(**data)

    @classmethod
    def create_processor_via_factory(cls, **overrides) -> MediaProcessor:
        """
        Create a MediaProcessor instance using the factory function.
        
        Args:
            **overrides: Parameters to override in the factory function.
            
        Returns:
            MediaProcessor: MediaProcessor instance created via factory.
        """
        data = cls.create_valid_initialization_data()
        data.update(overrides)
        return make_media_processor(**data)

    @classmethod
    def create_mock_wrapper_instances(cls) -> Dict[str, Any]:
        """
        Create mock wrapper instances for testing without real dependencies.
        
        Returns:
            Dict[str, Any]: Dictionary with mock wrapper instances.
                Keys:
                - 'ytdlp': YtDlpWrapper - Mock YT-DLP wrapper instance
                - 'ffmpeg': FFmpegWrapper - Mock FFmpeg wrapper instance
        """
        # Create mock YtDlp wrapper
        mock_ytdlp = YtDlpWrapperTestDataFactory.create_minimal_wrapper_instance()
        
        # Create mock FFmpeg wrapper  
        mock_ffmpeg = FFmpegWrapperTestDataFactory.create_minimal_wrapper_instance()
        
        return {
            "ytdlp": mock_ytdlp,
            "ffmpeg": mock_ffmpeg
        }

    @classmethod
    def create_output_directory_scenarios(cls) -> Dict[str, str]:
        """
        Create different output directory scenarios for testing.
        
        Returns:
            Dict[str, str]: Dictionary with output directory scenarios.
                Keys:
                - 'temp_dir': str - System temporary directory
                - 'custom_absolute': str - Custom absolute path ("/tmp/media_processor_test")
                - 'custom_relative': str - Relative path ("./media_output")
                - 'nested_dir': str - Nested directory structure ("/tmp/test/nested/media")
                - 'home_dir': str - Home directory relative path ("~/media_processor")
                - 'current_dir': str - Current working directory (".")
                
        Examples:
            >>> factory = MediaProcessorTestDataFactory()
            >>> dir_scenarios = factory.create_output_directory_scenarios()
            >>> dir_scenarios['current_dir']
            '.'
        """
        return {
            "temp_dir": tempfile.gettempdir(),
            "custom_absolute": "/tmp/media_processor_test",
            "custom_relative": "./media_output", 
            "nested_dir": "/tmp/test/nested/media",
            "home_dir": "~/media_processor",
            "current_dir": "."
        }

    @classmethod
    def create_workflow_test_scenarios(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create comprehensive workflow test scenarios.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with workflow test scenarios.
                Keys:
                - 'youtube_to_mp4': Dict - YouTube download kept as MP4
                  - 'description': str - Scenario description
                  - 'url': str - YouTube video URL
                  - 'output_format': str - Target format ("mp4")
                  - 'quality': str - Quality setting ("best")
                  - 'expected_conversion': bool - Whether conversion is expected (False)
                - 'youtube_to_avi': Dict - YouTube download converted to AVI
                  - 'expected_conversion': bool - Conversion expected (True)
                - 'vimeo_high_quality': Dict - Vimeo high quality download
                - 'soundcloud_audio': Dict - SoundCloud audio download
        """
        return {
            "youtube_to_mp4": {
                "description": "Download YouTube video and keep as MP4",
                "url": "https://youtube.com/watch?v=example",
                "output_format": "mp4",
                "quality": "best",
                "expected_conversion": False
            },
            "youtube_to_avi": {
                "description": "Download YouTube video and convert to AVI", 
                "url": "https://youtube.com/watch?v=example",
                "output_format": "avi",
                "quality": "720p",
                "expected_conversion": True
            },
            "vimeo_high_quality": {
                "description": "Download Vimeo video in high quality",
                "url": "https://vimeo.com/123456789",
                "output_format": "mkv",
                "quality": "best[height<=1080]",
                "expected_conversion": True
            },
            "soundcloud_audio": {
                "description": "Download SoundCloud track",
                "url": "https://soundcloud.com/artist/track",
                "output_format": "mp3",
                "quality": "best",
                "expected_conversion": False
            }
        }

    @classmethod
    def create_edge_case_scenarios(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create edge case scenarios for comprehensive testing.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with edge case scenarios.
                Keys:
                - 'unicode_url': Dict - URL with Unicode characters
                  - 'url': str - URL containing Cyrillic characters
                  - 'output_format': str - Target format ("mp4")
                  - 'quality': str - Quality setting ("best")
                - 'very_long_url': Dict - Extremely long URL test
                  - 'url': str - URL with 1000+ character parameter
                  - 'output_format': str - Target format
                  - 'quality': str - Quality setting
                - 'special_characters': Dict - URL with special characters
                  - 'url': str - URL containing @#$% symbols
                  - 'output_format': str - Target format
                  - 'quality': str - Quality setting
                - 'same_format_conversion': Dict - No conversion needed test
                  - 'url': str - Valid URL
                  - 'output_format': str - Same as source format ("mp4")
                  - 'quality': str - Quality setting
                  
        Examples:
            >>> factory = MediaProcessorTestDataFactory()
            >>> edge_cases = factory.create_edge_case_scenarios()
            >>> 'тест' in edge_cases['unicode_url']['url']
            True
        """
        return {
            "unicode_url": {
                "url": "https://youtube.com/watch?v=тест",
                "output_format": "mp4",
                "quality": "best"
            },
            "very_long_url": {
                "url": "https://youtube.com/watch?v=" + "a" * 1000,
                "output_format": "mp4", 
                "quality": "best"
            },
            "special_characters": {
                "url": "https://youtube.com/watch?v=test@#$%",
                "output_format": "mp4",
                "quality": "best"
            },
            "same_format_conversion": {
                "url": "https://youtube.com/watch?v=example",
                "output_format": "mp4",  # Same as likely downloaded format
                "quality": "best"
            }
        }
