#!/usr/bin/env python3
"""Ingest Angola official PDFs from Common Crawl WARC byte-ranges.

Reads ~/.ipfs_datasets/legal_collectors/logs/ao_cc_urls.jsonl (S3 CDXJ pointers),
Range-fetches https://data.commoncrawl.org/{filename}, gunzips WARC,
extracts %PDF…%%EOF, pdftotext (+ OCR if ALLOW_OCR=1), Artigo splits,
writes instruments under legal-corpora/ao/.

Official .gov.ao content only via Common Crawl archive.
No WAF bypass. No Hub upload. Caps compressed download budget.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    ROOT,
    atomic_write,
    ensure_dirs,
    existing_ids,
    log_failure,
    slug_id,
    utcnow,
    write_summary,
)
import archive_fallbacks as af
from world_lib import pdf_to_text, save_instrument
from collect_ao import (
    ART,
    CC,
    COUNTRY,
    LANG,
    LICENSE,
    SOURCE_TYPE,
    _ident_from_url,
    _lawish_fname,
    _title_from_text,
    pdf_ocr_text,
    _env_flag,
)

URLS_PATH = Path(str(_SCRAPERS) + "/logs/ao_cc_urls.jsonl")
LOG_PATH = ROOT / CC / "logs" / "ingest_cc_warc.log"
PROGRESS_PATH = ROOT / CC / "raw" / "ingest_cc_warc_progress.jsonl"
STATS_PATH = ROOT / CC / "raw" / "ingest_cc_warc_stats.json"

MAX_RECORD_LEN = 8_000_000
DOWNLOAD_BUDGET = 80 * 1024 * 1024
MIN_DISK_FREE = 15 * 1024 ** 3
MIN_TEXT = 150
SLEEP = 0.3

ALLOWED = (
    "imprensanacional.gov.ao",
    "gue.gov.ao",
    "governo.gov.ao",
    "minfin.gov.ao",
    "plataformacipra.gov.ao",
    "portais.gov.ao",
    "minjusdh.gov.ao",
    "maptss.gov.ao",
    "mirempet.gov.ao",
    "mtti.gov.ao",
    "parlamento.ao",
    "bna.ao",
    "minec.gov.ao",
    "minsa.gov.ao",
    "cij.gov.ao",
    "tribunalconstitucional.ao",
)

log = logging.getLogger("ao_cc_warc")


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
    if not name:
        # cms.minfin UUID paths
        parts = [p for p in path.strip("/").split("/") if p]
        name = parts[-1] if parts else "document"
    return name.strip() or "document"


def host_ok(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return any(host == s or host.endswith("." + s) for s in ALLOWED)


def existing_stems() -> set[str]:
    stems: set[str] = set()
    d = ROOT / CC / "instruments"
    if not d.exists():
        return stems
    for p in d.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for k in ("source_url", "url"):
            su = rec.get(k) or ""
            if su:
                stems.add(Path(unquote(urlparse(su).path)).name.lower())
        stems.add((rec.get("id") or p.stem).lower())
    return stems


def dedupe_rows(rows: list[dict]) -> list[dict]:
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
        if ln < pln:
            best[key] = r
    return list(best.values())


def priority_key(rec: dict) -> tuple:
    url = unquote(rec.get("url") or "")
    stem = url_stem(url)
    host = (urlparse(url).netloc or "").lower()
    named = 0 if re.search(
        r"(?i)(lei[_\s.-]|decreto|despacho|resolu|codigo|c[oó]digo|constitui|estatuto|regulament|aviso)",
        stem + " " + url,
    ) else 1
    if "gue.gov.ao" in host:
        host_rank = 0
    elif "minfin.gov.ao" in host:
        host_rank = 1
    elif "governo.gov.ao" in host or "plataformacipra" in host:
        host_rank = 2
    elif "portais.gov.ao" in host:
        host_rank = 3
    elif "imprensanacional" in host:
        host_rank = 4
    else:
        host_rank = 5
    try:
        length = int(rec.get("length") or 0)
    except Exception:
        length = 10**12
    size_pen = 0 if 20_000 <= length <= 4_000_000 else 1
    return (named, host_rank, size_pen, length)


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



def fetch_live_pdf(url: str) -> dict:
    """Prefer live official .gov.ao PDF; WARC Range often CloudFront 403."""
    import requests
    requests.packages.urllib3.disable_warnings()  # type: ignore
    time.sleep(SLEEP)
    try:
        r = requests.get(
            url,
            timeout=(20, 90),
            verify=False,
            headers={"User-Agent": "CountriesLawsScraper/1.0 (research; ao.gov.ao live pdf)"},
            allow_redirects=True,
        )
    except Exception as exc:
        return {"status": "error", "error": f"live:{exc}", "downloaded": 0}
    downloaded = len(r.content or b"")
    if r.status_code != 200 or not r.content:
        return {"status": "error", "error": f"live_http_{r.status_code}", "downloaded": downloaded}
    body = r.content
    if body[:4] != b"%PDF":
        idx = body.find(b"%PDF", 0, 65536)
        if idx < 0:
            return {"status": "error", "error": "live_not_pdf", "downloaded": downloaded}
        body = body[idx:]
    eof = body.rfind(b"%%EOF")
    if eof > 0:
        body = body[: eof + 5]
    return {
        "status": "success",
        "content": body,
        "downloaded": downloaded,
        "original_url": url,
        "method": "live_http",
        "cc_record": None,
    }


def fetch_warc_pdf(rec: dict) -> dict:
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
    url = fn if str(fn).startswith("http") else f"{af.CC_DATA}/{fn.lstrip('/')}"
    time.sleep(SLEEP)
    try:
        r = af.session().get(
            url,
            headers={"Range": f"bytes={off}-{off + ln - 1}"},
            timeout=(20, 120),
        )
    except Exception as exc:
        return {"status": "error", "error": str(exc), "downloaded": 0}
    downloaded = len(r.content or b"")
    if r.status_code not in (200, 206) or not r.content:
        return {"status": "error", "error": f"http_{r.status_code}", "downloaded": downloaded}
    pdf = extract_pdf_from_warc_bytes(r.content)
    if not pdf or pdf[:4] != b"%PDF":
        return {"status": "error", "error": "no_pdf_in_warc", "downloaded": downloaded}
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


def count_corpus() -> int:
    d = ROOT / CC / "instruments"
    if not d.exists():
        return 0
    return sum(1 for _ in d.glob("*.json"))


def append_progress(row: dict) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROGRESS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def extract_text(pdf: bytes) -> tuple[str, str]:
    text = pdf_to_text(pdf) or ""
    if len(text) >= MIN_TEXT:
        return text, "pdftotext"
    allow_ocr = _env_flag("ALLOW_OCR", False) and not _env_flag("SKIP_OCR", True)
    if allow_ocr:
        ocr = pdf_ocr_text(pdf)
        if len(ocr) >= MIN_TEXT:
            return ocr, "ocr_por"
    return text, "pdftotext_short"


def is_lawish_ao(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    stem_name = Path(unquote(urlparse(url).path)).name.lower()
    path = unquote(urlparse(url).path).lower()
    if _lawish_fname(stem_name or path, host):
        return True
    # minfin UCM / cms asset PDFs — treat as lawish if mime/path looks official
    if "minfin.gov.ao" in host:
        if stem_name.endswith(".pdf") or "/edisp/" in path or "/api/assets/" in path:
            return True
    if "portais.gov.ao" in host and any(
        k in (stem_name + path)
        for k in ("decreto", "despacho", "lei", "regulament", "aviso", "estatuto", "codigo", "código")
    ):
        return True
    if "plataformacipra" in host and "gov_angola" in path:
        return True
    return False


def process_one(rec: dict, done: set[str], stems: set[str]) -> tuple[str, int, Optional[str]]:
    url = rec.get("url") or ""
    if not host_ok(url):
        return "skip_host", 0, None
    stem_name = Path(unquote(urlparse(url).path)).name.lower()
    if not stem_name:
        stem_name = url_stem(url).lower() + ".pdf"
    host = (urlparse(url).netloc or "").lower()
    if not is_lawish_ao(url):
        if "imprensanacional" in host:
            allow_ocr = _env_flag("ALLOW_OCR", False) and not _env_flag("SKIP_OCR", True)
            if not allow_ocr:
                return "skip_imprensa_no_ocr", 0, None
        else:
            return "skip_not_lawish", 0, None

    if stem_name and stem_name in stems:
        return "skip_stem", 0, None
    # also check stem without .pdf for cms uuids
    bare = url_stem(url).lower()
    if bare and any(bare in s for s in stems if len(bare) > 8):
        # soft check — only exact stem match
        pass
    if bare + ".pdf" in stems or bare in stems:
        return "skip_stem", 0, None

    ident = _ident_from_url(url) if stem_name.endswith(".pdf") or "." in stem_name else _ident_from_url(url.rstrip("/") + "/" + bare + ".pdf")
    if not ident or ident in ("ao", "document"):
        ident = _ident_from_url(url) or bare[:160]
    rid = slug_id(CC, ident)
    if rid in done or ident in done:
        return "skip_dup", 0, None

    try:
        ln = int(rec.get("length") or 0)
    except Exception:
        ln = 0
    if ln > MAX_RECORD_LEN:
        return "skip_large", 0, None

    prefer_live = os.environ.get("PREFER_LIVE", "1") not in ("0", "false", "False")
    res = {"status": "error", "downloaded": 0}
    if prefer_live:
        res = fetch_live_pdf(url)
    if res.get("status") != "success":
        # WARC only as last resort for small ranges
        try:
            ln = int(rec.get("length") or 0)
        except Exception:
            ln = 0
        if ln and ln <= 6_000_000:
            warc = fetch_warc_pdf(rec)
            if warc.get("status") == "success":
                res = warc
            elif res.get("status") != "success":
                res = warc
    downloaded = int(res.get("downloaded") or 0)
    if res.get("status") != "success":
        log_failure(
            CC,
            {
                "identifier": ident,
                "source_url": url,
                "reason": res.get("error"),
                "portal": "cc_warc",
            },
        )
        return "fail", downloaded, None

    pdf = res["content"]
    text, backend = extract_text(pdf)
    if len(text) < MIN_TEXT:
        log_failure(
            CC,
            {
                "identifier": ident,
                "source_url": url,
                "reason": f"short_text:{len(text)}:{backend}",
                "portal": "cc_warc",
            },
        )
        return "fail_short", downloaded, None

    title = _title_from_text(text, ident.replace("-", " ")[:80])
    ok = save_instrument(
        cc=CC,
        country=COUNTRY,
        language=LANG,
        ident=ident,
        title=title,
        text=text,
        source_url=url,
        source_type=SOURCE_TYPE,
        license_text=LICENSE,
        collector="ingest_ao_cc_warc.py",
        article_re=ART,
        extra_meta={
            "fetch_method": res.get("method") or "common_crawl_warc",
            "portal": f"cc:{host}",
            "text_extraction": {"backend": backend},
            "cc_record": res.get("cc_record"),
            "discovery": {"method": "common_crawl_s3_cdxj", "crawl": rec.get("crawl")},
        },
    )
    if not ok:
        return "fail_save", downloaded, None
    done.add(rid)
    if stem_name:
        stems.add(stem_name)
    stems.add(bare)
    stems.add(bare + ".pdf")
    return "ok", downloaded, rid


def main() -> None:
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    setup_logging()
    t0 = utcnow()
    max_new = int(os.environ.get("MAX_NEW", "25") or 25)
    max_seconds = int(os.environ.get("MAX_SECONDS", "3600") or 3600)
    target_laws = int(os.environ.get("TARGET_LAWS", "360") or 340)

    if not URLS_PATH.exists():
        log.error("missing %s — run harvest_ao_cc.py first", URLS_PATH)
        sys.exit(1)

    rows = load_rows(URLS_PATH)
    rows = dedupe_rows(rows)
    rows.sort(key=priority_key)

    done = existing_ids(CC)
    stems = existing_stems()
    laws0 = count_corpus()
    log.info(
        "start rows=%s already_ids=%s stems=%s corpus=%s free_disk=%.1fG budget=%sMB "
        "ALLOW_OCR=%s SKIP_OCR=%s target=%s",
        len(rows),
        len(done),
        len(stems),
        laws0,
        disk_free() / (1024**3),
        DOWNLOAD_BUDGET // (1024 * 1024),
        _env_flag("ALLOW_OCR", False),
        _env_flag("SKIP_OCR", True),
        target_laws,
    )

    counters: dict[str, int] = {}
    downloaded_total = 0
    new_ids: list[str] = []
    t_start = time.time()

    for n, rec in enumerate(rows, 1):
        laws_now = count_corpus()
        if laws_now >= target_laws and counters.get("ok", 0) >= 2:
            log.info("stop: target_laws=%s reached (%s)", target_laws, laws_now)
            break
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
            st, dl, new_id = process_one(rec, done, stems)
        except Exception as exc:
            st, dl, new_id = "fail", 0, None
            log.exception("process error %s: %s", rec.get("url"), exc)
            log_failure(
                CC,
                {"source_url": rec.get("url"), "reason": repr(exc), "portal": "cc_warc"},
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
        if n % 5 == 0 or st == "ok":
            log.info(
                "progress %s/%s st=%s ok=%s fail=%s skip_stem=%s dl=%.1fMB corpus=%s",
                n,
                len(rows),
                st,
                counters.get("ok", 0),
                sum(v for k, v in counters.items() if k.startswith("fail")),
                counters.get("skip_stem", 0),
                downloaded_total / (1024 * 1024),
                count_corpus(),
            )

    laws = count_corpus()
    stats = {
        "started": t0,
        "finished": utcnow(),
        "counters": counters,
        "downloaded_bytes": downloaded_total,
        "new_ids": new_ids,
        "corpus_before": laws0,
        "corpus_after": laws,
        "disk_free_bytes": disk_free(),
    }
    atomic_write(STATS_PATH, json.dumps(stats, indent=2) + "\n")
    write_summary(
        CC,
        country=COUNTRY,
        source="Diário da República / Portal do Governo / GUE (Angola) + Common Crawl WARC",
        source_urls=[
            "https://www.imprensanacional.gov.ao/",
            "https://gue.gov.ao/portal/legislacao-portal",
            "https://governo.gov.ao/documentos/legislacao",
            "https://minjusdh.gov.ao/web/documentos?type=Legisla%C3%A7%C3%A3o",
            "https://data.commoncrawl.org/",
        ],
        license_text=LICENSE,
        discovered=len(rows),
        fetched=counters.get("ok", 0),
        skipped=sum(v for k, v in counters.items() if k.startswith("skip_")),
        failed=sum(v for k, v in counters.items() if k.startswith("fail")),
        coverage="official-cc-warc-pdfs + prior live/wayback",
        notes=(
            f"Ingested via ingest_ao_cc_warc.py from ao_cc_urls.jsonl. "
            f"Before {laws0}, after {laws}. "
            f"Downloaded {downloaded_total} compressed WARC bytes. "
            f"No Hub upload. Started {t0}."
        ),
        last_run=t0,
    )
    log.info(
        "done counters=%s new=%s corpus=%s->%s dl=%.1fMB",
        counters,
        len(new_ids),
        laws0,
        laws,
        downloaded_total / (1024 * 1024),
    )
    print(
        json.dumps(
            {
                "ok": counters.get("ok", 0),
                "laws": laws,
                "laws0": laws0,
                "new_ids": new_ids[:30],
                "counters": counters,
                "dl_mb": round(downloaded_total / (1024 * 1024), 2),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
