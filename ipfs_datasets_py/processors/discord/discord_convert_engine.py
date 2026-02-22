"""Discord export format conversion engine — canonical domain module.

Provides functions for converting Discord chat exports between data formats.

Usage::

    from ipfs_datasets_py.processors.discord import discord_convert_export
"""
from __future__ import annotations

import glob
import logging
import os
from pathlib import Path
from typing import Any, Dict, Literal, Optional

logger = logging.getLogger(__name__)

# Map output format → file extension
_EXT_MAP: dict[str, str] = {
    "json": "json",
    "jsonl": "jsonl",
    "jsonld": "json-ld",
    "jsonld-logic": "json-ld-logic",
    "parquet": "parquet",
    "ipld": "ipld",
    "car": "car",
    "csv": "csv",
}


async def discord_convert_export(
    input_path: str,
    output_path: str,
    to_format: Literal[
        "json", "jsonl", "jsonld", "jsonld-logic", "parquet", "ipld", "car", "csv"
    ] = "jsonl",
    token: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    compression: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Convert a Discord export file to a different data format.

    Args:
        input_path: Path to the input Discord export file (usually JSON).
        output_path: Path for the converted output file.
        to_format: Target format. Options: json, jsonl, jsonld, jsonld-logic,
            parquet, ipld, car, csv.
        token: Discord token (not required for conversion; accepted for API
            consistency).
        context: Custom JSON-LD ``@context`` for jsonld/jsonld-logic formats.
        compression: Compression for Parquet (``snappy``, ``gzip``, ``brotli``).
        **kwargs: Additional format-specific options.

    Returns:
        Dict with status, input_path, output_path, from_format, to_format,
        file_size, message.
    """
    try:
        from ipfs_datasets_py.utils.data_format_converter import get_converter

        converter = get_converter()

        convert_kwargs: Dict[str, Any] = {}
        if context:
            convert_kwargs["context"] = context
        if compression:
            convert_kwargs["compression"] = compression
        convert_kwargs.update(kwargs)

        converter.convert_file(
            input_path=input_path,
            output_path=output_path,
            to_format=to_format,
            **convert_kwargs,
        )

        file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        from_format = Path(input_path).suffix.lower().lstrip(".") or "json"

        return {
            "status": "success",
            "input_path": input_path,
            "output_path": output_path,
            "from_format": from_format,
            "to_format": to_format,
            "file_size": file_size,
            "message": f"Successfully converted from {from_format} to {to_format}",
        }

    except ImportError as exc:
        error_msg = f"Required dependencies not available: {exc}"
        logger.error(error_msg)
        return {
            "status": "error",
            "input_path": input_path,
            "output_path": output_path,
            "to_format": to_format,
            "error": error_msg,
        }
    except Exception as exc:
        error_msg = f"Conversion failed: {exc}"
        logger.error(error_msg)
        return {
            "status": "error",
            "input_path": input_path,
            "output_path": output_path,
            "to_format": to_format,
            "error": error_msg,
        }


async def discord_batch_convert_exports(
    input_dir: str,
    output_dir: str,
    to_format: Literal[
        "json", "jsonl", "jsonld", "jsonld-logic", "parquet", "ipld", "car", "csv"
    ] = "jsonl",
    file_pattern: str = "*.json",
    token: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Batch convert multiple Discord export files to a different format.

    Args:
        input_dir: Directory containing input Discord export files.
        output_dir: Directory for converted output files.
        to_format: Target format (see ``discord_convert_export``).
        file_pattern: Glob pattern for input files (default: ``*.json``).
        token: Discord token (not required for conversion).
        **kwargs: Additional format-specific options.

    Returns:
        Dict with status, total_files, successful, failed, conversions, message.
    """
    try:
        os.makedirs(output_dir, exist_ok=True)

        pattern = os.path.join(input_dir, file_pattern)
        input_files = glob.glob(pattern)

        if not input_files:
            return {
                "status": "error",
                "total_files": 0,
                "successful": 0,
                "failed": 0,
                "conversions": [],
                "error": (
                    f"No files matching pattern '{file_pattern}' found in {input_dir}"
                ),
            }

        conversions: list[Dict[str, Any]] = []
        successful = 0
        failed = 0

        for input_file in input_files:
            input_name = Path(input_file).stem
            output_ext = _EXT_MAP.get(to_format, to_format)
            output_file = os.path.join(output_dir, f"{input_name}.{output_ext}")

            result = await discord_convert_export(
                input_path=input_file,
                output_path=output_file,
                to_format=to_format,
                token=token,
                **kwargs,
            )
            conversions.append(result)

            if result.get("status") == "success":
                successful += 1
            else:
                failed += 1

        if failed == 0:
            status = "success"
            message = f"Successfully converted all {successful} files"
        elif successful == 0:
            status = "error"
            message = f"All {failed} conversions failed"
        else:
            status = "partial"
            message = f"Converted {successful} files, {failed} failed"

        return {
            "status": status,
            "total_files": len(input_files),
            "successful": successful,
            "failed": failed,
            "conversions": conversions,
            "message": message,
        }

    except Exception as exc:
        error_msg = f"Batch conversion failed: {exc}"
        logger.error(error_msg)
        return {
            "status": "error",
            "total_files": 0,
            "successful": 0,
            "failed": 0,
            "conversions": [],
            "error": error_msg,
        }
