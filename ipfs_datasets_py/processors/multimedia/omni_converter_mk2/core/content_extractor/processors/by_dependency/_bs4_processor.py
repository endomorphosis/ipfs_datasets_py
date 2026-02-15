"""
BeautifulSoup HTML processing utilities.

This module contains functions for processing HTML content using BeautifulSoup.
"""
import re
from typing import Any, Optional


from dependencies import dependencies


def _get_soup(html_content: str):
    return dependencies.bs4.BeautifulSoup(html_content, 'html.parser')


def extract_metadata(
    html_content: str,
    options: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """
    Extract metadata from HTML content using BeautifulSoup.
    
    Args:
        html_content: The HTML content as text.
        options: Optional extraction options.
        
    Returns:
        Dictionary of metadata.
    """
    soup = dependencies.bs4.BeautifulSoup(html_content, 'html.parser')

    metadata = {
        'format': 'html'
    }

    # Extract title
    title_tag = soup.find('title')
    if title_tag:
        metadata['title'] = title_tag.get_text().strip()

    # Extract meta tags
    meta_tags = soup.find_all('meta')
    
    for meta in meta_tags:
        name = meta.get('name', '').lower()
        content = meta.get('content', '')

        if name and content:
            metadata[name] = content

    # Extract Open Graph metadata
    og_tags = soup.find_all('meta', attrs={'property': re.compile(r'^og:')})
    for og in og_tags:
        property_name = og.get('property', '')
        content = og.get('content', '')
        if property_name and content:
            metadata[property_name] = content
    
    # Extract charset
    charset_meta = soup.find('meta', attrs={'charset': True})
    if charset_meta:
        metadata['charset'] = charset_meta.get('charset')
    
    return metadata


def extract_text(
    html_content: str,
    options: Optional[dict[str, Any]] = None
) -> str:
    """
    Extract plain text content from HTML using BeautifulSoup.
    
    Args:
        html_content: The HTML content as text.
        options: Optional extraction options.
        
    Returns:
        Plain text extracted from HTML.
    """
    soup = dependencies.bs4.BeautifulSoup(html_content, 'html.parser')
    
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()
    
    # Get text and handle line breaks
    text = soup.get_text()
    
    # Normalize whitespace
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = ' '.join(chunk for chunk in chunks if chunk)
    
    return text


def extract_structure(
    html_content: str,
    metadata: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    Create sections from HTML content using BeautifulSoup.
    
    Args:
        html_content: The HTML content as text.
        metadata: Metadata extracted from the HTML.
        
    Returns:
        List of sections.
    """
    soup = soup = dependencies.bs4.BeautifulSoup(html_content, 'html.parser')
    sections = []
    
    # Add title section if available
    title = metadata.get('title')
    if title:
        sections.append({
            'type': 'title',
            'content': title
        })
    
    # Extract headings (h1-h6)
    for heading_level in range(1, 7):
        headings = soup.find_all(f'h{heading_level}')
        for heading in headings:
            content = heading.get_text().strip()
            if content:
                sections.append({
                    'type': f'heading{heading_level}',
                    'content': content
                })
    
    # Extract paragraphs
    paragraphs = soup.find_all('p')
    for i, p in enumerate(paragraphs):
        content = p.get_text().strip()
        if content:
            sections.append({
                'type': 'paragraph',
                'content': content,
                'order': i
            })
    
    # Extract lists
    lists = soup.find_all(['ul', 'ol'])
    for list_elem in lists:
        list_items = list_elem.find_all('li')
        list_content = []
        for li in list_items:
            item_text = li.get_text().strip()
            if item_text:
                list_content.append(item_text)
        
        if list_content:
            sections.append({
                'type': 'list',
                'list_type': list_elem.name,
                'content': list_content
            })
    
    # Extract tables
    tables = soup.find_all('table')
    for table in tables:
        rows = []
        for tr in table.find_all('tr'):
            cells = []
            for cell in tr.find_all(['td', 'th']):
                cells.append(cell.get_text().strip())
            if cells:
                rows.append(cells)
        
        if rows:
            sections.append({
                'type': 'table',
                'content': rows
            })

    # Add overall body section with cleaned text
    text = extract_text(html_content)
    if text:
        sections.append({
            'type': 'body',
            'content': text
        })

    return sections


def process(
    file_content: bytes | str,
    options: dict[str, Any]
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """
    Process HTML content using BeautifulSoup.
    
    Args:
        file_content (Content): The file content to process.
        options (dict[str, Any]): Processing options.
        
    Returns:
        Tuple of (text content, metadata, sections).
    """
    # Get HTML content as text
    if hasattr(file_content, 'get_as_text'):
        html_content = file_content.get_as_text()
    else:
        html_content = str(file_content)

    # Extract metadata
    metadata = extract_metadata(html_content, options)

    # Extract text content
    text = extract_text(html_content, options)
    
    # Create sections
    sections = extract_structure(html_content, metadata)
    
    return text, metadata, sections