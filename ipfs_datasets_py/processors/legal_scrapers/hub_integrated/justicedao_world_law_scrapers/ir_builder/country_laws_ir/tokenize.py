"""FTS5 unicode61 remove_diacritics=2-style tokenizer."""

from __future__ import annotations

import re
import unicodedata

_TOKEN_RE = re.compile(r"[0-9A-Za-z]+", re.UNICODE)


def fold_diacritics(text: str) -> str:
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).lower()


def tokenize(text: str | None) -> list[str]:
    if not text:
        return []
    return _TOKEN_RE.findall(fold_diacritics(str(text)))
