#!/usr/bin/env python3
"""Indonesia: Undang-Undang from official JDIH BPK (peraturan.bpk.go.id).

Official only:
  https://peraturan.bpk.go.id/   (JDIH BPK Database Peraturan)
  https://peraturan.go.id/       (Ditjen PP; TLS failed from this host)
  https://jdihn.go.id/           (national hub; TLS failed from this host)

Undang-Undang first: BPK Search?jenis=8 (1927 UU).
Note: BPK jenis=9 is Perpu (not UU); user-facing "id=9" maps to Perpu here.
Does not use Pasal.id or other commercial aggregators.
Language: id.
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
from urllib.parse import unquote, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "id"
COUNTRY = "Indonesia"
SOURCE_TYPE = "jdih_bpk_pdf"
LICENSE = (
    "Official Indonesian legislative texts from JDIH BPK (peraturan.bpk.go.id), "
    "the Database Peraturan of Badan Pemeriksa Keuangan. Public-sector official "
    "texts; the authentic source is the State Gazette (Lembaran Negara / "
    "Tambahan Lembaran Negara). Not Pasal.id. Not legal advice."
)
UA = DEFAULT_UA + " source=https://peraturan.bpk.go.id/"
PORTAL = "https://peraturan.bpk.go.id/"
SEARCH_UU = "https://peraturan.bpk.go.id/Search?jenis=8"
# BPK taxonomy: 8=Undang-Undang (UU ~1927), 9=Perpu (~170), 10=PP
JENIS_UU = 8
WORKERS = 8
SLEEP = 0.25
MAX_PDF_BYTES = 120 * 1024 * 1024
log = logging.getLogger("id")

ART_ID = re.compile(
    r"(?im)^\s*((?:Pasal|PASAL|Ps\.)\s+\d+[A-Za-z]*)\b"
)
DETAILS_RE = re.compile(r"/Details/(\d+)/(uu-no-\d+-tahun-\d+)", re.I)
DOWNLOAD_RE = re.compile(
    r'href="(/Download/(\d+)/([^"]+\.pdf))"', re.I
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
                check=False, capture_output=True, timeout=240,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.warning("pdftotext failed: %s", exc)
    return ""


def split_id_articles(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_ID.finditer(text or ""))
    if len(matches) < 2:
        return []
    out = []
    seen = set()
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < 8:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            doc_id = f"{doc_id}-{len(out)+1}"[:180]
        seen.add(doc_id)
        heading = chunk.split("\n", 1)[0][:200]
        out.append({
            "id": doc_id,
            "title": heading,
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "jdih_bpk_pdf"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def parse_listing(html: str) -> list[dict]:
    items = []
    seen = set()
    for m in DETAILS_RE.finditer(html or ""):
        did, slug = m.group(1), m.group(2).lower()
        if did in seen:
            continue
        seen.add(did)
        nm = re.match(r"uu-no-(\d+)-tahun-(\d+)", slug)
        number = nm.group(1) if nm else ""
        year = nm.group(2) if nm else ""
        # title from nearby anchor text
        items.append({
            "details_id": did,
            "slug": slug,
            "url": f"https://peraturan.bpk.go.id/Details/{did}/{slug}",
            "number": number,
            "year": year,
            "jenis": "Undang-Undang",
        })
    return items


def max_page(html: str) -> int:
    pages = [int(x) for x in re.findall(r"jenis=8(?:&amp;|&)p=(\d+)", html or "")]
    return max(pages) if pages else 1


def discover() -> list[dict]:
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    items: list[dict] = []
    if cat.exists() and cat.stat().st_size > 1000:
        with cat.open(encoding="utf-8") as f:
            for line in f:
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        if items:
            log.info("resume catalog %s", len(items))
            return items
    seen = set()
    last_page = 1
    page = 1
    stagnant = 0
    while page <= 250:
        url = f"https://peraturan.bpk.go.id/Search?jenis={JENIS_UU}&p={page}"
        try:
            r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=4,
                         headers={"Accept": "text/html, */*", "Accept-Language": "id,en;q=0.8"})
        except Exception as exc:
            log.warning("listing p=%s %s", page, exc)
            stagnant += 1
            if stagnant >= 3:
                break
            page += 1
            continue
        if r.status_code != 200 or af.is_challenge(r.text or "", r.status_code):
            log.warning("listing p=%s HTTP %s challenge=%s", page, r.status_code,
                        af.is_challenge(r.text or "", r.status_code))
            stagnant += 1
            if stagnant >= 3:
                break
            page += 1
            continue
        if page == 1:
            last_page = max(max_page(r.text), 1)
            log.info("listing last_page=%s", last_page)
        batch = parse_listing(r.text)
        newc = 0
        for row in batch:
            if row["details_id"] in seen:
                continue
            seen.add(row["details_id"])
            items.append(row)
            append_catalog(CC, row)
            newc += 1
        log.info("listing p=%s new=%s total=%s page_hits=%s", page, newc, len(items), len(batch))
        if newc == 0:
            stagnant += 1
            if stagnant >= 2:
                break
        else:
            stagnant = 0
        page += 1
        if page > last_page + 2:
            break
    log.info("catalog discovered %s", len(items))
    return items


def parse_details(html: str, fallback_url: str) -> dict:
    title = ""
    m = re.search(r"<title>\s*([^<]+)", html or "", re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        title = re.sub(r"\s*\|\s*.*$", "", title)
    # descriptive span after the UU number link
    about = ""
    m = re.search(r"tentang\s+([^<]{8,300})", html or "", re.I)
    if m:
        about = re.sub(r"\s+", " ", m.group(1)).strip()
    pdfs = []
    for m in DOWNLOAD_RE.finditer(html or ""):
        rel, file_id, fname = m.group(1), m.group(2), unquote(m.group(3))
        if "UjiMateri" in rel or "putusan" in fname.lower():
            continue
        pdfs.append({
            "url": urljoin(PORTAL, rel),
            "file_id": file_id,
            "filename": fname,
        })
    # preview data-file-id
    if not pdfs:
        for m in re.finditer(r'data-file-id="(\d+)"[^>]*>\s*([^<]*\.pdf)', html or "", re.I):
            fid, fname = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
            pdfs.append({
                "url": f"https://peraturan.bpk.go.id/Download/{fid}/{quote_name(fname)}",
                "file_id": fid,
                "filename": fname,
            })
    date = None
    dm = re.search(r"(20\d{2}-\d{2}-\d{2})", html or "")
    if dm:
        date = dm.group(1)
    else:
        dm = re.search(r"(\d{1,2})\s+(\w+)\s+(20\d{2})", html or "")
        if dm:
            date = iso_date(f"{dm.group(1).zfill(2)}/01/{dm.group(3)}")  # rough
    return {"title": title, "about": about, "pdfs": pdfs, "date": date, "source_url": fallback_url}


def quote_name(name: str) -> str:
    from urllib.parse import quote
    return quote(name, safe="")


def fetch_pdf_bytes(url: str) -> bytes:
    try:
        r = http_get(
            url, ua=UA, sleep=SLEEP, timeout=(20, 300), retries=3,
            headers={"Accept": "application/pdf, application/octet-stream, */*",
                     "Referer": PORTAL},
        )
    except Exception as exc:
        log.warning("pdf %s: %s", url, exc)
        return b""
    if r.status_code != 200 or not r.content:
        return b""
    if r.content[:4] != b"%PDF":
        if af.is_challenge(r.text if r.headers.get("content-type", "").startswith("text") else "", r.status_code):
            return b""
        return b""
    if len(r.content) > MAX_PDF_BYTES:
        log.warning("pdf too large %s bytes=%s", url, len(r.content))
        return r.content[:MAX_PDF_BYTES] if False else r.content  # still try; caller pdftotext
    return r.content


def fetch_one(it: dict, done: set[str]) -> str:
    did = str(it.get("details_id") or "").strip()
    slug = it.get("slug") or f"uu-{did}"
    url = it.get("url") or f"https://peraturan.bpk.go.id/Details/{did}/{slug}"
    ident = slug
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    html = ""
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 90), retries=4,
                     headers={"Accept": "text/html, */*", "Accept-Language": "id,en;q=0.8"})
        if r.status_code == 200 and r.text and not af.is_challenge(r.text, r.status_code):
            html = r.text
    except Exception as exc:
        log.warning("details %s: %s", url, exc)
    if not html:
        res = af.get_wayback_content(url)
        if res.get("status") == "success":
            html = res.get("text") or ""
    if not html:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "empty_details"})
        return "fail"
    meta = parse_details(html, url)
    pdfs = meta.get("pdfs") or []
    # prefer the UU PDF not penjelasan
    pdfs_sorted = sorted(
        pdfs,
        key=lambda p: (0 if "penjelasan" not in (p.get("filename") or "").lower() else 1,
                       0 if (p.get("filename") or "").lower().startswith("uu") else 1),
    )
    text = ""
    pdf_url = None
    method = "live_pdf"
    for spec in pdfs_sorted[:2]:
        raw = fetch_pdf_bytes(spec["url"])
        if not raw:
            continue
        text = pdf_to_text(raw)
        if text and len(text) >= 40:
            pdf_url = spec["url"]
            break
    if not text:
        # wayback of details already tried; try CC of official details URL
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "empty_pdf_text",
                         "pdfs": [p.get("url") for p in pdfs_sorted[:3]]})
        return "fail"
    number = it.get("number") or ""
    year = it.get("year") or ""
    title = meta.get("title") or ""
    if meta.get("about") and "tentang" not in title.lower():
        title = (title + " tentang " + meta["about"]).strip()
    if not title:
        title = f"Undang-Undang Nomor {number} Tahun {year}".strip()
    official = f"UU No. {number} Tahun {year}".strip() if number else slug
    date = meta.get("date")
    if year and not date:
        date = f"{year}-01-01"
    docs = split_id_articles(text, rid, url, date)
    rec = base_record(
        cc=CC, country=COUNTRY, language="id", ident=ident,
        title=title, text=text, source_url=url, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="id-peraturan-bpk",
        eli=None, date=date if date and re.match(r"^\d{4}-\d{2}-\d{2}$", date or "") else None,
        official_identifier=official,
        document_type="statute", law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "discovery": {
                "method": "bpk_search_jenis_8",
                "catalog_identifier": did,
                "seed_url": SEARCH_UU,
                "pdf_url": pdf_url,
                "retrieval": method,
            },
            "official_metadata": {
                "details_id": did,
                "slug": slug,
                "number": number,
                "year": year,
                "jenis": "Undang-Undang",
                "bpk_jenis": JENIS_UU,
            },
        },
        extra_fields={
            "canonical_title": title,
            "citation": official,
            "canonical_document_url": pdf_url or url,
            "status_source": "jdih_bpk_undang_undang",
            "status_confidence": "medium",
            "status_note": "Undang-Undang from JDIH BPK. Lembaran Negara authentic text prevails. Not Pasal.id.",
        },
    )
    rec["id"] = rid
    rec["languages"] = ["id"]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    log.info("queue uu=%s already_done=%s", len(items), len(done))
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
            if n % 40 == 0 or n == len(items):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY,
                    source="JDIH BPK Database Peraturan — Undang-Undang (jenis=8)",
                    source_urls=[PORTAL, SEARCH_UU, "https://peraturan.go.id/", "https://jdihn.go.id/"],
                    license_text=LICENSE, discovered=len(items), fetched=ok,
                    skipped=skip, failed=fail, coverage="catalog-backed incomplete",
                    notes="Undang-Undang first. BPK jenis=9 is Perpu. Not Pasal.id.",
                    last_run=utcnow(),
                )
    coverage = "full" if fail == 0 and ok + skip >= len(items) and items else "catalog-backed incomplete"
    notes = (
        f"Undang-Undang from JDIH BPK Search?jenis=8 ({len(items)} catalog rows). "
        "BPK jenis=9 is Perpu (not collected). PP (jenis=10) not collected in this UU-first snapshot. "
        "peraturan.go.id and jdihn.go.id TLS failed from this host. Not Pasal.id. "
        f"Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="JDIH BPK Database Peraturan — Undang-Undang (jenis=8)",
        source_urls=[PORTAL, SEARCH_UU, "https://peraturan.go.id/", "https://jdihn.go.id/"],
        license_text=LICENSE, discovered=len(items), fetched=ok,
        skipped=skip, failed=fail, coverage=coverage, notes=notes,
        last_run=utcnow(), extra=f"started {t0}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items), "coverage": coverage,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()
