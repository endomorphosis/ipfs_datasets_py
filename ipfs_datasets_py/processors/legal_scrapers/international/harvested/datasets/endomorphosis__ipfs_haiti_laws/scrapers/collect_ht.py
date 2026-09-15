#!/usr/bin/env python3
"""Haiti: MEF Lois de Finances / Le Moniteur PDFs (mef.gouv.ht, budget.gouv.ht) + Wayback of official hosts."""
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

CC, COUNTRY, LANG = "ht", "Haiti", "fr"
SOURCE_TYPE = "le_moniteur_mef"
LICENSE = (
    "République d'Haïti — Journal officiel « Le Moniteur » / Ministère de l'Économie et des Finances "
    "(mef.gouv.ht, budget.gouv.ht). Authentic Moniteur text prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://www.mef.gouv.ht/budgets/lois)"
)
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+[0-9]+[a-zA-Z]?)\b")
log = logging.getLogger("ht")
MAX_PDF = env_int("MAX_PDF_BYTES", 8 * 1024 * 1024)
KEEP_RE = re.compile(
    r"(loi|decret|d[eé]cret|arr[eê]t[eé]|constitution|budget|finances|moniteur|"
    r"code|ordonnance|accord|trait[eé]|convention)",
    re.I,
)
SKIP_RE = re.compile(
    r"(boost|manuel|guide|lettre.?de.?cadrage|citoyen|powerpoint|pptx|"
    r"feuille.?de.?route|agenda|feuilleton|holder__)",
    re.I,
)
HOST_OK = (
    "mef.gouv.ht",
    "budget.gouv.ht",
    "parlementhaitien.ht",
    "pressesnationalesdhaiti.ht",
    "sgcm.gouv.ht",
)
SEED_PAGES = [
    "https://www.mef.gouv.ht/budgets/lois",
    "https://budget.gouv.ht/",
]
CDX_PREFIXES = [
    "mef.gouv.ht/storage/",
    "www.mef.gouv.ht/storage/",
    "mef.gouv.ht/docs/",
    "www.mef.gouv.ht/docs/",
    "budget.gouv.ht/storage/",
    "www.budget.gouv.ht/storage/",
    "parlementhaitien.ht/",
    "www.parlementhaitien.ht/",
]


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    url = url.replace("http://", "https://").replace(":80/", "/")
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h in host for h in HOST_OK)


def _ident_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    stem = Path(path).stem[:160] or "doc"
    # storage hashes alone are opaque — keep parent dirs for uniqueness
    parts = [p for p in path.split("/") if p and p != "public"]
    if len(parts) >= 2 and len(stem) <= 24:
        return ("_".join(parts[-4:]))[:160]
    return stem


def discover():
    items, seen = [], set()

    def add(url, title_hint=""):
        url = _norm(url)
        low = url.lower()
        if ".pdf" not in low:
            return
        if not _host_ok(url):
            return
        if SKIP_RE.search(low) or (title_hint and SKIP_RE.search(title_hint)):
            return
        blob = f"{low} {title_hint.lower()}"
        if not KEEP_RE.search(blob) and "storage/app/uploads" not in low:
            # MEF lois page storage PDFs are curated lois/décrets even without keyword in URL
            if "mef.gouv.ht/storage" not in low and "budget.gouv.ht/storage" not in low:
                return
        if url in seen:
            return
        seen.add(url)
        items.append((_ident_from_url(url), url, title_hint.strip()[:200]))

    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    for page in SEED_PAGES:
        try:
            r = sess.get(page, timeout=45, verify=False)
            if r.status_code != 200:
                log.warning("seed page %s -> %s", page, r.status_code)
                continue
            # href + surrounding text roughly
            for m in re.finditer(
                r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                r.text,
                re.I | re.S,
            ):
                href, inner = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
                inner = re.sub(r"\s+", " ", inner).strip()
                full = urljoin(page, href)
                if ".pdf" in full.lower():
                    add(full, inner if inner.lower() != "pdf" else "")
            for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)', r.text, re.I):
                add(urljoin(page, href))
            log.info("seed %s pdf candidates so far %s", page, len(items))
        except Exception as exc:
            log.warning("seed fail %s: %s", page, exc)

    for prefix in CDX_PREFIXES:
        for h in cdx_urls(
            prefix,
            limit=env_int("CDX_LIMIT", 1500),
            match_type="prefix",
            extra_filters=["mimetype:application/pdf"],
        ):
            orig = h.get("original") or ""
            if orig:
                add(orig)

    # Prefer constitution / loi / decret wording
    def rank(it):
        u = (it[1] + " " + it[2]).lower()
        if "constitution" in u:
            return 0
        if re.search(r"\bloi\b", u):
            return 1
        if "decret" in u or "décret" in u:
            return 2
        if "budget" in u or "finances" in u:
            return 3
        return 4

    items.sort(key=lambda it: (rank(it), it[1]))
    # dedupe by ident keeping first (higher rank)
    out, seen_id = [], set()
    for ident, url, hint in items:
        if ident in seen_id:
            continue
        seen_id.add(ident)
        out.append((ident, url, hint))
    log.info("catalog %s", len(out))
    return out


def ocr_pdf(raw: bytes) -> tuple[str, str, int]:
    os.environ.setdefault("TESSDATA_PREFIX", "/home/box/tessdata")
    ocr_pages = env_int("OCR_PAGES", 10)
    lang = "fra" if Path("/home/box/tessdata/fra.traineddata").exists() else "eng"
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


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 150)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = ocr_used = 0
    for ident, url, hint in discover():
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
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_ht.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Le Moniteur / MEF Lois de Finances",
        source_urls=["https://www.mef.gouv.ht/budgets/lois", "https://budget.gouv.ht/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (MEF lois PDFs + budget.gouv.ht + CDX of official hosts)",
        notes=f"Official MEF/budget Moniteur & finance law PDFs; Wayback of dead parlementhaitien. OCR used={ocr_used}. Not haitilibre. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
