"""Wallet-aware derived document analysis helpers."""

from __future__ import annotations

import re
from typing import Dict


def summarize_text_bytes(data: bytes, *, max_chars: int = 500) -> Dict[str, object]:
    """Return a small derived summary without exposing a full plaintext export."""

    text = data.decode("utf-8", errors="replace")
    compact = re.sub(r"\s+", " ", text).strip()
    return {
        "output_type": "summary",
        "summary": compact[:max_chars],
        "char_count": len(text),
        "truncated": len(compact) > max_chars,
    }

