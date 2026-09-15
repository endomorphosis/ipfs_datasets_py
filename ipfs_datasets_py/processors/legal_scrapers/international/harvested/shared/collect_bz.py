#!/usr/bin/env python3
"""Belize: Attorney General Ministry Revised Edition + Acts/SIs (agm.gov.bz) + Press Office SI PDFs.

Official-only. nationalassembly.gov.bz is currently suspended; prefer agm.gov.bz.
Skip belizelaw.org (non-resolving / non-official). Not vLex / commercial aggregators.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, logging, os, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text
import requests

CC, COUNTRY, LANG = "bz", "Belize", "en"
SOURCE_TYPE = "agm_belize_laws"
LICENSE = (
    "Government of Belize — Attorney General's Ministry (agm.gov.bz) Revised Edition / Acts / "
    "Statutory Instruments; Press Office SI PDFs (pressoffice.gov.bz). "
    "Authentic official gazette/AGM text prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://www.agm.gov.bz/laws)"
)
# Belize Acts use Section / s. / Article patterns (common-law drafting)
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
log = logging.getLogger("bz")
MAX_PDF = env_int("MAX_PDF_BYTES", 10 * 1024 * 1024)

HOST_OK = (
    "agm.gov.bz",
    "pressoffice.gov.bz",
    "nationalassembly.gov.bz",
    "belizeparliament.bz",
    "doc.belizeparliament.bz",
)
SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|order.?of.?the.?day|"
    r"minutes|hansard|holder__|LAW-INDEX|index.?alpha|favicon)",
    re.I,
)
KEEP_RE = re.compile(
    r"(act|law|constitution|cap[_-]?|si[_-]?|statutory|instrument|subsidiary|"
    r"regulation|order|rules?)",
    re.I,
)


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    url = url.replace("http://", "https://").replace(":80/", "/")
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h in host for h in HOST_OK)


def _ident_from_url(url: str, hint: str = "") -> str:
    if hint:
        stem = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if stem:
            return stem
    path = unquote(urlparse(url).path)
    stem = Path(path).stem[:160] or "doc"
    # strip leading hash prefixes like 6aa0784753c95_
    stem2 = re.sub(r"^[0-9a-f]{8,}_", "", stem, flags=re.I)
    return (stem2 or stem)[:160]


def _rank(name: str, cat: str, url: str) -> int:
    blob = f"{name} {cat} {url}".lower()
    if "constitution" in blob:
        return 0
    if "sustantive" in blob or "substantive" in blob or re.search(r"\bcap[_\s]", blob):
        return 1
    if re.search(r"\bact\b|acts", blob) and "si" not in cat.lower():
        return 2
    if "subsidiary" in blob:
        return 3
    if "s.i" in blob or "statutory" in blob or blob.startswith("si_") or "/si_" in blob:
        return 4
    return 5


def discover():
    items, seen = [], set()

    def add(url, title_hint="", cat=""):
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
        if url in seen:
            return
        seen.add(url)
        ident = _ident_from_url(url, title_hint)
        items.append((ident, url, title_hint.strip()[:200], cat.strip()[:80]))

    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    sess.headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
    sess.headers["X-Requested-With"] = "XMLHttpRequest"
    sess.headers["Referer"] = "https://www.agm.gov.bz/laws/law_substantive"

    # Primary: AGM portalLaws catalog (Revised Edition + Acts + SIs)
    try:
        r = sess.post(
            "https://www.agm.gov.bz/api-portalLaws/",
            data={"action": 1000},
            timeout=90,
            verify=False,
        )
        data = r.json() if r.status_code == 200 else {}
        rows = data.get("data") or []
        log.info("agm portalLaws rows=%s", len(rows))
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                continue
            name, cat, html = str(row[1]), str(row[2]), str(row[4])
            m = re.search(r"href=['\"](/uploads/laws/[^'\"]+\.pdf)['\"]", html, re.I)
            if not m:
                continue
            add(urljoin("https://www.agm.gov.bz", m.group(1)), name, cat)
    except Exception as exc:
        log.warning("agm portalLaws fail: %s", exc)

    # Supplemental: Press Office SI page (live HTML)
    try:
        pr = sess.get(
            "https://www.pressoffice.gov.bz/statutory-instruments/",
            timeout=45,
            verify=False,
        )
        if pr.status_code == 200:
            for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)', pr.text, re.I):
                full = urljoin(pr.url, href)
                tip = Path(unquote(urlparse(full).path)).stem
                add(full, tip, "Press Office SI")
            log.info("pressoffice SI candidates so far %s", len(items))
    except Exception as exc:
        log.warning("pressoffice fail: %s", exc)

    # CDX fallbacks for suspended nationalassembly + AGM uploads
    for prefix in (
        "www.agm.gov.bz/uploads/laws/",
        "agm.gov.bz/uploads/laws/",
        "www.nationalassembly.gov.bz/wp-content/uploads/",
        "nationalassembly.gov.bz/wp-content/uploads/",
        "www.pressoffice.gov.bz/wp-content/uploads/",
    ):
        try:
            for h in cdx_urls(
                prefix,
                limit=env_int("CDX_LIMIT", 1500),
                match_type="prefix",
                extra_filters=["mimetype:application/pdf"],
            ):
                orig = h.get("original") or ""
                if orig:
                    add(orig)
        except Exception as exc:
            log.warning("cdx %s fail: %s", prefix, exc)

    items.sort(key=lambda it: (_rank(it[0], it[3], it[1]), it[1]))
    out, seen_id = [], set()
    for ident, url, hint, cat in items:
        if ident in seen_id:
            continue
        seen_id.add(ident)
        out.append((ident, url, hint, cat))
    log.info("catalog %s", len(out))
    return out


def ocr_pdf(raw: bytes) -> tuple[str, str, int]:
    os.environ.setdefault("TESSDATA_PREFIX", "/home/box/tessdata")
    ocr_pages = env_int("OCR_PAGES", 10)
    lang = "eng"
    return extract_pdf_text(raw, enable_ocr=True, ocr_lang=lang, ocr_max_pages=ocr_pages)


def fetch_pdf(url: str) -> dict:
    got = fetch_official(url, ua=UA, verify=False, min_text=120)
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
    for ident, url, hint, cat in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_pdf(url)
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
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_bz.py",
            article_re=use_re, extra_meta={"fetch_method": got.get("method"), "category": cat},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Attorney General's Ministry / Press Office Belize",
        source_urls=[
            "https://www.agm.gov.bz/laws",
            "https://www.agm.gov.bz/api-portalLaws/",
            "https://www.pressoffice.gov.bz/statutory-instruments/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (AGM Revised Edition/Acts/SIs + Press Office SI + CDX)",
        notes=(
            f"Official AGM portalLaws PDFs + pressoffice.gov.bz SI; nationalassembly.gov.bz suspended "
            f"(CDX fallback). OCR used={ocr_used}. Skip belizelaw.org. Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
