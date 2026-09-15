#!/usr/bin/env python3
"""Barbados: Official Gazette / Cap Acts (barbadosparliament.com) + Government Printing Department.

Official-only. Parliament Official Gazette Part A (Acts/SIs) + Cap consolidated documents;
governmentprintery.gov.bb Online Gazette / Part A. Not vLex / commercial aggregators.
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

CC, COUNTRY, LANG = "bb", "Barbados", "en"
SOURCE_TYPE = "barbados_official_gazette"
LICENSE = (
    "Government of Barbados — Official Gazette / Laws of Barbados "
    "(barbadosparliament.com; governmentprintery.gov.bb). "
    "Authentic Official Gazette / Government Printer text prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://www.barbadosparliament.com/gazette/)"
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
log = logging.getLogger("bb")
MAX_PDF = env_int("MAX_PDF_BYTES", 10 * 1024 * 1024)

HOST_OK = (
    "barbadosparliament.com",
    "governmentprintery.gov.bb",
    "gov.bb",
)
SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|order.?of.?the.?day|"
    r"minutes|hansard|favicon|holder__|sittings?/attachments|"
    r"trademark|trade.?mark|quick_link|"
    r"Application-for-Leave|Statement-of-Travelling|Requisition|"
    r"Part[_ ]?B(?![^/]*Part[_ ]?A)|Part[_ ]?C(?![^/]*Part[_ ]?A)|"
    r"/bill_resolution/|/bills?/)",
    re.I,
)
KEEP_RE = re.compile(
    r"(gazette|part[_ ]?a|act|acts|constitution|cap|chapter|"
    r"statutory|instrument|s[_ ]?i|si[_-]|regulation|order|rules?|"
    r"/uploads/document/|/uploads/gazette/)",
    re.I,
)
CDX_PREFIXES = (
    "www.barbadosparliament.com/uploads/gazette/",
    "barbadosparliament.com/uploads/gazette/",
    "www.barbadosparliament.com/uploads/document/",
    "barbadosparliament.com/uploads/document/",
    "governmentprintery.gov.bb/",
    "www.governmentprintery.gov.bb/",
)
# Cap. 5 Financial Administration sample (known good Cap PDF on parliament)
SEED_DOCS = (
    (
        "https://www.barbadosparliament.com/uploads/document/e8358079f359d668ca8564deb9018136.pdf",
        "Financial Administration and Audit Act Cap. 5",
        "CAP",
    ),
)
LIVE_PAGES = (
    "https://www.barbadosparliament.com/gazette/",
    "https://governmentprintery.gov.bb/the-online-gazette/",
    "https://governmentprintery.gov.bb/category/part-a/",
    "https://governmentprintery.gov.bb/category/part-a/acts/",
    "https://governmentprintery.gov.bb/category/part-a/statutory-instruments/",
)


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    url = url.replace("http://", "https://").replace(":80/", "/")
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h == host or host.endswith("." + h) for h in HOST_OK)


def _category(url: str, hint: str = "") -> str:
    blob = f"{url} {hint}".lower()
    if "constitution" in blob:
        return "CONSTITUTION"
    if "/uploads/document/" in blob or re.search(r"\bcap\b|chapter", blob):
        return "CAP"
    if re.search(r"s[_\s]?i|statutory", blob):
        return "SI"
    if re.search(r"\bact", blob) or "part_a" in blob or "part a" in blob:
        return "ACT"
    if "gazette" in blob:
        return "GAZETTE"
    return ""


def _ident_from_url(url: str, hint: str = "") -> str:
    if hint:
        stem = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if stem and len(stem) > 8:
            return stem
    path = unquote(urlparse(url).path)
    stem = Path(path).stem[:160] or "doc"
    # Prefer human gazette filenames over bare hashes when available
    if re.search(r"Gazette_|Act_|Cap|Constitution", stem, re.I):
        return stem[:160]
    return stem[:160]


def _rank(ident: str, cat: str, url: str) -> int:
    blob = f"{ident} {cat} {url}".lower()
    if "constitution" in blob:
        return 0
    if cat == "CAP" or "/uploads/document/" in blob or re.search(r"\bcap\b", blob):
        return 1
    if cat == "ACT" or re.search(r"with_act|acts?_", blob):
        return 2
    if cat == "SI" or re.search(r"s_?i|statutory", blob):
        return 3
    if cat == "GAZETTE" or "part_a" in blob or "part-a" in blob:
        return 4
    return 5


def discover():
    items, seen_url, best = [], set(), {}

    def add(url, ts="", title_hint="", cat=""):
        url = _norm(url)
        low = url.lower()
        if ".pdf" not in low and "getpdf.php" not in low:
            return
        if not _host_ok(url):
            return
        blob = f"{low} {title_hint} {cat}"
        if SKIP_RE.search(blob):
            return
        # hashed Cap docs under /uploads/document/ always kept; else KEEP_RE
        if "/uploads/document/" not in low and not KEEP_RE.search(blob):
            return
        # Prefer Part A / Acts / SIs / Cap; skip pure Part B/C gazette if no Act/SI
        if "gazette" in low and re.search(r"part[_ ]?[bc]", low) and not re.search(
            r"part[_ ]?a|with_act|acts?_|s_?i", low
        ):
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
    # Live gazette / printery listing pages
    post_urls = []
    for page in LIVE_PAGES:
        try:
            r = sess.get(page, timeout=45, verify=False)
            if r.status_code != 200:
                log.warning("live %s status=%s", page, r.status_code)
                continue
            for href in re.findall(r'href=["\']([^"\']+)["\']', r.text, re.I):
                full = urljoin(r.url, href)
                low = full.lower()
                if ".pdf" in low or "getpdf.php" in low:
                    tip = Path(unquote(urlparse(full).path)).stem
                    add(full, "", tip.replace("_", " ")[:200])
                elif "governmentprintery.gov.bb" in low and re.search(
                    r"gazette-|/part-a|/acts|/statutory", low
                ):
                    post_urls.append(full)
            log.info("live %s ok; catalog so far %s", page, len(best))
        except Exception as exc:
            log.warning("live %s fail: %s", page, exc)

    # Follow a lean set of printery post pages for embedded PDFs
    seen_posts = set()
    for post in post_urls:
        post = _norm(post)
        if post in seen_posts:
            continue
        seen_posts.add(post)
        if len(seen_posts) > 40:
            break
        try:
            pr = sess.get(post, timeout=30, verify=False)
            if pr.status_code != 200:
                continue
            for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)', pr.text, re.I):
                full = urljoin(pr.url, href)
                tip = Path(unquote(urlparse(full).path)).stem
                add(full, "", tip.replace("_", " ")[:200])
            # title from post as hint if parliament mirror linked in body
            for href in re.findall(
                r'href=["\'](https?://[^"\']*barbadosparliament\.com[^"\']+\.pdf[^"\']*)',
                pr.text,
                re.I,
            ):
                add(href, "", Path(unquote(urlparse(href).path)).stem.replace("_", " ")[:200])
        except Exception as exc:
            log.warning("post %s fail: %s", post[:80], exc)

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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_bb.py",
            article_re=use_re,
            extra_meta={"fetch_method": got.get("method"), "category": cat, "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Barbados Official Gazette / Parliament / Government Printery",
        source_urls=[
            "https://www.barbadosparliament.com/gazette/",
            "https://www.barbadosparliament.com/uploads/gazette/",
            "https://www.barbadosparliament.com/uploads/document/",
            "https://governmentprintery.gov.bb/the-online-gazette/",
            "https://governmentprintery.gov.bb/category/part-a/acts/",
            "https://governmentprintery.gov.bb/category/part-a/statutory-instruments/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Parliament Gazette Part A Acts/SIs + Cap documents + Printery + CDX)",
        notes=(
            f"Official barbadosparliament.com Gazette/Cap PDFs + governmentprintery.gov.bb Part A; "
            f"live-first + Wayback CDX. Prefer Constitution + Cap Acts + Gazette Acts/SIs. "
            f"OCR used={ocr_used}. Skip Part B/C fluff, sittings, bills. Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
