"""
Enhanced File Type Detection for GraphRAG System

This module provides comprehensive file type detection using multiple methods:
1. File extension analysis (Python mimetypes)
2. Magic bytes detection (python-magic library)
3. Google's Magika AI (Python-only, no Rust)

Features:
- Multiple detection strategies (FAST, ACCURATE, VOTING, CONSERVATIVE)
- Support for file paths and byte streams
- Graceful fallback when methods unavailable
- Thread-safe operations
- Offline support
"""

import logging
import mimetypes
import os
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Union, Any
import threading

logger = logging.getLogger(__name__)

# Optional dependencies with graceful fallback
try:
    import magic
    HAVE_MAGIC = True
except ImportError:
    HAVE_MAGIC = False
    logger.warning("python-magic not available, magic bytes detection disabled")

try:
    from magika import Magika
    HAVE_MAGIKA = True
except ImportError:
    HAVE_MAGIKA = False
    logger.warning("magika not available, AI detection disabled")


class DetectionMethod(str, Enum):
    """Supported file type detection methods"""
    EXTENSION = "extension"
    MAGIC = "magic"
    MAGIKA = "magika"
    ALL = "all"


class DetectionStrategy(str, Enum):
    """Detection strategies for combining multiple methods"""
    FAST = "fast"  # extension → magic (fastest)
    ACCURATE = "accurate"  # magika → magic → extension (most accurate)
    VOTING = "voting"  # all methods, consensus wins
    CONSERVATIVE = "conservative"  # extension → magic → magika (safest)


class FileTypeDetector:
    """
    Comprehensive file type detector using multiple detection methods.
    
    This class provides robust file type detection with support for multiple
    detection methods and strategies. It handles both file paths and byte streams,
    with graceful fallback when optional dependencies are unavailable.
    
    Attributes:
        _lock (threading.Lock): Thread lock for thread-safe operations
        _magika (Optional[Magika]): Magika instance for AI detection
        _magic (Optional[magic.Magic]): Magic instance for magic bytes detection
    
    Example:
        >>> detector = FileTypeDetector()
        >>> result = detector.detect_type('document.pdf')
        >>> print(result['mime_type'])
        'application/pdf'
    """
    
    def __init__(self):
        """Initialize the file type detector with available methods."""
        self._lock = threading.Lock()
        self._magika = None
        self._magic = None
        
        # Initialize Magika if available
        if HAVE_MAGIKA:
            try:
                self._magika = Magika()
                logger.info("Magika AI detector initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize Magika: {e}")
                self._magika = None
        
        # Initialize python-magic if available
        if HAVE_MAGIC:
            try:
                self._magic = magic.Magic(mime=True)
                logger.info("Magic bytes detector initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize python-magic: {e}")
                self._magic = None
        
        # Initialize mimetypes
        if not mimetypes.inited:
            mimetypes.init()
    
    def detect_type(
        self,
        file_path_or_bytes: Union[str, Path, bytes],
        methods: Optional[List[str]] = None,
        strategy: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Detect file type using specified methods and strategy.
        
        Args:
            file_path_or_bytes: File path (str/Path) or file content (bytes)
            methods: List of detection methods to use (default: ['magika', 'magic', 'extension'])
            strategy: Detection strategy to use (default: 'accurate')
        
        Returns:
            Dict with keys:
                - mime_type: Detected MIME type
                - extension: File extension
                - confidence: Detection confidence (0.0-1.0)
                - method: Method used for final detection
                - all_results: Results from all methods attempted
        
        Example:
            >>> detector = FileTypeDetector()
            >>> result = detector.detect_type('/path/to/file.pdf')
            >>> print(result)
            {
                'mime_type': 'application/pdf',
                'extension': '.pdf',
                'confidence': 0.95,
                'method': 'magika',
                'all_results': {...}
            }
        """
        # Convert to list if single method provided
        if isinstance(methods, str):
            methods = [methods]
        
        # Determine default behavior
        if methods is None and strategy is None:
            # No parameters provided, use accurate strategy with all methods
            methods = ['magika', 'magic', 'extension']
            strategy = 'accurate'
        elif methods is not None and strategy is None:
            # Methods specified but no strategy - use methods directly
            strategy = None  # Will use _detect_by_methods
        elif methods is None and strategy is not None:
            # Strategy specified but no methods - use default methods for strategy
            methods = ['magika', 'magic', 'extension']
        # else: both specified, use both
        
        # Validate strategy if provided
        if strategy is not None and strategy not in [s.value for s in DetectionStrategy]:
            logger.warning(f"Invalid strategy '{strategy}', using method-based detection")
            strategy = None
        
        # Get file path and bytes
        file_path = None
        file_bytes = None
        
        if isinstance(file_path_or_bytes, bytes):
            file_bytes = file_path_or_bytes
        else:
            file_path = Path(file_path_or_bytes)
            if not file_path.exists():
                return self._error_result(f"File not found: {file_path}")
        
        # Apply detection strategy
        try:
            # If no strategy specified, use methods directly
            if strategy is None:
                return self._detect_by_methods(file_path, file_bytes, methods)
            elif strategy == DetectionStrategy.FAST.value:
                return self._detect_fast(file_path, file_bytes)
            elif strategy == DetectionStrategy.ACCURATE.value:
                return self._detect_accurate(file_path, file_bytes)
            elif strategy == DetectionStrategy.VOTING.value:
                return self._detect_voting(file_path, file_bytes, methods)
            elif strategy == DetectionStrategy.CONSERVATIVE.value:
                return self._detect_conservative(file_path, file_bytes)
            else:
                # Fallback to method-based detection
                return self._detect_by_methods(file_path, file_bytes, methods)
        except Exception as e:
            logger.error(f"Detection failed: {e}")
            return self._error_result(str(e))
    
    def _detect_fast(
        self,
        file_path: Optional[Path],
        file_bytes: Optional[bytes]
    ) -> Dict[str, Any]:
        """Fast detection: extension → magic"""
        all_results = {}
        
        # Try extension first (fastest)
        if file_path:
            ext_result = self._detect_by_extension(file_path)
            all_results['extension'] = ext_result
            if ext_result.get('mime_type'):
                ext_result['all_results'] = all_results
                return ext_result
        
        # Try magic bytes
        magic_result = self._detect_by_magic(file_path, file_bytes)
        all_results['magic'] = magic_result
        if magic_result.get('mime_type'):
            magic_result['all_results'] = all_results
            return magic_result
        
        # Return best available result
        return self._select_best_result(all_results)
    
    def _detect_accurate(
        self,
        file_path: Optional[Path],
        file_bytes: Optional[bytes]
    ) -> Dict[str, Any]:
        """Accurate detection: magika → magic → extension"""
        all_results = {}
        
        # Try Magika first (most accurate)
        magika_result = self._detect_by_magika(file_path, file_bytes)
        all_results['magika'] = magika_result
        if magika_result.get('confidence', 0) > 0.7:
            magika_result['all_results'] = all_results
            return magika_result
        
        # Try magic bytes
        magic_result = self._detect_by_magic(file_path, file_bytes)
        all_results['magic'] = magic_result
        if magic_result.get('mime_type'):
            magic_result['all_results'] = all_results
            return magic_result
        
        # Try extension
        if file_path:
            ext_result = self._detect_by_extension(file_path)
            all_results['extension'] = ext_result
            if ext_result.get('mime_type'):
                ext_result['all_results'] = all_results
                return ext_result
        
        # Return best available result
        return self._select_best_result(all_results)
    
    def _detect_voting(
        self,
        file_path: Optional[Path],
        file_bytes: Optional[bytes],
        methods: List[str]
    ) -> Dict[str, Any]:
        """Voting detection: all methods, consensus wins"""
        all_results = {}
        
        # Run all requested methods
        if 'extension' in methods and file_path:
            all_results['extension'] = self._detect_by_extension(file_path)
        if 'magic' in methods:
            all_results['magic'] = self._detect_by_magic(file_path, file_bytes)
        if 'magika' in methods:
            all_results['magika'] = self._detect_by_magika(file_path, file_bytes)
        
        # Count votes for each MIME type
        mime_votes = {}
        for method, result in all_results.items():
            mime_type = result.get('mime_type')
            if mime_type:
                mime_votes[mime_type] = mime_votes.get(mime_type, 0) + 1
        
        # Select MIME type with most votes
        if mime_votes:
            winning_mime = max(mime_votes.items(), key=lambda x: x[1])[0]
            
            # Find result with winning MIME type and highest confidence
            best_result = None
            best_confidence = 0
            for method, result in all_results.items():
                if result.get('mime_type') == winning_mime:
                    confidence = result.get('confidence', 0.5)
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_result = result
            
            if best_result:
                best_result['all_results'] = all_results
                best_result['votes'] = mime_votes
                return best_result
        
        # Return best available result
        return self._select_best_result(all_results)
    
    def _detect_conservative(
        self,
        file_path: Optional[Path],
        file_bytes: Optional[bytes]
    ) -> Dict[str, Any]:
        """Conservative detection: extension → magic → magika"""
        all_results = {}
        
        # Try extension first (safest, most predictable)
        if file_path:
            ext_result = self._detect_by_extension(file_path)
            all_results['extension'] = ext_result
            if ext_result.get('mime_type'):
                # Verify with magic bytes if available
                magic_result = self._detect_by_magic(file_path, file_bytes)
                all_results['magic'] = magic_result
                if magic_result.get('mime_type') == ext_result.get('mime_type'):
                    # Both agree, high confidence
                    ext_result['confidence'] = 0.9
                    ext_result['all_results'] = all_results
                    return ext_result
        
        # Extension not available or no match, try magic
        if 'magic' not in all_results:
            magic_result = self._detect_by_magic(file_path, file_bytes)
            all_results['magic'] = magic_result
            if magic_result.get('mime_type'):
                magic_result['all_results'] = all_results
                return magic_result
        
        # Try Magika as last resort
        magika_result = self._detect_by_magika(file_path, file_bytes)
        all_results['magika'] = magika_result
        if magika_result.get('mime_type'):
            magika_result['all_results'] = all_results
            return magika_result
        
        # Return best available result
        return self._select_best_result(all_results)
    
    def _detect_by_methods(
        self,
        file_path: Optional[Path],
        file_bytes: Optional[bytes],
        methods: List[str]
    ) -> Dict[str, Any]:
        """Detect using specified methods in order"""
        all_results = {}
        
        for method in methods:
            if method == 'extension' and file_path:
                result = self._detect_by_extension(file_path)
            elif method == 'magic':
                result = self._detect_by_magic(file_path, file_bytes)
            elif method == 'magika':
                result = self._detect_by_magika(file_path, file_bytes)
            else:
                continue
            
            all_results[method] = result
            if result.get('mime_type'):
                result['all_results'] = all_results
                return result
        
        return self._select_best_result(all_results)
    
    def _detect_by_extension(self, file_path: Path) -> Dict[str, Any]:
        """Detect file type by extension using Python mimetypes"""
        try:
            extension = file_path.suffix.lower()
            mime_type, _ = mimetypes.guess_type(str(file_path))
            
            if mime_type:
                return {
                    'mime_type': mime_type,
                    'extension': extension,
                    'confidence': 0.7,
                    'method': 'extension'
                }
            else:
                return {
                    'mime_type': None,
                    'extension': extension,
                    'confidence': 0.0,
                    'method': 'extension',
                    'error': 'Unknown extension'
                }
        except Exception as e:
            return self._error_result(f"Extension detection failed: {e}", 'extension')
    
    def _detect_by_magic(
        self,
        file_path: Optional[Path],
        file_bytes: Optional[bytes]
    ) -> Dict[str, Any]:
        """Detect file type by magic bytes using python-magic"""
        if not HAVE_MAGIC or not self._magic:
            return self._error_result("python-magic not available", 'magic')
        
        try:
            with self._lock:
                if file_bytes:
                    mime_type = self._magic.from_buffer(file_bytes)
                elif file_path:
                    mime_type = self._magic.from_file(str(file_path))
                else:
                    return self._error_result("No file path or bytes provided", 'magic')
            
            extension = mimetypes.guess_extension(mime_type) or ''
            
            return {
                'mime_type': mime_type,
                'extension': extension,
                'confidence': 0.85,
                'method': 'magic'
            }
        except Exception as e:
            return self._error_result(f"Magic bytes detection failed: {e}", 'magic')
    
    def _detect_by_magika(
        self,
        file_path: Optional[Path],
        file_bytes: Optional[bytes]
    ) -> Dict[str, Any]:
        """Detect file type using Magika AI"""
        if not HAVE_MAGIKA or not self._magika:
            return self._error_result("Magika not available", 'magika')
        
        try:
            with self._lock:
                if file_bytes:
                    result = self._magika.identify_bytes(file_bytes)
                elif file_path:
                    result = self._magika.identify_path(file_path)
                else:
                    return self._error_result("No file path or bytes provided", 'magika')
            
            # Extract result information from Magika result
            # score is on the result object itself (MagikaResult)
            # other fields are on result.output
            mime_type = result.output.mime_type
            extension = f".{result.output.label}" if result.output.label else ''
            confidence = result.score  # Score is on MagikaResult, not output
            label = result.output.label
            group = result.output.group
            
            return {
                'mime_type': mime_type,
                'extension': extension,
                'confidence': confidence,
                'method': 'magika',
                'label': label,
                'group': group
            }
        except Exception as e:
            return self._error_result(f"Magika detection failed: {e}", 'magika')
    
    def _select_best_result(self, all_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Select the best result from all available results"""
        if not all_results:
            return self._error_result("No detection methods succeeded")
        
        # Find result with highest confidence
        best_result = None
        best_confidence = -1
        
        for method, result in all_results.items():
            if result.get('mime_type'):
                confidence = result.get('confidence', 0)
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_result = result
        
        if best_result:
            best_result['all_results'] = all_results
            return best_result
        
        # No result with MIME type, return first error
        for result in all_results.values():
            if result:
                result['all_results'] = all_results
                return result
        
        return self._error_result("All detection methods failed")
    
    def _error_result(
        self,
        error: str,
        method: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create an error result"""
        return {
            'mime_type': None,
            'extension': None,
            'confidence': 0.0,
            'method': method or 'unknown',
            'error': error,
            'all_results': {}
        }
    
    def batch_detect(
        self,
        file_paths: List[Union[str, Path]],
        methods: Optional[List[str]] = None,
        strategy: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Detect file types for multiple files.
        
        Args:
            file_paths: List of file paths to analyze
            methods: Detection methods to use
            strategy: Detection strategy to use
        
        Returns:
            Dict mapping file paths to detection results
        """
        results = {}
        for file_path in file_paths:
            try:
                result = self.detect_type(file_path, methods=methods, strategy=strategy)
                results[str(file_path)] = result
            except Exception as e:
                logger.error(f"Failed to detect type for {file_path}: {e}")
                results[str(file_path)] = self._error_result(str(e))
        return results
    
    def get_available_methods(self) -> List[str]:
        """Get list of available detection methods"""
        methods = ['extension']  # Always available
        if HAVE_MAGIC and self._magic:
            methods.append('magic')
        if HAVE_MAGIKA and self._magika:
            methods.append('magika')
        return methods
    
    def get_supported_strategies(self) -> List[str]:
        """Get list of supported detection strategies"""
        return [s.value for s in DetectionStrategy]
