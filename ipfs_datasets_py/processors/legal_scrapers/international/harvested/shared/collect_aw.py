#!/usr/bin/env python3
"""Aruba: Afkondigingsblad van Aruba (AB) + Landscourant (LC) on gobierno.aw /
overheid.aw, PDFs on official CDN cuatro.sim-cdn.nl/arubaoverheid2858bd.

Official-only Aruba territorial law (Dutch Caribbean AW). Live year shelves
(1989–2026) + CDX of arubaoverheid CDN uploads. Prefer AB (Landsverordening /
Landsbesluit / Regeling) over LC notices. NOT Netherlands mainland wetten.nl /
overheid.nl BWB. Not commercial aggregators.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text
import requests

CC, COUNTRY, LANG = "aw", "Aruba", "nl"
SOURCE_TYPE = "gobierno_aw_afkondigingsblad"
LICENSE = (
    "Government of Aruba / Overheid van Aruba (gobierno.aw / overheid.aw) — "
    "Afkondigingsblad van Aruba (AB) and Landscourant (LC). Authentic Afkondigingsblad "
    "/ Landscourant / printed official text prevails. Not legal advice. Not Netherlands "
    "mainland wetten.nl/BWB."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://www.gobierno.aw/)"
)
# Dutch statute article markers (Papiamento rare in AB)
ART = re.compile(
    r"(?im)^\s*((?:Artikel|Art\.?|HOOFDSTUK|Hoofdstuk|Afdeling|Paragraaf|"
    r"§|BIJLAGE|Bijlage|DEEL|Deel)\s+[0-9IVXLC]+[A-Za-z]?)\b"
)
log = logging.getLogger("aw")
MAX_PDF = env_int("MAX_PDF_BYTES", 12 * 1024 * 1024)

HOST_OK = (
    "gobierno.aw", "www.gobierno.aw",
    "overheid.aw", "www.overheid.aw",
    "aruba.gov.aw", "www.aruba.gov.aw",
    "gov.aw", "www.gov.aw",
    "cuatro.sim-cdn.nl",  # official Aruba overheid CDN path only (checked in _host_ok)
)
SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|minutes|hansard|favicon|"
    r"vacancy|tender|questionnaire|organisational.?chart|organizational.?chart|"
    r"privacy.?policy|faqs|press.?release|speech|photo|vacature|"
    r"\.docx?$|\.jpe?g$|\.png$|\.doc$|\.css$|\.webp$|\.ico$|"
    r"wetten\.overheid\.nl|wetten\.nl|/bwb/|zoek\.officielebekendmakingen)",
    re.I,
)
KEEP_RE = re.compile(
    r"(afkondigingsblad|\bab\b|landscourant|\blc\b|landsverordening|landsbesluit|"
    r"regeling|staatsregeling|rijkswet|wetten|verordening|besluit|"
    r"arubaoverheid|uploads/ab|uploads/lc|gaceta|gazette|official.?journal)",
    re.I,
)
CDX_PREFIXES = (
    "cuatro.sim-cdn.nl/arubaoverheid2858bd/uploads/",
    "www.gobierno.aw/",
    "gobierno.aw/",
)
# Prefer recent AB years first (built below); also LC + archief hub
_YEARS = list(range(2026, 1988, -1))


def _ab_shelf(year: int) -> str:
    if year >= 2026:
        return f"https://www.gobierno.aw/nl/gaceta-oficial-{year}"
    return f"https://www.gobierno.aw/nl/afkondigingsbladen-{year}"


LIVE_SHELVES = (
    [("https://www.gobierno.aw/nl/gaceta-oficial-2026", "AB")]
    + [(_ab_shelf(y), "AB") for y in _YEARS if y != 2026]
    + [
        ("https://www.gobierno.aw/nl/afkondigingsbladenl-2002", "AB"),  # site typo slug
        ("https://www.gobierno.aw/nl/afkondigingsbladen-archief", "AB_ARCHIEF"),
        ("https://www.gobierno.aw/nl/landscouranten", "LC"),
        ("https://www.gobierno.aw/en/official-journals", "LC"),
        ("https://www.gobierno.aw/en/official-gazettes", "AB"),
        ("https://www.gobierno.aw/nl/afkondigingsbladen", "AB"),
    ]
)

SEED_DOCS: tuple = ()  # no separate Staatsregeling PDF seed found on gobierno CDN

PDF_HREF_RE = re.compile(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', re.I)
PDF_ABS_RE = re.compile(
    r'(https?://(?:(?:www\.)?(?:gobierno|overheid)\.aw|cuatro\.sim-cdn\.nl)/[^\s"\'<>]+\.pdf)',
    re.I,
)
AB_ID_RE = re.compile(
    r"(?i)(?:^|/)(?:ab[-_]?|AB)(\d{4})\s*(?:no\.?\s*|n[o°]\.?\s*|[-_])?(\d+[A-Za-z]?)"
)
LC_ID_RE = re.compile(
    r"(?i)(?:^|/)(?:lc[-_]?|LC)(\d{4})\s*(?:no\.?\s*|n[o°]\.?\s*|[-_])?(\d+[A-Za-z]?)"
)


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if not url:
        return url
    if "&amp;" in url:
        url = url.replace("&amp;", "&")
    # strip cache-busting ?cb= on CDN PDFs for stable id, keep for fetch candidates
    host = (urlparse(url).hostname or "").lower()
    if host in ("www.gobierno.aw", "www.overheid.aw"):
        url = url.replace("://" + host, "://" + host[4:], 1)
        host = (urlparse(url).hostname or "").lower()
    if host.endswith(".aw") or host == "cuatro.sim-cdn.nl":
        url = url.replace("http://", "https://").replace(":80/", "/")
    try:
        parts = urlparse(url)
        if parts.path and (" " in parts.path or any(ord(c) < 33 for c in parts.path)):
            segs = parts.path.split("/")
            enc = "/".join(quote(unquote(s), safe=".-_()%~[],") for s in segs)
            url = parts._replace(path=enc).geturl()
    except Exception:
        pass
    return url


def _canon_pdf_url(url: str) -> str:
    """Stable key without ?cb= for dedupe."""
    url = _norm(url)
    if "?" in url and ".pdf" in url.lower():
        base, q = url.split("?", 1)
        if base.lower().endswith(".pdf"):
            return base
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    path = (urlparse(url).path or "").lower()
    if host == "cuatro.sim-cdn.nl":
        # Only Aruba government tenant on SIM CDN
        return "arubaoverheid" in path
    if host.endswith(".gov.aw") or host in ("gov.aw", "www.gov.aw"):
        return True
    if host.endswith("gobierno.aw") or host.endswith("overheid.aw"):
        return True
    if host.endswith("aruba.gov.aw"):
        return True
    return any(h == host for h in HOST_OK)


def _category(url: str, hint: str = "", shelf: str = "") -> str:
    blob = f"{url} {hint} {shelf}".lower()
    path = unquote(urlparse(url).path).lower()
    if "staatsregel" in blob or "constitut" in blob:
        return "STAATSREGELING"
    if re.search(r"\blc\d{4}|landscourant|/lc|/uploads/lc", blob) or shelf == "LC":
        if re.search(r"\bab\d{4}|afkondigings|/uploads/ab", path):
            pass  # AB filename wins
        else:
            return "LANDSCOURANT"
    if "verbeterblad" in blob or re.search(r"no\.\d+[a-z]\b|no_\d+[a-z]", path):
        if "verbeter" in blob or re.search(r"no\.?\d+[a-z]\.pdf", path):
            # letter suffix often verbeterblad / corrigendum
            if re.search(r"no\.?\d+[a-z]", path):
                return "VERBETERBLAD"
    if "landsverordening" in blob or re.search(r"\blv\b", blob):
        return "LANDSVERORDENING"
    if "rijkswet" in blob or (re.search(r"\bwet\b", blob) and "landsbesluit" not in blob):
        if "rijkswet" in blob:
            return "RIJKSWET"
        if re.search(r"\bwet\s+van\b", hint or "", re.I):
            return "WET"
    if "landsbesluit" in blob or "lbham" in blob:
        return "LANDSBESLUIT"
    if "regeling" in blob and "samenwerkingsregeling" not in blob:
        return "REGELING"
    if "samenwerkingsregeling" in blob or "besluit van" in blob:
        return "BESLUIT"
    if shelf in ("AB", "AB_ARCHIEF") or re.search(r"/uploads/ab|\bab\d{4}", path):
        return "AFKONDIGINGSBLAD"
    if shelf == "LC":
        return "LANDSCOURANT"
    return "AFKONDIGINGSBLAD"


def _ident_from_url(url: str, hint: str = "") -> str:
    path = unquote(urlparse(_canon_pdf_url(url)).path)
    stem = Path(path).stem
    # Normalize ab2026no.16 / ab-2015no.12 / AB2026No.003 / ab2026no.5A / lc2026no.001
    m = re.search(
        r"(?i)(ab|lc)[-_]?(\d{4})\s*(?:no\.?|n[o°]\.?|[-_])?\s*(\d+[A-Za-z]?)",
        stem,
    )
    if m:
        kind, year, num = m.group(1).upper(), m.group(2), m.group(3).upper()
        # strip leading zeros on numeric part but keep letter suffix
        mm = re.match(r"(\d+)([A-Za-z]?)$", num)
        if mm:
            num = str(int(mm.group(1))) + mm.group(2).upper()
        return f"{kind}{year}_no_{num}"
    if hint:
        h = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if h and len(h) > 4:
            return h
    if stem:
        return re.sub(r"[^\w.\-]+", "_", unquote(stem)).strip("_")[:160]
    return ("doc_" + re.sub(r"[^\w.\-]+", "_", path)).strip("_")[:160]


def _year_from_ident(ident: str, url: str) -> int:
    m = re.search(r"(?:AB|LC|ab|lc)(\d{4})", ident) or re.search(r"(20\d{2}|19\d{2})", url)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return 0


def _rank(ident: str, cat: str, url: str) -> tuple:
    blob = f"{ident} {cat} {url}".lower()
    year = _year_from_ident(ident, url)
    # newer first via negative year; cat priority
    if cat == "STAATSREGELING" or "staatsregel" in blob:
        pri = 0
    elif cat == "LANDSVERORDENING":
        pri = 1
    elif cat in ("RIJKSWET", "WET"):
        pri = 2
    elif cat == "LANDSBESLUIT":
        pri = 3
    elif cat == "REGELING":
        pri = 4
    elif cat in ("BESLUIT", "AFKONDIGINGSBLAD"):
        pri = 5
    elif cat == "VERBETERBLAD":
        pri = 6
    elif cat == "LANDSCOURANT":
        pri = 7
    else:
        pri = 8
    return (pri, -year, ident)


def _title_from_path(url: str) -> str:
    path = unquote(urlparse(_canon_pdf_url(url)).path)
    stem = Path(path.rstrip("/")).name
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    m = re.search(r"(?i)(ab|lc)[-_]?(\d{4}).*?(?:no\.?|n[o°]\.?|[-_])?\s*(\d+[A-Za-z]?)", stem)
    if m:
        return f"{m.group(1).upper()} {m.group(2)} no. {m.group(3)}"
    return stem.replace("-", " ").replace("_", " ")[:200].strip()


def _session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
            "Accept-Language": "nl-AW,nl;q=0.9,en;q=0.8,pap;q=0.7",
            "Referer": "https://www.gobierno.aw/nl/gaceta-oficial-2026",
        }
    )
    sess.verify = False
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    return sess


def discover():
    seen_url, best = set(), {}
    sess = _session()

    def add(url, ts="", title_hint="", cat="", shelf=""):
        raw = url
        url = _norm(url)
        if not url:
            return
        low = url.lower()
        if ".pdf" not in low:
            return
        if not _host_ok(url):
            return
        # Hard block NL mainland
        if re.search(r"wetten\.overheid\.nl|zoek\.officielebekendmakingen|wetten\.nl", low):
            return
        blob = f"{low} {title_hint} {cat} {shelf}"
        if SKIP_RE.search(blob):
            return
        if not KEEP_RE.search(blob) and "arubaoverheid" not in low:
            return
        # Prefer arubaoverheid CDN or gobierno/overheid hosts
        cat = cat or _category(url, title_hint, shelf)
        if not cat:
            cat = "AFKONDIGINGSBLAD"
        # Refine category from filename when shelf-generic
        if cat in ("AFKONDIGINGSBLAD",) and title_hint:
            cat = _category(url, title_hint, shelf) or cat
        ident = _ident_from_url(url, title_hint)
        if not ident:
            return
        canon = _canon_pdf_url(url)
        if canon in seen_url:
            # still allow better cat/rank for same ident
            pass
        else:
            seen_url.add(canon)
        # Prefer URL with query for live CDN cache-bust if present, else canon
        fetch_url = raw if ("?cb=" in (raw or "") or "?cb=" in url) else canon
        fetch_url = _norm(fetch_url) if "?cb=" in (raw or url) else canon
        if "?cb=" in (raw or ""):
            fetch_url = _norm(raw.split("#")[0])
        row = (ident, fetch_url if fetch_url else canon, (title_hint or "").strip()[:200], cat, ts or "", shelf or "")
        prev = best.get(ident)
        if prev is None:
            best[ident] = row
        else:
            # Prefer AB over LC; prefer URL that still has live ?cb=; prefer newer ts
            pr = _rank(prev[0], prev[3], prev[1])
            nr = _rank(row[0], row[3], row[1])
            if nr < pr or (nr == pr and (ts or "") > (prev[4] or "")):
                best[ident] = row
            elif nr == pr and "?cb=" in row[1] and "?cb=" not in prev[1]:
                best[ident] = row

    for url, hint, cat in SEED_DOCS:
        add(url, "", hint, cat, shelf="SEED")

    # Limit live shelf crawl depth for speed: recent years first; older still listed
    # but catalog from all years helps CDX fill. Cap shelf GETs via env.
    max_shelves = env_int("AW_MAX_SHELVES", 40)
    for i, (base, shelf) in enumerate(LIVE_SHELVES):
        if i >= max_shelves:
            log.info("shelf cap reached at %s", max_shelves)
            break
        try:
            r = sess.get(base, timeout=90)
            if r.status_code != 200:
                log.warning("live %s status=%s", base, r.status_code)
                continue
            before = len(best)
            hrefs = PDF_HREF_RE.findall(r.text or "")
            abs_pdfs = PDF_ABS_RE.findall(r.text or "")
            # Also catch bare CDN paths in JSON/HTML
            extra = re.findall(
                r'(https?://cuatro\.sim-cdn\.nl/arubaoverheid2858bd/uploads/[^"\'\s<>]+\.pdf[^"\'\s<>]*)',
                r.text or "",
                re.I,
            )
            for href in list(hrefs) + list(abs_pdfs) + list(extra):
                full = href if href.startswith("http") else urljoin(base, href)
                tip = _title_from_path(full)
                add(full, "", tip, shelf=shelf)
            log.info("shelf %s +%s catalog=%s url=%s", shelf, len(best) - before, len(best), base[-40:])
        except Exception as exc:
            log.warning("shelf %s fail: %s", base, exc)

    lim = env_int("CDX_LIMIT", 1500)
    for prefix in CDX_PREFIXES:
        try:
            before = len(best)
            hits = list(
                cdx_urls(
                    prefix,
                    limit=lim,
                    match_type="prefix",
                    extra_filters=["mimetype:application/pdf"],
                )
            )
            for h in hits:
                orig = h.get("original") or ""
                ts = h.get("timestamp") or ""
                if not orig or ".pdf" not in orig.lower():
                    continue
                if "arubaoverheid" not in orig.lower() and "gobierno.aw" not in orig.lower() and "overheid.aw" not in orig.lower():
                    continue
                tip = _title_from_path(orig)
                add(orig, ts, tip)
            log.info("cdx %s +%s catalog=%s", prefix, len(best) - before, len(best))
        except Exception as exc:
            log.warning("cdx %s fail: %s", prefix, exc)

    items = [
        (ident, url, hint, cat, ts)
        for ident, url, hint, cat, ts, shelf in best.values()
    ]
    items.sort(key=lambda it: _rank(it[0], it[3], it[1]))
    log.info("catalog %s", len(items))
    return items


def ocr_pdf(raw: bytes) -> tuple[str, str, int]:
    os.environ.setdefault("TESSDATA_PREFIX", "/home/box/tessdata")
    ocr_pages = env_int("OCR_PAGES", 10)
    # Dutch primary; eng fallback for bilingual bits
    return extract_pdf_text(raw, enable_ocr=True, ocr_lang="nld+eng", ocr_max_pages=ocr_pages)


def fetch_pdf(url: str, wayback_ts: str = "") -> dict:
    sess = _session()
    sess.headers["Referer"] = "https://www.gobierno.aw/nl/gaceta-oficial-2026"
    sess.headers["Accept"] = "application/pdf,application/octet-stream,text/html,*/*;q=0.8"
    url = _norm(url)
    candidates = [url]
    canon = _canon_pdf_url(url)
    if canon != url:
        candidates.append(canon)
    # www / non-www gobierno
    for c in list(candidates):
        if "://www.gobierno.aw/" in c:
            candidates.append(c.replace("://www.gobierno.aw/", "://gobierno.aw/", 1))
        elif "://gobierno.aw/" in c:
            candidates.append(c.replace("://gobierno.aw/", "://www.gobierno.aw/", 1))

    seen = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        try:
            r = sess.get(cand, timeout=90, allow_redirects=True)
            body = r.content or b""
            if r.status_code == 200 and body[:4] == b"%PDF" and len(body) <= MAX_PDF:
                from world_lib import pdf_to_text

                text = pdf_to_text(body)
                if text and len(text) >= 120:
                    return {
                        "status": "success",
                        "text": text,
                        "content": body,
                        "method": "http_pdf_session",
                        "error": "",
                        "source_url": cand,
                    }
                text2, how, pages = ocr_pdf(body)
                if text2 and len(text2) >= 100:
                    return {
                        "status": "success",
                        "text": text2,
                        "content": body,
                        "method": f"ocr:{how}",
                        "error": "",
                        "source_url": cand,
                    }
        except Exception as exc:
            log.debug("session fetch fail %s: %s", cand[:80], exc)

    got = fetch_official(
        canon,
        ua=UA,
        verify=False,
        min_text=120,
        wayback_ts=wayback_ts or None,
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


def _refine_cat_from_text(cat: str, text: str, title: str) -> str:
    head = (title + "\n" + (text or "")[:2500]).lower()
    if "staatsregeling" in head:
        return "STAATSREGELING"
    if "landsverordening" in head:
        return "LANDSVERORDENING"
    if "rijkswet" in head:
        return "RIJKSWET"
    if re.search(r"\bwet van\b", head) and "landsbesluit" not in head[:400]:
        return "WET"
    if "landsbesluit" in head:
        return "LANDSBESLUIT"
    if "regeling van de minister" in head or re.search(r"\bregeling van\b", head):
        return "REGELING"
    if "verbeterblad" in head:
        return "VERBETERBLAD"
    if "landscourant" in head:
        return "LANDSCOURANT"
    return cat


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 175)
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
        # Prefer first substantive Dutch title line after AFKONDIGINGSBLAD header
        for line in text.splitlines()[:40]:
            s = line.strip()
            if re.match(
                r"(?i)^(LANDSVERORDENING|LANDSBESLUIT|REGELING|WET|RIJKSWET|BESLUIT|STAATSREGELING)\b",
                s,
            ):
                title = s[:240]
                break
        cat = _refine_cat_from_text(cat, text, title or "")
        if cat and title and cat.lower().replace("_", " ") not in title.lower():
            if not re.search(r"\[(LANDS|AFKONDIG|REGELING|WET|BESLUIT|STAATS)", title, re.I):
                title = f"{title} [{cat}]"
        src = got.get("source_url") or url
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title or ident,
            text=text,
            source_url=src,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_aw.py",
            article_re=ART,
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
        source=(
            "Overheid van Aruba / Gobierno di Aruba (gobierno.aw) — Afkondigingsblad "
            "van Aruba (AB) + Landscourant (LC); PDFs on official CDN arubaoverheid"
        ),
        source_urls=[
            "https://www.gobierno.aw/nl/gaceta-oficial-2026",
            "https://www.gobierno.aw/nl/afkondigingsbladen-archief",
            "https://www.gobierno.aw/nl/landscouranten",
            "https://www.overheid.aw/nl",
            "https://cuatro.sim-cdn.nl/arubaoverheid2858bd/uploads/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (gobierno.aw AB year shelves 1989–2026 + LC "
            "+ arubaoverheid CDN + CDX; not NL mainland)"
        ),
        notes=(
            f"Official gobierno.aw/overheid.aw Afkondigingsblad + Landscourant PDFs "
            f"via arubaoverheid CDN. Prefer Landsverordening/Landsbesluit/Regeling. "
            f"Skip NL mainland wetten.nl/BWB. OCR nld+eng used={ocr_used}. "
            f"Not commercial aggregators. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
