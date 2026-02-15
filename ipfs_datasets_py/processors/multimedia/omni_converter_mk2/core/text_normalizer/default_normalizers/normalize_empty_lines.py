import re

def normalize_empty_lines(text: str) -> str:
    """Normalize empty lines in text.
    
    Args:
        text: The text to normalize.
        
    Returns:
        The normalized text.
    """
    # Replace three or more consecutive newlines with two newlines
    return re.sub(r"\n{3,}", "\n\n", text)
