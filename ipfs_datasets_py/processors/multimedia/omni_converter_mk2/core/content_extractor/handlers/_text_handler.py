"""
Text format handlers for the Omni-Converter using IoC pattern.

This module provides handlers for text-based formats like HTML, XML, plain text, etc.
using dependency injection for better modularity and testability, without inheritance.
"""
from types_ import Configs, Logger, Any, Callable, Optional


class TextHandler:
    """
    Framework class for handling text-based formats.
    
    This class only contains orchestration logic and delegates all format-specific
    processing to injected processors via the resources dictionary.
    """
    
    def __init__(self, 
                 resources: dict[str, Callable], 
                 configs: Configs
                 ):
        """
        Initialize the text handler with injected dependencies.
        
        Args:
            resources: Dictionary of callable resources including processors and utilities.
            configs: Configuration settings.
        """
        self.resources = resources
        self.configs = configs

        self._splitext = resources["splitext"]

        # Extract required resources - fail fast if missing
        # NOTE Some of these use processors may support related formats,
        # Example: xlsx processors also handles xls, xlsm, etc.
        self._html_processor: Callable = self.resources["html_processor"]
        self._xml_processor: Callable = self.resources["xml_processor"]
        self._calendar_processor: Callable = self.resources["calendar_processor"]
        self._text_processor: Callable = self.resources["text_processor"]
        self._csv_processor: Callable = self.resources["csv_processor"]

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
        Extract content from a text file using the appropriate processor.
        
        Args:
            file_path: Path to the file.
            format_name: Format of the file.
            options: Processing options.
            
        Returns:
            Tuple of (text content, metadata, sections).
        """
        # Delegate to appropriate processor based on format
        match format_name: # TODO un-hard code this case-match
            case 'html':
                processor = self._html_processor
            case 'xml':
                processor = self._xml_processor
            case 'plain':
                processor = self._text_processor
            case 'calendar':
                processor = self._calendar_processor
            case 'csv':
                processor = self._csv_processor
            case _:
                raise ValueError(f"Unsupported text format: {format_name}")
        try:
            # Call the processor function
            return processor(file_path, options)
        except Exception as e:
            self._logger.error(f"Error processing {format_name} file '{file_path}': {e}", exc_info=True)
            raise RuntimeError(f"Failed to process {format_name} file: {file_path}") from e

    @property
    def capabilities(self) -> dict[str, Any]:
        """Get handler capabilities."""
        return self._capabilities
