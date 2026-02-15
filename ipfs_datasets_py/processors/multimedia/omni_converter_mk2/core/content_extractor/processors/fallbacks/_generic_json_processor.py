# TODO Implement generic JSON processor in the style of the others.

"""
Generic Text Processor
supported mime-types: text/plain, text/csv, text/tab-separated-values, text/markdown
"""
import json
from typing import Any


def extract_text(data: str | bytes, options: dict[str, Any]) -> str:
    """
    Extract text from JSON data by converting it to a formatted string.
    
    Args:
        data: The JSON data to extract text from, can be a string or bytes.
        
    Returns:
        Extracted text as a formatted JSON string.
    """
    match data:
        case str():
            # Parse and reformat JSON for consistent output
            try:
                parsed = json.loads(data)
                return json.dumps(parsed, indent=2, ensure_ascii=False)
            except json.JSONDecodeError:
                return data
        case bytes():
            decoded = ""
            try:
                decoded = data.decode('utf-8', errors='ignore')
                parsed = json.loads(decoded)
                return json.dumps(parsed, indent=2, ensure_ascii=False)
            except json.JSONDecodeError:
                return decoded
        case _:
            raise ValueError(f"Unsupported data type for JSON extraction '{type(data)}'. Expected str or bytes.")


def extract_metadata(text: str, options: dict[str, Any]) -> dict[str, Any]:
    """Extract metadata from JSON content.

    This function analyzes JSON data and returns metadata including
    format type, structure information, and size statistics.

    Args:
        text (str): The JSON content to analyze.
        options (dict[str, Any]): Additional options for metadata extraction.

    Returns:
        dict[str, Any]: A dictionary containing metadata with the following keys:
            - 'format' (str): Always 'json' for JSON content
            - 'character_count' (int): Total number of characters in the text
            - 'object_count' (int): Number of objects in the JSON structure
            - 'array_count' (int): Number of arrays in the JSON structure
            - 'is_valid' (bool): Whether the JSON is valid

    Example:
        >>> text = '{"name": "test", "items": [1, 2, 3]}'
        >>> extract_metadata(text, {})
        {
            'format': 'json',
            'character_count': 33,
            'object_count': 1,
            'array_count': 1,
            'is_valid': True
        }
    """
    metadata = {
        'format': 'json',
        'character_count': len(text),
        'object_count': 0,
        'array_count': 0,
        'is_valid': False
    }
    
    try:
        parsed = json.loads(text)
        metadata['is_valid'] = True
        metadata.update(_count_json_structures(parsed))
    except json.JSONDecodeError:
        pass
    
    return metadata


def _count_json_structures(obj: Any) -> dict[str, int]:
    """Count objects and arrays in JSON structure recursively."""
    counts = {'object_count': 0, 'array_count': 0}
    
    if isinstance(obj, dict):
        counts['object_count'] += 1
        for value in obj.values():
            sub_counts = _count_json_structures(value)
            counts['object_count'] += sub_counts['object_count']
            counts['array_count'] += sub_counts['array_count']
    elif isinstance(obj, list):
        counts['array_count'] += 1
        for item in obj:
            sub_counts = _count_json_structures(item)
            counts['object_count'] += sub_counts['object_count']
            counts['array_count'] += sub_counts['array_count']
    
    return counts


def extract_structure(text: str, options: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract structure from JSON data.
    
    Args:
        text: The JSON text to extract structure from.
        
    Returns:
        A list of sections representing the JSON structure.
    """
    try:
        parsed = json.loads(text)
        return _json_to_sections(parsed)
    except json.JSONDecodeError:
        return [{
            'type': 'invalid_json',
            'content': text
        }]


def _json_to_sections(obj: Any, path: str = "") -> list[dict[str, Any]]:
    """Convert JSON object to sections recursively."""
    sections = []
    
    if isinstance(obj, dict):
        sections.append({
            'type': 'json_object',
            'path': path,
            'content': obj,
            'keys': list(obj.keys())
        })
        for key, value in obj.items():
            new_path = f"{path}.{key}" if path else key
            sections.extend(_json_to_sections(value, new_path))
    elif isinstance(obj, list):
        sections.append({
            'type': 'json_array',
            'path': path,
            'content': obj,
            'length': len(obj)
        })
        for i, item in enumerate(obj):
            new_path = f"{path}[{i}]"
            sections.extend(_json_to_sections(item, new_path))
    else:
        sections.append({
            'type': 'json_value',
            'path': path,
            'content': obj,
            'value_type': type(obj).__name__
        })
    
    return sections


def process(
        data: bytes | str, 
        options: dict[str, Any]
        ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """Process a JSON file and extract content.
    
    Args:
        data: The JSON data to process.
        options: Processing options including format information.
            
    Returns:
        Tuple of (formatted JSON text, metadata, sections).
        
    Raises:
        Exception: If an error occurs during processing.
    """
    # Get text content
    if hasattr(data, 'get_as_text'):
        text: str = data.get_as_text()
    else:
        text: str = extract_text(data, options)

    # Extract metadata from JSON
    metadata = extract_metadata(text, options)

    # Extract structure sections
    sections = extract_structure(text, options)
    
    return text, metadata, sections
