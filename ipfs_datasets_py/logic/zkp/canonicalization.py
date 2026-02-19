"""Canonicalization utilities for ZKP theorems and axioms.

Provides stable, deterministic normalization for theorem text and axiom sets.
Used to create reproducible hashes and commitments across proof workflows.
"""

import hashlib
import json
import unicodedata
from typing import List


# BN254 scalar field modulus (same value used in Statement.to_field_elements).
P_BN254 = 21888242871839275222246405745257275088548364400416034343698204186575808495617

# Commitment parameters for circuit_version=2 (TDFOL_v1).
#
# This is intentionally NOT a cryptographic hash; it is a deterministic
# field-based accumulator designed to be implemented inside an R1CS.
_TDFOL_V1_V2_ALPHA = 7
_TDFOL_V1_V2_BETA = 13


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


def _sha256_field_int(text: str) -> int:
    """Map a UTF-8 string to a BN254 scalar via SHA-256 then mod p."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest, "big") % P_BN254


def tdfol_v1_axioms_commitment_hex_v2(axioms: List[str]) -> str:
    """Field-only commitment for `TDFOL_v1` axioms (circuit_version=2).

    Commitment is computed over the canonical axiom set (sorted + deduped).

    Encoding:
    - Fact `Q`           -> (antecedent=0, consequent=H(Q))
    - Implication `P->Q` -> (antecedent=H(P), consequent=H(Q))
    where H(atom) is SHA256(atom) reduced mod the BN254 scalar field.

    Accumulator:
        C = Σ_i (consequent_i + alpha * antecedent_i) * beta^i  (mod p)

    Returns:
        32-byte big-endian hex string (no 0x prefix).
    """

    # Import lazily to avoid any import-time overhead in the common path.
    from .legal_theorem_semantics import parse_tdfol_v1_axiom

    canonical = canonicalize_axioms(axioms)

    alpha = _TDFOL_V1_V2_ALPHA
    beta = _TDFOL_V1_V2_BETA

    acc = 0
    beta_pow = 1
    for axiom_text in canonical:
        ax = parse_tdfol_v1_axiom(axiom_text)
        if ax.antecedent is None:
            antecedent = 0
        else:
            antecedent = _sha256_field_int(ax.antecedent)
        consequent = _sha256_field_int(ax.consequent)

        term = (consequent + (alpha * antecedent) % P_BN254) % P_BN254
        acc = (acc + (term * beta_pow) % P_BN254) % P_BN254
        beta_pow = (beta_pow * beta) % P_BN254

    return acc.to_bytes(32, "big").hex()
