"""Name the 17 non-Python note files so a canonical index can skip them.

The filenames are the list in ``PLAN.md`` under
``hub_integrated/legal_scrapers/``. Each of those files stays at that path.
This module does not import, open, rename, delete, or rewrite them.
"""

from __future__ import annotations

from collections.abc import Iterable

QUARANTINE_NOTE_DIR = "hub_integrated/legal_scrapers"

QUARANTINE_NOTE_FILENAMES: tuple[str, ...] = (
    "al_alfresco_tip26b.py",
    "al_close_tip26b.py",
    "az_cdx_extra_tip26f.py",
    "az_live_gap_tip24o.py",
    "az_live_gap_tip26f.py",
    "bo_live_cdx_miss_tip26m.py",
    "bo_live_failures_tip26a.py",
    "bo_live_failures_tip26b.py",
    "ir_media_recent_tip25q.py",
    "ir_media_recent_tip26b.py",
    "ir_media_recent_tip26n.py",
    "mw_akn_miss_tip25m.py",
    "mw_akn_miss_tip26b.py",
    "mw_akn_miss_tip26n.py",
    "mw_extra_akn_tip25p.py",
    "mw_extra_akn_tip26b.py",
    "mw_extra_akn_tip26m.py",
)

_NOTE_NAMES = frozenset(QUARANTINE_NOTE_FILENAMES)


def note_filename(path: str) -> str:
    """Return the last path segment. An empty path has an empty name."""

    text = str(path).strip().replace("\\", "/")
    if text.endswith("/"):
        text = text[:-1]
    if not text or text == ".":
        return ""
    return text.rsplit("/", 1)[-1]


def is_quarantine_note(path: str) -> bool:
    """Return whether a canonical index must skip this filename or path."""

    return note_filename(path) in _NOTE_NAMES


def skip_quarantine_notes(names: Iterable[str]) -> tuple[str, ...]:
    """Drop quarantine notes. Every other name stays, in the order given."""

    return tuple(name for name in names if not is_quarantine_note(name))
