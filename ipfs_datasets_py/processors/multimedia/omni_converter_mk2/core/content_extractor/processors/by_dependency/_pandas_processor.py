"""
CSV processing utilities.

This module contains functions for processing CSV files using the
standard csv module and pandas for advanced functionality.
"""

import csv
from io import StringIO
from typing import Any, Optional, Union

from logger import logger

# TODO Refactor this so that it follows the model of the other processors. Dependency injection, IoC, etc.
# Check if pandas is available for advanced CSV processing # TODO This check should be moved to a constants.py file.
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    logger.info("pandas not available, using basic CSV processing")


def detect_csv_dialect(
    csv_content: str,
    options: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """
    Detect the dialect of a CSV file.
    
    Args:
        csv_content: The CSV content as text.
        options: Optional detection options.
        
    Returns:
        Dictionary with dialect information.
    """
    try:
        # Use csv.Sniffer to detect dialect
        dialect = csv.Sniffer().sniff(csv_content)
        has_header = csv.Sniffer().has_header(csv_content)
        
        return {
            'delimiter': dialect.delimiter,
            'quotechar': dialect.quotechar,
            'has_header': has_header
        }
    except Exception as e:
        logger.warning(f"CSV dialect detection failed: {e}")
        
        # Return default dialect
        return {
            'delimiter': ',',
            'quotechar': '"',
            'has_header': True
        }


def extract_csv_metadata_advanced(
    csv_content: str,
    options: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """
    Extract metadata from CSV content using pandas.
    
    Args:
        csv_content: The CSV content as text.
        options: Optional extraction options.
        
    Returns:
        Dictionary of metadata.
    """
    if not PANDAS_AVAILABLE:
        logger.info("pandas not available, using basic CSV metadata extraction")
        return extract_csv_metadata_basic(csv_content, options)
    
    options = options or {}
    
    try:
        # Detect dialect if not provided
        dialect_info = options.get('dialect', detect_csv_dialect(csv_content, options))
        
        # Parse CSV with pandas
        df = pd.read_csv(
            StringIO(csv_content),
            sep=dialect_info.get('delimiter', ','),
            quotechar=dialect_info.get('quotechar', '"'),
            header=0 if dialect_info.get('has_header', True) else None
        )
        
        # Basic metadata
        metadata = {
            'format': 'csv',
            'row_count': len(df),
            'column_count': len(df.columns),
            'delimiter': dialect_info.get('delimiter', ','),
            'has_header': dialect_info.get('has_header', True)
        }
        
        # Column types
        column_types = {}
        for column in df.columns:
            dtype = str(df[column].dtype)
            column_types[str(column)] = dtype
        
        metadata['column_types'] = column_types
        
        # Missing values
        missing_values = df.isnull().sum().to_dict()
        metadata['missing_values'] = {str(k): int(v) for k, v in missing_values.items()}
        
        # Sample statistics for numeric columns
        numeric_stats = {}
        for column in df.select_dtypes(include=['number']).columns:
            stats = df[column].describe().to_dict()
            numeric_stats[str(column)] = {
                'min': stats.get('min', 0),
                'max': stats.get('max', 0),
                'mean': stats.get('mean', 0),
                'std': stats.get('std', 0)
            }
        
        if numeric_stats:
            metadata['numeric_stats'] = numeric_stats
        
        return metadata
    
    except Exception as e:
        logger.warning(f"CSV metadata extraction with pandas failed: {e}")
        return extract_csv_metadata_basic(csv_content, options)


def extract_csv_metadata_basic(
    csv_content: str,
    options: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """
    Extract metadata from CSV content using the csv module.
    
    Args:
        csv_content: The CSV content as text.
        options: Optional extraction options.
        
    Returns:
        Dictionary of metadata.
    """
    options = options or {}
    
    try:
        # Detect dialect if not provided
        dialect_info = options.get('dialect', detect_csv_dialect(csv_content, options))
        
        # Parse CSV
        reader = csv.reader(
            StringIO(csv_content),
            delimiter=dialect_info.get('delimiter', ','),
            quotechar=dialect_info.get('quotechar', '"')
        )
        
        rows = list(reader)
        
        # Extract header if available
        header = []
        if rows and dialect_info.get('has_header', True):
            header = rows[0]
            rows = rows[1:]
        
        # Create metadata
        metadata = {
            'format': 'csv',
            'row_count': len(rows),
            'column_count': len(header) if header else (len(rows[0]) if rows else 0),
            'delimiter': dialect_info.get('delimiter', ','),
            'has_header': dialect_info.get('has_header', True)
        }
        
        if header:
            metadata['columns'] = header
        
        return metadata
    
    except Exception as e:
        logger.warning(f"CSV metadata extraction failed: {e}")
        
        return {
            'format': 'csv',
            'parse_error': str(e)
        }


def create_csv_sections(
    csv_content: str,
    options: Optional[dict[str, Any]] = None
) -> list[dict[str, Any]]:
    """
    Create sections from CSV content.
    
    Args:
        csv_content: The CSV content as text.
        options: Optional extraction options.
        
    Returns:
        List of sections.
    """
    options = options or {}
    
    try:
        # Detect dialect if not provided
        dialect_info = options.get('dialect', detect_csv_dialect(csv_content, options))
        
        # Parse CSV
        reader = csv.reader(
            StringIO(csv_content),
            delimiter=dialect_info.get('delimiter', ','),
            quotechar=dialect_info.get('quotechar', '"')
        )
        
        rows = list(reader)
        
        # Extract header if available
        header = []
        if rows and dialect_info.get('has_header', True):
            header = rows[0]
            rows = rows[1:]
        
        # Create sections
        sections = []
        
        if header:
            sections.append({
                'type': 'header',
                'content': header
            })
        
        sections.append({
            'type': 'data',
            'content': rows
        })
        
        return sections
    
    except Exception as e:
        logger.warning(f"CSV section creation failed: {e}")
        
        return [{
            'type': 'error',
            'content': f"CSV parsing error: {e}"
        }]


def process(
    file_content: Any,
    options: dict[str, Any]
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """
    Process CSV content.
    
    Args:
        file_content: The file content to process.
        options: Processing options.
        
    Returns:
        Tuple of (text content, metadata, sections).
    """
    # Get CSV content as text
    if hasattr(file_content, 'get_as_text'):
        csv_content = file_content.get_as_text()
    else:
        csv_content = file_content
    
    # Detect dialect
    dialect_info = detect_csv_dialect(csv_content, options)
    options['dialect'] = dialect_info
    
    # Extract metadata
    if PANDAS_AVAILABLE and options.get('use_pandas', True):
        metadata = extract_csv_metadata_advanced(csv_content, options)
    else:
        metadata = extract_csv_metadata_basic(csv_content, options)
    
    # Create sections
    sections = create_csv_sections(csv_content, options)
    
    # Create human-readable text
    output_text = []
    
    # Get header and data
    header = None
    data = []

    for section in sections:
        if section['type'] == 'header':
            header = section['content']
        elif section['type'] == 'data':
            data = section['content']
    
    # Add header
    if header:
        output_text.append(" | ".join(header))
        output_text.append("-" * (sum(len(h) for h in header) + 3 * (len(header) - 1)))
    
    # Add rows (limit to 100 rows for readability)
    max_rows = min(len(data), 100)
    for i in range(max_rows):
        output_text.append(" | ".join(data[i]))
    
    # Add note if data was truncated
    if len(data) > max_rows:
        output_text.append(f"\n[Note: {len(data) - max_rows} more rows not shown]")
    
    return "\n".join(output_text), metadata, sections