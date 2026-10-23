#!/usr/bin/env python3
"""Singapore: current Acts from Singapore Statutes Online (AGC Legislation Division).

Official only:
  https://sso.agc.gov.sg/
  Browse: https://sso.agc.gov.sg/Browse/Act/Current
  Act pages: https://sso.agc.gov.sg/Act/{code}  e.g. /Act/CoA1967
  PDF: https://sso.agc.gov.sg/Act/{code}?ViewType=Pdf

robots.txt: Disallow: /search ; crawl-delay: 6
This collector never hits /search. No Cloudflare browser rendering.
No WAF bypass (DEFAULT_UA only). Live CloudFront often 403s this UA.

Fallback: Wayback CDX of official sso.agc.gov.sg URLs only (letter prefixes
of /Act/{A-Z} with Historical/Act-Rev/query filters, plus exact Act and
ViewType=Pdf captures). Prefer official PDF snapshots, else HTML.
SSO is an unofficial reproduction; printed Gazette / AGC official text prevails.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "sg"
COUNTRY = "Singapore"
SOURCE_TYPE = "sso_agc_html"
LICENSE = (
    "Singapore Statutes Online (sso.agc.gov.sg) is an unofficial reproduction "
    "published by the Legislation Division of the Attorney-General's Chambers. "
    "The printed Gazette and AGC official text prevail. Research snapshot with "
    "provenance. Not legal advice."
)
UA = DEFAULT_UA + " source=https://sso.agc.gov.sg/"
PORTAL = "https://sso.agc.gov.sg/"
BROWSE = "https://sso.agc.gov.sg/Browse/Act/Current"
ACT_RE = re.compile(
    r"^https://sso\.agc\.gov\.sg/Act/([A-Za-z][A-Za-z0-9]{1,60}\d{4})$"
)
ACT_FROM_PATH = re.compile(
    r"https?://sso\.agc\.gov\.sg/Act/([A-Za-z][A-Za-z0-9]{1,60}\d{4})(?:/|$|\?)",
    re.I,
)
SG_SEC = re.compile(r"(?m)^(\d+[A-Za-z]{0,2})\.(?:—|\s+(?=[A-Z“\"'‘]))")
WORKERS = 2
SLEEP = 6.0
EXPECTED_ACTS = 524
log = logging.getLogger("sg")
_live_blocked = threading.Event()


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def normalize_act_url(url: str) -> Optional[str]:
    if not url:
        return None
    raw = (url or "").split("?")[0].split("#")[0].rstrip("/")
    raw = raw.replace("http://", "https://")
    if "/Historical" in raw or "/Act-Rev" in raw or "/act-rev" in raw:
        return None
    if "/Repealed" in raw or "/Uncommenced" in raw:
        return None
    m = ACT_FROM_PATH.search(raw + "/")
    if not m:
        return None
    return f"https://sso.agc.gov.sg/Act/{m.group(1)}"


def act_code_from_url(url: str) -> Optional[str]:
    nu = normalize_act_url(url)
    if not nu:
        return None
    m = ACT_RE.match(nu)
    return m.group(1) if m else None


def live_get(url: str) -> Optional[str]:
    if _live_blocked.is_set():
        return None
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=1,
                     headers={"Accept": "text/html, */*"})
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        return None
    if r.status_code in (403, 429) or af.is_challenge(r.text or "", r.status_code):
        _live_blocked.set()
        log.info("live blocked HTTP %s %s — skip further live fetches", r.status_code, url)
        return None
    if r.status_code != 200 or not r.text:
        log.info("live HTTP %s %s", r.status_code, url)
        return None
    return r.text


def parse_act_links(html: str) -> list[str]:
    urls = []
    seen = set()
    for href in re.findall(r'href=["\']([^"\']+)["\']', html or ""):
        href = href.replace("&amp;", "&")
        if href.startswith("/Act/"):
            href = "https://sso.agc.gov.sg" + href
        nu = normalize_act_url(href)
        if nu and nu not in seen:
            seen.add(nu)
            urls.append(nu)
    for code in re.findall(r"/Act/([A-Za-z][A-Za-z0-9]{1,60}\d{4})", html or ""):
        nu = f"https://sso.agc.gov.sg/Act/{code}"
        if nu not in seen:
            seen.add(nu)
            urls.append(nu)
    return urls


def slim_cc_record(rec: dict) -> Optional[dict]:
    fn = rec.get("filename") or rec.get("warc_filename")
    if not fn:
        return None
    return {
        "filename": fn,
        "offset": rec.get("offset") or rec.get("warc_offset"),
        "length": rec.get("length") or rec.get("warc_length"),
        "timestamp": rec.get("timestamp"),
        "url": rec.get("url") or rec.get("original"),
        "original": rec.get("original") or rec.get("url"),
    }


def add_item(items: list[dict], seen: dict, url: str, extra: dict) -> bool:
    nu = normalize_act_url(url)
    code = act_code_from_url(nu or "")
    if not nu or not code:
        return False
    prev = seen.get(nu)
    if prev is None:
        row = {"code": code, "url": nu, **extra}
        items.append(row)
        seen[nu] = row
        append_catalog(CC, {k: v for k, v in row.items() if k != "cc_record"})
        return True
    for k in ("cdx_ts", "pdf_ts", "pdf_url", "wayback_url", "cc_record"):
        if extra.get(k) and not prev.get(k):
            prev[k] = extra[k]
    return False


def load_catalog() -> tuple[list[dict], dict]:
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    items: list[dict] = []
    seen: dict = {}
    if not cat.exists() or cat.stat().st_size < 200:
        return items, seen
    with cat.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            nu = normalize_act_url(row.get("url") or "")
            code = row.get("code") or act_code_from_url(nu or "")
            if not nu or not code or not re.search(r"\d{4}$", str(code)):
                continue
            if nu in seen:
                prev = seen[nu]
                for k in ("cdx_ts", "pdf_ts", "pdf_url", "wayback_url", "cc_record"):
                    if row.get(k) and not prev.get(k):
                        prev[k] = row[k]
                continue
            row["code"] = code
            row["url"] = nu
            items.append(row)
            seen[nu] = row
    return items, seen


def rewrite_catalog(items: list[dict]) -> None:
    path = ROOT / CC / "raw" / "catalog.jsonl"
    slim = []
    for it in items:
        row = {k: v for k, v in it.items() if k != "cc_record"}
        cr = slim_cc_record(it.get("cc_record") or {})
        if cr:
            row["cc_record"] = cr
        slim.append(row)
    atomic_write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in slim))


def rec_len(rec: dict) -> int:
    try:
        return int(rec.get("length") or 0)
    except Exception:
        return 0


def pick_best(recs: list[dict], min_len: int = 8000) -> Optional[dict]:
    usable = [r for r in recs if rec_len(r) >= min_len]
    pool = usable or recs
    if not pool:
        return None
    return max(pool, key=rec_len)


def cdx_search(url: str, **kwargs) -> list[dict]:
    try:
        return af.search_wayback_machine(url, **kwargs) or []
    except Exception as exc:
        log.warning("cdx fail %s: %s", url, exc)
        time.sleep(4.0)
        try:
            return af.search_wayback_machine(url, **kwargs) or []
        except Exception as exc2:
            log.warning("cdx retry fail %s: %s", url, exc2)
            return []


def wb_get(url: str, ts: Optional[str], tries: int = 3) -> dict:
    last: dict = {}
    for i in range(tries):
        try:
            res = af.get_wayback_content(url, timestamp=ts)
        except Exception as exc:
            res = {"status": "error", "error": str(exc)}
        last = res or {}
        if last.get("status") == "success" and (last.get("text") or last.get("content")):
            return last
        err = str(last.get("error") or "")
        if last.get("http_status") in (403, 429) or "SSL" in err or "timeout" in err.lower() or "EOF" in err:
            time.sleep(5.0 + i * 4.0)
            continue
        break
    return last or {"status": "error", "error": "empty"}


def expand_catalog_letters(items: list[dict], seen: dict) -> None:
    """Wayback CDX of official /Act/{A-Z} URLs only. Filter Historical/query junk."""
    log.info("letter CDX expand unique=%s expected~%s", len(items), EXPECTED_ACTS)
    extra = [
        "!original:.*[?].*",
        "!original:.*Historical.*",
        "!original:.*Act-Rev.*",
        "!original:.*act-rev.*",
        "!original:.*Repealed.*",
        "!original:.*Uncommenced.*",
        "mimetype:text/html",
    ]
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        recs = cdx_search(
            f"sso.agc.gov.sg/Act/{letter}",
            match_type="prefix",
            limit=250,
            collapse="urlkey",
            filter_status="200",
            extra_filters=extra,
        )
        added = 0
        for rec in recs:
            extra_row = {
                "source": "wayback_letter_cdx",
                "cdx_ts": rec.get("timestamp"),
                "wayback_url": rec.get("wayback_url"),
                "cdx_length": rec.get("length"),
            }
            if add_item(items, seen, rec.get("original") or "", extra_row):
                added += 1
        log.info("letter %s cdx hits=%s new=%s total=%s", letter, len(recs), added, len(items))
        time.sleep(1.5)
    marker = ROOT / CC / "raw" / "letter_cdx_done.json"
    marker.write_text(json.dumps({"n": len(items), "at": utcnow()}) + "\n", encoding="utf-8")


def harvest_browse_pages(items: list[dict], seen: dict) -> None:
    log.info("harvest browse All/0-30 snapshots unique=%s", len(items))
    for n in range(0, 31):
        url = f"https://sso.agc.gov.sg/Browse/Act/Current/All/{n}"
        recs = cdx_search(
            url, match_type="exact", limit=8, collapse="", filter_status="200",
            extra_filters=["mimetype:text/html"],
        )
        rec = pick_best(recs, min_len=4000)
        if not rec:
            continue
        res = wb_get(rec.get("original") or url, rec.get("timestamp"))
        html = res.get("text") or ""
        if not html:
            continue
        newc = 0
        for href in parse_act_links(html):
            if add_item(items, seen, href, {
                "source": "wayback_browse",
                "browse_ts": rec.get("timestamp"),
            }):
                newc += 1
        log.info("browse All/%s new=%s total=%s html=%s", n, newc, len(items), len(html))
        if newc == 0 and n > 5 and n % 5 == 0:
            # keep going; later pages may still have acts
            pass


def discover() -> list[dict]:
    items, seen = load_catalog()
    if items:
        log.info("resume catalog unique=%s", len(items))
    else:
        for page in range(0, 40):
            url = f"https://sso.agc.gov.sg/Browse/Act/Current/All/{page}?PageSize=20"
            html = live_get(url)
            if not html:
                if page == 0:
                    html = live_get(BROWSE)
                if not html:
                    break
            newc = 0
            for href in parse_act_links(html):
                if add_item(items, seen, href, {"source": "live_browse"}):
                    newc += 1
            log.info("live browse page=%s new=%s total=%s", page, newc, len(items))
            if newc == 0 and page > 0:
                break

    marker = ROOT / CC / "raw" / "letter_cdx_done.json"
    if len(items) < EXPECTED_ACTS and not marker.exists():
        expand_catalog_letters(items, seen)
        rewrite_catalog(items)
    elif len(items) < 400:
        expand_catalog_letters(items, seen)
        rewrite_catalog(items)

    if len(items) < EXPECTED_ACTS:
        harvest_browse_pages(items, seen)
        rewrite_catalog(items)
    log.info("catalog discovered %s", len(items))
    return items


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
        log.warning("pdftotext failed: %s", exc)
    return ""


def split_sg(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(SG_SEC.finditer(text or ""))
    if len(matches) < 2:
        return []
    docs = []
    seen = set()
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < 8:
            continue
        num = m.group(1)
        aid = re.sub(r"[^a-z0-9]+", "-", f"s{num}").strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            doc_id = f"{doc_id}-{i+1}"[:180]
        seen.add(doc_id)
        docs.append({
            "id": doc_id,
            "title": chunk.split("\n", 1)[0][:200],
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "sso_section"}},
        })
        if len(docs) >= 4000:
            break
    return docs


def extract_provisions(html: str, law_id: str, source_url: str, date: Optional[str]) -> tuple[str, list[dict], str]:
    title = ""
    m = re.search(r"<title>\s*([^<]+?)\s*-\s*Singapore Statutes Online", html, re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
    if not title:
        m = re.search(r'class="legis-title"[^>]*>([^<]{3,200})', html, re.I)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
    legis = ""
    lm = re.search(r'id="legisContent"[^>]*>([\s\S]+?)</div>\s*<div[^>]*id="', html, re.I)
    if not lm:
        lm = re.search(r'id="colLegis"[^>]*>([\s\S]+)', html, re.I)
    if lm:
        legis = lm.group(1)
    target = legis or html
    docs = []
    parts = []
    blocks = re.findall(
        r'(<div[^>]*class="[^"]*prov1[^"]*"[^>]*>[\s\S]*?)(?=<div[^>]*class="[^"]*prov1[^"]*"|$)',
        target, re.I,
    )
    seen = set()
    for i, block in enumerate(blocks):
        hdr_m = re.search(r'class="[^"]*prov1Hdr[^"]*"[^>]*>([\s\S]*?)</div>', block, re.I)
        hdr = html_to_text(hdr_m.group(1) if hdr_m else "")
        body = html_to_text(block)
        if not body or len(body) < 8:
            continue
        parts.append(body)
        num = ""
        nm = re.match(r"^\s*(\d+[A-Za-z]?)", hdr or body)
        num = nm.group(1) if nm else str(i + 1)
        heading = (hdr or body.split("\n", 1)[0])[:200]
        aid = re.sub(r"[^a-z0-9]+", "-", f"s{num}").strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            doc_id = f"{doc_id}-{i+1}"[:180]
        seen.add(doc_id)
        docs.append({
            "id": doc_id,
            "title": heading,
            "text": body,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "sso_prov1_html"}},
        })
        if len(docs) >= 4000:
            break
    text = "\n\n".join(parts)
    full = html_to_text(target)
    if not text or len(full) > len(text) * 1.2:
        text = full
        docs = split_sg(text, law_id, source_url, date)
    if not text or len(text) < 80:
        cleaned = re.sub(r"(?is)<nav\b.*?</nav>", " ", html)
        cleaned = re.sub(r"(?is)<header\b.*?</header>", " ", cleaned)
        cleaned = re.sub(r"(?is)<footer\b.*?</footer>", " ", cleaned)
        text = html_to_text(cleaned)
        docs = split_sg(text, law_id, source_url, date)
    return text, docs, title


def fetch_one(it: dict, done: set[str]) -> str:
    code = (it.get("code") or "").strip()
    url = it.get("url") or f"https://sso.agc.gov.sg/Act/{code}"
    url = normalize_act_url(url) or url
    if not code:
        code = act_code_from_url(url) or ""
    if not code:
        return "fail"
    rid = slug_id(CC, code)
    if rid in done:
        return "skip"

    html = live_get(url)
    method = "live"
    backend = "live"
    wb_meta: dict = {}
    text = ""
    docs: list[dict] = []
    title = ""

    if html and not af.is_spa_shell(html, html_to_text(html or "")):
        text, docs, title = extract_provisions(html, rid, url, None)

    # Official PDF via Wayback CDX of ViewType=Pdf (complete Act body).
    pdf_text = ""
    pdf_url = it.get("pdf_url") or f"{url}?ViewType=Pdf"
    pdf_ts = it.get("pdf_ts")
    if not pdf_ts:
        pdf_recs = cdx_search(
            pdf_url,
            match_type="prefix",
            limit=12,
            collapse="",
            filter_status="200",
            extra_filters=["mimetype:application/pdf"],
        )
        best_pdf = pick_best(pdf_recs, min_len=15000)
        if best_pdf:
            pdf_ts = best_pdf.get("timestamp")
            pdf_url = best_pdf.get("original") or pdf_url
    if pdf_ts:
        pres = wb_get(pdf_url, pdf_ts)
        raw = pres.get("content") or b""
        if raw[:4] == b"%PDF":
            pdf_text = pdf_to_text(raw)
            if pdf_text and len(pdf_text) > 80:
                wb_meta = {
                    "archive_backend": "wayback_pdf",
                    "wayback_url": pres.get("wayback_url"),
                    "capture_timestamp": pres.get("capture_timestamp") or pdf_ts,
                    "archive_url": pres.get("wayback_url"),
                }
                method = "archive-of-official"
                backend = "wayback_pdf"
                text = pdf_text
                docs = split_sg(text, rid, url, None)
                if not title:
                    tm = re.search(r"(?m)^([A-Z][A-Za-z0-9 ,.'()/-]{5,120})\s*$", text[:2000])
                    title = tm.group(1).strip() if tm else code

    if not text or len(text) < 80:
        ts = it.get("cdx_ts")
        html_url = url
        if not ts:
            html_recs = cdx_search(
                url,
                match_type="exact",
                limit=20,
                collapse="",
                filter_status="200",
                extra_filters=["mimetype:text/html"],
            )
            best_h = pick_best(html_recs, min_len=12000)
            if best_h:
                ts = best_h.get("timestamp")
                html_url = best_h.get("original") or url
        if ts:
            res = wb_get(html_url, ts)
            html2 = res.get("text") or ""
            if html2 and len(html2) >= 500:
                t2, d2, title2 = extract_provisions(html2, rid, url, None)
                if t2 and len(t2) > len(text or ""):
                    text, docs, title = t2, d2, title2 or title
                    method = "archive-of-official"
                    backend = "wayback_html"
                    wb_meta = {
                        "archive_backend": backend,
                        "wayback_url": res.get("wayback_url"),
                        "capture_timestamp": res.get("capture_timestamp") or ts,
                        "archive_url": res.get("wayback_url"),
                    }

    if not text or len(text) < 40:
        log_failure(CC, {
            "identifier": code, "source_url": url, "status": "failed",
            "reason": "empty_text_after_pdf_html",
        })
        return "fail"

    title = title or code
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=code,
        title=title, text=text, source_url=url, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="sg-sso-agc",
        eli=None, date=None, official_identifier=code,
        document_type="statute", law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "discovery": {
                "method": it.get("source") or "mixed",
                "catalog_identifier": code,
                "seed_url": BROWSE,
                "retrieval": method,
                "archive_backend": backend,
                **{k: v for k, v in wb_meta.items() if v},
            },
            "official_metadata": {
                "act_code": code,
                "sso_unofficial_reproduction": True,
            },
            "text_extraction": {
                "source": "archive-of-official" if method != "live" else "official",
                "backend": f"sso_{backend}",
            },
        },
        extra_fields={
            "canonical_title": title,
            "citation": f"{title} ({code})",
            "status_source": "sso_current_acts",
            "status_confidence": "medium" if method != "live" else "high",
            "status_note": (
                "SSO is an unofficial reproduction. Printed Gazette / AGC official "
                "text prevails. robots.txt Disallow /search honoured."
            ),
        },
    )
    rec["id"] = rid
    rec["languages"] = ["en"]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    live_n = sum(1 for it in items if it.get("source") == "live_browse")
    log.info("queue acts=%s already_done=%s live_listed=%s workers=%s",
             len(items), len(done), live_n, WORKERS)
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
            ok += st == "ok"
            skip += st == "skip"
            fail += st == "fail"
            if n % 10 == 0 or n == len(items):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY,
                    source="Singapore Statutes Online (AGC Legislation Division)",
                    source_urls=[PORTAL, BROWSE],
                    license_text=LICENSE, discovered=len(items), fetched=ok,
                    skipped=skip, failed=fail, coverage="catalog-backed incomplete",
                    notes="Current Acts. No /search. Wayback CDX of official SSO URLs; PDF preferred.",
                    last_run=utcnow(),
                )
    coverage = "full" if fail == 0 and ok + skip >= len(items) and items else "catalog-backed incomplete"
    notes = (
        "Current Acts from SSO. robots.txt Disallow:/search honoured. "
        "Live CloudFront 403 uses Wayback CDX of official sso.agc.gov.sg/Act/ "
        "URLs (letter prefixes + ViewType=Pdf). No archive.is. "
        f"Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Singapore Statutes Online (AGC Legislation Division)",
        source_urls=[PORTAL, BROWSE, "https://sso.agc.gov.sg/Act/CoA1967"],
        license_text=LICENSE, discovered=len(items), fetched=ok,
        skipped=skip, failed=fail, coverage=coverage, notes=notes,
        last_run=utcnow(), extra=f"started {t0} live_listed={live_n}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items),
        "coverage": coverage, "live_listed": live_n,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()
