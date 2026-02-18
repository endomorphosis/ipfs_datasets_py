"""
Simple Tool Template - Pattern 1 (RECOMMENDED)

Use this template for 90% of tools. It demonstrates:
- Thin wrapper pattern (<100 lines)
- Core module delegation
- Proper error handling
- Type hints
- MCP decorator integration

Core Principle: All business logic lives in core modules.
"""
from typing import Dict, Any, Optional
import logging

# Import from core modules (business logic layer)
from ipfs_datasets_py.your_core_module import YourCoreClass

# MCP integration helpers
from ipfs_datasets_py.mcp_server.tools.mcp_helpers import (
    wrap_function_as_tool,
    mcp_error_response,
)

logger = logging.getLogger(__name__)


@wrap_function_as_tool(
    name="your_tool_name",
    description="Clear, concise description of what this tool does",
    category="your_category",  # e.g., "dataset", "search", "graph"
)
async def your_tool_name(
    required_param: str,
    optional_param: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Tool description with detailed documentation.
    
    This is a thin wrapper around YourCoreClass from core modules.
    
    Args:
        required_param: Description of required parameter
        optional_param: Description of optional parameter
        options: Additional options dictionary
        
    Returns:
        Dict containing:
            - status: "success" or "error"
            - result: The actual result data
            - message: Optional message
            
    Example:
        >>> result = await your_tool_name("value", optional_param="optional")
        >>> print(result["status"])
        success
    """
    try:
        # 1. Input validation (if needed beyond type hints)
        if not required_param:
            return mcp_error_response(
                "required_param cannot be empty",
                error_type="validation"
            )
        
        # 2. Initialize core module class/function
        core_instance = YourCoreClass()
        
        # 3. Delegate to core module (THIS IS WHERE THE WORK HAPPENS)
        result = await core_instance.your_method(
            required_param,
            optional_param=optional_param,
            **(options or {})
        )
        
        # 4. Format response
        return {
            "status": "success",
            "result": result,
            "message": "Operation completed successfully"
        }
        
    except ValueError as e:
        # Handle specific exceptions
        logger.warning(f"Validation error in your_tool_name: {e}")
        return mcp_error_response(str(e), error_type="validation")
        
    except Exception as e:
        # Handle general exceptions
        logger.error(f"Error in your_tool_name: {e}", exc_info=True)
        return mcp_error_response(
            f"Failed to execute tool: {str(e)}",
            error_type="execution"
        )


# CLI Integration (optional, for CLI-MCP alignment)
# This allows the same core logic to be used from CLI
async def cli_your_tool_name(args):
    """
    CLI wrapper that calls the same MCP tool function.
    Demonstrates CLI-MCP alignment.
    """
    return await your_tool_name(
        required_param=args.required_param,
        optional_param=args.optional_param,
        options=vars(args)
    )


# Module exports
__all__ = ["your_tool_name"]
