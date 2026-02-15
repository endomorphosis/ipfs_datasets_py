import re

def normalize_unicode(text: str) -> str:
    """Normalize Unicode characters in text.
    
    Args:
        text: The text to normalize.
        
    Returns:
        The normalized text.
    """
    # Replace non-breaking spaces with regular spaces
    text = text.replace("\u00A0", " ")

    # Normalize various Unicode characters to their ASCII equivalents
    unicode_replacements = [
        # Dash characters
        (r"[\u2010-\u2015]", "-"),     # Hyphen, non-breaking hyphen, figure dash, en dash, em dash, horizontal bar
        (r"[\u2212]", "-"),            # Minus sign
        # Quote characters
        (r"[\u2018\u2019]", "'"),      # Left and right single quotation marks
        (r"[\u201A\u201B]", "'"),      # Single low-9 quotation mark, single high-reversed-9 quotation mark
        (r"[\u201C\u201D]", '"'),      # Left and right double quotation marks
        (r"[\u201E\u201F]", '"'),      # Double low-9 quotation mark, double high-reversed-9 quotation mark
        (r"[\u2039\u203A]", "'"),      # Single left and right-pointing angle quotation marks
        (r"[\u00AB\u00BB]", '"'),      # Left and right-pointing double angle quotation marks
        # Apostrophe variants
        (r"[\u02BC\u2032]", "'"),      # Modifier letter apostrophe, prime
        # Space characters
        (r"[\u2000-\u200A]", " "),     # Various space characters (en quad, em quad, thin space, etc.)
        (r"[\u202F\u205F]", " "),      # Narrow no-break space, medium mathematical space
        # Ellipsis
        (r"\u2026", "..."),            # Horizontal ellipsis
        # Bullet points
        (r"[\u2022\u2023\u2043]", "*"), # Bullet, triangular bullet, hyphen bullet
        # Mathematical symbols
        (r"\u00D7", "x"),              # Multiplication sign
        (r"\u00F7", "/"),              # Division sign
        # Currency symbols (convert to text representations)
        (r"\u00A3", "GBP "),           # Pound sign
        (r"\u00A5", "JPY "),           # Yen sign
        (r"\u20AC", "EUR "),           # Euro sign
    ]
    
    for pattern, repl in unicode_replacements:
        text = re.sub(pattern, repl, text)
    return text
