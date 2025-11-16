"""
Analyze Detection Accuracy MCP Tool

Analyzes the accuracy of different detection methods on a set of files.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import Counter

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.file_detector import FileTypeDetector
    HAVE_DETECTOR = True
except ImportError:
    HAVE_DETECTOR = False
    logger.warning("FileTypeDetector not available")


def analyze_detection_accuracy(
    directory: str,
    recursive: bool = False,
    pattern: str = "*"
) -> Dict[str, Any]:
    """
    Analyze detection accuracy by comparing all methods on a set of files.
    
    This tool runs all available detection methods on files and compares their
    results to identify agreement/disagreement rates and confidence levels.
    Useful for validating detection reliability.
    
    Args:
        directory: Directory containing files to analyze
        recursive: Whether to scan directory recursively (default: False)
        pattern: File pattern to match (default: "*")
    
    Returns:
        Dict with accuracy analysis:
            - total_files: Number of files analyzed
            - method_availability: Which methods are available
            - method_success_rates: Success rate for each method
            - agreement_rate: How often methods agree
            - avg_confidence_by_method: Average confidence for each method
            - disagreements: List of files where methods disagreed
            - common_mime_types: Most common MIME types detected
    
    Example:
        >>> analyze_detection_accuracy('/path/to/test/files')
        {
            'total_files': 100,
            'method_availability': ['extension', 'magic', 'magika'],
            'method_success_rates': {
                'extension': 0.95,
                'magic': 0.92,
                'magika': 0.98
            },
            'agreement_rate': 0.89,
            'avg_confidence_by_method': {
                'extension': 0.70,
                'magic': 0.85,
                'magika': 0.93
            },
            'disagreements': [...],
            'common_mime_types': {
                'application/pdf': 45,
                'text/plain': 30,
                'image/jpeg': 15
            }
        }
    """
    if not HAVE_DETECTOR:
        return {
            'error': 'FileTypeDetector not available',
            'total_files': 0
        }
    
    try:
        detector = FileTypeDetector()
        
        # Check available methods
        available_methods = detector.get_available_methods()
        
        # Collect files
        dir_path = Path(directory)
        if not dir_path.exists():
            return {'error': f'Directory not found: {directory}'}
        
        if not dir_path.is_dir():
            return {'error': f'Not a directory: {directory}'}
        
        if recursive:
            files = [p for p in dir_path.rglob(pattern) if p.is_file()]
        else:
            files = [p for p in dir_path.glob(pattern) if p.is_file()]
        
        if not files:
            return {
                'error': 'No files found',
                'total_files': 0
            }
        
        # Analyze each file with all methods
        method_results = {method: [] for method in available_methods}
        file_results = []
        disagreements = []
        mime_types = []
        
        for file_path in files:
            file_str = str(file_path)
            
            # Run each method individually
            method_detections = {}
            for method in available_methods:
                result = detector.detect_type(file_str, methods=[method])
                method_results[method].append(result)
                method_detections[method] = result.get('mime_type')
            
            file_results.append({
                'file': file_str,
                'detections': method_detections
            })
            
            # Check for disagreements
            unique_types = set(v for v in method_detections.values() if v)
            if len(unique_types) > 1:
                disagreements.append({
                    'file': file_str,
                    'detections': method_detections
                })
            
            # Collect MIME types for statistics
            for mime_type in method_detections.values():
                if mime_type:
                    mime_types.append(mime_type)
        
        # Calculate statistics
        method_success_rates = {}
        avg_confidence_by_method = {}
        
        for method in available_methods:
            results = method_results[method]
            successes = sum(1 for r in results if r.get('mime_type'))
            method_success_rates[method] = successes / len(results) if results else 0.0
            
            confidences = [r.get('confidence', 0) for r in results if r.get('mime_type')]
            avg_confidence_by_method[method] = sum(confidences) / len(confidences) if confidences else 0.0
        
        # Calculate agreement rate
        agreements = len(files) - len(disagreements)
        agreement_rate = agreements / len(files) if files else 0.0
        
        # Count common MIME types
        mime_type_counts = dict(Counter(mime_types).most_common(10))
        
        return {
            'total_files': len(files),
            'method_availability': available_methods,
            'method_success_rates': method_success_rates,
            'agreement_rate': agreement_rate,
            'avg_confidence_by_method': avg_confidence_by_method,
            'disagreements': disagreements[:10],  # Limit to first 10
            'disagreement_count': len(disagreements),
            'common_mime_types': mime_type_counts
        }
        
    except Exception as e:
        logger.error(f"Detection accuracy analysis failed: {e}")
        return {
            'error': str(e),
            'total_files': 0
        }
