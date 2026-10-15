"""Local pin file for JusticeDAO repos the query must not open early.

``pin_readable`` is true only when this file names the id, ``searchable`` is
true, and ``revision`` is 40 lowercase hex characters. A missing id is not
readable. This module does not contact the Hub.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_PIN_PATH = Path(__file__).with_name("justicedao_release_pins.json")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def pin_path() -> Path:
    return _PIN_PATH


@lru_cache(maxsize=1)
def load_pins() -> dict[str, dict[str, object]]:
    payload = json.loads(_PIN_PATH.read_text(encoding="utf-8"))
    repos = payload.get("repos")
    if not isinstance(repos, dict):
        raise ValueError("justicedao_release_pins.json missing repos object")
    return repos


def _entry(repo_id: str) -> dict[str, object] | None:
    name = str(repo_id or "").strip()
    if name.startswith("justicedao/"):
        name = name.split("/", 1)[1]
    entry = load_pins().get(name)
    if not isinstance(entry, dict):
        return None
    return entry


def pin_readable(repo_id: str) -> bool:
    """True when the pin file allows this repo to be opened."""

    entry = _entry(repo_id)
    if entry is None or entry.get("searchable") is not True:
        return False
    revision = entry.get("revision")
    return isinstance(revision, str) and _SHA.fullmatch(revision) is not None


def pin_revision(repo_id: str) -> str | None:
    """40-hex revision when the pin is readable, otherwise None."""

    if not pin_readable(repo_id):
        return None
    entry = _entry(repo_id)
    if entry is None:
        return None
    revision = entry.get("revision")
    if isinstance(revision, str) and _SHA.fullmatch(revision) is not None:
        return revision
    return None
