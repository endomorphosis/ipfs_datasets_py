import string

def _count_paragraphs(text: str) -> int:
    return [p for p in text.split('\n\n') if p.strip()]

def _count_sections(text: str) -> int:
    return [line for line in text.split('\n') if line.strip() and (
        line.strip().startswith('#') or 
        line.strip().endswith(':') or
        all(c in string.ascii_letters + ' ' for c in line.strip())
    )]

def _count_tables(text: str) -> int:
    return [line for line in text.split('\n') if '|' in line]

def _count_lists(text: str) -> int:
    return [line for line in text.split('\n') if line.strip().startswith(('*', '-', '•'))]


def calculate_structural_similarity(str1: str, str2: str) -> float:
    """Calculate structural similarity between two texts.
    
    Args:
        str1: First text
        str2: Second text
        
    Returns:
        Structural similarity score
    """
    comparison_list = []
    for string_ in (str1, str2):
        paragraphs = _count_paragraphs(string_) # Count paragraphs (sequences separated by double newlines)
        sections = _count_sections(string_) # Count sections (lines that might be headings)
        tables = _count_tables(string_) # Count tables
        lists = _count_lists(string_) # Count lists
        # Calculate structural similarity score based on these counts
        struct_elements = len(paragraphs) + len(sections) + len(tables) + len(lists)
        comparison_list.append(struct_elements)

    struct_elements1, struct_elements2  = comparison_list[0], comparison_list[1]

    if struct_elements1 == 0 and struct_elements2 == 0:
        return 1.0  # Both have no structural elements
    
    if struct_elements1 == 0 or struct_elements2 == 0:
        return 0.0  # One has structural elements, the other doesn't
        
    similarity = min(struct_elements1, struct_elements2) / max(struct_elements1, struct_elements2)
    return similarity