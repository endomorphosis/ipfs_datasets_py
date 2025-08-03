#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test data factory for generating FFmpegWrapper instances and test data.

Provides methods to create valid baseline data, invalid variations, and edge cases
for comprehensive testing of the FFmpegWrapper class validation logic.
"""
from typing import Dict, Any, Optional, Callable
from pathlib import Path
import tempfile

from ipfs_datasets_py.multimedia.ffmpeg_wrapper import FFmpegWrapper


class FFmpegWrapperTestDataFactory:
    """
    Test data factory for generating FFmpegWrapper instances and test data.
    
    Provides methods to create valid baseline data, invalid variations, and edge cases
    for comprehensive testing of the FFmpegWrapper class validation logic.
    
    Examples:
        >>> # Create an FFmpegWrapper instance for testing
        >>> wrapper = FFmpegWrapperTestDataFactory.create_wrapper_instance()
        >>> 
        >>> # Get conversion test data
        >>> conversion_data = FFmpegWrapperTestDataFactory.create_conversion_test_data()
        >>> basic_test = conversion_data['basic_conversion']
        >>> input_path = basic_test['input_path']  # "/path/to/input.mp4"
        >>> 
        >>> # Get expected response structures
        >>> responses = FFmpegWrapperTestDataFactory.create_expected_success_responses()
        >>> success_response = responses['basic_success']  # {"status": "success", ...}
        >>> 
        >>> # Create wrapper with custom settings
        >>> custom_wrapper = FFmpegWrapperTestDataFactory.create_wrapper_instance(
        ...     default_output_dir="/custom/path",
        ...     enable_logging=False
        ... )
    """

    @classmethod
    def create_valid_initialization_data(cls) -> Dict[str, Any]:
        """
        Create valid initialization parameters for FFmpegWrapper.
        
        Returns:
            Dict[str, Any]: Dictionary with valid initialization parameters.
                Keys:
                - 'default_output_dir': str - Temporary directory path for output files
                - 'enable_logging': bool - Enable detailed logging (True)
                
        Examples:
            >>> factory = FFmpegWrapperTestDataFactory()
            >>> init_data = factory.create_valid_initialization_data()
            >>> init_data['enable_logging']
            True
        """
        return {
            "default_output_dir": tempfile.gettempdir(),
            "enable_logging": True
        }

    @classmethod
    def create_minimal_initialization_data(cls) -> Dict[str, Any]:
        """
        Create minimal initialization parameters for FFmpegWrapper.
        
        Returns:
            Dict[str, Any]: Dictionary with minimal initialization parameters.
                Keys:
                - 'default_output_dir': None - No default output directory specified
                - 'enable_logging': bool - Disable logging (False)
                
        Examples:
            >>> factory = FFmpegWrapperTestDataFactory()
            >>> minimal_data = factory.create_minimal_initialization_data()
            >>> minimal_data['enable_logging']
            False
        """
        return {
            "default_output_dir": None,
            "enable_logging": False
        }

    @classmethod
    def create_conversion_test_data(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create test data for video conversion operations.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with conversion test scenarios.
                Keys:
                - 'basic_conversion': Dict - Basic format conversion test
                  - 'input_path': str - Source video file path
                  - 'output_path': str - Target output file path
                  - 'kwargs': Dict - Additional conversion parameters (empty)
                - 'quality_conversion': Dict - Quality-focused conversion test
                  - 'kwargs': Dict - Contains video_codec, video_bitrate, audio_codec
                - 'resolution_conversion': Dict - Resolution change conversion test
                  - 'kwargs': Dict - Contains resolution, video_bitrate, audio_bitrate
                - 'codec_conversion': Dict - Codec change conversion test
                  - 'kwargs': Dict - Contains video_codec, audio_codec, crf
                - 'preset_conversion': Dict - Preset-based conversion test
                  - 'kwargs': Dict - Contains preset, crf parameters
        """
        return {
            "basic_conversion": {
                "input_path": "/path/to/input.mp4",
                "output_path": "/path/to/output.avi",
                "kwargs": {}
            },
            "quality_conversion": {
                "input_path": "/path/to/input.mov",
                "output_path": "/path/to/output.mp4",
                "kwargs": {
                    "video_codec": "libx264",
                    "video_bitrate": "1M",
                    "audio_codec": "aac"
                }
            },
            "resolution_conversion": {
                "input_path": "/path/to/input.mkv",
                "output_path": "/path/to/output.mp4",
                "kwargs": {
                    "resolution": "1280x720",
                    "video_bitrate": "2M",
                    "audio_bitrate": "128k"
                }
            },
            "codec_conversion": {
                "input_path": "/path/to/input.avi",
                "output_path": "/path/to/output.webm",
                "kwargs": {
                    "video_codec": "vp9",
                    "audio_codec": "opus",
                    "crf": 23
                }
            },
            "preset_conversion": {
                "input_path": "/path/to/input.mp4",
                "output_path": "/path/to/output.mp4",
                "kwargs": {
                    "preset": "medium",
                    "crf": 18
                }
            }
        }

    @classmethod
    def create_invalid_conversion_data(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create invalid conversion test data for error testing.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with invalid conversion scenarios.
                Keys:
                - 'empty_input_path': Dict - Test with empty input path string
                  - 'input_path': str - Empty string
                  - 'output_path': str - Valid output path
                  - 'kwargs': Dict - Empty parameters
                - 'empty_output_path': Dict - Test with empty output path
                - 'none_input_path': Dict - Test with None input path
                - 'none_output_path': Dict - Test with None output path
                - 'nonexistent_input': Dict - Test with nonexistent input file
        """
        return {
            "empty_input_path": {
                "input_path": "",
                "output_path": "/path/to/output.mp4",
                "kwargs": {}
            },
            "empty_output_path": {
                "input_path": "/path/to/input.mp4",
                "output_path": "",
                "kwargs": {}
            },
            "none_input_path": {
                "input_path": None,
                "output_path": "/path/to/output.mp4",
                "kwargs": {}
            },
            "none_output_path": {
                "input_path": "/path/to/input.mp4",
                "output_path": None,
                "kwargs": {}
            },
            "nonexistent_input": {
                "input_path": "/nonexistent/file.mp4",
                "output_path": "/path/to/output.mp4",
                "kwargs": {}
            }
        }

    @classmethod
    def create_expected_success_responses(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create expected success response structures.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with expected success responses.
                Keys:
                - 'basic_success': Dict - Basic successful conversion response
                  - 'status': str - Success status ("success")
                  - 'input_path': str - Original input file path
                  - 'output_path': str - Generated output file path
                  - 'message': str - Success message
                - 'conversion_with_metadata': Dict - Success response with metadata
                  - 'duration': float - Conversion duration in seconds
                  - 'input_metadata': Dict - Input file metadata (codec, resolution)
                  - 'output_metadata': Dict - Output file metadata (codec, resolution)
        """
        return {
            "basic_success": {
                "status": "success",
                "input_path": "/path/to/input.mp4",
                "output_path": "/path/to/output.avi",
                "message": "Video conversion completed"
            },
            "conversion_with_metadata": {
                "status": "success",
                "input_path": "/path/to/input.mov",
                "output_path": "/path/to/output.mp4",
                "message": "Video conversion completed",
                "duration": 120.5,
                "input_metadata": {"codec": "h264", "resolution": "1920x1080"},
                "output_metadata": {"codec": "h264", "resolution": "1280x720"}
            }
        }

    @classmethod
    def create_expected_error_responses(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create expected error response structures.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with expected error responses.
                Keys:
                - 'ffmpeg_unavailable': Dict - Error when FFmpeg is not available
                  - 'status': str - Error status ("error")
                  - 'error': str - Error message describing FFmpeg unavailability
                - 'file_not_found': Dict - Error when input file doesn't exist
                - 'permission_error': Dict - Error when lacking file permissions
                - 'invalid_format': Dict - Error when format is unsupported
        """
        return {
            "ffmpeg_unavailable": {
                "status": "error",
                "error": "FFmpeg not available"
            },
            "file_not_found": {
                "status": "error",
                "error": "Input file not found"
            },
            "permission_error": {
                "status": "error",
                "error": "Permission denied"
            },
            "invalid_format": {
                "status": "error",
                "error": "Unsupported format"
            }
        }

    @classmethod
    def create_audio_extraction_test_data(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create test data for audio extraction operations.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with audio extraction test scenarios.
                Keys:
                - 'basic_audio_extraction': Dict - Simple audio extraction
                  - 'input_path': str - Source video file path
                  - 'output_path': str - Target audio file path (.mp3)
                  - 'kwargs': Dict - Empty parameters for default extraction
                - 'high_quality_extraction': Dict - High quality audio extraction
                  - 'input_path': str - Source video file (.mkv)
                  - 'output_path': str - FLAC output file
                  - 'kwargs': Dict - Contains audio_codec, sample_rate, normalize
                - 'specific_track_extraction': Dict - Extract specific audio track
                  - 'kwargs': Dict - Contains track_index, audio_codec, audio_bitrate
                  
        Examples:
            >>> factory = FFmpegWrapperTestDataFactory()
            >>> audio_data = factory.create_audio_extraction_test_data()
            >>> audio_data['basic_audio_extraction']['output_path']
            '/path/to/audio.mp3'
        """
        return {
            "basic_audio_extraction": {
                "input_path": "/path/to/video.mp4",
                "output_path": "/path/to/audio.mp3",
                "kwargs": {}
            },
            "high_quality_extraction": {
                "input_path": "/path/to/video.mkv",
                "output_path": "/path/to/audio.flac",
                "kwargs": {
                    "audio_codec": "flac",
                    "sample_rate": 96000,
                    "normalize": True
                }
            },
            "specific_track_extraction": {
                "input_path": "/path/to/multilang.mp4",
                "output_path": "/path/to/audio.aac",
                "kwargs": {
                    "track_index": 1,
                    "audio_codec": "aac",
                    "audio_bitrate": "320k"
                }
            }
        }

    @classmethod
    def create_thumbnail_generation_test_data(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create test data for thumbnail generation operations.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with thumbnail generation test scenarios.
                Keys:
                - 'basic_thumbnail': Dict - Simple thumbnail generation
                  - 'input_path': str - Source video file path
                  - 'output_path': str - Target thumbnail image (.jpg)
                  - 'kwargs': Dict - Empty parameters for default settings
                - 'custom_time_thumbnail': Dict - Thumbnail at specific time
                  - 'output_path': str - PNG thumbnail output
                  - 'kwargs': Dict - Contains timestamp, width, height
                - 'high_quality_thumbnail': Dict - High quality thumbnail
                  - 'output_path': str - WebP thumbnail output
                  - 'kwargs': Dict - Contains timestamp, quality, smart_frame
                  
        Examples:
            >>> factory = FFmpegWrapperTestDataFactory()
            >>> thumb_data = factory.create_thumbnail_generation_test_data()
            >>> thumb_data['custom_time_thumbnail']['kwargs']['timestamp']
            '00:02:30'
        """
        return {
            "basic_thumbnail": {
                "input_path": "/path/to/video.mp4",
                "output_path": "/path/to/thumb.jpg",
                "kwargs": {}
            },
            "custom_time_thumbnail": {
                "input_path": "/path/to/video.avi",
                "output_path": "/path/to/thumb.png",
                "kwargs": {
                    "timestamp": "00:02:30",
                    "width": 640,
                    "height": 360
                }
            },
            "high_quality_thumbnail": {
                "input_path": "/path/to/video.mkv",
                "output_path": "/path/to/thumb.webp",
                "kwargs": {
                    "timestamp": "25%",
                    "quality": 95,
                    "smart_frame": True
                }
            }
        }

    @classmethod
    def create_wrapper_instance(cls, **overrides) -> FFmpegWrapper:
        """
        Create an FFmpegWrapper instance with optional overrides.
        
        Args:
            **overrides: Parameters to override in the initialization.
            
        Returns:
            FFmpegWrapper: Configured FFmpegWrapper instance.
        """
        data = cls.create_valid_initialization_data()
        data.update(overrides)
        return FFmpegWrapper(**data)

    @classmethod
    def create_minimal_wrapper_instance(cls, **overrides) -> FFmpegWrapper:
        """
        Create a minimal FFmpegWrapper instance with optional overrides.
        
        Args:
            **overrides: Parameters to override in the minimal initialization.
            
        Returns:
            FFmpegWrapper: Minimal FFmpegWrapper instance.
        """
        data = cls.create_minimal_initialization_data()
        data.update(overrides)
        return FFmpegWrapper(**data)

    @classmethod
    def create_output_directories(cls) -> Dict[str, str]:
        """
        Create test output directories for different scenarios.
        
        Returns:
            Dict[str, str]: Dictionary with output directory paths.
                Keys:
                - 'temp_dir': str - System temporary directory path
                - 'custom_dir': str - Custom absolute directory path
                - 'nested_dir': str - Nested directory structure path
                - 'relative_dir': str - Relative directory path
                - 'home_dir': str - Home directory relative path
        """
        temp_dir = tempfile.gettempdir()
        return {
            "temp_dir": temp_dir,
            "custom_dir": "/tmp/ffmpeg_test_output",
            "nested_dir": "/tmp/test/nested/output",
            "relative_dir": "./output",
            "home_dir": "~/ffmpeg_output"
        }

    @classmethod
    def create_invalid_initialization_data(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create invalid initialization data for error testing.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with invalid initialization scenarios.
                Keys:
                - 'invalid_output_dir_type': Dict - Wrong data type for output directory
                  - 'default_output_dir': int - Integer instead of string (123)
                  - 'enable_logging': bool - Valid logging setting
                - 'invalid_logging_type': Dict - Wrong data type for logging flag
                  - 'default_output_dir': str - Valid directory path
                  - 'enable_logging': str - String instead of boolean ("true")
                - 'nonexistent_output_dir': Dict - Directory that doesn't exist
                  - 'default_output_dir': str - Path to nonexistent directory
                  - 'enable_logging': bool - Valid logging setting
                  
        Examples:
            >>> factory = FFmpegWrapperTestDataFactory()
            >>> invalid_data = factory.create_invalid_initialization_data()
            >>> invalid_data['invalid_output_dir_type']['default_output_dir']
            123
        """
        return {
            "invalid_output_dir_type": {
                "default_output_dir": 123,
                "enable_logging": True
            },
            "invalid_logging_type": {
                "default_output_dir": "/tmp",
                "enable_logging": "true"
            },
            "nonexistent_output_dir": {
                "default_output_dir": "/nonexistent/directory/path",
                "enable_logging": True
            }
        }

    @classmethod
    def create_edge_case_paths(cls) -> Dict[str, str]:
        """
        Create edge case file paths for testing.
        
        Returns:
            Dict[str, str]: Dictionary with edge case file paths.
                Keys:
                - 'unicode_input': str - Input path with Cyrillic characters
                - 'unicode_output': str - Output path with Cyrillic characters
                - 'spaces_input': str - Input path with spaces in names
                - 'spaces_output': str - Output path with spaces in names
                - 'very_long_path': str - Extremely long file path (200+ chars)
                - 'special_chars': str - Path with special characters (@#$%^&*())
                - 'relative_input': str - Relative input path ("./relative/input.mp4")
                - 'relative_output': str - Relative output path ("./relative/output.avi")
                
        Examples:
            >>> factory = FFmpegWrapperTestDataFactory()
            >>> edge_paths = factory.create_edge_case_paths()
            >>> 'тест' in edge_paths['unicode_input']
            True
        """
        return {
            "unicode_input": "/path/to/тест.mp4",
            "unicode_output": "/path/to/выход.avi",
            "spaces_input": "/path with spaces/input file.mp4",
            "spaces_output": "/path with spaces/output file.avi",
            "very_long_path": "/very/long/path/" + "a" * 200 + "/file.mp4",
            "special_chars": "/path/file@#$%^&*().mp4",
            "relative_input": "./relative/input.mp4",
            "relative_output": "./relative/output.avi"
        }

    @classmethod
    def create_conversion_kwargs_variations(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create different kwargs variations for conversion testing.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with kwargs variations.
                Keys:
                - 'empty_kwargs': Dict - Empty parameters for default conversion
                - 'video_only': Dict - Video-focused parameters
                  - 'video_codec': str - Video codec ("libx264")
                  - 'video_bitrate': str - Video bitrate ("2M")
                - 'audio_only': Dict - Audio-focused parameters
                  - 'audio_codec': str - Audio codec ("aac")
                  - 'audio_bitrate': str - Audio bitrate ("192k")
                - 'quality_focused': Dict - High quality settings
                  - 'crf': int - Constant rate factor (18)
                  - 'preset': str - Encoding preset ("slow")
                - 'size_focused': Dict - Small file size settings
                  - 'video_bitrate': str - Low video bitrate ("500k")
                  - 'audio_bitrate': str - Low audio bitrate ("96k")
                  - 'preset': str - Fast encoding preset ("fast")
                - 'advanced_options': Dict - Comprehensive settings
                  - 'video_codec': str - Advanced codec ("libx265")
                  - 'audio_codec': str - Modern audio codec ("opus")
                  - 'resolution': str - Target resolution ("1920x1080")
                  - 'framerate': str - Frame rate ("30")
                  - 'crf': int - Quality setting (23)
                  - 'preset': str - Encoding preset ("medium")
                  
        Examples:
            >>> factory = FFmpegWrapperTestDataFactory()
            >>> kwargs_variations = factory.create_conversion_kwargs_variations()
            >>> kwargs_variations['quality_focused']['crf']
            18
        """
        return {
            "empty_kwargs": {},
            "video_only": {
                "video_codec": "libx264",
                "video_bitrate": "2M"
            },
            "audio_only": {
                "audio_codec": "aac",
                "audio_bitrate": "192k"
            },
            "quality_focused": {
                "crf": 18,
                "preset": "slow"
            },
            "size_focused": {
                "video_bitrate": "500k",
                "audio_bitrate": "96k",
                "preset": "fast"
            },
            "advanced_options": {
                "video_codec": "libx265",
                "audio_codec": "opus",
                "resolution": "1920x1080",
                "framerate": "30",
                "crf": 23,
                "preset": "medium"
            }
        }
