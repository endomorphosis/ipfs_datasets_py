"""CodePublishing (codepublishing.com) scraper via Common Crawl WARC records.

CodePublishing blocks/tarpits our egress IP, but the CC pointer index
(endomorphosis/common_crawl_municipal_index) holds status-200 WARC captures
for ~278 of 281 codepublishing jurisdictions (landing + title + chapter pages
from 2021-2022 crawls), fetchable with plain HTTP range requests to
data.commoncrawl.org (no throttle observed).

Site structure (static mod_perl HTML, verified 2026-09-16):
- Landing: {base}/  e.g. https://www.codepublishing.com/WA/BonneyLake/
  links to title pages: html/{City}01/{City}01.html  ("Title 1 GENERAL PROVISIONS")
- Title page: links to chapter pages: {City}0101.html ("1.01 Code Adoption Ordinance")
- Chapter page: full section text; sections are
  <h3 class="Cite" id="1.01.020"><a name="1.01.020">1.01.020</a> Title text.</h3>
  followed by <p class="P1">...</p> paragraphs, history notes inline as
  "(Ord. 482 \u00a7 1, 1979)."

Usage: build the URL map once with the pointers parquet
(see municipal_scrape/codepublishing_urlmap.json), then
scrape_jurisdiction(url, url_map=..., sleep=...).
"""

from __future__ import annotations

import gzip
import html as _html
import re
import time
import urllib.parse
import urllib.request

_CC_DATA = "https://data.commoncrawl.org"
_UA = "JusticeDAO-MuniBot/1.0 (municipal law archive recovery; contact: research)"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ANY_LINK_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.S | re.I,
)
_TITLE_PATH_RE = re.compile(
    r"^(?:#\!/)?(?:html/)?([A-Za-z0-9_]+)/([A-Za-z0-9_]+)\.html$"
)
_CHAPTER_LINK_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']*?[A-Za-z0-9_]+\.html)(?:#[^"\']*)?["\'][^>]*>(.*?)</a>',
    re.S | re.I,
)
_SECTION_RE = re.compile(
    r'<h3 class="Cite"[^>]*><a name="([^"]+)">.*?</a>(.*?)</h3>(.*?)(?=<h3 class="Cite"|$)',
    re.S | re.I,
)
_HEADING_RE = re.compile(
    r"<h[12][^>]*>(.*?)</h[12]>", re.S | re.I,
)


def _clean(raw: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", raw or "", flags=re.I)
    return _WS_RE.sub(" ", _html.unescape(_TAG_RE.sub("", text))).strip(" \t\r\n\xa0-")


def _dechunk(body: bytes) -> bytes:
    if not re.match(rb"^[0-9a-fA-F]{1,6}\r\n", body):
        return body
    out = bytearray()
    i = 0
    for _ in range(100000):
        j = body.find(b"\r\n", i)
        if j < 0:
            break
        try:
            size = int(body[i:j].strip().split(b";")[0], 16)
        except ValueError:
            break
        if size == 0:
            break
        out += body[j + 2:j + 2 + size]
        i = j + 2 + size + 2
    return bytes(out) if out else body


def fetch_warc(warc_filename: str, offset: int, length: int, *, timeout: int = 60) -> str | None:
    url = f"{_CC_DATA}/{warc_filename}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UA, "Range": f"bytes={offset}-{offset + length - 1}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
    except Exception:
        return None
    try:
        record = gzip.decompress(data)  # WARC segment-level compression
    except Exception:
        record = data
    # WARC record = WARC headers, then the captured HTTP message
    _, _, http_msg = record.partition(b"\r\n\r\n")
    if not http_msg:
        return None
    http_head, _, body = http_msg.partition(b"\r\n\r\n")
    head_l = http_head.lower()
    # Some captures store the HTTP body itself gzipped
    if b"content-encoding: gzip" in head_l or b"x-crawler-content-encoding: gzip" in head_l:
        try:
            maybe = gzip.decompress(body)
            # sanity: decompressed body should look like text/markup
            if maybe[:200].strip()[:1] in (b"<", b"{", b""):
                body = maybe
        except Exception:
            pass
    body = _dechunk(body)
    try:
        return body.decode("utf-8", "replace")
    except Exception:
        return None


def _resolve_codepub_link(href: str, page_url: str) -> str:
    """Resolve a codepublishing href, translating #!/ links to html/ paths."""
    href = href.replace("#!/", "html/")
    href = href.split("#")[0].split("?")[0]
    return urllib.parse.urljoin(page_url, href)


def parse_landing(html: str, page_url: str) -> list[tuple[str, str]]:
    """Return [(title_label, title_url)] in page order."""
    out, seen = [], set()
    for m in _ANY_LINK_RE.finditer(html or ""):
        href, label = m.group(1), _clean(m.group(2))
        # strip any leading site path, keeping the #!/ or html/ tail
        tail = href
        i = tail.find("#!/")
        if i >= 0:
            tail = tail[i:]
        else:
            j = tail.find("html/")
            tail = tail[j:] if j >= 0 else tail.rsplit("/", 1)[-1]
        if not _TITLE_PATH_RE.match(tail):
            continue
        url = _resolve_codepub_link(tail, page_url)
        if url in seen:
            continue
        seen.add(url)
        out.append((label or tail, url))
    return out


_CHAPTER_FILE_RE = re.compile(r"^([A-Za-z0-9_]*[0-9]{4,})\.html$")


def parse_title_page(html: str, page_url: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (title_heading, [(chapter_label, chapter_url)])."""
    heading = ""
    m = _HEADING_RE.search(html or "")
    if m:
        heading = _clean(m.group(1))
    out, seen = [], set()
    for m in _ANY_LINK_RE.finditer(html or ""):
        href, label = m.group(1), _clean(m.group(2))
        tail = href.rsplit("/", 1)[-1].split("#")[0].split("?")[0]
        cm = _CHAPTER_FILE_RE.match(tail)
        if not cm:
            continue
        url = _resolve_codepub_link(href, page_url)
        if url in seen:
            continue
        seen.add(url)
        out.append((label or cm.group(1), url))
    return heading, out


def parse_chapter_page(html: str) -> tuple[str, list[tuple[str, str, str]]]:
    """Return (chapter_heading, [(section_no, section_title, section_html)])."""
    heading = ""
    m = _HEADING_RE.search(html or "")
    if m:
        heading = _clean(m.group(1))
    sections = []
    for m in _SECTION_RE.finditer(html or ""):
        sec_no = m.group(1).strip()
        sec_title = _clean(m.group(2))
        sec_body = m.group(3).strip()
        sec_html = (
            f'<h3 class="chunk-title">{_html.escape(sec_no)}'
            f'{(" " + _html.escape(sec_title)) if sec_title else ""}</h3>'
            f'<div class="chunk-content">{sec_body}</div>'
        )
        sections.append((sec_no, sec_title, sec_html))
    return heading, sections


def fetch_wayback(page_url: str, *, year: str = "2023", timeout: int = 120) -> str | None:
    """Fetch the archived copy of page_url nearest to `year` from the Wayback Machine.

    Uses the `id_` modifier so the response is the original HTML (no toolbar).
    Wayback sometimes serves the original gzipped bytes; those are decompressed.
    Returns None on any failure.
    """
    wb_url = f"https://web.archive.org/web/{year}id_/{page_url}"
    req = urllib.request.Request(wb_url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return None
            raw = r.read()
            if raw[:2] == b"\x1f\x8b":
                try:
                    raw = gzip.decompress(raw)
                except Exception:
                    return None
            return raw.decode("utf-8", "replace")
    except Exception:
        return None


def _pointer_for(url_map: dict, gnis: str, url: str) -> dict | None:
    entry = (url_map or {}).get(str(gnis))
    if not entry:
        return None
    for row in entry.get("urls") or []:
        if row.get("url") == url:
            return row
    # fall back: same path ignoring scheme/www, and with/without the html/ segment
    # (codepublishing migrated between #!/City01/ and html/City01/ URL schemes)
    cands = {_norm_url(url)}
    host_path = re.sub(r"^https?://[^/]+", "", url, flags=re.I)
    if "/html/" in host_path:
        cands.add(_norm_url(url.replace("/html/", "/", 1)))
    else:
        parts = host_path.strip("/").split("/")
        if len(parts) >= 2:
            cands.add(_norm_url(re.sub(
                r"^https?://[^/]+", "", url, flags=re.I).replace(
                    "/" + parts[-2] + "/", "/html/" + parts[-2] + "/", 1)))
    for row in entry.get("urls") or []:
        if _norm_url(row.get("url") or "") in cands:
            return row
    # last resort: same host + matching filename tail
    tail = (url.rstrip("/").rsplit("/", 1)[-1] or "").lower()
    host = _norm_url(url).split("/", 1)[0]
    if tail:
        for row in entry.get("urls") or []:
            ru = row.get("url") or ""
            if (ru.rstrip("/").rsplit("/", 1)[-1].lower() == tail
                    and _norm_url(ru).split("/", 1)[0] == host):
                return row
    return None


def _norm_url(u: str) -> str:
    u = re.sub(r"^https?://(www\.)?", "", u or "", flags=re.I).rstrip("/")
    return u.lower()


def _scrape_jurisdiction_core(
    url: str,
    gnis: str,
    url_map: dict | None,
    get,
) -> dict:
    """Shared scrape body: landing -> titles -> chapters -> sections, plus the
    chapter-direct fallback over the URL map. `get(page_url)` supplies page HTML."""
    base = re.match(r"(https?://[^/]*codepublishing\.com/[^,;\s]+)", url or "", re.I)
    if not base:
        return {"ok": False, "error": f"not a codepublishing URL: {url}", "docs": []}
    base_url = base.group(1).rstrip("/") + "/"

    landing_html = get(base_url)
    if not landing_html:
        # try alternate scheme/www form present in the map
        entry = (url_map or {}).get(str(gnis), {})
        alt = (entry.get("base") or "").rstrip("/") + "/"
        if alt and _norm_url(alt) != _norm_url(base_url):
            landing_html = get(alt)
            if landing_html:
                base_url = alt
    # A missing landing capture no longer fails: the URL-map chapter fallback
    # below can still recover the jurisdiction.

    docs: list[dict] = []
    order = 0
    seen_sec: set[str] = set()

    def add_chapter_sections(
        chap_label: str,
        chap_url: str,
        chap_html: str,
        title_label: str = "",
        title_heading: str = "",
    ) -> None:
        nonlocal order
        chap_heading, sections = parse_chapter_page(chap_html)
        for sec_no, sec_title, sec_html in sections:
            key = re.sub(r"\s+", "", sec_no).lower()
            if key in seen_sec:
                continue
            seen_sec.add(key)
            order += 1
            doc_id = f"{title_label}::{sec_no}" if title_label else sec_no
            docs.append(
                {
                    "Id": doc_id,
                    "doc_id": doc_id,
                    "Title": f"{sec_no} {sec_title}".strip(),
                    "TitleHtml": "",
                    "Content": sec_html,
                    "DocOrderId": order,
                    "doc_order": order,
                    "chapter": chap_heading or chap_label,
                    "title_heading": title_heading or title_label,
                }
            )

    titles = parse_landing(landing_html, base_url) if landing_html else []
    for title_label, title_url in titles:
        title_html = get(title_url)
        if not title_html:
            continue
        title_heading, chapters = parse_title_page(title_html, title_url)
        for chap_label, chap_url in chapters:
            chap_html = get(chap_url)
            if not chap_html:
                continue
            add_chapter_sections(chap_label, chap_url, chap_html, title_label, title_heading)

    if not docs:
        # Fallback: some captures' landing pages are mobile-redirect stubs
        # ("Kirkland Codes and Laws" -> mobile/) with no title links. Harvest
        # chapter pages straight from the URL map instead.
        entry = (url_map or {}).get(str(gnis), {})
        base_p = _norm_url(base_url)
        seen_url: set[str] = set()
        for row in entry.get("urls") or []:
            u = row.get("url") or ""
            nu = _norm_url(u)
            if not nu.startswith(base_p) or nu == base_p:
                continue
            if not nu.endswith(".html"):
                continue
            tail = nu.rsplit("/", 1)[-1]
            if tail in ("disclaimer.html", "index.html"):
                continue
            if nu in seen_url:
                continue
            seen_url.add(nu)
            chap_html = get(u)
            if not chap_html:
                continue
            add_chapter_sections("", u, chap_html)
    if not docs:
        return {"ok": False, "error": "parsed zero sections", "docs": []}
    return {"ok": True, "docs": docs, "title_count": len(titles)}


def scrape_jurisdiction(
    url: str,
    gnis: str = "",
    url_map: dict | None = None,
    sleep: float = 0.4,
) -> dict:
    """Scrape one CodePublishing jurisdiction from CC WARC captures."""

    def get(page_url: str) -> str | None:
        ptr = _pointer_for(url_map or {}, gnis, page_url)
        if not ptr:
            return None
        for attempt in range(3):
            time.sleep(sleep)
            html = fetch_warc(ptr["warc_filename"], ptr["warc_offset"], ptr["warc_length"])
            if html:
                return html
        return None

    return _scrape_jurisdiction_core(url, gnis, url_map, get)


def scrape_jurisdiction_wayback(
    url: str,
    gnis: str = "",
    url_map: dict | None = None,
    sleep: float = 2.0,
    year: str = "2023",
    cache_dir: str | None = None,
) -> dict:
    """Scrape one CodePublishing jurisdiction from Wayback Machine captures.

    Fetches the archived copy of each page nearest to `year` directly from
    web.archive.org. Chapter enumeration still uses the CC URL map when the
    landing page is a mobile stub. Pace gently (default 3s) — Wayback throttles.

    When `cache_dir` is given, every fetched page is cached under
    `<cache_dir>/<gnis>/<sha1-of-url>.html` and reused on later runs, so a
    killed worker resumes a town instead of refetching it from scratch.
    """

    import hashlib
    import os

    def _cache_path(page_url: str) -> str | None:
        if not cache_dir or not gnis:
            return None
        digest = hashlib.sha1(page_url.encode("utf-8")).hexdigest()
        return os.path.join(cache_dir, str(gnis), digest + ".html")

    def get(page_url: str) -> str | None:
        cp = _cache_path(page_url)
        if cp and os.path.exists(cp):
            try:
                with open(cp, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError:
                pass
        for attempt in range(3):
            time.sleep(sleep)
            html = fetch_wayback(page_url, year=year)
            if html:
                if cp:
                    try:
                        os.makedirs(os.path.dirname(cp), exist_ok=True)
                        with open(cp, "w", encoding="utf-8") as f:
                            f.write(html)
                    except OSError:
                        pass
                return html
        return None

    return _scrape_jurisdiction_core(url, gnis, url_map, get)
