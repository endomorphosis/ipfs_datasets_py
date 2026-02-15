


def normalizer_mock_whitespace(text: str) -> str:
    """Mock normalizer that replaces multiple whitespace characters with a single space.
    
    Args:
        text (str): The input text to normalize.
        
    Returns:
        str: The normalized text with multiple whitespace characters replaced by a single space.
    """
    return ' '.join(text.split())