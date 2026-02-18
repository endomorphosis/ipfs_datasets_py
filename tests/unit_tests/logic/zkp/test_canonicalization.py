"""Unit tests for canonicalization module."""

import pytest
from ipfs_datasets_py.logic.zkp.canonicalization import (
    normalize_text,
    canonicalize_theorem,
    canonicalize_axioms,
    hash_theorem,
    hash_axioms_commitment,
    theorem_hash_hex,
    axioms_commitment_hex,
)


class TestNormalizeText:
    """Test text normalization."""

    def test_collapse_whitespace(self):
        """Multiple spaces collapse to single space."""
        assert normalize_text("All   humans   are   mortal") == "All humans are mortal"

    def test_strip_whitespace(self):
        """Leading/trailing whitespace removed."""
        assert normalize_text("  All humans are mortal  ") == "All humans are mortal"

    def test_newlines_become_spaces(self):
        """Newlines collapse to spaces."""
        assert normalize_text("All humans\nare mortal") == "All humans are mortal"

    def test_tabs_become_spaces(self):
        """Tabs collapse to spaces."""
        assert normalize_text("All\thumans\tare\tmortal") == "All humans are mortal"

    def test_unicode_normalization(self):
        """Unicode strings normalize consistently."""
        # Composed vs. decomposed form
        composed = "café"
        decomposed = "cafe\u0301"
        assert normalize_text(composed) == normalize_text(decomposed)


class TestCanonicalizeTheorem:
    """Test theorem canonicalization."""

    def test_simple_theorem(self):
        """Simple theorem normalizes correctly."""
        assert canonicalize_theorem("Q") == "Q"

    def test_theorem_with_spaces(self):
        """Theorem with extra spaces normalizes."""
        result = canonicalize_theorem("  All  humans  are  mortal  ")
        assert result == "All humans are mortal"

    def test_theorem_stability(self):
        """Same theorem + different whitespace → same canonical form."""
        t1 = "All humans are mortal"
        t2 = "  All   humans  are   mortal  "
        assert canonicalize_theorem(t1) == canonicalize_theorem(t2)


class TestCanonicalizeAxioms:
    """Test axiom canonicalization."""

    def test_simple_axioms(self):
        """Simple axioms are sorted."""
        result = canonicalize_axioms(["Q", "P", "P -> Q"])
        assert result == ["P", "P -> Q", "Q"]

    def test_axioms_with_whitespace(self):
        """Axioms with whitespace normalize."""
        result = canonicalize_axioms(["  Q  ", "  P  ", "  P -> Q  "])
        assert result == ["P", "P -> Q", "Q"]

    def test_duplicate_axioms_deduplicated(self):
        """Duplicate axioms appear once."""
        result = canonicalize_axioms(["P", "P", "Q"])
        assert result == ["P", "Q"]

    def test_axiom_order_irrelevant(self):
        """Axiom ordering doesn't matter."""
        axioms1 = ["P", "Q", "R"]
        axioms2 = ["R", "P", "Q"]
        assert canonicalize_axioms(axioms1) == canonicalize_axioms(axioms2)


class TestHashTheorem:
    """Test theorem hashing."""

    def test_hash_is_bytes(self):
        """Theorem hash returns bytes."""
        h = hash_theorem("Q")
        assert isinstance(h, bytes)
        assert len(h) == 32  # SHA-256

    def test_same_theorem_same_hash(self):
        """Same theorem produces same hash."""
        h1 = hash_theorem("All humans are mortal")
        h2 = hash_theorem("All humans are mortal")
        assert h1 == h2

    def test_whitespace_invariant(self):
        """Whitespace variations produce same hash."""
        h1 = hash_theorem("All humans are mortal")
        h2 = hash_theorem("  All   humans  are   mortal  ")
        assert h1 == h2

    def test_different_theorems_different_hashes(self):
        """Different theorems produce different hashes."""
        h1 = hash_theorem("P")
        h2 = hash_theorem("Q")
        assert h1 != h2


class TestHashAxiomsCommitment:
    """Test axiom commitment hashing."""

    def test_commitment_is_bytes(self):
        """Axiom commitment returns bytes."""
        c = hash_axioms_commitment(["P", "Q"])
        assert isinstance(c, bytes)
        assert len(c) == 32  # SHA-256

    def test_same_axioms_same_commitment(self):
        """Same axioms produce same commitment."""
        c1 = hash_axioms_commitment(["P", "Q"])
        c2 = hash_axioms_commitment(["P", "Q"])
        assert c1 == c2

    def test_axiom_order_invariant(self):
        """Axiom order doesn't change commitment."""
        c1 = hash_axioms_commitment(["P", "Q", "R"])
        c2 = hash_axioms_commitment(["R", "P", "Q"])
        assert c1 == c2

    def test_different_axioms_different_commitment(self):
        """Different axioms produce different commitments."""
        c1 = hash_axioms_commitment(["P", "Q"])
        c2 = hash_axioms_commitment(["P", "R"])
        assert c1 != c2

    def test_whitespace_invariant(self):
        """Whitespace in axioms is normalized."""
        c1 = hash_axioms_commitment(["P", "Q"])
        c2 = hash_axioms_commitment(["  P  ", "  Q  "])
        assert c1 == c2

    def test_duplicates_deduplicated(self):
        """Duplicate axioms don't change commitment."""
        c1 = hash_axioms_commitment(["P", "Q"])
        c2 = hash_axioms_commitment(["P", "P", "Q"])
        assert c1 == c2


class TestHexEncoding:
    """Test hex string encoding."""

    def test_theorem_hash_hex(self):
        """Theorem hash returns hex string."""
        h = theorem_hash_hex("Q")
        assert isinstance(h, str)
        assert len(h) == 64  # 32 bytes * 2 hex chars
        assert all(c in '0123456789abcdef' for c in h)

    def test_axioms_commitment_hex(self):
        """Axiom commitment returns hex string."""
        c = axioms_commitment_hex(["P", "Q"])
        assert isinstance(c, str)
        assert len(c) == 64
        assert all(c in '0123456789abcdef' for c in c)
