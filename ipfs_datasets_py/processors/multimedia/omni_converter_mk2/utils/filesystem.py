"""
Filesystem utility functions for the Omni-Converter.

This module provides filesystem utility functions for the Omni-Converter,
including file reading, writing, and information retrieval.
"""
import fnmatch
import magic
import mimetypes
import os
from datetime import datetime
from typing import Any, Optional

try:
    from pydantic import BaseModel, Field, FilePath, PositiveInt, NonNegativeInt
except ImportError:
    raise ImportError("Pydantic is required for the Python API.")


def _determine_mime_type(path_or_bytes: str | bytes | None) -> Optional[str]:
    """Determine the MIME type of a file.
    
    Args:
        file_path: The path to the file.
        
    Returns:
        The MIME type of the file.
    """
    match path_or_bytes:
        case str():
            try:
                mime_type = magic.from_file(path_or_bytes, mime=True)
                # If magic returns generic type but extension suggests specific type, use mimetypes
                if mime_type == 'application/octet-stream':
                    guessed_type = mimetypes.guess_type(path_or_bytes)[0]
                    if guessed_type:
                        return guessed_type
                return mime_type
            except Exception:
                return mimetypes.guess_type(path_or_bytes)[0] or 'application/octet-stream'
        case bytes():
            try:
                return magic.from_buffer(path_or_bytes, mime=True)
            except (ImportError, Exception):
                return 'application/octet-stream'
        case _:
            return None


class FileInfo(BaseModel):
    """
    Information about a file.
    
    Attributes:
        path (str): The path to the file.
        size (int): The size of the file in bytes.
        modified_time (datetime): The time the file was last modified.
        mime_type (str): The MIME type of the file.
        extension (str): The file extension.
        is_readable (bool): Whether the file is readable.
        is_writable (bool): Whether the file is writable.
    """
    path: FilePath = Field(description="The absolute path to the file")
    size: NonNegativeInt = Field(description="The size of the file in bytes")
    modified_time: datetime = Field(description="The time the file was last modified")
    mime_type: Optional[str] = Field(None, description="The MIME type of the file")
    extension: str = Field(description="The file extension")
    is_readable: bool = Field(description="Whether the file is readable")
    is_writable: bool = Field(description="Whether the file is writable")


    @classmethod
    def from_path(cls, path: str) -> 'FileInfo':
        """
        Create FileInfo from a file path.
        
        Args:
            path: The path to the file.
            
        Returns:
            FileInfo instance with populated data.
            
        Raises:
            FileNotFoundError: If the file does not exist.
        """
        if not isinstance(path, str):
            raise TypeError(f"path must be a string, got {type(path).__name__}")
        
        if not path:
            raise ValueError("path cannot be an empty string")

        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")

        abs_path = os.path.abspath(path)
        size = os.path.getsize(path)
        modified_time = datetime.fromtimestamp(os.path.getmtime(path))
        mime_type = _determine_mime_type(path)
        extension = os.path.splitext(path)[1].lstrip('.')
        is_readable = os.access(path, os.R_OK)
        is_writable = os.access(path, os.W_OK)
        
        return cls(
            path=abs_path,
            size=size,
            modified_time=modified_time,
            mime_type=mime_type,
            extension=extension,
            is_readable=is_readable,
            is_writable=is_writable
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to a dictionary.

        Returns:
            A dictionary containing the file information.
        """
        _dict = self.model_dump()
        _dict['modified_time'] = self.modified_time.isoformat()  # Convert datetime to a human-readable format
        _dict['path'] = str(self.path)  # Convert Path object to string for JSON serialization
        return _dict


class FileContent:
    """
    Content of a file.
    
    Attributes:
        raw_content (bytes): The raw binary content of the file.
        text_content (str): The text content of the file, if applicable.
        encoding (str): The encoding of the text content.
        size (int): The size of the content in bytes.
        mime_type (str): The MIME type of the content.
    """
    def __init__(
        self, 
        raw_content: bytes, 
        encoding: str = 'utf-8', 
        mime_type: Optional[str] = None
    ):
        """
        Initialize file content.
        
        Args:
            raw_content: The raw binary content of the file.
            encoding: The encoding to use for text conversion.
            mime_type: The MIME type of the content. If None, will be guessed from content.
        """
        if not isinstance(raw_content, bytes):
            raise TypeError(f"raw_content must be bytes, got {type(raw_content).__name__}")

        self._raw_content = raw_content
        self.encoding = encoding
        self.size = len(raw_content)
        
        # Determine MIME type if not provided
        if mime_type is None:
            try:
                self.mime_type = _determine_mime_type(raw_content)
            except (ImportError, Exception):
                self.mime_type = 'application/octet-stream'
        else:
            self.mime_type = mime_type
        
        # Convert to text if possible
        try:
            self.text_content = raw_content.decode(encoding)
        except UnicodeDecodeError as e:
            self.text_content = ''
    
    def get_as_text(self, encoding: Optional[str] = None) -> str:
        """
        Get the content as text.
        
        Args:
            encoding: The encoding to use. If None, uses the current encoding.
            
        Returns:
            The content as text.
        """
        if encoding and encoding != self.encoding:
            try:
                return self._raw_content.decode(encoding)
            except UnicodeDecodeError as e:
                raise ValueError(f"Cannot decode content with encoding {encoding}") from e
        return self.text_content
    
    @property
    def as_binary(self) -> bytes:
        """
        Get the content as binary.
        
        Returns:
            The raw binary content.
        """
        return self._raw_content


class FileSystem:
    """
    File system utility functions.
    
    Methods:
        read_file: Read file content. Returns FileContent object.
        write_file: Write content to file. Returns True if successful, else False.
        list_files: List files in directory, with optional pattern matching. Returns a list of file paths.
        file_exists: Check if file exists. Returns True if exists, else False.
        get_file_info: Get file information, returns FileInfo object.
        create_directory: Create directory, returns True if successful, else False.
    """ 
    
    @staticmethod
    def read_file(file_path: str, mode: str = 'rb') -> FileContent:
        """
        Read a file.
        
        Args:
            file_path: The path to the file.
            mode: The mode to open the file in. Default is binary mode.
            
        Returns:
            The file content.
            
        Raises:
            FileNotFoundError: If the file does not exist.
            PermissionError: If the file cannot be read.
            IsADirectoryError: If the path points to a directory.
            ValueError: If the mode is invalid.
        """
        # Validate mode
        valid_modes = ['r', 'rb', 'rt']
        if mode not in valid_modes:
            raise ValueError(f"Invalid mode: {mode}. Valid modes are: {valid_modes}")

        # Ensure the path is absolute
        file_path = os.path.abspath(file_path)

        # Check if the file exists
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # Check if path points to a directory
        if os.path.isdir(file_path):
            raise IsADirectoryError(f"Path is a directory: {file_path}")
        
        # Check if the file is readable
        if not os.access(file_path, os.R_OK):
            raise PermissionError(f"Permission denied for file: {file_path}")
        
        # Determine the MIME type
        try:
            mime_type = magic.from_file(file_path, mime=True)
        except Exception:
            mime_type = None

        # Read the file
        with open(file_path, mode) as f:
            content = f.read()

        # If the mode is text mode, convert the content to bytes
        if 'b' not in mode and isinstance(content, str):
            encoding = 'utf-8'  # Default encoding
            content = content.encode(encoding)
            return FileContent(content, encoding, mime_type)
        
        return FileContent(content, 'utf-8', mime_type)
    
    @staticmethod
    def write_file(file_path: str, content: str | bytes, mode: str = 'wb') -> bool:
        """
        Write to a file.
        
        Args:
            file_path: The path to the file.
            content: The content to write.
            mode: The mode to open the file in. Default is binary mode.
            
        Returns:
            True if the file was written successfully, False otherwise.
            
        Raises:
            PermissionError: If the file cannot be written.
            IsADirectoryError: If the path points to a directory.
            FileNotFoundError: If the parent directory doesn't exist.
            ValueError: If the mode is invalid.
        """
        # Validate mode
        valid_modes = ['w', 'wb', 'wt', 'a', 'ab', 'at']
        if mode not in valid_modes:
            raise ValueError(f"Invalid mode: {mode}. Valid modes are: {valid_modes}")

        # Ensure the path is absolute
        file_path = os.path.abspath(file_path)
        
        # Check if path points to an existing directory
        if os.path.exists(file_path) and os.path.isdir(file_path):
            raise IsADirectoryError(f"Path is a directory: {file_path}")

        # Check if parent directory exists
        parent_dir = os.path.dirname(file_path)
        if not os.path.exists(parent_dir):
            raise FileNotFoundError(f"Parent directory does not exist: {parent_dir}")
        
        # Check write permissions on parent directory
        if not os.access(parent_dir, os.W_OK):
            raise PermissionError(f"Permission denied for directory: {parent_dir}")
        
        # Convert string content to bytes if in binary mode
        if 'b' in mode and isinstance(content, str):
            content = content.encode('utf-8')
        
        # Convert bytes content to string if in text mode
        if 'b' not in mode and isinstance(content, bytes):
            content = content.decode('utf-8')
        
        try:
            with open(file_path, mode) as f:
                f.write(content)
            return True
        except Exception:
            return False
    
    @staticmethod
    def list_files(directory: str, pattern: str = '*.*') -> list[str]:
        """
        list files in a directory.
        
        Args:
            directory: The directory to list files in.
            pattern: The pattern to match files against.
            
        Returns:
            A list of file paths matching the pattern.
            
        Raises:
            FileNotFoundError: If the directory does not exist.
            PermissionError: If the directory cannot be read.
        """
        # Ensure the path is absolute
        directory = os.path.abspath(directory)
        
        # Check if the directory exists
        if not os.path.exists(directory):
            raise FileNotFoundError(f"Directory not found: {directory}")
        
        if not os.path.isdir(directory):
            raise NotADirectoryError(f"Path is not a directory: {directory}")

        # Check if the directory is readable
        if not os.access(directory, os.R_OK):
            raise PermissionError(f"Cannot read directory: {directory}")
        
        # List all files in directory and filter with case-insensitive pattern matching
        try:
            all_entries = os.listdir(directory)
        except OSError as e:
            raise PermissionError(f"Cannot read directory: {directory}") from e
            
        # Filter files with case-insensitive pattern matching
        files = []
        for entry in all_entries:
            full_path = os.path.join(directory, entry)
            # Only include actual files (not directories)
            if os.path.isfile(full_path):
                # Handle hidden files: exclude them unless pattern explicitly starts with '.'
                is_hidden = entry.startswith('.')
                pattern_matches_hidden = pattern.startswith('.')
                
                # Skip hidden files if pattern doesn't explicitly match them
                if is_hidden and not pattern_matches_hidden:
                    continue
                    
                # Case-insensitive pattern matching
                if fnmatch.fnmatch(entry.lower(), pattern.lower()):
                    files.append(full_path)
        
        return sorted(files)
    
    @staticmethod
    def file_exists(file_path: str) -> bool:
        """
        Check if a file exists.
        
        Args:
            file_path: The path to the file.
            
        Returns:
            True if the file exists, False otherwise.
        """
        # Ensure the path is absolute
        file_path = os.path.abspath(file_path)
        
        return os.path.exists(file_path) and os.path.isfile(file_path)
    
    @staticmethod
    def get_file_info(path: str) -> FileInfo:
        """
        Get information about a file.
        
        Args:
            file_path: The path to the file.
            
        Returns:
            File information.
            
        Raises:
            FileNotFoundError: If the file does not exist.
        """
        # Ensure the path is absolute
        path = os.path.abspath(path)
        
        return FileInfo.from_path(path)
    
    @staticmethod
    def create_directory(directory_path: str) -> bool:
        """
        Create a directory.
        
        Args:
            directory_path: The path to the directory.
            
        Returns:
            True if the directory was created successfully, False otherwise.
        """
        if not isinstance(directory_path, str):
            raise TypeError(f"directory_path must be a string, got {type(directory_path).__name__}")
        
        if not directory_path:
            return False

        # Ensure the path is absolute
        directory_path = os.path.abspath(directory_path)
        
        # If directory already exists, return True
        if os.path.exists(directory_path):
            if os.path.isdir(directory_path):
                return True
            else:
                # Path exists but is not a directory (file exists at path)
                return False
        
        # Check if parent directory exists (non-recursive implementation)
        parent_dir = os.path.dirname(directory_path)
        if not os.path.exists(parent_dir):
            return False
        
        try:
            os.mkdir(directory_path)  # Use mkdir instead of makedirs for non-recursive
            return True
        except Exception:
            return False
