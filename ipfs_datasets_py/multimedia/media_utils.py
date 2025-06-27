"""
Media utilities for common multimedia operations.

This module provides utility functions for working with media files,
formats, metadata, and validation.
"""

import logging
import mimetypes
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Set

logger = logging.getLogger(__name__)


class MediaUtils:
    """
    Utility functions for multimedia operations.
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
        Determine the type of media file.
        
        Args:
            file_path: Path to the media file
            
        Returns:
            Media type ('video', 'audio', 'image') or None
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
        Check if file is a supported media file.
        
        Args:
            file_path: Path to check
            
        Returns:
            True if file is a supported media type
        """
        return cls.get_file_type(file_path) is not None
    
    @classmethod
    def get_supported_formats(cls) -> Dict[str, Set[str]]:
        """
        Get all supported media formats by type.
        
        Returns:
            Dict mapping media types to supported formats
        """
        return {
            "video": cls.VIDEO_FORMATS,
            "audio": cls.AUDIO_FORMATS,
            "image": cls.IMAGE_FORMATS
        }
    
    @classmethod
    def validate_url(cls, url: str) -> bool:
        """
        Basic URL validation for media sources.
        
        Args:
            url: URL to validate
            
        Returns:
            True if URL appears valid
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
        Get MIME type for a media file.
        
        Args:
            file_path: Path to the media file
            
        Returns:
            MIME type string or None
        """
        try:
            mime_type, _ = mimetypes.guess_type(str(file_path))
            return mime_type
        except Exception:
            return None
    
    @classmethod
    def format_file_size(cls, size_bytes: int) -> str:
        """
        Format file size in human-readable format.
        
        Args:
            size_bytes: Size in bytes
            
        Returns:
            Formatted size string
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
        Format duration in human-readable format.
        
        Args:
            seconds: Duration in seconds
            
        Returns:
            Formatted duration string (HH:MM:SS)
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
        Sanitize filename for safe file system usage.
        
        Args:
            filename: Original filename
            
        Returns:
            Sanitized filename
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
