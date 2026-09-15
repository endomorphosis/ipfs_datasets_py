#!/usr/bin/env python3
"""United Kingdom: legislation.gov.uk (The National Archives) CLML API.

Official sources only (OGL v3.0):
  - https://www.legislation.gov.uk/developer
  - Atom lists: /{kind}/data.feed paginated via rel=next until exhausted
  - Document CLML: /{kind}/{year}/{number}/data.xml (latest / in-force revised)
  - Original print PDFs: /{kind}/.../pdfs/*.pdf when XML is a stub
    (NumberOfProvisions=0). robots.txt: never */data.pdf or */data.docx.

Primary: ukpga, ukla, ukcm, asp, nia, anaw, asc, mwa
Secondary: uksi, wsi, ssi, nisr, nisi, ukci, ukmo
Does not use BAILII, Westlaw, Lexis, or other unofficial/commercial databases.
Fair use: 3000 API requests / 5 minutes. No WAF bypass.
On 429: pause origin, Wayback of the same official legislation.gov.uk URL only.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "uk"
COUNTRY = "United Kingdom"
SOURCE_TYPE = "legislation_gov_uk"
LICENSE = (
    "Open Government Licence v3.0 (The National Archives / legislation.gov.uk). "
    "All content is available under the Open Government Licence v3.0 except where "
    "otherwise stated. See https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/ "
    "and https://www.legislation.gov.uk/. The official legislation.gov.uk text prevails. "
    "Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.legislation.gov.uk/developer"
HOST = "https://www.legislation.gov.uk"
WORKERS = 8
SLEEP = 0.35
RESULTS = 100
MIN_BODY = 80
MAX_CATALOG_PAGES = 8000
RATE_PER_5MIN = 900
COOLDOWN_429 = 25.0
OFFICIAL_HOSTS = {"www.legislation.gov.uk", "legislation.gov.uk"}
PRIMARY_KINDS = ["ukpga"]
SECONDARY_KINDS = []
ALL_KINDS = PRIMARY_KINDS + SECONDARY_KINDS
STATUTE_KINDS = set(PRIMARY_KINDS)
PRINT_ONLY_RE = re.compile(
    r"only available in its original print|original print pdf|no full text available",
    re.I,
)
SECTION_SPLIT = re.compile(
    r"(?im)^[ \t]*((?:section|s)\.?[ \t]+\d+[A-Za-z]?)\b"
)
log = logging.getLogger("uk")

NS_ATOM = "http://www.w3.org/2005/Atom"
NS_UKM = "http://www.legislation.gov.uk/namespaces/metadata"
NS_LEG = "http://www.legislation.gov.uk/namespaces/legislation"
NS_DC = "http://purl.org/dc/elements/1.1/"

_rate_lock = threading.Lock()
_rate_times: list[float] = []
_429_until = 0.0


def rate_wait(max_per_5min: int = RATE_PER_5MIN) -> None:
    global _rate_times
    sleep_for = 0.0
    with _rate_lock:
        now = time.time()
        extra = max(0.0, _429_until - now)
        _rate_times = [t for t in _rate_times if now - t < 300]
        if len(_rate_times) >= max_per_5min:
            sleep_for = 300 - (now - _rate_times[0]) + 0.2
        sleep_for = max(sleep_for, extra)
        _rate_times.append(now + max(0.0, sleep_for))
    if sleep_for > 0:
        log.info("rate-limit pause %.1fs", sleep_for)
        time.sleep(sleep_for)


def note_429() -> None:
    global _429_until
    with _rate_lock:
        _429_until = max(_429_until, time.time() + COOLDOWN_429)
    log.warning("origin 429 cooldown %.0fs", COOLDOWN_429)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def https(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url[7:]
    return url


def is_official(url: str) -> bool:
    if not url:
        return False
    u = https(url).split("?", 1)[0]
    if "legislation.gov.uk/" not in u:
        return False
    if "://web.archive.org/" in u or "://data.commoncrawl.org/" in u:
        return "legislation.gov.uk/" in u
    host = u.split("://", 1)[-1].split("/", 1)[0].lower()
    return host in OFFICIAL_HOSTS


def robots_blocked(url: str) -> bool:
    u = (url or "").lower()
    return "/data.pdf" in u or "/data.docx" in u


def with_results(url: str) -> str:
    url = https(url)
    if "results-count=" not in url:
        url += ("&" if "?" in url else "?") + f"results-count={RESULTS}"
    return url


def api_get(url: str, retries: int = 1) -> Optional[object]:
    """Live GET. On 429/403 return the response so caller can archive-fallback.
    Does not fetch robots-disallowed */data.pdf or */data.docx.
    """
    url = https(url)
    if robots_blocked(url):
        log.info("skip robots-disallowed %s", url)
        return None
    if not is_official(url):
        log.warning("blocked non-official URL %s", url)
        return None
    rate_wait()
    r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 120), retries=retries, allow_empty=True)
    if r.status_code in (404, 410):
        return None
    if r.status_code == 429:
        log.warning("HTTP 429 %s — archive fallback, not origin retry storm", url)
        note_429()
        return r
    if r.status_code == 403:
        log.warning("HTTP 403 %s", url)
        return r
    if r.status_code != 200 or not r.content:
        return r
    return r


def archive_official(url: str) -> tuple[Optional[bytes], str, str]:
    """Wayback of an official legislation.gov.uk URL only. No origin retry, no WAF bypass."""
    url = https(url)
    if not is_official(url) or robots_blocked(url):
        return None, url, ""
    try:
        wb = af.get_wayback_content(url)
        body = wb.get("content") or b""
        if isinstance(body, str):
            body = body.encode("utf-8", "replace")
        if wb.get("status") == "success" and body:
            return body, wb.get("wayback_url") or url, "wayback"
    except Exception as exc:
        log.info("wayback fail %s %s", url, exc)
    return None, url, ""


def fetch_official(url: str) -> tuple[Optional[bytes], str, int, str]:
    """Live official GET. On 429: Wayback of the same URL, then wait and one live retry.
    Never bypasses WAF; never fetches */data.pdf.
    """
    url = https(url)

    def once():
        try:
            resp = api_get(url)
        except Exception as exc:
            log.info("live fail %s %s", url, exc)
            return None, 0, url
        status = getattr(resp, "status_code", 0) if resp is not None else 0
        content = getattr(resp, "content", None) if resp is not None else None
        final = getattr(resp, "url", url) if resp is not None else url
        return content, status, https(final or url)

    content, status, final = once()
    if status == 200 and content:
        return content, final, status, "live"
    if status in (429, 403, 503):
        body, src, method = archive_official(url)
        if body:
            return body, src, 200, method or "archive"
        # archive miss: wait for origin cooldown then one live retry
        wait = 0.0
        with _rate_lock:
            wait = max(0.0, _429_until - time.time())
        if wait > 0:
            time.sleep(min(wait, 60.0))
        content, status, final = once()
        if status == 200 and content:
            return content, final, status, "live_retry"
    return None, final, status, "fail"


def is_clml_stub(raw: str) -> bool:
    if not raw or "<Legislation" not in raw:
        return True
    if re.search(r'NumberOfProvisions="0"', raw):
        return True
    if PRINT_ONLY_RE.search(raw):
        return True
    if "<P1" in raw or ":P1" in raw or "<Body" in raw or ":Body" in raw:
        return False
    return len(raw) < 8000


def extract_pdf_from_xml(raw: str) -> list[str]:
    urls = []
    for m in re.finditer(r'https?://(?:www\.)?legislation\.gov\.uk/[^"\s<>]+/pdfs/[^"\s<>]+\.pdf', raw, re.I):
        u = https(m.group(0))
        if not robots_blocked(u):
            urls.append(u)
    for m in re.finditer(r'URI="(https?://[^"]+/pdfs/[^"]+\.pdf)"', raw, re.I):
        u = https(m.group(1))
        if not robots_blocked(u) and "legislation.gov.uk" in u:
            urls.append(u)
    out, seen = [], set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def candidate_pdf(it: dict, kind: str) -> list[str]:
    urls: list[str] = []
    key = path_from_id(it.get("id") or "", kind)
    year = str(it.get("year") or "")
    number = str(it.get("number") or "")
    if key and year.isdigit() and number.isdigit():
        urls.append(f"{HOST}/{kind}/{key}/pdfs/{kind}_{year}{number.zfill(4)}_en.pdf")
    cat = https(it.get("pdf_url") or "")
    if cat and "/pdfs/" in cat and not robots_blocked(cat):
        urls.append(cat)
    out, seen = [], set()
    for u in urls:
        if u and u not in seen and is_official(u):
            seen.add(u)
            out.append(u)
    return out


def candidate_html(it: dict, kind: str) -> list[str]:
    urls = []
    key = path_from_id(it.get("id") or "", kind)
    if key:
        urls.append(f"{HOST}/{kind}/{key}/data.htm")
        urls.append(f"{HOST}/{kind}/{key}/enacted/data.htm")
    out, seen = [], set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def pdf_to_text(content: bytes) -> str:
    if not content or content[:4] != b"%PDF":
        return ""
    import subprocess
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(content)
            tmp.flush()
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", tmp.name, "-"],
                check=False, capture_output=True, timeout=120,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace")
    except Exception as exc:
        log.warning("pdftotext fail %s", exc)
    return ""


def html_legislation_text(html: str) -> str:
    if not html or af.is_challenge(html, 200) or PRINT_ONLY_RE.search(html or ""):
        return ""
    chunks = []
    for pat in (
        r'(?is)<div[^>]+id="viewLeg(?:Contents|Snippet)"[^>]*>(.*)</div>',
        r'(?is)<div[^>]+class="[^"]*LegSnippet[^"]*"[^>]*>(.*)</div>',
        r'(?is)<div[^>]+id="content"[^>]*>(.*)</div>',
    ):
        m = re.search(pat, html)
        if m:
            chunks.append(html_to_text(m.group(1)))
    text = max(chunks, key=len) if chunks else html_to_text(html)
    if "Search Legislation" in text and "Skip to main content" in text and len(text) < 2500:
        return ""
    if PRINT_ONLY_RE.search(text):
        return ""
    return text.strip()


def split_uk_sections(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if docs:
        return docs
    if not text or len(text) < MIN_BODY:
        return []
    matches = list(SECTION_SPLIT.finditer(text))
    if len(matches) < 2:
        return []
    docs = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < 20:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        docs.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": num,
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "uk_section"}},
        })
        if len(docs) >= 4000:
            break
    return docs


def catalog_path(kind: str) -> Path:
    return ROOT / CC / "raw" / f"catalog_{kind}.jsonl"


def catalog_complete_path(kind: str) -> Path:
    return ROOT / CC / "raw" / f"catalog_{kind}.complete"


def catalog_state_path(kind: str) -> Path:
    return ROOT / CC / "raw" / f"catalog_{kind}.state.json"


def load_catalog(kind: str) -> list[dict]:
    p = catalog_path(kind)
    if not p.exists() or p.stat().st_size < 200:
        return []
    items = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def save_catalog(kind: str, items: list[dict]) -> None:
    atomic_write(catalog_path(kind), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items))


def save_state(kind: str, nxt: Optional[str], pages: int, n: int, complete: bool) -> None:
    rec = {"next": nxt, "pages": pages, "n": n, "complete": complete, "updated": utcnow()}
    atomic_write(catalog_state_path(kind), json.dumps(rec, indent=2) + "\n")
    if complete:
        atomic_write(catalog_complete_path(kind), f"{n}\n{utcnow()}\n")


def load_state(kind: str) -> dict:
    p = catalog_state_path(kind)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_entries(xml_bytes: bytes, kind: str) -> tuple[list[dict], Optional[str], dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    next_href = None
    meta = {}
    for child in list(root):
        tag = localtag(child.tag)
        if tag == "link" and child.attrib.get("rel") == "next":
            next_href = https(child.attrib.get("href") or "")
        if tag == "morePages":
            meta["morePages"] = (child.text or "").strip()
        if tag == "facetType" and child.attrib.get("type"):
            meta["facet_total"] = child.attrib.get("value")
    for entry in root.iter():
        if localtag(entry.tag) != "entry":
            continue
        rec: dict = {"kind": kind}
        xml_url = html_url = pdf_url = ident = title = None
        year = number = None
        published = None
        for el in list(entry):
            t = localtag(el.tag)
            if t == "id":
                ident = (el.text or "").strip()
            elif t == "title":
                title = (el.text or "").strip()
            elif t == "published":
                published = (el.text or "").strip()
            elif t == "link":
                href = https(el.attrib.get("href") or "")
                rel = el.attrib.get("rel") or ""
                typ = (el.attrib.get("type") or "").lower()
                if href.endswith("/data.xml") or (typ == "application/xml" and "/data.xml" in href):
                    xml_url = href
                elif "/pdfs/" in href and href.lower().endswith(".pdf") and not robots_blocked(href):
                    pdf_url = href
                elif rel in ("", "alternate") and "/data." not in href and ident:
                    if not html_url:
                        html_url = href
            elif t == "Year":
                year = el.attrib.get("Value")
            elif t == "Number":
                number = el.attrib.get("Value")
            elif t == "DocumentMainType":
                rec["main_type"] = el.attrib.get("Value")
        if not ident:
            continue
        rec.update({
            "id": ident,
            "title": title,
            "year": year,
            "number": number,
            "xml_url": xml_url,
            "html_url": html_url,
            "pdf_url": pdf_url,
            "published": published,
        })
        items.append(rec)
    return items, next_href, meta


def _parse_catalog_page(kind: str, url: str) -> tuple[list[dict], Optional[str], dict, str]:
    """Fetch one Atom page. Retry live on 429; Wayback of the official feed URL if still blocked."""
    last_status = "fail"
    for attempt in range(1, 6):
        resp = api_get(url)
        status = getattr(resp, "status_code", 0) if resp is not None else 0
        content = getattr(resp, "content", None) if resp is not None else None
        if status == 200 and content:
            try:
                batch, nxt, meta = parse_entries(content, kind)
                return batch, nxt, meta, "live"
            except ET.ParseError as exc:
                log.warning("catalog XML parse fail %s %s", url, exc)
                last_status = "parse"
                break
        if status == 429:
            last_status = "429"
            time.sleep(min(30, 8 * attempt))
            continue
        if status in (403, 503):
            last_status = str(status)
            break
        last_status = str(status or "missing")
        break
    body, src, how = archive_official(url)
    if body:
        try:
            batch, nxt, meta = parse_entries(body, kind)
            return batch, nxt, meta, how or "wayback"
        except ET.ParseError:
            pass
    return [], None, {"error": last_status}, "fail"


def discover(kind: str) -> list[dict]:
    """Paginate Atom /{kind}/data.feed via rel=next until exhausted. Resume-safe."""
    existing = load_catalog(kind)
    complete_p = catalog_complete_path(kind)
    items: list[dict] = []
    seen: set[str] = set()
    for it in existing:
        k = it.get("id")
        if k and k not in seen:
            seen.add(k)
            items.append(it)
    state = load_state(kind)
    if items and complete_p.exists() and state.get("complete"):
        log.info("resume catalog %s n=%s (complete)", kind, len(items))
        return items

    # Always refresh page 1 so newly published instruments are not missed,
    # then continue from saved next (or page 2) until the feed is exhausted.
    first = with_results(f"{HOST}/{kind}/data.feed?results-count={RESULTS}")
    saved_next = state.get("next") if not state.get("complete") else None
    queue = [first]
    if saved_next and https(saved_next) != first:
        queue.append(with_results(saved_next))

    pages = int(state.get("pages") or 0)
    url = queue.pop(0) if queue else first
    stalled = 0
    while url and pages < MAX_CATALOG_PAGES:
        batch, nxt, meta, how = _parse_catalog_page(kind, url)
        if how == "fail" and not batch:
            stalled += 1
            log.warning("catalog %s stall=%s %s meta=%s", kind, stalled, url, meta)
            if stalled >= 4:
                save_state(kind, url, pages, len(items), complete=False)
                save_catalog(kind, items)
                break
            time.sleep(20)
            continue
        stalled = 0
        pages += 1
        newc = 0
        for it in batch:
            k = it.get("id")
            if not k or k in seen:
                continue
            seen.add(k)
            items.append(it)
            newc += 1
        log.info(
            "catalog %s page=%s batch=%s new=%s total=%s next=%s via=%s meta=%s",
            kind, pages, len(batch), newc, len(items), bool(nxt), how, meta,
        )
        if pages % 5 == 0:
            save_catalog(kind, items)
            save_state(kind, nxt, pages, len(items), complete=False)
        if not batch and not nxt:
            break
        if nxt:
            url = with_results(nxt)
            # after first page, if we have a saved-next jump target still queued, ignore it
            # once we are following live next links from page 1 (avoids skipping a hole).
            queue = []
            continue
        if queue:
            url = queue.pop(0)
            continue
        more = 0
        try:
            more = int(meta.get("morePages") or 0)
        except Exception:
            more = 0
        if more > 0:
            url = with_results(f"{HOST}/{kind}/data.feed?page={pages + 1}&results-count={RESULTS}")
            continue
        url = None

    complete = url is None and stalled == 0
    save_catalog(kind, items)
    save_state(kind, url, pages, len(items), complete=complete)
    log.info("catalog %s done n=%s complete=%s", kind, len(items), complete)
    return items


def path_from_id(ident: str, kind: str) -> Optional[str]:
    ident = ident.replace("https://", "http://")
    prefix = f"http://www.legislation.gov.uk/id/{kind}/"
    if ident.startswith(prefix):
        return ident[len(prefix):]
    m = re.search(rf"/id/{kind}/(.+)$", ident)
    return m.group(1) if m else None


def el_text(el: ET.Element, skip: set[str] | None = None) -> str:
    skip = skip or {"Commentary", "CommentaryRef", "Footnote", "Footnotes", "Metadata"}
    if localtag(el.tag) in skip:
        return ""
    parts: list[str] = []
    if el.text and el.text.strip():
        parts.append(el.text.strip())
    for c in list(el):
        t = el_text(c, skip)
        if t:
            parts.append(t)
        if c.tail and c.tail.strip():
            parts.append(c.tail.strip())
    tag = localtag(el.tag)
    if tag in {"P1", "P1para", "P2para", "Text", "Pblock", "P1group"}:
        parts.append("\n")
    return " ".join(parts)


def parse_clml(raw: str, law_id: str, source_url: str, date: Optional[str]) -> tuple[str, str, list[dict], dict]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        text = xml_to_text(raw)
        return "", text, split_articles(text, law_id, source_url, date), {}
    title = ""
    status = ""
    year = number = None
    for el in root.iter():
        t = localtag(el.tag)
        if t in {"Title", "title"} and not title and (el.text or "").strip():
            if "dc" in (el.tag or "") or t == "title":
                title = el.text.strip()
        if t == "DocumentStatus":
            status = el.attrib.get("Value") or ""
        if t == "Year":
            year = el.attrib.get("Value") or year
        if t == "Number":
            number = el.attrib.get("Value") or number
        if t == "LongTitle" and not title:
            title = " ".join(el.itertext()).strip()
    if not title:
        for el in root.iter():
            if localtag(el.tag) in {"Title", "title"} and (el.text or "").strip():
                title = el.text.strip()
                break
    body_text_parts = []
    docs = []
    for el in root.iter():
        if localtag(el.tag) != "P1":
            continue
        num = ""
        for child in list(el):
            if localtag(child.tag) == "Pnumber":
                num = re.sub(r"\s+", " ", "".join(child.itertext())).strip()
                break
        chunk = re.sub(r"[ \t]+", " ", el_text(el))
        chunk = re.sub(r"\n{3,}", "\n\n", chunk).strip()
        if not chunk or len(chunk) < 20:
            continue
        body_text_parts.append(chunk)
        label = f"Section {num}" if num else f"Section {len(docs)+1}"
        aid = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
        docs.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": label,
            "text": chunk,
            "date_filed": date,
            "document_number": label,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num or label,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "clml_p1"}},
        })
        if len(docs) >= 4000:
            break
    text = "\n\n".join(body_text_parts)
    if not text:
        text = xml_to_text(raw, skip_tags={
            "meta", "identification", "references", "classification", "workflow",
            "analysis", "proprietary", "presentation", "commentary", "commentaries",
            "metadata", "primarymetadata", "alternatives",
        })
        if not docs:
            docs = split_articles(text, law_id, source_url, date)
    return title, text, docs, {"status": status, "year": year, "number": number}


def candidate_xml(it: dict, kind: str) -> list[str]:
    urls = []
    key = path_from_id(it.get("id") or "", kind)
    if key:
        urls.append(f"{HOST}/{kind}/{key}/data.xml")
        urls.append(f"{HOST}/{kind}/{key}/enacted/data.xml")
    xml_url = https(it.get("xml_url") or "")
    if xml_url.endswith("/data.xml") and xml_url not in urls:
        urls.append(xml_url)
    out, seen = [], set()
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def rec_id(it: dict) -> str:
    kind = it.get("kind") or "ukpga"
    key = path_from_id(it.get("id") or "", kind) or (it.get("id") or "")
    return slug_id(CC, f"{kind}-{key}")


def nonempty_ids(cc: str) -> set[str]:
    """Skip only instruments that already have a usable body (retry empty_text JSON)."""
    d = ROOT / cc / "instruments"
    if not d.exists():
        return set()
    done: set[str] = set()
    for p in d.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if len(rec.get("text") or "") >= MIN_BODY:
            done.add(p.stem)
    return done


def fetch_one(it: dict, done: set[str]) -> str:
    ident = it.get("id") or ""
    kind = it.get("kind") or "ukpga"
    key = path_from_id(ident, kind) or ident
    rid = slug_id(CC, f"{kind}-{key}")
    if rid in done:
        return "skip"
    title = it.get("title") or key
    date = iso_date((it.get("published") or "")[:10])
    raw = ""
    source_url = ""
    method = ""
    stub_xml = ""

    # Print-only majority on resume: try constructed /pdfs/ first (one GET).
    pdf_urls_early = candidate_pdf(it, kind)
    if pdf_urls_early:
        content, final, status, how = fetch_official(pdf_urls_early[0])
        if content:
            text_try = pdf_to_text(content)
            if text_try and len(text_try) >= MIN_BODY:
                raw = text_try
                source_url = final or pdf_urls_early[0]
                method = "pdf" if how == "live" else f"pdf_{how}"

    # 1) born-digital CLML only if PDF did not yield text.
    if not raw:
        for url in candidate_xml(it, kind):
            content, final, status, how = fetch_official(url)
            if not content:
                continue
            body = content
            if not (body[:1] == b"<" or b"<Legislation" in body[:3000]):
                continue
            raw_try = body.decode("utf-8", "replace")
            if "<Legislation" not in raw_try and "legislation.gov.uk/namespaces" not in raw_try:
                continue
            if is_clml_stub(raw_try):
                stub_xml = stub_xml or raw_try
                continue
            raw = raw_try
            source_url = final or url
            method = "clml" if how == "live" else f"xml_{how}"
            break

    # 2) original print PDF via /pdfs/ when XML is stub/missing (never */data.pdf)
    pdf_urls = []
    if stub_xml:
        pdf_urls.extend(extract_pdf_from_xml(stub_xml))
    pdf_urls.extend(candidate_pdf(it, kind))
    seen_pdf = set()
    uniq_pdf = []
    for u in pdf_urls:
        if u and u not in seen_pdf:
            seen_pdf.add(u)
            uniq_pdf.append(u)
    missing_pdf = []
    if not raw:
        for pdf_url in uniq_pdf:
            content, final, status, how = fetch_official(pdf_url)
            if not content:
                missing_pdf.append(pdf_url)
                continue
            text_try = pdf_to_text(content)
            if text_try and len(text_try) >= MIN_BODY:
                raw = text_try
                source_url = final or pdf_url
                method = "pdf" if how == "live" else f"pdf_{how}"
                break

    # 3) HTML data.htm only when XML was missing (not a known print-only stub)
    in_cooldown = False
    with _rate_lock:
        in_cooldown = _429_until > time.time()
    if not raw and not stub_xml and not in_cooldown:
        for url in candidate_html(it, kind)[:1]:
            content, final, status, how = fetch_official(url)
            if not content:
                continue
            html = content.decode("utf-8", "replace")
            text_try = html_legislation_text(html)
            if text_try and len(text_try) >= MIN_BODY:
                raw = html
                source_url = final or url
                method = "html" if how == "live" else f"html_{how}"
                break

    # 4) Wayback of official /pdfs/ when live 404/empty (429 already handled in fetch_official)
    if not raw:
        for pdf_url in missing_pdf or uniq_pdf:
            body, src, how = archive_official(pdf_url)
            if not body:
                continue
            text_try = pdf_to_text(body)
            if text_try and len(text_try) >= MIN_BODY:
                raw = text_try
                source_url = src
                method = f"pdf_{how or 'wayback'}"
                break

    if not raw or len(raw) < 40:
        log_failure(CC, {"id": rid, "url": ident, "status": "failed", "reason": "no_body", "kind": kind})
        return "fail"

    if method.startswith("clml") or method.startswith("xml"):
        parsed_title, text, docs, meta = parse_clml(raw, rid, source_url, date)
        title = parsed_title or title
        status = (meta.get("status") or "").lower()
        if not text or len(text) < MIN_BODY:
            log_failure(CC, {"id": rid, "url": source_url or ident, "status": "failed", "reason": "empty_text", "kind": kind})
            return "fail"
    elif method.startswith("html"):
        text = html_legislation_text(raw) or html_to_text(raw)
        docs = split_uk_sections(text, rid, source_url, date)
        status = ""
    else:
        text = raw
        docs = split_uk_sections(text, rid, source_url, date)
        status = ""

    if not text or len(text) < MIN_BODY:
        log_failure(CC, {"id": rid, "url": source_url or ident, "status": "failed", "reason": "empty_text", "kind": kind})
        return "fail"

    repealed = "repealed" in (title or "").lower()
    law_status = "repealed" if repealed else ("current" if status in {"revised", "final", ""} else "unknown")
    if status == "revised":
        law_status = "repealed" if repealed else "current"
    canon = f"{HOST}/{kind}/{key}" if key else source_url
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=f"{kind}-{key}", title=title,
        text=text, source_url=source_url or canon, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="collect_legislation_gov_uk.py",
        eli=ident if ident.startswith("http") else None, date=date,
        official_identifier=f"{kind} {key}".replace("/", " "),
        document_type="statute" if kind in STATUTE_KINDS else "regulation",
        law_status=law_status, is_current=(law_status == "current"), documents=docs,
        extra_meta={
            "discovery": {"method": "atom_data.feed", "kind": kind},
            "document_status": status,
            "year": it.get("year"),
            "number": it.get("number"),
            "text_extraction": {"source": "official", "backend": method},
        },
        extra_fields={"canonical_law_url": canon, "information_url": canon},
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def run_pool(items, done, counters, write_progress, label: str):
    if not items:
        return
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, it, done) for it in items]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc), "kind": label})
            counters[st] = counters.get(st, 0) + 1
            if n % 25 == 0 or n == len(items):
                log.info(
                    "progress %s %s/%s ok=%s skip=%s fail=%s",
                    label, n, len(items), counters["ok"], counters["skip"], counters["fail"],
                )
                write_progress("catalog-backed incomplete")


def main():
    setup()
    t0 = utcnow()
    counters = {"ok": 0, "skip": 0, "fail": 0}
    listed: dict[str, int] = {}
    fetched_by: dict[str, int] = {}
    source_urls = [
        "https://www.legislation.gov.uk/",
        "https://www.legislation.gov.uk/developer",
        "https://www.legislation.gov.uk/ukpga/data.feed",
        "https://www.legislation.gov.uk/uksi/data.feed",
        "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
    ]
    notes_base = (
        "Official legislation.gov.uk coverage (OGL v3.0): primary ukpga/ukla/ukcm/asp/nia/"
        "anaw/asc/mwa then secondary uksi/wsi/ssi/nisr/nisi/ukci/ukmo. Atom data.feed "
        "paginated until exhausted. CLML data.xml first; stub XML (NumberOfProvisions=0 / "
        "print-only) falls through to /pdfs/ original print PDFs (robots.txt: */data.pdf not "
        "fetched). Repealed titles kept. Resume skips existing slug ids with usable text; "
        "retries previous empty_text. Not BAILII/Westlaw/Lexis. On 429: pause and Wayback of "
        "official legislation.gov.uk URLs only. WORKERS=3 SLEEP>=0.5."
    )
    all_items: list[dict] = []

    def write_progress(coverage: str, extra: str = ""):
        listed_s = ", ".join(f"{k}={listed.get(k, 0)}" for k in ALL_KINDS)
        notes = notes_base + f" Listed: {listed_s}." + extra
        write_summary(
            CC, country=COUNTRY,
            source="legislation.gov.uk (The National Archives)",
            source_urls=source_urls, license_text=LICENSE,
            discovered=sum(listed.values()) or len(all_items),
            fetched=counters["ok"], skipped=counters["skip"],
            failed=counters["fail"], coverage=coverage, notes=notes,
        )

    done = nonempty_ids(CC)
    log.info(
        "start ukpga-only PDF/CLML recovery kinds=%s already_done_nonempty=%s workers=%s sleep=%s",
        ",".join(ALL_KINDS), len(done), WORKERS, SLEEP,
    )

    # Catalog every official type first so uksi Atom pagination is underway
    # before (and not blocked by) the long ukpga body-recovery fetch.
    by_kind: dict[str, list] = {}
    for kind in ALL_KINDS:
        log.info("=== discover %s ===", kind)
        items = discover(kind)
        listed[kind] = len(items)
        by_kind[kind] = items
        all_items.extend(items)
        log.info("listed %s catalog=%s", kind, len(items))
        write_progress("catalog-backed incomplete", extra=f" Cataloguing {kind}. Started {t0}.")

    log.info("all catalogs listed=%s", listed)

    for kind in ALL_KINDS:
        items = by_kind[kind]
        todo = [it for it in items if rec_id(it) not in done]
        log.info(
            "queue %s catalog=%s todo=%s already_have=%s",
            kind, len(items), len(todo), len(items) - len(todo),
        )
        write_progress("catalog-backed incomplete", extra=f" Fetching {kind}. Started {t0}.")
        before_ok = counters["ok"]
        run_pool(todo, done, counters, write_progress, kind)
        fetched_by[kind] = counters["ok"] - before_ok
        log.info(
            "phase %s done fetched_this=%s ok=%s skip=%s fail=%s catalog=%s",
            kind, fetched_by[kind], counters["ok"], counters["skip"], counters["fail"], len(items),
        )

    remaining = sum(1 for it in all_items if rec_id(it) not in done)
    cov = "full" if remaining == 0 and counters["fail"] == 0 else "catalog-backed incomplete"
    extra = (
        f" Started {t0}. Fetched-by-kind: "
        + ", ".join(f"{k}={fetched_by.get(k, 0)}" for k in ALL_KINDS)
        + f". Remaining-without-body={remaining}."
    )
    write_progress(cov, extra=extra)
    log.info(
        "done ok=%s skip=%s fail=%s listed=%s coverage=%s remaining=%s",
        counters["ok"], counters["skip"], counters["fail"], listed, cov, remaining,
    )


if __name__ == "__main__":
    main()
