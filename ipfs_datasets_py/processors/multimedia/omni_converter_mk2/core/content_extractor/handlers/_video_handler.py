"""
Video format handlers for the Omni-Converter using IoC pattern.

This module provides handlers for video formats like MP4, WebM, AVI, MKV, and MOV
using dependency injection for better modularity and testability, without inheritance.
"""
from types_ import Configs, Logger, Any, Callable, Optional


class VideoHandler:
    """
    Framework class for handling video-based formats using IoC pattern.
    
    This class only contains orchestration logic and delegates all format-specific
    processing to injected processors via the resources dictionary.
    """

    def __init__(self, 
                 resources: dict[str, Callable], 
                 configs: Configs
                 ):
        """
        Initialize the video handler with injected dependencies.
        
        Args:
            resources: Dictionary of callable resources including processors and utilities.
            configs: Configuration settings.
        """
        self.resources = resources
        self.configs = configs

        self._splitext = resources["splitext"]

        # Extract required resources - fail fast if missing
        # NOTE Video processor handles metadata extraction and frame processing
        self._video_processor: Callable = self.resources["video_processor"]
        self._transcription_processor: Callable = self.resources["transcription_processor"]

        self._format_extensions: dict = self.resources["format_extensions"]
        self._supported_formats: set = self.resources["supported_formats"]
        self._capabilities: dict = self.resources["capabilities"]
        self._logger: Logger = self.resources["logger"]
        self._can_handle: Callable = self.resources["can_handle"]

    def can_handle(self, file_path: str, format_name: Optional[str] = None) -> bool:
        """
        Check if this handler can process the given file format.
        
        Args:
            file_path: Path to the file.
            format_name: Format of the file, if known.
            
        Returns:
            True if this handler can process the format, False otherwise.
        """
        return self._can_handle(self._supported_formats, self._format_extensions, file_path, format_name)

    def extract_content(self, file_path: str, format_name: str, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        """
        Extract content from a video file using the appropriate processor.
        
        Args:
            file_path: Path to the file.
            format_name: Format of the file.
            options: Processing options.
            
        Returns:
            Tuple of (text content, metadata, sections).
        """
        # Check if transcription is requested and available
        enable_transcription = options.get('enable_transcription', False)
        
        transcription = None
        metadata = None
        try:
            if enable_transcription:
                # Use transcription processor for speech-to-text from video audio
                transcription = self._transcription_processor(file_path, options)
                
            # Use video processor for metadata and frame extraction
            metadata = self._video_processor(file_path, options)
            return metadata, transcription
        except Exception as e:
            self._logger.error(f"Error processing {format_name} file '{file_path}': {e}", exc_info=True)
            raise RuntimeError(f"Failed to process {format_name} file: {file_path}") from e

    @property
    def capabilities(self) -> dict[str, Any]:
        """Get handler capabilities."""
        return self._capabilities
