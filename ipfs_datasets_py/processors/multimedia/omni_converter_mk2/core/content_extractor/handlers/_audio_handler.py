"""
Audio format handlers for the Omni-Converter using IoC pattern.

This module provides handlers for audio formats like MP3, WAV, OGG, FLAC, and AAC
using dependency injection for better modularity and testability, without inheritance.
"""
from types_ import Any, Callable, Configs, Logger, Optional


class AudioHandler:
    """
    Framework class for handling audio-based formats using IoC pattern.
    
    This class only contains orchestration logic and delegates all format-specific
    processing to injected processors via the resources dictionary.
    """
    
    def __init__(self, 
                 resources: dict[str, Callable], 
                 configs: Configs
                 ):
        """
        Initialize the audio handler with injected dependencies.
        
        Args:
            resources: Dictionary of callable resources including processors and utilities.
            configs: Configuration settings.
        """
        self.resources = resources
        self.configs = configs

        self._splitext: Callable = self.resources["splitext"]

        # Extract required resources - fail fast if missing
        # NOTE Audio processor handles all common audio formats
        self._audio_processor: Callable = self.resources["audio_processor"]
        self._transcription_processor: Callable = self.resources["transcription_processor"]

        self._format_extensions: dict = self.resources["format_extensions"]
        self._supported_formats: set = self.resources["supported_formats"]
        self._capabilities: dict = self.resources["capabilities"]
        self._logger: Logger = self.resources["logger"]


    def can_handle(self, file_path: str, format_name: Optional[str] = None) -> bool:
        """
        Check if this handler can process the given file format.
        
        Args:
            file_path: Path to the file.
            format_name: Format of the file, if known.
            
        Returns:
            True if this handler can process the format, False otherwise.
        """
        if format_name:
            return format_name in self._supported_formats
        
        # If no format provided, check file extension
        _, ext = self._splitext(file_path)
        ext = ext.lower()
        
        for format_type, extensions in self._format_extensions.items():
            if ext in extensions and format_type in self._supported_formats:
                return True
        
        return False
    
    def extract_content(self, file_path: str, format_name: str, options: dict[str, Any]) -> Callable:
        """
        Extract content from an audio file using the appropriate processor.
        
        Args:
            file_path: Path to the file.
            format_name: Format of the file.
            options: Processing options.
            
        Returns:
            Tuple of (text content, metadata, sections).
        """
        # Check if transcription is requested and available
        enable_transcription = options.get('enable_transcription', False)
        
        try:
            if enable_transcription:
                # Use transcription processor for speech-to-text
                return self._transcription_processor
            else:
                # Use audio processor for metadata extraction
                return self._audio_processor
        except Exception as e:
            self._logger.error(f"Error processing {format_name} file '{file_path}': {e}", exc_info=True)
            raise RuntimeError(f"Failed to process {format_name} file: {file_path}") from e

    @property
    def capabilities(self) -> dict[str, Any]:
        """Get handler capabilities."""
        return self._capabilities

