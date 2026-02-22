"""
Data Processing Engine — canonical business logic for text chunking,
data transformation, format conversion, and data validation.

Extracted from ipfs_datasets_py/mcp_server/tools/data_processing_tools/data_processing_tools.py.
This module is callable independently of the MCP layer.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.core_operations import DataProcessor
    HAVE_DATA_PROCESSOR = True
except ImportError:
    HAVE_DATA_PROCESSOR = False
    DataProcessor = None  # type: ignore[assignment,misc]


async def chunk_text_engine(
    text: str,
    strategy: str = "fixed_size",
    chunk_size: int = 1000,
    overlap: int = 100,
    max_chunks: int = 100,
) -> Dict[str, Any]:
    """Split text into overlapping chunks using the configured strategy.

    Delegates to :class:`~ipfs_datasets_py.core_operations.DataProcessor.chunk_text`.

    Args:
        text: Text to split.
        strategy: Chunking strategy — ``fixed_size``, ``sentence``,
                  ``paragraph``, or ``semantic``.
        chunk_size: Maximum characters per chunk.
        overlap: Character overlap between adjacent chunks.
        max_chunks: Upper bound on chunk count.

    Returns:
        Dict with ``status``, ``chunks`` list and ``chunk_count``.
    """
    if not HAVE_DATA_PROCESSOR:
        return {"status": "error", "message": "core_operations.DataProcessor not available"}
    try:
        processor = DataProcessor()
        return await processor.chunk_text(text, strategy, chunk_size, overlap, max_chunks)
    except Exception as exc:
        logger.error("chunk_text_engine failed: %s", exc)
        return {"status": "error", "message": str(exc)}


async def transform_data_engine(
    data: Any,
    transformation: str,
    **parameters: Any,
) -> Dict[str, Any]:
    """Apply a named transformation to *data*.

    Delegates to :class:`~ipfs_datasets_py.core_operations.DataProcessor.transform_data`.

    Args:
        data: Input data (any serialisable type).
        transformation: Transformation identifier (e.g. ``normalize``,
                        ``flatten``, ``validate_schema``).
        **parameters: Additional keyword arguments forwarded to the processor.

    Returns:
        Dict with ``status`` and ``result`` keys.
    """
    if not HAVE_DATA_PROCESSOR:
        return {"status": "error", "message": "core_operations.DataProcessor not available"}
    try:
        processor = DataProcessor()
        return await processor.transform_data(data, transformation, **parameters)
    except Exception as exc:
        logger.error("transform_data_engine failed: %s", exc)
        return {"status": "error", "message": str(exc)}


async def convert_format_engine(
    data: Any,
    source_format: str,
    target_format: str,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Convert *data* from *source_format* to *target_format*.

    Short-circuits when the formats are identical (no processing needed).

    Args:
        data: Input data.
        source_format: ``json``, ``csv``, ``parquet``, ``jsonl``, ``txt``.
        target_format: Same options as *source_format*.
        options: Optional format-specific parameters.

    Returns:
        Dict with ``status``, ``result``, ``source_format``, ``target_format``.
    """
    if source_format == target_format:
        return {
            "status": "success",
            "result": data,
            "source_format": source_format,
            "target_format": target_format,
            "message": "No conversion needed — formats are identical",
        }
    if not HAVE_DATA_PROCESSOR:
        return {"status": "error", "message": "core_operations.DataProcessor not available"}
    try:
        processor = DataProcessor()
        return await processor.convert_format(data, source_format, target_format)
    except Exception as exc:
        logger.error("convert_format_engine failed: %s", exc)
        return {"status": "error", "message": str(exc)}


def _validate_format(data: Any) -> Dict[str, Any]:
    """Lightweight format-level validation (no external dependency)."""
    metrics: Dict[str, Any] = {}
    warnings: List[str] = []
    if isinstance(data, str):
        if not data.strip():
            warnings.append("Empty or whitespace-only string")
        metrics["character_count"] = len(data)
        metrics["word_count"] = len(data.split())
    return {"valid": True, "errors": [], "warnings": warnings, "metrics": metrics}


def _validate_completeness(data: Any) -> Dict[str, Any]:
    """Check for missing / empty fields in a dict."""
    warnings: List[str] = []
    metrics: Dict[str, Any] = {}
    if isinstance(data, dict):
        total = len(data)
        empty = sum(1 for v in data.values() if v is None or v == "")
        ratio = (total - empty) / total if total else 0
        metrics = {"completeness_ratio": ratio, "empty_fields": empty, "total_fields": total}
        if ratio < 0.8:
            warnings.append(f"Low data completeness: {ratio:.2%}")
    return {"valid": True, "errors": [], "warnings": warnings, "metrics": metrics}


def _validate_quality(data: Any) -> Dict[str, Any]:
    """Heuristic quality score for text data."""
    score = 1.0
    issues: List[str] = []
    if isinstance(data, str):
        if len(data) < 10:
            score -= 0.3
            issues.append("Text too short")
        if data.isupper() or data.islower():
            score -= 0.1
            issues.append("Poor capitalisation")
    return {
        "valid": True,
        "errors": [],
        "warnings": issues,
        "metrics": {"quality_score": max(0.0, score)},
    }


def _apply_custom_rules(data: Any, rules: List[Dict[str, Any]]) -> List[str]:
    """Return a list of error messages from custom validation rules."""
    errors: List[str] = []
    for rule in rules:
        if rule.get("type") == "length" and isinstance(data, str):
            cond = rule.get("condition", {})
            lo, hi = cond.get("min", 0), cond.get("max", float("inf"))
            if not (lo <= len(data) <= hi):
                errors.append(f"Length {len(data)} not in range [{lo}, {hi}]")
    return errors


async def validate_data_engine(
    data: Any,
    validation_type: str,
    schema: Optional[Dict[str, Any]] = None,
    rules: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Validate *data* using the requested strategy.

    Args:
        data: Data to validate.
        validation_type: One of ``schema``, ``format``, ``completeness``, ``quality``.
        schema: JSON schema dict for ``schema`` validation.
        rules: Custom rule list (currently supports ``length`` constraints).

    Returns:
        Dict with ``status``, ``validation_type``, ``validation_result`` and
        ``data_summary`` keys.
    """
    if not data and data != 0:
        return {"status": "error", "message": "data is required"}

    allowed = {"schema", "format", "completeness", "quality"}
    if validation_type not in allowed:
        return {
            "status": "error",
            "message": f"Invalid validation_type. Must be one of: {', '.join(sorted(allowed))}",
        }

    # Schema validation delegates to the DataProcessor
    if validation_type == "schema" and schema:
        if not HAVE_DATA_PROCESSOR:
            return {"status": "error", "message": "core_operations.DataProcessor not available"}
        try:
            processor = DataProcessor()
            return await processor.transform_data(
                data, "validate_schema", required_fields=schema.get("required", [])
            )
        except Exception as exc:
            logger.error("validate_data_engine (schema) failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    # Lightweight validation paths (no external dependency)
    dispatch = {
        "format": _validate_format,
        "completeness": _validate_completeness,
        "quality": _validate_quality,
        "schema": lambda d: {"valid": True, "errors": [], "warnings": [], "metrics": {}},
    }
    vr: Dict[str, Any] = dispatch[validation_type](data)

    # Apply custom rules
    if rules:
        extra_errors = _apply_custom_rules(data, rules)
        vr["errors"].extend(extra_errors)
        if extra_errors:
            vr["valid"] = False

    return {
        "status": "success",
        "validation_type": validation_type,
        "validation_result": vr,
        "data_summary": {
            "type": type(data).__name__,
            "size": len(data) if hasattr(data, "__len__") else None,
        },
        "message": f"Data validation completed for {validation_type}",
    }
