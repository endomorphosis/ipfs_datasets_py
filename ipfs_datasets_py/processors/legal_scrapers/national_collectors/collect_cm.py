#!/usr/bin/env python3
"""Cameroon: official acts from Présidence (prc.cm) + Lois et Règlements SPM (spm.gov.cm)."""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, unquote, urlparse

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, html_to_text, log_failure, utcnow, write_summary
from world_lib import (
    cdx_urls,
    env_int,
    fetch_official,
    live_get,
    save_instrument,
    setup_log,
    slug_id,
)

CC, COUNTRY, LANG = "cm", "Cameroon", "fr"
SOURCE_TYPE = "prc_spm_cameroon"
LICENSE = (
    "Présidence de la République du Cameroun (prc.cm) / Services du Premier Ministre "
    "(spm.gov.cm). Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.prc.cm/)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.|Section)\s+\d+[a-zA-Z]?)\b")
PRC = "https://www.prc.cm"
SPM = "https://www.spm.gov.cm"
MAX_PDF_BYTES = 12 * 1024 * 1024  # skip oversized JO/finance PDFs in pilot
log = logging.getLogger("cm")

PRC_SEEDS = [
    ("lois", f"{PRC}/fr/actualites/actes/lois", 8),
    ("ordonnances", f"{PRC}/fr/actualites/actes/ordonnances", 8),
    ("decrets", f"{PRC}/fr/actualites/actes/decrets", 8),
    ("arretes", f"{PRC}/fr/actualites/actes/arretes", 8),
]


def _add(items, seen, ident, url, meta=None):
    if not url or url in seen:
        return
    seen.add(url)
    ident = re.sub(r"\W+", "-", (ident or "doc").strip("-"))[:160] or re.sub(r"\W+", "-", url)[-80:]
    items.append((ident, url, meta or {}))


def _slug_from_path(url: str) -> str:
    name = unquote(Path(urlparse(url).path).name)
    return re.sub(r"\W+", "-", name)[:160]


def resolve_prc_pdf(doc_or_act_url: str) -> tuple[str | None, str | None]:
    """Follow act or multimedia document page -> /files/...pdf. Returns (pdf_url, title)."""
    try:
        r = live_get(doc_or_act_url, ua=UA, verify=False, timeout=(15, 45), retries=2)
    except Exception as exc:
        log.info("resolve fail %s: %s", doc_or_act_url[:80], exc)
        return None, None
    soup = BeautifulSoup(r.text or "", "html.parser")
    title = None
    if soup.title:
        title = soup.title.get_text(strip=True).split("|")[0].strip()[:240]
    # Direct PDF embed on multimedia page
    pdfs = re.findall(r'(?:href|src)=["\']([^"\']+\.pdf)["\']', r.text or "", re.I)
    pdfs += re.findall(r'["\'](/files/[^"\']+\.pdf)["\']', r.text or "", re.I)
    for p in pdfs:
        full = urljoin(PRC, p)
        if "/files/" in full.lower() and full.lower().endswith(".pdf"):
            return full, title
    # Act page -> multimedia/documents/<id>-...
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/multimedia/documents/" in href and re.search(r"/\d+-", href):
            try:
                r2 = live_get(urljoin(PRC, href), ua=UA, verify=False, timeout=(15, 45), retries=2)
            except Exception:
                continue
            pdfs2 = re.findall(r'["\'](/files/[^"\']+\.pdf)["\']', r2.text or "", re.I)
            pdfs2 += re.findall(r'(?:href|src)=["\']([^"\']+\.pdf)["\']', r2.text or "", re.I)
            for p in pdfs2:
                full = urljoin(PRC, p)
                if "/files/" in full.lower() and full.lower().endswith(".pdf"):
                    return full, title
    return None, title


def discover_prc_actes(items, seen, *, max_pages_per: int = 12):
    """List act detail URLs from PRC category indexes; resolve PDFs lazily in main."""
    for kind, root, step in PRC_SEEDS:
        pages = env_int(f"PRC_{kind.upper()}_PAGES", max_pages_per)
        # Prefer lois / ordonnances more pages
        if kind == "lois":
            pages = env_int("PRC_LOIS_PAGES", max(pages, 20))
        elif kind == "ordonnances":
            pages = env_int("PRC_ORD_PAGES", max(pages, 8))
        elif kind in ("decrets", "arretes"):
            pages = env_int("PRC_DEC_PAGES", min(pages, 6))
        for i in range(pages):
            start = i * step
            url = root if start == 0 else f"{root}?start={start}"
            try:
                r = live_get(url, ua=UA, verify=False, timeout=(15, 50), retries=2)
            except Exception as exc:
                log.info("prc list fail %s: %s", url[:80], exc)
                break
            soup = BeautifulSoup(r.text or "", "html.parser")
            found = 0
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if f"/actualites/actes/{kind}/" not in href:
                    continue
                if href.rstrip("/").endswith(f"/{kind}"):
                    continue
                full = urljoin(PRC, href.split("?")[0])
                if full in seen:
                    continue
                title = (a.get_text(" ", strip=True) or "").strip()
                if not title or title.lower() in ("lire la suite...", "français", "english"):
                    continue
                if len(title) < 12:
                    continue
                ident = _slug_from_path(full)
                _add(
                    items,
                    seen,
                    ident,
                    full,
                    {"portal": "prc.cm", "kind": kind, "title": title, "page_url": full, "needs_pdf_resolve": True},
                )
                found += 1
            log.info("prc %s start=%s found=%s catalog=%s", kind, start, found, len(items))
            if found == 0 and i > 0:
                break


def discover_prc_multimedia(items, seen, *, max_pages: int = 40):
    """Paginate /fr/multimedia/documents (direct PDF hosts). Prefer Loi/Ordonnance titles."""
    root = f"{PRC}/fr/multimedia/documents"
    max_pages = env_int("PRC_DOCS_PAGES", max_pages)
    for i in range(max_pages):
        start = i * 10
        url = root if start == 0 else f"{root}?start={start}"
        try:
            r = live_get(url, ua=UA, verify=False, timeout=(15, 50), retries=2)
        except Exception as exc:
            log.info("prc docs fail %s: %s", url[:80], exc)
            break
        soup = BeautifulSoup(r.text or "", "html.parser")
        found = 0
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/multimedia/documents/" not in href or not re.search(r"/\d+-", href):
                continue
            title = (a.get_text(" ", strip=True) or "").strip()
            if not title or len(title) < 10:
                continue
            # Prefer substantive instruments; still allow decret/arrete for volume
            low = title.lower()
            if not any(k in low for k in ("loi", "ordonnance", "décret", "decret", "arrêté", "arrete", "code")):
                continue
            full = urljoin(PRC, href.split("?")[0])
            if full in seen:
                continue
            ident = _slug_from_path(full)
            _add(
                items,
                seen,
                ident,
                full,
                {"portal": "prc.cm_docs", "title": title, "page_url": full, "needs_pdf_resolve": True},
            )
            found += 1
        log.info("prc docs start=%s found=%s catalog=%s", start, found, len(items))
        if found == 0 and i > 2:
            break


def discover_spm(items, seen, *, max_pages: int = 25):
    """SPM Lois et Règlements — HTML full texts (older lois) + attached PDFs."""
    base = f"{SPM}/site/?q=fr/documentation/lois-et-r%C3%A8glements"
    max_pages = env_int("SPM_PAGES", max_pages)
    for page in range(max_pages):
        url = base if page == 0 else f"{base}&page={page}"
        try:
            r = live_get(url, ua=UA, verify=False, timeout=(15, 50), retries=2)
        except Exception as exc:
            log.info("spm list fail page=%s: %s", page, exc)
            break
        soup = BeautifulSoup(r.text or "", "html.parser")
        found = 0
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/content/" not in href and "q=fr/content/" not in href:
                continue
            title = (a.get_text(" ", strip=True) or "").strip()
            if not title or len(title) < 15:
                continue
            low = title.lower()
            # Skip personnel communiqués / pure nominations lists if thin; keep lois/decrets/arretes
            if not any(
                k in low
                for k in (
                    "loi",
                    "décret",
                    "decret",
                    "arrêté",
                    "arrete",
                    "ordonnance",
                    "code",
                    "constitution",
                )
            ):
                continue
            if href.startswith("http"):
                full = href
            elif href.startswith("/"):
                full = urljoin(SPM, href)
            elif href.startswith("site/"):
                full = urljoin(SPM + "/", href)
            else:
                full = urljoin(f"{SPM}/site/", href)
            full = full.replace("/site/site/", "/site/")
            if full in seen:
                continue
            # Skip obvious non-instrument person stubs
            if re.fullmatch(r"[A-ZÀÂÄÉÈÊËÎÏÔÙÛÜÇa-zàâäéèêëîïôùûüç'\-\s.]{5,60}", title) and not any(
                k in title.lower() for k in ("loi", "décret", "decret", "arrêté", "arrete", "ordonnance", "code")
            ):
                continue
            ident = re.sub(r"\W+", "-", title)[:140]
            _add(
                items,
                seen,
                ident,
                full,
                {"portal": "spm.gov.cm", "title": title, "page_url": full, "html_source": True},
            )
            found += 1
        log.info("spm page=%s found=%s catalog=%s", page, found, len(items))
        if found == 0 and page > 1:
            break


def discover_cdx(items, seen):
    """Wayback CDX of official prc.cm /files/ PDFs only (same host)."""
    limit = env_int("CDX_LIMIT", 120)
    for prefix in ("www.prc.cm/files/", "prc.cm/files/"):
        try:
            hits = cdx_urls(
                prefix,
                limit=limit,
                match_type="prefix",
                extra_filters=["mimetype:application/pdf", "statuscode:200"],
            )
        except Exception as exc:
            log.info("cdx fail %s: %s", prefix, exc)
            continue
        for h in hits:
            orig = (h.get("original") or "").replace("http://", "https://")
            if not orig or ".pdf" not in orig.lower():
                continue
            try:
                length = int(h.get("length") or 0)
            except Exception:
                length = 0
            if length and length > MAX_PDF_BYTES:
                continue
            ident = Path(urlparse(orig).path).stem[:140]
            _add(
                items,
                seen,
                ident,
                orig,
                {"portal": "prc.cm_cdx", "page_url": orig, "cdx_length": length},
            )


def discover():
    items, seen = [], set()
    # 1) SPM Lois et Règlements first (under-fetched vs PRC)
    discover_spm(items, seen, max_pages=env_int("SPM_PAGES", 40))
    spm_n = len(items)
    # 2) PRC actes (lois first via seed order)
    discover_prc_actes(items, seen)
    live_n = len(items) - spm_n
    # 3) Multimedia docs if still thin
    if len(items) < env_int("CATALOG_MIN", 200):
        discover_prc_multimedia(items, seen)
    # 4) CDX of same official PDF host
    discover_cdx(items, seen)
    log.info("catalog total=%s (spm~%s prc_actes~%s)", len(items), spm_n, live_n)
    return items



def ocr_pdf_bytes(body: bytes, *, max_pages: int = 4, dpi: int = 150) -> str:
    """OCR scanned SPM/PRC PDFs via pdftoppm + tesseract (fra+eng)."""
    import subprocess
    import tempfile

    if not body or body[:4] != b"%PDF":
        return ""
    max_pages = env_int("SPM_OCR_MAX_PAGES", max_pages)
    chunks: list[str] = []
    with tempfile.TemporaryDirectory(prefix="cm_ocr_") as td:
        pdf_path = Path(td) / "doc.pdf"
        pdf_path.write_bytes(body)
        prefix = str(Path(td) / "page")
        try:
            subprocess.run(
                ["pdftoppm", "-png", "-r", str(dpi), "-f", "1", "-l", str(max_pages), str(pdf_path), prefix],
                check=True,
                capture_output=True,
                timeout=180,
            )
        except Exception as exc:
            log.info("pdftoppm fail: %s", exc)
            return ""
        pages = sorted(Path(td).glob("page-*.png"))
        for img in pages:
            try:
                out = subprocess.run(
                    ["tesseract", str(img), "stdout", "-l", "fra", "--psm", "6"],
                    capture_output=True,
                    timeout=45,
                )
                t = (out.stdout or b"").decode("utf-8", "replace").strip()
                if t:
                    chunks.append(t)
            except Exception as exc:
                log.info("tesseract fail %s: %s", img.name, exc)
    return "\n\n".join(chunks).strip()


def fetch_spm_html(url: str) -> dict:
    """SPM content pages usually attach the act as PDF under sites/default/files/; HTML body is chrome."""
    try:
        r = live_get(url, ua=UA, verify=False, timeout=(15, 45), retries=2)
    except Exception as exc:
        return {"status": "error", "text": "", "method": "spm", "source_url": url, "error": str(exc)}
    soup = BeautifulSoup(r.text or "", "html.parser")
    pdfs = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ".pdf" in href.lower():
            pdfs.append(urljoin(url, href))
    # Prefer files under sites/default/files on spm.gov.cm
    pdfs = sorted(
        set(pdfs),
        key=lambda u: (0 if "sites/default/files" in u else 1, len(u)),
    )
    for pdf in pdfs[:3]:
        if pdf_too_large(pdf):
            continue
        got = fetch_official(pdf, ua=UA, verify=False, min_text=120, wayback=True)
        if got.get("status") == "success" and len(got.get("text") or "") >= 120:
            got["method"] = (got.get("method") or "pdf") + "+spm_attach"
            got["source_url"] = pdf
            return got
        # Scanned gazette PDFs often have no text layer — OCR when bytes available
        body = got.get("content") or b""
        if not body or body[:4] != b"%PDF":
            try:
                import requests
                from requests.packages.urllib3.exceptions import InsecureRequestWarning

                requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
                rr = requests.get(pdf, headers={"User-Agent": UA}, verify=False, timeout=(15, 90))
                if rr.status_code == 200 and rr.content[:4] == b"%PDF":
                    body = rr.content
            except Exception:
                body = b""
        if body and env_int("SPM_OCR", 1):
            ocr = ocr_pdf_bytes(body)
            if len(ocr) >= 120:
                return {
                    "status": "success",
                    "text": ocr,
                    "method": "spm_pdf_ocr",
                    "source_url": pdf,
                    "error": "",
                    "content": body,
                }
    # Fallback: HTML body fields only (exclude chrome)
    chunks = []
    for sel in (".field-name-body .field-item", ".field-name-body", "article .content", ".node-content"):
        for el in soup.select(sel):
            chunks.append(el.get_text("\n", strip=True))
    body = max(chunks, key=len) if chunks else ""
    if len(body) >= 200 and "Prime Minister" not in body[:80]:
        return {"status": "success", "text": body, "method": "spm_html", "source_url": url, "error": ""}
    # Last resort: wayback of page URL
    got = fetch_official(url, ua=UA, verify=False, min_text=400, wayback=True)
    if got.get("status") == "success":
        # Reject chrome-dominated extracts
        t = got.get("text") or ""
        if t.count("Services du Premier Ministre") >= 2 and "Article" not in t and "ARTICLE" not in t:
            return {
                "status": "error",
                "text": "",
                "method": "spm_chrome",
                "source_url": url,
                "error": "html_chrome_no_pdf",
            }
        return got
    got["error"] = (got.get("error") or "") + ";no_spm_pdf"
    return got


def pdf_too_large(url: str) -> bool:
    try:
        import requests
        from requests.packages.urllib3.exceptions import InsecureRequestWarning

        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        h = requests.head(url, timeout=(10, 20), headers={"User-Agent": UA}, verify=False, allow_redirects=True)
        cl = h.headers.get("content-length")
        if cl and int(cl) > MAX_PDF_BYTES:
            return True
    except Exception:
        pass
    return False


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    portals: dict[str, int] = {}
    catalog = discover()

    for ident, url, meta in catalog:
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue

        portal = meta.get("portal") or "unknown"
        title = (meta.get("title") or "").strip()
        fetch_url = url

        if meta.get("needs_pdf_resolve"):
            pdf_url, t2 = resolve_prc_pdf(url)
            if t2 and not title:
                title = t2
            if not pdf_url:
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": url, "reason": "no_pdf", "portal": portal})
                continue
            fetch_url = pdf_url
            if pdf_too_large(fetch_url):
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": fetch_url, "reason": "pdf_too_large", "portal": portal})
                continue
            got = fetch_official(fetch_url, ua=UA, verify=False, min_text=120, wayback=True)
        elif meta.get("html_source"):
            got = fetch_spm_html(url)
            if got.get("source_url") and got.get("source_url") != url:
                fetch_url = got["source_url"]
        else:
            if fetch_url.lower().endswith(".pdf") and pdf_too_large(fetch_url):
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": fetch_url, "reason": "pdf_too_large", "portal": portal})
                continue
            got = fetch_official(fetch_url, ua=UA, verify=False, min_text=120, wayback=True)

        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(
                CC,
                {"identifier": ident, "source_url": fetch_url, "reason": got.get("error"), "portal": portal},
            )
            continue

        if not title:
            title = next((ln.strip()[:240] for ln in text.splitlines() if len(ln.strip()) > 18), ident)

        # date guess from title / slug
        date = None
        m = re.search(r"(20\d{2}|19\d{2})[-_/ ](\d{1,2})[-_/ ](\d{1,2})", title + " " + ident)
        if m:
            date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        else:
            m2 = re.search(r"\b(20\d{2}|19\d{2})\b", title + " " + ident)
            if m2:
                date = f"{m2.group(1)}-01-01"

        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title,
            text=text,
            source_url=meta.get("page_url") or url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_cm.py",
            date=date,
            article_re=ART,
            extra_meta={
                "fetch_method": got.get("method"),
                "portal": portal,
                "pdf_url": fetch_url if fetch_url != url else None,
                "kind": meta.get("kind"),
            },
        ):
            ok += 1
            done.add(rid)
            portals[portal] = portals.get(portal, 0) + 1
            log.info("ok %s portal=%s chars=%s", ident[:70], portal, len(text))
        else:
            fail += 1

    write_summary(
        CC,
        country=COUNTRY,
        source="Présidence / Primature Cameroun (prc.cm, spm.gov.cm)",
        source_urls=[
            "https://www.prc.cm/fr/actualites/actes/lois",
            "https://www.prc.cm/fr/multimedia/documents",
            "https://www.spm.gov.cm/site/?q=fr/documentation/lois-et-r%C3%A8glements",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete (prc actes + spm lois/règlements; JO paper gazette not fully digitized)",
        notes=f"Official Cameroon acts. portals={portals}. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s portals=%s", ok, skip, fail, portals)


if __name__ == "__main__":
    main()
