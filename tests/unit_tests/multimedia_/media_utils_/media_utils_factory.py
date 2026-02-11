#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test data factory for generating MediaUtils instances and test data.

Provides methods to create valid baseline data, invalid variations, and edge cases
for comprehensive testing of the MediaUtils class validation logic.
"""
from typing import Dict, Any, List, Set, Union
from pathlib import Path

from ipfs_datasets_py.data_transformation.multimedia.media_utils import MediaUtils


class MediaUtilsTestDataFactory:
    """
    Test data factory for generating MediaUtils instances and test data.
    
    Provides methods to create valid baseline data, invalid variations, and edge cases
    for comprehensive testing of the MediaUtils class validation logic.
    
    Examples:
        >>> # Create a MediaUtils instance for testing
        >>> utils = MediaUtilsTestDataFactory.create_utils_instance()
        >>> 
        >>> # Get valid file paths for testing
        >>> file_paths = MediaUtilsTestDataFactory.create_valid_file_paths()
        >>> video_path = file_paths['video_mp4']  # "/path/to/video.mp4"
        >>> 
        >>> # Get test data for file size formatting
        >>> sizes = MediaUtilsTestDataFactory.create_file_size_test_data()
        >>> megabyte_size = sizes['megabytes']  # 1048576
        >>> 
        >>> # Get filename sanitization test cases
        >>> filenames = MediaUtilsTestDataFactory.create_filename_test_data()
        >>> invalid_name = filenames['invalid_chars']  # "file<name>with:invalid|chars?.mp4"
    """

    @classmethod
    def create_valid_file_paths(cls) -> Dict[str, str]:
        """
        Create dictionary of valid file paths for different media types.
        
        Returns:
            Dict[str, str]: Dictionary with valid file paths for testing.
                Keys:
                - 'video_mp4': str - Path to MP4 video file
                - 'video_avi': str - Path to AVI video file  
                - 'video_mkv': str - Path to MKV video file
                - 'audio_mp3': str - Path to MP3 audio file
                - 'audio_wav': str - Path to WAV audio file
                - 'audio_flac': str - Path to FLAC audio file
                - 'image_jpg': str - Path to JPEG image file
                - 'image_png': str - Path to PNG image file
                - 'image_gif': str - Path to GIF image file
                - 'non_media': str - Path to non-media file (PDF)
        """
        return {
            "video_mp4": "/path/to/video.mp4",
            "video_avi": "/path/to/video.avi",
            "video_mkv": "/path/to/video.mkv",
            "audio_mp3": "/path/to/audio.mp3",
            "audio_wav": "/path/to/audio.wav",
            "audio_flac": "/path/to/audio.flac",
            "image_jpg": "/path/to/image.jpg",
            "image_png": "/path/to/image.png",
            "image_gif": "/path/to/image.gif",
            "non_media": "/path/to/document.pdf"
        }

    @classmethod
    def create_valid_urls(cls) -> Dict[str, str]:
        """
        Create dictionary of valid URLs for different protocols.
        
        Returns:
            Dict[str, str]: Dictionary with valid URLs for testing.
                Keys:
                - 'http_video': str - HTTP URL pointing to video file
                - 'https_video': str - HTTPS URL pointing to video file
                - 'ftp_file': str - FTP URL pointing to media file
                - 'rtmp_stream': str - RTMP streaming URL
                - 'rtsp_stream': str - RTSP streaming URL  
                - 'local_file': str - Local file path
        """
        return {
            "http_video": "http://example.com/video.mp4",
            "https_video": "https://example.com/video.mp4",
            "ftp_file": "ftp://server.com/file.avi",
            "rtmp_stream": "rtmp://stream.server.com/live",
            "rtsp_stream": "rtsp://camera.server.com/stream",
            "local_file": "/home/user/video.mp4"
        }

    @classmethod
    def create_invalid_urls(cls) -> Dict[str, str]:
        """
        Create dictionary of invalid URLs for testing.
        
        Returns:
            Dict[str, str]: Dictionary with invalid URLs for testing.
                Keys:
                - 'empty': str - Empty string URL
                - 'none_string': None - None value instead of string
                - 'invalid_protocol': str - URL with unsupported protocol
                - 'malformed': str - Malformed URL string
                - 'whitespace_only': str - URL with only whitespace
                - 'missing_extension': str - URL without file extension
        """
        return {
            "empty": "",
            "none_string": None,
            "invalid_protocol": "invalid://example.com/video.mp4",
            "malformed": "not-a-url",
            "whitespace_only": "   ",
            "missing_extension": "https://example.com/video"
        }

    @classmethod
    def create_file_size_test_data(cls) -> Dict[str, int]:
        """
        Create dictionary of file sizes in bytes for testing formatting.
        
        Returns:
            Dict[str, int]: Dictionary with file sizes for testing.
                Keys:
                - 'zero': int - Zero byte file size
                - 'bytes': int - Small file size in bytes (512)
                - 'kilobytes': int - File size in kilobytes (1024 bytes)
                - 'megabytes': int - File size in megabytes (1048576 bytes)
                - 'gigabytes': int - File size in gigabytes (1073741824 bytes)
                - 'terabytes': int - File size in terabytes (1099511627776 bytes)
                - 'large': int - Very large file size (1 petabyte)
        """
        return {
            "zero": 0,
            "bytes": 512,
            "kilobytes": 1024,
            "megabytes": 1048576,
            "gigabytes": 1073741824,
            "terabytes": 1099511627776,
            "large": 1125899906842624  # 1 PB
        }

    @classmethod
    def create_duration_test_data(cls) -> Dict[str, float]:
        """
        Create dictionary of durations in seconds for testing formatting.
        
        Returns:
            Dict[str, float]: Dictionary with durations for testing.
                Keys:
                - 'zero': float - Zero duration (0.0 seconds)
                - 'short': float - Short duration (30.0 seconds)
                - 'minute_half': float - One and half minutes (90.0 seconds)
                - 'hour': float - One hour duration (3600.0 seconds)
                - 'hour_minute_second': float - 1 hour, 1 minute, 1 second (3661.0 seconds)
                - 'two_hours': float - Two hour duration (7200.0 seconds)
                - 'fractional': float - Duration with fractional seconds (125.7 seconds)
        """
        return {
            "zero": 0.0,
            "short": 30.0,
            "minute_half": 90.0,
            "hour": 3600.0,
            "hour_minute_second": 3661.0,
            "two_hours": 7200.0,
            "fractional": 125.7
        }

    @classmethod
    def create_filename_test_data(cls) -> Dict[str, str]:
        """
        Create dictionary of filenames for sanitization testing.
        
        Returns:
            Dict[str, str]: Dictionary with filenames for testing.
                Keys:
                - 'valid': str - Normal valid filename
                - 'with_spaces': str - Filename containing spaces
                - 'invalid_chars': str - Filename with invalid characters (<>:|?*)
                - 'leading_trailing_spaces': str - Filename with leading/trailing spaces
                - 'leading_trailing_dots': str - Filename with leading/trailing dots
                - 'empty': str - Empty filename string
                - 'very_long': str - Extremely long filename (250+ characters)
                - 'unicode': str - Filename with Unicode characters
                - 'special_chars': str - Filename with special characters (@#$%^&*()_+)
        """
        return {
            "valid": "normal_file.mp4",
            "with_spaces": "my video file.mp4",
            "invalid_chars": "file<name>with:invalid|chars?.mp4",
            "leading_trailing_spaces": "  file_name.mp4  ",
            "leading_trailing_dots": "..file_name.mp4..",
            "empty": "",
            "very_long": "a" * 250 + ".mp4",
            "unicode": "файл_видео.mp4",
            "special_chars": "file@#$%^&*()_+name.mp4"
        }

    @classmethod
    def create_expected_sanitized_filenames(cls) -> Dict[str, str]:
        """
        Create dictionary of expected sanitized filenames.
        
        Returns:
            Dict[str, str]: Dictionary with expected sanitized results.
                Keys:
                - 'valid': str - Expected result for valid filename (unchanged)
                - 'with_spaces': str - Expected result for filename with spaces (unchanged)
                - 'invalid_chars': str - Expected result with invalid chars replaced by underscores
                - 'leading_trailing_spaces': str - Expected result with spaces/dots trimmed
                - 'leading_trailing_dots': str - Expected result with leading/trailing dots removed
                - 'empty': str - Expected result for empty filename ("unnamed_file")
                - 'very_long': str - Expected result with filename truncated to 200 chars
                - 'unicode': str - Expected result for Unicode filename (preserved)
                - 'special_chars': str - Expected result with some special chars preserved
        """
        return {
            "valid": "normal_file.mp4",
            "with_spaces": "my video file.mp4",
            "invalid_chars": "file_name_with_invalid_chars_.mp4",
            "leading_trailing_spaces": "file_name.mp4",
            "leading_trailing_dots": "file_name.mp4",
            "empty": "unnamed_file",
            "very_long": "a" * 196 + ".mp4",  # 200 - 4 for extension
            "unicode": "файл_видео.mp4",
            "special_chars": "file_#$%^&_()__name.mp4"
        }

    @classmethod
    def create_mime_type_expectations(cls) -> Dict[str, str]:
        """
        Create dictionary of file extensions and their expected MIME types.
        
        Returns:
            Dict[str, str]: Dictionary mapping file paths to expected MIME types.
                Keys:
                - 'video.mp4': str - Expected MIME type for MP4 files ("video/mp4")
                - 'audio.mp3': str - Expected MIME type for MP3 files ("audio/mpeg")
                - 'image.jpg': str - Expected MIME type for JPEG files ("image/jpeg")
                - 'image.png': str - Expected MIME type for PNG files ("image/png")
                - 'video.avi': str - Expected MIME type for AVI files ("video/x-msvideo")
                - 'audio.wav': str - Expected MIME type for WAV files ("audio/wav")
        """
        return {
            "video.mp4": "video/mp4",
            "audio.mp3": "audio/mpeg",
            "image.jpg": "image/jpeg",
            "image.png": "image/png",
            "video.avi": "video/x-msvideo",
            "audio.wav": "audio/wav"
        }

    @classmethod
    def create_supported_formats_data(cls) -> Dict[str, Set[str]]:
        """
        Create the expected supported formats data structure.
        
        Returns:
            Dict[str, Set[str]]: Dictionary with supported formats by media type.
                Keys:
                - 'video': Set[str] - Set of supported video file extensions
                - 'audio': Set[str] - Set of supported audio file extensions  
                - 'image': Set[str] - Set of supported image file extensions
        """
        return {
            "video": {
                'mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'webm', 'm4v', '3gp',
                'mpg', 'mpeg', 'ts', 'vob', 'asf', 'rm', 'rmvb', 'ogv'
            },
            "audio": {
                'mp3', 'wav', 'flac', 'aac', 'ogg', 'wma', 'm4a', 'opus',
                'aiff', 'au', 'ra', 'amr', 'ac3', 'dts'
            },
            "image": {
                'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'tif', 'webp',
                'svg', 'ico', 'psd', 'raw', 'cr2', 'nef', 'arw'
            }
        }

    @classmethod
    def create_file_type_test_cases(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create test cases for file type detection.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with file paths and expected types.
                Keys:
                - 'video_mp4': Dict - Test case for MP4 video file
                  - 'path': str - File path to test
                  - 'expected_type': str - Expected media type ("video")
                - 'video_avi': Dict - Test case for AVI video file (case insensitive)
                - 'audio_mp3': Dict - Test case for MP3 audio file
                - 'audio_flac': Dict - Test case for FLAC audio file  
                - 'image_jpg': Dict - Test case for JPEG image file
                - 'image_png': Dict - Test case for PNG image file
                - 'non_media': Dict - Test case for non-media file (expected_type: None)
                - 'no_extension': Dict - Test case for file without extension
                - 'hidden_file': Dict - Test case for hidden media file
        """
        return {
            "video_mp4": {"path": "movie.mp4", "expected_type": "video"},
            "video_avi": {"path": "clip.AVI", "expected_type": "video"},  # Test case insensitive
            "audio_mp3": {"path": "song.mp3", "expected_type": "audio"},
            "audio_flac": {"path": "track.FLAC", "expected_type": "audio"},
            "image_jpg": {"path": "photo.jpg", "expected_type": "image"},
            "image_png": {"path": "picture.PNG", "expected_type": "image"},
            "non_media": {"path": "document.pdf", "expected_type": None},
            "no_extension": {"path": "filename", "expected_type": None},
            "hidden_file": {"path": ".hidden.mp4", "expected_type": "video"}
        }

    @classmethod
    def create_media_validation_test_cases(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create test cases for media file validation.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with file paths and expected validation results.
                Keys:
                - 'valid_video': Dict - Test case for valid video file
                  - 'path': str - File path to validate
                  - 'is_media': bool - Expected validation result (True)
                - 'valid_audio': Dict - Test case for valid audio file
                - 'valid_image': Dict - Test case for valid image file
                - 'invalid_document': Dict - Test case for non-media document
                - 'invalid_text': Dict - Test case for text file
                - 'no_extension': Dict - Test case for file without extension
                - 'case_insensitive': Dict - Test case for uppercase extension
        """
        return {
            "valid_video": {"path": "video.mp4", "is_media": True},
            "valid_audio": {"path": "audio.mp3", "is_media": True},
            "valid_image": {"path": "image.jpg", "is_media": True},
            "invalid_document": {"path": "doc.pdf", "is_media": False},
            "invalid_text": {"path": "file.txt", "is_media": False},
            "no_extension": {"path": "filename", "is_media": False},
            "case_insensitive": {"path": "VIDEO.MP4", "is_media": True}
        }

    @classmethod
    def create_utils_instance(cls) -> MediaUtils:
        """
        Create a MediaUtils instance for testing.
        
        Returns:
            MediaUtils: MediaUtils instance.
        """
        return MediaUtils()

    @classmethod
    def create_edge_case_data(cls) -> Dict[str, Any]:
        """
        Create edge case data for comprehensive testing.
        
        Returns:
            Dict[str, Any]: Dictionary with edge case test data.
                Keys:
                - 'empty_strings': List[str] - Various empty string representations
                - 'none_values': List[None] - None values for testing
                - 'unicode_paths': List[str] - File paths with Unicode characters
                - 'extreme_sizes': List[int] - Edge case file sizes (0, 1, max int)
                - 'extreme_durations': List[float] - Edge case durations 
                - 'path_objects': List[Path] - pathlib.Path objects for testing
                - 'malformed_extensions': List[str] - Files with malformed extensions
                - 'very_long_extensions': List[str] - Files with extremely long extensions
        """
        return {
            "empty_strings": ["", "   ", "\t\n"],
            "none_values": [None],
            "unicode_paths": ["тест.mp4", "测试.avi", "🎬movie.mp4"],
            "extreme_sizes": [0, 1, 2**63 - 1],  # Edge file sizes
            "extreme_durations": [0.0, 0.1, 999999.9],  # Edge durations
            "path_objects": [Path("test.mp4"), Path("/absolute/path.avi")],
            "malformed_extensions": [".mp4.", "file..mp4", "test."],
            "very_long_extensions": ["file." + "a" * 100]
        }
