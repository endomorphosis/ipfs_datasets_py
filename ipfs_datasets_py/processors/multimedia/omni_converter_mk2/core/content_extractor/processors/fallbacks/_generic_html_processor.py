"""
Generic HTML processor, using only base python 3.12 features.

supported file formats: text/html, application/xhtml+xml
"""
import re
import html
from typing import Any, Optional

def extract_metadata(data: str, options: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Extract metadata from HTML content.
    
    Args:
        data: The HTML content as text.
        options: Optional extraction options.
        
    Returns:
        Dictionary of metadata.
    """
    # Extract title
    title_match = re.search(r'<title\b[^>]*>(.*?)</title\b[^>]*>', data, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1) if title_match else ""
    
    # Extract metadata from meta tags
    metadata = {
        'title': title,
        'format': 'html'
    }
    
    # Extract description
    desc_match = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']\s*/?>', 
                        data, re.IGNORECASE | re.DOTALL)
    if desc_match:
        metadata['description'] = desc_match.group(1)
    
    # Extract keywords
    keywords_match = re.search(r'<meta\s+name=["\']keywords["\']\s+content=["\'](.*?)["\']\s*/?>', 
                            data, re.IGNORECASE | re.DOTALL)
    if keywords_match:
        metadata['keywords'] = keywords_match.group(1)
    
    # Extract author
    author_match = re.search(r'<meta\s+name=["\']author["\']\s+content=["\'](.*?)["\']\s*/?>', 
                            data, re.IGNORECASE | re.DOTALL)
    if author_match:
        metadata['author'] = author_match.group(1)
    
    return metadata


def extract_text(data: str, options: Optional[dict[str, Any]] = None) -> str:
    """
    Extract plain text content from HTML.
    
    Args:
        data: The HTML content as text.
        options: Optional extraction options.
        
    Returns:
        Plain text extracted from HTML.
    """
    # Remove script and style tags
    text = re.sub(r'<script\b[^>]*>.*?</script\b[^>]*>', '', data, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<style\b[^>]*>.*?</style\b[^>]*>', '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Replace common tags with newlines or spaces
    text = re.sub(r'<(br|p|div|h[1-6]|li)[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</(p|div|h[1-6]|li)>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]*>', ' ', text)
    
    # Decode HTML entities
    text = html.unescape(text)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def extract_structure(data: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Create sections from HTML content.
    
    Args:
        data: The HTML content as text.
        metadata: Metadata extracted from the HTML.
        
    Returns:
        List of sections.
    """
    sections = []
    
    # Add title section if available
    title = metadata.get('title')
    if title:
        sections.append({
            'type': 'title',
            'content': title
        })
    
    # Extract headings
    heading_pattern = r'<h([1-6])\b[^>]*>(.*?)</h\1\b[^>]*>'
    headings = re.findall(heading_pattern, data, re.IGNORECASE | re.DOTALL)
    
    for level, content in headings:
        # Clean up the heading content
        clean_content = re.sub(r'<[^>]*>', '', content)
        clean_content = html.unescape(clean_content).strip()
        
        if clean_content:
            sections.append({
                'type': f'heading{level}',
                'content': clean_content
            })
    
    # Add body section
    text = extract_text(data)
    sections.append({
        'type': 'body',
        'content': text
    })
    
    return sections


def process(
    file_content: str | bytes,
    options: dict[str, Any]
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """Process HTML content.
    
    Args:
        file_content: The file content to process.
        options: Processing options.
        
    Returns:
        Tuple of (text content, metadata, sections).
    """
    # Get HTML content as text
    if hasattr(file_content, 'get_as_text'):
        data = file_content.get_as_text()
    else:
        data = file_content
    
    # Extract metadata
    metadata = extract_metadata(data, options)
    
    # Extract text content
    text = extract_text(data, options)
    
    # Create sections
    sections = extract_structure(data, metadata)
    
    return text, metadata, sections