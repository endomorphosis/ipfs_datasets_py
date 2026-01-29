"""Export utilities for legal dataset tools.

Provides functions to export scraped data in various formats including
JSON, Parquet, and CSV.
"""
import logging
import json
from typing import Dict, List, Any, Optional
from pathlib import Path
import os

logger = logging.getLogger(__name__)


# Base directory for all dataset exports to prevent path traversal and
# uncontrolled file writes. All user-provided output paths are resolved
# relative to this directory.
_EXPORT_BASE_DIR = Path("/tmp/dataset_exports")


def _safe_output_path(output_path: str) -> Path:
    """Resolve a potentially user-controlled output path safely.

    The returned path is guaranteed to be within the export base directory
    or a ValueError is raised.
    """
    # Ensure base directory exists
    _EXPORT_BASE_DIR.mkdir(parents=True, exist_ok=True)

    # Treat empty paths as a default filename under the base directory
    if not output_path:
        return _EXPORT_BASE_DIR / "dataset_export"

    # Construct path under the base directory and resolve to eliminate ".."
    candidate = (_EXPORT_BASE_DIR / output_path).resolve()

    # Ensure the resolved path is still within the base directory
    base_resolved = _EXPORT_BASE_DIR.resolve()
    if os.path.commonpath([str(base_resolved), str(candidate)]) != str(base_resolved):
        raise ValueError("Output path is not allowed")

    return candidate


def export_to_json(
    data: List[Dict[str, Any]],
    output_path: str,
    pretty: bool = True
) -> Dict[str, Any]:
    """Export data to JSON format.
    
    Args:
        data: List of dictionaries to export
        output_path: Path to output file
        pretty: Pretty-print JSON (default True)
    
    Returns:
        Dict with status and file info
    """
    try:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            if pretty:
                json.dump(data, f, indent=2, ensure_ascii=False)
            else:
                json.dump(data, f, ensure_ascii=False)
        
        file_size = output_file.stat().st_size
        
        return {
            "status": "success",
            "output_path": str(output_file),
            "format": "json",
            "records_count": len(data),
            "file_size_bytes": file_size
        }
    except Exception as e:
        logger.error(f"JSON export failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


def export_to_parquet(
    data: List[Dict[str, Any]],
    output_path: str,
    compression: str = 'snappy'
) -> Dict[str, Any]:
    """Export data to Parquet format.
    
    Args:
        data: List of dictionaries to export
        output_path: Path to output file
        compression: Compression algorithm (snappy, gzip, brotli, none)
    
    Returns:
        Dict with status and file info
    """
    try:
        # Import required libraries
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as ie:
            return {
                "status": "error",
                "error": f"Required library not available: {ie}. Install with: pip install pyarrow"
            }
        
        output_file = _safe_output_path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert list of dicts to PyArrow Table
        # Flatten nested structures for Parquet compatibility
        flattened_data = []
        for record in data:
            flat_record = _flatten_dict(record)
            flattened_data.append(flat_record)
        
        # Create PyArrow table
        table = pa.Table.from_pylist(flattened_data)
        
        # Write to Parquet file
        pq.write_table(
            table,
            output_file,
            compression=compression
        )
        
        file_size = output_file.stat().st_size
        
        return {
            "status": "success",
            "output_path": str(output_file),
            "format": "parquet",
            "records_count": len(data),
            "file_size_bytes": file_size,
            "compression": compression
        }
    except Exception as e:
        logger.error(f"Parquet export failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


def export_to_csv(
    data: List[Dict[str, Any]],
    output_path: str,
    delimiter: str = ','
) -> Dict[str, Any]:
    """Export data to CSV format.
    
    Args:
        data: List of dictionaries to export
        output_path: Path to output file
        delimiter: CSV delimiter (default comma)
    
    Returns:
        Dict with status and file info
    """
    try:
        import csv
        
        output_file = _safe_output_path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        if not data:
            return {
                "status": "error",
                "error": "No data to export"
            }
        
        # Flatten nested structures
        flattened_data = [_flatten_dict(record) for record in data]
        
        # Get all unique keys across all records
        keys = set()
        for record in flattened_data:
            keys.update(record.keys())
        keys = sorted(keys)
        
        # Write CSV
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys, delimiter=delimiter)
            writer.writeheader()
            writer.writerows(flattened_data)
        
        file_size = output_file.stat().st_size
        
        return {
            "status": "success",
            "output_path": str(output_file),
            "format": "csv",
            "records_count": len(data),
            "file_size_bytes": file_size
        }
    except Exception as e:
        logger.error(f"CSV export failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


def _flatten_dict(d: Dict[str, Any], parent_key: str = '', sep: str = '_') -> Dict[str, Any]:
    """Flatten nested dictionary structure.
    
    Args:
        d: Dictionary to flatten
        parent_key: Parent key for nested items
        sep: Separator for nested keys
    
    Returns:
        Flattened dictionary
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            # Convert lists to JSON strings for compatibility
            items.append((new_key, json.dumps(v)))
        else:
            items.append((new_key, v))
    
    return dict(items)


def export_dataset(
    data: List[Dict[str, Any]],
    output_path: str,
    format: str = 'json',
    **kwargs
) -> Dict[str, Any]:
    """Export dataset in specified format.
    
    Args:
        data: List of dictionaries to export
        output_path: Path to output file (extension will be added if needed)
        format: Export format (json, parquet, csv)
        **kwargs: Format-specific options
    

    # Normalize and validate the output path to prevent path traversal and
    # uncontrolled writes outside of the export base directory.
    try:
        safe_path = _safe_output_path(str(output_path))
    except ValueError as exc:
        logger.error(f"Invalid output path '{output_path}': {exc}")
        return {
            "status": "error",
            "error": "Invalid output path"
        }
    Returns:
        Dict with status and file info
    """
    format_lower = format.lower()
    
    # Ensure proper file extension
    output_str = str(safe_path)
    if format_lower == 'json' and not output_str.endswith('.json'):
        output_str += '.json'
    elif format_lower == 'parquet' and not output_str.endswith('.parquet'):
        output_str += '.parquet'
    elif format_lower == 'csv' and not output_str.endswith('.csv'):
        output_str += '.csv'
    
    # Export based on format
    if format_lower == 'json':
        return export_to_json(data, output_str, **kwargs)
    elif format_lower == 'parquet':
        return export_to_parquet(data, output_str, **kwargs)
    elif format_lower == 'csv':
        return export_to_csv(data, output_str, **kwargs)
    else:
        return {
            "status": "error",
            "error": f"Unsupported format: {format}. Supported formats: json, parquet, csv"
        }
