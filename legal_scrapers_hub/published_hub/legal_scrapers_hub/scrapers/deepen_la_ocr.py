#!/usr/bin/env python3
"""Laos deepen: quarantine site-chrome/annex junk; fetch gazette PDFs with OCR."""
from __future__ import annotations
import json, logging, re, shutil, sys, time
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, existing_ids, log_failure, utcnow, write_instrument, write_summary, base_record, slug_id
from world_lib import cdx_urls, env_int, setup_log, live_get
import archive_fallbacks as af
from pdf_extract_lib import extract_pdf_text, extract_ocr, honest_split, is_garbage_text

CC, COUNTRY, LANG = "la", "Laos", "lo"
SOURCE_TYPE = "lao_official_gazette"
LICENSE = (
    "Lao Official Gazette (laoofficialgazette.gov.la). "
    "Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.laoofficialgazette.gov.la/)"
log = logging.getLogger("la_ocr")
JUNK = re.compile(r"(Laogazette|ໜ້າຫຼັກ|ເອກະສານຊ້ອນທ້າຍ|Sawn wood|ໄມ້ແປຮູບ)", re.I)


def quarantine_junk() -> int:
    instr = ROOT / CC / "instruments"
    q = ROOT / CC / "quarantine_nonlaws"
    q.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in list(instr.glob("*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        text = rec.get("text") or ""
        title = rec.get("title") or ""
        if JUNK.search(title) or JUNK.search(text[:500]) or text.lstrip().startswith("Laogazette"):
            shutil.move(str(p), str(q / p.name))
            n += 1
            log.info("quarantine %s", p.name)
    return n


def discover():
    items, seen = [], set()
    def add(url, ts=None):
        url = (url or "").split("#")[0].split("?")[0]
        low = url.lower()
        if ".pdf" not in low or "laoofficialgazette.gov.la" not in low:
            return
        key = low.replace("http://", "https://")
        if key in seen:
            return
        seen.add(key)
        stem = Path(unquote(urlparse(url).path)).stem[:140] or "la-doc"
        items.append((stem, url.replace("http://", "https://").replace(":80/", "/"), ts))
    home = "https://www.laoofficialgazette.gov.la/"
    try:
        r = live_get(home, ua=UA, verify=False, timeout=(20, 60))
        if r is not None and getattr(r, "status_code", None) == 200:
            for href in re.findall(r'href="([^"]+\.pdf[^"]*)"', r.text or "", re.I):
                from urllib.parse import urljoin
                add(urljoin(home, href))
    except Exception as exc:
        log.info("home %s", exc)
    for prefix in (
        "laoofficialgazette.gov.la/kcfinder/upload/files/",
        "www.laoofficialgazette.gov.la/kcfinder/upload/files/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 120), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            add(h.get("original") or "", h.get("timestamp"))
    log.info("catalog %s", len(items))
    return items


def fetch_pdf(url: str, ts=None) -> tuple[bytes, str]:
    import requests
    requests.packages.urllib3.disable_warnings()
    try:
        r = requests.get(url, timeout=(15, 70), verify=False, headers={"User-Agent": UA})
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            return r.content, "http_pdf"
    except Exception:
        pass
    if ts:
        w = af.get_wayback_content(url, timestamp=ts)
        body = w.get("content") or b""
        if w.get("status") == "success" and body[:4] == b"%PDF":
            return body, "wayback_pdf"
    w = af.get_wayback_content(url)
    body = w.get("content") or b""
    if w.get("status") == "success" and body[:4] == b"%PDF":
        return body, "wayback_pdf"
    return b"", "fail"


def main():
    setup_log(CC, "la_ocr")
    t0 = utcnow()
    qn = quarantine_junk()
    max_new = env_int("MAX_NEW", 20)
    max_seconds = env_int("MAX_SECONDS", 2400)
    ocr_pages = env_int("OCR_PAGES", 20)
    max_ocr = env_int("MAX_OCR", 20)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = ocr_used = 0
    for ident, url, ts in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        raw, method = fetch_pdf(url, ts)
        if not raw:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "fetch_fail"})
            continue
        text, how, pages = extract_pdf_text(raw, enable_ocr=False, ocr_lang="lao+eng", ocr_max_pages=ocr_pages)
        if (is_garbage_text(text) or len(text) < 200) and ocr_used < max_ocr:
            try:
                otext, opages = extract_ocr(raw, lang="lao+eng", max_pages=ocr_pages)
                ocr_used += 1
                if otext and len(otext) >= 80 and not is_garbage_text(otext):
                    text, how, pages = otext, "ocr_tesseract", opages
                elif otext and len(otext) > len(text or ""):
                    text, how, pages = otext, "ocr_tesseract", opages
            except Exception as exc:
                log.warning("ocr %s: %s", ident[:40], exc)
        if not text or len(text) < 100 or is_garbage_text(text) or JUNK.search(text[:400]):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": f"thin_or_junk:{how}"})
            continue
        docs, kind = honest_split(CC, text, rid, url)
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 12 and not JUNK.search(line):
                title = line.strip()[:240]
                break
        rec = base_record(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="deepen_la_ocr.py",
            documents=docs,
            extra_meta={
                "fetch_method": method, "extract_method": how, "pages": pages,
                "pdf_parser": "ipfs_datasets_py.IntegratedPDFProcessor",
                "article_split": {"method": kind, "count": len(docs)},
                "wayback_ts": ts,
            },
        )
        write_instrument(CC, rec)
        ok += 1
        done.add(rid)
        log.info("ok %s extract=%s arts=%s chars=%s", ident[:60], how, len(docs), len(text))
    write_summary(
        CC, country=COUNTRY, source="Lao Official Gazette",
        source_urls=["https://www.laoofficialgazette.gov.la/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (OCR of official gazette PDFs)",
        notes=f"Quarantined {qn} junk. OCR used={ocr_used}. Honest Article/ມາດຕາ splits. Not legal advice.",
        last_run=t0,
    )
    laws = arts = 0
    for p in (ROOT / CC / "instruments").glob("*.json"):
        rec = json.loads(p.read_text())
        if len(rec.get("text") or "") >= 80:
            laws += 1
            arts += len(rec.get("documents") or [])
    print(json.dumps({"ok": ok, "skip": skip, "fail": fail, "ocr_used": ocr_used, "quarantined": qn, "laws": laws, "arts": arts}))


if __name__ == "__main__":
    main()
