#!/usr/bin/env python3
"""Australia: Federal Register of Legislation (Commonwealth Acts + legislative instruments).

Official source only:
  - API (no key): https://api.prod.legislation.gov.au/v1/
  - Swagger:     https://api.prod.legislation.gov.au/swagger/index.html
  - Portal:      https://www.legislation.gov.au/

Does not use AustLII, Westlaw, Lexis, or other unofficial/commercial databases.
Does not HTML-crawl the SPA portal; text is taken from the Register API
compilation EPUB (preferred) or Word/PDF document bytes.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import threading
import subprocess
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
try:
    from archive_fallbacks import get_wayback_content
except Exception:  # pragma: no cover
    get_wayback_content = None  # type: ignore

CC = "au"
COUNTRY = "Australia"
SOURCE_TYPE = "federal_register_legislation"
LICENSE = (
    "Creative Commons Attribution 4.0 International (CC BY 4.0), as stated by the "
    "Federal Register of Legislation at https://www.legislation.gov.au/terms-of-use "
    "(exception: Commonwealth Coat of Arms and content otherwise noted). "
    "Attribute the Federal Register of Legislation, link to the CC BY 4.0 licence, "
    "and indicate any changes. Not legal advice; the authorised Register text prevails."
)
UA = DEFAULT_UA + " source=https://api.prod.legislation.gov.au/v1/"
API = "https://api.prod.legislation.gov.au/v1"
PORTAL = "https://www.legislation.gov.au"
WORKERS = 16
CATALOG_WORKERS = 20
SLEEP = 0.12
PAGE = 100
log = logging.getLogger("au")

# Prefer compilation EPUB (XHTML inside), then Word, then authorised PDF.
FORMATS = ("Epub", "Word", "Pdf")
AS_AT = ("Latest", "Current", "AsMade")

HEAD_P = re.compile(r"<p\b([^>]*)>(.*?)</p>", re.I | re.S)
CHAR_SECT = re.compile(r'class="CharSectno"[^>]*>([^<]+)', re.I)
CLASS_ATTR = re.compile(r'class="([^"]*)"', re.I)
DOCX_WT = re.compile(r"</w:p>|<w:p[\s>]|<w:br\b", re.I)


def setup():
    ensure_dirs(CC)
    (ROOT / CC / "raw" / "cache").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


TITLE_SELECT = (
    "id,name,collection,subCollection,isPrincipal,isInForce,status,year,number,"
    "seriesType,makingDate,optionalSeriesNumber,hasCommencedUnincorporatedAmendments"
)
OFFICIAL_HOSTS = ("legislation.gov.au", "api.prod.legislation.gov.au")


class _WaybackResp:
    def __init__(self, wb: dict):
        self.status_code = 200
        self.content = wb.get("content") or b""
        if isinstance(self.content, str):
            self.content = self.content.encode("utf-8", "replace")
        self.headers = {"content-type": wb.get("content_type") or "application/json"}
        self._text = wb.get("text") or ""
        self.url = wb.get("wayback_url") or wb.get("original_url") or ""

    def json(self):
        raw = self._text or self.content.decode("utf-8", "replace")
        return json.loads(raw)


def _wayback_official(url: str):
    """Replay an official legislation.gov.au URL from Wayback after live 429."""
    host = (urlparse(url).hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in OFFICIAL_HOSTS):
        if not host.endswith("legislation.gov.au"):
            return None
    if get_wayback_content is None:
        return None
    log.info("429 wayback fallback %s", url[:180])
    try:
        wb = get_wayback_content(url)
    except Exception as exc:
        log.warning("wayback fallback failed: %s", exc)
        return None
    if wb.get("status") != "success" or not (wb.get("content") or wb.get("text")):
        log.info("wayback miss %s err=%s", url[:120], wb.get("error"))
        return None
    return _WaybackResp(wb)


def api_get(url: str, *, timeout=(20, 180), retries: int = 5, sleep: float = SLEEP) -> Optional[object]:
    r = http_get(
        url, ua=UA, sleep=sleep, timeout=timeout, retries=retries,
        headers={"Accept": "application/json, application/octet-stream, */*"},
        allow_empty=True,
    )
    if r.status_code == 429:
        wb = _wayback_official(url)
        if wb is not None:
            r = wb
    if r.status_code in (404, 410):
        return None
    if r.status_code != 200 or not r.content:
        return r
    ctype = (r.headers.get("content-type") or "").lower()
    if "json" in ctype or r.content[:1] in (b"{", b"["):
        try:
            return r.json()
        except Exception:
            return r
    return r


def catalog_path(kind: str) -> Path:
    return ROOT / CC / "raw" / f"catalog_{kind}.jsonl"


def load_catalog(kind: str) -> list[dict]:
    path = catalog_path(kind)
    if not path.exists() or path.stat().st_size < 200:
        return []
    items = []
    with path.open(encoding="utf-8") as f:
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
    body = "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items)
    atomic_write(catalog_path(kind), body)



def _slim_title(row: dict, kind: str) -> dict:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "collection": row.get("collection"),
        "subCollection": row.get("subCollection"),
        "isPrincipal": row.get("isPrincipal"),
        "isInForce": row.get("isInForce"),
        "status": row.get("status"),
        "year": row.get("year"),
        "number": row.get("number"),
        "seriesType": row.get("seriesType"),
        "makingDate": row.get("makingDate"),
        "optionalSeriesNumber": row.get("optionalSeriesNumber"),
        "hasCommencedUnincorporatedAmendments": row.get("hasCommencedUnincorporatedAmendments"),
        "kind": kind,
    }


def _ingest_batch(batch: list, kind: str, seen: set[str], items: list[dict]) -> int:
    newc = 0
    for row in batch:
        tid = row.get("id")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        items.append(_slim_title(row, kind))
        newc += 1
    return newc


def page_titles(kind: str, odata_filter: str) -> list[dict]:
    """Catalog titles. Year-numbered rows use year eq YYYY (small buckets).

    Year-null Legislative Instruments cannot use unpartitioned $skip (default
    sort is not unique and misses ~5k of ~24k). $orderby=id is a unique sort
    so $skip is complete; $top is capped at 100 by the API. contains(id,'FYYYY')
    is a year-free secondary net if the ordered pass is still short.
    """
    existing = load_catalog(kind)
    probe = api_get(f"{API}/Titles?$filter={odata_filter}&$top=1", timeout=(20, 90), sleep=0.2)
    expected = probe.get("@odata.count") if isinstance(probe, dict) else None
    log.info("catalog %s expected=%s existing=%s", kind, expected, len(existing))

    if kind == "constitution" and existing:
        log.info("resume catalog %s n=%s", kind, len(existing))
        return existing
    if kind == "act" and existing and len(existing) >= 4700:
        log.info("resume catalog %s n=%s", kind, len(existing))
        return existing
    if (
        kind == "legislative_instrument"
        and existing
        and expected is not None
        and len(existing) >= int(expected) - 20
    ):
        log.info("resume catalog %s n=%s expected=%s", kind, len(existing), expected)
        return existing

    items: list[dict] = list(existing)
    seen: set[str] = {x.get("id") for x in items if x.get("id")}
    ingest_lock = threading.Lock()

    def catalog_year(clause: str) -> int:
        filt = f"{odata_filter} and {clause}"
        skip = 0
        year_total = 0
        while True:
            url = f"{API}/Titles?$filter={filt}&$skip={skip}"
            data = api_get(url, timeout=(20, 90), sleep=SLEEP)
            if not isinstance(data, dict):
                log.warning("catalog page failed kind=%s clause=%s skip=%s", kind, clause, skip)
                break
            batch = data.get("value") or []
            ycount = data.get("@odata.count")
            with ingest_lock:
                newc = _ingest_batch(batch, kind, seen, items)
                total_now = len(items)
            year_total += newc
            nbatch = len(batch)
            if newc or nbatch:
                log.info(
                    "catalog %s %s skip=%s batch=%s new=%s year_new=%s total=%s year_count=%s",
                    kind, clause, skip, nbatch, newc, year_total, total_now, ycount,
                )
            if nbatch == 0:
                break
            skip += nbatch
            if ycount is not None and skip >= int(ycount):
                break
            if nbatch < 50:
                break
        return year_total

    def catalog_ordered_null() -> int:
        """Page year-null titles with $orderby=id (unique sort; $top<=100)."""
        filt = f"{odata_filter} and year eq null"
        probe_n = api_get(
            f"{API}/Titles?$filter={filt}&$top=1&$select=id",
            timeout=(20, 90), sleep=0.2,
        )
        n_expect = probe_n.get("@odata.count") if isinstance(probe_n, dict) else None
        log.info("catalog %s year-null ordered expected=%s have=%s", kind, n_expect, len(items))
        page = min(PAGE, 100)
        if n_expect is None:
            n_expect = 0
        skips = list(range(0, max(int(n_expect), 0) + page, page))
        if not skips:
            skips = [0]
        added = 0
        failed: list[int] = []

        def fetch_skip(skip: int) -> tuple[int, int]:
            url = (
                f"{API}/Titles?$filter={filt}&$orderby=id&$top={page}"
                f"&$select={TITLE_SELECT}&$skip={skip}"
            )
            data = api_get(url, timeout=(20, 90), sleep=SLEEP)
            if not isinstance(data, dict):
                return skip, -1
            batch = data.get("value") or []
            with ingest_lock:
                newc = _ingest_batch(batch, kind, seen, items)
                total_now = len(items)
            if newc or batch:
                log.info(
                    "catalog %s year-null orderby skip=%s batch=%s new=%s total=%s expect=%s",
                    kind, skip, len(batch), newc, total_now, n_expect,
                )
            return skip, newc

        with ThreadPoolExecutor(max_workers=CATALOG_WORKERS) as ex:
            futs = [ex.submit(fetch_skip, sk) for sk in skips]
            for fut in as_completed(futs):
                skip, newc = fut.result()
                if newc < 0:
                    failed.append(skip)
                else:
                    added += newc
        for skip in sorted(failed):
            skip2, newc = fetch_skip(skip)
            if newc < 0:
                log.warning("catalog %s year-null orderby skip=%s failed after retry", kind, skip)
            else:
                added += newc
        log.info("catalog %s year-null ordered added=%s total=%s expect=%s", kind, added, len(items), n_expect)
        return added

    def catalog_contains_prefixes() -> int:
        """Year-free OData contains(id,'FYYYY') / CYYYY net for leftover year-null ids."""
        prefixes = [f"C{y}" for y in range(2004, 2027)] + [f"F{y}" for y in range(1996, 2027)]
        added = 0

        def one(prefix: str) -> int:
            filt = f"{odata_filter} and contains(id,'{prefix}')"
            skip = 0
            local = 0
            while True:
                url = (
                    f"{API}/Titles?$filter={filt}&$orderby=id&$top=100"
                    f"&$select={TITLE_SELECT}&$skip={skip}"
                )
                data = api_get(url, timeout=(20, 90), sleep=SLEEP)
                if not isinstance(data, dict):
                    log.warning("catalog contains(%s) skip=%s failed", prefix, skip)
                    break
                batch = data.get("value") or []
                ycount = data.get("@odata.count")
                with ingest_lock:
                    newc = _ingest_batch(batch, kind, seen, items)
                    total_now = len(items)
                local += newc
                nbatch = len(batch)
                if newc or nbatch:
                    log.info(
                        "catalog %s contains(id,'%s') skip=%s batch=%s new=%s total=%s year_count=%s",
                        kind, prefix, skip, nbatch, newc, total_now, ycount,
                    )
                if nbatch == 0:
                    break
                skip += nbatch
                if ycount is not None and skip >= int(ycount):
                    break
                if nbatch < 50:
                    break
            return local

        with ThreadPoolExecutor(max_workers=CATALOG_WORKERS) as ex:
            futs = [ex.submit(one, pfx) for pfx in prefixes]
            for fut in as_completed(futs):
                added += fut.result()
        log.info("catalog %s contains-id added=%s total=%s", kind, added, len(items))
        return added

    n_with_year = sum(1 for x in items if x.get("year") is not None)
    if kind != "legislative_instrument" or n_with_year < 500:
        year_clauses = [f"year eq {y}" for y in range(1900, 2027)]
        with ThreadPoolExecutor(max_workers=CATALOG_WORKERS) as ex:
            futs = [ex.submit(catalog_year, c) for c in year_clauses]
            for fut in as_completed(futs):
                fut.result()

    if kind == "legislative_instrument" or (expected is not None and len(items) < int(expected)):
        catalog_ordered_null()
        if expected is not None and len(items) < int(expected) - 20:
            log.info(
                "catalog %s still short %s<%s after orderby; contains(id) net",
                kind, len(items), expected,
            )
            catalog_contains_prefixes()
        elif expected is not None and len(items) < int(expected):
            log.info(
                "catalog %s residual gap %s vs expected %s (skip holes); skip contains net",
                kind, len(items), expected,
            )

    save_catalog(kind, items)
    log.info("catalog %s discovered %s expected=%s", kind, len(items), expected)
    return items



def discover(kinds: Optional[tuple[str, ...]] = None) -> list[dict]:
    queues = [
        ("constitution", "collection eq 'Constitution' and isInForce eq true"),
        ("act", "collection eq 'Act' and isInForce eq true"),
        ("legislative_instrument", "collection eq 'LegislativeInstrument' and isInForce eq true"),
    ]
    if kinds:
        queues = [q for q in queues if q[0] in kinds]
    items: list[dict] = []
    for kind, filt in queues:
        items.extend(page_titles(kind, filt))
    rank = {"constitution": 0, "act": 1, "legislative_instrument": 2}
    items.sort(key=lambda x: (rank.get(x.get("kind"), 9), x.get("id") or ""))
    return items


def b64_to_bytes(blob) -> Optional[bytes]:
    if blob is None:
        return None
    if isinstance(blob, bytes):
        if blob[:2] == b"PK" or blob[:4] == b"%PDF":
            return blob
        try:
            return base64.b64decode(blob)
        except Exception:
            return blob
    if isinstance(blob, str):
        s = blob.strip()
        if not s:
            return None
        if s.startswith("PK") or s.startswith("%PDF"):
            return s.encode("latin-1", "replace")
        try:
            return base64.b64decode(s)
        except Exception:
            return None
    return None


def epub_htmls(raw: bytes) -> list[str]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return []
    htmls = []
    names = [
        n for n in zf.namelist()
        if n.lower().endswith((".html", ".xhtml", ".htm"))
        and "nav" not in n.lower()
        and not n.lower().endswith("toc.xhtml")
    ]
    names.sort()
    for n in names:
        try:
            htmls.append(zf.read(n).decode("utf-8", "replace"))
        except Exception:
            continue
    return htmls


def docx_xml_text(raw: bytes) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        xml = zf.read("word/document.xml").decode("utf-8", "replace")
    except Exception:
        return ""
    xml = DOCX_WT.sub(lambda m: "\n" if "p" in m.group(0).lower() or "br" in m.group(0).lower() else m.group(0), xml)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return xml_to_text(xml)
    parts: list[str] = []
    for el in root.iter():
        tag = localtag(el.tag).lower()
        if tag == "t" and el.text:
            parts.append(el.text)
        elif tag in {"p", "br", "tab"}:
            parts.append("\n" if tag != "tab" else " ")
        if el.tail and localtag(el.tag).lower() == "t":
            parts.append(el.tail)
    text = "".join(parts)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def pdf_to_text(raw: bytes) -> str:
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(raw)
            tmp.flush()
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", tmp.name, "-"],
                check=False, capture_output=True, timeout=120,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.warning("pdftotext failed: %s", exc)
    return ""


def extract_sections_html(html: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    """Split compilation XHTML on CharSectno headings (ActHead5), skipping TOC."""
    heads: list[tuple[int, str, str]] = []
    for m in HEAD_P.finditer(html):
        attrs, inner = m.group(1), m.group(2)
        cls = " ".join(CLASS_ATTR.findall(attrs))
        if re.search(r"\bTOC\d*\b", cls, re.I):
            continue
        sm = CHAR_SECT.search(inner)
        if not sm:
            continue
        if "ActHead" not in cls and "CharSectno" not in inner:
            continue
        num = re.sub(r"\s+", "", html_to_text(sm.group(1)) or sm.group(1)).strip()
        heading = html_to_text(inner)
        heading = re.sub(r"\s+", " ", heading).strip()
        if not num:
            continue
        heads.append((m.start(), num, heading))
    if len(heads) < 2:
        return []
    # drop TOC-like duplicate run: first N heads that appear again later with same numbers
    docs: list[dict] = []
    seen: set[str] = set()
    for i, (start, num, heading) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(html)
        chunk_html = html[start:end]
        # cut endnotes from last section
        em = re.search(r'class="ENotesHeading', chunk_html)
        if em and i == len(heads) - 1:
            chunk_html = chunk_html[:em.start()]
        text = html_to_text(chunk_html)
        if not text or len(text) < 8:
            continue
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-") or f"s{i+1}"
        doc_id = f"{law_id}-s-{aid}"[:180]
        if doc_id in seen:
            doc_id = f"{law_id}-s-{aid}-{i+1}"[:180]
        seen.add(doc_id)
        docs.append({
            "id": doc_id,
            "title": (heading or f"Section {num}")[:500],
            "text": text,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "article_heading": heading,
            "law_identifier": law_id,
            "metadata": {
                "text_extraction": {"source": "official", "backend": "frl_epub_charsectno"},
                "unit": "section",
            },
        })
        if len(docs) >= 12000:
            break
    return docs


def extract_sections_text(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if docs:
        return docs
    # Australian numbered sections: "1  Short title" after the compilation preamble.
    body = text
    m = re.search(r"(?im)^(?:Contents|Table of provisions)\s*$", body)
    if m:
        # skip TOC: next occurrence of a numbered heading after a blank gap following TOC
        rest = body[m.end():]
        # find a repeated first section that looks like body (has following paragraph)
        body = rest
    matches = list(re.finditer(
        r"(?m)^(\d+[A-Z]{0,3})\s+([A-Z][^\n]{0,180})$",
        body,
    ))
    if len(matches) < 2:
        return []
    out = []
    seen: set[str] = set()
    for i, mm in enumerate(matches):
        start = mm.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunk = body[start:end].strip()
        if len(chunk) < 12:
            continue
        num = mm.group(1)
        heading = re.sub(r"\s+", " ", mm.group(0)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-s-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({
            "id": doc_id,
            "title": heading[:500],
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "article_heading": heading,
            "law_identifier": law_id,
            "metadata": {
                "text_extraction": {"source": "official", "backend": "frl_text_section_regex"},
                "unit": "section",
            },
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def _as_doc(data, fmt: str) -> Optional[dict]:
    """Normalise JSON-with-base64 or raw binary HTTP response into a dict with bytes."""
    if data is None:
        return None
    if isinstance(data, dict):
        if data.get("bytes") or data.get("contents"):
            return data
        return None
    content = getattr(data, "content", None)
    status = getattr(data, "status_code", None)
    if status not in (None, 200) or not content or len(content) < 40:
        return None
    ctype = ((getattr(data, "headers", None) or {}).get("content-type") or "").lower()
    if "json" in ctype or content[:1] in (b"{", b"["):
        return None
    if content[:2] not in (b"PK", b"%P") and not content[:4].startswith(b"%PDF"):
        # still accept if the format matches a zip/pdf magic after small header
        if fmt == "Epub" and content[:2] != b"PK":
            return None
        if fmt == "Word" and content[:2] != b"PK":
            return None
        if fmt == "Pdf" and not content.startswith(b"%PDF"):
            return None
    return {
        "bytes": content,
        "format": fmt,
        "extension": { "Epub": ".epub", "Word": ".docx", "Pdf": ".pdf" }.get(fmt),
        "sizeInBytes": len(content),
        "mimeType": ctype,
    }


def find_document(title_id: str, fmt: str, asat: str, volume: int = 0, register_id: Optional[str] = None) -> Optional[dict]:
    urls = []
    if register_id:
        urls.append(
            f"{API}/documents/find(registerId='{register_id}',type='Primary',format='{fmt}',"
            f"uniqueTypeNumber=0,volumeNumber={volume},rectificationSpecification='Latest')"
        )
    urls.append(
        f"{API}/documents/find(titleid='{title_id}',asatspecification='{asat}',"
        f"type='Primary',format='{fmt}',uniqueTypeNumber=0,volumeNumber={volume},"
        f"rectificationSpecification='Latest')"
    )
    urls.append(
        f"{API}/Documents/Find(titleid='{title_id}',asatspecification='{asat}',"
        f"type='Primary',format='{fmt}',uniqueTypeNumber=0,volumeNumber={volume},"
        f"rectificationSpecification='Latest')"
    )
    for url in urls:
        data = api_get(url, timeout=(20, 180), sleep=SLEEP)
        doc = _as_doc(data, fmt)
        if doc:
            return doc
    return None


def version_meta(title_id: str) -> dict:
    for asat in AS_AT:
        url = (
            f"{API}/Versions/Find(titleId='{title_id}',asAtSpecification='{asat}')"
            f"?$expand=documents"
        )
        data = api_get(url, timeout=(20, 90), sleep=SLEEP)
        if isinstance(data, dict) and data.get("titleId"):
            data["_asat"] = asat
            return data
    return {}


def available_volumes(ver: dict, fmt: str) -> list[int]:
    vols = []
    for d in ver.get("documents") or []:
        if not isinstance(d, dict):
            continue
        if (d.get("type") or "Primary") != "Primary":
            continue
        if (d.get("format") or "") != fmt:
            continue
        try:
            vols.append(int(d.get("volumeNumber") or 0))
        except Exception:
            vols.append(0)
    vols = sorted(set(vols))
    return vols or [0]


def fetch_text(title_id: str, ver: dict) -> tuple[str, str, str, list[str], dict]:
    """Return (text, html_join, format_used, html_parts, doc_meta)."""
    asat = ver.get("_asat") or "Latest"
    last_meta: dict = {}
    for fmt in FORMATS:
        htmls: list[str] = []
        texts: list[str] = []
        meta = None
        register_id = ver.get("registerId")
        for vol in available_volumes(ver, fmt):
            doc = find_document(title_id, fmt, asat, vol, register_id=register_id)
            if not doc:
                continue
            raw = b64_to_bytes(doc.get("bytes"))
            if not raw or len(raw) < 40:
                continue
            meta = {
                "format": fmt,
                "asat": asat,
                "volumeNumber": vol,
                "registerId": doc.get("registerId") or ver.get("registerId"),
                "compilationNumber": doc.get("compilationNumber") or ver.get("compilationNumber"),
                "extension": doc.get("extension"),
                "fileName": doc.get("fileName"),
                "sizeInBytes": doc.get("sizeInBytes") or len(raw),
                "isAuthorised": doc.get("isAuthorised"),
            }
            last_meta = meta
            if fmt == "Epub":
                parts = epub_htmls(raw)
                htmls.extend(parts)
                for h in parts:
                    t = html_to_text(h)
                    if t:
                        texts.append(t)
            elif fmt == "Word":
                t = docx_xml_text(raw)
                if t:
                    texts.append(t)
            elif fmt == "Pdf":
                t = pdf_to_text(raw)
                if t:
                    texts.append(t)
        text = "\n\n".join(t for t in texts if t).strip()
        html_join = "\n".join(htmls)
        if text and len(text) >= 20:
            return text, html_join, fmt, htmls, last_meta
    return "", "", "", [], last_meta


def document_type_for(it: dict) -> str:
    kind = (it.get("kind") or it.get("collection") or "").lower()
    if kind in {"act", "constitution"} or it.get("collection") in {"Act", "Constitution"}:
        return "statute" if kind != "constitution" else "constitution"
    return "regulation"


def fetch_one(it: dict, done: set[str]) -> str:
    tid = (it.get("id") or "").strip()
    if not tid:
        return "fail"
    rid = slug_id(CC, tid)
    if rid in done:
        return "skip"
    ver = version_meta(tid)
    text, html_join, fmt, htmls, doc_meta = fetch_text(tid, ver)
    if not text:
        log_failure(CC, {
            "identifier": tid,
            "source_url": f"{PORTAL}/{tid}",
            "status": "failed",
            "reason": "empty_text",
        })
        return "fail"
    title = it.get("name") or ver.get("name") or tid
    date = iso_date(ver.get("start") or it.get("makingDate"))
    making = iso_date(it.get("makingDate"))
    source_url = f"{PORTAL}/{tid}"
    docs: list[dict] = []
    if html_join:
        docs = extract_sections_html(html_join, rid, source_url, date)
    if len(docs) < 2:
        docs = extract_sections_text(text, rid, source_url, date)
    status_raw = (ver.get("status") or it.get("status") or "")
    if isinstance(status_raw, int):
        status_raw = {0: "InForce", 1: "Ceased", 2: "Repealed", 3: "NeverEffective"}.get(status_raw, str(status_raw))
    status_raw = str(status_raw)
    if it.get("isInForce") is True or status_raw == "InForce":
        law_status, is_cur = "current", True
    elif status_raw == "Repealed":
        law_status, is_cur = "repealed", False
    elif status_raw == "Ceased":
        law_status, is_cur = "historical", False
    else:
        law_status, is_cur = "unknown", None
    official = tid
    if it.get("year") and it.get("number") is not None:
        series = it.get("seriesType") or ("Act" if it.get("collection") == "Act" else "")
        official = f"{series} {it.get('number')}/{it.get('year')}".strip()
    register_id = ver.get("registerId") or doc_meta.get("registerId")
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=tid, title=title, text=text,
        source_url=source_url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="au-federal-register-legislation",
        eli=None, date=date, official_identifier=official,
        document_type=document_type_for(it),
        law_status=law_status, is_current=is_cur,
        documents=docs,
        extra_meta={
            "discovery": {
                "method": (
                    "odata_titles_filter_orderby_id"
                    if it.get("year") is None and it.get("kind") == "legislative_instrument"
                    else "odata_titles_filter"
                ),
                "catalog_identifier": tid,
                "seed_url": f"{API}/Titles",
                "api": API,
            },
            "official_metadata": {
                "title_id": tid,
                "register_id": register_id,
                "collection": it.get("collection"),
                "sub_collection": it.get("subCollection"),
                "is_principal": it.get("isPrincipal"),
                "status": status_raw,
                "year": it.get("year"),
                "number": it.get("number"),
                "series_type": it.get("seriesType"),
                "compilation_number": ver.get("compilationNumber") or doc_meta.get("compilationNumber"),
                "document_format": fmt or doc_meta.get("format"),
                "as_at": ver.get("_asat") or doc_meta.get("asat"),
                "optional_series_number": it.get("optionalSeriesNumber"),
                "has_commenced_unincorporated_amendments": it.get("hasCommencedUnincorporatedAmendments"),
            },
        },
        extra_fields={
            "canonical_title": title,
            "citation": title,
            "date_issued": making,
            "publication_date": making,
            "effective_date": date,
            "valid_from": date,
            "last_modified_date": iso_date(ver.get("registeredAt")),
            "law_version_identifier": register_id,
            "version_specific_identifier": register_id,
            "canonical_document_url": f"{PORTAL}/{tid}/latest/text",
            "information_url": f"{PORTAL}/{tid}/latest/details",
        },
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    return "ok"


def coverage_note(items: list[dict], ok: int, skip: int, fail: int) -> tuple[str, str]:
    n_act = sum(1 for x in items if x.get("kind") in {"act", "constitution"})
    n_li = sum(1 for x in items if x.get("kind") == "legislative_instrument")
    fetched_like = ok + skip
    acts_catalog = n_act
    if fail == 0 and fetched_like >= len(items) and n_li > 0:
        cov = "full"
    elif fetched_like >= acts_catalog and n_act > 0:
        cov = "catalog-backed incomplete"
    else:
        cov = "catalog-backed incomplete"
    notes = (
        f"In-force Commonwealth Constitution + Acts ({n_act} titles) then "
        f"in-force Legislative Instruments ({n_li} titles) from the Federal Register "
        f"of Legislation OData API ({API}). Text from compilation EPUB/Word/PDF via "
        f"documents/find. Year-null LIs catalogued with $orderby=id (unique sort) "
        f"because unpartitioned $skip misses rows. Notifiable instruments, gazettes, "
        f"as-made historical titles, and repealed laws are not in this snapshot. "
        f"Authorised PDF is not stored; the Register text prevails. CC BY 4.0."
    )
    return cov, notes


def run_pool(items: list[dict], done: set[str], counters: dict, all_items: list[dict], write_progress) -> None:
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
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            counters["ok"] += st == "ok"
            counters["skip"] += st == "skip"
            counters["fail"] += st == "fail"
            if n % 50 == 0 or n == len(items):
                log.info(
                    "progress %s/%s ok=%s skip=%s fail=%s",
                    n, len(items), counters["ok"], counters["skip"], counters["fail"],
                )
                cov, notes = coverage_note(all_items, counters["ok"], counters["skip"], counters["fail"])
                write_progress(cov, notes)


def main():
    setup()
    t0 = utcnow()
    # Acts first so a timeout still yields a coherent in-force Acts dump.
    act_items = discover(kinds=("constitution", "act"))
    counters = {"ok": 0, "skip": 0, "fail": 0}
    source_urls = [
        "https://www.legislation.gov.au/",
        "https://api.prod.legislation.gov.au/v1/",
        "https://api.prod.legislation.gov.au/swagger/index.html",
        "https://www.legislation.gov.au/terms-of-use",
        "https://www.legislation.gov.au/help-and-resources/using-the-legislation-register/data-share-and-reuse",
    ]
    all_items = list(act_items)

    def write_progress(coverage: str, notes: str, last: Optional[str] = None):
        write_summary(
            CC, country=COUNTRY,
            source="Federal Register of Legislation (Office of Parliamentary Counsel)",
            source_urls=source_urls, license_text=LICENSE,
            discovered=len(all_items), fetched=counters["ok"], skipped=counters["skip"],
            failed=counters["fail"], coverage=coverage, notes=notes,
            last_run=last or utcnow(),
        )

    fill_only = "--fill-li" in sys.argv or "--catalog-only" in sys.argv
    catalog_only = "--catalog-only" in sys.argv
    done = existing_ids(CC)
    if not fill_only:
        pending_acts = [it for it in act_items if slug_id(CC, (it.get("id") or "").strip()) not in done]
        log.info("queue constitution+acts=%s pending=%s already_done=%s", len(act_items), len(pending_acts), len(done))
        run_pool(pending_acts, done, counters, all_items, write_progress)
        log.info("acts phase done ok=%s skip=%s fail=%s", counters["ok"], counters["skip"], counters["fail"])
    else:
        log.info("fill-li: skip acts fetch; catalogued acts=%s done=%s", len(act_items), len(done))

    li_items = discover(kinds=("legislative_instrument",))
    all_items.extend(li_items)
    done = existing_ids(CC)
    pending_li = [it for it in li_items if slug_id(CC, (it.get("id") or "").strip()) not in done]
    log.info(
        "queue legislative_instruments=%s pending=%s already_done=%s",
        len(li_items), len(pending_li), len(done),
    )
    if catalog_only:
        log.info("catalog-only: not fetching %s pending LIs", len(pending_li))
    else:
        run_pool(pending_li, done, counters, all_items, write_progress)

    cov, notes = coverage_note(all_items, counters["ok"], counters["skip"], counters["fail"])
    if counters["fail"] == 0 and counters["ok"] + counters["skip"] >= len(all_items):
        cov = "full"
    notes = notes + f" Started {t0}."
    write_progress(cov, notes)
    log.info(
        "done ok=%s skip=%s fail=%s coverage=%s",
        counters["ok"], counters["skip"], counters["fail"], cov,
    )


if __name__ == "__main__":
    main()
