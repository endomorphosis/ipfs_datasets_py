"""
Data processing tools for MCP server.

This module provides thin wrapper tools for data transformation, chunking,
format conversion, and other data processing operations.

Core implementation: ipfs_datasets_py.core_operations.data_processor.DataProcessor
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import DataProcessor


async def chunk_text(
    text: str, 
    strategy: str = "fixed_size", 
    chunk_size: int = 1000,
    overlap: int = 100, 
    max_chunks: int = 100
) -> Dict[str, Any]:
    """
    Split text into chunks using various strategies.
    
    This is a thin wrapper around DataProcessor.chunk_text().
    All business logic is in ipfs_datasets_py.core_operations.data_processor
    
    Args:
        text: Text to chunk
        strategy: Chunking strategy (fixed_size, sentence, paragraph, semantic)
        chunk_size: Maximum chunk size in characters
        overlap: Overlap between chunks in characters
        max_chunks: Maximum number of chunks to create
        
    Returns:
        Dictionary containing chunking result
    """
    try:
        processor = DataProcessor()
        result = await processor.chunk_text(text, strategy, chunk_size, overlap, max_chunks)
        return result
    except Exception as e:
        logger.error(f"Error in chunk_text MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


async def transform_data(
    data: Any, 
    transformation: str, 
    **parameters
) -> Dict[str, Any]:
    """
    Apply various data transformations and processing operations.
    
    This is a thin wrapper around DataProcessor.transform_data().
    All business logic is in ipfs_datasets_py.core_operations.data_processor
    
    Args:
        data: Data to transform
        transformation: Type of transformation to apply
        **parameters: Additional parameters for transformation
        
    Returns:
        Dictionary containing transformation result
    """
    try:
        processor = DataProcessor()
        result = await processor.transform_data(data, transformation, **parameters)
        return result
    except Exception as e:
        logger.error(f"Error in transform_data MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


async def convert_format(
    data: Any, 
    source_format: str, 
    target_format: str,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Convert data between different formats.
    
    This is a thin wrapper around DataProcessor.convert_format().
    All business logic is in ipfs_datasets_py.core_operations.data_processor
    
    Args:
        data: Data to convert
        source_format: Source format (json, csv, parquet, jsonl, txt)
        target_format: Target format (json, csv, parquet, jsonl, txt)
        options: Optional conversion parameters
        
    Returns:
        Dictionary containing format conversion result
    """
    try:
        if source_format == target_format:
            return {
                "status": "success",
                "result": data,
                "source_format": source_format,
                "target_format": target_format,
                "message": "No conversion needed - formats are the same"
            }
        
        processor = DataProcessor()
        result = await processor.convert_format(data, source_format, target_format)
        return result
    except Exception as e:
        logger.error(f"Error in convert_format MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


async def validate_data(
    data: Any, 
    validation_type: str, 
    schema: Optional[Dict[str, Any]] = None,
    rules: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Validate data using various validation strategies.
    
    For schema validation, delegates to DataProcessor.transform_data with validate_schema.
    Other validations (format, completeness, quality) are handled locally.
    
    Args:
        data: Data to validate
        validation_type: Type of validation (schema, format, completeness, quality)
        schema: Optional schema definition for schema validation
        rules: Optional custom validation rules
        
    Returns:
        Dictionary containing validation results
    """
    try:
        if not data:
            return {
                "status": "error",
                "message": "Data is required"
            }
        
        if validation_type not in ["schema", "format", "completeness", "quality"]:
            return {
                "status": "error",
                "message": "Invalid validation_type. Must be one of: schema, format, completeness, quality"
            }
        
        # For schema validation, use the core processor
        if validation_type == "schema" and schema:
            processor = DataProcessor()
            required_fields = schema.get("required", [])
            result = await processor.transform_data(
                data, 
                "validate_schema", 
                required_fields=required_fields
            )
            return result
        
        # For other validations, handle locally (lightweight)
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "metrics": {}
        }
        
        if validation_type == "format":
            if isinstance(data, str):
                if not data.strip():
                    validation_result["warnings"].append("Empty or whitespace-only string")
                validation_result["metrics"]["character_count"] = len(data)
                validation_result["metrics"]["word_count"] = len(data.split())
        
        elif validation_type == "completeness":
            if isinstance(data, dict):
                total_fields = len(data)
                empty_fields = sum(1 for v in data.values() if v is None or v == "")
                completeness_ratio = (total_fields - empty_fields) / total_fields if total_fields > 0 else 0
                
                validation_result["metrics"]["completeness_ratio"] = completeness_ratio
                validation_result["metrics"]["empty_fields"] = empty_fields
                validation_result["metrics"]["total_fields"] = total_fields
                
                if completeness_ratio < 0.8:
                    validation_result["warnings"].append(f"Low data completeness: {completeness_ratio:.2%}")
        
        elif validation_type == "quality":
            quality_score = 1.0
            issues = []
            
            if isinstance(data, str):
                if len(data) < 10:
                    quality_score -= 0.3
                    issues.append("Text too short")
                
                if data.isupper() or data.islower():
                    quality_score -= 0.1
                    issues.append("Poor capitalization")
            
            validation_result["metrics"]["quality_score"] = max(0, quality_score)
            if issues:
                validation_result["warnings"].extend(issues)
        
        # Apply custom rules if provided
        if rules:
            for rule in rules:
                rule_type = rule.get("type")
                rule_condition = rule.get("condition")
                
                if rule_type == "length" and isinstance(data, str):
                    min_length = rule_condition.get("min", 0)
                    max_length = rule_condition.get("max", float('inf'))
                    
                    if not (min_length <= len(data) <= max_length):
                        validation_result["valid"] = False
                        validation_result["errors"].append(
                            f"Length {len(data)} not in range [{min_length}, {max_length}]"
                        )
        
        return {
            "status": "success",
            "validation_type": validation_type,
            "validation_result": validation_result,
            "data_summary": {
                "type": type(data).__name__,
                "size": len(data) if hasattr(data, '__len__') else None
            },
            "message": f"Data validation completed for {validation_type}"
        }
        
    except Exception as e:
        logger.error(f"Error in validate_data MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
