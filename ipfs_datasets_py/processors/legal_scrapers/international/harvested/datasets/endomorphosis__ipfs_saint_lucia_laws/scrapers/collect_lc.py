#!/usr/bin/env python3
"""Saint Lucia: Official Gazette (npc.govt.lc) + Finance Legal Instruments + core codes.

Official-only *.govt.lc / *.gov.lc / archive.stlucia.gov.lc. National Printing Corporation
Official Gazette PDFs (Acts/SIs published with Gazette) + Department of Finance Legal
Instruments + Constitution / Criminal Code / Labour Code mirrors. Not vLex / commercial.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import logging, os, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text
import requests

CC, COUNTRY, LANG = "lc", "Saint Lucia", "en"
SOURCE_TYPE = "saint_lucia_official_gazette"
LICENSE = (
    "Government of Saint Lucia — Official Gazette / Laws of Saint Lucia "
    "(npc.govt.lc National Printing Corporation; finance.gov.lc; archive.stlucia.gov.lc). "
    "Authentic Official Gazette / Government Printer text prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://npc.govt.lc/gazettes)"
)
# Commonwealth Cap / Constitution densify (OECS Cap-style Section split)
# Short Cap headings + legal openers; ART_NARROW for gazette shells / speeches.
ART = re.compile(
    r"(?im)^\s*((?:Section|SECTION|Article|Art\.?|SCHEDULE|Schedule|PART|Part|CHAPTER|Chapter)\s+[0-9IVXLC]+[A-Za-z]?\b|"
    r"s\.\s*[0-9]+[A-Za-z]?\b|"
    r"\d+[A-Za-z]?\.\s+[A-Z][A-Za-z0-9'()\-/ ,\"]{0,55}\.?\s*$|"
    r"\d+[A-Za-z]?\.\s+(?:This |In |These |The |For |Any |Every |Where |If |Subject |"
    r"No |Nothing |Notwithstanding |On |It |Whenever |Unless |Except |"
    r"\([0-9]|[\"'])"
    r")"
)
ART_NARROW = re.compile(
    r"(?im)^\s*((?:Section|Article|Art\.?|SCHEDULE|Schedule)\s+[0-9]+[A-Za-z]?|"
    r"s\.\s*[0-9]+[A-Za-z]?)\b"
)
log = logging.getLogger("lc")
MAX_PDF = env_int("MAX_PDF_BYTES", 10 * 1024 * 1024)

HOST_OK = (
    "npc.govt.lc",
    "govt.lc",
    "finance.gov.lc",
    "commerce.gov.lc",
    "archive.stlucia.gov.lc",
    "stlucia.gov.lc",
    "gov.lc",
)
SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|order.?of.?the.?day|"
    r"minutes|hansard|favicon|holder__|staff.?orders?|"
    r"audit[_ ]?report|budget.?address|throne.?speech|economic.?review|"
    r"vacancy|tender|questionnaire|communiqu|"
    r"\bbill\b|draft-|draft_|draft\s|circulated for feedback|"
    r"\.docx?$|\.jpe?g$|\.png$|\.doc$)",
    re.I,
)
KEEP_RE = re.compile(
    r"(gazette|act|acts|constitution|cap|chapter|statutory|instrument|"
    r"s[_ ]?i|si[_-]|regulation|order|rules?|code|labour|criminal|"
    r"/gazettes/|/legislation/|/resources/download/|"
    r"extraordinary|extra-?ordinary|assented)",
    re.I,
)
CDX_PREFIXES = (
    "npc.govt.lc/files/documents/gazettes/",
    "www.npc.govt.lc/files/documents/gazettes/",
    "www.govt.lc/media.govt.lc/www/legislation/",
    "govt.lc/media.govt.lc/www/legislation/",
    "archive.stlucia.gov.lc/docs/",
    "stlucia.gov.lc/docs/",
    "www.finance.gov.lc/resources/download/",
    "finance.gov.lc/resources/download/",
)
SEED_DOCS = (
    (
        "https://npc.govt.lc/files/documents/Constitution%20of%20Saint%20Lucia.pdf",
        "Constitution of Saint Lucia",
        "CONSTITUTION",
    ),
    (
        "https://archive.stlucia.gov.lc/docs/DisasterManagementAct.pdf",
        "Disaster Management Act 2006",
        "ACT",
    ),
    (
        "https://archive.stlucia.gov.lc/docs/Policy%20Documents/St%20Lucia%20Labour%20Code%20-%202006.pdf",
        "Saint Lucia Labour Code 2006",
        "CODE",
    ),
    # Wayback-backed core codes on former govt.lc legislation shelf
    (
        "http://www.govt.lc/media.govt.lc/www/legislation/ConstitutionOfSaintLucia.pdf",
        "Constitution of Saint Lucia",
        "CONSTITUTION",
    ),
    (
        "http://www.govt.lc/media.govt.lc/www/legislation/Criminal%20Code.pdf",
        "Criminal Code of Saint Lucia",
        "CODE",
    ),
    (
        "http://www.govt.lc/media.govt.lc/www/legislation/SaintLuciaLabourCode2006.pdf",
        "Saint Lucia Labour Code 2006",
        "CODE",
    ),
)
FINANCE_PAGES = (
    "https://www.finance.gov.lc/resources/index/33",  # Legal Instruments
    "https://www.finance.gov.lc/resources/index/36",  # Public Finance Management Regulations
)
GAZETTE_YEAR_START = 2004
GAZETTE_YEAR_END = 2026


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    # Keep finance download query-less path; strip cache-busters on PDFs
    if "?" in url and (".pdf" in url.lower() or "/resources/download/" in url.lower()):
        # finance download IDs have no query usually; strip anyway for PDFs
        if "/resources/download/" not in url.lower() or ".pdf" in url.lower():
            url = url.split("?")[0]
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("govt.lc") or host.endswith("gov.lc") or host.endswith("stlucia.gov.lc"):
        # Prefer https except where known-broken; npc/finance tolerate https
        if host.startswith("www.govt.lc") and "/media.govt.lc/" in url:
            # live 403/HTML; keep http original for Wayback matching
            pass
        else:
            url = url.replace("http://", "https://").replace(":80/", "/")
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h == host or host.endswith("." + h) for h in HOST_OK)


def _category(url: str, hint: str = "") -> str:
    blob = f"{url} {hint}".lower()
    if "constitution" in blob:
        return "CONSTITUTION"
    if re.search(r"\bcode\b|labour.?code|criminal.?code", blob):
        return "CODE"
    if re.search(r"statutory|s[_ /]?i\b|instrument|regulation", blob) and "act" not in Path(
        urlparse(url).path
    ).stem.lower():
        if re.search(r"\bact\b", blob):
            pass
        else:
            return "SI"
    if re.search(r"\bact\b|appropriation|assented", blob):
        return "ACT"
    if re.search(r"extra-?ordinary|extraordinary", blob):
        return "EXTRAORDINARY"
    if "gazette" in blob or "/gazettes/" in blob:
        return "GAZETTE"
    if re.search(r"regulation|order|rules?", blob):
        return "SI"
    return ""


def _ident_from_url(url: str, hint: str = "") -> str:
    if hint:
        stem = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if stem and len(stem) > 6:
            return stem
    path = unquote(urlparse(url).path)
    if "/resources/download/" in path:
        # finance opaque id — prefer hint; else download_N
        m = re.search(r"/download/(\d+)", path)
        return f"finance_download_{m.group(1)}" if m else (Path(path).stem[:160] or "doc")
    stem = Path(path).stem[:160] or "doc"
    return stem[:160]


def _rank(ident: str, cat: str, url: str) -> int:
    blob = f"{ident} {cat} {url}".lower()
    if cat == "CONSTITUTION" or "constitution" in blob:
        return 0
    if cat == "CODE" or re.search(r"criminal.?code|labour.?code", blob):
        return 1
    if cat == "ACT" or re.search(r"\bact\b|assented", blob):
        return 2
    if cat == "SI" or re.search(r"statutory|regulation", blob):
        return 3
    if cat == "EXTRAORDINARY" or "extra" in blob and "gazette" in blob:
        return 4
    if cat == "GAZETTE" or "/gazettes/" in blob or "gazette" in blob:
        return 5
    return 6


def discover():
    items, seen_url, best = [], set(), {}

    def add(url, ts="", title_hint="", cat=""):
        url = _norm(url)
        low = url.lower()
        is_finance_dl = "/resources/download/" in low
        if ".pdf" not in low and not is_finance_dl:
            return
        if not _host_ok(url):
            return
        blob = f"{low} {title_hint} {cat}"
        if SKIP_RE.search(blob):
            return
        if not KEEP_RE.search(blob) and not is_finance_dl:
            return
        # finance: require keep-ish title/filename (acts/SI/gazette/regs)
        if is_finance_dl and not KEEP_RE.search(blob):
            return
        cat = cat or _category(url, title_hint)
        ident = _ident_from_url(url, title_hint)
        if url in seen_url:
            return
        seen_url.add(url)
        row = (ident, url, (title_hint or "").strip()[:200], cat, ts or "")
        prev = best.get(ident)
        if prev is None or _rank(row[0], row[3], row[1]) < _rank(prev[0], prev[3], prev[1]):
            best[ident] = row
        elif _rank(row[0], row[3], row[1]) == _rank(prev[0], prev[3], prev[1]):
            if (ts or "") > (prev[4] or ""):
                best[ident] = row

    for url, hint, cat in SEED_DOCS:
        add(url, "", hint, cat)

    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    sess.headers["Accept"] = "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8"
    sess.verify = False
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    # --- National Printing Corporation Official Gazette (primary) ---
    for year in range(GAZETTE_YEAR_END, GAZETTE_YEAR_START - 1, -1):
        try:
            yr = sess.get(f"https://npc.govt.lc/gazettes/{year}", timeout=45)
            if yr.status_code != 200:
                log.warning("gaz year %s status=%s", year, yr.status_code)
                continue
            months = sorted(
                {int(m) for m in re.findall(rf"/gazettes/{year}/(\d+)", yr.text)},
                reverse=True,
            )
            for month in months:
                page = f"https://npc.govt.lc/gazettes/{year}/{month}"
                try:
                    r = sess.get(page, timeout=45)
                    if r.status_code != 200:
                        continue
                    for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)', r.text, re.I):
                        full = urljoin(r.url, href)
                        tip = Path(unquote(urlparse(full).path)).stem
                        tip_h = tip.replace("_", " ").replace("-", " ")[:200]
                        add(full, "", tip_h)
                except Exception as exc:
                    log.warning("gaz %s/%s fail: %s", year, month, exc)
            log.info("gaz year %s catalog=%s", year, len(best))
        except Exception as exc:
            log.warning("gaz year %s fail: %s", year, exc)

    # Constitution / StaffOrders footer also on laws pages — pick constitution only
    for page in (
        "https://npc.govt.lc/",
        "https://npc.govt.lc/laws",
        "https://npc.govt.lc/gazettes",
    ):
        try:
            r = sess.get(page, timeout=45)
            if r.status_code != 200:
                continue
            for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)', r.text, re.I):
                full = urljoin(r.url, href)
                tip = Path(unquote(urlparse(full).path)).stem.replace("_", " ")[:200]
                add(full, "", tip)
        except Exception as exc:
            log.warning("npc page %s fail: %s", page, exc)

    # --- Department of Finance Legal Instruments ---
    for page in FINANCE_PAGES:
        try:
            r = sess.get(
                page,
                timeout=45,
                headers={"Referer": "https://www.finance.gov.lc/resources/"},
            )
            if r.status_code != 200:
                log.warning("finance %s status=%s", page, r.status_code)
                continue
            for m in re.finditer(
                r'href="(/resources/download/\d+)"[^>]*>([^<]+)</a>'
                r'[\s\S]*?Filename:\s*([^|<]+)',
                r.text,
            ):
                href, title, fname = m.group(1), m.group(2).strip(), m.group(3).strip()
                full = urljoin(r.url, href)
                blob = f"{title} {fname}"
                if SKIP_RE.search(blob):
                    continue
                if not re.search(r"\.pdf\b", fname, re.I) and "gazette" not in blob.lower():
                    # only keep PDF instruments
                    if not re.search(r"\.pdf", fname, re.I):
                        continue
                add(full, "", title[:200] or Path(fname).stem[:200])
            log.info("finance %s catalog=%s", page, len(best))
        except Exception as exc:
            log.warning("finance %s fail: %s", page, exc)

    # --- archive.stlucia.gov.lc docs (legacy official PDFs) ---
    for page in (
        "https://archive.stlucia.gov.lc/",
        "https://archive.stlucia.gov.lc/docs/",
    ):
        try:
            r = sess.get(page, timeout=45)
            if r.status_code != 200:
                continue
            for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)', r.text, re.I):
                full = urljoin(r.url, href)
                tip = Path(unquote(urlparse(full).path)).stem.replace("%20", " ")[:200]
                tip = tip.replace("_", " ")
                add(full, "", tip)
            log.info("archive %s catalog=%s", page, len(best))
        except Exception as exc:
            log.warning("archive %s fail: %s", page, exc)

    lim = env_int("CDX_LIMIT", 1500)
    for prefix in CDX_PREFIXES:
        try:
            for h in cdx_urls(
                prefix,
                limit=lim,
                match_type="prefix",
                extra_filters=["mimetype:application/pdf"],
            ):
                orig = h.get("original") or ""
                ts = h.get("timestamp") or ""
                if orig:
                    tip = Path(unquote(urlparse(orig).path)).stem.replace("_", " ")[:200]
                    add(orig, ts, tip)
        except Exception as exc:
            log.warning("cdx %s fail: %s", prefix, exc)

    items = list(best.values())
    items.sort(key=lambda it: (_rank(it[0], it[3], it[1]), it[1]))
    log.info("catalog %s", len(items))
    return items


def ocr_pdf(raw: bytes) -> tuple[str, str, int]:
    os.environ.setdefault("TESSDATA_PREFIX", "/home/box/tessdata")
    ocr_pages = env_int("OCR_PAGES", 10)
    return extract_pdf_text(raw, enable_ocr=True, ocr_lang="eng", ocr_max_pages=ocr_pages)


def fetch_pdf(url: str, wayback_ts: str = "") -> dict:
    # finance downloads need browser-like Accept + Referer
    got = fetch_official(
        url, ua=UA, verify=False, min_text=120, wayback_ts=wayback_ts or None
    )
    if got.get("status") == "success":
        return got
    # Direct retry for finance.gov.lc download endpoints (406 without Accept)
    if "/resources/download/" in url and got.get("status") != "success":
        try:
            sess = requests.Session()
            sess.headers.update(
                {
                    "User-Agent": UA,
                    "Accept": "application/pdf,*/*;q=0.8",
                    "Referer": "https://www.finance.gov.lc/resources/index/33",
                }
            )
            sess.verify = False
            r = sess.get(url, timeout=90, allow_redirects=True)
            raw = r.content or b""
            if r.status_code == 200 and raw[:4] == b"%PDF" and len(raw) <= MAX_PDF:
                text, how, pages = extract_pdf_text(raw, enable_ocr=False)
                if text and len(text) >= 120:
                    return {
                        "status": "success",
                        "text": text,
                        "method": f"finance_direct:{how}",
                        "content": raw,
                        "error": "",
                    }
                text, how, pages = ocr_pdf(raw)
                if text and len(text) >= 100:
                    return {
                        "status": "success",
                        "text": text,
                        "method": f"finance_ocr:{how}",
                        "content": raw,
                        "error": "",
                    }
        except Exception as exc:
            got["error"] = (got.get("error") or "") + f";finance_direct:{exc}"
    raw = got.get("content") or b""
    if isinstance(raw, bytes) and raw[:4] == b"%PDF" and len(raw) <= MAX_PDF:
        text, how, pages = ocr_pdf(raw)
        if text and len(text) >= 100:
            got.update(status="success", text=text, method=f"ocr:{how}", error="")
            return got
        got["error"] = (got.get("error") or "") + f";ocr_failed:{how}"
    return got


def reprocess_existing() -> int:
    """Re-split articles on saved instruments with Cap densify ART (no re-fetch)."""
    from common import ROOT, atomic_write
    import json
    n = 0
    for path in sorted((ROOT / CC / "instruments").glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        if len(text) < 80:
            continue
        rid = rec.get("id") or path.stem
        cat = ((rec.get("metadata") or {}).get("category") or "")
        blob = (text[:3000] or "").lower()
        if cat in ("GAZETTE", "EXTRAORDINARY") or "budget speech" in blob or "we must " in blob:
            use_re = ART_NARROW
        elif cat in ("ACT", "CONSTITUTION", "SRO", "CAP", "SI", "PRINCIPAL", "AMENDING", "SUBORDINATE", "CODE", "CHAPTER") or "sustant" in cat.lower() or "substant" in cat.lower():
            use_re = ART
        else:
            use_re = ART
        docs = __import__("world_lib", fromlist=["split_custom"]).split_custom(
            text, rid, rec.get("source_url") or "", rec.get("date"), use_re
        )
        old = int(rec.get("article_count") or 0)
        if len(docs) == old and old > 0:
            continue
        if len(docs) < old and old >= 2 and len(docs) < 2:
            continue
        rec["documents"] = docs
        rec["article_count"] = len(docs)
        rec["article_extraction_status"] = "ok" if len(docs) >= 2 else ("missing" if not docs else "partial")
        meta = rec.get("metadata") or {}
        meta["article_re"] = "oecs_cap_section_v1"
        rec["metadata"] = meta
        atomic_write(path, json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
        n += 1
        log.info("reprocess %s arts %s->%s", rid[:70], old, len(docs))
    return n


def main():
    setup_log(CC)
    t0 = utcnow()
    if os.environ.get("REPROCESS_EXISTING", "1") not in ("0", "false", "False"):
        rp = reprocess_existing()
        log.info("reprocessed %s instruments", rp)
    max_new = env_int("MAX_NEW", 150)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = ocr_used = 0
    for ident, url, hint, cat, ts in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_pdf(url, ts)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        if "ocr" in str(got.get("method") or "").lower():
            ocr_used += 1
        title = hint or None
        if not title:
            for line in text.splitlines():
                if len(line.strip()) > 18:
                    title = line.strip()[:240]
                    break
        if cat and title and cat.lower() not in title.lower():
            title = f"{title} [{cat}]"
        if cat in ("GAZETTE", "EXTRAORDINARY"):
            use_re = ART_NARROW
        elif cat in ("ACT", "CONSTITUTION", "SRO", "CAP", "SI", "PRINCIPAL", "AMENDING", "SUBORDINATE", "CODE", "CHAPTER") or "sustant" in (cat or "").lower():
            use_re = ART
        else:
            use_re = ART
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_lc.py",
            article_re=use_re,
            extra_meta={"fetch_method": got.get("method"), "category": cat, "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Saint Lucia Official Gazette / NPC / Finance Legal Instruments",
        source_urls=[
            "https://npc.govt.lc/gazettes",
            "https://npc.govt.lc/laws",
            "https://npc.govt.lc/files/documents/Constitution%20of%20Saint%20Lucia.pdf",
            "https://www.finance.gov.lc/resources/index/33",
            "https://archive.stlucia.gov.lc/docs/",
            "http://www.govt.lc/media.govt.lc/www/legislation/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (NPC Official Gazette + Finance Legal Instruments + core codes + CDX)",
        notes=(
            f"Official npc.govt.lc Gazette PDFs (Acts/SIs published with Gazette) + "
            f"finance.gov.lc Legal Instruments + Constitution/Codes. "
            f"live-first + Wayback CDX. Prefer Constitution + Codes + Acts + SIs + Gazettes. "
            f"OCR used={ocr_used}. Skip bills/drafts/staff-orders. Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
