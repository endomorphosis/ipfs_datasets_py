
def normalizer_mock_newlines(text: str) -> str:
    """Mock normalizer that replaces multiple newlines with a single newline.
    
    Args:
        text (str): The input text to normalize.
        
    Returns:
        str: The normalized text with multiple newlines replaced by a single newline.
    """
    return '\n'.join(line.strip() for line in text.splitlines() if line.strip())
