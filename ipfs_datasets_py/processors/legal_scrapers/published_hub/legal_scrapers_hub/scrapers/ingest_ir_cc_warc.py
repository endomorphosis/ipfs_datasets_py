#!/usr/bin/env python3
"""Ingest Iran DOTIC laws from Common Crawl WARC byte-ranges.

Reads /workspace/legal_scrapers/logs/ir_cc_urls.jsonl (CDXJ pointers harvested
via S3 cluster.idx — not the live index.commoncrawl.org API).

- HTML news / law pages: BeautifulSoup text, RTL normalize, ماده splits
- PDFs: extract %PDF from WARC, pdftotext / OCR fallback

Official dotic.ir / media.dotic.ir content only via Common Crawl archive.
No live dotic hit required. No WAF bypass. No Hub upload.
"""
from __future__ import annotations

import gzip
import io
import json
import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    ROOT,
    atomic_write,
    base_record,
    ensure_dirs,
    existing_ids,
    log_failure,
    slug_id,
    utcnow,
    write_instrument,
    write_summary,
)
import archive_fallbacks as af
from collect_ir import ART, CC, COUNTRY, LANG, LICENSE, SOURCE_TYPE, pick_title
from pdf_extract_lib import extract_pdf_text, is_garbage_text, normalize_rtl_text
from world_lib import split_custom

URLS_PATH = Path("/workspace/legal_scrapers/logs/ir_cc_urls.jsonl")
LOG_PATH = ROOT / CC / "logs" / "ingest_cc_warc.log"
PROGRESS_PATH = ROOT / CC / "raw" / "ingest_cc_warc_progress.jsonl"
STATS_PATH = ROOT / CC / "raw" / "ingest_cc_warc_stats.json"

MAX_RECORD_LEN = 6_000_000
DOWNLOAD_BUDGET = 280 * 1024 * 1024  # 280 MiB compressed
MIN_DISK_FREE = 15 * 1024 ** 3
MIN_TEXT_HTML = 1200
MIN_TEXT_PDF = 100
# Broad ماده count (not line-anchored). DOTIC HTML often embeds ماده mid-line
# after footnotes/\r/controls; line-anchored ART then yields 0 and skip_thin
# wrongly rejects real statutes (e.g. قانون مجازات اسلامی with 1000+ ماده).
MIN_MADEH = int(os.environ.get("MIN_MADEH", "2") or 2)
SLEEP = 0.3

LAWISH_TITLE = re.compile(
    r"(قانون|آيين|آیین|اساسنامه|تصويب|تصویب|لايحه|لایحه|مقرره|نظامنامه|بخشنامه)"
)
NEWS_ID = re.compile(r"/news/(\d+)", re.I)
JUNK_PATH = re.compile(
    r"(?i)(/robots\.txt|/tags|/search|/cat/|/login|/register|\.css|\.js|/cdn-cgi/)"
)

log = logging.getLogger("ir_cc_warc")


def setup_logging() -> None:
    ensure_dirs(CC)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )


def disk_free(path: Path = ROOT) -> int:
    return shutil.disk_usage(path).free


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def html_to_plain(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html or "", "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    # Prefer main content regions when present
    main = (
        soup.find("div", id=re.compile(r"content|main|news", re.I))
        or soup.find("article")
        or soup.find("div", class_=re.compile(r"content|news|body|text", re.I))
        or soup.body
        or soup
    )
    plain = main.get_text("\n", strip=True)
    # DOTIC pages use \r and C0 controls around ماده markers; normalize so
    # line-anchored ART splits and broad counts both see real articles.
    plain = plain.replace("\r\n", "\n").replace("\r", "\n")
    plain = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", "\n", plain)
    plain = normalize_rtl_text(plain)
    title = normalize_rtl_text(title)
    return plain, title


def extract_pdf_from_warc_bytes(raw: bytes) -> bytes:
    data = raw
    if data[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(data)
        except Exception:
            try:
                data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
            except Exception:
                pass
    status, ctype, body = af._parse_warc_http(raw)
    if body and (body[:4] == b"%PDF" or b"%PDF" in body[:4096]):
        pdf = body
        idx = pdf.find(b"%PDF")
        if idx > 0:
            pdf = pdf[idx:]
        eof = pdf.rfind(b"%%EOF")
        if eof > 0:
            pdf = pdf[: eof + 5]
        if pdf[:4] == b"%PDF":
            return pdf
    idx = data.find(b"%PDF")
    if idx < 0:
        return b""
    pdf = data[idx:]
    eof = pdf.rfind(b"%%EOF")
    if eof > 0:
        pdf = pdf[: eof + 5]
    return pdf if pdf[:4] == b"%PDF" else b""


def fetch_warc(rec: dict, max_bytes: int = MAX_RECORD_LEN) -> dict:
    fn = rec.get("filename") or ""
    try:
        off = int(rec.get("offset") or 0)
        ln = int(rec.get("length") or 0)
    except Exception:
        return {"status": "error", "error": "bad_pointer", "downloaded": 0}
    if not fn or ln <= 0:
        return {"status": "error", "error": "missing_pointer", "downloaded": 0}
    if ln > MAX_RECORD_LEN:
        return {"status": "error", "error": "too_large", "downloaded": 0, "length": ln}
    fetch_ln = min(ln, max_bytes)
    url = fn if str(fn).startswith("http") else f"{af.CC_DATA}/{fn.lstrip('/')}"
    time.sleep(SLEEP)
    try:
        r = af.session().get(
            url,
            headers={"Range": f"bytes={off}-{off + fetch_ln - 1}"},
            timeout=(20, 120),
        )
    except Exception as exc:
        return {"status": "error", "error": str(exc), "downloaded": 0}
    downloaded = len(r.content or b"")
    if r.status_code not in (200, 206) or not r.content:
        return {
            "status": "error",
            "error": f"http_{r.status_code}",
            "downloaded": downloaded,
        }
    kind = (rec.get("kind") or "").lower()
    mime = (rec.get("mime") or "").lower()
    if kind == "pdf" or "pdf" in mime:
        pdf = extract_pdf_from_warc_bytes(r.content)
        if not pdf:
            return {
                "status": "error",
                "error": "no_pdf_in_warc",
                "downloaded": downloaded,
            }
        return {
            "status": "success",
            "content": pdf,
            "text": "",
            "downloaded": downloaded,
            "method": "common_crawl_warc_pdf",
            "cc_record": {
                "filename": fn,
                "offset": off,
                "length": ln,
                "crawl": rec.get("crawl"),
                "timestamp": rec.get("timestamp"),
                "digest": rec.get("digest"),
            },
        }
    # HTML path — reuse archive_fallbacks parser
    status, ctype, body = af._parse_warc_http(r.content)
    text = ""
    if body:
        text = body.decode("utf-8", "replace")
    if text and af.is_challenge(text, status or 200):
        return {
            "status": "error",
            "error": "challenge_or_shell",
            "downloaded": downloaded,
        }
    return {
        "status": "success",
        "content": body or b"",
        "text": text,
        "downloaded": downloaded,
        "method": "common_crawl_warc_html",
        "content_type": ctype,
        "cc_record": {
            "filename": fn,
            "offset": off,
            "length": ln,
            "crawl": rec.get("crawl"),
            "timestamp": rec.get("timestamp"),
            "digest": rec.get("digest"),
        },
    }


def news_id_from_url(url: str) -> Optional[str]:
    m = NEWS_ID.search(url or "")
    return m.group(1) if m else None


def make_ident(rec: dict, title: str = "") -> str:
    url = rec.get("url") or ""
    nid = news_id_from_url(url)
    if nid:
        return f"news-{nid}"
    path = unquote(urlparse(url).path)
    stem = Path(path).stem[:100]
    if stem and stem not in (".", "/"):
        clean = re.sub(r"[^a-zA-Z0-9\u0600-\u06FF._-]+", "-", stem).strip("-")[:90]
        if clean:
            return clean
    dig = (rec.get("digest") or "doc")[:16].lower()
    return f"cc-{dig}"


def normalize_title_key(title: str) -> str:
    t = normalize_rtl_text(title or "")
    t = re.sub(r"\s+", " ", t).strip().lower()
    # drop bidi / punctuation noise
    t = re.sub(r"[^\w\u0600-\u06FF\s]", "", t)
    return t[:140]


def existing_title_keys() -> set[str]:
    keys: set[str] = set()
    d = ROOT / CC / "instruments"
    if not d.exists():
        return keys
    for p in d.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        keys.add(normalize_title_key(rec.get("title") or p.stem))
    return keys


def count_corpus() -> tuple[int, int]:
    d = ROOT / CC / "instruments"
    n = arts = 0
    if not d.exists():
        return 0, 0
    for p in d.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if len(rec.get("text") or "") < 80:
            continue
        n += 1
        arts += len(rec.get("documents") or [])
    return n, arts


def count_madeh(text: str) -> int:
    """Quality-gate count: accept mid-line ماده (citations + real articles).
    Line-anchored ART is still used for article splitting via split_custom."""
    return len(re.findall(r"ماده\s*(?:واحده|\d+)", text or ""))


def priority_key(rec: dict) -> tuple:
    """Prefer HTML news laws with larger WARC length; PDFs secondary."""
    kind = 0 if rec.get("kind") == "html" else 1
    url = (rec.get("url") or "").lower()
    lawish = 0 if ("/news/" in url or "قانون" in unquote(url)) else 1
    try:
        length = -int(rec.get("length") or 0)  # larger first
    except Exception:
        length = 0
    return (kind, lawish, length)


def dedupe_rows(rows: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for r in rows:
        dig = (r.get("digest") or "").strip()
        nid = news_id_from_url(r.get("url") or "")
        stem = Path(unquote(urlparse(r.get("url") or "").path)).stem.lower()
        key = dig or (f"news:{nid}" if nid else f"stem:{stem}")
        prev = best.get(key)
        if prev is None or priority_key(r) < priority_key(prev):
            best[key] = r
    return list(best.values())


def append_progress(row: dict) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROGRESS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def process_one(
    rec: dict,
    done: set[str],
    title_keys: set[str],
) -> tuple[str, int, Optional[str]]:
    url = rec.get("url") or ""
    host = urlparse(url).netloc.lower()
    if "dotic.ir" not in host:
        return "skip_host", 0, None
    if JUNK_PATH.search(urlparse(url).path or ""):
        return "skip_junk", 0, None

    try:
        ln = int(rec.get("length") or 0)
    except Exception:
        ln = 0
    if ln > MAX_RECORD_LEN:
        return "skip_large", 0, None

    # Soft skip already-known news ids
    ident = make_ident(rec)
    rid = slug_id(CC, ident)
    if rid in done or ident in done:
        return "skip_dup", 0, None

    res = fetch_warc(rec)
    downloaded = int(res.get("downloaded") or 0)
    if res.get("status") != "success":
        log_failure(
            CC,
            {
                "id": ident,
                "url": url,
                "status": "failed",
                "reason": res.get("error"),
                "source": "cc_warc",
            },
        )
        return "fail", downloaded, None

    kind = rec.get("kind") or "html"
    text = ""
    title = ""
    method = res.get("method") or "common_crawl_warc"

    if kind == "pdf" or (res.get("content") or b"")[:4] == b"%PDF":
        pdf = res.get("content") or b""
        new_text, how, _pages = extract_pdf_text(
            pdf,
            enable_ocr=True,
            ocr_lang="ara",
            ocr_max_pages=int(os.environ.get("OCR_PAGES", "25") or 25),
        )
        text = normalize_rtl_text(new_text or "")
        method = f"{method}+{how}"
        if not text or len(text) < MIN_TEXT_PDF or is_garbage_text(text):
            log_failure(
                CC,
                {
                    "id": ident,
                    "url": url,
                    "status": "failed",
                    "reason": "pdf_short_or_garbage",
                    "chars": len(text or ""),
                    "source": "cc_warc",
                },
            )
            return "fail_short", downloaded, None
        title = pick_title(text, ident)
    else:
        plain, html_title = html_to_plain(res.get("text") or "")
        text = plain
        title = html_title or pick_title(text, ident)
        if len(text) < MIN_TEXT_HTML:
            return "fail_short", downloaded, None
        if not LAWISH_TITLE.search(title) and not LAWISH_TITLE.search(text[:800]):
            return "skip_not_law", downloaded, None
        if count_madeh(text) < MIN_MADEH:
            return "skip_thin_articles", downloaded, None
        if is_garbage_text(text):
            return "fail_short", downloaded, None

    tkey = normalize_title_key(title)
    if tkey and tkey in title_keys:
        return "skip_title", downloaded, None

    docs = split_custom(text, rid, url, None, ART)
    record = base_record(
        cc=CC,
        country=COUNTRY,
        language=LANG,
        ident=ident,
        title=title[:240] or ident,
        text=text,
        source_url=url,
        source_type=SOURCE_TYPE,
        license_text=LICENSE,
        collector="ingest_ir_cc_warc.py",
        date=None,
        official_identifier=title[:240],
        document_type="statute",
        law_status="current",
        is_current=True,
        documents=docs,
        extra_meta={
            "discovery": {
                "method": "common_crawl_cdxj_s3",
                "crawl": rec.get("crawl"),
                "digest": rec.get("digest"),
            },
            "retrieval": {
                "method": method,
                "cc_record": res.get("cc_record"),
                "note": "Archived official dotic.ir content via Common Crawl WARC; not live site",
            },
            "text_extraction": {
                "source": "official",
                "backend": "beautifulsoup" if "html" in method else "pdf",
            },
            "article_count_hint": count_madeh(text),
        },
    )
    record["id"] = rid
    write_instrument(CC, record)
    done.add(rid)
    if tkey:
        title_keys.add(tkey)
    return "ok", downloaded, rid


def main() -> None:
    setup_logging()
    t0 = utcnow()
    max_new = int(os.environ.get("MAX_NEW", "60") or 60)
    max_seconds = int(os.environ.get("MAX_SECONDS", "5400") or 5400)
    html_only = os.environ.get("HTML_ONLY", "1") not in ("0", "false", "False")

    rows = load_rows(URLS_PATH)
    rows = dedupe_rows(rows)
    if html_only:
        rows = [r for r in rows if r.get("kind") == "html"]
    reprocess_thin = os.environ.get("REPROCESS_THIN", "0") not in ("0", "false", "False")
    if reprocess_thin and PROGRESS_PATH.exists():
        thin_urls: set[str] = set()
        with PROGRESS_PATH.open(encoding="utf-8") as pf:
            for line in pf:
                line = line.strip()
                if not line:
                    continue
                try:
                    pr = json.loads(line)
                except Exception:
                    continue
                if pr.get("status") == "skip_thin_articles" and pr.get("url"):
                    thin_urls.add(pr["url"])
                    # http/https variants
                    u = pr["url"]
                    if u.startswith("http://"):
                        thin_urls.add("https://" + u[len("http://"):])
                    elif u.startswith("https://"):
                        thin_urls.add("http://" + u[len("https://"):])
        before = len(rows)
        rows = [r for r in rows if (r.get("url") or "") in thin_urls]
        log.info("REPROCESS_THIN filtered %s -> %s rows", before, len(rows))
    rows.sort(key=priority_key)

    done = existing_ids(CC)
    title_keys = existing_title_keys()
    laws0, arts0 = count_corpus()
    log.info(
        "start rows=%s html_only=%s already=%s corpus=%s/%s free=%.1fG budget=%sMB",
        len(rows),
        html_only,
        len(done),
        laws0,
        arts0,
        disk_free() / (1024**3),
        DOWNLOAD_BUDGET // (1024 * 1024),
    )

    counters: dict[str, int] = {}
    downloaded_total = 0
    new_ids: list[str] = []
    t_start = time.time()

    for n, rec in enumerate(rows, 1):
        if counters.get("ok", 0) >= max_new:
            log.info("stop: max_new=%s", max_new)
            break
        if time.time() - t_start > max_seconds:
            log.info("stop: max_seconds")
            break
        if downloaded_total >= DOWNLOAD_BUDGET:
            log.info("stop: download budget")
            break
        if disk_free() < MIN_DISK_FREE:
            log.info("stop: disk")
            break

        try:
            st, dl, new_id = process_one(rec, done, title_keys)
        except Exception as exc:
            st, dl, new_id = "fail", 0, None
            log.exception("process error %s: %s", rec.get("url"), exc)
            log_failure(
                CC,
                {
                    "url": rec.get("url"),
                    "status": "failed",
                    "reason": repr(exc),
                    "source": "cc_warc",
                },
            )

        downloaded_total += dl
        counters[st] = counters.get(st, 0) + 1
        if new_id:
            new_ids.append(new_id)
        append_progress(
            {
                "n": n,
                "status": st,
                "url": rec.get("url"),
                "id": new_id,
                "downloaded": dl,
                "budget_used": downloaded_total,
            }
        )
        if n % 10 == 0 or st == "ok":
            laws, arts = count_corpus()
            log.info(
                "progress %s/%s st=%s ok=%s fail=%s skip=%s dl=%.1fMB corpus=%s/%s",
                n,
                len(rows),
                st,
                counters.get("ok", 0),
                sum(v for k, v in counters.items() if k.startswith("fail")),
                sum(v for k, v in counters.items() if k.startswith("skip")),
                downloaded_total / (1024 * 1024),
                laws,
                arts,
            )

    laws, arts = count_corpus()
    stats = {
        "started": t0,
        "finished": utcnow(),
        "counters": counters,
        "downloaded_bytes": downloaded_total,
        "new_ids": new_ids,
        "corpus_before": {"laws": laws0, "articles": arts0},
        "corpus_after": {"laws": laws, "articles": arts},
        "disk_free_bytes": disk_free(),
        "html_only": html_only,
    }
    atomic_write(STATS_PATH, json.dumps(stats, indent=2) + "\n")
    write_summary(
        CC,
        country=COUNTRY,
        source="DOTIC Iran via Common Crawl WARC (archived official HTML/PDF)",
        source_urls=[
            "https://www.dotic.ir/",
            "https://data.commoncrawl.org/",
        ],
        license_text=LICENSE,
        discovered=len(rows),
        fetched=counters.get("ok", 0),
        skipped=sum(v for k, v in counters.items() if k.startswith("skip")),
        failed=sum(v for k, v in counters.items() if k.startswith("fail")),
        coverage="official-cc-warc-dotic-html-laws",
        notes=(
            f"Ingested via ingest_ir_cc_warc.py from ir_cc_urls.jsonl (S3 CDXJ). "
            f"Before {laws0}/{arts0}, after {laws}/{arts}. "
            f"Downloaded {downloaded_total} WARC bytes. No Hub upload. Started {t0}."
        ),
    )
    log.info(
        "done counters=%s new=%s corpus=%s/%s dl=%.1fMB",
        counters,
        len(new_ids),
        laws,
        arts,
        downloaded_total / (1024 * 1024),
    )
    print(
        json.dumps(
            {
                "ok": counters.get("ok", 0),
                "laws": laws,
                "arts": arts,
                "new_ids": new_ids[:30],
                "dl_mb": round(downloaded_total / (1024 * 1024), 2),
                "counters": counters,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
