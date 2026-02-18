"""Canonicalization utilities for ZKP theorems and axioms.

Provides stable, deterministic normalization for theorem text and axiom sets.
Used to create reproducible hashes and commitments across proof workflows.
"""

import hashlib
import json
import unicodedata
from typing import List


def normalize_text(text: str) -> str:
    """
    Normalize theorem/axiom text to a canonical form.
    
    Normalizations applied:
    - Unicode NFD normalization
    - Whitespace normalization (collapse multiple spaces, strip)
    - Case preservation (no lowercasing, preserve original intent)
    
    Args:
        text: Raw theorem or axiom text
    
    Returns:
        Normalized canonical text
    
    Example:
        >>> normalize_text("  All  humans  are  mortal  ")
        'All humans are mortal'
    """
    # Unicode normalization (decomposed form)
    text = unicodedata.normalize('NFD', text)
    
    # Collapse whitespace: replace runs of whitespace with single space
    text = ' '.join(text.split())
    
    return text


def canonicalize_theorem(theorem: str) -> str:
    """
    Canonicalize a theorem statement.
    
    Args:
        theorem: Raw theorem text
    
    Returns:
        Canonical form
    """
    return normalize_text(theorem)


def canonicalize_axioms(axioms: List[str]) -> List[str]:
    """
    Canonicalize a set of axioms.
    
    Normalizes each axiom individually, then sorts them for set stability.
    
    Args:
        axioms: List of raw axiom texts
    
    Returns:
        Sorted list of normalized axioms
    
    Example:
        >>> canonicalize_axioms(["Q", "P", "P -> Q"])
        ['P', 'P -> Q', 'Q']
    """
    normalized = [normalize_text(a) for a in axioms]
    return sorted(set(normalized))


def hash_theorem(theorem: str) -> bytes:
    """
    Hash a theorem text deterministically.
    
    The hash is stable under whitespace/unicode variations.
    
    Args:
        theorem: Raw theorem text
    
    Returns:
        SHA-256 digest of canonical theorem
    """
    canonical = canonicalize_theorem(theorem)
    return hashlib.sha256(canonical.encode('utf-8')).digest()


def hash_axioms_commitment(axioms: List[str]) -> bytes:
    """
    Compute a commitment to an axiom set.
    
    Uses Merkle-tree style commitment: hash of sorted, canonical axioms.
    Order-independent: same axioms in any order → same commitment.
    
    Args:
        axioms: List of raw axiom texts
    
    Returns:
        SHA-256 digest of commitment
    """
    canonical = canonicalize_axioms(axioms)
    
    # Build Merkle-style commitment
    # For MVP, use simple JSON hash (not a real Merkle tree)
    commitment_data = json.dumps({
        'axioms': canonical,
        'axiom_count': len(canonical),
    }, sort_keys=True)
    
    return hashlib.sha256(commitment_data.encode('utf-8')).digest()


def theorem_hash_hex(theorem: str) -> str:
    """Hash a theorem and return as hex string."""
    return hash_theorem(theorem).hex()


def axioms_commitment_hex(axioms: List[str]) -> str:
    """Hash axiom set commitment and return as hex string."""
    return hash_axioms_commitment(axioms).hex()
