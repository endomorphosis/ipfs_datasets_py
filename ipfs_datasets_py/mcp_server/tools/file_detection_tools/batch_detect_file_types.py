"""
Batch Detect File Types MCP Tool

Detects file types for multiple files in batch.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.utils.file_detector import FileTypeDetector
    HAVE_DETECTOR = True
except ImportError:
    HAVE_DETECTOR = False
    logger.warning("FileTypeDetector not available")


def batch_detect_file_types(
    directory: Optional[str] = None,
    file_paths: Optional[List[str]] = None,
    recursive: bool = False,
    pattern: str = "*",
    methods: Optional[List[str]] = None,
    strategy: Optional[str] = None,
    export_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Detect file types for multiple files in batch.
    
    This tool can process files from a directory or a list of file paths.
    Results can be exported to a JSON file for further analysis.
    
    Args:
        directory: Directory to scan for files
        file_paths: List of specific file paths to analyze
        recursive: Whether to scan directory recursively (default: False)
        pattern: File pattern to match (default: "*")
        methods: List of detection methods to use
        strategy: Detection strategy to use
        export_path: Path to export results as JSON
    
    Returns:
        Dict with:
            - results: Dict mapping file paths to detection results
            - total_files: Total number of files processed
            - successful: Number of successful detections
            - failed: Number of failed detections
            - export_path: Path where results were exported (if requested)
    
    Example:
        >>> batch_detect_file_types(
        ...     directory='/path/to/documents',
        ...     recursive=True,
        ...     pattern='*.pdf',
        ...     strategy='accurate'
        ... )
        {
            'results': {
                '/path/to/doc1.pdf': {...},
                '/path/to/doc2.pdf': {...}
            },
            'total_files': 2,
            'successful': 2,
            'failed': 0
        }
    """

    def _make_json_safe(value: Any, seen: Optional[set[int]] = None) -> Any:
        """Convert arbitrary nested results into a JSON-serializable structure.

        This tool output can include nested/cyclical references (e.g., debug
        structures under `all_results`). When exporting, we replace cycles with
        a placeholder to avoid `json.dump` failures.
        """
        if seen is None:
            seen = set()

        value_id = id(value)
        if value_id in seen:
            return "<circular_reference>"

        if isinstance(value, (str, int, float, bool)) or value is None:
            return value

        if isinstance(value, dict):
            seen.add(value_id)
            try:
                return {str(k): _make_json_safe(v, seen) for k, v in value.items()}
            finally:
                seen.remove(value_id)

        if isinstance(value, (list, tuple, set)):
            seen.add(value_id)
            try:
                return [_make_json_safe(v, seen) for v in value]
            finally:
                seen.remove(value_id)

        return str(value)
    if not HAVE_DETECTOR:
        return {
            'error': 'FileTypeDetector not available',
            'results': {},
            'total_files': 0,
            'successful': 0,
            'failed': 0
        }
    
    try:
        detector = FileTypeDetector()
        files_to_process = []
        
        # Collect files from directory
        if directory:
            dir_path = Path(directory)
            if not dir_path.exists():
                return {
                    'error': f'Directory not found: {directory}',
                    'results': {},
                    'total_files': 0,
                    'successful': 0,
                    'failed': 0
                }
            
            if not dir_path.is_dir():
                return {
                    'error': f'Not a directory: {directory}',
                    'results': {},
                    'total_files': 0,
                    'successful': 0,
                    'failed': 0
                }
            
            if recursive:
                files_to_process.extend([str(p) for p in dir_path.rglob(pattern) if p.is_file()])
            else:
                files_to_process.extend([str(p) for p in dir_path.glob(pattern) if p.is_file()])
        
        # Add specific file paths
        if file_paths:
            files_to_process.extend(file_paths)
        
        if not files_to_process:
            return {
                'error': 'No files to process',
                'results': {},
                'total_files': 0,
                'successful': 0,
                'failed': 0
            }
        
        # Process files
        results = detector.batch_detect(files_to_process, methods=methods, strategy=strategy)
        
        # Count successes and failures
        successful = sum(1 for r in results.values() if r.get('mime_type') is not None)
        failed = len(results) - successful
        
        # Export if requested
        exported = None
        if export_path:
            try:
                exportable_results = _make_json_safe(results)
                with open(export_path, 'w', encoding='utf-8') as f:
                    json.dump(exportable_results, f, indent=2)
                exported = export_path
                logger.info(f"Exported results to {export_path}")
            except Exception as e:
                logger.error(f"Failed to export results: {e}")
        
        return {
            'results': results,
            'total_files': len(results),
            'successful': successful,
            'failed': failed,
            **({"export_path": exported} if exported else {})
        }
        
    except Exception as e:
        logger.error(f"Batch file type detection failed: {e}")
        return {
            'error': str(e),
            'results': {},
            'total_files': 0,
            'successful': 0,
            'failed': 0
        }
