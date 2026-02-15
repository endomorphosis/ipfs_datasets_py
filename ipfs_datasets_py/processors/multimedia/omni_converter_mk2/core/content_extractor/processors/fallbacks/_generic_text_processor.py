"""
Generic Text Processor
supported mime-types: text/plain, text/csv, text/tab-separated-values, text/markdown
"""
from typing import Any


def extract_text(data: str | bytes, options: dict[str, Any]) -> str:
    """
    Extract text from the provided data.
    
    Args:
        data: The data to extract text from, can be a string or bytes.
        
    Returns:
        Extracted text as a string.
    """
    match data:
        case str():
            return data
        case bytes():
            return data.decode('utf-8', errors='ignore')
        case _:
            raise ValueError(f"Unsupported data type for text extraction '{type(data)}'. Expected str or bytes.")


def extract_metadata(text: str, options: dict[str, Any]) -> dict[str, Any]:
    """Extract metadata from plain text content.

    This function analyzes plain text and returns basic metadata including
    format type, line count, character count, and word count statistics.

    Args:
        text (str): The plain text content to analyze.
        options (dict[str, Any]): Additional options for metadata extraction.
                                 Currently unused for plain text processing.

    Returns:
        dict[str, Any]: A dictionary containing metadata with the following keys:
            - 'format' (str): Always 'plain' for plain text content
            - 'line_count' (int): Number of lines in the text (newlines + 1)
            - 'character_count' (int): Total number of characters in the text
            - 'word_count' (int): Number of words (split by whitespace)

    Example:
        >>> text = "Hello world\nThis is a test"
        >>> extract_metadata(text, {})
        {
            'format': 'plain',
            'line_count': 2,
            'character_count': 23,
            'word_count': 5
        }
    """
    # Plain text is already in the desired format
    return {
        'format': 'plain',
        'line_count': text.count('\n') + 1,
        'character_count': len(text),
        'word_count': len(text.split())
    }


def extract_structure(text: str, options: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract sections from the text.
    
    Args:
        text: The text to extract sections from.
        
    Returns:
        A list of sections, each represented as a dictionary.
    """
    # For plain text, we can treat the entire text as a single section
    return [{
        'type': 'text',
        'content': text
    }]


def process(
        data: bytes | str, 
        options: dict[str, Any]
        ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """Process a plaintext file and extract content.
    
    Args:
        file_content: The file content to process (text).
        options: Processing options including format information.
            Must contain:
            - file_path: Path to the text file
            
    Returns:
        Tuple of (text content, metadata, sections).
    """
    # Get text content
    if hasattr(data, 'get_as_text'):
        text: str = data.get_as_text()

    text = extract_text(text, options)

    # Plain text is already in the desired format
    metadata = extract_metadata(text, options)

    # Create a single section
    sections = extract_structure(text, options)
    
    return text, metadata, sections
