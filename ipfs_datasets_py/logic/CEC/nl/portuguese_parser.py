"""DJ172: Portuguese deontic NL parser for policy clause extraction.

Provides a lightweight keyword-based approach for detecting deontic operators
(permission, prohibition, obligation) in Portuguese text.  No external NLP
dependencies are required.

This module mirrors the structure of the French, Spanish, and German parsers
so that it integrates transparently with ``detect_all_languages()`` and the
``_I18N_KEYWORD_LOADERS`` dispatch table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Keyword tables
# ---------------------------------------------------------------------------

_PT_PERMISSION_KEYWORDS: List[str] = [
    "pode",
    "é permitido",
    "é autorizado",
    "tem o direito de",
    "está autorizado a",
    "pode ser",
    "é possível",
]

_PT_PROHIBITION_KEYWORDS: List[str] = [
    "não pode",
    "não é permitido",
    "é proibido",
    "está proibido",
    "não está autorizado",
    "não deve",
    "é vedado",
]

_PT_OBLIGATION_KEYWORDS: List[str] = [
    "deve",
    "tem de",
    "é obrigatório",
    "é necessário",
    "é exigido",
    "tem a obrigação de",
    "precisa de",
]

_PT_DEONTIC_KEYWORDS: Dict[str, List[str]] = {
    "permission": _PT_PERMISSION_KEYWORDS,
    "prohibition": _PT_PROHIBITION_KEYWORDS,
    "obligation": _PT_OBLIGATION_KEYWORDS,
}


def get_portuguese_deontic_keywords() -> Dict[str, List[str]]:
    """Return the Portuguese deontic keyword table.

    Returns
    -------
    dict
        Mapping ``{"permission": [...], "prohibition": [...], "obligation": [...]}``
        with Portuguese deontic keywords.
    """
    return _PT_DEONTIC_KEYWORDS


# ---------------------------------------------------------------------------
# Lightweight clause extractor
# ---------------------------------------------------------------------------

@dataclass
class PortugueseClause:
    """A deontic clause extracted from Portuguese text.

    Attributes
    ----------
    text:
        Original sentence fragment matched.
    deontic_type:
        ``"permission"``, ``"prohibition"``, or ``"obligation"``.
    matched_keyword:
        The deontic keyword that triggered the match.
    """

    text: str
    deontic_type: str
    matched_keyword: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "deontic_type": self.deontic_type,
            "matched_keyword": self.matched_keyword,
        }


class PortugueseParser:
    """Lightweight Portuguese deontic NL parser.

    Detects permission, prohibition, and obligation statements using the
    keyword tables defined in this module.  No external dependencies are
    required.

    Examples
    --------
    >>> parser = PortugueseParser()
    >>> clauses = parser.parse("O utilizador pode aceder ao sistema.")
    >>> len(clauses)
    1
    >>> clauses[0].deontic_type
    'permission'
    """

    def __init__(self) -> None:
        self._keywords = _PT_DEONTIC_KEYWORDS

    def parse(self, text: str) -> List[PortugueseClause]:
        """DP178: Parse *text* and return a list of :class:`PortugueseClause` objects.

        Splits the input on sentence boundaries (``"."``, ``"!"``, ``"?"`` and
        ``";"``) and scans each sentence fragment independently so that a
        single input can yield multiple clauses (one per deontic type per
        sentence).

        Parameters
        ----------
        text:
            Portuguese natural-language text to parse.

        Returns
        -------
        list of :class:`PortugueseClause`
            Detected deontic clauses; empty list when none are found.
            Multiple clauses may be returned when the text contains both
            permissions and prohibitions in separate sentences.
        """
        # DP178: split on sentence boundaries to allow multi-clause extraction.
        sentences = [s.strip() for s in re.split(r"[.!?;]+", text) if s.strip()]
        if not sentences:
            sentences = [text]
        clauses: List[PortugueseClause] = []
        for sentence in sentences:
            sentence_lower = sentence.lower()
            for deontic_type, keywords in self._keywords.items():
                for kw in keywords:
                    if kw in sentence_lower:
                        clauses.append(
                            PortugueseClause(
                                text=sentence,
                                deontic_type=deontic_type,
                                matched_keyword=kw,
                            )
                        )
                        break  # one clause per deontic type per sentence
        return clauses
