"""
Format detection module for the Omni-Converter.

This module provides functionality for detecting the format of files using dependency injection
and following the IoC pattern established in CLAUDE.md.
"""
from __future__ import annotations
from types_ import Any, Callable, Configs, Logger, Optional, FileInfo


class FileFormatDetector:
    """
    Format detector for the Omni-Converter.

    Detects the format of files based on their content and extension using injected dependencies.
    If a format is not supported, it returns None.

    Attributes:
        _get_file_info: Callable for getting file information
        _format_registry: dict mapping categories to supported formats
        _format_signatures: dict mapping MIME types to format names
        _format_extensions: dict mapping file extensions to format names
        _logger: Logger instance for debug/warning messages
    """
    def __init__(self, 
                 resources: dict[str, Any], 
                 configs: Configs
                 ) -> None:
        """
        Initialize the format detector with injected dependencies.
        
        Args:
            resources: Dictionary containing required callables and data:
                - 'get_file_info': Function to get file information
                - 'format_registry': dict of supported formats by category
                    Example:
                        {
                            'images': ['jpeg', 'png', 'gif', 'webp'],
                            'documents': ['pdf', 'docx', 'txt', 'md'],
                            'audio': ['mp3', 'wav', 'flac'],
                            'video': ['mp4', 'avi', 'mkv']
                        }
                - 'format_signatures': dict mapping MIME types to formats
                    Example:
                        {
                            'image/jpeg': 'jpeg',
                            'image/png': 'png',
                            'application/pdf': 'pdf',
                            'text/plain': 'txt',
                            'audio/mpeg': 'mp3'
                        }
                - 'format_extensions': dict mapping extensions to formats
                    Example:
                        {
                            '.jpg': 'jpeg',
                            '.jpeg': 'jpeg', 
                            '.png': 'png',
                            '.pdf': 'pdf',
                            '.txt': 'txt',
                            '.mp3': 'mp3'
                        }
                - 'logger': Logger instance
            configs: Pydantic configuration model
            
        Raises:
            KeyError: If required resources are missing
        """
        self.configs: Configs = configs
        self.resources: dict[str, Callable] = resources

        self._get_file_info: Callable = self.resources['get_file_info']
        self._format_registry: dict[str, set[str]] = self.resources['format_registry']
        self._format_signatures: dict[str, str] = self.resources['format_signatures']
        self._format_extensions: dict[str, str] = self.resources['format_extensions']
        self._logger: Logger = self.resources['logger']
        self._abspath: Callable = self.resources['abspath']


    def detect_format(self, file_path: str) -> tuple[Optional[str], Optional[str]]:
        """
        Detect the format of a file using injected dependencies.
        
        Args:
            file_path: The path to the file.
            
        Returns:
            A tuple of (format, category) if the format is detected, (None, None) otherwise.
                - format: The detected format name (e.g., 'jpeg', 'pdf').
                - category: The category of the format (e.g., 'images', 'documents').
            
        Raises:
            FileNotFoundError: If the file does not exist.
            PermissionError: If the file cannot be read.
        """
        # Get file information using absolute path
        file_path: str = self._abspath(file_path)
        file_info: FileInfo = self._get_file_info(file_path)

        format_name = None
        format_name = self._get_format_signatures(file_info, file_path)
        if format_name is None:
            self._logger.warning(f"Could not detect format for file: {file_path}")
            return None, None

        # Find the category for this format
        category = None
        category = self.get_format_category(format_name)

        # If the category is not found, this is an unsupported format
        if category is None:
            self._logger.warning(f"Format '{format_name}' is not in any supported category for file: {file_path}")
            return format_name, None

        self._logger.debug(f"Detected format '{format_name}' in category '{category}' for file: {file_path}")
        return format_name, category

    # @staticmethod
    # def _concatenate_frozensets_into_list(formats: list[frozenset[str]]) -> set[str]:
    #     """
    #     Convert a list of frozensets into a single set.
        
    #     Args:
    #         list_of_frozen_sets: List of frozensets to convert.
            
    #     Returns:
    #         A single set containing all elements from the frozensets.
    #     """
    #     format_set = []
    #     list_of_lists = [list(x) for x in formats]
    #     for format_list in list_of_lists:
    #         format_set.extend(format_list)
    #     return set(format_set)

    @property
    def supported_formats(self) -> dict[str, set[str]]:
        """
        Get the supported formats from injected registry.
        
        Returns:
            A dictionary of sets, where each key is the category, and every.
        """
        return self._format_registry


    def _get_format_signatures(self, file_info: FileInfo, file_path: str) -> Optional[dict[str, str]]:
        # Try to detect format based on MIME type
        format_name = self._format_signatures.get(file_info.mime_type)

        # If MIME type detection failed, try extension
        if format_name is None:
            self._logger.debug(f"Format detection by MIME type failed for file: {file_path} - MIME: {file_info.mime_type}")
            format_name = self._format_extensions.get(file_info.extension.lower())

        # If format detection failed entirely, return None
        if format_name is None:
            self._logger.debug(f"Format detection failed for file: {file_path} - MIME: {file_info.mime_type}, Ext: {file_info.extension}")
            return None
        else:
            return format_name

    def get_format_category(self, format_name: str) -> Optional[str]:
        """Get the category for a format
        
        Args:
            format_name: The format name.
            
        Returns:
            str | None: The category if found, None otherwise.
        """
        for category, formats in self._format_registry.items():
            #self._logger.debug(f"Format set: {formats}")
            if format_name in formats:
                return category
        return None

    def is_format_supported(self, format_name: str) -> bool:
        """
        Check if a format is supported.
        
        Args:
            format_name: The format name.
            
        Returns:
            True if the format is supported, False otherwise.
        """
        return self.get_format_category(format_name) is not None
