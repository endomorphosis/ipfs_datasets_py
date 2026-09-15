#!/usr/bin/env python3
"""Dominica: printery.dominica.gov.dm Official Gazette + dominica.gov.dm Revised Laws.

Official-only *.gov.dm / *.dominica.gov.dm. Government Printery Official Gazette /
Acts / S.R.&O. PDFs + Revised Laws chapters and annual Acts/SROs on dominica.gov.dm
+ CDX of the same official URLs. Not vLex / commercial aggregators.
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

CC, COUNTRY, LANG = "dm", "Dominica", "en"
SOURCE_TYPE = "printery_dominica_gov_dm"
LICENSE = (
    "Government of the Commonwealth of Dominica — Official Gazette / Laws "
    "(printery.dominica.gov.dm Government Printery; dominica.gov.dm Revised Laws; "
    "House of Assembly). "
    "Authentic Official Gazette / Government Printer text prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://printery.dominica.gov.dm/)"
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
log = logging.getLogger("dm")
MAX_PDF = env_int("MAX_PDF_BYTES", 10 * 1024 * 1024)

HOST_OK = (
    "printery.dominica.gov.dm",
    "dominica.gov.dm",
    "www.dominica.gov.dm",
    "houseofassembly.gov.dm",
    "finance.gov.dm",
)
SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|order.?of.?the.?day|"
    r"minutes|hansard|favicon|holder__|budget.?address|budget.?speech|"
    r"vacancy|tender|questionnaire|communiqu|"
    r"\bbill\b|draft-|draft_|draft\s|final.?draft|"
    r"commemorative.?stamp|stamp.?issue|stamp.?order|"
    r"pope francis commemorative|"
    r"\.docx?$|\.jpe?g$|\.png$|\.doc$)",
    re.I,
)
KEEP_RE = re.compile(
    r"(gazette|act|acts|constitution|cap|chapter|chap\d|statutory|"
    r"s[_ ]?r[_ ]?&?o|sro|regulation|order|rules?|proclamation|"
    r"by-?law|extraordinary|extra-?ordinary|"
    r"/laws/|/chapters/|/Uploads/|DownloadPreview|"
    r"ProductDocuments)",
    re.I,
)
CDX_PREFIXES = (
    "printery.dominica.gov.dm/Uploads/",
    "printery.dominica.gov.dm/ProductDocuments/",
    "www.dominica.gov.dm/laws/chapters/",
    "dominica.gov.dm/laws/chapters/",
    "www.dominica.gov.dm/laws/",
    "dominica.gov.dm/laws/",
)
SEED_DOCS = (
    (
        "https://www.dominica.gov.dm/laws/chapters/chap1-01.pdf",
        "Constitution of the Commonwealth of Dominica Cap. 1:01",
        "CONSTITUTION",
    ),
    (
        "https://www.dominica.gov.dm/laws/chapters/chap1-01-sch1.pdf",
        "Constitution of Dominica Schedule 1 Cap. 1:01",
        "CONSTITUTION",
    ),
)
# Printery product types: Laws, Gazette, Extraordinary Gazette, By-Law
PRINTERY_TYPES = (
    (1, "LAWS"),       # Acts + SROs shelf
    (4, "GAZETTE"),
    (1004, "EXTRAORDINARY"),
    (1007, "BYLAW"),
)
# Single-letter + keyword terms to walk the Revised Laws search
LAWS_SEARCH_TERMS = tuple("abcdefghijklmnopqrstuvwxyz") + (
    "chapter", "chap", "Act", "constitution", "Order", "Regulation", "SRO",
)


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if "?" in url and ".pdf" in url.lower():
        # keep only path for PDF; drop utm etc.
        url = url.split("?")[0]
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("dominica.gov.dm") or host.endswith("gov.dm"):
        url = url.replace("http://", "https://").replace(":80/", "/")
        # prefer www for laws paths (both work)
        if host == "dominica.gov.dm" and "/laws/" in url:
            url = url.replace("://dominica.gov.dm", "://www.dominica.gov.dm", 1)
    # Percent-encode spaces / unsafe path chars from CDX (e.g. "chap 7-61.pdf")
    try:
        parts = urlparse(url)
        if parts.path and ((" " in parts.path) or any(ord(c) < 33 for c in parts.path)):
            segs = parts.path.split("/")
            enc = "/".join(quote(unquote(s), safe=".-_()%") for s in segs)
            url = parts._replace(path=enc).geturl()
    except Exception:
        pass
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h == host or host.endswith("." + h) for h in HOST_OK) or host.endswith(
        ".gov.dm"
    ) or host.endswith("dominica.gov.dm")


def _category(url: str, hint: str = "") -> str:
    blob = f"{url} {hint}".lower()
    if "constitution" in blob:
        return "CONSTITUTION"
    if re.search(r"/chapters/|chap\d|\bcap\.?\s*\d|chapter\s+\d", blob):
        return "CAP"
    if re.search(r"\bact\s*no\.?\s*\d|act\s+\d+\s+of|/laws/\d{4}/act|\bact\b", blob):
        if re.search(r"sro|statutory|stamp", blob) and "act" not in Path(
            urlparse(url).path
        ).stem.lower():
            pass
        else:
            return "ACT"
    if re.search(r"\bsro\b|s\.?r\.?&?o|statutory.?rules|regulation", blob):
        return "SRO"
    if "by-law" in blob or "bylaw" in blob:
        return "BYLAW"
    if re.search(r"extra-?ordinary|extraordinary", blob):
        return "EXTRAORDINARY"
    if "gazette" in blob:
        return "GAZETTE"
    if re.search(r"order|rules?|proclamation", blob):
        return "SRO"
    return ""


def _ident_from_url(url: str, hint: str = "") -> str:
    if hint:
        stem = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if stem and len(stem) > 6:
            return stem
    path = unquote(urlparse(url).path)
    # DownloadPreview/16840 -> preview_16840 (prefer hint when available)
    m = re.search(r"/DownloadPreview/(\d+)", path)
    if m:
        return f"printery_{m.group(1)}"
    stem = Path(path).stem[:160] or "doc"
    return stem[:160]


def _rank(ident: str, cat: str, url: str) -> int:
    blob = f"{ident} {cat} {url}".lower()
    if cat == "CONSTITUTION" or "constitution" in blob or "chap1-01" in blob:
        return 0
    if cat == "CAP" or "/chapters/" in blob or re.search(r"chap\d", blob):
        return 1
    if cat == "ACT" or re.search(r"\bact\b|/laws/\d{4}/act", blob):
        return 2
    if cat == "SRO" or re.search(r"\bsro\b|statutory", blob):
        return 3
    if cat == "BYLAW" or "by-law" in blob or "bylaw" in blob:
        return 4
    if cat == "EXTRAORDINARY" or "extra" in blob:
        return 5
    if cat == "GAZETTE" or "gazette" in blob:
        return 6
    return 7


def discover():
    items, seen_url, best = [], set(), {}

    def add(url, ts="", title_hint="", cat=""):
        url = _norm(url)
        if " " in url:
            return
        low = url.lower()
        is_preview = "/downloadpreview/" in low or "/productdocuments/" in low
        is_pdf = ".pdf" in low
        if not is_pdf and not is_preview:
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
    sess.headers["Accept"] = "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8"
    sess.verify = False
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    # --- Government Printery: Laws / Gazette / Extraordinary / By-Law ---
    for ptype, default_cat in PRINTERY_TYPES:
        max_pages = 80
        for pg in range(1, max_pages + 1):
            if pg == 1:
                page = f"https://printery.dominica.gov.dm/Search?ProductTypeIdFk={ptype}"
            else:
                page = (
                    f"https://printery.dominica.gov.dm/Search?"
                    f"pg={pg}&ProductTypeIdFk={ptype}"
                )
            try:
                gr = sess.get(page, timeout=45)
                if gr.status_code != 200:
                    log.warning("printery type=%s pg=%s status=%s", ptype, pg, gr.status_code)
                    break
                before = len(best)
                # title + DownloadPreview pairs inside card blocks
                for m in re.finditer(
                    r"<h3>\s*(.*?)\s*</h3>.*?DownloadPreview/(\d+)",
                    gr.text,
                    re.I | re.S,
                ):
                    tip = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                    tip = re.sub(r"\s+", " ", tip)
                    pid = m.group(2)
                    # skip spurious "Gazettes" nav heading
                    if tip.lower() in ("gazettes", "publications", ""):
                        continue
                    full = (
                        f"https://printery.dominica.gov.dm/"
                        f"ProductDocuments/DownloadPreview/{pid}"
                    )
                    cat = _category(full, tip) or default_cat
                    if default_cat == "LAWS" and not cat:
                        cat = "ACT" if re.search(r"\bact\b", tip, re.I) else "SRO"
                    if default_cat == "LAWS" and cat in ("GAZETTE",):
                        # Laws shelf sometimes mixes; trust title
                        pass
                    add(full, "", tip[:200], cat if cat != "LAWS" else (_category(full, tip) or "ACT"))
                # bare preview hrefs as fallback
                for pid in set(re.findall(r"/ProductDocuments/DownloadPreview/(\d+)", gr.text)):
                    full = (
                        f"https://printery.dominica.gov.dm/"
                        f"ProductDocuments/DownloadPreview/{pid}"
                    )
                    add(full, "", f"printery_{pid}", default_cat if default_cat != "LAWS" else "")
                log.info(
                    "printery type=%s pg=%s +%s catalog=%s",
                    ptype, pg, len(best) - before, len(best),
                )
                # stop if no next page
                pages = [int(x) for x in re.findall(
                    rf"Search\?pg=(\d+)&(?:amp;)?ProductTypeIdFk={ptype}", gr.text
                )]
                if not pages or pg >= max(pages):
                    # also break if zero new and beyond first page
                    if len(best) == before and pg > 1:
                        break
                    if not pages or pg >= max(pages):
                        break
            except Exception as exc:
                log.warning("printery type=%s pg=%s fail: %s", ptype, pg, exc)
                break

    # --- Revised Laws search on dominica.gov.dm (chapters + annual Acts/SROs) ---
    for term in LAWS_SEARCH_TERMS:
        max_pg = 100
        for pg in range(1, max_pg + 1):
            page = (
                f"https://www.dominica.gov.dm/laws-of-dominica?"
                f"page={pg}&sort=title&term={quote(term)}"
            )
            try:
                lr = sess.get(page, timeout=45)
                if lr.status_code != 200:
                    break
                before = len(best)
                for m in re.finditer(
                    r'<a[^>]+href=["\']([^"\']+\.pdf[^"\']*)["\'][^>]*>(.*?)</a>',
                    lr.text,
                    re.I | re.S,
                ):
                    href = m.group(1)
                    tip = re.sub(r"<[^>]+>", "", m.group(2)).strip()
                    tip = re.sub(r"\s+", " ", tip)
                    full = urljoin(lr.url, href)
                    if not _host_ok(full):
                        continue
                    add(full, "", tip[:200], _category(full, tip))
                log.info("laws search term=%s pg=%s catalog=%s", term, pg, len(best))
                pages = [int(x) for x in re.findall(r"page=(\d+)", lr.text)]
                if not pages or pg >= max(pages):
                    break
                if len(best) == before and pg > 1:
                    break
                # Cap letter walks early once we have a large catalog (MAX_NEW is 150)
                if len(best) > 2500 and pg >= 3:
                    break
            except Exception as exc:
                log.warning("laws search term=%s pg=%s fail: %s", term, pg, exc)
                break

    # --- CDX of official PDF endpoints ---
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
    # Prefer live DownloadPreview / laws PDFs
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
        if not title or title.startswith("printery_"):
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_dm.py",
            article_re=use_re,
            extra_meta={"fetch_method": got.get("method"), "category": cat, "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC,
        country=COUNTRY,
        source="Dominica Official Gazette (printery.dominica.gov.dm) / Revised Laws (dominica.gov.dm)",
        source_urls=[
            "https://printery.dominica.gov.dm/",
            "https://printery.dominica.gov.dm/Search",
            "https://printery.dominica.gov.dm/Gazettes",
            "https://www.dominica.gov.dm/laws-of-dominica",
            "https://www.dominica.gov.dm/laws/chapters/chap1-01.pdf",
            "https://houseofassembly.gov.dm/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (printery.dominica.gov.dm Official Gazette / "
            "Acts / S.R.&O. / By-Laws + dominica.gov.dm Revised Laws chapters + CDX)"
        ),
        notes=(
            f"Official printery.dominica.gov.dm DownloadPreview PDFs (Acts/S.R.&O./Gazettes/"
            f"Extraordinary/By-Laws) + www.dominica.gov.dm/laws chapters & annual Acts/SROs; "
            f"live-first + Wayback CDX. Prefer Constitution + Caps + Acts + SROs + Gazettes. "
            f"OCR used={ocr_used}. Skip bills/drafts/commemorative stamps. Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
