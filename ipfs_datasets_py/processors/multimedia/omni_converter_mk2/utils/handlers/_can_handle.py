import os
from typing import Optional

def can_handle(
        supported_formats: frozenset[str], 
        format_extensions: frozenset[str], 
        file_path: str, 
        format_name: Optional[str] = None
    ) -> bool:
    if format_name:
        return format_name in supported_formats

    # If no format provided, check file extension
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()
    if not ext:
        return False
    ext = ext.lstrip('.')
    if ext in supported_formats:
        return True
    return False
