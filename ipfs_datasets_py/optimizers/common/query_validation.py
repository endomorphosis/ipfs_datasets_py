"""
Query Validation Mixin

Provides reusable validation methods for GraphRAG query optimizers and related components.
This mixin extracts common validation patterns to improve code reuse and maintainability.

Usage:
    class MyOptimizer(QueryValidationMixin):
        def optimize_query(self, query):
            # Validate query structure
            if not self.validate_query_structure(query, required_fields=['vector', 'max_results']):
                query = self.ensure_query_defaults(query)
            
            # Validate parameters
            max_depth = self.validate_numeric_param(
                query.get('max_depth'), 
                param_name='max_depth',
                min_value=1, 
                max_value=10, 
                default=2
            )
            
            # Check cache
            cache_key = self.generate_cache_key(query)
            if self.validate_cache_entry(cache_key):
                return self.get_from_cache(cache_key)
"""

import time
import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple, Union


class QueryValidationMixin:
    """
    Mixin class providing common validation methods for query optimizers.
    
    This mixin provides:
    - Parameter validation with type checking and range validation
    - Cache entry validation with expiration checking
    - Query structure validation with default value injection
    - Result validation before caching
    - Generic validation utilities
    
    Expected attributes in using class:
    - logger (optional): Logger instance for validation warnings
    - cache_enabled (optional): Boolean flag for cache validation
    - cache_ttl (optional): Cache time-to-live in seconds
    - query_cache (optional): Dictionary storing cached queries
    """
    
    # ==================== Parameter Validation ====================
    
    def validate_numeric_param(
        self,
        value: Any,
        param_name: str,
        min_value: Optional[Union[int, float]] = None,
        max_value: Optional[Union[int, float]] = None,
        default: Union[int, float] = 0,
        allow_none: bool = False
    ) -> Union[int, float]:
        """
        Validate a numeric parameter with optional range checking.
        
        Args:
            value: Parameter value to validate
            param_name: Name of parameter (for error messages)
            min_value: Minimum allowed value (inclusive), None for no minimum
            max_value: Maximum allowed value (inclusive), None for no maximum
            default: Default value if validation fails
            allow_none: Whether None is a valid value
            
        Returns:
            Validated numeric value or default
            
        Example:
            max_depth = self.validate_numeric_param(
                query.get('max_depth'),
                param_name='max_depth',
                min_value=1,
                max_value=10,
                default=2
            )
        """
        # Handle None
        if value is None:
            if allow_none:
                return value
            self._log_validation_warning(
                f"{param_name} is None, using default {default}"
            )
            return default
        
        # Check if numeric
        if not isinstance(value, (int, float)):
            try:
                value = float(value)
            except (ValueError, TypeError):
                self._log_validation_warning(
                    f"{param_name} is not numeric ({type(value).__name__}), using default {default}"
                )
                return default
        
        # Check minimum
        if min_value is not None and value < min_value:
            self._log_validation_warning(
                f"{param_name} ({value}) below minimum ({min_value}), clamping to minimum"
            )
            return min_value
        
        # Check maximum
        if max_value is not None and value > max_value:
            self._log_validation_warning(
                f"{param_name} ({value}) above maximum ({max_value}), clamping to maximum"
            )
            return max_value
        
        return value
    
    def validate_list_param(
        self,
        value: Any,
        param_name: str,
        element_type: Optional[type] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        default: Optional[List] = None,
        allow_none: bool = False
    ) -> Optional[List]:
        """
        Validate a list parameter with optional element type and length checking.
        
        Args:
            value: Parameter value to validate
            param_name: Name of parameter (for error messages)
            element_type: Required type for list elements, None for no checking
            min_length: Minimum list length, None for no minimum
            max_length: Maximum list length, None for no maximum
            default: Default value if validation fails
            allow_none: Whether None is a valid value
            
        Returns:
            Validated list or default
            
        Example:
            edge_types = self.validate_list_param(
                query.get('edge_types'),
                param_name='edge_types',
                element_type=str,
                default=[]
            )
        """
        if default is None:
            default = []
        
        # Handle None
        if value is None:
            if allow_none:
                return value
            return default
        
        # Check if list
        if not isinstance(value, (list, tuple)):
            self._log_validation_warning(
                f"{param_name} is not a list ({type(value).__name__}), using default"
            )
            return default
        
        # Convert tuple to list
        if isinstance(value, tuple):
            value = list(value)
        
        # Check element types
        if element_type is not None:
            validated_list = []
            for i, elem in enumerate(value):
                if not isinstance(elem, element_type):
                    try:
                        elem = element_type(elem)
                    except (ValueError, TypeError):
                        self._log_validation_warning(
                            f"{param_name}[{i}] is not {element_type.__name__}, skipping"
                        )
                        continue
                validated_list.append(elem)
            value = validated_list
        
        # Check minimum length
        if min_length is not None and len(value) < min_length:
            self._log_validation_warning(
                f"{param_name} length ({len(value)}) below minimum ({min_length}), using default"
            )
            return default
        
        # Check maximum length
        if max_length is not None and len(value) > max_length:
            self._log_validation_warning(
                f"{param_name} length ({len(value)}) above maximum ({max_length}), truncating"
            )
            value = value[:max_length]
        
        return value
    
    def validate_string_param(
        self,
        value: Any,
        param_name: str,
        allowed_values: Optional[List[str]] = None,
        default: str = "",
        allow_none: bool = False,
        case_sensitive: bool = True
    ) -> Optional[str]:
        """
        Validate a string parameter with optional allowed values checking.
        
        Args:
            value: Parameter value to validate
            param_name: Name of parameter (for error messages)
            allowed_values: List of allowed string values, None for no restriction
            default: Default value if validation fails
            allow_none: Whether None is a valid value
            case_sensitive: Whether allowed_values comparison is case-sensitive
            
        Returns:
            Validated string or default
            
        Example:
            graph_type = self.validate_string_param(
                query.get('graph_type'),
                param_name='graph_type',
                allowed_values=['wikipedia', 'ipld', 'general'],
                default='general'
            )
        """
        # Handle None
        if value is None:
            if allow_none:
                return value
            return default
        
        # Convert to string
        if not isinstance(value, str):
            try:
                value = str(value)
            except (ValueError, TypeError):
                self._log_validation_warning(
                    f"{param_name} cannot be converted to string, using default"
                )
                return default
        
        # Check allowed values
        if allowed_values is not None:
            if case_sensitive:
                if value not in allowed_values:
                    self._log_validation_warning(
                        f"{param_name} ({value}) not in allowed values {allowed_values}, using default {default}"
                    )
                    return default
            else:
                value_lower = value.lower()
                allowed_lower = [v.lower() for v in allowed_values]
                if value_lower not in allowed_lower:
                    self._log_validation_warning(
                        f"{param_name} ({value}) not in allowed values {allowed_values}, using default {default}"
                    )
                    return default
        
        return value
    
    # ==================== Cache Validation ====================
    
    def validate_cache_enabled(self) -> bool:
        """
        Check if caching is enabled and available.
        
        Returns:
            True if cache is enabled and cache_enabled attribute exists
            
        Example:
            if self.validate_cache_enabled():
                cache_key = self.generate_cache_key(query)
        """
        if not hasattr(self, 'cache_enabled'):
            return False
        return bool(getattr(self, 'cache_enabled', False))
    
    def validate_cache_entry(
        self,
        cache_key: str,
        check_expiration: bool = True
    ) -> bool:
        """
        Validate a cache entry exists and is not expired.
        
        Args:
            cache_key: Cache key to validate
            check_expiration: Whether to check if entry has expired
            
        Returns:
            True if cache entry is valid
            
        Example:
            cache_key = self.generate_cache_key(query)
            if self.validate_cache_entry(cache_key):
                return self.get_from_cache(cache_key)
        """
        # Check if caching is enabled
        if not self.validate_cache_enabled():
            return False
        
        # Check if cache_key is valid
        if cache_key is None:
            return False
        
        # Check if query_cache exists
        if not hasattr(self, 'query_cache') or self.query_cache is None:
            return False
        
        # Check if entry exists
        if cache_key not in self.query_cache:
            return False
        
        entry = self.query_cache.get(cache_key)
        if entry is None:
            return False
        
        # Validate entry structure (should be tuple of (result, timestamp))
        if not isinstance(entry, tuple) or len(entry) != 2:
            # Invalid cache entry, remove it
            try:
                del self.query_cache[cache_key]
            except Exception:
                pass
            return False
        
        # Check expiration if requested
        if check_expiration:
            _, timestamp = entry
            
            # Verify timestamp is valid
            if not isinstance(timestamp, (int, float)):
                try:
                    del self.query_cache[cache_key]
                except Exception:
                    pass
                return False
            
            # Check if expired
            cache_ttl = getattr(self, 'cache_ttl', 300.0)
            if time.time() - timestamp > cache_ttl:
                try:
                    del self.query_cache[cache_key]
                except Exception:
                    pass
                return False
        
        return True
    
    def generate_cache_key(
        self,
        *args,
        include_class_name: bool = False,
        **kwargs
    ) -> str:
        """
        Generate a cache key from arguments.
        
        Args:
            *args: Positional arguments to include in key
            include_class_name: Whether to include class name in key
            **kwargs: Keyword arguments to include in key
            
        Returns:
            SHA256 hash of arguments as cache key
            
        Example:
            cache_key = self.generate_cache_key(
                query_vector,
                max_results=10,
                max_depth=2
            )
        """
        try:
            # Start with class name if requested
            key_parts = []
            if include_class_name:
                key_parts.append(self.__class__.__name__)
            
            # Add positional args
            for arg in args:
                if hasattr(arg, 'tolist'):
                    # Handle numpy arrays/tensors
                    key_parts.append(str(arg.tolist()))
                else:
                    key_parts.append(str(arg))
            
            # Add keyword args (sorted for consistency)
            for k, v in sorted(kwargs.items()):
                if hasattr(v, 'tolist'):
                    key_parts.append(f"{k}={v.tolist()}")
                else:
                    key_parts.append(f"{k}={v}")
            
            # Create hash
            key_str = "_".join(key_parts)
            return hashlib.sha256(key_str.encode()).hexdigest()
            
        except Exception as e:
            # Fallback to simple hash on error
            self._log_validation_warning(
                f"Error generating cache key: {str(e)}, using fallback"
            )
            fallback_str = f"{len(args)}args_{len(kwargs)}kwargs_{time.time()}"
            return hashlib.sha256(fallback_str.encode()).hexdigest()
    
    # ==================== Query Structure Validation ====================
    
    def validate_query_structure(
        self,
        query: Any,
        required_fields: Optional[List[str]] = None
    ) -> bool:
        """
        Validate that query is a dictionary with required fields.
        
        Args:
            query: Query to validate
            required_fields: List of required field names
            
        Returns:
            True if query structure is valid
            
        Example:
            if not self.validate_query_structure(
                query,
                required_fields=['vector', 'max_results']
            ):
                query = self.ensure_query_defaults(query)
        """
        # Check if query is a dictionary
        if not isinstance(query, dict):
            self._log_validation_warning(
                f"Query is not a dictionary ({type(query).__name__})"
            )
            return False
        
        # Check required fields
        if required_fields is not None:
            missing_fields = [f for f in required_fields if f not in query]
            if missing_fields:
                self._log_validation_warning(
                    f"Query missing required fields: {missing_fields}"
                )
                return False
        
        return True
    
    def ensure_query_defaults(
        self,
        query: Any,
        defaults: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Ensure query has default values for missing fields.
        
        Args:
            query: Query to validate
            defaults: Dictionary of default values
            
        Returns:
            Query with defaults applied
            
        Example:
            query = self.ensure_query_defaults(query, {
                'max_depth': 2,
                'max_results': 10,
                'min_similarity': 0.5
            })
        """
        # Handle non-dict queries
        if not isinstance(query, dict):
            query = {}
        
        # Apply defaults
        if defaults is not None:
            for key, value in defaults.items():
                if key not in query:
                    query[key] = value
        
        return query
    
    def ensure_nested_dict(
        self,
        query: Dict[str, Any],
        *keys: str,
        default_value: Any = None
    ) -> Dict[str, Any]:
        """
        Ensure nested dictionary keys exist.
        
        Args:
            query: Query dictionary
            *keys: Nested keys to ensure (e.g., 'traversal', 'max_depth')
            default_value: Default value for final key
            
        Returns:
            Query with nested structure ensured
            
        Example:
            # Ensure query['traversal']['max_depth'] exists
            query = self.ensure_nested_dict(
                query,
                'traversal',
                'max_depth',
                default_value=2
            )
        """
        if not isinstance(query, dict):
            return {}
        
        # Navigate/create nested structure
        current = query
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            elif not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]
        
        # Set final key if not present
        if len(keys) > 0:
            final_key = keys[-1]
            if final_key not in current:
                current[final_key] = default_value
        
        return query
    
    # ==================== Result Validation ====================
    
    def validate_result_for_caching(
        self,
        result: Any,
        allow_none: bool = False
    ) -> bool:
        """
        Validate that a result is suitable for caching.
        
        Args:
            result: Result to validate
            allow_none: Whether None is a valid cacheable result
            
        Returns:
            True if result can be cached
            
        Example:
            if self.validate_result_for_caching(result):
                self.add_to_cache(cache_key, result)
        """
        # Check None
        if result is None:
            if not allow_none:
                self._log_validation_warning(
                    "Cannot cache None result"
                )
                return False
            return True
        
        # Try to serialize
        try:
            # Test string representation
            str(result)
            return True
        except Exception as e:
            self._log_validation_warning(
                f"Result cannot be serialized: {str(e)}"
            )
            return False
    
    def sanitize_for_cache(
        self,
        value: Any
    ) -> Any:
        """
        Sanitize a value to make it cache-safe.
        
        Converts numpy arrays and other complex types to basic Python types.
        
        Args:
            value: Value to sanitize
            
        Returns:
            Cache-safe version of value
            
        Example:
            clean_result = self.sanitize_for_cache(result)
            self.add_to_cache(cache_key, clean_result)
        """
        # Handle None
        if value is None:
            return None
        
        # Handle numpy arrays
        if hasattr(value, 'tolist'):
            return value.tolist()
        
        # Handle dictionaries recursively
        if isinstance(value, dict):
            return {k: self.sanitize_for_cache(v) for k, v in value.items()}
        
        # Handle lists/tuples recursively
        if isinstance(value, (list, tuple)):
            return [self.sanitize_for_cache(item) for item in value]
        
        # Return basic types as-is
        return value
    
    # ==================== Utility Methods ====================
    
    def _log_validation_warning(
        self,
        message: str,
        level: str = "warning"
    ) -> None:
        """
        Log a validation warning message.
        
        Args:
            message: Warning message
            level: Log level ('debug', 'info', 'warning', 'error')
        """
        # Try to use the class logger if available
        if hasattr(self, 'logger') and self.logger is not None:
            log_func = getattr(self.logger, level, self.logger.warning)
            log_func(f"[Validation] {message}")
        # Fallback to module logger
        else:
            module_logger = logging.getLogger(self.__class__.__module__)
            log_func = getattr(module_logger, level, module_logger.warning)
            log_func(f"[{self.__class__.__name__}] {message}")
