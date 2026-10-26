"""US municipalities from the Wikidata seed that are not in the scraped corpus.

The Wikipedia side is ``seeds/americas/US_wikidata.jsonl`` where
``admin_level`` is ``municipality``. A place is scraped when its name matches
one stored American municipal authority, in its state when the seed has one,
or one allowed municipal prefix away when that match is unique. Rows with the
same name in more than one state stay in the ambiguous file.

``gap_reason`` is ``both`` when no website is stored, and ``no_scraper`` when
a website is stored but it is not Municode, American Legal, eCode360, Code
Publishing, or Municipal Code Online. Places already on one of those hosts
and still absent from the corpus are in the ready file. Wikipedia article
titles are not invented.
"""

from __future__ import annotations

import json
from pathlib import Path

_SEEDS = Path(__file__).resolve().parent / "seeds" / "americas"
_GAPS = _SEEDS / "US_municipality_gaps.jsonl"
_READY = _SEEDS / "US_municipality_ready_unscraped.jsonl"
_AMBIGUOUS = _SEEDS / "US_municipality_ambiguous.jsonl"


def gaps_path() -> Path:
    return _GAPS


def ready_path() -> Path:
    return _READY


def ambiguous_path() -> Path:
    return _AMBIGUOUS


def load_municipality_gaps(path: Path | None = None) -> list[dict[str, object]]:
    """Read one municipality gap file. A missing file returns an empty list."""

    target = _GAPS if path is None else path
    if not target.is_file():
        return []
    rows: list[dict[str, object]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows
