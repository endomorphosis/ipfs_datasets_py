from typing import TypeAlias, Any
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


def return_text_content(input: Any, result_str: str) -> TextContent:
    """
    Return a TextContent object with formatted string.

    Args:
        string (str): The input string to be included in the content.
        result_str (str): A string identifier or label to prefix the input string.

    Returns:
        TextContent: A TextContent object with 'text' type and formatted text.
    """
    return TextContent(type="text", text=f"{result_str}: {repr(input)}") # NOTE we use repr to ensure special characters are handled correctly
