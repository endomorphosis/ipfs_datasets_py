#!/usr/bin/env python3
"""Sri Lanka: Constitution + Acts from official government hosts.

Official only:
  - Parliament Secretariat constitution PDF
      https://www.parliament.lk/files/pdf/constitution.pdf
      (printed at the Department of Government Printing)
  - Department of Government Printing Acts
      https://www.documents.gov.lk/view/acts/
    Live TLS to documents.gov.lk failed from this host; texts from Wayback /
    Common Crawl of those official Act PDF URLs (archive_fallbacks on 429).

LawNet is not used (not confirmed here as the government portal serving official
text; documents.gov.lk / parliament.lk are). No commercial DBs. No WAF bypass.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "lk"
COUNTRY = "Sri Lanka"
SOURCE_TYPE = "lk_official"
LICENSE = (
    "Official texts of the Democratic Socialist Republic of Sri Lanka as published "
    "by the Department of Government Printing (documents.gov.lk) and the Parliament "
    "Secretariat. The authentic Gazette / printed Act prevails. Parliament's "
    "constitution PDF is labelled an unofficial consolidation of official amendments. "
    "Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.documents.gov.lk/"
CONST = "https://www.parliament.lk/files/pdf/constitution.pdf"
CONST_ALT = "https://www.parliament.lk/files/pdf/constitution/constitution-upto-21st.pdf"
ACTS_PREFIX = "https://www.documents.gov.lk/view/acts/"
SLEEP = 0.45
log = logging.getLogger("lk")
ART_LK = re.compile(
    r"(?im)^\s*((?:Article|Section|CHAPTER)\s+[\dIVXLCDM]+[A-Za-z]?)\b"
)
ACT_PDF_RE = re.compile(
    r"documents\.gov\.lk/view/acts/.+\.pdf",
    re.I,
)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def pdf_to_text(raw: bytes) -> str:
    if not raw or raw[:4] != b"%PDF":
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(raw)
            tmp.flush()
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", tmp.name, "-"],
                check=False, capture_output=True, timeout=180,
            )
        if proc.returncode == 0 and proc.stdout:
            text = proc.stdout.decode("utf-8", "replace").strip()
            if len(text) >= 120:
                return text
    except Exception as exc:
        log.warning("pdftotext: %s", exc)
    return ocr_pdf(raw)


def ocr_pdf(raw: bytes) -> str:
    """Image-only Department of Government Printing PDFs (no text layer)."""
    try:
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "act.pdf"
            pdf.write_bytes(raw)
            proc = subprocess.run(
                ["pdftoppm", "-png", "-r", "180", str(pdf), str(Path(td) / "p")],
                check=False, capture_output=True, timeout=180,
            )
            if proc.returncode != 0:
                log.warning("pdftoppm: %s", (proc.stderr or b"")[:200])
                return ""
            pages = sorted(Path(td).glob("p*.png"))
            chunks = []
            for img in pages[:80]:
                tproc = subprocess.run(
                    ["tesseract", str(img), "stdout", "-l", "eng", "--psm", "6"],
                    check=False, capture_output=True, timeout=120,
                )
                if tproc.returncode == 0 and tproc.stdout:
                    chunks.append(tproc.stdout.decode("utf-8", "replace").strip())
            return "\n\n".join(c for c in chunks if c).strip()
    except Exception as exc:
        log.warning("ocr_pdf: %s", exc)
        return ""


def get_official(url: str, *, timeout=(20, 120), retries: int = 3) -> dict:
    if "documents.gov.lk" in url:
        log.info("documents.gov.lk live TLS skipped — wayback of official URL %s", url)
        res = af.fetch_with_fallbacks(url, try_http=False, try_cc=False)
        res.setdefault("retrieval", "archive")
        return res
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=timeout, retries=retries)
    except Exception as exc:
        log.info("live fail %s: %s — archive of official URL", url, exc)
        res = af.fetch_with_fallbacks(url, try_http=False, try_cc=False)
        res.setdefault("retrieval", "archive")
        return res
    status = r.status_code
    body = r.content or b""
    ctype = (r.headers.get("content-type") or "").lower()
    text = ""
    if body[:4] == b"%PDF":
        return {
            "status": "success", "content": body, "text": "",
            "content_type": ctype or "application/pdf", "original_url": url,
            "http_status": 200, "method": "http", "final_url": r.url or url,
            "retrieval": "live",
        }
    if body and ("html" in ctype or "xml" in ctype or "text/" in ctype or not ctype):
        text = body.decode(r.encoding or "utf-8", "replace")
    if status == 429:
        log.info("HTTP 429 %s — archive_fallbacks", url)
        res = af.fetch_with_fallbacks(url, try_http=False, try_cc=False)
        res.setdefault("retrieval", "archive")
        return res
    if status == 200 and body:
        if text and af.is_challenge(text, status) and len(body) < 4000:
            res = af.fetch_with_fallbacks(url, try_http=False, try_cc=False)
            res.setdefault("retrieval", "archive")
            return res
        return {
            "status": "success", "content": body, "text": text, "content_type": ctype,
            "original_url": url, "http_status": status, "method": "http",
            "final_url": r.url or url, "retrieval": "live",
        }
    if status in (404, 410):
        return {"status": "error", "error": f"http_{status}", "http_status": status, "retrieval": "live"}
    res = af.fetch_with_fallbacks(url, try_http=False, try_cc=False)
    res.setdefault("retrieval", "archive")
    return res


def catalog_path() -> Path:
    return ROOT / CC / "raw" / "catalog.jsonl"


def load_catalog() -> list[dict]:
    p = catalog_path()
    if not p.exists() or p.stat().st_size < 40:
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


def save_catalog(items: list[dict]) -> None:
    atomic_write(catalog_path(), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items))


def act_key(url: str) -> str:
    path = unquote((url or "").split("?")[0]).lower()
    path = re.sub(r"^https?://(www\.)?", "", path)
    # prefer English PDF when both language versions exist
    path = path.replace("_e.pdf", "_e.pdf")
    return path.rstrip("/")


def prefer_english(url: str) -> bool:
    u = (url or "").lower()
    return u.endswith("_e.pdf") or "/e/" in u or "_en.pdf" in u or u.endswith("e.pdf")


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 10:
        log.info("resume catalog n=%s", len(existing))
        return existing
    items: list[dict] = [{
        "url": CONST, "title": "Constitution of the Democratic Socialist Republic of Sri Lanka",
        "kind": "constitution", "fallback": [CONST_ALT],
    }]
    recs = af.search_wayback_machine(
        ACTS_PREFIX, match_type="prefix", limit=2500,
        extra_filters=["mimetype:application/pdf"],
    )
    recs += af.search_wayback_machine(
        "http://www.documents.gov.lk/view/acts/", match_type="prefix", limit=800,
        extra_filters=["mimetype:application/pdf"],
    )
    log.info("wayback documents.gov.lk acts cdx=%s", len(recs))
    best: dict[str, dict] = {}
    for rec in recs:
        orig = rec.get("original") or ""
        if not ACT_PDF_RE.search(orig):
            continue
        # skip gazette extras if they slipped in
        low = orig.lower()
        if "/egz/" in low or "/gz/" in low:
            continue
        key = act_key(orig)
        ts = rec.get("timestamp") or ""
        prev = best.get(key)
        score = (1 if prefer_english(orig) else 0, ts)
        prev_score = (1 if prev and prefer_english(prev["url"]) else 0, (prev or {}).get("wayback_ts") or "")
        if prev is None or score > prev_score:
            stem = Path(unquote(orig.split("?")[0])).stem
            title = stem.replace("_", " ").replace("-", " ")
            # canonicalize https www
            url = orig
            if url.startswith("http://"):
                url = "https://" + url[len("http://"):]
            if "://documents.gov.lk/" in url:
                url = url.replace("://documents.gov.lk/", "://www.documents.gov.lk/")
            best[key] = {
                "url": url, "title": title, "kind": "act",
                "wayback_ts": ts, "cdx_original": orig,
            }
    # collapse language variants: keep English if we have both same number/year
    collapsed: dict[str, dict] = {}
    for key, it in best.items():
        m = re.search(r"/acts/(\d{4})/(\d+)", key)
        base = f"{m.group(1)}-{m.group(2)}" if m else key
        prev = collapsed.get(base)
        if prev is None:
            collapsed[base] = it
        elif prefer_english(it["url"]) and not prefer_english(prev["url"]):
            collapsed[base] = it
    items.extend(collapsed.values())
    save_catalog(items)
    log.info("catalog n=%s", len(items))
    return items


def split_lk(text: str, law_id: str, source_url: str, date: Optional[str], constitution: bool) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_LK.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        chunk = text[m.start(): (matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({
            "id": doc_id, "title": chunk.split("\n", 1)[0][:200], "text": chunk,
            "date_filed": date, "document_number": num, "source_url": source_url,
            "record_type": "article", "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "lk"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def fetch_pdf(url: str, wayback_ts: Optional[str] = None) -> tuple[str, str, str]:
    if "documents.gov.lk" in url:
        last = ""
        for attempt in range(3):
            wb = af.get_wayback_content(url, timestamp=wayback_ts)
            body = wb.get("content") or b""
            last = wb.get("error") or wb.get("status") or ""
            if body[:4] == b"%PDF":
                text = pdf_to_text(body)
                if len(text) >= 120:
                    return text, "archive", wb.get("wayback_url") or url
                last = "empty_pdftotext"
            else:
                last = last or f"not_pdf magic={body[:12]!r} http={wb.get('http_status')}"
            log.info("wayback pdf miss %s ts=%s %s", url, wayback_ts, last)
        return "", "fail", url
    res = get_official(url)
    body = res.get("content") or b""
    if res.get("status") == "success" and body[:4] == b"%PDF":
        text = pdf_to_text(body)
        if len(text) >= 120:
            return text, res.get("retrieval") or "live", res.get("final_url") or url
    wb = af.get_wayback_content(url, timestamp=wayback_ts)
    body = wb.get("content") or b""
    if wb.get("status") == "success" and body[:4] == b"%PDF":
        text = pdf_to_text(body)
        if len(text) >= 120:
            return text, "archive", wb.get("wayback_url") or url
    return "", res.get("retrieval") or "fail", url


def fetch_one(it: dict, done: set[str]) -> str:
    kind = it.get("kind")
    url = it["url"]
    if kind == "constitution":
        ident = "lk-constitution-1978"
        rid = slug_id(CC, ident)
        if rid in done:
            return "skip"
        text, retrieval, used = fetch_pdf(url, it.get("wayback_ts"))
        if len(text) < 400:
            for fb in it.get("fallback") or []:
                text, retrieval, used = fetch_pdf(fb)
                if len(text) >= 400:
                    url = fb
                    break
        if len(text) < 400:
            log_failure(CC, {"id": ident, "url": url, "status": "failed", "reason": "constitution_empty"})
            return "fail"
        rec = base_record(
            cc=CC, country=COUNTRY, language="en", ident=ident,
            title="Constitution of the Democratic Socialist Republic of Sri Lanka",
            text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
            collector="collect_lk.py", date="1978-09-07",
            official_identifier="Constitution of Sri Lanka (as amended, Parliament Secretariat 2023 edition)",
            document_type="constitution", law_status="current", is_current=True,
            documents=split_lk(text, rid, url, "1978-09-07", True),
            extra_meta={
                "discovery": {"method": "parliament_secretariat_pdf"},
                "retrieval": {"method": retrieval, "used_url": used},
                "text_extraction": {"source": "official", "backend": "pdftotext"},
                "gaps": "Parliament Secretariat 2023 revised edition (unofficial consolidation of official amendments up to 21st Amendment); authentic Gazette text prevails.",
            },
        )
        rec["id"] = rid
        write_instrument(CC, rec)
        done.add(rid)
        return "ok"
    stem = Path(unquote(url.split("?")[0])).stem
    ident = "lk-act-" + re.sub(r"[^a-zA-Z0-9]+", "-", stem)[:100]
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    text, retrieval, used = fetch_pdf(url, it.get("wayback_ts"))
    if len(text) < 120:
        log_failure(CC, {"id": ident, "url": url, "status": "failed", "reason": "empty_pdf"})
        return "fail"
    title = it.get("title") or stem
    m = re.search(r"(?im)^((?:AN ACT|Act,?\s+No\.?\s+\d+)[^\n]{0,160})", text[:2500])
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:240]
    ym = re.search(r"/acts/(\d{4})/", url)
    date = f"{ym.group(1)}-01-01" if ym else None
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident, title=title, text=text,
        source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_lk.py", date=date, official_identifier=stem,
        document_type="statute", law_status="current", is_current=True,
        documents=split_lk(text, rid, url, date, False),
        extra_meta={
            "discovery": {"method": "documents.gov.lk_acts_cdx", "cdx_original": it.get("cdx_original")},
            "retrieval": {"method": retrieval, "used_url": used},
            "text_extraction": {"source": "official", "backend": "pdftotext"},
        },
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def write_progress(items, counters, coverage, extra=""):
    notes = (
        "Constitution from Parliament Secretariat official PDF (printed at the "
        "Department of Government Printing). Acts from documents.gov.lk/view/acts/ "
        "via Wayback/Common Crawl of those official PDF URLs (live TLS to "
        "documents.gov.lk failed from this host; archive_fallbacks on 429). LawNet "
        "not used. English PDFs preferred when language variants exist. "
        + extra
    )
    write_summary(
        CC, country=COUNTRY,
        source="Department of Government Printing + Parliament Secretariat",
        source_urls=[ACTS_PREFIX, "https://www.documents.gov.lk/view/acts/acts.html", CONST, CONST_ALT],
        license_text=LICENSE, discovered=len(items), fetched=counters["ok"],
        skipped=counters["skip"], failed=counters["fail"], coverage=coverage, notes=notes,
    )


def main():
    setup()
    t0 = utcnow()
    items = discover()
    counters = {"ok": 0, "skip": 0, "fail": 0}
    done = existing_ids(CC)
    log.info("queue n=%s already=%s", len(items), len(done))
    for n, it in enumerate(items, 1):
        try:
            st = fetch_one(it, done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"url": it.get("url"), "status": "failed", "reason": repr(exc)})
        counters[st] = counters.get(st, 0) + 1
        if n % 15 == 0 or n == len(items):
            log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items),
                     counters["ok"], counters["skip"], counters["fail"])
            write_progress(items, counters, "catalog-backed incomplete")
    cov = "snapshot"
    if counters["ok"] + counters["skip"] >= 1:
        cov = "official-hosted-snapshot"
    write_progress(items, counters, cov, extra=f"Started {t0}.")
    atomic_write(ROOT / CC / "raw" / "stats.json", json.dumps({
        "discovered": len(items), **counters, "coverage": cov,
        "started": t0, "finished": utcnow(),
    }, indent=2) + "\n")
    log.info("done %s", counters)


if __name__ == "__main__":
    main()
