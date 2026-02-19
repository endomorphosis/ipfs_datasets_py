"""
Enhanced Tool wrapper system for converting functions to MCP tools.

This module provides utilities to wrap standalone functions as MCP tools,
enabling easy integration of migrated functionality.
Enhanced with production features including monitoring, validation, and caching.
"""

import anyio
import inspect
import logging
import time
from typing import Dict, Any, Callable, Optional, Union, get_type_hints
from datetime import datetime
from abc import ABC, abstractmethod
from functools import wraps

# Import our enhanced components
from ..validators import validator, ValidationError
from ..monitoring import metrics_collector

logger = logging.getLogger(__name__)


class EnhancedBaseMCPTool(ABC):
    """
    Enhanced base class for MCP Tools with production features.
    Includes monitoring, caching, validation, and error handling.
    """
    
    def __init__(self):
        self.name: str = ""
        self.description: str = ""
        self.input_schema: Dict[str, Any] = {}
        self.category: str = "general"
        self.tags: list = []
        self.version: str = "1.0.0"
        self.created_at = datetime.utcnow()
        self.last_used = None
        self.usage_count = 0
        self.error_count = 0
        self.total_execution_time_ms = 0.0
        self.cache_enabled = False
        self.cache: Dict[str, Any] = {}
        self.cache_ttl_seconds = 300  # 5 minutes default
    
    @abstractmethod
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the tool with given parameters."""
        pass
    
    def get_schema(self) -> Dict[str, Any]:
        """Get the complete tool schema."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "category": self.category,
            "tags": self.tags,
            "version": self.version
        }
    
    def _generate_cache_key(self, parameters: Dict[str, Any]) -> str:
        """Generate cache key from parameters."""
        import hashlib
        import json
        param_str = json.dumps(parameters, sort_keys=True)
        return hashlib.md5(param_str.encode()).hexdigest()
    
    def _is_cache_valid(self, cache_entry: Dict[str, Any]) -> bool:
        """Check if cache entry is still valid."""
        if not cache_entry:
            return False
        
        cache_time = cache_entry.get('timestamp')
        if not cache_time:
            return False
        
        age_seconds = (datetime.utcnow() - cache_time).total_seconds()
        return age_seconds < self.cache_ttl_seconds
    
    async def validate_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate input parameters using enhanced validator."""
        try:
            # Basic schema validation if available
            if hasattr(self, 'input_schema') and self.input_schema:
                # # TODO add basic JSON schema validation here
                pass 
            
            # Custom validation can be implemented by subclasses
            return parameters
            
        except Exception as e:
            logger.error(f"Parameter validation failed for {self.name}: {e}")
            raise ValidationError("parameters", f"Parameter validation failed: {e}")
    
    async def call(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced call method with monitoring, caching, and validation."""
        start_time = time.time()
        success = False
        result = None
        
        try:
            # Update usage tracking
            self.usage_count += 1
            self.last_used = datetime.utcnow()
            
            # Validate parameters
            validated_params = await self.validate_parameters(parameters)
            
            # Check cache if enabled
            cache_key = None
            if self.cache_enabled:
                cache_key = self._generate_cache_key(validated_params)
                if cache_key in self.cache:
                    cache_entry = self.cache[cache_key]
                    if self._is_cache_valid(cache_entry):
                        logger.debug(f"Cache hit for {self.name}")
                        metrics_collector.increment_counter('tool_cache_hits', labels={'tool': self.name})
                        return cache_entry['result']
                    else:
                        # Remove stale cache entry
                        del self.cache[cache_key]
            
            # Execute the tool with monitoring
            async with metrics_collector.track_request(f"tool_{self.name}"):
                result = await self.execute(validated_params)
            
            # Cache result if enabled
            if self.cache_enabled and cache_key:
                self.cache[cache_key] = {
                    'result': result,
                    'timestamp': datetime.utcnow()
                }
                # Limit cache size
                if len(self.cache) > 100:
                    oldest_key = min(self.cache.keys(), 
                                   key=lambda k: self.cache[k]['timestamp'])
                    del self.cache[oldest_key]
            
            success = True
            return result
            
        except Exception as e:
            self.error_count += 1
            logger.error(f"Error executing tool {self.name}: {e}")
            raise
            
        finally:
            # Track execution metrics
            execution_time_ms = (time.time() - start_time) * 1000
            self.total_execution_time_ms += execution_time_ms
            
            metrics_collector.track_tool_execution(
                tool_name=self.name,
                execution_time_ms=execution_time_ms,
                success=success
            )
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics for this tool."""
        avg_execution_time = (
            self.total_execution_time_ms / self.usage_count 
            if self.usage_count > 0 else 0
        )
        
        success_rate = (
            (self.usage_count - self.error_count) / self.usage_count 
            if self.usage_count > 0 else 0
        )
        
        return {
            'usage_count': self.usage_count,
            'error_count': self.error_count,
            'success_rate': success_rate,
            'avg_execution_time_ms': avg_execution_time,
            'total_execution_time_ms': self.total_execution_time_ms,
            'last_used': self.last_used,
            'cache_enabled': self.cache_enabled,
            'cache_size': len(self.cache) if self.cache_enabled else 0
        }
    
    def enable_caching(self, ttl_seconds: int = 300):
        """Enable caching for this tool."""
        self.cache_enabled = True
        self.cache_ttl_seconds = ttl_seconds
        logger.info(f"Caching enabled for {self.name} with TTL {ttl_seconds}s")
    
    def disable_caching(self):
        """Disable caching for this tool."""
        self.cache_enabled = False
        self.cache.clear()
        logger.info(f"Caching disabled for {self.name}")
    
    def clear_cache(self):
        """Clear the tool's cache."""
        self.cache.clear()
        logger.info(f"Cache cleared for {self.name}")

# Backward compatibility alias
BaseMCPTool = EnhancedBaseMCPTool


class FunctionToolWrapper(BaseMCPTool):
    """
    Wrapper to convert a standalone function into an MCP tool.
    
    This class takes any function (sync or async) and wraps it to be
    compatible with our MCP tool system.
    """
    
    def __init__(self, 
                 function: Callable,
                 tool_name: str,
                 category: str = "general",
                 description: Optional[str] = None,
                 tags: Optional[list] = None):
        super().__init__()
        
        self.function = function
        self.name = tool_name
        self.category = category
        self.description = description or function.__doc__ or f"Execute {tool_name}"
        self.tags = tags or []
        
        # Extract input schema from function signature
        self.input_schema = self._extract_input_schema()
        
    def _extract_input_schema(self) -> Dict[str, Any]:
        """
        Extract input schema from function signature and type hints.
        """
        try:
            sig = inspect.signature(self.function)
            type_hints = get_type_hints(self.function)
            properties = {}
            required = []
            
            for param_name, param in sig.parameters.items():
                # Get type from hints or annotation
                param_type = type_hints.get(param_name, param.annotation)
                
                param_info = {
                    "type": self._python_type_to_json_type(param_type),
                    "description": f"Parameter {param_name}"
                }
                
                # Check if parameter has a default value
                if param.default == inspect.Parameter.empty:
                    required.append(param_name)
                else:
                    param_info["default"] = param.default
                
                properties[param_name] = param_info
            
            schema = {
                "type": "object",
                "properties": properties
            }
            
            if required:
                schema["required"] = required
                
            return schema
            
        except Exception as e:
            logger.warning(f"Could not extract schema for {self.name}: {e}")
            return {"type": "object", "properties": {}}
    
    def _python_type_to_json_type(self, python_type) -> str:
        """
        Convert Python type annotations to JSON schema types.
        """
        if python_type == inspect.Parameter.empty:
            return "string"  # Default type
        
        # Handle basic types
        type_mapping = {
            str: "string",
            int: "integer", 
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
            type(None): "null"
        }
        
        # Check direct mapping first
        if python_type in type_mapping:
            return type_mapping[python_type]
        
        # Handle typing module types (Optional, Union, List, Dict, etc.)
        if hasattr(python_type, '__origin__'):
            origin = python_type.__origin__
            
            if origin is list or origin is list:
                return "array"
            elif origin is dict or origin is dict:
                return "object"
            elif origin is Union:
                # For Union types (like Optional), return the first non-None type
                args = getattr(python_type, '__args__', ())
                for arg_type in args:
                    if arg_type is not type(None):
                        return self._python_type_to_json_type(arg_type)
                return "string"  # fallback
        
        # Handle string representations
        if isinstance(python_type, str):
            if python_type.lower() in ['str', 'string']:
                return "string"
            elif python_type.lower() in ['int', 'integer']:
                return "integer"
            elif python_type.lower() in ['float', 'number']:
                return "number"
            elif python_type.lower() in ['bool', 'boolean']:
                return "boolean"
            elif python_type.lower() in ['list', 'array']:
                return "array"
            elif python_type.lower() in ['dict', 'object']:
                return "object"
        
        return "string"  # Default fallback
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the wrapped function with the given parameters.
        """
        try:
            # Call the function with parameters
            if inspect.iscoroutinefunction(self.function):
                result = await self.function(**parameters)
            else:
                result = self.function(**parameters)
            
            # Ensure result is a dictionary
            if not isinstance(result, dict):
                result = {"result": result}
            
            # Add execution metadata
            result.update({
                "tool_name": self.name,
                "executed_at": datetime.utcnow().isoformat(),
                "success": result.get("success", True)
            })
            
            return result
            
        except Exception as e:
            error_msg = f"Error executing {self.name}: {e}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": str(e),
                "tool_name": self.name,
                "executed_at": datetime.utcnow().isoformat()
            }


def wrap_function_as_tool(*args, **kwargs):
    """
    Wrap functions as MCP tools with dual usage styles.

    Supports two patterns:
    1) Helper style (existing behavior):
       wrap_function_as_tool(function, tool_name, category="general", description=None, tags=None)
       -> returns FunctionToolWrapper

    2) Decorator style (new, for convenience):
       @wrap_function_as_tool(name="tool_name", category="general", description=None, tags=None)
       async def my_tool(...):
           ...
       -> returns the original function with metadata attributes set
    """
    if args and callable(args[0]):
        function: Callable = args[0]
        tool_name: str = args[1] if len(args) > 1 else function.__name__
        category: str = args[2] if len(args) > 2 else kwargs.get("category", "general")
        description: Optional[str] = kwargs.get("description")
        tags: Optional[list] = kwargs.get("tags")

        return FunctionToolWrapper(
            function=function,
            tool_name=tool_name,
            category=category,
            description=description,
            tags=tags
        )

    # Decorator usage
    name: Optional[str] = kwargs.get("name") or (args[0] if args else None)
    category: str = kwargs.get("category", "general")
    description: Optional[str] = kwargs.get("description")
    tags: Optional[list] = kwargs.get("tags")

    def decorator(function: Callable):
        try:
            setattr(function, "__mcp_tool_name__", name or function.__name__)
            setattr(function, "__mcp_tool_category__", category)
            if description:
                setattr(function, "__mcp_tool_description__", description)
            if tags:
                setattr(function, "__mcp_tool_tags__", tags)
        except AttributeError:
            pass


def wrap_function_with_metadata(function: Callable, 
                               metadata: Dict[str, Any]) -> FunctionToolWrapper:
    """
    Wrap a function using metadata dictionary.
    
    Args:
        function: The function to wrap
        metadata: Metadata dictionary with tool information
    
    Returns:
        FunctionToolWrapper instance
    
    Example:
        ```python
        metadata = {
            "name": "process_embeddings",
            "category": "embedding",
            "description": "Process embeddings for storage",
            "tags": ["embedding", "processing"]
        }
        
        tool = wrap_function_with_metadata(process_embeddings_func, metadata)
        ```
    """
    return FunctionToolWrapper(
        function=function,
        tool_name=metadata.get("name", function.__name__),
        category=metadata.get("category", "general"),
        description=metadata.get("description", function.__doc__),
        tags=metadata.get("tags", [])
    )


# Convenience function for bulk wrapping
def wrap_tools_from_module(module, tool_mappings: Dict[str, Dict[str, Any]]) -> Dict[str, FunctionToolWrapper]:
    """
    Wrap multiple functions from a module using tool mappings.
    
    Args:
        module: The module containing functions to wrap
        tool_mappings: Dictionary mapping function names to tool metadata
    
    Returns:
        Dictionary of wrapped tools
    
    Example:
        ```python
        from ipfs_datasets_py.mcp_server.tools.auth_tools import auth_tools
        
        mappings = {
            "authenticate_user": {
                "name": "authenticate_user",
                "category": "auth",
                "description": "Authenticate a user",
                "tags": ["auth", "security"]
            },
            "validate_token": {
                "name": "validate_token", 
                "category": "auth",
                "description": "Validate JWT token",
                "tags": ["auth", "validation"]
            }
        }
        
        tools = wrap_tools_from_module(auth_tools, mappings)
        ```
    """
    wrapped_tools = {}
    
    for func_name, metadata in tool_mappings.items():
        if hasattr(module, func_name):
            function = getattr(module, func_name)
            if callable(function):
                wrapped_tools[metadata["name"]] = wrap_function_with_metadata(function, metadata)
            else:
                logger.warning(f"Attribute {func_name} in module {module.__name__} is not callable")
        else:
            logger.warning(f"Function {func_name} not found in module {module.__name__}")
    
    return wrapped_tools
