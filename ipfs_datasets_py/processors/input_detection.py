"""
Input Detection - Utilities for detecting input types and formats.

This module provides utilities for automatically detecting what type of
input is being provided (URL, file, folder, IPFS, etc.) and extracting
metadata about the input.
"""

from __future__ import annotations

import re
import mimetypes
from pathlib import Path
from typing import Union, Optional
from urllib.parse import urlparse
import logging

from .protocol import InputType

logger = logging.getLogger(__name__)


class InputDetector:
    """
    Detect and classify input sources.
    
    Provides methods for determining input type, extracting metadata,
    and guessing content types for automatic processor routing.
    
    Example:
        >>> detector = InputDetector()
        >>> input_type = detector.detect_type("https://example.com")
        >>> print(input_type)  # InputType.URL
        >>> 
        >>> file_type = detector.detect_file_type("document.pdf")
        >>> print(file_type)  # "pdf"
    """
    
    # Common video extensions
    VIDEO_EXTENSIONS = {
        '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm',
        '.m4v', '.mpg', '.mpeg', '.3gp', '.ogv'
    }
    
    # Common audio extensions
    AUDIO_EXTENSIONS = {
        '.mp3', '.wav', '.ogg', '.flac', '.aac', '.wma', '.m4a',
        '.opus', '.alac', '.ape'
    }
    
    # Common image extensions
    IMAGE_EXTENSIONS = {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp',
        '.tiff', '.tif', '.ico', '.heic', '.heif'
    }
    
    # Common document extensions
    DOCUMENT_EXTENSIONS = {
        '.pdf', '.doc', '.docx', '.odt', '.txt', '.rtf', '.tex',
        '.md', '.rst'
    }
    
    # Common spreadsheet extensions
    SPREADSHEET_EXTENSIONS = {
        '.xls', '.xlsx', '.ods', '.csv', '.tsv'
    }
    
    # Common presentation extensions
    PRESENTATION_EXTENSIONS = {
        '.ppt', '.pptx', '.odp', '.key'
    }
    
    # Common archive extensions
    ARCHIVE_EXTENSIONS = {
        '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar', '.xz',
        '.tar.gz', '.tgz', '.tar.bz2'
    }
    
    # Video streaming domains
    VIDEO_DOMAINS = {
        'youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com',
        'twitch.tv', 'tiktok.com', 'instagram.com'
    }
    
    def __init__(self):
        """Initialize input detector."""
        # Initialize mimetypes
        mimetypes.init()
    
    def detect_type(self, input_source: Union[str, Path]) -> InputType:
        """
        Detect the type of input source.
        
        Args:
            input_source: Input to classify
            
        Returns:
            InputType enum value
            
        Example:
            >>> detector.detect_type("https://example.com")
            InputType.URL
            >>> detector.detect_type("document.pdf")
            InputType.FILE
            >>> detector.detect_type("/path/to/folder")
            InputType.FOLDER
        """
        if isinstance(input_source, str):
            # Check for URLs
            if input_source.startswith(('http://', 'https://')):
                return InputType.URL
            
            # Check for IPFS
            if input_source.startswith('ipfs://') or input_source.startswith('/ipfs/'):
                return InputType.IPFS
            
            # Check if CID (simplified check)
            if self._looks_like_cid(input_source):
                return InputType.IPFS
        
        # Convert to Path for file system checks
        path = Path(input_source)
        
        # Check if exists
        if path.exists():
            if path.is_dir():
                return InputType.FOLDER
            elif path.is_file():
                return InputType.FILE
        else:
            # Doesn't exist, but might be a file path we'll create
            # Check if it has an extension suggesting a file
            if path.suffix:
                return InputType.FILE
        
        return InputType.UNKNOWN
    
    def detect_file_type(self, file_path: Union[str, Path]) -> Optional[str]:
        """
        Detect the type of file based on extension and content.
        
        Args:
            file_path: Path to file
            
        Returns:
            File type identifier (pdf, video, audio, image, etc.) or None
            
        Example:
            >>> detector.detect_file_type("movie.mp4")
            'video'
            >>> detector.detect_file_type("document.pdf")
            'pdf'
        """
        path = Path(file_path)
        ext = path.suffix.lower()
        
        # Check specific types
        if ext == '.pdf':
            return 'pdf'
        elif ext in self.VIDEO_EXTENSIONS:
            return 'video'
        elif ext in self.AUDIO_EXTENSIONS:
            return 'audio'
        elif ext in self.IMAGE_EXTENSIONS:
            return 'image'
        elif ext in self.DOCUMENT_EXTENSIONS:
            return 'document'
        elif ext in self.SPREADSHEET_EXTENSIONS:
            return 'spreadsheet'
        elif ext in self.PRESENTATION_EXTENSIONS:
            return 'presentation'
        elif ext in self.ARCHIVE_EXTENSIONS:
            return 'archive'
        
        # Try MIME type
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type:
            if mime_type.startswith('video/'):
                return 'video'
            elif mime_type.startswith('audio/'):
                return 'audio'
            elif mime_type.startswith('image/'):
                return 'image'
            elif mime_type.startswith('text/'):
                return 'text'
            elif mime_type == 'application/pdf':
                return 'pdf'
        
        return None
    
    def detect_url_type(self, url: str) -> Optional[str]:
        """
        Detect the type of content at a URL.
        
        Args:
            url: URL to classify
            
        Returns:
            URL type identifier (video, webpage, api, etc.) or None
            
        Example:
            >>> detector.detect_url_type("https://youtube.com/watch?v=...")
            'video'
            >>> detector.detect_url_type("https://example.com")
            'webpage'
        """
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        path = parsed.path.lower()
        
        # Check for video streaming sites
        for video_domain in self.VIDEO_DOMAINS:
            if video_domain in domain:
                return 'video'
        
        # Check URL path extension
        if path:
            # Get extension from path
            path_obj = Path(path)
            ext = path_obj.suffix.lower()
            
            if ext in self.VIDEO_EXTENSIONS:
                return 'video'
            elif ext in self.AUDIO_EXTENSIONS:
                return 'audio'
            elif ext in self.IMAGE_EXTENSIONS:
                return 'image'
            elif ext == '.pdf':
                return 'pdf'
            elif ext in self.DOCUMENT_EXTENSIONS:
                return 'document'
        
        # Check for API patterns
        if '/api/' in path or path.endswith(('.json', '.xml')):
            return 'api'
        
        # Default to webpage
        return 'webpage'
    
    def get_mime_type(self, file_path: Union[str, Path]) -> Optional[str]:
        """
        Get MIME type for a file.
        
        Args:
            file_path: Path to file
            
        Returns:
            MIME type string or None
            
        Example:
            >>> detector.get_mime_type("document.pdf")
            'application/pdf'
        """
        mime_type, _ = mimetypes.guess_type(str(file_path))
        return mime_type
    
    def is_video_url(self, url: str) -> bool:
        """
        Check if URL points to a video.
        
        Args:
            url: URL to check
            
        Returns:
            True if video URL, False otherwise
        """
        return self.detect_url_type(url) == 'video'
    
    def is_media_file(self, file_path: Union[str, Path]) -> bool:
        """
        Check if file is a media file (video, audio, or image).
        
        Args:
            file_path: Path to file
            
        Returns:
            True if media file, False otherwise
        """
        file_type = self.detect_file_type(file_path)
        return file_type in ('video', 'audio', 'image')
    
    def _looks_like_cid(self, text: str) -> bool:
        """
        Check if text looks like an IPFS CID.
        
        CIDs typically:
        - Start with 'Qm' (CIDv0) or 'b' (CIDv1 base32)
        - Are 46+ characters for CIDv0, 59+ for CIDv1
        - Contain only base58 (CIDv0) or base32 (CIDv1) characters
        
        Args:
            text: Text to check
            
        Returns:
            True if looks like a CID, False otherwise
        """
        # Remove common prefixes
        text = text.strip()
        if text.startswith('/ipfs/'):
            text = text[6:]
        elif text.startswith('ipfs://'):
            text = text[7:]
        
        # CIDv0: starts with Qm, 46 characters, base58
        if text.startswith('Qm') and len(text) == 46:
            # Check if base58
            base58_pattern = re.compile(r'^[123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz]+$')
            return bool(base58_pattern.match(text))
        
        # CIDv1: starts with b, 59+ characters, base32
        if text.startswith('b') and len(text) >= 59:
            # Check if base32
            base32_pattern = re.compile(r'^[a-z2-7]+$')
            return bool(base32_pattern.match(text))
        
        return False
    
    def extract_filename(self, input_source: Union[str, Path]) -> Optional[str]:
        """
        Extract filename from input source.
        
        Args:
            input_source: Input to extract filename from
            
        Returns:
            Filename or None
            
        Example:
            >>> detector.extract_filename("/path/to/document.pdf")
            'document.pdf'
            >>> detector.extract_filename("https://example.com/file.pdf")
            'file.pdf'
        """
        if isinstance(input_source, Path):
            return input_source.name
        
        # Try as URL
        if input_source.startswith(('http://', 'https://')):
            parsed = urlparse(input_source)
            path = Path(parsed.path)
            if path.name:
                return path.name
        
        # Try as file path
        path = Path(input_source)
        if path.name:
            return path.name
        
        return None
    
    def get_file_extension(self, input_source: Union[str, Path]) -> Optional[str]:
        """
        Get file extension from input source.
        
        Args:
            input_source: Input to extract extension from
            
        Returns:
            Extension (including dot) or None
            
        Example:
            >>> detector.get_file_extension("document.pdf")
            '.pdf'
        """
        filename = self.extract_filename(input_source)
        if filename:
            return Path(filename).suffix.lower()
        return None
    
    def classify_for_routing(self, input_source: Union[str, Path]) -> dict:
        """
        Classify input for processor routing.
        
        Returns comprehensive classification information that can be used
        by UniversalProcessor to select appropriate processors.
        
        Args:
            input_source: Input to classify
            
        Returns:
            Dictionary with classification details:
            {
                "input_type": InputType enum,
                "file_type": str or None,
                "mime_type": str or None,
                "extension": str or None,
                "filename": str or None,
                "is_media": bool,
                "is_video_url": bool,
                "suggested_processors": list[str]
            }
            
        Example:
            >>> info = detector.classify_for_routing("document.pdf")
            >>> print(info["suggested_processors"])
            ['pdf', 'file_converter']
        """
        input_type = self.detect_type(input_source)
        file_type = None
        mime_type = None
        extension = None
        filename = None
        is_media = False
        is_video_url = False
        suggested_processors = []
        
        # Extract metadata based on input type
        if input_type == InputType.FILE:
            file_type = self.detect_file_type(input_source)
            mime_type = self.get_mime_type(input_source)
            extension = self.get_file_extension(input_source)
            filename = self.extract_filename(input_source)
            is_media = self.is_media_file(input_source)
            
            # Suggest processors based on file type
            if file_type == 'pdf':
                suggested_processors.append('pdf')
            elif file_type in ('video', 'audio'):
                suggested_processors.append('multimedia')
            elif file_type == 'image':
                suggested_processors.extend(['image', 'file_converter'])
            
            suggested_processors.append('file_converter')
        
        elif input_type == InputType.URL:
            url_type = self.detect_url_type(str(input_source))
            is_video_url = self.is_video_url(str(input_source))
            
            if url_type == 'video':
                suggested_processors.append('multimedia')
            elif url_type == 'webpage':
                suggested_processors.append('graphrag')
            elif url_type == 'pdf':
                suggested_processors.extend(['pdf', 'graphrag'])
            else:
                suggested_processors.append('graphrag')
        
        elif input_type == InputType.FOLDER:
            suggested_processors.append('batch')
        
        elif input_type == InputType.IPFS:
            suggested_processors.append('ipfs')
        
        return {
            "input_type": input_type,
            "file_type": file_type,
            "mime_type": mime_type,
            "extension": extension,
            "filename": filename,
            "is_media": is_media,
            "is_video_url": is_video_url,
            "suggested_processors": suggested_processors
        }


# Global detector instance (optional convenience)
_global_detector: Optional[InputDetector] = None


def get_global_detector() -> InputDetector:
    """
    Get or create the global input detector.
    
    Returns:
        Global InputDetector instance
    """
    global _global_detector
    if _global_detector is None:
        _global_detector = InputDetector()
    return _global_detector


# Convenience functions
def detect_input_type(input_source: Union[str, Path]) -> InputType:
    """Detect input type using global detector."""
    return get_global_detector().detect_type(input_source)


def detect_file_type(file_path: Union[str, Path]) -> Optional[str]:
    """Detect file type using global detector."""
    return get_global_detector().detect_file_type(file_path)


def classify_input(input_source: Union[str, Path]) -> dict:
    """Classify input for routing using global detector."""
    return get_global_detector().classify_for_routing(input_source)
