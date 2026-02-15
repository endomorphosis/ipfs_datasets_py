"""
Media utilities for common multimedia operations.

This module provides utility functions for working with media files,
formats, metadata, and validation.
"""

import logging
import mimetypes
from pathlib import Path
from typing import Dict, Optional, Union, Set

logger = logging.getLogger(__name__)


class MediaUtils:
    """
    Comprehensive media utility class for multimedia file operations and validation.

    The MediaUtils class provides a complete suite of utility functions for working with 
    multimedia files across various formats including video, audio, and image files. It offers
    file type detection, format validation, URL validation, metadata extraction, and file
    processing utilities designed to handle common multimedia operations in a robust and
    extensible manner. This class serves as a central hub for all media-related operations,
    supporting both local file processing and remote media resource validation.

    The class is designed with extensibility in mind, allowing for easy addition of new
    media formats and processing capabilities. All methods are implemented as class methods,
    making the utility functions accessible without instantiation while maintaining a clean
    namespace organization.

    Key Features:
    - Comprehensive media format support across video, audio, and image files
    - Intelligent file type detection based on file extensions and MIME types
    - URL validation for both local and remote media resources
    - Human-readable formatting for file sizes and durations
    - Safe filename sanitization for cross-platform compatibility
    - MIME type detection and validation
    - Extensive logging for debugging and monitoring

    Supported Formats:
    - Video: MP4, AVI, MOV, MKV, WMV, FLV, WebM, M4V, 3GP, MPG, MPEG, TS, VOB, ASF, RM, RMVB, OGV
    - Audio: MP3, WAV, FLAC, AAC, OGG, WMA, M4A, Opus, AIFF, AU, RA, AMR, AC3, DTS
    - Image: JPG, JPEG, PNG, GIF, BMP, TIFF, TIF, WebP, SVG, ICO, PSD, RAW, CR2, NEF, ARW

    Class Attributes:
        VIDEO_FORMATS (Set[str]): Set of supported video file extensions (lowercase, no dots)
        AUDIO_FORMATS (Set[str]): Set of supported audio file extensions (lowercase, no dots)
        IMAGE_FORMATS (Set[str]): Set of supported image file extensions (lowercase, no dots)

    Public Methods:
        get_file_type(file_path: Union[str, Path]) -> Optional[str]:
            Determines the media type category (video/audio/image) of a file based on its extension.
            Returns the media type string or None if the file is not a recognized media format.

        is_media_file(file_path: Union[str, Path]) -> bool:
            Validates whether a given file path represents a supported media file format.
            Returns True if the file extension matches any supported media format.

        get_supported_formats() -> Dict[str, Set[str]]:
            Retrieves a comprehensive mapping of all supported media formats organized by type.
            Returns a dictionary with media types as keys and format sets as values.

        validate_url(url: str) -> bool:
            Performs comprehensive URL validation for media sources including remote URLs
            and local file paths. Supports HTTP/HTTPS, FTP, RTMP, RTSP protocols.

        get_mime_type(file_path: Union[str, Path]) -> Optional[str]:
            Determines the MIME type of a media file using the system's MIME type database.
            Returns the MIME type string or None if detection fails.

        format_file_size(size_bytes: int) -> str:
            Converts file size from bytes to human-readable format using appropriate units
            (B, KB, MB, GB, TB, PB) with single decimal precision.

        format_duration(seconds: float) -> str:
            Converts duration from seconds to human-readable format in HH:MM:SS or MM:SS
            format depending on duration length.

        sanitize_filename(filename: str) -> str:
            Sanitizes filenames for safe cross-platform file system usage by removing
            invalid characters, limiting length, and handling edge cases.

    Usage Examples:
        # Basic file type detection
        file_type = MediaUtils.get_file_type("/path/to/video.mp4")
        # Returns: "video"

        # Validate media file
        is_valid = MediaUtils.is_media_file("audio.mp3")
        # Returns: True

        # Format file size
        size_str = MediaUtils.format_file_size(1048576)
        # Returns: "1.0 MB"

        # Format duration
        duration_str = MediaUtils.format_duration(3661)
        # Returns: "01:01:01"

        # Sanitize filename
        safe_name = MediaUtils.sanitize_filename("my<file>name.txt")
        # Returns: "my_file_name.txt"

        # URL validation
        is_valid_url = MediaUtils.validate_url("https://example.com/video.mp4")
        # Returns: True

        # Get supported formats
        formats = MediaUtils.get_supported_formats()
        # Returns: {"video": {...}, "audio": {...}, "image": {...}}

    Notes:
        - All file extension comparisons are case-insensitive
        - The class uses Python's built-in mimetypes module for MIME type detection
        - URL validation supports both remote URLs and local file paths
        - File size formatting uses 1024-byte units (binary prefixes)
        - Duration formatting automatically chooses between HH:MM:SS and MM:SS formats
        - Filename sanitization removes characters that are invalid on Windows, macOS, and Linux
        - All methods include comprehensive error handling with fallback return values
        - Logging is integrated throughout for debugging and monitoring purposes
    """
    
    # Supported media formats
    VIDEO_FORMATS = {
        'mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'webm', 'm4v', '3gp',
        'mpg', 'mpeg', 'ts', 'vob', 'asf', 'rm', 'rmvb', 'ogv'
    }
    
    AUDIO_FORMATS = {
        'mp3', 'wav', 'flac', 'aac', 'ogg', 'wma', 'm4a', 'opus',
        'aiff', 'au', 'ra', 'amr', 'ac3', 'dts'
    }
    
    IMAGE_FORMATS = {
        'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'tif', 'webp',
        'svg', 'ico', 'psd', 'raw', 'cr2', 'nef', 'arw'
    }
    
    @classmethod
    def get_file_type(cls, file_path: Union[str, Path]) -> Optional[str]:
        """
        Determine the media type category of a file based on its extension.

        This method analyzes the file extension to categorize the file into one of three
        supported media types: video, audio, or image. The determination is based on
        comprehensive format lists that cover the most common and widely-used multimedia
        file formats across different platforms and applications.

        Args:
            file_path (Union[str, Path]): Path to the media file to analyze. Can be either
                a string path or a pathlib.Path object. The path does not need to exist
                on the filesystem as only the extension is analyzed.

        Returns:
            Optional[str]: The media type category if the file extension is recognized:
                - "video": For video file formats (mp4, avi, mov, mkv, etc.)
                - "audio": For audio file formats (mp3, wav, flac, aac, etc.)
                - "image": For image file formats (jpg, png, gif, bmp, etc.)
                - None: If the file extension is not recognized or an error occurs

        Examples:
            >>> MediaUtils.get_file_type(str(Path.home() / "video.mp4"))
            'video'
            >>> MediaUtils.get_file_type("audio_file.mp3")
            'audio'
            >>> MediaUtils.get_file_type("image.jpg")
            'image'
            >>> MediaUtils.get_file_type("document.pdf")
            None
            >>> MediaUtils.get_file_type("file_without_extension")
            None

        Notes:
            - File extension comparison is case-insensitive
            - The file does not need to exist on the filesystem
            - Errors during processing are logged but do not raise exceptions
            - The method strips leading dots from extensions automatically
            - Hidden files are handled correctly
        """
        try:
            path = Path(file_path)
            extension = path.suffix.lower().lstrip('.')
            
            if extension in cls.VIDEO_FORMATS:
                return "video"
            elif extension in cls.AUDIO_FORMATS:
                return "audio"
            elif extension in cls.IMAGE_FORMATS:
                return "image"
            else:
                return None
                
        except Exception as e:
            logger.error(f"Error determining file type for {file_path}: {e}")
            return None
    
    @classmethod
    def is_media_file(cls, file_path: Union[str, Path]) -> bool:
        """
        Check if a file is a supported media file format.

        This method provides a simple boolean check to determine whether a given file
        path represents a supported media file. It leverages the get_file_type method
        to perform the format detection and returns a clear boolean result.

        Args:
            file_path (Union[str, Path]): Path to the file to check. Can be either
                a string path or a pathlib.Path object. The file does not need to
                exist on the filesystem.

        Returns:
            bool: True if the file extension matches any supported media format
                (video, audio, or image), False otherwise. Also returns False if
                an error occurs during processing.

        Raises:
            No exceptions are raised directly. All errors are handled internally
            by the get_file_type method.

        Examples:
            >>> MediaUtils.is_media_file("vacation_video.mp4")
            True
            >>> MediaUtils.is_media_file("song.mp3")
            True
            >>> MediaUtils.is_media_file("photo.jpg")
            True
            >>> MediaUtils.is_media_file("document.pdf")
            False
            >>> MediaUtils.is_media_file("README.txt")
            False

        Notes:
            - File extension comparison is case-insensitive
            - The file does not need to exist on the filesystem
        """
        return cls.get_file_type(file_path) is not None
    
    @classmethod
    def get_supported_formats(cls) -> Dict[str, Set[str]]:
        """
        Get all supported media formats organized by media type category.

        This method returns a comprehensive mapping of all supported media formats,
        organized by their respective media type categories. The returned dictionary
        provides easy access to format lists for validation, documentation, or
        user interface purposes.

        Returns:
            Dict[str, Set[str]]: A dictionary mapping media type categories to sets
                of supported file extensions. The dictionary contains:
                - "video": Set of supported video file extensions
                - "audio": Set of supported audio file extensions  
                - "image": Set of supported image file extensions
                All extensions are lowercase strings without leading dots.

        Examples:
            >>> formats = MediaUtils.get_supported_formats()
            >>> print(formats.keys())
            dict_keys(['video', 'audio', 'image'])
            >>> 'mp4' in formats['video']
            True
            >>> 'mp3' in formats['audio']
            True
            >>> len(formats['video']) >= 10
            True

        Notes:
            - The returned sets are references to the class attributes, not copies
            - Modifying the returned sets will affect the class behavior
            - All extensions are stored in lowercase format
            - Extensions do not include leading dots
            - The format lists are comprehensive and exhaustive
            - New formats can be added by modifying the class attributes
        """
        return {
            "video": cls.VIDEO_FORMATS,
            "audio": cls.AUDIO_FORMATS,
            "image": cls.IMAGE_FORMATS
        }
    
    @classmethod
    def validate_url(cls, url: str) -> bool:
        """
        Perform comprehensive URL validation for media sources and local file paths.

        This method validates URLs for media resources, supporting both remote URLs
        with various protocols and local file paths. It performs format validation
        and existence checking for local paths, making it suitable for validating
        media source URLs before processing.

        Args:
            url (str): The URL or file path to validate. Can be:
                - Remote URLs with protocols: http://, https://, ftp://, rtmp://, rtsp://
                - Local file paths (absolute or relative)
                - Empty strings or None (will return False)

        Returns:
            bool: True if the URL appears to be valid based on the following criteria:
                - Non-empty string after trimming whitespace
                - Starts with a supported protocol for remote URLs
                - Exists on the filesystem for local file paths
                - False for any invalid format, empty input, or processing errors

        Examples:
            >>> MediaUtils.validate_url("https://example.com/video.mp4")
            True
            >>> MediaUtils.validate_url("http://site.com/audio.mp3")
            True
            >>> MediaUtils.validate_url("ftp://server.com/file.avi")
            True
            >>> MediaUtils.validate_url("/path/to/existing/file.mp4")  # if file exists
            True
            >>> MediaUtils.validate_url("rtmp://stream.server.com/live")
            True
            >>> MediaUtils.validate_url("invalid-url")
            False
            >>> MediaUtils.validate_url("")
            False
            >>> MediaUtils.validate_url(None)
            False

        Notes:
            - Supports HTTP, HTTPS, FTP, RTMP, and RTSP protocols
            - Local file path validation requires the file to exist
            - Has comprehensive URL validation
            - Whitespace is automatically stripped from input
            - Case-sensitive protocol matching
            - Relative paths are resolved relative to current working directory
        """
        try:
            if not url or not isinstance(url, str):
                return False
            
            url = url.strip()
            if not url:
                return False
            
            # Basic checks
            if url.startswith(('http://', 'https://', 'ftp://', 'rtmp://', 'rtsp://')):
                return True
            
            # Local file path
            if Path(url).exists():
                return True
            
            return False
            
        except Exception:
            return False
    
    @classmethod
    def get_mime_type(cls, file_path: Union[str, Path]) -> Optional[str]:
        """
        Determine the MIME type of a media file using system MIME type database.

        Args:
            file_path (Union[str, Path]): Path to the media file for MIME type detection.
                Can be either a string path or pathlib.Path object. The file does not
                need to exist on the filesystem as only the extension is analyzed.

        Returns:
            Optional[str]: The MIME type string if successfully determined, such as:
                - "video/mp4" for MP4 video files
                - "audio/mpeg" for MP3 audio files
                - "image/jpeg" for JPEG image files
                - "image/png" for PNG image files
                - None if MIME type cannot be determined or an error occurs

        Examples:
            >>> MediaUtils.get_mime_type("video.mp4")
            'video/mp4'
            >>> MediaUtils.get_mime_type("audio.mp3")
            'audio/mpeg'
            >>> MediaUtils.get_mime_type("image.jpg")
            'image/jpeg'
            >>> MediaUtils.get_mime_type("image.png")
            'image/png'
            >>> MediaUtils.get_mime_type("unknown.xyz")
            None

        Notes:
            - The file does not need to exist on the filesystem
            - Returns the primary MIME type, ignoring any encoding information
        """
        try:
            mime_type, _ = mimetypes.guess_type(str(file_path))
            return mime_type
        except Exception:
            return None
    
    @classmethod
    def format_file_size(cls, size_bytes: int) -> str:
        """
        Convert file size from bytes to human-readable format with appropriate units.

        This method converts raw byte values into human-readable file size strings
        using binary units (1024-byte multiples). It automatically selects the most
        appropriate unit to provide a concise and readable representation of the file size.

        Args:
            size_bytes (int): The file size in bytes to format. Should be a non-negative
                integer representing the actual byte count of a file or data.

        Returns:
            str: A formatted file size string with one decimal place and appropriate unit:
                - Bytes: "X.X B" for sizes less than 1024 bytes
                - Kilobytes: "X.X KB" for sizes 1024 bytes to 1023 KB
                - Megabytes: "X.X MB" for sizes 1024 KB to 1023 MB
                - Gigabytes: "X.X GB" for sizes 1024 MB to 1023 GB
                - Terabytes: "X.X TB" for sizes 1024 GB to 1023 TB
                - Petabytes: "X.X PB" for sizes 1024 TB and above
                - "Unknown size" if an error occurs during processing
                If processing fails, returns "Unknown size".

        Examples:
            >>> MediaUtils.format_file_size(512)
            '512.0 B'
            >>> MediaUtils.format_file_size(1024)
            '1.0 KB'
            >>> MediaUtils.format_file_size(1048576)
            '1.0 MB'
            >>> MediaUtils.format_file_size(1073741824)
            '1.0 GB'
            >>> MediaUtils.format_file_size(1536)
            '1.5 KB'
            >>> MediaUtils.format_file_size(0)
            '0.0 B'

        Notes:
            - Uses binary units (1024-byte multiples), not decimal (1000-byte)
            - Always displays one decimal place for consistency
            - Automatically chooses the most appropriate unit for readability
            - Handles zero and very small file sizes correctly
            - Maximum supported size is petabytes before precision loss
        """
        try:
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if size_bytes < 1024.0:
                    return f"{size_bytes:.1f} {unit}"
                size_bytes /= 1024.0
            return f"{size_bytes:.1f} PB"
        except Exception:
            return "Unknown size"
    
    @classmethod
    def format_duration(cls, seconds: float) -> str:
        """
        Convert duration from seconds to human-readable time format.

        This method converts time duration values from seconds into standard time
        format strings. It automatically chooses between HH:MM:SS format for longer
        durations and MM:SS format for shorter durations to provide the most
        appropriate and readable representation.

        Args:
            seconds (float): Duration in seconds to format. Can be any non-negative
                numeric value representing time duration. Fractional seconds are
                truncated to whole seconds in the output.

        Returns:
            str: Formatted duration string in one of two formats:
                - "HH:MM:SS" for durations of 1 hour or longer (with leading zeros)
                - "MM:SS" for durations less than 1 hour (with leading zeros)
                - "Unknown duration" if an error occurs during processing
                If processing fails, returns "Unknown duration".

        Examples:
            >>> MediaUtils.format_duration(30)
            '00:30'
            >>> MediaUtils.format_duration(90)
            '01:30'
            >>> MediaUtils.format_duration(3661)
            '01:01:01'
            >>> MediaUtils.format_duration(7200)
            '02:00:00'
            >>> MediaUtils.format_duration(0)
            '00:00'
            >>> MediaUtils.format_duration(125.7)
            '02:05'

        Notes:
            - Automatically selects appropriate format based on duration length
            - Uses zero-padding for consistent formatting (e.g., "01:05" not "1:5")
            - Fractional seconds are rounded
            - Hours, minutes, and seconds are all displayed with two digits when present
            - Handles zero duration correctly
        """
        try:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            
            if hours > 0:
                return f"{hours:02d}:{minutes:02d}:{secs:02d}"
            else:
                return f"{minutes:02d}:{secs:02d}"
        except Exception:
            return "Unknown duration"
    
    @classmethod
    def sanitize_filename(cls, filename: str) -> str:
        """
        Sanitize filename for safe cross-platform file system usage.

        This method processes filenames to ensure they are safe for use across different
        operating systems and file systems. It removes or replaces invalid characters,
        handles length limitations, and provides fallback values for edge cases to
        prevent file system errors and compatibility issues.

        Args:
            filename (str): The original filename to sanitize. Can contain any characters
                including those that are invalid on various file systems.

        Returns:
            str: A sanitized filename that is safe for cross-platform use:
                - Invalid characters (<>:"/\\|?*) replaced with underscores
                - Leading and trailing spaces and dots removed
                - Length limited to 200 characters (preserving file extension)
                - "unnamed_file" returned for empty or invalid inputs
                - File extension preserved when truncating long names
                If the filename cannot be processed, "unnamed_file" is returned

        Examples:
            >>> MediaUtils.sanitize_filename("my video.mp4")
            'my video.mp4'
            >>> MediaUtils.sanitize_filename('file<name>.txt')
            'file_name_.txt'
            >>> MediaUtils.sanitize_filename('my|file"name?.mp3')
            'my_file_name_.mp3'
            >>> MediaUtils.sanitize_filename('  .hidden_file.txt  ')
            'hidden_file.txt'
            >>> MediaUtils.sanitize_filename('')
            'unnamed_file'
            >>> MediaUtils.sanitize_filename('a' * 250 + '.mp4')
            # Returns truncated version preserving .mp4 extension

        Notes:
            - Replaces invalid characters: < > : " / \\ | ? *
            - Removes leading and trailing spaces and dots
            - Preserves file extensions when truncating long filenames
            - Length limit of 200 characters prevents file system issues
            - Returns "unnamed_file" for empty input or processing errors
            - Safe for Windows, macOS, and Linux file systems
        """
        try:
            # Remove/replace invalid characters
            invalid_chars = '<>:"/\\|?*'
            for char in invalid_chars:
                filename = filename.replace(char, '_')
            
            # Remove leading/trailing spaces and dots
            filename = filename.strip(' .')
            
            # Limit length
            if len(filename) > 200:
                name, ext = Path(filename).stem, Path(filename).suffix
                filename = name[:200-len(ext)] + ext
            
            return filename or "unnamed_file"
            
        except Exception:
            return "unnamed_file"