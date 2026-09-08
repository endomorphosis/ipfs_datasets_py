#!/usr/bin/env python3
"""Bahrain: Constitution + national laws from the Legislation & Legal Opinion Commission.

Official source only:
  https://www.lloc.gov.bh  (هيئة التشريع والرأي القانوني)
  Constitution HTML/PDF: /Legislation/HTM/Constitution  /PDF/Constitution.pdf
  Category listings:     /Legislation/Category/{topic}?PageNum=N
  Item HTML:             /Legislation/HTM/{CODE}
  Item PDF:              /PDF/{CODE}.pdf
  Codes: K = قانون أو مرسوم بقانون; L = older law ids.

National in-force statutes (K/L + Constitution) first. Official Gazette
weekly issues are not ingested as whole books. No commercial DBs. No WAF bypass.
On HTTP 429/403 of official URLs, archive_fallbacks.py of those URLs only.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "bh"
COUNTRY = "Bahrain"
SOURCE_TYPE = "lloc_bahrain"
LICENSE = (
    "Official texts of the Kingdom of Bahrain as published by the Legislation "
    "and Legal Opinion Commission (lloc.gov.bh). The Official Gazette "
    "(الجريدة الرسمية) prevails over this research snapshot. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.lloc.gov.bh/"
PORTAL = "https://www.lloc.gov.bh/"
WORKERS = 3
SLEEP = 0.4
log = logging.getLogger("bh")
ART_AR = re.compile(
    r"(?im)^\s*((?:المادة|مادة)\s+(?:[0-9\u0660-\u0669]+|[()0-9]+|الأولى|الثانية|الثالثة|الرابعة|الخامسة))"
)
HTM_RE = re.compile(r"/Legislation/HTM/([^\"'?]+)", re.I)
SKIP_CAT = {"سجل تعيينات المرأة"}


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


def official_get(url: str, *, retries: int = 4) -> dict:
    r = None
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, retries=retries, timeout=(20, 90),
                     headers={"Accept": "text/html, application/pdf, */*",
                              "Accept-Language": "ar,en;q=0.8"})
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        r = None
    if r is not None and r.status_code == 200 and r.content:
        text = ""
        if r.content[:4] != b"%PDF":
            text = r.text or ""
            if af.is_challenge(text, r.status_code):
                r = None
            else:
                return {"ok": True, "content": r.content, "text": text,
                        "method": "live", "status": 200, "final_url": r.url or url}
        else:
            return {"ok": True, "content": r.content, "text": "",
                    "method": "live", "status": 200, "final_url": r.url or url}
    if r is not None and r.status_code in (404, 410):
        return {"ok": False, "error": f"http_{r.status_code}"}
    if r is not None and r.status_code == 429:
        log.info("HTTP 429 %s — archive_fallbacks", url)
    need = r is None or (r.status_code in (429, 403, 502, 503, 504))
    if not need:
        err = f"http_{getattr(r, 'status_code', 0)}"
        return {"ok": False, "error": err}
    res = af.fetch_with_fallbacks(url, try_http=False, try_cc=True, try_archive_is=False)
    if res.get("status") == "success" and (res.get("text") or res.get("content")):
        return {
            "ok": True, "content": res.get("content") or b"",
            "text": res.get("text") or "",
            "method": res.get("method") or "archive",
            "final_url": res.get("wayback_url") or url,
        }
    err = "archive_fail"
    if r is not None:
        err = f"http_{r.status_code}"
    return {"ok": False, "error": err}


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
            "metadata": {"text_extraction": {"source": "official", "backend": "bh"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def load_catalog() -> list[dict]:
    p = ROOT / CC / "raw" / "catalog.jsonl"
    if not p.exists() or p.stat().st_size < 50:
        return []
    items, seen = [], set()
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            code = str(row.get("id") or "")
            if not code or code in seen:
                continue
            seen.add(code)
            items.append(row)
    return items


def add_item(items, seen, row: dict):
    code = str(row.get("id") or "")
    if not code or code in seen:
        return
    seen.add(code)
    row.setdefault("htm_url", urljoin(PORTAL, f"Legislation/HTM/{code}"))
    row.setdefault("pdf_url", urljoin(PORTAL, f"PDF/{code}.pdf"))
    items.append(row)
    append_catalog(CC, row)


def list_categories() -> list[str]:
    got = official_get(urljoin(PORTAL, "Legislation/Category"))
    html = got.get("text") or ""
    cats = []
    for raw in re.findall(r"/[Ll]egislation/[Cc]ategory/([^\"'?]+)", html):
        from urllib.parse import unquote
        c = unquote(raw).strip()
        if c and c not in SKIP_CAT and c not in cats:
            cats.append(c)
    return cats


def discover() -> list[dict]:
    items = load_catalog()
    seen = {str(x.get("id")) for x in items}
    add_item(items, seen, {
        "id": "Constitution", "kind": "constitution",
        "title": "دستور مملكة البحرين",
        "source": "known_constitution",
    })
    n_cat = len({x.get("category") for x in items if x.get("category")})
    if n_cat >= 20 and len(items) >= 200:
        log.info("resume catalog %s cats=%s", len(items), n_cat)
        return items
    cats = list_categories()
    log.info("categories %s", len(cats))
    for cat in cats:
        for page in range(1, 40):
            url = urljoin(PORTAL, f"Legislation/Category/{quote(cat)}?PageNum={page}")
            got = official_get(url)
            if not got.get("ok"):
                break
            html = got.get("text") or ""
            codes = list(dict.fromkeys(HTM_RE.findall(html)))
            new = 0
            for code in codes:
                if code in seen:
                    continue
                prefix = code[:1].upper()
                kind = "constitution" if "const" in code.lower() else (
                    "statute" if prefix in {"K", "L"} else "decree"
                )
                add_item(items, seen, {
                    "id": code, "kind": kind, "title": "",
                    "category": cat, "source": f"category:{cat}:p{page}",
                })
                new += 1
            log.info("cat %s p=%s codes=%s new=%s total=%s", cat[:24], page, len(codes), new, len(items))
            if not codes or new == 0:
                break
    # Latest as extra discovery (laws/decree-laws)
    for page in range(1, 80):
        url = urljoin(PORTAL, f"Legislation/Latest?PageNum={page}")
        got = official_get(url)
        if not got.get("ok"):
            break
        codes = list(dict.fromkeys(HTM_RE.findall(got.get("text") or "")))
        new = 0
        for code in codes:
            if code in seen:
                continue
            prefix = code[:1].upper()
            if prefix not in {"K", "L"} and "const" not in code.lower():
                continue
            add_item(items, seen, {
                "id": code, "kind": "statute", "title": "",
                "source": f"latest_p{page}",
            })
            new += 1
        if not codes:
            break
        if new == 0 and page > 5:
            # later pages are ministerial decisions
            if page > 15:
                break
    log.info("discovered %s", len(items))
    return items


def page_title(html: str, fallback: str) -> str:
    m = re.search(r"<title>\s*([^<]+)", html or "", re.I)
    if m:
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        t = re.sub(r"^.*?(?:هيئة التشريع والرأي القانوني|Legislation and Legal Opinion Commission)\s*[-|:]*\s*", "", t)
        if t and "هيئة" not in t[:8]:
            return t[:300]
    m = re.search(r"<h1[^>]*>([\s\S]{3,240})</h1>", html or "", re.I)
    if m:
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
        if t:
            return t[:300]
    # first line of body
    body = html_to_text(html or "")
    if body:
        line = body.strip().split("\n", 1)[0].strip()
        if 8 <= len(line) <= 220:
            return line
    return fallback


def fetch_one(it: dict, done: set[str]) -> str:
    code = str(it.get("id") or "")
    if not code:
        return "fail"
    ident = "constitution" if code.lower() in {"constitution", "constitmemo"} else f"leg-{code}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    htm_url = it.get("htm_url") or urljoin(PORTAL, f"Legislation/HTM/{code}")
    pdf_url = it.get("pdf_url") or urljoin(PORTAL, f"PDF/{code}.pdf")
    page = official_get(htm_url)
    html = page.get("text") or ""
    title = page_title(html, it.get("title") or code)
    text = html_to_text(html) if html else ""
    backend = f"html-{(page.get('method') or 'live')}"
    used = page.get("final_url") or htm_url
    if len(text) < 80:
        pdf = official_get(pdf_url)
        body = pdf.get("content") or b""
        if pdf.get("ok") and body[:4] == b"%PDF":
            text = pdf_to_text(body)
            backend = f"pdf-{(pdf.get('method') or 'live')}"
            used = pdf.get("final_url") or pdf_url
    if len(text) < 80:
        log_failure(CC, {"identifier": code, "source_url": htm_url, "status": "failed",
                         "reason": "empty_text", "title": title})
        return "fail"
    year = None
    m = re.search(r"(?: لسنة |/)\s*(19\d{2}|20\d{2})", title) or re.search(r"(19\d{2}|20\d{2})$", code)
    if m:
        year = m.group(1)
    date = f"{year}-01-01" if year else None
    docs = split_ar(text, rid, used, date)
    is_const = "const" in code.lower() or "دستور" in (title or "")
    prefix = code[:1].upper()
    if is_const:
        doc_type = "constitution"
    elif prefix in {"K", "L"} or "قانون" in (title or ""):
        doc_type = "statute"
    else:
        doc_type = "decree"
    rec = base_record(
        cc=CC, country=COUNTRY, language="ar", ident=ident, title=title,
        text=text, source_url=htm_url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_bh.py", date=date, official_identifier=code,
        document_type=doc_type, law_status="current", is_current=True, documents=docs,
        extra_meta={
            "discovery": {"method": it.get("source") or "lloc", "id": code,
                          "category": it.get("category"), "retrieval": page.get("method")},
            "retrieval": {"method": (page.get("method") or "live") if "html" in backend else backend.split("-")[-1],
                          "used_url": used, "backend": backend},
            "text_extraction": {"source": "official", "backend": backend},
        },
    )
    rec["languages"] = ["ar"]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    def rank(it):
        code = str(it.get("id") or "")
        if "const" in code.lower() or it.get("kind") == "constitution":
            return (0, code)
        if code[:1].upper() in {"K", "L"}:
            return (1, code)
        return (2, code)
    items = sorted(items, key=rank)
    done = existing_ids(CC)
    ok = skip = fail = 0
    log.info("queue %s already=%s", len(items), len(done))
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
            if n % 25 == 0 or n == len(items):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY,
                    source="Legislation and Legal Opinion Commission (lloc.gov.bh)",
                    source_urls=[PORTAL, urljoin(PORTAL, "Legislation/Search"),
                                 urljoin(PORTAL, "Legislation/Category")],
                    license_text=LICENSE, discovered=len(items), fetched=ok,
                    skipped=skip, failed=fail, coverage="catalog-backed incomplete",
                    notes="Constitution + national laws from official LLOC portal.",
                    last_run=utcnow(),
                )
    coverage = "snapshot" if ok else "empty"
    if items and fail == 0 and ok + skip >= len(items):
        coverage = "national-laws snapshot"
    notes = (
        "Constitution and national laws from official lloc.gov.bh "
        "(Legislation and Legal Opinion Commission). HTML texts preferred; "
        "PDF fallback. Weekly Official Gazette issue PDFs not ingested as "
        "whole books. Appointments register skipped. "
        f"429/403 uses archive_fallbacks of official URLs. Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Legislation and Legal Opinion Commission (lloc.gov.bh)",
        source_urls=[PORTAL, urljoin(PORTAL, "Legislation/HTM/Constitution"),
                     urljoin(PORTAL, "Legislation/Category"),
                     urljoin(PORTAL, "OfficialGazette")],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage=coverage, notes=notes, last_run=utcnow(), extra=f"started {t0}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items), "coverage": coverage,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()
