def normalize_line_endings(text: str) -> str:
    """Normalize line endings in text.
    
    Args:
        text: The text to normalize.
        
    Returns:
        The normalized text.
    """
    # Replace all types of line endings with Unix-style line endings
    return text.replace("\r\n", "\n").replace("\r", "\n")
