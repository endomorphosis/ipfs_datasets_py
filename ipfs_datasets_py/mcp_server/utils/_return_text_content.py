from typing import TypeAlias
from mcp.types import CallToolResult, TextContent


CallToolResultType: TypeAlias = CallToolResult


def return_tool_call_results(content: TextContent, error: bool = False) -> CallToolResult:
    """
    Returns a CallToolResult object for tool call response.

    Args:
        content: The content of the tool call result.
        error: Whether the tool call resulted in an error. Defaults to False.

    Returns:
        CallToolResult: The formatted result object containing the content and error status.
    """
    return CallToolResult(isError=error, content=[content])
