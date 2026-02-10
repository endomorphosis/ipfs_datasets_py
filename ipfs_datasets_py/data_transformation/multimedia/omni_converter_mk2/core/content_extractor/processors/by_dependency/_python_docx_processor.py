"""
DOCX processor implementation using python-docx.

This module provides a concrete implementation of DocumentProcessor for DOCX files
using the python-docx library.
"""
from datetime import datetime
import io
from typing import Any, TypeVar


from dependencies import dependencies


Document = TypeVar('Document')


def _set_metadata(props: object, metadata: dict[str, Any]) -> None:
    list_of_attr = [attr for attr in dir(props)]
    for key in metadata.keys():
        if key in list_of_attr:
            value = getattr(props, key)
            match value:
                case datetime():
                    metadata[key] = value.isoformat()
                case str():
                    metadata[key] = value
                case _: # Stringify all other types
                    metadata[key] = str(value)


def _open_docx_file(data: bytes) -> Document:
    """
    Open a DOCX file from binary data.

    Args:
        data: The binary data of the DOCX document.

    Returns:
        A file-like object for the DOCX document.

    Raises:
        ValueError: If python-docx is not available or the data cannot be processed as a DOCX.
    """
    # Create a file-like object from the bytes
    docx_file = io.BytesIO(data)

    # Open the DOCX file
    doc = dependencies.docx.Document(docx_file)

    return doc


def extract_text(data: bytes, options: dict[str, Any]) -> str:
    """
    Extract plain text from a DOCX document.
    
    Args:
        data: The binary data of the DOCX document.
        options: Processing options.
            
    Returns:
        Extracted text from the DOCX document.
        
    Raises:
        ValueError: If python-docx is not available or the data cannot be processed as a DOCX.
    """
    doc = _open_docx_file(data)

    # Extract text from each paragraph
    paragraphs = []
    
    for para in doc.paragraphs:
        # Skip empty paragraphs
        if para.text.strip():
            paragraphs.append(para.text)
    
    # Extract text from tables if requested
    include_tables = options.get('include_tables', True)
    if include_tables:
        for table in doc.tables:
            for row in table.rows:
                cells = []
                for cell in row.cells:
                    # Get text from each cell
                    if cell.text.strip():
                        cells.append(cell.text.strip())
                
                if cells:
                    paragraphs.append(" | ".join(cells))

    # Join all paragraphs
    return "\n\n".join(paragraphs)


def extract_metadata(data: bytes, options: dict[str, Any]) -> dict[str, Any]:
    """
    Extract metadata from a DOCX document.
    
    Args:
        data: The binary data of the DOCX document.
        options: Processing options.
        
    Returns:
        Metadata extracted from the DOCX document.
        
    Raises:
        ValueError: If python-docx is not available or the data cannot be processed as a DOCX.
    """
    doc = _open_docx_file(data)
    
    # Extract document info
    metadata = {
        "title": None,
        "author": None,
        "subject": None,
        "keywords": None,
        "category": None,
        "comments": None,
        "creation_date": None,
        "modification_date": None,
        "last_modified_by": None,
        "revision": None,
        "language": None,
        "file_size_bytes": len(data),
        "paragraph_count": len(doc.paragraphs),
        "table_count": len(doc.tables),
        "section_count": len(doc.sections)
    }

    # Extract core properties if available
    if hasattr(doc, "core_properties"):
        _set_metadata(doc.core_properties, metadata)

    # Extract document statistics
    stats = {
        "character_count": 0,
        "word_count": 0,
        "paragraph_count": len(doc.paragraphs)
    }
    
    # Calculate character and word counts
    for para in doc.paragraphs:
        if para.text:
            stats["character_count"] += len(para.text)
            stats["word_count"] += len(para.text.split())
    
    metadata["statistics"] = stats

    return metadata


def extract_structure(data: bytes, options: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract structural elements from a DOCX document.
    
    Args:
        data: The binary data of the DOCX document.
        options: Processing options.
        
    Returns:
        A list of structural elements extracted from the DOCX document.
        
    Raises:
        ValueError: If python-docx is not available or the data cannot be processed as a DOCX.
    """
    doc = _open_docx_file(data)

    # Extract structure
    structure = []
    
    # Add document as a section
    structure.append({
        "type": "document",
        "content": "DOCX Document"
    })
    
    # Extract headings and content
    current_heading = None
    heading_content = []
    
    for para in doc.paragraphs:
        # Check if this paragraph is a heading
        if para.style.name.startswith('Heading'):
            # If we had a previous heading, add it to the structure
            if current_heading and heading_content:
                structure.append({
                    "type": "section",
                    "heading": current_heading,
                    "level": int(current_heading.split(':')[0].replace('Heading', '')) if current_heading[0].isdigit() else 1,
                    "content": "\n".join(heading_content)
                })
            
            # Start a new heading
            current_heading = para.style.name + ": " + para.text
            heading_content = []
        elif para.text.strip():
            # Add content to the current heading, or to a default section if no heading yet
            if not current_heading:
                current_heading = "Document"
            heading_content.append(para.text)
    
    # Add the last heading if there was one
    if current_heading and heading_content:
        structure.append({
            "type": "section",
            "heading": current_heading,
            "content": "\n".join(heading_content)
        })
    
    # Extract tables
    for idx, table in enumerate(doc.tables):
        table_data = []
        for row in table.rows:
            table_data.append([cell.text for cell in row.cells])
        
        structure.append({
            "type": "table",
            "table_number": idx + 1,
            "rows": len(table.rows),
            "columns": len(table.rows[0].cells) if table.rows else 0,
            "content": table_data
        })
    
    images_data: list[dict[str, Any]] = extract_images(data, options)
    image_count = len(images_data)
    
    # Add image information for OCR processing later in pipeline
    for idx, image_info in enumerate(images_data):
        structure.append({
            "type": "image",
            "image_number": idx + 1,
            "content_type": image_info.get("content_type", "unknown"),
            "target": image_info.get("target", ""),
            "image_data": image_info.get("image_data"),  # Binary data for OCR processor
            "content": f"Image {idx + 1} extracted for OCR processing"
        })
    
    if image_count > 0:
        structure.append({
            "type": "images",
            "count": image_count,
            "content": f"Document contains {image_count} image(s)"
        })
    
    # Extract document properties
    if hasattr(doc, "sections"):
        for i, section in enumerate(doc.sections):
            section_info = {
                "type": "document_section",
                "section_number": i + 1,
                "content": {}
            }
            
            if hasattr(section, "page_height") and hasattr(section, "page_width"):
                section_info["content"]["page_size"] = {
                    "width": section.page_width.inches if hasattr(section.page_width, "inches") else "Unknown",
                    "height": section.page_height.inches if hasattr(section.page_height, "inches") else "Unknown"
                }
            
            if hasattr(section, "orientation"):
                section_info["content"]["orientation"] = section.orientation
            
            structure.append(section_info)
    
    return structure

def extract_images(data: bytes, options: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract images from a DOCX document.
    
    Args:
        data: The binary data of the DOCX document.
        options: Processing options.
        
    Returns:
        A list of dictionaries containing information about the images in the DOCX document.
        
    Raises:
        ValueError: If python-docx is not available or the data cannot be processed as a DOCX.
    """
    doc = _open_docx_file(data)

    images = []

    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            image_data = rel.target_part.blob if hasattr(rel.target_part, 'blob') else None
            image_info = {
                "type": "image",
                "target": rel.target_ref,
                "content_type": rel.target_part.content_type,
                "size": getattr(rel.target_part, 'size', None),
                "image_data": image_data
            }
            images.append(image_info)
    return images

def process(data: bytes, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """
    Process a DOCX document completely, extracting text, metadata, and structure.
    
    Args:
        data: The binary data of the DOCX document.
        options: Processing options.
        
    Returns:
        A tuple of (text content, metadata, sections).
        
    Raises:
        ValueError: If python-docx is not available or the data cannot be processed as a DOCX.
    """
    # Extract text, metadata, and structure
    text = extract_text(data, options)
    metadata = extract_metadata(data, options)
    sections = extract_structure(data, options)
    
    # Create a human-readable text version
    text_content = [f"DOCX Document: {metadata.get('title', 'Untitled')}"]
    
    if "author" in metadata:
        text_content.append(f"Author: {metadata['author']}")
    
    if "subject" in metadata:
        text_content.append(f"Subject: {metadata['subject']}")

    if "creation_date" in metadata:
        text_content.append(f"Created: {metadata['creation_date']}")
    
    if "statistics" in metadata:
        stats = metadata["statistics"]
        text_content.append(f"Word Count: {stats.get('word_count', 'Unknown')}")
        text_content.append(f"Paragraphs: {stats.get('paragraph_count', 'Unknown')}")
    
    text_content.append("\n--- Document Text ---\n")
    text_content.append(text)
    
    return "\n".join(text_content), metadata, sections
