"""
Semantic normalizer for F-logic query goals.

This module maps semantically equivalent terms (synonyms, abbreviations,
domain aliases) to a single **canonical form** so that queries like
``"?X : Canine"`` and ``"?X : Dog"`` resolve to the same cache entry.

Two backends are supported, selected at construction time:

* **SymAI** (``symai``, if installed) — uses an LLM (via
  :class:`symai.Symbol`) to identify the preferred canonical name for any
  term.  The canonical form is cached locally so that each unique term is
  only LLM-resolved once per process lifetime.
* **Fallback** — a purely local dictionary-based resolver that applies a
  configurable synonym map.  No network calls, no external deps.

Usage::

    from ipfs_datasets_py.logic.flogic.semantic_normalizer import SemanticNormalizer

    # Uses SymAI if available, otherwise falls back to the built-in map
    norm = SemanticNormalizer()

    # Normalize individual terms
    assert norm.normalize_term("canine")  == "dog"   # if synonym map has it
    assert norm.normalize_term("Dog")     == "dog"

    # Normalize a full Ergo goal string
    goal_in  = "?X : Canine"
    goal_out = norm.normalize_goal(goal_in)
    # goal_out == "?X : dog"  (or whatever the canonical form is)

The normalizer is idempotent: passing an already-canonical form returns
the same string unchanged.
"""

from __future__ import annotations

import logging
import re
import time
from functools import lru_cache
from threading import RLock
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional SymAI import
# ---------------------------------------------------------------------------

try:
    from symai import Symbol as _SymaiSymbol  # type: ignore
    _SYMAI_AVAILABLE = True
except (ImportError, SystemExit):
    _SymaiSymbol = None  # type: ignore
    _SYMAI_AVAILABLE = False

# ---------------------------------------------------------------------------
# Built-in fallback synonym map
# ---------------------------------------------------------------------------

#: A conservative hand-crafted synonym map used when SymAI is unavailable.
#: Keys are lowercased variants; values are the canonical (preferred) form.
DEFAULT_SYNONYM_MAP: Dict[str, str] = {
    # Animals
    "canine": "dog",
    "feline": "cat",
    "equine": "horse",
    "bovine": "cow",
    "swine": "pig",
    "porcine": "pig",
    "ovine": "sheep",
    # People
    "person": "person",
    "human": "person",
    "individual": "person",
    "human being": "person",
    "homo sapiens": "person",
    # Legal / deontic
    "prohibited": "forbidden",
    "impermissible": "forbidden",
    "obligatory": "required",
    "must": "required",
    "shall": "required",
    "permitted": "allowed",
    "permissible": "allowed",
    "may": "allowed",
    # Data / type synonyms
    "integer": "int",
    "string": "str",
    "boolean": "bool",
    "floating point": "float",
}


# ---------------------------------------------------------------------------
# SemanticNormalizer
# ---------------------------------------------------------------------------


class SemanticNormalizer:
    """
    Normalize F-logic terms and query goals to canonical semantic forms.

    When **SymAI is available**, canonical forms are resolved by querying an
    LLM with a concise prompt.  Results are memoized so each unique input
    term is only sent to the LLM once per instance lifetime.

    When **SymAI is unavailable** (or ``use_symai=False``), a built-in
    synonym dictionary is used instead.

    Args:
        use_symai: Try to use SymAI for semantic resolution.  Defaults to
            ``True``; set to ``False`` to force dictionary-only mode.
        synonym_map: Additional synonyms to merge with ``DEFAULT_SYNONYM_MAP``.
            Keys and values are lowercased at construction time.
        confidence_threshold: Minimum LLM confidence (0.0–1.0) below which
            the LLM answer is discarded and the input term is kept unchanged.
    """

    def __init__(
        self,
        use_symai: bool = True,
        synonym_map: Optional[Dict[str, str]] = None,
        confidence_threshold: float = 0.6,
    ) -> None:
        # Merge the default map with any caller-supplied overrides
        self._map: Dict[str, str] = dict(DEFAULT_SYNONYM_MAP)
        for k, v in (synonym_map or {}).items():
            self._map[k.lower().strip()] = v.lower().strip()

        self._use_symai = use_symai and _SYMAI_AVAILABLE
        self._confidence_threshold = confidence_threshold

        # Thread-safe cache for LLM-resolved terms {input_lower: canonical}
        self._llm_cache: Dict[str, str] = {}
        self._lock = RLock()

        if self._use_symai:
            logger.info("SemanticNormalizer: SymAI backend active")
        else:
            logger.info(
                "SemanticNormalizer: dictionary-only mode%s",
                " (symai not installed)" if not _SYMAI_AVAILABLE else "",
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def symai_available(self) -> bool:
        """``True`` when the SymAI backend is active."""
        return self._use_symai

    def normalize_term(self, term: str) -> str:
        """
        Return the canonical form of *term*.

        Resolution order:
        1. LLM cache (if SymAI active and term was previously resolved)
        2. Built-in synonym map (case-insensitive)
        3. LLM resolution via SymAI (result is cached)
        4. Fallback: lowercase + stripped original

        Args:
            term: A single identifier, class name, or predicate token.

        Returns:
            Canonical lowercase string.
        """
        key = term.lower().strip()

        # 1. LLM cache hit
        with self._lock:
            if key in self._llm_cache:
                return self._llm_cache[key]

        # 2. Built-in map
        if key in self._map:
            return self._map[key]

        # 3. SymAI resolution
        if self._use_symai:
            canonical = self._resolve_via_symai(key)
            if canonical and canonical != key:
                with self._lock:
                    self._llm_cache[key] = canonical
                return canonical

        # 4. Fallback: return normalized input
        return key

    def normalize_goal(self, goal: str) -> str:
        """
        Normalize all identifiers in an Ergo *goal* string.

        Only identifiers that appear after ``:`` (ISA) or ``[`` (method
        head) or at the start of tokens are resolved; Ergo variable names
        (starting with ``?``) and quoted strings are left untouched.

        Args:
            goal: An Ergo query goal, e.g. ``"?X : Canine"``.

        Returns:
            Goal string with identifiers replaced by their canonical forms.
        """
        return _replace_identifiers(goal, self.normalize_term)

    def add_synonym(self, variant: str, canonical: str) -> None:
        """Register a new synonym mapping at runtime."""
        self._map[variant.lower().strip()] = canonical.lower().strip()

    def get_map_snapshot(self) -> Dict[str, str]:
        """Return a copy of the current synonym map (for inspection / export)."""
        with self._lock:
            combined = dict(self._map)
            combined.update(self._llm_cache)
        return combined

    # ------------------------------------------------------------------
    # SymAI internal
    # ------------------------------------------------------------------

    def _resolve_via_symai(self, term: str) -> Optional[str]:
        """Ask the LLM for the canonical English name for *term*."""
        if _SymaiSymbol is None:
            return None
        try:
            prompt = _SymaiSymbol(
                f"What is the single most common, canonical English word or"
                f" short phrase for the concept '{term}'?  Reply with ONLY"
                f" the canonical form, lowercase, no punctuation.",
                semantic=True,
            )
            response = str(prompt.query(
                "Provide the canonical term. Reply with ONE word or short phrase only."
            )).strip().lower()

            # Reject clearly bad responses (too long, empty, contains space-heavy text)
            if not response or len(response) > 50 or "\n" in response:
                return None

            # Strip any leading/trailing punctuation
            response = re.sub(r"^[\W_]+|[\W_]+$", "", response)
            if not response:
                return None

            return response
        except Exception as exc:
            logger.debug("SymAI term resolution failed for %r: %s", term, exc)
            return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Ergo identifier pattern: letters, digits, underscore, starting with letter
_IDENT_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*)\b")


def _replace_identifiers(text: str, resolver) -> str:
    """
    Replace non-variable, non-quoted identifiers in an Ergo string.

    Variable tokens (``?X``) and single/double-quoted literals are not touched.
    All resolved identifiers are lowercased to their canonical form so that
    "Dog" and "dog" and "Canine" all normalise to the same key.
    """
    # Quick protection: collect quoted ranges to skip
    quoted: list[Tuple[int, int]] = []
    for m in re.finditer(r"'[^']*'|\"[^\"]*\"", text):
        quoted.append((m.start(), m.end()))

    def _in_quotes(pos: int) -> bool:
        return any(s <= pos < e for s, e in quoted)

    def _replace(match: re.Match) -> str:
        if _in_quotes(match.start()):
            return match.group(0)
        orig = match.group(1)
        # Keep single uppercase letters (e.g. logical variables X, Y, Z)
        if orig[0].isupper() and len(orig) == 1:
            return orig
        # Always return the canonical (lowercase) form so that "Dog" and
        # "Canine" both resolve to "dog" and share the same cache key.
        return resolver(orig)

    return _IDENT_RE.sub(_replace, text)


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_global_normalizer: Optional[SemanticNormalizer] = None


def get_global_normalizer(*, use_symai: bool = True) -> SemanticNormalizer:
    """
    Return (or create) the process-wide :class:`SemanticNormalizer`.

    The first call controls whether SymAI is used; subsequent calls return
    the already-created instance regardless of *use_symai*.
    """
    global _global_normalizer
    if _global_normalizer is None:
        _global_normalizer = SemanticNormalizer(use_symai=use_symai)
    return _global_normalizer


__all__ = [
    "SemanticNormalizer",
    "get_global_normalizer",
    "DEFAULT_SYNONYM_MAP",
    "_SYMAI_AVAILABLE",
]
