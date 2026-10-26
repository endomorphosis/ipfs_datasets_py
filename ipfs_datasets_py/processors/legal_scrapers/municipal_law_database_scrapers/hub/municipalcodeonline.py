"""Municipal Code Online (municipalcodeonline.com) scraper.

Strategy (verified 2026-09-16 against norman.municipalcodeonline.com):
``GET {base}/book/print?type={ordinances|code}`` returns the *entire* book as
one HTML document (HTTP 200, no XHR, no JS required) via ordinary egress.

Document structure of the print view:
- Node headers: ``<div class='phx-name[ phx-break]'><a ... href='...#name=SLUG'>TITLE</a></div>``
  ``phx-break`` marks top-level nodes (CHARTER, CHAPTER_*, APPENDIX_*).
- A ``<div class='toc'>`` sub-table of contents may follow a header.
- Section body follows the header until the next ``phx-name`` header.
- History notes appear inline as ``(Ord. No. O-...., § N; ...)``.

The interactive ``/book/content`` XHR endpoint is gated by
``MunicipalCodeOnline.Filters.SameSiteAjaxFilter`` and returns
"Unauthorized Access" (HTTP 500) to non-browser clients, and the Kendo
``/book/expand`` TOC datasource 500s the same way — so the print view is
the reliable route.
"""

from __future__ import annotations

import html as _html
import re
import time
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_HEADER_RE = re.compile(
    r"<div class='phx-name([^']*)'><a[^>]*?href='[^']*#name=([^']+)'[^>]*>(.*?)</a>",
    re.S,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _parse_base(url: str) -> tuple[str | None, str | None]:
    m = re.match(r"(https?://[^/]+\.municipalcodeonline\.com)/?", url or "", re.I)
    if not m:
        return None, None
    base = m.group(1)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    btype = (q.get("type") or [None])[0]
    if btype not in ("ordinances", "code"):
        btype = None
    return base, btype


def _fetch_print_html(base: str, book_type: str, *, timeout: int = 90) -> str | None:
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    landing = f"{base}/book?type={book_type}"
    req = urllib.request.Request(
        landing, headers={"User-Agent": _BROWSER_UA, "Accept": "text/html"}
    )
    try:
        with opener.open(req, timeout=30) as r:
            r.read(65536)  # seed cookies; body is a JS shell
    except Exception:
        pass
    url = f"{base}/book/print?type={book_type}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _BROWSER_UA,
            "Accept": "text/html",
            "Referer": landing,
        },
    )
    try:
        with opener.open(req, timeout=timeout) as r:
            if r.status != 200:
                return None
            raw = r.read()
    except Exception:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", "replace")


def _clean_title(raw: str) -> str:
    text = _TAG_RE.sub("", raw)
    text = _html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _slug_to_section(slug: str) -> str:
    """'10-101_Filing_Fee_...' -> '10-101'."""
    head = slug.split("_", 1)[0]
    return head


def _parse_book(html: str) -> list[dict]:
    matches = list(_HEADER_RE.finditer(html))
    docs: list[dict] = []
    chapter_slug = ""
    chapter_title = ""
    for i, m in enumerate(matches):
        cls, slug, title_raw = m.group(1), m.group(2), m.group(3)
        title = _clean_title(title_raw)
        if not slug or not title:
            continue
        is_top = "phx-break" in cls
        if is_top:
            chapter_slug, chapter_title = slug, title
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(html)
        body = html[start:end]
        # drop the sub-TOC div (it duplicates links, not content)
        body = re.sub(r"<div class='toc'>.*?</div>\s*(?=<div><div class='phx-name )", "",
                      body, flags=re.S)
        body = body.strip()
        if not body:
            continue
        docs.append(
            {
                "Id": slug,
                "doc_id": slug,
                "Title": title,
                "TitleHtml": f'<div class="chunk-title">{_html.escape(title)}</div>',
                "Content": body,
                "DocOrderId": len(docs),
                "doc_order": len(docs),
                "chapter_slug": chapter_slug,
                "chapter_title": chapter_title,
                "section": _slug_to_section(slug),
                "is_top_level": is_top,
            }
        )
    return docs


def scrape_jurisdiction(url: str, sleep: float = 2.0) -> dict:
    """Scrape one Municipal Code Online jurisdiction via the print view."""
    base, btype = _parse_base(url)
    if not base:
        return {"ok": False, "error": f"not a municipalcodeonline URL: {url}", "docs": []}
    types = [btype] if btype else []
    types += [t for t in ("ordinances", "code") if t not in types]
    last_err = "no book type returned content"
    for book_type in types:
        time.sleep(sleep)
        html = _fetch_print_html(base, book_type)
        if not html or "phx-name" not in html:
            last_err = f"print view empty/failed for type={book_type}"
            continue
        docs = _parse_book(html)
        if not docs:
            last_err = f"no nodes parsed for type={book_type}"
            continue
        return {
            "ok": True,
            "docs": docs,
            "book_type": book_type,
            "node_count": len(docs),
        }
    return {"ok": False, "error": last_err, "docs": []}
