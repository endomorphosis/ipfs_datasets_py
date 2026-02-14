"""
Detect File Type MCP Tool

Detects the file type of a single file using specified methods and strategy.
"""

import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.utils.file_detector import FileTypeDetector
    HAVE_DETECTOR = True
except ImportError:
    HAVE_DETECTOR = False
    logger.warning("FileTypeDetector not available")


def detect_file_type(
    file_path: str,
    methods: Optional[List[str]] = None,
    strategy: Optional[str] = None
) -> Dict[str, Any]:
    """
    Detect file type using specified methods and strategy.
    
    This tool uses multiple detection methods to identify file types:
    - extension: Python mimetypes based on file extension
    - magic: Magic bytes detection using python-magic
    - magika: AI-powered detection using Google's Magika
    
    Strategies combine methods in different ways:
    - fast: extension → magic (fastest)
    - accurate: magika → magic → extension (most accurate)
    - voting: all methods, consensus wins
    - conservative: extension → magic → magika (safest)
    
    Args:
        file_path: Path to the file to analyze
        methods: List of detection methods to use (extension, magic, magika, all)
                Default: ['magika', 'magic', 'extension']
        strategy: Detection strategy (fast, accurate, voting, conservative)
                 If specified, overrides methods parameter
    
    Returns:
        Dict with detection results:
            - mime_type: Detected MIME type
            - extension: File extension
            - confidence: Detection confidence (0.0-1.0)
            - method: Method used for final detection
            - all_results: Results from all methods attempted
            - error: Error message if detection failed
    
    Example:
        >>> detect_file_type('/path/to/document.pdf', strategy='accurate')
        {
            'mime_type': 'application/pdf',
            'extension': '.pdf',
            'confidence': 0.95,
            'method': 'magika',
            'all_results': {...}
        }
    """
    if not HAVE_DETECTOR:
        return {
            'error': 'FileTypeDetector not available',
            'mime_type': None,
            'extension': None,
            'confidence': 0.0,
            'method': 'none'
        }
    
    try:
        detector = FileTypeDetector()
        result = detector.detect_type(file_path, methods=methods, strategy=strategy)
        return result
    except Exception as e:
        logger.error(f"File type detection failed: {e}")
        return {
            'error': str(e),
            'mime_type': None,
            'extension': None,
            'confidence': 0.0,
            'method': 'error'
        }
