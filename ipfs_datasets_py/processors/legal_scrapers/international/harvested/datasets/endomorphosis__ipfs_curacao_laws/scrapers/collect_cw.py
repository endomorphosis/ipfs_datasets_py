#!/usr/bin/env python3
"""Curaçao: Publicatieblad (P.B.) + Landscourant on gobiernu.cw / overheid.cw.

Official-only Curaçao territorial law (Dutch Caribbean CW). Live gobiernu.cw
regelingen / laws CPT / Landscourant / wet-regelgeving Klappers + WP media P.B.
PDFs + CDX of gobiernu.cw/wp-content/uploads. Prefer Landsverordening /
Landsbesluit / Ministeriële regeling / geconsolideerde tekst (GT). NOT
Netherlands mainland wetten.nl / overheid.nl BWB. Not commercial aggregators.
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
from urllib.parse import quote, unquote, urljoin, urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text
import requests

CC, COUNTRY, LANG = "cw", "Curaçao", "nl"
SOURCE_TYPE = "gobiernu_cw_publicatieblad"
LICENSE = (
    "Government of Curaçao / Gobièrnu di Kòrsou (gobiernu.cw) — Publicatieblad "
    "(P.B.) and Landscourant. Authentic Publicatieblad / Landscourant / printed "
    "official text prevails. Not legal advice. Not Netherlands mainland wetten.nl/BWB."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://gobiernu.cw/)"
)
ART = re.compile(
    r"(?im)^\s*((?:Artikel|Art\.?|HOOFDSTUK|Hoofdstuk|Afdeling|Paragraaf|"
    r"§|BIJLAGE|Bijlage|DEEL|Deel)\s+[0-9IVXLC]+[A-Za-z]?)\b"
)
log = logging.getLogger("cw")
MAX_PDF = env_int("MAX_PDF_BYTES", 12 * 1024 * 1024)

HOST_OK = (
    "gobiernu.cw", "www.gobiernu.cw",
    "wjz.gobiernu.cw",
    "overheid.cw", "www.overheid.cw",
    "gov.cw", "www.gov.cw",
)

SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|minutes|hansard|favicon|"
    r"vacancy|vacature|tender|questionnaire|organisational.?chart|"
    r"organizational.?chart|privacy.?policy|faqs|press.?release|speech|photo|"
    r"voorontwerp|concept[-_]?lands|ontwerp[-_]?lands|"
    r"\.docx?$|\.jpe?g$|\.png$|\.doc$|\.css$|\.webp$|\.ico$|\.woff|\.ttf|"
    r"wetten\.overheid\.nl|wetten\.nl|/bwb/|zoek\.officielebekendmakingen|"
    r"guia-digital|huramentashon|seo_gobiernu)",
    re.I,
)
KEEP_RE = re.compile(
    r"(publicatieblad|\bp\.?\s*b\.?\b|\bpb\b|landscourant|\blc\b|"
    r"landsverordening|landsbesluit|lbham|\blvo?\b|\blb\b|"
    r"ministeri[eë]le.?regeling|\bmr\b|geconsolideerde|[-_]gt[-_.]|"
    r"staatsregeling|rijkswet|verordening|besluit|regeling|"
    r"klapper|afkondigingsblad|wettelijke.?regelingen|"
    r"tcpdf|P\.B\._|P\.B\.-|PB[-_])",
    re.I,
)
CDX_PREFIXES = (
    "gobiernu.cw/wp-content/uploads/",
    "www.gobiernu.cw/wp-content/uploads/",
    "gobiernu.cw/tcpdf/",
)

LIVE_SHELVES = (
    ("https://gobiernu.cw/nl/themas/wet-regelgeving/", "WJZ"),
    ("https://gobiernu.cw/nl/landscourant/", "LC"),
    ("https://gobiernu.cw/nl/regelingen/", "REGELINGEN"),
    ("https://gobiernu.cw/nl/themas-result/", "THEMAS"),
    ("https://gobiernu.cw/nl/documenten/", "DOCUMENTEN"),
)

MEDIA_SEARCHES = (
    "P.B.",
    "P.B",
    "GT-",
    "Landsverordening",
    "Landsbesluit",
    "Ministeriele",
    "Publicatieblad",
)

PDF_HREF_RE = re.compile(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', re.I)
PDF_ABS_RE = re.compile(
    r'(https?://(?:(?:www\.)?gobiernu\.cw|wjz\.gobiernu\.cw)/[^\s"\'<>]+\.pdf)',
    re.I,
)
TCPDF_RE = re.compile(r'(https?://(?:www\.)?gobiernu\.cw/tcpdf/\?p_id=\d+)', re.I)
TCPDF_REL_RE = re.compile(r'(?:href=["\'])?((?:https?://(?:www\.)?gobiernu\.cw)?/tcpdf/\?p_id=\d+)', re.I)


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if not url:
        return url
    if "&amp;" in url:
        url = url.replace("&amp;", "&")
    host = (urlparse(url).hostname or "").lower()
    if host in ("www.gobiernu.cw", "www.overheid.cw"):
        url = url.replace("://" + host, "://" + host[4:], 1)
        host = (urlparse(url).hostname or "").lower()
    if host and (host.endswith(".cw") or host.endswith("gobiernu.cw")):
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
    url = _norm(url)
    # tcpdf keep query (p_id is the identity)
    if "tcpdf/" in url.lower() and "p_id=" in url.lower():
        return url
    if "?" in url and ".pdf" in url.lower():
        base, q = url.split("?", 1)
        if base.lower().endswith(".pdf"):
            return base
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if host.endswith("gobiernu.cw") or host.endswith("overheid.cw"):
        return True
    if host.endswith(".gov.cw") or host in ("gov.cw", "www.gov.cw"):
        return True
    return any(h == host for h in HOST_OK)


def _category(url: str, hint: str = "", shelf: str = "") -> str:
    blob = f"{url} {hint} {shelf}".lower()
    path = unquote(urlparse(url).path).lower()
    if "staatsregel" in blob or "constitut" in blob:
        return "STAATSREGELING"
    if "klapper" in blob:
        return "KLAPPER"
    if "tcpdf" in blob or shelf == "LC" or "landscourant" in blob:
        if re.search(r"p\.?\s*b\.?|publicatieblad|/uploads/.*p\.b", blob) and "landscourant" not in blob:
            pass
        else:
            if "tcpdf" in blob or shelf == "LC" or re.search(r"landscourant|editie.?no", blob):
                return "LANDSCOURANT"
    if re.search(r"\bgt\b|geconsolideerde|[-_]gt[-_.]|gt[-_.]", blob) and (
        "landsverordening" in blob or "landsbesluit" in blob or "p.b" in blob or "pb" in path
    ):
        if "landsverordening" in blob or re.search(r"\blvo?\b", blob):
            return "LANDSVERORDENING_GT"
        if "landsbesluit" in blob or "lbham" in blob or re.search(r"\blb\b", blob):
            return "LANDSBESLUIT_GT"
        return "GECONSOLIDEERDE_TEKST"
    if "landsverordening" in blob or re.search(r"\blvo?\b", blob):
        return "LANDSVERORDENING"
    if "rijkswet" in blob:
        return "RIJKSWET"
    if "landsbesluit" in blob or "lbham" in blob or re.search(r"(?:^|[^a-z])lb(?:ham)?(?:[^a-z]|$)", blob):
        return "LANDSBESLUIT"
    if "ministeri" in blob or re.search(r"(?:^|[^a-z])mr(?:[^a-z]|$)", blob):
        return "MINISTERIELE_REGELING"
    if "beschikking" in blob:
        return "BESCHIKKING"
    if "regeling" in blob and "samenwerkingsregeling" not in blob:
        return "REGELING"
    if shelf in ("WJZ", "REGELINGEN", "THEMAS") or re.search(r"p\.?\s*b\.?|publicatieblad", blob):
        return "PUBLICATIEBLAD"
    if shelf == "LC":
        return "LANDSCOURANT"
    return "PUBLICATIEBLAD"


def _ident_from_url(url: str, hint: str = "") -> str:
    canon = _canon_pdf_url(url)
    path = unquote(urlparse(canon).path)
    stem = Path(path).stem
    qs = parse_qs(urlparse(canon).query)
    if "tcpdf" in canon.lower() and qs.get("p_id"):
        return f"LC_tcpdf_{qs['p_id'][0]}"
    # P.B. 2018 no. 54 / P.B._2018__no._54 / GT-P.B.-1998-no.-139 / PB-2025-no-187
    m = re.search(
        r"(?i)(?:P\.?\s*B\.?|PB)[-_\s]*(\d{4})[-_\s]*(?:no\.?|n[o°]\.?|[-_])?\s*(\d+[A-Za-z]?)",
        unquote(stem + " " + hint + " " + path),
    )
    if m:
        year, num = m.group(1), m.group(2).upper()
        mm = re.match(r"(\d+)([A-Za-z]?)$", num)
        if mm:
            num = str(int(mm.group(1))) + mm.group(2).upper()
        gt = "_GT" if re.search(r"(?i)(?:^|[^a-z])gt(?:[^a-z]|$)|geconsolideerde", stem + " " + hint) else ""
        return f"PB{year}_no_{num}{gt}"
    # Leading issue number: 88.-MR.-... / 206-GT.-Lb-...
    m = re.match(r"(?i)(?:PDF[-_])?(\d{1,4})[-_.\s]+(.+)$", stem)
    if m and hint:
        n = str(int(m.group(1)))
        rest = re.sub(r"[^\w.\-]+", "_", m.group(2)).strip("_")[:100]
        return f"PB_issue_{n}_{rest}"[:160]
    if m:
        n = str(int(m.group(1)))
        rest = re.sub(r"[^\w.\-]+", "_", m.group(2)).strip("_")[:120]
        return f"doc_{n}_{rest}"[:160]
    if hint:
        h = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if h and len(h) > 4:
            return h
    if stem:
        return re.sub(r"[^\w.\-]+", "_", unquote(stem)).strip("_")[:160]
    return ("doc_" + re.sub(r"[^\w.\-]+", "_", path)).strip("_")[:160]


def _year_from_ident(ident: str, url: str) -> int:
    m = re.search(r"(?:PB|pb)(\d{4})", ident) or re.search(r"(20\d{2}|19\d{2})", url + " " + ident)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return 0


def _rank(ident: str, cat: str, url: str) -> tuple:
    blob = f"{ident} {cat} {url}".lower()
    year = _year_from_ident(ident, url)
    if cat == "STAATSREGELING" or "staatsregel" in blob:
        pri = 0
    elif cat in ("LANDSVERORDENING", "LANDSVERORDENING_GT"):
        pri = 1
    elif cat in ("RIJKSWET", "WET"):
        pri = 2
    elif cat in ("LANDSBESLUIT", "LANDSBESLUIT_GT"):
        pri = 3
    elif cat == "MINISTERIELE_REGELING":
        pri = 4
    elif cat in ("GECONSOLIDEERDE_TEKST", "REGELING", "BESCHIKKING", "PUBLICATIEBLAD"):
        pri = 5
    elif cat == "KLAPPER":
        pri = 7
    elif cat == "LANDSCOURANT":
        pri = 8
    else:
        pri = 6
    return (pri, -year, ident)


def _title_from_path(url: str) -> str:
    if "tcpdf" in url.lower():
        qs = parse_qs(urlparse(url).query)
        pid = (qs.get("p_id") or [""])[0]
        return f"Landscourant tcpdf {pid}".strip()
    path = unquote(urlparse(_canon_pdf_url(url)).path)
    stem = Path(path.rstrip("/")).name
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    m = re.search(
        r"(?i)(?:P\.?\s*B\.?|PB)[-_\s]*(\d{4}).*?(?:no\.?|n[o°]\.?|[-_])?\s*(\d+[A-Za-z]?)",
        stem,
    )
    if m:
        return f"P.B. {m.group(1)} no. {m.group(2)}"
    return stem.replace("-", " ").replace("_", " ")[:200].strip()


def _session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf,application/json,*/*;q=0.8",
            "Accept-Language": "nl-CW,nl;q=0.9,en;q=0.8,pap;q=0.7",
            "Referer": "https://gobiernu.cw/nl/regelingen/",
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
        is_tcpdf = "tcpdf/" in low and "p_id=" in low
        if ".pdf" not in low and not is_tcpdf:
            return
        if not _host_ok(url):
            return
        if re.search(r"wetten\.overheid\.nl|zoek\.officielebekendmakingen|wetten\.nl", low):
            return
        blob = f"{low} {title_hint} {cat} {shelf}"
        if SKIP_RE.search(blob):
            return
        if not KEEP_RE.search(blob) and not is_tcpdf:
            return
        cat = cat or _category(url, title_hint, shelf)
        if not cat:
            cat = "PUBLICATIEBLAD"
        if cat in ("PUBLICATIEBLAD",) and title_hint:
            cat = _category(url, title_hint, shelf) or cat
        ident = _ident_from_url(url, title_hint)
        if not ident:
            return
        canon = _canon_pdf_url(url)
        if canon not in seen_url:
            seen_url.add(canon)
        fetch_url = canon
        row = (ident, fetch_url, (title_hint or "").strip()[:200], cat, ts or "", shelf or "")
        prev = best.get(ident)
        if prev is None:
            best[ident] = row
        else:
            pr = _rank(prev[0], prev[3], prev[1])
            nr = _rank(row[0], row[3], row[1])
            if nr < pr or (nr == pr and (ts or "") > (prev[4] or "")):
                best[ident] = row

    # --- live shelves ---
    max_shelves = env_int("CW_MAX_SHELVES", 20)
    # Landscourant paginated
    lc_pages = env_int("CW_LC_PAGES", 15)
    reg_pages = env_int("CW_REG_PAGES", 25)
    shelves = list(LIVE_SHELVES)
    for p in range(2, lc_pages + 1):
        shelves.append((f"https://gobiernu.cw/nl/landscourant/page/{p}/", "LC"))
    for p in range(2, reg_pages + 1):
        shelves.append((f"https://gobiernu.cw/nl/regelingen/page/{p}/", "REGELINGEN"))

    law_page_urls = []
    for i, (base, shelf) in enumerate(shelves):
        if i >= max_shelves + lc_pages + reg_pages:
            break
        try:
            r = sess.get(base, timeout=90)
            if r.status_code != 200:
                log.warning("live %s status=%s", base, r.status_code)
                continue
            before = len(best)
            text = r.text or ""
            hrefs = PDF_HREF_RE.findall(text)
            abs_pdfs = PDF_ABS_RE.findall(text)
            tcpdfs = TCPDF_RE.findall(text) + [
                urljoin(base, m) if m.startswith("/") else m
                for m in TCPDF_REL_RE.findall(text)
            ]
            for href in list(hrefs) + list(abs_pdfs) + list(tcpdfs):
                full = href if href.startswith("http") else urljoin(base, href)
                tip = _title_from_path(full)
                add(full, "", tip, shelf=shelf)
            # collect law detail pages for later PDF extraction
            for href in re.findall(r'href=["\']([^"\']+/laws/[^"\']+)["\']', text, re.I):
                full = href if href.startswith("http") else urljoin(base, href)
                if "gobiernu.cw" in full and full not in law_page_urls:
                    law_page_urls.append(full)
            log.info(
                "shelf %s +%s catalog=%s laws_queued=%s url=%s",
                shelf,
                len(best) - before,
                len(best),
                len(law_page_urls),
                base[-50:],
            )
        except Exception as exc:
            log.warning("shelf %s fail: %s", base, exc)

    # --- follow law pages for attached PDFs (capped) ---
    max_law_pages = env_int("CW_MAX_LAW_PAGES", 120)
    for i, lp in enumerate(law_page_urls[:max_law_pages]):
        try:
            r = sess.get(lp, timeout=60)
            if r.status_code != 200:
                continue
            before = len(best)
            pdfs = PDF_ABS_RE.findall(r.text or "") + PDF_HREF_RE.findall(r.text or "")
            # title from page
            tm = re.search(r"<title>([^<]+)</title>", r.text or "", re.I)
            tip = (tm.group(1).split("|")[0].strip() if tm else "")[:200]
            tip = re.sub(r"\s+", " ", tip)
            for href in pdfs:
                full = href if href.startswith("http") else urljoin(lp, href)
                if ".pdf" not in full.lower():
                    continue
                add(full, "", tip or _title_from_path(full), shelf="LAWS")
            if (i + 1) % 20 == 0:
                log.info("law pages %s/%s catalog=%s", i + 1, min(len(law_page_urls), max_law_pages), len(best))
        except Exception as exc:
            log.debug("law page fail %s: %s", lp[:80], exc)

    # --- WP REST: nl laws (recent pages) for titles + follow ---
    max_api_pages = env_int("CW_LAWS_API_PAGES", 8)
    try:
        for page in range(1, max_api_pages + 1):
            r = sess.get(
                "https://gobiernu.cw/nl/wp-json/wp/v2/laws",
                params={"per_page": 50, "page": page},
                timeout=90,
            )
            if r.status_code != 200:
                break
            laws = r.json()
            if not laws:
                break
            before = len(best)
            for law in laws:
                link = law.get("link") or ""
                title = re.sub(r"<[^>]+>", "", (law.get("title") or {}).get("rendered") or "")
                title = re.sub(r"\s+", " ", title).strip()[:200]
                if not link:
                    continue
                try:
                    hr = sess.get(link, timeout=60)
                    if hr.status_code != 200:
                        continue
                    for href in PDF_ABS_RE.findall(hr.text or "") + PDF_HREF_RE.findall(hr.text or ""):
                        full = href if href.startswith("http") else urljoin(link, href)
                        if ".pdf" not in full.lower():
                            continue
                        add(full, "", title or _title_from_path(full), shelf="LAWS_API")
                except Exception:
                    continue
            log.info("laws api page %s +%s catalog=%s", page, len(best) - before, len(best))
    except Exception as exc:
        log.warning("laws api fail: %s", exc)

    # --- WP media search (P.B. etc.) ---
    media_pages = env_int("CW_MEDIA_PAGES", 12)
    for q in MEDIA_SEARCHES:
        try:
            for page in range(1, media_pages + 1):
                r = sess.get(
                    "https://gobiernu.cw/wp-json/wp/v2/media",
                    params={
                        "search": q,
                        "per_page": 50,
                        "page": page,
                        "mime_type": "application/pdf",
                    },
                    timeout=90,
                )
                if r.status_code != 200:
                    break
                items = r.json()
                if not items:
                    break
                before = len(best)
                for it in items:
                    src = it.get("source_url") or ""
                    title = re.sub(
                        r"<[^>]+>",
                        "",
                        (it.get("title") or {}).get("rendered") or it.get("slug") or "",
                    )
                    title = re.sub(r"\s+", " ", title).strip()[:200]
                    if src:
                        add(src, "", title or _title_from_path(src), shelf="MEDIA")
                log.info("media q=%s page=%s +%s catalog=%s", q, page, len(best) - before, len(best))
                total_pages = int(r.headers.get("X-WP-TotalPages") or "1")
                if page >= total_pages:
                    break
                # Prefer first query deeply; later queries fewer pages
                if q != "P.B." and page >= 4:
                    break
        except Exception as exc:
            log.warning("media search %s fail: %s", q, exc)

    # --- landscourant CPT ---
    try:
        for page in range(1, 10):
            r = sess.get(
                "https://gobiernu.cw/wp-json/wp/v2/landscourant",
                params={"per_page": 50, "page": page},
                timeout=90,
            )
            if r.status_code != 200:
                break
            items = r.json()
            if not items:
                break
            before = len(best)
            for it in items:
                link = it.get("link") or ""
                title = re.sub(r"<[^>]+>", "", (it.get("title") or {}).get("rendered") or "")
                title = re.sub(r"\s+", " ", title).strip()[:200]
                if not link:
                    continue
                hr = sess.get(link, timeout=60)
                if hr.status_code != 200:
                    continue
                for href in TCPDF_RE.findall(hr.text or "") + TCPDF_REL_RE.findall(hr.text or ""):
                    full = href if href.startswith("http") else urljoin(link, href)
                    add(full, "", title or _title_from_path(full), cat="LANDSCOURANT", shelf="LC")
            log.info("landscourant cpt page %s +%s catalog=%s", page, len(best) - before, len(best))
            if page >= int(r.headers.get("X-WP-TotalPages") or "1"):
                break
    except Exception as exc:
        log.warning("landscourant cpt fail: %s", exc)

    # --- CDX ---
    lim = env_int("CDX_LIMIT", 1500)
    for prefix in CDX_PREFIXES:
        try:
            before = len(best)
            hits = list(
                cdx_urls(
                    prefix,
                    limit=lim,
                    match_type="prefix",
                    extra_filters=["mimetype:application/pdf"] if "tcpdf" not in prefix else None,
                )
            )
            for h in hits:
                orig = h.get("original") or ""
                ts = h.get("timestamp") or ""
                if not orig:
                    continue
                if ".pdf" not in orig.lower() and "tcpdf" not in orig.lower():
                    continue
                if "gobiernu.cw" not in orig.lower() and "overheid.cw" not in orig.lower():
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
    return extract_pdf_text(raw, enable_ocr=True, ocr_lang="nld+eng", ocr_max_pages=ocr_pages)


def fetch_pdf(url: str, wayback_ts: str = "") -> dict:
    sess = _session()
    sess.headers["Referer"] = "https://gobiernu.cw/nl/regelingen/"
    sess.headers["Accept"] = "application/pdf,application/octet-stream,text/html,*/*;q=0.8"
    url = _norm(url)
    candidates = [url]
    canon = _canon_pdf_url(url)
    if canon != url:
        candidates.append(canon)
    for c in list(candidates):
        if "://www.gobiernu.cw/" in c:
            candidates.append(c.replace("://www.gobiernu.cw/", "://gobiernu.cw/", 1))
        elif "://gobiernu.cw/" in c:
            candidates.append(c.replace("://gobiernu.cw/", "://www.gobiernu.cw/", 1))

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
        if "geconsolideerde tekst" in head or re.search(r"\bgt\b", title.lower()):
            return "LANDSVERORDENING_GT"
        return "LANDSVERORDENING"
    if "rijkswet" in head:
        return "RIJKSWET"
    if "landsbesluit" in head:
        if "geconsolideerde tekst" in head:
            return "LANDSBESLUIT_GT"
        return "LANDSBESLUIT"
    if "ministeriële regeling" in head or "ministeriele regeling" in head:
        return "MINISTERIELE_REGELING"
    if "landscourant" in head:
        return "LANDSCOURANT"
    if "klapper" in head:
        return "KLAPPER"
    if "publicatieblad" in head:
        return "PUBLICATIEBLAD"
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
        for line in text.splitlines()[:40]:
            s = line.strip()
            if re.match(
                r"(?i)^(LANDSVERORDENING|LANDSBESLUIT|MINISTERI[EË]LE REGELING|WET|RIJKSWET|"
                r"BESLUIT|STAATSREGELING|PUBLICATIEBLAD|LANDSCOURANT)\b",
                s,
            ):
                title = s[:240]
                break
        cat = _refine_cat_from_text(cat, text, title or "")
        if cat and title and cat.lower().replace("_", " ") not in title.lower():
            if not re.search(r"\[(LANDS|PUBLICATIE|REGELING|WET|BESLUIT|STAATS|MINISTER)", title, re.I):
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
            collector="collect_cw.py",
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
            "Gobièrnu di Kòrsou / Government of Curaçao (gobiernu.cw) — Publicatieblad "
            "(P.B.) + Landscourant; Wetgeving en Juridische Zaken"
        ),
        source_urls=[
            "https://gobiernu.cw/nl/regelingen/",
            "https://gobiernu.cw/nl/themas/wet-regelgeving/",
            "https://gobiernu.cw/nl/landscourant/",
            "https://gobiernu.cw/nl/themas-result/",
            "https://gobiernu.cw/wp-content/uploads/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (gobiernu.cw Publicatieblad / laws CPT / "
            "Landscourant / WJZ Klappers + WP media P.B. + CDX; not NL mainland)"
        ),
        notes=(
            f"Official gobiernu.cw Publicatieblad + Landscourant PDFs. Prefer "
            f"Landsverordening/Landsbesluit/Ministeriële regeling/GT. Skip NL mainland "
            f"wetten.nl/BWB and voorontwerp drafts. OCR nld+eng used={ocr_used}. "
            f"Not commercial aggregators. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
