#!/usr/bin/env python3
"""Antigua and Barbuda: laws.gov.ag (Acts / Caps / SI / Sub-laws) + Official Gazette.

Official-only *.gov.ag. Live laws.gov.ag WP shelf + gazette.laws.gov.ag Official Gazette
PDFs + CDX of the same official URLs. Not vLex / commercial aggregators.
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
from urllib.parse import urljoin, urlparse, unquote, quote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text
import requests

CC, COUNTRY, LANG = "ag", "Antigua and Barbuda", "en"
SOURCE_TYPE = "laws_gov_ag"
LICENSE = (
    "Government of Antigua and Barbuda — laws.gov.ag / Official Gazette "
    "(gazette.laws.gov.ag; Ministry of Justice & Legal Affairs). "
    "Authentic Official Gazette / Government Printer text prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://laws.gov.ag/)"
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
log = logging.getLogger("ag")
MAX_PDF = env_int("MAX_PDF_BYTES", 10 * 1024 * 1024)

HOST_OK = (
    "laws.gov.ag",
    "gazette.laws.gov.ag",
    "legalaffairs.gov.ag",
    "ab.gov.ag",
)
SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|order.?of.?the.?day|"
    r"minutes|hansard|favicon|holder__|"
    r"vacancy|petition.?for.?a.?licence|permanent.?residence.?scheme|"
    r"special.?marriage|local.?marriage|"
    r"nclhl1|individual.?form|"
    r"\bbill\b|bills?/|Amendment-Bill|Amendment_Bill)",
    re.I,
)
KEEP_RE = re.compile(
    r"(gazette|act|acts|constitution|cap|chapter|statutory|instrument|"
    r"s[_ ]?i|si[_-]|regulation|order|rules?|subsidiary|sub-laws?|"
    r"extraordinary|supplementary|wp-content/uploads|/acts/|/pdf/|"
    r"2004Laws|parliament)",
    re.I,
)
CDX_PREFIXES = (
    "laws.gov.ag/wp-content/uploads/",
    "www.laws.gov.ag/wp-content/uploads/",
    "laws.gov.ag/acts/",
    "www.laws.gov.ag/acts/",
    "gazette.laws.gov.ag/wp-content/uploads/",
    "legalaffairs.gov.ag/pdf/",
    "www.ab.gov.ag/gov_v1/parliament/",
)
# Antigua and Barbuda Constitution Order (Cap. 23)
SEED_DOCS = (
    (
        "https://laws.gov.ag/wp-content/uploads/2018/08/cap-23.pdf",
        "Antigua and Barbuda Constitution Order Cap. 23",
        "CONSTITUTION",
    ),
)
LIVE_PAGES = (
    "https://laws.gov.ag/laws/alphabetical/",
    "https://laws.gov.ag/caps/",
    "https://laws.gov.ag/annual/",
    "https://laws.gov.ag/statutory/",
    "https://laws.gov.ag/sub-laws/",
    "https://laws.gov.ag/repealed-laws/",
    "http://gazette.laws.gov.ag/",
    "https://legalaffairs.gov.ag/",
)
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    # strip cache-buster query on gazette PDFs
    if "?" in url and ".pdf" in url.lower():
        url = url.split("?")[0]
    # Prefer https for laws.gov.ag; keep http for gazette (https redirects to IRD)
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("laws.gov.ag") and not host.startswith("gazette."):
        url = url.replace("http://", "https://").replace(":80/", "/")
    elif host == "legalaffairs.gov.ag" or host.endswith(".ab.gov.ag") or host == "ab.gov.ag":
        url = url.replace("http://", "https://").replace(":80/", "/")
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h == host or host.endswith("." + h) for h in HOST_OK)


def _category(url: str, hint: str = "") -> str:
    blob = f"{url} {hint}".lower()
    if "constitution" in blob and "referendum" not in blob and "redress" not in blob:
        return "CONSTITUTION"
    if re.search(r"\bcap[_\-\s]?\d|/caps/|chapters/cap", blob):
        return "CAP"
    if re.search(r"/acts/|a\d{4}-\d+|no\.\-?\d+.*act|\bact\b", blob) and "bill" not in blob:
        if re.search(r"statutory|regulation|order|instrument|s\.?i\.?", blob) and "act" not in Path(urlparse(url).path).stem.lower():
            pass
        elif re.search(r"\bact\b|a\d{4}-\d+|-/acts/", blob):
            return "ACT"
    if re.search(r"statutory|sub-laws?|subsidiary|regulation|s[_ /]?i\b|instrument", blob):
        return "SI"
    if "gazette" in blob or "extraordinary" in blob or "supplementary" in blob:
        return "GAZETTE"
    if re.search(r"\bact\b|a\d{4}-\d+", blob):
        return "ACT"
    if re.search(r"\bcap", blob):
        return "CAP"
    return ""


def _ident_from_url(url: str, hint: str = "") -> str:
    if hint:
        stem = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if stem and len(stem) > 8:
            return stem
    path = unquote(urlparse(url).path)
    stem = Path(path).stem[:160] or "doc"
    return stem[:160]


def _rank(ident: str, cat: str, url: str) -> int:
    blob = f"{ident} {cat} {url}".lower()
    if "constitution" in blob and "cap-23" in blob.replace("_", "-"):
        return 0
    if cat == "CONSTITUTION" or ("constitution" in blob and "bill" not in blob):
        return 0
    if cat == "CAP" or re.search(r"\bcap[_\-\s]?\d", blob):
        return 1
    if cat == "ACT" or re.search(r"/acts/|a\d{4}-\d+|act[-_]", blob):
        return 2
    if cat == "SI" or re.search(r"statutory|regulation|sub-law|subsidiary", blob):
        return 3
    if cat == "GAZETTE" or "gazette" in blob:
        return 4
    return 5


def discover():
    items, seen_url, best = [], set(), {}

    def add(url, ts="", title_hint="", cat=""):
        url = _norm(url)
        low = url.lower()
        if ".pdf" not in low:
            return
        if not _host_ok(url):
            return
        blob = f"{low} {title_hint} {cat}"
        if SKIP_RE.search(blob):
            return
        if not KEEP_RE.search(blob):
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
    # Disable SSL verify — some *.gov.ag certs chain poorly
    sess.verify = False
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    # Alphabetical letter shelves (primary Acts/Caps catalog)
    for letter in LETTERS:
        page = f"https://laws.gov.ag/laws/alphabetical/?letter={letter}"
        try:
            r = sess.get(page, timeout=45)
            if r.status_code != 200:
                log.warning("alpha %s status=%s", letter, r.status_code)
                continue
            for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)', r.text, re.I):
                full = urljoin(r.url, href)
                tip = Path(unquote(urlparse(full).path)).stem
                add(full, "", tip.replace("_", " ").replace("-", " ")[:200])
            log.info("alpha %s catalog=%s", letter, len(best))
        except Exception as exc:
            log.warning("alpha %s fail: %s", letter, exc)

    # Section landing pages
    for page in LIVE_PAGES:
        try:
            r = sess.get(page, timeout=45)
            if r.status_code != 200:
                log.warning("live %s status=%s", page, r.status_code)
                continue
            for href in re.findall(r'href=["\']([^"\']+)["\']', r.text, re.I):
                full = urljoin(r.url, href)
                if ".pdf" in full.lower():
                    tip = Path(unquote(urlparse(full).path)).stem
                    add(full, "", tip.replace("_", " ").replace("-", " ")[:200])
            log.info("live %s catalog=%s", page, len(best))
        except Exception as exc:
            log.warning("live %s fail: %s", page, exc)

    # WP media API — laws.gov.ag (newest first; still useful for recent Acts/SIs)
    media_pages = env_int("WP_MEDIA_PAGES", 12)
    for host_base, pages in (
        ("https://laws.gov.ag", media_pages),
        ("http://gazette.laws.gov.ag", min(media_pages, 6)),
    ):
        for page in range(1, pages + 1):
            api = f"{host_base}/wp-json/wp/v2/media?per_page=100&mime_type=application/pdf&page={page}"
            try:
                r = sess.get(api, timeout=45)
                if r.status_code != 200:
                    break
                data = r.json()
                if not data:
                    break
                for item in data:
                    src = item.get("source_url") or ""
                    title = ""
                    t = item.get("title")
                    if isinstance(t, dict):
                        title = re.sub(r"<[^>]+>", "", t.get("rendered") or "")
                    add(src, "", title[:200])
                log.info("wp %s page=%s catalog=%s", host_base, page, len(best))
            except Exception as exc:
                log.warning("wp %s page %s fail: %s", host_base, page, exc)
                break

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
                    add(orig, ts)
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
    got = fetch_official(
        url, ua=UA, verify=False, min_text=120, wayback_ts=wayback_ts or None
    )
    if got.get("status") == "success":
        return got
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_ag.py",
            article_re=use_re,
            extra_meta={"fetch_method": got.get("method"), "category": cat, "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Antigua and Barbuda laws.gov.ag / Official Gazette",
        source_urls=[
            "https://laws.gov.ag/",
            "https://laws.gov.ag/laws/alphabetical/",
            "https://laws.gov.ag/caps/",
            "https://laws.gov.ag/statutory/",
            "https://laws.gov.ag/sub-laws/",
            "http://gazette.laws.gov.ag/",
            "https://legalaffairs.gov.ag/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (laws.gov.ag Acts/Caps/SI/Sub-laws + Official Gazette + CDX)",
        notes=(
            f"Official laws.gov.ag WP PDFs + gazette.laws.gov.ag Official Gazette; "
            f"live-first + Wayback CDX. Prefer Constitution Cap.23 + Caps + Acts + SIs. "
            f"OCR used={ocr_used}. Skip bills/vacancies/forms. Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
