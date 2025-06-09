
import re

def check_dates(citation: dict, documents: list[dict]) -> dict:  # -> ValidationResult
    """Check: Is the year reasonable (1776-2025)?"""

    cited_date = citation.get('date') or citation.get('year')
    
    if not cited_date:
        return 'Missing date or year information in citation'

    # Check if the citation's date is in the html body, the metadata, or both
    documents # TODO: Implement logic to check if the date is in the documents

    # Extract year from various date formats
    year = None
    match cited_date:
        case int():
            year = cited_date
        case str():
            # Try to extract 4-digit year from string
            year_match = re.search(r'\b(1[7-9]\d{2}|20[0-2][0-9])\b', cited_date)
            if year_match:
                year = int(year_match.group(1))

    if year is None:
        return f'Could not extract valid year from date: {cited_date}'

    # Check if year is in reasonable range (1776-2025)
    if year < 1776 or year > 2025:
        return  f'Year {year} is outside reasonable range (1776-2025)'

    return 'Date check passed'
