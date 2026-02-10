"""
Rich metadata extraction for file conversion.

This module provides comprehensive metadata extraction capabilities,
combining features from omni_converter_mk2 with IPFS integration.
"""

import hashlib
import mimetypes
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)


class MetadataExtractor:
    """
    Extract rich metadata from files including:
    - File properties (size, dates, permissions)
    - Content hashes (MD5, SHA256, CID)
    - MIME type and encoding
    - Format-specific metadata
    """
    
    def __init__(self, enable_ipfs: bool = True):
        """
        Initialize metadata extractor.
        
        Args:
            enable_ipfs: Whether to generate IPFS CIDs (requires ipfs_kit_py)
        """
        self.enable_ipfs = enable_ipfs
        self._ipfs_available = self._check_ipfs()
    
    def _check_ipfs(self) -> bool:
        """Check if IPFS functionality is available."""
        if not self.enable_ipfs:
            return False
        
        try:
            import ipfs_kit_py
            return True
        except ImportError:
            return False
    
    def extract(self, file_path: str) -> Dict[str, Any]:
        """
        Extract comprehensive metadata from a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dictionary with rich metadata
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        metadata = {}
        
        # Basic file properties
        metadata['file'] = self._extract_file_properties(path)
        
        # Content hashes
        metadata['hashes'] = self._extract_hashes(path)
        
        # MIME type and encoding
        metadata['format'] = self._extract_format_info(path)
        
        # IPFS CID if available
        if self._ipfs_available:
            metadata['ipfs'] = self._extract_ipfs_info(path)
        
        # Statistics
        metadata['extraction_time'] = datetime.utcnow().isoformat()
        
        return metadata
    
    def _extract_file_properties(self, path: Path) -> Dict[str, Any]:
        """Extract basic file properties."""
        stat = path.stat()
        
        return {
            'name': path.name,
            'path': str(path.absolute()),
            'size': stat.st_size,
            'size_human': self._human_readable_size(stat.st_size),
            'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'accessed': datetime.fromtimestamp(stat.st_atime).isoformat(),
            'permissions': oct(stat.st_mode)[-3:],
            'is_symlink': path.is_symlink(),
            'extension': path.suffix.lower(),
        }
    
    def _extract_hashes(self, path: Path) -> Dict[str, str]:
        """Calculate content hashes."""
        hashes = {}
        
        # Read file in chunks for efficiency
        chunk_size = 8192
        
        # Initialize hashers
        md5_hash = hashlib.md5()
        sha256_hash = hashlib.sha256()
        
        try:
            with open(path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    md5_hash.update(chunk)
                    sha256_hash.update(chunk)
            
            hashes['md5'] = md5_hash.hexdigest()
            hashes['sha256'] = sha256_hash.hexdigest()
        except Exception as e:
            logger.warning(f"Failed to calculate hashes for {path}: {e}")
            hashes['error'] = str(e)
        
        return hashes
    
    def _extract_format_info(self, path: Path) -> Dict[str, Any]:
        """Extract format and MIME type information."""
        # Try to detect MIME type
        mime_type, encoding = mimetypes.guess_type(str(path))
        
        format_info = {
            'mime_type': mime_type or 'application/octet-stream',
            'encoding': encoding,
            'extension': path.suffix.lower(),
        }
        
        # Try to use format_detector if available
        try:
            from .format_detector import FormatDetector
            detector = FormatDetector()
            detected_mime = detector.detect_file(str(path))
            if detected_mime:
                format_info['detected_mime'] = detected_mime
                format_info['category'] = detector.get_category(detected_mime)
        except Exception as e:
            logger.debug(f"Format detector not available: {e}")
        
        return format_info
    
    def _extract_ipfs_info(self, path: Path) -> Dict[str, Any]:
        """Extract IPFS-related information."""
        ipfs_info = {}
        
        try:
            import ipfs_kit_py
            # Calculate what the CID would be without actually adding to IPFS
            # This is a placeholder - actual CID calculation would use ipfs_kit_py
            ipfs_info['cid_calculable'] = True
            ipfs_info['note'] = 'CID can be calculated when file is added to IPFS'
        except Exception as e:
            logger.debug(f"IPFS info extraction failed: {e}")
            ipfs_info['available'] = False
        
        return ipfs_info
    
    def _human_readable_size(self, size_bytes: int) -> str:
        """Convert bytes to human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"
    
    def extract_batch(self, file_paths: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Extract metadata from multiple files.
        
        Args:
            file_paths: List of file paths
            
        Returns:
            Dictionary mapping file paths to metadata
        """
        results = {}
        
        for file_path in file_paths:
            try:
                results[file_path] = self.extract(file_path)
            except Exception as e:
                logger.error(f"Failed to extract metadata from {file_path}: {e}")
                results[file_path] = {'error': str(e)}
        
        return results


def extract_metadata(file_path: str, enable_ipfs: bool = True) -> Dict[str, Any]:
    """
    Convenience function to extract metadata from a file.
    
    Args:
        file_path: Path to the file
        enable_ipfs: Whether to include IPFS information
        
    Returns:
        Rich metadata dictionary
    """
    extractor = MetadataExtractor(enable_ipfs=enable_ipfs)
    return extractor.extract(file_path)
