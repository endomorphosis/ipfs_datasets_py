"""Shared HTTP, CID, Bluebook, and citation-parsing helpers."""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://library.municode.com/",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
}

# Bluebook (T10) state abbreviations. Column name in the dataset is the typo
# bluebook_sate_code.
BLUEBOOK_STATE = {
    "AL": "Ala.",
    "AK": "Alaska",
    "AZ": "Ariz.",
    "AR": "Ark.",
    "CA": "Cal.",
    "CO": "Colo.",
    "CT": "Conn.",
    "DE": "Del.",
    "FL": "Fla.",
    "GA": "Ga.",
    "HI": "Haw.",
    "ID": "Idaho",
    "IL": "Ill.",
    "IN": "Ind.",
    "IA": "Iowa",
    "KS": "Kan.",
    "KY": "Ky.",
    "LA": "La.",
    "ME": "Me.",
    "MD": "Md.",
    "MA": "Mass.",
    "MI": "Mich.",
    "MN": "Minn.",
    "MS": "Miss.",
    "MO": "Mo.",
    "MT": "Mont.",
    "NE": "Neb.",
    "NV": "Nev.",
    "NH": "N.H.",
    "NJ": "N.J.",
    "NM": "N.M.",
    "NY": "N.Y.",
    "NC": "N.C.",
    "ND": "N.D.",
    "OH": "Ohio",
    "OK": "Okla.",
    "OR": "Or.",
    "PA": "Pa.",
    "RI": "R.I.",
    "SC": "S.C.",
    "SD": "S.D.",
    "TN": "Tenn.",
    "TX": "Tex.",
    "UT": "Utah",
    "VT": "Vt.",
    "VA": "Va.",
    "WA": "Wash.",
    "WV": "W. Va.",
    "WI": "Wis.",
    "WY": "Wyo.",
    "DC": "D.C.",
}

STATE_NAME = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia",
}


def cid_v1_raw(data: bytes) -> str:
    """IPFS CIDv1, multibase base32, codec raw (0x55), sha2-256.

    Matches existing american_municipal_law html cids: hashing the UTF-8
    bytes of ``{gnis}_{doc_id}.json`` produces the sample ``bafkrei…`` values.
    """
    import base64
    digest = hashlib.sha256(data).digest()
    mh = bytes([0x12, 0x20]) + digest
    cid_bytes = bytes([0x01, 0x55]) + mh
    return "b" + base64.b32encode(cid_bytes).decode("ascii").lower().rstrip("=")


def cid_from_string(s: str) -> str:
    return cid_v1_raw(s.encode("utf-8"))


def law_cid(gnis: str, doc_id: str) -> str:
    return cid_from_string(f"{gnis}_{doc_id}.json")


def bluebook_cid(place_name: str, bb_state: str, title: str, history_note: str) -> str:
    return cid_from_string(f"{place_name}{bb_state}{title}{history_note}")


def slugify_client_name(name: str) -> str:
    s = name.strip().lower()
    s = s.replace("&", "and")
    s = s.replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def normalize_name(name: str) -> str:
    s = name.lower().replace("&", " and ")
    s = s.replace(".", " ").replace(",", " ").replace("'", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


_TYPE_PREFIX = re.compile(
    r"^(city|town|village|borough|charter township|township|county|parish|"
    r"municipality|consolidated government) of "
)
_TYPE_SUFFIX = re.compile(
    r" (county|parish|city|town|village|borough|township|municipality)$"
)


def name_variants(name: str) -> set[str]:
    n = normalize_name(name)
    out = {n}
    stripped = _TYPE_PREFIX.sub("", n).strip()
    out.add(stripped)
    out.add(_TYPE_SUFFIX.sub("", stripped).strip())
    out.add(_TYPE_SUFFIX.sub("", n).strip())
    if stripped and not stripped.endswith(" county"):
        out.add(stripped + " county")
    if stripped and not stripped.endswith(" parish"):
        out.add(stripped + " parish")
    out.discard("")
    return out


def looks_like_county(place_name: str) -> bool:
    n = normalize_name(place_name)
    if n.endswith(" county") or n.endswith(" parish") or n.startswith("county of"):
        return True
    if _TYPE_PREFIX.match(n):
        return False
    # Bare names in this corpus are almost always counties (Buncombe, Larimer).
    return True


def html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html or "")
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&sect;", "§", text)
    text = re.sub(r"&#167;", "§", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


HISTORYNOTE_RE = re.compile(
    r'(?is)<p[^>]*class="[^"]*historynote[^"]*"[^>]*>(.*?)</p>'
)


def extract_history_note_html_texts(html: str) -> list[str]:
    notes = []
    for m in HISTORYNOTE_RE.finditer(html or ""):
        t = html_to_text(m.group(1))
        t = t.strip(" ()")
        if t:
            notes.append(t)
    return notes


def split_history_entries(note: str) -> list[str]:
    note = note.strip().strip("()")
    if not note:
        return []
    parts = re.split(
        r";\s*(?=(?:Ord|Res|Mo|Code|Laws|Adopted|Comp)\b)",
        note,
        flags=re.I,
    )
    return [p.strip(" ;") for p in parts if p.strip(" ;")]


_DATE_RE = re.compile(r"\b(\d{1,2}-\d{1,2}-\d{2,4})\b")
_ORD_RE = re.compile(
    r"(?i)((?:Ord(?:inance)?|Res(?:olution)?|Mo)\.?\s*(?:No\.?)?\s*[^,;]*)"
)
_SECTION_RE = re.compile(r"(§+\s*[^,;]+)")


def parse_history_entry(entry: str) -> dict[str, str]:
    entry = re.sub(r"\s+", " ", entry).strip()
    date = ""
    dm = _DATE_RE.search(entry)
    if dm:
        date = dm.group(1)
    ordinance = ""
    om = _ORD_RE.search(entry)
    if om:
        ordinance = om.group(1).strip(" ,")
        ordinance = re.sub(r"\s+", " ", ordinance)
    section = ""
    sm = _SECTION_RE.search(entry)
    if sm:
        section = sm.group(1).strip()
    year = year_from_date(date)
    return {
        "history_note": entry,
        "date": date,
        "ordinance": ordinance,
        "section": section,
        "year": year,
        "enacted": year,
    }


def year_from_date(date: str) -> str:
    if not date:
        return ""
    parts = date.split("-")
    if len(parts) < 3:
        m = re.search(r"(19|20)\d{2}", date)
        return m.group(0) if m else ""
    yy = parts[-1]
    if len(yy) == 4:
        return yy
    try:
        n = int(yy)
    except ValueError:
        return ""
    # 2-digit: 00–30 → 2000s, else 1900s (corpus spans ~1970–2026).
    if n <= 30:
        return f"20{n:02d}"
    return f"19{n:02d}"


_TITLE_NUM_PATTERNS = [
    re.compile(r"(?i)^\s*(?:sec(?:tion)?\.?|§)\s*([0-9A-Za-z.\-]+)"),
    re.compile(r"(?i)^\s*chapters?\s+([0-9A-Za-z.\-]+(?:\s*[,–—\-]\s*[0-9A-Za-z.\-]+)*)"),
    re.compile(r"(?i)^\s*art(?:icle)?\.?\s+([IVXLCDM0-9A-Za-z.\-]+)"),
    re.compile(r"(?i)^\s*div(?:ision)?\.?\s+([0-9A-Za-z.\-]+)"),
    re.compile(r"(?i)^\s*title\s+([0-9A-Za-z.\-]+)"),
    re.compile(r"(?i)^\s*part\s+([IVXLCDM0-9A-Za-z.\-]+)"),
]


def title_num_from_title(title: str) -> str:
    t = (title or "").strip()
    for pat in _TITLE_NUM_PATTERNS:
        m = pat.search(t)
        if m:
            return m.group(1).rstrip(".")
    return ""


def chapter_num_from_chapter(chapter: str) -> str:
    m = re.search(r"(?i)^\s*(?:chapter|title|part)\s+([0-9A-Za-z.\-]+)", chapter or "")
    return m.group(1).rstrip(".") if m else ""


def polite_get_json(url: str, *, sleep: float = 0.4, retries: int = 5, timeout: int = 90) -> Any:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            time.sleep(sleep + random.uniform(0, sleep * 0.25))
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                wait = float(e.headers.get("Retry-After") or (2 ** attempt) * 2)
                time.sleep(wait)
                continue
            if e.code in (500, 502, 503, 504) and attempt < retries - 1:
                time.sleep((2 ** attempt) + random.uniform(0, 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep((2 ** attempt) + random.uniform(0, 1))
                continue
            raise
    raise last_err or RuntimeError(f"failed GET {url}")


def encode_qs(params: dict[str, Any]) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
