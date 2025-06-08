# src/mcp_server/validators.py

import re
import json
import hashlib
import logging
from typing import Any, Dict, List, Optional, Union, Set
from urllib.parse import urlparse
from pathlib import Path

import jsonschema
from jsonschema import validate, ValidationError as JsonSchemaValidationError

# from .error_handlers import ValidationError # Commented out for now

logger = logging.getLogger(__name__)

# Define a placeholder ValidationError if the original is not available
class ValidationError(ValueError):
    """Placeholder for ValidationError if original is not imported."""
    def __init__(self, param_name, message):
        self.param_name = param_name
        self.message = message
        super().__init__(f"Validation Error for parameter '{param_name}': {message}")

class ParameterValidator:
    """
    Comprehensive parameter validation for MCP tools.
    Provides validation for various data types and formats.
    """
    
    # Model name patterns
    VALID_MODEL_PATTERNS = [
        r'^sentence-transformers/.*',
        r'^all-.*',
        r'^openai/.*',
        r'^cohere/.*',
        r'^huggingface/.*',
        r'^local/.*'
    ]
    
    # Collection name pattern (alphanumeric, hyphens, underscores)
    COLLECTION_NAME_PATTERN = r'^[a-zA-Z0-9_-]+$'
    
    # File extension patterns
    SUPPORTED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    SUPPORTED_AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.ogg', '.m4a'}
    SUPPORTED_TEXT_EXTENSIONS = {'.txt', '.md', '.json', '.csv', '.xml', '.html'}
    
    def __init__(self):
        self.validation_cache: Dict[str, bool] = {}
    
    def validate_text_input(self, text: str, max_length: int = 10000, 
                           min_length: int = 1, allow_empty: bool = False) -> str:
        """Validate text input with length constraints."""
        if not isinstance(text, str):
            # raise ValidationError("text", "Text input must be a string") # Commented out
            raise ValueError("Text input must be a string") # Using ValueError as a fallback
        
        if not allow_empty and len(text.strip()) < min_length:
            # raise ValidationError("text", f"Text must be at least {min_length} characters long") # Commented out
            raise ValueError(f"Text must be at least {min_length} characters long") # Using ValueError as a fallback
        
        if len(text) > max_length:
            # raise ValidationError("text", f"Text must not exceed {max_length} characters") # Commented out
            raise ValueError(f"Text must not exceed {max_length} characters") # Using ValueError as a fallback
        
        return text.strip()
    
    def validate_model_name(self, model_name: str) -> str:
        """Validate embedding model name."""
        if not isinstance(model_name, str):
            # raise ValidationError("model_name", "Model name must be a string") # Commented out
            raise ValueError("Model name must be a string") # Using ValueError as a fallback
        
        if not model_name.strip():
            # raise ValidationError("model_name", "Model name cannot be empty") # Commented out
            raise ValueError("Model name cannot be empty") # Using ValueError as a fallback
        
        # Check against known patterns
        for pattern in self.VALID_MODEL_PATTERNS:
            if re.match(pattern, model_name):
                return model_name
        
        # If no pattern matches, log warning but allow (for flexibility)
        logger.warning(f"Unknown model pattern: {model_name}")
        return model_name
    
    def validate_numeric_range(self, value: Union[int, float], param_name: str,
                              min_val: Optional[float] = None, 
                              max_val: Optional[float] = None) -> Union[int, float]:
        """Validate numeric value within specified range."""
        if not isinstance(value, (int, float)):
            # raise ValidationError(param_name, "Value must be a number") # Commented out
            raise ValueError("Value must be a number") # Using ValueError as a fallback
        
        if min_val is not None and value < min_val:
            # raise ValidationError(param_name, f"Value must be >= {min_val}") # Commented out
            raise ValueError(f"Value must be >= {min_val}") # Using ValueError as a fallback
        
        if max_val is not None and value > max_val:
            # raise ValidationError(param_name, f"Value must be <= {max_val}") # Commented out
            raise ValueError(f"Value must be <= {max_val}") # Using ValueError as a fallback
        
        return value
    
    def validate_collection_name(self, collection_name: str) -> str:
        """Validate collection name format."""
        if not isinstance(collection_name, str):
            # raise ValidationError("collection_name", "Collection name must be a string") # Commented out
            raise ValueError("Collection name must be a string") # Using ValueError as a fallback
        
        if not re.match(self.COLLECTION_NAME_PATTERN, collection_name):
            # raise ValidationError(
            #     "collection_name",
            #     "Collection name must contain only alphanumeric characters, hyphens, and underscores"
            # ) # Commented out
            raise ValueError("Collection name must contain only alphanumeric characters, hyphens, and underscores") # Using ValueError as a fallback
        
        if len(collection_name) > 64:
            # raise ValidationError("collection_name", "Collection name must not exceed 64 characters") # Commented out
            raise ValueError("Collection name must not exceed 64 characters") # Using ValueError as a fallback
        
        return collection_name
    
    def validate_search_filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate search filter parameters."""
        if not isinstance(filters, dict):
            # raise ValidationError("filters", "Filters must be a dictionary") # Commented out
            raise ValueError("Filters must be a dictionary") # Using ValueError as a fallback
        
        validated_filters = {}
        
        for key, value in filters.items():
            # Validate filter key
            if not isinstance(key, str) or not key.strip():
                # raise ValidationError("filters", f"Filter key '{key}' must be a non-empty string") # Commented out
                raise ValueError(f"Filter key '{key}' must be a non-empty string") # Using ValueError as a fallback
            
            # Validate filter value types
            if isinstance(value, (str, int, float, bool)):
                validated_filters[key] = value
            elif isinstance(value, list):
                # Validate list contents
                if all(isinstance(item, (str, int, float, bool)) for item in value):
                    validated_filters[key] = value
                else:
                    # raise ValidationError("filters", f"Filter '{key}' contains invalid list items") # Commented out
                    raise ValueError(f"Filter '{key}' contains invalid list items") # Using ValueError as a fallback
            elif isinstance(value, dict):
                # Handle range filters
                if set(value.keys()).issubset({'min', 'max', 'gte', 'lte', 'gt', 'lt'}):
                    validated_filters[key] = value
                else:
                    # raise ValidationError("filters", f"Filter '{key}' has unsupported value type") # Commented out
                    raise ValueError(f"Filter '{key}' has unsupported value type") # Using ValueError as a fallback
            else:
                raise ValidationError("filters", f"Filter '{key}' has unsupported value type")
        
        return validated_filters
    
    def validate_file_path(self, file_path: str, check_exists: bool = False,
                          allowed_extensions: Optional[Set[str]] = None) -> str:
        """Validate file path format and optionally check existence."""
        if not isinstance(file_path, str):
            # raise ValidationError("file_path", "File path must be a string") # Commented out
            raise ValueError("File path must be a string") # Using ValueError as a fallback
        
        try:
            path = Path(file_path)
        except Exception as e:
            # raise ValidationError("file_path", f"Invalid file path format: {e}") # Commented out
            raise ValueError(f"Invalid file path format: {e}") # Using ValueError as a fallback
        
        if allowed_extensions:
            if path.suffix.lower() not in allowed_extensions:
                # raise ValidationError(
                #     "file_path",
                #     f"File extension must be one of: {', '.join(allowed_extensions)}"
                # ) # Commented out
                raise ValueError(f"File extension must be one of: {', '.join(allowed_extensions)}") # Using ValueError as a fallback
        
        if check_exists and not path.exists():
            # raise ValidationError("file_path", "File does not exist") # Commented out
            raise FileNotFoundError("File does not exist") # Using FileNotFoundError as a fallback
        
        return str(path)
    
    def validate_url(self, url: str) -> str:
        """Validate URL format."""
        if not isinstance(url, str):
            # raise ValidationError("url", "URL must be a string") # Commented out
            raise ValueError("URL must be a string") # Using ValueError as a fallback
        
        try:
            result = urlparse(url)
            if not all([result.scheme, result.netloc]):
                # raise ValidationError("url", "Invalid URL format") # Commented out
                raise ValueError("Invalid URL format") # Using ValueError as a fallback
        except Exception as e:
            # raise ValidationError("url", f"Invalid URL: {e}") # Commented out
            raise ValueError(f"Invalid URL: {e}") # Using ValueError as a fallback
        
        return url
    
    def validate_json_schema(self, data: Any, schema: Dict[str, Any], 
                           parameter_name: str = "data") -> Any:
        """Validate data against JSON schema."""
        try:
            validate(instance=data, schema=schema)
            return data
        except JsonSchemaValidationError as e:
            # raise ValidationError(parameter_name, f"Schema validation failed: {e.message}") # Commented out
            raise ValueError(f"Schema validation failed for parameter '{parameter_name}': {e.message}") # Using ValueError as a fallback
    
    def validate_batch_size(self, batch_size: int, max_batch_size: int = 100) -> int:
        """Validate batch size parameter."""
        # return int(self.validate_numeric_range( # Commented out
        #     batch_size, "batch_size", min_val=1, max_val=max_batch_size
        # ))
        # Using direct validation as a fallback
        if not isinstance(batch_size, int) or batch_size < 1 or batch_size > max_batch_size:
             # raise ValidationError("batch_size", f"Batch size must be an integer between 1 and {max_batch_size}") # Commented out
             raise ValueError(f"Batch size must be an integer between 1 and {max_batch_size}") # Using ValueError as a fallback
        return batch_size
    
    def validate_algorithm_choice(self, algorithm: str, 
                                 allowed_algorithms: List[str]) -> str:
        """Validate algorithm choice from allowed options."""
        if not isinstance(algorithm, str):
            # raise ValidationError("algorithm", "Algorithm must be a string") # Commented out
            raise ValueError("Algorithm must be a string") # Using ValueError as a fallback
        
        if algorithm not in allowed_algorithms:
            # raise ValidationError(
            #     "algorithm",
            #     f"Algorithm must be one of: {', '.join(allowed_algorithms)}"
            # ) # Commented out
            raise ValueError(f"Algorithm must be one of: {', '.join(allowed_algorithms)}") # Using ValueError as a fallback
        
        return algorithm
    
    def validate_embedding_vector(self, embedding: List[float]) -> List[float]:
        """Validate embedding vector format."""
        if not isinstance(embedding, list):
            # raise ValidationError("embedding", "Embedding must be a list") # Commented out
            raise ValueError("Embedding must be a list") # Using ValueError as a fallback
        
        if not embedding:
            # raise ValidationError("embedding", "Embedding cannot be empty") # Commented out
            raise ValueError("Embedding cannot be empty") # Using ValueError as a fallback
        
        if not all(isinstance(x, (int, float)) for x in embedding):
            # raise ValidationError("embedding", "Embedding must contain only numbers") # Commented out
            raise ValueError("Embedding must contain only numbers") # Using ValueError as a fallback
        
        return embedding
    
    def validate_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Validate metadata dictionary."""
        if not isinstance(metadata, dict):
            # raise ValidationError("metadata", "Metadata must be a dictionary") # Commented out
            raise ValueError("Metadata must be a dictionary") # Using ValueError as a fallback
        
        # Check for reasonable size
        if len(json.dumps(metadata)) > 10000:  # 10KB limit
            # raise ValidationError("metadata", "Metadata too large (max 10KB)") # Commented out
            raise ValueError("Metadata too large (max 10KB)") # Using ValueError as a fallback
        
        # Validate that all values are JSON serializable
        try:
            json.dumps(metadata)
        except (TypeError, ValueError) as e:
            # raise ValidationError("metadata", f"Metadata must be JSON serializable: {e}") # Commented out
            raise ValueError(f"Metadata must be JSON serializable: {e}") # Using ValueError as a fallback
        
        return metadata
    
    def validate_and_hash_args(self, args: Dict[str, Any]) -> str:
        """Validate arguments and return a hash for caching."""
        # Create a deterministic hash of the arguments
        args_str = json.dumps(args, sort_keys=True, default=str)
        return hashlib.md5(args_str.encode()).hexdigest()
    
    def create_tool_validator(self, schema: Dict[str, Any]):
        """Create a validator function for a specific tool schema."""
        def validator(args: Dict[str, Any]) -> Dict[str, Any]:
            # return self.validate_json_schema(args, schema, "tool_arguments") # Commented out
            # Using direct validation as a fallback
            try:
                validate(instance=args, schema=schema)
                return args
            except JsonSchemaValidationError as e:
                # raise ValidationError("tool_arguments", f"Schema validation failed: {e.message}") # Commented out
                raise ValueError(f"Schema validation failed for tool arguments: {e.message}") # Using ValueError as a fallback
        
        return validator

# Predefined schemas for common tool parameters
COMMON_SCHEMAS = {
    "text_input": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "minLength": 1,
                "maxLength": 10000
            }
        },
        "required": ["text"]
    },
    
    "embedding_generation": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "minLength": 1,
                "maxLength": 10000
            },
            "model": {
                "type": "string",
                "minLength": 1
            },
            "normalize": {
                "type": "boolean",
                "default": True
            }
        },
        "required": ["text"]
    },
    
    "search_query": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1
            },
            "collection": {
                "type": "string",
                "pattern": "^[a-zA-Z0-9_-]+$"
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1000,
                "default": 10
            },
            "threshold": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0
            }
        },
        "required": ["query", "collection"]
    }
}

# Global validator instance
validator = ParameterValidator()
