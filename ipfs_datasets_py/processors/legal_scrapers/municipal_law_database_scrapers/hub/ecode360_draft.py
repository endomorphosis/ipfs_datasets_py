"""eCode360 (General Code) scraper draft.

Public site serves server-rendered HTML with an embedded TOC JSON blob
(``data-toc-nodes``) on the jurisdiction landing page
(``https://ecode360.com/{custId}``). Chapter pages at
``https://ecode360.com/{guid}`` include nested section HTML under
``div.*_content.content`` nodes.

The licensed JSON API at developer.ecode360.com (paired-key) is NOT used.
Admin ``/api/{custId}/…`` routes require auth (401) and are avoided.

Target row shape matches ``parquet_writer.docs_to_html_rows`` Municode docs:
  Id, Title, TitleHtml, Content, DocOrderId
"""

from __future__ import annotations

import html as html_lib
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Iterable, Optional

PUBLISHER = "ecode360"
BASE = "https://ecode360.com"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; JusticeDAO-MuniBot/1.0; "
        "+https://huggingface.co/datasets/justicedao/american_municipal_law)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://ecode360.com/",
}

ECODE_URL_RE = re.compile(
    r"ecode360\.com/([A-Za-z]{2}\d{3,5}|\d{6,})(?:[/?#]|$)",
    re.I,
)
TOC_NODES_RE = re.compile(r'data-toc-nodes="([^"]+)"')
CUST_ID_RE = re.compile(r'data-cust-id="([^"]+)"')
CUSTOMER_NAME_RE = re.compile(r'data-customer-name="([^"]+)"')
CODE_DATE_RE = re.compile(r'data-code-date="([^"]+)"')


class RateLimitError(RuntimeError):
    def __init__(self, retry_after: float, message: str = "rate limited"):
        super().__init__(message)
        self.retry_after = retry_after


def parse_ecode_url(url: str) -> Optional[str]:
    """Return custId or numeric guid from an eCode360 URL."""
    m = ECODE_URL_RE.search(url or "")
    return m.group(1) if m else None


def polite_get_text(
    url: str,
    *,
    sleep: float = 0.75,
    retries: int = 5,
    timeout: float = 90.0,
) -> str:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            time.sleep(sleep + random.uniform(0, sleep * 0.25))
            return raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last_err = e
            body = b""
            try:
                body = e.read() or b""
            except Exception:
                pass
            if e.code == 429 or b"Just a moment" in body[:2000]:
                wait = float(e.headers.get("Retry-After") or (3 * (2**attempt)))
                time.sleep(wait)
                continue
            if e.code in (500, 502, 503, 504) and attempt < retries - 1:
                time.sleep((2**attempt) + random.uniform(0, 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep((2**attempt) + random.uniform(0, 1))
                continue
            raise
    raise last_err or RuntimeError(f"failed GET {url}")


def _walk_toc(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield node
    for child in node.get("children") or []:
        if isinstance(child, dict):
            yield from _walk_toc(child)


def extract_toc(landing_html: str) -> dict[str, Any]:
    m = TOC_NODES_RE.search(landing_html or "")
    if not m:
        raise ValueError("no data-toc-nodes on eCode360 landing page")
    return json.loads(html_lib.unescape(m.group(1)))


def chapter_guids(toc: dict[str, Any]) -> list[dict[str, Any]]:
    """Nodes we should HTTP-fetch: chapters, or leaf numeric guids."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n in _walk_toc(toc):
        guid = str(n.get("guid") or "")
        if not guid.isdigit():
            continue
        ntype = (n.get("type") or "").lower()
        kids = n.get("children") or []
        if ntype in {"chapter", "article", "section"} or not kids:
            if guid not in seen:
                seen.add(guid)
                out.append(n)
    return out


class _ContentExtractor(HTMLParser):
    """Collect div.*_content.content blocks and title metadata."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.titles: dict[str, str] = {}
        self.positions: dict[str, int] = {}
        self.types: dict[str, str] = {}
        self.blocks: list[dict[str, Any]] = []
        self._capture_guid: str | None = None
        self._capture_depth = 0
        self._parts: list[str] = []
        self._capture_class = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        ad = {k: (v or "") for k, v in attrs}
        guid = ad.get("data-guid") or ""
        if guid:
            ft = ad.get("data-full-title")
            if ft:
                self.titles[guid] = html_lib.unescape(ft)
            if ad.get("data-position"):
                try:
                    self.positions[guid] = int(ad["data-position"])
                except ValueError:
                    pass
            if ad.get("data-code-content-type"):
                self.types[guid] = ad["data-code-content-type"]

        if self._capture_guid is not None:
            self._capture_depth += 1
            self._parts.append(self._rebuild_start(tag, attrs))
            return

        if tag == "div":
            cls = ad.get("class", "")
            eid = ad.get("id", "")
            m = re.match(r"^(\d+)_content$", eid)
            if m and "_content" in cls and "content" in cls.split():
                self._capture_guid = m.group(1)
                self._capture_depth = 1
                self._capture_class = cls
                self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._capture_guid is None:
            return
        if tag == "div" and self._capture_depth == 1:
            html = "".join(self._parts).strip()
            self.blocks.append(
                {
                    "guid": self._capture_guid,
                    "class": self._capture_class,
                    "html": html,
                }
            )
            self._capture_guid = None
            self._capture_depth = 0
            self._parts = []
            return
        self._parts.append(f"</{tag}>")
        self._capture_depth = max(0, self._capture_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._capture_guid is not None:
            self._parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._capture_guid is not None:
            self._parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._capture_guid is not None:
            self._parts.append(f"&#{name};")

    @staticmethod
    def _rebuild_start(tag: str, attrs: list[tuple[str, Optional[str]]]) -> str:
        parts = [f"<{tag}"]
        for k, v in attrs:
            if v is None:
                parts.append(f" {k}")
            else:
                parts.append(f' {k}="{html_lib.escape(v, quote=True)}"')
        parts.append(">")
        return "".join(parts)


def parse_chapter_html(page_html: str, *, chapter_guid: str, chapter_title: str) -> list[dict[str, Any]]:
    parser = _ContentExtractor()
    parser.feed(page_html or "")
    parser.close()

    # Ensure chapter title present even if only in <title>
    if chapter_guid not in parser.titles and chapter_title:
        parser.titles[chapter_guid] = chapter_title
    if not parser.titles.get(chapter_guid):
        m = re.search(r"<title[^>]*>(.*?)</title>", page_html or "", re.I | re.S)
        if m:
            parser.titles[chapter_guid] = re.sub(r"\s+-.*$", "", html_lib.unescape(m.group(1))).strip()

    docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in parser.blocks:
        guid = block["guid"]
        if guid in seen:
            continue
        seen.add(guid)
        title = parser.titles.get(guid) or ""
        if not title:
            # fall back to first heading-ish text
            plain = re.sub(r"<[^>]+>", " ", block["html"])
            title = re.sub(r"\s+", " ", plain).strip()[:180]
        title_html = f'<div class="chunk-title">{html_lib.escape(title)}</div>'
        content = block["html"]
        if 'class="chunk-content"' not in content:
            content = f'<div class="chunk-content">{content}</div>'
        order = parser.positions.get(guid)
        if order is None:
            order = len(docs)
        docs.append(
            {
                "Id": guid,
                "Title": title,
                "TitleHtml": title_html,
                "Content": content,
                "DocOrderId": int(order),
                "_content_type": parser.types.get(guid) or "",
                "_block_class": block["class"],
            }
        )
    docs.sort(key=lambda d: (int(d["DocOrderId"]), str(d["Id"])))
    return docs


def scrape_jurisdiction(
    source_url: str,
    *,
    sleep: float = 0.75,
    max_chapters: int | None = None,
    include_types: Optional[set[str]] = None,
) -> dict[str, Any]:
    """
    Scrape one eCode360 jurisdiction into Municode-shaped docs.

    Returns {ok, docs, cust_id, place_name, code_date, chapters_fetched, error}.
    """
    cust = parse_ecode_url(source_url)
    if not cust:
        return {"ok": False, "error": f"not an ecode360 url: {source_url}", "docs": []}

    landing_url = f"{BASE}/{cust}"
    try:
        landing = polite_get_text(landing_url, sleep=sleep)
    except Exception as e:
        return {"ok": False, "error": f"landing fetch failed: {e}", "docs": []}

    try:
        toc = extract_toc(landing)
    except Exception as e:
        return {"ok": False, "error": str(e), "docs": []}

    cust_id = (CUST_ID_RE.search(landing) or [None, cust])[1] or cust
    place_name = html_lib.unescape((CUSTOMER_NAME_RE.search(landing) or [None, ""])[1] or "")
    code_date = (CODE_DATE_RE.search(landing) or [None, ""])[1] or ""

    chapters = chapter_guids(toc)
    if max_chapters is not None:
        chapters = chapters[: max(0, int(max_chapters))]

    docs_by_id: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    fetched = 0
    for node in chapters:
        guid = str(node.get("guid"))
        title = node.get("title") or node.get("tocName") or ""
        prefix = node.get("prefix") or node.get("indexNum") or ""
        if prefix and title and not title.lower().startswith(str(prefix).lower().split()[0] if prefix else ""):
            full_title = f"{prefix}: {title}" if prefix else title
        else:
            full_title = title
        url = f"{BASE}/{guid}"
        try:
            page = polite_get_text(url, sleep=sleep)
        except Exception as e:
            errors.append(f"{guid}: {e}")
            continue
        fetched += 1
        for doc in parse_chapter_html(page, chapter_guid=guid, chapter_title=full_title):
            if include_types:
                # Prefer section/article/chapter based on block class or type attr
                bcls = doc.get("_block_class") or ""
                ctype = doc.get("_content_type") or ""
                kind = ctype
                if not kind:
                    if "section_content" in bcls:
                        kind = "section"
                    elif "article_content" in bcls:
                        kind = "article"
                    elif "chapter_content" in bcls:
                        kind = "chapter"
                if kind and kind not in include_types and not (
                    "section" in include_types and "section_content" in bcls
                ):
                    # still keep if unknown
                    if kind not in include_types:
                        continue
            docs_by_id[str(doc["Id"])] = doc

    docs = list(docs_by_id.values())
    # Stable global order: publisher position first, then guid. Re-number so
    # DocOrderId is unique across chapters (positions restart per page).
    docs.sort(key=lambda d: (int(d.get("DocOrderId") or 0), str(d.get("Id") or "")))
    for i, d in enumerate(docs):
        d["DocOrderId"] = i
    return {
        "ok": bool(docs),
        "error": None if docs else ("no docs; " + "; ".join(errors[:3])),
        "docs": docs,
        "cust_id": cust_id,
        "place_name": place_name,
        "code_date": code_date,
        "chapters_total": len(chapter_guids(toc)),
        "chapters_fetched": fetched,
        "fetch_errors": errors,
        "url": landing_url,
        "toc_title": toc.get("tocName") or toc.get("title") or "",
    }


def scrape_rows(source_url: str, *, sleep: float = 0.75, max_chapters: int | None = None) -> list[dict[str, Any]]:
    """Interface-compatible helper: return docs list or raise."""
    result = scrape_jurisdiction(source_url, sleep=sleep, max_chapters=max_chapters)
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "ecode360 scrape failed")
    return list(result["docs"])


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Smoke-scrape one eCode360 jurisdiction")
    ap.add_argument("url", nargs="?", default="https://ecode360.com/DI3285")
    ap.add_argument("--sleep", type=float, default=0.6)
    ap.add_argument("--max-chapters", type=int, default=2)
    args = ap.parse_args()
    res = scrape_jurisdiction(args.url, sleep=args.sleep, max_chapters=args.max_chapters)
    print(json.dumps({k: v for k, v in res.items() if k != "docs"}, indent=2))
    print(f"docs={len(res.get('docs') or [])}")
    for d in (res.get("docs") or [])[:8]:
        print(f"  {d['DocOrderId']:>6} {d['Id']} {d['Title'][:80]}")
    sys.exit(0 if res.get("ok") else 1)
