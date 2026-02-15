from supported_formats import SupportedFormats


def map_extension_to_format(ext: str) -> str:
    """
    Map a file extension to its corresponding format.
    
    Args:
        ext: The file extension (with or without leading dot)
        
    Returns:
        The format name for the given extension
    """

    # Clean the extension by removing any leading dot and converting to lowercase
    clean_ext = ext.strip('.').lower().strip() 

    SupportedFormats.FORMAT_EXTENSIONS
    if clean_ext in SupportedFormats.FORMAT_EXTENSIONS:
        return SupportedFormats.FORMAT_EXTENSIONS[clean_ext]

