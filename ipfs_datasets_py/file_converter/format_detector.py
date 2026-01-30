"""
Format detection utilities for native file converter.

Provides MIME type detection and format identification without requiring
external magic libraries (though they can enhance detection if available).

Phase 2 Feature: Native format detection combining:
- Magic number detection (file signatures)
- Extension-based detection
- Content analysis
- URL/protocol detection
"""

from pathlib import Path
from typing import Optional, Union
import logging

logger = logging.getLogger(__name__)


# Common file signatures (magic numbers)
MAGIC_SIGNATURES = {
    # Documents
    b'%PDF': 'application/pdf',
    b'PK\x03\x04': 'application/zip',  # Also DOCX, XLSX, etc.
    b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1': 'application/msword',  # Old Office
    
    # Images
    b'\xff\xd8\xff': 'image/jpeg',
    b'\x89PNG\r\n\x1a\n': 'image/png',
    b'GIF87a': 'image/gif',
    b'GIF89a': 'image/gif',
    b'RIFF': 'image/webp',  # Or audio/wav - needs further check
    b'<svg': 'image/svg+xml',
    # Note: <?xml is ambiguous - could be any XML. Check content in _detect_text_format
    
    # Audio/Video
    b'ID3': 'audio/mpeg',  # MP3
    b'\xff\xfb': 'audio/mpeg',  # MP3
    b'\xff\xf3': 'audio/mpeg',  # MP3
    b'fLaC': 'audio/flac',
    b'\x00\x00\x00\x18ftypmp42': 'video/mp4',
    b'\x00\x00\x00\x20ftypisom': 'video/mp4',
    
    # Archives
    b'\x1f\x8b': 'application/gzip',
    b'BZh': 'application/x-bzip2',
    b'Rar!': 'application/x-rar-compressed',
    b'7z\xbc\xaf\x27\x1c': 'application/x-7z-compressed',
}

# Extension to MIME type mapping
EXTENSION_MIME_TYPES = {
    # Text formats
    '.txt': 'text/plain',
    '.md': 'text/markdown',
    '.markdown': 'text/markdown',
    '.rst': 'text/x-rst',
    '.log': 'text/plain',
    
    # Documents
    '.pdf': 'application/pdf',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xls': 'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.ppt': 'application/vnd.ms-powerpoint',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.odt': 'application/vnd.oasis.opendocument.text',
    '.ods': 'application/vnd.oasis.opendocument.spreadsheet',
    '.odp': 'application/vnd.oasis.opendocument.presentation',
    '.rtf': 'application/rtf',
    
    # Web/Markup
    '.html': 'text/html',
    '.htm': 'text/html',
    '.xml': 'application/xml',
    '.xhtml': 'application/xhtml+xml',
    '.css': 'text/css',
    '.js': 'application/javascript',
    '.json': 'application/json',
    '.yaml': 'application/x-yaml',
    '.yml': 'application/x-yaml',
    
    # Data
    '.csv': 'text/csv',
    '.tsv': 'text/tab-separated-values',
    '.sql': 'application/sql',
    
    # Images
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.bmp': 'image/bmp',
    '.webp': 'image/webp',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.tif': 'image/tiff',
    '.tiff': 'image/tiff',
    
    # Audio
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.ogg': 'audio/ogg',
    '.flac': 'audio/flac',
    '.aac': 'audio/aac',
    '.m4a': 'audio/mp4',
    '.wma': 'audio/x-ms-wma',
    
    # Video
    '.mp4': 'video/mp4',
    '.avi': 'video/x-msvideo',
    '.mov': 'video/quicktime',
    '.wmv': 'video/x-ms-wmv',
    '.flv': 'video/x-flv',
    '.webm': 'video/webm',
    '.mkv': 'video/x-matroska',
    '.m4v': 'video/x-m4v',
    
    # Archives
    '.zip': 'application/zip',
    '.tar': 'application/x-tar',
    '.gz': 'application/gzip',
    '.bz2': 'application/x-bzip2',
    '.rar': 'application/x-rar-compressed',
    '.7z': 'application/x-7z-compressed',
}

# MIME type to format category
MIME_CATEGORIES = {
    'text': ['text/plain', 'text/markdown', 'text/html', 'text/css', 'text/csv'],
    'document': [
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    ],
    'image': ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml'],
    'audio': ['audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/flac'],
    'video': ['video/mp4', 'video/webm', 'video/x-msvideo', 'video/quicktime'],
    'archive': ['application/zip', 'application/x-tar', 'application/gzip'],
}


class FormatDetector:
    """
    Native format detection without external dependencies.
    
    Uses a combination of:
    1. Magic number detection (file signatures)
    2. File extension analysis
    3. Content analysis for text formats
    4. Optional python-magic if available
    
    Examples:
        detector = FormatDetector()
        mime_type = detector.detect_file('document.pdf')
        # Returns: 'application/pdf'
        
        category = detector.get_category('image/jpeg')
        # Returns: 'image'
    """
    
    def __init__(self, use_magic: bool = True):
        """
        Initialize format detector.
        
        Args:
            use_magic: Try to use python-magic library if available
        """
        self.use_magic = use_magic
        self._magic_available = False
        
        if use_magic:
            try:
                import magic
                self._magic = magic.Magic(mime=True)
                self._magic_available = True
                logger.debug("python-magic available for enhanced detection")
            except ImportError:
                logger.debug("python-magic not available, using native detection")
    
    def detect_file(self, file_path: Union[str, Path]) -> Optional[str]:
        """
        Detect MIME type of a file.
        
        Args:
            file_path: Path to file
            
        Returns:
            MIME type string or None if detection fails
            
        Example:
            mime_type = detector.detect_file('image.jpg')
            # Returns: 'image/jpeg'
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            logger.warning(f"File does not exist: {file_path}")
            return None
        
        # Try python-magic first if available
        if self._magic_available:
            try:
                mime_type = self._magic.from_file(str(file_path))
                logger.debug(f"Detected {file_path.name} as {mime_type} (magic)")
                return mime_type
            except Exception as e:
                logger.debug(f"Magic detection failed: {e}")
        
        # Try magic number detection
        mime_type = self._detect_by_magic_number(file_path)
        if mime_type:
            logger.debug(f"Detected {file_path.name} as {mime_type} (signature)")
            return mime_type
        
        # Try content analysis for text files
        if self._is_text_file(file_path):
            mime_type = self._detect_text_format(file_path)
            if mime_type:
                logger.debug(f"Detected {file_path.name} as {mime_type} (content)")
                return mime_type
        
        # Fall back to extension
        mime_type = self._detect_by_extension(file_path)
        if mime_type:
            logger.debug(f"Detected {file_path.name} as {mime_type} (extension)")
            return mime_type
        
        logger.warning(f"Could not detect MIME type for {file_path}")
        return None
    
    def _detect_by_magic_number(self, file_path: Path) -> Optional[str]:
        """Detect MIME type by reading file signature."""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(32)  # Read first 32 bytes
                
                # Check against known signatures
                for signature, mime_type in MAGIC_SIGNATURES.items():
                    if header.startswith(signature):
                        # Special handling for ZIP-based formats
                        if mime_type == 'application/zip':
                            return self._detect_zip_variant(file_path)
                        return mime_type
                
        except Exception as e:
            logger.debug(f"Magic number detection failed: {e}")
        
        return None
    
    def _detect_zip_variant(self, file_path: Path) -> str:
        """Detect specific type of ZIP-based file (DOCX, XLSX, etc.)."""
        # Check extension for Office formats
        ext = file_path.suffix.lower()
        if ext in ['.docx', '.xlsx', '.pptx', '.odt', '.ods', '.odp']:
            return EXTENSION_MIME_TYPES.get(ext, 'application/zip')
        
        return 'application/zip'
    
    def _detect_by_extension(self, file_path: Path) -> Optional[str]:
        """Detect MIME type by file extension."""
        ext = file_path.suffix.lower()
        return EXTENSION_MIME_TYPES.get(ext)
    
    def _is_text_file(self, file_path: Path, sample_size: int = 512) -> bool:
        """Check if file appears to be text (not binary)."""
        try:
            with open(file_path, 'rb') as f:
                sample = f.read(sample_size)
                
            # Check for null bytes (common in binary files)
            if b'\x00' in sample:
                return False
            
            # Try to decode as UTF-8
            try:
                sample.decode('utf-8')
                return True
            except UnicodeDecodeError:
                pass
            
            # Try other common encodings
            for encoding in ['latin-1', 'cp1252']:
                try:
                    sample.decode(encoding)
                    return True
                except UnicodeDecodeError:
                    continue
                    
        except Exception as e:
            logger.debug(f"Text detection failed: {e}")
        
        return False
    
    def _detect_text_format(self, file_path: Path) -> Optional[str]:
        """Detect specific text format by content analysis."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(512)  # Read first 512 chars
            
            # Check for specific formats
            content_lower = content.lower()
            content_stripped = content.strip()
            
            # XML detection (before HTML which might also have XML declaration)
            if content_stripped.startswith('<?xml'):
                # Check if it's SVG - look for svg tag in the content
                if '<svg' in content_lower:
                    return 'image/svg+xml'
                return 'application/xml'
            
            # HTML detection
            if content_stripped.startswith('<!DOCTYPE html') or '<html' in content_lower:
                return 'text/html'
            
            # JSON detection
            if content_stripped.startswith('{') and '"' in content:
                return 'application/json'
            
            # YAML detection
            if content_stripped.startswith('---\n') or '\n---\n' in content:
                return 'application/x-yaml'
            
            # CSV detection
            if ',' in content and '\n' in content:
                # Might be CSV
                lines = content.strip().split('\n')
                if len(lines) > 1 and all(',' in line for line in lines[:3]):
                    return 'text/csv'
            
            # Check extension for markdown
            if file_path.suffix.lower() in ['.md', '.markdown']:
                return 'text/markdown'
            
            # Default to plain text
            return 'text/plain'
            
        except Exception as e:
            logger.debug(f"Text format detection failed: {e}")
        
        return None
    
    def get_category(self, mime_type: str) -> Optional[str]:
        """
        Get format category for a MIME type.
        
        Args:
            mime_type: MIME type string
            
        Returns:
            Category name ('text', 'document', 'image', etc.) or None
            
        Example:
            category = detector.get_category('image/jpeg')
            # Returns: 'image'
        """
        for category, mime_types in MIME_CATEGORIES.items():
            if mime_type in mime_types:
                return category
        
        # Check by prefix
        if mime_type.startswith('text/'):
            return 'text'
        if mime_type.startswith('image/'):
            return 'image'
        if mime_type.startswith('audio/'):
            return 'audio'
        if mime_type.startswith('video/'):
            return 'video'
        if mime_type.startswith('application/'):
            return 'document'
        
        return None
    
    def get_extension(self, mime_type: str) -> Optional[str]:
        """
        Get common file extension for a MIME type.
        
        Args:
            mime_type: MIME type string
            
        Returns:
            File extension (with dot) or None
            
        Example:
            ext = detector.get_extension('image/jpeg')
            # Returns: '.jpg'
        """
        # Reverse lookup in extension map
        for ext, mt in EXTENSION_MIME_TYPES.items():
            if mt == mime_type:
                return ext
        
        return None
    
    def is_supported(self, file_path: Union[str, Path]) -> bool:
        """
        Check if file format is supported for conversion.
        
        Args:
            file_path: Path to file
            
        Returns:
            True if format is supported
        """
        mime_type = self.detect_file(file_path)
        if not mime_type:
            return False
        
        # Check if we have a category for this MIME type
        category = self.get_category(mime_type)
        return category is not None


# Singleton instance for easy access
_default_detector = None

def get_detector() -> FormatDetector:
    """Get singleton format detector instance."""
    global _default_detector
    if _default_detector is None:
        _default_detector = FormatDetector()
    return _default_detector


def detect_format(file_path: Union[str, Path]) -> Optional[str]:
    """
    Convenience function to detect file format.
    
    Args:
        file_path: Path to file
        
    Returns:
        MIME type string or None
        
    Example:
        mime_type = detect_format('document.pdf')
        # Returns: 'application/pdf'
    """
    return get_detector().detect_file(file_path)
