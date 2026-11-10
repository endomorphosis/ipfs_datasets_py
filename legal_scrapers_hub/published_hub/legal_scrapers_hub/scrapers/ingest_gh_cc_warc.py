#!/usr/bin/env python3
"""Ingest Ghana Act PDFs from Common Crawl WARC byte-ranges.

Reads /workspace/legal_scrapers/logs/gh_cc_urls.jsonl (CDX pointers),
Range-fetches https://data.commoncrawl.org/{filename}, gunzips the WARC
record, extracts %PDF…%%EOF, pdftotext, Section/Article splits, writes
instruments under legal-corpora/gh/.

Does NOT hit live ir.parliament.gh bitstream (DSpace SPA redirect).
No WAF bypass. No Hub upload. Caps compressed download budget.
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
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

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
from collect_gh import (
    ART_GH,
    CC,
    COUNTRY,
    LICENSE,
    SOURCE_TYPE,
    is_act_like,
    is_dspace_shell,
    pdf_to_text,
    split_gh,
)

URLS_PATH = Path("/workspace/legal_scrapers/logs/gh_cc_urls.jsonl")
LOG_PATH = ROOT / CC / "logs" / "ingest_cc_warc.log"
PROGRESS_PATH = ROOT / CC / "raw" / "ingest_cc_warc_progress.jsonl"
STATS_PATH = ROOT / CC / "raw" / "ingest_cc_warc_stats.json"

MAX_RECORD_LEN = 5_000_000          # skip larger WARC pointers
DOWNLOAD_BUDGET = 300 * 1024 * 1024  # 300 MiB compressed
MIN_DISK_FREE = 20 * 1024 ** 3       # stop if < 20 GiB free
MIN_TEXT = 800
SLEEP = 0.35

# Prefer true Acts / Bills / Codes; deprioritize committee reports / memos
ACT_NAME = re.compile(
    r"(?i)(?:^|[^A-Za-z])(?:ACT|BILL|CONSTITUTION|CODE)(?:[^A-Za-z]|$)"
)
REPORTISH = re.compile(
    r"(?i)\b(report of the committee|memorandum to parliament|budget statement|"
    r"annual budget|order.?paper|hansard|brochure)\b"
)
JUNK_STEM = re.compile(
    r"(?i)^(logo|brochure|order.?paper|hansard|l-?\.?i\.?-?s)"
)

log = logging.getLogger("gh_cc_warc")


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


def url_stem(url: str) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    # REAL+ESTATE+… → spaces
    name = name.replace("+", " ")
    return name.strip() or "document"


def title_from_stem(stem: str) -> str:
    t = re.sub(r"\s+", " ", stem.replace("_", " ").replace("%20", " ")).strip()
    return t[:240] or "Untitled"


def priority_key(rec: dict) -> tuple:
    """Sort key: act-ish first, then smaller length, then non-report."""
    url = unquote(rec.get("url") or "")
    stem = url_stem(url)
    blob = f"{stem} {url}"
    is_act = 0 if ACT_NAME.search(blob) else 1
    is_report = 0 if not REPORTISH.search(blob) else 1
    # Prefer filenames that look like ACT #### / named Act over opaque scans
    named = 0 if re.search(r"(?i)\bACT\b.*,?\s*\d{4}|\bACT\s*\(?\s*ACT\s*\d+", stem) else 1
    try:
        length = int(rec.get("length") or 0)
    except Exception:
        length = 10**12
    return (is_act, is_report, named, length)


def dedupe_rows(rows: list[dict]) -> list[dict]:
    """Keep one pointer per digest (or url stem if no digest). Prefer smaller length."""
    best: dict[str, dict] = {}
    for r in rows:
        dig = (r.get("digest") or "").strip()
        stem = url_stem(r.get("url") or "").lower()
        key = dig or f"stem:{stem}"
        try:
            ln = int(r.get("length") or 0)
        except Exception:
            ln = 10**12
        prev = best.get(key)
        if prev is None:
            best[key] = r
            continue
        try:
            pln = int(prev.get("length") or 0)
        except Exception:
            pln = 10**12
        # Prefer act-named URL if tied; else smaller
        if priority_key(r) < priority_key(prev) or (
            priority_key(r)[:3] == priority_key(prev)[:3] and ln < pln
        ):
            best[key] = r
    return list(best.values())


def extract_pdf_from_warc_bytes(raw: bytes) -> bytes:
    """Gunzip if needed, then locate %PDF … %%EOF."""
    data = raw
    if data[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(data)
        except Exception:
            try:
                data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
            except Exception:
                pass
    # Prefer HTTP-parsed body when present
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


def fetch_warc_pdf(rec: dict, max_bytes: int = MAX_RECORD_LEN) -> dict:
    """Range-fetch WARC record; return PDF bytes (not HTML shells)."""
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
    pdf = extract_pdf_from_warc_bytes(r.content)
    if not pdf or pdf[:4] != b"%PDF":
        # Maybe HTML DSpace shell was archived
        status, ctype, body = af._parse_warc_http(r.content)
        text = ""
        if body:
            text = body.decode("utf-8", "replace")
        return {
            "status": "error",
            "error": "no_pdf_in_warc",
            "downloaded": downloaded,
            "content_type": ctype,
            "text_head": (text or "")[:200],
        }
    return {
        "status": "success",
        "content": pdf,
        "downloaded": downloaded,
        "original_url": rec.get("url") or "",
        "method": "common_crawl_warc",
        "cc_record": {
            "filename": fn,
            "offset": off,
            "length": ln,
            "crawl": rec.get("crawl"),
            "timestamp": rec.get("timestamp"),
            "digest": rec.get("digest"),
        },
    }


def make_ident(stem: str, digest: str = "") -> str:
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", stem).strip("-").lower()[:90]
    if not clean:
        clean = (digest or "doc")[:16].lower()
    return f"gh-act-{clean}"


def normalize_title_key(title: str) -> str:
    t = re.sub(r"[^a-z0-9]+", " ", (title or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    # drop trailing act numbers for soft dedupe of near-dupes
    return t[:120]


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
        # also stem-ish
        keys.add(normalize_title_key(p.stem.replace("gh-act-", "").replace("-", " ")))
    return keys


def count_corpus() -> tuple[int, int]:
    d = ROOT / CC / "instruments"
    n = 0
    arts = 0
    if not d.exists():
        return 0, 0
    for p in d.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if is_dspace_shell(rec.get("text") or "", "") or "DSpace" in (rec.get("title") or ""):
            continue
        n += 1
        arts += len(rec.get("documents") or [])
    return n, arts


def append_progress(row: dict) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROGRESS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def process_one(
    rec: dict,
    done: set[str],
    title_keys: set[str],
) -> tuple[str, int, Optional[str]]:
    """Returns (status, downloaded_bytes, new_id_or_none)."""
    url = rec.get("url") or ""
    stem = url_stem(url)
    if JUNK_STEM.search(stem):
        return "skip_junk", 0, None
    # Skip non-parliament official hosts
    host = urlparse(url).netloc.lower()
    if not any(
        h in host
        for h in ("parliament.gh", "ir.parliament.gh", "repository.parliament.gh", "www.parliament.gh")
    ):
        return "skip_host", 0, None

    digest = (rec.get("digest") or "").strip()
    ident = make_ident(stem, digest)
    rid = slug_id(CC, ident)
    if rid in done or ident in done:
        return "skip_dup", 0, None

    soft = normalize_title_key(title_from_stem(stem))
    if soft and soft in title_keys:
        return "skip_title", 0, None

    try:
        ln = int(rec.get("length") or 0)
    except Exception:
        ln = 0
    if ln > MAX_RECORD_LEN:
        return "skip_large", 0, None

    res = fetch_warc_pdf(rec)
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

    pdf = res["content"]
    text = pdf_to_text(pdf)
    if is_dspace_shell(text):
        log_failure(CC, {"id": ident, "url": url, "status": "failed", "reason": "dspace_shell", "source": "cc_warc"})
        return "fail_dspace", downloaded, None
    if len(text) < MIN_TEXT or not is_act_like(text, title_from_stem(stem)):
        log_failure(
            CC,
            {
                "id": ident,
                "url": url,
                "status": "failed",
                "reason": "not_act_like_or_short",
                "chars": len(text),
                "source": "cc_warc",
            },
        )
        return "fail_short", downloaded, None

    title = title_from_stem(stem)
    head = text[:2500]
    m = re.search(
        r"(?im)^(AN ACT[^\n]+|[A-Z][A-Za-z0-9 ,.'()\-]{8,160}(?:ACT|BILL|CODE),?\s+\d{4})",
        head,
    )
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:240]
    if title.strip() in ("DSpace Repository :: Home", "Home") or is_dspace_shell(title):
        return "fail_title", downloaded, None

    tkey = normalize_title_key(title)
    if tkey in title_keys:
        return "skip_title", downloaded, None

    docs = split_gh(text, rid, url, None, False)
    record = base_record(
        cc=CC,
        country=COUNTRY,
        language="en",
        ident=ident,
        title=title,
        text=text,
        source_url=url,
        source_type=SOURCE_TYPE,
        license_text=LICENSE,
        collector="ingest_gh_cc_warc.py",
        date=None,
        official_identifier=title,
        document_type="statute",
        law_status="current",
        is_current=True,
        documents=docs,
        extra_meta={
            "discovery": {
                "method": "common_crawl_cdx",
                "crawl": rec.get("crawl"),
                "digest": digest,
            },
            "retrieval": {
                "method": "common_crawl_warc_range",
                "cc_record": res.get("cc_record"),
                "note": "Archived official parliament.gh / ir.parliament.gh PDF; not live bitstream",
            },
            "text_extraction": {"source": "official", "backend": "pdftotext"},
        },
    )
    record["id"] = rid
    write_instrument(CC, record)
    done.add(rid)
    title_keys.add(tkey)
    title_keys.add(normalize_title_key(stem))
    return "ok", downloaded, rid


def main() -> None:
    setup_logging()
    t0 = utcnow()
    max_new = int(os.environ.get("MAX_NEW", "80") or 80)
    max_seconds = int(os.environ.get("MAX_SECONDS", "5400") or 5400)
    act_only = os.environ.get("ACT_ONLY", "1") not in ("0", "false", "False")

    rows = load_rows(URLS_PATH)
    rows = dedupe_rows(rows)
    rows.sort(key=priority_key)
    if act_only:
        rows = [r for r in rows if priority_key(r)[0] == 0]

    done = existing_ids(CC)
    title_keys = existing_title_keys()
    laws0, arts0 = count_corpus()
    log.info(
        "start rows=%s act_only=%s already_ids=%s corpus=%s/%s free_disk=%.1fG budget=%sMB",
        len(rows),
        act_only,
        len(done),
        laws0,
        arts0,
        disk_free() / (1024**3),
        DOWNLOAD_BUDGET // (1024 * 1024),
    )

    counters = {
        "ok": 0,
        "fail": 0,
        "fail_dspace": 0,
        "fail_short": 0,
        "fail_title": 0,
        "skip_dup": 0,
        "skip_title": 0,
        "skip_large": 0,
        "skip_junk": 0,
        "skip_host": 0,
    }
    downloaded_total = 0
    new_ids: list[str] = []
    t_start = time.time()

    for n, rec in enumerate(rows, 1):
        if counters["ok"] >= max_new:
            log.info("stop: max_new=%s", max_new)
            break
        if time.time() - t_start > max_seconds:
            log.info("stop: max_seconds")
            break
        if downloaded_total >= DOWNLOAD_BUDGET:
            log.info("stop: download budget exceeded (%s)", downloaded_total)
            break
        free = disk_free()
        if free < MIN_DISK_FREE:
            log.info("stop: disk free %.1fG < 20G", free / (1024**3))
            break

        try:
            st, dl, new_id = process_one(rec, done, title_keys)
        except Exception as exc:
            st, dl, new_id = "fail", 0, None
            log.exception("process error %s: %s", rec.get("url"), exc)
            log_failure(CC, {"url": rec.get("url"), "status": "failed", "reason": repr(exc), "source": "cc_warc"})

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
        if n % 5 == 0 or st == "ok":
            laws, arts = count_corpus()
            log.info(
                "progress %s/%s st=%s ok=%s fail=%s skip_dup=%s skip_title=%s dl=%.1fMB corpus=%s/%s",
                n,
                len(rows),
                st,
                counters["ok"],
                counters["fail"]
                + counters["fail_dspace"]
                + counters["fail_short"]
                + counters["fail_title"],
                counters["skip_dup"],
                counters["skip_title"],
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
        "act_only": act_only,
    }
    atomic_write(STATS_PATH, json.dumps(stats, indent=2) + "\n")
    write_summary(
        CC,
        country=COUNTRY,
        source="Parliament of Ghana PDFs via Common Crawl WARC (archived official bitstreams)",
        source_urls=[
            "https://www.parliament.gh/",
            "https://ir.parliament.gh/",
            "https://data.commoncrawl.org/",
        ],
        license_text=LICENSE,
        discovered=len(rows),
        fetched=counters["ok"],
        skipped=sum(counters.get(k, 0) for k in counters if k.startswith("skip_")),
        failed=sum(counters.get(k, 0) for k in counters if k.startswith("fail")),
        coverage="official-cc-warc-act-pdfs",
        notes=(
            f"Ingested via ingest_gh_cc_warc.py from gh_cc_urls.jsonl. "
            f"Before {laws0}/{arts0}, after {laws}/{arts}. "
            f"Downloaded {downloaded_total} compressed WARC bytes. "
            f"DSpace shells rejected. No live IR bitstream. No Hub upload. "
            f"Started {t0}."
        ),
    )
    log.info("done counters=%s new=%s corpus=%s/%s dl=%.1fMB", counters, len(new_ids), laws, arts, downloaded_total / (1024 * 1024))
    print(json.dumps({"ok": counters["ok"], "laws": laws, "arts": arts, "new_ids": new_ids[:20], "dl_mb": round(downloaded_total / (1024 * 1024), 2)}, indent=2))


if __name__ == "__main__":
    main()
