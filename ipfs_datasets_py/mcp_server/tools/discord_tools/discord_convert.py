"""
Discord Export Format Conversion MCP Tools

Provides MCP tools for converting Discord chat exports between various
data formats including JSON, JSONL, JSON-LD, Parquet, IPLD, and CAR.
"""

import os
import logging
from typing import Dict, Any, Optional, Literal

logger = logging.getLogger(__name__)


async def discord_convert_export(
    input_path: str,
    output_path: str,
    to_format: Literal['json', 'jsonl', 'jsonld', 'jsonld-logic', 'parquet', 'ipld', 'car', 'csv'] = 'jsonl',
    token: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    compression: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Convert a Discord export file to a different data format.
    
    Converts Discord chat exports (typically JSON from DiscordChatExporter)
    to various formats supported by ipfs_datasets_py. This enables integration
    with different data processing pipelines and storage systems.
    
    Args:
        input_path (str): Path to the input Discord export file (usually JSON)
        output_path (str): Path for the converted output file
        to_format (str): Target format. Options:
            - 'json': Standard JSON
            - 'jsonl': JSON Lines (newline-delimited, streaming-friendly)
            - 'jsonld': JSON-LD with semantic web context
            - 'jsonld-logic': JSON-LD with formal logic annotations
            - 'parquet': Apache Parquet (columnar, analytics-optimized)
            - 'ipld': InterPlanetary Linked Data (content-addressed)
            - 'car': Content Addressable aRchive (IPFS format)
            - 'csv': Comma-separated values
        token (Optional[str]): Discord token (not required for conversion,
            but accepted for API consistency)
        context (Optional[Dict]): Custom JSON-LD @context for jsonld/jsonld-logic formats
        compression (Optional[str]): Compression for Parquet ('snappy', 'gzip', 'brotli')
        **kwargs: Additional format-specific options
    
    Returns:
        Dict[str, Any]: Conversion result containing:
            - status: 'success' or 'error'
            - input_path: Source file path
            - output_path: Destination file path
            - from_format: Detected source format
            - to_format: Target format
            - file_size: Output file size in bytes (if successful)
            - message: Status or error message
    
    Examples:
        Convert to JSONL for streaming:
            result = await discord_convert_export(
                "channel.json",
                "channel.jsonl",
                to_format="jsonl"
            )
        
        Convert to Parquet for analytics:
            result = await discord_convert_export(
                "channel.json",
                "channel.parquet",
                to_format="parquet",
                compression="snappy"
            )
        
        Convert to JSON-LD with semantic context:
            result = await discord_convert_export(
                "channel.json",
                "channel.json-ld",
                to_format="jsonld",
                context={"discord": "https://discord.com/developers/docs/"}
            )
    """
    try:
        from ipfs_datasets_py.utils.data_format_converter import get_converter
        
        # Get the universal converter directly (no Discord dependencies)
        converter = get_converter()
        
        # Prepare conversion kwargs
        convert_kwargs = {}
        if context:
            convert_kwargs['context'] = context
        if compression:
            convert_kwargs['compression'] = compression
        convert_kwargs.update(kwargs)
        
        # Perform conversion using the universal converter
        converter.convert_file(
            input_path=input_path,
            output_path=output_path,
            to_format=to_format,
            **convert_kwargs
        )
        
        # Build success response
        import os
        from pathlib import Path
        
        file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        
        # Detect input format from file extension
        input_ext = Path(input_path).suffix.lower().lstrip('.')
        from_format = input_ext if input_ext else 'json'  # Default to json if no extension
        
        return {
            'status': 'success',
            'input_path': input_path,
            'output_path': output_path,
            'from_format': from_format,
            'to_format': to_format,
            'file_size': file_size,
            'message': f'Successfully converted from {from_format} to {to_format}'
        }
    
    except ImportError as e:
        error_msg = f"Required dependencies not available: {str(e)}"
        logger.error(error_msg)
        return {
            'status': 'error',
            'input_path': input_path,
            'output_path': output_path,
            'to_format': to_format,
            'error': error_msg
        }
    except Exception as e:
        error_msg = f"Conversion failed: {str(e)}"
        logger.error(error_msg)
        return {
            'status': 'error',
            'input_path': input_path,
            'output_path': output_path,
            'to_format': to_format,
            'error': error_msg
        }


async def discord_batch_convert_exports(
    input_dir: str,
    output_dir: str,
    to_format: Literal['json', 'jsonl', 'jsonld', 'jsonld-logic', 'parquet', 'ipld', 'car', 'csv'] = 'jsonl',
    file_pattern: str = "*.json",
    token: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Batch convert multiple Discord export files to a different format.
    
    Processes all Discord exports in a directory that match the specified
    pattern and converts them to the target format. Useful for bulk processing
    of Discord chat archives.
    
    Args:
        input_dir (str): Directory containing input Discord export files
        output_dir (str): Directory for converted output files
        to_format (str): Target format (see discord_convert_export for options)
        file_pattern (str): Glob pattern for input files (default: "*.json")
        token (Optional[str]): Discord token (not required for conversion)
        **kwargs: Additional format-specific options
    
    Returns:
        Dict[str, Any]: Batch conversion results containing:
            - status: 'success' or 'partial' or 'error'
            - total_files: Total number of files processed
            - successful: Number of successful conversions
            - failed: Number of failed conversions
            - conversions: List of individual conversion results
            - message: Summary message
    
    Example:
        Convert all JSON exports in a directory to Parquet:
            result = await discord_batch_convert_exports(
                "/exports/json/",
                "/exports/parquet/",
                to_format="parquet",
                file_pattern="*.json"
            )
    """
    try:
        import glob
        from pathlib import Path
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # Find matching files
        pattern = os.path.join(input_dir, file_pattern)
        input_files = glob.glob(pattern)
        
        if not input_files:
            return {
                'status': 'error',
                'total_files': 0,
                'successful': 0,
                'failed': 0,
                'conversions': [],
                'error': f"No files matching pattern '{file_pattern}' found in {input_dir}"
            }
        
        # Process each file
        conversions = []
        successful = 0
        failed = 0
        
        for input_file in input_files:
            # Determine output filename
            input_name = Path(input_file).stem
            output_ext = {
                'json': 'json',
                'jsonl': 'jsonl',
                'jsonld': 'json-ld',
                'jsonld-logic': 'json-ld-logic',
                'parquet': 'parquet',
                'ipld': 'ipld',
                'car': 'car',
                'csv': 'csv'
            }.get(to_format, to_format)
            output_file = os.path.join(output_dir, f"{input_name}.{output_ext}")
            
            # Convert file
            result = await discord_convert_export(
                input_path=input_file,
                output_path=output_file,
                to_format=to_format,
                token=token,
                **kwargs
            )
            
            conversions.append(result)
            
            if result.get('status') == 'success':
                successful += 1
            else:
                failed += 1
        
        # Determine overall status
        if failed == 0:
            status = 'success'
            message = f"Successfully converted all {successful} files"
        elif successful == 0:
            status = 'error'
            message = f"All {failed} conversions failed"
        else:
            status = 'partial'
            message = f"Converted {successful} files, {failed} failed"
        
        return {
            'status': status,
            'total_files': len(input_files),
            'successful': successful,
            'failed': failed,
            'conversions': conversions,
            'message': message
        }
    
    except Exception as e:
        error_msg = f"Batch conversion failed: {str(e)}"
        logger.error(error_msg)
        return {
            'status': 'error',
            'total_files': 0,
            'successful': 0,
            'failed': 0,
            'conversions': [],
            'error': error_msg
        }
