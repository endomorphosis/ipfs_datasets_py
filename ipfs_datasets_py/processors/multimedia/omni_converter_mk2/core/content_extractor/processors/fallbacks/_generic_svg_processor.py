"""
SVG processing utilities.

This module contains functions for processing SVG files which are text-based XML files.
No special dependencies are required since SVG is a text format, but we isolate it
for consistency with other image processors.
"""

import os
import re
from typing import Any, Optional, Union

from logger import logger
from utils.filesystem import FileSystem


def extract_metadata(
    data: str,
    options: dict
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Extract metadata from SVG text.
    
    Args:
        data: The SVG file content as text.
        file_path: The path to the SVG file.
        
    Returns:
        A tuple of (metadata, sections).
    """
    # Try to extract dimensions
    width = height = "Unknown"
    width_match = re.search(r'width="([^"]*)"', data) # TODO All regex should be moved to constants.py file.
    if width_match:
        width = width_match.group(1)
    
    height_match = re.search(r'height="([^"]*)"', data)
    if height_match:
        height = height_match.group(1)
    
    # Extract text content from SVG tags that might contain text
    text_elements = re.findall(r'<text[^>]*>(.*?)</text>', data, re.DOTALL)
    title_elements = re.findall(r'<title[^>]*>(.*?)</title>', data, re.DOTALL)
    desc_elements = re.findall(r'<desc[^>]*>(.*?)</desc>', data, re.DOTALL)
    
    # Create metadata
    metadata = {
        'format': 'svg',
        'width': width,
        'height': height,
        'title': title_elements[0] if title_elements else None,
        'description': desc_elements[0] if desc_elements else None
    }
    
    # Create sections
    sections = [
        {
            'type': 'image_info',
            'content': f"SVG Image: {width}x{height}"
        }
    ]
    
    if title_elements or desc_elements:
        sections.append({
            'type': 'metadata',
            'content': {
                'title': title_elements[0] if title_elements else None,
                'description': desc_elements[0] if desc_elements else None
            }
        })
    
    if text_elements:
        sections.append({
            'type': 'text_content',
            'content': text_elements
        })
    
    return metadata, sections


def extract_text(
    file_path: str,
    metadata: dict[str, Any],
    text_elements: list[str]
) -> list[str]:
    """
    Generate a human-readable description of an SVG file.
    
    Args:
        file_path: The path to the SVG file.
        metadata: The metadata dictionary.
        text_elements: Text elements extracted from the SVG.
        
    Returns:
        A list of text lines describing the SVG.
    """
    text_content = [f"SVG Image: {os.path.basename(file_path)}"]
    
    # Add dimensions
    width = metadata.get('width', 'Unknown')
    height = metadata.get('height', 'Unknown')
    text_content.append(f"Dimensions: {width}x{height}")
    
    # Add title and description if available
    title = metadata.get('title')
    if title:
        text_content.append(f"Title: {title}")
    
    description = metadata.get('description')
    if description:
        text_content.append(f"Description: {description}")
    
    # Add text elements
    if text_elements:
        text_content.append("\nText content:")
        for text in text_elements:
            text_content.append(text.strip())
    
    return text_content


def extract_structure(data: bytes | str, options: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract sections from the svg.
    
    Args:
        data: The data to extract sections from.
        options: Processing options.

    Returns:
        A list of sections, each represented as a dictionary.
    """
    # Convert bytes to string if needed
    svg_content = data.decode('utf-8') if isinstance(data, bytes) else data
    
    sections = []
    
    # Extract SVG root attributes for basic info
    width = height = "Unknown"
    width_match = re.search(r'width="([^"]*)"', svg_content)
    if width_match:
        width = width_match.group(1)
    
    height_match = re.search(r'height="([^"]*)"', svg_content)
    if height_match:
        height = height_match.group(1)
    
    # Add basic image info section
    sections.append({
        'type': 'image_info',
        'content': f"SVG Image: {width}x{height}",
        'metadata': {
            'width': width,
            'height': height,
            'format': 'svg'
        }
    })
    
    # Extract title and description elements
    title_elements = re.findall(r'<title[^>]*>(.*?)</title>', svg_content, re.DOTALL)
    desc_elements = re.findall(r'<desc[^>]*>(.*?)</desc>', svg_content, re.DOTALL)
    
    if title_elements or desc_elements:
        sections.append({
            'type': 'metadata',
            'content': {
                'title': title_elements[0].strip() if title_elements else None,
                'description': desc_elements[0].strip() if desc_elements else None
            }
        })
    
    # Extract text content from text elements
    text_elements = re.findall(r'<text[^>]*>(.*?)</text>', svg_content, re.DOTALL)
    if text_elements:
        sections.append({
            'type': 'text_content',
            'content': [text.strip() for text in text_elements if text.strip()]
        })
    
    return sections


def process(
    data: str | bytes,
    options: dict[str, Any]
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """
    Process an SVG file and extract content.
    
    Args:
        data: The file content to process.
        options: Processing options including format information.
        
    Returns:
        Tuple of (text content, metadata, sections).
        
    Raises:
        ValueError: If the file is not valid SVG.
        Exception: If an error occurs during processing.
    """
    # Get key information from the options
    file_path = options.get("file_path", "")
    
    if not file_path:
        raise ValueError("File path is required for SVG processing")

    # Get SVG text
    data = data.get_as_text() if hasattr(data, 'get_as_text') else data
    
    # Extract text elements from SVG tags that might contain text
    text_elements = re.findall(r'<text[^>]*>(.*?)</text>', data, re.DOTALL) # TODO Regex should be moved to constants.py.
    
    # Extract metadata and sections
    metadata, sections = extract_metadata(data, file_path)
    
    # Generate text description
    text_content = extract_text(file_path, metadata, text_elements)
    
    return "\n".join(text_content), metadata, sections
