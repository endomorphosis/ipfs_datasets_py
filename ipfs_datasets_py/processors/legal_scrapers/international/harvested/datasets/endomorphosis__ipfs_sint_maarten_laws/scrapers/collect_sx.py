#!/usr/bin/env python3
"""Sint Maarten: Afkondigingsblad (AB) + Landscourant on sintmaartengov.org.

Official-only Sint Maarten territorial law (Dutch Caribbean SX). Live SharePoint
Documents/Official Publications (AB) + Documents/National Gazette (Landscourant)
via _api + CDX of sintmaartengov.org/Documents. Prefer Landsverordening /
Landsbesluit / Ministeriële regeling / GT / Staatsregeling over Landscourant
notices. NOT Netherlands mainland wetten.nl / overheid.nl / lokaleregelgeving;
NOT French Saint-Martin (st-martin.gouv.fr). Not commercial aggregators.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json
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

CC, COUNTRY, LANG = "sx", "Sint Maarten", "nl"
SOURCE_TYPE = "sintmaartengov_afkondigingsblad"
LICENSE = (
    "Government of Sint Maarten (sintmaartengov.org) — Afkondigingsblad van "
    "Sint Maarten (Official Publication / AB) and Landscourant (National Gazette). "
    "Authentic Afkondigingsblad / Landscourant / printed official text prevails. "
    "Electronic texts informational only. Not legal advice. Not Netherlands mainland "
    "wetten.nl/BWB. Not French Saint-Martin."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://www.sintmaartengov.org/)"
)
ART = re.compile(
    r"(?im)^\s*((?:Artikel|Art\.?|HOOFDSTUK|Hoofdstuk|Afdeling|Paragraaf|"
    r"§|BIJLAGE|Bijlage|DEEL|Deel)\s+[0-9IVXLC]+[A-Za-z]?)\b"
)
log = logging.getLogger("sx")
MAX_PDF = env_int("MAX_PDF_BYTES", 12 * 1024 * 1024)

HOST_OK = (
    "sintmaartengov.org", "www.sintmaartengov.org",
    "gov.sx", "www.gov.sx",
    "overheid.sx", "www.overheid.sx",
)

SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|minutes|hansard|favicon|"
    r"vacancy|vacature|tender|questionnaire|organisational.?chart|"
    r"organizational.?chart|privacy.?policy|faqs|press.?release|speech|photo|"
    r"critical.?vacancies|public.?tenders|income.?tax.?forms|profit.?tax.?forms|"
    r"nesc.?national.?job|employment/|"
    r"voorontwerp|concept[-_]?lands|ontwerp[-_]?lands|"
    r"\.docx?$|\.jpe?g$|\.png$|\.doc$|\.css$|\.webp$|\.ico$|\.woff|\.ttf|"
    r"wetten\.overheid\.nl|wetten\.nl|/bwb/|zoek\.officielebekendmakingen|"
    r"lokaleregelgeving\.overheid|st-martin\.gouv|saint-martin\.gouv|"
    r"memorie.?van.?toelichting|_mvt\b|mvt[_ ])",
    re.I,
)
KEEP_RE = re.compile(
    r"(afkondigingsblad|\bab\b|landscourant|\blc\b|national.?gazette|"
    r"official.?publication|landsverordening|landsbesluit|lbham|\blvo?\b|\blb\b|"
    r"ministeri[eë]le.?regeling|\bmr\b|geconsolideerde|[-_]gt[-_.]|\bgt\b|"
    r"staatsregeling|rijkswet|verordening|besluit|regeling|verbeterblad)",
    re.I,
)

SP_FOLDERS = (
    ("/Documents/Official Publications", "AB"),
    ("/Documents/National Gazette", "LC"),
)
# Prefer Dutch AB originals; Translated Legislation is English — skip as pack source
CDX_PREFIXES = (
    "sintmaartengov.org/Documents/Official Publications/",
    "www.sintmaartengov.org/Documents/Official Publications/",
    "sintmaartengov.org/Documents/Official%20Publications/",
    "www.sintmaartengov.org/Documents/Official%20Publications/",
    "sintmaartengov.org/Documents/National Gazette/",
    "www.sintmaartengov.org/Documents/National%20Gazette/",
)

PDF_HREF_RE = re.compile(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', re.I)
PDF_ABS_RE = re.compile(
    r'(https?://(?:www\.)?sintmaartengov\.org/[^\s"\'<>]+\.pdf)',
    re.I,
)

LIVE_SHELVES = (
    ("https://www.sintmaartengov.org/Government/Pages/Official-Publications.aspx", "AB"),
    ("https://www.sintmaartengov.org/Government/Pages/Laws-and-National-Gazette.aspx", "LC"),
    ("https://www.sintmaartengov.org/Ministries/Departments/Pages/Legal-Affairs-and-Legislation.aspx", "AB"),
)


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if not url:
        return url
    if "&amp;" in url:
        url = url.replace("&amp;", "&")
    host = (urlparse(url).hostname or "").lower()
    if host == "www.sintmaartengov.org":
        # keep www — SharePoint often requires it; still normalize http
        pass
    if host and (host.endswith("sintmaartengov.org") or host.endswith(".sx")):
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
    if "?" in url and ".pdf" in url.lower():
        base, q = url.split("?", 1)
        if base.lower().endswith(".pdf"):
            return base
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if host.endswith("sintmaartengov.org"):
        return True
    if host.endswith("overheid.sx") or host.endswith("gov.sx"):
        return True
    # reject NL mainland / FR Saint-Martin even if linked
    if host.endswith("overheid.nl") or host.endswith("wetten.nl") or "st-martin" in host:
        return False
    return any(h == host for h in HOST_OK)


def _category(url: str, hint: str = "", shelf: str = "") -> str:
    blob = f"{url} {hint} {shelf}".lower()
    path = unquote(urlparse(url).path).lower()
    if "staatsregel" in blob or "constitut" in blob:
        return "STAATSREGELING"
    if shelf == "LC" or "national gazette" in path or "landscourant" in blob:
        if re.search(r"/official\s*publications/|\bab\s*\d{4}|afkondigings", path + blob):
            pass
        else:
            return "LANDSCOURANT"
    if "verbeterblad" in blob or "verbeter" in blob:
        return "VERBETERBLAD"
    if re.search(r"\bgt\b|geconsolideerde|[-_]gt[-_.]|gt\s*no", blob):
        if "landsverordening" in blob or re.search(r"\blvo?\b", blob):
            return "LANDSVERORDENING_GT"
        if "landsbesluit" in blob or "lbham" in blob:
            return "LANDSBESLUIT_GT"
        return "GECONSOLIDEERDE_TEKST"
    if "landsverordening" in blob or re.search(r"\blvo?\b", blob):
        return "LANDSVERORDENING"
    if "rijkswet" in blob or "rijksbesluit" in blob:
        return "RIJKSWET"
    if "landsbesluit" in blob or "lbham" in blob or re.search(r"(?:^|[^a-z])lb(?:ham|sec)?(?:[^a-z]|$)", blob):
        return "LANDSBESLUIT"
    if "ministeri" in blob or re.search(r"(?:^|[^a-z])mr(?:[^a-z]|$)|min\.?\s*reg", blob):
        return "MINISTERIELE_REGELING"
    if "regeling" in blob and "samenwerkingsregeling" not in blob:
        return "REGELING"
    if "beschikking" in blob:
        return "BESCHIKKING"
    if shelf == "AB" or "official publications" in path or re.search(r"\bab\b", blob):
        return "AFKONDIGINGSBLAD"
    if shelf == "LC":
        return "LANDSCOURANT"
    return "AFKONDIGINGSBLAD"


def _ident_from_url(url: str, hint: str = "") -> str:
    canon = _canon_pdf_url(url)
    path = unquote(urlparse(canon).path)
    stem = Path(path).stem
    blob = unquote(stem + " " + hint + " " + path)
    # strip trailing ! / (2) / (3) duplication markers for stable id
    stem_clean = re.sub(r"[!\s]+$", "", stem)
    stem_clean = re.sub(r"\s*\(\d+\)\s*$", "", stem_clean)

    # AB 2018, no. 22 / AB 2023 no 19 / AB 2010, GT No. 21 / AB2021, no. 64
    m = re.search(
        r"(?i)\bAB\s*[,_]?\s*(\d{4})\s*[,_]?\s*(?:GT\s*)?(?:no\.?|n[o°]\.?|nummer)?\s*[,_]?\s*(\d+[A-Za-z]?)",
        stem_clean + " " + hint,
    )
    if m:
        year, num = m.group(1), m.group(2).upper()
        mm = re.match(r"(\d+)([A-Za-z]?)$", num)
        if mm:
            num = str(int(mm.group(1))) + mm.group(2).upper()
        gt = "_GT" if re.search(r"(?i)\bGT\b|geconsolideerde", stem_clean + " " + hint) else ""
        return f"AB{year}_no_{num}{gt}"

    # AB without year: AB 1 Staatsregeling / AB 78 Regeling luchtwerk
    m = re.match(r"(?i)^\s*AB\s*[,_]?\s*(\d+[A-Za-z]?)\b\s*(.*)$", stem_clean)
    if m:
        num = m.group(1).upper()
        mm = re.match(r"(\d+)([A-Za-z]?)$", num)
        if mm:
            num = str(int(mm.group(1))) + mm.group(2).upper()
        rest = re.sub(r"[^\w.\-]+", "_", m.group(2) or "").strip("_")[:80]
        if rest:
            return f"AB_no_{num}_{rest}"[:160]
        return f"AB_no_{num}"

    # Landscourant: 01 Landscourant 16 Januari 2026 / 07. Landscourant 06 maart 2020
    m = re.search(
        r"(?i)(?:^|/)(?:(\d{1,2})\.?\s*)?(?:de\s+)?landscourant\s+(?:special\s+edition\s+)?(\d{1,2})\s+(\w+)\s+(\d{4})",
        stem_clean,
    )
    if m:
        ed, day, mon, year = m.group(1) or "0", m.group(2), m.group(3), m.group(4)
        return f"LC_{year}_{ed.zfill(2)}_{day.zfill(2)}_{mon}"[:160]
    if "landscourant" in stem_clean.lower() or "national gazette" in path.lower():
        rest = re.sub(r"[^\w.\-]+", "_", stem_clean).strip("_")[:120]
        return f"LC_{rest}"[:160]

    if hint:
        h = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if h and len(h) > 4:
            return h
    if stem_clean:
        return re.sub(r"[^\w.\-]+", "_", unquote(stem_clean)).strip("_")[:160]
    return ("doc_" + re.sub(r"[^\w.\-]+", "_", path)).strip("_")[:160]


def _year_from_ident(ident: str, url: str) -> int:
    m = re.search(r"(?:AB|LC|ab|lc)(\d{4})", ident) or re.search(r"(20\d{2}|19\d{2})", url + " " + ident)
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
    elif cat in ("GECONSOLIDEERDE_TEKST", "REGELING", "BESCHIKKING", "AFKONDIGINGSBLAD"):
        pri = 5
    elif cat == "VERBETERBLAD":
        pri = 7
    elif cat == "LANDSCOURANT":
        pri = 8
    else:
        pri = 6
    return (pri, -year, ident)


def _title_from_path(url: str) -> str:
    path = unquote(urlparse(_canon_pdf_url(url)).path)
    stem = Path(path.rstrip("/")).name
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    stem = re.sub(r"[!]+$", "", stem).strip()
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem).strip()
    m = re.search(
        r"(?i)\bAB\s*[,_]?\s*(\d{4})\s*[,_]?\s*(?:GT\s*)?(?:no\.?|n[o°]\.?)?\s*[,_]?\s*(\d+[A-Za-z]?)",
        stem,
    )
    if m:
        return f"AB {m.group(1)}, no. {m.group(2)}"
    return stem.replace("-", " ").replace("_", " ")[:200].strip()


def _sp_url_from_rel(server_rel: str) -> str:
    # ServerRelativeUrl like /Documents/Official Publications/AB 2018, no. 22 ....pdf
    path = quote(server_rel, safe="/")
    return "https://www.sintmaartengov.org" + path


def _session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf,application/json,*/*;q=0.8",
            "Accept-Language": "nl-SX,nl;q=0.9,en;q=0.8",
            "Referer": "https://www.sintmaartengov.org/Government/Pages/Official-Publications.aspx",
        }
    )
    sess.verify = False
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    return sess


def _list_sp_folder(sess: requests.Session, folder: str) -> list[dict]:
    """List PDF files in a SharePoint Documents folder via REST."""
    enc = quote(folder, safe="")
    # folder path itself has spaces — API wants encoded in URL path segment
    # Use single-quoted path with spaces (SharePoint accepts encoded %20)
    enc_path = quote(folder, safe="/")
    base = (
        "https://www.sintmaartengov.org/_api/web/GetFolderByServerRelativeUrl("
        f"'{enc_path}')/Files"
    )
    params = {"$select": "Name,ServerRelativeUrl,Length,TimeLastModified", "$top": "5000"}
    out = []
    url = base
    first = True
    while url:
        try:
            if first:
                r = sess.get(url, params=params, headers={"Accept": "application/json;odata=verbose"}, timeout=120)
                first = False
            else:
                r = sess.get(url, headers={"Accept": "application/json;odata=verbose"}, timeout=120)
            if r.status_code != 200:
                log.warning("sp list %s status=%s", folder, r.status_code)
                break
            data = r.json().get("d") or {}
            for it in data.get("results") or []:
                name = it.get("Name") or ""
                if not name.lower().endswith(".pdf"):
                    continue
                out.append(it)
            nxt = data.get("__next")
            url = nxt if nxt else None
        except Exception as exc:
            log.warning("sp list %s fail: %s", folder, exc)
            break
    return out


def discover():
    seen_url, best = set(), {}
    sess = _session()

    def add(url, ts="", title_hint="", cat="", shelf=""):
        url = _norm(url)
        if not url:
            return
        low = url.lower()
        if ".pdf" not in low:
            return
        if not _host_ok(url):
            return
        if re.search(
            r"wetten\.overheid\.nl|zoek\.officielebekendmakingen|wetten\.nl|"
            r"lokaleregelgeving|st-martin\.gouv|saint-martin",
            low,
        ):
            return
        # skip English translations folder
        if "/translated%20legislation/" in low or "/translated legislation/" in low:
            return
        blob = f"{low} {title_hint} {cat} {shelf}"
        if SKIP_RE.search(blob):
            return
        if not KEEP_RE.search(blob) and shelf not in ("AB", "LC"):
            return
        cat = cat or _category(url, title_hint, shelf)
        if not cat:
            cat = "AFKONDIGINGSBLAD" if shelf == "AB" else ("LANDSCOURANT" if shelf == "LC" else "AFKONDIGINGSBLAD")
        ident = _ident_from_url(url, title_hint)
        if not ident:
            return
        canon = _canon_pdf_url(url)
        if canon not in seen_url:
            seen_url.add(canon)
        row = (ident, canon, (title_hint or "").strip()[:200], cat, ts or "", shelf or "")
        prev = best.get(ident)
        if prev is None:
            best[ident] = row
        else:
            pr = _rank(prev[0], prev[3], prev[1])
            nr = _rank(row[0], row[3], row[1])
            # Prefer Official Publications over National Gazette / CDX for same id
            if nr < pr or (nr == pr and shelf == "AB" and prev[5] != "AB"):
                best[ident] = row
            elif nr == pr and (ts or "") > (prev[4] or ""):
                best[ident] = row

    # --- SharePoint REST (primary) ---
    for folder, shelf in SP_FOLDERS:
        before = len(best)
        files = _list_sp_folder(sess, folder)
        for it in files:
            rel = it.get("ServerRelativeUrl") or ""
            name = it.get("Name") or ""
            if not rel:
                continue
            full = _sp_url_from_rel(rel)
            tip = name[:-4] if name.lower().endswith(".pdf") else name
            tip = re.sub(r"[!]+$", "", tip).strip()
            tip = re.sub(r"\s*\(\d+\)\s*$", "", tip).strip()[:200]
            ts = (it.get("TimeLastModified") or "").replace("-", "").replace(":", "")[:14]
            add(full, ts, tip, shelf=shelf)
        log.info("sp %s files=%s +%s catalog=%s", shelf, len(files), len(best) - before, len(best))

    # --- live HTML shelves (rarely have direct PDF links; still probe) ---
    for base, shelf in LIVE_SHELVES:
        try:
            r = sess.get(base, timeout=90)
            if r.status_code != 200:
                log.warning("live %s status=%s", base, r.status_code)
                continue
            before = len(best)
            text = r.text or ""
            for href in PDF_HREF_RE.findall(text) + PDF_ABS_RE.findall(text):
                full = href if href.startswith("http") else urljoin(base, href)
                add(full, "", _title_from_path(full), shelf=shelf)
            log.info("shelf %s +%s catalog=%s url=%s", shelf, len(best) - before, len(best), base[-60:])
        except Exception as exc:
            log.warning("shelf %s fail: %s", base, exc)

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
                    extra_filters=["mimetype:application/pdf"],
                )
            )
            for h in hits:
                orig = h.get("original") or ""
                ts = h.get("timestamp") or ""
                if not orig or ".pdf" not in orig.lower():
                    continue
                if "sintmaartengov.org" not in orig.lower():
                    continue
                tip = _title_from_path(orig)
                shelf = "LC" if "national" in orig.lower() and "gazette" in orig.lower() else "AB"
                add(orig, ts, tip, shelf=shelf)
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
    sess.headers["Referer"] = "https://www.sintmaartengov.org/Government/Pages/Official-Publications.aspx"
    sess.headers["Accept"] = "application/pdf,application/octet-stream,text/html,*/*;q=0.8"
    url = _norm(url)
    candidates = [url]
    canon = _canon_pdf_url(url)
    if canon != url:
        candidates.append(canon)
    # www / non-www variants
    for c in list(candidates):
        if "://www.sintmaartengov.org/" in c:
            candidates.append(c.replace("://www.sintmaartengov.org/", "://sintmaartengov.org/", 1))
        elif "://sintmaartengov.org/" in c:
            candidates.append(c.replace("://sintmaartengov.org/", "://www.sintmaartengov.org/", 1))

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
    if "landscourant" in head or "national gazette" in head:
        return "LANDSCOURANT"
    if "afkondigingsblad" in head:
        return "AFKONDIGINGSBLAD"
    if "verbeterblad" in head:
        return "VERBETERBLAD"
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
                r"BESLUIT|STAATSREGELING|AFKONDIGINGSBLAD|LANDSCOURANT|PUBLICATIEBLAD)\b",
                s,
            ):
                title = s[:240]
                break
        cat = _refine_cat_from_text(cat, text, title or "")
        if cat and title and cat.lower().replace("_", " ") not in title.lower():
            if not re.search(r"\[(LANDS|AFKONDIG|PUBLICATIE|REGELING|WET|BESLUIT|STAATS|MINISTER)", title, re.I):
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
            collector="collect_sx.py",
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
            "Government of Sint Maarten (sintmaartengov.org) — Afkondigingsblad "
            "(Official Publication / AB) + Landscourant (National Gazette); "
            "Ministerie van Algemene Zaken / Juridische Zaken en Wetgeving"
        ),
        source_urls=[
            "https://www.sintmaartengov.org/Government/Pages/Official-Publications.aspx",
            "https://www.sintmaartengov.org/Government/Pages/Laws-and-National-Gazette.aspx",
            "https://www.sintmaartengov.org/Ministries/Departments/Pages/Legal-Affairs-and-Legislation.aspx",
            "https://www.sintmaartengov.org/Documents/Official%20Publications/",
            "https://www.sintmaartengov.org/Documents/National%20Gazette/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (sintmaartengov.org SharePoint Official "
            "Publications AB + National Gazette Landscourant + CDX; not NL mainland; "
            "not French Saint-Martin)"
        ),
        notes=(
            f"Official sintmaartengov.org Afkondigingsblad + Landscourant PDFs via "
            f"SharePoint REST. Prefer Landsverordening/Landsbesluit/Ministeriële "
            f"regeling/GT/Staatsregeling. Skip NL mainland wetten.nl/BWB/"
            f"lokaleregelgeving and French Saint-Martin. OCR nld+eng used={ocr_used}. "
            f"Not commercial aggregators. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
