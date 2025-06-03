from typing import Any


from mcp.types import TextContent, ErrorData


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
