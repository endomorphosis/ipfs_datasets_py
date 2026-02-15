"""
XML processing utilities.

This module contains functions for processing XML content.
In a future implementation, this could use lxml or another XML parsing library.
"""
import re
from typing import Any, Optional
import xml.etree.ElementTree as ET


from logger import logger


def extract_metadata(
    data: bytes | str,
    options: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """
    Extract metadata from XML content.
    
    Args:
        data: The XML content as text.
        options: Optional extraction options.
        
    Returns:
        Dictionary of metadata.
    """
    try:
        root = ET.fromstring(data)
        
        # Basic metadata
        metadata = {
            'root_element': root.tag,
            'format': 'xml'
        }
        
        # Count child elements
        metadata['child_count'] = len(root)
        
        # Get namespace info if available
        nsmap = {}
        for match in re.finditer(r'xmlns:(\w+)=["\'](.*?)["\']', data):
            prefix, uri = match.groups()
            nsmap[prefix] = uri
        
        if nsmap:
            metadata['namespaces'] = nsmap
        
        return metadata
    
    except ET.ParseError as e:
        logger.warning(f"XML parsing failed: {e}")
        return {
            'format': 'xml',
            'parse_error': str(e)
        }


def extract_text(element: ET.Element) -> str:
    """
    Extract text from XML element and its children.
    
    Args:
        element: The XML element to process.
        
    Returns:
        Extracted text.
    """
    text = element.text or ""
    for child in element:
        text += f" {extract_text(child)}"
    if element.tail:
        text += f" {element.tail}"
    return text


def extract_structure(
    data: bytes | str,
    options: Optional[dict[str, Any]] = None
) -> list[dict[str, Any]]:
    """
    Create sections from XML content.
    
    Args:
        data: The XML content as text.
        options: Optional extraction options.
        
    Returns:
        list of sections.
    """
    try:
        root = ET.fromstring(data)
        sections = []
        
        # Create a section for each top-level element
        for child in root:
            child_text = extract_text(child)
            sections.append({
                'type': child.tag,
                'content': child_text.strip()
            })
        
        return sections
    
    except ET.ParseError:
        logger.warning("XML parsing failed, returning empty sections")
        return []


def process_xml(
    data: bytes | str,
    options: dict[str, Any]
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """
    Process XML content.

    Args:
        data: The file content to process.
        options: Processing options.
        
    Returns:
        tuple of (text content, metadata, sections).
    """
    # Get XML content as text
    if hasattr(data, 'get_as_text'):
        data = data.get_as_text()
    else:
        data = data

    try:
        # Parse XML
        root = ET.fromstring(data)
        
        # Extract metadata
        metadata = extract_metadata(data, options)
        
        # Extract text
        text = extract_text(root)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Create sections
        sections = extract_structure(data, options)
        
        return text, metadata, sections
    
    except ET.ParseError as e: # TODO This should be moved outside the processor. All exceptions should be handled by the handler.
        logger.warning(f"XML parsing failed, falling back to plain text: {e}")

        # Fallback to plain text
        metadata = {
            'format': 'xml',
            'parse_error': str(e)
        }

        sections = [{
            'type': 'text',
            'content': data
        }]

        return data, metadata, sections