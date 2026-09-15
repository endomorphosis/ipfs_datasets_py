#!/usr/bin/env python3
"""Saint Kitts and Nevis: lawcommission.gov.kn Revised Acts / Annual Laws + legal.gov.kn.

Official-only *.gov.kn. Law Commission revised chapters / annual Acts & S.R.O.s /
Constitution + Ministry of Justice & Legal Affairs PDFs + CDX of the same official
URLs (live SiteGround captcha falls back to Wayback of official URLs).
Not vLex / commercial aggregators. gazette.gov.kn is maintenance-mode (2026).
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
from urllib.parse import urlparse, unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text
import requests

CC, COUNTRY, LANG = "kn", "Saint Kitts and Nevis", "en"
SOURCE_TYPE = "lawcommission_gov_kn"
LICENSE = (
    "Government of Saint Christopher and Nevis — Law Commission "
    "(lawcommission.gov.kn); Ministry of Justice & Legal Affairs (legal.gov.kn); "
    "Official Gazette (gazette.gov.kn). "
    "Authentic Official Gazette / Government Printer / Law Commission text prevails. "
    "Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://lawcommission.gov.kn/)"
)
# Commonwealth drafting: Section / s. / Article
ART = re.compile(
    r"(?im)^\s*((?:Section|Article|Art\.?|SCHEDULE|Schedule)\s+[0-9]+[A-Za-z]?|"
    r"s\.\s*[0-9]+[A-Za-z]?)\b"
)
log = logging.getLogger("kn")
MAX_PDF = env_int("MAX_PDF_BYTES", 10 * 1024 * 1024)

HOST_OK = (
    "lawcommission.gov.kn",
    "www.lawcommission.gov.kn",
    "legal.gov.kn",
    "www.legal.gov.kn",
    "gazette.gov.kn",
    "www.gazette.gov.kn",
    "gov.kn",
    "www.gov.kn",
)
SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|order.?of.?the.?day|"
    r"minutes|hansard|favicon|holder__|order.?form|order-form|"
    r"vacancy|tender|questionnaire|communiqu|budget.?address|"
    r"\bbill\b|draft-|draft_|draft\s|"
    r"registering.?as.?a.?voter|electoral.?office.?listing|"
    r"objection.?hearings|parliamentary.?sittings|"
    r"application.?for.?liquor|nra.?report|"
    r"revised-edition-indices|"
    r"\.docx?$|\.jpe?g$|\.png$|\.doc$)",
    re.I,
)
KEEP_RE = re.compile(
    r"(gazette|act|acts|constitution|cap|chapter|ch-\d|statutory|"
    r"s[_ ]?r[_ ]?&?o|sro|regulation|order|rules?|proclamation|"
    r"ordinance|revised-acts|annual-laws|wp-content/documents|"
    r"law.?commission|official.?gazette)",
    re.I,
)
CDX_PREFIXES = (
    "lawcommission.gov.kn/wp-content/documents/",
    "www.lawcommission.gov.kn/wp-content/documents/",
    "legal.gov.kn/wp-content/uploads/",
    "www.legal.gov.kn/wp-content/uploads/",
    "gazette.gov.kn/wp-content/uploads/",
    "www.gazette.gov.kn/wp-content/uploads/",
)
SEED_DOCS = (
    (
        "https://lawcommission.gov.kn/wp-content/documents/Annual-Laws/"
        "The-Constitution-of-St-Christopher-and-Nevis.pdf",
        "Constitution of Saint Christopher and Nevis",
        "CONSTITUTION",
        "20231106151117",
    ),
    (
        "https://legal.gov.kn/wp-content/uploads/2020/03/Constitution-of-SKN.pdf",
        "Constitution of Saint Kitts and Nevis",
        "CONSTITUTION",
        "20210615000000",
    ),
)
LIVE_PAGES = (
    "https://lawcommission.gov.kn/laws/",
    "https://lawcommission.gov.kn/annual-laws/annual-laws-of-st-kitts-and-nevis/",
    "https://lawcommission.gov.kn/acts-of-st-kitts-nevis/revised-acts-of-st-kitts-and-nevis-as-at-31st-december-2020-supplement/",
    "https://www.legal.gov.kn/law-commission/",
    "https://gazette.gov.kn/",
)

# Chapter stem e.g. Ch-01_03-Law-Commission-Act
CH_STEM_RE = re.compile(r"(Ch-\d{2}_\d{2}N?-[-A-Za-z0-9]+)", re.I)
EDITION_RANK = (
    ("Revised-Acts-of-St-Kitts-and-Nevis-2020", 0),
    ("Revised-Acts-of-St-Kitts-and-Nevis-2017", 1),
    ("Revised-Ordinances-of-Nevis-2020", 0),
    ("Revised-Ordinances-of-Nevis-2017", 1),
    ("Revised-Acts-of-St-Kitts-and-Nevis-2009", 2),
    ("Revised-Ordinances-of-Nevis-2009", 2),
    ("Act17TOC", 3),
    ("Ord17TOC", 3),
    ("Act02and09TOC", 4),
    ("Ord02and09TOC", 4),
)


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if "?" in url and ".pdf" in url.lower():
        url = url.split("?")[0]
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("gov.kn"):
        url = url.replace("http://", "https://").replace(":80/", "/")
        if host.startswith("www.lawcommission.") or host.startswith("www.legal.") or host.startswith("www.gazette."):
            url = url.replace("://www.", "://", 1)
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h == host or host.endswith("." + h) for h in HOST_OK) or host.endswith(".gov.kn")


def _category(url: str, hint: str = "") -> str:
    blob = f"{url} {hint}".lower()
    if "constitution" in blob and "constable" not in blob and "constitutional-questions" not in blob:
        return "CONSTITUTION"
    if re.search(r"/sros?/|nevis-ordinances|/sro|s\.?r\.?&?o|\bsro\b|statutory.?rules", blob):
        if "ordinance" in blob or "nevis" in blob:
            return "ORDINANCE" if "ordinance" in blob else "SRO"
        return "SRO"
    if "ordinance" in blob or "/ord" in blob or re.search(r"ch-\d{2}_\d{2}n-", blob):
        return "ORDINANCE"
    if re.search(r"/acts?/|annual-laws|.*/act-\d|revised-acts|act\d*toc|\bact\b", blob):
        if re.search(r"ch-\d{2}_|/revised-acts/|act\d*toc", blob):
            return "CAP"
        return "ACT"
    if re.search(r"ch-\d{2}_|\bcap\.?\s*\d|chapter\s+\d", blob):
        return "CAP"
    if "gazette" in blob:
        return "GAZETTE"
    if re.search(r"regulation|order|rules?|proclamation", blob):
        return "SRO"
    return ""


def _edition_score(url: str) -> int:
    for key, score in EDITION_RANK:
        if key.lower() in url.lower():
            return score
    if "/Annual-Laws/" in url:
        return 5
    if "legal.gov.kn" in url.lower():
        return 6
    return 7


def _ident_from_url(url: str, hint: str = "") -> str:
    path = unquote(urlparse(url).path)
    blob = f"{path} {hint}".lower()
    if "constitution" in blob and "constable" not in blob and "constitutional-questions" not in blob:
        return "Constitution_of_Saint_Christopher_and_Nevis"
    m = CH_STEM_RE.search(path)
    if m:
        return m.group(1)[:160]
    stem = Path(path).stem
    # Annual Act-N-of-YEAR-...
    if re.match(r"Act-\d+-of-\d{4}", stem, re.I) or re.match(r"SRO-?", stem, re.I):
        return stem[:160]
    if hint:
        h = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if h and len(h) > 6:
            # Prefer chapter-like stems from filename over free hint when available
            if stem and len(stem) > 8 and ("Ch-" in stem or "Act-" in stem or "SRO" in stem.upper()):
                return stem[:160]
            return h
    if stem:
        return stem[:160]
    return "doc"


def _rank(ident: str, cat: str, url: str) -> int:
    blob = f"{ident} {cat} {url}".lower()
    ed = _edition_score(url)
    if cat == "CONSTITUTION" or ("constitution" in blob and "constable" not in blob):
        return (0, ed)
    if cat == "CAP" or re.search(r"ch-\d{2}_|revised-acts|act\d*toc", blob):
        return (1, ed)
    if cat == "ACT" or re.search(r"/annual-laws/.*/acts?/|act-\d+-of-\d{4}", blob):
        return (2, ed)
    if cat == "SRO" or "/sros/" in blob or re.search(r"\bsro\b", blob):
        return (3, ed)
    if cat == "ORDINANCE" or "ordinance" in blob or "nevis" in blob:
        return (4, ed)
    if cat == "GAZETTE" or "gazette" in blob:
        return (5, ed)
    return (6, ed)


def discover():
    items, seen_url, best = [], set(), {}

    def add(url, ts="", title_hint="", cat=""):
        url = _norm(url)
        if " " in url:
            return
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
        # Skip pure fee schedules / forms on legal.gov.kn unless clearly an Act
        if "legal.gov.kn" in low:
            if not re.search(
                r"constitution|\bact\b|sro|ordinance|chapter|chap\.|cap\.|"
                r"regulation|statutory",
                blob,
                re.I,
            ):
                return
            if re.search(r"fees\.pdf|forms?\.pdf|listing|registering", low):
                if "act" not in low and "sro" not in low:
                    return
        cat = cat or _category(url, title_hint)
        ident = _ident_from_url(url, title_hint)
        if url in seen_url:
            return
        seen_url.add(url)
        row = (ident, url, (title_hint or "").strip()[:200], cat, ts or "")
        prev = best.get(ident)
        if prev is None:
            best[ident] = row
            return
        if _rank(row[0], row[3], row[1]) < _rank(prev[0], prev[3], prev[1]):
            best[ident] = row
        elif _rank(row[0], row[3], row[1]) == _rank(prev[0], prev[3], prev[1]):
            if (ts or "") > (prev[4] or ""):
                best[ident] = row

    for url, hint, cat, ts in SEED_DOCS:
        add(url, ts, hint, cat)

    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    sess.headers["Accept"] = "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8"
    sess.verify = False
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    # Live shelf crawl (often SiteGround 202 / captcha — best-effort)
    for page in LIVE_PAGES:
        try:
            gr = sess.get(page, timeout=45)
            if gr.status_code != 200:
                log.warning("live page %s status=%s", page, gr.status_code)
                continue
            before = len(best)
            for m in re.finditer(
                r'href=["\']([^"\']+\.pdf[^"\']*)["\']',
                gr.text,
                re.I,
            ):
                href = m.group(1)
                from urllib.parse import urljoin
                full = urljoin(gr.url, href)
                tip = Path(unquote(urlparse(full).path)).stem.replace("-", " ").replace("_", " ")[:200]
                add(full, "", tip, _category(full, tip))
            log.info("live %s +%s catalog=%s", page[:60], len(best) - before, len(best))
        except Exception as exc:
            log.warning("live %s fail: %s", page, exc)

    # CDX of official PDF endpoints
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
                    tip = Path(unquote(urlparse(orig).path)).stem.replace("_", " ").replace("-", " ")[:200]
                    add(orig, ts, tip)
            log.info("cdx %s catalog=%s", prefix, len(best))
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


def main():
    setup_log(CC)
    t0 = utcnow()
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
        if not title or title.startswith("Ch ") or len(title) < 8:
            for line in text.splitlines():
                if len(line.strip()) > 18:
                    title = line.strip()[:240]
                    break
        if cat and title and cat.lower() not in title.lower():
            title = f"{title} [{cat}]"
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_kn.py",
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
            "Saint Kitts and Nevis Law Commission (lawcommission.gov.kn) / "
            "Ministry of Justice & Legal Affairs (legal.gov.kn)"
        ),
        source_urls=[
            "https://lawcommission.gov.kn/",
            "https://lawcommission.gov.kn/laws/",
            "https://lawcommission.gov.kn/annual-laws/annual-laws-of-st-kitts-and-nevis/",
            "https://lawcommission.gov.kn/wp-content/documents/Annual-Laws/"
            "The-Constitution-of-St-Christopher-and-Nevis.pdf",
            "https://www.legal.gov.kn/law-commission/",
            "https://gazette.gov.kn/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (lawcommission.gov.kn Revised Acts 2009/2017/2020 "
            "+ Annual Laws Acts/SROs/Nevis Ordinances + Constitution + legal.gov.kn; "
            "CDX/Wayback of official URLs; gazette.gov.kn maintenance)"
        ),
        notes=(
            f"Official lawcommission.gov.kn Revised Acts (prefer 2020) / Annual Laws "
            f"Acts & S.R.O.s / Nevis Ordinances / Constitution + legal.gov.kn Act/SRO PDFs; "
            f"live-first (SiteGround captcha common) + Wayback CDX. Prefer Constitution + "
            f"Caps + Acts + SROs. OCR used={ocr_used}. Skip bills/drafts/order-forms/"
            f"electoral listings. gazette.gov.kn was maintenance-mode. Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
