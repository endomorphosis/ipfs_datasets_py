import re

def check_format(citation: dict) -> str | None:
    """Check: Does this follow correct Bluebook formatting?"""

    # Get citation components
    title = citation.get('title', '')
    section = citation.get('section', '')
    date = citation.get('date', '')
    url = citation.get('url', '')
    
    if not any([title, section, date, url]):
        return 'Missing required citation components'

    errors = []

    # Check title formatting (should not be empty and properly capitalized)
    if not title or title.strip() == '':
        errors.append('Title is missing or empty')
    elif title != title.strip():
        errors.append('Title has leading/trailing whitespace')

    # Check section formatting (should match pattern like "14-75" or "§ 14-75")
    if section:
        section_pattern = r'^(§\s*)?[\d]+[-\.][\d]+(\([a-z]\))?$'
        if not re.match(section_pattern, section.strip()):
            errors.append(f'Section "{section}" does not match expected format')

    # Check URL formatting (should be valid URL)
    if url:
        url_pattern = r'^https?://[^\s<>"{}|\\^`\[\]]+$'
        if not re.match(url_pattern, url.strip()):
            errors.append(f'URL "{url}" is not properly formatted')

    # Check date formatting (should be valid year or date)
    if date:
        date_str = str(date).strip()
        # Check for various date formats
        date_patterns = [
            r'^\d{4}$',  # Year only: 2023
            r'^\d{1,2}/\d{1,2}/\d{4}$',  # MM/DD/YYYY
            r'^\d{4}-\d{2}-\d{2}$',  # YYYY-MM-DD
            r'^[A-Za-z]+ \d{1,2}, \d{4}$'  # Month DD, YYYY
        ]
        if not any(re.match(pattern, date_str) for pattern in date_patterns):
            errors.append(f'Date "{date}" is not in a recognized format')

    if errors:
        return '; '.join(errors)
