"""InputDetector - Automatically classify inputs and extract metadata.

This module provides intelligent input detection and classification for the
unified processor system. It examines input data to determine its type (URL,
file, folder, etc.) and extracts relevant metadata.
"""

from __future__ import annotations

import os
import re
import mimetypes
from typing import Any, Dict, Optional, Union
from pathlib import Path
from urllib.parse import urlparse
import uuid

from .protocol import InputType, ProcessingContext


# URL patterns for detection
URL_PATTERNS = {
    'http': re.compile(r'^https?://'),
    'ipfs_protocol': re.compile(r'^ipfs://(.+)'),
    'ipfs_path': re.compile(r'^/ipfs/([a-zA-Z0-9]+)'),
    'ipns_protocol': re.compile(r'^ipns://(.+)'),
    'ipns_path': re.compile(r'^/ipns/([a-zA-Z0-9\-.]+)'),
    'ipfs_cid': re.compile(r'^(Qm[1-9A-HJ-NP-Za-km-z]{44}|b[A-Za-z2-7]{58,})$'),
}

# Magic bytes for common file formats
MAGIC_BYTES = {
    b'%PDF': 'pdf',
    b'\x89PNG': 'png',
    b'\xFF\xD8\xFF': 'jpg',
    b'GIF87a': 'gif',
    b'GIF89a': 'gif',
    b'PK\x03\x04': 'zip',  # Also docx, xlsx, etc.
    b'PK\x05\x06': 'zip',
    b'PK\x07\x08': 'zip',
    b'\x1f\x8b': 'gz',
    b'BM': 'bmp',
    b'RIFF': 'webp',  # or avi, wav - need more bytes
    b'\x00\x00\x01\xBA': 'mpg',
    b'\x00\x00\x01\xB3': 'mpg',
    b'ftyp': 'mp4',  # at offset 4
    b'\x4F\x67\x67\x53': 'ogg',
}


class InputDetector:
    """Detector for automatically classifying inputs and extracting metadata.
    
    This class examines input data to determine its type and extract relevant
    metadata. It supports URLs, files, folders, text, and binary data.
    
    Example:
        >>> detector = InputDetector()
        >>> context = detector.detect("https://example.com/page.html")
        >>> print(context.input_type)  # InputType.URL
        >>> print(context.get_format())  # 'html'
        
        >>> context = detector.detect("/path/to/document.pdf")
        >>> print(context.input_type)  # InputType.FILE
        >>> print(context.get_format())  # 'pdf'
    """
    
    def __init__(self):
        """Initialize the input detector."""
        # Initialize mimetypes database
        mimetypes.init()
    
    def detect(self, input_data: Any, **options) -> ProcessingContext:
        """Detect input type and create processing context.
        
        This is the main entry point for input detection. It examines the
        input data and returns a ProcessingContext with the detected type,
        extracted metadata, and any provided options.
        
        Args:
            input_data: Input to detect (URL string, file path, bytes, etc.)
            **options: Additional options to include in context
            
        Returns:
            ProcessingContext with detected type and metadata
            
        Example:
            >>> detector = InputDetector()
            >>> context = detector.detect("https://example.com")
            >>> assert context.input_type == InputType.URL
            
            >>> context = detector.detect("/path/to/file.pdf")
            >>> assert context.input_type == InputType.FILE
        """
        # Generate session ID if not provided
        session_id = options.get('session_id', str(uuid.uuid4()))
        
        # Initialize metadata
        metadata: Dict[str, Any] = {}
        input_type: InputType
        source: Union[str, bytes, Any] = input_data
        
        # Handle None or empty input
        if input_data is None:
            raise ValueError("Input data cannot be None")
        
        # Detect bytes/binary data
        if isinstance(input_data, bytes):
            input_type = InputType.BINARY
            metadata['size'] = len(input_data)
            metadata['format'] = self._detect_format_from_magic_bytes(input_data)
        
        # Detect string inputs
        elif isinstance(input_data, str):
            input_str = input_data.strip()
            
            # Check for URL patterns
            if self._is_url(input_str):
                url_info = self._parse_url(input_str)
                input_type = url_info['type']
                metadata.update(url_info['metadata'])
            
            # Check if it's a folder
            elif self._is_folder(input_str):
                input_type = InputType.FOLDER
                metadata.update(self._get_folder_metadata(input_str))
            
            # Check if it's a file
            elif self._is_file(input_str):
                input_type = InputType.FILE
                metadata.update(self._get_file_metadata(input_str))
            
            # Otherwise treat as text
            else:
                input_type = InputType.TEXT
                metadata['length'] = len(input_str)
                metadata['format'] = 'text'
        
        # Handle other types (objects, etc.)
        else:
            input_type = InputType.BINARY
            metadata['type'] = str(type(input_data))
        
        # Create and return context
        return ProcessingContext(
            input_type=input_type,
            source=source,
            metadata=metadata,
            options=options,
            session_id=session_id
        )
    
    def _is_url(self, text: str) -> bool:
        """Check if text is a URL.
        
        Args:
            text: Text to check
            
        Returns:
            True if text appears to be a URL
        """
        # Check for URL patterns
        if URL_PATTERNS['http'].match(text):
            return True
        if URL_PATTERNS['ipfs_protocol'].match(text):
            return True
        if URL_PATTERNS['ipfs_path'].match(text):
            return True
        if URL_PATTERNS['ipns_protocol'].match(text):
            return True
        if URL_PATTERNS['ipns_path'].match(text):
            return True
        if URL_PATTERNS['ipfs_cid'].match(text):
            return True
        
        return False
    
    def _parse_url(self, url: str) -> Dict[str, Any]:
        """Parse URL and extract information.
        
        Args:
            url: URL string to parse
            
        Returns:
            Dictionary with 'type' and 'metadata'
        """
        result = {'type': InputType.URL, 'metadata': {}}
        
        # Check for IPFS CID (bare CID without protocol)
        if URL_PATTERNS['ipfs_cid'].match(url):
            result['type'] = InputType.IPFS_CID
            result['metadata']['cid'] = url
            result['metadata']['protocol'] = 'ipfs'
            return result
        
        # Check for IPFS protocol
        ipfs_match = URL_PATTERNS['ipfs_protocol'].match(url)
        if ipfs_match:
            result['type'] = InputType.IPFS_CID
            result['metadata']['cid'] = ipfs_match.group(1)
            result['metadata']['protocol'] = 'ipfs'
            return result
        
        # Check for IPFS path
        ipfs_path_match = URL_PATTERNS['ipfs_path'].match(url)
        if ipfs_path_match:
            result['type'] = InputType.IPFS_CID
            result['metadata']['cid'] = ipfs_path_match.group(1)
            result['metadata']['protocol'] = 'ipfs'
            result['metadata']['path_format'] = '/ipfs/'
            return result
        
        # Check for IPNS protocol
        ipns_match = URL_PATTERNS['ipns_protocol'].match(url)
        if ipns_match:
            result['type'] = InputType.IPNS
            result['metadata']['name'] = ipns_match.group(1)
            result['metadata']['protocol'] = 'ipns'
            return result
        
        # Check for IPNS path
        ipns_path_match = URL_PATTERNS['ipns_path'].match(url)
        if ipns_path_match:
            result['type'] = InputType.IPNS
            result['metadata']['name'] = ipns_path_match.group(1)
            result['metadata']['protocol'] = 'ipns'
            result['metadata']['path_format'] = '/ipns/'
            return result
        
        # Parse as regular URL
        try:
            parsed = urlparse(url)
            result['metadata']['scheme'] = parsed.scheme
            result['metadata']['netloc'] = parsed.netloc
            result['metadata']['path'] = parsed.path
            
            # Extract format from path if available
            if parsed.path:
                path_lower = parsed.path.lower()
                if '.' in path_lower:
                    ext = path_lower.rsplit('.', 1)[-1]
                    # Remove query params if present
                    if '?' in ext:
                        ext = ext.split('?')[0]
                    result['metadata']['format'] = ext
        except Exception:
            # If parsing fails, just store the original URL
            result['metadata']['url'] = url
        
        return result
    
    def _is_file(self, path: str) -> bool:
        """Check if path is an existing file.
        
        Args:
            path: Path to check
            
        Returns:
            True if path exists and is a file
        """
        try:
            return os.path.isfile(path)
        except (OSError, ValueError):
            return False
    
    def _is_folder(self, path: str) -> bool:
        """Check if path is an existing folder.
        
        Args:
            path: Path to check
            
        Returns:
            True if path exists and is a directory
        """
        try:
            return os.path.isdir(path)
        except (OSError, ValueError):
            return False
    
    def _get_file_metadata(self, file_path: str) -> Dict[str, Any]:
        """Extract metadata from a file.
        
        Args:
            file_path: Path to file
            
        Returns:
            Dictionary with file metadata
        """
        metadata: Dict[str, Any] = {}
        
        try:
            path = Path(file_path)
            
            # Basic file info
            metadata['path'] = str(path.absolute())
            metadata['filename'] = path.name
            metadata['extension'] = path.suffix.lstrip('.').lower() if path.suffix else None
            
            # File stats
            stat = path.stat()
            metadata['size'] = stat.st_size
            metadata['modified'] = stat.st_mtime
            metadata['created'] = stat.st_ctime
            
            # Detect format from extension
            if metadata['extension']:
                metadata['format'] = metadata['extension']
            
            # Try to detect MIME type
            mime_type, _ = mimetypes.guess_type(file_path)
            if mime_type:
                metadata['mime_type'] = mime_type
            
            # Try to detect format from magic bytes
            if stat.st_size > 0:
                magic_format = self.detect_format(file_path)
                if magic_format:
                    metadata['format_from_magic'] = magic_format
                    # Use magic bytes format if extension is missing or ambiguous
                    if not metadata.get('format'):
                        metadata['format'] = magic_format
        
        except Exception as e:
            metadata['error'] = str(e)
        
        return metadata
    
    def _get_folder_metadata(self, folder_path: str) -> Dict[str, Any]:
        """Extract metadata from a folder.
        
        Args:
            folder_path: Path to folder
            
        Returns:
            Dictionary with folder metadata
        """
        metadata: Dict[str, Any] = {}
        
        try:
            path = Path(folder_path)
            
            # Basic folder info
            metadata['path'] = str(path.absolute())
            metadata['name'] = path.name
            metadata['format'] = 'folder'
            
            # Count files
            try:
                files = list(path.iterdir())
                metadata['file_count'] = len(files)
                metadata['files'] = [f.name for f in files[:10]]  # First 10 files
                if len(files) > 10:
                    metadata['has_more'] = True
            except PermissionError:
                metadata['permission_error'] = True
        
        except Exception as e:
            metadata['error'] = str(e)
        
        return metadata
    
    def detect_format(self, file_path: str) -> Optional[str]:
        """Detect file format using magic bytes.
        
        Args:
            file_path: Path to file
            
        Returns:
            Detected format string or None
        """
        try:
            with open(file_path, 'rb') as f:
                # Read first 16 bytes for magic byte detection
                header = f.read(16)
                
                return self._detect_format_from_magic_bytes(header)
        
        except Exception:
            return None
    
    def _detect_format_from_magic_bytes(self, data: bytes) -> Optional[str]:
        """Detect format from magic bytes.
        
        Args:
            data: Bytes to check (usually file header)
            
        Returns:
            Detected format string or None
        """
        if not data:
            return None
        
        # Check each magic byte pattern
        for magic, format_name in MAGIC_BYTES.items():
            if data.startswith(magic):
                return format_name
        
        # Special cases that need offset checking
        if len(data) >= 8:
            # MP4 has 'ftyp' at offset 4
            if data[4:8] == b'ftyp':
                return 'mp4'
        
        return None
    
    def extract_metadata(self, input_data: Any) -> Dict[str, Any]:
        """Extract metadata from input data.
        
        This is a convenience method that creates a context and returns
        just the metadata portion.
        
        Args:
            input_data: Input to extract metadata from
            
        Returns:
            Dictionary with extracted metadata
            
        Example:
            >>> detector = InputDetector()
            >>> metadata = detector.extract_metadata("/path/to/file.pdf")
            >>> print(metadata['format'])  # 'pdf'
        """
        context = self.detect(input_data)
        return context.metadata


# Convenience functions
_default_detector = None


def detect_input(input_data: Any, **options) -> ProcessingContext:
    """Convenience function to detect input using default detector.
    
    Args:
        input_data: Input to detect
        **options: Additional options
        
    Returns:
        ProcessingContext with detected type and metadata
        
    Example:
        >>> from ipfs_datasets_py.processors.core import detect_input
        >>> context = detect_input("https://example.com")
        >>> print(context.input_type)
    """
    global _default_detector
    if _default_detector is None:
        _default_detector = InputDetector()
    return _default_detector.detect(input_data, **options)


def detect_format(file_path: str) -> Optional[str]:
    """Convenience function to detect file format.
    
    Args:
        file_path: Path to file
        
    Returns:
        Detected format string or None
        
    Example:
        >>> from ipfs_datasets_py.processors.core import detect_format
        >>> format = detect_format("/path/to/file.pdf")
        >>> print(format)  # 'pdf'
    """
    global _default_detector
    if _default_detector is None:
        _default_detector = InputDetector()
    return _default_detector.detect_format(file_path)
