# ipfs_datasets_py/mcp_server/validators.py

import re
import json
import hashlib
import logging
from typing import Any, Dict, List, Optional, Union, Set
from urllib.parse import urlparse
from pathlib import Path

logger = logging.getLogger(__name__)

class ValidationError(Exception):
    """Custom validation error for MCP tools."""
    
    def __init__(self, parameter: str, message: str):
        self.parameter = parameter
        self.message = message
        super().__init__(f"Validation error for parameter '{parameter}': {message}")

class EnhancedParameterValidator:
    """
    Enhanced parameter validation for production MCP tools.
    Provides comprehensive validation for various data types and formats.
    """
    
    # Model name patterns
    VALID_MODEL_PATTERNS = [
        r'^sentence-transformers/.*',
        r'^all-.*',
        r'^openai/.*',
        r'^cohere/.*',
        r'^huggingface/.*',
        r'^local/.*',
        r'^text-embedding-.*',
        r'^multilingual-.*'
    ]
    
    # Collection name pattern (alphanumeric, hyphens, underscores)
    COLLECTION_NAME_PATTERN = r'^[a-zA-Z0-9_-]+$'
    
    # IPFS hash patterns
    IPFS_HASH_PATTERNS = [
        r'^Qm[1-9A-HJ-NP-Za-km-z]{44}$',  # CIDv0
        r'^baf[a-z0-9]{56}$',              # CIDv1
        r'^bafybe[a-z0-9]{52}$',           # CIDv1 base32
    ]
    
    # File extension patterns
    SUPPORTED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff'}
    SUPPORTED_AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac'}
    SUPPORTED_TEXT_EXTENSIONS = {'.txt', '.md', '.json', '.csv', '.xml', '.html', '.yaml', '.yml'}
    SUPPORTED_DATA_EXTENSIONS = {'.parquet', '.arrow', '.feather', '.hdf5', '.h5'}
    
    def __init__(self):
        self.validation_cache: Dict[str, bool] = {}
        self.performance_metrics = {
            'validations_performed': 0,
            'validation_errors': 0,
            'cache_hits': 0
        }
    
    def _cache_key(self, value: Any, validation_type: str) -> str:
        """Generate cache key for validation result."""
        return f"{validation_type}:{hashlib.md5(str(value).encode()).hexdigest()}"
    
    def validate_text_input(self, text: str, max_length: int = 10000, 
                           min_length: int = 1, allow_empty: bool = False) -> str:
        """Validate text input with length constraints and content checks."""
        self.performance_metrics['validations_performed'] += 1
        
        if not isinstance(text, str):
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("text", "Text input must be a string")
        
        if not allow_empty and len(text.strip()) < min_length:
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("text", f"Text must be at least {min_length} characters long")
        
        if len(text) > max_length:
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("text", f"Text must not exceed {max_length} characters")
        
        # Check for potentially malicious content
        if self._contains_suspicious_patterns(text):
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("text", "Text contains potentially unsafe content")
        
        return text.strip()
    
    def validate_model_name(self, model_name: str) -> str:
        """Validate embedding model name with caching."""
        cache_key = self._cache_key(model_name, "model_name")
        
        if cache_key in self.validation_cache:
            self.performance_metrics['cache_hits'] += 1
            if not self.validation_cache[cache_key]:
                raise ValidationError("model_name", "Invalid model name (cached)")
            return model_name
        
        self.performance_metrics['validations_performed'] += 1
        
        if not isinstance(model_name, str):
            self.validation_cache[cache_key] = False
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("model_name", "Model name must be a string")
        
        if not model_name.strip():
            self.validation_cache[cache_key] = False
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("model_name", "Model name cannot be empty")
        
        # Check against known patterns
        is_valid = any(re.match(pattern, model_name) for pattern in self.VALID_MODEL_PATTERNS)
        
        if not is_valid:
            # Log warning but allow for flexibility
            logger.warning(f"Unknown model pattern: {model_name}")
            # Still consider it valid for flexibility
            is_valid = True
        
        self.validation_cache[cache_key] = is_valid
        return model_name
    
    def validate_ipfs_hash(self, ipfs_hash: str) -> str:
        """Validate IPFS hash format."""
        self.performance_metrics['validations_performed'] += 1
        
        if not isinstance(ipfs_hash, str):
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("ipfs_hash", "IPFS hash must be a string")
        
        if not any(re.match(pattern, ipfs_hash) for pattern in self.IPFS_HASH_PATTERNS):
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("ipfs_hash", "Invalid IPFS hash format")
        
        return ipfs_hash
    
    def validate_numeric_range(self, value: Union[int, float], param_name: str,
                              min_val: Optional[float] = None, 
                              max_val: Optional[float] = None,
                              allow_none: bool = False) -> Union[int, float, None]:
        """Validate numeric value within specified range."""
        self.performance_metrics['validations_performed'] += 1
        
        if value is None and allow_none:
            return None
        
        if not isinstance(value, (int, float)):
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError(param_name, "Value must be a number")
        
        if min_val is not None and value < min_val:
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError(param_name, f"Value must be >= {min_val}")
        
        if max_val is not None and value > max_val:
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError(param_name, f"Value must be <= {max_val}")
        
        return value
    
    def validate_collection_name(self, collection_name: str) -> str:
        """Validate collection name format with enhanced security checks."""
        self.performance_metrics['validations_performed'] += 1
        
        if not isinstance(collection_name, str):
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("collection_name", "Collection name must be a string")
        
        if not re.match(self.COLLECTION_NAME_PATTERN, collection_name):
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError(
                "collection_name", 
                "Collection name must contain only alphanumeric characters, hyphens, and underscores"
            )
        
        if len(collection_name) > 64:
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("collection_name", "Collection name must not exceed 64 characters")
        
        if len(collection_name) < 2:
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("collection_name", "Collection name must be at least 2 characters long")
        
        # Check for reserved names
        reserved_names = {'admin', 'system', 'root', 'default', 'null', 'undefined'}
        if collection_name.lower() in reserved_names:
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("collection_name", f"'{collection_name}' is a reserved name")
        
        return collection_name
    
    def validate_search_filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate search filter parameters with enhanced security."""
        self.performance_metrics['validations_performed'] += 1
        
        if not isinstance(filters, dict):
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("filters", "Filters must be a dictionary")
        
        if len(filters) > 50:  # Prevent excessive filter complexity
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("filters", "Too many filters (maximum 50 allowed)")
        
        validated_filters = {}
        
        for key, value in filters.items():
            # Validate filter key
            if not isinstance(key, str) or not key.strip():
                self.performance_metrics['validation_errors'] += 1
                raise ValidationError("filters", f"Filter key '{key}' must be a non-empty string")
            
            if len(key) > 100:  # Prevent excessively long keys
                self.performance_metrics['validation_errors'] += 1
                raise ValidationError("filters", f"Filter key '{key}' is too long (max 100 characters)")
            
            # Validate filter value types
            if isinstance(value, (str, int, float, bool)):
                validated_filters[key] = value
            elif isinstance(value, list):
                if len(value) > 1000:  # Prevent excessive list sizes
                    self.performance_metrics['validation_errors'] += 1
                    raise ValidationError("filters", f"Filter '{key}' list is too long (max 1000 items)")
                
                if all(isinstance(item, (str, int, float, bool)) for item in value):
                    validated_filters[key] = value
                else:
                    self.performance_metrics['validation_errors'] += 1
                    raise ValidationError("filters", f"Filter '{key}' contains invalid list items")
            elif isinstance(value, dict):
                # Handle range filters
                allowed_operators = {'min', 'max', 'gte', 'lte', 'gt', 'lt', 'eq', 'ne', 'in', 'nin'}
                if set(value.keys()).issubset(allowed_operators):
                    validated_filters[key] = value
                else:
                    self.performance_metrics['validation_errors'] += 1
                    raise ValidationError("filters", f"Filter '{key}' contains invalid operators")
            else:
                self.performance_metrics['validation_errors'] += 1
                raise ValidationError("filters", f"Filter '{key}' has unsupported value type")
        
        return validated_filters
    
    def validate_file_path(self, file_path: str, check_exists: bool = False,
                          allowed_extensions: Optional[Set[str]] = None) -> str:
        """Validate file path format and optionally check existence."""
        self.performance_metrics['validations_performed'] += 1
        
        if not isinstance(file_path, str):
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("file_path", "File path must be a string")
        
        try:
            path = Path(file_path)
        except Exception as e:
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("file_path", f"Invalid file path format: {e}")
        
        # Security check: prevent directory traversal
        if '..' in str(path) or str(path).startswith('/'):
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("file_path", "File path contains invalid characters or patterns")
        
        if allowed_extensions:
            if path.suffix.lower() not in allowed_extensions:
                self.performance_metrics['validation_errors'] += 1
                raise ValidationError(
                    "file_path", 
                    f"File extension '{path.suffix}' not in allowed extensions: {allowed_extensions}"
                )
        
        if check_exists and not path.exists():
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("file_path", f"File does not exist: {file_path}")
        
        return str(path)
    
    def validate_json_schema(self, data: Any, schema: Dict[str, Any]) -> Any:
        """Validate data against JSON schema."""
        self.performance_metrics['validations_performed'] += 1
        
        try:
            import jsonschema
            jsonschema.validate(data, schema)
            return data
        except ImportError:
            logger.warning("jsonschema not available, skipping schema validation")
            return data
        except Exception as e:
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("schema", f"Schema validation failed: {e}")
    
    def validate_url(self, url: str, allowed_schemes: Optional[Set[str]] = None) -> str:
        """Validate URL format and scheme."""
        self.performance_metrics['validations_performed'] += 1
        
        if not isinstance(url, str):
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("url", "URL must be a string")
        
        try:
            parsed = urlparse(url)
        except Exception as e:
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("url", f"Invalid URL format: {e}")
        
        if not parsed.scheme:
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("url", "URL must include a scheme (http, https, etc.)")
        
        if allowed_schemes and parsed.scheme not in allowed_schemes:
            self.performance_metrics['validation_errors'] += 1
            raise ValidationError("url", f"URL scheme '{parsed.scheme}' not in allowed schemes: {allowed_schemes}")
        
        return url
    
    def _contains_suspicious_patterns(self, text: str) -> bool:
        """Check for potentially suspicious patterns in text."""
        suspicious_patterns = [
            r'<script[^>]*>',  # Script tags
            r'javascript:',     # JavaScript URLs
            r'eval\s*\(',      # eval() calls
            r'exec\s*\(',      # exec() calls
            r'import\s+os',    # OS imports
            r'__import__',     # Dynamic imports
            r'subprocess',     # Subprocess calls
        ]
        
        text_lower = text.lower()
        return any(re.search(pattern, text_lower) for pattern in suspicious_patterns)
    
    def get_performance_metrics(self) -> Dict[str, int]:
        """Get validation performance metrics."""
        return self.performance_metrics.copy()
    
    def clear_cache(self) -> None:
        """Clear validation cache."""
        self.validation_cache.clear()
        logger.info("Validation cache cleared")

# Global validator instance
validator = EnhancedParameterValidator()
