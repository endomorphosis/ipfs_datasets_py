

from utils.for_tests.longest_common_subsequence_length import longest_common_subsequence_length


def simple_rouge_approximation(reference: str, extracted: str) -> float:
    """Simple approximation of ROUGE-L score when Rouge library is not available.
    
    Args:
        self: Class instance
        reference: Reference text
        extracted: Extracted text
        
    Returns:
        Approximate ROUGE-L score
    """
    # Get words from both texts
    ref_words = [w.lower() for w in reference.split() if w]
    ext_words = [w.lower() for w in extracted.split() if w]
    
    if not ref_words or not ext_words:
        return 0.0
    
    # Find longest common subsequence length
    lcs_length = longest_common_subsequence_length(ref_words, ext_words)
    
    # Calculate precision, recall and F1 (ROUGE-L is based on F1)
    precision = lcs_length / len(ext_words) if ext_words else 0
    recall = lcs_length / len(ref_words) if ref_words else 0
    
    if precision + recall > 0:
        f1 = (2 * precision * recall) / (precision + recall)
    else:
        f1 = 0.0
        
    return f1