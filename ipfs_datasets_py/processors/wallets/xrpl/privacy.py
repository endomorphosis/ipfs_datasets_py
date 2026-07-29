"""Memo and tag privacy policy for XRPL ledger normalization.

Destination tags are numeric identifiers and are preserved by default.
Memo *data* is size-bounded and may be redacted; type/format are retained so
downstream systems can still reason about presence without unconstrained
payload retention. No Xaman payload lifecycle fields are handled here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .models import MemoRecord


DEFAULT_MAX_MEMO_DATA_BYTES = 1024
DEFAULT_MAX_MEMOS = 8


@dataclass(frozen=True, slots=True)
class MemoPrivacyPolicy:
    """Bounds and redaction controls for XRPL memos."""

    max_memo_data_bytes: int = DEFAULT_MAX_MEMO_DATA_BYTES
    max_memos: int = DEFAULT_MAX_MEMOS
    redact_memo_data: bool = False
    preserve_destination_tags: bool = True
    preserve_source_tags: bool = True

    def apply_memos(self, raw_memos: Sequence[Mapping[str, Any]] | None) -> tuple[MemoRecord, ...]:
        if not raw_memos:
            return ()
        out: list[MemoRecord] = []
        for item in list(raw_memos)[: self.max_memos]:
            if not isinstance(item, Mapping):
                continue
            # XRPL account_tx nests fields under "Memo".
            memo = item.get("Memo") if "Memo" in item else item
            if not isinstance(memo, Mapping):
                continue
            memo_type = _optional_str(memo.get("MemoType"))
            memo_format = _optional_str(memo.get("MemoFormat"))
            memo_data = _optional_str(memo.get("MemoData"))
            original_bytes = len(memo_data.encode("utf-8")) if memo_data else 0
            truncated = False
            redacted = False
            if memo_data is not None and original_bytes > self.max_memo_data_bytes:
                # Truncate hex/text payload to bound storage.
                encoded = memo_data.encode("utf-8")[: self.max_memo_data_bytes]
                memo_data = encoded.decode("utf-8", errors="ignore")
                truncated = True
            if self.redact_memo_data and memo_data is not None:
                memo_data = None
                redacted = True
            out.append(
                MemoRecord(
                    memo_type=memo_type,
                    memo_format=memo_format,
                    memo_data=memo_data,
                    data_redacted=redacted,
                    data_truncated=truncated,
                    original_data_bytes=original_bytes or None,
                )
            )
        return tuple(out)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "DEFAULT_MAX_MEMO_DATA_BYTES",
    "DEFAULT_MAX_MEMOS",
    "MemoPrivacyPolicy",
]
