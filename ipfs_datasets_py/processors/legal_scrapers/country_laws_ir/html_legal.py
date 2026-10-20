"""Pull operative legal text out of municipal HTML chunks.

The scrapers store a page as ``<div class="chunk-content">``. The flattened
``text`` column still starts with letterhead, attendance rolls, and cover
sheets, and the embedder only reads the first 4,000 characters of the body.
This keeps the operative text and leaves a page unchanged when the cut would
drop most of it.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_LEGAL = re.compile(
    r"(?i)("
    r"§|"
    r"\bart\.?\s*\d|"
    r"\barticles?\s+\d|"
    r"\bartikel\b|"
    r"\bpasal\b|"
    r"\bayat\b|"
    r"\bmenimbang\b|"
    r"\bmemutuskan\b|"
    r"\bmenetapkan\b|"
    r"\bperaturan\b|"
    r"\bconsidérant\b|"
    r"\bdécide\b|"
    r"\bdélibère\b|"
    r"\bvu (?:le|la|les|l['’])|"
    r"\brundschreiben\b|"
    r"\bverordnung\b|"
    r"\bdecreto\b|"
    r"\bdelibera\b|"
    r"\brèglement\b|"
    r"\barrêté\b|"
    r"\brésumé\s*:"
    r")"
)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_PHONE = re.compile(
    r"(?i)\b(?:tel\.?|telefon|téléphone|telephone|cellulaire|télécopieur|telefax|fax)\b"
)
_TAX = re.compile(
    r"(?i)\b(?:steuernr|mwst\.?|codice fiscale|partita iva|npwp|momsnr)\b"
)
_POSTAL = re.compile(
    r"(?i)\b(?:straße|strasse|via |rue |väg|gatan|landhaus|palazzo)\b"
)
_TOC = re.compile(r"\.{4,}\s*\d{1,4}\s*$")
_PAGE = re.compile(r"^\d{1,4}$")
_PAGE_PREFIX = re.compile(r"^(\d{1,3})\s+(?=[A-ZÀ-ÖØ-Þ]{4,}\b)")
_LABEL = re.compile(
    r"(?i)^(?:"
    r"dokumentnamn|gäller\s+fr.*|gäller\s+t.*|diarienummer|fastställd(?:\s+av)?|"
    r"dokumentansvar\w*|handläggare|dokumenthistorik|version|tidigare beslut|"
    r"innehållsförteckning|rapporteur|secrétaire|commission|avis"
    r")\s*:?\s*$"
)
_ATTEND = re.compile(
    r"(?i)\b(?:étaient présents|etaient présents|étaient absents|etaient absents|"
    r"procurations de vote|secrétaire\s*:)"
)
_START = re.compile(
    r"(?i)("
    r"résumé\s*:|"
    r"\ble présent\b|"
    r"\bvu (?:le|la|les|l['’])|"
    r"\bconsidérant\b|"
    r"\barticles?\s+\d|"
    r"\bdécide\b|"
    r"\brundschreiben\b|"
    r"\bperaturan\b|"
    r"\bmenimbang\b"
    r")"
)
_ROLL = re.compile(
    r"(?i)\b(?:étaient présents|etaient présents|présidence de|"
    r"conseillers municipaux en exercice|procurations de vote)\b"
)
_ROLE = re.compile(
    r"(?i)\b(?:kommundirektör|handläggare|utredare|föreningssamordnare|dokumentansvar)\b"
)
_IDLINE = re.compile(
    r"^(?:[A-Z]{1,6}/\d{4}:\d+|\d{8}-\d+(?:\.\d+)?|\d{4}-\d{2}-\d{2})$"
)
_EMAIL_ONLY = re.compile(r"(?i)(?:nur mittels|solo via)\s+e-?mail")


class _Paragraphs(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._buf: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        if tag in {"p", "br", "div", "li", "h1", "h2", "h3", "tr"} and self._skip == 0:
            self._flush()

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3"} and self._skip == 0:
            self._flush()

    def handle_data(self, data):
        if self._skip == 0 and data:
            self._buf.append(data)

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        self._buf.clear()
        if text:
            self.parts.append(text)

    def close(self):
        super().close()
        self._flush()


def _paragraphs(html: str, fallback: str) -> list[str]:
    if html and "<" in html:
        parser = _Paragraphs()
        try:
            parser.feed(html)
            parser.close()
        except Exception:
            parser.parts = []
        if parser.parts:
            return parser.parts
    raw = fallback or html or ""
    parts = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines()]
    return [part for part in parts if part]


def _is_chrome(text: str) -> bool:
    if not text:
        return True
    if _PAGE.fullmatch(text) or _TOC.search(text) or _LABEL.fullmatch(text):
        return True
    if _EMAIL_ONLY.search(text) and len(text) < 80:
        return True
    if _IDLINE.fullmatch(text):
        return True
    if _ROLE.search(text) and len(text) < 140 and _LEGAL.search(text) is None:
        return True
    if _ATTEND.search(text) and _START.search(text) is None and _LEGAL.search(text) is None:
        return True
    if _LEGAL.search(text):
        return False
    if len(text) > 280:
        return False
    if _EMAIL.search(text) or _URL.search(text) or _PHONE.search(text) or _TAX.search(text):
        return True
    if _POSTAL.search(text) and len(text) < 140:
        return True
    return False


def _leading_cover(text: str) -> bool:
    """Short cover-sheet line with no operative marker."""
    if _LEGAL.search(text) or _is_chrome(text):
        return False
    if len(text) > 90:
        return False
    words = text.split()
    return len(words) <= 14


def _trim_blob(text: str) -> str:
    match = _START.search(text)
    if match is None or match.start() < 60:
        return text
    head = text[: match.start()]
    if _ROLL.search(head) or _ATTEND.search(head) or re.search(r"(?i)\b(?:mairie|rapporteur)\b", head):
        return text[match.start() :].strip()
    return text


def _strip_page_prefix(text: str) -> str:
    match = _PAGE_PREFIX.match(text)
    if match is None or int(match.group(1)) > 40:
        return text
    return text[match.end() :].strip()


def extract_municipal_legal_text(html: str, fallback: str = "") -> str:
    """Return operative text. ``fallback`` is the flattened page text."""
    base = re.sub(r"\s+", " ", (fallback or "")).strip()
    paragraphs = [_trim_blob(part) for part in _paragraphs(html or "", fallback or "")]
    start = 0
    while start < len(paragraphs) and (
        _is_chrome(paragraphs[start]) or _leading_cover(paragraphs[start])
    ):
        start += 1
    kept: list[str] = []
    for part in paragraphs[start:]:
        if _is_chrome(part):
            continue
        part = _strip_page_prefix(part)
        if part:
            kept.append(part)
    cleaned = "\n".join(kept).strip()
    plain = (fallback or "").strip()
    if not cleaned:
        return plain
    if plain and len(plain) > 400 and len(cleaned) < int(0.2 * len(plain)):
        return plain
    return cleaned
