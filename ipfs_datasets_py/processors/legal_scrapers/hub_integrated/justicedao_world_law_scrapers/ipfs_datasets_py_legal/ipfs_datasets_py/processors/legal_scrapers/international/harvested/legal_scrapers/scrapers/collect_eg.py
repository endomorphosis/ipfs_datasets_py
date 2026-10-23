#!/usr/bin/env python3
"""Egypt: Constitution + laws from official government hosts.

Official only:
  - Presidency constitution PDF: presidency.eg (2014 Constitution as amended 2019)
  - Cabinet landing: cabinet.gov.eg/StaticContent/Constitution (official host; chrome shell)
  - الهيئة العامة لشئون المطابع الأميرية (alamiria.com) TashTxt pages — official printer
    of الجريدة الرسمية / الوقائع المصرية. Homepage items + Wayback of official TashTxt URLs.

NOT used: manshurat.org (unofficial compilation); alamiria.laalaws.com / law-pub.com
(commercial). elpai.idsc.gov.eg search results are subscriber-only — no paywall bypass;
Wayback is used only for official URLs. Archive.aspx on alamiria redirects to login
(print-from-archive service) and is not fetched. alamiria.moj.gov.eg did not resolve;
egypt.gov.eg TLS failed from this host.
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
from urllib.parse import quote, urljoin, urlparse, parse_qs, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "eg"
COUNTRY = "Egypt"
SOURCE_TYPE = "egypt_official"
LICENSE = (
    "Official texts of the Arab Republic of Egypt as published by the Presidency, "
    "the Cabinet, and the General Organisation for Government Printing Offices "
    "(الهيئة العامة لشئون المطابع الأميرية — الجريدة الرسمية / الوقائع المصرية). "
    "The Official Gazette prevails over this research snapshot. Not legal advice. "
    "Not Manshurat / commercial compilations."
)
UA = DEFAULT_UA + " source=http://www.alamiria.com/"
ALAMIRIA = "http://www.alamiria.com"
ALAMIRIA_HOME = f"{ALAMIRIA}/Sec/Home"
CABINET_CONST = "https://www.cabinet.gov.eg/StaticContent/Constitution"
PRES_CONST_PAGE = "https://www.presidency.eg/ar/%D9%85%D8%B5%D8%B1/%D8%A7%D9%84%D8%AF%D8%B3%D8%AA%D9%88%D8%B1/"
PRES_CONST_PDF = "https://www.presidency.eg/media/46122/" + quote("دستور-جمهورية-مصر-العربية-2019.pdf")
SLEEP = 0.45
log = logging.getLogger("eg")
ART_AR = re.compile(
    r"(?im)^\s*((?:المادة|مادة)\s+(?:[0-9\u0660-\u0669]+|الأولى|الثانية|الثالثة|الرابعة|الخامسة))"
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
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.warning("pdftotext: %s", exc)
    return ""


def canonicalize_alamiria(url: str) -> str:
    if not url:
        return url
    u = url.replace("https://www.alamiria.com", "http://www.alamiria.com")
    u = u.replace("https://alamiria.com", "http://www.alamiria.com")
    u = u.replace("http://alamiria.com", "http://www.alamiria.com")
    return u


def wayback_only(url: str, timestamp: Optional[str] = None) -> dict:
    res = af.get_wayback_content(canonicalize_alamiria(url), timestamp=timestamp)
    res.setdefault("retrieval", "archive")
    return res


def get_official(url: str, *, timeout=(20, 90), retries: int = 3, verify: bool = True) -> dict:
    url = canonicalize_alamiria(url)
    r = None
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=timeout, retries=retries)
    except Exception as exc:
        log.info("live fail %s: %s — wayback of official URL", url, exc)
        return wayback_only(url)
    status = r.status_code
    body = r.content or b""
    ctype = (r.headers.get("content-type") or "").lower()
    text = ""
    if body and ("html" in ctype or "xml" in ctype or "text/" in ctype or not ctype) and body[:4] != b"%PDF":
        text = body.decode(r.encoding or "utf-8", "replace")
    if status == 200 and body[:4] == b"%PDF":
        return {
            "status": "success", "content": body, "text": "",
            "content_type": ctype or "application/pdf", "original_url": url,
            "http_status": 200, "method": "http", "final_url": r.url or url,
            "retrieval": "live",
        }
    if status == 200 and body and len(body) >= 400:
        final = (r.url or url)
        if "/login" in final.lower() and "tashtxt" not in url.lower():
            return {"status": "error", "error": "login_wall", "http_status": status, "retrieval": "live"}
        return {
            "status": "success", "content": body, "text": text, "content_type": ctype,
            "original_url": url, "http_status": status, "method": "http",
            "final_url": final, "retrieval": "live",
        }
    if status == 429:
        log.info("HTTP 429 %s — archive_fallbacks wayback", url)
        return wayback_only(url)
    if status in (404, 410):
        return {"status": "error", "error": f"http_{status}", "http_status": status, "retrieval": "live"}
    log.info("HTTP %s %s — wayback of official URL", status, url)
    return wayback_only(url)



def split_ar(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_AR.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        chunk = text[m.start(): (matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9\u0600-\u06ff]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({
            "id": doc_id, "title": chunk.split("\n", 1)[0][:200], "text": chunk,
            "date_filed": date, "document_number": num, "source_url": source_url,
            "record_type": "article", "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "eg"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def write_law(*, ident, title, text, source_url, date, doc_type, extra_meta, official=None) -> str:
    rid = slug_id(CC, ident)
    if rid in existing_ids(CC):
        return "skip"
    if len(text or "") < 80:
        return "fail"
    rec = base_record(
        cc=CC, country=COUNTRY, language="ar", ident=ident, title=title, text=text,
        source_url=source_url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_eg.py", date=date, official_identifier=official or ident,
        document_type=doc_type, law_status="current", is_current=True,
        documents=split_ar(text, rid, source_url, date), extra_meta=extra_meta,
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    return "ok"


def tash_id_from_url(url: str) -> Optional[str]:
    q = parse_qs(urlparse(url).query)
    if q.get("id"):
        return unquote(q["id"][0])
    m = re.search(r"[?&]id=([^&]+)", url)
    return unquote(m.group(1)) if m else None


def discover() -> list[dict]:
    dest = ROOT / CC / "raw" / "catalog.jsonl"
    if dest.exists() and dest.stat().st_size > 40:
        items = []
        with dest.open(encoding="utf-8") as f:
            for line in f:
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        if items:
            log.info("resume catalog n=%s", len(items))
            return items
    items: list[dict] = [{
        "kind": "constitution",
        "url": PRES_CONST_PDF,
        "page": PRES_CONST_PAGE,
        "title": "دستور جمهورية مصر العربية 2014 المعدل 2019",
        "fallbacks": [
            PRES_CONST_PAGE,
            CABINET_CONST,
        ],
    }]
    res = get_official(ALAMIRIA_HOME)
    html = res.get("text") or ""
    log.info("alamiria home status=%s bytes=%s retrieval=%s", res.get("http_status"), len(html), res.get("retrieval"))
    seen = set()
    for raw_id in re.findall(r"TashTxt(?:\.aspx)?\?id=([^\"'&<>]+)", html):
        tid = unquote(raw_id)
        if tid in seen:
            continue
        seen.add(tid)
        items.append({
            "kind": "tash",
            "id": tid,
            "url": f"{ALAMIRIA}/Sec/TashTxt.aspx?id={raw_id}",
            "title": None,
        })
    recs = af.search_wayback_machine(
        "http://www.alamiria.com/Sec/TashTxt",
        match_type="prefix", limit=400,
        extra_filters=["mimetype:text/html"],
    )
    recs += af.search_wayback_machine(
        "http://www.alamiria.com/Sec/TashTxt.aspx",
        match_type="prefix", limit=200,
        extra_filters=["mimetype:text/html"],
    )
    log.info("wayback tash cdx=%s", len(recs))
    for rec in recs:
        orig = rec.get("original") or ""
        if "laalaws" in orig or "law-pub" in orig or "manshurat" in orig:
            continue
        tid = tash_id_from_url(orig)
        if not tid or tid in seen:
            continue
        seen.add(tid)
        items.append({
            "kind": "tash",
            "id": tid,
            "url": orig if orig.startswith("http") else f"{ALAMIRIA}/Sec/TashTxt.aspx?id={quote(tid)}",
            "wayback_ts": rec.get("timestamp"),
            "title": None,
        })
    atomic_write(dest, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items))
    log.info("catalog n=%s", len(items))
    return items


def body_from_tash(html: str) -> tuple[str, str]:
    """Return (title, text) from official printer HTML."""
    title = ""
    m = re.search(r"<title>\s*([^<]+)", html, re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        if "المطابع" in title or title.lower() in ("alamiria",):
            title = ""
    # drop chrome: take text and cut typical nav
    text = html_to_text(html)
    # strip repeated nav blocks
    for marker in ("تسجيل دخول", "انشاء حساب", "البوابة القانونية"):
        if marker in text[:800] and len(text) > 400:
            # find first legislation-like heading
            break
    m = re.search(
        r"(دستور|قانون|قرار رئيس|قرار مجلس|قرار وزير|الجريدة الرسمية|الوقائع المصرية)",
        text,
    )
    if m and m.start() > 40:
        title = title or re.sub(r"\s+", " ", text[m.start(): m.start() + 120]).strip()
        text = text[m.start():]
    return title, text


def fetch_constitution(it: dict) -> str:
    ident = "eg-constitution-2014"
    url = it["url"]
    text = ""
    retrieval = "live"
    used = url
    res = get_official(url)
    body = res.get("content") or b""
    if res.get("status") == "success" and body[:4] == b"%PDF":
        text = pdf_to_text(body)
        retrieval = res.get("retrieval") or "live"
        used = res.get("final_url") or url
    if len(text) < 200:
        wb = af.get_wayback_content(url)
        body = wb.get("content") or b""
        if wb.get("status") == "success" and body[:4] == b"%PDF":
            text = pdf_to_text(body)
            retrieval = "archive"
            used = wb.get("wayback_url") or url
    if len(text) < 200:
        for fb in it.get("fallbacks") or []:
            res = get_official(fb)
            html = res.get("text") or ""
            title, body_text = body_from_tash(html)
            if "المادة" in body_text and len(body_text) > 500:
                text = body_text
                retrieval = res.get("retrieval") or "live"
                used = fb
                break
            if (res.get("content") or b"")[:4] == b"%PDF":
                text = pdf_to_text(res["content"])
                used = fb
                retrieval = res.get("retrieval") or "live"
                if len(text) >= 200:
                    break
    title = it.get("title") or "دستور جمهورية مصر العربية"
    st = write_law(
        ident=ident, title=title, text=text, source_url=used, date="2019-04-23",
        doc_type="constitution", official="دستور جمهورية مصر العربية 2014 المعدل 2019",
        extra_meta={
            "discovery": {"method": "presidency_constitution_pdf", "page": it.get("page"),
                          "cabinet_landing": CABINET_CONST},
            "retrieval": {"method": retrieval, "used_url": used},
            "text_extraction": {"source": "official", "backend": "pdftotext-or-html"},
            "language_primary": "ar",
        },
    )
    if st == "fail":
        log_failure(CC, {"id": ident, "url": url, "status": "failed", "reason": "constitution_empty"})
    log.info("constitution %s chars=%s retrieval=%s", st, len(text), retrieval)
    return st


def fetch_tash(it: dict) -> str:
    tid = it.get("id") or tash_id_from_url(it["url"]) or "unknown"
    tid_safe = re.sub(r"[^A-Za-z0-9]+", "-", (tid or "unknown")).strip("-")[:80] or "unknown"
    ident = f"eg-tash-{tid_safe}"[:120]
    url = it["url"]
    res = get_official(url)
    html = res.get("text") or ""
    retrieval = res.get("retrieval") or "live"
    used = res.get("final_url") or url
    if res.get("status") != "success" or len(html) < 200 or res.get("error") == "login_wall":
        wb = af.get_wayback_content(url, timestamp=it.get("wayback_ts"))
        if wb.get("status") == "success":
            html = wb.get("text") or ""
            retrieval = "archive"
            used = wb.get("wayback_url") or url
    title, text = body_from_tash(html)
    title = it.get("title") or title or f"نشرة المطابع الأميرية {tid}"
    if len(text) < 80:
        log_failure(CC, {"id": ident, "url": url, "status": "failed", "reason": "empty_tash"})
        return "fail"
    # classify
    head = (title or "") + "\n" + (text or "")[:500]
    if "دستور جمهورية مصر" in head or (title or "").startswith("دستور"):
        doc_type = "constitution"
    elif "قانون" in (title or "") or (text or "")[:400].lstrip().startswith("قانون"):
        doc_type = "statute"
    else:
        doc_type = "decree"
    st = write_law(
        ident=ident, title=title, text=text, source_url=url, date=None,
        doc_type=doc_type, extra_meta={
            "discovery": {"method": "alamiria_tashtxt", "tash_id": tid},
            "retrieval": {"method": retrieval, "used_url": used},
            "text_extraction": {"source": "official", "backend": "alamiria-html"},
            "printer": "الهيئة العامة لشئون المطابع الأميرية",
        },
    )
    if st != "skip":
        log.info("tash %s %s chars=%s type=%s", st, ident[:40], len(text), doc_type)
    return st


def fetch_one(it: dict) -> str:
    if it.get("kind") == "constitution":
        return fetch_constitution(it)
    return fetch_tash(it)


def main():
    setup()
    t0 = utcnow()
    items = discover()
    counters = {"ok": 0, "skip": 0, "fail": 0}
    notes = (
        "Arabic primary. Constitution PDF from the Presidency (official government host); "
        "cabinet.gov.eg/StaticContent/Constitution is the Cabinet landing (no full text in HTML). "
        "Laws/decrees from alamiria.com TashTxt (official gazette printer) live plus Wayback "
        "of those official URLs. Archive print service is login-walled and was not bypassed. "
        "elpai.idsc.gov.eg is subscriber-only and was not paywall-bypassed. "
        "Not manshurat.org / laalaws commercial compilation. "
        f"Started {t0}."
    )
    for n, it in enumerate(items, 1):
        try:
            st = fetch_one(it)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"url": it.get("url"), "status": "failed", "reason": repr(exc)})
        counters[st] = counters.get(st, 0) + 1
        if n % 15 == 0 or n == len(items):
            log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items),
                     counters["ok"], counters["skip"], counters["fail"])
    cov = "partial-official-fulltext"
    write_summary(
        CC, country=COUNTRY,
        source="Presidency + Cabinet + Alamiria (المطابع الأميرية / الجريدة الرسمية)",
        source_urls=[PRES_CONST_PAGE, CABINET_CONST, ALAMIRIA_HOME, "http://www.alamiria.com/"],
        license_text=LICENSE, discovered=len(items), fetched=counters["ok"],
        skipped=counters["skip"], failed=counters["fail"], coverage=cov, notes=notes,
    )
    atomic_write(ROOT / CC / "raw" / "stats.json", json.dumps({
        "discovered": len(items), **counters, "coverage": cov,
        "started": t0, "finished": utcnow(),
    }, indent=2) + "\n")
    log.info("done %s", counters)


if __name__ == "__main__":
    main()
