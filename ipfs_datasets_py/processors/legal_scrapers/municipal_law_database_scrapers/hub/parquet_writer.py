"""ZSTD parquet writer matching justicedao/american_municipal_law schema (minus pandas index)."""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HTML_COLUMNS = ["cid", "doc_id", "doc_order", "html_title", "html"]
CITATION_COLUMNS = [
    "bluebook_cid",
    "cid",
    "title",
    "title_num",
    "date",
    "public_law_num",
    "chapter",
    "chapter_num",
    "history_note",
    "ordinance",
    "section",
    "enacted",
    "year",
    "place_name",
    "state_name",
    "state_code",
    "bluebook_sate_code",  # dataset typo, keep
    "bluebook_citation",
]

STATE_NAME = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}

# Bluebook T10-style abbreviations
BLUEBOOK_STATE = {
    "AL": "Ala.", "AK": "Alaska", "AZ": "Ariz.", "AR": "Ark.", "CA": "Cal.",
    "CO": "Colo.", "CT": "Conn.", "DE": "Del.", "DC": "D.C.", "FL": "Fla.",
    "GA": "Ga.", "HI": "Haw.", "ID": "Idaho", "IL": "Ill.", "IN": "Ind.",
    "IA": "Iowa", "KS": "Kan.", "KY": "Ky.", "LA": "La.", "ME": "Me.",
    "MD": "Md.", "MA": "Mass.", "MI": "Mich.", "MN": "Minn.", "MS": "Miss.",
    "MO": "Mo.", "MT": "Mont.", "NE": "Neb.", "NV": "Nev.", "NH": "N.H.",
    "NJ": "N.J.", "NM": "N.M.", "NY": "N.Y.", "NC": "N.C.", "ND": "N.D.",
    "OH": "Ohio", "OK": "Okla.", "OR": "Or.", "PA": "Pa.", "RI": "R.I.",
    "SC": "S.C.", "SD": "S.D.", "TN": "Tenn.", "TX": "Tex.", "UT": "Utah",
    "VT": "Vt.", "VA": "Va.", "WA": "Wash.", "WV": "W. Va.", "WI": "Wis.",
    "WY": "Wyo.", "PR": "P.R.",
}

_B32 = "abcdefghijklmnopqrstuvwxyz234567"


def _b32encode(data: bytes) -> str:
    bits = 0
    value = 0
    out: List[str] = []
    for b in data:
        value = (value << 8) | b
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(_B32[(value >> bits) & 31])
    if bits:
        out.append(_B32[(value << (5 - bits)) & 31])
    return "".join(out)


def cid_v1_raw_sha256(text: str) -> str:
    """CIDv1 (base32, raw, sha2-256) of UTF-8 text. Matches dataset cids."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    cid_bytes = bytes([0x01, 0x55, 0x12, 0x20]) + digest
    return "b" + _b32encode(cid_bytes)


def html_cid(gnis: str, doc_id: str) -> str:
    return cid_v1_raw_sha256(f"{gnis}_{doc_id}.json")


def bluebook_cid(place_name: str, bb_state: str, title: str, history_note: str) -> str:
    return cid_v1_raw_sha256(f"{place_name}{bb_state}{title}{history_note}")


def strip_tags(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# A section token is digits with dot, hyphen, or colon separators.
# "sec" must be a whole word so "SECURE" is not section "URE".
# A later "Chapter 180" inside a section title is not the section number.
_SECTION_ATOM = r"\d+(?:[.\-:]\d+)*"
_LEADING_SECTION = re.compile(
    rf"^\s*({_SECTION_ATOM})(?:\s*[\-\u2013\u2014]+\s*({_SECTION_ATOM}))?\b"
)
_SECTION_KEYWORD = re.compile(
    rf"(?i)(?:§{{1,2}}|\bsec(?:tion|s)?\b)\.?\s*"
    rf"({_SECTION_ATOM})(?:\s*[\-\u2013\u2014]+\s*({_SECTION_ATOM}))?"
)
_ACTION_DATE = re.compile(r"(?i)\b(?:passed|adopted|effective|eff\.)[:\s]*")
# "12- 21-09" appears in real history notes. Spaces around the hyphens stay legal.
_MDY = re.compile(r"\b(\d{1,2})\s*-\s*(\d{1,2})\s*-\s*(\d{2,4})\b")
# A two-digit year is not placed in the future. 36 is 1936, 24 is 2024.
_TWO_DIGIT_CEILING = 2026
_ISO_DATE = re.compile(r"\b((?:18|19|20)\d{2})-(\d{2})-(\d{2})\b")
_MONTH_DATE = re.compile(
    r"(?i)\b((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?))[.]?\s+(\d{1,2}),\s+((?:18|19|20)\d{2})\b"
)
_MONTH_INDEX = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_CANONICAL_HREF = re.compile(
    r"(?i)<link\b[^>]*?\brel\s*=\s*[\"']canonical[\"'][^>]*?\bhref\s*=\s*[\"']([^\"']+)[\"']"
    r"|<link\b[^>]*?\bhref\s*=\s*[\"']([^\"']+)[\"'][^>]*?\brel\s*=\s*[\"']canonical[\"']"
)
_HREF = re.compile(r"""(?i)\bhref\s*=\s*["']([^"']+)["']""")
_CHROME_URL = re.compile(
    r"(?i)(?:xmlrpc\.php|/(?:feed|comments)(?:/|$)|wp-content/|wp-includes/|"
    r"fonts\.googleapis|fonts\.gstatic|gmpg\.org|googletagmanager|favicon|"
    r"\.css(?:\?|$)|\.js(?:\?|$)|\.(?:png|jpe?g|gif|svg|ico|webp|woff2?)(?:\?|$))"
)
_MUNICODE_ORIGIN = "https://library.municode.com"


def _section_from_match(match: re.Match[str]) -> str:
    start = match.group(1)
    end = match.group(2)
    if end:
        return f"{start}—{end}"
    return start


def extract_title_num(title: str) -> str:
    """Return the section number printed at the start of a chunk title.

    A leading ``186.04`` wins over a later chapter cross-reference.
    ``Sec.`` / ``Secs.`` / ``§`` must introduce a digit. A word that merely
    begins with ``sec`` is not a section.
    """

    text = title or ""
    match = _LEADING_SECTION.match(text)
    if match:
        return _section_from_match(match)
    match = _SECTION_KEYWORD.search(text)
    if match:
        return _section_from_match(match)
    return ""


def extract_chapter_num(chapter: str) -> str:
    m = re.search(r"(?i)\bchapter\s+([0-9A-Za-z]+(?:[.\-][0-9A-Za-z]+)*)", chapter or "")
    return m.group(1) if m else ""


def _year_from_short(yy: int) -> int:
    year = 2000 + yy
    if year > _TWO_DIGIT_CEILING:
        return 1900 + yy
    return year


def _iso_from_parts(month: int, day: int, year: int) -> str:
    if not (1 <= month <= 12 and 1 <= day <= 31 and 1800 <= year <= 2100):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def _iso_from_year_token(year_s: str, month: int, day: int) -> str:
    if len(year_s) == 4:
        year = int(year_s)
    elif len(year_s) == 2:
        year = _year_from_short(int(year_s))
    else:
        return ""
    return _iso_from_parts(month, day, year)


def _date_in_window(window: str) -> Optional[Tuple[str, str]]:
    match = _MDY.search(window)
    if match:
        iso = _iso_from_year_token(match.group(3), int(match.group(1)), int(match.group(2)))
        if iso:
            return match.group(0), iso
    match = _MONTH_DATE.search(window)
    if match:
        month = _MONTH_INDEX.get(match.group(1).lower().rstrip("."))
        if month is not None:
            iso = _iso_from_parts(month, int(match.group(2)), int(match.group(3)))
            if iso:
                return match.group(0), iso
    return None


def _trailing_passage(text: str) -> Optional[Tuple[str, str]]:
    """A citation date sitting at the end of a note, after a comma or ``of``.

    ``Ord. No. 75-02, 4-21-75`` and ``Amd. of 7-9-13`` carry the date there.
    ``Ord. 98-6-61`` and ``§ 12-15-10`` are not dates.
    """

    match: Optional[re.Match[str]] = None
    for candidate in _MDY.finditer(text):
        match = candidate
    if match is None or text[match.end() :].strip(" .;"):
        return None
    prefix = text[: match.start()]
    if re.search(r"(?i)(?:§|secs?\.?|sections?)\s*$", prefix):
        return None
    if not re.search(r"(?i)(?:,\s*|of\s+)$", prefix):
        return None
    iso = _iso_from_year_token(match.group(3), int(match.group(1)), int(match.group(2)))
    if not iso:
        return None
    return match.group(0), iso


def passage_dates(note: str) -> List[Tuple[str, str]]:
    """Return ``(raw token, YYYY-MM-DD)`` for each passage or effective date.

    Ordinance numbers such as ``98-6-61`` are not dates. A token after
    Passed, Adopted, or Effective is read first. Otherwise a month-name date,
    or a trailing ``, 4-21-75`` / ``of 7-9-13`` citation date. A bare
    two-digit year is not a date.
    """

    text = note or ""
    found: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for match in _ACTION_DATE.finditer(text):
        parsed = _date_in_window(text[match.end(): match.end() + 48])
        if parsed is None or parsed[1] in seen:
            continue
        seen.add(parsed[1])
        found.append(parsed)
    if found:
        return found
    match = _MONTH_DATE.search(text)
    if match:
        month = _MONTH_INDEX.get(match.group(1).lower().rstrip("."))
        if month is not None:
            iso = _iso_from_parts(month, int(match.group(2)), int(match.group(3)))
            if iso:
                return [(match.group(0), iso)]
    trailing = _trailing_passage(text)
    if trailing:
        return [trailing]
    return []


def adoption_line_dates(plain: str) -> List[Tuple[str, str]]:
    """Adoption dates printed on a title page that has no history note.

    ``current through ... passed <date>`` is a supplement stamp, not the
    effective date of the chunk.
    """

    text = plain or ""
    found: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for match in _ACTION_DATE.finditer(text):
        prefix = text[max(0, match.start() - 48) : match.start()]
        window = text[match.end() : match.end() + 48]
        if re.search(r"(?i)\bthrough\b", prefix):
            continue
        folded = window.lstrip().lower()
        if folded.startswith(("through", "after", "before", "prior", "since")):
            continue
        # A supplement-table column header ("Date Adopted Include/Omit") is not
        # an adoption. "Date Adopted: October 16, 1990" still is.
        if re.search(r"(?i)\bdate$", prefix.rstrip()):
            lead = window.lstrip(" :")
            if _MDY.match(lead) is None and _MONTH_DATE.match(lead) is None:
                continue
        parsed = _date_in_window(window)
        if parsed is None or parsed[1] in seen:
            continue
        seen.add(parsed[1])
        found.append(parsed)
    return found


def parse_year(date_s: str) -> str:
    """Year of one date token. An ordinance number is not a year."""

    if not date_s:
        return ""
    dates = passage_dates(date_s)
    if dates:
        return dates[0][1][:4]
    match = _MDY.search(date_s)
    if match:
        iso = _iso_from_year_token(match.group(3), int(match.group(1)), int(match.group(2)))
        if iso:
            return iso[:4]
    match = _ISO_DATE.search(date_s)
    if match:
        iso = _iso_from_parts(int(match.group(2)), int(match.group(3)), int(match.group(1)))
        if iso:
            return iso[:4]
    match = _MONTH_DATE.search(date_s)
    if match:
        return match.group(3)
    return ""


def _http_url(href: str) -> Optional[str]:
    text = html.unescape(href or "").strip()
    if text.startswith("//"):
        text = "https:" + text
    if not text.startswith(("http://", "https://")):
        return None
    return text.split("#", 1)[0]


def source_url_from_html(raw: str) -> Optional[str]:
    """Return the chunk's own URL, or None when the HTML has no source link.

    A ``rel=canonical`` document URL wins. Otherwise the first Municode
    ``/codes/...`` path is prefixed with ``https://library.municode.com``.
    Stylesheets, feeds, and state-code cross-references are not the source.
    """

    blob = raw or ""
    match = _CANONICAL_HREF.search(blob)
    if match:
        url = _http_url(match.group(1) or match.group(2) or "")
        if url and _CHROME_URL.search(url) is None:
            return url
    for href in _HREF.findall(blob):
        text = html.unescape(href).strip()
        absolute = _http_url(text)
        path = (absolute or text).split("?", 1)[0].split("#", 1)[0]
        if path.startswith("/codes/"):
            return _MUNICODE_ORIGIN + path
        if (
            absolute
            and "library.municode.com/codes/" in absolute
            and _CHROME_URL.search(absolute) is None
        ):
            return absolute.split("?", 1)[0]
    return None


def _split_history_notes(blob: str) -> List[str]:
    blob = blob.strip()
    if blob.startswith("(") and blob.endswith(")"):
        blob = blob[1:-1].strip()
    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    for ch in blob:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == ";" and depth == 0:
            piece = "".join(buf).strip(" ;")
            if piece:
                parts.append(piece)
            buf = []
        else:
            buf.append(ch)
    piece = "".join(buf).strip(" ;")
    if piece:
        parts.append(piece)
    return parts or ([blob] if blob else [])


def extract_history_notes(html: str) -> List[str]:
    """Pull Municode history notes from section HTML."""
    if not html:
        return []
    notes: List[str] = []
    for cls in (
        r"historynote\d*",
        r"history-note",
        r"refeditor\d*",
        r"refhistory\d*",
        r"refmanual\d*",
    ):
        for m in re.finditer(
            rf'<p[^>]*class="[^"]*{cls}[^"]*"[^>]*>(.*?)</p>',
            html,
            flags=re.I | re.S,
        ):
            plain = strip_tags(m.group(1))
            if re.search(r"(?i)\b(ord\.|res\.|ord\b)", plain):
                notes.extend(_split_history_notes(plain))
    if not notes:
        # Real notes often start with a code cross-reference or "EOrd.", not "Ord.".
        # Keep a parenthetical only when it carries a passage or effective date.
        plain = strip_tags(html)
        for m in re.finditer(r"\(([^()]{3,400})\)", plain):
            blob = m.group(1)
            if re.search(r"(?i)\b(?:passed|adopted|effective|eff\.)\b", blob):
                notes.extend(_split_history_notes(blob))
        if not notes:
            for m in re.finditer(
                r"\(((?:Ord\.|Res\.)[^()]{3,180})\)",
                plain,
            ):
                notes.extend(_split_history_notes(m.group(1)))
    # de-dupe preserving order
    seen = set()
    out = []
    for n in notes:
        n = re.sub(r"\s+", " ", n).strip(" ;")
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def parse_history_fields(note: str) -> Dict[str, str]:
    ordinance = ""
    section = ""
    date_s = ""
    m = re.search(r"((?:Ord\.|Res\.)(?:\s+No\.)?[^,;]*)", note)
    if m:
        ordinance = m.group(1).strip(" ,;")
    m = re.search(r"(§+\s*[^,;]+)", note)
    if m:
        section = m.group(1).strip(" ,;")
    dates = passage_dates(note)
    if dates:
        date_s = dates[0][0]
        year = dates[0][1][:4]
    else:
        year = ""
    return {
        "history_note": note,
        "ordinance": ordinance,
        "section": section,
        "date": date_s,
        "year": year,
        "enacted": year,
    }


def _code_kind(place_name: str) -> str:
    n = (place_name or "").lower()
    if "county" in n and "city" not in n:
        return "County Code"
    return "Municipal Code"


def format_bluebook(
    place_name: str,
    bb_state: str,
    title_num: str,
    year: str,
    kind: str,
) -> str:
    parts = [f"{place_name}, {bb_state}, {kind}"]
    if title_num:
        parts.append(f"§ {title_num}")
    cite = ", ".join(parts) if title_num else f"{place_name}, {bb_state}, {kind}"
    if year:
        cite = f"{cite} ({year})"
    return cite


def docs_to_html_rows(docs: Sequence[Dict[str, Any]], gnis: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for doc in docs:
        doc_id = str(doc.get("Id") or doc.get("doc_id") or "")
        if not doc_id:
            continue
        title_html = doc.get("TitleHtml") or ""
        title_plain = doc.get("Title") or strip_tags(title_html)
        if not title_html and title_plain:
            title_html = f'<div class="chunk-title">{title_plain}</div>'
        html = doc.get("Content") or '<div class="chunk-content"></div>'
        if html and 'class="chunk-content"' not in html:
            html = f'<div class="chunk-content">{html}</div>'
        try:
            order = int(doc.get("DocOrderId") or doc.get("doc_order") or 0)
        except (TypeError, ValueError):
            order = 0
        if order < 0:
            order = 0
        rows.append(
            {
                "cid": html_cid(str(gnis), doc_id),
                "doc_id": doc_id,
                "doc_order": order,
                "html_title": title_html,
                "html": html,
                "_title": title_plain,
            }
        )
    rows.sort(key=lambda r: (r["doc_order"], r["doc_id"]))
    return rows


def html_rows_to_citation_rows(
    html_rows: Sequence[Dict[str, Any]],
    *,
    place_name: str,
    state_code: str,
) -> List[Dict[str, Any]]:
    state_code = (state_code or "").upper()
    state_name = STATE_NAME.get(state_code, state_code)
    bb_state = BLUEBOOK_STATE.get(state_code, state_code)
    kind = _code_kind(place_name)
    chapter = ""
    chapter_num = ""
    out: List[Dict[str, Any]] = []
    for row in html_rows:
        title = row.get("_title") or strip_tags(row.get("html_title") or "")
        if re.match(r"(?i)^\s*chapter\s+", title):
            chapter = title
            chapter_num = extract_chapter_num(chapter)
        title_num = extract_title_num(title)
        notes = extract_history_notes(row.get("html") or "")
        if not notes:
            notes = [""]
        for note in notes:
            parsed = parse_history_fields(note) if note else {
                "history_note": "", "ordinance": "", "section": "",
                "date": "", "year": "", "enacted": "",
            }
            year = parsed["year"]
            cite = format_bluebook(place_name, bb_state, title_num, year, kind)
            out.append(
                {
                    "bluebook_cid": bluebook_cid(place_name, bb_state, title, parsed["history_note"]),
                    "cid": row["cid"],
                    "title": title,
                    "title_num": title_num,
                    "date": parsed["date"],
                    "public_law_num": "NA",
                    "chapter": chapter,
                    "chapter_num": chapter_num,
                    "history_note": parsed["history_note"],
                    "ordinance": parsed["ordinance"],
                    "section": parsed["section"],
                    "enacted": parsed["enacted"],
                    "year": year,
                    "place_name": place_name,
                    "state_name": state_name,
                    "state_code": state_code,
                    "bluebook_sate_code": bb_state,
                    "bluebook_citation": cite,
                }
            )
    return out


def _compression() -> str:
    pa, _pq = _ensure_pyarrow()
    try:
        if pa.Codec.is_available("zstd"):
            return "zstd"
    except Exception:
        pass
    return "snappy"


def _ensure_pyarrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        return pa, pq
    except ImportError as e:
        raise RuntimeError(
            "pyarrow is required. Use /workspace/muni/.venv or set PYTHONPATH to its site-packages."
        ) from e


def write_html_parquet(path: Path, rows: Sequence[Dict[str, Any]]) -> int:
    pa, pq = _ensure_pyarrow()
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "cid": [r["cid"] for r in rows],
            "doc_id": [r["doc_id"] for r in rows],
            "doc_order": pa.array([int(r["doc_order"]) for r in rows], type=pa.uint32()),
            "html_title": [r["html_title"] for r in rows],
            "html": [r["html"] for r in rows],
        }
    )
    pq.write_table(table, str(path), compression=_compression())
    return table.num_rows


def write_citation_parquet(path: Path, rows: Sequence[Dict[str, Any]]) -> int:
    pa, pq = _ensure_pyarrow()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {col: [r.get(col, "") if r.get(col) is not None else "" for r in rows] for col in CITATION_COLUMNS}
    table = pa.table(data)
    pq.write_table(table, str(path), compression=_compression())
    return table.num_rows


def write_metadata(path: Path, place_name: str, state_code: str, total_sections: int, last_updated_ms: Optional[int] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if last_updated_ms is None:
        last_updated_ms = int(time.time() * 1000)
    path.write_text(
        json.dumps(
            {
                "place_name": place_name,
                "state_code": state_code,
                "total_sections": int(total_sections),
                "last_updated": int(last_updated_ms),
            },
            separators=(",", ":"),
        )
        + "\n"
    )


def write_jurisdiction(
    out_root: Path,
    gnis: str,
    html_rows: Sequence[Dict[str, Any]],
    place_name: str,
    state_code: str,
    last_updated_ms: Optional[int] = None,
) -> Dict[str, Any]:
    gnis = str(gnis)
    data_dir = Path(out_root) / "american_law" / "data"
    html_path = data_dir / f"{gnis}_html.parquet"
    cite_path = data_dir / f"{gnis}_citation.parquet"
    meta_path = data_dir / "metadata" / f"{gnis}.json"
    n_html = write_html_parquet(html_path, html_rows)
    cite_rows = html_rows_to_citation_rows(html_rows, place_name=place_name, state_code=state_code)
    n_cite = write_citation_parquet(cite_path, cite_rows)
    write_metadata(meta_path, place_name, state_code, n_html, last_updated_ms)
    return {
        "gnis": gnis,
        "html_rows": n_html,
        "citation_rows": n_cite,
        "html_path": str(html_path),
        "citation_path": str(cite_path),
        "metadata_path": str(meta_path),
    }


def validate_html_schema(path: Path, sample_path: Path) -> Dict[str, Any]:
    pa, pq = _ensure_pyarrow()
    got = pq.read_table(str(path))
    sample = pq.read_table(str(sample_path))
    sample_cols = [c for c in sample.column_names if c != "__index_level_0__"]
    got_cols = list(got.column_names)
    ok = got_cols == sample_cols
    type_ok = True
    notes = []
    if got_cols != sample_cols:
        notes.append(f"columns {got_cols} != sample {sample_cols}")
    for name in sample_cols:
        if name not in got.schema.names:
            type_ok = False
            continue
        st = sample.schema.field(name).type
        gt = got.schema.field(name).type
        if str(st) != str(gt):
            # uint32 vs int64 still acceptable for doc_order if values fit
            notes.append(f"type {name}: got {gt} sample {st}")
            if name != "doc_order":
                type_ok = False
    return {
        "ok": ok and ("__index_level_0__" not in got_cols),
        "columns": got_cols,
        "sample_columns_minus_index": sample_cols,
        "types_ok": type_ok,
        "compression_note": f"written with {_compression()}",
        "notes": notes,
        "rows": got.num_rows,
    }
