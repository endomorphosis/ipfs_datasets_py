"""
Data processing tools for MCP server.

This module provides tools for data transformation, chunking,
format conversion, and other data processing operations.
"""

import anyio
import logging
import json
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, Union
from pathlib import Path

logger = logging.getLogger(__name__)

# Mock data processor for testing
class MockDataProcessor:
    """Mock data processor for testing purposes."""
    
    def __init__(self):
        self.supported_formats = ["json", "csv", "parquet", "jsonl", "txt"]
        self.chunk_strategies = ["fixed_size", "sentence", "paragraph", "semantic"]
    
    async def chunk_text(self, text: str, strategy: str, chunk_size: int = 1000,
                        overlap: int = 100) -> List[Dict[str, Any]]:
        """Chunk text using specified strategy."""
        if strategy == "fixed_size":
            chunks = []
            start = 0
            chunk_id = 0
            
            while start < len(text):
                end = min(start + chunk_size, len(text))
                chunk_text = text[start:end]
                
                chunks.append({
                    "chunk_id": chunk_id,
                    "text": chunk_text,
                    "start_pos": start,
                    "end_pos": end,
                    "length": len(chunk_text)
                })
                
                chunk_id += 1
                start = end - overlap if end < len(text) else end
            
            return chunks
        
        elif strategy == "sentence":
            # Simple sentence splitting
            sentences = re.split(r'[.!?]+', text)
            chunks = []
            current_chunk = ""
            chunk_id = 0
            
            for sentence in sentences:
                if len(current_chunk) + len(sentence) > chunk_size:
                    if current_chunk:
                        chunks.append({
                            "chunk_id": chunk_id,
                            "text": current_chunk.strip(),
                            "length": len(current_chunk)
                        })
                        chunk_id += 1
                    current_chunk = sentence
                else:
                    current_chunk += sentence + ". "
            
            if current_chunk:
                chunks.append({
                    "chunk_id": chunk_id,
                    "text": current_chunk.strip(),
                    "length": len(current_chunk)
                })
            
            return chunks
        
        else:
            # Default to paragraph splitting
            paragraphs = text.split('\n\n')
            chunks = []
            for i, paragraph in enumerate(paragraphs):
                if paragraph.strip():
                    chunks.append({
                        "chunk_id": i,
                        "text": paragraph.strip(),
                        "length": len(paragraph)
                    })
            
            return chunks
    
    async def transform_data(self, data: Any, transformation: str, **params) -> Any:
        """Apply data transformations."""
        if transformation == "normalize_text":
            if isinstance(data, str):
                # Simple text normalization
                normalized = data.lower().strip()
                normalized = re.sub(r'\s+', ' ', normalized)
                return normalized
            elif isinstance(data, list):
                return [self.transform_data(item, transformation, **params) for item in data]
        
        elif transformation == "extract_metadata":
            if isinstance(data, dict):
                metadata = {
                    "keys": list(data.keys()),
                    "value_types": {k: type(v).__name__ for k, v in data.items()},
                    "size": len(data)
                }
                return metadata
        
        elif transformation == "filter_fields":
            if isinstance(data, dict) and "fields" in params:
                return {k: v for k, v in data.items() if k in params["fields"]}
        
        elif transformation == "validate_schema":
            # Simple schema validation
            if isinstance(data, dict) and "required_fields" in params:
                missing = [f for f in params["required_fields"] if f not in data]
                return {
                    "valid": len(missing) == 0,
                    "missing_fields": missing,
                    "found_fields": list(data.keys())
                }
        
        return data
    
    async def convert_format(self, data: Any, source_format: str, target_format: str) -> Any:
        """Convert data between formats."""
        if source_format == "json" and target_format == "csv":
            # Mock JSON to CSV conversion
            if isinstance(data, list) and len(data) > 0:
                headers = list(data[0].keys()) if isinstance(data[0], dict) else ["value"]
                rows = []
                for item in data:
                    if isinstance(item, dict):
                        rows.append([str(item.get(h, "")) for h in headers])
                    else:
                        rows.append([str(item)])
                
                return {
                    "headers": headers,
                    "rows": rows,
                    "format": "csv"
                }
        
        elif source_format == "csv" and target_format == "json":
            # Mock CSV to JSON conversion
            if isinstance(data, dict) and "headers" in data and "rows" in data:
                json_data = []
                for row in data["rows"]:
                    item = {h: v for h, v in zip(data["headers"], row)}
                    json_data.append(item)
                return json_data
        
        return data

# Global mock data processor instance
_mock_data_processor = MockDataProcessor()

async def chunk_text(text: str, strategy: str = "fixed_size", chunk_size: int = 1000,
                    overlap: int = 100, max_chunks: int = 100,
                    data_processor=None) -> Dict[str, Any]:
    """
    Split text into chunks using various strategies.
    
    Args:
        text: Text to chunk
        strategy: Chunking strategy (fixed_size, sentence, paragraph, semantic)
        chunk_size: Maximum chunk size in characters
        overlap: Overlap between chunks in characters
        max_chunks: Maximum number of chunks to create
        data_processor: Optional data processor service
        
    Returns:
        Dictionary containing chunking result
    """
    try:
        # Input validation
        if not text or not isinstance(text, str):
            return {
                "status": "error",
                "message": "Text is required and must be a string"
            }
        
        if strategy not in ["fixed_size", "sentence", "paragraph", "semantic"]:
            return {
                "status": "error",
                "message": "Invalid strategy. Must be one of: fixed_size, sentence, paragraph, semantic"
            }
        
        if not isinstance(chunk_size, int) or chunk_size < 1 or chunk_size > 10000:
            return {
                "status": "error",
                "message": "chunk_size must be an integer between 1 and 10000"
            }
        
        if not isinstance(overlap, int) or overlap < 0 or overlap >= chunk_size:
            return {
                "status": "error",
                "message": "overlap must be a non-negative integer less than chunk_size"
            }
        
        if not isinstance(max_chunks, int) or max_chunks < 1 or max_chunks > 1000:
            return {
                "status": "error",
                "message": "max_chunks must be an integer between 1 and 1000"
            }
        
        # Use provided data processor or default mock
        processor = data_processor or _mock_data_processor
        chunks = await processor.chunk_text(text, strategy, chunk_size, overlap)
        
        # Limit number of chunks
        if len(chunks) > max_chunks:
            chunks = chunks[:max_chunks]
        
        return {
            "status": "success",
            "chunks": chunks,
            "total_chunks": len(chunks),
            "original_length": len(text),
            "strategy": strategy,
            "chunk_size": chunk_size,
            "overlap": overlap,
            "message": f"Text chunked into {len(chunks)} pieces using {strategy} strategy"
        }
        
    except Exception as e:
        logger.error(f"Text chunking error: {e}")
        return {
            "status": "error",
            "message": f"Text chunking failed: {str(e)}"
        }

async def transform_data(data: Any, transformation: str, **parameters) -> Dict[str, Any]:
    """
    Apply various data transformations and processing operations.
    
    Args:
        data: Data to transform
        transformation: Type of transformation to apply
        **parameters: Additional parameters for transformation
        
    Returns:
        Dictionary containing transformation result
    """
    try:
        # Input validation
        if data is None:
            return {
                "status": "error",
                "message": "Data is required"
            }
        
        if not transformation or not isinstance(transformation, str):
            return {
                "status": "error",
                "message": "Transformation type is required and must be a string"
            }
        
        valid_transformations = [
            "normalize_text", "extract_metadata", "filter_fields", 
            "validate_schema", "clean_data", "aggregate_data"
        ]
        
        if transformation not in valid_transformations:
            return {
                "status": "error",
                "message": f"Invalid transformation. Must be one of: {', '.join(valid_transformations)}"
            }
        
        # Use mock data processor
        processor = _mock_data_processor
        
        if transformation == "clean_data":
            # Mock data cleaning
            if isinstance(data, dict):
                cleaned = {k: v for k, v in data.items() if v is not None and v != ""}
                return {
                    "status": "success",
                    "original_data": data,
                    "cleaned_data": cleaned,
                    "removed_fields": len(data) - len(cleaned),
                    "message": "Data cleaned successfully"
                }
        
        elif transformation == "aggregate_data":
            # Mock data aggregation
            if isinstance(data, list):
                numeric_fields = []
                for item in data:
                    if isinstance(item, dict):
                        for k, v in item.items():
                            if isinstance(v, (int, float)) and k not in numeric_fields:
                                numeric_fields.append(k)
                
                aggregation = {
                    "count": len(data),
                    "numeric_fields": numeric_fields,
                    "sample_item": data[0] if data else None
                }
                
                return {
                    "status": "success",
                    "original_count": len(data),
                    "aggregation": aggregation,
                    "message": "Data aggregated successfully"
                }
        
        # Apply transformation using processor
        result = await processor.transform_data(data, transformation, **parameters)
        
        return {
            "status": "success",
            "transformation": transformation,
            "original_data": data,
            "transformed_data": result,
            "parameters": parameters,
            "message": f"Applied {transformation} transformation successfully"
        }
        
    except Exception as e:
        logger.error(f"Data transformation error: {e}")
        return {
            "status": "error",
            "message": f"Data transformation failed: {str(e)}"
        }

async def convert_format(data: Any, source_format: str, target_format: str,
                        options: Optional[Dict[str, Any]] = None,
                        data_processor=None) -> Dict[str, Any]:
    """
    Convert data between different formats.
    
    Args:
        data: Data to convert
        source_format: Source format (json, csv, parquet, jsonl, txt)
        target_format: Target format (json, csv, parquet, jsonl, txt)
        options: Optional conversion parameters
        data_processor: Optional data processor service
        
    Returns:
        Dictionary containing format conversion result
    """
    try:
        # Input validation
        if data is None:
            return {
                "status": "error",
                "message": "Data is required"
            }
        
        supported_formats = ["json", "csv", "parquet", "jsonl", "txt"]
        
        if source_format not in supported_formats:
            return {
                "status": "error",
                "message": f"Invalid source_format. Must be one of: {', '.join(supported_formats)}"
            }
        
        if target_format not in supported_formats:
            return {
                "status": "error",
                "message": f"Invalid target_format. Must be one of: {', '.join(supported_formats)}"
            }
        
        if source_format == target_format:
            return {
                "status": "success",
                "converted_data": data,
                "source_format": source_format,
                "target_format": target_format,
                "message": "No conversion needed - formats are the same"
            }
        
        # Use provided data processor or default mock
        processor = data_processor or _mock_data_processor
        converted_data = await processor.convert_format(data, source_format, target_format)
        
        return {
            "status": "success",
            "source_format": source_format,
            "target_format": target_format,
            "original_data": data,
            "converted_data": converted_data,
            "options": options or {},
            "message": f"Successfully converted from {source_format} to {target_format}"
        }
        
    except Exception as e:
        logger.error(f"Format conversion error: {e}")
        return {
            "status": "error",
            "message": f"Format conversion failed: {str(e)}"
        }

async def validate_data(data: Any, validation_type: str, schema: Optional[Dict[str, Any]] = None,
                       rules: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Validate data against schemas and rules.
    
    Args:
        data: Data to validate
        validation_type: Type of validation (schema, format, completeness, quality)
        schema: Optional schema for validation
        rules: Optional list of validation rules
        
    Returns:
        Dictionary containing validation result
    """
    try:
        # Input validation
        if data is None:
            return {
                "status": "error",
                "message": "Data is required"
            }
        
        if validation_type not in ["schema", "format", "completeness", "quality"]:
            return {
                "status": "error",
                "message": "Invalid validation_type. Must be one of: schema, format, completeness, quality"
            }
        
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "metrics": {}
        }
        
        if validation_type == "schema":
            # Basic schema validation
            if schema and isinstance(data, dict):
                required_fields = schema.get("required", [])
                missing_fields = [f for f in required_fields if f not in data]
                
                if missing_fields:
                    validation_result["valid"] = False
                    validation_result["errors"].append(f"Missing required fields: {missing_fields}")
                
                validation_result["metrics"]["required_fields_present"] = len(required_fields) - len(missing_fields)
                validation_result["metrics"]["total_required_fields"] = len(required_fields)
        
        elif validation_type == "format":
            # Format validation
            if isinstance(data, str):
                if not data.strip():
                    validation_result["warnings"].append("Empty or whitespace-only string")
                validation_result["metrics"]["character_count"] = len(data)
                validation_result["metrics"]["word_count"] = len(data.split())
        
        elif validation_type == "completeness":
            # Completeness validation
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
            # Data quality validation
            quality_score = 1.0
            issues = []
            
            if isinstance(data, str):
                # Text quality checks
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
        logger.error(f"Data validation error: {e}")
        return {
            "status": "error",
            "message": f"Data validation failed: {str(e)}"
        }
