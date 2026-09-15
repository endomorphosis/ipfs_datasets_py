#!/usr/bin/env python3
"""Philippines: Republic Acts + 1987 Constitution from official sources.

Official only (no Lawphil, no Chan Robles as primary):
  https://www.officialgazette.gov.ph          (authentic gazette; live often CF 403)
  https://issuances-library.senate.gov.ph     (Senate LRB official RA texts)
  Senate / House / Congress hosts of official RA texts
  e-Gazette / Official Gazette Wayback of official URLs

Prefer RA + Constitution. Official Gazette prevails. Not legal advice.
Live 403/429 uses archive_fallbacks (CC WARC -> Wayback -> archive.is). No WAF bypass.
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
from urllib.parse import urljoin, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "ph"
COUNTRY = "Philippines"
SOURCE_TYPE = "official_gazette_senate_lrb"
LICENSE = (
    "Official Philippine legislative texts (Republic Acts and Constitution) from "
    "the Official Gazette of the Republic of the Philippines and the Senate of "
    "the Philippines Legislative Reference Bureau issuances library. Official "
    "Gazette authentic text prevails. Not Lawphil. Not Chan Robles. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.officialgazette.gov.ph/"
OG = "https://www.officialgazette.gov.ph/"
SENATE_LIB = "https://issuances-library.senate.gov.ph/"
RA_LIST = "https://issuances-library.senate.gov.ph/legislative-issuances/republic-acts"
CONST_URLS = [
    "https://www.officialgazette.gov.ph/constitutions/1987-constitution/",
    "https://www.officialgazette.gov.ph/constitutions/the-1987-constitution-of-the-republic-of-the-philippines/",
    "https://www.officialgazette.gov.ph/downloads/2019/07jul/1987-Constitution.pdf",
]
WORKERS = 2
SLEEP = 1.4
MIN_TEXT = 120
MAX_PDF = 80 * 1024 * 1024
log = logging.getLogger("ph")

RA_HREF = re.compile(r'href="(/legislative-issuance/republic-act-no-[^"?#]+)"', re.I)
RA_ENC = re.compile(
    r'(?:href|about)="(/legislative(?:%2B|\+)issuances/Republic(?:%20| )Act(?:%20| )No\.(?:%20| )?\d+)"',
    re.I,
)
RA_NO = re.compile(r"republic-act-no-(\d+)", re.I)
RA_TITLE_NO = re.compile(r"Republic Act No\.\s*(\d+)")
ART_PH = re.compile(
    r"(?im)^\s*((?:ARTICLE|Article|Art\.|SECTION|Section|SEC\.|Sec\.)\s+[IVXLCDM0-9]+[A-Za-z]?)\b"
)
FIELD_RE = re.compile(
    r'class="[^"]*field--name-([^"]+)[^"]*"[^>]*>'
    r'(.*?)(?=class="[^"]*field--name-|\Z)',
    re.I | re.S,
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


def split_ph(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_PH.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            doc_id = f"{doc_id}-{len(out)+1}"[:180]
        seen.add(doc_id)
        out.append({
            "id": doc_id,
            "title": chunk.split("\n", 1)[0][:200],
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "ph_collector"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def live_get(url: str, *, accept: str = "text/html, */*", timeout=(20, 90), retries: int = 3) -> Optional[object]:
    try:
        r = http_get(
            url, ua=UA, sleep=SLEEP, timeout=timeout, retries=retries,
            headers={"Accept": accept, "Accept-Language": "en", "Referer": SENATE_LIB},
        )
    except Exception as exc:
        log.info("live fail %s: %s", url, exc)
        return None
    return r


def get_html(url: str) -> tuple[str, str]:
    """Return (html, retrieval_method)."""
    import time as _time
    import requests as _req
    r = live_get(url)
    if r is not None and r.status_code == 200 and r.text and not af.is_challenge(r.text, r.status_code):
        return r.text, "live"
    if r is not None and r.status_code in (403, 429, 503):
        log.info("live HTTP %s %s — backoff retry", r.status_code, url)
        _time.sleep(3)
        r2 = live_get(url, retries=1)
        if r2 is not None and r2.status_code == 200 and r2.text and not af.is_challenge(r2.text, r2.status_code):
            return r2.text, "live"
        wb = "http://web.archive.org/web/2id_/" + url
        try:
            wr = _req.get(wb, timeout=(20, 90), allow_redirects=True, headers={"User-Agent": UA})
            if wr.status_code == 200 and wr.text and not af.is_challenge(wr.text, wr.status_code):
                return wr.text, "wayback"
        except Exception as exc:
            log.info("http wayback fail %s: %s", url, exc)
        return "", "failed"
    return "", "failed"


def get_bytes(url: str) -> tuple[bytes, str]:
    r = live_get(url, accept="application/pdf, application/octet-stream, */*", timeout=(20, 180), retries=2)
    if r is not None and r.status_code == 200 and r.content and r.content[:4] == b"%PDF":
        return r.content, "live_pdf"
    if r is not None and r.status_code in (403, 429):
        import requests as _req
        wb = "http://web.archive.org/web/2id_/" + url
        try:
            wr = _req.get(wb, timeout=(20, 120), allow_redirects=True, headers={"User-Agent": UA})
            if wr.status_code == 200 and wr.content[:4] == b"%PDF":
                return wr.content, "wayback_pdf"
        except Exception as exc:
            log.info("http wayback pdf fail %s: %s", url, exc)
    return b"", "failed"


def extract_field(html: str, name: str) -> str:
    m = re.search(
        rf'field--name-{re.escape(name)}\b.*?(?:field__item|field__items)(.*?)(?:field--name-|\Z)',
        html or "", re.I | re.S,
    )
    if not m:
        return ""
    return html_to_text(m.group(1))


def parse_ra_page(html: str, url: str) -> dict:
    title = extract_field(html, "field-full-title-of-issuance") or ""
    if not title:
        tm = re.search(r"<title>\s*([^<]+)", html or "", re.I)
        if tm:
            title = re.sub(r"\s+", " ", tm.group(1)).split("|")[0].strip()
    body = extract_field(html, "body")
    date = iso_date(extract_field(html, "field-date-of-approval"))
    if not date:
        dm = re.search(r"(\d{4}-\d{2}-\d{2})", extract_field(html, "field-date-of-approval") or html[:8000] or "")
        date = dm.group(1) if dm else None
    og_src = extract_field(html, "field-official-gazette-source")
    pdfs = []
    for href in re.findall(r'href="(https?://issuances-library\.senate\.gov\.ph/sites/default/files/[^"]+\.pdf)"', html or "", re.I):
        pdfs.append(href)
    for href in re.findall(r'href="(/sites/default/files/[^"]+\.pdf)"', html or "", re.I):
        pdfs.append(urljoin(SENATE_LIB, href))
    return {"title": title, "body": body, "date": date, "og_source": og_src, "pdfs": pdfs, "url": url}


def discover_senate() -> list[dict]:
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    items: list[dict] = []
    if cat.exists() and cat.stat().st_size > 500:
        with cat.open(encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("kind") == "constitution" or row.get("slug"):
                    items.append(row)
        if len(items) > 2000:
            log.info("resume catalog %s", len(items))
            return items
    seen = set()
    page = 0
    stagnant = 0
    last_page = 250
    while page <= last_page + 2 and page < 400:
        url = f"{RA_LIST}?field_date_of_approval_value=All&sort_by=field_title_sort_of_issuance_value&sort_order=DESC&items_per_page=50&page={page}"
        html, method = get_html(url)
        if not html:
            log.warning("listing page=%s empty method=%s", page, method)
            stagnant += 1
            if stagnant >= 4:
                break
            page += 1
            continue
        if page == 0:
            nums = [int(x) for x in re.findall(r"[?&]page=(\d+)", html)]
            if nums:
                last_page = max(nums)
            tot = re.search(r"of\s+([\d,]+)", html)
            log.info("listing last_page=%s total_hint=%s method=%s", last_page, tot.group(1) if tot else "?", method)
        newc = 0
        candidates = []
        for m in RA_HREF.finditer(html):
            rel = m.group(1)
            nm = RA_NO.search(rel)
            num = nm.group(1) if nm else ""
            candidates.append((num, urljoin(SENATE_LIB, rel), rel.rsplit("/", 1)[-1].lower()))
        for m in RA_ENC.finditer(html):
            rel = m.group(1)
            decoded = unquote(rel.replace("+", " "))
            nm = re.search(r"(\d+)\s*$", decoded)
            num = nm.group(1) if nm else ""
            # keep percent-encoding; senate aliases 404 on the hyphen slug
            url = urljoin(SENATE_LIB, rel)
            slug = f"republic-act-no-{num}" if num else decoded.lower()
            candidates.append((num, url, slug))
        for num in RA_TITLE_NO.findall(html):
            slug = f"republic-act-no-{num}"
            url = urljoin(SENATE_LIB, f"legislative%2Bissuances/Republic%20Act%20No.%20{num}")
            candidates.append((num, url, slug))
        # prefer hyphen slug URLs when both exist
        by_num = {}
        for num, url, slug in candidates:
            if not num:
                continue
            prev = by_num.get(num)
            if prev is None or ("/legislative-issuance/republic-act-no-" in url and "/legislative-issuance/republic-act-no-" not in prev[0]):
                by_num[num] = (url, slug)
        for num, (url, slug) in by_num.items():
            if num in seen:
                continue
            seen.add(num)
            row = {
                "kind": "ra",
                "slug": slug,
                "url": url,
                "number": num,
                "list_method": method,
            }
            items.append(row)
            append_catalog(CC, row)
            newc += 1
        log.info("listing p=%s new=%s total=%s", page, newc, len(items))
        if newc == 0:
            stagnant += 1
            # keep walking; some Drupal pages omit rows; encoded aliases appear later
            if stagnant >= 12 and page >= last_page:
                break
        else:
            stagnant = 0
        page += 1
    # constitution seeds (Official Gazette first)
    for u in CONST_URLS:
        row = {"kind": "constitution", "slug": "1987-constitution", "url": u, "number": "1987"}
        if u not in {x.get("url") for x in items}:
            items.append(row)
            append_catalog(CC, row)
    log.info("catalog discovered %s", len(items))
    return items


def pick_ra_pdf(pdfs: list[str], number: str) -> Optional[str]:
    if not pdfs:
        return None
    scored = []
    for p in pdfs:
        name = unquote(p.split("/")[-1]).lower()
        score = 0
        if number and number in re.sub(r"\D", "", name + p):
            score += 5
        if re.search(r"\bra[\s_\-]*0*" + re.escape(number or "") + r"\b", name) or "ra-" in name or "ra_" in name or name.startswith("ra"):
            score += 4
        if any(x in name for x in ("history", "hrep", "deliberation", "plenary", "journal")):
            score -= 6
        scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    return scored[0][1] if scored else pdfs[0]


def fetch_constitution(it: dict, done: set[str]) -> str:
    ident = "constitution-1987"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    text = ""
    method = "failed"
    source_url = it.get("url") or CONST_URLS[0]
    used = source_url
    for u in [source_url] + [x for x in CONST_URLS if x != source_url]:
        if u.lower().endswith(".pdf"):
            raw, method = get_bytes(u)
            if not raw:
                res = af.get_wayback_content(u)
                if res.get("status") == "success" and res.get("content"):
                    raw, method = res["content"], "wayback_pdf"
            text = pdf_to_text(raw) if raw else ""
        else:
            html, method = get_html(u)
            text = html_to_text(html) if html else ""
            if len(text) < 800 and html:
                # try linked PDF
                for href in re.findall(r'href="([^"]+\.pdf)"', html, re.I):
                    pdfu = urljoin(u, href)
                    raw, pm = get_bytes(pdfu)
                    if not raw:
                        res = af.get_wayback_content(pdfu)
                        if res.get("status") == "success" and res.get("content"):
                            raw, pm = res["content"], "wayback_pdf"
                    pt = pdf_to_text(raw) if raw else ""
                    if len(pt) > len(text):
                        text, method, used = pt, pm, pdfu
        if len(text) >= 800:
            source_url = used
            break
    if len(text) < 400:
        log_failure(CC, {"identifier": ident, "source_url": source_url, "status": "failed", "reason": "empty_constitution"})
        return "fail"
    docs = split_ph(text, rid, source_url, "1987-02-02")
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident,
        title="The 1987 Constitution of the Republic of the Philippines",
        text=text, source_url=source_url, source_type="official_gazette",
        license_text=LICENSE, collector="ph-official-gazette-senate",
        date="1987-02-02", official_identifier="1987 Constitution",
        document_type="constitution", law_status="current", is_current=True,
        documents=docs,
        extra_meta={
            "discovery": {"method": "official_gazette_constitution", "retrieval": method},
            "official_metadata": {"kind": "constitution"},
        },
        extra_fields={
            "canonical_title": "The 1987 Constitution of the Republic of the Philippines",
            "citation": "1987 Constitution",
            "canonical_document_url": source_url,
            "status_source": "official_gazette",
            "status_note": "Official Gazette authentic text prevails. Not Lawphil/Chan Robles.",
        },
    )
    rec["id"] = rid
    rec["languages"] = ["en"]
    write_instrument(CC, rec)
    return "ok"


def fetch_one(it: dict, done: set[str]) -> str:
    if it.get("kind") == "constitution":
        return fetch_constitution(it, done)
    slug = (it.get("slug") or "").lower()
    number = str(it.get("number") or "")
    enc = urljoin(SENATE_LIB, f"legislative%2Bissuances/Republic%20Act%20No.%20{number}") if number else ""
    hyp = urljoin(SENATE_LIB, f"legislative-issuance/republic-act-no-{number}") if number else ""
    url = enc or it.get("url") or urljoin(SENATE_LIB, f"legislative-issuance/{slug}")
    ident = slug or f"ra-{number}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    html, method = get_html(url)
    alts = []
    if number:
        enc = urljoin(SENATE_LIB, f"legislative%2Bissuances/Republic%20Act%20No.%20{number}")
        hyp = urljoin(SENATE_LIB, f"legislative-issuance/republic-act-no-{number}")
        alts = [u for u in (enc, hyp) if u.rstrip("/") != url.rstrip("/")]
    if (not html or "field--name-body" not in html) and alts:
        for alt in alts:
            html2, m2 = get_html(alt)
            if html2 and ("field--name-body" in html2 or "sites/default/files" in html2):
                html, method, url = html2, m2, alt
                break
    if not html:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "empty_page"})
        return "fail"
    meta = parse_ra_page(html, url)
    text = meta.get("body") or ""
    pdf_url = None
    if len(text) < MIN_TEXT:
        pdf_url = pick_ra_pdf(meta.get("pdfs") or [], number)
        if pdf_url:
            raw, pm = get_bytes(pdf_url)
            pt = pdf_to_text(raw) if raw else ""
            if len(pt) >= MIN_TEXT:
                text, method = pt, pm
    if len(text) < MIN_TEXT:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "empty_text",
                         "pdfs": (meta.get("pdfs") or [])[:3]})
        return "fail"
    title = meta.get("title") or f"Republic Act No. {number}".strip()
    official = f"Republic Act No. {number}" if number else title
    date = meta.get("date")
    docs = split_ph(text, rid, url, date)
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=ident,
        title=title, text=text, source_url=url, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="ph-official-gazette-senate",
        date=date if date and re.match(r"^\d{4}-\d{2}-\d{2}$", date or "") else None,
        official_identifier=official, document_type="statute",
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "discovery": {
                "method": "senate_lrb_republic_acts",
                "seed_url": RA_LIST,
                "pdf_url": pdf_url,
                "retrieval": method,
                "official_gazette_cite": meta.get("og_source") or "",
            },
            "official_metadata": {"slug": slug, "number": number, "kind": "republic_act"},
        },
        extra_fields={
            "canonical_title": title,
            "citation": official,
            "canonical_document_url": pdf_url or url,
            "status_source": "senate_lrb_issuances_library",
            "status_note": "Official Gazette authentic text prevails. Senate LRB hosts official RA texts. Not Lawphil/Chan Robles.",
        },
    )
    rec["id"] = rid
    rec["languages"] = ["en"]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover_senate()
    def _num(it):
        try:
            return int(str(it.get("number") or "0"))
        except Exception:
            return 0
    # Oldest first: Drupal aliases 404 on hyphen slugs; encoded "Republic Act No. N" works.
    items = sorted(items, key=_num)
    done = existing_ids(CC)
    ok = skip = fail = 0
    log.info("queue %s already_done=%s oldest_first — pause before fetch", len(items), len(done))
    import time as _time
    _time.sleep(5)
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
                    source="Official Gazette + Senate LRB Republic Acts",
                    source_urls=[OG, SENATE_LIB, RA_LIST],
                    license_text=LICENSE, discovered=len(items), fetched=ok,
                    skipped=skip, failed=fail, coverage="catalog-backed incomplete",
                    notes="RA + Constitution. Official Gazette prevails. Not Lawphil/Chan Robles.",
                    last_run=utcnow(),
                )
    coverage = "full" if fail == 0 and ok + skip >= len(items) and items else "catalog-backed incomplete"
    notes = (
        "Republic Acts from Senate LRB issuances-library.senate.gov.ph "
        f"({len(items)} catalog rows including Constitution seeds). "
        "Official Gazette live is Cloudflare-challenged from this host; Constitution "
        "fetched via live Senate/OG or archive_fallbacks of officialgazette.gov.ph URLs. "
        "Not Lawphil. Not Chan Robles. Official Gazette authentic text prevails. "
        f"Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Official Gazette + Senate LRB Republic Acts",
        source_urls=[OG, SENATE_LIB, RA_LIST, "https://web.senate.gov.ph/", "https://www.congress.gov.ph/"],
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
