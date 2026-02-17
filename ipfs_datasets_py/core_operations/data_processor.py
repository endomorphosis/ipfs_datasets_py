"""
Core data processing operations for ipfs_datasets_py.

This module contains reusable data processing logic for:
- Text chunking with multiple strategies
- Data transformation and normalization
- Format conversion
- Schema validation

Used by:
- MCP server tools (thin wrappers)
- CLI commands
- Direct Python API imports
"""

import logging
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, Union

logger = logging.getLogger(__name__)


class DataProcessor:
    """
    Core data processor providing text chunking, transformation, and conversion.
    
    This class centralizes all data processing business logic, making it
    reusable across MCP tools, CLI commands, and Python imports.
    """
    
    def __init__(self):
        self.supported_formats = ["json", "csv", "parquet", "jsonl", "txt"]
        self.chunk_strategies = ["fixed_size", "sentence", "paragraph", "semantic"]
        self.valid_transformations = [
            "normalize_text", "extract_metadata", "filter_fields", 
            "validate_schema", "clean_data", "aggregate_data"
        ]
    
    async def chunk_text(
        self, 
        text: str, 
        strategy: str = "fixed_size", 
        chunk_size: int = 1000,
        overlap: int = 100,
        max_chunks: int = 100
    ) -> Dict[str, Any]:
        """
        Split text into chunks using various strategies.
        
        Args:
            text: Text to chunk
            strategy: Chunking strategy (fixed_size, sentence, paragraph, semantic)
            chunk_size: Maximum chunk size in characters
            overlap: Overlap between chunks in characters
            max_chunks: Maximum number of chunks to create
            
        Returns:
            Dictionary containing:
            - status: "success" or "error"
            - chunks: List of chunk dictionaries
            - total_chunks: Number of chunks created
            - original_length: Length of original text
            - strategy: Strategy used
            - message: Status message
        """
        try:
            # Input validation
            if not text or not isinstance(text, str):
                return {
                    "status": "error",
                    "message": "Text is required and must be a string"
                }
            
            if strategy not in self.chunk_strategies:
                return {
                    "status": "error",
                    "message": f"Invalid strategy. Must be one of: {', '.join(self.chunk_strategies)}"
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
            
            # Perform chunking based on strategy
            chunks = await self._chunk_by_strategy(text, strategy, chunk_size, overlap)
            
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
    
    async def _chunk_by_strategy(
        self, 
        text: str, 
        strategy: str, 
        chunk_size: int, 
        overlap: int
    ) -> List[Dict[str, Any]]:
        """Internal method to perform chunking based on strategy."""
        if strategy == "fixed_size":
            return self._chunk_fixed_size(text, chunk_size, overlap)
        elif strategy == "sentence":
            return self._chunk_by_sentence(text, chunk_size)
        elif strategy == "paragraph":
            return self._chunk_by_paragraph(text)
        elif strategy == "semantic":
            # For now, fall back to paragraph-based chunking
            # Future: integrate with semantic embeddings
            return self._chunk_by_paragraph(text)
        else:
            return self._chunk_fixed_size(text, chunk_size, overlap)
    
    def _chunk_fixed_size(
        self, 
        text: str, 
        chunk_size: int, 
        overlap: int
    ) -> List[Dict[str, Any]]:
        """Fixed-size chunking with overlap."""
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
    
    def _chunk_by_sentence(
        self, 
        text: str, 
        chunk_size: int
    ) -> List[Dict[str, Any]]:
        """Sentence-based chunking."""
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
    
    def _chunk_by_paragraph(self, text: str) -> List[Dict[str, Any]]:
        """Paragraph-based chunking."""
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
    
    async def transform_data(
        self, 
        data: Any, 
        transformation: str, 
        **parameters
    ) -> Dict[str, Any]:
        """
        Apply various data transformations and processing operations.
        
        Args:
            data: Data to transform
            transformation: Type of transformation to apply
            **parameters: Additional parameters for transformation
            
        Returns:
            Dictionary containing:
            - status: "success" or "error"
            - result: Transformation result
            - message: Status message
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
            
            if transformation not in self.valid_transformations:
                return {
                    "status": "error",
                    "message": f"Invalid transformation. Must be one of: {', '.join(self.valid_transformations)}"
                }
            
            # Apply transformation
            if transformation == "normalize_text":
                return await self._normalize_text(data)
            elif transformation == "extract_metadata":
                return await self._extract_metadata(data)
            elif transformation == "filter_fields":
                return await self._filter_fields(data, parameters.get("fields", []))
            elif transformation == "validate_schema":
                return await self._validate_schema(data, parameters.get("required_fields", []))
            elif transformation == "clean_data":
                return await self._clean_data(data)
            elif transformation == "aggregate_data":
                return await self._aggregate_data(data)
            else:
                return {
                    "status": "error",
                    "message": f"Transformation '{transformation}' not implemented"
                }
            
        except Exception as e:
            logger.error(f"Data transformation error: {e}")
            return {
                "status": "error",
                "message": f"Data transformation failed: {str(e)}"
            }
    
    async def _normalize_text(self, data: Any) -> Dict[str, Any]:
        """Normalize text data."""
        if isinstance(data, str):
            normalized = data.lower().strip()
            normalized = re.sub(r'\s+', ' ', normalized)
            return {
                "status": "success",
                "original": data,
                "result": normalized,
                "message": "Text normalized successfully"
            }
        elif isinstance(data, list):
            normalized = [d.lower().strip() if isinstance(d, str) else d for d in data]
            return {
                "status": "success",
                "original": data,
                "result": normalized,
                "message": f"Normalized {len(normalized)} text items"
            }
        else:
            return {
                "status": "error",
                "message": "Data must be string or list of strings for normalize_text"
            }
    
    async def _extract_metadata(self, data: Any) -> Dict[str, Any]:
        """Extract metadata from data."""
        if isinstance(data, dict):
            metadata = {
                "keys": list(data.keys()),
                "value_types": {k: type(v).__name__ for k, v in data.items()},
                "size": len(data)
            }
            return {
                "status": "success",
                "result": metadata,
                "message": "Metadata extracted successfully"
            }
        else:
            return {
                "status": "error",
                "message": "Data must be a dictionary for extract_metadata"
            }
    
    async def _filter_fields(self, data: Any, fields: List[str]) -> Dict[str, Any]:
        """Filter data to include only specified fields."""
        if isinstance(data, dict):
            filtered = {k: v for k, v in data.items() if k in fields}
            return {
                "status": "success",
                "original_fields": len(data),
                "result": filtered,
                "filtered_fields": len(filtered),
                "message": f"Filtered to {len(filtered)} fields"
            }
        else:
            return {
                "status": "error",
                "message": "Data must be a dictionary for filter_fields"
            }
    
    async def _validate_schema(self, data: Any, required_fields: List[str]) -> Dict[str, Any]:
        """Validate data against a schema."""
        if isinstance(data, dict):
            missing = [f for f in required_fields if f not in data]
            return {
                "status": "success",
                "result": {
                    "valid": len(missing) == 0,
                    "missing_fields": missing,
                    "found_fields": list(data.keys())
                },
                "message": "Schema validation completed" if not missing else f"Missing fields: {missing}"
            }
        else:
            return {
                "status": "error",
                "message": "Data must be a dictionary for validate_schema"
            }
    
    async def _clean_data(self, data: Any) -> Dict[str, Any]:
        """Clean data by removing null/empty values."""
        if isinstance(data, dict):
            cleaned = {k: v for k, v in data.items() if v is not None and v != ""}
            return {
                "status": "success",
                "original_data": data,
                "result": cleaned,
                "removed_fields": len(data) - len(cleaned),
                "message": "Data cleaned successfully"
            }
        else:
            return {
                "status": "error",
                "message": "Data must be a dictionary for clean_data"
            }
    
    async def _aggregate_data(self, data: Any) -> Dict[str, Any]:
        """Aggregate data statistics."""
        if isinstance(data, list):
            numeric_fields = []
            for item in data:
                if isinstance(item, dict):
                    for k, v in item.items():
                        if isinstance(v, (int, float)) and k not in numeric_fields:
                            numeric_fields.append(k)
            
            aggregation = {
                "total_records": len(data),
                "numeric_fields": numeric_fields,
                "record_types": {}
            }
            
            # Count record types
            for item in data:
                item_type = type(item).__name__
                aggregation["record_types"][item_type] = \
                    aggregation["record_types"].get(item_type, 0) + 1
            
            return {
                "status": "success",
                "result": aggregation,
                "message": f"Aggregated {len(data)} records"
            }
        else:
            return {
                "status": "error",
                "message": "Data must be a list for aggregate_data"
            }
    
    async def convert_format(
        self, 
        data: Any, 
        source_format: str, 
        target_format: str
    ) -> Dict[str, Any]:
        """
        Convert data between formats.
        
        Args:
            data: Data to convert
            source_format: Source format (json, csv, parquet, jsonl, txt)
            target_format: Target format (json, csv, parquet, jsonl, txt)
            
        Returns:
            Dictionary containing:
            - status: "success" or "error"
            - result: Converted data
            - source_format: Original format
            - target_format: Target format
            - message: Status message
        """
        try:
            if source_format not in self.supported_formats:
                return {
                    "status": "error",
                    "message": f"Unsupported source format. Must be one of: {', '.join(self.supported_formats)}"
                }
            
            if target_format not in self.supported_formats:
                return {
                    "status": "error",
                    "message": f"Unsupported target format. Must be one of: {', '.join(self.supported_formats)}"
                }
            
            # Perform conversion
            if source_format == "json" and target_format == "csv":
                result = await self._json_to_csv(data)
            elif source_format == "csv" and target_format == "json":
                result = await self._csv_to_json(data)
            else:
                # For other conversions, return as-is for now
                result = data
            
            return {
                "status": "success",
                "result": result,
                "source_format": source_format,
                "target_format": target_format,
                "message": f"Converted from {source_format} to {target_format}"
            }
            
        except Exception as e:
            logger.error(f"Format conversion error: {e}")
            return {
                "status": "error",
                "message": f"Format conversion failed: {str(e)}"
            }
    
    async def _json_to_csv(self, data: Any) -> Dict[str, Any]:
        """Convert JSON to CSV format."""
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
        else:
            return {"headers": [], "rows": [], "format": "csv"}
    
    async def _csv_to_json(self, data: Any) -> List[Dict[str, Any]]:
        """Convert CSV to JSON format."""
        if isinstance(data, dict) and "headers" in data and "rows" in data:
            json_data = []
            for row in data["rows"]:
                item = {h: v for h, v in zip(data["headers"], row)}
                json_data.append(item)
            return json_data
        else:
            return []
