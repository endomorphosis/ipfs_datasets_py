""""
Database processing using DuckDB.

This module contains functions for extracting text and metadata from database files using DuckDB.
"""


import re

import io

import os


from typing import Any, Optional

from dependencies import dependencies




def extract_metadata(

    file_path: str,

    options: Optional[dict[str, Any]] = None

) -> dict[str, Any]:
    """
    Extract metadata from database file using DuckDB.
    
    Args:

        file_path: Path to the database file.

        options: Optional extraction options.

        
    Returns:
        Dictionary of database metadata.
    """
    conn = dependencies.duckdb.connect(file_path)

    try:
        # Get table information
        tables_result = conn.execute("SHOW TABLES").fetchall()
        table_names = [row[0] for row in tables_result]
        
        metadata = {
            'format': 'database',
            'engine': 'duckdb',
            'tables': table_names,
            'table_count': len(table_names),
            'file_size': os.path.getsize(file_path) if os.path.exists(file_path) else 0
        }
        
        # Get row counts for each table
        table_info = {}
        for table in table_names:
            try:
                count_result = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                table_info[table] = {'row_count': count_result[0] if count_result else 0}
            except Exception:
                table_info[table] = {'row_count': 0}
        
        metadata['table_info'] = table_info
        
        return metadata
    finally:
        conn.close()



def extract_text(

    file_path: str,

    options: Optional[dict[str, Any]] = None

) -> str:
    """
    Extract text content from database using DuckDB.
    
    Args:

        file_path: Path to the database file.

        options: Optional extraction options.

        
    Returns:
        Text content extracted from database.
    """
    conn = dependencies.duckdb.connect(file_path)
    text_parts = []
    
    try:
        # Get all tables
        tables_result = conn.execute("SHOW TABLES").fetchall()
        table_names = [row[0] for row in tables_result]
        
        for table in table_names:
            text_parts.append(f"Table: {table}")
            
            # Get column information
            try:
                columns_result = conn.execute(f"DESCRIBE {table}").fetchall()
                column_names = [row[0] for row in columns_result]
                text_parts.append(f"Columns: {', '.join(column_names)}")
                
                # Extract sample data (first 10 rows)
                sample_limit = options.get('sample_rows', 10) if options else 10
                data_result = conn.execute(f"SELECT * FROM {table} LIMIT {sample_limit}").fetchall()
                
                for row in data_result:
                    row_text = ' | '.join(str(cell) for cell in row)
                    text_parts.append(row_text)
                    
            except Exception as e:
                text_parts.append(f"Error reading table {table}: {str(e)}")
            
            text_parts.append("")  # Add separator between tables
        
        return '\n'.join(text_parts)
    finally:
        conn.close()



def process_database(

    file_path: str,

    options: dict[str, Any]

) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """
    Process database file using DuckDB.
    
    Args:

        file_path: Path to the database file.

        options: Processing options.

        
    Returns:
        Tuple of (text content, metadata, sections).
    """
    # Extract metadata
    metadata = extract_metadata(file_path, options)
    
    # Extract text content
    text = extract_text(file_path, options)
    
    # Create sections for each table
    sections = []
    conn = dependencies.duckdb.connect(file_path)
    
    try:
        tables_result = conn.execute("SHOW TABLES").fetchall()
        table_names = [row[0] for row in tables_result]
        
        for table in table_names:
            try:
                # Get table schema
                columns_result = conn.execute(f"DESCRIBE {table}").fetchall()
                column_info = [{'name': row[0], 'type': row[1]} for row in columns_result]
                
                # Get sample data
                sample_limit = options.get('sample_rows', 10) if options else 10
                data_result = conn.execute(f"SELECT * FROM {table} LIMIT {sample_limit}").fetchall()
                
                sections.append({
                    'type': 'table',
                    'name': table,
                    'columns': column_info,
                    'sample_data': data_result,
                    'content': f"Table {table} with {len(column_info)} columns"
                })
            except Exception:
                sections.append({
                    'type': 'table',
                    'name': table,
                    'error': True,
                    'content': f"Error processing table {table}"
                })
    finally:
        conn.close()
    
    return text, metadata, sections



def get_version() -> str:
    """
    Get DuckDB version information.
    
    Args:

        
    Returns:
        DuckDB version string.
    """
    try:
        return dependencies.duckdb.__version__
    except AttributeError:
        return "unknown"

