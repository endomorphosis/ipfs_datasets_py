import re

def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace in text.
    
    Args:
        text: The text to normalize.
        
    Returns:
        The normalized text.
    """
    # Replace tabs with spaces
    text = text.replace("\t", "    ")
    
    # Replace multiple spaces with a single space
    return re.sub(r" {2,}", " ", text)
