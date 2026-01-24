"""
Media processor that coordinates between different multimedia libraries.

This module provides a unified interface for processing multimedia content
using various backends like FFmpeg and yt-dlp.
"""
from __future__ import annotations
import anyio
import logging
from typing import Dict, Any, Optional
from pathlib import Path

try:
    from pydantic import BaseModel, Field, NonNegativeFloat, NonNegativeInt, FilePath
except ImportError:
    raise ImportError("pydantic required for MediaProcessor. Please install it with 'pip install pydantic'.")


from ipfs_datasets_py.multimedia.ytdlp_wrapper import YtDlpWrapper, YTDLP_AVAILABLE
from ipfs_datasets_py.multimedia.ffmpeg_wrapper import FFmpegWrapper, FFMPEG_AVAILABLE


class MediaProcessorMetadata(BaseModel):
    """
    Metadata model for MediaProcessor operations.

    Attributes:
        output_path (str): Path to the output media file.
        filesize (NonNegativeInt): Size of the media file in bytes.
        format (str): Format/container type of the media file.
        title (str): Title of the media content. Defaults to "[Unknown Title]".
        duration (NonNegativeFloat): Duration of the media in seconds. Defaults to 0.0.
        resolution (str): Resolution of the media (e.g., "1920x1080"). Defaults to "unknown".
        converted_path (Optional[FilePath]): Path to converted file if conversion was performed. Defaults to None.
        conversion_result (Optional[Dict[str, Any]]): Result metadata from conversion operation. Defaults to None.
    """
    output_path: str
    filesize: NonNegativeInt
    format: str
    title: str = "[Unknown Title]"
    duration: NonNegativeFloat = 0.0
    resolution: str = "unknown"
    converted_path: Optional[FilePath] = None  # Path to converted file if applicable
    conversion_result: Optional[Dict[str, Any]] = None  # Result of conversion operation if applicable


CORE_METADATA_FIELDS = [
    "output_path", "title", "duration", "filesize", "format", "resolution"
]

OPTIONAL_METADATA_FIELDS = [
    "converted_path", "conversion_result"
]

ALL_METADATA_FIELDS = CORE_METADATA_FIELDS + OPTIONAL_METADATA_FIELDS

# Weighted completeness: core fields = 0.85 weight, optional fields = 0.15 weight
CORE_WEIGHT = 0.85
OPTIONAL_WEIGHT = 0.15
COMPLETENESS_THRESHOLD = 0.90  # Reduced from 0.98 for practical deployment scenarios

# Metadata field defaults for graceful degradation
METADATA_DEFAULTS = {
    "title": "[Unknown Title]",  # Fallback when both video title and filename are unavailable
    "duration": 0.0,             # Zero duration for streams/unknown
    "resolution": "unknown",     # String format for undetectable resolution
    "converted_path": None,      # Explicit None when no conversion
    "conversion_result": None    # Explicit None when no conversion
}



def make_media_processor(
    default_output_dir: Optional[str|Path] = None,
    enable_logging: bool = True,
    logger: logging.Logger = logging.getLogger(__name__),
    ytdlp: Optional[YtDlpWrapper] = None,
    ffmpeg: Optional[FFmpegWrapper] = None
    ) -> 'MediaProcessor':
    """
    Factory function to create a MediaProcessor instance.

    Args:
        default_output_dir (Optional[str], optional): Default directory path for output files.
            If not provided, defaults to the current working directory. The directory will
            be created if it doesn't exist. Defaults to None.
        enable_logging (bool, optional): Enable detailed logging for debugging and monitoring.
            When True, logs initialization status, operation progress, and error details.
            Defaults to True.

    Returns:
        MediaProcessor: Configured MediaProcessor instance.
    """
    input_dict = {
        "default_output_dir": default_output_dir,
        "enable_logging": enable_logging,
        "logger": logger,
        "ytdlp": ytdlp,
        "ffmpeg": ffmpeg
    }
    if input_dict["ytdlp"] is None and YTDLP_AVAILABLE:
        input_dict["ytdlp"] = YtDlpWrapper(default_output_dir, enable_logging)

    if input_dict["ffmpeg"] is None and FFMPEG_AVAILABLE:
        input_dict["ffmpeg"] = FFmpegWrapper(default_output_dir, enable_logging)

    return MediaProcessor(**input_dict)


class MediaProcessor:
    """
    Media Processor for Multimedia Operations

    The MediaProcessor class provides a comprehensive interface for coordinating multimedia
    operations across different backend libraries including yt-dlp for video downloading
    and FFmpeg for media conversion. It serves as a high-level abstraction that manages
    the complexity of multiple multimedia tools while providing a consistent API for
    common media processing workflows.

    This class automatically detects available backend libraries and gracefully handles
    scenarios where certain tools are not installed, providing clear feedback about
    available capabilities. It supports asynchronous operations for improved performance
    and provides detailed logging for debugging and monitoring purposes.

    Args:
        default_output_dir (Optional[str], optional): Default directory path for output files.
            If not provided, defaults to the current working directory. The directory will
            be created if it doesn't exist. Defaults to None.
        enable_logging (bool, optional): Enable detailed logging for debugging and monitoring.
            When True, logs initialization status, operation progress, and error details.
            Defaults to True.

    Key Features:
    - Unified interface for video downloading and media conversion
    - Automatic backend availability detection and graceful degradation
    - Asynchronous operation support for improved performance
    - Comprehensive error handling and logging
    - Flexible output directory management
    - Quality and format selection for downloads and conversions
    - Capability introspection for runtime feature detection

    Attributes:
        default_output_dir (Path): Default directory for output files, resolved to absolute path
        enable_logging (bool): Flag indicating whether detailed logging is enabled
        ytdlp (Optional[YtDlpWrapper]): yt-dlp wrapper instance for video downloading,
            None if yt-dlp is not available
        ffmpeg (Optional[FFmpegWrapper]): FFmpeg wrapper instance for media conversion,
            None if FFmpeg is not available

    Public Methods:
        download_and_convert(url: str, output_format: str = "mp4", quality: str = "best") -> Dict[str, Any]:
            Downloads video from URL and optionally converts to specified format.
            Coordinates between yt-dlp for downloading and FFmpeg for conversion,
            providing comprehensive status reporting and error handling.
        get_capabilities() -> Dict[str, Any]:
            Returns detailed information about available backends and supported operations.
            Useful for runtime capability detection and user interface adaptation.

    Usage Example:
        # Basic usage with default settings
        processor = MediaProcessor()
        
        # Download and convert video
        result = await processor.download_and_convert(
            url="https://youtube.com/watch?v=example",
            output_format="mp4",
            quality="720p"
        )
        
        # Check available capabilities
        capabilities = processor.get_capabilities()
        if capabilities["download"]:
            print("Video downloading is available")
        
        # Custom output directory and logging
        processor = MediaProcessor(
            default_output_dir="/path/to/output",
            enable_logging=True
        )

    Notes:
        - Requires yt-dlp for video downloading functionality
        - Requires FFmpeg for media conversion functionality
        - Operations gracefully degrade when backends are unavailable
        - All file paths are resolved to absolute paths for consistency
        - Error handling provides both machine-readable status codes and human-readable messages
    """
    
    def __init__(self, 
                default_output_dir: Optional[str|Path] = None,
                enable_logging: bool = True,
                logger: logging.Logger =  logging.getLogger(__name__),
                ytdlp: Optional[YtDlpWrapper] = None,
                ffmpeg: Optional[FFmpegWrapper] = None
        ) -> None:
        """
        Initialize the MediaProcessor with specified configuration options.

        Sets up the media processor by configuring output directories, initializing
        logging, and creating wrapper instances for available backend libraries.
        The initialization process detects which multimedia tools are available
        and configures the processor accordingly.

        Args:
            default_output_dir (Optional[str|Path], optional): Default directory path for output files.
                Can be relative or absolute path. If relative, it will be resolved relative
                to the current working directory. If None, uses current working directory.
                The directory will be created if it doesn't exist. Defaults to None.
            enable_logging (bool, optional): Enable detailed logging for debugging and monitoring.
                When True, logs initialization status, backend availability, operation progress,
                and error details to the configured logger. Defaults to True.
            logger (logging.Logger, optional): Logger instance for logging messages.
                If None, uses the default logger. Defaults to logging.getLogger(__name__).
            ytdlp (Optional[YtDlpWrapper], optional): Pre-initialized YtDlpWrapper instance.
            ffmpeg (Optional[FFmpegWrapper], optional): Pre-initialized FFmpegWrapper instance.

        Attributes set:
            default_output_dir (Path): Resolved absolute path for default output directory.
                Created from provided path or current working directory if None.
            enable_logging (bool): Flag indicating whether detailed logging is enabled.
            ytdlp (Optional[YtDlpWrapper]): yt-dlp wrapper instance for video downloading.
                Set only if YtDlpWrapper instance is provided, otherwise None.
            ffmpeg (Optional[FFmpegWrapper]): FFmpeg wrapper instance for media conversion.
                Set only if FFmpegWrapper instance is provided is available, otherwise None.

        Raises:
            OSError: If the default_output_dir cannot be created due to permission issues
                or invalid path specifications.
            ImportError: If required dependencies for wrapper initialization are missing
                beyond the expected optional dependencies.
            RuntimeError: If neither yt-dlp nor FFmpeg is provided in arguments.

        Examples:
            >>> # Basic initialization with defaults
            >>> processor = MediaProcessor()
            
            >>> # Custom output directory
            >>> processor = MediaProcessor(default_output_dir="/tmp/media_output")
            
            >>> # Disable logging for production use
            >>> processor = MediaProcessor(enable_logging=False)
            
            >>> # Full configuration
            >>> processor = MediaProcessor(
            ...     default_output_dir="./downloads",
            ...     enable_logging=True
            ... )
        """
        if default_output_dir is None:
            default_output_dir = Path.cwd()
        else:
            if not isinstance(default_output_dir, (Path, str)):
                raise TypeError(f"default_output_dir must be a string or Path, got {type(default_output_dir)}")
            default_output_dir = Path(default_output_dir).resolve()

        self.default_output_dir: Path = default_output_dir
        self.enable_logging: bool = enable_logging
        self.logger = None
        if enable_logging:
            self.logger = logger

        # Initialize component wrappers
        self.ytdlp: Optional[YtDlpWrapper] = ytdlp
        self.ffmpeg: Optional[FFmpegWrapper] = ffmpeg
        
        if self.logger is not None:
            self.logger.info(
                f"MediaProcessor initialized - YT-DLP: {YTDLP_AVAILABLE}, FFmpeg: {FFMPEG_AVAILABLE}"
            )

        # Ensure instances are set.
        if self.ytdlp is None and self.ffmpeg is None:
            if self.logger is not None:
                self.logger.error("No multimedia backends available - cannot perform operations")
            raise RuntimeError("No multimedia backends available - cannot perform operations")
    
    async def download_and_convert(self,
                                 url: str,
                                 output_format: str = "mp4",
                                 quality: str = "best") -> Dict[str, Any]:
        """
        Download video from URL and optionally convert to specified format.

        This method provides a complete workflow for acquiring and processing video content
        by coordinating between yt-dlp for downloading and FFmpeg for format conversion.
        It handles the complexity of chaining operations while providing comprehensive
        error handling and status reporting throughout the process.

        The method first attempts to download the video using yt-dlp in the specified
        quality, then evaluates whether format conversion is needed based on the downloaded
        file format and requested output format. If conversion is required and FFmpeg is
        available, it performs the conversion and reports both download and conversion results.

        Args:
            url (str): Video URL to download. Must be a valid URL supported by yt-dlp,
                including YouTube, Vimeo, and hundreds of other video platforms.
                Examples: "https://youtube.com/watch?v=abc123", "https://vimeo.com/123456789"
            output_format (str, optional): Desired output format for the final video file.
                Common formats include "mp4", "avi", "mkv", "webm", "mov". The format
                determines the container and potentially triggers conversion if the
                downloaded format differs. Defaults to "mp4".
            quality (str, optional): Quality preference for video download. Options include
                "best", "worst", specific resolutions like "720p", "1080p", or format
                specifiers like "mp4[height<=720]". Defaults to "best".

        Returns:
            Dict[str, Any]: Comprehensive result dictionary containing operation status
                and detailed information. Structure varies based on operation outcome:
                
                Success case:
                {
                    "status": "success",
                    "output_path": str,  # Path to downloaded file
                    "title": str,        # Video title
                    "duration": float,   # Duration in seconds
                    "filesize": int,     # File size in bytes
                    "format": str,       # Downloaded format
                    "converted_path": str,      # Path to converted file (if conversion occurred)
                    "conversion_result": Dict   # Conversion operation details (if applicable)
                }
                
                Error cases:
                {
                    "status": "error",
                    "error": str  # Human-readable error description
                }

        Raises:
            ValueError: If url is empty, invalid, or not supported by available backends.
            TypeError: If url is not a string or if quality/output_format parameters
                are not strings.
            OSError: If output directory is not writable or disk space is insufficient.
            TimeoutError: If download or conversion operations exceed timeout limits.
            Exception: For unexpected errors during download or conversion operations,
                with error details logged and included in return dictionary.

        Examples:
            >>> # Basic video download
            >>> result = await processor.download_and_convert("https://youtube.com/watch?v=abc123")
            >>> print(f"Downloaded: {result['output_path']}")
            
            >>> # Download with specific quality and format
            >>> result = await processor.download_and_convert(
            ...     url="https://vimeo.com/123456789",
            ...     output_format="avi",
            ...     quality="720p"
            ... )
            
            >>> # Error handling
            >>> result = await processor.download_and_convert("invalid_url")
            >>> if result["status"] == "error":
            ...     print(f"Download failed: {result['error']}")

        Note:
            - Requires yt-dlp to be available for download functionality
            - Format conversion only occurs if FFmpeg is available and formats differ
            - Original downloaded file is preserved even after conversion
            - Progress information is logged when logging is enabled
            - Operation respects rate limiting and platform-specific restrictions
        """
        try:
            if self.ytdlp is None:
                return {
                    "status": "error",
                    "error": "YT-DLP not available for download"
                }
            
            # Download video
            download_result = await self.ytdlp.download_video(
                url=url,
                quality=quality,
                output_dir=str(self.default_output_dir)
            )
            
            if download_result.get("status") != "success":
                return download_result
            
            # Initialize conversion fields to None (may be overridden if conversion occurs)
            download_result["converted_path"] = None
            download_result["conversion_result"] = None
            
            # If format conversion is needed and FFmpeg is available
            downloaded_file = download_result.get("output_path")
            conversion_needed = downloaded_file and self.ffmpeg and not downloaded_file.endswith(f".{output_format}")
            
            if conversion_needed:
                convert_path = str(Path(downloaded_file).with_suffix(f".{output_format}"))
                convert_result = await self.ffmpeg.convert_video(downloaded_file, convert_path)
                print(f"convert_result: {convert_result}")
                
                status = convert_result.get("status")
                match status:
                    case "success":
                        download_result["converted_path"] = convert_path
                        download_result["conversion_result"] = convert_result
                    case "error":
                        # Conversion failure should result in overall error status
                        return {
                            "status": "error",
                            "error": f"Conversion failed: {convert_result.get('error', 'Unknown conversion error')}"
                        }
                    case _:
                        raise ValueError(f"Unexpected conversion status: '{status}'")
            
            return download_result

        except Exception as e:
            if self.logger is not None:
                self.logger.exception(f"Error in download_and_convert: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        """
        Get comprehensive information about available capabilities and supported operations.

        This method provides runtime introspection of the MediaProcessor's capabilities
        by checking the availability of backend libraries and determining which operations
        are supported. It's useful for adapting user interfaces, validating operation
        requests, and providing informative feedback about system capabilities.

        The capabilities information includes both individual backend availability and
        composite operation support, allowing callers to understand not just what tools
        are available but what complete workflows can be executed.

        Returns:
            Dict[str, Any]: Comprehensive capabilities information with the following structure:
                {
                    "download": bool,                    # Video downloading capability
                    "convert": bool,                     # Media conversion capability
                }

        Examples:
            >>> processor_can = processor.get_capabilities()
            >>> 
            >>> # Check if downloading is supported
            >>> if processor_can["download"]:
            ...     print("Video downloading is available")
            ... else:
            ...     print("yt-dlp is required for video downloading")
            >>> 
            >>> # Adapt UI based on capabilities
            >>> if processor_can["download"] and processor_can["convert"]:
            ...     show_full_interface()
            ... elif processor_can["download"]:
            ...     show_download_only_interface()
            ... else:
            ...     show_no_capabilities_message()
            >>> 
            >>> # Validate operation before attempting
            >>> if not processor_can["convert"]:
            ...     raise RuntimeError("Conversion not supported - FFmpeg required")

        Note:
            - Capability detection is performed at initialization time
            - Results reflect the state at processor creation, not current runtime state
            - Backend availability depends on proper installation and system PATH configuration
            - Composite operations require all constituent backends to be available
            - This method is synchronous and performs no external operations
        """
        return {
            "download": YTDLP_AVAILABLE,
            "convert": FFMPEG_AVAILABLE,
        }

