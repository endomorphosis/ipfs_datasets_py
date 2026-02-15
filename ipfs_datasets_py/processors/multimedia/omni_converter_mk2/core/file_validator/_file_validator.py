"""
Validation module for the Omni-Converter.

This module provides validation functionality for files and formats.
"""
from typing import Callable, Optional

from configs import Configs
from core.file_validator._validation_result import ValidationResult

from utils.filesystem import FileSystem


from types_ import Logger


class FileValidator:
    """
    File validator for the Omni-Converter.
    
    Validates files for processing, checking for issues like:
    - File exists and is readable
    - File size is within limits
    - File format is supported
    - File is not corrupted
    """

    def __init__(self,
                 resources: dict[str, Callable] = None, 
                 configs: Configs = None
                 ) -> None:
        """
        Initialize the FileValidator with configuration and dependencies.

        Args:
            resources: Dictionary containing injected dependencies including:
            - file_exists: Function to check if a file exists
            - get_file_info: Function to retrieve file metadata
            - validation_result: Factory function for ValidationResult objects
            - file_format_detector: File format detection service
            - logger: Logger instance for error reporting
    
            configs: Configuration object containing validation settings
             - max_file_size_mb: Maximum allowed file size in MB
             - allowed_formats: List of allowed file formats
        """
        self.configs = configs
        self.resources = resources

        # Load validation rules from config
        self.max_file_size_mb: int = self.configs.security.max_file_size_mb
        self.allowed_formats: list[str] = self.configs.security.allowed_formats

        # Injected dependencies
        self._file_exists: Callable = self.resources['file_exists']
        self._get_file_info: Callable = self.resources['get_file_info']
        self._validation_result: Callable = self.resources['validation_result']
        self._format_detector = self.resources['file_format_detector']
        self._logger: Logger = self.resources['logger']


    def validate_file(self, file_path: str, format_name: Optional[str] = None) -> ValidationResult:
        """
        Validate a file for processing.
        
        Args:
            file_path: The path to the file.
            format_name: The format of the file, if known. Will be detected if not provided.
            
        Returns:
            A validation result.
            
        Raises:
            FileNotFoundError: If the file does not exist.
        """
        # Create validation result
        result: ValidationResult = self._validation_result()
        
        print(f"Validating file: {file_path} with format: {format_name}\n{result}")

        try:
            # Check if file exists
            if not self._file_exists(file_path):
                result.add_error(f"File does not exist: {file_path}")
                return result
            
            # Get file info
            file_info = self._get_file_info(file_path)
            
            # Check if file is readable
            if not file_info.is_readable:
                result.add_error(f"File is not readable: {file_path}")
                return result
            
            # Check file size
            max_size_bytes = self.max_file_size_mb * 1024 * 1024
            if file_info.size > max_size_bytes:
                result.add_error(
                    f"File size ({file_info.size} bytes) exceeds maximum allowed "
                    f"({max_size_bytes} bytes): {file_path}"
                )
                return result
            elif file_info.size == 0:
                result.add_error(f"File is empty: {file_path}")
                return result

            # Detect format if not provided
            if not format_name:
                format_name, category = self._format_detector.detect_format(file_path)
                if not format_name:
                    result.add_error(f"Unable to detect format for file: {file_path}")
                    return result
                
                result.add_context('format', format_name)
                result.add_context('category', category)
            else:
                # Check if provided format is supported
                # TODO This is redundant as we already checked for this in in the detector.
                category = self._format_detector.get_format_category(format_name)
                if not category:
                    result.add_error(f"Format '{format_name}' is not supported")
                    return result

                result.add_context('format', format_name)
                result.add_context('category', category)

            # Check if format is allowed
            if self.allowed_formats: 
                if format_name not in self.allowed_formats:
                    result.add_error(f"Format '{format_name}' is not allowed")
                    return result
            print(f"Allowed formats: {self.allowed_formats}")

            # Add file metadata to result
            result.add_context('file_size', file_info.size)
            result.add_context('mime_type', file_info.mime_type)
            result.add_context('extension', file_info.extension)

            # All checks passed
            result.is_valid = True

        except Exception as e:
            result.add_error(f"Unexpected Validation error: {e}")
            self._logger.error(f"Unexpected validation error for file: {file_path}", {'error': str(e)})

        return result

    @staticmethod
    def _check_for_null_bytes_and_permissions(file_path:str, format_name:str, result: ValidationResult) -> bool:
        """Check for null bytes and permission issues that could cause hangs
        
        Args:
            file_path: The path to the file.
            format_name: The format of the file
            
        Returns:
            True if the file is corrupt, False otherwise.
        """
        try:
            with open(file_path, 'rb') as f:
                # Read first 1KB to check for null bytes
                chunk = f.read(1024)
                if b'\x00' in chunk and format_name not in ['pdf', 'docx', 'xlsx', 'pptx']: # TODO This needs to be more generic.
                    result.add_error(f"File contains null bytes and may be corrupted: {file_path}")
                    return result
        except PermissionError:
            result.add_error(f"Insufficient permissions to read file: {file_path}")
            return result
        except (OSError, IOError) as e:
            result.add_error(f"File access error: {file_path} - {str(e)}")
            return result

    def is_valid_for_processing(self, file_path: str, format_name: Optional[str] = None) -> bool:
        """Check if a file is valid for processing.
        
        Args:
            file_path: The path to the file.
            format_name: The format of the file, if known. Will be detected if not provided.
            
        Returns:
            True if the file is valid for processing, False otherwise.
        """
        result = self.validate_file(file_path, format_name)
        return result.is_valid

    def get_validation_errors(self, file_path: str, format_name: Optional[str] = None) -> list[str]:
        """
        Get validation errors for a file.
        
        Args:
            file_path: The path to the file.
            format_name: The format of the file, if known. Will be detected if not provided.
            
        Returns:
            A list of validation errors.
        """
        result = self.validate_file(file_path, format_name)
        return result.errors

