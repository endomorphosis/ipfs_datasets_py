def _get_words(text: str) -> list:
    return [w.lower() for w in text.split() if w]

def simple_bleu_approximation(reference: str, extracted: str) -> float:
    """Simple approximation of BLEU score when NLTK is not available.
    
    Args:
        reference: Reference text
        extracted: Extracted text
        
    Returns:
        Approximate BLEU score
    """
    # Get words from both texts
    ref_words = _get_words(reference)
    ext_words = _get_words(extracted)

    if not ref_words or not ext_words:
        return 0.0

    # Calculate word precision (what percentage of extracted words are in reference)
    matches = sum(1 for w in ext_words if w in ref_words)
    precision = matches / len(ext_words) if ext_words else 0
    
    # Calculate brevity penalty
    brevity_penalty = min(1.0, len(ext_words) / len(ref_words)) if ref_words else 0
    
    # Approximate BLEU
    return precision * brevity_penalty