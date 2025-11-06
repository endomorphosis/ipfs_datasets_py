import re
from typing import Optional
from bs4 import BeautifulSoup

from ipfs_datasets_py.mcp_server.tools.lizardperson_argparse_programs.municipal_bluebook_citation_validator.dependencies import dependencies

def check_section(citation_section: str, html_body: str) -> Optional[str]:
    """
    Check if a bluebook citation section exists in the HTML document.
    
    Args:
        citation_section: The section from citation (e.g., "S 11-2", "§ 11-2")
        html_body: HTML content to search in
        
    Returns:
        Optional[str]: Error message if validation fails, None if valid
    """
    if not citation_section or not html_body:
        return "Citation section or HTML body is empty"
    
    # Normalize the section format - handle both "S" and "§" prefixes
    normalized_section = citation_section.strip()
    if normalized_section.startswith('S '):
        normalized_section = normalized_section.replace('S ', '§ ')
    elif not normalized_section.startswith('§'):
        normalized_section = f"§ {normalized_section}"
    
    # Extract just the number part for flexible matching
    section_match = re.search(r'(\d+(?:-\d+)?)', normalized_section)
    if not section_match:
        return f"Could not parse section number from: {citation_section}"
    
    section_number = section_match.group(1)
    
    # Parse HTML and search for section references
    try:
        soup = BeautifulSoup(html_body, 'html.parser')
        text_content = soup.get_text().lower()
        
        # Search patterns for section references
        patterns = [ # TODO Debug these regex patterns
            rf'§\s*{re.escape(section_number)}\b',
            rf'section\s+{re.escape(section_number)}\b',
            rf'sec\.\s*{re.escape(section_number)}\b',
            rf's\s+{re.escape(section_number)}\b'
        ]
        
        for pattern in patterns:
            if re.search(pattern, text_content, re.IGNORECASE):
                return None  # Valid - no error
        
        return f"Section {section_number} not found in document"
        
    except Exception as e:
        return f"Error parsing HTML content: {str(e)}"
