"""Find an official website when Wikidata P856 is empty."""

from __future__ import annotations

import re
from urllib.parse import urlparse

_OFFICIAL = (
    re.compile(r"\{\{[Oo]fficial(?:\s+website|\s+URL)?\|([^}|]+)"),
    re.compile(r"\|\s*(?:website|web|official_website|official website)\s*=\s*(?:\{\{[Uu]RL\|)?([^}|\n]+)"),
)
_SKIP_HOSTS = (
    "wikipedia.org",
    "wikimedia.org",
    "wikidata.org",
    "web.archive.org",
    "archive.org",
    "doi.org",
    "facebook.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "instagram.com",
    "google.com",
    "worldcat.org",
    "viaf.org",
    "geonames.org",
    "musicbrainz.org",
)


def clean_website(value: str) -> str:
    text = (value or "").strip().strip("[]'\"")
    text = re.sub(r"\{\{[Uu]RL\|", "", text)
    text = text.split("|", 1)[0].strip()
    if not text or text.startswith("{{"):
        return ""
    if text.startswith("//"):
        text = "https:" + text
    elif not text.startswith(("http://", "https://")):
        if "." not in text:
            return ""
        text = "https://" + text
    host = urlparse(text).netloc.lower().removeprefix("www.")
    if not host or any(host == skip or host.endswith("." + skip) for skip in _SKIP_HOSTS):
        return ""
    return text


_RESULT_SKIP = _SKIP_HOSTS + (
    "tripadvisor.",
    "booking.com",
    "britannica.com",
    "lonelyplanet.com",
)
_NAME_STOP = {
    "province",
    "region",
    "district",
    "municipality",
    "department",
    "county",
    "north",
    "south",
    "east",
    "west",
    "city",
    "town",
    "state",
    "territory",
    "parish",
}


def name_tokens(name: str) -> list[str]:
    import unicodedata

    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return [token for token in re.findall(r"[a-z]{4,}", text) if token not in _NAME_STOP]


_HOST_BLOCK = (
    "tourism",
    "visit",
    "chamber",
    "embassy",
    "tripadvisor",
    "britannica",
    "unhcr.org",
    "iom.int",
    "themimu",
    "toptours",
    "travel",
)


def result_matches_place(url: str, name: str) -> bool:
    """Keep a hit only when the place name is in a government hostname."""
    cleaned = clean_website(url)
    tokens = name_tokens(name)
    if not cleaned or not tokens:
        return False
    host = urlparse(cleaned).netloc.lower().removeprefix("www.")
    if any(skip in host for skip in _RESULT_SKIP) or any(block in host for block in _HOST_BLOCK):
        return False
    if "deped" in host:
        return False
    government = any(mark in host for mark in (".gov", ".gouv", ".gob.", ".gub.", ".go.", "gov."))
    return government and any(token in host for token in tokens)


def official_website_from_wikitext(wikitext: str) -> str:
    for pattern in _OFFICIAL:
        match = pattern.search(wikitext or "")
        if not match:
            continue
        cleaned = clean_website(match.group(1))
        if cleaned:
            return cleaned
    return ""
