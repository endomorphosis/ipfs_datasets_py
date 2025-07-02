
from ipfs_datasets_py.mcp_tools.tool_registry import ClaudeMCPTool

def wrap_function_as_tool() -> ClaudeMCPTool:
    """

    Example:
        >>> from .tools import create_vector_store_tool
        ... wrap_function_as_tool(create_vector_store_tool, "create_vector_store", "storage")
    """